# -*- coding: utf-8 -*-
"""Matjakts egen receptdatabas.

Recipes used to be two hardcoded arrays inside app.js, then a JSON file. Both
worked at 58 recipes and neither scales: the amounts lived in a SEPARATE
table (RECIPE_QUANTITIES, keyed by recipe id AND ingredient name), so an
ingredient and its quantity could drift apart, and nothing linked either to
the grocery products they are supposed to be priced against.

This module is the real thing. Two design decisions carry most of the weight:

STRUCTURED INGREDIENTS, NOT STRINGS. An ingredient is a row with an amount, a
unit and a NORMALIZED ID - not the string "Kycklinglårfilé" with its 600 g
stored somewhere else. The normalized id is what connects a recipe to the
grocery side:

    recipe -> ingredient.normalized_id -> product match -> package maths -> cost

The id is derived with the SAME accent-folding the pricing engine matches
with (grocery/pricing.py's _fold), then slugified. Matching itself still
happens on the ingredient NAME - the id is what makes the same ingredient
recognisable across recipes and indexable. A test pins the derivation so the
two cannot drift apart unnoticed.

IMAGES ARE REFERENCES, WITH THEIR RIGHTS. A recipe carries image, source,
credit, licence and alt text. Rights we cannot state are rights we do not
have, so a recipe with no licensed image gets no image rather than a
plausible-looking one - a photo of the wrong dish is worse than an honest
placeholder. Nothing here fetches or searches for an image; the reference is
data, and swapping in a different picture never touches recipe logic.
"""

import re
import sqlite3
import time
import unicodedata
from pathlib import Path


def normalize_ingredient_id(name: str) -> str:
    """The stable key that links a recipe ingredient to grocery matching.

    Built by applying the SAME accent-folding the pricing engine matches with
    (grocery/pricing.py's _fold) and then slugifying: lowercase, accents
    stripped, every run of non-letters collapsed to one dash.

    It is NOT byte-identical to _fold's output - _fold keeps spaces and "&",
    a slug cannot - so this is a derived key, not the matching key itself.
    Product matching still happens on the ingredient NAME; normalized_id is
    what lets the same ingredient be recognised across recipes, indexed, and
    counted. A test pins the derivation so the two cannot drift apart for
    reasons nobody can see."""
    lowered = str(name or "").lower().strip()
    folded = "".join(c for c in unicodedata.normalize("NFD", lowered)
                     if unicodedata.category(c) != "Mn")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", folded)).strip("-")


def _row_get(row, key):
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


class RecipeStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._migrate()

    @property
    def connection(self):
        return self._connection

    def close(self):
        self._connection.close()

    def _migrate(self):
        """Adds columns that postdate existing production databases.

        The price columns hold what the PRICING run computed, not what anyone
        typed: a real portion cost against a real chain, with its coverage,
        so a card can show a price that is genuinely defensible - or no price
        at all. ALTER-if-missing because production's recipes.db predates
        them and must not be rebuilt (it would lose backfilled images)."""
        have = {row[1] for row in self._connection.execute("PRAGMA table_info(recipes)")}
        wanted = {
            "price_per_portion": "REAL",
            "price_chain": "TEXT",
            "price_covered": "INTEGER",
            "price_total": "INTEGER",
            "priced_at": "REAL",
        }
        with self._connection:
            for column, kind in wanted.items():
                if column not in have:
                    self._connection.execute(
                        f"ALTER TABLE recipes ADD COLUMN {column} {kind}")

    def get_meta(self, key: str):
        try:
            row = self._connection.execute(
                "SELECT value FROM recipe_meta WHERE key = ?", (key,)).fetchone()
        except Exception:
            return None
        return row["value"] if row else None

    def set_meta(self, key: str, value: str):
        with self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS recipe_meta (key TEXT PRIMARY KEY, value TEXT)")
            self._connection.execute(
                "INSERT INTO recipe_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def set_price(self, recipe_id: str, *, price_per_portion, chain,
                  covered: int, total: int):
        """Records one pricing run's verdict for a recipe.

        price_per_portion may be None - "we could not price this" is a valid
        verdict and must overwrite a stale success, or a recipe whose
        ingredient lost its product match would keep advertising the old
        price forever."""
        import time as _time
        with self._connection:
            self._connection.execute(
                """UPDATE recipes SET price_per_portion = ?, price_chain = ?,
                   price_covered = ?, price_total = ?, priced_at = ?
                   WHERE id = ?""",
                (price_per_portion, chain, covered, total, _time.time(), recipe_id))

    def _init_schema(self):
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS recipes (
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
            );

            -- One row per ingredient, with its amount. Previously the amounts
            -- lived in a separate table keyed by name, which let an
            -- ingredient and its quantity drift apart silently.
            CREATE TABLE IF NOT EXISTS recipe_ingredients (
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

            CREATE TABLE IF NOT EXISTS recipe_steps (
                recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                instruction TEXT NOT NULL,
                PRIMARY KEY (recipe_id, position)
            );

            -- Tags, categories, allergens and diet flags share one table:
            -- they are all "a label of some kind on a recipe", and separate
            -- tables would mean four near-identical queries for every filter
            -- the recipe page offers.
            CREATE TABLE IF NOT EXISTS recipe_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS recipe_labels (
                recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (recipe_id, kind, value)
            );

            -- The recipe page filters on labels and sorts on time, price and
            -- protein. Without these, every filter is a full scan - fine at
            -- 58 recipes, not at 5 000.
            CREATE INDEX IF NOT EXISTS idx_recipe_labels_lookup
                ON recipe_labels(kind, value);
            CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_normalized
                ON recipe_ingredients(normalized_id);
            CREATE INDEX IF NOT EXISTS idx_recipes_time ON recipes(total_time);
            CREATE INDEX IF NOT EXISTS idx_recipes_protein ON recipes(protein);
            """
        )
        # Added after the first release - sqlite has no "ADD COLUMN IF NOT
        # EXISTS", and this file has no migration runner.
        for column in ("image_source_url TEXT", "image_status TEXT"):
            try:
                self._connection.execute(f"ALTER TABLE recipes ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass
        self._connection.commit()

    # ---- writing ---------------------------------------------------------

    def upsert_recipe(self, recipe: dict) -> str:
        """Writes one recipe and everything hanging off it, in a transaction.

        Labels, ingredients and steps are replaced wholesale rather than
        merged: a recipe edited to have fewer ingredients must not keep the
        old ones, and working out which rows to delete is the kind of
        bookkeeping that goes wrong quietly."""
        now = time.time()
        recipe_id = recipe["id"]
        with self._connection:
            existing = self._connection.execute(
                "SELECT created_at FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
            self._connection.execute(
                """
                INSERT INTO recipes (id, slug, name, description, servings, prep_time,
                    cook_time, total_time, difficulty, kcal, protein, carbs, fat, fiber,
                    image, image_source, image_source_url, image_credit, image_license,
                    image_alt, image_status, created_at, updated_at)
                VALUES (:id, :slug, :name, :description, :servings, :prep_time,
                    :cook_time, :total_time, :difficulty, :kcal, :protein, :carbs, :fat,
                    :fiber, :image, :image_source, :image_source_url, :image_credit,
                    :image_license, :image_alt, :image_status, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    slug=excluded.slug, name=excluded.name, description=excluded.description,
                    servings=excluded.servings, prep_time=excluded.prep_time,
                    cook_time=excluded.cook_time, total_time=excluded.total_time,
                    difficulty=excluded.difficulty, kcal=excluded.kcal,
                    protein=excluded.protein, carbs=excluded.carbs, fat=excluded.fat,
                    fiber=excluded.fiber, image=excluded.image,
                    image_source=excluded.image_source,
                    image_source_url=excluded.image_source_url,
                    image_credit=excluded.image_credit,
                    image_license=excluded.image_license, image_alt=excluded.image_alt,
                    image_status=excluded.image_status, updated_at=excluded.updated_at
                """,
                {
                    "id": recipe_id,
                    "slug": recipe.get("slug") or normalize_ingredient_id(recipe["name"]),
                    "name": recipe["name"],
                    "description": recipe.get("description"),
                    "servings": int(recipe.get("servings") or 4),
                    "prep_time": recipe.get("prepTime"),
                    "cook_time": recipe.get("cookTime"),
                    "total_time": recipe.get("totalTime"),
                    "difficulty": recipe.get("difficulty"),
                    "kcal": recipe.get("kcal"), "protein": recipe.get("protein"),
                    "carbs": recipe.get("carbs"), "fat": recipe.get("fat"),
                    "fiber": recipe.get("fiber"),
                    "image": recipe.get("image"),
                    "image_source": recipe.get("imageSource"),
                    "image_source_url": recipe.get("imageSourceUrl"),
                    "image_credit": recipe.get("imageCredit"),
                    "image_license": recipe.get("imageLicense"),
                    "image_alt": recipe.get("imageAlt"),
                    "image_status": recipe.get("imageStatus") or ("ok" if recipe.get("image") else "needs_image"),
                    "created_at": existing["created_at"] if existing else now,
                    "updated_at": now,
                },
            )
            for table in ("recipe_ingredients", "recipe_steps", "recipe_labels"):
                self._connection.execute(f"DELETE FROM {table} WHERE recipe_id = ?", (recipe_id,))

            for position, ingredient in enumerate(recipe.get("ingredients") or []):
                name = ingredient["name"]
                self._connection.execute(
                    """INSERT INTO recipe_ingredients (recipe_id, position, name, amount,
                       unit, normalized_id, optional, pantry_staple, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (recipe_id, position, name, ingredient.get("amount"),
                     ingredient.get("unit"),
                     ingredient.get("normalizedId") or normalize_ingredient_id(name),
                     int(bool(ingredient.get("optional"))),
                     int(bool(ingredient.get("pantryStaple"))), ingredient.get("note")),
                )
            for position, step in enumerate(recipe.get("instructions") or []):
                self._connection.execute(
                    "INSERT INTO recipe_steps (recipe_id, position, instruction) VALUES (?, ?, ?)",
                    (recipe_id, position, step))
            for kind in ("categories", "tags", "allergens", "dietFlags"):
                for value in recipe.get(kind) or []:
                    self._connection.execute(
                        "INSERT OR IGNORE INTO recipe_labels (recipe_id, kind, value) VALUES (?, ?, ?)",
                        (recipe_id, kind, value))
        return recipe_id

    # ---- reading ---------------------------------------------------------

    def _labels(self, recipe_id: str) -> dict:
        labels = {"categories": [], "tags": [], "allergens": [], "dietFlags": []}
        for row in self._connection.execute(
                "SELECT kind, value FROM recipe_labels WHERE recipe_id = ? ORDER BY kind, value",
                (recipe_id,)):
            labels.setdefault(row["kind"], []).append(row["value"])
        return labels

    def _to_dict(self, row) -> dict:
        recipe_id = row["id"]
        ingredients = [
            {"name": r["name"], "amount": r["amount"], "unit": r["unit"],
             "normalizedId": r["normalized_id"], "optional": bool(r["optional"]),
             "pantryStaple": bool(r["pantry_staple"]), "note": r["note"]}
            for r in self._connection.execute(
                "SELECT * FROM recipe_ingredients WHERE recipe_id = ? ORDER BY position",
                (recipe_id,))
        ]
        steps = [r["instruction"] for r in self._connection.execute(
            "SELECT instruction FROM recipe_steps WHERE recipe_id = ? ORDER BY position",
            (recipe_id,))]
        return {
            "id": recipe_id, "slug": row["slug"], "name": row["name"],
            "description": row["description"], "servings": row["servings"],
            "prepTime": row["prep_time"], "cookTime": row["cook_time"],
            "totalTime": row["total_time"], "difficulty": row["difficulty"],
            "nutrition": {"kcal": row["kcal"], "protein": row["protein"],
                          "carbs": row["carbs"], "fat": row["fat"], "fiber": row["fiber"]},
            "image": row["image"], "imageSource": row["image_source"],
            "imageSourceUrl": row["image_source_url"],
            "imageCredit": row["image_credit"], "imageLicense": row["image_license"],
            "imageAlt": row["image_alt"], "imageStatus": row["image_status"],
            "ingredients": ingredients, "instructions": steps,
            "pricePerPortion": _row_get(row, "price_per_portion"),
            "priceChain": _row_get(row, "price_chain"),
            "priceCovered": _row_get(row, "price_covered"),
            "priceTotal": _row_get(row, "price_total"),
            "pricedAt": _row_get(row, "priced_at"),
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
            **self._labels(recipe_id),
        }

    def delete(self, recipe_id: str) -> bool:
        """Removes a recipe and everything hanging off it."""
        with self._connection:
            cursor = self._connection.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            for table in ("recipe_ingredients", "recipe_steps", "recipe_labels"):
                self._connection.execute(f"DELETE FROM {table} WHERE recipe_id = ?", (recipe_id,))
        return cursor.rowcount > 0

    def id_for_slug(self, slug: str) -> str | None:
        row = self._connection.execute("SELECT id FROM recipes WHERE slug = ?", (slug,)).fetchone()
        return row["id"] if row else None

    def get(self, recipe_id: str) -> dict | None:
        row = self._connection.execute("SELECT * FROM recipes WHERE id = ? OR slug = ?",
                                       (recipe_id, recipe_id)).fetchone()
        return self._to_dict(row) if row else None

    def count(self) -> int:
        return self._connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]

    def search(self, *, tags=None, max_time=None, min_protein=None, max_kcal=None,
               query=None, limit=200, offset=0) -> list[dict]:
        """Filtering happens in SQL, not by loading every recipe and sifting
        it in Python - which is the difference between 58 recipes and 5 000."""
        where, params = [], []
        for tag in tags or []:
            where.append("""id IN (SELECT recipe_id FROM recipe_labels
                            WHERE kind IN ('tags','categories','dietFlags') AND value = ?)""")
            params.append(tag)
        if max_time is not None:
            where.append("total_time IS NOT NULL AND total_time <= ?")
            params.append(max_time)
        if min_protein is not None:
            where.append("protein IS NOT NULL AND protein >= ?")
            params.append(min_protein)
        if max_kcal is not None:
            where.append("kcal IS NOT NULL AND kcal <= ?")
            params.append(max_kcal)
        if query:
            where.append("(name LIKE ? OR description LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
        sql = "SELECT * FROM recipes"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY name LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [self._to_dict(row) for row in self._connection.execute(sql, params)]

    def stats(self) -> dict:
        """What the bank actually contains - used by the report and by the
        admin panel, so a claim about the catalogue can be checked."""
        total = self.count()
        by_label = {}
        for row in self._connection.execute(
                """SELECT value, COUNT(*) n FROM recipe_labels
                   WHERE kind IN ('tags','categories') GROUP BY value ORDER BY n DESC"""):
            by_label[row["value"]] = row["n"]
        complete_nutrition = self._connection.execute(
            """SELECT COUNT(*) FROM recipes WHERE kcal IS NOT NULL AND protein IS NOT NULL
               AND carbs IS NOT NULL AND fat IS NOT NULL""").fetchone()[0]
        with_image = self._connection.execute(
            "SELECT COUNT(*) FROM recipes WHERE image IS NOT NULL AND image != ''").fetchone()[0]
        licensed = self._connection.execute(
            """SELECT COUNT(*) FROM recipes WHERE image IS NOT NULL AND image != ''
               AND image_license IS NOT NULL AND image_license != ''""").fetchone()[0]
        needs_image = self._connection.execute(
            "SELECT COUNT(*) FROM recipes WHERE image_status = 'needs_image'").fetchone()[0]
        return {"total": total, "byLabel": by_label, "needsImage": needs_image,
                "completeNutrition": complete_nutrition,
                "withImage": with_image, "withLicensedImage": licensed}
