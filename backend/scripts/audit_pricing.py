# -*- coding: utf-8 -*-
"""FULL PRISAUDIT: varje recept × ingrediens × kedja, med Adams flaggor.

    python backend/scripts/audit_pricing.py

Körs mot den lokala prisdatabasen (samma nattliga pipeline som produktionen).
Skriver en flaggrapport till stdout och detaljer till audit_flags.tsv.
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from services.grocery import api as gapi  # noqa: E402
from services.grocery.pricing import (  # noqa: E402
    RecipePricingEngine, _MASS, _VOLUME, _fold)
from services.recipes import api as rapi  # noqa: E402

FLAVOR_SUSPECTS = ["knäcke", "bulle", "kaka", "skorpa", "müsli", "godis",
                   "glass", "te ", "dryck", "yoghurt", "gröt", "chips"]


def main() -> int:
    gs = gapi.open_store()
    engine = RecipePricingEngine(gs)
    chains = {c: gapi._store_row_for(gs, c)
              for c in ("Willys", "Hemköp", "City Gross")}
    chains = {c: row for c, row in chains.items() if row is not None}

    rs = rapi.open_store()
    recipes = [rs.get(row["id"]) for row in rs.connection.execute("SELECT id FROM recipes")]

    flags = {
        "gram_som_styck": [], "volym_som_styck": [], "paket_over_10": [],
        "paket_over_50": [], "rad_over_500": [], "rad_over_1000": [],
        "kategori_konflikt": [], "smakords_misstanke": [], "otolkad_paketstorlek": [],
        "estimat": [],
    }
    rows_checked = 0
    out = open(ROOT / "audit_flags.tsv", "w", encoding="utf-8")
    out.write("recept\tingrediens\tbehov\tenhet\tkedja\tprodukt\tkategori\tpaket\tpaketenhet\tantal\texakt\tradpris\tflagga\n")

    def flag(kind, recipe, ing, chain, row, note=""):
        flags[kind].append((recipe["id"], ing["name"], chain, row.get("productName"), note))
        out.write(f"{recipe['id']}\t{ing['name']}\t{ing.get('amount')}\t{ing.get('unit')}\t{chain}\t"
                  f"{row.get('productName')}\t{(row.get('category') or '')[:60]}\t{row.get('packageAmount')}\t"
                  f"{row.get('packageUnit')}\t{row.get('packages')}\t{row.get('exactPackaging')}\t"
                  f"{row.get('totalCost')}\t{kind} {note}\n")

    for recipe in recipes:
        servings = recipe.get("servings") or 4
        scale = 4 / servings
        for ing in recipe.get("ingredients", []):
            if ing.get("pantryStaple") or ing.get("optional"):
                continue
            amount = (ing.get("amount") if ing.get("amount") is not None else 1) * scale
            unit = ing.get("unit") or "st"
            for chain, store_row in chains.items():
                rows_checked += 1
                row = engine.price_item(ing["name"], amount, unit, chain, store_row["id"])
                if row is None:
                    continue
                folded_unit = _fold(unit)
                package_unit = _fold(row.get("packageUnit") or "")
                packages = row.get("packages") or 0
                total = row.get("totalCost")
                exact = row.get("exactPackaging", True)

                if not exact:
                    flag("estimat", recipe, ing, chain, row)
                if row.get("perKg"):
                    pass  # lösvikt per kilo: exakt modell, ingen flagga
                elif folded_unit in _MASS and package_unit not in _MASS and exact:
                    flag("gram_som_styck", recipe, ing, chain, row,
                         f"behov i {unit} men paket i {row.get('packageUnit')}")
                if folded_unit in _VOLUME and package_unit not in _VOLUME \
                        and package_unit not in _MASS and exact:
                    flag("volym_som_styck", recipe, ing, chain, row,
                         f"behov i {unit} men paket i {row.get('packageUnit')}")
                if packages > 50:
                    flag("paket_over_50", recipe, ing, chain, row, f"{packages} paket")
                elif packages > 10:
                    flag("paket_over_10", recipe, ing, chain, row, f"{packages} paket")
                if total is not None and total > 1000:
                    flag("rad_over_1000", recipe, ing, chain, row, f"{total} kr")
                elif total is not None and total > 500:
                    flag("rad_over_500", recipe, ing, chain, row, f"{total} kr")
                if not row.get("packageAmount") and not row.get("perKg"):
                    flag("otolkad_paketstorlek", recipe, ing, chain, row)
                name_folded = _fold(row.get("productName") or "")
                if any(word in name_folded for word in FLAVOR_SUSPECTS):
                    flag("smakords_misstanke", recipe, ing, chain, row)

    out.close()
    print(f"\n{'='*64}")
    print(f"AUDIT: {len(recipes)} recept, {rows_checked} rad×kedja-kontroller")
    for kind, hits in flags.items():
        print(f"  {kind:<24} {len(hits)}")
        for hit in hits[:6]:
            print(f"      {hit[0][:22]} | {hit[1][:16]} | {hit[2]} | {str(hit[3])[:34]} {hit[4]}")
        if len(hits) > 6:
            print(f"      ... +{len(hits)-6} till (se audit_flags.tsv)")
    gs.close(); rs.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
