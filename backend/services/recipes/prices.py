# -*- coding: utf-8 -*-
"""Räknar ut riktiga portionspriser för hela receptbanken.

THE RULE THIS MODULE ENFORCES: a recipe card only ever shows a price that a
person could actually pay. Every countable ingredient priced against a real
product at a real chain, whole packages, or no price at all. A portion cost
that quietly omits the chicken because the match failed is not "almost
right" - it is a smaller number than the checkout will say, which is the
worst direction to be wrong in for a budgeting app.

Runs in the background: at startup once the recipe bank exists, and after
every successful grocery import (fresh prices should reach the cards without
waiting for a redeploy). Never in a request path - pricing ~90 recipes
against three chains takes tens of seconds, which is a job, not a request.
"""

import logging
import threading

from . import api as recipes_api

logger = logging.getLogger("matjakt.recipes.prices")

# One reprice at a time. A second trigger while one runs (import finishing
# during startup's run) is a no-op, not a queue - the running pass reads the
# same fresh prices anyway.
_LOCK = threading.Lock()


def _countable(ingredient: dict) -> bool:
    """The lines a shopper actually buys: not cupboard staples, not optional
    garnish. Same definition the shopping list uses."""
    return not ingredient.get("pantryStaple") and not ingredient.get("optional")


def items_for(recipe: dict) -> list[dict]:
    return [
        {"name": ingredient["name"], "amount": ingredient.get("amount"),
         "unit": ingredient.get("unit")}
        for ingredient in recipe.get("ingredients", []) if _countable(ingredient)
    ]


def reprice_all() -> dict:
    """Prices every recipe and stores the verdict, including 'no price'.

    Returns {"priced": n, "unpriced": n, "recipes": total} for logs/tests."""
    if not _LOCK.acquire(blocking=False):
        return {"skipped": "already_running"}
    try:
        return _reprice_locked()
    finally:
        _LOCK.release()


def _reprice_locked() -> dict:
    # Imported here, not at module top: the recipes service must load even
    # where the grocery stack is absent (some tests), and this module is
    # useless without it anyway.
    from ..grocery import api as grocery_api
    from ..grocery.pricing import RecipePricingEngine

    chains = grocery_api.priceable_chains()
    if not chains:
        logger.info("Ingen kedja har prisdata - receptpriser hoppas över")
        return {"skipped": "no_chains"}

    recipe_store = recipes_api.open_store()
    grocery_store = grocery_api.open_store()
    priced = unpriced = 0
    try:
        engine = RecipePricingEngine(grocery_store)
        stores = {}
        for chain in chains:
            row = grocery_api._store_row_for(grocery_store, chain)
            if row is not None:
                stores[chain] = row["id"]

        ids = [r["id"] for r in recipe_store.connection.execute("SELECT id FROM recipes")]
        for recipe_id in ids:
            recipe = recipe_store.get(recipe_id)
            if not recipe:
                continue
            items = items_for(recipe)
            servings = recipe.get("servings") or 4
            best = None  # (portion_price, chain, covered, total)
            for chain, store_id in stores.items():
                result = engine.price_list(items, chain, store_id)
                # Matchade rader räcker här - även de vars PAKETANTAL är en
                # gissning (kryddmått mot gram-burkar). Portionspriset är
                # uttryckligen ett cirkapris per portion; det är BUTIKS-
                # JÄMFÖRELSEN som aldrig får räkna en gissning som säker,
                # och den läser realPriceItems, inte det här kriteriet.
                # (Skärpningen av realPriceItems 2026-09-01 nollade annars
                # portionspriset för varje recept med en kryddrad.)
                covered = result.get("realPriceItems", 0) + result.get("estimatedItems", 0)
                total = result.get("totalItems", len(items))
                # Full match or nothing: a partially-matched week total is
                # a smaller number than the real one, presented as smaller.
                if total == 0 or covered < total:
                    continue
                portion = result["totalCheckoutCost"] / servings
                if portion <= 0:
                    continue
                if best is None or portion < best[0]:
                    best = (round(portion, 2), chain, covered, total)
            if best:
                recipe_store.set_price(recipe_id, price_per_portion=best[0],
                                       chain=best[1], covered=best[2], total=best[3])
                priced += 1
            else:
                # Overwrites any earlier success on purpose - see set_price.
                recipe_store.set_price(recipe_id, price_per_portion=None, chain=None,
                                       covered=0, total=len(items))
                unpriced += 1
    finally:
        grocery_store.close()
        recipe_store.close()

    recipes_api.clear_cache()
    logger.info("Receptpriser: %d prissatta, %d utan fullt pris", priced, unpriced)
    return {"priced": priced, "unpriced": unpriced, "recipes": priced + unpriced}


def reprice_in_background(reason: str = ""):
    """Fire-and-forget wrapper for startup and post-import hooks."""
    def run():
        try:
            result = reprice_all()
            if result.get("skipped"):
                return
            logger.info("Receptprissättning klar (%s): %s", reason or "manuell", result)
        except Exception:
            logger.exception("Receptprissättningen misslyckades (%s)", reason)
    threading.Thread(target=run, name="recipe-prices", daemon=True).start()
