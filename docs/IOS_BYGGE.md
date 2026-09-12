# iOS: från klon till TestFlight

Projektet ligger i `ios/App/App.xcodeproj` och använder **Swift Package
Manager** — inga CocoaPods behövs (Capacitor 8).

## Varje gång, innan du bygger

```bash
npm run ios:sync
```

Det gör två saker: bygger frontend till `dist/native/` med produktionens
API-adress inkodad och utan statistikskriptet, och kopierar bygget till
`ios/App/App/public/`.

**Hoppar du över steget paketeras gamla webbresurser** — eller inga alls i en
färsk klon, eftersom `public/` är gitignorerad byggutdata.

## Bygga och köra i simulatorn

```bash
xcrun simctl boot "iPhone 17 Pro"
open ios/App/App.xcodeproj
```

Eller från terminalen:

```bash
cd ios/App
xcodebuild -project App.xcodeproj -scheme App -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
```

Simulatorbygget kräver **ingen** signering.

## TestFlight

Signeringen är `Automatic` men `DEVELOPMENT_TEAM` är **osatt** — den fylls i
en gång i Xcode (Signing & Capabilities → Team) och sparas i projektfilen.

1. Öppna `ios/App/App.xcodeproj`, välj **Any iOS Device** som mål
2. Signing & Capabilities → välj team
3. Product → Archive
4. Distribute App → TestFlight & App Store

## Identiteterna, och vad som går att ändra

| | Värde | Ändringsbart |
|---|---|---|
| Bundle-id | `se.matjakt.app` | **Nej.** Registrerat i App Store Connect, låst för alltid |
| Namn under ikonen | `Matjakt` | Ja — `appName` i `capacitor.config.json`, syncas in |
| App Store-titel | `Matjakt: matbudget & veckomeny` | Ja, till publicering — `store/appstore/metadata/sv-SE/name.txt` |

Xcode förifyller fältet `Name` i "Create App on App Store Connect" med
**target-namnet**, som Capacitor kallar `App`. Det är fel — fältet är appens
namn i App Store, och "App" är upptaget. Skriv in titeln ovan.

## Kvar innan granskning

`store/appstore/metadata/review_notes.txt` har två platshållare för
granskningskontots e-post och lösenord. **Apple behöver ett konto som kan
logga in och se Premium**, annars avvisas granskningen utan att appen
provas. Lösenordet hör hemma i filen — repot är publikt, så det ska vara ett
konto som bara finns för granskning.

Skärmbilderna genereras av `backend/scripts/make_store_screenshots.py` och
bör köras om när våg L är klar — appen byter utseende under tiden, och en
skärmbild tagen i går är fel i morgon.

## Varför projektet inte fanns förut

`ios/App/App/` innehöll `capacitor.config.json`, `config.xml` och `public/`
— alltså exakt de filer `cap sync` *kopierar in*, men ingen `.xcodeproj`.
Någon hade tagit genvägen att kopiera webbresurser till en katalog som såg
ut som ett iOS-projekt. Det upptäcktes först när appen skulle till
TestFlight.

`backend/tests/test_ios_projektet.py` vaktar att det inte händer igen:
projektfilen finns, bundle-id stämmer mot det registrerade, och byggutdata
är inte spårad.
