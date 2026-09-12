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
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()  # MATJAKT_DATA_DIR -> tempkatalog INNAN api_server importeras
from services.grocery import RawProduct  # noqa: E402
from services.grocery import api as grocery_api  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402


def result(chain, total, coverage, matched=10, age=None, missing=()):
    return {"chain": chain, "totalCheckoutCost": total, "coveragePercent": coverage,
            "realPriceItems": matched, "dataAgeSeconds": age,
            "missingItemNames": list(missing)}


class CompareChainsTest(unittest.TestCase):
    def test_names_the_cheapest_when_the_comparison_holds(self):
        comparison = grocery_api.compare_chains([
            result("Willys", 320.0, 95), result("Hemköp", 380.0, 95)])
        self.assertEqual(comparison["cheapestChain"], "Willys")
        self.assertEqual(comparison["savings"], 60.0)
        self.assertIsNone(comparison["reason"])

    def test_an_incomplete_basket_is_never_crowned_over_a_complete_one(self):
        """Täckningströskeln ensam räckte inte. En kedja på 85 % (17 av 20
        varor) klarade filtret och krontes över en kedja på 100 % - dess
        total var lägre för att tre varor SAKNADES, inte för att butiken var
        billig. De tre kunde kosta mer än de 50 kr som utlovades som
        besparing, och då är beskedet falskt om användarens pengar."""
        comparison = grocery_api.compare_chains([
            result("A", 400.0, 85, missing=["Kycklingfilé", "Grädde", "Basmatiris"]),
            result("B", 450.0, 100)])
        self.assertIsNone(comparison["cheapestChain"])
        self.assertIsNone(comparison["savings"])
        self.assertEqual(comparison["reason"], "different_baskets")
        # Vilka varor som skiljer, så gränssnittet kan säga varför i stället
        # för att bara tiga.
        self.assertEqual(comparison["differingItems"],
                         ["Basmatiris", "Grädde", "Kycklingfilé"])

    def test_chains_missing_the_same_items_may_still_be_compared(self):
        """Saknar båda samma vara svarar totalerna fortfarande på samma
        fråga - då är jämförelsen ärlig och kröningen tillåten."""
        comparison = grocery_api.compare_chains([
            result("Willys", 320.0, 95, missing=["Saffran"]),
            result("Hemköp", 380.0, 95, missing=["Saffran"])])
        self.assertEqual(comparison["cheapestChain"], "Willys")
        self.assertEqual(comparison["savings"], 60.0)

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
        # Skärpt 2026-09-01: ett gissat paketantal är INTE ett säkert pris.
        # Det räknas som estimat och hålls utanför täckningen - en kedja ska
        # aldrig kunna vinna Billigast på en underskattad gissning.
        self.assertEqual(listing["realPriceItems"], 0)

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


class CampaignDealsSmokeTest(unittest.TestCase):
    """Kampanjlistan gick sönder i produktion TVÅ gånger av samma halva
    patch (konstant + SQL-rad som bara körs vid anrop). En tom test-DB
    hade dessutom dolt felet - noll kedjor betyder att frågan aldrig
    exekveras. Därför seedas en riktig kampanjrad här, så själva SQL:en
    bevisligen körs varje testkörning."""

    def test_campaign_deals_executes_the_real_query(self):
        import tempfile
        from pathlib import Path
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "grocery.db"
        real = grocery_api.DB_PATH
        grocery_api.DB_PATH = db_path
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", real))
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)

        db = GroceryStore(db_path)
        try:
            store = db.upsert_store(chain="Willys", external_store_id="2132", name="Willys test",
                                    city=None, postal_code=None, address=None,
                                    latitude=None, longitude=None, active=True)
            product = db.find_or_create_product(RawProduct(
                chain="Willys", external_product_id="willys-kampanj", name="Kaffe Mellanrost",
                store_id="2132", store_name="Willys", gtin=None, brand=None,
                size="450g", quantity=450.0, unit="g",
                category="Skafferi > Kaffe"))
            db.upsert_current_price(product_id=product.id, store_id=store.id,
                                    regular_price=79.0, campaign_price=49.0,
                                    member_price=None, multibuy_price=None, unit_price=None,
                                    currency="SEK", source_url=None, fetched_at=None)
        finally:
            db.close()

        result = grocery_api.campaign_deals()
        willys = result["deals"].get("Willys") or []
        self.assertTrue(willys, "den seedade kampanjen måste komma ut ur frågan")
        self.assertEqual(willys[0]["campaignPrice"], 49.0)


class ChainHealthTest(unittest.TestCase):
    """Driftstatusen per kedja: EN rad ägaren kan läsa i stället för att
    jämföra produktantal mot tidsstämplar mot releaselistan i huvudet.

    Det viktiga är inte att fälten finns, utan att de aldrig ljuger åt det
    optimistiska hållet: en kedja som inte importerats får inte se frisk ut,
    och en lyckad import får aldrig i sig själv göra en kedja publik.
    """

    def _entry(self, chain="Coop", status="working_via_primat", last=None, success=None):
        return {"chain": chain, "status": status, "lastRun": last, "lastSuccessfulRun": success}

    def test_a_chain_that_never_imported_is_not_healthy(self):
        health = grocery_api.chain_health(self._entry())
        self.assertEqual(health["status"], "never_imported")
        self.assertIsNone(health["ageHours"])
        self.assertFalse(health["released"])

    def test_a_failed_run_with_no_earlier_success_is_failed(self):
        health = grocery_api.chain_health(self._entry(
            last={"status": "failed", "finishedAt": 1000.0, "errorMessage": "429 quota"}))
        self.assertEqual(health["status"], "failed")
        self.assertIn("429", health["reason"])

    def test_a_failed_run_after_a_good_one_is_not_failed(self):
        """Kärnan i last-good: nattens fel är ett driftproblem, inte ett
        kundproblem. Användarna får gårdagens priser, så kedjan är inte
        'failed' - den har en egen status, se failing nedan."""
        now = 100000.0
        health = grocery_api.chain_health(self._entry(
            last={"status": "failed", "finishedAt": now - 60, "errorMessage": "timeout"},
            success={"status": "success", "finishedAt": now - 3600}), now=now)
        self.assertNotEqual(health["status"], "failed")

    def test_a_failed_attempt_shows_even_when_yesterday_succeeded(self):
        """D4. En körning som ger noll rader faller på publiceringsgaten och
        märks "failed" - men statusen härleddes bara ur senaste LYCKADE
        körning, så en success från i går gjorde kedjan frisk. Willys byter
        API-form tisdag natt, och onsdagen igenom ser allt bra ut."""
        now = 1_000_000.0
        health = grocery_api.chain_health(self._entry(
            chain="Willys", status="working",
            last={"status": "failed", "finishedAt": now - 3600,
                  "errorMessage": "inga rader att publicera"},
            success={"status": "success", "finishedAt": now - 25 * 3600}), now=now)
        self.assertEqual(health["status"], "failing")
        self.assertIn("inga rader", health["reason"])
        # Åldern på det kunderna faktiskt får står i samma besked - annars går
        # det inte att se hur bråttom det är.
        self.assertIn("25", health["reason"])

    def test_a_blocked_attempt_is_not_a_failed_attempt(self):
        """En Primat-körning som slår i dygnskvoten märks blocked, behåller
        det den hann hämta och slås ihop av publiceringen. Larmade vi på det
        skulle larmet komma varje natt tills katalogen är hel."""
        now = 1_000_000.0
        health = grocery_api.chain_health(self._entry(
            chain="Willys", status="working",
            last={"status": "blocked", "finishedAt": now - 3600},
            success={"status": "success", "finishedAt": now - 3600}), now=now)
        self.assertEqual(health["status"], "healthy")

    def test_a_failed_attempt_beats_a_structurally_limited_provider(self):
        """limited säger vad providern kan leverera som bäst, och förklarar
        aldrig varför en körning sprack."""
        now = 1_000_000.0
        health = grocery_api.chain_health(self._entry(
            chain="Lidl", status="partial_via_primat",
            last={"status": "failed", "finishedAt": now - 60, "errorMessage": "500 från Primat"},
            success={"status": "success", "finishedAt": now - 3600}), now=now)
        self.assertEqual(health["status"], "failing")

    def test_data_older_than_the_window_is_stale(self):
        now = 1_000_000.0
        health = grocery_api.chain_health(self._entry(
            success={"status": "success",
                     "finishedAt": now - grocery_api.CHAIN_STALE_AFTER_SECONDS - 60}), now=now)
        self.assertEqual(health["status"], "stale")

    def test_a_missed_night_alone_does_not_alarm(self):
        """36 timmar rymmer en missad natt för en kedja som inte är släppt.
        Larmar vi på 25 timmar skriker systemet varje gång ett jobb blir en
        timme sent."""
        now = 1_000_000.0
        health = grocery_api.chain_health(self._entry(
            success={"status": "success", "finishedAt": now - 25 * 3600}), now=now)
        self.assertNotEqual(health["status"], "stale")

    def test_a_released_chain_is_judged_the_same_morning(self):
        """D4. En SLÄPPT kedja är den kunden prissätts mot, och nattens
        resultat ska vara bedömt samma morgon. 28 timmar betyder att natten
        uteblev: för Willys är det inaktuellt, för ICA ryms det fortfarande
        inom en missad natt."""
        now = 1_000_000.0
        körning = {"status": "success", "finishedAt": now - 28 * 3600}
        släppt = grocery_api.chain_health(self._entry(
            chain="Willys", status="working", success=körning), now=now)
        self.assertEqual(släppt["status"], "stale")
        osläppt = grocery_api.chain_health(self._entry(chain="Coop", success=körning), now=now)
        self.assertNotEqual(osläppt["status"], "stale")

    def test_a_normal_night_never_reaches_the_released_window(self):
        """Gränsen får inte larma på en kedja som fungerar. Precis innan
        nästa nattjobb är datan ~24 timmar gammal."""
        self.assertGreater(grocery_api.RELEASED_CHAIN_STALE_AFTER_SECONDS, 25 * 3600)
        now = 1_000_000.0
        health = grocery_api.chain_health(self._entry(
            chain="Willys", status="working",
            success={"status": "success", "finishedAt": now - 24 * 3600}), now=now)
        self.assertEqual(health["status"], "healthy")

    def test_fresh_data_on_an_unreleased_chain_never_reads_as_released(self):
        """En lyckad import gör ALDRIG en kedja publik. Den blir
        ready_for_release och väntar på ett uttryckligt beslut."""
        now = 1_000_000.0
        health = grocery_api.chain_health(self._entry(
            chain="Coop", success={"status": "success", "finishedAt": now - 3600}), now=now)
        self.assertEqual(health["status"], "ready_for_release")
        self.assertFalse(health["released"])
        self.assertNotIn("Coop", grocery_api.RELEASED_CHAINS)

    def test_a_released_chain_with_fresh_data_is_healthy(self):
        now = 1_000_000.0
        health = grocery_api.chain_health(self._entry(
            chain="Willys", status="working",
            success={"status": "success", "finishedAt": now - 3600}), now=now)
        self.assertEqual(health["status"], "healthy")
        self.assertTrue(health["released"])

    def test_a_structurally_limited_provider_is_limited_not_pending(self):
        """Lidl får aldrig läsas som 'snart klar'. Det finns inga
        per-produkt-priser att vänta på."""
        health = grocery_api.chain_health(self._entry(chain="Lidl", status="partial_via_primat"))
        self.assertEqual(health["status"], "limited")

    def test_every_chain_in_the_panel_gets_a_health_block(self):
        for entry in grocery_api.provider_status():
            self.assertIn("health", entry, entry["chain"])
            self.assertIn(entry["health"]["status"],
                          {"limited", "never_imported", "failed", "failing", "stale",
                           "healthy", "ready_for_release"}, entry["chain"])


class BasketAgeTest(unittest.TestCase):
    """Kassans färskhet.

    Åldern gick in i compare_chains age-filter, så den avgjorde vilken kedja
    som fick krönas billigast. Räknades den fel kunde en kedja med
    veckogamla priser kröna sig mot en med färska.
    """

    NU = 1_000_000.0
    TIMME = 3600.0

    def _rad(self, verified=None, fetched=None, total=42.0):
        return {"verifiedAt": verified, "fetchedAt": fetched, "totalCost": total}

    def test_the_age_is_the_oldest_row_not_the_newest(self):
        """En kasse är inte färskare än sin äldsta prisrad. Förut svarade
        åldern på en annan fråga - "när uppdaterades något i butiken senast?"
        - och en enda färsk rad nollställde åldern för hela kassen."""
        resultat = {"matchedItems": [
            self._rad(verified=self.NU - 200 * self.TIMME),   # åtta dygn
            self._rad(verified=self.NU - 1 * self.TIMME),     # en timme
        ]}
        ålder = grocery_api._result_age_seconds(resultat, now=self.NU)
        self.assertAlmostEqual(ålder, 200 * self.TIMME, delta=1)

    def test_a_row_that_did_not_count_does_not_affect_the_age(self):
        """En rad utan totalCost räknades inte in i summan, och dess ålder
        säger därför ingenting om kassan."""
        resultat = {"matchedItems": [
            self._rad(verified=self.NU - 2 * self.TIMME),
            self._rad(verified=self.NU - 500 * self.TIMME, total=None),
        ]}
        ålder = grocery_api._result_age_seconds(resultat, now=self.NU)
        self.assertAlmostEqual(ålder, 2 * self.TIMME, delta=1)

    def test_verified_beats_fetched(self):
        """När priset senast BEKRÄFTADES i butiken är det som betyder något,
        inte när vi råkade hämta hem raden."""
        resultat = {"matchedItems": [
            self._rad(verified=self.NU - 50 * self.TIMME, fetched=self.NU - 1),
        ]}
        ålder = grocery_api._result_age_seconds(resultat, now=self.NU)
        self.assertAlmostEqual(ålder, 50 * self.TIMME, delta=1)

    def test_fetched_is_used_when_nothing_was_verified(self):
        resultat = {"matchedItems": [self._rad(fetched=self.NU - 3 * self.TIMME)]}
        ålder = grocery_api._result_age_seconds(resultat, now=self.NU)
        self.assertAlmostEqual(ålder, 3 * self.TIMME, delta=1)

    def test_a_basket_without_priced_rows_has_no_age(self):
        """Ingen kasse att åldersbedöma. En sådan kasse har realPriceItems=0
        och kan ändå aldrig krönas billigast."""
        self.assertIsNone(grocery_api._result_age_seconds({"matchedItems": []}, now=self.NU))
        self.assertIsNone(grocery_api._result_age_seconds({}, now=self.NU))

    def test_an_old_basket_is_excluded_from_the_crowning(self):
        """Hela poängen: med rätt ålder faller en gammal kedja ur
        jämförelsen i stället för att krönas billigast."""
        gammal = result("A", 300.0, 95)
        gammal["dataAgeSeconds"] = grocery_api.MAX_AGE_SECONDS_FOR_COMPARISON + 1
        färsk = result("B", 400.0, 95)
        färsk["dataAgeSeconds"] = 3600
        jämförelse = grocery_api.compare_chains([gammal, färsk])
        self.assertIsNone(jämförelse["cheapestChain"])
        self.assertEqual(jämförelse["reason"], "too_few_comparable_chains")
