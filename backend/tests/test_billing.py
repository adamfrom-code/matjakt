import hashlib
import hmac
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import urllib.error
from unittest.mock import patch

from services.billing import StripeError, verify_webhook_signature  # noqa: E402
from services.billing import stripe_client  # noqa: E402


def _sign(payload_bytes, secret, timestamp=None):
    timestamp = timestamp or int(time.time())
    signed_payload = f"{timestamp}.{payload_bytes.decode('utf-8')}"
    signature = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


class StripeWebhookSignatureTest(unittest.TestCase):
    def test_accepts_valid_signature(self):
        payload = json.dumps({"type": "customer.subscription.updated"}).encode("utf-8")
        header = _sign(payload, "whsec_test")
        verify_webhook_signature(payload, header, "whsec_test")  # does not raise

    def test_rejects_wrong_secret(self):
        payload = json.dumps({"type": "customer.subscription.updated"}).encode("utf-8")
        header = _sign(payload, "whsec_wrong")
        with self.assertRaises(StripeError):
            verify_webhook_signature(payload, header, "whsec_test")

    def test_rejects_tampered_payload(self):
        payload = json.dumps({"type": "customer.subscription.updated"}).encode("utf-8")
        header = _sign(payload, "whsec_test")
        tampered = json.dumps({"type": "customer.subscription.updated", "extra": "x"}).encode("utf-8")
        with self.assertRaises(StripeError):
            verify_webhook_signature(tampered, header, "whsec_test")

    def test_rejects_stale_timestamp(self):
        payload = json.dumps({"type": "x"}).encode("utf-8")
        header = _sign(payload, "whsec_test", timestamp=int(time.time()) - 10_000)
        with self.assertRaises(StripeError):
            verify_webhook_signature(payload, header, "whsec_test")

    def test_rejects_missing_header(self):
        with self.assertRaises(StripeError):
            verify_webhook_signature(b"{}", "", "whsec_test")

    def test_requires_webhook_secret_configured(self):
        payload = json.dumps({"type": "x"}).encode("utf-8")
        header = _sign(payload, "whsec_test")
        with self.assertRaises(StripeError):
            verify_webhook_signature(payload, header, "")

    def test_rejects_garbage_timestamp_without_crashing(self):
        payload = b"{}"
        with self.assertRaises(StripeError):
            verify_webhook_signature(payload, "t=abc,v1=deadbeef", "whsec_test")

    def test_accepts_any_of_several_v1_signatures(self):
        """Under hemlighetsrotation skickar Stripe två v1 - en räcker."""
        payload = json.dumps({"type": "x"}).encode("utf-8")
        timestamp = int(time.time())
        good = _sign(payload, "whsec_new", timestamp).split("v1=")[1]
        header = f"t={timestamp},v1=0000,v1={good}"
        verify_webhook_signature(payload, header, "whsec_new")


class StripeClientTransport(unittest.TestCase):
    def test_network_error_becomes_stripe_error_not_500(self):
        with patch.object(stripe_client.urllib.request, "urlopen", side_effect=urllib.error.URLError("dns")):
            with self.assertRaises(StripeError):
                stripe_client.create_customer("sk_test_x", "a@b.se", 1)

    def test_timeout_becomes_stripe_error(self):
        with patch.object(stripe_client.urllib.request, "urlopen", side_effect=TimeoutError()):
            with self.assertRaises(StripeError):
                stripe_client.create_portal_session("sk_test_x", "cus_1", "https://x")

    def test_missing_secret_makes_no_network_call(self):
        with patch.object(stripe_client.urllib.request, "urlopen") as urlopen:
            with self.assertRaises(StripeError):
                stripe_client.create_customer("", "a@b.se", 1)
            urlopen.assert_not_called()

    def test_checkout_is_subscription_without_trial(self):
        captured = {}

        class _Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"url": "https://checkout.stripe.com/x"}'

        def fake_urlopen(req, timeout=None):
            captured["body"] = req.data.decode("utf-8")
            return _Response()

        with patch.object(stripe_client.urllib.request, "urlopen", fake_urlopen):
            url = stripe_client.create_checkout_session("sk_test_x", "cus_1", "price_m", "https://ok", "https://cancel")
        self.assertEqual(url, "https://checkout.stripe.com/x")
        self.assertIn("mode=subscription", captured["body"])
        self.assertIn("price_m", captured["body"])
        self.assertNotIn("trial_period_days", captured["body"])

    def test_cancel_of_already_cancelled_subscription_is_success(self):
        with patch.object(stripe_client, "_request", side_effect=StripeError("A canceled subscription can only update its cancellation_details.")):
            stripe_client.cancel_subscription("sk_test_x", "sub_1")  # kastar inte
        with patch.object(stripe_client, "_request", side_effect=StripeError("Stripe svarar inte just nu")):
            with self.assertRaises(StripeError):
                stripe_client.cancel_subscription("sk_test_x", "sub_1")

    def test_period_end_is_read_from_items_on_new_api_versions(self):
        self.assertEqual(stripe_client.subscription_period_end({"current_period_end": 5}), 5)
        self.assertEqual(stripe_client.subscription_period_end({"items": {"data": [{"current_period_end": 7}]}}), 7)
        self.assertIsNone(stripe_client.subscription_period_end({"items": {"data": []}}))


if __name__ == "__main__":
    unittest.main()
