"""Shared base for Axfood's grocery chains (Willys, Hemköp).

Both sites run the same commerce platform and expose the same public
`/axfood/rest/v1/` REST API - verified live on 2026-08-30 by comparing full
responses from www.willys.se and www.hemkop.se: identical top-level keys and
identical product field sets. Only the host, the chain name and the actual
PRICES differ (the same GTIN 07340083443893 was 16.50 at Willys and 17.70 at
Hemköp - a real chain price difference, which is exactly what Matjakt
compares).

So the request/parse/normalize logic lives here once, and each chain's own
module is a thin subclass supplying its host and metadata. Nothing here is
assumed to be shared: every field mapping below was checked against real
responses from BOTH chains before being put in this file.

NO AUTHENTICATION of any kind is used or needed - no key, no cookie, no
session, no browser.

=== PROMOTION SEMANTICS (the subtle part) ===
A promotion in potentialPromotions[] can be one of three genuinely different
things, and conflating them would misreport prices to users:

  campaignType == "LOYALTY"  -> a MEMBER price. Only members pay it, so it
                                must not be shown as the price everyone gets.
  qualifyingCount > 1        -> a MULTIBUY. price.value is the PER-UNIT price
                                when buying that many ("2 för 40 kr" -> 20.00
                                each). Storing it as a campaign price would
                                overstate the discount for a single item.
  otherwise                  -> a straight CAMPAIGN price everyone pays.

Field-choice note: an earlier version of this logic keyed off
conditionLabelFormatted ("2 för"/"3 för" vs empty). That is WRONG across
chains - verified live that Hemköp leaves conditionLabelFormatted empty on
promotions that are really multibuys (qualifyingCount 2, rewardLabel
"129 kr", per-unit price 64.50 against an ordinary 66.20), while Willys
fills it in. qualifyingCount is populated correctly by both, so it is what
this code trusts.
"""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from ..base import GroceryProvider
from ..models import RawProduct, Store

logger = logging.getLogger("matjakt.grocery.axfood")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Matjakt/1.0 (+grocery-collector)"
REQUEST_TIMEOUT_SECONDS = 15
REQUEST_DELAY_SECONDS = 1.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 3, 8)
PAGE_SIZE = 30

# There is no "whole catalog" endpoint on the search API, so a collector
# works from a known vocabulary. (Both chains DO expose a category tree at
# /leftMenu/categorytree - browsing that instead would give a systematic walk
# and real categories; noted as the better long-term approach, not done yet.)
DEFAULT_SEARCH_TERMS = [
    "mjölk", "smör", "ägg", "bröd", "kyckling", "köttfärs", "lax", "ris",
    "pasta", "tomat", "lök", "potatis", "ost", "yoghurt",
]


class AxfoodRequestError(Exception):
    """A request that failed after its retries, or returned something that
    isn't the JSON shape this provider expects."""


class AxfoodBlockedError(AxfoodRequestError):
    """The chain actively refused us (403/429, or an empty body). Terminal,
    not transient - a collector must stop and report rather than retrying its
    way through a refusal.

    Not observed during the 2026-08-30 investigation (both chains answered
    every plain server-side request), but implemented up front so that if
    Axfood adds bot protection this degrades the same safe way ICA's provider
    already does."""

    def __init__(self, message, partial_products=None):
        super().__init__(message)
        self.partial_products = partial_products or []


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_swedish_price(text) -> float | None:
    """'119,00 kr' -> 119.0. Returns None for anything that doesn't parse,
    never a fallback 0 - a missing price must stay missing."""
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(text).replace("\xa0", " "))
    return float(match.group(1).replace(",", ".")) if match else None


def _parse_display_volume(text: str | None) -> tuple[float | None, str | None]:
    """'1,5l' -> (1.5, 'l'), '500g' -> (500.0, 'g'). Deliberately simple: a
    plain number+unit regex over a consistently-formatted field, not a
    unit-conversion library. Anything else returns (None, None)."""
    if not text:
        return None, None
    match = re.match(r"^\s*([\d.,]+)\s*([a-zA-ZäöåÄÖÅ]+)\s*$", text)
    if not match:
        return None, None
    try:
        return float(match.group(1).replace(",", ".")), match.group(2)
    except ValueError:
        return None, None


def gtin_checksum_ok(code: str) -> bool:
    """GS1 mod-10 check digit; weights alternate 3,1 from the digit left of
    the check digit."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body = digits[:-1][::-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    return (10 - total % 10) % 10 == digits[-1]


def gtin_from_image_url(url: str | None) -> str | None:
    """Neither chain exposes a gtin/ean field, but both key their product
    images by GTIN-14:
        https://assets.axfood.se/image/upload/f_auto,t_200/07310865005168_C1L1_s01
    Only returns a code whose GS1 check digit validates. An unvalidated code
    is treated as "no GTIN" rather than stored as a guess, because a wrong
    GTIN would wrongly merge two different products under GroceryStore's
    tier-1 matching - the exact failure the matching rules exist to prevent."""
    if not url:
        return None
    match = re.search(r"/(\d{8,14})_", url)
    if not match:
        return None
    code = match.group(1)
    return code if gtin_checksum_ok(code) else None


def split_promotions(promotions) -> tuple[float | None, float | None, float | None]:
    """Returns (campaign_price, member_price, multibuy_price).

    See this module's docstring for why the three are kept apart and why
    qualifyingCount - not conditionLabelFormatted - decides what a multibuy
    is. When several promotions of the same kind exist, the lowest price
    wins."""
    campaign = member = multibuy = None

    def lowest(current, value):
        return value if current is None else min(current, value)

    for promotion in promotions or []:
        value = _to_float((promotion.get("price") or {}).get("value"))
        if value is None:
            continue
        campaign_type = (promotion.get("campaignType") or "").upper()
        qualifying = promotion.get("qualifyingCount") or 0
        if campaign_type == "LOYALTY":
            member = lowest(member, value)
        elif isinstance(qualifying, (int, float)) and qualifying > 1:
            multibuy = lowest(multibuy, value)
        else:
            campaign = lowest(campaign, value)
    return campaign, member, multibuy


class AxfoodProvider(GroceryProvider):
    """Base for Willys/Hemköp. Subclasses set name, base_url and metadata."""

    name: str = ""
    base_url: str = ""
    status = "working"
    recurring_import_verified = False
    pricing_scope = "national"

    def __init__(self, search_terms: list[str] | None = None, page_size: int = PAGE_SIZE):
        self.search_terms = search_terms or DEFAULT_SEARCH_TERMS
        self.page_size = page_size

    # ---- transport ---------------------------------------------------

    def _request(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
        })
        last_error = None
        for attempt, delay in enumerate((0, *RETRY_BACKOFF_SECONDS)):
            if delay:
                time.sleep(delay)
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    body = response.read()
                    if not body.strip():
                        raise AxfoodBlockedError(f"{self.name} returned an empty body (HTTP {response.status}) for {url}")
                    return json.loads(body)
            except urllib.error.HTTPError as error:
                if error.code in (403, 429):
                    raise AxfoodBlockedError(f"{self.name} refused the request (HTTP {error.code}) for {url}") from error
                last_error = error
                logger.warning("%s request failed (HTTP %s), attempt %d/%d: %s", self.name, error.code, attempt + 1, MAX_RETRIES, url)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("%s request failed (%s), attempt %d/%d: %s", self.name, type(error).__name__, attempt + 1, MAX_RETRIES, url)
            if attempt + 1 >= MAX_RETRIES:
                break
        raise AxfoodRequestError(f"{self.name} request failed after {MAX_RETRIES} attempts: {url}") from last_error

    # ---- GroceryProvider ---------------------------------------------

    def get_stores(self) -> list[Store]:
        data = self._request(f"{self.base_url}/store")
        stores = []
        for store in data if isinstance(data, list) else []:
            store_id = store.get("storeId")
            if not store_id:
                continue
            address = store.get("address") or {}
            point = store.get("geoPoint") or {}
            stores.append(Store(
                id=0,
                chain=self.name,
                external_store_id=str(store_id),
                name=store.get("name") or "",
                city=address.get("town"),
                postal_code=address.get("postalCode"),
                address=address.get("line1"),
                # 0.0/0.0 is Axfood's "no coordinates" placeholder, not a real
                # position in the Atlantic - store it as unknown.
                latitude=point.get("latitude") or None,
                longitude=point.get("longitude") or None,
                active=bool(store.get("onlineStore")),
            ))
        return stores

    def get_products(self, store_id: str) -> list[RawProduct]:
        """Walks every search term, following pagination within each.
        store_id is carried onto results for attribution only - it does NOT
        scope prices (see pricing_scope)."""
        seen: set[str] = set()
        products: list[RawProduct] = []
        for term in self.search_terms:
            page = 0
            while True:
                time.sleep(REQUEST_DELAY_SECONDS)
                url = f"{self.base_url}/search?q={quote(term)}&page={page}&size={self.page_size}"
                try:
                    data = self._request(url)
                except AxfoodBlockedError as blocked:
                    logger.error("%s blocked this run at term %r - stopping after %d product(s)", self.name, term, len(products))
                    blocked.partial_products = products
                    raise
                except AxfoodRequestError:
                    logger.exception("%s search failed for term %r (page %d)", self.name, term, page)
                    break

                results = data.get("results") or []
                for raw in results:
                    code = str(raw.get("code") or "")
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    try:
                        products.append(self.normalize_product({**raw, "_store_id": store_id}))
                    except Exception:
                        logger.exception("Failed to normalize %s product %r", self.name, code)

                total_pages = (data.get("pagination") or {}).get("numberOfPages") or 0
                page += 1
                if page >= total_pages or not results:
                    break
        return products

    def get_product_details(self, product_id: str, store_id: str) -> RawProduct | None:
        """Searching for a product's own code returns that product. Both sites
        also have a Next.js data route for the product page, but its URL
        embeds a build hash that changes on every site deploy - depending on
        it would break silently and often, so this uses the stable REST
        endpoint instead."""
        url = f"{self.base_url}/search?q={quote(product_id)}&page=0&size={self.page_size}"
        try:
            data = self._request(url)
        except AxfoodRequestError:
            logger.exception("%s product detail failed for %r", self.name, product_id)
            return None
        for raw in data.get("results") or []:
            if str(raw.get("code") or "") == product_id:
                return self.normalize_product({**raw, "_store_id": store_id})
        return None

    def normalize_product(self, raw_product) -> RawProduct:
        code = str(raw_product.get("code") or "")
        image_url = ((raw_product.get("image") or {}).get("url")
                     or (raw_product.get("thumbnail") or {}).get("url") or None)
        quantity, unit = _parse_display_volume(raw_product.get("displayVolume"))
        campaign_price, member_price, multibuy_price = split_promotions(raw_product.get("potentialPromotions"))
        store_id = raw_product.get("_store_id", "")
        return RawProduct(
            chain=self.name,
            external_product_id=code,
            name=raw_product.get("name") or "",
            store_id=store_id,
            store_name=store_id,
            gtin=gtin_from_image_url(image_url),
            ean=None,
            brand=raw_product.get("manufacturer") or None,
            description=raw_product.get("productLine2") or None,
            size=raw_product.get("displayVolume") or None,
            quantity=quantity,
            unit=unit,
            # Search results carry no usable category on either chain
            # (googleAnalyticsCategory is "" and breadcrumbs is []).
            category=None,
            image_url=image_url,
            regular_price=_to_float(raw_product.get("priceValue")),
            campaign_price=campaign_price,
            member_price=member_price,
            multibuy_price=multibuy_price,
            unit_price=_parse_swedish_price(raw_product.get("comparePrice")),
            currency="SEK",
            source_url=f"{self.product_url_base}/{quote(code)}" if code else None,
            fetched_at=time.time(),
        )

    @property
    def product_url_base(self) -> str:
        return self.base_url.replace("/axfood/rest/v1", "/produkt")

    def health_check(self) -> bool:
        try:
            data = self._request(f"{self.base_url}/store")
        except AxfoodRequestError:
            return False
        return isinstance(data, list) and len(data) > 0
