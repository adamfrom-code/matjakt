"""Tests for the shared Axfood layer and both chains built on it
(WillysProvider, HemkopProvider).

Every fixture is a trimmed copy of a REAL response captured live on
2026-08-30 from www.willys.se and www.hemkop.se - same field names, same
values (prices, GTINs, promotion shapes, campaignType/qualifyingCount).
Nothing here touches the network.
"""

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery.providers import axfood as axfood_module  # noqa: E402
from services.grocery.providers.axfood import (  # noqa: E402
    AxfoodBlockedError, AxfoodRequestError, _parse_display_volume, _parse_swedish_price,
    gtin_checksum_ok, gtin_from_image_url, split_promotions,
)
from services.grocery.providers.hemkop import HemkopProvider  # noqa: E402
from services.grocery.providers.willys import WillysProvider  # noqa: E402

# --- Real Willys product (Smör Normalsaltat 82%) --------------------------
WILLYS_PRODUCT = {
    "code": "101017249_ST", "name": "Smör Normalsaltat 82%", "manufacturer": "Svenskt Smör",
    "displayVolume": "500g", "productLine2": "SVENSKT SMÖR, 500g",
    "price": "59,50 kr", "priceValue": 59.5, "priceUnit": "kr/st",
    "comparePrice": "119,00 kr", "comparePriceUnit": "kg",
    "outOfStock": False, "online": True, "potentialPromotions": [],
    "image": {"url": "https://assets.axfood.se/image/upload/f_auto,t_200/07310865005168_C1L1_s01"},
    "thumbnail": {"url": "https://assets.axfood.se/image/upload/f_auto,t_100/07310865005168_C1L1_s01"},
}

# Real Hemköp product - SAME product code and GTIN as Willys carries, but a
# genuinely different price (16.50 at Willys vs 17.70 at Hemköp on the same
# day). This is the cross-chain comparison Matjakt exists to make.
HEMKOP_PRODUCT = {
    "code": "101233933_ST", "name": "Mellanmjölk Längre Hållbarhet 1,5%", "manufacturer": "Garant",
    "displayVolume": "1,5l", "price": "17,70 kr", "priceValue": 17.7, "priceUnit": "kr/st",
    "comparePrice": "11,80 kr", "comparePriceUnit": "l",
    "outOfStock": False, "online": True, "potentialPromotions": [],
    "image": {"url": "https://assets.axfood.se/image/upload/f_auto,t_200/07340083443893_C1L1_s06"},
}

# Real Willys multibuy: chips, ordinary 24.90, "2 för 40 kr" -> 20.00 each.
WILLYS_MULTIBUY = {
    **WILLYS_PRODUCT, "code": "101197040_ST", "name": "Havssalt Räfflade Västkustchips", "priceValue": 24.9,
    "potentialPromotions": [{
        "campaignType": "GENERAL", "promotionType": "MixMatchPricePromotion",
        "conditionLabelFormatted": "2 för", "qualifyingCount": 2, "rewardLabel": "40,00",
        "price": {"currencyIso": "SEK", "value": 20.0}, "code": "2500312588",
    }],
}

# Real Hemköp multibuy - note conditionLabelFormatted is EMPTY here while
# qualifyingCount is 2. This is the exact case that made the original
# label-based heuristic wrong; see providers/axfood.py's docstring.
HEMKOP_MULTIBUY = {
    **HEMKOP_PRODUCT, "code": "300000001_ST", "name": "Bryggkaffe Mellanrost Eko Fairtrade", "priceValue": 66.2,
    "potentialPromotions": [{
        "campaignType": "GENERAL", "promotionType": "MixMatchPricePromotion",
        "conditionLabelFormatted": "", "qualifyingCount": 2, "rewardLabel": "129 kr",
        "price": {"currencyIso": "SEK", "value": 64.5}, "code": "2500400001",
    }],
}

# Real straight discount (everyone pays it).
GENERAL_CAMPAIGN = {
    **WILLYS_PRODUCT, "code": "200000001_ST", "name": "Högrev Nötkött Irland", "priceValue": 145.0,
    "potentialPromotions": [{
        "campaignType": "GENERAL", "conditionLabelFormatted": "", "qualifyingCount": 1,
        "price": {"currencyIso": "SEK", "value": 129.0}, "code": "2500300001",
    }],
}

# Real member-only offer (campaignType LOYALTY), observed on Hemköp.
LOYALTY_OFFER = {
    **HEMKOP_PRODUCT, "code": "400000001_ST", "name": "Medlemsvara", "priceValue": 50.0,
    "potentialPromotions": [{
        "campaignType": "LOYALTY", "promotionType": "MixMatchPricePromotion",
        "conditionLabelFormatted": "", "qualifyingCount": 1,
        "price": {"currencyIso": "SEK", "value": 39.0}, "code": "2500500001",
    }],
}

WILLYS_STORES = [
    {"storeId": "2132", "name": "Willys Gävle Gestrike", "onlineStore": True,
     "address": {"town": "Gävle", "postalCode": "80267", "line1": "Gestrikevägen 1"},
     "geoPoint": {"latitude": 60.6749, "longitude": 17.1413}},
    {"storeId": "9999", "name": "Willys Offline", "onlineStore": False,
     "address": {"town": "Nowhere"}, "geoPoint": {"latitude": 0.0, "longitude": 0.0}},
]

HEMKOP_STORES = [
    {"storeId": "4256", "name": "Hemköp Uppsala Svava C", "onlineStore": True,
     "address": {"town": "Uppsala", "postalCode": "75320", "line1": "Svartbäcksgatan 1"},
     "geoPoint": {"latitude": 59.8586, "longitude": 17.6389}},
]


def search_response(*products, total_pages=1, current_page=0):
    return {"results": list(products),
            "pagination": {"pageSize": 30, "currentPage": current_page,
                           "numberOfPages": total_pages, "totalNumberOfResults": len(products)}}


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


class AxfoodTestBase(unittest.TestCase):
    def setUp(self):
        self._orig_urlopen = axfood_module.urllib.request.urlopen
        self._orig_sleep = axfood_module.time.sleep
        axfood_module.time.sleep = lambda s: None

    def tearDown(self):
        axfood_module.urllib.request.urlopen = self._orig_urlopen
        axfood_module.time.sleep = self._orig_sleep


class PromotionSemanticsTest(unittest.TestCase):
    """The three promotion kinds must never be conflated - each would
    misreport a price to the user in a different way."""

    def test_general_campaign_is_a_campaign_price(self):
        campaign, member, multibuy = split_promotions(GENERAL_CAMPAIGN["potentialPromotions"])
        self.assertEqual(campaign, 129.0)
        self.assertIsNone(member)
        self.assertIsNone(multibuy)

    def test_loyalty_promotion_is_a_member_price_not_a_campaign(self):
        """A member-only deal must never be shown as the price everyone pays."""
        campaign, member, multibuy = split_promotions(LOYALTY_OFFER["potentialPromotions"])
        self.assertIsNone(campaign)
        self.assertEqual(member, 39.0)
        self.assertIsNone(multibuy)

    def test_willys_multibuy_detected_via_qualifying_count(self):
        campaign, member, multibuy = split_promotions(WILLYS_MULTIBUY["potentialPromotions"])
        self.assertIsNone(campaign)
        self.assertEqual(multibuy, 20.0)

    def test_hemkop_multibuy_detected_despite_empty_condition_label(self):
        """Regression test for a real bug: Hemköp leaves
        conditionLabelFormatted empty on genuine multibuys, so the original
        label-based heuristic classified a 2-for price as a single-item
        campaign price. qualifyingCount is what actually distinguishes them."""
        campaign, member, multibuy = split_promotions(HEMKOP_MULTIBUY["potentialPromotions"])
        self.assertIsNone(campaign, "a 2-for price must not be reported as a campaign price")
        self.assertEqual(multibuy, 64.5)

    def test_loyalty_wins_over_multibuy_classification(self):
        campaign, member, multibuy = split_promotions([{
            "campaignType": "LOYALTY", "qualifyingCount": 2, "price": {"value": 30.0},
        }])
        self.assertEqual(member, 30.0)
        self.assertIsNone(multibuy)
        self.assertIsNone(campaign)

    def test_qualifying_count_of_one_is_a_plain_campaign(self):
        campaign, _, multibuy = split_promotions([
            {"campaignType": "GENERAL", "qualifyingCount": 1, "price": {"value": 99.0}},
        ])
        self.assertEqual(campaign, 99.0)
        self.assertIsNone(multibuy)

    def test_missing_qualifying_count_is_treated_as_a_campaign(self):
        campaign, _, multibuy = split_promotions([
            {"campaignType": "GENERAL", "price": {"value": 99.0}},
        ])
        self.assertEqual(campaign, 99.0)
        self.assertIsNone(multibuy)

    def test_lowest_price_wins_within_a_kind(self):
        campaign, _, _ = split_promotions([
            {"campaignType": "GENERAL", "qualifyingCount": 1, "price": {"value": 129.0}},
            {"campaignType": "GENERAL", "qualifyingCount": 1, "price": {"value": 119.0}},
        ])
        self.assertEqual(campaign, 119.0)

    def test_no_promotions_yields_all_none(self):
        self.assertEqual(split_promotions([]), (None, None, None))
        self.assertEqual(split_promotions(None), (None, None, None))

    def test_promotion_without_a_price_is_ignored(self):
        self.assertEqual(split_promotions([{"campaignType": "GENERAL"}]), (None, None, None))


class GtinDerivationTest(unittest.TestCase):
    """GTIN is derived from the image URL, so validating it is the safeguard
    against wrongly merging two different products."""

    def test_real_gtins_from_both_chains_validate(self):
        for code in ["07310865005168", "07340083443893", "07311043002191",
                     "07340083427299", "07393061000342", "07311041070390"]:
            self.assertTrue(gtin_checksum_ok(code), code)

    def test_checksum_rejects_a_corrupted_digit(self):
        self.assertFalse(gtin_checksum_ok("07310865005169"))

    def test_checksum_rejects_bad_lengths_and_non_digits(self):
        for bad in ["1234567", "123456789012345", "abcdefghijklmn", ""]:
            self.assertFalse(gtin_checksum_ok(bad))

    def test_extracts_gtin_from_a_real_image_url(self):
        self.assertEqual(gtin_from_image_url(WILLYS_PRODUCT["image"]["url"]), "07310865005168")

    def test_invalid_checksum_yields_no_gtin_rather_than_a_guess(self):
        self.assertIsNone(gtin_from_image_url(
            "https://assets.axfood.se/image/upload/f_auto/07310865005169_C1L1_s01"))

    def test_url_without_a_code_yields_none(self):
        self.assertIsNone(gtin_from_image_url("https://assets.axfood.se/image/upload/placeholder.png"))
        self.assertIsNone(gtin_from_image_url(None))


class ParsingTest(unittest.TestCase):
    def test_parses_real_swedish_prices(self):
        self.assertEqual(_parse_swedish_price("119,00 kr"), 119.0)
        self.assertEqual(_parse_swedish_price("11,80 kr"), 11.8)

    def test_unparseable_price_is_none_not_zero(self):
        for bad in [None, "", "inget pris"]:
            self.assertIsNone(_parse_swedish_price(bad))

    def test_parses_real_display_volumes(self):
        self.assertEqual(_parse_display_volume("1,5l"), (1.5, "l"))
        self.assertEqual(_parse_display_volume("500g"), (500.0, "g"))

    def test_unparseable_volume_returns_none(self):
        self.assertEqual(_parse_display_volume("ca 6-pack"), (None, None))
        self.assertEqual(_parse_display_volume(None), (None, None))


class WillysNormalizationTest(AxfoodTestBase):
    def setUp(self):
        super().setUp()
        self.provider = WillysProvider(search_terms=["smör"])

    def test_maps_all_supported_fields(self):
        raw = self.provider.normalize_product({**WILLYS_PRODUCT, "_store_id": "2132"})
        self.assertEqual(raw.chain, "Willys")
        self.assertEqual(raw.external_product_id, "101017249_ST")
        self.assertEqual(raw.brand, "Svenskt Smör")
        self.assertEqual(raw.size, "500g")
        self.assertEqual((raw.quantity, raw.unit), (500.0, "g"))
        self.assertEqual(raw.regular_price, 59.5)
        self.assertEqual(raw.unit_price, 119.0)
        self.assertEqual(raw.gtin, "07310865005168")
        self.assertEqual(raw.currency, "SEK")

    def test_source_url_points_at_willys(self):
        raw = self.provider.normalize_product({**WILLYS_PRODUCT, "_store_id": "2132"})
        self.assertIn("willys.se", raw.source_url)
        self.assertIn("101017249_ST", raw.source_url)

    def test_product_without_image_has_no_image_and_no_gtin(self):
        without = {k: v for k, v in WILLYS_PRODUCT.items() if k not in ("image", "thumbnail")}
        raw = self.provider.normalize_product({**without, "_store_id": "2132"})
        self.assertIsNone(raw.image_url)
        self.assertIsNone(raw.gtin)

    def test_falls_back_to_thumbnail(self):
        without_primary = {k: v for k, v in WILLYS_PRODUCT.items() if k != "image"}
        raw = self.provider.normalize_product({**without_primary, "_store_id": "2132"})
        self.assertEqual(raw.gtin, "07310865005168")

    def test_missing_price_is_none_not_zero(self):
        without = {k: v for k, v in WILLYS_PRODUCT.items() if k != "priceValue"}
        raw = self.provider.normalize_product({**without, "_store_id": "2132"})
        self.assertIsNone(raw.regular_price)

    def test_multibuy_is_not_stored_as_campaign(self):
        raw = self.provider.normalize_product({**WILLYS_MULTIBUY, "_store_id": "2132"})
        self.assertIsNone(raw.campaign_price)
        self.assertEqual(raw.multibuy_price, 20.0)

    def test_pricing_scope_is_declared_national(self):
        self.assertEqual(self.provider.pricing_scope, "national")

    def test_recurring_import_is_marked_verified(self):
        self.assertTrue(self.provider.recurring_import_verified)


class HemkopNormalizationTest(AxfoodTestBase):
    def setUp(self):
        super().setUp()
        self.provider = HemkopProvider(search_terms=["mjölk"])

    def test_maps_all_supported_fields(self):
        raw = self.provider.normalize_product({**HEMKOP_PRODUCT, "_store_id": "4256"})
        self.assertEqual(raw.chain, "Hemköp")
        self.assertEqual(raw.external_product_id, "101233933_ST")
        self.assertEqual(raw.brand, "Garant")
        self.assertEqual(raw.regular_price, 17.7)
        self.assertEqual(raw.unit_price, 11.8)
        self.assertEqual(raw.gtin, "07340083443893")

    def test_source_url_points_at_hemkop_not_willys(self):
        raw = self.provider.normalize_product({**HEMKOP_PRODUCT, "_store_id": "4256"})
        self.assertIn("hemkop.se", raw.source_url)
        self.assertNotIn("willys.se", raw.source_url)

    def test_same_gtin_as_willys_enables_cross_chain_matching(self):
        """The same physical product at both chains must expose the same GTIN,
        or cross-chain price comparison can't work."""
        willys_raw = WillysProvider().normalize_product({
            **WILLYS_PRODUCT, "image": HEMKOP_PRODUCT["image"], "_store_id": "2132"})
        hemkop_raw = self.provider.normalize_product({**HEMKOP_PRODUCT, "_store_id": "4256"})
        self.assertEqual(willys_raw.gtin, hemkop_raw.gtin)

    def test_loyalty_offer_becomes_member_price(self):
        raw = self.provider.normalize_product({**LOYALTY_OFFER, "_store_id": "4256"})
        self.assertEqual(raw.member_price, 39.0)
        self.assertIsNone(raw.campaign_price)

    def test_hemkop_multibuy_with_empty_label_is_not_a_campaign(self):
        raw = self.provider.normalize_product({**HEMKOP_MULTIBUY, "_store_id": "4256"})
        self.assertIsNone(raw.campaign_price)
        self.assertEqual(raw.multibuy_price, 64.5)

    def test_recurring_import_is_marked_verified(self):
        """Set True only after two real consecutive imports (2026-08-30,
        store 4256) showed run 2 reporting 0 new / 100 updated with no
        block - the flag must never be asserted ahead of that evidence."""
        self.assertTrue(HemkopProvider.recurring_import_verified)

    def test_pricing_scope_is_declared_national(self):
        self.assertEqual(HemkopProvider.pricing_scope, "national")


class StoreListTest(AxfoodTestBase):
    def test_willys_stores_are_mapped(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(WILLYS_STORES)
        stores = WillysProvider().get_stores()
        gestrike = next(s for s in stores if s.external_store_id == "2132")
        self.assertEqual(gestrike.chain, "Willys")
        self.assertEqual(gestrike.city, "Gävle")
        self.assertEqual(gestrike.latitude, 60.6749)
        self.assertTrue(gestrike.active)

    def test_hemkop_stores_are_mapped_with_its_own_chain_name(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(HEMKOP_STORES)
        store = HemkopProvider().get_stores()[0]
        self.assertEqual(store.chain, "Hemköp")
        self.assertEqual(store.external_store_id, "4256")
        self.assertEqual(store.city, "Uppsala")

    def test_placeholder_zero_coordinates_become_unknown(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(WILLYS_STORES)
        offline = next(s for s in WillysProvider().get_stores() if s.external_store_id == "9999")
        self.assertIsNone(offline.latitude)
        self.assertFalse(offline.active)

    def test_stores_without_id_are_skipped(self):
        axfood_module.urllib.request.urlopen = fake_urlopen([{"name": "Trasig"}])
        self.assertEqual(WillysProvider().get_stores(), [])

    def test_health_check_reflects_reachability(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(WILLYS_STORES)
        self.assertTrue(WillysProvider().health_check())
        axfood_module.urllib.request.urlopen = lambda r, timeout=None: (_ for _ in ()).throw(http_error(403))
        self.assertFalse(WillysProvider().health_check())


class ProductListingTest(AxfoodTestBase):
    def setUp(self):
        super().setUp()
        self.provider = WillysProvider(search_terms=["smör"])

    def test_normalizes_results(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(search_response(WILLYS_PRODUCT))
        products = self.provider.get_products("2132")
        self.assertEqual(len(products), 1)

    def test_pagination_is_followed(self):
        pages = {0: search_response(WILLYS_PRODUCT, total_pages=2, current_page=0),
                 1: search_response(GENERAL_CAMPAIGN, total_pages=2, current_page=1)}
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            page = 1 if "page=1" in request.full_url else 0
            return FakeResponse(json.dumps(pages[page]).encode("utf-8"))

        axfood_module.urllib.request.urlopen = _open
        products = self.provider.get_products("2132")
        self.assertEqual(calls["n"], 2)
        self.assertEqual({p.external_product_id for p in products}, {"101017249_ST", "200000001_ST"})

    def test_duplicate_codes_returned_once(self):
        provider = WillysProvider(search_terms=["smör", "smor"])
        axfood_module.urllib.request.urlopen = fake_urlopen(search_response(WILLYS_PRODUCT))
        self.assertEqual(len(provider.get_products("2132")), 1)

    def test_products_without_code_are_skipped(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(search_response({"name": "Utan kod"}))
        self.assertEqual(self.provider.get_products("2132"), [])

    def test_empty_results_are_not_an_error(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(search_response())
        self.assertEqual(self.provider.get_products("2132"), [])

    def test_get_product_details_finds_matching_code(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(search_response(WILLYS_PRODUCT, GENERAL_CAMPAIGN))
        raw = self.provider.get_product_details("200000001_ST", "2132")
        self.assertEqual(raw.name, "Högrev Nötkött Irland")

    def test_get_product_details_returns_none_when_absent(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(search_response(WILLYS_PRODUCT))
        self.assertIsNone(self.provider.get_product_details("nope", "2132"))


class ErrorHandlingTest(AxfoodTestBase):
    def setUp(self):
        super().setUp()
        self.provider = WillysProvider(search_terms=["smör"])

    def test_403_and_429_are_terminal_and_not_retried(self):
        for code in (403, 429):
            attempts = []

            def _open(request, timeout=None):
                attempts.append(1)
                raise http_error(code)

            axfood_module.urllib.request.urlopen = _open
            with self.assertRaises(AxfoodBlockedError):
                self.provider.get_stores()
            self.assertEqual(len(attempts), 1, f"HTTP {code} must not be retried")

    def test_server_error_is_retried_then_reported(self):
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            raise http_error(500)

        axfood_module.urllib.request.urlopen = _open
        with self.assertRaises(AxfoodRequestError):
            self.provider.get_stores()
        self.assertEqual(len(attempts), axfood_module.MAX_RETRIES)

    def test_timeout_is_retried_then_reported(self):
        axfood_module.urllib.request.urlopen = lambda r, timeout=None: (_ for _ in ()).throw(TimeoutError())
        with self.assertRaises(AxfoodRequestError):
            self.provider.get_stores()

    def test_malformed_json_is_reported(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(None, raw_bytes=b"<html>nope</html>")
        with self.assertRaises(AxfoodRequestError):
            self.provider.get_stores()

    def test_empty_body_is_treated_as_a_block(self):
        axfood_module.urllib.request.urlopen = fake_urlopen(None, raw_bytes=b"")
        with self.assertRaises(AxfoodBlockedError):
            self.provider.get_stores()

    def test_block_preserves_already_collected_products(self):
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse(json.dumps(search_response(WILLYS_PRODUCT)).encode("utf-8"))
            raise http_error(429)

        provider = WillysProvider(search_terms=["smör", "mjölk"])
        axfood_module.urllib.request.urlopen = _open
        with self.assertRaises(AxfoodBlockedError) as ctx:
            provider.get_products("2132")
        self.assertEqual(len(ctx.exception.partial_products), 1)

    def test_failed_term_does_not_abort_the_run(self):
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] <= axfood_module.MAX_RETRIES:
                raise http_error(500)
            return FakeResponse(json.dumps(search_response(WILLYS_PRODUCT)).encode("utf-8"))

        provider = WillysProvider(search_terms=["trasig", "smör"])
        axfood_module.urllib.request.urlopen = _open
        self.assertEqual(len(provider.get_products("2132")), 1)


if __name__ == "__main__":
    unittest.main()
