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

## Kontrollrummet (2026-09-06)

`/app/admin.html` (serveras av backend-servern, dvs. matjakt.onrender.com/app/admin.html,
admin-token) visar överst MÄNNISKOR: konton, aktiva 7/28 dagar, Premium, tratten
per registreringsvecka (registrerade -> skapade en vecka -> tillbaka efter 7 dagar
-> Premium, "ofullständig" tills alla haft sju dagar på sig), händelserna dag för
dag med unika konton, och fritextfeedbacken. Därunder prisdatabasen som förut.
Skriptet ligger i `admin.js` - serverns CSP (`script-src 'self'`) blockerade det
gamla inline-skriptet, så sidan var död när den serverades av backend.

Datan: `backend/services/analytics/` med två tabeller i kontodatabasen
(`analytics_daily` anonymt per dag, `analytics_user_days` konto x dag x händelse,
aldrig klockslag/IP) plus `users.last_active_day` som sessionsuppslaget sätter
högst en gång per dag. De gamla räknarna i kv_cache rensades efter 7 dagar (så
"14 dagar" tappade hälften) - de flyttas in vid uppstart. Frontend skickar
sessionen med i `trackEvent`, så personer kan skiljas från klick. Raderas
kontot följer mätraderna med. Integritetspolicyn nämner produktstatistiken.
Läses via `GET /api/admin/insights` (`/testresultat` = samma svar).

Lanseringsmått (30 dagar efter att låset öppnas): 100 personer som planerat
en vecka, 10 tillbaka vecka två, 1 betalande.

## Trafik och utskick (2026-09-06)

Trafik: `frontend/traffic.js` laddar Plausible eller Umami när
`<meta name="matjakt-traffic">` (landningssidan + app/index.html) säger
`plausible:matjakt.store` eller `umami:<website-id>`. Tomt = av; aldrig på
localhost. Värdarna finns i CSP:n (meta i app/index.html + api_server).

Utskick: `backend/services/mailings.py`. Välkomstserien dag 3 och dag 7
(fönster 3-7 resp. 7-21 dagar efter registrering) och Kampanjtorget varje
torsdag, allt kl. 08:00 Europe/Stockholm. Dag 0 = verifieringsmejlet (nu med
igångsättningstips; transaktionellt). REGLER: bara samtycke
(`users.marketing_consent`, kryss vid registrering eller Konto-vyn) OCH
verifierad adress; varje mejl har HMAC-signerad avprenumerationslänk
(`GET /api/mail/unsubscribe?u=&t=`, gate-exempt, rate-limitad) + List-Unsubscribe;
`mail_log` gör varje steg en-gång; tomt torg skickas aldrig; kedja = användarens
favoritbutik om släppt, annars alla släppta (aldrig Coop). AV tills
`MATJAKT_MAILINGS_ENABLED=1` (render.yaml har "0"); `MATJAKT_MAIL_SECRET`
signerar länkarna (fallback admin-token); `MATJAKT_PUBLIC_API_URL` för länkar.
Kontrollrummet har ett Utskick-kort: status, mottagare, "Skicka exempel till
mig" (kräver bara SMTP) och "Kör dagens utskick nu". Innan påslag: verifiera
SMTP-leverans + SPF/DKIM för avsändardomänen.

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
