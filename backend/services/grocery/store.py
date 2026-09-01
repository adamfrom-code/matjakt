"""SQLite-backed storage for the grocery price backend (FAS A).

Stdlib-only, same shape as services/pricing/store.py and services/accounts/
store.py: one file, one class per concern, no ORM, WAL mode for concurrent
readers. Deliberately a SEPARATE database file (grocery.db, not prices.db or
matjakt.db) - this is a different, much larger-scale dataset (a real product
catalog with history, not a short-TTL cache) with its own growth and backup
characteristics, and keeping it apart means nothing here can accidentally
collide with the existing price-cache/account schemas.

Table names are prefixed grocery_ even though this is already a dedicated
database file, purely so a stray `sqlite3 grocery.db` session immediately
reads as "these tables are the grocery backend" without needing the filename
for context.
"""

import re
import sqlite3
import time
from pathlib import Path

from .models import CollectorRun, CurrentPrice, PriceHistoryEntry, Product, RawProduct, Store


def _normalize_text(value: str | None) -> str:
    """Lowercase, collapse whitespace, strip - deliberately NOT fuzzy: this
    is the last-resort matching tier (see GroceryStore.find_or_create_
    product), and the spec is explicit that it must stay an exact match on
    normalized text, never a similarity/distance-based one. Two products
    that differ by more than casing/whitespace are treated as different
    products, full stop - a false merge (two different products silently
    treated as one) is worse than a missed merge (the same product getting
    two rows for a while until a GTIN shows up)."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def _normalized_key(brand: str | None, name: str, size: str | None) -> str:
    return f"{_normalize_text(brand)}|{_normalize_text(name)}|{_normalize_text(size)}"


class GroceryStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Kept so process-global caches can key on WHICH database they
        # describe. Without it, two different databases whose contents happen
        # to fingerprint the same (easy for small test fixtures) would share
        # one cache entry and answer for each other.
        self.db_path = str(db_path)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @property
    def connection(self):
        return self._connection

    def _init_schema(self):
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS grocery_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gtin TEXT,
                ean TEXT,
                name TEXT NOT NULL,
                brand TEXT,
                description TEXT,
                size TEXT,
                quantity REAL,
                unit TEXT,
                category TEXT,
                image_url TEXT,
                image_source_url TEXT,
                normalized_key TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_grocery_products_gtin
                ON grocery_products(gtin) WHERE gtin IS NOT NULL AND gtin != '';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_grocery_products_ean
                ON grocery_products(ean) WHERE ean IS NOT NULL AND ean != '';
            CREATE INDEX IF NOT EXISTS idx_grocery_products_normalized_key
                ON grocery_products(normalized_key);

            -- Not part of the spec's PRODUCTS columns, but needed to actually
            -- implement matching tier 2 ("annat stabilt externt produkt-ID"):
            -- lets a later collector run recognize "I've seen this chain's own
            -- product id before" even for the many real-world catalog rows
            -- that never carry a GTIN at all, without re-deriving the match
            -- from name/brand/size every single night.
            CREATE TABLE IF NOT EXISTS grocery_product_external_ids (
                chain TEXT NOT NULL,
                external_product_id TEXT NOT NULL,
                product_id INTEGER NOT NULL REFERENCES grocery_products(id),
                PRIMARY KEY (chain, external_product_id)
            );

            CREATE TABLE IF NOT EXISTS grocery_stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain TEXT NOT NULL,
                external_store_id TEXT NOT NULL,
                name TEXT NOT NULL,
                city TEXT,
                postal_code TEXT,
                address TEXT,
                latitude REAL,
                longitude REAL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(chain, external_store_id)
            );

            CREATE TABLE IF NOT EXISTS grocery_current_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES grocery_products(id),
                store_id INTEGER NOT NULL REFERENCES grocery_stores(id),
                regular_price REAL,
                campaign_price REAL,
                member_price REAL,
                multibuy_price REAL,
                unit_price REAL,
                currency TEXT NOT NULL DEFAULT 'SEK',
                source_url TEXT,
                fetched_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(product_id, store_id)
            );

            CREATE TABLE IF NOT EXISTS grocery_price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES grocery_products(id),
                store_id INTEGER NOT NULL REFERENCES grocery_stores(id),
                regular_price REAL,
                campaign_price REAL,
                member_price REAL,
                multibuy_price REAL,
                unit_price REAL,
                timestamp REAL NOT NULL
            );
            -- Every user-facing price lookup goes through these. Without
            -- them the pricing engine walks a whole chain's products for
            -- each ingredient, which is fine at a hundred products and not
            -- at eleven thousand.
            CREATE INDEX IF NOT EXISTS idx_grocery_external_ids_chain
                ON grocery_product_external_ids(chain, product_id);
            CREATE INDEX IF NOT EXISTS idx_grocery_current_prices_store
                ON grocery_current_prices(store_id, product_id);
            CREATE INDEX IF NOT EXISTS idx_grocery_products_category
                ON grocery_products(category);
            CREATE INDEX IF NOT EXISTS idx_grocery_price_history_lookup
                ON grocery_price_history(product_id, store_id, timestamp DESC);

            CREATE TABLE IF NOT EXISTS grocery_collector_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain TEXT NOT NULL,
                store_id INTEGER REFERENCES grocery_stores(id),
                started_at REAL NOT NULL,
                finished_at REAL,
                status TEXT NOT NULL DEFAULT 'running',
                products_found INTEGER NOT NULL DEFAULT 0,
                products_created INTEGER NOT NULL DEFAULT 0,
                products_updated INTEGER NOT NULL DEFAULT 0,
                prices_updated INTEGER NOT NULL DEFAULT 0,
                images_found INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            );
            """
        )

    # ---- Stores -----------------------------------------------------

    def upsert_store(self, *, chain: str, external_store_id: str, name: str, city: str | None = None,
                      postal_code: str | None = None, address: str | None = None,
                      latitude: float | None = None, longitude: float | None = None,
                      active: bool = True) -> Store:
        now = time.time()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO grocery_stores (chain, external_store_id, name, city, postal_code, address,
                                             latitude, longitude, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chain, external_store_id) DO UPDATE SET
                    name = excluded.name, city = excluded.city, postal_code = excluded.postal_code,
                    address = excluded.address, latitude = excluded.latitude, longitude = excluded.longitude,
                    active = excluded.active, updated_at = excluded.updated_at
                """,
                (chain, external_store_id, name, city, postal_code, address, latitude, longitude,
                 int(active), now, now),
            )
        return self.get_store(chain=chain, external_store_id=external_store_id)

    def get_store(self, *, chain: str, external_store_id: str) -> Store | None:
        row = self._connection.execute(
            "SELECT * FROM grocery_stores WHERE chain = ? AND external_store_id = ?",
            (chain, external_store_id),
        ).fetchone()
        return self._row_to_store(row) if row else None

    def get_store_by_id(self, store_id: int) -> Store | None:
        row = self._connection.execute("SELECT * FROM grocery_stores WHERE id = ?", (store_id,)).fetchone()
        return self._row_to_store(row) if row else None

    def list_stores(self, *, chain: str | None = None, active_only: bool = False) -> list[Store]:
        query = "SELECT * FROM grocery_stores"
        conditions, params = [], []
        if chain:
            conditions.append("chain = ?")
            params.append(chain)
        if active_only:
            conditions.append("active = 1")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY chain, name"
        rows = self._connection.execute(query, params).fetchall()
        return [self._row_to_store(row) for row in rows]

    @staticmethod
    def _row_to_store(row) -> Store:
        return Store(
            id=row["id"], chain=row["chain"], external_store_id=row["external_store_id"], name=row["name"],
            city=row["city"], postal_code=row["postal_code"], address=row["address"],
            latitude=row["latitude"], longitude=row["longitude"], active=bool(row["active"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    # ---- Products / matching -----------------------------------------

    def find_or_create_product(self, raw: RawProduct) -> Product:
        """Reconciles one RawProduct against the shared catalog. Matching
        priority, per spec section 3 - never falls through to a looser tier
        once an earlier one matches:

        1. GTIN
        2. EAN (only if no GTIN match)
        3. this chain's own external_product_id, if we've resolved it to a
           product before (grocery_product_external_ids)
        4. brand + normalized name + size, exact (not fuzzy) match

        No match at any tier creates a new product. Every path backfills the
        external_product_id mapping and any newly-known gtin/ean/image onto
        the matched row (see _apply_new_signals) - so a product first seen
        without a GTIN still gets linked up automatically once a chain that
        does supply one reports the same item."""
        product = None
        if raw.gtin:
            product = self._find_product_by_gtin(raw.gtin)
        if product is None and raw.ean:
            product = self._find_product_by_ean(raw.ean)
        if product is None:
            product = self._find_product_by_external_id(raw.chain, raw.external_product_id)
        if product is None:
            product = self._find_product_by_normalized_key(raw.brand, raw.name, raw.size)

        if product is not None:
            product = self._apply_new_signals(product, raw)
        else:
            product = self._create_product(raw)

        self._link_external_id(raw.chain, raw.external_product_id, product.id)
        return product

    def _find_product_by_gtin(self, gtin: str) -> Product | None:
        row = self._connection.execute("SELECT * FROM grocery_products WHERE gtin = ?", (gtin,)).fetchone()
        return self._row_to_product(row) if row else None

    def _find_product_by_ean(self, ean: str) -> Product | None:
        row = self._connection.execute("SELECT * FROM grocery_products WHERE ean = ?", (ean,)).fetchone()
        return self._row_to_product(row) if row else None

    def _find_product_by_external_id(self, chain: str, external_product_id: str) -> Product | None:
        row = self._connection.execute(
            """
            SELECT p.* FROM grocery_products p
            JOIN grocery_product_external_ids e ON e.product_id = p.id
            WHERE e.chain = ? AND e.external_product_id = ?
            """,
            (chain, external_product_id),
        ).fetchone()
        return self._row_to_product(row) if row else None

    def _find_product_by_normalized_key(self, brand: str | None, name: str, size: str | None) -> Product | None:
        row = self._connection.execute(
            "SELECT * FROM grocery_products WHERE normalized_key = ?",
            (_normalized_key(brand, name, size),),
        ).fetchone()
        return self._row_to_product(row) if row else None

    def _create_product(self, raw: RawProduct) -> Product:
        now = time.time()
        with self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO grocery_products (gtin, ean, name, brand, description, size, quantity, unit,
                                               category, image_url, image_source_url, normalized_key,
                                               created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (raw.gtin, raw.ean, raw.name, raw.brand, raw.description, raw.size, raw.quantity, raw.unit,
                 raw.category, raw.image_url, raw.source_url if raw.image_url else None,
                 _normalized_key(raw.brand, raw.name, raw.size), now, now),
            )
        return self.get_product(cursor.lastrowid)

    def _apply_new_signals(self, product: Product, raw: RawProduct) -> Product:
        """Backfills fields onto an already-matched product that it didn't
        have yet (a GTIN discovered after the product was first created from
        a chain that doesn't supply one; an image when the product had
        none). Never overwrites a value that's already set - this is meant
        to fill gaps, not let a later, possibly lower-quality source
        clobber a good existing value."""
        updates, params = [], []
        if raw.gtin and not product.gtin:
            updates.append("gtin = ?")
            params.append(raw.gtin)
        if raw.ean and not product.ean:
            updates.append("ean = ?")
            params.append(raw.ean)
        if raw.image_url and not product.image_url:
            updates.append("image_url = ?")
            params.append(raw.image_url)
            updates.append("image_source_url = ?")
            params.append(raw.source_url)
        if raw.category and not product.category:
            updates.append("category = ?")
            params.append(raw.category)
        if not updates:
            return product
        updates.append("updated_at = ?")
        params.append(time.time())
        params.append(product.id)
        with self._connection:
            self._connection.execute(f"UPDATE grocery_products SET {', '.join(updates)} WHERE id = ?", params)
        return self.get_product(product.id)

    def _link_external_id(self, chain: str, external_product_id: str, product_id: int):
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO grocery_product_external_ids (chain, external_product_id, product_id)
                VALUES (?, ?, ?)
                ON CONFLICT(chain, external_product_id) DO UPDATE SET product_id = excluded.product_id
                """,
                (chain, external_product_id, product_id),
            )

    def get_product(self, product_id: int) -> Product | None:
        row = self._connection.execute("SELECT * FROM grocery_products WHERE id = ?", (product_id,)).fetchone()
        return self._row_to_product(row) if row else None

    def get_product_by_external_id(self, chain: str, external_product_id: str) -> Product | None:
        """Public wrapper around the same lookup find_or_create_product uses
        internally (tier 3 matching) - exposed so a caller (e.g. a collector
        script logging created-vs-updated counts) can check "have we seen
        this chain's product before" without reaching into a private
        method."""
        return self._find_product_by_external_id(chain, external_product_id)

    def search_products(self, query: str, limit: int = 20) -> list[Product]:
        needle = f"%{_normalize_text(query)}%"
        rows = self._connection.execute(
            "SELECT * FROM grocery_products WHERE normalized_key LIKE ? ORDER BY name LIMIT ?",
            (needle, limit),
        ).fetchall()
        return [self._row_to_product(row) for row in rows]

    @staticmethod
    def _row_to_product(row) -> Product:
        return Product(
            id=row["id"], gtin=row["gtin"], ean=row["ean"], name=row["name"], brand=row["brand"],
            description=row["description"], size=row["size"], quantity=row["quantity"], unit=row["unit"],
            category=row["category"], image_url=row["image_url"], image_source_url=row["image_source_url"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    # ---- Prices --------------------------------------------------------

    def upsert_current_price(self, *, product_id: int, store_id: int, regular_price: float | None,
                              campaign_price: float | None = None, member_price: float | None = None,
                              multibuy_price: float | None = None, unit_price: float | None = None,
                              currency: str = "SEK", source_url: str | None = None,
                              fetched_at: float | None = None) -> tuple[CurrentPrice, bool]:
        """Updates CURRENT_PRICES and, only if a price fact actually changed,
        appends a row to PRICE_HISTORY (see spec section 11 - no duplicate
        history rows for an unchanged nightly re-check). Returns
        (current_price, price_changed).

        Never called with a failure in mind: a collector that couldn't fetch
        a price at all should simply not call this for that product/store,
        leaving the existing CURRENT_PRICES row (and its own fetched_at)
        exactly as it was - see spec section 7, "om en collector misslyckas:
        radera inte gamla priser"."""
        now = fetched_at if fetched_at is not None else time.time()

        # PRISSANERING VID KÄLLAN. Ett pris <= 0 eller absurt högt är ett
        # importfel, inte ett pris - inskrivet skulle det vinna varje
        # billigast-jämförelse (0 kr slår allt). Regeln är att VÄGRA värdet,
        # aldrig gissa ett annat: raden behåller sitt gamla pris, precis som
        # när en collector inte kunde hämta något alls. 30 000 kr täcker
        # dyraste legitima matvara med bred marginal.
        def _sane(value):
            if value is None:
                return None
            try:
                value = float(value)
            except (TypeError, ValueError):
                return None
            return value if 0 < value <= 30000 else None

        regular_price = _sane(regular_price)
        campaign_price = _sane(campaign_price)
        member_price = _sane(member_price)
        multibuy_price = _sane(multibuy_price)
        unit_price = _sane(unit_price)
        # En "kampanj" som inte är billigare än ordinarie är ingen kampanj.
        if campaign_price is not None and regular_price is not None and campaign_price >= regular_price:
            campaign_price = None
        if regular_price is None and campaign_price is None:
            existing_row = self._connection.execute(
                "SELECT * FROM grocery_current_prices WHERE product_id = ? AND store_id = ?",
                (product_id, store_id)).fetchone()
            if existing_row is not None:
                return CurrentPrice(**{key: existing_row[key] for key in existing_row.keys()}), False
            raise ValueError("Ogiltigt pris - raden skrivs inte")

        existing = self._connection.execute(
            "SELECT * FROM grocery_current_prices WHERE product_id = ? AND store_id = ?",
            (product_id, store_id),
        ).fetchone()

        changed = existing is None or any(
            existing[field] != value
            for field, value in (
                ("regular_price", regular_price), ("campaign_price", campaign_price),
                ("member_price", member_price), ("multibuy_price", multibuy_price),
                ("unit_price", unit_price),
            )
        )

        with self._connection:
            self._connection.execute(
                """
                INSERT INTO grocery_current_prices (product_id, store_id, regular_price, campaign_price,
                                                      member_price, multibuy_price, unit_price, currency,
                                                      source_url, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id, store_id) DO UPDATE SET
                    regular_price = excluded.regular_price, campaign_price = excluded.campaign_price,
                    member_price = excluded.member_price, multibuy_price = excluded.multibuy_price,
                    unit_price = excluded.unit_price, currency = excluded.currency,
                    source_url = excluded.source_url, fetched_at = excluded.fetched_at,
                    updated_at = excluded.updated_at
                """,
                (product_id, store_id, regular_price, campaign_price, member_price, multibuy_price,
                 unit_price, currency, source_url, now, now),
            )
            if changed:
                self._connection.execute(
                    """
                    INSERT INTO grocery_price_history (product_id, store_id, regular_price, campaign_price,
                                                         member_price, multibuy_price, unit_price, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (product_id, store_id, regular_price, campaign_price, member_price, multibuy_price,
                     unit_price, now),
                )

        row = self._connection.execute(
            "SELECT * FROM grocery_current_prices WHERE product_id = ? AND store_id = ?",
            (product_id, store_id),
        ).fetchone()
        return self._row_to_current_price(row), changed

    def get_current_price(self, product_id: int, store_id: int) -> CurrentPrice | None:
        row = self._connection.execute(
            "SELECT * FROM grocery_current_prices WHERE product_id = ? AND store_id = ?",
            (product_id, store_id),
        ).fetchone()
        return self._row_to_current_price(row) if row else None

    def get_prices_for_product(self, product_id: int) -> list[CurrentPrice]:
        rows = self._connection.execute(
            "SELECT * FROM grocery_current_prices WHERE product_id = ? ORDER BY regular_price",
            (product_id,),
        ).fetchall()
        return [self._row_to_current_price(row) for row in rows]

    @staticmethod
    def _row_to_current_price(row) -> CurrentPrice:
        return CurrentPrice(
            id=row["id"], product_id=row["product_id"], store_id=row["store_id"],
            regular_price=row["regular_price"], campaign_price=row["campaign_price"],
            member_price=row["member_price"], multibuy_price=row["multibuy_price"],
            unit_price=row["unit_price"], currency=row["currency"], source_url=row["source_url"],
            fetched_at=row["fetched_at"], updated_at=row["updated_at"],
        )

    def get_price_history(self, product_id: int, store_id: int | None = None,
                           since: float | None = None) -> list[PriceHistoryEntry]:
        query = "SELECT * FROM grocery_price_history WHERE product_id = ?"
        params: list = [product_id]
        if store_id is not None:
            query += " AND store_id = ?"
            params.append(store_id)
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC, id DESC"
        rows = self._connection.execute(query, params).fetchall()
        return [self._row_to_history_entry(row) for row in rows]

    @staticmethod
    def _row_to_history_entry(row) -> PriceHistoryEntry:
        return PriceHistoryEntry(
            id=row["id"], product_id=row["product_id"], store_id=row["store_id"],
            regular_price=row["regular_price"], campaign_price=row["campaign_price"],
            member_price=row["member_price"], multibuy_price=row["multibuy_price"],
            unit_price=row["unit_price"], timestamp=row["timestamp"],
        )

    # ---- Collector runs --------------------------------------------

    def reconcile_interrupted_runs(self) -> int:
        """Marks runs still labelled "running" as interrupted.

        A collector run lives in a thread. When the process dies - a deploy,
        a restart, an OOM - the thread goes with it, but the database row
        stays "running" forever. Seen in production: a row claimed an import
        was in progress 15 minutes after the deploy that killed it, so the
        status endpoint and the admin panel both reported an import that did
        not exist, and lastSuccessfulRun never appeared.

        Call this at STARTUP only, never from GroceryStore.__init__: the CLI
        collectors open the same database, and a server restart must not
        relabel a collector run that is genuinely still going in another
        process."""
        cursor = self._connection.execute(
            """
            UPDATE grocery_collector_runs
            SET status = 'interrupted',
                finished_at = ?,
                error_message = COALESCE(error_message,
                    'Processen startade om innan körningen hann bli klar')
            WHERE status = 'running'
            """,
            (time.time(),),
        )
        self._connection.commit()
        return cursor.rowcount

    def data_version(self) -> str:
        """A fingerprint of the data as CUSTOMERS see it.

        Anything derived from this database - matched products, chain totals,
        a whole priced week - stays valid exactly as long as this string
        does, so it is the invalidation key for every cache over this data.

        It deliberately advances only when a collector run FINISHES, never on
        each price written. That is what keeps an import invisible from the
        outside: a category walk writes for tens of minutes, and if the
        version moved with every batch then every cached index, price map and
        priced week would be discarded continuously - the import window would
        become the slowest the app ever is, which is exactly when it must not
        be. Instead the version holds still, customers keep being served from
        warm caches built on the data that was already there, and when the run
        completes it moves once and everything picks up the new prices
        together.

        Rows written mid-import are still real, complete rows (imports only
        ever upsert - there is no delete path here), so nothing is lost or
        half-written. A cache miss during an import simply sees some newer
        prices, which is what an upsert has always meant."""
        row = self._connection.execute(
            """
            SELECT (SELECT COUNT(*) FROM grocery_products),
                   (SELECT COUNT(*) FROM grocery_current_prices),
                   (SELECT MAX(id) FROM grocery_collector_runs
                     WHERE status IS NOT NULL AND status != 'running')
            """
        ).fetchone()
        return "-".join(str(value or 0) for value in row)

    def start_collector_run(self, *, chain: str, store_id: int | None = None) -> CollectorRun:
        now = time.time()
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO grocery_collector_runs (chain, store_id, started_at, status) VALUES (?, ?, ?, 'running')",
                (chain, store_id, now),
            )
        return self.get_collector_run(cursor.lastrowid)

    def finish_collector_run(self, run_id: int, *, status: str, products_found: int = 0,
                              products_created: int = 0, products_updated: int = 0, prices_updated: int = 0,
                              images_found: int = 0, errors: int = 0, error_message: str | None = None) -> CollectorRun:
        with self._connection:
            self._connection.execute(
                """
                UPDATE grocery_collector_runs SET
                    finished_at = ?, status = ?, products_found = ?, products_created = ?,
                    products_updated = ?, prices_updated = ?, images_found = ?, errors = ?, error_message = ?
                WHERE id = ?
                """,
                (time.time(), status, products_found, products_created, products_updated, prices_updated,
                 images_found, errors, error_message, run_id),
            )
        return self.get_collector_run(run_id)

    def get_collector_run(self, run_id: int) -> CollectorRun | None:
        row = self._connection.execute("SELECT * FROM grocery_collector_runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_collector_run(row) if row else None

    def latest_collector_run(self, chain: str) -> CollectorRun | None:
        # Ordered by id, not just started_at - two runs started back-to-back
        # can land on the exact same time.time() value (seen for real in
        # tests on Windows, whose wall-clock resolution is coarser than
        # Linux's), and id (AUTOINCREMENT) is the one field guaranteed to
        # break that tie in actual insertion order.
        row = self._connection.execute(
            "SELECT * FROM grocery_collector_runs WHERE chain = ? ORDER BY started_at DESC, id DESC LIMIT 1",
            (chain,),
        ).fetchone()
        return self._row_to_collector_run(row) if row else None

    @staticmethod
    def _row_to_collector_run(row) -> CollectorRun:
        return CollectorRun(
            id=row["id"], chain=row["chain"], store_id=row["store_id"], started_at=row["started_at"],
            finished_at=row["finished_at"], status=row["status"], products_found=row["products_found"],
            products_created=row["products_created"], products_updated=row["products_updated"],
            prices_updated=row["prices_updated"], images_found=row["images_found"], errors=row["errors"],
            error_message=row["error_message"],
        )

    def close(self):
        self._connection.close()
