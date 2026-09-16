# Premium i iOS-appen: Apples regler, dagens flöde och vald arkitektur

Paket P02a. Läst mot Apples publicerade text **2026-09-16**. Allt engelskt
i citattecken nedan är ordagrant från Apple; det svenska runt omkring är vår
tolkning. Dokumentet är beslutsunderlaget för P02b–P02d och listan över vad
bara Adam kan göra. Den listan står sist, under **BLOCKED – ADAM**.

Kort version: **dagens iOS-flöde får inte skickas till App Review.** Appen
visar en knapp "Prenumerera" som öppnar Stripe Checkout i
SFSafariViewController för att låsa upp digitala funktioner. Det är exakt
det 3.1.1 förbjuder, och undantagen (US-storefront, EU-alternativen,
reader-appar) gäller inte oss. Vägen framåt är StoreKit 2 i appen, Stripe
på webben, och **en** entitlement-sanning på servern som vet varifrån
Premium kommer och hur länge det gäller.

Ett fynd på vägen som är ett **produktbeslut**, inte ett tekniskt: koden
ger sju dagars Premium efter kontots första skapade vecka (J3,
`backend/services/billing/activation.py`), medan affärsbeslutet lyder
"59/399, ingen automatisk trial". Se A6 och BLOCKED – ADAM 10.
Entitlement-modellen (P02b) bär provperioden som en egen källa med
slutdatum, så beslutet kan tas åt vilket håll som helst utan omskrivning.

---

## (a) Vad Apples regler säger i dag

Källa: App Store Review Guidelines,
<https://developer.apple.com/app-store/review/guidelines/>, hämtad
2026-09-16. Sidan bär inget eget datum; den senaste revisionen annonserades
**2026-06-08** ("Updated Apple Developer Program License Agreement and App
Review Guidelines now available", <https://developer.apple.com/news/>).
Nästa relevanta ändring är EU-villkoren som träder i kraft **2026-10-01**
(se A4 nedan).

### A1. Huvudregeln – 3.1.1 In-App Purchase

> "If you want to unlock features or functionality within your app, (by way
> of example: subscriptions, in-game currencies, game levels, access to
> premium content, or unlocking a full version), you must use in-app
> purchase. Apps may not use their own mechanisms to unlock content or
> functionality, such as license keys, augmented reality markers, QR codes,
> cryptocurrencies and cryptocurrency wallets, etc."

Två saker i det stycket träffar Matjakt. Prenumerationen ("subscriptions")
är det uppenbara. Det mindre uppenbara är **"license keys"**: formuläret
"Har du en Premium-kod? Lös in kod" i kontoarket är en egen mekanism som
låser upp funktionalitet, och den ligger i native-bygget i dag.

Samma avsnitt kräver också en återställningsväg:

> "…you should make sure you have a restore mechanism for any restorable
> in-app purchases."

### A2. Länkar och knappar ut ur appen – 3.1.1(a) och 3.1.3

3.1.1(a) "Link to Other Purchase Methods":

> "In all other storefronts, except for the United States storefront, where
> this prohibition does not apply, apps and their metadata may not include
> buttons, external links, or other calls to action that direct customers
> to purchasing mechanisms other than in-app purchase."

3.1.3 "Other Purchase Methods", inledningen:

> "The following apps may use purchase methods other than in-app purchase.
> Apps in this section cannot, within the app, encourage users to use a
> purchasing method other than in-app purchase, except for apps on the
> United States storefront and as set forth in 3.1.1(a) and 3.1.3(a).
> Developers can send communications outside of the app to their user base
> about purchasing methods other than in-app purchase."

Matjakt säljs på den **svenska** storefronten. US-undantaget ("United
States storefront") och entitlementen för externa köplänkar ("StoreKit
External Purchase Link Entitlements … limited to use only in the iOS or
iPadOS App Store in specific storefronts") ger oss ingenting.

### A3. Undantaget som faktiskt gäller oss – 3.1.3(b) Multiplatform Services

> "Apps that operate across multiple platforms may allow users to access
> content, subscriptions, or features they have acquired in your app on
> other platforms or your web site, including consumable items in
> multi-platform games, provided those items are also available as in-app
> purchases within the app."

Det här är hela grunden för korsplattformsdesignen i (d): ett Premium köpt
via Stripe på matjakt.store **får** låsas upp i iOS-appen – **på villkor
att** samma Premium också går att köpa i appen via IAP. Bisatsen "provided
those items are also available as in-app purchases within the app" är inte
förhandlingsbar och den är anledningen till att "väg A" i `IOS_RELEASE.md`
(ingen köpknapp alls, bara upplåsning) står på osäker grund: 3.1.3(b)
förutsätter att IAP finns. Den enda klausul som tillåter "inget köp alls" är
3.1.3(f):

> "Free apps acting as a stand-alone companion to a paid web based tool
> (i.e. VoIP, Cloud Storage, Email Services, Web Hosting) do not need to
> use in-app purchase, provided there is no purchasing inside the app, or
> calls to action for purchase outside of the app."

Exemplen är verktyg för företag, inte en konsumentapp som säljer en
prenumeration till privatpersoner. Att luta en inlämning mot 3.1.3(f) är en
chansning; 3.1.3(b) med IAP på plats är det säkra spåret.

### A4. Reader-appar och EU/DMA – varför inget av dem är vår väg

**Reader-appar, 3.1.3(a):**

> "Apps may allow a user to access previously purchased content or content
> subscriptions (specifically: magazines, newspapers, books, audio, music,
> and video)."

Matjakt är inget av det. Klausulen gäller inte.

**EU-alternativen.** Apples sida "Changes for apps in the European Union"
(<https://developer.apple.com/support/apps-in-the-eu/>, uppdaterad
2026-08-18) och nyheten samma dag ("Changes for apps in the European Union",
<https://developer.apple.com/news/>) beskriver nya, enhetliga villkor som
gäller från **2026-10-01** genom Attachment 14 i Apple Developer Program
License Agreement. Vad som gäller efter det datumet:

- Tre vägar finns: Apples In-App Purchase, alternativ betalningshantering
  *i* appen, eller erbjudanden som leder ut ur appen. Vald väg måste
  behållas i tolv månader.
- Provision på IAP: **26 %**, eller **15 %** för deltagare i Small Business
  Program (och för auto-förnyande prenumerationer efter första året).
- Provision på alternativ betalning i appen: **20 %**, eller **10 %** för
  Small Business Program. Provisionen rapporteras och betalas till Apple av
  utvecklaren; det kräver en entitlement och egen rapportering av varje
  transaktion.
- Initial Acquisition Fee, Store Services Fee och Core Technology Fee
  försvinner; Core Technology Commission (5 %) gäller bara distribution
  utanför App Store.

Räkneexemplet som avgör: på 59 kr inkl. moms är skillnaden mellan 15 %
(IAP) och 10 % (alternativ betalning) ungefär 2,40 kr per prenumerant och
månad – **före** Stripes avgifter (~1,5 % + fast del), före vår egen
momshantering och OSS-rapportering, och före arbetet med att rapportera
varje transaktion till Apple. På Matjakts skala är den vägen dyrare än den
sparar. IAP med Small Business Program är det rätta valet vid lansering,
och den kan omprövas när volymen motiverar det.

### A5. Reglerna för själva prenumerationen – 3.1.2

> "If you offer an auto-renewable subscription, you must provide ongoing
> value to the customer, and the subscription period must last at least
> seven days and be available across all of the user's devices."

> "Users should have a seamless upgrade/downgrade experience and should not
> be able to inadvertently subscribe to multiple variations of the same
> thing." (3.1.2(b))

> "Before asking a customer to subscribe, you should clearly describe what
> the user will get for the price." (3.1.2(c))

Konsekvenser för oss: månad och år ligger i **samma** subscription group så
Apple sköter byte mellan dem; jämförelsetabellen (J2) och priset syns före
köpknappen; och 3.1.2(c) hänvisar vidare till Schedule 2 i licensavtalet,
som kräver att titel, längd, pris per period samt länkar till
användarvillkor och integritetspolicy finns både i appen och i
metadatan. Länkarna finns redan i kontoarket
(`frontend/app/index.html`, `#accountLegal`).

### A6. Aktiveringstrialen (J3): vad koden gör, mot affärsbeslutet, mot Apple

**Vad koden gör, med fil och rad** (verifierat på `main` 2026-09-16):

| Var | Vad |
|---|---|
| `backend/services/billing/activation.py:41` | `ACTIVATION_TRIAL_DAYS = 7` – "Ett tal, ett ställe." |
| `activation.py:44` `on_first_week()` → `:65` | Ropar `accounts.grant_activation_trial(user_id, ACTIVATION_TRIAL_DAYS)` första gången kontot skapar en vecka, och kör sedan hänvisningskroken (H5). |
| `backend/services/accounts/store.py:490` `mark_first_week()` | Atomär övergång, sann exakt en gång per konto (`WHERE first_week_at IS NULL`). |
| `store.py:506` `grant_activation_trial()` | Skriver `trial_ends_at` = nu + 7 dagar och `trial_used = 1`. Delas **inte** ut till den som redan är Premium, och aldrig två gånger. |
| `backend/api_server.py:3937` och `:4108` | De två utlösarna: en prissatt vecka (`/api/pricing/week`, `_record_first_week`) och klientens händelse `vecka_skapad` (`/api/analytics/event`). |
| `store.py:244`, `:282` | `_to_public`: `trial_ends_at` i framtiden ⇒ `premium: true`, `premiumSource: "trial"`. Samma Premium som betalande, i appen och på webben. |
| `frontend/app/src/views/account.js:344` | Det kunden ser: "✓ Provperiod aktiv – N dagar kvar (ingen betalning krävs)". |
| `frontend/app/src/views/premiumtabellen.js:55` | Provperioden står med flit **inte** i jämförelsetabellen. |

Historiken: commit `0eca3da` (2026-08-31, "Affärsmodellen: Free för
alltid, Premium 59 kr/mån eller 399 kr/år") tog bort **registrerings**-
trialen på fjorton dagar och det gamla årspriset, och `features.py:4`
säger sedan dess "No automatic trial". J3 (PR #114) lade in en **aktiverings**-trial i
stället – `docs/changelog.d/J3.md`: "Trialen togs bort 2026-08-31. Det
var rätt beslut på fel provperiod: en trial vid registrering testar
nyfikenhet. Nu ges sju dagar efter den första skapade veckan". Repot säger
alltså två saker samtidigt, och kunden får sju dagar automatiskt.

**Mot affärsbeslutet.** Den *är* automatisk – ingen kod, inget val, bara
användning – och den *är* en trial. Att den ges efter aktivering i stället
för vid registrering ändrar inte det. Koden och beslutet "59/399, ingen
automatisk trial" är alltså oense, och det avgörs inte här: BLOCKED – ADAM
10 ställer frågan. Ingenting i P02 ändrar beteendet.

**Mot Apple.** Apples egen mekanism för en gratisperiod är introductory
offer, konfigurerad i App Store Connect (3.1.2(a)):

> "Auto-renewable subscription apps may offer a free trial period to
> customers by providing the relevant information set forth in App Store
> Connect."

och för appar utan prenumeration kräver 3.1.1 till och med att en gratis
provperiod modelleras som IAP: "Non-subscription apps may offer a free
time-based trial period … by setting up a Non-Consumable IAP item at Price
Tier 0". Apples free trial är dessutom något annat än vår: "At the end of
the offer period, the subscription auto-renews at the standard price unless
a subscriber cancels it" (developer.apple.com/app-store/subscriptions/).
Kunden måste alltså **starta prenumerationen** för att få dagarna.

Vår aktiveringstrial är inget köp: inga pengar, ingen kod, ingen
betalmetod, ingen konvertering – en tidsbegränsad gåva som servern ger
för att kontot använt produkten. 3.1.1 reglerar *köp- och
upplåsningsmekanismer* ("license keys, augmented reality markers, QR
codes …"); en gåva utan motprestation är ingen sådan. Bedömningen är
därför: **inte ett klart brott, men en granskningsrisk** på två punkter.
(1) Ordet "Provperiod" i appen signalerar en free trial som inte är
Apples, och en granskare som ser Premium tändas av något annat än IAP
frågar. (2) Den gör "ingen automatisk trial" i metadatan osann. Behålls
den ska texten i native säga *ingår* ("Premium ingår i sju dagar efter din
första vecka"), och reviewnoterna säga att perioden är gratis, utan
betalmetod och utan konvertering. Görs den om till Apples introductory
offer gäller Apples villkor: en per subscription group och kund, och
prenumerationen måste startas. Tas den bort försvinner frågan.

Entitlement-modellen i P02b bär `trial` som en egen källa med
`entitlementUntil = trial_ends_at`, i sanningsordningen efter de
betalande källorna. Vilket av de tre svaren Adam ger kräver ingen
schemaändring.

---

## (b) Vad dagens iOS-flöde gör – och att det strider

Verifierat i kod på `main` 2026-09-16:

| Var | Vad |
|---|---|
| `frontend/app/index.html` `#premiumPitch` | Prisflikar, ångerrättsruta, knappen `#subscribeBtn` "Prenumerera", och formuläret `#accountRedeemForm` "Lös in kod". Allt följer med i native-bygget. |
| `frontend/app/app.js`, `subscribeBtn`-lyssnaren | `startCheckout(token, plan, consent)` → `POST /api/billing/checkout` → Stripe Checkout-URL → `openExternal(url)`. |
| `frontend/app/app.js`, `openExternal()` | I native: `@capacitor/browser` (SFSafariViewController), annars `window.open`. |
| `frontend/app/app.js`, `onAppResumed()` | Pollar `/api/auth/me` när appen vaknar tills `premium` är sant (`activatePremiumAfterCheckout`). |
| `backend/services/accounts/features.py` `plan_for_user()` | Läser `user["premium"]` (boolean) + `subscriptionPlan`. |
| `backend/services/accounts/store.py` `_to_public()` | `premium` = evig flagga **eller** trial **eller** Stripe-prenumeration (levande status, period ej passerad) **eller** respit vid nekat kort **eller** inlöst kod (`premium_until`). `premiumSource` ∈ `subscription · grace · trial · code · comped`. |
| StoreKit / IAP | **Finns inte.** Inte i `ios/`, inte i `frontend/`, inte i `backend/`. `features.PRICING` bär redan `storekitProductId`-strängarna, men ingenting läser dem (se C5). |
| `backend/services/billing/activation.py` | Sju dagars Premium efter första skapade veckan, automatiskt, i appen som på webben (A6). |

Mot A1–A2 ovan är slutsatsen entydig:

1. **Knappen "Prenumerera" → Stripe** är "buttons, external links, or other
   calls to action that direct customers to purchasing mechanisms other
   than in-app purchase". Förbjudet på svenska storefronten (3.1.1(a)),
   och prenumerationen som sådan ska säljas via IAP (3.1.1).
2. **"Lös in kod"** är en egen upplåsningsmekanism av typen "license keys"
   (3.1.1). Även utan Stripe-knappen är formuläret en granskningsrisk.
3. **Upplåsning av webbköpt Premium** i appen är tillåten (3.1.3(b)) – men
   bara när Premium också säljs via IAP i appen.
4. Metadatan säger just nu något annat än bygget:
   `store/appstore/metadata/review_notes.txt` rad 12 påstår "Inga
   köpknappar", medan appen visar en. Granskaren som klickar på den ser
   Stripe. Reviewnoterna måste beskriva det bygge som lämnas in.

TestFlight intern testning kräver ingen App Review (`VAG-N-appstore.md`
§0), så `1.0 (1)` får ligga där som den är. Ingen skarp inlämning förrän
P02d är på och flaggan är påslagen.

---

## (c) Vald arkitektur

**StoreKit 2 på iOS. Stripe på webben. En entitlement-sanning på
servern.** Ingen tredjepartsplattform som kräver konto (RevenueCat och
liknande är blockerade – se pluginvalet nedan).

### C1. Entitlement-modellen (P02b)

Premium bärs av en **källa** med en **giltighetstid**. Fyra källor i
briefens vokabulär, plus provperioden som redan finns:

| Källa | Bärs av | Gäller till | Finns i dag |
|---|---|---|---|
| `stripe` | `subscription_status`, `subscription_period_end`, `subscription_plan` (+ `past_due_since`-respiten) | periodslut (+ 3 dygns respit för tappat event) | ja |
| `apple` | `apple_original_transaction_id`, `apple_product_id`, `apple_expires_at`, `apple_status`, `apple_auto_renew`, `apple_environment`, `apple_signed_date` | `apple_expires_at` (+ samma respit så länge status är levande; **noll** respit efter EXPIRED/REVOKE/REFUND) | **nytt** |
| `code` | `premium_until` (H5) | `premium_until` | ja |
| `comp` | flaggan `premium = 1` | för evigt (grandfathrad) | ja |
| `trial` | `trial_ends_at` (J3:s aktiveringstrial, A6 – ett öppet produktbeslut, BLOCKED – ADAM 10) | `trial_ends_at` | ja |

Kolumnerna läggs till additivt (nullbara, `ALTER TABLE ADD COLUMN` i
`AccountStore._init_schema`, samma mönster som H5 och J5), `KONTON` i
`services/schema_version.py` bumpas i samma commit, och
`backend/tests/fixturer/scheman/konton.sql` regenereras med
`test_migrationer.py --spara`. Rollbackplanen är K6/K6b:s: en återställd
release läser bara sina egna kolumner, `stämpla()` sänker aldrig
versionen, och `test_migrationer.py` bevisar att en rad skriven av
föregående version överlever och att en INSERT med bara gamla kolumner
fortfarande går igenom.

`_to_public()` får två nya fält bredvid de gamla, som inte rörs:

- `entitlementSource`: `apple | stripe | code | comp | trial | null` –
  briefens vokabulär. (`premiumSource` behåller sina gamla värden
  `subscription/grace/trial/code/comped` av hänsyn till A01-tratten, och
  får värdet `apple` som nytt.)
- `entitlementUntil`: ISO-tid när den vinnande källan tar slut, `null`
  för `comp`.

Sanningsordning när flera källor är levande (samma princip som A01: den
som **betalar** vinner): `stripe` (levande) → `apple` (levande) → `stripe`
i respit → `trial` → `code` → `comp`. Planen (`premium_monthly` /
`premium_yearly`) är den vinnande källans plan: Stripes `subscription_plan`
eller Apples `apple_product_id`. `plan_for_user()` läser `user["plan"]` när
det är satt och faller annars tillbaka på dagens logik – ingen befintlig
anropare ändras, och grandfathering-regeln i dess docstring
("a paying or comped user must never wake up demoted by a refactor")
prövas av testet: kod, comp, Stripe, Apple, flera samtidigt, och en
**utgången** Apple-källa som ska ge Free.

### C2. Servern tar emot Apples notiser (P02c)

Bakom `MATJAKT_APPLE_IAP` (av som standard; `1/true/yes/on` slår på).
Avstängd flagga = vägarna svarar 404, precis som adminvägarna utan token.

`POST /api/billing/apple/notifications` tar emot App Store Server
Notifications **V2**. Kroppen är `{"signedPayload": "<JWS>"}`. Verifiering
enligt Apples eget referensbibliotek
(<https://github.com/apple/app-store-server-library-python>,
`signed_data_verifier.py`):

1. JWS-huvudets `x5c` ska bära **exakt tre** certifikat: löv →
   mellanliggande → rot. (`INVALID_CHAIN_LENGTH` annars.)
2. Roten jämförs byte för byte med **Apple Root CA – G3**, som pinnas i
   koden. Den är ett publikt rotcertifikat, inte en hemlighet:
   <https://www.apple.com/certificateauthority/AppleRootCA-G3.cer>,
   SHA-256 `63:34:3A:BF:B8:9A:6A:03:EB:B5:7E:9B:3F:5F:A7:BE:7C:4F:5C:75:6F:30:17:B3:A8:C4:88:C3:65:3E:91:79`
   (mätt lokalt med `openssl x509 -fingerprint -sha256` på den nedladdade
   filen 2026-09-16). Kurva P-384, signatur ecdsa-with-SHA384.
3. Mellanliggande certifikat ska bära OID `1.2.840.113635.100.6.2.1`
   (Apple WWDR CA; i dag "Apple Worldwide Developer Relations Certification
   Authority, OU=G6", P-384, giltigt till 2036-03-19). Lövet ska bära OID
   `1.2.840.113635.100.6.11.1`. Varje länk verifieras med utfärdarens
   nyckel; giltighetstiderna prövas mot payloadens `signedDate`.
4. JWS-signaturen (`alg: ES256`, P-256 + SHA-256) verifieras med lövets
   nyckel.
5. Payloadens `data.bundleId` ska vara `se.matjakt.app`; `environment`
   ska vara `Production` om inte `MATJAKT_APPLE_IAP_ACCEPT_SANDBOX=1`
   (staging). `appAppleId` prövas när `MATJAKT_APPLE_APP_ID` är satt.

**Kryptot är ren Python.** `backend/requirements.txt` är hash-låst och
saknar `cryptography`; `services/billing/stripe_client.py` är stdlib av
samma skäl, och `IOS_RELEASE.md` pekade redan ut valet ("kräver
kryptobibliotek – bryter stdlib-only-mönstret eller kräver egen
P-256-implementation"). Verifiering av ECDSA behöver ingen
konstanttidsaritmetik (ingen hemlighet finns på vår sida), och P-256/P-384
över kort Weierstrass-form är samma kod med olika parametrar. Beviset för
att aritmetiken är rätt består av två delar som inte kan ljuga i takt:
kända testvektorer, och **det riktiga WWDR G6-certifikatet verifierat mot
den riktiga roten** som fixtur. Fullständiga kedjor och JWS:er byggs i
testet med en egen signerare och DER-kodare – inga nätanrop, inga
skip.

Hanteringen speglar Stripe-webhookens regler (B1, J5):

| notificationType (subtype) | Vad servern gör |
|---|---|
| `SUBSCRIBED` (`INITIAL_BUY`, `RESUBSCRIBE`), `DID_RENEW` (`BILLING_RECOVERY`) | status `active`; `apple_product_id`/`apple_expires_at` ur `signedTransactionInfo`; `apple_auto_renew` ur `signedRenewalInfo`. |
| `DID_CHANGE_RENEWAL_PREF` (`UPGRADE`/`DOWNGRADE`), `OFFER_REDEEMED` | samma – transaktionsinfon är sanningen, typen är bara en etikett. |
| `DID_CHANGE_RENEWAL_STATUS` | `apple_auto_renew` uppdateras; Premium löper till `expiresDate`. |
| `DID_FAIL_TO_RENEW` (`GRACE_PERIOD`) | status `grace`, `apple_expires_at` = `gracePeriodExpiresDate` (Premium fortsätter: "continue to provide service through the grace period"). |
| `DID_FAIL_TO_RENEW` (utan subtype), `GRACE_PERIOD_EXPIRED` | status `billing_retry`, Premium upphör vid `expiresDate` ("you can stop providing the subscription service"). |
| `EXPIRED` (alla subtyper) | status `expired`, noll respit. |
| `REFUND`, `REVOKE` | status `revoked`, `apple_expires_at` = `revocationDate`; dessutom `premium = 0` och `trial_ends_at = NULL`, samma regel som `revoke_after_refund` för Stripe ("en återbetalning ska inte lämna en gammal kod-inlösning kvar som en osynlig bakdörr"). |
| `REFUND_REVERSED` | status `active` igen, `apple_expires_at` ur transaktionen. |
| `TEST` | 200, loggas, ändrar inget. |
| allt annat | 200 utan åtgärd, `ignored: <typ>` i svaret. |

**Idempotens på `notificationUUID`** – Apple: "Use this value to identify
a duplicate notification." – i tabellen `apple_notifications`, i **samma
transaktion** som tillståndsändringen. Okänd kund rullar tillbaka utan att
förbruka UUID:t och svarar 500, så Apple försöker igen: "For version 2
notifications, it retries five times, at 1, 12, 24, 48, and 72 hours after
the previous attempt." Under tiden hinner appens egen anmälan (nedan) binda
transaktionen till kontot. Ordning: en notis med äldre `signedDate` än
den senast applicerade ignoreras. Svar 200–206 = mottaget.

Tekniska krav från Apple för mottagaren: HTTPS med TLS 1.2 eller senare;
port 443 eller ≥ 1024; avsändarnät `17.0.0.0/8` om vi har en allowlist.
Render uppfyller det utan ändring.

`POST /api/billing/apple/transaction` (inloggad, `{"jws": "<signed
transaction>"}`) är appens egen anmälan av ett köp eller en
återställning. Samma verifierare; dessutom ska `appAccountToken` i
transaktionen vara **kontots** token (nedan), annars nekas anmälan – en
JWS från någon annans telefon kan inte ge Premium här. Servern skriver
samma `apple_*`-fält som en notis skulle, och svarar med kontot.

`GET /api/entitlements` får, när flaggan är på och anroparen är inloggad,
ett block `apple: {enabled, appAccountToken, products: {monthly, yearly}}`.
Produkt-id:na är `features.PRICING[*]["storekitProductId"]`.

**Kopplingen konto ↔ Apple-kund** är `appAccountToken`: ett UUID v5 som
servern härleder ur konto-id:t (fast namnrymd, deterministiskt, ingen
hemlighet), som appen skickar med i `purchaseProduct(...)` och som Apple
sedan bär i varje transaktion och notis. Apple ger oss aldrig kundens
e-post; token är den enda vägen tillbaka. Uppslag i tur och ordning:
`apple_original_transaction_id` → lagrad token → beräknad token (genomgång
av konton; billigt på vår skala) → okänd kund (500, omförsök).

### C3. Appen (P02d)

Bakom samma flagga, läst ur `/api/entitlements` (`apple.enabled`). Av =
dagens beteende (Stripe-knappen står kvar för intern TestFlight). På, i
native:

- Knappen "Prenumerera" köper vald plan via StoreKit 2 med
  `appAccountToken`, skickar `jwsRepresentation` till
  `/api/billing/apple/transaction`, och ritar om kontot.
- Priset på knappen och prisflikarna visar **StoreKits** lokaliserade
  `displayPrice` för produkten, inte 59/399 ur `features.PRICING`. Apples
  prispunkt kan avvika från webbpriset, och det pris som visas ska vara
  det som dras (prisinformationslagen). Webben fortsätter läsa
  `PRICING`.
- **"Återställ köp"** (3.1.1: "restore mechanism") – `restorePurchases()`
  + `getPurchases({onlyCurrentEntitlements: true})` → anmälan till
  servern.
- "Hantera prenumeration" öppnar App Stores prenumerationssida
  (`manageSubscriptions()`) när källan är `apple`; Stripes portal när den
  är `stripe`.
- Ångerrättsrutan (B3) **visas inte** i IAP-flödet. Apple är säljare av
  IAP och hanterar kundens ångerrätt och återbetalningar i sina
  villkor; vår ruta hör till Stripe-köpet på webben.
- Formuläret "Lös in kod" **döljs i native** (A1, "license keys").
  Koder löses in på webben och slår igenom i appen via 3.1.3(b).
- På webben ändras ingenting.

### C4. Pluginvalet: `@capgo/native-purchases`, inte `cordova-plugin-purchase`

Briefens förstahandsval var `cordova-plugin-purchase` v13+ "om det fungerar
med Capacitor 8.5". Verifierat 2026-09-16 mot npm-registret och
projektets README:

| | `cordova-plugin-purchase` 13.18.0 | `@capgo/native-purchases` 8.7.0 |
|---|---|---|
| Licens | MIT | MPL-2.0 (filbaserad copyleft; vi ändrar inte filerna, så inget i Matjakt påverkas) |
| StoreKit | **StoreKit 1** (SKPaymentQueue + app-kvitto) som standard; StoreKit 2 bara via den separata adaptern `cordova-plugin-purchase-storekit2` 1.0.5 (januari 2025) | **StoreKit 2 enbart**, iOS 15+ (projektets deployment target är 15.0) |
| Capacitor 8 | Via Cordova-kompatibilitetslagret. Capacitors SPM-dokumentation: "Projects with Cordova plugins should work, but some plugins may not work correctly as we have to generate a `Package.swift` file for them." Projektet kör SPM (`ios/App/CapApp-SPM`). | Inbyggd Capacitor-plugin med egen `Package.swift` (`CapgoNativePurchases`, iOS 15, `capacitor-swift-pm` ≥ 8.0.0); `peerDependencies: @capacitor/core >= 8.0.0`. |
| Serververifiering | Kvitto (StoreKit 1) eller JWS via adaptern | `Transaction.jwsRepresentation` – samma JWS-format och samma certifikatkedja som notiserna, så **en** verifierare räcker på servern |
| Konto hos leverantör | Nej (Iaptic är frivilligt) | Nej ("No Capgo account required") |
| `appAccountToken` | Ja | Ja (UUID-format krävs, som Apple kräver) |
| API vi behöver | finns | `getProducts`, `purchaseProduct`, `restorePurchases`, `getPurchases({onlyCurrentEntitlements})`, `manageSubscriptions`, `isBillingSupported` |

Avgörande: projektet är ett SPM-projekt, och vi vill ha StoreKit 2 utan
en adapter från en enskild utgivare. `@capgo/native-purchases` är den
plugin som ger StoreKit 2 direkt, ligger i Capacitors egna SPM-form och
lämnar ut JWS:en oförändrad. Installeras med `npm install
@capgo/native-purchases` + `npx cap sync ios`, som skriver om
`CapApp-SPM/Package.swift` (filen är CLI-hanterad och redigeras aldrig för
hand). RevenueCat och andra leverantörer som kräver konto är uteslutna av
briefen och behövs inte: verifieringen sker på vår server.

### C5. Produkt-id:na i `features.py`

`backend/services/accounts/features.py`, `PRICING`:
`"storekitProductId": "se.matjakt.premium.monthly"` respektive
`"se.matjakt.premium.yearly"`, med kommentaren "Fylls i när riktiga
betalplattformar kopplas på." De kom in med commit `0eca3da` (2026-08-31,
samma commit som satte 59/399), och **ingenting läser dem i dag**: inte
appen (`grep storekitProductId frontend/app` är tomt), inte servern
utöver att `/api/entitlements` skickar hela `PRICING` vidare.

Om de matchar något i App Store Connect går inte att läsa härifrån:
Monetization → Subscriptions kräver Adams inloggning, och repot har ingen
App Store Connect API-nyckel (och ska inte ha någon i en spårad fil).
Rekommendationen är att de **blir** de riktiga StoreKit-id:na: formen är
rätt (omvänd domän, en produkt per plan), de hör ihop med planerna i samma
tabell som priserna, och `test_iap_compliance.py` binder redan det här
dokumentet till exakt de strängarna – P02c och P02d binder koden till
`PRICING[*]["storekitProductId"]` på samma sätt. Det som återstår är att
Adam kontrollerar att inget annat redan ligger i App Store Connect innan
produkterna skapas (BLOCKED – ADAM 3, första punkten).

---

## (d) Köp på iOS ger Premium på webben – och tvärtom

Kontot är nyckeln, inte enheten. Samma inloggning på båda ställena.

**Köpt på webben (Stripe) → syns i appen.** Stripes webhook skriver
`subscription_status`/`period_end` som i dag; appen läser `/api/auth/me`
och `/api/entitlements` och låser upp. Tillåtet enligt 3.1.3(b) *därför
att* appen också säljer Premium via IAP. Appen visar ingen köpknapp för den
som redan har Premium (så i dag: `premiumPitch.hidden = user.premium`), och
"Hantera prenumeration" pekar dit köpet gjordes. Ingen text i appen får
säga "billigare på webben" (3.1.1(a)); det får vi säga i mejl och på
sajten ("Developers can send communications outside of the app").

**Köpt i appen (Apple) → syns på webben.** Notisen (eller appens anmälan)
skriver `apple_*`; `_to_public()` säger `premium: true, entitlementSource:
"apple"`; webben låser upp på exakt samma villkor som för Stripe. Webbens
kontosida visar "Prenumerationen hanteras i App Store" i stället för
Stripes portal.

**Två prenumerationer samtidigt förhindras på servern:**
`/api/billing/checkout` svarar 409 `ALREADY_SUBSCRIBED` när en
Apple-källa är levande (samma väg som i dag för en levande Stripe-status),
och appen döljer IAP-knappen när en Stripe-källa är levande. Skulle båda
ändå finnas vinner den betalande källan i sanningsordningen och kontosidan
säger var den andra sägs upp.

**Familjedelning** (Family Sharing) sätts **inte** på i App Store Connect
för v1. `REVOKE`-hanteringen finns, men hushållsdelningen i Matjakt är en
egen funktion (J3) och ska inte blandas ihop med Apples.

**Moms.** Apple är säljare och redovisar svensk moms för IAP-köp. B2:s
Stripe Tax och B2b:s OSS-rapportering gäller bara webbköpen. Ingen
Apple-intäkt får räknas in i OSS-underlaget.

**Integritetsetiketten** i App Store Connect bär redan "köphistorik"
(`store/appstore/APP_PRIVACY_LABEL.md`); `appAccountToken` är en
pseudonym kopplad till kontot, ingen ny kategori.

---

## (e) BLOCKED – ADAM

Varje punkt kan bara göras av Account Holder eller kräver inloggning i
App Store Connect (<https://appstoreconnect.apple.com>). Klickvägarna är
Apples egna hjälptexter, lästa 2026-09-16
(<https://developer.apple.com/help/app-store-connect/>). **Hårdkoda inga
belopp ur ASC i repot** – välj prispunkt i gränssnittet, appen visar
StoreKits `displayPrice`.

### BLOCKED – ADAM 1 · Paid Apps-avtalet

Utan det går varken produkter eller inlämning att skapa. "Once accepted,
this action cannot be undone."

- Klickväg: App Store Connect → **Business** (överst) → fliken
  **Agreements** → raden **Paid Apps** → **View and Agree to Terms** → läs →
  **Agree**. Roll: **Account Holder**. Tvåfaktorskod kan krävas.
- Sedan, i samma **Business**-vy: **Tax** → skatteformulär (svensk enskild
  firma: W-8BEN-liknande formulär för USA + de EU/övriga som ASC ber om),
  och **Banking** → svenskt bankkonto (IBAN, BIC, kontoinnehavare).
  Apple: uppdateringar av juridisk information kan ta upp till två veckor.

### BLOCKED – ADAM 2 · Small Business Program (15 % i stället för 26 %)

- Klickväg: <https://developer.apple.com/app-store/small-business-program/enroll/>
  → logga in som **Account Holder** → bekräfta att Paid Apps-avtalet är
  accepterat → lista eventuella Associated Developer Accounts → skicka.
- Gäller från "15 days after the end of the fiscal calendar month in which
  your enrollment is approved". Gör det **före** första IAP-försäljningen.

### BLOCKED – ADAM 3 · Subscription group och två produkter

- Först, läs bara: **Apps** → Matjakt → sidopanelen **Monetization** →
  **Subscriptions**. Är listan tom skapas allt nedan. Finns det redan
  produkter med **andra** id:n än `se.matjakt.premium.monthly` /
  `se.matjakt.premium.yearly`: säg till innan P02c/P02d – koden binder sig
  till strängarna i `features.py` (C5), och ett produkt-id går inte att
  byta i efterhand.
- Klickväg: **Apps** → Matjakt → sidopanelen **Monetization** →
  **Subscriptions** → **(+)** → Reference Name `Matjakt Premium` → **Create**.
- I gruppen: **Create** → Reference Name `Premium månad`, **Product ID**
  `se.matjakt.premium.monthly` → **Create** → **Subscription Duration**
  `1 month` → **Save**. Upprepa: `Premium år`, `se.matjakt.premium.yearly`,
  `1 year`. Produkt-id:na är exakt strängarna i
  `backend/services/accounts/features.py` (`PRICING[*]["storekitProductId"]`);
  ett produkt-id kan inte återanvändas efter borttagning, så stava rätt.
- Nivåer i gruppen: året högst (nivå 1), månaden under. Då räknar Apple
  månad → år som uppgradering (omedelbar) och år → månad som nedgradering
  (vid nästa förnyelse), enligt 3.1.2(b).
- **App Store Localizations** (svenska): gruppens visningsnamn `Matjakt
  Premium`; produkternas visningsnamn `Premium` / `Premium År` och
  beskrivningar (ta ingressen från `#premiumPitch`: alla butikers priser,
  priser per vara under dagen, hela hushållet delar veckan).
- **Review Information** per produkt: skärmbild av premiumskärmen (efter
  P02d) och en anteckning som förklarar att Premium också säljs på webben
  och att köpta konton låses upp i appen (3.1.3(b)).
- Första prenumerationen "must be submitted with a new app version":
  **Add for Review** på produkten när P02d-bygget lämnas in.

### BLOCKED – ADAM 4 · Prispunkter (läs listan, hårdkoda inget)

- Klickväg: produkten → **Subscription Prices** → **Add Subscription
  Price** → land/region **Sweden** → välj prispunkt → **Next**. Apple
  visar "comparable prices for all 175 App Store countries and regions"
  automatiskt; **Next** → kontrollera → **Confirm**. 800 prispunkter per
  valuta finns; **See Additional Prices** visar hela listan.
- Välj den prispunkt i SEK som ligger **närmast 59 kr** för månaden och
  **närmast 399 kr** för året (inkl. moms – Apples priser är alltid
  konsumentpriser). Vilka punkter som finns går bara att läsa i ASC;
  därför står inget belopp här och inget i koden. Kolumnen "Proceeds" i
  samma vy visar vad vi får ut per punkt efter moms och provision.
- **Export as CSV** ger listan om du vill jämföra med Stripe-priset.
- Ingen introduktionsperiod, inget gratisprov (affärsbeslut 2026-08-31,
  `features.py`: "No automatic trial"). Lämna **Introductory Offers**
  tomt.

### BLOCKED – ADAM 5 · Notis-URL:er (Server Notifications V2)

- Klickväg: **Apps** → Matjakt → sidopanelen **General** → **App
  Information** → rulla till **App Store Server Notifications** →
  **Production Server URL** → **Set Up URL** →
  `https://matjakt.onrender.com/api/billing/apple/notifications` → välj
  **Version 2** → **Save**. Roll: Account Holder, Admin, App Manager eller
  Marketing.
- **Sandbox Server URL**: peka på **staging** (K4), inte produktion.
  Apple: "If you do not provide a Sandbox URL … the App Store will
  automatically send notifications for both environments to the
  Production URL" – produktionsservern ignorerar sandbox-notiser (200
  utan åtgärd) om inte `MATJAKT_APPLE_IAP_ACCEPT_SANDBOX=1`, men de ska
  ändå inte dit.
- Testa mottagaren med **Request a Test Notification** (App Store Server
  API) – kräver en API-nyckel, se punkt 7.

### BLOCKED – ADAM 6 · Miljövariabler på Render (aldrig i en spårad fil)

- Klickväg: <https://dashboard.render.com> → tjänsten **matjakt** →
  **Environment** → **Add Environment Variable**.
- `MATJAKT_APPLE_IAP=1` (produktion, först när P02d är mergad och
  produkterna godkända), `MATJAKT_APPLE_APP_ID=<Apple ID>` (siffran under
  **App Information** → **General Information** → **Apple ID**),
  `MATJAKT_APPLE_IAP_ACCEPT_SANDBOX=1` **bara** på staging.
- Inga hemligheter behövs för själva mottagaren: verifieringen bygger på
  Apples publika rot. (Det finns ingen "shared secret" i V2; den hör till
  det utfasade `verifyReceipt`.)

### BLOCKED – ADAM 7 · In-App Purchase-nyckel för App Store Server API (uppföljning)

Behövs inte för P02b–P02d, men för avstämning ("Get All Subscription
Statuses") och för testnotisen.

- Klickväg: **Users and Access** → **Integrations** → **In-App Purchase**
  → **(+)** → namn `matjakt-server` → **Generate** → ladda ner `.p8`
  **en gång**. Nyckel-id och Issuer ID står i samma vy.
- Läggs i Render som miljövariabler när avstämningen byggs. `.p8`-filen
  hamnar aldrig i repot (`.gitignore` blockerar redan `*.p8` via N0f).

### BLOCKED – ADAM 8 · Sandbox-testare och TestFlight-test

- Klickväg: **Users and Access** → **Sandbox** → **Test Accounts** →
  **(+)** → en e-postadress som inte är ett Apple-konto → land Sverige.
- På telefonen: **Inställningar → App Store → Sandbox Account** → logga in
  med testkontot. Köp i TestFlight-bygget dras då i sandbox (ingen
  riktig debitering). Mot staging med `MATJAKT_APPLE_IAP_ACCEPT_SANDBOX=1`.

### BLOCKED – ADAM 9 · Metadata före inlämning

- Klickväg: **Apps** → Matjakt → **App Information** → **License
  Agreement**: Apples standard-EULA räcker. Sedan **App Privacy** →
  **Privacy Policy URL**: `https://matjakt.store/integritetspolicy.html`.
- `store/appstore/metadata/review_notes.txt` rad 12 ("Inga köpknappar")
  skrivs om till det som gäller efter P02d: Premium säljs via IAP i appen,
  och konton som köpt på webben låses upp enligt 3.1.3(b). (Z-SITE, eget
  paket.)

### BLOCKED – ADAM 10 · Aktiveringstrialen – produktbeslutet

Koden ger sju dagars Premium efter kontots första skapade vecka (A6);
affärsbeslutet lyder "59/399, ingen automatisk trial". Frågan, exakt:

**Ska sju dagars Premium efter första skapade veckan finnas kvar – och i
så fall i vilken form?** Tre svar, och vad vart och ett betyder:

- **(A) Behåll den som gåva.** Ingen kodändring i servern. I native byts
  ordet "Provperiod" mot "ingår" (P02d), och reviewnoterna säger att
  perioden är gratis, utan betalmetod och utan konvertering. Kvar står
  granskningsrisken i A6 och att "ingen automatisk trial" inte stämmer.
- **(B) Gör om den till Apples introductory offer** (free trial, 1 vecka)
  på båda produkterna, och stäng serverns. Kunden måste då *starta*
  prenumerationen för att få dagarna, och de dras automatiskt efteråt –
  en annan tratt än J3:s. Klickväg: **Apps** → Matjakt → sidopanelen
  **Subscriptions** → gruppen → produkten → **Subscription Prices** →
  **View all Subscription pricing** → **Set up Introductory Offer** →
  typ **Free Trial** → längd **1 Week** → länder. Apples regel: en
  introductory offer per subscription group och kund. (Gäller bara iOS;
  webben har då ingen trial alls, om inte Stripe-Checkout får
  `trial_period_days` i ett eget paket.)
- **(C) Ta bort den**, enligt beslutet som det står. `ACTIVATION_TRIAL_DAYS`
  och `grant_activation_trial` slutar användas; hänvisningskroken (H5)
  hänger på samma `on_first_week` och påverkas inte.

Inget av svaren kräver en schemaändring: `trial` är sedan P02b en egen
källa med slutdatum i entitlement-modellen. Tills svaret finns ändrar P02
ingenting i beteendet.

---

## Paketen och det som återstår

| Paket | Zon | Innehåll | Status |
|---|---|---|---|
| P02a | docs | det här dokumentet + testet som binder det till `features.PRICING` | #198 |
| P02b | Z-AUTH | kolumnerna, `_to_public`, `plan_for_user`, KONTON-bump, fixtur, tester | #200 |
| P02c | Z-BILLING | JWS-verifierare (ren Python), notismottagare, appens anmälan, `apple`-blocket i `/api/entitlements`, flaggan | #206 |
| P02d | Z-NATIVE + köpknappen | `@capgo/native-purchases`, köp/återställ/hantera, StoreKit-priser, dölj kod-formuläret och ångerrättsrutan i IAP-läge | PR efter #206 |

Flaggan är av i produktion tills Adam gjort punkterna 1–6 ovan och P02d ligger
i ett TestFlight-bygge som prövats mot staging med en sandbox-testare
(punkt 8). Först då: `MATJAKT_APPLE_IAP=1` på Render, nytt bygge, inlämning.

Uppföljningar som **inte** ingår i P02: avstämning mot App Store Server
API (kräver nyckeln i punkt 7); Apple Offer Codes som ersättning för
hänvisningskoder på iOS; webbens kontosida ("hanteras i App Store"); N1 i
`VAG-N-appstore.md` ("plocka bort köpflödet") ersätts av P02d – köpflödet
byts ut, inte tas bort.
