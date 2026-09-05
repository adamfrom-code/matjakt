# Checkpoint — 2026-09-06 (master-audit)

Skriven så nästa session kan fortsätta utan att bygga om något. Allt nedan
är verifierat mot kod, tester eller live produktion — inget antaget för att
koden "finns". Föregående checkpoint (2026-09-01) gäller i grunden; det här
är vad som ändrats och vad som är sant nu.

## Läget i ett stycke

Matjakt är live på **matjakt.store** (GitHub Pages) mot **matjakt.onrender.com**
(Render, persistent disk). 241 recept, tre släppta kedjor (Willys, Hemköp,
City Gross) med verifierade butikspriser och kedjereferenspriser; ICA, Coop och
Lidl finns i registret men är gated (`RELEASED_CHAINS`) - och frontend speglar
den listan (`test_frontend_contract.py`). Free/Premium 59/399 utan trial,
Stripe i TEST-läge release-verifierat (28/28 skarpa kontroller, servern
verifierar sina pris-id vid uppstart och rapporterar det i `/api/health`).
SMTP är fortfarande osatt i Render (`mail: false`).

## Master-auditen 2026-09-06 - vad som gjordes

Commits `bcd6957` … `6aade83` (elva stycken), alla pushade och deployade.

- **Critical rättat:** publiceringen av priser var inte atomisk - en krasch
  mitt i lämnade ett halvt dataset synligt. Nu en transaktion
  (`GroceryStore.bulk_transaction`), rullas tillbaka i sin helhet, körningen
  märks failed.
- **High rättade:** login-timingorakel (okänd e-post körde inte PBKDF2);
  trasig Content-Length dödade varje POST; oväntade undantag stängde
  anslutningen (nu 500 på svenska via `_guarded`); dyra/öppna vägar utan
  rate limit; XSS-sinks i receptkort/receptsida/butiksnamn; refreshUser
  loggade ut på nätfel; Primat utan omförsök och med fel verified_at;
  perCategory=0 kringgick 30 %-regeln; trasig kategori räknades som komplett.
- **Auth:** verifierings-/reset-token hashade, verifiering 7 dygn, utgångna
  sessioner städas, admin-vägar enhetligt 404, HSTS bakom proxyn.
- **Testsviten skapade riktiga Stripe-kunder** ur .env: central spärr
  (`data_guard.guard_outbound_call`) + `tests/run.py` tömmer hemligheter.
- **Frontend:** bara släppta kedjor valbara, ärlig Premium-pitch, inga
  emoji-ikoner, SW-uppdateringsrad, versioner låsta på tre ställen,
  onboarding-layout, tomt tidsfilter, bildfallback, TheMealDB avstängd
  (`MATJAKT_EXTERNAL_RECIPES`), receptbilder -34 %.
- **Drift:** `.github/workflows/ci.yml` (svit, node, secret_scan, versioner),
  `docs/DISASTER_RECOVERY.md`, `docs/DATA_MAP.md`, `docs/RETENTION.md`,
  `docs/RELEASE.md`, `docs/BACKUP.md` + `scripts/pull_backup.py`,
  admin `GET /api/admin/backup-download`, `GET /api/admin/stripe-check`.
- **Native:** Android-ikon/splash från `resources/`, `capacitor.config.json`
  med iOS-sektion, `ios-prep/` (Info.plist, PrivacyInfo), `docs/IOS_RELEASE.md`.

## Tester

`python backend/tests/run.py` → 865 tester gröna (isolerad tempkatalog,
inga riktiga anrop). `node --test` → 63. Sviten körd två gånger i rad med
sha256 på de riktiga databasfilerna före/efter (se slutrapporten 2026-09-06).
Prisauditen lokalt: `gate: GRÖN` (0/0/0/0/0 + 0 kilopris-som-paketpris).

## Miljövariabler (Render)

Som i `render.yaml`. Satta: MATJAKT_PREMIUM_CODE, MATJAKT_ADMIN_TOKEN,
PRIMAT_API_KEY, DABAS_API_KEY, STRIPE_SECRET_KEY (test), STRIPE_WEBHOOK_SECRET,
STRIPE_PRICE_MONTHLY, STRIPE_PRICE_YEARLY, MATJAKT_TRUST_PROXY=1,
MATJAKT_GROCERY_SCHEDULE_ENABLED=1. **Osatta:** SMTP_HOST/USER/PASSWORD/
FROM_EMAIL (Resend, domänen väntar på DNS hos Loopia).

## Kända öppna punkter

- Render deployar på push, inte på grön CI → stäng Auto-Deploy och koppla
  deploy-hook från `ci.yml` (Adam, dashboarden).
- SMTP: Resend-domänen ovärderad hos Loopia; tillfälligt
  `SMTP_FROM_EMAIL=onboarding@resend.dev` fungerar bara till Adams adress.
- Rate limit är per process - blir svag vid fler än en Render-instans.
- Primat: cursorn sparas inte mellan körningar (partiella katalogen hämtar
  samma sidor igen). Gated tills App-nivå/licens.
- Receptbanken: `biff-lindstrom` och `biff-a-la-lindstrom` är samma rätt
  (ingrediens-likhet 0,86); källa `backend/recipe_sources/*.json`.
- Retention för inaktiva konton och feedback obeslutad (`docs/RETENTION.md`).
- Juridik: platshållare i integritetspolicy/villkor; Apple IAP-beslut
  (`docs/IOS_RELEASE.md`).
- Ingen automatiserad browser-E2E; konsumentresan verifierades för hand
  2026-09-06 (onboarding 4 steg → vecka → recept → Handla → skafferi →
  konto → logga ut/in med bevarad vecka).
