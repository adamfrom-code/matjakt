# -*- coding: utf-8 -*-
"""Säkerhetskopierar Matjakts databaser - persistens är inte backup.

The Render disk survives deploys; it does not survive "the disk broke" or
"a migration ate the users table". This script copies every database in
DATA_DIR into DATA_DIR/backups/<UTC-timestamp>/ using sqlite's own backup
API (safe against concurrent writers - a plain file copy of a live WAL
database can produce a corrupt copy), then prunes to the newest KEEP sets.

    python backend/scripts/backup_data.py            # ta en backup
    python backend/scripts/backup_data.py --list     # visa vad som finns
    python backend/scripts/backup_data.py --verify SENASTE  # integritetskolla

RECOVERY: stoppa servern, kopiera filerna från backups/<stämpel>/ till
DATA_DIR, starta servern. Ingenting mer - databaserna är självbärande.
On Render: run it in the service Shell; the backups live on the same disk,
so for real disaster-tolerance download the newest set now and then
(Shell -> tar czf /tmp/b.tgz /app/backend/data/backups && ... or via an
admin endpoint later). Secrets never enter these files - the databases hold
hashed passwords and hashed session tokens only.
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from api_server import DATA_DIR  # noqa: E402

BACKUP_DIR = DATA_DIR / "backups"
KEEP = 7


def take_backup() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = BACKUP_DIR / stamp
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for db_path in sorted(DATA_DIR.glob("*.db")):
        source = sqlite3.connect(db_path)
        try:
            destination = sqlite3.connect(target / db_path.name)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
        copied += 1
        print(f"  {db_path.name:<16} -> backups/{stamp}/")
    if not copied:
        print("Inga databaser att kopiera.")
        target.rmdir()
        return target
    # Prune: behåll de KEEP senaste kompletta seten.
    sets = sorted(d for d in BACKUP_DIR.iterdir() if d.is_dir())
    for stale in sets[:-KEEP]:
        shutil.rmtree(stale, ignore_errors=True)
        print(f"  rensade {stale.name}")
    print(f"Backup klar: {copied} databaser i backups/{stamp}")
    return target


def list_backups():
    sets = sorted(d for d in BACKUP_DIR.iterdir() if d.is_dir()) if BACKUP_DIR.exists() else []
    if not sets:
        print("Inga backuper ännu.")
        return
    for backup in sets:
        files = list(backup.glob("*.db"))
        size = sum(f.stat().st_size for f in files)
        print(f"  {backup.name}  {len(files)} databaser  {size/1e6:.1f} MB")


def verify(name: str) -> int:
    sets = sorted(d for d in BACKUP_DIR.iterdir() if d.is_dir()) if BACKUP_DIR.exists() else []
    if not sets:
        print("Inga backuper att verifiera.")
        return 1
    target = sets[-1] if name == "SENASTE" else BACKUP_DIR / name
    bad = 0
    for db_path in sorted(target.glob("*.db")):
        connection = sqlite3.connect(db_path)
        try:
            status = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
        print(f"  {db_path.name:<16} {status}")
        if status != "ok":
            bad += 1
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--verify", metavar="STÄMPEL")
    args = parser.parse_args()
    if args.list:
        list_backups()
        return 0
    if args.verify:
        return verify(args.verify)
    take_backup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
