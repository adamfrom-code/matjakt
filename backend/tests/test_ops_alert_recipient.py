# -*- coding: utf-8 -*-
"""D1 - larmen ska ha en mottagare, och avsaknaden ska SYNAS.

Hela larmkedjan i services/grocery/alerts.py fanns: dedupering, ett
incidentmejl, ett recoverymejl, tillstånd i databasen, tolv tester. Den var
ändå helt tyst i produktion, för `admin_email()` läser MATJAKT_ADMIN_EMAIL
och den variabeln stod varken i render.yaml eller i .env.example - bara i
testerna. Utan adress lägger `alerts.process` incidenten i `skipped` och går
vidare. Ett larmsystem som ingen får höra är inte ett larmsystem.

Det här testet låser båda halvorna av D1:

  1. DEKLARATIONEN. render.yaml måste namnge MATJAKT_ADMIN_EMAIL med
     `sync: false`, och .env.example måste nämna den. Det är den faktiska
     buggen - koden var redan rätt - och därmed det som måste kunna gå
     sönder igen.
  2. SYNLIGHETEN. /api/health måste svara `false` på
     adminAlerts.recipientConfigured när variabeln saknas och `true` när den
     finns, hämtat över riktig HTTP och inte genom att anropa hjälparen. En
     miljö utan mottagare ska gå att se utifrån utan att någon behöver läsa
     Renders dashboard - och utan att adressen läcker ut i ett publikt svar.
"""

import http.client
import json
import os
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

ROOT = Path(__file__).resolve().parents[2]


class RenderDeclaresTheAlertRecipientTest(unittest.TestCase):
    """Den variabel larmen faktiskt läser måste stå i driftkonfigurationen."""

    def test_render_yaml_declares_the_recipient_as_a_dashboard_value(self):
        rader = (ROOT / "render.yaml").read_text(encoding="utf-8").splitlines()
        index = next((i for i, rad in enumerate(rader)
                      if rad.strip() == "- key: MATJAKT_ADMIN_EMAIL"), None)
        self.assertIsNotNone(
            index, "render.yaml saknar MATJAKT_ADMIN_EMAIL - larmen får ingen mottagare "
                   "i produktion, och alerts.process lägger varje incident i skipped")
        # sync: false = sätts i Renders dashboard. En adress hör inte hemma
        # som ett värde i ett publikt repo, och en blueprint-synk får inte
        # heller nollställa den.
        self.assertEqual(rader[index + 1].strip(), "sync: false",
                         "MATJAKT_ADMIN_EMAIL måste vara sync: false - aldrig ett värde i repot")

    def test_env_example_names_the_variable(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("MATJAKT_ADMIN_EMAIL=", text)
        # Platshållare, aldrig en riktig adress.
        for rad in text.splitlines():
            if rad.startswith("MATJAKT_ADMIN_EMAIL="):
                self.assertEqual(rad.strip(), "MATJAKT_ADMIN_EMAIL=")

    def test_the_code_reads_exactly_the_variable_render_declares(self):
        """Ett stavfel på endera sidan ger tysta larm igen."""
        from services.grocery import alerts
        with mock.patch.dict(os.environ, {"MATJAKT_ADMIN_EMAIL": "drift@example.test"}):
            self.assertEqual(alerts.admin_email(), "drift@example.test")


class HealthShowsTheMissingRecipientTest(unittest.TestCase):
    """ACCEPTANSEN: health visar false när variabeln saknas."""

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

    def _health(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", "/api/health")
            response = conn.getresponse()
            body = response.read()
            self.assertEqual(response.status, 200)
            return json.loads(body)
        finally:
            conn.close()

    def test_health_says_false_when_the_variable_is_missing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MATJAKT_ADMIN_EMAIL", None)
            larm = self._health()["adminAlerts"]
        self.assertIs(larm["recipientConfigured"], False)
        self.assertIsNone(larm["recipientDomain"])

    def test_health_says_true_when_the_variable_is_set(self):
        with mock.patch.dict(os.environ, {"MATJAKT_ADMIN_EMAIL": "drift@example.test"}):
            larm = self._health()["adminAlerts"]
        self.assertIs(larm["recipientConfigured"], True)
        # Domänen, aldrig adressen: svaret är publikt.
        self.assertEqual(larm["recipientDomain"], "example.test")
        self.assertNotIn("drift", json.dumps(larm))

    def test_a_blank_variable_counts_as_missing(self):
        """Renders dashboard sparar gärna ett blanksteg. En adress som bara
        är whitespace når ingen och ska inte se konfigurerad ut."""
        with mock.patch.dict(os.environ, {"MATJAKT_ADMIN_EMAIL": "   "}):
            larm = self._health()["adminAlerts"]
        self.assertIs(larm["recipientConfigured"], False)

    def test_transport_and_recipient_stay_separate_signals(self):
        """Ett enda "larm: ja" hade dolt att mottagare och SMTP kan saknas
        var för sig. Båda fälten måste finnas i svaret."""
        larm = self._health()["adminAlerts"]
        self.assertIn("recipientConfigured", larm)
        self.assertIn("transportConfigured", larm)


if __name__ == "__main__":
    unittest.main()
