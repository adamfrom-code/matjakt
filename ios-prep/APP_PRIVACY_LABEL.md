# App Privacy-etiketten — svaren som ska skrivas in i App Store Connect

App Privacy-etiketten fylls i för hand under **App Store Connect → appen →
App Privacy**. Den finns alltså inte i repot, och därför driver den isär
från `PrivacyInfo.xcprivacy` så fort någon rör det ena utan att röra det
andra. Den här filen är svaren, och
`backend/tests/test_ios_privacy_manifest.py` håller den mot manifestet.

**Apple jämför tre dokument med varandra:** manifestet i bundlen, den här
etiketten och integritetspolicyn på `matjakt.store`. En motsägelse mellan
dem är en anledning till avslag — och den upptäcks efter att arkivet
laddats upp.

## Första frågan: Do you or your third-party partners collect data?

**Ja.** Fem uppgifter, alla kopplade till användaren, ingen för spårning.

`NSPrivacyTracking = false`, `NSPrivacyTrackingDomains` tomt: appen har
inga tredjeparts-SDK:er, inget annonsnätverk och ingen reklam. Ingen
ATT-dialog (AppTrackingTransparency) behövs, och ingen uppgift får kryssas
som "Used for Tracking".

## Data Linked to You

| Kategori i ASC | Uppgift | Ändamål (Purposes) | Vad det är i koden |
|---|---|---|---|
| Contact Info | **Email Address**<br>`NSPrivacyCollectedDataTypeEmailAddress` | App Functionality | `users.email` — kontots inloggning |
| Location | **Coarse Location**<br>`NSPrivacyCollectedDataTypeCoarseLocation` | App Functionality | Postnumret, i `users.synced_state` |
| Health & Fitness | **Health**<br>`NSPrivacyCollectedDataTypeHealth` | App Functionality | Allergier och kosttyp, i `users.synced_state` och i hushållsprofilen |
| Usage Data | **Product Interaction**<br>`NSPrivacyCollectedDataTypeProductInteraction` | **Analytics** | `analytics_user_days` — konto × dag × händelse |
| Purchases | **Purchase History**<br>`NSPrivacyCollectedDataTypePurchaseHistory` | App Functionality | Premium-plan och prenumerationsstatus på kontoraden |

## Data Not Collected — och varför

**Precise Location.** Kryssa den INTE. "Hitta mig" läser koordinater, men
de lämnar aldrig enheten: `state.position` ingår inte i
`buildSyncPayload()`, skrivs inte till localStorage, POSTas inte till
`/api/account/state`, och `users` har ingen lat/lon-kolumn. Avståndet till
butikerna räknas i klienten — servern skickar butikernas koordinater till
enheten, aldrig tvärtom.

Apples definition avgör saken:

> "Collect" refers to transmitting data off the device in a way that allows
> you and/or your third-party partners to access it for a period longer
> than what is necessary to service the transmitted request in real time.
>
> — [App privacy details on the App Store](https://developer.apple.com/app-store/app-privacy-details/)

Data som stannar på enheten samlas inte in. Att ändå kryssa exakt plats
vore att påstå en insamling som inte sker, och etiketten hade då motsagt
integritetspolicyn, som säger att koordinaterna stannar i appens minne.
Fram till N0k deklarerade manifestet exakt plats som kopplad till
användaren; det var fel.

**Varför postnumret ändå är Coarse Location.** Postnumret skickas till
servern och blir kvar i `users.synced_state`. Fem siffror beskriver var
någon bor med *lägre* upplösning än lat/lon med tre decimaler, vilket är
precis Apples gräns mellan Precise och Coarse.

**Varför ändamålet för produktinteraktion är Analytics.**
`analytics_user_days` finns för att besvara om någon kommer tillbaka vecka
två — inte för att appen ska fungera. App Functionality hade varit fel
ruta. Tabellen lagrar konto, dag och händelsenamn ur en fast lista; aldrig
klockslag, aldrig IP, aldrig fritext.

**Varför hälsodata är kryssad.** Allergier och kosttyp lämnar enheten på
två vägar: kontots synk och hushållsprofilen, som delar dem med familjen.
Integritetspolicyn behandlar dem som uppgifter enligt artikel 9 i
dataskyddsförordningen, med uttryckligt samtycke. En etikett utan hälsodata
hade motsagt appens egen policy.

## När det här ändras

Ändras manifestet ska den här filen ändras i samma PR — testet failar
annars. Ändras något av dem efter att appen är inlämnad måste svaren
uppdateras i App Store Connect också; det kräver ingen ny version av appen.
