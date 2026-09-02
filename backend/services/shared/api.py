# -*- coding: utf-8 -*-
"""Det api_server.py behöver veta om det delade lagret.

Formen är medvetet densamma som services/recipes/api.py: en tunn modul som
äger sina egna frågor och sin egen cache, så en ny endpoint aldrig blir en
ny klump i api_server.py.

TVÅ SAKER SOM INTE FÅR LÄCKA HÄR:

PRISER. Receptkorten i Matjakt bär pricePerPortion från prissättnings-
körningen. De fälten skalas BORT här. Prisgrindens fail-closed-regler och
Dabas villkor gäller Matjakts egna ytor; att skicka samma tal vidare genom
en ny endpoint vore att publicera dem någon annanstans utan att någon
beslutat det. Delade priser är ett eget beslut - se docs/SHARED_API.md.

BILDRÄTTIGHETER. Bilden följer med tillsammans med sin licens och sin
källa, aldrig utan. En delad app som visar bilden måste kunna visa
attributionen, och det går bara om den får den.
"""

import threading
import time

from ..recipes import api as recipes_api
from .canonical import DEFAULT_PANTRY_STAPLES, canonical_ingredient, canonical_id
from .matching import match_recipes, resolve_staples
from .portions import scale_recipe

# Kontraktets version. Höjs när ett fält FÖRSVINNER eller byter betydelse -
# nya fält är inte en ny version, eftersom ingen konsument går sönder av
# dem. En app kan läsa den ur /api/v1/shared/meta och vägra starta mot en
# version den inte känner igen.
CONTRACT_VERSION = "1.0"

# Matchning läser hela banken. Att bygga indexet per anrop är två SQL-
# frågor och 241 rader i dag - billigt, men inte gratis, och banken ändras
# bara när recept publiceras. Samma TTL som receptlagrets egen cache.
_INDEX_TTL_SECONDS = 120
_INDEX = None
_INDEX_EXPIRES = 0.0
_LOCK = threading.Lock()

# Fält på ett receptkort som ALDRIG lämnar Matjakt genom det här lagret.
_PRICE_FIELDS = ("pricePerPortion", "priceChain", "priceCovered", "priceTotal", "pricedAt")


def _public(recipe: dict) -> dict:
    """Ett recept som en delad app får se det."""
    return {key: value for key, value in recipe.items() if key not in _PRICE_FIELDS}


def clear_cache():
    """Anropas när banken ändrats. Receptlagret har sin egen cache; den här
    modulen har en till, och båda måste tömmas eller så matchar en app mot
    en bank som inte finns längre."""
    global _INDEX, _INDEX_EXPIRES
    with _LOCK:
        _INDEX, _INDEX_EXPIRES = None, 0.0


def _build_index() -> list:
    """Hela banken med sina ingredienser, i TVÅ frågor.

    Inte 241 anrop till store.get(): en fråga för recepten och en för alla
    ingrediensrader, hopfogade i Python. Skillnaden är hela poängen med att
    lägga matchningen i backend i stället för att skicka banken till
    telefonen."""
    store = recipes_api.open_store()
    try:
        rows = {}
        for row in store.connection.execute(
                "SELECT id, slug, name, description, total_time, servings, "
                "       kcal, protein, carbs, fat, fiber, image, image_alt, "
                "       image_credit, image_license, image_source_url "
                "FROM recipes ORDER BY name"):
            rows[row["id"]] = {
                "id": row["id"], "slug": row["slug"], "name": row["name"],
                "description": row["description"], "totalTime": row["total_time"],
                "servings": row["servings"],
                "nutrition": {"kcal": row["kcal"], "protein": row["protein"],
                              "carbs": row["carbs"], "fat": row["fat"],
                              "fiber": row["fiber"]},
                "image": row["image"], "imageAlt": row["image_alt"],
                "imageCredit": row["image_credit"],
                "imageLicense": row["image_license"],
                "imageSourceUrl": row["image_source_url"],
                "ingredients": [],
            }
        for row in store.connection.execute(
                "SELECT recipe_id, name, amount, unit, normalized_id, optional, "
                "       pantry_staple FROM recipe_ingredients ORDER BY recipe_id, position"):
            recipe = rows.get(row["recipe_id"])
            if recipe is not None:
                recipe["ingredients"].append({
                    "name": row["name"], "amount": row["amount"], "unit": row["unit"],
                    "normalizedId": row["normalized_id"],
                    "optional": bool(row["optional"]),
                    "pantryStaple": bool(row["pantry_staple"]),
                })
        # Allergener och kostflaggor: matchning bryr sig inte, men en app
        # som filtrerar bort nötter innan den visar ett kort gör det.
        for row in store.connection.execute(
                "SELECT recipe_id, kind, value FROM recipe_labels "
                "WHERE kind IN ('allergens', 'dietFlags', 'tags')"):
            recipe = rows.get(row["recipe_id"])
            if recipe is not None:
                recipe.setdefault(row["kind"], []).append(row["value"])
        for recipe in rows.values():
            for kind in ("allergens", "dietFlags", "tags"):
                recipe.setdefault(kind, [])
        return list(rows.values())
    finally:
        store.close()


def index() -> list:
    global _INDEX, _INDEX_EXPIRES
    with _LOCK:
        if _INDEX is not None and _INDEX_EXPIRES > time.time():
            return _INDEX
    built = _build_index()
    with _LOCK:
        _INDEX, _INDEX_EXPIRES = built, time.time() + _INDEX_TTL_SECONDS
    return built


def meta() -> dict:
    """Vad kontraktet lovar och vad banken innehåller just nu.

    En delad app anropar den vid start: den ser om Matjakt lever, om
    versionen är begriplig, och hur många recept det finns att matcha mot -
    utan att behöva hämta banken för att ta reda på det."""
    return {
        "contractVersion": CONTRACT_VERSION,
        "recipeCount": len(index()),
        "defaultPantryStaples": sorted(DEFAULT_PANTRY_STAPLES),
        # Uttryckligt, inte underförstått: en app ska inte upptäcka genom
        # att gissa att priser saknas.
        "provides": ["recipes", "ingredients", "recipe-match"],
        "excludes": ["pricing", "products", "accounts"],
    }


def recipes(**kwargs) -> dict:
    """Kortprojektionen av banken, utan priser."""
    result = recipes_api.search(**kwargs)
    return {**result, "recipes": [_public(recipe) for recipe in result["recipes"]]}


def recipe(recipe_id: str, servings=None):
    """Ett helt recept - ingredienser, steg, näring, allergener.

    servings skalar mängderna innan svaret lämnar servern. Skalningen ligger
    i shared/portions.py och inte hos anroparen, därför att den har fyra
    fällor och två appar som skriver den var för sig skriver den olika."""
    found = recipes_api.get(recipe_id)
    if not found:
        return None
    return _public(scale_recipe(found, servings) if servings else found)


def ingredients() -> dict:
    """Varje ingrediens banken känner, kanoniserad.

    Det här är vad en app bygger sin autocomplete på: den som skriver "lö"
    ska få "Lök" ur Matjakts egen vokabulär, inte ur en lista appen hittat
    på - annars matchar det användaren skrev aldrig det recepten säger."""
    counts, labels = {}, {}
    for entry in index():
        for row in entry["ingredients"]:
            identifier = canonical_id(row["name"])
            if not identifier:
                continue
            counts[identifier] = counts.get(identifier, 0) + 1
            # Namnet som visas är det vanligaste stavningssättet i banken,
            # inte det första som råkade dyka upp.
            labels.setdefault(identifier, {})
            labels[identifier][row["name"]] = labels[identifier].get(row["name"], 0) + 1
    result = []
    for identifier, count in counts.items():
        name = max(labels[identifier].items(), key=lambda pair: (pair[1], pair[0]))[0]
        result.append({**canonical_ingredient(name), "id": identifier, "recipeCount": count})
    result.sort(key=lambda row: (-row["recipeCount"], row["name"]))
    return {"ingredients": result, "total": len(result)}


def recipe_match(items, *, extra_staples=None, not_staples=None,
                 max_missing=None, limit=60) -> dict:
    """Skafferi in, recept ut - lagrets enda egentliga beräkning."""
    staples = resolve_staples(extra_staples, not_staples)
    matched = match_recipes(index(), items, staples=staples,
                            max_missing=max_missing, limit=limit)
    return {
        "matches": [{"recipe": _public(entry["recipe"]), **entry["match"]}
                    for entry in matched],
        # Vad motorn FAKTISKT förstod av det som skickades in. Utan detta
        # kan en app inte skilja "receptet finns inte" från "vi tolkade
        # aldrig 'creme fraiche' som crème fraiche".
        "pantry": [canonical_ingredient(item) for item in items],
        "staples": sorted(staples),
        "recipeCount": len(index()),
    }
