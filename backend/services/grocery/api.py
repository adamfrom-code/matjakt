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
import os
import threading
import time
from pathlib import Path

from .pricing import RecipePricingEngine
from .store import GroceryStore

logger = logging.getLogger("matjakt.grocery.api")

# Same override as api_server's DATA_DIR, for the same reason: a test run
# must never read or write the real price database.
DB_PATH = Path(os.environ.get("MATJAKT_DATA_DIR")
               or (Path(__file__).resolve().parents[2] / "data")) / "grocery.db"

# THE central coverage rule. A chain must price at least this share of the
# list before its total may be compared with another chain's, be crowned
# cheapest, or headline a screen. Below it the two numbers are answering
# different questions - see the module docstring.
#
# Raised from 60 to 85 after watching it live: at 60 a chain with 1 of 21
# items priced was excluded (good), but chains around two thirds still slid
# into a comparison where their total was low mostly because items were
# missing. 85 is the point where "this basket is priced" is true enough to
# put a kronor figure next to another shop's.
#
# Every consumer reads `comparable` off the response rather than re-deriving
# this, so there is exactly one threshold in the system.
MIN_COVERAGE_FOR_COMPARISON = 85

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


def campaign_deals(per_chain: int = 10) -> dict:
    """The best current campaign discounts, per chain, from our own data.

    Every price here was collected from the chain itself - campaign_price
    genuinely below regular_price, ranked by discount. No scraping at
    request time, no third party: the Hem screen's campaign rail must never
    make a phone wait on someone else's website. Cached like everything
    else keyed on data_version, so a fresh import shows up immediately."""
    def build():
        store = open_store()
        try:
            deals = {}
            for chain in priceable_chains():
                rows = store.connection.execute(
                    """
                    SELECT p.id AS product_id, p.gtin, p.name, p.brand,
                           p.size, p.image_url,
                           cp.campaign_price, cp.regular_price
                    FROM grocery_current_prices cp
                    JOIN grocery_products p ON p.id = cp.product_id
                    -- The PRICE row's own store decides the chain. Joining
                    -- via external ids let a GTIN-shared product carry one
                    -- chain's campaign into another chain's rail.
                    JOIN grocery_stores st ON st.id = cp.store_id
                    WHERE st.chain = ?
                      AND cp.campaign_price IS NOT NULL
                      AND cp.regular_price IS NOT NULL
                      AND cp.campaign_price < cp.regular_price
                      AND cp.regular_price > 0
                    ORDER BY 1.0 - (cp.campaign_price / cp.regular_price) DESC
                    LIMIT ?
                    """,
                    (chain, per_chain * 3),
                ).fetchall()
                seen, chain_deals = set(), []
                for row in rows:
                    # One deal per product NAME: the same discount on four
                    # pack sizes reads as filler, not as four offers.
                    if row["name"] in seen:
                        continue
                    seen.add(row["name"])
                    discount = round(100 * (1 - row["campaign_price"] / row["regular_price"]))
                    # Below 10 % is shelf noise, not a campaign worth a card.
                    if discount < 10:
                        continue
                    chain_deals.append({
                        "chain": chain, "name": row["name"], "brand": row["brand"],
                        "productId": row["product_id"], "gtin": row["gtin"],
                        # Kampanjens giltighetstid samlas inte in av någon
                        # kedja idag - null, aldrig en gissad slutdag.
                        "validUntil": None,
                        "size": row["size"], "imageUrl": row["image_url"],
                        "campaignPrice": row["campaign_price"],
                        "regularPrice": row["regular_price"],
                        "discountPercent": discount,
                    })
                    if len(chain_deals) >= per_chain:
                        break
                deals[chain] = chain_deals
            return {"deals": deals}
        finally:
            store.close()
    key = f"campaign_deals:{per_chain}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    payload = build()
    _cache_set(key, payload)
    return payload


def database_summary() -> dict:
    """What the price database actually holds, per chain.

    This is deliberately blunt: the frontend must be able to tell the
    difference between "Willys is expensive" and "we have barely any Willys
    data", and so must we when a deploy comes up with an empty disk."""
    store = open_store()
    try:
        chains = []
        # Counted over DISTINCT products, not over the join: one product can
        # carry several external ids for the same chain, and summing the
        # joined rows reported more products "with a category" than there
        # were products (City Gross: 98 products, 100 with category).
        rows = store.connection.execute(
            """
            SELECT chain,
                   COUNT(*) AS products,
                   SUM(CASE WHEN category IS NOT NULL THEN 1 ELSE 0 END) AS with_category,
                   SUM(CASE WHEN gtin IS NOT NULL THEN 1 ELSE 0 END) AS with_gtin,
                   SUM(CASE WHEN image_url IS NOT NULL THEN 1 ELSE 0 END) AS with_image
            FROM (
                SELECT DISTINCT e.chain AS chain, p.id AS id,
                       p.category AS category, p.gtin AS gtin, p.image_url AS image_url
                FROM grocery_product_external_ids e
                JOIN grocery_products p ON p.id = e.product_id
            )
            GROUP BY chain
            ORDER BY chain
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
            prices = store.connection.execute(
                """
                SELECT COUNT(*) FROM grocery_current_prices cp
                JOIN grocery_product_external_ids e ON e.product_id = cp.product_id
                WHERE e.chain = ?
                """,
                (row["chain"],),
            ).fetchone()[0]
            products = row["products"] or 0
            chains.append({
                "chain": row["chain"],
                "products": products,
                "prices": prices,
                "withCategory": row["with_category"] or 0,
                "withGtin": row["with_gtin"] or 0,
                "withImage": row["with_image"] or 0,
                # Percentages are what a panel is actually read for - "812 of
                # 964" needs mental arithmetic at a glance, "84%" does not.
                "categoryPercent": round(100 * (row["with_category"] or 0) / products) if products else 0,
                "gtinPercent": round(100 * (row["with_gtin"] or 0) / products) if products else 0,
                "imagePercent": round(100 * (row["with_image"] or 0) / products) if products else 0,
                "lastFetchedAt": fetched,
                "ageSeconds": (time.time() - fetched) if fetched else None,
            })
        total = store.connection.execute("SELECT COUNT(*) FROM grocery_products").fetchone()[0]
        return {"totalProducts": total, "chains": chains}
    finally:
        store.close()


# Every chain Matjakt knows about, INCLUDING the ones we cannot collect from.
# Leaving Coop and Lidl out of the panel would quietly turn "we are blocked"
# into "we forgot", and the reason each is blocked is the useful part - one
# needs someone else's credential, the other publishes no prices at all.
PROVIDER_STATUS = {
    "Willys": {
        "status": "working", "recurringImportVerified": True, "pricingScope": "national",
        "collectable": True,
        "note": "Axfoods öppna REST-API. Ingen nyckel, cookie, session eller browser.",
    },
    "Hemköp": {
        "status": "working", "recurringImportVerified": True, "pricingScope": "national",
        "collectable": True,
        "note": "Samma Axfood-plattform som Willys. Enda kedjan med riktiga medlemspriser.",
    },
    "City Gross": {
        "status": "working_but_unreliable", "recurringImportVerified": True,
        "pricingScope": "store", "collectable": True,
        "note": "Rikast data, men stryper genom att släppa anslutningar i stället för "
                "HTTP 429. En delvis import är normalt, inte ett fel.",
    },
    "ICA": {
        "status": "working_but_rate_limited", "recurringImportVerified": False,
        "pricingScope": "store", "collectable": False,
        "note": "AWS WAF-challenge vid upprepad hämtning. Vi kringgår den inte. "
                "ICA visar senast hämtade data tills officiell åtkomst är löst.",
    },
    "Coop": {
        "status": "blocked_requires_vendor_credential", "recurringImportVerified": False,
        "pricingScope": None, "collectable": False,
        "note": "All produktdata kräver Coops egen Azure APIM-nyckel. Vi autentiserar "
                "oss inte med någon annans credential.",
    },
    "Lidl": {
        "status": "not_available_no_public_prices", "recurringImportVerified": False,
        "pricingScope": None, "collectable": False,
        "note": "Strukturellt, inte en blockering: Lidl Sverige publicerar inga "
                "per-produkt-priser alls. Går inte att lösa tekniskt och ska inte fejkas.",
    },
}


def provider_status() -> list[dict]:
    """The status panel's data: what each chain's provider can do, and what
    the database actually holds for it right now.

    The two halves must be read together. A chain can be "working" and still
    have no data (nothing has imported yet), and it can have data while being
    uncollectable (ICA's last successful run, kept until official access is
    sorted). Showing only one half would misrepresent both cases."""
    holdings = {entry["chain"]: entry for entry in database_summary()["chains"]}
    store = open_store()
    try:
        def _runs(where: str):
            found = {}
            for row in store.connection.execute(
                f"""
                SELECT chain, status, started_at, finished_at, products_found,
                       prices_updated, error_message
                FROM grocery_collector_runs
                WHERE id IN (SELECT MAX(id) FROM grocery_collector_runs {where} GROUP BY chain)
                """
            ).fetchall():
                found[row["chain"]] = {
                    "status": row["status"], "startedAt": row["started_at"],
                    "finishedAt": row["finished_at"], "productsFound": row["products_found"],
                    "pricesUpdated": row["prices_updated"], "errorMessage": row["error_message"],
                }
            return found

        # Last ATTEMPT and last SUCCESS are different questions and the panel
        # needs both: a chain whose last attempt was blocked can still be
        # serving perfectly good data from a successful run two days ago, and
        # showing only the attempt would read as "this chain is broken".
        runs = _runs("")
        successes = _runs("WHERE status = 'success'")
    finally:
        store.close()

    panel = []
    for chain, meta in PROVIDER_STATUS.items():
        held = holdings.get(chain) or {}
        panel.append({
            "chain": chain, **meta,
            "products": held.get("products", 0),
            "withCategory": held.get("withCategory", 0),
            "prices": held.get("prices", 0),
            "withGtin": held.get("withGtin", 0),
            "withImage": held.get("withImage", 0),
            "categoryPercent": held.get("categoryPercent", 0),
            "gtinPercent": held.get("gtinPercent", 0),
            "imagePercent": held.get("imagePercent", 0),
            "ageSeconds": held.get("ageSeconds"),
            "lastRun": runs.get(chain),
            "lastSuccessfulRun": successes.get(chain),
        })
    return panel


def priceable_chains() -> list[str]:
    """Chains that actually have data to price against. A chain with no rows
    must not appear in a comparison at all - an empty chain would otherwise
    show up as the cheapest, at 0 kr."""
    return [entry["chain"] for entry in database_summary()["chains"] if entry["products"] > 0]


def _store_row_for(store: GroceryStore, chain: str):
    return store.connection.execute(
        "SELECT id, name, external_store_id, city FROM grocery_stores "
        "WHERE chain = ? ORDER BY id LIMIT 1", (chain,)
    ).fetchone()


def _store_id_for(store: GroceryStore, chain: str):
    row = _store_row_for(store, chain)
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
        raw_results, store_rows = [], {}
        for chain in chains:
            store_row = _store_row_for(store, chain)
            if store_row is None:
                continue
            store_rows[chain] = store_row
            result = engine.price_list(items, chain, store_row["id"], pantry=pantry)
            result["dataAgeSeconds"] = _chain_age_seconds(store, chain)
            raw_results.append(result)
    finally:
        store.close()

    # The comparison is decided on the raw results, THEN handed to the
    # formatter - so a chain's "savings" can never be a number the comparison
    # itself refused to stand behind.
    comparison = compare_chains(raw_results)
    results = [format_chain_result(result, store_rows.get(result["chain"]), comparison)
               for result in raw_results]
    payload = {"results": results, "comparison": comparison}
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


# Three genuinely different states, and collapsing any two of them would
# mislead. "current" is a real price for a real product. "estimated" is a
# real price whose PACKAGE COUNT had to be guessed, because the recipe's unit
# could not be converted to the pack's unit (a recipe in "st" against a pack
# in "g") - the money is real, the quantity is not certain. "missing" is an
# ingredient we could not match to a real product at all, and it carries no
# price whatsoever rather than a filled-in guess.
PRICE_STATUS_CURRENT = "current"
PRICE_STATUS_ESTIMATED = "estimated"
PRICE_STATUS_MISSING = "missing"


def format_chain_result(result: dict, store_row=None, comparison: dict | None = None) -> dict:
    """One chain's result in the single shape the frontend consumes.

    Everything the UI needs is here, so no screen has to re-derive a number
    and risk disagreeing with another screen that derived it differently -
    which is how "Coop 351 / Willys 351 / ICA 351, one marked cheapest"
    happened in the first place.

    items[] merges matched and missing into ONE ordered list. Keeping them in
    separate arrays pushed every UI into re-merging them, and a UI that
    forgot would silently drop the unpriced items from the shopping list -
    exactly the disappearance this engine exists to prevent."""
    items = []
    estimated = 0
    for match in result.get("matchedItems", []):
        exact = match.get("exactPackaging", True)
        if not exact:
            estimated += 1
        items.append({
            "ingredient": match.get("name"),
            "priceStatus": PRICE_STATUS_CURRENT if exact else PRICE_STATUS_ESTIMATED,
            "neededAmount": match.get("neededAmount"),
            "neededUnit": match.get("neededUnit"),
            "productId": match.get("productId"),
            "productName": match.get("productName"),
            "brand": match.get("brand"),
            "imageUrl": match.get("imageUrl"),
            "category": match.get("category"),
            "packageSize": match.get("packageSize"),
            "packageAmount": match.get("packageAmount"),
            "packageUnit": match.get("packageUnit"),
            "packages": match.get("packages"),
            "unitPrice": match.get("unitPrice"),
            "totalCost": match.get("totalCost"),
            "regularPrice": match.get("regularPrice"),
            # Only a real discount: campaignPrice is already only set by the
            # providers when it is genuinely below the ordinary price.
            "campaignPrice": match.get("campaignPrice"),
            "memberPrice": match.get("memberPrice"),
            "comparisonPrice": match.get("comparisonPrice"),
            "fetchedAt": match.get("fetchedAt"),
        })
    for missing in result.get("missingItems", []):
        items.append({
            "ingredient": missing.get("name"),
            "priceStatus": PRICE_STATUS_MISSING,
            "neededAmount": missing.get("amount"),
            "neededUnit": missing.get("unit"),
            "productName": None, "imageUrl": None, "packages": None,
            "totalCost": None, "regularPrice": None, "campaignPrice": None,
            "comparisonPrice": None,
        })

    chain = result.get("chain")
    age = result.get("dataAgeSeconds")
    # Savings are only reported for the chain the comparison actually crowned,
    # and only when the comparison was allowed to name one at all.
    savings = None
    if comparison and comparison.get("cheapestChain") == chain:
        savings = comparison.get("savings")

    # WHICH store these prices actually came from, and whether that matters.
    # Willys and Hemköp are verified nationally priced, so any branch of the
    # chain pays this. City Gross and ICA price per store, so a price
    # collected in Gävle is a Gävle price - presenting it under a Stockholm
    # branch's name without saying so would be a quiet lie.
    scope = (PROVIDER_STATUS.get(chain) or {}).get("pricingScope")
    return {
        "store": {
            "chain": chain,
            "name": store_row["name"] if store_row else None,
            "externalStoreId": store_row["external_store_id"] if store_row else None,
            "city": store_row["city"] if store_row else None,
        },
        "pricingScope": scope,
        "chain": chain,
        "totalCheckoutCost": result.get("totalCheckoutCost"),
        "coveragePercent": result.get("coveragePercent"),
        "realPriceItems": result.get("realPriceItems"),
        "estimatedItems": estimated,
        "missingItems": len(result.get("missingItems", [])),
        # The names too, not just the count - "2 saknas" leaves the user
        # guessing which two, and whether the total is missing something
        # expensive.
        "missingItemNames": [m.get("name") for m in result.get("missingItems", [])],
        "totalItems": result.get("totalItems"),
        "savings": savings,
        "dataAgeSeconds": age,
        "updatedAt": (time.time() - age) if age is not None else None,
        "comparable": (result.get("coveragePercent", 0) >= MIN_COVERAGE_FOR_COMPARISON
                       and result.get("realPriceItems", 0) > 0),
        "items": items,
    }


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
        store_row = _store_row_for(store, chain)
        if store_row is None:
            # Not an empty list - an empty list would price the week at 0 kr
            # and read as the cheapest shop in Sweden.
            return {"chain": chain, "error": "no_data_for_chain",
                    "store": {"chain": chain, "name": None},
                    "totalCheckoutCost": None, "coveragePercent": 0,
                    "realPriceItems": 0, "estimatedItems": 0,
                    "missingItems": len(items or []), "items": []}
        result = RecipePricingEngine(store).price_list(items, chain, store_row["id"], pantry=pantry)
        result["dataAgeSeconds"] = _chain_age_seconds(store, chain)
        return format_chain_result(result, store_row)
    finally:
        store.close()
