"""Tests for the Recipe Pricing Engine.

The two things that matter most here, and that the assertions are built
around:
  1. Package maths - a shopper buys whole packages, so needing 600 g of a
     700 g product costs one full package, and 1200 g costs two.
  2. Never inventing a price - an unmatched ingredient is reported missing
     and lowers coverage, rather than being quietly dropped (which would
     make a chain look cheaper than it is).
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery import GroceryStore, RawProduct  # noqa: E402
from services.grocery import api as grocery_api  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    MAX_CAMPAIGN_AGE_SECONDS, RecipePricingEngine, convert_amount,
    effective_price, packages_needed, product_matches_ingredient,
)
from services.recipes import RecipeStore  # noqa: E402
from services.recipes import api as recipes_api  # noqa: E402
from services.recipes import prices as recipe_prices  # noqa: E402


class UnitConversionTest(unittest.TestCase):
    def test_converts_within_mass(self):
        self.assertEqual(convert_amount(1, "kg", "g"), 1000)
        self.assertEqual(convert_amount(500, "g", "kg"), 0.5)

    def test_converts_within_volume(self):
        self.assertEqual(convert_amount(1, "l", "ml"), 1000)
        self.assertEqual(convert_amount(2, "dl", "ml"), 200)

    def test_refuses_to_cross_mass_and_volume(self):
        """Converting g<->ml would require a density we don't have; guessing
        one would silently produce a wrong package count."""
        self.assertIsNone(convert_amount(500, "g", "ml"))
        self.assertIsNone(convert_amount(1, "l", "kg"))

    def test_refuses_incomparable_units(self):
        self.assertIsNone(convert_amount(2, "st", "g"))
        self.assertIsNone(convert_amount(2, None, "g"))

    def test_identical_units_pass_through(self):
        self.assertEqual(convert_amount(3, "st", "st"), 3)


class PackageMathTest(unittest.TestCase):
    """The spec's own worked examples."""

    def test_600g_need_from_a_700g_package_is_one_package(self):
        self.assertEqual(packages_needed(600, "g", 700, "g"), 1)

    def test_1200g_need_from_a_700g_package_is_two_packages(self):
        self.assertEqual(packages_needed(1200, "g", 700, "g"), 2)

    def test_900g_need_from_a_1kg_package_is_one_package(self):
        self.assertEqual(packages_needed(900, "g", 1, "kg"), 1)

    def test_exact_fit_does_not_round_up_to_two(self):
        """700 g needed from a 700 g package is one package - a floating point
        slip here would make every exact fit cost double."""
        self.assertEqual(packages_needed(700, "g", 700, "g"), 1)
        self.assertEqual(packages_needed(1000, "g", 1, "kg"), 1)

    def test_slightly_over_rounds_up(self):
        self.assertEqual(packages_needed(701, "g", 700, "g"), 2)

    def test_zero_need_costs_nothing(self):
        self.assertEqual(packages_needed(0, "g", 700, "g"), 0)

    def test_incomparable_units_return_none_not_a_guess(self):
        self.assertIsNone(packages_needed(2, "st", 700, "g"))

    def test_missing_package_size_returns_none(self):
        self.assertIsNone(packages_needed(600, "g", None, None))


class IngredientMatchingTest(unittest.TestCase):
    def test_matches_the_right_product(self):
        self.assertTrue(product_matches_ingredient("Kycklingfilé Naturell 700g", "Kycklingfilé"))

    def test_accent_and_case_insensitive(self):
        self.assertTrue(product_matches_ingredient("KYCKLINGFILE naturell", "Kycklingfilé"))

    def test_does_not_match_a_sausage_for_a_fillet(self):
        """The exact failure the spec calls out: kycklingfilé must not match
        kycklingkorv just because both contain 'kyckling'."""
        self.assertFalse(product_matches_ingredient("Kycklingkorv 400g", "Kycklingfilé"))

    def test_ris_does_not_match_risotto_or_risifrutti(self):
        self.assertFalse(product_matches_ingredient("Avorio Risottoris 1kg", "Ris"))
        self.assertFalse(product_matches_ingredient("Risifrutti Jordgubb", "Ris"))

    def test_ris_matches_actual_rice(self):
        self.assertTrue(product_matches_ingredient("Jasminris 1kg Garant", "Ris"))

    def test_citron_does_not_match_lemonade_or_pepper(self):
        self.assertFalse(product_matches_ingredient("Citronsaft 500ml", "Citron"))
        self.assertFalse(product_matches_ingredient("Citronpeppar Krydda", "Citron"))

    def test_paprika_does_not_match_the_spice(self):
        self.assertFalse(product_matches_ingredient("Paprikapulver 35g", "Paprika"))

    def test_multiword_ingredient_needs_all_words(self):
        self.assertTrue(product_matches_ingredient("Fryst Torsk i bitar 450g", "Fryst torsk"))
        self.assertFalse(product_matches_ingredient("Torskrygg färsk", "Fryst torsk"))

    def test_universal_exclusions_apply(self):
        self.assertFalse(product_matches_ingredient("Chips med smak av Kycklingfilé", "Kycklingfilé"))

    def test_substring_alone_is_not_a_match(self):
        """Whole-word matching - 'ost' must not match 'ostbågar'."""
        self.assertFalse(product_matches_ingredient("Ostbågar 150g", "Ost"))


class EffectivePriceTest(unittest.TestCase):
    class P:
        # fetched_at som standard: varje riktig prisrad bär en tidsstämpel
        # (upsert_current_price skriver den vid varje import), och en kampanj
        # utan slutdatum dateras mot den - se _campaign_expired.
        def __init__(self, regular=None, campaign=None, member=None, multibuy=None,
                     fetched_at=None):
            self.regular_price, self.campaign_price = regular, campaign
            self.member_price, self.multibuy_price = member, multibuy
            self.fetched_at = time.time() if fetched_at is None else fetched_at

    def test_uses_campaign_when_cheaper(self):
        self.assertEqual(effective_price(self.P(regular=30.0, campaign=25.0)), 25.0)

    def test_uses_regular_when_no_campaign(self):
        self.assertEqual(effective_price(self.P(regular=30.0)), 30.0)

    def test_ignores_member_price(self):
        """A member price isn't available to everyone - counting it as the
        plain price would understate what a normal shopper pays."""
        self.assertEqual(effective_price(self.P(regular=30.0, member=20.0)), 30.0)

    def test_ignores_multibuy_price(self):
        """A multibuy price only applies if you buy the qualifying quantity."""
        self.assertEqual(effective_price(self.P(regular=30.0, multibuy=20.0)), 30.0)

    def test_no_price_at_all_is_none(self):
        self.assertIsNone(effective_price(self.P()))
        self.assertIsNone(effective_price(None))

    def test_a_campaign_nobody_has_confirmed_in_over_eight_days_is_gone(self):
        """C5: bara Primat och partnerfeeden sätter valid_to. Axfood, City
        Gross och ICA gör det aldrig, så en kampanj utan slutdatum försvann
        först vid nästa LYCKADE import - och när importen dör händer det
        aldrig. Nu åldras den i stället."""
        fresh = self.P(regular=30.0, campaign=25.0,
                       fetched_at=time.time() - MAX_CAMPAIGN_AGE_SECONDS + 3600)
        stale = self.P(regular=30.0, campaign=25.0,
                       fetched_at=time.time() - MAX_CAMPAIGN_AGE_SECONDS - 3600)
        self.assertEqual(effective_price(fresh), 25.0)
        self.assertEqual(effective_price(stale), 30.0, "utgången kampanj -> ordinarie")

    def test_a_campaign_that_cannot_be_dated_at_all_is_not_used(self):
        """Fail closed: utan både slutdatum och tidsstämpel går kampanjen
        inte att gå i god för, och fallbacken är det HÖGRE priset."""
        undateable = self.P(regular=30.0, campaign=25.0)
        undateable.fetched_at = None
        self.assertEqual(effective_price(undateable), 30.0)


def raw(chain, external_id, name, *, gtin=None, brand=None, quantity=None, unit=None, size=None):
    return RawProduct(chain=chain, external_product_id=external_id, name=name, store_id="1",
                      store_name="Test", gtin=gtin, brand=brand, quantity=quantity, unit=unit, size=size)


class PricingEngineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = GroceryStore(Path(self._tmp.name) / "grocery.db")
        self.store = self.db.upsert_store(chain="Willys", external_store_id="2132", name="Willys Test")
        self.engine = RecipePricingEngine(self.db)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _add(self, name, price, quantity, unit, *, external_id=None, campaign=None, chain="Willys"):
        product = self.db.find_or_create_product(raw(
            chain, external_id or name, name, quantity=quantity, unit=unit, size=f"{quantity}{unit}"))
        self.db.upsert_current_price(product_id=product.id, store_id=self.store.id,
                                     regular_price=price, campaign_price=campaign)
        return product

    def test_prices_one_ingredient_with_whole_packages(self):
        self._add("Kycklingfilé Naturell", 79.90, 700, "g")
        result = self.engine.price_list(
            [{"name": "Kycklingfilé", "amount": 600, "unit": "g"}], "Willys", self.store.id)
        self.assertEqual(result["realPriceItems"], 1)
        item = result["matchedItems"][0]
        self.assertEqual(item["packages"], 1)
        self.assertEqual(item["totalCost"], 79.90)
        self.assertEqual(result["totalCheckoutCost"], 79.90)

    def test_needing_more_than_one_package_buys_two(self):
        self._add("Kycklingfilé Naturell", 79.90, 700, "g")
        result = self.engine.price_list(
            [{"name": "Kycklingfilé", "amount": 1200, "unit": "g"}], "Willys", self.store.id)
        item = result["matchedItems"][0]
        self.assertEqual(item["packages"], 2)
        self.assertEqual(item["totalCost"], 159.80)

    def test_picks_the_cheapest_total_not_the_cheapest_package(self):
        """One big package can beat several small ones - the comparison has to
        be on total checkout cost."""
        self._add("Ris Jasmin liten", 15.0, 500, "g", external_id="small")
        self._add("Ris Jasmin stor", 25.0, 1, "kg", external_id="big")
        result = self.engine.price_list(
            [{"name": "Ris", "amount": 900, "unit": "g"}], "Willys", self.store.id)
        item = result["matchedItems"][0]
        self.assertEqual(item["totalCost"], 25.0, "2x500g=30 should lose to 1x1kg=25")
        self.assertEqual(item["packages"], 1)

    def test_campaign_price_is_used_when_running(self):
        self._add("Kycklingfilé Naturell", 79.90, 700, "g", campaign=59.90)
        result = self.engine.price_list(
            [{"name": "Kycklingfilé", "amount": 600, "unit": "g"}], "Willys", self.store.id)
        self.assertEqual(result["matchedItems"][0]["totalCost"], 59.90)

    def test_unmatched_ingredient_is_reported_missing_and_lowers_coverage(self):
        """It must never silently vanish from the total - that would make this
        chain look cheaper than it really is."""
        self._add("Kycklingfilé Naturell", 79.90, 700, "g")
        result = self.engine.price_list([
            {"name": "Kycklingfilé", "amount": 600, "unit": "g"},
            {"name": "Saffran", "amount": 1, "unit": "g"},
        ], "Willys", self.store.id)
        self.assertEqual(result["realPriceItems"], 1)
        self.assertEqual(len(result["missingItems"]), 1)
        self.assertEqual(result["missingItems"][0]["name"], "Saffran")
        self.assertEqual(result["coveragePercent"], 50)
        self.assertEqual(result["totalCheckoutCost"], 79.90)

    def test_product_without_a_price_counts_as_missing(self):
        # Prissaneringen (2026-09-01) vägrar numera skriva en prislös rad
        # över huvud taget - "utan pris" är därför exakt detta: produkten
        # finns, prisraden finns inte.
        self.db.find_or_create_product(raw("Willys", "np", "Kycklingfilé Utan Pris", quantity=700, unit="g"))
        result = self.engine.price_list(
            [{"name": "Kycklingfilé", "amount": 600, "unit": "g"}], "Willys", self.store.id)
        self.assertEqual(result["realPriceItems"], 0)
        self.assertEqual(len(result["missingItems"]), 1)
        self.assertEqual(result["totalCheckoutCost"], 0)

    def test_pantry_stock_reduces_what_must_be_bought(self):
        self._add("Ris Jasmin", 25.0, 1, "kg")
        result = self.engine.price_list(
            [{"name": "Ris", "amount": 900, "unit": "g"}], "Willys", self.store.id,
            pantry={"Ris": 900})
        self.assertEqual(result["totalCheckoutCost"], 0)
        self.assertEqual(result["totalItems"], 0, "a fully-stocked item is neither bought nor missing")

    def test_partial_pantry_still_buys_a_package(self):
        self._add("Ris Jasmin", 25.0, 1, "kg")
        result = self.engine.price_list(
            [{"name": "Ris", "amount": 900, "unit": "g"}], "Willys", self.store.id,
            pantry={"Ris": 400})
        self.assertEqual(result["matchedItems"][0]["neededAmount"], 500)
        self.assertEqual(result["totalCheckoutCost"], 25.0)

    def test_wrong_category_product_is_not_used(self):
        """Only kycklingkorv in stock must yield a missing item, not a
        confidently wrong price."""
        self._add("Kycklingkorv", 39.90, 400, "g")
        result = self.engine.price_list(
            [{"name": "Kycklingfilé", "amount": 600, "unit": "g"}], "Willys", self.store.id)
        self.assertEqual(result["realPriceItems"], 0)
        self.assertEqual(len(result["missingItems"]), 1)

    def test_other_chains_products_are_not_used(self):
        self._add("Kycklingfilé Naturell", 79.90, 700, "g", chain="Hemköp")
        result = self.engine.price_list(
            [{"name": "Kycklingfilé", "amount": 600, "unit": "g"}], "Willys", self.store.id)
        self.assertEqual(result["realPriceItems"], 0)

    def test_full_coverage_reports_100_percent(self):
        self._add("Kycklingfilé Naturell", 79.90, 700, "g")
        self._add("Ris Jasmin", 25.0, 1, "kg")
        result = self.engine.price_list([
            {"name": "Kycklingfilé", "amount": 600, "unit": "g"},
            {"name": "Ris", "amount": 900, "unit": "g"},
        ], "Willys", self.store.id)
        self.assertEqual(result["coveragePercent"], 100)
        self.assertEqual(result["totalCheckoutCost"], 104.90)

    def test_empty_list_is_zero_not_a_crash(self):
        result = self.engine.price_list([], "Willys", self.store.id)
        self.assertEqual(result["totalCheckoutCost"], 0)
        self.assertEqual(result["coveragePercent"], 0)

    def test_piece_weights_make_st_against_grams_exact(self):
        """RELEASE GATE 2026-09-02: "2 st citroner" mot ett 100 g-paket räknas
        numera EXAKT via styckvikttabellen (citron 120 g/st -> 240 g -> 3
        paket) - beslutad köksstandard, inte gissning per produkt."""
        self._add("Citron Klass 1", 5.0, 100, "g")
        result = self.engine.price_list(
            [{"name": "Citron", "amount": 2, "unit": "st"}], "Willys", self.store.id)
        item = result["matchedItems"][0]
        self.assertTrue(item["exactPackaging"])
        self.assertEqual(item["packages"], 3)
        self.assertEqual(item["totalCost"], 15.0)

    def test_st_outside_the_piece_table_stays_an_estimate(self):
        """Ingredienser UTAN styckvikt förblir ärliga estimat - utanför
        säkra totaler, aldrig gram-som-paket."""
        self._add("Halloumi 200g", 30.0, 200, "g")
        result = self.engine.price_list(
            [{"name": "Halloumi", "amount": 1, "unit": "st"}], "Willys", self.store.id)
        item = result["matchedItems"][0]
        self.assertFalse(item["exactPackaging"])
        self.assertEqual(item["packages"], 1)
        self.assertIsNone(item.get("totalCost"), "osäker rad får ingen radtotal")


class PortionPriceOmitsNothingTest(unittest.TestCase):
    """C1: portionspriset får aldrig vara lägre än kassan.

    price_list ger en rad med gissat paketantal totalCost=None - den bidrar
    med noll kronor till totalCheckoutCost. Räknas den ändå som "täckt"
    passerar receptet full-match-spärren och kortet visar ett portionspris
    där en hel ingrediens kostnad saknas. Modulens egen docstring kallar det
    "the worst direction to be wrong in".
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)

        self._saved = (grocery_api.DB_PATH, recipes_api.DB_PATH)
        self.addCleanup(self._restore)
        grocery_api.DB_PATH = root / "grocery.db"
        recipes_api.DB_PATH = root / "recipes.db"
        grocery_api.clear_cache()
        recipes_api.clear_cache()

        self.db = GroceryStore(grocery_api.DB_PATH)
        self.addCleanup(self.db.close)
        # Willys ligger i RELEASED_CHAINS - priceable_chains() plockar bara
        # upp släppta kedjor med produkter.
        self.store = self.db.upsert_store(chain="Willys", external_store_id="2132",
                                          name="Willys Test")
        self._add("Kycklingfilé Naturell", 79.90, 700, "g")
        self._add("Halloumi Grill", 30.0, 200, "g")

        self.recipes = RecipeStore(recipes_api.DB_PATH)
        self.addCleanup(self.recipes.close)

    def _restore(self):
        grocery_api.DB_PATH, recipes_api.DB_PATH = self._saved
        grocery_api.clear_cache()
        recipes_api.clear_cache()

    def _add(self, name, price, quantity, unit):
        product = self.db.find_or_create_product(raw(
            "Willys", name, name, quantity=quantity, unit=unit, size=f"{quantity}{unit}"))
        self.db.upsert_current_price(product_id=product.id, store_id=self.store.id,
                                     regular_price=price)
        return product

    def _recipe(self, recipe_id, ingredients):
        self.recipes.upsert_recipe({
            "id": recipe_id, "name": recipe_id, "servings": 4, "totalTime": 30,
            "ingredients": ingredients, "instructions": ["Laga."],
            "categories": [], "tags": [], "allergens": [], "dietFlags": [],
        })

    def test_a_recipe_with_one_uncertain_row_gets_no_portion_price(self):
        """Halloumi "1 st" saknar styckvikt: paketantalet är en gissning, och
        radens kostnad räknas inte in. Då finns inget ärligt portionspris."""
        self._recipe("osaker", [
            {"name": "Kycklingfilé", "amount": 600, "unit": "g"},
            {"name": "Halloumi", "amount": 1, "unit": "st"},
        ])

        recipe_prices.reprice_all()

        priced = self.recipes.get("osaker")
        self.assertIsNone(
            priced["pricePerPortion"],
            "ett recept med en osäker rad får inget portionspris - inte ett "
            "för lågt tal där halloumin kostar noll")

    def test_a_recipe_where_every_row_is_exact_still_gets_a_price(self):
        """Motpolen: spärren får inte nolla allt. Alla rader säkra -> pris."""
        self._recipe("saker", [{"name": "Kycklingfilé", "amount": 600, "unit": "g"}])

        recipe_prices.reprice_all()

        priced = self.recipes.get("saker")
        self.assertEqual(priced["pricePerPortion"], round(79.90 / 4, 2))
        self.assertEqual(priced["priceChain"], "Willys")


if __name__ == "__main__":
    unittest.main()
