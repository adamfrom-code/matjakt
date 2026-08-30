"""Tests for WillysProvider.

Fixtures are trimmed copies of REAL responses captured live from
www.willys.se on 2026-08-30 - same field names, same values (prices, GTINs,
promotion shapes). Nothing here contacts the network.
"""

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery.providers import willys as willys_module  # noqa: E402
from services.grocery.providers.willys import (  # noqa: E402
    WillysBlockedError, WillysProvider, WillysRequestError,
    _gtin_checksum_ok, _gtin_from_image_url, _parse_display_volume,
    _parse_swedish_price, _split_promotions,
)

# Real product (Smör Normalsaltat 82%), verbatim field values.
REAL_PRODUCT = {
    "code": "101017249_ST",
    "name": "Smör Normalsaltat 82%",
    "manufacturer": "Svenskt Smör",
    "displayVolume": "500g",
    "productLine2": "SVENSKT SMÖR, 500g",
    "price": "59,50 kr",
    "priceValue": 59.5,
    "priceNoUnit": "59,50",
    "priceUnit": "kr/st",
    "comparePrice": "119,00 kr",
    "comparePriceUnit": "kg",
    "savingsAmount": None,
    "googleAnalyticsCategory": "",
    "outOfStock": False,
    "online": True,
    "labels": ["swedish_flag", "from_sweden"],
    "potentialPromotions": [],
    "image": {"imageType": "PRIMARY", "format": "product",
              "url": "https://assets.axfood.se/image/upload/f_auto,t_200/07310865005168_C1L1_s01"},
    "thumbnail": {"imageType": "PRIMARY", "format": "thumbnail",
                  "url": "https://assets.axfood.se/image/upload/f_auto,t_100/07310865005168_C1L1_s01"},
}

# Real straight-discount promotion (Högrev Nötkött Irland: 145.00 -> 129.00).
REAL_CAMPAIGN_PRODUCT = {
    **REAL_PRODUCT, "code": "200000001_ST", "name": "Högrev Nötkött Irland", "priceValue": 145.0,
    "potentialPromotions": [{
        "conditionLabelFormatted": "", "price": {"currencyIso": "SEK", "value": 129.0, "priceType": "BUY"},
        "code": "2500300001", "applied": False,
    }],
}

# Real multibuy promotion (chips: 24.90 ordinary, "2 för" 20.00 per unit).
REAL_MULTIBUY_PRODUCT = {
    **REAL_PRODUCT, "code": "101197040_ST", "name": "Havssalt Räfflade Västkustchips", "priceValue": 24.9,
    "potentialPromotions": [{
        "conditionLabelFormatted": "2 för", "price": {"currencyIso": "SEK", "value": 20.0, "priceType": "BUY"},
        "code": "2500312588", "applied": False,
    }],
}

REAL_STORE_LIST = [
    {"storeId": "2132", "name": "Willys Gävle Gestrike", "onlineStore": True,
     "address": {"town": "Gävle", "postalCode": "80267", "line1": "Gestrikevägen 1"},
     "geoPoint": {"latitude": 60.6749, "longitude": 17.1413}},
    {"storeId": "2223", "name": "Willys Gävle Hemsta", "onlineStore": True,
     "address": {"town": "Gävle", "postalCode": "80425", "line1": "Hemstavägen 2"},
     "geoPoint": {"latitude": 60.6612, "longitude": 17.1201}},
    # Axfood uses 0.0/0.0 as "no coordinates" - must not be stored as a real position.
    {"storeId": "9999", "name": "Willys Offline", "onlineStore": False,
     "address": {"town": "Nowhere"}, "geoPoint": {"latitude": 0.0, "longitude": 0.0}},
]


def search_response(*products, total_pages=1, current_page=0):
    return {
        "results": list(products),
        "pagination": {"pageSize": 30, "currentPage": current_page,
                       "numberOfPages": total_pages, "totalNumberOfResults": len(products)},
    }


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"", *, status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_urlopen(payload, *, raw_bytes=None):
    def _open(request, timeout=None):
        return FakeResponse(raw_bytes if raw_bytes is not None else json.dumps(payload).encode("utf-8"))
    return _open


def http_error(code):
    return urllib.error.HTTPError("https://example.test", code, "refused", {}, io.BytesIO(b""))


class WillysTestBase(unittest.TestCase):
    def setUp(self):
        self.provider = WillysProvider(search_terms=["smör"])
        self._orig_urlopen = willys_module.urllib.request.urlopen
        self._orig_sleep = willys_module.time.sleep
        willys_module.time.sleep = lambda s: None

    def tearDown(self):
        willys_module.urllib.request.urlopen = self._orig_urlopen
        willys_module.time.sleep = self._orig_sleep


class GtinDerivationTest(unittest.TestCase):
    """GTIN is derived from the image URL, not an API field - so validating it
    is the whole safeguard against wrongly merging two different products."""

    def test_real_gtins_from_the_live_import_validate(self):
        # Every one of these was pulled from a real Willys image URL.
        for code in ["07310865005168", "07340083443893", "07311043002191", "07340083427299",
                     "07393061000342", "07311041070390"]:
            self.assertTrue(_gtin_checksum_ok(code), code)

    def test_checksum_rejects_a_corrupted_digit(self):
        self.assertFalse(_gtin_checksum_ok("07310865005169"))
        self.assertFalse(_gtin_checksum_ok("07310865005160"))

    def test_checksum_rejects_wrong_lengths_and_non_digits(self):
        for bad in ["1234567", "123456789012345", "abcdefghijklmn", ""]:
            self.assertFalse(_gtin_checksum_ok(bad))

    def test_extracts_gtin_from_a_real_image_url(self):
        self.assertEqual(
            _gtin_from_image_url("https://assets.axfood.se/image/upload/f_auto,t_200/07310865005168_C1L1_s01"),
            "07310865005168",
        )

    def test_returns_none_when_the_embedded_code_fails_checksum(self):
        """A code that doesn't validate must be treated as no-GTIN, never
        stored as a guess."""
        self.assertIsNone(_gtin_from_image_url("https://assets.axfood.se/image/upload/f_auto/07310865005169_C1L1_s01"))

    def test_returns_none_for_urls_without_a_code(self):
        self.assertIsNone(_gtin_from_image_url("https://assets.axfood.se/image/upload/placeholder.png"))
        self.assertIsNone(_gtin_from_image_url(None))
        self.assertIsNone(_gtin_from_image_url(""))


class PromotionSplitTest(unittest.TestCase):
    """Campaign vs multibuy must not be conflated - storing a '2 för 20 kr'
    per-unit price as a campaign price would overstate the discount for
    someone buying one item."""

    def test_empty_condition_label_is_a_campaign_price(self):
        campaign, multibuy = _split_promotions(REAL_CAMPAIGN_PRODUCT["potentialPromotions"])
        self.assertEqual(campaign, 129.0)
        self.assertIsNone(multibuy)

    def test_n_for_label_is_a_multibuy_not_a_campaign(self):
        campaign, multibuy = _split_promotions(REAL_MULTIBUY_PRODUCT["potentialPromotions"])
        self.assertIsNone(campaign)
        self.assertEqual(multibuy, 20.0)

    def test_three_for_is_also_multibuy(self):
        campaign, multibuy = _split_promotions([
            {"conditionLabelFormatted": "3 för", "price": {"value": 13.33}},
        ])
        self.assertIsNone(campaign)
        self.assertEqual(multibuy, 13.33)

    def test_no_promotions_yields_two_nones(self):
        self.assertEqual(_split_promotions([]), (None, None))
        self.assertEqual(_split_promotions(None), (None, None))

    def test_promotion_without_a_price_is_ignored(self):
        self.assertEqual(_split_promotions([{"conditionLabelFormatted": ""}]), (None, None))

    def test_cheapest_wins_when_several_promotions_of_a_kind_exist(self):
        campaign, _ = _split_promotions([
            {"conditionLabelFormatted": "", "price": {"value": 129.0}},
            {"conditionLabelFormatted": "", "price": {"value": 119.0}},
        ])
        self.assertEqual(campaign, 119.0)


class ParsingTest(unittest.TestCase):
    def test_parses_real_swedish_prices(self):
        self.assertEqual(_parse_swedish_price("119,00 kr"), 119.0)
        self.assertEqual(_parse_swedish_price("59,50 kr"), 59.5)
        self.assertEqual(_parse_swedish_price("138,33 kr"), 138.33)

    def test_unparseable_price_is_none_not_zero(self):
        self.assertIsNone(_parse_swedish_price(None))
        self.assertIsNone(_parse_swedish_price(""))
        self.assertIsNone(_parse_swedish_price("inget pris"))

    def test_parses_real_display_volumes(self):
        self.assertEqual(_parse_display_volume("1,5l"), (1.5, "l"))
        self.assertEqual(_parse_display_volume("500g"), (500.0, "g"))

    def test_unparseable_volume_returns_none(self):
        self.assertEqual(_parse_display_volume("ca 6-pack"), (None, None))
        self.assertEqual(_parse_display_volume(None), (None, None))


class NormalizationTest(WillysTestBase):
    def test_normal_product_maps_all_supported_fields(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "2132"})
        self.assertEqual(raw.chain, "Willys")
        self.assertEqual(raw.external_product_id, "101017249_ST")
        self.assertEqual(raw.name, "Smör Normalsaltat 82%")
        self.assertEqual(raw.brand, "Svenskt Smör")
        self.assertEqual(raw.size, "500g")
        self.assertEqual(raw.quantity, 500.0)
        self.assertEqual(raw.unit, "g")
        self.assertEqual(raw.regular_price, 59.5)
        self.assertEqual(raw.unit_price, 119.0)
        self.assertEqual(raw.currency, "SEK")
        self.assertEqual(raw.store_id, "2132")

    def test_gtin_is_populated_from_the_validated_image_url(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "2132"})
        self.assertEqual(raw.gtin, "07310865005168")

    def test_image_url_is_the_real_axfood_url(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "2132"})
        self.assertEqual(raw.image_url, REAL_PRODUCT["image"]["url"])

    def test_product_without_image_has_no_image_and_no_gtin(self):
        without = {k: v for k, v in REAL_PRODUCT.items() if k not in ("image", "thumbnail")}
        raw = self.provider.normalize_product({**without, "_store_id": "2132"})
        self.assertIsNone(raw.image_url)
        self.assertIsNone(raw.gtin)

    def test_falls_back_to_thumbnail_when_primary_image_missing(self):
        without_primary = {k: v for k, v in REAL_PRODUCT.items() if k != "image"}
        raw = self.provider.normalize_product({**without_primary, "_store_id": "2132"})
        self.assertEqual(raw.image_url, REAL_PRODUCT["thumbnail"]["url"])
        self.assertEqual(raw.gtin, "07310865005168")

    def test_campaign_product_sets_campaign_not_multibuy(self):
        raw = self.provider.normalize_product({**REAL_CAMPAIGN_PRODUCT, "_store_id": "2132"})
        self.assertEqual(raw.regular_price, 145.0)
        self.assertEqual(raw.campaign_price, 129.0)
        self.assertIsNone(raw.multibuy_price)

    def test_multibuy_product_sets_multibuy_not_campaign(self):
        raw = self.provider.normalize_product({**REAL_MULTIBUY_PRODUCT, "_store_id": "2132"})
        self.assertEqual(raw.regular_price, 24.9)
        self.assertIsNone(raw.campaign_price)
        self.assertEqual(raw.multibuy_price, 20.0)

    def test_member_price_is_always_none(self):
        """Willys' API exposes no member price - it must stay null."""
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "2132"})
        self.assertIsNone(raw.member_price)

    def test_missing_price_is_none_not_zero(self):
        without_price = {k: v for k, v in REAL_PRODUCT.items() if k != "priceValue"}
        raw = self.provider.normalize_product({**without_price, "_store_id": "2132"})
        self.assertIsNone(raw.regular_price)

    def test_category_is_none_because_search_does_not_provide_one(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "2132"})
        self.assertIsNone(raw.category)

    def test_source_url_uses_the_product_code(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "2132"})
        self.assertIn("101017249_ST", raw.source_url)


class StoreListTest(WillysTestBase):
    def test_get_stores_maps_real_axfood_records(self):
        willys_module.urllib.request.urlopen = fake_urlopen(REAL_STORE_LIST)
        stores = self.provider.get_stores()
        self.assertEqual(len(stores), 3)
        gestrike = next(s for s in stores if s.external_store_id == "2132")
        self.assertEqual(gestrike.name, "Willys Gävle Gestrike")
        self.assertEqual(gestrike.city, "Gävle")
        self.assertEqual(gestrike.latitude, 60.6749)
        self.assertTrue(gestrike.active)

    def test_placeholder_zero_coordinates_are_stored_as_unknown(self):
        """0.0/0.0 is Axfood's 'no coordinates', not a real location."""
        willys_module.urllib.request.urlopen = fake_urlopen(REAL_STORE_LIST)
        offline = next(s for s in self.provider.get_stores() if s.external_store_id == "9999")
        self.assertIsNone(offline.latitude)
        self.assertIsNone(offline.longitude)
        self.assertFalse(offline.active)

    def test_stores_without_id_are_skipped(self):
        willys_module.urllib.request.urlopen = fake_urlopen([{"name": "Trasig"}])
        self.assertEqual(self.provider.get_stores(), [])

    def test_health_check_true_when_stores_come_back(self):
        willys_module.urllib.request.urlopen = fake_urlopen(REAL_STORE_LIST)
        self.assertTrue(self.provider.health_check())

    def test_health_check_false_when_refused(self):
        def _open(request, timeout=None):
            raise http_error(403)
        willys_module.urllib.request.urlopen = _open
        self.assertFalse(self.provider.health_check())


class ProductListingTest(WillysTestBase):
    def test_get_products_normalizes_results(self):
        willys_module.urllib.request.urlopen = fake_urlopen(search_response(REAL_PRODUCT))
        products = self.provider.get_products("2132")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].external_product_id, "101017249_ST")

    def test_pagination_is_followed(self):
        """Willys, unlike ICA, exposes real pagination - a collector must walk
        it rather than stopping at page 0."""
        pages = {
            0: search_response(REAL_PRODUCT, total_pages=2, current_page=0),
            1: search_response(REAL_CAMPAIGN_PRODUCT, total_pages=2, current_page=1),
        }
        calls = {"n": 0}

        def _open(request, timeout=None):
            url = request.full_url
            page = 1 if "page=1" in url else 0
            calls["n"] += 1
            return FakeResponse(json.dumps(pages[page]).encode("utf-8"))

        willys_module.urllib.request.urlopen = _open
        products = self.provider.get_products("2132")
        self.assertEqual(calls["n"], 2)
        self.assertEqual({p.external_product_id for p in products}, {"101017249_ST", "200000001_ST"})

    def test_duplicate_product_codes_are_returned_once(self):
        provider = WillysProvider(search_terms=["smör", "smor"])
        willys_module.urllib.request.urlopen = fake_urlopen(search_response(REAL_PRODUCT))
        products = provider.get_products("2132")
        self.assertEqual(len(products), 1)

    def test_products_without_code_are_skipped(self):
        willys_module.urllib.request.urlopen = fake_urlopen(search_response({"name": "Utan kod"}))
        self.assertEqual(self.provider.get_products("2132"), [])

    def test_empty_results_are_not_an_error(self):
        willys_module.urllib.request.urlopen = fake_urlopen(search_response())
        self.assertEqual(self.provider.get_products("2132"), [])

    def test_get_product_details_finds_the_matching_code(self):
        willys_module.urllib.request.urlopen = fake_urlopen(search_response(REAL_PRODUCT, REAL_CAMPAIGN_PRODUCT))
        raw = self.provider.get_product_details("200000001_ST", "2132")
        self.assertIsNotNone(raw)
        self.assertEqual(raw.name, "Högrev Nötkött Irland")

    def test_get_product_details_returns_none_when_not_found(self):
        willys_module.urllib.request.urlopen = fake_urlopen(search_response(REAL_PRODUCT))
        self.assertIsNone(self.provider.get_product_details("does-not-exist", "2132"))


class ErrorHandlingTest(WillysTestBase):
    def test_403_is_a_terminal_block_not_retried(self):
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            raise http_error(403)

        willys_module.urllib.request.urlopen = _open
        with self.assertRaises(WillysBlockedError):
            self.provider.get_stores()
        self.assertEqual(len(attempts), 1)

    def test_429_is_a_terminal_block_not_retried(self):
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            raise http_error(429)

        willys_module.urllib.request.urlopen = _open
        with self.assertRaises(WillysBlockedError):
            self.provider.get_stores()
        self.assertEqual(len(attempts), 1)

    def test_server_error_is_retried_then_reported(self):
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            raise http_error(500)

        willys_module.urllib.request.urlopen = _open
        with self.assertRaises(WillysRequestError):
            self.provider.get_stores()
        self.assertEqual(len(attempts), willys_module.MAX_RETRIES)

    def test_timeout_is_retried_then_reported(self):
        def _open(request, timeout=None):
            raise TimeoutError("timed out")
        willys_module.urllib.request.urlopen = _open
        with self.assertRaises(WillysRequestError):
            self.provider.get_stores()

    def test_malformed_json_is_reported(self):
        willys_module.urllib.request.urlopen = fake_urlopen(None, raw_bytes=b"<html>nope</html>")
        with self.assertRaises(WillysRequestError):
            self.provider.get_stores()

    def test_empty_body_is_treated_as_a_block(self):
        willys_module.urllib.request.urlopen = fake_urlopen(None, raw_bytes=b"")
        with self.assertRaises(WillysBlockedError):
            self.provider.get_stores()

    def test_block_preserves_already_collected_products(self):
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse(json.dumps(search_response(REAL_PRODUCT)).encode("utf-8"))
            raise http_error(429)

        provider = WillysProvider(search_terms=["smör", "mjölk"])
        willys_module.urllib.request.urlopen = _open
        with self.assertRaises(WillysBlockedError) as ctx:
            provider.get_products("2132")
        self.assertEqual(len(ctx.exception.partial_products), 1)

    def test_failed_search_term_does_not_abort_the_run(self):
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] <= willys_module.MAX_RETRIES:
                raise http_error(500)
            return FakeResponse(json.dumps(search_response(REAL_PRODUCT)).encode("utf-8"))

        provider = WillysProvider(search_terms=["trasig", "smör"])
        willys_module.urllib.request.urlopen = _open
        products = provider.get_products("2132")
        self.assertEqual(len(products), 1)


if __name__ == "__main__":
    unittest.main()
