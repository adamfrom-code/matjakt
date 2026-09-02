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
    instead of after the TTL. Tömmer även motorns prisbild/ordindex: en
    partnerpaus som raderar priser eller en referensbackfill ändrar vad
    kunden ska se utan att någon körning avslutats."""
    with _LOCK:
        _CACHE.clear()
    from . import pricing
    pricing._PRICE_CACHE.clear()
    pricing._INDEX_CACHE.clear()


def open_store() -> GroceryStore:
    return GroceryStore(DB_PATH)


# Kampanjer är veckovaror: data äldre än så här visas inte som "aktiv
# kampanj" - hellre en tom rad än ett erbjudande som gick ut i förrgår.
MAX_CAMPAIGN_AGE_SECONDS = 3 * 24 * 3600


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
                           cp.campaign_price, cp.regular_price, cp.store_id
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
                      AND cp.fetched_at >= ?
                    ORDER BY 1.0 - (cp.campaign_price / cp.regular_price) DESC
                    LIMIT ?
                    """,
                    (chain, time.time() - MAX_CAMPAIGN_AGE_SECONDS, per_chain * 3),
                ).fetchall()
                seen, chain_deals = set(), []
                for row in rows:
                    # One deal per product NAME: the same discount on four
                    # pack sizes reads as filler, not as four offers.
                    if row["name"] in seen:
                        continue
                    seen.add(row["name"])
                    # Prishistoriken avgör om fyndet FAKTISKT är bra: lägsta
                    # pris vi själva noterat för produkten i denna butik
                    # senaste 30 dagarna. Historiken växer per natt - fältet
                    # betyder "lägsta vi sett", aldrig mer än vi vet.
                    lowest_seen = store.connection.execute(
                        """SELECT MIN(COALESCE(campaign_price, regular_price))
                           FROM grocery_price_history
                           WHERE product_id = ? AND store_id = ?
                             AND timestamp >= ?
                             AND COALESCE(campaign_price, regular_price) > 0""",
                        (row["product_id"], row["store_id"],
                         time.time() - 30 * 24 * 3600)).fetchone()[0]
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
                        "lowestSeen": lowest_seen,
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
            # Prisradens EGEN butik avgör kedjan - samma bugg och samma fix
            # som campaign_deals: en GTIN-delad produkt lät en Willys-hämtning
            # räknas som färskhet (och prisantal) för ICA, vilket både visade
            # osant färsk data för kund och släppte en stale kedja förbi
            # åldersspärren i jämförelsen.
            fetched = store.connection.execute(
                """
                SELECT MAX(cp.fetched_at) FROM grocery_current_prices cp
                JOIN grocery_stores st ON st.id = cp.store_id
                WHERE st.chain = ?
                """,
                (row["chain"],),
            ).fetchone()[0]
            prices = store.connection.execute(
                """
                SELECT COUNT(*) FROM grocery_current_prices cp
                JOIN grocery_stores st ON st.id = cp.store_id
                WHERE st.chain = ?
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
        "status": "working_via_primat", "recurringImportVerified": False,
        "pricingScope": "store", "collectable": True,
        "note": "Butiksspecifika priser via Primat-API:t (providers/primat.py) - "
                "bevisat olika priser mellan butiker. Direktvägen är stängd (WAF + "
                "villkor) och kringgås inte. Bakom RELEASED_CHAINS tills full "
                "katalog klarat kvalitetsgaten.",
    },
    "Coop": {
        "status": "working_via_primat", "recurringImportVerified": False,
        "pricingScope": "store", "collectable": True,
        "note": "Butiksscopade priser via Primat. Coops egen API-portal är låst till "
                "deras interna Azure AD - vi autentiserar oss inte med någon annans "
                "credential. Bakom RELEASED_CHAINS tills kvalitetsgaten passerats.",
    },
    "Lidl": {
        "status": "partial_via_primat", "recurringImportVerified": False,
        "pricingScope": "national", "collectable": True,
        "note": "Lidl publicerar inga egna per-produkt-priser; Primats Lidl-feed är "
                "rikspriser men liten (~200-400 varor) - för tunn för en hel matkorg. "
                "Bakom RELEASED_CHAINS; ingen Lidl-total ska fejkas fram.",
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


# Kedjor som är SLÄPPTA mot användare. ICA, Coop och Lidl har en färdig
# provider (Primat, se providers/primat.py) och kan importeras manuellt, men
# de får inte dyka upp i jämförelsen förrän de klarat samma kvalitetsgate som
# de tre befintliga: kanonisk matchning, paketmatte, fail-closed, full audit
# på full katalog. En partiell katalog i databasen får ALDRIG räcka för att
# en kedja ska börja kröna "Billigast" - därav uttrycklig lista i stället
# för "allt som råkar ha rader".
RELEASED_CHAINS = ("Willys", "Hemköp", "City Gross")


def priceable_chains() -> list[str]:
    """Chains that actually have data to price against - and that have been
    RELEASED (see RELEASED_CHAINS). A chain with no rows must not appear in
    a comparison at all - an empty chain would otherwise show up as the
    cheapest, at 0 kr - and an unreleased chain's half-imported catalog
    must not either."""
    return [entry["chain"] for entry in database_summary()["chains"]
            if entry["products"] > 0 and entry["chain"] in RELEASED_CHAINS]


def stores_near(latitude: float, longitude: float,
                max_km: float = 50.0, per_chain: int = 6) -> list[dict]:
    """Närliggande butiker ur det nationella registret, sorterade på avstånd.

    Helt ur egen databas - inga API-anrop per uppslag. max_km=50 är medvetet
    generöst: i glesbygd är fem mil till butiken verklighet, och en tom lista
    hjälper ingen. per_chain håller stadslistor hanterliga (Stockholm har
    hundratals butiker inom fem mil).

    Varje rad bär prisbar: kan den här butikens priser finnas hos Matjakt?
    NATIONAL-kedja = ja så fort kedjans katalog finns; STORE_SPECIFIC = bara
    om butikens egen katalog importerats (harPriser) eller åtminstone KAN
    importeras (active, dvs. full täckning hos källan). UI:t ska kunna visa
    skillnaden ärligt i stället för att låtsas att allt går att prissätta."""
    import math

    from .register import CHAIN_PRICING_SCOPE

    store = open_store()
    try:
        rows = store.connection.execute(
            """
            SELECT s.chain, s.external_store_id, s.name, s.city, s.postal_code,
                   s.address, s.latitude, s.longitude, s.active, s.pricing_scope,
                   EXISTS(SELECT 1 FROM grocery_current_prices cp
                          WHERE cp.store_id = s.id) AS har_priser
            FROM grocery_stores s
            WHERE s.latitude IS NOT NULL AND s.longitude IS NOT NULL
            """).fetchall()
        chains_with_catalog = set(priceable_chains())
    finally:
        store.close()

    lat_rad = math.radians(latitude)
    results: dict[str, list[dict]] = {}
    for row in rows:
        # Haversine räcker gott för butiksavstånd.
        d_lat = math.radians(row["latitude"] - latitude)
        d_lng = math.radians(row["longitude"] - longitude)
        a = (math.sin(d_lat / 2) ** 2
             + math.cos(lat_rad) * math.cos(math.radians(row["latitude"]))
             * math.sin(d_lng / 2) ** 2)
        km = 6371.0 * 2 * math.asin(math.sqrt(a))
        if km > max_km:
            continue
        chain = row["chain"]
        scope = row["pricing_scope"] or CHAIN_PRICING_SCOPE.get(chain)
        if scope == "NATIONAL":
            prisbar = chain in chains_with_catalog
        else:
            prisbar = bool(row["har_priser"]) or bool(row["active"])
        results.setdefault(chain, []).append({
            "kedja": chain,
            "namn": row["name"],
            "ort": row["city"],
            "adress": row["address"],
            "postnummer": row["postal_code"],
            "avstandKm": round(km, 1),
            "externalStoreId": row["external_store_id"],
            "pricingScope": scope,
            "prisbar": prisbar,
            "harPriser": bool(row["har_priser"]),
            "lat": row["latitude"], "lon": row["longitude"],
        })

    flattened = []
    for chain, chain_rows in results.items():
        chain_rows.sort(key=lambda r: r["avstandKm"])
        flattened.extend(chain_rows[:per_chain])
    flattened.sort(key=lambda r: r["avstandKm"])
    return flattened


def platform_status() -> dict:
    """Den nationella prisplattformens tillstånd i siffror - per kedja:
    butiker i registret, produkter, verifierade prisrader, referenspriser,
    senaste verifiering, senaste körning med gate. Inga priser, inga
    användare: får ligga öppet i /api/health."""
    store = open_store()
    try:
        chains = {}
        for row in store.connection.execute(
                "SELECT chain, COUNT(*) AS stores, SUM(CASE WHEN latitude IS NOT NULL THEN 1 ELSE 0 END) AS geo, "
                "SUM(CASE WHEN partner_status = 'ACTIVE' THEN 1 ELSE 0 END) AS partners "
                "FROM grocery_stores GROUP BY chain"):
            chains[row["chain"]] = {"stores": row["stores"], "storesWithCoordinates": row["geo"],
                                    "activePartnerStores": row["partners"]}
        for row in store.connection.execute(
                "SELECT chain, COUNT(DISTINCT product_id) AS products FROM grocery_product_external_ids GROUP BY chain"):
            chains.setdefault(row["chain"], {})["products"] = row["products"]
        for row in store.connection.execute(
                "SELECT s.chain, COUNT(*) AS prices, COUNT(DISTINCT cp.store_id) AS priced_stores, "
                "MAX(COALESCE(cp.verified_at, cp.fetched_at)) AS last_verified, "
                "SUM(CASE WHEN cp.source IS NOT NULL THEN 1 ELSE 0 END) AS with_source "
                "FROM grocery_current_prices cp JOIN grocery_stores s ON s.id = cp.store_id GROUP BY s.chain"):
            chains.setdefault(row["chain"], {}).update({
                "verifiedStorePrices": row["prices"], "storesWithPrices": row["priced_stores"],
                "lastVerifiedAt": row["last_verified"], "pricesWithSource": row["with_source"]})
        for row in store.connection.execute(
                "SELECT chain, COUNT(*) AS n, MAX(verified_at) AS last, MIN(source) AS sample_source "
                "FROM grocery_reference_prices GROUP BY chain"):
            chains.setdefault(row["chain"], {}).update({
                "referencePrices": row["n"], "referenceLastVerifiedAt": row["last"],
                "referenceSource": row["sample_source"]})
        for row in store.connection.execute(
                "SELECT chain, status, finished_at, gate_percent, published, prices_updated, gate_message "
                "FROM grocery_collector_runs WHERE id IN (SELECT MAX(id) FROM grocery_collector_runs GROUP BY chain)"):
            chains.setdefault(row["chain"], {})["lastRun"] = {
                "status": row["status"], "finishedAt": row["finished_at"],
                "gatePercent": row["gate_percent"], "published": row["published"],
                "pricesUpdated": row["prices_updated"], "message": row["gate_message"]}
        totals = {
            "stores": store.connection.execute("SELECT COUNT(*) FROM grocery_stores").fetchone()[0],
            "products": store.connection.execute("SELECT COUNT(*) FROM grocery_products").fetchone()[0],
            "verifiedStorePrices": store.connection.execute("SELECT COUNT(*) FROM grocery_current_prices").fetchone()[0],
            "referencePrices": store.connection.execute("SELECT COUNT(*) FROM grocery_reference_prices").fetchone()[0],
            "activePartners": store.connection.execute(
                "SELECT COUNT(*) FROM grocery_partners WHERE status = 'ACTIVE'").fetchone()[0],
        }
        return {"totals": totals, "chains": chains, "releasedChains": list(RELEASED_CHAINS),
                "active": totals["referencePrices"] > 0 and totals["stores"] >= 100}
    finally:
        store.close()


def store_register_count() -> int:
    """Hur många butiker registret håller - 0 betyder att registersynken
    aldrig körts i den här miljön (då får /api/stores falla tillbaka på den
    gamla uppslagsvägen)."""
    store = open_store()
    try:
        return store.connection.execute(
            "SELECT COUNT(*) FROM grocery_stores WHERE latitude IS NOT NULL"
        ).fetchone()[0]
    finally:
        store.close()


def _store_row_for(store: GroceryStore, chain: str, external_store_id: str | None = None):
    """Butiksraden att prissätta mot.

    Med external_store_id: exakt den butiken (användarens val). Utan: kedjans
    KATALOGBUTIK - raden som faktiskt bär priser. Det gamla "ORDER BY id
    LIMIT 1" var Gävle-låsningen i förklädnad: när det nationella
    butiksregistret fyllt tabellen med ~2 800 rader hade första-raden-per-id
    kunnat bli vilken prislösa registerbutik som helst."""
    if external_store_id is not None:
        return store.connection.execute(
            "SELECT id, name, external_store_id, city, pricing_scope FROM grocery_stores "
            "WHERE chain = ? AND external_store_id = ?", (chain, str(external_store_id))
        ).fetchone()
    return store.connection.execute(
        "SELECT id, name, external_store_id, city, pricing_scope FROM grocery_stores "
        "WHERE chain = ? "
        "ORDER BY EXISTS(SELECT 1 FROM grocery_current_prices cp WHERE cp.store_id = grocery_stores.id) DESC, id "
        "LIMIT 1", (chain,)
    ).fetchone()


def _store_has_prices(store: GroceryStore, store_row) -> bool:
    if store_row is None:
        return False
    return store.connection.execute(
        "SELECT EXISTS(SELECT 1 FROM grocery_current_prices WHERE store_id = ?)",
        (store_row["id"],)).fetchone()[0] == 1


class PricingTarget:
    """Vad en kedja ska prissättas mot för EN användare.

    store_id: butiken vars VERIFIERADE priser läggs ovanpå kedjans
              referenspriser i motorn (None = bara referenspriser).
    label_row: butiken som visas för användaren (None = kedjan som helhet,
              "ICA referenspris").
    reason:   None, eller varför kedjan inte kan prissättas alls."""
    __slots__ = ("store_id", "label_row", "reason")

    def __init__(self, store_id=None, label_row=None, reason=None):
        self.store_id, self.label_row, self.reason = store_id, label_row, reason


def resolve_pricing_store(store: GroceryStore, chain: str,
                          external_store_id: str | None = None) -> PricingTarget:
    """TVÅ PRISNIVÅER i upplösningen:

      VERIFIED_STORE_PRICE  användarens valda butik har egen importerad/
                            partnerlevererad katalog -> dess priser, färska,
                            går först (motorn lägger dem ovanpå referensen)
      REFERENCE_PRICE       annars kedjans referenspris - tydligt märkt,
                            aldrig ett påstående om just den butiken
      PRICE_MISSING         varken butikspris eller referens -> kedjan
                            prissätts inte alls. Ingen gissning.

    Utan användarval prissätts kedjan mot sin katalogbutik (den som bär
    priser) som förut - dess rader är verifierade för DEN butiken och
    kedjans referens för alla andra."""
    reference_available = (hasattr(store, "reference_price_count")
                           and store.reference_price_count(chain) > 0)
    catalog_row = _store_row_for(store, chain)
    catalog_has_prices = _store_has_prices(store, catalog_row)

    if external_store_id is None:
        if catalog_has_prices:
            return PricingTarget(catalog_row["id"], catalog_row, None)
        if reference_available:
            return PricingTarget(None, None, None)
        return PricingTarget(None, None, "no_data_for_chain")

    chosen = _store_row_for(store, chain, external_store_id)
    if chosen is None:
        return PricingTarget(None, None, "unknown_store")
    if _store_has_prices(store, chosen) or reference_available:
        return PricingTarget(chosen["id"], chosen, None)
    if catalog_has_prices:
        # Ingen referens publicerad ännu men kedjan har en prissatt katalog-
        # butik: kedjans pris finns, bara inte som referensrad. Etikettera
        # ärligt med användarens butik men prissätt ur katalogen - samma
        # beteende som nationella modellen hade före referenstabellen.
        from .register import CHAIN_PRICING_SCOPE
        if CHAIN_PRICING_SCOPE.get(chain) == "NATIONAL":
            return PricingTarget(catalog_row["id"], chosen, None)
    return PricingTarget(None, chosen, "no_data_for_store")


def _store_id_for(store: GroceryStore, chain: str):
    row = _store_row_for(store, chain)
    return row["id"] if row else None


def price_week(items: list[dict], chains: list[str] | None = None,
               pantry: dict | None = None,
               store_selection: dict[str, str] | None = None) -> dict:
    """Prices one week's summed ingredient list against every chain.

    items are already week-aggregated: [{"name","amount","unit"}, ...].
    store_selection ({kedja: external_store_id}) är användarens valda
    butiker: nationellt prissatta kedjor etiketteras med den valda butiken,
    butiksspecifika kedjor prissätts BARA om just den butikens katalog är
    importerad - annars rapporteras kedjan ärligt som otillgänglig i stället
    för att visa en annan butiks priser. Returns one result per chain plus a
    comparison that is allowed to stay undecided - see compare_chains."""
    available = priceable_chains()
    chains = [chain for chain in (chains or available) if chain in available]
    store_selection = {str(k): str(v) for k, v in (store_selection or {}).items()}

    key = None
    try:
        # Butiksvalet MÅSTE in i cachenyckeln - utan det delade en
        # Stockholmsanvändares jämförelse cache med en Gävleanvändares.
        key = repr((sorted((i.get("name"), i.get("amount"), i.get("unit")) for i in items),
                    tuple(sorted(chains)), tuple(sorted((pantry or {}).items())),
                    tuple(sorted(store_selection.items()))))
    except TypeError:
        key = None  # unhashable input - price it, just don't cache it
    if key:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    store = open_store()
    unavailable = []
    try:
        engine = RecipePricingEngine(store)
        raw_results, store_rows = [], {}
        for chain in chains:
            target = resolve_pricing_store(store, chain, store_selection.get(chain))
            if target.reason is not None:
                if target.reason == "no_data_for_store" and target.label_row is not None:
                    # Användarens butik finns men varken butikspris eller
                    # referenspris: säg det, hitta inte på en total.
                    unavailable.append({
                        "chain": chain, "reason": target.reason,
                        "storeName": target.label_row["name"],
                        "externalStoreId": target.label_row["external_store_id"]})
                continue
            store_rows[chain] = target.label_row
            result = engine.price_list(items, chain, target.store_id, pantry=pantry)
            result["dataAgeSeconds"] = _chain_age_seconds(store, chain, target.store_id)
            raw_results.append(result)

        # Anonym partnerstatistik: butiken jämfördes. Räknas per butik och
        # dag, aldrig per användare - och ALDRIG med i rankingen.
        from . import partners as partner_api
        for chain, label_row in store_rows.items():
            if label_row is not None:
                partner_api.record_stat(store, label_row["id"], "store_compared")
    finally:
        store.close()

    # The comparison is decided on the raw results, THEN handed to the
    # formatter - so a chain's "savings" can never be a number the comparison
    # itself refused to stand behind. Partnerstatus, betalning och prisnivå
    # ingår inte i underlaget: bara totaler och täckning.
    comparison = compare_chains(raw_results)
    comparison.update(_comparison_basis(raw_results, comparison))
    if comparison.get("cheapestChain"):
        crowned = store_rows.get(comparison["cheapestChain"])
        if crowned is not None:
            stat_store = open_store()
            try:
                from . import partners as partner_api
                partner_api.record_stat(stat_store, crowned["id"], "store_cheapest")
            finally:
                stat_store.close()
    results = [format_chain_result(result, store_rows.get(result["chain"]), comparison)
               for result in raw_results]
    payload = {"results": results, "comparison": comparison,
               "unavailableChains": unavailable}
    if key:
        _cache_set(key, payload)
    return payload


BASIS_LABELS = {
    "verified": "Billigast bland dina valda butiker",
    "reference": "Billigast enligt aktuella referenspriser",
    "mixed": "Billigast bland dina valda butiker (delvis referenspriser)",
}


def _comparison_basis(raw_results: list[dict], comparison: dict) -> dict:
    """Vad kröningen vilar på - så konsumenten förstår skillnaden mellan
    referenspris och verifierat lokalt pris utan att behöva läsa fältnamn."""
    compared = [r for r in raw_results if r.get("pricingBasis")]
    if not compared:
        return {"basis": None, "basisLabel": None}
    bases = {r["pricingBasis"] for r in compared}
    if bases == {"VERIFIED"}:
        basis = "verified"
    elif bases == {"REFERENCE"}:
        basis = "reference"
    else:
        basis = "mixed"
    return {"basis": basis, "basisLabel": BASIS_LABELS[basis] if comparison.get("cheapestChain") else None}


def _chain_age_seconds(store: GroceryStore, chain: str, store_id: int | None = None):
    """Färskheten på det som faktiskt prissattes: butikens senaste verifiering
    om en butik är vald, annars kedjans referens- eller katalogpriser."""
    stamps = []
    if store_id is not None:
        row = store.connection.execute(
            "SELECT MAX(COALESCE(cp.verified_at, cp.fetched_at)) FROM grocery_current_prices cp "
            "WHERE cp.store_id = ?", (store_id,)).fetchone()
        if row and row[0]:
            stamps.append(row[0])
    row = store.connection.execute(
        "SELECT MAX(verified_at) FROM grocery_reference_prices WHERE chain = ?", (chain,)).fetchone()
    if row and row[0]:
        stamps.append(row[0])
    if not stamps:
        # st.chain, inte external_ids: prisradens egen butik avgör vems ålder
        # det är (se database_summary för hela historien).
        row = store.connection.execute(
            """
            SELECT MAX(cp.fetched_at) FROM grocery_current_prices cp
            JOIN grocery_stores st ON st.id = cp.store_id
            WHERE st.chain = ?
            """,
            (chain,),
        ).fetchone()
        if row and row[0]:
            stamps.append(row[0])
    return (time.time() - max(stamps)) if stamps else None


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
            # Prisnivån per rad: verifierat i butiken eller kedjans referens.
            "priceTier": match.get("priceTier"),
            "verifiedAt": match.get("verifiedAt"),
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
    basis = result.get("pricingBasis")
    # Konsumentens etikett - aldrig "centrallagerpris", aldrig ett butiks-
    # påstående utan verifiering.
    if basis == "VERIFIED":
        price_label = "Verifierat lokalt pris"
    elif basis == "MIXED":
        price_label = "Delvis verifierade lokala priser"
    elif basis == "REFERENCE":
        price_label = f"{chain} referenspris"
    else:
        price_label = None
    return {
        "store": {
            "chain": chain,
            "name": store_row["name"] if store_row else None,
            "externalStoreId": store_row["external_store_id"] if store_row else None,
            "city": store_row["city"] if store_row else None,
        },
        "pricingScope": scope,
        "pricingBasis": basis,
        "priceTiers": result.get("priceTiers"),
        "priceLabel": price_label,
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
        # SAMMA definition som compare_chains använder för kröningen - även
        # ålderskravet. Docstringen lovar att konsumenter läser denna flagga
        # i stället för att härleda själva; två olika definitioner gjorde
        # löftet till en fälla (frontend byggde egen billigast-beräkning på
        # kedjor som kröningen just diskvalificerat för ålder).
        "comparable": (result.get("coveragePercent", 0) >= MIN_COVERAGE_FOR_COMPARISON
                       and result.get("realPriceItems", 0) > 0
                       and (age is None or age <= MAX_AGE_SECONDS_FOR_COMPARISON)),
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
    # Delad förstaplats: att kröna den som råkar ligga först i listan vore
    # en osann exklusivitetsclaim av exakt den sort blocket ovan stoppar.
    if len(totals) > 1 and cheapest["totalCheckoutCost"] == totals[1]["totalCheckoutCost"]:
        return {"cheapestChain": None, "savings": None, "comparedChains": len(comparable),
                "reason": "tied_cheapest"}

    return {
        "cheapestChain": cheapest["chain"],
        "cheapestTotal": cheapest["totalCheckoutCost"],
        "priciestChain": priciest["chain"],
        "priciestTotal": priciest["totalCheckoutCost"],
        "savings": round(priciest["totalCheckoutCost"] - cheapest["totalCheckoutCost"], 2),
        "comparedChains": len(comparable),
        "reason": None,
    }


def shopping_list(items: list[dict], chain: str, pantry: dict | None = None,
                  external_store_id: str | None = None) -> dict:
    """One chain's store-specific shopping list: the real products to put in
    the basket, with image, pack size, package count and price - plus what we
    could NOT price, which stays visible rather than quietly disappearing.

    external_store_id är användarens valda butik - samma upplösningsregler
    som price_week (nationell katalog etiketteras om, butiksspecifik kedja
    vägrar hellre än att visa fel butiks priser)."""
    store = open_store()
    try:
        target = resolve_pricing_store(store, chain, external_store_id)
        label_row = target.label_row
        if target.reason is not None:
            # Not an empty list - an empty list would price the week at 0 kr
            # and read as the cheapest shop in Sweden.
            return {"chain": chain, "error": target.reason,
                    "store": {"chain": chain,
                              "name": label_row["name"] if label_row else None,
                              "externalStoreId": label_row["external_store_id"] if label_row else None,
                              "city": label_row["city"] if label_row else None},
                    "totalCheckoutCost": None, "coveragePercent": 0,
                    "realPriceItems": 0, "estimatedItems": 0,
                    "missingItems": len(items or []), "items": []}
        result = RecipePricingEngine(store).price_list(items, chain, target.store_id, pantry=pantry)
        result["dataAgeSeconds"] = _chain_age_seconds(store, chain, target.store_id)
        return format_chain_result(result, label_row)
    finally:
        store.close()
