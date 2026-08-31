# -*- coding: utf-8 -*-
"""Bevisar kedjan recept -> ingrediens -> produkt -> förpackning -> kassakostnad.

    python backend/scripts/verify_recipe_pricing.py [--chain Willys] [--limit 10]

The recipe bank is only worth having if the pricing engine can actually use
it. This walks recipes straight out of recipes.db, prices each one against
real products in grocery.db, and reports coverage per recipe - so "the
recipes are structured correctly" is a measurement rather than a claim.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.grocery import api as grocery_api  # noqa: E402
from services.recipes import RecipeStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="Willys")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--all", action="store_true", help="Mät alla recept, visa bara summering")
    args = parser.parse_args()

    store = RecipeStore(ROOT / "backend" / "data" / "recipes.db")
    try:
        recipes = store.search(limit=1000)
    finally:
        store.close()

    grocery = grocery_api.open_store()
    try:
        from services.grocery.pricing import RecipePricingEngine
        engine = RecipePricingEngine(grocery)
        store_row = grocery_api._store_row_for(grocery, args.chain)
        if store_row is None:
            print(f"Ingen butiksdata för {args.chain}")
            return 1

        totals = {"priced": 0, "matched": 0, "ingredients": 0}
        shown = 0
        for recipe in recipes:
            # Pantry staples are real ingredients but nobody buys salt weekly.
            items = [{"name": i["name"], "amount": i["amount"] or 1, "unit": i["unit"] or "st"}
                     for i in recipe["ingredients"] if not i["pantryStaple"]]
            if not items:
                continue
            result = engine.price_list(items, args.chain, store_row["id"])
            totals["ingredients"] += result["totalItems"]
            totals["matched"] += result["realPriceItems"]
            if result["realPriceItems"]:
                totals["priced"] += 1

            if not args.all and shown < args.limit:
                shown += 1
                coverage = result["coveragePercent"]
                print(f"\n{shown}. {recipe['name']}  —  {result['totalCheckoutCost']} kr "
                      f"({result['realPriceItems']}/{result['totalItems']} varor, {coverage}%)")
                for match in result["matchedItems"][:4]:
                    print(f"     {match['name']:18} -> {match['productName'][:36]:36} "
                          f"{match['packages']} x {match['packageSize'] or '?':>9} "
                          f"= {match['totalCost']:>7} kr")
                for missing in result["missingItems"][:3]:
                    print(f"     {missing['name']:18} -> ingen produkt matchad")
    finally:
        grocery.close()

    count = len(recipes)
    print(f"\n{'=' * 62}")
    print(f"Kedja: {args.chain}")
    print(f"Recept i databasen:                 {count}")
    print(f"Recept som går att prissätta:       {totals['priced']}/{count} "
          f"({100 * totals['priced'] // max(1, count)}%)")
    print(f"Ingredienser totalt (ej skafferi):  {totals['ingredients']}")
    print(f"Ingredienser matchade mot produkt:  {totals['matched']} "
          f"({100 * totals['matched'] // max(1, totals['ingredients'])}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
