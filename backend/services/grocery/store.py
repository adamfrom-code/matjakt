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
        self._migrate_schema()

    # Additiva kolumner per tabell. CREATE TABLE IF NOT EXISTS rör aldrig en
    # tabell som redan finns, så nya kolumner läggs till här - idempotent,
    # styrt av vad tabellen faktiskt har. Ordningen i listan spelar ingen roll.
    _COLUMN_MIGRATIONS = {
        "grocery_products": [
            # Dabas-masterdata + paketverifiering (se providers/dabas.py,
            # enrichment.py). Ingen av dessa rör produktens pris.
            ("manufacturer", "TEXT"), ("dabas_name", "TEXT"), ("dabas_category", "TEXT"),
            ("dabas_gpc", "TEXT"), ("ingredients", "TEXT"), ("allergens", "TEXT"),
            ("nutrition", "TEXT"), ("dabas_data", "TEXT"),
            ("dabas_status", "TEXT"), ("dabas_last_checked", "REAL"),
            ("dabas_last_success", "REAL"), ("dabas_error", "TEXT"),
            ("dabas_source_version", "TEXT"),
            ("package_source", "TEXT"), ("package_confidence", "TEXT"),
            ("package_conflict", "TEXT"),
            ("provider_size", "TEXT"), ("provider_quantity", "REAL"), ("provider_unit", "TEXT"),
        ],
        "grocery_stores": [
            ("provider", "TEXT"), ("pricing_scope", "TEXT"),
            # Nationell prisplattform + butikspartner (2026-09-02)
            ("ownership_type", "TEXT"),            # FRANCHISE/COOPERATIVE/CENTRAL
            ("partner_status", "TEXT NOT NULL DEFAULT 'NONE'"),
            ("partner_id", "INTEGER"),
        ],
        "grocery_current_prices": [
            # Radens ursprung och färskhet: vem sa det, när, och hur länge
            # kampanjen gäller. Alla rader här är VERIFIED_STORE_PRICE -
            # referenspriser bor i grocery_reference_prices.
            ("source", "TEXT"), ("verified_at", "REAL"),
            ("valid_from", "REAL"), ("valid_to", "REAL"),
        ],
        "grocery_collector_runs": [
            ("rows_staged", "INTEGER"), ("gate_percent", "REAL"),
            ("published", "INTEGER"), ("gate_message", "TEXT"),
        ],
    }

    def _migrate_schema(self):
        for table, columns in self._COLUMN_MIGRATIONS.items():
            existing = {row[1] for row in self._connection.execute(f"PRAGMA table_info({table})")}
            with self._connection:
                for name, decl in columns:
                    if name not in existing:
                        self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

        self._connection.executescript(
            """
            -- KEDJOR: hur varje kedja prissätter och hur partnerskap tecknas.
            -- pricing_model: NATIONAL/REGIONAL/STORE_SPECIFIC.
            -- partner_model: PER_STORE (handlarägt), PER_GROUP (förening),
            -- PER_CHAIN (centralt avtal). chain_partner_id aktiverar alla
            -- kedjans butiker på en gång.
            CREATE TABLE IF NOT EXISTS grocery_chains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                pricing_model TEXT NOT NULL,
                reference_price_available INTEGER NOT NULL DEFAULT 0,
                reference_source TEXT,
                reference_store_external_id TEXT,
                partner_model TEXT NOT NULL DEFAULT 'PER_STORE',
                chain_partner_id INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            -- REFERENSPRISER: kedjans pris, en rad per produkt och kedja.
            -- Får användas nationellt, tydligt märkt "<Kedja> referenspris" -
            -- aldrig som påstående om en specifik butik.
            CREATE TABLE IF NOT EXISTS grocery_reference_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES grocery_products(id),
                chain TEXT NOT NULL,
                regular_price REAL,
                campaign_price REAL,
                member_price REAL,
                multibuy_price REAL,
                unit_price REAL,
                currency TEXT NOT NULL DEFAULT 'SEK',
                valid_from REAL,
                valid_to REAL,
                source TEXT,
                verified_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(product_id, chain)
            );
            CREATE INDEX IF NOT EXISTS idx_grocery_reference_prices_chain
                ON grocery_reference_prices(chain);

            -- STAGING: nattens import landar här först. Ingenting når
            -- grocery_current_prices förrän raderna passerat sanering och
            -- quality gate och körningen publicerats atomiskt.
            CREATE TABLE IF NOT EXISTS grocery_price_staging (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                regular_price REAL,
                campaign_price REAL,
                member_price REAL,
                multibuy_price REAL,
                unit_price REAL,
                currency TEXT NOT NULL DEFAULT 'SEK',
                source_url TEXT,
                source TEXT,
                valid_to REAL,
                fetched_at REAL,
                gate_status TEXT,
                gate_reason TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_grocery_price_staging_run
                ON grocery_price_staging(run_id);

            -- BUTIKSPARTNER. Betalning påverkar ALDRIG rankingen - partner-
            -- tabellerna ger rätten att LEVERERA verifierade lokala priser,
            -- ingenting annat.
            CREATE TABLE IF NOT EXISTS grocery_partner_plans (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                monthly_price_sek REAL NOT NULL,
                billing_model TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS grocery_partners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,                  -- PER_STORE/PER_GROUP/PER_CHAIN
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                plan_code TEXT REFERENCES grocery_partner_plans(code),
                monthly_price_sek REAL,
                chain TEXT,
                contact_email TEXT,
                api_key_hash TEXT,
                started_at REAL,
                ended_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS grocery_partner_stores (
                partner_id INTEGER NOT NULL REFERENCES grocery_partners(id),
                store_id INTEGER NOT NULL REFERENCES grocery_stores(id),
                PRIMARY KEY (partner_id, store_id)
            );
            CREATE TABLE IF NOT EXISTS grocery_partner_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id INTEGER NOT NULL REFERENCES grocery_partners(id),
                store_id INTEGER NOT NULL REFERENCES grocery_stores(id),
                format TEXT NOT NULL,
                status TEXT NOT NULL,
                rows_received INTEGER NOT NULL DEFAULT 0,
                rows_published INTEGER NOT NULL DEFAULT 0,
                gate_percent REAL,
                message TEXT,
                received_at REAL NOT NULL
            );
            -- Anonym aggregerad partnerstatistik: räknare per butik och dag,
            -- aldrig per användare.
            CREATE TABLE IF NOT EXISTS grocery_partner_stats (
                store_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                event TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (store_id, day, event)
            );
            """)

        now = time.time()
        with self._connection:
            # Första kommersiella erbjudandet - konfigurerbart, inte hårdkodat
            # i någon kärnlogik: ändra raden, inte koden.
            self._connection.execute(
                "INSERT OR IGNORE INTO grocery_partner_plans (code, name, monthly_price_sek, billing_model, active, updated_at) "
                "VALUES ('matjakt_butik', 'Matjakt Butik', 1495, 'PER_STORE', 1, ?)", (now,))
        # Kedjetabellen speglar konfigurationen i register.py och ska finnas i
        # varje miljö - även en som aldrig registersynkats (kedjepartner slår
        # upp via den). Lat import: lagret ska aldrig kunna hindras från att
        # öppna en databas av ett konfigurationsfel.
        try:
            from .register import ensure_chains
            ensure_chains(self)
        except Exception:  # pragma: no cover - loggas, blockerar aldrig
            import logging
            logging.getLogger("matjakt.grocery.store").exception("Kunde inte seeda kedjetabellen")

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
                      active: bool = True, provider: str | None = None,
                      pricing_scope: str | None = None) -> Store:
        now = time.time()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO grocery_stores (chain, external_store_id, name, city, postal_code, address,
                                             latitude, longitude, active, created_at, updated_at,
                                             provider, pricing_scope)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chain, external_store_id) DO UPDATE SET
                    name = excluded.name, city = excluded.city, postal_code = excluded.postal_code,
                    address = excluded.address, latitude = excluded.latitude, longitude = excluded.longitude,
                    active = excluded.active, updated_at = excluded.updated_at,
                    -- COALESCE: en anropare som inte känner provider/scope
                    -- (t.ex. en gammal kedje-provider) får inte RADERA vad
                    -- registersynken redan vet om butiken.
                    provider = COALESCE(excluded.provider, grocery_stores.provider),
                    pricing_scope = COALESCE(excluded.pricing_scope, grocery_stores.pricing_scope)
                """,
                (chain, external_store_id, name, city, postal_code, address, latitude, longitude,
                 int(active), now, now, provider, pricing_scope),
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
        keys = row.keys()
        return Store(
            id=row["id"], chain=row["chain"], external_store_id=row["external_store_id"], name=row["name"],
            city=row["city"], postal_code=row["postal_code"], address=row["address"],
            latitude=row["latitude"], longitude=row["longitude"], active=bool(row["active"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
            provider=row["provider"] if "provider" in keys else None,
            pricing_scope=row["pricing_scope"] if "pricing_scope" in keys else None,
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
                                               created_at, updated_at,
                                               provider_size, provider_quantity, provider_unit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (raw.gtin, raw.ean, raw.name, raw.brand, raw.description, raw.size, raw.quantity, raw.unit,
                 raw.category, raw.image_url, raw.source_url if raw.image_url else None,
                 _normalized_key(raw.brand, raw.name, raw.size), now, now,
                 raw.size, raw.quantity, raw.unit),
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
        # PROVIDERNS EGNA paketvärden uppdateras vid VARJE import - de är
        # sanningen om vad kedjan säger, oberoende av Dabas. En partnerfeed
        # utan mängd (bara size-text) får inte nolla en kedjas explicita
        # mängd: bara riktiga värden skrivs.
        if raw.size or raw.quantity:
            if raw.size and raw.size != getattr(product, "provider_size", None):
                updates.append("provider_size = ?")
                params.append(raw.size)
            if raw.quantity and (raw.quantity != getattr(product, "provider_quantity", None)
                                 or raw.unit != getattr(product, "provider_unit", None)):
                updates.append("provider_quantity = ?")
                params.append(raw.quantity)
                updates.append("provider_unit = ?")
                params.append(raw.unit)
        # Samma luckfyllnad för namn och storlek: en produkt som skapades
        # namnlös (eller utan paketstorlek) får dem från nästa källa som vet.
        if raw.name and not (product.name or "").strip():
            updates.append("name = ?")
            params.append(raw.name)
        if raw.size and not product.size:
            updates.append("size = ?")
            params.append(raw.size)
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
        keys = row.keys()
        extra = {name: (row[name] if name in keys else None) for name in (
            "manufacturer", "dabas_status", "dabas_category", "package_source",
            "package_confidence", "package_conflict",
            "provider_size", "provider_quantity", "provider_unit")}
        return Product(
            id=row["id"], gtin=row["gtin"], ean=row["ean"], name=row["name"], brand=row["brand"],
            description=row["description"], size=row["size"], quantity=row["quantity"], unit=row["unit"],
            category=row["category"], image_url=row["image_url"], image_source_url=row["image_source_url"],
            created_at=row["created_at"], updated_at=row["updated_at"], **extra,
        )

    # ---- Dabas-masterdata -----------------------------------------------

    def products_needing_dabas(self, limit: int = 200, recheck_after_seconds: float = 30 * 86400,
                              retry_error_after_seconds: float = 6 * 3600) -> list:
        """Produkter med GTIN som aldrig slagits upp, vars uppslag gav fel för
        ett tag sedan, eller vars masterdata är äldre än omprövningsfönstret.
        'not_found' omprövas bara i det längre fönstret - ett GTIN som inte
        finns i Dabas i dag finns sällan där i morgon."""
        now = time.time()
        rows = self._connection.execute(
            """
            SELECT * FROM grocery_products
            WHERE gtin IS NOT NULL AND gtin != ''
              AND (dabas_status IS NULL
                   OR (dabas_status = 'error' AND COALESCE(dabas_last_checked, 0) < ?)
                   OR (dabas_status IN ('ok', 'not_found') AND COALESCE(dabas_last_checked, 0) < ?))
            ORDER BY COALESCE(dabas_last_checked, 0), id
            LIMIT ?
            """, (now - retry_error_after_seconds, now - recheck_after_seconds, limit)).fetchall()
        return rows

    def record_dabas_check(self, product_id: int, *, status: str, error: str | None = None,
                           source_version: str | None = None):
        now = time.time()
        with self._connection:
            self._connection.execute(
                "UPDATE grocery_products SET dabas_status = ?, dabas_last_checked = ?, dabas_error = ?, "
                "dabas_last_success = CASE WHEN ? = 'ok' THEN ? ELSE dabas_last_success END, "
                "dabas_source_version = COALESCE(?, dabas_source_version) WHERE id = ?",
                (status, now, error, status, now, source_version, product_id))

    def apply_product_fields(self, product_id: int, fields: dict):
        """Fältvis uppdatering - bara nycklarna som skickas rörs. Merge-
        besluten (Dabas > provider > fallback, men aldrig null över bra
        data) fattas i enrichment.py; lagret skriver det som bestämts."""
        if not fields:
            return
        allowed = {"name", "brand", "manufacturer", "description", "size", "quantity", "unit", "category",
                   "dabas_name", "dabas_category", "dabas_gpc", "ingredients", "allergens", "nutrition",
                   "dabas_data", "package_source", "package_confidence", "package_conflict",
                   "provider_size", "provider_quantity", "provider_unit"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = time.time()
        assignments = ", ".join(f"{k} = ?" for k in updates)
        with self._connection:
            self._connection.execute(
                f"UPDATE grocery_products SET {assignments} WHERE id = ?", (*updates.values(), product_id))

    # ---- Prices --------------------------------------------------------

    def upsert_current_price(self, *, product_id: int, store_id: int, regular_price: float | None,
                              campaign_price: float | None = None, member_price: float | None = None,
                              multibuy_price: float | None = None, unit_price: float | None = None,
                              currency: str = "SEK", source_url: str | None = None,
                              fetched_at: float | None = None, source: str | None = None,
                              valid_to: float | None = None) -> tuple[CurrentPrice, bool]:
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
                                                      source_url, fetched_at, updated_at,
                                                      source, verified_at, valid_from, valid_to)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id, store_id) DO UPDATE SET
                    regular_price = excluded.regular_price, campaign_price = excluded.campaign_price,
                    member_price = excluded.member_price, multibuy_price = excluded.multibuy_price,
                    unit_price = excluded.unit_price, currency = excluded.currency,
                    source_url = excluded.source_url, fetched_at = excluded.fetched_at,
                    updated_at = excluded.updated_at,
                    source = COALESCE(excluded.source, grocery_current_prices.source),
                    verified_at = excluded.verified_at,
                    -- valid_from = när DETTA pris började gälla: behålls om
                    -- priset är oförändrat, nytt datum bara vid ändring.
                    valid_from = CASE WHEN grocery_current_prices.regular_price IS excluded.regular_price
                                       AND grocery_current_prices.campaign_price IS excluded.campaign_price
                                      THEN COALESCE(grocery_current_prices.valid_from, excluded.valid_from)
                                      ELSE excluded.valid_from END,
                    valid_to = excluded.valid_to
                """,
                (product_id, store_id, regular_price, campaign_price, member_price, multibuy_price,
                 unit_price, currency, source_url, now, now, source, now, now,
                 valid_to if campaign_price is not None else None),
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
    def _row_to_current_price(row, tier: str = "VERIFIED_STORE_PRICE") -> CurrentPrice:
        keys = row.keys()
        return CurrentPrice(
            id=row["id"], product_id=row["product_id"], store_id=row["store_id"],
            regular_price=row["regular_price"], campaign_price=row["campaign_price"],
            member_price=row["member_price"], multibuy_price=row["multibuy_price"],
            unit_price=row["unit_price"], currency=row["currency"], source_url=row["source_url"],
            fetched_at=row["fetched_at"], updated_at=row["updated_at"],
            tier=tier,
            source=row["source"] if "source" in keys else None,
            verified_at=row["verified_at"] if "verified_at" in keys else None,
            valid_from=row["valid_from"] if "valid_from" in keys else None,
            valid_to=row["valid_to"] if "valid_to" in keys else None,
        )

    # ---- Referenspriser (nivå B: kedjans pris, nationellt användbart) ----

    def upsert_reference_price(self, *, product_id: int, chain: str, regular_price, campaign_price=None,
                               member_price=None, multibuy_price=None, unit_price=None,
                               currency: str = "SEK", source: str | None = None,
                               valid_to: float | None = None, verified_at: float | None = None):
        """Samma sanering som butikspriser: ett pris <= 0 eller absurt är ett
        importfel och skrivs aldrig - raden behåller sitt gamla värde."""
        def _sane(value):
            try:
                value = float(value) if value is not None else None
            except (TypeError, ValueError):
                return None
            return value if value is not None and 0 < value <= 30000 else None
        regular_price, campaign_price = _sane(regular_price), _sane(campaign_price)
        member_price, multibuy_price, unit_price = _sane(member_price), _sane(multibuy_price), _sane(unit_price)
        if campaign_price is not None and regular_price is not None and campaign_price >= regular_price:
            campaign_price = None
        if regular_price is None and campaign_price is None:
            return False
        now = time.time()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO grocery_reference_prices (product_id, chain, regular_price, campaign_price,
                    member_price, multibuy_price, unit_price, currency, valid_from, valid_to, source,
                    verified_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id, chain) DO UPDATE SET
                    regular_price = excluded.regular_price, campaign_price = excluded.campaign_price,
                    member_price = excluded.member_price, multibuy_price = excluded.multibuy_price,
                    unit_price = excluded.unit_price, currency = excluded.currency,
                    valid_from = CASE WHEN grocery_reference_prices.regular_price IS excluded.regular_price
                                       AND grocery_reference_prices.campaign_price IS excluded.campaign_price
                                      THEN COALESCE(grocery_reference_prices.valid_from, excluded.valid_from)
                                      ELSE excluded.valid_from END,
                    valid_to = excluded.valid_to, source = excluded.source,
                    verified_at = excluded.verified_at, updated_at = excluded.updated_at
                """,
                (product_id, chain, regular_price, campaign_price, member_price, multibuy_price,
                 unit_price, currency, now, valid_to if campaign_price is not None else None,
                 source, verified_at if verified_at is not None else now, now))
        return True

    def reference_prices_for_chain(self, chain: str) -> dict[int, CurrentPrice]:
        """product_id -> referenspris för kedjan, som CurrentPrice med
        tier=REFERENCE_PRICE och store_id=0 (inget butikspåstående)."""
        prices = {}
        for row in self._connection.execute(
                "SELECT id, product_id, 0 AS store_id, regular_price, campaign_price, member_price, "
                "multibuy_price, unit_price, currency, NULL AS source_url, verified_at AS fetched_at, "
                "updated_at, source, verified_at, valid_from, valid_to "
                "FROM grocery_reference_prices WHERE chain = ?", (chain,)):
            prices[row["product_id"]] = self._row_to_current_price(row, tier="REFERENCE_PRICE")
        return prices

    def reference_price_count(self, chain: str) -> int:
        return self._connection.execute(
            "SELECT COUNT(*) FROM grocery_reference_prices WHERE chain = ?", (chain,)).fetchone()[0]

    # ---- Staging: importen landar här innan publicering ----------------

    def stage_price(self, *, run_id: int, store_id: int, product_id: int, regular_price=None,
                    campaign_price=None, member_price=None, multibuy_price=None, unit_price=None,
                    currency: str = "SEK", source_url: str | None = None, source: str | None = None,
                    valid_to: float | None = None, fetched_at: float | None = None):
        with self._connection:
            self._connection.execute(
                "INSERT INTO grocery_price_staging (run_id, store_id, product_id, regular_price, "
                "campaign_price, member_price, multibuy_price, unit_price, currency, source_url, "
                "source, valid_to, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, store_id, product_id, regular_price, campaign_price, member_price,
                 multibuy_price, unit_price, currency, source_url, source, valid_to, fetched_at))

    def staged_rows(self, run_id: int) -> list:
        return self._connection.execute(
            "SELECT * FROM grocery_price_staging WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()

    def mark_staged(self, staging_id: int, status: str, reason: str | None = None):
        self._connection.execute(
            "UPDATE grocery_price_staging SET gate_status = ?, gate_reason = ? WHERE id = ?",
            (status, reason, staging_id))

    def clear_staging(self, run_id: int):
        with self._connection:
            self._connection.execute("DELETE FROM grocery_price_staging WHERE run_id = ?", (run_id,))

    def record_run_gate(self, run_id: int, *, rows_staged: int, gate_percent: float | None,
                        published: bool, message: str | None = None):
        with self._connection:
            self._connection.execute(
                "UPDATE grocery_collector_runs SET rows_staged = ?, gate_percent = ?, published = ?, "
                "gate_message = ? WHERE id = ?",
                (rows_staged, gate_percent, int(published), message, run_id))

    def price_count_for_store(self, store_id: int) -> int:
        return self._connection.execute(
            "SELECT COUNT(*) FROM grocery_current_prices WHERE store_id = ?", (store_id,)).fetchone()[0]

    # ---- Kedjor och partner --------------------------------------------

    def upsert_chain(self, *, name: str, pricing_model: str, reference_price_available: bool = False,
                     reference_source: str | None = None, reference_store_external_id: str | None = None,
                     partner_model: str = "PER_STORE"):
        now = time.time()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO grocery_chains (name, pricing_model, reference_price_available, reference_source,
                    reference_store_external_id, partner_model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    pricing_model = excluded.pricing_model,
                    reference_price_available = excluded.reference_price_available,
                    reference_source = excluded.reference_source,
                    reference_store_external_id = excluded.reference_store_external_id,
                    partner_model = excluded.partner_model, updated_at = excluded.updated_at
                """,
                (name, pricing_model, int(reference_price_available), reference_source,
                 reference_store_external_id, partner_model, now, now))

    def get_chain(self, name: str):
        return self._connection.execute(
            "SELECT * FROM grocery_chains WHERE name = ?", (name,)).fetchone()

    def set_chain_partner(self, chain: str, partner_id: int | None):
        with self._connection:
            self._connection.execute(
                "UPDATE grocery_chains SET chain_partner_id = ?, updated_at = ? WHERE name = ?",
                (partner_id, time.time(), chain))

    def create_partner(self, *, kind: str, name: str, plan_code: str | None = "matjakt_butik",
                       chain: str | None = None, contact_email: str | None = None,
                       api_key_hash: str | None = None, monthly_price_sek: float | None = None) -> int:
        """Partnern skapas PENDING. Priset kopieras från planen vid skapandet
        så en senare planändring inte tyst ändrar befintliga avtal."""
        now = time.time()
        if monthly_price_sek is None and plan_code:
            plan = self._connection.execute(
                "SELECT monthly_price_sek FROM grocery_partner_plans WHERE code = ?", (plan_code,)).fetchone()
            monthly_price_sek = plan["monthly_price_sek"] if plan else None
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO grocery_partners (kind, name, status, plan_code, monthly_price_sek, chain, "
                "contact_email, api_key_hash, created_at, updated_at) VALUES (?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?)",
                (kind, name, plan_code, monthly_price_sek, chain, contact_email, api_key_hash, now, now))
        return cursor.lastrowid

    def get_partner(self, partner_id: int):
        return self._connection.execute(
            "SELECT * FROM grocery_partners WHERE id = ?", (partner_id,)).fetchone()

    def partner_by_key_hash(self, api_key_hash: str):
        return self._connection.execute(
            "SELECT * FROM grocery_partners WHERE api_key_hash = ?", (api_key_hash,)).fetchone()

    def set_partner_status(self, partner_id: int, status: str):
        now = time.time()
        with self._connection:
            self._connection.execute(
                "UPDATE grocery_partners SET status = ?, updated_at = ?, "
                "started_at = CASE WHEN ? = 'ACTIVE' AND started_at IS NULL THEN ? ELSE started_at END, "
                "ended_at = CASE WHEN ? IN ('CANCELLED') THEN ? ELSE ended_at END WHERE id = ?",
                (status, now, status, now, status, now, partner_id))

    def link_partner_store(self, partner_id: int, store_id: int):
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO grocery_partner_stores (partner_id, store_id) VALUES (?, ?)",
                (partner_id, store_id))
            self._connection.execute(
                "UPDATE grocery_stores SET partner_id = ?, updated_at = ? WHERE id = ?",
                (partner_id, time.time(), store_id))

    def partner_store_ids(self, partner_id: int) -> list[int]:
        return [row[0] for row in self._connection.execute(
            "SELECT store_id FROM grocery_partner_stores WHERE partner_id = ?", (partner_id,))]

    def list_partners(self) -> list:
        return self._connection.execute(
            "SELECT * FROM grocery_partners ORDER BY id").fetchall()

    def record_partner_feed(self, *, partner_id: int, store_id: int, format: str, status: str,
                            rows_received: int, rows_published: int, gate_percent: float | None,
                            message: str | None = None):
        with self._connection:
            self._connection.execute(
                "INSERT INTO grocery_partner_feeds (partner_id, store_id, format, status, rows_received, "
                "rows_published, gate_percent, message, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (partner_id, store_id, format, status, rows_received, rows_published, gate_percent,
                 message, time.time()))

    def latest_partner_feed(self, store_id: int):
        return self._connection.execute(
            "SELECT * FROM grocery_partner_feeds WHERE store_id = ? ORDER BY id DESC LIMIT 1",
            (store_id,)).fetchone()

    def delete_prices_from_source(self, source_prefix: str) -> int:
        """Partnerns priser försvinner när partnern inte längre är ACTIVE:
        utan aktiv leverantör finns ingen som går i god för dem."""
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM grocery_current_prices WHERE source LIKE ?", (source_prefix + "%",))
        return cursor.rowcount

    def bump_partner_stat(self, store_id: int, event: str, day: str, amount: int = 1):
        with self._connection:
            self._connection.execute(
                "INSERT INTO grocery_partner_stats (store_id, day, event, count) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(store_id, day, event) DO UPDATE SET count = count + excluded.count",
                (store_id, day, event, amount))

    def partner_stats(self, store_id: int, days: int = 30) -> dict[str, int]:
        rows = self._connection.execute(
            "SELECT event, SUM(count) FROM grocery_partner_stats WHERE store_id = ? "
            "AND day >= date('now', ?) GROUP BY event", (store_id, f"-{int(days)} days")).fetchall()
        return {row[0]: row[1] for row in rows}

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
                     WHERE status IS NOT NULL AND status != 'running'),
                   -- Referensnivån och partnerstatus ändrar också vad
                   -- kunderna ser (backfill, paus som raderar priser).
                   (SELECT CAST(COALESCE(MAX(updated_at), 0) AS INTEGER) FROM grocery_reference_prices),
                   (SELECT CAST(COALESCE(MAX(updated_at), 0) AS INTEGER) FROM grocery_partners)
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
