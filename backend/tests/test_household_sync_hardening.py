# -*- coding: utf-8 -*-
"""Synken under press: samtidighet, gammal revision, återkomst och utträde.

De vanliga hushållstesterna visar att synken fungerar. De här visar att den
inte GÅR SÖNDER när verkligheten är stökig - två personer i samma butik, en
telefon som legat i fickan, ett svar som kom i fel ordning, och en medlem
som kastas ut medan appen står öppen.

Regeln som allt vilar på: en skrivning rör EN rad och stämplar den med en ny
revision. Ingen väg skickar hela listan, så det finns aldrig en gammal kopia
som kan skriva över en nyare.
"""

import concurrent.futures
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.household import (  # noqa: E402
    ALREADY_HAVE, HouseholdStore, NEED_TO_BUY, NotAMemberError, PURCHASED, item_key,
)


class SyncHardeningTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.store = HouseholdStore(Path(self._tmp.name) / "household.db")
        self.addCleanup(self.store.close)
        self.adam, self.sara, self.stranger = 1, 2, 99
        household = self.store.create_household(self.adam, "Familjen From")
        self.household_id = household["id"]
        invite = self.store.create_invite(self.household_id, self.adam)
        self.store.accept_invite(invite["token"], self.sara)

    def _add(self, name, user=None):
        return self.store.upsert_shopping_item(self.household_id, user or self.adam, {"name": name})

    # ---- två samtidiga ändringar ----------------------------------------

    def test_two_members_changing_different_rows_keep_both_changes(self):
        """Adam markerar mjölken köpt, Sara kaffet som hemma. Ingen av
        ändringarna får försvinna."""
        milk, coffee = self._add("Mjölk"), self._add("Kaffe")
        baseline = self.store.revision(self.household_id)
        self.store.set_item_status(self.household_id, self.adam, milk["key"], PURCHASED)
        self.store.set_item_status(self.household_id, self.sara, coffee["key"], ALREADY_HAVE)
        changed = {row["name"]: row["status"]
                   for row in self.store.sync(self.household_id, self.adam, baseline)["shopping"]}
        self.assertEqual(changed, {"Mjölk": PURCHASED, "Kaffe": ALREADY_HAVE})

    def test_the_same_row_changed_by_both_ends_on_one_answer_not_a_lost_row(self):
        """Samma vara, två personer, nästan samtidigt. En av dem vinner -
        det är oundvikligt - men raden måste finnas kvar och ha EN av de två
        statusarna, aldrig försvinna eller bli något tredje."""
        milk = self._add("Mjölk")
        self.store.set_item_status(self.household_id, self.adam, milk["key"], PURCHASED)
        self.store.set_item_status(self.household_id, self.sara, milk["key"], ALREADY_HAVE)
        rows = self.store.shopping_items(self.household_id, self.adam)
        self.assertEqual(len(rows), 1)
        self.assertIn(rows[0]["status"], (PURCHASED, ALREADY_HAVE))

    def test_parallel_writes_from_both_members_all_survive(self):
        """Trådat på riktigt: tjugo skrivningar från två medlemmar samtidigt.
        Revisionsräknaren är läs-ändra-skriv, så utan låset kan två rader få
        samma revision och den ena aldrig synas i en sync 'sedan N'."""
        names = [f"Vara {index}" for index in range(20)]
        errors = []

        def add(index):
            try:
                user = self.adam if index % 2 == 0 else self.sara
                self.store.upsert_shopping_item(self.household_id, user, {"name": names[index]})
            except Exception as error:      # pragma: no cover - felet ÄR resultatet
                errors.append(error)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add, range(len(names))))
        self.assertEqual(errors, [])
        stored = {row["name"] for row in self.store.shopping_items(self.household_id, self.adam)}
        self.assertEqual(stored, set(names))

    def test_every_row_has_a_distinct_revision_so_none_hides_in_a_delta(self):
        """Två rader med samma revision betyder att en av dem aldrig kommer
        med i en sync 'sedan N' - den blir osynlig för den andra telefonen."""
        for index in range(12):
            self._add(f"Vara {index}")
        revisions = [row["revision"] for row in self.store.shopping_items(self.household_id, self.adam)]
        self.assertEqual(len(revisions), len(set(revisions)))

    # ---- gammal revision --------------------------------------------------

    def test_asking_from_an_old_revision_returns_everything_since(self):
        """Telefonen har legat i fickan och ligger tio ändringar efter."""
        first = self.store.revision(self.household_id)
        for index in range(10):
            self._add(f"Vara {index}")
        delta = self.store.sync(self.household_id, self.sara, first)
        self.assertEqual(len(delta["shopping"]), 10)

    def test_asking_from_revision_zero_returns_the_whole_household(self):
        self._add("Mjölk")
        self.store.upsert_inventory_item(self.household_id, self.adam, {"name": "Ris"})
        self.store.set_doc(self.household_id, self.adam, "week", {"weekPlan": ["tacos"]})
        full = self.store.sync(self.household_id, self.sara, 0)
        self.assertIsNotNone(full["household"])
        self.assertEqual(len(full["shopping"]), 1)
        self.assertEqual(len(full["inventory"]), 1)
        self.assertIn("week", full["docs"])

    def test_asking_from_a_future_revision_returns_nothing_rather_than_everything(self):
        """En klient med en revision servern aldrig delat ut (bytt databas,
        återställd backup) ska få tomt - inte hela hushållet, och absolut
        inte ett fel."""
        self._add("Mjölk")
        ahead = self.store.sync(self.household_id, self.adam, 999_999)
        self.assertEqual(ahead["shopping"], [])
        self.assertEqual(ahead["inventory"], [])

    def test_a_negative_or_junk_revision_is_treated_as_a_full_sync(self):
        self._add("Mjölk")
        for since in (-5, None, "abc", ""):
            payload = self.store.sync(self.household_id, self.adam, since)
            self.assertEqual(len(payload["shopping"]), 1, since)

    # ---- offline och återkomst -------------------------------------------

    def test_a_member_returning_after_offline_changes_sees_exactly_the_gap(self):
        """Sara var offline medan Adam handlade. Vid återkomst ska hon få
        precis det som hänt - inte allt om igen, och inte för lite."""
        seen = self.store.revision(self.household_id)
        milk, coffee = self._add("Mjölk"), self._add("Kaffe")
        self.store.set_item_status(self.household_id, self.adam, milk["key"], PURCHASED)
        back = self.store.sync(self.household_id, self.sara, seen)
        names = {row["name"]: row["status"] for row in back["shopping"]}
        self.assertEqual(names, {"Mjölk": PURCHASED, "Kaffe": NEED_TO_BUY})
        # ...och nästa hämtning direkt efteråt är tom.
        self.assertEqual(self.store.sync(self.household_id, self.sara, back["revision"])["shopping"], [])

    def test_changes_made_while_offline_land_when_they_are_replayed(self):
        """Adams telefon skickar sin ändring först när täckningen kommer
        tillbaka. Den ska landa som vilken annan skrivning som helst, även
        om Sara hunnit ändra andra rader under tiden."""
        milk, coffee = self._add("Mjölk"), self._add("Kaffe")
        self.store.set_item_status(self.household_id, self.sara, coffee["key"], ALREADY_HAVE)
        # Adams fördröjda skrivning:
        self.store.set_item_status(self.household_id, self.adam, milk["key"], PURCHASED)
        statuses = {row["name"]: row["status"]
                    for row in self.store.shopping_items(self.household_id, self.sara)}
        self.assertEqual(statuses, {"Mjölk": PURCHASED, "Kaffe": ALREADY_HAVE})

    def test_two_devices_on_the_same_account_share_one_household_view(self):
        """Samma användare, två telefoner. Båda är samma medlem och ska se
        samma sak - hushållet hänger på kontot, inte på enheten."""
        phone_a = self.store.sync(self.household_id, self.adam, 0)
        self._add("Mjölk")
        phone_b = self.store.sync(self.household_id, self.adam, phone_a["revision"])
        self.assertEqual([row["name"] for row in phone_b["shopping"]], ["Mjölk"])
        # Den andra telefonens skrivning syns för den första.
        self.store.set_item_status(self.household_id, self.adam, item_key("Mjölk"), PURCHASED)
        self.assertEqual(self.store.shopping_items(self.household_id, self.adam)[0]["status"], PURCHASED)

    # ---- utträde medan appen är öppen -------------------------------------

    def test_a_member_removed_mid_session_loses_access_on_the_next_sync(self):
        """Saras app står öppen när Adam tar bort henne. Nästa hämtning ska
        neka - inte fortsätta leverera familjens data ur en cache."""
        self._add("Mjölk")
        seen = self.store.revision(self.household_id)
        self.store.remove_member(self.household_id, self.adam, self.sara)
        with self.assertRaises(NotAMemberError):
            self.store.sync(self.household_id, self.sara, seen)

    def test_a_member_who_left_cannot_write_with_a_stale_view(self):
        """Sara lämnade från en annan enhet men hennes öppna app tror att hon
        är kvar. Skrivningen måste nekas."""
        milk = self._add("Mjölk")
        self.store.leave(self.household_id, self.sara)
        with self.assertRaises(NotAMemberError):
            self.store.set_item_status(self.household_id, self.sara, milk["key"], PURCHASED)
        self.assertEqual(self.store.shopping_items(self.household_id, self.adam)[0]["status"], NEED_TO_BUY)

    def test_the_household_keeps_working_for_the_others_after_a_removal(self):
        self._add("Mjölk")
        self.store.remove_member(self.household_id, self.adam, self.sara)
        self.store.upsert_shopping_item(self.household_id, self.adam, {"name": "Kaffe"})
        names = {row["name"] for row in self.store.shopping_items(self.household_id, self.adam)}
        self.assertEqual(names, {"Mjölk", "Kaffe"})

    def test_rejoining_after_leaving_starts_from_a_full_sync(self):
        """Sara går med igen. Hennes gamla revision är meningslös nu, men
        en full hämtning ska ge henne hela hushållet - inte en tom vy."""
        self._add("Mjölk")
        self.store.leave(self.household_id, self.sara)
        invite = self.store.create_invite(self.household_id, self.adam)
        self.store.accept_invite(invite["token"], self.sara)
        full = self.store.sync(self.household_id, self.sara, 0)
        self.assertEqual([row["name"] for row in full["shopping"]], ["Mjölk"])


if __name__ == "__main__":
    unittest.main()
