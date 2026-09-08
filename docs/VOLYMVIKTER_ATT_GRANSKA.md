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

Se `VERIFIED_DENSITY_G_PER_ML` i `backend/services/grocery/pricing.py`.

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

## Vad som INTE finns i källan

Tomatpuré, sirap, currypasta och sambal oelek — de fyra rader som gör
prisrevisionen röd (se O10b i `MASTER_BACKLOG.md`). De förblir osäkra.
