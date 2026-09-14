---
paket: L2c
titel: En rect som är idel nollor är ingen mätning
---

L2b tog subpixelfelet: `getBoundingClientRect()` ger flyttal, en knapp med
`height:44px` läser tillbaka 44 − 2⁻¹⁵, och toleransen är en halv pixel. Det
här är ett annat fel med samma offer. Browser-E2E:n fällde en PR med

    AssertionError: 0 not greater than or equal to 44 :
    {'hojd': 0, 'vanster': False, 'hoger': False}

Noll rakt igenom — och `matt.minst(0)` är falskt hur vid toleransen än är. En
halv pixel räddar inte en nolla, och ska inte göra det.

## Varifrån nollan kom

Veckolistan ritas av `renderBasket`:

```js
$("weekPlanList").innerHTML = veckoDagarMarkup(selected, { idag: todayIndex() });
```

Varje omritning byter alltså ut **varje** `.vecka-dag`-nod. Mätningen slog upp
knappen i Python och mätte den i en andra CDP-vända:

```python
knapp = rad.locator("[data-week-add-meal]")
expect(knapp).to_be_visible()      # 1: finns den, syns den?
träff = knapp.evaluate("...")      # 2: hur stor är den?
```

Landar omritningen mellan de två mäter man en nod som inte sitter i dokumentet
längre, och `getBoundingClientRect()` på en avhängd nod är idel nollor.
**Playwright kastar inte på det** — den mäter villigt — så felet kommer
tillbaka som "knappen är 0 px hög" i stället för "noden byttes ut".

Det är samma familj som T2b:s avbockning, som läste listan i två steg med en
bildruta emellan. T2b lämnade den här: *"Den andra orsaken — subpixelmätningen
— hör inte hit och ligger i L2b."* Nollan var en tredje, och fanns kvar när
båda var lagade.

## Mätt, inte gissat

Tjugo mätningar av samma knapp i en riktig browser, med en omritning påtvingad
med flit — det lastad CI gör slumpvis:

| omritning | gamla mätningen | nya mätningen |
|---|---|---|
| ingen (som lokalt) | 0/20 nollor | — |
| var 2:a ms | **20/20 nollor** | **0/20 nollor** |

Lokalt hinner bildrutan alltid först och felet finns inte. Det är därför det är
CI:s fel och inte utvecklarens — precis vad T2b fann för avbockningen.

## Vad som ändrades

Mätningen bor i `tests/e2e/matt.py` och har två regler:

**Ett svep, inte två.** Noden söks upp **och** mäts i samma `evaluate()`. Inom
en JS-vända kan DOM:en inte bytas ut, så det finns inget glapp att dela
mätningen i. Under stormen ovan kostade den nya mätningen ett enda svep — min
*och* max — för den behövde aldrig göra om något. Det är atomiciteten som botar
flaket.

**Ett svep utan ritad nod är inget mätvärde.** Omtaget gäller det andra fallet:
vyn har inte ritats när testet tittar. Då är svaret "kom tillbaka nästa
bildruta", inte "noll pixlar".

Grinden blev **inte** slappare. En knapp som verkligen är 0 px — `display:none`,
en kollapsad förälder — ger samma svar varje svep och fälls när taket är slut.
Det som ändras är beskedet: `Oritad: ingen ritad nod att mäta efter 60 svep -
appen ritade den aldrig` är ett besked om appen, till skillnad från
`0 >= 43.5 är falskt`, som bara var ett besked om när Playwright råkade titta.

## Acceptanstest

`backend/tests/test_e2e_matt.py`, utan Playwright (samma skäl som L2b och
`test_e2e_avbockning.py`), mot en falsk knapp som gör exakt vad render-bussen
gör — byter ut noden under mätningen:

- den gamla enstegsläsningen mot samma sekvens **reproducerar
  `{'hojd': 0, ...}` ordagrant**, och den nya sveper förbi och mäter 44;
- en ritad nod kostar ett enda svep — omtaget är ett skyddsnät, inte en väntan;
- **en knapp som verkligen är 30 px fälls fortfarande** — vakten skiljer "inte
  ritad" från "ritad, och för liten";
- en som aldrig ritas fälls vid taket, med ett besked om appen.

Grinden `test_ingen_matning_gors_pa_en_nod_som_slagits_upp_i_python` **har setts
faila mot origin/main** och pekar då ut raden:

    test_consumer_journey.py:1085: knapp.evaluate(...) mäter en uppslagen nod

Den letade igenom alla e2e-filer: det var det enda stället. De övriga
mätställena — kap. 5-måtten i veckan och knappsvepet i `test_admin_panel.py` —
använder redan `page.evaluate()` och söker upp noden inne i JS, alltså ett svep.
