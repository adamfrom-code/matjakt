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
import random
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
    from services.household import HouseholdStore, NotificationStore
    from services.analytics import AnalyticsStore
    from services.grocery import api as grocery_api
    from services.recipes import api as recipes_api
    from services.recipes import prices as recipe_prices
    from tests.e2e import fixture
    from tests.e2e.diagnos import (rader_som_saenker_taeckningen, sammanfatta_begaran,
                                   sammanfatta_svar)

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
            # Hushållet delar SQLite-fil med kontona i produktion, och måste
            # göra det här också - annars ligger sessionen i en databas och
            # medlemskapet i en annan, och inget hushåll går att slå upp.
            "household": api_server.HOUSEHOLD_STORE,
            "notifications": api_server.NOTIFICATION_STORE,
            # ANALYTICS binder ACCOUNT_STORE.connection VID IMPORT. Byts bara
            # kontolagret ut hamnar resans händelser i den ursprungliga
            # databasen medan kontona ligger här - och user_id krockar mellan
            # databaserna, så en annan testfils konto får resans klick.
            # (Syntes som "4 != 3" i trattestet när E2E:n körs i samma
            # process som enhetstesterna, dvs. lokalt där Playwright finns.)
            "analytics": api_server.ANALYTICS,
            "stripe": (api_server.STRIPE_SECRET_KEY, api_server.STRIPE_WEBHOOK_SECRET,
                       api_server.STRIPE_PRICE_MONTHLY, api_server.STRIPE_PRICE_YEARLY,
                       api_server.APP_URL, api_server.create_customer, api_server.create_checkout_session),
        }
        grocery_api.DB_PATH = root / "grocery.db"
        recipes_api.DB_PATH = root / "recipes.db"
        api_server.ACCOUNT_STORE = AccountStore(root / "matjakt.db")
        api_server.HOUSEHOLD_STORE = HouseholdStore(root / "matjakt.db")
        api_server.NOTIFICATION_STORE = NotificationStore(root / "matjakt.db")
        api_server.ANALYTICS = AnalyticsStore(api_server.ACCOUNT_STORE.connection)
        grocery_api.clear_cache()
        recipes_api.clear_cache()
        ratelimit.reset()

        self.recipes_imported = recipes_api.bootstrap_if_empty()
        self.seeded = fixture.seed_grocery(grocery_api.DB_PATH, recipes_api.DB_PATH)
        grocery_api.clear_cache()
        self.repriced = recipe_prices.reprice_all()
        api_server.KV_CACHE.set("geocode", fixture.POSTCODE, dict(fixture.GAVLE))
        # INGEN E2E får nå en riktig leverantör. Utan det här sträckte sig
        # /api/products/batch efter primat.nu på riktigt (43 anrop i en enda
        # resa) - det syntes aldrig, för utfallet swaldes som "leverantören
        # svarar inte". Spärren i data_guard gör numera samma försök till ett
        # 500, vilket är hur det upptäcktes. E2E:n har sin egen prisdata i
        # fixturen och behöver ingen livesökning.
        self._saved["primat"] = (api_server.primat_resolve_stores,
                                 api_server.primat_search_products)
        api_server.primat_resolve_stores = lambda zip_code, api_key=None: {}
        api_server.primat_search_products = lambda *args, **kwargs: []
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
        api_server.HOUSEHOLD_STORE.close()
        api_server.NOTIFICATION_STORE.close()
        api_server.HOUSEHOLD_STORE = self._saved["household"]
        api_server.NOTIFICATION_STORE = self._saved["notifications"]
        api_server.ANALYTICS = self._saved["analytics"]
        grocery_api.DB_PATH = self._saved["grocery"]
        recipes_api.DB_PATH = self._saved["recipes"]
        api_server.ACCOUNT_STORE = self._saved["accounts"]
        api_server.FRONTEND_DIR = self._saved["frontend"]
        (api_server.primat_resolve_stores, api_server.primat_search_products) = self._saved["primat"]
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

    def _spara_prissattning(self, response):
        """Begäran och svar, lästa medan de fortfarande finns kvar."""
        try:
            begäran = sammanfatta_begaran(response.request.post_data)
        except Exception as error:          # noqa: BLE001
            begäran = {"kropp": f"kunde inte läsas: {error!r}"}
        try:
            svar = sammanfatta_svar(response.status, response.json())
        except Exception as error:          # noqa: BLE001
            svar = {"status": response.status, "kropp": f"kunde inte läsas: {error!r}"}
        self.pricing_responses.append({"väg": response.url.split("/api/", 1)[-1],
                                       "begäran": begäran, "svar": svar})

    def _pricing_diagnosis(self):
        """Vad prissättningen FRÅGADE om och vad den svarade, i anropsordning.

        Begäran är beviset. Skärmens och localStorages tillstånd läses efter
        att flera omgångar hunnit köra och säger därför ingenting säkert om
        vad just det felande anropet innehöll - de tas med som komplettering,
        tydligt märkta, inte som underlag.
        """
        anrop = [f"[{nummer}] POST /api/{a['väg']} begäran={a['begäran']} svar={a['svar']}"
                 for nummer, a in enumerate(self.pricing_responses[-6:], start=1)]

        # KOMPLETTERANDE, inte bevis: läget vid assertionen, inte vid anropet.
        kort = self.page.evaluate("() => document.querySelector('#storeCards')?.innerText || ''")
        korg = self.page.evaluate(
            "() => [...document.querySelectorAll('#shoppingList .shopping-item')]"
            ".map(e => (e.innerText || '').split('\\n')[0].trim()).filter(Boolean)")
        extra = self.page.evaluate(
            "() => { try { const s = JSON.parse(localStorage.getItem('matjakt-state') || '{}');"
            " return {extra: (s.extraItems || []).map(e => e.name), personer: s.personer,"
            " valda: s.valda, borttagna: s.removedItems, butik: s.butik}; }"
            " catch (error) { return {fel: 'olasbart lage'}; } }")
        return (f"frö={self.seed} (kör om exakt den här veckan med "
                f"MATJAKT_E2E_SEED={self.seed})\nANROP I ORDNING:\n  " + "\n  ".join(anrop)
                + f"\nEFTERÅT (komplettering, inte bevis): kort={kort!r}"
                + f" kassen({len(korg)})={korg!r} läge={extra!r}")

    def setUp(self):
        ratelimit.reset()
        self.context = self.browser.new_context(viewport=MOBILE, locale="sv-SE", service_workers="block",
                                                is_mobile=True, has_touch=True)
        # VECKAN ÄR SLUMPAD, avsiktligt: everydayRank (app.js) lägger
        # Math.random() på rankningen så att "Skapa ny vecka" ger en ny
        # vecka. Följden är att resan lottar i receptbanken vid varje
        # körning - och ett fel som bara vissa veckor utlöser går då inte
        # att spela upp igen.
        #
        # Fröet SÄTTS men slumpas fortfarande per körning: variationen är
        # poängen, det som saknades var att kunna återvända till den.
        #
        # VAD FRÖET RÄCKER TILL, mätt: samma frö ger samma FÖLJD av veckor,
        # men körningarna kan hamna ur fas om antalet prisanrop skiljer sig
        # (kör 1:s andra vecka var kör 2:s första). Fröet gör alltså
        # uppspelning trolig, inte garanterad. Den exakta veckan står i
        # diagnosens recipeIds - det är den som är det sparade urvalet.
        # Ingen timeout höjs och inget kvalitetskrav sänks.
        self.seed = int(os.environ.get("MATJAKT_E2E_SEED") or random.randrange(2**31))
        self.context.add_init_script(f"""
            (() => {{
              let frö = {self.seed} >>> 0;
              Math.random = () => {{
                frö = (frö + 0x6D2B79F5) >>> 0;
                let t = frö;
                t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
                t = (t ^ (t + Math.imul(t ^ (t >>> 7), t | 61))) >>> 0;
                return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
              }};
            }})();
        """)
        self.page = self.context.new_page()
        self.page.set_default_timeout(20_000)
        self.console_errors = []
        # Nätdisciplin: hur många live-prisanrop resan gör. Free ska göra
        # NOLL (priserna kommer ur prisdatabasen), Premium några få chunkar.
        self.batch_requests = []
        self.page.on("request", lambda request: self.batch_requests.append(request.url)
                     if "/api/products/batch" in request.url else None)
        # Diagnostik: varje prissättningsanrop sparas i ANROPSORDNING med
        # både begäran och svar. Ett svar utan sin begäran går inte att
        # tolka - "16 av 19" beror på vilka varor som frågades efter, med
        # vilka mängder, med vilket skafferiavdrag och för vilken kedja.
        # /pricing/list är med därför att extravarorna hämtar sina priser
        # där, och de ingår i samma kasse som veckan.
        #
        # KROPPEN LÄSES DIREKT, inte vid assertionen. Playwright kastar bort
        # svarskroppen så fort sidan navigerat ("Response body is not
        # available for a response that was navigated away from"), och resan
        # navigerar flera gånger - så de tidiga anropen, just de som skapade
        # veckan, gick inte att läsa när de behövdes.
        self.pricing_responses = []
        self.page.on("response", lambda response: self._spara_prissattning(response)
                     if ("/api/pricing/week" in response.url
                         or "/api/pricing/list" in response.url) else None)
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
            # Kryssrutan är borta: "Har hemma" och "Köpt" är två olika saker
            # och har två knappar (hushållspasset, §6). Ett klick på Köpt är
            # det som förr var en avbockning - plus att varan hamnar hemma.
            page.click("#shoppingList [data-bought] >> nth=0")
            state = self.wait_for_state(lambda s: len(s.get("avklarade") or []) == 1 and len(s.get("removedItems") or []) == 1,
                                        what="borttagen + köpt")
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
            # TVÅ, inte en: "Köpt" i steget ovan lägger varan hemma (§6 -
            # det man just burit hem finns hemma), och riset här är den
            # andra. Förr gjorde en avbockning ingenting med skafferiet.
            expect(page.locator("#pantryCount")).to_have_text("2")

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
            # Två i skafferiet: den köpta varan och riset - se steget ovan.
            self.wait_for_server_state(lambda s: s.get("weekPlan") == swapped_week and len(s.get("pantry") or {}) == 2,
                                       what="vecka + skafferi synkade")
            self.logout()
            state = self.wait_for_state(lambda s: not s.get("weekPlan"), what="rensad vecka")
            self.assertFalse(state.get("pantry"))
            self.login(email)
            state = self.wait_for_state(lambda s: s.get("weekPlan") == swapped_week, timeout=20, what="återställd vecka")
            self.assertEqual(state["removedItems"], [removed_name])
            self.assertEqual(len(state["avklarade"]), 1)
            self.assertEqual(len(state["pantry"]), 2)     # köpt vara + ris
            self.assertEqual(state["budget"], 900)
            self.assertEqual(state["postnummer"], fixture.POSTCODE)
            self.close_account_modal()
            page.click('.bottom-nav-item[data-view="week"]')
            expect(page.locator("#weekTodayCard [data-week-details]")).to_be_visible()
            page.click('.bottom-nav-item[data-view="pantry"]')
            expect(page.locator("#pantryCount")).to_have_text("2")

        self.assertEqual(self.console_errors, [])
        self.assertEqual(len(self.batch_requests), 0, "Free ska aldrig hämta livepriser per vara")

    def test_tiden_till_forsta_anvandbara_listan(self):
        """U03: sikta på ungefär en minut - och MÄT, påstå inte.

        Kravet säger uttryckligen att målet ska mätas. Det som mäts är
        vägen en riktig förstagångsanvändare tar: öppna appen, svara på
        onboardingen, välja vecka, och få en inköpslista med riktiga priser.
        Klockan startar när sidan öppnas och stannar när listan har både
        varor och en prissatt total - inte när en spinner visas.

        VAD SIFFRAN INTE ÄR. Maskinen skriver inte, den klickar direkt, och
        servern är lokal utan nätlatens. Mätningen sätter alltså ett GOLV
        för hur snabbt flödet kan gå, inte hur lång tid en människa
        faktiskt behöver. Den fångar det den kan fånga: att appen inte
        själv lägger in minuter av väntan. Gränsen är satt med marginal så
        att en långsam CI-maskin inte gör testet till en lottning - det
        som ska larma är en REGRESSION, inte en dålig dag hos GitHub.
        """
        page = self.page
        start = time.monotonic()
        page.goto(self.app())
        self.complete_onboarding()
        self.choose_standard_week()
        page.click('.bottom-nav-item[data-view="basket"]')
        expect(page.locator("#shoppingList .shopping-item").first).to_be_visible()
        # "Användbar" = varor OCH ett riktigt pris. En lista utan pris går
        # inte att handla efter, och en spinner är inte en lista.
        expect(page.locator("#shoppingCost")).not_to_contain_text("pris hämtas", timeout=30_000)
        sekunder = time.monotonic() - start

        varor = page.locator("#shoppingList .shopping-item").count()
        total = page.locator("#shoppingCost").inner_text()
        self.assertGreater(varor, 0, "listan var tom")
        self.assertRegex(total, r"\d+ kr", total)
        print(f"\n[U03] första användbara listan: {sekunder:.1f} s, {varor} varor, total {total!r}")
        self.assertLess(sekunder, 30.0,
                        f"flödet tog {sekunder:.1f} s till en användbar lista ({varor} varor)")

    def test_gasten_ser_nyttan_och_far_behalla_sin_vecka(self):
        """U02: nyttan före kontokravet, och planen överlever registreringen.

        Det klassiska felet är att kontot skapas, servern svarar med sitt
        tomma tillstånd, och gästens vecka skrivs över av ingenting. Koden
        har en gren för det (pullAccountState bootstrappar servern när den
        inte har något) - men "finns i koden" är inte "fungerar", och det
        här är den enda vägen som prövar den.
        """
        page = self.page

        with self.step("gäst: vecka och priser UTAN konto"):
            page.goto(self.app())
            self.complete_onboarding()
            self.choose_standard_week()
            # Ingen token = ingen inloggning. Nyttan ska synas ändå.
            self.assertIsNone(page.evaluate("() => localStorage.getItem('matjakt-auth-token')"))
            page.click('.bottom-nav-item[data-view="basket"]')
            expect(page.locator("#shoppingList .shopping-item").first).to_be_visible()
            self.wait_for_store_cards()
            varor = page.locator("#shoppingList .shopping-item").count()
            self.assertGreater(varor, 0)
            # Ett riktigt pris, inte "pris hämtas" och inte en gissning.
            self.assertRegex(page.locator("#shoppingCost").inner_text(), r"\d+ kr")
            gästens_vecka = list(self.local_state()["valda"])
            self.assertTrue(gästens_vecka)

        with self.step("konto skapas - veckan följer med"):
            self.register(f"gast-{uuid.uuid4().hex[:10]}@example.com")
            self.close_account_modal()
            # Lokalt: samma vecka, inte en tom.
            läge = self.wait_for_state(lambda s: bool(s.get("valda")), what="veckan efter registrering")
            self.assertEqual(sorted(läge["valda"]), sorted(gästens_vecka))
            self.assertEqual(page.locator("#shoppingList .shopping-item").count(), varor)

        with self.step("servern har fått gästens vecka, inte tomheten"):
            token = page.evaluate("() => localStorage.getItem('matjakt-auth-token')")
            self.assertTrue(token)
            status, payload = self.server.request(
                "GET", "/api/account/state", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(status, 200, payload)
            fjärran = (payload or {}).get("state") or {}
            self.assertEqual(sorted(fjärran.get("valda") or []), sorted(gästens_vecka),
                             "servern fick inte gästens vecka")

    def test_antagna_hemmavaror_gar_att_lagga_till(self):
        """U06 hela vägen: antagandet syns, går att lägga till, och tillägget
        blir en riktig inköpsrad med pris - inte bara ett namn.

        Receptbanken har 21 varor som är antagna i ett recept och köpta i
        ett annat (Ris antas i 1 och köps i 50). En sådan vara får ALDRIG
        erbjudas: den står redan på listan, och ett tryck vore ett dubbelköp.
        """
        page = self.page
        # Receptlänken först: den öppnar appen utan onboarding, så kontot
        # hinner skapas innan modalen tar över skärmen.
        page.goto(self.app(f"?recept={self.any_recipe_id()}"))
        expect(page.locator("#recipePage")).to_be_visible()
        self.register(f"e2e-{uuid.uuid4().hex[:10]}@example.com")
        self.close_account_modal()
        page.goto(self.app())
        self.complete_onboarding()
        self.choose_standard_week()
        page.click('.bottom-nav-item[data-view="basket"]')
        self.wait_for_store_cards()

        sektion = page.locator("#assumedHomeSection")
        expect(sektion).to_be_visible()
        expect(sektion.locator("h3")).to_have_text("Antas finnas hemma")

        # Inget som står på inköpslistan får erbjudas.
        #
        # VAD DEN HÄR KONTROLLEN INTE BEVISAR: veckan är slumpad, så en
        # vecka utan överlappande varor gör assertionen tom. Den är ett
        # regressionsskydd, inte beviset. Tillståndsmaskinen prövas
        # deterministiskt i tests/assumed-home.test.js.
        på_listan = {namn.strip().lower() for namn in
                     page.locator("#shoppingList .shopping-item strong").all_inner_texts()}
        erbjudna = [text.strip().lower() for text in
                    page.locator("#assumedHomeList [data-assumed-add]").all_inner_texts()]
        krock = [namn for namn in erbjudna if namn.split("+")[0].strip() in på_listan]
        self.assertEqual(krock, [], f"erbjöd varor som redan står på listan: {krock}")

        knappar = page.locator("#assumedHomeList [data-assumed-add]")
        self.assertGreater(knappar.count(), 0, "veckan hade inga antagna hemmavaror att pröva")
        namn = knappar.first.get_attribute("data-assumed-add")
        före = page.locator("#shoppingCost").inner_text()

        knappar.first.click()
        # Varan blir en riktig rad med mängd - inte bara ett namn.
        läge = self.wait_for_state(lambda s: any(e.get("name") == namn for e in s.get("extraItems") or []),
                                   what=f"{namn} som extravara")
        rad = next(e for e in läge["extraItems"] if e["name"] == namn)
        self.assertEqual(rad.get("qty"), 1, rad)
        self.assertEqual(rad.get("source"), "assumed_home", rad)

        # Chippet stannar kvar men byter tillstånd - det försvinner inte.
        expect(page.locator("#assumedHomeList .assumed-chip.is-added")).to_contain_text(namn)
        expect(page.locator(f'#assumedHomeList [data-assumed-add="{namn}"]')).to_have_count(0)

        expect(page.locator("#extraItemsSection")).to_be_visible()
        expect(page.locator("#extraItemsList")).to_contain_text(namn)

        # DEN ÄRLIGA VARIANTEN, inte den önskade.
        #
        # Extravaror prissätts som "1 st" (syncExtraMatches). En vara som
        # säljs i gram eller milliliter går inte att räkna om från styck, så
        # price_list markerar raden osäker och nollar totalCost enligt regeln
        # om säkra totaler - och klienten filtrerar bort rader utan total.
        # Mätt mot fixturen: 13 av 35 antagna hemmavaror hamnar där, bland
        # dem Olivolja, Smör, Vetemjöl, Ris, Honung och Sirap.
        #
        # Kontraktet som gäller i dag är alltså: raden får ETT PRIS ELLER en
        # synlig upplysning om att pris saknas. Det som ALDRIG får hända är
        # en tyst nolla - en rad som ser prissatt ut och bidrar med 0 kr.
        # Se docs/MASTER_BACKLOG.md; luckan gäller alla extravaror, även de
        # som skrivs in för hand, och är inte något U06 införde.
        rad = page.locator("#extraItemsList")
        expect(rad).to_be_visible()
        text = rad.inner_text()
        utan_pris = "Ingen säker prismatch" in text
        totalen = page.locator("#shoppingCost").inner_text()
        if utan_pris:
            self.assertEqual(totalen, före,
                             "oprissatt rad ändrade totalen - då är nollan inte ärlig")
        else:
            self.assertRegex(text, r"\d")            # ett pris syns på raden
            self.assertNotEqual(totalen, före, "prissatt rad räknades inte in i totalen")

        # BETALVÄGGEN HÅLLER FORTFARANDE. Gaten avgörs numera på veckan i
        # stället för på extravarorna - det får inte betyda att Free får se
        # alla kedjors listor. Exakt EN kedja ska svara 200, resten 403.
        läge = self.local_state()
        # Token bor i sin egen nyckel, inte i synkpayloaden - den ska aldrig
        # följa med ett tillstånd som skickas till servern.
        token = page.evaluate("() => localStorage.getItem('matjakt-auth-token')")
        self.assertTrue(token, "kontot saknar token i webbläsarens lagring")
        recept = [r["id"] for r in (läge.get("apiRecipes") or [])] or list(läge.get("valda") or [])
        svar = {}
        for kedja in ("Willys", "Hemköp", "City Gross"):
            status, _ = self.server.request(
                "POST", "/api/pricing/list",
                {"chain": kedja, "recipeIds": recept, "people": läge.get("personer") or 2,
                 "items": [{"name": namn, "amount": 1, "unit": "st"}]},
                headers={"Authorization": f"Bearer {token}"})
            svar[kedja] = status
        self.assertEqual(sorted(svar.values()), [200, 403, 403], svar)

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
            # Texten får inte PÅSTÅ att betalningen är gjord: användaren kan ha
            # stängt Stripes sida utan att betala (särskilt i native-appen).
            expect(page.locator("#accountPremiumStatus")).to_contain_text("Kontrollerar om betalningen")
            # Och köpknappen ska finnas kvar så länge Premium inte är aktiverat,
            # annars är en avbruten betalning en återvändsgränd.
            expect(page.locator("#premiumPitch")).to_be_visible()
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
            try:
                expect(page.locator("#storeCards .store-card:not(.locked):not(.unavailable)")).to_have_count(3, timeout=30_000)
            except AssertionError as error:
                raise AssertionError(str(error) + " | DIAGNOS: " + self._pricing_diagnosis()) from None
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
        self.assertLessEqual(len(self.batch_requests), 12,
                             f"för många livepris-anrop för en Premium-resa: {len(self.batch_requests)}")


if __name__ == "__main__":
    unittest.main()
