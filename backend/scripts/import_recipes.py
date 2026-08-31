# -*- coding: utf-8 -*-
"""Importerar en batch recept: validera -> bild -> licens -> spara -> prissätt.

    python backend/scripts/import_recipes.py backend/data/recipes/batch01_barn.json
    python backend/scripts/import_recipes.py --all
    python backend/scripts/import_recipes.py --all --no-images   (snabb omkörning)

Nothing is written until a recipe passes validation. A recipe that fails is
reported and skipped, not half-saved - a bank where some recipes are missing
their amounts is worse than a smaller bank where every recipe is complete.

Images are looked up ONCE, here. A recipe that gets no confident, licensed
match is still saved, marked needs_image, so the gap is findable rather than
discovered by a user.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.recipes import RecipeStore, normalize_ingredient_id  # noqa: E402
from services.recipes.images import find_image, placeholder  # noqa: E402

RECIPE_DIR = ROOT / "backend" / "data" / "recipes"
DB_PATH = ROOT / "backend" / "data" / "recipes.db"

# Units the pricing engine can convert between, plus the ones a recipe
# legitimately uses that it cannot ("msk" of tomato purée is not worth
# converting - the package maths falls back to one package and says so).
KNOWN_UNITS = {"g", "kg", "ml", "l", "dl", "msk", "tsk", "st", "krm", "knippe"}


def validate(recipe: dict, seen_ids: set, seen_names: set) -> list[str]:
    """Everything that must be true before a recipe is allowed into the bank."""
    problems = []
    for field in ("id", "name", "description", "servings", "instructions"):
        if not recipe.get(field):
            problems.append(f"saknar {field}")

    if recipe.get("id") in seen_ids:
        problems.append(f"dubblett-id: {recipe['id']}")
    name = (recipe.get("name") or "").lower()
    if name in seen_names:
        problems.append(f"dubblett-namn: {recipe.get('name')}")

    if len(recipe.get("instructions") or []) < 3:
        problems.append("för få instruktionssteg (minst 3)")

    nutrition = recipe.get("nutrition") or {}
    for key in ("kcal", "protein", "carbs", "fat"):
        if nutrition.get(key) is None:
            problems.append(f"saknar näring: {key}")
    kcal = nutrition.get("kcal") or 0
    if not 150 <= kcal <= 1400:
        problems.append(f"orimliga kalorier: {kcal}")
    # Protein, carbs and fat should roughly account for the calories. A
    # 30 % slack absorbs rounding and unlisted cooking fat; beyond that the
    # numbers were not computed from the ingredients.
    derived = (nutrition.get("protein", 0) * 4 + nutrition.get("carbs", 0) * 4
               + nutrition.get("fat", 0) * 9)
    if kcal and abs(derived - kcal) > kcal * 0.3:
        problems.append(f"näringen går inte ihop: {derived:.0f} kcal ur makros mot {kcal}")

    ingredients = recipe.get("ingredients") or []
    if len(ingredients) < 3:
        problems.append("för få ingredienser")
    for ingredient in ingredients:
        if not ingredient.get("name"):
            problems.append("ingrediens utan namn")
            continue
        if ingredient.get("pantryStaple"):
            continue
        if ingredient.get("amount") is None:
            problems.append(f"ingrediens utan mängd: {ingredient['name']}")
        unit = ingredient.get("unit")
        if unit and unit not in KNOWN_UNITS:
            problems.append(f"okänd enhet '{unit}' för {ingredient['name']}")

    if not recipe.get("tags"):
        problems.append("saknar tags")
    # A vegetarian recipe with meat in it is the kind of error that matters
    # to a person, not just to a schema.
    flags = set(recipe.get("dietFlags") or []) | set(recipe.get("tags") or [])
    if {"vegetarisk", "vegetariskt", "vegansk", "veganskt"} & flags:
        meat = [i["name"] for i in ingredients
                if normalize_ingredient_id(i["name"]) in MEAT_IDS]
        if meat:
            problems.append(f"märkt vegetariskt men innehåller {', '.join(meat)}")
    return problems


MEAT_IDS = {
    "blandfars", "kottfars", "notfars", "kycklingfile", "kycklinglarfile",
    "flaskfile", "bacon", "falukorv", "korv", "skinka", "biff", "lax",
    "laxfile", "torskfile", "torsk", "rakor", "kyckling", "flaskkarre",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="JSON-filer med recept")
    parser.add_argument("--all", action="store_true", help="Alla filer i data/recipes/")
    parser.add_argument("--no-images", action="store_true", help="Hoppa över bildsökning")
    args = parser.parse_args()

    paths = sorted(RECIPE_DIR.glob("*.json")) if args.all else [Path(f) for f in args.files]
    if not paths:
        parser.error("ange filer eller --all")

    store = RecipeStore(DB_PATH)
    try:
        # Images already in use, so the same picture is never reused - the
        # same generic photo on eight recipes reads as stock filler.
        used_images = {row["image"] for row in store.connection.execute(
            "SELECT image FROM recipes WHERE image IS NOT NULL")}
        seen_ids = {row["id"] for row in store.connection.execute("SELECT id FROM recipes")}
        seen_names = {row["name"].lower() for row in
                      store.connection.execute("SELECT name FROM recipes")}

        saved = failed = with_image = needs_image = 0
        for path in paths:
            recipes = json.loads(path.read_text(encoding="utf-8"))
            print(f"\n=== {path.name}: {len(recipes)} recept ===")
            for recipe in recipes:
                problems = validate(recipe, seen_ids - {recipe.get("id")},
                                    seen_names - {(recipe.get("name") or "").lower()})
                if problems:
                    failed += 1
                    print(f"  AVVISAD  {recipe.get('name', '?')}")
                    for problem in problems:
                        print(f"           - {problem}")
                    continue

                nutrition = recipe.pop("nutrition", {})
                recipe.update({k: nutrition.get(k) for k in ("kcal", "protein", "carbs", "fat", "fiber")})
                recipe["totalTime"] = (recipe.get("prepTime") or 0) + (recipe.get("cookTime") or 0)

                if args.no_images or recipe.get("image"):
                    image = {}
                else:
                    found = find_image(recipe, used_images)
                    if found:
                        used_images.add(found["image"])
                        with_image += 1
                        image = found
                    else:
                        needs_image += 1
                        image = placeholder(recipe)
                recipe.update({k: v for k, v in image.items() if k != "imageTitle"})

                # The migrated recipes have no instructions and no
                # descriptions. When a new, complete recipe is the same dish,
                # it SUPERSEDES the old one - but visibly, never silently.
                slug = recipe.get("slug") or normalize_ingredient_id(recipe["name"])
                recipe["slug"] = slug
                existing_id = store.id_for_slug(slug)
                if existing_id and existing_id != recipe["id"]:
                    store.delete(existing_id)
                    seen_ids.discard(existing_id)
                    print(f"  ERSATTE  {existing_id} -> {recipe['id']} (samma rätt, komplett version)")

                store.upsert_recipe(recipe)
                seen_ids.add(recipe["id"])
                seen_names.add(recipe["name"].lower())
                saved += 1
                mark = "bild" if image.get("image") else "needs_image" if image else "-"
                print(f"  OK       {recipe['name'][:46]:46} {mark}")

        stats = store.stats()
        print(f"\n{'=' * 60}")
        print(f"sparade {saved}, avvisade {failed}")
        print(f"bild hittad {with_image}, needs_image {needs_image}")
        print(f"receptbanken: {stats['total']} recept, "
              f"{stats['completeNutrition']} med komplett näring, "
              f"{stats['withLicensedImage']} med licensierad bild")
        return 1 if failed else 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
