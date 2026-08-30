"""Tests for IcaProvider (FAS B).

Every fixture below is a trimmed copy of a REAL response captured live from
ICA on 2026-08-30 (Maxi ICA Stormarknad Gävle, account id 1003987) - see the
module docstring in services/grocery/providers/ica.py for the full
investigation. Field names/shapes are therefore not invented; the only
edits are dropping bulk (srcset lists, unrelated products) and constructing
the deliberately-degenerate variants (no image, no price, malformed) the
provider has to survive.

The network is never touched here: urlopen is replaced per test. The real
end-to-end import against live ICA is a separate, manual collector run.
"""

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery.providers import ica as ica_module  # noqa: E402
from services.grocery.providers.ica import IcaBlockedError, IcaProvider, IcaRequestError, _parse_pack_size, _to_float  # noqa: E402


# --- Real captured shapes -------------------------------------------------

REAL_PRODUCT = {
    "productId": "f4ec81a4-4fff-4696-92dc-4a3e7bf06c31",
    "retailerProductId": "2052770",
    "type": "REGULAR",
    "name": "Mellanmjölk 1,5% Ekologisk 1,5l KRAV ICA I love eco",
    "brand": "ICA I love eco",
    "packSizeDescription": "1.5L",
    "countryOfOrigin": "Sverige",
    "price": {"amount": "19.16", "currency": "SEK"},
    "unitPrice": {"price": {"amount": "12.77", "currency": "SEK"}, "unit": "fop.price.per.litre", "unitName": "PER_LITRE"},
    "available": True,
    "image": {
        "src": "https://handlaprivatkund.ica.se/images-v3/bf7a00ca/000b7f1c/300x300.jpg",
        "description": "Mellanmjölk 1,5% Ekologisk 1,5l KRAV ICA I love eco",
        "imageId": "000b7f1c-4ea9-401b-9a9b-44710f62e5dc",
    },
    "categoryPath": ["Mejeri & Ost", "Mjölk", "Mellanmjölk", "Mellanmjölk, laktos"],
    "alcohol": False,
    "isNew": False,
}

REAL_STORE_LOOKUP = {
    "combinedHomePickupDelivery": None,
    "forHomeDelivery": [
        {
            "id": "10800", "storeOwnerId": "35655", "name": "Maxi ICA Stormarknad Gävle",
            "city": "Gävle", "street": "Hemlingby Köpcentrum", "zipCode": "80293",
            "latitude": 60.64671, "longitude": 17.14747, "accountId": "1003987", "enable": "1",
        },
        {
            "id": "00761", "storeOwnerId": "35633", "name": "ICA Nära Bomhus",
            "city": "Gävle", "street": "Hövdingavägen 2", "zipCode": "80432",
            "latitude": 60.66555, "longitude": 17.22808, "accountId": "1003587", "enable": "1",
        },
    ],
}


def search_response(*products):
    """The real search envelope: productGroups[].decoratedProducts[]."""
    return {
        "productGroups": [{"type": "personalized", "decoratedProducts": list(products)}],
        "metadata": {}, "additionalPageInfo": {}, "missedPromotions": [],
    }


class FakeHeaders(dict):
    """urllib's response.headers is case-insensitive; only .get() is used."""

    def get(self, key, default=None):
        for existing, value in self.items():
            if existing.lower() == key.lower():
                return value
        return default


class FakeResponse(io.BytesIO):
    """Stands in for what urlopen() returns - the provider reads .headers,
    .status and .read(), and uses it as a context manager."""

    def __init__(self, body=b"", *, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = FakeHeaders(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_urlopen(payload, *, raw_bytes=None, status=200, headers=None):
    def _open(request, timeout=None):
        body = raw_bytes if raw_bytes is not None else json.dumps(payload).encode("utf-8")
        return FakeResponse(body, status=status, headers=headers)
    return _open


def raising_urlopen(error):
    def _open(request, timeout=None):
        raise error
    return _open


def http_error(code):
    # fp must be a real file object, not None: HTTPError keeps it as the
    # response body, and Python's own traceback machinery touches it while
    # formatting a chained exception (a None fp raises KeyError: 'file' from
    # deep inside tempfile).
    return urllib.error.HTTPError("https://example.test", code, "blocked", {}, io.BytesIO(b""))


class IcaProviderTestBase(unittest.TestCase):
    def setUp(self):
        self.provider = IcaProvider(zip_code="80293", search_terms=["mjölk"])
        self._original_urlopen = ica_module.urllib.request.urlopen
        self._original_sleep = ica_module.time.sleep
        # Retry backoff and the polite inter-request delay both sleep for real
        # seconds - pointless in tests, and it would make the retry cases take
        # ~12s each.
        ica_module.time.sleep = lambda seconds: None

    def tearDown(self):
        ica_module.urllib.request.urlopen = self._original_urlopen
        ica_module.time.sleep = self._original_sleep


class NormalizationTest(IcaProviderTestBase):
    def test_normal_product_maps_every_field_we_claim_to_support(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "1003987", "_store_name": "Maxi ICA Stormarknad Gävle"})
        self.assertEqual(raw.chain, "ICA")
        self.assertEqual(raw.external_product_id, "2052770")
        self.assertEqual(raw.name, "Mellanmjölk 1,5% Ekologisk 1,5l KRAV ICA I love eco")
        self.assertEqual(raw.brand, "ICA I love eco")
        self.assertEqual(raw.size, "1.5L")
        self.assertEqual(raw.quantity, 1.5)
        self.assertEqual(raw.unit, "L")
        self.assertEqual(raw.category, "Mellanmjölk, laktos")  # most specific breadcrumb
        self.assertEqual(raw.store_id, "1003987")
        self.assertEqual(raw.currency, "SEK")
        self.assertIsNotNone(raw.fetched_at)

    def test_regular_and_unit_price_are_parsed_as_numbers(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "1003987"})
        self.assertEqual(raw.regular_price, 19.16)
        self.assertEqual(raw.unit_price, 12.77)
        self.assertIsInstance(raw.regular_price, float)

    def test_product_with_image_keeps_the_real_ica_url(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "1003987"})
        self.assertEqual(raw.image_url, "https://handlaprivatkund.ica.se/images-v3/bf7a00ca/000b7f1c/300x300.jpg")

    def test_product_without_image_yields_none_not_a_crash(self):
        without_image = {k: v for k, v in REAL_PRODUCT.items() if k != "image"}
        raw = self.provider.normalize_product({**without_image, "_store_id": "1003987"})
        self.assertIsNone(raw.image_url)

    def test_product_with_empty_image_object_yields_none(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "image": {}, "_store_id": "1003987"})
        self.assertIsNone(raw.image_url)

    def test_gtin_and_ean_are_always_none_for_ica(self):
        """ICA's public API exposes no GTIN/EAN (verified live - see the
        provider's module docstring). The spec is explicit that a missing
        GTIN must stay null and never be fabricated, so this asserts the
        provider does exactly that even when the payload happens to carry
        GTIN-looking keys."""
        raw = self.provider.normalize_product({**REAL_PRODUCT, "gtin": "7310865004703", "ean": "7310865004703", "_store_id": "1003987"})
        self.assertIsNone(raw.gtin)
        self.assertIsNone(raw.ean)

    def test_missing_price_yields_none_not_zero(self):
        """A missing price must never become a spendable-looking 0 - the same
        rule the rest of Matjakt already enforces for live prices."""
        without_price = {k: v for k, v in REAL_PRODUCT.items() if k != "price"}
        raw = self.provider.normalize_product({**without_price, "_store_id": "1003987"})
        self.assertIsNone(raw.regular_price)
        self.assertNotEqual(raw.regular_price, 0)

    def test_missing_unit_price_yields_none(self):
        without_unit = {k: v for k, v in REAL_PRODUCT.items() if k != "unitPrice"}
        raw = self.provider.normalize_product({**without_unit, "_store_id": "1003987"})
        self.assertIsNone(raw.unit_price)

    def test_campaign_and_member_price_default_to_none_on_real_ica_payloads(self):
        """No campaign/member price was ever observed populated during the
        live investigation - the fields are read defensively, so on a real
        payload they must come back None rather than fabricated."""
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "1003987"})
        self.assertIsNone(raw.campaign_price)
        self.assertIsNone(raw.member_price)
        self.assertIsNone(raw.multibuy_price)

    def test_campaign_price_is_picked_up_when_present_as_object(self):
        """Defensive path: if ICA ever does expose a campaign price in this
        shape, it must flow through instead of being silently dropped."""
        raw = self.provider.normalize_product({**REAL_PRODUCT, "campaignPrice": {"amount": "15.90", "currency": "SEK"}, "_store_id": "1003987"})
        self.assertEqual(raw.campaign_price, 15.90)

    def test_campaign_price_is_picked_up_when_present_as_scalar(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "campaignPrice": "15.90", "_store_id": "1003987"})
        self.assertEqual(raw.campaign_price, 15.90)

    def test_member_price_is_picked_up_when_present(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "memberPrice": {"amount": "14.50"}, "_store_id": "1003987"})
        self.assertEqual(raw.member_price, 14.50)

    def test_source_url_uses_the_stable_retailer_product_id(self):
        raw = self.provider.normalize_product({**REAL_PRODUCT, "_store_id": "1003987"})
        self.assertIn("1003987", raw.source_url)
        self.assertIn("2052770", raw.source_url)

    def test_missing_category_path_yields_none(self):
        without_category = {k: v for k, v in REAL_PRODUCT.items() if k != "categoryPath"}
        raw = self.provider.normalize_product({**without_category, "_store_id": "1003987"})
        self.assertIsNone(raw.category)

    def test_falls_back_to_product_id_when_retailer_id_missing(self):
        without_retailer_id = {k: v for k, v in REAL_PRODUCT.items() if k != "retailerProductId"}
        raw = self.provider.normalize_product({**without_retailer_id, "_store_id": "1003987"})
        self.assertEqual(raw.external_product_id, "f4ec81a4-4fff-4696-92dc-4a3e7bf06c31")


class PackSizeParsingTest(unittest.TestCase):
    def test_parses_real_ica_pack_size_formats(self):
        self.assertEqual(_parse_pack_size("1.5L"), (1.5, "L"))
        self.assertEqual(_parse_pack_size("0.45kg"), (0.45, "kg"))
        self.assertEqual(_parse_pack_size("500 g"), (500.0, "g"))
        self.assertEqual(_parse_pack_size("1,5L"), (1.5, "L"))

    def test_unparseable_pack_size_returns_none_rather_than_guessing(self):
        self.assertEqual(_parse_pack_size(None), (None, None))
        self.assertEqual(_parse_pack_size(""), (None, None))
        self.assertEqual(_parse_pack_size("ca 6-pack"), (None, None))

    def test_to_float_never_turns_junk_into_zero(self):
        self.assertIsNone(_to_float(None))
        self.assertIsNone(_to_float(""))
        self.assertIsNone(_to_float("inte ett tal"))
        self.assertEqual(_to_float("19.16"), 19.16)


class StoreLookupTest(IcaProviderTestBase):
    def test_get_stores_uses_account_id_as_external_store_id(self):
        """accountId (1003987), not id (10800), is what every product endpoint
        expects in its path - verified live. Getting this wrong makes every
        later product call 404, so it's asserted explicitly."""
        ica_module.urllib.request.urlopen = fake_urlopen(REAL_STORE_LOOKUP)
        stores = self.provider.get_stores()
        self.assertEqual(len(stores), 2)
        maxi = next(s for s in stores if s.name == "Maxi ICA Stormarknad Gävle")
        self.assertEqual(maxi.external_store_id, "1003987")
        self.assertEqual(maxi.chain, "ICA")
        self.assertEqual(maxi.city, "Gävle")
        self.assertEqual(maxi.latitude, 60.64671)

    def test_stores_without_account_id_are_skipped(self):
        ica_module.urllib.request.urlopen = fake_urlopen({"forHomeDelivery": [{"name": "Trasig butik"}]})
        self.assertEqual(self.provider.get_stores(), [])

    def test_health_check_true_when_stores_come_back(self):
        ica_module.urllib.request.urlopen = fake_urlopen(REAL_STORE_LOOKUP)
        self.assertTrue(self.provider.health_check())

    def test_health_check_false_when_source_is_blocked(self):
        ica_module.urllib.request.urlopen = raising_urlopen(http_error(403))
        self.assertFalse(self.provider.health_check())


class ErrorHandlingTest(IcaProviderTestBase):
    def test_403_block_is_reported_immediately_without_retrying(self):
        """Per spec section 8: a block is a stop-and-report condition. Retrying
        it would just be hammering a source that already said no."""
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            raise http_error(403)

        ica_module.urllib.request.urlopen = _open
        with self.assertRaises(IcaRequestError) as ctx:
            self.provider.get_stores()
        self.assertEqual(len(attempts), 1, "a 403 must not be retried")
        self.assertIn("403", str(ctx.exception))

    def test_429_rate_limit_is_reported_immediately_without_retrying(self):
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            raise http_error(429)

        ica_module.urllib.request.urlopen = _open
        with self.assertRaises(IcaRequestError):
            self.provider.get_stores()
        self.assertEqual(len(attempts), 1, "a 429 must not be retried")

    def test_server_error_is_retried_then_reported(self):
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            raise http_error(500)

        ica_module.urllib.request.urlopen = _open
        with self.assertRaises(IcaRequestError):
            self.provider.get_stores()
        self.assertEqual(len(attempts), ica_module.MAX_RETRIES)

    def test_timeout_is_retried_then_reported(self):
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            raise TimeoutError("timed out")

        ica_module.urllib.request.urlopen = _open
        with self.assertRaises(IcaRequestError):
            self.provider.get_stores()
        self.assertEqual(len(attempts), ica_module.MAX_RETRIES)

    def test_malformed_json_is_retried_then_reported(self):
        ica_module.urllib.request.urlopen = fake_urlopen(None, raw_bytes=b"<html>inte json</html>")
        with self.assertRaises(IcaRequestError):
            self.provider.get_stores()

    def test_transient_failure_then_success_recovers(self):
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise http_error(500)
            return FakeResponse(json.dumps(REAL_STORE_LOOKUP).encode("utf-8"))

        ica_module.urllib.request.urlopen = _open
        stores = self.provider.get_stores()
        self.assertEqual(len(stores), 2)
        self.assertEqual(calls["n"], 2)

    def test_failed_search_term_does_not_abort_the_whole_product_run(self):
        """One bad search term must cost us that term's products, not the run."""
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] <= ica_module.MAX_RETRIES:  # first term fails all its attempts
                raise http_error(500)
            return FakeResponse(json.dumps(search_response(REAL_PRODUCT)).encode("utf-8"))

        provider = IcaProvider(zip_code="80293", search_terms=["trasig", "mjölk"])
        ica_module.urllib.request.urlopen = _open
        products = provider.get_products("1003987")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].external_product_id, "2052770")

    def test_get_product_details_returns_none_on_failure_instead_of_raising(self):
        ica_module.urllib.request.urlopen = raising_urlopen(http_error(403))
        self.assertIsNone(self.provider.get_product_details("2052770", "1003987"))


class WafChallengeTest(IcaProviderTestBase):
    """ICA sits behind AWS WAF. Observed live after a full collector run: it
    stops returning data and answers HTTP 202, empty body, header
    `x-amzn-waf-action: challenge`. These tests pin the two things that
    matter: we recognise it as a refusal (not as malformed JSON), and we
    stop rather than keep asking."""

    WAF_HEADERS = {"x-amzn-waf-action": "challenge", "Content-Type": "text/html; charset=UTF-8"}

    def test_waf_challenge_is_recognised_as_a_block_not_bad_json(self):
        ica_module.urllib.request.urlopen = fake_urlopen(None, raw_bytes=b"", status=202, headers=self.WAF_HEADERS)
        with self.assertRaises(IcaBlockedError) as ctx:
            self.provider.get_stores()
        self.assertIn("waf", str(ctx.exception).lower())

    def test_waf_challenge_is_not_retried(self):
        """Retrying a challenge is just hammering a source that said no."""
        attempts = []

        def _open(request, timeout=None):
            attempts.append(1)
            return FakeResponse(b"", status=202, headers=self.WAF_HEADERS)

        ica_module.urllib.request.urlopen = _open
        with self.assertRaises(IcaBlockedError):
            self.provider.get_stores()
        self.assertEqual(len(attempts), 1)

    def test_empty_body_without_waf_header_is_also_treated_as_a_block(self):
        ica_module.urllib.request.urlopen = fake_urlopen(None, raw_bytes=b"   ", status=202)
        with self.assertRaises(IcaBlockedError):
            self.provider.get_stores()

    def test_block_stops_the_run_instead_of_walking_every_search_term(self):
        """The bug this pins: before it was fixed, a WAF challenge looked like
        malformed JSON, so a 14-term run made 14 x 3 = 42 requests against a
        WAF that had already refused the very first one."""
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            return FakeResponse(b"", status=202, headers=self.WAF_HEADERS)

        provider = IcaProvider(zip_code="80293", search_terms=["a", "b", "c", "d", "e"])
        ica_module.urllib.request.urlopen = _open
        with self.assertRaises(IcaBlockedError):
            provider.get_products("1003987")
        self.assertEqual(calls["n"], 1, "must stop at the first refusal, not try every term")

    def test_block_preserves_products_collected_before_it_hit(self):
        """Real data already fetched must survive the block - a partial import
        is worth keeping, and the collector persists exactly this list."""
        calls = {"n": 0}

        def _open(request, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse(json.dumps(search_response(REAL_PRODUCT)).encode("utf-8"))
            return FakeResponse(b"", status=202, headers=self.WAF_HEADERS)

        provider = IcaProvider(zip_code="80293", search_terms=["mjölk", "smör"])
        ica_module.urllib.request.urlopen = _open
        with self.assertRaises(IcaBlockedError) as ctx:
            provider.get_products("1003987")
        self.assertEqual(len(ctx.exception.partial_products), 1)
        self.assertEqual(ctx.exception.partial_products[0].external_product_id, "2052770")

    def test_403_and_429_are_blocked_errors_too(self):
        for code in (403, 429):
            ica_module.urllib.request.urlopen = raising_urlopen(http_error(code))
            with self.assertRaises(IcaBlockedError):
                self.provider.get_stores()


class ProductListingTest(IcaProviderTestBase):
    def test_get_products_normalizes_every_result(self):
        ica_module.urllib.request.urlopen = fake_urlopen(search_response(REAL_PRODUCT))
        products = self.provider.get_products("1003987")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].name, REAL_PRODUCT["name"])
        self.assertEqual(products[0].store_id, "1003987")

    def test_duplicate_external_product_id_is_returned_only_once(self):
        """The same product legitimately appears under several search terms
        (and in both the 'featured' and 'personalized' groups of one
        response) - it must be deduplicated on retailerProductId, or a
        100-product import would be mostly repeats."""
        duplicate_across_groups = {
            "productGroups": [
                {"type": "featured", "decoratedProducts": [REAL_PRODUCT]},
                {"type": "personalized", "decoratedProducts": [REAL_PRODUCT, {**REAL_PRODUCT, "retailerProductId": "9999", "name": "Annan produkt"}]},
            ]
        }
        provider = IcaProvider(zip_code="80293", search_terms=["mjölk", "mellanmjölk"])
        ica_module.urllib.request.urlopen = fake_urlopen(duplicate_across_groups)
        products = provider.get_products("1003987")
        self.assertEqual(len(products), 2)
        self.assertEqual({p.external_product_id for p in products}, {"2052770", "9999"})

    def test_products_without_any_id_are_skipped(self):
        nameless = {"name": "Produkt utan id", "price": {"amount": "10.00"}}
        ica_module.urllib.request.urlopen = fake_urlopen(search_response(nameless))
        self.assertEqual(self.provider.get_products("1003987"), [])

    def test_empty_result_set_is_not_an_error(self):
        ica_module.urllib.request.urlopen = fake_urlopen({"productGroups": []})
        self.assertEqual(self.provider.get_products("1003987"), [])

    def test_get_product_details_enriches_with_detailed_description(self):
        detail_payload = {
            "product": REAL_PRODUCT,
            "bopData": {
                "detailedDescription": "ICA I love eco ekologisk mellanmjölk har lite längre hållbarhet.",
                "fields": [{"title": "brand", "content": "ICA I love eco"}],
                "breadcrumbs": [],
            },
            "bopPromotions": [],
        }
        ica_module.urllib.request.urlopen = fake_urlopen(detail_payload)
        raw = self.provider.get_product_details("2052770", "1003987")
        self.assertIsNotNone(raw)
        self.assertEqual(raw.external_product_id, "2052770")
        self.assertIn("ekologisk mellanmjölk", raw.description)

    def test_get_product_details_returns_none_when_product_missing_from_payload(self):
        ica_module.urllib.request.urlopen = fake_urlopen({"bopData": {}, "bopPromotions": []})
        self.assertIsNone(self.provider.get_product_details("2052770", "1003987"))


if __name__ == "__main__":
    unittest.main()
