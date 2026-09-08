# Matjakt — kravmatris

> **Den auktoritativa statusen per krav finns i [`KRAVTABELL.md`](KRAVTABELL.md)**, genererad av
> `backend/scripts/kravtabell.py` med totaler räknade ur raderna. Det här dokumentet bär
> resonemangen; tabellen bär statusen. Masterinstruktionen har 127 krav (F1–F7, O1–O15,
> U01–U80, X01–X16, A01–A09); F3b och O10b är tillägg definierade under arbetet. Det finns
> inget X17 — det var ett skrivfel här som nu är rättat.

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
| F2 | Veckoval ska prissättas med riktig prismotor, inte ungefärlig kostnad | **delvis** | Felet är nu MÄTT, inte resonerat: uppskattningen ligger median +4,6 % från riktigt pris, spann −12,9 % till +19,5 % (tolv veckor mot `/api/pricing/week`). Budgetfiltret förkastar inte längre en vecka på gissningen ensam. Kvar: att VÄLJA på riktigt pris kräver den asynkrona ändringen nedan |
| F3 | Färskhet per prisrad | **klart att testa** (mergad `380a136`) | Åldern räknas nu på äldsta raden som faktiskt användes. Felet var värre än rapporterat: MAX() filtrerade bara på butik, inte på kassans varor |
| F3b | Åldersgräns på referenspriser | att göra — **kräver beslut** | `store.py:869` hämtar referenspriser utan åldersgräns, och `pricing.py:1355` släpper ett för gammalt butikspris till förmån för ett referenspris som kan vara ÄLDRE. Kräver ett beslut om maxålder |
| F4 | Skilj möjlig / planerad / genomförd besparing | **delvis, mergad** (`8103df5`) | "Billigaste butiken för dig" var läget av VALD butik - ingen prisjämförelse alls. Etiketten rättad, dedupering per vecka inlagd. Kvar: posten skrivs vid val, inte vid handling |
| F5 | Osäker enhetsgenväg får inte räknas som exakt | **klart att testa** (mergad `f320e8a`) | Regeln prövade aldrig att varan var en krydda: 2 msk honung (~42 g) fick "1 paket, exakt" mot en 15 g-burk. Räknades in i säkra totaler och gick in i billigast-jämförelsen. Revisionen fångar det inte |
| F6 | Databasincidenten i git-historiken | **blockerat** | Kräver force-push mot delad historik = ägarbeslut. Ingen destruktiv sanering utan uttryckligt godkännande |
| F7 | Skilj CI, merge och deploy | verifierat | Kontrollerat 2026-09-07: `main` `235958a` live på backend, webben v34. Den misslyckade Pages-körningen följdes av en lyckad |

---

### F2 i detalj — vad som är mätt och vad som återstår

`comboEstimatedCost` (`app.js:885`) summerar receptens separata inköpspriser
och skalar linjärt med antal personer. Talet har tre kända fel:

1. En förpackning som delas mellan två rätter räknas två gånger.
2. Kostnaden skalas linjärt med personer fast hela förpackningar inte gör det.
3. Receptens priser kommer från **olika kedjor** - 48 Willys, 7 Hemköp,
   5 City Gross i banken - men summeras ändå.

**Felet är mätt, inte uppskattat.** Tolv slumpade veckor om fyra rätter för
fyra personer, uppskattning mot `/api/pricing/week` i produktion:

| | |
|---|---|
| Median | **+4,6 %** |
| Spann | **−12,9 % till +19,5 %** |
| På 800 kr budget | upp till ~160 kr fel åt vardera hållet |

**Rättat:** `inBudgetPool` gav förut ett hårt `cost <= budget`. En vecka vars
gissning låg strax över sållades bort fast den rymdes - och den veckan fick
användaren aldrig se. Nu finns en marginal satt på den uppmätta
överskattningen. En vecka som inte ryms kan komma med, men då står dess
RIKTIGA pris på kortet innan man väljer (`syncPlanPricing`), så ingen luras.

**Mindre allvarligt än backloggen först påstod.** Jag skrev att användaren
väljer på fel grund. Kandidatveckorna prissätts redan på riktigt av
`syncPlanPricing` och det priset står på kortet före valet - användaren ser
alltså sant pris innan hen bestämmer sig. Skadan är att veckan inom varje
typ inte nödvändigtvis är den billigaste möjliga, inte att summan ljuger.

**Kvar, och det kräver fortfarande ett beslut:** att låta valet självt göras
på riktigt pris. `bestMenuCombo` är synkron och anropas från tre ställen
(`app.js:1177`, `:1237`, `:4382`). En riktig fix skiljer kandidatval från
prissättning: sålla snabbt, prissätta ett fåtal hela kassar med riktiga
motorn, välja på det. Det gör funktionen asynkron och kräver laddnings-
tillstånd i tre vyer.

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
| U04 | **verifierat** | E2E: alla fyra startval ändras i Justera veckan - personer, middagar, budget, postnummer, butik - och slår igenom både i lagringen och i gränssnittet (omfattningstexten följer med). Veckan lever kvar, ingen omladdning |
| U05 | **verifierat** | E2E bryter `/api/pricing/week` i nätlagret och kräver att beskedet "pris saknas just nu" kommer inom 45 s. Kontrollerar också att texten är fri från HTTP-koder, `undefined`, `NaN` och stacktrace, och att listan lever kvar. Felet som en gång strandade varje öppen telefon (synknyckeln låg kvar efter ett misslyckat anrop) har nu ett test |
| U06 | **verifierat** | #21 mergad och driftsatt. `står redan på listan` och `lägg till i inköpslistan` bekräftade i bundlet. Kvarstående lucka i extravarornas pris är dokumenterad, inte dold |
| Veckoplanering | U07–U18 | **delvis** — se raderna nedan |

### U07–U18 i detalj

Inventerat i koden, inte gissat:

| ID | Status | Vad som finns |
|---|---|---|
| U07 lås middagar | **att göra** | Ingen låsning finns. `pinnedBranch` gäller butik, inte rätter |
| U08 flytta mellan dagar | **att göra** | Ingen flyttfunktion |
| U09 ångra vecka | **verifierat** | E2E: skapa vecka A, skapa vecka B, återställ → A tillbaka och historiken minskad med ett. Noterat: historiken är redan icke-tom efter första veckan, eftersom appen skapar en vecka under onboardingen som planvalet sedan ersätter - "förra veckan" kan alltså vara en användaren aldrig såg |
| U10 portioner per dag | **att göra** | Portioner är ett värde för hela veckan |
| U11 återkommande favoriter | **att göra** | Favoriter finns, men ingen återkomst med paus |
| U12 nytt mot bekant | **att göra** | `recentlyEatenPenalty` finns i swap, men inget val för användaren |
| U13 egna middagar | **att göra** | Inga användarskapade recept |
| U14 gäster | **att göra** | Ingen skalning av enskild rätt |
| U15 aktiv arbetsinsats | **att göra** | Bara total tid (`maxTid`) |
| U16 köksutrustning | **att göra** | Inget utrustningsbegrepp |
| U17 säg när kraven inte går ihop | **klart att testa** | Allergier lättas ALDRIG tyst: `filterByDiet` körs först i återfallsvägen, med synonymexpansion. Ny varning när veckan blir kortare än begärt eller tom |
| U18 inställning raderar inte planen | **verifierat** | `refreshAfterSettingsChange` renderar om en vecka finns och skapar bara när ingen finns. E2E i U04 bekräftar att veckan lever kvar |
| Pengar | U19–U30 | **delvis** — se raderna nedan |

### U19–U30 i detalj

| ID | Status | Vad som gäller |
|---|---|---|
| U19 rättvisa jämförelser | **verifierat** | F1 mergad: `compare_chains` kräver identiska saknade-mängder, annars `different_baskets` |
| U20 delade förpackningar över veckan | **verifierat, mätt** | Servern aggregerar veckan före förpackningsräkningen. Två recept med Gräslök och Ägg gemensamt kostade **30,75 kr mindre** (3,1 %) prissatta tillsammans än var för sig |
| U21 kostnadsförändring före byte | **klart att testa** | Priset stod bara när man bytte FÖR att spara pengar; bytte man för tid kunde veckan bli dyrare utan ett ord. Nu står prisändringen alltid, och "Prisändring okänd" när data saknas |
| U22 jämför med vanlig butik | **att göra** | Inget begrepp för användarens vanliga butik |
| U23 butiker användaren accepterar | behöver verifieras | `storeSelectionForPricing` och `pinnedBranch` finns; urvalsregeln inte granskad |
| U24 avstånd intill prisskillnad | behöver verifieras | Avstånd visas i butikskorten; "genomförbar helhandling först" inte granskad |
| U25 medlems- och flerköpspris | **delvis** | Konservativt RÄTT: `effective_price` använder aldrig medlems- eller flerköpspris, kampanj med passerat `valid_to` faller bort, orimliga värden saneras. Ingen summa underskattas. Frivilligt medlemskap saknas — feature |
| U26 dyra engångsförpackningar | **att göra** | Ingen förklaring av varför en vara är dyr |
| U27 billigare produktval | **att göra** | Inget alternativval per vara |
| U28 extravaror separat men i totalen | **verifierat** | Egen sektion "Extra du lagt till"; `extrasCost` läggs till i handlingens total; portionspriserna kommer per recept från backend och kan strukturellt inte innehålla tvättmedel |
| U29 rättvis besparingshistorik | **verifierat** | F4 mergad: dedupering per veckonyckel |
| U30 kvarvarande mängd efter veckan | **att göra** | Ingen restmängd visas |
| I butiken | U31–U42 | **delvis** — U34/U35 verifierade, U32/U38/U40 delvis, resten features |
| Matlagning | U43–U52 | **delvis** — U43 och U52 finns, U44–U51 saknas |
| Skafferi och rester | U53–U60 | **U53 har ett mätt fel, se nedan**; U60 hanterad; resten saknas |

### U53: en okänd mängd blir ett exakt avdrag

`addLocalPantryItem` lagrar `{ amount: 1 }` när användaren bockar
"Har hemma" utan att ange mängd. Den ettan går rakt in i prissättningen
(`pantryForPricing` → `price_list`) och behandlas som ett exakt avdrag.

**Mätt med riktiga priser**, 400 g köttfärs och 2 st gul lök:

| Skafferi | Total | Kvar att köpa |
|---|---|---|
| inget | 68,00 kr | 400 g, 2 st |
| "Har hemma" → `amount: 1` | **63,50 kr** | 399 g, **1 st** |
| verklig mängd angiven | 0 kr | – |

Ett tryck på "Har hemma" utan mängd drar alltså av exakt en lök och sänker
priset 4,50 kr. Kravet säger uttryckligen att en okänd mängd inte får bli
ett exakt avdrag.

Inkonsekvensen är värre än siffran: varan markeras hanterad och lämnar den
aktiva listan, medan priset fortfarande tar betalt för den andra löken.

**Inte rättat, och det är avsiktligt.** Rätt fix beror på U55 (skilj köpt
från förbrukat) och U56 (bekräfta förbrukning innan lager minskas), som
inte finns. Utan dem flyttar en isolerad ändring bara felet: skriver vi in
veckans hela behov i skafferiet i stället, dras samma varor av igen nästa
vecka fast de är uppätna. Ändringen påverkar dessutom visade priser.
**Kräver ett ägarbeslut om hur "finns hemma" ska betyda.**
| Utseende och känsla | U61–U70 | **delvis** — U64 och U67 finns, U65 rättad, resten inventerade |

### U61–U80 i detalj

| ID | Status | Vad som gäller |
|---|---|---|
| U64 reserverad plats | behöver verifieras | 42 regler för `min-height`/`aspect-ratio`/skelett i styles.css |
| U65 bevara plats och filter | **klart att testa** | Tillbakavägen gjorde `scrollTo(0, 0)` - platsen nollställdes med FLIT. Rättat; filtren låg redan kvar i state. Exakt pixel går inte att kräva: webbläsarens scroll anchoring flyttar scrollY för att hålla bilden stilla när innehåll ovanför växer. Testet kräver att man står kvar djupt i listan, inom en skärmhöjd |
| U67 lokalt/väntar/bekräftat | behöver verifieras | `setSyncStatus` med `pending`/`Synkar…` finns |
| U68 bildrättigheter | delvis | Backend släpper bara bilder med licens (`migrate_recipes`: "An image whose licence we cannot state is an image we have no right to publish"). Frontend visar ingen kreditering |
| U71 gemensam prisdefinition | delvis | `hasUsablePrice` och `comparable` finns på ETT ställe, men i app.js - inte utbrutet som modul |
| U72 cache med rätt versioner | **verifierat** | Planen ingår i cachenyckeln (`${hasPremium() ? "premium" : "free"}\|...`), och `PARSER_VERSION` hindrar att felparsade priser återkommer ur stale-cache (PR #7) |
| U76 övervakning av importer | **verifierat** | `alerts.py` med dedupe och recovery (PR #8), `_run_ops_alerts` 07:00, `reconcile_interrupted_runs` |
| U78 fel-ID i felrapport | **att göra** | Servern loggar `rid=`, men inget når användaren |
| U79 riktiga enheter | **att göra** | Ingen fysisk enhet testad. Simulator finns byggd i `build/ios` |
| U80 databasincidenten | **blockerat** | = F6, kräver ägarbeslut om historikrensning |
| Teknik | U71–U80 | att göra (U72 delvis: cacheversion mergad i PR #7; U80 = F6, blockerat) |

## X — ytterligare produktflöden

| ID | Status | Vad som gäller |
|---|---|---|
| X02 vad äter vi ikväll | delvis | `cookModal` "Laga med det du har hemma" finns |
| X07 dela vecka/recept | delvis | Receptdelning och hushållsinbjudan finns; mottagarens omräknade priser inte granskade |
| X12 byt rätt med avsikt | **verifierat** | Fem avsikter (billigare, snabbare, barnvänligare, mer protein, använd hemma) matchar kravet, och kostnadsdeltat visas alltid sedan U21 - "Prisändring okänd" när data saknas |
| X14 erbjudanden | delvis | Kampanjtext per rad och kampanjtorg finns |
| X15 påminnelse | delvis | Notiskod finns; plattformsstöd och tillstånd inte granskade |
| X16 köp hela listan | **blockerat, korrekt dokumenterat** | `cart.py` bär de fyra nivåer kravet namnger och säger själv "FÖRBEREDELSE, inte en färdig funktion". Registret är tomt på riktiga providers därför att ingen kedja har avtalad väg in. Tester finns som hindrar att den ljuger: en kedja får inte påstå mer än en hemsidelänk, och ett resultat är komplett bara när ingenting lämnats kvar |
| X01, X03–X06, X08–X11, X13 | att göra | Features |

## A — ägarpanelen utöver Operations

| ID | Status | Vad som gäller |
|---|---|---|
| A01 översikt | **klart att testa** | Tratten räknade EN boolean, så en inlöst kod och en betalande prenumerant blev samma siffra. Nu skiljs `premiumBetalande`, `premiumKompenserad` och `premiumProv` åt, och kontrollrummet visar dem var för sig. Datan fanns redan i kontomodellen - bara sammanslagen |
| A06 ekonomi | **blockerat** | Kräver verifierad betaldata. Ingen intäktssiffra får härledas ur antal Premium × pris - uppdelningen i A01 är konton, inte kronor |
| A02–A05, A07–A09 | att göra | |

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

**Sidofynd med källa - ketchupen åtgärdad efter ägarbeslut 2026-09-08.**

Källa, exakt: Livsmedelsverkets PM 2024, **tabell 10 på sidan 16**,
"Vikter (gram) för olika enheter av majonnässallader, röror och andra
tillbehör", raden **"Tomatketchup"**. Uppmätt **tsk 6 g (n=20)** och
**msk 18 g (n=20)**; dl-kolumnen är TOM. Referens 1 = myndighetens egna
volymviktsförsök 2022-23.

Båda mätningarna ger samma tal - 6/5 = 1,20 och 18/15 = 1,20 - så ett
msk-recept och ett tsk-recept får exakt samma vikt, och 1 msk = 3 tsk går
ihop. Inga motstridiga omräkningsvägar. **1 dl = 120 g är en extrapolering**
från samma densitet, inte en mätning, och det står i koden.

Ett uppmätt genomsnitt över 20 vägningar är en **omräkningsgrund**, inte ett
löfte om att just den flaskan väger så. Paketräkningens tillförlitlighet och
prisets tillförlitlighet är skilda saker: raden är `exactPackaging=True`
därför att enheterna GÅR att räkna om, medan `priceTier` svarar för om
priset stämmer.

**Bara ketchup är ändrad.** Samma rapport har avvikande mätvärden för crème
fraiche, grekisk yoghurt, filmjölk, kvarg, mjölk, vetemjöl och havregryn.
De är inte inlagda - fyra av dem kräver ett produktval receptbanken inte
gör (fetthalt, naturell mot smaksatt). Samlade med källa, produktfråga och
konsekvens i **`docs/VOLYMVIKTER_ATT_GRANSKA.md`**.

## Dubbla rader för samma vara

Kassen i en verklig E2E-körning innehöll `Tomatpuré` **två gånger**.
Aggregatet nycklar på namn + enhetsfamilj och vägrar summera msk med gram -
avsiktligt, med motiveringen "2 st morötter plus 400 g morötter är inte
402 st". Följden är ändå en lista som ber dig köpa två tuber.

Dubbelraden och den osäkra raden har SAMMA rot: ingen densitet för
tomatpuré. Löser man den ena löser man båda.

**Följdverkan, hittad när main blev röd 2026-09-08.** `removeShoppingItem`
nycklar på NAMNET, medan aggregatet ger en rad per namn *och* enhetsfamilj.
Ett klick på × tar därför bort alla rader med det namnet. Bevisat
deterministiskt: fyra rader blev två när en vara togs bort.

Avsikten är rimlig - "jag behöver inte tomatpuré" gäller båda raderna - men
två saker skaver. UI:t säger "1 borttagen vara" fast två rader försvann,
och den som bara ville stryka msk-raden kan inte det.

Rätt fix är densiteten, inte borttagningen: med ett uppmätt värde blir det
en rad och frågan upphör. Tomatpuré saknas i Livsmedelsverkets tabell, så
den får vänta. Frontendens aggregat känner inte till backendens
`VERIFIED_DENSITY_G_PER_ML` - att dela den vore ett eget steg.

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

**Sidofynd med källa - ÅTGÄRDAT efter ägarbeslut 2026-09-08.** Samma PM
väger flera av de varor motorn antog 1 g = 1 ml för. `VERIFIED_DENSITY_G_PER_ML`
bär nu de uppmätta värdena, med n i kommentaren per rad:

| Vara | Antaget | Uppmätt | n |
|---|---|---|---|
| Tomatketchup | 1,00 | **1,20** | 20 |
| Crème fraiche | 1,00 | **0,95** | 10 |
| Grekisk yoghurt | 1,00 | **1,08** | 10 |
| Filmjölk | 1,00 | **1,10** | 20 |
| Kvarg | 1,00 | **1,11** | 10 |
| Mjölk | 1,00 | **0,98** | 20 |
| Vetemjöl | 60 g/dl | **56 g/dl** | 50 |
| Havregryn | 35 g/dl | **39 g/dl** | 30 |

Effekten syns först vid förpackningsgränsen, och går åt BÅDA hållen:

| Fall | Antaget 1,0 | Uppmätt | Varför |
|---|---|---|---|
| 5 dl ketchup | 24,90 | **49,80** | väger 600 g, ryms inte i 500 g |
| 2,05 dl crème fraiche | 37,00 | **18,50** | väger 195 g, ryms i 200 g |
| 4,7 dl grekisk yoghurt | 22,00 | **44,00** | väger 508 g, ryms inte i 500 g |
| 10,1 dl mjölk | 29,80 | **14,90** | väger 990 g, ryms i litern |

Varor källan SAKNAR behåller 1,0 via `DAIRY_DENSITY_ONE` - senap, majonnäs,
sriracha, gräddfil, keso. Ett antagande vi vet om är bättre än en siffra
som ser mätt ut. De fyra osäkra (tomatpuré, sirap, currypasta, sambal
oelek) står kvar som osäkra, och revisionen är fortsatt röd med rätta.

## Dubbla rader för samma vara

Kassen i en verklig E2E-körning innehöll `Tomatpuré` **två gånger**.
Aggregatet nycklar på namn + enhetsfamilj och vägrar summera msk med gram -
avsiktligt, med motiveringen "2 st morötter plus 400 g morötter är inte
402 st". Följden är ändå en lista som ber dig köpa två tuber.

Dubbelraden och den osäkra raden har SAMMA rot: ingen densitet för
tomatpuré. Löser man den ena löser man båda.

**Följdverkan, hittad när main blev röd 2026-09-08.** `removeShoppingItem`
nycklar på NAMNET, medan aggregatet ger en rad per namn *och* enhetsfamilj.
Ett klick på × tar därför bort alla rader med det namnet. Bevisat
deterministiskt: fyra rader blev två när en vara togs bort.

Avsikten är rimlig - "jag behöver inte tomatpuré" gäller båda raderna - men
två saker skaver. UI:t säger "1 borttagen vara" fast två rader försvann,
och den som bara ville stryka msk-raden kan inte det.

Rätt fix är densiteten, inte borttagningen: med ett uppmätt värde blir det
en rad och frågan upphör. Tomatpuré saknas i Livsmedelsverkets tabell, så
den får vänta. Frontendens aggregat känner inte till backendens
`VERIFIED_DENSITY_G_PER_ML` - att dela den vore ett eget steg.

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

## Kvar för ägaren

1. **Primat App-nivå** — betalbeslut. Gratisnivån räcker inte för ICA och
   Coop samma natt.
2. **De osäkra prisraderna** — se O10b ovan. Två vägar, och de är inte lika
   bra.
3. **F6 databasincidenten** — kräver ditt godkännande för historikrensning.
