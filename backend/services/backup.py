# -*- coding: utf-8 -*-
"""Automatiska säkerhetskopior - persistens är inte backup.

The Render disk survives deploys; it does not survive "the disk broke" or
"a migration ate the users table". Every night this copies each database in
the data directory into backups/<UTC-stamp>/ with sqlite's own backup API
(safe against concurrent writers - a plain file copy of a live WAL database
can produce a corrupt copy), integrity-checks the copies, and prunes to the
newest KEEP sets.

HONEST LIMIT: the backups live on the SAME disk as the data. They protect
against application bugs and bad migrations - not against losing the disk.
Off-site copies need storage credentials the server does not have; until
then, download a set now and then from the Render shell:

    tar czf /tmp/matjakt-backup.tgz /app/backend/data/backups

RESTORE: stoppa tjänsten (Render: Manual Deploy -> Suspend eller skala till
0), kopiera filerna från backups/<stämpel>/ till datakatalogen (skriv över),
starta tjänsten. Databaserna är självbärande - ingenting mer behövs.
Lokalt: samma sak mot backend/data/.

Secrets never enter these files - the databases hold hashed passwords and
hashed session tokens only.
"""

import logging
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .data_guard import guard_database_path

logger = logging.getLogger("matjakt.backup")

KEEP = 7
# Ett dygn mellan seten; kontrollen var timme kostar en stat().
INTERVAL_SECONDS = 24 * 3600
CHECK_EVERY_SECONDS = 3600


def backup_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "backups"


def newest_set(data_dir: Path) -> Path | None:
    root = backup_dir(data_dir)
    sets = sorted(d for d in root.iterdir() if d.is_dir()) if root.exists() else []
    return sets[-1] if sets else None


def newest_age_seconds(data_dir: Path) -> float | None:
    newest = newest_set(data_dir)
    if newest is None:
        return None
    try:
        stamp = datetime.strptime(newest.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - stamp).total_seconds()


def take_backup(data_dir: Path) -> dict:
    """One complete, verified, pruned backup set. Returns a small report."""
    data_dir = Path(data_dir)
    guard_database_path(data_dir, purpose="datakatalogen (backup)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir(data_dir) / stamp
    target.mkdir(parents=True, exist_ok=True)
    copied, failed = [], []
    for db_path in sorted(data_dir.glob("*.db")):
        try:
            source = sqlite3.connect(db_path)
            try:
                destination = sqlite3.connect(target / db_path.name)
                try:
                    source.backup(destination)
                    status = destination.execute("PRAGMA integrity_check").fetchone()[0]
                finally:
                    destination.close()
            finally:
                source.close()
            if status == "ok":
                copied.append(db_path.name)
            else:
                # En kopia som inte klarar integritetskollen är ingen backup.
                failed.append(db_path.name)
                (target / db_path.name).unlink(missing_ok=True)
                logger.error("Backupkopian av %s underkändes: %s", db_path.name, status)
        except sqlite3.Error:
            failed.append(db_path.name)
            logger.exception("Kunde inte säkerhetskopiera %s", db_path.name)

    if not copied:
        shutil.rmtree(target, ignore_errors=True)
        return {"stamp": stamp, "copied": [], "failed": failed}

    sets = sorted(d for d in backup_dir(data_dir).iterdir() if d.is_dir())
    for stale in sets[:-KEEP]:
        shutil.rmtree(stale, ignore_errors=True)

    logger.info("Backup klar: %d databaser i backups/%s%s", len(copied), stamp,
                f" ({len(failed)} MISSLYCKADES)" if failed else "")
    return {"stamp": stamp, "copied": copied, "failed": failed}


def start_nightly(data_dir: Path) -> threading.Thread:
    """Daemon-tråd: ett verifierat backupset per dygn, första direkt om det
    saknas eller är gammalt. En krasch i en cykel dödar inte tråden."""
    guard_database_path(data_dir, purpose="datakatalogen (backup)")

    def run():
        while True:
            try:
                age = newest_age_seconds(data_dir)
                if age is None or age >= INTERVAL_SECONDS:
                    take_backup(data_dir)
            except Exception:
                logger.exception("Backupcykeln misslyckades - försöker igen om en timme")
            time.sleep(CHECK_EVERY_SECONDS)

    thread = threading.Thread(target=run, name="matjakt-backup", daemon=True)
    thread.start()
    return thread
