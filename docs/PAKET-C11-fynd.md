# C11 · Fynd rankas efter vad de gör för veckan, inte efter rabattdjup

**Zon:** `Z-GROCERY` (inte `Z-MAIL` — det är underlaget som är fel, inte texten)
**Allvarlighet:** HÖG. Blockerar verkan hos I4 (Kampanjtorget), fyndraden på Ikväll, och "Visa alla" i G12.
**Tillägg till `UPPDRAG-MATJAKT.md`** efter mätning som dokumentet inte hade tillgång till.

---

## Vad som är fel

`backend/services/grocery/api.py:139`

```sql
ORDER BY 1.0 - (cp.campaign_price / cp.regular_price) DESC
LIMIT ?            -- per_chain * 3
```

Rankningen är rent rabattdjup i procent. Det är inte ett mått på hur bra ett fynd är — det är ett mått på hur angelägen butiken är att bli av med varan. I september betyder det säsongsutförsäljning, och mätningen visar exakt det: **Willys topp-10 är tio glassar, och 5 av 20 fynd går att koppla till ett recept.**

Funktionens docstring säger att raderna är "ranked by discount", så koden gör vad den lovar. Felet är att löftet är fel.

Tre följdfel faller ut ur samma rad:

1. **Fyndraden på Ikväll** visar tio varor som inte hör hemma i någon middag.
2. **Kampanjtorget (I4)** lovar i sin brödtext: *"Trycker du in ett fynd i veckan byter Matjakt ut en rätt mot en som använder varan."* Det löftet går inte att infria, för fynden bär ingen koppling till recept alls.
3. **`per_chain * 3` som tak före avdubbling** gör problemet värre: pool:en är redan filtrerad till de trettio djupaste procentavdragen innan något annat urval sker. En bra vara som råkar ligga på 18 % finns inte ens med som kandidat.

---

## Vad ett fynd faktiskt är värt

Ett fynd är värt något för Matjakts användare om det **sänker kostnaden för en vecka hon ändå skulle laga**. Tre saker avgör, och procent är ingen av dem:

- **Går varan att laga mat av?** En vara som inte matchar någon ingrediens i receptbanken kan aldrig hamna i en vecka.
- **Hur många kronor sparar den?** 30 % på en burk krossade tomater för 12 kr är 3,60 kr. 20 % på 1,2 kg fläskkarré är ~24 kr. Procenten säger tvärtom.
- **Går det att planera runt den?** En ingrediens som finns i fyrtio recept kan bytas in i veckan. En som finns i ett kan det inte.

---

## Åtgärd

### 1. Bygg ett ingrediensindex nattligt, inte per anrop

Prismotorn kan redan svara på "vilken produkt matchar den här ingrediensen hos den här kedjan" — `price_item()` i `pricing.py`, med hela namnregel-, avdelnings- och exklusionsapparaten. Kör den **baklänges** en gång per import och materialisera resultatet:

```
grocery_ingredient_index(
  canonical_ingredient TEXT,   -- "fläskkarré", "krossade tomater"
  product_id           INTEGER,
  chain                TEXT,
  recipe_count         INTEGER,  -- antal recept i banken som använder ingrediensen
  typical_amount       REAL,     -- median över recepten
  typical_unit         TEXT,
  PRIMARY KEY (canonical_ingredient, product_id)
)
```

Byggs i samma steg som publiceringen (`publish.py`), efter att gaten passerat. Aldrig i en HTTP-väg — `campaign_deals` får inte vänta på matchning.

`recipe_count` och `typical_amount` räknas ur receptbanken (`backend/recipe_sources/*.json`, 240 recept), inte ur den gamla 58-receptslistan i `frontend/app/data/recipes.json`.

### 2. Byt rankningen

```sql
JOIN grocery_ingredient_index ix
     ON ix.product_id = cp.product_id AND ix.chain = st.chain
```

Det är en **hård grind**: en vara utan ingrediensmatchning kommer inte med. Sortera sedan på sparade kronor på en realistisk mängd, med receptspridningen som vikt:

```
kronor_sparade = (regular_price - campaign_price) * paket_som_behovs(typical_amount, typical_unit)
poang           = kronor_sparade * log2(1 + recipe_count)
```

`paket_som_behovs` är **samma funktion som inköpslistan använder** (`packagesFor` / paketmatten i `price_item`). Beloppet på fyndkortet ska vara det belopp veckan faktiskt ändras med — annars har vi två sanningar om samma vara, och det är precis det fel C7 handlar om på totalnivå.

`log2` och inte rakt antal: skillnaden mellan 1 och 10 recept är stor, mellan 30 och 40 är den inte det.

### 3. Tak per kategori

Max **två fynd per `grocery_products.category` och kedja**. Kolumnen finns och är indexerad (`store.py:289, 367`).

Den regeln ensam avlivar glasslistan, och den gör det utan att förbjuda något: en verkligt billig glass är ett fullgott tionde kort. Den får bara inte vara hela listan.

### 4. Behåll det som redan är rätt

Rör inte: golvet på 10 % (`api.py:165`), avdubbling på produktnamn (`148`), `lowestSeen` ur prishistoriken (`155-162`), åldersgränsen `MAX_CAMPAIGN_AGE_SECONDS`, eller cachningen på `data_version`. Allt det är välmotiverat och kommenterat.

Höj däremot kandidattaket: med en hård grind krymper poolen kraftigt, så `LIMIT per_chain * 3` blir för snålt. Hämta alla kampanjrader för kedjan som passerar grinden och poängsätt i SQL.

### 5. Skicka med kopplingen till recept

Varje fynd i svaret får två nya fält:

```json
"recipeIds": ["flaskfilerotmos", "flaskcurrygryta", "flasktomatpasta"],
"savesOnWeek": 24.20
```

Det är det som gör kortet användbart i stället för dekorativt. Fyndraden på Ikväll kan då säga *"Byt torsdagen mot Fläskfilé med rotmos — 24 kr billigare den här veckan"*, och Kampanjtorgets löfte i I4 blir infriat i stället för påstått.

---

## Acceptans

Ett test med fixturdata där:

- tio glassar har de djupaste procentavdragen,
- en fläskkarré har det största kronbeloppet,
- och minst tre glassar delar kategori.

Testet kräver att:

1. Fläskkarrén ligger före samtliga glassar.
2. Högst två glassar finns i listan.
3. **Varje returnerat fynd bär minst ett `recipeId`** — det är den regel som gör resten omöjlig att kringgå.
4. `savesOnWeek` för en vara stämmer exakt med vad samma vara kostar i inköpslistan för samma mängd. Räknar de två olika är det ett fel, inte en avrundning.

Lägg dessutom ett test som körs mot produktionsdatan i prisauditen: **andelen fynd med minst ett recept ska vara 100 %**. Mätningen från i går (5 av 20) blir då en larmande siffra i stället för en anekdot.

---

## Ordning och beroenden

- Kan köras **nu**, parallellt med allt annat. `Z-GROCERY` rör inte `app.js` och inte `styles.css`.
- **I4-agenten ska inte vänta.** Texten är rätt oavsett; det är underlaget som byts under den. Den skriver som planerat i sin PR att verkan är begränsad tills C11 landat.
- Fyndraden i UI:t (`renderCampaignSection`) kan läsa de nya fälten när de finns och falla tillbaka snyggt när de inte gör det — inget hårt beroende åt det hållet.
- **G12:s "Visa alla"** blir först nu en riktig funktion. Idag scrollar knappen bara raden till slutet (`app.js:4839`). Med recept­kopplingen finns det något att visa: en fyndlista med filter per kedja, och per fynd vilken rätt det byter in.
