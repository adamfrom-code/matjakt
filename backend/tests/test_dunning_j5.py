# -*- coding: utf-8 -*-
"""J5: livscykeln EFTER köpet.

Matjakt hade en köpväg och ingen livscykel. Sex hål, alla på samma ställe i
kundens liv:

1. Ett nekat kort släckte Premium i samma sekund.
2. `invoice.payment_failed` hanterades inte alls - inget dunning-mejl.
3. `charge.refunded` / `charge.dispute.created` hanterades inte - återbetalar
   man i god ton och glömmer säga upp behåller kunden Premium ett år gratis.
4. E-post gick inte att byta. Adressen var permanent från registreringen.
5. Verifierad adress krävdes inte före köp.
6. Ingen påminnelse före årsförnyelsen, och ingen avstämning mot Stripe.

DET VIKTIGA MED DE HÄR TESTERNA ÄR IDEMPOTENSEN (B1).

Webhooken får leverera samma händelse hur många gånger som helst. B1:s regel
- att ett event-id bara förbrukas när händelsen faktiskt fått ett avgörande -
får inte rivas sönder av de nya vägarna. De förbrukar därför inget event-id
alls, och testerna nedan levererar varje händelse TVÅ gånger och kräver samma
utfall båda gångerna.
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services import mailings  # noqa: E402
from services.accounts import AccountStore, ratelimit  # noqa: E402
from services.accounts import store as account_store  # noqa: E402
from services.billing import dunning as billing_dunning  # noqa: E402


class DunningTestCase(unittest.TestCase):
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
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self._original = (api_server.ACCOUNT_STORE, api_server.DUNNING, api_server.MAIL_LOG)
        api_server.ACCOUNT_STORE = AccountStore(Path(self._tmp.name) / "j5.db")
        api_server.MAIL_LOG = mailings.MailingStore(api_server.ACCOUNT_STORE.connection,
                                                    lock=api_server.ACCOUNT_STORE.lock)

        # INGEN UTGÅENDE TRAFIK: mejlen och uppsägningarna fångas i listor.
        self.sent, self.cancelled = [], []
        api_server.DUNNING = billing_dunning.Dunning(
            api_server.ACCOUNT_STORE,
            send_mail=lambda to, subject, text, html: self.sent.append(
                {"to": to, "subject": subject, "text": text}),
            cancel_subscription=self.cancelled.append,
            render_dunning=mailings.render_dunning,
            render_renewal=mailings.render_fornyelse,
            app_url="https://matjakt.store/app",
            billing_url="https://matjakt.store/app/?billing=portal",
            mail_log=api_server.MAIL_LOG, metrics=None)

        def restore():
            api_server.ACCOUNT_STORE.close()
            (api_server.ACCOUNT_STORE, api_server.DUNNING, api_server.MAIL_LOG) = self._original
        self.addCleanup(restore)

    # ---- verktyg ---------------------------------------------------------

    def request(self, method, path, body=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()

    def account(self, email=None, *, verified=True):
        ratelimit.reset()
        email = email or f"j5-{uuid.uuid4().hex}@example.com"
        status, payload = self.request("POST", "/api/auth/register",
                                       {"email": email, "password": "hemligt123"})
        self.assertEqual(status, 201, payload)
        if verified:
            self.sql("UPDATE users SET email_verified = 1 WHERE email = ?", (email,))
        return payload["token"], email

    @staticmethod
    def sql(query, args=()):
        api_server.ACCOUNT_STORE.connection.execute(query, args)
        api_server.ACCOUNT_STORE.connection.commit()

    @staticmethod
    def row(email):
        return api_server.ACCOUNT_STORE.connection.execute(
            "SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    def subscriber(self, *, plan="monthly", status="active", days=30):
        """Ett konto som betalar, med en Stripe-kund och en prenumeration."""
        token, email = self.account()
        customer = f"cus_{uuid.uuid4().hex[:12]}"
        subscription = f"sub_{uuid.uuid4().hex[:12]}"
        self.sql("""UPDATE users SET stripe_customer_id = ?, stripe_subscription_id = ?,
                        subscription_status = ?, subscription_plan = ?,
                        subscription_period_end = ?
                    WHERE email = ?""",
                 (customer, subscription, status, plan,
                  (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(), email))
        return {"token": token, "email": email, "customer": customer,
                "subscription": subscription}

    def me(self, token):
        return self.request("GET", "/api/auth/me", token=token)[1]["user"]

    def event(self, event_type, obj):
        """Skickar händelsen genom DUNNING precis som webhooken gör."""
        return api_server.DUNNING.handle(
            event_type, obj, fallback_user_id=None)


class RespitVidNekatKort(DunningTestCase):
    """Ett nekat kort släckte Premium i samma sekund som banken sa nej."""

    def test_a_declined_card_keeps_premium_for_the_grace_period(self):
        user = self.subscriber()
        self.assertTrue(self.me(user["token"])["premium"])

        outcome = self.event(billing_dunning.INVOICE_FAILED,
                             {"customer": user["customer"], "amount_due": 5900})
        self.assertEqual(outcome, "dunning_sent")

        me = self.me(user["token"])
        self.assertTrue(me["premium"], "ett nekat kort släckte Premium direkt")
        # Men sanningen döljs inte: statusen säger past_due, källan säger
        # "grace", och slutdatumet finns att rita en banderoll av.
        self.assertEqual(me["subscriptionStatus"], "past_due")
        self.assertEqual(me["premiumSource"], "grace")
        self.assertTrue(me["subscriptionGraceUntil"])

    def test_premium_falls_away_when_the_grace_period_runs_out(self):
        user = self.subscriber()
        self.event(billing_dunning.INVOICE_FAILED, {"customer": user["customer"]})
        # Sju dagar och en minut senare.
        expired = (datetime.now(timezone.utc)
                   - timedelta(days=account_store.PAST_DUE_GRACE_DAYS, minutes=1)).isoformat()
        self.sql("UPDATE users SET past_due_since = ? WHERE email = ?", (expired, user["email"]))
        me = self.me(user["token"])
        self.assertFalse(me["premium"])
        self.assertIsNone(me["subscriptionGraceUntil"])

    def test_a_successful_retry_clears_the_grace_and_gives_the_next_one_its_own(self):
        """Respiten hör ihop med EN nekad betalning. En kund som missade en
        dragning i mars ska ha sina fulla sju dagar i november."""
        user = self.subscriber()
        self.event(billing_dunning.INVOICE_FAILED, {"customer": user["customer"]})
        first = self.row(user["email"])["past_due_since"]
        self.assertTrue(first)

        self.event(billing_dunning.INVOICE_PAID, {"customer": user["customer"]})
        self.assertIsNone(self.row(user["email"])["past_due_since"])

        self.event(billing_dunning.INVOICE_FAILED, {"customer": user["customer"]})
        self.assertNotEqual(self.row(user["email"])["past_due_since"], first)

    def test_the_grace_clock_is_not_pushed_forward_by_stripes_retries(self):
        """Stripe försöker i tre veckor. Varje nytt nekande får INTE starta om
        respiten - då hade sju dagar blivit tjugoen."""
        user = self.subscriber()
        self.event(billing_dunning.INVOICE_FAILED, {"customer": user["customer"]})
        started = self.row(user["email"])["past_due_since"]
        for _ in range(4):
            self.event(billing_dunning.INVOICE_FAILED, {"customer": user["customer"]})
        self.assertEqual(self.row(user["email"])["past_due_since"], started)

    def test_the_grace_length_is_one_constant(self):
        self.assertEqual(account_store.PAST_DUE_GRACE_DAYS, 7)


class DunningMejlet(DunningTestCase):
    """20-30 % av all churn, och den billigaste att rädda."""

    def test_the_failed_payment_sends_one_mail_that_says_what_happened(self):
        user = self.subscriber()
        self.event(billing_dunning.INVOICE_FAILED,
                   {"customer": user["customer"], "amount_due": 5900})
        self.assertEqual(len(self.sent), 1)
        mail = self.sent[0]
        self.assertEqual(mail["to"], user["email"])
        self.assertIn("Betalningen gick inte igenom", mail["subject"])
        self.assertIn("59 kr", mail["text"])
        self.assertIn("Premium ligger kvar till", mail["text"])

    def test_stripes_redeliveries_do_not_send_the_mail_again(self):
        """IDEMPOTENS. Samma händelse tre gånger = ett mejl. Tre likadana
        "din betalning gick inte igenom" på en timme läser som ett fel i
        systemet - vilket det också vore."""
        user = self.subscriber()
        for _ in range(3):
            self.event(billing_dunning.INVOICE_FAILED, {"customer": user["customer"]})
        self.assertEqual(len(self.sent), 1)

    def test_an_unknown_customer_is_never_acknowledged(self):
        """B1:s regel gäller även här: 200 på en okänd kund vore slutet, för
        Stripe återlevererar aldrig ett kvitterat event."""
        self.assertEqual(
            self.event(billing_dunning.INVOICE_FAILED, {"customer": "cus_frammande"}),
            "unknown_customer")

    def test_a_broken_mail_transport_does_not_undo_the_grace(self):
        """Mejlet är räddningen, inte kvittot. Faller det ska respiten och
        banderollen stå kvar."""
        user = self.subscriber()
        api_server.DUNNING._send_mail = mock.Mock(side_effect=RuntimeError("SMTP nere"))
        outcome = self.event(billing_dunning.INVOICE_FAILED, {"customer": user["customer"]})
        self.assertEqual(outcome, "dunning_sent")
        self.assertTrue(self.me(user["token"])["premium"])
        self.assertEqual(self.me(user["token"])["premiumSource"], "grace")


class AterbetalningOchBestridande(DunningTestCase):
    """Återbetalar man i god ton och glömmer säga upp behåller kunden Premium
    ett år gratis."""

    def test_a_full_refund_ends_premium_and_cancels_the_subscription(self):
        user = self.subscriber(plan="yearly", days=365)
        outcome = self.event(billing_dunning.CHARGE_REFUNDED,
                             {"customer": user["customer"], "refunded": True,
                              "amount": 39900, "amount_refunded": 39900})
        self.assertEqual(outcome, "revoked:återbetalning")
        self.assertFalse(self.me(user["token"])["premium"])
        self.assertEqual(self.cancelled, [user["subscription"]])

    def test_a_partial_refund_changes_nothing(self):
        """En kulans på en månad av ett år är inte att kunden lämnat. Att
        säga upp för att vi gav pengar tillbaka vore att straffa det vi
        själva erbjöd."""
        user = self.subscriber(plan="yearly", days=365)
        outcome = self.event(billing_dunning.CHARGE_REFUNDED,
                             {"customer": user["customer"], "refunded": False,
                              "amount": 39900, "amount_refunded": 5900})
        self.assertEqual(outcome, "partial_refund_ignored")
        self.assertTrue(self.me(user["token"])["premium"])
        self.assertEqual(self.cancelled, [])

    def test_a_dispute_ends_premium_immediately(self):
        user = self.subscriber()
        self.assertEqual(
            self.event(billing_dunning.DISPUTE_CREATED, {"customer": user["customer"]}),
            "revoked:bestridd betalning")
        self.assertFalse(self.me(user["token"])["premium"])

    def test_a_refund_also_clears_a_comped_premium_flag(self):
        """En återbetalning ska inte lämna en gammal kod-inlösning kvar som
        en osynlig bakdörr till Premium."""
        user = self.subscriber()
        self.sql("UPDATE users SET premium = 1 WHERE email = ?", (user["email"],))
        self.event(billing_dunning.DISPUTE_CREATED, {"customer": user["customer"]})
        self.assertFalse(self.me(user["token"])["premium"])

    def test_revoking_twice_is_the_same_as_once(self):
        user = self.subscriber()
        for _ in range(3):
            self.event(billing_dunning.CHARGE_REFUNDED,
                       {"customer": user["customer"], "refunded": True})
        self.assertFalse(self.me(user["token"])["premium"])

    def test_a_failed_cancellation_still_takes_premium_away(self):
        """Kontot har redan tappat Premium - det var det brådskande. En
        prenumeration som lever kvar hos Stripe fångas av avstämningen."""
        user = self.subscriber()
        api_server.DUNNING._cancel = mock.Mock(side_effect=RuntimeError("Stripe nere"))
        self.event(billing_dunning.DISPUTE_CREATED, {"customer": user["customer"]})
        self.assertFalse(self.me(user["token"])["premium"])


class WebhookenBehallerSinIdempotens(DunningTestCase):
    """B1 får inte rivas sönder av de nya vägarna."""

    def _post_webhook(self, event_id, event_type, obj):
        with mock.patch.object(api_server, "verify_webhook_signature", lambda *a, **k: None), \
             mock.patch.object(api_server, "parse_event",
                               lambda raw: json.loads(raw.decode("utf-8"))):
            return self.request("POST", "/api/billing/webhook", {
                "id": event_id, "type": event_type, "created": int(datetime.now().timestamp()),
                "data": {"object": obj}})

    def test_the_same_delivery_twice_gives_the_same_answer_and_one_mail(self):
        user = self.subscriber()
        first = self._post_webhook("evt_j5_1", billing_dunning.INVOICE_FAILED,
                                   {"customer": user["customer"], "amount_due": 5900})
        second = self._post_webhook("evt_j5_1", billing_dunning.INVOICE_FAILED,
                                    {"customer": user["customer"], "amount_due": 5900})
        self.assertEqual(first[0], 200, first)
        self.assertEqual(second[0], 200, second)
        self.assertEqual(first[1]["outcome"], second[1]["outcome"])
        self.assertEqual(len(self.sent), 1)

    def test_an_unknown_customer_answers_500_so_stripe_retries(self):
        status, payload = self._post_webhook("evt_j5_okand", billing_dunning.INVOICE_FAILED,
                                             {"customer": "cus_frammande"})
        self.assertEqual(status, 500, payload)
        # Och event-id:t är INTE förbrukat - andra leveransen får en ny chans.
        seen = api_server.ACCOUNT_STORE.connection.execute(
            "SELECT 1 FROM stripe_events WHERE event_id = ?", ("evt_j5_okand",)).fetchone()
        self.assertIsNone(seen, "ett event som inte ändrade något förbrukades ändå")

    def test_a_subscription_event_still_goes_the_old_way(self):
        """De nya händelsetyperna får inte ha kapat prenumerationsvägen."""
        user = self.subscriber()
        status, payload = self._post_webhook(
            "evt_j5_sub", "customer.subscription.updated",
            {"id": user["subscription"], "customer": user["customer"], "status": "canceled",
             "items": {"data": []}})
        self.assertEqual(status, 200, payload)
        self.assertEqual(self.me(user["token"])["subscriptionStatus"], "canceled")

    def test_an_event_type_we_do_not_handle_is_acknowledged_without_touching_anything(self):
        status, payload = self._post_webhook("evt_j5_annat", "customer.created", {"id": "cus_x"})
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("ignored"), "customer.created")


class BytaEpost(DunningTestCase):
    """Adressen var permanent från registreringen. Enda vägen ut var att
    radera kontot - vilket säger upp prenumerationen och kastar hushållet."""

    def start(self, token, new_email, password="hemligt123"):
        return self.request("POST", "/api/auth/change-email",
                            {"email": new_email, "password": password}, token=token)

    def pending_token(self, email):
        """Den råa token finns bara i mejlet. Testet tar hashen ur databasen
        och byter inte adress - det läser bara ut vilken rad som väntar."""
        return self.row(email)["pending_email_token"]

    def confirm(self, raw):
        return self.request("POST", "/api/auth/confirm-email-change", {"token": raw})

    def test_the_wrong_password_changes_nothing(self):
        """En kapad session ska inte räcka för att ta över kontot permanent."""
        token, email = self.account()
        status, payload = self.start(token, "ny@example.com", password="fel")
        self.assertEqual(status, 400, payload)
        self.assertIsNone(self.row(email)["pending_email"])

    def test_the_address_does_not_change_until_the_new_mailbox_confirms(self):
        token, email = self.account()
        with mock.patch.object(api_server, "send_email") as sender, \
             mock.patch.object(api_server, "send_email_async"):
            status, payload = self.start(token, "Ny.Adress@Example.com")
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["pendingEmail"], "ny.adress@example.com")
        # Kontot är KVAR på sin gamla adress tills länken följts. En
        # felstavad adress ska inte kunna låsa ute ägaren.
        self.assertEqual(self.me(token)["email"], email)
        self.assertEqual(self.me(token)["pendingEmail"], "ny.adress@example.com")
        # Bekräftelsemejlet gick till den NYA adressen.
        self.assertEqual(sender.call_args[0][1], "ny.adress@example.com")

    def test_the_confirmation_link_moves_the_account_and_verifies_it(self):
        token, email = self.account(verified=False)
        with mock.patch.object(api_server, "send_email") as sender, \
             mock.patch.object(api_server, "send_email_async"):
            self.start(token, "ratt@example.com")
            status, payload = self.confirm(_token_from_mail(sender))
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["user"]["email"], "ratt@example.com")
        self.assertTrue(payload["user"]["emailVerified"])
        # Sessionen överlever bytet - man ska inte kastas ut ur sin egen app.
        self.assertEqual(self.me(token)["email"], "ratt@example.com")

    def test_a_link_can_only_be_used_once(self):
        token, _ = self.account()
        with mock.patch.object(api_server, "send_email") as sender, \
             mock.patch.object(api_server, "send_email_async"):
            self.start(token, "ettbyte@example.com")
            raw = _token_from_mail(sender)
            self.assertEqual(self.confirm(raw)[0], 200)
            self.assertEqual(self.confirm(raw)[0], 400)

    def test_an_expired_link_is_refused(self):
        token, email = self.account()
        with mock.patch.object(api_server, "send_email") as sender, \
             mock.patch.object(api_server, "send_email_async"):
            self.start(token, "sent@example.com")
            raw = _token_from_mail(sender)
        self.sql("UPDATE users SET pending_email_expires_at = ? WHERE email = ?",
                 ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), email))
        self.assertEqual(self.confirm(raw)[0], 400)

    def test_an_address_someone_else_already_has_is_refused(self):
        _, taken = self.account()
        token, _ = self.account()
        with mock.patch.object(api_server, "send_email"), \
             mock.patch.object(api_server, "send_email_async"):
            status, payload = self.start(token, taken)
        self.assertEqual(status, 400, payload)

    def test_the_stripe_customer_follows_the_account(self):
        """Annars går kvittot fortfarande till adressen som var fel från
        början - vilket var hela skälet till bytet."""
        user = self.subscriber()
        with mock.patch.object(api_server, "send_email") as sender, \
             mock.patch.object(api_server, "send_email_async"), \
             mock.patch.object(api_server, "STRIPE_SECRET_KEY", "sk_test_x"), \
             mock.patch.object(api_server, "stripe_update_customer_email") as update:
            self.start(user["token"], "flyttad@example.com")
            self.confirm(_token_from_mail(sender))
        update.assert_called_once()
        self.assertEqual(update.call_args[0][1:], (user["customer"], "flyttad@example.com"))


class VerifieradAdressForeKop(DunningTestCase):
    def test_an_unverified_account_cannot_start_a_checkout(self):
        token, _ = self.account(verified=False)
        status, payload = self.request("POST", "/api/billing/checkout",
                                       {"plan": "monthly", "withdrawalConsent": True},
                                       token=token)
        self.assertEqual(status, 403, payload)
        self.assertEqual(payload["code"], "EMAIL_NOT_VERIFIED")

    def test_a_verified_account_gets_past_that_check(self):
        """Spärren ska vara adressen - inte allt annat. Ett verifierat konto
        får INTE 403 EMAIL_NOT_VERIFIED (att Stripe saknas i testmiljön ger
        ett annat fel, och det är rätt)."""
        token, _ = self.account(verified=True)
        status, payload = self.request("POST", "/api/billing/checkout",
                                       {"plan": "monthly", "withdrawalConsent": True},
                                       token=token)
        self.assertNotEqual(payload.get("code"), "EMAIL_NOT_VERIFIED")


class Arspaminnelsen(DunningTestCase):
    """I Sverige förväntas en påminnelse före en årsförnyelse."""

    def yearly(self, days):
        user = self.subscriber(plan="yearly", days=days)
        return user

    def test_a_yearly_subscriber_is_reminded_before_the_renewal(self):
        user = self.yearly(days=3)
        self.assertEqual(api_server.DUNNING.send_renewal_reminders(), 1)
        mail = self.sent[0]
        self.assertEqual(mail["to"], user["email"])
        self.assertIn("förnyas", mail["subject"])
        self.assertIn("399 kr", mail["text"])

    def test_the_reminder_is_sent_once_per_period(self):
        self.yearly(days=3)
        self.assertEqual(api_server.DUNNING.send_renewal_reminders(), 1)
        self.assertEqual(api_server.DUNNING.send_renewal_reminders(), 0)
        self.assertEqual(len(self.sent), 1)

    def test_a_renewal_far_away_is_not_reminded_yet(self):
        self.yearly(days=60)
        self.assertEqual(api_server.DUNNING.send_renewal_reminders(), 0)

    def test_a_monthly_subscriber_is_never_reminded(self):
        """Tolv påminnelser om året vore tjat, inte omtanke."""
        self.subscriber(plan="monthly", days=3)
        self.assertEqual(api_server.DUNNING.send_renewal_reminders(), 0)

    def test_someone_who_already_cancelled_is_not_reminded(self):
        user = self.yearly(days=3)
        self.sql("UPDATE users SET subscription_cancel_at_period_end = 1 WHERE email = ?",
                 (user["email"],))
        self.assertEqual(api_server.DUNNING.send_renewal_reminders(), 0)

    def test_a_failed_send_is_retried_next_round(self):
        """Markeras EFTER att mejlet gått iväg. En misslyckad sändning ska
        försökas igen, inte tystas."""
        self.yearly(days=3)
        api_server.DUNNING._send_mail = mock.Mock(side_effect=RuntimeError("SMTP nere"))
        self.assertEqual(api_server.DUNNING.send_renewal_reminders(), 0)
        api_server.DUNNING._send_mail = lambda *args: self.sent.append({"to": args[0],
                                                                       "subject": args[1],
                                                                       "text": args[2]})
        self.assertEqual(api_server.DUNNING.send_renewal_reminders(), 1)


class Avstamningen(DunningTestCase):
    """Säkerhetsnätet under B1, åt andra hållet: konton med Premium hos oss
    utan en levande prenumeration hos Stripe."""

    def test_everything_matching_is_no_divergence(self):
        user = self.subscriber()
        report = billing_dunning.reconcile(
            api_server.ACCOUNT_STORE, lambda sub: {"id": sub, "status": "active"})
        self.assertEqual(report["divergenceCount"], 0)
        self.assertEqual(report["checked"], 1)
        self.assertEqual(user["subscription"][:4], "sub_")

    def test_a_subscription_stripe_does_not_know_is_a_divergence(self):
        self.subscriber()
        report = billing_dunning.reconcile(api_server.ACCOUNT_STORE, lambda sub: None)
        self.assertEqual(report["divergenceCount"], 1)
        self.assertEqual(report["divergences"][0]["problem"], "gone")

    def test_a_status_stripe_disagrees_with_is_a_divergence(self):
        self.subscriber()
        report = billing_dunning.reconcile(
            api_server.ACCOUNT_STORE, lambda sub: {"status": "canceled"})
        self.assertEqual(report["divergences"][0]["problem"], "status_mismatch")
        self.assertEqual(report["divergences"][0]["stripeStatus"], "canceled")

    def test_premium_without_any_subscription_id_is_a_divergence(self):
        user = self.subscriber()
        self.sql("UPDATE users SET stripe_subscription_id = NULL WHERE email = ?",
                 (user["email"],))
        report = billing_dunning.reconcile(api_server.ACCOUNT_STORE, lambda sub: None)
        self.assertEqual(report["divergences"][0]["problem"], "missing_subscription")

    def test_stripe_being_down_is_not_reported_as_a_divergence(self):
        """Ett nätfel är inte en avvikelse. Att larma om det vore att larma
        om Stripes upptid i stället för om våra konton."""
        self.subscriber()

        def broken(subscription_id):
            raise RuntimeError("Stripe svarar inte")

        report = billing_dunning.reconcile(api_server.ACCOUNT_STORE, broken)
        self.assertEqual(report["divergenceCount"], 0)

    def test_the_admin_route_is_hidden_without_a_token(self):
        self.assertEqual(self.request("GET", "/api/admin/subscription-audit")[0], 404)


class Hjalpfunktioner(unittest.TestCase):
    def test_a_full_refund_is_recognised_in_both_shapes(self):
        self.assertTrue(billing_dunning.is_fully_refunded({"refunded": True}))
        self.assertTrue(billing_dunning.is_fully_refunded(
            {"amount": 5900, "amount_refunded": 5900}))
        self.assertFalse(billing_dunning.is_fully_refunded(
            {"amount": 39900, "amount_refunded": 5900}))
        self.assertFalse(billing_dunning.is_fully_refunded({}))

    def test_the_date_in_the_mail_is_one_a_person_recognises(self):
        self.assertEqual(billing_dunning.swedish_date("2026-09-24T10:00:00+00:00"),
                         "24 september")
        self.assertEqual(billing_dunning.swedish_date("skräp"), "om några dagar")

    def test_the_amount_comes_from_stripes_ore(self):
        self.assertEqual(billing_dunning.amount_kr({"amount_due": 39900}), 399)
        self.assertEqual(billing_dunning.amount_kr({}), 0)

    def test_the_customer_id_is_read_through_an_expanded_object(self):
        self.assertEqual(billing_dunning.customer_of({"customer": "cus_1"}), "cus_1")
        self.assertEqual(billing_dunning.customer_of({"customer": {"id": "cus_2"}}), "cus_2")
        self.assertIsNone(billing_dunning.customer_of({}))


def _token_from_mail(sender):
    """Den råa token finns bara i länken som gick i mejlet - precis som för
    varje annan token i Matjakt. Testet läser den där kunden läser den:
    send_email(config, till, ämne, text, html)."""
    text = sender.call_args[0][3]
    marker = "?bytmejl="
    start = text.index(marker) + len(marker)
    return text[start:].split()[0].strip('">\').,')


if __name__ == "__main__":
    unittest.main()
