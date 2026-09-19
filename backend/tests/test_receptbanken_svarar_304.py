# -*- coding: utf-8 -*-
"""AN1: receptbanken svarar 304 när klienten redan har den.

Appen hämtar HELA banken (/api/recipes?limit=500, ~260 KB) vid varje start
utan någon villkorad hämtning. Nu bär de cachebara receptsvaren en svag
ETag ur kroppens hash, och samma kropp igen (If-None-Match) ger 304 utan
kropp. Hashen är kroppens: ändras ett pris eller ett recept ändras taggen,
och en gammal bank kan aldrig svara 304 på en ny. no-store-svar och fel får
ingen tagg alls.
"""

import http.client
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.recipes import api as recipes_api  # noqa: E402


class Receptbanken304(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        recipes_api.bootstrap_if_empty()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)

    def get(self, path, **headers):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            con.request("GET", path, headers=headers)
            r = con.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            con.close()

    def test_banken_bar_en_etag_och_svarar_304_pa_samma_kropp(self):
        status, h, body = self.get("/api/recipes?limit=500")
        self.assertEqual(status, 200)
        self.assertGreater(len(body), 10_000, "banken ska vara hel")
        tag = h.get("ETag")
        self.assertTrue(tag and tag.startswith('W/"'), h)
        self.assertIn("max-age=120", h.get("Cache-Control", ""))
        status, h2, body2 = self.get("/api/recipes?limit=500", **{"If-None-Match": tag})
        self.assertEqual((status, body2), (304, b""))
        self.assertEqual(h2.get("ETag"), tag)
        self.assertIn("max-age=120", h2.get("Cache-Control", ""), "304:an ska bära samma cacheregel")

    def test_en_annan_tagg_ger_hela_svaret(self):
        status, h, body = self.get("/api/recipes?limit=5", **{"If-None-Match": 'W/"gammal"'})
        self.assertEqual(status, 200)
        self.assertGreater(len(body), 100)

    def test_flera_taggar_och_stark_form_kanns_igen(self):
        _, h, _ = self.get("/api/recipes?limit=5")
        tag = h["ETag"]
        stark = tag[2:]
        self.assertEqual(self.get("/api/recipes?limit=5", **{"If-None-Match": f'W/"x", {stark}'})[0], 304)

    def test_hyllor_och_ett_recept_har_ocksa_taggar(self):
        for path in ("/api/recipes/shelves", "/api/recipes/kottbullar-potatismos"):
            with self.subTest(path=path):
                status, h, _ = self.get(path)
                self.assertEqual(status, 200)
                self.assertTrue(h.get("ETag"), path)
                self.assertEqual(self.get(path, **{"If-None-Match": h["ETag"]})[0], 304)

    def test_ett_fel_bar_ingen_tagg(self):
        status, h, _ = self.get("/api/recipes/finns-inte")
        self.assertEqual(status, 404)
        self.assertIsNone(h.get("ETag"))

    def test_taggen_foljer_kroppen(self):
        """Två olika kroppar - två olika taggar. Det är hela garantin mot
        en gammal bank som låtsas vara ny."""
        _, h5, _ = self.get("/api/recipes?limit=5")
        _, h6, _ = self.get("/api/recipes?limit=6")
        self.assertNotEqual(h5["ETag"], h6["ETag"])


if __name__ == "__main__":
    unittest.main()
