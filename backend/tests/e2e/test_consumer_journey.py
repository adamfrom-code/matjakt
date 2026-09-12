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
    from services.billing.savings import SavingsStore
    from services.grocery import api as grocery_api
    from services.recipes import api as recipes_api
    from services.recipes import prices as recipe_prices
    from tests.e2e import fixture
    from tests.e2e import vantan
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
            # Samma sak för sparhistoriken (J3): SavingsStore binder
            # ACCOUNT_STORE.connection vid uppstart.
            "savings": api_server.SAVINGS,
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
        api_server.SAVINGS = SavingsStore(api_server.ACCOUNT_STORE.connection,
                                          lock=api_server.ACCOUNT_STORE.lock)
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
        api_server.SAVINGS = self._saved["savings"]
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
        # Skrivboken FÖRE första sidan: varje skrivning av matjakt-state
        # bokförs i sidan, och wait_for_state väcks av den i stället för att
        # stickprova localStorage på en klocka (se e2e/vantan.py).
        self.context.add_init_script(vantan.SKRIVBOKEN)
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

    def swipe_away(self, row):
        """Sveper bort en varurad, som G5 gjorde det: på pekskärm ligger krysset
        utanför radens kant, och svep vänster är vägen dit i stället. Pek-
        händelserna skickas direkt - Playwright har tap men inget svep."""
        for typ, x in (("pointerdown", 320), ("pointermove", 300),
                       ("pointermove", 220), ("pointerup", 170)):
            row.dispatch_event(typ, {"pointerType": "touch", "clientX": x, "clientY": 400})

    def local_state(self):
        raw = self.page.evaluate("() => localStorage.getItem('matjakt-state')")
        return json.loads(raw) if raw else {}

    def wait_for_state(self, predicate, tystnad=vantan.TYSTNAD, what="tillstånd"):
        """Väntar tills predikatet är sant om något tillstånd appen SKRIVIT.

        Väcks av skrivningen, inte av en klocka: `tystnad` är hur länge
        appen får vara helt tyst innan väntan ger upp, inte hur lång tid
        väntan totalt får ta. Skillnaden är hela poängen - en lastad
        CI-maskin gör varje nätvända långsammare, men den gör inte appen
        tyst. Och ett värde som skrivs över några millisekunder senare
        missas inte längre, för varje skrivning prövas.
        """
        nulage, nasta = vantan.sidans_skrivbok(self.page)
        # Vantan ÄR ett AssertionError, så ett uteblivet tillstånd
        # rapporteras som ett fel i testet - inte som en krasch i hjälparen,
        # och utan en omslagen traceback ovanpå beskedet.
        return vantan.vanta_pa_tillstand(nulage, nasta, predicate,
                                         vad=what, tystnad=tystnad)

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

    def open_account(self):
        """Kontoarket. G11: profilknappen leder till INSTÄLLNINGAR, och
        kontoraden i den skärmen öppnar arket. Knappen hette "Öppna profil och
        inställningar" redan förut; nu leder den dit den sa att den ledde."""
        page = self.page
        if page.locator("#accountModal").is_visible():
            return
        page.click("#profileBtn")
        expect(page.locator("#top")).to_have_class(re.compile(r"view-settings"))
        page.click('[data-settings="konto"]')
        expect(page.locator("#accountModal")).to_be_visible()

    def register(self, email):
        page = self.page
        self.open_account()
        page.click('[data-account-tab="register"]')
        page.fill("#registerEmail", email)
        page.fill("#registerPassword", PASSWORD)
        page.click('#accountRegisterForm button[type="submit"]')
        expect(page.locator("#accountLoggedIn")).to_be_visible()
        expect(page.locator("#accountEmail")).to_have_text(email)

    def verify_email(self, email):
        """Följer verifieringslänken, som en ny användare gör i sin brevlåda.

        J5 kräver en bekräftad adress före ett köp: kvittot,
        lösenordsåterställningen och prenumerationssidan går alla dit, och
        den som skrev adam@gmial.com upptäckte det först efter att ha betalat
        399 kr. E2E:n har ingen SMTP, så token hämtas ur lagret - men den
        löses in via den RIKTIGA vägen."""
        token = api_server.ACCOUNT_STORE.create_verification_token_for_email(email)
        status, _ = self.server.request("POST", "/api/auth/verify-email", {"token": token})
        self.assertEqual(status, 200)

    def trial_already_used(self):
        """J3 ger sju dagars Premium efter den FÖRSTA skapade veckan, så varje
        nyregistrerat konto i en E2E ÄR Premium så snart veckan finns. Det är
        hela poängen med trialen - och samtidigt skälet att den måste vara
        förbrukad innan man prövar något som bara gäller Free.

        `trial_used = 1` säger "den här personen har redan haft sina sju
        dagar". Anropas FÖRE veckan skapas: då beviljas ingen trial alls, och
        kontot är Free hela resan igenom. Ingen omladdning behövs, och därmed
        kan ingen väntande synk gå förlorad."""
        api_server.ACCOUNT_STORE.connection.execute(
            "UPDATE users SET trial_ends_at = NULL, trial_used = 1")
        api_server.ACCOUNT_STORE.connection.commit()

    def login(self, email):
        page = self.page
        self.open_account()
        page.click('[data-account-tab="login"]')     # fliken minns "Skapa konto" från signup
        expect(page.locator("#accountLoginForm")).to_be_visible()
        page.fill("#loginEmail", email)
        page.fill("#loginPassword", PASSWORD)
        page.click('#accountLoginForm button[type="submit"]')
        expect(page.locator("#accountModal")).to_be_hidden()      # lyckad inloggning stänger modalen
        expect(page.locator("#profileBtn")).to_have_text(email[:2].upper())

    def logout(self):
        page = self.page
        self.open_account()
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
        # G8: KNAPPEN HETER "SKAPA MIN VECKA" OCH SKAPAR NU EN VECKA.
        #
        # Den öppnade förut planjämförelsen, där sju av åtta veckotyper är
        # låsta för en gratisanvändare. Det första en ny användare såg av
        # produkten var alltså en hänglåsvägg - innan hon sett en enda
        # måltid eller en enda prislapp. Nu landar hon i Vecka-vyn med en
        # färdig vecka, och erbjudandet om en annan veckotyp står som en rad
        # ovanför den.
        expect(page.locator("#planModal")).to_be_hidden()
        expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))
        expect(page.locator('#weekDayTabs [data-week-day="0"]')).to_be_visible()
        expect(page.locator("#weekPlanUpsell")).to_be_visible()

    def choose_standard_week(self):
        """Standardveckan ur planjämförelsen - eller den vecka som redan finns.

        Efter G8 öppnas modalen INTE av onboardingen; den nås från "Skapa ny
        vecka" och från raden ovanför veckan. Anropas helpern direkt efter
        onboardingen är veckan alltså redan gjord, och då finns ingen modal
        att välja i.
        """
        page = self.page
        plan_modal = page.locator("#planModal")
        if plan_modal.is_visible():
            # J3: varenda veckotyp är gratis. Veckorna sätts ihop i klienten
            # ur ett lokalt receptregister och gick aldrig att skydda - och
            # de är precis det som gör en ny användare beroende de första
            # två veckorna. Alla kort ska alltså gå att VÄLJA, inget ska bära
            # ett hänglås.
            expect(page.locator('[data-choose-plan]').first).to_be_visible()
            self.assertEqual(page.locator("[data-plan-paywall]").count(), 0,
                             "en veckotyp är låst trots att alla är gratis sedan J3")
            page.click('[data-choose-plan="standard"]')
            expect(plan_modal).to_be_hidden()
        expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))
        # Dagfliken följer veckodagen; en söndag utan middag har inget att
        # byta. Måndagen har alltid veckans första rätt.
        page.click('#weekDayTabs [data-week-day="0"]')
        expect(page.locator("#weekTodayCard [data-week-swap]")).to_be_visible()

    def wait_for_store_cards(self):
        """Butikskorten - G13: de bor på Vecka, inte i Handla.

        "Var blir det billigast?" är en fråga man svarar på innan man går
        till affären. Helpern byter därför själv till Vecka-vyn; den som
        vill mäta något i Handla efteråt får gå tillbaka dit.
        """
        page = self.page
        page.click('.bottom-nav-item[data-view="week"]')
        expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))
        cards = page.locator("#storeCards .store-card")
        expect(cards.first).to_be_visible(timeout=30_000)
        expect(page.locator("#shoppingCost")).not_to_contain_text("pris hämtas", timeout=30_000)
        return cards

    # ---- vaktposten: väntan själv ----
    def test_vantan_vaknar_pa_skrivningen_och_missar_inte_en_overskriven(self):
        """Att väntan väcks av skrivningen prövas i en riktig sida.

        Loopen har sina egna tester (tests/test_e2e_vantan.py, utan
        browser). Det den halvan inte kan svara på är om init-skriptet
        verkligen ligger före app.js och verkligen bokför rätt nyckel - och
        en väntan som tyst slutat se skrivningar hade sett ut precis som en
        grön svit ända tills den dagen den behövdes.
        """
        page = self.page
        with self.step("skrivboken ligger före app.js"):
            page.goto(self.app())
            # Appens egen boot-sparning måste vara bokförd. Låg skriptet
            # efter app.js vore boken tom här, och varje väntan i sviten
            # hade väntat på skrivningar den aldrig fick se.
            page.wait_for_function("() => (window.__matjaktSkrivbok || {}).nummer > 0")

        # De två fällorna prövas på landningssidan: samma origin, alltså
        # samma localStorage och samma skrivbok, men ingen app som skriver
        # i bakgrunden. Det är avsiktligt - vaktposten ska falla på väntan,
        # aldrig på vad veckan råkade göra just då.
        # domcontentloaded: landningssidans film behöver inte hämtas för att
        # localStorage ska gå att skriva i.
        page.goto(f"{self.server.base}/", wait_until="domcontentloaded")
        with self.step("en sen skrivning"):
            # Senare än något stickprovsfönster, tidigare än tystnaden.
            page.evaluate("""() => setTimeout(() => {
                localStorage.setItem("matjakt-state", JSON.stringify({ weekPlan: ["prov-sent"] }));
            }, 2000)""")
            läge = self.wait_for_state(lambda s: s.get("weekPlan") == ["prov-sent"],
                                       what="en sen skrivning")
            self.assertEqual(läge["weekPlan"], ["prov-sent"])

        with self.step("en skrivning som skrivs över i nästa andetag"):
            # Precis det pullAccountState gör med klientens egen skrivning:
            # värdet finns i en millisekund. Ett stickprov däremellan ser
            # ingenting - värdet fanns, men ingen tittade.
            page.evaluate("""() => setTimeout(() => {
                localStorage.setItem("matjakt-state", JSON.stringify({ weekPlan: ["prov-flyktig"] }));
                localStorage.setItem("matjakt-state", JSON.stringify({ weekPlan: ["prov-efterat"] }));
            }, 100)""")
            läge = self.wait_for_state(lambda s: s.get("weekPlan") == ["prov-flyktig"],
                                       what="en överskriven skrivning")
            self.assertEqual(läge["weekPlan"], ["prov-flyktig"])
            # Och lagringen står kvar på det som skrevs SIST: väntan svarade
            # om ett läge som inte längre går att läsa av.
            self.assertNotEqual(self.local_state().get("weekPlan"), ["prov-flyktig"])

        with self.step("tystnad är ett eget besked"):
            # Inte "tiden gick ut" - beskedet ska säga att appen slutade
            # skriva, och vad den skrev sist.
            with self.assertRaises(AssertionError) as fångat:
                self.wait_for_state(lambda s: s.get("weekPlan") == ["kommer-aldrig"],
                                    tystnad=1.0, what="något som aldrig skrivs")
            self.assertIn("tyst i 1 s", str(fångat.exception))
            self.assertIn("prov-efterat", str(fångat.exception))

    # ---- resan ----
    def test_full_consumer_journey(self):
        page = self.page
        email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
        recipe_id = self.any_recipe_id()

        with self.step("delad receptlänk öppnar receptet utan onboarding"):
            page.goto(self.app(f"?recept={recipe_id}"))
            expect(page.locator("#recipePage")).to_be_visible()
            # L4: receptsidan är byggd som telefon 4 i design D. Raden heter
            # .ingrrad och har mängden i en egen kolumn; .ing-row är kvar i
            # appen men hör numera till "Följer priset på", inte hit.
            expect(page.locator("#recipePage .ingrrad").first).to_be_visible()
            expect(page.locator("#onboardingModal")).to_be_hidden()

        with self.step("signup"):
            self.register(email)

        with self.step("logout och login"):
            self.logout()
            self.login(email)
            self.close_account_modal()
            # Bytesräknaren och middagstaket är GRATIS-gränser. Utan det här
            # är kontot Premium i sju dagar från sin första vecka (J3), och
            # då finns inget tak att pröva.
            self.trial_already_used()

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
            # L4: steget är en avbockningsbar rad (.steg) med sitt nummer i
            # egen kolumn. Bocken är kvar, klassen heter som i design D.
            expect(page.locator("#recipePage .steg").first).to_be_visible()
            expect(page.locator("#recipePage .steg input[type=checkbox]").first).to_be_visible()
            # Priset är bildtext under fotot, inte ett chips bland fyra andra.
            expect(page.locator("#recipePage .receptmeta")).to_contain_text("Pris per portion")
            # Mängderna kommer med detaljhämtningen (kortet i listan bär bara
            # namn) - vänta in dem i stället för att läsa mitt i. De står i
            # mängdkolumnen .mangd2, inte längre i ett <strong> i raden.
            expect(page.locator("#recipePage .ingrrad .mangd2").first).not_to_have_text("", timeout=15_000)
            amounts = page.locator("#recipePage .ingrrad .mangd2").all_inner_texts()
            self.assertTrue(any(re.search(r"\d", text) for text in amounts), amounts)
            page.click("#recipePage .recipe-back")
            expect(page.locator("#top")).to_be_visible()

        with self.step("Vecka: butikskort, Billigast, lås"):
            # G13: butiksvalet bor på Vecka. wait_for_store_cards byter vy.
            cards = self.wait_for_store_cards()
            priced = page.locator("#storeCards .store-card:not(.locked):not(.unavailable)")
            locked = page.locator("#storeCards .store-card.locked")
            self.assertEqual(priced.count(), 1, cards.all_inner_texts())     # Free ser EN butik
            self.assertEqual(locked.count(), 2, cards.all_inner_texts())     # de andra bakom Premium
            expect(priced.first).to_contain_text("Billigast")
            expect(locked.first).to_contain_text("Se pris med Premium")

        with self.step("Handla: listan först"):
            page.click('.bottom-nav-item[data-view="basket"]')
            expect(page.locator("#top")).to_have_class(re.compile(r"view-basket"))
            expect(page.locator("#shoppingList .shopping-item").first).to_be_visible()
            items_before = page.locator("#shoppingList .shopping-item").count()
            # G13: butikskorten ligger INTE kvar i Handla-skärmen.
            self.assertEqual(page.locator(".shopping-screen #storeCards").count(), 0)
            expect(page.locator("#priceSourceNote")).to_contain_text("Priser från")
            self.assertRegex(page.locator("#shoppingCost").inner_text(), r"\d+ kr / 900 kr")

        with self.step("finns hemma (ur listan) och handlad"):
            # EN VARA KAN STÅ SOM FLERA RADER. Aggregatet nycklar på namn OCH
            # enhetsfamilj, så "2 msk tomatpuré" och "140 g tomatpuré" blir två
            # rader - de går inte att summera utan en densitet. Borttagningen
            # nycklar däremot bara på NAMNET, så ett klick tar alla rader med
            # det namnet. Det är rimlig avsikt ("jag behöver inte tomatpuré"),
            # men antalet rader minskar då med mer än ett.
            #
            # Testet antog items_before - 1 och föll på main med "13 != 14" när
            # veckan råkade innehålla en dubblerad vara. Att skriva om det till
            # ett lösare antal hade dolt saken; nu räknas raderna med det
            # namnet först, och kravet är att exakt de försvinner.
            namn_att_ta_bort = page.locator("#shoppingList .shopping-item strong").nth(0).inner_text().strip()
            rader_med_namnet = page.locator("#shoppingList .shopping-item").evaluate_all(
                "(rader, namn) => rader.filter(r => (r.querySelector('strong')?.innerText || '').trim() === namn).length",
                namn_att_ta_bort)
            self.swipe_away(page.locator("#shoppingList .shopping-item").first)
            expect(page.locator("#restoreRemovedBtn")).to_contain_text("1 borttagen vara")
            expect(page.locator("#storeCardsCompareBtn")).to_have_count(0)      # Free har ingen jämförelsesida
            self.assertEqual(page.locator("#shoppingList .shopping-item").count(),
                             items_before - rader_med_namnet,
                             f"{namn_att_ta_bort!r} stod på {rader_med_namnet} rader")
            kvar = page.locator("#shoppingList .shopping-item strong").all_inner_texts()
            self.assertNotIn(namn_att_ta_bort, [t.strip() for t in kvar],
                             "den borttagna varan står kvar i listan")
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

            # U35: BORTTAGEN ÄR INTE SAMMA SAK SOM HEMMA.
            #
            # Antalet ovan utesluter den borttagna varan implicit - vore den
            # med skulle det stå tre. Men en implicit kontroll säger inte
            # VAD som gick fel när den brister, och det här är en invariant
            # med konsekvenser: en vara som tyst hamnar i skafferiet gör att
            # kommande veckor räknar bort den och underköper.
            skafferiet = page.evaluate(
                "() => [...document.querySelectorAll('#pantryList .pantry-item')]"
                ".map(e => (e.innerText || '').split('\\n')[0].trim())")
            # Två varor ska SYNAS - annars är assertionen nedan tomt sann
            # och bevisar ingenting.
            self.assertEqual(len(skafferiet), 2, f"skafferiet läste fel: {skafferiet}")
            self.assertNotIn(removed_name, skafferiet,
                             f"{removed_name!r} togs BORT ur listan men hamnade i skafferiet: {skafferiet}")
            läge = self.local_state()
            self.assertIn(removed_name, läge.get("removedItems") or [])
            self.assertNotIn(removed_name, läge.get("harHemma") or [])
            self.assertNotIn(removed_name, läge.get("avklarade") or [])

        with self.step("butiksjämförelse: Free ser spridningen, låsta butiker och paywallen"):
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
            state = self.wait_for_state(lambda s: s.get("weekPlan") == swapped_week, what="återställd vecka")
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

    # ---- den sena kontosynken ----
    #
    # HÅLLER kontosynkens svar i sidan tills testet släpper det. Skrivboken
    # (vantan.py) bokför vad appen gör; det här skriptet bestämmer NÄR ett
    # svar kommer fram - och det är hela skillnaden mellan att hoppas på ett
    # kapplöp och att köra det.
    #
    # Bara den FÖRSTA hämtningen parkeras: det är boot-radens `refreshUser()`,
    # den som app.js startar utan att vänta in innan den öppnar onboardingen.
    # Nummer tas när anropet går ut, inte när svaret kommer - flera synkar
    # ligger i luften samtidigt och `bok.antal` hinner räknas upp under tiden.
    PARKERA_KONTOSYNKEN = """
    (() => {
      const bok = { antal: 0, levererade: 0, slapp: null };
      window.__parkeradKontosynk = bok;
      const original = window.fetch;
      window.fetch = async (...args) => {
        const url = String((args[0] && args[0].url) || args[0] || "");
        const metod = ((args[1] && args[1].method) || "GET").toUpperCase();
        if (!url.includes("/api/account/state") || metod !== "GET") return original(...args);
        const nummer = ++bok.antal;
        const svar = await original(...args);
        if (nummer !== 1) return svar;
        await new Promise(klar => { bok.slapp = klar; });
        // Räknas när appen läst KROPPEN, inte när svaret lämnades ut: det är
        // raden efter som lägger blobben i tillståndet, och det är den
        // väntan nedan behöver ha bakom sig.
        const json = svar.json.bind(svar);
        svar.json = async () => { const data = await json(); bok.levererade += 1; return data; };
        return svar;
      };
    })();
    """

    def test_en_sen_kontosynk_skriver_inte_over_onboardingsvaren(self):
        """Svaren du just gav överlever en kontosynk som landar efteråt.

        Boot-raden i app.js startar `refreshUser()` UTAN att vänta in den och
        öppnar onboardingen i nästa andetag. Hämtningen av kontots blob är
        alltså i luften medan användaren skriver sina svar - och blobben är
        tagen FÖRE dem: budget 800, tomt postnummer, onboarding ogjord.
        Landade den efter svaren skrevs de över, tyst och utan att rutan på
        skärmen ändrades: fältet visade 900 medan tillståndet sa 800.

        Så såg felet ut i CI ("AssertionError: 800 != 900" i resan ovan), och
        det gick igenom vid omkörning - inte för att något lagats, utan för
        att svaret hann före nästa gång.

        Här är det inget kapplöp: svaret HÅLLS tills svaren är givna och
        släpps sedan fram. Utan grinden i applySyncBlob faller testet på
        exakt samma rad som CI föll på.
        """
        page = self.page
        email = f"e2e-sen-synk-{uuid.uuid4().hex[:8]}@example.com"

        with self.step("konto - blobben på servern är från före onboardingen"):
            # Receptlänken håller onboardingen stängd så kontot går att skapa
            # först; blobben som skrivs nu bär standardvärdena.
            page.goto(self.app(f"?recept={self.any_recipe_id()}"))
            expect(page.locator("#recipePage")).to_be_visible()
            self.register(email)
            self.close_account_modal()
            self.wait_for_server_state(lambda s: s.get("budget") == 800 and not s.get("onboardingComplete"),
                                       what="blobben före onboardingen")

        with self.step("hela onboardingen besvaras medan kontosynken hålls"):
            page.add_init_script(self.PARKERA_KONTOSYNKEN)
            page.goto(self.app())
            expect(page.locator("#onboardingModal")).to_be_visible()
            page.wait_for_function("() => (window.__parkeradKontosynk || {}).antal > 0")
            self.complete_onboarding()
            # RUTAN ÄR STÄNGD NU, och det är hela poängen: "Skapa min vecka"
            # stänger den långt innan ett sent svar landar. Det ögonblicket -
            # veckan skapas, blobben är kvar i luften - var det oskyddade.
            state = self.wait_for_state(lambda s: s.get("weekPlan"), what="veckan")
            self.assertEqual(state["budget"], 900, "appen tog inte emot svaret alls")

        with self.step("den gamla blobben släpps fram"):
            page.evaluate("() => window.__parkeradKontosynk.slapp()")
            # LEVERERAD, inte bara släppt. Hann http.js tidsgräns (15 s) före
            # oss avbröts kroppsläsningen och appen såg ett nätfel i stället
            # för en gammal blob - då har ingenting prövats, och det ska sägas
            # rakt ut i stället för att passera som grönt.
            levererad = True
            try:
                page.wait_for_function(
                    "() => (window.__parkeradKontosynk || {}).levererade >= 1", timeout=10_000)
            except Exception:                                  # noqa: BLE001
                levererad = False
            if not levererad:
                self.fail("kontosynkens blob nådde aldrig appen - parkeringen översteg"
                          " http.js REQUEST_TIMEOUT_MS och testet prövade ingenting")

        with self.step("svaren står kvar"):
            # LÄSNINGEN LIGGER EFTER BLOBBEN, utan att vänta på en klocka:
            # wait_for_function ovan är en TASK i sidan, och mikrotaskkön
            # töms före nästa task. Räknaren höjs inuti svarets json(), och
            # allt som följer på den - applySyncBlob, persistLocally - är
            # mikrotasks i samma kedja. Pollningen som ser räknaren kan alltså
            # inte köra före dem.
            state = self.local_state()
            self.assertEqual(state["budget"], 900, "den gamla blobben skrev över budgeten")
            self.assertEqual(state["postnummer"], fixture.POSTCODE)
            self.assertEqual(state["hushall"]["vuxna"], 3)
            self.assertTrue(state["onboardingComplete"])
            self.assertTrue(state["weekPlan"], "veckan som just skapades är borta")
            # Och skärmen säger samma sak som tillståndet. Budgetraden är
            # platsen där ett överskrivet värde faktiskt syns för användaren.
            page.click('.bottom-nav-item[data-view="basket"]')
            expect(page.locator("#shoppingList .shopping-item").first).to_be_visible()
            self.assertRegex(page.locator("#shoppingCost").inner_text(), r"/ 900 kr")

        self.assertEqual(self.console_errors, [])

    def test_hela_veckan_syns_utan_ett_enda_klick(self):
        """G3: sju rader syns utan att man klickar.

        "Veckans plan" var `hidden` i markupen, och koden bakom ritade
        dessutom bara fyra rader med resten bakom "Visa hela veckan". Kvar på
        skärmen fanns sju dagflikar och ETT dagskort i taget - alltså gick
        frågan appen finns för, *vad äter vi i veckan*, inte att besvara med
        ögonen. "✓ Lagad" och "✗ Hoppade över" fanns bara i den dolda listan
        och var därmed oåtkomliga.

        Testet rör ingenting efter onboardingen. Varje klick det INTE gör är
        en del av påståendet.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()

        lista = page.locator("#weekPlanList")
        expect(lista).to_be_visible()
        rader = lista.locator(".week-plan-row")
        # Sju dagar, alltid - weekPlan är bara så lång som antalet middagar
        # (fyra på Free), medan dagflikarna ovanför ritar sju. Stod det fyra
        # rader under sju flikar sa skärmen två saker om samma vecka.
        expect(rader).to_have_count(7)
        self.assertEqual(page.locator("#weekDayTabs .week-day-tab").count(), 7)

        # Veckans rätter står i listan, inte bara i dagskortet.
        state = self.wait_for_state(lambda s: s.get("weekPlan"), what="veckan")
        planerade = lista.locator(".week-plan-row:not(.is-empty)")
        expect(planerade).to_have_count(len(state["weekPlan"]))
        # ...och de planlösa dagarna behåller sin plats i stället för att
        # skjuta senare dagar uppåt (E2:s dagsindexfel i ett annat lager).
        expect(lista.locator(".week-plan-row.is-empty"))\
            .to_have_count(7 - len(state["weekPlan"]))

        # Ingen kvarglömd knapp mellan användaren och veckan.
        expect(page.locator("#weekPlanToggle")).to_have_count(0)

        # "✓ Lagad" / "✗ Hoppade över" är åtkomliga först nu.
        expect(lista.locator(".week-plan-menu").first).to_be_visible()
        lista.locator(".week-plan-menu summary").first.click()
        expect(lista.locator("[data-cooked]").first).to_be_visible()

    def test_forsta_veckan_kommer_utan_betalvagg(self):
        """G8: det dyraste avhoppet - hänglåsväggen före första måltiden.

        Onboardingens sista knapp heter "Skapa min vecka". Den öppnade
        planjämförelsen, där sju av åtta veckotyper är låsta för en
        gratisanvändare. Det FÖRSTA en ny användare såg av produkten var
        alltså en vägg av hänglås - innan hon sett en enda måltid, en enda
        prislapp eller ett enda bevis på att appen kan något.

        Testet mäter vad hon ser i det ögonblicket: en färdig vecka, inte en
        modal. Erbjudandet finns kvar, men ovanför veckan och efter den -
        sälj efter leverans, inte före.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()

        # Ingen modal, och framför allt inget hänglås: noll låsta veckotyper
        # på skärmen direkt efter sista knappen.
        expect(page.locator("#planModal")).to_be_hidden()
        self.assertEqual(page.locator("[data-plan-paywall]:visible").count(), 0)
        expect(page.locator("#paywallModal")).to_have_count(0)

        # En RIKTIG vecka, inte en tom vy som påstår sig vara en.
        state = self.wait_for_state(lambda s: s.get("weekPlan"), what="veckan")
        self.assertTrue(1 <= len(state["weekPlan"]) <= 4, state["weekPlan"])
        expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))
        page.click('#weekDayTabs [data-week-day="0"]')
        expect(page.locator("#weekTodayCard [data-week-details]")).to_be_visible()

        # Raden ovanför veckan är erbjudandet - och den leder till exakt den
        # jämförelse som förut stod i vägen.
        upsell = page.locator("#weekPlanUpsell")
        expect(upsell).to_be_visible()
        expect(upsell).to_contain_text("familjevecka")
        # OVANFÖR veckan, mätt i DOM:en - en rad under den är något annat än
        # det G8 beskriver.
        ordning = page.evaluate(
            "() => [...document.querySelectorAll('.week-overview > *')]"
            ".map(el => el.id || el.className.split(' ')[0])")
        self.assertLess(ordning.index("weekPlanUpsell"), ordning.index("weekDayTabs"), ordning)
        upsell.click()
        expect(page.locator("#planModal")).to_be_visible()
        # J3: veckotyperna är gratis, så jämförelsen är ett ERBJUDANDE om en
        # annan vecka - inte en vägg av hänglås. Raden leder fortfarande dit,
        # och där går varje kort att välja.
        expect(page.locator("[data-choose-plan]").first).to_be_visible()
        self.assertEqual(page.locator("[data-plan-paywall]").count(), 0)

    def test_postnumret_ar_inte_en_grind_fore_forsta_veckan(self):
        """G9: postnummer är ett frivilligt steg, inte en grind.

        `/^\\d{5}$/` krävdes för att passera steg 4 av 4. Ett
        integritetsmotstånd precis före det ögonblick då appen för första
        gången levererar något: den som inte ville lämna sin adress kom
        aldrig till en enda måltid.

        FALLBACK_BRANCH bär redan hela vägen utan postnummer - riksgemensamma
        Willys-priser. Testet går igenom onboardingen UTAN att röra
        postnummerfältet och kräver en färdig vecka på andra sidan.
        """
        page = self.page
        page.goto(self.app())
        modal = page.locator("#onboardingModal")
        expect(modal).to_be_visible()
        page.click("#onboardingNext")           # hushåll
        page.click("#onboardingNext")           # budget
        page.click("#onboardingNext")           # kost
        expect(page.locator("#onboardingTitle")).to_have_text("Var handlar ni?")

        # Steget säger att fältet är frivilligt och vad man avstår.
        expect(page.locator("#obPostcodeHint")).to_contain_text("riksgemensamma priser")
        expect(page.locator("#obSkipPostcode")).to_be_visible()

        # Ingenting skrivs i fältet. Knappen som lovar en vecka ska ge en.
        page.click("#onboardingNext")
        expect(modal).to_be_hidden()
        state = self.wait_for_state(lambda s: s.get("weekPlan"), what="veckan utan postnummer")
        self.assertTrue(len(state["weekPlan"]) >= 1, state["weekPlan"])
        self.assertEqual(state.get("postnummer") or "", "")
        expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))

        # ...och frågan ställs i stället där svaret gör skillnad: i Handla.
        page.click('.bottom-nav-item[data-view="basket"]')
        rad = page.locator("#basketPostcodePrompt")
        expect(rad).to_be_visible()
        expect(rad).to_contain_text("riksgemensamma")
        rad.click()
        expect(page.locator("#weekSheet")).to_be_visible()
        page.fill("#postcodeInput", fixture.POSTCODE)
        page.click("#weekSheetDone")
        # Ifyllt postnummer -> raden är borta, för alltid.
        page.click('.bottom-nav-item[data-view="basket"]')
        expect(rad).to_be_hidden()

    def test_postnumret_som_hoppas_over_ger_samma_vecka(self):
        """G9, andra halvan: "Hoppa över" är en riktig väg, inte en text.

        Knappen bredvid fältet säger vad man avstår - riksgemensamma priser
        i stället för butikerna nära dig - och ska ta exakt samma väg ut som
        "Skapa min vecka". Annars vore den ett löfte till.
        """
        page = self.page
        page.goto(self.app())
        expect(page.locator("#onboardingModal")).to_be_visible()
        for _ in range(3):
            page.click("#onboardingNext")
        expect(page.locator("#onboardingTitle")).to_have_text("Var handlar ni?")

        # Ett halvskrivet postnummer är något annat än inget: det ska inte
        # slängas tyst. En rad säger vad som saknas...
        page.fill("#obPostcode", "802")
        page.click("#onboardingNext")
        expect(page.locator("#onboardingModal")).to_be_visible()
        expect(page.locator("#obPostcodeError")).to_contain_text("fem siffror")

        # ...och "Hoppa över" går igenom ändå, med en färdig vecka.
        page.click("#obSkipPostcode")
        expect(page.locator("#onboardingModal")).to_be_hidden()
        state = self.wait_for_state(lambda s: s.get("weekPlan"), what="veckan efter hoppa över")
        self.assertTrue(len(state["weekPlan"]) >= 1, state["weekPlan"])
        expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))

    def test_installningarna_ar_en_skarm_med_allergierna_markta(self):
        """G11: skärmen appen inte hade.

        Kost och allergier - det mest säkerhetskritiska i hela appen - bodde i
        ett bottenark bakom ett OMÄRKT "＋" på 28x28 px i hörnet av
        veckokortet. Konto, hushåll, lösenord, prenumeration och radera konto
        låg i ett enda långt modalt scroll. Det fanns ingen skärm som hette
        Inställningar, och därför ingen plats där man kunde SE vad man svarat.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()

        with self.step("profilknappen leder till Inställningar"):
            page.click("#profileBtn")
            expect(page.locator("#top")).to_have_class(re.compile(r"view-settings"))
            expect(page.locator("#settingsTitle")).to_have_text("Inställningar")
            # Kontoarket ska INTE ha öppnat sig ovanpå.
            expect(page.locator("#accountModal")).to_be_hidden()

        with self.step("åtta grupper, och allergiraden märkt"):
            grupper = page.locator(".settings-group-title")
            expect(grupper).to_have_count(8)
            allergi = page.locator('[data-settings="kost"]')
            expect(allergi).to_be_visible()
            # Onboardingen hoppade över kost-steget, så raden är tom - och en
            # tom allergirad får inte se ut som en ifylld.
            expect(allergi).to_contain_text("Ej ifyllt")
            expect(allergi).to_contain_text("Inga angivna")
            # Värden ur tillståndet, inte platshållare: budgeten sattes till
            # 900 i complete_onboarding().
            expect(page.locator('[data-settings="budget"]')).to_contain_text("900 kr")

        with self.step("raden leder till stället där inställningen bor"):
            allergi.click()
            expect(page.locator("#weekSheet")).to_be_visible()
            expect(page.locator("#kosttypInput")).to_be_visible()
            page.keyboard.press("Escape")           # G6: Escape stänger arket
            expect(page.locator("#weekSheet")).to_be_hidden()

        with self.step("det man ställer in syns på skärmen efteråt"):
            page.click('[data-settings="kost"]')
            page.select_option("#kosttypInput", "vegetariskt")
            page.click("#weekSheetDone")
            expect(page.locator('[data-settings="kost"]')).to_contain_text("Vegetariskt")
            self.assertNotIn("Ej ifyllt",
                             page.locator('[data-settings="kost"]').inner_text(),
                             "raden är fortfarande märkt som tom trots att kosttyp är satt")

        with self.step("tillbaka till Ikväll"):
            page.click(".settings-screen .back-link")
            expect(page.locator("#top")).to_have_class(re.compile(r"view-home"))

    def test_skapa_min_vecka_skapar_en_vecka_inte_ett_formular(self):
        """G7: en knapp som lovar ett resultat ska leverera resultatet.

        "Skapa min vecka" öppnade planjämförelsen - ett formulär med åtta
        veckotyper, sju av dem låsta. Det är den klassiska tillitsläckan:
        knappen säger vad den ska göra, och gör något annat.

        Läget testet behöver är "ingen vecka än", och det finns på riktigt:
        den som kommer in via en DELAD RECEPTLÄNK hoppar över onboardingen,
        och då bygger starten ingen vecka åt henne. Det är exakt där knappen
        heter "Skapa min vecka".
        """
        page = self.page
        recipe_id = self.any_recipe_id()
        page.goto(self.app(f"?recept={recipe_id}"))
        expect(page.locator("#recipePage")).to_be_visible()
        page.click('.bottom-nav-item[data-view="home"]')
        expect(page.locator("#generateBtnLabel")).to_have_text("Skapa min vecka")

        page.click("#generateBtn")

        # EN FÄRDIG VECKA, inte en modal.
        expect(page.locator("#planModal")).to_be_hidden()
        self.assertEqual(page.locator("[data-plan-paywall]:visible").count(), 0)
        state = self.wait_for_state(lambda s: s.get("weekPlan"), what="veckan")
        self.assertTrue(len(state["weekPlan"]) >= 1, state["weekPlan"])
        expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))
        expect(page.locator("#weekPlanList .week-plan-row:not(.is-empty)").first).to_be_visible()

        # "Välj veckotyp" finns kvar - efter leveransen, inte före den.
        page.click('.bottom-nav-item[data-view="home"]')
        page.click("#weekSheetOpen")
        page.click("#sheetPlanBtn")
        expect(page.locator("#planModal")).to_be_visible()

    def test_onboardingen_gar_att_stanga_med_tangentbord(self):
        """G6: onboardingmodalen gick inte att stänga med tangentbord ALLS.

        Det var det FÖRSTA en ny användare mötte: ingen Escape, ingen
        fokusflytt, och tab-ordningen fortsatte rakt ner i appen bakom. Den
        som inte kan använda pekskärm hade ingen väg vidare.
        """
        page = self.page
        page.goto(self.app())
        expect(page.locator("#onboardingModal")).to_be_visible()

        # Fokus flyttas in i lagret, och appen bakom stängs av.
        self.assertTrue(page.evaluate(
            "() => document.getElementById('onboardingModal').contains(document.activeElement)"),
            "fokus flyttades aldrig in i onboardingen")
        self.assertTrue(page.evaluate(
            "() => document.querySelector('.phone-shell').hasAttribute('inert')"),
            "appen bakom onboardingen var fortfarande tabbbar")

        page.keyboard.press("Escape")
        expect(page.locator("#onboardingModal")).to_be_hidden()
        self.assertFalse(page.evaluate(
            "() => document.querySelector('.phone-shell').hasAttribute('inert')"),
            "inert låg kvar på appen efter att onboardingen stängts")

        # Escape stänger på samma villkor som "Hoppa över, jag ställer in
        # senare" - annars hade modalen smugit tillbaka vid nästa rendering
        # och Escape bara varit en paus.
        läge = self.wait_for_state(lambda s: s.get("onboardingComplete"), what="onboarding avklarad")
        self.assertTrue(läge["onboardingComplete"])

    def test_varje_modal_stangs_med_escape_och_lamnar_tillbaka_fokus(self):
        """G6:s acceptanskriterium, prövat på varje modal i appen.

        app.js hade EN Escape-lyssnare (veckoarket) och EN skrollspärr (samma
        ark). Plan-, byt-, konto-, skafferi- och laga-modalerna hade ingen
        fokusflytt vid öppning, ingen fokusfälla, ingen Escape - och
        tab-ordningen fortsatte rakt ner i sidan bakom arket.

        Fyra påståenden per modal: fokus flyttas IN, appen bakom blir inert,
        Escape stänger, och fokus kommer tillbaka till knappen som öppnade.
        Det sista är det som gör tangentbordsnavigering användbar: utan det
        landar fokus på <body> och nästa Tab börjar om från sidans topp.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()
        # Priserna klara först: veckokortet ritas om vid varje prissvar, och
        # en knapp som byts ut medan arket är öppet finns inte kvar att ge
        # fokus tillbaka till. Det är en väntan på ett lugnt läge, inte en
        # höjd timeout.
        self.wait_for_store_cards()
        # Dagfliken följer veckodagen, och en Free-vecka har fyra middagar -
        # öppnas resan en fredag står dagskortet på en tom dag och har ingen
        # "Byt"-knapp alls. Måndagen har alltid veckans första rätt.
        page.click('#weekDayTabs [data-week-day="0"]')
        expect(page.locator("#weekTodayCard [data-week-swap]")).to_be_visible()

        fall = [
            ("week", "#weekPlanUpsell", "#planModal"),
            ("week", "#weekTodayCard [data-week-swap]", "#swapModal"),
            ("home", "#weekSheetOpen", "#weekSheet"),
            ("home", "#feedbackBtn", "#feedbackSheet"),
            # G11: kontoarket nås via Inställningar-skärmen, som inte har
            # någon flik i bottennavigeringen. Det prövas separat nedan.
            ("pantry", "#addPantryBtn", "#pantryModal"),
            ("pantry", "#cookFromPantryBtn", "#cookModal"),
        ]
        for vy, öppnare, modal in fall:
            with self.step(f"{modal} stängs med Escape"):
                page.click(f'.bottom-nav-item[data-view="{vy}"]')
                page.click(öppnare)
                expect(page.locator(modal)).to_be_visible()
                self.assertTrue(page.evaluate(
                    "sel => document.querySelector(sel).contains(document.activeElement)", modal),
                    f"{modal}: fokus flyttades aldrig in i modalen")
                self.assertTrue(page.evaluate(
                    "() => document.querySelector('.phone-shell').hasAttribute('inert')"),
                    f"{modal}: appen bakom var fortfarande tabbbar")

                page.keyboard.press("Escape")
                expect(page.locator(modal)).to_be_hidden()
                self.assertTrue(page.evaluate(
                    "sel => document.activeElement === document.querySelector(sel)", öppnare),
                    f"{modal}: fokus kom inte tillbaka till {öppnare}")
                self.assertFalse(page.evaluate(
                    "() => document.querySelector('.phone-shell').hasAttribute('inert')"),
                    f"{modal}: inert låg kvar på appen efter stängning")

        with self.step("#accountModal stängs med Escape"):
            # Kontoarket nås via Inställningar (G11) och har därför ingen flik
            # i bottennavigeringen - samma fyra påståenden, egen väg dit.
            page.click("#profileBtn")
            page.click('[data-settings="konto"]')
            expect(page.locator("#accountModal")).to_be_visible()
            self.assertTrue(page.evaluate(
                "() => document.getElementById('accountModal').contains(document.activeElement)"))
            self.assertTrue(page.evaluate(
                "() => document.querySelector('.phone-shell').hasAttribute('inert')"))
            page.keyboard.press("Escape")
            expect(page.locator("#accountModal")).to_be_hidden()
            self.assertTrue(page.evaluate(
                "() => document.activeElement === document.querySelector('[data-settings=\"konto\"]')"),
                "fokus kom inte tillbaka till kontoraden i Inställningar")
            self.assertFalse(page.evaluate(
                "() => document.querySelector('.phone-shell').hasAttribute('inert')"))

    def test_handla_borjar_med_listan_och_erbjuder_hushallet(self):
        """G13: i butik, med varorna framför sig, ska listan vara det första.

        Handla började med hushållsnot, kostnadsvarning, basvarufråga, två
        priskällenoter, "Var blir det billigast?", butikskort och
        framstegsmätare - sju saker före det enda man öppnar skärmen för.
        Butiksvalet hör hemma på Vecka: var det blir billigast avgör man
        innan man går, inte när man står vid hyllan.

        Samtidigt är hushållet appens starkaste virala kanal och nämndes
        inte en enda gång. Raden överst säger det, en gång, där den betyder
        något.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()
        page.click('.bottom-nav-item[data-view="basket"]')
        expect(page.locator("#top")).to_have_class(re.compile(r"view-basket"))
        expect(page.locator("#shoppingList .shopping-item").first).to_be_visible()

        # Butiksvalet finns inte längre i Handla-skärmen - det bor på Vecka.
        for flyttat in ("#storeCards", "#storeCompareTitle", "#storeSpreadTeaser"):
            self.assertEqual(page.locator(f".shopping-screen {flyttat}").count(), 0,
                             f"{flyttat} ligger kvar i Handla")
            self.assertEqual(page.locator(f".week-screen {flyttat}").count(), 1,
                             f"{flyttat} saknas på Vecka")

        # ORDNINGEN, mätt i DOM:en: listan före allt som förklarar den.
        ordning = page.evaluate(
            "() => [...document.querySelectorAll('.shopping-screen > *')]"
            ".map(el => el.id || el.className.split(' ')[0])")
        plats = {namn: index for index, namn in enumerate(ordning)}
        self.assertIn("shoppingList", plats, ordning)
        for efter in ("shopping-progress", "weekCostAlert", "staplePrompt",
                      "priceSourceNote", "dabasNote"):
            self.assertGreater(plats[efter], plats["shoppingList"],
                               f"{efter} står före listan: {ordning}")

        # Hushållsraden: överst, och bara när inget hushåll finns.
        rad = page.locator("#basketHouseholdInvite")
        expect(rad).to_be_visible()
        expect(rad).to_contain_text("Handlar ni ihop?")
        self.assertLess(plats["basketHouseholdInvite"], plats["shoppingList"], ordning)
        rad.click()
        expect(page.locator("#accountModal")).to_be_visible()

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

    def test_platsen_i_receptlistan_overlever_ett_besok_i_ett_recept(self):
        """U65: bevara scrollposition och filter efter receptdetalj/tillbaka.

        Tillbakavägen gjorde scrollTo(0, 0) - platsen nollställdes med flit.
        Den som bläddrade i en lång receptlista fick börja om efter varje
        titt, och det är inte en saknad finess utan en aktiv nollställning.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()
        self.choose_standard_week()

        page.click('.bottom-nav-item[data-view="recipes"]')
        # Receptvyn visar HYLLOR tills något filter är satt - då tar den
        # platta listan över (recipeBrowsingMode). Filtret är alltså både
        # det som ger en scrollbar lista och "relevant tillstånd" som ska
        # överleva resan enligt kravet.
        page.select_option("#timeFilter", "45")
        expect(page.locator("#recipeScroll [data-details]").first).to_be_visible()
        page.wait_for_timeout(300)

        # Scrolla en bit ner - och kontrollera att sidan FAKTISKT flyttade
        # sig, annars mäter testet ingenting.
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(400)
        före = page.evaluate("() => Math.round(window.scrollY)")
        self.assertGreater(före, 200, "listan gick inte att scrolla - testet mäter inget")

        # Öppna ett recept som syns där man står, inte det första i listan.
        page.locator("#recipeScroll [data-details]").nth(3).click()
        expect(page.locator("#recipePage")).to_be_visible()
        # Receptet scrollar till toppen FÖRST när detaljerna hämtats och
        # sidan renderats om - vänta in tillståndet i stället för att mäta
        # mitt i. (Att mäta i flykten gav 720 px och såg ut som en bugg.)
        page.wait_for_function("() => window.scrollY < 50", timeout=10_000)

        page.click("#recipePage .recipe-back")
        expect(page.locator("#recipePage")).to_be_hidden()
        page.wait_for_timeout(600)
        efter = page.evaluate("() => Math.round(window.scrollY)")
        höjd = page.evaluate("() => window.innerHeight")

        # VAD SOM GÅR ATT KRÄVA. Exakt samma pixel går inte: bilder och
        # priser laddas efter renderingen, innehåll ovanför växer, och
        # webbläsarens scroll anchoring flyttar scrollY för att hålla BILDEN
        # stilla. Spårat: återställningen landar på 1198 av 1200 och glider
        # sedan till ~1479 utan att någon kod scrollar - det är anchoring
        # som gör sitt jobb, inte ett fel.
        #
        # Det testet ska fånga är återgången till det gamla beteendet:
        # scrollTo(0, 0), alltså kastad tillbaka till toppen. Därför krävs
        # att man fortfarande står djupt i listan och inom en skärmhöjd från
        # där man var.
        self.assertGreater(efter, före * 0.8,
                           f"kastad mot toppen: {före} px före, {efter} px efter")
        self.assertLess(abs(efter - före), höjd,
                        f"platsen tappades mer än en skärmhöjd: {före} -> {efter}")
        # Filtret ligger kvar - "relevant tillstånd" i kravet.
        self.assertEqual(page.locator("#timeFilter").input_value(), "45")

    def test_angra_veckan_ger_tillbaka_den_forra(self):
        """U09: ångra en skapad eller ändrad vecka, med förra planen bevarad.

        Koden fanns men ingen väg prövade den. Knappen är dessutom dold
        tills det finns en historik, så en trasig historik ser ut som en
        medvetet gömd knapp - och då märks felet först när någon behöver
        ångra sig.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()
        self.choose_standard_week()
        första = list(self.local_state()["valda"])
        self.assertTrue(första)

        # OBS: historiken kan redan vara icke-tom här. Hinner receptbanken bli
        # klar först efter onboardingen skapar startkoden en vecka som
        # onboardingens egen vecka sedan ersätter - en "förra vecka"
        # användaren aldrig såg. Testet mäter därför att historiken går
        # TILLBAKA till sin nivå, inte att den börjar tom.
        historik_innan = len(self.local_state().get("weekHistory") or [])

        # En ny vecka lägger den förra i historiken. Knappen bor på hemvyn,
        # och efter G7 gör den vad den heter: skapar veckan direkt i stället
        # för att öppna planjämförelsen. (choose_standard_week hanterar båda
        # lägena - den väljer i modalen om den råkar vara öppen.)
        page.click('.bottom-nav-item[data-view="home"]')
        expect(page.locator("#newWeekBtn")).to_be_visible()
        page.click("#newWeekBtn")
        self.choose_standard_week()
        andra = self.wait_for_state(lambda s: list(s.get("valda") or []) != första,
                                    what="en ny vecka")["valda"]
        self.assertNotEqual(sorted(andra), sorted(första))

        page.click('.bottom-nav-item[data-view="home"]')
        page.click("#weekSheetOpen")
        expect(page.locator("#restoreWeekBtn")).to_be_visible()
        page.click("#restoreWeekBtn")

        återställd = self.wait_for_state(
            lambda s: sorted(s.get("valda") or []) == sorted(första),
            what="förra veckan tillbaka")
        self.assertEqual(sorted(återställd["valda"]), sorted(första))
        # Historiken konsumeras - annars kunde man ångra samma vecka i evighet.
        self.assertEqual(len(återställd.get("weekHistory") or []), historik_innan)

    def test_felaktiga_startval_gar_att_andra_utan_omstart(self):
        """U04: den som svarat fel i onboardingen ska inte behöva börja om.

        Alla fyra startval - personer, middagar, postnummer och butik -
        måste gå att ändra efteråt, och ändringen ska slå igenom direkt.
        Ett val som kräver omstart är ett val användaren inte vågar göra.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()
        self.choose_standard_week()
        före = self.local_state()

        # Justera veckan nås från hemvyn - dit man kommer utan omstart.
        page.click('.bottom-nav-item[data-view="home"]')
        page.click("#weekSheetOpen")
        expect(page.locator("#weekSheet")).to_be_visible()

        # Personer och middagar: stegare, inte omstart.
        page.click("#peoplePlus")
        page.click("#mealsMinus")
        # Budget skrivs in.
        page.fill("#budgetInput", "1234")
        # Plats och butik byts i samma vy.
        page.fill("#postcodeInput", "11122")
        page.select_option("#storeInput", "Hemköp")

        efter = self.wait_for_state(
            lambda s: s.get("budget") == 1234 and s.get("postnummer") == "11122"
            and s.get("butik") == "Hemköp",
            what="ändrade startval")
        self.assertEqual(efter["personer"], före["personer"] + 1)
        self.assertEqual(efter["middagar"], före["middagar"] - 1)

        # Ingen omladdning har skett, och veckan lever kvar.
        self.assertEqual(sorted(efter.get("valda") or []), sorted(före.get("valda") or []))
        expect(page.locator("#onboardingModal")).to_be_hidden()

        # Omfattningstexten (U01) följer de nya valen direkt - beviset för
        # att ändringen slog igenom i gränssnittet, inte bara i lagringen.
        expect(page.locator("#budgetScopeNote")).to_contain_text(
            f"{efter['middagar']} middag", timeout=5_000)
        expect(page.locator("#budgetScopeNote")).to_contain_text(f"{efter['personer']} personer")

    def test_trasig_prissattning_ger_besked_inte_evig_spinner(self):
        """U05: begriplig väntestatus - och ALDRIG en ändlös spinner.

        Felet som en gång strandade varje öppen telefon står beskrivet i
        app.js: när prissättningen misslyckades låg synknyckeln kvar, varje
        senare rendering drog slutsatsen "redan hämtat", och rubriken sa
        "pris hämtas…" tills någon laddade om. Fixen finns - men inget test
        prövade den, och det är precis den sortens kod som tyst går sönder.

        Här bryts prissättningen på riktigt: anropet avvisas i nätlagret.
        Kravet är att användaren får ett BESKED inom rimlig tid, inte att
        ordet "pris hämtas…" aldrig syns - det får synas medan ett nytt
        försök pågår. Det som inte får hända är att beskedet aldrig kommer.
        """
        page = self.page
        # Nätlagret säger nej FRÅN BÖRJAN. Ingen produktionskod ändras och
        # inget mockas i appen - den möter samma sorts fel som ett tapp i
        # mobilnätet. Rutten läggs före veckan skapas, annars hinner en
        # lyckad prissättning cachas och felet visas aldrig.
        page.route("**/api/pricing/week", lambda route: route.abort())
        page.goto(self.app())
        self.complete_onboarding()
        self.choose_standard_week()
        page.click('.bottom-nav-item[data-view="basket"]')
        expect(page.locator("#shoppingList .shopping-item").first).to_be_visible()

        # Beskedet ska komma. 45 s är gott om tid även med några omförsök
        # och backoff - poängen är att det finns en ände, inte hur snabb den är.
        try:
            expect(page.locator("#shoppingCost")).to_contain_text("pris saknas just nu", timeout=45_000)
        except AssertionError as error:
            raise AssertionError(
                f"{error} | rubriken visade {page.locator('#shoppingCost').inner_text()!r}"
                f" efter 45 s - det är en ändlös spinner, inte ett besked") from None
        # Och det ska vara ett besked på svenska, inte ett HTTP-fel eller en
        # stacktrace: "inga tekniska detaljer" står uttryckligen i kravet.
        text = page.locator("#shoppingCost").inner_text()
        for teknik in ("HTTP", "Error", "undefined", "NaN", "500", "Failed"):
            self.assertNotIn(teknik, text, f"tekniskt läckage i väntestatusen: {text!r}")

        # Listan finns kvar - ett prisfel får inte ta med sig veckan i fallet.
        self.assertGreater(page.locator("#shoppingList .shopping-item").count(), 0)

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
        # Betalväggen längst ned i testet gäller ett GRATISKONTO. J3 ger sju
        # dagar Premium vid första veckan, så trialen får vara förbrukad.
        self.trial_already_used()
        self.close_account_modal()
        page.goto(self.app())
        self.complete_onboarding()
        self.choose_standard_week()
        # Butikskorten (nu på Vecka) är kvittot på att prissättningen är klar.
        self.wait_for_store_cards()
        page.click('.bottom-nav-item[data-view="basket"]')

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

        # CHIPPET visar ingrediensnamnet - renderAssumedHome skriver ut just
        # det namn den erbjöd. Det stannar kvar men byter tillstånd, det
        # försvinner inte. Antalet är ett: bara varan vi tryckte på får flippa.
        tillagt = page.locator("#assumedHomeList .assumed-chip.is-added")
        expect(tillagt).to_have_count(1)
        expect(tillagt).to_contain_text(namn)
        expect(page.locator(f'#assumedHomeList [data-assumed-add="{namn}"]')).to_have_count(0)

        # RADEN känns igen på sitt id, inte på sin text.
        #
        # extraRowMarkup visar PRODUKTENS namn när prismatchningen hittade en
        # (`match?.productName || extra.name`), och det är avsiktligt: den som
        # står i butiken ska läsa det som står på hyllan. Men veckan är
        # slumpad, så vilken vara som blir den första skiftar - och "Peppar"
        # matchar produkten "Vitpeppar" (sammansättningsregeln låter
        # "vitpeppar" svara på "peppar"). "Vitpeppar" innehåller inte "Peppar"
        # med versal, så to_contain_text(namn) föll på VECKAN, inte på ett
        # fel: CI-körning 34542092867, grön på omkörning av samma commit.
        # Mätt mot fixturen byter 2 av 35 antagna hemmavaror namn så här
        # (Peppar -> Vitpeppar, Ris -> Jasminris) och en tredje klarar sig
        # bara på att produkten börjar med ingrediensen (Buljong ->
        # Buljongtärning). Id:t är veckooberoende; namnet är det inte.
        expect(page.locator("#extraItemsSection")).to_be_visible()
        listraden = page.locator(f'#extraItemsList .extra-item:has([data-extra-check="{rad["id"]}"])')
        expect(listraden).to_be_visible()

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
        text = listraden.inner_text()
        # RADEN, inte totalen. Rubriktotalen rör sig av skäl som inte har med
        # extravaran att göra - vilken kedja som hunnit prissättas, en
        # omprissättning som landar. Att jämföra den före och efter mätte
        # brus och föll på 697 mot 503 utan att något var fel.
        # Att en oprissatt rad bidrar med 0 kr hålls fast av extrasTotal och
        # dess enhetstester; här kontrolleras att raden SÄGER det.
        if "Ingen säker prismatch" not in text:
            self.assertRegex(text, r"\d", f"prissatt rad utan synligt pris: {text!r}")
        else:
            # Utan produktmatch finns bara ingrediensens eget namn att visa,
            # och då SKA raden visa det. Gemener på båda sidor: det är
            # namnet som prövas, inte versalerna.
            self.assertIn(namn.lower(), text.lower(), f"oprissatt rad utan varunamn: {text!r}")

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

        def fake_checkout(key, customer_id, price_id, success_url, cancel_url, **kwargs):
            checkouts.append({"customer": customer_id, "price": price_id})
            return success_url
        api_server.create_checkout_session = fake_checkout

        with self.step("konto och vecka"):
            page.goto(self.app(f"?recept={self.any_recipe_id()}"))
            expect(page.locator("#recipePage")).to_be_visible()
            self.register(email)
            # Köpflödet prövas på ett konto som INTE redan har Premium: J3:s
            # aktiveringstrial hade annars gjort betalväggen osynlig.
            self.trial_already_used()
            # J5: och på ett konto vars adress är bekräftad - annars når man
            # inte checkout alls, vilket är hela poängen med den spärren.
            self.verify_email(email)
            self.close_account_modal()
            page.goto(self.app())
            self.complete_onboarding()
            self.choose_standard_week()

        with self.step("paywall från middagstaket"):
            # J3 flyttade ner veckotyperna till gratis, så det är inte längre
            # där betalväggen möter någon. Den sjätte middagen är: Free
            # planerar upp till FREE_MAX_DINNERS och servern räknar
            # recipeIds, så spärren är äkta hela vägen ner.
            page.click('.bottom-nav-item[data-view="home"]')
            page.click("#weekSheetOpen")
            paywall = page.locator("#paywallModal")
            for _ in range(8):
                if paywall.is_visible():
                    break
                page.click("#mealsPlus")
            expect(paywall).to_be_visible()
            expect(paywall).to_contain_text("Matjakt Premium")

        with self.step("ångerrätten måste kryssas i innan betalningen kan starta"):
            # B3: distansavtalslagen. Utan rutan får Premium inte levereras
            # direkt utan fjorton dagars ångerrätt - så köpet ska inte ens
            # gå att starta, och det ska SYNAS varför.
            page.click('#paywallModal [data-paywall-plan="yearly"]')
            expect(page.locator("#paywallError")).to_contain_text("ångerrätten")
            self.assertEqual(len(checkouts), 0, "en Checkout startades utan samtycke")
            expect(page.locator("#paywallModal")).to_be_visible()

        with self.step("checkout (testläge, mockad Stripe) → tillbaka i appen"):
            week_before = list(self.local_state().get("weekPlan") or [])
            self.assertTrue(week_before)
            page.check("#paywallWithdrawalConsent")
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
                                        what="veckan efter checkout")
            self.assertEqual(state.get("postnummer"), fixture.POSTCODE)

        with self.step("Premium: alla butiker prissatta och jämförelsesidan"):
            self.close_account_modal()
            page.click('.bottom-nav-item[data-view="basket"]')
            expect(page.locator("#shoppingList .shopping-item").first).to_be_visible()
            # G13: butikskorten och "Jämför butiker" bor på Vecka.
            page.click('.bottom-nav-item[data-view="week"]')
            expect(page.locator("#top")).to_have_class(re.compile(r"view-week"))
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
            self.open_account()
            expect(page.locator("#accountPremiumStatus")).to_have_text("Inget Premium ännu")
            expect(page.locator("#premiumPitch")).to_be_visible()
            self.close_account_modal()
            page.click('.bottom-nav-item[data-view="basket"]')
            self.wait_for_store_cards()
            expect(page.locator("#storeCards .store-card.locked")).to_have_count(2)

        self.assertEqual(self.console_errors, [])
        self.assertLessEqual(len(self.batch_requests), 12,
                             f"för många livepris-anrop för en Premium-resa: {len(self.batch_requests)}")

    # ---- E0: render-bussen ----
    #
    # Räknaren ersätter sättaren på Element.prototype.innerHTML och bokför
    # varje skrivning på närmaste förfader med id. Det mäter det som faktiskt
    # kostar - en rivning av ett helt DOM-träd - och inte hur många gånger en
    # funktion råkade anropas.
    RAKNARE = """
        () => {
          if (!window.__matjaktInnerHtml) {
            const beskrivning = Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML");
            window.__matjaktInnerHtml = {};
            Object.defineProperty(Element.prototype, "innerHTML", {
              configurable: true,
              enumerable: beskrivning.enumerable,
              get: beskrivning.get,
              set(värde) {
                const värd = this.closest ? this.closest("[id]") : null;
                const nyckel = värd && värd.id ? värd.id : "(utan id)";
                window.__matjaktInnerHtml[nyckel] = (window.__matjaktInnerHtml[nyckel] || 0) + 1;
                beskrivning.set.call(this, värde);
              },
            });
          }
          for (const nyckel of Object.keys(window.__matjaktInnerHtml)) delete window.__matjaktInnerHtml[nyckel];
          return true;
        }
    """
    # Behållarna som renderRecipes/renderHemRecipePreview skriver i. Hyllorna
    # och taggfiltren hör hit lika mycket som den platta listan: i normalläget
    # (ingen sökning, inga filter) är det HYLLORNA som är receptbiblioteket.
    RECEPTBEHALLARE = ("recipeScroll", "recipeShelves", "recipeTagFilters", "hemRecipePreview")

    def test_avbockning_ritar_inte_om_receptlistan(self):
        """E0: att bocka av en vara i Handla ritar om kassen - ingenting annat.

        Förr var render() sju renderare i rad, så en kryssruta i Handla rev
        ner och byggde upp hela receptbiblioteket (200+ kort med bilder) och
        band om varenda lyssnare. Det här är mätningen, inte åsikten: antalet
        skrivningar till innerHTML per behållare under exakt det klicket.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()
        self.choose_standard_week()
        self.wait_for_store_cards()
        page.click('.bottom-nav-item[data-view="basket"]')

        # Låt uppstartens hämtningar (priser, hyllor, kampanjer) landa först -
        # annars mäts deras omritningar och inte klickets.
        page.wait_for_timeout(1500)
        self.assertTrue(page.evaluate(self.RAKNARE))
        page.wait_for_timeout(500)
        i_vila = page.evaluate("() => ({ ...window.__matjaktInnerHtml })")
        brus = {namn: i_vila[namn] for namn in self.RECEPTBEHALLARE if i_vila.get(namn)}
        self.assertEqual(brus, {}, f"receptbiblioteket ritades om utan att något hände: {i_vila}")

        knappar = page.locator("#shoppingList [data-bought]")
        self.assertGreater(knappar.count(), 0, "inköpslistan hade inga varor att bocka av")
        vara = knappar.first.get_attribute("data-bought")
        page.evaluate(self.RAKNARE)
        knappar.first.click()

        # Avbockningen ska synas: varan lämnar den aktiva listan och kassen
        # ritas om. Utan den här väntan mäter testet en bildruta som inte hänt.
        page.wait_for_function("() => (window.__matjaktInnerHtml.shoppingList || 0) > 0")
        self.wait_for_state(lambda s: vara in (s.get("avklarade") or []), what=f"{vara} som avbockad")

        skrivningar = page.evaluate("() => ({ ...window.__matjaktInnerHtml })")
        ritade_om = {namn: skrivningar[namn] for namn in self.RECEPTBEHALLARE if skrivningar.get(namn)}
        self.assertEqual(ritade_om, {},
                         f"avbockningen ritade om receptbiblioteket: {ritade_om} (allt: {skrivningar})")
        # Och kassen ritades om: bussen samlar ihop, den slutar inte rita.
        # Exakt antal står inte här med flit - avbockningen slänger också
        # prissnapshotten, och omhämtningen som följer ritar kassen en gång
        # till när den landar. Det som prövas är att receptbiblioteket inte
        # följer med, inte hur många gånger kassen hinner ritas.
        self.assertGreaterEqual(skrivningar.get("shoppingList", 0), 1,
                                f"kassen ritades aldrig om: {skrivningar}")
        self.assertEqual(self.console_errors, [])

    # ---- E2: dagsindex ----
    def test_ett_saknat_recept_forskjuter_inte_veckans_dagar(self):
        """E2: en dag vars recept inte går att slå upp blir tom - inte borta.

        Ett id i veckoplanen kan sluta gå att slå upp: receptbanken hann inte
        laddas, receptet togs bort i backend, provider-recepten rensades vid
        utloggning. Förr filtrerades den dagen bort ur listan, och då sköts
        varje EFTERFÖLJANDE dag ett steg - torsdagens rätt stod på onsdagen.
        Bytesrutan räknade samtidigt i den ofiltrerade weekPlan, så de två
        sa olika saker om samma klick.
        """
        page = self.page
        page.goto(self.app())
        self.complete_onboarding()
        self.choose_standard_week()
        plan = self.local_state().get("weekPlan") or []
        self.assertGreaterEqual(len(plan), 3, f"veckan blev för kort för att pröva förskjutning: {plan}")

        # Ett id som inte finns, mitt i veckan. Resten av tillståndet rörs inte.
        page.evaluate("""
            () => {
              const lage = JSON.parse(localStorage.getItem("matjakt-state"));
              lage.weekPlan = [lage.weekPlan[0], "saknat-recept-e2e", ...lage.weekPlan.slice(1)];
              localStorage.setItem("matjakt-state", JSON.stringify(lage));
            }
        """)
        page.reload()
        page.click('.bottom-nav-item[data-view="week"]')
        expect(page.locator("#weekDayTabs .week-day-tab").first).to_be_visible()

        # Tisdagsfliken är den tomma dagen, och den säger det.
        page.click('#weekDayTabs [data-week-day="1"]')
        expect(page.locator("#weekTodayCard .week-today-empty")).to_be_visible()
        expect(page.locator('#weekDayTabs [data-week-day="1"]')).to_have_class(re.compile(r"empty"))

        # Onsdagen bär veckoplanens TREDJE id - inte tisdagens rätt uppflyttad.
        # (Namnet läses ur tillståndet, så det är planens id som avgör facit.)
        page.click('#weekDayTabs [data-week-day="2"]')
        kort = page.locator("#weekTodayCard .week-today-card")
        expect(kort).to_be_visible()
        expect(page.locator("#weekTodayCard .week-today-day")).to_have_text("onsdag")
        namn_pa_kortet = kort.locator(".week-today-info strong").first.inner_text().strip()

        # Bytesrutan är överens med kortet: samma dag, samma rätt. Det var
        # precis de två som drev isär - kortet numrerade i den filtrerade
        # listan, bytesrutan i den ofiltrerade weekPlan.
        page.click("#weekTodayCard [data-week-swap]")
        expect(page.locator("#swapModal")).to_be_visible()
        hint = page.locator("#swapModalHint").inner_text()
        self.assertIn("Ons", hint, f"bytesrutan pekade på en annan dag än kortet: {hint!r}")
        self.assertIn(namn_pa_kortet, hint,
                      f"bytesrutan pekade på en annan rätt än kortet ({namn_pa_kortet!r}): {hint!r}")

        # Den dolda "Veckans plan"-listan ritar också en rad per dag, med den
        # tomma dagen kvar på sin plats (G3 tänder listan; den ska inte tändas
        # på en förskjuten vecka).
        rader = page.locator("#weekPlanList .week-plan-row")
        self.assertGreaterEqual(rader.count(), 3)
        self.assertIn("is-empty", rader.nth(1).get_attribute("class"))
        self.assertIn("Tis", rader.nth(1).evaluate("el => el.textContent"))
        self.assertIn(namn_pa_kortet, rader.nth(2).evaluate("el => el.textContent"))

        self.assertEqual(self.console_errors, [])


if __name__ == "__main__":
    unittest.main()
