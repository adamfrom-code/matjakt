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
- **Receptbanken:** dubblett borttagen; bildsöken förstår `ugnslax`/`laxfilé`;
  209 recept med licensierad bild, **32 saknar bild** (husmanskost utan
  stockfoto - behöver egna foton eller manuellt urval).
- **Frontend-bygge:** `npm run build` (esbuild) → `dist/frontend`, deployen
  laddar upp bygget: app.js 260 → 141 kB råt (81 → 44 kB gzip), en fil i
  stället för tretton moduler. Källorna orörda; ingen funktionsändring.
- **iOS/App Store:** `store/appstore/metadata/sv-SE/` (klart att klistra in),
  `review_notes.txt` (mall), absoluta juridiklänkar, `docs/IOS_RELEASE.md`.

## Tester

`python backend/tests/run.py` → 875 tester gröna (inkl. 2 browser-E2E,
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
