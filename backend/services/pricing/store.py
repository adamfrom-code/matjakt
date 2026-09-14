"""SQLite-backed cache of scraped store product results.

Kept deliberately small and stdlib-only, mirroring services/accounts/store.py.
Before this, scraped prices only lived in an in-memory dict - every deploy or
restart threw away everything the app had ever learned, so users kept hitting
"Uppskattat" for items that had a perfectly good real price from an hour ago.
This persists that same (chain, query, zip) -> products shape to disk, so it
survives restarts and slowly gets more complete/useful over time instead of
starting from zero every deploy.
"""

import json
import random
import sqlite3
import threading
import time
from pathlib import Path

from ..data_guard import guard_database_path
from ..schema_version import PRISCACHE, stämpla

PRUNE_PROBABILITY = 0.02
PRUNE_MAX_AGE_SECONDS = 7 * 86400


# Priset i en cachad rad är bara lika bra som tolkningen som skrev den.
# BUMPA DEN HÄR när prisutvinningen ändras på ett sätt som gör gamla rader
# fel - rader med annan version ignoreras direkt och skrivs över vid nästa
# hämtning. Inget raderas, ingen annan data rörs.
#
#   2026-09-07  "kilo-vs-paket": jämförpris kunde tolkas som förpackningspris
#               (PR #4). Hemköp visade 111,60 kr för en burk som kostar
#               11,83. Utan den här bumpen hade de raderna serverats i sex
#               timmar till efter att fixen deployats.
PARSER_VERSION = "2026-09-07-kilo-vs-paket"


class PriceCacheStore:
    def __init__(self, db_path: Path):
        # Testläge får aldrig nå en riktig databas - se services/data_guard.py.
        guard_database_path(db_path, purpose="priscachen")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        # EN anslutning delas av alla servertrådar (och av KeyValueCacheStore).
        # Utan lås kan två trådars "with connection" flätas ihop: "cannot
        # start a transaction within a transaction" - sett som 500 på
        # /api/products/batch i browser-E2E:n.
        self.lock = threading.RLock()
        self._init_schema()

    @property
    def connection(self):
        """Exposed so KeyValueCacheStore can share this exact connection (and
        so the same file backs every persisted cache, not a second .db to
        deploy/back up) - see KeyValueCacheStore's docstring."""
        return self._connection

    def _init_schema(self):
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS product_cache (
                chain TEXT NOT NULL,
                query TEXT NOT NULL,
                zip TEXT NOT NULL,
                products_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (chain, query, zip)
            );
            """
        )
        # Migrering: rader skrivna före versionskolumnen får "", vilket aldrig
        # matchar PARSER_VERSION och därför ignoreras - exakt det vi vill när
        # tolkningen ändrats. De skrivs över vid nästa hämtning, så inget
        # raderas och inget ackumuleras.
        kolumner = {row[1] for row in self._connection.execute("PRAGMA table_info(product_cache)")}
        if "parser_version" not in kolumner:
            with self.lock, self._connection:
                self._connection.execute(
                    "ALTER TABLE product_cache ADD COLUMN parser_version TEXT NOT NULL DEFAULT ''")
        # Schemat är nu det version PRISCACHE beskriver - stämpla filen, så att en
        # människa efter ett rollback kan LÄSA vilken version den bär i
        # stället för att gissa. Se services/schema_version.py.
        stämpla(self._connection, PRISCACHE)

    def get(self, chain: str, query: str, zip_code: str):
        """Returns (products, updated_at) - a real time.time() timestamp, not
        time.monotonic(), since it needs to stay meaningful across restarts -
        or (None, None) if there's no entry at all. Callers apply their own
        freshness window on top of updated_at (see cached_products) - this
        method itself doesn't judge age, so get_stale() below can reuse the
        exact same row for a fallback when a fresh re-fetch fails."""
        with self.lock:
            row = self._connection.execute(
                "SELECT products_json, updated_at FROM product_cache "
                "WHERE chain = ? AND query = ? AND zip = ? AND parser_version = ?",
                (chain, query, zip_code, PARSER_VERSION),
            ).fetchone()
        if not row:
            return None, None
        return json.loads(row[0]), row[1]

    # get() and get_stale() are the same query today - kept as two named
    # methods (rather than one call site re-interpreting a single get())
    # because they answer different questions: get() is "do I have a fresh
    # answer", get_stale() is "do I have ANY answer, however old, to show as
    # 'Senast känt pris' when a live re-fetch just failed". A caller reading
    # get_stale() shouldn't have to know that's implemented identically to
    # get() today - only that it may legitimately return old data.
    def get_stale(self, chain: str, query: str, zip_code: str):
        """Även den här respekterar PARSER_VERSION: "senast känt pris" får
        vara gammalt, aldrig fel. En rad skriven av en tolkning vi vet var
        felaktig är inte ett sämre svar - det är ett osant."""
        return self.get(chain, query, zip_code)

    def set(self, chain: str, query: str, zip_code: str, products: list, updated_at: float = None):
        """updated_at defaults to now - the override exists for tests that
        need to plant an entry of a specific age without sleeping."""
        now = updated_at if updated_at is not None else time.time()
        with self.lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO product_cache (chain, query, zip, products_json, updated_at, parser_version)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chain, query, zip) DO UPDATE SET
                    products_json = excluded.products_json,
                    updated_at = excluded.updated_at,
                    parser_version = excluded.parser_version
                """,
                (chain, query, zip_code, json.dumps(products), now, PARSER_VERSION),
            )
        # Unbounded growth isn't a real risk at this scale (one row per
        # distinct ingredient/store/zip ever searched), but a cheap
        # probabilistic sweep keeps genuinely ancient rows from lingering
        # forever without needing a scheduled job.
        if random.random() < PRUNE_PROBABILITY:
            self._prune(time.time())

    def _prune(self, now: float):
        with self.lock, self._connection:
            self._connection.execute(
                "DELETE FROM product_cache WHERE updated_at < ?", (now - PRUNE_MAX_AGE_SECONDS,)
            )

    def clear(self):
        """Test-only: wipes every entry."""
        with self.lock, self._connection:
            self._connection.execute("DELETE FROM product_cache")

    def close(self):
        self._connection.close()


class KeyValueCacheStore:
    """A general-purpose, persisted (namespace, key) -> JSON value cache -
    shares PriceCacheStore's SQLite file/connection so no second database
    needs deploying or backing up separately. Replaces the several plain
    Python dicts (campaigns, geocoding, store lists, Primat store lookups,
    Open Food Facts images) that used to live only in process memory and
    lost everything on every deploy/restart - exactly the caching gap that
    made "senast uppdaterad" numbers reset to nothing on every deploy. Each
    caller keeps its own TTL check on top of this (see cache_scope-style
    helpers in api_server.py); this store itself only tracks when a value
    was written, same division of responsibility as PriceCacheStore."""

    def __init__(self, connection: sqlite3.Connection, lock=None):
        self._connection = connection
        # Samma lås som ägaren av anslutningen (PriceCacheStore.lock) - två
        # lås på en anslutning skyddar ingenting.
        self.lock = lock or threading.RLock()
        self._init_schema()

    def _init_schema(self):
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv_cache (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (namespace, key)
            );
            """
        )

    def get(self, namespace: str, key: str):
        """Returns (value, updated_at), or (None, None) if there's no entry -
        same shape as PriceCacheStore.get(), same reasoning: the caller
        judges freshness, this just answers "what's stored and when"."""
        with self.lock:
            row = self._connection.execute(
                "SELECT value_json, updated_at FROM kv_cache WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
        if not row:
            return None, None
        return json.loads(row[0]), row[1]

    def set(self, namespace: str, key: str, value, updated_at: float = None):
        now = updated_at if updated_at is not None else time.time()
        with self.lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO kv_cache (namespace, key, value_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (namespace, key, json.dumps(value), now),
            )
        if random.random() < PRUNE_PROBABILITY:
            self._prune(time.time())

    # Namnrymder som inte är cache utan driftsfakta (senaste prisauditen):
    # de får inte försvinna efter sju dagar bara för att inget skrivit dem.
    PROTECTED_NAMESPACES = ("pricing_audit",)

    def keys(self, namespace: str) -> list:
        """Alla nycklar i ett namespace. Finns för driftlarmen, som måste
        kunna hitta en ÖPPEN incident som inte längre är aktuell - annars går
        det inte att skicka ett recoverymejl för något som slutat hända."""
        with self.lock:
            rows = self._connection.execute(
                "SELECT key FROM kv_cache WHERE namespace = ?", (namespace,)).fetchall()
        return [row[0] for row in rows]

    def delete(self, namespace: str, key: str):
        """Tar bort en post. Används när en incident är löst: en kvarliggande
        rad skulle betyda att samma problem aldrig fick larma igen."""
        with self.lock, self._connection:
            self._connection.execute(
                "DELETE FROM kv_cache WHERE namespace = ? AND key = ?", (namespace, key))

    def _prune(self, now: float):
        with self.lock, self._connection:
            self._connection.execute(
                "DELETE FROM kv_cache WHERE updated_at < ? AND namespace NOT IN (%s)"
                % ",".join("?" * len(self.PROTECTED_NAMESPACES)),
                (now - PRUNE_MAX_AGE_SECONDS, *self.PROTECTED_NAMESPACES),
            )

    def clear(self):
        """Test-only: wipes every entry."""
        with self.lock, self._connection:
            self._connection.execute("DELETE FROM kv_cache")
