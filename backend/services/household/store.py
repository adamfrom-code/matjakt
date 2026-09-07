# -*- coding: utf-8 -*-
"""Hushållet: EN delad vecka, EN inköpslista, ETT skafferi för familjen.

Datamodellen håller isär fyra saker som är lätta att blanda ihop (§32 i
kravet), och som redan blandats ihop en gång i den gamla localStorage-modellen:

  ingredient      receptets behov: "mjölk 5 dl"
  product         en riktig vara i en butik: "Arla Mellanmjölk 1,5 l, GTIN …"
  inventory item  vad hushållet har hemma: "ca 1 liter, i kylen"
  shopping item   vad som ska handlas: "0 - vi har den redan"

Ett shopping item PEKAR på en produkt (en ögonblicksbild för visning), det
ÄR inte produkten. Ett inventory item kan vara en produkt eller en generisk
vara (lök, potatis) - därför är produktfälten valfria överallt.

REVISIONER, INTE HELA LISTOR
Varje hushåll har en räknare (households.revision). Varje skrivning ökar den
med ett och stämplar den ändrade RADEN med det nya talet. Klienten frågar
"vad har hänt sedan revision N?" och får bara de raderna tillbaka. Två
personer i samma butik kan därför ändra varsin rad utan att den enes svar
skriver över den andres lista - det som skickas är en rad, aldrig hela
listan. En rad tas heller aldrig bort på riktigt vid en statusändring; den
byter status (REMOVED) och behåller sitt id, så en "ångra" alltid har något
att gå tillbaka till.

SÄKERHET (§24)
Ingen väg här tar emot ett household_id från klienten utan att först slå upp
medlemskapet för den inloggade användaren. `_require_member` är den enda
dörren, och varje läsning och skrivning går genom den. Ett påhittat id ger
NotAMemberError, som API-lagret översätter till 404 - inte 403, som annars
avslöjar att hushållet finns.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import secrets
import sqlite3
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..data_guard import guard_database_path

# Livscykeln för en rad i inköpslistan. "Köpt" och "Har hemma" är INTE samma
# sak (§6): den som redan hade ketchup hemma har inte köpt något, och får
# därför inte räknas in i veckans matkasse. Båda tar bort raden ur behovet,
# men bara PURCHASED är ett köp.
NEED_TO_BUY = "NEED_TO_BUY"
ALREADY_HAVE = "ALREADY_HAVE"
PURCHASED = "PURCHASED"
REMOVED = "REMOVED"
ITEM_STATUSES = (NEED_TO_BUY, ALREADY_HAVE, PURCHASED, REMOVED)

LOCATIONS = ("skafferi", "kyl", "frys")

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"

INVITE_TTL_HOURS = 72
MAX_MEMBERS = 12
MAX_HOUSEHOLD_NAME = 60
MAX_ITEM_NAME = 80
# Ett hushåll delar disk med prisdatabasen. Utan tak kan en klient fylla
# 1 GB med rader; med tak fallerar dess EGEN skrivning, inte hela tjänsten.
MAX_SHOPPING_ITEMS = 400
MAX_INVENTORY_ITEMS = 600
MAX_DOC_BYTES = 200 * 1024
# Händelseloggen är till för notiser och felsökning, inte för historik.
MAX_EVENTS_PER_HOUSEHOLD = 500


class HouseholdError(Exception):
    """Fel som får visas för användaren (fel indata, fullt hushåll, ...)."""


class NotAMemberError(HouseholdError):
    """Användaren är inte medlem i hushållet - eller hushållet finns inte.

    Med FLIT samma undantag för båda fallen: skilda svar berättar för en
    angripare vilka household_id som existerar."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fold(text) -> str:
    """Gemener utan diakriter - 'Crème fraiche' och 'creme fraiche' är samma
    vara i hushållets ögon. Samma regel som prismotorns _fold, medvetet
    kopierad i stället för importerad: hushållsmodulen ska inte kunna gå
    sönder av en ändring i prissättningen."""
    if not text:
        return ""
    lowered = str(text).lower().strip()
    stripped = "".join(c for c in unicodedata.normalize("NFD", lowered)
                       if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", stripped)


def item_key(name: str, gtin: str | None = None) -> str:
    """Radens identitet i ett hushåll.

    En vara med GTIN är den varan - två personer som lägger in samma Arla
    Mellanmjölk ska landa på EN rad. En generisk vara (lök) har inget GTIN
    och identifieras av sitt vikta namn."""
    if gtin and str(gtin).strip():
        return f"gtin:{str(gtin).strip()}"
    return f"name:{fold(name)}"


def _token_hash(token: str) -> str:
    """Inbjudningslänkar lagras hashade, precis som sessionstokens. Länken är
    en bärarhemlighet: den som har den kan gå med i familjens hushåll och
    läsa vad de äter, handlar och har hemma."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _json_or_none(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _clean_name(value, limit=MAX_ITEM_NAME) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _since(value) -> int:
    """Klientens "sedan revision N", tolkad defensivt.

    En klient kan skicka skräp (en trasig lagrad revision, en manipulerad
    parameter, None efter en misslyckad läsning). Att kasta ValueError där
    gör en läsning till ett 500; att tolka skräp som 0 ger en full hämtning,
    vilket alltid är ett korrekt - om än dyrare - svar. Negativa tal är
    samma sak: det finns ingen revision före 0."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _number(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


class HouseholdStore:
    """SQLite-lagret för hushåll. Samma fil som kontodatabasen (users finns
    där), egen anslutning. Stdlib only, som resten av Matjakt."""

    def __init__(self, db_path: Path):
        guard_database_path(db_path, purpose="hushållsdatabasen")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        # Revisionsräknaren är läs-ändra-skriv. ThreadingHTTPServer kör två
        # familjemedlemmars skrivningar parallellt; utan låset kan båda läsa
        # revision 7 och stämpla varsin rad med 8, varpå den ena raden aldrig
        # syns i en sync "sedan 8".
        self._lock = threading.RLock()
        self._init_schema()

    def close(self):
        self._connection.close()

    # ---- schema ---------------------------------------------------------

    def _init_schema(self):
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS households (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS household_members (
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                display_name TEXT,
                profile TEXT,
                joined_at TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (household_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_members_user ON household_members(user_id);
            CREATE TABLE IF NOT EXISTS household_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                used_by INTEGER,
                revoked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS shopping_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                amount REAL,
                unit TEXT,
                status TEXT NOT NULL DEFAULT 'NEED_TO_BUY',
                source TEXT NOT NULL DEFAULT 'week',
                category TEXT,
                product TEXT,
                note TEXT,
                deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by INTEGER,
                revision INTEGER NOT NULL,
                UNIQUE (household_id, item_key)
            );
            CREATE INDEX IF NOT EXISTS idx_shopping_rev ON shopping_items(household_id, revision);
            CREATE TABLE IF NOT EXISTS inventory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT 'skafferi',
                amount REAL NOT NULL DEFAULT 0,
                unit TEXT,
                category TEXT,
                expiry TEXT,
                gtin TEXT,
                product TEXT,
                deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by INTEGER,
                revision INTEGER NOT NULL,
                UNIQUE (household_id, item_key)
            );
            CREATE INDEX IF NOT EXISTS idx_inventory_rev ON inventory_items(household_id, revision);
            CREATE TABLE IF NOT EXISTS household_docs (
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                doc TEXT NOT NULL,
                body TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by INTEGER,
                revision INTEGER NOT NULL,
                PRIMARY KEY (household_id, doc)
            );
            CREATE TABLE IF NOT EXISTS household_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                actor_user_id INTEGER,
                payload TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_household ON household_events(household_id, id);
            """
        )
        # Migrering: inköpsrader raderades hårt fram till 2026-09-07, och en
        # hård radering syns aldrig i ett delta - den andra telefonen behöll
        # spökrader. Nu soft delete (som skafferiet redan hade).
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(shopping_items)")}
        if "deleted" not in columns:
            self._connection.execute("ALTER TABLE shopping_items ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
        self._connection.commit()

    # ---- behörighet -----------------------------------------------------

    def _require_member(self, household_id, user_id, *, admin=False):
        """DEN ENDA dörren in i ett hushålls data.

        Tar household_id som klienten påstår, och användar-id:t som SESSIONEN
        bevisade. Utan en matchande medlemsrad finns hushållet inte, punkt."""
        if not user_id:
            raise NotAMemberError("Du måste vara inloggad")
        try:
            household_id = int(household_id)
        except (TypeError, ValueError):
            raise NotAMemberError("Hushållet finns inte")
        row = self._connection.execute(
            "SELECT * FROM household_members WHERE household_id = ? AND user_id = ?",
            (household_id, int(user_id)),
        ).fetchone()
        if not row:
            raise NotAMemberError("Hushållet finns inte")
        if admin and row["role"] != ROLE_ADMIN:
            raise HouseholdError("Bara hushållets administratör kan göra det")
        return row

    def household_id_for_user(self, user_id) -> int | None:
        """Användarens hushåll, eller None. En användare hör till högst ett
        hushåll - ett andra hushåll skulle betyda två veckor, två listor och
        ett val i varje vy, vilket är precis den administration Matjakt ska
        slippa (§29)."""
        if not user_id:
            return None
        row = self._connection.execute(
            "SELECT household_id FROM household_members WHERE user_id = ? ORDER BY joined_at LIMIT 1",
            (int(user_id),),
        ).fetchone()
        return row["household_id"] if row else None

    # ---- revisioner -----------------------------------------------------

    def _bump(self, household_id) -> int:
        self._connection.execute(
            "UPDATE households SET revision = revision + 1 WHERE id = ?", (household_id,))
        row = self._connection.execute(
            "SELECT revision FROM households WHERE id = ?", (household_id,)).fetchone()
        return row["revision"] if row else 1

    def revision(self, household_id) -> int:
        row = self._connection.execute(
            "SELECT revision FROM households WHERE id = ?", (int(household_id),)).fetchone()
        return row["revision"] if row else 0

    # ---- hushåll --------------------------------------------------------

    def create_household(self, user_id: int, name: str) -> dict:
        name = _clean_name(name, MAX_HOUSEHOLD_NAME)
        if not name:
            raise HouseholdError("Ge hushållet ett namn")
        with self._lock:
            if self.household_id_for_user(user_id):
                raise HouseholdError("Du är redan med i ett hushåll")
            cursor = self._connection.execute(
                "INSERT INTO households (name, created_at, created_by, revision) VALUES (?, ?, ?, 1)",
                (name, _now(), int(user_id)))
            household_id = cursor.lastrowid
            self._connection.execute(
                """INSERT INTO household_members
                   (household_id, user_id, role, joined_at, revision)
                   VALUES (?, ?, ?, ?, 1)""",
                (household_id, int(user_id), ROLE_ADMIN, _now()))
            self._connection.commit()
        return self.household_for(household_id, user_id)

    def rename_household(self, household_id, user_id, name: str) -> dict:
        name = _clean_name(name, MAX_HOUSEHOLD_NAME)
        if not name:
            raise HouseholdError("Ge hushållet ett namn")
        with self._lock:
            self._require_member(household_id, user_id, admin=True)
            self._connection.execute("UPDATE households SET name = ? WHERE id = ?", (name, int(household_id)))
            self._bump(household_id)
            self._connection.commit()
        return self.household_for(household_id, user_id)

    def household_for(self, household_id, user_id) -> dict:
        member = self._require_member(household_id, user_id)
        row = self._connection.execute(
            "SELECT * FROM households WHERE id = ?", (int(household_id),)).fetchone()
        if not row:
            raise NotAMemberError("Hushållet finns inte")
        return {
            "id": row["id"],
            "name": row["name"],
            "createdAt": row["created_at"],
            "revision": row["revision"],
            "role": member["role"],
            "members": self._members(household_id),
        }

    def _members(self, household_id) -> list[dict]:
        """Medlemslistan. E-post kommer INTE härifrån - hushållsdatabasen ska
        inte kunna lämna ut en adress ens av misstag; API-lagret berikar med
        e-post via kontolagret när det är rätt (medlemslistan i Konto)."""
        rows = self._connection.execute(
            "SELECT * FROM household_members WHERE household_id = ? ORDER BY joined_at",
            (int(household_id),)).fetchall()
        return [{
            "userId": row["user_id"],
            "role": row["role"],
            "displayName": row["display_name"],
            "profile": _json_or_none(row["profile"]) or {},
            "joinedAt": row["joined_at"],
        } for row in rows]

    def member_user_ids(self, household_id) -> list[int]:
        return [row["user_id"] for row in self._connection.execute(
            "SELECT user_id FROM household_members WHERE household_id = ?",
            (int(household_id),)).fetchall()]

    def set_profile(self, household_id, user_id, *, display_name=None, profile=None) -> dict:
        """Den personliga profilen INUTI hushållet (§3): visningsnamn,
        matpreferenser, allergier. En medlem sätter bara sin egen - det finns
        ingen väg att skriva någon annans."""
        with self._lock:
            self._require_member(household_id, user_id)
            fields, values = [], []
            if display_name is not None:
                fields.append("display_name = ?")
                values.append(_clean_name(display_name, 40) or None)
            if profile is not None:
                if not isinstance(profile, dict):
                    raise HouseholdError("Ogiltig profil")
                body = json.dumps(_clean_profile(profile), ensure_ascii=False)
                if len(body.encode("utf-8")) > 4096:
                    raise HouseholdError("Profilen är för stor")
                fields.append("profile = ?")
                values.append(body)
            if not fields:
                return self.household_for(household_id, user_id)
            revision = self._bump(household_id)
            fields.append("revision = ?")
            values.append(revision)
            values.extend([int(household_id), int(user_id)])
            self._connection.execute(
                f"UPDATE household_members SET {', '.join(fields)} WHERE household_id = ? AND user_id = ?",
                values)
            self._connection.commit()
        return self.household_for(household_id, user_id)

    # ---- inbjudningar ---------------------------------------------------

    def create_invite(self, household_id, user_id) -> dict:
        """En engångslänk som går ut efter 72 timmar.

        Token:en returneras EN gång, i det här svaret - därefter finns bara
        hashen. Det är samma regel som för sessionstokens, och den gör en
        läcka ur databasen värdelös för den som vill smyga in i ett hushåll."""
        with self._lock:
            self._require_member(household_id, user_id, admin=True)
            if len(self.member_user_ids(household_id)) >= MAX_MEMBERS:
                raise HouseholdError("Hushållet är fullt")
            token = secrets.token_urlsafe(24)
            expires = datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)
            self._connection.execute(
                """INSERT INTO household_invites
                   (household_id, token_hash, created_by, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (int(household_id), _token_hash(token), int(user_id), _now(), expires.isoformat()))
            self._connection.commit()
        return {"token": token, "expiresAt": expires.isoformat()}

    def revoke_invites(self, household_id, user_id) -> int:
        with self._lock:
            self._require_member(household_id, user_id, admin=True)
            cursor = self._connection.execute(
                "UPDATE household_invites SET revoked_at = ? WHERE household_id = ? AND used_at IS NULL AND revoked_at IS NULL",
                (_now(), int(household_id)))
            self._connection.commit()
            return cursor.rowcount

    def _live_invite(self, token: str):
        if not token:
            return None
        row = self._connection.execute(
            "SELECT * FROM household_invites WHERE token_hash = ?", (_token_hash(token),)).fetchone()
        if not row or row["used_at"] or row["revoked_at"]:
            return None
        if row["expires_at"] <= _now():
            return None
        return row

    def preview_invite(self, token: str) -> dict:
        """Vad landningssidan får visa INNAN någon loggat in (§28).

        Bara hushållets namn och vem som bjöd in - inget om veckan, listan
        eller skafferiet. En länk på avvägar ska räcka till "Adam har bjudit
        in dig till Familjen From", inte till familjens middagar."""
        row = self._live_invite(token)
        if not row:
            raise HouseholdError("Inbjudan gäller inte längre")
        household = self._connection.execute(
            "SELECT name FROM households WHERE id = ?", (row["household_id"],)).fetchone()
        if not household:
            raise HouseholdError("Inbjudan gäller inte längre")
        inviter = self._connection.execute(
            "SELECT display_name FROM household_members WHERE household_id = ? AND user_id = ?",
            (row["household_id"], row["created_by"])).fetchone()
        return {
            "householdName": household["name"],
            "invitedBy": (inviter["display_name"] if inviter else None),
            "expiresAt": row["expires_at"],
        }

    def accept_invite(self, token: str, user_id: int) -> dict:
        with self._lock:
            row = self._live_invite(token)
            if not row:
                raise HouseholdError("Inbjudan gäller inte längre")
            household_id = row["household_id"]
            existing = self.household_id_for_user(user_id)
            if existing == household_id:
                # Redan med: förbruka inte inbjudan, svara vänligt.
                return self.household_for(household_id, user_id)
            if existing:
                raise HouseholdError("Du är redan med i ett hushåll. Lämna det först.")
            if len(self.member_user_ids(household_id)) >= MAX_MEMBERS:
                raise HouseholdError("Hushållet är fullt")
            self._connection.execute(
                """INSERT INTO household_members
                   (household_id, user_id, role, joined_at, revision)
                   VALUES (?, ?, ?, ?, ?)""",
                (household_id, int(user_id), ROLE_MEMBER, _now(), self._bump(household_id)))
            self._connection.execute(
                "UPDATE household_invites SET used_at = ?, used_by = ? WHERE id = ?",
                (_now(), int(user_id), row["id"]))
            self._connection.commit()
        return self.household_for(household_id, user_id)

    # ---- lämna / ta bort ------------------------------------------------

    def leave(self, household_id, user_id):
        """Medlemmen lämnar. Gemensam data (vecka, lista, skafferi) stannar i
        hushållet - den tillhör familjen, inte den som går. Personlig data
        (profilen inuti hushållet) tas bort med medlemsraden. Sista medlemmen
        som går tar hushållet och all dess data med sig; att lämna en tom
        familj kvar vore data ingen längre kan nå eller radera."""
        with self._lock:
            member = self._require_member(household_id, user_id)
            household_id = int(household_id)
            others = [uid for uid in self.member_user_ids(household_id) if uid != int(user_id)]
            self._connection.execute(
                "DELETE FROM household_members WHERE household_id = ? AND user_id = ?",
                (household_id, int(user_id)))
            if not others:
                self._delete_household(household_id)
            else:
                if member["role"] == ROLE_ADMIN and not self._has_admin(household_id):
                    # Ett hushåll utan administratör kan varken bjuda in eller
                    # städa upp. Äldsta kvarvarande medlem ärver rollen.
                    self._connection.execute(
                        "UPDATE household_members SET role = ? WHERE household_id = ? AND user_id = ?",
                        (ROLE_ADMIN, household_id, others[0]))
                self._bump(household_id)
            self._connection.commit()

    def remove_member(self, household_id, actor_user_id, target_user_id):
        with self._lock:
            self._require_member(household_id, actor_user_id, admin=True)
            if int(actor_user_id) == int(target_user_id):
                raise HouseholdError("Använd Lämna hushållet för att gå ur själv")
            self._require_member(household_id, target_user_id)
            self._connection.execute(
                "DELETE FROM household_members WHERE household_id = ? AND user_id = ?",
                (int(household_id), int(target_user_id)))
            # Öppna inbjudningar som den borttagna skapat ska inte kunna
            # användas för att komma tillbaka bakvägen.
            self._connection.execute(
                "UPDATE household_invites SET revoked_at = ? WHERE household_id = ? AND created_by = ? AND used_at IS NULL AND revoked_at IS NULL",
                (_now(), int(household_id), int(target_user_id)))
            self._bump(household_id)
            self._connection.commit()

    def _has_admin(self, household_id) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM household_members WHERE household_id = ? AND role = ? LIMIT 1",
            (int(household_id), ROLE_ADMIN)).fetchone()
        return bool(row)

    def _delete_household(self, household_id):
        household_id = int(household_id)
        for table in ("shopping_items", "inventory_items", "household_docs",
                      "household_events", "household_invites", "household_members"):
            self._connection.execute(f"DELETE FROM {table} WHERE household_id = ?", (household_id,))
        self._connection.execute("DELETE FROM households WHERE id = ?", (household_id,))

    def forget_user(self, user_id):
        """Kontot raderas (§24: vad händer med datan?).

        Personlig data försvinner: medlemsraden med profilen, och
        inbjudningar personen skapat. Gemensam hushållsdata stannar hos de
        andra - familjens vecka och skafferi är deras, inte den som lämnar.
        Är personen ensam i hushållet raderas hushållet med allt i sig."""
        with self._lock:
            user_id = int(user_id)
            rows = self._connection.execute(
                "SELECT household_id FROM household_members WHERE user_id = ?", (user_id,)).fetchall()
            for row in rows:
                household_id = row["household_id"]
                others = [uid for uid in self.member_user_ids(household_id) if uid != user_id]
                self._connection.execute(
                    "DELETE FROM household_members WHERE household_id = ? AND user_id = ?",
                    (household_id, user_id))
                self._connection.execute(
                    "UPDATE household_invites SET revoked_at = ? WHERE created_by = ? AND used_at IS NULL AND revoked_at IS NULL",
                    (_now(), user_id))
                if not others:
                    self._delete_household(household_id)
                else:
                    if not self._has_admin(household_id):
                        self._connection.execute(
                            "UPDATE household_members SET role = ? WHERE household_id = ? AND user_id = ?",
                            (ROLE_ADMIN, household_id, others[0]))
                    self._bump(household_id)
            self._connection.commit()

    # ---- inköpslistan ---------------------------------------------------

    def upsert_shopping_item(self, household_id, user_id, item: dict) -> dict:
        """Lägger till eller uppdaterar EN rad. Aldrig hela listan.

        Radens identitet är item_key (GTIN om vi vet produkten, annars vikt
        namn), så samma vara från två håll blir en rad i stället för två."""
        with self._lock:
            self._require_member(household_id, user_id)
            household_id = int(household_id)
            name = _clean_name(item.get("name") or item.get("displayName"))
            if not name:
                raise HouseholdError("Varan behöver ett namn")
            product = _clean_product(item.get("product"))
            key = _clean_name(item.get("key"), 120) or item_key(name, (product or {}).get("gtin"))
            status = item.get("status") or NEED_TO_BUY
            if status not in ITEM_STATUSES:
                raise HouseholdError("Okänd status")
            existing = self._connection.execute(
                "SELECT * FROM shopping_items WHERE household_id = ? AND item_key = ?",
                (household_id, key)).fetchone()
            if existing is None:
                count = self._connection.execute(
                    "SELECT COUNT(*) AS n FROM shopping_items WHERE household_id = ? AND deleted = 0",
                    (household_id,)).fetchone()["n"]
                if count >= MAX_SHOPPING_ITEMS:
                    raise HouseholdError("Inköpslistan är full")
            revision = self._bump(household_id)
            now = _now()
            amount = item.get("amount")
            unit = _clean_name(item.get("unit"), 12) or None
            values = {
                "display_name": name,
                "amount": None if amount is None else _number(amount),
                "unit": unit,
                "status": status,
                "source": _clean_name(item.get("source"), 20) or (existing["source"] if existing else "week"),
                "category": _clean_name(item.get("category"), 40) or None,
                "product": json.dumps(product, ensure_ascii=False) if product else (existing["product"] if existing else None),
                "note": _clean_name(item.get("note"), 120) or None,
            }
            if existing:
                self._connection.execute(
                    """UPDATE shopping_items SET display_name = ?, amount = ?, unit = ?, status = ?,
                           source = ?, category = ?, product = ?, note = ?, deleted = 0, updated_at = ?,
                           updated_by = ?, revision = ?
                       WHERE id = ?""",
                    (values["display_name"], values["amount"], values["unit"], values["status"],
                     values["source"], values["category"], values["product"], values["note"],
                     now, int(user_id), revision, existing["id"]))
                item_id = existing["id"]
            else:
                cursor = self._connection.execute(
                    """INSERT INTO shopping_items
                       (household_id, item_key, display_name, amount, unit, status, source,
                        category, product, note, created_at, updated_at, updated_by, revision)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (household_id, key, values["display_name"], values["amount"], values["unit"],
                     values["status"], values["source"], values["category"], values["product"],
                     values["note"], now, now, int(user_id), revision))
                item_id = cursor.lastrowid
            self._connection.commit()
        return self.shopping_item(household_id, item_id)

    def replace_week_items(self, household_id, user_id, items: list[dict]) -> dict:
        """Veckans behov skrivs om när planen ändras - men bara raderna som
        KOM FRÅN veckan, och bara de fält veckan äger.

        Det användaren har sagt om en rad ("har hemma", "köpt", "bort") är
        deras beslut och överlever en omgenerering; det vore respektlöst att
        kryssa upp mjölken igen bara för att torsdagens middag byttes ut.
        Manuellt tillagda rader rörs inte alls."""
        with self._lock:
            self._require_member(household_id, user_id)
            household_id = int(household_id)
            revision = self._bump(household_id)
            now = _now()
            seen = set()
            for item in items or []:
                name = _clean_name(item.get("name") or item.get("displayName"))
                if not name:
                    continue
                product = _clean_product(item.get("product"))
                key = item_key(name, (product or {}).get("gtin"))
                seen.add(key)
                existing = self._connection.execute(
                    "SELECT * FROM shopping_items WHERE household_id = ? AND item_key = ?",
                    (household_id, key)).fetchone()
                amount = None if item.get("amount") is None else _number(item.get("amount"))
                unit = _clean_name(item.get("unit"), 12) or None
                category = _clean_name(item.get("category"), 40) or None
                product_json = json.dumps(product, ensure_ascii=False) if product else None
                if existing and existing["deleted"]:
                    # Raden var borttagen (planen bytte, eller någon tog bort
                    # den manuellt) - kommer den tillbaka med veckan är den
                    # ett nytt behov, inte det gamla beslutet.
                    self._connection.execute(
                        """UPDATE shopping_items SET display_name = ?, amount = ?, unit = ?,
                               category = ?, product = COALESCE(?, product), status = ?,
                               source = 'week', deleted = 0, updated_at = ?, updated_by = ?, revision = ?
                           WHERE id = ?""",
                        (name, amount, unit, category, product_json, NEED_TO_BUY, now, int(user_id),
                         revision, existing["id"]))
                elif existing:
                    self._connection.execute(
                        """UPDATE shopping_items SET display_name = ?, amount = ?, unit = ?,
                               category = ?, product = COALESCE(?, product), updated_at = ?,
                               updated_by = ?, revision = ?
                           WHERE id = ?""",
                        (name, amount, unit, category, product_json, now, int(user_id),
                         revision, existing["id"]))
                else:
                    self._connection.execute(
                        """INSERT INTO shopping_items
                           (household_id, item_key, display_name, amount, unit, status, source,
                            category, product, created_at, updated_at, updated_by, revision)
                           VALUES (?, ?, ?, ?, ?, ?, 'week', ?, ?, ?, ?, ?, ?)""",
                        (household_id, key, name, amount, unit, NEED_TO_BUY, category,
                         product_json, now, now, int(user_id), revision))
            # Veckorader som inte längre ingår i planen försvinner - men bara
            # de som veckan själv lade dit.
            stale = self._connection.execute(
                "SELECT id, item_key FROM shopping_items WHERE household_id = ? AND source = 'week' AND deleted = 0",
                (household_id,)).fetchall()
            for row in stale:
                if row["item_key"] not in seen:
                    # Soft delete med ny revision - så den andra telefonen får
                    # veta att raden ska bort (§ P1-2 i granskningen 2026-09-07).
                    self._connection.execute(
                        "UPDATE shopping_items SET deleted = 1, updated_at = ?, updated_by = ?, revision = ? WHERE id = ?",
                        (now, int(user_id), revision, row["id"]))
            self._connection.commit()
        return {"revision": revision, "items": self.shopping_items(household_id, user_id)}

    def set_item_status(self, household_id, user_id, key_or_id, status: str) -> dict:
        if status not in ITEM_STATUSES:
            raise HouseholdError("Okänd status")
        with self._lock:
            self._require_member(household_id, user_id)
            row = self._find_shopping_row(household_id, key_or_id)
            if not row:
                raise HouseholdError("Varan finns inte i listan")
            revision = self._bump(household_id)
            self._connection.execute(
                "UPDATE shopping_items SET status = ?, updated_at = ?, updated_by = ?, revision = ? WHERE id = ?",
                (status, _now(), int(user_id), revision, row["id"]))
            self._connection.commit()
        return self.shopping_item(household_id, row["id"])

    def delete_shopping_item(self, household_id, user_id, key_or_id):
        """Radering (soft) - används bara för manuellt tillagda rader som
        användaren ångrar helt. Statusändringar går genom set_item_status, som
        BEVARAR raden (och därmed ångra-möjligheten).

        En rad som inte finns i DITT hushåll är ett fel, inte ett tyst ok.
        Den tidigare tysta returen gjorde radering till den enda skrivvägen
        som svarade "gick bra" på ett id ur ett annat hushåll - ingen data
        ändrades, men svaret skilde sig från alla andra vägars, och en
        skillnad är allt en angripare behöver. Klienten ska läsa 404 som
        "redan borta" vid ett omförsök."""
        with self._lock:
            self._require_member(household_id, user_id)
            row = self._find_shopping_row(household_id, key_or_id)
            if not row:
                raise HouseholdError("Varan finns inte i listan")
            revision = self._bump(household_id)
            # Soft delete: raden bär sin sista revision så ett delta-svar kan
            # tala om för andra telefoner att den är borta.
            self._connection.execute(
                "UPDATE shopping_items SET deleted = 1, updated_at = ?, updated_by = ?, revision = ? WHERE id = ?",
                (_now(), int(user_id), revision, row["id"]))
            self._connection.commit()

    def _find_shopping_row(self, household_id, key_or_id):
        household_id = int(household_id)
        if isinstance(key_or_id, int) or (isinstance(key_or_id, str) and key_or_id.isdigit()):
            return self._connection.execute(
                "SELECT * FROM shopping_items WHERE household_id = ? AND id = ? AND deleted = 0",
                (household_id, int(key_or_id))).fetchone()
        return self._connection.execute(
            "SELECT * FROM shopping_items WHERE household_id = ? AND item_key = ? AND deleted = 0",
            (household_id, str(key_or_id))).fetchone()

    def shopping_item(self, household_id, item_id) -> dict:
        row = self._connection.execute(
            "SELECT * FROM shopping_items WHERE household_id = ? AND id = ?",
            (int(household_id), int(item_id))).fetchone()
        return _shopping_to_public(row) if row else {}

    def shopping_items(self, household_id, user_id, since: int = 0) -> list[dict]:
        self._require_member(household_id, user_id)
        since = _since(since)
        # since=0 är en full hämtning: gravstenarna behövs inte där. I ett
        # delta är de själva poängen - den andra telefonen ska ta bort raden.
        rows = self._connection.execute(
            "SELECT * FROM shopping_items WHERE household_id = ? AND revision > ? AND (deleted = 0 OR ? > 0) ORDER BY id",
            (int(household_id), since, since)).fetchall()
        return [_shopping_to_public(row) for row in rows]

    # ---- skafferi / kyl / frys -------------------------------------------

    def upsert_inventory_item(self, household_id, user_id, item: dict) -> dict:
        with self._lock:
            self._require_member(household_id, user_id)
            household_id = int(household_id)
            name = _clean_name(item.get("name") or item.get("displayName"))
            if not name:
                raise HouseholdError("Varan behöver ett namn")
            product = _clean_product(item.get("product"))
            gtin = _clean_gtin(item.get("gtin") or (product or {}).get("gtin"))
            key = _clean_name(item.get("key"), 120) or item_key(name, gtin)
            location = item.get("location") if item.get("location") in LOCATIONS else "skafferi"
            existing = self._connection.execute(
                "SELECT * FROM inventory_items WHERE household_id = ? AND item_key = ?",
                (household_id, key)).fetchone()
            if existing is None or existing["deleted"]:
                live = self._connection.execute(
                    "SELECT COUNT(*) AS n FROM inventory_items WHERE household_id = ? AND deleted = 0",
                    (household_id,)).fetchone()["n"]
                if live >= MAX_INVENTORY_ITEMS:
                    raise HouseholdError("Skafferiet är fullt")
            revision = self._bump(household_id)
            now = _now()
            amount = _number(item.get("amount"), 1.0)
            unit = _clean_name(item.get("unit"), 12) or None
            category = _clean_name(item.get("category"), 40) or None
            expiry = _clean_date(item.get("expiry"))
            product_json = json.dumps(product, ensure_ascii=False) if product else None
            if existing:
                self._connection.execute(
                    """UPDATE inventory_items SET display_name = ?, location = ?, amount = ?, unit = ?,
                           category = ?, expiry = ?, gtin = ?, product = COALESCE(?, product),
                           deleted = 0, updated_at = ?, updated_by = ?, revision = ?
                       WHERE id = ?""",
                    (name, location, amount, unit, category, expiry, gtin, product_json,
                     now, int(user_id), revision, existing["id"]))
                item_id = existing["id"]
            else:
                cursor = self._connection.execute(
                    """INSERT INTO inventory_items
                       (household_id, item_key, display_name, location, amount, unit, category,
                        expiry, gtin, product, created_at, updated_at, updated_by, revision)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (household_id, key, name, location, amount, unit, category, expiry, gtin,
                     product_json, now, now, int(user_id), revision))
                item_id = cursor.lastrowid
            self._connection.commit()
        return self.inventory_item(household_id, item_id)

    def touch_inventory_item(self, household_id, user_id, key_or_id) -> dict:
        """"Har hemma" på en vara som REDAN står hemma: rör varken plats,
        mängd, bäst före eller kategori - familjens rad är familjens rad.
        Bara revisionen bumpas så alla telefoner ser att den bekräftades."""
        with self._lock:
            self._require_member(household_id, user_id)
            row = self._find_inventory_row(household_id, key_or_id)
            if not row:
                raise HouseholdError("Varan finns inte i skafferiet")
            revision = self._bump(household_id)
            self._connection.execute(
                "UPDATE inventory_items SET deleted = 0, updated_at = ?, updated_by = ?, revision = ? WHERE id = ?",
                (_now(), int(user_id), revision, row["id"]))
            self._connection.commit()
        return self.inventory_item(household_id, row["id"])

    def adjust_inventory(self, household_id, user_id, key_or_id, delta: float) -> dict:
        """+/- i skafferiet. Går mängden till noll markeras raden som borttagen
        (soft delete) i stället för att försvinna - annars vet en annan telefon
        aldrig att den ska ta bort raden ur sin vy."""
        with self._lock:
            self._require_member(household_id, user_id)
            row = self._find_inventory_row(household_id, key_or_id)
            if not row:
                raise HouseholdError("Varan finns inte i skafferiet")
            amount = max(0.0, _number(row["amount"]) + _number(delta))
            revision = self._bump(household_id)
            self._connection.execute(
                "UPDATE inventory_items SET amount = ?, deleted = ?, updated_at = ?, updated_by = ?, revision = ? WHERE id = ?",
                (amount, 1 if amount <= 0 else 0, _now(), int(user_id), revision, row["id"]))
            self._connection.commit()
        return self.inventory_item(household_id, row["id"])

    def remove_inventory_item(self, household_id, user_id, key_or_id) -> dict:
        with self._lock:
            self._require_member(household_id, user_id)
            row = self._find_inventory_row(household_id, key_or_id)
            if not row:
                raise HouseholdError("Varan finns inte i skafferiet")
            revision = self._bump(household_id)
            self._connection.execute(
                "UPDATE inventory_items SET deleted = 1, updated_at = ?, updated_by = ?, revision = ? WHERE id = ?",
                (_now(), int(user_id), revision, row["id"]))
            self._connection.commit()
        return self.inventory_item(household_id, row["id"])

    def _find_inventory_row(self, household_id, key_or_id):
        household_id = int(household_id)
        if isinstance(key_or_id, int) or (isinstance(key_or_id, str) and key_or_id.isdigit()):
            return self._connection.execute(
                "SELECT * FROM inventory_items WHERE household_id = ? AND id = ?",
                (household_id, int(key_or_id))).fetchone()
        return self._connection.execute(
            "SELECT * FROM inventory_items WHERE household_id = ? AND item_key = ?",
            (household_id, str(key_or_id))).fetchone()

    def inventory_item(self, household_id, item_id) -> dict:
        row = self._connection.execute(
            "SELECT * FROM inventory_items WHERE household_id = ? AND id = ?",
            (int(household_id), int(item_id))).fetchone()
        return _inventory_to_public(row) if row else {}

    def inventory_items(self, household_id, user_id, since: int = 0, include_deleted=True) -> list[dict]:
        self._require_member(household_id, user_id)
        sql = "SELECT * FROM inventory_items WHERE household_id = ? AND revision > ?"
        if not include_deleted:
            sql += " AND deleted = 0"
        rows = self._connection.execute(sql + " ORDER BY id",
                                        (int(household_id), _since(since))).fetchall()
        return [_inventory_to_public(row) for row in rows]

    def pantry_amounts(self, household_id) -> dict:
        """Vad prismotorn får veta om vad som finns hemma: {namn: mängd}.

        KONSERVATIVT (§10): bara rader med en mängd vi faktiskt vet. Motorn
        drar av i radens egen enhet och struntar i det som inte går att
        konvertera - den här funktionen ska inte gissa något åt den."""
        rows = self._connection.execute(
            "SELECT display_name, amount FROM inventory_items WHERE household_id = ? AND deleted = 0 AND amount > 0",
            (int(household_id),)).fetchall()
        return {row["display_name"]: row["amount"] for row in rows}

    # ---- delade dokument (vecka, inställningar, basvaror, historik) -------

    DOCS = ("week", "settings", "staples", "history")

    def set_doc(self, household_id, user_id, doc: str, body) -> dict:
        if doc not in self.DOCS:
            raise HouseholdError("Okänt dokument")
        payload = json.dumps(body, ensure_ascii=False)
        if len(payload.encode("utf-8")) > MAX_DOC_BYTES:
            raise HouseholdError("Datat är för stort för att sparas")
        with self._lock:
            self._require_member(household_id, user_id)
            revision = self._bump(household_id)
            self._connection.execute(
                """INSERT INTO household_docs (household_id, doc, body, updated_at, updated_by, revision)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(household_id, doc) DO UPDATE SET
                       body = excluded.body, updated_at = excluded.updated_at,
                       updated_by = excluded.updated_by, revision = excluded.revision""",
                (int(household_id), doc, payload, _now(), int(user_id), revision))
            self._connection.commit()
        return {"doc": doc, "revision": revision}

    def get_doc(self, household_id, user_id, doc: str):
        self._require_member(household_id, user_id)
        row = self._connection.execute(
            "SELECT body FROM household_docs WHERE household_id = ? AND doc = ?",
            (int(household_id), doc)).fetchone()
        return _json_or_none(row["body"]) if row else None

    def docs_since(self, household_id, since: int = 0) -> dict:
        rows = self._connection.execute(
            "SELECT doc, body, revision, updated_by, updated_at FROM household_docs WHERE household_id = ? AND revision > ?",
            (int(household_id), _since(since))).fetchall()
        return {row["doc"]: {"body": _json_or_none(row["body"]), "revision": row["revision"],
                             "updatedBy": row["updated_by"], "updatedAt": row["updated_at"]}
                for row in rows}

    # ---- händelser ------------------------------------------------------

    def record_event(self, household_id, actor_user_id, event_type: str, payload: dict | None = None):
        """Ett gemensamt händelselager (§ Push): backend avgör sedan vem som
        ska notifieras. Loggen är avsiktligt tunn - vad som hände, vem som
        gjorde det, när - så den kan ligga kvar utan att bli ett arkiv över
        familjens matvanor."""
        with self._lock:
            self._connection.execute(
                "INSERT INTO household_events (household_id, type, actor_user_id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (int(household_id), str(event_type)[:60],
                 None if actor_user_id is None else int(actor_user_id),
                 json.dumps(payload or {}, ensure_ascii=False)[:2000], _now()))
            self._connection.execute(
                """DELETE FROM household_events WHERE household_id = ? AND id NOT IN (
                       SELECT id FROM household_events WHERE household_id = ? ORDER BY id DESC LIMIT ?)""",
                (int(household_id), int(household_id), MAX_EVENTS_PER_HOUSEHOLD))
            self._connection.commit()

    def events(self, household_id, user_id, limit: int = 30) -> list[dict]:
        self._require_member(household_id, user_id)
        rows = self._connection.execute(
            "SELECT * FROM household_events WHERE household_id = ? ORDER BY id DESC LIMIT ?",
            (int(household_id), max(1, min(200, int(limit or 30))))).fetchall()
        return [{"id": row["id"], "type": row["type"], "actorUserId": row["actor_user_id"],
                 "payload": _json_or_none(row["payload"]) or {}, "createdAt": row["created_at"]}
                for row in rows]

    # ---- sync -----------------------------------------------------------

    def sync(self, household_id, user_id, since: int = 0) -> dict:
        """Allt som ändrats sedan revision `since`.

        since=0 ger hela hushållet (första hämtningen). Svaret bär alltid den
        aktuella revisionen, så klienten vet vad den ska fråga efter nästa
        gång - och en klient som ligger efter hämtar bara skillnaden."""
        self._require_member(household_id, user_id)
        household_id = int(household_id)
        since = _since(since)
        return {
            "householdId": household_id,
            "revision": self.revision(household_id),
            "since": since,
            "household": self.household_for(household_id, user_id) if since == 0 else None,
            "members": self._members(household_id),
            "shopping": self.shopping_items(household_id, user_id, since),
            "inventory": self.inventory_items(household_id, user_id, since),
            "docs": self.docs_since(household_id, since),
        }


def _clean_gtin(value) -> str | None:
    text = re.sub(r"\D", "", str(value or ""))
    return text[:14] if 8 <= len(text) <= 14 else None


def _clean_date(value) -> str | None:
    text = str(value or "").strip()[:10]
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None


_PRODUCT_TEXT_FIELDS = (("productName", 120), ("brand", 60), ("packageSize", 40),
                        ("chain", 40), ("category", 40), ("priceTier", 32),
                        ("packageSource", 32), ("productId", 64))


def _clean_product(product) -> dict | None:
    """Produktögonblicksbilden som visas i listan.

    Detta är VISNINGSDATA, inget prisbeslut. Prismotorn räknar fortfarande
    från sin egen databas; det som sparas här är vad raden ska säga när den
    ritas, plus produktens id så vi kan följa varför just den varan valdes.
    Fälten är vitlistade - allt annat klienten skickar kastas, så en snygg
    bild aldrig kan smyga in ett påhittat pris i hushållets data."""
    if not isinstance(product, dict):
        return None
    cleaned = {}
    for field, limit in _PRODUCT_TEXT_FIELDS:
        value = product.get(field)
        if value not in (None, ""):
            cleaned[field] = _clean_name(value, limit)
    gtin = _clean_gtin(product.get("gtin"))
    if gtin:
        cleaned["gtin"] = gtin
    image = str(product.get("imageUrl") or "").strip()
    if image.startswith("https://") and len(image) <= 500:
        cleaned["imageUrl"] = image
    for field in ("unitPrice", "totalCost", "packages", "packageAmount", "comparisonPrice"):
        if product.get(field) is not None:
            cleaned[field] = _number(product.get(field))
    unit = _clean_name(product.get("packageUnit"), 12)
    if unit:
        cleaned["packageUnit"] = unit
    return cleaned or None


_SPICE = ("mild", "medel", "stark")
_MAX_PROFILE_LIST = 12


def _clean_profile(profile: dict) -> dict:
    """Profilen är avsiktligt LITEN (§3): kosttyp, styrka, allergier, ogillar.
    Inget socialt nätverk, inga fritextfält som växer till ett arkiv."""
    cleaned = {}
    diet = _clean_name(profile.get("diet"), 24)
    if diet:
        cleaned["diet"] = diet
    spice = str(profile.get("spice") or "").strip().lower()
    if spice in _SPICE:
        cleaned["spice"] = spice
    for field in ("allergies", "dislikes"):
        values = profile.get(field)
        if isinstance(values, list):
            items = [_clean_name(value, 40) for value in values[:_MAX_PROFILE_LIST]]
            items = [item for item in items if item]
            if items:
                cleaned[field] = items
    if profile.get("child") is not None:
        cleaned["child"] = bool(profile.get("child"))
    return cleaned


def _shopping_to_public(row) -> dict:
    return {
        "id": row["id"],
        "key": row["item_key"],
        "name": row["display_name"],
        "amount": row["amount"],
        "unit": row["unit"],
        "status": row["status"],
        "source": row["source"],
        "category": row["category"],
        "product": _json_or_none(row["product"]),
        "note": row["note"],
        "deleted": bool(row["deleted"]),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
        "revision": row["revision"],
    }


def _inventory_to_public(row) -> dict:
    return {
        "id": row["id"],
        "key": row["item_key"],
        "name": row["display_name"],
        "location": row["location"],
        "amount": row["amount"],
        "unit": row["unit"],
        "category": row["category"],
        "expiry": row["expiry"],
        "gtin": row["gtin"],
        "product": _json_or_none(row["product"]),
        "deleted": bool(row["deleted"]),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
        "revision": row["revision"],
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


_ALSO_LOCKED = {"_find_inventory_row", "_find_shopping_row", "_live_invite", "_members", "_require_member"}
for _name, _member in list(vars(HouseholdStore).items()):
    if callable(_member) and _name != "close" and (not _name.startswith("_") or _name in _ALSO_LOCKED):
        setattr(HouseholdStore, _name, _synchronized(_member))

