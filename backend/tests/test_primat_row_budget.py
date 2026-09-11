# -*- coding: utf-8 -*-
"""D5: dygnets radkvot bokförs, och kontrolleras FÖRE start.

Natten 2026-09-11 mättes utfallet i produktion:

    ICA=0/0p [failed]  Coop=12079/12050p [ready_for_release]  Lidl=0/0p [limited]

Coop hann först och tog det som fanns kvar av dygnskvoten; ICA och Lidl kom
aldrig förbi 429. Orsakskedjan var två fel som förstärkte varandra. Taket per
körning (40 000) låg över dygnskvoten (100 000 delat på tre kedjor), och
ingenting räknade vad som redan förbrukats - `_rows_spent` fanns i providern,
men bara inom en körning och bara i minnet.

Testerna nedan motsvarar varje led i den kedjan.
"""

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import quota  # noqa: E402
from services.grocery.errors import ProviderBlockedError  # noqa: E402
from services.grocery.providers import primat  # noqa: E402
from services.grocery.providers.primat import PrimatProvider  # noqa: E402


class MinnesKV:
    """KV-store i minnet med KeyValueCacheStore-ytan."""

    def __init__(self):
        self.data = {}

    def get(self, namespace, key):
        return self.data.get((namespace, key), (None, None))

    def set(self, namespace, key, value, updated_at=None):
        self.data[(namespace, key)] = (value, updated_at or 0.0)


def _epok(år, månad, dag, timme=12, minut=0):
    return datetime(år, månad, dag, timme, minut, tzinfo=timezone.utc).timestamp()


class Bokforingen(unittest.TestCase):
    def setUp(self):
        self.kv = MinnesKV()
        self.nu = _epok(2026, 9, 11)

    def test_forbrukade_rader_summeras_over_korningar(self):
        """Poängen med att den ligger i databasen: den ska överleva både
        körningen och processen."""
        quota.book_rows(12_000, kv=self.kv, now=self.nu)
        quota.book_rows(8_000, kv=self.kv, now=self.nu)
        self.assertEqual(quota.rows_spent(kv=self.kv, now=self.nu), 20_000)
        self.assertEqual(quota.headroom(kv=self.kv, now=self.nu), 80_000)

    def test_dygnet_ar_primats_inte_vart(self):
        """Kvoten nollställs midnatt UTC = 02:00 svensk sommartid. Räknade vi
        på svensk midnatt hade bokföringen nollställts tre timmar för tidigt,
        och ICA 05:30 börjat om mot en kvot som ännu inte vänt."""
        sent = _epok(2026, 9, 11, 23, 59)
        tidigt = _epok(2026, 9, 12, 0, 1)
        quota.book_rows(90_000, kv=self.kv, now=sent)
        self.assertEqual(quota.headroom(kv=self.kv, now=sent), 10_000)
        self.assertEqual(quota.headroom(kv=self.kv, now=tidigt), 100_000)
        # ... och svensk midnatt (22:00 UTC kvällen innan) vänder INTE dygnet.
        self.assertEqual(quota.headroom(kv=self.kv, now=_epok(2026, 9, 11, 22, 30)),
                         10_000)

    def test_utan_utrymme_far_ingen_katalogimport_starta(self):
        quota.book_rows(99_500, kv=self.kv, now=self.nu)
        ok, skäl = quota.can_start(kv=self.kv, now=self.nu)
        self.assertFalse(ok)
        self.assertIn("500 rader kvar", skäl)
        self.assertIn("100000", skäl)

    def test_med_utrymme_far_den_starta(self):
        ok, skäl = quota.can_start(kv=self.kv, now=self.nu)
        self.assertTrue(ok)
        self.assertIn("100000", skäl)

    def test_en_ostorbar_kv_store_stoppar_inte_importen(self):
        """Bokföringen är en spärr, inte ett beroende. Går den inte att
        skriva ska nattjobbet ändå gå - Primats egen 429 står kvar som sista
        spärr."""
        class Trasig:
            def get(self, *a, **k):
                raise OSError("disken")

            def set(self, *a, **k):
                raise OSError("disken")

        self.assertEqual(quota.rows_spent(kv=Trasig(), now=self.nu), 0)
        quota.book_rows(100, kv=Trasig(), now=self.nu)      # får inte kasta
        self.assertTrue(quota.can_start(kv=Trasig(), now=self.nu)[0])


class Budgeten(unittest.TestCase):
    def setUp(self):
        self.kv = MinnesKV()

    def test_app_nivans_tak_ar_utgangslaget(self):
        """100 000 rader per dygn, bekräftat ur Primats eget 429-svar
        2026-09-10. Uppdragsdokumentets 20 000 var gratisnivåns siffra och
        inaktuell för det här kontot."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PRIMAT_DAILY_ROW_BUDGET", None)
            self.assertEqual(quota.daily_row_budget(self.kv), 100_000)

    def test_primats_egen_siffra_vinner_over_var(self):
        """O8:s princip: talet ska komma från Primat. Så fort driftkollen
        läst ett tak ur GET /me är DET budgeten."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PRIMAT_DAILY_ROW_BUDGET", None)
            quota.remember_reported_budget(20_000, kv=self.kv)
            self.assertEqual(quota.daily_row_budget(self.kv), 20_000)

    def test_miljovariabeln_vinner_over_allt(self):
        quota.remember_reported_budget(20_000, kv=self.kv)
        with mock.patch.dict(os.environ, {"PRIMAT_DAILY_ROW_BUDGET": "50000"}):
            self.assertEqual(quota.daily_row_budget(self.kv), 50_000)

    def test_ett_trasigt_varde_tolkas_aldrig_som_noll(self):
        """Noll hade betytt "kör aldrig igen", tyst, tills någon läste
        loggen."""
        for värde in ("", "0", "-5", "mycket"):
            with mock.patch.dict(os.environ, {"PRIMAT_DAILY_ROW_BUDGET": värde}):
                self.assertEqual(quota.daily_row_budget(self.kv), 100_000, värde)


class TaketPerKorning(unittest.TestCase):
    def test_tre_kedjor_ryms_under_dygnskvoten(self):
        """Kärnan i D5. Tre kedjor gånger det gamla taket 40 000 var 120 000
        mot en kvot på 100 000: ett tak över kvoten skyddar ingenting."""
        self.assertLessEqual(
            primat.DEFAULT_MAX_ROWS_PER_RUN * primat.PRIMAT_SCHEDULED_CHAINS,
            quota.DEFAULT_DAILY_ROW_BUDGET,
            "taket per körning gånger antalet schemalagda kedjor överstiger dygnskvoten")

    def test_taket_klipps_mot_det_som_ar_kvar_av_dygnet(self):
        kv = MinnesKV()
        quota.book_rows(95_000, kv=kv)
        with mock.patch.object(quota, "_kv", return_value=kv):
            provider = PrimatProvider("ICA", api_key="x")
        self.assertEqual(provider._max_rows, 5_000)

    def test_ett_uttryckligt_tak_klipps_inte(self):
        """En manuell körning som ber om ett tak får det taket. Klippningen
        gäller den härledda vägen, som nattjobbet går."""
        kv = MinnesKV()
        quota.book_rows(99_000, kv=kv)
        with mock.patch.object(quota, "_kv", return_value=kv):
            provider = PrimatProvider("ICA", api_key="x", max_rows=7)
        self.assertEqual(provider._max_rows, 7)


class ProvidernBokforMedanDenHamtar(unittest.TestCase):
    """Bokföringen sker UNDER körningen, inte efteråt. En import som dör
    halvvägs - 429, timeout, deploy mitt i - har ändå förbrukat sina rader,
    och en bokföring vid lyckad avslutning hade sagt att kvoten var orörd."""

    def _svar(self, sidor):
        def fake_call(method, path, params=None, body=None):
            if path == "/prices":
                return sidor.pop(0)
            return {"data": []}
        return fake_call

    def test_raderna_bokfors_innan_taket_stoppar_korningen(self):
        bokfört = []
        provider = PrimatProvider("ICA", api_key="x", max_rows=4,
                                  book_rows=bokfört.append)
        rad = {"chain": "ica", "store_id": "1", "product_id": "A", "name": "Vara",
               "price": 10.0, "effective_price": 10.0}
        sidor = [{"data": [dict(rad), dict(rad)], "next_cursor": "mer"},
                 {"data": [dict(rad), dict(rad)], "next_cursor": "mer"}]

        with mock.patch.object(PrimatProvider, "_call", side_effect=self._svar(sidor)):
            with self.assertRaises(ProviderBlockedError):
                provider.get_products("1")
        # Halva radbudgeten går till prisrader (max_rows=4 -> 2), så körningen
        # avbryts efter första sidan. De raderna ska vara bokförda.
        self.assertEqual(sum(bokfört), provider.rows_spent)
        self.assertGreater(sum(bokfört), 0)


if __name__ == "__main__":
    unittest.main()
