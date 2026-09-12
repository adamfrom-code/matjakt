# -*- coding: utf-8 -*-
"""Söndagsnotisen (H1): söndag 17:00 Europe/Stockholm, en per konto.

Söndag 17 är den enda naturliga rytm produkten har. Veckan börjar i morgon,
handlingen sker i kväll eller i morgon bitti, och förslaget är redan klart -
det är hela notisens innehåll.

FYRA SPÄRRAR, I DEN ORDNING DE GÄLLER

  1. Nycklarna. Utan MATJAKT_VAPID_PUBLIC_KEY skickas ingenting, och det
     syns som `blocked_reason` - inte som ett undantag i loggen. Allt annat
     i servern fungerar oförändrat.
  2. Samtycke. `notification_prefs`: huvudbrytaren PÅ och "Ny vecka" (week)
     PÅ. Ett nej är permanent - det frågas inte igen nästa söndag, för det
     finns ingenting här som frågar.
  3. En gång. push_log har UNIQUE (user_id, kind, day) och platsen tas FÖRE
     avsändningen. En omstart 17:00:30 kör tick igen med tomt `_last_fired`
     och får noll mottagare tillbaka.
  4. Egna tal. "5 middagar för 4 personer" läses ur kontots synced_state.
     Går de inte att läsa skickas den generella texten - aldrig en siffra
     som låtsas vara någons.

Tidszonen är Europe/Stockholm av samma skäl som nattjobben och utskicken.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime

from ..household.notifications import PREF_WEEK
from .webpush import WebPushError, WebPushGone

try:
    from zoneinfo import ZoneInfo
    STOCKHOLM = ZoneInfo("Europe/Stockholm")
except Exception:  # pragma: no cover
    STOCKHOLM = None

logger = logging.getLogger("matjakt.push")

KIND = "sondagsnotis"
SEND_AT = "17:00"            # Europe/Stockholm
SEND_WEEKDAY = 6             # söndag (måndag = 0)
CHECK_INTERVAL_SECONDS = 30

TITLE = "Dags att planera veckan"
# Den generella varianten. Används när synced_state inte går att läsa, är
# tom, eller innehåller tal som inte kan vara sanna. Den säger exakt lika
# mycket som den andra minus siffrorna, och ljuger inte om något.
GENERIC_BODY = "Förslaget till veckan är redan klart."
# Vart ett tryck leder. `?notis=vecka` är inte en djuplänk till en vy - det
# är en uppmaning till appen att BYGGA veckan (app.js, chooseMenu).
DEEPLINK = "?notis=vecka"
# Samma tag varje söndag: webbläsaren ersätter en oläst notis i stället för
# att lägga en till. Andra försvaret mot dubbletter, efter push_log.
TAG = "matjakt-vecka"

# Vad appen själv tillåter (app-state.js): 1-12 personer, 1-7 middagar.
# Ett tal utanför dem är inte "användarens eget" utan skräp i blobben.
MAX_PERSONER = 12
MAX_MIDDAGAR = 7


def _now() -> datetime:
    return datetime.now(STOCKHOLM) if STOCKHOLM else datetime.now()


def _whole(value, high: int):
    """Ett heltal som kan vara en riktig inställning, annars None.

    Bool först: `True` är ett heltal i Python och hade blivit "1 middag"."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != int(value):
        return None
    number = int(value)
    return number if 1 <= number <= high else None


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one}" if count == 1 else f"{count} {many}"


def week_body(synced_state) -> str:
    """Notisens text ur ANVÄNDARENS egna tal.

    "5 middagar för 4 personer — förslaget är redan klart." Saknas något av
    talen faller HELA meningen tillbaka på den generella - halva sanningen
    ("5 middagar för några personer") är sämre än ingen siffra alls."""
    try:
        blob = json.loads(synced_state) if synced_state else {}
    except (TypeError, ValueError):
        blob = {}
    if not isinstance(blob, dict):
        return GENERIC_BODY
    middagar = _whole(blob.get("middagar"), MAX_MIDDAGAR)
    personer = _whole(blob.get("personer"), MAX_PERSONER)
    if middagar is None or personer is None:
        return GENERIC_BODY
    return (f"{_plural(middagar, 'middag', 'middagar')} för "
            f"{_plural(personer, 'person', 'personer')} — förslaget är redan klart.")


def week_notification(synced_state, app_url: str = "") -> dict:
    """Nyttolasten service workern får. Håll den liten: den krypteras och
    varje push-tjänst har ett tak (4 kB är det lägsta som garanteras)."""
    return {
        "title": TITLE,
        "body": week_body(synced_state),
        "url": f"{(app_url or '').rstrip('/')}/{DEEPLINK}" if app_url else DEEPLINK,
        "tag": TAG,
        "kind": KIND,
    }


class WeeklyPushScheduler:
    """Timertråd som söndag 17:00 skickar en notis till varje konto som har
    en prenumeration OCH har veckonotiser påslagna."""

    def __init__(self, store, sender, notifications, *, app_url: str = "",
                 pause_seconds: float = 0.05):
        self.store = store
        self.sender = sender
        self.notifications = notifications
        self.app_url = (app_url or "").rstrip("/")
        self.pause_seconds = pause_seconds
        self._stop = threading.Event()
        self._thread = None
        self._last_fired = None
        self._lock = threading.Lock()
        self.last_run = None

    # -- drift --
    def blocked_reason(self):
        return self.sender.blocked_reason()

    def status(self) -> dict:
        return {
            "skickasKl": SEND_AT, "dag": "söndag", "timezone": "Europe/Stockholm",
            "blockerat": self.blocked_reason(),
            "prenumeranter": self.store.count(),
            "senasteKorning": self.last_run,
            "skickadeSenaste30Dagarna": self.store.counts(30).get(KIND, 0),
        }

    def start(self):
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="matjakt-veckonotis", daemon=True)
        self._thread.start()
        # info, inte error: att notisen är avstängd för att nycklarna inte
        # finns är ett tillstånd, inte ett fel. Ett larm här hade lärt en
        # driftansvarig att loggens larm inte betyder något.
        logger.info("Veckonotisen startad (%s)", self.blocked_reason() or "aktiv")

    def stop(self):
        self._stop.set()

    def _loop(self):  # pragma: no cover - trådens egen slinga
        while not self._stop.wait(CHECK_INTERVAL_SECONDS):
            try:
                self._tick()
            except Exception:
                logger.exception("Veckonotisens tick misslyckades")

    def _tick(self, now=None):
        now = now or _now()
        stamp = now.strftime("%Y-%m-%d")
        if now.weekday() != SEND_WEEKDAY or now.strftime("%H:%M") != SEND_AT:
            return
        if self._last_fired == stamp:
            return
        self._last_fired = stamp
        self.run_due(now)

    # -- körning --
    def run_due(self, now=None) -> dict:
        now = now or _now()
        today = now.date()
        reason = self.blocked_reason()
        summary = {"dag": today.isoformat(), "blockerat": reason, "skickat": 0,
                   "utanSamtycke": 0, "redanSkickat": 0, "fel": 0, "borttagna": 0}
        if reason:
            self.last_run = summary
            return summary
        with self._lock:
            for row in self.store.recipients(KIND, today):
                user_id = row["id"]
                # Spärr 2 före spärr 3: den som tackat nej ska inte ens ta en
                # plats i loggen. Annars hade ett senare ja samma dag mötts av
                # "redan skickat" för en notis som aldrig gick ut.
                if not self.notifications.wants(user_id, PREF_WEEK):
                    summary["utanSamtycke"] += 1
                    continue
                if not self.store.claim(user_id, KIND, today):
                    summary["redanSkickat"] += 1
                    continue
                self._send_to(user_id, row["synced_state"], today, summary)
                if self.pause_seconds:
                    time.sleep(self.pause_seconds)
        self.last_run = summary
        logger.info("Veckonotisen klar: %s", summary)
        return summary

    def _send_to(self, user_id, synced_state, today, summary):
        payload = json.dumps(week_notification(synced_state, self.app_url), ensure_ascii=False)
        devices = self.store.subscriptions_for(user_id)
        if not devices:
            # Kontot hann avsluta mellan frågan och utskicket. Ingen notis
            # gick ut, så platsen i loggen ska tillbaka.
            self.store.release(user_id, KIND, today)
            return
        delivered = False
        for device in devices:
            try:
                self.sender.send(device, payload)
                delivered = True
            except WebPushGone:
                self.store.drop_endpoint(device["endpoint"])
                summary["borttagna"] += 1
            except WebPushError as error:
                logger.warning("Veckonotisen till konto %s gick inte fram: %s", user_id, error)
            except Exception:
                logger.exception("Veckonotisen till konto %s kraschade", user_id)
        if delivered:
            summary["skickat"] += 1
        else:
            # Platsen behålls med flit. En notis som inte kom fram får
            # utebli; en som kommer två gånger är värre.
            summary["fel"] += 1
