# Receptidentitet och dubbletter

**Paket P04a · 2026-09-16 · read-only.** Det här dokumentet ändrar ingenting i
banken. Det avgör, par för par, vilka av receptbankens likheter som är
*samma rätt under två id* och vilka som är *två rätter som råkar likna
varandra* — och räknar upp allt i kod och data som bär ett recept-id, så att
paket 2 (`P04b`, stabil identitet i koden) vet exakt vad som måste tåla att
ett id blir alias för ett annat.

Underlag: `backend/recipe_sources/*.json`, 240 recept i 13 filer, alla id
unika. Varje bedömning nedan är gjord mot källfilernas ingrediensrader, steg,
proteinkälla, bild, måltidstyp och portionsantal — inte mot en siffra.

`backend/tests/test_receptidentitet.py` håller dokumentet sant: varje id i
tabellerna måste finnas i källorna (som recept eller deklarerat alias), varje
Jaccard- och namnlikhet räknas om, aliastabellen får bara bära par som är
klassade som samma rätt, och siffrorna i sammanfattningen räknas ur
tabellerna.

---

## 1. Sammanfattning

Utfall för de 29 paren: **0** exakta dubbletter · **4** samma rätt,
namnvariant · **3** legitima varianter · **22** olika rätter.

Utanför de 29 (paren briefen namnger, plus vad delade bilder och namnlikhet
pekade ut): **0** exakta dubbletter · **6** samma rätt, namnvariant · **3**
legitima varianter · **10** olika rätter.

Totalt föreslås **10 aliasgrupper** (avsnitt 7): tio id blir alias för tio
kanoniska. Banken går från 240 till 230 kanoniska recept, och de tio gamla
id:na fortsätter öppna rätt recept. Ingen grupp har mer än ett alias. Inget
par är en exakt dubblett — inte ens tacos-paret: kcal 590/620, blandfärs mot
nötfärs, paprikapulver mot tacokrydda.

Tre saker som avgjorde mer än siffrorna:

- **Ingrediens-Jaccard kan inte avgöra identitet.** `rakcurry` ↔ `tofucurry`
  ligger på 0,750 och är två rätter; `tacos-kottfars` ↔ `kottfars-tacos`
  ligger på 0,250 och är samma rätt. Det andra beror på att
  `normalize_ingredient_id` är en slug och ingen kanonisering: `tomat` ≠
  `tomater`, `tortilla` ≠ `tortillabrod`, `blandfars` ≠ `notfars`. (P05a,
  `backend/services/ingredients/`, är precis den länken; en omkörning av
  auditen på kanoniska ingrediens-id är ett rimligt nästa steg, men inte det
  här paketets.)
- **Namnlikhet kan inte avgöra identitet.** `falukorv-ugn` ↔
  `torsk-potatismos` ligger på 0,857 ("Ugnsbakad falukorv med potatismos" /
  "Ugnsbakad torsk med potatismos"); `kyckling-ris-mild` ↔ `kycklinggryta`
  på 0,894 och är grädde/paprika mot kokos/curry.
- **Bilden är ett symptom, inte ett bevis.** 40 bilder delas av flera recept;
  en skål med ris bär nio olika rätter. Delad bild var en anledning att
  *titta*, aldrig en anledning att slå ihop.

---

## 2. Metod

Auditen reproducerades med bankens egen nyckel: `normalize_ingredient_id`
(`backend/services/recipes/store.py`) på varje ingrediensrad inklusive
skafferivaror, Jaccard över mängderna, tröskel 0,70. Det gav **exakt 29 par**
i **13 sammanhängande klumpar**, varav en curryklump på sex recept (avsnitt
5). Namnlikhet är `difflib.SequenceMatcher` på gemena receptnamn. Båda talen
står i tabellerna så att de går att räkna om.

Sedan lästes varje par i sin helhet ur källfilerna. Det som fick avgöra, i
den här ordningen:

1. **Vad man köper.** Ingrediensraderna med mängder — inte deras slug.
   "Bacon 140 g" och "Sidfläsk 300 g" är samma sorts rad i samma rätt;
   "Ryggbiff 600 g" och "Laxfilé 600 g" gör två rätter av samma glaze.
2. **Vad man gör.** Stegen. Två recept med samma stegföljd och samma teknik
   (ugn 175 °, koka potatis, kall sås på crème fraiche) är samma rätt även om
   den ena har gräslök i såsen.
3. **Proteinkällan.** Byts den (fläsk/kikärter/kyckling/räkor/tofu) är det en
   annan rätt, oavsett hur lika resten är.
4. **Vad receptet själv säger att det är.** Ett namn som "Snabb kikärtscurry"
   eller en beskrivning som "torsdagsklassikern helt utan fläsk" positionerar
   receptet som en variant på en axel. Det är skillnaden mellan *legitim
   variant* och *olika rätter*.
5. **Måltidstyp, portioner, bild** — som stöd, aldrig som avgörande.

---

## 3. Klasserna

| klass | betyder | konsekvens |
|---|---|---|
| `EXAKT DUBBLETT` | samma ingrediensrader, samma steg, samma näringstal | alias |
| `SAMMA RÄTT, NAMNVARIANT` | samma rätt (samma köp, samma teknik, samma proteinkälla) med skillnader som inte bär någon avsikt: ett annat namn, en örtsort till, en annan sylt | alias |
| `LEGITIM VARIANT (axel)` | samma rätt, men receptet positionerar sig avsiktligt på en axel: **klassisk / billig / snabb / protein / vego** — och skillnaden finns i ingredienserna, inte bara i namnet | båda behålls |
| `OLIKA RÄTTER` | olika proteinkälla, olika teknik eller olika tillbehör som gör en annan tallrik — även när siffrorna säger annat | båda behålls |

**Kanoniskt id** väljs efter, i ordning: (1) det recept vars data är mest
komplett och stämmer med sig själv (ingredienser som stegen faktiskt använder,
allergener, fiber, svårighetsgrad, licensierad bild); (2) det id som namnger
rätten som en svensk söker den; (3) befintliga referenser i kod och tester;
(4) längst tid i drift. Det fjärde väger lätt med flit: aliaset gör att det
gamla id:t fortsätter fungera, så exponering är inget skäl att behålla ett
sämre recept som sanning. **Receptet som blir kvar behåller sitt id; det som
tas bort blir aliaset.** Innehållet flyttas aldrig mellan id — det är Recept
2.0:s kvalitetsspår (P0.5+), inte identitetens.

---

## 4. De 29 paren

Ordnade efter Jaccard. Kolumnen *namn* är namnlikheten.

<!-- par29:start -->
| # | par | Jaccard | namn | klass | varför |
|---|---|---|---|---|---|
| 1 | `flaskfile-rotfrukter` ↔ `flaskfilerotmos` | 0.875 | 0.636 | SAMMA RÄTT, NAMNVARIANT | Fläskfilé (700/600 g), potatis 600 g, morötter 400 g, timjan, ugn 200 ° till 65 ° innertemperatur i båda. `flaskfilerotmos` säger "baconlindad" i namn och steg 3 men har **ingen bacon i ingredienslistan** — som data är det samma rätt utan bacon. Id:t säger "rotmos"; receptet har inget mos. Samma bild (Pexels 11001292). `flaskfile-rotfrukter` har dessutom rödlök, bryning, fiber och svårighetsgrad. |
| 2 | `lax-kall-dillsas` ↔ `ugnslax-citron` | 0.875 | 0.553 | SAMMA RÄTT, NAMNVARIANT | Identiska köp: laxfilé 600 g, potatis 800 g, crème fraiche 2 dl, dill, citron, salt, svartpeppar — `ugnslax-citron` lägger till gräslök 20 g. Identisk stegföljd: ugn 175 °, koka potatis, lax i form med salt/peppar/citron, 15–22 min, kall sås på crème fraiche och dill. kcal 560/560, protein 34/35. Bilderna är två foton ur samma Pexels-serie (20182311/20182293). Dillsås med gräslök är en örtsås; det är samma tallrik. |
| 3 | `biffbowl-teriyaki` ↔ `lax-teriyaki` | 0.800 | 0.613 | OLIKA RÄTTER | Samma glaze (sojasås 1 dl, honung 40 g, ingefära, vitlök), samma broccoli och sesam — men ryggbiff 600 g mot laxfilé 600 g. Proteinkällan byts: kött mot fisk, allergen `fisk` tillkommer. Två rätter på samma sås. |
| 4 | `flasktomatpasta` ↔ `halloumipasta` | 0.778 | 0.424 | OLIKA RÄTTER | Pasta i tomatsås med basilika i båda; fläskfilé 500 g mot halloumi 225 g. Kött mot vegetariskt, `laktos` tillkommer. Mallsyskon i batch00, inte samma rätt. |
| 5 | `artsoppa-klassisk` ↔ `artsoppa-vegetarisk` | 0.750 | 0.449 | LEGITIM VARIANT (vego) | Gula ärtor 400 g, lök, morötter, timjan, senap, 75–90 min i båda. Den ena kokas på rimmat sidfläsk 300 g, den andra på buljongtärning och beskriver sig själv som "torsdagsklassikern helt utan fläsk". Skillnaden är avsiktlig och finns i köpet (fläsk mot buljong) och i kosten (`veganskt`, `glutenfritt`). |
| 6 | `biffgraddtimjan` ↔ `biffmedlok` | 0.750 | 0.587 | OLIKA RÄTTER | Biff, potatis 800 g, grädde 200 ml, smör, salt, peppar i båda — men rostad timjanpotatis med gräddsås mot potatismos med sötstekt lök (lök 2 st finns bara i den ena). Två klassiska biffmiddagar med olika tillbehör. |
| 7 | `flaskcurrygryta` ↔ `kikartscurry` | 0.750 | 0.578 | OLIKA RÄTTER | Curryklumpen (avsnitt 5): fläskfilé 500 g mot kikärtor 380 g. |
| 8 | `flaskcurrygryta` ↔ `kycklinggryta` | 0.750 | 0.522 | OLIKA RÄTTER | Curryklumpen: fläskfilé mot kycklinglårfilé 600 g. |
| 9 | `flaskcurrygryta` ↔ `rakcurry` | 0.750 | 0.667 | OLIKA RÄTTER | Curryklumpen: fläskfilé mot räkor 300 g (`skaldjur`). |
| 10 | `flaskcurrygryta` ↔ `tofucurry` | 0.750 | 0.615 | OLIKA RÄTTER | Curryklumpen: fläskfilé mot tofu 400 g (`soja`, veganskt). |
| 11 | `kikartscurry` ↔ `kycklinggryta` | 0.750 | 0.585 | OLIKA RÄTTER | Curryklumpen: kikärtor mot kyckling; veganskt mot blandkost. |
| 12 | `kikartscurry` ↔ `morotscurry` | 0.750 | 0.636 | OLIKA RÄTTER | Båda kikärtor 380 g över ris, men `morotscurry` bygger på morötter 400 g och har **ingen kokosmjölk** — en torrare grönsakscurry (fett 3 g mot 21 g). |
| 13 | `kikartscurry` ↔ `rakcurry` | 0.750 | 0.609 | OLIKA RÄTTER | Curryklumpen: kikärtor mot räkor. |
| 14 | `kikartscurry` ↔ `tofucurry` | 0.750 | 0.596 | OLIKA RÄTTER | Curryklumpen: kikärtor mot tofu; båda veganska men olika köp och olika allergen (`soja`). |
| 15 | `kycklinggryta` ↔ `rakcurry` | 0.750 | 0.511 | OLIKA RÄTTER | Curryklumpen: kyckling mot räkor. |
| 16 | `kycklinggryta` ↔ `tofucurry` | 0.750 | 0.458 | OLIKA RÄTTER | Curryklumpen: kyckling mot tofu. |
| 17 | `rakcurry` ↔ `tofucurry` | 0.750 | 0.868 | OLIKA RÄTTER | Det par briefen pekar ut. Namnen skiljer sig på tre bokstäver, ingredienserna på proteinkällan: räkor 300 g (`skaldjur`, blandkost) mot tofu 400 g (`soja`, veganskt). Stegen skiljer sig också — räkorna läggs i sist "inte mer, då blir de sega", tofun pressas, tärnas och steks först. |
| 18 | `laxsallad` ↔ `raksallad` | 0.750 | 0.706 | OLIKA RÄTTER | Matvete 250 g, citron, dill, olja i båda; ugnsbakad laxfilé 500 g mot räkor 300 g. Fisk mot skaldjur, ljummen mot kyld. |
| 19 | `linsbolognese` ↔ `linsbolognese-proteinrik` | 0.750 | 0.746 | SAMMA RÄTT, NAMNVARIANT | Röda linser 300 g, pasta 400 g, morötter 2, gul lök 1, vitlök, tomatpuré, oregano 5 g, samma stegföljd (fräs, tomatpuré, linser + krossade tomater, sjud 20 min). "Proteinrik" bär **ingen extra proteinkälla** — samma 300 g linser ger 22 g i den ena och 30 g i den andra — och "fullkornspasta" i namnet motsvaras av raden "Pasta". Skillnaderna (krossade tomater 800/400 g, buljongtärning) är mängder, inte avsikt. Samma bild (Pexels 4350120). Ett protein-variantanspråk utan proteinkälla är inte en legitim variant. |
| 20 | `linsbolognese` ↔ `spaghetti-kottfarssas` | 0.750 | 0.346 | OLIKA RÄTTER | Samma sås-bas (krossade tomater, morot, lök, vitlök, tomatpuré, oregano) men röda linser 300 g mot blandfärs 500 g. Vego-motsvarigheten till köttfärssåsen är en egen rätt — den beskriver sig inte som en variant av den. |
| 21 | `pannkakor` ↔ `raggmunk` | 0.750 | 0.263 | OLIKA RÄTTER | Samma smet (vetemjöl, mjölk, ägg, salt, smör, lingonsylt) — men raggmunk river ner 900 g potatis och steker 300 g rimmat sidfläsk. Potatisplättar med fläsk mot tunna pannkakor. |
| 22 | `stekt-strommingsflundra` ↔ `torsk-brynt-smor-agg` | 0.750 | 0.603 | OLIKA RÄTTER | Torskfilé 600 g, potatis 800 g, smör, citron, persilja i båda. Den ena mjölvänds och **steks** i smör (vetemjöl 60 g, `gluten`), den andra **sjuds** och serveras med brynt smör och tre hackade ägg (`ägg`, `glutenfritt`). Olika teknik, olika tallrik. (Id:t säger strömming/flundra; receptet är torsk — se avsnitt 10.) |
| 23 | `chili-con-carne` ↔ `vegansk-chili-sin-carne` | 0.733 | 0.500 | LEGITIM VARIANT (vego) | Samma gryta: kidneybönor, krossade tomater 800 g, lök 2, vitlök 3, tomatpuré 70 g, paprikapulver, spiskummin, chilipulver, ris 480 g, 6 portioner. Nötfärs 600 g mot svarta bönor 380 g + röda linser 150 g + paprika. "Sin carne" är per definition den köttfria varianten av "con carne", och skillnaden finns i köpet. |
| 24 | `kikartscurry-protein` ↔ `kikartscurry-snabb` | 0.727 | 0.885 | LEGITIM VARIANT (snabb) | Samma rätt — kikärtor (800/760 g), kokosmjölk 400 ml, spenat, lök, vitlök, curry, ris — och den ena heter "Snabb kikärtscurry med spenat". Snabbheten finns i receptet: 5 + 15 min mot 10 + 20, och krossade tomater 400 g gör såsen till en tomat-kokoscurry. Bankens tunnaste variant: skillnaden är en burk tomater och tio minuter, och proteintalet (15 mot 22 g på nästan samma mängd kikärtor) hänger inte ihop. Behålls som variant; Recept 2.0 bör antingen skärpa den eller vika in den. |
| 25 | `flaskpannkaka` ↔ `pannkakor` | 0.714 | 0.500 | OLIKA RÄTTER | Samma smet, men ugnspannkaka med 300 g sidfläsk mot tunna stekta pannkakor. |
| 26 | `flaskpannkaka` ↔ `ugnspannkaka-bacon` | 0.714 | 0.585 | SAMMA RÄTT, NAMNVARIANT | Samma teknik steg för steg: ugn 225 °, smet på vetemjöl/mjölk/ägg/salt, fläsket steks knaprigt i formen, smeten hälls över, 25–35 min, serveras med lingonsylt 150 g. Sidfläsk 300 g mot bacon 140 g är samma sorts rad — bacon är den moderna styckdetaljen i en fläskpannkaka, inte en annan rätt. Ingen axel (inte billigare, inte snabbare, inte mer protein). `flaskpannkaka` har rättens eget namn och en licensierad bild av just den rätten (Wikimedia Commons, CC BY 2.0); `ugnspannkaka-bacon` bär en generisk Pexels-bild. |
| 27 | `pannkakor` ↔ `ugnspannkaka-bacon` | 0.714 | 0.516 | OLIKA RÄTTER | Samma smet; tunna pannkakor i panna mot ugnspannkaka med bacon. |
| 28 | `flasktomatpasta` ↔ `kottfarssas` | 0.700 | 0.627 | OLIKA RÄTTER | Pasta i tomatsås med basilika; fläskfilé 500 g mot köttfärs 500 g (+ lök). Olika kött, olika rätt. |
| 29 | `halloumipasta` ↔ `kottfarssas` | 0.700 | 0.211 | OLIKA RÄTTER | Halloumi mot köttfärs. Vegetariskt mot kött. |
<!-- par29:slut -->

---

## 5. Curryklumpen

Sex recept i `batch00_migrerade.json` är byggda på samma mall: ris 250 g,
curry 10 g, wokgrönsaker 300 g, kokosmjölk 400 ml, olja, salt — plus **en**
proteinkälla:

| id | proteinkälla | kost | allergen | bild |
|---|---|---|---|---|
| `flaskcurrygryta` | fläskfilé 500 g | blandkost | — | egen |
| `kycklinggryta` | kycklinglårfilé 600 g | blandkost | — | delad med fyra andra kycklinggrytor |
| `rakcurry` | räkor 300 g | blandkost | skaldjur | egen |
| `tofucurry` | tofu 400 g | veganskt | soja | egen |
| `kikartscurry` | kikärtor 380 g | veganskt | — | delad med `kikartscurry-protein` |
| `morotscurry` | morötter 400 g + kikärtor 380 g, **utan kokosmjölk** | veganskt | — | egen |

Elva av de 29 paren ligger här, alla på Jaccard 0,750 därför att sex av sju
rader är mallens. **Samtliga är olika rätter**: det som skiljer dem är precis
det en användare väljer rätt efter — vad som ligger i grytan. Ingen av dem är
alias för en annan. Att sex rätter delar en sås är däremot en fråga om
*variation* (veckoplaneraren kan i dag ge tre kokoscurryn samma vecka) och en
fråga för Recept 2.0, inte för identiteten.

---

## 6. Utanför de 29

Paren briefen namnger som inte nådde tröskeln, plus vad delade bilder och
namnlikhet ≥ 0,80 pekade ut. Samma metod, samma rigor.

<!-- extra:start -->
| # | par | Jaccard | namn | klass | varför |
|---|---|---|---|---|---|
| E1 | `tacos-kottfars` ↔ `kottfars-tacos` | 0.250 | 0.610 | SAMMA RÄTT, NAMNVARIANT | Färs 500 g, tortilla 8 st, gurka, tomat, majs 200 g, riven ost, crème fraiche i båda; samma fem steg (bryn färsen, krydda med vatten, skär grönsakerna, värm bröden, alla bygger sina egna). Blandfärs mot nötfärs, paprikapulver mot tacokrydda, paprika mot isbergssallad, kcal 590/620. Samma bild (Pexels 28895976). Jaccard 0,250 beror på slugarna (tomat/tomater, tortilla/tortillabröd, blandfärs/nötfärs), inte på rätten. |
| E2 | `lax-teriyaki` ↔ `teriyakilax` | 0.455 | 0.735 | SAMMA RÄTT, NAMNVARIANT | Två "Teriyakilax … och ris". Laxfilé (600/500 g) steks 2–3 min per sida och glaseras i soja + honung + ingefära 20 g över ris med en grön grönsak (broccoli 400 g mot wokgrönsaker 400 g). Samma bild (Pexels 17308546). `teriyakilax` (batch00) är den tunna versionen: "Soja 30 ml", "Honung 1 tsk", ingen vitlök, inget sesam, allergener utan `sesam`, kost `pescetariskt` utan `laktosfritt`; `lax-teriyaki` bär en riktig glaze (sojasås 1 dl, honung 40 g), fiber och svårighetsgrad. |
| E3 | `pannkakor` ↔ `pannkakor-klassiska` | 0.625 | 0.474 | SAMMA RÄTT, NAMNVARIANT | Tunna pannkakor: vetemjöl, mjölk, ägg, salt, smet som får svälla, steks i smör. Lingonsylt 150 g mot jordgubbssylt 200 g + grädde 2 dl är tillbehör, inte rätt. kcal 480/480. Samma bild (Pexels 3807390). |
| E4 | `vegobolognese` ↔ `vegansk-bolognese-vegofars` | 0.133 | 0.536 | SAMMA RÄTT, NAMNVARIANT | Vegofärs 400 g i tomatsås över pasta i båda, samma stegföljd (fräs lök, stek färsen, krossade tomater, sjud, koka pastan). `vegobolognese` (batch00) är sex rader varav en heter "Kryddor"; `vegansk-bolognese-vegofars` har morötter, vitlök, tomatpuré, buljong, oregano, fiber och svårighetsgrad. Samma bild (Pexels 5807018). Jaccard 0,133 är slugarnas fel (pasta/spaghetti, lök/gul lök). |
| E5 | `linssoppa` ↔ `linssoppa-rod` | 0.556 | 0.634 | SAMMA RÄTT, NAMNVARIANT | "Röd linssoppa" och "Röd linssoppa med kokosmjölk": röda linser (250/300 g), kokosmjölk 400 ml, morötter, lök, vitlök, buljong 700 ml, olja — samma soppa mixad slät. Protein 19/19. Samma bild (Pexels 7160694). `linssoppa` (batch00) skriver "Lök & vitlök 150 g" som en rad; `linssoppa-rod` har raderna var för sig, salt, fiber och svårighetsgrad. |
| E6 | `rakpasta-vitlok` ↔ `scampi` | 0.364 | 0.844 | SAMMA RÄTT, NAMNVARIANT | Stegen är nästan ordagrant samma text: "Koka pastan al dente och spara en kopp pastavatten", "Fräs skivad vitlök … i rikligt med olivolja", "Lägg i räkorna och värm dem en minut", "Vänd ner pastan med citronskal, citronsaft och en skvätt pastavatten". Räkor (400/300 g), pasta, vitlök, citron, persilja, olivolja i båda; `rakpasta-vitlok` har chili och mängder, `scampi` (batch00) har vitlök 1 klyfta och kcal 307 med fett 1 g — omöjligt med "rikligt med olivolja". Olika bilder. |
| E7 | `chili-con-carne` ↔ `chili-sin-carne-budget` | 0.467 | 0.867 | LEGITIM VARIANT (vego) | Det par briefen varnar för: namnen skiljer sig på en bokstav, köpet på proteinkällan — nötfärs 600 g + kidneybönor mot svarta bönor 800 g + majs. Köttfri variant av samma gryta, avsiktlig och i ingredienserna. |
| E8 | `chili-sin-carne-budget` ↔ `vegansk-chili-sin-carne` | 0.600 | 0.577 | LEGITIM VARIANT (billig) | Två köttfria chilin. `chili-sin-carne-budget` (batch03_budget, 4 portioner, 25 min): svarta bönor 800 g + majs, tio rader. `vegansk-chili-sin-carne` (6 portioner, 35 min): tre sorters bönor + röda linser + paprika, fjorton rader. Olika bönmix, olika sats. Alla tre chilin delar dock **samma bild** (Pexels 5966140) — ett bildproblem, inte ett identitetsproblem. |
| E9 | `kikartscurry` ↔ `kikartscurry-protein` | 0.455 | 0.837 | LEGITIM VARIANT (protein) | Kikärtor 380 g med wokgrönsaker mot kikärtor 800 g med spenat, lök, vitlök och currypasta. Proteinvarianten har dubbla mängden kikärtor och 22 g mot 13 g — skillnaden finns i köpet. Samma bild (Pexels 7364662). |
| E10 | `falukorv-ugn` ↔ `torsk-potatismos` | 0.333 | 0.857 | OLIKA RÄTTER | Namnlikhetens fälla: "Ugnsbakad falukorv med potatismos" / "Ugnsbakad torsk med potatismos". Falukorv 500 g med senap, ost och tomat mot torskfilé 600 g med citron och dill. Bara moset är gemensamt. |
| E11 | `kyckling-ris-mild` ↔ `kycklinggryta` | 0.250 | 0.894 | OLIKA RÄTTER | "Mild kycklinggryta med ris" / "Kycklinggryta med ris" — grädde 200 ml, paprika, buljong mot kokosmjölk, curry, wokgrönsaker. Två olika såser; namnet ljuger. |
| E12 | `tonfiskpasta` ↔ `tonfiskpasta-citron` | 0.500 | 0.807 | OLIKA RÄTTER | Krämig tonfiskpasta (crème fraiche 2 dl, rödlök, frysta ärtor, `laktos`) mot oljebaserad (kapris 30 g, vitlök, persilja, `laktosfritt`). Två närbesläktade rätter med samma bild (Pexels 5864362); namnen borde skilja dem tydligare (avsnitt 10). |
| E13 | `ugnstorsk` ↔ `torsk-potatismos` | 0.500 | 0.722 | OLIKA RÄTTER | Ugnsbakad torsk i båda; sparris med citronsmör och kokt potatis mot potatismos med dill. Olika tillbehör, samma bild (Pexels 11044248). |
| E14 | `kalvschnitzel` ↔ `kalvschnitzelmatvete` | 0.600 | 0.606 | OLIKA RÄTTER | Samma panerade schnitzel; kokt potatis med kapris och brynt smör mot ljummen matvetesallad med paprika. Samma bild (Pexels 33865567). |
| E15 | `flaskkarre` ↔ `flaskytterfile-appelmos` | 0.308 | 0.481 | OLIKA RÄTTER | Stekta skivor med rödkål, äppelmos och kokt potatis (20 min) mot helstekt karré i ugn med rostade rotfrukter (60 min). Samma bild (Pexels 7333166). Id:na är korsvis fel mot innehållet — se avsnitt 10. |
| E16 | `fetagryta` ↔ `halloumigryta-tomat` | 0.385 | 0.655 | OLIKA RÄTTER | Kikärtor i tomatsås i båda; feta 200 g som smulas i mot halloumi 400 g som steks, plus spenat och ris. Samma bild (Pexels 33755318). |
| E17 | `kycklingsoppa-nudlar` ↔ `kycklingsoppa-ris` | 0.200 | 0.712 | OLIKA RÄTTER | Äggnudlar, ingefära, vitlök (`gluten`, `ägg`) mot ris, persilja (`glutenfritt`). Två kycklingsoppor, samma bild (Pexels 8696571). |
| E18 | `tomatsoppa` ↔ `tomatsoppa-grillost` | 0.273 | 0.417 | OLIKA RÄTTER | Samma soppa, men den ena är `lunch` (330 kcal, 8 g protein) och den andra `middag` med grillade ostmackor (bröd 8 st, riven ost 200 g; 520 kcal, 20 g). Olika måltidstyp — veckoplaneraren ser dem aldrig i samma urval. Samma bild (Pexels 2421593). |
| E19 | `svarta-bonor-tacos` ↔ `tacos-kottfars` | 0.167 | 0.494 | OLIKA RÄTTER | Bönröra med majssalsa, avokado, lime och koriander mot köttfärs med ost och crème fraiche. Vego-tacos är en egen rätt. Delar bild med båda köttfärstacosen (Pexels 28895976). |
<!-- extra:slut -->

---

## 7. Föreslagna grupper: kanoniskt id och alias

Tio grupper. Varje rad är ett par som är klassat som samma rätt i avsnitt 4
eller 6. Receptet i kolumnen *kanoniskt* blir kvar med sitt innehåll; id:t i
kolumnen *alias* tas ur källorna som recept och deklareras i stället som
`aliases` på det kanoniska (paket 2). Ingen grupp har fler än två medlemmar.

<!-- aliasgrupper:start -->
| kanoniskt | alias | klass | varför just det id:t |
|---|---|---|---|
| `tacos-kottfars` | `kottfars-tacos` | SAMMA RÄTT, NAMNVARIANT | Båda kompletta. `tacos-kottfars` har legat i drift längst (batch01, 2026-08-31 mot batch11, 2026-09-01), är nycklad i `classify_recipe_pantry.py` (`MANGDER`), och bär `kott`/`proteinrikt` som receptsidans filter (`TAG_LABELS`) frågar efter. |
| `ugnslax-citron` | `lax-kall-dillsas` | SAMMA RÄTT, NAMNVARIANT | `ugnslax-citron` är det id de gamla tabellerna nycklar på (`legacy-catalog.js`: `RECIPE_QUANTITIES`, `RECIPE_DETAILS`), det id `test_recipe_identity.py` låser, det äldre (batch05), och det som har örtsåsen komplett (dill + gräslök). |
| `flaskfile-rotfrukter` | `flaskfilerotmos` | SAMMA RÄTT, NAMNVARIANT | Det kompletta receptet: rödlök, bryning, fiber, svårighetsgrad, ett namn som säger vad som ligger på tallriken. `flaskfilerotmos` har bacon i stegen men inte i köpet, och "rotmos" i id:t utan mos i receptet. Referenserna till `flaskfilerotmos` är syntetisk testdata (`test_fyndsidan.py`, `tests/ikvall.test.js`) och ett historiskt skript — ingen läser banken. |
| `linsbolognese` | `linsbolognese-proteinrik` | SAMMA RÄTT, NAMNVARIANT | Namnet är rättens, spaghettin i ingredienserna är spaghettin i namnet, buljongen ger smak som stegen räknar med. Proteinvarianten saknar proteinkälla. `MANGDER` i `classify_recipe_pantry.py` har en rad `("linsbolognese-proteinrik", "oregano")` som blir död — paket 2 tar bort den. |
| `flaskpannkaka` | `ugnspannkaka-bacon` | SAMMA RÄTT, NAMNVARIANT | Rättens eget namn och den enda licensierade bilden av just den rätten i banken (Wikimedia Commons, CC BY 2.0, `assets/recipes/flaskpannkaka.jpg`). `ugnspannkaka-bacon` är äldre (batch01) och bär `familj`/`barn`-etiketter som `flaskpannkaka` saknar — det är etikettinnehåll för Recept 2.0, inte ett identitetsskäl. |
| `lax-teriyaki` | `teriyakilax` | SAMMA RÄTT, NAMNVARIANT | Riktig glaze med mängder, vitlök, sesam och kompletta allergener. `teriyakilax` är batch00:s tunna version; dess två rader i `MANGDER` (`ingefara`, `honung`) blir döda och tas bort i paket 2. `DISH_TERMS_EN["teriyakilax"]` i `images.py` är ett ordboksuppslag på namn, inte på id, och rörs inte. |
| `pannkakor` | `pannkakor-klassiska` | SAMMA RÄTT, NAMNVARIANT | Kortaste id:t, rättens namn rakt av, äldst (batch01). Båda kompletta; `pannkakor-klassiska` tillför sylt och grädde som tillbehör. |
| `vegansk-bolognese-vegofars` | `vegobolognese` | SAMMA RÄTT, NAMNVARIANT | Elva rader mot sex; morötter, vitlök, tomatpuré, buljong, oregano, fiber, svårighetsgrad. `vegobolognese` är batch00:s skiss av samma rätt. |
| `linssoppa-rod` | `linssoppa` | SAMMA RÄTT, NAMNVARIANT | Rader var för sig ("Gul lök", "Vitlök" i stället för "Lök & vitlök 150 g"), salt, fiber, svårighetsgrad, etiketterna `soppor`/`vardagsmat`. `test_e2e_vantan.py` använder redan `linssoppa-rod`. |
| `rakpasta-vitlok` | `scampi` | SAMMA RÄTT, NAMNVARIANT | Mängder på allt, chili, kompletta etiketter (`pasta`, `vardagsmat`) och trovärdiga näringstal. `scampi` (batch00) har kcal 307 och fett 1 g för en rätt stekt i "rikligt med olivolja". |
<!-- aliasgrupper:slut -->

Fem av de tio aliasen (`flaskfilerotmos`, `teriyakilax`, `vegobolognese`,
`linssoppa`, `scampi`) — plus det kanoniska `ugnslax-citron` och `pannkakor`
— ligger i den **nuvarande** reservbanken (`frontend/app/data/recipes.json`,
58 recept). Det är de id användarnas favoriter och veckor bar innan banken
växte. Aliasmekanismen är alltså inte en artighet mot gamla länkar; den är
det som gör att en favorit sparad i augusti fortfarande öppnas i oktober.

---

## 8. Allt som refererar recept-id

Det här är listan paket 2 måste gå igenom. "Ogenomskinlig" betyder att
servern lagrar strängen utan att tolka den — migrering måste då ske där
strängen *läses*, inte där den lagras.

### 8.1 Datalager

| lager | var | vad | tolkas av servern? |
|---|---|---|---|
| Receptbanken | `recipes.db`: `recipes.id` (PK), `recipes.slug` (UNIQUE), `recipe_ingredients.recipe_id`, `recipe_steps.recipe_id`, `recipe_labels.recipe_id` (FK, `ON DELETE CASCADE`) | id:t självt, och prisstämpeln per recept (`set_price`, kolumnerna `price_*`) | ja — `store.get()` slår upp på `id = ? OR slug = ?` |
| Kontosynk | `accounts.db`: `users.synced_state` (TEXT, JSON, ≤ 200 KB; `get_synced_state`/`set_synced_state` i `services/accounts/store.py`) | appens hela tillstånd: `favoriter[]`, `valda[]`, `weekPlan[]` (dagordning, index 0 = måndag), `weekHistory[].plan[]` (tolv veckor), `apiRecipes[].id` (valda receptposter), `betyg{id}`, `feedback{id}`, `savingsLog[]` (veckonyckel = sorterade id sammanfogade med `\|`, `savings-log.js`) | **nej — ogenomskinlig** |
| Hushåll | `household.db`: `household_docs` (`doc` ∈ `week`/`settings`/`staples`/`history`, `body` JSON ≤ `MAX_DOC_BYTES`; `set_doc`/`get_doc`/`docs_since`) | veckodokumentets `body.weekPlan[]` (`test_household_api.py:224`, `e2e/test_household_journey.py:185`); `shopping_items` med `source='week'` bär **ingrediensnamn**, inte recept-id | **nej — ogenomskinlig** |
| Appens lokala tillstånd | `localStorage` via `src/state/storage.js`; formen normaliseras av `FIELDS` i `src/state/app-state.js` (`favoriter`, `valda`, `weekPlan` = `names`; `weekHistory` filtreras på `plan`; `betyg`, `feedback` = `record`) | samma fält som kontoblobben | klienten |
| Reservbanken | `frontend/app/data/recipes.json` (58 handredigerade i dag; genereras ur källorna av `backend/scripts/generate_recipe_fallback.py` när P03a landar) | `id` per recept — de id veckogeneratorn planerar ur när backend inte svarar | klienten; `test_recipe_identity.py` kräver att varje id finns i källorna |
| Gamla tabellerna | `frontend/app/src/data/legacy-catalog.js`: `RECIPE_QUANTITIES`, `RECIPE_DETAILS` nycklade på id (bl.a. `ugnslax-citron`, `chili-sin-carne-budget`) | mängder och steg för recept utan strukturerade ingredienser (`app.js:625`) | klienten; `test_recipe_identity.py` kräver att varje nyckel är ett känt id |
| Service worker | `frontend/app/sw.js` cachar på exakt URL: `/api/recipes/<id>` och navigeringar med `?recept=<id>` | id i URL:er | klienten |
| Djuplänkar | `?recept=<id>` (`src/views/recipes.js:205` `openRecipeTab`, `renderRecipePage` slår upp `item.id === id` i banken; ett id med `:` hämtas från providern via `recipeDetailApiUrl`) | id i delade adresser, mejl och pushnotiser | klienten |
| Utskick | `services/mailings.py` `deals_menu()` ← `recipes_api.week_candidates()` via `api_server.py:728` — bär `name`, `slug` och `ingredientNames` | **slug**, inte id | servern; slug slås upp av `store.get()` |

`ogillar`, `avklarade`, `removedItems` och `harHemma` bär ingrediens- och
varunamn, inte recept-id (`app.js:2851–2865`, `DISLIKE_SUGGESTIONS`). Push
(`services/push/`, `weekly-push.js`) bär inga recept-id.

### 8.2 Kodvägar som slår upp ett recept per id

| var | vad den gör | vad som händer med ett okänt id |
|---|---|---|
| `services/recipes/store.py` `RecipeStore.get(recipe_id)` | `SELECT … WHERE id = ? OR slug = ?` | `None` |
| `store.id_for_slug(slug)` | slug → id | `None` |
| `store.delete`, `store.set_price`, `upsert_recipe` | skriver per id | — |
| `services/recipes/api.py` `get(recipe_id)` | cachar 120 s på det **begärda** id:t | `None` |
| `api.search`/`shelves`/`week_candidates` | listprojektioner med `id` och `slug` | — |
| `api.bootstrap_if_empty` | upsertar källornas id och **beskär** allt som inte längre finns i källorna | ett borttaget id försvinner ur banken vid nästa deploy |
| `api_server.py:2858` `GET /api/recipes/<id>` | `recipes_api.get()`; 300 s cache-header | **404** `{"error": "Receptet finns inte"}` |
| `api_server.py:3709` `_recipe_items(payload)` | `recipeIds[]` + `people` → `store.get()` per id → prissatta inköpsrader | okänt id **hoppas över tyst** ("a stale week from before a recipe was retired") |
| `api_server.py:3940` `_paywall_refuses_week` | räknar middagar som `len(recipeIds)` | räknar med okända id |
| `api_server.py:2916` `GET /api/v1/recipes/<id>` | providerrecept (TheMealDB), id med `:` | 404 |
| `scripts/backfill_recipe_images.py` | `store.get(recipe["id"])` → `upsert_recipe` | — |
| `scripts/classify_recipe_pantry.py` `MANGDER` | `(recept-id, ingrediens-id) → mängd` för rader som blir köpvara; `ratta_rad` slår upp per recept | en nyckel utan recept är död vikt |
| `scripts/check_product_data.py` | itererar `SELECT id FROM recipes` | — |
| `services/recipes/images.py` `DISH_TERMS_EN` | ordbok på **namnord** (`pannkakor`, `raggmunk`, `teriyakilax` …), används på receptets namn | inget id-uppslag |
| `services/grocery/pricing.py:675` | `"raksallad"` är ett **produktord** i en uteslutningslista, inte ett recept-id | — |
| `src/state/app-state.js` `selectedRecipes()` | `state.weekPlan.map(id => all.find(r => r.id === id) ?? null)` | dagen blir `null` — en tom rad i veckan |
| `app.js:3758` `namnFör(id)`, `:3969` `receptNamn(id)` | namn ur `RECEPT`/`apiRecipes` per id (veckohistoriken, fyndraden) | `null`/`""` — historikposten tappar rättens namn (H3 tål det) |
| `app.js:3485` bytet (`data-choose-swap`), `:3395` `weekPlan.indexOf(currentId)` | id per dag | — |
| `src/services/swap.js:131` `recentlyEatenPenalty(recipeId, weekHistory)` | jämför kandidatens id mot historikens `plan[]` | ett omdöpt id ger ingen straffpoäng — rätten kan komma tillbaka direkt |
| `app.js:117–153` betyg och gilla/ogilla | `state.betyg[id]`, `state.feedback[id]` | tappas för det gamla id:t |
| `app.js:2576` `ensureWeekRecipeDetails` → `loadRecipe(id)` | hämtar detaljer per id; `null` vid 404 stoppar omförsök | — |
| `src/views/recipes.js:284` `renderRecipePage` | `allRecipes.find(item => item.id === id)` | "Hämtar receptet…" tills banken laddat; sedan tomt |
| `src/services/recipe-search.js:9` | dedupe på `item.id` | — |

### 8.3 Hårdkodade id i kod, tester och dokument

Bara id som ingår i ett par ovan. `backend/recipe_sources/` och
`frontend/app/data/recipes.json` är undantagna (de *är* banken).

| id | var | sort |
|---|---|---|
| `tacos-kottfars` | `scripts/classify_recipe_pantry.py:112` | `MANGDER`-nyckel (paprikapulver) |
| `ugnslax-citron` | `tests/test_recipe_identity.py:126`, `src/data/legacy-catalog.js:117,178` | låst id→namn; legacy-tabeller |
| `chili-sin-carne-budget` | `tests/test_recipe_identity.py:122`, `legacy-catalog.js:119,180` | låst id→namn; legacy-tabeller |
| `flaskfilerotmos` | `services/site/fynd_page.py:18` (docstring), `tests/test_fyndsidan.py:65,119`, `tests/ikvall.test.js:528`, `docs/PAKET-C11-fynd.md`, `scripts/compute_recipe_nutrition.py` | syntetisk testdata med egen namntabell; historiskt skript |
| `flaskcurrygryta` | `tests/test_fyndsidan.py:65,120`, `docs/PAKET-C11-fynd.md`, `compute_recipe_nutrition.py` | syntetisk testdata; historiskt skript |
| `linsbolognese-proteinrik` | `classify_recipe_pantry.py:117` | `MANGDER`-nyckel (oregano) |
| `teriyakilax` | `classify_recipe_pantry.py:79,85,90`, `services/recipes/images.py:223` (namnord), `compute_recipe_nutrition.py` | `MANGDER`-nycklar (ingefära, honung); ordbok på namn |
| `kikartscurry-protein` | `tests/test_recipe_labels.py:74` | `BADGE_PER_RECEPT` |
| `spaghetti-kottfarssas`, `torsk-potatismos` | `tests/test_recipe_labels.py:72,75`, `classify_recipe_pantry.py:115` | badge-test; `MANGDER` |
| `kottfarssas` | `tests/test_household_api.py:224`, `e2e/test_household_journey.py:185`, `tests/test_e2e_vantan.py:63,66`, `classify_recipe_pantry.py:59,76`, `images.py:193` | veckoplaner i hushålls- och E2E-tester; `MANGDER` |
| `kycklinggryta` | `tests/test_recipe_store.py:20–71` (egen fixtur), `tests/auth_e2e.py`, `tests/prod_persistence_e2e.py` (körs inte av `run.py`), `images.py:198` | fixtur; manuella E2E-skript |
| `linssoppa-rod` | `tests/test_e2e_vantan.py:63` | veckoplan i E2E |
| `linssoppa` | `tests/auth_e2e.py:62` (körs inte av `run.py`) | manuellt E2E-skript |
| `pannkakor`, `raggmunk`, `linsbolognese`, `kottfarssas` | `images.py:192–221` | namnord i `DISH_TERMS_EN`, inte id |
| `raksallad` | `services/grocery/pricing.py:675` | produktord, inte id |
| `flasktomatpasta`, `halloumipasta`, `rakcurry`, `tofucurry`, `kikartscurry`, `morotscurry`, `biffgraddtimjan`, `biffmedlok`, `laxsallad`, `raksallad` | `scripts/compute_recipe_nutrition.py` `RECIPE_QUANTITIES` | historiskt engångsskript för de 58 |

Inget i listan bryts av att ett alias-id försvinner som recept: de tre
`MANGDER`-raderna blir döda nycklar (paket 2 tar bort dem), de syntetiska
testerna bär sina egna namntabeller, och `kottfarssas`/`ugnslax-citron`/
`chili-sin-carne-budget`/`linssoppa-rod` är alla kanoniska eller orörda.

---

## 9. Vad paket 2 måste göra

Det som klassificeringen kräver av `P04b`, med de vägval som är avgjorda
här så att koden inte behöver avgöra dem. **Genomfört i P04b** — de tio
grupperna i avsnitt 7 är deklarerade som `aliases` i källfilerna, och
`backend/tests/test_receptalias.py` är acceptansen.

1. **Modellen.** Det kanoniska receptet bär `"aliases": ["…"]` i sin källfil;
   aliasreceptet tas bort ur källorna. Banken får en tabell
   `recipe_aliases(alias_id TEXT PRIMARY KEY, recipe_id TEXT REFERENCES
   recipes(id) ON DELETE CASCADE)` — rent additiv, så K6:s
   återställningsregler håller. `RECEPT` i `services/schema_version.py` bumpas
   till 3 och `fixturer/scheman/recept.sql` regenereras med
   `test_migrationer.py --spara` (bara den fixturen committas). `_to_dict`
   exponerar `canonicalId` (= `id`) och `aliases`.
2. **Uppslaget.** `store.get(x)` prövar `recipes.id`/`slug` **först** och
   `recipe_aliases` sedan. Ordningen är rollbackplanen: återställs ett
   aliasrecept ur git (`git revert`) finns id:t både som rad och som alias,
   och raden vinner. `id_for_slug` oförändrad.
3. **`GET /api/recipes/<alias>` svarar 200 med det kanoniska receptet —
   transparent, inte 302.** Skälen: `fetch` följer en 302 ändå, så klienten
   vinner inget; service workern cachar på exakt URL och en 302 ger två
   cacheposter för samma rätt; djuplänkar i mejl och delningar bär det gamla
   id:t och ska bara fungera; och klienten jämför redan `recipe.id` i svaret
   — som är det kanoniska — med det den bad om. Cachenyckeln i `api.get`
   förblir det begärda id:t.
4. **Veckoplaneraren föreslår aldrig två id i samma grupp** — av konstruktion:
   `search`/`week_candidates` läser `recipes`, och ett alias är ingen rad.
   Testet skriver ändå ut det: för varje aliasgrupp finns högst ett av dess
   id bland `week_candidates()` och i reservbanken, och
   `/api/recipes/<alias>` och `/api/recipes/<kanoniskt>` ger samma `id`.
5. **Migreringen sker där strängarna läses.** Servern tolkar varken
   `synced_state` eller `household_docs` — och ska inte börja: en klient med
   gammalt lokalt tillstånd skulle skriva tillbaka de gamla id:na i nästa
   synk. I stället: banken (API-listan och den genererade reservbanken) bär
   `aliases`, klienten bygger `alias → kanoniskt` ur den och skriver om
   `favoriter`, `valda`, `weekPlan`, `weekHistory[].plan`, `apiRecipes[].id`,
   `betyg`, `feedback` — i `loadRecipes().then()` innan första veckoritningen
   och i `applySyncBlob`. Idempotent: bara id som är alias i den laddade banken
   rörs. Slår `betyg`/`feedback` ihop två nycklar behålls det högsta betyget
   och `liked`/`disliked` som redan står på det kanoniska. En vecka där
   alias och kanoniskt stod på två dagar blir samma rätt två dagar —
   användarens vecka hittas inte på; nästa "Skapa ny vecka" rättar det.
   `savingsLog`-nycklar är historik och lämnas.
6. **Rollback.** Kod: föregående release läser `recipes` utan att känna
   `recipe_aliases` — tabellen är osynlig för den, och alla kanoniska id
   finns i dag, så en klient som redan migrerat pekar på recept som också
   den gamla banken har. Data: `bootstrap_if_empty` beskär borttagna recept
   vid nästa deploy och återställer dem vid en revert av källfilerna; ett
   alias-id som återuppstår som recept vinner över aliastabellen (punkt 2).
7. **Städning i samma paket.** De tre döda `MANGDER`-raderna
   (`linsbolognese-proteinrik`/oregano, `teriyakilax`/ingefära och honung);
   reservbanken genereras om (`generate_recipe_fallback.py`) om P03a hunnit
   landa, annars regenereras den av P03a. `recipe_ingredients` och
   `normalized_id` rörs **inte** — P05b kan bygga ovanpå utan att vänta.

---

## 10. Utanför paketet — noterat för Recept 2.0

Innehåll, inte identitet. Ingenting av det här ändras av P04a eller P04b.

- **Bacon utan bacon.** `flaskfilerotmos` lindar filén i bacon i steg 3;
  ingen baconrad finns. Vill Recept 2.0 ha en baconlindad variant är det ett
  nytt recept med baconet i köpet — inte en återuppväckning av aliaset.
- **Id som säger fel sak.** `stekt-strommingsflundra` är torsk;
  `flaskkarre` har fläskfilé i ingredienserna och "karrén" i stegen, medan
  `flaskytterfile-appelmos` har fläskkarré; `flaskfilerotmos` har inget mos;
  `linsbolognese-proteinrik` har "fullkornspasta" i namnet och "Pasta" i
  köpet. Id är stabila nycklar och ska inte döpas om för det — men namnen
  och raderna kan rättas.
- **Näringstal som inte hänger ihop.** Tacos 590/620 kcal på samma köp;
  linsbolognese 22/30 g protein på samma 300 g linser; kikärtscurry med
  spenat 22/15 g på 800/760 g kikärtor; `scampi` 307 kcal och 1 g fett med
  "rikligt med olivolja"; `ugnstorsk` 264 kcal och 1 g fett med smör.
- **Sammanslagna rader från batch00.** "Lök & vitlök 150 g" (`linssoppa`),
  "Kryddor" (`vegobolognese`), "Curry & grönsaker" — rader som inte går att
  prissätta som en vara.
- **Delade bilder.** 40 bilder på flera recept; nio bowls på ett foto, nio
  grytor på ett annat, alla tre chilin på ett tredje. Det är K-spårets
  (`GOOD_VARIANT`/`EXACT`) fråga.
- **Tre kokoscurryn samma vecka.** Curryklumpen och pastaklumpen är
  variationsproblem för planeraren (`proteinkalla` skiljer dem, `bas` gör
  det inte).
- **Namn som borde skilja.** "Tonfiskpasta med citron" mot "… och kapris"
  är krämig mot oljebaserad; "Mild kycklinggryta med ris" mot
  "Kycklinggryta med ris" är grädde mot kokos. Namnen säger inte det.
- **Två soppor i klassen `lunch`** (`tomatsoppa`) och `middag`
  (`tomatsoppa-grillost`) med samma bild — rätt klassade, fel bild.
