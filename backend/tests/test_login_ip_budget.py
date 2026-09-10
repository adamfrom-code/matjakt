# -*- coding: utf-8 -*-
"""B6: en egen inloggning nollställde offrets IP-hink.

`clear_on_success("login", ip, email)` raderade BÅDA hinkarna. En angripare
med ett eget konto behövde alltså bara varva: nio gissningar, en inloggning
på sitt eget konto, budgeten tillbaka på noll. I all evighet, och därmed
utan gräns mot en hel användarlista - för e-posthinken tar bara tio per
konto och fem minuter, medan IP-hinken var den enda som såg helheten.

Inloggning kräver dessutom bara åtta tecken utan komplexitetskrav
(`store.py`), så en obegränsad gissningstakt är inte ett teoretiskt problem.

Här bevisas att IP-hinken ÖVERLEVER en lyckad inloggning från samma IP, och
- lika viktigt - att den som lyckas inte straffas av sin egen framgång: den
enda träff som glöms är den lyckade inloggningens egen.
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
from services.accounts.store import AccountStore  # noqa: E402

ANGRIPARENS_IP = "203.0.113.7"


def bucket_size(action, identifier):
    """Hur många träffar limitern har på identifieraren, i båda lägena."""
    connection = ratelimit._connection
    if connection is not None:
        return connection.execute(
            "SELECT COUNT(*) FROM rate_limit_hits WHERE action = ? AND identifier = ?",
            (action, identifier)).fetchone()[0]
    return len(ratelimit._attempts.get(f"{action}:{identifier}", []))


class LoginIpBudgetTest(unittest.TestCase):

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
        original_store = api_server.ACCOUNT_STORE
        original_trust = api_server.TRUST_PROXY_HEADERS
        api_server.ACCOUNT_STORE = AccountStore(Path(self._tmpdir.name) / "test.db")
        # Så testet kan tala från olika adresser mot samma loopback-server.
        api_server.TRUST_PROXY_HEADERS = True

        def restore():
            api_server.ACCOUNT_STORE.close()
            api_server.ACCOUNT_STORE = original_store
            api_server.TRUST_PROXY_HEADERS = original_trust
        self.addCleanup(restore)

    def post(self, path, payload, ip):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", path, body=json.dumps(payload).encode("utf-8"),
                         headers={"Content-Type": "application/json", "X-Forwarded-For": ip})
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def register(self, ip):
        email = f"b6-{uuid.uuid4().hex[:10]}@example.invalid"
        # Registreringen har sin egen hink (5/timme per IP) - den är inte
        # det som testas, så den nollas mellan konton.
        ratelimit.clear_on_success("register", ip)
        self.assertEqual(self.post("/api/auth/register", {"email": email, "password": "hemligt123"}, ip), 201)
        ratelimit.reset()
        return email

    def guess(self, email, ip=ANGRIPARENS_IP):
        return self.post("/api/auth/login", {"email": email, "password": "fel-losenord"}, ip)

    # ---- acceptanskriteriet ------------------------------------------------

    def test_the_ip_bucket_survives_a_successful_login_from_the_same_ip(self):
        """Acceptans, ordagrant: hinken finns kvar efteråt."""
        egen = self.register(ANGRIPARENS_IP)
        limit, _ = ratelimit.LIMITS["login"]
        for _ in range(limit - 1):                                  # nio gissningar
            self.guess(f"offer-{uuid.uuid4().hex[:8]}@example.invalid")
        self.assertEqual(bucket_size("login", ANGRIPARENS_IP), limit - 1)

        self.assertEqual(self.post("/api/auth/login", {"email": egen, "password": "hemligt123"},
                                   ANGRIPARENS_IP), 200)
        # Före B6 stod det 0 här: den lyckade inloggningen raderade allt.
        self.assertEqual(bucket_size("login", ANGRIPARENS_IP), limit - 1)

    def test_logging_into_your_own_account_no_longer_buys_endless_guesses(self):
        """Angreppet i sin helhet: nio gissningar mot nio OLIKA konton (så
        e-posthinken aldrig hinner slå i), en inloggning på det egna kontot,
        och sen fortsätter man. Nu tar budgeten slut ändå."""
        egen = self.register(ANGRIPARENS_IP)
        limit, _ = ratelimit.LIMITS["login"]
        for _ in range(limit - 1):
            self.assertEqual(self.guess(f"offer-{uuid.uuid4().hex[:8]}@example.invalid"), 401)
        self.assertEqual(self.post("/api/auth/login", {"email": egen, "password": "hemligt123"},
                                   ANGRIPARENS_IP), 200)
        # Exakt en gissning kvar av de tio - inte tio nya.
        self.assertEqual(self.guess(f"offer-{uuid.uuid4().hex[:8]}@example.invalid"), 401)
        self.assertEqual(self.guess(f"offer-{uuid.uuid4().hex[:8]}@example.invalid"), 429)

    # ---- och ingen som lyckas straffas av det ------------------------------

    def test_a_family_behind_one_router_is_not_locked_out_by_logging_in(self):
        """Den lyckade inloggningen tar bort sin EGEN träff, så den varken
        förlåter tidigare misslyckanden eller äter av budgeten. Utan det
        delar en familj - eller tusen abonnenter bakom operatörens NAT - på
        tio inloggningar per fem minuter."""
        konton = [self.register(ANGRIPARENS_IP) for _ in range(3)]
        limit, _ = ratelimit.LIMITS["login"]
        for _ in range(limit + 5):
            konto = konton[_ % len(konton)]
            self.assertEqual(self.post("/api/auth/login", {"email": konto, "password": "hemligt123"},
                                       ANGRIPARENS_IP), 200)
        self.assertEqual(bucket_size("login", ANGRIPARENS_IP), 0)

    def test_mistyping_and_then_succeeding_still_forgives_your_own_account(self):
        """Regeln som fanns innan får inte gå förlorad: den som skriver fel
        två gånger och sen rätt ska inte vara spärrad resten av fönstret."""
        konto = self.register("198.51.100.4")
        for _ in range(3):
            self.assertEqual(self.guess(konto, "198.51.100.4"), 401)
        self.assertEqual(bucket_size("login", konto), 3)
        self.assertEqual(self.post("/api/auth/login", {"email": konto, "password": "hemligt123"},
                                   "198.51.100.4"), 200)
        self.assertEqual(bucket_size("login", konto), 0)

    def test_another_address_is_untouched(self):
        limit, _ = ratelimit.LIMITS["login"]
        for _ in range(limit):
            self.guess(f"offer-{uuid.uuid4().hex[:8]}@example.invalid")
        self.assertEqual(self.guess("annan@example.invalid"), 429)
        self.assertEqual(self.guess("annan@example.invalid", "192.0.2.55"), 401)


class UncountUnitTest(unittest.TestCase):
    """Primitiven själv: en träff bort, inte alla."""

    def setUp(self):
        ratelimit.reset()
        self.addCleanup(ratelimit.reset)

    def test_uncount_removes_exactly_one_hit(self):
        for _ in range(4):
            ratelimit.check("login", "9.9.9.9")
        ratelimit.uncount("login", "9.9.9.9")
        self.assertEqual(bucket_size("login", "9.9.9.9"), 3)

    def test_uncount_on_an_empty_bucket_is_harmless(self):
        ratelimit.uncount("login", "9.9.9.9")
        self.assertEqual(bucket_size("login", "9.9.9.9"), 0)

    def test_uncount_never_touches_another_identifier(self):
        ratelimit.check("login", "9.9.9.9", "a@example.invalid")
        ratelimit.uncount("login", "9.9.9.9")
        self.assertEqual(bucket_size("login", "a@example.invalid"), 1)


if __name__ == "__main__":
    unittest.main()
