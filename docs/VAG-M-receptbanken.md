# Våg M — receptbanken

**Tillägg till `UPPDRAG-MATJAKT.md`.** Ny zon: **`Z-RECEPT`**.

Zonen rör `backend/data/recipes.db`, `backend/recipe_sources/`,
`backend/services/recipes/` och `backend/scripts/*recipe*`. Den **krockar med
ingen annan zon** och kan därför köras parallellt med allt annat.

Alla siffror nedan är mätta mot `backend/data/recipes.db` 2026-09-12, inte
uppskattade.

---

## M1 · `mealType` på alla 240 recept `Z-RECEPT`

**Roten till att risgrynsgröt kan hamna i en middagsvecka.** Inget fält i
`recipes` säger idag vad en rätt är till för — kolumnen finns inte. Verifierat:
`PRAGMA table_info(recipes)` har varken `mealType` eller `meal_type`.

Veckoplaneraren väljer alltså bland allt den har, och att frukostgröt och
efterrätter inte dyker upp oftare är tur, inte konstruktion.

**Gör:** inför `meal_type` i `recipes` med ett litet, stängt värdeförråd
(`middag`, `frukost`, `lunch`, `efterratt`, `tillbehor`). Sätt det på alla 240
— inte på de uppenbara och `NULL` på resten, för `NULL` betyder i praktiken
"kanske middag" och då är fältet värdelöst. Låt veckoplaneraren filtrera på
`middag`.

**Acceptans:** ett test som kräver att **varje** recept har ett `meal_type` ur
värdeförrådet, och att veckoplaneraren aldrig returnerar ett recept som inte
är `middag`. Plus ett konkret fall: `risgrynsgrot-kanel-apple` får inte
förekomma i en genererad vecka.

**M1 först och ensam.** M3, M4 och M5 rör samma tabell.

---

## M2 · De 31 recepten utan bild `Z-RECEPT`

**31 av 240 recept saknar bild.** Verifierat: `image IS NULL OR image = ''`.

Det var kosmetiskt tidigare. Sedan design D valdes är det inte det längre:
**Ikväll är ett helbleed-foto på 278 px med rubriken på bilden** (L1), och
Veckan är sju rader med 52-pixelsfoton (L2). Ett recept utan bild blir ett hål
där maten ska vara, på appens viktigaste skärm.

**Gör:** två saker, i den ordningen.

1. **Försök hitta foton** för de 31 genom den väg som redan finns
   (`backend/scripts/find_recipe_images.py`, licensierade källor). Varje
   hittad bild ska bära `image_source`, `image_license` och `image_credit` —
   ett foto utan proveniens läggs inte in.
2. **Bygg ett reservkort** för dem som inte får foto. **Aldrig en grå ruta.**
   Designsystemet har materialet: pappersytan, hårfina linjer, display-serif.
   Ett typografiskt kort med rättens namn är ett medvetet utseende; en tom
   platshållare är ett fel som syns.

**Acceptans:** inget recept renderar en tom bildyta — varken i Ikväll, i
Veckan eller i receptvyn. Testet ska pröva **ett recept utan bild**, inte bara
att de med bild fungerar.

**M2 kan köras parallellt med M1** — den rör `image`-kolumnen och en ny
frontend-komponent, inte receptens struktur.

---

## M3 · Ingredienser som är skafferivara ibland och inte ibland `Z-RECEPT`

Fyndet är skarpare än "saknar mängd". Varje rad utan mängd **är** märkt
`pantry_staple = 1`, och det fältet betyder *"antas finnas hemma"*: raden
prissätts aldrig (`audit.py:89` hoppar över den) och hamnar i `rows.home` i
stället för `rows.buy` i receptvyn.

För salt, olja, smör och peppar är det rätt. Problemet är att **samma
ingrediens är klassad olika i olika recept**:

| Ingrediens | Rader totalt | Märkta skafferi |
|---|---|---|
| Ägg | 36 | **2** |
| Vetemjöl | 29 | **2** |
| Lök | 5 | **2** |
| Socker | 7 | 7 |
| Ättika | 8 | 7 |
| Vitlök | 79 | **9** |

Ägg prissätts i 34 recept och antas finnas hemma i 2. Det är ingen smaksak —
det gör priset fel i just de två, och användaren får inga ägg på listan för en
rätt som behöver dem.

**Gör:** bestäm per ingrediens om den är skafferivara eller inte, och gör den
konsekvent. Skafferivaror är sådant man har öppnat hemma och doserar efter
smak: salt, peppar, olja, smör, socker, ättika, vanliga torra kryddor. **Ägg,
lök och vitlök är varor man köper** — de ska ha mängd och prissättas.

Vitlöken är extra känslig: **C3 räknade just om den från knoppar till
klyftor**. Läs `docs/changelog.d/C3.md` innan du rör de nio raderna, så att
mängden du sätter är i klyftor.

**Acceptans:** ett test som kräver att en ingrediens har **samma**
`pantry_staple` i alla recept den förekommer i. Plus att ägg, lök och vitlök
har mängd i varje rad.

---

## M4 · `categories` och `tags` gör samma jobb `Z-RECEPT`

Två fält med överlappande innehåll och olika versalisering — `Kött` mot
`kott`. `recipe_labels` har 2 012 rader.

Två sätt att säga samma sak betyder att ett filter träffar hälften: den som
söker `kott` missar `Kött`, och ingen ser att det blev fel, för listan blir
kortare i stället för tom.

**Gör:** ett fält, ett format. Normaliserad, gemen, utan diakriter i nyckeln
(visningsnamnet får behålla sitt) — samma form som `normalize_ingredient_id`
redan använder för ingredienser. Migrera befintlig data; kasta inte bort en
etikett som bara fanns i det ena fältet.

**Acceptans:** ett test som kräver att ingen etikett förekommer i två
versaliseringar, och att varje etikett som fanns före migreringen finns efter.

---

## M5 · Två soppor på 6–7 g protein som huvudrätt `Z-RECEPT`

Verifierat: `Morotssoppa med ingefära` 6 g, `Sötpotatissoppa med kokos och
lime` 7 g. Nästa i listan är `Krämig tomatsoppa` på 8 g.

En middag för en familj bör ligga väsentligt högre. Appen säljer inte
näringsrådgivning, men den föreslår vad man ska äta — och en huvudrätt på 6 g
protein är inte en middag, oavsett hur god den är.

**Gör:** välj en väg per soppa och skriv vilken i PR:en. Antingen höj proteinet
i receptet (linser, kikärtor, en tillbehörsmacka med ost som ingår i
näringsberäkningen), eller märk soppan som `lunch` i M1:s `meal_type` så den
aldrig föreslås som middag. **Hitta inte på näringsvärden** — ändras
ingredienserna ska `compute_recipe_nutrition.py` räkna om dem.

**Acceptans:** inget recept med `meal_type = middag` har under en satt
proteingräns, och gränsen står som en namngiven konstant med en mening om
varför just den.

---

## Ordning

```
M1  först och ensam      (rör recepttabellens struktur)
M2  parallellt med M1    (rör image-kolumnen och en frontend-komponent)
M3, M4, M5  efter M1     (rör samma tabell, sekventiellt sinsemellan)
```

M5 beror dessutom på M1: alternativet "märk soppan som lunch" kräver att
`meal_type` finns.
