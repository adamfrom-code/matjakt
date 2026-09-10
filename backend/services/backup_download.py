# -*- coding: utf-8 -*-
"""Off-site-kopian: senaste verifierade backupsetet, krypterat, som en fil.

Vägen är `/api/admin/backup-download` och den bär mer personuppgifter än
någon annan väg i systemet - hela kontodatabasen, varje `synced_state` och
all fritextfeedback. Därför två spärrar som inte finns någon annanstans:

1. EGEN HEMLIGHET. `MATJAKT_BACKUP_TOKEN`, skild från kontrollrummets
   `MATJAKT_ADMIN_TOKEN`. Kontrollrumstoken sitter i en webbläsare, i
   utvecklarverktyg och i minst en gammal commit; nedladdningen av allas
   personuppgifter ska inte hänga på samma sträng. Kontrollen ligger i
   api_server (`_backup_download_authorized`), inte här.

2. KRYPTERAT INNAN DET LÄMNAR PROCESSEN. Se services/backup_crypto.py.
   Servern har bara den publika nyckeln, så ett arkiv på vift är en
   binärklump - också för den som tagit över servern.

Utan konfigurerad nyckel skickas ingenting: 503 med vad som saknas, aldrig
databasen "så länge".
"""

import tarfile
import tempfile
from pathlib import Path

from . import backup as backup_service
from . import backup_crypto

CHUNK = 1024 * 1024


def _tar_newest_set(newest: Path, target: Path) -> None:
    """Arkivet byggs på disk, inte i minnet - grocery.db är stor."""
    with tarfile.open(str(target), mode="w:gz") as archive:
        for db_file in sorted(newest.glob("*.db")):
            archive.add(db_file, arcname=f"{newest.name}/{db_file.name}")


def serve(handler, data_dir) -> None:
    """Skriver hela svaret på `handler`. Anroparen har redan auktoriserat."""
    newest = backup_service.newest_set(Path(data_dir))
    if newest is None:
        handler.send_json(404, {"error": "Ingen backup finns ännu"})
        return

    state = backup_crypto.status()
    if not state["ready"]:
        # Fail closed. Anroparen ÄR auktoriserad här, så orsaken får sägas
        # rakt ut - den som kommit så här långt ska kunna åtgärda den.
        if not state["configured"]:
            reason = (f"{backup_crypto.PUBLIC_KEY_ENV} är inte satt. Backupen skickas "
                      "aldrig i klartext - se docs/BACKUP.md för hur nyckelparet skapas.")
        elif not state["scheme"]:
            reason = f"{backup_crypto.PUBLIC_KEY_ENV} har en form som inte känns igen."
        else:
            reason = f"verktyget för {state['scheme']} saknas på servern."
        handler.send_json(503, {"error": f"Krypteringen är inte klar: {reason}"})
        return

    with tempfile.TemporaryDirectory(prefix="matjakt-backup-out-") as tmp:
        plain = Path(tmp) / f"matjakt-backup-{newest.name}.tar.gz"
        _tar_newest_set(newest, plain)
        sealed = plain.with_name(plain.name + backup_crypto.EXTENSIONS[state["scheme"]])
        try:
            backup_crypto.encrypt_file(plain, sealed)
        except backup_crypto.BackupCryptoError as error:
            handler.send_json(503, {"error": f"Kunde inte kryptera backupen: {error}"})
            return
        finally:
            # Klartextarkivet ska inte ligga kvar en sekund längre än det
            # behövs, inte ens i en katalog vi själva städar.
            plain.unlink(missing_ok=True)

        size = sealed.stat().st_size
        handler.send_response(200)
        handler.send_header("Content-Type", "application/octet-stream")
        handler.send_header("Content-Disposition", f'attachment; filename="{sealed.name}"')
        handler.send_header("Content-Length", str(size))
        handler.send_header("X-Backup-Encryption", state["scheme"])
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        with open(sealed, "rb") as stream:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                handler.wfile.write(chunk)
