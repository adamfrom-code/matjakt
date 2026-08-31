"""Tests for CityGrossProvider.

Fixtures are trimmed copies of REAL responses captured live from
www.citygross.se on 2026-08-30 - same field names and values (gtin,
productStoreDetails price block, image filename, categories). Nothing here
touches the network.
"""

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery.errors import ProviderBlockedError  # noqa: E402
from services.grocery.providers import citygross as cg_module  # noqa: E402
from services.grocery.providers.citygross import (  # noqa: E402
    CityGrossBlockedError, CityGrossProvider, CityGrossRequestError,
    extract_prices, gtin_checksum_ok, normalize_gtin14,
)

# Real product, verbatim from the live API.
REAL_PRODUCT = {
    "id": "101233933_ST",
    "gtin": "7340083443893",
    "url": "/matvaror/mejeri-ost-och-agg/mjolk-och-dryck/garant-mellanmjolk-langre-hallbarhet-p101233933_ST",
    "name": "Mellanmjölk Längre Hållbarhet",
    "subtitle": "1,5L 1,5% GARANT",
    "description": "Mellanmjölk från våra svenska gårdar. Med lite längre hållbarhet.",
    "brand": "GARANT",
    "superCategory": "Mejeri, ost & ägg",
    "category": "Mjölk & dryck",
    "bfCategory": "Mellanmjölk",
    "countryOfOrigin": "SVERIGE",
    "descriptiveSize": "1,5L",
    "netContent": {"unitOfMeasure": 0, "value": 1500},
    "images": [{"url": "VI_734008344389320241104-083259-763.jpeg", "alt": "Mellanmjölk", "type": 0}],
    "productStoreDetails": {
        "p_has_price": True,
        "p_has_members_only_price": False,
        "prices": {
            "currentPrice": {"price": 16.5, "unit": "PCE", "comparativePrice": 11, "comparativePriceUnit": "LTR"},
            "ordinaryPrice": {"price": 16.5, "unit": "PCE", "comparativePrice": 11, "comparativePriceUnit": "LTR"},
            "memberPrice": None,
            "promotions": [], "activePromotion": None,
            "hasDiscount": False, "hasPromotion": False,
            "displayLowestPriceLast30Days": False, "lowestPriceLast30Days": None,
        },
    },
}

REAL_SITES = {"sites": [
    {"id": 35, "type": 3, "no": "City Gross Gävle", "name": "City Gross Gävle",
     "streetAddress": "Ingenjörsgatan 15", "zipcode": "80293", "city": "Gävle", "storeNumber": "3209"},
    {"id": 34, "type": 3, "no": "City Gross Falun", "name": "City Gross Falun",
     "streetAddress": "Stortallsvägen 3", "zipcode": "79155", "city": "Falun", "storeNumber": "3207"},
]}

REAL_STORE_PAGES = [
    {"data": {"storeName": "Gävle", "storeLocation": {"coordinates": "60.6749,17.1413"}}},
    {"data": {"storeName": "Falun", "storeLocation": {"coordinates": "60.6036,15.6260"}}},
]


def search_response(*products, total=None):
    return {"searchResults": {"products": list(products), "totalCount": total if total is not None else len(products),
                              "pageSize": 20, "currentPage": 0, "totalPages": 1}}


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"", *, status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def route(mapping, default=None):
    """Dispatch by substring of the requested URL, so a test can serve the
    sites/store-pages/search endpoints differently in one run."""
    def _open(request, timeout=None):
        url = request.full_url
        for needle, payload in mapping.items():
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(json.dumps(payload).encode("utf-8"))
        if default is None:
            raise AssertionError(f"unexpected URL in test: {url}")
        return FakeResponse(json.dumps(default).encode("utf-8"))
    return _open


def http_error(code):
    return urllib.error.HTTPError("https://example.test", code, "refused", {}, io.BytesIO(b""))


class Base(unittest.TestCase):
    def setUp(self):
        self.provider = CityGrossProvider(search_terms=["mjölk"])
        self._orig = cg_module.urllib.request.urlopen
        self._sleep = cg_module.time.sleep
        cg_module.time.sleep = lambda s: None

    def tearDown(self):
        cg_module.urllib.request.urlopen = self._orig
        cg_module.time.sleep = self._sleep


class GtinNormalizationTest(unittest.TestCase):
    """City Gross returns EAN-13 while the Axfood chains yield GTIN-14 for the
    SAME product. Without zero-padding, cross-chain matching silently fails."""

    def test_real_ean13_is_padded_to_the_axfood_gtin14(self):
        self.assertEqual(normalize_gtin14("7340083443893"), "07340083443893")

    def test_already_14_digits_is_unchanged(self):
        self.assertEqual(normalize_gtin14("07340083443893"), "07340083443893")

    def test_padding_preserves_checksum_validity(self):
        self.assertTrue(gtin_checksum_ok("7340083443893"))
        self.assertTrue(gtin_checksum_ok("07340083443893"))

    def test_invalid_checksum_yields_none_not_a_guess(self):
        self.assertIsNone(normalize_gtin14("7340083443894"))

    def test_non_numeric_and_empty_yield_none(self):
        for bad in [None, "", "abc", "12"]:
            self.assertIsNone(normalize_gtin14(bad))

    def test_strips_separators_before_validating(self):
        self.assertEqual(normalize_gtin14("7340083-443893"), "07340083443893")


class PriceExtractionTest(unittest.TestCase):
    def test_ordinary_price_becomes_regular_price(self):
        p = extract_prices(REAL_PRODUCT["productStoreDetails"])
        self.assertEqual(p["regular_price"], 16.5)
        self.assertEqual(p["unit_price"], 11)

    def test_no_campaign_when_current_equals_ordinary(self):
        """Recording the ordinary price as a campaign would invent a discount
        that doesn't exist - the single most misleading thing this could do."""
        p = extract_prices(REAL_PRODUCT["productStoreDetails"])
        self.assertIsNone(p["campaign_price"])

    def test_campaign_only_when_current_is_genuinely_lower(self):
        details = {"prices": {"currentPrice": {"price": 12.0, "comparativePrice": 8},
                              "ordinaryPrice": {"price": 16.5}, "memberPrice": None}}
        p = extract_prices(details)
        self.assertEqual(p["regular_price"], 16.5)
        self.assertEqual(p["campaign_price"], 12.0)

    def test_current_higher_than_ordinary_is_not_a_campaign(self):
        details = {"prices": {"currentPrice": {"price": 20.0}, "ordinaryPrice": {"price": 16.5}}}
        self.assertIsNone(extract_prices(details)["campaign_price"])

    def test_member_price_is_read_when_present(self):
        details = {"prices": {"currentPrice": {"price": 16.5}, "ordinaryPrice": {"price": 16.5},
                              "memberPrice": {"price": 13.9}}}
        self.assertEqual(extract_prices(details)["member_price"], 13.9)

    def test_member_price_none_stays_none(self):
        self.assertIsNone(extract_prices(REAL_PRODUCT["productStoreDetails"])["member_price"])

    def test_falls_back_to_current_when_ordinary_missing(self):
        details = {"prices": {"currentPrice": {"price": 9.9}}}
        self.assertEqual(extract_prices(details)["regular_price"], 9.9)

    def test_missing_prices_yield_none_not_zero(self):
        p = extract_prices({})
        self.assertIsNone(p["regular_price"])
        self.assertIsNone(p["unit_price"])
        p2 = extract_prices(None)
        self.assertIsNone(p2["regular_price"])

    def test_multibuy_is_none_because_the_api_exposes_no_such_structure(self):
        self.assertIsNone(extract_prices(REAL_PRODUCT["productStoreDetails"])["multibuy_price"])


class NormalizationTest(Base):
    def test_maps_all_supported_fields(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "3209"})
        self.assertEqual(raw.chain, "City Gross")
        self.assertEqual(raw.external_product_id, "101233933_ST")
        self.assertEqual(raw.name, "Mellanmjölk Längre Hållbarhet")
        self.assertEqual(raw.brand, "GARANT")
        self.assertEqual(raw.size, "1,5L")
        self.assertEqual((raw.quantity, raw.unit), (1.5, "L"))
        self.assertEqual(raw.regular_price, 16.5)
        self.assertEqual(raw.unit_price, 11)
        self.assertEqual(raw.currency, "SEK")
        self.assertEqual(raw.store_id, "3209")

    def test_gtin_is_normalized_for_cross_chain_matching(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "3209"})
        self.assertEqual(raw.gtin, "07340083443893")

    def test_category_is_the_whole_path_broadest_first(self):
        """City Gross' three levels are joined into one path, in the same
        shape the Axfood chains produce. The leaf alone is not enough:
        category-aware matching (see grocery/pricing.py) needs the DEPARTMENT
        to reject a wrong aisle, and only the ancestors carry it -
        "Mellanmjölk" does not say "dairy", "Mejeri, ost & ägg" does."""
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "3209"})
        self.assertEqual(raw.category, "Mejeri, ost & ägg > Mjölk & dryck > Mellanmjölk")

    def test_category_path_skips_levels_the_product_lacks(self):
        without = {k: v for k, v in REAL_PRODUCT.items() if k != "bfCategory"}
        raw = self.provider.normalize_product({**without, "_store_id": "3209"})
        self.assertEqual(raw.category, "Mejeri, ost & ägg > Mjölk & dryck")

    def test_image_filename_is_expanded_to_a_full_url(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "3209"})
        self.assertEqual(raw.image_url,
                         "https://www.citygross.se/images/products/VI_734008344389320241104-083259-763.jpeg")

    def test_missing_image_yields_none(self):
        without = {k: v for k, v in REAL_PRODUCT.items() if k != "images"}
        self.assertIsNone(self.provider.normalize_product({**without, "_store_id": "3209"}).image_url)

    def test_empty_image_list_yields_none(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "images": [], "_store_id": "3209"})
        self.assertIsNone(raw.image_url)

    def test_source_url_is_absolute(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "3209"})
        self.assertTrue(raw.source_url.startswith("https://www.citygross.se/"))
        self.assertIn("101233933_ST", raw.source_url)

    def test_invalid_gtin_is_dropped_rather_than_stored(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "gtin": "1234567890123", "_store_id": "3209"})
        self.assertIsNone(raw.gtin)


class StoreListTest(Base):
    def test_uses_store_number_as_external_id_and_merges_coordinates(self):
        """storeNumber - not id/siteId - is the only value the search endpoint
        accepts, verified live. Coordinates come from the other endpoint."""
        cg_module.urllib.request.urlopen = route({
            "sites?siteTypeId=3": REAL_SITES,
            "PageData/stores": REAL_STORE_PAGES,
        })
        stores = self.provider.get_stores()
        gavle = next(s for s in stores if s.name == "City Gross Gävle")
        self.assertEqual(gavle.external_store_id, "3209")
        self.assertEqual(gavle.city, "Gävle")
        self.assertAlmostEqual(gavle.latitude, 60.6749)
        self.assertAlmostEqual(gavle.longitude, 17.1413)

    def test_still_works_when_coordinate_endpoint_fails(self):
        """Coordinates are a nice-to-have; losing them must not lose the store."""
        cg_module.urllib.request.urlopen = route({
            "sites?siteTypeId=3": REAL_SITES,
            "PageData/stores": http_error(500),
        })
        stores = self.provider.get_stores()
        self.assertEqual(len(stores), 2)
        self.assertIsNone(stores[0].latitude)

    def test_sites_without_store_number_are_skipped(self):
        cg_module.urllib.request.urlopen = route({
            "sites?siteTypeId=3": {"sites": [{"name": "Utan nummer", "city": "X"}]},
            "PageData/stores": [],
        })
        self.assertEqual(self.provider.get_stores(), [])

    def test_health_check_true_when_sites_returned(self):
        cg_module.urllib.request.urlopen = route({"sites?siteTypeId=3": REAL_SITES})
        self.assertTrue(self.provider.health_check())

    def test_health_check_false_when_refused(self):
        cg_module.urllib.request.urlopen = route({"sites?siteTypeId=3": http_error(403)})
        self.assertFalse(self.provider.health_check())


class ProductListingTest(Base):
    def test_normalizes_search_results(self):
        cg_module.urllib.request.urlopen = route({"Loop54/search": search_response(REAL_PRODUCT)})
        products = self.provider.get_products("3209")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].gtin, "07340083443893")

    def test_pagination_is_followed(self):
        second = {**REAL_PRODUCT, "id": "999_ST", "gtin": "7310865005168", "name": "Annan"}
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            page = search_response(REAL_PRODUCT, total=40) if "skip=0" in request.full_url else search_response(second, total=40)
            return FakeResponse(json.dumps(page).encode("utf-8"))

        cg_module.urllib.request.urlopen = _open
        products = self.provider.get_products("3209")
        self.assertEqual(calls["n"], 2)
        self.assertEqual({p.external_product_id for p in products}, {"101233933_ST", "999_ST"})

    def test_duplicate_ids_returned_once(self):
        provider = CityGrossProvider(search_terms=["mjölk", "mjolk"])
        cg_module.urllib.request.urlopen = route({"Loop54/search": search_response(REAL_PRODUCT)})
        self.assertEqual(len(provider.get_products("3209")), 1)

    def test_products_without_id_are_skipped(self):
        cg_module.urllib.request.urlopen = route({"Loop54/search": search_response({"name": "Utan id"})})
        self.assertEqual(self.provider.get_products("3209"), [])

    def test_empty_results_are_not_an_error(self):
        cg_module.urllib.request.urlopen = route({"Loop54/search": search_response()})
        self.assertEqual(self.provider.get_products("3209"), [])

    def test_get_product_details_finds_matching_id(self):
        cg_module.urllib.request.urlopen = route({"Loop54/search": search_response(REAL_PRODUCT)})
        raw = self.provider.get_product_details("101233933_ST", "3209")
        self.assertIsNotNone(raw)
        self.assertEqual(raw.name, "Mellanmjölk Längre Hållbarhet")

    def test_get_product_details_returns_none_when_absent(self):
        cg_module.urllib.request.urlopen = route({"Loop54/search": search_response(REAL_PRODUCT)})
        self.assertIsNone(self.provider.get_product_details("nope", "3209"))


class ErrorHandlingTest(Base):
    def test_403_and_429_are_terminal_blocks(self):
        for code in (403, 429):
            attempts = []

            def _open(request, timeout=None):
                attempts.append(1)
                raise http_error(code)

            cg_module.urllib.request.urlopen = _open
            with self.assertRaises(CityGrossBlockedError):
                self.provider.get_stores()
            self.assertEqual(len(attempts), 1, f"HTTP {code} must not be retried")

    def test_blocked_error_is_a_shared_provider_blocked_error(self):
        """The shared collector catches ProviderBlockedError - if this
        subclassing broke, a City Gross block would crash the run instead of
        being handled and reported."""
        self.assertTrue(issubclass(CityGrossBlockedError, ProviderBlockedError))

    def test_server_error_is_retried_then_reported(self):
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            raise http_error(500)

        cg_module.urllib.request.urlopen = _open
        with self.assertRaises(CityGrossRequestError):
            self.provider.get_stores()
        self.assertEqual(len(attempts), cg_module.MAX_RETRIES)

    def test_timeout_is_retried_then_reported(self):
        cg_module.urllib.request.urlopen = lambda r, timeout=None: (_ for _ in ()).throw(TimeoutError())
        with self.assertRaises(CityGrossRequestError):
            self.provider.get_stores()

    def test_malformed_json_is_reported(self):
        cg_module.urllib.request.urlopen = lambda r, timeout=None: FakeResponse(b"<html>nope</html>")
        with self.assertRaises(CityGrossRequestError):
            self.provider.get_stores()

    def test_empty_body_is_treated_as_a_block(self):
        cg_module.urllib.request.urlopen = lambda r, timeout=None: FakeResponse(b"")
        with self.assertRaises(CityGrossBlockedError):
            self.provider.get_stores()

    def test_block_preserves_already_collected_products(self):
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse(json.dumps(search_response(REAL_PRODUCT)).encode("utf-8"))
            raise http_error(429)

        provider = CityGrossProvider(search_terms=["mjölk", "smör"])
        cg_module.urllib.request.urlopen = _open
        with self.assertRaises(CityGrossBlockedError) as ctx:
            provider.get_products("3209")
        self.assertEqual(len(ctx.exception.partial_products), 1)

    def test_failed_term_does_not_abort_the_run(self):
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] <= cg_module.MAX_RETRIES:
                raise http_error(500)
            return FakeResponse(json.dumps(search_response(REAL_PRODUCT)).encode("utf-8"))

        provider = CityGrossProvider(search_terms=["trasig", "mjölk"])
        cg_module.urllib.request.urlopen = _open
        self.assertEqual(len(provider.get_products("3209")), 1)


if __name__ == "__main__":
    unittest.main()
