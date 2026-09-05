# Disaster recovery – så återställs Matjakt från noll

*Uppdaterad 2026-09-06. Övas: minst en gång per kvartal, se checklistan sist.*

Matjakt består av tre saker som kan gå sönder: **koden** (GitHub), **tjänsten** (Render) och **datat** (fyra SQLite-filer på Renders disk). Allt utom datat återskapas från repot på minuter. Datat är det enda som kräver en backup.

## Vad som finns var

| Del | Var | Återskapas från | Tid |
|---|---|---|---|
| Frontend (matjakt.store) | GitHub Pages, byggs av `.github/workflows/deploy.yml` | repot, `main` | ~3 min efter push |
| Backend-kod | Render, Docker från `backend/Dockerfile` | repot, `main` | ~5 min efter push |
| Miljövariabler | Render-dashboarden | listan i `render.yaml` + hemligheterna (bara Adam har dem) | 10 min att skriva in |
| `matjakt.db` (konton, sessioner, synkat tillstånd, Stripe-referenser) | Render-disk `/app/backend/data` | backup | se nedan |
| `grocery.db` (produkter, priser, butiker, partner) | Render-disk | backup, eller nattimporten fyller på inom ett dygn | |
| `recipes.db` (receptbanken) | Render-disk | backup, eller `backend/scripts/import_recipes.py` + `migrate_recipes.py` från källfilerna | |
| `prices.db` (KV-cache: geokod, butikslistor, bilder) | Render-disk | behövs inte – byggs om av sig själv | 0 |
| Stripe-kunder och prenumerationer | Stripe | Stripe är sanningen; `matjakt.db` bär bara referenserna | – |
| DNS (matjakt.store) | Loopia | Loopias DNS-editor: A/CNAME för GitHub Pages (`@`, `www`), Resends tre poster för mejl (`resend._domainkey`, `send`, `rsend`) – exakta värden i Resends dashboard | – |

## Scenario 1: en deploy gick sönder

1. `git revert <commit>` på `main` och push. Render och Pages bygger om automatiskt.
2. Kontrollera `https://matjakt.onrender.com/api/health` → `ok: true`, `platform.active: true`.
3. Om backend inte startar alls: Render → *Manual Deploy → Deploy previous commit*.

## Scenario 2: en migrering eller ett programfel åt upp data (disken finns kvar)

1. Render → *Manual Deploy → Suspend* (inga skrivningar under återställningen).
2. Render-shell: `ls /app/backend/data/backups/` – välj senaste hela setet (sju dygn bakåt finns).
3. `cp /app/backend/data/backups/<stämpel>/*.db /app/backend/data/`
4. *Resume*. Kontrollera hälsan och logga in med ett konto.
5. Skriv in vad som hände i `CHECKPOINT.md`.

## Scenario 3: disken, tjänsten eller hela Render-kontot är borta

Förutsätter att off-site-kopian finns (`docs/BACKUP.md`: `backend/scripts/pull_backup.py` körs dagligen på Adams dator). Utan den är konton och receptbank förlorade; priser läker inom ett dygn.

1. Skapa tjänsten på nytt från `render.yaml` (*New → Blueprint* i Render, peka på repot). Disken `matjakt-data` skapas med.
2. Skriv in miljövariablerna. Nycklarna hämtas från respektive dashboard (Stripe, Primat, Dabas, Resend), aldrig från något dokument. `MATJAKT_ADMIN_TOKEN` och `MATJAKT_PREMIUM_CODE` sätts till nya värden.
3. Låt den första deployen gå igenom med tom disk. Backend startar, skapar tomma databaser, och nattimporten schemaläggs.
4. Lägg tillbaka datat. Render-shell saknar `scp`; enklaste vägen är en tillfällig admin-uppladdning:
   - Lokalt: packa upp senaste `matjakt-backup-<stämpel>.tar.gz`.
   - `matjakt.db` och `recipes.db` är små (< 2 MB). Kopiera dem via shell med `base64`: lokalt `base64 -w0 matjakt.db > m.b64`, klistra in i shell `echo '<…>' | base64 -d > /app/backend/data/matjakt.db`. Tjänsten ska vara suspenderad under tiden.
   - `grocery.db` (~100 MB) behöver inte kopieras: kör `POST /api/admin/platform-activate` och `POST /api/admin/grocery-import` för Willys, Hemköp och City Gross, eller vänta på nattjobbet. Referenspriserna byggs vid publiceringen.
5. *Resume*, kontrollera hälsan, logga in, kör ett prisanrop i appen.
6. Stripe: webhook-endpointen pekar fortfarande på `https://matjakt.onrender.com/api/billing/webhook` – tjänstens URL är densamma om namnet är detsamma. Ny hemlighet krävs bara om endpointen skapas om; då uppdateras `STRIPE_WEBHOOK_SECRET`.
7. DNS rörs inte: `matjakt.store` pekar på GitHub Pages och backend nås via `matjakt.onrender.com`.

## Scenario 4: Stripe är nere eller nyckeln roterad

Befintlig Premium försvinner inte: prenumerationsläget ligger i `matjakt.db` och gäller till periodslut plus tre dygns respit (`services/accounts/store.py`). Checkout och portal svarar 400/503 med tydlig text. Efter rotation: nya värden i Render, deploy, `GET /api/health` → `stripe.pricesVerified: true`.

## Scenario 5: en datakälla är nere (Axfood, City Gross, Primat, Dabas)

Ingenting behöver göras. En misslyckad import märks `failed`, senaste godkända priser behålls (`services/grocery/publish.py`), och verifierade butikspriser äldre än fyra dygn faller tillbaka på kedjans referenspris. Dabas-berikning är ett tillägg ovanpå providerdata – utan den fortsätter allt med providerns egna uppgifter.

## Scenario 6: mejl (Resend) är nere

Registrering fungerar; svaret bär `verificationMail: failed`. Glömt lösenord svarar 503 med besked. Inget kraschar. Kontrollera `GET /api/health` → `mail`.

## Kvartalsövning (30 minuter)

- [ ] `python backend/scripts/pull_backup.py` ger `OK` och arkivet är från i dag
- [ ] Packa upp senaste arkivet lokalt och starta `MATJAKT_DATA_DIR=<mapp> python backend/api_server.py`; logga in med ett konto
- [ ] `git log -1` på `main` bygger grönt i CI (`.github/workflows/ci.yml`)
- [ ] Miljövariabellistan i `render.yaml` stämmer med dashboarden (namn, inte värden)
- [ ] Anteckna datum och utfall i `CHECKPOINT.md`
