# -*- coding: utf-8 -*-
"""Tests for the nightly import scheduler.

The important behaviour is not "does a timer fire" - it is WHICH CHAINS ARE
ALLOWED TO RUN. Automatic collection is a claim that repeated unattended
fetching works and is welcome. Willys, Hemköp och City Gross har förtjänat
det mot sina egna sidor. ICA och Coop hämtas ALDRIG därifrån - deras rader i
schemat gäller Primats betal-API, som aldrig rör kedjornas servrar - och utan
PRIMAT_API_KEY hoppas de över helt, för då skulle importeraren falla tillbaka
på den direkta skrap-providern. Lidl står kvar utanför: det finns inga
per-produkt-priser att hämta. A config typo must not be able to start
hammering any chain that said no.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.grocery import scheduler as scheduler_module  # noqa: E402
from services.grocery.scheduler import (  # noqa: E402
    DEFAULT_SCHEDULE, SCHEDULABLE_CHAINS, GroceryScheduler, next_run_at, parse_schedule,
)


class MinnesKV:
    """KV-store i minnet med samma yta som KeyValueCacheStore.

    Schemaläggarens dygnsmarkeringar ligger numera i databasen, och två
    tester som delar markeringar skulle dölja precis det de prövar - det
    andra testet skulle se det första som "kedjan har redan kört i dag"."""

    def __init__(self):
        self.data = {}

    def get(self, namespace, key):
        return self.data.get((namespace, key), (None, None))

    def set(self, namespace, key, value, updated_at=None):
        self.data[(namespace, key)] = (value, updated_at or 0.0)


def schemalaggare(schedule, kv=None, kort_i_dag=False):
    """En schemaläggare isolerad från den riktiga databasen: egna
    dygnsmarkeringar, och körningshistoriken svarar det testet ber om."""
    sched = GroceryScheduler(schedule, kv=kv if kv is not None else MinnesKV())
    sched._chain_already_started_today = lambda chain, day_start: kort_i_dag
    return sched


class SchedulableChainsTest(unittest.TestCase):
    def test_only_the_verified_chains_are_schedulable(self):
        """ICA, Coop och Lidl kom till när Primat-vägen fanns: den rör aldrig
        kedjornas egna servrar, så WAF-skälet gäller inte den.

        Lidl stod utanför till 2026-09-10 med motiveringen "det finns inga
        per-produkt-priser att hämta". Det gäller lidl.se - Primat har en
        Lidl-feed, precis som för de två andra. Att den kan vara för liten
        för en hel matkorg är ett TÄCKNINGSPROBLEM, och det löses av
        jämförelsegrinden, inte av att aldrig hämta."""
        self.assertEqual(set(SCHEDULABLE_CHAINS),
                         {"Willys", "Hemköp", "City Gross", "ICA", "Coop", "Lidl"})

    def test_a_chain_that_said_no_can_never_be_scheduled_by_config(self):
        """Allow-listans kvarvarande poäng: ett stavfel i en miljövariabel
        får inte sätta en kedja som sagt nej på en nattlig timer. Att lägga
        till en kedja ska kräva en kodändring."""
        schedule = parse_schedule("Matpriskollen=02:00")
        self.assertNotIn("Matpriskollen", schedule)
        # Falls back to the safe default rather than to an empty schedule
        # that would silently stop all imports.
        self.assertEqual(schedule, DEFAULT_SCHEDULE)

    def test_importing_lidl_is_not_releasing_it(self):
        """Det skydd som verkligen betydde något när Lidl stod utanför
        schemat: kunden får aldrig se en Lidl-total som inte bär. Det ligger
        i RELEASED_CHAINS och täckningsgrinden - inte i att aldrig hämta."""
        from services.grocery.api import RELEASED_CHAINS
        self.assertIn("Lidl", SCHEDULABLE_CHAINS)
        self.assertNotIn("Lidl", RELEASED_CHAINS)

    def test_primat_chains_are_skipped_without_the_key(self):
        """Utan PRIMAT_API_KEY väljer importer._provider_for() den DIREKTA
        skrap-providern för ICA - exakt den upprepade hämtningen som triggar
        ICAs WAF. Spärren är det som gör schemaposterna ofarliga."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PRIMAT_API_KEY", None)
            self.assertFalse(scheduler_module._får_köras("ICA"))
            self.assertFalse(scheduler_module._får_köras("Coop"))
            self.assertTrue(scheduler_module._får_köras("Willys"))
        with mock.patch.dict(os.environ, {"PRIMAT_API_KEY": "x"}):
            self.assertTrue(scheduler_module._får_köras("ICA"))
            self.assertTrue(scheduler_module._får_köras("Coop"))

    def test_every_chain_runs_daily(self):
        """Alla fem kedjor ska uppdateras varje dygn - inget veckoschema."""
        for chain, when in DEFAULT_SCHEDULE.items():
            self.assertRegex(when, r"^\d{2}:\d{2}$", f"{chain}: {when!r} är inte HH:MM")

    def test_primat_chains_run_after_the_daily_quota_reset(self):
        """Primats dygnskvot nollställs midnatt UTC = 02:00 svensk sommartid.
        Ett jobb före det faller på gårdagens förbrukning - verifierat i
        produktion 2026-09-02 med 429 daily_row_budget_exceeded."""
        for chain in ("ICA", "Coop"):
            timme = int(DEFAULT_SCHEDULE[chain].split(":")[0])
            self.assertGreaterEqual(timme, 2, f"{chain} startar före kvotresetten")

    def test_the_ops_check_runs_after_every_import(self):
        """Driftkollen ska bedöma NATTENS resultat. Ligger den före sista
        importen larmar den på gårdagens läge, vilket är värre än inget larm
        - man lär sig ignorera det."""
        kollen = scheduler_module.OPS_ALERT_AT
        for chain, when in DEFAULT_SCHEDULE.items():
            self.assertLess(when, kollen, f"{chain} kör {when}, efter driftkollen {kollen}")

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
        # Varken ICA, Coop eller Lidl duger som exempel längre - alla tre
        # har ett Primat-schema. En kedja vi inte hämtar alls får svara.
        self.assertIsNone(next_run_at("Matpriskollen", DEFAULT_SCHEDULE))


class BootstrapFortsatterEfterEttFel(unittest.TestCase):
    """En kedja som kastar får inte ta de övriga med sig.

    Sett i produktion 2026-09-10: Coop hämtade 12 079 varor, sedan hände
    ingenting med ICA och Lidl. Metoden kör på en daemon-tråd utan handler,
    så undantaget dödade tråden tyst - inget fel i loggen, ingen körning."""

    def test_ett_undantag_stoppar_inte_resten(self):
        from unittest import mock
        startade = []

        def start(chain, *a, **kw):
            startade.append(chain)
            if chain == "Coop":
                raise RuntimeError("Primat svarade inte")
            return {"started": True}

        sched = scheduler_module.GroceryScheduler({"Coop": "01:00", "ICA": "02:00",
                                                   "Lidl": "03:00"})
        sched.enabled = True   # enabled läses ur miljön i __init__
        tomma = [{"chain": c, "products": 0, "lastSuccessfulRun": None}
                 for c in ("Coop", "ICA", "Lidl")]
        with mock.patch.dict(os.environ, {"PRIMAT_API_KEY": "x"}), \
             mock.patch.object(scheduler_module.importer, "start", side_effect=start), \
             mock.patch.object(scheduler_module.importer, "status", return_value={"running": False}), \
             mock.patch("services.grocery.api.database_summary", return_value={"chains": []}), \
             mock.patch("services.grocery.api.provider_status", return_value=tomma):
            sched.bootstrap_if_empty()
        # Bootstrapen går över SCHEDULABLE_CHAINS, inte bara de tre här -
        # det som prövas är att de EFTER den som kastade ändå startades.
        for kedja in ("Coop", "ICA", "Lidl"):
            self.assertIn(kedja, startade, f"{kedja} startades aldrig")
        self.assertLess(startade.index("Coop"), startade.index("ICA"),
                        "ICA ska ha försökts efter Coop")
        self.assertLess(startade.index("ICA"), startade.index("Lidl"))


class TickTest(unittest.TestCase):
    def setUp(self):
        self.started = []
        self._real_start = scheduler_module.importer.start
        scheduler_module.importer.start = lambda chain, **kwargs: (
            self.started.append(chain) or {"started": True, "chain": chain})
        self.addCleanup(lambda: setattr(scheduler_module.importer, "start", self._real_start))
        self.scheduler = schemalaggare({"Willys": "02:00", "Hemköp": "03:00"})

    def test_fires_the_chain_whose_time_it_is(self):
        self.scheduler._tick(datetime(2026, 8, 31, 2, 0))
        self.assertEqual(self.started, ["Willys"])

    def test_fires_nothing_before_its_time(self):
        """Ett klockslag som inte passerat är inte ett missat jobb. (Efter
        klockslaget gäller motsatsen: se MissadKorningTasIgen - en tick 02:30
        TAR igen 02:00-jobbet i stället för att skjuta det ett dygn.)"""
        self.scheduler._tick(datetime(2026, 8, 31, 1, 30))
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
        """A blank next-run for a blocked chain would read as an oversight.
        Bara Lidl är kvar utan jobb: ICA och Coop går via Primat numera."""
        status = self.scheduler.status()
        # Ingen kedja står utan jobb längre - Lidl fick sitt 2026-09-10.
        # Raden finns kvar i svaret så adminvyn kan säga "inga" i stället
        # för att visa en tom yta som läses som ett fel.
        self.assertEqual(status["notScheduled"], {})
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
        # Med nyckeln får ÄVEN Primat-kedjorna starta, så testet fortsätter
        # mäta det det menar: varje schemalagd kedja bootstrappas. Fallet
        # utan nyckel täcks av test_primat_chains_are_skipped_without_the_key.
        with mock.patch.dict(os.environ, {"PRIMAT_API_KEY": "x"}):
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

        with mock.patch.dict(os.environ, {"PRIMAT_API_KEY": "x"}):
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


class DaylightSavingAndLateTicks(unittest.TestCase):
    """Exakt minutmatchning missade 02:00-jobbet natten klockan hoppar från
    02:00 till 03:00, och varje tick som blev försenad av last."""

    def setUp(self):
        self.started = []
        self.scheduler = schemalaggare({"Willys": "02:00"})
        self._original = scheduler_module.importer.start
        scheduler_module.importer.start = lambda chain: (self.started.append(chain) or {"started": True, "chain": chain})

    def tearDown(self):
        scheduler_module.importer.start = self._original

    def test_spring_forward_night_still_runs_the_job(self):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Stockholm")
        # 2026-03-29: klockan 02:00 CET blir 03:00 CEST. Första ticken efter
        # hoppet är 03:00 - jobbet ska gå då, inte utebli.
        self.scheduler._tick(datetime(2026, 3, 29, 1, 59, tzinfo=tz))
        self.assertEqual(self.started, [])
        self.scheduler._tick(datetime(2026, 3, 29, 3, 0, tzinfo=tz))
        self.assertEqual(self.started, ["Willys"])
        self.scheduler._tick(datetime(2026, 3, 29, 3, 1, tzinfo=tz))
        self.assertEqual(self.started, ["Willys"], "en gång per dygn")

    def test_en_sen_tick_kor_jobbet_oavsett_hur_sen_den_ar(self):
        """Fönstret på fem minuter är borta (D3). Det var ett tak på hur sent
        ett jobb fick gå, och en deploy 02:03-02:05 räckte för att slå i det
        - då uteblev Willys hela natten. Dygnsmarkeringen är gränsen nu: en
        tick klockan 02:30 tar igen jobbet som skulle gått 02:00."""
        self.scheduler._tick(datetime(2026, 8, 31, 2, 3))
        self.assertEqual(self.started, ["Willys"])
        self.scheduler._tick(datetime(2026, 9, 1, 2, 30))
        self.assertEqual(self.started, ["Willys", "Willys"])


class MissadKorningTasIgen(unittest.TestCase):
    """D3. Dygnets körning ska konsumeras av en import som FAKTISKT startade
    - ingenting annat.

    Tre fel satt i samma loop. `_last_fired[chain]` sattes FÖRE
    `importer.start()`, så en kedja som fick "already_running" räknades som
    körd fast ingenting hämtats. Markeringen låg bara i minnet, så en omstart
    mitt i startfönstret kunde köra samma jobb två gånger samma natt. Och
    fönstret var fem minuter brett, så en deploy 02:03-02:05 tog Willys hela
    den natten - vilket syntes först som ett stale-larm efter 36 timmar."""

    def setUp(self):
        self.started = []
        self.svar = {"started": True}
        self._real_start = scheduler_module.importer.start
        scheduler_module.importer.start = lambda chain, **kw: (
            self.started.append(chain) or dict(self.svar, chain=chain))
        self.addCleanup(lambda: setattr(scheduler_module.importer, "start", self._real_start))

    def test_already_running_konsumerar_inte_dygnets_korning(self):
        """Acceptanskriteriet. En Willys-import som drog över till 03:00 tog
        med sig Hemköp för hela dygnet: Hemköp markerades som körd, fick
        "already_running", och nästa försök låg ett dygn bort."""
        sched = schemalaggare({"Hemköp": "03:00"})
        self.svar = {"started": False, "reason": "already_running"}
        sched._tick(datetime(2026, 8, 31, 3, 0))
        self.assertEqual(self.started, ["Hemköp"], "försöket ska ha gjorts")

        # Den pågående importen blir klar. Nästa tick ska ta jobbet, inte
        # vänta till i morgon.
        self.svar = {"started": True}
        sched._tick(datetime(2026, 8, 31, 3, 1))
        self.assertEqual(self.started, ["Hemköp", "Hemköp"])

        # ... och när det väl startade är dygnets körning förbrukad.
        sched._tick(datetime(2026, 8, 31, 3, 2))
        self.assertEqual(self.started, ["Hemköp", "Hemköp"])

    def test_ett_missat_klockslag_tas_igen_samma_dygn(self):
        """En deploy under startminuten ska kosta minuter, inte ett dygn."""
        sched = schemalaggare({"Willys": "02:00"})
        # Processen var nere 02:00-02:04 och första ticken kommer 02:05.
        sched._tick(datetime(2026, 8, 31, 2, 5))
        self.assertEqual(self.started, ["Willys"])

    def test_markeringen_overlever_en_omstart(self):
        """Markeringen låg i minnet: en omstart 02:02 nollställde den och
        samma jobb startade en gång till samma natt - dubbel hämtning mot
        kedjan, och för Primat-kedjorna dubbel kvot."""
        kv = MinnesKV()
        fore = schemalaggare({"Willys": "02:00"}, kv=kv)
        fore._tick(datetime(2026, 8, 31, 2, 0))
        self.assertEqual(self.started, ["Willys"])

        efter = schemalaggare({"Willys": "02:00"}, kv=kv)   # ny process, tomt minne
        efter._tick(datetime(2026, 8, 31, 2, 2))
        self.assertEqual(self.started, ["Willys"], "samma natt, samma jobb, en gång")

        efter._tick(datetime(2026, 9, 1, 2, 0))
        self.assertEqual(self.started, ["Willys", "Willys"], "nästa dygn är ett nytt jobb")

    def test_en_kedja_som_redan_kort_i_dag_startas_inte_om(self):
        """Markeringen är inte den enda sanningen. Första gången koden
        deployas finns inga markeringar alls, och en deploy mitt på dagen
        skulle då starta varje kedja vars klockslag passerat. Databasens
        körningshistorik får säga ifrån."""
        sched = schemalaggare({"Willys": "02:00"}, kort_i_dag=True)
        sched._tick(datetime(2026, 8, 31, 14, 0))
        self.assertEqual(self.started, [])

    def test_en_olasbar_historik_startar_ingen_import(self):
        """"Vet inte" får inte betyda "kör". En dubblerad Primat-körning
        kostar kvot som inte kommer tillbaka; ett uteblivet nattjobb syns i
        driftkollen."""
        sched = GroceryScheduler({"Willys": "02:00"}, kv=MinnesKV())
        with mock.patch("services.grocery.api.open_store", side_effect=OSError("disken")):
            sched._tick(datetime(2026, 8, 31, 2, 0))
        self.assertEqual(self.started, [])

    def test_en_kedja_utan_nyckel_markeras_inte_som_kord(self):
        """Att hoppa över ICA för att PRIMAT_API_KEY saknas är inte en
        körning. Kommer nyckeln på plats klockan 05:31 ska jobbet gå."""
        sched = schemalaggare({"ICA": "05:30"})
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PRIMAT_API_KEY", None)
            sched._tick(datetime(2026, 8, 31, 5, 30))
        self.assertEqual(self.started, [])
        with mock.patch.dict(os.environ, {"PRIMAT_API_KEY": "x"}):
            sched._tick(datetime(2026, 8, 31, 5, 31))
        self.assertEqual(self.started, ["ICA"])

    def test_driftkollen_tas_ocksa_igen(self):
        """Exakt minutmatchning gjorde att en tick som blev försenad av last
        hoppade över hela driftkollen den dagen - larmen tystnade utan att
        någon incident var löst."""
        sched = schemalaggare({})
        startade = []
        for namn in ("_sync_register_if_missing", "activate_platform",
                     "_run_dabas_enrichment", "_run_ops_alerts"):
            setattr(sched, namn, (lambda n: lambda *a: startade.append(n))(namn))
        # Trådarna körs på plats, så testet mäter VAD som startades och inte
        # hur snabbt en daemon-tråd hinner.
        with mock.patch.object(scheduler_module.threading, "Thread",
                               lambda target, args=(), name=None, daemon=None:
                               mock.Mock(start=lambda: target(*args))):
            sched._tick(datetime(2026, 8, 31, 7, 44))   # 14 minuter efter 07:30
            self.assertIn("_run_ops_alerts", startade)
            startade.clear()
            sched._tick(datetime(2026, 8, 31, 7, 45))
            self.assertEqual(startade, [], "en gång per dygn")


if __name__ == "__main__":
    unittest.main()


class CrashedImportEndsItsRun(unittest.TestCase):
    """En serverimport som kraschar oväntat får aldrig lämna sin körning som
    evig 'running' - då visar adminpanelen en fantomimport och lastRun löses
    aldrig."""

    def setUp(self):
        # Importern öppnar databasen via grocery_api.open_store(), som läser
        # DB_PATH vid anropet. Utan omdirigering lämnar varje testkörning en
        # 'failed'-rad i backend/data/grocery.db (id 30-35 sågs 2026-09-02).
        # Tester får aldrig skriva i produktionsdatabasen - samma mönster som
        # test_national_stores och test_two_tier_pricing.
        from services.grocery import api as grocery_api
        self.grocery_api = grocery_api
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "grocery.db"
        self._real = grocery_api.DB_PATH
        grocery_api.DB_PATH = self.db_path
        self.addCleanup(lambda: setattr(grocery_api, "DB_PATH", self._real))
        grocery_api.clear_cache()
        self.addCleanup(grocery_api.clear_cache)

    def test_unexpected_crash_marks_the_run_failed(self):
        from services.grocery import importer
        grocery_api = self.grocery_api

        class ExplodingProvider:
            name = "Willys"
            def get_stores(self):
                raise RuntimeError("nätverket exploderade")

        original_provider = importer._provider_for
        importer._provider_for = lambda chain: ExplodingProvider()
        try:
            importer.start("Willys")
            for _ in range(200):
                if not importer.status().get("running"):
                    break
                time.sleep(0.05)
            # Felvägen sätter running=False innan db.close() hunnit köras.
            # Vänta in importtråden så att den inte håller temp-databasen
            # öppen när katalogen städas (Windows vägrar ta bort öppna filer).
            for thread in threading.enumerate():
                if thread.name == "grocery-import-Willys":
                    thread.join(timeout=10)
            self.assertTrue(self.db_path.exists(),
                            "körningen skulle ha landat i temp-databasen")
            store = grocery_api.open_store()
            try:
                run = store.connection.execute(
                    "SELECT status, error_message FROM grocery_collector_runs "
                    "ORDER BY id DESC LIMIT 1").fetchone()
            finally:
                store.close()
            self.assertIsNotNone(run)
            self.assertEqual(run["status"], "failed")
            self.assertIn("exploderade", run["error_message"])
            self.assertFalse(importer.status().get("running"))
        finally:
            importer._provider_for = original_provider
