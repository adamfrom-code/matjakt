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

  ICA         Never fetched from ICA's own pages: repeated fetching trips an
              AWS WAF challenge, and we do not attempt to solve or evade it.
              It runs DAILY via PRIMAT'S PAID API instead - a licensed third
              party that never touches ICA's servers, so the reason for the
              ban does not apply to that route.
  Coop        Same: Coop's own portal is locked to their internal Azure AD
              and we do not authenticate with someone else's key. Runs daily
              via Primat.
  Lidl        runs daily via Primat since 2026-09-10. Lidl Sweden publishes
              no per-product prices at all, so their own site is not a route
              - Primat is. The feed is national and has been described as
              ~200-400 rows, which would be too thin for a whole basket, but
              nobody has run an import and counted. Importing it is how that
              gets measured; RELEASED_CHAINS keeps it invisible to customers
              until the number is known and the quality gate passed.

PRIMAT_ONLY_CHAINS holds the line the WAF ban was really about: without
PRIMAT_API_KEY those two are skipped entirely, because importer._provider_for
would otherwise fall back to the direct scraper for ICA - the exact repeated
fetching this module refuses to do.

QUOTA. Här stod att koden inte hade något eget radtak och att dygnsbudgetens
storlek därför inte fanns i koden. Bägge påståendena var fel.
`PRIMAT_MAX_ROWS_PER_RUN` i providers/primat.py var - och är - ett radtak,
och det stod på 40 000. Tre kedjor i schemat gånger 40 000 är 120 000 rader
mot en dygnskvot på 100 000: taket låg ÖVER kvoten, alltså kunde det aldrig
skydda något. Natten 2026-09-11 blev utfallet

    ICA=0/0p [failed]  Coop=12079/12050p [ready_for_release]  Lidl=0/0p [limited]

Coop hann först och tog det som fanns kvar; ICA och Lidl kom aldrig förbi
429.

Nu gäller tre saker samtidigt:

  * varje förbrukad rad BOKFÖRS per kvotdygn (services/grocery/quota.py),
    medan körningen pågår - inte efteråt, eftersom det är körningar som inte
    blir klara som kostat rader utan att lämna spår;
  * schemaläggaren och bootstrapen frågar bokföringen FÖRE start och hoppar
    över kedjan när det inte finns utrymme, i stället för att betala för ett
    429;
  * en körnings tak är dygnsbudgeten delad på de tre Primat-kedjorna, klippt
    mot det som återstår av dygnet.

Budgetens storlek är 100 000 rader på App-nivån, bekräftat ur Primats eget
429-svar 2026-09-10, och ändras utan deploy via PRIMAT_DAILY_ROW_BUDGET. Så
fort driftkollen läst ett tak ur Primats GET /me är DET talet budgeten -
vårt eget står kvar bara som utgångsläge. Driftkollen varnar fortfarande vid
85 % av det Primat själv rapporterar, och säger "Ej tillgängligt" hellre än
ett antaget tal när svaret inte går att läsa.

Ett tak som ändå nås är inte farligt: providern slutar hämta, behåller det
den fått och märker körningen "blocked", vilket publish.py slår ihop i
stället för att förkasta - täckningen byggs upp över flera nätter i stället
för att en natt misslyckas helt.

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
from datetime import timezone, datetime, timedelta

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
    # ICA och Coop hämtas ALDRIG från kedjornas egna sidor - se modulens
    # docstring, den spärren står kvar. De här raderna gäller Primats
    # betal-API, en licensierad tredjepartskälla som aldrig rör ICAs WAF
    # eller Coops Azure AD. PRIMAT_ONLY_CHAINS ser till att de inte kan
    # starta på någon annan väg.
    #
    # Dagligen, staggrat efter de tre andra. Kvoten nollställs midnatt UTC =
    # 02:00 svensk sommartid, så båda ligger efter den. Importeraren kör en
    # kedja i taget, så tiderna är startfönster - inte parallella jobb.
    #
    # KVOT: ICAs katalog är ensam ~11 000 rader. Hur många som ryms per dygn
    # avgörs av kontots nivå, som läses ur Primats /me - inte av något tal
    # här. Slår en kedja i taket behålls det den hann hämta.
    # Det är ofarligt - providern slutar hämta, behåller det den fått och
    # märker körningen "blocked", vilket publiceringen slår ihop i stället
    # för att förkasta. Driftkollen varnar vid 85 % av den kvot Primat
    # själv rapporterar, så taket syns innan det slår i.
    "ICA": "05:30",
    "Coop": "06:30",
    # Lidl gick redan att importera - PrimatProvider stödjer kedjan och
    # importer.py bär ett butiks-id - men den saknades i schemat, så den
    # hämtades aldrig. Sist i ordningen därför att dess feed är den minsta:
    # slår kvoten i taket är Lidl den kedja som gör minst skada att missa.
    #
    # ATT IMPORTERA ÄR INTE ATT SLÄPPA. RELEASED_CHAINS är orörd, så Lidl
    # syns fortfarande inte för kunder. Poängen med att hämta den är att
    # kunna MÄTA hur stor feeden faktiskt är - PROVIDER_STATUS påstår
    # "~200-400 varor" utan att någon kört en import och räknat.
    "Lidl": "07:00",
}

# Kedjor som BARA får importeras via Primat. Utan nyckeln väljer
# importer._provider_for() den direkta skrap-providern för ICA, och ett
# nattjobb får aldrig hamna där - det är precis den upprepade hämtningen som
# triggar ICAs WAF. Saknas nyckeln hoppas de över, tyst och avsiktligt.
# Lidl hör hit av samma skäl: utan nyckel finns ingen laglig väg till Lidls
# priser alls, och _provider_for kastar. Stod kedjan inte här skulle den
# schemaläggas ändå, falla varje natt och skicka ett driftlarm om saken -
# ett larm om något vi själva valt att inte konfigurera.
PRIMAT_ONLY_CHAINS = frozenset({"ICA", "Coop", "Lidl"})


def _får_köras(chain: str) -> bool:
    """False för en Primat-kedja när nyckeln saknas. Kollas vid körning, inte
    vid import av modulen: miljön kan ha fått nyckeln efter starten, och en
    tom miljö i tester ska inte kunna schemalägga ICA mot skrap-providern."""
    if chain in PRIMAT_ONLY_CHAINS and not os.environ.get("PRIMAT_API_KEY"):
        logger.info("Hoppar över nattjobb för %s: PRIMAT_API_KEY saknas, och "
                    "den här kedjan hämtas aldrig direkt från butikens sidor", chain)
        return False
    return True

# Allow-listan är fortfarande poängen: ett stavfel i en miljövariabel får
# inte sätta en kedja som sagt nej på en nattlig timer. Den härleds ur
# DEFAULT_SCHEDULE, så att lägga till en kedja är ett medvetet kodbeslut -
# aldrig en konfigurationsrad.
#
# Lidl kom med 2026-09-10 av samma skäl som ICA och Coop: Primat är en
# licensierad tredjepart som aldrig rör kedjans egna servrar. Skyddet som
# spelade roll - att en Lidl-total aldrig får fejkas fram - ligger inte här
# utan i RELEASED_CHAINS och täckningsgrinden, och står kvar.
SCHEDULABLE_CHAINS = frozenset(DEFAULT_SCHEDULE)

CHECK_INTERVAL_SECONDS = 60

# Namnrymden i KV-storen där dygnsmarkeringarna ligger ("kördes jobbet X i
# dag?"). Egen namnrymd, inte "cache": det här är driftfakta, och en post som
# försvinner betyder att ett nattjobb kan starta en gång till.
SCHEDULE_STATE_NAMESPACE = "grocery_schedule"


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

# Driftkollen: EFTER nattens alla importer (Willys 02 ... Coop 06:30), så
# larmet bedömer nattens resultat och inte gårdagens. Skickar bara när något
# faktiskt är fel, och som mest ett mejl per incident - se alerts.py.
# Efter sista importen, inte före. Låg kollen kvar på 07:00 när Lidl fick
# sitt jobb där hade nattens sista körning aldrig bedömts av den - ett test
# fångade det. Halvtimmen efter Lidl räcker: feeden är den minsta av alla.
OPS_ALERT_AT = "07:30"

# Which chain fills an empty database first. Willys: the largest verified
# catalogue (10 842 products, 100 % with category), plain HTTP with no
# browser, and the chain most likely to be near any given user.
BOOTSTRAP_CHAIN = "Willys"


def parse_schedule(raw: str | None) -> dict:
    """Reads MATJAKT_GROCERY_SCHEDULE, e.g. "Willys=02:00,Hemköp=03:30".

    Veckodagar skrivs med SNEDSTRECK här - "ICA=Mon/Wed/Fri 05:30" - eftersom
    komma redan separerar posterna i den här strängen.

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

    def __init__(self, schedule: dict | None = None, kv=None):
        self.schedule = schedule if schedule is not None else parse_schedule(
            os.environ.get("MATJAKT_GROCERY_SCHEDULE"))
        self.enabled = _truthy(os.environ.get("MATJAKT_GROCERY_SCHEDULE_ENABLED", "0"))
        self._thread = None
        self._stop = threading.Event()
        # The minute a chain last fired, so a job cannot run twice inside the
        # same minute if the loop wakes up more than once in it. För kedjorna
        # är det numera bara en RESERV: dygnsmarkeringen ligger i KV-storen,
        # se _last_run_day.
        self._last_fired = {}
        self._kv_store = kv

    # ------------------------------------------------- dygnsmarkeringen (D3)
    #
    # Markeringen låg tidigare BARA i minnet, och sattes dessutom FÖRE
    # importer.start(). Tre saker följde av det:
    #
    #   en kedja som fick "already_running" markerades som körd ändå, och
    #   dygnets körning var därmed förbrukad utan att någonting hämtats;
    #
    #   en omstart mitt i startfönstret nollställde minnet, så samma jobb
    #   kunde starta två gånger samma natt;
    #
    #   och fönstret var fem minuter brett, så en deploy 02:03-02:05 tog
    #   Willys hela den natten. Det syntes först som ett stale-larm efter
    #   36 timmar - om larmen hade haft en mottagare (D1).
    #
    # Nu: markera FÖRST när en import faktiskt startade, skriv markeringen
    # till databasen, och kör så fort klockslaget passerat om jobbet inte
    # kört i dag. Ingen övre gräns behövs - dygnsmarkeringen ÄR gränsen.
    def _kv(self):
        """KV-storen för dygnsmarkeringarna, eller None när den inte går att
        nå. Lat och guardad med flit: schemaläggaren instansieras även i
        miljöer där api_server inte är importerbar (tester, skript), och en
        oåtkomlig store får aldrig stoppa nattjobben - då gäller minnet,
        precis som förut."""
        if self._kv_store is None:
            try:
                from api_server import KV_CACHE
                self._kv_store = KV_CACHE
            except Exception:
                logger.info("Schemamarkeringarna kunde inte persisteras - "
                            "kör vidare mot minnet")
                return None
        return self._kv_store

    def _last_run_day(self, key: str) -> str | None:
        """Dygnet jobbet senast hanterades, "YYYY-MM-DD", eller None."""
        kv = self._kv()
        if kv is not None:
            try:
                värde, _ = kv.get(SCHEDULE_STATE_NAMESPACE, key)
            except Exception:
                logger.exception("Kunde inte läsa schemamarkeringen för %s", key)
                värde = None
            if värde:
                return str(värde)
        return self._last_fired.get(key)

    def _mark_run(self, key: str, day: str):
        """Markerar jobbet som hanterat i dag. Minnet skrivs alltid, så en
        databas som inte svarar degraderar till gamla beteendet i stället
        för att låta samma jobb starta varje minut."""
        self._last_fired[key] = day
        kv = self._kv()
        if kv is None:
            return
        try:
            kv.set(SCHEDULE_STATE_NAMESPACE, key, day)
        except Exception:
            logger.exception("Kunde inte spara schemamarkeringen för %s", key)

    def _is_due(self, now, when: str, key: str, day_stamp: str) -> bool:
        """"Klockslaget har passerat i dag och jobbet har inte kört i dag."

        Inget fönster. Ett jobb som missades för att processen startade om
        klockan 02:04 går klockan 02:05 i stället för att utebli till nästa
        natt.

        `when` får bära ett veckodagsprefix ("Sun 01:00"); stämmer inte dagen
        är jobbet inte aktuellt alls."""
        weekday, _, klockslag = str(when or "").rpartition(" ")
        if weekday and now.strftime("%a") != weekday:
            return False
        due = _due_today(now, klockslag)
        if due is None:
            return False
        # I UTC, uttryckligen: två datetime med SAMMA tzinfo jämförs naivt i
        # Python, och då syns inte sommartidshoppet alls.
        late = ((now.astimezone(timezone.utc) - due.astimezone(timezone.utc))
                if now.tzinfo else (now - due))
        if late < timedelta(0):
            return False
        return self._last_run_day(key) != day_stamp

    def _chain_already_started_today(self, chain: str, day_start: float) -> bool:
        """Har kedjan redan en körning som STARTADE i dag?

        Markeringen i KV-storen räcker inte ensam, av två skäl. Första gången
        den här koden deployas finns inga markeringar alls, och då skulle
        varje kedja vars klockslag passerat starta direkt - en deploy klockan
        tolv hade dragit igång sex importer och bränt Primat-kvoten på en
        gång. Och en markering som inte gick att skriva (databasen upptagen)
        skulle ge samma sak vid nästa omstart.

        Körningsraden i databasen är det som faktiskt hände, så den får
        avgöra när markeringen saknas - och markeringen skrivs då så att
        frågan ställs en gång per kedja och dygn, inte varje minut.

        Att en MANUELL import samma dygn också räknas är avsiktligt: kedjan
        har färsk data och nattjobbet skulle bara kosta kvot om igen."""
        try:
            from . import api as grocery_api
            store = grocery_api.open_store()
            try:
                rad = store.connection.execute(
                    "SELECT 1 FROM grocery_collector_runs "
                    "WHERE chain = ? AND started_at >= ? LIMIT 1",
                    (chain, day_start)).fetchone()
            finally:
                store.close()
            return rad is not None
        except Exception:
            # Går databasen inte att läsa vet vi ingenting - och "vet inte"
            # får inte betyda "kör". Ett uteblivet nattjobb syns i
            # driftkollen; en dubblerad kostar kvot vi inte får tillbaka.
            logger.exception("Kunde inte läsa körningshistoriken för %s", chain)
            return True

    def _primat_quota_allows(self, chain: str) -> bool:
        """False när dygnets radkvot inte räcker för en katalogimport.

        Gäller bara Primat-kedjorna: Willys, Hemköp och City Gross hämtas
        från kedjornas egna sidor och kostar ingen kvot alls.

        D9: "bara Primat-kedjorna" är inte längre en fast lista. Flyttas
        Willys eller Hemköp till Primat-reservvägen (MATJAKT_PRIMAT_CHAINS,
        se importer.py) kostar de plötsligt kvot som alla andra, och då ska
        spärren gälla dem också - annars vore reservvägen ett sätt att gå
        förbi den enda kontroll som står mellan oss och ett 429.

        Kontrollen ligger FÖRE start med flit. `_rows_spent` fanns i
        providern men bara inom en körning, i minnet, och ingen frågade den
        innan nästa startade. Natten 2026-09-11 blev utfallet
        ICA=0/0p, Coop=12 079, Lidl=0/0p: Coop hann först och tog det som
        fanns, de andra två fick 429 och lämnade varsin blocked-markering
        utan en enda rad."""
        if chain not in PRIMAT_ONLY_CHAINS and chain not in importer.primat_fallback_stores():
            return True
        from . import quota
        ok, skäl = quota.can_start(kv=self._kv())
        if not ok:
            logger.warning("Hoppar över %s: %s", chain, skäl)
        return ok

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
            if not _får_köras(chain):
                continue
            # GENOMFÖRD, inte LYCKAD (D5). Villkoret läste lastSuccessfulRun,
            # och en Primat-körning som slår i radtaket märks "blocked" -
            # aldrig "success" - hur många rader den än hann publicera. ICA
            # och Coop hade alltså en katalog i databasen och
            # lastSuccessfulRun = None för alltid, så VARJE deploy startade om
            # dem och betalade för katalogen en gång till. Två deployer samma
            # dag räckte för att bränna dygnskvoten.
            #
            # Det kan inte loopa: så fort en körning publicerat något är
            # lastCompletedRun satt och villkoret slutar gälla, hur många
            # omstarter som än kommer.
            if state.get("products", 0) == 0 or not state.get("lastCompletedRun"):
                needy.append(chain)
        if not needy:
            return False

        logger.warning("Prisdatabasen saknar fungerande data för %s - importerar",
                       ", ".join(needy))
        started_any = False
        for chain in needy:
            # KVOTEN FRÅGAS FÖRE START, inte efteråt. En bootstrap som kör
            # mot en tom dygnskvot får ett 429 per kedja, lämnar tre
            # blocked-markeringar och har ingen katalog att visa för det.
            if not self._primat_quota_allows(chain):
                continue
            # EN KEDJA FÅR INTE TA DE ÖVRIGA MED SIG. Metoden körs på en
            # daemon-tråd utan handler: ett undantag här dödade tråden tyst,
            # och de kedjor som stod på tur importerades aldrig. Sett i
            # produktion 2026-09-10: Coop hämtade 12 079 varor, sedan hände
            # ingenting med ICA och Lidl - inget fel i loggen, ingen körning,
            # bara tystnad tills nästa nattjobb.
            try:
                if not importer.start(chain).get("started"):
                    logger.warning("Bootstrap hoppade över %s: en import pågick redan", chain)
                    continue
                started_any = True
                # One at a time, waited for, not fired in parallel: the
                # importer refuses concurrent runs anyway, and three
                # simultaneous walks on a booting 512 MB instance is how the
                # last OOM happened. Waiting here is free - this whole method
                # runs on its own daemon thread.
                while importer.status().get("running"):
                    time.sleep(30)
            except Exception:
                logger.exception("Bootstrap av %s misslyckades - fortsätter med nästa", chain)
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
                # Rader som lagrades innan skrubbningen fanns kan bära en
                # hemlighet, och provider_status serverar dem publikt.
                rensade = store.scrub_stored_errors()
            finally:
                store.close()
            if stale:
                logger.warning("Markerade %d avbruten körning(ar) från en tidigare process", stale)
            if rensade:
                logger.warning("Rensade hemligheter ur %d lagrat felmeddelande(n)", rensade)
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
            from .enrichment import (backfill_provider_fields, classify_package_sources,
                                     enrichment_enabled, recompute_verdicts)
            store = grocery_api.open_store()
            try:
                backfill_provider_fields(store)
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
            "notScheduled": {},
            # ICA, Coop och Lidl HAR ett jobb men kan behöva flera körningar
            # innan katalogen är hel: en körning som slår i kvottaket märks
            # "blocked", behåller det den hann hämta och slås ihop nästa
            # gång. Hur stor kvoten är står inte här - den läses ur Primats
            # /me. Sagt rakt ut så adminvyn inte ser en halv katalog som ett
            # fel.
            "partialUntilFullTier": {
                "ICA": "Primat: full katalog kan kräva flera körningar om kvoten tar slut",
                "Coop": "Primat: samma villkor som ICA",
                "Lidl": "Primat: feedens verkliga storlek är inte uppmätt än",
            },
            "registerSyncAt": REGISTER_SYNC_AT,
            # Radbokföringen syns, för annars är den en spärr ingen kan se
            # förrän den slår till. Talet är VÅRT - Primats /me är facit, och
            # det säger fältet uttryckligen.
            "rowBudget": _row_budget_status(self._kv()),
        }

    def _run_ops_alerts(self):
        """Läser panelen, jämför mot öppna incidenter och mejlar det som är
        nytt. Allt tillstånd ligger i databasen, så en omstart mitt i en
        incident inte skickar om larmet."""
        try:
            from . import alerts, api as grocery_api
            from api_server import KV_CACHE, MAIL_CONFIG
            # KVOTEN MED I KOLLEN. alerts.evaluate har haft en färdig
            # 85 %-varning sedan den skrevs, men anropet skickade aldrig
            # någon quota - grenen var alltså död kod och kunde aldrig
            # larma. Med en betald nivå är det just den vakten som gör
            # nytta: slår kvoten i taket byggs täckningen upp över flera
            # nätter i stället för en, och det ska synas innan det händer.
            #
            # Uppslaget får ALDRIG fälla driftkollen: utan nyckel, vid
            # nätfel eller okänt svarsformat blir quota None och resten
            # körs som förut.
            kvot = _primat_quota()
            if kvot:
                # Primats eget tak är facit, och det här är enda stället där
                # vi faktiskt får se det. Sparat blir det budgeten som
                # radbokföringen (quota.py) räknar mot, i stället för vårt
                # utgångsvärde - byter kontot nivå följer spärren med utan
                # deploy.
                from . import quota as row_quota
                row_quota.remember_reported_budget(kvot.get("dailyRowLimit"), kv=KV_CACHE)
            resultat = alerts.process(grocery_api.provider_status(), KV_CACHE, MAIL_CONFIG,
                                      quota=kvot)
            if resultat["incidents"] or resultat["recoveries"]:
                logger.warning("Driftlarm: %d nya, %d lösta",
                               len(resultat["incidents"]), len(resultat["recoveries"]))
            else:
                logger.info("Driftkoll: inget att larma om")
        except Exception:
            logger.exception("Driftkollen kunde inte köras")


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
        day_stamp = now.strftime("%Y-%m-%d")
        # Klockslaget har passerat i dag, och jobbet har inte kört i dag. Det
        # är hela regeln, för varje jobb i loopen. Tidigare låg ett fönster
        # på fem minuter runt varje klockslag: en deploy 02:03-02:05 tog
        # Willys hela den natten, och en tick som blev försenad av last tog
        # driftkollen med sig.
        for nyckel, klockslag, mål, trådnamn, args in (
            # Saknas registret helt (första synken föll t.ex. på dagens
            # Primat-kvot) görs ett nytt försök varje natt tills det sitter -
            # utan att vänta på nästa deploy eller söndag.
            ("__register_retry__", REGISTER_RETRY_AT, self._sync_register_if_missing,
             "grocery-register-retry", ()),
            # Referensnivån läks varje natt efter prisjobben, inte bara vid
            # boot: en kedja vars referens släpar efter sina verifierade
            # priser fylls.
            ("__reference_heal__", REFERENCE_HEAL_AT, self.activate_platform,
             "grocery-reference-heal", ()),
            # Dabas-berikning efter nattens prisjobb: nya GTIN får masterdata,
            # gamla omprövas i sitt fönster. Bara när den uttryckligen är
            # aktiverad (nyckel + MATJAKT_DABAS_ENRICHMENT_ENABLED=1).
            ("__dabas__", DABAS_ENRICHMENT_AT, self._run_dabas_enrichment,
             "grocery-dabas-enrichment", ()),
            # Driftkollen efter nattens importer. Egen tråd och egen try: ett
            # trasigt larm får aldrig fälla schemaläggaren - då byter vi ut
            # ett driftproblem mot ett kundproblem.
            ("__ops__", OPS_ALERT_AT, self._run_ops_alerts,
             "grocery-ops-alerts", ()),
        ):
            # Alla fyra är idempotenta och körs dessutom redan vid boot, så
            # att ta igen ett missat pass kostar ingenting utom några
            # sekunders arbete. Kedjorna nedan är dyra och behandlas därför
            # strängare.
            if self._is_due(now, klockslag, nyckel, day_stamp):
                self._mark_run(nyckel, day_stamp)
                threading.Thread(target=mål, args=args, name=trådnamn, daemon=True).start()
        # Butiksregistret: veckovis (söndag 01:00), separat från prisjobben -
        # butiker byter inte adress varje natt och synken kostar ~2 800 rader
        # av Primat-kvoten. Just därför får den INTE tas igen i efterhand: en
        # deploy en söndagseftermiddag ska inte kosta en registersynk, och en
        # missad söndag kostar ingenting alls - adresser ändras inte på en
        # vecka, och _sync_register_if_missing ovan fångar ett register som
        # saknas helt redan nästa natt.
        if (now.strftime("%a %H:%M") == REGISTER_SYNC_AT
                and self._last_run_day("__register__") != day_stamp):
            self._mark_run("__register__", day_stamp)
            threading.Thread(target=self._sync_register, args=("veckosynk",),
                             name="grocery-register-sync", daemon=True).start()

        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for chain, when in self.schedule.items():
            if not self._is_due(now, when, chain, day_stamp):
                continue
            if not _får_köras(chain):
                # Ingen markering: kedjan hoppades över för att nyckeln
                # saknas, inte för att den kördes. Får nyckeln komma på plats
                # i kväll ska jobbet kunna gå i natt.
                continue
            if self._chain_already_started_today(chain, day_start):
                self._mark_run(chain, day_stamp)
                continue
            if not self._primat_quota_allows(chain):
                # MARKERAS som skött för i dag. Kvoten nollställs midnatt UTC
                # = 02:00 svensk tid, och alla tre Primat-jobben ligger efter
                # det - är kvoten slut vid jobbets klockslag finns det inget
                # mer att hämta förrän i morgon. Utan markeringen hade
                # schemaläggaren prövat samma kedja varje minut resten av
                # dygnet och loggat lika ofta.
                self._mark_run(chain, day_stamp)
                continue
            result = importer.start(chain)
            if result.get("started"):
                # MARKERAS FÖRST NU. Låg markeringen före start() räknades en
                # kedja som fick "already_running" som körd, och dygnets
                # körning var förbrukad utan att någonting hämtats.
                self._mark_run(chain, day_stamp)
                logger.info("Nattjobb startade import för %s", chain)
            else:
                # Not an error: the importer allows one run at a time on
                # purpose, and a still-running job is the normal reason. Utan
                # markering står jobbet kvar som oskött och tas om vid nästa
                # tick, när den pågående importen är klar.
                logger.info("Nattjobb hoppade över %s: %s - försöker igen vid nästa tick",
                            chain, result.get("reason"))


def _due_today(now, when: str):
    """Dagens förekomst av ett "HH:MM"-klockslag, i samma tidszon som now.
    På sommartidsnatten pekar 02:00 på en minut som inte finns; i UTC-
    jämförelsen blir den då lika med 03:00, så jobbet startar då i stället
    för att utebli."""
    try:
        hour, minute = (int(part) for part in when.split(":"))
    except (TypeError, ValueError):
        return None
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _row_budget_status(kv):
    """Radbokföringen för adminvyn. Får aldrig fälla statusanropet: en
    oläsbar bokföring är ett tomt fält, inte ett 500."""
    try:
        from . import quota
        return quota.status(kv=kv)
    except Exception:
        logger.exception("Kunde inte läsa radbokföringen")
        return None


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


SCHEDULER = GroceryScheduler()


def _primat_quota():
    """Primats egen kvot, eller None. Aldrig ett gissat tal."""
    try:
        from api_server import PRIMAT_API_KEY
        from services.pricing import primat_account_status
        from . import alerts
        if not PRIMAT_API_KEY:
            return None
        return alerts.quota_from_account_status(primat_account_status(PRIMAT_API_KEY))
    except Exception:
        logger.info("Primats kvot kunde inte läsas - driftkollen fortsätter utan den")
        return None
