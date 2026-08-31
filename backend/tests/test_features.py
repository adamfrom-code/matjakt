# -*- coding: utf-8 -*-
"""Tests för affärsmodellen: FREE FÖR ALLTID / 59 KR/MÅN / 399 KR/ÅR.

The rule every case protects: Free/Premium changes what is SHOWN, never what
is TRUE - and the backend, not the frontend, decides who sees what.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.accounts import features  # noqa: E402
import api_server  # noqa: E402


class PlanDerivation(unittest.TestCase):
    def test_anonymous_is_free(self):
        self.assertEqual(features.plan_for_user(None), "free")

    def test_registered_without_premium_is_free(self):
        self.assertEqual(features.plan_for_user({"premium": False}), "free")

    def test_yearly_subscription_is_premium_yearly(self):
        self.assertEqual(
            features.plan_for_user({"premium": True, "subscriptionPlan": "yearly"}),
            "premium_yearly")

    def test_monthly_subscription_is_premium_monthly(self):
        self.assertEqual(
            features.plan_for_user({"premium": True, "subscriptionPlan": "monthly"}),
            "premium_monthly")

    def test_legacy_premium_flag_is_grandfathered_as_monthly(self):
        """A redeem-code or legacy user must never wake up demoted."""
        self.assertEqual(
            features.plan_for_user({"premium": True, "subscriptionPlan": None}),
            "premium_monthly")


class FeatureMatrix(unittest.TestCase):
    def test_both_premium_plans_get_every_feature(self):
        for plan in ("premium_monthly", "premium_yearly"):
            for feature in features.FEATURES:
                self.assertTrue(features.allowed(plan, feature), f"{plan} saknar {feature}")

    def test_free_gets_the_core_loop(self):
        for feature in ("standard_week", "cheapest_store_price",
                        "cheapest_store_basket", "recipe_search",
                        "basic_pantry", "favorites"):
            self.assertTrue(features.allowed("free", feature), feature)

    def test_free_does_not_get_the_premium_set(self):
        for feature in ("family_week", "budget_week", "training_week", "bulk_week",
                        "quick_week", "vegetarian_week", "balanced_week",
                        "all_store_prices", "all_store_baskets", "store_comparison",
                        "advanced_nutrition", "full_pantry", "seven_dinners"):
            self.assertFalse(features.allowed("free", feature), feature)

    def test_dinner_caps(self):
        self.assertEqual(features.entitlements("free")["maxDinners"], 4)
        self.assertEqual(features.entitlements("premium_yearly")["maxDinners"], 7)

    def test_pricing_copy_is_arithmetically_honest(self):
        """59*12 - 399 = 309. The savings line is maths, not marketing."""
        monthly = features.PRICING["monthly"]["pricePerMonth"]
        yearly = features.PRICING["yearly"]["pricePerYear"]
        self.assertEqual(monthly * 12 - yearly, 309)
        self.assertIn("309", features.PRICING["yearly"]["savingsText"])
        self.assertEqual(features.PRICING["yearly"]["badge"], "Bäst värde")


def _chain(chain, total, covered, items=3, comparable=True):
    return {"chain": chain, "totalCheckoutCost": total, "realPriceItems": covered,
            "totalItems": items, "comparable": comparable,
            "items": [{"ingredient": "x"}], "missingItemNames": []}


class FreeMasking(unittest.TestCase):
    """mask_pricing_for_free: full sanning för billigaste kvalificerade
    butiken, ärliga siluetter av resten."""

    def _week(self):
        return {
            "results": [_chain("Willys", 400, 3), _chain("Hemköp", 450, 3),
                        _chain("City Gross", 480, 3)],
            "comparison": {"cheapestChain": "Willys", "savings": 80,
                           "priciestTotal": 480},
        }

    def test_free_sees_the_cheapest_chain_in_full(self):
        masked = api_server.mask_pricing_for_free(self._week())
        willys = next(r for r in masked["results"] if r["chain"] == "Willys")
        self.assertTrue(willys.get("free"))
        self.assertEqual(willys["totalCheckoutCost"], 400)
        self.assertIn("items", willys)

    def test_other_chains_lose_their_numbers_but_keep_their_names(self):
        masked = api_server.mask_pricing_for_free(self._week())
        hemkop = next(r for r in masked["results"] if r["chain"] == "Hemköp")
        self.assertTrue(hemkop["locked"])
        self.assertNotIn("totalCheckoutCost", hemkop)
        self.assertNotIn("items", hemkop)

    def test_the_spread_is_real_arithmetic_from_real_totals(self):
        """"Priserna skiljer sig med upp till 80 kr" - 480 minus 400,
        computed, never invented."""
        masked = api_server.mask_pricing_for_free(self._week())
        self.assertEqual(masked["comparison"]["priceSpread"], 80)

    def test_one_qualified_chain_means_no_spread_claim(self):
        week = {"results": [_chain("Willys", 400, 3)],
                "comparison": {"cheapestChain": None, "reason": "too_few_comparable_chains"}}
        masked = api_server.mask_pricing_for_free(week)
        self.assertIsNone(masked["comparison"]["priceSpread"])

    def test_free_chain_falls_back_to_best_real_total_without_a_verdict(self):
        week = {"results": [_chain("Hemköp", 450, 3), _chain("Willys", 400, 3)],
                "comparison": {"cheapestChain": None, "reason": "all_totals_identical"}}
        self.assertEqual(api_server._free_chain_for(week), "Willys")


if __name__ == "__main__":
    unittest.main()
