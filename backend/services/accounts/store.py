"""SQLite-backed user accounts and sessions.

Kept deliberately small: stdlib only (sqlite3, hashlib, secrets), no ORM. Password
hashes use PBKDF2-HMAC-SHA256 with a per-user random salt, which needs no extra
dependency beyond what ships with Python.
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
        self._connection.commit()

    @staticmethod
    def _to_public(row) -> dict:
        keys = row.keys()
        trial_ends_at = row["trial_ends_at"] if "trial_ends_at" in keys else None
        trial_active = bool(trial_ends_at) and trial_ends_at > datetime.now(timezone.utc).isoformat()
        sub_status = row["subscription_status"] if "subscription_status" in keys else None
        subscription_active = sub_status in ("active", "trialing")
        return {
            "email": row["email"],
            "premium": bool(row["premium"]) or trial_active or subscription_active,
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
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()
        self._connection.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)", (token, user_id, expires_at)
        )
        self._connection.commit()
        return token

    def close(self):
        self._connection.close()

    def logout(self, token: str):
        self._connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
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
            (token, datetime.now(timezone.utc).isoformat()),
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

    def start_trial(self, token: str) -> dict:
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        if row["premium"]:
            raise AccountError("Du har redan Premium")
        if row["trial_used"]:
            raise AccountError("Du har redan använt din gratis provperiod")
        trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
        self._connection.execute(
            "UPDATE users SET trial_ends_at = ?, trial_used = 1 WHERE id = ?", (trial_ends_at, row["id"])
        )
        self._connection.commit()
        return self._to_public(self._session_user_row(token))

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

    def get_synced_state(self, token) -> str | None:
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
        return row["synced_state"]

    def set_synced_state(self, token, state_json: str):
        row = self._session_user_row(token)
        if not row:
            raise AccountError("Du måste vara inloggad")
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
