# -*- coding: utf-8 -*-
"""B9: sessionstokenfragment i klartext i backupen.

Vägar som räknas per session skickade `token[:16]` som identifierare, och
`ratelimit._check_db` skriver identifieraren ORÖRD till
`rate_limit_hits.identifier`. Den filen ligger i datakatalogen, följer med i
det nattliga backupsetet och i arkivet från `/api/admin/backup-download` -
sexton tecken av en levande bärartoken i klartext, i den enda databasfil som
inte omfattades av regeln.

Det motsäger uttryckligen policyn i `store.py`: en sessionstoken lagras
aldrig i klartext, bara som hash, just för att en läckt backup annars lämnar
över levande sessioner och inte bara lösenordshashar.

Acceptans: ingen rad i `rate_limit_hits` innehåller ett prefix av en levande
token.
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402
from services.accounts import ratelimit  # noqa: E402
from services.accounts.store import AccountStore, _session_key  # noqa: E402


def all_identifiers():
    """Varje identifierare limitern har skrivit, i båda lägena."""
    connection = ratelimit._connection
    if connection is not None:
        return [row[0] for row in connection.execute("SELECT identifier FROM rate_limit_hits")]
    return [key.split(":", 1)[1] for key in ratelimit._attempts]


class TokenFragmentTest(unittest.TestCase):

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
        api_server.ACCOUNT_STORE = AccountStore(Path(self._tmpdir.name) / "test.db")

        def restore():
            api_server.ACCOUNT_STORE.close()
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

    def living_token(self):
        _, payload = self.call("POST", "/api/auth/register",
                               {"email": f"b9-{uuid.uuid4().hex[:10]}@example.invalid",
                                "password": "hemligt123"})
        ratelimit.reset()
        return payload["token"]

    def exercise_every_session_keyed_path(self, token):
        self.call("GET", "/api/household/sync", token=token)
        self.call("POST", "/api/household/create", {"name": "B9"}, token=token)
        self.call("POST", "/api/household/invite", {}, token=token)
        self.call("POST", "/api/auth/redeem", {"code": "fel-kod"}, token=token)
        self.call("POST", "/api/auth/resend-verification", {}, token=token)

    # ---- acceptanskriteriet ------------------------------------------------

    def test_no_row_in_rate_limit_hits_holds_a_prefix_of_a_living_token(self):
        """Acceptans, ordagrant."""
        token = self.living_token()
        self.exercise_every_session_keyed_path(token)
        identifiers = all_identifiers()
        self.assertTrue(identifiers, "inga rader skrevs - testet mäter ingenting")
        for identifier in identifiers:
            self.assertFalse(token.startswith(identifier),
                             f"{identifier!r} är ett prefix av en levande token")
            self.assertNotIn(identifier, token)
            self.assertFalse(identifier and identifier in token)

    def test_the_bucket_key_cannot_be_joined_against_the_session_table(self):
        """Sessionstabellen lagrar sha256(token). Vore hinknyckeln ett prefix
        av samma hash gick raderna att para ihop: den här sessionen gjorde de
        här anropen vid de här tiderna - alltså den här användaren."""
        token = self.living_token()
        self.exercise_every_session_keyed_path(token)
        stored = _session_key(token)
        for identifier in all_identifiers():
            self.assertFalse(stored.startswith(identifier), identifier)
            self.assertNotEqual(identifier, stored)

    def test_the_bucket_still_counts_the_session(self):
        """Anonymiseringen får inte ha gjort spärren verkningslös."""
        token = self.living_token()
        limit, _ = ratelimit.LIMITS["redeem"]
        for _ in range(limit):
            self.call("POST", "/api/auth/redeem", {"code": "fel-kod"}, token=token)
        status, _ = self.call("POST", "/api/auth/redeem", {"code": "fel-kod"}, token=token)
        self.assertEqual(status, 429)
        # Och en annan session har sin egen budget.
        self.assertNotEqual(self.call("POST", "/api/auth/redeem", {"code": "fel-kod"},
                                      token=self.living_token())[0], 429)


class TokenIdentifierUnitTest(unittest.TestCase):
    def test_two_tokens_never_share_a_bucket(self):
        a = ratelimit.token_identifier("aaaa-token-ett")
        b = ratelimit.token_identifier("aaaa-token-tva")
        self.assertNotEqual(a, b)
        self.assertEqual(a, ratelimit.token_identifier("aaaa-token-ett"))

    def test_no_token_gives_no_bucket_at_all(self):
        """Hashen av tom sträng vore EN hink för alla anonyma anropare - och
        då kan en av dem låsa ute alla andra."""
        for empty in ("", None):
            self.assertEqual(ratelimit.token_identifier(empty), "")

    def test_the_identifier_reveals_nothing_of_the_token(self):
        token = "hemlig-bärartoken-abcdefghijklmnop"
        identifier = ratelimit.token_identifier(token)
        self.assertNotIn(identifier, token)
        self.assertNotIn(token[:8], identifier)
        self.assertEqual(len(identifier), 32)

    def test_it_is_not_the_stored_session_key(self):
        token = "hemlig-bärartoken-abcdefghijklmnop"
        self.assertFalse(_session_key(token).startswith(ratelimit.token_identifier(token)))


if __name__ == "__main__":
    unittest.main()
