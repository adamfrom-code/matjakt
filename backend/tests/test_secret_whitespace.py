# -*- coding: utf-8 -*-
"""En hemlighet med blanksteg i miljön låser ute den som har rätt värde.

Renders formulär tar gärna med en radbrytning när man klistrar in. Med
hmac.compare_digest blir "hemlighet\\n" != "hemlighet", och varje försök med
RÄTT token svarar 404 - utan att något i loggen säger varför. Det kostade en
kväll att hitta; det här testet gör att det inte kan hända igen."""

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class HemligheterStrippas(unittest.TestCase):
    """Prövar läsningen direkt - att ladda om api_server drar igång hela
    moduluppstarten och säger ingenting mer om just den här raden."""

    def _las(self, varde):
        import api_server
        with mock.patch.dict(os.environ, {"PROV_HEMLIGHET": varde}, clear=False):
            return api_server.secret_from_env("PROV_HEMLIGHET")

    def test_radbrytning_efter_token_later_agaren_in(self):
        self.assertEqual(self._las("hemlig-token\n"), "hemlig-token")

    def test_mellanslag_runt_token_spelar_ingen_roll(self):
        self.assertEqual(self._las("  hemlig-token  "), "hemlig-token")

    def test_windows_radslut_ocksa(self):
        # En nyckel med \r\n ger 401 från Primat och en natt utan import,
        # med "Pass a valid API key" som enda ledtråd.
        self.assertEqual(self._las("pk_live_abc\r\n"), "pk_live_abc")

    def test_bara_blanksteg_ar_tomt_inte_en_token_som_finns(self):
        # Annars släpper ADMIN_TOKEN-villkoret igenom en jämförelse mot skräp.
        self.assertEqual(self._las("   "), "")

    def test_blanksteg_inuti_ror_vi_inte(self):
        self.assertEqual(self._las(" a b "), "a b")

    def test_en_variabel_som_inte_finns_ar_tom(self):
        import api_server
        self.assertEqual(api_server.secret_from_env("FINNS_INTE_ALLS_XYZ"), "")

    def test_bada_hemligheterna_lases_med_den_har_vagen(self):
        # Regressionsskyddet: den som lägger till en ny hemlighet ska se att
        # det finns ett sätt, och de två som redan bränt en kväll ska inte
        # kunna glida tillbaka till os.environ.get utan strip.
        kalla = (Path(__file__).resolve().parents[1] / "api_server.py").read_text(encoding="utf-8")
        for rad in ('ADMIN_TOKEN = secret_from_env("MATJAKT_ADMIN_TOKEN")',
                    'PRIMAT_API_KEY = secret_from_env("PRIMAT_API_KEY")'):
            self.assertIn(rad, kalla)


if __name__ == "__main__":
    unittest.main()
