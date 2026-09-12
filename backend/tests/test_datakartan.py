# -*- coding: utf-8 -*-
"""Datakartan prövas mot koden, inte mot minnet av hur koden såg ut.

WHY. `docs/DATA_MAP.md` och `docs/RETENTION.md` är grunden för
integritetspolicyn och App Store-etiketterna. De skrevs 2026-09-06 och blev
sedan kvar medan koden gick vidare. När I3 skrev om
`frontend/integritetspolicy.html` MOT KÄLLKODEN föll tre rader isär:

  * Klient-IP påstods ligga "bara i processminne". Rate limit-räknarna är
    persistenta sedan dess: en egen SQLite-fil i datakatalogen, som därmed
    följer med i varje backupset.
  * Samma fel i retentionstabellen: "i processminne, max 1 timme ... vid
    omstart". Att de ÖVERLEVER omstarten är hela poängen.
  * Analytics påstods vara räknare i `prices.db`. Det finns numera en tabell
    med en rad PER KONTO, i kontodatabasen. Det är en materiell skillnad för
    en datakarta, inte en detalj.

En datakarta som beskriver fjolårets kod är värre än ingen: den är ett
löfte till användaren, och den blir en felaktig App Store-etikett.

ACCEPTANSKRITERIET. Varje påstående som testas här är förankrat i den kod
som äger det - räknaren skrivs och läses på riktigt, backupen tas på
riktigt, tabellerna läses ur `sqlite_master`, kontot raderas på riktigt.
Testet jämför alltså inte dokumentet med en andra kopia av samma text; det
jämför dokumentet med verkligheten. Skrivs koden om igen faller raden här,
och dokumentet måste följa med.

Gränsen åt andra hållet gäller också: exportvyn i appen SAKNAS, och raden
får säga det bara så länge ingen fil under `frontend/app/` anropar
endpointen. Den dagen UI:t byggs blir den här raden röd.
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services import backup as backup_service  # noqa: E402
from services.accounts import AccountStore, ratelimit  # noqa: E402
from services.accounts.data_export import CATEGORIES  # noqa: E402
from services.analytics import AnalyticsStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA_MAP = ROOT / "docs" / "DATA_MAP.md"
RETENTION = ROOT / "docs" / "RETENTION.md"
API_SERVER = ROOT / "backend" / "api_server.py"
APP_DIR = ROOT / "frontend" / "app"


def _rad(dokument: Path, nyckel: str) -> str:
    """Tabellraden vars första cell är `nyckel`. Saknas den är det ett fel i
    sig - en datakarta utan raden är inte en rättad datakarta."""
    text = dokument.read_text(encoding="utf-8")
    for rad in text.splitlines():
        if rad.startswith(f"| {nyckel} |"):
            return rad
    raise AssertionError(f"raden '{nyckel}' saknas i {dokument.name}")


class KlientIpRaden(unittest.TestCase):
    """Rate limit-räknarna: var de ligger, vem de namnger, vart de följer med."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        self.path = self.data_dir / "ratelimit.db"
        ratelimit.configure(self.path)
        ratelimit.reset()
        self.addCleanup(ratelimit.disable)
        self.rad = _rad(DATA_MAP, "Klient-IP")

    def test_rakarna_ligger_pa_disk_med_identifieraren_i_klartext(self):
        # Koden först: en enda träff ska lämna en rad på disk, och raden ska
        # bära identifieraren. Det är DEN detaljen som gör filen till
        # persondata och därmed en rad i datakartan.
        ratelimit.check("login", "203.0.113.7", "nagon@example.com")
        self.assertTrue(self.path.exists(), "ratelimit.db skapades inte i datakatalogen")
        with sqlite3.connect(self.path) as connection:
            rader = connection.execute(
                "SELECT action, identifier FROM rate_limit_hits ORDER BY identifier").fetchall()
        self.assertEqual(rader, [("login", "203.0.113.7"), ("login", "nagon@example.com")])

        # Sedan dokumentet.
        self.assertNotIn("bara i processminne", self.rad,
                         "datakartan påstår fortfarande att rate limit bara är minne")
        for ord in ("ratelimit.db", "rate_limit_hits"):
            self.assertIn(ord, self.rad, f"datakartan namnger inte {ord}")

    def test_filen_foljer_med_i_backupsetet(self):
        ratelimit.check("login", "203.0.113.7")
        AccountStore(self.data_dir / "matjakt.db").close()
        backup_service.take_backup(self.data_dir)
        senaste = backup_service.newest_set(self.data_dir)
        self.assertIsNotNone(senaste, "inget backupset togs")
        kopierade = {fil.name for fil in senaste.iterdir()}
        self.assertIn("ratelimit.db", kopierade,
                      "ratelimit.db kom inte med i backupsetet - glob('*.db') tar den")
        self.assertIn("backup", self.rad.lower(),
                      "datakartan nämner inte att filen följer med i backupen")

    def test_langsta_fonstret_ar_en_timme_i_koden_och_i_bada_dokumenten(self):
        langsta = max(fonster for _, fonster in ratelimit.LIMITS.values())
        self.assertEqual(langsta, 3600)
        self.assertIn("3600", self.rad, "datakartan säger inte när raderna rensas")
        self.assertIn("timme", _rad(RETENTION, "Rate limit-räknare"))


class RetentionRaden(unittest.TestCase):
    """Retentionstabellens rad ska säga motsatsen till vad den sa."""

    def setUp(self):
        self.rad = _rad(RETENTION, "Rate limit-räknare")

    def test_raden_sager_inte_langre_processminne_och_omstart(self):
        self.assertNotIn("processminne", self.rad)
        self.assertNotIn("vid omstart", self.rad)

    def test_raden_sager_att_rakarna_overlever_omstarten(self):
        self.assertIn("ratelimit.db", self.rad)
        self.assertIn("överlever", self.rad.lower(),
                      "retentionstabellen säger inte att räknarna överlever en omstart")


class AnalyticsRaden(unittest.TestCase):
    """Två tabeller, i kontodatabasen, varav en per konto."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.accounts = AccountStore(Path(self._tmp.name) / "matjakt.db")
        self.addCleanup(self.accounts.close)
        self.analytics = AnalyticsStore(self.accounts.connection, lock=self.accounts.lock)
        self.rad = _rad(DATA_MAP, "Analytics-händelser")

    def test_tabellerna_ligger_i_kontodatabasen_och_star_i_kartan(self):
        # Samma anslutning som users: analysdatan ligger i kontodatabasen,
        # inte i priscachen. Tabellnamnen läses ur databasen, inte ur koden.
        tabeller = {namn for (namn,) in self.accounts.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'analytics%'")}
        self.assertEqual(tabeller, {"analytics_daily", "analytics_user_days"})
        anvandare = {namn for (namn,) in self.accounts.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'")}
        self.assertEqual(anvandare, {"users"}, "analysen delar inte fil med kontona")

        for tabell in sorted(tabeller):
            self.assertIn(tabell, self.rad, f"datakartan namnger inte {tabell}")
        self.assertNotIn("prices.db", self.rad,
                         "datakartan påstår fortfarande att analysen ligger i priscachen")
        self.assertNotIn("KV-cache", self.rad)

    def test_analysdatan_raderas_med_kontot(self):
        token, _ = self.accounts.register("radera@example.com", "hemligt123")
        user_id = self.accounts.connection.execute(
            "SELECT id FROM users WHERE email = ?", ("radera@example.com",)).fetchone()[0]
        self.analytics.record("vecka_skapad", user_id=user_id)
        self.assertEqual(len(self.analytics.user_days(user_id)), 1)

        self.accounts.delete_account(token)
        self.assertEqual(self.analytics.user_days(user_id), [],
                         "kontots mätrader låg kvar efter raderingen")
        self.assertIn("raderas med kontot", self.rad,
                      "datakartan säger inte att analysdatan följer med kontot i graven")


    def test_ingen_rad_pastar_langre_att_analysen_saknar_identitet(self):
        """Principen och rättighetstabellen bar samma föråldrade fakta.

        `analytics_user_days` har en `user_id`-kolumn. Så länge den finns får
        varken principen överst eller raden om invändning påstå att mätningen
        är identitetslös rakt av."""
        kolumner = {rad[1] for rad in self.accounts.connection.execute(
            "PRAGMA table_info(analytics_user_days)")}
        self.assertIn("user_id", kolumner)

        text = DATA_MAP.read_text(encoding="utf-8")
        self.assertNotIn("namngivna räknare utan identitet", text,
                         "principen påstår fortfarande att all mätning saknar identitet")
        invandning = _rad(DATA_MAP, "Invändning mot analytics")
        self.assertIn("analytics_user_days", invandning,
                      "rättighetstabellen nämner inte kontoraderna")


class ExportRaden(unittest.TestCase):
    """Endpointen finns; knappen gör det inte."""

    def setUp(self):
        self.rad = _rad(DATA_MAP, "Tillgång/export")

    def test_endpointen_finns_med_sju_kategorier(self):
        self.assertIn('"/api/account/export"', API_SERVER.read_text(encoding="utf-8"))
        self.assertEqual(len(CATEGORIES), 7)
        self.assertIn("/api/account/export", self.rad,
                      "datakartan känner fortfarande bara till /api/account/state")

    def test_ui_saknas_fortfarande_och_raden_sager_det(self):
        # Åt andra hållet: den dagen någon bygger knappen ska den här raden
        # bli röd, så att datakartan inte blir kvar i fjolårets sanning igen.
        anropare = [fil.relative_to(ROOT) for fil in APP_DIR.rglob("*")
                    if fil.is_file() and fil.suffix in (".js", ".mjs", ".html")
                    and "account/export" in fil.read_text(encoding="utf-8", errors="replace")]
        self.assertEqual(anropare, [], f"exportvyn finns nu ({anropare}) - uppdatera datakartan")
        self.assertIn("saknas", self.rad, "datakartan säger inte att UI:t saknas")


if __name__ == "__main__":
    unittest.main()
