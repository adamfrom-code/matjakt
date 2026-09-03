"""Normalized data shapes for the grocery price backend.

Two different "product" shapes exist on purpose:
- RawProduct is what a GroceryProvider hands back after normalize_product() -
  one row as that provider's collector saw it, for one store, not yet
  reconciled against anything else.
- Product is the deduplicated, cross-chain record in GroceryStore's database -
  the thing multiple RawProducts (from different chains, even) can resolve to
  once matched by GTIN/EAN (see GroceryStore.find_or_create_product).

Everything here is a plain dataclass, no ORM - consistent with the rest of
backend/services/*, which is deliberately stdlib-only.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RawProduct:
    """The common shape every GroceryProvider.normalize_product() must return
    - see GroceryProvider's docstring. This is provider output, not yet a
    database row: chain/store identify WHERE this was seen, gtin/ean (when
    the source has them) are what GroceryStore.find_or_create_product uses
    to reconcile it against the shared product catalog."""

    chain: str
    external_product_id: str
    name: str
    store_id: str
    store_name: str
    gtin: str | None = None
    ean: str | None = None
    brand: str | None = None
    description: str | None = None
    size: str | None = None
    quantity: float | None = None
    unit: str | None = None
    category: str | None = None
    image_url: str | None = None
    regular_price: float | None = None
    campaign_price: float | None = None
    member_price: float | None = None
    multibuy_price: float | None = None
    unit_price: float | None = None
    currency: str = "SEK"
    source_url: str | None = None
    fetched_at: float | None = None
    # Kampanjens sista giltighetsdag (epok). Ett kampanjpris utan datum gäller
    # tills källan säger annat; ett med passerat datum får inte användas.
    campaign_valid_to: float | None = None

    def to_dict(self):
        value = asdict(self)
        return {
            "chain": value["chain"],
            "externalProductId": value["external_product_id"],
            "gtin": value["gtin"],
            "ean": value["ean"],
            "name": value["name"],
            "brand": value["brand"],
            "description": value["description"],
            "size": value["size"],
            "quantity": value["quantity"],
            "unit": value["unit"],
            "category": value["category"],
            "imageUrl": value["image_url"],
            "storeId": value["store_id"],
            "storeName": value["store_name"],
            "regularPrice": value["regular_price"],
            "campaignPrice": value["campaign_price"],
            "memberPrice": value["member_price"],
            "multibuyPrice": value["multibuy_price"],
            "unitPrice": value["unit_price"],
            "currency": value["currency"],
            "sourceUrl": value["source_url"],
            "fetchedAt": value["fetched_at"],
        }


@dataclass(frozen=True)
class Product:
    """One row in PRODUCTS - a single real-world product, possibly carried by
    several chains/stores at once (see CurrentPrice, keyed by product_id +
    store_id)."""

    id: int
    name: str
    gtin: str | None = None
    ean: str | None = None
    brand: str | None = None
    description: str | None = None
    size: str | None = None
    quantity: float | None = None
    unit: str | None = None
    category: str | None = None
    image_url: str | None = None
    image_source_url: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    # DABAS-MASTERDATA (2026-09-02). Dabas säger vad produkten ÄR; prisprovidern
    # vad den KOSTAR. dabas_category är en extra REJECT-signal i kanoniska
    # matchningen; package_* säger hur säker paketmängden är:
    #   package_source     DABAS_VERIFIED / PROVIDER_DATA / NORMALIZED_FALLBACK
    #   package_confidence high (Dabas och provider eniga, eller bara Dabas)
    #                      / provider / conflict / none
    #   package_conflict   texten som beskriver konflikten - och då används
    #                      mängden INTE (fail closed i effective_package)
    manufacturer: str | None = None
    dabas_status: str | None = None
    dabas_category: str | None = None
    package_source: str | None = None
    package_confidence: str | None = None
    package_conflict: str | None = None
    # PROVIDERNS EGNA paketvärden, uppdaterade vid varje import och ALDRIG
    # rörda av Dabas. size/quantity/unit ovan är de UPPLÖSTA värdena
    # (provider, eller Dabas när providern saknade). Utan den här
    # separationen skrev en omräkning över Vallmolevains 560 g med Dabas
    # 500 g - en äkta konflikt som försvann i stället för att falla stängt.
    provider_size: str | None = None
    provider_quantity: float | None = None
    provider_unit: str | None = None

    def to_dict(self):
        value = asdict(self)
        return {
            "id": value["id"],
            "gtin": value["gtin"],
            "ean": value["ean"],
            "name": value["name"],
            "brand": value["brand"],
            "description": value["description"],
            "size": value["size"],
            "quantity": value["quantity"],
            "unit": value["unit"],
            "category": value["category"],
            "imageUrl": value["image_url"],
            "imageSourceUrl": value["image_source_url"],
            "createdAt": value["created_at"],
            "updatedAt": value["updated_at"],
        }


@dataclass(frozen=True)
class Store:
    """One row in STORES - one physical store location for one chain."""

    id: int
    chain: str
    external_store_id: str
    name: str
    city: str | None = None
    postal_code: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    active: bool = True
    created_at: float = 0.0
    updated_at: float = 0.0
    # Nationella butiksmodellen (2026-09-02): vilken datakälla som känner
    # butiken ("axfood"/"citygross"/"primat") och hur kedjans priser gäller -
    # "NATIONAL" (samma pris i hela landet, en katalog räcker),
    # "STORE_SPECIFIC" (varje butik har egna priser; bara butiker vars
    # katalog faktiskt importerats får prissättas) eller "REGIONAL"
    # (reserverad). Kedjor är olika på riktigt - modellen ska inte låtsas
    # något annat.
    provider: str | None = None
    pricing_scope: str | None = None

    def to_dict(self):
        value = asdict(self)
        return {
            "id": value["id"],
            "chain": value["chain"],
            "externalStoreId": value["external_store_id"],
            "name": value["name"],
            "city": value["city"],
            "postalCode": value["postal_code"],
            "address": value["address"],
            "latitude": value["latitude"],
            "longitude": value["longitude"],
            "active": value["active"],
            "createdAt": value["created_at"],
            "updatedAt": value["updated_at"],
        }


@dataclass(frozen=True)
class CurrentPrice:
    """One row in CURRENT_PRICES - the latest known price for one product at
    one store. Never deleted on a failed re-fetch (see GroceryStore.upsert_
    current_price's docstring) - a stale price beats no price."""

    id: int
    product_id: int
    store_id: int
    regular_price: float | None
    campaign_price: float | None
    member_price: float | None
    multibuy_price: float | None
    unit_price: float | None
    currency: str
    source_url: str | None
    fetched_at: float
    updated_at: float
    # TVÅ PRISNIVÅER (2026-09-02). tier säger vad raden ÄR:
    #   VERIFIED_STORE_PRICE - ett verkligt pris i en specifik butik (egen
    #                          import av just den butiken, eller partnerfeed)
    #   REFERENCE_PRICE      - kedjans referenspris, får användas nationellt
    #                          men är ALDRIG ett påstående om en viss butik
    # source ("axfood:2132", "primat:ica:1158001", "partner:7") och
    # verified_at säger varifrån och när. valid_to är kampanjens sista dag.
    tier: str = "VERIFIED_STORE_PRICE"
    source: str | None = None
    verified_at: float | None = None
    valid_from: float | None = None
    valid_to: float | None = None

    def to_dict(self):
        value = asdict(self)
        return {
            "id": value["id"],
            "productId": value["product_id"],
            "storeId": value["store_id"],
            "regularPrice": value["regular_price"],
            "campaignPrice": value["campaign_price"],
            "memberPrice": value["member_price"],
            "multibuyPrice": value["multibuy_price"],
            "unitPrice": value["unit_price"],
            "currency": value["currency"],
            "sourceUrl": value["source_url"],
            "fetchedAt": value["fetched_at"],
            "updatedAt": value["updated_at"],
        }


@dataclass(frozen=True)
class PriceHistoryEntry:
    """One row in PRICE_HISTORY - a price snapshot at a point in time. Only
    written when a price actually changed (see GroceryStore.upsert_current_
    price) - not one row per collector run, or a year of nightly runs on an
    unchanged price would write a year of identical rows for nothing."""

    id: int
    product_id: int
    store_id: int
    regular_price: float | None
    campaign_price: float | None
    member_price: float | None
    multibuy_price: float | None
    unit_price: float | None
    timestamp: float

    def to_dict(self):
        value = asdict(self)
        return {
            "id": value["id"],
            "productId": value["product_id"],
            "storeId": value["store_id"],
            "regularPrice": value["regular_price"],
            "campaignPrice": value["campaign_price"],
            "memberPrice": value["member_price"],
            "multibuyPrice": value["multibuy_price"],
            "unitPrice": value["unit_price"],
            "timestamp": value["timestamp"],
        }


@dataclass(frozen=True)
class CollectorRun:
    """One row in COLLECTOR_RUNS - one collector's attempt at one store (or a
    whole chain, when store_id is None), for the status panel (see FAS 13)."""

    id: int
    chain: str
    store_id: int | None
    started_at: float
    finished_at: float | None
    status: str
    products_found: int = 0
    products_created: int = 0
    products_updated: int = 0
    prices_updated: int = 0
    images_found: int = 0
    errors: int = 0
    error_message: str | None = None

    def to_dict(self):
        value = asdict(self)
        return {
            "id": value["id"],
            "chain": value["chain"],
            "storeId": value["store_id"],
            "startedAt": value["started_at"],
            "finishedAt": value["finished_at"],
            "status": value["status"],
            "productsFound": value["products_found"],
            "productsCreated": value["products_created"],
            "productsUpdated": value["products_updated"],
            "pricesUpdated": value["prices_updated"],
            "imagesFound": value["images_found"],
            "errors": value["errors"],
            "errorMessage": value["error_message"],
        }
