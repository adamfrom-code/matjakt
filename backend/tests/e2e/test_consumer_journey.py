# -*- coding: utf-8 -*-
"""Browser-E2E: hela konsumentresan i en riktig Chromium mot den riktiga
servern (ApiHandler i processen, egna tempdatabaser, syntetisk prisdata,
inga riktiga anrop).

    signup -> login -> onboarding 4 steg -> generera vecka -> byt rätt ->
    recept (mängder + steg) -> Handla (lista, butikskort, Billigast, lås) ->
    finns hemma -> skafferi -> butiksjämförelse (Free: paywall) ->
    logout -> login -> allt kvar

plus Premium-paywallen och Stripe-flödet i testläge med Stripe-gränsen
mockad: checkout-URL:en pekar tillbaka på appen, webhooken är riktigt
signerad och går genom den riktiga vägen, Premium aktiveras i UI:t,
uppsägning ger Free igen. Inga Stripe-nycklar, inga nätanrop.

Hoppar över sig själv utan Playwright (pip install playwright &&
playwright install chromium) och utanför tests/run.py (testvakten).
Skärmdump vid fel: MATJAKT_E2E_ARTIFACTS eller tests/e2e/artifacts/.
"""

import contextlib
import hashlib
import hmac
import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

try:
    from playwright.sync_api import expect, sync_playwright
    HAVE_PLAYWRIGHT = True
except ImportError:  # pragma: no cover - miljö utan Playwright
    HAVE_PLAYWRIGHT = False

from services.data_guard import test_mode_active

if test_mode_active():
    import api_server
    from services.accounts import ratelimit
    from services.accounts import AccountStore
    from services.grocery import api as grocery_api
    from services.recipes import api as recipes_api
    from services.recipes import prices as recipe_prices
    from tests.e2e import fixture

ARTIFACTS = Path(os.environ.get("MATJAKT_E2E_ARTIFACTS") or Path(__file__).resolve().parent / "artifacts")
MOBILE = {"width": 390, "height": 844}
PASSWORD = "hemligt-losen-123"


def _skip_reason():
    if not HAVE_PLAYWRIGHT:
        return "Playwright saknas (pip install playwright && playwright install chromium)"
    if not test_mode_active():
        return "körs bara via backend/tests/run.py (testvakten måste vara aktiv)"
    if os.environ.get("MATJAKT_E2E", "1") == "0":
        return "MATJAKT_E2E=0"
    return None


class _Server:
    """Den riktiga ApiHandler:n på en ledig port, med E2E:ns egna databaser
    inkopplade och återställda efteråt."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="matjakt-e2e-", ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self._saved = {
            "grocery": grocery_api.DB_PATH, "recipes": recipes_api.DB_PATH,
            "accounts": api_server.ACCOUNT_STORE,
            "stripe": (api_server.STRIPE_SECRET_KEY, api_server.STRIPE_WEBHOOK_SECRET,
                       api_server.STRIPE_PRICE_MONTHLY, api_server.STRIPE_PRICE_YEARLY,
                       api_server.APP_URL, api_server.create_customer, api_server.create_checkout_session),
        }
        grocery_api.DB_PATH = root / "grocery.db"
        recipes_api.DB_PATH = root / "recipes.db"
        api_server.ACCOUNT_STORE = AccountStore(root / "matjakt.db")
        grocery_api.clear_cache()
        recipes_api.clear_cache()
        ratelimit.reset()

        self.recipes_imported = recipes_api.bootstrap_if_empty()
        self.seeded = fixture.seed_grocery(grocery_api.DB_PATH, recipes_api.DB_PATH)
        grocery_api.clear_cache()
        self.repriced = recipe_prices.reprice_all()
        api_server.KV_CACHE.set("geocode", fixture.POSTCODE, dict(fixture.GAVLE))
        # MATJAKT_E2E_FRONTEND_DIR=dist/frontend kör samma resa mot det
        # byggda bundlet (scripts/build_frontend.mjs).
        self._saved["frontend"] = api_server.FRONTEND_DIR
        built = os.environ.get("MATJAKT_E2E_FRONTEND_DIR")
        if built:
            api_server.FRONTEND_DIR = Path(built).resolve()
            assert (api_server.FRONTEND_DIR / "app" / "index.html").exists(), api_server.FRONTEND_DIR

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        api_server.ACCOUNT_STORE.close()
        grocery_api.DB_PATH = self._saved["grocery"]
        recipes_api.DB_PATH = self._saved["recipes"]
        api_server.ACCOUNT_STORE = self._saved["accounts"]
        api_server.FRONTEND_DIR = self._saved["frontend"]
        (api_server.STRIPE_SECRET_KEY, api_server.STRIPE_WEBHOOK_SECRET, api_server.STRIPE_PRICE_MONTHLY,
         api_server.STRIPE_PRICE_YEARLY, api_server.APP_URL, api_server.create_customer,
         api_server.create_checkout_session) = self._saved["stripe"]
        grocery_api.clear_cache()
        recipes_api.clear_cache()
        ratelimit.reset()
        self.tmp.cleanup()

    def request(self, method, path, payload=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            base_headers = {"Content-Type": "application/json"} if body else {}
            base_headers.update(headers or {})
            conn.request(method, path, body=body, headers=base_headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()

    def post_webhook(self, event: dict, secret: str):
        body = json.dumps(event).encode("utf-8")
        timestamp = int(time.time())
        signature = hmac.new(secret.encode("utf-8"), f"{timestamp}.{body.decode('utf-8')}".encode("utf-8"),
                             hashlib.sha256).hexdigest()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", "/api/billing/webhook", body=body, headers={
                "Content-Type": "application/json", "Stripe-Signature": f"t={timestamp},v1={signature}"})
            response = conn.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()


class BrowserJourney(unittest.TestCase):
    server = None

    @classmethod
    def setUpClass(cls):
        reason = _skip_reason()
        if reason:
            raise unittest.SkipTest(reason)
        cls.server = _Server()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception as error:  # pragma: no cover - Chromium saknas
            cls.playwright.stop()
            cls.server.close()
            raise unittest.SkipTest(f"Chromium kunde inte startas: {str(error)[:120]}")
        # Självkontroll innan en enda skärmdump: prisdata måste prissätta
        # och registret måste hitta butikerna - annars är resan meningslös.
        status, stores = cls.server.request("GET", f"/api/stores?zip={fixture.POSTCODE}")
        assert status == 200 and len(stores["butiker"]) >= 3, (status, stores)
        priced = cls.server.repriced
        assert priced.get("priced", 0) >= 100, f"för få recept prissatta i fixturen: {priced}"

    @classmethod
    def tearDownClass(cls):
        if cls.server is None:
            return
        with contextlib.suppress(Exception):
            cls.browser.close()
        with contextlib.suppress(Exception):
            cls.playwright.stop()
        cls.server.close()

    def setUp(self):
        ratelimit.reset()
        self.context = self.browser.new_context(viewport=MOBILE, locale="sv-SE", service_workers="block",
                                                is_mobile=True, has_touch=True)
        self.page = self.context.new_page()
        self.page.set_default_timeout(20_000)
        self.console_errors = []
        self.page.on("pageerror", lambda error: self.console_errors.append(str(error)))
        # Riktiga sidfel (undantag) och konsolfel - men inte nätverksmissar
        # för bilder/kampanjer: E2E:n körs utan internet, och en bild som
        # inte kan hämtas är förväntat här.
        self.page.on("console", lambda message: self.console_errors.append(f"console.{message.type}: {message.text}")
                     if message.type == "error" and "Failed to load resource" not in message.text else None)
        self.step_name = "start"

    def tearDown(self):
        with contextlib.suppress(Exception):
            self.context.close()

    # ---- hjälpare ----
    @contextlib.contextmanager
    def step(self, name):
        self.step_name = name
        try:
            yield
        except Exception:
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^a-z0-9]+", "-", f"{self._testMethodName}-{name}".lower()).strip("-")
            with contextlib.suppress(Exception):
                self.page.screenshot(path=str(ARTIFACTS / f"{safe}.png"), full_page=True)
            if self.console_errors:
                print(f"\n[e2e] sidfel under '{name}': {self.console_errors}")
            raise

    def app(self, query=""):
        return f"{self.server.base}/app/{query}"

    def local_state(self):
        raw = self.page.evaluate("() => localStorage.getItem('matjakt-state')")
        return json.loads(raw) if raw else {}

    def wait_for_state(self, predicate, timeout=15.0, what="tillstånd"):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.local_state()
            if predicate(last):
                return last
            time.sleep(0.25)
        self.fail(f"{what} nådde aldrig förväntat värde; senast: {json.dumps(last)[:600]}")

    def wait_for_server_state(self, predicate, timeout=15.0, what="serversynk"):
        """Väntar in den debouncade synken till kontot (1,5 s efter sista
        ändringen) så utloggning inte hinner före - läser vad servern
        faktiskt har sparat, inte vad klienten tror."""
        token = self.page.evaluate("() => localStorage.getItem('matjakt-auth-token')")
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            raw = api_server.ACCOUNT_STORE.get_synced_state(token)
            last = json.loads(raw) if raw else {}
            if predicate(last):
                return last
            time.sleep(0.25)
        self.fail(f"{what}: servern fick aldrig förväntat tillstånd; senast: {json.dumps(last)[:600]}")

    def any_recipe_id(self):
        store = recipes_api.open_store()
        try:
            rows = store.search(limit=5)
        finally:
            store.close()
        return rows[0]["id"]

    def register(self, email):
        page = self.page
        page.click("#profileBtn")
        expect(page.locator("#accountModal")).to_be_visible()
        page.click('[data-account-tab="register"]')
        page.fill("#registerEmail", email)
        page.fill("#registerPassword", PASSWORD)
        page.click('#accountRegisterForm button[type="submit"]')
        expect(page.locator("#accountLoggedIn")).to_be_visible()
        expect(page.locator("#accountEmail")).to_have_text(email)

    def login(self, email):
        page = self.page
        if not page.locator("#accountModal").is_visible():
            page.click("#profileBtn")
        page.click('[data-account-tab="login"]')     # fliken minns "Skapa konto" från signup
        expect(page.locator("#accountLoginForm")).to_be_visible()
        page.fill("#loginEmail", email)
        page.fill("#loginPassword", PASSWORD)
        page.click('#accountLoginForm button[type="submit"]')
        expect(page.locator("#accountModal")).to_be_hidden()      # lyckad inloggning stänger modalen
        expect(page.locator("#profileBtn")).to_have_text(email[:2].upper())

    def logout(self):
        page = self.page
        if not page.locator("#accountModal").is_visible():
            page.click("#profileBtn")
        page.click("#logoutBtn")
        expect(page.locator("#accountModal")).to_be_hidden()      # utloggning stänger modalen
        expect(page.locator("#profileBtn")).to_have_text("MJ")

    def close_account_modal(self):
        if self.page.locator("#accountModal").is_visible():
            self.page.click("#accountModal .account-modal-close")
        expect(self.page.locator("#accountModal")).to_be_hidden()

    def complete_onboarding(self, postcode=fixture.POSTCODE, budget="900"):
        page = self.page
        modal = page.locator("#onboardingModal")
        expect(modal).to_be_visible()
        self.assertEqual(page.locator("#onboardingDots i").count(), 4)
        expect(page.locator("#onboardingTitle")).to_have_text("Vilka är ni hemma?")
        page.click('[data-ob-adj="vuxna"][data-delta="1"]')
        page.click("#onboardingNext")
        expect(page.locator("#onboardingTitle")).to_have_text("Budget & antal middagar")
        page.fill("#obBudget", budget)
        page.click("#onboardingNext")
        expect(page.locator("#onboardingTitle")).to_have_text("Kost & allergier")
        page.click("#onboardingNext")
        expect(page.locator("#onboardingTitle")).to_have_text("Var handlar ni?")
        expect(page.locator("#onboardingNext span")).to_have_text("Skapa min vecka")
        page.fill("#obPostcode", postcode)
        page.click("#onboardingNext")
        expect(modal).to_be_hidden()

    def choose_standard_week(self):
        page = self.page
        plan_modal = page.locator("#planModal")
        if plan_modal.is_visible():
            expect(page.locator('[data-plan-paywall]').first).to_be_visible()   # Premium-veckor låsta
            page.click('[data-choose-plan="standard"]')
            expect(plan_modal).to_be_hidden()
        expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))
        # Dagfliken följer veckodagen; en söndag utan middag har inget att
        # byta. Måndagen har alltid veckans första rätt.
        page.click('#weekDayTabs [data-week-day="0"]')
        expect(page.locator("#weekTodayCard [data-week-swap]")).to_be_visible()

    def wait_for_store_cards(self):
        cards = self.page.locator("#storeCards .store-card")
        expect(cards.first).to_be_visible(timeout=30_000)
        expect(self.page.locator("#shoppingCost")).not_to_contain_text("pris hämtas", timeout=30_000)
        return cards

    # ---- resan ----
    def test_full_consumer_journey(self):
        page = self.page
        email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
        recipe_id = self.any_recipe_id()

        with self.step("delad receptlänk öppnar receptet utan onboarding"):
            page.goto(self.app(f"?recept={recipe_id}"))
            expect(page.locator("#recipePage")).to_be_visible()
            expect(page.locator("#recipePage .ing-row").first).to_be_visible()
            expect(page.locator("#onboardingModal")).to_be_hidden()

        with self.step("signup"):
            self.register(email)

        with self.step("logout och login"):
            self.logout()
            self.login(email)
            self.close_account_modal()

        with self.step("onboarding 4 steg"):
            page.goto(self.app())
            self.complete_onboarding()

        with self.step("generera vecka"):
            self.choose_standard_week()
            state = self.wait_for_state(lambda s: s.get("weekPlan"), what="veckan")
            self.assertTrue(1 <= len(state["weekPlan"]) <= 4, state["weekPlan"])   # Free: max 4 middagar
            self.assertEqual(state["postnummer"], fixture.POSTCODE)
            self.assertEqual(state["budget"], 900)
            self.assertTrue(state["onboardingComplete"])
            first_week = list(state["weekPlan"])

        with self.step("byt rätt"):
            page.click("#weekTodayCard [data-week-swap]")
            expect(page.locator("#swapModal")).to_be_visible()
            expect(page.locator("[data-choose-swap]").first).to_be_visible()
            page.click("[data-choose-swap] >> nth=0")
            expect(page.locator("#swapConfirmBtn")).to_be_visible()
            page.click("#swapConfirmBtn")
            expect(page.locator("#swapModal")).to_be_hidden()
            state = self.wait_for_state(lambda s: s.get("weekPlan") != first_week, what="bytet")
            self.assertEqual(len(state["weekPlan"]), len(first_week))
            self.assertEqual(state.get("swapsThisWeek"), 1)
            swapped_week = list(state["weekPlan"])

        with self.step("recept: mängder och steg"):
            page.click("#weekTodayCard [data-week-details]")
            expect(page.locator("#recipePage")).to_be_visible()
            expect(page.locator("#recipePage .step-row").first).to_be_visible()
            # Mängderna kommer med detaljhämtningen (kortet i listan bär bara
            # namn) - vänta in dem i stället för att läsa mitt i.
            expect(page.locator("#recipePage .ing-row strong").first).not_to_have_text("", timeout=15_000)
            amounts = page.locator("#recipePage .ing-row strong").all_inner_texts()
            self.assertTrue(any(re.search(r"\d", text) for text in amounts), amounts)
            page.click("#recipePage .recipe-back")
            expect(page.locator("#top")).to_be_visible()

        with self.step("Handla: lista, butikskort, Billigast, lås"):
            page.click('.bottom-nav-item[data-view="basket"]')
            expect(page.locator("#top")).to_have_class(re.compile(r"view-basket"))
            expect(page.locator("#shoppingList .shopping-item").first).to_be_visible()
            items_before = page.locator("#shoppingList .shopping-item").count()
            cards = self.wait_for_store_cards()
            priced = page.locator("#storeCards .store-card:not(.locked):not(.unavailable)")
            locked = page.locator("#storeCards .store-card.locked")
            self.assertEqual(priced.count(), 1, cards.all_inner_texts())     # Free ser EN butik
            self.assertEqual(locked.count(), 2, cards.all_inner_texts())     # de andra bakom Premium
            expect(priced.first).to_contain_text("Billigast")
            expect(locked.first).to_contain_text("Se pris med Premium")
            expect(page.locator("#priceSourceNote")).to_contain_text("Priser från")
            self.assertRegex(page.locator("#shoppingCost").inner_text(), r"\d+ kr / 900 kr")

        with self.step("finns hemma (ur listan) och handlad"):
            page.click("#shoppingList [data-remove-item] >> nth=0")
            expect(page.locator("#restoreRemovedBtn")).to_contain_text("1 borttagen vara")
            expect(page.locator("#storeCardsCompareBtn")).to_have_count(0)      # Free har ingen jämförelsesida
            self.assertEqual(page.locator("#shoppingList .shopping-item").count(), items_before - 1)
            page.check("#shoppingList [data-shopping] >> nth=0")
            state = self.wait_for_state(lambda s: len(s.get("avklarade") or []) == 1 and len(s.get("removedItems") or []) == 1,
                                        what="borttagen + avbockad")
            removed_name = state["removedItems"][0]

        with self.step("skafferi: har hemma"):
            page.click('.bottom-nav-item[data-view="pantry"]')
            page.click("#addPantryBtn")
            expect(page.locator("#pantryModal")).to_be_visible()
            page.fill("#pantrySearch", "ris")
            page.click("[data-pantry-pick] >> nth=0")
            expect(page.locator("#pantryAddConfirm")).to_be_visible()
            page.click("#pantryAddConfirmBtn")
            expect(page.locator("#pantryModal")).to_be_hidden()
            expect(page.locator("#pantryCount")).to_have_text("1")

        with self.step("butiksjämförelse: Free ser spridningen, låsta butiker och paywallen"):
            page.click('.bottom-nav-item[data-view="basket"]')
            self.wait_for_store_cards()
            expect(page.locator("#storeSpreadTeaser")).to_be_visible()
            expect(page.locator("#storeSpreadTeaser")).to_contain_text("skiljer sig")
            page.click("#storeCards .store-card.locked >> nth=0")
            paywall = page.locator("#paywallModal")
            expect(paywall).to_be_visible()
            expect(paywall.locator('[data-paywall-plan="yearly"]')).to_contain_text("399 kr/år")
            expect(paywall.locator('[data-paywall-plan="monthly"]')).to_contain_text("59 kr/mån")
            page.click("#paywallModal .paywall-continue")
            expect(paywall).to_be_hidden()

        with self.step("logout rensar, login återställer"):
            self.wait_for_server_state(lambda s: s.get("weekPlan") == swapped_week and len(s.get("pantry") or {}) == 1,
                                       what="vecka + skafferi synkade")
            self.logout()
            state = self.wait_for_state(lambda s: not s.get("weekPlan"), what="rensad vecka")
            self.assertFalse(state.get("pantry"))
            self.login(email)
            state = self.wait_for_state(lambda s: s.get("weekPlan") == swapped_week, timeout=20, what="återställd vecka")
            self.assertEqual(state["removedItems"], [removed_name])
            self.assertEqual(len(state["avklarade"]), 1)
            self.assertEqual(len(state["pantry"]), 1)
            self.assertEqual(state["budget"], 900)
            self.assertEqual(state["postnummer"], fixture.POSTCODE)
            self.close_account_modal()
            page.click('.bottom-nav-item[data-view="week"]')
            expect(page.locator("#weekTodayCard [data-week-details]")).to_be_visible()
            page.click('.bottom-nav-item[data-view="pantry"]')
            expect(page.locator("#pantryCount")).to_have_text("1")

        self.assertEqual(self.console_errors, [])

    def test_premium_paywall_and_stripe_testmode(self):
        page = self.page
        server = self.server
        email = f"e2e-premium-{uuid.uuid4().hex[:8]}@example.com"
        checkouts = []

        # Stripe-gränsen mockad: kund och checkout-session skapas "hos Stripe"
        # utan nät, success-URL:en är appens egen. Webhooken går den riktiga
        # vägen (signatur, idempotens, apply_stripe_event).
        api_server.STRIPE_SECRET_KEY = "sk_test_fake"
        api_server.STRIPE_WEBHOOK_SECRET = "whsec_test"
        api_server.STRIPE_PRICE_MONTHLY = "price_e2e_month"
        api_server.STRIPE_PRICE_YEARLY = "price_e2e_year"
        api_server.APP_URL = f"{server.base}/app"
        api_server.create_customer = lambda key, mail, user_id: f"cus_e2e_{uuid.uuid4().hex[:8]}"

        def fake_checkout(key, customer_id, price_id, success_url, cancel_url):
            checkouts.append({"customer": customer_id, "price": price_id})
            return success_url
        api_server.create_checkout_session = fake_checkout

        with self.step("konto och vecka"):
            page.goto(self.app(f"?recept={self.any_recipe_id()}"))
            expect(page.locator("#recipePage")).to_be_visible()
            self.register(email)
            self.close_account_modal()
            page.goto(self.app())
            self.complete_onboarding()
            self.choose_standard_week()

        with self.step("paywall från låst veckotyp"):
            page.click('.bottom-nav-item[data-view="home"]')
            page.click("#newWeekBtn")
            expect(page.locator("#planModal")).to_be_visible()
            page.click("[data-plan-paywall] >> nth=0")
            paywall = page.locator("#paywallModal")
            expect(paywall).to_be_visible()
            expect(paywall).to_contain_text("Matjakt Premium")

        with self.step("checkout (testläge, mockad Stripe) → tillbaka i appen"):
            week_before = list(self.local_state().get("weekPlan") or [])
            self.assertTrue(week_before)
            with page.expect_navigation():
                page.click('#paywallModal [data-paywall-plan="yearly"]')
            expect(page.locator("#accountPremiumStatus")).to_contain_text("Aktiverar Premium")
            self.assertEqual(len(checkouts), 1)
            self.assertEqual(checkouts[0]["price"], "price_e2e_year")          # årsplanen mappar rätt

        with self.step("webhook aktiverar Premium i UI:t"):
            customer_id = checkouts[0]["customer"]
            status, _ = server.post_webhook({
                "id": "evt_e2e_active", "created": int(time.time()),
                "type": "customer.subscription.updated",
                "data": {"object": {"id": "sub_e2e", "customer": customer_id, "status": "active",
                                    "current_period_end": int(time.time()) + 365 * 86400,
                                    "cancel_at_period_end": False,
                                    "items": {"data": [{"price": {"id": "price_e2e_year"},
                                                         "current_period_end": int(time.time()) + 365 * 86400}]}}},
            }, "whsec_test")
            self.assertEqual(status, 200)
            expect(page.locator("#accountPremiumStatus")).to_have_text("✓ Premium aktiverat", timeout=30_000)
            expect(page.locator("#subscriptionPanelLine")).to_contain_text("399 kr/år")
            expect(page.locator("#premiumPitch")).to_be_hidden()
            # Veckan och onboardingen gjordes sekunderna före checkout: den
            # väntande synken måste ha nått servern innan sidan lämnades,
            # annars hämtar återkomsten en äldre blob och allt är borta.
            state = self.wait_for_state(lambda s: s.get("weekPlan") == week_before and s.get("onboardingComplete"),
                                        timeout=20, what="veckan efter checkout")
            self.assertEqual(state.get("postnummer"), fixture.POSTCODE)

        with self.step("Premium: alla butiker prissatta och jämförelsesidan"):
            self.close_account_modal()
            page.click('.bottom-nav-item[data-view="basket"]')
            expect(page.locator("#shoppingList .shopping-item").first).to_be_visible()
            # Efter återkomsten från checkout prissätts veckan i två omgångar
            # (ny vecka + återställd vecka) och korten töms däremellan - vänta
            # in de TRE prissatta korten innan något annat asserteras, annars
            # passerar "inga lås" på en tom behållare (sett i CI).
            expect(page.locator("#storeCards .store-card:not(.locked):not(.unavailable)")).to_have_count(3, timeout=30_000)
            expect(page.locator("#shoppingCost")).not_to_contain_text("pris hämtas", timeout=30_000)
            expect(page.locator("#storeCards .store-card.locked")).to_have_count(0)
            expect(page.locator("#storeCards .store-card-badge")).to_have_count(1)     # exakt EN Billigast
            page.click("#storeCardsCompareBtn")
            expect(page.locator("#top")).to_have_class(re.compile(r"view-comparison"))
            expect(page.locator("#comparisonStoreList .comparison-store-card")).to_have_count(3)
            expect(page.locator("#comparisonStoreList .comparison-store-card.cheapest")).to_have_count(1)
            page.click(".comparison-screen .back-link")
            expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))

        with self.step("uppsägning → Free igen"):
            status, _ = server.post_webhook({
                "id": "evt_e2e_deleted", "created": int(time.time()) + 1,
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": "sub_e2e", "customer": customer_id, "status": "canceled",
                                    "current_period_end": int(time.time()) - 10,
                                    "cancel_at_period_end": False,
                                    "items": {"data": [{"price": {"id": "price_e2e_year"}}]}}},
            }, "whsec_test")
            self.assertEqual(status, 200)
            page.reload()
            page.click("#profileBtn")
            expect(page.locator("#accountPremiumStatus")).to_have_text("Inget Premium ännu")
            expect(page.locator("#premiumPitch")).to_be_visible()
            self.close_account_modal()
            page.click('.bottom-nav-item[data-view="basket"]')
            self.wait_for_store_cards()
            expect(page.locator("#storeCards .store-card.locked")).to_have_count(2)

        self.assertEqual(self.console_errors, [])


if __name__ == "__main__":
    unittest.main()
