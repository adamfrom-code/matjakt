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
from datetime import date, datetime, timedelta, timezone

# Kärnhändelserna: skapas veckor, används fynden, bockas listan av, delas
# recept, rapporteras prisfel - och den grova tratten över flikarna.
# Nedladdningar är fåfänga; återkommande veckor är sanningen.
ANALYTICS_EVENTS = frozenset({
    "cta_testa_gratis", "cta_logga_in", "cta_se_hur_det_fungerar", "view_premium",
    "vecka_skapad", "fynd_tillagt", "lista_anvand", "recept_delat",
    "prisfel_rapporterat", "recept_bytt",
    "view_home", "view_week", "view_recipes", "view_basket", "view_pantry",
})

# Händelsen som betyder att en person faktiskt använt produkten, inte bara
# tittat. Trattens andra steg.
ACTIVATION_EVENT = "vecka_skapad"
# Efter så många dagar räknas en återkomst som "kom tillbaka", dvs. inte
# samma nyfikna första kväll.
RETURN_AFTER_DAYS = 7


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


class AnalyticsStore:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
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

    def funnel(self, weeks: int = 8, premium_of=None) -> dict:
        """Tratten per registreringsvecka plus totaler. `premium_of(row)`
        avgör om ett konto är Premium (kontotjänstens egen regel, så tratten
        och /auth/me alltid är överens)."""
        today = datetime.now(timezone.utc).date()
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(users)")}
        has_last_active = "last_active_day" in columns
        users = self._connection.execute("SELECT * FROM users").fetchall()
        activity = self._user_days()

        cohorts: dict[str, dict] = {}
        active_7, active_28, premium_total, registered_7 = set(), set(), 0, 0
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
            last_day = _day_of(max(days)) or created
            if last_day >= today - timedelta(days=6):
                active_7.add(user_id)
            if last_day >= today - timedelta(days=27):
                active_28.add(user_id)
            if created >= today - timedelta(days=6):
                registered_7 += 1
            premium_total += 1 if is_premium else 0
            if created < week_cutoff:
                continue
            cohort = cohorts.setdefault(_iso_week(created), {
                "vecka": _iso_week(created), "registrerade": 0, "skapadeVecka": 0,
                "tillbakaEfter7Dagar": 0, "premium": 0,
                # Kohorten kan svara på "kom tillbaka" först när alla i den
                # haft sju dagar på sig. Innan dess är siffran ofullständig.
                "mogen": True,
            })
            cohort["registrerade"] += 1
            cohort["skapadeVecka"] += 1 if activated else 0
            cohort["tillbakaEfter7Dagar"] += 1 if returned else 0
            cohort["premium"] += 1 if is_premium else 0
            cohort["mogen"] = cohort["mogen"] and return_from <= today

        ordered = [cohorts[key] for key in sorted(cohorts, reverse=True)]
        return {
            "totalt": {
                "registrerade": len(users),
                "registreradeSenaste7Dagarna": registered_7,
                "aktivaSenaste7Dagarna": len(active_7),
                "aktivaSenaste28Dagarna": len(active_28),
                "premium": premium_total,
            },
            "kohorter": ordered,
            "definitioner": {
                "skapadeVecka": f"minst en händelse '{ACTIVATION_EVENT}' inloggad",
                "tillbakaEfter7Dagar": f"aktiv någon dag minst {RETURN_AFTER_DAYS} dagar efter registreringen",
                "mogen": "alla i kohorten har haft sju dagar på sig - först då är återkomstsiffran fullständig",
            },
        }
