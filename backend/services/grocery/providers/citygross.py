"""City Gross provider - plain HTTP/JSON against citygross.se's public API.
No authentication, no key, no cookie, no session, no browser.

=============================================================================
INVESTIGATION FINDINGS (verified live, 2026-08-30)
=============================================================================
City Gross exposes the RICHEST data of the four chains looked at so far - an
explicit gtin field, explicit ordinary/member/promotion prices, and real
category names. Nothing below is derived or guessed.

STORE LIST (two endpoints, both needed)
  GET /api/v1/sites?siteTypeId=3
      -> {"sites": [...]} with the field the search endpoint actually wants:
         storeNumber ("3209" for City Gross Gävle). id (35) and siteId are
         NOT accepted by the search endpoint - verified: passing either
         returns products: [] while a correct storeNumber returns results.
  GET /api/v1/PageData/stores
      -> 38 store pages carrying storeLocation.coordinates ("57.71,12.86"),
         address and opening hours. Merged with the above by store name,
         since only this one has coordinates and only the other one has
         storeNumber.

PRODUCT SEARCH (real pagination)
  GET /api/v1/Loop54/search?SearchQuery={q}&skip={n}&store={storeNumber}&take={n}
      -> {"searchResults": {"products": [...], "totalCount", "pageSize",
          "currentPage", "totalPages", "categories", "facets", ...}}
  There is also /api/v1/Loop54/search/quick/?SearchQuery={q} (used by the
  type-ahead) which returns products but WITHOUT store scoping.

FIELDS CONFIRMED PRESENT on a product:
  id ("101233933_ST"), gtin ("7340083443893" - 13 digits, see below), name,
  subtitle ("1,5L 1,5% GARANT"), description, brand ("GARANT"),
  superCategory ("Mejeri, ost & ägg"), category ("Mjölk & dryck"),
  bfCategory ("Mellanmjölk"), countryOfOrigin, descriptiveSize ("1,5L"),
  netContent {unitOfMeasure, value}, url (product page path),
  images [{url: "VI_7340083443893...jpeg", alt, type}],
  productStoreDetails {...} - see below.

GTIN IS EXPLICIT, BUT 13-DIGIT - normalisation matters:
  City Gross returns EAN-13 ("7340083443893") while the Axfood chains'
  image-derived codes are GTIN-14 ("07340083443893"). These are the SAME
  product. Without zero-padding to 14, cross-chain matching silently fails
  and the same item gets two rows. normalize_gtin14() below handles it, and
  the checksum is validated the same way as for Axfood (leading zeros do not
  affect the GS1 check digit).

PRICES - the most explicit of any chain (productStoreDetails.prices):
  currentPrice   {price, unit, comparativePrice, comparativePriceUnit}
  ordinaryPrice  {price, ...}          - the undiscounted price
  memberPrice    - an explicit field (null when there is none)
  promotions[] / activePromotion
  hasDiscount / hasPromotion
  lowestPriceLast30Days                - EU price-history disclosure
  Sibling flags: p_has_price, p_has_members_only_price,
  p_has_current_week_only_discount, p_has_long_time_discount.

  Mapping used here:
    regular_price  = ordinaryPrice.price (falls back to currentPrice.price)
    campaign_price = currentPrice.price, but ONLY when it is actually lower
                     than the ordinary price - otherwise "current" is just
                     the normal price and recording it as a campaign would
                     invent a discount that does not exist.
    member_price   = memberPrice.price
    unit_price     = currentPrice.comparativePrice
  multibuy: no qualifying-count/multibuy structure was observed in the
  sampled data, so multibuy_price stays None rather than being guessed.

IMAGES: images[].url is a bare filename. The site renders it from
  https://www.citygross.se/images/products/{filename}
  (verified by reading a real product page's rendered <img> src).

PRICING SCOPE: national, with store-scoped ASSORTMENT. Verified by comparing
  store=3209 (Gävle) with store=3207 (Falun): every one of the 11 products
  present in both had an identical price, but the two responses differed in
  size (77847 vs 78782 bytes), i.e. the store parameter genuinely changes
  which products are returned - just not their prices. That is a weaker
  claim than "store-specific pricing" and is recorded as such.
=============================================================================
"""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from ..base import GroceryProvider
from ..errors import ProviderBlockedError, ProviderRequestError
from .axfood import CATEGORY_PATH_SEPARATOR
from ..models import RawProduct, Store

logger = logging.getLogger("matjakt.grocery.citygross")

BASE = "https://www.citygross.se"
SITES_URL = f"{BASE}/api/v1/sites?siteTypeId=3"
STORE_PAGES_URL = f"{BASE}/api/v1/PageData/stores"
IMAGE_BASE = f"{BASE}/images/products"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Matjakt/1.0 (+grocery-collector)"
REQUEST_TIMEOUT_SECONDS = 20
# Measured, not guessed: at 1.0s between requests a full 14-term run had
# 13/14 terms fail with connection errors (URLError), while a controlled
# retest at 3s spacing succeeded on every call in ~0.5s each. City Gross
# throttles by dropping connections rather than returning HTTP 429, so the
# provider has to back off on its own - there is no status code to react to.
REQUEST_DELAY_SECONDS = 3.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 3, 8)
PAGE_SIZE = 20

# City Gross has no category-listing endpoint that has been VERIFIED (the
# Axfood chains do, so they browse the tree instead - see providers/axfood.py),
# so collection here is still term-driven. The honest way to widen it is to
# use the vocabulary the app actually cooks with rather than a longer generic
# list: these are the ingredients Matjakt's own recipes ask for, plus the
# staples every week needs. A term that returns nothing costs one request.
#
# Ordered roughly by how often a week's list needs them, because City Gross
# throttles by dropping connections and a run may not finish - the terms most
# likely to matter should already be in when it stops.
# =============================================================================
# CATEGORY BROWSE (verified live 2026-09-01) - the full catalogue
# =============================================================================
# The term-driven collection below tops out around 4 000 products because it
# only sees what the ~60 recipe-vocabulary terms happen to hit. The site's
# own category browse reaches everything:
#
#   GET /api/v1/navigation
#       -> {"data": {"tree": {...}}} - a page tree where every node with
#          link.categoryPageId and type "ProductCategoryPage" is a browsable
#          category. 1 113 such pages exist; the top-level food departments
#          under "Matvaror" (Mejeri id 1503, Kött & fågel 1493, ...) cover
#          the whole assortment, while the seasonal pages ("Jul", "Semlor",
#          "Nutelladagen"...) only re-shelve products the departments already
#          carry.
#   GET /api/v1/Loop54/category/{id}/products
#           ?skip={n}&categoryName={name}&store={storeNumber}&take={n}
#       -> {"items": [...], "totalCount", "pageSize", "totalPages"} - same
#          product shape as the search endpoint (gtin, prices, images, all
#          of it), with honest pagination. Verified: id 1503 reports
#          totalCount 1344 for store 3209.
#
# Both endpoints are the public ones the site itself calls on every page
# load - no auth, no cookie, no session. Same 3-second request delay, same
# blocked-means-stop rules as the search path.
NAVIGATION_URL = f"{BASE}/api/v1/navigation"
CATEGORY_PAGE_SIZE = 100

# Statisk reserv när navigationsendpointen inte svarar (produktionens
# nattkörning 2026-09-02 föll tyst tillbaka till termsökningen och fick
# 4 030 produkter i stället för ~8 700 - PRODUKTendpointen fungerar
# bevisligen från servern, så avdelnings-id:na tar oss hela vägen även när
# trädet inte går att läsa). Id:na är sajtens egna sidnummer och har varit
# stabila; ändrar City Gross dem faller vi tillbaka till termer igen och
# loggar det - vi gissar aldrig.
FALLBACK_FOOD_DEPARTMENTS = [
    (1493, "Kött & fågel"), (1448, "Frukt & grönt"), (1503, "Mejeri, ost & ägg"),
    (1507, "Skafferiet"), (1511, "Fryst"), (1502, "Bröd & bageri"),
    (1504, "Chark & pålägg"), (1505, "Fisk & skaldjur"), (1506, "Kyld färdigmat"),
    (3473, "Vegetariskt"), (1510, "Dryck"),
]

# The departments that belong in a grocery-price service. A deliberate
# allow-list by NAME: new seasonal pages appear all the time ("Fotbollsfest!",
# "Kanelbullens dag") and re-shelve existing products, while LEGO, Tobak,
# Husdjur and Skönhet are simply not food. A department City Gross renames
# falls out of collection visibly instead of silently collecting junk.
FOOD_DEPARTMENTS = {
    "Kött & fågel", "Frukt & grönt", "Mejeri, ost & ägg", "Skafferiet",
    "Fryst", "Bröd & bageri", "Chark & pålägg", "Fisk & skaldjur",
    "Kyld färdigmat", "Vegetariskt", "Dryck",
}

DEFAULT_SEARCH_TERMS = [
    # protein
    "kyckling", "kycklingfilé", "köttfärs", "fläskfilé", "lax", "torsk",
    "räkor", "korv", "falukorv", "bacon", "skinka", "tofu", "halloumi",
    # dairy and eggs
    "mjölk", "smör", "ägg", "grädde", "crème fraiche", "yoghurt", "ost",
    "riven ost", "fetaost",
    # pantry staples
    "ris", "pasta", "nudlar", "couscous", "bulgur", "matvete", "linser",
    "kikärtor", "bönor", "krossade tomater", "tomatpuré", "kokosmjölk",
    "buljong", "olja", "mjöl", "socker", "soja",
    # produce
    "potatis", "lök", "vitlök", "morötter", "paprika", "tomat", "gurka",
    "citron", "broccoli", "spenat", "purjolök", "champinjoner", "majs",
    # bread
    "bröd", "tortilla",
]


class CityGrossRequestError(ProviderRequestError):
    """A request that failed after its retries, or returned an unexpected shape."""


class CityGrossBlockedError(CityGrossRequestError, ProviderBlockedError):
    """City Gross actively refused us (403/429/empty body). Terminal - a
    collector stops and reports rather than retrying through a refusal.

    Not observed during the 2026-08-30 investigation, but implemented up
    front so this degrades the same safe way the other providers do."""


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def gtin_checksum_ok(code: str) -> bool:
    """GS1 mod-10 check digit (same rule as the Axfood providers use)."""
    if not code or not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body = digits[:-1][::-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    return (10 - total % 10) % 10 == digits[-1]


def normalize_gtin14(code) -> str | None:
    """Zero-pads a valid GTIN to 14 digits so City Gross' EAN-13 matches the
    Axfood chains' GTIN-14 for the same product - without this, cross-chain
    matching silently fails and one product gets two rows. Returns None for
    anything whose checksum doesn't validate, rather than storing a guess."""
    if code is None:
        return None
    cleaned = re.sub(r"\D", "", str(code))
    if not gtin_checksum_ok(cleaned):
        return None
    return cleaned.zfill(14)


def _parse_descriptive_size(text: str | None) -> tuple[float | None, str | None]:
    """'1,5L' -> (1.5, 'L'), '500g' -> (500.0, 'g')."""
    if not text:
        return None, None
    match = re.match(r"^\s*([\d.,]+)\s*([a-zA-ZäöåÄÖÅ]+)\s*$", str(text))
    if not match:
        return None, None
    try:
        return float(match.group(1).replace(",", ".")), match.group(2)
    except ValueError:
        return None, None


def extract_prices(product_store_details) -> dict:
    """Maps City Gross' explicit price block onto our model. See this
    module's docstring for why campaign_price is only set when the current
    price is genuinely BELOW the ordinary price."""
    prices = (product_store_details or {}).get("prices") or {}
    current = prices.get("currentPrice") or {}
    ordinary = prices.get("ordinaryPrice") or {}
    member = prices.get("memberPrice") or {}

    current_price = _to_float(current.get("price"))
    ordinary_price = _to_float(ordinary.get("price"))
    regular = ordinary_price if ordinary_price is not None else current_price

    campaign = None
    if current_price is not None and ordinary_price is not None and current_price < ordinary_price:
        campaign = current_price

    return {
        "regular_price": regular,
        "campaign_price": campaign,
        "member_price": _to_float(member.get("price")) if isinstance(member, dict) else _to_float(member),
        # No multibuy/qualifying-count structure was observed in this API -
        # left None rather than invented.
        "multibuy_price": None,
        "unit_price": _to_float(current.get("comparativePrice")),
    }


class CityGrossProvider(GroceryProvider):
    name = "City Gross"
    # Works and dedups correctly, but is materially less reliable than the
    # Axfood chains: it throttles via dropped connections (see
    # REQUEST_DELAY_SECONDS). A collector run should expect some terms to
    # fail and treat a partial import as normal.
    status = "working_but_unreliable"
    # Verified 2026-08-30: two real runs, the second reporting 0 new / 100
    # updated with no duplicate rows.
    recurring_import_verified = True
    # National prices, but the store parameter does change which products are
    # returned - see the module docstring's PRICING SCOPE note.
    pricing_scope = "national_with_store_assortment"

    def __init__(self, search_terms: list[str] | None = None, page_size: int = PAGE_SIZE):
        self.search_terms = search_terms or DEFAULT_SEARCH_TERMS
        self.page_size = page_size

    def _request(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
            "Referer": f"{BASE}/",
        })
        last_error = None
        for attempt, delay in enumerate((0, *RETRY_BACKOFF_SECONDS)):
            if delay:
                time.sleep(delay)
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    body = response.read()
                    if not body.strip():
                        raise CityGrossBlockedError(f"City Gross returned an empty body (HTTP {response.status}) for {url}")
                    return json.loads(body)
            except urllib.error.HTTPError as error:
                if error.code in (403, 429):
                    raise CityGrossBlockedError(f"City Gross refused the request (HTTP {error.code}) for {url}") from error
                last_error = error
                logger.warning("City Gross request failed (HTTP %s), attempt %d/%d: %s", error.code, attempt + 1, MAX_RETRIES, url)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("City Gross request failed (%s), attempt %d/%d: %s", type(error).__name__, attempt + 1, MAX_RETRIES, url)
            if attempt + 1 >= MAX_RETRIES:
                break
        raise CityGrossRequestError(f"City Gross request failed after {MAX_RETRIES} attempts: {url}") from last_error

    def get_stores(self) -> list[Store]:
        """Merges the two store endpoints: /sites carries storeNumber (the id
        the search endpoint needs), /PageData/stores carries coordinates.
        Joined on the store's city/name, which is the only field both share."""
        sites = (self._request(SITES_URL) or {}).get("sites") or []

        coordinates_by_name: dict[str, tuple[float | None, float | None]] = {}
        try:
            for page in self._request(STORE_PAGES_URL) or []:
                data = page.get("data") or {}
                raw = ((data.get("storeLocation") or {}).get("coordinates") or "").split(",")
                if len(raw) == 2:
                    try:
                        coordinates_by_name[(data.get("storeName") or "").strip().lower()] = (float(raw[0]), float(raw[1]))
                    except ValueError:
                        pass
        except CityGrossRequestError:
            # Coordinates are a nice-to-have; a store without them is still
            # perfectly usable for importing prices.
            logger.warning("City Gross store-page lookup failed - continuing without coordinates")

        stores = []
        for site in sites:
            store_number = site.get("storeNumber")
            if not store_number:
                continue
            name = site.get("name") or ""
            # "City Gross Gävle" in /sites vs "Gävle" in /PageData/stores.
            short_name = name.replace("City Gross", "").strip().lower()
            latitude, longitude = coordinates_by_name.get(short_name, (None, None))
            stores.append(Store(
                id=0,
                chain=self.name,
                external_store_id=str(store_number),
                name=name,
                city=site.get("city"),
                postal_code=site.get("zipcode"),
                address=site.get("streetAddress"),
                latitude=latitude,
                longitude=longitude,
                active=True,
            ))
        return stores

    def _food_categories(self) -> list[tuple[int, str]]:
        """The top-level food departments from the site's own navigation.

        Returns [] when the navigation cannot be read or looks unexpected -
        the caller then falls back to term search rather than aborting, so a
        navigation redesign degrades collection instead of killing it."""
        try:
            tree = ((self._request(NAVIGATION_URL) or {}).get("data") or {}).get("tree") or {}
        except CityGrossRequestError:
            logger.warning("City Gross-navigationen svarar inte härifrån - "
                           "använder den statiska avdelningslistan")
            return list(FALLBACK_FOOD_DEPARTMENTS)
        found: list[tuple[int, str]] = []

        def walk(node):
            link = node.get("link") or {}
            if (link.get("categoryPageId") and node.get("type") == "ProductCategoryPage"
                    and (node.get("name") or "").strip() in FOOD_DEPARTMENTS):
                found.append((int(node["id"]), node["name"].strip()))
                # Children are subcategories of a department already being
                # collected in full - walking into them would only re-fetch
                # the same products.
                return
            for child in node.get("children") or []:
                walk(child)

        walk(tree)
        if not found:
            logger.warning("City Gross-navigationen gav inga matavdelningar - "
                           "använder den statiska avdelningslistan")
            return list(FALLBACK_FOOD_DEPARTMENTS)
        return found

    def _category_products(self, store_id: str, seen: set[str],
                           products: list[RawProduct]) -> bool:
        """Collects every food department via the category browse. Returns
        False when the navigation gave nothing usable."""
        categories = self._food_categories()
        if not categories:
            return False
        for category_id, category_name in categories:
            skip = 0
            while True:
                time.sleep(REQUEST_DELAY_SECONDS)
                url = (f"{BASE}/api/v1/Loop54/category/{category_id}/products"
                       f"?skip={skip}&categoryName={quote(category_name)}"
                       f"&store={quote(str(store_id))}&take={CATEGORY_PAGE_SIZE}")
                try:
                    data = self._request(url)
                except CityGrossBlockedError as blocked:
                    logger.error("City Gross blocked this run in category %r - stopping after %d product(s)",
                                 category_name, len(products))
                    blocked.partial_products = products
                    raise
                except CityGrossRequestError:
                    logger.exception("City Gross category %r failed (skip %d) - moving on", category_name, skip)
                    break
                items = data.get("items") or []
                for raw in items:
                    product_id = str(raw.get("id") or "")
                    if not product_id or product_id in seen:
                        continue
                    seen.add(product_id)
                    try:
                        products.append(self.normalize_product({**raw, "_store_id": store_id}))
                    except Exception:
                        logger.exception("Failed to normalize City Gross product %r", product_id)
                total = data.get("totalCount") or 0
                skip += CATEGORY_PAGE_SIZE
                if skip >= total or not items:
                    break
            logger.info("City Gross %r klar: %d produkter totalt hittills", category_name, len(products))
        return True

    def get_products(self, store_id: str) -> list[RawProduct]:
        """store_id is City Gross' storeNumber (e.g. "3209"). It scopes which
        products come back, though not their prices - see pricing_scope.

        Category browse first (the whole catalogue), term search as the
        fallback when navigation is unreadable - and as a top-up for
        anything assortment quirks keep out of the department pages."""
        seen: set[str] = set()
        products: list[RawProduct] = []
        self._category_products(store_id, seen, products)
        for term in self.search_terms:
            skip = 0
            while True:
                time.sleep(REQUEST_DELAY_SECONDS)
                url = (f"{BASE}/api/v1/Loop54/search?SearchQuery={quote(term)}"
                       f"&skip={skip}&store={quote(str(store_id))}&take={self.page_size}")
                try:
                    data = self._request(url)
                except CityGrossBlockedError as blocked:
                    logger.error("City Gross blocked this run at term %r - stopping after %d product(s)", term, len(products))
                    blocked.partial_products = products
                    raise
                except CityGrossRequestError:
                    logger.exception("City Gross search failed for term %r (skip %d)", term, skip)
                    break

                results = (data.get("searchResults") or {}).get("products") or []
                for raw in results:
                    product_id = str(raw.get("id") or "")
                    if not product_id or product_id in seen:
                        continue
                    seen.add(product_id)
                    try:
                        products.append(self.normalize_product({**raw, "_store_id": store_id}))
                    except Exception:
                        logger.exception("Failed to normalize City Gross product %r", product_id)

                total = (data.get("searchResults") or {}).get("totalCount") or 0
                skip += self.page_size
                if skip >= total or not results:
                    break
        return products

    def get_product_details(self, product_id: str, store_id: str) -> RawProduct | None:
        url = (f"{BASE}/api/v1/Loop54/search?SearchQuery={quote(product_id)}"
               f"&skip=0&store={quote(str(store_id))}&take={self.page_size}")
        try:
            data = self._request(url)
        except CityGrossRequestError:
            logger.exception("City Gross product detail failed for %r", product_id)
            return None
        for raw in (data.get("searchResults") or {}).get("products") or []:
            if str(raw.get("id") or "") == product_id:
                return self.normalize_product({**raw, "_store_id": store_id})
        return None

    def normalize_product(self, raw_product) -> RawProduct:
        product_id = str(raw_product.get("id") or "")
        prices = extract_prices(raw_product.get("productStoreDetails"))
        quantity, unit = _parse_descriptive_size(raw_product.get("descriptiveSize"))

        images = raw_product.get("images") or []
        image_name = (images[0] or {}).get("url") if images else None
        image_url = f"{IMAGE_BASE}/{image_name}" if image_name else None

        # City Gross gives three levels: superCategory is the broadest
        # ("Mejeri, ost & ägg"), then category ("Mjölk & dryck"), then
        # bfCategory the most specific ("Mellanmjölk"). They are joined into
        # one path, in the same "broad > narrow" shape the Axfood chains
        # produce, so category-aware matching sees the same kind of string for
        # every chain instead of a per-chain format.
        levels = [raw_product.get("superCategory"), raw_product.get("category"), raw_product.get("bfCategory")]
        seen_levels = []
        for level in levels:
            level = (level or "").strip()
            if level and level not in seen_levels:
                seen_levels.append(level)
        category = CATEGORY_PATH_SEPARATOR.join(seen_levels) or None

        path = raw_product.get("url") or ""
        store_id = raw_product.get("_store_id", "")
        return RawProduct(
            chain=self.name,
            external_product_id=product_id,
            name=raw_product.get("name") or "",
            store_id=str(store_id),
            store_name=str(store_id),
            # Explicit field here (unlike Axfood), normalised to GTIN-14 so it
            # matches the other chains for the same product.
            gtin=normalize_gtin14(raw_product.get("gtin")),
            ean=None,
            brand=raw_product.get("brand") or None,
            description=raw_product.get("description") or raw_product.get("subtitle") or None,
            size=raw_product.get("descriptiveSize") or None,
            quantity=quantity,
            unit=unit,
            category=category,
            image_url=image_url,
            regular_price=prices["regular_price"],
            campaign_price=prices["campaign_price"],
            member_price=prices["member_price"],
            multibuy_price=prices["multibuy_price"],
            unit_price=prices["unit_price"],
            currency="SEK",
            source_url=f"{BASE}{path}" if path.startswith("/") else (path or None),
            fetched_at=time.time(),
        )

    def health_check(self) -> bool:
        try:
            data = self._request(SITES_URL)
        except CityGrossRequestError:
            return False
        return bool((data or {}).get("sites"))
