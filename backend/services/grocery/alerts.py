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
#
# "failing" kom till med D4: senaste FÖRSÖKET misslyckades trots att det finns
# äldre godkänd data. Det larmet fanns inte alls förut, och det är just det
# fallet som var tystast - en natt som gav noll rader syntes inte förrän
# stale-gränsen passerats, ett och ett halvt dygn senare, och då bara som en
# varning. Ett trasigt nattjobb är rött från första natten.
CRITICAL_STATUSES = {"failed", "failing"}
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


def evaluate(panel, quota=None, backup=None, canaries=None):
    """Vilka problem som finns JUST NU, som en dict key -> beskrivning.

    Nyckeln identifierar problemet, inte tillfället: samma trasiga ICA-import
    två nätter i rad ger samma nyckel och därmed inget nytt mejl.
    """
    problem = {}
    for entry in panel or []:
        chain = entry.get("chain")
        health = entry.get("health") or {}
        status = health.get("status")
        if status == "failing":
            # Egen nyckel och egen text: det HÄR fallet är det som ser friskt
            # ut i varje annat fält. Produktantalet står kvar, åldern är
            # rimlig, kunderna får last-good - och kedjan uppdateras inte.
            problem[f"chain:{chain}:failing"] = {
                "severity": "critical", "chain": chain,
                "title": f"Matjakt — {chain} slutade uppdateras i natt",
                "body": (f"{chain}s senaste importförsök misslyckades. Kedjan har "
                         f"äldre godkänd data kvar, så varje annan siffra i panelen "
                         f"ser normal ut - men inga nya priser kommer in.\n\n"
                         f"Orsak: {_kort(health.get('reason'))}\n\n"
                         f"Användarna får senast godkända priser under tiden. Rättas "
                         f"inte importen blir de till slut för gamla för att serveras."),
            }
        elif status in CRITICAL_STATUSES:
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
    # D10. BACKUPEN SOM SLUTAT TAS.
    # Backupen var rätt byggd men helt oövervakad: åldern lästes bara av
    # backuptråden själv. En backup ingen tittar på är ett antagande, och
    # den dag den behövs är exakt fel dag att upptäcka att den slutade tas
    # för tre veckor sedan.
    if backup and not backup.get("ok"):
        problem["backup:stale"] = {
            "severity": "critical", "chain": None,
            "title": "Matjakt — säkerhetskopiorna har slutat tas",
            "body": (f"{backup.get('reason') or 'backupen ser inte frisk ut'}.\n\n"
                     f"Antal set på disken: {backup.get('sets')}. Backupen är det enda "
                     f"som står mellan en dålig migrering och alla konton, och den "
                     f"upptäcks annars först den dag den behövs.\n\n"
                     f"Kontrollera backuptråden i serverloggen och /api/health -> backup."),
        }
    # D10. KANARIEFÅGELN: en känd vara till ett känt pris, per kedja.
    # Radantal och medianpris svarar på "ser insamlingen normal ut?" utan att
    # någonsin titta på en vara någon känner igen. En kedja som byter
    # API-form kan fortsätta leverera tiotusen välformade rader - bara inte
    # rätt rader.
    for kanarie in canaries or []:
        if kanarie.get("ok") or not kanarie.get("configured"):
            continue
        kedja = kanarie.get("chain")
        problem[f"canary:{kedja}"] = {
            "severity": "warning", "chain": kedja,
            "title": f"Matjakt — kontrollvaran hos {kedja} ser fel ut",
            "body": (f"{_kort(kanarie.get('reason'))}\n\n"
                     f"Kontrollvaran är EN vara vi vet fanns, till ett pris vi vet "
                     f"ungefär vad det var. Ser den fel ut har något gått sönder "
                     f"mellan kedjans sida och vår databas - resten av katalogen kan "
                     f"se helt normal ut ändå.\n\n"
                     f"Kedjans priser är kvar och serveras; det här är en signal om "
                     f"att titta på insamlingen, inte ett skäl att kasta natten."),
        }
    return problem


# Primats /me-svar -> {"rowsUsedToday", "dailyRowLimit", "plan", "resetsAt"}
# eller None när fälten inte går att hitta.
#
# VARFÖR EN NORMALISERARE OCH INTE DIREKT UPPSLAG. Primats exakta fältnamn i
# GET /me är inte verifierade mot ett riktigt konto härifrån - nyckeln bor i
# Renders miljö och kommer aldrig in i den här processen under utveckling.
# Att gissa ett namn och tyst få None vore att visa "0 av 0 rader" som om det
# vore mätt. Därför prövas ett fåtal rimliga stavningar, och hittas ingen
# svarar funktionen None så att gränssnittet skriver "Ej tillgängligt" -
# precis det O8 kräver. Loggraden namnger vilka nycklar svaret FAKTISKT bar,
# så nästa person ser den riktiga formen utan att gissa en gång till.
# Siffror är inte hemligheter; nyckeln loggas aldrig.
ANVANDA_NYCKLAR = ("rowsUsedToday", "rows_used_today", "usedToday", "rowsUsed", "used")
TAK_NYCKLAR = ("dailyRowLimit", "daily_row_limit", "rowLimit", "dailyLimit", "limit", "quota")
PLAN_NYCKLAR = ("plan", "tier", "planName", "subscription")
RESET_NYCKLAR = ("resetsAt", "resets_at", "resetAt", "nextReset")


def _forsta(kalla, nycklar):
    for nyckel in nycklar:
        if isinstance(kalla, dict) and kalla.get(nyckel) is not None:
            return kalla[nyckel]
    return None


def quota_from_account_status(status):
    """Kvoten ur Primats eget svar, eller None när den inte finns där."""
    if not isinstance(status, dict):
        return None
    # Fälten kan ligga i roten eller under en nivå (data/account/usage/quota).
    kandidater = [status]
    for nyckel in ("data", "account", "usage", "quota"):
        if isinstance(status.get(nyckel), dict):
            kandidater.append(status[nyckel])
    for kalla in kandidater:
        anvant, tak = _forsta(kalla, ANVANDA_NYCKLAR), _forsta(kalla, TAK_NYCKLAR)
        if anvant is None or tak is None:
            continue
        try:
            anvant, tak = int(anvant), int(tak)
        except (TypeError, ValueError):
            continue
        if tak <= 0:
            continue
        # plan och reset söks i ALLA nivåer, inte bara den som bar kvoten:
        # ett vanligt svar har {"plan": "app", "usage": {...}}, alltså
        # planen i roten och siffrorna en nivå ner.
        plan = next((v for k in kandidater if (v := _forsta(k, PLAN_NYCKLAR)) is not None), None)
        reset = next((v for k in kandidater if (v := _forsta(k, RESET_NYCKLAR)) is not None), None)
        return {"rowsUsedToday": anvant, "dailyRowLimit": tak,
                "plan": plan, "resetsAt": reset}
    logger.info("Primats /me bar inga kvotfält vi känner igen; nycklar i svaret: %s",
                sorted(status)[:20])
    return None


def _state(kv, key):
    värde, _ = kv.get(NAMESPACE, key)
    return värde or None


# O6: historiken är en egen nyckel i samma namnrymd, avgränsad från de öppna
# incidenterna med ett prefix som inte kan vara en incidentnyckel.
HISTORY_KEY = "_history"
HISTORY_LIMIT = 50


def history(kv):
    värde, _ = kv.get(NAMESPACE, HISTORY_KEY)
    return list(värde or [])


def open_incidents(kv):
    """Öppna incidenter ur databasen: {key: post}. Historiknyckeln är inte en."""
    return {key: _state(kv, key) for key in (kv.keys(NAMESPACE) if hasattr(kv, "keys") else [])
            if key != HISTORY_KEY and _state(kv, key)}


def process(panel, kv, mail_config, quota=None, now=None, to_email=None,
            backup=None, canaries=None):
    """Jämför nuläget mot öppna incidenter och skickar det som faktiskt är nytt.

    TILLSTÅNDET ÄR SANNINGEN, MEJLET ÄR ETT KVITTO. Förut skrevs en incident
    bara om larmet gick att skicka (kv.set låg inuti if _skicka). Utan
    konfigurerad e-post spårades alltså ingen incident alls, och om
    återställningsmejlet misslyckades låg incidenten öppen för evigt. Nu
    skrivs incidenten oavsett, och mejlets öde står för sig: sent, failed,
    not_configured eller pending (ingen mottagare). Ingen JA-markering för
    ett försök som inte gick.

    Returnerar vad som gjordes, så nattjobbet kan logga det och testerna
    kontrollera det utan att läsa mejl.
    """
    now = now if now is not None else time.time()
    to_email = to_email if to_email is not None else admin_email()
    aktuella = evaluate(panel, quota=quota, backup=backup, canaries=canaries)
    öppna = open_incidents(kv)
    resultat = {"incidents": [], "recoveries": [], "suppressed": [], "skipped": []}

    for key, problem in sorted(aktuella.items()):
        tidigare = öppna.get(key)
        post = {
            "key": key, "chain": problem.get("chain"), "severity": problem["severity"],
            "title": problem["title"], "summary": _kort(problem["body"].split("\n")[0], 160),
            "openedAt": (tidigare or {}).get("openedAt", now), "lastSeenAt": now,
            "mail": (tidigare or {}).get("mail") or {"status": "pending", "lastAttemptAt": None, "lastSentAt": None},
            # Äldre poster hade bara lastSent; behåll så cooldownen inte nollas.
            "lastSent": (tidigare or {}).get("lastSent"),
        }
        if not to_email:
            # Utan mottagare uppdaterar vi ändå tillståndet, så att ett larm
            # inte sparas upp och exploderar den dag adressen sätts - och så
            # att incidenten SYNS i kontrollrummet även utan e-post.
            post["mail"] = {**post["mail"], "status": "pending"}
            kv.set(NAMESPACE, key, post)
            resultat["skipped"].append(key)
            continue
        # Cooldownen gäller bara ett larm som FAKTISKT gick ut. Ett misslyckat
        # försök har inget lastSent, och "lastSent or 0" hade tystat det i sju
        # dygn - testet för trasig SMTP fångade det. Försök igen nästa körning.
        if tidigare and tidigare.get("lastSent") and now - tidigare["lastSent"] < ALERT_COOLDOWN_SECONDS:
            kv.set(NAMESPACE, key, post)
            resultat["suppressed"].append(key)
            continue
        utfall = _skicka(mail_config, to_email, problem["title"], problem["body"], key)
        post["mail"] = {"status": utfall, "lastAttemptAt": now,
                        "lastSentAt": now if utfall == "sent" else post["mail"].get("lastSentAt")}
        if utfall == "sent":
            post["lastSent"] = now
        kv.set(NAMESPACE, key, post)
        if not tidigare or utfall == "sent":
            resultat["incidents"].append(key)

    for key in sorted(öppna):
        if key in aktuella:
            continue
        tidigare = öppna[key]
        timmar = round((now - (tidigare.get("openedAt") or now)) / 3600, 1)
        # Återställd är återställd: signalen är borta, alltså stängs
        # incidenten - oavsett om kvittot går att skicka. Mejlets öde skrivs
        # i historiken i stället för att hålla incidenten öppen.
        utfall = ("pending" if not to_email else
                  _skicka(mail_config, to_email, f"Matjakt — löst: {key}",
                          f"Problemet är borta igen efter {timmar} timmar.\n\n"
                          f"Ingen åtgärd behövs - det här mejlet är bara kvittot.", key))
        _arkivera(kv, tidigare, key, now, utfall)
        kv.delete(NAMESPACE, key)
        resultat["recoveries"].append(key)
    return resultat


def _arkivera(kv, post, key, now, recovery_mail):
    öppnad = post.get("openedAt") or now
    rad = {
        "key": key, "chain": post.get("chain"), "severity": post.get("severity"),
        "title": post.get("title"), "summary": post.get("summary"),
        "openedAt": öppnad, "recoveredAt": now, "durationSeconds": max(0, round(now - öppnad)),
        "mail": {"opened": (post.get("mail") or {}).get("status", "sent" if post.get("lastSent") else "pending"),
                 "recovered": recovery_mail},
    }
    hist = [rad] + history(kv)
    kv.set(NAMESPACE, HISTORY_KEY, hist[:HISTORY_LIMIT])


# O5: vad är fel, påverkas kunderna, vad behöver jag göra - per öppen incident.
#
# Kundpåverkan härleds ur det panelen faktiskt vet: om kedjan är släppt och
# hur gammal senaste lyckade import är, ställt mot serveringsregeln
# (MAX_STORE_PRICE_AGE_SECONDS: äldre butikspriser serveras inte). Vi
# påstår inte att kunder får ett snapshot - vi säger vad regeln ger vid den
# åldern, och "okänd" när underlaget saknas.
def overview(kv, panel, now=None):
    from .pricing import MAX_STORE_PRICE_AGE_SECONDS
    now = now if now is not None else time.time()
    per_kedja = {e.get("chain"): e for e in (panel or [])}
    aktiva = []
    for key, post in sorted(open_incidents(kv).items()):
        entry = per_kedja.get(post.get("chain")) or {}
        health = entry.get("health") or {}
        släppt = bool(health.get("released"))
        ålder_h = health.get("ageHours")
        if post.get("chain") is None:
            påverkan, åtgärd = "ingen direkt", "Se kvoten i O8; nästa import kan bli ofullständig"
        elif not släppt:
            påverkan = "ingen - kedjan är inte släppt"
            åtgärd = "Läs importfelet; ingen kund ser kedjan"
        elif ålder_h is None:
            påverkan = "okänd - ålder på senaste lyckade import saknas"
            åtgärd = "Kontrollera senaste körningen manuellt"
        elif ålder_h * 3600 < MAX_STORE_PRICE_AGE_SECONDS:
            påverkan = (f"kunder ser senast godkända priser, {ålder_h} h gamla - "
                        f"inom serveringsregeln ({MAX_STORE_PRICE_AGE_SECONDS // 86400} dygn)")
            åtgärd = "Rätta importen innan regeln slår till"
        else:
            påverkan = (f"KUNDPÅVERKAN: senaste godkända priser är {ålder_h} h gamla, "
                        f"över serveringsregeln - kedjan visas utan färska priser")
            åtgärd = "Starta import manuellt nu"
        aktiva.append({
            **post,
            "ageHours": round((now - (post.get("openedAt") or now)) / 3600, 1),
            "released": släppt,
            "lastAttempt": (entry.get("lastRun") or {}).get("status"),
            "vadArFel": post.get("summary") or post.get("title"),
            "paverkasKunder": påverkan,
            "vadGora": åtgärd,
        })
    return {"active": aktiva, "history": history(kv), "historyLimit": HISTORY_LIMIT,
            "cooldownSeconds": ALERT_COOLDOWN_SECONDS, "measuredAt": now}


def _skicka(mail_config, to_email, subject, body, key):
    """Skickar och säger SANNINGEN om hur det gick: "sent", "not_configured"
    eller "failed". Ett misslyckat försök får aldrig se ut som ett skickat."""
    try:
        send_email(mail_config, to_email, subject, body)
        return "sent"
    except MailNotConfigured:
        logger.warning("Larm %s kunde inte skickas: e-post är inte konfigurerat", key)
        return "not_configured"
    except Exception:
        # Ett trasigt larm får ALDRIG stoppa nattjobbet - då byter vi ut ett
        # driftproblem mot ett kundproblem.
        logger.exception("Larm %s kunde inte skickas", key)
        return "failed"
