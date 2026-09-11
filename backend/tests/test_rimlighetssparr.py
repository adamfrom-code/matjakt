# -*- coding: utf-8 -*-
"""C8: prisauditen visste vad som var orimligt - motorn prissatte det ändå.

Verkligt fall ur produktionsauditen:

    rostbiff-potatissallad | Rostbiff | 400 g | Willys
    "Rostbiff i Skivor Sverige" | 2 paket | 538,00 kr

Delikatesskivor på ~673 kr/kg prissatta som stekbit.
WHOLE_CUT_FORBIDDEN_DEPARTMENTS räddade inte, för kategorin mappar till
`meat`, inte `coldcuts`. Raden var märkt exactPackaging=True och gick alltså
in i den "säkra" totalen och i Billigast-underlaget.

Två lager täpper till två olika hål:
  (a) namnregeln - rostbiff är STEKEN, inte delikatessdisken,
  (b) rimlighetsspärren - en orimlig rad blir OSÄKER i stället för dyr,
      vilken produkt den än råkar matcha.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import GroceryStore, RawProduct  # noqa: E402
from services.grocery.audit import kilo_price_as_pack_price  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    UNREASONABLE_PACKAGE_COUNT, UNREASONABLE_ROW_COST, RecipePricingEngine,
    product_matches_ingredient, unreasonable_row)


class TheNameRule(unittest.TestCase):
    def test_sliced_deli_roast_beef_is_not_roast_beef(self):
        self.assertFalse(product_matches_ingredient("Rostbiff i Skivor Sverige", "Rostbiff"))
        self.assertFalse(product_matches_ingredient("Rostbiff Deliskivor", "Rostbiff"))

    def test_a_whole_roast_still_matches(self):
        self.assertTrue(product_matches_ingredient("Rostbiff Sverige", "Rostbiff"))
        self.assertTrue(product_matches_ingredient("Rostbiff Färsk Nöt", "Rostbiff"))


class TheSanityRule(unittest.TestCase):
    """Samma tre kontroller som auditen kört offline sedan länge."""

    def test_a_row_over_the_cost_limit_is_unreasonable(self):
        self.assertEqual(unreasonable_row({"totalCost": UNREASONABLE_ROW_COST + 1,
                                           "packages": 2}), "row_cost")
        self.assertIsNone(unreasonable_row({"totalCost": UNREASONABLE_ROW_COST, "packages": 2}))

    def test_too_many_packages_is_unreasonable(self):
        self.assertEqual(unreasonable_row({"totalCost": 40.0,
                                           "packages": UNREASONABLE_PACKAGE_COUNT + 1}),
                         "package_count")
        self.assertIsNone(unreasonable_row({"totalCost": 40.0,
                                            "packages": UNREASONABLE_PACKAGE_COUNT}))

    def test_a_kilo_price_shown_as_a_pack_price_is_unreasonable(self):
        row = {"packageSize": "ca: 850g", "packageAmount": 850, "packageUnit": "g",
               "comparisonPrice": 125.0, "totalCost": 125.0, "packages": 1}
        self.assertEqual(kilo_price_as_pack_price(row), 125.0)
        self.assertEqual(unreasonable_row(row), "kilo_price_as_pack_price")

    def test_an_ordinary_row_is_reasonable(self):
        self.assertIsNone(unreasonable_row({"totalCost": 79.90, "packages": 1}))


def raw(name, *, quantity, unit, size=None):
    return RawProduct(chain="Willys", external_product_id=name, name=name,
                      store_id="2132", store_name="Willys", gtin=None, brand=None,
                      quantity=quantity, unit=unit, size=size or f"{quantity}{unit}")


class TheRoastBeefCase(unittest.TestCase):
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
        return product

    def _price(self):
        # 800 g = receptets 400 g uppskalat till fyra portioner, precis som
        # auditen räknar. Två 400 g-paket à 269 kr = 538,00 kr.
        return self.engine.price_list([{"name": "Rostbiff", "amount": 800, "unit": "g"}],
                                      "Willys", self.store.id)

    def test_the_deli_slices_are_not_priced_as_a_roast_at_all(self):
        """Namnregeln: finns bara skivorna på hyllan har vi inget pris - och
        ett tomt fack är sant, 538 kr är det inte."""
        self._add("Rostbiff i Skivor Sverige", 269.0, 400, "g")

        result = self._price()
        self.assertEqual(result["matchedItems"], [])
        self.assertEqual([m["name"] for m in result["missingItems"]], ["Rostbiff"])

    def test_an_unreasonable_row_becomes_uncertain_not_expensive(self):
        """Rimlighetsspärren fångar samma vara under ett namn som namnregeln
        inte ser ("Skivad", inte "i Skivor"): 538 kr för en ingrediensrad i
        en husmansrätt går inte att tro på, och raden blir osäker."""
        self._add("Rostbiff Skivad Sverige", 269.0, 400, "g")

        result = self._price()
        row = result["matchedItems"][0]
        self.assertTrue(row["rowUncertain"], "orimlig rad ska vara osäker")
        self.assertIsNone(row["totalCost"], "ingen radtotal på 538 kr")
        self.assertEqual(row["unreasonable"], "row_cost")
        self.assertFalse(row["exactPackaging"])
        # Och den får inte smyga in i den säkra totalen eller i täckningen.
        self.assertIsNone(result["totalCheckoutCost"])
        self.assertEqual(result["realPriceItems"], 0)
        self.assertTrue(result["totalIsFloor"])

    def test_a_sensibly_priced_roast_is_untouched(self):
        """Motpolen: spärren får inte göra vanliga rader osäkra."""
        self._add("Rostbiff Sverige", 60.0, 400, "g")

        result = self._price()
        row = result["matchedItems"][0]
        self.assertTrue(row["exactPackaging"])
        self.assertIsNone(row["unreasonable"])
        self.assertEqual(row["packages"], 2)
        self.assertEqual(row["totalCost"], 120.0)

    def test_a_reasonable_candidate_wins_over_an_unreasonable_one(self):
        """EXAKT SLÅR ESTIMAT gäller även här: den orimliga raden blir osäker
        och förlorar därmed mot den rimliga, i stället för att vinna på ett
        lägre tal eller sänka hela kedjans täckning."""
        self._add("Rostbiff Skivad Sverige", 269.0, 400, "g")
        self._add("Rostbiff Sverige", 60.0, 400, "g")

        row = self._price()["matchedItems"][0]
        self.assertEqual(row["productName"], "Rostbiff Sverige")
        self.assertTrue(row["exactPackaging"])

    def test_too_many_packages_makes_the_row_uncertain(self):
        """Andra kontrollen, samma mekanism: fjorton förpackningar är inte
        en inköpslista, det är ett räknefel."""
        self._add("Rostbiff Sverige", 20.0, 60, "g")

        row = self._price()["matchedItems"][0]
        self.assertEqual(row["packages"], 14)
        self.assertEqual(row["unreasonable"], "package_count")
        self.assertIsNone(row["totalCost"])


if __name__ == "__main__":
    unittest.main()
