# -*- coding: utf-8 -*-
"""Measures ingredient->product matching precision, with and without category data.

    python backend/scripts/measure_matching.py --chain Willys

The point is NOT to maximise coverage. A wrong match produces a confidently
wrong price, which is worse for a user than an honest missing item - so the
headline number here is how many matches the category layer REJECTED, and
what they were.

Two things are measured:

  COVERAGE   how many ingredients get at least one candidate product. Category
             filtering can only lower this, and a drop is the honest cost of
             rejecting a wrong aisle.

  HARD-WRONG how many matched products sit in a department no cooking
             ingredient ever comes from (pet food, baby food, sweets/snacks,
             non-food). This needs no judgement call: any match there is
             objectively wrong, so it is the precision metric to trust.

Ingredients come from Matjakt's own recipe bank, not from a list invented for
this script - measuring against a vocabulary chosen to flatter the matcher
would prove nothing. Note this measures NAME matching only; the end-to-end
number including ingredient aliases is what verify_recipe_pricing.py reports.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.grocery import GroceryStore  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    NEVER_INGREDIENT_DEPARTMENTS, departments_for_category, product_matches_ingredient,
)

DB_PATH = ROOT / "backend" / "data" / "grocery.db"


def recipe_ingredients() -> list[str]:
    """Every distinct ingredient the recipe bank actually asks for.

    Reads the RECIPE DATABASE, not app.js. The recipes moved out of the UI
    file, and this script kept reading the empty array left behind - which
    made it divide by zero rather than measure anything.
    """
    from services.recipes import RecipeStore
    store = RecipeStore(ROOT / "backend" / "data" / "recipes.db")
    try:
        seen = []
        for recipe in store.search(limit=5000):
            for ingredient in recipe["ingredients"]:
                if ingredient["pantryStaple"]:
                    continue
                name = ingredient["name"]
                if name not in seen:
                    seen.append(name)
        return seen
    finally:
        store.close()


def load_products(store: GroceryStore, chain: str) -> list:
    rows = store.connection.execute(
        """
        SELECT DISTINCT p.* FROM grocery_products p
        JOIN grocery_product_external_ids e ON e.product_id = p.id
        WHERE e.chain = ?
        """,
        (chain,),
    ).fetchall()
    return [store._row_to_product(row) for row in rows]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="Willys")
    parser.add_argument("--json", help="Write the full result to this file")
    args = parser.parse_args()

    store = GroceryStore(DB_PATH)
    try:
        products = load_products(store, args.chain)
    finally:
        store.close()

    with_category = [p for p in products if p.category]
    ingredients = recipe_ingredients()

    print(f"Kedja: {args.chain}")
    print(f"Produkter i databasen: {len(products)}")
    print(f"  varav med kategori:  {len(with_category)} "
          f"({100 * len(with_category) // max(1, len(products))}%)")
    print(f"Ingredienser (ur receptbanken): {len(ingredients)}")
    print()

    report = []
    totals = dict(before_matches=0, after_matches=0, rejected=0,
                  before_covered=0, after_covered=0,
                  before_hard_wrong=0, after_hard_wrong=0)

    for ingredient in ingredients:
        before, after, rejected = [], [], []
        for product in products:
            # "Before" is name-only matching: exactly what the engine did
            # before category data existed.
            name_ok = product_matches_ingredient(product.name, ingredient, product.brand, None)
            if not name_ok:
                continue
            before.append(product)
            if product_matches_ingredient(product.name, ingredient, product.brand, product.category):
                after.append(product)
            else:
                rejected.append(product)

        def hard_wrong(items):
            return [p for p in items
                    if departments_for_category(p.category) & NEVER_INGREDIENT_DEPARTMENTS]

        before_wrong, after_wrong = hard_wrong(before), hard_wrong(after)
        totals["before_matches"] += len(before)
        totals["after_matches"] += len(after)
        totals["rejected"] += len(rejected)
        totals["before_covered"] += 1 if before else 0
        totals["after_covered"] += 1 if after else 0
        totals["before_hard_wrong"] += len(before_wrong)
        totals["after_hard_wrong"] += len(after_wrong)

        report.append({
            "ingredient": ingredient,
            "before": len(before), "after": len(after),
            "rejected": [{"name": p.name, "category": p.category} for p in rejected],
            "kept": [{"name": p.name, "category": p.category} for p in after[:8]],
        })

    count = len(ingredients)
    print("=== FÖRE (endast namnmatchning) ===")
    print(f"Ingredienser med minst en träff: {totals['before_covered']}/{count}"
          f" ({100 * totals['before_covered'] // count}%)")
    print(f"Kandidatprodukter totalt:        {totals['before_matches']}")
    print(f"Träffar i FEL avdelning:         {totals['before_hard_wrong']}")
    print()
    print("=== EFTER (namn + kategori) ===")
    print(f"Ingredienser med minst en träff: {totals['after_covered']}/{count}"
          f" ({100 * totals['after_covered'] // count}%)")
    print(f"Kandidatprodukter totalt:        {totals['after_matches']}")
    print(f"Träffar i FEL avdelning:         {totals['after_hard_wrong']}")
    print(f"Avvisade av kategorilagret:      {totals['rejected']}")
    print()

    print("=== VAD KATEGORILAGRET AVVISADE ===")
    shown = 0
    for entry in report:
        if not entry["rejected"]:
            continue
        print(f"\n{entry['ingredient']}  ({entry['before']} -> {entry['after']})")
        for item in entry["rejected"][:6]:
            print(f"   - {item['name']}   [{item['category'] or 'ingen kategori'}]")
        if len(entry["rejected"]) > 6:
            print(f"   ... och {len(entry['rejected']) - 6} till")
        shown += 1
    if not shown:
        print("(inget avvisat)")

    print()
    print("=== INGREDIENSER HELT UTAN TRÄFF (ärliga missar) ===")
    misses = [e["ingredient"] for e in report if e["after"] == 0]
    print(", ".join(misses) if misses else "(inga)")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"totals": totals, "ingredients": report}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"\nFullständigt resultat skrivet till {args.json}")


if __name__ == "__main__":
    main()
