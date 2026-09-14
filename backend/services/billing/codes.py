# -*- coding: utf-8 -*-
"""Premium-koder som RADER med gränser, inte en evig sträng i miljön.

Före H5 var hela kodhanteringen en env-variabel: `MATJAKT_PREMIUM_CODE`, en
enda sträng utan förbrukning, utgång eller räknare. Tre konsekvenser, och
ingen av dem gick att åtgärda i efterhand:

* Läggs strängen på Flashback blir varje konto som löser in den **permanent**
  Premium. Det finns inget tak, ingen klocka och ingen räknare som märker att
  det händer.
* Att byta env-variabeln återkallar **ingenting**. De redan inlösta kontona
  har `premium = 1` för evigt, och inget i systemet minns vilken kod som gav
  dem det.
* Det gick inte att ge en enskild person en kod. Alla delade samma.

Nu är en kod en rad: `code_hash`, en etikett som säger vad den är till för,
hur många dagar den ger, ett antal användningar, en utgång, och vem som äger
den. Koden själv lagras bara som SHA-256 - samma regel som för sessioner och
återställningstoken. En läckt databas är inte en bunt giltiga koder.

Och belöningen är `premium_until`, inte en evig boolean: en kod ger exakt de
dagar dess `grant_days` säger, och när de är slut faller kontot till Free av
sig självt. Hur många dagar det är bestämmer den som skapar koden - talet står
aldrig här. Den gamla flaggan finns kvar för de konton som redan har den
(ingen ska vakna degraderad av en refaktorering), men ingenting NYTT sätter
den.
"""

import hashlib
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

# Läsbara koder: inga 0/O/1/I/l, för en kod skrivs av från en telefonskärm.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class CodeError(Exception):
    """Fel som får visas för den som löser in koden."""


def hash_code(code: str) -> str:
    """Samma hashning som sessionstoken. Råa koder lagras aldrig."""
    return hashlib.sha256((code or "").strip().upper().encode("utf-8")).hexdigest()


def new_code(prefix: str = "", length: int = 8) -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(length))
    return f"{prefix}{body}" if prefix else body


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PremiumCodeStore:
    """Koderna i kontodatabasen. Delar anslutning och lås med AccountStore av
    samma skäl som mätningen gör det: en commit() från en annan tråd på samma
    anslutning nollställer ett pågående sessionsuppslag."""

    def __init__(self, connection: sqlite3.Connection, lock=None):
        self._connection = connection
        self._lock = lock if lock is not None else threading.RLock()
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS premium_codes (
                    code_hash TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    grant_days INTEGER NOT NULL,
                    max_uses INTEGER,
                    uses INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    owner_user_id INTEGER,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS premium_code_uses (
                    code_hash TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    used_at TEXT NOT NULL,
                    rewarded_at TEXT,
                    PRIMARY KEY (code_hash, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_codes_owner
                    ON premium_codes(owner_user_id);
                """
            )
            self._connection.commit()

    # ---- skapa och ändra --------------------------------------------------

    def create(self, *, label: str, grant_days: int, max_uses=None, expires_at=None,
               owner_user_id=None, code: str = None, prefix: str = "") -> str:
        """Skapar en kod och returnerar den RÅA strängen - en enda gång.

        Därefter finns bara hashen. Den som tappar bort koden får en ny; det
        finns ingen väg att läsa ut den, och det är med avsikt."""
        raw = (code or new_code(prefix)).strip().upper()
        with self._lock:
            self._connection.execute(
                """INSERT OR REPLACE INTO premium_codes
                       (code_hash, label, grant_days, max_uses, uses, expires_at,
                        owner_user_id, created_at, revoked_at)
                   VALUES (?, ?, ?, ?,
                           COALESCE((SELECT uses FROM premium_codes WHERE code_hash = ?), 0),
                           ?, ?, ?, NULL)""",
                (hash_code(raw), str(label)[:80], int(grant_days),
                 (int(max_uses) if max_uses is not None else None), hash_code(raw),
                 expires_at, (int(owner_user_id) if owner_user_id is not None else None),
                 _now()))
            self._connection.commit()
        return raw

    def revoke(self, code: str) -> bool:
        """Stänger en kod. Redan utdelade dagar rörs inte - de är betalda i
        förtroende - men ingen ny inlösen går igenom. Det är skillnaden mot
        env-variabeln, som inte gick att stänga alls."""
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE premium_codes SET revoked_at = ? WHERE code_hash = ? AND revoked_at IS NULL",
                (_now(), hash_code(code)))
            self._connection.commit()
            return cursor.rowcount > 0

    # ---- läsa -------------------------------------------------------------

    def describe(self, code_hash: str) -> dict | None:
        row = self._connection.execute(
            "SELECT * FROM premium_codes WHERE code_hash = ?", (code_hash,)).fetchone()
        return dict(row) if row else None

    def owned_by(self, user_id) -> dict | None:
        """Kontots egen hänvisningskod, eller None. Ett konto har högst en."""
        row = self._connection.execute(
            """SELECT * FROM premium_codes WHERE owner_user_id = ? AND revoked_at IS NULL
               ORDER BY created_at DESC LIMIT 1""", (int(user_id),)).fetchone()
        return dict(row) if row else None

    def uses_of(self, code_hash: str) -> list:
        rows = self._connection.execute(
            "SELECT * FROM premium_code_uses WHERE code_hash = ? ORDER BY used_at",
            (code_hash,)).fetchall()
        return [dict(row) for row in rows]

    def pending_reward(self, user_id) -> dict | None:
        """Den obelönade inlösen som det här kontot gjorde, med ägaren.

        Det är kroken H5 hänger på: när den INBJUDNA skapar sin första vecka
        ska den som bjöd in få betalt. Returnerar None när kontot inte kommit
        in via en hänvisning, eller när belöningen redan betalats."""
        row = self._connection.execute(
            """SELECT u.code_hash, u.user_id, c.owner_user_id, c.grant_days, c.label
               FROM premium_code_uses u
               JOIN premium_codes c ON c.code_hash = u.code_hash
               WHERE u.user_id = ? AND u.rewarded_at IS NULL
                 AND c.owner_user_id IS NOT NULL""",
            (int(user_id),)).fetchone()
        return dict(row) if row else None

    def mark_rewarded(self, code_hash: str, user_id) -> bool:
        """Stämplar belöningen som betald. ATOMÄR: `rewarded_at IS NULL` i
        WHERE gör att två samtidiga "första veckan"-signaler inte kan betala
        ut två gånger."""
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE premium_code_uses SET rewarded_at = ?
                   WHERE code_hash = ? AND user_id = ? AND rewarded_at IS NULL""",
                (_now(), code_hash, int(user_id)))
            self._connection.commit()
            return cursor.rowcount > 0

    # ---- lösa in ----------------------------------------------------------

    def redeem(self, code: str, user_id: int) -> dict:
        """Löser in en kod för ett konto. Returnerar radens beskrivning
        (`grant_days`, `owner_user_id`, `label`, `code_hash`), eller kastar
        CodeError med ett besked som får visas.

        HELA KONTROLLEN LIGGER INUTI LÅSET, och räknaren skrivs upp i samma
        transaktion som kontrollen. Annars kan hundra samtidiga inlösningar av
        en kod med max_uses = 1 alla läsa uses = 0 och alla lyckas - vilket är
        precis vad som händer när en kod läggs ut på ett forum."""
        code_hash = hash_code(code)
        if not (code or "").strip():
            raise CodeError("Fel kod")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM premium_codes WHERE code_hash = ?", (code_hash,)).fetchone()
            if not row:
                raise CodeError("Fel kod")
            if row["revoked_at"]:
                raise CodeError("Koden gäller inte längre")
            if row["expires_at"] and row["expires_at"] <= _now():
                raise CodeError("Koden har gått ut")
            if row["max_uses"] is not None and row["uses"] >= row["max_uses"]:
                raise CodeError("Koden är slut")
            if row["owner_user_id"] is not None and int(row["owner_user_id"]) == int(user_id):
                # Annars är hänvisningsprogrammet en knapp som heter "ge mig
                # en gratismånad".
                raise CodeError("Du kan inte lösa in din egen kod")
            already = self._connection.execute(
                "SELECT 1 FROM premium_code_uses WHERE code_hash = ? AND user_id = ?",
                (code_hash, int(user_id))).fetchone()
            if already:
                raise CodeError("Du har redan löst in den här koden")
            self._connection.execute(
                "INSERT INTO premium_code_uses (code_hash, user_id, used_at) VALUES (?, ?, ?)",
                (code_hash, int(user_id), _now()))
            self._connection.execute(
                "UPDATE premium_codes SET uses = uses + 1 WHERE code_hash = ?", (code_hash,))
            self._connection.commit()
        return {"codeHash": code_hash, "grantDays": int(row["grant_days"]),
                "ownerUserId": row["owner_user_id"], "label": row["label"]}

    def forget_user(self, user_id) -> None:
        """GDPR: raderas kontot försvinner dess inlösningar och dess egen kod."""
        with self._lock:
            self._connection.execute(
                "DELETE FROM premium_code_uses WHERE user_id = ?", (int(user_id),))
            self._connection.execute(
                "DELETE FROM premium_codes WHERE owner_user_id = ?", (int(user_id),))
            self._connection.commit()

    # ---- drift ------------------------------------------------------------

    def summary(self) -> dict:
        """Vad kontrollrummet behöver: hur många koder som finns, hur många
        inlösningar de har och hur många av dem som är hänvisningar."""
        row = self._connection.execute(
            """SELECT COUNT(*) AS codes,
                      COALESCE(SUM(uses), 0) AS uses,
                      COALESCE(SUM(owner_user_id IS NOT NULL), 0) AS referral_codes
               FROM premium_codes WHERE revoked_at IS NULL""").fetchone()
        rewarded = self._connection.execute(
            "SELECT COUNT(*) FROM premium_code_uses WHERE rewarded_at IS NOT NULL").fetchone()[0]
        return {"koder": int(row["codes"]), "inlosningar": int(row["uses"]),
                "hanvisningskoder": int(row["referral_codes"]),
                "utbetaldaBeloningar": int(rewarded)}


def expiry_in(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=int(days))).isoformat()
