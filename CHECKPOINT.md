# Checkpoint — överlämning 2026-08-31

Skriven för att nästa agent ska kunna fortsätta exakt härifrån utan att bygga
om något. Allt nedan är verifierat mot kod, tester eller live produktion —
inget är antaget för att koden "finns".

**Senaste commit:** `96a97c3` — Verktyg för receptbilder från Pexels
**Branch:** `main`, synkad med origin. Arbetskatalogen är ren.
**Tester:** 514/514 gröna (`npm test` kör både frontend- och backendsviten).

---

## ⚠️ KRITISKT: produktionsdisken sparar inte data

**Detta måste lösas innan något annat byggs på produktionen.**

Bevis, i tur och ordning:

1. Kl. 15:09 slutförde produktionen en Willys-import: **10 837 produkter,
   `status=success`**.
2. Efter nästa deploy visade `/api/grocery/status` **`totalProducts: 0`** och
   bootstrap-importen startade om — den kör *bara* när databasen är helt tom.
3. `lastSuccessfulRun` är **`None`**. Även raden i `grocery_collector_runs`
   från den lyckade körningen är borta, alltså försvann hela databasfilen.

Slutsats: `/app/backend/data` beter sig som container-lokal lagring, inte som
en monterad disk. `render.yaml` deklarerar en disk, men tjänsten verkar vara
skapad manuellt i dashboarden (samma skäl som gjorde att env-variabler i
`render.yaml` inte slog igenom förrän de sattes för hand).

**Att kontrollera i Render-dashboarden:** finns en disk faktiskt kopplad till
tjänsten, och är dess `Mount Path` exakt `/app/backend/data`?

Ett testkonto skapades i produktion för att bekräfta samma sak för
användardata: **`persist+1788184978@matjakt.test`** (lösenord
`ett-riktigt-losenord`). Logga in på det efter nästa deploy. Går det inte,
tappas även kontodatabasen.

Konsekvensen så länge: varje deploy tömmer prisdatabasen och triggar en ny
17-minutersimport. Koden hanterar det korrekt (bootstrap kör bara vid tom
databas, inkrementell sparning gör att data syns under tiden), men det är en
plåsterlösning på ett infrastrukturproblem.

---

## Vad som är färdigt

**Grocery/pricing-backend.** Egen produkt-/prisdatabas (`grocery.db`) med
providers för Willys, Hemköp, City Gross och ICA. Kategoriinsamling via
verifierade endpoints. Recipe Pricing Engine med paketmatematik (600 g ur ett
700 g-paket = ett helt paket) som aldrig uppfinner ett pris — omatchat hamnar
i `missingItems` och sänker coverage.

**Kategorimatchning.** Mätt mot 10 842 riktiga produkter: 52/57 ingredienser
(91 %) med **0 träffar i fel avdelning**, ned från 23. Se
`backend/scripts/measure_matching.py`.

**Prestanda.** Prissättning 1658 → 749 ms kall, butikskorg 134 ms, byta butik
79 ms — uppmätt *med en import igång*. Verifieras med
`backend/scripts/acceptance_speed.py`.

**Auth.** Registrering, login/logout, sessioner, glömt lösenord med
engångstoken, lösenordsbyte, kontoradering, rate limiting, hashade
sessionstokens (SHA-256, migrering som inte loggar ut någon),
användarisolering. 27/27 i `backend/tests/auth_e2e.py` mot en levande backend,
plus 5/5 efter omstart.

**Frontend.** Sju veckotyper (Familj, Budget, Träning, Bulk, Snabb,
Vegetarisk, Balanserad), dynamiska butikskedjor, klickbara butikskort med
riktig varukorg, postnummerbyte som invaliderar gamla butiker, korrekt
Billigast-logik (kräver ≥85 % coverage och minst två jämförbara butiker).
58 recept flyttade ur `app.js` till `frontend/app/data/recipes.json`.

**Nattjobb.** Willys 02:00, Hemköp 03:00, City Gross 04:00 (Europe/Stockholm).
ICA, Coop och Lidl kan inte schemaläggas ens av en felskriven env-variabel.
Adminpanel på `/app/admin.html`.

---

## Vad som är halvfärdigt

**Receptbilderna.** De 58 bilderna är amatörsnapshots från Wikimedia Commons —
blixt, mönstrade dukar, och linssoppsbilden är faktiskt quinoasoppa. Bara 5 är
tekniskt små, så det är inte ett upplösningsproblem utan ett källproblem.
Verktyget `backend/scripts/pexels_recipe_images.py` är byggt och klart men
**väntar på `PEXELS_API_KEY` i `.env`**. Undersökningen av alternativen finns
i commit `cf9413a`: TheMealDB har 793 recept med bra bilder men **noll svenska
recept** (kategorin finns, är tom), och Livsmedelsverket har näringsdata men
inga recept eller bilder. Det finns ingen fri svensk receptdatabas med bilder.

**Barn-kategorin och receptsidans sektioner/filter.** Datamodellen är klar —
varje recept har `tags` (barn, snabbt, billigt, proteinrikt, vegetariskt,
mealprep, helgmiddag …) och `RECIPE_SHELVES` i
`frontend/app/src/data/recipes.js` definierar hyllorna. **UI:t som renderar
dem är inte byggt.**

**Bulkveckan har för få recept.** Vid `kcal ≥ 500` fanns bara 7 av 58 recept,
färre än en sjudagarsvecka behöver, så typen kunde aldrig visas. Tröskeln är
sänkt till 450 kcal som en tillfällig åtgärd. **Rätt lösning är fler recept,
inte lägre gränser.**

**Hårdkodningsaudit.** Påbörjad men inte genomförd. Kvarvarande fynd:
`frontend/app/app.js:82` (postnummer 80252 som default), rader 147/1532/2075
("Willys" som fallback-kedja), `backend/services/grocery/api.py:171`.
Collectorernas store-ID (2132, 4256, 3209, 1003987) är dokumenterade
standardvärden i CLI-skript och behöver troligen inte flyttas.

**City Gross och ICA prissätter per butik.** Idag importeras City Gross från
Gävle och ICA från Maxi Gävle, så en Stockholmsanvändare ser Gävlepriser.
Skärmen säger det rakt ut, men rätt lösning är efterfrågestyrd import per
butik — dokumenterad i `backend/services/grocery/README.md` under "Nästa
förbättring".

---

## Nästa steg

1. **Fixa Render-disken** (se varningen överst). Allt annat i produktion är
   ostadigt tills dess.
2. Slutför frontendfasen: Barn-kategorin, receptsidans sektioner och filter.
3. Bygg Matjakts egen svenska receptbank. Datamodellen och laddningslagret
   finns; det som saknas är recepten och bilderna.

---

## Filer nästa agent bör läsa först

| Fil | Varför |
|---|---|
| `backend/services/grocery/README.md` | Den egentliga arkitekturdokumentationen: providerstatus, kategoridata, endpoints, nattjobb, persistens |
| `backend/services/grocery/pricing.py` | Recipe Pricing Engine. Modulens docstring förklarar de två ärlighetsreglerna |
| `backend/services/grocery/api.py` | Det enda `api_server.py` behöver känna till. `compare_chains()` innehåller Billigast-logiken |
| `frontend/app/src/data/recipes.js` | Receptbankens laddningslager och hyllorna som ska renderas |
| `frontend/app/data/recipes.json` | De 58 recepten i strukturerad form |
| `backend/scripts/acceptance_speed.py` | Kör detta för att bevisa att prestandan håller |
| `backend/tests/auth_e2e.py` | Kör mot en levande backend; kräver omstart mellan körningar (rate limit) |

Commit-meddelandena är utförliga med flit — de förklarar *varför* varje beslut
togs, inklusive de fel som avslöjade behovet. `git log` är den bästa källan
till projektets historik.

---

## Produktionsstatus vid överlämningen

- **Frontend:** matjakt.store kör `app.js?v=63`, alltså senaste koden.
- **Backend:** senaste commit deployad (CSP-headern svarar).
- **Willys-import:** kör just nu, 10 430 produkter och stigande. Den startade
  efter senaste deployen eftersom databasen var tom — se varningen överst.
- **Hemköp och City Gross:** ingen data i produktion ännu. De kör enligt
  schema 03:00 och 04:00, men överlever inte nästa deploy förrän disken är
  åtgärdad.
- **En deploy nu avbryter den pågående importen.** Inkrementell sparning gör
  att det redan importerade finns kvar, men körningen får börja om.
