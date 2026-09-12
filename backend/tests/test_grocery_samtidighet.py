# -*- coding: utf-8 -*-
"""D8: SQLite utan busy_timeout, och schemamigrering per request.

Tre fel som alla ser ut som otur när de slår till:

  * `busy_timeout` sattes aldrig. SQLites standard är noll - den andra
    skrivaren får "database is locked" direkt. `bulk_transaction` håller
    skrivlåset under hela publiceringen av ~10 000 upserts, så varje anrop
    som råkade skriva under den minuten dog mitt i nattens import.
  * Varje `open_store()` körde hela schemat och hela migreringen: fyra
    PRAGMA table_info, två executescript och en seedning av kedjetabellen -
    per HTTP-request som rörde grocery.
  * `clear_cache()` är in-process. Med två instanser serverade den ena gamla
    priser i fem minuter efter den andras import.

ACCEPTANSKRITERIET är samtidighetstestet: en skrivning UNDER en pågående
publicering. Motprovet körs med `busy_timeout` avstängt, så testet bevisar
vad som faktiskt fixade det och inte bara att det råkar fungera.
"""

import sqlite3
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
DATA_DIR = Path(isolated_test_data_dir())

from services.grocery import api as grocery_api  # noqa: E402
from services.grocery import store as store_module  # noqa: E402
from services.grocery.store import GroceryStore  # noqa: E402


def _ny_databas(namn: str) -> Path:
    sökväg = DATA_DIR / namn
    for extra in ("", "-wal", "-shm"):
        Path(str(sökväg) + extra).unlink(missing_ok=True)
    store_module._SCHEMA_READY.discard(str(sökväg))
    return sökväg


class SkrivningUnderPublicering(unittest.TestCase):
    """En publicering håller skrivlåset. Vad händer med den som skriver
    samtidigt?"""

    def setUp(self):
        self.db = _ny_databas("samtidighet.db")
        self.addCleanup(store_module.release_thread_stores)

    def _skriv_under_publicering(self, busy_timeout_ms: int):
        """Startar en publicering som håller låset, låter en ANNAN anslutning
        skriva mitt i den, och returnerar vad den skrivningen råkade ut för.

        Publiceringen släpper låset strax efter att den andra skrivaren
        BÖRJAT skriva - inte när den är klar. Det är hela poängen: den som
        väntar ska få låset när publiceringen commitar, och den som inte
        väntar ska ha dött långt innan dess."""
        publiceraren = GroceryStore(self.db)
        self.addCleanup(publiceraren.close, True)
        original = store_module.BUSY_TIMEOUT_MS
        store_module.BUSY_TIMEOUT_MS = busy_timeout_ms
        try:
            skribenten = GroceryStore(self.db)
        finally:
            store_module.BUSY_TIMEOUT_MS = original
        self.addCleanup(skribenten.close, True)

        låset_taget = threading.Event()
        försöker = threading.Event()
        försöket_klart = threading.Event()
        resultat = {}

        def publicera():
            with publiceraren.bulk_transaction():
                publiceraren.connection.execute(
                    "INSERT INTO grocery_stores (chain, external_store_id, name, active, created_at, updated_at) "
                    "VALUES ('Willys', 'pub', 'Publicering', 1, 0, 0)")
                låset_taget.set()
                försöker.wait(timeout=10)
                # Den som saknar busy_timeout har redan dött här; den som
                # har det står och väntar på commiten nedan.
                försöket_klart.wait(timeout=0.3)

        def skriv():
            låset_taget.wait(timeout=10)
            försöker.set()
            try:
                skribenten.connection.execute(
                    "INSERT INTO grocery_stores (chain, external_store_id, name, active, created_at, updated_at) "
                    "VALUES ('Hemköp', 'samtidig', 'Samtidig', 1, 0, 0)")
                skribenten.connection.commit()
                resultat["fel"] = None
            except sqlite3.OperationalError as error:
                resultat["fel"] = str(error)
            finally:
                försöket_klart.set()

        trådar = [threading.Thread(target=publicera), threading.Thread(target=skriv)]
        for tråd in trådar:
            tråd.start()
        for tråd in trådar:
            tråd.join(timeout=40)
        self.assertFalse(any(t.is_alive() for t in trådar), "trådarna hängde")
        return resultat.get("fel", "kördes aldrig")

    def test_skrivning_under_publicering_vantar_i_stallet_for_att_do(self):
        """D8:s acceptanskriterium. Skrivningen ska vänta ut publiceringen."""
        fel = self._skriv_under_publicering(store_module.BUSY_TIMEOUT_MS)
        self.assertIsNone(fel, f"skrivningen dog i stället för att vänta: {fel}")
        rader = GroceryStore(self.db).connection.execute(
            "SELECT COUNT(*) FROM grocery_stores WHERE external_store_id IN ('pub', 'samtidig')"
        ).fetchone()[0]
        self.assertEqual(rader, 2, "båda skrivningarna ska finnas kvar")

    def test_utan_busy_timeout_dor_samma_skrivning(self):
        """Motprovet: det är PRAGMA:n som gör skillnaden, inte turen."""
        fel = self._skriv_under_publicering(0)
        self.assertIsNotNone(fel, "utan busy_timeout ska skrivningen dö direkt")
        self.assertIn("locked", fel)

    def test_pragman_ar_satt_pa_anslutningen(self):
        store = GroceryStore(self.db)
        self.addCleanup(store.close, True)
        self.assertEqual(store.connection.execute("PRAGMA busy_timeout").fetchone()[0],
                         store_module.BUSY_TIMEOUT_MS)


class SchemaEnGangPerProcess(unittest.TestCase):
    """Schemat är idempotent. Idempotent är inte samma sak som gratis."""

    def setUp(self):
        self.db = _ny_databas("schema.db")
        self.räknare = {"init": 0, "migrate": 0}
        for namn in ("_init_schema", "_migrate_schema"):
            original = getattr(GroceryStore, namn)
            nyckel = namn.strip("_").split("_")[0]

            def räknande(self_, _original=original, _nyckel=nyckel):
                self.räknare[_nyckel] += 1
                return _original(self_)

            setattr(GroceryStore, namn, räknande)
            self.addCleanup(setattr, GroceryStore, namn, original)
        self.addCleanup(store_module.release_thread_stores)

    def test_tio_oppningar_ger_en_migrering(self):
        for _ in range(10):
            GroceryStore(self.db).close(True)
        self.assertEqual(self.räknare, {"init": 1, "migrate": 1})

    def test_en_ny_fil_pa_samma_sokvag_far_sitt_schema(self):
        """Minnet är inte sanningen. Läggs en ny (eller återställd) databas
        på samma sökväg ska schemat läggas upp igen - annars skulle en
        återställning från backup ge en process som tror att tabellerna
        finns."""
        GroceryStore(self.db).close(True)
        self.assertEqual(self.räknare["init"], 1)
        for extra in ("", "-wal", "-shm"):
            Path(str(self.db) + extra).unlink(missing_ok=True)
        GroceryStore(self.db).close(True)
        self.assertEqual(self.räknare["init"], 2)


class EnAnslutningPerTrad(unittest.TestCase):
    def setUp(self):
        self.db = _ny_databas("pool.db")
        self._original = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db
        self.addCleanup(setattr, grocery_api, "DB_PATH", self._original)
        self.addCleanup(store_module.release_thread_stores)

    def test_samma_trad_far_samma_anslutning(self):
        self.assertIs(grocery_api.open_store(), grocery_api.open_store())

    def test_en_annan_trad_far_en_egen(self):
        min_egen = grocery_api.open_store()
        andras = {}

        def i_tråden():
            andras["store"] = grocery_api.open_store()
            store_module.release_thread_stores()

        tråd = threading.Thread(target=i_tråden)
        tråd.start()
        tråd.join(timeout=10)
        self.assertIsNot(andras["store"], min_egen)

    def test_close_pa_en_delad_store_stanger_inte_den_yttre(self):
        """Mönstret i api.py är `store = open_store()` med ett
        `finally: store.close()`, och två sådana kan ligga i varandra. Den
        inre får inte dra undan anslutningen för den yttre."""
        yttre = grocery_api.open_store()
        inre = grocery_api.open_store()
        inre.close()
        self.assertFalse(yttre.closed)
        yttre.connection.execute("SELECT COUNT(*) FROM grocery_products").fetchone()

    def test_en_ersatt_databasfil_ger_en_ny_anslutning(self):
        första = grocery_api.open_store()
        for extra in ("", "-wal", "-shm"):
            Path(str(self.db) + extra).unlink(missing_ok=True)
        andra = grocery_api.open_store()
        self.assertIsNot(första, andra)
        self.assertTrue(första.closed)


class CachenSjalvlaker(unittest.TestCase):
    """En annan process importerar. Hur lång tid tar det innan den här
    processen slutar servera gårdagens priser?"""

    def setUp(self):
        self.db = _ny_databas("cache.db")
        self._original = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db
        self.addCleanup(setattr, grocery_api, "DB_PATH", self._original)
        self.addCleanup(store_module.release_thread_stores)
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)

    def _tiden_gar(self):
        """TTL:n för dataversionen passerar. Att sätta tidsstämpeln i
        stället för att sova två sekunder är samma sak för koden och två
        sekunder kortare för den som kör sviten."""
        grocery_api._version_state["at"] = 0.0

    def _annan_process_importerar(self):
        """En HELT egen anslutning avslutar en körning - det är vad en annan
        Render-instans gör, och den här processen får inget besked."""
        annan = GroceryStore(self.db)
        try:
            körning = annan.start_collector_run(chain="Willys")
            annan.finish_collector_run(körning.id, status="success", prices_updated=1)
        finally:
            annan.close(True)

    def test_en_trafferad_post_serveras_tills_datan_andras(self):
        """Motprovet först: utan en dataändring ska cachen fortsätta svara.
        En cache som alltid missar är inte en självläkande cache."""
        grocery_api._cache_set("veckan", {"total": 511})
        self._tiden_gar()
        self.assertEqual(grocery_api._cache_get("veckan"), {"total": 511})

    def test_en_import_i_en_annan_process_ogiltigforklarar_posten(self):
        grocery_api._cache_set("veckan", {"total": 511})
        self.assertEqual(grocery_api._cache_get("veckan"), {"total": 511})
        self._annan_process_importerar()
        self._tiden_gar()
        self.assertIsNone(grocery_api._cache_get("veckan"),
                          "posten bär en dataversion som inte längre gäller")

    def test_dataversionen_lases_inte_per_cacheuppslag(self):
        """Stämpeln kostar ett par COUNT över katalogen. Läst per uppslag
        vore den ett värre problem än den inaktuella cachen den löser."""
        store = grocery_api.open_store()
        original = type(store).data_version
        antal = {"n": 0}

        def räknande(self_):
            antal["n"] += 1
            return original(self_)

        type(store).data_version = räknande
        self.addCleanup(setattr, type(store), "data_version", original)
        grocery_api.clear_cache()
        grocery_api._cache_set("a", 1)
        grocery_api._cache_get("a")
        grocery_api._cache_get("a")
        self.assertEqual(antal["n"], 1)

    def test_cachen_kastar_ut_den_aldsta_inte_alla(self):
        """Förut tömdes hela cachen vid 200 poster: den 201:a veckan slängde
        de 200 som just värmts upp."""
        grocery_api.clear_cache()
        for n in range(grocery_api._CACHE_MAX_ENTRIES):
            grocery_api._cache_set(f"vecka-{n}", n)
        grocery_api._cache_get("vecka-1")          # nyss använd - ska överleva
        grocery_api._cache_set("vecka-ny", "ny")
        self.assertEqual(len(grocery_api._CACHE), grocery_api._CACHE_MAX_ENTRIES)
        self.assertEqual(grocery_api._cache_get("vecka-1"), 1)
        self.assertEqual(grocery_api._cache_get("vecka-ny"), "ny")
        self.assertIsNone(grocery_api._cache_get("vecka-0"), "äldst ska ha åkt ut")


if __name__ == "__main__":
    unittest.main()
