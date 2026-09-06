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
