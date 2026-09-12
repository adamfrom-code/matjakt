# -*- coding: utf-8 -*-
"""Sparhistoriken: den enda siffran som BEVISAR att prenumerationen betalar sig.

J3 flyttade upp historiken till Premium, och den flytten är bara ärlig om
siffran finns. Före det här paketet fanns den inte på servern alls -
`state.savingsLog` låg i webbläsarens localStorage, alltså borta vid varje
byte av telefon, varje rensning och varje ominstallation. "Ni har sparat
612 kr sedan i september" gick inte att säga, för ingen visste det.

TRE BESLUT SOM ÄR VÄRDA ATT SKRIVA UT

**Öre, inte kronor.** Beloppen lagras som heltal öre. Femtiotvå veckor
avrundade var för sig och sedan summerade blir en månadsrapport som inte
stämmer med veckorna den består av, och en budgetapp som räknar fel på sin
egen sparsiffra har inget att sälja.

**Besparingen är ett mellanrum, aldrig ett negativt tal.** Den är skillnaden
mellan den dyraste jämförbara butiken och den billigaste - alltså vad veckan
hade kostat någon annanstans. Är dyraste lägre än billigaste är underlaget
trasigt; då sparas noll i stället för en lögn åt andra hållet.

**En rad per konto och vecka.** Prissätts samma vecka om (byten, ändrad
lista) skrivs raden över i stället för att läggas till. Annars hade "sparat i
september" vuxit med varje omräkning, vilket är den sortens siffra som är
imponerande precis tills någon kontrollräknar den.

Free/Premium ändrar vad som VISAS, aldrig vad som är SANT (features.py):
gratiskontot får sin senaste vecka ur exakt samma rader, och när det
uppgraderar finns hela historiken redan där - den har samlats hela tiden.
"""

import math
import sqlite3
import threading
from datetime import date, datetime, timezone

# Så många veckor bakåt den fulla historiken sträcker sig i ett svar.
MAX_WEEKS = 104
MONTH_NAMES = ("januari", "februari", "mars", "april", "maj", "juni", "juli",
               "augusti", "september", "oktober", "november", "december")


def _ore(value) -> int:
    """Kronor (float från klienten) -> hela öre. Allt ogiltigt blir 0."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    # NaN och oändligheter tyst till noll: de kommer från en klient som
    # räknat fel, och en sparsumma på "inf kr" är värre än ingen.
    if not math.isfinite(number):
        return 0
    if number < 0:
        return 0
    return int(round(number * 100))


def _kronor(ore) -> float:
    return round(int(ore) / 100, 2)


def current_week_key(today: date | None = None) -> str:
    """ISO-veckan, "2026-W37". ISO för att den är entydig över nyår -
    "vecka 1" utan år har bitit fler än en kalenderfunktion."""
    day = today or datetime.now(timezone.utc).date()
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def normalize_week_key(value, today: date | None = None) -> str:
    """Klientens veckonyckel, eller den här veckan om den inte duger.

    Formen kontrolleras hårt: nyckeln är en primärnyckelhalva och får
    varken vara fritext eller ett sätt att skriva 10 000 rader per konto."""
    parts = str(value or "").strip().upper().split("-W")
    if len(parts) == 2:
        year, week = parts
        if len(year) == 4 and year.isdigit() and week.isdigit() and 1 <= int(week) <= 53:
            return f"{int(year):04d}-W{int(week):02d}"
    return current_week_key(today)


def month_of(week_key: str) -> str | None:
    """Vilken månad ("2026-09") en ISO-vecka hör till: torsdagen bestämmer,
    precis som ISO-veckans år gör. En vecka som delas av ett månadsskifte
    måste hamna i EN månad, annars summerar månadsrapporten till mer än
    året."""
    try:
        year, week = week_key.split("-W")
        thursday = date.fromisocalendar(int(year), int(week), 4)
    except (ValueError, AttributeError):
        return None
    return f"{thursday.year}-{thursday.month:02d}"


def month_label(month_key: str) -> str:
    """"2026-09" -> "september 2026". Svenska, gemener - det är så det står
    i en mening: "Du sparade 1 340 kr i september"."""
    try:
        year, month = month_key.split("-")
        return f"{MONTH_NAMES[int(month) - 1]} {int(year)}"
    except (ValueError, IndexError, AttributeError):
        return month_key


class SavingsStore:
    """En tabell i kontodatabasen. Delar anslutning och lås med AccountStore
    av samma skäl som AnalyticsStore gör det: en commit() från en annan tråd
    på samma anslutning nollställer ett pågående sessionsuppslag."""

    def __init__(self, connection: sqlite3.Connection, lock=None):
        self._connection = connection
        self._lock = lock if lock is not None else threading.RLock()
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS savings_weeks (
                    user_id INTEGER NOT NULL,
                    week_key TEXT NOT NULL,
                    saved_ore INTEGER NOT NULL DEFAULT 0,
                    cheapest_ore INTEGER,
                    priciest_ore INTEGER,
                    chain TEXT,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, week_key)
                );
                CREATE INDEX IF NOT EXISTS idx_savings_user
                    ON savings_weeks(user_id, week_key DESC);
                """
            )
            self._connection.commit()

    # ---- skrivning -------------------------------------------------------

    def record_week(self, user_id, *, week_key=None, cheapest_total=None,
                    priciest_total=None, saved=None, chain=None) -> dict:
        """Skriver en veckas besparing för ett konto. Idempotent per vecka.

        Antingen skickas de två totalerna (då räknas mellanrummet här, på
        servern) eller ett färdigt `saved`. Det första är att föredra:
        siffrorna kommer då från samma jämförelse som resten av appen visar,
        och kan inte bli ett tal klienten hittat på."""
        key = normalize_week_key(week_key)
        cheapest = _ore(cheapest_total) if cheapest_total is not None else None
        priciest = _ore(priciest_total) if priciest_total is not None else None
        if cheapest is not None and priciest is not None:
            # Ett mellanrum, aldrig ett negativt tal: ett trasigt underlag
            # sparar noll hellre än en besparing åt fel håll.
            saved_ore = max(0, priciest - cheapest)
        else:
            saved_ore = _ore(saved)
        with self._lock:
            self._connection.execute(
                """INSERT INTO savings_weeks
                       (user_id, week_key, saved_ore, cheapest_ore, priciest_ore, chain, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, week_key) DO UPDATE SET
                       saved_ore = excluded.saved_ore,
                       cheapest_ore = excluded.cheapest_ore,
                       priciest_ore = excluded.priciest_ore,
                       chain = excluded.chain,
                       recorded_at = excluded.recorded_at""",
                (int(user_id), key, saved_ore, cheapest, priciest,
                 (str(chain)[:40] if chain else None),
                 datetime.now(timezone.utc).isoformat()),
            )
            self._connection.commit()
        return {"weekKey": key, "savedKr": _kronor(saved_ore)}

    def forget_user(self, user_id) -> int:
        """GDPR: raderas kontot följer sparhistoriken med."""
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM savings_weeks WHERE user_id = ?", (int(user_id),))
            self._connection.commit()
            return cursor.rowcount

    # ---- läsning ---------------------------------------------------------

    def weeks(self, user_id, limit=MAX_WEEKS) -> list:
        """Veckorna, nyast först. Alltid HELA sanningen ur databasen - det
        är läsvägen ovanför som maskar för Free, inte den här."""
        rows = self._connection.execute(
            """SELECT week_key, saved_ore, cheapest_ore, priciest_ore, chain
               FROM savings_weeks WHERE user_id = ?
               ORDER BY week_key DESC LIMIT ?""",
            (int(user_id), int(min(limit, MAX_WEEKS)))).fetchall()
        return [{
            "weekKey": row["week_key"],
            "savedKr": _kronor(row["saved_ore"]),
            "cheapestKr": _kronor(row["cheapest_ore"]) if row["cheapest_ore"] is not None else None,
            "priciestKr": _kronor(row["priciest_ore"]) if row["priciest_ore"] is not None else None,
            "chain": row["chain"],
        } for row in rows]

    def total_ore(self, user_id) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(SUM(saved_ore), 0) AS total FROM savings_weeks WHERE user_id = ?",
            (int(user_id),)).fetchone()
        return int(row["total"] if row else 0)

    def months(self, user_id, limit=24) -> list:
        """Månadsrapporten: "Du sparade 1 340 kr i september."

        Summeras i öre ur veckoraderna och avrundas EN gång, sist. Tolv
        veckor avrundade var för sig och sedan adderade kan skilja sex öre
        från sanningen - lite, men fel på just den siffra hela paketeringen
        vilar på."""
        totals: dict[str, dict] = {}
        for row in self._connection.execute(
                "SELECT week_key, saved_ore FROM savings_weeks WHERE user_id = ?",
                (int(user_id),)).fetchall():
            key = month_of(row["week_key"])
            if not key:
                continue
            entry = totals.setdefault(key, {"ore": 0, "weeks": 0})
            entry["ore"] += int(row["saved_ore"])
            entry["weeks"] += 1
        ordered = sorted(totals.items(), key=lambda pair: pair[0], reverse=True)[:int(limit)]
        return [{
            "month": key,
            "label": month_label(key),
            "savedKr": _kronor(entry["ore"]),
            "weeks": entry["weeks"],
            # Färdig mening, formulerad på ETT ställe. Skrivs den i klienten
            # blir den snart tre olika meningar i tre vyer.
            "sentence": f"Du sparade {_kronor(entry['ore']):.0f} kr i {month_label(key).split()[0]}.",
        } for key, entry in ordered]

    def report(self, user_id, *, max_weeks, include_months) -> dict:
        """Svaret på GET /api/savings, redan maskat för planen.

        `max_weeks` och `include_months` kommer från features.py via
        grinden. Den här funktionen bestämmer ingenting om planer - den
        lyder ett tal och en boolean, så maskningen bara kan ha en källa."""
        everything = self.weeks(user_id)
        shown = everything[:max(0, int(max_weeks))]
        return {
            "weeks": shown,
            "months": self.months(user_id) if include_months else [],
            # Hela sanningen om HUR MYCKET som finns, även för Free: att
            # veta att det finns 23 veckor bakom låset är själva
            # försäljningen. Att dölja mängden vore att dölja erbjudandet.
            "weeksAvailable": len(everything),
            "weeksShown": len(shown),
            "totalSavedKr": _kronor(self.total_ore(user_id)) if include_months else None,
        }
