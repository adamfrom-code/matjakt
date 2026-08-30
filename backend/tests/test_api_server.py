import concurrent.futures
import hashlib
import hmac
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

    def test_store_key_param_accepts_a_real_primat_key(self):
        self.assertEqual(api_server.store_key_param("coop:206414"), "coop:206414")

    def test_store_key_param_rejects_malformed_input(self):
        for bad in ["", "coop", "coop:", ":206414", "coop 206414", "<script>alert(1)</script>", "a" * 41]:
            self.assertIsNone(api_server.store_key_param(bad), bad)

    def test_cache_scope_folds_a_store_key_into_the_zip(self):
        self.assertEqual(api_server.cache_scope("80252", None), "80252")
        self.assertEqual(api_server.cache_scope("80252", "coop:206414"), "80252#coop:206414")
        # Different stores in the same zip must never collapse to one key.
        self.assertNotEqual(api_server.cache_scope("80252", "coop:206401"), api_server.cache_scope("80252", "coop:206414"))

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

    def test_best_match_rejects_swedish_compound_words_that_merely_start_with_the_query(self):
        """Found directly against real Primat data: "Majs" (corn) picked
        "Majskakor Ost" (corn CAKES, a snack) because the string "majskakor"
        starts with "majs" as a character sequence, even though they're
        completely different products. Swedish forms compounds this way
        constantly, so a raw substring check silently recommends the wrong
        product; matching whole leading words instead must reject these."""
        products = [
            {"produktnamn": "Majskakor Ost", "pris_kr": 16},
            {"produktnamn": "Majs på kolv", "pris_kr": 20},
        ]
        self.assertEqual(api_server.best_match(products, "Majs")["produktnamn"], "Majs på kolv")

    def test_best_match_rejects_riskakor_for_ris(self):
        products = [{"produktnamn": "Riskakor Ost", "pris_kr": 15}, {"produktnamn": "Ris Långkornigt", "pris_kr": 30}]
        self.assertEqual(api_server.best_match(products, "Ris")["produktnamn"], "Ris Långkornigt")

    def test_best_match_rejects_paprikapulver_for_paprika(self):
        products = [{"produktnamn": "Paprikapulver Tetra", "pris_kr": 62}, {"produktnamn": "Paprika Röd Klass 1", "pris_kr": 20}]
        self.assertEqual(api_server.best_match(products, "Paprika")["produktnamn"], "Paprika Röd Klass 1")

    def test_best_match_handles_multi_word_queries_by_matching_all_leading_words(self):
        products = [{"produktnamn": "Svartaste Bönorna Special", "pris_kr": 5}, {"produktnamn": "Svarta Bönor Naturella", "pris_kr": 10}]
        self.assertEqual(api_server.best_match(products, "Svarta bönor")["produktnamn"], "Svarta Bönor Naturella")

    def test_best_match_returns_none_when_nothing_matches_by_word(self):
        """No candidate has the query as leading words at all. There used to
        be a fallback here (whatever Primat ranked first) - that's exactly
        the mechanism that put "Avorio Risottoris" on a shopping list for
        "Ris" in production, so a caller must get None (-> "Pris saknas"),
        never a guess."""
        products = [{"produktnamn": "Lime Klass 1", "pris_kr": 5}, {"produktnamn": "Apelsinjuice", "pris_kr": 15}]
        self.assertIsNone(api_server.best_match(products, "Citron"))

    def test_best_match_rejects_citron_flavoured_soda_by_category(self):
        """Live reproduction (2026-08-30): Coop's "Citron" search surfaced
        "Citronsoda Sockerfri" and "Sprite", both starting with the literal
        word "Citron" (a flavour name) and both passing the word-boundary
        check. Primat's own category ("Dryck > Läsk > ...") is what actually
        distinguishes a soda from real lemons."""
        products = [
            {"produktnamn": "Citronsoda Sockerfri", "pris_kr": 12, "kategori": "Dryck > Läsk > Citron- & limesmak"},
            {"produktnamn": "Citron Eko", "pris_kr": 33, "kategori": "Frukt & Grönsaker > Frukt > Citrusfrukt"},
        ]
        self.assertEqual(api_server.best_match(products, "Citron")["produktnamn"], "Citron Eko")

    def test_best_match_rejects_citron_juice_by_exclude_word(self):
        """"Citronjuice" also starts with the word "Citron" and sits in a
        third category (Kryddor & Smaksättare > Såser & dressing) that isn't
        covered by the soda case above - the per-ingredient exclude list
        catches it regardless of category."""
        products = [
            {"produktnamn": "Citronjuice", "pris_kr": 9, "kategori": "Kryddor & Smaksättare > Såser & dressing > Pressad citron & Lime"},
            {"produktnamn": "Citron Klass 1", "pris_kr": 7, "kategori": "Frukt & Grönsaker > Frukt > Citrusfrukt"},
        ]
        self.assertEqual(api_server.best_match(products, "Citron")["produktnamn"], "Citron Klass 1")

    def test_best_match_rejects_risotto_rice_for_plain_ris(self):
        """Live reproduction (2026-08-30, Willys): with no plain "Ris ..."
        product in stock, the old fallback picked "Avorio Risottoris" -
        specialty risotto rice, sharing the exact same Primat category as
        everyday rice ("Skafferi > Ris, Mos & Gryner > Ris"), so category
        alone can't reject it - only the name-based exclude list can."""
        products = [{"produktnamn": "Avorio Risottoris", "pris_kr": 30, "kategori": "Skafferi > Ris, Mos & Gryner > Ris"}]
        self.assertIsNone(api_server.best_match(products, "Ris"))

    def test_best_match_accepts_plain_ris_alongside_rejected_risotto_rice(self):
        products = [
            {"produktnamn": "Avorio Risottoris", "pris_kr": 30, "kategori": "Skafferi > Ris, Mos & Gryner > Ris"},
            {"produktnamn": "Ris Långkornigt", "pris_kr": 28, "kategori": "Skafferi > Ris, Mos & Gryner > Ris"},
        ]
        self.assertEqual(api_server.best_match(products, "Ris")["produktnamn"], "Ris Långkornigt")

    def test_best_match_rejects_risifrutti_for_ris(self):
        """"Risifrutti" is one compound word ("risifrutti" != "ris" split by
        word) so the word-boundary check alone already rejects it - this
        guards against that regressing."""
        products = [{"produktnamn": "Risifrutti Jordgubb", "pris_kr": 14, "kategori": "Kylvaror > Fil & Yoghurt > Barnmellanmål"}]
        self.assertIsNone(api_server.best_match(products, "Ris"))

    def test_best_match_rejects_paprikakrydda_by_category(self):
        """Same mechanism as the existing riskakor/paprikapulver word-boundary
        tests, but for a category-only collision: "Paprikakrydda" written as
        one word never passes the word check anyway, so this specifically
        covers a two-word spice name ("Paprika Krydda") that WOULD pass the
        word-boundary check and needs the category/exclude-word layer."""
        products = [
            {"produktnamn": "Paprika Krydda Stark", "pris_kr": 29, "kategori": "Kryddor & Smaksättare > Kryddor > Kryddor K - P"},
            {"produktnamn": "Paprika Röd", "pris_kr": 20, "kategori": "Frukt & Grönsaker > Grönsaker > Paprika"},
        ]
        self.assertEqual(api_server.best_match(products, "Paprika")["produktnamn"], "Paprika Röd")

    def test_best_match_ignores_category_for_scraped_products_without_one(self):
        """Scraped rows (Willys/Coop/Hemköp/ICA's own pages) never carry a
        "kategori" field - the category check must be skipped for them
        (word-boundary + exclude-words still apply), not treated as an
        automatic rejection just because the field is absent."""
        products = [{"produktnamn": "Paprika Röd Klass 1", "pris_kr": 24}]
        self.assertEqual(api_server.best_match(products, "Paprika")["produktnamn"], "Paprika Röd Klass 1")

    def test_fill_missing_image_leaves_products_without_a_gtin_untouched(self):
        """Scraped products never have a "gtin" key at all - this must be a
        pure no-op for them, not attempt a lookup with gtin=None."""
        product = {"produktnamn": "Citron", "bild": ""}
        self.assertEqual(api_server.fill_missing_image(product), product)

    def test_fill_missing_image_leaves_products_that_already_have_an_image_untouched(self):
        original = api_server.image_url_for_gtin
        calls = []
        api_server.image_url_for_gtin = lambda gtin: calls.append(1) or "https://example.com/should-not-be-used.jpg"
        try:
            product = {"produktnamn": "Citron", "bild": "https://real-store-image.jpg", "gtin": "123"}
            result = api_server.fill_missing_image(product)
        finally:
            api_server.image_url_for_gtin = original
        self.assertEqual(result["bild"], "https://real-store-image.jpg")
        self.assertEqual(calls, [])

    def test_fill_missing_image_fills_in_a_found_image(self):
        original = api_server.image_url_for_gtin
        api_server.image_url_for_gtin = lambda gtin: "https://images.openfoodfacts.org/x.jpg"
        try:
            product = {"produktnamn": "Sprite", "bild": "", "gtin": "5000112642667"}
            result = api_server.fill_missing_image(product)
        finally:
            api_server.image_url_for_gtin = original
        self.assertEqual(result["bild"], "https://images.openfoodfacts.org/x.jpg")

    def test_fill_missing_image_handles_product_not_found_gracefully(self):
        """Common, expected case for Swedish private-label groceries - Open
        Food Facts just doesn't have them. Must not raise or crash."""
        original = api_server.image_url_for_gtin
        api_server.image_url_for_gtin = lambda gtin: None
        try:
            product = {"produktnamn": "Willys Eget Märke", "bild": "", "gtin": "7311042001683"}
            result = api_server.fill_missing_image(product)
        finally:
            api_server.image_url_for_gtin = original
        self.assertEqual(result["bild"], "")

    def test_fill_missing_image_handles_open_food_facts_errors_gracefully(self):
        from services.pricing import OpenFoodFactsError
        original = api_server.image_url_for_gtin
        api_server.image_url_for_gtin = lambda gtin: (_ for _ in ()).throw(OpenFoodFactsError("timeout"))
        try:
            product = {"produktnamn": "Citron", "bild": "", "gtin": "123"}
            result = api_server.fill_missing_image(product)
        finally:
            api_server.image_url_for_gtin = original
        self.assertEqual(result["bild"], "")

    def test_fill_missing_image_caches_by_gtin(self):
        original = api_server.image_url_for_gtin
        calls = []
        api_server.image_url_for_gtin = lambda gtin: calls.append(gtin) or "https://images.openfoodfacts.org/x.jpg"
        api_server.KV_CACHE.clear()
        try:
            api_server.fill_missing_image({"produktnamn": "Sprite", "bild": "", "gtin": "5000112642667"})
            api_server.fill_missing_image({"produktnamn": "Sprite igen", "bild": "", "gtin": "5000112642667"})
        finally:
            api_server.image_url_for_gtin = original
            api_server.KV_CACHE.clear()
        self.assertEqual(calls, ["5000112642667"])

    def test_cached_products_serves_entries_within_24h_without_rescraping(self):
        """A price from earlier today (well past the old 15min TTL) should
        still come back as usable - re-scraping on every request is what made
        this unreliable, not what made it accurate (see cached_products'
        docstring). updated_at should be the real timestamp it was stored
        with, so the frontend can label it "Senast uppdaterat <tid>"."""
        stale_timestamp = time.time() - 3600
        api_server.PRICE_CACHE.set("Willys", "gurka", api_server.DEFAULT_ZIP, [{"produktnamn": "Gurka"}], updated_at=stale_timestamp)
        try:
            products, updated_at = api_server.cached_products("Willys", "gurka", api_server.DEFAULT_ZIP)
            self.assertEqual(products, [{"produktnamn": "Gurka"}])
            self.assertEqual(updated_at, stale_timestamp)
        finally:
            api_server.PRICE_CACHE.clear()

    def test_cached_products_drops_entries_older_than_max_age(self):
        """Grocery prices from a day-old cache entry are too stale to trust -
        cached_products should treat it as if it were never cached at all
        rather than silently serving an outdated price."""
        ancient_timestamp = time.time() - api_server.CACHE_MAX_AGE_SECONDS - 1
        api_server.PRICE_CACHE.set("Willys", "gurka", api_server.DEFAULT_ZIP, [{"produktnamn": "Gurka"}], updated_at=ancient_timestamp)
        try:
            products, updated_at = api_server.cached_products("Willys", "gurka", api_server.DEFAULT_ZIP)
            self.assertIsNone(products)
            self.assertIsNone(updated_at)
        finally:
            api_server.PRICE_CACHE.clear()


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


class _FakePage:
    def set_default_timeout(self, timeout_ms):
        pass

    def close(self):
        pass


class _FakeBrowser:
    def new_page(self, locale=None):
        return _FakePage()

    def close(self):
        pass

    def is_connected(self):
        return True


class _FakeChromium:
    def launch(self, headless=True):
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()


class _FakeSyncPlaywrightCtx:
    def start(self):
        return _FakePlaywright()

    def stop(self):
        pass


def _fake_sync_playwright():
    return _FakeSyncPlaywrightCtx()


def _reset_shared_browser():
    """api_server.get_shared_browser() caches a browser/playwright-context in
    thread-local storage on each of its fixed pool of scrape worker threads (by
    design - reusing one real browser per worker thread across requests is the
    whole point in production, and Playwright's sync API only works from the
    thread that started it). Tests that monkeypatch sync_playwright must clear
    that cache too, else a later test can reuse a fake browser left over on a
    worker thread from an earlier test instead of exercising its own mock. Since
    thread-local storage on another thread can't be reached directly, this
    replaces the whole executor with a fresh one, which starts with fresh
    (empty) worker threads."""
    api_server._scrape_executor.shutdown(wait=True)
    api_server._scrape_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=api_server.MAX_CONCURRENT_SCRAPES, thread_name_prefix="playwright-worker"
    )


class GetSharedBrowserTest(unittest.TestCase):
    """get_shared_browser() is written to be called from inside a scrape
    worker thread, but threading.local() state is inherently per-thread -
    calling it directly from the test's own thread exercises the exact same
    logic in complete isolation from _scrape_executor's real worker threads."""

    def setUp(self):
        self._original_sync_playwright = api_server.sync_playwright
        api_server.sync_playwright = _fake_sync_playwright
        api_server._thread_browser.browser = None
        api_server._thread_browser.playwright = None

    def tearDown(self):
        api_server.sync_playwright = self._original_sync_playwright
        api_server._thread_browser.browser = None
        api_server._thread_browser.playwright = None

    def test_reuses_the_same_browser_across_calls(self):
        first = api_server.get_shared_browser()
        second = api_server.get_shared_browser()
        self.assertIs(first, second)

    def test_relaunches_after_browser_max_requests_to_avoid_degrading_over_a_long_run(self):
        """Measured directly against production: a long run of consecutive
        real page loads on the same browser process visibly slowed down and
        started failing more often. Recycling the browser periodically is the
        mitigation - this proves it actually happens on schedule."""
        first = api_server.get_shared_browser()
        for _ in range(api_server.BROWSER_MAX_REQUESTS - 1):
            self.assertIs(api_server.get_shared_browser(), first)
        recycled = api_server.get_shared_browser()
        self.assertIsNot(recycled, first)


class RunOnScrapeThreadTest(unittest.TestCase):
    """A production incident: one scrape request hung forever (a stalled
    navigation on a resource-constrained host), and since MAX_CONCURRENT_SCRAPES=1
    in production there was only one worker thread - every request after it
    queued behind the wedged one indefinitely, taking down the whole
    /api/products* surface until the process was restarted by hand. These tests
    prove run_on_scrape_thread can't get stuck like that again: a task that runs
    past the timeout raises instead of hanging the caller, and the worker pool
    is replaced so the NEXT call gets a fresh thread rather than queuing behind
    the abandoned one forever."""

    def setUp(self):
        self._original_timeout = api_server.SCRAPE_TASK_TIMEOUT_SECONDS
        api_server.SCRAPE_TASK_TIMEOUT_SECONDS = 0.05

    def tearDown(self):
        # A timed-out call inside the test may already have replaced (and shut
        # down) _scrape_executor - always leave a fresh, live one behind rather
        # than trying to "restore" a reference that could itself be dead.
        api_server.SCRAPE_TASK_TIMEOUT_SECONDS = self._original_timeout
        api_server._scrape_executor.shutdown(wait=False)
        api_server._scrape_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=api_server.MAX_CONCURRENT_SCRAPES, thread_name_prefix="playwright-worker"
        )

    def test_hung_task_raises_instead_of_blocking_forever(self):
        release = threading.Event()
        try:
            with self.assertRaises(concurrent.futures.TimeoutError):
                api_server.run_on_scrape_thread(lambda: release.wait(5))
        finally:
            release.set()

    def test_executor_is_replaced_after_a_timeout_so_later_calls_are_not_wedged(self):
        release = threading.Event()
        original_executor = api_server._scrape_executor
        try:
            with self.assertRaises(concurrent.futures.TimeoutError):
                api_server.run_on_scrape_thread(lambda: release.wait(5))
        finally:
            release.set()
        self.assertIsNot(api_server._scrape_executor, original_executor)
        self.assertEqual(api_server.run_on_scrape_thread(lambda: 42), 42)

    def test_normal_call_within_timeout_is_unaffected(self):
        api_server.SCRAPE_TASK_TIMEOUT_SECONDS = self._original_timeout
        self.assertEqual(api_server.run_on_scrape_thread(lambda: "ok"), "ok")


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
        # Primat is a real third-party service - tests must never depend on
        # a live network call to it (slow, flaky, and .env may have a real
        # PRIMAT_API_KEY set for local dev). Default every test to "Primat
        # has nothing" so scraping fakes are what actually get exercised;
        # tests that specifically cover the Primat path replace this
        # themselves within their own try/finally, same pattern as
        # sync_playwright/parse_products elsewhere in this file.
        self._original_fetch_from_primat = api_server.fetch_from_primat
        api_server.fetch_from_primat = lambda chain, query, zip_code, store_key=None: []
        # Same reasoning as fetch_from_primat above, for the Open Food Facts
        # image lookup stamp_match() runs on every product - default to
        # "nothing found" so no test depends on a live network call.
        self._original_image_url_for_gtin = api_server.image_url_for_gtin
        api_server.image_url_for_gtin = lambda gtin: None

    def tearDown(self):
        api_server.PREMIUM_CODE = self._original_code
        api_server.fetch_from_primat = self._original_fetch_from_primat
        api_server.image_url_for_gtin = self._original_image_url_for_gtin

    def get(self, path, token=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            request_headers = {"Authorization": f"Bearer {token}"} if token else {}
            request_headers.update(headers or {})
            conn.request("GET", path, headers=request_headers)
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

    def test_admin_primat_status_refuses_unset_admin_token(self):
        """No MATJAKT_ADMIN_TOKEN configured (the default) must refuse every
        request to this endpoint, not fall open."""
        original_admin_token = api_server.ADMIN_TOKEN
        api_server.ADMIN_TOKEN = ""
        try:
            status, payload = self.get("/api/admin/primat-status", headers={"X-Admin-Token": "anything"})
            self.assertEqual(status, 404)
        finally:
            api_server.ADMIN_TOKEN = original_admin_token

    def test_admin_primat_status_refuses_a_wrong_token(self):
        original_admin_token = api_server.ADMIN_TOKEN
        api_server.ADMIN_TOKEN = "ratt-hemlighet"
        try:
            status, payload = self.get("/api/admin/primat-status", headers={"X-Admin-Token": "fel-hemlighet"})
            self.assertEqual(status, 404)
        finally:
            api_server.ADMIN_TOKEN = original_admin_token

    def test_admin_primat_status_reports_unconfigured_when_no_primat_key(self):
        original_admin_token, original_primat_key = api_server.ADMIN_TOKEN, api_server.PRIMAT_API_KEY
        api_server.ADMIN_TOKEN, api_server.PRIMAT_API_KEY = "ratt-hemlighet", ""
        try:
            status, payload = self.get("/api/admin/primat-status", headers={"X-Admin-Token": "ratt-hemlighet"})
            self.assertEqual(status, 200)
            self.assertFalse(payload["configured"])
        finally:
            api_server.ADMIN_TOKEN, api_server.PRIMAT_API_KEY = original_admin_token, original_primat_key

    def test_admin_primat_status_returns_quota_with_a_valid_token_and_never_the_key_itself(self):
        original_admin_token, original_primat_key = api_server.ADMIN_TOKEN, api_server.PRIMAT_API_KEY
        original_account_status = api_server.primat_account_status
        api_server.ADMIN_TOKEN, api_server.PRIMAT_API_KEY = "ratt-hemlighet", "hemlig-primat-nyckel"
        api_server.primat_account_status = lambda api_key: {"plan": "free", "rows_used_today": 4200, "row_budget": 20000, "resets_at": "2026-08-31T00:00:00Z"}
        try:
            status, payload = self.get("/api/admin/primat-status", headers={"X-Admin-Token": "ratt-hemlighet"})
            self.assertEqual(status, 200)
            self.assertTrue(payload["configured"])
            self.assertEqual(payload["status"]["rows_used_today"], 4200)
            self.assertNotIn("hemlig-primat-nyckel", json.dumps(payload))
        finally:
            api_server.ADMIN_TOKEN, api_server.PRIMAT_API_KEY = original_admin_token, original_primat_key
            api_server.primat_account_status = original_account_status

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

    def test_products_uses_primat_and_skips_scraping_when_it_has_results(self):
        """Primat is tried before Playwright ever gets involved (see
        fetch_from_primat's docstring) - when it has an answer, scraping
        should never run at all."""
        original_parse_products, original_fetch_from_primat = api_server.parse_products, api_server.fetch_from_primat
        scrape_calls = []
        api_server.parse_products = lambda page, chain, query: scrape_calls.append(1) or [{"produktnamn": "Fräsch scrape", "pris_kr": 1}]
        api_server.fetch_from_primat = lambda chain, query, zip_code, store_key=None: [
            {"kedja": chain, "produktnamn": "Citron Klass 1 (Primat)", "marke_och_storlek": "", "bild": "", "pris_kr": 6.9,
             "storlek": "", "lager": True, "url": "https://www.willys.se/x", "sokning": query, "kampanj": None, "gtin": "123", "kalla": "primat"}
        ]
        try:
            status, payload = self.get("/api/products?butik=Willys&q=citron")
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"][0]["produktnamn"], "Citron Klass 1 (Primat)")
            self.assertEqual(payload["produkter"][0]["kalla"], "primat")
            self.assertIn("uppdaterad", payload["produkter"][0])
            self.assertEqual(len(scrape_calls), 0)
        finally:
            api_server.parse_products, api_server.fetch_from_primat = original_parse_products, original_fetch_from_primat
            api_server.PRICE_CACHE.clear()

    def test_products_forwards_a_pinned_store_key_to_primat(self):
        """Clicking a specific branch in the store comparison list (e.g.
        "Coop Tullhuset") sends its Primat key as butiksnyckel - this must
        reach fetch_from_primat so the search is actually scoped to that
        door, not the zip's default. Returns a real match (not []) so the
        request is satisfied by Primat and never falls through to a real
        scrape, which would hang this test waiting on a live browser."""
        original_fetch_from_primat = api_server.fetch_from_primat
        seen = []
        def _fake(chain, query, zip_code, store_key=None):
            seen.append(store_key)
            return [{"kedja": chain, "produktnamn": "Citron", "marke_och_storlek": "", "bild": "", "pris_kr": 7,
                     "storlek": "", "lager": True, "url": "", "sokning": query, "kampanj": None, "gtin": "1", "kalla": "primat"}]
        api_server.fetch_from_primat = _fake
        try:
            self.get("/api/products?butik=Coop&q=citron&butiksnyckel=coop:206414")
            self.assertEqual(seen, ["coop:206414"])
        finally:
            api_server.fetch_from_primat = original_fetch_from_primat
            api_server.PRICE_CACHE.clear()

    def test_products_ignores_a_malformed_store_key(self):
        """A store key must look like Primat's own "chain:store_id" shape -
        anything else (garbage, an injection attempt) is dropped rather than
        passed through to the cache key or the outbound Primat call."""
        original_fetch_from_primat = api_server.fetch_from_primat
        seen = []
        def _fake(chain, query, zip_code, store_key=None):
            seen.append(store_key)
            return [{"kedja": chain, "produktnamn": "Citron", "marke_och_storlek": "", "bild": "", "pris_kr": 7,
                     "storlek": "", "lager": True, "url": "", "sokning": query, "kampanj": None, "gtin": "1", "kalla": "primat"}]
        api_server.fetch_from_primat = _fake
        try:
            self.get("/api/products?butik=Coop&q=citron&butiksnyckel=<script>alert(1)</script>")
            self.assertEqual(seen, [None])
        finally:
            api_server.fetch_from_primat = original_fetch_from_primat
            api_server.PRICE_CACHE.clear()

    def test_products_caches_a_pinned_store_separately_from_the_default(self):
        """Two Coop locations can genuinely have different prices - a pinned
        branch's result must never be served back for a plain (unpinned)
        request for the same chain/zip/query, or vice versa."""
        original_fetch_from_primat = api_server.fetch_from_primat
        def _fake(chain, query, zip_code, store_key=None):
            price = 42 if store_key else 10
            return [{"kedja": chain, "produktnamn": f"Citron ({store_key or 'default'})", "marke_och_storlek": "", "bild": "",
                     "pris_kr": price, "storlek": "", "lager": True, "url": "", "sokning": query, "kampanj": None, "gtin": "1", "kalla": "primat"}]
        api_server.fetch_from_primat = _fake
        try:
            status_default, payload_default = self.get("/api/products?butik=Coop&q=citron")
            status_pinned, payload_pinned = self.get("/api/products?butik=Coop&q=citron&butiksnyckel=coop:206414")
            self.assertEqual(status_default, 200)
            self.assertEqual(status_pinned, 200)
            self.assertEqual(payload_default["produkter"][0]["pris_kr"], 10)
            self.assertEqual(payload_pinned["produkter"][0]["pris_kr"], 42)
        finally:
            api_server.fetch_from_primat = original_fetch_from_primat
            api_server.PRICE_CACHE.clear()

    def test_products_falls_back_to_scraping_when_primat_has_nothing(self):
        original_sync_playwright, original_parse_products, original_fetch_from_primat = (
            api_server.sync_playwright, api_server.parse_products, api_server.fetch_from_primat
        )
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        api_server.fetch_from_primat = lambda chain, query, zip_code, store_key=None: []
        api_server.parse_products = lambda page, chain, query: [{"produktnamn": "Fräsch scrape", "pris_kr": 1}]
        try:
            status, payload = self.get("/api/products?butik=Willys&q=citron")
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"][0]["produktnamn"], "Fräsch scrape")
        finally:
            api_server.sync_playwright, api_server.parse_products, api_server.fetch_from_primat = (
                original_sync_playwright, original_parse_products, original_fetch_from_primat
            )
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()

    def test_products_cache_hit_skips_scraping(self):
        """A cache entry from an hour ago (well past the old 15min TTL) should
        be served as-is with no scrape at all - re-scraping on every request
        is exactly what made this unreliable. The response should carry an
        "uppdaterad" timestamp matching when it was actually captured, not
        the time of this request, so the frontend can label it honestly."""
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        calls = []
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        api_server.parse_products = lambda page, chain, query: calls.append(1) or [{"produktnamn": "Fräsch scrape"}]
        try:
            stale_timestamp = time.time() - 3600
            api_server.PRICE_CACHE.set("Willys", "kaffe", api_server.DEFAULT_ZIP, [{"produktnamn": "Cachad produkt"}], updated_at=stale_timestamp)
            status, payload = self.get("/api/products?butik=Willys&q=kaffe")
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"][0]["produktnamn"], "Cachad produkt")
            self.assertEqual(payload["produkter"][0]["uppdaterad"], stale_timestamp)
            self.assertEqual(len(calls), 0)
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()

    def test_products_rescrapes_once_cache_entry_exceeds_max_age(self):
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        calls = []
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        api_server.parse_products = lambda page, chain, query: calls.append(1) or [{"produktnamn": "Fräsch scrape"}]
        try:
            ancient_timestamp = time.time() - api_server.CACHE_MAX_AGE_SECONDS - 1
            api_server.PRICE_CACHE.set("Willys", "te", api_server.DEFAULT_ZIP, [{"produktnamn": "Gammal produkt"}], updated_at=ancient_timestamp)
            status, payload = self.get("/api/products?butik=Willys&q=te")
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"][0]["produktnamn"], "Fräsch scrape")
            self.assertEqual(len(calls), 1)
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()

    def test_products_502_when_nothing_cached_and_scrape_fails(self):
        """No cache entry at all (or one past CACHE_MAX_AGE_SECONDS, which
        cached_products treats the same as absent) and a failing live scrape
        leaves nothing honest to serve - this should surface as an error, not
        silently return an empty or fabricated result."""
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()

        def _boom(page, chain, query):
            raise RuntimeError("scrape failed")

        api_server.parse_products = _boom
        try:
            status, payload = self.get("/api/products?butik=Willys&q=smor")
            self.assertEqual(status, 502)
            self.assertIn("error", payload)
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()

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
        _reset_shared_browser()
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
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()
            api_server.KV_CACHE.clear()

    def test_products_batch_rejects_invalid_input(self):
        status, payload = self.post("/api/products/batch", {"butik": "Willys", "zip": "11122"})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        status, _ = self.post("/api/products/batch", {"butik": "OkändButik", "zip": "11122", "varor": ["Pasta"]})
        self.assertEqual(status, 400)

    def test_products_batch_prefers_a_name_that_starts_with_the_ingredient(self):
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        by_query = {
            # First result by search relevance is a wrong-department cheap match
            # (mirrors the real "Paprika" -> "Cheese Paprika Sandwich" case) -
            # the actual "Paprika ..." product should still win.
            "paprika": [{"produktnamn": "Cheese Paprika Sandwich 2-pack", "pris_kr": 7.9}, {"produktnamn": "Paprika Röd Klass 1", "pris_kr": 19.9}],
            "lök": [{"produktnamn": "Lök Gul Klass 1", "pris_kr": 5}],
        }
        api_server.parse_products = lambda page, chain, query: by_query.get(query.lower(), [])
        try:
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "zip": "11122", "varor": ["Paprika", "Lök", "Okänd vara"]})
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"]["Paprika"]["produktnamn"], "Paprika Röd Klass 1")
            self.assertEqual(payload["produkter"]["Lök"]["produktnamn"], "Lök Gul Klass 1")
            self.assertIsNone(payload["produkter"]["Okänd vara"])
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()

    def test_products_batch_returns_none_when_no_name_matches(self):
        """No candidate starts with "Citron" at all - must come back as
        "Pris saknas" (None), never a guess (see best_match's docstring for
        why the old fallback-to-first-result was removed)."""
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        api_server.parse_products = lambda page, chain, query: [{"produktnamn": "Lime Klass 1", "pris_kr": 4.9}, {"produktnamn": "Pressad apelsinjuice", "pris_kr": 15}]
        try:
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "zip": "11122", "varor": ["Citron"]})
            self.assertEqual(status, 200)
            self.assertIsNone(payload["produkter"]["Citron"])
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()

    def test_products_batch_reuses_fresh_cache_without_scraping(self):
        original_sync_playwright, original_parse_products = api_server.sync_playwright, api_server.parse_products
        calls = []
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        api_server.parse_products = lambda page, chain, query: calls.append(1) or [{"produktnamn": "Smör Bregott Färskt 500g", "pris_kr": 10}]
        try:
            api_server.PRICE_CACHE.set("Willys", "smör", api_server.DEFAULT_ZIP, [{"produktnamn": "Smör Bregott Cachad 500g", "pris_kr": 25}])
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "varor": ["Smör"]})
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"]["Smör"]["produktnamn"], "Smör Bregott Cachad 500g")
            self.assertEqual(len(calls), 0)
        finally:
            api_server.sync_playwright, api_server.parse_products = original_sync_playwright, original_parse_products
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()

    def test_products_batch_uses_primat_before_scraping(self):
        """The shopping list's own endpoint - this is the path that actually
        matters for Handla. A query Primat can answer should never reach
        Playwright at all."""
        original_parse_products, original_fetch_from_primat = api_server.parse_products, api_server.fetch_from_primat
        scrape_calls = []
        api_server.parse_products = lambda page, chain, query: scrape_calls.append(1) or []
        api_server.fetch_from_primat = lambda chain, query, zip_code, store_key=None: [
            {"kedja": chain, "produktnamn": "Paprika Röd Klass 1", "marke_och_storlek": "", "bild": "", "pris_kr": 19.9,
             "storlek": "", "lager": True, "url": "https://www.willys.se/x", "sokning": query, "kampanj": None, "gtin": "7311042001683", "kalla": "primat"}
        ]
        try:
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "varor": ["Paprika"]})
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"]["Paprika"]["produktnamn"], "Paprika Röd Klass 1")
            self.assertEqual(payload["produkter"]["Paprika"]["kalla"], "primat")
            self.assertEqual(len(scrape_calls), 0)
        finally:
            api_server.parse_products, api_server.fetch_from_primat = original_parse_products, original_fetch_from_primat
            api_server.PRICE_CACHE.clear()

    def test_products_batch_forwards_a_pinned_store_key_to_primat(self):
        original_fetch_from_primat = api_server.fetch_from_primat
        seen = []
        def _fake(chain, query, zip_code, store_key=None):
            seen.append(store_key)
            return [{"kedja": chain, "produktnamn": "Citron", "marke_och_storlek": "", "bild": "", "pris_kr": 7,
                     "storlek": "", "lager": True, "url": "", "sokning": query, "kampanj": None, "gtin": "1", "kalla": "primat"}]
        api_server.fetch_from_primat = _fake
        try:
            self.post("/api/products/batch", {"butik": "Coop", "varor": ["Citron"], "butiksnyckel": "coop:206414"})
            self.assertEqual(seen, ["coop:206414"])
        finally:
            api_server.fetch_from_primat = original_fetch_from_primat
            api_server.PRICE_CACHE.clear()

    def test_products_batch_falls_back_to_scraping_when_primat_has_nothing(self):
        original_sync_playwright, original_parse_products, original_fetch_from_primat = (
            api_server.sync_playwright, api_server.parse_products, api_server.fetch_from_primat
        )
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        api_server.fetch_from_primat = lambda chain, query, zip_code, store_key=None: []
        api_server.parse_products = lambda page, chain, query: [{"produktnamn": "Smör Bregott Färskt 500g", "pris_kr": 10}]
        try:
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "varor": ["Smör"]})
            self.assertEqual(status, 200)
            self.assertEqual(payload["produkter"]["Smör"]["produktnamn"], "Smör Bregott Färskt 500g")
        finally:
            api_server.sync_playwright, api_server.parse_products, api_server.fetch_from_primat = (
                original_sync_playwright, original_parse_products, original_fetch_from_primat
            )
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()

    def test_products_batch_falls_back_to_stale_price_when_a_live_refetch_fails(self):
        """An entry too old for cached_products' normal freshness window,
        combined with Primat AND scraping both failing on this request,
        should still surface as "senast känt pris" instead of a bare "Pris
        saknas" - a real, honestly-aged price beats no information at all."""
        original_sync_playwright, original_parse_products, original_fetch_from_primat = (
            api_server.sync_playwright, api_server.parse_products, api_server.fetch_from_primat
        )
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        old_timestamp = time.time() - api_server.CACHE_MAX_AGE_SECONDS - 3600
        api_server.PRICE_CACHE.set("Willys", "ris", api_server.DEFAULT_ZIP, [{"produktnamn": "Ris Långkornigt", "pris_kr": 28}], updated_at=old_timestamp)
        api_server.fetch_from_primat = lambda chain, query, zip_code, store_key=None: []
        api_server.parse_products = lambda page, chain, query: []
        try:
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "varor": ["Ris"]})
            self.assertEqual(status, 200)
            result = payload["produkter"]["Ris"]
            self.assertIsNotNone(result, "ett gammalt men riktigt pris ska visas, inte ingenting")
            self.assertEqual(result["produktnamn"], "Ris Långkornigt")
            self.assertTrue(result["senastKantPris"])
            self.assertAlmostEqual(result["uppdaterad"], old_timestamp, delta=1)
        finally:
            api_server.sync_playwright, api_server.parse_products, api_server.fetch_from_primat = (
                original_sync_playwright, original_parse_products, original_fetch_from_primat
            )
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()

    def test_products_batch_shows_pris_saknas_when_nothing_was_ever_cached(self):
        """No stale fallback exists when there's truly nothing to fall back
        to - must stay None ("Pris saknas"), not invent a price."""
        original_sync_playwright, original_parse_products, original_fetch_from_primat = (
            api_server.sync_playwright, api_server.parse_products, api_server.fetch_from_primat
        )
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        api_server.fetch_from_primat = lambda chain, query, zip_code, store_key=None: []
        api_server.parse_products = lambda page, chain, query: []
        try:
            status, payload = self.post("/api/products/batch", {"butik": "Willys", "varor": ["Saffran"]})
            self.assertEqual(status, 200)
            self.assertIsNone(payload["produkter"]["Saffran"])
        finally:
            api_server.sync_playwright, api_server.parse_products, api_server.fetch_from_primat = (
                original_sync_playwright, original_parse_products, original_fetch_from_primat
            )
            _reset_shared_browser()
            api_server.PRICE_CACHE.clear()


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
        self.assertEqual(payload["user"], {
            "email": email, "premium": False, "trialEndsAt": None, "trialUsed": False,
            "subscriptionStatus": None, "subscriptionPlan": None, "subscriptionPeriodEnd": None,
            "subscriptionCancelAtPeriodEnd": False, "emailVerified": False,
        })
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

    def test_start_trial_grants_temporary_premium(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        token = payload["token"]
        status, payload = self.post("/api/auth/start-trial", {}, token=token)
        self.assertEqual(status, 200)
        self.assertTrue(payload["user"]["premium"])
        self.assertIsNotNone(payload["user"]["trialEndsAt"])

    def test_start_trial_rejects_second_trial(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        token = payload["token"]
        self.post("/api/auth/start-trial", {}, token=token)
        status, payload = self.post("/api/auth/start-trial", {}, token=token)
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_account_state_round_trip(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        token = payload["token"]
        status, payload = self.get("/api/account/state", token=token)
        self.assertEqual(status, 200)
        self.assertIsNone(payload["state"])
        blob = {"budget": 900, "valda": ["lax", "chili"], "ogillar": ["lok"]}
        status, payload = self.post("/api/account/state", blob, token=token)
        self.assertEqual(status, 200)
        status, payload = self.get("/api/account/state", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], blob)

    def test_account_state_requires_login(self):
        status, payload = self.get("/api/account/state")
        self.assertEqual(status, 401)
        status, payload = self.post("/api/account/state", {"budget": 100})
        self.assertEqual(status, 401)

    def test_account_state_rejects_non_object_payload(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        token = payload["token"]
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/account/state", body=json.dumps([1, 2, 3]), headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {token}",
        })
        response = conn.getresponse()
        status = response.status
        response.read()
        conn.close()
        self.assertEqual(status, 400)

    def test_request_password_reset_returns_ok_for_known_and_unknown_email(self):
        email = self._email()
        self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        status, payload = self.post("/api/auth/request-password-reset", {"email": email})
        self.assertEqual(status, 200)
        status, payload = self.post("/api/auth/request-password-reset", {"email": "nobody-" + email})
        self.assertEqual(status, 200)

    def test_reset_password_via_http_then_login_with_new_password(self):
        email = self._email()
        self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        reset_token = api_server.ACCOUNT_STORE.request_password_reset(email)
        status, payload = self.post("/api/auth/reset-password", {"token": reset_token, "password": "nyttlosenord123"})
        self.assertEqual(status, 200)
        status, payload = self.post("/api/auth/login", {"email": email, "password": "hemligt123"})
        self.assertEqual(status, 401)
        status, payload = self.post("/api/auth/login", {"email": email, "password": "nyttlosenord123"})
        self.assertEqual(status, 200)

    def test_reset_password_rejects_bad_token(self):
        status, payload = self.post("/api/auth/reset-password", {"token": "okant", "password": "nyttlosenord123"})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_verify_email_via_http(self):
        email = self._email()
        self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        verify_token = api_server.ACCOUNT_STORE.create_verification_token_for_email(email)
        status, payload = self.post("/api/auth/verify-email", {"token": verify_token})
        self.assertEqual(status, 200)
        self.assertTrue(payload["user"]["emailVerified"])

    def test_resend_verification_requires_login(self):
        status, payload = self.post("/api/auth/resend-verification", {})
        self.assertEqual(status, 400)

    def test_delete_account_via_http(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        token = payload["token"]
        status, payload = self.post("/api/auth/delete-account", {}, token=token)
        self.assertEqual(status, 200)
        status, payload = self.get("/api/auth/me", token=token)
        self.assertEqual(status, 401)
        status, payload = self.post("/api/auth/login", {"email": email, "password": "hemligt123"})
        self.assertEqual(status, 401)

    def test_checkout_rejects_when_stripe_not_configured(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        status, payload = self.post("/api/billing/checkout", {"plan": "monthly"}, token=payload["token"])
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_checkout_creates_customer_once_and_returns_url(self):
        original_price, original_key = api_server.STRIPE_PRICE_MONTHLY, api_server.STRIPE_SECRET_KEY
        original_create_customer, original_create_checkout = api_server.create_customer, api_server.create_checkout_session
        api_server.STRIPE_PRICE_MONTHLY = "price_month"
        api_server.STRIPE_SECRET_KEY = "sk_test_fake"
        calls = {"create_customer": 0}

        def fake_create_customer(secret_key, email, user_id):
            calls["create_customer"] += 1
            return "cus_fake123"

        def fake_create_checkout_session(secret_key, customer_id, price_id, success_url, cancel_url):
            return f"https://checkout.stripe.com/fake/{customer_id}/{price_id}"

        api_server.create_customer = fake_create_customer
        api_server.create_checkout_session = fake_create_checkout_session
        try:
            email = self._email()
            _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
            token = payload["token"]
            status, payload = self.post("/api/billing/checkout", {"plan": "monthly"}, token=token)
            self.assertEqual(status, 200)
            self.assertIn("cus_fake123", payload["url"])
            self.assertIn("price_month", payload["url"])
            # Second checkout call must reuse the same Stripe customer, not create a new one.
            status, payload = self.post("/api/billing/checkout", {"plan": "monthly"}, token=token)
            self.assertEqual(status, 200)
            self.assertEqual(calls["create_customer"], 1)
        finally:
            api_server.STRIPE_PRICE_MONTHLY, api_server.STRIPE_SECRET_KEY = original_price, original_key
            api_server.create_customer, api_server.create_checkout_session = original_create_customer, original_create_checkout

    def test_portal_rejects_without_existing_customer(self):
        email = self._email()
        _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
        status, payload = self.post("/api/billing/portal", {}, token=payload["token"])
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_webhook_rejects_invalid_signature(self):
        original_secret = api_server.STRIPE_WEBHOOK_SECRET
        api_server.STRIPE_WEBHOOK_SECRET = "whsec_test"
        try:
            status, payload = self.post("/api/billing/webhook", {"type": "customer.subscription.updated"})
            self.assertEqual(status, 400)
        finally:
            api_server.STRIPE_WEBHOOK_SECRET = original_secret

    def test_webhook_updates_subscription_and_grants_premium(self):
        original_secret = api_server.STRIPE_WEBHOOK_SECRET
        api_server.STRIPE_WEBHOOK_SECRET = "whsec_test"
        try:
            email = self._email()
            _, payload = self.post("/api/auth/register", {"email": email, "password": "hemligt123"})
            token = payload["token"]
            user_id, _, _ = api_server.ACCOUNT_STORE.billing_identity_for_token(token)
            api_server.ACCOUNT_STORE.set_stripe_customer_id(user_id, "cus_webhook_test")
            body = json.dumps({
                "type": "customer.subscription.updated",
                "data": {"object": {
                    "id": "sub_123", "customer": "cus_webhook_test", "status": "active",
                    "current_period_end": int(time.time()) + 30 * 86400, "cancel_at_period_end": False,
                    "items": {"data": [{"price": {"id": "price_month"}}]},
                }},
            }).encode("utf-8")
            timestamp = int(time.time())
            signed_payload = f"{timestamp}.{body.decode('utf-8')}"
            signature = hmac.new(b"whsec_test", signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request("POST", "/api/billing/webhook", body=body, headers={
                "Content-Type": "application/json", "Stripe-Signature": f"t={timestamp},v1={signature}",
            })
            response = conn.getresponse()
            status = response.status
            response.read()
            conn.close()
            self.assertEqual(status, 200)
            status, payload = self.get("/api/auth/me", token=token)
            self.assertTrue(payload["user"]["premium"])
            self.assertEqual(payload["user"]["subscriptionStatus"], "active")
        finally:
            api_server.STRIPE_WEBHOOK_SECRET = original_secret

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
        api_server.KV_CACHE.clear()

    def test_fresh_cache_entry_skips_network_lookup(self):
        api_server.KV_CACHE.set("ica_stores", "11122", {"stores": [{"accountId": "abc"}]})

        class ExplodingPage:
            def goto(self, *args, **kwargs):
                raise AssertionError("should not hit the network for a fresh cache entry")

        store = api_server.resolve_ica_store(ExplodingPage(), "11122")
        self.assertEqual(store, {"accountId": "abc"})

    def test_failed_lookup_expires_and_is_retried(self):
        # An empty-stores entry uses the short ICA_STORE_FAILURE_TTL_SECONDS
        # (300s), not the long success TTL - backdating past that (not just
        # past 0) is what actually exercises the retry path.
        api_server.KV_CACHE.set("ica_stores", "11122", {"stores": []}, updated_at=time.time() - api_server.ICA_STORE_FAILURE_TTL_SECONDS - 1)

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
            for name in ["geocode_postcode", "fetch_axfood_stores", "ica_stores_for_zip", "search_coop_stores", "sync_playwright", "primat_nearby_stores"]
        }
        # Primat is tried first in nearby_stores() - forcing it to report
        # "nothing" here is what actually exercises the scraping fallback
        # this test is about. Without this, the test depends on a real
        # network call to a third-party service (slow, flaky, and would
        # silently stop testing the fallback path entirely if Primat ever
        # succeeds for this zip).
        api_server.primat_nearby_stores = lambda zip_code, api_key=None: []
        api_server.geocode_postcode = lambda zip_code: {"ort": "Gävle", "lat": 60.67, "lon": 17.14}
        api_server.fetch_axfood_stores = lambda chain: [{"kedja": chain, "namn": f"{chain} nära", "lat": 60.68, "lon": 17.15, "ort": "Gävle"}]
        api_server.ica_stores_for_zip = lambda page, zip_code: [{"name": "ICA långt bort", "latitude": 65.6, "longitude": 22.15, "address": {"city": "Luleå"}}]
        api_server.search_coop_stores = lambda page, city: [{"kedja": "Coop", "namn": "Coop nära", "lat": 60.69, "lon": 17.16, "ort": "Gävle"}]
        api_server.sync_playwright = _fake_sync_playwright
        _reset_shared_browser()
        try:
            stores = api_server.nearby_stores("80252")
        finally:
            for name, fn in originals.items():
                setattr(api_server, name, fn)
            _reset_shared_browser()
        chains = {store["kedja"] for store in stores}
        self.assertEqual(chains, {"Willys", "Hemköp", "Coop"})  # ICA store ~400km away is outside the radius cap
        self.assertEqual(stores, sorted(stores, key=lambda store: store["avstandKm"]))

    def test_nearby_stores_uses_primat_when_it_has_results(self):
        original = api_server.primat_nearby_stores
        api_server.primat_nearby_stores = lambda zip_code, api_key=None: [
            {"kedja": "Willys", "namn": "Willys Gävle Gestrike", "ort": "Gävle", "avstandKm": 0.9},
            {"kedja": "ICA", "namn": "Maxi ICA Stormarknad Brynäs", "ort": "Gävle", "avstandKm": 2.2},
        ]
        try:
            stores = api_server.nearby_stores("80252")
        finally:
            api_server.primat_nearby_stores = original
        self.assertEqual({store["kedja"] for store in stores}, {"Willys", "ICA"})
        self.assertEqual(stores, sorted(stores, key=lambda store: store["avstandKm"]))
