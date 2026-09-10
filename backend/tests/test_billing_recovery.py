# -*- coding: utf-8 -*-
"""B1: en betalning får inte kunna försvinna.

Scenariot är inte hypotetiskt. Render deployar mitt i köpet: servern startar
om mellan create_customer och set_stripe_customer_id, och kunden har en
Stripe-kund vi aldrig hann skriva ner. Hon slutför Checkout, debiteras, och
webhooken kommer in för ett stripe_customer_id ingen användare har.

Tidigare svarade servern 200 på det. Stripe återlevererar aldrig ett
kvitterat event, och event-id:t låg dessutom redan i stripe_events - så när
kundraden väl skrevs och en människa försökte spela upp händelsen igen
svarade servern "duplicate" utan att någonsin ha ändrat något. Kunden blev
kvar på Free. Permanent.

Testerna nedan prövar de tre vägarna ut ur det, i den ordning de träder in:

  1. Omleverans. Okänd kund förbrukar inte event-id:t och besvaras 500, så
     Stripe fortsätter försöka i tre dygn - och andra leveransen landar.
  2. Andra spåret. Checkout bär matjakt_user_id i prenumerationens metadata
     och i client_reference_id, så FÖRSTA leveransen landar rätt även utan
     kundrad - och skriver samtidigt in kund-id:t.
  3. Avstämningen. GET /api/admin/stripe-reconcile listar de kunder som
     betalar utan att ha ett konto - de fall ingen webhook kan rädda.
"""

import hashlib
import hmac
import http.client
import json
import sys
import threading
import time
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()          # MATJAKT_DATA_DIR -> tempkatalog INNAN api_server importeras

import api_server  # noqa: E402
from services.billing import StripeError  # noqa: E402
from services.billing import reconcile  # noqa: E402

WEBHOOK_SECRET = "whsec_b1_test"


class StripeBetalningTappasInte(unittest.TestCase):

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
        self._saved = (api_server.STRIPE_WEBHOOK_SECRET, api_server.STRIPE_SECRET_KEY,
                       api_server.STRIPE_PRICE_MONTHLY, api_server.ADMIN_TOKEN)
        api_server.STRIPE_WEBHOOK_SECRET = WEBHOOK_SECRET
        api_server.STRIPE_PRICE_MONTHLY = "price_month"

    def tearDown(self):
        (api_server.STRIPE_WEBHOOK_SECRET, api_server.STRIPE_SECRET_KEY,
         api_server.STRIPE_PRICE_MONTHLY, api_server.ADMIN_TOKEN) = self._saved

    # ---- hjälpare -------------------------------------------------------
    def _konto(self):
        """(token, user_id) för ett nytt konto UTAN stripe_customer_id -
        precis det läge en kund är i när servern startade om mitt i köpet."""
        token, _ = api_server.ACCOUNT_STORE.register(f"b1-{uuid.uuid4().hex[:10]}@example.com", "hemligt123")
        user_id, _, customer_id = api_server.ACCOUNT_STORE.billing_identity_for_token(token)
        self.assertIsNone(customer_id, "kontot ska sakna kundrad från start")
        return token, user_id

    def _premium(self, token):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            con.request("GET", "/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            response = con.getresponse()
            return json.loads(response.read())["user"]
        finally:
            con.close()

    def _post_webhook(self, event):
        body = json.dumps(event).encode("utf-8")
        timestamp = int(time.time())
        signature = hmac.new(WEBHOOK_SECRET.encode(), f"{timestamp}.{body.decode()}".encode(),
                             hashlib.sha256).hexdigest()
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            con.request("POST", "/api/billing/webhook", body=body, headers={
                "Content-Type": "application/json", "Stripe-Signature": f"t={timestamp},v1={signature}"})
            response = con.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            con.close()

    def _admin_get(self, path, token):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            con.request("GET", path, headers={"X-Admin-Token": token})
            response = con.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            con.close()

    @staticmethod
    def _event(event_id, customer, **extra):
        obj = {"id": "sub_" + event_id, "customer": customer, "status": "active",
               "current_period_end": int(time.time()) + 30 * 86400, "cancel_at_period_end": False,
               "items": {"data": [{"price": {"id": "price_month"}}]}}
        obj.update(extra)
        return {"id": event_id, "created": int(time.time()), "type": "customer.subscription.created",
                "data": {"object": obj}}

    # ---- 1. ACCEPTANSKRITERIET -----------------------------------------
    def test_webhook_fore_kundraden_landar_anda_vid_andra_leveransen(self):
        """Webhooken kommer FÖRE set_stripe_customer_id - och betalningen
        landar ändå på rätt konto när Stripe levererar om."""
        token, user_id = self._konto()
        customer = f"cus_b1_{uuid.uuid4().hex[:8]}"
        event = self._event(f"evt_b1_{uuid.uuid4().hex[:8]}", customer)

        # Första leveransen: ingen användare har kund-id:t ännu.
        status, payload = self._post_webhook(event)
        self.assertEqual(status, 500, payload)
        self.assertFalse(self._premium(token)["premium"])

        # Event-id:t får INTE ha förbrukats - det är hela buggen.
        rad = api_server.ACCOUNT_STORE._connection.execute(
            "SELECT 1 FROM stripe_events WHERE event_id = ?", (event["id"],)).fetchone()
        self.assertIsNone(rad, "okänd kund förbrukade event-id:t - omleveransen blir 'duplicate'")

        # Kundraden skrivs (av en omstartad server, av avstämningen, av en
        # människa) och Stripe levererar om SAMMA event.
        api_server.ACCOUNT_STORE.set_stripe_customer_id(user_id, customer)
        status, payload = self._post_webhook(event)
        self.assertEqual(status, 200, payload)

        anvandare = self._premium(token)
        self.assertTrue(anvandare["premium"], "andra leveransen landade inte")
        self.assertEqual(anvandare["subscriptionStatus"], "active")

    # ---- 2. Andra spåret: matjakt_user_id ------------------------------
    def test_metadata_pa_prenumerationen_raddar_forsta_leveransen(self):
        token, user_id = self._konto()
        customer = f"cus_meta_{uuid.uuid4().hex[:8]}"
        event = self._event(f"evt_meta_{uuid.uuid4().hex[:8]}", customer,
                            metadata={"matjakt_user_id": str(user_id)})
        status, payload = self._post_webhook(event)
        self.assertEqual(status, 200, payload)
        self.assertTrue(self._premium(token)["premium"])
        # Kund-id:t ska ha skrivits in, så nästa händelse hittar rätt direkt.
        _, _, sparat = api_server.ACCOUNT_STORE.billing_identity_for_token(token)
        self.assertEqual(sparat, customer)

    def test_client_reference_id_raddar_forsta_leveransen(self):
        token, user_id = self._konto()
        customer = f"cus_ref_{uuid.uuid4().hex[:8]}"
        event = self._event(f"evt_ref_{uuid.uuid4().hex[:8]}", customer,
                            client_reference_id=str(user_id))
        self.assertEqual(self._post_webhook(event)[0], 200)
        self.assertTrue(self._premium(token)["premium"])

    def test_metadata_flyttar_aldrig_ett_konto_som_redan_har_en_annan_kund(self):
        """Ett konto med ett annat stripe_customer_id är en manuell fråga -
        aldrig något en webhook får skriva om på eget bevåg."""
        token, user_id = self._konto()
        api_server.ACCOUNT_STORE.set_stripe_customer_id(user_id, "cus_riktig")
        event = self._event(f"evt_kap_{uuid.uuid4().hex[:8]}", "cus_frammande",
                            metadata={"matjakt_user_id": str(user_id)})
        self.assertEqual(self._post_webhook(event)[0], 500)
        self.assertFalse(self._premium(token)["premium"])
        _, _, sparat = api_server.ACCOUNT_STORE.billing_identity_for_token(token)
        self.assertEqual(sparat, "cus_riktig")

    def test_skrap_i_metadata_ar_inget_id(self):
        for skrap in ({"matjakt_user_id": "0"}, {"matjakt_user_id": "abc"},
                      {"matjakt_user_id": ""}, {"matjakt_user_id": "-3"}, {}):
            self.assertIsNone(reconcile.matjakt_user_id({"metadata": skrap}), skrap)
        self.assertEqual(reconcile.matjakt_user_id({"metadata": {"matjakt_user_id": " 42 "}}), 42)
        self.assertEqual(reconcile.matjakt_user_id({"customer": {"metadata": {"matjakt_user_id": "7"}}}), 7)

    # ---- 3. Avstämningen ------------------------------------------------
    def test_reconcile_listar_bara_prenumerationer_utan_konto(self):
        kand, okand = "cus_kand", "cus_utan_konto"
        sidor = {"active": [{"id": "sub_1", "status": "active", "created": 10,
                             "customer": {"id": kand, "email": "kund@example.com"}},
                            {"id": "sub_2", "status": "active", "created": 20,
                             "customer": {"id": okand, "email": "tappad@example.com",
                                          "metadata": {"matjakt_user_id": "31"}}}]}

        def lista(secret_key, status="all", limit=100, starting_after=None):
            return {"data": sidor.get(status, []), "has_more": False}

        rapport = reconcile.orphan_subscriptions(
            "sk_test_x", lambda ids: {kand}, statuses=("active",), list_page=lista)
        self.assertEqual(rapport["checked"], 2)
        self.assertEqual(rapport["orphanCount"], 1)
        self.assertFalse(rapport["truncated"])
        tappad = rapport["orphans"][0]
        self.assertEqual(tappad["customerId"], okand)
        self.assertEqual(tappad["email"], "tappad@example.com")
        self.assertEqual(tappad["matjaktUserId"], 31)

    def test_reconcile_bladdrar_och_markerar_avhugget_resultat(self):
        sida = {"data": [{"id": f"sub_{i}", "status": "active", "created": i,
                          "customer": {"id": f"cus_{i}"}} for i in range(3)], "has_more": True}
        rapport = reconcile.orphan_subscriptions(
            "sk_test_x", lambda ids: set(), statuses=("active",),
            list_page=lambda *a, **k: sida)
        self.assertTrue(rapport["truncated"], "avhugget resultat måste synas, inte gissas")
        self.assertEqual(rapport["checked"], 3 * reconcile.MAX_PAGES)

    def test_known_stripe_customer_ids_svarar_bara_om_de_id_som_fragades(self):
        token, user_id = self._konto()
        api_server.ACCOUNT_STORE.set_stripe_customer_id(user_id, "cus_finns")
        svar = api_server.ACCOUNT_STORE.known_stripe_customer_ids(["cus_finns", "cus_finns_inte", None])
        self.assertEqual(svar, {"cus_finns"})
        self.assertEqual(api_server.ACCOUNT_STORE.known_stripe_customer_ids([]), set())

    def test_reconcile_vagen_ar_admin_gated_och_osynlig_utan_token(self):
        api_server.ADMIN_TOKEN = "admin-b1"
        api_server.STRIPE_SECRET_KEY = "sk_test_fake"
        status, payload = self._admin_get("/api/admin/stripe-reconcile", "fel-token")
        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "Okänd endpoint"})

    def test_reconcile_vagen_svarar_med_avstamningen_for_admin(self):
        api_server.ADMIN_TOKEN = "admin-b1"
        api_server.STRIPE_SECRET_KEY = "sk_test_fake"
        original = api_server.stripe_orphan_subscriptions
        api_server.stripe_orphan_subscriptions = lambda key, known: {
            "checked": 1, "orphanCount": 1, "truncated": False, "statuses": ["active"],
            "orphans": [{"subscriptionId": "sub_x", "customerId": "cus_x", "status": "active",
                         "created": 1, "email": "x@example.com", "matjaktUserId": None}]}
        try:
            status, payload = self._admin_get("/api/admin/stripe-reconcile", "admin-b1")
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["orphanCount"], 1)
            self.assertEqual(payload["orphans"][0]["customerId"], "cus_x")
        finally:
            api_server.stripe_orphan_subscriptions = original

    def test_reconcile_utan_stripe_nyckel_sager_det_i_stallet_for_att_krascha(self):
        api_server.ADMIN_TOKEN = "admin-b1"
        api_server.STRIPE_SECRET_KEY = ""
        status, payload = self._admin_get("/api/admin/stripe-reconcile", "admin-b1")
        self.assertEqual(status, 503)
        self.assertIn("error", payload)

    def test_reconcile_vidarebefordrar_stripe_fel_som_502(self):
        api_server.ADMIN_TOKEN = "admin-b1"
        api_server.STRIPE_SECRET_KEY = "sk_test_fake"
        original = api_server.stripe_orphan_subscriptions

        def nere(key, known):
            raise StripeError("Stripe svarar inte just nu (URLError)")
        api_server.stripe_orphan_subscriptions = nere
        try:
            status, payload = self._admin_get("/api/admin/stripe-reconcile", "admin-b1")
            self.assertEqual(status, 502)
            self.assertIn("Stripe svarar inte", payload["error"])
        finally:
            api_server.stripe_orphan_subscriptions = original


class CheckoutBarMatjaktUserId(unittest.TestCase):
    """Andra spåret måste faktiskt skickas till Stripe - annars finns det
    ingen metadata att rädda betalningen med."""

    def test_checkout_sessionen_bar_user_id_pa_prenumerationen(self):
        from unittest.mock import patch
        from services.billing import stripe_client
        from services.data_guard import mocked_outbound
        fangat = {}

        class _Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"url": "https://checkout.stripe.com/x"}'

        def fake_urlopen(req, timeout=None):
            fangat["body"] = req.data.decode("utf-8")
            return _Response()

        with mocked_outbound(), patch.object(stripe_client.urllib.request, "urlopen", fake_urlopen):
            stripe_client.create_checkout_session("sk_test_x", "cus_1", "price_m",
                                                  "https://ok", "https://cancel", user_id=99)
        kropp = fangat["body"]
        self.assertIn("client_reference_id=99", kropp)
        self.assertIn("subscription_data%5Bmetadata%5D%5Bmatjakt_user_id%5D=99", kropp)


if __name__ == "__main__":
    unittest.main()
