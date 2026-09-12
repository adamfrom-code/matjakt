# Release – reproducerbar process och kvalitetsgrind

*Uppdaterad 2026-09-06. Ingen release får bygga på att någon minns manuella kommandon.*

## Vad som händer vid `git push origin main`

1. **CI** (`.github/workflows/ci.yml`): kompilering, hela backend-sviten i en isolerad tempkatalog utan riktiga anrop, frontend-tester, `node --check`, hemlighetsskanning, kontroll att `.env` inte är spårad, kontroll att frontendens cache-version inte står i källan och att stämpeln i bygget är digesten av bygget.
2. **Pages** (`.github/workflows/deploy.yml`): startar när CI är GRÖN på main (`workflow_run`), kör `npm test`, bygger `dist/frontend` med `npm run build` (esbuild: `app.js` buntad + minifierad, `styles.css` minifierad, källorna orörda) och deployar den till matjakt.store med `matjakt-api-url` satt till Render.
3. **Render**: bygger `backend/Dockerfile` och deployar. *Observera:* Render lyssnar på pushen direkt – inte på CI. En röd svit stoppar i dag Pages men inte backend. Åtgärd (Adam, Render-dashboarden): stäng av *Auto-Deploy* och lägg ett deploy-hook-steg sist i `ci.yml` (`curl -X POST "$RENDER_DEPLOY_HOOK"` med hooken som GitHub-secret). Tills dess: pusha bara grönt.

## Kvalitetsgrind – release är RÖD om något av detta gäller

| Kontroll | Kommando / var | Krav |
|---|---|---|
| Backend-svit | `python backend/tests/run.py` (E2E:n ingår när Playwright finns) | alla gröna |
| Frontend-svit | `node --test` | alla gröna |
| Syntax | `node --check frontend/app/app.js && python -m compileall -q backend` | ok |
| Hemligheter | `python backend/scripts/secret_scan.py` | inga träffar |
| Versioner | `python backend/scripts/check_frontend_version.py` och `... --build dist/frontend` | platshållare i källan, stämpeln i bygget = digesten av bygget |
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

# 2. Frontend-ändring? Ingenting att göra (L9). Versionen står inte i källan -
#    bygget stämplar in eran plus en digest över det som byggts, så en ändrad
#    frontend byter cache-nyckel av sig själv. Kontrollera bygget om du vill:
npm run build && python backend/scripts/check_frontend_version.py --build dist/frontend

#    Eran (den läsbara etiketten "v110", inte cache-nyckeln) höjs vid en riktig
#    release - inte per paket:
node scripts/frontend_version.mjs --bump

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

## Deploy bara på grön CI

Backend deployas av jobbet `deploy-backend` i `ci.yml`: det körs efter `backend`, `frontend`, `security` och `e2e` och bara när alla är gröna på en **push till main**, och anropar Renders deploy-hook med `ref=<committen>` (repo-secret `RENDER_DEPLOY_HOOK`). Frontend deployas av `deploy.yml` som triggas av CI:s slutförande (`workflow_run`, bara `success` för en push till main) och checkar ut **exakt den commit CI testade** (`workflow_run.head_sha`). `ci.yml` kör en körning per gren i taget (`concurrency`), så en äldre grön körning kan inte deploya efter en nyare push. `render.yaml` har `autoDeploy: false`. Undantag: `workflow_dispatch` på `deploy.yml` är en manuell väg med bara `npm test` som grind - använd den inte för släpp.

**Engångssteg i Render-dashboarden (Adam):** Service → Settings → *Auto-Deploy: Off*; Settings → *Deploy Hook* → skapa och kopiera URL:en → GitHub → repo → Settings → Secrets → `RENDER_DEPLOY_HOOK`. Hooken är en hemlighet: aldrig i chatt, repo eller loggar (jobbet skriver bara "triggad").

**Bevis att röd CI inte deployar - utan att göra main röd:**
1. Render → *Events*: bara deploys med trigger *Deploy hook* efter att Auto-Deploy stängts av (en push utan grön CI får inte synas där).
2. Pusha en avsiktligt röd commit (ett `assert False` i en TESTFIL, aldrig i körande kod) på en gren och öppna PR: CI röd, `deploy-backend` visas som *skipped*, `deploy.yml` startar inte. Stäng PR:en.
3. Positivt bevis på main: nästa gröna push → `deploy-backend` grön → `GET /api/health` → `commit` = den pushade committens 12 första tecken inom ~5 min, och Pages serverar `app.js?v=` från samma commit.
Dokumentera körnings-id:n i CHECKPOINT.md.

## Utvecklingslåset är avvecklat (2026-09-06)

Konsumentvägarna kräver ingen token; konto/hushåll kräver session, admin admin-token (enhetlig 404), partner partnernyckel, Stripes webhook sin signatur (`test_removing_the_gate_removed_no_real_security`). `GET /api/health` → `gate: false`. Native-appen (`capacitor://localhost`) fungerar därför utan låsskärm; CORS ekar bara uttryckligen betrodda origins (`CorsForNativeTest`).

## Prisauditen i drift

Auditen (`services/grocery/audit.run_pricing_audit`, alla recept × ingredienser × släppta kedjor) körs i bakgrunden vid serverstart (efter 120 s, `MATJAKT_PRICING_AUDIT_DELAY`) och efter varje lyckad import; begärs en ny medan en pågår köas den och körs direkt efteråt. `GET /api/health` → `pricingAudit`: `gate` (GRÖN/RÖD/INGEN DATA/FEL), `kontroller`, `saknade`, `tackningProcent`, `perKedja` (kontroller/saknade/täckning per kedja), `recept`, `kedjor`, `flaggor` (alla räknare), `ranAt`, `durationSeconds`, `reason`, `commit`. Bara siffror - exemplen finns i admin-vägen `POST /api/admin/pricing-audit` (som också uppdaterar summeringen).

Gate-regler: 0 kontroller, eller en kedja helt utan priser → **INGEN DATA**; någon av de farliga kategorierna > 0 (gram→styck, volym→styck, estimat, otolkad förpackning, kilopris som paketpris) eller täckning < 90 % totalt eller i någon kedja → **RÖD**; havererad audit → **FEL**. **Releasekrav:** `gate: GRÖN`, `commit` = körande deploy, `kedjor` = alla släppta, `kontroller` i tusental, `ranAt` efter senaste uppstart. Rapportera alltid `saknade`/`perKedja` bredvid gaten.

## Mejl: skarpt test efter att SMTP satts i Render

Förutsättningar: Resend-domänen `matjakt.store` *Verified* (DKIM `resend._domainkey` och `send`-posten finns hos Loopia sedan 2026-09-06). **Lägg `_dmarc.matjakt.store TXT "v=DMARC1; p=none; rua=mailto:<adress som läses>"` före testet** - Gmail/Outlook väger avsaknad av DMARC negativt för en ny domän. Render: `SMTP_HOST=smtp.resend.com`, `SMTP_PORT=587`, `SMTP_USER=resend`, `SMTP_PASSWORD=<Resend-nyckel, direkt i Render>`, `SMTP_FROM_EMAIL=noreply@matjakt.store` (eller `Matjakt <noreply@matjakt.store>`). Mejlen bär Date, Message-ID och avsändarnamn. Mejllänkarna (`?verify`/`?reset`) landar på `matjakt.store` och följer med in i appen.

*Serversida, utan inkorg (kan verifieras utifrån):*

| Steg | Förväntat |
|---|---|
| `GET /api/health` | `mail: true` (= konfigurerad, inte bevisat fungerande), `mailFrom: "matjakt.store"`, `metrics.mail_send_failed` = 0 efter registreringen |
| `POST /api/auth/request-password-reset` med OKÄND adress | 200, samma svar som för känd (ingen enumerering) |
| `POST /api/auth/verify-email` med påhittad token | 400 |
| Samma reset-token två gånger | andra gången 400 (engångs, 1 h) - även testat i sviten |

*Kräver Adams inkorg:*

| Steg | Förväntat |
|---|---|
| Registrera nytt konto | svaret säger att verifieringsmejlet skickats; mejl inom en minut, From `Matjakt <noreply@matjakt.store>`, inte i skräpposten |
| Klicka verifieringslänken | "verifierad"; kontot visar inte längre "inte verifierad"; samma länk igen avvisas |
| Glömt lösenord → mejl → länk → nytt lösenord | inloggning med NYA lösenordet fungerar; gamla nekas; andra enheter utloggade |
| Öppna reset-länken igen | avvisas |
| Mejlhuvuden (visa original) | `DKIM: PASS` (d=matjakt.store) - det som bär DMARC; `SPF` PASS på `send.matjakt.store` om Resend skriver om Return-Path, annars `none` (ok); `DMARC: PASS` när posten finns |
| Resend → Logs | levererat, inga studsar/klagomål |

Känt och accepterat: registrering svarar "det finns redan ett konto" (kontoenumerering via registrering är en medveten UX-avvägning; reset-vägen svarar identiskt oavsett). `noreply@` kan inte ta emot svar (ingen MX på matjakt.store) - supportadressen står i appen.

## Juridik

Avtalspart och personuppgiftsansvarig är ifyllda sedan I3: **Adam From, enskild firma, org.nr 199511045651, Södra Kansligatan 25, 805 52 Gävle**, kontakt `adamfrom@icloud.com`. Kontaktblock med postadress finns på båda sidorna — e-post ensam räcker inte för konsumentköp. Ångerrätten beskriver B3:s faktiska mekanism (kryssruta före köp, samtycket tidsstämplat, databasen avgör om Checkout får starta, ordalydelsen versionsmärkt).

`tests/juridik.test.js` failar om en `class="placeholder"` kommer tillbaka, om org.nr saknas, om kontaktblocket saknar postnummer eller om ångerrättstexten inte nämner distansavtalslagen.

`support@matjakt.store` har **ingen vidarebefordran** ännu. Sätts den upp ska adressen bytas på alla fem ställena samtidigt (två juridiksidor, landningssidan, 404, och `EPOST` i testet) — en halvbytt supportadress är sämre än ingen.

## KVAR FÖR ADAM INNAN PUBLIK LANSERING

Det här är saker bara kontoinnehavaren kan göra. Koden är byggd och väntar på var och en; ingen av dem kräver en deploy.

### 1. Stripe: moms  (B2)

Kontot står i **testläge**. Gör stegen där först, sedan om i live-läget.

| Steg | Var | Notering |
|---|---|---|
| 1 | Skapa **nya** priser, 59,00 SEK/mån och 399,00 SEK/år, *Include tax in price* = **Yes** | `tax_behavior` går **inte** att ändra i efterhand. Nya pris-id:n måste in i Render. |
| 2 | Settings → Tax: huvudkontorets adress (Sverige) + momsregistrering SE | `GET /v1/tax/settings` ska svara `status: "active"` |
| 3 | Settings → Customer emails: *Successful payments* och *Refunds* | Ett kvitto utan momsuppdelning kan en svensk kund inte bokföra |
| 4 | `GET /api/admin/stripe-check` med admin-token | Kör om hela kontrollen **utan omstart** och skriver in klartecknet som checkout läser |

Priserna 59 och 399 kr är **inklusive 25 % moms** — prisinformationslagen kräver att visat pris till konsument är totalpriset. 59 kr = 47,20 + 11,80. 399 kr = 319,20 + 79,80. Beloppen ändras alltså inte.

**Stripes *Legal entity* måste stå på samma juridiska person som juridiken ovan.** Momsen bokförs på den enhet Stripe känner till, inte på den som står i policyn.

Ingen brådska i drift: `automatic_tax` skickas först när Stripe självt bekräftar att Tax är aktivt (`tax.py`), så köpknappen fungerar hela tiden. Tills dess står orsaken i klartext i `/api/health` → `stripe.priceCheck`.

**OSS:** prenumerationen går att köpa från vilket EU-land som helst, och då gäller köparlandets momssats. Stripe Tax räknar rätt sats av sig själv, men OSS-registreringen är din. B2b lägger en kontroll som larmar första gången en betalande kund har adress utanför Sverige.

### 2. Render: backupnycklarna  (B5)

```
MATJAKT_BACKUP_TOKEN         skild från admin-token
MATJAKT_BACKUP_PUBLIC_KEY    certifikathalvan av ett openssl req -x509-par
```

Den **privata** nyckeln får aldrig finnas i miljön — servern behöver bara den publika för att kryptera.

Backuperna tas som vanligt varje natt utan dem; det är bara *nedladdningen* som är stängd (`/api/admin/backup-download` svarar 404/503, `pull_backup.py` larmar med exit 1). Fail closed med avsikt: alternativet var att fortsätta strömma varje e-postadress i klartext över en enda headerhemlighet.

### 3. Klickspårning i mejlen  (I7, ditt beslut)

`mail_klick` har sitt namn men ingen avsändare. Den kräver en `GET /api/mail/click`-omdirigering och ändrade mallar — **och den ska stå i integritetspolicyn innan den byggs**. Klickspårning i marknadsmejl är personuppgiftsbehandling och smygs inte in.

### 4. Övrigt

- **App Store och Play:** `review_notes.txt` har två platshållare för granskningskontots e-post och lösenord. Kör om `backend/scripts/make_store_screenshots.py` när våg L är klar — skärmbilderna åldras med designen.
- **Plausible:** `<meta name="matjakt-traffic">` finns men är tom. Sätt `plausible:matjakt.store` när du vill ha besöksstatistik. Kakfritt, redan i CSP:n, ingen samtyckesbanner.
- **`RENDER_DEPLOY_HOOK`** i repo-secrets är valfri. Utan den deployar Render ändå via sin egen Auto-Deploy, och hälsogrinden väntar på committen oavsett (K3b). Med den får vi `?ref=<SHA>` så Render bygger exakt den gröna committen i stället för grenspetsen.

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
| Produktions-smoke | `curl /api/health`, `backend/tests/prod_persistence_e2e.py` (manuell) | nej | – |
| Säkerhetsregression | auth-härdning, rate limits, admin 404, HSTS, hashade token, testspärr | ja | – |
| Visuell regression | skärmdumpar sparas av E2E:n vid fel (`tests/e2e/artifacts/`) | nej | jämförelse mot referensbilder |
