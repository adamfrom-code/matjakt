# -*- coding: utf-8 -*-
"""Hushållslagret: behörighet, revisioner och de fyra statusarna.

Tyngdpunkten ligger på §24 i kravet - att ingen kan läsa eller skriva ett
annat hushålls data genom att byta ut ett id - och på §6, att "köpt" och
"har hemma" är två olika saker som inte får smälta samman.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.household import (  # noqa: E402
    ALREADY_HAVE, HouseholdError, HouseholdStore, NEED_TO_BUY, NotAMemberError,
    PURCHASED, REMOVED, item_key,
)
from services.household.store import MAX_MEMBERS  # noqa: E402


class HouseholdStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.store = HouseholdStore(Path(self._tmp.name) / "household.db")
        self.addCleanup(self.store.close)
        self.adam, self.sara, self.stranger = 1, 2, 99

    def _family(self):
        household = self.store.create_household(self.adam, "Familjen From")
        invite = self.store.create_invite(household["id"], self.adam)
        self.store.accept_invite(invite["token"], self.sara)
        return household["id"]


class MembershipTest(HouseholdStoreTestCase):
    def test_creator_becomes_admin_and_only_member(self):
        household = self.store.create_household(self.adam, "Familjen From")
        self.assertEqual(household["name"], "Familjen From")
        self.assertEqual(household["role"], "admin")
        self.assertEqual([m["userId"] for m in household["members"]], [self.adam])

    def test_a_user_belongs_to_at_most_one_household(self):
        self.store.create_household(self.adam, "Familjen From")
        with self.assertRaises(HouseholdError):
            self.store.create_household(self.adam, "Ett till")

    def test_household_needs_a_name(self):
        with self.assertRaises(HouseholdError):
            self.store.create_household(self.adam, "   ")

    def test_household_id_for_user_is_none_without_a_household(self):
        self.assertIsNone(self.store.household_id_for_user(self.stranger))

    def test_rename_is_admin_only(self):
        household_id = self._family()
        with self.assertRaises(HouseholdError):
            self.store.rename_household(household_id, self.sara, "Familjen Sara")
        renamed = self.store.rename_household(household_id, self.adam, "Familjen From & Sara")
        self.assertEqual(renamed["name"], "Familjen From & Sara")

    def test_member_can_leave_and_loses_access(self):
        household_id = self._family()
        self.store.leave(household_id, self.sara)
        self.assertIsNone(self.store.household_id_for_user(self.sara))
        with self.assertRaises(NotAMemberError):
            self.store.sync(household_id, self.sara, 0)
        # Adam har kvar hushållet - gemensam data följer inte med den som går.
        self.assertEqual(self.store.household_for(household_id, self.adam)["name"], "Familjen From")

    def test_last_member_leaving_removes_the_household_and_its_data(self):
        household_id = self._family()
        self.store.upsert_shopping_item(household_id, self.adam, {"name": "Mjölk"})
        self.store.leave(household_id, self.sara)
        self.store.leave(household_id, self.adam)
        self.assertEqual(self.store.revision(household_id), 0)
        with self.assertRaises(NotAMemberError):
            self.store.household_for(household_id, self.adam)

    def test_admin_leaving_hands_the_role_to_someone_else(self):
        household_id = self._family()
        self.store.leave(household_id, self.adam)
        self.assertEqual(self.store.household_for(household_id, self.sara)["role"], "admin")

    def test_admin_can_remove_a_member(self):
        household_id = self._family()
        self.store.remove_member(household_id, self.adam, self.sara)
        with self.assertRaises(NotAMemberError):
            self.store.sync(household_id, self.sara, 0)

    def test_member_cannot_remove_the_admin(self):
        household_id = self._family()
        with self.assertRaises(HouseholdError):
            self.store.remove_member(household_id, self.sara, self.adam)

    def test_admin_cannot_remove_themselves_through_remove_member(self):
        household_id = self._family()
        with self.assertRaises(HouseholdError):
            self.store.remove_member(household_id, self.adam, self.adam)

    def test_household_is_capped(self):
        household = self.store.create_household(self.adam, "Stora familjen")
        for user_id in range(100, 100 + MAX_MEMBERS - 1):
            invite = self.store.create_invite(household["id"], self.adam)
            self.store.accept_invite(invite["token"], user_id)
        with self.assertRaises(HouseholdError):
            self.store.create_invite(household["id"], self.adam)

    def test_forget_user_keeps_shared_data_for_the_others(self):
        household_id = self._family()
        self.store.upsert_shopping_item(household_id, self.sara, {"name": "Kaffe"})
        self.store.forget_user(self.sara)
        names = [item["name"] for item in self.store.shopping_items(household_id, self.adam)]
        self.assertEqual(names, ["Kaffe"])
        self.assertEqual([m["userId"] for m in self.store.household_for(household_id, self.adam)["members"]],
                         [self.adam])

    def test_forget_user_deletes_a_solo_household(self):
        household = self.store.create_household(self.adam, "Ensam")
        self.store.forget_user(self.adam)
        self.assertEqual(self.store.revision(household["id"]), 0)


class ProfileTest(HouseholdStoreTestCase):
    def test_each_member_has_their_own_profile(self):
        household_id = self._family()
        self.store.set_profile(household_id, self.adam, display_name="Adam",
                               profile={"spice": "stark"})
        self.store.set_profile(household_id, self.sara, display_name="Sara",
                               profile={"diet": "vegetarisk", "allergies": ["Nötter"]})
        members = {m["userId"]: m for m in self.store.household_for(household_id, self.adam)["members"]}
        self.assertEqual(members[self.adam]["profile"], {"spice": "stark"})
        self.assertEqual(members[self.sara]["profile"]["diet"], "vegetarisk")
        self.assertEqual(members[self.sara]["displayName"], "Sara")

    def test_profile_fields_are_whitelisted(self):
        household_id = self._family()
        self.store.set_profile(household_id, self.adam,
                               profile={"spice": "atomisk", "hemligt": "x" * 50, "child": 1})
        member = next(m for m in self.store.household_for(household_id, self.adam)["members"]
                      if m["userId"] == self.adam)
        self.assertNotIn("hemligt", member["profile"])
        self.assertNotIn("spice", member["profile"])   # "atomisk" är inte en giltig nivå
        self.assertIs(member["profile"]["child"], True)

    def test_a_non_member_cannot_write_a_profile(self):
        household_id = self._family()
        with self.assertRaises(NotAMemberError):
            self.store.set_profile(household_id, self.stranger, display_name="Inkräktare")


class InviteTest(HouseholdStoreTestCase):
    def test_invite_is_single_use(self):
        household = self.store.create_household(self.adam, "Familjen From")
        invite = self.store.create_invite(household["id"], self.adam)
        self.store.accept_invite(invite["token"], self.sara)
        with self.assertRaises(HouseholdError):
            self.store.accept_invite(invite["token"], 3)

    def test_invite_preview_leaks_nothing_but_the_name(self):
        household = self.store.create_household(self.adam, "Familjen From")
        self.store.set_profile(household["id"], self.adam, display_name="Adam")
        invite = self.store.create_invite(household["id"], self.adam)
        preview = self.store.preview_invite(invite["token"])
        self.assertEqual(preview["householdName"], "Familjen From")
        self.assertEqual(preview["invitedBy"], "Adam")
        self.assertEqual(set(preview), {"householdName", "invitedBy", "expiresAt"})

    def test_expired_invite_is_refused(self):
        household = self.store.create_household(self.adam, "Familjen From")
        invite = self.store.create_invite(household["id"], self.adam)
        self.store._connection.execute(
            "UPDATE household_invites SET expires_at = '2020-01-01T00:00:00+00:00'")
        self.store._connection.commit()
        with self.assertRaises(HouseholdError):
            self.store.accept_invite(invite["token"], self.sara)

    def test_revoked_invite_is_refused(self):
        household = self.store.create_household(self.adam, "Familjen From")
        invite = self.store.create_invite(household["id"], self.adam)
        self.store.revoke_invites(household["id"], self.adam)
        with self.assertRaises(HouseholdError):
            self.store.preview_invite(invite["token"])

    def test_only_an_admin_creates_invites(self):
        household_id = self._family()
        with self.assertRaises(HouseholdError):
            self.store.create_invite(household_id, self.sara)

    def test_removed_members_open_invites_are_revoked(self):
        household_id = self._family()
        # Sara görs till admin så hon kan skapa en inbjudan, och tas sedan bort.
        self.store._connection.execute(
            "UPDATE household_members SET role = 'admin' WHERE household_id = ? AND user_id = ?",
            (household_id, self.sara))
        self.store._connection.commit()
        invite = self.store.create_invite(household_id, self.sara)
        self.store.remove_member(household_id, self.adam, self.sara)
        with self.assertRaises(HouseholdError):
            self.store.accept_invite(invite["token"], 3)

    def test_the_token_is_never_stored_in_the_clear(self):
        household = self.store.create_household(self.adam, "Familjen From")
        invite = self.store.create_invite(household["id"], self.adam)
        rows = self.store._connection.execute("SELECT token_hash FROM household_invites").fetchall()
        self.assertNotIn(invite["token"], [row["token_hash"] for row in rows])
        self.assertEqual(len(rows[0]["token_hash"]), 64)

    def test_joining_twice_is_a_no_op_not_an_error(self):
        household_id = self._family()
        invite = self.store.create_invite(household_id, self.adam)
        again = self.store.accept_invite(invite["token"], self.sara)
        self.assertEqual(len(again["members"]), 2)

    def test_a_user_in_another_household_cannot_join(self):
        household_id = self._family()
        self.store.create_household(self.stranger, "Familjen Annan")
        invite = self.store.create_invite(household_id, self.adam)
        with self.assertRaises(HouseholdError):
            self.store.accept_invite(invite["token"], self.stranger)


class ShoppingListTest(HouseholdStoreTestCase):
    def test_both_members_see_the_same_list(self):
        household_id = self._family()
        self.store.upsert_shopping_item(household_id, self.adam, {"name": "Mjölk", "amount": 1, "unit": "l"})
        seen_by_sara = self.store.shopping_items(household_id, self.sara)
        self.assertEqual([item["name"] for item in seen_by_sara], ["Mjölk"])

    def test_same_item_from_two_members_is_one_row(self):
        household_id = self._family()
        self.store.upsert_shopping_item(household_id, self.adam, {"name": "Mjölk"})
        self.store.upsert_shopping_item(household_id, self.sara, {"name": "mjölk"})
        self.assertEqual(len(self.store.shopping_items(household_id, self.adam)), 1)

    def test_gtin_identifies_the_row_when_we_know_the_product(self):
        self.assertEqual(item_key("Arla Mellanmjölk", "7310865004703"), "gtin:7310865004703")
        self.assertEqual(item_key("Crème fraiche"), item_key("creme fraiche"))

    def test_status_moves_without_losing_the_row(self):
        household_id = self._family()
        item = self.store.upsert_shopping_item(household_id, self.adam, {"name": "Ketchup"})
        moved = self.store.set_item_status(household_id, self.sara, item["key"], ALREADY_HAVE)
        self.assertEqual(moved["status"], ALREADY_HAVE)
        self.assertEqual(moved["id"], item["id"])
        back = self.store.set_item_status(household_id, self.sara, item["key"], NEED_TO_BUY)
        self.assertEqual(back["status"], NEED_TO_BUY)

    def test_unknown_status_is_refused(self):
        household_id = self._family()
        item = self.store.upsert_shopping_item(household_id, self.adam, {"name": "Ketchup"})
        with self.assertRaises(HouseholdError):
            self.store.set_item_status(household_id, self.adam, item["key"], "KANSKE")

    def test_replacing_the_week_keeps_what_the_user_decided(self):
        household_id = self._family()
        self.store.replace_week_items(household_id, self.adam, [
            {"name": "Mjölk", "amount": 1, "unit": "l"},
            {"name": "Ris", "amount": 500, "unit": "g"},
        ])
        self.store.set_item_status(household_id, self.sara, item_key("Mjölk"), ALREADY_HAVE)
        self.store.upsert_shopping_item(household_id, self.sara, {"name": "Kaffe", "source": "manual"})
        # Veckan genereras om: Ris byts mot Pasta.
        self.store.replace_week_items(household_id, self.adam, [
            {"name": "Mjölk", "amount": 2, "unit": "l"},
            {"name": "Pasta", "amount": 400, "unit": "g"},
        ])
        items = {item["name"]: item for item in self.store.shopping_items(household_id, self.adam)}
        self.assertEqual(items["Mjölk"]["status"], ALREADY_HAVE)   # beslutet överlevde
        self.assertEqual(items["Mjölk"]["amount"], 2)              # men mängden uppdaterades
        self.assertIn("Kaffe", items)                              # manuell rad rörd
        self.assertNotIn("Ris", items)                             # veckans egen rad städades

    def test_purchased_and_already_have_are_different_states(self):
        household_id = self._family()
        milk = self.store.upsert_shopping_item(household_id, self.adam, {"name": "Mjölk"})
        ketchup = self.store.upsert_shopping_item(household_id, self.adam, {"name": "Ketchup"})
        self.store.set_item_status(household_id, self.adam, milk["key"], PURCHASED)
        self.store.set_item_status(household_id, self.sara, ketchup["key"], ALREADY_HAVE)
        statuses = {item["name"]: item["status"] for item in self.store.shopping_items(household_id, self.adam)}
        self.assertEqual(statuses, {"Mjölk": PURCHASED, "Ketchup": ALREADY_HAVE})

    def test_product_snapshot_is_whitelisted_and_https_only(self):
        household_id = self._family()
        item = self.store.upsert_shopping_item(household_id, self.adam, {
            "name": "Mjölk",
            "product": {"productName": "Arla Mellanmjölk", "brand": "Arla", "gtin": "7310865004703",
                        "imageUrl": "javascript:alert(1)", "totalCost": 19.95,
                        "evil": "<script>", "priceTier": "VERIFIED_STORE_PRICE"},
        })
        product = item["product"]
        self.assertEqual(product["productName"], "Arla Mellanmjölk")
        self.assertEqual(product["gtin"], "7310865004703")
        self.assertNotIn("imageUrl", product)
        self.assertNotIn("evil", product)

    def test_manual_row_can_be_deleted_outright(self):
        household_id = self._family()
        item = self.store.upsert_shopping_item(household_id, self.adam, {"name": "Kaffe", "source": "manual"})
        self.store.delete_shopping_item(household_id, self.sara, item["key"])
        self.assertEqual(self.store.shopping_items(household_id, self.adam), [])

    def test_list_is_capped(self):
        household_id = self._family()
        from services.household.store import MAX_SHOPPING_ITEMS
        for index in range(MAX_SHOPPING_ITEMS):
            self.store.upsert_shopping_item(household_id, self.adam, {"name": f"Vara {index}"})
        with self.assertRaises(HouseholdError):
            self.store.upsert_shopping_item(household_id, self.adam, {"name": "En för mycket"})


class InventoryTest(HouseholdStoreTestCase):
    def test_generic_items_need_no_product(self):
        household_id = self._family()
        item = self.store.upsert_inventory_item(household_id, self.adam,
                                                {"name": "Lök", "amount": 3, "unit": "st"})
        self.assertIsNone(item["product"])
        self.assertIsNone(item["gtin"])
        self.assertEqual(item["location"], "skafferi")

    def test_real_products_keep_brand_image_and_package(self):
        household_id = self._family()
        item = self.store.upsert_inventory_item(household_id, self.adam, {
            "name": "Arla Mellanmjölk", "location": "kyl", "amount": 1, "unit": "st",
            "gtin": "7310865004703",
            "product": {"productName": "Arla Mellanmjölk", "brand": "Arla", "packageSize": "1,5 l",
                        "imageUrl": "https://bilder.example/mjolk.jpg"},
        })
        self.assertEqual(item["location"], "kyl")
        self.assertEqual(item["product"]["brand"], "Arla")
        self.assertEqual(item["product"]["imageUrl"], "https://bilder.example/mjolk.jpg")
        self.assertEqual(item["gtin"], "7310865004703")

    def test_unknown_location_falls_back_to_the_pantry(self):
        household_id = self._family()
        item = self.store.upsert_inventory_item(household_id, self.adam,
                                                {"name": "Ris", "location": "garaget"})
        self.assertEqual(item["location"], "skafferi")

    def test_adjust_to_zero_soft_deletes_so_other_phones_learn_about_it(self):
        household_id = self._family()
        item = self.store.upsert_inventory_item(household_id, self.adam, {"name": "Ris", "amount": 1})
        emptied = self.store.adjust_inventory(household_id, self.sara, item["key"], -1)
        self.assertTrue(emptied["deleted"])
        self.assertEqual(emptied["amount"], 0)
        live = self.store.inventory_items(household_id, self.adam, include_deleted=False)
        self.assertEqual(live, [])
        # men raden syns i en sync så andra klienter kan ta bort den ur sin vy
        self.assertEqual(len(self.store.inventory_items(household_id, self.adam)), 1)

    def test_pantry_amounts_only_reports_what_we_actually_know(self):
        household_id = self._family()
        self.store.upsert_inventory_item(household_id, self.adam, {"name": "Ris", "amount": 1000, "unit": "g"})
        self.store.upsert_inventory_item(household_id, self.adam, {"name": "Soja", "amount": 0})
        self.assertEqual(self.store.pantry_amounts(household_id), {"Ris": 1000})

    def test_expiry_must_be_a_real_date(self):
        household_id = self._family()
        item = self.store.upsert_inventory_item(household_id, self.adam,
                                                {"name": "Yoghurt", "expiry": "snart"})
        self.assertIsNone(item["expiry"])
        dated = self.store.upsert_inventory_item(household_id, self.adam,
                                                 {"name": "Yoghurt", "expiry": "2026-09-20"})
        self.assertEqual(dated["expiry"], "2026-09-20")


class RevisionTest(HouseholdStoreTestCase):
    def test_sync_since_returns_only_what_changed(self):
        household_id = self._family()
        self.store.upsert_shopping_item(household_id, self.adam, {"name": "Mjölk"})
        first = self.store.sync(household_id, self.sara, 0)
        self.assertEqual(len(first["shopping"]), 1)
        self.assertIsNotNone(first["household"])
        nothing = self.store.sync(household_id, self.sara, first["revision"])
        self.assertEqual(nothing["shopping"], [])
        self.assertIsNone(nothing["household"])
        self.store.upsert_shopping_item(household_id, self.adam, {"name": "Kaffe"})
        delta = self.store.sync(household_id, self.sara, first["revision"])
        self.assertEqual([item["name"] for item in delta["shopping"]], ["Kaffe"])

    def test_two_concurrent_edits_both_survive(self):
        """Adam och Sara står i samma butik och ändrar varsin rad. Ingen av
        ändringarna får försvinna, och båda ska synas i en enda sync."""
        household_id = self._family()
        milk = self.store.upsert_shopping_item(household_id, self.adam, {"name": "Mjölk"})
        coffee = self.store.upsert_shopping_item(household_id, self.adam, {"name": "Kaffe"})
        baseline = self.store.revision(household_id)
        self.store.set_item_status(household_id, self.adam, milk["key"], PURCHASED)
        self.store.set_item_status(household_id, self.sara, coffee["key"], ALREADY_HAVE)
        changed = {item["name"]: item["status"]
                   for item in self.store.sync(household_id, self.adam, baseline)["shopping"]}
        self.assertEqual(changed, {"Mjölk": PURCHASED, "Kaffe": ALREADY_HAVE})

    def test_every_write_moves_the_revision_forward(self):
        household_id = self._family()
        before = self.store.revision(household_id)
        self.store.upsert_inventory_item(household_id, self.adam, {"name": "Ris"})
        self.assertGreater(self.store.revision(household_id), before)

    def test_docs_carry_their_own_revision(self):
        household_id = self._family()
        self.store.set_doc(household_id, self.adam, "week", {"weekPlan": ["tacos"]})
        sync = self.store.sync(household_id, self.sara, 0)
        self.assertEqual(sync["docs"]["week"]["body"], {"weekPlan": ["tacos"]})
        after = self.store.sync(household_id, self.sara, sync["revision"])
        self.assertEqual(after["docs"], {})

    def test_unknown_doc_is_refused(self):
        household_id = self._family()
        with self.assertRaises(HouseholdError):
            self.store.set_doc(household_id, self.adam, "hemligheter", {"x": 1})

    def test_oversized_doc_is_refused(self):
        household_id = self._family()
        with self.assertRaises(HouseholdError):
            self.store.set_doc(household_id, self.adam, "week", {"junk": "x" * 300_000})


class HorizontalEscalationTest(HouseholdStoreTestCase):
    """§24: ingen får läsa eller skriva ett annat hushåll genom att byta id."""

    def setUp(self):
        super().setUp()
        self.family = self._family()
        self.other = self.store.create_household(self.stranger, "Familjen Annan")["id"]
        self.store.upsert_shopping_item(self.family, self.adam, {"name": "Mjölk"})
        self.store.upsert_inventory_item(self.family, self.adam, {"name": "Ris"})
        self.store.set_doc(self.family, self.adam, "week", {"weekPlan": ["tacos"]})

    def test_outsider_cannot_read_anything(self):
        for call in (
            lambda: self.store.sync(self.family, self.stranger, 0),
            lambda: self.store.household_for(self.family, self.stranger),
            lambda: self.store.shopping_items(self.family, self.stranger),
            lambda: self.store.inventory_items(self.family, self.stranger),
            lambda: self.store.get_doc(self.family, self.stranger, "week"),
            lambda: self.store.events(self.family, self.stranger),
        ):
            with self.assertRaises(NotAMemberError):
                call()

    def test_outsider_cannot_write_anything(self):
        for call in (
            lambda: self.store.upsert_shopping_item(self.family, self.stranger, {"name": "Hack"}),
            lambda: self.store.upsert_inventory_item(self.family, self.stranger, {"name": "Hack"}),
            lambda: self.store.replace_week_items(self.family, self.stranger, [{"name": "Hack"}]),
            lambda: self.store.set_doc(self.family, self.stranger, "week", {"weekPlan": []}),
            lambda: self.store.create_invite(self.family, self.stranger),
            lambda: self.store.leave(self.family, self.stranger),
            lambda: self.store.remove_member(self.family, self.stranger, self.adam),
            lambda: self.store.rename_household(self.family, self.stranger, "Kapad"),
        ):
            with self.assertRaises(NotAMemberError):
                call()
        self.assertEqual([item["name"] for item in self.store.shopping_items(self.family, self.adam)],
                         ["Mjölk"])

    def test_a_member_of_another_household_is_still_an_outsider(self):
        with self.assertRaises(NotAMemberError):
            self.store.sync(self.family, self.stranger, 0)
        with self.assertRaises(NotAMemberError):
            self.store.sync(self.other, self.adam, 0)

    def test_item_ids_from_another_household_are_invisible(self):
        """Radernas id är globala i tabellen. Att känna till ett id från ett
        annat hushåll får inte räcka - varje uppslag filtrerar på hushållet."""
        foreign = self.store.upsert_shopping_item(self.other, self.stranger, {"name": "Hemligt"})
        with self.assertRaises(HouseholdError):
            self.store.set_item_status(self.family, self.adam, foreign["id"], PURCHASED)
        self.assertEqual(self.store.shopping_item(self.family, foreign["id"]), {})
        untouched = self.store.shopping_items(self.other, self.stranger)
        self.assertEqual(untouched[0]["status"], NEED_TO_BUY)

    def test_inventory_ids_from_another_household_are_invisible(self):
        foreign = self.store.upsert_inventory_item(self.other, self.stranger, {"name": "Hemligt"})
        with self.assertRaises(HouseholdError):
            self.store.adjust_inventory(self.family, self.adam, foreign["id"], -1)
        with self.assertRaises(HouseholdError):
            self.store.remove_inventory_item(self.family, self.adam, foreign["id"])
        self.assertFalse(self.store.inventory_items(self.other, self.stranger)[0]["deleted"])

    def test_a_missing_household_looks_exactly_like_one_you_cannot_see(self):
        with self.assertRaises(NotAMemberError):
            self.store.household_for(999_999, self.adam)
        with self.assertRaises(NotAMemberError):
            self.store.household_for(self.other, self.adam)

    def test_garbage_household_ids_do_not_crash(self):
        for bad in ("", None, "abc", "1 OR 1=1", -1, [1]):
            with self.assertRaises(NotAMemberError):
                self.store.household_for(bad, self.adam)


if __name__ == "__main__":
    unittest.main()


class KeyContractWithTheClient(HouseholdStoreTestCase):
    """Serverns halva av nyckelkontraktet (klientens ligger i
    tests/household-keys.test.js). Går formlerna isär hittar servern ingen
    rad, svarar 400 på varje "Köpt"/"Har hemma", och klientens optimistiska
    rad blir en dubblett i familjens lista."""

    FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "household-keys.json"

    def test_the_server_key_matches_the_shared_table(self):
        table = json.loads(self.FIXTURE.read_text(encoding="utf-8"))["keys"]
        self.assertTrue(table)
        for name, expected in table.items():
            self.assertEqual(item_key(name), expected, f"nyckeln för {name!r} ändrades")

    def test_a_week_row_and_a_status_change_land_on_the_same_row(self):
        """Veckan läggs in utan produktdata; avbockningen måste träffa exakt
        den raden."""
        household_id = self._family()
        self.store.replace_week_items(household_id, self.adam, [{"name": "Mjölk", "amount": 1, "unit": "l"}])
        rows = self.store.shopping_items(household_id, self.adam)
        milk = next(row for row in rows if row["name"] == "Mjölk")
        self.assertEqual(milk["key"], item_key("Mjölk"))
        updated = self.store.set_item_status(household_id, self.adam, item_key("Mjölk"), PURCHASED)
        self.assertEqual(updated["status"], PURCHASED)

