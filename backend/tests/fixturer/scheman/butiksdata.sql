CREATE TABLE grocery_chains (
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
CREATE TABLE grocery_collector_runs (
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
            , rows_staged INTEGER, gate_percent REAL, published INTEGER, gate_message TEXT);
CREATE TABLE grocery_current_prices (
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
                updated_at REAL NOT NULL, source TEXT, verified_at REAL, valid_from REAL, valid_to REAL,
                UNIQUE(product_id, store_id)
            );
CREATE TABLE grocery_partner_feeds (
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
CREATE TABLE grocery_partner_plans (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                monthly_price_sek REAL NOT NULL,
                billing_model TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL
            );
CREATE TABLE grocery_partner_stats (
                store_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                event TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (store_id, day, event)
            );
CREATE TABLE grocery_partner_stores (
                partner_id INTEGER NOT NULL REFERENCES grocery_partners(id),
                store_id INTEGER NOT NULL REFERENCES grocery_stores(id),
                PRIMARY KEY (partner_id, store_id)
            );
CREATE TABLE grocery_partners (
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
CREATE TABLE grocery_price_history (
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
CREATE TABLE grocery_price_staging (
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
CREATE TABLE grocery_product_external_ids (
                chain TEXT NOT NULL,
                external_product_id TEXT NOT NULL,
                product_id INTEGER NOT NULL REFERENCES grocery_products(id),
                PRIMARY KEY (chain, external_product_id)
            );
CREATE TABLE grocery_products (
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
            , manufacturer TEXT, dabas_name TEXT, dabas_category TEXT, dabas_gpc TEXT, ingredients TEXT, allergens TEXT, nutrition TEXT, dabas_data TEXT, dabas_status TEXT, dabas_last_checked REAL, dabas_last_success REAL, dabas_error TEXT, dabas_source_version TEXT, package_source TEXT, package_confidence TEXT, package_conflict TEXT, provider_size TEXT, provider_quantity REAL, provider_unit TEXT);
CREATE TABLE grocery_reference_prices (
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
CREATE TABLE grocery_stores (
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
                updated_at REAL NOT NULL, provider TEXT, pricing_scope TEXT, ownership_type TEXT, partner_status TEXT NOT NULL DEFAULT 'NONE', partner_id INTEGER,
                UNIQUE(chain, external_store_id)
            );
CREATE INDEX idx_grocery_current_prices_store
                ON grocery_current_prices(store_id, product_id);
CREATE INDEX idx_grocery_external_ids_chain
                ON grocery_product_external_ids(chain, product_id);
CREATE INDEX idx_grocery_price_history_lookup
                ON grocery_price_history(product_id, store_id, timestamp DESC);
CREATE INDEX idx_grocery_price_staging_run
                ON grocery_price_staging(run_id);
CREATE INDEX idx_grocery_products_category
                ON grocery_products(category);
CREATE UNIQUE INDEX idx_grocery_products_ean
                ON grocery_products(ean) WHERE ean IS NOT NULL AND ean != '';
CREATE UNIQUE INDEX idx_grocery_products_gtin
                ON grocery_products(gtin) WHERE gtin IS NOT NULL AND gtin != '';
CREATE INDEX idx_grocery_products_normalized_key
                ON grocery_products(normalized_key);
CREATE INDEX idx_grocery_reference_prices_chain
                ON grocery_reference_prices(chain);
