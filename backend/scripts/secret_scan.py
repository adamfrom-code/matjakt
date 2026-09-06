# -*- coding: utf-8 -*-
"""Hemlighetsskanning av det spårade arbetsträdet - körs i CI och lokalt.

    python backend/scripts/secret_scan.py            # exit 1 vid träff

Letar efter riktigt nyckelmaterial (Stripe sk_live_/sk_test_/whsec_, Resend
re_..., privata nycklar, ifyllda SMTP_PASSWORD/PRIMAT_API_KEY/DABAS_API_KEY/
MATJAKT_ADMIN_TOKEN) i alla filer git spårar. Skriver ALDRIG ut värdet -
bara fil, rad och mönster. .env är gitignorerad och skannas inte.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = {
    "stripe live key": re.compile(r"sk_live_[A-Za-z0-9]{8,}"),
    "stripe test key": re.compile(r"sk_test_[A-Za-z0-9]{16,}"),
    "stripe webhook secret": re.compile(r"whsec_[A-Za-z0-9]{16,}"),
    "resend api key": re.compile(r"\bre_[A-Za-z0-9]{20,}"),
    "privat nyckel": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    # Bara ett CITERAT literal räknas: `PRIMAT_API_KEY = original_key` är kod,
    # `PRIMAT_API_KEY = "abcd…"` är en ifylld hemlighet.
    "ifylld hemlighet": re.compile(
        r"(?:SMTP_PASSWORD|PRIMAT_API_KEY|DABAS_API_KEY|MATJAKT_ADMIN_TOKEN|MATJAKT_PREMIUM_CODE|STRIPE_SECRET_KEY)"
        r"\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
}
# Testfixturer får bära uppenbart påhittade värden. Allt annat är skarpt.
ALLOWLIST = re.compile(r"(?:sk_test_(?:x|fake|abc123|hemlig|riktig)\b|whsec_(?:x|test|new|wrong)\b|PRIMAT_API_KEY\s*=\s*\"(?:hemlig|testnyckel))")
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".ico", ".db", ".lock", ".min.js", ".map", ".pdf")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return [line for line in out.stdout.splitlines() if line]


def main() -> int:
    hits = []
    for rel in tracked_files():
        if rel.endswith(SKIP_SUFFIXES) or "node_modules" in rel or "/venv/" in rel or rel.endswith("package-lock.json"):
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for name, pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    if ALLOWLIST.search(line):
                        continue
                    hits.append((rel, number, name, match.group(0)[:6] + "…"))
    if hits:
        print("HEMLIGHETER I SPÅRADE FILER:")
        for rel, number, name, masked in hits:
            print(f"  {rel}:{number}  [{name}]  {masked}")
        return 1
    print("secret_scan: inga hemligheter i spårade filer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
