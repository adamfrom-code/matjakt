# Checkpoint — 2026-09-01 (natt-skiftet)

Skriven så nästa session kan fortsätta utan att bygga om något. Allt nedan
är verifierat mot kod, tester eller live produktion — inget antaget för att
koden "finns".

## Läget i ett stycke

Matjakt är live på **matjakt.store** (frontend GitHub Pages) mot
**matjakt.onrender.com** (backend Render, persistent disk `/app/backend/data`,
verifierad över deploys). 205 recept med instruktioner/näring/bilder,
alla fullt prissatta mot riktiga butiksprodukter. Tre kedjor jämförs på
riktigt: Willys, Hemköp, City Gross. Affärsmodellen är **Free för alltid /
Premium 59 kr/mån / Premium 399 kr/år, ingen trial** — server-side entitlement
med central feature-matris.

## Arkitekturen (oförändrad i grunden)

- Backend: Python stdlib (`http.server`, sqlite3), inga ramverk.
  `backend/api_server.py` + `backend/services/{accounts,billing,email,grocery,
  pricing,recipes,recipe_providers,site}`.
- Frontend: statisk ES-modul-app i `frontend/app/`, landningssida i
  `frontend/`. Service worker versioneras ihop med `?v=`-queries
  (`CACHE_NAME` i `sw.js` + `app.js?v=`/`styles.css?v=` i `index.html` —
  bumpa ALLA tre vid varje UI-släpp).
- Recept: källfilerna i `backend/recipe_sources/*.json` är sanningen
  (INTE under `backend/data/` — Render-monteringen skuggar den sökvägen).
  `bootstrap_if_empty()` synkar databasen när källornas sha256-fingeravtryck
  ändras. Bilder exporteras tillbaka till källfilerna med
  `backend/scripts/export_recipe_images.py` efter varje backfill.
- Priser: nattimporter (Willys 02:00, Hemköp 03:00, City Gross 04:00
  Europe/Stockholm) + bootstrap som fyller varje tom kedja vid start.
  Recepten prissätts om (portionspriser i recipes.db) vid serverstart och
  efter varje lyckad import. ICA endast manuell import (WAF), Coop aldrig
  (kräver deras credential), Lidl aldrig (inga publika priser).

## Free/Premium (beslutad 2026-08-31)

- `backend/services/accounts/features.py` äger ALLT: planer, priser
  (59/399/309-besparingen), feature-matrisen, `FREE_MAX_DINNERS = 4`.
- `/api/entitlements` ger frontend kontraktet; frontend ritar lås,
  servern bestämmer: `/api/pricing/week` maskas för Free
  (`mask_pricing_for_free` i api_server) — full sanning för billigaste
  kvalificerade kedjan, siluetter + riktigt prisspann för resten;
  `/api/pricing/list` ger 403 på låsta butikskorgar.
- Trial är BORTA: `/api/auth/start-trial` svarar 410. Gamla
  premium-flaggan/koder grandfathras som premium_monthly.
- StoreKit-produkt-id:n reserverade i PRICING-configen
  (`se.matjakt.premium.monthly|yearly`) — ej kopplade ännu.

## Handla-vyn

Butikskort överst (dynamiska ur prisdatan, aldrig hårdkodade), Free ser
billigaste butikens riktiga total + Billigast-märke, övriga 🔒/"Pris ej
tillgängligt". "Din matvecka" + "Extra du lagt till": kampanjprodukter
(+ Lägg i inköpslistan från Hem-raden) och manuella varor, med regeln i
`frontend/app/src/services/extras.js`: kampanjpris gäller ENDAST sin egen
kedja; osäker match = rad utan pris. Extras synkas via kontostaten.

## Tester

`npm test` = node --test (frontend) + `python backend/tests/run.py`
(temp-datadir så riktiga databaser aldrig röres). ~795 tester.
Spärr i `backend/services/data_guard.py` (2026-09-02): i testläge får ingen
butiksklass, backup eller api_server öppna en databas utanför tempkatalogen -
hard fail med `ProductionDatabaseInTestError`, oavsett om testet satt `DB_PATH`.
Bevisat i `tests/test_db_guard.py`; riktig `backend/data/*.db` innehållsmässigt
oförändrad av hela sviten (tabellräkningar + hashar före/efter).
Prod-E2E: `backend/tests/auth_e2e.py`, `backend/tests/prod_persistence_e2e.py`
(--before/--after runt en deploy).

## Backup

`python backend/scripts/backup_data.py` (sqlite backup-API, 7 set,
`--verify SENASTE`, `--list`). Recovery: stoppa servern, kopiera tillbaka
filerna från `backups/<stämpel>/`, starta. Ladda ner senaste setet från
Render Shell då och då — disken är persistens, inte katastrofskydd.

## Miljövariabler (Render)

MATJAKT_DATA_DIR (implicit via disk), MATJAKT_GROCERY_SCHEDULE_ENABLED=1,
MATJAKT_ADMIN_TOKEN, MATJAKT_PREMIUM_CODE, MATJAKT_TRUST_PROXY,
PEXELS_API_KEY, PRIMAT_API_KEY, STRIPE_SECRET_KEY + STRIPE_PRICE_MONTHLY/
YEARLY + STRIPE_WEBHOOK_SECRET, SMTP_HOST/PORT/USER/PASSWORD/FROM_EMAIL.
Inga hemligheter i repo eller frontend (verifierat inkl. git-historik).

## Kända öppna punkter

- Juridiksidorna: [FÖRETAGSNAMN]/[ORGANISATIONSNUMMER]/[ÅNGERRÄTT] är
  markerade fält som ADAM måste fylla i + juridisk slutgranskning.
- Riktig betalning: Stripe-flödet är kopplat (checkout/portal/webhook) men
  kräver att STRIPE_PRICE_* pekar på riktiga produkter (399/59); StoreKit
  för iOS är enbart datamodell.
- E-postleverans overifierad (SMTP-env-status i Render okänd); flödena är
  enumeration-säkra och rate-limitade.
- ICA i produktion: tom tills en manuell adminimport körs (instruktion i
  nattrapporten). Rate-limitern är i-minne — Redis krävs vid >1 instans.
- 22 recept har needs_image (hellre än fel bild).
