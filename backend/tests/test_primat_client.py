import io
import json
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.pricing import primat_client  # noqa: E402


def _fake_response(payload, status=200):
    body = json.dumps(payload).encode("utf-8")
    response = io.BytesIO(body)
    response.status = status

    class _Ctx:
        def __enter__(self):
            return response

        def __exit__(self, *args):
            return False

    return _Ctx()


class RequestPathTest(unittest.TestCase):
    """Whether a call goes to the free demo endpoint or the authenticated one
    depends entirely on whether an api_key was passed - this is the switch
    "Börja med demo-API utan nyckel" / "bygg stöd för PRIMAT_API_KEY" hinges
    on, so it's worth pinning down directly."""

    @patch("urllib.request.urlopen")
    def test_search_products_uses_demo_path_without_key(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"data": []})
        primat_client.search_products("citron")
        called_url = mock_urlopen.call_args[0][0].full_url
        self.assertIn("/demo/products", called_url)
        self.assertNotIn("Authorization", mock_urlopen.call_args[0][0].headers)

    @patch("urllib.request.urlopen")
    def test_every_request_sends_a_real_user_agent(self, mock_urlopen):
        """Confirmed directly against the real API: Python's default
        urllib User-Agent ("Python-urllib/3.x") gets a hard 403 (Cloudflare
        error 1010, "browser signature blocked") from Primat, while the
        exact same request succeeds with a real User-Agent set. Every
        request must carry one - this isn't optional polish."""
        mock_urlopen.return_value = _fake_response({"data": []})
        primat_client.search_products("citron")
        self.assertEqual(mock_urlopen.call_args[0][0].headers.get("User-agent"), primat_client.USER_AGENT)

    @patch("urllib.request.urlopen")
    def test_search_products_uses_authenticated_path_with_key(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"data": []})
        primat_client.search_products("citron", api_key="primat_live_test")
        req = mock_urlopen.call_args[0][0]
        self.assertIn("/products", req.full_url)
        self.assertNotIn("/demo/", req.full_url)
        self.assertEqual(req.headers.get("Authorization"), "Bearer primat_live_test")

    @patch("urllib.request.urlopen")
    def test_resolve_stores_uses_demo_path_without_key(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"default_selection": []})
        primat_client.resolve_stores("80252")
        self.assertIn("/demo/stores/resolve", mock_urlopen.call_args[0][0].full_url)


class ErrorHandlingTest(unittest.TestCase):
    """API errors, quota limits and network failures must all surface as
    PrimatError - api_server.py's fetch_from_primat relies on this single
    exception type to know when to fall back to scraping."""

    @patch("urllib.request.urlopen")
    def test_http_error_raises_primat_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 500, "Internal Server Error", {}, io.BytesIO(b'{"error":{"message":"boom"}}')
        )
        with self.assertRaises(primat_client.PrimatError):
            primat_client.search_products("citron")

    @patch("urllib.request.urlopen")
    def test_quota_exceeded_raises_primat_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 429, "Too Many Requests", {},
            io.BytesIO(b'{"error":{"code":"daily_row_budget_exceeded","message":"quota exceeded"}}'),
        )
        with self.assertRaises(primat_client.PrimatError):
            primat_client.search_products("citron", api_key="primat_live_test")

    @patch("urllib.request.urlopen")
    def test_network_error_raises_primat_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        with self.assertRaises(primat_client.PrimatError):
            primat_client.resolve_stores("80252")

    @patch("urllib.request.urlopen")
    def test_malformed_json_raises_primat_error(self, mock_urlopen):
        response = io.BytesIO(b"not json")
        response.status = 200

        class _Ctx:
            def __enter__(self):
                return response

            def __exit__(self, *args):
                return False

        mock_urlopen.return_value = _Ctx()
        with self.assertRaises(primat_client.PrimatError):
            primat_client.search_products("citron")


class MissingProductsTest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_search_with_no_matches_returns_empty_list(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"data": []})
        self.assertEqual(primat_client.search_products("something-nonexistent"), [])

    @patch("urllib.request.urlopen")
    def test_resolve_stores_with_no_coverage_returns_empty_dict(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({"default_selection": []})
        self.assertEqual(primat_client.resolve_stores("00000"), {})


class ResolveStoresTest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_builds_chain_keyed_map_from_default_selection(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response({
            "default_selection": ["willys:2132", "coop:206403", "lidl:SE0128", "ica:1158001", "citygross:3209"]
        })
        result = primat_client.resolve_stores("80252")
        self.assertEqual(result, {
            "willys": "willys:2132", "coop": "coop:206403", "lidl": "lidl:SE0128",
            "ica": "ica:1158001", "citygross": "citygross:3209",
        })


class NearbyStoresTest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_maps_known_chains_and_skips_unsupported_ones(self, mock_urlopen):
        """Matjakt doesn't have a chain for Lidl/City Gross yet - those rows
        should be silently dropped, not raise or produce a garbage entry."""
        mock_urlopen.return_value = _fake_response({
            "stores": [
                {"chain": "willys", "store_id": "2132", "key": "willys:2132", "name": "Willys Gävle Gestrike", "city": "Gävle", "km": 0.9},
                {"chain": "lidl", "store_id": "SE0128", "key": "lidl:SE0128", "name": "Lidl Gävle Stiglund", "city": "Gävle", "km": 2.1},
                {"chain": "citygross", "store_id": "3209", "key": "citygross:3209", "name": "Gävle", "city": "Gävle", "km": 3.6},
                {"chain": "hemkop", "store_id": "8891", "key": "hemkop:8891", "name": "Hemköp Söder", "city": "Gävle", "km": 1.5},
            ]
        })
        result = primat_client.nearby_stores("80252")
        self.assertEqual(result, [
            {"kedja": "Willys", "namn": "Willys Gävle Gestrike", "ort": "Gävle", "avstandKm": 0.9, "primatKey": "willys:2132"},
            {"kedja": "Hemköp", "namn": "Hemköp Söder", "ort": "Gävle", "avstandKm": 1.5, "primatKey": "hemkop:8891"},
        ])


class ToMatjaktProductTest(unittest.TestCase):
    """The adapter that lets Primat slot in wherever a scraped product dict
    is expected (best_match, store_products, the frontend's rendering) -
    getting this field mapping wrong would silently corrupt prices."""

    def test_maps_effective_price_not_regular_when_a_campaign_applies(self):
        primat_product = {
            "name": "Citronjuice Från koncentrat", "brand": "ICA", "package": "200 ml",
            "gtin": "7318690164555", "available": True,
            "prices": {"regular": 10.3, "member": None, "offer": {"price": 7.0, "label": "2 för 14kr", "valid_until": "2026-08-30T21:59:59Z"}, "effective": 7.0},
            "urls": {"source": "https://handlaprivatkund.ica.se/stores/1004519/products/2021874"},
        }
        result = primat_client.to_matjakt_product(primat_product, "ICA", "Citronjuice")
        self.assertEqual(result["pris_kr"], 7.0)
        self.assertEqual(result["kampanj"], {"text": "2 för 14kr", "ordinariePris": 10.3, "slutdatum": "2026-08-30T21:59:59Z"})
        self.assertEqual(result["gtin"], "7318690164555")
        self.assertEqual(result["kalla"], "primat")
        self.assertEqual(result["kedja"], "ICA")
        self.assertEqual(result["marke_och_storlek"], "ICA 200 ml")

    def test_no_offer_means_no_kampanj_and_effective_equals_regular(self):
        primat_product = {
            "name": "Paprika Röd Klass 1", "brand": None, "package": "1 st", "gtin": "7311042001683",
            "available": True, "prices": {"regular": 19.9, "member": None, "offer": None, "effective": 19.9},
            "urls": {"source": "https://www.willys.se/produkt/100816306_ST"},
        }
        result = primat_client.to_matjakt_product(primat_product, "Willys", "Paprika")
        self.assertIsNone(result["kampanj"])
        self.assertEqual(result["pris_kr"], 19.9)
        self.assertEqual(result["marke_och_storlek"], "1 st")  # no brand - just the package size

    def test_missing_gtin_and_brand_dont_crash(self):
        primat_product = {
            "name": "Danskt Citronvatten", "brand": None, "package": "1000 ml", "gtin": None,
            "available": True, "prices": {"regular": 18.9, "effective": 18.9}, "urls": {},
        }
        result = primat_client.to_matjakt_product(primat_product, "ICA", "citronvatten")
        self.assertIsNone(result["gtin"])
        self.assertEqual(result["url"], "")
        self.assertEqual(result["bild"], "")  # Primat never returns images - see Open Food Facts fallback

    def test_member_price_and_multiprice_dont_affect_effective_mapping(self):
        """Member/multiprice discounts are already folded into "effective" by
        Primat - Matjakt just needs to trust that field, not recompute it."""
        primat_product = {
            "name": "Sprite", "brand": "Sprite", "package": "1500 ml", "gtin": "5000112642667",
            "available": True,
            "prices": {
                "regular": 24.95, "member": None,
                "multiprice": {"price": None, "quantity": None},
                "member_multiprice": {"price": 14.5, "quantity": 2},
                "offer": {"price": 12.5, "label": "MedMera: Medlemspris-2 Cola 25kr-2 för 25:-"},
                "effective": 12.5,
            },
            "urls": {"source": "https://www.coop.se/handla/varor/dryck/lask/sprite"},
        }
        result = primat_client.to_matjakt_product(primat_product, "Coop", "Sprite")
        self.assertEqual(result["pris_kr"], 12.5)
        self.assertEqual(result["kampanj"]["ordinariePris"], 24.95)


class FetchFromPrimatIntegrationTest(unittest.TestCase):
    """api_server.fetch_from_primat / primat_store_scope: the actual glue
    that decides when Matjakt asks Primat vs. falls back to scraping."""

    def setUp(self):
        import api_server
        self.api_server = api_server
        api_server.KV_CACHE.clear()
        # The circuit breaker is module-level global state (see
        # _trip_primat_circuit) - without resetting it, a test that trips it
        # would leak a cooldown into whichever test runs next.
        self._original_circuit = api_server._primat_circuit_open_until
        api_server._primat_circuit_open_until = 0.0

    def tearDown(self):
        self.api_server.KV_CACHE.clear()
        self.api_server._primat_circuit_open_until = self._original_circuit

    def test_unsupported_chain_skips_primat_without_calling_it(self):
        calls = []
        original = self.api_server.primat_resolve_stores
        self.api_server.primat_resolve_stores = lambda zip_code, api_key=None: calls.append(1) or {}
        try:
            # "Lidl" isn't a Matjakt chain at all - CHAIN_TO_PRIMAT has no entry for it.
            result = self.api_server.fetch_from_primat("Lidl", "citron", "80252")
        finally:
            self.api_server.primat_resolve_stores = original
        self.assertEqual(result, [])
        self.assertEqual(calls, [])

    def test_no_nearby_store_for_chain_returns_empty_without_searching(self):
        calls = []
        original_resolve, original_search = self.api_server.primat_resolve_stores, self.api_server.primat_search_products
        self.api_server.primat_resolve_stores = lambda zip_code, api_key=None: {"willys": "willys:2132"}  # no "hemkop" key
        self.api_server.primat_search_products = lambda *a, **k: calls.append(1) or []
        try:
            result = self.api_server.fetch_from_primat("Hemköp", "citron", "80252")
        finally:
            self.api_server.primat_resolve_stores, self.api_server.primat_search_products = original_resolve, original_search
        self.assertEqual(result, [])
        self.assertEqual(calls, [])

    def test_explicit_store_key_is_used_directly_without_resolving_the_zip(self):
        """Pinning a specific branch (e.g. the user clicked "Coop Tullhuset"
        in the store comparison list) must search that exact door, not
        whichever store primat_store_scope would have picked as the zip's
        default - and must skip the resolve call entirely, since the caller
        already knows exactly which store it wants."""
        resolve_calls, search_calls = [], []
        original_resolve, original_search = self.api_server.primat_resolve_stores, self.api_server.primat_search_products
        self.api_server.primat_resolve_stores = lambda zip_code, api_key=None: resolve_calls.append(1) or {"coop": "coop:206401"}
        self.api_server.primat_search_products = lambda query, stores=None, api_key=None: search_calls.append(stores) or []
        try:
            self.api_server.fetch_from_primat("Coop", "citron", "80252", store_key="coop:206414")
        finally:
            self.api_server.primat_resolve_stores, self.api_server.primat_search_products = original_resolve, original_search
        self.assertEqual(search_calls, ["coop:206414"])
        self.assertEqual(resolve_calls, [])

    def test_store_key_for_the_wrong_chain_is_ignored(self):
        """A stale pinned key left over from switching chains (e.g. still
        holding a Coop key while now searching Willys) must not silently
        scope the search to the wrong store - it should fall back to the
        zip's normal default resolution for the chain actually being
        searched, exactly as if no key had been passed at all."""
        original_resolve, original_search = self.api_server.primat_resolve_stores, self.api_server.primat_search_products
        self.api_server.primat_resolve_stores = lambda zip_code, api_key=None: {"willys": "willys:2132"}
        search_calls = []
        self.api_server.primat_search_products = lambda query, stores=None, api_key=None: search_calls.append(stores) or []
        try:
            self.api_server.fetch_from_primat("Willys", "citron", "80252", store_key="coop:206414")
        finally:
            self.api_server.primat_resolve_stores, self.api_server.primat_search_products = original_resolve, original_search
        self.assertEqual(search_calls, ["willys:2132"])

    def test_primat_error_falls_back_to_empty_list(self):
        from services.pricing import PrimatError
        original_resolve = self.api_server.primat_resolve_stores
        self.api_server.primat_resolve_stores = lambda zip_code, api_key=None: (_ for _ in ()).throw(PrimatError("down"))
        try:
            result = self.api_server.fetch_from_primat("Willys", "citron", "80252")
        finally:
            self.api_server.primat_resolve_stores = original_resolve
        self.assertEqual(result, [])

    def test_a_failure_trips_the_circuit_so_the_next_call_does_not_retry(self):
        """The actual bug found while building this: a failure that isn't
        remembered means every subsequent ingredient lookup retries the same
        failing call immediately - exactly the request burst that got a real
        key rate-limited during testing. One failure should protect every
        call for the cooldown window, not just its own zip/query."""
        from services.pricing import PrimatError
        call_count = [0]

        def _failing_resolve(zip_code, api_key=None):
            call_count[0] += 1
            raise PrimatError("down")

        original_resolve = self.api_server.primat_resolve_stores
        self.api_server.primat_resolve_stores = _failing_resolve
        try:
            self.api_server.fetch_from_primat("Willys", "citron", "80252")
            self.assertEqual(call_count[0], 1)
            # A different query, different zip - still covered by the same
            # cooldown, so this must NOT trigger a second real call.
            result = self.api_server.fetch_from_primat("Coop", "paprika", "11122")
        finally:
            self.api_server.primat_resolve_stores = original_resolve
        self.assertEqual(result, [])
        self.assertEqual(call_count[0], 1)

    def test_circuit_recovers_once_the_cooldown_has_elapsed(self):
        self.api_server._primat_circuit_open_until = time.monotonic() - 1  # already expired
        original_resolve = self.api_server.primat_resolve_stores
        calls = []
        self.api_server.primat_resolve_stores = lambda zip_code, api_key=None: calls.append(1) or {"willys": "willys:2132"}
        try:
            self.api_server.primat_store_scope("80252")
        finally:
            self.api_server.primat_resolve_stores = original_resolve
        self.assertEqual(len(calls), 1)

    def test_store_scope_is_cached_across_calls_for_the_same_zip(self):
        calls = []
        original = self.api_server.primat_resolve_stores
        self.api_server.primat_resolve_stores = lambda zip_code, api_key=None: calls.append(zip_code) or {"willys": "willys:2132"}
        try:
            self.api_server.primat_store_scope("80252")
            self.api_server.primat_store_scope("80252")
        finally:
            self.api_server.primat_resolve_stores = original
        self.assertEqual(len(calls), 1)

    def test_successful_search_is_converted_and_returned(self):
        original_resolve, original_search = self.api_server.primat_resolve_stores, self.api_server.primat_search_products
        self.api_server.primat_resolve_stores = lambda zip_code, api_key=None: {"willys": "willys:2132"}
        self.api_server.primat_search_products = lambda query, stores=None, api_key=None: [
            {"name": "Paprika Röd Klass 1", "brand": None, "package": "1 st", "gtin": "7311042001683",
             "available": True, "prices": {"regular": 19.9, "effective": 19.9}, "urls": {"source": "https://www.willys.se/x"}}
        ]
        try:
            result = self.api_server.fetch_from_primat("Willys", "Paprika", "80252")
        finally:
            self.api_server.primat_resolve_stores, self.api_server.primat_search_products = original_resolve, original_search
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["produktnamn"], "Paprika Röd Klass 1")
        self.assertEqual(result[0]["kedja"], "Willys")


if __name__ == "__main__":
    unittest.main()
