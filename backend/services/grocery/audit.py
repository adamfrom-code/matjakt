# -*- coding: utf-8 -*-
"""Prisauditen som funktion - samma kontroller som scripts/audit_pricing.py,
körbar mot VILKEN databas som helst: lokalt av skriptet, i produktion av
admin-endpointen. Releasegaten är grön först när produktionens siffror är
0/0/0/0/0 (gram som styck, volym som styck, estimat, otolkade paket,
kategorikonflikter)."""

from .pricing import (UNREASONABLE_PACKAGE_COUNT, UNREASONABLE_ROW_COST, RecipePricingEngine,
                      _MASS, _VOLUME, _exclusion_hit, _fold, _words, baking_grams,
                      dairy_gram_ml_equivalent, kilo_price_as_pack_price)

# SMAKSORD: produktnamn som ser ut som en smaksatt eller söt VARIANT av
# råvaran i stället för råvaran själv - "Kanel" prissatt mot kanelbullar,
# "Havregryn" mot färdig gröt.
#
# Orden bär svenska sammansättningar (kanelBULLE, havreGRÖT, chokladKAKA), så
# matchningen måste gå på ORDGRÄNS: motorns egen _exclusion_hit. Den var förut
# `any(word in namnet)` - ren delsträngsmatchning - och det gav 75 av 114
# flaggor i produktionsauditen på en enda falsk träff: "te " ryms i "penne
# rigaTE Pasta". Exakt den bugg motorn själv övergav när _exclusion_hit
# skrevs ("läsk" inuti "fläskfilé").
FLAVOR_SUSPECTS = ["knäcke", "bulle", "kaka", "skorpa", "müsli", "godis",
                   "glass", "te", "dryck", "yoghurt", "gröt", "chips"]

# Ordgränsen räcker ändå inte för "te". Två bokstäver kan inte bära ett
# sammansättningsled: suffixregeln säger sant om rigaTE, latTE och
# arrabiaTE, prefixregeln om TEquila. Ett så kort ord flaggas därför bara
# som HELT ORD - "Grönt Te" och "Earl Grey Te" fångas fortfarande, medan
# "Kanelte" slipper undan. Det är rätt byte: flaggan är en VARNING som
# ingen ska behöva sålla i, och 114 larm som ingen orkar läsa döljer det
# enda riktiga.
FLAVOR_MIN_COMPOUND_LENGTH = 3

_FOLDED_FLAVOR_SUSPECTS = [_fold(word) for word in FLAVOR_SUSPECTS]


def flavor_suspect(product_name: str) -> bool:
    """Om produktnamnet ser ut som en smaksatt variant snarare än råvaran."""
    folded = _fold(product_name)
    if not folded:
        return False
    words = _words(product_name)
    return any(term in words if len(term) < FLAVOR_MIN_COMPOUND_LENGTH
               else _exclusion_hit(folded, words, term)
               for term in _FOLDED_FLAVOR_SUSPECTS)


# kilo_price_as_pack_price BODDE här. Den flyttade till pricing.py (C8) så
# att motorn dömer efter samma regel som auditen i stället för att auditen
# ensam vet vad som är fel - en orimlig rad blir numera osäker i
# price_item() i stället för att prissättas som säker och dyr. Namnet står
# kvar i den här modulens yta för allt som importerar det härifrån.
__all__ = ["FLAVOR_SUSPECTS", "flavor_suspect", "kilo_price_as_pack_price",
           "run_pricing_audit"]


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
    # VILKA ingredienser som är osäkra - inte vilka produkter. Namn och enhet
    # står redan i den publika receptkällan, så nedbrytningen får ligga i
    # /api/health; produktnamnen i examples gör det inte och stannar hos
    # admin-vägen. Utan den här är "estimat: 30" omöjlig att åtgärda för
    # någon som saknar admin-token: siffran säger att något är fel men inte
    # vad, och en flagga man inte kan följa upp blir en flagga man slutar
    # tro på.
    estimat_per_ingrediens: dict[str, int] = {}
    checks = 0
    # Per kedja: en hel kedja utan priser får inte försvinna i totalen.
    per_chain = {c: {"kontroller": 0, "saknade": 0} for c in store_rows}

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
                per_chain[chain]["kontroller"] += 1
                row = engine.price_item(ing["name"], amount, unit, chain, store_row["id"])
                if row is None:
                    counts["saknade"] += 1
                    per_chain[chain]["saknade"] += 1
                    continue
                folded_unit, package_unit = _fold(unit), _fold(row.get("packageUnit") or "")
                packages, total, exact = row.get("packages") or 0, row.get("totalCost"), row.get("exactPackaging", True)
                if not exact:
                    note("estimat", recipe, ing, chain, row, f"({unit}->{row.get('packageUnit')})")
                    nyckel = f"{ing['name']} ({unit})"
                    estimat_per_ingrediens[nyckel] = estimat_per_ingrediens.get(nyckel, 0) + 1
                if row.get("perKg") or dairy_gram_ml_equivalent(ing["name"]) or baking_grams(ing["name"], 1, "dl") is not None:
                    pass
                elif folded_unit in _MASS and package_unit not in _MASS and exact:
                    note("gram_som_styck", recipe, ing, chain, row)
                if folded_unit in _VOLUME and package_unit not in _VOLUME and package_unit not in _MASS and exact:
                    note("volym_som_styck", recipe, ing, chain, row)
                # Gränserna är motorns (UNREASONABLE_*) och inte auditens egna
                # tal: rimlighetsspärren i price_item() dömer efter samma
                # siffra, och två kopior av "vad som är orimligt" hade genast
                # börjat glida isär.
                if packages > 50:
                    note("paket_over_50", recipe, ing, chain, row, f"{packages} paket")
                elif packages > UNREASONABLE_PACKAGE_COUNT:
                    note("paket_over_10", recipe, ing, chain, row, f"{packages} paket")
                if total is not None and total > 1000:
                    note("rad_over_1000", recipe, ing, chain, row, f"{total} kr")
                elif total is not None and total > UNREASONABLE_ROW_COST:
                    note("rad_over_500", recipe, ing, chain, row, f"{total} kr")
                if not row.get("packageAmount") and not row.get("perKg"):
                    note("otolkad_paketstorlek", recipe, ing, chain, row, f"size={row.get('packageSize')!r}")
                if flavor_suspect(row.get("productName") or ""):
                    note("smakords_misstanke", recipe, ing, chain, row)
                # Viktvara ("ca: 850g") vars PAKETPRIS fortfarande är kilopriset:
                # 125 kr/kg visat som 125 kr paketet. Fel pris - gaten är röd.
                pack_cost = kilo_price_as_pack_price(row)
                if pack_cost is not None:
                    note("kilopris_som_paketpris", recipe, ing, chain, row,
                         f"{pack_cost} kr/paket = {row.get('comparisonPrice')} kr/kg")

    gate = all(counts[k] == 0 for k in ("gram_som_styck", "volym_som_styck", "estimat", "otolkad_paketstorlek",
                                        "kilopris_som_paketpris"))
    return {"recept": len(recipes), "kedjor": list(store_rows), "kontroller": checks,
            "perKedja": per_chain,
            "flaggor": counts, "exempel": {k: v for k, v in examples.items() if v},
            # Störst först, taket finns för att health ska ha en övre storlek
            # även den dag något går riktigt fel och tusen rader blir osäkra.
            "estimatPerIngrediens": dict(sorted(estimat_per_ingrediens.items(),
                                                key=lambda kv: (-kv[1], kv[0]))[:20]),
            "gate": "GRÖN" if gate else "RÖD"}
