# -*- coding: utf-8 -*-
"""Köp hela listan: att arkitekturen är ärlig innan den är byggd (§22).

Det som testas är inte att överföringen fungerar - ingen kedja har en
avtalad väg in än. Det som testas är att modulen INTE kan lova något den
inte håller: ingen kedja rapporteras klara mer än den gör, och en
överföring som inte tog med alla varor måste säga vilka som blev kvar.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery.cart import (  # noqa: E402
    BULK_LIST_IMPORT, CAPABILITIES, FULL_CART_API, PRODUCT_DEEPLINK,
    STORE_HOMEPAGE_FALLBACK, BasketLine, CheckoutBasket, HandoffResult,
    basket_from_items, capability_for, provider_for,
)


class CapabilityTest(unittest.TestCase):
    def test_no_chain_claims_more_than_a_homepage_link_today(self):
        """2026-09-06 finns ingen avtalad väg in hos någon kedja. Den dagen
        någon lägger till en provider ska DET vara ett medvetet beslut, inte
        något som glider in - därför står sanningen i ett test."""
        for chain in ("Willys", "Hemköp", "City Gross", "ICA", "Coop", "Lidl"):
            self.assertEqual(capability_for(chain), STORE_HOMEPAGE_FALLBACK, chain)

    def test_capabilities_are_ordered_from_best_to_worst(self):
        self.assertEqual(CAPABILITIES,
                         (FULL_CART_API, BULK_LIST_IMPORT, PRODUCT_DEEPLINK, STORE_HOMEPAGE_FALLBACK))

    def test_an_unknown_chain_still_gets_an_answer(self):
        self.assertEqual(capability_for("Okänd Kedja"), STORE_HOMEPAGE_FALLBACK)
        self.assertIsNotNone(provider_for("Okänd Kedja"))


class BasketTest(unittest.TestCase):
    def test_a_line_with_gtin_or_product_id_can_be_transferred_exactly(self):
        self.assertTrue(BasketLine("Mjölk", gtin="7310865004703").transferable_exactly)
        self.assertTrue(BasketLine("Mjölk", external_product_id="abc").transferable_exactly)
        self.assertFalse(BasketLine("Lök").transferable_exactly)

    def test_basket_is_built_from_the_same_rows_the_shopping_list_uses(self):
        basket = basket_from_items("Willys", [
            {"name": "Mjölk", "packages": 2, "product": {"gtin": "7310865004703", "productId": "p1"}},
            {"name": "Lök", "packages": 1},
            {"name": "", "packages": 1},
        ])
        self.assertEqual(len(basket.lines), 2, "namnlösa rader hoppas över")
        self.assertEqual(basket.lines[0].quantity, 2)
        self.assertEqual(len(basket.exact_lines), 1, "bara mjölken har GTIN")

    def test_quantity_is_never_below_one(self):
        basket = basket_from_items("Willys", [{"name": "Mjölk", "packages": 0}])
        self.assertEqual(basket.lines[0].quantity, 1)


class HandoffHonestyTest(unittest.TestCase):
    def test_the_fallback_says_plainly_that_nothing_was_transferred(self):
        basket = basket_from_items("Willys", [{"name": "Mjölk"}, {"name": "Lök"}])
        result = provider_for("Willys").handoff(basket)
        self.assertEqual(result.capability, STORE_HOMEPAGE_FALLBACK)
        self.assertEqual(result.transferred, 0)
        self.assertEqual(sorted(result.unmatched), ["Lök", "Mjölk"])
        self.assertFalse(result.complete)
        self.assertIn("Listan finns kvar", result.message)

    def test_a_result_is_only_complete_when_nothing_was_left_behind(self):
        self.assertTrue(HandoffResult(capability=FULL_CART_API, transferred=3).complete)
        self.assertFalse(HandoffResult(capability=FULL_CART_API, transferred=3,
                                       unmatched=["Saffran"]).complete)

    def test_the_fallback_points_at_a_real_store_page(self):
        for chain in ("Willys", "Hemköp", "City Gross"):
            result = provider_for(chain).handoff(CheckoutBasket(chain=chain))
            self.assertTrue(result.url.startswith("https://"), chain)


if __name__ == "__main__":
    unittest.main()
