# Release – reproducerbar process och kvalitetsgrind

*Uppdaterad 2026-09-06. Ingen release får bygga på att någon minns manuella kommandon.*

## Vad som händer vid `git push origin main`

1. **CI** (`.github/workflows/ci.yml`): kompilering, hela backend-sviten i en isolerad tempkatalog utan riktiga anrop, frontend-tester, `node --check`, hemlighetsskanning, kontroll att `.env` inte är spårad, kontroll att frontendens tre versionsnummer följs åt.
2. **Pages** (`.github/workflows/deploy.yml`): kör `npm test`, bygger `dist/frontend` med `npm run build` (esbuild: `app.js` buntad + minifierad, `styles.css` minifierad, källorna orörda) och deployar den till matjakt.store med `matjakt-api-url` satt till Render.
3. **Render**: bygger `backend/Dockerfile` och deployar. *Observera:* Render lyssnar på pushen direkt – inte på CI. En röd svit stoppar i dag Pages men inte backend. Åtgärd (Adam, Render-dashboarden): stäng av *Auto-Deploy* och lägg ett deploy-hook-steg sist i `ci.yml` (`curl -X POST "$RENDER_DEPLOY_HOOK"` med hooken som GitHub-secret). Tills dess: pusha bara grönt.

## Kvalitetsgrind – release är RÖD om något av detta gäller

| Kontroll | Kommando / var | Krav |
|---|---|---|
| Backend-svit | `python backend/tests/run.py` (E2E:n ingår när Playwright finns) | alla gröna |
| Frontend-svit | `node --test` | alla gröna |
| Syntax | `node --check frontend/app/app.js && python -m compileall -q backend` | ok |
| Hemligheter | `python backend/scripts/secret_scan.py` | inga träffar |
| Versioner | `python backend/scripts/check_frontend_version.py` | samma nummer på tre ställen |
| Prisaudit | `python backend/scripts/audit_pricing.py` (lokalt) och `POST /api/admin/pricing-audit` (prod, admin-token) | `gate: GRÖN` = 0 gram→styck, 0 volym→styck, 0 estimat, 0 otolkade, 0 kilopris-som-paketpris |
| Auth | svitens `test_accounts`, `test_auth_hardening`, `test_session_tokens` + ett manuellt registrera/logga ut/logga in i prod | gröna, veckan finns kvar |
| Stripe | `GET /api/health` → `stripe.mode`, `stripe.pricesVerified: true`; `GET /api/admin/stripe-check` → `ok: true` | test-läge tills live beslutas |
| Mejl | `GET /api/health` → `mail: true`; registrera ett konto och klicka länken | mejlet kommer |
| Backup | `python backend/scripts/pull_backup.py` | `OK` med dagens datum |
| Säkerhet | inga öppna Critical/High i senaste auditen (`CHECKPOINT.md`) | – |
| Onboarding | fyra steg i prod (`curl -s https://matjakt.store/app/app.js | grep -c 'render: renderOb'` = 4) | 4 |
| Kontopersistens | logga ut, rensa lagring, logga in – veckan är kvar | ja |

## Steg för steg

```bash
# 1. Grönt lokalt
python backend/tests/run.py && node --test && python backend/scripts/secret_scan.py && python backend/scripts/check_frontend_version.py

# 2. Frontend-ändring? Höj cache-versionen (alla tre ställen på en gång)
python backend/scripts/check_frontend_version.py --bump

# 3. Små logiska commits, push
git push origin main

# 4. Efter deploy (3-5 min)
curl -s https://matjakt.onrender.com/api/health | python -m json.tool
```

Kontrollera i hälsosvaret: `ok`, `platform.active`, `platform.releasedChains`, `stripe.pricesVerified`, `mail`.

## Loggar, request-id och räknare

- Varje svar bär `X-Request-Id` (klientens egna id behålls om det är välformat, 8-64 tecken `[A-Za-z0-9._-]`). Samma id står i varje loggrad som skrivs under begäran - vid ett supportärende: be om id:t, sök i Render-loggen.
- På Render skrivs loggen som JSON (`MATJAKT_LOG_FORMAT=json` är standard där; `text` lokalt). Accessraden har sökväg utan query, status, svarstid och IP maskerad till /24.
- `GET /api/health` → `metrics`: `requests_total`, `responses_4xx/5xx`, `slow_requests_2s`, `auth_login_failed`, `stripe_webhook_rejected/errors`, `mail_send_failed`, `pricing_gate_failed`, `unhandled_exceptions`, `uptime_seconds`. Nollställs vid omstart - de svarar på "händer det nu?".
- Larmgräns att bevaka manuellt tills en riktig monitor finns: `responses_5xx` > 0 efter deploy, `stripe_webhook_rejected` > 0, `pricing_gate_failed` > 0.

## Rate limit

Räknarna ligger i `ratelimit.db` i datakatalogen (`services/accounts/ratelimit.py`) och överlever omstart/deploy; `GET /api/health` → `rateLimitPersistent: true`. Flera processer på samma disk delar dem. Vid horisontell skalning över flera diskar (fler Render-instanser) krävs en central räknare - byt `_check_db` mot Redis `INCR`+`EXPIRE` per `action:identifier`; publika API:t (`check`, `clear_on_success`, `LIMITS`) är oförändrat.

## Frontend-bygge

`npm run build` → `dist/frontend` (gitignorerad). Lokalt körs appen från källorna; Playwright-E2E:n kan köras mot bygget: `MATJAKT_E2E_FRONTEND_DIR=dist/frontend python backend/tests/run.py --pattern "test_consumer*"`. Bygget ändrar ingen funktionalitet - bara en fil i stället för tretton moduler.

## Rollback

`git revert <commit>` + push. Både Pages och Render bygger om. Databasen berörs inte av en kodrollback; för data, se `docs/DISASTER_RECOVERY.md`.

## Native (Capacitor)

Android: `npx cap sync android` efter frontend-ändringar, bumpa `versionCode`/`versionName` i `android/app/build.gradle`. iOS: se `docs/IOS_RELEASE.md` (kräver Mac).

## Testmatris

| Nivå | Finns | Kör i CI | Saknas |
|---|---|---|---|
| Backend unit (motor, butik, matchning, enheter, Dabas, partner, auth, billing, mejl, vakt) | ~870 tester i `backend/tests/` | ja | Primat-cursor, importer-krasch mitt i staging (finns delvis) |
| Backend HTTP/integration (routes med riktig server på port 0) | `test_api_server.py`, `test_partner_api.py` | ja | – |
| Frontend unit | `tests/*.test.js` (63) | ja | renderingskoden i `app.js` saknar test |
| Kontrakt frontend↔backend | `test_frontend_contract.py` | ja | – |
| Fuzz | `scratchpad`-skript vid audit (Content-Length, typer, injektion, path traversal) | nej – kör manuellt vid större ändringar | flytta in i sviten |
| Browser-E2E | `backend/tests/e2e/test_consumer_journey.py` (Playwright, riktig Chromium mot riktig server med egna tempdatabaser): signup → login → onboarding 4 steg → vecka → byt rätt → recept → Handla → finns hemma → skafferi → butiksjämförelse/paywall → logout → login → allt kvar; Premium-paywall + Stripe-testläge med mockad Stripe-gräns och riktigt signerad webhook | ja (`ci.yml` jobb `e2e`, både källor och byggt bundle) | visuell regression |
| Produktions-smoke | `curl /api/health`, `backend/tests/prod_persistence_e2e.py` (manuell, bakom låset) | nej | – |
| Säkerhetsregression | auth-härdning, rate limits, admin 404, HSTS, hashade token, testspärr | ja | – |
| Visuell regression | skärmdumpar sparas av E2E:n vid fel (`tests/e2e/artifacts/`) | nej | jämförelse mot referensbilder |
