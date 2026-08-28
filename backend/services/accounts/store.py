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
        self._connection.commit()

    @staticmethod
    def _to_public(row) -> dict:
        return {"email": row["email"], "premium": bool(row["premium"])}

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
        return self._create_session(user_id), {"email": email, "premium": False}

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

    def user_for_token(self, token: str) -> dict | None:
        if not token:
            return None
        row = self._connection.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
        return self._to_public(row) if row else None

    def redeem_premium(self, token: str, code: str, expected_code: str) -> dict:
        if not expected_code:
            raise AccountError("Premium-inlösen är inte konfigurerad på servern")
        if not code or not secrets.compare_digest(code, expected_code):
            raise AccountError("Fel kod")
        row = self._connection.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
        if not row:
            raise AccountError("Du måste vara inloggad")
        self._connection.execute("UPDATE users SET premium = 1 WHERE id = ?", (row["id"],))
        self._connection.commit()
        return {"email": row["email"], "premium": True}
