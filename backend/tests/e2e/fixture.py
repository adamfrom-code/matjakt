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
#
# msk/tsk/krm hörde inte hit förut och föll på fallbacken till "1 st". Då
# sålde fixturen olivolja och sirap STYCKVIS, och eftersom styck inte går
# att räkna om till en volym blev raderna estimat. Riktiga butiker säljer
# olja i flaska; att fixturen gör det med är inte en eftergift utan en
# rättelse.
PACKAGES = {
    "g": (1000.0, "g", "1 kg"),
    "ml": (1000.0, "ml", "1 l"),
    "dl": (1000.0, "ml", "1 l"),
    "l": (1000.0, "ml", "1 l"),
    "msk": (1000.0, "ml", "1 l"),
    "tsk": (1000.0, "ml", "1 l"),
    "krm": (1000.0, "ml", "1 l"),
    "st": (1.0, "st", "1 st"),
}


# Vilken enhetsfamilj en förpackning helst ska ha. Massa först, sedan
# volym, styck sist - för att motorn kan väga om ETT STYCK till gram via
# styckvikttabellen, men inte 300 g till ett antal morötter. En gramvara
# duger alltså åt båda sorternas recept; en styckvara bara åt sina egna.
_FAMILJ = {"g": 0, "kg": 0, "hg": 0, "ml": 1, "dl": 1, "l": 1, "msk": 1, "tsk": 1, "krm": 1}


def _forpackningsenhet(rows) -> str | None:
    """Vilken enhet varan SÄLJS i, given hur recepten mäter den.

    Förut stod det MIN(unit) i frågan, och alfabetisk ordning är inte ett
    val. Vetemjöl mäts i gram i 18 recept, dl i 5 och msk i 4 - MIN valde
    'dl' därför att d kommer före g, så fixturen sålde mjöl per liter och
    de 18 gramrecepten gick inte att räkna om: 18 rader blev estimat.

    Estimat räknas inte in i coveragePercent (se pricing.price_list), och
    under 85 % slutar kedjan vara jämförbar. Konsumentresan kräver tre
    prissatta butikskort - så en fixtur där VARENDA vara har ett pris kunde
    ändå ge noll kort, beroende på vilka recept veckan råkade välja. Det såg
    ut som flakighet och var en sorteringsordning.

    Ordningen är familj först, antal sedan, enhetsnamnet sist - det sista
    bara för att två lika vanliga enheter ska ge samma svar varje körning.
    """
    if not rows:
        return None
    return sorted(rows, key=lambda rad: (_FAMILJ.get((rad[0] or "").lower(), 2),
                                         -rad[1], rad[0] or ""))[0][0]


def _base_price(name: str) -> float:
    """Deterministiskt pris ur namnet - samma vara kostar lika mycket från
    körning till körning, olika varor olika."""
    digest = sum(ord(ch) * (index + 1) for index, ch in enumerate(name)) % 400
    return 9.95 + digest / 10.0


def seed_grocery(grocery_db_path, recipe_db_path) -> dict:
    """Skapar butiker, produkter och priser. Returnerar en summering."""
    # ÄVEN skafferivarorna. De prissätts aldrig som del av en vecka (motorn
    # hoppar över pantry_staple), men butiken säljer förstås salt och olja -
    # och användaren kan lägga till dem på listan när hen inte har dem hemma.
    # Utan produkter för dem gick den vägen inte att pröva: varje tillägg
    # blev en oprissatt rad, oavsett om koden fungerade eller inte.
    # Veckans täckning påverkas inte, just för att raderna hoppas över.
    with sqlite3.connect(str(recipe_db_path)) as recipes:
        rows = recipes.execute(
            "SELECT name, unit, COUNT(*) FROM recipe_ingredients GROUP BY name, unit").fetchall()
    per_namn: dict[str, list] = {}
    for name, unit, antal in rows:
        if name:
            per_namn.setdefault(name, []).append((unit, antal))
    ingredients = [(name, _forpackningsenhet(rader)) for name, rader in sorted(per_namn.items())]

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
                    # GTIN på riktigt: utan det nycklade klienten sina
                    # hushållsrader på namn av en slump, och den riktiga
                    # buggen (gtin-nyckel mot namn-nyckel) syntes aldrig.
                    gtin = "73" + f"{abs(hash((chain, slug))) % 10**11:011d}"
                    product = db.find_or_create_product(RawProduct(
                        chain=chain, external_product_id=f"e2e-{slug}", name=name,
                        store_id=external_id, store_name=chain, gtin=gtin, brand="E2E",
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
