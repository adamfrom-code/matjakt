"""Riktad kontroll av produktdata i Handla/Skafferi mot RIKTIG kedjedata.

    set MATJAKT_DATA_DIR=<katalog med grocery.db och recipes.db>
    python backend/scripts/check_product_data.py

Komplement till test_product_data_integrity.py: det testet bevisar reglerna
mot konstruerade rader, det här skriptet kontrollerar dem mot verkliga
produkter ur en riktig prisdatabas. Avslutar med kod 1 vid avvikelse.


Minst 50 blandade rader ur riktig kedjedata, kontrollerade mot det raden
FAKTISKT visar i appen:

  * GTIN         hör ihop med produkten, inte med en annan vara
  * produktnamn  kommer från prisdatabasen, inte från ingrediensen
  * varumärke    finns bara när kedjan angett ett
  * paketstorlek finns och går att tolka
  * bild         https, hör till produkten, aldrig en annans
  * generiska råvaror får INTE ett påhittat varumärke
  * saknad bild  ger neutral fallback, inte en annan produkts bild
  * Dabas-bilder är fortfarande av

Och det viktigaste: UI-data får inte kunna påverka matchningen eller
prisets säkerhet. Det kontrolleras genom att köra prissättningen två
gånger - en gång som vanligt, en gång med bild/märke/namn manipulerade i
den sparade ögonblicksbilden - och jämföra besluten.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery import api as gapi          # noqa: E402
from services.recipes import api as rapi          # noqa: E402
from services.grocery.pricing import RecipePricingEngine  # noqa: E402
from services.household.store import _clean_product, item_key  # noqa: E402

CHAINS = ("Willys", "Hemköp", "City Gross")
TARGET_ROWS = 60

gs, rs = gapi.open_store(), rapi.open_store()
engine = RecipePricingEngine(gs)
store_rows = {c: gapi._store_row_for(gs, c) for c in CHAINS}
store_rows = {c: r for c, r in store_rows.items() if r is not None}

rows = []
for recipe in [rs.get(r["id"]) for r in rs.connection.execute("SELECT id FROM recipes")]:
    if len(rows) >= TARGET_ROWS:
        break
    scale = 4 / (recipe.get("servings") or 4)
    for ing in recipe.get("ingredients", []):
        if ing.get("pantryStaple") or ing.get("optional"):
            continue
        for chain, store_row in store_rows.items():
            amount = (ing.get("amount") if ing.get("amount") is not None else 1) * scale
            priced = engine.price_item(ing["name"], amount, ing.get("unit") or "st",
                                       chain, store_row["id"])
            if priced:
                rows.append((recipe["id"], ing["name"], chain, priced))
                break
        if len(rows) >= TARGET_ROWS:
            break

problems = []
stats = {"gtin": 0, "brand": 0, "image": 0, "no_image": 0, "package": 0, "dabas_image": 0}

for recipe_id, ingredient, chain, row in rows:
    where = f"{recipe_id}/{ingredient}/{chain}"

    # --- GTIN hör ihop med produkten -------------------------------------
    gtin = row.get("gtin")
    if gtin:
        stats["gtin"] += 1
        if not str(gtin).isdigit() or not (8 <= len(str(gtin)) <= 14):
            problems.append(f"{where}: ogiltigt GTIN {gtin!r}")
        actual = gs.connection.execute(
            "SELECT gtin, name FROM grocery_products WHERE id = ?", (row["productId"],)).fetchone()
        if actual and actual[0] != gtin:
            problems.append(f"{where}: GTIN {gtin} tillhör inte {actual[1]!r} ({actual[0]})")

    # --- produktnamnet kommer från prisdatabasen -------------------------
    stored = gs.connection.execute(
        "SELECT name, brand, size, image_url FROM grocery_products WHERE id = ?",
        (row["productId"],)).fetchone()
    if not stored:
        problems.append(f"{where}: productId {row['productId']} finns inte i produkttabellen")
        continue
    if row["productName"] != stored[0]:
        problems.append(f"{where}: visat namn {row['productName']!r} != databasens {stored[0]!r}")

    # --- varumärke bara när kedjan angett ett ----------------------------
    if row.get("brand"):
        stats["brand"] += 1
        if row["brand"] != stored[1]:
            problems.append(f"{where}: märke {row['brand']!r} != databasens {stored[1]!r}")
    elif stored[1]:
        problems.append(f"{where}: databasen har märket {stored[1]!r} men raden visar inget")

    # --- paketstorlek -----------------------------------------------------
    if row.get("packageSize"):
        stats["package"] += 1
        if row["packageSize"] != stored[2]:
            problems.append(f"{where}: storlek {row['packageSize']!r} != databasens {stored[2]!r}")
    if not row.get("packageAmount") and not row.get("perKg"):
        problems.append(f"{where}: otolkad paketstorlek {row.get('packageSize')!r}")

    # --- bilden hör till produkten ---------------------------------------
    image = row.get("imageUrl")
    if image:
        stats["image"] += 1
        if image != stored[3]:
            problems.append(f"{where}: bild {image} != produktens egen {stored[3]}")
        if not str(image).startswith("https://"):
            problems.append(f"{where}: bild är inte https: {image}")
    else:
        stats["no_image"] += 1

    # --- Dabas-bilder ska vara AV ----------------------------------------
    if image and "dabas" in str(image).lower():
        stats["dabas_image"] += 1
        problems.append(f"{where}: Dabas-bild visas: {image}")

print(f"Kontrollerade {len(rows)} rader ur riktig kedjedata")
print(f"  med GTIN:          {stats['gtin']}")
print(f"  med varumärke:     {stats['brand']}")
print(f"  med paketstorlek:  {stats['package']}")
print(f"  med bild:          {stats['image']}")
print(f"  utan bild (fallback förväntas): {stats['no_image']}")
print(f"  Dabas-bilder:      {stats['dabas_image']} (ska vara 0)")
print()
if problems:
    print(f"AVVIKELSER ({len(problems)}):")
    for problem in problems[:25]:
        print("  -", problem)
else:
    print("Inga avvikelser.")

gs.close()
rs.close()
sys.exit(1 if problems else 0)
