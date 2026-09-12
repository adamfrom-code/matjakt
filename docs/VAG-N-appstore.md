# Våg N — appen till App Store

Zon: `Z-NATIVE`. Ett paket i taget, samma regler som väg A–M.

## 0. Beslutet som styr vågen

**TestFlight intern testning kräver ingen App Review.** Det är hela
anledningen till att den här vågen går att köra nu. Köpflödet får ligga
kvar precis som det är — Stripe i en webbvy är förbjudet i App Store, men
inte i intern TestFlight-distribution.

Paket **N1** — plocka bort köpflödet ur native-bygget — gäller först när
vi går mot skarp inlämning. Det är inte ett förarbete, det är ett arbete
som ska göras *efter* att appen har legat i händerna på en intern testare.

**Skärmbilderna körs inte om än.** De ska visa design D efter väg L, och
L1–L5 är inte klara. TestFlight behöver inga skärmbilder.

## 1. Förutsättningarna (N0)

Fyra saker som måste vara på plats innan ett arkiv är värt att ladda upp.
De hittades inte på en checklista utan genom att bygga arkivet en gång och
titta i det.

| Paket | Vad | Varför |
|---|---|---|
| **N0a** | Juridiklänkarna når fram | Integritetspolicy och användarvillkor måste gå att öppna *inifrån* appen. En `target="_blank"` som inte gör någonting är samma sak som en länk som inte finns. |
| **N0b** | Typsnitten buntade lokalt | Newsreader och Archivo hämtades från Google Fonts. En app som startar utan nät ska inte tappa sin typografi, och CSP:n blir stramare när det externa ursprunget kan strykas. |
| **N0c** | `ios-prep`-nycklarna in i bygget | `CFBundleDisplayName`, `NSLocationWhenInUseUsageDescription`, `ITSAppUsesNonExemptEncryption`, språk, orientering och URL-schemat `matjakt`. Utan encryption-nyckeln stannar varje uppladdning och frågar. |
| **N0d** | Kontrollrummet stannar utanför | Första arkivet innehöll `admin.html` och `admin.js`. Ingen säkerhetslucka — grinden ligger på servern — men en driftsinloggning i en matbudgetapp är en fråga vi inte vill svara på. |
| **N0e** | Appikonen är Matjakts | `npx cap add ios` lägger in Capacitors egen blå logotyp. Den följer med hela vägen till hemskärmen om ingen byter ut den. |

## 2. Bygget

Verifierat mot maskinen, inte mot dokumentation: **Xcode 26.3 (17C529)**.
Flaggorna nedan finns i `xcodebuild -help` på just den versionen. De ändras
mellan versioner — kontrollera om om Xcode uppdateras.

```
npm run build:native                      # dist/native/app
npx cap sync ios                          # skriver config.xml + capacitor.config.json
npx @capacitor/assets generate --ios      # ikon och startskärm ur resources/
```

`npx cap sync ios` är det enda som skriver `config.xml` och
`capacitor.config.json` in i `ios/App/App/`. En filkopia till `public/`
räcker inte — det var det som fällde det första arkivförsöket med exit 65.

Versionerna: `MARKETING_VERSION = 1.0`, `CURRENT_PROJECT_VERSION = 1`.

```
xcodebuild -workspace ios/App/App.xcworkspace -scheme App \
  -configuration Release -destination generic/platform=iOS \
  -archivePath build/Matjakt.xcarchive archive \
  -allowProvisioningUpdates \
  -authenticationKeyPath <.p8> -authenticationKeyID <id> -authenticationKeyIssuerID <issuer>

xcodebuild -exportArchive -archivePath build/Matjakt.xcarchive \
  -exportOptionsPlist build/ExportOptions.plist -exportPath build/export \
  -allowProvisioningUpdates \
  -authenticationKeyPath <.p8> -authenticationKeyID <id> -authenticationKeyIssuerID <issuer>
```

`ExportOptions.plist` sätter `method = app-store-connect`,
`destination = upload` och `signingStyle = automatic`. Med `destination =
upload` laddar `-exportArchive` upp direkt; ingen `.ipa` behöver skickas
vidare för hand.

## 3. Hemligheterna

Adam skapar appposten i App Store Connect med bundle-ID **`se.matjakt.app`**,
genererar en API-nyckel med rollen **App Manager**, och loggar in med sitt
Apple-ID i Xcode.

Tre värden behövs vid bygget: **Issuer ID**, **Key ID** och **`.p8`-filen**.

De är hemligheter. De committas aldrig, de klistras aldrig in i en chatt,
och `.p8`-filen ligger utanför repot. `.gitignore` ska hålla `*.p8` ute
oavsett var någon råkar spara den.

## 4. Kvar efter TestFlight

- **N1** — köpflödet ut ur native-bygget, inför skarp inlämning.
- **Skärmbilderna** — efter L1–L5, i design D.
- **Granskningskontot** — platshållarna i `store/appstore/metadata/review_notes.txt`
  är fortfarande platshållare.
