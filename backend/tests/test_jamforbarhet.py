# -*- coding: utf-8 -*-
"""C6: referenspriserna hade ingen åldersgräns, och "comparable" var en
enda flagga för två olika fel.

MAX_STORE_PRICE_AGE_SECONDS (fyra dygn) gällde bara VERIFIERADE butikspriser.
Referenspriserna lades in utan cutoff, och enda spärren var jämförelsens
fjortondygnsgräns - som bara blockerar KRÖNINGEN, inte visningen. Dog City
Gross-importen i tre månader såg kunden fortfarande fulla priser och en
total.

Dessutom slog `comparable` ihop TÄCKNING och ÅLDER i ett enda nej, så UI:t
bara kunde säga "För få av varorna har aktuellt pris..." - rätt text i
hälften av fallen, fel i resten.
"""

import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import api as grocery_api  # noqa: E402
from services.grocery import register  # noqa: E402
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    COMPARISON_LOW_COVERAGE, COMPARISON_NO_REAL_PRICES, COMPARISON_TOO_OLD,
    MAX_REFERENCE_PRICE_AGE_SECONDS, RecipePricingEngine,
    comparability_reasons)
from services.grocery.store import GroceryStore  # noqa: E402

APP_JS = Path(__file__).resolve().parents[2] / "frontend" / "app" / "app.js"


def _reasons(*, coverage=100, real=5, age=None):
    return comparability_reasons(
        coverage_percent=coverage, real_price_items=real, age_seconds=age,
        min_coverage=grocery_api.MIN_COVERAGE_FOR_COMPARISON,
        max_age_seconds=grocery_api.MAX_AGE_SECONDS_FOR_COMPARISON)


class ComparabilityReasonCodes(unittest.TestCase):
    """Ett test per orsakskod - det är acceptanskriteriet."""

    def test_a_fully_priced_fresh_chain_has_no_reasons(self):
        self.assertEqual(_reasons(), [])

    def test_low_coverage_is_its_own_code(self):
        self.assertEqual(_reasons(coverage=40), [COMPARISON_LOW_COVERAGE])

    def test_too_old_is_its_own_code(self):
        age = grocery_api.MAX_AGE_SECONDS_FOR_COMPARISON + 1
        self.assertEqual(_reasons(age=age), [COMPARISON_TOO_OLD])

    def test_no_real_prices_is_its_own_code(self):
        """Noll säkra rader är inte "låg täckning" - det är ingen prisbild
        alls, och förtjänar sin egen mening."""
        self.assertEqual(_reasons(coverage=0, real=0), [COMPARISON_NO_REAL_PRICES])

    def test_both_problems_are_both_reported(self):
        """Att bara nämna det ena gör att den som åtgärdar det får samma
        varning igen och tror att inget hände."""
        age = grocery_api.MAX_AGE_SECONDS_FOR_COMPARISON + 1
        self.assertEqual(_reasons(coverage=40, age=age),
                         [COMPARISON_LOW_COVERAGE, COMPARISON_TOO_OLD])

    def test_an_age_exactly_on_the_limit_is_still_comparable(self):
        self.assertEqual(_reasons(age=grocery_api.MAX_AGE_SECONDS_FOR_COMPARISON), [])


class ReasonCodesReachTheClient(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "grocery.db"
        self._real = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db_path
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", self._real))
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)

        db = GroceryStore(self.db_path)
        try:
            store = db.upsert_store(chain="Willys", external_store_id="2132",
                                    name="Willys test", active=True)
            product = db.find_or_create_product(RawProduct(
                chain="Willys", external_product_id="w-ris", name="Ris Jasmin",
                store_id="2132", store_name="Willys", gtin=None, brand=None,
                size="1kg", quantity=1000.0, unit="g",
                category="Skafferi > Pasta, ris & mat > Ris"))
            db.upsert_current_price(product_id=product.id, store_id=store.id,
                                    regular_price=25.0)
        finally:
            db.close()

    def test_a_thinly_covered_chain_says_so_by_code(self):
        payload = grocery_api.price_week([
            {"name": "Ris", "amount": 500, "unit": "g"},
            {"name": "Struts", "amount": 1, "unit": "st"}])
        willys = next(r for r in payload["results"] if r["chain"] == "Willys")
        self.assertFalse(willys["comparable"])
        self.assertEqual(willys["comparableReasons"], [COMPARISON_LOW_COVERAGE])

    def test_a_comparable_chain_carries_an_empty_reason_list(self):
        payload = grocery_api.price_week([{"name": "Ris", "amount": 500, "unit": "g"}])
        willys = next(r for r in payload["results"] if r["chain"] == "Willys")
        self.assertTrue(willys["comparable"])
        self.assertEqual(willys["comparableReasons"], [])

    def test_the_app_has_one_sentence_per_reason_code(self):
        """Hela vägen ut i UI-texten: en kedja som är för GAMMAL fick förr
        meningen om för få priser. Låser att app.js bär en egen text per
        kod - samma speglingsprincip som resten av test_frontend_contract."""
        app = APP_JS.read_text(encoding="utf-8")
        match = re.search(r"const COMPARABILITY_WARNINGS = \{(.*?)\};", app, re.S)
        self.assertIsNotNone(match, "COMPARABILITY_WARNINGS saknas i app.js")
        block = match.group(1)
        meningar = dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", block))
        self.assertEqual(set(meningar), {COMPARISON_TOO_OLD, COMPARISON_LOW_COVERAGE,
                                         COMPARISON_NO_REAL_PRICES})
        self.assertEqual(len(set(meningar.values())), 3, "koderna delar text")
        self.assertIn("gamla", meningar[COMPARISON_TOO_OLD])
        self.assertIn("För få", meningar[COMPARISON_LOW_COVERAGE])


class ReferencePricesExpire(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = GroceryStore(Path(self._tmp.name) / "grocery.db")
        self.addCleanup(self.db.close)
        register.ensure_chains(self.db)
        self.store = self.db.upsert_store(chain="City Gross", external_store_id="9",
                                          name="City Gross test")
        self.product = self.db.find_or_create_product(RawProduct(
            chain="City Gross", external_product_id="cg-ris", name="Ris Jasmin",
            store_id="9", store_name="City Gross", gtin=None, brand=None,
            size="1kg", quantity=1000.0, unit="g",
            category="Skafferi > Pasta, ris & mat > Ris"))

    def _price_rice(self):
        engine = RecipePricingEngine(self.db)
        return engine.price_list([{"name": "Ris", "amount": 500, "unit": "g"}],
                                 "City Gross", self.store.id)

    def test_a_reference_price_older_than_the_limit_is_not_used(self):
        """Dör importen i tre månader ska kunden INTE se fulla priser och en
        total - varan faller ur prisbilden och redovisas som saknad."""
        self.db.upsert_reference_price(
            product_id=self.product.id, chain="City Gross", regular_price=25.0,
            source="test", verified_at=time.time() - MAX_REFERENCE_PRICE_AGE_SECONDS - 3600)

        result = self._price_rice()
        self.assertEqual(result["matchedItems"], [])
        self.assertEqual([m["name"] for m in result["missingItems"]], ["Ris"])

    def test_a_reference_price_inside_the_limit_is_used(self):
        self.db.upsert_reference_price(
            product_id=self.product.id, chain="City Gross", regular_price=25.0,
            source="test", verified_at=time.time() - MAX_REFERENCE_PRICE_AGE_SECONDS + 3600)

        result = self._price_rice()
        self.assertEqual(result["totalCheckoutCost"], 25.0)
        self.assertEqual(result["matchedItems"][0]["priceTier"], "REFERENCE_PRICE")


if __name__ == "__main__":
    unittest.main()
