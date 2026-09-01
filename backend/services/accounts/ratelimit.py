# -*- coding: utf-8 -*-
"""Rate limiting for the authentication endpoints.

WHY. Without this, /api/auth/login accepts unlimited guesses at unlimited
speed. PBKDF2 at 200 000 iterations makes each attempt cost us real CPU, so
an attacker gets both a password oracle AND a cheap way to saturate the one
Render instance we run on. /api/auth/register and the password-reset
endpoints are the same shape of problem: free account creation, and a way to
have us send unlimited mail to an address we do not control.

TWO KEYS, NOT ONE. Limiting by IP alone lets one attacker spread guesses
across many accounts from a botnet; limiting by account alone lets one IP
walk a whole user list. Both are counted, and whichever trips first wins.

IN MEMORY, ON PURPOSE - AND ONLY WHILE WE RUN ONE INSTANCE. The backend is a
single process on a single Render instance (see MATJAKT_MAX_SCRAPES and the
OOM history), so a shared store would be infrastructure for a problem we do
not have. Two tradeoffs, both deliberate:

  - A restart forgives every counter. Acceptable for slowing down guessing;
    not acceptable as the ONLY defence, which is why passwords are also
    PBKDF2-hashed with a per-user salt.

  - THE LIMIT IS PER PROCESS. The moment we run more than one backend
    instance - a second Render instance, any autoscaling, a blue/green
    deploy that overlaps - each one keeps its own counters, so the effective
    limit becomes (limit x instances) and an attacker simply spreads guesses
    across them. THIS MODULE MUST THEN BE REPLACED with a shared counter
    (Redis INCR with EXPIRE is the obvious fit), not merely tuned. Treat
    "we scaled to two instances" as a change that silently weakens auth
    until this is done.
"""

import threading
import time

# (max attempts, window seconds) per action. Login is the tightest because
# it is the one that leaks whether a password is right.
LIMITS = {
    "login": (10, 300),           # 10 guesses / 5 min
    "register": (5, 3600),        # 5 new accounts / hour
    "password_reset": (5, 3600),  # 5 reset mails / hour
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
}

# A single dict of key -> [timestamps]. Pruned as it goes, and hard-capped so
# a flood of distinct keys cannot grow it without bound (which would be a
# memory-exhaustion bug dressed up as a rate limiter).
MAX_TRACKED_KEYS = 20_000

_attempts: dict[str, list[float]] = {}
_lock = threading.Lock()


class RateLimited(Exception):
    """Raised when an action must be refused for now. `retry_after` is
    seconds until the oldest attempt in the window falls out of it."""

    def __init__(self, retry_after: int):
        super().__init__(f"För många försök. Försök igen om {retry_after} sekunder.")
        self.retry_after = retry_after


def _prune(now: float):
    longest = max(window for _, window in LIMITS.values())
    stale = [key for key, hits in _attempts.items() if not hits or hits[-1] < now - longest]
    for key in stale:
        _attempts.pop(key, None)


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
    with _lock:
        if len(_attempts) > MAX_TRACKED_KEYS:
            _prune(now)
            if len(_attempts) > MAX_TRACKED_KEYS:
                _attempts.clear()
        for identifier in identifiers:
            if not identifier:
                continue
            key = f"{action}:{identifier}"
            hits = [hit for hit in _attempts.get(key, []) if hit > now - window]
            if len(hits) >= limit:
                _attempts[key] = hits
                raise RateLimited(int(hits[0] + window - now) + 1)
            hits.append(now)
            _attempts[key] = hits


def clear_on_success(action: str, *identifiers: str) -> None:
    """Forgets an identifier's attempts after it succeeds.

    Without this a person who mistypes their password a few times and then
    gets it right stays throttled for the rest of the window - punishing the
    legitimate user for the attacker's behaviour."""
    with _lock:
        for identifier in identifiers:
            if identifier:
                _attempts.pop(f"{action}:{identifier}", None)


def reset() -> None:
    """Test-only: empties every counter."""
    with _lock:
        _attempts.clear()
