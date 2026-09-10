# -*- coding: utf-8 -*-
"""O12: varje admin-väg nekar alla utom admin - bevisat per väg, inte läst.

Skyddet får inte bestå av en dold knapp. Därför anropas VARJE admin-väg
med GET och POST som utloggad, som vanligt konto, som Premium och som
hushållsmedlem, och svaret ska vara 404 - samma som för en väg som inte
finns, så att admin-ytan inte ens syns utifrån.

En positiv kontroll ingår: rätt admin-token ger 200. Utan den vore alla
404:or förenliga med en felkonfigurerad server där INGEN är admin."""

import http.client
import json
import sys
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api_server  # noqa: E402
from services.accounts import ratelimit  # noqa: E402  # noqa: E402

# Alla admin-vägar i api_server.py (grep '"/api/admin'), oavsett metod.
ADMIN_VAGAR = (
    "/api/admin/backup-download", "/api/admin/dabas-enrich", "/api/admin/dabas-lookup",
    "/api/admin/grocery-import", "/api/admin/insights", "/api/admin/mailing",
    "/api/admin/partner", "/api/admin/partner-feed", "/api/admin/partner-overview",
    "/api/admin/partner-stats", "/api/admin/platform-activate", "/api/admin/pricing-audit",
    "/api/admin/primat-status", "/api/admin/store-register-sync", "/api/admin/stripe-check",
    "/api/admin/stripe-reconcile",
    "/api/admin/testresultat",
)
ADMIN_HEMLIGHET = "admin-test-o12"


class AdminApiNekarAllaUtomAdmin(unittest.TestCase):

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
        self._orig_admin = api_server.ADMIN_TOKEN
        self._orig_code = api_server.PREMIUM_CODE
        api_server.ADMIN_TOKEN = ADMIN_HEMLIGHET
        api_server.PREMIUM_CODE = "hemlig-kod"

    def tearDown(self):
        api_server.ADMIN_TOKEN = self._orig_admin
        api_server.PREMIUM_CODE = self._orig_code

    def _req(self, method, path, headers=None, body=None):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            h = {"Content-Type": "application/json"} if body is not None else {}
            h.update(headers or {})
            con.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=h)
            r = con.getresponse(); raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
        finally:
            con.close()

    def _konto(self):
        ratelimit.clear_on_success("register", "127.0.0.1")   # 5 konton/timme per IP
        _, p = self._req("POST", "/api/auth/register",
                         body={"email": f"o12-{uuid.uuid4().hex[:10]}@example.com", "password": "hemligt123"})
        return p["token"]

    def _identiteter(self):
        vanlig = self._konto()
        premium = self._konto()
        self._req("POST", "/api/auth/redeem", {"Authorization": f"Bearer {premium}"}, {"code": "hemlig-kod"})
        agare, medlem = self._konto(), self._konto()
        self._req("POST", "/api/household/create", {"Authorization": f"Bearer {agare}"}, {"name": "O12"})
        _, inbjudan = self._req("POST", "/api/household/invite", {"Authorization": f"Bearer {agare}"}, {})
        self._req("POST", "/api/household/join", {"Authorization": f"Bearer {medlem}"}, {"token": inbjudan["token"]})
        return {
            "utloggad": {},
            "vanligt konto": {"Authorization": f"Bearer {vanlig}"},
            "Premium": {"Authorization": f"Bearer {premium}"},
            "hushållsmedlem": {"Authorization": f"Bearer {medlem}"},
            # Den som klistrar in sin inloggningstoken som admin-token.
            "login-token som admin-token": {"X-Admin-Token": vanlig},
        }

    def test_varje_admin_vag_nekar_alla_fyra_identiteterna(self):
        identiteter = self._identiteter()
        _, okand = self._req("GET", "/api/admin/finns-inte-alls")
        fel = []
        for namn, headers in identiteter.items():
            for vag in ADMIN_VAGAR:
                for metod, body in (("GET", None), ("POST", {})):
                    # Gissningsbudgeten per IP delas av alla anrop här - nollställ så
                    # ett 429 inte maskerar sig som (eller döljer) ett läckage.
                    ratelimit.clear_on_success("admin", "127.0.0.1")
                    status, payload = self._req(metod, vag, headers, body)
                    if status != 404:
                        fel.append(f"{namn}: {metod} {vag} -> {status} {str(payload)[:80]}")
                    elif payload != okand:
                        # Felmeddelandet får inte avslöja att vägen finns.
                        fel.append(f"{namn}: {metod} {vag} -> 404 men annan kropp än okänd väg: {payload}")
        self.assertEqual(fel, [], "\n".join(fel))

    def test_positiv_kontroll_ratt_token_slapps_in(self):
        # Utan den här vore alla 404:or ovan förenliga med "ingen är admin".
        ratelimit.clear_on_success("admin", "127.0.0.1")
        status, payload = self._req("GET", "/api/admin/insights", {"X-Admin-Token": ADMIN_HEMLIGHET})
        self.assertEqual(status, 200, payload)
        self.assertIn("tratt", payload)

    def test_utan_konfigurerad_hemlighet_ar_ingen_admin(self):
        api_server.ADMIN_TOKEN = ""
        ratelimit.clear_on_success("admin", "127.0.0.1")
        status, _ = self._req("GET", "/api/admin/insights", {"X-Admin-Token": ""})
        self.assertEqual(status, 404)
        status, _ = self._req("GET", "/api/admin/insights", {"X-Admin-Token": ADMIN_HEMLIGHET})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
