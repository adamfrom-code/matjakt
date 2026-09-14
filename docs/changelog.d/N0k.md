---
paket: N0k
titel: Privacy-manifestet deklarerade en plats appen aldrig sparat — och tog inte upp hälsodata
---

Apple läser tre dokument om samma sak och jämför dem med varandra:
`PrivacyInfo.xcprivacy` i bundlen, App Privacy-etiketten i App Store
Connect och integritetspolicyn som `privacy_url.txt` pekar på. En
motsägelse mellan dem är inte ett skrivfel — det är en anledning till
avslag, och den upptäcks efter att arkivet redan är uppladdat. Manifestet
hade två.

## Exakt plats deklarerades som insamlad och kopplad till användaren

Manifestet bar `NSPrivacyCollectedDataTypePreciseLocation` med
`NSPrivacyCollectedDataTypeLinked = true`, och kommentaren överst sa att
platsen "sparas i profilen som lat/lon för butiksval (kopplad till kontot
när man är inloggad)".

Den sparas inte alls. `state.position` sätts av "Hitta mig"
(`app.js:2903`) och av geokodningen av postnumret (`:2886`), men `position`
ingår inte i `buildSyncPayload()` — och det är den payloaden, och bara den,
som `persistLocally()` skriver till localStorage och som POSTas till
`/api/account/state`. `users` har ingen lat/lon-kolumn. Avståndsräkningen
sker i klienten (`app.js:1038`): servern skickar butikernas koordinater
till enheten, aldrig tvärtom.

Apples definition av "collect" avgör saken, och den är snävare än ordet
låter: *"transmitting data off the device in a way that allows you and/or
your third-party partners to access it for a period longer than what is
necessary to service the transmitted request in real time."* Data som
stannar på enheten samlas inte in. Deklarationen påstod alltså en
insamling som inte sker — och en etikett som **överdriver** insamlingen är
lika oriktig som en som underdriver den. Den motsade dessutom policyns egen
mening om att koordinaterna stannar i appens minne.

Det som faktiskt lagras är postnumret, i `users.synced_state`. Fem siffror
beskriver var någon bor med lägre upplösning än lat/lon med tre decimaler,
vilket är precis Apples gräns mellan Precise och Coarse. Exakt plats är
alltså borta; `NSPrivacyCollectedDataTypeCoarseLocation` är på plats.

## Två uppgifter appen behandlar saknades helt

**Hälsa.** Allergier och kosttyp lämnar enheten på två vägar: kontots synk
(`kost.avoidAllergens` och `kost.kosttyp` i payloaden, vidare till
`users.synced_state`) och hushållsprofilen, där `allergies` delas med
familjen. Integritetspolicyn behandlar dem som uppgifter enligt artikel 9 i
dataskyddsförordningen, med uttryckligt samtycke. En etikett utan hälsodata
motsade alltså appens egen policy. `NSPrivacyCollectedDataTypeHealth`,
kopplad till användaren.

**Produktinteraktion.** `analytics_user_days` räknar 29 namngivna händelser
per konto och dag, och `trackEvent()` skickar sessionens token med varje
händelse när någon är inloggad. Ändamålet är **Analytics**, inte App
Functionality: tabellen finns för att besvara om någon kommer tillbaka
vecka två, inte för att appen ska fungera.

Ingen av de fem deklarationerna är spårning. Appen har inga
tredjeparts-SDK:er, inget annonsnätverk och ingen reklam;
`NSPrivacyTracking` är kvar på `false` och ingen ATT-dialog behövs.

## Två filer, inte en

`scripts/ios_mac_pass.sh:184` kopierar `ios-prep/PrivacyInfo.xcprivacy`
över `ios/App/App/PrivacyInfo.xcprivacy` vid varje Mac-pass. Rättas bara
den ena är rättelsen borta nästa gång skriptet körs — tyst, för
kopieringen lyckas. Båda är ändrade, och testet jämför dem.

## Etiketten finns inte i repot, så svaren skrevs ner

App Privacy-etiketten fylls i för hand i App Store Connect. Steg 5 i
`docs/IOS_RELEASE.md` sa "samma innehåll som PrivacyInfo.xcprivacy: e-post,
plats, köphistorik" — vilket nu är fel på tre av tre punkter. Svaren står i
stället i `ios-prep/APP_PRIVACY_LABEL.md`, med skälet till varje ruta och
till varför Precise Location inte ska kryssas.

## Acceptanstestet

`backend/tests/test_ios_privacy_manifest.py` bygger på samma regel som
`test_juridiska_sidorna.py::PlatsenBeskrivsSomKodenFaktisktGor`:
**deklarerar manifestet att en uppgift samlas in, ska det gå att peka ut
var den lagras.** `BEVIS` är den tabellen — datatyp, fil, en textbit ur
källan och vad raden bevisar — och den prövas åt båda hållen. En
deklaration utan bevis failar; ett bevis utan deklaration failar; ett bevis
vars textbit försvunnit ur källan failar.

De kodfakta som *tvingar* fram en deklaration prövas separat: att
`position` inte ligger i synkpayloaden och att `users` saknar lat/lon-kolumn
(annars ska exakt plats tillbaka), att postnumret ligger kvar i payloaden,
att kosten gör det, och att mätningen fortfarande skriver `user_id`.
Datatyper och ändamål jämförs mot Apples egna listor, eftersom Xcode inte
genererar någon privacy-rapport alls om ett egenpåhittat värde smyger in —
och det märks först när arkivet är byggt.

Nio av sjutton prov faller på manifestet som stod där innan. Fyra
muteringar prövades efteråt: bara ena filen rättad (9 röda), `position`
insmugen i payloaden (1), hälsodeklarationen borttagen (3) och mätningen
avkopplad från kontot (2).
