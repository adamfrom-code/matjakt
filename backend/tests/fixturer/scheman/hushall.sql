CREATE TABLE household_docs (
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                doc TEXT NOT NULL,
                body TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by INTEGER,
                revision INTEGER NOT NULL,
                PRIMARY KEY (household_id, doc)
            );
CREATE TABLE household_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                actor_user_id INTEGER,
                payload TEXT,
                created_at TEXT NOT NULL
            );
CREATE TABLE household_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                used_by INTEGER,
                revoked_at TEXT
            );
CREATE TABLE household_members (
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                display_name TEXT,
                profile TEXT,
                joined_at TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (household_id, user_id)
            );
CREATE TABLE households (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1
            );
CREATE TABLE inventory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT 'skafferi',
                amount REAL NOT NULL DEFAULT 0,
                unit TEXT,
                category TEXT,
                expiry TEXT,
                gtin TEXT,
                product TEXT,
                deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by INTEGER,
                revision INTEGER NOT NULL,
                UNIQUE (household_id, item_key)
            );
CREATE TABLE shopping_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                amount REAL,
                unit TEXT,
                status TEXT NOT NULL DEFAULT 'NEED_TO_BUY',
                source TEXT NOT NULL DEFAULT 'week',
                category TEXT,
                product TEXT,
                note TEXT,
                deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by INTEGER,
                revision INTEGER NOT NULL,
                UNIQUE (household_id, item_key)
            );
CREATE INDEX idx_events_household ON household_events(household_id, id);
CREATE INDEX idx_inventory_rev ON inventory_items(household_id, revision);
CREATE INDEX idx_members_user ON household_members(user_id);
CREATE INDEX idx_shopping_rev ON shopping_items(household_id, revision);
