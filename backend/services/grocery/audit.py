# -*- coding: utf-8 -*-
"""Prisauditen som funktion - samma kontroller som scripts/audit_pricing.py,
körbar mot VILKEN databas som helst: lokalt av skriptet, i produktion av
admin-endpointen. Releasegaten är grön först när produktionens siffror är
0/0/0/0/0 (gram som styck, volym som styck, estimat, otolkade paket,
kategorikonflikter)."""

from .pricing import (RecipePricingEngine, _MASS, _VOLUME, _VARIABLE_WEIGHT_RE, _fold, baking_grams,
                      convert_amount, dairy_gram_ml_equivalent)

FLAVOR_SUSPECTS = ["knäcke", "bulle", "kaka", "skorpa", "müsli", "godis",
                   "glass", "te ", "dryck", "yoghurt", "gröt", "chips"]


def run_pricing_audit(grocery_store, recipe_store, chains: list[str], servings: int = 4,
                      max_examples: int = 8) -> dict:
    from . import api as grocery_api
    engine = RecipePricingEngine(grocery_store)
    store_rows = {c: grocery_api._store_row_for(grocery_store, c) for c in chains}
    store_rows = {c: r for c, r in store_rows.items() if r is not None}
    recipes = [recipe_store.get(row["id"]) for row in recipe_store.connection.execute("SELECT id FROM recipes")]

    counts = {k: 0 for k in ("gram_som_styck", "volym_som_styck", "paket_over_10", "paket_over_50",
                             "rad_over_500", "rad_over_1000", "otolkad_paketstorlek", "estimat",
                             "kilopris_som_paketpris", "smakords_misstanke", "saknade")}
    examples: dict[str, list] = {k: [] for k in counts}
    checks = 0

    def note(kind, recipe, ing, chain, row, extra=""):
        counts[kind] += 1
        if len(examples[kind]) < max_examples:
            examples[kind].append(f"{recipe['id']} | {ing['name']} | {chain} | {(row or {}).get('productName')} {extra}".strip())

    for recipe in recipes:
        scale = servings / (recipe.get("servings") or servings)
        for ing in recipe.get("ingredients", []):
            if ing.get("pantryStaple") or ing.get("optional"):
                continue
            amount = (ing.get("amount") if ing.get("amount") is not None else 1) * scale
            unit = ing.get("unit") or "st"
            for chain, store_row in store_rows.items():
                checks += 1
                row = engine.price_item(ing["name"], amount, unit, chain, store_row["id"])
                if row is None:
                    counts["saknade"] += 1
                    continue
                folded_unit, package_unit = _fold(unit), _fold(row.get("packageUnit") or "")
                packages, total, exact = row.get("packages") or 0, row.get("totalCost"), row.get("exactPackaging", True)
                if not exact:
                    note("estimat", recipe, ing, chain, row, f"({unit}->{row.get('packageUnit')})")
                if row.get("perKg") or dairy_gram_ml_equivalent(ing["name"]) or baking_grams(ing["name"], 1, "dl") is not None:
                    pass
                elif folded_unit in _MASS and package_unit not in _MASS and exact:
                    note("gram_som_styck", recipe, ing, chain, row)
                if folded_unit in _VOLUME and package_unit not in _VOLUME and package_unit not in _MASS and exact:
                    note("volym_som_styck", recipe, ing, chain, row)
                if packages > 50:
                    note("paket_over_50", recipe, ing, chain, row, f"{packages} paket")
                elif packages > 10:
                    note("paket_over_10", recipe, ing, chain, row, f"{packages} paket")
                if total is not None and total > 1000:
                    note("rad_over_1000", recipe, ing, chain, row, f"{total} kr")
                elif total is not None and total > 500:
                    note("rad_over_500", recipe, ing, chain, row, f"{total} kr")
                if not row.get("packageAmount") and not row.get("perKg"):
                    note("otolkad_paketstorlek", recipe, ing, chain, row, f"size={row.get('packageSize')!r}")
                if any(word in _fold(row.get("productName") or "") for word in FLAVOR_SUSPECTS):
                    note("smakords_misstanke", recipe, ing, chain, row)
                # Viktvara ("ca: 850g") vars radpris fortfarande ÄR kilopriset:
                # 125 kr/kg visat som 125 kr paketet. Fel pris - gaten är röd.
                size = row.get("packageSize") or ""
                comparison, unit_cost = row.get("comparisonPrice"), row.get("unitPrice")
                pack_g = convert_amount(row.get("packageAmount") or 0, row.get("packageUnit") or "g", "g") if package_unit in _MASS else None
                if (_VARIABLE_WEIGHT_RE.match(size) and comparison and unit_cost and pack_g
                        and abs(pack_g - 1000) > 1 and abs(unit_cost - comparison) < 0.01 and not row.get("weightPriced")):
                    note("kilopris_som_paketpris", recipe, ing, chain, row, f"{unit_cost} kr = {comparison} kr/kg")

    gate = all(counts[k] == 0 for k in ("gram_som_styck", "volym_som_styck", "estimat", "otolkad_paketstorlek",
                                        "kilopris_som_paketpris"))
    return {"recept": len(recipes), "kedjor": list(store_rows), "kontroller": checks,
            "flaggor": counts, "exempel": {k: v for k, v in examples.items() if v},
            "gate": "GRÖN" if gate else "RÖD"}
