# -*- coding: utf-8 -*-
"""Acceptance test: does PRODUCTION keep its data across a deploy?

    Fas 1, före deploy:   python backend/tests/prod_persistence_e2e.py --before
    (deploya/starta om backend)
    Fas 2, efter deploy:  python backend/tests/prod_persistence_e2e.py --after \
                              --email ... --password ... --products N

Exists because production LOST a completed 10 837-product import on an
ordinary deploy - render.yaml declared a disk, but that block only applies to
Blueprint-managed services, and this service was created by hand. The lesson:
a setting is not evidence. This script is the evidence.

--before registers a fresh account, saves real user data on it, and prints
the exact command line for phase two. --after verifies every claim:
the mounted flag, the product count, the collector-run history, the login,
the user data, and that the scheduler came back.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://matjakt.onrender.com/api"
PASSES, FAILURES = [], []

PROFILE = {"personer": 4, "middagar": 7, "budget": 1450, "postnummer": "21120",
           "butik": "Willys", "favoriter": ["kycklinggryta"]}


def check(name, condition, detail=""):
    (PASSES if condition else FAILURES).append(name)
    print(f"  {'✅' if condition else '❌'} {name}{f' — {detail}' if detail and not condition else ''}")


def call(path, method="GET", body=None, token=None):
    request = urllib.request.Request(
        f"{BASE}{path}", method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"{}")
        except json.JSONDecodeError:
            return error.code, {}


def grocery_status():
    status, data = call("/grocery/status")
    if status != 200:
        raise SystemExit(f"/grocery/status svarade HTTP {status}")
    return data


def before():
    data = grocery_status()
    storage = data.get("storage") or {}
    print("\n=== LÄGE FÖRE DEPLOY ===")
    print(f"  mounted disk : {storage.get('mounted')}")
    print(f"  produkter    : {data.get('totalProducts')}")
    if not storage.get("mounted"):
        print("\n⚠️  storage.mounted är INTE true - disken är inte monterad på")
        print("    /app/backend/data. Att köra vidare bevisar bara att data")
        print("    försvinner. Åtgärda disken i Render först.")

    stamp = int(time.time())
    email = f"persist-e2e+{stamp}@matjakt.test"
    password = "ett-riktigt-losenord"
    status, created = call("/auth/register", "POST", {"email": email, "password": password})
    check("Testkonto skapat", status == 201, f"HTTP {status}: {created.get('error')}")
    token = created.get("token")
    status, _ = call("/account/state", "POST", PROFILE, token=token)
    check("Användardata sparad", status == 200, f"HTTP {status}")

    print("\n=== DEPLOYA/STARTA OM NU, kör sedan: ===")
    print(f"python backend/tests/prod_persistence_e2e.py --after "
          f"--email {email} --password {password} --products {data.get('totalProducts')}")
    return 0 if not FAILURES else 1


def after(email, password, products_before):
    data = grocery_status()
    storage = data.get("storage") or {}
    scheduler = data.get("scheduler") or {}
    willys = next((p for p in data.get("providers", []) if p["chain"] == "Willys"), {})

    print("\n=== EFTER DEPLOY ===")
    check("Persistent disk monterad (storage.mounted)", storage.get("mounted") is True)
    total = data.get("totalProducts") or 0
    # >= rather than ==: the nightly job may legitimately have ADDED products
    # in between. What must never happen is losing them.
    check(f"Produkterna finns kvar ({total} >= {products_before})", total >= products_before,
          f"{total} < {products_before}")
    check("Körningshistoriken överlevde (lastSuccessfulRun finns)",
          bool(willys.get("lastSuccessfulRun")))
    check("Bootstrap startade INTE om (databasen var inte tom)",
          (willys.get("lastRun") or {}).get("status") != "running" or total > 0)

    status, session = call("/auth/login", "POST", {"email": email, "password": password})
    check("Testkontot går att logga in på", status == 200, f"HTTP {status}: {session.get('error')}")
    if status == 200:
        status, state = call("/account/state", token=session.get("token"))
        saved = state.get("state") or {}
        ok = all(saved.get(k) == v for k, v in PROFILE.items())
        bad = {k: saved.get(k) for k, v in PROFILE.items() if saved.get(k) != v}
        check("Användardatan finns kvar", ok, f"avvikelser: {bad}")

    check("Nattjobben är på efter omstart", scheduler.get("enabled") is True)
    runs = {entry["chain"]: entry.get("nextRunAt") for entry in scheduler.get("schedule", [])}
    check("Alla tre kedjor har en nästa körning", all(runs.get(c) for c in ("Willys", "Hemköp", "City Gross")),
          str(runs))

    print(f"\n{'=' * 50}\n{len(PASSES)} godkända, {len(FAILURES)} underkända")
    for name in FAILURES:
        print(f"  ❌ {name}")
    if not FAILURES:
        print("\nPRODUCTION GROCERY PERSISTENCE: ✅")
        print("USER DATA PERSISTENCE: ✅")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", action="store_true")
    parser.add_argument("--after", action="store_true")
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--products", type=int, default=0)
    args = parser.parse_args()
    if args.before:
        sys.exit(before())
    elif args.after:
        if not (args.email and args.password):
            parser.error("--after kräver --email och --password från fas 1")
        sys.exit(after(args.email, args.password, args.products))
    else:
        parser.error("ange --before eller --after")
