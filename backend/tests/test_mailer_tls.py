# -*- coding: utf-8 -*-
"""STARTTLS måste verifiera serverns certifikat. smtplib.starttls() utan
context gör det inte på Python < 3.12 (produktionens image): en MITM mellan
Render och Resend kunde läsa SMTP-lösenordet och varje återställningslänk."""

import ssl
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import data_guard  # noqa: E402
from services.email import mailer  # noqa: E402


class _FakeSmtp:
    calls = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        _FakeSmtp.calls.append(("starttls", context))

    def login(self, user, password):
        _FakeSmtp.calls.append(("login", user))

    def sendmail(self, envelope_from, recipients, message):
        _FakeSmtp.calls.append(("sendmail", envelope_from, tuple(recipients)))

    def noop(self):
        _FakeSmtp.calls.append(("noop",))


class StartTlsVerifies(unittest.TestCase):
    CONFIG = {"host": "smtp.example.test", "port": 587, "user": "resend", "password": "x",
              "from_email": "noreply@matjakt.store"}

    def setUp(self):
        _FakeSmtp.calls = []
        self._saved = mailer.smtplib.SMTP
        mailer.smtplib.SMTP = _FakeSmtp
        self.addCleanup(setattr, mailer.smtplib, "SMTP", self._saved)

    def _contexts(self):
        return [context for name, *rest in _FakeSmtp.calls if name == "starttls" for context in rest]

    def test_send_email_uses_a_verifying_context(self):
        with data_guard.mocked_outbound():
            mailer.send_email(self.CONFIG, "till@example.com", "Ämne", "Text")
        contexts = self._contexts()
        self.assertEqual(len(contexts), 1)
        self.assertIsInstance(contexts[0], ssl.SSLContext)
        self.assertEqual(contexts[0].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(contexts[0].check_hostname)

    def test_check_transport_uses_a_verifying_context(self):
        with data_guard.mocked_outbound():
            mailer.check_transport(self.CONFIG)
        contexts = self._contexts()
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].verify_mode, ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
