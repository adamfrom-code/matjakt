# Kravtabell — en rad per krav, totaler räknade ur raderna

Genererad av `backend/scripts/kravtabell.py`. **129 krav**: masterinstruktionens 127 plus två tillägg (F3b, O10b). Skriptet vägrar skriva om ett ID saknas, dubbleras eller inte finns i instruktionen.

## Totaler

| Status | Antal |
|---|---:|
| verifierat | 9 |
| klart att testa | 14 |
| delvis | 24 |
| behöver verifieras | 5 |
| kräver beslut | 3 |
| blockerat | 4 |
| att göra | 70 |
| **summa** | **129** |

**Färdiga (verifierat): 9 av 129.** 'Klart att testa' räknas inte som färdigt.

Verifierat i produktion = JA bara när något faktiskt lästes från matjakt.onrender.com eller matjakt.store efter deploy.

## Tilläggen, definierade

- **F3b** — Tillagt under F3-arbetet: referenspriser hämtas utan åldersgräns (store.py:869), och pricing.py:1355 kan ersätta ett för gammalt butikspris med ett ÄLDRE referenspris. Kravet: en maxålder även för referenspriser.
- **O10b** — Tillagt under O10-arbetet: prisrevisionen är röd på korrekt märkt osäkerhet (30 rader utan verifierad densitet). Kravet: besluta om sådan osäkerhet ska blockera releasegrinden, eller om grinden ska mäta den separat.

## Motsägelser som är utredda

- **U20 mot F2.** Prissättningen av en *vald* vecka aggregerar delade förpackningar (mätt). *Valet* av vecka gör det inte. U20 är därför `delvis`, inte verifierat, tills F2:s asynkrona val finns.
- **U06.** Synliga antaganden och fungerande tilläggsknapp är verifierade. Korrekt mängd och pris är det inte: raden får `qty 1` utan enhet, 13 av 35 hemmavaror får inget pris som extravara, och extravaror ingår inte i butiksjämförelsen. Därför `delvis`.
- **F3/U72.** Verifierat: kassans ålder räknas på använda rader, cachenyckeln bär planen, PARSER_VERSION hindrar felparsade priser. Inte verifierat: färskhet på *referensrader* — F3b blockerar, eftersom referenspriser hämtas utan åldersgräns.
- **Blockeringar.** Varje blockerad rad skiljer den blockerade delen (kolumnen 'återstår') från det som gjorts eller kan göras självständigt (kolumnen 'fungerar').

## Olöst — får inte försvinna bakom en grön körning

- **E2E-orsaken.** Konsumentresan har fallit i CI på `16/19 = 84,2 %` täckning. Tre slutsatser dragna och tillbakatagna. 20 000 modellerade veckor **utesluter ingenting** — *inte reproducerat i det modellerade urvalet*. Diagnosen skriver nu ut begäran och svar per anrop och väntar på nästa verkliga fall.
- **'1 st' för en förpackad vara.** 13 av 35 hemmavaror får inget pris när de läggs till.

## Tabellen

| ID | Krav | Status | Fungerar | Återstår | Test/bevis | PR/commit | Prod |
|---|---|---|---|---|---|---|---|
| F1 | Ofullständig kasse får inte krönas billigast | klart att testa | compare_chains kräver identiska saknade-mängder, annars different_baskets | Bekräfta i produktion att ingen kröning sker vid olika kassar | Regressionstest med granskningens exakta scenario | #9 9d68f48 | NEJ |
| F2 | Veckoval på riktig prismotor, inte uppskattning | delvis | Felet MÄTT mot produktion: median +4,6 %, spann −12,9…+19,5 %. inBudgetPool förkastar inte på gissning ensam. syncPlanPricing visar riktigt pris FÖRE valet | Själva valet sker på comboEstimatedCost (dubbelräknar delade förpackningar, blandar kedjor). Asynkron bestMenuCombo krävs | planning.test.js (3), mätning mot /api/pricing/week | #25 37b876c | NEJ |
| F3 | Färskhet per prisrad | klart att testa | Kassans ålder = äldsta raden som faktiskt användes (min över verifiedAt/fetchedAt) | Referensprisvägen saknar åldersgräns - se F3b. Ett för gammalt butikspris kan ersättas av ett äldre referenspris | Enhetstest: en färsk rad nollställer inte kassens ålder | #15 380a136 | NEJ |
| F3b | Åldersgräns på referenspriser (tillägg) | kräver beslut | Problemet är lokaliserat: store.py:869 och pricing.py:1355 | BLOCKERAT: maxålderns värde är ett ägarbeslut. SJÄLVSTÄNDIGT MÖJLIGT: rörledningen (ålder på referensrader, flagga i svaret) kan byggas nu | — | — | NEJ |
| F4 | Skilj möjlig/planerad/genomförd besparing | delvis | Etiketten 'Billigaste butiken' (var = vald butik) rättad till 'Oftast vald butik'; en post per vecka | Posten skrivs vid VAL, inte vid genomförd handling | savings-log.test.js | #14 8103df5 | NEJ |
| F5 | Osäker enhetsgenväg får inte räknas som exakt | klart att testa | DRY_SPICES: bara torra kryddor får 30 ml ≤ 15 g-regeln. 2 msk honung är inte längre '1 paket exakt' | Konsekvensen är synlig i produktion (revisionen röd på 30 ärliga rader) - det är rätt, men O10b avgör vad som händer sen | Enhetstester | #13 f320e8a | JA - revisionen visar exakt de rader F5 avslöjade |
| F6 | Databasincidenten i git-historiken | blockerat | Inget | BLOCKERAT: force-push mot delad historik kräver ägarbeslut. SJÄLVSTÄNDIGT: inget - all sanering är destruktiv | — | — | NEJ |
| F7 | Skilj CI, merge och deploy | verifierat | Deploygrinden 'bara grön main' höll när main var röd: #32 låg mergad men odeployad tills #33 gjorde main grön. health.commit och revisionens egen commit skiljer versionerna | — | Observerat live 2026-09-08 12:00-12:42 | — | JA |
| O1 | Driftstatus som adminförstasida | klart att testa | Sex systemkort + rubrik som väger in revisionen (rubriken sa förut 'alla system fungerar' över ett rött kort) | Se den mot riktig produktionsdata i kontrollrummet | Browser mot fixtur, desktop + 375 px | #11 d9aab36, #16 b0e1202 | NEJ |
| O2 | Rad per kedja: health, released, scope, ålder, gate | klart att testa | chain_health() med healthy/stale/failed/limited/never_imported/ready_for_release; skilda kolumner | Kontroll mot riktig data | 9 enhetstester | #8 745d37e | NEJ |
| O3 | ICA/Coop: visa ej släppt, schema, ingen snapshot | delvis | Dagligt schema 05:30/06:30 mergat; RELEASED_CHAINS orörd | Ingen import har någonsin körts - täckning 'ej verifierat' | — | #5 235958a | NEJ |
| O4 | Lidl som Limited med orsak | delvis | limited-status finns och larmar aldrig | Orsakstexten i adminvyn inte kontrollerad | — | #8 | NEJ |
| O5 | Aktiva incidenter med kundpåverkan | klart att testa | overview(): per öppen incident vad är fel / påverkas kunder / vad göra; kundpåverkan ur släppt + ålder mot serveringsregeln, 'okänd' utan underlag; limited blir aldrig incident; kortet Incidenter i kontrollrummet | Kontroll mot en riktig incident i produktion; 'senaste försök' visas ur panelen men snapshot-serveringen är härledd ur regeln, inte observerad | 7 nya + 1 uppdaterat test; browser 375 px | #39 | NEJ |
| O6 | Incidenthistorik, persistenta ID, dedupe | klart att testa | Tillstånd skrivs oavsett mejl; mejlstatus sent/failed/not_configured/pending sanningsenligt; recovery arkiverar start/recovery/duration/mejlstatus även om kvittot misslyckas; 50 poster i databasen, överlever omstart; cooldown bara för larm som gått ut | Kontroll mot riktig drift över tid | test_grocery_alerts.py (21) | #8, #39 | NEJ |
| O7 | Admin-mail: mottagare/transport/försök/leverans | delvis | recipientConfigured + transportConfigured + domän i health | Senaste skickförsök och faktisk leverans saknas | Live-läst adminAlerts | #10 6052735 | JA (delen som finns) |
| O8 | Primat: configured JA/NEJ, kvot ur verklig API-data | delvis | FINNS: /api/admin/primat-status svarar configured JA/NEJ utan nyckeln och anropar Primats GET /me (plan, dagsbudget, använda rader, reset) - rättelse: jag skrev tidigare att ingen kvot-endpoint fanns | VISAS INTE: ingenting i kontrollrummet läser endpointen. OVERIFIERAT: att /me svarar med de fälten mot det riktiga kontot - kräver admin-token. Varning nära gräns finns inte. Köp/uppgradering = ägarbeslut | Kodläsning primat_client.account_status | — | NEJ |
| O9 | Scheduler: schema, körningar, nästa körning | delvis | Operations-koll 07:00 med test att den ligger efter importerna | Faktiska körningar och nästa körning i adminvyn | 1 test | #8 | NEJ |
| O10 | Pricing audit med definierade nämnare | delvis | Auditen körs vid start + efter import, namnger osäkra rader per ingrediens, rubriken i admin visar felet | Live-parsningsvägen granskas inte av auditen. Vad som händer med de 30 raderna = O10b | Enhetstester i båda riktningarna; live-läst | #16 b0e1202 | JA |
| O10b | Beslut om korrekt märkt osäkerhet i grinden (tillägg) | kräver beslut | Ketchup fick verifierad densitet (LV tabell 10 s.16). Tomatpuré, sirap, currypasta, sambal oelek saknas i källan | BLOCKERAT: ska osäkerhet blockera grinden, eller mätas separat? SJÄLVSTÄNDIGT: ingen mer densitet utan källa | — | #34 (öppen) | NEJ |
| O11 | Deploy: commit, tider, avvikelse | delvis | health.commit; revisionen bär sin egen commit | Jämförelse mot förväntad deploy saknas | — | #16 | JA (fälten finns) |
| O12 | Skyddat admin-API, inte bara dold knapp | behöver verifieras | _admin_ok() finns på endpointerna | Negativa tester för hushållsmedlem saknas | — | — | NEJ |
| O13 | Mobilanpassad admin | klart att testa | Under 720 px: Kedjor-tabellen (13 kolumner, 1 424 px) ritas som kort per kedja; knappar min 44 px; sidscroll med synlig kant | Kontroll på riktig telefon (U79) och mot produktionsdata | Mätt i browser: 375 px före/efter, 1 280 px utan regression | #36 | NEJ |
| O14 | Testlista för Operations | delvis | 21+ tester (chain_health 9, alerts 12) | Samlad lista saknas | — | #8 | NEJ |
| O15 | Active stores + kvotmonitorering | delvis | BUTIKER: fyra skilda tal per kedja (i registret / aktiva / färska ≤ 4 dygn / kundtillgängliga = färska i släppt kedja) med källa och mättid, visade i kontrollrummet | KVOT: se O8 - endpointen finns men visas inte och är overifierad mot kontot. Butikstalen är inte kontrollerade mot produktionsdata | 4 enhetstester; browser 375 + 1 280 px | #37 | NEJ |
| U01 | Förklara budgetens omfattning | verifierat | 'Gäller 4 middagar för 2 personer. Frukost, lunch och hushållsvaror ingår inte.' i onboarding + Justera veckan, aria-label på hemkortet | — | budget-scope.test.js (4), browser 375 px | #17 fc97052 | NEJ |
| U02 | Nytta före kontokrav; bevara gästens plan | verifierat | Gäst får prissatt vecka; planen överlever kontoskapande | — | E2E | #22 560cbbf | NEJ |
| U03 | Minimal start, mät tid till första listan | delvis | Mäts i E2E: 2,1-2,7 s till första användbara listan | Mätt i testmiljö, inte med riktiga användare - målet 'ungefär en minut' är inte påstått uppnått | E2E skriver ut måttet | #23 fea9fb6 | NEJ |
| U04 | Ändra felaktiga startval utan omstart | verifierat | Justera veckan ändrar utan att radera planen | — | E2E | #24 6f06428 | NEJ |
| U05 | Begriplig väntestatus | verifierat | 'pris hämtas…' skiljs från 'pris saknas just nu'; prisfel ger besked | — | E2E | #24 6f06428 | NEJ |
| U06 | Visa antagna hemmavaror, erbjud tillägg | delvis | SYNLIGT + KNAPP: veckans antaganden listas, deduplicerade; tillägg via addExtraItem; en vara på listan erbjuds inte igen (21 namn är både antagna och köpta); tomt skafferifack räknas inte som hemma | MÄNGD: raden får qty 1 utan enhet - receptet bär ingen mängd för hemmavaror. PRIS: 13 av 35 hemmavaror får inget pris som extravara; Free-gaten svarar 403 i ~1 av 5 fall och klienten sväljer det. JÄMFÖRELSE: extravaror ingår i totalen men inte i butiksjämförelsen | assumed-home.test.js (10), E2E med betalväggskontroll | #21 15299fd | JA (strängen 'står redan på listan' i live-bundlet) |
| U07 | Lås middagar, byt resten | att göra | — | Ingen låsfunktion | — | — | NEJ |
| U08 | Flytta middagar mellan dagar | att göra | — | — | — | — | NEJ |
| U09 | Ångra vecka, bevara förra | verifierat | weekHistory + Återställ förra veckan. Noterat: historiken är icke-tom redan efter första veckan (onboardingen skapar en) | — | E2E: A → B → återställ → A, historiken minskad med ett; 5 körningar | #28 bc48d6f | NEJ |
| U10 | Olika portioner per dag | att göra | — | — | — | — | NEJ |
| U11 | Återkommande favoriter med paus | att göra | — | — | — | — | NEJ |
| U12 | Nytt mot bekant, lagom upprepning | att göra | — | — | — | — | NEJ |
| U13 | Egna middagar med strukturerade ingredienser | att göra | — | — | — | — | NEJ |
| U14 | Gäster: skala rätt, visa extra inköp | att göra | — | — | — | — | NEJ |
| U15 | Aktiv arbetsinsats, inte bara total tid | att göra | — | — | — | — | NEJ |
| U16 | Köksutrustning | att göra | — | — | — | — | NEJ |
| U17 | Säg när budget/kost/utbud inte går ihop; lätta aldrig på allergier | klart att testa | Varning när kraven inte går ihop; allergener lättas aldrig tyst | Kontroll mot riktig trafik | plan-warning.test.js, E2E | #26 ab0b84e | JA (strängen i live-bundlet) |
| U18 | Ändrad inställning raderar inte planen | verifierat | refreshAfterSettingsChange behåller valda | — | E2E | #24 | NEJ |
| U19 | Rättvisa jämförelser (= F1) | klart att testa | Se F1 | Se F1 | Se F1 | #9 | NEJ |
| U20 | Optimera delade förpackningar (= F2) | delvis | PRISSÄTTNINGEN av en vald vecka aggregerar före paketräkning: två recept med Gräslök+Ägg kostade 30,75 kr (3,1 %) mindre tillsammans | VALET av vecka gör det inte - comboEstimatedCost summerar per recept. Fullt uppfyllt först med F2:s asynkrona val | Mätning mot fixtur | — | NEJ |
| U21 | Kostnadsförändring före receptbyte; ange saknad data | klart att testa | Prisändring per portion visas alltid; 'Prisändring okänd' utan data | Talet är receptets portionspris, inte veckans inköpskostnad (kräver F2) | swap.test.js (4), browser | #27 0c3f08c | JA (strängen i live-bundlet) |
| U22 | Jämför med kundens vanliga butik | att göra | — | Inget begrepp för vanlig butik | — | — | NEJ |
| U23 | Butiker användaren accepterar | behöver verifieras | storeSelectionForPricing, pinnedBranch finns | Urvalsregeln inte granskad | — | — | NEJ |
| U24 | Avstånd intill prisskillnad, helhandling först | behöver verifieras | Avstånd visas i butikskorten | 'Genomförbar helhandling först' inte granskad | — | — | NEJ |
| U25 | Frivilligt medlemskap, villkorsstyrd beräkning | delvis | Konservativt RÄTT: medlems-/flerköpspris används aldrig i totalen, passerad kampanj faller bort, orimliga värden saneras | Frivilligt medlemskap saknas (feature) | Kodläsning effective_price | — | NEJ |
| U26 | Förklara dyra engångsförpackningar | att göra | — | — | — | — | NEJ |
| U27 | Billigare godtagbara produktval | att göra | — | — | — | — | NEJ |
| U28 | Extravaror separat men i totalen; ej i portionspris | delvis | SETT I BROWSER: egen sektion 'Extra du lagt till', extrasCost i handlingens total | Portionspriset kommer per recept från backend (kodläsning) - inget test på att tvättmedel inte kan smyga in | Browser under U06-arbetet | — | NEJ |
| U29 | Rättvis besparingshistorik (= F4) | delvis | Se F4 | Se F4 | Se F4 | #14 | NEJ |
| U30 | Kvarvarande mängd efter veckan | att göra | — | — | — | — | NEJ |
| U31 | Enhandsanvändning, stora tryckytor, tydliga mängder | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U32 | Visa behov och faktiskt inköp | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U33 | Anpassningsbar kategoriordning efter butikens avdelningar | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U34 | Hämtade varor flyttas undan diskret och kan återställas | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U35 | Borttagen är inte samma sak som hemma | klart att testa | Skilda handlingar 'Har hemma' och 'Köpt'; borttagen vara går att ta tillbaka | Kontroll mot riktig trafik | E2E | #29 c6b8651 | NEJ |
| U36 | ”Varan är slut” | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U37 | Rapportera och rätta pris i den egna listan | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U38 | Senaste användbara lista offline, med tydligt väntande synk och prisdatum | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U39 | Misslyckad skrivning syns och återställs/kan försökas igen | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U40 | Två personer kan handla samtidigt utan dubbletter eller förlorade ändringar | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U41 | Egna varor får antal, anteckning, kategori och redigerbar mängd | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U42 | Avsluta handling genom att bekräfta vad som faktiskt köpts innan skafferiet up… | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U43 | Matlagningsläge med ett tydligt steg i taget och stor text | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U44 | Skalad mängd i instruktionen, exempelvis ”Tillsätt 2 dl grädde” | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U45 | Namngivna timers per relevant steg, flera samtidiga utan förväxling | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U46 | Frivilligt håll skärmen vaken, med fallback där plattformen saknar stöd | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U47 | Skilj förberedelse, aktiv tid och väntetid | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U48 | Visa möjliga förberedelser tidigare under dagen | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U49 | Enkel feedback | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U50 | Manuell/strukturerad kvalitetsgranskning av mest föreslagna recept före fler r… | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U51 | Spara egna receptanpassningar, exempelvis mindre chili | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U52 | Använd faktisk feedback i nästa veckoförslag | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U53 | Vad 'finns hemma' utan mängd betyder | kräver beslut | — | BLOCKERAT: produktdefinition. SJÄLVSTÄNDIGT: beror på U55/U56 som inte finns | — | — | NEJ |
| U54 | Fråga om relevanta varor till aktuell vecka, inte en total köksinventering | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U55 | Separera köpt och förbrukat | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U56 | Bekräfta förbrukning innan lager minskas, och hantera ändrade portioner eller … | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U57 | Lunchlådor som explicita portioner | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U58 | Planera restmiddag utan att dubbelräkna mat eller inköp | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U59 | Prioritera angivna öppnade förpackningar | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U60 | Slå ihop namn- och GTIN-registrering av samma skafferivara med säker identitet… | att göra | — | Inte inventerat i detalj | — | — | NEJ |
| U61 | En tydlig huvudhandling per vy | att göra | — | — | — | — | NEJ |
| U62 | Progressiv detaljvisning | att göra | — | — | — | — | NEJ |
| U63 | Konsekventa ord och siffror mellan Hem, Vecka, Recept och Handla | att göra | — | — | — | — | NEJ |
| U64 | Reservera plats så skärmen inte hoppar | behöver verifieras | 42 regler för min-height/aspect-ratio/skelett | Inte prövat | — | — | NEJ |
| U65 | Bevara scroll och filter efter receptdetalj | klart att testa | Tillbakavägen gjorde scrollTo(0,0) - nu återställs platsen momentant; filtren låg redan i state | Exakt pixel går inte (scroll anchoring); testet kräver kvar djupt i listan inom en skärmhöjd | E2E, verifierat att testet fångar gamla beteendet | #30 892d2b6 | NEJ |
| U66 | Större text, skärmläsare, kontrast | att göra | — | — | — | — | NEJ |
| U67 | Lokalt/väntar/bekräftat | behöver verifieras | setSyncStatus med 'Synkar…' finns | Inte prövat | — | — | NEJ |
| U68 | Bilder: rätt rätt, rättigheter, fallback | delvis | Backend släpper bara bilder med licens; kategoribaserad fallback | Ingen kreditering visas i frontend | recipe-fallback.test.js | #12 | NEJ |
| U69 | Hjälpsamma tomlägen | att göra | — | — | — | — | NEJ |
| U70 | Premium i sammanhang, inte störande | att göra | — | — | — | — | NEJ |
| U71 | Gemensam definition av pris/jämförbarhet/besparing | delvis | hasUsablePrice och comparable finns på ETT ställe | I app.js, inte utbrutet som modul | — | — | NEJ |
| U72 | Färskhet, giltighet, cache (= F3) | delvis | VERIFIERAT: cachenyckeln bär planen (free/premium); PARSER_VERSION hindrar felparsade priser ur stale-cache; kassans ålder från använda rader | Referensprisvägen saknar åldersgräns (F3b) - 'färskhet per rad' gäller därför inte referensrader | Enhetstester (#7, #15) | #7 115aa03, #15 380a136 | NEJ |
| U73 | Dela upp app.js stegvis | att göra | Fem moduler utbrutna under sessionen (budget-scope, assumed-home, savings-log, plan-warning, recipe-fallback) | app.js är fortfarande ~5 300 rader | — | — | NEJ |
| U74 | Testa nätbortfall mitt i flöden | att göra | — | — | — | — | NEJ |
| U75 | Service worker behåller vecka, blandar inte versioner | att göra | Cacheversion bumpas per release (v35→v42) | Inget test på blandade versioner | — | — | NEJ |
| U76 | Automatisk övervakning av uteblivna importer | verifierat | alerts.py med dedupe + recovery, operationskoll 07:00, reconcile_interrupted_runs; adminAlerts live | — | 12 tester; live-läst adminAlerts | #8, #10 | JA |
| U77 | Följ första vecka → lista → nästa vecka | att göra | Tratten per kohort finns i insights | Definitioner och integritet inte granskade | — | — | NEJ |
| U78 | Fel-ID i felrapport | att göra | Servern loggar rid= | Inget når användaren | — | — | NEJ |
| U79 | Testa riktiga enheter; annars redovisa | att göra | REDOVISNING: allt är browser + Playwright (390x844 mobil emulering). Ingen fysisk iPhone/Android testad. iOS-appen är byggd i build/ios | Simulatorkörning inte gjord | — | — | NEJ |
| U80 | Avsluta databasincidenten (= F6) | blockerat | Se F6 | Se F6 | — | — | NEJ |
| X01 | Jämför egen lista utan recept | att göra | — | — | — | — | NEJ |
| X02 | Vad kan vi äta ikväll? | delvis | cookModal 'Laga med det du har hemma' | Personer/tid-urval inte granskat | — | — | NEJ |
| X03 | Klistra in lista | att göra | — | — | — | — | NEJ |
| X04 | Produktval: vanligt märke/likvärdigt/lägst | att göra | — | — | — | — | NEJ |
| X05 | Förklara prisändring | att göra | — | — | — | — | NEJ |
| X06 | Liten budget: minsta att betala nu | att göra | — | — | — | — | NEJ |
| X07 | Dela användbar vecka | delvis | Receptdelning + hushållsinbjudan | Mottagarens omräknade priser inte granskade | — | — | NEJ |
| X08 | Familjen röstar | att göra | — | — | — | — | NEJ |
| X09 | Återkomst efter uppehåll | att göra | — | — | — | — | NEJ |
| X10 | Följ upp rapporterade fel | att göra | — | — | — | — | NEJ |
| X11 | Ändrade planer på dagens middag | att göra | — | — | — | — | NEJ |
| X12 | Byt rätt med avsikt, visa kostnadsdelta | verifierat | Fem avsikter (billigare, snabbare, barnvänligare, mer protein, använd hemma); kostnadsdelta alltid sedan U21 | — | swap.test.js, browser | #27 | JA (via U21) |
| X13 | Andra veckan lättare | att göra | weekHistory och favoriter finns | Återanvänd förra veckan med ändringar saknas | — | — | NEJ |
| X14 | Relevant erbjudandeflöde | delvis | Kampanjtext per rad, kampanjtorg | Villkor/giltighet inte granskade | — | #12 | NEJ |
| X15 | Frivillig påminnelse | delvis | Notiskod finns | Plattformsstöd och tillstånd inte granskade | — | — | NEJ |
| X16 | Köp hela listan | blockerat | SJÄLVSTÄNDIGT GJORT: cart.py med de fyra nivåerna, tester som hindrar den från att påstå mer än en hemsidelänk | BLOCKERAT: ingen kedja har avtalad väg in - registret är tomt med flit | 8 tester | — | NEJ |
| A01 | Översikt; skilj kompenserad från betalande | klart att testa | premiumSource (subscription/trial/comped); tratten räknar per källa; kontrollrummet visar dem | Se den mot riktiga konton | 7 tester, browser mot fixtur | #31 20a6b8a | JA (admin.js live bär 'betalande Premium') |
| A02 | Första användningen | att göra | — | — | — | — | NEJ |
| A03 | Återkomst | att göra | — | — | — | — | NEJ |
| A04 | Recept | att göra | — | — | — | — | NEJ |
| A05 | Feedback | att göra | — | — | — | — | NEJ |
| A06 | Ekonomi ur verifierad betaldata | blockerat | SJÄLVSTÄNDIGT GJORT: A01 räknar konton per källa | BLOCKERAT: kräver betaldata; ingen intäkt får härledas ur antal × pris | — | #31 | NEJ |
| A07 | Utveckling | att göra | — | — | — | — | NEJ |
| A08 | Varje uppgift | att göra | — | — | — | — | NEJ |
| A09 | Dashboarden ska hjälpa ägaren avgöra nästa åtgärd | att göra | — | — | — | — | NEJ |
