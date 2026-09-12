# -*- coding: utf-8 -*-
"""D10: backupen var rätt byggd och helt oövervakad - och aldrig återställd.

Backupen gör allt rätt på vägen ut: sqlites backup-API (säkert mot samtidiga
skrivare), `integrity_check`, en underkänd kopia raderas, sju set behålls.
Men `newest_age_seconds()` anropades bara av backuptråden SJÄLV, syntes
varken i `/api/health` eller i `storage_info()`, och det fanns inget
`test_backup.py` alls. Återställningen var en manuell månadsbock i
`docs/BACKUP.md`.

En backup ingen tittar på är ett antagande. En återställning ingen provat är
en förhoppning.

ACCEPTANSKRITERIET: ett test som tar backup av en fixturdatabas och STARTAR
mot återställningen. Det går inte att uppfylla genom att läsa filen och
jämföra bytes - servern startas på riktigt, i en egen process, mot den
återställda katalogen, och får svara på sina egna endpoints.
"""

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services import backup as backup_service  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]

# Fixturens kanariefågel: samma GTIN som canary.py bevakar för Willys, så
# testet också bevisar att en återställd databas duger åt kollen.
GTIN = "07340083443893"
PRIS = 16.50


def _fixturdatabas(data_dir: Path) -> Path:
    """En liten men ÄKTA grocery.db: butik, produkt och ett publicerat pris.

    Skriven genom GroceryStore och inte med rå SQL, så fixturen har samma
    schema som drift - en backup av något annat än den riktiga formen
    bevisar ingenting."""
    store = GroceryStore(data_dir / "grocery.db")
    try:
        butik = store.upsert_store(chain="Willys", external_store_id="2132",
                                   name="Willys Gävle Gestrike", city="Gävle",
                                   postal_code="80265", address="Gestrikevägen 1",
                                   latitude=None, longitude=None, active=True)
        from services.grocery.models import RawProduct
        produkt = store.find_or_create_product(RawProduct(
            chain="Willys", external_product_id="101233933_ST",
            name="Mellanmjölk Längre Hållbarhet", store_id="2132",
            store_name="Willys Gävle Gestrike", gtin=GTIN, brand="GARANT",
            size="1,5 l", quantity=1.5, unit="l", regular_price=PRIS,
            currency="SEK", fetched_at=time.time()))
        store.upsert_current_price(product_id=produkt.id, store_id=butik.id,
                                   regular_price=PRIS, fetched_at=time.time(),
                                   source="test:fixtur")
    finally:
        store.close(True)
    return data_dir / "grocery.db"


class BackupOchAterstallning(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="matjakt-backup-")
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name) / "data"
        self.data_dir.mkdir(parents=True)
        self.db = _fixturdatabas(self.data_dir)

    def test_backupen_tas_och_gar_igenom_integritetskollen(self):
        rapport = backup_service.take_backup(self.data_dir)
        self.assertIn("grocery.db", rapport["copied"])
        self.assertEqual(rapport["failed"], [])
        kopia = backup_service.newest_set(self.data_dir) / "grocery.db"
        self.assertTrue(kopia.exists())
        koll = sqlite3.connect(kopia).execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(koll, "ok")

    def test_en_underkand_kopia_sparas_inte(self):
        """Motprovet mot hela idén: en kopia som inte klarar
        integritetskollen får inte ligga kvar och se ut som en backup."""
        trasig = self.data_dir / "trasig.db"
        trasig.write_bytes(b"det har ar inte en databas")
        rapport = backup_service.take_backup(self.data_dir)
        self.assertIn("trasig.db", rapport["failed"])
        self.assertFalse((backup_service.newest_set(self.data_dir) / "trasig.db").exists())

    def test_aterstallningen_ger_tillbaka_datan(self):
        """Katastrofen, i den ordning den faktiskt sker: kopia, förlust,
        återställning."""
        backup_service.take_backup(self.data_dir)
        setet = backup_service.newest_set(self.data_dir)
        for extra in ("", "-wal", "-shm"):
            Path(str(self.db) + extra).unlink(missing_ok=True)
        self.assertFalse(self.db.exists())

        aterstalld = Path(self._tmp.name) / "aterstalld"
        aterstalld.mkdir()
        for fil in setet.glob("*.db"):
            shutil.copy2(fil, aterstalld / fil.name)

        store = GroceryStore(aterstalld / "grocery.db")
        try:
            rad = store.connection.execute(
                "SELECT p.name, cp.regular_price FROM grocery_current_prices cp "
                "JOIN grocery_products p ON p.id = cp.product_id WHERE p.gtin = ?",
                (GTIN,)).fetchone()
        finally:
            store.close(True)
        self.assertIsNotNone(rad, "den återställda databasen saknar priset")
        self.assertAlmostEqual(rad["regular_price"], PRIS)

    def test_kanariefageln_kanner_igen_en_aterstalld_databas(self):
        """Återställd data ska duga åt kollen som ska upptäcka trasig data."""
        from services.grocery import canary
        store = GroceryStore(self.db)
        try:
            resultat = canary.check(store, "Willys")
        finally:
            store.close(True)
        self.assertTrue(resultat["ok"], resultat.get("reason"))
        self.assertAlmostEqual(resultat["price"], PRIS)


class BackupensHalsa(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="matjakt-backuphalsa-")
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def test_ingen_backup_alls_ar_inte_ok(self):
        hälsa = backup_service.health(self.data_dir)
        self.assertFalse(hälsa["ok"])
        self.assertEqual(hälsa["sets"], 0)
        self.assertIsNone(hälsa["newestAgeHours"])
        self.assertIn("ingen säkerhetskopia", hälsa["reason"])

    def test_en_fars_backup_ar_ok(self):
        (self.data_dir / "tom.db").write_bytes(b"")
        sqlite3.connect(self.data_dir / "tom.db").execute("CREATE TABLE x (a)")
        backup_service.take_backup(self.data_dir)
        hälsa = backup_service.health(self.data_dir)
        self.assertTrue(hälsa["ok"], hälsa)
        self.assertEqual(hälsa["sets"], 1)
        self.assertLess(hälsa["newestAgeHours"], 1)
        self.assertIsNone(hälsa["reason"])

    def test_en_gammal_backup_larmar(self):
        gammal = backup_service.backup_dir(self.data_dir) / "20200101T000000Z"
        gammal.mkdir(parents=True)
        hälsa = backup_service.health(self.data_dir)
        self.assertFalse(hälsa["ok"])
        self.assertGreater(hälsa["newestAgeHours"], 36)
        self.assertIn("timmar gammal", hälsa["reason"])

    def test_larmet_gar_pa_en_dod_backup(self):
        from services.grocery import alerts
        problem = alerts.evaluate([], backup={"ok": False, "sets": 0,
                                              "reason": "ingen säkerhetskopia finns"})
        self.assertIn("backup:stale", problem)
        self.assertEqual(problem["backup:stale"]["severity"], "critical")

    def test_en_frisk_backup_larmar_inte(self):
        from services.grocery import alerts
        self.assertEqual(alerts.evaluate([], backup={"ok": True, "sets": 7,
                                                     "newestAgeHours": 2.0}), {})


class ServernStartarMotAterstallningen(unittest.TestCase):
    """Acceptanskriteriet: servern startas på riktigt mot den återställda
    katalogen, i en egen process, och får svara på sina egna endpoints.

    En jämförelse av filinnehåll hade bevisat att bytes kopierades. Det här
    bevisar det som faktiskt efterfrågas: att en återställd databas går att
    STARTA - rätt schema, rätt migreringsläge, läsbar för den riktiga
    servern och inte bara för testets egen SQLite-anslutning."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="matjakt-restore-")
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name) / "data"
        self.data_dir.mkdir(parents=True)
        _fixturdatabas(self.data_dir)

    def _aterstall(self) -> Path:
        backup_service.take_backup(self.data_dir)
        setet = backup_service.newest_set(self.data_dir)
        mål = Path(self._tmp.name) / "aterstalld"
        mål.mkdir()
        for fil in setet.glob("*.db"):
            shutil.copy2(fil, mål / fil.name)
        # Originalet är borta: servern nedan har inget annat att läsa än
        # återställningen.
        shutil.rmtree(self.data_dir)
        return mål

    @staticmethod
    def _ledig_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _starta(self, data_dir: Path):
        port = self._ledig_port()
        miljö = dict(os.environ)
        miljö.update({
            "MATJAKT_DATA_DIR": str(data_dir),
            "MATJAKT_TEST_MODE": "1",          # inga utgående anrop, se data_guard
            "MATJAKT_PORT": str(port),
            "MATJAKT_GROCERY_SCHEDULE_ENABLED": "0",
            "PYTHONUNBUFFERED": "1",
        })
        for hemlighet in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "SMTP_HOST",
                          "SMTP_USER", "SMTP_PASSWORD", "PRIMAT_API_KEY",
                          "DABAS_API_KEY", "MATJAKT_ADMIN_TOKEN"):
            miljö[hemlighet] = ""
        process = subprocess.Popen(
            [sys.executable, str(BACKEND / "api_server.py")], env=miljö,
            cwd=str(BACKEND), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(self._stoppa, process)
        return process, port

    def _stoppa(self, process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()

    def _hamta(self, process, port, path, timeout=120):
        """Pollar tills servern svarar - och ger upp direkt om processen
        dött, så ett startfel blir serverns eget felmeddelande i stället
        för nittio sekunders tystnad."""
        slut = time.time() + timeout
        senaste = None
        while time.time() < slut:
            if process.poll() is not None:
                self.fail(f"servern dog under start:\n{process.stdout.read()[-3000:]}")
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}{path}", timeout=10) as svar:
                    return json.loads(svar.read().decode("utf-8"))
            except (urllib.error.URLError, ConnectionError, OSError) as fel:
                senaste = fel
                time.sleep(0.3)
        self.fail(f"{path} svarade aldrig: {senaste}")

    def test_servern_startar_och_serverar_den_aterstallda_datan(self):
        aterstalld = self._aterstall()
        process, port = self._starta(aterstalld)

        hälsa = self._hamta(process, port, "/api/health")
        self.assertTrue(hälsa.get("ok"), hälsa)
        # Backupblocket finns i health - D10:s andra halva, kontrollerad på
        # en riktigt startad server och inte bara som ett funktionsanrop.
        self.assertIn("backup", hälsa)
        self.assertIn("newestAgeHours", hälsa["backup"])

        # Och datan: den återställda produkten ska gå att prissätta.
        status = self._hamta(process, port, "/api/grocery/status")
        self.assertGreaterEqual(status.get("totalProducts", 0), 1,
                                "den startade servern ser ingen produkt i återställningen")

    def test_en_tom_katalog_ger_inte_samma_svar(self):
        """Motprovet: testet ovan måste kunna FAILA. En server som startar
        mot en tom katalog svarar också ok på /api/health - det är antalet
        produkter som skiljer en återställning från ett tomt blad."""
        tom = Path(self._tmp.name) / "tom"
        tom.mkdir()
        process, port = self._starta(tom)
        status = self._hamta(process, port, "/api/grocery/status")
        self.assertEqual(status.get("totalProducts", 0), 0)


if __name__ == "__main__":
    unittest.main()
