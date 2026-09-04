"""Minimal Stripe REST client - stdlib only (urllib/hmac), no stripe SDK dependency,
matching this project's existing pattern of avoiding extra deps where a small
wrapper suffices (see services/accounts/store.py). Stripe's API is plain HTTPS
form-encoded requests with Bearer auth, so this covers exactly what Matjakt
needs: create a customer, start a Checkout session, open the Billing Portal,
and verify webhook signatures.
"""

import hashlib
import hmac
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from ..data_guard import guard_outbound_call

API_BASE = "https://api.stripe.com/v1"
# Signaturfälten har fast form. Allt annat avvisas INNAN det jämförs - annars
# kunde ett icke-ASCII-tecken i v1 (headers avkodas latin-1) eller ett
# gigantiskt t få hmac/time att kasta TypeError/OverflowError, som handlern
# inte fångade: en oautentiserad begäran gav traceback i stället för 400.
_HEX64 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_TIMESTAMP = re.compile(r"^\d{1,12}$")


class StripeError(Exception):
    """Raised for both "not configured" and real Stripe API errors."""


def _request(secret_key, method, path, data=None):
    # Konfigurationsfelet först: utan nyckel blir det ändå inget anrop, och
    # anroparen ska få sitt vanliga StripeError - inte testspärren.
    if not secret_key:
        raise StripeError("Stripe är inte konfigurerat på servern ännu")
    guard_outbound_call("Stripe")
    url = f"{API_BASE}{path}"
    body = urllib.parse.urlencode(data, doseq=True).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {secret_key}")
    if body:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error).get("error", {}).get("message", str(error))
        except Exception:
            detail = str(error)
        raise StripeError(detail)
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as error:
        # Nätfel/timeout är inte en 500 i vår server - det är "Stripe svarar
        # inte just nu", och anroparen svarar 503/400 med det beskedet.
        raise StripeError(f"Stripe svarar inte just nu ({error.__class__.__name__})")
    except ValueError as error:
        raise StripeError(f"Oväntat svar från Stripe: {error}")


def create_customer(secret_key, email, user_id):
    result = _request(secret_key, "POST", "/customers", {
        "email": email, "metadata[matjakt_user_id]": str(user_id),
    })
    return result["id"]


def create_checkout_session(secret_key, customer_id, price_id, success_url, cancel_url):
    result = _request(secret_key, "POST", "/checkout/sessions", {
        "mode": "subscription",
        "customer": customer_id,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": 1,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": "true",
    })
    return result["url"]


def cancel_subscription(secret_key, subscription_id):
    if not subscription_id:
        return
    try:
        _request(secret_key, "DELETE", f"/subscriptions/{subscription_id}")
    except StripeError as error:
        # Redan uppsagd eller borta hos Stripe = målet är uppnått. Att
        # kasta här skulle t.ex. stoppa en kontoradering i onödan.
        text = str(error).lower()
        if "no such subscription" in text or "canceled subscription" in text or "already been canceled" in text:
            return
        raise


def delete_customer(secret_key, customer_id):
    """GDPR: kunden hos Stripe följer med när kontot raderas. Best effort -
    anroparen loggar men blockerar inte raderingen på detta."""
    if not customer_id:
        return
    try:
        _request(secret_key, "DELETE", f"/customers/{customer_id}")
    except StripeError as error:
        if "no such customer" in str(error).lower():
            return
        raise


def subscription_period_end(subscription: dict):
    """Unix-tid för periodens slut. Stripe flyttade fältet från
    prenumerationen till dess items i API-version 2025-03-31.basil - läs
    båda så period_end inte tyst blir null efter en versionsuppgradering."""
    value = subscription.get("current_period_end")
    if value:
        return value
    items = ((subscription.get("items") or {}).get("data")) or []
    for item in items:
        if isinstance(item, dict) and item.get("current_period_end"):
            return item["current_period_end"]
    return None


def fetch_price(secret_key, price_id):
    """Ett pris som Stripe ser det - för konfigurationskontrollen. Kastar
    StripeError när id:t inte finns (typiskt: fel id inklistrat i miljön)."""
    return _request(secret_key, "GET", f"/prices/{urllib.parse.quote(price_id)}")


def create_portal_session(secret_key, customer_id, return_url):
    result = _request(secret_key, "POST", "/billing_portal/sessions", {
        "customer": customer_id,
        "return_url": return_url,
    })
    return result["url"]


def verify_webhook_signature(payload_bytes, sig_header, webhook_secret, tolerance_seconds=300):
    """Stripe's documented scheme: the Stripe-Signature header holds
    `t=<unix timestamp>,v1=<hmac>`. Recompute hmac_sha256(webhook_secret,
    f"{t}.{payload}") and compare to v1, and reject stale timestamps (replay
    defense) - see https://stripe.com/docs/webhooks#verify-manually.
    Raises StripeError on any mismatch; callers must treat that as untrusted input.
    """
    if not webhook_secret:
        raise StripeError("Stripe webhook är inte konfigurerat på servern ännu")
    if not sig_header:
        raise StripeError("Saknar Stripe-signatur")
    # Flera v1-signaturer förekommer under hemlighetsrotation - en räcker.
    timestamp, signatures = None, []
    for item in sig_header.split(","):
        key, _, value = item.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1" and value:
            signatures.append(value)
    signatures = [value for value in signatures if _HEX64.match(value)]
    if not timestamp or not signatures or not _TIMESTAMP.match(timestamp):
        raise StripeError("Ogiltig Stripe-signatur")
    timestamp_value = int(timestamp)
    if abs(time.time() - timestamp_value) > tolerance_seconds:
        raise StripeError("Stripe-signaturen är för gammal")
    try:
        signed_payload = f"{timestamp}.{payload_bytes.decode('utf-8')}"
    except UnicodeDecodeError:
        raise StripeError("Kroppen är inte giltig UTF-8")
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, signature.lower()) for signature in signatures):
        raise StripeError("Stripe-signaturen matchar inte")


def parse_event(payload_bytes):
    return json.loads(payload_bytes.decode("utf-8"))
