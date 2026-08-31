# -*- coding: utf-8 -*-
"""Tests for Matjakts egen receptdatabas.

The invariants worth protecting are the ones that used to be violated by the
old shape: an ingredient and its amount living in different files, and a
recipe carrying an image nobody could prove we were allowed to publish.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery.pricing import _fold  # noqa: E402
from services.recipes import RecipeStore, normalize_ingredient_id  # noqa: E402

RECIPE = {
    "id": "kycklinggryta", "name": "Kycklinggryta med ris", "servings": 4,
    "totalTime": 30, "kcal": 580, "protein": 36, "carbs": 52, "fat": 25,
    "image": "assets/recipes/kycklinggryta.jpg",
    "imageSource": "https://commons.wikimedia.org/wiki/File:Creamy_Chicken_Curry.jpg",
    "imageCredit": "Shrabee", "imageLicense": "CC BY-SA 4.0",
    "imageAlt": "Kycklinggryta med ris serverad på tallrik",
    "ingredients": [
        {"name": "Kycklinglårfilé", "amount": 600, "unit": "g"},
        {"name": "Ris", "amount": 250, "unit": "g"},
        {"name": "Salt", "amount": None, "unit": None, "pantryStaple": True},
    ],
    "instructions": ["Bryn kycklingen.", "Koka riset."],
    "categories": ["Familjefavorit"], "tags": ["barn", "mealprep"],
    "allergens": [], "dietFlags": ["blandkost"],
}


class RecipeStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = RecipeStore(Path(self._tmp.name) / "recipes.db")
        self.addCleanup(self.store.close)
        self.store.upsert_recipe(RECIPE)

    def test_round_trips_a_recipe(self):
        got = self.store.get("kycklinggryta")
        self.assertEqual(got["name"], "Kycklinggryta med ris")
        self.assertEqual(got["servings"], 4)
        self.assertEqual(got["nutrition"]["protein"], 36)
        self.assertEqual(got["instructions"], ["Bryn kycklingen.", "Koka riset."])

    def test_ingredient_keeps_its_amount(self):
        """The whole reason this database exists: the amount used to live in
        a different file, keyed by name, and could drift from the ingredient
        it belonged to."""
        chicken = self.store.get("kycklinggryta")["ingredients"][0]
        self.assertEqual((chicken["name"], chicken["amount"], chicken["unit"]),
                         ("Kycklinglårfilé", 600, "g"))

    def test_ingredient_order_is_preserved(self):
        names = [i["name"] for i in self.store.get("kycklinggryta")["ingredients"]]
        self.assertEqual(names, ["Kycklinglårfilé", "Ris", "Salt"])

    def test_pantry_staples_are_flagged_not_dropped(self):
        """Salt is a real ingredient, but a shopping list must not tell
        someone to buy it every week."""
        salt = self.store.get("kycklinggryta")["ingredients"][2]
        self.assertTrue(salt["pantryStaple"])

    def test_findable_by_slug(self):
        self.assertIsNotNone(self.store.get("kycklinggryta-med-ris"))

    def test_upsert_replaces_rather_than_accumulates(self):
        """A recipe edited to have fewer ingredients must not keep the old
        ones."""
        self.store.upsert_recipe({**RECIPE, "ingredients": [
            {"name": "Ris", "amount": 250, "unit": "g"}]})
        self.assertEqual(len(self.store.get("kycklinggryta")["ingredients"]), 1)
        self.assertEqual(self.store.count(), 1)

    def test_created_at_survives_an_update(self):
        before = self.store.get("kycklinggryta")["createdAt"]
        self.store.upsert_recipe({**RECIPE, "name": "Nytt namn"})
        self.assertEqual(self.store.get("kycklinggryta")["createdAt"], before)


class IngredientIdTest(unittest.TestCase):
    def test_id_is_derived_from_the_same_fold_the_pricing_engine_uses(self):
        """If these drift apart, recipes stop matching products for reasons
        nobody can see."""
        for name in ["Kycklinglårfilé", "Crème fraiche", "Röda linser",
                     "Lök & vitlök", "Ägg", "Fryst torsk"]:
            slugified = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", _fold(name))).strip("-")
            self.assertEqual(normalize_ingredient_id(name), slugified, name)

    def test_accents_and_case_collapse_to_one_id(self):
        self.assertEqual(normalize_ingredient_id("Kycklingfilé"),
                         normalize_ingredient_id("kycklingfile"))

    def test_stored_automatically_when_not_given(self):
        store = RecipeStore(Path(tempfile.mkdtemp()) / "r.db")
        self.addCleanup(store.close)
        store.upsert_recipe(RECIPE)
        self.assertEqual(store.get("kycklinggryta")["ingredients"][0]["normalizedId"],
                         "kycklinglarfile")


class ImageRightsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = RecipeStore(Path(self._tmp.name) / "recipes.db")
        self.addCleanup(self.store.close)

    def test_image_carries_its_rights(self):
        self.store.upsert_recipe(RECIPE)
        got = self.store.get("kycklinggryta")
        self.assertEqual(got["imageLicense"], "CC BY-SA 4.0")
        self.assertEqual(got["imageCredit"], "Shrabee")
        self.assertTrue(got["imageSource"].startswith("https://"))
        self.assertTrue(got["imageAlt"])

    def test_stats_count_licensed_images_separately(self):
        """An image without a stated licence is one we cannot prove we may
        publish - it must not be counted as if we could."""
        self.store.upsert_recipe(RECIPE)
        self.store.upsert_recipe({**RECIPE, "id": "utan", "name": "Utan licens",
                                  "slug": "utan", "imageLicense": None})
        stats = self.store.stats()
        self.assertEqual(stats["withImage"], 2)
        self.assertEqual(stats["withLicensedImage"], 1)

    def test_nothing_here_fetches_an_image(self):
        """The reference is data. A recipe opening must never trigger an
        image search."""
        source = (Path(__file__).resolve().parents[1] /
                  "services" / "recipes" / "store.py").read_text(encoding="utf-8")
        for forbidden in ("urlopen", "requests.", "fetch(", "http://", "https://"):
            self.assertNotIn(forbidden, source, f"receptlagret gör nätverksanrop: {forbidden}")


class SearchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = RecipeStore(Path(self._tmp.name) / "recipes.db")
        self.addCleanup(self.store.close)
        self.store.upsert_recipe(RECIPE)
        self.store.upsert_recipe({**RECIPE, "id": "snabb", "slug": "snabb",
                                  "name": "Snabb pasta", "totalTime": 15,
                                  "protein": 12, "tags": ["snabbt", "vegetariskt"]})

    def test_filters_by_tag(self):
        self.assertEqual([r["id"] for r in self.store.search(tags=["barn"])], ["kycklinggryta"])

    def test_filters_by_time(self):
        self.assertEqual([r["id"] for r in self.store.search(max_time=20)], ["snabb"])

    def test_filters_by_protein(self):
        self.assertEqual([r["id"] for r in self.store.search(min_protein=30)], ["kycklinggryta"])

    def test_combines_filters(self):
        self.assertEqual(self.store.search(tags=["snabbt"], min_protein=30), [])

    def test_searches_by_name(self):
        self.assertEqual([r["id"] for r in self.store.search(query="pasta")], ["snabb"])

    def test_paginates(self):
        self.assertEqual(len(self.store.search(limit=1)), 1)
        first = self.store.search(limit=1)[0]["id"]
        self.assertNotEqual(self.store.search(limit=1, offset=1)[0]["id"], first)


if __name__ == "__main__":
    unittest.main()


class RecipePriceColumns(unittest.TestCase):
    """The price columns hold what the pricing RUN computed - a real portion
    cost with its chain and coverage, or the explicit verdict that no full
    price exists. Both must round-trip, and 'no price' must overwrite a stale
    success."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.store = RecipeStore(Path(self.dir.name) / "recipes.db")
        # LIFO: close must run BEFORE the directory removal, or Windows
        # refuses to delete a database file that is still open.
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(self.store.close)
        self.store.upsert_recipe({
            "id": "testgryta", "slug": "testgryta", "name": "Testgryta",
            "servings": 4, "totalTime": 30,
            "ingredients": [{"name": "Pasta", "amount": 400, "unit": "g"}],
            "instructions": ["Koka."],
        })

    def test_price_round_trips(self):
        self.store.set_price("testgryta", price_per_portion=23.5,
                             chain="Willys", covered=5, total=5)
        recipe = self.store.get("testgryta")
        self.assertEqual(recipe["pricePerPortion"], 23.5)
        self.assertEqual(recipe["priceChain"], "Willys")
        self.assertIsNotNone(recipe["pricedAt"])

    def test_no_price_overwrites_a_stale_success(self):
        """A recipe whose ingredient lost its product match must not keep
        advertising last month's price."""
        self.store.set_price("testgryta", price_per_portion=23.5,
                             chain="Willys", covered=5, total=5)
        self.store.set_price("testgryta", price_per_portion=None,
                             chain=None, covered=3, total=5)
        recipe = self.store.get("testgryta")
        self.assertIsNone(recipe["pricePerPortion"])

    def test_migration_adds_columns_to_an_existing_database(self):
        """Production's recipes.db predates the price columns and must not be
        rebuilt (a rebuild would lose the backfilled images)."""
        import sqlite3, tempfile
        with tempfile.TemporaryDirectory() as workdir:
            path = Path(workdir) / "old.db"
            connection = sqlite3.connect(path)
            # Ett schema utan priskolumnerna, som produktionens.
            connection.executescript(
                "CREATE TABLE recipes (id TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, "
                "name TEXT NOT NULL, description TEXT, servings INTEGER NOT NULL DEFAULT 4, "
                "prep_time INTEGER, cook_time INTEGER, total_time INTEGER, difficulty TEXT, "
                "kcal REAL, protein REAL, carbs REAL, fat REAL, fiber REAL, image TEXT, "
                "image_source TEXT, image_source_url TEXT, image_credit TEXT, "
                "image_license TEXT, image_alt TEXT, image_status TEXT, "
                "created_at REAL NOT NULL, updated_at REAL NOT NULL);")
            connection.execute(
                "INSERT INTO recipes (id, slug, name, created_at, updated_at) "
                "VALUES ('gammal', 'gammal', 'Gammal', 1, 1)")
            connection.commit()
            connection.close()
            migrated = RecipeStore(path)
            try:
                recipe = migrated.get("gammal")
                self.assertIsNone(recipe["pricePerPortion"])
                migrated.set_price("gammal", price_per_portion=12.0,
                                   chain="Willys", covered=1, total=1)
                self.assertEqual(migrated.get("gammal")["pricePerPortion"], 12.0)
            finally:
                migrated.close()
