# -*- coding: utf-8 -*-
"""Tests for category (department) data: collecting it, and using it to
reject a wrong product.

Every category string here is a REAL path taken from the live category trees
walked on 2026-08-31 (Willys 452 leaf categories, Hemköp 428) or from City
Gross' superCategory/category/bfCategory triplet. Nothing here touches the
network.

The failure cases are not hypothetical - each one is a confidently wrong
match that name-only matching produced against real Willys data, recorded in
grocery/pricing.py's history: "Ris" -> dog food, "Smör" -> popcorn, "Ägg" ->
chocolate eggs.
"""

import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery.pricing import (  # noqa: E402
    aliases_for, category_allows_ingredient, departments_for_category,
    product_matches_ingredient,
)
from services.grocery.providers.axfood import flatten_category_tree  # noqa: E402
from services.grocery.providers.willys import WillysProvider  # noqa: E402

# --- Real fragment of /leftMenu/categorytree (Willys, 2026-08-31) ---------
REAL_TREE = {
    "id": "N00", "category": "N00", "title": "Alla varor", "url": "/alla-varor/c/",
    "valid": True, "children": [
        {"id": "N01", "category": "N01", "title": "Kött, chark & fågel",
         "url": "kott-chark-och-fagel", "valid": True, "children": [
             {"id": "N0101", "category": "N0101", "title": "Fågel",
              "url": "kott-chark-och-fagel/fagel", "valid": True, "children": [
                  {"id": "N010101", "category": "N010101", "title": "Färsk fågel",
                   "url": "kott-chark-och-fagel/fagel/farsk-fagel", "valid": True, "children": []},
                  {"id": "N010102", "category": "N010102", "title": "Fryst fågel",
                   "url": "kott-chark-och-fagel/fagel/fryst-fagel", "valid": True, "children": []},
              ]},
         ]},
        {"id": "N99", "category": "N99", "title": "Utgången kategori",
         "url": "utgangen", "valid": False, "children": []},
    ],
}

# --- Real /c/{slug} response fragment (same shape as /search) -------------
REAL_CATEGORY_LISTING = {
    "categoryInfo": {"code": "N010101", "name": "Färsk fågel",
                     "url": "kott-chark-och-fagel/fagel/farsk-fagel",
                     "parentCategoryName": "Fågel"},
    "pagination": {"pageSize": 30, "currentPage": 0, "numberOfPages": 1,
                   "totalNumberOfResults": 1},
    "results": [{
        "code": "101258401_ST", "name": "Kycklingfilé Strimlad Sverige",
        "manufacturer": "Kronfågel", "displayVolume": "700g",
        "priceValue": 46.7, "comparePrice": "66,71 kr", "potentialPromotions": [],
        "image": {"url": "https://assets.axfood.se/image/upload/f_auto,t_200/07340083452093_C1L1_s01"},
        # Verified live: the product itself carries NO category - it is empty
        # on every product of both chains, which is why the category has to
        # come from the request.
        "googleAnalyticsCategory": "",
    }],
}


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class CategoryTreeTest(unittest.TestCase):
    def test_returns_only_leaves(self):
        """A parent's listing is the union of its children's, so walking both
        levels would fetch every product twice."""
        leaves = flatten_category_tree(REAL_TREE)
        self.assertEqual([leaf["code"] for leaf in leaves], ["N010101", "N010102"])

    def test_path_is_broadest_first_and_excludes_the_root(self):
        """"Alla varor" is a container, not an aisle - it must not prefix
        every path."""
        leaves = flatten_category_tree(REAL_TREE)
        self.assertEqual(leaves[0]["path"], "Kött, chark & fågel > Fågel > Färsk fågel")

    def test_slug_is_the_full_request_path(self):
        leaves = flatten_category_tree(REAL_TREE)
        self.assertEqual(leaves[0]["slug"], "kott-chark-och-fagel/fagel/farsk-fagel")

    def test_invalid_categories_are_skipped_not_requested(self):
        codes = [leaf["code"] for leaf in flatten_category_tree(REAL_TREE)]
        self.assertNotIn("N99", codes)

    def test_empty_tree_is_not_an_error(self):
        self.assertEqual(flatten_category_tree({}), [])
        self.assertEqual(flatten_category_tree(None), [])


class CategoryBrowsingTest(unittest.TestCase):
    """The category must reach the product, or none of the matching below
    can work."""

    def setUp(self):
        self.provider = WillysProvider()
        self.requested = []

        def fake_request(url):
            self.requested.append(url)
            return json.loads(json.dumps(REAL_CATEGORY_LISTING))

        self.provider._request = fake_request

    def test_product_gets_the_category_it_was_collected_from(self):
        categories = flatten_category_tree(REAL_TREE)[:1]
        products = self.provider.get_products_by_category("2132", categories)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].category, "Kött, chark & fågel > Fågel > Färsk fågel")

    def test_uses_the_verified_c_endpoint(self):
        self.provider.get_products_by_category("2132", flatten_category_tree(REAL_TREE)[:1])
        self.assertIn("/axfood/rest/v1/c/kott-chark-och-fagel/fagel/farsk-fagel", self.requested[0])

    def test_all_other_fields_still_parse_from_the_same_shape(self):
        """The /c/ payload is the same shape as /search, so the existing field
        mapping must apply unchanged - if it didn't, category browsing would
        silently import products without prices or GTINs."""
        product = self.provider.get_products_by_category("2132", flatten_category_tree(REAL_TREE)[:1])[0]
        self.assertEqual(product.name, "Kycklingfilé Strimlad Sverige")
        self.assertEqual(product.regular_price, 46.7)
        self.assertEqual(product.gtin, "07340083452093")
        self.assertEqual(product.quantity, 700.0)

    def test_term_search_still_leaves_category_none(self):
        """Term search genuinely does not know the category, and must say so
        rather than guessing one from the product name."""
        raw = self.provider.normalize_product({**REAL_CATEGORY_LISTING["results"][0], "_store_id": "2132"})
        self.assertIsNone(raw.category)


class DepartmentTest(unittest.TestCase):
    def test_recognises_real_paths_from_every_chain(self):
        self.assertEqual(departments_for_category("Mejeri, ost & ägg > Mjölk > Lättmjölk"), {"dairy"})
        self.assertEqual(departments_for_category("Kött, chark & fågel > Fågel > Färsk fågel"), {"meat"})
        self.assertEqual(departments_for_category("Skafferi > Pasta, ris & mat > Ris"), {"pantry"})
        self.assertIn("fish", departments_for_category("Fisk & Skaldjur > Fisk > Lax"))

    def test_no_category_is_undecidable_not_a_rejection(self):
        """ICA exposes no usable tree and older rows were term-collected.
        Those must still be priceable on their names alone."""
        self.assertEqual(departments_for_category(None), set())
        self.assertTrue(category_allows_ingredient(None, "ris"))
        self.assertTrue(category_allows_ingredient("", "smör"))

    def test_an_ingredient_without_a_department_list_is_unconstrained(self):
        self.assertTrue(category_allows_ingredient("Skafferi > Bakning > Jäst", "jäst"))

    def test_but_the_never_departments_still_apply_to_it(self):
        self.assertFalse(category_allows_ingredient("Djur > Hund > Torrfoder", "jäst"))


class WrongAisleIsRejectedTest(unittest.TestCase):
    """Each of these is a real confidently-wrong match from live Willys data.
    Every one contains the ingredient as a genuine leading word, so name
    matching alone cannot reject it - the category is what settles it."""

    def test_rice_does_not_match_dog_food(self):
        self.assertFalse(product_matches_ingredient(
            "Ris & Kyckling Active", "ris", "Mini Small",
            category="Djur > Hund > Torrfoder"))

    def test_butter_does_not_match_popcorn(self):
        self.assertFalse(product_matches_ingredient(
            "Smör Popcorn 3-pack", "smör", "Micropop",
            category="Glass, godis & snacks > Chips, snacks & dip > Popcorn"))

    def test_egg_does_not_match_chocolate_eggs(self):
        self.assertFalse(product_matches_ingredient(
            "Ägg Choklad", "ägg", None,
            category="Glass, godis & snacks > Choklad > Chokladägg"))

    def test_cheese_does_not_match_crispbread(self):
        self.assertFalse(product_matches_ingredient(
            "Ost Frasrost", "ost", None,
            category="Bröd & Kakor > Knäckebröd & Skorpor"))

    def test_chicken_fillet_does_not_match_a_ready_meal(self):
        self.assertFalse(product_matches_ingredient(
            "Kycklingfilé Curry", "kycklingfilé", None,
            category="Färdigmat > Portionsrätter & snabblagat"))

    def test_the_real_products_still_match(self):
        """Precision must not come from rejecting everything."""
        self.assertTrue(product_matches_ingredient(
            "Ris Jasmin", "ris", None, category="Skafferi > Pasta, ris & mat > Ris"))
        self.assertTrue(product_matches_ingredient(
            "Smör Normalsaltat 82%", "smör", "Svenskt Smör",
            category="Mejeri, ost & ägg > Smör, margarin & jäst > Smör"))
        # Strimlad filé är en annan FORM än hel filé - kanoniska kravet
        # (2026-09-01) är att en butik får byta märke och förpackning men
        # aldrig styckningsform: strimlor mot hel filé är inte samma vara i
        # en prisjämförelse.
        self.assertFalse(product_matches_ingredient(
            "Kycklingfilé Strimlad Sverige", "kycklingfilé", "Kronfågel",
            category="Kött, chark & fågel > Fågel > Färsk fågel"))
        self.assertTrue(product_matches_ingredient(
            "Kycklingfilé Färsk Sverige", "kycklingfilé", "Kronfågel",
            category="Kött, chark & fågel > Fågel > Färsk fågel"))
        self.assertTrue(product_matches_ingredient(
            "Ägg Frigående Inomhus M", "ägg", None,
            category="Mejeri, ost & ägg > Ägg"))

    def test_frozen_forms_are_allowed_where_they_are_real_products(self):
        self.assertTrue(product_matches_ingredient(
            "Laxfilé Naturell Fryst", "laxfilé", None,
            category="Fryst > Fisk & skaldjur"))

    def test_name_rules_still_apply_on_top_of_the_category(self):
        """Category is a filter, not a replacement: a sausage in the meat
        aisle is still not a chicken fillet."""
        self.assertFalse(product_matches_ingredient(
            "Kycklingkorv Grillad", "kycklingfilé", None,
            category="Kött, chark & fågel > Korv"))


class SubstringBoundaryTest(unittest.TestCase):
    """Both bugs below are the same shape, and both were found by MEASURING
    against 10 842 real Willys products rather than by reading the code: a
    Swedish word sitting inside a longer Swedish word, matched as a raw
    substring. The codebase had already been bitten by this class of bug once
    (accent folding), which is why each fix here is pinned by a test."""

    def test_skaldjur_is_not_pet_food(self):
        """"djur" as a plain substring also matches "skaldjur", which filed
        every shellfish aisle under pet food and took "Räkor" from 13 real
        candidates to zero."""
        self.assertEqual(departments_for_category("Fryst > Fisk & skaldjur > Räkor"),
                         {"fish", "frozen"})
        self.assertTrue(product_matches_ingredient(
            "Räkor Skalade Frysta", "räkor", None,
            category="Fryst > Fisk & skaldjur > Räkor"))

    def test_actual_pet_food_is_still_rejected(self):
        self.assertEqual(departments_for_category("Djur > Hund > Torrfoder"), {"pet"})

    def test_risdryck_is_not_a_beverage_aisle_word(self):
        self.assertNotIn("drinks", departments_for_category(
            "Mejeri, ost & ägg > Havre-, Soja-, Risdryck mm"))

    def test_flaskfile_is_not_a_soft_drink(self):
        """"läsk" folds to "lask", which sits inside "flaskfile" - so every
        pork product in the catalogue was universally excluded as a soft
        drink, and "Fläskfilé" matched nothing at all."""
        self.assertTrue(product_matches_ingredient(
            "Fläskfilé Fryst Danmark", "fläskfilé", None,
            category="Kött, chark & fågel > Kött > Fläsk"))
        self.assertTrue(product_matches_ingredient(
            "Fläskkarré Benfri", "fläskkarré", None,
            category="Kött, chark & fågel > Kött > Fläsk"))

    def test_an_actual_soft_drink_is_still_excluded(self):
        self.assertFalse(product_matches_ingredient(
            "Citron Läsk", "citron", None, category="Dryck > Läsk"))

    def test_exclusions_still_catch_the_compound_head(self):
        """A sausage is still not a fillet, and a sauce is still not cream -
        the boundary rule must not have loosened the real exclusions."""
        self.assertFalse(product_matches_ingredient(
            "Kycklingkorv Grillad", "kycklingfilé", None,
            category="Kött, chark & fågel > Korv"))
        self.assertFalse(product_matches_ingredient(
            "Vaniljsås Grädde & Mjölk", "grädde", None,
            category="Mejeri, ost & ägg > Matlagning > Grädde"))

    def test_exclusions_still_catch_the_compound_prefix(self):
        """"messmör" is whey spread, not butter - caught by its first element
        rather than its head, which is why prefixes must count too."""
        self.assertFalse(product_matches_ingredient(
            "Messmör Original", "smör", None,
            category="Mejeri, ost & ägg > Smör, margarin & jäst > Smör"))


if __name__ == "__main__":
    unittest.main()


class WholeCutTest(unittest.TestCase):
    """A whole piece of meat is not a patty, a sausage or a cold cut.

    Found by pricing the real recipe bank against real Willys data: 7 of 22
    matches for "Biff" were wrong, in exactly two classes - formed mince
    ("Pannbiff" ends with "biff", so compound-head matching accepts it) and
    sliced cold cuts ("Rostbiff Deliskivor" is something you put on bread).
    Both produce a confidently wrong price for a different product.
    """

    def test_a_steak_is_not_a_mince_patty(self):
        self.assertFalse(product_matches_ingredient(
            "Pannbiff Fryst/1 Port", "Biff", None,
            category="Kött, chark & fågel > Kött > Färdiglagat & pannfärdigt"))

    def test_a_steak_is_not_sliced_cold_cuts(self):
        self.assertFalse(product_matches_ingredient(
            "Rostbiff Deliskivor", "Biff", None,
            category="Kött, chark & fågel > Pålägg > Skivat pålägg"))

    def test_a_fillet_is_not_a_breaded_schnitzel(self):
        self.assertFalse(product_matches_ingredient(
            "Fläskschnitzel Panerad", "Fläskfilé", None,
            category="Kött, chark & fågel > Kött > Fläsk"))

    def test_real_steaks_still_match(self):
        """Precision must not come from rejecting everything."""
        for name in ["Ryggbiff Bit Sverige", "Lövbiff Skivad Sverige",
                     "Pepparbiff av Nöt Sverige"]:
            self.assertTrue(product_matches_ingredient(
                name, "Biff", None, category="Kött, chark & fågel > Kött > Nöt & kalv"), name)

    def test_a_steak_requirement_is_canonical_across_stores(self):
        """Fanns i verklig data: "Biff" prissattes som Biff med Kappa hos en
        kedja, Rostbiff hos en annan och Grillbiff av SKINKA hos en tredje.
        Tre butiker, tre råvaror - ingen jämförelse. En butik får välja
        märke och förpackning, aldrig en annan styckdetalj eller ett annat
        djur."""
        for name in ["Biff med Kappa Brasilien", "Rostbiff Nöt i Bit Sverige",
                     "Grillbiff av Skinka", "Biff Strimlad Sverige"]:
            self.assertFalse(product_matches_ingredient(
                name, "Biff", None, category="Kött, chark & fågel > Kött > Nöt & kalv"), name)

    def test_minced_meat_may_still_match_minced_products(self):
        """The rule is about WHOLE cuts. A recipe asking for köttfärs
        obviously may be priced against minced meat."""
        self.assertTrue(product_matches_ingredient(
            "Blandfärs 20% Sverige", "Blandfärs", None,
            category="Kött, chark & fågel > Kött > Köttfärs"))

    def test_ham_may_still_be_a_cold_cut(self):
        """Skinka genuinely IS a cold cut - the cold-cuts rejection applies
        only to whole raw cuts."""
        self.assertTrue(product_matches_ingredient(
            "Skinka Kokt Skivad", "Skinka", None,
            category="Kött, chark & fågel > Pålägg > Skivat pålägg"))


class IngredientAliasTest(unittest.TestCase):
    """What a recipe calls something and what the shelf calls it are often
    two different Swedish words. A recipe says "Köttfärs"; the shelf says
    "Blandfärs". No amount of string matching bridges that - it is
    vocabulary, so it lives in data.
    """

    def test_aliases_exist_for_the_measured_misses(self):
        for ingredient in ["Köttfärs", "Soja", "Fryst torsk", "Kycklinglårfilé",
                           "Wokgrönsaker"]:
            self.assertTrue(aliases_for(ingredient), ingredient)

    def test_an_alias_still_goes_through_every_rule(self):
        """An alias may only find products the matcher would have accepted
        anyway - it widens coverage without loosening precision."""
        self.assertFalse(product_matches_ingredient(
            "Blandfärs Hundfoder", "Blandfärs", None, category="Djur > Hund > Torrfoder"))

    def test_unknown_ingredients_have_no_aliases(self):
        self.assertEqual(aliases_for("Struts"), [])


class AliasesCompeteWithLiteralMatches(unittest.TestCase):
    """Aliases are not a fallback - they compete. "Pasta" literally matched
    exactly one product at Willys (organic chickpea pasta at 118 kr/kg), so
    the "cheapest pasta" was a specialty product while every ordinary
    spaghetti sat unconsidered under its own name."""

    class _Product:
        def __init__(self, id, name, category="Skafferi > Pasta, ris & matgryn > Pasta"):
            self.id, self.name, self.brand, self.category = id, name, None, category
            self.quantity, self.unit = 500.0, "g"

    def test_alias_products_join_the_literal_matches(self):
        from services.grocery.pricing import RecipePricingEngine
        engine = RecipePricingEngine.__new__(RecipePricingEngine)
        chickpea = self._Product(1, "Kikärtspasta Ekologisk")
        wholegrain = self._Product(3, "Fullkornspasta")
        penne = self._Product(2, "Penne Rigate")
        index = {"pasta": [chickpea, wholegrain], "penne": [penne],
                 "spaghetti": [], "makaroner": [], "fusilli": [],
                 "tagliatelle": [], "farfalle": []}
        engine._index_for = lambda chain: index
        names = [p.name for p in engine._candidates("Pasta", "Willys")]
        self.assertIn("Penne Rigate", names, "aliasformen måste konkurrera")
        self.assertIn("Fullkornspasta", names)
        # Kanoniskt krav: baljväxtpasta är en substitution, aldrig ett svar
        # på generisk pasta - vill receptet ha kikärtspasta säger det det.
        self.assertNotIn("Kikärtspasta Ekologisk", names)


class CanonicalCrossStoreRequirements(unittest.TestCase):
    """§Kanoniska krav (2026-09-01): butiksjämförelsen bygger på ETT
    oföränderligt behov per ingrediens. En butik får välja märke och
    förpackning - aldrig råvara, styckdetalj, form eller smaksättning.
    Varje FALSE här är en substitution som observerats eller efterfrågats
    förbjuden; varje TRUE är den äkta varan som måste fortsätta matcha."""

    MEAT = "Kött, chark & fågel > Kött > Nöt & kalv"
    DAIRY = "Mejeri, ost & ägg > Mjölk, fil & grädde"
    PANTRY = "Skafferi > Pasta, ris & matgryn > Pasta"

    def test_forbidden_substitutions(self):
        cases = [
            ("Lövbiff", "Biffkappa Bit", self.MEAT),
            ("Lövbiff", "Pannbiff Färdigstekt", "Färdigmat > Kylda rätter"),
            ("Biff", "Grillbiff av Skinka", self.MEAT),
            ("Biff", "Rostbiff Nöt i Bit", self.MEAT),
            ("Biff", "Nöt Strimlad Sverige", self.MEAT),
            ("Vispgrädde", "Matgrädde Laktosfri 13%", self.DAIRY),
            ("Matlagningsgrädde", "Vispgrädde 40%", self.DAIRY),
            ("Laxfilé", "Fiskpinnar Frysta", "Fryst > Fisk & skaldjur"),
            ("Yoghurt", "Vaniljyoghurt Laktosfri", self.DAIRY),
            ("Grekisk yoghurt", "Grekisk Yoghurt Müsli 7%", self.DAIRY),
            ("Fetaost", "Feta Tomat Lätt Crème Fraiche 12%", self.DAIRY),
            ("Pasta", "Kikärtspasta Ekologisk", self.PANTRY),
            ("Spaghetti", "Spaghetti Majspasta Glutenfri", self.PANTRY),
            ("Crème fraiche", "Crème Fraiche Lätt 13%", self.DAIRY),
            ("Kycklinglårfilé", "Kycklingklubba Sverige", "Kött, chark & fågel > Fågel"),
            ("Apelsin", "Apelsin Mandarin Kolsyrat Vatten", "Dryck > Vatten"),
        ]
        for ingredient, product, category in cases:
            self.assertFalse(
                product_matches_ingredient(product, ingredient, None, category),
                f"{product!r} får aldrig prissätta {ingredient!r}")

    def test_the_genuine_article_still_matches_everywhere(self):
        cases = [
            ("Lövbiff", "Lövbiff Skivad Sverige", self.MEAT),
            ("Biff", "Ryggbiff Skivad", self.MEAT),
            ("Nötfärs", "Nötfärs 12% Sverige", self.MEAT),
            ("Blandfärs", "Blandfärs 20% Irland Danmark", self.MEAT),
            ("Kycklingfilé", "Kycklingfilé Färsk Sverige", "Kött, chark & fågel > Fågel"),
            # Tvåordsformen "Kyckling Lårfilé" nås via aliaslagret i motorn;
            # matcharens direkta kontrakt testas med sammansättningen.
            ("Kycklinglårfilé", "Kycklinglårfilé Sverige", "Fryst > Kött & fågel"),
            ("Laxfilé", "Laxfilé Fryst", "Fryst > Fisk"),
            ("Torskfilé", "Torskfilé", "Fisk & skaldjur"),
            ("Vispgrädde", "Vispgrädde Färsk 40%", self.DAIRY),
            # "Matgrädde" nås via aliaslagret; direktmatcharen testas med
            # produktens fulla namnform.
            ("Matlagningsgrädde", "Matlagningsgrädde 15%", self.DAIRY),
            ("Yoghurt", "Yoghurt Naturell 3%", self.DAIRY),
            ("Grekisk yoghurt", "Grekisk Matyoghurt 10%", self.DAIRY),
            ("Fetaost", "Fetaost Block 23%", "Mejeri, ost & ägg > Ost"),
            ("Pasta", "Pasta Penne Rigate", self.PANTRY),
            ("Ris", "Ris Långkornigt", "Skafferi > Pasta, ris & matgryn > Ris"),
            ("Riven ost", "Gratängost Riven 27%", "Mejeri, ost & ägg > Ost"),
        ]
        for ingredient, product, category in cases:
            self.assertTrue(
                product_matches_ingredient(product, ingredient, None, category),
                f"{product!r} är den äkta varan för {ingredient!r} och måste matcha")

    def test_the_requirement_object_is_identical_for_every_chain(self):
        """Invarianten: kedjorna får exakt samma krav. price_list muterar
        aldrig items - en butik som "behövde" ändra kravet för att hitta en
        match har ingen match."""
        import copy
        from services.grocery.pricing import RecipePricingEngine
        engine = RecipePricingEngine.__new__(RecipePricingEngine)
        engine._index_for = lambda chain: {}
        engine._prices_for = lambda store_id: {}
        items = [{"name": "Lövbiff", "amount": 600, "unit": "g"},
                 {"name": "Vispgrädde", "amount": 3, "unit": "dl"}]
        snapshot = copy.deepcopy(items)
        for chain in ("Willys", "Hemköp", "City Gross"):
            engine.price_list(items, chain, store_id=1)
            self.assertEqual(items, snapshot,
                             f"{chain} förändrade det kanoniska kravet")
