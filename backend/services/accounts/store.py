"""SQLite-backed user accounts and sessions.

Kept deliberately small: stdlib only (sqlite3, hashlib, secrets), no ORM. Password
hashes use PBKDF2-HMAC-SHA256 with a per-user random salt, which needs no extra
dependency beyond what ships with Python.

Session tokens are stored as SHA-256 hashes, never raw - see _session_key.
The raw token exists in exactly two places: the client that holds it, and the
single response that handed it over.

NOT YET HASHED: the password-reset and e-mail-verification tokens on the
users table. They are single-use and short-lived (the reset token carries an
explicit expiry), so a leak of them is a much smaller window than a leak of
30-day session tokens - but they are still bearer credentials sitting in
plain text, and hashing them the same way is the obvious next step.
"""

import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_TTL_DAYS = 30
PBKDF2_ITERATIONS = 200_000


class AccountError(Exception):
    """Raised for user-facing account errors (bad input, wrong password, ...)."""


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()


def _session_key(token: str) -> str:
    """What we store for a session: SHA-256 of the token the client holds.

    The raw token is a bearer credential - anyone holding it IS the user
    until it expires. Storing it verbatim meant a database leak (a backup, a
    stray copy of the Render disk, an SQL injection anywhere) handed over
    every live session, not just password hashes an attacker still has to
    crack. Hashing makes the stored value useless on its own.

    Plain SHA-256 rather than PBKDF2, deliberately: a session token is 32
    bytes of output from secrets.token_urlsafe, so there is no dictionary to
    attack and nothing for a slow KDF to buy. It is also checked on every
    single request, where PBKDF2's cost would be paid by us, not the
    attacker."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


class AccountStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                premium INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                expires_at TEXT NOT NULL
            );
            """
        )
        # Added after the initial release - ALTER TABLE guarded with try/except since
        # sqlite3 has no "ADD COLUMN IF NOT EXISTS" and this file has no migration runner.
        for column, definition in (
            ("trial_ends_at", "TEXT"), ("trial_used", "INTEGER NOT NULL DEFAULT 0"),
            ("stripe_customer_id", "TEXT"), ("stripe_subscription_id", "TEXT"),
            ("subscription_status", "TEXT"), ("subscription_plan", "TEXT"),
            ("subscription_period_end", "TEXT"), ("subscription_cancel_at_period_end", "INTEGER NOT NULL DEFAULT 0"),
            ("synced_state", "TEXT"),
            ("email_verified", "INTEGER NOT NULL DEFAULT 0"), ("verification_token", "TEXT"),
            ("reset_token", "TEXT"), ("reset_token_expires_at", "TEXT"),
        ):
            try:
                self._connection.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass
        self._migrate_session_tokens_to_hashes()
        self._connection.commit()

    def _migrate_session_tokens_to_hashes(self):
        """Rewrites any session row still holding a RAW token as its hash.

        This keeps everyone logged in: the client presents the same raw token
        it always did, and it now hashes to the value stored here. Deleting
        the rows instead would have signed out every user on the deploy that
        shipped this, for no security benefit.

        Migrated rows are told apart by length: a SHA-256 hex digest is 64
        characters, while secrets.token_urlsafe(32) is always 43. Running
        this twice is therefore a no-op rather than a double-hash that would
        lock everybody out."""
        rows = self._connection.execute(
            "SELECT token FROM sessions WHERE length(token) != 64").fetchall()
        for row in rows:
            self._connection.execute(
                "UPDATE sessions SET token = ? WHERE token = ?",
                (_session_key(row["token"]), row["token"]),
            )

    @staticmethod
    def _to_public(row) -> dict:
        keys = row.keys()
        trial_ends_at = row["trial_ends_at"] if "trial_ends_at" in keys else None
        trial_active = bool(trial_ends_at) and trial_ends_at > datetime.now(timezone.utc).isoformat()
        sub_status = row["subscription_status"] if "subscription_status" in keys else None
        subscription_active = sub_status in ("active", "trialing")
        premium_active = bool(row["premium"]) or trial_active or subscription_active
        plan_raw = row["subscription_plan"] if "subscription_plan" in keys else None
        return {
            "email": row["email"],
            "premium": premium_active,
            # The plan name the feature system keys on. Derived here so every
            # consumer (auth/me, entitlements, tests) agrees on one answer.
            "plan": ("premium_yearly" if premium_active and plan_raw and "year" in str(plan_raw).lower()
                     else "premium_monthly" if premium_active else "free"),
            "trialEndsAt": trial_ends_at if trial_active else None,
            "trialUsed": bool(row["trial_used"]) if "trial_used" in keys else False,
            "subscriptionStatus": sub_status,
            "subscriptionPlan": row["subscription_plan"] if "subscription_plan" in keys else None,
            "subscriptionPeriodEnd": row["subscription_period_end"] if "subscription_period_end" in keys else None,
            "subscriptionCancelAtPeriodEnd": bool(row["subscription_cancel_at_period_end"]) if "subscription_cancel_at_period_end" in keys else False,
            "emailVerified": bool(row["email_verified"]) if "email_verified" in keys else False,
        }

    def register(self, email: str, password: str) -> tuple[str, dict]:
        email = (email or "").strip().lower()
        if not EMAIL_PATTERN.match(email):
            raise AccountError("Ange en giltig e-postadress")
        if not password or len(password) < 8:
            raise AccountError("Lösenordet måste vara minst 8 tecken")
        salt = secrets.token_bytes(16)
        password_hash = _hash_password(password, salt)
        try:
            cursor = self._connection.execute(
                "INSERT INTO users (email, password_hash, salt, premium, created_at) VALUES (?, ?, ?, 0, ?)",
                (email, password_hash, salt.hex(), datetime.now(timezone.utc).isoformat()),
            )
            self._connection.commit()
        except sqlite3.IntegrityError:
            raise AccountError("Det finns redan ett konto med den e-postadressen")
        user_id = cursor.lastrowid
        row = self._connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._create_session(user_id), self._to_public(row)

    def login(self, email: str, password: str) -> tuple[str, dict]:
        email = (email or "").strip().lower()
        row = self._connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            raise AccountError("Fel e-post eller lösenord")
        expected = _hash_password(password or "", bytes.fromhex(row["salt"]))
        if not secrets.compare_digest(expected, row["password_hash"]):
            raise AccountError("Fel e-post eller lösenord")
        return self._create_session(row["id"]), self._to_public(row)

    def _create_session(self, user_id: int) -> str:
        """Returns the RAW token - the only moment it exists outside the
        client. Only its hash is written down."""
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()
        self._connection.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (_session_key(token), user_id, expires_at),
        )
        self._connection.commit()
        return token

    def close(self):
        self._connection.close()

    def logout(self, token: str):
        self._connection.execute("DELETE FROM sessions WHERE token = ?", (_session_key(token),))
        self._connection.commit()

    def _session_user_row(self, token: str):
        if not token:
            return None
        return self._connection.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (_session_key(token), datetime.now(timezone.utc).isoformat()),
        ).fetchone()

    def user_for_token(self, token: str) -> dict | None:
        row = self._session_user_row(token)
        return self._to_public(row) if row else None

    def redeem_premium(self, token: str, code: str, expected_code: str) -> dict:
        if not expected_code:
            raise AccountError("Premium-inlösen är inte konfigurerad på servern")
        if not code or not secrets.compare_digest(code, expected_code):
            raise AccountError("Fel kod")
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        self._connection.execute("UPDATE users SET premium = 1 WHERE id = ?", (row["id"],))
        self._connection.commit()
        return self._to_public(self._session_user_row(token))

    # start_trial är borttagen (affärsmodell 2026-08-31: Free / 59 kr/mån /
    # 399 kr/år, INGEN provperiod). Kolumnerna trial_ends_at/trial_used finns
    # kvar enbart för grandfathering av redan utdelade trials - läsvägen ovan
    # respekterar dem tills de löpt ut, men ingenting kan bevilja nya.
    def billing_identity_for_token(self, token):
        """Returns (user_id, email, existing_stripe_customer_id_or_None) for a session token."""
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        return row["id"], row["email"], row["stripe_customer_id"]

    def set_stripe_customer_id(self, user_id, customer_id):
        self._connection.execute("UPDATE users SET stripe_customer_id = ? WHERE id = ?", (customer_id, user_id))
        self._connection.commit()

    def stripe_customer_id_for_token(self, token):
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        if not row["stripe_customer_id"]:
            raise AccountError("Ingen prenumeration hittades för det här kontot")
        return row["stripe_customer_id"]

    # ---- Testarfeedback (anonym) -------------------------------------------
    # Fri text + vilken skärm den skrevs från. INGEN användarkoppling, ingen
    # IP, inget konto - fem testpersoner ska kunna säga vad som skaver utan
    # att lämna personuppgifter.
    MAX_FEEDBACK_CHARS = 2000

    def add_feedback(self, screen: str, text: str):
        text = (text or "").strip()[: self.MAX_FEEDBACK_CHARS]
        if not text:
            raise AccountError("Skriv något först")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS feedback_notes (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   created_at TEXT NOT NULL,
                   screen TEXT,
                   text TEXT NOT NULL)""")
        self._connection.execute(
            "INSERT INTO feedback_notes (created_at, screen, text) VALUES (?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), (screen or "")[:40], text))
        self._connection.commit()

    def list_feedback(self, limit: int = 200) -> list[dict]:
        try:
            rows = self._connection.execute(
                "SELECT created_at, screen, text FROM feedback_notes ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        except Exception:
            return []
        return [{"createdAt": r[0], "screen": r[1], "text": r[2]} for r in rows]

    def get_synced_state(self, token) -> str | None:
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        return row["synced_state"]

    # Ett kontos synkade state är veckor, skafferi och inställningar - några
    # tiotal kB. Utan tak delar varje konto skrivrätt till samma 1GB-disk som
    # prisdatabasen, och EN illasinnad klient kan fylla den tills varje
    # skrivning i hela tjänsten fallerar.
    MAX_SYNCED_STATE_BYTES = 200 * 1024

    def set_synced_state(self, token, state_json: str):
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        if len((state_json or "").encode("utf-8")) > self.MAX_SYNCED_STATE_BYTES:
            raise AccountError("Datat är för stort för att sparas")
        self._connection.execute("UPDATE users SET synced_state = ? WHERE id = ?", (state_json, row["id"]))
        self._connection.commit()

    def apply_subscription_event(self, customer_id, subscription_id, status, period_end_iso, cancel_at_period_end, plan):
        self._connection.execute(
            """UPDATE users SET stripe_subscription_id = ?, subscription_status = ?, subscription_period_end = ?,
               subscription_cancel_at_period_end = ?, subscription_plan = ? WHERE stripe_customer_id = ?""",
            (subscription_id, status, period_end_iso, int(cancel_at_period_end), plan, customer_id),
        )
        self._connection.commit()

    def _create_verification_token(self, user_id) -> str:
        token = secrets.token_urlsafe(24)
        self._connection.execute("UPDATE users SET verification_token = ? WHERE id = ?", (token, user_id))
        self._connection.commit()
        return token

    def create_verification_token_for_email(self, email: str) -> str:
        row = self._connection.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
        if not row:
            raise AccountError("Okänt konto")
        return self._create_verification_token(row["id"])

    def verify_email(self, token: str) -> dict:
        if not token:
            raise AccountError("Ogiltig verifieringslänk")
        row = self._connection.execute("SELECT * FROM users WHERE verification_token = ?", (token,)).fetchone()
        if not row:
            raise AccountError("Ogiltig eller redan använd verifieringslänk")
        self._connection.execute(
            "UPDATE users SET email_verified = 1, verification_token = NULL WHERE id = ?", (row["id"],)
        )
        self._connection.commit()
        return self._to_public(self._connection.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone())

    def resend_verification(self, token: str):
        """Returns (email, verification_token) for the logged-in user's session token."""
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        if row["email_verified"]:
            raise AccountError("E-postadressen är redan verifierad")
        return row["email"], self._create_verification_token(row["id"])

    def request_password_reset(self, email: str) -> str | None:
        """Returns a reset token if the email matches an account, else None. Callers
        must respond identically either way (don't reveal whether the email exists)."""
        row = self._connection.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
        if not row:
            return None
        token = secrets.token_urlsafe(24)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self._connection.execute(
            "UPDATE users SET reset_token = ?, reset_token_expires_at = ? WHERE id = ?", (token, expires_at, row["id"])
        )
        self._connection.commit()
        return token

    def reset_password(self, token: str, new_password: str):
        if not new_password or len(new_password) < 8:
            raise AccountError("Lösenordet måste vara minst 8 tecken")
        if not token:
            raise AccountError("Länken är ogiltig eller har gått ut")
        row = self._connection.execute("SELECT * FROM users WHERE reset_token = ?", (token,)).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        if not row or not row["reset_token_expires_at"] or row["reset_token_expires_at"] < now:
            raise AccountError("Länken är ogiltig eller har gått ut")
        salt = secrets.token_bytes(16)
        password_hash = _hash_password(new_password, salt)
        self._connection.execute(
            "UPDATE users SET password_hash = ?, salt = ?, reset_token = NULL, reset_token_expires_at = NULL WHERE id = ?",
            (password_hash, salt.hex(), row["id"]),
        )
        # A password reset invalidates every existing session on every device -
        # including whoever might have been using a compromised one.
        self._connection.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        self._connection.commit()

    def change_password(self, token: str, current_password: str, new_password: str) -> dict:
        """Changes a logged-in user's password.

        The CURRENT password is required even though the session already
        proves who this is: a borrowed or stolen session must not be enough
        to lock the real owner out of their own account.

        Every OTHER session is dropped afterwards. A password change is what
        a person does when they think someone else has access, and leaving
        those sessions alive would make the change cosmetic. The session
        doing the change survives, so the user is not logged out of the
        device they are holding."""
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        expected = _hash_password(current_password or "", bytes.fromhex(row["salt"]))
        if not secrets.compare_digest(expected, row["password_hash"]):
            raise AccountError("Fel nuvarande lösenord")
        if not new_password or len(new_password) < 8:
            raise AccountError("Det nya lösenordet måste vara minst 8 tecken")
        if secrets.compare_digest(_hash_password(new_password, bytes.fromhex(row["salt"])), row["password_hash"]):
            raise AccountError("Det nya lösenordet måste skilja sig från det nuvarande")
        salt = secrets.token_bytes(16)
        self._connection.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
            (_hash_password(new_password, salt), salt.hex(), row["id"]),
        )
        self._connection.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token != ?",
            (row["id"], _session_key(token)))
        self._connection.commit()
        return self._to_public(self._session_user_row(token))

    def delete_account(self, token: str):
        """Returns (stripe_customer_id, stripe_subscription_id) so the caller can
        cancel any active Stripe subscription before the account record is gone."""
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        stripe_customer_id, stripe_subscription_id = row["stripe_customer_id"], row["stripe_subscription_id"]
        self._connection.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
        self._connection.execute("DELETE FROM users WHERE id = ?", (row["id"],))
        self._connection.commit()
        return stripe_customer_id, stripe_subscription_id
