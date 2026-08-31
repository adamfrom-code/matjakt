# -*- coding: utf-8 -*-
"""Flyttar de 58 befintliga recepten till Matjakts egen receptdatabas.

    python backend/scripts/migrate_recipes.py [--db backend/data/recipes.db]

The recipes are currently spread across THREE places that have to be read
together, which is the whole reason for this migration:

  frontend/app/data/recipes.json   name, nutrition, tags, image filename
  frontend/app/app.js              RECIPE_QUANTITIES - the amounts, keyed by
                                   recipe id AND ingredient name
  assets/recipes/CREDITS.md        author, licence and source per image

An ingredient in one file, its 600 g in another, and the right to show its
picture in a third. Nothing enforced that they agreed.

WHAT THIS MIGRATION DOES NOT DO: invent content. The existing recipes have no
descriptions and no cooking instructions, so those fields come out empty
rather than filled with something plausible. A recipe you cannot cook from is
worse than one that admits it has no method yet.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.recipes import RecipeStore, normalize_ingredient_id  # noqa: E402

RECIPES_JSON = ROOT / "frontend" / "app" / "data" / "recipes.json"
APP_JS = ROOT / "frontend" / "app" / "app.js"
CREDITS = ROOT / "frontend" / "app" / "assets" / "recipes" / "CREDITS.md"

# Units the recipes use, mapped to what the pricing engine converts between.
# Left alone when already sensible - this is not a place to be clever.
UNIT_FIXES = {"st": "st", "g": "g", "kg": "kg", "ml": "ml", "l": "l", "dl": "dl"}


def read_quantities() -> dict:
    """RECIPE_QUANTITIES out of app.js: {recipe_id: {ingredient: (amount, unit)}}."""
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("const RECIPE_QUANTITIES = {")
    quantities = {}
    for line in source[start:].splitlines()[1:]:
        if line.strip().startswith("}"):
            break
        match = re.match(r'\s*([a-z0-9]+):\s*\{(.*)\},?\s*$', line)
        if not match:
            continue
        entries = {}
        for name, amount, unit in re.findall(
                r'"?([^",:{}\[\]]+)"?:\s*\[([\d.]+),\s*"([^"]+)"\]', match.group(2)):
            entries[name.strip()] = (float(amount), UNIT_FIXES.get(unit, unit))
        quantities[match.group(1)] = entries
    return quantities


def read_credits() -> dict:
    """Image rights per filename, from the credits table."""
    credits = {}
    if not CREDITS.exists():
        return credits
    for line in CREDITS.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        # | file | author | licence | source |
        if len(cells) >= 6 and cells[1].endswith(".jpg"):
            credits[cells[1]] = {"credit": cells[2], "license": cells[3], "source": cells[4]}
    return credits


def build(recipe: dict, quantities: dict, credits: dict) -> dict:
    amounts = quantities.get(recipe["id"], {})
    ingredients = []
    for name in recipe.get("ingredienser") or []:
        amount, unit = amounts.get(name, (None, None))
        ingredients.append({
            "name": name, "amount": amount, "unit": unit,
            "normalizedId": normalize_ingredient_id(name),
        })
    # "hemma" is salt, pepper, oil - real ingredients, but ones a shopping
    # list must not tell someone to buy every week. Kept as ingredients so a
    # recipe is complete, flagged so pricing can skip them.
    for name in recipe.get("hemma") or []:
        ingredients.append({
            "name": name, "amount": None, "unit": None,
            "normalizedId": normalize_ingredient_id(name), "pantryStaple": True,
        })

    filename = (recipe.get("bild") or "").rsplit("/", 1)[-1]
    rights = credits.get(filename, {})
    image = recipe.get("bild")
    # An image whose licence we cannot state is an image we have no right to
    # publish. Better no picture than an unattributed one.
    if image and not rights.get("license"):
        image = None

    categories = [recipe["typ"]] if recipe.get("typ") else []
    diet_flags = [recipe["kosttyp"]] if recipe.get("kosttyp") else []

    return {
        "id": recipe["id"],
        "slug": normalize_ingredient_id(recipe["namn"]),
        "name": recipe["namn"],
        # Not invented - see the module docstring.
        "description": None,
        "servings": recipe.get("portioner") or 4,
        "totalTime": recipe.get("tid"),
        "kcal": recipe.get("kcal"), "protein": recipe.get("protein"),
        "carbs": recipe.get("kolhydrater"), "fat": recipe.get("fett"),
        "image": image,
        "imageSource": rights.get("source"),
        "imageCredit": rights.get("credit"),
        "imageLicense": rights.get("license"),
        "imageAlt": f"{recipe['namn']} serverad på tallrik" if image else None,
        "ingredients": ingredients,
        "instructions": [],
        "categories": categories,
        "tags": recipe.get("tags") or [],
        "allergens": recipe.get("allergener") or [],
        "dietFlags": diet_flags,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "backend" / "data" / "recipes.db"))
    args = parser.parse_args()

    recipes = json.loads(RECIPES_JSON.read_text(encoding="utf-8"))
    quantities = read_quantities()
    credits = read_credits()
    print(f"läser {len(recipes)} recept, {len(quantities)} mängdtabeller, {len(credits)} bildkrediteringar")

    store = RecipeStore(Path(args.db))
    try:
        for recipe in recipes:
            store.upsert_recipe(build(recipe, quantities, credits))
        stats = store.stats()
        print(f"\nskrev {stats['total']} recept till {args.db}")
        print(f"  komplett näring: {stats['completeNutrition']}/{stats['total']}")
        print(f"  med bild:        {stats['withImage']}/{stats['total']}")
        print(f"  med licens:      {stats['withLicensedImage']}/{stats['total']}")

        # The honest gaps, stated rather than left to be discovered.
        no_amount = store.connection.execute(
            """SELECT COUNT(*) FROM recipe_ingredients
               WHERE amount IS NULL AND pantry_staple = 0""").fetchone()[0]
        total_ing = store.connection.execute(
            "SELECT COUNT(*) FROM recipe_ingredients WHERE pantry_staple = 0").fetchone()[0]
        no_steps = store.connection.execute(
            """SELECT COUNT(*) FROM recipes WHERE id NOT IN
               (SELECT DISTINCT recipe_id FROM recipe_steps)""").fetchone()[0]
        print(f"\nLUCKOR ATT FYLLA:")
        print(f"  ingredienser utan mängd: {no_amount}/{total_ing}")
        print(f"  recept utan instruktioner: {no_steps}/{stats['total']}")
        print(f"  recept utan beskrivning: {stats['total']}/{stats['total']}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
