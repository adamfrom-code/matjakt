"""Local product API for Matjakt.

The store websites do not publish a stable public API. This service uses
Playwright against their public shopping pages and returns one normalized
shape to the frontend. Keep request volume low and check each store's terms
before deploying this publicly.
"""

import concurrent.futures
import hmac
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright
from services.accounts import AccountError, AccountStore
from services.billing import StripeError, cancel_subscription, create_checkout_session, create_customer, create_portal_session, parse_event, verify_webhook_signature
from services.email import MailError, send_email
from services.accounts import ratelimit  # noqa: E402
from services.grocery import api as grocery_api  # noqa: E402
from services.grocery import importer as grocery_importer  # noqa: E402
from services.grocery.scheduler import SCHEDULER as GROCERY_SCHEDULER  # noqa: E402
from services.pricing import CHAIN_TO_PRIMAT, KeyValueCacheStore, OpenFoodFactsError, PRIMAT_ATTRIBUTION, PriceCacheStore, PrimatError, image_url_for_gtin, nearby_stores as primat_nearby_stores, primat_account_status, resolve_stores as primat_resolve_stores, search_products as primat_search_products, to_matjakt_product as primat_to_matjakt_product
from services.recipe_providers import RecipeService, TheMealDbProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("matjakt.api")


def load_dotenv(path):
    """Minimal .env loader: fills unset env vars only, never overrides values
    already set by the shell. Avoids adding python-dotenv as a dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

HOST = os.environ.get("MATJAKT_HOST", "127.0.0.1")
PORT = int(os.environ.get("MATJAKT_PORT", os.environ.get("PORT", "8000")))
def _parse_allowed_origins(raw):
    """MATJAKT_FRONTEND_ORIGIN may hold one origin or several comma-separated
    ones (used during the matjakt.store domain migration, so both the new
    domain and the old GitHub Pages origin stay allowed at once)."""
    origins = [o.strip().rstrip("/") for o in raw.split(",")]
    return tuple(o for o in origins if o)


ALLOWED_ORIGINS = _parse_allowed_origins(os.environ.get("MATJAKT_FRONTEND_ORIGIN", "http://localhost:5500"))
# Back-compat single-value name, kept as the default/fallback CORS origin
# (e.g. for non-browser requests with no Origin header).
ALLOWED_ORIGIN = ALLOWED_ORIGINS[0]
# Where Stripe should redirect the browser back to after checkout/the billing portal.
# Distinct from ALLOWED_ORIGIN (used for the CORS header, which must be a bare origin
# with no path) because GitHub Pages serves this app from a project subpath
# (.../matjakt/), not the origin root.
APP_URL = os.environ.get("MATJAKT_APP_URL", ALLOWED_ORIGIN).rstrip("/")
# Ordinary product prices: fresh for 6h, matching how often a Swedish
# grocery chain actually changes shelf prices (campaigns are handled
# separately below, at a much shorter TTL, since those genuinely can start
# or end within hours).
CACHE_TTL_SECONDS = 900
CACHE_MAX_AGE_SECONDS = 6 * 3600
ICA_STORE_FAILURE_TTL_SECONDS = 300
ICA_STORE_SUCCESS_TTL_SECONDS = 24 * 3600
# Each worker thread keeps its own persistent Chromium process alive (see
# get_shared_browser) - this is therefore also the hard ceiling on how many
# Chromium processes can ever run at once. Defaults to 1 (not 3) because the
# production host has just 512MB-2GB of RAM; a second concurrent browser is
# exactly what caused a real OOM kill (Render Events: "Ran out of memory
# (used over 512MB)") on 2026-08-30. Only raise this on a host with RAM to
# spare for genuinely concurrent scraping.
MAX_CONCURRENT_SCRAPES = int(os.environ.get("MATJAKT_MAX_SCRAPES", "1"))
MAX_BATCH_ITEMS = 20
PANTRY_RECIPE_CACHE_TTL_SECONDS = 1800
CAMPAIGN_CACHE_TTL_SECONDS = 3600
# Anonymous, aggregate-only counters for the landing page (see
# _handle_analytics_event) - a fixed allowlist, not free-text, so this can
# never become a place to smuggle arbitrary or identifying data through. No
# IP, user id, or timestamp finer than "today" is ever stored alongside a
# count.
ANALYTICS_ALLOWED_EVENTS = frozenset({"cta_testa_gratis", "cta_logga_in", "cta_se_hur_det_fungerar", "view_premium"})
CAMPAIGN_CAPABLE_CHAINS = ("Coop", "Hemköp")
CAMPAIGN_SCAN_INGREDIENTS = ["Kycklingfilé", "Kycklinglårfilé", "Köttfärs", "Biff", "Fläskfilé", "Laxfilé", "Fryst torsk", "Räkor", "Kalvschnitzel", "Falukorv", "Halloumi"]
GEOCODE_CACHE_TTL_SECONDS = 86400
PREMIUM_CODE = os.environ.get("MATJAKT_PREMIUM_CODE", "")
# Gates GET /api/admin/primat-status (current Primat quota usage) - a
# separate, unset-by-default secret, not tied to any user account (this app
# has no admin-role concept on accounts, and building one just for this one
# read-only diagnostic would be more machinery than the need warrants). When
# unset, the endpoint refuses every request rather than falling open.
ADMIN_TOKEN = os.environ.get("MATJAKT_ADMIN_TOKEN", "")
PRIMAT_API_KEY = os.environ.get("PRIMAT_API_KEY", "")
PRIMAT_STORE_CACHE_TTL_SECONDS = 86400
PRIMAT_CIRCUIT_COOLDOWN_SECONDS = 60
OFF_IMAGE_CACHE_TTL_SECONDS = 7 * 86400
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_MONTHLY = os.environ.get("STRIPE_PRICE_MONTHLY", "")
STRIPE_PRICE_YEARLY = os.environ.get("STRIPE_PRICE_YEARLY", "")
MAIL_CONFIG = {
    "host": os.environ.get("SMTP_HOST", ""),
    "port": os.environ.get("SMTP_PORT", "587"),
    "user": os.environ.get("SMTP_USER", ""),
    "password": os.environ.get("SMTP_PASSWORD", ""),
    "from_email": os.environ.get("SMTP_FROM_EMAIL", ""),
}
AXFOOD_STORE_LIST_URL = {"Willys": "https://www.willys.se/axfood/rest/v1/store", "Hemköp": "https://www.hemkop.se/axfood/rest/v1/store"}
STORE_LIST_CACHE_TTL_SECONDS = 86400
ICA_STORE_LIST_TTL_SECONDS = 3600
COOP_STORE_SEARCH_TTL_SECONDS = 86400
# How long a CLIENT may reuse a store list. Deliberately short and unrelated
# to the server-side cache above it: the payload is tiny, and a stale list is
# a user standing outside a shop that is not there.
# Whether X-Forwarded-For may be believed. True only when a trusted proxy
# sits in front of us and overwrites it (Render does); false by default so a
# directly-exposed instance cannot be fooled about who is calling.
TRUST_PROXY_HEADERS = str(os.environ.get("MATJAKT_TRUST_PROXY", "")).strip().lower() in {"1", "true", "yes", "on"}

STORE_LIST_RESPONSE_CACHE_SECONDS = 900

NEARBY_STORE_LIMIT = 12
NEARBY_STORE_RADIUS_KM = 60
# Whole-result cache for nearby_stores() itself (see its docstring) - a
# successful list is cached as long as a store list normally would be;
# an empty result gets a much shorter TTL so a transient Primat/geocode
# hiccup doesn't lock a postcode out of any stores for a full day.
NEARBY_STORES_TTL_SECONDS = STORE_LIST_CACHE_TTL_SECONDS
NEARBY_STORES_EMPTY_TTL_SECONDS = 300

STORE_CONFIG = {
    "Willys": {
        "search_url": "https://www.willys.se/sok?q={query}",
        "base_url": "https://www.willys.se",
        "product_selector": '[data-testid="product"]',
    },
    "Hemköp": {
        "search_url": "https://www.hemkop.se/sok?q={query}",
        "base_url": "https://www.hemkop.se",
        "product_selector": '[data-testid="product-container"]',
    },
    # ICA/Coop selectors below are best-effort guesses - verify against the
    # live site with DevTools before relying on them in production.
    # ICA is handled separately in parse_ica_products/resolve_ica_store - it has
    # no search results at all until a store is picked for a postnummer, so it
    # doesn't fit the generic search_url/product_selector shape used here.
    "ICA": {},
    # Verified live on 2026-08-27: coop.se has no stable data-testid, but every
    # product card has a direct-child link to /handla/varor/... which is stable.
    "Coop": {
        "search_url": "https://www.coop.se/handla/sok/?q={query}",
        "base_url": "https://www.coop.se",
        "product_selector": 'div:has(> a[href*="/handla/varor/"])',
    },
}
DEFAULT_ZIP = "11122"
_primat_store_scope_lock = threading.Lock()
_primat_circuit_open_until = 0.0
PANTRY_RECIPE_CACHE = {}
# One lock per (chain, query, cache_zip) so two concurrent requests for the
# SAME uncached item (two different users searching "Kycklingfilé" for the
# same chain/zip at the same moment, or one user's own several devices)
# never both hit Primat/scrape it at once - the second just waits, then
# reads what the first one cached, exactly the "flera samtidiga anrok får
# inte hämta samma uppgift parallellt" requirement. Same double-checked-
# locking shape as _primat_store_scope_lock below, generalized to a lock per
# key instead of one global lock, since product queries are far higher
# cardinality than zip codes.
_product_fetch_locks = {}
_product_fetch_locks_guard = threading.Lock()


def _lock_for_product_key(key):
    with _product_fetch_locks_guard:
        lock = _product_fetch_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _product_fetch_locks[key] = lock
        return lock
_scrape_executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SCRAPES, thread_name_prefix="playwright-worker")
_thread_browser = threading.local()
BROWSER_MAX_REQUESTS = 4


def get_shared_browser():
    """Launching headless Chromium costs 1-3s on its own, before any navigation -
    every scrape endpoint used to pay that on EVERY request (launch a fresh
    browser, use it once, close it), which is why a chain of small batched
    requests could take longer than a client-side timeout even though each one
    eventually succeeded. Playwright's sync API binds its greenlet dispatcher to
    the thread that called sync_playwright().start(), so a browser can only ever
    be driven from that same OS thread - it can't be launched on one thread and
    then used from another (ThreadingHTTPServer's per-request threads). So
    "shared" here means shared across every job that lands on the same
    _scrape_executor worker thread: each of its fixed pool of threads lazily
    launches its own Chromium once and keeps it for the life of the server,
    instead of paying the launch cost on every request. Callers get their own
    page per job for isolation and just close the page (not the browser) when
    done. This must only be called from inside a function passed to
    run_on_scrape_thread, never directly from a request-handling thread. If the
    thread's browser has died (crash, OOM), it's relaunched on the next call.

    Also force-relaunches after BROWSER_MAX_REQUESTS regardless of health -
    measured directly against production: a long run of consecutive real page
    loads on the same browser process visibly slows down and starts failing
    more (a 10-item week went from consistently succeeding on isolated
    single-item requests to only 2/10 succeeding back to back), on a host
    with just 512MB of RAM to work with. Deliberately low (4, not 10 or more):
    a typical shopping week is itself ~10 items, and the whole point is for a
    week-sized run to actually get recycled partway through instead of aging
    on one browser the entire time - a threshold at or above a typical batch
    size would never trigger during the run it's meant to help. Periodically
    starting clean is cheap (the 1-3s relaunch cost this function exists to
    avoid paying per-request) compared to the alternative of degrading for the
    rest of the process's life."""
    browser = getattr(_thread_browser, "browser", None)
    if browser is not None and (not browser.is_connected() or _thread_browser.request_count >= BROWSER_MAX_REQUESTS):
        try:
            browser.close()
        except Exception:
            pass
        _thread_browser.browser = None
    if getattr(_thread_browser, "browser", None) is None:
        if getattr(_thread_browser, "playwright", None) is None:
            _thread_browser.playwright = sync_playwright().start()
        _thread_browser.browser = _thread_browser.playwright.chromium.launch(headless=True)
        _thread_browser.request_count = 0
    _thread_browser.request_count += 1
    return _thread_browser.browser


def new_scrape_page():
    """A fresh page from the shared browser, with a short default action
    timeout. Without this, any Playwright call that waits for an element
    (inner_text, get_attribute, etc.) falls back to Playwright's own 30s
    default - and a page can make dozens of such calls per scrape (parse_products
    loops over up to 80 product cards), so worst case adds up to minutes rather
    than the ~25s SCRAPE_TASK_TIMEOUT_SECONDS is meant to bound things to."""
    page = get_shared_browser().new_page(locale="sv-SE")
    page.set_default_timeout(12000)
    return page


SCRAPE_TASK_TIMEOUT_SECONDS = 30


def run_on_scrape_thread(fn):
    """Runs fn on one of the dedicated Playwright worker threads and blocks the
    caller for the result - see get_shared_browser for why Playwright calls can't
    happen on an arbitrary request-handling thread. Also bounds how many scrapes
    run at once, since the executor has a fixed-size pool (MATJAKT_MAX_SCRAPES).

    A worker thread that hangs inside a blocking Playwright/OS call (a stalled
    navigation, a browser process that died mid-call) can't be interrupted -
    Python threads can't be killed from outside. Without a bound here, a single
    such hang permanently wedges every future scrape behind it forever, since
    with MATJAKT_MAX_SCRAPES=1 (the production setting) there's no other worker
    to pick up new requests - this happened for real: one stuck request took
    down the entire /api/products* surface until the process was restarted. So
    a call that runs past the timeout replaces the whole executor with a fresh
    one - the wedged thread is abandoned (it keeps running in the background,
    but nothing waits on it anymore) and every request after this one gets a
    brand new worker instead of queuing behind a dead one. 30s (just under the
    frontend's 35s per-item fetch timeout) so the server gives up at roughly
    the same point the client already would have - measured against the real
    production host: Willys scrapes in ~9-10s, but Coop alone can take
    18-25s even with nothing else competing for the CPU, so anything much
    tighter than this cuts off Coop specifically before it has a real chance
    to finish."""
    global _scrape_executor
    future = _scrape_executor.submit(fn)
    try:
        return future.result(timeout=SCRAPE_TASK_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        logger.error("Scrape task exceeded %ss - replacing the worker pool so future requests aren't wedged behind it", SCRAPE_TASK_TIMEOUT_SECONDS)
        stale_executor = _scrape_executor
        _scrape_executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SCRAPES, thread_name_prefix="playwright-worker")
        # The wedged thread's browser can only ever be closed from that same
        # thread (Playwright's sync API isn't safe to touch cross-thread -
        # see get_shared_browser). Queuing the close behind the stuck job is
        # a best-effort, not a guarantee (a truly-forever-hung call means
        # this never runs), but without it every timeout permanently leaked
        # one more live Chromium process for the rest of the server's
        # lifetime - on a memory-constrained host that quietly defeats
        # MAX_CONCURRENT_SCRAPES over time even though it's meant to be a
        # hard ceiling.
        try:
            stale_executor.submit(_close_thread_browser)
        except RuntimeError:
            pass
        stale_executor.shutdown(wait=False)
        raise
RECIPE_SERVICE = RecipeService([TheMealDbProvider()])
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
# Where the persisted stores live. Overridable so a TEST RUN never touches
# the real files: the suite calls KV_CACHE.clear() (documented "test-only")
# nine times, which against the real database wipes every cached geocode,
# store list, campaign and product image the machine had. On a developer's
# machine that just made the app slow for a while; pointed at a deployed data
# directory it would throw away real cached state on every CI run.
DATA_DIR = Path(os.environ.get("MATJAKT_DATA_DIR") or (Path(__file__).resolve().parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

ACCOUNT_STORE = AccountStore(DATA_DIR / "matjakt.db")
PRICE_CACHE = PriceCacheStore(DATA_DIR / "prices.db")
# Same SQLite file/connection as PRICE_CACHE (see KeyValueCacheStore's
# docstring) - campaigns, geocoding, store lists and Primat/OFF lookups used
# to live only in plain process-memory dicts, which reset to empty on every
# deploy/restart. Persisting them here is what actually makes "senast
# uppdaterad" survive a deploy.
KV_CACHE = KeyValueCacheStore(PRICE_CACHE.connection)


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def parse_price(text):
    match = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:kr|:-)", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def parse_willys_price(text):
    match = re.search(r"(\d+)\s+(\d{2})", clean_text(text))
    return float(f"{match.group(1)}.{match.group(2)}") if match else parse_price(text)


def geocode_postcode(zip_code):
    """Free, keyless Swedish postcode -> town/lat/lon lookup via zippopotam.us,
    so postcode-based distance works outside the Gävle demo data. Cached
    forever, persisted to disk since postal geography doesn't change day to
    day and this must survive restarts/deploys, not just this process's
    lifetime.

    Returns None on any failure (unknown postcode, network error, timeout) -
    never lets urlopen's exception escape. Found live: an invalid postcode
    makes zippopotam.us answer with a genuine HTTP 404, which urlopen raises
    as an uncaught HTTPError - that propagated all the way up through
    nearby_stores() to /api/stores's generic handler, which turned it into a
    502. A 502 is exactly what this app must never return for "we couldn't
    resolve this", per the same reasoning as stale_products - an honest
    empty/not-found result, not a server error, is what a bad or unlucky
    input should produce."""
    cached, updated_at = KV_CACHE.get("geocode", zip_code)
    if cached is not None and time.time() - updated_at < GEOCODE_CACHE_TTL_SECONDS:
        return cached
    request = Request(f"http://api.zippopotam.us/SE/{zip_code}", headers={"User-Agent": "Matjakt/1.0"})
    try:
        with urlopen(request, timeout=8) as response:
            data = json.load(response)
    except Exception:
        logger.exception("Geocode lookup failed for zip %s", zip_code)
        return None
    place = (data.get("places") or [None])[0]
    if not place:
        return None
    result = {"ort": place.get("place name", ""), "lat": float(place["latitude"]), "lon": float(place["longitude"])}
    KV_CACHE.set("geocode", zip_code, result)
    return result


def ica_stores_for_zip(zip_code):
    """ICA has no search results at all until a pickup/delivery store is chosen
    for a postnummer. Found via live network inspection: this JSON endpoint
    backs their own "Välj butik" widget, so it's the same data they use. Returns
    every store ICA offers for the zip (used both to pick one for product
    scraping and to list real nearby branches).

    Plain HTTP, no Playwright - verified live (2026-08-30) that this endpoint
    serves ordinary JSON with no browser/session/CAPTCHA requirement (unlike
    ICA's product SEARCH, which is genuinely blocked - see the "Kända
    begränsningar" note in README.md). Driving a whole Chromium instance just
    to fetch a JSON document was wasted memory on a host where that's scarce;
    this is the same urlopen pattern already used successfully for
    geocode_postcode/fetch_axfood_stores."""
    cached, updated_at = KV_CACHE.get("ica_stores", zip_code)
    if cached is not None:
        ttl = ICA_STORE_SUCCESS_TTL_SECONDS if cached["stores"] else ICA_STORE_FAILURE_TTL_SECONDS
        if time.time() - updated_at < ttl:
            return cached["stores"]
    request = Request(f"https://handla.ica.se/api/store/v1?zip={quote(zip_code)}&customerType=B2C", headers={"User-Agent": "Matjakt/1.0"})
    try:
        with urlopen(request, timeout=10) as response:
            data = json.load(response)
    except Exception:
        logger.exception("Failed to parse ICA store lookup response for zip %s", zip_code)
        data = {}
    stores = data.get("forPickupDelivery") or data.get("forHomeDelivery") or []
    KV_CACHE.set("ica_stores", zip_code, {"stores": stores})
    return stores


def resolve_ica_store(zip_code):
    stores = ica_stores_for_zip(zip_code)
    return stores[0] if stores else None


def haversine_km(lat1, lon1, lat2, lon2):
    earth_radius = 6371
    lat_delta, lon_delta = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(lat_delta / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(lon_delta / 2) ** 2
    return earth_radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_axfood_stores(chain):
    """Willys and Hemköp (both Axfood brands) expose their full national store
    list at this undocumented-but-public, unauthenticated REST endpoint - found
    via live network inspection of "Hitta butik". Cached for a day (persisted
    to disk, survives restarts) since store locations essentially never
    change."""
    cached, updated_at = KV_CACHE.get("store_list", chain)
    if cached is not None and time.time() - updated_at < STORE_LIST_CACHE_TTL_SECONDS:
        return cached
    request = Request(AXFOOD_STORE_LIST_URL[chain], headers={"User-Agent": "Matjakt/1.0"})
    with urlopen(request, timeout=15) as response:
        raw = json.load(response)
    stores = []
    for item in raw:
        point = item.get("geoPoint") or {}
        lat, lon = point.get("latitude"), point.get("longitude")
        name = item.get("name")
        if not name or not lat or not lon:
            continue
        stores.append({"kedja": chain, "namn": name, "lat": lat, "lon": lon, "ort": (item.get("address") or {}).get("town") or ""})
    KV_CACHE.set("store_list", chain, stores)
    return stores


def search_coop_stores(page, city):
    """Coop's store search needs a real browser session (their API sits behind
    an Azure APIM subscription key that's only attached by their own frontend
    JS), so - like ICA - this drives their real "Butiker" search and reads the
    same response their page renders from, instead of replicating the request."""
    cached, updated_at = KV_CACHE.get("coop_store_search", city)
    if cached is not None and time.time() - updated_at < COOP_STORE_SEARCH_TTL_SECONDS:
        return cached
    captured = {}

    def on_response(response):
        if "personalization/search/global" in response.url and response.request.method == "POST":
            try:
                captured["data"] = response.json()
            except Exception:
                pass

    page.on("response", on_response)
    try:
        page.goto("https://www.coop.se/butiker-erbjudanden/", wait_until="networkidle", timeout=20000)
        try:
            page.click("text=Acceptera alla cookies", timeout=3000)
        except Exception:
            pass
        box = page.locator('input[type="search"], input[type="text"]').first
        box.click(timeout=5000)
        box.fill(city)
        page.wait_for_timeout(400)
        box.press("Enter")
        page.wait_for_timeout(3000)
    except Exception:
        logger.exception("Coop store search interaction failed for %s", city)
    finally:
        page.remove_listener("response", on_response)
    data = captured.get("data") or {}
    items = ((data.get("storesResults") or {}).get("results") or {}).get("items") or []
    stores = []
    for item in items:
        lat, lon = item.get("latitude"), item.get("longitude")
        if not lat or not lon:
            continue
        stores.append({"kedja": "Coop", "namn": item.get("name") or "", "lat": lat, "lon": lon, "ort": item.get("city") or ""})
    KV_CACHE.set("coop_store_search", city, stores)
    return stores


def fetch_citygross_stores():
    """City Gross' own store list, via the provider that already knows how to
    read it (plain HTTP + coordinates, no browser).

    Added because /api/stores covered Willys, Hemköp, ICA and Coop but not
    City Gross - so a chain we hold real prices for could never be shown as a
    nearby store, and its shopping list was unreachable from the comparison.
    Cached for a day like the Axfood list; store locations barely change."""
    cached, updated_at = KV_CACHE.get("store_list", "City Gross")
    if cached is not None and time.time() - updated_at < STORE_LIST_CACHE_TTL_SECONDS:
        return cached
    stores = []
    try:
        from services.grocery.providers.citygross import CityGrossProvider
        for store in CityGrossProvider().get_stores():
            if store.latitude and store.longitude:
                stores.append({
                    "kedja": "City Gross",
                    "namn": store.name,
                    "lat": store.latitude,
                    "lon": store.longitude,
                    "ort": store.city or "",
                })
    except Exception:
        # A chain we cannot reach right now must not break the whole store
        # lookup - the other chains are still perfectly usable.
        logger.exception("Kunde inte hämta City Gross butikslista")
        return cached or []
    KV_CACHE.set("store_list", "City Gross", stores)
    return stores


def _limit_keeping_every_chain(stores, limit=None):
    """Caps the store list without letting one dense chain crowd out another.

    A plain distance sort truncated to 12 dropped City Gross entirely for
    Gävle: five Coop branches inside 2 km pushed out the only City Gross
    store at ~3 km - a chain Matjakt holds over ten thousand real prices for.
    Five branches of the same chain are not more useful to a shopper than one
    branch of a chain they could actually compare against.

    So: every chain gets its nearest branch first, then the remaining slots
    are filled by distance as before. Input must already be distance-sorted."""
    limit = NEARBY_STORE_LIMIT if limit is None else limit
    first_per_chain, rest, seen = [], [], set()
    for store in stores:
        chain = store.get("kedja")
        if chain in seen:
            rest.append(store)
        else:
            seen.add(chain)
            first_per_chain.append(store)
    kept = first_per_chain[:limit] + rest[:max(0, limit - len(first_per_chain))]
    return sorted(kept, key=lambda store: store["avstandKm"])


def _citygross_stores_or_empty():
    """One chain's store lookup must never be able to take down the others.

    fetch_citygross_stores() already swallows its own network errors, but the
    call sites guard it too: a chain being unreachable is a normal Tuesday,
    and losing Willys, Hemköp, ICA and Coop over it would turn a small outage
    into a total one."""
    try:
        return fetch_citygross_stores()
    except Exception:
        logger.exception("City Gross-butiksuppslag misslyckades")
        return []


def nearby_stores(zip_code):
    """Cached, single-flight wrapper around _compute_nearby_stores - see that
    function for the actual Primat/geocode/scrape logic. Added because
    /api/stores previously called the real computation on every single
    request with no result cache of its own (only its sub-lookups were
    individually cached) - with Primat's quota exhausted, that meant every
    request fell through to a real Coop scrape, which is exactly the kind of
    repeated Chromium usage that caused a real OOM kill on the production
    host (Render Events: "Ran out of memory (used over 512MB)", 2026-08-30).
    The per-zip lock (same _lock_for_product_key used for products) ensures
    concurrent requests for the same postcode share one fetch instead of each
    starting their own."""
    cached, updated_at = KV_CACHE.get("nearby_stores", zip_code)
    if cached is not None and time.time() - updated_at < (NEARBY_STORES_TTL_SECONDS if cached else NEARBY_STORES_EMPTY_TTL_SECONDS):
        return cached
    with _lock_for_product_key(("nearby_stores", zip_code)):
        cached, updated_at = KV_CACHE.get("nearby_stores", zip_code)
        if cached is not None and time.time() - updated_at < (NEARBY_STORES_TTL_SECONDS if cached else NEARBY_STORES_EMPTY_TTL_SECONDS):
            return cached
        result = _compute_nearby_stores(zip_code)
        KV_CACHE.set("nearby_stores", zip_code, result)
        return result


def _compute_nearby_stores(zip_code):
    # Primat's own store resolver first - a fast, ordinary HTTPS call that
    # already covers Willys/Coop/Hemköp/ICA with real distances, no
    # geocoding or scraping needed at all. Falls through to the existing
    # scrape-based approach only if Primat has nothing. Shares the same
    # circuit breaker as primat_store_scope/fetch_from_primat - see
    # _trip_primat_circuit for why a failure here shouldn't be retried
    # immediately either.
    primat_results = []
    if not _primat_circuit_is_open():
        try:
            primat_results = primat_nearby_stores(zip_code, api_key=PRIMAT_API_KEY or None)
        except PrimatError:
            logger.exception("Primat nearby-stores failed for zip %s", zip_code)
            _trip_primat_circuit()
    place = geocode_postcode(zip_code)

    if primat_results:
        nearby = [s for s in primat_results
                  if s["avstandKm"] is not None and s["avstandKm"] <= NEARBY_STORE_RADIUS_KM]
        # Primat resolves Willys/Coop/Hemköp/ICA but knows nothing about City
        # Gross, so returning here without it would permanently hide a chain
        # we hold real prices for.
        if place:
            for store in _citygross_stores_or_empty():
                distance = round(haversine_km(place["lat"], place["lon"], store["lat"], store["lon"]), 1)
                if distance <= NEARBY_STORE_RADIUS_KM:
                    nearby.append({**store, "avstandKm": distance, "primatKey": ""})
        return _limit_keeping_every_chain(sorted(nearby, key=lambda s: s["avstandKm"]))

    if not place:
        return []
    lat, lon = place["lat"], place["lon"]
    # Willys/Hemköp (plain HTTP, cached) and ICA (plain HTTP, cached - see
    # ica_stores_for_zip) never need a browser at all. Only Coop's store
    # search genuinely does (its API sits behind a key only its own frontend
    # JS attaches - see search_coop_stores), so a Chromium page is only
    # opened when Coop's own cache is actually cold, not on every lookup.
    candidates = [*fetch_axfood_stores("Willys"), *fetch_axfood_stores("Hemköp"),
                  *_citygross_stores_or_empty()]
    for store in ica_stores_for_zip(zip_code):
        s_lat, s_lon = store.get("latitude"), store.get("longitude")
        if s_lat and s_lon:
            candidates.append({"kedja": "ICA", "namn": store.get("name") or "", "lat": s_lat, "lon": s_lon, "ort": (store.get("address") or {}).get("city") or ""})

    coop_cached, coop_updated_at = KV_CACHE.get("coop_store_search", place["ort"])
    if coop_cached is not None and time.time() - coop_updated_at < COOP_STORE_SEARCH_TTL_SECONDS:
        candidates.extend(coop_cached)
    else:
        def _scrape_coop():
            page = new_scrape_page()
            try:
                return search_coop_stores(page, place["ort"])
            finally:
                page.close()
        try:
            candidates.extend(run_on_scrape_thread(_scrape_coop))
        except Exception:
            logger.exception("Failed to resolve Coop stores for %s", place["ort"])

    for store in candidates:
        store["avstandKm"] = round(haversine_km(lat, lon, store["lat"], store["lon"]), 1)
    nearby = sorted((s for s in candidates if s["avstandKm"] <= NEARBY_STORE_RADIUS_KM), key=lambda s: s["avstandKm"])
    return _limit_keeping_every_chain(nearby)


def parse_ica_products(page, query, zip_code):
    store = resolve_ica_store(zip_code)
    if not store:
        return []
    account_id = store["accountId"]
    base_url = f"https://handlaprivatkund.ica.se/stores/{account_id}"
    # A fresh page.goto() straight to "{base_url}/search?q=..." is silently
    # redirected away to the bare handlaprivatkund.ica.se domain (verified
    # live 2026-08-30, before and after this fix - reproduced with several
    # different queries and store ids) - this SPA doesn't support deep-
    # linking directly into /search on a cold load, even though that exact
    # URL works fine once reached by an in-app route change. The fix is to
    # load the store's base page first (that navigation is unaffected) and
    # then drive the real search box, matching what a user's browser
    # actually does - not a second goto(). The result page's own markup
    # (.product-card-container, [data-test="fop-price"] etc. below) is
    # completely unchanged from before; only how you reach it changed.
    page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
    try:
        # A fresh session (no stored consent) shows a OneTrust cookie banner
        # that sits on top of the page and blocks every later click as
        # "intercepts pointer events" until dismissed - verified live
        # 2026-08-30 that this is what actually broke the submit-button click
        # below, not the click itself. #onetrust-accept-btn-handler is
        # OneTrust's own stable button id (not page-specific/guessed markup),
        # unlike a text match, which matched two different elements on this
        # page and clicked the wrong one. A session that already has consent
        # just skips this (button never appears).
        page.click("#onetrust-accept-btn-handler", timeout=4000)
        # The banner's own fade-out transition still intercepts clicks for a
        # moment after the accept click resolves - waiting for it to actually
        # leave the DOM (not just for the click itself) is what made this
        # reliable in testing, vs. clicks landing on the still-fading overlay.
        page.wait_for_selector("#onetrust-banner-sdk", state="hidden", timeout=5000)
    except Exception:
        pass
    search_input = page.locator("#search")
    try:
        search_input.wait_for(state="visible", timeout=3000)
    except Exception:
        # Mobile-width layouts collapse the search box behind a "hoppa till
        # sökning" skip-link that must be opened first (verified live
        # 2026-08-30) - desktop-width layouts show #search immediately and
        # never need this.
        skip_link = page.locator('a[href="#search"]').first
        if skip_link.count():
            skip_link.click()
        search_input.wait_for(state="visible", timeout=10000)
    search_input.fill(query)
    # Clicking the form's real submit button, not pressing Enter - verified
    # live (2026-08-30) that Enter alone changes the URL but never actually
    # triggers the results fetch (only the autocomplete "suggestions"
    # endpoints fire), while the submit button reliably loads real, priced
    # results. Falls back to Enter only if the button isn't found at all, so
    # a future markup change degrades instead of hard-failing.
    submit_button = search_input.locator("xpath=ancestor::form").locator('button[type="submit"]')
    if submit_button.count():
        submit_button.first.click()
    else:
        search_input.press("Enter")
    try:
        page.locator(".product-card-container").first.wait_for(state="visible", timeout=10000)
    except Exception:
        # No results ever rendered - handled the same as any other "nothing
        # found" case by the loop's own retry/empty-return below, not a
        # special error path.
        pass
    products = []
    for attempt in range(3):
        page.wait_for_timeout(1800)
        products = []
        seen = set()
        for card in page.locator(".product-card-container").all()[:80]:
            link = card.locator('[data-test="fop-product-link"][aria-hidden="false"]').first
            price_node = card.locator('[data-test="fop-price"]').first
            if not link.count() or not price_node.count():
                continue
            name = clean_text(link.inner_text())
            price = parse_price(price_node.inner_text())
            href = link.get_attribute("href")
            if not name or not price or not href:
                continue
            image_node = card.locator("img").first
            image = (image_node.get_attribute("src") if image_node.count() else "") or ""
            if image.startswith("//"):
                image = f"https:{image}"
            key = (name, price, href)
            if key in seen:
                continue
            seen.add(key)
            products.append({"kedja": "ICA", "produktnamn": name, "marke_och_storlek": store["name"], "bild": image or "", "pris_kr": price, "storlek": "", "lager": True, "url": f"https://handlaprivatkund.ica.se{href}", "sokning": query, "kampanj": None})
        if products:
            break
    return products[:20]


def parse_kronor_ore_text(text):
    match = re.search(r"(\d+)\s*kronor(?:\s+och\s+(\d+)\s*öre)?", text or "", re.I)
    if not match:
        return None
    return int(match.group(1)) + int(match.group(2) or 0) / 100


def extract_campaign(chain, text, aria_label):
    """Coop and Hemköp mark discounted products distinctly in their search
    results (verified live 2026-08-28); Willys/ICA showed no such markup in
    samples checked, so they're left undetected rather than guessed at."""
    if chain == "Coop":
        if not aria_label or "erbjudande" not in aria_label.lower():
            return None
        parts = [clean_text(part) for part in aria_label.split(",")]
        offer = next((part for part in parts if part.lower().startswith("erbjudande") and "jämförpris" not in part.lower()), None)
        if not offer:
            return None
        ordinary = next((part for part in parts if part.lower().startswith("ordinarie pris")), None)
        return {"text": offer, "ordinariePris": parse_kronor_ore_text(ordinary) if ordinary else None}
    if chain == "Hemköp":
        match = re.search(r"\d+\s+för\s+\d+[.,]?\d*\s*kr", text or "", re.I)
        return {"text": clean_text(match.group(0)), "ordinariePris": None} if match else None
    return None


def parse_products(page, chain, query):
    config = STORE_CONFIG[chain]
    page.goto(config["search_url"].format(query=quote(query)), wait_until="domcontentloaded", timeout=30000)
    products = []
    for attempt in range(3):
        page.wait_for_timeout(1800)
        products = []
        seen = set()
        for card in page.locator(config["product_selector"]).all()[:80]:
            text = clean_text(card.inner_text())
            price_node = card.locator('[data-testid*="price"], [data-testid*="Price"]')
            price = parse_willys_price(price_node.first.inner_text()) if price_node.count() else parse_price(text)
            link = card.locator("a").first
            href = link.get_attribute("href") if link.count() else None
            if not text or not price or not href:
                continue
            name_node = card.locator('[itemprop="name"], [data-testid="product-title"]')
            brand_node = card.locator('[itemprop="brand"], [data-testid="display-manufacturer"]')
            name = clean_text(name_node.first.inner_text()) if name_node.count() else clean_text(link.inner_text())
            aria_label = link.get_attribute("aria-label") or ""
            aria_parts = []
            if not name:
                # Coop's product link only wraps the image; the name/brand/size
                # live in the link's aria-label instead, e.g. "Mellanmjölk, Coop,
                # 1.5 l, Pris 16 kronor och 27 öre styck, ...".
                aria_parts = [clean_text(p) for p in aria_label.split(",")]
                name = aria_parts[0] if aria_parts else ""
            brand = clean_text(brand_node.first.inner_text()) if brand_node.count() else ""
            if not brand and len(aria_parts) > 2:
                brand = f"{aria_parts[1]} {aria_parts[2]}".strip()
            volume_node = card.locator('[data-testid="display-volume"]')
            if volume_node.count():
                brand = f"{brand} {clean_text(volume_node.first.inner_text())}".strip()
            image_node = card.locator("img").first
            image = (image_node.get_attribute("src") if image_node.count() else "") or ""
            if image.startswith("//"):
                image = f"https:{image}"
            key = (name, price, href)
            if key in seen:
                continue
            seen.add(key)
            products.append({"kedja": chain, "produktnamn": name, "marke_och_storlek": brand, "bild": image or "", "pris_kr": price, "storlek": "", "lager": True, "url": href if href.startswith("http") else f"{config['base_url']}{href}", "sokning": query, "kampanj": extract_campaign(chain, text, aria_label)})
        if products:
            break
    return products[:20]


STORE_KEY_PATTERN = re.compile(r"^[a-z]+:[A-Za-z0-9]+$")


def store_key_param(raw):
    """Validates a client-supplied Primat store key ("chain:store_id", from a
    branch's primatKey) before it's trusted anywhere - rejects anything that
    doesn't match the shape Primat itself hands out, rather than passing
    arbitrary client input straight into a cache key and an outbound API
    call."""
    value = clean_text(str(raw or ""))[:40]
    return value if STORE_KEY_PATTERN.fullmatch(value) else None


def cache_scope(zip_code, store_key):
    """A specific pinned store's prices must never share a cache entry with
    the chain's default door for this zip - two Coop locations can genuinely
    have different prices (member deals, local campaigns), and conflating
    them would let one silently overwrite what "auto" shows for the other.
    Folded into the existing zip_code-shaped cache key (see PriceCacheStore,
    which treats it as an opaque string) rather than changing the cache's
    schema."""
    return f"{zip_code}#{store_key}" if store_key else zip_code


def cached_products(chain, query, zip_code):
    """Returns (products, updated_at) for a persisted cache entry within
    CACHE_MAX_AGE_SECONDS (6h), or (None, None) if there's no usable entry.
    updated_at is a real time.time() timestamp (not time.monotonic() - this
    has to stay meaningful across restarts, since the whole point of
    PRICE_CACHE is surviving them) so callers can label a served price
    "Senast uppdaterat <tid>" instead of quietly passing off an old number
    as current. Deliberately reused for the full 6h rather than just a few
    minutes: re-scraping on every request is exactly what made this
    unreliable in practice (see get_shared_browser's docstring) - a same-day
    price is close enough to correct that re-fetching it is waste, not
    accuracy. See stale_products() for the fallback used when a fresh
    re-fetch is attempted (this returned None/expired) and then fails."""
    products, updated_at = PRICE_CACHE.get(chain, query.lower(), zip_code)
    if products is None:
        return None, None
    if time.time() - updated_at >= CACHE_MAX_AGE_SECONDS:
        return None, None
    return products, updated_at


def stale_products(chain, query, zip_code):
    """Returns (products, updated_at) regardless of age (up to
    PriceCacheStore's own 7-day prune horizon), or (None, None) if nothing
    was ever cached at all. Used only as a last resort when both the fresh
    cache (cached_products) missed AND a live re-fetch (Primat + scraping)
    just failed - a real price from earlier, honestly labeled "Senast känt
    pris <tid>", beats an empty shopping list row."""
    return PRICE_CACHE.get_stale(chain, query.lower(), zip_code)


def store_products(chain, query, zip_code, products):
    PRICE_CACHE.set(chain, query.lower(), zip_code, products)


def scrape_products(page, chain, query, zip_code):
    return parse_ica_products(page, query, zip_code) if chain == "ICA" else parse_products(page, chain, query)


def annotate_updated(products, updated_at):
    """Stamps each product with when this price was actually captured (a real
    time.time() timestamp) so the frontend can tell a just-scraped price from
    one served out of the 24h cache and label it honestly - "Live" only for
    the former, "Senast uppdaterat <tid>" for the latter. Never omitted: a
    price with no indication of its age is exactly the kind of claim the app
    has deliberately avoided making all along."""
    return [{**product, "uppdaterad": updated_at} for product in products]


def stamp_match(product, updated_at):
    if not product:
        return None
    return {**fill_missing_image(product), "uppdaterad": updated_at}


# Verified live against real Primat data (2026-08-30) for the ingredient
# names known to collide with a wrong grocery department when only a
# leading-word check is used - see best_match()'s docstring for the general
# mechanism. Kept as a small, explicit table (not a generic classifier)
# because the app's ingredient vocabulary is itself small and fixed (see
# RECIPE_QUANTITIES/PRODUCT_CATALOG in frontend/app/app.js) - every entry here
# should be backed by a real reproduction, not a guess.
#
# "category_top" checks Primat's own top-level department (the first segment
# of "kategori", e.g. "Frukt & Grönsaker > Grönsaker > Paprika" -> "Frukt &
# Grönsaker") - only applied when a candidate actually has a category
# (Primat-sourced only; scraped rows have "kategori": ""). "exclude_words" is
# a substring check on the product name, applied regardless of source, for
# cases where the category alone doesn't distinguish the right product from
# a wrong one in the *same* department (risotto rice shares "Skafferi > Ris,
# Mos & Gryner > Ris" with everyday rice).
INGREDIENT_MATCH_RULES = {
    "citron": {
        # Live reproduction: Coop's top "Citron" relevance hits included
        # "Citronsoda Sockerfri" and "Sprite" (category "Dryck > Läsk >
        # Citron- & limesmak") - a citron-*flavoured* drink starts with the
        # literal word "Citron" just as validly as a real lemon does, so the
        # word-boundary check alone lets it through.
        "category_top": "frukt & grönsaker",
        "exclude_words": ["zero", "soda", "sprite", "läsk", "juice", "saft", "syra", "peppar"],
    },
    "paprika": {
        "category_top": "frukt & grönsaker",
        "exclude_words": ["pulver", "krydda", "kryddor", "chips", "sås"],
    },
    "ris": {
        # Category alone doesn't help here - "Risottoris"/"Avorioris" share
        # the exact same "Skafferi > Ris, Mos & Gryner > Ris" category as
        # everyday jasmine/basmati rice. Live reproduction: Willys/"Ris"
        # picked "Avorio Risottoris" (specialty risotto rice) once no plain
        # "Ris ..." leading-word match existed in that store's current stock.
        "category_top": "skafferi",
        "exclude_words": ["risotto", "arborio", "avorio", "risifrutti", "gröt", "pudding", "nudlar", "kaka", "kakor", "snacks"],
    },
    "majs": {
        # Already covered by the word-boundary check for "Majskakor" (one
        # compound word), but category adds a second, independent layer -
        # "Majssnacks" is itself a separate two-word product name that could
        # otherwise slip through if Primat ever lists it split differently.
        "category_top": "frukt & grönsaker",
        "exclude_words": ["kaka", "kakor", "snacks", "chips", "popcorn"],
    },
}

# Words that never belong to a legitimate match for ANY ingredient this app
# searches for - none of RECIPE_QUANTITIES' ~90 ingredient names are
# themselves a soft drink, candy, or snack, so excluding these everywhere is
# safe (unlike a per-ingredient list, this needs no per-query justification).
UNIVERSAL_EXCLUDE_WORDS = ["zero", "läsk", "cola", "fanta", "sprite", "loka", "ramlösa", "zingo", "saft", "chips", "godis", "glass", "karamell", "tuggummi", "kex", "muffin", "bulle", "wienerbröd"]


def _passes_ingredient_rules(product, query_key):
    name = product["produktnamn"].lower()
    rule = INGREDIENT_MATCH_RULES.get(query_key)
    exclude_words = UNIVERSAL_EXCLUDE_WORDS + (rule["exclude_words"] if rule else [])
    if any(word in name for word in exclude_words):
        return False
    if rule and rule.get("category_top"):
        category = (product.get("kategori") or "").strip()
        if category and category.split(">")[0].strip().lower() != rule["category_top"]:
            return False
    return True


def best_match(products, query):
    """Search results are sorted by relevance, not name accuracy, so a plain
    "first result" can be a wrong department entirely (e.g. "Paprika" matching
    a paprika-flavoured cracker). Only a result that passes ALL THREE checks
    below is trusted; if none do, this returns None and the caller must show
    "Pris saknas" rather than guess - a wrong product silently priced is
    worse than an honest gap.

    1. Whole leading WORDS, not a raw string prefix - found directly against
       real Primat data: "Majs" (corn) matching "Majskakor" (corn cakes, a
       snack) because the string "majskakor" happens to start with "majs" as
       a character sequence. Swedish compounds words this way constantly
       ("Ris"/"Riskakor", "Paprika"/"Paprikapulver"), so a substring check
       quietly recommends the wrong department just as easily as no filter
       at all - comparing whole words closes exactly that gap while still
       matching "Kidneybönor" against "Kidneybönor Naturella".
    2. Category (see INGREDIENT_MATCH_RULES) - Primat's own department path,
       when available, for the handful of ingredient names verified to need
       it.
    3. Negative keywords (also INGREDIENT_MATCH_RULES, plus
       UNIVERSAL_EXCLUDE_WORDS) - catches wrong-but-same-department products
       category alone can't separate (risotto rice vs. everyday rice).

    There used to be a fourth step here: fall back to whatever Primat ranked
    first if nothing passed the word check. That's exactly how "Ris" turned
    into "Avorio Risottoris" and "Paprika" into paprika-flavoured chips in
    production - removed on purpose, not simplified away by accident.

    Among equally-good matches, prefer one with a real GTIN attached (Primat
    results carry this; scraped results never have a "gtin" key at all, so
    .get() just returns None for them and this tiebreaker is a no-op there -
    a GTIN doesn't make a wrong name match right, it only breaks ties between
    otherwise-safe candidates)."""
    if not products:
        return None
    query_key = query.strip().lower()
    query_words = query_key.split()
    starts_with = [
        product for product in products
        if product["produktnamn"].lower().split()[:len(query_words)] == query_words
    ]
    safe = [product for product in starts_with if _passes_ingredient_rules(product, query_key)]
    if not safe:
        return None
    with_gtin = [product for product in safe if product.get("gtin")]
    return (with_gtin or safe)[0]


def _primat_circuit_is_open():
    """True while Primat is in a post-failure cooldown - see
    _trip_primat_circuit for why this exists."""
    return time.monotonic() < _primat_circuit_open_until


def _trip_primat_circuit():
    """Opens the circuit for PRIMAT_CIRCUIT_COOLDOWN_SECONDS after ANY Primat
    failure (resolve or search). Measured directly while building this: a
    single bad response (a transient block, a brief outage) meant every
    subsequent lookup - one per ingredient, times however many are in flight -
    retried immediately, which is itself the kind of request burst that gets
    a shared API key rate-limited or blocked by the provider's own abuse
    protection (confirmed: a burst of retries here produced a 403 from
    Primat's own Cloudflare layer, while a single clean request right after
    succeeded normally). A short global cooldown after any failure turns
    "keep hammering a service that just said no" into "back off briefly,
    let scraping cover this round, try Primat again soon" - the difference
    between being a well-behaved client and being the reason a key gets
    throttled."""
    global _primat_circuit_open_until
    _primat_circuit_open_until = time.monotonic() + PRIMAT_CIRCUIT_COOLDOWN_SECONDS


def primat_store_scope(zip_code):
    """{primat_chain: "chain:store_id"} for a zip code, cached for a day
    (store locations don't change often, and this saves a network round trip
    on every single search). Returns {} - not an exception - if Primat's own
    resolver is unreachable or the circuit is open, so callers just fall back
    to searching without a store scope (or, if that's not sensible, skip
    Primat and go straight to scraping) rather than failing the request.

    Serialized with a lock - measured directly while building this: a
    shopping list's items are looked up with a few concurrent workers (see
    LIVE_PRICE_CONCURRENCY in app.js), and on a cold cache every one of them
    would race to resolve the same zip code at once. That thundering herd of
    simultaneous requests is a very different, worse pattern than a few
    requests spread out over time, and it's what actually triggered a 403
    from Primat's own abuse protection during testing - a single request
    right after succeeded normally. The lock means only the first caller
    for an uncached zip actually hits the network; everyone else just reads
    the cache it fills in. Persisted to disk (not just this process's
    memory) so a restart doesn't throw away a day's worth of resolved zips."""
    cached, updated_at = KV_CACHE.get("primat_store_scope", zip_code)
    if cached is not None and time.time() - updated_at < PRIMAT_STORE_CACHE_TTL_SECONDS:
        return cached
    with _primat_store_scope_lock:
        # Re-check inside the lock - another thread may have just resolved
        # (or failed to resolve) this exact zip while we were waiting.
        cached, updated_at = KV_CACHE.get("primat_store_scope", zip_code)
        if cached is not None and time.time() - updated_at < PRIMAT_STORE_CACHE_TTL_SECONDS:
            return cached
        if _primat_circuit_is_open():
            return {}
        try:
            stores = primat_resolve_stores(zip_code, api_key=PRIMAT_API_KEY or None)
        except PrimatError:
            logger.exception("Primat store resolve failed for zip %s", zip_code)
            _trip_primat_circuit()
            return {}
        KV_CACHE.set("primat_store_scope", zip_code, stores)
        return stores


def fill_missing_image(product):
    """Primat never returns product images at all (see
    primat_client.to_matjakt_product) - this fills one in from Open Food
    Facts via the product's GTIN when possible. Cached for a week (an image
    URL essentially never changes) since this is a real extra network call
    per product. Swedish private-label groceries are frequently NOT in Open
    Food Facts at all - that's an expected, common outcome (see
    open_food_facts_client's docstring), not something to log as an error;
    the item just keeps the placeholder icon, same as before this existed."""
    gtin = product.get("gtin")
    if product.get("bild") or not gtin:
        return product
    # "no image found" is itself a real, worth-caching result (a GTIN that's
    # simply not in Open Food Facts, common for Swedish private-label
    # groceries) - cached_image is None in that case, so freshness is judged
    # by updated_at being present, not by truthiness of the value itself.
    cached_image, updated_at = KV_CACHE.get("off_image", gtin)
    if updated_at is not None and time.time() - updated_at < OFF_IMAGE_CACHE_TTL_SECONDS:
        image_url = cached_image
    else:
        try:
            image_url = image_url_for_gtin(gtin)
        except OpenFoodFactsError:
            logger.exception("Open Food Facts image lookup failed for GTIN %s", gtin)
            image_url = None
        KV_CACHE.set("off_image", gtin, image_url)
    if image_url:
        # bild_kalla lets the frontend show Open Food Facts' own required
        # attribution specifically when one of their images is actually on
        # screen, same idea as "kalla" for Primat's price attribution.
        product = {**product, "bild": image_url, "bild_kalla": "openfoodfacts"}
    return product


def fetch_from_primat(chain, query, zip_code, store_key=None):
    """Tries Primat for a single ingredient query before ever touching
    Playwright. A fast, ordinary HTTPS call - no headless browser - so this
    runs directly on the request-handling thread; run_on_scrape_thread's
    dedicated worker pool exists specifically to manage Playwright's
    cost/slowness, which doesn't apply here. Always returns a list (possibly
    empty) rather than raising - "Primat has nothing for this" and "Primat
    couldn't be reached" both mean the same thing to callers: fall back to
    scraping (see get_shared_browser/parse_products), since Primat is
    explicitly still under active development and this app must never depend
    on it always answering.

    store_key ("chain:store_id", from a branch's primatKey - see
    primat_client.nearby_stores) pins the search to that exact door instead
    of the zip code's default pick for the chain - this is how a user
    picking a specific branch in the store comparison list (e.g. "Coop
    Tullhuset" over the default "Coop Nian") actually changes which real
    prices come back. Only trusted when its own chain prefix matches the
    chain being searched, so a stale/mismatched key from switching chains
    can't silently scope a search to the wrong store."""
    if _primat_circuit_is_open():
        return []
    primat_chain = CHAIN_TO_PRIMAT.get(chain)
    if not primat_chain:
        return []
    if store_key and store_key.split(":", 1)[0] != primat_chain:
        store_key = None
    store_scope = store_key or primat_store_scope(zip_code).get(primat_chain)
    if not store_scope:
        return []
    try:
        results = primat_search_products(query, stores=store_scope, api_key=PRIMAT_API_KEY or None)
    except PrimatError:
        logger.exception("Primat product search failed for %s/%s", chain, query)
        _trip_primat_circuit()
        return []
    return [primat_to_matjakt_product(product, chain, query) for product in results]


class ApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _cors_origin(self):
        request_origin = self.headers.get("Origin", "")
        if request_origin.rstrip("/") in ALLOWED_ORIGINS:
            return request_origin
        return ALLOWED_ORIGIN

    def send_json(self, status, payload, cache_seconds=None):
        self._json_response = True
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", f"public, max-age={cache_seconds}" if cache_seconds else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # Static files (frontend/*.js, *.css, ...) get no Cache-Control from
        # SimpleHTTPRequestHandler, so browsers fall back to heuristic caching
        # off Last-Modified - which can silently keep serving a stale ES module
        # (e.g. src/api/config.js) after a deploy, with no error until a whole
        # import breaks. Force revalidation instead; conditional GETs still get
        # cheap 304s. API responses set their own Cache-Control via send_json.
        if not getattr(self, "_json_response", False):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, "File not found")
        return None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def _client_ip(self):
        """The caller's address, honouring the proxy header Render sets.

        Behind a proxy every request appears to come from the proxy, which
        would put every user of the app in ONE rate-limit bucket - the first
        ten failed logins anywhere would lock out the whole world. Only the
        FIRST entry of X-Forwarded-For is used: the rest are attacker-supplied
        and trivially spoofed."""
        # X-Forwarded-For is only believed when we are actually behind a
        # proxy that sets it. A client talking to us directly can put
        # anything in that header, so trusting it unconditionally would let
        # an attacker rotate it and walk straight past the per-IP limit -
        # turning the rate limiter into decoration. Render terminates TLS at
        # its own proxy, so MATJAKT_TRUST_PROXY=1 is set there and nowhere
        # else. Only the FIRST entry is used; the rest are appended by
        # upstream hops and are attacker-controlled.
        if TRUST_PROXY_HEADERS:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()[:64]
        return (self.client_address[0] if self.client_address else "") or ""

    def _rate_limit(self, action, *identifiers):
        """Returns True when the request must be refused. Sends the 429."""
        try:
            ratelimit.check(action, self._client_ip(), *identifiers)
            return False
        except ratelimit.RateLimited as limited:
            self.send_json(429, {"error": str(limited), "retryAfter": limited.retry_after})
            return True

    def _bearer_token(self):
        header = self.headers.get("Authorization", "")
        return header[7:] if header.lower().startswith("bearer ") else None

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        return json.loads(raw)

    def _handle_stripe_webhook(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            verify_webhook_signature(raw, self.headers.get("Stripe-Signature", ""), STRIPE_WEBHOOK_SECRET)
            event = parse_event(raw)
        except StripeError as error:
            logger.warning("Rejected Stripe webhook: %s", error)
            self.send_json(400, {"error": str(error)})
            return
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Ogiltig JSON"})
            return
        event_type = event.get("type", "")
        data = event.get("data", {}).get("object", {})
        if event_type in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            customer_id = data.get("customer")
            period_end = data.get("current_period_end")
            period_end_iso = datetime.fromtimestamp(period_end, tz=timezone.utc).isoformat() if period_end else None
            items = data.get("items", {}).get("data", [])
            price_id = items[0]["price"]["id"] if items else None
            plan = "yearly" if price_id == STRIPE_PRICE_YEARLY else "monthly" if price_id == STRIPE_PRICE_MONTHLY else price_id
            ACCOUNT_STORE.apply_subscription_event(
                customer_id, data.get("id"), data.get("status"), period_end_iso,
                bool(data.get("cancel_at_period_end")), plan,
            )
        self.send_json(200, {"received": True})

    def do_GET(self):
        self._json_response = False
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json(200, {"ok": True, "stores": sorted(STORE_CONFIG), "recipeProviders": sorted(RECIPE_SERVICE.providers)}, cache_seconds=900)
            return
        if parsed.path == "/api/admin/primat-status":
            # Never a regular user's endpoint - gated by a separate admin
            # secret (see ADMIN_TOKEN), not account premium status. Refuses
            # everything if the secret was never configured, rather than
            # falling open. The Primat API key itself is never included in
            # the response - only Primat's own usage numbers are.
            if not ADMIN_TOKEN or not hmac.compare_digest(self.headers.get("X-Admin-Token", ""), ADMIN_TOKEN):
                self.send_json(404, {"error": "Okänd endpoint"})
                return
            if not PRIMAT_API_KEY:
                self.send_json(200, {"configured": False})
                return
            try:
                status = primat_account_status(PRIMAT_API_KEY)
            except PrimatError as error:
                self.send_json(502, {"configured": True, "error": str(error)})
                return
            self.send_json(200, {"configured": True, "status": status})
            return
        if parsed.path == "/api/grocery/status":
            # Public and deliberately blunt: the frontend must be able to
            # tell "this chain is expensive" apart from "we have barely any
            # data for this chain", and so must we when a deploy comes up
            # with an empty disk.
            summary = grocery_api.database_summary()
            summary["providers"] = grocery_api.provider_status()
            self.send_json(200, summary, cache_seconds=60)
            return
        if parsed.path == "/api/admin/grocery-import":
            if not ADMIN_TOKEN or not hmac.compare_digest(self.headers.get("X-Admin-Token", ""), ADMIN_TOKEN):
                self.send_json(403, {"error": "Admin-token krävs"})
                return
            self.send_json(200, {
                "import": grocery_importer.status(),
                "scheduler": GROCERY_SCHEDULER.status(),
                "providers": grocery_api.provider_status(),
            })
            return
        if parsed.path == "/api/auth/me":
            user = ACCOUNT_STORE.user_for_token(self._bearer_token())
            if not user:
                self.send_json(401, {"error": "Inte inloggad"})
            else:
                self.send_json(200, {"user": user})
            return
        if parsed.path == "/api/account/state":
            try:
                stored = ACCOUNT_STORE.get_synced_state(self._bearer_token())
                self.send_json(200, {"state": json.loads(stored) if stored else None})
            except AccountError as error:
                self.send_json(401, {"error": str(error)})
            return
        if parsed.path == "/api/v1/recipes/search":
            query = clean_text(parse_qs(parsed.query).get("q", [""])[0])
            if not 2 <= len(query) <= 100:
                self.send_json(400, {"error": "Ange en receptsökning på 2–100 tecken"})
                return
            try:
                recipes = [recipe.to_dict() for recipe in RECIPE_SERVICE.search(query)]
                self.send_json(200, {"recipes": recipes}, cache_seconds=900)
            except Exception:
                logger.exception("Recipe search failed for query %r", query)
                self.send_json(502, {"error": "Receptkällan svarar inte just nu"})
            return
        if parsed.path == "/api/v1/recipes/by-pantry":
            items = [clean_text(item) for item in parse_qs(parsed.query).get("items", [""])[0].split(",") if clean_text(item)]
            items = items[:30]
            if not items:
                self.send_json(400, {"error": "Ange minst en ingrediens"})
                return
            cache_key = tuple(sorted(item.lower() for item in items))
            cached = PANTRY_RECIPE_CACHE.get(cache_key)
            if cached and time.monotonic() - cached[1] < PANTRY_RECIPE_CACHE_TTL_SECONDS:
                self.send_json(200, {"recipes": cached[0]}, cache_seconds=PANTRY_RECIPE_CACHE_TTL_SECONDS)
                return
            try:
                pairs = RECIPE_SERVICE.search_by_pantry(items)
                recipes = [{**recipe.to_dict(), "matchedIngredients": matched} for recipe, matched in pairs]
                PANTRY_RECIPE_CACHE[cache_key] = (recipes, time.monotonic())
                self.send_json(200, {"recipes": recipes}, cache_seconds=PANTRY_RECIPE_CACHE_TTL_SECONDS)
            except Exception:
                logger.exception("Pantry-based recipe search failed for items %r", items)
                self.send_json(502, {"error": "Receptkällan svarar inte just nu"})
            return
        recipe_prefix = "/api/v1/recipes/"
        if parsed.path.startswith(recipe_prefix):
            recipe_id = unquote(parsed.path[len(recipe_prefix):])
            try:
                recipe = RECIPE_SERVICE.get(recipe_id)
                if not recipe:
                    self.send_json(404, {"error": "Receptet hittades inte"})
                else:
                    self.send_json(200, {"recipe": recipe.to_dict()}, cache_seconds=900)
            except Exception:
                logger.exception("Recipe lookup failed for id %r", recipe_id)
                self.send_json(502, {"error": "Receptkällan svarar inte just nu"})
            return
        if parsed.path == "/api/geocode":
            zip_code = clean_text(parse_qs(parsed.query).get("zip", [""])[0])
            if not re.fullmatch(r"\d{5}", zip_code):
                self.send_json(400, {"error": "Ange ett giltigt postnummer (5 siffror)"})
                return
            try:
                place = geocode_postcode(zip_code)
                if not place:
                    self.send_json(404, {"error": "Hittade inget postnummer med den koden"})
                else:
                    self.send_json(200, place, cache_seconds=GEOCODE_CACHE_TTL_SECONDS)
            except Exception:
                logger.exception("Geocoding failed for zip %s", zip_code)
                self.send_json(502, {"error": "Postnummerslagningen svarar inte just nu"})
            return
        if parsed.path == "/api/campaigns":
            self._handle_campaigns(parse_qs(parsed.query))
            return
        if parsed.path == "/api/stores":
            zip_code = clean_text(parse_qs(parsed.query).get("zip", [""])[0])
            if not re.fullmatch(r"\d{5}", zip_code):
                self.send_json(400, {"error": "Ange ett giltigt postnummer (5 siffror)"})
                return
            try:
                # The SERVER keeps its day-long cache - that is where the
                # expensive geocoding and store lookups are. The RESPONSE
                # must not, though: a 24h Cache-Control meant a browser kept
                # serving a day-old store list, so a chain we started
                # carrying (City Gross) stayed invisible for a day and a user
                # who moved kept seeing the old town's shops.
                self.send_json(200, {"butiker": nearby_stores(zip_code)},
                               cache_seconds=STORE_LIST_RESPONSE_CACHE_SECONDS)
            except Exception:
                logger.exception("Failed to compute nearby stores for zip %s", zip_code)
                self.send_json(502, {"error": "Kunde inte hitta butiker just nu"})
            return
        if parsed.path != "/api/products":
            if parsed.path.startswith("/api/"):
                self.send_json(404, {"error": "Okänd endpoint"})
            else:
                super().do_GET()
            return
        params = parse_qs(parsed.query)
        chain = params.get("butik", ["Willys"])[0]
        query = clean_text(params.get("q", [""])[0])
        zip_code = clean_text(params.get("zip", [DEFAULT_ZIP])[0]) or DEFAULT_ZIP
        store_key = store_key_param(params.get("butiksnyckel", [""])[0])
        if chain not in STORE_CONFIG or not 2 <= len(query) <= 100 or not re.fullmatch(r"\d{5}", zip_code):
            self.send_json(400, {"error": "Ange butik Willys/Hemköp och en sökning på minst två tecken"})
            return
        cache_zip = cache_scope(zip_code, store_key)
        cached, cached_at = cached_products(chain, query, cache_zip)
        if cached is not None:
            # Reused as-is for the full 24h window (see cached_products) -
            # re-scraping on every request is what made this unreliable, not
            # what made it accurate. uppdaterad lets the frontend say "Senast
            # uppdaterat X" instead of implying this is this-second-live.
            self.send_json(200, {"butik": chain, "sokning": query, "produkter": annotate_updated(cached, cached_at)}, cache_seconds=CACHE_TTL_SECONDS)
            return

        primat_products = fetch_from_primat(chain, query, zip_code, store_key=store_key)
        if primat_products:
            store_products(chain, query, cache_zip, primat_products)
            self.send_json(200, {"butik": chain, "sokning": query, "produkter": annotate_updated(primat_products, time.time())}, cache_seconds=CACHE_TTL_SECONDS)
            return

        def _scrape():
            page = new_scrape_page()
            try:
                return scrape_products(page, chain, query, zip_code)
            finally:
                page.close()

        try:
            products = run_on_scrape_thread(_scrape)
            if products:
                store_products(chain, query, cache_zip, products)
                products = annotate_updated(products, time.time())
            else:
                products = []
            self.send_json(200, {"butik": chain, "sokning": query, "produkter": products}, cache_seconds=CACHE_TTL_SECONDS)
        except Exception:
            logger.exception("Product scrape failed for %s/%s", chain, query)
            self.send_json(502, {"error": "Butikens webbsida kunde inte läsas"})

    def do_POST(self):
        self._json_response = False
        parsed = urlparse(self.path)
        if parsed.path == "/api/billing/webhook":
            self._handle_stripe_webhook()
            return
        try:
            payload = self._read_json_body()
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {"error": "Ogiltig JSON"})
            return
        if parsed.path == "/api/auth/register":
            if self._rate_limit("register", str(payload.get("email") or "").strip().lower()):
                return
            try:
                token, user = ACCOUNT_STORE.register(payload.get("email"), payload.get("password"))
                try:
                    verify_token = ACCOUNT_STORE.create_verification_token_for_email(user["email"])
                    send_email(
                        MAIL_CONFIG, user["email"], "Verifiera din e-postadress - Matjakt",
                        f"Välkommen till Matjakt!\n\nKlicka här för att verifiera din e-postadress:\n{APP_URL}/?verify={verify_token}\n\nOm du inte skapade det här kontot kan du ignorera mejlet.",
                    )
                except (AccountError, MailError):
                    logger.info("Could not send verification email for %s (email not configured or send failed)", user["email"])
                self.send_json(201, {"token": token, "user": user})
            except AccountError as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/auth/login":
            email = str(payload.get("email") or "").strip().lower()
            if self._rate_limit("login", email):
                return
            try:
                token, user = ACCOUNT_STORE.login(payload.get("email"), payload.get("password"))
                # A person who mistypes twice and then gets it right must not
                # stay throttled for the rest of the window.
                ratelimit.clear_on_success("login", self._client_ip(), email)
                self.send_json(200, {"token": token, "user": user})
            except AccountError as error:
                self.send_json(401, {"error": str(error)})
            return
        if parsed.path == "/api/auth/change-password":
            if self._rate_limit("change_password"):
                return
            try:
                user = ACCOUNT_STORE.change_password(
                    self._bearer_token(), payload.get("currentPassword"), payload.get("newPassword"))
                self.send_json(200, {"user": user})
            except AccountError as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/auth/logout":
            token = self._bearer_token()
            if token:
                ACCOUNT_STORE.logout(token)
            self.send_json(200, {"ok": True})
            return
        if parsed.path == "/api/auth/redeem":
            try:
                user = ACCOUNT_STORE.redeem_premium(self._bearer_token(), payload.get("code"), PREMIUM_CODE)
                self.send_json(200, {"user": user})
            except AccountError as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/auth/start-trial":
            try:
                user = ACCOUNT_STORE.start_trial(self._bearer_token())
                self.send_json(200, {"user": user})
            except AccountError as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/auth/request-password-reset":
            if self._rate_limit("password_reset", str(payload.get("email") or "").strip().lower()):
                return
            reset_token = ACCOUNT_STORE.request_password_reset(payload.get("email"))
            if reset_token:
                try:
                    send_email(
                        MAIL_CONFIG, (payload.get("email") or "").strip().lower(), "Återställ ditt Matjakt-lösenord",
                        f"Klicka här för att välja ett nytt lösenord:\n{APP_URL}/?reset={reset_token}\n\nLänken slutar gälla om en timme. Om du inte bad om detta kan du ignorera mejlet.",
                    )
                except MailError:
                    logger.exception("Failed to send password reset email")
            # Always respond the same way whether or not the email matched an account -
            # otherwise this endpoint could be used to check which emails have accounts.
            self.send_json(200, {"ok": True})
            return
        if parsed.path == "/api/auth/reset-password":
            if self._rate_limit("password_reset"):
                return
            try:
                ACCOUNT_STORE.reset_password(payload.get("token"), payload.get("password"))
                self.send_json(200, {"ok": True})
            except AccountError as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/auth/verify-email":
            try:
                user = ACCOUNT_STORE.verify_email(payload.get("token"))
                self.send_json(200, {"user": user})
            except AccountError as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/auth/resend-verification":
            try:
                email, verify_token = ACCOUNT_STORE.resend_verification(self._bearer_token())
                send_email(
                    MAIL_CONFIG, email, "Verifiera din e-postadress - Matjakt",
                    f"Klicka här för att verifiera din e-postadress:\n{APP_URL}/?verify={verify_token}",
                )
                self.send_json(200, {"ok": True})
            except AccountError as error:
                self.send_json(400, {"error": str(error)})
            except MailError as error:
                self.send_json(503, {"error": str(error)})
            return
        if parsed.path == "/api/auth/delete-account":
            try:
                stripe_customer_id, stripe_subscription_id = ACCOUNT_STORE.delete_account(self._bearer_token())
                if stripe_subscription_id and STRIPE_SECRET_KEY:
                    try:
                        cancel_subscription(STRIPE_SECRET_KEY, stripe_subscription_id)
                    except StripeError:
                        logger.exception("Failed to cancel Stripe subscription %s during account deletion", stripe_subscription_id)
                self.send_json(200, {"ok": True})
            except AccountError as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/account/state":
            if not isinstance(payload, dict):
                self.send_json(400, {"error": "Ogiltigt format"})
                return
            try:
                ACCOUNT_STORE.set_synced_state(self._bearer_token(), json.dumps(payload))
                self.send_json(200, {"ok": True})
            except AccountError as error:
                self.send_json(401, {"error": str(error)})
            return
        if parsed.path == "/api/billing/checkout":
            try:
                price_id = STRIPE_PRICE_YEARLY if payload.get("plan") == "yearly" else STRIPE_PRICE_MONTHLY
                if not price_id:
                    raise StripeError("Stripe-priser är inte konfigurerade på servern ännu")
                user_id, email, customer_id = ACCOUNT_STORE.billing_identity_for_token(self._bearer_token())
                if not customer_id:
                    customer_id = create_customer(STRIPE_SECRET_KEY, email, user_id)
                    ACCOUNT_STORE.set_stripe_customer_id(user_id, customer_id)
                url = create_checkout_session(
                    STRIPE_SECRET_KEY, customer_id, price_id,
                    success_url=f"{APP_URL}/?billing=success",
                    cancel_url=f"{APP_URL}/?billing=cancelled",
                )
                self.send_json(200, {"url": url})
            except (AccountError, StripeError) as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/billing/portal":
            try:
                customer_id = ACCOUNT_STORE.stripe_customer_id_for_token(self._bearer_token())
                url = create_portal_session(STRIPE_SECRET_KEY, customer_id, return_url=f"{APP_URL}/")
                self.send_json(200, {"url": url})
            except (AccountError, StripeError) as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/products/batch":
            self._handle_products_batch(payload)
            return
        if parsed.path == "/api/pricing/week":
            self._handle_pricing_week(payload)
            return
        if parsed.path == "/api/pricing/list":
            self._handle_pricing_list(payload)
            return
        if parsed.path == "/api/admin/grocery-import":
            if not ADMIN_TOKEN or not hmac.compare_digest(self.headers.get("X-Admin-Token", ""), ADMIN_TOKEN):
                self.send_json(403, {"error": "Admin-token krävs"})
                return
            chain = (payload or {}).get("chain")
            # ALL_STORES, not DEFAULT_STORES: an admin may refresh ICA by
            # hand. The scheduler still cannot reach it (see importer's
            # MANUAL_ONLY_STORES), which is the distinction that matters.
            if chain not in grocery_importer.ALL_STORES:
                self.send_json(400, {"error": f"Okänd kedja. Välj en av "
                                              f"{sorted(grocery_importer.ALL_STORES)}"})
                return
            self.send_json(200, grocery_importer.start(
                chain, store_id=(payload or {}).get("store"),
                limit_per_category=(payload or {}).get("perCategory")))
            return
        if parsed.path == "/api/analytics/event":
            self._handle_analytics_event(payload)
            return
        self.send_json(404, {"error": "Okänd endpoint"})

    # Prices are capped per request so one call can't walk the whole
    # database: a week's list is ~20-40 lines, and anything far beyond that
    # is a mistake or an abuse, not a shopping list.
    MAX_PRICING_ITEMS = 80

    def _pricing_items(self, payload):
        """Normalises the week's summed ingredient lines, dropping anything
        that isn't a usable {name, amount, unit}. Returns (items, error)."""
        if not isinstance(payload, dict):
            return None, "Ogiltig begäran"
        raw_items = payload.get("items") or payload.get("varor")
        if not isinstance(raw_items, list) or not raw_items:
            return None, "items saknas"
        if len(raw_items) > self.MAX_PRICING_ITEMS:
            return None, f"För många varor (max {self.MAX_PRICING_ITEMS})"
        items = []
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            name = clean_text(str(entry.get("name") or entry.get("namn") or ""))
            if not name:
                continue
            try:
                amount = float(entry.get("amount") if entry.get("amount") is not None
                               else entry.get("total") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            unit = clean_text(str(entry.get("unit") or entry.get("enhet") or "st")) or "st"
            items.append({"name": name, "amount": amount, "unit": unit})
        if not items:
            return None, "Inga giltiga varor"
        return items, None

    def _handle_pricing_week(self, payload):
        """Real checkout cost for a week's list, per chain, from Matjakt's own
        price database - not an estimate and not a live scrape.

        Never invents a price: an ingredient with no confident product match
        comes back in missingItems and lowers that chain's coverage. The
        comparison is allowed to stay undecided (cheapestChain null with a
        reason) rather than claim a cheapest chain the data can't support."""
        items, error = self._pricing_items(payload)
        if error:
            self.send_json(400, {"error": error})
            return
        chains = payload.get("chains") or payload.get("butiker")
        chains = [clean_text(str(c)) for c in chains if str(c).strip()] if isinstance(chains, list) else None
        pantry = payload.get("pantry") if isinstance(payload.get("pantry"), dict) else None
        try:
            self.send_json(200, grocery_api.price_week(items, chains, pantry))
        except Exception:
            logger.exception("Prissättning av veckan misslyckades")
            self.send_json(503, {"error": "Prisdatabasen är inte tillgänglig just nu"})

    def _handle_pricing_list(self, payload):
        """One chain's store-specific shopping list: the actual products to
        put in the basket, with image, pack size, package count and price."""
        items, error = self._pricing_items(payload)
        if error:
            self.send_json(400, {"error": error})
            return
        chain = clean_text(str(payload.get("chain") or payload.get("butik") or ""))
        if not chain:
            self.send_json(400, {"error": "chain saknas"})
            return
        pantry = payload.get("pantry") if isinstance(payload.get("pantry"), dict) else None
        try:
            self.send_json(200, grocery_api.shopping_list(items, chain, pantry))
        except Exception:
            logger.exception("Inköpslista misslyckades för %s", chain)
            self.send_json(503, {"error": "Prisdatabasen är inte tillgänglig just nu"})

    def _handle_analytics_event(self, payload):
        """Anonymous product-event counter for the landing page - a click on
        a specific CTA increments a per-day counter, nothing else. No account,
        no cookie, no IP address is recorded here (the OS/Render's own
        infrastructure logs may still see the request like any other, but
        this handler adds nothing identifying on top of that). Never allowed
        to affect page functionality - the frontend always fires this as a
        best-effort, catch-and-ignore call."""
        event = payload.get("event") if isinstance(payload, dict) else None
        if event not in ANALYTICS_ALLOWED_EVENTS:
            self.send_json(400, {"error": "Okänt event"})
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"{event}:{today}"
        count, _ = KV_CACHE.get("analytics", key)
        KV_CACHE.set("analytics", key, (count or 0) + 1)
        self.send_json(200, {"ok": True})

    def _handle_campaigns(self, params):
        user = ACCOUNT_STORE.user_for_token(self._bearer_token())
        if not user or not user.get("premium"):
            self.send_json(403, {"error": "Kampanjer kräver Premium"})
            return
        chain = params.get("butik", [""])[0]
        zip_code = clean_text(params.get("zip", [DEFAULT_ZIP])[0]) or DEFAULT_ZIP
        if chain not in CAMPAIGN_CAPABLE_CHAINS or not re.fullmatch(r"\d{5}", zip_code):
            self.send_json(400, {"error": "Kampanjer stöds just nu bara för Coop och Hemköp"})
            return
        cache_key = f"{chain}:{zip_code}"
        cached, cached_at = KV_CACHE.get("campaigns", cache_key)
        if cached is not None and time.time() - cached_at < CAMPAIGN_CACHE_TTL_SECONDS:
            self.send_json(200, {"butik": chain, "kampanjer": cached}, cache_seconds=CAMPAIGN_CACHE_TTL_SECONDS)
            return
        def _scrape():
            found = []
            page = new_scrape_page()
            try:
                for ingredient in CAMPAIGN_SCAN_INGREDIENTS:
                    cached_ingredient, cached_ingredient_at = cached_products(chain, ingredient, zip_code)
                    if cached_ingredient is not None:
                        products = cached_ingredient
                    else:
                        products = fetch_from_primat(chain, ingredient, zip_code)
                        if not products:
                            try:
                                products = scrape_products(page, chain, ingredient, zip_code)
                            except Exception:
                                logger.exception("Campaign scan failed for %s/%s", chain, ingredient)
                                products = []
                        if products:
                            store_products(chain, ingredient, zip_code, products)
                    on_offer = next((product for product in products if product.get("kampanj") and ingredient.lower() in product["produktnamn"].lower()), None)
                    # Same Primat-first/OFF-fallback/local-icon priority as every
                    # other product image in the app - campaign cards were the one
                    # place this wasn't applied, so a Primat-sourced deal (no image
                    # from Primat itself) would silently render with no picture at
                    # all instead of falling through to Open Food Facts.
                    if on_offer:
                        on_offer = fill_missing_image(on_offer)
                    if on_offer:
                        found.append({"ingrediens": ingredient, **on_offer})
            finally:
                page.close()
            return found

        try:
            deals = run_on_scrape_thread(_scrape)
            KV_CACHE.set("campaigns", cache_key, deals)
            self.send_json(200, {"butik": chain, "kampanjer": deals}, cache_seconds=CAMPAIGN_CACHE_TTL_SECONDS)
        except Exception:
            logger.exception("Campaign scan session failed for %s", chain)
            # A stale cached list (of any age, not just within the normal 1h
            # freshness window - see KV_CACHE.get) is a more honest answer
            # than an outright error when a fresh scan just failed: real
            # deals from earlier today, clearly timestamped, beat nothing.
            stale, stale_at = KV_CACHE.get("campaigns", cache_key)
            if stale is not None:
                self.send_json(200, {"butik": chain, "kampanjer": stale, "senastKantPris": True, "uppdaterad": stale_at}, cache_seconds=0)
            else:
                self.send_json(502, {"error": "Butikens webbsida kunde inte läsas"})

    def _handle_products_batch(self, payload):
        chain = payload.get("butik")
        zip_code = clean_text(str(payload.get("zip") or DEFAULT_ZIP)) or DEFAULT_ZIP
        store_key = store_key_param(payload.get("butiksnyckel"))
        # Used by the store-comparison list, which fetches every nearby
        # branch's own price (not just the chain's generic door - see
        # syncBranchComparison) - with a dozen branches that's a dozen calls,
        # and unlike a single pinned branch's list, scraping can't actually
        # answer any of them differently from each other (a scrape has no
        # concept of "this specific store", only Primat's store_key does -
        # see cache_scope's docstring). Falling through to a real Chromium
        # scrape per branch would be pure waste (identical, non-branch-
        # specific results, N times over) and exactly the kind of repeated
        # heavy-scrape load that caused the OOM this endpoint is guarded
        # against elsewhere - so this flag stops at Primat/cache and skips
        # scraping entirely, leaving unanswered branches to their honest
        # static estimate instead.
        primat_only = bool(payload.get("primatOnly"))
        items = payload.get("varor")
        if chain not in STORE_CONFIG or not re.fullmatch(r"\d{5}", zip_code) or not isinstance(items, list) or not items:
            self.send_json(400, {"error": "Ange butik, giltigt postnummer och en lista med varor"})
            return
        seen, queries = set(), []
        for raw in items:
            query = clean_text(str(raw))[:100]
            if 2 <= len(query) <= 100 and query.lower() not in seen:
                seen.add(query.lower())
                queries.append(query)
        queries = queries[:MAX_BATCH_ITEMS]
        if not queries:
            self.send_json(400, {"error": "Inga giltiga varunamn angavs"})
            return

        cache_zip = cache_scope(zip_code, store_key)
        results, to_scrape = {}, []
        for query in queries:
            cached, cached_at = cached_products(chain, query, cache_zip)
            if cached is not None:
                results[query] = stamp_match(best_match(cached, query), cached_at)
            else:
                to_scrape.append(query)

        # Primat first for anything not already cached - a fast, ordinary
        # HTTPS call (no headless browser), so it runs inline here rather
        # than through run_on_scrape_thread's Playwright-oriented worker
        # pool. Only queries Primat couldn't answer fall through to scraping
        # (see fetch_from_primat's docstring for why "nothing" and
        # "unreachable" are treated the same way). Each query is guarded by
        # its own lock (see _lock_for_product_key) so a second concurrent
        # request for the same (chain, query, cache_zip) waits and reuses
        # this result instead of re-fetching it too.
        still_to_scrape = []
        for query in to_scrape:
            with _lock_for_product_key((chain, query.lower(), cache_zip)):
                cached, cached_at = cached_products(chain, query, cache_zip)
                if cached is not None:
                    results[query] = stamp_match(best_match(cached, query), cached_at)
                    continue
                primat_products = fetch_from_primat(chain, query, zip_code, store_key=store_key)
                if primat_products:
                    store_products(chain, query, cache_zip, primat_products)
                    results[query] = stamp_match(best_match(primat_products, query), time.time())
                else:
                    still_to_scrape.append(query)
        to_scrape = still_to_scrape

        if to_scrape and primat_only:
            for query in to_scrape:
                results[query] = None
            to_scrape = []

        if to_scrape:
            def _scrape():
                page = new_scrape_page()
                try:
                    for query in to_scrape:
                        with _lock_for_product_key((chain, query.lower(), cache_zip)):
                            # Re-check cache - another request may have
                            # scraped (or Primat-fetched) this exact item
                            # while this one waited for the lock.
                            cached, cached_at = cached_products(chain, query, cache_zip)
                            if cached is not None:
                                results[query] = stamp_match(best_match(cached, query), cached_at)
                                continue
                            try:
                                products = scrape_products(page, chain, query, zip_code)
                            except Exception:
                                logger.exception("Batch scrape failed for %s/%s", chain, query)
                                products = []
                            if products:
                                store_products(chain, query, cache_zip, products)
                                results[query] = stamp_match(best_match(products, query), time.time())
                            else:
                                results[query] = None
                finally:
                    page.close()

            try:
                run_on_scrape_thread(_scrape)
            except Exception:
                logger.exception("Batch scrape session failed for %s", chain)
                for query in to_scrape:
                    results.setdefault(query, None)

        # A query that still has no answer (no confident match, or the fetch
        # itself failed) falls back to whatever was last known for it -
        # of any age, not just within the normal freshness window - labeled
        # "senastKantPris" so the frontend shows "Senast känt pris <tid>"
        # rather than silently passing an old number off as current. Real,
        # honestly-aged data beats an empty "Pris saknas" row when one exists.
        for query, result in results.items():
            if result is None:
                stale, stale_at = stale_products(chain, query, cache_zip)
                if stale is not None:
                    matched = best_match(stale, query)
                    if matched:
                        results[query] = {**stamp_match(matched, stale_at), "senastKantPris": True}

        self.send_json(200, {"butik": chain, "produkter": results})


def _close_thread_browser():
    if getattr(_thread_browser, "browser", None) is not None:
        _thread_browser.browser.close()
        _thread_browser.browser = None
    if getattr(_thread_browser, "playwright", None) is not None:
        _thread_browser.playwright.stop()
        _thread_browser.playwright = None


if __name__ == "__main__":
    print(f"Matjakt API kör på http://{HOST}:{PORT}")
    # Launch each scrape worker thread's own browser in the background at
    # startup rather than waiting for the first request on that thread to pay
    # the 1-3s Chromium cold-start cost.
    for _ in range(MAX_CONCURRENT_SCRAPES):
        _scrape_executor.submit(get_shared_browser)
    # Off unless MATJAKT_GROCERY_SCHEDULE_ENABLED is set, so a local dev run
    # never starts fetching from three chains on its own.
    GROCERY_SCHEDULER.start()
    try:
        ThreadingHTTPServer((HOST, PORT), ApiHandler).serve_forever()
    finally:
        for _ in range(MAX_CONCURRENT_SCRAPES):
            _scrape_executor.submit(_close_thread_browser)
        _scrape_executor.shutdown(wait=True)
