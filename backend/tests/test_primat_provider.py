# -*- coding: utf-8 -*-
"""PrimatProvider - ICA/Coop/Lidl-katalogimport via Primat.

Testerna kör helt utan nätverk: _call mockas med inspelade svarsformer
(verifierade live 2026-09-02 mot /prices, /batch och /stores/resolve)."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery.errors import ProviderBlockedError  # noqa: E402
from services.grocery.providers.primat import PrimatProvider, _epoch  # noqa: E402


def _price_row(**overrides):
    row = {
        "chain": "lidl", "store_id": "SE0128", "product_id": "0001032",
        "name": "Klyftpotatis", "brand": "Harvest Basket", "gtin": None,
        "changed_at": "2026-08-31T01:03:14Z",
        "price": 10.9, "member_price": None,
        "multi_price": None, "multi_count": None,
        "member_multi_price": None, "member_multi_count": None,
        "effective_price": 10.9,
        "offer_price": None, "offer_label": None, "offer_valid_until": None,
    }
    row.update(overrides)
    return row


def _detail(**overrides):
    detail = {
        "chain": "lidl", "store_id": "SE0128", "product_id": "0001032",
        "name": "Klyftpotatis", "brand": "Harvest Basket",
        "category": "Frukt & grönt > Potatis", "amount": 750.0, "unit": "g",
        "package": "750 g", "available": True, "gtin": "7310865093530",
        "prices": {"regular": 10.9, "comparison": {"price": 14.53, "unit": "kg"}},
        "confirmed_at": "2026-09-02T03:32:13Z",
        "urls": {"source": "https://www.lidl.se/p/x", "primat": "https://primat.nu/p/x"},
    }
    detail.update(overrides)
    return detail


class NormalizeProduct(unittest.TestCase):
    def setUp(self):
        self.provider = PrimatProvider("Lidl", api_key="test-nyckel")

    def test_full_mapping(self):
        raw = self.provider.normalize_product(
            (_price_row(gtin="7310865093530"), _detail(), "SE0128"))
        self.assertEqual(raw.chain, "Lidl")
        self.assertEqual(raw.external_product_id, "0001032")
        self.assertEqual(raw.gtin, "07310865093530")  # EAN-13 -> GTIN-14
        self.assertEqual(raw.size, "750 g")
        self.assertEqual(raw.quantity, 750.0)
        self.assertEqual(raw.unit, "g")
        self.assertEqual(raw.category, "Frukt & grönt > Potatis")
        self.assertEqual(raw.regular_price, 10.9)
        self.assertIsNone(raw.campaign_price)
        self.assertEqual(raw.unit_price, 14.53)
        self.assertEqual(raw.source_url, "https://www.lidl.se/p/x")
        self.assertIsNotNone(raw.fetched_at)

    def test_row_without_any_price_is_dropped_fail_closed(self):
        raw = self.provider.normalize_product(
            (_price_row(price=None, effective_price=None, offer_price=None),
             _detail(), "SE0128"))
        self.assertIsNone(raw)

    def test_offer_equal_to_regular_is_not_a_campaign(self):
        raw = self.provider.normalize_product(
            (_price_row(offer_price=10.9, offer_label="-0%"), None, "SE0128"))
        self.assertIsNone(raw.campaign_price)

    def test_offer_below_regular_is_a_campaign(self):
        raw = self.provider.normalize_product(
            (_price_row(price=15.9, offer_price=10.9), None, "SE0128"))
        self.assertEqual(raw.regular_price, 15.9)
        self.assertEqual(raw.campaign_price, 10.9)

    def test_offer_without_regular_keeps_the_campaign_price_only(self):
        """Kampanjrad utan ordinarie (Lidls kampanjblads-varor): kampanjen ÄR
        hyllpriset just nu, ordinarie förblir ärligt okänt."""
        raw = self.provider.normalize_product(
            (_price_row(price=None, effective_price=32.9, offer_price=32.9,
                        offer_label="-12%"), None, "SE0128"))
        self.assertIsNone(raw.regular_price)
        self.assertEqual(raw.campaign_price, 32.9)

    def test_missing_detail_gives_no_package_never_a_guess(self):
        raw = self.provider.normalize_product((_price_row(), None, "SE0128"))
        self.assertIsNone(raw.size)
        self.assertIsNone(raw.quantity)
        self.assertIsNone(raw.unit)

    def test_invalid_gtin_is_dropped_not_stored(self):
        raw = self.provider.normalize_product(
            (_price_row(gtin="12345"), None, "SE0128"))
        self.assertIsNone(raw.gtin)


class Stores(unittest.TestCase):
    def test_offers_only_stores_are_inactive(self):
        provider = PrimatProvider("ICA", api_key="test-nyckel")
        resolve = {"stores": [
            {"chain": "ica", "store_id": "1158001", "key": "ica:1158001",
             "name": "Maxi Brynäs", "city": "Gävle", "tier": "full"},
            {"chain": "ica", "store_id": "1048012", "key": "ica:1048012",
             "name": "Nära Stortorget", "city": "Gävle", "tier": "offers_only"},
            {"chain": "coop", "store_id": "206403", "key": "coop:206403",
             "name": "Coop Eken", "city": "Gävle", "tier": "full"},
        ]}
        with patch.object(PrimatProvider, "_call", return_value=resolve):
            stores = provider.get_stores()
        self.assertEqual([s.external_store_id for s in stores], ["1158001", "1048012"])
        self.assertTrue(stores[0].active)
        self.assertFalse(stores[1].active)  # offers_only duger inte till en matkorg


class ProductsPagination(unittest.TestCase):
    def test_pages_then_batch_merge(self):
        provider = PrimatProvider("Lidl", api_key="test-nyckel")
        calls = []

        def fake_call(method, path, params=None, body=None):
            calls.append((method, path))
            if path == "/prices" and not (params or {}).get("cursor"):
                return {"data": [_price_row(product_id="A"), _price_row(product_id="B")],
                        "next_cursor": "sida2"}
            if path == "/prices":
                return {"data": [_price_row(product_id="C")], "next_cursor": None}
            if path == "/batch":
                return {"data": [
                    {"lookup": {"product_id": pid},
                     "results": [_detail(product_id=pid, package=f"{pid}-paket")]}
                    for pid in [l["product_id"] for l in body["lookups"]]]}
            raise AssertionError(path)

        with patch.object(PrimatProvider, "_call", side_effect=fake_call):
            products = provider.get_products("SE0128")
        self.assertEqual(len(products), 3)
        self.assertEqual({p.external_product_id for p in products}, {"A", "B", "C"})
        self.assertEqual(products[0].size, "A-paket")  # batchdetaljen nådde raden
        self.assertEqual([c for c in calls if c[1] == "/prices"],
                         [("GET", "/prices"), ("GET", "/prices")])

    def test_row_cap_stops_honestly_with_partials(self):
        provider = PrimatProvider("Lidl", api_key="test-nyckel", max_rows=2)

        def fake_call(method, path, params=None, body=None):
            if path == "/prices":
                return {"data": [_price_row(product_id="A"), _price_row(product_id="B")],
                        "next_cursor": "mer-finns"}
            raise AssertionError(f"{path} skulle inte anropas efter taket")

        with patch.object(PrimatProvider, "_call", side_effect=fake_call):
            with self.assertRaises(ProviderBlockedError) as ctx:
                provider.get_products("SE0128")
        # Det hämtade följer med blockeringen - inget slängs, inget gissas.
        self.assertEqual(len(ctx.exception.partial_products), 2)
        self.assertIn("radtak", str(ctx.exception))


class ImporterRouting(unittest.TestCase):
    def test_coop_and_lidl_require_the_key(self):
        from services.grocery import importer
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("PRIMAT_API_KEY", None)
            for chain in ("Coop", "Lidl"):
                with self.assertRaises(ValueError):
                    importer._provider_for(chain)

    def test_primat_chains_route_to_primat_with_key(self):
        from services.grocery import importer
        with patch.dict("os.environ", {"PRIMAT_API_KEY": "test-nyckel"}):
            for chain in ("ICA", "Coop", "Lidl"):
                provider = importer._provider_for(chain)
                self.assertIsInstance(provider, PrimatProvider)
                self.assertEqual(provider.chain, chain)

    def test_untouched_chains_still_use_their_own_providers(self):
        from services.grocery import importer
        from services.grocery.providers.willys import WillysProvider
        with patch.dict("os.environ", {"PRIMAT_API_KEY": "test-nyckel"}):
            self.assertIsInstance(importer._provider_for("Willys"), WillysProvider)


class ReleasedChainsGate(unittest.TestCase):
    def test_unreleased_chains_never_reach_the_comparison(self):
        """En halvimporterad ICA/Coop/Lidl-katalog i databasen får aldrig
        räcka för att kedjan ska börja jämföras - släpp är ett beslut."""
        from services.grocery import api as gapi
        self.assertEqual(set(gapi.RELEASED_CHAINS), {"Willys", "Hemköp", "City Gross"})
        for chain in gapi.priceable_chains():
            self.assertIn(chain, gapi.RELEASED_CHAINS)


class Epoch(unittest.TestCase):
    def test_iso_z_and_none(self):
        self.assertAlmostEqual(_epoch("1970-01-01T00:00:10Z"), 10.0)
        self.assertIsNone(_epoch(None))
        self.assertIsNone(_epoch("inte-en-tid"))


if __name__ == "__main__":
    unittest.main()
