# Release Candidate Report — Matjakt iOS 1.0 (build 2)

Skriven 2026-09-19 av Claude (Claude Code) på uppdrag av Adam, enligt
MASTERARBETORDERN ("Produktionsklar v1 + ny TestFlight/App Store-build").
Allt nedan är läst ur GitHub, Render (`/api/health`), App Store Connect API
och lokala körningar — ingenting är antaget.

## 1. Identitet

| | |
|---|---|
| MAIN SHA | `40b715c (T5b, #222)` |
| PRODUCTION SHA (`/api/health` → `commit`) | `40b715c — lika med main; deployad via hooken efter grön CI` |
| VERSION | 1.0 (`MARKETING_VERSION`) |
| BUILD | 2 (`CURRENT_PROJECT_VERSION`, N1b) |
| GIT SHA i bygget | `40b715c` |
| Bundle-id / Apple ID | `se.matjakt.app` / 6811440663 |
| TESTFLIGHT STATUS | 1.0 (2) uppladdad 2026-09-19 15:24, `VALID`; intern TestFlight `IN_BETA_TESTING` (de interna grupperna `matjakt1` och `bkl` får bygget automatiskt); "What to Test" satt |
| EXTERNAL TESTFLIGHT STATUS | `READY_FOR_BETA_SUBMISSION` — **inte skickad till Beta App Review**, medvetet: IAP-flaggorna är av på Render (BLOCKED – ADAM 2) och produkterna saknas (BLOCKED 1), så bygget visar i dag Stripe-vägen, som inte får granskas (P02a). Skickas när 1–2 är lösta (`testflight.py external <build> matjakt`) |
| APP STORE REVIEW STATUS | **Inte inskickad.** Version 1.0 står i `PREPARE_FOR_SUBMISSION` med build 2 kopplad, all metadata och skärmbilder på plats, **manual release**. Ordern tillät inlämning bara med alla gates gröna — tre är externa och röda (BLOCKED 1–5) |

## 2. Testerna (senaste main)

| | Resultat | Var |
|---|---|---|
| BACKEND TESTS | 2 752 OK, 4 överhoppade (skip-budget), 344 s — körd två gånger i natt: på `9d04e91` och på slutliga `40b715c` | `backend/tests/run.py` (isolerad datakatalog) |
| FRONTEND TESTS | 844 pass, 0 fail (main 40b715c) | `node --test` |
| E2E | 32 OK (konsument-, hushålls-, reset-länk- och adminresan) + `test_mobil_ergonomi` OK (main 40b715c); i CI: Browser-E2E grönt på 40b715c | `backend/tests/e2e/` (Playwright, ingår i run.py) |
| NATIVE | `test_ios_*` OK, `tests/ios-signeringen.test.js` OK; arkiv ARCHIVE SUCCEEDED (1.0/2), export+uppladdning EXPORT SUCCEEDED (`scripts/ios_testflight.sh`, Admin-nyckeln) | `test_ios_*.py`, `tests/ios-signeringen.test.js`, arkiv + export |
| LINT | ruff: All checks passed · eslint: 0 fel (15 varningar, förbefintliga) | `ruff check backend`, `npx eslint .` |
| SECRET SCAN | inga hemligheter i spårade filer | `backend/scripts/secret_scan.py` |
| MIGRATIONS | inga väntande: schemat migreras vid start (kolumntillägg i `AccountStore`/`RecipeStore`), `migrate_*.py` är historiska | |
| BUILD | `npm run build:native` + `npx cap sync ios` utan diff i spårade filer | |

## 3. Drift — tre statusar

**DEPLOY HEALTH: GRÖN.** `smoke.py --url https://matjakt.onrender.com/api
--stripe-lage test`: health 200/ok, prisplattformen aktiv, recipes 200,
account/state 401 utan token, adminvägen 404, Stripe i test-läge.
Deploykedjan (CI → `RENDER_DEPLOY_HOOK?ref=SHA` → hälsogrind) har följt
varje merge i natt: produktion körde `43ffde7`, `fb5ab1f`, `faac27b`, …
inom minuter efter respektive merge.

**LAUNCH READINESS: RÖD (ett hinder, data — inte kod).** Prisauditens grind
är `RÖD`: 5 964 kontroller, 99,5 % täckning (Willys 100 %, City Gross 99,7 %,
Hemköp 99,5 %, ICA 98,9 %), 29 saknade rader, och **40 estimat-rader** —
alla på msk/tsk av tomatpuré (20), sirap (8), currypasta (4), honung (4),
sambal oelek (4). Grinden är röd enbart av `estimat` (alla andra
grindflaggor 0). Orsaken är känd och medveten: volym→gram för de här
varorna saknas i Livsmedelsverkets källa och projektet har beslutat att
inte gissa dem (`docs/VOLYMVIKTER_ATT_GRANSKA.md`, "Vad som INTE finns i
källan"; `test_verified_density.py`). Se BLOCKED – ADAM 6.

**DATA QUALITY: GUL.** 230 recept (P04a/b: identitet + alias), 206
kanoniska ingredienser (P05a), varje ingrediensrad bär `canonicalId`
(P05b) och registrets alias når prismatchningen (P05c). Bildstatus (P09a):
62 EXACT, 54 GOOD_VARIANT, 51 NEEDS_REVIEW, 52 REJECTED, 11 MISSING —
appen visar nu bara de 116 bekräftade fotona, resten reservkort (P09b/c).
Produktdata: 35 021 produkter, Dabas-träff 12,5 % totalt. Auditens
`smakords_misstanke` 58 (heuristik, inte grindande).

## 4. Apple In-App Purchase (P02a–P02h)

| | Läge |
|---|---|
| APPLE IAP | Implementerat: `@capgo/native-purchases` (StoreKit 2), köp med `appAccountToken`, JWS → `/api/billing/apple/transaction`, StoreKits lokaliserade pris på knapparna, väntläge/pending/cancel/error, `transactionUpdated`-lyssnare, återsynk vid start (P02d). **Av i produktion** tills `MATJAKT_APPLE_IAP=1` når Render (BLOCKED – ADAM 2). |
| STRIPE WEB | Oförändrad: 59 kr/mån, 399 kr/år, test-läge i produktion (`stripe.mode=test`). Webben nekar Checkout (409) när en Apple-prenumeration lever. |
| RESTORE PURCHASE | "Återställ köp" (`restorePurchases` + `getPurchases(onlyCurrentEntitlements)` → anmälan), visas bara i StoreKit-läget. |
| MANAGE SUBSCRIPTION | "Hantera prenumeration" → Apples ark när källan är Apple, Stripes portal när den är Stripe. |
| SANDBOX REVIEW PATH | P02f: produktionsservern godtar en Sandbox-transaktion efter full verifiering (Apples rot, exakt bundle-id, produkt i allowlisten, miljön ur den signerade transaktionen) när `MATJAKT_APPLE_IAP_ACCEPT_SANDBOX=1`. Sju tester. Flaggan i `render.yaml` (P02h) men **inte aktiv på Render** (blueprint-synk sker inte) — BLOCKED – ADAM 2. |
| Produkter i App Store Connect | **Finns inte** — BLOCKED – ADAM 1. |
| Ingen automatisk trial | J3b: aktiveringstrialen borttagen, regressionsvakt, reviewnoterna nämner ingen. |
| Reviewnoterna | Engelska, beskriver det slutliga bygget (P02g). Ligger i `store/appstore/metadata/review_notes.txt` och är inskrivna i TestFlights Beta App Review-noter. |

## 5. App Store Connect — läget just nu (läst via API)

| | Läge |
|---|---|
| Version 1.0 | `PREPARE_FOR_SUBMISSION`, **releaseType MANUAL** (ändrat från AFTER_APPROVAL) |
| Namn / undertitel | "Matjakt: matbudget & veckomeny" / "Riktiga matpriser, din budget" |
| Beskrivning, nyckelord, promo, support-/marknads-/integritets-URL | satta ur `store/appstore/metadata/sv-SE/` (beskrivningen utan iOS-pris, I5b) |
| Kategori | Food & Drink |
| Åldersgräns | 4+ (deklaration komplett; hälsa/kost = ja) |
| Skärmbilder | 6 × 6,7" + 6 × 6,5", `COMPLETE` (I5c-skriptet, fixturdata) |
| Bygge kopplat till versionen | 1.0 (2), `VALID`, kopplad till versionen; `usesNonExemptEncryption=false`, minOS 15.0 |
| App Review-kontakt | **saknas** (förnamn, efternamn, telefon) — BLOCKED – ADAM 3 |
| Granskningskonto | **saknas** — BLOCKED – ADAM 3 |
| App Privacy | **inte besvarat** (API saknar stöd) — BLOCKED – ADAM 4 |
| Prenumerationsgrupp/produkter | **saknas** — BLOCKED – ADAM 1 |
| Paid Apps Agreement | okänt/ej verifierbart via API — BLOCKED – ADAM 5 |
| TestFlight | interna grupper `matjakt1`, `bkl`; externa `matjakt`, `matjaktjhh` (publik länk). Beta-noter satta. Integritets-URL rättad till https. |

## 6. Prestanda (AM/AN)

Lokalt mot dev-servern, `/app/`, efter AM1/AM2/AN1:

| | Före (AM-baslinje) | Efter |
|---|---|---|
| DOMContentLoaded / load | 421 / 452 ms | 236 / 236 ms (kall) · 325 ms (varm) |
| Resurser / bytes | 73 / 1,36 MB | 68 / 400 KB (kall) · **2 KB (varm)** |
| `/api/entitlements` vid start | 2 | **1** |
| `/api/recipes/shelves` vid start | 2 | **1** |
| Receptbanken (`/api/recipes?limit=500`, 261 KB) | hämtades varje start | cachad 120 s; svag ETag → `304` utan kropp vid revalidering (verifierat mot servern med curl) |
| Offline | ingen reservbank | förhandscachad vid SW-install (AN2) |

## 7. Mobilgranskningen (AO)

DOM-mätt i 375 px (skärmdumparna i panelen var artefakter: panelen ~420 px
hög, fixerade element följer den synliga ytan — "tabraden mitt på skärmen"
och "tom Recept-vy" reproducerades inte i DOM och släpptes). Verkliga fynd
åtgärdade (AO1): fält under 16 px (sök 15, filter 13, "Lägg till vara" 15,
onboardingens budget 15 → 16 px på telefon, iOS zoomar inte längre in),
dagens ＋ 34 → 44 px, receptchipsen 32 → 44 px. Onboardingen på 375×667:
arket 400 px, "Hoppa över" inom skärmen, 24 px under den är safe-area —
inget klipps. Systemgränssnittet tvingas ljust (`UIUserInterfaceStyle`,
N1b). E2E `test_mobil_ergonomi.py` vaktar.

## 8. Integritet / native-arkivet

`PrivacyInfo.xcprivacy`: ingen spårning; Email, Coarse Location, Health
(allergier/kost), Product Interaction, Purchase History; API-skäl
UserDefaults + FileTimestamp. `NSLocationDefaultAccuracyReduced = true`
(N1b) gör "Hitta mig" till ungefärlig plats — etiketten (Coarse), noterna
("never asks for precise location") och koden säger samma sak. Pluginet
`@capgo/native-purchases` bär inget eget privacy-manifest (StoreKit kräver
inga required-reason-API:er). Kontoradering: Konto > Radera konto.
Kryptering: `ITSAppUsesNonExemptEncryption = false`.

## 9. Mergat sedan masterarbetsordern

32 PR:er mergade 2026-09-16 → 2026-09-19 (alla squash, grön CI, deployade):

- #195 (2026-09-16) docs: MATJAKT_MASTER_ROADMAP — varje krav avstämt mot koden
- #196 (2026-09-16) P03a: en receptsanning — reservbanken byggs ur källorna
- #197 (2026-09-16) P05a: ett kanoniskt ingredienslager — länken som saknades
- #199 (2026-09-16) P06a: paketorden blev enheter — och importen får inte acceptera en enhet prissättningen inte känner
- #200 (2026-09-16) P02b: Premium bärs av en källa med en giltighetstid - och Apple är en av dem
- #198 (2026-09-16) P02a: dagens iOS-köpflöde får inte skickas till App Review - och vägen som får det
- #201 (2026-09-16) P04a: receptidentiteten avgjord par för par — tio rätter under två id, och inget som får slås ihop av en siffra
- #204 (2026-09-16) P04b: ett recept-id är för alltid — tio gamla id blev alias, och favoriten från augusti öppnar fortfarande sin rätt
- #206 (2026-09-16) P02c: servern tar emot App Stores notiser - och verifierar dem i ren Python
- #203 (2026-09-16) P07a: matchningen förklarar sig — vilken regel, och hur säker
- #205 (2026-09-16) D11b: "aktivera allt" importerar alla släppta kedjor — ICA hoppades tyst över
- #209 (2026-09-16) P02e: reviewnoterna beskriver köpet i appen - IAP, 3.1.3(b), Återställ köp och en sandboxväg för granskaren
- #207 (2026-09-18) AM2: hyllorna hämtas en gång per start, hur många gånger vyn än ritas om
- #210 (2026-09-18) P05b: varje ingrediensrad ur API:t bär sitt kanoniska id
- #208 (2026-09-19) AM1: boot, inloggning och uppvaknande delar en spärr mot /api/entitlements
- #202 (2026-09-19) P09a: bildstatus — vad källan säger att fotot visar, per recept, med bevis
- #211 (2026-09-19) J3b: ingen automatisk trial - aktiveringstrialen borttagen, signalen kvar för hänvisningen
- #213 (2026-09-19) P02f: sandbox-köp godtas i produktion - verifierade, med produktallowlist
- #212 (2026-09-19) P02d: Premium köps med StoreKit i iOS-appen - bakom serverns flagga
- #217 (2026-09-19) T5: leveransen läses efter omritningen, inte efter klicket - och prisbilden i ett svep
- #216 (2026-09-19) P02g: reviewnoterna på engelska - det slutliga bygget, inget annat
- #214 (2026-09-19) AO1: mobil ergonomi - fält som inte får iOS att zooma, och tryckytor på 44 pt
- #219 (2026-09-19) AN1: receptbanken svarar 304 när klienten redan har den
- #215 (2026-09-19) P02h: IAP-flaggorna på i produktion - och sandbox godtaget för granskaren
- #224 (2026-09-19) N1b: releasebygge 2 - byggnummer och ljust systemgränssnitt
- #218 (2026-09-19) P05c: registrets namn når hyllan - kanoniska alias i prismatchningen
- #221 (2026-09-19) P09b: bildstatusen styr appen - fel foto visas inte, alt-texten är bevisets
- #220 (2026-09-19) I5b: App Store-copyn lovar inget iOS-pris
- #225 (2026-09-19) I5c: butiksbilderna följer dagens UI - 18 skärmbilder genererade
- #223 (2026-09-19) P09c: alt-texten i appen är bevisets, inte receptnamnets
- #226 (2026-09-19) AN2: reservbanken förhandscachas - recepten finns offline
- #222 (2026-09-19) T5b: en veckomutation tömmer hela prisbilden - även de låsta kedjorna

## 10. Öppna PR:er

Inga öppna PR:er utöver den här rapportens egen (BB). Kön var tom när bygget gjordes (main `40b715c`).

## 11. P0 REMAINING

Inget P0 återstår **i koden**. Det som återstår för inlämning är externt
(alla BLOCKED – ADAM nedan), och tre av dem är hårda stopp för App Review:

1. Prenumerationsprodukterna finns inte i App Store Connect (BLOCKED 1) —
   utan dem kan Premium inte köpas i bygget och köpknappen har inget att
   sälja.
2. IAP-flaggorna är inte satta på Render (BLOCKED 2) — bygget går då till
   Stripe-vägen, som inte får skickas till App Review (P02a).
3. App Review-kontakt + granskningskonto + App Privacy + Paid Apps Agreement
   (BLOCKED 3–5) — inlämningen avvisas av App Store Connect utan dem.

Därför är versionen **inte inskickad till App Review**: ordern tillät det
bara om alla release-gates var gröna, och de tre ovan är det inte.

## 12. P1 REMAINING

- Prisauditens estimat-rader (beslut om volymvikter, BLOCKED – ADAM 6).
- Hushållssynk/planeringsmotor/2.0-paket (ej påbörjade; roadmapen).
- `smakords_misstanke` (58) — heuristisk granskning av smaksatta produktnamn.

## 13. BLOCKED – ADAM

1. **Prenumerationsprodukterna i App Store Connect.**
   Vad: gruppen "Matjakt Premium" med `se.matjakt.premium.monthly` (1 månad)
   och `se.matjakt.premium.yearly` (1 år), svensk lokalisering, prispunkt
   (≈ 59 / 399 kr eller det du väljer), review-skärmdump, tillgänglighet.
   Var: App Store Connect → Apps → Matjakt → **Subscriptions**.
   Exakt klickväg: *Create Subscription Group* → namn "Matjakt Premium" →
   *Create Subscription* ×2 (Reference Name "Premium"/"Premium År",
   Product ID exakt som ovan, Duration 1 Month/1 Year) → *Subscription
   Prices* → *Localization* (sv) → *Review Information* (skärmdump av
   betalväggen) → spara.
   Varför: mitt API-anrop som skulle skapa dem nekades av Claude Codes
   auto-läge som "real-world transaction". Tillåter du den åtgärden
   (Bash-regel för `asc.py`) skapar jag dem på 30 sekunder.
2. **IAP-flaggorna på Render.** Vad: `MATJAKT_APPLE_IAP=1`,
   `MATJAKT_APPLE_IAP_ACCEPT_SANDBOX=1`, `MATJAKT_APPLE_APP_ID=6811440663`.
   Var: dashboard.render.com → **matjakt-backend** → *Environment* → *Add
   Environment Variable* → *Save* (tjänsten deployar om). Varför: P02h lade
   dem i `render.yaml`, men tjänsten är inte blueprint-synkad —
   `/api/health` säger fortfarande `appleIap.enabled=false`. Utan dem går
   iOS-bygget till Stripe-vägen (som inte får skickas till App Review).
3. **App Review-information.** Vad: kontaktperson (förnamn, efternamn,
   telefon, e-post) och ett granskningskonto (e-post + lösenord på ett
   Matjakt-konto). Var: App Store Connect → Matjakt → 1.0 → *App Review
   Information*. Varför: API:t kräver för- och efternamn + telefon som jag
   inte har, och kontouppgifter hör inte i repot eller chatten.
4. **App Privacy-svaren.** Var: App Store Connect → Matjakt → *App
   Privacy* → *Get Started*. Svaren står exakt i
   `ios-prep/APP_PRIVACY_LABEL.md` (Email, Coarse Location, Health, Product
   Interaction, Purchase History — inget tracking). Varför: inget API-stöd.
5. **Paid Apps Agreement + bank/skatt.** Var: App Store Connect →
   *Business* (Agreements, Tax, and Banking) → Paid Apps → godkänn, lägg in
   bank- och skatteuppgifter. Varför: krävs för att prenumerationer ska
   kunna säljas och för att inlämningen ska gå igenom; bara Account Holder
   kan skriva under.
6. **Volymvikterna (prisauditen).** Vad: besluta gram per msk för
   tomatpuré, sirap, currypasta, honung, sambal oelek (eller att de förblir
   estimat). Var: `docs/VOLYMVIKTER_ATT_GRANSKA.md` → beslut → paket P06b
   lägger in dem med källa och `test_verified_density.py`. Varför: grinden
   är röd enbart av dem; projektregeln är att inte gissa densiteter.
7. **App Store Server Notifications.** Var: App Store Connect → Matjakt →
   *App Information* → *App Store Server Notifications*: Production URL och
   Sandbox URL = `https://matjakt.onrender.com/api/billing/apple/notifications`,
   version 2. Varför: förnyelser/uppsägningar når servern utan att appen
   är öppen (appen återsynkar annars bara vid start).
8. **Sandbox-testare** (för din egen test): *Users and Access* → *Sandbox*
   → *Test Accounts* → ny adress → på telefonen Inställningar → App Store →
   Sandbox Account.
9. **Rollback-hemligheterna** `RENDER_API_KEY` + `RENDER_SERVICE_ID` (GitHub
   secrets) — rollback vid riktigt deployfel är annars manuell.
10. **VAPID-nycklar** (söndagsnotisen, H1): `npx web-push
    generate-vapid-keys` → Render-miljövariabler.
11. **Juridiska sakuppgifter** (från tidigare rapport): org.nr/adress i
    villkoren, DPA/SCC-underlag, support@matjakt.store, retention-beslut.
12. **Simulatorpanelen**: i Claude Code-appen, öppna simulatorpanelen och
    tryck "Let Claude use it" — då kan jag köra hela TestFlight-checklistan
    (signup, vecka, IAP-sandbox) i simulatorn utan att du gör något mer.

## 14. Vad Apple gör nu

Ingenting väntar hos Apple just nu:

- **TestFlight (intern):** bygget är klart att installera för interna testare
  (Adams team) — ingen granskning krävs. Sandbox-prenumerationer renews i
  accelererad takt.
- **Beta App Review (extern):** inte begärd (se ovan). När IAP-flaggorna och
  produkterna finns skickas bygget till Beta App Review; Apple svarar
  normalt inom 1–2 dygn.
- **App Review:** inte begärd. När BLOCKED 1–5 är lösta är versionen
  förberedd: build 2 kopplad, metadata, skärmbilder, åldersgräns, kategori,
  reviewnoter på engelska, manual release. Ett tryck på *Add for Review* →
  *Submit to App Review* återstår — och efter godkännande släpps den
  **manuellt** (releaseType MANUAL), aldrig automatiskt till alla.

## 15. Simulatorkontroll av releasecommiten

Samma commit (`40b715c`, samma webbundle som arkivet) byggd för iPhone 16e
(iOS-simulator), **färsk installation**: appen startar, onboardingens
ark "Vilka är ni hemma?" ligger över Ikväll, gränssnittet är ljust
(statusfält, tangentbord), appen når produktionsbackenden. Inga fel i
processloggen utöver simulatorns vanliga Security/BoardServices-brus.
Tryckgenomgången (signup, vecka, byten, Handla, IAP-sandbox) gick inte att
köra härifrån: Claude Codes simulatorpanel kräver ditt godkännande ("Let
Claude use it") — BLOCKED – ADAM 12. Ett kosmetiskt fynd att ta i AO2:
rubriken i onboardingens ark får en synlig fokusram (`outline`) när arket
sätter fokus på den.

## 16–20. Övrigt

- **Deploy**: ingen manuell Render-deploy gjordes; hooken + hälsogrinden
  har tagit varje merge. Rollback inte utlöst (inga deployfel).
- **Flaken "första veckan utan betalvägg"**: rotorsaken var två — E2E:n
  läste DOM:en i glappet före omritningen (T5, Adams session) och
  produkten lämnade förra svarets låsta kedjor kvar när prisbilden tömdes
  (T5b). Båda mergade; ingen rerun har dolt den.
- **Ingen 2.0-funktion** har rörts (ordern: inget får riskera releasebygget).
- Skärmbilderna är genererade ur fixturdata (butiksnamn och priser
  syntetiska men verkliga i form); inför inlämningen kan de göras om mot
  produktion med `--base https://matjakt.onrender.com --login …`.
