# -*- coding: utf-8 -*-
"""Tests for the grocery API layer - the thing api_server.py talks to.

The interesting part is compare_chains(): naming a cheapest chain is a
factual claim about the user's money, and this app has already shipped that
claim wrongly once (the "Coop 351 / Willys 351 / ICA 351, one marked
cheapest" bug). Each block below corresponds to a way the comparison can be
meaningless while still producing numbers.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery import RawProduct  # noqa: E402
from services.grocery import api as grocery_api  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402


def result(chain, total, coverage, matched=10, age=None):
    return {"chain": chain, "totalCheckoutCost": total, "coveragePercent": coverage,
            "realPriceItems": matched, "dataAgeSeconds": age}


class CompareChainsTest(unittest.TestCase):
    def test_names_the_cheapest_when_the_comparison_holds(self):
        comparison = grocery_api.compare_chains([
            result("Willys", 320.0, 95), result("Hemköp", 380.0, 95)])
        self.assertEqual(comparison["cheapestChain"], "Willys")
        self.assertEqual(comparison["savings"], 60.0)
        self.assertIsNone(comparison["reason"])

    def test_one_chain_alone_is_not_a_comparison(self):
        comparison = grocery_api.compare_chains([result("Willys", 320.0, 95)])
        self.assertIsNone(comparison["cheapestChain"])
        self.assertEqual(comparison["reason"], "too_few_comparable_chains")

    def test_a_poorly_covered_chain_is_not_crowned_cheapest(self):
        """The whole point: 120 kr covering 3 of 20 items is not cheap, it is
        incomplete. Without this the WORST-covered chain always wins."""
        comparison = grocery_api.compare_chains([
            result("Willys", 120.0, 15, matched=3), result("Hemköp", 380.0, 95)])
        self.assertIsNone(comparison["cheapestChain"])
        self.assertEqual(comparison["reason"], "too_few_comparable_chains")

    def test_identical_totals_yield_no_winner(self):
        comparison = grocery_api.compare_chains([
            result("Willys", 351.0, 95), result("ICA", 351.0, 95),
            result("Coop", 351.0, 95)])
        self.assertIsNone(comparison["cheapestChain"])
        self.assertEqual(comparison["reason"], "all_totals_identical")

    def test_stale_data_is_not_compared_against_fresh_data(self):
        old = grocery_api.MAX_AGE_SECONDS_FOR_COMPARISON + 1
        comparison = grocery_api.compare_chains([
            result("Willys", 320.0, 95, age=old), result("Hemköp", 380.0, 95, age=60)])
        self.assertIsNone(comparison["cheapestChain"])

    def test_a_chain_with_zero_matches_never_wins_at_zero_kronor(self):
        """An empty chain totals 0 kr, which would otherwise read as the
        cheapest shop in Sweden."""
        comparison = grocery_api.compare_chains([
            result("Tom kedja", 0.0, 0, matched=0), result("Willys", 320.0, 95)])
        self.assertIsNone(comparison["cheapestChain"])

    def test_totals_are_still_returned_when_the_claim_is_blocked(self):
        results = [result("Willys", 351.0, 95), result("ICA", 351.0, 95)]
        grocery_api.compare_chains(results)
        self.assertEqual([r["totalCheckoutCost"] for r in results], [351.0, 351.0])


class PriceWeekTest(unittest.TestCase):
    """End-to-end against a real (temporary) database, so the SQL and the
    engine are exercised together rather than mocked apart."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "grocery.db"
        self._real_db_path = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db_path
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", self._real_db_path))
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)

        db = GroceryStore(self.db_path)
        try:
            for chain, external, price in (("Willys", "2132", 25.0), ("Hemköp", "4256", 31.0)):
                store = db.upsert_store(chain=chain, external_store_id=external, name=f"{chain} test",
                                        city=None, postal_code=None, address=None,
                                        latitude=None, longitude=None, active=True)
                product = db.find_or_create_product(RawProduct(
                    chain=chain, external_product_id=f"{chain}-ris", name="Ris Jasmin",
                    store_id=external, store_name=chain, gtin=None, brand=None,
                    size="1kg", quantity=1000.0, unit="g",
                    category="Skafferi > Pasta, ris & mat > Ris"))
                db.upsert_current_price(product_id=product.id, store_id=store.id,
                                        regular_price=price, campaign_price=None,
                                        member_price=None, multibuy_price=None, unit_price=None,
                                        currency="SEK", source_url=None, fetched_at=None)
        finally:
            db.close()

    def test_prices_the_same_item_at_both_chains(self):
        payload = grocery_api.price_week([{"name": "Ris", "amount": 500, "unit": "g"}])
        totals = {r["chain"]: r["totalCheckoutCost"] for r in payload["results"]}
        # 500 g from a 1 kg bag is one whole bag, not half of one.
        self.assertEqual(totals, {"Willys": 25.0, "Hemköp": 31.0})

    def test_an_unmatched_ingredient_is_reported_not_hidden(self):
        payload = grocery_api.price_week([
            {"name": "Ris", "amount": 500, "unit": "g"},
            {"name": "Struts", "amount": 1, "unit": "st"}])
        willys = next(r for r in payload["results"] if r["chain"] == "Willys")
        self.assertEqual(willys["missingItemNames"], ["Struts"])
        self.assertEqual(willys["coveragePercent"], 50)
        # The missing item must not have quietly reduced the total.
        self.assertEqual(willys["totalCheckoutCost"], 25.0)

    def test_missing_items_stay_in_the_one_items_list(self):
        """Separate arrays pushed every UI into re-merging them, and a UI that
        forgot would silently drop unpriced items from the shopping list."""
        payload = grocery_api.price_week([
            {"name": "Ris", "amount": 500, "unit": "g"},
            {"name": "Struts", "amount": 1, "unit": "st"}])
        willys = next(r for r in payload["results"] if r["chain"] == "Willys")
        statuses = {item["ingredient"]: item["priceStatus"] for item in willys["items"]}
        self.assertEqual(statuses, {"Ris": "current", "Struts": "missing"})
        struts = next(i for i in willys["items"] if i["ingredient"] == "Struts")
        # No price at all, not a filled-in guess.
        self.assertIsNone(struts["totalCost"])
        self.assertIsNone(struts["productName"])

    def test_savings_are_only_reported_for_the_crowned_chain(self):
        payload = grocery_api.price_week([{"name": "Ris", "amount": 500, "unit": "g"}])
        by_chain = {r["chain"]: r for r in payload["results"]}
        self.assertEqual(payload["comparison"]["cheapestChain"], "Willys")
        self.assertEqual(by_chain["Willys"]["savings"], 6.0)
        # The pricier chain must not display a "savings" figure of its own.
        self.assertIsNone(by_chain["Hemköp"]["savings"])

    def test_store_identity_travels_with_the_result(self):
        payload = grocery_api.price_week([{"name": "Ris", "amount": 500, "unit": "g"}])
        willys = next(r for r in payload["results"] if r["chain"] == "Willys")
        self.assertEqual(willys["store"]["name"], "Willys test")
        self.assertEqual(willys["store"]["externalStoreId"], "2132")

    def test_a_chain_with_no_data_is_left_out_entirely(self):
        payload = grocery_api.price_week([{"name": "Ris", "amount": 500, "unit": "g"}],
                                         chains=["Willys", "Coop"])
        self.assertEqual([r["chain"] for r in payload["results"]], ["Willys"])

    def test_shopping_list_returns_the_real_product_to_buy(self):
        listing = grocery_api.shopping_list([{"name": "Ris", "amount": 1500, "unit": "g"}], "Willys")
        item = listing["items"][0]
        self.assertEqual(item["productName"], "Ris Jasmin")
        self.assertEqual(item["packages"], 2)      # 1500 g needs two 1 kg bags
        self.assertEqual(item["totalCost"], 50.0)
        self.assertEqual(item["category"], "Skafferi > Pasta, ris & mat > Ris")
        self.assertEqual(item["priceStatus"], "current")

    def test_shopping_list_for_an_unknown_chain_says_so(self):
        """Not an empty list priced at 0 kr - that would read as the cheapest
        shop in Sweden."""
        listing = grocery_api.shopping_list([{"name": "Ris", "amount": 500, "unit": "g"}], "Coop")
        self.assertEqual(listing["error"], "no_data_for_chain")
        self.assertEqual(listing["items"], [])
        self.assertIsNone(listing["totalCheckoutCost"])

    def test_an_unconvertible_unit_is_estimated_not_silently_exact(self):
        """Recipe in "st" against a pack measured in "g": the money is real,
        the package count is a guess, and the shopper is the one who can tell
        whether one pack is enough."""
        listing = grocery_api.shopping_list([{"name": "Ris", "amount": 2, "unit": "st"}], "Willys")
        item = listing["items"][0]
        self.assertEqual(item["priceStatus"], "estimated")
        self.assertEqual(listing["estimatedItems"], 1)
        self.assertEqual(listing["realPriceItems"], 1)

    def test_summary_reports_what_the_database_actually_holds(self):
        summary = grocery_api.database_summary()
        chains = {c["chain"]: c for c in summary["chains"]}
        self.assertEqual(sorted(chains), ["Hemköp", "Willys"])
        self.assertEqual(chains["Willys"]["products"], 1)
        self.assertEqual(chains["Willys"]["withCategory"], 1)


if __name__ == "__main__":
    unittest.main()


class CoverageInvariant(unittest.TestCase):
    """Täckning kan aldrig överstiga 100 %: en användare såg "21 av 20
    varor". Räknaren och nämnaren ska komma ur samma resultat, och motorn
    får aldrig producera fler prissatta rader än rader."""

    def test_real_price_items_never_exceed_total_items(self):
        from services.grocery.pricing import RecipePricingEngine
        store = grocery_api.open_store()
        try:
            engine = RecipePricingEngine(store)
            row = grocery_api._store_row_for(store, "Willys")
            if row is None:
                self.skipTest("ingen Willys-data lokalt")
            items = [
                {"name": "Pasta", "amount": 400, "unit": "g"},
                {"name": "Köttfärs", "amount": 500, "unit": "g"},
                {"name": "Grädde", "amount": 2, "unit": "dl"},
                # samma namn två gånger med olika enhet - serverns delade rader
                {"name": "Morötter", "amount": 2, "unit": "st"},
                {"name": "Morötter", "amount": 200, "unit": "g"},
                {"name": "Påhittad ingrediens utan produkt", "amount": 1, "unit": "st"},
            ]
            result = engine.price_list(items, "Willys", row["id"])
            self.assertLessEqual(result["realPriceItems"], result["totalItems"])
            self.assertLessEqual(result["coveragePercent"], 100)
            self.assertEqual(result["totalItems"], len(items))
        finally:
            store.close()


class ExcludeItemsRespectRemovals(unittest.TestCase):
    """En vara användaren tagit bort ur listan ("finns hemma", "redan köpt")
    får inte fortsätta prissättas via recipeIds-vägen, som annars aggregerar
    om hela veckan på servern och ignorerar borttagningen."""

    def _handler(self):
        import api_server
        handler = api_server.ApiHandler.__new__(api_server.ApiHandler)
        return handler

    def test_excluded_names_are_dropped_case_insensitively(self):
        handler = self._handler()
        items, error = handler._pricing_items({
            "items": [{"name": "Falukorv", "amount": 800, "unit": "g"},
                      {"name": "Mjölk", "amount": 1, "unit": "l"}],
            "excludeItems": ["falukorv"]})
        self.assertIsNone(error)
        self.assertEqual([i["name"] for i in items], ["Mjölk"])

    def test_removing_everything_is_a_valid_empty_list_not_an_error(self):
        handler = self._handler()
        items, error = handler._pricing_items({
            "items": [{"name": "Falukorv", "amount": 800, "unit": "g"}],
            "excludeItems": ["Falukorv"]})
        self.assertIsNone(error)
        self.assertEqual(items, [])

    def test_no_exclusions_changes_nothing(self):
        handler = self._handler()
        items, error = handler._pricing_items({
            "items": [{"name": "Falukorv", "amount": 800, "unit": "g"}]})
        self.assertIsNone(error)
        self.assertEqual(len(items), 1)
