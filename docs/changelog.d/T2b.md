---
paket: T2b
titel: Avbockningen läser listan efter omritningen, inte efter skrivningen
---

Browser-E2E:n fällde slumpvis gröna PR:er. Två körningar på samma push föll
på olika tester, och `gh run list --workflow ci.yml --branch main` visade
`failure` för de fem senaste merge-committarna. En svit som är röd ungefär
lika ofta som den är grön lär alla — agenter och människor — att köra om
utan att läsa loggen, och det är den dyraste sortens trasigt test.

Det här paketet tar den ena av de två orsakerna:

    playwright._impl._errors.TimeoutError: Locator.get_attribute:
    Timeout 20000ms exceeded.
    waiting for locator("#shoppingList [data-bought]")

## Varifrån de tjugo sekunderna kom

T2 (#99) flyttade E2E:ns väntan från klockan till skrivningen: `wait_for_state`
väcks av att appen skriver `matjakt-state`. Det var rätt, och det räckte inte
— för avbockningsloopen **väntar på skrivningen och läser sedan DOM:en**, och
de två sakerna händer inte samtidigt. `setItemStatus` i `app.js`:

    saveState();          // skrivningen — den T2:s väntan väcks av
    invalidate("basket"); // omritningen — köad på requestAnimationFrame

Skrivningen först, omritningen en bildruta senare. Loopen läste dessutom i
**två steg**: `count()` svarar direkt, `get_attribute()` *väntar in* ett
element. Landade bildrutan mellan de två såg steg 1 den sista obockade raden
och steg 2 en lista där ingen finns kvar — och då väntade Playwright ut hela
sin tidsgräns på en rad som aldrig kommer tillbaka.

## Mätt, inte gissat

Den första gissningen var att DOM:en alltid ligger en bildruta efter. **Det
stämde inte.** En sond som mätte glappet i en riktig körning såg noll
inaktuella läsningar på femton avbockningar — omritningen hade redan landat
varje gång Python fick tillbaka kontrollen. En bildruta är 16 ms; de
CDP-vändor som ligger mellan skrivningen och nästa läsning mättes till
18–104 ms. Lokalt hinner bildrutan alltid först, och loopen får aldrig
tillfälle att läsa fel.

Det är därför felet är CI:s och inte utvecklarens. På en lastad maskin
skjuts bildrutan upp medan CDP-vändan inte gör det. Sonden bromsade därför
`requestAnimationFrame` med flit, och då föll det:

| 400 ms/bildruta | Utfall |
|---|---|
| den gamla tvåstegsläsningen | **FAILED** efter 62,8 s |
| samma lista genom `avbockning.py` | **OK**, 16 varor på 17,5 s |

Vid 60 ms kom den gamla loopen i mål — men på 51 sekunder i stället för
tio, för den snurrade på rader den redan bockat av. Samma fel, mildare form.

Tio körningar av `test_sparkvittot_star_dar_nar_listan_ar_avbockad` på
oförändrad main var **gröna alla tio**. Det säger inte att testet är friskt:
glappet är en CDP-vända brett, och en mätning som inte kan se det kan inte
heller frikänna det. Bromsen ovan är mätningen som kan.

## Vad som ändrades

Loopen bor i `backend/tests/e2e/avbockning.py` och har två regler:

**Ett svep, inte två.** Vad som är kvar läses i en enda `evaluate()`. Två
frågor med en omritning emellan ger svar om ett läge som aldrig funnits.

**Läs efter omritningen.** Efter varje avbockning väntas raden in som
avbockad i DOM:en (`data-need`, L3:s avbockade rad på sin plats) innan
listan läses om. Tidsgränsen finns kvar men betyder något annat: "appen
bokförde avbockningen men ritade den aldrig" är ett besked om appen, till
skillnad från "tjugo sekunder gick" som bara var ett besked om maskinen.

Grinden hittade **två call-sites till** med samma tvåstegsform — mätningen
av render-bussen (`count()` + `get_attribute()`) och ett `>> nth=0` i
Free-resan. Ingen av dem har fallit, för båda står med en orörd och full
lista. De hade gjort det. Båda fäster nu vid varans namn i stället för vid
"den nod som råkar ligga först just nu".

## Acceptanstest

`backend/tests/test_e2e_avbockning.py`, utan Playwright (samma skäl som
`test_e2e_vantan.py` och `test_e2e_matt.py`), 8 tester mot en falsk lista
som gör exakt vad render-bussen gör — skriver tillståndet direkt, ritar en
bildruta senare:

- loopen läser aldrig listan medan en bildruta är oritad;
- **den gamla tvåstegsläsningen mot samma lista reproducerar
  tjugosekunderskraschen**, och den nya kommer i mål;
- och det som verkligen är trasigt fäller fortfarande: en vara som inte går
  att bocka av, en som går tillbaka till obockad efter att ha ritats som
  avbockad, en lista som aldrig tar slut.

Grinden `test_ingen_annan_e2e_fil_bockar_av_listan_pa_egen_hand` **har setts
faila mot origin/main** och pekar då ut de tre raderna som bar mönstret.

## Det som inte var trasigt

E2E-jobbet kör sviten två gånger med flit — `test_*journey*` mot källan och
sedan mot `dist/frontend` — så de två `Ran 31 tests`-blocken i loggen är två
frontends, inte en omkörning. Båda är vanliga `run:`-steg: failar det första
faller jobbet där. `if: always()` i ci.yml sitter bara på rapportsteg
(täckningssiffran, död kod, artifact-uppladdning) och mjukar inte upp någon
grind. **Grinden är rätt kopplad** — det var mätningen inuti den som inte var
det.

Den andra orsaken — subpixelmätningen `43.999969482421875 >= 44` — hör inte
hit och ligger i L2b (#176).
