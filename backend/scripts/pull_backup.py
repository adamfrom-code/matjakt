# -*- coding: utf-8 -*-
"""Hämtar produktionens senaste verifierade backupset till en ANNAN maskin.

Persistens är inte backup, och en backup på samma disk som datat är inte
off-site. Det här skriptet är off-site-kopian utan tredje part: det laddar
ner senaste setet från servern (GET /api/admin/backup-download, admin-token),
kontrollerar att arkivet går att läsa och att varje databas klarar
PRAGMA integrity_check, och behåller de N senaste seten lokalt.

    set MATJAKT_ADMIN_TOKEN=...          (miljövariabel - aldrig som argument)
    python backend/scripts/pull_backup.py
    python backend/scripts/pull_backup.py --dest D:\\MatjaktBackups --keep 30
    python backend/scripts/pull_backup.py --url https://matjakt.onrender.com

Schemalägg dagligen (Windows: Schemaläggaren, "Kör oavsett om användaren är
inloggad") - se docs/BACKUP.md. Destinationen bör ligga på en krypterad
volym (BitLocker) eftersom databaserna innehåller kontons e-postadresser.

Avslutar med kod 1 om något steg misslyckas, så schemaläggaren kan larma.
"""

import argparse
import os
import sqlite3
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://matjakt.onrender.com"
DEFAULT_DEST = Path.home() / "MatjaktBackups"


def download(url: str, token: str, dest_dir: Path) -> Path:
    request = urllib.request.Request(f"{url}/api/admin/backup-download",
                                     headers={"X-Admin-Token": token, "User-Agent": "matjakt-pull-backup"})
    with urllib.request.urlopen(request, timeout=600) as response:
        disposition = response.headers.get("Content-Disposition", "")
        name = disposition.split('filename="')[-1].rstrip('"') if 'filename="' in disposition else None
        target = dest_dir / (name or f"matjakt-backup-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.tar.gz")
        tmp = target.with_suffix(".part")
        with open(tmp, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        tmp.replace(target)
    return target


def verify(archive_path: Path) -> list[str]:
    """Packar upp i temp och kör integrity_check på varje databas. Returnerar
    listan över godkända filer; kastar vid första underkända."""
    approved = []
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(archive_path, mode="r:gz") as archive:
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
    archives = sorted(dest_dir.glob("matjakt-backup-*.tar.gz"))
    removed = archives[:-keep] if keep > 0 else []
    for stale in removed:
        stale.unlink()
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    parser.add_argument("--keep", type=int, default=30, help="antal set att behålla lokalt (0 = alla)")
    args = parser.parse_args()
    token = os.environ.get("MATJAKT_ADMIN_TOKEN", "").strip()
    if not token:
        print("MATJAKT_ADMIN_TOKEN saknas i miljön.", file=sys.stderr)
        return 1
    dest_dir = Path(args.dest)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        archive = download(args.url.rstrip("/"), token, dest_dir)
    except urllib.error.HTTPError as error:
        print(f"Servern svarade {error.code}: {'fel admin-token eller ingen backup ännu' if error.code == 404 else error.reason}",
              file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as error:
        print(f"Kunde inte hämta backup: {error}", file=sys.stderr)
        return 1
    try:
        approved = verify(archive)
    except (tarfile.TarError, RuntimeError, sqlite3.Error) as error:
        archive.rename(archive.with_suffix(".corrupt"))
        print(f"Backupen underkändes och döptes om till .corrupt: {error}", file=sys.stderr)
        return 1
    removed = prune(dest_dir, args.keep)
    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"OK {archive.name} ({size_mb:.1f} MB): {', '.join(approved)} verifierade"
          + (f"; {len(removed)} äldre set rensade" if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
