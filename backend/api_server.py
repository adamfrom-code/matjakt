"""Local product API for Matjakt.

The store websites do not publish a stable public API. This service uses
Playwright against their public shopping pages and returns one normalized
shape to the frontend. Keep request volume low and check each store's terms
before deploying this publicly.
"""

import json
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from playwright.sync_api import sync_playwright
from services.recipe_providers import RecipeService, TheMealDbProvider

HOST = os.environ.get("MATJAKT_HOST", "127.0.0.1")
PORT = int(os.environ.get("MATJAKT_PORT", "8000"))
ALLOWED_ORIGIN = os.environ.get("MATJAKT_FRONTEND_ORIGIN", "http://localhost:5500")

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
    # ICA/Coop selectors below are best-effort guesses, same as ica_scraper.py /
    # coop_scraper.py. Verify against the live site with DevTools before relying
    # on them - see README.md "Kom igång (backend/scraping)".
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
RECIPE_SERVICE = RecipeService([TheMealDbProvider()])
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def parse_price(text):
    match = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:kr|:-)", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def parse_willys_price(text):
    match = re.search(r"(\d+)\s+(\d{2})", clean_text(text))
    return float(f"{match.group(1)}.{match.group(2)}") if match else parse_price(text)


def resolve_ica_store(page, zip_code):
    """ICA has no search results at all until a pickup/delivery store is chosen
    for a postnummer. Found via live network inspection: this JSON endpoint
    backs their own "Välj butik" widget, so it's the same data they use."""
    if zip_code in ICA_STORE_CACHE:
        return ICA_STORE_CACHE[zip_code]
    page.goto(f"https://handla.ica.se/api/store/v1?zip={quote(zip_code)}&customerType=B2C", wait_until="domcontentloaded", timeout=15000)
    try:
        data = json.loads(page.locator("pre").inner_text())
    except Exception:
        data = {}
    stores = data.get("forPickupDelivery") or data.get("forHomeDelivery") or []
    store = stores[0] if stores else None
    ICA_STORE_CACHE[zip_code] = store
    return store


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
            image = image_node.get_attribute("src") if image_node.count() else ""
            if image.startswith("//"):
                image = f"https:{image}"
            key = (name, price, href)
            if key in seen:
                continue
            seen.add(key)
            products.append({"kedja": "ICA", "produktnamn": name, "marke_och_storlek": store["name"], "bild": image or "", "pris_kr": price, "storlek": "", "lager": True, "url": f"https://handlaprivatkund.ica.se{href}", "sokning": query})
        if products:
            break
    return products[:20]


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
            aria_parts = []
            if not name:
                # Coop's product link only wraps the image; the name/brand/size
                # live in the link's aria-label instead, e.g. "Mellanmjölk, Coop,
                # 1.5 l, Pris 16 kronor och 27 öre styck, ...".
                aria_parts = [clean_text(p) for p in (link.get_attribute("aria-label") or "").split(",")]
                name = aria_parts[0] if aria_parts else ""
            brand = clean_text(brand_node.first.inner_text()) if brand_node.count() else ""
            if not brand and len(aria_parts) > 2:
                brand = f"{aria_parts[1]} {aria_parts[2]}".strip()
            volume_node = card.locator('[data-testid="display-volume"]')
            if volume_node.count():
                brand = f"{brand} {clean_text(volume_node.first.inner_text())}".strip()
            image_node = card.locator("img").first
            image = image_node.get_attribute("src") if image_node.count() else ""
            if image.startswith("//"):
                image = f"https:{image}"
            key = (name, price, href)
            if key in seen:
                continue
            seen.add(key)
            products.append({"kedja": chain, "produktnamn": name, "marke_och_storlek": brand, "bild": image or "", "pris_kr": price, "storlek": "", "lager": True, "url": href if href.startswith("http") else f"{config['base_url']}{href}", "sokning": query})
        if products:
            break
    return products[:20]


class ApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Cache-Control", "public, max-age=900")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json(200, {"ok": True, "stores": sorted(STORE_CONFIG), "recipeProviders": sorted(RECIPE_SERVICE.providers)})
            return
        if parsed.path == "/api/v1/recipes/search":
            query = clean_text(parse_qs(parsed.query).get("q", [""])[0])
            if not 2 <= len(query) <= 100:
                self.send_json(400, {"error": "Ange en receptsökning på 2–100 tecken"})
                return
            try:
                recipes = [recipe.to_dict() for recipe in RECIPE_SERVICE.search(query)]
                self.send_json(200, {"recipes": recipes})
            except Exception:
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
                    self.send_json(200, {"recipe": recipe.to_dict()})
            except Exception:
                self.send_json(502, {"error": "Receptkällan svarar inte just nu"})
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
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(locale="sv-SE")
                products = parse_ica_products(page, query, zip_code) if chain == "ICA" else parse_products(page, chain, query)
                browser.close()
            cache_key = (chain, query.lower(), zip_code)
            if products:
                CACHE[cache_key] = products
            else:
                products = CACHE.get(cache_key, [])
            self.send_json(200, {"butik": chain, "sokning": query, "produkter": products})
        except Exception:
            self.send_json(502, {"error": "Butikens webbsida kunde inte läsas"})


if __name__ == "__main__":
    print(f"Matjakt API kör på http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), ApiHandler).serve_forever()
