"""Client for the Primat API (https://primat.nu/api) - a third-party service
that tracks daily prices across ICA, Coop, Willys, Hemkop, Lidl and City Gross
and exposes them over a plain JSON REST API. Unlike scraping each store's own
website with headless Chromium (slow, resource-heavy, prone to timeouts - see
api_server.py's get_shared_browser), this is a fast, ordinary HTTPS request -
no browser involved.

Verified directly against the real API before building this (2026-08-29):
commercial use is explicitly permitted in Primat's terms, data/images may be
cached, and the free/demo tier requires visible "Prisdata fran primat.nu"
attribution with a link wherever the data is shown (see ATTRIBUTION below and
frontend/app/app.js's use of it). Reselling the data itself as a dataset/mirror
API is not permitted - Matjakt only ever uses it to price its own shopping
list, never re-exposes Primat's data as a standalone feed.

Primat is explicitly still under development ("Strukturen, datat och
prismodellen kan komma att andras" - their own words). This client is written
so a Primat outage or shape change degrades gracefully: every function raises
PrimatError on any failure, and callers (api_server.py) are expected to catch
that and fall back to the existing store-scraping path - Matjakt must never
depend on Primat always being up.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://primat.nu/api/v3"
ATTRIBUTION = {"text": "Prisdata från primat.nu", "url": "https://primat.nu"}
# Python's urllib default User-Agent ("Python-urllib/3.x") gets blocked
# outright by Primat's Cloudflare bot protection (confirmed directly: the
# exact same authenticated request succeeds with this header and fails with
# error code 1010 - "browser signature blocked" - without it). This isn't
# working around a restriction Primat wants enforced against API clients -
# their whole product is a REST API for exactly this kind of consumption,
# and Matjakt has valid, authorized credentials for it. It's just identifying
# honestly as what it is instead of tripping a default script-blocking rule.
USER_AGENT = "Matjakt/1.0 (+https://adamfrom-code.github.io/matjakt)"

# Matjakt's own chain names (used throughout api_server.py/frontend) to
# Primat's lowercase, diacritic-free chain keys, and back. Primat also covers
# Lidl and City Gross, which Matjakt doesn't have a chain for yet - left out
# of this mapping on purpose so those rows are simply skipped wherever this
# is used to filter/label results, rather than needing a "does the rest of
# the app actually support this chain" check at every call site.
CHAIN_TO_PRIMAT = {"Willys": "willys", "Coop": "coop", "Hemköp": "hemkop", "ICA": "ica"}
PRIMAT_TO_CHAIN = {value: key for key, value in CHAIN_TO_PRIMAT.items()}


class PrimatError(Exception):
    """Raised for any Primat failure - network error, non-2xx response,
    quota/rate-limit, or an unexpected response shape. Callers must treat
    this as "Primat has no answer right now" and fall back accordingly,
    never as a reason to fail the whole request."""


def _request(method, path, api_key=None, params=None, body=None):
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    if data:
        req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error).get("error", {}).get("message", str(error))
        except Exception:
            detail = str(error)
        raise PrimatError(f"{error.code}: {detail}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise PrimatError(str(error))


def _resolve_raw(zip_code, api_key=None):
    path = "/stores/resolve" if api_key else "/demo/stores/resolve"
    return _request("GET", path, api_key=api_key, params={"postcode": zip_code})


def resolve_stores(zip_code, api_key=None):
    """Returns {primat_chain: "chain:store_id"} for a Swedish postcode, built
    from Primat's own default_selection (their "nearest full-catalog door per
    chain" pick - no need to reimplement distance sorting here). Not every
    chain necessarily has a nearby store, so a chain can be absent from the
    result (callers must handle that as "no Primat coverage here for this
    chain", not an error)."""
    result = _resolve_raw(zip_code, api_key=api_key)
    return {key.split(":", 1)[0]: key for key in result.get("default_selection", [])}


def nearby_stores(zip_code, api_key=None):
    """Returns Primat's full ranked nearby-store list (not just the one pick
    per chain that resolve_stores gives), mapped to Matjakt's own
    {"kedja","namn","ort","avstandKm","primatKey"} shape - the same shape
    nearby_stores() in api_server.py already produces from
    scraping/fetch_axfood_stores (plus primatKey, which only a Primat-sourced
    branch has), so this is a drop-in alternative source. Chains Matjakt
    doesn't have yet (Lidl, City Gross) are silently skipped rather than
    passed through - see PRIMAT_TO_CHAIN. Distance (km) comes straight from
    Primat; no need to geocode or haversine anything here.

    primatKey ("chain:store_id", e.g. "coop:206401") is each store's own
    identity in Primat's system - carried through so a caller can pin
    product searches to this exact door (see fetch_from_primat's store_key)
    instead of always getting whichever store primat_store_scope's default
    resolution would have picked for the chain."""
    result = _resolve_raw(zip_code, api_key=api_key)
    stores = []
    for store in result.get("stores", []):
        chain = PRIMAT_TO_CHAIN.get(store.get("chain"))
        if not chain:
            continue
        stores.append({"kedja": chain, "namn": store.get("name") or "", "ort": store.get("city") or "", "avstandKm": store.get("km"), "primatKey": store.get("key") or ""})
    return stores


def account_status(api_key):
    """Primat's own account-usage endpoint (GET /me) - plan, daily row
    budget, rows used so far today, when it resets. Requires a real key (no
    demo-tier equivalent exists for this), and is for internal/admin
    visibility only - see api_server's admin-gated endpoint that calls this;
    the key itself must never be included in what that endpoint returns to
    a client."""
    return _request("GET", "/me", api_key=api_key)


def search_products(query, stores=None, api_key=None):
    """stores: comma-separated "chain:store_id" list (e.g. from
    resolve_stores) to scope results to specific stores; without it, Primat
    returns one row per product at that product's cheapest store nationally,
    which isn't what a specific shopping list needs. Returns the raw list of
    Primat product rows (see PRODUCT SHAPE in the module docstring)."""
    path = "/products" if api_key else "/demo/products"
    result = _request("GET", path, api_key=api_key, params={"q": query, "stores": stores})
    return result.get("data", [])


def to_matjakt_product(primat_product, chain, query):
    """Maps a Primat product row onto the exact same dict shape
    scrape_products()/parse_products() already produce, so every existing
    consumer (best_match, cached_products/store_products, annotate_updated,
    the frontend's rendering) needs zero changes - Primat is just another
    source of the same shape, per run_on_scrape_thread's docstring pattern of
    keeping call sites source-agnostic.

    pris_kr uses "effective" (Primat's already-computed best current price a
    shopper would actually pay - regular price, or a cheaper offer/multiprice
    if one applies), not "regular" - showing the un-discounted price when a
    real discount applies would itself be a kind of dishonesty the rest of
    this app has been careful to avoid.

    Primat's own "confirmed_at" (when THEY last verified this price, not when
    Matjakt happened to ask) is preserved as "uppdaterad" so store_products'
    persisted timestamp reflects the price's real-world age, consistent with
    cached_products' cache window.

    "kategori" is Primat's own breadcrumb-style department path (e.g. "Frukt
    & Grönsaker > Grönsaker > Paprika") - scraped products never have this
    (Willys/Coop/Hemköp/ICA's own pages don't expose it), so it's "" for
    those, not missing - best_match() only applies its category check when
    this is non-empty."""
    prices = primat_product.get("prices") or {}
    offer = prices.get("offer")
    brand = primat_product.get("brand") or ""
    package = primat_product.get("package") or ""
    return {
        "kedja": chain,
        "produktnamn": primat_product.get("name") or query,
        "marke_och_storlek": " ".join(part for part in (brand, package) if part),
        "bild": "",  # Primat doesn't provide product images - see Open Food Facts fallback
        "pris_kr": prices.get("effective"),
        "kategori": primat_product.get("category") or "",
        "storlek": package,
        "lager": bool(primat_product.get("available", True)),
        "url": (primat_product.get("urls") or {}).get("source") or (primat_product.get("urls") or {}).get("primat") or "",
        "sokning": query,
        "kampanj": {"text": offer["label"], "ordinariePris": prices.get("regular"), "slutdatum": offer.get("valid_until")} if offer else None,
        "gtin": primat_product.get("gtin"),
        "kalla": "primat",
    }
