# -*- coding: utf-8 -*-
"""ETT händelselager för hushållsnotiser - PWA idag, Capacitor/iOS/Android sen.

Poängen med att lägga det här i backend i stället för i klienten: appen ska
aldrig behöva två notissystem. Backend tar emot en händelse
(`household.shopping_item_added`), avgör VEM som ska veta, formulerar den
korta svenska texten och lägger den i en utkorg. Vilken transport som sedan
tömmer utkorgen - hämtning i appen idag, APNs/FCM när push är produktionsklart
- är ett byte av leveranssteg, inte en ny modell.

TRE REGLER SOM GÖR SKILLNAD PÅ NOTIS OCH SPAM

1. Aldrig till den som gjorde ändringen. Man behöver inte få veta att man
   själv lade mjölk i listan.
2. Debounce + gruppering. Tio varor på tjugo sekunder blir EN rad: "Sara lade
   till 10 varor i inköpslistan". Utkorgsraden ligger kvar och räknar upp tills
   det varit tyst i DEBOUNCE_SECONDS.
3. Användaren bestämmer. Varje kategori kan stängas av, och allt kan stängas
   av på en gång.

SÄKERHET
En utkorgsrad hör till EN användare och skapas bara för medlemmar i hushållet
när händelsen inträffar. Vid utloggning glöms enhetens token (device_forget),
vid lämnat hushåll städas köade rader bort - annars kunde en gammal telefon
fortsätta plinga om en familj den inte längre tillhör.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..data_guard import guard_database_path

# Hur länge en gruppérbar händelse väntar på fler av samma sort innan den
# skickas. Tjugo sekunder är lagom: tillräckligt för att fånga någon som
# betar av en lista, för kort för att kännas fördröjt.
DEBOUNCE_SECONDS = 20
# Kategorierna användaren kan slå av/på (Konto → Hushåll → Notiser).
PREF_WEEK = "week"                  # ny vecka / veckan är klar
PREF_SHOPPING = "shopping"          # ändringar i inköpslistan
PREF_PLAN = "plan"                  # ändringar i veckoplaneringen
PREF_INVENTORY = "inventory"        # skafferi/kyl/frys
PREF_PRICE = "price"                # prisbevakningar
PREF_ALL = "all"                    # huvudbrytaren
PREFERENCES = (PREF_WEEK, PREF_SHOPPING, PREF_PLAN, PREF_INVENTORY, PREF_PRICE)

# Händelsetyp -> (inställning, deeplink, grupperbar)
EVENT_RULES = {
    "household.shopping_item_added": (PREF_SHOPPING, "/handla", True),
    "household.shopping_item_purchased": (PREF_SHOPPING, "/handla", True),
    "household.shopping_item_at_home": (PREF_INVENTORY, "/skafferi", True),
    "household.inventory_changed": (PREF_INVENTORY, "/skafferi", True),
    "household.week_changed": (PREF_PLAN, "/vecka", True),
    "household.week_ready": (PREF_WEEK, "/vecka", False),
    # Ingen av de fem kategorierna: att någon gått med i hushållet är sällan
    # och viktigt, och att gömma det bakom "Ny vecka" hade tyst tystat det
    # för den som bara ville slippa veckopåminnelser. Bara huvudbrytaren
    # stänger av den.
    "household.member_joined": (PREF_ALL, "/konto", False),
    "household.price_drop": (PREF_PRICE, "/handla", False),
}

MAX_OUTBOX_PER_USER = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _device_key(token: str) -> str:
    """Push-token lagras hashad. En enhetstoken är adressen till någons
    telefon - lika lite som sessionstokens har den i klartext i en databas."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one}" if count == 1 else f"{count} {many}"


class NotificationStore:
    def __init__(self, db_path: Path):
        guard_database_path(db_path, purpose="notisdatabasen")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        self._init_schema()

    def close(self):
        self._connection.close()

    def _init_schema(self):
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS notification_prefs (
                user_id INTEGER NOT NULL,
                pref TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (user_id, pref)
            );
            CREATE TABLE IF NOT EXISTS push_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                platform TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_devices_user ON push_devices(user_id);
            CREATE TABLE IF NOT EXISTS notification_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                household_id INTEGER,
                kind TEXT NOT NULL,
                pref TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                deeplink TEXT,
                group_key TEXT,
                count INTEGER NOT NULL DEFAULT 1,
                actor_name TEXT,
                created_at TEXT NOT NULL,
                send_after TEXT NOT NULL,
                sent_at TEXT,
                read_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_user ON notification_outbox(user_id, id);
            CREATE INDEX IF NOT EXISTS idx_outbox_group ON notification_outbox(group_key);
            """
        )
        self._connection.commit()

    # ---- inställningar ---------------------------------------------------

    def preferences(self, user_id) -> dict:
        rows = self._connection.execute(
            "SELECT pref, enabled FROM notification_prefs WHERE user_id = ?", (int(user_id),)).fetchall()
        stored = {row["pref"]: bool(row["enabled"]) for row in rows}
        # Allt på som standard: en familj som just gått med ska märka att
        # appen är gemensam. Den som tycker det plingar för mycket stänger av.
        prefs = {pref: stored.get(pref, True) for pref in PREFERENCES}
        prefs[PREF_ALL] = stored.get(PREF_ALL, True)
        return prefs

    def set_preferences(self, user_id, values: dict) -> dict:
        with self._lock:
            for pref, enabled in (values or {}).items():
                if pref not in PREFERENCES and pref != PREF_ALL:
                    continue
                self._connection.execute(
                    """INSERT INTO notification_prefs (user_id, pref, enabled) VALUES (?, ?, ?)
                       ON CONFLICT(user_id, pref) DO UPDATE SET enabled = excluded.enabled""",
                    (int(user_id), pref, 1 if enabled else 0))
            self._connection.commit()
        return self.preferences(user_id)

    def wants(self, user_id, pref: str) -> bool:
        prefs = self.preferences(user_id)
        return bool(prefs.get(PREF_ALL, True)) and bool(prefs.get(pref, True))

    # ---- enheter ---------------------------------------------------------

    def register_device(self, user_id, token: str, platform: str = "web") -> dict:
        token = (token or "").strip()
        if len(token) < 16 or len(token) > 512:
            raise ValueError("Ogiltig enhetstoken")
        platform = platform if platform in ("web", "ios", "android") else "web"
        with self._lock:
            # Samma enhet, nytt konto: raden BYTER ägare. Utan det fortsatte
            # den gamla användarens hushållsnotiser till telefonen efter att
            # någon annan loggat in på den.
            self._connection.execute(
                """INSERT INTO push_devices (user_id, token_hash, platform, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(token_hash) DO UPDATE SET
                       user_id = excluded.user_id, platform = excluded.platform,
                       last_seen_at = excluded.last_seen_at""",
                (int(user_id), _device_key(token), platform, _iso(_now()), _iso(_now())))
            self._connection.commit()
        return {"ok": True, "platform": platform}

    def forget_device(self, token: str, user_id=None):
        """Vid utloggning. Enheten ska inte fortsätta ta emot privata
        hushållsnotiser från kontot som lämnat telefonen. Bara ägaren får
        glömma sin enhet - en token som råkat läcka ska inte kunna tysta
        någon annans notiser."""
        with self._lock:
            if user_id is None:
                return
            self._connection.execute("DELETE FROM push_devices WHERE token_hash = ? AND user_id = ?",
                                     (_device_key(token), int(user_id)))
            self._connection.commit()

    def forget_user_devices(self, user_id):
        with self._lock:
            self._connection.execute("DELETE FROM push_devices WHERE user_id = ?", (int(user_id),))
            self._connection.commit()

    def devices_for(self, user_id) -> list[dict]:
        rows = self._connection.execute(
            "SELECT platform, created_at, last_seen_at FROM push_devices WHERE user_id = ?",
            (int(user_id),)).fetchall()
        return [dict(row) for row in rows]

    # ---- utkorgen --------------------------------------------------------

    def publish(self, *, event_type: str, household_id, actor_user_id, recipient_ids,
                actor_name: str | None = None, subject: str | None = None,
                extra: dict | None = None) -> int:
        """Lägger händelsen i utkorgen för alla som ska ha den.

        Returnerar antalet mottagare som faktiskt fick en rad - noll är ett
        fullt giltigt svar (ensam i hushållet, alla har stängt av)."""
        rule = EVENT_RULES.get(event_type)
        if not rule:
            return 0
        pref, deeplink, groupable = rule
        actor_user_id = None if actor_user_id is None else int(actor_user_id)
        created = 0
        with self._lock:
            for user_id in recipient_ids or []:
                user_id = int(user_id)
                if actor_user_id is not None and user_id == actor_user_id:
                    continue          # regel 1: aldrig sin egen ändring
                if not self.wants(user_id, pref):
                    continue          # regel 3: användaren bestämmer
                if self._merge_or_insert(user_id, household_id, event_type, pref, deeplink,
                                         groupable, actor_name, subject, extra):
                    created += 1
            self._connection.commit()
        return created

    def _merge_or_insert(self, user_id, household_id, event_type, pref, deeplink,
                         groupable, actor_name, subject, extra) -> bool:
        now = _now()
        group_key = None
        if groupable:
            group_key = f"{household_id}:{event_type}:{user_id}:{actor_name or ''}"
            pending = self._connection.execute(
                "SELECT * FROM notification_outbox WHERE group_key = ? AND sent_at IS NULL ORDER BY id DESC LIMIT 1",
                (group_key,)).fetchone()
            if pending:
                # Regel 2: samma sort igen inom fönstret -> räkna upp och
                # skjut fram avsändningen i stället för att skapa en ny rad.
                count = pending["count"] + 1
                title, body = _render(event_type, actor_name, subject, count, extra)
                self._connection.execute(
                    "UPDATE notification_outbox SET count = ?, title = ?, body = ?, send_after = ? WHERE id = ?",
                    (count, title, body, _iso(now + timedelta(seconds=DEBOUNCE_SECONDS)), pending["id"]))
                return False
        title, body = _render(event_type, actor_name, subject, 1, extra)
        send_after = now + timedelta(seconds=DEBOUNCE_SECONDS if groupable else 0)
        self._connection.execute(
            """INSERT INTO notification_outbox
               (user_id, household_id, kind, pref, title, body, deeplink, group_key,
                count, actor_name, created_at, send_after)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (user_id, None if household_id is None else int(household_id), event_type, pref,
             title, body, deeplink, group_key, actor_name, _iso(now), _iso(send_after)))
        self._connection.execute(
            """DELETE FROM notification_outbox WHERE user_id = ? AND id NOT IN (
                   SELECT id FROM notification_outbox WHERE user_id = ? ORDER BY id DESC LIMIT ?)""",
            (user_id, user_id, MAX_OUTBOX_PER_USER))
        return True

    def due(self, user_id, *, mark_sent=True) -> list[dict]:
        """Notiser som passerat sitt debounce-fönster.

        Det här är LEVERANSGRÄNSEN. Idag hämtar appen dem själv och visar dem
        i gränssnittet; när APNs/FCM finns är det samma funktion som matar
        push-avsändaren. Ingen ny modell krävs för det bytet."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM notification_outbox WHERE user_id = ? AND sent_at IS NULL AND send_after <= ? ORDER BY id",
                (int(user_id), _iso(_now()))).fetchall()
            if mark_sent and rows:
                self._connection.executemany(
                    "UPDATE notification_outbox SET sent_at = ? WHERE id = ?",
                    [(_iso(_now()), row["id"]) for row in rows])
                self._connection.commit()
        return [_outbox_to_public(row) for row in rows]

    def pending_count(self, user_id) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM notification_outbox WHERE user_id = ? AND sent_at IS NULL",
            (int(user_id),)).fetchone()
        return row["n"] if row else 0

    def history(self, user_id, limit: int = 20) -> list[dict]:
        rows = self._connection.execute(
            "SELECT * FROM notification_outbox WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (int(user_id), max(1, min(100, int(limit or 20))))).fetchall()
        return [_outbox_to_public(row) for row in rows]

    def forget_household(self, user_id, household_id):
        """Någon lämnade (eller togs bort ur) ett hushåll: köade notiser om det
        hushållet ska inte nå fram efteråt."""
        with self._lock:
            self._connection.execute(
                "DELETE FROM notification_outbox WHERE user_id = ? AND household_id = ? AND sent_at IS NULL",
                (int(user_id), int(household_id)))
            self._connection.commit()

    def forget_user(self, user_id):
        with self._lock:
            self._connection.execute("DELETE FROM notification_outbox WHERE user_id = ?", (int(user_id),))
            self._connection.execute("DELETE FROM push_devices WHERE user_id = ?", (int(user_id),))
            self._connection.execute("DELETE FROM notification_prefs WHERE user_id = ?", (int(user_id),))
            self._connection.commit()


def _who(actor_name: str | None) -> str:
    return actor_name or "Någon i hushållet"


def _render(event_type: str, actor_name, subject, count: int, extra: dict | None):
    """Kort, tydlig svenska. Ingen känslig detalj i titeln - en notis kan
    ligga synlig på en låst skärm."""
    who = _who(actor_name)
    subject = re.sub(r"\s+", " ", str(subject or "")).strip()[:60]
    extra = extra or {}
    if event_type == "household.shopping_item_added":
        body = (f"{who} lade till {subject} i inköpslistan." if count == 1 and subject
                else f"{who} lade till {_plural(count, 'vara', 'varor')} i inköpslistan.")
        return "Inköpslistan", body
    if event_type == "household.shopping_item_purchased":
        body = (f"{who} markerade {subject} som köpt." if count == 1 and subject
                else f"{who} markerade {_plural(count, 'vara', 'varor')} som köpta.")
        return "Inköpslistan", body
    if event_type == "household.shopping_item_at_home":
        body = (f"{subject} finns hemma och lades i skafferiet." if count == 1 and subject
                else f"{who} flyttade {_plural(count, 'vara', 'varor')} till skafferiet.")
        return "Skafferi", body
    if event_type == "household.inventory_changed":
        body = (f"{who} uppdaterade {subject} i skafferiet." if count == 1 and subject
                else f"{who} uppdaterade {_plural(count, 'vara', 'varor')} i skafferiet.")
        return "Skafferi", body
    if event_type == "household.week_changed":
        body = (f"{who} ändrade {subject}." if count == 1 and subject
                else f"{who} ändrade veckoplaneringen på {_plural(count, 'ställe', 'ställen')}.")
        return "Veckan", body
    if event_type == "household.week_ready":
        detail = extra.get("summary")
        return "Veckan är klar", (f"{subject}: {detail}" if subject and detail
                                  else detail or f"En ny vecka är klar för {subject or 'hushållet'}.")
    if event_type == "household.member_joined":
        return "Hushållet", f"{subject or 'En ny medlem'} gick med i hushållet."
    if event_type == "household.price_drop":
        detail = extra.get("summary") or "har blivit billigare."
        return "Pris", f"{subject or 'En vara du följer'} {detail}"
    return "Matjakt", f"{who} gjorde en ändring."


def _outbox_to_public(row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "pref": row["pref"],
        "title": row["title"],
        "body": row["body"],
        "deeplink": row["deeplink"],
        "count": row["count"],
        "createdAt": row["created_at"],
        "sentAt": row["sent_at"],
    }


def _synchronized(method):
    """Samma anslutning delas av alla trådar, och en commit() från en tråd
    nollställer en annan tråds pågående SELECT. Skrivvägarna tog redan låset;
    läsvägarna gjorde det inte, vilket gav sällsynta tomma svar mitt i en
    familjs handling. RLock, så en låst metod kan anropa en annan."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


_ALSO_LOCKED = set()
for _name, _member in list(vars(NotificationStore).items()):
    if callable(_member) and _name != "close" and (not _name.startswith("_") or _name in _ALSO_LOCKED):
        setattr(NotificationStore, _name, _synchronized(_member))

