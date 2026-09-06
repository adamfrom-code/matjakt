# -*- coding: utf-8 -*-
"""Rate limiting - persistent i SQLite, med minnesläge för tester.

WHY. Utan spärr tar /api/auth/login obegränsade gissningar i obegränsad
fart. PBKDF2 med 200 000 iterationer gör varje försök dyrt för OSS, så en
angripare får både ett lösenordsorakel och ett billigt sätt att mätta
instansen. Registrering, återställning, kampanjskrap och prisanrop är samma
sorts problem.

TVÅ NYCKLAR, INTE EN. Bara IP låter ett botnät sprida gissningar över många
konton; bara konto låter en IP gå igenom en hel användarlista. Båda räknas,
och den som slår i först vinner.

PERSISTENT. Räknarna ligger i en egen SQLite-fil i datakatalogen
(`ratelimit.db`), så en deploy eller omstart förlåter inte en pågående
attack, och flera processer på samma disk delar samma räknare. Räcker för
en instans med disk; vid riktig horisontell skalning över flera diskar
krävs en central räknare (Redis INCR + EXPIRE) - se docs/RELEASE.md.

MINNESLÄGE. Utan `configure()` (tester, skript) används en dict i processen,
exakt som tidigare. `reset()` tömmer båda.
"""

import contextlib
import sqlite3
import threading
import time
from pathlib import Path

# (max attempts, window seconds) per action. Login is the tightest because
# it is the one that leaks whether a password is right.
LIMITS = {
    "login": (10, 300),           # 10 guesses / 5 min
    "register": (5, 3600),        # 5 new accounts / hour
    "password_reset": (5, 3600),  # 5 reset mails / hour
    # Inlösen av länken räknas för sig - den som begärt tre mejl och skrivit
    # fel två gånger ska fortfarande kunna sätta sitt lösenord.
    "password_reset_submit": (20, 3600),
    "change_password": (10, 3600),
    # A premium code is a credential; guessing it must cost as much as
    # guessing a password.
    "redeem": (10, 3600),
    # Utvecklingslåsets inloggning bär samma kod som redeem och får samma
    # gissningsbudget.
    "gate": (10, 3600),
    # Mejl på begäran: utan spärr kan vem som helst be servern bombardera en
    # adress den inte äger.
    "resend_verification": (5, 3600),
    # Fri text från vem som helst behöver ett lock.
    "feedback": (10, 3600),
    # Partnerfeeds: en butik behöver sällan mer än några leveranser i timmen.
    "partner_feed": (60, 3600),
    # Dyra eller öppna vägar: skydd mot missbruk, inte mot normal användning.
    # Per IP, och generöst nog för familjer bakom operatörs-NAT på mobilen.
    "pricing": (300, 60),          # pricing/week, pricing/list
    "search": (120, 60),           # receptsök
    "lookup": (120, 60),           # stores, geocode
    "scrape": (30, 60),            # campaigns, products, products/batch -> Chromium
    "analytics": (300, 60),        # beacon, förbi gaten
    "verify_email": (20, 3600),
    "delete_account": (5, 3600),
}

# Minnesläget: key -> [timestamps]. Hårt tak så en flod av olika nycklar inte
# kan växa utan gräns (en minnesläcka klädd som rate limiter).
MAX_TRACKED_KEYS = 20_000

_attempts: dict[str, list[float]] = {}
_lock = threading.Lock()
_connection: sqlite3.Connection | None = None
_db_path: str | None = None
_calls_since_prune = 0
PRUNE_EVERY_CALLS = 200


class RateLimited(Exception):
    """Raised when an action must be refused for now. `retry_after` is
    seconds until the oldest attempt in the window falls out of it."""

    def __init__(self, retry_after: int):
        super().__init__(f"För många försök. Försök igen om {retry_after} sekunder.")
        self.retry_after = retry_after


def configure(db_path) -> None:
    """Slår på det persistenta läget. Anropas en gång vid serverstart med en
    fil i datakatalogen. Idempotent för samma sökväg."""
    global _connection, _db_path
    with _lock:
        if _connection is not None and _db_path == str(db_path):
            return
        if _connection is not None:
            _connection.close()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS rate_limit_hits (action TEXT NOT NULL, identifier TEXT NOT NULL, ts REAL NOT NULL)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_rate_limit_hits ON rate_limit_hits (action, identifier, ts)")
        connection.commit()
        _connection, _db_path = connection, str(db_path)


def disable() -> None:
    """Tillbaka till minnesläget (tester)."""
    global _connection, _db_path
    with _lock:
        if _connection is not None:
            _connection.close()
        _connection, _db_path = None, None


def persistent() -> bool:
    return _connection is not None


def _longest_window() -> int:
    return max(window for _, window in LIMITS.values())


def _prune_memory(now: float):
    longest = _longest_window()
    stale = [key for key, hits in _attempts.items() if not hits or hits[-1] < now - longest]
    for key in stale:
        _attempts.pop(key, None)


def _check_memory(action: str, identifiers, limit: int, window: int, now: float):
    if len(_attempts) > MAX_TRACKED_KEYS:
        _prune_memory(now)
        if len(_attempts) > MAX_TRACKED_KEYS:
            _attempts.clear()
    for identifier in identifiers:
        key = f"{action}:{identifier}"
        hits = [hit for hit in _attempts.get(key, []) if hit > now - window]
        if len(hits) >= limit:
            _attempts[key] = hits
            raise RateLimited(int(hits[0] + window - now) + 1)
        hits.append(now)
        _attempts[key] = hits


def _check_db(action: str, identifiers, limit: int, window: int, now: float):
    global _calls_since_prune
    connection = _connection
    _calls_since_prune += 1
    if _calls_since_prune >= PRUNE_EVERY_CALLS:
        _calls_since_prune = 0
        connection.execute("DELETE FROM rate_limit_hits WHERE ts < ?", (now - _longest_window(),))
    for identifier in identifiers:
        row = connection.execute(
            "SELECT COUNT(*), MIN(ts) FROM rate_limit_hits WHERE action = ? AND identifier = ? AND ts > ?",
            (action, identifier, now - window)).fetchone()
        count, oldest = row[0], row[1]
        if count >= limit:
            connection.commit()
            raise RateLimited(int(oldest + window - now) + 1)
        connection.execute("INSERT INTO rate_limit_hits (action, identifier, ts) VALUES (?, ?, ?)",
                           (action, identifier, now))
    connection.commit()


def check(action: str, *identifiers: str) -> None:
    """Records one attempt at `action` for each identifier and raises
    RateLimited if any of them is over its limit.

    Identifiers are typically the client IP and the account email. Empty ones
    are skipped rather than collapsing into a shared bucket - a missing IP
    must not put every anonymous request in the same counter."""
    limit, window = LIMITS.get(action, (0, 0))
    if not limit:
        return
    now = time.time()
    wanted = [identifier for identifier in identifiers if identifier]
    with _lock:
        if _connection is not None:
            try:
                _check_db(action, wanted, limit, window, now)
                return
            except sqlite3.Error:
                # Databasen är trasig eller låst: hellre minnesläget än en
                # öppen dörr (eller en krasch på inloggningen).
                with contextlib.suppress(Exception):
                    _connection.rollback()
        _check_memory(action, wanted, limit, window, now)


def clear_on_success(action: str, *identifiers: str) -> None:
    """Forgets an identifier's attempts after it succeeds.

    Without this a person who mistypes their password a few times and then
    gets it right stays throttled for the rest of the window - punishing the
    legitimate user for the attacker's behaviour."""
    wanted = [identifier for identifier in identifiers if identifier]
    with _lock:
        for identifier in wanted:
            _attempts.pop(f"{action}:{identifier}", None)
        if _connection is not None and wanted:
            with contextlib.suppress(sqlite3.Error):
                _connection.executemany("DELETE FROM rate_limit_hits WHERE action = ? AND identifier = ?",
                                        [(action, identifier) for identifier in wanted])
                _connection.commit()


def reset() -> None:
    """Test-only: empties every counter, in both modes."""
    with _lock:
        _attempts.clear()
        if _connection is not None:
            with contextlib.suppress(sqlite3.Error):
                _connection.execute("DELETE FROM rate_limit_hits")
                _connection.commit()
