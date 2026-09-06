# Checkpoint — 2026-09-06 (release-finish efter master-auditen)

Skriven så nästa session kan fortsätta utan att bygga om något. Allt nedan
är verifierat mot kod, tester eller live produktion — inget antaget för att
koden "finns". Föregående checkpointar (2026-09-01, master-auditen samma
dag) gäller i grunden; det här är vad som ändrats och vad som är sant nu.

## Läget i ett stycke

Matjakt är live på **matjakt.store** (GitHub Pages, bundlad frontend) mot
**matjakt.onrender.com** (Render, persistent disk). 240 recept (dubbletten
`biff-lindstrom` borttagen), tre släppta kedjor (Willys, Hemköp, City Gross).
Free/Premium 59/399 utan trial, Stripe i TEST-läge release-verifierat. SMTP
fortfarande osatt i Render (`mail: false`). Utvecklingslåset är på - appen
är inte lanserad.

## Release-finish 2026-09-06 - vad som gjordes

Commits `5e04cc0` … `9c89be0` (+ docs), alla pushade.

- **Observability:** JSON-logg på Render, `X-Request-Id` i varje svar och i
  varje loggrad (contextvar), accesslogg utan query och med maskerad IP,
  räknare i `GET /api/health` → `metrics` (`responses_5xx`,
  `auth_login_failed`, `stripe_webhook_rejected`, `mail_send_failed`,
  `pricing_gate_failed`, `unhandled_exceptions`, `slow_requests_2s` …).
- **Rate limit persistent:** `ratelimit.db` i datakatalogen, överlever deploy,
  minnesläge i tester, fallback till minnet om filen är trasig;
  `rateLimitPersistent: true` i health. Redis-vägen dokumenterad i RELEASE.md.
- **Browser-E2E (Playwright, riktig Chromium, mobil viewport):**
  `backend/tests/e2e/test_consumer_journey.py` - hela konsumentresan
  (signup → login → onboarding 4 steg → vecka → byt rätt → recept → Handla →
  finns hemma → skafferi → paywall → logout → login → allt kvar) och
  Premium/Stripe i testläge (mockad Stripe-gräns, riktigt signerad webhook,
  aktivering i UI:t, uppsägning → Free). Ingår i `tests/run.py`; CI-jobb `e2e`
  kör den i källform och mot det byggda bundlet.
- **Fel som E2E:n hittade och som är rättade:** receptsidan utan mängder vid
  byt-rätt-och-öppna (race), jämförelsesidan saknade ingång (knapp under
  butikskorten för Premium), 800 avvisade live-prisanrop per körning (stopp
  vid 429), 500 på `/api/products/batch` av delad SQLite-anslutning utan lås,
  CSP-headern blockerade låsskriptet, klientavbrott räknades som prisfel.
  Två till hittades först i CI (snabbare maskin): kontosynken (debouncad
  1,5 s) försvann när sidan lämnades för Stripe Checkout och återkomsten
  hämtade serverns äldre blob - veckan och onboardingen "ogjorda"
  (`flushServerSync` före navigering + pagehide med keepalive); och
  kontolagrets delade SQLite-anslutning saknade lås (401 på giltig session
  mitt under Premium-aktiveringen - lås runt varje publik metod).
- **Receptbanken:** dubblett borttagen; bildsöken förstår `ugnslax`/`laxfilé`;
  209 recept med licensierad bild, **32 saknar bild** (husmanskost utan
  stockfoto - behöver egna foton eller manuellt urval).
- **Frontend-bygge:** `npm run build` (esbuild) → `dist/frontend`, deployen
  laddar upp bygget: app.js 260 → 141 kB råt (81 → 44 kB gzip), en fil i
  stället för tretton moduler. Källorna orörda; ingen funktionsändring.
- **iOS/App Store:** `store/appstore/metadata/sv-SE/` (klart att klistra in),
  `review_notes.txt` (mall), absoluta juridiklänkar, `docs/IOS_RELEASE.md`.

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

`python backend/tests/run.py` → 876 tester gröna (inkl. 2 browser-E2E,
1 skipped), isolerad tempkatalog, inga riktiga anrop. `node --test` → 63.
`MATJAKT_E2E_FRONTEND_DIR=dist/frontend python backend/tests/run.py --pattern
"test_consumer*"` → grön mot bundlet. Skärmdumpar vid E2E-fel i
`backend/tests/e2e/artifacts/` (gitignorerad).

## Miljövariabler (Render)

Oförändrat sedan master-auditen. Nytt frivilligt: `MATJAKT_LOG_FORMAT`
(json|text; json är standard på Render).

## Kända öppna punkter

- Render deployar på push, inte på grön CI → stäng Auto-Deploy och koppla
  deploy-hook från `ci.yml` (Adam, dashboarden).
- SMTP: Resend-domänen ovärderad hos Loopia (`mail: false`).
- 32 recept utan bild.
- Live-prishämtningen (`/api/products/batch`) gör fortfarande ett anrop per
  vara; `scrape`-spärren 30/min per IP håller servern, klienten stannar vid
  första 429 - en batch-endpoint som tar hela listan vore bättre.
- Retention för inaktiva konton obeslutad; juridiska platshållare; Apple
  IAP-beslut; `cap add ios` kräver Mac.
- Ingen riktig monitor: räknarna i health måste läsas av någon.

## Final web release gate 2026-09-06 (kväll) - läget

- **Deploy bara på grön CI - mekaniken bevisad åt båda håll:** röd CI (merge-
  committen `eb63036`) → `deploy-backend` *skipped* och Pages-körningen
  *skipped*; grön CI (`9cfb8e4`) → `deploy-backend` kört (hook-secret saknas
  ännu → loggar "saknas") och Pages deployade v29 via `workflow_run`.
  **Render deployar dock fortfarande på push** (Auto-Deploy på i dashboarden)
  → `render.yaml` har `autoDeploy: false`, men dashboarden måste ändras och
  `RENDER_DEPLOY_HOOK` läggas som repo-secret (Adam).
- **Hemlighet läckt i publikt repo:** `MATJAKT_ADMIN_TOKEN` låg i klartext i
  `.claude/launch.json` (commit `27edd8a`, annan session). Borttagen ur filen
  (`eb63036`) men kvar i git-historiken → **måste roteras i Render och i
  lokal .env**. Rotationen ogiltigförklarar alla gate-tokens (härledda).
- **Health visar nu** `gate` (låset), `commit`, `mailFrom`, `pricingAudit`.
- **Produktionens prisaudit** kördes automatiskt första gången: 4 596
  kontroller, 240 recept, tre kedjor, täckning 99,7 % - RÖD på
  `kilopris_som_paketpris` 316 → visade sig vara ett **falskt larm i
  auditen** (lösvikt per kilo räknades som kilopris-som-paketpris; motorn
  var rätt). Auditen bedömer nu paketpriset (totalCost/packages), tester i
  `tests/test_pricing_audit.py`; motorn orörd.
- **Mejl:** DNS klart hos Loopia (DKIM + send), `_dmarc` saknas, SMTP-värden
  inte i Render (`mail: false`). Låset bevarar nu `?verify`/`?reset`.
  Checklista i `docs/RELEASE.md`.
- Sammanslagning med annan sessions commits (kontrollrum, utskick, statistik,
  `44ff642`): konflikter i CSP-headern och mailer lösta; 904 → 909 tester.

## Gate-stegen genomförda 2026-09-06 (sen kväll, via Adams Chrome)

- **Render:** Auto-Deploy = **"After CI Checks Pass"** (native; ingen hook-secret behövs; `render.yaml` behåller `autoDeploy: false` som fail-closed vid blueprint-synk). Admin-token roterad och laddad (omstart bekräftad).
- **Loopia:** `_dmarc.matjakt.store TXT "v=DMARC1; p=none; rua=mailto:adamfrom@icloud.com"` publicerad (syns på 8.8.8.8/1.1.1.1).
- **Resend:** domänen `matjakt.store` **verifierad** (DKIM + `rsend`/`send` CNAME) efter "Restart"; ny API-nyckel `matjakt-render-smtp` (Sending access, bara matjakt.store). "Enable Receiving" står kvar på → statusen visas som "partially verified" (bara kosmetiskt, utskick opåverkade).
- **Render env:** `SMTP_HOST/PORT/USER/FROM_EMAIL` + `SMTP_PASSWORD` satta → `mail: true`, `mailFrom: matjakt.store`.
- **Skarpt mejltest i produktion:** registrering → verifieringsmejl *Delivered* (Resend) → länk klickad → `emailVerified: true`; glömt lösenord → mejl *Delivered* → nytt lösenord → login 200, gammalt lösenord 401; okänd adress ger identiskt svar; `mail_send_failed` 0 efter domänverifieringen. **Första mejlet hamnade i skräpposten hos iCloud** (ny domän, DMARC nyss satt) - länkar i Skräp är avstängda i Apple Mail, flytta till inkorgen först.
- **Öppet:** `POST /api/products/batch` → tätt 429-flöde från riktiga klienter (livepris-loopen); Loopia visar förfallen faktura för kontot (domänen!); låset (`MATJAKT_GATE=0`) vid lansering; juridik senare (Adams beslut).

## Native + household + öppen app 2026-09-06/07 (natt)

- **Utvecklingslåset avvecklat i kod** (`9c1898d`): inga GATE_*, inga `/api/gate/*`,
  ingen fetch-wrapper, inget inline-låsskript (CSP utan hash). Kvar och testat:
  konto/hushåll 401, admin 404 (även fel token), partner 401, webhook 400
  (`test_removing_the_gate_removed_no_real_security`). Landningen är en enkel
  "Öppna Matjakt"-sida som bär `?verify/?reset/?invite` vidare. Health: `gate: false`.
- **CORS för native** (`CorsForNativeTest`): `capacitor://localhost` ekas på nio
  vägar, okända origins får standard-origin, aldrig `*`, inga credentials.
- **429-roten** (`476d119`): `/api/products/batch` var inte plan-gated → ny feature
  `live_prices` (Free: nej), servern svarar 403. Klienten hämtar livepriser bara
  för Premium, 5/20 varor per anrop, stopp + 60 s paus vid 429/403, inga
  filialanrop för Free. E2E räknar anrop: Free 0, Premium ≤ 12.
- **Riktig bugg bakom "flaky" bundle-E2E** (`9f5851c`): prisnyckeln saknade
  planen → Free-maskat svar låg kvar efter checkout. Fixad i roten.
- **Native-förberedelser** (`a3b5f0c`): `npm run build:native` → `dist/native`
  med API-URL i metataggen, `webDir` = bygget, `@capacitor/app` + `@capacitor/browser`
  (Stripe externt, appStateChange, appUrlOpen med bevarad query). Mac-kommandon
  och simulatorkontroller i `docs/IOS_RELEASE.md`. **Ingen `ios/`-katalog kan
  skapas på Windows** - simulatorn är Adams steg.
- **Nätfel**: backoff 8 s→2 min på prissättning/kampanjer (ingen anropsloop),
  utloggning bara vid 401 (oförändrat). Sju oanvända importer bort.
- **CI**: frontend-jobbet och Pages-deployens testjobb kör `npm ci` (esbuild
  behövs av `tests/build-native.test.js`); main var röd en körning (`a3b5f0c`),
  grön igen från `6e422e5`.
- **Verifierat i produktion (backend `6e422e5`)**: `gate: false`, recipes 200
  utan token, account/household 401, admin 404 med och utan token, `/api/gate/check`
  404, batch anonymt 403, CORS-eko för `capacitor://localhost`, preflight 204,
  prisaudit GRÖN 4 596 kontroller / 99,7 %. Tester: backend 1117 (skipped 2),
  node 106, E2E 4 resor mot källor och bundle; prod-DB-hashar oförändrade av
  testkörningarna.
- **Kvar/blockerare:** iOS-simulator och fysisk iPhone (Mac + Xcode, Apple-ID);
  universella länkar kräver Team-ID; Stripe TEST; juridik parkerad (Adams beslut);
  Loopias förfallna faktura (domänen!).

## Granskningar och fixar samma natt (2026-09-07)

- **P0 - kontodatabas i publikt repo:** `backend/data/backups/` (tre backupset,
  tolv SQLite-filer inkl. `matjakt.db` med e-post + lösenordshashar + salt,
  reset-token-hashar, synkad kontodata, fritextfeedback) var **spårad i git
  sedan 2026-08-31** (.gitignore-regeln kom efter). Borttagen ur HEAD
  (`1697d1f`), `.gitignore` breddad (`*.db`, `.env.*`), CI vägrar spårade
  databasfiler. **Historiken är inte omskriven** - kräver Adams beslut
  (force-push påverkar alla kloner/worktrees) och en bedömning av
  anmälningsplikt (GDPR art. 33): 198 användarrader varav 11 adresser inte
  ser ut som testkonton (räknat, inte listat).
- **Hushållet (`ed69688`)**: fem fel ur granskningen fixade med tester -
  "Har hemma" rör inte längre familjens skafferirad, raderingar når andra
  telefonen (soft delete + gravstenar i delta), Ångra efter × och
  "Återställ alla" går via servern, Ångra-race, 401 stoppar pollningen.
  Öppet (P2): hushållsprofilernas allergier påverkar inte receptvalet
  (produktbeslut - vems allergier gäller?), servern verifierar inte
  klientens GTIN mot produktlagret, notiser konsumeras av första enheten.
- **Säkerhet (`414835e`)**: delat lås på kontoanslutningen (analytics,
  mail_log), socket-timeout mot Slowloris, lösenordsbyte dödar
  reset-länk, hinkar på öppna vägar + billing, STARTTLS verifierar
  certifikat, enhetstoken kräver ägarskap, secret_scan breddad, fyra
  attribut escapade, safeHttpUrl på checkout-URL. Öppet (P1, kräver
  beslut/större ändring): registreringen svarar olika för befintlig adress
  (kontoenumeration, bromsad av 5/h), återställningens svarstid skiljer
  (mejl skickas synkront), `admin.html` utan CSP-meta på Pages,
  hushållslagrets läsvägar utan lås, `MAIL_SECRET` faller tillbaka på
  admin-token.

