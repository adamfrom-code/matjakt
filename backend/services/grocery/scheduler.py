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

        Guards, all three necessary:
          - only when the scheduler is enabled, so a local dev run never
            starts fetching from three chains on its own;
          - only when the database holds NOTHING, so an ordinary deploy does
            not re-import a catalogue that is already there;
          - one chain only. The others follow on their normal nightly slots.
            Importing three at once on a 512 MB instance, right as it boots
            and while Chromium is warming up, is how the last OOM happened.
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

        chain = BOOTSTRAP_CHAIN
        state = providers.get(chain) or {}
        empty = summary["totalProducts"] == 0
        # A catalogue that has NEVER been imported all the way through is not
        # a working catalogue. Production sat on 2 538 of ~11 000 products
        # because a deploy killed the import partway and the old guard
        # ("only when totally empty") refused to resume - leaving a quarter
        # of a catalogue until the next nightly run.
        #
        # This cannot loop: once one run finishes, lastSuccessfulRun is set
        # and the condition stops being true, however many times we restart.
        never_finished = not state.get("lastSuccessfulRun")
        if not (empty or never_finished):
            return False

        logger.warning("Prisdatabasen är %s - startar en import av %s",
                       "tom" if empty else "ofullständig (ingen körning har blivit klar)", chain)
        return bool(importer.start(chain).get("started"))

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
        return True

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
                "ICA": "AWS WAF-challenge vid upprepad hämtning - uppdateras manuellt",
                "Coop": "Kräver Coops egen API-nyckel",
                "Lidl": "Publicerar inga per-produkt-priser",
            },
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
