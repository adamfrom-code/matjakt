# -*- coding: utf-8 -*-
"""Hemlighetsskanning av det spårade arbetsträdet - körs i CI och lokalt.

    python backend/scripts/secret_scan.py            # exit 1 vid träff

Letar efter riktigt nyckelmaterial (Stripe sk_live_/sk_test_/whsec_, Resend
re_..., privata nycklar, ifyllda SMTP_PASSWORD/PRIMAT_API_KEY/DABAS_API_KEY/
MATJAKT_ADMIN_TOKEN) i alla filer git spårar. Skriver ALDRIG ut värdet -
bara fil, rad och mönster. .env är gitignorerad och skannas inte.

Plus en kontroll som inte är ett mönster utan en plats: butiksmetadatan
under store/. Den bär ett granskningskonto som ska fyllas i i App Store
Connects egna fält, inte i en spårad fil, och mallen har hakparenteser för
att göra det tydligt. En gång låg ett riktigt lösenord i arbetsträdet,
oskrivet men en `git add -A` från att bli publicerat för alltid. Inget
mönster fångade det - ett lösenord ser ut som vilket ord som helst - så
kontrollen utgår från raden i stället: står det "Lösenord:" och något som
inte är en platshållare efter, är det ifyllt.
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
    "github token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"),
    "aws access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "anthropic/openai key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{24,}"),
    "slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),
    # Bara ett CITERAT literal räknas: `PRIMAT_API_KEY = original_key` är kod,
    # `PRIMAT_API_KEY = "abcd…"` är en ifylld hemlighet.
    "ifylld hemlighet": re.compile(
        r"(?:SMTP_PASSWORD|PRIMAT_API_KEY|DABAS_API_KEY|MATJAKT_ADMIN_TOKEN|MATJAKT_PREMIUM_CODE|MATJAKT_MAIL_SECRET|STRIPE_SECRET_KEY)"
        r"\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
}
# Testfixturer får bära uppenbart påhittade värden. Allt annat är skarpt.
ALLOWLIST = re.compile(r"(?:sk_test_(?:x|fake|abc123|hemlig|riktig)\b|whsec_(?:x|test|new|wrong)\b|PRIMAT_API_KEY\s*=\s*\"(?:hemlig|testnyckel))")
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".ico", ".db", ".lock", ".min.js", ".map", ".pdf")

# Butiksmetadatan: raderna som ska stå tomma, och vad som räknas som tomt.
# En platshållare är hakparentes, bindestreck eller ingenting alls.
BUTIKSMETADATA = "store/"
KONTORAD = re.compile(r"(?i)^\s*(lösenord|password|e-post|epost|email|användarnamn|username)\s*:\s*(.*)$")
PLATSHALLARE = re.compile(r"^(?:\[.*\]|-+|)\s*$")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    return [line for line in out.stdout.splitlines() if line]


def granskningskontot(rel: str, text: str) -> list[tuple[str, int, str, str]]:
    """Ett ifyllt granskningskonto i butiksmetadatan.

    Kontot hör hemma i App Store Connects App Review Information, inte i
    repot - och repot är publikt. Mallen har hakparenteser; allt annat är
    ifyllt. Värdet skrivs aldrig ut, bara vilken rad det står på.
    """
    if not rel.startswith(BUTIKSMETADATA):
        return []
    träffar = []
    for number, line in enumerate(text.splitlines(), 1):
        match = KONTORAD.match(line)
        if match and not PLATSHALLARE.match(match.group(2)):
            träffar.append((rel, number, f"ifyllt granskningskonto ({match.group(1).lower()})", "…"))
    return träffar


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
                    # Allowlisten prövas mot TRÄFFEN, inte raden: ett fejkvärde
                    # på samma rad som en äkta nyckel ska inte tysta nyckeln.
                    if ALLOWLIST.search(match.group(0)) or ALLOWLIST.search(line[max(0, match.start() - 40):match.end()]):
                        continue
                    hits.append((rel, number, name, match.group(0)[:6] + "…"))
        hits.extend(granskningskontot(rel, text))
    if hits:
        print("HEMLIGHETER I SPÅRADE FILER:")
        for rel, number, name, masked in hits:
            print(f"  {rel}:{number}  [{name}]  {masked}")
        return 1
    print("secret_scan: inga hemligheter i spårade filer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
