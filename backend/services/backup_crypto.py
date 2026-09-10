# -*- coding: utf-8 -*-
"""Backuparkivet lämnar aldrig processen i klartext.

WHY. `/api/admin/backup-download` skickade `matjakt.db` som den ligger: varje
e-postadress i klartext, hela `synced_state` och all fritextfeedback för
samtliga konton. Mellan internet och den filen stod en enda headerhemlighet -
och den sortens hemlighet läcker (det har redan hänt en gång i det här repot,
commit `27edd8a`). Ett krypterat arkiv gör läckan värdelös: den som får tag i
filen får en binärklump.

BARA DEN PUBLIKA NYCKELN PÅ SERVERN. Hela poängen. Servern kan kryptera men
inte dekryptera; den privata nyckeln ligger på Adams maskin och sätts aldrig
som miljövariabel på Render. Blir servern helt övertagen finns ingen nyckel
att stjäla - varken för de nya arkiven eller för de gamla.

TRE FORMAT, VALDA AV NYCKELNS FORM. Ingen flagga att glömma:

    -----BEGIN CERTIFICATE-----          -> openssl cms (rekommenderat)
    age1... / ssh-ed25519 ... / ssh-rsa  -> age
    -----BEGIN PGP PUBLIC KEY BLOCK----- -> gpg

`openssl` är rekommendationen därför att binären redan finns överallt vi kör
- utvecklarmaskinen, CI och Playwright-imagen - så vägen går att bevisa med
ett test i stället för att antas. `age` och `gpg` fungerar när binären finns.

FAIL CLOSED. Saknas nyckel, är formen okänd eller saknas verktyget: inget
arkiv skickas. Att svara "krypteringen är inte konfigurerad, här är
databasen" vore att bygga tillbaka exakt det hål paketet stänger.
"""

import base64
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PUBLIC_KEY_ENV = "MATJAKT_BACKUP_PUBLIC_KEY"

# Suffixet talar om för mottagaren hur filen öppnas igen (se scripts/pull_backup.py).
EXTENSIONS = {"cms": ".cms", "age": ".age", "gpg": ".gpg"}
TOOLS = {"cms": ("openssl",), "age": ("age", "rage"), "gpg": ("gpg", "gpg2")}

_AGE_RECIPIENT = re.compile(r"^(age1[0-9a-z]{20,}|ssh-(ed25519|rsa)\s+\S+)")
ENCRYPT_TIMEOUT_SECONDS = 900


class BackupCryptoError(Exception):
    """Kunde inte kryptera. Ropas i stället för att skicka klartext."""


def configured_key(environ=None) -> str:
    """Den publika nyckeln ur miljön.

    Ett PEM/ASCII-armor-block är flerradigt. Render klarar flerradiga värden,
    men allt gör inte det - därför accepteras också base64 av samma block, på
    en rad. Vi avkodar bara om resultatet faktiskt ser ut som ett block."""
    raw = str((environ if environ is not None else os.environ).get(PUBLIC_KEY_ENV, "") or "").strip()
    if not raw or raw.startswith("-----") or _AGE_RECIPIENT.match(raw):
        return raw
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8", "replace").strip()
    except Exception:
        return raw
    return decoded if decoded.startswith("-----") else raw


def scheme_of(key: str) -> str:
    """Vilket verktyg nyckeln hör till. Tom sträng = okänd form."""
    key = (key or "").strip()
    if key.startswith("-----BEGIN CERTIFICATE-----"):
        return "cms"
    if key.startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----"):
        return "gpg"
    if _AGE_RECIPIENT.match(key):
        return "age"
    return ""


def tool_for(scheme: str) -> str | None:
    for candidate in TOOLS.get(scheme, ()):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def status(environ=None) -> dict:
    """Vad kontrollrummet behöver veta utan att se nyckeln.

    Aldrig nyckeln själv, aldrig ett prefix av den - en publik nyckel är
    visserligen publik, men /api/health är det också, och en fingervisning om
    VILKEN nyckel som gäller hjälper bara den som vill byta ut den."""
    key = configured_key(environ)
    scheme = scheme_of(key)
    tool = tool_for(scheme) if scheme else None
    return {
        "configured": bool(key),
        "scheme": scheme or None,
        "toolAvailable": bool(tool),
        "ready": bool(key and scheme and tool),
    }


def extension(environ=None) -> str:
    return EXTENSIONS.get(scheme_of(configured_key(environ)), "")


def _run(argv, what: str) -> None:
    try:
        result = subprocess.run(argv, capture_output=True, timeout=ENCRYPT_TIMEOUT_SECONDS, check=False)
    except FileNotFoundError:
        raise BackupCryptoError(f"{what}: verktyget finns inte på servern")
    except subprocess.TimeoutExpired:
        raise BackupCryptoError(f"{what}: tog för lång tid")
    if result.returncode != 0:
        # stderr kan innehålla sökvägar till temporära nyckelfiler, aldrig
        # nyckelmaterial - men klipp ändå, felmeddelanden hamnar i loggen.
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()[:300]
        raise BackupCryptoError(f"{what} misslyckades: {detail or result.returncode}")


def encrypt_file(source, target, *, key: str | None = None, environ=None) -> str:
    """Krypterar `source` till `target` med den publika nyckeln. Returnerar
    schemat som användes. Kastar `BackupCryptoError` hellre än att skriva
    något oskyddat till `target`."""
    key = configured_key(environ) if key is None else (key or "").strip()
    if not key:
        raise BackupCryptoError(
            f"{PUBLIC_KEY_ENV} är inte satt - backupen skickas inte i klartext")
    scheme = scheme_of(key)
    if not scheme:
        raise BackupCryptoError(
            f"{PUBLIC_KEY_ENV} har okänd form (väntade ett certifikat, en age-mottagare "
            "eller ett PGP-block)")
    tool = tool_for(scheme)
    if not tool:
        raise BackupCryptoError(f"verktyget för {scheme} saknas på servern")

    source, target = Path(source), Path(target)
    with tempfile.TemporaryDirectory(prefix="matjakt-backup-key-") as tmp:
        key_file = Path(tmp) / "recipient"
        key_file.write_text(key + "\n", encoding="utf-8")
        if scheme == "cms":
            _run([tool, "cms", "-encrypt", "-aes-256-cbc", "-binary", "-outform", "DER",
                  "-in", str(source), "-out", str(target), str(key_file)], "openssl cms")
        elif scheme == "age":
            _run([tool, "--recipients-file", str(key_file), "-o", str(target), str(source)], "age")
        else:
            # Egen homedir: servern har ingen nyckelring och ska inte skaffa
            # en. --trust-model always eftersom nyckeln kommer ur miljön, inte
            # ur ett förtroendenät.
            _run([tool, "--batch", "--yes", "--homedir", tmp, "--trust-model", "always",
                  "--recipient-file", str(key_file), "--encrypt",
                  "--output", str(target), str(source)], "gpg")
    if not target.exists() or target.stat().st_size == 0:
        raise BackupCryptoError(f"{scheme}: inget krypterat arkiv skrevs")
    return scheme
