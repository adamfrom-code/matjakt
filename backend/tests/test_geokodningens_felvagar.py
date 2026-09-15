"""Postnummeruppslagets felvägar, som aldrig fick ett test.

`geocode_postcode()` frågar api.zippopotam.us om ort och koordinater.
Dess docstring beskriver en RIKTIG produktionsincident:

    Found live: an invalid postcode makes zippopotam.us answer with a
    genuine HTTP 404, which urlopen raises as an uncaught HTTPError - that
    propagated all the way up through nearby_stores() to /api/stores's
    generic handler, which turned it into a 502.

Felet lagades. Testet skrevs aldrig. De befintliga testerna byter ut HELA
`geocode_postcode` mot en attrapp (test_api_server.py:1063), så funktionens
egen felhantering har aldrig prövats - bara att anroparen tål ett None.

Det här paketet prövar funktionen själv, och det gör det INTE genom att gå
ut på nätet: sviten sätter hemlighetsvariablerna till tomma just för att ett
test en gång gick ut till api.stripe.com och skapade riktiga kunder.
urlopen mockas.

Invarianten i ett enda påstående: ett dåligt eller otursamt postnummer ska
ge ett ärligt "vet inte", aldrig ett serverfel. Samma resonemang som
stale_products.
"""

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()  # MATJAKT_DATA_DIR -> tempkatalog INNAN api_server importeras

import api_server  # noqa: E402


def _svar(kropp: dict) -> io.BytesIO:
    ström = io.BytesIO(json.dumps(kropp).encode("utf-8"))
    ström.__enter__ = lambda: ström
    ström.__exit__ = lambda *a: None
    return ström


class GeokodningenFallerAldrigUtat(unittest.TestCase):
    # Cachen är beständig och slås upp per postnummer. Varje fall använder
    # därför ett EGET nummer - annars kan en träff från ett tidigare fall
    # svara i stället för mocken, och testet bevisar ingenting.

    def _kor(self, bieffekt, zip_code="99999"):
        with mock.patch.object(api_server, "urlopen", side_effect=bieffekt):
            return api_server.geocode_postcode(zip_code)

    def test_404_ger_none_och_inte_ett_undantag(self):
        """Incidenten i docstringen. Ett ogiltigt postnummer är inte ett fel."""
        fel = urllib.error.HTTPError(
            "https://api.zippopotam.us/SE/99999", 404, "Not Found", {}, None)
        self.assertIsNone(self._kor(fel))

    def test_natfel_ger_none(self):
        self.assertIsNone(self._kor(urllib.error.URLError("namnuppslaget misslyckades")))

    def test_timeout_ger_none(self):
        self.assertIsNone(self._kor(TimeoutError("tog för lång tid")))

    def test_trasig_json_ger_none(self):
        trasig = io.BytesIO(b"<html>502 Bad Gateway</html>")
        trasig.__enter__ = lambda: trasig
        trasig.__exit__ = lambda *a: None
        with mock.patch.object(api_server, "urlopen", return_value=trasig):
            self.assertIsNone(api_server.geocode_postcode("99998"))

    def test_tomt_places_ger_none(self):
        """Ett 200-svar utan platser är också ett 'vet inte'."""
        with mock.patch.object(api_server, "urlopen", return_value=_svar({"places": []})):
            self.assertIsNone(api_server.geocode_postcode("99997"))

    def test_lyckat_svar_ger_ort_och_koordinater(self):
        kropp = {"places": [{"place name": "Gävle", "latitude": "60.6745",
                             "longitude": "17.1417"}]}
        with mock.patch.object(api_server, "urlopen", return_value=_svar(kropp)):
            svar = api_server.geocode_postcode("80251")
        self.assertEqual(svar["ort"], "Gävle")
        self.assertAlmostEqual(svar["lat"], 60.6745)
        self.assertAlmostEqual(svar["lon"], 17.1417)

    def test_adressen_gar_over_https(self):
        """O16: postnumret ligger i SÖKVÄGEN och får inte gå i klartext."""
        sedda = []

        def fanga(begaran, *a, **k):
            sedda.append(begaran.full_url)
            return _svar({"places": [{"place name": "Gävle", "latitude": "60.6",
                                      "longitude": "17.1"}]})

        with mock.patch.object(api_server, "urlopen", side_effect=fanga):
            api_server.geocode_postcode("80299")
        self.assertTrue(sedda, "inget anrop gjordes")
        self.assertTrue(
            sedda[0].startswith("https://"),
            f"postnumret skickades i klartext: {sedda[0]}",
        )


if __name__ == "__main__":
    unittest.main()
