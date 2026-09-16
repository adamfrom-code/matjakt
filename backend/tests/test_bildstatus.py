# -*- coding: utf-8 -*-
"""P09a: bildstatus är genererad ur källorna och varje dom bär sitt bevis."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

ROOT = Path(__file__).resolve().parents[2]
SKRIPT = ROOT / "backend" / "scripts" / "bildstatus.py"


def _ladda():
    spec = importlib.util.spec_from_file_location("bildstatus", SKRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Bildstatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _ladda()
        cls.rader = json.loads((ROOT / "docs" / "bildstatus.json").read_text(encoding="utf-8"))
        cls.kall_ids = {r["id"] for r in cls.m._källor()}

    def test_genererad_ur_dagens_kallor(self):
        """--check är offline: Wikimedia läses ur den committade cachen."""
        self.assertEqual(self.m.main(["--check"]), 0,
                         "docs/bildstatus.* stämmer inte med källorna - kör backend/scripts/bildstatus.py")

    def test_varje_recept_exakt_en_gang(self):
        ids = [r["id"] for r in self.rader]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), self.kall_ids)

    def test_statusarna_ar_ur_det_stangda_forradet(self):
        for r in self.rader:
            self.assertIn(r["status"], self.m.STATUSAR, r["id"])

    def test_missing_ar_exakt_recepten_utan_bild(self):
        utan = {r["id"] for r in self.m._källor() if not r.get("image")}
        self.assertEqual({r["id"] for r in self.rader if r["status"] == "MISSING"}, utan)

    def test_rejected_och_exact_bar_bevis(self):
        for r in self.rader:
            if r["status"] in ("REJECTED", "EXACT-KANDIDAT"):
                b = r["bevis"]
                self.assertTrue(b.get("fotografens_titel") or b.get("fil") or "olika huvudprotein" in r["skal"],
                                f"{r['id']}: {r['status']} utan bevis")

    def test_ett_delat_foto_ar_aldrig_exact(self):
        for r in self.rader:
            if r["delas_med"]:
                self.assertNotEqual(r["status"], "EXACT-KANDIDAT", f"{r['id']} delar foto och kan inte vara EXACT")

    def test_de_kanda_fallen(self):
        d = {r["id"]: r for r in self.rader}
        self.assertEqual(d["kottbullar-potatismos"]["status"], "REJECTED")   # "fried meat cutlet"
        self.assertEqual(d["laxpoke"]["status"], "REJECTED")                 # bowl-fotot, 9 rätter
        self.assertEqual(d["pitepalt"]["status"], "MISSING")
        self.assertNotEqual(d["biffmatvetesallad"]["status"], "EXACT-KANDIDAT")  # "sallad" ensamt räcker inte

    def test_alt_texten_anvands_inte_som_bevis(self):
        src = SKRIPT.read_text(encoding="utf-8")
        self.assertNotIn('r.get("imageAlt")', src.split("def klassificera")[1])


if __name__ == "__main__":
    unittest.main()
