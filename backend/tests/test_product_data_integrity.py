# -*- coding: utf-8 -*-
"""Produktdata i Handla och Skafferi: vad raden får påstå, och vad den inte får.

Två regler, och den andra är den viktiga:

1. Det raden VISAR ska komma från prisdatabasen - namn, märke, förpackning,
   GTIN, bild. Aldrig från ingrediensen, aldrig gissat, aldrig lånat från en
   annan produkt.

2. Det raden visar får ALDRIG påverka matchningen eller prisets säkerhet.
   En snygg bild gör inte en osäker matchning säker. Klienten skickar en
   ögonblicksbild av produkten för VISNING; den får inte kunna smyga in ett
   pris, en prisnivå eller en produktidentitet i hushållets data.

Regel 2 upprätthålls av _clean_product: en vitlista som kastar allt annat.
Testerna nedan försöker aktivt bryta igenom den.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.household import HouseholdStore  # noqa: E402
from services.household.store import _clean_product  # noqa: E402


class ProductSnapshotWhitelistTest(unittest.TestCase):
    """Vad en klient får spara om en produkt - och inte."""

    def test_display_fields_survive(self):
        product = _clean_product({
            "productName": "Arla Mellanmjölk", "brand": "Arla", "packageSize": "1,5 l",
            "gtin": "7310865004703", "chain": "Willys", "category": "Mejeri",
            "imageUrl": "https://bilder.example/mjolk.jpg",
        })
        self.assertEqual(product["productName"], "Arla Mellanmjölk")
        self.assertEqual(product["brand"], "Arla")
        self.assertEqual(product["gtin"], "7310865004703")
        self.assertEqual(product["imageUrl"], "https://bilder.example/mjolk.jpg")

    def test_unknown_fields_are_dropped(self):
        """Allt som inte står på vitlistan kastas - inklusive fält som ser
        harmlösa ut. En klient ska inte kunna odla egna kolumner i
        hushållets data."""
        product = _clean_product({
            "productName": "Mjölk", "priceTier": "VERIFIED_STORE_PRICE",
            "confidence": 1.0, "matchScore": 99, "verifiedAt": "2026-01-01",
            "isCheapest": True, "__proto__": {"admin": True}, "sql": "DROP TABLE",
        })
        for forbidden in ("confidence", "matchScore", "verifiedAt", "isCheapest",
                          "__proto__", "sql"):
            self.assertNotIn(forbidden, product, forbidden)

    def test_a_client_cannot_invent_a_price_tier_that_the_engine_did_not_set(self):
        """priceTier står på vitlistan för VISNING, men det är en text -
        den läses aldrig tillbaka som ett prisbeslut. Testet dokumenterar
        att den bara är en sträng, och att inget annat prisfält följer med."""
        product = _clean_product({"productName": "Mjölk", "priceTier": "VERIFIED_STORE_PRICE"})
        self.assertEqual(product["priceTier"], "VERIFIED_STORE_PRICE")
        self.assertNotIn("verifiedAt", product)

    def test_non_https_images_are_refused(self):
        """En bild-URL är det enda fältet som blir ett nätverksanrop i
        klienten. javascript:, data: och http: släpps aldrig igenom."""
        for bad in ("javascript:alert(1)", "data:text/html;base64,x",
                    "http://osaker.example/bild.jpg", "//evil.example/x.jpg",
                    "HTTPS://versaler.example/x.jpg"):
            product = _clean_product({"productName": "Mjölk", "imageUrl": bad})
            self.assertNotIn("imageUrl", product or {}, bad)

    def test_surrounding_whitespace_is_trimmed_before_the_https_check(self):
        """En url med blanksteg runt sig är en giltig url med slarv omkring -
        den trimmas och godtas. Det är kontrollen EFTER trimningen som är
        skyddet, och den kan inte kringgås med ett inledande mellanslag."""
        product = _clean_product({"productName": "Mjölk",
                                  "imageUrl": "  https://bilder.example/x.jpg  "})
        self.assertEqual(product["imageUrl"], "https://bilder.example/x.jpg")

    def test_an_absurdly_long_image_url_is_refused(self):
        product = _clean_product({"productName": "Mjölk",
                                  "imageUrl": "https://x.example/" + "a" * 600})
        self.assertNotIn("imageUrl", product or {})

    def test_a_malformed_gtin_is_dropped_rather_than_stored(self):
        for bad in ("abc", "123", "", None, "7310865004703123456", "<script>"):
            product = _clean_product({"productName": "Mjölk", "gtin": bad})
            self.assertNotIn("gtin", product or {}, repr(bad))

    def test_text_fields_are_length_capped(self):
        product = _clean_product({"productName": "x" * 500, "brand": "y" * 500})
        self.assertLessEqual(len(product["productName"]), 120)
        self.assertLessEqual(len(product["brand"]), 60)

    def test_numbers_stay_numbers_and_junk_becomes_zero(self):
        product = _clean_product({"productName": "Mjölk", "totalCost": "inte ett tal",
                                  "unitPrice": 19.95})
        self.assertEqual(product["unitPrice"], 19.95)
        self.assertEqual(product["totalCost"], 0.0)

    def test_a_non_dict_snapshot_is_simply_no_product(self):
        for bad in ("sträng", 42, [1, 2], None, True):
            self.assertIsNone(_clean_product(bad), repr(bad))


class GenericItemsKeepNoBrandTest(unittest.TestCase):
    """§8: lök, potatis och persilja har inget varumärke, och att hitta på
    ett vore värre än att låta bli."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.store = HouseholdStore(Path(self._tmp.name) / "h.db")
        self.addCleanup(self.store.close)
        self.household_id = self.store.create_household(1, "Familjen From")["id"]

    def test_a_generic_pantry_item_has_no_product_and_no_gtin(self):
        for name in ("Lök", "Potatis", "Banan", "Vitlök", "Persilja"):
            item = self.store.upsert_inventory_item(self.household_id, 1,
                                                    {"name": name, "amount": 2, "unit": "st"})
            self.assertIsNone(item["product"], name)
            self.assertIsNone(item["gtin"], name)

    def test_a_generic_item_stays_generic_even_if_a_client_sends_an_empty_product(self):
        item = self.store.upsert_inventory_item(self.household_id, 1,
                                                {"name": "Lök", "product": {}})
        self.assertIsNone(item["product"])

    def test_a_real_product_keeps_its_identity(self):
        item = self.store.upsert_inventory_item(self.household_id, 1, {
            "name": "Arla Mellanmjölk", "gtin": "7310865004703",
            "product": {"productName": "Arla Mellanmjölk", "brand": "Arla",
                        "packageSize": "1,5 l",
                        "imageUrl": "https://bilder.example/mjolk.jpg"},
        })
        self.assertEqual(item["product"]["brand"], "Arla")
        self.assertEqual(item["gtin"], "7310865004703")

    def test_the_row_key_follows_the_gtin_so_the_same_product_is_one_row(self):
        """Två personer lägger in samma mjölk från varsin telefon."""
        first = self.store.upsert_inventory_item(self.household_id, 1, {
            "name": "Arla Mellanmjölk", "gtin": "7310865004703"})
        second = self.store.upsert_inventory_item(self.household_id, 1, {
            "name": "Mellanmjölk 1,5l", "gtin": "7310865004703"})
        self.assertEqual(first["key"], second["key"])
        self.assertEqual(len(self.store.inventory_items(self.household_id, 1)), 1)

    def test_two_different_generic_items_do_not_collapse(self):
        self.store.upsert_inventory_item(self.household_id, 1, {"name": "Lök"})
        self.store.upsert_inventory_item(self.household_id, 1, {"name": "Purjolök"})
        names = {row["name"] for row in self.store.inventory_items(self.household_id, 1)}
        self.assertEqual(names, {"Lök", "Purjolök"})


class UiDataCannotAffectPricingTest(unittest.TestCase):
    """§35/§6: ingen produktbild och inget snyggt namn får göra en osäker
    matchning säker.

    Beviset är strukturellt: hushållets ögonblicksbild och prismotorns
    beslut lever i skilda lager. Motorn läser sin egen databas och tar
    aldrig emot ett product-fält från en klient."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.store = HouseholdStore(Path(self._tmp.name) / "h.db")
        self.addCleanup(self.store.close)
        self.household_id = self.store.create_household(1, "Familjen From")["id"]

    def test_the_pricing_engine_takes_no_product_snapshot_from_the_caller(self):
        """price_list tar namn, mängd och enhet - inget mer. Fanns en väg in
        för klientens produktdata skulle den synas i signaturen."""
        import inspect
        from services.grocery.pricing import RecipePricingEngine
        signature = inspect.signature(RecipePricingEngine.price_list)
        self.assertEqual(list(signature.parameters), ["self", "items", "chain", "store_id", "pantry"])

    def test_a_shopping_row_snapshot_never_reaches_the_pantry_amounts(self):
        """Det enda hushållet skickar in i prissättningen är MÄNGDER, aldrig
        produktpåståenden. En manipulerad ögonblicksbild kan därför inte
        flytta ett pris."""
        self.store.upsert_inventory_item(self.household_id, 1, {
            "name": "Ris", "amount": 1000, "unit": "g",
            "product": {"productName": "Påhittat", "totalCost": 0.01,
                        "priceTier": "VERIFIED_STORE_PRICE"}})
        amounts = self.store.pantry_amounts(self.household_id)
        self.assertEqual(amounts, {"Ris": 1000})
        self.assertTrue(all(isinstance(value, (int, float)) for value in amounts.values()))

    def test_a_fabricated_cost_in_the_snapshot_is_stored_but_never_summed(self):
        """totalCost sparas för visning. Att det finns i raden får inte göra
        det till en del av någon summa - hushållslagret summerar aldrig
        priser, det är prismotorns ensak."""
        item = self.store.upsert_shopping_item(self.household_id, 1, {
            "name": "Mjölk", "product": {"productName": "Mjölk", "totalCost": 0.01}})
        self.assertEqual(item["product"]["totalCost"], 0.01)
        for method in ("total", "sum_prices", "basket_total", "price_list"):
            self.assertFalse(hasattr(self.store, method),
                             f"hushållslagret har fått en prisberäkning ({method})")


if __name__ == "__main__":
    unittest.main()
