# Våg L — skärmarna byggs som i design D

**Tillägg till `UPPDRAG-MATJAKT.md`.** Rättar en lucka i vågen G.

Facit för varje paket: `docs/matjakt-design-D.html` (åtta skärmar).
Tokens, kontrastpar och komponentspecar: `docs/DESIGNSYSTEM-D.md`.

---

## Varför den här vågen finns

G-vågen är en lista över fel i den **befintliga** appen: kasta om ordningen på
Hem, laga kontrasten, förstora träffytorna, skriv om texterna, lägg in tokens.
Den är riktig och den ska köras klart.

Men den bygger inte design D. Den målar om den gamla appen.

Design D är inte en palett — det är en struktur: helbleed-foto med rubriken
liggande på bilden, veckan som sju synliga rader med 52-pixelsfoton,
inköpslistan i hårlinjegrupper per avdelning, sparsumman på den enda mörka
ytan i appen. `matjakt-design-D.html` visar åtta skärmar. G-vågen bygger noll
av dem.

Aliasskiktet i G1 var rätt migreringsväg och ligger kvar. Den här vågen är
steg två.

**Timingen är bra.** F-vågen flyttar vyerna ur `app.js` till egna moduler
under `src/views/`. Att bygga om en vy är en helt annan sak när den är 200
rader i sin egen fil än när den är inflätad i 5 300. Vänta in F — det är inte
en fördröjning, det är förutsättningen.

---

## Ordning

| Paket | Zon | Beror på |
|---|---|---|
| **L0** prisreglerna som komponenter | `Z-STYLE` | G5 |
| **L1** Ikväll | `Z-FRONT-VIEW` | F, G2, L0 |
| **L2** Veckan | `Z-FRONT-VIEW` | F, G3, L0 |
| **L3** Handla | `Z-FRONT-VIEW` | F3, L0 |
| **L4** Receptet | `Z-FRONT-VIEW` | F4 |
| **L5** Sparat | `Z-FRONT-VIEW` | F, G4 |
| **L6** Inställningar | `Z-FRONT-VIEW` | F5, G11 |
| **L7** Premium | `Z-FRONT-VIEW` | F5, J2, J3 |
| **L8** literalstädning | `Z-STYLE` | L0–L5 |

**L0 först och ensam.** Allt annat använder den. L1–L7 kan sedan köras
parallellt av sju agenter — de äger varsin vymodul och rör inte varandras
filer.

Varje paket har `matjakt-design-D.html` som facit. Öppna rätt telefon i den
filen och bygg den skärmen. Avviker du, skriv i PR:en varför.

---

## L0 · De tre prisreglerna som delade komponenter `Z-STYLE`

Det här är produktens själ och det enda paketet som inte får byggas två
gånger på olika sätt.

Tre tillstånd, kodade i **form** så de överlever gråskala och färgblindhet:

1. **Kontrollerat pris** — naken siffra, ingen utsmyckning. Det som inte är
   markerat är det du kan lita på.
2. **Uppskattat pris** — `ca` före talet i kapitäler, plus streckad
   understrykning.
3. **Pris saknas** — öppen ram med tankstreck. **Aldrig rött.** Ett saknat
   pris är ingen varning, det är ett tomt fack. Rött skulle lära användaren
   att systemets ärlighet är ett fel.

Bygg som tre CSS-klasser plus en `prisMarkup(värde, tillstånd)` i
`src/views/pris.js`. Alla vyer kallar den; ingen vy skriver egen prismarkup.

Lägg en teckenförklaring med de tre formerna i foten på Handla, så de går att
läsa utan att ha memorerat systemet.

**Acceptans:** ett test som renderar de tre tillstånden och kräver att de
skiljer sig i något annat än färg — konvertera till gråskala och kräv att
markupen fortfarande är olika. Plus: inget `--red`, `--danger` eller rött
literal någonstans i prismarkupen.

---

## L1 · Ikväll `Z-FRONT-VIEW`

Facit: telefon 1.

- Helbleed foto, 278 px, med toning underifrån och rubriken **på** bilden.
  Foto ur `assets/recipes/`.
- Ögonbryn `IKVÄLL · ONSDAG` i kapitäler, rätten som display-serif, meta under.
- Prisrad under fotot: portionspriset stort till vänster, `Se receptet` som
  accentlänk till höger.
- Budgeten som en **remsa**: etikett, `612 / 800 kr`, 6 px mätare. Inte en
  mätartavla.
- Fyndraden under, med de nya `recipeIds` från C11 när de finns.

G2 kastar om ordningen i CSS. **L1 är den som gör Ikväll till ett fotokort.**
G2 är tio rader, L1 är skärmen.

**Acceptans:** fotot fyller bredden, rubriken ligger på det, och texten klarar
4,5:1 mot toningen räknat mot värsta fall — ett helvitt foto under. Skärmdump
i PR:en, ljust och mörkt.

---

## L2 · Veckan `Z-FRONT-VIEW`

Facit: telefon 2.

- **Alla sju dagar synliga.** Inga dagflikar. G3 tar bort `hidden`; L2 bygger
  raderna.
- Rad: dagförkortning, 52 px foto, rättens namn och tid, pris till höger,
  bytesknapp 44×44.
- Tom dag: streckad ruta i stället för foto, `Ingen middag planerad`, `＋`.
- Summeringsblock under: delposter, linje, summa — kvittots logik, inte
  kvittots utseende. Summan säger vad den grundar sig på.
- Där veckan har osäkra rader: `minst 612 kr`, aldrig ett exakt tal (C7).

**Acceptans:** sju rader ryms utan scroll på 844 px tillsammans med rubrik och
summering. Två tomma dagar renderas rätt.

---

## L3 · Handla `Z-FRONT-VIEW`

Facit: telefon 3. Modulen finns redan — F3 flyttade den till
`src/views/shopping.js`.

- **Listan först.** Butiksvalet flyttas till Veckan.
- Avdelningsgrupper med en hårlinje till vänster och rubriken i kapitäler:
  `FRUKT & GRÖNT`, `KÖTT & CHARK`, `MEJERI`.
- Rad: kryssruta 21 px i en 44 px träffyta, namn, mängd som underrad, pris
  till höger via `prisMarkup` från L0.
- Avbockad rad: genomstruken, tonad.
- Fot: `Minst att betala` plus en rad om hur många varor som saknar säkert
  antal.
- **`×` bort ur tumzonen.** Ta bort görs med svep vänster och Ångra-toast,
  inte med en 30-pixelsknapp bredvid priset.

**Acceptans:** de tre pristillstånden renderas med L0:s komponent, inte med
egen markup. Svep-för-ta-bort fungerar med tangentbord också.

---

## L4 · Receptet `Z-FRONT-VIEW`

Facit: telefon 4.

- Helbleed foto med rubriken på.
- Portionspriset som bildtext, inte som utrop.
- Ingredienser i två kolumner: mängden i egen kolumn med `tabular-nums`,
  namnet bredvid. Går att läsa med en gryta i handen.
- `Har du hemma` som tonad rad, inte som utelämnad.
- Numrerade steg, avbockningsbara.

**Acceptans:** dubbelescapningen är borta (E12), så `salt & peppar` visas rätt.

---

## L5 · Sparat `Z-FRONT-VIEW`

Facit: telefon 5.

- Sparsumman på **den enda mörka ytan i appen**. Det är appens viktigaste
  siffra och den ska ha appens starkaste kontrast.
- Månadsstaplar mot en riktig skala, med etiketter som namnger värden
  staplarna faktiskt når. Pågående månad markerad som pågående.
- Nyckeltalsrader under: den här veckan, den här månaden, middagar planerade,
  kampanjvaror som hamnade i maten.
- `Dela din månad` som sekundär knapp — kopplas till H4.

G4 lagade kontrastfelet. **L5 bygger skärmen** som gör siffran till något man
vill komma tillbaka till.

---

## L6 · Inställningar `Z-FRONT-VIEW`

Facit: telefon 7. G11 säger att skärmen ska finnas; L6 bygger den som i D.

Grupper med hårlinjer: Hushåll · Kost och allergier · Budget · Butik och plats
· Konto · Prenumeration · Notiser · Integritet. Varje rad minst 52 px med
värdet till höger.

**Allergiraden märks särskilt** när den är tom. Det är appens mest
säkerhetskritiska inställning och den bor idag bakom ett omärkt plustecken på
28×28 px.

---

## L7 · Premium `Z-FRONT-VIEW`

Facit: telefon 8.

Inte en hänglåsvägg — en jämförelsetabell med **bara sanna rader**, byggd mot
feature-matrisen som J3 landar. Nej sätts med tankstreck, inte enbart med färg.

Blockeras av J3. Bygg inte tabellen mot den gamla matrisen.

---

## L8 · Literalstädningen `Z-STYLE`

`styles.css` har ungefär nittio hårdkodade färgvärden som aldrig gick genom en
token. Aliasskiktet riktade om variablerna och lämnade literalerna:

`#14532d` ×4 (gammalt mörkgrönt) · `#fff` ×42 · `rgba(23,33,27)` ×14
(grönsvart skugga) · `#fff8ea` · `#f4f1e7` · `rgba(184,137,60,.25)` ·
`#fbe4e1` · `#e7d9d4` · `#cfd5d0` · `#b7c1b9` · `#5b6470`

Resultatet är en kall pappersgrå palett med nittio varma och gröna fläckar i
sig. I mörkt läge blir det värre — literaler inverterar inte.

Varje literal ersätts av en token eller motiveras i en kommentar. Ett test
failar på nya literaler utanför `:root`.

**Kör sist.** Under L1–L5 skrivs vyerna om ändå, och en literal i en rad som
snart raderas är inte värd en granskning.
