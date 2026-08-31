# -*- coding: utf-8 -*-
"""Runs a collector import inside the running server, in the background.

WHY THIS EXISTS. The Render disk at /app/backend/data persists grocery.db
across deploys and restarts (verified), but nothing ever PUTS anything in it:
backend/data/ is gitignored so no database ships in the image, and the
collectors are CLI scripts that only ever ran on a developer's machine. A
production deploy therefore comes up with an empty, permanently empty price
database - and an empty chain prices a week at 0 kr, which would read as
"cheapest".

A full category walk takes tens of minutes, far longer than any HTTP request
may last, so the trigger starts a background thread and returns immediately.
Progress is readable while it runs.

SAFETY RULES (the same ones the collectors follow):
  - Only ONE import at a time. Two concurrent walks would double the request
    rate against the chains and race on the same SQLite file.
  - A failed or blocked run NEVER deletes existing prices; it leaves whatever
    it managed to collect and records why it stopped.
  - Import is gated by the admin token, never by a user account.
"""

import logging
import threading
import time

from . import api as grocery_api
from .errors import ProviderBlockedError

logger = logging.getLogger("matjakt.grocery.importer")

# Store used for attribution per chain. Prices at Willys/Hemköp are national
# (verified - the endpoint accepts but ignores storeId), so this identifies
# the run, it does not scope the price.
DEFAULT_STORES = {
    "Willys": "2132",      # Willys Gävle Gestrike
    "Hemköp": "4256",      # Hemköp Uppsala Svava C - nearest online store
    "City Gross": "3209",  # City Gross Gävle (storeNumber, not id/siteId)
}

_state = {
    "running": False,
    "chain": None,
    "startedAt": None,
    "finishedAt": None,
    "categoriesDone": 0,
    "categoriesTotal": 0,
    "currentCategory": None,
    "productsSaved": 0,
    "status": "idle",
    "message": None,
}
_lock = threading.Lock()


def status() -> dict:
    with _lock:
        state = dict(_state)
    if state["startedAt"]:
        end = state["finishedAt"] or time.time()
        state["elapsedSeconds"] = round(end - state["startedAt"], 1)
    return state


def _set(**fields):
    with _lock:
        _state.update(fields)


def _provider_for(chain: str):
    if chain == "Willys":
        from .providers.willys import WillysProvider
        return WillysProvider()
    if chain == "Hemköp":
        from .providers.hemkop import HemkopProvider
        return HemkopProvider()
    if chain == "City Gross":
        from .providers.citygross import CityGrossProvider
        return CityGrossProvider()
    raise ValueError(f"Ingen importerbar provider för {chain!r}")


def start(chain: str, store_id: str | None = None, limit_per_category: int | None = None) -> dict:
    """Starts an import. Returns immediately; poll status() for progress."""
    with _lock:
        if _state["running"]:
            return {"started": False, "reason": "already_running", "state": dict(_state)}
        _state.update(running=True, chain=chain, startedAt=time.time(), finishedAt=None,
                      categoriesDone=0, categoriesTotal=0, currentCategory=None,
                      productsSaved=0, status="running", message=None)

    thread = threading.Thread(target=_run, args=(chain, store_id, limit_per_category),
                              name=f"grocery-import-{chain}", daemon=True)
    thread.start()
    return {"started": True, "chain": chain}


def _run(chain: str, store_id: str | None, limit_per_category: int | None):
    try:
        provider = _provider_for(chain)
        store_id = store_id or DEFAULT_STORES.get(chain)
        if not store_id:
            raise ValueError(f"Ingen butik angiven för {chain!r}")

        db = grocery_api.open_store()
        run_record = db.start_collector_run(chain=chain)
        blocked_message = None
        saved = 0
        try:
            stores = provider.get_stores()
            store = next((s for s in stores if s.external_store_id == str(store_id)), None)
            if store is None:
                raise ValueError(f"Butik {store_id!r} finns inte hos {chain}")
            db_store = db.upsert_store(
                chain=chain, external_store_id=store.external_store_id, name=store.name,
                city=store.city, postal_code=store.postal_code, address=store.address,
                latitude=store.latitude, longitude=store.longitude, active=store.active)

            try:
                raw_products = _collect(provider, str(store_id), limit_per_category)
            except ProviderBlockedError as blocked:
                # A block is not data loss: keep everything collected so far.
                blocked_message = str(blocked)
                raw_products = getattr(blocked, "partial_products", []) or []
                logger.warning("%s blockerade importen: %s", chain, blocked_message)

            for raw in raw_products:
                try:
                    product = db.find_or_create_product(raw)
                    db.upsert_current_price(
                        product_id=product.id, store_id=db_store.id,
                        regular_price=raw.regular_price, campaign_price=raw.campaign_price,
                        member_price=raw.member_price, multibuy_price=raw.multibuy_price,
                        unit_price=raw.unit_price, currency=raw.currency,
                        source_url=raw.source_url, fetched_at=raw.fetched_at)
                    saved += 1
                    if saved % 100 == 0:
                        _set(productsSaved=saved)
                except Exception:
                    logger.exception("Kunde inte spara %r", raw.name)

            status_text = "blocked" if blocked_message else ("success" if saved else "empty")
            db.finish_collector_run(run_record.id, status=status_text,
                                    products_found=len(raw_products), prices_updated=saved,
                                    errors=0, error_message=blocked_message)
        finally:
            db.close()

        # New prices must be visible immediately, not after the read cache TTL.
        grocery_api.clear_cache()
        _set(running=False, finishedAt=time.time(), productsSaved=saved,
             status="blocked" if blocked_message else "done", message=blocked_message)
        logger.info("Import klar för %s: %d produkter", chain, saved)
    except Exception as error:
        logger.exception("Import misslyckades för %s", chain)
        _set(running=False, finishedAt=time.time(), status="failed", message=str(error))


def _collect(provider, store_id: str, limit_per_category: int | None):
    """Category walk where the provider supports one, term search otherwise."""
    if not hasattr(provider, "get_products_by_category"):
        return provider.get_products(store_id)

    categories = provider.get_categories()
    _set(categoriesTotal=len(categories))

    def on_category(category, _count=[0]):
        _count[0] += 1
        _set(categoriesDone=_count[0], currentCategory=category.get("path") or category.get("slug"))

    return provider.get_products_by_category(
        store_id, categories, limit_per_category=limit_per_category, on_category=on_category)
