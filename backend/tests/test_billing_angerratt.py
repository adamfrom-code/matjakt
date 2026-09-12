# -*- coding: utf-8 -*-
"""B3: ångerrätten i köpflödet.

Lag (2005:59) om distansavtal ger konsumenten fjorton dagars ångerrätt. För
en digital tjänst som levereras direkt gäller undantaget i 2 kap. 11 § p. 11
bara om kunden uttryckligen samtyckt till att leveransen påbörjas OCH
godkänt att ångerrätten därmed upphör. Ingen sådan ruta fanns någonstans:
varje kund kunde använda Premium i tretton dagar och kräva hela pengarna
tillbaka, och vi hade inget att invända.

ACCEPTANS: checkout går inte att starta utan sparat samtycke.

Det prövas i båda riktningarna. Att köpet fungerar med samtycke säger
ingenting om det inte också visas att det stoppas utan - och att det som
avgör är vad som står i DATABASEN, inte vad klienten råkade skicka med.
"""

import http.client
import json
import sys
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.billing import withdrawal  # noqa: E402


class AngerrattenKravsForCheckout(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)

    def setUp(self):
        self._sparat = (api_server.STRIPE_SECRET_KEY, api_server.STRIPE_PRICE_MONTHLY,
                        api_server.STRIPE_PRICE_YEARLY, api_server.create_customer,
                        api_server.create_checkout_session)
        api_server.STRIPE_SECRET_KEY = "sk_test_fake"
        api_server.STRIPE_PRICE_MONTHLY, api_server.STRIPE_PRICE_YEARLY = "price_m", "price_y"
        self.sessioner = []
        api_server.create_customer = lambda key, mail, user_id: f"cus_b3_{user_id}"
        api_server.create_checkout_session = lambda *a, **kw: (
            self.sessioner.append(kw) or "https://checkout.stripe.com/b3")

    def tearDown(self):
        (api_server.STRIPE_SECRET_KEY, api_server.STRIPE_PRICE_MONTHLY,
         api_server.STRIPE_PRICE_YEARLY, api_server.create_customer,
         api_server.create_checkout_session) = self._sparat

    # ---- hjälpare -------------------------------------------------------
    def _konto(self):
        email = f"b3-{uuid.uuid4().hex[:10]}@example.com"
        token, _ = api_server.ACCOUNT_STORE.register(email, "hemligt123")
        user_id, _, _ = api_server.ACCOUNT_STORE.billing_identity_for_token(token)
        # J5 kräver verifierad adress före köp. Det är inte vad B3 prövar -
        # spärren som ska falla här är ångerrätten, inte adressen.
        api_server.ACCOUNT_STORE.connection.execute(
            "UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))
        api_server.ACCOUNT_STORE.connection.commit()
        return token, user_id

    def _checkout(self, token, **kropp):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            con.request("POST", "/api/billing/checkout", body=json.dumps({"plan": "monthly", **kropp}).encode(),
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
            response = con.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            con.close()

    def _get(self, path, token=None):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            con.request("GET", path, headers={"Authorization": f"Bearer {token}"} if token else {})
            response = con.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            con.close()

    # ---- ACCEPTANSKRITERIET --------------------------------------------
    def test_checkout_gar_inte_att_starta_utan_sparat_samtycke(self):
        token, user_id = self._konto()

        status, payload = self._checkout(token)
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["code"], withdrawal.ERROR_CODE)
        self.assertEqual(self.sessioner, [], "en Checkout-session skapades utan samtycke")
        # Ingenting sparat på kontot heller - det är samma sanning.
        self.assertIsNone(api_server.ACCOUNT_STORE.withdrawal_consent(user_id)["at"])

        # Med kryssrutan i: samtycket sparas med tidsstämpel, och köpet går.
        status, payload = self._checkout(token, withdrawalConsent=True)
        self.assertEqual(status, 200, payload)
        self.assertEqual(len(self.sessioner), 1)
        sparat = api_server.ACCOUNT_STORE.withdrawal_consent(user_id)
        self.assertIsNotNone(sparat["at"], "samtycket sparades inte")
        self.assertEqual(sparat["version"], withdrawal.VERSION)

    def test_ett_falskt_varde_ar_inte_ett_samtycke(self):
        """En kryssruta som inte är ikryssad skickar false. Den får inte
        behandlas som "fältet fanns med, alltså ja"."""
        token, _ = self._konto()
        for varde in (False, None, "", "ja", 1, "true"):
            with self.subTest(varde=varde):
                status, payload = self._checkout(token, withdrawalConsent=varde)
                self.assertEqual(status, 400, f"{varde!r} godtogs som samtycke: {payload}")
        self.assertEqual(self.sessioner, [])

    def test_sanningen_lases_ur_databasen_inte_ur_begaran(self):
        """Ett sparat samtycke räcker för nästa köpförsök - och ett konto
        utan sparat samtycke kommer inte förbi genom att fältet utelämnas."""
        token, user_id = self._konto()
        api_server.ACCOUNT_STORE.record_withdrawal_consent(user_id, withdrawal.VERSION)
        status, payload = self._checkout(token)                 # inget fält alls
        self.assertEqual(status, 200, payload)

    def test_samtycke_till_en_aldre_ordalydelse_racker_inte(self):
        """Ändras texten är det ett nytt samtycke. Ett sparat ja till en
        äldre formulering bevisar ingenting om den nya."""
        token, user_id = self._konto()
        api_server.ACCOUNT_STORE.record_withdrawal_consent(user_id, withdrawal.VERSION - 1)
        status, payload = self._checkout(token)
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["code"], withdrawal.ERROR_CODE)
        # ... och frågan går att ställa om: rutan följer med i felsvaret.
        self.assertEqual(payload["withdrawal"]["text"], withdrawal.TEXT)
        self.assertEqual(payload["withdrawal"]["version"], withdrawal.VERSION)

    def test_tidsstampeln_skrivs_om_vid_nasta_kop(self):
        """Beviset ska svara på "när godkände hon DET HÄR köpet", inte "när
        klickade hon första gången någonsin"."""
        token, user_id = self._konto()
        forsta = api_server.ACCOUNT_STORE.record_withdrawal_consent(user_id, withdrawal.VERSION)
        self.assertEqual(self._checkout(token, withdrawalConsent=True)[0], 200)
        andra = api_server.ACCOUNT_STORE.withdrawal_consent(user_id)["at"]
        self.assertGreaterEqual(andra, forsta)

    def test_utloggad_kommer_inte_forbi_via_samtyckesfaltet(self):
        status, _ = self._checkout("inte-en-token", withdrawalConsent=True)
        self.assertIn(status, (400, 401))
        self.assertEqual(self.sessioner, [])

    # ---- texten bor på ETT ställe ---------------------------------------
    def test_entitlements_bar_samma_text_som_servern_kraver(self):
        status, payload = self._get("/api/entitlements")
        self.assertEqual(status, 200)
        self.assertEqual(payload["withdrawal"]["text"], withdrawal.TEXT)
        self.assertEqual(payload["withdrawal"]["version"], withdrawal.VERSION)
        self.assertTrue(payload["withdrawal"]["note"])

    def test_texten_sager_bada_de_saker_lagen_kraver(self):
        """Undantaget kräver TVÅ saker: samtycke till att leveransen börjar
        direkt, och godkännande av att ångerrätten därmed upphör. En text
        som bara säger det ena bär inte undantaget."""
        self.assertIn("direkt", withdrawal.TEXT)
        self.assertIn("ångerrätt", withdrawal.TEXT)
        self.assertIn("upphör", withdrawal.TEXT)

    def test_consent_is_current_ar_inte_lattlurad(self):
        self.assertTrue(withdrawal.consent_is_current(withdrawal.VERSION))
        for skrap in (None, "", "ja", 0, withdrawal.VERSION + 1, withdrawal.VERSION - 1, [], {}):
            self.assertFalse(withdrawal.consent_is_current(skrap), repr(skrap))


if __name__ == "__main__":
    unittest.main()
