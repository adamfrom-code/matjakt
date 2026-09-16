# -*- coding: utf-8 -*-
"""P06a: mängder och enheter - masterorderns checklista, på ett ställe.

Det mesta här fanns redan och är pinnat i egna filer: fiskpinnarna (224 g
-> 224 paket, 6 561 kr) och persiljan i test_release_gate, klyftorna i
test_vitloksklyftor, familjerna i test_units, skafferiavdraget i
test_skafferi_enheter. Det här är inte kopior av dem. Det här är:

  1. VAKTEN. Varje enhet receptimporten accepterar (import_recipes
     .KNOWN_UNITS) hör till en familj prissättningen känner. "knippe" låg i
     importen utan att pricing visste om den - ett recept med "1 knippe
     persilja" hade importerats fint och aldrig fått ett exakt pris.
  2. PAKETORDEN. burk/påse/paket/förpackning/knippe är styckenheter: exakta
     mot styckvaror, ärliga estimat mot gram/ml. Aldrig en gissad storlek.
  3. DELENHETER ÄR INTE FÖRPACKNINGAR. skiva vägrar. (klyfta har sin egen
     vikt och sin egen fil.)
  4. OSÄKERT ÄR OSÄKERT, HELA VÄGEN. msk mot ett grampaket utan känd
     densitet -> exactPackaging False, totalCost None, och raden hålls ur
     totalen, gör den till ett golv och räknas som estimat - inte som pris.
  5. ORIMLIGT FLAGGAS. >10 paket eller >500 kr på en rad märks, aldrig
     tyst.
  6. INCIDENTERNA ÄR KVAR. De historiska felen har namngivna tester i
     andra filer; det här testet vägrar att de tas bort.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery.pricing import COUNT_UNITS, _MASS, _VOLUME, KLYFTA_UNITS, convert_amount, _fold  # noqa: E402
from test_release_gate import _engine_with  # noqa: E402


def unit_family(unit) -> str | None:
    """massa | volym | antal | None, rakt ur prissättningens tabeller. Inte
    importerad från services.ingredients (P05a) - det här paketet ska stå
    på egna ben och vakta pricing, inte ett annat paket."""
    u = _fold(unit or "")
    if not u:
        return None
    if u in _MASS:
        return "massa"
    if u in _VOLUME:
        return "volym"
    if u in COUNT_UNITS:
        return "antal"
    return None

ROOT = Path(__file__).resolve().parents[2]
IMPORT = ROOT / "backend" / "scripts" / "import_recipes.py"


def _known_units() -> set[str]:
    src = IMPORT.read_text(encoding="utf-8")
    m = re.search(r"KNOWN_UNITS = \{([^}]*)\}", src, re.S)
    return set(re.findall(r'"([^"]+)"', m.group(1)))


PAKETORD = ("burk", "påse", "paket", "förpackning", "knippe")


class Vakten(unittest.TestCase):
    def test_varje_importenhet_har_en_familj_i_prissattningen(self):
        saknas = []
        for u in sorted(_known_units()):
            f = _fold(u)
            känd = f in _MASS or f in _VOLUME or f in COUNT_UNITS or f in KLYFTA_UNITS
            if not känd:
                saknas.append(u)
        self.assertEqual(saknas, [],
                         f"importen accepterar enheter prissättningen inte känner: {saknas}. "
                         "Ett recept med en sådan enhet får aldrig ett exakt pris.")

    def test_knippe_var_hålet(self):
        self.assertIn("knippe", _known_units())
        self.assertIn("knippe", COUNT_UNITS)


class Paketorden(unittest.TestCase):
    def test_ar_styckenheter(self):
        for ord_ in PAKETORD:
            self.assertEqual(unit_family(ord_), "antal", ord_)
            self.assertEqual(convert_amount(2, ord_, "st"), 2.0, ord_)
            self.assertEqual(convert_amount(1, ord_, ord_), 1.0, ord_)

    def test_vagrar_mot_massa_och_volym(self):
        """Ingen gissad storlek. En burk mot 400 g är okänt, inte 400 g."""
        for ord_ in PAKETORD:
            self.assertIsNone(convert_amount(1, ord_, "g"), ord_)
            self.assertIsNone(convert_amount(1, ord_, "dl"), ord_)
            self.assertIsNone(convert_amount(400, "g", ord_), ord_)

    def test_en_burk_mot_en_styckvara_ar_exakt(self):
        engine, store_id, tmp, db = _engine_with([
            {"id": "kt", "name": "Krossade tomater", "quantity": 1, "unit": "st", "price": 12.0, "size": "400 g"},
        ])
        try:
            row = engine.price_item("Krossade tomater", 1, "burk", "Willys", store_id)
            self.assertTrue(row.get("exactPackaging"), row)
            self.assertEqual(row.get("packages"), 1, row)
            self.assertEqual(row.get("totalCost"), 12.0, row)
        finally:
            db.close(); tmp.cleanup()

    def test_en_burk_mot_en_gramvara_ar_ett_estimat(self):
        engine, store_id, tmp, db = _engine_with([
            {"id": "kt", "name": "Krossade tomater", "quantity": 400, "unit": "g", "price": 12.0},
        ])
        try:
            row = engine.price_item("Krossade tomater", 1, "burk", "Willys", store_id)
            # Radnivån säger "osäkert"; listnivån (price_list) är den som
            # vägrar räkna in den - se test_den_osakra_raden_halls_ur_totalen.
            self.assertFalse(row.get("exactPackaging", True), row)
            self.assertEqual(row.get("packages"), 1, "golvet är ett paket, aldrig noll")
        finally:
            db.close(); tmp.cleanup()


class Delenheter(unittest.TestCase):
    def test_skiva_ar_ingen_forpackning(self):
        self.assertNotIn("skiva", COUNT_UNITS)
        self.assertIsNone(convert_amount(2, "skiva", "st"))
        self.assertIsNone(unit_family("skiva"))

    def test_klyfta_ar_inte_st(self):
        """Klyftan har egen vikt (5 g) och egen fil. Som styck hade 3 klyftor
        köpt 3 knoppar - det var incidenten."""
        self.assertNotIn("klyfta", COUNT_UNITS)
        self.assertIn("klyfta", KLYFTA_UNITS)


class OsakertHelaVagen(unittest.TestCase):
    def _tomatpure(self):
        # Tomatpuré i msk mot en tub i gram. Ingen källbelagd densitet finns
        # (roadmap M: O10b) - alltså ett estimat, inte en gissning.
        return _engine_with([
            {"id": "tp", "name": "Tomatpuré", "quantity": 140, "unit": "g", "price": 9.0},
        ])

    def test_msk_mot_gram_utan_densitet_ar_ett_estimat(self):
        engine, store_id, tmp, db = self._tomatpure()
        try:
            row = engine.price_item("Tomatpuré", 2, "msk", "Willys", store_id)
            # Raden bär exactPackaging=False och ett golv på ett paket. Att
            # totalCost nollas och raden hålls ur summan sker i price_list -
            # två lager, och båda vaktas: det här testet vaktar signalen,
            # test_den_osakra_raden_halls_ur_totalen vaktar effekten.
            self.assertFalse(row.get("exactPackaging", True), row)
            self.assertEqual(row.get("packages"), 1, row)
            self.assertIsNone(row.get("unreasonable"), row)
        finally:
            db.close(); tmp.cleanup()

    def test_den_osakra_raden_halls_ur_totalen(self):
        engine, store_id, tmp, db = _engine_with([
            {"id": "tp", "name": "Tomatpuré", "quantity": 140, "unit": "g", "price": 9.0},
            {"id": "ps", "name": "Pasta", "quantity": 500, "unit": "g", "price": 15.0},
        ])
        try:
            r = engine.price_list([{"name": "Tomatpuré", "amount": 2, "unit": "msk"},
                                   {"name": "Pasta", "amount": 400, "unit": "g"}],
                                  "Willys", store_id)
            self.assertTrue(r["totalIsFloor"])
            self.assertEqual(r["estimatedItems"], 1)
            self.assertEqual(r["realPriceItems"], 1)
            self.assertEqual(r["totalCheckoutCost"], 15.0, "estimatet får inte bidra med en krona")
        finally:
            db.close(); tmp.cleanup()


class OrimligtFlaggas(unittest.TestCase):
    def test_for_manga_paket_marks(self):
        engine, store_id, tmp, db = _engine_with([
            {"id": "sm", "name": "Smör", "quantity": 50, "unit": "g", "price": 5.0},
        ])
        try:
            row = engine.price_item("Smör", 2000, "g", "Willys", store_id)  # 40 paket
            self.assertGreater(row.get("packages") or 0, 10, row)
            self.assertEqual(row.get("unreasonable"), "package_count", row)
        finally:
            db.close(); tmp.cleanup()

    def test_for_dyr_rad_marks(self):
        engine, store_id, tmp, db = _engine_with([
            {"id": "ox", "name": "Oxfilé", "quantity": 500, "unit": "g", "price": 300.0},
        ])
        try:
            row = engine.price_item("Oxfilé", 1000, "g", "Willys", store_id)  # 600 kr
            self.assertEqual(row.get("unreasonable"), "row_cost", row)
        finally:
            db.close(); tmp.cleanup()


class IncidenternaArKvar(unittest.TestCase):
    """Meta-vakt: de historiska felen har namngivna tester. Tas ett bort
    ska det synas här, inte upptäckas av nästa 6 561-kronorslista."""
    KRAV = {
        "test_release_gate.py": ("test_fiskpinnar_224g_against_450g_package_is_one_package",
                                 "test_persilja_10g_against_50g_package_is_one_package",
                                 "test_kanel_never_matches_kanel_flavoured_bakery",
                                 "test_a_dense_liquid_is_never_one_exact_package"),
        "test_vitloksklyftor.py": ("test_three_cloves_cost_less_than_five_kronor",
                                   "test_cloves_without_a_usable_package_stay_uncertain"),
        "test_units.py": ("test_spoons_pieces_and_cross_family_refuse",),
    }

    def test_de_namngivna_testerna_finns(self):
        for fil, namn in self.KRAV.items():
            src = (ROOT / "backend" / "tests" / fil).read_text(encoding="utf-8")
            for n in namn:
                self.assertIn(f"def {n}(", src, f"{fil}: {n} är borta")


if __name__ == "__main__":
    unittest.main()
