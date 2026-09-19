# -*- coding: utf-8 -*-
"""W1 Familjepuls: hushållets senaste händelser som en läsbar lista.

GET /api/household/events ger händelserna nyast först med aktörens
visningsnamn (aldrig e-post), bara till medlemmar; utan hushåll en tom
lista. Substratet fanns (household_events, högst 500 per hushåll) - det
här är vägen ut till appen.
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.accounts import AccountStore, ratelimit  # noqa: E402
from services.household import HouseholdStore, NotificationStore  # noqa: E402


class Familjepuls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)

    def setUp(self):
        ratelimit.reset()
        self.addCleanup(ratelimit.reset)
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "test.db"
        self._originals = (api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE, api_server.NOTIFICATION_STORE)
        api_server.ACCOUNT_STORE = AccountStore(path)
        api_server.HOUSEHOLD_STORE = HouseholdStore(path)
        api_server.NOTIFICATION_STORE = NotificationStore(path)
        self.addCleanup(self._restore)

    def _restore(self):
        for store in (api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE, api_server.NOTIFICATION_STORE):
            try:
                store.close()
            except Exception:
                pass
        api_server.ACCOUNT_STORE, api_server.HOUSEHOLD_STORE, api_server.NOTIFICATION_STORE = self._originals

    def call(self, method, path, payload=None, token=None):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            con.request(method, path, body=(json.dumps(payload).encode("utf-8") if payload is not None else None), headers=headers)
            r = con.getresponse(); raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
        finally:
            con.close()

    def user(self, name):
        status, payload = self.call("POST", "/api/auth/register", {"email": f"{name}@example.com", "password": "hemligt123"})
        self.assertEqual(status, 201, payload)
        return payload["token"]

    def family(self):
        adam, sara = self.user("adam"), self.user("sara")
        self.assertEqual(self.call("POST", "/api/household/create", {"name": "Familjen"}, adam)[0], 201)
        self.call("POST", "/api/household/profile", {"displayName": "Adam"}, adam)
        status, invite = self.call("POST", "/api/household/invite", {}, adam)
        self.assertEqual(status, 200, invite)
        self.assertEqual(self.call("POST", "/api/household/join", {"token": invite["token"]}, sara)[0], 200)
        return adam, sara

    def test_utan_hushall_en_tom_lista_och_utan_token_401(self):
        ensam = self.user("ensam")
        self.assertEqual(self.call("GET", "/api/household/events", token=ensam), (200, {"events": []}))
        self.assertEqual(self.call("GET", "/api/household/events")[0], 401)

    def test_handelserna_kommer_nyast_forst_med_aktorens_namn_aldrig_epost(self):
        adam, sara = self.family()
        status, svar = self.call("POST", "/api/household/shopping/item", {"name": "Mjölk", "amount": 2, "unit": "l", "source": "manual"}, adam)
        self.assertEqual(status, 200, svar)
        status, svar = self.call("GET", "/api/household/events?limit=10", token=sara)
        self.assertEqual(status, 200, svar)
        events = svar["events"]
        self.assertGreaterEqual(len(events), 1)
        senaste = events[0]
        for nyckel in ("id", "type", "actor", "isMe", "createdAt", "payload"):
            self.assertIn(nyckel, senaste)
        self.assertEqual(senaste["actor"], "Adam")
        self.assertIs(senaste["isMe"], False)
        self.assertNotIn("@", json.dumps(svar), "e-post får aldrig lämna hushållslagret via pulsen")
        ids = [e["id"] for e in events]
        self.assertEqual(ids, sorted(ids, reverse=True), "nyast först")
        # Samma händelse sedd av den som gjorde den: isMe
        mina = self.call("GET", "/api/household/events", token=adam)[1]["events"]
        self.assertIs(mina[0]["isMe"], True)

    def test_limit_klampas_och_bara_medlemmar_ser_pulsen(self):
        adam, _ = self.family()
        for i in range(3):
            self.call("POST", "/api/household/shopping/item", {"name": f"Vara {i}", "amount": 1, "unit": "st", "source": "manual"}, adam)
        self.assertEqual(len(self.call("GET", "/api/household/events?limit=2", token=adam)[1]["events"]), 2)
        self.assertGreaterEqual(len(self.call("GET", "/api/household/events?limit=0", token=adam)[1]["events"]), 1)
        annan = self.user("annan")
        self.assertEqual(self.call("GET", "/api/household/events", token=annan)[1], {"events": []})


if __name__ == "__main__":
    unittest.main()
