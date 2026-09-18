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

ETT ID ÄR FÖR ALLTID (P04b). Tio rätter låg i banken under två id var -
`scampi` och `rakpasta-vitlok` var samma pasta - och favoriter, veckor och
historik bar de gamla id:na. Det receptet som blev kvar bär de andra id:na
som `aliases`, lagrade i `recipe_aliases`, och `get()` svarar med det
kanoniska receptet för vilket av dem som helst. Ett alias är en pekare, inte
ett recept: det finns inte i `search()`, i hyllorna eller bland
veckokandidaterna, så planeraren kan inte föreslå samma rätt två gånger
under två namn. Vilka id som är alias avgörs i docs/RECEPTIDENTITET.md, inte
av en likhetssiffra.
"""

import re
import sqlite3
import time
import unicodedata
from pathlib import Path

from ..data_guard import guard_database_path
from .labels import LABELS, LEGACY_KINDS, display as label_display
from .labels import merge as merge_labels
from .labels import normalize_label_id
from .meal_types import protein_of, require_dinner_protein
from ..schema_version import RECEPT, stämpla
from .meal_types import require as require_meal_type
from .pantry import is_pantry_staple


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
        # Testläge får aldrig nå en riktig databas - se services/data_guard.py.
        guard_database_path(db_path, purpose="receptdatabasen")
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
        them and must not be rebuilt (it would lose backfilled images).

        `meal_type` (M1) säger vad rätten är TILL FÖR. Den läggs till på
        samma sätt och av samma skäl - och med samma två egenskaper som gör
        varje migration här återställningssäker (K6): den är rent additiv,
        och kolumnen är nullbar utan `NOT NULL`. Efter en rollback kör gammal
        kod mot en databas ny kod redan migrerat, och en `INSERT` som bara
        nämner de gamla kolumnerna måste fortsätta gå igenom.

        Kolumnen får AVSIKTLIGT ingen `CHECK`-begränsning: SQLite kan inte
        lägga till en sådan i efterhand utan att bygga om tabellen, och en
        ombyggd `recipes` är precis det som aldrig får hända i produktion (den
        bär bakfyllda bilder). Det stängda värdeförrådet hålls i stället vid
        SKRIVNING - se `meal_types.require`.

        Metoden är idempotent och tål att köras om: `PRAGMA table_info` läses
        varje gång, och en kolumn som redan finns läggs inte till igen."""
        have = {row[1] for row in self._connection.execute("PRAGMA table_info(recipes)")}
        wanted = {
            "price_per_portion": "REAL",
            "price_chain": "TEXT",
            "price_covered": "INTEGER",
            "price_total": "INTEGER",
            "priced_at": "REAL",
            "meal_type": "TEXT",
        }
        with self._connection:
            for column, kind in wanted.items():
                if column not in have:
                    self._connection.execute(
                        f"ALTER TABLE recipes ADD COLUMN {column} {kind}")
            # Veckoplaneringen frågar efter EN sak ur den här tabellen -
            # middagarna - och gör det vid varje veckobygge.
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_recipes_meal_type ON recipes(meal_type)")
            etiketter = {row[1] for row in
                         self._connection.execute("PRAGMA table_info(recipe_labels)")}
            if "position" not in etiketter:
                self._connection.execute(
                    "ALTER TABLE recipe_labels ADD COLUMN position INTEGER")
        self._merge_legacy_labels()
        # Schemat är nu det version RECEPT beskriver - stämpla filen, så att en
        # människa efter ett rollback kan LÄSA vilken version den bär i
        # stället för att gissa. Se services/schema_version.py.
        stämpla(self._connection, RECEPT)

    def _merge_legacy_labels(self) -> int:
        """M4: slår ihop `categories` och `tags` till ETT fält, i befintlig db.

        Källorna är sanningen och skrivs om av sitt eget skript, men en redan
        driftsatt bank ska bli konsekvent av att ÖPPNAS - annars lever felet
        kvar tills nästa import, och importen körs bara när källornas
        fingeravtryck ändras.

        Ordningen är det känsliga. Före M4 lästes etiketterna med `ORDER BY
        kind, value`, och eftersom 'categories' < 'tags' alfabetiskt kom
        kategorierna först - vilket är den ordning appen har visat sin badge
        ur. Sammanslagningen läser därför i exakt den ordningen och fryser den
        som `position`, så att det första namnet är oförändrat efter
        migreringen. En datastädning får inte byta text på ett recept.

        Idempotent och återupptagbar: redan migrerade rader läses in först och
        behåller sin plats, gamla rader vävs in efter dem, och en bank utan
        gamla rader rörs inte alls."""
        legacy = ",".join("?" * len(LEGACY_KINDS))
        berorda = [row["recipe_id"] for row in self._connection.execute(
            f"SELECT DISTINCT recipe_id FROM recipe_labels WHERE kind IN ({legacy})",
            LEGACY_KINDS)]
        if not berorda:
            return 0
        with self._connection:
            for recipe_id in berorda:
                redan = [row["value"] for row in self._connection.execute(
                    "SELECT value FROM recipe_labels WHERE recipe_id = ? AND kind = ? "
                    "ORDER BY position IS NULL, position, value", (recipe_id, LABELS))]
                gamla = [row["value"] for row in self._connection.execute(
                    f"SELECT value FROM recipe_labels WHERE recipe_id = ? "
                    f"AND kind IN ({legacy}) ORDER BY kind, value",
                    (recipe_id, *LEGACY_KINDS))]
                self._connection.execute(
                    f"DELETE FROM recipe_labels WHERE recipe_id = ? "
                    f"AND kind IN ({legacy},?)", (recipe_id, *LEGACY_KINDS, LABELS))
                self._write_labels(recipe_id, merge_labels(redan, gamla))
        return len(berorda)

    def _write_labels(self, recipe_id: str, keys) -> None:
        """Skriver det sammanslagna etikettfältet. Nycklar in, ordning bevarad."""
        for position, key in enumerate(keys):
            self._connection.execute(
                "INSERT OR IGNORE INTO recipe_labels (recipe_id, kind, value, position) "
                "VALUES (?, ?, ?, ?)", (recipe_id, LABELS, key, position))

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

            -- Labels, allergens and diet flags share one table: they are all
            -- "a label of some kind on a recipe", and separate tables would
            -- mean three near-identical queries for every filter the recipe
            -- page offers.
            --
            -- `value` är ALLTID en nyckel (gemen, utan diakriter - se
            -- labels.normalize_label_id), aldrig ett visningsnamn. Fram till
            -- M4 fanns `kind` 'categories' och 'tags' med överlappande
            -- innehåll i var sin versalisering, och filtret jämförde med
            -- likhet: den som sökte `kott` missade `Kött`. De två är numera
            -- ETT fält, kind 'labels', och namnet räknas fram ur nyckeln vid
            -- läsning i stället för att lagras en gång per rad.
            --
            -- `position` bär receptets egen etikettordning. Den är data, inte
            -- kosmetik: appen visar den första etiketten som badge på kortet.
            CREATE TABLE IF NOT EXISTS recipe_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS recipe_labels (
                recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                position INTEGER,
                PRIMARY KEY (recipe_id, kind, value)
            );

            -- P04b: ett gammalt id som fortsätter öppna rätt recept. Raden är
            -- en pekare, inte ett recept. `get()` prövar `recipes` FÖRST och
            -- den här tabellen sedan, så ett id som är både rad och alias -
            -- en källfil som återställts efter en sammanslagning - svarar
            -- med raden. Rent additiv (K6): gammal kod ser den inte, och en
            -- INSERT som bara känner de gamla tabellerna går fortfarande
            -- igenom. Kaskaden tar aliasen med sig när receptet tas bort.
            CREATE TABLE IF NOT EXISTS recipe_aliases (
                alias_id TEXT PRIMARY KEY,
                recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_recipe_aliases_recipe
                ON recipe_aliases(recipe_id);

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
        bookkeeping that goes wrong quietly.

        `mealType` är undantaget från "ersätt rakt av": utelämnas det behåller
        raden sitt befintliga värde (`COALESCE`). Bildbakfyllningen skriver
        tillbaka hela recept den läst ur databasen och en delmängdsuppdatering
        får inte råka nolla klassificeringen. Ett MEDSKICKAT värde prövas
        däremot mot det stängda värdeförrådet och avvisas om det inte hör dit
        - ett felstavat `meal_type` upptäcks annars först som en frukost i
        någons middagsvecka.

        M5: en `middag` prövas dessutom mot proteingolvet. Klassificeringen
        läses ur raden när skrivningen inte bär någon egen (`COALESCE` ovan),
        så en delmängdsuppdatering som sänker proteinet på ett recept som
        redan STÅR som middag fångas också - annars hade hålet bara flyttat
        sig ett steg."""
        now = time.time()
        recipe_id = recipe["id"]
        meal_type = recipe.get("mealType", recipe.get("meal_type"))
        if meal_type is not None:
            meal_type = require_meal_type(meal_type, recipe_id=str(recipe_id))
        with self._connection:
            existing = self._connection.execute(
                "SELECT created_at, meal_type FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
            require_dinner_protein(
                meal_type if meal_type is not None
                else (existing["meal_type"] if existing else None),
                protein_of(recipe), recipe_id=str(recipe_id),
                name=str(recipe.get("name") or ""))
            self._connection.execute(
                """
                INSERT INTO recipes (id, slug, name, description, servings, prep_time,
                    cook_time, total_time, difficulty, kcal, protein, carbs, fat, fiber,
                    image, image_source, image_source_url, image_credit, image_license,
                    image_alt, image_status, meal_type, created_at, updated_at)
                VALUES (:id, :slug, :name, :description, :servings, :prep_time,
                    :cook_time, :total_time, :difficulty, :kcal, :protein, :carbs, :fat,
                    :fiber, :image, :image_source, :image_source_url, :image_credit,
                    :image_license, :image_alt, :image_status, :meal_type,
                    :created_at, :updated_at)
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
                    image_status=excluded.image_status,
                    meal_type=COALESCE(excluded.meal_type, recipes.meal_type),
                    updated_at=excluded.updated_at
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
                    "meal_type": meal_type,
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
                     # HÄRLEDD, inte kopierad (M3). "Antas finnas hemma" är en
                     # egenskap hos INGREDIENSEN, inte hos raden - och när den
                     # avgjordes rad för rad blev ägg prissatt i 34 recept och
                     # gratis i 2. Att läsa svaret ur services/recipes/pantry.py
                     # gör "samma ingrediens, samma klassning" sant av
                     # konstruktion, i varje databas som någonsin skrivs: en
                     # felaktig flagga i en källfil kan inte överleva en import.
                     int(is_pantry_staple(name)), ingredient.get("note")),
                )
            for position, step in enumerate(recipe.get("instructions") or []):
                self._connection.execute(
                    "INSERT INTO recipe_steps (recipe_id, position, instruction) VALUES (?, ?, ?)",
                    (recipe_id, position, step))
            # ETT etikettfält (M4). `categories` och `tags` tas fortfarande
            # EMOT - källfiler, fixturer och äldre anropare skriver dem än -
            # men de vävs ihop till samma fält på väg in i stället för att
            # lagras var för sig. Kategorierna först: den ordningen är den
            # appen har visat sin badge ur, och en etikettstädning ska inte
            # byta text på ett receptkort.
            self._write_labels(recipe_id, merge_labels(
                recipe.get(LABELS), recipe.get("categories"), recipe.get("tags")))
            for kind in ("allergens", "dietFlags"):
                for value in recipe.get(kind) or []:
                    self._connection.execute(
                        "INSERT OR IGNORE INTO recipe_labels (recipe_id, kind, value) VALUES (?, ?, ?)",
                        (recipe_id, kind, value))
            # Aliasen ersätts bara när skrivningen BÄR fältet - som mealType.
            # Bildbakfyllningen och äldre anropare skriver recept utan det,
            # och en delmängdsuppdatering får inte tyst koppla loss tio
            # gamla id från sina rätter.
            if "aliases" in recipe:
                self._write_aliases(recipe_id, recipe.get("aliases") or [])
        return recipe_id

    def _write_aliases(self, recipe_id: str, aliases) -> None:
        """Pekarna från gamla id till det här receptet, ersatta i sin helhet.

        Ett alias som redan pekar på ett ANNAT recept flyttas hit (`INSERT OR
        REPLACE`): källorna är sanningen, och den senaste importen vinner.
        Att aliaset råkar finnas som egen rad i `recipes` är däremot inget
        fel här - under en import ligger det gamla receptet kvar tills
        beskärningen i `bootstrap_if_empty` tagit det, och efter en
        återställd källfil ska raden vinna i `get()`. Så det avvisas inte;
        det får bara inte peka på sig självt."""
        self._connection.execute("DELETE FROM recipe_aliases WHERE recipe_id = ?", (recipe_id,))
        for alias in aliases:
            alias = str(alias or "").strip()
            if not alias or alias == recipe_id:
                raise ValueError(f"{recipe_id}: ett alias måste vara ett annat, icke-tomt id")
            self._connection.execute(
                "INSERT OR REPLACE INTO recipe_aliases (alias_id, recipe_id) VALUES (?, ?)",
                (alias, recipe_id))

    def _aliases(self, recipe_id: str) -> list[str]:
        return [row["alias_id"] for row in self._connection.execute(
            "SELECT alias_id FROM recipe_aliases WHERE recipe_id = ? ORDER BY alias_id",
            (recipe_id,))]

    # ---- reading ---------------------------------------------------------

    def _labels(self, recipe_id: str) -> dict:
        """Receptets etiketter: ETT fält plus två vyer av samma fält.

        `labels` är fältet - nyckel och namn för varje etikett, i receptets
        egen ordning. `tags` och `categories` är PROJEKTIONER av exakt samma
        lista: nycklarna respektive namnen. De bär de gamla fältnamnen därför
        att appen läser dem (`tags` filtrerar, `categories[0]` blir badgen på
        kortet) - men det finns bara ett fält under dem, och det går inte
        längre att lägga en etikett i det ena utan att den syns i det andra.
        Det var just den möjligheten som lät `Kött` och `kott` leva sida vid
        sida och halvera varje filter.

        `allergens` och `dietFlags` är egna vokabulärer som svarar på andra
        frågor, och de rörs inte."""
        labels = {"allergens": [], "dietFlags": []}
        egna = []
        for row in self._connection.execute(
                "SELECT kind, value FROM recipe_labels WHERE recipe_id = ? "
                "ORDER BY kind, position IS NULL, position, value", (recipe_id,)):
            if row["kind"] == LABELS:
                egna.append(row["value"])
            else:
                labels.setdefault(row["kind"], []).append(row["value"])
        labels[LABELS] = [{"key": key, "name": label_display(key)} for key in egna]
        labels["tags"] = egna
        labels["categories"] = [label_display(key) for key in egna]
        return labels

    def _to_dict(self, row) -> dict:
        recipe_id = row["id"]
        # P05b: varje rad bär sitt kanoniska id (services/ingredients). Det är
        # länken RecipeIngredient -> CanonicalIngredient som saknades; utan
        # den var normalizedId bara en stavningsnyckel (tomat != tomater).
        # None om ingrediensen är okänd - aldrig en gissning - och P05a:s
        # täckningsvakt gör en okänd ingrediens i banken till röd CI.
        from services.ingredients import canonical_id
        ingredients = [
            {"name": r["name"], "amount": r["amount"], "unit": r["unit"],
             "normalizedId": r["normalized_id"], "canonicalId": canonical_id(r["name"]),
             "optional": bool(r["optional"]),
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
            # Vad rätten är TILL FÖR. None betyder "ingen har klassificerat
            # den" - aldrig "kanske middag": veckoplaneringen kräver exakt
            # "middag" och släpper därför aldrig igenom en oklassad rad.
            "mealType": _row_get(row, "meal_type"),
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
            # P04b: `id` ÄR det kanoniska. `canonicalId` står bredvid så att en
            # klient som bad om ett alias kan se att svaret är ett annat id
            # utan att jämföra strängar den inte vet är alias; `aliases` är
            # de gamla id:na, så samma klient kan peka om sitt tillstånd.
            "canonicalId": recipe_id,
            "aliases": self._aliases(recipe_id),
            **self._labels(recipe_id),
        }

    def delete(self, recipe_id: str) -> bool:
        """Removes a recipe and everything hanging off it."""
        with self._connection:
            cursor = self._connection.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            for table in ("recipe_ingredients", "recipe_steps", "recipe_labels", "recipe_aliases"):
                self._connection.execute(f"DELETE FROM {table} WHERE recipe_id = ?", (recipe_id,))
        return cursor.rowcount > 0

    def id_for_slug(self, slug: str) -> str | None:
        row = self._connection.execute("SELECT id FROM recipes WHERE slug = ?", (slug,)).fetchone()
        return row["id"] if row else None

    def _row(self, recipe_id: str):
        """Raden för ett id, en slug - eller ett alias, i den ordningen.

        Ordningen är återställningsplanen: finns id:t som rad vinner raden,
        även om något alias råkar peka någon annanstans. Så kan en källfil
        som återställts efter en sammanslagning aldrig skuggas av en
        aliasrad som ligger kvar i databasen."""
        row = self._connection.execute("SELECT * FROM recipes WHERE id = ? OR slug = ?",
                                       (recipe_id, recipe_id)).fetchone()
        if row is None:
            row = self._connection.execute(
                """SELECT r.* FROM recipes r
                   JOIN recipe_aliases a ON a.recipe_id = r.id
                   WHERE a.alias_id = ?""", (recipe_id,)).fetchone()
        return row

    def get(self, recipe_id: str) -> dict | None:
        """Receptet - för sitt id, sin slug eller något av sina alias (P04b).

        Transparent, inte en omdirigering: svaret bär det kanoniska `id`,
        och den som frågade med ett gammalt id ser i `canonicalId`/`aliases`
        vad som hänt."""
        row = self._row(recipe_id)
        return self._to_dict(row) if row else None

    def canonical_id(self, recipe_id: str) -> str | None:
        """Det id ett recept HETER, för ett id/slug/alias. None om okänt."""
        row = self._row(recipe_id)
        return row["id"] if row else None

    def count(self) -> int:
        return self._connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]

    def search(self, *, tags=None, max_time=None, min_protein=None, max_kcal=None,
               query=None, meal_type=None, limit=200, offset=0) -> list[dict]:
        """Filtering happens in SQL, not by loading every recipe and sifting
        it in Python - which is the difference between 58 recipes and 5 000.

        `meal_type` är ett LIKHETSVILLKOR, inte "det här eller okänt". En rad
        utan klassificering faller därför bort ur `meal_type="middag"`, vilket
        är rätt håll att fela åt: ett recept ingen har sagt något om hamnar
        inte i någons middagsvecka."""
        where, params = [], []
        if meal_type is not None:
            where.append("meal_type = ?")
            params.append(require_meal_type(meal_type))
        # Etiketten normaliseras på väg IN i frågan (M4), inte bara på väg in
        # i databasen. Det är den halvan som gör felet omöjligt att göra om:
        # `Kött`, `kott` och `KÖTT` blir samma nyckel och hittar samma recept.
        # Förut var det en ren likhetsjämförelse, och `kott` gav 39 recept
        # medan `Kött` gav 18 - utan att något sa ifrån, för en kortare lista
        # ser ut som ett ärligt svar.
        for tag in tags or []:
            where.append(f"""id IN (SELECT recipe_id FROM recipe_labels
                            WHERE kind IN ('{LABELS}','dietFlags') AND value = ?)""")
            params.append(normalize_label_id(tag))
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
        recipes = [self._to_dict(row) for row in self._connection.execute(sql, params)]
        # IngrediensNAMNEN följer med listraderna (en batchfråga, inte N+1).
        # Fulla ingredienser med mängder är fortsatt detaljsidans sak - men
        # utan namnen kunde "Laga med det jag har" aldrig se ett enda
        # bankrecept, eftersom listprojektionen gav ingredients: [].
        if recipes:
            ids = [r["id"] for r in recipes]
            names: dict[str, list] = {}
            marks = ",".join("?" * len(ids))
            for row in self._connection.execute(
                    f"SELECT recipe_id, name FROM recipe_ingredients WHERE recipe_id IN ({marks}) ORDER BY position",
                    ids):
                names.setdefault(row["recipe_id"], []).append(row["name"])
            for recipe in recipes:
                recipe["ingredientNames"] = names.get(recipe["id"], [])
        return recipes

    def stats(self) -> dict:
        """What the bank actually contains - used by the report and by the
        admin panel, so a claim about the catalogue can be checked."""
        total = self.count()
        by_label = {}
        # Räknat per NYCKEL, redovisat under namnet. Före M4 räknades `Kött`
        # och `kott` som två etiketter i adminpanelen, vilket gjorde varje
        # siffra om katalogen till en halv siffra.
        for row in self._connection.execute(
                f"""SELECT value, COUNT(*) n FROM recipe_labels
                    WHERE kind = '{LABELS}' GROUP BY value ORDER BY n DESC"""):
            by_label[label_display(row["value"])] = row["n"]
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
        # Klassificeringen ska vara TOTAL. Går den sönder ska det synas som en
        # siffra i adminpanelen och inte upptäckas av en användare som får
        # gröt till middag, så luckan räknas här bredvid bildluckan.
        by_meal_type = {row["meal_type"]: row["n"] for row in self._connection.execute(
            """SELECT meal_type, COUNT(*) n FROM recipes
               WHERE meal_type IS NOT NULL GROUP BY meal_type ORDER BY n DESC""")}
        without_meal_type = self._connection.execute(
            "SELECT COUNT(*) FROM recipes WHERE meal_type IS NULL OR meal_type = ''").fetchone()[0]
        aliases = self._connection.execute("SELECT COUNT(*) FROM recipe_aliases").fetchone()[0]
        return {"total": total, "byLabel": by_label, "needsImage": needs_image,
                "completeNutrition": complete_nutrition,
                "byMealType": by_meal_type, "withoutMealType": without_meal_type,
                "withImage": with_image, "withLicensedImage": licensed,
                # Gamla id som fortfarande öppnar en rätt (P04b). `total`
                # räknar recept; ett alias är inget recept.
                "aliases": aliases}
