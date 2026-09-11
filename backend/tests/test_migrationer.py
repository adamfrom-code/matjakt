# -*- coding: utf-8 -*-
"""K6: migrationerna, och vägen tillbaka från en release som just rullats bort.

Schemat växer med `ALTER TABLE ... ADD COLUMN` på fem ställen — konton,
butiksdata, recept, hushåll, priscache — var och en i en egen try/except
eller ett eget `PRAGMA table_info`-varv. Det fungerar framåt. Frågan ingen
hade ställt är vad som händer BAKÅT, och den frågan blev akut i samma stund
som K4 lade in ett `rollback`-jobb som startar den föregående live-deployen
av sig själv när rökprovet faller.

Efter en återställning kör GAMMAL KOD mot en databas som NY KOD redan har
migrerat. Det går bra — men bara så länge varje migration är rent additiv och
varje tillagd kolumn är nullbar eller har ett DEFAULT. Tappar någon en
kolumn, döper om en, eller lägger till en kolumn utan default som den gamla
koden inte skriver, så är återställningen inte en väg tillbaka utan en andra
incident.

Uppdragets acceptans är "ett test per lager mot en fixtur-DB av föregående
version". Fixturerna ligger i `fixturer/scheman/*.sql` — hela schemat som det
ser ut i den här releasen, dumpat ur `sqlite_master`, inte en `.db` (spårade
databasfiler är förbjudna i det här repot, av goda skäl). Nästa release kör
alltså sina migrationer mot DEN HÄR versionens verkliga schema, med
verkliga rader i, och de här testerna säger till om något inte överlever.

    Regenerera efter en avsiktlig schemaändring:
        python backend/tests/test_migrationer.py --spara

och lägg de nya .sql-filerna i SAMMA commit som koden som ändrade schemat.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HÄR = Path(__file__).resolve().parent
sys.path.insert(0, str(HÄR.parent))

from services.accounts.store import AccountStore  # noqa: E402
from services.grocery import GroceryStore  # noqa: E402
from services.household.store import HouseholdStore  # noqa: E402
from services.pricing.store import PriceCacheStore  # noqa: E402
from services.recipes.store import RecipeStore  # noqa: E402

SCHEMAN = HÄR / "fixturer" / "scheman"

# Ett lager per rad: (fixturnamn, lagrets klass, tabell att skriva en rad i,
# raden som föregående version skrev). Raden är inte pynt - den är skillnaden
# mellan "schemat överlevde" och "datan överlevde", och det är den senare
# frågan en människa ställer efter en återställning.
LAGER = [
    ("konton", AccountStore, "users", {
        "email": "foregaende@exempel.test", "password_hash": "hash", "salt": "salt",
        "premium": 1, "created_at": "2026-09-01T00:00:00+00:00",
    }),
    ("butiksdata", GroceryStore, "grocery_products", {
        "name": "Mellanmjölk 1,5l", "normalized_key": "mellanmjolk-1-5l",
        "gtin": "07340083443893", "created_at": 1000.0, "updated_at": 1000.0,
    }),
    ("recept", RecipeStore, "recipes", {
        "id": "kyckling-ris", "slug": "kyckling-med-ris", "name": "Kyckling med ris",
        "servings": 4, "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
    }),
    ("hushall", HouseholdStore, "households", {
        "name": "Familjen", "created_at": "2026-09-01T00:00:00+00:00", "created_by": 1,
    }),
    ("priscache", PriceCacheStore, "product_cache", {
        "chain": "Willys", "query": "mjölk", "zip": "80281",
        "products_json": "[]", "updated_at": 1000.0,
    }),
]


def schema(anslutning):
    """{tabell: {kolumnnamn}} för allt utom sqlite:s egna tabeller."""
    tabeller = [rad[0] for rad in anslutning.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {tabell: {rad[1] for rad in anslutning.execute(f"PRAGMA table_info({tabell})")}
            for tabell in tabeller}


def bygg_foregaende(väg: Path, fixtur: str):
    """En databas med FÖREGÅENDE versions schema, ur den committade .sql-filen."""
    anslutning = sqlite3.connect(väg)
    anslutning.executescript((SCHEMAN / f"{fixtur}.sql").read_text(encoding="utf-8"))
    anslutning.commit()
    return anslutning


def skriv(anslutning, tabell: str, rad: dict):
    kolumner = ", ".join(rad)
    platser = ", ".join("?" for _ in rad)
    anslutning.execute(f"INSERT INTO {tabell} ({kolumner}) VALUES ({platser})", tuple(rad.values()))
    anslutning.commit()


class Lagerprov(unittest.TestCase):
    """Gemensam uppsättning: fixtur-DB, en rad i, sedan dagens kod på den."""

    def _migrera(self, fixtur, klass, tabell, rad):
        katalog = tempfile.TemporaryDirectory()
        self.addCleanup(katalog.cleanup)
        väg = Path(katalog.name) / f"{fixtur}.db"

        gammal = bygg_foregaende(väg, fixtur)
        före = schema(gammal)
        skriv(gammal, tabell, rad)
        gammal.close()

        klass(väg)  # dagens kod öppnar den - här körs migrationerna

        efter_anslutning = sqlite3.connect(väg)
        efter_anslutning.row_factory = sqlite3.Row
        self.addCleanup(efter_anslutning.close)
        return före, schema(efter_anslutning), efter_anslutning


class ForegaendeVersionsSchemaOverlever(Lagerprov):
    """Framåt: dagens kod mot föregående versions databas."""

    def test_varje_lager_oppnar_en_foregaende_databas(self):
        for fixtur, klass, tabell, rad in LAGER:
            with self.subTest(lager=fixtur):
                self._migrera(fixtur, klass, tabell, rad)

    def test_ingen_tabell_och_ingen_kolumn_forsvinner(self):
        # Det här är villkoret som gör en återställning ofarlig. En borttagen
        # eller omdöpt kolumn syns inte framåt - dagens kod slutade ju läsa
        # den - men den gamla koden läser den fortfarande.
        for fixtur, klass, tabell, rad in LAGER:
            with self.subTest(lager=fixtur):
                före, efter, _ = self._migrera(fixtur, klass, tabell, rad)
                for tab, kolumner in före.items():
                    self.assertIn(tab, efter, f"{fixtur}: tabellen {tab} finns inte kvar")
                    saknade = kolumner - efter[tab]
                    self.assertEqual(saknade, set(),
                                     f"{fixtur}.{tab}: kolumnerna {sorted(saknade)} är borta. "
                                     f"En återställning till föregående release läser dem "
                                     f"fortfarande - migrationen måste vara additiv.")

    def test_raden_foregaende_version_skrev_finns_kvar_med_sina_varden(self):
        # Ett schema kan överleva en migration som ändå tömmer en tabell.
        for fixtur, klass, tabell, rad in LAGER:
            with self.subTest(lager=fixtur):
                *_, anslutning = self._migrera(fixtur, klass, tabell, rad)
                rader = anslutning.execute(f"SELECT * FROM {tabell}").fetchall()
                self.assertEqual(len(rader), 1, f"{fixtur}: raden överlevde inte migrationen")
                for kolumn, värde in rad.items():
                    self.assertEqual(rader[0][kolumn], värde, f"{fixtur}.{tabell}.{kolumn}")


class AterstallningenHarEnVagTillbaka(Lagerprov):
    """Bakåt: den gamla koden mot den migrerade databasen.

    Det här är det K4:s `rollback`-jobb faktiskt gör, automatiskt, mitt i
    natten. Den gamla koden känner bara till föregående versions kolumner och
    skriver bara dem.
    """

    def test_en_insert_med_bara_gamla_kolumner_gar_fortfarande_igenom(self):
        # Faller det här har någon lagt till en NOT NULL-kolumn utan DEFAULT,
        # och då är återställningen inte en väg tillbaka utan en andra incident.
        for fixtur, klass, tabell, rad in LAGER:
            with self.subTest(lager=fixtur):
                *_, anslutning = self._migrera(fixtur, klass, tabell, rad)
                bakåt = {nyckel: (f"{värde}-2" if isinstance(värde, str) else värde)
                         for nyckel, värde in rad.items()}
                try:
                    skriv(anslutning, tabell, bakåt)
                except sqlite3.IntegrityError as fel:
                    self.fail(f"{fixtur}.{tabell}: den gamla kodens INSERT avvisas efter "
                              f"migrationen ({fel}). En ny kolumn saknar DEFAULT.")

    def test_en_select_med_bara_gamla_kolumner_gar_fortfarande_att_lasa(self):
        for fixtur, klass, tabell, rad in LAGER:
            with self.subTest(lager=fixtur):
                *_, anslutning = self._migrera(fixtur, klass, tabell, rad)
                kolumner = ", ".join(rad)
                läst = anslutning.execute(f"SELECT {kolumner} FROM {tabell}").fetchall()
                self.assertEqual(len(läst), 1)


class MigrationernaKorsTvaGangerUtanSkada(Lagerprov):
    """Idempotens. Render startar om, en deploy körs om, ett rollback följs av
    en ny framåtdeploy - samma migration körs flera gånger mot samma databas.
    """

    def test_samma_lager_oppnas_tva_ganger_i_rad(self):
        for fixtur, klass, tabell, rad in LAGER:
            with self.subTest(lager=fixtur):
                katalog = tempfile.TemporaryDirectory()
                self.addCleanup(katalog.cleanup)
                väg = Path(katalog.name) / f"{fixtur}.db"
                gammal = bygg_foregaende(väg, fixtur)
                skriv(gammal, tabell, rad)
                gammal.close()
                klass(väg)
                klass(väg)   # andra gången: inget ALTER får kastas om
                anslutning = sqlite3.connect(väg)
                self.addCleanup(anslutning.close)
                antal = anslutning.execute(f"SELECT COUNT(*) FROM {tabell}").fetchone()[0]
                self.assertEqual(antal, 1, f"{fixtur}: andra öppningen rörde datan")


class SessionsmigreringenDubbelhashar_Inte(unittest.TestCase):
    """DEN ENDA migrationen i repot som skriver om DATA, inte bara schema.

    `_migrate_session_tokens_to_hashes` hashar varje sessionstoken som ännu
    ligger i klartext. Den är avsiktligt INTE reversibel: rullar man tillbaka
    till en release som jämför råa tokens loggas alla ut. Det är ett pris som
    är betalt en gång och aldrig behöver betalas igen - men bara så länge
    migrationen är idempotent. Körs den två gånger och hashar hashen låses
    alla ut för gott, och det utan att någon rad ser annorlunda ut.
    """

    def test_en_redan_hashad_token_hashas_inte_en_gang_till(self):
        katalog = tempfile.TemporaryDirectory()
        self.addCleanup(katalog.cleanup)
        väg = Path(katalog.name) / "konton.db"
        AccountStore(väg)

        anslutning = sqlite3.connect(väg)
        self.addCleanup(anslutning.close)
        anslutning.execute("INSERT INTO users (email, password_hash, salt, created_at) "
                           "VALUES ('a@exempel.test', 'h', 's', '2026-09-01T00:00:00+00:00')")
        anslutning.execute("INSERT INTO sessions (token, user_id, expires_at) "
                           "VALUES ('rå-token-i-klartext', 1, '2030-01-01T00:00:00+00:00')")
        anslutning.commit()
        anslutning.close()

        AccountStore(väg)   # migrerar: rå -> hash
        efter_ett = sqlite3.connect(väg).execute("SELECT token FROM sessions").fetchone()[0]
        self.assertEqual(len(efter_ett), 64, "tokenet hashades inte")

        AccountStore(väg)   # igen: får INTE hasha hashen
        efter_två = sqlite3.connect(väg).execute("SELECT token FROM sessions").fetchone()[0]
        self.assertEqual(efter_två, efter_ett,
                         "migrationen dubbelhashade - varje inloggad användare är utlåst")


class FixturernaFinnsOchAktuella(unittest.TestCase):
    def test_ett_schema_per_lager(self):
        for fixtur, *_ in LAGER:
            self.assertTrue((SCHEMAN / f"{fixtur}.sql").exists(),
                            f"fixturer/scheman/{fixtur}.sql saknas - kör "
                            f"`python backend/tests/test_migrationer.py --spara`")

    def test_ingen_sparad_databasfil_smog_in(self):
        # Spårade databasfiler är förbjudna i det här repot (kontodatabasen
        # låg i det publika repot i en vecka). Fixturerna är .sql, aldrig .db.
        självmål = [p.name for p in SCHEMAN.iterdir()
                    if p.suffix in (".db", ".sqlite", ".sqlite3")]
        self.assertEqual(självmål, [], "en databasfil ligger bland schemafixturerna")


def spara_scheman():
    """Dumpar varje lagers schema som det ser ut NU. Körs för hand."""
    with tempfile.TemporaryDirectory() as tmp:
        SCHEMAN.mkdir(parents=True, exist_ok=True)
        for fixtur, klass, *_ in LAGER:
            väg = Path(tmp) / f"{fixtur}.db"
            klass(väg)
            anslutning = sqlite3.connect(väg)
            rader = [rad[0] for rad in anslutning.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL "
                "AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name")]
            anslutning.close()
            (SCHEMAN / f"{fixtur}.sql").write_text(
                ";\n".join(rad.strip() for rad in rader) + ";\n", encoding="utf-8")
            print(f"  {fixtur}.sql: {len(rader)} objekt")


if __name__ == "__main__":
    if "--spara" in sys.argv:
        os.environ.setdefault("MATJAKT_TEST_MODE", "1")
        print("Sparar dagens scheman som fixturer:")
        spara_scheman()
    else:
        unittest.main()
