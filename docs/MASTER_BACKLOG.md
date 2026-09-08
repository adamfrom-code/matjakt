# Matjakt — kravmatris

Beständig arbetslista från ägarens masterinstruktion 2026-09-07. **Inget krav
får försvinna härifrån.** Nästa session fortsätter i den här filen i stället
för att börja om.

## Statusord

| Status | Betyder |
|---|---|
| `verifierat` | Byggt, testat OCH kontrollerat i den miljö som räknas |
| `klart att testa` | Kod finns och är mergad, men effekten är inte kontrollerad |
| `pågår` | Påbörjat i en gren/PR |
| `att göra` | Inventerat, inte påbörjat |
| `behöver verifieras` | Fanns redan i koden; effekten är inte bekräftad av mig |
| `blockerat` | Kräver åtkomst, betalning eller beslut jag inte har |

**Färdig kod ≠ mergad kod ≠ driftsatt kod ≠ verifierad produktion.** Kolumnen
Bevis säger vilket av dem som faktiskt gäller.

---

## Kända begränsningar i min verifiering

Det här gäller allt nedan och ska inte behöva upprepas per rad:

- **Ingen ICA- eller Coop-import har någonsin körts.** Basket coverage, gate-%
  och canonical match för dem är därför `ej verifierat`, aldrig uppskattat.
- **Admin-token hanterar jag inte.** Manuella importer via
  `/api/admin/grocery-import` kan jag inte starta.
- **Primats kvot** kan bara läsas om deras API exponerar den. Tills det är
  bekräftat står `ej tillgängligt` — ingen egen räknare presenteras som deras.
- Backendsviten körs lokalt med Python 3.12 (`backend/venv`) sedan 2026-09-07.

---

## F — fynd att revalidera och rätta (Fas 1)

| ID | Krav | Status | Bevis / nästa steg |
|---|---|---|---|
| F1 | Ofullständig kasse får inte krönas billigast | **klart att testa** | Revaliderat mot `235958a`: felet fanns kvar. PR #9 mergad (`9d68f48`). Regressionstest med exakt scenariot. Kvar: bekräfta i produktion att ingen kröning sker vid olika kassar |
| F2 | Veckoval ska prissättas med riktig prismotor, inte ungefärlig kostnad | att göra — **kräver beslut** | Se avsnittet nedan |
| F3 | Färskhet per prisrad | **klart att testa** (mergad `380a136`) | Åldern räknas nu på äldsta raden som faktiskt användes. Felet var värre än rapporterat: MAX() filtrerade bara på butik, inte på kassans varor |
| F3b | Åldersgräns på referenspriser | att göra — **kräver beslut** | `store.py:869` hämtar referenspriser utan åldersgräns, och `pricing.py:1355` släpper ett för gammalt butikspris till förmån för ett referenspris som kan vara ÄLDRE. Kräver ett beslut om maxålder |
| F4 | Skilj möjlig / planerad / genomförd besparing | **delvis, mergad** (`8103df5`) | "Billigaste butiken för dig" var läget av VALD butik - ingen prisjämförelse alls. Etiketten rättad, dedupering per vecka inlagd. Kvar: posten skrivs vid val, inte vid handling |
| F5 | Osäker enhetsgenväg får inte räknas som exakt | **klart att testa** (mergad `f320e8a`) | Regeln prövade aldrig att varan var en krydda: 2 msk honung (~42 g) fick "1 paket, exakt" mot en 15 g-burk. Räknades in i säkra totaler och gick in i billigast-jämförelsen. Revisionen fångar det inte |
| F6 | Databasincidenten i git-historiken | **blockerat** | Kräver force-push mot delad historik = ägarbeslut. Ingen destruktiv sanering utan uttryckligt godkännande |
| F7 | Skilj CI, merge och deploy | verifierat | Kontrollerat 2026-09-07: `main` `235958a` live på backend, webben v34. Den misslyckade Pages-körningen följdes av en lyckad |

---

### F2 i detalj — varför den inte är en enkel fix

Revaliderat mot `app.js:882`. Felet är kvar:

```js
function comboEstimatedCost(combo) {
  const factor = portionFactor(state.personer);
  return combo.reduce((sum, recipe) =>
    sum + (recipe.inkopspris ?? medianInkopspris()) * factor, 0);
}
```

Två fel i samma rad. Receptens **separata** inköpspriser summeras, så en
förpackning som delas mellan två rätter räknas två gånger. Och kostnaden
skalas **linjärt** med antal personer, men hela förpackningar skalar inte
så — en dubbelt så stor familj köper sällan dubbelt så många paket.

Talet används sedan på två ställen som båda gör skada:

- `inBudgetPool(evaluated, budget)` förkastar veckor mot användarens
  **riktiga** budget med ett **falskt** tal. En vecka som hade rymts
  sorteras bort, en som inte ryms släpps igenom.
- `pickCheapest` väljer billigast på samma falska tal.

Veckan prissätts korrekt EFTER valet (`/api/pricing/week`), så användaren
ser till slut rätt summa — men valet är redan gjort på fel grund.

**Varför jag inte rättade den direkt.** `bestMenuCombo` är synkron och
anropas från tre ställen (`app.js:1177`, `:1237`, `:4382`). En riktig fix
kräver att kandidatval och prissättning skiljs åt: sålla snabbt, prissätta
ett fåtal hela kassar med riktiga motorn, välja på det. Det gör funktionen
asynkron, kräver laddningstillstånd i tre vyer och nätanrop mitt i
planeringen. Det är en arkitekturändring, inte en rättelse — och
browser-E2E:n är redan tidskänslig (två olika flakiga fall observerade).

**Föreslagen ordning när den tas:**
1. Bryt ut kandidatvalet så det går att testa utan DOM.
2. Lägg till en prissättning av N kandidatkassar bakom ett explicit anrop.
3. Gör budgetfiltret tolerant tills det riktiga priset finns — en
   uppskattning får aldrig ensam förkasta en vecka mot en riktig budget.
4. Visa det användaren behöver när budgeten inte går att hålla, med
   konkreta ändringar (F2:s egen formulering).

### O10b i detalj — de trettio osäkra raderna

F5 rättade en regel som märkte osäkra rader som exakta. Följden är att
revisionen nu är röd på `estimat: 30` (= 10 receptrader × 3 kedjor).
**Ingen siffra har blivit sämre; en osanning har slutat döljas.**

Mekanismen: ingrediensen mäts i volym (ml/msk/tsk), varan säljs i gram, och
ingen densitet finns för just den ingrediensen. Motorn kan då inte veta hur
många förpackningar som behövs och markerar raden som uppskattad. Raderna
hålls redan utanför säkra totaler och billigast-jämförelsen — de ljuger
alltså inte för användaren, de erkänner.

Ur repots egen receptkälla går **en** av de tio att härleda: `Soja (30 ml)`
i fem recept. Produktionen har 240 recept mot repots 58, så resten syns
först när PR #16 är deployad.

**Två vägar, och de är inte lika bra:**

1. **Ge de ingredienser som har en verklig densitet sin densitet.** Motorn
   har redan `DAIRY_DENSITY_ONE` för tunna såser (ketchup ~1,14, senap,
   sriracha…). Soja ligger på ~1,15 och hör hemma i samma grupp. Det ger
   ett *rättare* pris, inte ett grönare — ofta ett högre, för 30 ml soja är
   34 g och kan behöva två flaskor där en gissades.
2. **Acceptera att osäkerhet är ett giltigt tillstånd** och låt gaten mäta
   det separat i stället för att kräva `estimat = 0`.

**Det som INTE får göras:** utöka `DRY_SPICES` med honung, sirap eller olja
för att få grönt. Det vore att återinföra precis den lögn F5 tog bort.
Gaten är dessutom rådgivande — den blockerar ingenting, den rapporteras i
`/api/health`.

---

## O — Operations (Fas 2)

| ID | Krav | Status | Bevis / nästa steg |
|---|---|---|---|
| O1 | Driftstatus som adminförstasida | **klart att testa** | Byggd och mergad (`d9aab36`). Verifierad i webbläsare mot fixturserver, desktop + mobil 375 px. Kvar: se den mot riktig produktionsdata |
| O2 | Rad/kort per kedja med health, released, scope, snapshot, ålder, gate | **klart att testa** | `chain_health()` + tabellkolumner mergade. Drift, Släppt och Provider är skilda kolumner |
| O3 | ICA/Coop: visa ej släppt, schema, ingen verifierad snapshot | **pågår** | Schema dagligen 05:30/06:30 mergat (#5). Coverage `ej verifierat` |
| O4 | Lidl som Limited med orsak | **pågår** | `limited` finns i statusmodellen och larmar aldrig |
| O5 | Aktiva incidenter med kundpåverkan | delvis | Incidenter finns i `alerts.py`; adminvyn som visar dem saknas |
| O6 | Incidenthistorik, persistenta ID, dedupe | delvis | Dedupe + recovery mergat (`745d37e`), 12 tester. Historikvy saknas |
| O7 | Admin-mail: skilj mottagare/transport/försök/leverans | delvis | **Verifierat live 2026-09-07:** `adminAlerts` visar recipientConfigured + transportConfigured = true, domän icloud.com. Kvar: senaste skickförsök och faktisk leverans |
| O8 | Primat: configured JA/NEJ, kvot endast från verklig API-data | **blockerat** | Ingen dokumenterad kvot-endpoint hittad. Står `ej tillgängligt` tills motsatsen bevisas |
| O9 | Scheduler: schema, faktiska körningar, nästa körning | delvis | Operations-koll 07:00 inkopplad med test som kräver att den ligger efter alla importer |
| O10 | Pricing audit med definierade nämnare | **pågår** | Auditen är **RÖD** sedan F5 mergades: `estimat: 30`, allt annat 0, täckning 99,7 %. Inte en regression — F5 slutade märka osäkra rader som exakta. PR #16 får auditen att namnge vilka ingredienser som är osäkra; utan det går flaggan inte att åtgärda utan admin-token. Live-parsningsvägen granskas fortfarande INTE av auditen |
| O10b | Besluta vad som ska hända med de osäkra raderna | **kräver beslut** | Se avsnittet nedan |
| O11 | Deploy: commit, tider, avvikelse | delvis | `health.commit` finns; jämförelse mot förväntad deploy saknas |
| O12 | Skyddat admin-API, inte bara dold knapp | behöver verifieras | `_admin_ok()` finns på endpointerna; negativa tester för household-medlem saknas |
| O13 | Mobilanpassad admin | att göra | |
| O14 | Testlista för Operations | delvis | 21 av testerna finns (chain_health 9, alerts 12) |
| O15 | Active stores + kvotmonitorering | att göra | De fyra definitionerna (register / valda / färska / kundtillgängliga) ska hållas isär |

---

## U — konsumentappen (Fas 4–6)

Samtliga 80 krav är inventerade. Ingen är påbörjad; de kräver Operations
först enligt ägarens egen faseordning.

| Grupp | ID | Status |
|---|---|---|
| Första användningen | U01–U06 | **delvis** — se raderna nedan |

### U01–U06 i detalj

| ID | Status | Bevis |
|---|---|---|
| U01 | **verifierat** | #17 mergad och driftsatt. Strängen `Frukost, lunch och hushållsvaror ingår inte` bekräftad i det minifierade bundlet på matjakt.store, frontend v37 |
| U02 | **verifierat** | Gästen får en prissatt vecka utan konto, och veckan överlever registreringen - både lokalt och på servern. E2E-test som går hela vägen: gäst → vecka → pris → konto → `GET /api/account/state` |
| U03 | **mätt** | Tiden från öppnad app till en lista med varor OCH riktigt pris: **2,6–5,3 s** över sex lokala körningar, median ~3,2 s, 18–23 varor. Kravets mål är ungefär en minut. Siffran är ett GOLV, inte en människas tid: maskinen skriver inte och servern är lokal. I CI: **1,7–1,8 s**. Åtta mätningar totalt, 1,7–5,3 s. Testet skriver ut mätvärdet vid varje körning och faller över 30 s - nära sex gånger det långsammaste vi sett |
| U04 | behöver verifieras | Justera veckan når alla startval utan omstart; ändringarna slår igenom direkt (sett i webbläsare vid U01-arbetet). Inget test |
| U05 | behöver verifieras | Koden skiljer på `stillFetching` ("pris hämtas…") och verkligt saknat pris ("pris saknas just nu") - alltså ingen ändlös spinner och inga tekniska detaljer. Inte prövat systematiskt |
| U06 | **verifierat** | #21 mergad och driftsatt. `står redan på listan` och `lägg till i inköpslistan` bekräftade i bundlet. Kvarstående lucka i extravarornas pris är dokumenterad, inte dold |
| Veckoplanering | U07–U18 | att göra |
| Pengar | U19–U30 | att göra (U19 = F1, **pågår**) |
| I butiken | U31–U42 | att göra |
| Matlagning | U43–U52 | att göra |
| Skafferi och rester | U53–U60 | att göra |
| Utseende och känsla | U61–U70 | att göra |
| Teknik | U71–U80 | att göra (U72 delvis: cacheversion mergad i PR #7; U80 = F6, blockerat) |

## X — ytterligare produktflöden

`X01`–`X17` inventerade, alla `att göra`. X16 (köp hela listan) är
**blockerat** av avtal/åtkomst: tidigare granskning visade tomt
providerregister och hemsidefallback, inte färdig korgöverföring.

## A — ägarpanelen utöver Operations

`A01`–`A09` inventerade, alla `att göra`. A06 (ekonomi) kräver verifierad
betaldata; ingen intäktssiffra får härledas ur antal Premium × pris.

---

## Mergat, driftsatt och verifierat är tre olika saker

Kontrollerat mot GitHub och `/api/health` 2026-09-08:

| | Läge |
|---|---|
| Mergade till `main` | #16, #17, #19, #20 |
| Faktiskt driftsatt | `6f8f2f4` — innehåller #16, #17, #19, #20 |
| Öppen | #21 (U06) — **blockerande fynd, se nedan** |
| Stängd utan merge | #18 — basgrenen togs bort vid mergen av #17; ersatt av #21 |
| Verifierat i produktion | Bara #16: `estimatPerIngrediens` svarar live. #17 är driftsatt men inte kontrollerad mot riktig trafik |

## Blockerande fynd: en tillagd extravara får ofta inget pris

Gäller alla extravaror, även de som skrivs in för hand - inte något U06
införde, men U06 gör vägen ett tryck lång.

`syncExtraMatches` prissätter varje extravara som **1 st**. En vara som
säljs i gram eller milliliter går inte att räkna om från styck, så
`price_list` markerar raden osäker och nollar `totalCost` enligt regeln om
säkra totaler - och klienten filtrerar bort rader utan total
(`item.totalCost != null`). Raden visas som "Ingen säker prismatch – egen
rad" och bidrar med 0 kr.

**Mätt mot fixturen: 13 av 35 antagna hemmavaror hamnar där** - Olivolja,
Smör, Vetemjöl, Ris, Honung, Sirap, Parmesan, Ströbröd, Sesamfrön,
Ingefära, Paprikapulver, Spiskummin, Ättika.

Vad som INTE är orsaken: en hypotes om att Free-gaten räknade på fel korg
(`_free_chain_for` över enbart extravarorna). Den byggde jag och mätte:
**8 gröna av 10 före ändringen, 8 av 10 efter** - alltså ingen effekt.
Ändringen är återtagen. Betalväggskod ska inte ändras på en gissning.
`_pricing_items` slår dessutom redan ihop `recipeIds` med `items`, så
gaten ser veckan när klienten skickar med den.

Kvar att avgöra: vad "1 st" ska betyda för en förpackad vara. Motorn kan
inte skilja "1 st gul lök" (en styckvara) från "1 st flaska olja" (en
förpackning), och att gissa fel åt något håll ger fel pris. Det är ett
riktigt designval, inte en bugg att slarva bort.

## O10b: de trettio osäkra raderna - underlag saknas

De verkliga raderna, lästa ur `/api/health` efter att #16 driftsattes:

| Ingrediens | Rader |
|---|---|
| Tomatpuré (msk) | 18 |
| Sirap (msk) | 6 |
| Currypasta (msk) | 3 |
| Sambal oelek (tsk) | 3 |

Alla är samma sak: ett volymmått mot en gramförpackning för en tjock pasta
eller sirap. Ingen är en torr krydda, så F5-regeln gäller rätt.

**Sökt verifierat underlag och inte hittat något.** Livsmedelsverkets
[PM 2024 *Volymvikter, viktförändringsfaktorer och avfall*](https://www.livsmedelsverket.se/globalassets/publikationsdatabas/pm/2024/pm-2024-volymvikter-viktforandringsfaktorer-och-avfall.pdf)
innehåller uppmätta gramvikter per tsk/msk/dl - men **ingen av de fyra
finns med**. Alltså saknas underlag, och då ska raderna förbli osäkra.
Att härleda en densitet ur ketchup eller ur eget omdöme vore att gissa.

**Följden: revisionen är röd med rätta och förblir det.** Grinden kräver
`estimat = 0`, och Matjakt kan i dag inte prissätta "2 msk tomatpuré"
exakt. Det är ett sant besked, inte ett fel.

**Ägarbeslut som behövs:** ska en känd och korrekt märkt osäkerhet blockera
releasegrinden? I dag kan grinden aldrig bli grön så länge något recept
mäter en tät vara i msk. Alternativet är att recepten anger gram - det är
receptdata, alltså ditt innehåll, inte prislogik.

**Sidofynd med källa:** samma PM anger **tomatketchup till 18 g/msk**
(n=20). Koden behandlar ketchup som 1 g/ml i `DAIRY_DENSITY_ONE`, alltså
15 g - 17 % för lågt. Verifierat underlag finns alltså här, till skillnad
från de fyra ovan. Inte ändrat: det påverkar priser och hör till samma
beslut som raden ovan.

## Dubbla rader för samma vara

Kassen i en verklig E2E-körning innehöll `Tomatpuré` **två gånger**.
Aggregatet nycklar på namn + enhetsfamilj och vägrar summera msk med gram -
avsiktligt, med motiveringen "2 st morötter plus 400 g morötter är inte
402 st". Följden är ändå en lista som ber dig köpa två tuber.

Dubbelraden och den osäkra raden har SAMMA rot: ingen densitet för
tomatpuré. Löser man den ena löser man båda.

## Gjort i den här sessionen

| Vad | PR | Verifiering |
|---|---|---|
| Jämförpris räknades som förpackningspris (Hemköp 6–18× fel) | #4 mergad | Bekräftat på 16 varor i produktion; fixen live-verifierad |
| Publiceringsgrindens 95 %-gräns testad vid kanten | #6 mergad | 94,9 % nekas, 95,0 % publiceras, last-good behålls |
| Cachade priser bär tolkningens version | #7 mergad | Gamla felpriser serveras inte längre i sex timmar efter en fix |
| ICA/Coop dagligen via Primat | #5 mergad | `RELEASED_CHAINS` orörd — kedjorna blir inte publika av sig själva |
| F5: kryddgenvägen gällde honung | #13 **mergad** | 2 msk honung fick "1 paket, exakt" mot 15 g |
| F4: "billigaste butiken" var oftast vald | #14 **mergad** | Osant påstående i UI rättat, dedupe per vecka |
| F3: kassans ålder från använda rader | #15 **mergad** | En färsk rad nollställde inte längre kassens ålder |
| Revisionen namnger vad som är osäkert | #16 **mergad + driftsatt** (`6f8f2f4`) | Rubriken kunde säga "alla system fungerar" över ett rött kort. Två tester i båda riktningarna |
| U01: budgeten säger vad den räcker till | #17 **mergad**, ej verifierad i produktion | "Veckobudget" lästes rimligen som all mat. Verifierad i webbläsare, mobil |
| U06: veckans antaganden syns och går att lägga till | #21 **öppen** (#18 stängdes när dess basgren togs bort) | Appen antog tyst ris, smör och socker. Sju tester |
| Kampanjtorget med bilder och hero | #12 **mergad** | Bilden bär aldrig budskapet |
| Driftstatus i kontrollrummet | #11 **mergad** | Verifierad i webbläsare, desktop + mobil |
| health visar om larmen går att skicka | #10 **mergad** | Live: mottagare och transport bekräftade |
| Driftstatus + larm med dedupe och recovery | #8 **mergad** | 21 tester; ett av dem hittade att en API-nyckel kunde mejlas i klartext |
| F1: ofullständig kasse krönas inte | #9 **mergad** | Regressionstest med exakt scenariot ur granskningen |

## E2E-fallen — OLÖST

Orsaken är inte funnen. Posten står kvar som olöst tills det finns ett
reproducerbart fall och en verifierad förklaring.

**Tre slutsatser jag har dragit och tagit tillbaka.** Att fixturen tappade
prissättningen (fel). Att fixturens enhetsval var orsaken (fel, och
formulerat som avgjort). Att Free-gaten räknade på fel korg (fel, mätt:
ingen effekt).

**Vad modelleringen visar och inte visar.** Täckning för 20 000 slumpade
veckor per storlek, aggregerat med appens egen nyckel (namn + enhetsfamilj),
ger ingen vecka under 85 %; sämsta är 87,5 % för två recept. Det
**utesluter ingenting** - modellen antog likformigt slumpade recept, en
kedja, inga extravaror, inget skafferi, ingen portionsskalning och ingen
tidsaspekt, och den återskapade aldrig den felande resan. Rätt formulering
är **inte reproducerat i det modellerade urvalet**.

**Konstaterat i kod, inte antaget:**

- `coveragePercent` räknar EXAKTA rader, inte prissatta (`price_list`).
- Skafferitäckta rader hoppas över före `requested = len(matched) +
  len(missing)` (`pricing.py:1650`) - skafferiet sänker inte nämnaren.
- Veckan är slumpad: `everydayRank` (`app.js:902`).
- Premiumtestet, det som faller, tar inte bort varor och rör inte skafferiet.
- En verklig grön körning visade 20 av 21 exakta rader (95,2 %). Den
  felande CI-körningen visade 16 av 19 (84,2 %). **Receptbanken ensam kan
  inte ge det** enligt modellen ovan - men modellen är inte verkligheten.

**Verktygen finns nu på plats:**

- Diagnosen skriver ut begäran OCH svar per anrop, i anropsordning, med
  recept-id, personer, mängder, enheter, skafferiavdrag, butiksval och
  vilka rader som är osäkra respektive saknade. Kroppen läses direkt vid
  svaret - annars kastar Playwright bort den vid nästa navigering, och just
  de tidiga anropen gick inte att läsa.
- Fälten är whitelistade, inte svartlistade, så inga tokens eller
  personuppgifter kan följa med. Testat.
- Ett frö per körning skrivs ut vid fel. Mätt räckvidd: samma frö ger samma
  FÖLJD av veckor, men körningar kan hamna ur fas om antalet prisanrop
  skiljer sig. Uppspelning blir trolig, inte garanterad; det exakta urvalet
  står i diagnosens `recipeIds`.

**Nästa steg:** vänta in ett verkligt fall och läsa diagnosen. Höj inte
timeouten och sänk inte kvalitetskravet.

## Mergat, driftsatt och verifierat är tre olika saker

Kontrollerat mot GitHub och `/api/health` 2026-09-08:

| | Läge |
|---|---|
| Mergade till `main` | #16, #17, #19, #20 |
| Faktiskt driftsatt | `6f8f2f4` — innehåller #16, #17, #19, #20 |
| Öppen | #21 (U06) — **blockerande fynd, se nedan** |
| Stängd utan merge | #18 — basgrenen togs bort vid mergen av #17; ersatt av #21 |
| Verifierat i produktion | Bara #16: `estimatPerIngrediens` svarar live. #17 är driftsatt men inte kontrollerad mot riktig trafik |

## Blockerande fynd: en tillagd extravara får ofta inget pris

Gäller alla extravaror, även de som skrivs in för hand - inte något U06
införde, men U06 gör vägen ett tryck lång.

`syncExtraMatches` prissätter varje extravara som **1 st**. En vara som
säljs i gram eller milliliter går inte att räkna om från styck, så
`price_list` markerar raden osäker och nollar `totalCost` enligt regeln om
säkra totaler - och klienten filtrerar bort rader utan total
(`item.totalCost != null`). Raden visas som "Ingen säker prismatch – egen
rad" och bidrar med 0 kr.

**Mätt mot fixturen: 13 av 35 antagna hemmavaror hamnar där** - Olivolja,
Smör, Vetemjöl, Ris, Honung, Sirap, Parmesan, Ströbröd, Sesamfrön,
Ingefära, Paprikapulver, Spiskummin, Ättika.

Vad som INTE är orsaken: en hypotes om att Free-gaten räknade på fel korg
(`_free_chain_for` över enbart extravarorna). Den byggde jag och mätte:
**8 gröna av 10 före ändringen, 8 av 10 efter** - alltså ingen effekt.
Ändringen är återtagen. Betalväggskod ska inte ändras på en gissning.
`_pricing_items` slår dessutom redan ihop `recipeIds` med `items`, så
gaten ser veckan när klienten skickar med den.

Kvar att avgöra: vad "1 st" ska betyda för en förpackad vara. Motorn kan
inte skilja "1 st gul lök" (en styckvara) från "1 st flaska olja" (en
förpackning), och att gissa fel åt något håll ger fel pris. Det är ett
riktigt designval, inte en bugg att slarva bort.

## O10b: de trettio osäkra raderna - underlag saknas

De verkliga raderna, lästa ur `/api/health` efter att #16 driftsattes:

| Ingrediens | Rader |
|---|---|
| Tomatpuré (msk) | 18 |
| Sirap (msk) | 6 |
| Currypasta (msk) | 3 |
| Sambal oelek (tsk) | 3 |

Alla är samma sak: ett volymmått mot en gramförpackning för en tjock pasta
eller sirap. Ingen är en torr krydda, så F5-regeln gäller rätt.

**Sökt verifierat underlag och inte hittat något.** Livsmedelsverkets
[PM 2024 *Volymvikter, viktförändringsfaktorer och avfall*](https://www.livsmedelsverket.se/globalassets/publikationsdatabas/pm/2024/pm-2024-volymvikter-viktforandringsfaktorer-och-avfall.pdf)
innehåller uppmätta gramvikter per tsk/msk/dl - men **ingen av de fyra
finns med**. Alltså saknas underlag, och då ska raderna förbli osäkra.
Att härleda en densitet ur ketchup eller ur eget omdöme vore att gissa.

**Följden: revisionen är röd med rätta och förblir det.** Grinden kräver
`estimat = 0`, och Matjakt kan i dag inte prissätta "2 msk tomatpuré"
exakt. Det är ett sant besked, inte ett fel.

**Ägarbeslut som behövs:** ska en känd och korrekt märkt osäkerhet blockera
releasegrinden? I dag kan grinden aldrig bli grön så länge något recept
mäter en tät vara i msk. Alternativet är att recepten anger gram - det är
receptdata, alltså ditt innehåll, inte prislogik.

**Sidofynd med källa:** samma PM anger **tomatketchup till 18 g/msk**
(n=20). Koden behandlar ketchup som 1 g/ml i `DAIRY_DENSITY_ONE`, alltså
15 g - 17 % för lågt. Verifierat underlag finns alltså här, till skillnad
från de fyra ovan. Inte ändrat: det påverkar priser och hör till samma
beslut som raden ovan.

## Dubbla rader för samma vara

Kassen i en verklig E2E-körning innehöll `Tomatpuré` **två gånger**.
Aggregatet nycklar på namn + enhetsfamilj och vägrar summera msk med gram -
avsiktligt, med motiveringen "2 st morötter plus 400 g morötter är inte
402 st". Följden är ändå en lista som ber dig köpa två tuber.

Dubbelraden och den osäkra raden har SAMMA rot: ingen densitet för
tomatpuré. Löser man den ena löser man båda.

## Gjort i den här sessionen

| Vad | PR | Verifiering |
|---|---|---|
| Jämförpris räknades som förpackningspris (Hemköp 6–18× fel) | #4 mergad | Bekräftat på 16 varor i produktion; fixen live-verifierad |
| Publiceringsgrindens 95 %-gräns testad vid kanten | #6 mergad | 94,9 % nekas, 95,0 % publiceras, last-good behålls |
| Cachade priser bär tolkningens version | #7 mergad | Gamla felpriser serveras inte längre i sex timmar efter en fix |
| ICA/Coop dagligen via Primat | #5 mergad | `RELEASED_CHAINS` orörd — kedjorna blir inte publika av sig själva |
| F5: kryddgenvägen gällde honung | #13 **mergad** | 2 msk honung fick "1 paket, exakt" mot 15 g |
| F4: "billigaste butiken" var oftast vald | #14 **mergad** | Osant påstående i UI rättat, dedupe per vecka |
| F3: kassans ålder från använda rader | #15 **mergad** | En färsk rad nollställde inte längre kassens ålder |
| Revisionen namnger vad som är osäkert | #16 **mergad + driftsatt** (`6f8f2f4`) | Rubriken kunde säga "alla system fungerar" över ett rött kort. Två tester i båda riktningarna |
| U01: budgeten säger vad den räcker till | #17 **mergad**, ej verifierad i produktion | "Veckobudget" lästes rimligen som all mat. Verifierad i webbläsare, mobil |
| U06: veckans antaganden syns och går att lägga till | #21 **öppen** (#18 stängdes när dess basgren togs bort) | Appen antog tyst ris, smör och socker. Sju tester |
| Kampanjtorget med bilder och hero | #12 **mergad** | Bilden bär aldrig budskapet |
| Driftstatus i kontrollrummet | #11 **mergad** | Verifierad i webbläsare, desktop + mobil |
| health visar om larmen går att skicka | #10 **mergad** | Live: mottagare och transport bekräftade |
| Driftstatus + larm med dedupe och recovery | #8 **mergad** | 21 tester; ett av dem hittade att en API-nyckel kunde mejlas i klartext |
| F1: ofullständig kasse krönas inte | #9 **mergad** | Regressionstest med exakt scenariot ur granskningen |

## E2E-fallen — OLÖST

Orsaken är inte funnen. Den här posten står kvar som olöst tills det finns
ett reproducerbart fall och en verifierad förklaring.

**Två slutsatser jag har dragit och tagit tillbaka.** Först skrev jag att
fixturen tappade prissättningen — fel. Sedan att fixturens enhetsval var
orsaken — också fel, och formulerat som om saken vore avgjord.

**Vad modelleringen faktiskt visar.** Jag räknade täckning för 20 000
slumpade veckor per storlek, aggregerat som appens lista gör, och ingen låg
under 85 %. Det **utesluter ingenting**: modellen antog likformigt slumpade
recept, en kedja, inga extravaror, inget skafferi och ingen tidsaspekt, och
den återskapade aldrig den felande resan. Rätt formulering är **inte
reproducerat i det modellerade urvalet** — receptbanken och fixturen är
fortfarande möjliga bidragande orsaker.

**Vad som är konstaterat i kod, inte antaget:**

- `coveragePercent` räknar EXAKTA rader, inte prissatta
  (`pricing.price_list`). Under `MIN_COVERAGE_FOR_COMPARISON = 85` slutar en
  kedja vara jämförbar. CI:s diagnosrad visade `16/19 = 84,2 %`.
- Skafferitäckta rader hoppas över före `requested = len(matched) +
  len(missing)` (`pricing.py:1650`), så skafferiet sänker inte nämnaren.
- Veckan är slumpad: `everydayRank` (`app.js:902`) lägger `Math.random()` på
  rankningen, avsiktligt.
- Fixturen hade två äkta defekter (`MIN(unit)` gav mjöl i literförpackning,
  msk/tsk föll till "1 st"). Rättade i PR #19.

**Hypoteser, inte slutsatser:** extravaror i kassen, hushållsrader, annan
data i CI än lokalt, och tidsberoende (två prissättningsomgångar efter
checkout). Ingen av dem är prövad mot ett verkligt felande anrop.

**Nästa steg:** PR #20 skriver nu ut vilka rader som är osäkra respektive
saknade, plus kassens innehåll. Det ska kompletteras så request och response
kopplas ihop för exakt det felande anropet. Höj inte timeouten och sänk inte
kvalitetskravet.

## Kvar för ägaren

1. **Primat App-nivå** — betalbeslut. Gratisnivån räcker inte för ICA och
   Coop samma natt.
2. **De osäkra prisraderna** — se O10b ovan. Två vägar, och de är inte lika
   bra.
3. **F6 databasincidenten** — kräver ditt godkännande för historikrensning.
