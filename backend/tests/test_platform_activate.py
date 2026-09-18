# -*- coding: utf-8 -*-
"""D11b: "aktivera allt" startar import för VARJE släppt kedja.

/api/admin/platform-activate med startImports loopade över en tupel
skriven när tre kedjor var släppta. ICA släpptes i D11 (19 008 referens-
priser, Sveriges största kedja) - och aktiveringen hoppade tyst över den.
Ingen negativ test fanns för det: bara auth-testerna, som prövar att vägen
nekar. Det här är det första positiva testet av vad den faktiskt gör.
"""

import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.grocery import api as grocery_api  # noqa: E402
from services.grocery import publish  # noqa: E402


class PlatformActivateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)

    def _post(self, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", "/api/admin/platform-activate", body=json.dumps(payload).encode(),
                         headers={"Content-Type": "application/json", "X-Admin-Token": "admin-hemlighet"})
            r = conn.getresponse(); body = r.read()
            return r.status, json.loads(body or b"{}")
        finally:
            conn.close()

    def test_aktiveringen_startar_import_for_varje_slappt_kedja(self):
        startade = []
        orig = (api_server.ADMIN_TOKEN, api_server.grocery_importer.start, publish.backfill_reference_prices)
        api_server.ADMIN_TOKEN = "admin-hemlighet"
        api_server.grocery_importer.start = lambda chain, store_id=None, limit_per_category=None: startade.append(chain) or {"started": True}
        publish.backfill_reference_prices = lambda db: {"stubbad": True}
        try:
            status, payload = self._post({"startImports": True, "registerSync": False})
            self.assertEqual(status, 200, payload)
            self.assertEqual(startade, list(grocery_api.RELEASED_CHAINS),
                             "aktiveringen ska importera exakt de släppta kedjorna, i ordning")
            self.assertIn("ICA", startade, "ICA är släppt sedan D11 och får inte hoppas över")
            self.assertEqual([list(x)[0] for x in payload["imports"]], list(grocery_api.RELEASED_CHAINS))
        finally:
            api_server.ADMIN_TOKEN, api_server.grocery_importer.start, publish.backfill_reference_prices = orig

    def test_utan_startImports_startas_ingenting(self):
        startade = []
        orig = (api_server.ADMIN_TOKEN, api_server.grocery_importer.start, publish.backfill_reference_prices)
        api_server.ADMIN_TOKEN = "admin-hemlighet"
        api_server.grocery_importer.start = lambda chain, **k: startade.append(chain)
        publish.backfill_reference_prices = lambda db: {"stubbad": True}
        try:
            status, payload = self._post({"registerSync": False})
            self.assertEqual(status, 200, payload)
            self.assertEqual(startade, [])
            self.assertNotIn("imports", payload)
        finally:
            api_server.ADMIN_TOKEN, api_server.grocery_importer.start, publish.backfill_reference_prices = orig

    def test_ingen_hardkodad_kedjelista_i_api_server(self):
        """Källvakt: listan över släppta kedjor finns på ETT ställe."""
        src = Path(api_server.__file__).read_text(encoding="utf-8")
        self.assertNotIn('for chain in ("Willys"', src)


if __name__ == "__main__":
    unittest.main()
