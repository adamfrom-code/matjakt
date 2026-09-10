# -*- coding: utf-8 -*-
"""C3: vitlök prissattes som knoppar, inte klyftor.

Receptbanken skrev "Vitlök 3 st" och menade tre KLYFTOR. Prismotorns
styckvikttabell läste det som tre hela knoppar: 3 × 70 = 210 g. En vecka med
fem vitlöksrecept blev ~840 g vitlök - cirka 125 kr på en veckobudget som
skulle varit 15.

Testerna låser tre saker:
  1. migreringen ändrar exakt de rader den ska och inget annat,
  2. den är körbar om (idempotent) - den ska gå att köra i produktion,
  3. det migrerade receptet prissätts under 5 kr på vitlöksraden.
"""

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from services.grocery import GroceryStore, RawProduct  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    KLYFT_VIKT_G, RecipePricingEngine, klyft_vikt_for, styck_vikt_for)
from services.recipes import RecipeStore  # noqa: E402

import migrate_vitloksklyftor as migration  # noqa: E402


# Så här såg receptbanken ut före migreringen: 33 recept med "2 st", 25 med
# "3 st", 9 med "1 st" och 3 med "4 st" vitlök. Fixturen bär ett av varje
# plus de rader som INTE får röras.
FIXTURE_RECIPES = [
    {"id": "pastasas", "name": "Pastasås med vitlök", "servings": 4, "totalTime": 30,
     "ingredients": [
         {"name": "Krossade tomater", "amount": 400, "unit": "g"},
         {"name": "Vitlök", "amount": 3, "unit": "st"},
     ],
     "instructions": ["Fräs.", "Koka.", "Servera."],
     "categories": [], "tags": ["vardag"], "allergens": [], "dietFlags": []},
    {"id": "gryta", "name": "Gryta med vitlök", "servings": 4, "totalTime": 40,
     "ingredients": [
         {"name": "Vitlök", "amount": 2, "unit": "st"},
         # Rör inte: gram-raden är en annan vara med en annan mängd.
         {"name": "Lök & vitlök", "amount": 150, "unit": "g"},
         # Rör inte: skafferirad utan enhet.
         {"name": "Vitlök", "amount": None, "unit": None, "pantryStaple": True},
     ],
     "instructions": ["Fräs.", "Koka.", "Servera."],
     "categories": [], "tags": ["vardag"], "allergens": [], "dietFlags": []},
]


def _build_fixture(path: Path) -> None:
    store = RecipeStore(path)
    try:
        for recipe in FIXTURE_RECIPES:
            store.upsert_recipe(recipe)
    finally:
        store.close()


def _garlic_rows(path: Path) -> list[tuple]:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT name, amount, unit FROM recipe_ingredients ORDER BY recipe_id, position"
        ).fetchall()
        return [(row["name"], row["amount"], row["unit"]) for row in rows]
    finally:
        connection.close()


class CloveWeightTest(unittest.TestCase):
    def test_a_clove_is_five_grams_and_a_bulb_is_still_seventy(self):
        """Knoppen är kvar: "1 st vitlök" ÄR en knopp - det är varan man
        lyfter ur hyllan. Klyftan är ett eget mått."""
        self.assertEqual(klyft_vikt_for("Vitlök"), 5)
        self.assertEqual(klyft_vikt_for("vitlok"), 5)
        self.assertEqual(styck_vikt_for("Vitlök"), 70)

    def test_an_ingredient_without_a_clove_weight_has_none(self):
        self.assertIsNone(klyft_vikt_for("Potatis"))
        self.assertEqual(set(KLYFT_VIKT_G), {"vitlok"})


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "recipes.db"
        _build_fixture(self.db)

    def test_only_garlic_in_pieces_is_rewritten(self):
        result = migration.migrate(self.db)
        self.assertEqual(result["changed"], 2)
        self.assertEqual(result["recipes"], 2)
        self.assertEqual(_garlic_rows(self.db), [
            ("Vitlök", 2.0, "klyfta"),
            ("Lök & vitlök", 150.0, "g"),
            ("Vitlök", None, None),
            ("Krossade tomater", 400.0, "g"),
            ("Vitlök", 3.0, "klyfta"),
        ])

    def test_the_amount_is_untouched(self):
        """"3 st" blir "3 klyftor", inte "15 g" - klyftan är måttet receptet
        menar, och motorn väger om den."""
        migration.migrate(self.db)
        connection = sqlite3.connect(str(self.db))
        try:
            amounts = {row[0] for row in connection.execute(
                "SELECT amount FROM recipe_ingredients WHERE unit = 'klyfta'")}
        finally:
            connection.close()
        self.assertEqual(amounts, {2.0, 3.0})

    def test_it_is_idempotent(self):
        """Måste gå att köra om i produktion utan att göra något andra
        gången."""
        first = migration.migrate(self.db)
        second = migration.migrate(self.db)
        self.assertEqual(first["changed"], 2)
        self.assertEqual(second, {"found": 0, "changed": 0, "recipes": 0})

    def test_dry_run_writes_nothing(self):
        before = _garlic_rows(self.db)
        result = migration.migrate(self.db, dry_run=True)
        self.assertEqual((result["found"], result["changed"]), (2, 0))
        self.assertEqual(_garlic_rows(self.db), before)

    def test_a_copy_of_the_real_bank_is_never_touched_directly(self):
        """Fixturen är en KOPIA. Testet visar mönstret: migreringen körs mot
        en fil i tempkatalogen, aldrig mot data/recipes.db (data_guard)."""
        copy = Path(self._tmp.name) / "kopia.db"
        shutil.copy(self.db, copy)
        migration.migrate(copy)
        self.assertEqual([r[2] for r in _garlic_rows(copy) if r[0] == "Vitlök" and r[1]],
                         ["klyfta", "klyfta"])


def raw(name, *, quantity=None, unit=None, size=None):
    return RawProduct(chain="Willys", external_product_id=name, name=name,
                      store_id="1", store_name="Test", gtin=None, brand=None,
                      quantity=quantity, unit=unit, size=size)


class ClovePricingTest(unittest.TestCase):
    """Acceptanskriteriet: ett recept med "vitlök 3 st" ska kosta under 5 kr
    på den raden - inte 13,50 för tre hela knoppar."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.grocery = GroceryStore(Path(self._tmp.name) / "grocery.db")
        self.addCleanup(self.grocery.close)
        self.store = self.grocery.upsert_store(chain="Willys", external_store_id="2132",
                                               name="Willys Test")
        self.engine = RecipePricingEngine(self.grocery)

    def _add(self, name, price, quantity, unit):
        product = self.grocery.find_or_create_product(
            raw(name, quantity=quantity, unit=unit, size=f"{quantity}{unit}"))
        self.grocery.upsert_current_price(product_id=product.id, store_id=self.store.id,
                                          regular_price=price)
        return product

    def _price_recipe_garlic_row(self):
        """Bygger receptet som banken har det, migrerar, prissätter raden."""
        recipes_db = Path(self._tmp.name) / "recipes.db"
        _build_fixture(recipes_db)
        migration.migrate(recipes_db)
        store = RecipeStore(recipes_db)
        try:
            garlic = [ing for ing in store.get("pastasas")["ingredients"]
                      if ing["name"] == "Vitlök"][0]
        finally:
            store.close()
        result = self.engine.price_list(
            [{"name": garlic["name"], "amount": garlic["amount"], "unit": garlic["unit"]}],
            "Willys", self.store.id)
        self.assertEqual(len(result["matchedItems"]), 1, result)
        return result["matchedItems"][0]

    def test_three_cloves_cost_less_than_five_kronor(self):
        """En knopp på 70 g för 4,50 kr. Tre klyftor = 15 g = EN knopp =
        4,50 kr. Före C3: 3 × 70 g = 210 g = TRE knoppar = 13,50 kr."""
        self._add("Vitlök Klass 1", 4.50, 70, "g")
        row = self._price_recipe_garlic_row()
        self.assertTrue(row["exactPackaging"], "raden ska fortfarande vara säker")
        self.assertEqual(row["packages"], 1)
        self.assertLess(row["totalCost"], 5.0)

    def test_a_whole_bulb_recipe_still_buys_a_whole_bulb(self):
        """Motpolen: "1 st vitlök" är fortfarande en hel knopp på 70 g."""
        self._add("Vitlök Klass 1", 4.50, 70, "g")
        result = self.engine.price_list(
            [{"name": "Vitlök", "amount": 1, "unit": "st"}], "Willys", self.store.id)
        item = result["matchedItems"][0]
        self.assertEqual(item["packages"], 1)
        self.assertEqual(item["totalCost"], 4.50)

    def test_cloves_against_a_piece_priced_product_buy_one_package(self):
        """Säljs vitlöken i styck ("3-pack") räknas klyftorna om till
        knoppar - tre klyftor är 0,21 knopp, alltså EN förpackning."""
        self._add("Vitlök 3-pack", 15.0, 3, "st")
        row = self._price_recipe_garlic_row()
        self.assertEqual(row["packages"], 1)
        self.assertEqual(row["totalCost"], 15.0)

    def test_cloves_without_a_usable_package_stay_uncertain(self):
        """Fail closed: går klyftorna inte att räkna om mot förpackningen
        blir raden osäker, inte gissad."""
        self._add("Vitlökssås", 25.0, 500, "ml")
        result = self.engine.price_list(
            [{"name": "Vitlök", "amount": 3, "unit": "klyfta"}], "Willys", self.store.id)
        if result["matchedItems"]:
            self.assertFalse(result["matchedItems"][0]["exactPackaging"])
            self.assertIsNone(result["matchedItems"][0]["totalCost"])
        else:
            self.assertEqual(len(result["missingItems"]), 1)


if __name__ == "__main__":
    unittest.main()
