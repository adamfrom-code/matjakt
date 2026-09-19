# -*- coding: utf-8 -*-
"""P05c: det kanoniska ingredienslagret når in i prismatchningen.

P05a byggde registret, P05b satte canonicalId på varje ingrediensrad -
men matchningen läste fortfarande bara INGREDIENT_ALIASES. Receptet säger
"tomat", hyllan säger "Tomater"; receptet säger "feta", hyllan "Fetaost".
Matcharen svarar nej på båda literalt (prövat: product_matches_ingredient
("Tomater Kvist", "tomat") är False) och ja under registrets namn.

Registrets namn får konkurrera på exakt INGREDIENT_ALIASES villkor: samma
matchare under aliasets namn, ORIGINALETS uteslutningar och kategorivakter.
Ingen fuzzy-gissning - resolve() svarar None för det den inte känner, och
då tillförs ingenting. Osäkert = inget pris, som förut.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery.pricing import (  # noqa: E402
    RecipePricingEngine, _explain_chosen, aliases_for, canonical_names_for, product_matches_ingredient,
)

GRONT = "Frukt & grönt > Grönsaker"
KONSERV = "Skafferi > Konserver > Tomater"
OST = "Mejeri, ost & ägg > Ost"
KRYDDOR = "Skafferi > Kryddor & smaksättning > Kryddor"
BROD = "Bröd & kakor > Kakor & bullar"


class _Product:
    def __init__(self, id, name, category, brand=None):
        self.id, self.name, self.brand, self.category = id, name, brand, category
        self.quantity, self.unit = 500.0, "g"


def _motor(index):
    engine = RecipePricingEngine.__new__(RecipePricingEngine)
    engine._index_for = lambda chain: index
    return engine


class RegistretsNamnNarHyllan(unittest.TestCase):
    def test_tomat_nar_tomater_men_inte_konserven(self):
        kvist = _Product(1, "Tomater Kvist 500g", GRONT)
        krossade = _Product(2, "Krossade Tomater 400g", KONSERV)
        index = {"tomater": [kvist, krossade], "tomat": [], "kvist": [kvist], "krossade": [krossade]}
        # Literalt: matcharen känner inte "tomat" i "Tomater Kvist".
        self.assertFalse(product_matches_ingredient(kvist.name, "tomat", None, GRONT))
        namn = [p.name for p in _motor(index)._candidates("tomat", "Willys")]
        self.assertIn("Tomater Kvist 500g", namn, "registrets namn ska nå hyllan")
        self.assertNotIn("Krossade Tomater 400g", namn,
                         "kravet (frukt & grönt) följer med aliaset - konserven är en annan vara")

    def test_feta_nar_fetaost_och_soja_nar_sojasas(self):
        feta = _Product(3, "Fetaost 150g", OST)
        soja = _Product(4, "Sojasås Japansk 250ml", "Skafferi > Asiatiskt")
        index = {"fetaost": [feta], "feta": [], "sojasas": [soja], "soja": [], "japansk": [soja]}
        self.assertEqual([p.name for p in _motor(index)._candidates("feta", "Ica")], ["Fetaost 150g"])
        self.assertEqual([p.name for p in _motor(index)._candidates("soja", "Ica")], ["Sojasås Japansk 250ml"])

    def test_raden_sager_vilket_namn_som_bar_matchen(self):
        kvist = _Product(1, "Tomater Kvist 500g", GRONT)
        dom = _explain_chosen(kvist, "tomat")
        self.assertTrue(dom.ok)
        self.assertTrue(dom.rule.startswith("kanonisk:Tomater/"), dom.rule)

    def test_registrets_namn_ar_kurerade_och_taljs_inte_dubbelt(self):
        self.assertEqual(canonical_names_for("tomat"), ["Tomater"])
        self.assertEqual(canonical_names_for("feta"), ["Fetaost"])
        # Ett namn INGREDIENT_ALIASES redan bär räknas inte upp igen: unionen
        # av de två listorna har varje namn exakt en gång.
        for ingrediens in ("Tomater", "tomat", "lök", "gul lök", "feta"):
            union = [n.lower() for n in (*aliases_for(ingrediens), *canonical_names_for(ingrediens))]
            self.assertEqual(len(union), len(set(union)), (ingrediens, union))
            self.assertNotIn(ingrediens.lower(), union)
        self.assertIn("tomat", [n.lower() for n in (*aliases_for("Tomater"), *canonical_names_for("Tomater"))])
        # Ingrediensen själv och INGREDIENT_ALIASES räknas inte upp igen.
        for namn in canonical_names_for("gul lök"):
            self.assertNotEqual(namn.lower(), "gul lök")


class IngenGissning(unittest.TestCase):
    def test_okand_ingrediens_tillfor_ingenting(self):
        self.assertEqual(canonical_names_for("drakfruktsnektar"), [])
        self.assertEqual(canonical_names_for(""), [])
        index = {"drakfrukt": [_Product(9, "Drakfrukt", GRONT)]}
        self.assertEqual(_motor(index)._candidates("drakfruktsnektar", "Ica"), [])

    def test_de_farliga_fallen_star_kvar(self):
        """Historiska felmatchningar får inte komma tillbaka genom registret:
        kanel är inte kanelbullar, persilja är inte persiljesmör,
        fiskpinnar är inte fisk, och en krydda i gram är inte ett paket."""
        bullar = _Product(10, "Kanelbullar 6-pack", BROD)
        persiljesmor = _Product(11, "Persiljesmör 100g", "Mejeri, ost & ägg > Smör")
        fisk = _Product(12, "Torskfilé 400g", "Fisk & skaldjur > Fisk")
        index = {"kanelbullar": [bullar], "kanel": [], "persiljesmor": [persiljesmor], "persilja": [],
                 "torskfile": [fisk], "fisk": [fisk], "fiskpinnar": []}
        motor = _motor(index)
        self.assertEqual(motor._candidates("kanel", "Ica"), [])
        self.assertEqual(motor._candidates("persilja", "Ica"), [])
        self.assertEqual(motor._candidates("fiskpinnar", "Ica"), [])
        # ...och registret svarar med en post för alla tre - det är
        # kategorin och matcharen som säger nej, inte okunskap.
        for namn in ("kanel", "persilja", "fiskpinnar"):
            from services.ingredients import resolve
            self.assertIsNotNone(resolve(namn), namn)

    def test_kategorin_ar_ett_krav_aven_under_registrets_namn(self):
        """En "Tomater"-produkt i kryddhyllan (torkad tomat, tomatpulver)
        är inte färsk tomat - även om namnet stämmer."""
        pulver = _Product(13, "Tomater Torkade 50g", KRYDDOR)
        self.assertEqual(_motor({"tomater": [pulver], "tomat": []})._candidates("tomat", "Ica"), [])


if __name__ == "__main__":
    unittest.main()
