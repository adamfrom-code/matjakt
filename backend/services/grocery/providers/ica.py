"""ICA provider - plain HTTP/JSON against ICA's real public online-store API,
no Playwright, no browser automation.

=============================================================================
PROVIDER STATUS: working_but_rate_limited / recurring_import_not_verified
=============================================================================
A one-off import genuinely works and produces real, complete data. A
REPEATED (e.g. nightly) import has NOT been verified to work, because ICA's
AWS WAF challenges sustained automated access - see IcaBlockedError.

Verified first real import (2026-08-30), Maxi ICA Stormarknad Gävle,
store/account ID 1003987:
    262 products found, 100 saved (--limit 100)
    100/100 with image URL          (all verified to return real JPEGs)
    100/100 with regular price
    100/100 with unit price (jämförpris)
      0/100 with GTIN/EAN           - ICA does not expose it at all (below)
      0/100 with campaign price     - none observed on any sampled product
      0/100 with member price       - none observed on any sampled product
    0 errors, 81.2s

Known limitation - repeated automated collection triggers an AWS WAF bot
challenge (HTTP 202 + x-amzn-waf-action: challenge, empty body). It is
volume-based: it lifts after a few minutes of quiet and returns as soon as a
run resumes. Both curl and Python are treated identically, so it is not a
client-configuration issue. We deliberately do NOT attempt to solve or work
around that challenge. Consequence: a nightly ICA collector should be
expected to be challenged partway through, and must treat a partial import
as normal rather than as failure.
=============================================================================

INVESTIGATION FINDINGS (verified live, 2026-08-30, against Maxi ICA
Stormarknad Gävle, store account id 1003987) - see FAS B report for the exact
request/response captures this is built from:

STORE IDENTIFICATION
  GET https://handla.ica.se/api/store/v1?zip={zip}&customerType=B2C
  No auth, no special headers needed - works from a bare server-side request.
  Returns forHomeDelivery/forPickupDelivery lists of stores. The field to use
  as this chain's external_store_id is `accountId` (e.g. "1003987"), NOT the
  `id` field (e.g. "10800") - accountId is what every other endpoint below
  expects in its /stores/{accountId}/... path. Confirmed by cross-checking:
  the store lookup's accountId for "Maxi ICA Stormarknad Gävle" is 1003987,
  and every product API call below only succeeds under that path segment.

PRODUCT SEARCH (paged in one response, not a next-cursor scheme)
  GET https://handlaprivatkund.ica.se/stores/{store_id}/api/webproductpagews/v6/product-pages/search
      ?includeAdditionalPageInfo=true&maxPageSize={n}&maxProductsToDecorate=50&q={query}&tag=web
  Returns {"productGroups": [{"type": "featured"|"personalized"|...,
  "decoratedProducts": [...]}], "metadata", "additionalPageInfo",
  "missedPromotions"}. maxPageSize controls how many results come back in
  this one call (tested up to 300, no separate pagination cursor was ever
  offered even at the edge of a result set) - there is no "list this store's
  entire catalog" endpoint; every product must be reached via a search term
  or a category, which is why get_products() below works from a fixed term
  list rather than walking a catalog directly (see its docstring).
  BLOCKED without realistic headers: a bare request (default/no User-Agent)
  gets a 403 "Request blocked" from what looks like a CDN/WAF. A completely
  standard browser User-Agent + Accept-Language + Referer - the same kind of
  identifying header this codebase already sends to Willys/zippopotam.us,
  not any kind of evasion - is all that's needed; no cookies, no session,
  no CAPTCHA was ever presented for this endpoint.

PRODUCT DETAIL
  GET https://handlaprivatkund.ica.se/stores/{store_id}/api/webproductpagews/v5/products/bop?retailerProductId={id}
  Returns {"product": {...same shape as one search result...}, "bopData":
  {"fields": [...key/value spec sheet: countryOfOrigin, brand, ingredients,
  storage, nutritionalData, contactInformation, otherInformation...],
  "detailedDescription", "breadcrumbs"}, "bopPromotions": [], ...}.

FIELDS CONFIRMED PRESENT on a product (search result AND detail - same
  shape): productId (ICA's internal UUID), retailerProductId (a stable
  numeric id - this is what's used as external_product_id, since it's the
  same id ICA's own product URLs use), name, brand, packSizeDescription
  (e.g. "1.5L", "0.45kg" - parsed into quantity+unit by _parse_pack_size
  below), countryOfOrigin, price.amount + price.currency, unitPrice.price.
  amount + unitPrice.unitName, image.src (a real, working image URL - also
  image.fopSrcset/bopSrcset for other resolutions), categoryPath (a
  breadcrumb array, most specific last), available, isNew, alcohol,
  iconAttributes (eco/KRAV/origin badges).

FIELDS CONFIRMED ABSENT - do not invent these:
  - No GTIN/EAN anywhere: not in search results, not in the detail
    endpoint, not in bopData.fields. ICA's public web API simply does not
    expose it. This means ICA products can only ever match tier 3
    (external_product_id) or tier 4 (name/brand/size) in GroceryStore.
    find_or_create_product - never tier 1/2 - unless a different chain's
    provider supplies the GTIN and ICA's own retailerProductId gets linked
    to that same product afterward.
  - Campaign/member pricing NOT CONFIRMED: bopPromotions was an empty list
    on every product sampled during this investigation (~100 products
    across several searches), and no campaignPrice/memberPrice field was
    ever observed populated. normalize_product() below still reads a
    campaignPrice/memberPrice key defensively (in case a field name match
    shows up on a genuinely-discounted product later), but this path is
    UNVERIFIED - flagged here rather than silently assumed correct. Worth
    revisiting once a real ICA campaign item is found to search for.

RATE LIMITING (verified live): 5 sequential requests at 0.5s spacing, no
  429/403 encountered. No documented rate limit was found (this isn't a
  published developer API), so REQUEST_DELAY_SECONDS below is a
  conservative default, not a measured ceiling.
"""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from ..base import GroceryProvider
from .axfood import CATEGORY_PATH_SEPARATOR
from ..models import RawProduct, Store

logger = logging.getLogger("matjakt.grocery.ica")

STORE_LOOKUP_URL = "https://handla.ica.se/api/store/v1"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Matjakt/1.0 (+grocery-collector)"
REQUEST_TIMEOUT_SECONDS = 10
# Measured, not guessed: 0.5s between search terms got the whole collector
# run challenged by ICA's WAF partway through a 14-term run (see
# IcaBlockedError). The challenge lifted on its own within minutes, so it's
# rate-based rather than a permanent ban - this backs off to a pace that
# leaves real headroom. A nightly job has no reason to be fast.
REQUEST_DELAY_SECONDS = 2.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1, 3, 8)

# There is no "every product this store has" endpoint (see module docstring) -
# get_products() instead searches this fixed, small list of common Swedish
# grocery terms, matching the same "known ingredient list" approach already
# used for campaign scanning elsewhere in this codebase (see
# CAMPAIGN_SCAN_INGREDIENTS in api_server.py). Deliberately short for FAS B
# (proving the pipeline works end to end, not covering ICA's full range) -
# a real nightly collector would draw this from the app's own recipe
# ingredient vocabulary instead, as already discussed for the nightly-job
# design.
DEFAULT_SEARCH_TERMS = [
    "mjölk", "smör", "ägg", "bröd", "kyckling", "köttfärs", "lax", "ris",
    "pasta", "tomat", "lök", "potatis", "ost", "yoghurt",
]


class IcaRequestError(Exception):
    """Raised for anything that isn't a clean 200 - a 403/429/5xx, a timeout,
    or a response that doesn't parse as the expected JSON shape. Callers
    (get_products, the collector script) catch this per-item and keep going;
    it is never allowed to crash a whole run over one bad response."""


class IcaBlockedError(IcaRequestError):
    """ICA's WAF is actively challenging/refusing us - a distinct, terminal
    condition, not a transient error.

    Observed live (2026-08-30, after ~1 full 14-term collector run): ICA sits
    behind AWS WAF, which stops answering with data and instead returns
    HTTP 202, an EMPTY body, and the header `x-amzn-waf-action: challenge`.
    That is a bot-detection challenge asking for a JS/CAPTCHA-style proof of
    work.

    We deliberately do NOT attempt to solve or work around that challenge.
    This exception exists so the collector stops cleanly and reports the
    block, instead of (a) mistaking an empty 202 for malformed JSON and
    retrying it, or (b) continuing through the remaining search terms - both
    of which would mean hammering a source that has already said no.

    NOTE for future readers: a bare 202 from this API is NOT success. It has
    no body. Do not treat 2xx as "fine" here without checking the WAF
    header/body.

    partial_products carries whatever get_products() had already collected
    before the block hit, so a collector can still persist real data gathered
    earlier in the run rather than throwing it away."""

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


def _parse_pack_size(text: str | None) -> tuple[float | None, str | None]:
    """"1.5L" -> (1.5, "L"), "0.45kg" -> (0.45, "kg"). Deliberately simple -
    a plain "number then letters" regex on a field ICA already formats
    consistently, not a unit-conversion library. Anything that doesn't match
    this shape (rare, freeform pack descriptions) just returns (None, None)
    rather than guessing."""
    if not text:
        return None, None
    match = re.match(r"^([\d.,]+)\s*([a-zA-ZäöåÄÖÅ]+)$", text.strip())
    if not match:
        return None, None
    try:
        return float(match.group(1).replace(",", ".")), match.group(2)
    except ValueError:
        return None, None


class IcaProvider(GroceryProvider):
    """One ICA region's worth of stores/products, scoped by the zip code
    given at construction - see base.GroceryProvider's docstring on why
    get_stores() takes no argument: ICA's own store lookup is zip-scoped
    (there is no "list every ICA in Sweden" endpoint we found), so a
    provider instance is configured for one search area rather than the
    interface method taking a location parameter. A later phase covering
    more of Sweden just constructs more IcaProvider instances with
    different zips, not a different interface."""

    name = "ICA"
    # Machine-readable counterpart to the status block in this module's
    # docstring, so the status panel (FAS 13) can show provider health
    # without hardcoding per-chain knowledge of its own.
    status = "working_but_rate_limited"
    recurring_import_verified = False

    def __init__(self, zip_code: str, search_terms: list[str] | None = None):
        self.zip_code = zip_code
        self.search_terms = search_terms or DEFAULT_SEARCH_TERMS

    def _request(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
            "Referer": "https://handlaprivatkund.ica.se/",
        })
        last_error = None
        for attempt, delay in enumerate((0, *RETRY_BACKOFF_SECONDS)):
            if delay:
                time.sleep(delay)
            try:
                with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    # A WAF challenge comes back as a perfectly "successful"
                    # 202 with an empty body - checked BEFORE parsing, or it
                    # would look like malformed JSON and get retried. See
                    # IcaBlockedError.
                    if response.headers.get("x-amzn-waf-action"):
                        raise IcaBlockedError(
                            f"ICA's WAF is challenging automated requests "
                            f"(HTTP {response.status}, x-amzn-waf-action="
                            f"{response.headers.get('x-amzn-waf-action')}) for {url}"
                        )
                    body = response.read()
                    if not body.strip():
                        raise IcaBlockedError(f"ICA returned an empty body (HTTP {response.status}) for {url}")
                    return json.loads(body)
            except urllib.error.HTTPError as error:
                # 403/429 mean the source is actively refusing us - per spec
                # section 8, that's a stop-and-report condition, not
                # something to retry through (retrying a block just looks
                # like hammering it harder).
                if error.code in (403, 429):
                    raise IcaBlockedError(f"ICA blocked the request (HTTP {error.code}) for {url}") from error
                last_error = error
                logger.warning("ICA request failed (HTTP %s), attempt %d/%d: %s", error.code, attempt + 1, MAX_RETRIES, url)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("ICA request failed (%s), attempt %d/%d: %s", type(error).__name__, attempt + 1, MAX_RETRIES, url)
            if attempt + 1 >= MAX_RETRIES:
                break
        raise IcaRequestError(f"ICA request failed after {MAX_RETRIES} attempts: {url}") from last_error

    def get_stores(self) -> list[Store]:
        data = self._request(f"{STORE_LOOKUP_URL}?zip={quote(self.zip_code)}&customerType=B2C")
        raw_stores = (data.get("forHomeDelivery") or data.get("forPickupDelivery") or
                      (data.get("combinedHomePickupDelivery") or []))
        stores = []
        for store in raw_stores:
            account_id = store.get("accountId")
            if not account_id:
                continue
            stores.append(Store(
                id=0,  # not a database row yet - GroceryStore.upsert_store assigns the real id
                chain=self.name,
                external_store_id=str(account_id),
                name=store.get("name") or "",
                city=store.get("city"),
                postal_code=store.get("zipCode"),
                address=store.get("street"),
                latitude=store.get("latitude"),
                longitude=store.get("longitude"),
                active=bool(store.get("enable", "1") == "1"),
            ))
        return stores

    def get_products(self, store_id: str) -> list[RawProduct]:
        """Searches DEFAULT_SEARCH_TERMS (see module docstring for why there's
        no direct catalog walk) and returns every uniquely-decorated product
        found, deduplicated by retailerProductId. A failed search term is
        logged and skipped - see the docstring on IcaRequestError - so one
        bad term never aborts the whole run."""
        seen_ids: set[str] = set()
        products: list[RawProduct] = []
        # store_name is informational only (see RawProduct's docstring - it's
        # not a GroceryStore schema column); the store's real name is already
        # in the STORES table via the Store the collector script upserted
        # from get_stores(), so a bare store_id placeholder here is fine.
        store_name = store_id
        for term in self.search_terms:
            time.sleep(REQUEST_DELAY_SECONDS)
            url = (f"https://handlaprivatkund.ica.se/stores/{quote(store_id)}/api/webproductpagews/v6/"
                   f"product-pages/search?includeAdditionalPageInfo=true&maxPageSize=50&maxProductsToDecorate=50"
                   f"&q={quote(term)}&tag=web")
            try:
                data = self._request(url)
            except IcaBlockedError as blocked:
                # Terminal, not per-term: continuing through the remaining
                # search terms would mean sending dozens more requests to a
                # source that has explicitly just refused us. Stop and let the
                # caller report the block, keeping whatever we collected so far.
                logger.error("ICA blocked this collector run at term %r - stopping after %d product(s)", term, len(products))
                blocked.partial_products = products
                raise
            except IcaRequestError:
                logger.exception("ICA product search failed for term %r at store %s", term, store_id)
                continue
            for group in data.get("productGroups") or []:
                for raw in group.get("decoratedProducts") or group.get("products") or []:
                    retailer_id = str(raw.get("retailerProductId") or raw.get("productId") or "")
                    if not retailer_id or retailer_id in seen_ids:
                        continue
                    seen_ids.add(retailer_id)
                    try:
                        products.append(self.normalize_product({**raw, "_store_id": store_id, "_store_name": store_name}))
                    except Exception:
                        logger.exception("Failed to normalize ICA product %r", retailer_id)
        return products

    def get_product_details(self, product_id: str, store_id: str) -> RawProduct | None:
        url = (f"https://handlaprivatkund.ica.se/stores/{quote(store_id)}/api/webproductpagews/v5/"
               f"products/bop?retailerProductId={quote(product_id)}")
        try:
            data = self._request(url)
        except IcaRequestError:
            logger.exception("ICA product detail failed for %r at store %s", product_id, store_id)
            return None
        product = data.get("product")
        if not product:
            return None
        fields_by_title = {field.get("title"): field.get("content") for field in (data.get("bopData") or {}).get("fields") or []}
        raw = self.normalize_product({**product, "_store_id": store_id, "_store_name": store_id})
        # detail-only enrichment the search response doesn't carry
        return RawProduct(**{**raw.__dict__, "description": (data.get("bopData") or {}).get("detailedDescription")})

    def normalize_product(self, raw_product) -> RawProduct:
        price = raw_product.get("price") or {}
        unit_price_block = (raw_product.get("unitPrice") or {}).get("price") or {}
        category_path = raw_product.get("categoryPath") or []
        image = raw_product.get("image") or {}
        retailer_id = str(raw_product.get("retailerProductId") or raw_product.get("productId") or "")
        quantity, unit = _parse_pack_size(raw_product.get("packSizeDescription"))
        store_id = raw_product.get("_store_id", "")
        return RawProduct(
            chain=self.name,
            external_product_id=retailer_id,
            name=raw_product.get("name") or "",
            store_id=store_id,
            store_name=raw_product.get("_store_name", store_id),
            gtin=None,  # confirmed absent from ICA's public API - see module docstring
            ean=None,
            brand=raw_product.get("brand"),
            description=None,  # only available via get_product_details, not search
            size=raw_product.get("packSizeDescription"),
            quantity=quantity,
            unit=unit,
            # The whole path, not just the leaf, in the same "broad > narrow"
            # shape the other chains produce - category-aware matching needs
            # the department, which only the ancestors carry.
            category=CATEGORY_PATH_SEPARATOR.join(str(p) for p in category_path if p) or None,
            image_url=image.get("src") or None,
            regular_price=_to_float(price.get("amount")),
            # Unverified field paths - see module docstring's "FIELDS CONFIRMED
            # ABSENT" section. Read defensively so a real campaign item, if
            # ICA does expose one this way, is picked up automatically -
            # never fabricated when absent.
            campaign_price=_to_float((raw_product.get("campaignPrice") or {}).get("amount") if isinstance(raw_product.get("campaignPrice"), dict) else raw_product.get("campaignPrice")),
            member_price=_to_float((raw_product.get("memberPrice") or {}).get("amount") if isinstance(raw_product.get("memberPrice"), dict) else raw_product.get("memberPrice")),
            multibuy_price=None,
            unit_price=_to_float(unit_price_block.get("amount")),
            currency=price.get("currency") or "SEK",
            source_url=f"https://handlaprivatkund.ica.se/stores/{store_id}/products/produkt/{retailer_id}" if store_id and retailer_id else None,
            fetched_at=time.time(),
        )

    def health_check(self) -> bool:
        try:
            data = self._request(f"{STORE_LOOKUP_URL}?zip={quote(self.zip_code)}&customerType=B2C")
        except IcaRequestError:
            return False
        return bool(data.get("forHomeDelivery") or data.get("forPickupDelivery"))
