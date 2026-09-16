# -*- coding: utf-8 -*-
"""P02c: App Store Server Notifications V2 och appens köpanmälan - mot en
riktig server, bakom flaggan.

Allt går genom HTTP mot api_server, som Apple och appen gör. Notiserna
byggs med testkedjan i apple_testkedja.py och servern får den kedjans rot
som betrodd - i drift är det Apple Root CA - G3 och ingenting annat.

Reglerna som prövas är Stripe-webhookens (B1, J5), överförda:

  * flaggan av = vägarna finns inte (404), och /api/entitlements säger av
  * SUBSCRIBED ger Premium med rätt plan; DID_RENEW flyttar slutdatumet;
    EXPIRED tar bort det; GRACE_PERIOD behåller det till respitens slut;
    REFUND släcker allt, även den manuella flaggan
  * samma notificationUUID två gånger appliceras en gång
  * en äldre notis skriver inte över en nyare
  * okänd kund: 500 och UUID:t förbrukas INTE, så Apple försöker igen
  * sandbox i produktion kvitteras utan åtgärd; på staging appliceras den
  * fel bundle-id, fel Apple ID, fel rot, saknad payload: 400
  * appens anmälan binder köpet till det inloggade kontot - och bara om
    appAccountToken är kontots
  * webben nekar en Stripe-Checkout (409) när App Store-prenumerationen lever
"""

import http.client
import json
import sys
import threading
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

HÄR = Path(__file__).resolve().parent
sys.path.insert(0, str(HÄR.parent))
sys.path.insert(0, str(HÄR))

from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()          # MATJAKT_DATA_DIR -> tempkatalog INNAN api_server importeras

import api_server  # noqa: E402
import apple_testkedja as kedja  # noqa: E402
from services.accounts import features  # noqa: E402
from services.billing import apple as billing_apple  # noqa: E402

MONTHLY = features.PRICING["monthly"]["storekitProductId"]
YEARLY = features.PRICING["yearly"]["storekitProductId"]
NU = datetime.now(timezone.utc).replace(microsecond=0)


def _om(**delta):
    return NU + timedelta(**delta)


class Bas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.chain = kedja.apple_like_chain()
        cls.annan_kedja = kedja.apple_like_chain()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)

    def setUp(self):
        self._saved = (api_server.APPLE_IAP, api_server.STRIPE_PRICE_MONTHLY)
        api_server.APPLE_IAP = replace(api_server.APPLE_IAP, enabled=True, trusted_roots=(self.chain[2].der,),
                                       accept_sandbox=False, app_apple_id=None)
        # Ett originalTransactionId per test. Det är Apples stabila nyckel
        # för EN prenumeration, och servern slår upp kontot på det först -
        # delar två tester samma id hittar det andra testet det förstas konto.
        self.otid = "2" + str(uuid.uuid4().int)[:11]

    def tearDown(self):
        api_server.APPLE_IAP, api_server.STRIPE_PRICE_MONTHLY = self._saved

    # ---- hjälpare -------------------------------------------------------
    def konto(self):
        token, _ = api_server.ACCOUNT_STORE.register(f"p02c-{uuid.uuid4().hex[:10]}@example.com", "hemligt123")
        user_id = api_server.ACCOUNT_STORE.user_id_for_token(token)
        return token, int(user_id)

    def request(self, method, path, body=None, token=None):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            con.request(method, path, body=(json.dumps(body).encode("utf-8") if body is not None else None),
                        headers=headers)
            response = con.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            con.close()

    def me(self, token):
        return self.request("GET", "/api/auth/me", token=token)[1]["user"]

    def notis(self, kind, subtype=None, *, user_id=None, otid=None, product=YEARLY, expires=None,
              environment="Production", auto_renew=1, notification_uuid=None, signed_date=None, grace_until=None,
              revocation=None, app_account_token=None, bundle_id=billing_apple.BUNDLE_ID, app_apple_id=None,
              chain=None, with_transaction=True):
        chain = chain or self.chain
        otid = otid or self.otid
        signed = signed_date if signed_date is not None else kedja.ms(NU)
        tx = {"transactionId": str(uuid.uuid4().int)[:12], "originalTransactionId": otid, "productId": product,
              "bundleId": bundle_id, "environment": environment, "type": "Auto-Renewable Subscription",
              "purchaseDate": kedja.ms(_om(days=-1)), "expiresDate": kedja.ms(expires or _om(days=30)),
              "signedDate": signed}
        token_value = app_account_token or (billing_apple.app_account_token(user_id) if user_id else None)
        if token_value:
            tx["appAccountToken"] = token_value
        if revocation:
            tx["revocationDate"] = kedja.ms(revocation)
            tx["revocationReason"] = 0
        renewal = {"originalTransactionId": otid, "autoRenewProductId": product, "productId": product,
                   "autoRenewStatus": auto_renew, "environment": environment, "signedDate": signed}
        if grace_until:
            renewal["gracePeriodExpiresDate"] = kedja.ms(grace_until)
            renewal["isInBillingRetryPeriod"] = True
        data = {"bundleId": bundle_id, "bundleVersion": "1", "environment": environment,
                "signedRenewalInfo": kedja.sign_jws(renewal, chain)}
        if with_transaction:
            data["signedTransactionInfo"] = kedja.sign_jws(tx, chain)
        if app_apple_id is not None:
            data["appAppleId"] = app_apple_id
        payload = {"notificationType": kind, "notificationUUID": notification_uuid or str(uuid.uuid4()),
                   "data": data, "version": "2.0", "signedDate": signed}
        if subtype:
            payload["subtype"] = subtype
        return kedja.sign_jws(payload, chain)

    def skicka(self, signed_payload):
        return self.request("POST", "/api/billing/apple/notifications", {"signedPayload": signed_payload})

    def transaktion(self, user_id, *, otid=None, product=MONTHLY, expires=None, environment="Production",
                    app_account_token=None, revocation=None, chain=None, kind="Auto-Renewable Subscription"):
        otid = otid or ("3" + self.otid[1:])
        tx = {"transactionId": "1", "originalTransactionId": otid, "productId": product,
              "bundleId": billing_apple.BUNDLE_ID, "environment": environment, "type": kind,
              "purchaseDate": kedja.ms(_om(days=-1)), "expiresDate": kedja.ms(expires or _om(days=30)),
              "signedDate": kedja.ms(NU)}
        token_value = app_account_token if app_account_token is not None else billing_apple.app_account_token(user_id)
        if token_value:
            tx["appAccountToken"] = token_value
        if revocation:
            tx["revocationDate"] = kedja.ms(revocation)
        return kedja.sign_jws(tx, chain or self.chain)


class FlagganAr_Av(Bas):
    def setUp(self):
        super().setUp()
        api_server.APPLE_IAP = replace(api_server.APPLE_IAP, enabled=False)

    def test_vagarna_finns_inte_och_entitlements_sager_av(self):
        token, user_id = self.konto()
        self.assertEqual(self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id))[0], 404)
        self.assertEqual(self.request("POST", "/api/billing/apple/transaction",
                                      {"jws": self.transaktion(user_id)}, token=token)[0], 404)
        self.assertEqual(self.request("GET", "/api/entitlements", token=token)[1]["apple"], {"enabled": False})
        self.assertFalse(self.me(token)["premium"])
        self.assertFalse(self.request("GET", "/api/health")[1]["appleIap"]["enabled"])


class Notiserna(Bas):
    def test_subscribed_ger_premium_med_ratt_plan(self):
        token, user_id = self.konto()
        status, svar = self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id, product=YEARLY))
        self.assertEqual((status, svar["outcome"]), (200, "applied"))
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["entitlementSource"], "apple")
        self.assertEqual(me["plan"], "premium_yearly")
        self.assertEqual(me["appleSubscription"]["status"], "active")
        self.assertTrue(me["appleSubscription"]["autoRenew"])
        self.assertTrue(self.request("GET", "/api/entitlements", token=token)[1]["isPremium"])
        self.assertTrue(self.request("GET", "/api/entitlements", token=token)[1]["features"]["all_store_prices"])

    def test_samma_uuid_tva_ganger_appliceras_en_gang(self):
        token, user_id = self.konto()
        samma = str(uuid.uuid4())
        first = self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id, notification_uuid=samma)
        self.assertEqual(self.skicka(first)[1]["outcome"], "applied")
        self.assertEqual(self.skicka(first)[1]["outcome"], "duplicate")
        # Och ett ANNAT innehåll under samma UUID ändrar inget heller.
        expired = self.notis("EXPIRED", "VOLUNTARY", user_id=user_id, notification_uuid=samma,
                             expires=_om(days=-1), signed_date=kedja.ms(_om(minutes=5)))
        self.assertEqual(self.skicka(expired)[1]["outcome"], "duplicate")
        self.assertTrue(self.me(token)["premium"])
        self.assertEqual(api_server.APPLE_NOTIFICATIONS.seen(samma)["outcome"], "applied")

    def test_did_renew_flyttar_slutdatumet(self):
        token, user_id = self.konto()
        self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id, expires=_om(days=30)))
        self.skicka(self.notis("DID_RENEW", user_id=user_id, expires=_om(days=60), signed_date=kedja.ms(_om(minutes=1))))
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["appleSubscription"]["expiresAt"], _om(days=60).isoformat())

    def test_en_aldre_notis_skriver_inte_over_en_nyare(self):
        token, user_id = self.konto()
        self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id, signed_date=kedja.ms(NU)))
        status, svar = self.skicka(self.notis("EXPIRED", "VOLUNTARY", user_id=user_id, expires=_om(days=-1),
                                              signed_date=kedja.ms(_om(hours=-2))))
        self.assertEqual((status, svar["outcome"]), (200, "ignored"))
        self.assertTrue(self.me(token)["premium"])

    def test_expired_ger_free(self):
        token, user_id = self.konto()
        self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id))
        self.skicka(self.notis("EXPIRED", "VOLUNTARY", user_id=user_id, expires=_om(minutes=-1),
                               signed_date=kedja.ms(_om(minutes=1))))
        me = self.me(token)
        self.assertFalse(me["premium"])
        self.assertEqual(me["appleSubscription"]["status"], "expired")
        self.assertIsNone(me["entitlementSource"])

    def test_grace_period_behaller_premium_till_respitens_slut(self):
        token, user_id = self.konto()
        self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id))
        self.skicka(self.notis("DID_FAIL_TO_RENEW", "GRACE_PERIOD", user_id=user_id, expires=_om(minutes=-1),
                               grace_until=_om(days=16), signed_date=kedja.ms(_om(minutes=1))))
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["appleSubscription"]["status"], "grace")
        self.assertEqual(me["entitlementUntil"], _om(days=16).isoformat())

    def test_fail_to_renew_utan_respit_ger_free(self):
        token, user_id = self.konto()
        self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id))
        self.skicka(self.notis("DID_FAIL_TO_RENEW", user_id=user_id, expires=_om(minutes=-1),
                               signed_date=kedja.ms(_om(minutes=1))))
        me = self.me(token)
        self.assertFalse(me["premium"])
        self.assertEqual(me["appleSubscription"]["status"], "billing_retry")

    def test_refund_slacker_allt_aven_den_manuella_flaggan(self):
        token, user_id = self.konto()
        api_server.ACCOUNT_STORE.connection.execute("UPDATE users SET premium = 1 WHERE id = ?", (user_id,))
        api_server.ACCOUNT_STORE.connection.commit()
        self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id))
        self.skicka(self.notis("REFUND", user_id=user_id, revocation=_om(minutes=-1), signed_date=kedja.ms(_om(minutes=1))))
        me = self.me(token)
        self.assertFalse(me["premium"])
        self.assertEqual(me["appleSubscription"]["status"], "revoked")
        self.assertIsNone(me["premiumSource"])

    def test_auto_renew_av_ar_informativt_premium_star_kvar(self):
        token, user_id = self.konto()
        self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id))
        self.skicka(self.notis("DID_CHANGE_RENEWAL_STATUS", "AUTO_RENEW_DISABLED", user_id=user_id, auto_renew=0,
                               signed_date=kedja.ms(_om(minutes=1))))
        me = self.me(token)
        self.assertTrue(me["premium"])
        self.assertEqual(me["appleSubscription"]["status"], "active")
        self.assertFalse(me["appleSubscription"]["autoRenew"])

    def test_test_notisen_kvitteras_utan_atgard(self):
        token, user_id = self.konto()
        status, svar = self.skicka(self.notis("TEST", user_id=user_id, with_transaction=False))
        self.assertEqual((status, svar["outcome"]), (200, "unhandled"))
        self.assertFalse(self.me(token)["premium"])

    def test_okand_kund_ger_500_och_forbrukar_inte_uuidt(self):
        # B1:s regel: Apple försöker igen efter 1, 12, 24, 48 och 72 timmar,
        # och under tiden hinner appens anmälan binda köpet.
        okant = str(uuid.uuid4())
        status, svar = self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", app_account_token=str(uuid.uuid4()),
                                              otid="4000000404", notification_uuid=okant))
        self.assertEqual(status, 500)
        self.assertIsNone(api_server.APPLE_NOTIFICATIONS.seen(okant), "UUID:t förbrukades - omleveransen är död")

    def test_kontot_hittas_via_originaltransaktionen_utan_token(self):
        # Kontot band köpet via appen; Apples förnyelsenotis saknar
        # appAccountToken (äldre köp) men bär originalTransactionId.
        token, user_id = self.konto()
        self.request("POST", "/api/billing/apple/transaction",
                     {"jws": self.transaktion(user_id, otid="5000000001", expires=_om(days=30))}, token=token)
        status, svar = self.skicka(self.notis("DID_RENEW", otid="5000000001", app_account_token=None,
                                              expires=_om(days=60), signed_date=kedja.ms(_om(minutes=1))))
        self.assertEqual((status, svar["outcome"]), (200, "applied"))
        self.assertEqual(self.me(token)["appleSubscription"]["expiresAt"], _om(days=60).isoformat())

    def test_sandbox_kvitteras_utan_atgard_i_produktion_men_appliceras_pa_staging(self):
        token, user_id = self.konto()
        status, svar = self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id, environment="Sandbox"))
        self.assertEqual((status, svar["outcome"]), (200, "sandbox_ignored"))
        self.assertFalse(self.me(token)["premium"])
        api_server.APPLE_IAP = replace(api_server.APPLE_IAP, accept_sandbox=True)
        status, svar = self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id, environment="Sandbox"))
        self.assertEqual((status, svar["outcome"]), (200, "applied"))
        self.assertEqual(self.me(token)["appleSubscription"]["environment"], "Sandbox")

    def test_fel_app_fel_rot_och_tom_kropp_ger_400(self):
        token, user_id = self.konto()
        self.assertEqual(self.skicka(self.notis("SUBSCRIBED", user_id=user_id, bundle_id="se.annan.app"))[0], 400)
        self.assertEqual(self.skicka(self.notis("SUBSCRIBED", user_id=user_id, chain=self.annan_kedja))[0], 400)
        self.assertEqual(self.skicka("inte.en.jws")[0], 400)
        self.assertEqual(self.request("POST", "/api/billing/apple/notifications", {})[0], 400)
        self.assertFalse(self.me(token)["premium"])

    def test_apple_id_provas_nar_det_ar_satt(self):
        token, user_id = self.konto()
        api_server.APPLE_IAP = replace(api_server.APPLE_IAP, app_apple_id="6740000000")
        self.assertEqual(self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id, app_apple_id=1235))[0], 400)
        status, svar = self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id, app_apple_id=6740000000))
        self.assertEqual((status, svar["outcome"]), (200, "applied"))
        self.assertTrue(self.me(token)["premium"])


class AppensAnmalan(Bas):
    def test_kraver_inloggning(self):
        _, user_id = self.konto()
        self.assertEqual(self.request("POST", "/api/billing/apple/transaction", {"jws": self.transaktion(user_id)})[0], 401)

    def test_ett_kop_binds_till_det_inloggade_kontot(self):
        token, user_id = self.konto()
        status, svar = self.request("POST", "/api/billing/apple/transaction",
                                    {"jws": self.transaktion(user_id, product=MONTHLY)}, token=token)
        self.assertEqual((status, svar["outcome"]), (200, "applied"))
        self.assertTrue(svar["user"]["premium"])
        self.assertEqual(svar["user"]["plan"], "premium_monthly")
        self.assertEqual(svar["user"]["entitlementSource"], "apple")
        # Idempotent: samma anmälan igen (Återställ köp) är ofarlig.
        self.assertEqual(self.request("POST", "/api/billing/apple/transaction",
                                      {"jws": self.transaktion(user_id, product=MONTHLY)}, token=token)[0], 200)

    def test_nagon_annans_kop_kan_inte_anmalas(self):
        token_a, user_a = self.konto()
        token_b, user_b = self.konto()
        # B skickar in en JWS vars appAccountToken är A:s.
        status, svar = self.request("POST", "/api/billing/apple/transaction",
                                    {"jws": self.transaktion(user_a)}, token=token_b)
        self.assertEqual(status, 400)
        self.assertIn("annat", svar["error"])
        self.assertFalse(self.me(token_b)["premium"])
        # Utan token alls, men transaktionen ägs redan av A: nekas också.
        self.request("POST", "/api/billing/apple/transaction",
                     {"jws": self.transaktion(user_a, otid="6000000001")}, token=token_a)
        status, _ = self.request("POST", "/api/billing/apple/transaction",
                                 {"jws": self.transaktion(user_b, otid="6000000001", app_account_token="")}, token=token_b)
        self.assertEqual(status, 400)

    def test_utgangen_eller_aterkallad_transaktion_ger_inte_premium(self):
        token, user_id = self.konto()
        status, svar = self.request("POST", "/api/billing/apple/transaction",
                                    {"jws": self.transaktion(user_id, expires=_om(days=-40))}, token=token)
        self.assertEqual((status, svar["status"]), (200, "expired"))
        self.assertFalse(svar["user"]["premium"])
        status, svar = self.request("POST", "/api/billing/apple/transaction",
                                    {"jws": self.transaktion(user_id, revocation=_om(hours=-1))}, token=token)
        self.assertEqual((status, svar["status"]), (200, "revoked"))
        self.assertFalse(svar["user"]["premium"])

    def test_sandbox_fel_rot_och_fel_typ_ger_400(self):
        token, user_id = self.konto()
        for jws in (self.transaktion(user_id, environment="Sandbox"),
                    self.transaktion(user_id, chain=self.annan_kedja),
                    self.transaktion(user_id, kind="Consumable")):
            self.assertEqual(self.request("POST", "/api/billing/apple/transaction", {"jws": jws}, token=token)[0], 400)
        self.assertEqual(self.request("POST", "/api/billing/apple/transaction", {}, token=token)[0], 400)
        self.assertFalse(self.me(token)["premium"])


class KontraktetMotAppen(Bas):
    def test_entitlements_bar_apple_blocket(self):
        token, user_id = self.konto()
        apple = self.request("GET", "/api/entitlements", token=token)[1]["apple"]
        self.assertTrue(apple["enabled"])
        self.assertEqual(apple["products"], {"monthly": MONTHLY, "yearly": YEARLY})
        self.assertEqual(apple["appAccountToken"], billing_apple.app_account_token(user_id))
        self.assertEqual(uuid.UUID(apple["appAccountToken"]).version, 5)
        anonym = self.request("GET", "/api/entitlements")[1]["apple"]
        self.assertTrue(anonym["enabled"])
        self.assertNotIn("appAccountToken", anonym)

    def test_webben_nekar_checkout_nar_app_store_prenumerationen_lever(self):
        token, user_id = self.konto()
        api_server.ACCOUNT_STORE.connection.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,))
        api_server.ACCOUNT_STORE.connection.commit()
        api_server.STRIPE_PRICE_MONTHLY = "price_month"
        self.skicka(self.notis("SUBSCRIBED", "INITIAL_BUY", user_id=user_id))
        status, svar = self.request("POST", "/api/billing/checkout",
                                    {"plan": "monthly", "withdrawalConsent": True}, token=token)
        self.assertEqual((status, svar["code"]), (409, "ALREADY_SUBSCRIBED"))
        self.assertIn("App Store", svar["error"])

    def test_health_visar_laget(self):
        api_server.APPLE_IAP = replace(api_server.APPLE_IAP, accept_sandbox=True, app_apple_id="1")
        self.assertEqual(self.request("GET", "/api/health")[1]["appleIap"],
                         {"enabled": True, "acceptSandbox": True, "appIdConfigured": True})


class Tillstandstabellen(unittest.TestCase):
    """state_from() mot tabellen i docs/IAP_COMPLIANCE.md (C2)."""

    def _notis(self, kind, subtype=None, **tx):
        return billing_apple.Notification(type=kind, subtype=subtype, uuid="u", signed_date=kedja.ms(NU),
                                          environment="Production", bundle_id=billing_apple.BUNDLE_ID,
                                          app_apple_id=None, transaction={"expiresDate": kedja.ms(_om(days=3)), **tx},
                                          renewal={"autoRenewStatus": 1}, version="2.0")

    def test_varje_hanterad_typ_har_en_status(self):
        for kind, status in (("SUBSCRIBED", "active"), ("DID_RENEW", "active"), ("REFUND_REVERSED", "active"),
                             ("EXPIRED", "expired"), ("GRACE_PERIOD_EXPIRED", "billing_retry"),
                             ("REFUND", "revoked"), ("REVOKE", "revoked")):
            self.assertEqual(billing_apple.state_from(self._notis(kind)).status, status, kind)
        self.assertEqual(billing_apple.state_from(self._notis("DID_FAIL_TO_RENEW", "GRACE_PERIOD")).status, "grace")
        self.assertEqual(billing_apple.state_from(self._notis("DID_FAIL_TO_RENEW")).status, "billing_retry")
        for kind in ("DID_CHANGE_RENEWAL_STATUS", "DID_CHANGE_RENEWAL_PREF", "OFFER_REDEEMED", "PRICE_INCREASE"):
            self.assertIsNone(billing_apple.state_from(self._notis(kind)).status, kind)
        for kind in ("TEST", "CONSUMPTION_REQUEST", "REFUND_DECLINED", "ONE_TIME_CHARGE", "EXTERNAL_PURCHASE_TOKEN"):
            self.assertIsNone(billing_apple.state_from(self._notis(kind)), kind)

    def test_app_account_token_ar_deterministiskt_och_per_konto(self):
        self.assertEqual(billing_apple.app_account_token(7), billing_apple.app_account_token("7"))
        self.assertNotEqual(billing_apple.app_account_token(7), billing_apple.app_account_token(8))
        self.assertEqual(uuid.UUID(billing_apple.app_account_token(7)).version, 5)


if __name__ == "__main__":
    unittest.main()
