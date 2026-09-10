# -*- coding: utf-8 -*-
"""En hemlighet får aldrig nå ett publikt fält.

Bakgrund: en Primat-nyckel med radbrytning gav "Invalid header value
b'Bearer <nyckeln>'", som sparades rått och serverades av det PUBLIKA
/api/grocery/status. Den låg läsbar tills nyckeln byttes."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.secret_scrub import DOLT, scrub  # noqa: E402

NYCKEL = "primat_live_AbCd1234EfGh5678IjKl"


class Skrubbningen(unittest.TestCase):

    def test_det_verkliga_felet_ur_produktion(self):
        # Formen är hämtad ur den riktiga incidenten 2026-09-10 20:18.
        with mock.patch.dict(os.environ, {"PRIMAT_API_KEY": NYCKEL}):
            ut = scrub(f"Invalid header value b'Bearer {NYCKEL}\\n'")
        self.assertNotIn(NYCKEL, ut)
        self.assertIn(DOLT, ut)

    def test_nyckeln_doljs_aven_utan_att_vi_har_vardet(self):
        # En roterad nyckel i en gammal rad: värdet finns inte i miljön
        # längre, men mönstret ska ändå fånga den.
        ut = scrub(f"Invalid header value b'Bearer {NYCKEL}'")
        self.assertNotIn(NYCKEL, ut)

    def test_alla_hemliga_variabler_taks(self):
        hemlis = "en-mycket-lang-hemlighet-1234"
        for namn in ("PRIMAT_API_KEY", "MATJAKT_ADMIN_TOKEN", "STRIPE_SECRET_KEY"):
            with mock.patch.dict(os.environ, {namn: hemlis}):
                self.assertNotIn(hemlis, scrub(f"fel: {hemlis} avvisades"), namn)

    def test_blanksteg_i_miljovardet_hindrar_inte_traffen(self):
        # Nyckeln i Render bar en radbrytning; undantaget bar den utan.
        with mock.patch.dict(os.environ, {"PRIMAT_API_KEY": f"{NYCKEL}\\n"}):
            self.assertNotIn(NYCKEL, scrub(f"Bearer {NYCKEL} avvisades"))

    def test_langsta_hemligheten_ersatts_forst(self):
        # Annars delar en kort delsträng sönder en längre och lämnar svansen.
        with mock.patch.dict(os.environ, {"PRIMAT_API_KEY": "abcdefghijklmnop",
                                          "DABAS_API_KEY": "abcdefghijkl"}):
            ut = scrub("nyckeln abcdefghijklmnop nekades")
        self.assertNotIn("mnop", ut)

    def test_ett_kort_varde_ror_vi_inte(self):
        # "test" som premiumkod får inte sudda ordet ur varje felmeddelande.
        with mock.patch.dict(os.environ, {"MATJAKT_PREMIUM_CODE": "test"}):
            self.assertEqual(scrub("test misslyckades"), "test misslyckades")

    def test_vanliga_fel_forblir_lasbara(self):
        for text in ("Timeout efter 30 s", "HTTP 502 från Primat",
                     "sqlite3.OperationalError: database is locked"):
            self.assertEqual(scrub(text), text)

    def test_tomt_in_tomt_ut(self):
        for tom in (None, "", 0):
            self.assertEqual(scrub(tom), "")


if __name__ == "__main__":
    unittest.main()


class LagradeFelRensas(unittest.TestCase):
    """Raderna som skrevs innan skrubbningen fanns ligger kvar - och
    provider_status serverar dem via det PUBLIKA /api/grocery/status."""

    def test_en_lagrad_nyckel_rensas_vid_uppstart(self):
        import tempfile, time
        from services.grocery.store import GroceryStore
        with tempfile.TemporaryDirectory() as tmp:
            db = GroceryStore(Path(tmp) / "g.db")
            try:
                db.connection.execute(
                    "INSERT INTO grocery_collector_runs (chain, status, started_at, error_message) "
                    "VALUES (?, ?, ?, ?)",
                    ("ICA", "failed", time.time(), f"Invalid header value b'Bearer {NYCKEL}'"))
                db.connection.commit()
                antal = db.scrub_stored_errors()
                kvar = db.connection.execute(
                    "SELECT error_message FROM grocery_collector_runs").fetchone()[0]
            finally:
                db.close()
        self.assertEqual(antal, 1)
        self.assertNotIn(NYCKEL, kvar)
        self.assertIn(DOLT, kvar)

    def test_rena_rader_ror_vi_inte(self):
        import tempfile, time
        from services.grocery.store import GroceryStore
        with tempfile.TemporaryDirectory() as tmp:
            db = GroceryStore(Path(tmp) / "g.db")
            try:
                db.connection.execute(
                    "INSERT INTO grocery_collector_runs (chain, status, started_at, error_message) "
                    "VALUES (?, ?, ?, ?)", ("ICA", "failed", time.time(), "HTTP 502 från Primat"))
                db.connection.commit()
                self.assertEqual(db.scrub_stored_errors(), 0)
            finally:
                db.close()
