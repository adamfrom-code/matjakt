# Volymvikter att granska — inte ändrade

Livsmedelsverkets PM 2024 *Volymvikter, viktförändringsfaktorer och avfall*
har mätvärden som avviker från prismotorns nuvarande antaganden för fler
varor än tomatketchup.

**Ingen av dem är inlagd.** En tabellrad med liknande namn är inte en
granskad produktmatchning. Det här dokumentet finns för att skillnaderna
ska gå att bedöma en och en, med källa, produktfråga och konsekvens — inte
för att de ska bytas i klump.

Källa för samtliga:
<https://www.livsmedelsverket.se/globalassets/publikationsdatabas/pm/2024/pm-2024-volymvikter-viktforandringsfaktorer-och-avfall.pdf>

Referens 1 i rapporten = "Volymviktsförsök utförda på Livsmedelsverket
2022-23", alltså myndighetens egen mätning.

---

## Vad som redan är ändrat

| Vara | Motorn | Källan | Var |
|---|---|---|---|
| Tomatketchup | 1,00 g/ml | **1,20 g/ml** | Tabell 10, s. 16. tsk 6 g (n=20), msk 18 g (n=20) |
| Tomatpuré | ingen (estimat) | **1,20 g/ml** | Vikttabellen (källa 2), kod 1138 "Tomatpuré konserv, konc": 1 msk 18 g, 120 g/dl — P06b |
| Sirap | ingen (estimat) | **1,40 g/ml** | Vikttabellen, kod 8003 "Sirap ljus": 1 tsk 7 g, 140 g/dl — P06b |
| Honung | ingen (estimat) | **1,40 g/ml** | Vikttabellen, kod 8004 "Honung": 1 tsk 7 g, 140 g/dl — P06b |

Se `VERIFIED_DENSITY_G_PER_ML` i `backend/services/grocery/pricing.py`.

### Källa 2: Livsmedelsverkets vikttabell (P06b)

PM 2024 väger varken tomatpuré, sirap eller honung. Det gör Livsmedelsverkets
äldre **vikttabell** — "Texter i den tryckta vikttabellen", uppdaterad senast
2001, med de gamla livsmedelskoderna. Kolumnerna är g per mått och g/dl.
Myndigheten tillhandahåller inte längre filen själv; kopian som lästs ligger
på <https://surdegsmakarn.wordpress.com/wp-content/uploads/2012/06/vikttabell.pdf>
(rubriken "OBS! Viktabellen uppdaterades senast 2001 och har gamla
livsmedelskoder").

**Kontrollen som gör att den får användas:** tabellens rad "1048 Tomatketchup,
1 msk 18 g, 120 g/dl" är exakt vad PM 2024 mätte upp tjugo år senare (msk
18 g, n=20). De två källorna säger samma sak där de överlappar.

**Ingen motstridig väg.** För alla tre ger måttet och decilitern samma tal:
18/15 = 1,20 och 120/100 = 1,20; 7/5 = 1,40 och 140/100 = 1,40.

**Produktfrågan.** Tomatpuré i handeln är alltid koncentrerad (tub eller
burk), tabellradens vara. Receptbanken skriver "Sirap" och menar ljus sirap;
mörk sirap får samma tal — det är samma sockerlösning och en egen mätning
saknas. **Avvikande källa, inte gömd:** USDA väger en amerikansk matsked
(14,8 ml) tomatpuré till 16 g, ~1,08 g/ml. Den svenska myndighetens tal på
den svenska varan används; skillnaden (10 %) kan flytta antalet burkar bara
vid en paketgräns (4 msk mot en 70 g-burk: 72 g mot 65 g).

---

## Att granska

### Mejeri — tabell på s. 15

Motorn behandlar samtliga som 1 g = 1 ml via `DAIRY_DENSITY_ONE`.

| Källans livsmedel | Uppmätt | n | Motorn nu | Produktfrågan |
|---|---|---|---|---|
| Crème fraiche | 95 g/dl | 10 | 100 g/dl | Källan har både "Crème fraiche" och "Crème fraiche, lätt" (98 g/dl). Receptbanken skiljer inte på fetthalt — vilken gäller? |
| Yoghurt, grekisk | 108 g/dl | 10 | 100 g/dl | Motorn har både "yoghurt" och "grekisk yoghurt". Källan mäter bara den grekiska; vanlig yoghurt saknas |
| Filmjölk, naturell | 110 g/dl | 20 | 100 g/dl | Källan skiljer naturell (110) från smaksatt (112). Recepten säger bara "Filmjölk" |
| Kvarg, smaksatt | 111 g/dl | 10 | 100 g/dl | Källan mäter bara den **smaksatta**. Naturell kvarg saknas, och det är den recepten oftast menar |
| Mjölk, lättmjölk 0,5 % | 98 g/dl | 20 | 100 g/dl | Källan mäter per fetthalt (lätt 98, mellan 99). Recepten säger "Mjölk" utan fetthalt |

**Konsekvens för matkassarna.** Alla fem ligger inom ±11 % av 1,00.
Effekten uppstår bara när avvikelsen flyttar antalet förpackningar, alltså
nära en paketgräns. Störst är kvarg och filmjölk (+10–11 %), som skulle
kunna kräva en extra förpackning vid stora mängder; crème fraiche och mjölk
går åt andra hållet och skulle kunna spara en.

**Varför de inte är inlagda.** Fyra av fem rader kräver ett produktval som
receptbanken i dag inte gör: fetthalt för mjölk och crème fraiche, naturell
mot smaksatt för kvarg och filmjölk. Att välja en av dem åt användaren är
ett produktbeslut, inte en omräkning.

### Bakvaror — tabell på s. 13

| Källans livsmedel | Uppmätt | n | Motorn nu (`BAKING_GRAMS_PER_DL`) |
|---|---|---|---|
| Vetemjöl | 56 g/dl | 50 | 60 g/dl |
| Havregryn | 39 g/dl | 30 | 35 g/dl |

**Produktfrågan.** Motorn använder samma tal för `vetemjol` och `mjol`.
Källan mäter en specifik vara; siktat mjöl väger mindre än osiktat, och
"havregryn" finns som stora och snabba. Vilken variant som är vägd framgår
inte av tabellraden.

**Konsekvens.** Vetemjöl −7 %, havregryn +11 %. Bakrecept i dl är vanliga i
banken, så det här slår bredare än mejerivarorna.

---

## Vad som INTE finns i någon av källorna

Currypasta och sambal oelek. Ingen av Livsmedelsverkets tabeller väger dem,
och de får därför **ingen densitet** (`verified_density` svarar None,
låst av `test_de_tva_osakra_far_ingen_pahittad_siffra`).

Deras paketantal är ändå säkert i receptens mängder, utan att någon densitet
antas: ingen matvara väger över 2 g/ml (tabellens tyngsta är sirap och honung
på 1,40), så 1 tsk sambal oelek (5 ml) väger högst 10 g och 1 msk currypasta
(15 ml) högst 30 g — båda ryms i varje burk i handeln. Motorn räknar då
**en** förpackning och märker raden exakt, på samma grund som torra kryddor:
en övre gräns, inte en uppskattning (`THICK_PASTES`,
`PASTE_MAX_DENSITY_G_PER_ML` i `pricing.py`, P06b). Behöver ett recept mer
än gränsen ger — 2 dl currypasta mot en 200 g-burk — förblir raden ett
ärligt estimat.

Tomatpuré, sirap och honung, som tidigare stod här, har fått sina tal ur
vikttabellen (källa 2 ovan).

---

# Styckvikter att granska (`STYCK_VIKT_G`)

Samma princip, annan tabell. `STYCK_VIKT_G` i
`backend/services/grocery/pricing.py` säger vad "N st" av en vara väger, och
den siffran avgör hur många förpackningar veckan kräver. Tre rader
granskades i samband med C3 (vitlöksklyftorna). Bara den som gick att belägga
mot receptbankens egna rader ändrades.

## Ändrad: vitlök

`"vitlok": 70` står kvar — **en hel knopp väger 70 g, och "1 st vitlök" ÄR en
knopp**. Felet låg inte i talet utan i att receptbanken skrev "Vitlök 3 st"
och menade tre *klyftor*. Klyftan har fått en egen enhet och en egen vikt
(`KLYFT_VIKT_G`, 5 g) och banken normaliserades till den. Se C3.

## Att granska: `korv: 60`

**Fynd mot receptbanken: regeln träffar aldrig banken.** Ingen rad i
receptbanken har `Korv` med enheten `st`. Samtliga korvrader är i gram:
Falukorv 300/400/500 g (13 recept), Wienerkorv 480 g, Grillkorv 600 g,
Korvbröd 270 g.

**Produktfrågan.** 60 g är en grillkorv eller en wienerkorv. Men "korv" i en
inköpslista kan lika gärna vara en falukorv på 800 g — mer än tretton gånger
så mycket. Talet gäller därför bara varor som en *användare* själv lägger
till, och där vet vi inte vilken korv som menas.

**Varför det inte är ändrat.** Ett tal som aldrig används av banken går inte
att belägga mot banken, och att välja korvsort åt användaren är ett
produktbeslut. Rätt åtgärd är sannolikt att skilja `grillkorv`/`prinskorv`
(styckvaror) från `falukorv` (gramvara) — inte att justera 60 uppåt eller
nedåt.

## Att granska: `brod: 35`

**Fynd mot receptbanken: två rader, och de kan mena olika saker.** `Bröd 8 st`
(ett recept) och `Bröd 4 st` (ett recept). Åtta bröd i ett recept är skivor —
varma mackor eller toast — och 35 g per skiva är rätt. Fyra kan vara skivor,
men kan lika gärna vara fyra frallor på 60–80 g.

**Konsekvens.** Skillnaden är 140 g mot 280 g på en rad. Mot en 800 g-limpa
flyttar det inte förpackningsantalet, så priset är detsamma i båda fallen —
det är därför den här raden är låg prioritet trots att den är osäker.

**Varför det inte är ändrat.** Talet stämmer för det ena receptet och
möjligen inte för det andra. Rätt åtgärd är att skriva ut vad recepten menar
(`brödskiva` finns redan i tabellen på 35 g), inte att gissa ett medelvärde.

## Granskad och oförändrad: `dill: 20`

**Receptbanken belägger talet själv.** Sju recept skriver `Dill 1 st`, och
banken skriver samma ört i gram i tio andra recept: 15 g (ett), 20 g (sex),
25 g (tre). En örtkruka eller ett knippe om ~20 g är alltså precis vad
recepten menar med "1 st dill". Ingen ändring behövs. Samma resonemang
gäller de övriga örterna på 20 g i tabellen, men bara dillen är belagd med
gramrader ur banken.
