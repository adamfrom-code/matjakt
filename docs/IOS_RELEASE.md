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
- Utvecklingslåset (`GATE_ENABLED` på Render): antingen av vid release, eller dokumentera gate-inloggning för App Review i "Notes for reviewer".
- Typsnitten laddas från fonts.googleapis.com; bunta Bricolage Grotesque/Manrope lokalt så första start fungerar offline och CSP kan stängas ytterligare.

## Ikoner – not om källa

`frontend/app/assets/icons/icon-512.png` är enda rastret (ingen SVG). `resources/icon-only.png` (1024²) är uppskalat 2× med Lanczos – acceptabelt för en platt "M."-ikon, men en vektor-/1024-källa från designen är bättre före App Store. `resources/splash.png` är bakgrund `#f6f7f4` med ikonen centrerad.

## Metadata (förslag, sv-SE)

- Namn: **Matjakt** · Undertitel: *Din smarta matvecka*
- Nyckelord: matbudget, veckomeny, inköpslista, matpriser, recept, Willys, Hemköp, City Gross (kontrollera varumärkesregler)
- Support-URL: `https://matjakt.store` · Integritetspolicy-URL: `https://matjakt.store/integritetspolicy.html`
- Beskrivning: utgå från `package.json` description + Free/Premium-matrisen i `backend/services/accounts/features.py` – lova inga butiker som inte är släppta (ICA/Coop/Lidl är gated).
- Skärmbilder: 6,7" (iPhone 15 Pro Max) och 6,5" krävs; ta dem i simulatorn på Mac från Hem, Recept, Handla (butiksjämförelse) och Justera veckan.
