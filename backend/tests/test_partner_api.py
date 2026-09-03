# -*- coding: utf-8 -*-
"""HTTP-nivå: partneradminlagret och partnerns egen feed-endpoint.

Kör en riktig ApiHandler på en ledig port mot en temporär grocery-databas.
Inga nätverksanrop utåt: allt är egna tabeller."""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()  # MATJAKT_DATA_DIR -> tempkatalog INNAN api_server importeras
import api_server  # noqa: E402
from services.grocery import api as grocery_api  # noqa: E402
from services.grocery import register  # noqa: E402
from services.grocery.models import RawProduct  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402

MILK_GTIN = "07310865093530"


class PartnerApiTest(unittest.TestCase):
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
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._real_db = grocery_api.DB_PATH
        grocery_api.DB_PATH = Path(self._tmp.name) / "grocery.db"
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", self._real_db))
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)
        self._real_admin = api_server.ADMIN_TOKEN
        api_server.ADMIN_TOKEN = "admin-hemlighet"
        self.addCleanup(lambda: setattr(api_server, "ADMIN_TOKEN", self._real_admin))

        db = GroceryStore(grocery_api.DB_PATH)
        try:
            register.ensure_chains(db)
            self.store = db.upsert_store(chain="ICA", external_store_id="1003987",
                                         name="Maxi ICA Stormarknad Gävle", city="Gävle",
                                         pricing_scope="STORE_SPECIFIC")
            product = db.find_or_create_product(RawProduct(
                chain="ICA", external_product_id="ica-milk", name="Mellanmjölk 1,5%",
                store_id="1003987", store_name="Maxi", gtin=MILK_GTIN,
                size="1000 ml", quantity=1000.0, unit="ml", category="Mejeri > Mjölk"))
            db.upsert_reference_price(product_id=product.id, chain="ICA", regular_price=12.9,
                                      source="primat:ica:1003987")
        finally:
            db.close()

    def request(self, method, path, payload=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            request_headers = {"Content-Type": "application/json", **(headers or {})}
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            conn.request(method, path, body=body, headers=request_headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            conn.close()

    def admin(self, path, payload):
        return self.request("POST", path, payload, {"X-Admin-Token": "admin-hemlighet"})

    def test_admin_token_is_required(self):
        status, _ = self.request("POST", "/api/admin/partner-overview", {},
                                 {"X-Admin-Token": "fel"})
        self.assertEqual(status, 403)

    def test_partner_lifecycle_over_http(self):
        status, created = self.admin("/api/admin/partner", {
            "action": "create", "kind": "PER_STORE", "name": "Maxi Gävle AB",
            "chain": "ICA", "storeIds": ["1003987"], "contactEmail": "butik@example.se"})
        self.assertEqual(status, 200, created)
        partner_id, api_key = created["partnerId"], created["apiKey"]
        self.assertTrue(api_key.startswith("mjp_"))

        rows = [{"gtin": MILK_GTIN, "namn": "Mellanmjölk 1,5%", "storlek": "1000 ml", "pris": "14,40"}]

        # PENDING partner: feeden vägras - även med rätt nyckel.
        status, body = self.request("POST", "/api/partner/feed",
                                    {"storeId": self.store.id, "format": "API", "rows": rows},
                                    {"X-Partner-Key": api_key})
        self.assertEqual(status, 403, body)

        status, body = self.admin("/api/admin/partner", {"action": "activate", "partnerId": partner_id})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "ACTIVE")

        # Fel nyckel: 401, inget publicerat.
        status, _ = self.request("POST", "/api/partner/feed",
                                 {"storeId": self.store.id, "format": "API", "rows": rows},
                                 {"X-Partner-Key": "mjp_fel"})
        self.assertEqual(status, 401)

        status, body = self.request("POST", "/api/partner/feed",
                                    {"storeId": self.store.id, "format": "API", "rows": rows},
                                    {"X-Partner-Key": api_key})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["publishedOk"], body)
        self.assertEqual(body["published"], 1)
        self.assertEqual(body["gatePercent"], 100.0)

        # Adminöversikten visar butiken som ACTIVE med sitt pris och sin gate.
        status, overview = self.admin("/api/admin/partner-overview", {})
        self.assertEqual(status, 200)
        row = next(s for s in overview["stores"] if s["externalStoreId"] == "1003987")
        self.assertEqual(row["partnerStatus"], "ACTIVE")
        self.assertEqual(row["prices"], 1)
        self.assertEqual(row["lastFeed"]["status"], "published")
        self.assertEqual(row["gatePercent"], 100.0)

        # Prissättningen: verifierat lokalt pris (14,40) före referensen (12,90).
        with patch.object(grocery_api, "RELEASED_CHAINS", ("ICA",)):
            status, week = self.request("POST", "/api/pricing/week", {
                "items": [{"name": "Mjölk", "amount": 1, "unit": "l"}],
                "stores": {"ICA": "1003987"}})
        self.assertEqual(status, 200, week)
        result = week["results"][0]
        self.assertEqual(result["pricingBasis"], "VERIFIED")
        self.assertEqual(result["priceLabel"], "Verifierat lokalt pris")
        self.assertEqual(result["totalCheckoutCost"], 14.4)

        # Paus: priset borta, referensen tar över och etiketten säger det.
        status, body = self.admin("/api/admin/partner", {"action": "pause", "partnerId": partner_id})
        self.assertEqual(status, 200)
        self.assertEqual(body["pricesRemoved"], 1)
        with patch.object(grocery_api, "RELEASED_CHAINS", ("ICA",)):
            status, week = self.request("POST", "/api/pricing/week", {
                "items": [{"name": "Mjölk", "amount": 1, "unit": "l"}],
                "stores": {"ICA": "1003987"}})
        result = week["results"][0]
        self.assertEqual(result["pricingBasis"], "REFERENCE")
        self.assertEqual(result["priceLabel"], "ICA referenspris")
        self.assertEqual(result["totalCheckoutCost"], 12.9)

        status, stats = self.admin("/api/admin/partner-stats", {"storeId": self.store.id})
        self.assertEqual(status, 200)
        self.assertGreaterEqual(stats["stats"].get("store_compared", 0), 1)

    def test_bad_feed_rows_never_go_live_over_http(self):
        _, created = self.admin("/api/admin/partner", {
            "action": "create", "kind": "PER_STORE", "name": "X", "chain": "ICA",
            "storeIds": ["1003987"]})
        self.admin("/api/admin/partner", {"action": "activate", "partnerId": created["partnerId"]})
        status, body = self.admin("/api/admin/partner-feed", {
            "partnerId": created["partnerId"], "storeId": self.store.id, "format": "JSON",
            "rows": [{"gtin": MILK_GTIN, "namn": "Mellanmjölk", "pris": "-2"},
                     {"gtin": MILK_GTIN, "namn": "Mellanmjölk", "pris": "0"}]})
        self.assertEqual(status, 200, body)
        self.assertFalse(body["publishedOk"])
        self.assertEqual(body["published"], 0)
        self.assertTrue(body["rowErrors"])


if __name__ == "__main__":
    unittest.main()
