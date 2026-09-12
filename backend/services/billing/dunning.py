# -*- coding: utf-8 -*-
"""Det som händer EFTER köpet: nekade kort, återbetalningar och avstämning.

Matjakt hade en köpväg och ingen livscykel. Fem hål, alla på samma ställe i
kundens liv - efter att hon börjat betala:

1. **Ett nekat kort släckte Premium i samma sekund.** Stripe Smart Retries
   får ofta igenom betalningen på dag 3 av 21, så det var ofrivillig churn på
   ett problem som löste sig självt - och det dyraste slaget, för kunden VILL
   betala. Nu behåller kontot Premium i `PAST_DUE_GRACE_DAYS` dagar
   (accounts/store.py) och får veta varför.
2. **`invoice.payment_failed` hanterades inte alls.** Dunning är typiskt
   20-30 % av all churn i en konsumentprenumeration, och den billigaste att
   rädda: ett mejl som säger "ditt kort har gått ut".
3. **`charge.refunded` och `charge.dispute.created` hanterades inte.**
   Återbetalade man i god ton och glömde säga upp prenumerationen behöll
   kunden Premium ett år gratis.
4. **Ingen påminnelse före årsförnyelsen.** I Sverige förväntas den, och den
   förebygger chargebacks: den som blir överraskad av 399 kr bestrider
   dragningen i stället för att säga upp.
5. **Ingen avstämning.** B1 byggde avstämningen åt ena hållet - kunder hos
   Stripe utan konto hos oss. Den här modulen gör den åt andra hållet:
   konton som HAR Premium hos oss utan en levande prenumeration hos Stripe.
   Det är säkerhetsnätet under B1, och det som upptäcker ett tappat event
   innan en revisor gör det.

IDEMPOTENS (B1:s regel, oförändrad)

Webhooken får leverera samma händelse hur många gånger som helst.
`stripe_events` skyddar prenumerationsvägen. De här vägarna förbrukar
medvetet INGET event-id, för de är idempotenta i sig själva:

* `mark_past_due` sätter `past_due_since` bara när den är tom.
* `revoke_after_refund` skriver ett sluttillstånd; att skriva det två gånger
  är samma sak som en gång.
* Mejlen dedupliceras på `mail_log` (konto, sort, DAG) - en unik nyckel i
  databasen, inte en variabel i minnet.

Det är strängare än att kvittera ett event-id: en leverans som misslyckades
halvvägs får köra om hela vägen utan att något dubbleras.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("matjakt.billing.dunning")

# Händelsetyperna den här modulen äger. Webhooken frågar listan i stället
# för att räkna upp strängar på sitt håll - annars hanteras en händelse på
# ett ställe och ignoreras på ett annat.
INVOICE_FAILED = "invoice.payment_failed"
INVOICE_PAID = "invoice.payment_succeeded"
CHARGE_REFUNDED = "charge.refunded"
DISPUTE_CREATED = "charge.dispute.created"
HANDLED_EVENTS = (INVOICE_FAILED, INVOICE_PAID, CHARGE_REFUNDED, DISPUTE_CREATED)

# Så många dagar före en årsförnyelse påminnelsen går ut.
RENEWAL_REMINDER_DAYS = 7
# Hur ofta bakgrundsvakten stämmer av mot Stripe och skickar påminnelser.
WATCH_INTERVAL_SECONDS = 3600

MONTH_NAMES = ("januari", "februari", "mars", "april", "maj", "juni", "juli",
               "augusti", "september", "oktober", "november", "december")


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def customer_of(obj):
    """Kund-id:t, oavsett om `customer` är ett id eller ett expanderat objekt."""
    customer = _as_dict(obj).get("customer")
    return customer.get("id") if isinstance(customer, dict) else customer


def swedish_date(iso_text) -> str:
    """"2026-09-24T..." -> "24 september". Mejlet ska säga ett datum en
    människa känner igen, inte en tidsstämpel."""
    try:
        moment = datetime.fromisoformat(str(iso_text))
    except (TypeError, ValueError):
        return "om några dagar"
    return f"{moment.day} {MONTH_NAMES[moment.month - 1]}"


def amount_kr(invoice) -> int:
    """Beloppet i hela kronor ur en faktura. Stripe räknar i öre."""
    invoice = _as_dict(invoice)
    for field in ("amount_due", "amount_remaining", "total", "amount_paid"):
        value = invoice.get(field)
        if isinstance(value, (int, float)) and value:
            return int(round(value / 100))
    return 0


def is_fully_refunded(charge) -> bool:
    """Bara en HEL återbetalning tar Premium.

    En delvis återbetalning - en kulans på en månad av ett år - är inte
    samma sak som att kunden lämnat, och att säga upp hennes prenumeration
    för att vi gav henne pengar tillbaka vore att straffa det vi själva
    erbjöd."""
    charge = _as_dict(charge)
    if charge.get("refunded") is True:
        return True
    amount, refunded = charge.get("amount"), charge.get("amount_refunded")
    return bool(amount) and refunded is not None and refunded >= amount


class Dunning:
    """Webhookens efterköpsvägar, samlade så de går att pröva utan en socket.

    Anroparen skickar in lagret och två funktioner - `send_mail(to, subject,
    text, html)` och `cancel(subscription_id)` - så hela modulen kan prövas
    mot en lista i minnet i stället för mot Stripe och en SMTP-server."""

    def __init__(self, accounts, *, send_mail, cancel_subscription, render_dunning,
                 render_renewal, app_url, billing_url, mail_log=None, metrics=None):
        self.accounts = accounts
        self._send_mail = send_mail
        self._cancel = cancel_subscription
        self._render_dunning = render_dunning
        self._render_renewal = render_renewal
        self.app_url = app_url
        self.billing_url = billing_url
        self._mail_log = mail_log
        self._metrics = metrics

    # -- gemensamt ---------------------------------------------------------

    def _count(self, name):
        if self._metrics is not None:
            try:
                self._metrics.incr(name)
            except Exception:
                pass

    def _once_per_day(self, user_id, kind) -> bool:
        """True när mejlet inte redan gått ut i dag.

        `mail_log` har UNIQUE(user_id, kind, day), så spärren är en rad i
        databasen - inte en variabel som nollställs av nästa deploy. Utan
        loggen skickas mejlet ändå: hellre ett mejl för mycket än en tyst
        churn."""
        if self._mail_log is None:
            return True
        today = datetime.now(timezone.utc).date()
        try:
            if self._mail_log.sent_today(user_id, kind, today):
                return False
            self._mail_log.log(user_id, kind, today)
            return True
        except Exception:
            logger.exception("Kunde inte läsa mail_log för %s", kind)
            return True

    # -- webhook -----------------------------------------------------------

    def handle(self, event_type: str, data: dict, *, fallback_user_id=None) -> str:
        """Ett Stripe-event. Returnerar en kort sträng som anroparen loggar.

        "unknown_customer" betyder att anroparen ska svara 500 så Stripe
        försöker igen (B1) - INTE att händelsen ska kvitteras bort."""
        customer_id = customer_of(data)
        if event_type == INVOICE_FAILED:
            return self._payment_failed(customer_id, data, fallback_user_id)
        if event_type == INVOICE_PAID:
            self.accounts.clear_past_due(customer_id, fallback_user_id)
            return "grace_cleared"
        if event_type == CHARGE_REFUNDED:
            if not is_fully_refunded(data):
                return "partial_refund_ignored"
            return self._revoke(customer_id, fallback_user_id, "återbetalning")
        if event_type == DISPUTE_CREATED:
            return self._revoke(customer_id, fallback_user_id, "bestridd betalning")
        return "ignored"

    def _payment_failed(self, customer_id, invoice, fallback_user_id) -> str:
        user = self.accounts.mark_past_due(customer_id, fallback_user_id)
        if user is None:
            return "unknown_customer"
        self._count("stripe_payment_failed")
        if not user.get("subscriptionGraceUntil"):
            # Respiten är redan förbrukad - då är det inte ett dunning-läge
            # längre utan en prenumeration på väg ut, och ett mejl till om
            # att uppdatera kortet vore tjat.
            return "grace_expired"
        self._send_dunning(user, invoice)
        return "dunning_sent"

    def _send_dunning(self, user, invoice) -> None:
        if not self._once_per_day(user["id"], "dunning"):
            return
        try:
            subject, text, html = self._render_dunning(
                self.billing_url, self.app_url,
                namn=_first_name(user.get("email")),
                belopp=amount_kr(invoice) or None,
                datum=swedish_date(user.get("subscriptionGraceUntil")))
            self._send_mail(user["email"], subject, text, html)
            self._count("dunning_mail_sent")
        except Exception:
            # Mejlet är räddningen, inte kvittot. Faller det ska respiten och
            # banderollen stå kvar - och webhooken svara 200, för tillståndet
            # ÄR skrivet. En omleverans skickar mejlet igen.
            self._count("dunning_mail_failed")
            logger.exception("Dunning-mejlet kunde inte skickas till konto %s", user.get("id"))

    def _revoke(self, customer_id, fallback_user_id, reason) -> str:
        result = self.accounts.revoke_after_refund(customer_id, fallback_user_id, reason=reason)
        if result is None:
            return "unknown_customer"
        user_id, subscription_id = result
        logger.warning("Premium återkallat för konto %s: %s", user_id, reason)
        self._count("stripe_refund_revoked")
        if subscription_id:
            try:
                self._cancel(subscription_id)
            except Exception:
                # Kontot har redan tappat Premium - det var det brådskande.
                # En prenumeration som lever kvar hos Stripe fångas av
                # avstämningen nedan, som är byggd för precis det här.
                logger.exception("Prenumerationen %s kunde inte sägas upp efter %s",
                                 subscription_id, reason)
        return f"revoked:{reason}"

    # -- årspåminnelsen ----------------------------------------------------

    def send_renewal_reminders(self, within_days: int = RENEWAL_REMINDER_DAYS) -> int:
        """Påminner årsprenumeranter före förnyelsen. Returnerar antalet."""
        sent = 0
        for row in self.accounts.renewal_reminder_candidates(within_days):
            period_end = row["subscription_period_end"]
            try:
                subject, text, html = self._render_renewal(
                    self.billing_url, self.app_url,
                    namn=_first_name(row["email"]), datum=swedish_date(period_end))
                self._send_mail(row["email"], subject, text, html)
            except Exception:
                logger.exception("Förnyelsepåminnelsen kunde inte skickas till konto %s", row["id"])
                continue
            # Markeras EFTER att mejlet gått iväg: en misslyckad sändning ska
            # försökas igen vid nästa varv, inte tystas.
            self.accounts.mark_renewal_reminded(row["id"], period_end)
            sent += 1
        if sent:
            logger.info("Skickade %s förnyelsepåminnelser", sent)
        return sent


def _first_name(email) -> str:
    """Ett tilltal ur adressen. Matjakt frågar aldrig om namn, och "Hej," utan
    namn läser som ett massutskick - vilket ett kvitto inte är."""
    local = str(email or "").split("@")[0]
    first = local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    return first[0].capitalize() if first and first[0].isalpha() else "du"


# =============================================================================
# AVSTÄMNING: konton vi tror betalar, mot vad Stripe faktiskt säger
# =============================================================================

def divergences(accounts_rows, subscription_status_of) -> list:
    """Konton vars Premium inte har täckning hos Stripe.

    `subscription_status_of(subscription_id)` svarar med Stripes status, eller
    None när prenumerationen inte finns. Funktionen gör inga anrop själv, så
    avstämningen går att pröva utan vare sig Stripe eller ett kontolager.

    Tre sorters avvikelse, och alla tre betyder samma sak för ägaren: någon
    har Premium som ingen betalar för.

    * `missing_subscription` - vi har en status men inget prenumerations-id.
      Ett tappat event, eller en Checkout som aldrig landade.
    * `gone` - Stripe känner inte igen prenumerationen alls.
    * `status_mismatch` - Stripe säger canceled/unpaid medan vi säger active.
    """
    found = []
    for row in accounts_rows:
        subscription_id = row.get("stripe_subscription_id")
        ours = row.get("subscription_status")
        if not subscription_id:
            found.append({**_summary(row), "problem": "missing_subscription", "stripeStatus": None})
            continue
        theirs = subscription_status_of(subscription_id)
        if theirs is None:
            found.append({**_summary(row), "problem": "gone", "stripeStatus": None})
        elif theirs != ours:
            found.append({**_summary(row), "problem": "status_mismatch", "stripeStatus": theirs})
    return found


def _summary(row) -> dict:
    """Vad avstämningen lämnar ut. Adressen tas med - det är en admin-väg
    bakom admin-token, och utan adress går avvikelsen inte att åtgärda."""
    return {"userId": row.get("id"), "email": row.get("email"),
            "customerId": row.get("stripe_customer_id"),
            "subscriptionId": row.get("stripe_subscription_id"),
            "ourStatus": row.get("subscription_status"),
            "periodEnd": row.get("subscription_period_end")}


def reconcile(accounts, fetch_subscription) -> dict:
    """Hela avstämningen. `fetch_subscription(id)` -> Stripe-objekt eller None.

    Svaret är avsett att gå rakt ut på admin-vägen OCH att larmas på:
    `divergenceCount` är noll när allt stämmer, och allt annat är något
    någon behöver titta på."""
    rows = accounts.owing_subscribers()

    def status_of(subscription_id):
        try:
            subscription = fetch_subscription(subscription_id)
        except Exception:
            # Ett nätfel är inte en avvikelse. Att rapportera det som en
            # vore att larma om Stripes upptid i stället för om våra konton.
            return _UNKNOWN
        return _as_dict(subscription).get("status") if subscription else None

    found = [row for row in divergences(rows, status_of) if row["stripeStatus"] is not _UNKNOWN]
    return {"checked": len(rows), "divergenceCount": len(found), "divergences": found}


class _Unknown:
    """Sentinel: "Stripe svarade inte", till skillnad från "finns inte"."""

    def __repr__(self):
        return "<okänt>"


_UNKNOWN = _Unknown()
