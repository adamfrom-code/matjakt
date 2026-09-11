# -*- coding: utf-8 -*-
"""C9: skafferiavdraget var enhetsblint.

Hushållets databas HAR en enhetskolumn på varje lagerrad
(`inventory_items.unit`) och synken bär den hela vägen ut i klienten. På väg
tillbaka till prismotorn kastades den bort: frontend skickade bara ett tal,
och avdraget fick gissa sig till radens basenhet.

Två fel i motsatt riktning, båda verkliga:

  "Ris 2 (kg) hemma"  mot en 500 g-rad   -> drog av TVÅ GRAM.
                                            "Har hemma" gjorde i praktiken
                                            ingenting för vikt- och
                                            volymvaror.
  "Potatis 1000" (g)  mot "Potatis 4 st" -> drog av 1 000 STYCK.
                                            Potatisen försvann ur både
                                            listan och totalen.

Nu följer enheten med, motorn konverterar med `convert_amount`, och vägrar
avdrag när enheterna inte går att jämföra. Det rena talet är fortfarande en
giltig form på tråden - det lokala skafferiet har ingen enhet, och varje
klient med gammal app.js i sin service worker-cache skickar det.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery import GroceryStore, RawProduct  # noqa: E402
from services.grocery.pricing import RecipePricingEngine, pantry_entry  # noqa: E402


class PantryEntryTest(unittest.TestCase):
    """Formen på tråden. Båda måste gå att läsa, och skräp får aldrig bli
    ett avdrag."""

    def test_a_bare_number_has_no_unit(self):
        self.assertEqual(pantry_entry(500), (500.0, None))
        self.assertEqual(pantry_entry("500"), (500.0, None))

    def test_an_entry_with_a_unit_keeps_it(self):
        self.assertEqual(pantry_entry({"amount": 2, "unit": "kg"}), (2.0, "kg"))
        self.assertEqual(pantry_entry({"amount": 2, "unit": " kg "}), (2.0, "kg"))

    def test_an_entry_without_a_unit_is_the_bare_number_again(self):
        self.assertEqual(pantry_entry({"amount": 2}), (2.0, None))
        self.assertEqual(pantry_entry({"amount": 2, "unit": ""}), (2.0, None))

    def test_rubbish_is_nothing_at_home(self):
        for value in (None, "", "två", {"amount": "två"}, {}, [], float("inf"), float("nan")):
            self.assertEqual(pantry_entry(value), (0.0, None), value)


def raw(name, *, quantity, unit):
    return RawProduct(chain="Willys", external_product_id=name, name=name,
                      store_id="2132", store_name="Willys", gtin=None, brand=None,
                      quantity=quantity, unit=unit, size=f"{quantity}{unit}")


class PantryDeductionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = GroceryStore(Path(self._tmp.name) / "grocery.db")
        self.addCleanup(self.db.close)
        self.store = self.db.upsert_store(chain="Willys", external_store_id="2132",
                                          name="Willys test")
        self.engine = RecipePricingEngine(self.db)

    def _add(self, name, price, quantity, unit):
        product = self.db.find_or_create_product(raw(name, quantity=quantity, unit=unit))
        self.db.upsert_current_price(product_id=product.id, store_id=self.store.id,
                                     regular_price=price)

    def _price(self, items, pantry):
        return self.engine.price_list(items, "Willys", self.store.id, pantry=pantry)

    # ---- Fall 1: "Ris 2 (kg) hemma" mot en 500 g-rad -------------------

    def test_two_kilos_of_rice_at_home_covers_a_five_hundred_gram_row(self):
        """FÖRE C9: avdraget blev 2 GRAM och kunden fick köpa ris hon redan
        hade två kilo av."""
        self._add("Ris Jasmin", 29.90, 1000, "g")

        result = self._price([{"name": "Ris", "amount": 500, "unit": "g"}],
                             {"Ris": {"amount": 2, "unit": "kg"}})

        self.assertEqual(result["matchedItems"], [], "raden ska inte behöva köpas alls")
        self.assertEqual(result["missingItems"], [])
        self.assertEqual(result["totalItems"], 0)
        self.assertEqual(result["totalCheckoutCost"], 0)

    def test_a_partly_covered_weight_row_buys_only_the_rest(self):
        """Skafferiet ska kunna räcka DELVIS också - 300 g hemma mot en
        1 200 g-rad lämnar 900 g kvar att köpa."""
        self._add("Ris Jasmin", 20.00, 500, "g")

        result = self._price([{"name": "Ris", "amount": 1200, "unit": "g"}],
                             {"Ris": {"amount": 300, "unit": "g"}})

        row = result["matchedItems"][0]
        self.assertEqual(row["neededAmount"], 900)
        self.assertEqual(row["packages"], 2)

    def test_the_old_bare_number_still_deducts_as_before(self):
        """Bakåtkompatibiliteten: en klient utan enhet (lokalt skafferi,
        cachad app.js) räknas fortfarande i radens basenhet. 2 utan enhet
        mot en gram-rad är två gram - försumbart, men aldrig ett fel åt det
        farliga hållet."""
        self._add("Ris Jasmin", 29.90, 1000, "g")

        result = self._price([{"name": "Ris", "amount": 500, "unit": "g"}], {"Ris": 2})

        self.assertEqual(result["matchedItems"][0]["neededAmount"], 498)

    # ---- Fall 2: "Potatis 1000" (gram) mot "Potatis 4 st" --------------

    def test_a_thousand_grams_of_potato_does_not_cancel_four_pieces(self):
        """FÖRE C9: 1 000 drogs av som 1 000 STYCK och potatisen försvann ur
        både listan och totalen. Gram och styck går inte att jämföra utan att
        gissa en styckvikt - då står varan hellre kvar."""
        self._add("Potatis Fast", 24.90, 1000, "g")

        result = self._price([{"name": "Potatis", "amount": 4, "unit": "st"}],
                             {"Potatis": {"amount": 1000, "unit": "g"}})

        self.assertEqual(len(result["matchedItems"]), 1,
                         "potatisen får inte försvinna ur listan")
        row = result["matchedItems"][0]
        self.assertEqual(row["neededAmount"], 4)
        self.assertEqual(row["neededUnit"], "st")

    def test_the_same_row_without_the_unit_is_exactly_the_old_bug(self):
        """Kontrollen som visar att det ÄR enheten som gör jobbet: samma tal
        utan enhet försvinner fortfarande, precis som före C9. Det är därför
        frontend måste skicka med den."""
        self._add("Potatis Fast", 24.90, 1000, "g")

        result = self._price([{"name": "Potatis", "amount": 4, "unit": "st"}],
                             {"Potatis": 1000})

        self.assertEqual(result["matchedItems"], [])
        self.assertEqual(result["totalItems"], 0)

    def test_pieces_at_home_still_cancel_a_piece_row(self):
        """Motpolen: jämförbara enheter drar av som de ska."""
        self._add("Potatis Fast", 24.90, 1000, "g")

        result = self._price([{"name": "Potatis", "amount": 4, "unit": "st"}],
                             {"Potatis": {"amount": 4, "unit": "st"}})

        self.assertEqual(result["matchedItems"], [])

    def test_volume_at_home_meets_a_deciliter_row(self):
        """Tredje familjen: 5 dl grädde hemma mot en 2 dl-rad. Konverteringen
        går genom volymtabellen, inte genom en gissad basenhet."""
        self._add("Vispgrädde 40%", 25.00, 500, "ml")

        result = self._price([{"name": "Vispgrädde", "amount": 2, "unit": "dl"}],
                             {"Vispgrädde": {"amount": 5, "unit": "dl"}})

        self.assertEqual(result["matchedItems"], [])

    def test_an_unreadable_amount_deducts_nothing(self):
        self._add("Ris Jasmin", 29.90, 1000, "g")

        result = self._price([{"name": "Ris", "amount": 500, "unit": "g"}],
                             {"Ris": {"amount": "en påse", "unit": "kg"}})

        self.assertEqual(result["matchedItems"][0]["neededAmount"], 500)


class PantryCacheKeyTest(unittest.TestCase):
    """Nyckeln i price_week måste tåla den nya formen. Två skafferier med
    samma innehåll i olika ordning är samma skafferi."""

    def test_the_key_is_canonical_for_the_same_pantry(self):
        from services.grocery import api as grocery_api

        def key(pantry):
            return repr(tuple(sorted((str(name), *pantry_entry(value))
                                     for name, value in pantry.items())))

        self.assertTrue(callable(grocery_api.pantry_entry))
        self.assertEqual(key({"Ris": {"amount": 2, "unit": "kg"}, "Potatis": 4}),
                         key({"Potatis": 4, "Ris": {"unit": "kg", "amount": 2}}))
        self.assertNotEqual(key({"Ris": {"amount": 2, "unit": "kg"}}),
                            key({"Ris": {"amount": 2, "unit": "g"}}))


if __name__ == "__main__":
    unittest.main()
