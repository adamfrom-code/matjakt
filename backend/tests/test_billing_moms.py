# -*- coding: utf-8 -*-
"""B2: är 59 kr inklusive eller exklusive 25 % moms?

Före det här paketet visste ingen. Checkout skickade varken automatic_tax,
customer_update eller tax_id_collection, och uppstartskontrollen läste bara
beloppet - 5900 SEK/månad var "ok" oavsett om Stripe betraktade summan som
brutto eller netto. Kvittot sa ingenting, för kvitton var avstängda.

Acceptanskriteriet är den första klassen nedan: verify_stripe_prices FAILAR
när tax_behavior saknas. Resten låser att kontrollen inte går att lura åt
något håll, att checkout skickar rätt fält, och - lika viktigt - att den
INTE skickar automatic_tax innan Stripe Tax är aktiverat. Det sista är
skillnaden mellan ett paket som väntar in dashboarden och ett paket som
släcker köpknappen för alla i glappet.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.billing import StripeError, stripe_client, tax  # noqa: E402
from services.data_guard import mocked_outbound  # noqa: E402

MANAD = {"unit_amount": 5900, "currency": "sek", "active": True,
         "tax_behavior": "inclusive", "recurring": {"interval": "month"}}
AR = {"unit_amount": 39900, "currency": "sek", "active": True,
      "tax_behavior": "inclusive", "recurring": {"interval": "year"}}
TAX_AKTIV = {"active": True, "status": "active", "reason": None}


def _utan_moms(price):
    kopia = dict(price)
    kopia.pop("tax_behavior", None)
    return kopia


class VerifyStripePricesKontrollerarMoms(unittest.TestCase):
    """ACCEPTANS: verify_stripe_prices failar om tax_behavior saknas."""

    def setUp(self):
        self._sparat = (api_server.STRIPE_SECRET_KEY, api_server.STRIPE_PRICE_MONTHLY,
                        api_server.STRIPE_PRICE_YEARLY, api_server.fetch_stripe_price,
                        api_server.stripe_tax_readiness, dict(api_server.STRIPE_PRICE_CHECK))
        api_server.STRIPE_SECRET_KEY = "sk_test_b2"
        api_server.STRIPE_PRICE_MONTHLY, api_server.STRIPE_PRICE_YEARLY = "price_m", "price_y"
        api_server.stripe_tax_readiness = lambda key: dict(TAX_AKTIV)

    def tearDown(self):
        (api_server.STRIPE_SECRET_KEY, api_server.STRIPE_PRICE_MONTHLY,
         api_server.STRIPE_PRICE_YEARLY, api_server.fetch_stripe_price,
         api_server.stripe_tax_readiness, aterstall) = self._sparat
        api_server.STRIPE_PRICE_CHECK.clear()
        api_server.STRIPE_PRICE_CHECK.update(aterstall)

    def _priser(self, manad, ar):
        api_server.fetch_stripe_price = lambda key, pid: (manad if pid == "price_m" else ar)

    def test_utan_tax_behavior_underkanns_priserna(self):
        self._priser(_utan_moms(MANAD), _utan_moms(AR))
        resultat = api_server.verify_stripe_prices()
        self.assertFalse(resultat["ok"], "priser utan tax_behavior gick igenom kontrollen")
        for plan in ("monthly", "yearly"):
            self.assertIn("moms saknas", resultat["plans"][plan], plan)
        self.assertFalse(resultat["automaticTax"]["ready"])

    def test_ett_av_tva_priser_utan_moms_racker_for_underkant(self):
        self._priser(MANAD, _utan_moms(AR))
        resultat = api_server.verify_stripe_prices()
        self.assertFalse(resultat["ok"])
        self.assertEqual(resultat["plans"]["monthly"], "ok")
        self.assertIn("moms saknas", resultat["plans"]["yearly"])

    def test_exclusive_ar_ocksa_fel_for_svensk_konsumentprissattning(self):
        """Ett pris exklusive moms betyder 59 + 14,75 kr i kassan. Priser
        till konsument ska anges som totalpris."""
        exkl = dict(MANAD, tax_behavior="exclusive")
        self._priser(exkl, dict(AR, tax_behavior="exclusive"))
        resultat = api_server.verify_stripe_prices()
        self.assertFalse(resultat["ok"])
        self.assertIn("tax_behavior=exclusive", resultat["plans"]["monthly"])

    def test_ratt_konfiguration_godkanns_och_slar_pa_automatic_tax(self):
        self._priser(MANAD, AR)
        resultat = api_server.verify_stripe_prices()
        self.assertTrue(resultat["ok"], resultat["plans"])
        self.assertTrue(resultat["automaticTax"]["ready"])
        self.assertTrue(tax.automatic_tax_allowed(resultat))

    def test_priser_med_moms_men_stripe_tax_avstangt_ar_inte_klart(self):
        """Halva vägen är inte en halv förbättring: skickas automatic_tax
        till ett konto utan Stripe Tax vägrar Stripe skapa sessionen."""
        self._priser(MANAD, AR)
        api_server.stripe_tax_readiness = lambda key: {
            "active": False, "status": "pending", "reason": "Stripe Tax saknar head_office"}
        resultat = api_server.verify_stripe_prices()
        self.assertFalse(resultat["ok"])
        self.assertFalse(resultat["automaticTax"]["ready"])
        self.assertIn("head_office", resultat["automaticTax"]["reason"])
        self.assertFalse(tax.automatic_tax_allowed(resultat))


class PriceVerdictSagerVadSomArFel(unittest.TestCase):
    def test_ratt_pris_ar_ok(self):
        self.assertEqual(tax.price_verdict(MANAD, 5900, "month"), "ok")

    def test_fel_belopp_namns_fore_momsen(self):
        self.assertIn("fel pris", tax.price_verdict(dict(MANAD, unit_amount=4900), 5900, "month"))

    def test_inaktivt_pris_underkanns(self):
        self.assertIn("inaktivt", tax.price_verdict(dict(MANAD, active=False), 5900, "month"))

    def test_provperiod_underkanns(self):
        med_trial = dict(MANAD, recurring={"interval": "month", "trial_period_days": 14})
        self.assertIn("provperiod", tax.price_verdict(med_trial, 5900, "month"))

    def test_unspecified_sags_med_ord(self):
        dom = tax.price_verdict(dict(MANAD, tax_behavior="unspecified"), 5900, "month")
        self.assertIn("moms saknas", dom)
        self.assertIn("inclusive", dom)

    def test_tomt_svar_kraschar_inte(self):
        self.assertIn("fel pris", tax.price_verdict(None, 5900, "month"))


class TaxReadinessLaserStripesEgetSvar(unittest.TestCase):
    def test_active_ar_klartecken(self):
        svar = tax.tax_readiness("sk_test_x", fetch=lambda key: {"status": "active"})
        self.assertTrue(svar["active"])

    def test_pending_namner_vad_som_saknas(self):
        svar = tax.tax_readiness("sk_test_x", fetch=lambda key: {
            "status": "pending", "status_details": {"pending": {"missing_fields": ["head_office"]}}})
        self.assertFalse(svar["active"])
        self.assertIn("head_office", svar["reason"])

    def test_natfel_ar_inte_klartecken(self):
        def nere(key):
            raise StripeError("Stripe svarar inte just nu (URLError)")
        svar = tax.tax_readiness("sk_test_x", fetch=nere)
        self.assertFalse(svar["active"])
        self.assertIn("Stripe svarar inte", svar["reason"])

    def test_ovantat_undantag_stoppar_inte_uppstarten(self):
        def trasig(key):
            raise ValueError("oväntat")
        svar = tax.tax_readiness("sk_test_x", fetch=trasig)
        self.assertFalse(svar["active"])

    def test_utan_nyckel_fragas_stripe_inte_alls(self):
        def aldrig(key):
            raise AssertionError("Stripe frågades utan nyckel")
        self.assertFalse(tax.tax_readiness("", fetch=aldrig)["active"])


class CheckoutSessionenBarMomsfalten(unittest.TestCase):
    def _kropp(self, **kwargs):
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
                                                  "https://ok", "https://cancel", **kwargs)
        return fangat["body"]

    def test_adress_namn_och_momsnummer_gar_alltid_med(self):
        kropp = self._kropp()
        self.assertIn("customer_update%5Baddress%5D=auto", kropp)
        # Stripe kräver name=auto så snart tax_id_collection är på och en
        # befintlig kund skickas med - utan den avvisas hela sessionen.
        self.assertIn("customer_update%5Bname%5D=auto", kropp)
        self.assertIn("tax_id_collection%5Benabled%5D=true", kropp)

    def test_automatic_tax_skickas_nar_stripe_tax_ar_klart(self):
        self.assertIn("automatic_tax%5Benabled%5D=true", self._kropp(automatic_tax=True))

    def test_automatic_tax_skickas_inte_innan_dashboarden_ar_klar(self):
        """Annars vägrar Stripe skapa sessionen och köpknappen dör för alla
        mellan deploy och att någon hinner klicka i dashboarden."""
        self.assertNotIn("automatic_tax", self._kropp(automatic_tax=False))


class CheckoutVagenFoljerKontrollen(unittest.TestCase):
    """Kopplingen: det uppstartskontrollen kom fram till är det checkout gör."""

    def setUp(self):
        self._sparat = (api_server.STRIPE_SECRET_KEY, api_server.STRIPE_PRICE_MONTHLY,
                        api_server.create_customer, api_server.create_checkout_session,
                        dict(api_server.STRIPE_PRICE_CHECK))
        api_server.STRIPE_SECRET_KEY = "sk_test_fake"
        api_server.STRIPE_PRICE_MONTHLY = "price_m"
        self.anrop = []
        api_server.create_customer = lambda key, mail, user_id: "cus_b2"
        api_server.create_checkout_session = lambda *a, **kw: (
            self.anrop.append(kw) or "https://checkout.stripe.com/x")

    def tearDown(self):
        (api_server.STRIPE_SECRET_KEY, api_server.STRIPE_PRICE_MONTHLY,
         api_server.create_customer, api_server.create_checkout_session,
         aterstall) = self._sparat
        api_server.STRIPE_PRICE_CHECK.clear()
        api_server.STRIPE_PRICE_CHECK.update(aterstall)

    def _checkout(self):
        import http.client
        import json as _json
        import threading
        import uuid
        from http.server import ThreadingHTTPServer
        server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        port = server.server_address[1]
        trad = threading.Thread(target=server.serve_forever, daemon=True)
        trad.start()
        try:
            token, _ = api_server.ACCOUNT_STORE.register(f"b2-{uuid.uuid4().hex[:10]}@example.com", "hemligt123")
            con = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                con.request("POST", "/api/billing/checkout",
                            # B3: köpet kräver samtycke till att ångerrätten upphör.
                            body=_json.dumps({"plan": "monthly", "withdrawalConsent": True}).encode(),
                            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
                response = con.getresponse()
                response.read()
                return response.status
            finally:
                con.close()
        finally:
            server.shutdown(); server.server_close(); trad.join(timeout=5)

    def test_automatic_tax_foljer_uppstartskontrollen(self):
        api_server.STRIPE_PRICE_CHECK.clear()
        api_server.STRIPE_PRICE_CHECK.update(checked=True, ok=False,
                                             automaticTax={"ready": False, "reason": "Stripe Tax är inte aktiverat"})
        self.assertEqual(self._checkout(), 200)
        self.assertIs(self.anrop[-1]["automatic_tax"], False)

        api_server.STRIPE_PRICE_CHECK.update(ok=True, automaticTax={"ready": True, "reason": None})
        self.assertEqual(self._checkout(), 200)
        self.assertIs(self.anrop[-1]["automatic_tax"], True)


if __name__ == "__main__":
    unittest.main()
