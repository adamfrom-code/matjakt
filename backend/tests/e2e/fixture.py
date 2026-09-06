# -*- coding: utf-8 -*-
"""Syntetisk prisdata för browser-E2E - inga riktiga anrop, inga riktiga
databaser.

Tre butiker nära Gävle (postnummer 80252), en produkt per ingrediensnamn i
receptbanken hos varje släppt kedja, med kedjespecifika priser så att en
"Billigast" faktiskt går att kröna (identiska totaler blockerar jämförelsen,
se compare_chains). Produktnamnet ÄR ingrediensnamnet: fixturen testar
konsumentresan, inte matchningsreglerna - de har sina egna tester.
"""

import re
import sqlite3
import time

from services.grocery.models import RawProduct
from services.grocery.store import GroceryStore

GAVLE = {"ort": "Gävle", "lat": 60.6749, "lon": 17.1413}
POSTCODE = "80252"

# Kedja -> (externt butiks-id, namn, prisfaktor). Willys billigast så
# Free-vyn har en tydlig vinnare; Hemköp och City Gross dyrare men
# fullt täckta (>= 85 % krävs för att få vara med i jämförelsen).
STORES = (
    ("Willys", "e2e-willys", "Willys Gävle Hemlingby", 1.00),
    ("Hemköp", "e2e-hemkop", "Hemköp Gävle Drottninggatan", 1.18),
    ("City Gross", "e2e-citygross", "City Gross Gävle", 1.09),
)

# Enhet i receptet -> förpackning (mängd, enhet, storlekstext).
PACKAGES = {
    "g": (1000.0, "g", "1 kg"),
    "ml": (1000.0, "ml", "1 l"),
    "dl": (1000.0, "ml", "1 l"),
    "l": (1000.0, "ml", "1 l"),
    "st": (1.0, "st", "1 st"),
}


def _base_price(name: str) -> float:
    """Deterministiskt pris ur namnet - samma vara kostar lika mycket från
    körning till körning, olika varor olika."""
    digest = sum(ord(ch) * (index + 1) for index, ch in enumerate(name)) % 400
    return 9.95 + digest / 10.0


def seed_grocery(grocery_db_path, recipe_db_path) -> dict:
    """Skapar butiker, produkter och priser. Returnerar en summering."""
    with sqlite3.connect(str(recipe_db_path)) as recipes:
        rows = recipes.execute(
            "SELECT name, MIN(unit) FROM recipe_ingredients WHERE pantry_staple = 0 GROUP BY name").fetchall()
    ingredients = [(name, unit) for name, unit in rows if name]

    db = GroceryStore(grocery_db_path)
    try:
        stores = {}
        for chain, external_id, label, _ in STORES:
            stores[chain] = db.upsert_store(
                chain=chain, external_store_id=external_id, name=label, city="Gävle",
                postal_code=POSTCODE, address="Testgatan 1",
                latitude=GAVLE["lat"] + 0.01 * len(stores), longitude=GAVLE["lon"] + 0.01,
                active=True, provider="e2e",
                pricing_scope="STORE_SPECIFIC" if chain == "City Gross" else "NATIONAL")
        products = 0
        with db.bulk_transaction():
            for chain, external_id, _, factor in STORES:
                store = stores[chain]
                for name, unit in ingredients:
                    quantity, pack_unit, size = PACKAGES.get((unit or "st").lower(), PACKAGES["st"])
                    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
                    product = db.find_or_create_product(RawProduct(
                        chain=chain, external_product_id=f"e2e-{slug}", name=name,
                        store_id=external_id, store_name=chain, gtin=None, brand="E2E",
                        size=size, quantity=quantity, unit=pack_unit, category=None))
                    price = round(_base_price(name) * factor, 2)
                    db.upsert_current_price(
                        product_id=product.id, store_id=store.id, regular_price=price,
                        campaign_price=None, member_price=None, multibuy_price=None,
                        unit_price=None, currency="SEK", source_url=None, fetched_at=time.time())
                    if chain != "City Gross":
                        db.upsert_reference_price(product_id=product.id, chain=chain, regular_price=price)
                    products += 1
        return {"ingredients": len(ingredients), "products": products,
                "stores": {chain: stores[chain].id for chain in stores}}
    finally:
        db.close()
