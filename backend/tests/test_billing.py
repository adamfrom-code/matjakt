import hashlib
import hmac
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.billing import StripeError, verify_webhook_signature  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
