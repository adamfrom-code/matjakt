# iOS / App Store – vad som är gjort på Windows och vad som kräver Mac

*2026-09-03. Ingen `ios/`-katalog finns ännu: `npx cap add ios` kräver macOS + Xcode.*

## Gjort på Windows (i repo)

| Punkt | Status | Var |
|---|---|---|
| `@capacitor/ios` installerad (8.5.1, matchar core 8.5.0) | ✅ | `package.json` |
| iOS-sektion i Capacitor-konfigen (contentInset, bakgrund, scheme) | ✅ | `capacitor.config.json` |
| Info.plist-nycklar (plats-behörighet, ej-exempt-kryptering, stående läge, sv) | ✅ förberett | `ios-prep/Info.plist.additions.xml` |
| Privacy manifest | ✅ förberett | `ios-prep/PrivacyInfo.xcprivacy` |
| Ikon-/splashkällor för `@capacitor/assets` (1024², 2732²) | ✅ genererade från 512-ikonen | `resources/` (se not om vektorkälla nedan) |
| Android-paritet: plats-behörighet i manifestet | ✅ | `android/app/src/main/AndroidManifest.xml` |
| CORS för native-webview (`capacitor://localhost`) | ✅ i `render.yaml`; **sätt även i Render-dashboarden** (env `MATJAKT_FRONTEND_ORIGIN`) | `render.yaml` |

## Kräver Mac + Apple Developer-konto (99 USD/år)

1. `npx cap add ios && npx cap sync ios` – skapar `ios/App`.
2. Lägg in `ios-prep/`-filerna: nycklarna i `ios/App/App/Info.plist`, `PrivacyInfo.xcprivacy` i `ios/App/App/` (lägg till i target i Xcode).
3. `npx @capacitor/assets generate --ios` (källor i `resources/`).
4. Xcode: Team + signering, `MARKETING_VERSION 1.0`, `CURRENT_PROJECT_VERSION 1`, Bundle ID `se.matjakt.app`.
5. App Store Connect: skapa appen, fyll i sekretessetiketter (samma innehåll som PrivacyInfo.xcprivacy: e-post, plats, köphistorik – inga spårningsändamål).
6. Archive → TestFlight → intern testning.

## Blockerare före App Store (inte TestFlight)

**Betalning.** Premium säljs i dag via Stripe Checkout som öppnas i webviewen. Apple 3.1.1 kräver In-App Purchase för digitala prenumerationer som köps i appen. Två vägar, Adam väljer:

| Väg | Vad det innebär | Arbete |
|---|---|---|
| **A. v1 utan köp i appen** (rekommenderas för TestFlight/första release) | iOS-appen visar Free + låser upp Premium för konton som redan har det (köpt på matjakt.store). Ingen "köp"-knapp, ingen länk till Stripe i native-bygget (`Capacitor.isNativePlatform()` döljer paywall-CTA:n). Tillåtet enligt 3.1.3(b) så länge appen inte pekar användaren till externt köp. | Liten frontend-ändring |
| **B. StoreKit 2 + App Store Server API** | Produkter `se.matjakt.premium.monthly`/`yearly` i ASC, kvitto-/JWS-verifiering i backend (`services/billing/apple_client.py`: ES256-verifiering kräver kryptobibliotek – bryter stdlib-only-mönstret eller kräver egen P-256-implementation), webhook för App Store Server Notifications, entitlement-sammanslagning Stripe/Apple. | Flera dagar + Mac för test |

**Juridik.** Platshållare måste fyllas i innan inlämning:
- `frontend/integritetspolicy.html:31` – `[FÖRETAGSNAMN / DITT NAMN]`, `[ORGANISATIONSNUMMER]`
- `frontend/anvandarvillkor.html:31` – samma; `:45` – `[ÅNGERRÄTT …]`
- Sidorna ligger utanför `webDir` (`frontend/app`) och länkas relativt (`../integritetspolicy.html`) ⇒ 404 i native-appen. Kopiera dem in i `frontend/app/` eller länka absolut till `https://matjakt.store/…`.

**Native-drift.**
- `<meta name="matjakt-api-url">` i `frontend/app/index.html` är tom ⇒ sätt `https://matjakt.onrender.com` före `cap sync` (webben körs same-origin, appen inte).
- Utvecklingslåset är avvecklat (2026-09-06): servern svarar `gate: false` och native-origin `capacitor://localhost` är CORS-betrodd - appen behöver ingen låsinloggning.
- Typsnitten laddas från fonts.googleapis.com; bunta Bricolage Grotesque/Manrope lokalt så första start fungerar offline och CSP kan stängas ytterligare.

## Ikoner – not om källa

`frontend/app/assets/icons/icon-512.png` är enda rastret (ingen SVG). `resources/icon-only.png` (1024²) är uppskalat 2× med Lanczos – acceptabelt för en platt "M."-ikon, men en vektor-/1024-källa från designen är bättre före App Store. `resources/splash.png` är bakgrund `#f6f7f4` med ikonen centrerad.

## Metadata (förslag, sv-SE)

- Namn: **Matjakt** · Undertitel: *Din smarta matvecka*
- Nyckelord: matbudget, veckomeny, inköpslista, matpriser, recept, Willys, Hemköp, City Gross (kontrollera varumärkesregler)
- Support-URL: `https://matjakt.store` · Integritetspolicy-URL: `https://matjakt.store/integritetspolicy.html`
- Beskrivning: utgå från `package.json` description + Free/Premium-matrisen i `backend/services/accounts/features.py` – lova inga butiker som inte är släppta (ICA/Coop/Lidl är gated).
- Skärmbilder: 6,7" (iPhone 15 Pro Max) och 6,5" krävs; ta dem i simulatorn på Mac från Hem, Recept, Handla (butiksjämförelse) och Justera veckan.

## Gjort 2026-09-06 (release-finish)

| Punkt | Status | Var |
|---|---|---|
| App Store-metadata på svenska (namn, undertitel, beskrivning, nyckelord, kampanjtext, support-/integritets-URL) | ✅ klara att klistra in | `store/appstore/metadata/sv-SE/` |
| Notes for App Review (inloggning, betalning, plats, kontoradering) | ✅ mall - Adam fyller i testkonto | `store/appstore/metadata/review_notes.txt` |
| Juridiklänkar absoluta (`https://matjakt.store/...`) så de fungerar i native-webviewen | ✅ | `frontend/app/index.html` |
| Kontoradering inifrån appen (Apple 5.1.1(v)) | ✅ finns: Konto → Radera konto, avslutar även Stripe-prenumerationen först | `api_server.py` `/api/auth/delete-account` |
| Sign in with Apple | ej krav: appen har bara e-post + lösenord, ingen tredjepartsinloggning (riktlinje 4.8 gäller bara när tredjepartsinloggning erbjuds) | – |
| Browser-E2E av hela konsumentresan i mobil viewport (390×844, touch) | ✅ `backend/tests/e2e/` | CI-jobb `e2e` |

Kvar (kräver Mac/Adam): `npx cap add ios`, signering, skärmbilder, IAP-beslut (väg A rekommenderas för v1), juridiska platshållare i policy/villkor.

## Native-pass 2026-09-06 (Windows) - vad som nu är gjort i repo

| Punkt | Status | Var |
|---|---|---|
| Native-bygge: `npm run build:native` → `dist/native` med `https://matjakt.onrender.com/api` i metataggen och utan landningens statistikskript | ✅ testat (`tests/build-native.test.js`) | `scripts/build_frontend.mjs` |
| `webDir` pekar på bygget (`dist/native/app`), inte källorna | ✅ | `capacitor.config.json` |
| `@capacitor/app` (appStateChange, appUrlOpen) och `@capacitor/browser` (Stripe i SFSafariViewController) | ✅ installerade, används bara när `Capacitor.isNativePlatform()` | `package.json`, `frontend/app/app.js` |
| Stripe-checkout/portal i native öppnas externt; Premium pollas när appen blir aktiv igen (en poll åt gången); `flushServerSync()` före | ✅ | `frontend/app/app.js` (`openExternal`, `onAppResumed`) |
| Djuplänkar i native: `appUrlOpen` laddar om appen med query-strängen (`?verify`/`?reset`/`?invite`/`?recept`) så webbens startkod tar hand om den | ✅ kod; **kräver Associated Domains (Mac + Team-ID)** | `frontend/app/app.js` |
| Utvecklingslåset borta, `capacitor://localhost` CORS-testat mot alla konsument-, konto- och hushållsvägar | ✅ | `backend/tests/test_api_server.py` `CorsForNativeTest` |
| Livepriser: max ett anrop per filial, stopp vid 429 - ingen anropsstorm från appen | ✅ E2E räknar anrop | `backend/tests/e2e/test_consumer_journey.py` |

### Exakt på Macen (i den här ordningen)

```bash
git pull
npm ci
npm run build:native          # dist/native - bygget som paketeras
npx cap add ios               # bara första gången: skapar ios/App
npx cap sync ios              # kopierar dist/native/app + plugin-pods (App, Browser)
npx @capacitor/assets generate --ios     # ikon + splash från resources/
npx cap open ios              # Xcode
```

I Xcode (första gången):
1. Target App → Signing & Capabilities: Team (Apple-ID räcker för simulatorn - ingen betald medlemskap krävs), Bundle Identifier `se.matjakt.app`.
2. Info-fliken: klistra in nycklarna från `ios-prep/Info.plist.additions.xml` (plats-text, endast stående läge, svenska, ingen egen kryptering).
3. Lägg `ios-prep/PrivacyInfo.xcprivacy` i `ios/App/App/` och bocka i target App.
4. Product → Destination → iPhone 15 Pro (simulator) → Run. Eller från terminalen: `npx cap run ios` (väljer simulator interaktivt).

Simulatorkontroller (E2E för hand, ta skärmbilder till `store/appstore/screenshots/`):
- Kallstart: ingen vit skärm, Hem-skärmen med onboarding.
- Onboarding → Gävle-postnummer → butiker → vecka → Handla: "Har hemma"/"Köpt"/Ångra.
- Konto: registrera, verifiera (mejlet öppnar `matjakt.store/app/?verify=` i Safari - fungerar utan Associated Domains), logga in i appen.
- Hushåll: skapa, bjud in (dela-arket), gå med från en andra simulator/telefon, delad lista.
- Premium: knappen öppnar Stripe (TEST) i SFSafariViewController; tillbaka i appen → Premium aktiverat inom 30 s.
- Flygplansläge: ingen vit skärm, ingen utloggning, "pris saknas just nu" i stället för evig "hämtas…".
- Safe areas (notch, hemindikator), tangentbordet skjuter inte bort inmatningsfältet, endast stående läge, statusfältet läsbart.

### Universella länkar (djuplänkar direkt in i native-appen) - kräver Adam

Utan detta öppnas mejl- och inbjudningslänkar i Safari (webbappen) - det fungerar, men inte inne i native-appen.
1. Xcode → Signing & Capabilities → + Associated Domains → `applinks:matjakt.store`.
2. Lägg `frontend/.well-known/apple-app-site-association` (JSON utan filändelse) med `"appID": "<TEAMID>.se.matjakt.app"` och `"paths": ["/app/*"]`; verifiera att GitHub Pages serverar den som `application/json` (annars via backend-proxy).
3. Testa: `xcrun simctl openurl booted "https://matjakt.store/app/?recept=<id>"` - appen ska öppna receptet.

