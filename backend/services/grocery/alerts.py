# -*- coding: utf-8 -*-
"""Driftlarm för prisinsamlingen: ett mejl när något går sönder, ett när det
är lagat, och tystnad däremellan.

VARFÖR DEN HÄR FINNS. Ägaren ska inte behöva öppna en adminpanel varje dag
för att upptäcka att ICA slutat uppdatera. En frisk natt ska vara tyst; en
trasig natt ska höras EN gång.

DEDUPERING ÄR HELA POANGEN. Ett jobb som misslyckas varje natt får inte ge
ett mejl per natt - efter några dagar läser man dem inte längre, och då är
larmet värdelöst precis när det behövs. Modellen är därför:

    första gången ett problem ses   -> ett incidentmejl
    så länge det kvarstår           -> tystnad
    när det är borta                -> ett recoverymejl
    om det återkommer efteråt       -> nytt incidentmejl

Tillståndet ligger i KeyValueCacheStore, inte i minnet: en omstart mitt i en
pågående incident får inte återställa räknaren och skicka om larmet.

ALDRIG ETT LARM SOM ÄR ETT KUNDPROBLEM. Att en natt misslyckas är ett
driftproblem - användarna får last-good-data under tiden (se publish.py).
Larmet säger därför vad som hände och hur gammal datan är, inte att appen
är nere.

INGA HEMLIGHETER I MEJLET. Varken API-nycklar, tokens eller mejladresser
utöver mottagaren själv. Felmeddelanden från providers kan innehålla URL:er
med parametrar, så de kortas.
"""

import logging
import os
import re
import time

from ..email.mailer import MailNotConfigured, send_email

logger = logging.getLogger("matjakt.grocery.alerts")

NAMESPACE = "ops_incident"

# Hur länge ett kvarstående problem tigers ihjäl innan det får larma igen.
# Sätts inte till "aldrig": ett fel som pågått i en vecka förtjänar en
# påminnelse, men inte en per natt.
ALERT_COOLDOWN_SECONDS = 7 * 24 * 3600

# Fel som betyder att kedjan inte uppdateras alls. Röda.
CRITICAL_STATUSES = {"failed"}
# Fel som betyder att den uppdateras för sällan. Orange.
WARNING_STATUSES = {"stale"}

# Primats dygnskvot: larma innan den tar slut, inte efteråt.
QUOTA_WARN_FRACTION = 0.85


def admin_email():
    """Mottagaren. Saknas den skickas ingenting - larm utan adress ska vara
    tyst, inte krascha nattjobbet."""
    return (os.environ.get("MATJAKT_ADMIN_EMAIL") or "").strip()


# En URL i ett providerfel kan bära nyckeln i query-strängen - "401 from
# https://primat.nu/api/v3?key=..." är precis så ett felmeddelande ser ut.
# Frågetecknet och allt efter det stryks därför innan texten når ett mejl.
# Sökvägen behålls: den säger vilket anrop som sprack, vilket är hela
# nyttan med att ta med felet alls.
_QUERY_I_URL = re.compile(r"(https?://[^\s?]+)\?\S*")


def _kort(text, gräns=200):
    """Felmeddelandet, utan hemligheter och utan att svämma över mejlet."""
    text = _QUERY_I_URL.sub(r"\1?…", str(text or "").strip())
    return text if len(text) <= gräns else text[:gräns - 1] + "…"


def evaluate(panel, quota=None):
    """Vilka problem som finns JUST NU, som en dict key -> beskrivning.

    Nyckeln identifierar problemet, inte tillfället: samma trasiga ICA-import
    två nätter i rad ger samma nyckel och därmed inget nytt mejl.
    """
    problem = {}
    for entry in panel or []:
        chain = entry.get("chain")
        health = entry.get("health") or {}
        status = health.get("status")
        if status in CRITICAL_STATUSES:
            problem[f"chain:{chain}:failed"] = {
                "severity": "critical", "chain": chain,
                "title": f"Matjakt — {chain} importerar inte",
                "body": (f"{chain} misslyckas med sin import och har ingen tidigare "
                         f"lyckad körning att falla tillbaka på.\n\n"
                         f"Orsak: {_kort(health.get('reason'))}"),
            }
        elif status in WARNING_STATUSES:
            problem[f"chain:{chain}:stale"] = {
                "severity": "warning", "chain": chain,
                "title": f"Matjakt — {chain} har inte uppdaterats",
                "body": (f"{chain} har inte fått en lyckad import på "
                         f"{health.get('ageHours')} timmar.\n\n"
                         f"Användarna får fortfarande senaste godkända priser - "
                         f"det här är ett driftproblem, inte ett kundproblem."),
            }
    if quota:
        använt, tak = quota.get("rowsUsedToday"), quota.get("dailyRowLimit")
        if använt is not None and tak:
            if använt >= tak * QUOTA_WARN_FRACTION:
                problem["primat:quota"] = {
                    "severity": "warning", "chain": None,
                    "title": "Matjakt — Primats dygnskvot närmar sig taket",
                    "body": (f"{använt} av {tak} rader förbrukade i dag "
                             f"({round(100 * använt / tak)} %).\n\n"
                             f"Slår kvoten i taket avbryts hämtningen ärligt och "
                             f"det som hunnit hämtas behålls - men täckningen "
                             f"byggs då upp över flera nätter i stället för en."),
                }
    return problem


def _state(kv, key):
    värde, _ = kv.get(NAMESPACE, key)
    return värde or None


def process(panel, kv, mail_config, quota=None, now=None, to_email=None):
    """Jämför nuläget mot öppna incidenter och skickar det som faktiskt är nytt.

    Returnerar vad som gjordes, så nattjobbet kan logga det och testerna
    kontrollera det utan att läsa mejl.
    """
    now = now if now is not None else time.time()
    to_email = to_email if to_email is not None else admin_email()
    aktuella = evaluate(panel, quota=quota)
    öppna = {key for key in (kv.keys(NAMESPACE) if hasattr(kv, "keys") else [])}
    resultat = {"incidents": [], "recoveries": [], "suppressed": [], "skipped": []}

    if not to_email:
        # Utan mottagare uppdaterar vi ändå tillståndet, så att ett larm inte
        # sparas upp och exploderar den dag adressen sätts.
        resultat["skipped"] = sorted(aktuella)
        return resultat

    for key, problem in sorted(aktuella.items()):
        tidigare = _state(kv, key)
        if tidigare and now - (tidigare.get("lastSent") or 0) < ALERT_COOLDOWN_SECONDS:
            resultat["suppressed"].append(key)
            continue
        if _skicka(mail_config, to_email, problem["title"], problem["body"], key):
            kv.set(NAMESPACE, key, {"openedAt": (tidigare or {}).get("openedAt", now),
                                    "lastSent": now, "severity": problem["severity"]})
            resultat["incidents"].append(key)

    for key in sorted(öppna):
        if key in aktuella:
            continue
        tidigare = _state(kv, key)
        if not tidigare:
            continue
        timmar = round((now - (tidigare.get("openedAt") or now)) / 3600, 1)
        if _skicka(mail_config, to_email, f"Matjakt — löst: {key}",
                   f"Problemet är borta igen efter {timmar} timmar.\n\n"
                   f"Ingen åtgärd behövs - det här mejlet är bara kvittot.", key):
            kv.delete(NAMESPACE, key)
            resultat["recoveries"].append(key)
    return resultat


def _skicka(mail_config, to_email, subject, body, key):
    try:
        send_email(mail_config, to_email, subject, body)
        return True
    except MailNotConfigured:
        logger.warning("Larm %s kunde inte skickas: e-post är inte konfigurerat", key)
    except Exception:
        # Ett trasigt larm får ALDRIG stoppa nattjobbet - då byter vi ut ett
        # driftproblem mot ett kundproblem.
        logger.exception("Larm %s kunde inte skickas", key)
    return False
