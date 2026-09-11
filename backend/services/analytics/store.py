"""Produktmätning: räknar de händelser som avgör om Matjakt fungerar.

Två tabeller i kontodatabasen, ingenting annat:

  analytics_daily      event x dag -> antal          (anonymt, som förut)
  analytics_user_days  konto x dag x event -> antal  (bara inloggade)

Det andra bordet är hela skillnaden mot de gamla räknarna. "23 veckor
skapades i går" säger inte om det var 23 personer eller en person som
klickade 23 gånger, och det kan aldrig svara på den enda frågan som
avgör lanseringen: kommer någon tillbaka vecka två? Med konto och DAG
(aldrig klockslag, aldrig IP, aldrig fritext) kan tratten räknas per
registreringsvecka: registrerade -> skapade en vecka -> tillbaka efter
sju dagar -> Premium.

Varför inte kv_cache som förut: den rensar allt äldre än sju dagar, så
"senaste fjorton dagarna" tappade tyst hälften. Mätdata är inte cache.

Händelserna är en fast lista. Klienten kan inte hitta på nya namn, så
tabellerna kan aldrig bli en plats att smuggla in godtycklig eller
identifierande data genom.
"""

import sqlite3
import threading
import functools
from datetime import date, datetime, timedelta, timezone

# Kärnhändelserna: skapas veckor, används fynden, bockas listan av, delas
# recept, rapporteras prisfel - och den grova tratten över flikarna.
# Nedladdningar är fåfänga; återkommande veckor är sanningen.
ANALYTICS_EVENTS = frozenset({
    "cta_testa_gratis", "cta_logga_in", "cta_se_hur_det_fungerar", "view_premium",
    "vecka_skapad", "fynd_tillagt", "lista_anvand", "recept_delat",
    "prisfel_rapporterat", "recept_bytt",
    "view_home", "view_week", "view_recipes", "view_basket", "view_pantry",
    # Vyer appen redan skickade men listan avvisade. setView() i app.js
    # skickar view_<vy> för VARJE vy, och de tre nedan fanns inte här - varje
    # gång någon öppnade sparstatistiken, butiksjämförelsen eller kedjelistan
    # svarade servern 400 och tappade siffran. Verifierat i produktionsloggen.
    "view_stats", "view_comparison", "view_chainlist",
    # I7: kontot, hushållet och hela betalsteget. Utan dem slutade mätningen
    # vid "öppnade Premium-vyn" - trattens dyraste steg var osynligt.
    "konto_skapat", "inbjudan_skickad", "inbjudan_accepterad", "mail_klick",
    "checkout_startad", "checkout_avbruten", "betalning_genomford", "premium_kop",
    "plan_vald_manad", "plan_vald_ar", "uppsagning_paborjad",
})

# Händelsen som betyder att en person faktiskt använt produkten, inte bara
# tittat. Trattens andra steg.
ACTIVATION_EVENT = "vecka_skapad"
# Efter så många dagar räknas en återkomst som "kom tillbaka", dvs. inte
# samma nyfikna första kväll.
RETURN_AFTER_DAYS = 7
# "Skapar en vecka inom 48 h" mätt i de enheter datan faktiskt har. Tabellen
# lagrar DAG, aldrig klockslag (det är ett medvetet val i integritetspolicyn),
# så 48 timmar går inte att räkna - två kalenderdagar gör det. Talet heter
# därför det det är. Ett mått som låtsas ha en precision underlaget saknar är
# värre än ett trubbigare mått som stämmer.
ACTIVATION_WINDOW_DAYS = 2

# Priserna är satta INKLUSIVE moms (prisinformationslagen; se
# services/billing/tax.py, EXPECTED_TAX_BEHAVIOR = "inclusive"). MRR i
# kronor är därför brutto, och nettot - det som blir intäkt - är brutto
# delat med 1,25. Båda redovisas, för de svarar på olika frågor.
MOMSSATS = 0.25


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _day_of(iso_text) -> date | None:
    try:
        return datetime.fromisoformat(str(iso_text)).date()
    except (TypeError, ValueError):
        return None


def _iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-V{week:02d}"


def manadsvarden() -> dict:
    """Vad en prenumeration är värd PER MÅNAD, i kronor inklusive moms.

    Talen läses ur services/accounts/features.py: 59 och 399 finns DÄR och
    ingen annanstans i koden, och en andra kopia här hade blivit fel den dag
    paketeringen ändras (J3). Årsplanen periodiseras - 399 kr på ett år är
    33,25 kr i månaden, och att räkna den som 399 kr MRR i inbetalningsmånaden
    hade fått varje mars att se ut som en raket.

    Importen är lat med flit: analytics ska kunna läsas utan att dra in
    kontopaketet, och en cirkulär import vid uppstart är dyrare än ett
    funktionsanrop."""
    from ..accounts import features
    priser = features.PRICING
    return {
        "monthly": float(priser["monthly"]["pricePerMonth"]),
        "yearly": float(priser["yearly"]["pricePerYear"]) / 12.0,
    }


def _manadsvarde(plan, priser: dict) -> float:
    """Planens månadsvärde. Okänd eller saknad plan ger 0 - ett betalande
    konto vars plan vi inte känner igen räknas hellre som noll kronor än som
    en gissning, och avvikelsen syns då i `betalandeUtanKandPlan`."""
    nyckel = str(plan or "").replace("premium_", "")
    return priser.get(nyckel, 0.0)


def _ore(belopp: float) -> float:
    """Kronor med två decimaler. Flyttal som visas som pengar ska avrundas
    en gång, vid kanten, inte ackumulera decimalskräp genom hela kedjan."""
    return round(float(belopp) + 0.0, 2)


class AnalyticsStore:
    def __init__(self, connection: sqlite3.Connection, lock=None):
        self._connection = connection
        # Delar anslutning med AccountStore: SAMMA lås, annars kan en
        # commit() här nollställa ett sessionsuppslag i en annan tråd.
        self._lock = lock if lock is not None else threading.RLock()
        self._init_schema()

    def _init_schema(self):
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS analytics_daily (
                event TEXT NOT NULL,
                day TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (event, day)
            );
            CREATE TABLE IF NOT EXISTS analytics_user_days (
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                event TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day, event)
            );
            """
        )
        self._connection.commit()

    # ---- Skrivning ----------------------------------------------------------
    def record(self, event: str, user_id: int | None = None, day: str | None = None) -> bool:
        """Räknar upp händelsen för dagen; med konto även per konto och dag.
        Okända händelser ignoreras (returnerar False) - aldrig ett undantag,
        mätning får inte störa appen."""
        if event not in ANALYTICS_EVENTS:
            return False
        day = day or _today()
        with self._connection:
            self._connection.execute(
                """INSERT INTO analytics_daily (event, day, count) VALUES (?, ?, 1)
                   ON CONFLICT(event, day) DO UPDATE SET count = count + 1""",
                (event, day),
            )
            if user_id is not None:
                self._connection.execute(
                    """INSERT INTO analytics_user_days (user_id, day, event, count) VALUES (?, ?, ?, 1)
                       ON CONFLICT(user_id, day, event) DO UPDATE SET count = count + 1""",
                    (int(user_id), day, event),
                )
        return True

    def import_legacy_counters(self, lookup, days: int = 14) -> int:
        """Engångsflytt från de gamla kv_cache-räknarna: lookup(event, day)
        -> antal eller None. Skriver bara dagar som saknas här, så flytten
        är ofarlig att köra vid varje uppstart."""
        imported = 0
        today = datetime.now(timezone.utc).date()
        with self._connection:
            for event in sorted(ANALYTICS_EVENTS):
                for back in range(days):
                    day = (today - timedelta(days=back)).isoformat()
                    try:
                        count = lookup(event, day)
                    except Exception:
                        count = None
                    if not count:
                        continue
                    cursor = self._connection.execute(
                        "INSERT OR IGNORE INTO analytics_daily (event, day, count) VALUES (?, ?, ?)",
                        (event, day, int(count)),
                    )
                    imported += cursor.rowcount
        return imported

    # ---- Läsning ------------------------------------------------------------
    def user_days(self, user_id) -> list[dict]:
        """Kontots egna mätrader - vilken händelse, vilken dag, hur många.

        B10: exporten ska visa allt vi vet, och det här är den enda tabellen
        som håller något PER konto utöver kontoraden själv. Att kunna se den
        är skillnaden mellan "vi mäter användning" och "vi kan visa exakt
        vad vi mätt om just dig"."""
        return [{"dag": row["day"], "handelse": row["event"], "antal": row["count"]}
                for row in self._connection.execute(
                    "SELECT day, event, count FROM analytics_user_days WHERE user_id = ? "
                    "ORDER BY day, event", (user_id,))]

    def daily_events(self, days: int = 14) -> dict:
        """{event: {"total": n, "unikaKonton": u, "perDag": {dag: n}}} för
        de senaste `days` dagarna, plus dagarna i ordning."""
        today = datetime.now(timezone.utc).date()
        day_list = [(today - timedelta(days=back)).isoformat() for back in range(days - 1, -1, -1)]
        first = day_list[0]
        events = {event: {"total": 0, "unikaKonton": 0, "perDag": {}} for event in sorted(ANALYTICS_EVENTS)}
        for event, day, count in self._connection.execute(
            "SELECT event, day, count FROM analytics_daily WHERE day >= ?", (first,)
        ):
            entry = events.setdefault(event, {"total": 0, "unikaKonton": 0, "perDag": {}})
            entry["perDag"][day] = int(count)
            entry["total"] += int(count)
        for event, users in self._connection.execute(
            "SELECT event, COUNT(DISTINCT user_id) FROM analytics_user_days WHERE day >= ? GROUP BY event",
            (first,),
        ):
            events.setdefault(event, {"total": 0, "unikaKonton": 0, "perDag": {}})["unikaKonton"] = int(users)
        return {"dagar": day_list, "events": events}

    def _user_days(self) -> dict:
        """konto -> {"dagar": set(dag), "aktiverad": första dag med vecka_skapad}"""
        result = {}
        for user_id, day, event in self._connection.execute(
            "SELECT user_id, day, event FROM analytics_user_days"
        ):
            entry = result.setdefault(int(user_id), {"dagar": set(), "aktiverad": None})
            entry["dagar"].add(day)
            if event == ACTIVATION_EVENT and (entry["aktiverad"] is None or day < entry["aktiverad"]):
                entry["aktiverad"] = day
        return result

    def funnel(self, weeks: int = 8, premium_of=None, premium_source_of=None) -> dict:
        """Tratten per registreringsvecka plus totaler. `premium_of(row)`
        avgör om ett konto är Premium (kontotjänstens egen regel, så tratten
        och /auth/me alltid är överens).

        `premium_source_of(row)` säger VARFÖR: "subscription", "trial",
        "comped" eller None. A01 kräver att gratis och kompenserad Premium
        skiljs från faktiskt betalande - en boolean räckte inte, och den
        som ska bedöma om affären bär behöver veta vilken sorts Premium
        siffran består av."""
        today = datetime.now(timezone.utc).date()
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(users)")}
        has_last_active = "last_active_day" in columns
        has_plan = "subscription_plan" in columns
        has_sub_id = "stripe_subscription_id" in columns
        has_cancel_flag = "subscription_cancel_at_period_end" in columns
        users = self._connection.execute("SELECT * FROM users").fetchall()
        activity = self._user_days()
        priser = manadsvarden()

        cohorts: dict[str, dict] = {}
        active_7, active_28, premium_total, registered_7 = set(), set(), 0, 0
        per_kalla = {"subscription": 0, "trial": 0, "comped": 0}
        # I7: tratten räknade konton, aldrig kronor. Utan MRR går det inte att
        # svara på om affären bär, och det är den enda frågan siffrorna finns
        # för.
        mrr = 0.0
        utan_kand_plan = 0
        har_haft_prenumeration = 0
        sager_upp_vid_periodslut = 0
        aktiverade_snabbt, mogna_for_snabbfragan = 0, 0
        week_cutoff = today - timedelta(days=7 * weeks)
        for row in users:
            user_id = int(row["id"])
            created = _day_of(row["created_at"]) or today
            days = set(activity.get(user_id, {}).get("dagar", set()))
            if has_last_active and row["last_active_day"]:
                days.add(row["last_active_day"])
            days.add(created.isoformat())
            activated = activity.get(user_id, {}).get("aktiverad")
            return_from = created + timedelta(days=RETURN_AFTER_DAYS)
            returned = any((parsed := _day_of(day)) is not None and parsed >= return_from for day in days)
            is_premium = bool(premium_of(row)) if premium_of else bool(row["premium"])
            källa = premium_source_of(row) if (is_premium and premium_source_of) else None
            # "Skapade en vecka inom två dygn": aktiveringsdagen får ligga
            # högst ACTIVATION_WINDOW_DAYS efter registreringsdagen. Nämnaren
            # är bara de konton som HUNNIT få sina två dygn - annars sjunker
            # andelen varje gång någon registrerar sig, vilket ser ut som en
            # försämring och är en artefakt.
            snabb_deadline = created + timedelta(days=ACTIVATION_WINDOW_DAYS)
            aktiverad_snabbt = bool(activated) and (_day_of(activated) or today) <= snabb_deadline
            snabbfragan_mogen = snabb_deadline <= today
            last_day = _day_of(max(days)) or created
            if last_day >= today - timedelta(days=6):
                active_7.add(user_id)
            if last_day >= today - timedelta(days=27):
                active_28.add(user_id)
            if created >= today - timedelta(days=6):
                registered_7 += 1
            if snabbfragan_mogen:
                mogna_for_snabbfragan += 1
                aktiverade_snabbt += 1 if aktiverad_snabbt else 0
            premium_total += 1 if is_premium else 0
            if källa in per_kalla:
                per_kalla[källa] += 1
            värde = 0.0
            if källa == "subscription":
                värde = _manadsvarde(row["subscription_plan"] if has_plan else None, priser)
                mrr += värde
                if not värde:
                    utan_kand_plan += 1
                if has_cancel_flag and row["subscription_cancel_at_period_end"]:
                    sager_upp_vid_periodslut += 1
            if has_sub_id and row["stripe_subscription_id"]:
                har_haft_prenumeration += 1
            if created < week_cutoff:
                continue
            cohort = cohorts.setdefault(_iso_week(created), {
                "vecka": _iso_week(created), "registrerade": 0, "skapadeVecka": 0,
                "skapadeVeckaInomTvaDygn": 0, "mognaForSnabbfragan": 0,
                "tillbakaEfter7Dagar": 0, "premium": 0, "premiumBetalande": 0,
                "mrrKronor": 0.0, "harHaftPrenumeration": 0,
                # Kohorten kan svara på "kom tillbaka" först när alla i den
                # haft sju dagar på sig. Innan dess är siffran ofullständig.
                "mogen": True,
            })
            cohort["registrerade"] += 1
            cohort["skapadeVecka"] += 1 if activated else 0
            cohort["skapadeVeckaInomTvaDygn"] += 1 if aktiverad_snabbt else 0
            cohort["mognaForSnabbfragan"] += 1 if snabbfragan_mogen else 0
            cohort["tillbakaEfter7Dagar"] += 1 if returned else 0
            cohort["premium"] += 1 if is_premium else 0
            cohort["premiumBetalande"] += 1 if källa == "subscription" else 0
            cohort["mrrKronor"] += värde
            if has_sub_id and row["stripe_subscription_id"]:
                cohort["harHaftPrenumeration"] += 1
            cohort["mogen"] = cohort["mogen"] and return_from <= today

        ordered = []
        for key in sorted(cohorts, reverse=True):
            kohort = cohorts[key]
            kohort["mrrKronor"] = _ore(kohort["mrrKronor"])
            # Churn per kohort: hur många som EN GÅNG haft en prenumeration
            # och inte betalar längre. Uppsägningen sker i Stripes portal och
            # syns bara som ett webhook-tillstånd, så det här är det enda
            # ärliga måttet vi har - och det är ett mått på tapp, inte på en
            # tidpunkt.
            kohort["tappadePremium"] = max(0, kohort["harHaftPrenumeration"]
                                           - kohort["premiumBetalande"])
            ordered.append(kohort)

        betalande = per_kalla["subscription"]
        return {
            "totalt": {
                "registrerade": len(users),
                "registreradeSenaste7Dagarna": registered_7,
                "aktivaSenaste7Dagarna": len(active_7),
                "aktivaSenaste28Dagarna": len(active_28),
                "premium": premium_total,
                # Uppdelningen är ETT konto per rad, aldrig en uppskattning.
                # Summan kan vara mindre än "premium" om källan är okänd -
                # det är ärligare än att tvinga in resten någonstans.
                "premiumBetalande": betalande,
                "premiumProv": per_kalla["trial"],
                "premiumKompenserad": per_kalla["comped"],
                "skapadeVeckaInomTvaDygn": aktiverade_snabbt,
                "mognaForSnabbfragan": mogna_for_snabbfragan,
                "aktivaHushallMedFlerAnEn": self._flerpersonshushall(active_28),
                # Kronorna. Brutto är det kunden betalar (priserna är satta
                # inklusive moms); netto är det som blir intäkt.
                "mrrKronor": _ore(mrr),
                "mrrExMomsKronor": _ore(mrr / (1 + MOMSSATS)),
                "arpuKronor": _ore(mrr / betalande) if betalande else 0.0,
                "arpuPerKontoKronor": _ore(mrr / len(users)) if users else 0.0,
                "sagerUppVidPeriodslut": sager_upp_vid_periodslut,
                "harHaftPrenumeration": har_haft_prenumeration,
                "tappadePremium": max(0, har_haft_prenumeration - betalande),
                # Ett betalande konto vars plan vi inte känner igen räknas som
                # noll kronor. Står det något annat än 0 här är MRR för låg,
                # och det ska synas i stället för att gömmas i ett snitt.
                "betalandeUtanKandPlan": utan_kand_plan,
            },
            "kohorter": ordered,
            "definitioner": {
                "skapadeVecka": f"minst en händelse '{ACTIVATION_EVENT}' inloggad",
                "skapadeVeckaInomTvaDygn": (
                    f"aktiverade senast {ACTIVATION_WINDOW_DAYS} kalenderdagar efter "
                    "registreringen. Tabellen lagrar dag, aldrig klockslag, så exakta "
                    "48 timmar går inte att räkna - talet heter det det är"),
                "mognaForSnabbfragan": "konton som hunnit få sina två dygn - andelens nämnare",
                "tillbakaEfter7Dagar": f"aktiv någon dag minst {RETURN_AFTER_DAYS} dagar efter registreringen",
                "mogen": "alla i kohorten har haft sju dagar på sig - först då är återkomstsiffran fullständig",
                "premiumBetalande": "aktiv prenumeration hos betalleverantören - inte inlöst kod, inte prov",
                "premiumKompenserad": "Premium given utan betalning, t.ex. inlöst kod",
                "aktivaHushallMedFlerAnEn": (
                    "hushåll med minst två medlemmar där någon varit aktiv de senaste 28 dagarna"),
                "mrrKronor": (
                    "summan av de betalande kontonas månadsvärde, inklusive moms. "
                    "Årsplanen periodiseras (399 kr/år = 33,25 kr/mån), annars hade "
                    "inbetalningsmånaden sett ut som en raket"),
                "tappadePremium": (
                    "konton som en gång haft en prenumeration och inte betalar nu. "
                    "Uppsägning sker i betalleverantörens portal och syns bara som "
                    "ett tillstånd - det här är ett mått på tapp, inte på en tidpunkt"),
            },
        }

    def _flerpersonshushall(self, aktiva_konton: set) -> int:
        """Hushåll med fler än en medlem där någon varit aktiv senaste 28
        dagarna. Ett hushåll som ingen öppnat på en månad är inte ett delat
        hushåll, det är två gamla rader.

        household_members ligger i samma SQLite-fil som users (se
        api_server.py: HOUSEHOLD_STORE byggs på ACCOUNT_STORE_PATH), men
        skapas av hushållstjänstens schema. I en databas där den tjänsten
        aldrig körts finns tabellen inte, och då är svaret noll - inte ett
        undantag som fäller hela kontrollrummet."""
        try:
            rader = self._connection.execute(
                "SELECT household_id, user_id FROM household_members").fetchall()
        except sqlite3.Error:
            return 0
        medlemmar: dict = {}
        for household_id, user_id in rader:
            medlemmar.setdefault(household_id, set()).add(int(user_id))
        return sum(1 for konton in medlemmar.values()
                   if len(konton) > 1 and konton & aktiva_konton)

    def veckans_tal(self, **kwargs) -> dict:
        """De fem talen, en gång i veckan, i den ordning de ska läsas.

        Varje tal bär sitt eget underlag: en andel utan nämnare är en gissning
        med decimaler, och en andel räknad på konton som inte hunnit få sin
        chans sjunker varje gång någon registrerar sig - vilket ser ut som en
        försämring och är en artefakt. Därför följer `av` och `mogen` med.

        Tar samma argument som funnel()."""
        tratt = self.funnel(**kwargs)
        t = tratt["totalt"]
        mogna_sju = sum(k["registrerade"] for k in tratt["kohorter"] if k["mogen"])
        tillbaka = sum(k["tillbakaEfter7Dagar"] for k in tratt["kohorter"] if k["mogen"])

        def andel(täljare, nämnare):
            return round(täljare / nämnare, 4) if nämnare else None

        return {
            "nyaKonton": {"tal": t["registreradeSenaste7Dagarna"], "period": "7 dagar",
                          "totaltSedanStart": t["registrerade"]},
            "skapadeVeckaInomTvaDygn": {
                "tal": t["skapadeVeckaInomTvaDygn"], "av": t["mognaForSnabbfragan"],
                "andel": andel(t["skapadeVeckaInomTvaDygn"], t["mognaForSnabbfragan"])},
            "tillbakaEfterSjuDagar": {
                "tal": tillbaka, "av": mogna_sju, "andel": andel(tillbaka, mogna_sju),
                "not": "bara mogna kohorter - de som haft sina sju dagar"},
            "aktivaHushallMedFlerAnEn": {"tal": t["aktivaHushallMedFlerAnEn"]},
            "betalandeOchMrr": {
                "tal": t["premiumBetalande"], "mrrKronor": t["mrrKronor"],
                "mrrExMomsKronor": t["mrrExMomsKronor"], "arpuKronor": t["arpuKronor"],
                "tappade": t["tappadePremium"],
                "sagerUppVidPeriodslut": t["sagerUppVidPeriodslut"],
                "utanKandPlan": t["betalandeUtanKandPlan"]},
        }


def _synchronized(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


for _name, _member in list(vars(AnalyticsStore).items()):
    if callable(_member) and not _name.startswith("_"):
        setattr(AnalyticsStore, _name, _synchronized(_member))

