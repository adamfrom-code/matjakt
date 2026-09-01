# -*- coding: utf-8 -*-
"""RELEASE GATE (2026-09-02): de tre produktionsfelen Adam hittade, som
exakta regressioner, plus paketmatematikens invarianter.

    Fiskpinnar: 224 g behov mot 450 g-paket visades som 224 st och 6 561 kr.
    Persilja:   10 g behov mot 50 g-paket visades i stycken, ~100 kr.
    Kanel:      matchade "Wasa Kanel Veteknäcke" (Bröd & Kakor).

Två grundorsaker: frontends paketfallback behandlade vikt/volym utan
paketinfo som styck (fiskpinnar + persilja, samma rot), och torra kryddor
saknade avdelningskrav så bakverk som LEDER med kryddnamnet godkändes
(kanel, egen rot). Dessa tester låser båda för alltid."""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    RecipePricingEngine,
    convert_amount,
    packages_needed,
    product_matches_ingredient,
)
from services.grocery.store import GroceryStore  # noqa: E402


def _engine_with(products):
    """En motor mot en riktig temporär databas med givna produkter+priser."""
    import tempfile
    tmp = tempfile.TemporaryDirectory()
    db = GroceryStore(Path(tmp.name) / "gate.db")
    store = db.upsert_store(chain="Willys", external_store_id="1", name="Willys test",
                            city=None, postal_code=None, address=None,
                            latitude=None, longitude=None, active=True)
    for spec in products:
        product = db.find_or_create_product(RawProduct(
            chain="Willys", external_product_id=spec["id"], name=spec["name"],
            store_id="1", store_name="Willys", gtin=None, brand=spec.get("brand"),
            size=spec.get("size"), quantity=spec["quantity"], unit=spec["unit"],
            category=spec.get("category")))
        db.upsert_current_price(product_id=product.id, store_id=store.id,
                                regular_price=spec["price"], campaign_price=None,
                                member_price=None, multibuy_price=None, unit_price=None,
                                currency="SEK", source_url=None, fetched_at=None)
    engine = RecipePricingEngine(db)
    return engine, store.id, tmp, db


class TheThreeProductionErrors(unittest.TestCase):
    def test_fiskpinnar_224g_against_450g_package_is_one_package(self):
        engine, store_id, tmp, db = _engine_with([{
            "id": "fp", "name": "Fiskpinnar Frysta/15-pack", "size": "450g",
            "quantity": 450.0, "unit": "g", "price": 23.5,
            "category": "Fryst > Fisk & skaldjur > Fisk"}])
        try:
            row = engine.price_item("Fiskpinnar", 224, "g", "Willys", store_id)
            self.assertIsNotNone(row)
            self.assertEqual(row["packages"], 1)
            self.assertTrue(row["exactPackaging"])
            self.assertEqual(row["totalCost"], 23.5)
        finally:
            db.close(); tmp.cleanup()

    def test_persilja_10g_against_50g_package_is_one_package(self):
        engine, store_id, tmp, db = _engine_with([{
            "id": "pe", "name": "Persilja Finhackad Fryst", "size": "50g",
            "quantity": 50.0, "unit": "g", "price": 8.9,
            "category": "Fryst > Grönsaker & kryddor > Kryddor"}])
        try:
            row = engine.price_item("Persilja", 10, "g", "Willys", store_id)
            self.assertIsNotNone(row)
            self.assertEqual(row["packages"], 1)
            self.assertTrue(row["exactPackaging"])
            self.assertEqual(row["totalCost"], 8.9)
        finally:
            db.close(); tmp.cleanup()

    def test_kanel_kryddmatt_against_spice_jar_is_one_package_decided(self):
        """2-5 g eller 1 tsk kanel mot en kryddburk är EN förpackning - en
        bestämd regel (<=30 ml kryddmått mot >=15 g-förpackning), inte en
        gissning, så raden får ingå i säkra totaler."""
        engine, store_id, tmp, db = _engine_with([{
            "id": "ka", "name": "Kanel Malen Påse", "size": "19g",
            "quantity": 19.0, "unit": "g", "price": 12.2,
            "category": "Skafferi > Kryddor & smaksättare > Kryddor"}])
        try:
            for amount, unit in ((2, "g"), (5, "g"), (1, "tsk"), (1, "msk")):
                row = engine.price_item("Kanel", amount, unit, "Willys", store_id)
                self.assertIsNotNone(row, f"{amount} {unit}")
                self.assertEqual(row["packages"], 1, f"{amount} {unit}")
                self.assertTrue(row["exactPackaging"], f"{amount} {unit}")
        finally:
            db.close(); tmp.cleanup()

    def test_kanel_never_matches_kanel_flavoured_bakery(self):
        for product, category in [
            ("Kanel Veteknäcke Runt", "Bröd & Kakor > Knäckebröd & Skorpor"),
            ("Kanelbullar 6-pack", "Bröd & bageri > Kaffebröd"),
            ("Kanelkakor", "Bröd & Kakor > Kex"),
            ("Kanellängd", "Bröd & bageri"),
            ("Kanel & Äpple Gröt", "Skafferi > Frukost"),
        ]:
            self.assertFalse(
                product_matches_ingredient(product, "Kanel", "Wasa", category),
                f"{product!r} får aldrig prissätta kryddan kanel")
        # ...och den äkta varan måste förstås fortsätta matcha.
        self.assertTrue(product_matches_ingredient(
            "Kanel Malen Påse", "Kanel", None, "Skafferi > Kryddor & smaksättare"))


class PackageMathInvariants(unittest.TestCase):
    """packages = ceil(behov / paket) i RÄTT enhet - för varje familj."""

    def test_weight_invariant(self):
        for required, package in [(224, 450), (10, 50), (500, 500), (501, 500),
                                  (1000, 400), (1, 2000), (999, 100)]:
            self.assertEqual(packages_needed(required, "g", package, "g"),
                             math.ceil(required / package), f"{required}g/{package}g")

    def test_weight_with_kg_conversion(self):
        self.assertEqual(packages_needed(1.5, "kg", 500, "g"), 3)
        self.assertEqual(packages_needed(400, "g", 1, "kg"), 1)

    def test_volume_invariant(self):
        for required, unit, package, punit, expected in [
            (11, "dl", 1000, "ml", 2), (2, "l", 1000, "ml", 2),
            (5, "dl", 2, "dl", 3), (30, "cl", 300, "ml", 1),
            (1, "msk", 500, "ml", 1),
        ]:
            self.assertEqual(packages_needed(required, unit, package, punit), expected,
                             f"{required}{unit} / {package}{punit}")

    def test_count_invariant(self):
        for required, package, expected in [(2, 1, 2), (10, 6, 2), (6, 6, 1), (7, 6, 2)]:
            self.assertEqual(packages_needed(required, "st", package, "st"), expected)

    def test_cross_family_refuses_instead_of_guessing(self):
        self.assertIsNone(packages_needed(2, "st", 450, "g"))
        self.assertIsNone(packages_needed(200, "g", 500, "ml"))
        self.assertIsNone(convert_amount(1, "tsk", "g"))


if __name__ == "__main__":
    unittest.main()
