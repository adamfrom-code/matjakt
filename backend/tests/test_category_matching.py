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
    category_allows_ingredient, departments_for_category, product_matches_ingredient,
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
        self.assertTrue(product_matches_ingredient(
            "Kycklingfilé Strimlad Sverige", "kycklingfilé", "Kronfågel",
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


if __name__ == "__main__":
    unittest.main()
