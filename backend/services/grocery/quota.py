# -*- coding: utf-8 -*-
"""Dygnsbokföring av Primats radkvot: vad har vi förbrukat i dag, och finns
det utrymme kvar innan vi startar?

VARFÖR DEN HÄR FINNS. `PrimatProvider._rows_spent` räknade redan varje rad -
men bara inom en enda körning, i minnet, och ingen frågade den innan nästa
körning startade. Tre kedjor i schemat, ett tak på 40 000 rader per körning
och en dygnskvot på 100 000 gav 120 000 mot 100 000: taket låg ÖVER kvoten.
En deploy mitt på dagen kunde dessutom starta om ICA och Coop från
bootstrapen, så samma dygn kunde betala för fyra, fem, sex kataloger.

Natten 2026-09-11 mättes utfallet:

    ICA=0/0p [failed]   Coop=12079/12050p [ready_for_release]   Lidl=0/0p [limited]

ICA och Lidl kom aldrig förbi 429 från Primat. Coop hann först och tog det
som fanns kvar.

MODELLEN. En rad i KV-storen per KVOTDYGN, och kvotdygnet är Primats - inte
vårt. Kvoten nollställs midnatt UTC, alltså 02:00 svensk sommartid, så
nyckeln är UTC-datumet. Räknaren skrivs medan körningen pågår, inte efteråt:
en import som dör halvvägs har ändå förbrukat sina rader, och en bokföring
som bara skedde vid lyckad avslutning hade sagt att kvoten var orörd.

BUDGETEN. 100 000 rader per dygn på App-nivån, bekräftat ur Primats eget
429-svar 2026-09-10. Talet går att ändra utan deploy via
PRIMAT_DAILY_ROW_BUDGET - byts kontonivån är det den enda ändring som behövs.

Den här räknaren är VÅR bild av förbrukningen och kan bara vara för låg (en
rad Primat räknade men vi inte såg). Primats eget /me är sanningen, och
driftkollen varnar redan vid 85 % av det talet (alerts.quota_from_account_
status). De två kompletterar varandra: /me säger vad som hänt, den här säger
vad vi är på väg att göra - och det är bara den senare som går att fråga
INNAN ett anrop skickas.
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("matjakt.grocery.quota")

NAMESPACE = "primat_quota"

# App-nivåns dygnskvot, bekräftad ur Primats eget 429-svar 2026-09-10.
# Gratisnivån ger 20 000; sätt PRIMAT_DAILY_ROW_BUDGET om kontot byter nivå.
DEFAULT_DAILY_ROW_BUDGET = 100_000

# Under så här många rader kvar är det inte värt att starta en katalogimport:
# den skulle ändå avbrytas nästan direkt, och en avbruten körning kostar både
# rader och en blocked-markering utan att ge en användbar katalog.
MIN_ROWS_TO_START = 2_000


# Nyckeln där Primats EGET rapporterade tak sparas, när driftkollen har läst
# det ur GET /me. Inte ett datum: taket hör till kontot, inte till dygnet.
REPORTED_BUDGET_KEY = "reported_daily_row_limit"


def remember_reported_budget(limit, kv=None):
    """Sparar det tak Primat själv rapporterade, så budgeten följer kontot.

    O8:s princip är att kvotens storlek ska komma från Primat och aldrig
    gissas. Den principen går inte att följa fullt ut här - vi måste kunna
    svara "räcker kvoten?" INNAN ett anrop skickas, och då finns inget färskt
    /me att fråga. Kompromissen: så fort driftkollen HAR läst ett tak ur
    Primats svar blir det talet budgeten, och vårt eget står kvar bara som
    utgångsläge tills dess."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return
    if limit <= 0:
        return
    store = _kv(kv)
    if store is None:
        return
    try:
        tidigare, _ = store.get(NAMESPACE, REPORTED_BUDGET_KEY)
        if tidigare != limit:
            logger.info("Primats rapporterade dygnstak: %d rader (var %s)", limit, tidigare)
        store.set(NAMESPACE, REPORTED_BUDGET_KEY, limit)
    except Exception:
        logger.exception("Kunde inte spara Primats rapporterade dygnstak")


def _reported_budget(kv=None):
    store = _kv(kv)
    if store is None:
        return None
    try:
        värde, _ = store.get(NAMESPACE, REPORTED_BUDGET_KEY)
        värde = int(värde)
    except Exception:
        return None
    return värde if värde > 0 else None


def daily_row_budget(kv=None) -> int:
    """Dygnskvoten i rader, i fallande turordning:

      1. PRIMAT_DAILY_ROW_BUDGET i miljön - en uttrycklig operatörsvilja
         vinner alltid, och är vägen att stänga ned förbrukningen utan deploy.
      2. Det tak Primat själv senast rapporterade (driftkollen läser /me).
      3. DEFAULT_DAILY_ROW_BUDGET, App-nivåns 100 000.

    Aldrig noll: en felskriven miljövariabel får inte tolkas som "kör inte
    alls"."""
    rått = (os.environ.get("PRIMAT_DAILY_ROW_BUDGET") or "").strip()
    if rått:
        if rått.isdigit() and int(rått) > 0:
            return int(rått)
        logger.warning("PRIMAT_DAILY_ROW_BUDGET är inte ett positivt tal (%r) - ignoreras", rått)
    return _reported_budget(kv) or DEFAULT_DAILY_ROW_BUDGET


def quota_day(now: float | None = None) -> str:
    """Kvotdygnets nyckel, "YYYY-MM-DD" i UTC.

    UTC och inte svensk tid, för det är Primats dygn vi håller reda på.
    Nyckeln byter alltså vid 02:00 svensk sommartid - samma sekund som kvoten
    faktiskt nollställs - i stället för vid midnatt hemma, tre timmar för
    tidigt."""
    stund = (datetime.fromtimestamp(now, timezone.utc) if now is not None
             else datetime.now(timezone.utc))
    return stund.strftime("%Y-%m-%d")


def _kv(kv=None):
    """KV-storen, eller None när den inte går att nå. Lat och guardad: den
    här modulen används från providers och skript som inte kan importera
    api_server."""
    if kv is not None:
        return kv
    try:
        from api_server import KV_CACHE
        return KV_CACHE
    except Exception:
        return None


def rows_spent(kv=None, now: float | None = None) -> int:
    """Rader vi vet att vi förbrukat under det pågående kvotdygnet."""
    store = _kv(kv)
    if store is None:
        return 0
    try:
        värde, _ = store.get(NAMESPACE, quota_day(now))
    except Exception:
        logger.exception("Kunde inte läsa radbokföringen")
        return 0
    try:
        return max(0, int(värde or 0))
    except (TypeError, ValueError):
        return 0


def book_rows(count: int, kv=None, now: float | None = None) -> int:
    """Bokför förbrukade rader och returnerar dygnets nya summa.

    Anropas MEDAN en körning pågår. Att vänta till slutet hade gjort
    bokföringen beroende av att körningen lyckas - och det är just de
    körningar som INTE lyckas (429, timeout, deploy mitt i) som kostat rader
    utan att lämna spår."""
    if count <= 0:
        return rows_spent(kv=kv, now=now)
    store = _kv(kv)
    if store is None:
        return 0
    dag = quota_day(now)
    try:
        nuvarande = rows_spent(kv=store, now=now)
        summa = nuvarande + int(count)
        store.set(NAMESPACE, dag, summa)
        return summa
    except Exception:
        # En bokföring som inte gick igenom får aldrig fälla en import. Den
        # gör oss blinda för just de raderna, och nästa kontroll blir för
        # optimistisk - men Primats egen 429 står kvar som sista spärr.
        logger.exception("Kunde inte bokföra %d förbrukade rader", count)
        return 0


def headroom(kv=None, now: float | None = None) -> int:
    """Rader kvar av dygnskvoten, aldrig negativt."""
    return max(0, daily_row_budget(kv) - rows_spent(kv=kv, now=now))


def can_start(kv=None, now: float | None = None, minimum: int | None = None) -> tuple[bool, str]:
    """(får starta, skäl). Skälet är till för loggen och adminvyn - det säger
    vad som mättes, aldrig vad vi antog i stället."""
    minimum = MIN_ROWS_TO_START if minimum is None else minimum
    kvar = headroom(kv=kv, now=now)
    tak = daily_row_budget(kv)
    if kvar >= minimum:
        return True, f"{kvar} rader kvar av {tak}"
    return False, (f"bara {kvar} rader kvar av dygnskvoten {tak} (minst {minimum} "
                   f"krävs för att en katalogimport ska hinna bli något) - kvoten "
                   f"nollställs midnatt UTC")


def status(kv=None, now: float | None = None) -> dict:
    """Bokföringen som den syns i adminvyn och driftkollen."""
    tak = daily_row_budget(kv)
    använt = rows_spent(kv=kv, now=now)
    return {
        "quotaDay": quota_day(now),
        "rowsSpent": använt,
        "dailyRowBudget": tak,
        "rowsLeft": max(0, tak - använt),
        "percentUsed": round(100 * använt / tak, 1) if tak else None,
        # Sagt rakt ut så ingen läser talet som Primats officiella siffra:
        # det här är vad VI har räknat, och det kan bara vara för lågt.
        "source": "Matjakts egen bokföring; Primats /me är facit",
    }
