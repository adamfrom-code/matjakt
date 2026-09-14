---
paket: L2b
titel: Träffytans 44 px mättes som ett flyttal, och föll på 0,00003 px
---

L2:s acceptanstest mäter att plusknappen på en tom dag har en träffyta på minst
44 px. Knappen är `height:44px` i CSS. Testet läste tillbaka

    43.999969482421875

alltså **44 − 2⁻¹⁵**, och fällde bygget — senast på M4, en PR vars diff inte rör
en enda fil appen laddar i webbläsaren. Samma innehåll passerade vid omkörning.

## Var det kom ifrån

Inte ur CSS:en. `getBoundingClientRect().height` är `bottom − top`, och båda
är dubbel­precisionstal räknade från elementets plats på sidan. Ligger den
platsen på en bruten pixel — och det gör den, så fort något ovanför raden har
en fraktionell höjd — blir differensen av två sådana tal inte exakt 44.

Det syns i **vilken** körning som föll: CI kör E2E:n två gånger, mot källan och
mot `dist/frontend`. Källan gav 44 och passerade. Bundlet gav 44 − 2⁻¹⁵ och
föll. Samma CSS, samma knapp, samma webbläsare — bara ett annat läge på sidan.

Det gjorde grinden till ett lotteri: grön på L2:s egen PR, röd på nästa gren
som råkade ligga på fel sida av en subpixel. En grind som faller på något den
som läser den inte kan ändra lär den som ser den att sviten ljuger.

## Vad som ändrades

**44 px är ett mått på en tumme, inte ett flyttal.** Kravet kommer ur Apple HIG
och WCAG 2.5.5 och handlar om vad ett finger träffar; en tumme märker inte tre
hundratusendels pixel. Toleransen är en halv pixel — stor nog att äta varje
avrundning en layoutmotor kan hitta på, liten nog att en knapp som verkligen
krympt till 43,5 px fortfarande fälls.

Regeln bor i `backend/tests/e2e/matt.py` och har **en** definition:
`minst()`, `hogst()`, `golv()` och `TUMYTA_PX`. Att det blev en modul och inte
en rättad rad är hela poängen — det var inte en rad som var fel utan ett
mönster, och mönstret stod på fyra ställen när det upptäcktes:

| Var | Mätte | Nu |
|---|---|---|
| `test_consumer_journey.py` · plusknappens höjd | `>= 44` | `matt.minst()` |
| `test_consumer_journey.py` · sidoprobens kant | `(44 − r.width) / 2` | `matt.golv()` in i `evaluate()` |
| `test_consumer_journey.py` · rubrik, sjunde raden, summering | `>= 0`, `<= gräns` | `matt.minst()` / `matt.hogst()` |
| `test_admin_panel.py` · alla knappar vid 320/375/390 px | `.height < 44` i JS | mäts i JS, döms av `matt.for_sma()` |

Den sista var samma bugg en våning ned och hade inte fällt något ännu — den
råkade bara aldrig ligga på fel sida av en subpixel. Den hade gjort det.

Admin-mätningen döms numera i Python i stället för i webbläsaren, och bär med
sig **de uppmätta höjderna** ut i felmeddelandet. "Avbryt #3: 24.0" går att
åtgärda; "knappar under 44 px: ['Avbryt']" går att gissa om.

## Tre sessioner, tre lagningar av samma rad

Raden lagades tre gånger oberoende av varandra: `>= 43.5`, `round(hojd, 2) >= 44`
(som hann landa med L3, #151) och den här. Att det gick att göra tre gånger är
själva argumentet för att regeln ska ha ett hem i stället för en tröskel per
mätställe. `round(hojd, 2)` fungerar men tål bara ±0,005 px - en halv pixel
tål varje avrundning en layoutmotor kan hitta på.

L3:s session hittade dessutom en andra väg till samma rest: `.screen` bär
animationen `screen-in` (0,35 s), och en rect som mäts under en pågående
transform räknas ut med lägre precision än layouten. Den iakttagelsen är
bevarad i `matt.py`.

## Att grinden har kvar sina tänder

`backend/tests/test_e2e_matt.py` kör **utan Playwright** och prövar två saker.

Att toleransen är rätt satt: subpixelresten ur den riktiga CI-körningen räcker,
och 43,4 / 40 / 24 / 0 px fälls fortfarande.

Att ingen e2e-fil jämför ett uppmätt mått mot ett naket tal — Python-sidan läst
med `tokenize` (så att prosan i kommentarerna inte råkar räknas) och den
inbäddade JS:en läst ur strängarna, i båda leden. Det är den som gör att nästa
mätning ärver toleransen i stället för att uppfinna en egen tröskel. Båda
grindarna har setts faila mot `origin/main` och pekar då ut exakt de två rader
som bar mönstret.

Höjden är dessutom fortfarande bara ett av tre mått på plusknappen: `vanster`
och `hoger` trycker med `elementFromPoint` strax utanför den synliga kanten och
kräver träff — alltså att `.tapmin`-mönstret verkligen vidgar ytan i sidled. De
två mäter med en tumme i stället för med en linjal, och de rördes inte.
