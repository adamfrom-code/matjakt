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
import time
from pathlib import Path

PRUNE_PROBABILITY = 0.02
PRUNE_MAX_AGE_SECONDS = 7 * 86400


class PriceCacheStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

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

    def get(self, chain: str, query: str, zip_code: str):
        """Returns (products, updated_at) - a real time.time() timestamp, not
        time.monotonic(), since it needs to stay meaningful across restarts -
        or (None, None) if there's no entry at all."""
        row = self._connection.execute(
            "SELECT products_json, updated_at FROM product_cache WHERE chain = ? AND query = ? AND zip = ?",
            (chain, query, zip_code),
        ).fetchone()
        if not row:
            return None, None
        return json.loads(row[0]), row[1]

    def set(self, chain: str, query: str, zip_code: str, products: list, updated_at: float = None):
        """updated_at defaults to now - the override exists for tests that
        need to plant an entry of a specific age without sleeping."""
        now = updated_at if updated_at is not None else time.time()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO product_cache (chain, query, zip, products_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chain, query, zip) DO UPDATE SET
                    products_json = excluded.products_json,
                    updated_at = excluded.updated_at
                """,
                (chain, query, zip_code, json.dumps(products), now),
            )
        # Unbounded growth isn't a real risk at this scale (one row per
        # distinct ingredient/store/zip ever searched), but a cheap
        # probabilistic sweep keeps genuinely ancient rows from lingering
        # forever without needing a scheduled job.
        if random.random() < PRUNE_PROBABILITY:
            self._prune(time.time())

    def _prune(self, now: float):
        with self._connection:
            self._connection.execute(
                "DELETE FROM product_cache WHERE updated_at < ?", (now - PRUNE_MAX_AGE_SECONDS,)
            )

    def clear(self):
        """Test-only: wipes every entry."""
        with self._connection:
            self._connection.execute("DELETE FROM product_cache")

    def close(self):
        self._connection.close()
