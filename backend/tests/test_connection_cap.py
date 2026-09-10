# -*- coding: utf-8 -*-
"""B8: kontovägar utan spärr, och inget anslutningstak.

TVÅ HÅL, SAMMA RESURS. `/api/auth/me`, `/api/entitlements`,
`/api/account/state` (GET och POST) och `/api/account/marketing` anropade
aldrig `_rate_limit`, trots att alla går genom `AccountStore` med EN delad
SQLite-anslutning bakom ett processglobalt lås - och POST:en skriver upp
till 200 kB per anrop. En klient som hamrade den vägen serialiserade hela
kontolagret för alla andra.

Och `ThreadingHTTPServer` startade en tråd per anslutning utan tak.
Handlerns `timeout = 30` skyddar mot Slowloris per anslutning; ingenting
hindrade femtusen trådar samtidigt på en 512 MB-instans.

Acceptanskriteriet är det andra: anslutning nummer N+1 ska avvisas snabbt i
stället för att skapa en tråd.
"""

import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402
from services.accounts import ratelimit  # noqa: E402
from services.accounts.store import AccountStore  # noqa: E402
from services.bounded_server import BoundedThreadingHTTPServer  # noqa: E402

TAK = 4


class AnslutningstakTest(unittest.TestCase):
    """Acceptans: anslutning nr TAK+1 avvisas, och ingen tråd skapas för den."""

    def setUp(self):
        self.server = BoundedThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler,
                                                 max_connections=TAK)
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.held = []
        self.addCleanup(self._close_held)

    def _close_held(self):
        for sock in self.held:
            try:
                sock.close()
            except OSError:
                pass

    def _hold_a_slot(self):
        """Öppnar en anslutning och TIGER. Handlern väntar på en begäran som
        aldrig kommer (upp till `timeout` sekunder) och håller sin plats -
        exakt det beteende ett tak ska överleva."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.held.append(sock)
        return sock

    def _wait_for_active(self, wanted, deadline=5.0):
        slut = time.time() + deadline
        while time.time() < slut:
            if self.server.active_connections >= wanted:
                return True
            time.sleep(0.01)
        return False

    def test_connection_number_max_plus_one_is_refused_fast(self):
        """Acceptanskriteriet, ordagrant."""
        trådar_före = threading.active_count()
        for _ in range(TAK):
            self._hold_a_slot()
        self.assertTrue(self._wait_for_active(TAK), "servern hann inte ta emot de fyra")
        trådar_med_fullt = threading.active_count()

        started = time.time()
        extra = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.held.append(extra)
        extra.sendall(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        svar = extra.recv(400)
        duration = time.time() - started

        self.assertIn(b"503", svar.split(b"\r\n")[0])
        self.assertIn(b"Retry-After", svar)
        self.assertLess(duration, 2.0, "avvisningen ska vara snabb, inte en kö")
        # Ingen ny tråd för den femte. (Trådräkningen kan variera med en i
        # bakgrunden, därför <= och inte ==.)
        self.assertLessEqual(threading.active_count(), trådar_med_fullt,
                             "anslutningen över taket skapade en tråd")
        self.assertGreaterEqual(trådar_med_fullt, trådar_före + TAK)
        self.assertEqual(self.server.stats()["refused"], 1)

    def test_a_slot_comes_back_when_the_connection_closes(self):
        """Ett tak som bara räknar uppåt är en tidsinställd utelåsning."""
        for _ in range(TAK):
            self._hold_a_slot()
        self.assertTrue(self._wait_for_active(TAK))
        self.held.pop().close()
        slut = time.time() + 5
        while time.time() < slut and self.server.active_connections >= TAK:
            time.sleep(0.01)
        self.assertLess(self.server.active_connections, TAK, "platsen lämnades aldrig tillbaka")

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/api/health")
            self.assertEqual(conn.getresponse().status, 200)
        finally:
            conn.close()

    def test_under_the_cap_everything_is_normal(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/api/health")
            response = conn.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, 200)
        finally:
            conn.close()
        self.assertIn("connections", payload)      # taket syns utifrån


class KontovagarnaHarSpärrTest(unittest.TestCase):
    """Varje väg som går genom det låsta kontolagret har en hink."""

    @classmethod
    def setUpClass(cls):
        cls.server = BoundedThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler,
                                                max_connections=64)
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
            response.read()
            return response.status
        finally:
            conn.close()

    def _token(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            body = json.dumps({"email": f"b8-{uuid.uuid4().hex[:10]}@example.invalid",
                               "password": "hemligt123"}).encode()
            conn.request("POST", "/api/auth/register", body=body,
                         headers={"Content-Type": "application/json"})
            payload = json.loads(conn.getresponse().read())
        finally:
            conn.close()
        ratelimit.reset()
        return payload["token"]

    def test_the_read_paths_share_the_public_budget(self):
        limit, _ = ratelimit.LIMITS["public"]
        vagar = ("/api/auth/me", "/api/entitlements", "/api/account/state")
        for index in range(limit):
            self.call("GET", vagar[index % len(vagar)])
        # Budgeten är gemensam per IP, så nästa anrop på VILKEN som helst av
        # dem är över taket - inte tre separata obegränsade vägar.
        for vag in vagar:
            self.assertEqual(self.call("GET", vag), 429, vag)

    def test_the_write_path_has_its_own_tighter_budget(self):
        token = self._token()
        limit, _ = ratelimit.LIMITS["state"]
        self.assertLess(limit, ratelimit.LIMITS["public"][0], "skrivvägen ska vara trängre")
        for _ in range(limit):
            self.assertEqual(self.call("POST", "/api/account/state", {"budget": 1200}, token), 200)
        self.assertEqual(self.call("POST", "/api/account/state", {"budget": 1200}, token), 429)
        # Och läsvägarnas budget är inte förbrukad av skrivandet.
        self.assertEqual(self.call("GET", "/api/auth/me", token=token), 200)

    def test_the_marketing_toggle_is_limited_too(self):
        token = self._token()
        limit, _ = ratelimit.LIMITS["state"]
        for _ in range(limit):
            self.call("POST", "/api/account/marketing", {"consent": True}, token)
        self.assertEqual(self.call("POST", "/api/account/marketing", {"consent": False}, token), 429)


if __name__ == "__main__":
    unittest.main()
