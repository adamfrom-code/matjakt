"""Local product API for Matjakt.

The store websites do not publish a stable public API. This service uses
Playwright against their public shopping pages and returns one normalized
shape to the frontend. Keep request volume low and check each store's terms
before deploying this publicly.
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from playwright.sync_api import sync_playwright

HOST = "127.0.0.1"
PORT = 8000
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
}
CACHE = {}


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def parse_price(text):
    match = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:kr|:-)", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def parse_willys_price(text):
    match = re.search(r"(\d+)\s+(\d{2})", clean_text(text))
    return float(f"{match.group(1)}.{match.group(2)}") if match else parse_price(text)


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
            brand = clean_text(brand_node.first.inner_text()) if brand_node.count() else ""
            volume_node = card.locator('[data-testid="display-volume"]')
            if volume_node.count():
                brand = f"{brand} {clean_text(volume_node.first.inner_text())}".strip()
            image_node = card.locator("img").first
            image = image_node.get_attribute("src") if image_node.count() else ""
            key = (name, price, href)
            if key in seen:
                continue
            seen.add(key)
            products.append({"kedja": chain, "produktnamn": name, "marke_och_storlek": brand, "bild": image or "", "pris_kr": price, "storlek": "", "lager": True, "url": href if href.startswith("http") else f"{config['base_url']}{href}", "sokning": query})
        if products:
            break
    return products[:20]


class ApiHandler(BaseHTTPRequestHandler):
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
            self.send_json(200, {"ok": True, "stores": sorted(STORE_CONFIG)})
            return
        if parsed.path != "/api/products":
            self.send_json(404, {"error": "Okänd endpoint"})
            return
        params = parse_qs(parsed.query)
        chain = params.get("butik", ["Willys"])[0]
        query = clean_text(params.get("q", [""])[0])
        if chain not in STORE_CONFIG or len(query) < 2:
            self.send_json(400, {"error": "Ange butik Willys/Hemköp och en sökning på minst två tecken"})
            return
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(locale="sv-SE")
                products = parse_products(page, chain, query)
                browser.close()
            cache_key = (chain, query.lower())
            if products:
                CACHE[cache_key] = products
            else:
                products = CACHE.get(cache_key, [])
            self.send_json(200, {"butik": chain, "sokning": query, "produkter": products})
        except Exception as error:
            self.send_json(502, {"error": "Butikens webbsida kunde inte läsas", "detail": str(error)})


if __name__ == "__main__":
    print(f"Matjakt API kör på http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), ApiHandler).serve_forever()
