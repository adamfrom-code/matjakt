# -*- coding: utf-8 -*-
"""B2b: OSS-kontrollen - den första kunden utanför Sverige.

B2 kontrollerade prisobjekten (`tax_behavior: inclusive`) och kontots
skatteinställningar (Stripe Tax aktivt). Den läste aldrig KUNDERNAS adresser.

Prenumerationen går att köpa från vilket EU-land som helst, och då gäller
köparlandets momssats via One Stop Shop. Stripe Tax räknar rätt sats av sig
självt - men OSS-registreringen görs hos Skatteverket, och den finns inte
förrän Adam gjort den. Utan den här kontrollen hade den första tyska kunden
varit osynlig tills en granskning hittade henne, med retroaktiv moms i ett
land vi inte var registrerade i.

ACCEPTANSKRITERIET, ORDAGRANT

En betalande kund med adress `DE` ska få kontrollen att LARMA. Med `SE` ska
den TIGA. Det är `test_a_german_paying_customer_raises_the_alarm` och
`test_a_swedish_paying_customer_is_silent`.

INGEN UTGÅENDE TRAFIK: Stripes svar skickas in som en funktion, precis som i
avstämningen (services/billing/reconcile.py). Sviten har en gång i tiden
skapat riktiga kunder hos Stripe; det får inte hända igen.
"""

import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.billing import oss  # noqa: E402


def subscription(sub_id, *, country=None, status="active", email="kund@example.com",
                 shipping_country=None, tax_country=None, created=1):
    """En prenumeration med kunden EXPANDERAD, som list_subscriptions ger den."""
    customer = {"id": f"cus_{sub_id}", "email": email}
    if country is not None:
        customer["address"] = {"country": country, "city": "Gävle"}
    if shipping_country is not None:
        customer["shipping"] = {"address": {"country": shipping_country}}
    if tax_country is not None:
        customer["tax"] = {"location": {"country": tax_country}}
    return {"id": sub_id, "status": status, "customer": customer, "created": created}


def pages(*rows_per_status):
    """En list_subscriptions-dubbel. Varje status får sin egen sida."""
    by_status = {}
    for status, rows in rows_per_status:
        by_status.setdefault(status, []).extend(rows)

    def list_page(secret_key, status="all", limit=100, starting_after=None):
        return {"data": by_status.get(status, []), "has_more": False}

    return list_page


class Acceptanskriteriet(unittest.TestCase):
    """DE larmar, SE tiger. Allt annat i filen är kringfall."""

    def test_a_german_paying_customer_raises_the_alarm(self):
        report = oss.foreign_customers(
            "sk_test_x", list_page=pages(("active", [subscription("sub_de", country="DE")])))
        self.assertTrue(report["alarm"])
        self.assertEqual(report["foreignCount"], 1)
        self.assertEqual(report["countries"], ["DE"])
        self.assertEqual(report["foreign"][0]["customerId"], "cus_sub_de")
        # Och meningen säger vad Adam ska göra åt det.
        self.assertIn("DE", report["reason"])
        self.assertIn("OSS", report["reason"])

    def test_a_swedish_paying_customer_is_silent(self):
        report = oss.foreign_customers(
            "sk_test_x", list_page=pages(("active", [subscription("sub_se", country="SE")])))
        self.assertFalse(report["alarm"])
        self.assertEqual(report["foreignCount"], 0)
        self.assertEqual(report["countries"], [])
        self.assertIsNone(report["reason"])
        self.assertEqual(report["checked"], 1)


class VilkaKunderSomRaknas(unittest.TestCase):
    def test_only_paying_customers_count(self):
        """En avslutad prenumeration i Tyskland är ingen pågående
        OSS-skyldighet."""
        report = oss.foreign_customers(
            "sk_test_x",
            list_page=pages(("canceled", [subscription("sub_gammal", country="DE",
                                                       status="canceled")])))
        self.assertFalse(report["alarm"])
        self.assertEqual(report["checked"], 0, "en canceled-prenumeration lästes ändå")

    def test_past_due_and_trialing_count_too(self):
        """Samma mängd som avstämningen i B1: levande nog att äga kontot."""
        for status in ("trialing", "past_due"):
            with self.subTest(status=status):
                report = oss.foreign_customers(
                    "sk_test_x",
                    list_page=pages((status, [subscription("sub_x", country="FI", status=status)])))
                self.assertTrue(report["alarm"])

    def test_an_unknown_address_is_not_an_alarm_but_is_counted(self):
        """Vi kan inte påstå att en kund är utländsk för att fältet är tomt.
        Men en växande siffra betyder att adressen inte sparas - och det är
        en annan sak att åtgärda."""
        report = oss.foreign_customers(
            "sk_test_x", list_page=pages(("active", [subscription("sub_tom")])))
        self.assertFalse(report["alarm"])
        self.assertEqual(report["unknownCountry"], 1)

    def test_a_lowercase_country_is_the_same_country(self):
        report = oss.foreign_customers(
            "sk_test_x", list_page=pages(("active", [subscription("sub_se", country="se")])))
        self.assertFalse(report["alarm"])

    def test_several_countries_are_listed_once_each_and_sorted(self):
        report = oss.foreign_customers("sk_test_x", list_page=pages(("active", [
            subscription("s1", country="DE"), subscription("s2", country="NO"),
            subscription("s3", country="DE"), subscription("s4", country="SE"),
            subscription("s5", country="DK")])))
        self.assertEqual(report["countries"], ["DE", "DK", "NO"])
        self.assertEqual(report["foreignCount"], 4)


class VarLandetLases(unittest.TestCase):
    """Tre källor, i sanningsordning."""

    def test_the_billing_address_comes_first(self):
        self.assertEqual(oss.customer_country(
            subscription("s", country="SE", shipping_country="DE", tax_country="FI")), "SE")

    def test_shipping_is_the_fallback_for_older_customers(self):
        self.assertEqual(oss.customer_country(
            subscription("s", shipping_country="DE")), "DE")

    def test_stripes_own_tax_location_is_the_last_word(self):
        """Den bedömningen är det som FAKTISKT avgjorde momssatsen på
        fakturan."""
        self.assertEqual(oss.customer_country(subscription("s", tax_country="DE")), "DE")

    def test_nothing_at_all_is_none(self):
        self.assertIsNone(oss.customer_country(subscription("s")))
        self.assertIsNone(oss.customer_country({}))
        self.assertIsNone(oss.customer_country({"customer": "cus_bara_id"}))


class NarKontrollenInteGarAttGora(unittest.TestCase):
    def test_a_truncated_listing_says_so(self):
        """En tom lista av fel skäl är värre än ingen lista."""
        def endless(secret_key, status="all", limit=100, starting_after=None):
            return {"data": [subscription(f"s{status}", country="SE")], "has_more": True}

        report = oss.foreign_customers("sk_test_x", statuses=("active",), list_page=endless)
        self.assertTrue(report["truncated"])
        self.assertIn("ofullständig", report["reason"])

    def test_unavailable_never_alarms(self):
        """Ett nätfel mot Stripe är inte en tysk kund."""
        report = oss.unavailable("Stripe svarar inte")
        self.assertFalse(report["alarm"])
        self.assertFalse(report["available"])
        self.assertEqual(report["reason"], "Stripe svarar inte")


class KontrollrummetOchHalsan(unittest.TestCase):
    """Hela vägen: /api/admin/stripe-check och /api/health."""

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
        from services.accounts import ratelimit
        ratelimit.reset()
        self.addCleanup(ratelimit.reset)
        self._check = dict(api_server.STRIPE_PRICE_CHECK)

        def restore():
            api_server.STRIPE_PRICE_CHECK.clear()
            api_server.STRIPE_PRICE_CHECK.update(self._check)
        self.addCleanup(restore)

    def get(self, path, admin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"X-Admin-Token": admin} if admin else {}
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()

    def _with_customers(self, rows):
        """Patchar in Stripes svar utan en enda utgående begäran."""
        return mock.patch.object(
            api_server.stripe_oss, "list_subscriptions",
            pages(("active", rows), ("trialing", []), ("past_due", [])))

    def test_the_control_room_lists_the_foreign_customers_and_does_not_answer_200(self):
        with mock.patch.object(api_server, "STRIPE_SECRET_KEY", "sk_test_x"), \
             mock.patch.object(api_server, "STRIPE_WEBHOOK_SECRET", "whsec_x"), \
             mock.patch.object(api_server, "STRIPE_PRICE_MONTHLY", "price_m"), \
             mock.patch.object(api_server, "STRIPE_PRICE_YEARLY", "price_y"), \
             mock.patch.object(api_server, "ADMIN_TOKEN", "hemlig"), \
             mock.patch.object(api_server, "verify_stripe_prices", lambda: None), \
             mock.patch.object(api_server, "fetch_stripe_price",
                               lambda key, price: {
                                   "unit_amount": 5900 if price == "price_m" else 39900,
                                   "currency": "sek", "active": True,
                                   "tax_behavior": "inclusive",
                                   "recurring": {"interval": "month" if price == "price_m" else "year"}}), \
             mock.patch.object(api_server, "stripe_tax_readiness",
                               lambda key: {"active": True, "status": "active", "reason": None}), \
             self._with_customers([subscription("sub_de", country="DE")]):
            status, payload = self.get("/api/admin/stripe-check", admin="hemlig")
        self.assertTrue(payload["oss"]["alarm"], payload["oss"])
        self.assertEqual(payload["oss"]["countries"], ["DE"])
        self.assertEqual(payload["oss"]["foreign"][0]["country"], "DE")
        # Larmet syns på statuskoden. 200 hade varit "allt är bra".
        self.assertNotEqual(status, 200)

    def test_a_swedish_only_account_answers_200(self):
        with mock.patch.object(api_server, "STRIPE_SECRET_KEY", "sk_test_x"), \
             mock.patch.object(api_server, "STRIPE_WEBHOOK_SECRET", "whsec_x"), \
             mock.patch.object(api_server, "STRIPE_PRICE_MONTHLY", "price_m"), \
             mock.patch.object(api_server, "STRIPE_PRICE_YEARLY", "price_y"), \
             mock.patch.object(api_server, "ADMIN_TOKEN", "hemlig"), \
             mock.patch.object(api_server, "verify_stripe_prices", lambda: None), \
             mock.patch.object(api_server, "fetch_stripe_price",
                               lambda key, price: {
                                   "unit_amount": 5900 if price == "price_m" else 39900,
                                   "currency": "sek", "active": True,
                                   "tax_behavior": "inclusive",
                                   "recurring": {"interval": "month" if price == "price_m" else "year"}}), \
             mock.patch.object(api_server, "stripe_tax_readiness",
                               lambda key: {"active": True, "status": "active", "reason": None}), \
             self._with_customers([subscription("sub_se", country="SE")]):
            status, payload = self.get("/api/admin/stripe-check", admin="hemlig")
        self.assertFalse(payload["oss"]["alarm"], payload["oss"])
        self.assertEqual(status, 200, payload)

    def test_health_shows_the_alarm_without_an_admin_token_but_never_the_customers(self):
        """Kontrollen ska synas utan admin-token, som de andra
        Stripe-kontrollerna - men kundlistan bär e-postadresser och
        /api/health är öppen."""
        with mock.patch.object(api_server, "STRIPE_SECRET_KEY", "sk_test_x"), \
             self._with_customers([subscription("sub_de", country="DE",
                                                email="privat@example.com")]):
            api_server.check_oss_countries()
        status, payload = self.get("/api/health")
        self.assertEqual(status, 200)
        oss_block = payload["stripe"]["oss"]
        self.assertTrue(oss_block["alarm"])
        self.assertEqual(oss_block["countries"], ["DE"])
        self.assertNotIn("foreign", oss_block)
        self.assertNotIn("privat@example.com", json.dumps(payload))

    def test_the_check_never_raises_when_stripe_is_unreachable(self):
        def broken(*args, **kwargs):
            raise RuntimeError("Stripe svarar inte")

        with mock.patch.object(api_server, "STRIPE_SECRET_KEY", "sk_test_x"), \
             mock.patch.object(api_server.stripe_oss, "list_subscriptions", broken):
            report = api_server.check_oss_countries()
        self.assertFalse(report["alarm"])
        self.assertFalse(report["available"])

    def test_without_stripe_configured_the_check_says_so_instead_of_alarming(self):
        with mock.patch.object(api_server, "STRIPE_SECRET_KEY", ""):
            report = api_server.check_oss_countries()
        self.assertFalse(report["alarm"])
        self.assertIn("inte konfigurerat", report["reason"])


if __name__ == "__main__":
    unittest.main()
