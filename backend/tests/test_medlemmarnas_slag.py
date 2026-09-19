# -*- coding: utf-8 -*-
"""S1: medlemmens slag (vuxen/barn/gäst) och portionsfaktorn.

Rollen (admin/member) säger vad man får göra; slaget säger vad man äter.
`kind` sparas i profilen, `child` (J3) hålls i takt åt båda hållen, och
varje medlem i svaret bär `kind` + `portionFactor`; hushållet bär
`portionSum`. Faktorerna står i EN tabell (PORTION_FACTOR) - barnets värde
är ett produktbeslut och är 1.0 tills det tagits.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.household import HouseholdStore  # noqa: E402
from services.household.store import MEMBER_KINDS, PORTION_FACTOR, member_kind  # noqa: E402


class Slaget(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.store = HouseholdStore(Path(self._tmp.name) / "household.db")
        self.addCleanup(self.store.close)
        self.adam, self.sara, self.lo = 1, 2, 3
        self.hus = self.store.create_household(self.adam, "Familjen")["id"]
        for uid in (self.sara, self.lo):
            invite = self.store.create_invite(self.hus, self.adam)
            self.store.accept_invite(invite["token"], uid)

    def medlem(self, uid):
        return next(m for m in self.store.household_for(self.hus, self.adam)["members"] if m["userId"] == uid)

    def test_slaget_sparas_och_child_halls_i_takt(self):
        self.store.set_profile(self.hus, self.lo, profile={"kind": "child"})
        m = self.medlem(self.lo)
        self.assertEqual((m["kind"], m["profile"]["kind"], m["profile"]["child"]), ("child", "child", True))
        self.store.set_profile(self.hus, self.lo, profile={"kind": "adult"})
        m = self.medlem(self.lo)
        self.assertEqual((m["kind"], m["profile"]["child"]), ("adult", False))

    def test_child_utan_kind_ger_slaget(self):
        """J3:s gamla klient skickar bara child - slaget härleds."""
        self.store.set_profile(self.hus, self.sara, profile={"child": True})
        self.assertEqual(self.medlem(self.sara)["kind"], "child")
        self.assertEqual(self.medlem(self.sara)["profile"]["kind"], "child")
        self.store.set_profile(self.hus, self.sara, profile={"child": False})
        self.assertEqual(self.medlem(self.sara)["kind"], "adult")

    def test_okant_slag_sparas_inte(self):
        self.store.set_profile(self.hus, self.sara, profile={"kind": "drake", "spice": "mild"})
        m = self.medlem(self.sara)
        self.assertNotIn("kind", m["profile"])
        self.assertEqual(m["kind"], "adult")                 # härlett, inte "drake"
        self.assertEqual(m["profile"]["spice"], "mild")

    def test_gammal_profil_utan_nagot_ar_vuxen(self):
        m = self.medlem(self.adam)
        self.assertEqual((m["kind"], m["portionFactor"]), ("adult", 1.0))
        self.assertEqual(member_kind(None), "adult")
        self.assertEqual(member_kind({"child": True}), "child")

    def test_varje_medlem_bar_faktor_och_hushallet_summan(self):
        self.store.set_profile(self.hus, self.lo, profile={"kind": "child"})
        self.store.set_profile(self.hus, self.sara, profile={"kind": "guest"})
        hus = self.store.household_for(self.hus, self.adam)
        faktorer = {m["userId"]: m["portionFactor"] for m in hus["members"]}
        self.assertEqual(faktorer, {self.adam: PORTION_FACTOR["adult"], self.sara: PORTION_FACTOR["guest"], self.lo: PORTION_FACTOR["child"]})
        self.assertEqual(hus["portionSum"], round(sum(faktorer.values()), 1))

    def test_tabellen_tacker_varje_slag_och_ar_en_portion_tills_beslutet(self):
        self.assertEqual(set(PORTION_FACTOR), set(MEMBER_KINDS))
        for kind, faktor in PORTION_FACTOR.items():
            self.assertGreater(faktor, 0, kind)
            self.assertLessEqual(faktor, 1.0, kind)
        # Barnets faktor är 1.0 tills produktbeslutet är taget - samma som
        # appen räknar i dag (personer = vuxna + barn). Ändras raden ska det
        # vara med flit och med ett beslut bakom.
        self.assertEqual(PORTION_FACTOR["child"], 1.0)


if __name__ == "__main__":
    unittest.main()
