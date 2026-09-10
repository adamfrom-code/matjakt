# -*- coding: utf-8 -*-
"""Hämtar produktionens senaste verifierade backupset till en ANNAN maskin.

Persistens är inte backup, och en backup på samma disk som datat är inte
off-site. Det här skriptet är off-site-kopian utan tredje part: det laddar
ner senaste setet från servern (GET /api/admin/backup-download), dekrypterar
det med den PRIVATA nyckeln - som bara finns här, aldrig på servern -
kontrollerar att arkivet går att läsa och att varje databas klarar
PRAGMA integrity_check, och behåller de N senaste seten lokalt.

    set MATJAKT_BACKUP_TOKEN=...         (miljövariabel - aldrig som argument)
    set MATJAKT_BACKUP_IDENTITY=C:\\nycklar\\matjakt-backup-key.pem
    python backend/scripts/pull_backup.py
    python backend/scripts/pull_backup.py --dest D:\\MatjaktBackups --keep 30
    python backend/scripts/pull_backup.py --url https://matjakt.onrender.com

TVÅ HEMLIGHETER, INTE EN. `MATJAKT_BACKUP_TOKEN` öppnar vägen;
`MATJAKT_BACKUP_IDENTITY` pekar på den privata nyckeln som öppnar innehållet.
Den som får tag i tokenen får en binärklump. Sätt aldrig identiteten som
miljövariabel på servern - då är hela poängen borta.

Schemalägg dagligen (Windows: Schemaläggaren, "Kör oavsett om användaren är
inloggad") - se docs/BACKUP.md. Destinationen bör ändå ligga på en krypterad
volym (BitLocker): det uppackade setet innehåller kontons e-postadresser.

Avslutar med kod 1 om något steg misslyckas, så schemaläggaren kan larma.
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://matjakt.onrender.com"
DEFAULT_DEST = Path.home() / "MatjaktBackups"

# Suffix -> hur filen öppnas igen. Speglar services/backup_crypto.py.
DECRYPTORS = {
    ".cms": lambda tool, ident, src, dst: [tool, "cms", "-decrypt", "-inform", "DER",
                                           "-in", str(src), "-inkey", str(ident), "-out", str(dst)],
    ".age": lambda tool, ident, src, dst: [tool, "-d", "-i", str(ident), "-o", str(dst), str(src)],
    ".gpg": lambda tool, ident, src, dst: [tool, "--batch", "--yes", "--decrypt",
                                           "--output", str(dst), str(src)],
}
TOOLS = {".cms": ("openssl",), ".age": ("age", "rage"), ".gpg": ("gpg", "gpg2")}


def download(url: str, token: str, dest_dir: Path) -> Path:
    request = urllib.request.Request(f"{url}/api/admin/backup-download",
                                     headers={"X-Backup-Token": token, "User-Agent": "matjakt-pull-backup"})
    with urllib.request.urlopen(request, timeout=600) as response:
        disposition = response.headers.get("Content-Disposition", "")
        name = disposition.split('filename="')[-1].rstrip('"') if 'filename="' in disposition else None
        target = dest_dir / (name or f"matjakt-backup-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.tar.gz")
        tmp = target.with_suffix(target.suffix + ".part")
        with open(tmp, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        tmp.replace(target)
    return target


def decrypt(archive_path: Path, identity: str | None, into: Path) -> Path:
    """Krypterat arkiv -> tar.gz i `into`. Oförändrat om det redan är klartext.

    Den privata nyckeln läses HÄR, på mottagarmaskinen. Servern har den inte
    och ska inte kunna få den."""
    suffix = archive_path.suffix.lower()
    if suffix not in DECRYPTORS:
        return archive_path
    if not identity:
        raise RuntimeError(f"{archive_path.name} är krypterad ({suffix}) men ingen privat nyckel angavs "
                           "- sätt MATJAKT_BACKUP_IDENTITY eller använd --identity")
    if suffix != ".gpg" and not Path(identity).exists():
        raise RuntimeError(f"identitetsfilen finns inte: {identity}")
    tool = next((shutil.which(name) for name in TOOLS[suffix] if shutil.which(name)), None)
    if not tool:
        raise RuntimeError(f"verktyget för {suffix} saknas ({' eller '.join(TOOLS[suffix])})")
    plain = into / archive_path.name[: -len(suffix)]
    result = subprocess.run(DECRYPTORS[suffix](tool, identity, archive_path, plain),
                            capture_output=True, timeout=900, check=False)
    if result.returncode != 0 or not plain.exists():
        raise RuntimeError(f"dekrypteringen misslyckades: "
                           f"{(result.stderr or b'').decode('utf-8', 'replace').strip()[:200]}")
    return plain


def verify(archive_path: Path, identity: str | None = None) -> list[str]:
    """Dekrypterar vid behov, packar upp i temp och kör integrity_check på
    varje databas. Returnerar listan över godkända filer; kastar vid första
    underkända."""
    approved = []
    with tempfile.TemporaryDirectory() as tmp:
        opened = decrypt(archive_path, identity, Path(tmp))
        with tarfile.open(opened, mode="r:gz") as archive:
            members = [m for m in archive.getmembers() if m.isfile() and m.name.endswith(".db")]
            if not members:
                raise RuntimeError("arkivet innehåller inga .db-filer")
            for member in members:
                if ".." in Path(member.name).parts:
                    raise RuntimeError(f"misstänkt sökväg i arkivet: {member.name}")
            archive.extractall(tmp, members=members)
        for db_file in sorted(Path(tmp).rglob("*.db")):
            connection = sqlite3.connect(db_file)
            try:
                status = connection.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                connection.close()
            if status != "ok":
                raise RuntimeError(f"{db_file.name}: integrity_check = {status}")
            approved.append(db_file.name)
    return approved


def prune(dest_dir: Path, keep: int) -> list[Path]:
    archives = sorted(dest_dir.glob("matjakt-backup-*.tar.gz*"))
    archives = [a for a in archives if not a.name.endswith((".part", ".corrupt"))]
    removed = archives[:-keep] if keep > 0 else []
    for stale in removed:
        stale.unlink()
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    parser.add_argument("--keep", type=int, default=30, help="antal set att behålla lokalt (0 = alla)")
    parser.add_argument("--identity", default=os.environ.get("MATJAKT_BACKUP_IDENTITY", "").strip(),
                        help="privat nyckelfil för dekryptering (aldrig på servern)")
    args = parser.parse_args()
    token = os.environ.get("MATJAKT_BACKUP_TOKEN", "").strip()
    if not token:
        print("MATJAKT_BACKUP_TOKEN saknas i miljön. (Kontrollrummets MATJAKT_ADMIN_TOKEN "
              "duger inte längre - nedladdningen har en egen hemlighet sedan B5.)", file=sys.stderr)
        return 1
    dest_dir = Path(args.dest)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        archive = download(args.url.rstrip("/"), token, dest_dir)
    except urllib.error.HTTPError as error:
        hint = {404: "fel backup-token eller ingen backup ännu",
                503: "krypteringen är inte konfigurerad på servern (MATJAKT_BACKUP_PUBLIC_KEY)"}
        print(f"Servern svarade {error.code}: {hint.get(error.code, error.reason)}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as error:
        print(f"Kunde inte hämta backup: {error}", file=sys.stderr)
        return 1
    try:
        approved = verify(archive, args.identity or None)
    except (tarfile.TarError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        archive.rename(archive.with_suffix(archive.suffix + ".corrupt"))
        print(f"Backupen underkändes och döptes om till .corrupt: {error}", file=sys.stderr)
        return 1
    removed = prune(dest_dir, args.keep)
    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"OK {archive.name} ({size_mb:.1f} MB): {', '.join(approved)} verifierade"
          + (f"; {len(removed)} äldre set rensade" if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
