# -*- coding: utf-8 -*-
"""P07a: varför matchade den här produkten? Vilken regel? Vilken säkerhet?

product_matches_ingredient() svarade True/False genom åtta namnlösa
`return False`. Ett fel pris gick inte att förklara för någon - varken för
den som läste auditen eller för den som skulle rätta regeln.

explain_match() gör samma kontroller i samma ordning och ger domen ett
namn. Den gamla funktionen DELEGERAR dit, så de kan inte glida isär -
och det första testet bevisar det över hela den kanoniska matrisen.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery import pricing  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    MatchVerdict, category_allows_ingredient, explain_match, product_matches_ingredient,
)
from test_canonical_matrix import CASES, MEAT  # noqa: E402
from test_release_gate import _engine_with  # noqa: E402

REGLER_NEJ = {"kategori", "universell-uteslutning", "inga-ingrediensord", "ord-saknas",
              "leder-inte-namnet", "charkform", "regel-uteslutning", "regel-krav"}
REGLER_JA = {"helord", "sammansattningshuvud"}


class SammaDomSomForut(unittest.TestCase):
    def test_boolean_ar_exakt_explain_ok_over_hela_matrisen(self):
        """128 par åt båda hållen. Skiljer sig ett enda har delegeringen brutits."""
        for ingredient, product, category, want in CASES:
            v = explain_match(product, ingredient, None, category)
            self.assertIsInstance(v, MatchVerdict)
            self.assertEqual(v.ok, product_matches_ingredient(product, ingredient, None, category))
            self.assertEqual(v.ok, want, f"{ingredient!r} mot {product!r}: {v}")
            self.assertIn(v.rule, REGLER_JA if v.ok else REGLER_NEJ, f"{ingredient!r} mot {product!r}: okänd regel {v.rule!r}")

    def test_boolean_funktionen_har_ingen_egen_logik(self):
        """Källvakt: kroppen är EN delegerande rad. Får den en egen kontroll
        kan de två svara olika, och då är förklaringen en lögn."""
        src = Path(pricing.__file__).read_text(encoding="utf-8")
        start = src.index("def product_matches_ingredient(")
        kropp = src[src.index('"""', src.index('"""', start) + 3) + 3:src.index("\ndef explain_match", start)]
        rader = [r.strip() for r in kropp.splitlines() if r.strip()]
        self.assertEqual(rader, ["return explain_match(product_name, ingredient, brand, category).ok"], rader)


class VarjeRegelNasMedEttPar(unittest.TestCase):
    def test_kategori(self):
        """Datadrivet ur matrisen: par där kedjans kategori ensam avgör."""
        par = [(i, p, c) for i, p, c, want in CASES if not want and c and not category_allows_ingredient(c, i)]
        self.assertTrue(par, "matrisen har inget par där kategorin stoppar")
        for i, p, c in par:
            self.assertEqual(explain_match(p, i, None, c).rule, "kategori", (i, p, c))

    def test_universell_uteslutning(self):
        v = explain_match("Potatischips Sourcream", "Potatis")
        self.assertEqual((v.ok, v.rule), (False, "universell-uteslutning"), v)
        self.assertIn("chips", v.detail)

    def test_inga_ingrediensord(self):
        v = explain_match("Gul Lök", "ök")
        self.assertEqual((v.ok, v.rule), (False, "inga-ingrediensord"), v)

    def test_ord_saknas(self):
        v = explain_match("Fläskfilé Bit", "Kycklingfilé")
        self.assertEqual((v.ok, v.rule), (False, "ord-saknas"), v)
        self.assertIn("kycklingfile", v.detail)

    def test_leder_inte_namnet(self):
        # Ur modulens egen incidentlista: "Grädde" -> "Kyld Vaniljsås Grädde & Mjölk".
        v = explain_match("Kyld Vaniljsås Grädde & Mjölk", "Grädde")
        self.assertEqual((v.ok, v.rule), (False, "leder-inte-namnet"), v)
        self.assertIn("kyld", v.detail)

    def test_charkform(self):
        v = explain_match("Kycklingfilé Panerad", "Kycklingfilé")
        self.assertEqual((v.ok, v.rule), (False, "charkform"), v)
        self.assertIn("panerad", v.detail)

    def test_regel_uteslutning(self):
        # Fläsklägg slutar på -lägg, alltså på -ägg: styckdetaljen är inte ett ägg.
        v = explain_match("Fläsklägg Rimmad", "Ägg")
        self.assertEqual((v.ok, v.rule), (False, "regel-uteslutning"), v)
        self.assertIn("lägg", v.detail)

    def test_regel_krav_finns_som_utfall(self):
        """Ingen naturlig rad i matrisen når require-steget (helordskravet
        före det fångar samma fall), men utfallet finns och är namngivet."""
        src = Path(pricing.__file__).read_text(encoding="utf-8")
        self.assertIn('MatchVerdict(False, "regel-krav"', src)


class VarforDenMatchade(unittest.TestCase):
    def test_helord_med_kategori_ar_hog_sakerhet(self):
        v = explain_match("Oxfilé Bit", "Oxfilé", None, MEAT)
        self.assertEqual((v.ok, v.rule, v.confidence), (True, "helord", "hög"), v)

    def test_sammansattningshuvud_utan_kategori_ar_medel(self):
        v = explain_match("Jasminris 1 kg", "Ris")
        self.assertEqual((v.ok, v.rule, v.confidence), (True, "sammansattningshuvud", "medel"), v)

    def test_sakerheten_ar_kategorisk_aldrig_ett_tal(self):
        for ingredient, product, category, want in CASES:
            v = explain_match(product, ingredient, None, category)
            self.assertIn(v.confidence, (None, "hög", "medel"))
            self.assertNotIsInstance(v.confidence, (int, float))


class RadenBarSinForklaring(unittest.TestCase):
    def test_price_item_forklarar_den_valda_produkten(self):
        engine, store_id, tmp, db = _engine_with([
            {"id": "ox", "name": "Oxfilé Bit", "quantity": 500, "unit": "g", "price": 250.0,
             "category": MEAT},
        ])
        try:
            row = engine.price_item("Oxfilé", 400, "g", "Willys", store_id)
            m = row.get("matchRule")
            self.assertIsInstance(m, dict, row)
            self.assertEqual((m["ok"], m["rule"], m["confidence"]), (True, "helord", "hög"), m)
            self.assertEqual(set(m), {"ok", "rule", "detail", "confidence"})
        finally:
            db.close(); tmp.cleanup()

    def test_en_produkt_som_kom_in_via_alias_sager_vilket(self):
        engine, store_id, tmp, db = _engine_with([
            {"id": "pg", "name": "Parmigiano Reggiano", "quantity": 200, "unit": "g", "price": 59.0},
        ])
        try:
            row = engine.price_item("Parmesan", 100, "g", "Willys", store_id)
            m = row.get("matchRule") or {}
            self.assertTrue(m.get("ok"), row)
            self.assertTrue(m["rule"].startswith("alias:parmigiano/"), m)
        finally:
            db.close(); tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
