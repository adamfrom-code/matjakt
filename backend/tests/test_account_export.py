# -*- coding: utf-8 -*-
"""B10: GDPR - exporten saknades, och raderingen lämnade spår.

Raderingen fanns och var gedigen. Men:

  * Ingen dataexport (art. 20). `GET /api/account/state` gav appstaten och
    ingenting annat - inte e-postadressen, inte prenumerationshistoriken,
    inte hushållsmedlemskapet, inte samtyckestidpunkten. Rätten till
    dataportabilitet är rätten att få ut allt i maskinläsbar form, inte att
    få tillbaka det man själv skrev in i appen.
  * `mail_log` rensades aldrig vid kontoradering. Kvar blev en rad per
    utskick med user_id och datum - ett spår av ett konto som personen bett
    oss radera, och det spåret följde med i varje backupset.
  * Två rader i registreringsflödet loggade användarens fulla e-postadress.
    De var de enda två ställena i hela backenden, och de motsade rubriken i
    `observability.py`: inga personuppgifter i loggen.

Acceptans: exporten innehåller alla sju datakategorier, och `mail_log` är
tom efter radering.
"""

import http.client
import json
import logging
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402
from services import mailings, observability  # noqa: E402
from services.accounts import data_export, ratelimit  # noqa: E402
from services.accounts.store import AccountStore  # noqa: E402


class AccountExportTest(unittest.TestCase):

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
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        original = api_server.ACCOUNT_STORE
        self.store = AccountStore(Path(self._tmpdir.name) / "test.db")
        api_server.ACCOUNT_STORE = self.store
        # mail_log ligger i kontodatabasen och delar dess anslutning och lås.
        self.mail_store = mailings.MailingStore(self.store.connection, lock=self.store.lock)

        def restore():
            self.store.close()
            api_server.ACCOUNT_STORE = original
        self.addCleanup(restore)

    def call(self, method, path, payload=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()

    def account(self, marketing=True):
        email = f"b10-{uuid.uuid4().hex[:10]}@example.invalid"
        status, payload = self.call("POST", "/api/auth/register",
                                    {"email": email, "password": "hemligt123", "marketing": marketing})
        self.assertEqual(status, 201, payload)
        ratelimit.reset()
        return email, payload["token"]

    def mail_rows(self, user_id=None):
        sql = "SELECT user_id, kind, day FROM mail_log"
        params = ()
        if user_id is not None:
            sql += " WHERE user_id = ?"
            params = (user_id,)
        return self.store.connection.execute(sql, params).fetchall()

    # ---- acceptans (a): alla sju kategorier ---------------------------------

    def test_the_export_carries_all_seven_categories(self):
        """Acceptans, ordagrant. Listan läses ur modulens eget kontrakt, så
        en bortglömd kategori blir ett rött test - inte en tom nyckel."""
        email, token = self.account()
        self.call("POST", "/api/account/state", {"budget": 1450, "personer": 4}, token)
        self.call("POST", "/api/household/create", {"name": "Familjen B10"}, token)

        status, export = self.call("GET", "/api/account/export", token=token)
        self.assertEqual(status, 200, export)
        self.assertEqual(len(data_export.CATEGORIES), 7)
        for category in data_export.CATEGORIES:
            self.assertIn(category, export, category)

        # Och innehållet är verkligen kontots, inte tomma skal.
        self.assertEqual(export["konto"]["epost"], email)
        self.assertTrue(export["konto"]["skapat"])
        self.assertTrue(export["konto"]["utskickssamtycke"])
        self.assertTrue(export["konto"]["utskickssamtyckeTidpunkt"], "samtyckestidpunkten saknas")
        self.assertEqual(export["syncedState"]["budget"], 1450)
        self.assertEqual(export["hushall"]["name"], "Familjen B10")
        self.assertIn("status", export["prenumeration"])
        self.assertIsInstance(export["skafferi"], list)
        self.assertIsInstance(export["lista"], list)
        self.assertIsInstance(export["analytics"], list)

    def test_the_export_carries_the_household_list_and_pantry(self):
        _, token = self.account()
        self.call("POST", "/api/household/create", {"name": "B10"}, token)
        self.assertEqual(self.call("POST", "/api/household/shopping/item",
                                   {"name": "Mjölk", "amount": 2, "unit": "l"}, token)[0], 200)
        self.assertEqual(self.call("POST", "/api/household/inventory/item",
                                   {"name": "Ris", "amount": 1, "unit": "kg"}, token)[0], 200)
        _, export = self.call("GET", "/api/account/export", token=token)
        self.assertTrue(any(row.get("name") == "Mjölk" for row in export["lista"]), export["lista"])
        self.assertTrue(any(row.get("name") == "Ris" for row in export["skafferi"]), export["skafferi"])

    def test_the_export_never_carries_a_credential(self):
        """Filen laddas ner, mejlas vidare och glöms i en nedladdningsmapp."""
        _, token = self.account()
        _, export = self.call("GET", "/api/account/export", token=token)
        # meta.utelamnat räknar med flit UPP orden - den listan är
        # dokumentation om vad som saknas, inte data.
        raw = json.dumps({key: value for key, value in export.items() if key != "meta"},
                         ensure_ascii=False)
        for forbidden in ("password_hash", "passwordHash", "salt", "reset_token",
                          "verification_token", "sessions"):
            self.assertNotIn(forbidden, raw, forbidden)
        self.assertNotIn(token, raw, "exporten bär den levande sessionstokenen")

    def test_the_export_needs_a_session(self):
        self.assertEqual(self.call("GET", "/api/account/export")[0], 401)
        self.assertEqual(self.call("GET", "/api/account/export", token="hittepå")[0], 401)

    def test_the_export_is_rate_limited(self):
        _, token = self.account()
        limit, _ = ratelimit.LIMITS["export"]
        for _ in range(limit):
            self.assertEqual(self.call("GET", "/api/account/export", token=token)[0], 200)
        self.assertEqual(self.call("GET", "/api/account/export", token=token)[0], 429)

    # ---- acceptans (b): inga spår kvar --------------------------------------

    def test_mail_log_is_empty_after_the_account_is_deleted(self):
        """Acceptans, ordagrant."""
        _, token = self.account()
        user_id = self.store.user_id_for_token(token)
        for kind, day in (("valkommen_dag1", "2026-09-01"), ("kampanjtorget", "2026-09-08")):
            self.store.connection.execute(
                "INSERT INTO mail_log (user_id, kind, day, sent_at) VALUES (?, ?, ?, ?)",
                (user_id, kind, day, "2026-09-08T09:00:00+00:00"))
        self.store.connection.commit()
        self.assertEqual(len(self.mail_rows(user_id)), 2)

        status, payload = self.call("POST", "/api/auth/delete-account", {}, token)
        self.assertEqual(status, 200, payload)
        self.assertEqual(self.mail_rows(user_id), [], "utskicksspåret överlevde raderingen")

    def test_deleting_one_account_leaves_another_ones_mail_log_alone(self):
        _, token_a = self.account()
        _, token_b = self.account()
        id_a, id_b = self.store.user_id_for_token(token_a), self.store.user_id_for_token(token_b)
        for user_id in (id_a, id_b):
            self.store.connection.execute(
                "INSERT INTO mail_log (user_id, kind, day, sent_at) VALUES (?, ?, ?, ?)",
                (user_id, "kampanjtorget", "2026-09-08", "2026-09-08T09:00:00+00:00"))
        self.store.connection.commit()
        self.assertEqual(self.call("POST", "/api/auth/delete-account", {}, token_a)[0], 200)
        self.assertEqual(self.mail_rows(id_a), [])
        self.assertEqual(len(self.mail_rows(id_b)), 1)

    # ---- acceptans (c): domänen, aldrig adressen ----------------------------

    def test_registration_logs_the_domain_never_the_address(self):
        """De två enda ställena i backenden som loggade en e-postadress."""
        with self.assertLogs("matjakt.api", level=logging.INFO) as captured:
            email, _ = self.account()
        rader = "\n".join(captured.output)
        self.assertNotIn(email, rader, "e-postadressen står i loggen")
        self.assertNotIn(email.split("@")[0], rader, "lokaldelen står i loggen")
        self.assertIn("example.invalid", rader, "domänen behövs för att felsöka utskicken")

    def test_email_domain_helper(self):
        self.assertEqual(observability.email_domain("Anna.Andersson@Example.COM"), "example.com")
        for junk in ("", None, "ingen-snabel-a"):
            self.assertEqual(observability.email_domain(junk), "-")


if __name__ == "__main__":
    unittest.main()
