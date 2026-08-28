"""Local product API for Matjakt.

The store websites do not publish a stable public API. This service uses
Playwright against their public shopping pages and returns one normalized
shape to the frontend. Keep request volume low and check each store's terms
before deploying this publicly.
"""

import json
import logging
import math
import os
import re
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright
from services.accounts import AccountError, AccountStore
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
ALLOWED_ORIGIN = os.environ.get("MATJAKT_FRONTEND_ORIGIN", "http://localhost:5500")
CACHE_TTL_SECONDS = 900
ICA_STORE_FAILURE_TTL_SECONDS = 300
ICA_STORE_SUCCESS_TTL_SECONDS = 3600
CACHE_MAX_ENTRIES = 200
MAX_CONCURRENT_SCRAPES = 3
MAX_BATCH_ITEMS = 20
PANTRY_RECIPE_CACHE_TTL_SECONDS = 1800
CAMPAIGN_CACHE_TTL_SECONDS = 3600
CAMPAIGN_CAPABLE_CHAINS = ("Coop", "Hemköp")
CAMPAIGN_SCAN_INGREDIENTS = ["Kycklingfilé", "Kycklinglårfilé", "Köttfärs", "Biff", "Fläskfilé", "Laxfilé", "Fryst torsk", "Räkor", "Kalvschnitzel", "Falukorv", "Halloumi"]
GEOCODE_CACHE_TTL_SECONDS = 86400
PREMIUM_CODE = os.environ.get("MATJAKT_PREMIUM_CODE", "")
AXFOOD_STORE_LIST_URL = {"Willys": "https://www.willys.se/axfood/rest/v1/store", "Hemköp": "https://www.hemkop.se/axfood/rest/v1/store"}
STORE_LIST_CACHE_TTL_SECONDS = 86400
ICA_STORE_LIST_TTL_SECONDS = 3600
COOP_STORE_SEARCH_TTL_SECONDS = 86400
NEARBY_STORE_LIMIT = 12
NEARBY_STORE_RADIUS_KM = 60

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
ICA_STORE_CACHE = {}
CACHE = {}
PANTRY_RECIPE_CACHE = {}
CAMPAIGN_CACHE = {}
GEOCODE_CACHE = {}
STORE_LIST_CACHE = {}
COOP_STORE_SEARCH_CACHE = {}
SCRAPE_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_SCRAPES)
RECIPE_SERVICE = RecipeService([TheMealDbProvider()])
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
ACCOUNT_STORE = AccountStore(Path(__file__).resolve().parent / "data" / "matjakt.db")


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
    forever in-process since postal geography doesn't change day to day."""
    cached = GEOCODE_CACHE.get(zip_code)
    if cached and time.monotonic() - cached[1] < GEOCODE_CACHE_TTL_SECONDS:
        return cached[0]
    request = Request(f"http://api.zippopotam.us/SE/{zip_code}", headers={"User-Agent": "Matjakt/1.0"})
    with urlopen(request, timeout=8) as response:
        data = json.load(response)
    place = (data.get("places") or [None])[0]
    if not place:
        return None
    result = {"ort": place.get("place name", ""), "lat": float(place["latitude"]), "lon": float(place["longitude"])}
    GEOCODE_CACHE[zip_code] = (result, time.monotonic())
    return result


def ica_stores_for_zip(page, zip_code):
    """ICA has no search results at all until a pickup/delivery store is chosen
    for a postnummer. Found via live network inspection: this JSON endpoint
    backs their own "Välj butik" widget, so it's the same data they use. Returns
    every store ICA offers for the zip (used both to pick one for product
    scraping and to list real nearby branches)."""
    cached = ICA_STORE_CACHE.get(zip_code)
    if cached is not None and time.monotonic() < cached[1]:
        return cached[0]
    page.goto(f"https://handla.ica.se/api/store/v1?zip={quote(zip_code)}&customerType=B2C", wait_until="domcontentloaded", timeout=15000)
    try:
        data = json.loads(page.locator("pre").inner_text())
    except Exception:
        logger.exception("Failed to parse ICA store lookup response for zip %s", zip_code)
        data = {}
    stores = data.get("forPickupDelivery") or data.get("forHomeDelivery") or []
    ttl = ICA_STORE_SUCCESS_TTL_SECONDS if stores else ICA_STORE_FAILURE_TTL_SECONDS
    ICA_STORE_CACHE[zip_code] = (stores, time.monotonic() + ttl)
    return stores


def resolve_ica_store(page, zip_code):
    stores = ica_stores_for_zip(page, zip_code)
    return stores[0] if stores else None


def haversine_km(lat1, lon1, lat2, lon2):
    earth_radius = 6371
    lat_delta, lon_delta = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(lat_delta / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(lon_delta / 2) ** 2
    return earth_radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_axfood_stores(chain):
    """Willys and Hemköp (both Axfood brands) expose their full national store
    list at this undocumented-but-public, unauthenticated REST endpoint - found
    via live network inspection of "Hitta butik". Cached for a day since store
    locations essentially never change."""
    cached = STORE_LIST_CACHE.get(chain)
    if cached and time.monotonic() - cached[1] < STORE_LIST_CACHE_TTL_SECONDS:
        return cached[0]
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
    STORE_LIST_CACHE[chain] = (stores, time.monotonic())
    return stores


def search_coop_stores(page, city):
    """Coop's store search needs a real browser session (their API sits behind
    an Azure APIM subscription key that's only attached by their own frontend
    JS), so - like ICA - this drives their real "Butiker" search and reads the
    same response their page renders from, instead of replicating the request."""
    cached = COOP_STORE_SEARCH_CACHE.get(city)
    if cached and time.monotonic() - cached[1] < COOP_STORE_SEARCH_TTL_SECONDS:
        return cached[0]
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
    COOP_STORE_SEARCH_CACHE[city] = (stores, time.monotonic())
    return stores


def nearby_stores(zip_code):
    place = geocode_postcode(zip_code)
    if not place:
        return []
    lat, lon = place["lat"], place["lon"]
    candidates = [*fetch_axfood_stores("Willys"), *fetch_axfood_stores("Hemköp")]
    try:
        with SCRAPE_SEMAPHORE:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(locale="sv-SE")
                    for store in ica_stores_for_zip(page, zip_code):
                        s_lat, s_lon = store.get("latitude"), store.get("longitude")
                        if s_lat and s_lon:
                            candidates.append({"kedja": "ICA", "namn": store.get("name") or "", "lat": s_lat, "lon": s_lon, "ort": (store.get("address") or {}).get("city") or ""})
                    candidates.extend(search_coop_stores(page, place["ort"]))
                finally:
                    browser.close()
    except Exception:
        logger.exception("Failed to resolve ICA/Coop stores for zip %s", zip_code)
    for store in candidates:
        store["avstandKm"] = round(haversine_km(lat, lon, store["lat"], store["lon"]), 1)
    nearby = sorted((s for s in candidates if s["avstandKm"] <= NEARBY_STORE_RADIUS_KM), key=lambda s: s["avstandKm"])
    return nearby[:NEARBY_STORE_LIMIT]


def parse_ica_products(page, query, zip_code):
    store = resolve_ica_store(page, zip_code)
    if not store:
        return []
    account_id = store["accountId"]
    base_url = f"https://handlaprivatkund.ica.se/stores/{account_id}"
    page.goto(f"{base_url}/search?q={quote(query)}", wait_until="domcontentloaded", timeout=30000)
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


def cached_products(chain, query, zip_code):
    """Returns (products, is_fresh) for a cache entry, or (None, False) if absent."""
    cached = CACHE.get((chain, query.lower(), zip_code))
    if not cached:
        return None, False
    return cached[0], time.monotonic() - cached[1] < CACHE_TTL_SECONDS


def store_products(chain, query, zip_code, products):
    CACHE[(chain, query.lower(), zip_code)] = (products, time.monotonic())
    if len(CACHE) > CACHE_MAX_ENTRIES:
        del CACHE[min(CACHE, key=lambda key: CACHE[key][1])]


def scrape_products(page, chain, query, zip_code):
    return parse_ica_products(page, query, zip_code) if chain == "ICA" else parse_products(page, chain, query)


def best_match(products, query):
    """Search results are sorted by relevance, not name accuracy, so a plain
    "first result" can be a wrong department entirely (e.g. "Paprika" matching
    a paprika-flavoured cracker). Prefer a result whose name actually starts
    with the ingredient before falling back to whatever ranked first."""
    if not products:
        return None
    query_lower = query.strip().lower()
    starts_with = [product for product in products if product["produktnamn"].lower().startswith(query_lower)]
    return (starts_with or products)[0]


class ApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def send_json(self, status, payload, cache_seconds=None):
        self._json_response = True
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
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
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def _bearer_token(self):
        header = self.headers.get("Authorization", "")
        return header[7:] if header.lower().startswith("bearer ") else None

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        return json.loads(raw)

    def do_GET(self):
        self._json_response = False
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json(200, {"ok": True, "stores": sorted(STORE_CONFIG), "recipeProviders": sorted(RECIPE_SERVICE.providers)}, cache_seconds=900)
            return
        if parsed.path == "/api/auth/me":
            user = ACCOUNT_STORE.user_for_token(self._bearer_token())
            if not user:
                self.send_json(401, {"error": "Inte inloggad"})
            else:
                self.send_json(200, {"user": user})
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
                self.send_json(200, {"butiker": nearby_stores(zip_code)}, cache_seconds=STORE_LIST_CACHE_TTL_SECONDS)
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
        if chain not in STORE_CONFIG or not 2 <= len(query) <= 100 or not re.fullmatch(r"\d{5}", zip_code):
            self.send_json(400, {"error": "Ange butik Willys/Hemköp och en sökning på minst två tecken"})
            return
        cached, fresh = cached_products(chain, query, zip_code)
        if fresh:
            self.send_json(200, {"butik": chain, "sokning": query, "produkter": cached}, cache_seconds=CACHE_TTL_SECONDS)
            return
        try:
            with SCRAPE_SEMAPHORE:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(locale="sv-SE")
                        products = scrape_products(page, chain, query, zip_code)
                    finally:
                        browser.close()
            if products:
                store_products(chain, query, zip_code, products)
            else:
                products = cached or []
            self.send_json(200, {"butik": chain, "sokning": query, "produkter": products}, cache_seconds=CACHE_TTL_SECONDS)
        except Exception:
            logger.exception("Product scrape failed for %s/%s", chain, query)
            if cached:
                self.send_json(200, {"butik": chain, "sokning": query, "produkter": cached}, cache_seconds=CACHE_TTL_SECONDS)
            else:
                self.send_json(502, {"error": "Butikens webbsida kunde inte läsas"})

    def do_POST(self):
        self._json_response = False
        parsed = urlparse(self.path)
        try:
            payload = self._read_json_body()
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {"error": "Ogiltig JSON"})
            return
        if parsed.path == "/api/auth/register":
            try:
                token, user = ACCOUNT_STORE.register(payload.get("email"), payload.get("password"))
                self.send_json(201, {"token": token, "user": user})
            except AccountError as error:
                self.send_json(400, {"error": str(error)})
            return
        if parsed.path == "/api/auth/login":
            try:
                token, user = ACCOUNT_STORE.login(payload.get("email"), payload.get("password"))
                self.send_json(200, {"token": token, "user": user})
            except AccountError as error:
                self.send_json(401, {"error": str(error)})
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
        if parsed.path == "/api/products/batch":
            self._handle_products_batch(payload)
            return
        self.send_json(404, {"error": "Okänd endpoint"})

    def _handle_campaigns(self, params):
        chain = params.get("butik", [""])[0]
        zip_code = clean_text(params.get("zip", [DEFAULT_ZIP])[0]) or DEFAULT_ZIP
        if chain not in CAMPAIGN_CAPABLE_CHAINS or not re.fullmatch(r"\d{5}", zip_code):
            self.send_json(400, {"error": "Kampanjer stöds just nu bara för Coop och Hemköp"})
            return
        cache_key = (chain, zip_code)
        cached = CAMPAIGN_CACHE.get(cache_key)
        if cached and time.monotonic() - cached[1] < CAMPAIGN_CACHE_TTL_SECONDS:
            self.send_json(200, {"butik": chain, "kampanjer": cached[0]}, cache_seconds=CAMPAIGN_CACHE_TTL_SECONDS)
            return
        deals = []
        try:
            with SCRAPE_SEMAPHORE:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(locale="sv-SE")
                        for ingredient in CAMPAIGN_SCAN_INGREDIENTS:
                            cached_ingredient, fresh = cached_products(chain, ingredient, zip_code)
                            if fresh:
                                products = cached_ingredient
                            else:
                                try:
                                    products = scrape_products(page, chain, ingredient, zip_code)
                                except Exception:
                                    logger.exception("Campaign scan failed for %s/%s", chain, ingredient)
                                    products = cached_ingredient or []
                                if products:
                                    store_products(chain, ingredient, zip_code, products)
                            on_offer = next((product for product in products if product.get("kampanj") and ingredient.lower() in product["produktnamn"].lower()), None)
                            if on_offer:
                                deals.append({"ingrediens": ingredient, **on_offer})
                    finally:
                        browser.close()
            CAMPAIGN_CACHE[cache_key] = (deals, time.monotonic())
            self.send_json(200, {"butik": chain, "kampanjer": deals}, cache_seconds=CAMPAIGN_CACHE_TTL_SECONDS)
        except Exception:
            logger.exception("Campaign scan session failed for %s", chain)
            if cached:
                self.send_json(200, {"butik": chain, "kampanjer": cached[0]}, cache_seconds=CAMPAIGN_CACHE_TTL_SECONDS)
            else:
                self.send_json(502, {"error": "Butikens webbsida kunde inte läsas"})

    def _handle_products_batch(self, payload):
        chain = payload.get("butik")
        zip_code = clean_text(str(payload.get("zip") or DEFAULT_ZIP)) or DEFAULT_ZIP
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

        results, to_scrape = {}, []
        for query in queries:
            cached, fresh = cached_products(chain, query, zip_code)
            if fresh:
                results[query] = best_match(cached, query)
            else:
                to_scrape.append((query, cached))

        if to_scrape:
            try:
                with SCRAPE_SEMAPHORE:
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        try:
                            page = browser.new_page(locale="sv-SE")
                            for query, cached in to_scrape:
                                try:
                                    products = scrape_products(page, chain, query, zip_code)
                                except Exception:
                                    logger.exception("Batch scrape failed for %s/%s", chain, query)
                                    products = []
                                if products:
                                    store_products(chain, query, zip_code, products)
                                else:
                                    products = cached or []
                                results[query] = best_match(products, query)
                        finally:
                            browser.close()
            except Exception:
                logger.exception("Batch scrape session failed for %s", chain)
                for query, cached in to_scrape:
                    results.setdefault(query, best_match(cached, query) if cached else None)

        self.send_json(200, {"butik": chain, "produkter": results})


if __name__ == "__main__":
    print(f"Matjakt API kör på http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), ApiHandler).serve_forever()
