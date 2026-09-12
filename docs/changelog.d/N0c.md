---
paket: N0c
titel: ios-prep-nycklarna in i bygget
---

`ios-prep/` bar sedan 3 september en färdig lista över Info.plist-nycklar och
ett `PrivacyInfo.xcprivacy`, med kommentaren *"Förberett på Windows; kan inte
verifieras utan Xcode."* De låg alltså rätt — men utanför bygget, eftersom
det inte fanns något iOS-projekt att lägga dem i.

N1 genererade projektet. N0c applicerar nycklarna och **verifierar dem mot
den byggda appen**, inte mot källan:

```
PrivacyInfo.xcprivacy                  MED i Resources
CFBundleDisplayName                    Matjakt
CFBundleShortVersionString             1.0
CFBundleVersion                        1
CFBundleDevelopmentRegion              sv
NSLocationWhenInUseUsageDescription    ...hitta matbutiker nära dig
ITSAppUsesNonExemptEncryption          false
URL-schema                             matjakt://
orientering                            Portrait
```

**Två av nycklarna är inte kosmetik.** Utan
`NSLocationWhenInUseUsageDescription` **kraschar appen** i samma stund
användaren trycker "Hitta mig" — iOS avslutar processen när ett
behörighetsanrop saknar sin förklaringstext. Och App Store avvisar
inlämningar utan privacy-manifest sedan våren 2024.

Manifestet lades i targetets Resources med repots eget
`scripts/ios_pbxproj_add_file.mjs`. **En fil som bara ligger på disk hamnar
aldrig i app-bundlen** — den måste stå i `project.pbxproj`.

`backend/tests/test_ios_nycklarna.py` (10) håller dem kvar. `npx cap sync ios`
rör inte Info.plist, men `npx cap add ios` genererar den på nytt, och då
försvinner varje nyckel som inte står i Capacitors mall.

**En sak bygget lärde oss:** en kopiering av `dist/native/app/` till
`ios/App/App/public/` räcker inte. Xcode kräver också `config.xml` och
`capacitor.config.json`, som bara `npx cap sync ios` skriver. Bygget failade
på exakt det tills syncen kördes riktigt — vilket är varför `npm run
ios:sync` finns och står som första steg i `docs/IOS_BYGGE.md`.
