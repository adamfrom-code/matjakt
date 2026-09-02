# -*- coding: utf-8 -*-
"""Nightly imports for the chains that have actually proven they tolerate one.

WHICH CHAINS RUN AUTOMATICALLY, AND WHY NOT THE OTHERS
Automatic collection is a claim that repeated unattended fetching works and
is welcome. Only three chains have earned it:

  Willys      verified: two consecutive full runs, no block
  Hemköp      verified: same, on the same Axfood platform
  City Gross  verified, but it throttles by DROPPING CONNECTIONS rather than
              answering HTTP 429, so it runs conservatively (the provider's
              own 3 s delay and retry) and a partial run is treated as
              normal, not as a failure

  ICA         NOT automatic. Repeated fetching trips an AWS WAF challenge,
              and we do not attempt to solve or evade it. ICA keeps its last
              imported data and is refreshed manually until official access
              exists. Running it on a nightly timer would be exactly the
              aggressive repetition that trips the challenge.
  Coop        never runs. All data sits behind Coop's own API credential,
              and we do not authenticate with someone else's key.
  Lidl        never runs. Lidl Sweden publishes no per-product prices at
              all - there is nothing to fetch, and nothing to fake.

Times are Europe/Stockholm, which is the point: a "03:00" job that silently
means 03:00 UTC would drift an hour twice a year against the shelf prices it
is meant to mirror.

A FAILED RUN NEVER DELETES ANYTHING. Imports only ever upsert; there is no
delete path here at all. A blocked or failed run leaves every previously
collected price exactly where it was (see importer._run).
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    STOCKHOLM = ZoneInfo("Europe/Stockholm")
except Exception:  # pragma: no cover - zoneinfo missing its database
    STOCKHOLM = None

from . import importer

logger = logging.getLogger("matjakt.grocery.scheduler")

# Chain -> hour:minute, Europe/Stockholm. Staggered rather than all at once:
# three simultaneous category walks would triple our request rate against
# three different sites in the same minute, and the importer only runs one at
# a time anyway, so they would just queue.
DEFAULT_SCHEDULE = {
    "Willys": "02:00",
    "Hemköp": "03:00",
    "City Gross": "04:00",
}

# Deliberately not configurable to include ICA/Coop/Lidl - see the module
# docstring. A config typo must not be able to start hammering a chain that
# has told us no.
SCHEDULABLE_CHAINS = frozenset(DEFAULT_SCHEDULE)

CHECK_INTERVAL_SECONDS = 60

# Veckodag + klockslag (Europe/Stockholm, strftime "%a %H:%M") för den
# nationella butiksregistersynken.
REGISTER_SYNC_AT = "Sun 01:00"
# Nattligt nyförsök när registret saknas. Primats dygnskvot nollställs vid
# midnatt UTC = 02:00 svensk sommartid, så försöket ligger EFTER det -
# annars faller det på gårdagens förbrukning (verifierat 2026-09-02: 429
# daily_row_budget_exceeded fram till resetten).
REGISTER_RETRY_AT = "03:15"
# Nattlig självläkning av referensnivån, efter prisjobben (02-04) och före
# Dabas-berikningen (05:00).
REFERENCE_HEAL_AT = "04:45"

# Dabas-berikning, efter att prisjobben (02-04) hunnit publicera nya GTIN.
DABAS_ENRICHMENT_AT = "05:00"

# Which chain fills an empty database first. Willys: the largest verified
# catalogue (10 842 products, 100 % with category), plain HTTP with no
# browser, and the chain most likely to be near any given user.
BOOTSTRAP_CHAIN = "Willys"


def parse_schedule(raw: str | None) -> dict:
    """Reads MATJAKT_GROCERY_SCHEDULE, e.g. "Willys=02:00,Hemköp=03:30".

    An unparseable or unknown entry is logged and skipped rather than
    silently changing which chain runs when - and a chain that is not
    schedulable is refused outright, whatever the config says."""
    if not raw:
        return dict(DEFAULT_SCHEDULE)
    schedule = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        chain, _, when = part.partition("=")
        chain, when = chain.strip(), when.strip()
        if chain not in SCHEDULABLE_CHAINS:
            logger.warning("Hoppar över %r i schemat: kedjan får inte köras automatiskt", chain)
            continue
        try:
            hour, minute = (int(value) for value in when.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError(when)
        except ValueError:
            logger.warning("Hoppar över %r i schemat: %r är inte HH:MM", chain, when)
            continue
        schedule[chain] = f"{hour:02d}:{minute:02d}"
    return schedule or dict(DEFAULT_SCHEDULE)


def _now():
    return datetime.now(STOCKHOLM) if STOCKHOLM else datetime.now()


def next_run_at(chain: str, schedule: dict, reference=None):
    """When this chain runs next, as a Europe/Stockholm datetime."""
    when = schedule.get(chain)
    if not when:
        return None
    hour, minute = (int(value) for value in when.split(":"))
    reference = reference or _now()
    candidate = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= reference:
        candidate += timedelta(days=1)
    return candidate


class GroceryScheduler:
    """A plain timer thread. No cron, no extra dependency - the whole backend
    is stdlib-only by design, and one sleeping thread is enough for three
    jobs a day."""

    def __init__(self, schedule: dict | None = None):
        self.schedule = schedule if schedule is not None else parse_schedule(
            os.environ.get("MATJAKT_GROCERY_SCHEDULE"))
        self.enabled = _truthy(os.environ.get("MATJAKT_GROCERY_SCHEDULE_ENABLED", "0"))
        self._thread = None
        self._stop = threading.Event()
        # The minute a chain last fired, so a job cannot run twice inside the
        # same minute if the loop wakes up more than once in it.
        self._last_fired = {}

    def bootstrap_if_empty(self):
        """Runs the first import immediately when the price database is empty.

        A Render deploy comes up on a persistent disk that is empty on first
        boot - backend/data/ is gitignored, so no database ships in the image.
        Without this the app sat there with zero products until the first
        nightly job happened to run, and every price on matjakt.store was the
        flat estimate. Verified in production: /api/grocery/status reported
        totalProducts 0 on a fully deployed backend.

        Guards, both necessary:
          - only when the scheduler is enabled, so a local dev run never
            starts fetching from three chains on its own;
          - only chains with no completed run, so an ordinary deploy does not
            re-import a catalogue that is already there.
        """
        if not self.enabled:
            return False
        try:
            from . import api as grocery_api
            summary = grocery_api.database_summary()
            providers = {entry["chain"]: entry for entry in grocery_api.provider_status()}
        except Exception:
            logger.exception("Kunde inte läsa prisdatabasens tillstånd - hoppar över bootstrap")
            return False

        # EVERY schedulable chain that has never completed an import gets one
        # now, not just Willys. Production ran for hours with Willys full and
        # Hemköp/City Gross at zero products, because their data had only
        # ever existed on a disk that predated persistence - and the only
        # thing that would fill them was the wall clock reaching 03:00. An
        # empty chain is an empty chain; which one it is does not matter.
        #
        # A chain that HAS a completed run is left alone however old its data
        # is - freshness is the nightly job's job, not bootstrap's.
        needy = []
        for chain in sorted(SCHEDULABLE_CHAINS,
                            key=lambda name: (name != BOOTSTRAP_CHAIN, name)):
            state = providers.get(chain) or {}
            # This cannot loop: once one run finishes, lastSuccessfulRun is
            # set and the condition stops being true, however many times we
            # restart.
            if state.get("products", 0) == 0 or not state.get("lastSuccessfulRun"):
                needy.append(chain)
        if not needy:
            return False

        logger.warning("Prisdatabasen saknar fungerande data för %s - importerar",
                       ", ".join(needy))
        started_any = False
        for chain in needy:
            if not importer.start(chain).get("started"):
                continue
            started_any = True
            # One at a time, waited for, not fired in parallel: the importer
            # refuses concurrent runs anyway, and three simultaneous walks on
            # a booting 512 MB instance is how the last OOM happened. Waiting
            # here is free - this whole method runs on its own daemon thread.
            while importer.status().get("running"):
                time.sleep(30)
        return started_any

    def start(self):
        if not self.enabled:
            logger.info("Nattjobb för prisimport är avstängt "
                        "(sätt MATJAKT_GROCERY_SCHEDULE_ENABLED=1 för att slå på)")
            return False
        if self._thread and self._thread.is_alive():
            return False
        # Any run still marked "running" belongs to a process that no longer
        # exists - clear it before anything reads or acts on that status.
        try:
            from . import api as grocery_api
            store = grocery_api.open_store()
            try:
                stale = store.reconcile_interrupted_runs()
            finally:
                store.close()
            if stale:
                logger.warning("Markerade %d avbruten körning(ar) från en tidigare process", stale)
        except Exception:
            logger.exception("Kunde inte städa avbrutna körningar")

        self._thread = threading.Thread(target=self._loop, name="grocery-scheduler", daemon=True)
        self._thread.start()
        logger.info("Nattjobb startat: %s (Europe/Stockholm)", self.schedule)
        # In its own thread: the import takes tens of minutes and must not
        # hold up the server binding its port (Render would call that a
        # failed deploy).
        threading.Thread(target=self.bootstrap_if_empty, name="grocery-bootstrap",
                         daemon=True).start()
        threading.Thread(target=self.activate_platform, name="grocery-platform-activate",
                         daemon=True).start()
        return True

    def activate_platform(self):
        """Den nationella prisplattformen aktiverar sig själv vid deploy:

          1. REFERENSPRISER: finns verifierade butikspriser men ingen
             referensrad ännu, lyfts de en gång (backfill) - appen behöver
             inte vänta på nattjobbet för att få "<Kedja> referenspris".
          2. BUTIKSREGISTRET: saknar databasen ett nationellt register och
             finns en Primat-nyckel, synkas registret (2 800 rader, en gång;
             därefter veckovis via _tick).

        Bägge är idempotenta och guardade så en omstart aldrig kostar en
        ny kvotrunda i onödan."""
        if not self.enabled:
            return
        try:
            from . import api as grocery_api
            from .publish import backfill_reference_prices, chains_needing_reference_backfill
            store = grocery_api.open_store()
            try:
                # Självläkande PER KEDJA: en backfill som avbröts av en omstart
                # (deploy mitt i City Gross) lämnar en kedja tom medan totalen
                # ser rimlig ut. Varje kedja vars referens släpar fylls.
                # Backfillen är idempotent.
                needing = chains_needing_reference_backfill(store)
                if needing:
                    logger.warning("Referensnivån släpar för %s - referenspubliceringen körs",
                                   ", ".join(needing))
                    backfill_reference_prices(store, needing)
                    grocery_api.clear_cache()
                registered = store.connection.execute(
                    "SELECT COUNT(*) FROM grocery_stores WHERE latitude IS NOT NULL").fetchone()[0]
            finally:
                store.close()
            if registered < 100 and os.environ.get("PRIMAT_API_KEY"):
                self._sync_register("första registersynken")
            # Paketkällnivå på varje produkt (PROVIDER_VERIFIED/NORMALIZED/NONE)
            # så att raderna bär sin nivå även utan Dabas. Idempotent.
            from .enrichment import classify_package_sources, enrichment_enabled, recompute_verdicts
            store = grocery_api.open_store()
            try:
                classified = classify_package_sources(store)
                # Paketverdikten räknas om ur sparade Dabas-ögonblicksbilder
                # vid varje boot (inga API-anrop): en regeländring i
                # package_verdict slår igenom direkt, gamla falska
                # konflikter försvinner utan att vänta på 30-dagarsomprövningen.
                recomputed = recompute_verdicts(store)
            finally:
                store.close()
            if classified:
                logger.info("Paketkällor klassade: %s", classified)
            if recomputed:
                logger.info("Paketverdikt omräknade: %s", recomputed)
                grocery_api.clear_cache()
            # Dabas-berikning i bakgrunden direkt vid boot (text/paket/kategori,
            # aldrig bilder) - appen väntar aldrig på den.
            if enrichment_enabled():
                threading.Thread(target=self._run_dabas_enrichment,
                                 name="grocery-dabas-boot", daemon=True).start()
        except Exception:
            logger.exception("Plattformsaktiveringen misslyckades - nattjobbet fortsätter ändå")

    def _run_dabas_enrichment(self):
        from . import api as grocery_api
        from .enrichment import enrichment_enabled, run_enrichment
        if not enrichment_enabled():
            return
        store = grocery_api.open_store()
        try:
            summary = run_enrichment(store)
        finally:
            store.close()
        if summary.get("ok"):
            grocery_api.clear_cache()
        logger.info("Dabas-berikning (nattjobb): %s", summary)

    def _sync_register_if_missing(self):
        try:
            from . import api as grocery_api
            if grocery_api.store_register_count() >= 100 or not os.environ.get("PRIMAT_API_KEY"):
                return
            self._sync_register("nattligt nyförsök")
        except Exception:
            logger.exception("Registersynkens nyförsök misslyckades - försöker i morgon")

    def _sync_register(self, why: str):
        api_key = os.environ.get("PRIMAT_API_KEY")
        if not api_key:
            return
        from . import api as grocery_api
        from .register import sync_store_register
        store = grocery_api.open_store()
        try:
            summary = sync_store_register(store, api_key)
            logger.info("Butiksregistret synkat (%s): %s", why, summary)
        finally:
            store.close()
        grocery_api.clear_cache()

    def stop(self):
        self._stop.set()

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "running": bool(self._thread and self._thread.is_alive()),
            "timezone": "Europe/Stockholm",
            "schedule": [
                {
                    "chain": chain,
                    "time": when,
                    "nextRunAt": (next_run_at(chain, self.schedule) or "").isoformat()
                    if next_run_at(chain, self.schedule) else None,
                }
                for chain, when in sorted(self.schedule.items())
            ],
            # Named explicitly so the admin panel can say WHY a chain has no
            # nightly job, instead of leaving a blank that reads as an
            # oversight.
            "notScheduled": {
                "ICA": "Bakom feature gate: referenskatalog via Primat kräver App-nivå för full nattsynk",
                "Coop": "Bakom feature gate: samma som ICA",
                "Lidl": "Bakom feature gate: Primats Lidl-feed är för liten för en hel matkorg",
            },
            "registerSyncAt": REGISTER_SYNC_AT,
        }

    def _loop(self):
        while not self._stop.wait(CHECK_INTERVAL_SECONDS):
            try:
                self._tick()
            except Exception:
                # A scheduler that dies on one bad tick silently stops every
                # future import, which looks identical to "prices are just
                # old".
                logger.exception("Schemaläggarens tick misslyckades")

    def _tick(self, now=None):
        now = now or _now()
        stamp = now.strftime("%Y-%m-%d %H:%M")
        # Butiksregistret: veckovis (söndag 01:00), separat från prisjobben -
        # butiker byter inte adress varje natt och synken kostar ~2 800 rader
        # av Primat-kvoten.
        if (now.strftime("%a %H:%M") == REGISTER_SYNC_AT
                and self._last_fired.get("__register__") != stamp):
            self._last_fired["__register__"] = stamp
            threading.Thread(target=self._sync_register, args=("veckosynk",),
                             name="grocery-register-sync", daemon=True).start()
        # Saknas registret helt (första synken föll t.ex. på dagens Primat-
        # kvot) görs ett nytt försök varje natt tills det sitter - utan att
        # vänta på nästa deploy eller söndag.
        if (now.strftime("%H:%M") == REGISTER_RETRY_AT
                and self._last_fired.get("__register_retry__") != stamp):
            self._last_fired["__register_retry__"] = stamp
            threading.Thread(target=self._sync_register_if_missing,
                             name="grocery-register-retry", daemon=True).start()
        # Referensnivån läks varje natt efter prisjobben, inte bara vid boot:
        # en kedja vars referens släpar efter sina verifierade priser fylls.
        if (now.strftime("%H:%M") == REFERENCE_HEAL_AT
                and self._last_fired.get("__reference_heal__") != stamp):
            self._last_fired["__reference_heal__"] = stamp
            threading.Thread(target=self.activate_platform,
                             name="grocery-reference-heal", daemon=True).start()
        # Dabas-berikning efter nattens prisjobb: nya GTIN får masterdata,
        # gamla omprövas i sitt fönster. Bara när den uttryckligen är
        # aktiverad (nyckel + MATJAKT_DABAS_ENRICHMENT_ENABLED=1).
        if (now.strftime("%H:%M") == DABAS_ENRICHMENT_AT
                and self._last_fired.get("__dabas__") != stamp):
            self._last_fired["__dabas__"] = stamp
            threading.Thread(target=self._run_dabas_enrichment,
                             name="grocery-dabas-enrichment", daemon=True).start()
        for chain, when in self.schedule.items():
            if now.strftime("%H:%M") != when or self._last_fired.get(chain) == stamp:
                continue
            self._last_fired[chain] = stamp
            result = importer.start(chain)
            if result.get("started"):
                logger.info("Nattjobb startade import för %s", chain)
            else:
                # Not an error: the importer allows one run at a time on
                # purpose, and a still-running job is the normal reason.
                logger.info("Nattjobb hoppade över %s: %s", chain, result.get("reason"))


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


SCHEDULER = GroceryScheduler()
