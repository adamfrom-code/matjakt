# Delat läs-API (`/api/v1/shared/`)

Kontraktet andra appar läser Matjakt genom. Första konsumenten är **Ät Upp**
([adamfrom-code/at-upp](https://github.com/adamfrom-code/at-upp)), som hjälper
människor använda maten de redan har hemma.

Koden ligger i `backend/services/shared/`. Endpointsen är tunna omslag runt
den modulen — all logik som är värd något (kanonisering, matchning,
portionsskalning) är importerbar Python och testad för sig.

## Varför ett eget lager

Matjakts egen frontend deployas samtidigt som backend, så dess API får ändras
när som helst. En annan app gör det inte. Det som ligger under
`/api/v1/shared/` är därför ett kontrakt: det versioneras, det testas mot
sina fältnamn, och det innehåller bara sådant vi är beredda att stå för i
en annan kodbas.

Tre regler formar lagret:

1. **Bara läsning.** Ingenting under prefixet skriver. En delad app kan inte
   ändra Matjakts recept, priser eller konton.
2. **Inga priser i v1.** Se [Vad som inte delas](#vad-som-inte-delas).
3. **En implementation av matchning.** Ät Upp bygger inte en egen kopia av
   kanoniska ingredienser. Två implementationer blir två sanningar första
   gången någon lägger till ett alias.

## Åtkomst

Utvecklingslåset (`MATJAKT_GATE`) stänger hela `/api/`. En app släpps in på
sitt eget prefix med en **app-nyckel**:

```
X-Shared-Key: <nyckel>
```

Nycklar konfigureras med `MATJAKT_SHARED_API_KEYS` (kommaseparerat, en per
konsument så att en kan återkallas utan att slå ut de andra).

Nyckeln öppnar **bara** `/api/v1/shared/`. En läckt app-nyckel kan läsa
recept och ingenting annat — inte konton, inte priser, inte driftvägar. Utan
konfigurerad variabel finns ingen nyckel och ingen släpps in (fail-closed);
en tom sträng i listan filtreras bort så att `MATJAKT_SHARED_API_KEYS=` inte
gör en tom header giltig.

Nyckeln hör hemma i konsumentens **backend**, aldrig i en webbklient. Ät Upp
anropar Matjakt server-till-server just därför — då behövs ingen CORS-regel
och nyckeln når aldrig en webbläsare.

## Versionering

`contractVersion` (i `/meta`) höjs när ett fält **försvinner eller byter
betydelse**. Nya fält är inte en ny version — ingen konsument går sönder av
dem. En app kan läsa versionen vid start och vägra köra mot en den inte
känner igen.

## Endpoints

### `GET /api/v1/shared/meta`

Vad kontraktet lovar och vad banken innehåller just nu.

```json
{
  "contractVersion": "1.0",
  "recipeCount": 241,
  "defaultPantryStaples": ["salt", "peppar", "olja", "..."],
  "provides": ["recipes", "ingredients", "recipe-match"],
  "excludes": ["pricing", "products", "accounts"]
}
```

`excludes` är uttryckligt med flit: en app ska inte behöva gissa sig till vad
som saknas.

### `GET /api/v1/shared/recipes`

Kortprojektionen av receptbanken. Parametrar: `q`, `tag` (upprepad eller
kommaseparerad, AND:as), `maxTime`, `minProtein`, `maxKcal`, `limit`
(max 500), `offset`.

Korten bär `ingredientNames` men inte mängder — detaljsidan är den enda som
returnerar allt.

### `GET /api/v1/shared/recipes/{id|slug}`

Ett helt recept: ingredienser med mängder, instruktioner, näring, allergener,
kostflaggor och bild med licens.

`?servings=N` skalar mängderna (1–24). Skalningen sker i
`services/shared/portions.py`, inte hos anroparen, därför att den har fyra
fällor: skafferirader utan mängd ska förbli utan mängd, näring är redan per
portion och ska aldrig multipliceras, avrundningen ska gå att laga mat efter,
och receptet får inte muteras på plats (cachen delar ut samma objekt till
alla läsare).

Bilden följer alltid med `imageLicense`, `imageCredit` och `imageSourceUrl`.
En app som visar bilden måste kunna visa attributionen.

### `GET /api/v1/shared/ingredients`

Varje ingrediens banken känner, kanoniserad — underlaget för en apps
autocomplete. Den som skriver "lö" ska få **Matjakts** ord, inte ett ord
appen hittat på; annars matchar det användaren skrev aldrig det recepten
säger.

```json
{"ingredients": [
  {"id": "gul-lok", "name": "Gul lök", "generalId": "lok",
   "isPantryStaple": false, "recipeCount": 79}
], "total": 212}
```

### `POST /api/v1/shared/recipe-match`

Skafferi in, matchade recept ut. POST trots att ingenting skrivs: ett skafferi
är en lista, och listor i query-strängar blir trunkerade, dubbelkodade och
loggade.

```json
{
  "items": ["kyckling", "ris", "paprika", "creme fraiche"],
  "extraStaples": ["Vitlök"],
  "notStaples": ["Smör"],
  "maxMissing": 3,
  "limit": 60
}
```

`items` får vara strängar eller objekt med `name` (Ät Upps skafferi bär
mängd och bäst före; bara namnet betyder något här). Max 100 poster.

Svaret:

```json
{
  "matches": [{
    "recipe": { "...kort..." },
    "matchPercent": 83,
    "requiredCount": 6,
    "availableCount": 5,
    "missingCount": 1,
    "missingMainCount": 1,
    "missingStapleCount": 0,
    "canCookNow": false,
    "availableIngredients": [
      {"name": "Kycklingfilé", "id": "kycklingfile", "amount": 600, "unit": "g",
       "recipeStaple": false, "have": "kyckling", "match": "generic"}
    ],
    "stapleIngredients": [{"name": "Salt", "id": "salt", "...": "..."}],
    "missingIngredients": [
      {"name": "Gul lök", "id": "gul-lok", "amount": 1, "unit": "st",
       "recipeStaple": false}
    ]
  }],
  "pantry": [{"id": "kyckling", "name": "kyckling", "generalId": null,
              "isPantryStaple": false}],
  "staples": ["salt", "peppar", "..."],
  "recipeCount": 241
}
```

`pantry` säger hur skafferiet **tolkades**. Utan det kan en app inte skilja
"receptet finns inte" från "vi tolkade aldrig `creme fraiche` som crème
fraiche".

Recept där ingenting finns hemma returneras inte — det är receptbanken, inte
ett svar på "vad kan jag laga av det jag har". Skafferigrunden ensam räknas
inte som en träff: salt finns i nästan varje recept och hade annars gjort hela
banken till en träff.

#### Fältnamn

Uppgiften som beställde lagret skrev `match_percent`, `missing_count`,
`missing_ingredients`, `available_ingredients` och `can_cook_now`. Svaret
använder camelCase på alla fem, eftersom receptobjektet i samma payload är
camelCase hela vägen (`totalTime`, `imageAlt`, `pricePerPortion`) och en
payload med två namnkonventioner är värre än en med "fel". Mappningen är
en-till-en: `match_percent` → `matchPercent`, och så vidare.

## Matchningsreglerna

Modellen är **stängd som standard**. Två ingredienser hör ihop bara när något
säger det: samma kanoniska id, en strukturell regel (bestämningsord + vara),
eller en deklarerad tabell. Det finns ingen "de liknar varandra"-väg in.

Fyra relationer, alla märkta i svaret:

| `match` | Betyder | Exempel |
| --- | --- | --- |
| `exact` | samma vara | lök / Lök |
| `specific` | jag har en sort av det som behövs | Gul lök → Lök |
| `generic` | jag har det allmänna, receptet vill ha en sort | kyckling → Kycklingfilé |
| `substitute` | två sorter av samma sak | Kycklinglårfilé → Kycklingfilé |

Alla fyra räknas som "finns hemma", men märkningen gör att en app kan skriva
"du har lårfilé i stället för filé" i stället för att låtsas att det är samma
sak.

Ett sammansatt **ord** delas aldrig upp automatiskt. Det är precis det steget
som hade gjort kokosmjölk till mjölk. Därför faller de här ut som *ingen
träff*, utan spärrlista:

```
kycklingbuljong ≠ kyckling      tomatsås ≠ tomat      kanelknäcke ≠ kanel
kokosmjölk ≠ mjölk              jordnötssmör ≠ smör   gravad lax ≠ lax
```

`backend/tests/test_shared_canonical.py` pinnar femton sådana par.

## Skafferigrunden

Salt, peppar och olja står redan i skåpet, och ett recept ska inte rankas ned
för att de saknas i en registrerad kyl. Men listan är en **standard, inte en
sanning** — anroparen skickar sin egen med `extraStaples` och `notStaples`.

Receptbankens egen `pantryStaple`-flagga följer med varje rad som
`recipeStaple`, men **avgör inte**: banken flaggar ris, lök och vitlök i en
del recept, och ett "kan lagas nu" som förutsätter ris man inte har är ett
löfte appen inte kan hålla.

## Vad som inte delas

**Priser.** Receptkorten i Matjakt bär `pricePerPortion` från
prissättningskörningen. De fälten skalas bort i `services/shared/api.py`, och
ett test läser hela svaret som text och letar efter dem. Prisgrindens
fail-closed-regler och Dabas villkor gäller Matjakts egna ytor; att skicka
samma tal vidare genom en ny endpoint vore att publicera dem någon annanstans
utan att någon beslutat det.

**Produkter och GTIN.** Samma skäl, plus att produktdata till stor del är
Dabas-berikad och lyder under skriftliga villkor som inte automatiskt följer
med till en annan app.

**Konton.** Ät Upp har egen inloggning. Se `docs/` i det repot för hur
gemensam SSO skulle kunna se ut — men användartabeller kopieras aldrig mellan
databaser.

Att dela priser senare är ett eget beslut med egna villkor, inte en extra
endpoint. Det som redan finns på plats för den dagen: Ät Upp skickar
kanoniska ingredienser plus mängder, och Matjakt äger svaret.

## Filer

| Fil | Innehåll |
| --- | --- |
| `backend/services/shared/canonical.py` | Kanoniska id:n, de fyra relationerna, skafferigrunden |
| `backend/services/shared/matching.py` | Matchningsmotorn |
| `backend/services/shared/portions.py` | Portionsskalning |
| `backend/services/shared/api.py` | Lagrets API, cache, prisfiltret |
| `backend/tests/test_shared_canonical.py` | Kanonisering och falska vänner |
| `backend/tests/test_shared_matching.py` | Matchning, skafferigrund, portioner |
| `backend/tests/test_shared_api.py` | HTTP-kontraktet och app-nyckeln |
