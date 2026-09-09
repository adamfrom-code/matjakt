# -*- coding: utf-8 -*-
"""Kravtabellen: exakt en rad per krav, totaler RÄKNADE ur raderna.

    python backend/scripts/kravtabell.py          -> skriver docs/KRAVTABELL.md

Skriptet vägrar skriva om ett ID saknas, dubbleras eller inte finns i
masterinstruktionen. Totalsiffror som skrivs för hand glider ifrån raderna;
de här kan inte göra det.

STATUSORD (bara dessa sju):
  verifierat         byggt, testat OCH kontrollerat i den miljö som räknas
  klart att testa    mergat och driftsatt, effekten inte kontrollerad mot
                     riktig trafik - RÄKNAS INTE SOM FÄRDIGT
  delvis             en del gjord och prövad, resten kvar
  behöver verifieras fanns i koden före sessionen; ingen har prövat att den
                     gör det den påstår
  kräver beslut      blockerad på ett ägarbeslut (produktval, gräns, kostnad)
  blockerat          blockerad på åtkomst, avtal eller destruktiv åtgärd
  att göra           inventerat, inte påbörjat

"Verifierat i produktion" = JA bara när något faktiskt lästes från
matjakt.onrender.com eller matjakt.store efter deploy."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UT = ROOT / "docs" / "KRAVTABELL.md"

STATUS = ("verifierat", "klart att testa", "delvis", "behöver verifieras",
          "kräver beslut", "blockerat", "att göra")

# Masterinstruktionens 127 krav + två tillägg som definierades under arbetet.
ORIGINAL = ([f"F{i}" for i in range(1, 8)] + [f"O{i}" for i in range(1, 16)]
            + [f"U{i:02d}" for i in range(1, 81)] + [f"X{i:02d}" for i in range(1, 17)]
            + [f"A{i:02d}" for i in range(1, 10)])
TILLAGG = {
    "F3b": "Tillagt under F3-arbetet: referenspriser hämtas utan åldersgräns (store.py:869), "
           "och pricing.py:1355 kan ersätta ett för gammalt butikspris med ett ÄLDRE referenspris. "
           "Kravet: en maxålder även för referenspriser.",
    "O10b": "Tillagt under O10-arbetet: prisrevisionen är röd på korrekt märkt osäkerhet "
            "(30 rader utan verifierad densitet). Kravet: besluta om sådan osäkerhet ska blockera "
            "releasegrinden, eller om grinden ska mäta den separat.",
}
ALLA = ORIGINAL + list(TILLAGG)

# Kravtexten ur masterinstruktionen, första meningen, för rader utan egen text.
KRAVTEXT = {
    "F1": 'Ofullständig matkasse kan utses till billigast',
    "F2": 'Veckans recept väljs med ungefärlig kostnad',
    "F3": 'En färsk rad kan dölja gamla priser',
    "F4": 'Sparhistoriken byggs vid val, inte genomförd handling',
    "F5": 'Osäker enhetsgenväg markeras exakt',
    "F6": 'Dokumenterad databasincident',
    "F7": 'CI, merge och deploy är olika saker',
    "O1": 'Driftstatus som adminförstasida',
    "O2": 'En rad eller ett kort per kedja',
    "O3": 'ICA och Coop',
    "O4": 'Lidl',
    "O5": 'Aktiva incidenter',
    "O6": 'Incidenthistorik och livscykel',
    "O7": 'Admin-mail',
    "O8": 'Primat',
    "O9": 'Scheduler',
    "O10": 'Pricing audit',
    "O11": 'Deploy',
    "O12": 'Säkert admin',
    "O13": 'Mobil och layout',
    "O14": 'Tester och verifiering',
    "O15": 'Fortsätt med active stores och quota',
    "U01": 'Förklara budgetens omfattning',
    "U02": 'Visa första veckans nytta före kontokrav där det kan göras säkert',
    "U03": 'Minimal start',
    "U04": 'Ändra felaktiga startval utan omstart',
    "U05": 'Begriplig väntestatus för planering och prishämtning',
    "U06": 'Visa vilka basingredienser som antas finnas hemma och erbjud tillägg',
    "U07": 'Lås middagar och byt resten',
    "U08": 'Flytta middagar mellan dagar utan onödig ändring av inköpslistan',
    "U09": 'Ångra skapad/ändrad vecka, bevara tidigare plan',
    "U10": 'Olika antal portioner per dag',
    "U11": 'Återkommande favoriter som fredagstacos, med paus och möjlighet att variera',
    "U12": 'Val mellan mycket nytt och mest sådant hushållet gillar',
    "U13": 'Egna middagar med egna strukturerade ingredienser, återanvändbara i planering',
    "U14": 'Gäster',
    "U15": 'Välj aktiv arbetsinsats, inte bara total tillagningstid',
    "U16": 'Ta hänsyn till tillgänglig köksutrustning',
    "U17": 'Visa när budget, kostkrav och receptutbud inte går ihop',
    "U18": 'Ändrad budget eller inställning får inte automatiskt radera användarens plan',
    "U19": 'Kompletta och rättvisa jämförelser enligt F1, samma middagar/behov mellan buti…',
    "U20": 'Optimera gemensamma förpackningar i hela veckan enligt F2',
    "U21": 'Visa verifierbar förändring i inköpskostnad före receptbyte',
    "U22": 'Jämför med kundens vanliga butik, tydlig jämförelsebas',
    "U23": 'Välj butiker användaren faktiskt accepterar, inte godtyckligt nationellt billi…',
    "U24": 'Avstånd intill prisskillnad',
    "U25": 'Frivilligt medlemskap och korrekt villkorsstyrd medlems-/flerköpsberäkning',
    "U26": 'Förklara dyra ingredienser och specialförpackningar som används en enda gång',
    "U27": 'Billigare godtagbara produktval och tydlig kostnadsskillnad',
    "U28": 'Middagsinköp och extravaror redovisas separat men ingår i handlingens total',
    "U29": 'Rättvis möjlig/genomförd besparing och deduplicerad historik enligt F4',
    "U30": 'Visa kvarvarande mängd efter veckan',
    "U31": 'Enhandsanvändning, stora tryckytor, tydliga mängder',
    "U32": 'Visa behov och faktiskt inköp',
    "U33": 'Anpassningsbar kategoriordning efter butikens avdelningar',
    "U34": 'Hämtade varor flyttas undan diskret och kan återställas',
    "U35": 'Hämtad/köpt, har hemma och borttagen är olika tillstånd',
    "U36": '”Varan är slut”',
    "U37": 'Rapportera och rätta pris i den egna listan',
    "U38": 'Senaste användbara lista offline, med tydligt väntande synk och prisdatum',
    "U39": 'Misslyckad skrivning syns och återställs/kan försökas igen',
    "U40": 'Två personer kan handla samtidigt utan dubbletter eller förlorade ändringar',
    "U41": 'Egna varor får antal, anteckning, kategori och redigerbar mängd',
    "U42": 'Avsluta handling genom att bekräfta vad som faktiskt köpts innan skafferiet up…',
    "U43": 'Matlagningsläge med ett tydligt steg i taget och stor text',
    "U44": 'Skalad mängd i instruktionen, exempelvis ”Tillsätt 2 dl grädde”',
    "U45": 'Namngivna timers per relevant steg, flera samtidiga utan förväxling',
    "U46": 'Frivilligt håll skärmen vaken, med fallback där plattformen saknar stöd',
    "U47": 'Skilj förberedelse, aktiv tid och väntetid',
    "U48": 'Visa möjliga förberedelser tidigare under dagen',
    "U49": 'Enkel feedback',
    "U50": 'Manuell/strukturerad kvalitetsgranskning av mest föreslagna recept före fler r…',
    "U51": 'Spara egna receptanpassningar, exempelvis mindre chili',
    "U52": 'Använd faktisk feedback i nästa veckoförslag',
    "U53": 'Snabb registrering ”finns hemma” och detaljerad mängd/förvaring',
    "U54": 'Fråga om relevanta varor till aktuell vecka, inte en total köksinventering',
    "U55": 'Separera köpt och förbrukat',
    "U56": 'Bekräfta förbrukning innan lager minskas, och hantera ändrade portioner eller …',
    "U57": 'Lunchlådor som explicita portioner',
    "U58": 'Planera restmiddag utan att dubbelräkna mat eller inköp',
    "U59": 'Prioritera angivna öppnade förpackningar',
    "U60": 'Slå ihop namn- och GTIN-registrering av samma skafferivara med säker identitet…',
    "U61": 'En tydlig huvudhandling per vy',
    "U62": 'Progressiv detaljvisning',
    "U63": 'Konsekventa ord och siffror mellan Hem, Vecka, Recept och Handla',
    "U64": 'Reservera plats för priser/bilder så skärmen inte hoppar vid laddning',
    "U65": 'Bevara scrollposition, filter och relevant tillstånd efter receptdetalj/tillba…',
    "U66": 'Större text, små skärmar, skärmläsare, kontrast och fokus får inte bryta layou…',
    "U67": 'Direkt återkoppling på tryck och tydlig skillnad mellan lokalt ändrat, väntar …',
    "U68": 'Bilder ska föreställa rätt maträtt, ha dokumenterade rättigheter och tydlig fa…',
    "U69": 'Hjälpsamma tomlägen med direkt nästa handling',
    "U70": 'Premium presenteras i relevant sammanhang, inte som upprepade störande betalpå…',
    "U71": 'En gemensam definition av pris, jämförbarhet och besparing, återanvänd i alla …',
    "U72": 'Färskhet per rad, giltighet och cache enligt F3',
    "U73": 'Dela stegvis upp stora app.js i planering, prisvisning, Handla, konto/betalnin…',
    "U74": 'Testa nätbortfall mitt i planering, synk, handling och återkomst från betalning',
    "U75": 'Appuppdatering/service worker ska behålla sparad vecka och inte blanda inkompa…',
    "U76": 'Automatisk övervakning av uteblivna importer, inte bara en räknare någon manue…',
    "U77": 'Följ första vecka → inköpslista → nästa vecka med tydliga definitioner, minima…',
    "U78": 'Felrapport ska få relevant version/funktion/fel-ID med minimal datainsamling',
    "U79": 'Testa verkliga iPhone-/Android-enheter, äldre enheter och svag uppkoppling',
    "U80": 'Avsluta den dokumenterade databasincidenten enligt F6 och verifiera regression…',
    "X01": 'Jämför min egen inköpslista utan recept eller veckoplan',
    "X02": '”Vad kan vi äta ikväll?”',
    "X03": 'Klistra in lista från Anteckningar/meddelande, tolka rader och låt användaren …',
    "X04": 'Produktval',
    "X05": 'Förklara prisändring',
    "X06": 'Liten budget',
    "X07": 'Dela användbar vecka',
    "X08": 'Familjen kan rösta/välja mellan några middagar, planeraren beslutar slutligt',
    "X09": 'Återkomst efter uppehåll',
    "X10": 'Följ upp rapporterade fel med bekräftelse och status/återkoppling när möjligt',
    "X11": '”Ändrade planer?” på dagens middag',
    "X12": 'Förfina ”Byt rätt” med avsikt',
    "X13": 'Gör andra veckan lättare',
    "X14": 'Relevant erbjudandeflöde',
    "X15": 'Frivillig planeringsdag och påminnelse',
    "X16": 'Köp hela listan/matkassen',
    "A01": 'Översikt',
    "A02": 'Första användningen',
    "A03": 'Återkomst',
    "A04": 'Recept',
    "A05": 'Feedback',
    "A06": 'Ekonomi',
    "A07": 'Utveckling',
    "A08": 'Varje uppgift',
    "A09": 'Dashboarden ska hjälpa ägaren avgöra nästa åtgärd',
}

# (id, beskrivning, status, fungerar, återstår, test/bevis, PR/commit, prod)
K = []
def k(*rad): K.append(rad)

# ---- F: fynd ----------------------------------------------------------
k("F1", "Ofullständig kasse får inte krönas billigast", "klart att testa",
  "compare_chains kräver identiska saknade-mängder, annars different_baskets",
  "Bekräfta i produktion att ingen kröning sker vid olika kassar",
  "Regressionstest med granskningens exakta scenario", "#9 9d68f48", "NEJ")
k("F2", "Veckoval på riktig prismotor, inte uppskattning", "delvis",
  "Felet MÄTT mot produktion: median +4,6 %, spann −12,9…+19,5 %. inBudgetPool förkastar inte på gissning ensam. syncPlanPricing visar riktigt pris FÖRE valet",
  "Själva valet sker på comboEstimatedCost (dubbelräknar delade förpackningar, blandar kedjor). Asynkron bestMenuCombo krävs",
  "planning.test.js (3), mätning mot /api/pricing/week", "#25 37b876c", "NEJ")
k("F3", "Färskhet per prisrad", "klart att testa",
  "Kassans ålder = äldsta raden som faktiskt användes (min över verifiedAt/fetchedAt)",
  "Referensprisvägen saknar åldersgräns - se F3b. Ett för gammalt butikspris kan ersättas av ett äldre referenspris",
  "Enhetstest: en färsk rad nollställer inte kassens ålder", "#15 380a136", "NEJ")
k("F3b", "Åldersgräns på referenspriser (tillägg)", "kräver beslut",
  "Problemet är lokaliserat: store.py:869 och pricing.py:1355",
  "BLOCKERAT: maxålderns värde är ett ägarbeslut. SJÄLVSTÄNDIGT MÖJLIGT: rörledningen (ålder på referensrader, flagga i svaret) kan byggas nu",
  "—", "—", "NEJ")
k("F4", "Skilj möjlig/planerad/genomförd besparing", "delvis",
  "Etiketten 'Billigaste butiken' (var = vald butik) rättad till 'Oftast vald butik'; en post per vecka",
  "Posten skrivs vid VAL, inte vid genomförd handling",
  "savings-log.test.js", "#14 8103df5", "NEJ")
k("F5", "Osäker enhetsgenväg får inte räknas som exakt", "klart att testa",
  "DRY_SPICES: bara torra kryddor får 30 ml ≤ 15 g-regeln. 2 msk honung är inte längre '1 paket exakt'",
  "Konsekvensen är synlig i produktion (revisionen röd på 30 ärliga rader) - det är rätt, men O10b avgör vad som händer sen",
  "Enhetstester", "#13 f320e8a", "JA - revisionen visar exakt de rader F5 avslöjade")
k("F6", "Databasincidenten i git-historiken", "blockerat",
  "Inget", "BLOCKERAT: force-push mot delad historik kräver ägarbeslut. SJÄLVSTÄNDIGT: inget - all sanering är destruktiv",
  "—", "—", "NEJ")
k("F7", "Skilj CI, merge och deploy", "verifierat",
  "Deploygrinden 'bara grön main' höll när main var röd: #32 låg mergad men odeployad tills #33 gjorde main grön. health.commit och revisionens egen commit skiljer versionerna",
  "—", "Observerat live 2026-09-08 12:00-12:42", "—", "JA")

# ---- O: Operations ------------------------------------------------------
k("O1", "Driftstatus som adminförstasida", "klart att testa",
  "Sex systemkort + rubrik som väger in revisionen (rubriken sa förut 'alla system fungerar' över ett rött kort)",
  "Se den mot riktig produktionsdata i kontrollrummet",
  "Browser mot fixtur, desktop + 375 px", "#11 d9aab36, #16 b0e1202", "NEJ")
k("O2", "Rad per kedja: health, released, scope, ålder, gate", "klart att testa",
  "chain_health() med healthy/stale/failed/limited/never_imported/ready_for_release; skilda kolumner",
  "Kontroll mot riktig data", "9 enhetstester", "#8 745d37e", "NEJ")
k("O3", "ICA/Coop: visa ej släppt, schema, ingen snapshot", "delvis",
  "Dagligt schema 05:30/06:30 mergat; RELEASED_CHAINS orörd",
  "Ingen import har någonsin körts - täckning 'ej verifierat'", "—", "#5 235958a", "NEJ")
k("O4", "Lidl som Limited med orsak", "delvis",
  "limited-status finns och larmar aldrig", "Orsakstexten i adminvyn inte kontrollerad", "—", "#8", "NEJ")
k("O5", "Aktiva incidenter med kundpåverkan", "klart att testa",
  "overview(): per öppen incident vad är fel / påverkas kunder / vad göra; kundpåverkan ur släppt + ålder mot serveringsregeln, 'okänd' utan underlag; limited blir aldrig incident; kortet Incidenter i kontrollrummet",
  "Kontroll mot en riktig incident i produktion; 'senaste försök' visas ur panelen men snapshot-serveringen är härledd ur regeln, inte observerad",
  "7 nya + 1 uppdaterat test; browser 375 px", "#39", "NEJ")
k("O6", "Incidenthistorik, persistenta ID, dedupe", "klart att testa",
  "Tillstånd skrivs oavsett mejl; mejlstatus sent/failed/not_configured/pending sanningsenligt; recovery arkiverar start/recovery/duration/mejlstatus även om kvittot misslyckas; 50 poster i databasen, överlever omstart; cooldown bara för larm som gått ut",
  "Kontroll mot riktig drift över tid",
  "test_grocery_alerts.py (21)", "#8, #39", "NEJ")
k("O7", "Admin-mail: mottagare/transport/försök/leverans", "delvis",
  "recipientConfigured + transportConfigured + domän i health",
  "Senaste skickförsök och faktisk leverans saknas", "Live-läst adminAlerts", "#10 6052735", "JA (delen som finns)")
k("O8", "Primat: configured JA/NEJ, kvot ur verklig API-data", "delvis",
  "FINNS: /api/admin/primat-status svarar configured JA/NEJ utan nyckeln och anropar Primats GET /me (plan, dagsbudget, använda rader, reset) - rättelse: jag skrev tidigare att ingen kvot-endpoint fanns",
  "VISAS INTE: ingenting i kontrollrummet läser endpointen. OVERIFIERAT: att /me svarar med de fälten mot det riktiga kontot - kräver admin-token. Varning nära gräns finns inte. Köp/uppgradering = ägarbeslut",
  "Kodläsning primat_client.account_status", "—", "NEJ")
k("O9", "Scheduler: schema, körningar, nästa körning", "delvis",
  "Operations-koll 07:00 med test att den ligger efter importerna", "Faktiska körningar och nästa körning i adminvyn", "1 test", "#8", "NEJ")
k("O10", "Pricing audit med definierade nämnare", "delvis",
  "Auditen körs vid start + efter import, namnger osäkra rader per ingrediens, rubriken i admin visar felet",
  "Live-parsningsvägen granskas inte av auditen. Vad som händer med de 30 raderna = O10b",
  "Enhetstester i båda riktningarna; live-läst", "#16 b0e1202", "JA")
k("O10b", "Beslut om korrekt märkt osäkerhet i grinden (tillägg)", "kräver beslut",
  "Ketchup fick verifierad densitet (LV tabell 10 s.16). Tomatpuré, sirap, currypasta, sambal oelek saknas i källan",
  "BLOCKERAT: ska osäkerhet blockera grinden, eller mätas separat? SJÄLVSTÄNDIGT: ingen mer densitet utan källa",
  "—", "#34 (öppen)", "NEJ")
k("O11", "Deploy: commit, tider, avvikelse", "delvis",
  "health.commit; revisionen bär sin egen commit", "Jämförelse mot förväntad deploy saknas", "—", "#16", "JA (fälten finns)")
k("O12", "Skyddat admin-API, inte bara dold knapp", "verifierat",
  "Alla 16 admin-vägar × GET/POST × utloggad, vanligt konto, Premium, hushållsmedlem och login-token-som-admin-token = 160 anrop, alla 404 med SAMMA kropp som en okänd väg; positiv kontroll 200; utan konfigurerad hemlighet är ingen admin",
  "Ägarinloggning via roll (önskat spår i kravet) - inte påbörjat, och ska inte göras hastigt",
  "test_admin_api_negatives.py (3); produktionssond: 4 vägar × 2 identiteter = 404 med okänd-väg-kropp", "#38", "JA (negativa delen, live 2026-09-08)")
k("O13", "Mobilanpassad admin", "klart att testa",
  "Under 720 px: Kedjor-tabellen (13 kolumner, 1 424 px) ritas som kort per kedja; knappar min 44 px; sidscroll med synlig kant",
  "Kontroll på riktig telefon (U79) och mot produktionsdata",
  "Mätt i browser: 375 px före/efter, 1 280 px utan regression", "#36", "NEJ")
k("O14", "Testlista för Operations", "delvis", "21+ tester (chain_health 9, alerts 12)", "Samlad lista saknas", "—", "#8", "NEJ")
k("O15", "Active stores + kvotmonitorering", "delvis",
  "BUTIKER: fyra skilda tal per kedja (i registret / aktiva / färska ≤ 4 dygn / kundtillgängliga = färska i släppt kedja) med källa och mättid, visade i kontrollrummet",
  "KVOT: se O8 - endpointen finns men visas inte och är overifierad mot kontot. Butikstalen är inte kontrollerade mot produktionsdata",
  "4 enhetstester; browser 375 + 1 280 px", "#37", "NEJ")

# ---- U01-U06: första användningen ---------------------------------------
k("U01", "Förklara budgetens omfattning", "verifierat",
  "'Gäller 4 middagar för 2 personer. Frukost, lunch och hushållsvaror ingår inte.' i onboarding + Justera veckan, aria-label på hemkortet",
  "—", "budget-scope.test.js (4), browser 375 px", "#17 fc97052", "NEJ")
k("U02", "Nytta före kontokrav; bevara gästens plan", "verifierat",
  "Gäst får prissatt vecka; planen överlever kontoskapande", "—", "E2E", "#22 560cbbf", "NEJ")
k("U03", "Minimal start, mät tid till första listan", "delvis",
  "Mäts i E2E: 2,1-2,7 s till första användbara listan",
  "Mätt i testmiljö, inte med riktiga användare - målet 'ungefär en minut' är inte påstått uppnått", "E2E skriver ut måttet", "#23 fea9fb6", "NEJ")
k("U04", "Ändra felaktiga startval utan omstart", "verifierat", "Justera veckan ändrar utan att radera planen", "—", "E2E", "#24 6f06428", "NEJ")
k("U05", "Begriplig väntestatus", "verifierat", "'pris hämtas…' skiljs från 'pris saknas just nu'; prisfel ger besked", "—", "E2E", "#24 6f06428", "NEJ")
k("U06", "Visa antagna hemmavaror, erbjud tillägg", "delvis",
  "SYNLIGT + KNAPP: veckans antaganden listas, deduplicerade; tillägg via addExtraItem; en vara på listan erbjuds inte igen (21 namn är både antagna och köpta); tomt skafferifack räknas inte som hemma",
  "MÄNGD: raden får qty 1 utan enhet - receptet bär ingen mängd för hemmavaror. PRIS: 13 av 35 hemmavaror får inget pris som extravara; Free-gaten svarar 403 i ~1 av 5 fall och klienten sväljer det. JÄMFÖRELSE: extravaror ingår i totalen men inte i butiksjämförelsen",
  "assumed-home.test.js (10), E2E med betalväggskontroll", "#21 15299fd", "JA (strängen 'står redan på listan' i live-bundlet)")

# ---- U07-U18: veckoplanering --------------------------------------------
k("U07", "Lås middagar, byt resten", "att göra", "—", "Ingen låsfunktion", "—", "—", "NEJ")
k("U08", "Flytta middagar mellan dagar", "att göra", "—", "—", "—", "—", "NEJ")
k("U09", "Ångra vecka, bevara förra", "verifierat",
  "weekHistory + Återställ förra veckan. Noterat: historiken är icke-tom redan efter första veckan (onboardingen skapar en)",
  "—", "E2E: A → B → återställ → A, historiken minskad med ett; 5 körningar", "#28 bc48d6f", "NEJ")
k("U10", "Olika portioner per dag", "att göra", "—", "—", "—", "—", "NEJ")
k("U11", "Återkommande favoriter med paus", "att göra", "—", "—", "—", "—", "NEJ")
k("U12", "Nytt mot bekant, lagom upprepning", "att göra", "—", "—", "—", "—", "NEJ")
k("U13", "Egna middagar med strukturerade ingredienser", "att göra", "—", "—", "—", "—", "NEJ")
k("U14", "Gäster: skala rätt, visa extra inköp", "att göra", "—", "—", "—", "—", "NEJ")
k("U15", "Aktiv arbetsinsats, inte bara total tid", "att göra", "—", "—", "—", "—", "NEJ")
k("U16", "Köksutrustning", "att göra", "—", "—", "—", "—", "NEJ")
k("U17", "Säg när budget/kost/utbud inte går ihop; lätta aldrig på allergier", "klart att testa",
  "Varning när kraven inte går ihop; allergener lättas aldrig tyst", "Kontroll mot riktig trafik", "plan-warning.test.js, E2E", "#26 ab0b84e", "JA (strängen i live-bundlet)")
k("U18", "Ändrad inställning raderar inte planen", "verifierat", "refreshAfterSettingsChange behåller valda", "—", "E2E", "#24", "NEJ")

# ---- U19-U30: pengar ----------------------------------------------------
k("U19", "Rättvisa jämförelser (= F1)", "klart att testa", "Se F1", "Se F1", "Se F1", "#9", "NEJ")
k("U20", "Optimera delade förpackningar (= F2)", "delvis",
  "PRISSÄTTNINGEN av en vald vecka aggregerar före paketräkning: två recept med Gräslök+Ägg kostade 30,75 kr (3,1 %) mindre tillsammans",
  "VALET av vecka gör det inte - comboEstimatedCost summerar per recept. Fullt uppfyllt först med F2:s asynkrona val",
  "Mätning mot fixtur", "—", "NEJ")
k("U21", "Kostnadsförändring före receptbyte; ange saknad data", "klart att testa",
  "Prisändring per portion visas alltid; 'Prisändring okänd' utan data",
  "Talet är receptets portionspris, inte veckans inköpskostnad (kräver F2)", "swap.test.js (4), browser", "#27 0c3f08c", "JA (strängen i live-bundlet)")
k("U22", "Jämför med kundens vanliga butik", "att göra", "—", "Inget begrepp för vanlig butik", "—", "—", "NEJ")
k("U23", "Butiker användaren accepterar", "behöver verifieras", "storeSelectionForPricing, pinnedBranch finns", "Urvalsregeln inte granskad", "—", "—", "NEJ")
k("U24", "Avstånd intill prisskillnad, helhandling först", "behöver verifieras", "Avstånd visas i butikskorten", "'Genomförbar helhandling först' inte granskad", "—", "—", "NEJ")
k("U25", "Frivilligt medlemskap, villkorsstyrd beräkning", "delvis",
  "Konservativt RÄTT: medlems-/flerköpspris används aldrig i totalen, passerad kampanj faller bort, orimliga värden saneras",
  "Frivilligt medlemskap saknas (feature)", "Kodläsning effective_price", "—", "NEJ")
k("U26", "Förklara dyra engångsförpackningar", "att göra", "—", "—", "—", "—", "NEJ")
k("U27", "Billigare godtagbara produktval", "att göra", "—", "—", "—", "—", "NEJ")
k("U28", "Extravaror separat men i totalen; ej i portionspris", "delvis",
  "SETT I BROWSER: egen sektion 'Extra du lagt till', extrasCost i handlingens total",
  "Portionspriset kommer per recept från backend (kodläsning) - inget test på att tvättmedel inte kan smyga in", "Browser under U06-arbetet", "—", "NEJ")
k("U29", "Rättvis besparingshistorik (= F4)", "delvis", "Se F4", "Se F4", "Se F4", "#14", "NEJ")
k("U30", "Kvarvarande mängd efter veckan", "att göra", "—", "—", "—", "—", "NEJ")

# ---- U31-U42: i butiken -------------------------------------------------
for i in (31, 32, 33, 34):
    k(f"U{i}", KRAVTEXT[f"U{i}"], "att göra", "—", "Inte inventerat i detalj", "—", "—", "NEJ")
k("U35", "Borttagen är inte samma sak som hemma", "klart att testa",
  "Skilda handlingar 'Har hemma' och 'Köpt'; borttagen vara går att ta tillbaka", "Kontroll mot riktig trafik", "E2E", "#29 c6b8651", "NEJ")
for i in range(36, 43):
    k(f"U{i}", KRAVTEXT[f"U{i}"], "att göra", "—", "Inte inventerat i detalj", "—", "—", "NEJ")

# ---- U43-U60: matlagning, skafferi -------------------------------------
for i in range(43, 53):
    k(f"U{i}", KRAVTEXT[f"U{i}"], "att göra", "—", "Inte inventerat i detalj", "—", "—", "NEJ")
k("U53", "Vad 'finns hemma' utan mängd betyder", "kräver beslut", "—",
  "BLOCKERAT: produktdefinition. SJÄLVSTÄNDIGT: beror på U55/U56 som inte finns", "—", "—", "NEJ")
for i in range(54, 61):
    k(f"U{i}", KRAVTEXT[f"U{i}"], "att göra", "—", "Inte inventerat i detalj", "—", "—", "NEJ")

# ---- U61-U80: utseende, teknik ------------------------------------------
for i in (61, 62, 63):
    k(f"U{i}", KRAVTEXT[f"U{i}"], "att göra", "—", "—", "—", "—", "NEJ")
k("U64", "Reservera plats så skärmen inte hoppar", "behöver verifieras", "42 regler för min-height/aspect-ratio/skelett", "Inte prövat", "—", "—", "NEJ")
k("U65", "Bevara scroll och filter efter receptdetalj", "klart att testa",
  "Tillbakavägen gjorde scrollTo(0,0) - nu återställs platsen momentant; filtren låg redan i state",
  "Exakt pixel går inte (scroll anchoring); testet kräver kvar djupt i listan inom en skärmhöjd", "E2E, verifierat att testet fångar gamla beteendet", "#30 892d2b6", "NEJ")
k("U66", "Större text, skärmläsare, kontrast", "att göra", "—", "—", "—", "—", "NEJ")
k("U67", "Lokalt/väntar/bekräftat", "behöver verifieras", "setSyncStatus med 'Synkar…' finns", "Inte prövat", "—", "—", "NEJ")
k("U68", "Bilder: rätt rätt, rättigheter, fallback", "delvis",
  "Backend släpper bara bilder med licens; kategoribaserad fallback", "Ingen kreditering visas i frontend", "recipe-fallback.test.js", "#12", "NEJ")
k("U69", "Hjälpsamma tomlägen", "att göra", "—", "—", "—", "—", "NEJ")
k("U70", "Premium i sammanhang, inte störande", "att göra", "—", "—", "—", "—", "NEJ")
k("U71", "Gemensam definition av pris/jämförbarhet/besparing", "delvis",
  "hasUsablePrice och comparable finns på ETT ställe", "I app.js, inte utbrutet som modul", "—", "—", "NEJ")
k("U72", "Färskhet, giltighet, cache (= F3)", "delvis",
  "VERIFIERAT: cachenyckeln bär planen (free/premium); PARSER_VERSION hindrar felparsade priser ur stale-cache; kassans ålder från använda rader",
  "Referensprisvägen saknar åldersgräns (F3b) - 'färskhet per rad' gäller därför inte referensrader",
  "Enhetstester (#7, #15)", "#7 115aa03, #15 380a136", "NEJ")
k("U73", "Dela upp app.js stegvis", "att göra", "Fem moduler utbrutna under sessionen (budget-scope, assumed-home, savings-log, plan-warning, recipe-fallback)", "app.js är fortfarande ~5 300 rader", "—", "—", "NEJ")
k("U74", "Testa nätbortfall mitt i flöden", "att göra", "—", "—", "—", "—", "NEJ")
k("U75", "Service worker behåller vecka, blandar inte versioner", "att göra", "Cacheversion bumpas per release (v35→v42)", "Inget test på blandade versioner", "—", "—", "NEJ")
k("U76", "Automatisk övervakning av uteblivna importer", "verifierat",
  "alerts.py med dedupe + recovery, operationskoll 07:00, reconcile_interrupted_runs; adminAlerts live",
  "—", "12 tester; live-läst adminAlerts", "#8, #10", "JA")
k("U77", "Följ första vecka → lista → nästa vecka", "att göra", "Tratten per kohort finns i insights", "Definitioner och integritet inte granskade", "—", "—", "NEJ")
k("U78", "Fel-ID i felrapport", "att göra", "Servern loggar rid=", "Inget når användaren", "—", "—", "NEJ")
k("U79", "Testa riktiga enheter; annars redovisa", "att göra",
  "REDOVISNING: allt är browser + Playwright (390x844 mobil emulering). Ingen fysisk iPhone/Android testad. iOS-appen är byggd i build/ios",
  "Simulatorkörning inte gjord", "—", "—", "NEJ")
k("U80", "Avsluta databasincidenten (= F6)", "blockerat", "Se F6", "Se F6", "—", "—", "NEJ")

# ---- X: produktflöden ---------------------------------------------------
k("X01", "Jämför egen lista utan recept", "att göra", "—", "—", "—", "—", "NEJ")
k("X02", "Vad kan vi äta ikväll?", "delvis", "cookModal 'Laga med det du har hemma'", "Personer/tid-urval inte granskat", "—", "—", "NEJ")
k("X03", "Klistra in lista", "att göra", "—", "—", "—", "—", "NEJ")
k("X04", "Produktval: vanligt märke/likvärdigt/lägst", "att göra", "—", "—", "—", "—", "NEJ")
k("X05", "Förklara prisändring", "att göra", "—", "—", "—", "—", "NEJ")
k("X06", "Liten budget: minsta att betala nu", "att göra", "—", "—", "—", "—", "NEJ")
k("X07", "Dela användbar vecka", "delvis", "Receptdelning + hushållsinbjudan", "Mottagarens omräknade priser inte granskade", "—", "—", "NEJ")
k("X08", "Familjen röstar", "att göra", "—", "—", "—", "—", "NEJ")
k("X09", "Återkomst efter uppehåll", "att göra", "—", "—", "—", "—", "NEJ")
k("X10", "Följ upp rapporterade fel", "att göra", "—", "—", "—", "—", "NEJ")
k("X11", "Ändrade planer på dagens middag", "att göra", "—", "—", "—", "—", "NEJ")
k("X12", "Byt rätt med avsikt, visa kostnadsdelta", "verifierat",
  "Fem avsikter (billigare, snabbare, barnvänligare, mer protein, använd hemma); kostnadsdelta alltid sedan U21",
  "—", "swap.test.js, browser", "#27", "JA (via U21)")
k("X13", "Andra veckan lättare", "att göra", "weekHistory och favoriter finns", "Återanvänd förra veckan med ändringar saknas", "—", "—", "NEJ")
k("X14", "Relevant erbjudandeflöde", "delvis", "Kampanjtext per rad, kampanjtorg", "Villkor/giltighet inte granskade", "—", "#12", "NEJ")
k("X15", "Frivillig påminnelse", "delvis", "Notiskod finns", "Plattformsstöd och tillstånd inte granskade", "—", "—", "NEJ")
k("X16", "Köp hela listan", "blockerat",
  "SJÄLVSTÄNDIGT GJORT: cart.py med de fyra nivåerna, tester som hindrar den från att påstå mer än en hemsidelänk",
  "BLOCKERAT: ingen kedja har avtalad väg in - registret är tomt med flit", "8 tester", "—", "NEJ")

# ---- A: ägarpanel -------------------------------------------------------
k("A01", "Översikt; skilj kompenserad från betalande", "klart att testa",
  "premiumSource (subscription/trial/comped); tratten räknar per källa; kontrollrummet visar dem",
  "Se den mot riktiga konton", "7 tester, browser mot fixtur", "#31 20a6b8a", "JA (admin.js live bär 'betalande Premium')")
for i in (2, 3, 4, 5):
    k(f"A{i:02d}", KRAVTEXT[f"A{i:02d}"], "att göra", "—", "—", "—", "—", "NEJ")
k("A06", "Ekonomi ur verifierad betaldata", "blockerat",
  "SJÄLVSTÄNDIGT GJORT: A01 räknar konton per källa", "BLOCKERAT: kräver betaldata; ingen intäkt får härledas ur antal × pris", "—", "#31", "NEJ")
for i in (7, 8, 9):
    k(f"A{i:02d}", KRAVTEXT[f"A{i:02d}"], "att göra", "—", "—", "—", "—", "NEJ")


def main() -> int:
    ids = [r[0] for r in K]
    dubbla = [i for i, n in Counter(ids).items() if n > 1]
    saknas = sorted(set(ALLA) - set(ids), key=ALLA.index)
    okanda = sorted(set(ids) - set(ALLA))
    fel_status = [(r[0], r[2]) for r in K if r[2] not in STATUS]
    if dubbla or saknas or okanda or fel_status:
        print("VÄGRAR SKRIVA:", file=sys.stderr)
        if dubbla: print("  dubbla:", dubbla, file=sys.stderr)
        if saknas: print("  saknas:", saknas, file=sys.stderr)
        if okanda: print("  okända:", okanda, file=sys.stderr)
        if fel_status: print("  ogiltig status:", fel_status, file=sys.stderr)
        return 1

    tot = Counter(r[2] for r in K)
    klara = tot["verifierat"]
    rader = [
        "# Kravtabell — en rad per krav, totaler räknade ur raderna",
        "",
        f"Genererad av `backend/scripts/kravtabell.py`. **{len(K)} krav**: masterinstruktionens "
        f"{len(ORIGINAL)} plus två tillägg ({', '.join(TILLAGG)}). Skriptet vägrar skriva om ett ID "
        "saknas, dubbleras eller inte finns i instruktionen.",
        "",
        "## Totaler",
        "",
        "| Status | Antal |", "|---|---:|",
    ]
    for s in STATUS:
        rader.append(f"| {s} | {tot[s]} |")
    rader += [
        f"| **summa** | **{sum(tot.values())}** |",
        "",
        f"**Färdiga (verifierat): {klara} av {len(K)}.** 'Klart att testa' räknas inte som färdigt.",
        "",
        "Verifierat i produktion = JA bara när något faktiskt lästes från matjakt.onrender.com "
        "eller matjakt.store efter deploy.",
        "",
        "## Tilläggen, definierade",
        "",
    ]
    for tid, text in TILLAGG.items():
        rader.append(f"- **{tid}** — {text}")
    rader += [
        "",
        "## Motsägelser som är utredda",
        "",
        "- **U20 mot F2.** Prissättningen av en *vald* vecka aggregerar delade förpackningar (mätt). "
        "*Valet* av vecka gör det inte. U20 är därför `delvis`, inte verifierat, tills F2:s asynkrona val finns.",
        "- **U06.** Synliga antaganden och fungerande tilläggsknapp är verifierade. Korrekt mängd och pris är det inte: "
        "raden får `qty 1` utan enhet, 13 av 35 hemmavaror får inget pris som extravara, och extravaror ingår "
        "inte i butiksjämförelsen. Därför `delvis`.",
        "- **F3/U72.** Verifierat: kassans ålder räknas på använda rader, cachenyckeln bär planen, PARSER_VERSION "
        "hindrar felparsade priser. Inte verifierat: färskhet på *referensrader* — F3b blockerar, eftersom "
        "referenspriser hämtas utan åldersgräns.",
        "- **Blockeringar.** Varje blockerad rad skiljer den blockerade delen (kolumnen 'återstår') från det "
        "som gjorts eller kan göras självständigt (kolumnen 'fungerar').",
        "",
        "## Olöst — får inte försvinna bakom en grön körning",
        "",
        "- **E2E-orsaken.** Konsumentresan har fallit i CI på `16/19 = 84,2 %` täckning. Tre slutsatser dragna och "
        "tillbakatagna. 20 000 modellerade veckor **utesluter ingenting** — *inte reproducerat i det modellerade "
        "urvalet*. Diagnosen skriver nu ut begäran och svar per anrop och väntar på nästa verkliga fall.",
        "- **'1 st' för en förpackad vara.** 13 av 35 hemmavaror får inget pris när de läggs till.",
        "",
        "## Tabellen",
        "",
        "| ID | Krav | Status | Fungerar | Återstår | Test/bevis | PR/commit | Prod |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in K:
        rader.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    UT.write_text("\n".join(rader) + "\n", encoding="utf-8")
    print(f"skrev {UT.relative_to(ROOT)}: {len(K)} rader")
    for s in STATUS:
        print(f"  {s:20s} {tot[s]:3d}")
    print(f"  {'summa':20s} {sum(tot.values()):3d}   färdiga (verifierat): {klara}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
