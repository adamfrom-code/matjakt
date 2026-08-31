# -*- coding: utf-8 -*-
"""Tests for the nightly import scheduler.

The important behaviour is not "does a timer fire" - it is WHICH CHAINS ARE
ALLOWED TO RUN. Automatic collection is a claim that repeated unattended
fetching works and is welcome, and three chains have not earned it: ICA trips
an AWS WAF challenge, Coop needs someone else's API credential, and Lidl
publishes no prices at all. A config typo must not be able to start hammering
any of them.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery import scheduler as scheduler_module  # noqa: E402
from services.grocery.scheduler import (  # noqa: E402
    DEFAULT_SCHEDULE, SCHEDULABLE_CHAINS, GroceryScheduler, next_run_at, parse_schedule,
)


class SchedulableChainsTest(unittest.TestCase):
    def test_only_the_verified_chains_are_schedulable(self):
        self.assertEqual(set(SCHEDULABLE_CHAINS), {"Willys", "Hemköp", "City Gross"})

    def test_blocked_chains_cannot_be_scheduled_by_config(self):
        """The whole point of the allow-list: a typo in an env var must not
        put ICA, Coop or Lidl on a nightly timer."""
        for chain in ("ICA", "Coop", "Lidl"):
            schedule = parse_schedule(f"{chain}=02:00")
            self.assertNotIn(chain, schedule)
            # Falls back to the safe default rather than to an empty schedule
            # that would silently stop all imports.
            self.assertEqual(schedule, DEFAULT_SCHEDULE)

    def test_a_valid_override_is_honoured(self):
        self.assertEqual(parse_schedule("Willys=05:30"), {"Willys": "05:30"})

    def test_several_chains_can_be_overridden(self):
        self.assertEqual(parse_schedule("Willys=01:00,Hemköp=01:30"),
                         {"Willys": "01:00", "Hemköp": "01:30"})

    def test_an_unparseable_time_is_skipped_not_guessed(self):
        self.assertEqual(parse_schedule("Willys=nattetid,Hemköp=03:00"), {"Hemköp": "03:00"})

    def test_out_of_range_times_are_rejected(self):
        self.assertEqual(parse_schedule("Willys=25:00"), DEFAULT_SCHEDULE)
        self.assertEqual(parse_schedule("Willys=02:99"), DEFAULT_SCHEDULE)

    def test_empty_config_uses_the_defaults(self):
        self.assertEqual(parse_schedule(""), DEFAULT_SCHEDULE)
        self.assertEqual(parse_schedule(None), DEFAULT_SCHEDULE)

    def test_defaults_are_staggered(self):
        """Three simultaneous category walks would triple our request rate
        against three sites in the same minute."""
        times = sorted(DEFAULT_SCHEDULE.values())
        self.assertEqual(len(set(times)), len(times))


class NextRunTest(unittest.TestCase):
    def test_later_today_when_the_time_has_not_passed(self):
        reference = datetime(2026, 8, 31, 1, 0)
        self.assertEqual(next_run_at("Willys", {"Willys": "02:00"}, reference),
                         datetime(2026, 8, 31, 2, 0))

    def test_tomorrow_when_the_time_has_passed(self):
        reference = datetime(2026, 8, 31, 3, 0)
        self.assertEqual(next_run_at("Willys", {"Willys": "02:00"}, reference),
                         datetime(2026, 9, 1, 2, 0))

    def test_unscheduled_chain_has_no_next_run(self):
        self.assertIsNone(next_run_at("ICA", DEFAULT_SCHEDULE))


class TickTest(unittest.TestCase):
    def setUp(self):
        self.started = []
        self._real_start = scheduler_module.importer.start
        scheduler_module.importer.start = lambda chain, **kwargs: (
            self.started.append(chain) or {"started": True, "chain": chain})
        self.addCleanup(lambda: setattr(scheduler_module.importer, "start", self._real_start))
        self.scheduler = GroceryScheduler({"Willys": "02:00", "Hemköp": "03:00"})

    def test_fires_the_chain_whose_time_it_is(self):
        self.scheduler._tick(datetime(2026, 8, 31, 2, 0))
        self.assertEqual(self.started, ["Willys"])

    def test_fires_nothing_at_another_time(self):
        self.scheduler._tick(datetime(2026, 8, 31, 2, 30))
        self.assertEqual(self.started, [])

    def test_does_not_fire_twice_within_the_same_minute(self):
        """The loop can wake more than once inside a minute; a second run
        would double our request rate against the chain for no gain."""
        self.scheduler._tick(datetime(2026, 8, 31, 2, 0))
        self.scheduler._tick(datetime(2026, 8, 31, 2, 0, 30))
        self.assertEqual(self.started, ["Willys"])

    def test_fires_again_the_next_day(self):
        self.scheduler._tick(datetime(2026, 8, 31, 2, 0))
        self.scheduler._tick(datetime(2026, 9, 1, 2, 0))
        self.assertEqual(self.started, ["Willys", "Willys"])

    def test_a_still_running_import_is_skipped_not_an_error(self):
        scheduler_module.importer.start = lambda chain, **kwargs: {
            "started": False, "reason": "already_running"}
        self.scheduler._tick(datetime(2026, 8, 31, 2, 0))  # must not raise

    def test_status_names_why_each_blocked_chain_has_no_job(self):
        """A blank next-run for ICA/Coop/Lidl would read as an oversight."""
        status = self.scheduler.status()
        self.assertEqual(set(status["notScheduled"]), {"ICA", "Coop", "Lidl"})
        self.assertEqual(status["timezone"], "Europe/Stockholm")

    def test_disabled_by_default(self):
        """A local dev run must not start fetching from three chains on its
        own."""
        self.assertFalse(GroceryScheduler({}).enabled)
        self.assertFalse(GroceryScheduler({}).start())



class BootstrapTest(unittest.TestCase):
    """A deploy onto an empty persistent disk must fill itself.

    Verified in production before this existed: /api/grocery/status reported
    totalProducts 0 on a fully deployed backend, so every price on
    matjakt.store was the flat estimate.
    """

    def setUp(self):
        self.started = []
        self._real_start = scheduler_module.importer.start
        scheduler_module.importer.start = lambda chain, **kwargs: (
            self.started.append(chain) or {"started": True, "chain": chain})
        self.addCleanup(lambda: setattr(scheduler_module.importer, "start", self._real_start))
        self.scheduler = GroceryScheduler({"Willys": "02:00"})
        self.scheduler.enabled = True

    def _summary(self, total, finished=True, chains=None):
        """`finished` is whether a full import has EVER completed. A
        catalogue that has never finished importing is not a working
        catalogue, however many rows it happens to hold.

        `chains` overrides the per-chain state: {chain: (products, finished)}.
        By default every schedulable chain mirrors the summary, because that
        is what provider_status really returns - a mock that only mentions
        Willys would make the other chains look permanently empty."""
        from services.grocery import api as grocery_api
        real_summary = grocery_api.database_summary
        real_status = grocery_api.provider_status
        if chains is None:
            chains = {chain: (total, finished)
                      for chain in scheduler_module.SCHEDULABLE_CHAINS}
        grocery_api.database_summary = lambda: {"totalProducts": total, "chains": []}
        grocery_api.provider_status = lambda: [
            {"chain": chain, "products": products,
             "lastSuccessfulRun": {"status": "success"} if done else None}
            for chain, (products, done) in chains.items()]
        self.addCleanup(lambda: setattr(grocery_api, "database_summary", real_summary))
        self.addCleanup(lambda: setattr(grocery_api, "provider_status", real_status))

    def test_imports_every_chain_when_the_database_is_empty(self):
        """An empty chain is an empty chain - production ran for hours with
        Willys full and Hemköp/City Gross at zero, waiting for the wall clock
        to reach their nightly slots."""
        self._summary(0, finished=False)
        self.assertTrue(self.scheduler.bootstrap_if_empty())
        self.assertEqual(self.started[0], "Willys")
        self.assertEqual(sorted(self.started),
                         sorted(scheduler_module.SCHEDULABLE_CHAINS))

    def test_does_nothing_when_the_catalogue_is_complete(self):
        """An ordinary deploy must not re-import a catalogue that is there."""
        self._summary(10842, finished=True)
        self.assertFalse(self.scheduler.bootstrap_if_empty())
        self.assertEqual(self.started, [])

    def test_resumes_a_catalogue_that_never_finished_importing(self):
        """Production sat on 2 538 of ~11 000 products because a deploy killed
        the import partway and the old guard ("only when totally empty")
        refused to resume - leaving a quarter of a catalogue until the next
        nightly run."""
        self._summary(2538, finished=True,
                      chains={"Willys": (2538, False),
                              "Hemköp": (9000, True),
                              "City Gross": (8000, True)})
        self.assertTrue(self.scheduler.bootstrap_if_empty())
        self.assertEqual(self.started, ["Willys"])

    def test_a_finished_catalogue_is_not_re_imported_on_every_restart(self):
        """The resume rule must not become a loop: once one run finishes, no
        number of restarts may start another."""
        self._summary(10842, finished=True)
        for _ in range(5):
            self.scheduler.bootstrap_if_empty()
        self.assertEqual(self.started, [])

    def test_does_nothing_when_the_scheduler_is_disabled(self):
        """A local dev run must not start fetching from a chain on its own."""
        self._summary(0)
        self.scheduler.enabled = False
        self.assertFalse(self.scheduler.bootstrap_if_empty())
        self.assertEqual(self.started, [])

    def test_chains_import_one_at_a_time_not_in_parallel(self):
        """Three category walks at once, on a 512 MB instance, right as it
        boots, is how the last OOM happened. Each started import is waited
        out before the next chain begins."""
        self._summary(0, finished=False)
        running = {"count": 0}
        real_status = scheduler_module.importer.status
        def fake_status():
            # Report "running" exactly once per import, so the loop has to
            # take its waiting branch every time.
            running["count"] += 1
            return {"running": running["count"] % 2 == 1}
        scheduler_module.importer.status = fake_status
        self.addCleanup(lambda: setattr(scheduler_module.importer, "status", real_status))
        real_sleep = scheduler_module.time.sleep
        scheduler_module.time.sleep = lambda seconds: None
        self.addCleanup(lambda: setattr(scheduler_module.time, "sleep", real_sleep))

        self.scheduler.bootstrap_if_empty()
        self.assertEqual(len(self.started), len(scheduler_module.SCHEDULABLE_CHAINS))

    def test_a_full_chain_is_left_alone_while_empty_chains_import(self):
        """Bootstrap must not re-walk Willys just because Hemköp is empty -
        freshness is the nightly job's job."""
        self._summary(10842, finished=True,
                      chains={"Willys": (10842, True),
                              "Hemköp": (0, False),
                              "City Gross": (0, False)})
        self.assertTrue(self.scheduler.bootstrap_if_empty())
        self.assertNotIn("Willys", self.started)
        self.assertEqual(sorted(self.started), ["City Gross", "Hemköp"])

    def test_a_failure_to_read_the_database_is_not_fatal(self):
        from services.grocery import api as grocery_api
        real = grocery_api.database_summary
        def boom():
            raise OSError("disken svarar inte")
        grocery_api.database_summary = boom
        self.addCleanup(lambda: setattr(grocery_api, "database_summary", real))
        self.assertFalse(self.scheduler.bootstrap_if_empty())
        self.assertEqual(self.started, [])


if __name__ == "__main__":
    unittest.main()
