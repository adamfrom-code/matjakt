# -*- coding: utf-8 -*-
"""Ett skippat E2E-set får inte läcka tillstånd till resten av sviten.

setUpClass som kastar SkipTest kör aldrig tearDownClass. Sätts ADMIN_TOKEN
före den punkten ligger den kvar i api_server för alla tester efteråt - så
föll test_the_mail_signing_key_is_not_the_admin_token i CI utan Chromium."""
import sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402


class SkippadE2ELackerInte(unittest.TestCase):
    def test_admin_token_ar_ororad_nar_chromium_saknas(self):
        try:
            from tests.e2e import test_admin_panel as modul
        except Exception as error:  # playwright saknas helt: då finns inget att läcka
            self.skipTest(f"e2e-modulen kan inte importeras här: {error}")
        fore = api_server.ADMIN_TOKEN
        klass = type("Fake", (), {})
        class Trasig:
            def start(self):
                return self
            class chromium:
                @staticmethod
                def launch(**kw): raise RuntimeError("ingen Chromium")
            def stop(self): pass
        with mock.patch.object(modul, "_skip_reason", return_value=None), \
             mock.patch.object(modul, "sync_playwright", lambda: Trasig()):
            with self.assertRaises(unittest.SkipTest):
                modul.AdminPanel.setUpClass()
        self.assertEqual(api_server.ADMIN_TOKEN, fore, "ADMIN_TOKEN läckte ur ett skippat setUpClass")


if __name__ == "__main__":
    unittest.main()
