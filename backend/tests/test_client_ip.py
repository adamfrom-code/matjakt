# -*- coding: utf-8 -*-
"""B4: X-Forwarded-For fick inte upphäva rate limitern.

Fyndet: `forwarded.split(",")[0]` läste den post som ANGRIPAREN skrev. En
proxy som lägger till bygger listan `<klientens påhitt>, <verklig IP>`, så
den som ville gissa admin-token behövde bara byta header för varje försök
- tio i timmen blev obegränsat, och skrapvägen (Chromium på 512 MB) blev
en gratis OOM-knapp.

Här bevisas två saker: att funktionen räknar bakifrån, och att hinken i
den riktiga servern faktiskt nycklas på den verkliga adressen.
"""

import http.client
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402
from services.accounts import clientip, ratelimit  # noqa: E402


def bucket_identifiers(action):
    """Varje identifierare limitern har räknat för `action`, i båda lägena.

    Hinknyckeln är det testet handlar om - inte statuskoden. Att svaret blir
    429 kan bero på tur; att raden står på 9.9.9.9 kan det inte."""
    connection = ratelimit._connection
    if connection is not None:
        return {row[0] for row in connection.execute(
            "SELECT DISTINCT identifier FROM rate_limit_hits WHERE action = ?", (action,))}
    prefix = f"{action}:"
    return {key[len(prefix):] for key in ratelimit._attempts if key.startswith(prefix)}


class ClientIpTest(unittest.TestCase):
    def test_the_last_entry_wins_not_the_first(self):
        """Acceptanskriteriet: 1.2.3.4 är påhittet, 9.9.9.9 är sant."""
        self.assertEqual(
            clientip.client_ip("1.2.3.4, 9.9.9.9", "10.0.0.1", trust_proxy=True, hops=1),
            "9.9.9.9")

    def test_a_spoofed_list_cannot_rotate_the_bucket(self):
        """Samma verkliga avsändare, tre olika påhitt - en enda hink."""
        seen = {clientip.client_ip(f"{spoof}, 9.9.9.9", "10.0.0.1", trust_proxy=True, hops=1)
                for spoof in ("1.2.3.4", "5.6.7.8", "203.0.113.9, 198.51.100.4")}
        self.assertEqual(seen, {"9.9.9.9"})

    def test_two_trusted_hops_count_two_from_the_back(self):
        self.assertEqual(
            clientip.client_ip("1.2.3.4, 9.9.9.9, 10.0.0.7", "10.0.0.1", trust_proxy=True, hops=2),
            "9.9.9.9")

    def test_a_chain_shorter_than_expected_falls_back_to_the_peer(self):
        """Kortare kedja än väntat betyder att någon kom in vid sidan av
        proxyn. Då är motpartens adress det enda vi vet."""
        self.assertEqual(
            clientip.client_ip("1.2.3.4", "198.51.100.7", trust_proxy=True, hops=2),
            "198.51.100.7")

    def test_the_header_is_ignored_without_a_trusted_proxy(self):
        self.assertEqual(
            clientip.client_ip("1.2.3.4", "198.51.100.7", trust_proxy=False, hops=1),
            "198.51.100.7")

    def test_garbage_in_the_header_never_becomes_a_bucket_name(self):
        """Utan detta väljer den som ringer sitt eget hinknamn - och skriver
        fritext i en kolumn som följer med i backupen."""
        for junk in ("not-an-ip", "'; DROP TABLE", "a" * 300):
            self.assertEqual(
                clientip.client_ip(junk, "198.51.100.7", trust_proxy=True, hops=1),
                "198.51.100.7", junk)

    def test_a_port_suffix_is_stripped(self):
        self.assertEqual(clientip.client_ip("1.2.3.4, 9.9.9.9:5678", "10.0.0.1", trust_proxy=True, hops=1), "9.9.9.9")
        self.assertEqual(clientip.client_ip("[2001:db8::1]:443", "10.0.0.1", trust_proxy=True, hops=1), "2001:db8::1")

    def test_hops_never_falls_to_zero(self):
        """0 vore 'lita på hela listan' - alltså på angriparen."""
        for raw in ("0", "-3", "", "två", None):
            self.assertGreaterEqual(clientip.trusted_hops({"MATJAKT_TRUSTED_HOPS": raw}), 1)
        self.assertEqual(clientip.trusted_hops({"MATJAKT_TRUSTED_HOPS": "2"}), 2)


class ForwardedForBucketTest(unittest.TestCase):
    """Samma sak genom hela servern: hinken ska stå på den verkliga adressen."""

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
        self._trust = api_server.TRUST_PROXY_HEADERS
        self._token = api_server.ADMIN_TOKEN
        api_server.TRUST_PROXY_HEADERS = True
        api_server.ADMIN_TOKEN = "kontrollrummets-token"

        def restore():
            api_server.TRUST_PROXY_HEADERS = self._trust
            api_server.ADMIN_TOKEN = self._token
        self.addCleanup(restore)

    def get(self, path, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def test_the_bucket_is_keyed_on_the_real_address(self):
        """`X-Forwarded-For: 1.2.3.4, 9.9.9.9` -> hinken heter 9.9.9.9."""
        self.get("/api/admin/primat-status", {"X-Forwarded-For": "1.2.3.4, 9.9.9.9"})
        identifiers = bucket_identifiers("admin")
        self.assertIn("9.9.9.9", identifiers)
        self.assertNotIn("1.2.3.4", identifiers)

    def test_rotating_the_first_entry_no_longer_buys_extra_guesses(self):
        """Innan B4 gav varje nytt påhitt en ny hink och admin-token kunde
        gissas obegränsat. Nu tar budgeten slut oavsett vad som står först."""
        limit, _ = ratelimit.LIMITS["admin"]
        statuses = [self.get("/api/admin/primat-status",
                             {"X-Forwarded-For": f"10.9.9.{index}, 9.9.9.9",
                              "X-Admin-Token": "gissning"})
                    for index in range(limit + 1)]
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(bucket_identifiers("admin"), {"9.9.9.9"})

    def test_another_real_client_behind_the_same_proxy_is_untouched(self):
        """Bakifrån-räkningen får inte lägga hela världen i en hink igen."""
        limit, _ = ratelimit.LIMITS["admin"]
        for _ in range(limit + 1):
            self.get("/api/admin/primat-status", {"X-Forwarded-For": "1.2.3.4, 9.9.9.9"})
        self.assertNotEqual(self.get("/api/admin/primat-status", {"X-Forwarded-For": "1.2.3.4, 8.8.8.8"}), 429)


if __name__ == "__main__":
    unittest.main()
