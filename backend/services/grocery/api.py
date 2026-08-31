# -*- coding: utf-8 -*-
"""The API layer over the grocery price database.

This is the ONLY thing api_server.py needs to know about the grocery backend:
it opens the database, prices a week's shopping list against real products,
and reports what the database actually contains. Everything chain-specific
stays behind the providers, exactly as the module README requires.

Two honesty rules carry through from grocery/pricing.py and must not be
softened by anything here:

  NEVER INVENT A PRICE. An ingredient with no confident product match is
  reported in missingItems and lowers coverage. It is never estimated and
  never dropped from the total, because dropping it would make a chain look
  cheaper than it is.

  A TOTAL IS ONLY COMPARABLE ALONGSIDE ITS COVERAGE. 320 kr covering 12 of 20
  items is not a smaller number than 380 kr covering 20 of 20 - it is a
  different question. Every result therefore carries coverage, and
  compare_chains() refuses to name a cheapest chain when the comparison
  cannot bear it.
"""

import logging
import threading
import time
from pathlib import Path

from .pricing import RecipePricingEngine
from .store import GroceryStore

logger = logging.getLogger("matjakt.grocery.api")

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "grocery.db"

# A chain must price at least this share of the list before its total is
# allowed to be compared with another chain's. Below it the two numbers are
# answering different questions - see the module docstring.
MIN_COVERAGE_FOR_COMPARISON = 60

# A price this old is still shown (with its age), but a chain whose data is
# this stale must not be crowned cheapest against a freshly imported one.
MAX_AGE_SECONDS_FOR_COMPARISON = 14 * 24 * 3600

# Results are cached briefly: the same week's list gets priced again on every
# re-render, and the underlying data only changes when a collector runs.
_CACHE: dict = {}
_CACHE_TTL_SECONDS = 300
_CACHE_MAX_ENTRIES = 200
_LOCK = threading.Lock()


def _cache_get(key):
    with _LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        value, expires = entry
        if expires < time.time():
            _CACHE.pop(key, None)
            return None
        return value


def _cache_set(key, value):
    with _LOCK:
        if len(_CACHE) >= _CACHE_MAX_ENTRIES:
            _CACHE.clear()
        _CACHE[key] = (value, time.time() + _CACHE_TTL_SECONDS)


def clear_cache():
    """Called after an import, so newly collected prices are visible at once
    instead of after the TTL."""
    with _LOCK:
        _CACHE.clear()


def open_store() -> GroceryStore:
    return GroceryStore(DB_PATH)


def database_summary() -> dict:
    """What the price database actually holds, per chain.

    This is deliberately blunt: the frontend must be able to tell the
    difference between "Willys is expensive" and "we have barely any Willys
    data", and so must we when a deploy comes up with an empty disk."""
    store = open_store()
    try:
        chains = []
        rows = store.connection.execute(
            """
            SELECT e.chain AS chain,
                   COUNT(DISTINCT e.product_id) AS products,
                   SUM(CASE WHEN p.category IS NOT NULL THEN 1 ELSE 0 END) AS with_category,
                   SUM(CASE WHEN p.gtin IS NOT NULL THEN 1 ELSE 0 END) AS with_gtin
            FROM grocery_product_external_ids e
            JOIN grocery_products p ON p.id = e.product_id
            GROUP BY e.chain
            ORDER BY e.chain
            """
        ).fetchall()
        for row in rows:
            fetched = store.connection.execute(
                """
                SELECT MAX(cp.fetched_at) FROM grocery_current_prices cp
                JOIN grocery_product_external_ids e ON e.product_id = cp.product_id
                WHERE e.chain = ?
                """,
                (row["chain"],),
            ).fetchone()[0]
            chains.append({
                "chain": row["chain"],
                "products": row["products"],
                "withCategory": row["with_category"] or 0,
                "withGtin": row["with_gtin"] or 0,
                "lastFetchedAt": fetched,
                "ageSeconds": (time.time() - fetched) if fetched else None,
            })
        total = store.connection.execute("SELECT COUNT(*) FROM grocery_products").fetchone()[0]
        return {"totalProducts": total, "chains": chains}
    finally:
        store.close()


def priceable_chains() -> list[str]:
    """Chains that actually have data to price against. A chain with no rows
    must not appear in a comparison at all - an empty chain would otherwise
    show up as the cheapest, at 0 kr."""
    return [entry["chain"] for entry in database_summary()["chains"] if entry["products"] > 0]


def _store_id_for(store: GroceryStore, chain: str):
    row = store.connection.execute(
        "SELECT id FROM grocery_stores WHERE chain = ? ORDER BY id LIMIT 1", (chain,)
    ).fetchone()
    return row["id"] if row else None


def price_week(items: list[dict], chains: list[str] | None = None,
               pantry: dict | None = None) -> dict:
    """Prices one week's summed ingredient list against every chain.

    items are already week-aggregated: [{"name","amount","unit"}, ...].
    Returns one result per chain plus a comparison that is allowed to stay
    undecided - see compare_chains."""
    available = priceable_chains()
    chains = [chain for chain in (chains or available) if chain in available]

    key = None
    try:
        key = repr((sorted((i.get("name"), i.get("amount"), i.get("unit")) for i in items),
                    tuple(sorted(chains)), tuple(sorted((pantry or {}).items()))))
    except TypeError:
        key = None  # unhashable input - price it, just don't cache it
    if key:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    store = open_store()
    try:
        engine = RecipePricingEngine(store)
        results = []
        for chain in chains:
            store_id = _store_id_for(store, chain)
            if store_id is None:
                continue
            result = engine.price_list(items, chain, store_id, pantry=pantry)
            result["dataAgeSeconds"] = _chain_age_seconds(store, chain)
            results.append(result)
    finally:
        store.close()

    payload = {"results": results, "comparison": compare_chains(results)}
    if key:
        _cache_set(key, payload)
    return payload


def _chain_age_seconds(store: GroceryStore, chain: str):
    row = store.connection.execute(
        """
        SELECT MAX(cp.fetched_at) FROM grocery_current_prices cp
        JOIN grocery_product_external_ids e ON e.product_id = cp.product_id
        WHERE e.chain = ?
        """,
        (chain,),
    ).fetchone()
    return (time.time() - row[0]) if row and row[0] else None


def compare_chains(results: list[dict]) -> dict:
    """Names a cheapest chain ONLY when the comparison actually holds.

    Calling a chain cheapest is a factual claim about the user's money, so it
    needs a basis that bears weight. Four things each block it on their own,
    and each has produced a wrong claim in this app before:

      1. Fewer than two chains priced - nothing to compare against.
      2. A chain covering too little of the list (below
         MIN_COVERAGE_FOR_COMPARISON): its total is small because items are
         MISSING, not because the shop is cheap. This is the failure mode
         that matters most, since it makes the worst-covered chain look best.
      3. Every total identical - that is what happens when the numbers are
         not really chain-specific, and crowning one of several identical
         figures is exactly the "Coop 351 / Willys 351 / ICA 351, one marked
         cheapest" bug.
      4. Data too old to compare against fresh data.

    When blocked, the totals are still returned - they are real - but with
    cheapestChain None and a reason the UI can show instead of a claim."""
    comparable = [r for r in results
                  if r.get("coveragePercent", 0) >= MIN_COVERAGE_FOR_COMPARISON
                  and r.get("realPriceItems", 0) > 0
                  and (r.get("dataAgeSeconds") is None
                       or r["dataAgeSeconds"] <= MAX_AGE_SECONDS_FOR_COMPARISON)]

    if len(comparable) < 2:
        return {"cheapestChain": None, "savings": None, "comparedChains": len(comparable),
                "reason": "too_few_comparable_chains"}

    totals = sorted(comparable, key=lambda r: r["totalCheckoutCost"])
    cheapest, priciest = totals[0], totals[-1]
    if cheapest["totalCheckoutCost"] == priciest["totalCheckoutCost"]:
        return {"cheapestChain": None, "savings": None, "comparedChains": len(comparable),
                "reason": "all_totals_identical"}

    return {
        "cheapestChain": cheapest["chain"],
        "cheapestTotal": cheapest["totalCheckoutCost"],
        "priciestChain": priciest["chain"],
        "priciestTotal": priciest["totalCheckoutCost"],
        "savings": round(priciest["totalCheckoutCost"] - cheapest["totalCheckoutCost"], 2),
        "comparedChains": len(comparable),
        "reason": None,
    }


def shopping_list(items: list[dict], chain: str, pantry: dict | None = None) -> dict:
    """One chain's store-specific shopping list: the real products to put in
    the basket, with image, pack size, package count and price - plus what we
    could NOT price, which stays visible rather than quietly disappearing."""
    store = open_store()
    try:
        store_id = _store_id_for(store, chain)
        if store_id is None:
            return {"chain": chain, "error": "no_data_for_chain",
                    "matchedItems": [], "missingItems": list(items or [])}
        result = RecipePricingEngine(store).price_list(items, chain, store_id, pantry=pantry)
        result["dataAgeSeconds"] = _chain_age_seconds(store, chain)
        return result
    finally:
        store.close()
