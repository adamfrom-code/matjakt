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

# NATTJOBBETS standardbutiker - INTE en produktbegränsning: start() tar
# store_id som parameter, så vilken svensk butik som helst kan importeras
# (butiksregistret i register.py listar alla ~2 800). Willys/Hemköp är
# nationellt prissatta (verifierat - endpointen ignorerar storeId), så deras
# rad identifierar bara körningen. City Gross prissätter PER BUTIK och 3209
# är TESTMARKNADEN GÄVLES butik - fler CG-butiker importeras efterfrågestyrt
# per användarort när kedjans butiksval släpps i UI:t (prissättningen vägrar
# redan ärligt att visa Gävle-priser under en annan butiks namn, se
# resolve_pricing_store).
DEFAULT_STORES = {
    "Willys": "2132",      # Willys Gävle Gestrike (nationellt pris)
    "Hemköp": "4256",      # Hemköp Uppsala Svava C (nationellt pris)
    "City Gross": "3209",  # City Gross Gävle - testmarknadens butik
}

# ICA can be imported, but ONLY when a person asks for it. Repeated automatic
# fetching trips an AWS WAF challenge, which we do not attempt to solve or
# evade, so ICA is deliberately absent from DEFAULT_STORES (and therefore
# from anything the scheduler can reach) and lives here instead. A run is
# expected to be challenged partway through; the partial import is kept, and
# the previous prices are never deleted.
#
# Coop och Lidl importeras via Primat-providern (se providers/primat.py för
# hela utredningen: Coops portal är stängd för externa, Lidl publicerar inga
# ordinarie priser). Manuella tills de klarat samma kvalitetsgate som de tre
# befintliga kedjorna - schemaläggaren når dem medvetet inte, och de syns
# inte i appens jämförelse förrän det beslutet fattas separat.
# Även dessa är TESTMARKNADSDEFAULTS, inte begränsningar: admin-endpointen
# tar store_id och Primat-providern listar hela landets butiker.
MANUAL_ONLY_STORES = {
    "ICA": "1003987",      # Maxi ICA Stormarknad Gävle (full täckning hos Primat)
    "Coop": "206403",      # Coop Eken Gävle (full täckning hos Primat)
    "Lidl": "SE0128",      # Lidl Gävle Stiglund (full täckning hos Primat)
}

ALL_STORES = {**DEFAULT_STORES, **MANUAL_ONLY_STORES}

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
    import os
    if chain in ("Coop", "Lidl"):
        # Ingen direktväg finns (Coops portal stängd för externa, Lidl utan
        # publicerade ordinarie priser) - Primat är den utredda och tillåtna
        # källan. Utan nyckel finns ingen väg alls: säg det, gissa inte.
        from .providers.primat import PrimatProvider
        if not os.environ.get("PRIMAT_API_KEY"):
            raise ValueError(f"{chain} importeras via Primat och kräver PRIMAT_API_KEY i miljön")
        return PrimatProvider(chain)
    if chain == "ICA":
        # Primat föredras när nyckeln finns: butiksspecifika priser med GTIN
        # utan att gå i närheten av ICAs WAF. Den gamla skrap-providern
        # lämnas orörd som manuell fallback för miljöer utan nyckel.
        if os.environ.get("PRIMAT_API_KEY"):
            from .providers.primat import PrimatProvider
            return PrimatProvider("ICA")
        from .providers.ica import IcaProvider
        # Butiksuppslag kräver ett postnummer; MANUAL_ONLY_STORES pekar på
        # ICA Kvantum Gävle, så dess postnummer är rätt default. Utan
        # argumentet kraschade varje manuell adminimport med TypeError innan
        # den ens börjat - "started: true" följt av omedelbar failed.
        return IcaProvider(zip_code="80252")
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
            # One import at a time across ALL chains, not one per chain. Two
            # concurrent walks would write to the same SQLite file and would
            # also double our outbound request rate; the jobs are minutes
            # apart by design, so queuing is not a real cost.
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
        store_id = store_id or ALL_STORES.get(chain)
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
            from .register import CHAIN_PRICE_PROVIDER, CHAIN_PRICING_SCOPE
            db_store = db.upsert_store(
                chain=chain, external_store_id=store.external_store_id, name=store.name,
                city=store.city, postal_code=store.postal_code, address=store.address,
                latitude=store.latitude, longitude=store.longitude, active=store.active,
                provider=CHAIN_PRICE_PROVIDER.get(chain),
                pricing_scope=CHAIN_PRICING_SCOPE.get(chain))

            found = 0

            def save_batch(batch):
                """Writes one category's products immediately.

                Saving as we go, rather than accumulating the whole
                catalogue and writing it at the end, is what keeps a crash
                from costing the entire run - and what stops the
                empty-database bootstrap from starting the same walk over
                again after that crash."""
                nonlocal saved, found
                found += len(batch)
                for raw in batch:
                    try:
                        product = db.find_or_create_product(raw)
                        db.upsert_current_price(
                            product_id=product.id, store_id=db_store.id,
                            regular_price=raw.regular_price, campaign_price=raw.campaign_price,
                            member_price=raw.member_price, multibuy_price=raw.multibuy_price,
                            unit_price=raw.unit_price, currency=raw.currency,
                            source_url=raw.source_url, fetched_at=raw.fetched_at)
                        saved += 1
                    except Exception:
                        logger.exception("Kunde inte spara %r", raw.name)
                _set(productsSaved=saved)

            try:
                leftover = _collect(provider, str(store_id), limit_per_category, save_batch)
            except ProviderBlockedError as blocked:
                # A block is not data loss: whatever was already handed to
                # save_batch is on disk, and anything still in flight comes
                # through here.
                blocked_message = str(blocked)
                leftover = getattr(blocked, "partial_products", []) or []
                logger.warning("%s blockerade importen: %s", chain, blocked_message)

            # Providers without a category walk (City Gross, ICA) return the
            # whole list instead of streaming it.
            if leftover:
                save_batch(leftover)

            status_text = "blocked" if blocked_message else ("success" if saved else "empty")
            db.finish_collector_run(run_record.id, status=status_text,
                                    products_found=found, prices_updated=saved,
                                    errors=0, error_message=blocked_message)
        except Exception as error:
            # Utan denna hoppade varje oväntad krasch (get_stores-fel, okänd
            # butik, providerbugg) över finish_collector_run och lämnade
            # raden som evig fantom-"running" i adminpanelen, med lastRun
            # olöst för alltid. ProviderBlockedError fångas redan i den inre
            # hanteringen; det här är allt annat.
            logger.exception("%s-importen kraschade", chain)
            db.finish_collector_run(run_record.id, status="failed",
                                    products_found=0, prices_updated=saved,
                                    errors=1, error_message=str(error)[:300])
            grocery_api.clear_cache()
            _set(running=False, finishedAt=time.time(), status="failed",
                 message=str(error)[:300])
            return
        finally:
            db.close()

        # New prices must be visible immediately, not after the read cache TTL.
        grocery_api.clear_cache()
        _set(running=False, finishedAt=time.time(), productsSaved=saved,
             status="blocked" if blocked_message else "done", message=blocked_message)
        logger.info("Import klar för %s: %d produkter", chain, saved)
        if saved:
            # Fresh shelf prices should reach the recipe cards without a
            # redeploy. Guarded: the grocery stack must work even where the
            # recipes service is absent, and a reprice failure is a stale
            # card, never a failed import.
            try:
                from ..recipes import prices as recipe_prices
                recipe_prices.reprice_in_background(f"import {chain}")
            except Exception:
                logger.exception("Kunde inte starta receptprissättningen")
    except Exception as error:
        logger.exception("Import misslyckades för %s", chain)
        _set(running=False, finishedAt=time.time(), status="failed", message=str(error))


def _collect(provider, store_id: str, limit_per_category: int | None, on_products=None):
    """Category walk where the provider supports one, term search otherwise.

    Returns whatever was NOT already handed to on_products - an empty list
    for a streaming category walk, and the full list for a provider that can
    only return everything at once."""
    if not hasattr(provider, "get_products_by_category"):
        return provider.get_products(store_id)

    categories = provider.get_categories()
    _set(categoriesTotal=len(categories))

    def on_category(category, _count=[0]):
        _count[0] += 1
        _set(categoriesDone=_count[0], currentCategory=category.get("path") or category.get("slug"))

    return provider.get_products_by_category(
        store_id, categories, limit_per_category=limit_per_category,
        on_category=on_category, on_products=on_products)
