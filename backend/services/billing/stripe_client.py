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
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.stripe.com/v1"


class StripeError(Exception):
    """Raised for both "not configured" and real Stripe API errors."""


def _request(secret_key, method, path, data=None):
    if not secret_key:
        raise StripeError("Stripe är inte konfigurerat på servern ännu")
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
    _request(secret_key, "DELETE", f"/subscriptions/{subscription_id}")


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
    parts = dict(item.split("=", 1) for item in sig_header.split(",") if "=" in item)
    timestamp, signature = parts.get("t"), parts.get("v1")
    if not timestamp or not signature:
        raise StripeError("Ogiltig Stripe-signatur")
    if abs(time.time() - int(timestamp)) > tolerance_seconds:
        raise StripeError("Stripe-signaturen är för gammal")
    signed_payload = f"{timestamp}.{payload_bytes.decode('utf-8')}"
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise StripeError("Stripe-signaturen matchar inte")


def parse_event(payload_bytes):
    return json.loads(payload_bytes.decode("utf-8"))
