import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402
from api_server import clean_text, parse_price, parse_willys_price  # noqa: E402
from services.accounts import AccountStore  # noqa: E402


class ApiHelpersTest(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(clean_text("  ekologisk\n mjölk "), "ekologisk mjölk")

    def test_parse_price(self):
        self.assertEqual(parse_price("Pris 18,90 kr"), 18.9)
        self.assertIsNone(parse_price("pris saknas"))

    def test_parse_willys_price(self):
        self.assertEqual(parse_willys_price("24 95"), 24.95)

    def test_parse_kronor_ore_text(self):
        self.assertEqual(api_server.parse_kronor_ore_text("Ordinarie pris 74 kronor och 65 öre styck"), 74.65)
        self.assertEqual(api_server.parse_kronor_ore_text("Ordinarie pris 20 kronor styck"), 20)
        self.assertIsNone(api_server.parse_kronor_ore_text("inget pris här"))

    def test_extract_campaign_coop_reads_the_aria_label(self):
        aria = "Bryggkaffe Mellanrost, Arvid Nordquist, 500 g, Erbjudande 2 för 119 kronor, Erbjudande jämförpris 119 kronor per kilo, Ordinarie pris 74 kronor och 65 öre styck"
        campaign = api_server.extract_campaign("Coop", "irrelevant card text", aria)
        self.assertEqual(campaign["text"], "Erbjudande 2 för 119 kronor")
        self.assertEqual(campaign["ordinariePris"], 74.65)

    def test_extract_campaign_coop_none_without_erbjudande(self):
        aria = "Mjölk, Arla, 1 l, Pris 16 kronor och 27 öre styck"
        self.assertIsNone(api_server.extract_campaign("Coop", "text", aria))

    def test_extract_campaign_hemkop_reads_the_badge_text(self):
        campaign = api_server.extract_campaign("Hemköp", "2 för 129 kr\nGäller endast online\nBryggkaffe Mellanrost Eko", "")
        self.assertEqual(campaign["text"], "2 för 129 kr")

    def test_extract_campaign_none_for_willys_and_ica(self):
        self.assertIsNone(api_server.extract_campaign("Willys", "2 för 129 kr", ""))
        self.assertIsNone(api_server.extract_campaign("ICA", "2 för 129 kr", ""))


class LoadDotenvTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._sentinel_key = "MATJAKT_TEST_DOTENV_VAR"
        os.environ.pop(self._sentinel_key, None)

    def tearDown(self):
        os.environ.pop(self._sentinel_key, None)
        self._tmpdir.cleanup()

    def test_fills_unset_variables_from_file(self):
        env_path = Path(self._tmpdir.name) / ".env"
        env_path.write_text(f"# comment\n{self._sentinel_key}=from-file\n", encoding="utf-8")
        api_server.load_dotenv(env_path)
        self.assertEqual(os.environ[self._sentinel_key], "from-file")

    def test_does_not_override_variables_already_set(self):
        os.environ[self._sentinel_key] = "from-shell"
        env_path = Path(self._tmpdir.name) / ".env"
        env_path.write_text(f"{self._sentinel_key}=from-file\n", encoding="utf-8")
        api_server.load_dotenv(env_path)
        self.assertEqual(os.environ[self._sentinel_key], "from-shell")

    def test_missing_file_is_a_noop(self):
        api_server.load_dotenv(Path(self._tmpdir.name) / "does-not-exist.env")
        self.assertNotIn(self._sentinel_key, os.environ)


class _FakeBrowser:
    def new_page(self, locale=None):
        return object()

    def close(self):
        pass


class _FakeChromium:
    def launch(self, headless=True):
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()


class _FakeSyncPlaywrightCtx:
    def __enter__(self):
        return _FakePlaywright()

    def __exit__(self, *args):
        return False


def _fake_sync_playwright():
    return _FakeSyncPlaywrightCtx()


class ApiServerHttpTest(unittest.TestCase):
    """HTTP-level tests. Scraping itself is stubbed out (via _fake_sync_playwright /
    api_server.parse_products) so these don't need Chromium installed."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self._original_code = api_server.PREMIUM_CODE
        api_server.PREMIUM_CODE = "hemlig-kod"

    def tearDown(self):
        api_server.PREMIUM_CODE = self._original_code

    def get(self, path, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            body = response.read()
            return response.status, json.loads(body) if body else None
        finally:
            conn.close()

    def post(self, path, payload=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            body = json.dumps(payload or {}).encode("utf-8")
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            response_body = response.read()
            return response.status, json.loads(response_body) if response_body else None
        finally:
            conn.close()

    def _premium_token(self):
        email = f"user-{uuid.uuid4().hex}@example.com"
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        token = payload["token"]
        self.post("/api/auth/redeem", {"code": "hemlig-kod"}, token=token)
        return token

    def test_health(self):
        status, payload = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("Willys", payload["stores"])

    def test_static_files_are_never_heuristically_cached(self):
        # Same connection reused for both requests (HTTP/1.1 keep-alive) so this
        # also proves the "_json_response" flag doesn't leak across requests on
        # one handler instance - a static request must not inherit the header
        # behavior of an earlier JSON request, or vice versa.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/api/health")
            first = conn.getresponse()
            self.assertEqual(json.loads(first.read())["ok"], True)

            conn.request("GET", "/src/api/config.js")
            second = conn.getresponse()
            second.read()
            self.assertEqual(second.status, 200)
            self.assertEqual(second.getheader("Cache-Control"), "no-cache")
        finally:
            conn.close()

    def test_products_rejects_invalid_zip(self):
        status, payload = self.get("/api/products?butik=Willys&q=pasta&zip=abc")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_products_rejects_short_query(self):
        status, _ = self.get("/api/products?butik=Willys&q=a")
        self.assertEqual(status, 400)

    def test_recipes_search_rejects_short_query(self):
        status, _ = self.get("/api/v1/recipes/search?q=a")
        self.assertEqual(status, 400)

    def test_unknown_api_route_is_404(self):
        status, payload = self.get("/api/does-not-exist")
        self.assertEqual(status, 404)
        self.assertIn("error", payload)

    def test_products_cache_hit_skips_scraping(self):
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        calls = []
        api_server.sync_playwright = _fake_sync_playwright
        api_server.parse_products = lambda page, chain, query: calls.append(1) or [{"produktnamn": "Fräsch scrape"}]
        try:
            key = ("Willys", "kaffe", api_server.DEFAULT_ZIP)
            api_server.CACHE[key] = ([{"produktnamn": "Cachad produkt"}], time.monotonic())
            status, payload = self.get("/api/products?butik=Willys&q=kaffe")
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"][0]["produktnamn"], "Cachad produkt")
            self.assertEqual(len(calls), 0)
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            api_server.CACHE.clear()

    def test_products_cache_expires_after_ttl(self):
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        calls = []
        api_server.sync_playwright = _fake_sync_playwright
        api_server.parse_products = lambda page, chain, query: calls.append(1) or [{"produktnamn": "Fräsch scrape"}]
        try:
            key = ("Willys", "te", api_server.DEFAULT_ZIP)
            stale_timestamp = time.monotonic() - api_server.CACHE_TTL_SECONDS - 1
            api_server.CACHE[key] = ([{"produktnamn": "Gammal produkt"}], stale_timestamp)
            status, payload = self.get("/api/products?butik=Willys&q=te")
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"][0]["produktnamn"], "Fräsch scrape")
            self.assertEqual(len(calls), 1)
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            api_server.CACHE.clear()

    def test_post_with_malformed_body_encoding_returns_400_not_crash(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", "/api/products/batch", body=b'{"butik": "Willys", "varor": ["L\xf6k"]}', headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 400)
        finally:
            conn.close()

    def test_recipes_by_pantry_rejects_empty_items(self):
        status, payload = self.get("/api/v1/recipes/by-pantry?items=")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_recipes_by_pantry_returns_matches_and_caches(self):
        original = api_server.RECIPE_SERVICE.search_by_pantry
        calls = []

        class FakeRecipe:
            def to_dict(self):
                return {"id": "themealdb:1", "title": "Test"}

        api_server.RECIPE_SERVICE.search_by_pantry = lambda items: calls.append(items) or [(FakeRecipe(), ["Lök"])]
        try:
            status, payload = self.get(f"/api/v1/recipes/by-pantry?items={urllib.parse.quote('Lök,Pasta')}")
            self.assertEqual(status, 200)
            self.assertEqual(payload["recipes"][0]["matchedIngredients"], ["Lök"])
            status2, payload2 = self.get(f"/api/v1/recipes/by-pantry?items={urllib.parse.quote('Pasta,Lök')}")
            self.assertEqual(status2, 200)
            self.assertEqual(payload2["recipes"], payload["recipes"])
            self.assertEqual(len(calls), 1, "second request with the same ingredient set (different order) should hit the cache")
        finally:
            api_server.RECIPE_SERVICE.search_by_pantry = original
            api_server.PANTRY_RECIPE_CACHE.clear()

    def test_geocode_rejects_invalid_zip(self):
        status, payload = self.get("/api/geocode?zip=abc")
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_geocode_returns_place_and_caches(self):
        original = api_server.geocode_postcode
        calls = []
        api_server.geocode_postcode = lambda zip_code: calls.append(zip_code) or {"ort": "Göteborg", "lat": 57.7, "lon": 11.97}
        try:
            status, payload = self.get("/api/geocode?zip=41118")
            self.assertEqual(status, 200)
            self.assertEqual(payload["ort"], "Göteborg")
            self.assertEqual(len(calls), 1)
        finally:
            api_server.geocode_postcode = original

    def test_geocode_returns_404_for_unknown_postcode(self):
        original = api_server.geocode_postcode
        api_server.geocode_postcode = lambda zip_code: None
        try:
            status, payload = self.get("/api/geocode?zip=99999")
            self.assertEqual(status, 404)
        finally:
            api_server.geocode_postcode = original

    def test_campaigns_rejects_missing_premium(self):
        status, payload = self.get("/api/campaigns?butik=Coop&zip=11122")
        self.assertEqual(status, 403)
        self.assertIn("error", payload)

    def test_campaigns_rejects_unsupported_chain(self):
        status, payload = self.get("/api/campaigns?butik=Willys&zip=11122", token=self._premium_token())
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_campaigns_returns_only_ingredients_on_offer(self):
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        api_server.sync_playwright = _fake_sync_playwright
        by_query = {
            "kycklingfilé": [{"produktnamn": "Kycklingfilé", "pris_kr": 59, "kampanj": {"text": "2 för 99 kr", "ordinariePris": None}}],
            "biff": [{"produktnamn": "Biff", "pris_kr": 129, "kampanj": None}],
        }
        api_server.parse_products = lambda page, chain, query: by_query.get(query.lower(), [{"produktnamn": query, "pris_kr": 10, "kampanj": None}])
        try:
            status, payload = self.get("/api/campaigns?butik=Coop&zip=11122", token=self._premium_token())
            self.assertEqual(status, 200)
            deal_ingredients = [deal["ingrediens"] for deal in payload["kampanjer"]]
            self.assertIn("Kycklingfilé", deal_ingredients)
            self.assertNotIn("Biff", deal_ingredients)
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            api_server.CACHE.clear()
            api_server.CAMPAIGN_CACHE.clear()

    def test_products_batch_rejects_invalid_input(self):
        status, payload = self.post("/api/products/batch", {"butik": "Willys", "zip": "11122"})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        status, _ = self.post("/api/products/batch", {"butik": "OkändButik", "zip": "11122", "varor": ["Pasta"]})
        self.assertEqual(status, 400)

    def test_products_batch_prefers_a_name_that_starts_with_the_ingredient(self):
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        api_server.sync_playwright = _fake_sync_playwright
        by_query = {
            # First result by search relevance is a wrong-department cheap match
            # (mirrors the real "Paprika" -> "Cheese Paprika Sandwich" case) -
            # the actual "Paprika ..." product should still win.
            "paprika": [{"produktnamn": "Cheese Paprika Sandwich 2-pack", "pris_kr": 7.9}, {"produktnamn": "Paprika Röd Klass 1", "pris_kr": 19.9}],
            "lok": [{"produktnamn": "Lök Gul Klass 1", "pris_kr": 5}],
        }
        api_server.parse_products = lambda page, chain, query: by_query.get(query.lower(), [])
        try:
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "zip": "11122", "varor": ["Paprika", "Lok", "Okänd vara"]})
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"]["Paprika"]["produktnamn"], "Paprika Röd Klass 1")
            self.assertEqual(payload["produkter"]["Lok"]["produktnamn"], "Lök Gul Klass 1")
            self.assertIsNone(payload["produkter"]["Okänd vara"])
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            api_server.CACHE.clear()

    def test_products_batch_falls_back_to_first_result_when_no_name_matches(self):
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        api_server.sync_playwright = _fake_sync_playwright
        api_server.parse_products = lambda page, chain, query: [{"produktnamn": "Lime Klass 1", "pris_kr": 4.9}, {"produktnamn": "Pressad apelsinjuice", "pris_kr": 15}]
        try:
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "zip": "11122", "varor": ["Citron"]})
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"]["Citron"]["produktnamn"], "Lime Klass 1")
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            api_server.CACHE.clear()

    def test_products_batch_reuses_fresh_cache_without_scraping(self):
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        calls = []
        api_server.sync_playwright = _fake_sync_playwright
        api_server.parse_products = lambda page, chain, query: calls.append(1) or [{"produktnamn": "Fräsch scrape", "pris_kr": 10}]
        try:
            api_server.CACHE[("Willys", "smor", api_server.DEFAULT_ZIP)] = ([{"produktnamn": "Cachat smör", "pris_kr": 25}], time.monotonic())
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "varor": ["Smor"]})
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"]["Smor"]["produktnamn"], "Cachat smör")
            self.assertEqual(len(calls), 0)
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            api_server.CACHE.clear()


class AuthHttpTest(unittest.TestCase):
    """Auth endpoints served through the same running ApiHandler, with the
    account store swapped for a throwaway temp-file database per test."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_store = api_server.ACCOUNT_STORE
        self._original_code = api_server.PREMIUM_CODE
        api_server.ACCOUNT_STORE = AccountStore(Path(self._tmpdir.name) / "test.db")
        api_server.PREMIUM_CODE = "hemlig-kod"

    def tearDown(self):
        api_server.ACCOUNT_STORE.close()
        api_server.ACCOUNT_STORE = self._original_store
        api_server.PREMIUM_CODE = self._original_code
        self._tmpdir.cleanup()

    def post(self, path, payload=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            body = json.dumps(payload or {}).encode("utf-8")
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            response_body = response.read()
            return response.status, json.loads(response_body) if response_body else None
        finally:
            conn.close()

    def get(self, path, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            body = response.read()
            return response.status, json.loads(body) if body else None
        finally:
            conn.close()

    def _email(self):
        return f"user-{uuid.uuid4().hex}@example.com"

    def test_register_login_and_me(self):
        email = self._email()
        status, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        self.assertEqual(status, 201)
        token = payload["token"]
        self.assertEqual(payload["user"], {"email": email, "premium": False})
        status, payload = self.get("/api/auth/me", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["email"], email)

    def test_register_rejects_duplicate_email(self):
        email = self._email()
        self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        status, payload = self.post("/api/auth/register", {"email": email, "password": "annat-losenord"})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_login_rejects_wrong_password(self):
        email = self._email()
        self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        status, _ = self.post("/api/auth/login", {"email": email, "password": "fel-losenord"})
        self.assertEqual(status, 401)

    def test_me_rejects_missing_token(self):
        status, _ = self.get("/api/auth/me")
        self.assertEqual(status, 401)

    def test_redeem_premium_with_correct_code(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        token = payload["token"]
        status, payload = self.post("/api/auth/redeem", {"code": "hemlig-kod"}, token=token)
        self.assertEqual(status, 200)
        self.assertTrue(payload["user"]["premium"])
        status, payload = self.get("/api/auth/me", token=token)
        self.assertTrue(payload["user"]["premium"])

    def test_redeem_premium_with_wrong_code(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        token = payload["token"]
        status, _ = self.post("/api/auth/redeem", {"code": "fel-kod"}, token=token)
        self.assertEqual(status, 400)

    def test_logout_invalidates_session(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        token = payload["token"]
        status, _ = self.post("/api/auth/logout", token=token)
        self.assertEqual(status, 200)
        status, _ = self.get("/api/auth/me", token=token)
        self.assertEqual(status, 401)


class IcaStoreCacheTest(unittest.TestCase):
    def tearDown(self):
        api_server.ICA_STORE_CACHE.clear()

    def test_fresh_cache_entry_skips_network_lookup(self):
        api_server.ICA_STORE_CACHE["11122"] = ([{"accountId": "abc"}], time.monotonic() + 60)

        class ExplodingPage:
            def goto(self, *args, **kwargs):
                raise AssertionError("should not hit the network for a fresh cache entry")

        store = api_server.resolve_ica_store(ExplodingPage(), "11122")
        self.assertEqual(store, {"accountId": "abc"})

    def test_failed_lookup_expires_and_is_retried(self):
        api_server.ICA_STORE_CACHE["11122"] = ([], time.monotonic() - 1)

        class FakeLocator:
            def inner_text(self):
                return json.dumps({"forPickupDelivery": [{"accountId": "xyz"}]})

        class FakePage:
            def goto(self, *args, **kwargs):
                pass

            def locator(self, selector):
                return FakeLocator()

        store = api_server.resolve_ica_store(FakePage(), "11122")
        self.assertEqual(store, {"accountId": "xyz"})


class NearbyStoresTest(unittest.TestCase):
    def test_haversine_km_known_distance(self):
        # Stockholm to Gothenburg is roughly 400 km as the crow flies.
        distance = api_server.haversine_km(59.3293, 18.0686, 57.7089, 11.9746)
        self.assertTrue(390 <= distance <= 410, distance)

    def test_nearby_stores_combines_all_chains_sorts_by_distance_and_caps_radius(self):
        originals = {
            name: getattr(api_server, name)
            for name in ["geocode_postcode", "fetch_axfood_stores", "ica_stores_for_zip", "search_coop_stores", "sync_playwright"]
        }
        api_server.geocode_postcode = lambda zip_code: {"ort": "Gävle", "lat": 60.67, "lon": 17.14}
        api_server.fetch_axfood_stores = lambda chain: [{"kedja": chain, "namn": f"{chain} nära", "lat": 60.68, "lon": 17.15, "ort": "Gävle"}]
        api_server.ica_stores_for_zip = lambda page, zip_code: [{"name": "ICA långt bort", "latitude": 65.6, "longitude": 22.15, "address": {"city": "Luleå"}}]
        api_server.search_coop_stores = lambda page, city: [{"kedja": "Coop", "namn": "Coop nära", "lat": 60.69, "lon": 17.16, "ort": "Gävle"}]
        api_server.sync_playwright = _fake_sync_playwright
        try:
            stores = api_server.nearby_stores("80252")
        finally:
            for name, fn in originals.items():
                setattr(api_server, name, fn)
        chains = {store["kedja"] for store in stores}
        self.assertEqual(chains, {"Willys", "Hemköp", "Coop"})  # ICA store ~400km away is outside the radius cap
        self.assertEqual(stores, sorted(stores, key=lambda store: store["avstandKm"]))
