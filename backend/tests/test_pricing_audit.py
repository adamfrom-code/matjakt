# -*- coding: utf-8 -*-
"""Prisauditen (services/grocery/audit) - releasegatens egen kontroll måste
själv vara rätt. Falska larm är lika farliga som missade: en röd gate på
korrekta priser gör att ingen tror på gaten den dag den är röd på riktigt."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery.audit import kilo_price_as_pack_price, run_pricing_audit  # noqa: E402
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402
from services.recipes.store import RecipeStore  # noqa: E402


class KiloPriceAsPackPrice(unittest.TestCase):
    """Kontrollen bedömer PAKETPRISET konsumenten ser, aldrig unitPrice."""

    def test_pack_sold_at_the_kilo_price_is_flagged(self):
        row = {"packageSize": "ca: 850g", "packageAmount": 850, "packageUnit": "g",
               "comparisonPrice": 125.0, "totalCost": 125.0, "packages": 1,
               "perKg": False, "weightPriced": False}
        self.assertEqual(kilo_price_as_pack_price(row), 125.0)

    def test_pack_priced_by_weight_is_fine(self):
        row = {"packageSize": "ca: 850g", "packageAmount": 850, "packageUnit": "g",
               "comparisonPrice": 125.0, "totalCost": 106.25, "packages": 1,
               "perKg": False, "weightPriced": True}
        self.assertIsNone(kilo_price_as_pack_price(row))

    def test_loose_weight_per_kilo_is_never_this_error(self):
        # Två tomater à ca 98 g till 44,90 kr/kg: kostnaden är kr/kg × behov.
        # unitPrice ÄR kilopriset - det är modellen, inte ett fel.
        row = {"packageSize": "ca: 98g", "packageAmount": 98, "packageUnit": "g",
               "comparisonPrice": 44.9, "unitPrice": 44.9, "totalCost": 11.22, "packages": 1,
               "perKg": True, "weightPriced": False}
        self.assertIsNone(kilo_price_as_pack_price(row))

    def test_one_kilo_pack_and_fixed_weight_packs_are_ignored(self):
        self.assertIsNone(kilo_price_as_pack_price({
            "packageSize": "ca: 1kg", "packageAmount": 1000, "packageUnit": "g",
            "comparisonPrice": 89.0, "totalCost": 89.0, "packages": 1}))
        self.assertIsNone(kilo_price_as_pack_price({
            "packageSize": "500g", "packageAmount": 500, "packageUnit": "g",
            "comparisonPrice": 117.8, "totalCost": 58.9, "packages": 1}))

    def test_two_packs_at_the_kilo_price_each_are_flagged(self):
        row = {"packageSize": "ca: 700g", "packageAmount": 700, "packageUnit": "g",
               "comparisonPrice": 99.0, "totalCost": 198.0, "packages": 2}
        self.assertEqual(kilo_price_as_pack_price(row), 99.0)


class AuditAgainstTheRealEngine(unittest.TestCase):
    """Hela kedjan: butik + produkt + pris -> motorn -> auditen. Lösvikt till
    kilopris (tomater) ger GRÖN gate, inte ett kilopris-larm."""

    def _recipe(self, rs, ingredients):
        rs.upsert_recipe({"id": "test-audit", "name": "Tomatsallad med ris", "description": "", "servings": 4,
                          "prepTime": 5, "cookTime": 10, "difficulty": "lätt", "tags": [], "categories": [],
                          "dietFlags": [], "allergens": [], "instructions": ["Blanda."],
                          "ingredients": ingredients})

    def test_loose_tomatoes_at_kilo_price_are_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            gs = GroceryStore(Path(tmp) / "g.db")
            rs = RecipeStore(Path(tmp) / "r.db")
            try:
                store = gs.upsert_store(chain="Willys", external_store_id="w1", name="Willys Test", active=True)
                product = gs.find_or_create_product(RawProduct(
                    chain="Willys", external_product_id="tomat", name="Tomat Runda Sverige Klass 1",
                    store_id="w1", store_name="Willys", gtin=None, brand=None,
                    size="ca: 98g", quantity=None, unit=None, category="Frukt & grönt > Grönsaker > Tomat"))
                # Kilopris-signaturen: pris och jämförpris är samma tal (kr/kg).
                gs.upsert_current_price(product_id=product.id, store_id=store.id, regular_price=44.9,
                                        campaign_price=None, member_price=None, multibuy_price=None,
                                        unit_price=44.9, currency="SEK", source_url=None, fetched_at=time.time())
                self._recipe(rs, [{"name": "Tomat", "amount": 2, "unit": "st"}])
                result = run_pricing_audit(gs, rs, ["Willys"])
            finally:
                gs.close(); rs.close()
        self.assertEqual(result["kontroller"], 1)
        self.assertEqual(result["flaggor"]["saknade"], 0)
        self.assertEqual(result["flaggor"]["kilopris_som_paketpris"], 0, result.get("exempel"))
        self.assertEqual(result["gate"], "GRÖN")

    def test_uncertain_row_names_the_ingredient(self):
        """En osäker rad måste gå att åtgärda, alltså gå att hitta.

        30 ml soja mot en 150-gramsflaska: motorn kan inte räkna om ml till
        g för soja (ingen densitet finns) och raden blir korrekt ETT ESTIMAT.
        Det är rätt svar - men gaten blir röd, och siffran "estimat: 1" ensam
        säger inte VAD som är osäkert. Nedbrytningen ska namnge ingrediensen
        och enheten, aldrig produkten."""
        with tempfile.TemporaryDirectory() as tmp:
            gs = GroceryStore(Path(tmp) / "g.db")
            rs = RecipeStore(Path(tmp) / "r.db")
            try:
                store = gs.upsert_store(chain="Willys", external_store_id="w1", name="Willys Test", active=True)
                product = gs.find_or_create_product(RawProduct(
                    chain="Willys", external_product_id="soja", name="Soja Japansk",
                    store_id="w1", store_name="Willys", gtin=None, brand=None,
                    size="150 g", quantity=None, unit=None,
                    category="Skafferi > Såser & dressing > Soja"))
                gs.upsert_current_price(product_id=product.id, store_id=store.id, regular_price=24.9,
                                        campaign_price=None, member_price=None, multibuy_price=None,
                                        unit_price=166.0, currency="SEK", source_url=None, fetched_at=time.time())
                self._recipe(rs, [{"name": "Soja", "amount": 30, "unit": "ml"}])
                result = run_pricing_audit(gs, rs, ["Willys"])
            finally:
                gs.close(); rs.close()
        self.assertEqual(result["flaggor"]["saknade"], 0)
        self.assertEqual(result["flaggor"]["estimat"], 1, result.get("exempel"))
        self.assertEqual(result["estimatPerIngrediens"], {"Soja (ml)": 1})
        # Produktnamnet hör hemma i exempel (admin), aldrig i nedbrytningen.
        self.assertNotIn("Japansk", " ".join(result["estimatPerIngrediens"]))
        self.assertEqual(result["gate"], "RÖD")

    def test_certain_rows_leave_the_breakdown_empty(self):
        """Motsatsriktningen: gaten får inte kunna bli röd utan att någon rad
        faktiskt är osäker. Kanel i tsk mot en 30-gramsburk ryms i F5-regeln
        och ska förbli exakt - blir den ett estimat är regeln sönder."""
        with tempfile.TemporaryDirectory() as tmp:
            gs = GroceryStore(Path(tmp) / "g.db")
            rs = RecipeStore(Path(tmp) / "r.db")
            try:
                store = gs.upsert_store(chain="Willys", external_store_id="w1", name="Willys Test", active=True)
                product = gs.find_or_create_product(RawProduct(
                    chain="Willys", external_product_id="kanel", name="Kanel Malen",
                    store_id="w1", store_name="Willys", gtin=None, brand=None,
                    size="30 g", quantity=None, unit=None, category="Skafferi > Kryddor"))
                gs.upsert_current_price(product_id=product.id, store_id=store.id, regular_price=17.9,
                                        campaign_price=None, member_price=None, multibuy_price=None,
                                        unit_price=596.0, currency="SEK", source_url=None, fetched_at=time.time())
                self._recipe(rs, [{"name": "Kanel", "amount": 2, "unit": "tsk"}])
                result = run_pricing_audit(gs, rs, ["Willys"])
            finally:
                gs.close(); rs.close()
        self.assertEqual(result["flaggor"]["estimat"], 0, result.get("exempel"))
        self.assertEqual(result["estimatPerIngrediens"], {})
        self.assertEqual(result["gate"], "GRÖN")


if __name__ == "__main__":
    unittest.main()
