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

from .pricing import RecipePricingEngine, comparability_reasons
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
from ..secret_scrub import scrub

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


# O15: FYRA OLIKA SAKER SOM ALLA HETER "BUTIKER".
#
# Ett register med tusentals adresser är inte tusentals prissatta butiker.
# De fyra talen hålls isär, och varje svar bär källa, mättid och gräns så
# att den som läser "41 butiker" vet vilket av de fyra talen det är.
#
#   iRegistret       rader i grocery_stores för kedjan
#   aktiva           active = 1 - valda/aktiverade för import
#   färska           aktiva med minst ett butikspris yngre än
#                    MAX_STORE_PRICE_AGE_SECONDS (samma gräns som
#                    prismotorn själv vägrar servera äldre priser vid)
#   kundtillgängliga färska OCH kedjan i RELEASED_CHAINS - en färsk butik i
#                    en osläppt kedja når ingen kund
#
# Ingen automatisk publicering följer av talen: RELEASED_CHAINS är orörd.
def store_counts(store, chain: str, now: float | None = None) -> dict:
    from .pricing import MAX_STORE_PRICE_AGE_SECONDS
    now = time.time() if now is None else now
    con = store.connection
    i_registret = con.execute(
        "SELECT COUNT(*) FROM grocery_stores WHERE chain = ?", (chain,)).fetchone()[0]
    aktiva = con.execute(
        "SELECT COUNT(*) FROM grocery_stores WHERE chain = ? AND active = 1", (chain,)).fetchone()[0]
    butiker_med_farskt = con.execute(
        """SELECT COUNT(DISTINCT st.id) FROM grocery_stores st
           JOIN grocery_current_prices cp ON cp.store_id = st.id
           WHERE st.chain = ? AND st.active = 1
             AND COALESCE(cp.verified_at, cp.fetched_at) >= ?""",
        (chain, now - MAX_STORE_PRICE_AGE_SECONDS)).fetchone()[0]
    # SAMMA REGEL SOM SERVERINGEN (nearby_stores / PricingTarget): en
    # riksprissatt kedja är prisbar i ALLA aktiva butiker så snart katalogen
    # har ett färskt pris - priset sitter på en katalogbutik men gäller
    # överallt. Bara en butiksspecifik kedja räknas butik för butik. Utan
    # den här skillnaden stod produktionen med "255 aktiva · 1 färsk" för
    # Willys, vilket var sant om prisRADER och falskt om butiker.
    from .register import CHAIN_PRICING_SCOPE
    scope = CHAIN_PRICING_SCOPE.get(chain, "STORE_SPECIFIC")
    farska = (aktiva if butiker_med_farskt else 0) if scope == "NATIONAL" else butiker_med_farskt
    slappt = chain in RELEASED_CHAINS
    return {
        "iRegistret": i_registret,
        "aktiva": aktiva,
        "farska": farska,
        "kundtillgangliga": farska if slappt else 0,
        "prisScope": scope,
        "butikerMedEgnaFarskaPriser": butiker_med_farskt,
        "kalla": "grocery_stores + grocery_current_prices; regel: register.CHAIN_PRICING_SCOPE",
        "mattVid": now,
        "farskGrans": f"pris yngre än {MAX_STORE_PRICE_AGE_SECONDS // 86400} dygn",
        "slapptKedja": slappt,
    }


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
                # O15: fyra tal som alla heter "butiker", hållna isär.
                "butiker": store_counts(store, row["chain"]),
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


# Hur gammal en lyckad import får bli innan kedjan räknas som inaktuell.
# Nattjobben ligger 02-06:30 och kör dagligen, så 36 timmar rymmer en missad
# natt utan att larma - men inte två. Kortare och en enda hicka larmar i
# onödan; längre och en kedja kan tyna bort en hel helg obemärkt.
CHAIN_STALE_AFTER_SECONDS = 36 * 3600


def chain_health(entry: dict, now: float = None) -> dict:
    """En sammanfattande status per kedja, härledd ur data som redan finns.

    Poängen är att ägaren ska kunna läsa EN rad i stället för att jämföra
    produktantal mot tidsstämplar mot releaselistan i huvudet. Fälten under
    den (products, lastRun, ageSeconds ...) står kvar oförändrade - det här
    lägger bara en slutsats ovanpå dem.

    Tillstånden, i den ordning de prövas:
      limited            providern kan aldrig ge en hel korg (Lidl: ~200-400
                         rikspriser). Inte ett fel, men får aldrig läsas som
                         "snart klar".
      never_imported     ingen körning alls har gjorts.
      failed             senaste körningen misslyckades OCH ingen tidigare
                         lyckad finns att falla tillbaka på.
      stale              det finns godkänd data, men den senaste lyckade
                         importen är äldre än CHAIN_STALE_AFTER_SECONDS.
                         Användarna får fortfarande last-good - det här är
                         ett driftlarm, inte ett kundfel.
      healthy            släppt mot användare, färsk och frisk. Det här är
                         det enda tillståndet som betyder "inget att göra".
      ready_for_release  har färsk data som klarat de tekniska kraven, men
                         kedjan är INTE publik. Kräver ett uttryckligt
                         beslut; en lyckad import gör aldrig en kedja
                         släppt av sig själv (se RELEASED_CHAINS).

    "released" är en FLAGGA, inte ett tillstånd - en släppt kedja kan mycket
    väl vara stale eller failed. Att blanda ihop dem skulle dölja precis de
    fallen.
    """
    now = now if now is not None else time.time()
    lyckad = entry.get("lastSuccessfulRun") or {}
    senaste = entry.get("lastRun") or {}
    klar_vid = lyckad.get("finishedAt")
    ålder = (now - klar_vid) if klar_vid else None
    resultat = {
        "ageHours": round(ålder / 3600, 1) if ålder is not None else None,
        "lastAttempt": senaste.get("finishedAt") or senaste.get("startedAt"),
        "lastSuccess": klar_vid,
        "released": entry.get("chain") in RELEASED_CHAINS,
    }
    if str(entry.get("status", "")).startswith("partial"):
        return {**resultat, "status": "limited",
                "reason": "Providern har för lite data för en hel matkasse"}
    if not klar_vid:
        if senaste and senaste.get("status") != "success":
            return {**resultat, "status": "failed",
                    "reason": scrub(senaste.get("errorMessage")) or "Importen misslyckades"}
        return {**resultat, "status": "never_imported",
                "reason": "Ingen import har körts än"}
    if ålder is not None and ålder > CHAIN_STALE_AFTER_SECONDS:
        return {**resultat, "status": "stale",
                "reason": f"Senaste lyckade import är {resultat['ageHours']} timmar gammal"}
    if resultat["released"]:
        return {**resultat, "status": "healthy", "reason": None}
    return {**resultat, "status": "ready_for_release",
            "reason": "Har färsk data men är inte släppt - kräver uttryckligt beslut"}


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
                    "pricesUpdated": row["prices_updated"],
                    # Skrubbas ÄVEN vid utskick: rader som lagrades innan
                    # lager 1 fanns ligger kvar, och en ny kodväg som glömmer
                    # skrubba före lagring ska ändå inte kunna exponera något.
                    "errorMessage": scrub(row["error_message"]),
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
            "butiker": held.get("butiker"),
            "withImage": held.get("withImage", 0),
            "categoryPercent": held.get("categoryPercent", 0),
            "gtinPercent": held.get("gtinPercent", 0),
            "imagePercent": held.get("imagePercent", 0),
            "ageSeconds": held.get("ageSeconds"),
            "lastRun": runs.get(chain),
            "lastSuccessfulRun": successes.get(chain),
        })
    # Slutsatsen läggs på efter att raden är komplett, så chain_health() ser
    # samma fält som panelen visar - ingen risk att de säger olika saker.
    for entry in panel:
        entry["health"] = chain_health(entry)
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


_PLATFORM_STATUS_CACHE = {"at": 0.0, "value": None}
PLATFORM_STATUS_TTL_SECONDS = 60


def platform_status() -> dict:
    """Den nationella prisplattformens tillstånd i siffror - per kedja:
    butiker i registret, produkter, verifierade prisrader, referenspriser,
    senaste verifiering, senaste körning med gate. Inga priser, inga
    användare: får ligga öppet i /api/health. Cachad en minut i processen:
    /api/health är Renders hälsokontroll och får inte kosta en fråga per
    tabell varje gång."""
    cached = _PLATFORM_STATUS_CACHE
    if cached["value"] is not None and time.time() - cached["at"] < PLATFORM_STATUS_TTL_SECONDS:
        return cached["value"]
    value = _platform_status_uncached()
    cached["at"], cached["value"] = time.time(), value
    return value


def _platform_status_uncached() -> dict:
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
        dabas = {row[0] or "none": row[1] for row in store.connection.execute(
            "SELECT dabas_status, COUNT(*) FROM grocery_products WHERE gtin IS NOT NULL GROUP BY dabas_status")}
        package = {row[0] or "provider_or_none": row[1] for row in store.connection.execute(
            "SELECT package_confidence, COUNT(*) FROM grocery_products GROUP BY package_confidence")}
        try:
            from .enrichment import coverage_report
            dabas_coverage = coverage_report(store)
        except Exception:
            dabas_coverage = None
        totals = {
            "dabas": dabas,
            "dabasCoverage": dabas_coverage,
            "packageConfidence": package,
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
    from .register import CHAIN_PRICING_SCOPE
    scope = CHAIN_PRICING_SCOPE.get(chain)
    if _store_has_prices(store, chosen):
        return PricingTarget(chosen["id"], chosen, None)
    if reference_available:
        if scope == "NATIONAL":
            # Nationellt pris: referensen gäller i användarens butik - butiken
            # får stå på etiketten (Willys Älvsjö visar Willys pris, sant).
            return PricingTarget(chosen["id"], chosen, None)
        # BUTIKSSPECIFIK kedja utan egen katalog för just den här butiken:
        # kedjans referenspris, men ALDRIG under butikens namn. En
        # Malmöanvändare ser "City Gross referenspris", inte "City Gross
        # Malmö" med Gävles siffror - tills Malmös katalog finns.
        return PricingTarget(None, None, None)
    if catalog_has_prices and scope == "NATIONAL":
        # Ingen referens publicerad ännu men kedjan har en prissatt katalog-
        # butik: kedjans pris finns, bara inte som referensrad. Etikettera
        # ärligt med användarens butik men prissätt ur katalogen - samma
        # beteende som nationella modellen hade före referenstabellen.
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
            result["dataAgeSeconds"] = _age_for_result(result, store, chain, target.store_id)
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


def _result_age_seconds(result, now: float = None):
    """Åldern på det ÄLDSTA pris som FAKTISKT användes i den här kassen.

    Det här ersätter en MAX()-fråga mot hela butiken, som svarade på en helt
    annan fråga: "när uppdaterades något i den här butiken senast?" En enda
    färsk prisrad - på vilken vara som helst, även en som inte ingick i
    kassen - nollställde åldern för en kasse byggd på veckogamla priser.

    Fel åt fel håll, dessutom. Åldern går in i compare_chains age-filter
    (MAX_AGE_SECONDS_FOR_COMPARISON), så en kedja som borde diskvalificerats
    för gammal data kunde krönas billigast för att en orelaterad rad var ny.

    ÄLDSTA, inte nyaste: en kasse är inte färskare än sin äldsta prisrad.
    Bara rader som räknades in i totalen vägs - en rad utan totalCost
    påverkar inte summan och dess ålder säger inget om den.

    verifiedAt före fetchedAt: när priset senast BEKRÄFTADES i butiken är
    det som betyder något, inte när vi råkade hämta hem raden.
    """
    now = now if now is not None else time.time()
    stamps = []
    for match in result.get("matchedItems") or []:
        if match.get("totalCost") is None:
            continue
        stamp = match.get("verifiedAt") or match.get("fetchedAt")
        if stamp:
            stamps.append(stamp)
    return (now - min(stamps)) if stamps else None


def _age_for_result(result, store: GroceryStore, chain: str, store_id: int | None = None):
    """Kassans ålder, med kedjefrågan bara som sista utväg.

    Har kassan prissatta rader är deras egen ålder det enda ärliga svaret.
    Saknas rader helt finns ingen kasse att åldersbedöma, och då säger
    kedjans tidsstämpel åtminstone något om butiken - en sådan kasse har
    ändå realPriceItems = 0 och kan aldrig krönas billigast."""
    from_rows = _result_age_seconds(result)
    if from_rows is not None:
        return from_rows
    return _chain_age_seconds(store, chain, store_id)


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
            "gtin": match.get("gtin"),
            "productName": match.get("productName"),
            "brand": match.get("brand"),
            "imageUrl": match.get("imageUrl"),
            "category": match.get("category"),
            "packageSize": match.get("packageSize"),
            "packageSource": match.get("packageSource"),
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
    reasons = comparability_reasons(
        coverage_percent=result.get("coveragePercent", 0),
        real_price_items=result.get("realPriceItems", 0),
        age_seconds=age,
        min_coverage=MIN_COVERAGE_FOR_COMPARISON,
        max_age_seconds=MAX_AGE_SECONDS_FOR_COMPARISON)
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
        "comparable": not reasons,
        # VARFÖR den inte är jämförbar. Flaggan ovan slog ihop täckning och
        # ålder, och UI:t hade därför bara en mening att säga - "För få av
        # varorna har aktuellt pris" - som är rätt text i hälften av fallen
        # och fel i resten. Koderna hålls isär hela vägen ut.
        "comparableReasons": reasons,
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
      2b. Chains that priced DIFFERENT items. The threshold alone let a
         chain at 85 % be crowned over one at 100 %: its total was lower
         because three items were missing, and those three could cost more
         than the "savings". Two totals compare only when they answer the
         same question.
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

    # SAMMA VAROR, ANNARS INGEN KRÖNING.
    #
    # Täckningströskeln ensam räcker inte. En kedja på 85 % (17 av 20 varor)
    # klarade filtret ovan och kunde krönas mot en kedja på 100 % - men dess
    # total är lägre för att tre varor SAKNAS, inte för att butiken är
    # billig. De tre kunde kosta mer än den utlovade besparingen, och då är
    # "du sparar 50 kr" ett falskt besked om användarens pengar.
    #
    # Två totaler är jämförbara först när de svarar på samma fråga. Vi kräver
    # därför att kedjorna saknar exakt samma varor - normalfallet är att de
    # inte saknar några alls. Skiljer de sig returneras totalerna ändå (de är
    # sanna var för sig) men utan kröning, och med vilka varor som skiljer
    # så gränssnittet kan säga varför i stället för att bara tiga.
    saknade = {r["chain"]: frozenset(r.get("missingItemNames") or ()) for r in comparable}
    if len(set(saknade.values())) > 1:
        skiljer = sorted(set().union(*saknade.values()))
        return {"cheapestChain": None, "savings": None, "comparedChains": len(comparable),
                "reason": "different_baskets", "differingItems": skiljer}

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
        result["dataAgeSeconds"] = _age_for_result(result, store, chain, target.store_id)
        return format_chain_result(result, label_row)
    finally:
        store.close()
