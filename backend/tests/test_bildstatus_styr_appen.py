# -*- coding: utf-8 -*-
"""P09b: bildstatusen styr vad appen visar.

P09a klassificerade varje receptfoto efter vad KÄLLAN säger att det visar.
Nu följer produkten datan: REJECTED och NEEDS_REVIEW visas inte (hellre
reservkortet än fel matbild), MISSING är reservkortet, EXACT och
GOOD_VARIANT visas med alt-text ur beviset - aldrig ur receptnamnet.
Kartan servern läser genereras av samma skript som docs/bildstatus.json
och hålls i takt av --check.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.recipes import api as recipes_api  # noqa: E402
from services.recipes.store import RecipeStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SKRIPT = ROOT / "backend" / "scripts" / "bildstatus.py"


def _ladda():
    spec = importlib.util.spec_from_file_location("bildstatus", SKRIPT)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


class KartanArGenererad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _ladda()
        cls.docs = json.loads((ROOT / "docs" / "bildstatus.json").read_text(encoding="utf-8"))
        cls.karta = recipes_api.las_bildstatus()

    def test_kartan_ar_samma_klassificering_som_docs(self):
        self.assertEqual(set(self.karta), {r["id"] for r in self.docs})
        for r in self.docs:
            self.assertEqual(self.karta[r["id"]]["status"], r["status"], r["id"])

    def test_alt_texten_kommer_ur_beviset_inte_ur_namnet(self):
        for r in self.docs:
            alt = self.karta[r["id"]]["alt"]
            if r["status"] in ("EXACT-KANDIDAT", "GOOD_VARIANT-KANDIDAT"):
                self.assertTrue(alt, r["id"])
                # Aldrig den genererade frasen. Att KÄLLANS titel råkar vara
                # rättens namn ("Pannkakor.jpg") är däremot ett bevis, inte
                # en gissning - den får stå.
                self.assertNotIn("upplagd på tallrik", alt)
                self.assertIn("foto", alt.lower())
            else:
                self.assertIsNone(alt, r["id"])

    def test_check_haller_kartan_i_takt(self):
        self.assertEqual(self.m.main(["--check"]), 0, "kör backend/scripts/bildstatus.py")


class ImportenFoljerKartan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = RecipeStore(Path(cls.tmp.name) / "recept.db")
        recipes_api.import_sources(cls.store)
        cls.docs = {r["id"]: r for r in json.loads((ROOT / "docs" / "bildstatus.json").read_text(encoding="utf-8"))}
        cls.recept = {rid: cls.store.get(rid) for rid in cls.docs}

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.tmp.cleanup()

    def test_avvisade_och_obekraftade_foton_visas_inte(self):
        for rid, r in self.docs.items():
            if r["status"] in ("REJECTED", "NEEDS_REVIEW"):
                self.assertIsNone(self.recept[rid]["image"], f"{rid} ({r['status']}) visar ett foto")
                self.assertEqual(self.recept[rid]["imageStatus"],
                                 "rejected" if r["status"] == "REJECTED" else "unverified")

    def test_bekraftade_foton_visas_med_bevisets_alt(self):
        antal = 0
        for rid, r in self.docs.items():
            if r["status"] in ("EXACT-KANDIDAT", "GOOD_VARIANT-KANDIDAT"):
                antal += 1
                self.assertTrue(self.recept[rid]["image"], rid)
                self.assertEqual(self.recept[rid]["imageStatus"], "ok")
                self.assertNotIn("upplagd på tallrik", self.recept[rid]["imageAlt"] or "")
        self.assertGreater(antal, 50)

    def test_saknade_foton_ar_reservkortet(self):
        for rid, r in self.docs.items():
            if r["status"] == "MISSING":
                self.assertIsNone(self.recept[rid]["image"])
                self.assertEqual(self.recept[rid]["imageStatus"], "needs_image")

    def test_ett_oklassificerat_foto_visas_inte(self):
        """Fail closed: ett nytt recept med foto men utan post i kartan
        visar reservkortet tills bildstatus.py körts."""
        r = {"id": "nytt", "name": "Nytt", "image": "assets/recipes/nytt.jpg", "imageSource": "Pexels",
             "imageAlt": "Nytt upplagd på tallrik"}
        recipes_api.tillampa_bildstatus(r, None)
        self.assertIsNone(r["image"])
        self.assertEqual(r["imageStatus"], "unverified")

    def test_ett_bekraftat_foto_utan_alt_far_kallan(self):
        r = {"id": "x", "name": "X", "image": "assets/recipes/x.jpg", "imageSource": "Wikimedia Commons"}
        recipes_api.tillampa_bildstatus(r, {"status": "EXACT-KANDIDAT", "alt": None})
        self.assertEqual((r["image"], r["imageStatus"], r["imageAlt"]),
                         ("assets/recipes/x.jpg", "ok", "Foto: Wikimedia Commons"))


if __name__ == "__main__":
    unittest.main()
