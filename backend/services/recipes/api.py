# -*- coding: utf-8 -*-
"""API-lagret över receptdatabasen.

The only thing api_server.py needs to know about recipes. Two rules shape it:

FILTERING HAPPENS IN SQL. The recipe page offers shelves ("Under 20 minuter",
"Barnens favoriter") and filters (price, time, protein, tags). Loading every
recipe and sifting it in Python is fine at 58 and hopeless at 5 000, so every
shelf is a query. Adding a shelf never means touching the rendering code.

THE CLIENT GETS WHAT THE SCREEN NEEDS. A list view gets a card-sized
projection, not the full recipe with all its steps and ingredients - a phone
should not download the whole bank to draw ten cards.
"""

import os
import threading
import time
from pathlib import Path

from .store import RecipeStore

DB_PATH = Path(os.environ.get("MATJAKT_DATA_DIR")
               or (Path(__file__).resolve().parents[2] / "data")) / "recipes.db"

# The recipe bank changes only when we publish recipes, so a short read cache
# removes almost all repeated work without any risk of serving a stale menu
# for long.
_CACHE: dict = {}
_CACHE_TTL_SECONDS = 120
_LOCK = threading.Lock()


# The recipe SOURCES are committed JSON; recipes.db is built from them. On a
# developer's machine that happens when you run the import script. In
# production nothing ever ran it, so the database was empty and the app had no
# recipes at all - the same shape of gap that left the price database empty
# after every deploy.
# NOT under backend/data/. The Render disk mounts at /app/backend/data and
# a mount SHADOWS whatever the image had at that path - so the recipe JSON
# shipped in the image was invisible at runtime, and production served zero
# recipes from a fully deployed backend. The sources are code; they belong
# next to the code, not inside the volume.
RECIPE_SOURCE_DIR = Path(__file__).resolve().parents[2] / "recipe_sources"


def bootstrap_if_empty() -> int:
    """Builds the recipe bank from the committed JSON when it is missing.

    Runs at startup, once, and only when the database holds nothing - an
    ordinary deploy must not rebuild a bank that is already there, because
    that would also throw away images the backfill has since attached.

    Returns how many recipes were imported."""
    store = open_store()
    try:
        if store.count() > 0:
            return 0
    finally:
        store.close()

    # Imported lazily: the importer pulls in the image pipeline, which is not
    # something an ordinary request path should ever load.
    import json as _json
    from .images import placeholder

    store = open_store()
    imported = 0
    try:
        for path in sorted(RECIPE_SOURCE_DIR.glob("*.json")):
            try:
                recipes = _json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for recipe in recipes:
                nutrition = recipe.pop("nutrition", {}) or {}
                recipe.update({k: nutrition.get(k) for k in ("kcal", "protein", "carbs", "fat", "fiber")})
                recipe["totalTime"] = (recipe.get("prepTime") or 0) + (recipe.get("cookTime") or 0)
                # No image lookup here. Startup must not depend on a network
                # call to Wikimedia or Pexels, and images are attached by the
                # backfill script, which is where that belongs.
                if not recipe.get("image"):
                    recipe.update(placeholder(recipe))
                store.upsert_recipe(recipe)
                imported += 1
    finally:
        store.close()
    clear_cache()
    return imported


def open_store() -> RecipeStore:
    return RecipeStore(DB_PATH)


def clear_cache():
    with _LOCK:
        _CACHE.clear()


def _cached(key, build):
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[1] > time.time():
            return hit[0]
    value = build()
    with _LOCK:
        if len(_CACHE) > 200:
            _CACHE.clear()
        _CACHE[key] = (value, time.time() + _CACHE_TTL_SECONDS)
    return value


def card(recipe: dict) -> dict:
    """A recipe as a list card: enough to draw it and decide to open it.

    Deliberately omits ingredients and instructions. A shelf of ten cards
    would otherwise carry ten full recipes, and the recipe page shows several
    shelves at once."""
    return {
        "id": recipe["id"], "slug": recipe["slug"], "name": recipe["name"],
        "description": recipe["description"],
        "totalTime": recipe["totalTime"], "servings": recipe["servings"],
        "nutrition": recipe["nutrition"],
        "image": recipe["image"], "imageAlt": recipe["imageAlt"],
        "tags": recipe["tags"], "categories": recipe["categories"],
        "dietFlags": recipe["dietFlags"], "allergens": recipe["allergens"],
        # A real portion cost from the pricing run, never an estimate. Null
        # when the last run could not price every countable ingredient -
        # a portion price missing two of nine ingredients is not a price.
        "pricePerPortion": recipe.get("pricePerPortion"),
        "priceChain": recipe.get("priceChain"),
        "pricedAt": recipe.get("pricedAt"),
    }


# The shelves on the recipe page, as data. Each is a query, not a hand-picked
# list of recipe names - a new recipe joins the right shelves the moment it is
# published, and a shelf that would be empty is simply not returned.
SHELVES = [
    {"key": "nytt", "title": "Nytt i Matjakt", "order": "newest"},
    {"key": "barn", "title": "Barnens favoriter", "tags": ["barn"]},
    {"key": "snabbt", "title": "Under 20 minuter", "maxTime": 20},
    {"key": "billigt", "title": "Under 25 kr/portion", "tags": ["billigt"]},
    {"key": "proteinrikt", "title": "Proteinrikt", "minProtein": 30},
    {"key": "familj", "title": "Familjemiddag", "tags": ["Familjefavorit"]},
    {"key": "vegetariskt", "title": "Vegetariskt", "tags": ["vegetariskt"]},
    {"key": "mealprep", "title": "Meal prep", "tags": ["mealprep"]},
    {"key": "helg", "title": "Helgmiddag", "tags": ["helgmiddag"]},
]


def shelves(per_shelf: int = 12) -> dict:
    """Every shelf the recipe page shows, in one request.

    One round trip rather than nine: the page draws them together, and nine
    requests on a phone is nine chances to be slow."""
    def build():
        store = open_store()
        try:
            result = []
            for shelf in SHELVES:
                if shelf.get("order") == "newest":
                    rows = [dict(r) for r in store.connection.execute(
                        "SELECT id FROM recipes ORDER BY created_at DESC, name LIMIT ?",
                        (per_shelf,))]
                    recipes = [store.get(row["id"]) for row in rows]
                else:
                    recipes = store.search(tags=shelf.get("tags"),
                                           max_time=shelf.get("maxTime"),
                                           min_protein=shelf.get("minProtein"),
                                           limit=per_shelf)
                # A shelf with nothing on it is not a shelf. Showing an empty
                # "Barnens favoriter" tells the user we have nothing, in the
                # place where we promised something.
                if recipes:
                    result.append({"key": shelf["key"], "title": shelf["title"],
                                   "recipes": [card(r) for r in recipes]})
            return {"shelves": result, "total": store.count()}
        finally:
            store.close()
    return _cached(("shelves", per_shelf), build)


def search(**kwargs) -> dict:
    limit = min(int(kwargs.pop("limit", 60) or 60), 200)
    offset = max(int(kwargs.pop("offset", 0) or 0), 0)
    def build():
        store = open_store()
        try:
            recipes = store.search(limit=limit, offset=offset, **kwargs)
            return {"recipes": [card(r) for r in recipes], "total": store.count(),
                    "limit": limit, "offset": offset}
        finally:
            store.close()
    return _cached(("search", repr(sorted(kwargs.items())), limit, offset), build)


def get(recipe_id: str) -> dict | None:
    """One full recipe - ingredients, steps and all. This is the only place
    that returns everything, because it is the only screen that needs it."""
    def build():
        store = open_store()
        try:
            return store.get(recipe_id)
        finally:
            store.close()
    return _cached(("get", recipe_id), build)


def stats() -> dict:
    def build():
        store = open_store()
        try:
            return store.stats()
        finally:
            store.close()
    return _cached(("stats",), build)
