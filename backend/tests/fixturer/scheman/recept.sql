CREATE TABLE recipe_ingredients (
                recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                name TEXT NOT NULL,
                amount REAL,
                unit TEXT,
                -- The link to the grocery side, derived with the same
                -- accent-folding the pricing engine matches with.
                normalized_id TEXT NOT NULL,
                optional INTEGER NOT NULL DEFAULT 0,
                -- Things assumed to be in the cupboard (salt, pepper, oil)
                -- are listed but not bought, so a shopping list does not tell
                -- someone to buy salt every week.
                pantry_staple INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                PRIMARY KEY (recipe_id, position)
            );
CREATE TABLE recipe_labels (
                recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (recipe_id, kind, value)
            );
CREATE TABLE recipe_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
CREATE TABLE recipe_steps (
                recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                instruction TEXT NOT NULL,
                PRIMARY KEY (recipe_id, position)
            );
CREATE TABLE recipes (
                id TEXT PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                servings INTEGER NOT NULL DEFAULT 4,
                prep_time INTEGER,
                cook_time INTEGER,
                total_time INTEGER,
                difficulty TEXT,
                kcal REAL, protein REAL, carbs REAL, fat REAL, fiber REAL,
                -- Image as a REFERENCE plus its rights. A licence we cannot
                -- state is a licence we do not have.
                image TEXT,
                image_source TEXT,
                -- The page the file came from, so an attribution can link
                -- back to it and a licence claim can be checked later.
                image_source_url TEXT,
                image_credit TEXT,
                image_license TEXT,
                image_alt TEXT,
                -- "ok" or "needs_image". Without persisting this, a recipe
                -- that failed to get a picture looked identical to one that
                -- was never asked - and the gaps could not be found.
                image_status TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            , price_per_portion REAL, price_chain TEXT, price_covered INTEGER, price_total INTEGER, priced_at REAL);
CREATE INDEX idx_recipe_ingredients_normalized
                ON recipe_ingredients(normalized_id);
CREATE INDEX idx_recipe_labels_lookup
                ON recipe_labels(kind, value);
CREATE INDEX idx_recipes_protein ON recipes(protein);
CREATE INDEX idx_recipes_time ON recipes(total_time);
PRAGMA user_version = 1;
