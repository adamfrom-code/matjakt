# Backup och återställning

*Uppdaterad 2026-09-03. Persistens är inte backup; en backup på samma disk är inte off-site.*

## Vad som finns i dag

| Lager | Var | Hur ofta | Behåller | Skyddar mot |
|---|---|---|---|---|
| Nattlig backup (`services/backup.py`) | Renders disk, `backend/data/backups/<UTC-stämpel>/` | 1 gång/dygn, första direkt efter deploy om set saknas | 7 set | Programfel, dålig migrering, "tabellen försvann" |
| Off-site-kopia (`scripts/pull_backup.py`) | Adams dator (eller valfri annan maskin) | Dagligen via schemaläggaren | 30 set (konfigurerbart) | Disk borta, Render-konto borta, ransomware på servern |

Nedladdningen har en **egen** hemlighet (`MATJAKT_BACKUP_TOKEN`) och arkivet krypteras med en publik nyckel innan det lämnar servern — se nästa avsnitt. Kontrollrummets `MATJAKT_ADMIN_TOKEN` ger 404 på `/api/admin/backup-download`.

Varje set tas med sqlite:s backup-API (säkert mot samtidiga skrivningar), integritetskontrolleras och rensas till de 7 senaste. Filerna är databaserna som de är: `grocery.db` (priser, produkter, butiker, partner), `matjakt.db` (konton med **hashade** lösenord och **hashade** sessionstoken, synkat tillstånd), `prices.db`, `recipes.db`. Inga API-nycklar, inga Stripe-hemligheter, ingen admin-token finns i databaserna.

## Nyckelparet (B5): servern kan låsa, bara du kan låsa upp

Arkivet krypteras **innan det lämnar processen**. Servern har bara den publika
delen, så ett arkiv på vift är en binärklump — också för den som tagit över
servern. Skapa paret på **din egen maskin**, en gång:

```bash
openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
  -subj "/CN=matjakt-backup" \
  -keyout matjakt-backup-key.pem \      # PRIVAT — bara här, backas upp separat
  -out    matjakt-backup-cert.pem        # publik — den här går till servern
```

* `matjakt-backup-cert.pem` → Render → Environment → `MATJAKT_BACKUP_PUBLIC_KEY`
  (hela PEM-blocket; `sync: false` i `render.yaml`, värdet sätts i dashboarden).
  En rad går också bra: `base64 -w0 matjakt-backup-cert.pem`.
* `matjakt-backup-key.pem` sätts **aldrig** som miljövariabel någonstans. Den
  ligger på hämtmaskinen och i ett kassaskåp/en lösenordshanterare. Tappas den
  är alla krypterade arkiv förlorade — det är priset för att servern inte kan
  läsa dem.

`age` går lika bra: `age-keygen -o matjakt-backup-key.txt` och lägg `age1…`-raden
i `MATJAKT_BACKUP_PUBLIC_KEY`. Formen på nyckeln väljer verktyget automatiskt
(certifikat → `openssl cms`, `age1…` → `age`, PGP-block → `gpg`). `openssl` är
rekommendationen: binären finns redan överallt vi kör.

Utan konfigurerad nyckel skickas **ingenting** — vägen svarar 503 med vad som
saknas. `GET /api/health` visar `backupEncryption.ready`.

## Off-site-kopian: så här (kostar 0 kr, ingen tredje part)

1. Två miljövariabler på hämtmaskinen (aldrig i skript, aldrig i repo):
   `MATJAKT_BACKUP_TOKEN` (öppnar vägen — **egen hemlighet, inte**
   `MATJAKT_ADMIN_TOKEN`) och `MATJAKT_BACKUP_IDENTITY` (sökväg till
   `matjakt-backup-key.pem`, öppnar innehållet).
2. Kör manuellt en gång:
   ```bash
   python backend/scripts/pull_backup.py --dest D:\MatjaktBackups --keep 30
   ```
   Skriptet hämtar `GET /api/admin/backup-download` (backup-token, 404 utan), dekrypterar med den privata nyckeln, verifierar att arkivet går att packa upp och att varje databas klarar `PRAGMA integrity_check`, och rensar till 30 set. Fel ⇒ exit 1 och filen döps till `.corrupt`.
3. Schemalägg dagligen: Windows Schemaläggaren → "Skapa aktivitet" → trigger dagligen 06:30 (efter nattens import och backup 05:xx svensk tid) → åtgärd `python C:\APPAR\matjakt\backend\scripts\pull_backup.py --dest D:\MatjaktBackups` → "Kör oavsett om användaren är inloggad".
4. Destinationen bör ändå ligga på en **krypterad volym** (BitLocker på Windows): det *uppackade* setet innehåller kontons e-postadresser. Transporten är TLS, arkivet är krypterat med din publika nyckel, och volymkrypteringen skyddar det du packat upp.

Storlek: ett set är i dag ~100–150 MB okomprimerat, ~25–40 MB som tar.gz. 30 set ≈ 1 GB.

## Retention

| Nivå | Behåller | Var |
|---|---|---|
| Daglig | 7 set | Servern (automatiskt) |
| Daglig off-site | 30 set | Hämtmaskinen (`--keep 30`) |
| Månatlig (manuell) | 12 set | Kopiera första setet varje månad till en undermapp `månad/` som skriptet inte rensar |

## Återställning (övad plan, ~10 minuter)

1. **Stoppa tjänsten** så inget skriver: Render → tjänsten → *Manual Deploy → Suspend* (eller sätt `MATJAKT_GROCERY_SCHEDULE_ENABLED=0` och vänta ut pågående import).
2. Välj set: senaste hela (`ls backups/` i Render-shell, eller ett lokalt `matjakt-backup-<stämpel>.tar.gz`).
3. **Från servern själv** (programfel/migrering): i Render-shell
   ```bash
   cp /app/backend/data/backups/<stämpel>/*.db /app/backend/data/
   ```
4. **Från off-site** (disken borta): packa upp lokalt, ladda upp via Render-shell (`scp`/`rsync` saknas: använd ett tillfälligt admin-uppladdningssteg eller Renders *Disk snapshots* om planen har det; enklast är att starta med tom disk, kopiera in filerna med `cat > fil` via shell för små filer, och för grocery.db låta nattimporten fylla på — priser läker inom ett dygn, konton och recept är de små filerna som måste tillbaka).
5. Starta tjänsten; kontrollera `GET /api/health` (`ok`, `productCount`, `platform.active`) och logga in med ett konto.
6. Notera i CHECKPOINT.md vilket set som återställdes och varför.

Databaserna är självbärande: inga migreringar behöver köras om, `store.py` lägger till saknade kolumner vid öppning.

## Alternativ som INTE aktiveras utan Adams godkännande

| Alternativ | Kostnad | Fördel | Krav |
|---|---|---|---|
| Cloudflare R2 (S3-API, push från servern nattligen) | 0 kr upp till 10 GB, ingen egress-avgift | Helt automatiskt, oberoende av Adams dator | Cloudflare-konto, access-nycklar som env i Render, ~120 rader SigV4-signering i stdlib |
| Backblaze B2 | 0 kr upp till 10 GB | Samma | B2-konto + nycklar |
| Renders disk snapshots | Ingår i vissa planer, annars betalplan | Enklast | Kontrollera i Render-dashboarden; inte verifierat här |

Rekommendation: kör off-site-kopian via `pull_backup.py` nu (0 kr, i dag), och lägg till R2-push som steg två när det finns ett Cloudflare-konto att sätta nycklar i.

## Kontroll varje månad

- [ ] Senaste off-site-arkivet är från i dag/i går (`dir D:\MatjaktBackups`)
- [ ] `python backend/scripts/pull_backup.py` avslutar med `OK`
- [ ] Prova en återställning lokalt: packa upp ett set till `backend/data-restore/`, starta `MATJAKT_DATA_DIR=backend/data-restore python backend/api_server.py`, logga in
