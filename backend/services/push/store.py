# -*- coding: utf-8 -*-
"""Prenumerationer och utskickslogg för Web Push.

Två tabeller i KONTOdatabasen, på samma anslutning och under samma lås som
AccountStore - precis som mail_log (services/mailings.py). Det är med avsikt:
mottagarfrågan behöver `users.synced_state` för att kunna skriva
användarens EGNA tal i notisen, och en join över två filer finns inte.

  push_subscriptions   en rad per webbläsare/telefon som sagt ja
  push_log             en rad per (konto, sort, dag) - GARANTIN för "en gång"

VARFÖR ENDPOINTEN LIGGER I KLARTEXT OCH ENHETSTOKEN INTE GÖR DET.
services/household/notifications.py lagrar sin push-token hashad, och det är
rätt där: den används bara för att känna igen en enhet. En Web
Push-prenumeration är något annat - den ÄR adressen servern måste POSTa till,
plus de två nycklar meddelandet krypteras med. En hash går inte att skicka
till. Därför: endpointen lagras som den är, `endpoint_hash` finns bara som
unik nyckel (en endpoint kan vara 2 000 tecken lång och duger illa som
index), och raden städas bort i samma tre lägen som allt annat privat -
utloggning, raderat konto, och när push-tjänsten själv svarar 404/410.
"""

from __future__ import annotations

import functools
import hashlib
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

# Vad en prenumeration får se ut som. Grovt tilltagna gränser - endpointer
# från FCM, Mozilla och Apple ser helt olika ut - men inte obegränsade: en
# rad som inte kan vara en riktig prenumeration ska avvisas i vägen in, inte
# upptäckas som ett konstigt fel en söndag klockan 17.
MAX_ENDPOINT_LENGTH = 2048
MIN_ENDPOINT_LENGTH = 16
MAX_KEY_LENGTH = 200
PLATFORMS = ("web", "ios", "android")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def endpoint_key(endpoint: str) -> str:
    return hashlib.sha256((endpoint or "").encode("utf-8")).hexdigest()


class PushStore:
    def __init__(self, connection: sqlite3.Connection, lock=None):
        self._connection = connection
        self._lock = lock if lock is not None else threading.RLock()
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                endpoint_hash TEXT NOT NULL UNIQUE,
                endpoint TEXT NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT 'web',
                created_at TEXT NOT NULL,
                last_seen_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_push_subs_user ON push_subscriptions(user_id);
            CREATE TABLE IF NOT EXISTS push_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                day TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE (user_id, kind, day)
            );
            """
        )
        self._connection.commit()

    # ---- prenumerationer -------------------------------------------------

    def subscribe(self, user_id, subscription: dict, platform: str = "web") -> dict:
        """PushSubscription.toJSON() från webbläsaren, rakt in.

        Samma webbläsare, nytt konto: raden BYTER ägare, av samma skäl som
        register_device i household/notifications.py - annars fortsatte förra
        användarens veckonotiser till en telefon som bytt händer."""
        endpoint, p256dh, auth = _validate(subscription)
        platform = platform if platform in PLATFORMS else "web"
        now = _iso(_now())
        with self._connection:
            self._connection.execute(
                """INSERT INTO push_subscriptions
                       (user_id, endpoint_hash, endpoint, p256dh, auth, platform, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(endpoint_hash) DO UPDATE SET
                       user_id = excluded.user_id, p256dh = excluded.p256dh,
                       auth = excluded.auth, platform = excluded.platform,
                       last_seen_at = excluded.last_seen_at""",
                (int(user_id), endpoint_key(endpoint), endpoint, p256dh, auth, platform, now, now))
        return {"ok": True, "platform": platform}

    def unsubscribe(self, endpoint: str, user_id=None) -> None:
        """Bara ägaren får glömma sin egen prenumeration. En endpoint som
        råkat läcka ska inte kunna tysta någon annans notiser."""
        if user_id is None:
            return
        with self._connection:
            self._connection.execute(
                "DELETE FROM push_subscriptions WHERE endpoint_hash = ? AND user_id = ?",
                (endpoint_key(endpoint), int(user_id)))

    def drop_endpoint(self, endpoint: str) -> None:
        """Push-tjänsten svarade 404/410: prenumerationen finns inte längre.
        Utan den här raden hade varje söndag i all framtid räknat ett fel för
        en webbläsare som avinstallerats."""
        with self._connection:
            self._connection.execute("DELETE FROM push_subscriptions WHERE endpoint_hash = ?",
                                     (endpoint_key(endpoint),))

    def forget_user(self, user_id) -> None:
        with self._connection:
            self._connection.execute("DELETE FROM push_subscriptions WHERE user_id = ?", (int(user_id),))
            self._connection.execute("DELETE FROM push_log WHERE user_id = ?", (int(user_id),))

    def subscriptions_for(self, user_id) -> list[dict]:
        rows = self._connection.execute(
            "SELECT endpoint, p256dh, auth, platform FROM push_subscriptions WHERE user_id = ? ORDER BY id",
            (int(user_id),)).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM push_subscriptions").fetchone()
        return int(row["n"] if row else 0)

    # ---- utskickslogg ----------------------------------------------------

    def recipients(self, kind: str, today) -> list:
        """Konton med minst en prenumeration som inte redan fått `kind` i dag.

        SAMTYCKET PRÖVAS INTE HÄR. notification_prefs ligger på en annan
        anslutning (household/notifications.py) och frågan ställs av
        schemaläggaren, en gång per konto - se schedule.py."""
        return self._connection.execute(
            """SELECT u.id AS id, u.email AS email, u.synced_state AS synced_state
                 FROM users u
                WHERE EXISTS (SELECT 1 FROM push_subscriptions s WHERE s.user_id = u.id)
                  AND NOT EXISTS (SELECT 1 FROM push_log l
                                   WHERE l.user_id = u.id AND l.kind = ? AND l.day = ?)
                ORDER BY u.id""", (kind, today.isoformat())).fetchall()

    def claim(self, user_id, kind: str, today) -> bool:
        """Tar dagens plats för kontot. True bara för den FÖRSTA som frågar.

        Det här är hela garantin för "en notis per söndag och konto", och den
        ligger i databasen - inte i en variabel i processen. `_last_fired` i
        schemaläggaren nollställs av en omstart; UNIQUE (user_id, kind, day)
        gör det inte.

        Platsen tas FÖRE avsändningen, till skillnad från mail_log som loggar
        efter. Skillnaden spelar roll precis en gång: när servern dör mitt i
        utskicket. Ett mejl som inte kom fram får komma i morgon; en notis som
        kommer två gånger är den sortens skäl folk stänger av notiser för."""
        with self._connection:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO push_log (user_id, kind, day, sent_at) VALUES (?, ?, ?, ?)",
                (int(user_id), kind, today.isoformat(), _iso(_now())))
        return cursor.rowcount == 1

    def release(self, user_id, kind: str, today) -> None:
        """Ångrar en claim. Används bara när avsändningen aldrig ens
        försöktes (ingen prenumeration kvar) - inte när den misslyckades."""
        with self._connection:
            self._connection.execute(
                "DELETE FROM push_log WHERE user_id = ? AND kind = ? AND day = ?",
                (int(user_id), kind, today.isoformat()))

    def counts(self, days: int = 30) -> dict:
        since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
        return {kind: int(count) for kind, count in self._connection.execute(
            "SELECT kind, COUNT(*) FROM push_log WHERE day >= ? GROUP BY kind", (since,))}


def _validate(subscription) -> tuple[str, str, str]:
    if not isinstance(subscription, dict):
        raise ValueError("Ogiltig prenumeration")
    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") if isinstance(subscription.get("keys"), dict) else {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not (MIN_ENDPOINT_LENGTH <= len(endpoint) <= MAX_ENDPOINT_LENGTH):
        raise ValueError("Ogiltig prenumeration")
    # https eller ingenting: en push-endpoint över klartext hade läckt
    # innehållet i varje notis till nätet den reste över.
    if not endpoint.startswith("https://"):
        raise ValueError("Prenumerationen måste vara https")
    if not p256dh or not auth or len(p256dh) > MAX_KEY_LENGTH or len(auth) > MAX_KEY_LENGTH:
        raise ValueError("Prenumerationen saknar nycklar")
    return endpoint, p256dh, auth


def _synchronized(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


for _name, _member in list(vars(PushStore).items()):
    if callable(_member) and not _name.startswith("_"):
        setattr(PushStore, _name, _synchronized(_member))
