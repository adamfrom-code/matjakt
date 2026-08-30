"""Imports real products from ONE Willys store into the grocery database,
via WillysProvider (plain HTTP/JSON, no auth - see providers/willys.py).

Usage (from the repo root):
    python -m backend.services.grocery.collectors.willys --store 2132 --limit 100

--store is Willys' own storeId from the Axfood store list (2132 = Willys
Gävle Gestrike). NOTE: Willys prices are national, not per store - the store
is used for attribution, not to scope pricing. See providers/willys.py.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from services.grocery import GroceryStore  # noqa: E402
from services.grocery.providers.willys import WillysBlockedError, WillysProvider  # noqa: E402

DB_PATH = Path(__file__).resolve().parents[4] / "backend" / "data" / "grocery.db"


def run(store_id: str, limit: int) -> dict:
    started = time.time()
    provider = WillysProvider()
    db = GroceryStore(DB_PATH)
    run_record = db.start_collector_run(chain="Willys")

    stats = dict(found=0, saved=0, with_gtin=0, with_image=0, with_regular_price=0,
                 with_campaign_price=0, with_member_price=0, with_multibuy_price=0,
                 with_unit_price=0, errors=0, created=0, updated=0, price_changes=0)
    saved_examples = []
    blocked_message = None

    try:
        stores = provider.get_stores()
        store = next((s for s in stores if s.external_store_id == store_id), None)
        if store is None:
            raise SystemExit(
                f"Store {store_id!r} was not among the {len(stores)} Willys store(s). "
                f"Try one of: {[s.external_store_id for s in stores[:10]]}"
            )
        db_store = db.upsert_store(
            chain="Willys", external_store_id=store.external_store_id, name=store.name,
            city=store.city, postal_code=store.postal_code, address=store.address,
            latitude=store.latitude, longitude=store.longitude, active=store.active,
        )

        try:
            raw_products = provider.get_products(store_id)
        except WillysBlockedError as blocked:
            blocked_message = str(blocked)
            raw_products = blocked.partial_products
            print(f"\n!! Willys blockerade körningen: {blocked_message}", file=sys.stderr)
            print(f"!! Sparar de {len(raw_products)} produkter som hann hämtas.\n", file=sys.stderr)
        stats["found"] = len(raw_products)

        for raw in raw_products[:limit]:
            try:
                existing = db.get_product_by_external_id("Willys", raw.external_product_id)
                product = db.find_or_create_product(raw)
                stats["created" if existing is None else "updated"] += 1
                if product.gtin:
                    stats["with_gtin"] += 1
                if product.image_url:
                    stats["with_image"] += 1
                if raw.regular_price is not None:
                    stats["with_regular_price"] += 1
                if raw.campaign_price is not None:
                    stats["with_campaign_price"] += 1
                if raw.member_price is not None:
                    stats["with_member_price"] += 1
                if raw.multibuy_price is not None:
                    stats["with_multibuy_price"] += 1
                if raw.unit_price is not None:
                    stats["with_unit_price"] += 1

                _, changed = db.upsert_current_price(
                    product_id=product.id, store_id=db_store.id, regular_price=raw.regular_price,
                    campaign_price=raw.campaign_price, member_price=raw.member_price,
                    multibuy_price=raw.multibuy_price, unit_price=raw.unit_price,
                    currency=raw.currency, source_url=raw.source_url, fetched_at=raw.fetched_at,
                )
                stats["saved"] += 1
                stats["price_changes"] += 1 if changed else 0
                if len(saved_examples) < 5:
                    saved_examples.append((raw.external_product_id, product.id, db_store.id))
            except Exception as error:
                stats["errors"] += 1
                print(f"  ! Failed to save {raw.name!r} ({raw.external_product_id}): {error}", file=sys.stderr)

        if blocked_message:
            status = "blocked"
        elif stats["errors"]:
            status = "partial"
        elif stats["found"] == 0:
            status = "empty"
        else:
            status = "success"
        db.finish_collector_run(
            run_record.id, status=status, products_found=stats["found"],
            products_created=stats["created"], products_updated=stats["updated"],
            prices_updated=stats["saved"], images_found=stats["with_image"],
            errors=stats["errors"], error_message=blocked_message,
        )
    except Exception as error:
        db.finish_collector_run(run_record.id, status="failed", errors=1, error_message=str(error))
        raise
    finally:
        elapsed = time.time() - started
        db.close()

    return {"store": store, "stats": stats, "examples": saved_examples, "elapsed": elapsed}


def print_report(store_id: str, result: dict):
    stats, examples, elapsed, store = result["stats"], result["examples"], result["elapsed"], result["store"]
    print()
    print(f"Willys-butik: {store.name}")
    print(f"Store ID: {store_id}")
    print("Prissättning: NATIONELL (storeId påverkar inte priset - se providers/willys.py)")
    print()
    print(f"Produkter hämtade: {stats['found']}")
    print(f"Produkter sparade: {stats['saved']}")
    print(f"Nya produkter: {stats['created']}")
    print(f"Uppdaterade produkter: {stats['updated']}")
    print(f"Prisändringar (ny historikrad): {stats['price_changes']}")
    print(f"Produkter med bild: {stats['with_image']}")
    print(f"Produkter med GTIN/EAN: {stats['with_gtin']}")
    print(f"Produkter med ordinarie pris: {stats['with_regular_price']}")
    print(f"Produkter med kampanjpris: {stats['with_campaign_price']}")
    print(f"Produkter med medlemspris: {stats['with_member_price']}")
    print(f"Produkter med multibuy: {stats['with_multibuy_price']}")
    print(f"Produkter med unit price: {stats['with_unit_price']}")
    print(f"Fel: {stats['errors']}")
    print(f"Total körtid: {elapsed:.1f}s")

    db = GroceryStore(DB_PATH)
    try:
        print()
        print(f"--- {len(examples)} riktiga produkter, lästa tillbaka ur grocery.db ---")
        for external_id, product_id, db_store_id in examples:
            product = db.get_product(product_id)
            price = db.get_current_price(product_id, db_store_id)
            print()
            print(f"Produkt: {product.name}")
            print(f"External product ID: {external_id}")
            print(f"GTIN/EAN: {product.gtin or product.ean or 'null'}")
            print(f"Varumärke: {product.brand or 'null'}")
            print(f"Storlek: {product.size or 'null'}")
            print(f"Ordinarie pris: {price.regular_price if price.regular_price is not None else 'null'} {price.currency}")
            print(f"Kampanjpris: {price.campaign_price if price.campaign_price is not None else 'null'}")
            print(f"Medlemspris: {price.member_price if price.member_price is not None else 'null'}")
            print(f"Multibuy: {price.multibuy_price if price.multibuy_price is not None else 'null'}")
            print(f"Jämförpris: {price.unit_price if price.unit_price is not None else 'null'}")
            print(f"Bild-URL: {product.image_url or 'null'}")
            print(f"Source URL: {price.source_url or 'null'}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import real Willys products for one store into the grocery database.")
    parser.add_argument("--store", required=True, help="Willys storeId (e.g. 2132 = Willys Gävle Gestrike)")
    parser.add_argument("--limit", type=int, default=100, help="Max products to import (default 100)")
    args = parser.parse_args()

    result = run(store_id=args.store, limit=args.limit)
    print_report(args.store, result)
