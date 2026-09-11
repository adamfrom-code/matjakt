# -*- coding: utf-8 -*-
"""J1: betalväggen prövas på servern, inte i CSS.

Tretton av sjutton premiumfunktioner var låsta enbart i klienten. `/api/v1/
recipes/by-pantry` - hela "Laga med det jag har", som säljs som full_pantry -
hade ingen entitlement-kontroll alls, och `entitlements.isPremium = true` i
devtools räckte för att låsa upp familjevecka, budgetvecka, sju middagar och
näringsfilter för hela sessionen.

Det här testet är acceptanskriteriet, och det är med flit skrivet så att
ingen kan lägga till en premiumfunktion utan att också lägga till dess
serverkontroll:

1. Mängden premiumfunktioner HÄRLEDS ur `features.FEATURES`. Ingen lista
   underhålls för hand här - flyttas en funktion mellan nivåerna följer
   testet med i samma sekund.
2. Varje premiumfunktion måste ha minst en registrerad grind
   (`services/billing/gate.py`). En funktion utan grind gör
   `unguarded_premium_features()` icke-tom, och testet faller.
3. Varje grind PRÖVAS mot en körande server med ett riktigt gratiskonto.
   Att registrera en grind utan att anropa den räcker alltså inte: vägen
   svarar då 200 och testet faller på samma ställe.
4. Samma begäran måste släppas igenom för ett premiumkonto. Utan det steget
   vore "neka alla" ett grönt test.
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()  # MATJAKT_DATA_DIR -> tempkatalog INNAN api_server importeras

import api_server  # noqa: E402
from services.accounts import AccountStore, ratelimit  # noqa: E402
from services.accounts import features as plan_features  # noqa: E402
from services.billing import gate as paywall  # noqa: E402
from services.billing.savings import SavingsStore  # noqa: E402
from services.household import HouseholdStore, NotificationStore  # noqa: E402


def _fake_week(*args, **kwargs):
    """En prissatt vecka med tre kedjor och en avgjord jämförelse. Riktig
    prisdata finns inte i en slängbar tempkatalog, och maskningen ska prövas
    på ett svar som FAKTISKT har något att maska."""
    def chain(name, total):
        return {"chain": name, "totalCheckoutCost": total, "realPriceItems": 3,
                "totalItems": 3, "comparable": True,
                "items": [{"ingredient": "mjölk", "price": total / 3}],
                "missingItemNames": []}
    return {"results": [chain("Willys", 400), chain("Hemköp", 450), chain("City Gross", 480)],
            "comparison": {"cheapestChain": "Willys", "savings": 80, "priciestTotal": 480}}


class ServerSidePaywall(unittest.TestCase):
    """Varje grind mot en riktig server, en gratisanvändare och en
    premiumanvändare."""

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
        ratelimit.reset()
        self.addCleanup(ratelimit.reset)
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        # Kontona, hushållet och sparhistoriken byts ALLA ut. J3 lade grindar
        # på hushållet, och ett hushållslager som pekar på den riktiga filen
        # medan kontona ligger i en tempkatalog gör user_id till en lott:
        # grindarna såg då andra testers hushåll.
        path = Path(self._tmpdir.name) / "paywall.db"
        self._original_stores = (api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE,
                                 api_server.NOTIFICATION_STORE, api_server.SAVINGS)
        api_server.ACCOUNT_STORE = AccountStore(path)
        api_server.HOUSEHOLD_STORE = HouseholdStore(path)
        api_server.NOTIFICATION_STORE = NotificationStore(path)
        api_server.SAVINGS = SavingsStore(api_server.ACCOUNT_STORE.connection,
                                          lock=api_server.ACCOUNT_STORE.lock)

        def restore():
            api_server.ACCOUNT_STORE.close()
            api_server.HOUSEHOLD_STORE.close()
            (api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE,
             api_server.NOTIFICATION_STORE, api_server.SAVINGS) = self._original_stores
        self.addCleanup(restore)

        # INGEN UTGÅENDE TRAFIK. Varenda väg en grind sitter på hämtar
        # annars riktiga recept eller riktiga butikspriser; premiumvarvet
        # nedan går igenom exakt samma kod som gratisvarvet.
        for target, attribute, replacement in (
            (api_server.grocery_api, "price_week", _fake_week),
            (api_server.grocery_api, "shopping_list", lambda *a, **k: {"chain": "Willys", "items": []}),
            (api_server.RECIPE_SERVICE, "search_by_pantry", lambda *a, **k: []),
            (api_server, "fetch_from_primat", lambda *a, **k: []),
            (api_server, "run_on_scrape_thread", lambda fn: None),
        ):
            patch = mock.patch.object(target, attribute, replacement)
            patch.start()
            self.addCleanup(patch.stop)
        api_server.PANTRY_RECIPE_CACHE.clear()

    # -- kontoskapande -----------------------------------------------------

    def _fresh_account(self, premium=False):
        """Ett eget konto per grind. Grindar som vaktar ett TILLSTÅND (J3:
        hushållet) ställer om kontot i sin setup, och ett delat konto hade
        låtit en grinds setup avgöra nästa grinds utfall.

        Rate limitern nollställs först: registreringstaket är fem konton i
        timmen, och det är inte det den här sviten prövar."""
        ratelimit.reset()
        return self._account(premium=premium)

    def _account(self, premium=False):
        email = f"gate-{uuid.uuid4().hex}@example.com"
        status, payload = self._post("/api/auth/register",
                                     {"email": email, "password": "hemligt123"})
        self.assertEqual(status, 201, payload)
        if premium:
            api_server.ACCOUNT_STORE.connection.execute(
                "UPDATE users SET premium = 1 WHERE email = ?", (email,))
            api_server.ACCOUNT_STORE.connection.commit()
        return payload["token"]

    # -- HTTP --------------------------------------------------------------

    def _request(self, method, path, body=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return (response.status, json.loads(raw) if raw else None,
                    response.getheader("Cache-Control") or "")
        finally:
            conn.close()

    def _post(self, path, body, token=None):
        status, payload, _ = self._request("POST", path, body, token)
        return status, payload

    def _send(self, spec, token):
        path = spec["path"]
        if spec.get("query"):
            path = f"{path}?{spec['query']}"
        return self._request(spec["method"], path, spec.get("body"), token)

    def _run_setup(self, gate, token):
        """Kör grindens `setup` (J3): begäranden som ställer kontot i det
        tillstånd grinden vaktar.

        Hushållsgrinden är skälet att det här finns. Ett nytt konto har ett
        hushåll med en medlem, och att bjuda in den ANDRA är gratis - det är
        den tredje som möter betalväggen. Utan setup gick den grinden inte
        att pröva alls, och en grind som inte går att pröva är tillbaka till
        att vara en åsikt."""
        captured, other = {}, None
        for step in gate.setup:
            body = step.get("body")
            if isinstance(body, dict):
                body = {key: captured.get(str(value)[1:], value)
                        if isinstance(value, str) and value.startswith("$") else value
                        for key, value in body.items()}
            if step.get("as") == "other":
                other = other or self._account()
                step_token = other
            else:
                step_token = token
            status, payload, _ = self._send({**step, "body": body}, step_token)
            self.assertLess(status, 400,
                            f"setup-steget {step['method']} {step['path']} för "
                            f"{gate.feature} föll: {status} {payload}")
            if step.get("capture") and isinstance(payload, dict):
                captured[step["capture"]] = payload.get(step["capture"])

    def _probe(self, gate, token=None):
        """Kör grindens egen probe. Det är grinden som beskriver hur den ska
        bevisas - beskrivningen bor på raden som utför kontrollen."""
        if gate.setup:
            if not token:
                return None, None, None   # anonym kan inte nå tillståndet alls
            self._run_setup(gate, token)
        return self._send(gate.probe, token)

    # -- 1: ingen premiumfunktion utan grind -------------------------------

    def test_no_premium_feature_is_left_unguarded(self):
        """Härledd ur FEATURES, inte ur en lista. Lägg till en premium-
        funktion utan serverkontroll och det här faller."""
        self.assertEqual(paywall.unguarded_premium_features(), set())
        # Och premiummängden är faktiskt icke-tom - annars vore raden ovan
        # grön av tomhet.
        self.assertTrue(paywall.premium_features())

    def test_every_gate_belongs_to_a_feature_that_is_actually_premium(self):
        for gate in paywall.all_gates():
            self.assertFalse(plan_features.allowed(plan_features.FREE, gate.feature),
                             f"{gate.feature} är gratis men har ändå en grind")

    # -- 2: varje grind nekar ett gratiskonto ------------------------------

    def test_every_deny_gate_refuses_a_free_account(self):
        for gate in paywall.all_gates():
            if gate.kind != paywall.DENY:
                continue
            with self.subTest(feature=gate.feature, route=gate.route):
                status, payload, _ = self._probe(gate, self._fresh_account())
                self.assertEqual(status, 403, f"{gate.route} släppte igenom Free: {payload}")
                self.assertTrue(payload.get("locked"))
                self.assertEqual(payload.get("feature"), gate.feature)

    def test_every_deny_gate_refuses_an_anonymous_caller(self):
        """Anonym är Free. Att slippa logga in får inte vara vägen runt.

        Kravet är "aldrig ett lyckat svar", inte "exakt 403": en väg som
        kräver inloggning för att ens nå det grindade tillståndet (hushållet)
        svarar 401, och 401 är minst lika stängt som 403. Det som INTE får
        hända är 2xx."""
        for gate in paywall.all_gates():
            if gate.kind != paywall.DENY:
                continue
            with self.subTest(feature=gate.feature, route=gate.route):
                status, payload, _ = self._send(gate.probe, None)
                self.assertGreaterEqual(status, 400,
                                        f"{gate.route} släppte igenom anonym: {status} {payload}")

    def test_every_mask_gate_answers_a_free_account_with_less_than_premium(self):
        """En maskad väg svarar, men inte med samma svar. Prövas mot ett
        underlag som FAKTISKT har något att maska - en prissatt vecka med tre
        kedjor, eller två inskrivna sparveckor."""
        for gate in paywall.all_gates():
            if gate.kind != paywall.MASK:
                continue
            with self.subTest(feature=gate.feature, route=gate.route):
                free_status, free_body, _ = self._probe(gate, self._fresh_account())
                paid_status, paid_body, _ = self._probe(gate, self._fresh_account(premium=True))
                self.assertEqual((free_status, paid_status), (200, 200))
                self.assertNotEqual(free_body, paid_body,
                                    f"{gate.route} gav Free exakt Premiums svar")

    # -- 3: premium släpps igenom ------------------------------------------

    def test_no_gate_blocks_a_premium_account(self):
        """"Neka alla" vore också ett grönt test. Premium ska aldrig se 403."""
        for gate in paywall.all_gates():
            with self.subTest(feature=gate.feature, route=gate.route):
                status, payload, _ = self._probe(gate, self._fresh_account(premium=True))
                self.assertNotEqual(status, 403, f"{gate.route} nekade Premium: {payload}")

    # -- 4: svaren får inte ligga i en delad cache -------------------------

    def test_a_plan_dependent_answer_is_never_publicly_cacheable(self):
        """En "public, max-age"-header på ett svar som beror på planen låter
        en mellanhand dela ut Premiums svar till nästa gratiskonto."""
        for gate in paywall.all_gates():
            with self.subTest(feature=gate.feature, route=gate.route):
                _, _, cache = self._probe(gate, self._fresh_account(premium=True))
                self.assertNotIn("public", cache,
                                 f"{gate.route} svarar Premium med delbar cache: {cache!r}")

    # -- Det som J1 pekar ut med namn --------------------------------------

    def test_by_pantry_follows_the_business_model_and_nothing_else(self):
        """J1 hittade att "Laga med det jag har" saknade kontroll helt och
        byggde grinden. J3 flyttade sedan funktionen NER till gratis - och
        då ska grinden vara borta, inte kvar och tyst nekande.

        Det är hela poängen med att härleda grindarna ur FEATURES: vägen
        följer affärsmodellen automatiskt, åt båda hållen. Testet frågar
        därför features.py vad som gäller, inte sitt eget minne."""
        free = self._fresh_account()
        path = "/api/v1/recipes/by-pantry?items=kyckling,ris"
        status, payload, _ = self._request("GET", path, token=free)
        if plan_features.allowed(plan_features.FREE, "full_pantry"):
            self.assertEqual(status, 200, payload)
            self.assertIn("recipes", payload)
            self.assertEqual(paywall.gates_for("full_pantry"), [],
                             "full_pantry är gratis men har ändå en grind kvar")
        else:
            self.assertEqual(status, 403, payload)
            self.assertEqual(payload["feature"], "full_pantry")

    def test_a_free_account_cannot_price_more_dinners_than_it_pays_for(self):
        free, premium = self._fresh_account(), self._fresh_account(premium=True)
        ids = [f"r{n}" for n in range(plan_features.FREE_MAX_DINNERS + 1)]
        status, payload = self._post("/api/pricing/week",
                                     {"recipeIds": ids, "people": 2}, token=free)
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["feature"], "seven_dinners")
        self.assertEqual(payload["maxDinners"], plan_features.FREE_MAX_DINNERS)
        # Exakt taket går igenom - spärren är ett tak, inte en avrundning.
        status, payload = self._post(
            "/api/pricing/week",
            {"recipeIds": ids[:plan_features.FREE_MAX_DINNERS], "people": 2}, token=free)
        self.assertNotEqual(status, 403, payload)
        status, payload = self._post("/api/pricing/week",
                                     {"recipeIds": ids, "people": 2}, token=premium)
        self.assertNotEqual(status, 403, payload)

    def test_the_shopping_list_is_not_a_back_door_past_the_dinner_cap(self):
        free = self._fresh_account()
        ids = [f"r{n}" for n in range(plan_features.PREMIUM_MAX_DINNERS)]
        status, payload = self._post(
            "/api/pricing/list", {"chain": "Willys", "recipeIds": ids, "people": 2}, token=free)
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["feature"], "seven_dinners")

    def test_a_free_account_cannot_price_a_premium_week_type(self):
        free = self._fresh_account()
        for key, feature in paywall.WEEK_TYPE_FEATURES.items():
            if plan_features.allowed(plan_features.FREE, feature):
                continue
            with self.subTest(week_type=key):
                status, payload = self._post(
                    "/api/pricing/week",
                    {"weekType": key, "recipeIds": ["r1"], "people": 2}, token=free)
                self.assertEqual(status, 403, payload)
                self.assertEqual(payload["feature"], feature)

    def test_the_free_week_type_is_priced_for_free(self):
        """Grinden får inte svälja standardveckan - den ÄR gratisprodukten."""
        status, payload = self._post(
            "/api/pricing/week",
            {"weekType": "standard", "recipeIds": ["r1"], "people": 2}, token=self._fresh_account())
        self.assertNotEqual(status, 403, payload)

    def test_an_unknown_week_type_unlocks_nothing(self):
        """En okänd nyckel prissätts som en standardvecka - men den får
        förstås inte heller kunna användas för att komma förbi taket."""
        free = self._fresh_account()
        status, payload = self._post(
            "/api/pricing/week",
            {"weekType": "påhittad", "recipeIds": ["r1"], "people": 2}, token=free)
        self.assertNotEqual(status, 403, payload)
        status, payload = self._post(
            "/api/pricing/week",
            {"weekType": "påhittad",
             "recipeIds": [f"r{n}" for n in range(plan_features.PREMIUM_MAX_DINNERS)],
             "people": 2}, token=free)
        self.assertEqual(status, 403, payload)

    def test_the_curated_shelves_stay_free(self):
        """Näringsfiltret är Premium; hyllorna är paketeringens
        "grundläggande" och måste fortsätta fungera utan konto."""
        status, _, _ = self._request("GET", "/api/recipes/shelves")
        self.assertEqual(status, 200)
        status, _, _ = self._request("GET", "/api/recipes?tag=barn")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
