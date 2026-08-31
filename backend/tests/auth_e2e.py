# -*- coding: utf-8 -*-
"""End-to-end auth check against a RUNNING backend.

    python backend/tests/auth_e2e.py [--base http://127.0.0.1:8000/api]

Not part of `npm test` on purpose: it needs a live server and it writes real
rows into the real account database. It answers the question the unit tests
cannot - does a person's account and data actually survive logging out,
logging in from a fresh session, and the backend being restarted underneath
them.

Run it, restart the backend, then run it again with --token to prove the
session and the data survived the restart.

RESTART THE BACKEND BEFORE EACH FULL RUN. The login limiter is per IP and
in-memory, and one full run uses most of a five-minute budget - a second run
straight after gets 429s that look like broken logins. (That is exactly how
this script's first results read, and the failures were entirely its own
doing.)
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

PASSES, FAILURES = [], []


def check(name, condition, detail=""):
    (PASSES if condition else FAILURES).append(name)
    print(f"  {'✅' if condition else '❌'} {name}{f' — {detail}' if detail and not condition else ''}")
    return condition


def call(base, path, method="GET", body=None, token=None):
    request = urllib.request.Request(
        f"{base}{path}", method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"{}")
        except json.JSONDecodeError:
            return error.code, {}


# The settings a real user actually cares about surviving.
PROFILE = {
    "personer": 4, "middagar": 7, "budget": 1450, "postnummer": "21120",
    "butik": "City Gross", "favoriter": ["kycklinggryta", "lax"],
    "kost": {"kosttyp": "vegetarisk", "avoidAllergens": ["gluten", "laktos"]},
    "pantry": {"Ris": {"amount": 2, "location": "skafferi"}},
    "weekPlan": ["kycklinggryta", "pastagratang", "linssoppa", "korvstroganoff",
                 "tacobonor", "fiskpasta", "lax"],
    "onboardingComplete": True,
}


def profile_matches(remote):
    if not remote:
        return False, "ingen state alls"
    for key, expected in PROFILE.items():
        if remote.get(key) != expected:
            return False, f"{key}: {remote.get(key)!r} != {expected!r}"
    return True, ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000/api")
    parser.add_argument("--token", help="Existing session token, to re-check after a restart")
    parser.add_argument("--email", help="Existing account email (with --token)")
    parser.add_argument("--password", help="Existing account password (with --token)")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    if args.token:
        print("\n=== EFTER OMSTART: samma session, samma data ===")
        status, me = call(base, "/auth/me", token=args.token)
        check("Sessionen överlevde omstarten", status == 200, f"HTTP {status}")
        check("Kontot är samma", me.get("user", {}).get("email") == args.email,
              f"{me.get('user', {}).get('email')} != {args.email}")
        status, data = call(base, "/account/state", token=args.token)
        ok, why = profile_matches(data.get("state"))
        check("Användardatan överlevde omstarten", ok, why)
        if args.password:
            status, login = call(base, "/auth/login", "POST",
                                 {"email": args.email, "password": args.password})
            check("Inloggning fungerar efter omstart", status == 200, f"HTTP {status}")
            status, data = call(base, "/account/state", token=login.get("token"))
            ok, why = profile_matches(data.get("state"))
            check("Ny session ser samma data", ok, why)
        return report()

    stamp = int(time.time())
    email = f"e2e+{stamp}@matjakt.test"
    other_email = f"e2e-other+{stamp}@matjakt.test"
    password = "ett-riktigt-losenord"

    print("\n=== 1-2. REGISTRERA OCH LOGGA IN ===")
    status, created = call(base, "/auth/register", "POST", {"email": email, "password": password})
    check("Registrering skapar konto", status == 201, f"HTTP {status}: {created.get('error')}")
    token = created.get("token")
    check("Registrering ger en session", bool(token))

    status, dup = call(base, "/auth/register", "POST", {"email": email.upper(), "password": password})
    check("Samma e-post (annan skiftning) avvisas", status == 400,
          f"HTTP {status} - e-post normaliseras inte")

    print("\n=== 3-8. SPARA ANVÄNDARENS DATA ===")
    status, _ = call(base, "/account/state", "POST", PROFILE, token=token)
    check("Datan sparas mot kontot", status == 200, f"HTTP {status}")

    print("\n=== 9-11. LOGGA UT, LOGGA IN IGEN, DATAN FINNS KVAR ===")
    status, _ = call(base, "/auth/logout", "POST", token=token)
    check("Utloggning svarar OK", status == 200)
    status, _ = call(base, "/account/state", token=token)
    check("Den utloggade token fungerar inte längre", status in (401, 403), f"HTTP {status}")

    status, session = call(base, "/auth/login", "POST", {"email": email, "password": password})
    check("Inloggning efter utloggning", status == 200, f"HTTP {status}")
    fresh = session.get("token")
    check("Ny session har en annan token", fresh != token)

    status, data = call(base, "/account/state", token=fresh)
    ok, why = profile_matches(data.get("state"))
    check("All användardata finns kvar", ok, why)

    print("\n=== 15. SEPARAT SESSION (som en annan enhet) ===")
    status, second = call(base, "/auth/login", "POST", {"email": email, "password": password})
    second_token = second.get("token")
    status, data = call(base, "/account/state", token=second_token)
    ok, why = profile_matches(data.get("state"))
    check("En andra enhet ser samma data", ok, why)
    check("De två sessionerna är olika", second_token != fresh)

    print("\n=== SÄKERHET: ANVÄNDARISOLERING ===")
    status, other = call(base, "/auth/register", "POST",
                         {"email": other_email, "password": password})
    other_token = other.get("token")
    call(base, "/account/state", "POST", {"budget": 1, "postnummer": "00000"},
         token=other_token)
    status, data = call(base, "/account/state", token=other_token)
    check("Användare B ser SIN data, inte A:s",
          (data.get("state") or {}).get("budget") == 1,
          f"B fick {data.get('state')}")
    status, data = call(base, "/account/state", token=fresh)
    ok, _ = profile_matches(data.get("state"))
    check("Användare A:s data är orörd av B", ok)

    # The API takes no user id at all - the session decides who you are. Try
    # to smuggle one in anyway and confirm it changes nothing.
    call(base, "/account/state", "POST",
         {"budget": 999, "userId": 1, "user_id": 1, "email": email},
         token=other_token)
    status, data = call(base, "/account/state", token=fresh)
    ok, why = profile_matches(data.get("state"))
    check("Ett påhittat user_id i requesten ändrar ingenting", ok, why)

    status, _ = call(base, "/account/state", token="pahittad-token")
    check("En påhittad token avvisas", status in (401, 403), f"HTTP {status}")

    print("\n=== LÖSENORD ===")
    status, body = call(base, "/auth/change-password", "POST",
                        {"currentPassword": "fel", "newPassword": "nytt-losenord-123"},
                        token=fresh)
    check("Byte med fel nuvarande lösenord avvisas", status == 400, f"HTTP {status}")

    status, body = call(base, "/auth/change-password", "POST",
                        {"currentPassword": password, "newPassword": "nytt-losenord-123"},
                        token=fresh)
    check("Lösenordsbyte fungerar", status == 200, f"HTTP {status}: {body.get('error')}")
    status, _ = call(base, "/auth/login", "POST", {"email": email, "password": password})
    check("Det gamla lösenordet slutar fungera", status == 401, f"HTTP {status}")
    status, relogin = call(base, "/auth/login", "POST",
                           {"email": email, "password": "nytt-losenord-123"})
    check("Det nya lösenordet fungerar", status == 200, f"HTTP {status}")
    status, _ = call(base, "/account/state", token=second_token)
    check("Den andra enhetens session dödades av bytet", status in (401, 403), f"HTTP {status}")
    status, data = call(base, "/account/state", token=relogin.get("token"))
    ok, why = profile_matches(data.get("state"))
    check("Datan överlevde lösenordsbytet", ok, why)

    status, body = call(base, "/auth/request-password-reset", "POST", {"email": email})
    check("Glömt lösenord svarar OK", status == 200, f"HTTP {status}")
    status, body = call(base, "/auth/reset-password", "POST",
                        {"token": "pahittad", "password": "nytt-igen-12345"})
    check("Reset med påhittad token avvisas", status == 400, f"HTTP {status}")

    print("\n=== RADERA KONTO ===")
    status, _ = call(base, "/auth/delete-account", "POST", token=other_token)
    check("Kontoradering svarar OK", status == 200, f"HTTP {status}")
    status, _ = call(base, "/auth/me", token=other_token)
    check("Sessionen dör med kontot", status in (401, 403), f"HTTP {status}")
    status, _ = call(base, "/auth/login", "POST", {"email": other_email, "password": password})
    check("Det raderade kontot går inte att logga in på", status == 401, f"HTTP {status}")

    # Deliberately LAST: this exhausts the login budget for this IP, so any
    # login check placed after it would get a 429 instead of the answer it
    # was actually asking about. (That is exactly what happened the first
    # time this ran, and it looked like account deletion was broken.)
    print("\n=== RATE LIMITING ===")
    blocked = False
    for _ in range(15):
        status, _ = call(base, "/auth/login", "POST",
                         {"email": f"finns-inte+{stamp}@matjakt.test", "password": "fel"})
        if status == 429:
            blocked = True
            break
    check("Upprepade felaktiga inloggningar bromsas (429)", blocked)

    print(f"\nBEHÅLL FÖR OMSTARTSTESTET:\n  --email {email} --password nytt-losenord-123 "
          f"--token {relogin.get('token')}")
    return report()


def report():
    print(f"\n{'=' * 52}\n{len(PASSES)} godkända, {len(FAILURES)} underkända")
    for name in FAILURES:
        print(f"  ❌ {name}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
