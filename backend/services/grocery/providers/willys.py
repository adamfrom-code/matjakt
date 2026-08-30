"""Willys provider - plain HTTP/JSON against Axfood's public REST API for
willys.se. No authentication, no browser automation, no credentials.

=============================================================================
PROVIDER STATUS: working / national_pricing_only
=============================================================================
Unlike ICA (rate-limited by a WAF) and Coop (requires a vendor API key), the
Willys endpoints below answer plain server-side requests with no key, no
cookie and no session. They are the same `/axfood/rest/v1/` namespace this
codebase already calls for store lookups.

IMPORTANT LIMITATION - prices are NATIONAL, not per store. Verified live
(2026-08-30): requesting the same query with storeId=2132 (Willys Gävle
Gestrike) and storeId=2223 (Willys Gävle Hemsta) returns byte-identical
responses (35593 B both times) with identical prices on every product. The
search endpoint accepts but IGNORES storeId. That is consistent with Willys
being a centrally-priced discount chain rather than independently-priced
franchises like ICA, but it means a price stored against a specific Willys
store is really "Willys' national price", and must not be presented as
independently verified for that address.
=============================================================================

INVESTIGATION FINDINGS (verified live, 2026-08-30):

STORE LIST
  GET https://www.willys.se/axfood/rest/v1/store
  No auth. 256 stores. Fields used: storeId ("2132"), name, address.town,
  address.postalCode, address.line1, geoPoint.latitude/longitude,
  onlineStore. Willys Gävle Gestrike = storeId 2132 (onlineStore: true).

PRODUCT SEARCH (real pagination, unlike ICA)
  GET https://www.willys.se/axfood/rest/v1/search?q={q}&page={n}&size={n}
  No auth. Returns {"results": [...], "pagination": {"pageSize",
  "currentPage", "numberOfPages", "totalNumberOfResults"}, ...}. A "mjölk"
  search reported 142 results across 5 pages - so a collector can walk a
  whole result set rather than being capped at one response like ICA.

CATEGORY TREE (available, not used yet)
  GET https://www.willys.se/axfood/rest/v1/leftMenu/categorytree?storeId={id}&deviceType=OTHER
  No auth, 568 category nodes. Search results themselves carry NO usable
  category (googleAnalyticsCategory is an empty string, breadcrumbs is []),
  so category is left null by this provider. Browsing by category instead of
  by search term would fix that and give a systematic catalog walk - a
  deliberate future improvement, not done here.

FIELDS CONFIRMED PRESENT on a search result:
  code ("101017249_ST" - stable product id, used as external_product_id),
  name, manufacturer (brand), displayVolume ("1,5l" - size),
  priceValue (float, regular price), price ("59,50 kr"), priceUnit ("kr/st"),
  comparePrice ("119,00 kr") + comparePriceUnit ("kg") - unit price,
  image.url, thumbnail.url, potentialPromotions[], savingsAmount,
  outOfStock, online, labels.

GTIN - DERIVED, NOT AN EXPLICIT FIELD:
  There is no gtin/ean/barcode key anywhere in the response. However the
  image URL is keyed by the product's GTIN-14:
      https://assets.axfood.se/image/upload/f_auto,t_200/07310865005168_C1L1_s01
  Verified on 12/12 sampled products that the extracted code passes the GS1
  mod-10 check-digit test (see _gtin_from_image_url). This provider only
  sets gtin when that checksum validates - a code that fails is treated as
  "no GTIN" rather than stored as a guess, because a wrong GTIN would
  wrongly merge two different products in GroceryStore's tier-1 matching.

PROMOTIONS - two distinct kinds, verified live:
  potentialPromotions[].conditionLabelFormatted tells them apart:
    ""       -> a straight campaign price. Ex: "Högrev Nötkött Irland",
                ordinary 145.00, promotion price 129.00 -> campaign_price.
    "2 för"  -> a multibuy: promotion price is the PER-UNIT price when
    "3 för"     buying that many. Ex: chips 24.90 ordinary, "2 för" 20.00
                -> multibuy_price. Storing this as campaign_price would
                overstate the discount for someone buying a single item.

MEMBER PRICE: no member/medlemspris field observed on any sampled product.
  Left as None - never fabricated.
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

logger = logging.getLogger("matjakt.grocery.willys")

BASE = "https://www.willys.se/axfood/rest/v1"
STORE_LIST_URL = f"{BASE}/store"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Matjakt/1.0 (+grocery-collector)"
REQUEST_TIMEOUT_SECONDS = 15
REQUEST_DELAY_SECONDS = 1.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 3, 8)
PAGE_SIZE = 30

# Same rationale as ICA's list: there is no "give me the whole catalog"
# endpoint on the search API, so a collector works from a known vocabulary.
# (The category tree above WOULD allow a systematic walk - noted as the
# better long-term approach in this module's docstring.)
DEFAULT_SEARCH_TERMS = [
    "mjölk", "smör", "ägg", "bröd", "kyckling", "köttfärs", "lax", "ris",
    "pasta", "tomat", "lök", "potatis", "ost", "yoghurt",
]


class WillysRequestError(Exception):
    """A request that failed after its retries, or returned something that
    isn't the JSON shape this provider expects."""


class WillysBlockedError(WillysRequestError):
    """Willys actively refused us (403/429). Terminal, not transient - the
    same stop-and-report contract as IcaBlockedError, so a collector never
    retries its way through a refusal.

    Not observed during the 2026-08-30 investigation (Willys answered every
    plain server-side request), but implemented up front so that if Axfood
    ever adds bot protection, this provider degrades the same safe way ICA's
    already does instead of hammering."""

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
    """'119,00 kr' -> 119.0. Willys formats these with a comma decimal and a
    currency suffix; anything that doesn't match returns None rather than a
    guess."""
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(text).replace("\xa0", " "))
    return float(match.group(1).replace(",", ".")) if match else None


def _parse_display_volume(text: str | None) -> tuple[float | None, str | None]:
    """'1,5l' -> (1.5, 'l'), '500g' -> (500.0, 'g'). Same deliberately-simple
    approach as ICA's _parse_pack_size."""
    if not text:
        return None, None
    match = re.match(r"^\s*([\d.,]+)\s*([a-zA-ZäöåÄÖÅ]+)\s*$", text)
    if not match:
        return None, None
    try:
        return float(match.group(1).replace(",", ".")), match.group(2)
    except ValueError:
        return None, None


def _gtin_checksum_ok(code: str) -> bool:
    """GS1 mod-10 check digit. Weights alternate 3,1 from the rightmost digit
    before the check digit."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body = digits[:-1][::-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    return (10 - total % 10) % 10 == digits[-1]


def _gtin_from_image_url(url: str | None) -> str | None:
    """Willys has no GTIN field, but its image URLs are keyed by GTIN-14 (see
    the module docstring). Only returns a code whose GS1 check digit
    validates - an unvalidated code would risk merging two genuinely
    different products under GroceryStore's tier-1 GTIN matching, which is
    exactly the failure mode the matching rules are built to avoid."""
    if not url:
        return None
    match = re.search(r"/(\d{8,14})_", url)
    if not match:
        return None
    code = match.group(1)
    return code if _gtin_checksum_ok(code) else None


def _split_promotions(promotions) -> tuple[float | None, float | None]:
    """Returns (campaign_price, multibuy_price) - see the module docstring for
    why these must not be conflated. An empty conditionLabelFormatted means a
    straight discounted price; an 'N för' label means the price applies only
    when buying N, which is a multibuy, not a price everyone pays."""
    campaign = multibuy = None
    for promotion in promotions or []:
        value = _to_float((promotion.get("price") or {}).get("value"))
        if value is None:
            continue
        label = (promotion.get("conditionLabelFormatted") or "").strip()
        if label:
            multibuy = value if multibuy is None else min(multibuy, value)
        else:
            campaign = value if campaign is None else min(campaign, value)
    return campaign, multibuy


class WillysProvider(GroceryProvider):
    name = "Willys"
    status = "working"
    # Verified 2026-08-30: two consecutive full imports, the second reporting
    # 0 new / 100 updated with no block and no duplicate rows.
    recurring_import_verified = True
    # Prices come from a national endpoint - see the module docstring. Kept as
    # an explicit attribute so a status panel or the app can label a Willys
    # price honestly rather than implying it was checked at that address.
    pricing_scope = "national"

    def __init__(self, search_terms: list[str] | None = None, page_size: int = PAGE_SIZE):
        self.search_terms = search_terms or DEFAULT_SEARCH_TERMS
        self.page_size = page_size

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
                        raise WillysBlockedError(f"Willys returned an empty body (HTTP {response.status}) for {url}")
                    return json.loads(body)
            except urllib.error.HTTPError as error:
                if error.code in (403, 429):
                    raise WillysBlockedError(f"Willys refused the request (HTTP {error.code}) for {url}") from error
                last_error = error
                logger.warning("Willys request failed (HTTP %s), attempt %d/%d: %s", error.code, attempt + 1, MAX_RETRIES, url)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("Willys request failed (%s), attempt %d/%d: %s", type(error).__name__, attempt + 1, MAX_RETRIES, url)
            if attempt + 1 >= MAX_RETRIES:
                break
        raise WillysRequestError(f"Willys request failed after {MAX_RETRIES} attempts: {url}") from last_error

    def get_stores(self) -> list[Store]:
        data = self._request(STORE_LIST_URL)
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
                # 0.0/0.0 is Axfood's placeholder for "no coordinates", not a
                # real position off the coast of Africa - store it as unknown.
                latitude=point.get("latitude") or None,
                longitude=point.get("longitude") or None,
                active=bool(store.get("onlineStore")),
            ))
        return stores

    def get_products(self, store_id: str) -> list[RawProduct]:
        """Walks every search term, following pagination within each. store_id
        is carried through onto the results for attribution only - it does NOT
        change the prices returned (see the module docstring's national-pricing
        note)."""
        seen: set[str] = set()
        products: list[RawProduct] = []
        for term in self.search_terms:
            page = 0
            while True:
                time.sleep(REQUEST_DELAY_SECONDS)
                url = f"{BASE}/search?q={quote(term)}&page={page}&size={self.page_size}"
                try:
                    data = self._request(url)
                except WillysBlockedError as blocked:
                    logger.error("Willys blocked this run at term %r - stopping after %d product(s)", term, len(products))
                    blocked.partial_products = products
                    raise
                except WillysRequestError:
                    logger.exception("Willys search failed for term %r (page %d)", term, page)
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
                        logger.exception("Failed to normalize Willys product %r", code)

                pagination = data.get("pagination") or {}
                total_pages = pagination.get("numberOfPages") or 0
                page += 1
                if page >= total_pages or not results:
                    break
        return products

    def get_product_details(self, product_id: str, store_id: str) -> RawProduct | None:
        """Willys' search endpoint is also the cheapest way to re-read one
        product: searching for its own code returns that product. There is a
        separate Next.js data route for the product page, but it is tied to a
        build hash in its URL (/_next/data/<hash>/...), which changes on every
        site deploy - depending on it would break silently and often, so this
        deliberately uses the stable REST endpoint instead."""
        url = f"{BASE}/search?q={quote(product_id)}&page=0&size={self.page_size}"
        try:
            data = self._request(url)
        except WillysRequestError:
            logger.exception("Willys product detail failed for %r", product_id)
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
        campaign_price, multibuy_price = _split_promotions(raw_product.get("potentialPromotions"))
        store_id = raw_product.get("_store_id", "")
        return RawProduct(
            chain=self.name,
            external_product_id=code,
            name=raw_product.get("name") or "",
            store_id=store_id,
            store_name=store_id,
            # Derived from the image URL and checksum-validated - see
            # _gtin_from_image_url. None when it doesn't validate.
            gtin=_gtin_from_image_url(image_url),
            ean=None,
            brand=raw_product.get("manufacturer") or None,
            description=raw_product.get("productLine2") or None,
            size=raw_product.get("displayVolume") or None,
            quantity=quantity,
            unit=unit,
            # Search results carry no usable category (see module docstring).
            category=None,
            image_url=image_url,
            regular_price=_to_float(raw_product.get("priceValue")),
            campaign_price=campaign_price,
            member_price=None,  # no member price exposed by this API
            multibuy_price=multibuy_price,
            unit_price=_parse_swedish_price(raw_product.get("comparePrice")),
            currency="SEK",
            source_url=f"https://www.willys.se/produkt/{quote(code)}" if code else None,
            fetched_at=time.time(),
        )

    def health_check(self) -> bool:
        try:
            data = self._request(STORE_LIST_URL)
        except WillysRequestError:
            return False
        return isinstance(data, list) and len(data) > 0
