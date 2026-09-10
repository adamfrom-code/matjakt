# Matjakt — Designsystem D, "Middagskortet"

Teknisk specifikation för utvecklare. Sanningen är `/home/claude/matjakt-design/src-D.html`.
Det här dokumentet beskriver den riktningen, räknar efter den och översätter den till
byggbar CSS mot `/home/claude/matjakt/frontend/app/styles.css`.

Där jag har rättat riktningen står det **RÄTTELSE** med skälet och det uträknade värdet.
Alla kontrastvärden i dokumentet är beräknade enligt WCAG 2.1 relativ luminans,
inte uppskattade.

---

## 1. Riktningen i ett stycke

Matjakt är en mattidning i telefonformat. Ett stort foto, en rubrik med luft omkring sig,
och priset satt som bildtext — sakligt, litet, aldrig ett utrop. Sidan är sval pappersvit,
sättningen är asymmetrisk, linjerna är hårfina, och den enda färgen är oxblod. Det finns
inga kort, inga skuggor och inga pillerformade chips inne i appen: innehållet skiljs åt av
linjer och luft, precis som på ett tryckt uppslag. **Kärnbeslutet är att priset degraderas
från huvudperson till bildtext.** Allt annat följer av det. Budgeten blir en tunn remsa
under maten i stället för en mätare som äger skärmen. Prisets säkerhet kodas i formen —
hel siffra, streckad siffra, tom ram — och inte i färg, så den överlever gråskala och
färgblindhet. Den enda stora siffran i hela appen är pengarna som blivit över, på skärmen
Sparat, för det är den enda siffra som förtjänar en hjälterubrik.

---

## 2. Färg

### 2.1 Tokens

Ljust läge definieras komplett på bar `:root`. Mörkt läge omdefinierar **endast** de tokens
som ändras, tre gånger: under `@media (prefers-color-scheme:dark)` med
`:root:not([data-theme="light"])`, och under `:root[data-theme="dark"]`. Ingen färg får ha
sin enda definition inuti ett media- eller `[data-theme]`-block.

| Token | Ljust | Mörkt | Får användas till |
|---|---|---|---|
| `--paper` | `#ECEEEF` | `#111416` | Sidans grundyta. Bakgrund på `body`, bottennav, bottenark, modalpanel, toast-nedslag. Aldrig som textfärg utom på `--ink` och `--accent`. |
| `--paper-2` | `#E2E5E7` | `#191D1F` | Nedsänkt fält: budgetremsan, summeringsblocket, tom dagrad, tryckt tillstånd på rader, laddningsskelett. Aldrig som ram. |
| `--ink` | `#16191B` | `#E9ECEE` | All primär text: rubriker, brödtext, varunamn, kontrollerat pris. Ifylld kryssruta. Markören i budgetmätaren. Fokusring **på** accentfärgad yta. |
| `--ink-2` | `#5A6367` | `#A6AFB3` | Sekundär text: ingredienslistor, bildtexter, "kvar av"-texten, uppskattat pris, kursiv tomtext, kapitäletikett **på `--paper-2`**. |
| `--ink-3` | `#626B6F` | `#7E888C` | Tertiär text **endast på `--paper`**: kapitäletiketter, metadata, mängdangivelser, avbockad text, inaktiv navflik, inaktiv knapptext. Dessutom: alla *betydelsebärande* streck och ramar (streckad prissiffra, ram runt "pris saknas", stapel i månadsdiagrammet, teckenförklaringens glyfer). |
| `--rule` | `#CBD1D3` | `#272C2F` | Hårfina avdelare inuti en lista: 1px linje mellan varurader, mellan dagrader, mätarens spår. Aldrig bärare av betydelse. |
| `--rule-2` | `#B3BBBE` | `#3A4145` | Tyngre avdelare mellan sektioner: ovanför avdelningsrubrik, ovanför summeringsblock, ovanför bottennav, ovanför bottenark. Aldrig bärare av betydelse. |
| `--accent` | `#8A1F42` | `#EE93AB` | Se accentregeln, 2.3. |
| `--accent-press` | `#6E1935` | `#F5B7C6` | Endast tryckt tillstånd på accentfärgad yta och tryckt textknapp. |
| `--accent-soft` | `#EBDDE2` | `#2A1720` | Reserverad. Får i praktiken bara användas som bakgrund bakom `--ink` (13,43:1) om en framtida skärm behöver en markerad rad. Aldrig bakom `--ink-3`. |
| `--on-accent` | `#FFFFFF` | `#26060F` | Text och ikon ovanpå `--accent` / `--accent-press`. |
| `--shot` | `#D2D7D9` | `#1E2325` | Platshållarton bakom foton som inte laddat. Aldrig textbakgrund utan skärm (se 5.2). |
| `--shadow` | `rgba(18,24,26,.22)` | `rgba(0,0,0,.6)` | Enda skuggan, se 4.5. |
| `--scrim` | `rgba(10,12,13,.78)` | `rgba(10,12,13,.78)` | Bottenfärg i gradienten under text på foto. Samma i båda lägen — den ska mörklägga fotot, inte följa temat. |

```css
:root{
  --paper:#ECEEEF; --paper-2:#E2E5E7;
  --ink:#16191B; --ink-2:#5A6367; --ink-3:#626B6F;
  --rule:#CBD1D3; --rule-2:#B3BBBE;
  --accent:#8A1F42; --accent-press:#6E1935; --accent-soft:#EBDDE2; --on-accent:#FFFFFF;
  --shot:#D2D7D9; --shadow:rgba(18,24,26,.22); --scrim:rgba(10,12,13,.78);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#111416; --paper-2:#191D1F;
    --ink:#E9ECEE; --ink-2:#A6AFB3; --ink-3:#7E888C;
    --rule:#272C2F; --rule-2:#3A4145;
    --accent:#EE93AB; --accent-press:#F5B7C6; --accent-soft:#2A1720; --on-accent:#26060F;
    --shot:#1E2325; --shadow:rgba(0,0,0,.6);
  }
}
:root[data-theme="dark"]{
  --paper:#111416; --paper-2:#191D1F;
  --ink:#E9ECEE; --ink-2:#A6AFB3; --ink-3:#7E888C;
  --rule:#272C2F; --rule-2:#3A4145;
  --accent:#EE93AB; --accent-press:#F5B7C6; --accent-soft:#2A1720; --on-accent:#26060F;
  --shot:#1E2325; --shadow:rgba(0,0,0,.6);
}
body{background:var(--paper);color:var(--ink)}
```

`body` måste ha explicit `background:var(--paper)`. En genomskinlig `body` lånar värdens
tema och gör mörkt läge trasigt.

### 2.2 Kontrasttabell

Varje textfärg mot varje bakgrund den faktiskt förekommer på i de fyra skärmarna.
Gränser: AA normal text 4,5:1 · AA stor text (≥18,66px fet eller ≥24px) 3:1 · AAA normal 7:1 ·
grafiska objekt och ramar som bär betydelse 3:1.

**Ljust läge**

| Text | Bakgrund | Ratio | Bedömning | Förekomst |
|---|---|---|---|---|
| `--ink` `#16191B` | `--paper` `#ECEEEF` | **15,17:1** | AAA | Allt: rubriker, brödtext, varunamn, kontrollerat pris |
| `--ink` | `--paper-2` `#E2E5E7` | **13,96:1** | AAA | Summa i kassan, "612 kr" i budgetremsan, tomtext-rad |
| `--ink` | `--accent-soft` `#EBDDE2` | **13,43:1** | AAA | Reserverad markerad rad |
| `--ink-2` `#5A6367` | `--paper` | **5,28:1** | AA (ej AAA) | Ingredienslista, bildtexter, uppskattat pris, kursiv tomtext |
| `--ink-2` | `--paper-2` | **4,86:1** | AA (ej AAA) | Kapitäletikett och teckenförklaring i summeringsblocket |
| `--ink-3` `#626B6F` | `--paper` | **4,68:1** | AA (ej AAA) | Kapitäletiketter, metadata, mängd, avbockad text, inaktiv navflik |
| `--ink-3` | `--paper-2` | **4,31:1** | **UNDERKÄNT** | — förbjuden kombination, se RÄTTELSE nedan |
| `--ink-3` | `--shot` `#D2D7D9` | **3,75:1** | **UNDERKÄNT** | — ingen text på `--shot` utan skärm |
| `--accent` `#8A1F42` | `--paper` | **7,66:1** | AAA | Idag-etikett, kursiv kicker, "Lägg till", aktiv navmarkör |
| `--accent` | `--paper-2` | **7,05:1** | AAA | Textknapp i budgetremsan och i summeringsblocket |
| `--on-accent` `#FFFFFF` | `--accent` | **8,92:1** | AAA | Primärknappens etikett |
| `--on-accent` | `--accent-press` `#6E1935` | **11,33:1** | AAA | Primärknappen tryckt |
| `--paper` | `--ink` | **15,17:1** | AAA | Bocken i ifylld kryssruta, toast-text |
| `--rule` `#CBD1D3` | `--paper` | **1,33:1** | Dekorativ | Enbart avdelare — får aldrig bära betydelse |
| `--rule-2` `#B3BBBE` | `--paper` | **1,68:1** | Dekorativ | Enbart avdelare — får aldrig bära betydelse |
| `#FFFFFF` | foto + `--scrim` (värsta fall: vitt foto) | **10,23:1** | AAA | Text på helbleed-hjälte |

**Mörkt läge**

| Text | Bakgrund | Ratio | Bedömning |
|---|---|---|---|
| `--ink` `#E9ECEE` | `--paper` `#111416` | **15,59:1** | AAA |
| `--ink` | `--paper-2` `#191D1F` | **14,31:1** | AAA |
| `--ink` | `--accent-soft` `#2A1720` | **14,25:1** | AAA |
| `--ink-2` `#A6AFB3` | `--paper` | **8,28:1** | AAA |
| `--ink-2` | `--paper-2` | **7,60:1** | AAA |
| `--ink-3` `#7E888C` | `--paper` | **5,10:1** | AA (ej AAA) |
| `--ink-3` | `--paper-2` | **4,68:1** | AA — men förbjuden ändå, se RÄTTELSE (regeln ska vara lägesoberoende) |
| `--ink-3` | `--shot` `#1E2325` | **4,38:1** | **UNDERKÄNT** |
| `--accent` `#EE93AB` | `--paper` | **8,28:1** | AAA |
| `--accent` | `--paper-2` | **7,60:1** | AAA |
| `--on-accent` `#26060F` | `--accent` | **8,43:1** | AAA |
| `--on-accent` | `--accent-press` `#F5B7C6` | **11,18:1** | AAA |
| `--rule` `#272C2F` | `--paper` | **1,31:1** | Dekorativ |
| `--rule-2` `#3A4145` | `--paper` | **1,78:1** | Dekorativ |

> **RÄTTELSE 1 — `--ink-3` får aldrig ligga på `--paper-2`.**
> I riktningen står `.kap` (`--ink-3`) på `--paper-2` i budgetremsan (`.remsa`),
> i summeringsblocket (`.kassa`) och i den tomma dagraden (`.dag--tom .d`).
> Uträknat blir det **4,31:1** i ljust läge — under AA för 10px text.
> Regeln, kodad så den går att granska:
> ```css
> .remsa .kap, .kassa .kap, .dag--tom .d { color: var(--ink-2); }  /* 4,86:1 ✓ */
> ```
> Generellt: **`--ink-3` bara på `--paper`. På `--paper-2` och `--shot` gäller `--ink-2`.**

> **RÄTTELSE 2 — betydelsebärande linjer ritas i `--ink-3`, inte i `--rule-2`.**
> Riktningen ritar den streckade prissiffran, ramen runt "pris saknas", teckenförklaringens
> streck och fyrkant, samt månadsstaplarna i `--rule-2`. Det ger **1,68:1** mot papperet.
> Det är grafiska objekt som bär information och kräver 3:1. `--ink-3` ger **4,68:1**.
> `--rule` och `--rule-2` behåller sin roll som rena avdelare, där 1,33 och 1,68 är rätt —
> de bär ingen betydelse och behöver ingen kontrast.

### 2.3 Accentregeln

**Accenten har exakt en betydelse: här är du, och här går vägen vidare.**

Den märker ut nuläget och den enda primära handlingen. Ingenting annat.

Tillåtet:
- nuläget: dagens rad i veckolistan (`.dag--idag .d`), aktiv flik i bottennav
  (`[aria-current="page"] .mark`), aktuell månad i månadsdiagrammet (`.man--topp i`),
  den förbrukade delen av budgetmätaren (`.meter i`)
- vägen vidare: primärknappen, den enda textknappen på skärmen (`.lagg`)
- tidningens egen röst: den kursiva kickern under hjälterubriken

Förbjudet, utan undantag:
- pris, prisförändring, bra pris, dåligt pris, kampanj, rea
- status, varning, fel, "över budget", "saknas", "gammal data"
- kvalitet, betyg, favorit, Premium
- kategori- eller butiksfärg

**Granskningsregel:** en skärm får ha högst två accentmarkeringar synliga samtidigt —
nuläget och vägen vidare. Ser du en tredje har någon börjat använda accenten som status.

Det finns ingen `--danger`, ingen `--gold`, ingen `--success`. Systemet har en färg.
Destruktiva val (radera konto, ta bort vara) skrivs som text i `--ink` med en förklarande
mening och bekräftas i modal — inte som en röd knapp.

---

## 3. Typografi

### 3.1 Familjer

```css
--f-disp:"Newsreader",Georgia,"Times New Roman",serif;
--f-ui:"Archivo","Helvetica Neue",Helvetica,Arial,sans-serif;
```

Newsreader används **bara** för mat och pengar: rätternas namn, skärmrubriker,
summor och stortalet. Archivo används för allt annat: etiketter, metadata, brödtext,
knappar, navigering. Kursiv Newsreader är en egen röst — kickern under hjälterubriken och
den tomma dagens "Ingen middag planerad" — aldrig betoning i löpande text.

Laddning: `<link rel="preconnect">` mot `fonts.googleapis.com` och `fonts.gstatic.com`,
sedan
`family=Archivo:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,300..700;1,6..72,300..600&display=swap`.
Fallbackstackarna ovan är obligatoriska — Georgia och Helvetica finns på de plattformar
appen körs på, och `display=swap` gör att sidan är läsbar innan Newsreader kommit fram.

### 3.2 Skalan

| Roll | Familj | Storlek | Vikt | Radavstånd | Spärrning | Klass |
|---|---|---|---|---|---|---|
| Hjälterubrik (stortal, endast Sparat) | disp | 82px | 400 | 0.86 | −0.035em | `.stortal` |
| Hjälterubrikens enhet ("kr") | disp | 26px | 400 | ärvs | −0.01em | `.stortal small` |
| Skärmrubrik, stor (Ikväll: rättens namn) | disp | 38px | 400 | 1.0 | −0.02em | `.tonight h2` |
| Skärmrubrik (Veckan) | disp | 30px | 400 | 1.0 | 0 | `.veckotopp h2` |
| Skärmrubrik, kompakt (Handla) | disp | 28px | 400 | 1.0 | 0 | `.handlatopp h2` |
| Kicker (kursiv, accent) | disp *kursiv* | 16px | 400 | 1.3 | 0 | `.kicker` |
| Rättens namn i lista | disp | 16.5px | 400 | 1.18 | −0.01em | `.dag .namn` |
| Rättens namn i rutnät | disp | 16px | 400 | 1.15 | −0.01em | `.duo .namn` |
| Underrubrik (Sparat: bytet) | disp | 20px | 400 | 1.08 | −0.01em | `.bytet h3` |
| Sektionsrubrik (avdelning) | ui | 10px | 600 | 1.5 | **0.2em** versaler | `.kap.kap-ink` |
| Etikett i kapitäler | ui | 10px | 600 | 1.5 | **0.2em** versaler | `.kap` |
| Etikett, smal (dag, navflik, stapel) | ui | 9.5–10px | 600 | 1.4 | **0.14em** versaler | `.d`, `.nav small`, `.man span` |
| Ordmärke i topplisten | ui | 10.5px | 600 | **0.26em** versaler | 1 | `.wordmark` |
| Brödtext | ui | 14px | 400 | 1.5 | 0 | `body` |
| Brödtext, tät (ingredienser) | ui | 13.5px | 400 | 1.5 | 0 | `.ingr` |
| Bildtext | ui | 11–12.5px | 400 | 1.5 | 0 | `.meta`, `.under`, `.not` |
| Pris, normalt | ui | 14px | 400 | 1.4 | 0 | `.pris` |
| Pris, litet (rutnät, trio) | ui | 12–13px | 400 | 1.4 | 0 | `.duo .pris` |
| Pris, framhävt (per portion, dagssumma) | **disp** | 19px | 400 | 1.2 | 0 | `.portionsrad .pris`, `.summa` |
| Pris, summa i kassan | **disp** | 26px | 400 | 1.1 | 0 | `.kassa .summa` |
| Prismarkör "ca" | ui | 9.5px | 600 | 1 | 0.16em versaler | `.cirka` |
| "Pris saknas"-etikett | ui | 10px | 600 | 1 | 0.14em versaler | `.saknas` |

Ingen vikt över 600 finns i systemet. Archivo laddas i 400/500/600 och punkt slut —
fet stil är inte ett sätt att göra något viktigt, det gör man med storlek och luft.

Rubriker sätts i `font-weight:400`. En Newsreader i 400 på 38px är redan tyngre än
omgivningen; att sätta 700 gör den bullrig, inte viktigare.

### 3.3 `font-variant-numeric: tabular-nums`

Regeln i tre delar:

1. **Globalt på.** `body{font-variant-numeric:tabular-nums}`. Alla siffror i appen står
   i kolumn, för nästan varje siffra här är ett belopp som ska gå att jämföra med
   siffran ovanför.
2. **Explicit återdeklarerad** på varje element som visar ett belopp:
   `.pris`, `.summa`, `.stortal`, `.manrad div`, `.kvar b`, `.meta`, `.mangd`.
   Skälet är mekaniskt: `font`-kortformen nollställer `font-variant-numeric`. Så länge
   någon regel i filen sätter `font:700 20px var(--f-disp)` tappar det elementet
   tabularsiffrorna tyst. Återdeklarationen gör att en sådan regel inte kan förstöra
   priskolumnen.
3. **Aldrig avstängd.** Det finns inget fall i appen där proportionella siffror är
   rätt. Om någon vill ha det, är det ett tecken på att texten inte är ett belopp och
   inte hör hemma i en priskolumn.

```css
body{font-variant-numeric:tabular-nums}
.pris,.summa,.stortal,.manrad div,.kvar b,.dag .meta,.vara .mangd{
  font-variant-numeric:tabular-nums;
}
```

### 3.4 Talformat

- Decimalkomma: `38,50 kr`. Aldrig punkt.
- Tusental med tunt hårt mellanslag U+2009: `1 340 kr` (`1&#8239;340` i HTML — U+202F,
  smalt hårt mellanslag, som i riktningen).
- Hårt mellanslag U+00A0 mellan siffra och `kr`, så beloppet aldrig bryts över raden.
- Procent skrivs ut med mellanslag: `crème fraiche 34 %`.
- Intervall med tankstreck utan mellanslag: `7–13 september`.

---

## 4. Rum och linjer

### 4.1 Spacing-skala

Åtta steg. Inga andra värden får förekomma i ny CSS.

```css
--sp-1:2px;  --sp-2:5px;  --sp-3:7px;   --sp-4:10px;
--sp-5:12px; --sp-6:16px; --sp-7:20px;  --sp-8:28px;
```

Användning i praktiken:
- `--sp-1` mellan en etikett och siffran under den
- `--sp-2`/`--sp-3` inuti en rad (mellan bild och text, mellan siffra och enhet)
- `--sp-4`/`--sp-5` mellan rader och block
- `--sp-6` mellan bilder i ett rutnät (`.duo`, `.trio`)
- `--sp-7` sidmarginal, se nedan
- `--sp-8` mellan sektioner som verkligen inte hör ihop

### 4.2 Marginaler

```css
--gutter:20px;   /* enda sidmarginalen i hela appen */
```

- **Sidmarginal 20px** på allt textinnehåll. Sätts som `padding-inline` på blocket,
  aldrig som `margin` på enskilda element.
- **Helbleed** (`padding-inline:0`) gäller exakt tre saker: hjältefotot, det breda fotot
  på Sparat, och skiljelinjerna mellan varurader/dagrader — linjen ska gå kant till kant,
  det är det som gör att listan ser tryckt ut i stället för inramad.
- **Asymmetrisk sättning:** rättens namn på Ikväll dras 8px in i högermarginalen
  (`margin-right:-8px`) så en lång rubrik får plats utan att brytas illa. Det är
  avsiktligt och ska inte "rättas".
- **Minsta sidogutter vid 400px och smalare: 16px.** Sätts en gång på ytterblocket, med
  `padding-block` för vertikal padding, aldrig med `padding`-kortform som nollställer sidorna.
- **Botten:** `padding-bottom: calc(64px + env(safe-area-inset-bottom))` på scrollytan,
  så bottennavigeringen aldrig ligger över sista raden.

### 4.3 Radier

```css
--radius:0;
```

**Radie används ingenstans inuti appen.** Konkret nolla:

- knappar (primär, sekundär, text) — 0
- kryssrutor och bockrutor — 0, det är kvadrater
- foton och bildplatshållare — 0
- bottenark och modalpanel — 0, även upptill
- toast — 0
- fält och select — 0
- bottennavigeringen — 0
- avatar/profilknapp — 0, det är en kvadrat med initialer

Enda undantaget i hela kodbasen: telefonramen i designpresentationen
(`src-D.html .phone{border-radius:30px}`). Den finns inte i appen.

Om något ser för hårt ut är svaret mer luft, inte rundare hörn.

### 4.4 Linjetjocklekar

| Roll | Tjocklek | Färg | Var |
|---|---|---|---|
| Avdelare inuti lista | 1px | `--rule` | Mellan varurader, mellan dagrader, under prisraden |
| Avdelare mellan sektioner | 1px | `--rule-2` | Ovanför avdelningsrubrik, ovanför summering, ovanför/under budgetremsan, ovanför bottennav, ovanför bottenark |
| Utfyllnadslinje i rubrikrad | 1px | `--rule-2` | `.rubrikrad .linje` (linjen som fyller ut efter "Senare i veckan") |
| Budgetmätarens spår | 3px | `--rule` | `.meter` |
| Budgetmätarens markör | 1px | `--ink` | `.meter::after`, sticker 3px över och under spåret |
| Kryssrutans ram | 1.5px | `--ink-3` | `.ruta` (RÄTTELSE 2 — riktningen har `--rule-2`) |
| Streckad prissiffra | 1.5px dashed | `--ink-3` | `.pris--ca .tal` (RÄTTELSE 2) |
| Ram runt "pris saknas" | 1px | `--ink-3` | `.saknas` (RÄTTELSE 2) |
| Fokusring | 2px | `--accent` (`--ink` på accentyta) | Alla fokuserbara element, offset 2px |
| Månadsstapel | fyllning | `--ink-3` / `--accent` | `.man i` (RÄTTELSE 2) |

Alla linjer sätts som `border-top` eller `border-bottom` på innehållselementet — inga
`<hr>`, inga pseudo-element för vanliga avdelare. Undantaget är mätarens markör, som är
`::after` eftersom den ska sticka utanför spåret.

### 4.5 Den enda tillåtna skuggan

```css
--shadow-sheet: 0 -16px 48px -24px var(--shadow);
```

Den får förekomma på **exakt två element**: bottenarkets panel och modalens panel — och
bara medan de är öppna över annat innehåll. Skuggan finns där för att säga "det här ligger
ovanpå", inget annat.

Överallt annars: `box-shadow:none`. Inga kortskuggor, ingen `--shadow-lg`, ingen
`backdrop-filter:blur()` på topplist eller nav. En mattidning har inte upphöjda kort.

---

## 5. Komponenter

Genomgående krav: **minsta träffyta 44×44 CSS-px** på allt som går att trycka på.
När kontrollen ska *se* mindre ut används den här hjälpklassen — den utvidgar träffytan
utan att flytta något visuellt:

```css
.tapmin{position:relative}
.tapmin::after{
  content:"";position:absolute;top:50%;left:50%;
  width:max(100%,44px);height:max(100%,44px);
  transform:translate(-50%,-50%);
}
```

Fokus, en gång för alla, gäller varje komponent nedan:

```css
:where(a,button,summary,input,select,textarea,[tabindex]):focus-visible{
  outline:2px solid var(--accent);
  outline-offset:2px;
}
/* på accentfärgad yta byter ringen färg, annars är den osynlig */
.btn-primar:focus-visible{outline-color:var(--ink)}
```

`:focus{outline:0}` är förbjudet i hela filen. Se rivningslistan, rad 15 och 64.

### 5.1 Knapp

**Primär** — max en per skärm.

```css
.btn-primar{
  display:flex;align-items:center;justify-content:center;gap:10px;
  width:100%;min-height:52px;padding:0 20px;
  border:0;border-radius:0;
  background:var(--accent);color:var(--on-accent);
  font:500 15px/1.2 var(--f-ui);letter-spacing:.02em;
}
.btn-primar:active{background:var(--accent-press)}
.btn-primar[aria-disabled="true"]{
  background:var(--paper-2);color:var(--ink-3);
  box-shadow:inset 0 0 0 1px var(--rule-2);cursor:default;
}
```

| Tillstånd | Utseende |
|---|---|
| Normal | `--accent` botten, `--on-accent` text, 8,92:1 |
| Tryckt | `--accent-press` botten, 11,33:1. **Ingen skalning, ingen transform.** |
| Inaktiv | `--paper-2` botten, `--ink-3` text (4,31 — men undantaget för inaktiva kontroller gäller; formen bär budskapet: ram i stället för fyllning) + `aria-disabled="true"`, inte `disabled`, så den behåller fokus och kan förklara varför |
| Fokus | `outline:2px solid var(--ink)`, offset 2px |

**Sekundär**

```css
.btn-sekundar{
  display:flex;align-items:center;justify-content:center;
  width:100%;min-height:52px;padding:0 20px;
  border:1px solid var(--ink);border-radius:0;
  background:transparent;color:var(--ink);
  font:500 15px/1.2 var(--f-ui);letter-spacing:.02em;
}
.btn-sekundar:active{background:var(--paper-2)}
.btn-sekundar[aria-disabled="true"]{border-color:var(--rule-2);color:var(--ink-3)}
```

**Textknapp** — formen är understruken text i kapitäler, aldrig en ram.

```css
.btn-text{
  display:inline-flex;align-items:center;min-height:44px;padding:0 2px;
  background:none;border:0;color:var(--accent);
  font:600 10px/1 var(--f-ui);letter-spacing:.14em;text-transform:uppercase;
}
.btn-text > span{border-bottom:1px solid var(--accent);padding-bottom:2px}
.btn-text:active{color:var(--accent-press)}
.btn-text:active > span{border-bottom-width:1.5px;border-color:var(--accent-press)}
.btn-text[aria-disabled="true"]{color:var(--ink-3)}
.btn-text[aria-disabled="true"] > span{border-bottom-color:transparent}
```

Träffytan: `min-height:44px` finns, men en kort etikett som "Lägg till" blir ~70px bred —
över 44. Blir etiketten kortare än så, lägg till `.tapmin`.

### 5.2 Helbleed-hjälte med text på foto

Används där texten måste ligga ovanpå (dagens rätt i veckovyn, det breda fotot på Sparat
när en rubrik ska ligga i bild). När det finns plats sätts texten hellre **under** fotot,
som på Ikväll — det är riktningens förstahandsval.

```css
.hjalte{position:relative;background:var(--shot);margin-inline:0}
.hjalte img{display:block;width:100%;height:268px;object-fit:cover}
.hjalte::after{                       /* skärmen */
  content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(180deg,transparent 38%,var(--scrim) 100%);
}
.hjalte-text{
  position:absolute;left:20px;right:20px;bottom:14px;z-index:1;
  color:#FFFFFF;                      /* låst vitt — inte --ink */
  text-shadow:none;                   /* skärmen gör jobbet, inte en skugga */
}
.hjalte-text .kap{color:rgba(255,255,255,.86)}
.hjalte-text h2{font:400 30px/1.05 var(--f-disp);letter-spacing:-.02em;margin:4px 0 0}
```

- Skärmen är obligatorisk. Utan den är texten oläsbar över ett ljust foto.
- Med `--scrim` på `.78` mot ett helvitt foto blir vit text **10,23:1**. Det är golvet,
  inte snittet — mot ett normalt matfoto är det bättre.
- Texten är alltid `#FFFFFF`, inte `--ink`. Ett foto har inget tema.
- `object-fit:cover` med fast höjd, plus `max-width:100%`, så bilden aldrig sprängar layouten.
- Bildhöjd: 268px på Ikväll, 180px i veckovyn, 120px på Sparat.
- Träffyta: hela `.hjalte` är knappen (`<button>`), alltså långt över 44×44.
- Tryckt: `.hjalte:active::after{background:linear-gradient(180deg,transparent 30%,var(--scrim) 100%)}`
  — skärmen kryper uppåt. Ingen skalning av fotot.
- Fokus: `outline:2px solid #FFFFFF; outline-offset:-4px` (inåt, annars försvinner ringen
  i helbleed-kanten).

### 5.3 Prisrad

Raden som redovisar ett pris med etikett. Två element på baslinjen, linje ovanför.

```css
.prisrad{
  display:flex;align-items:baseline;justify-content:space-between;gap:12px;
  margin:12px var(--gutter) 0;padding-top:9px;
  border-top:1px solid var(--rule);
}
.prisrad .kap{color:var(--ink-3)}
.prisrad .pris{font-family:var(--f-disp);font-size:19px;white-space:nowrap}
```

Etiketten står först och är liten; priset står sist och är i Newsreader. Det är
bildtextsförhållandet: etiketten säger vad, siffran säger hur mycket, ingen av dem skriker.
Ej klickbar, alltså inget träffytekrav.

### 5.4 Dagrad i veckolistan

```css
.dagar{border-top:1px solid var(--rule)}
.dag{
  display:grid;grid-template-columns:36px 1fr 76px;gap:10px;align-items:center;
  min-height:44px;padding:10px var(--gutter);
  border-bottom:1px solid var(--rule);
}
.dag .d{font:600 10px/1.4 var(--f-ui);letter-spacing:.14em;text-transform:uppercase;
        color:var(--ink-3);align-self:start;padding-top:2px}
.dag .mitt{display:flex;align-items:center;gap:12px;min-width:0}
.dag img{flex:0 0 52px;width:52px;height:52px;object-fit:cover;background:var(--shot)}
.dag .namn{display:block;font:400 16.5px/1.18 var(--f-disp);letter-spacing:-.01em}
.dag .meta{display:block;margin-top:3px;font-size:11px;color:var(--ink-3)}
.dag .hoger{text-align:right;font-size:13px}

.dag--idag .d{color:var(--accent)}
.dag--tom{background:var(--paper-2)}
.dag--tom .d{color:var(--ink-2)}                  /* RÄTTELSE 1 */
.dag--tom .tomtext{font:italic 400 15.5px/1.3 var(--f-disp);color:var(--ink-2)}
```

- Faktisk höjd med 52px-miniatyr blir 72px; `min-height:44px` är golvet för rader utan bild.
- **Idag kodas i två kanaler:** accentfärgad dagförkortning *och* ordet "Ikväll" först i
  `.meta`. Färgen ensam överlever inte gråskala.
- Tom dag kodas i två kanaler: nedsänkt `--paper-2`-fält *och* kursiv Newsreader.
- Hela raden är en `<button>` när det finns en rätt; på tom dag är bara `.btn-text` klickbar,
  och den har egen 44px-höjd.
- Tryckt: `.dag:active{background:var(--paper-2)}` — på tom dag i stället `--rule`.
- Fokus: standardringen, `outline-offset:-2px` så den inte krockar med raden ovanför.

### 5.5 Varurad i inköpslistan

```css
.vara{
  display:flex;align-items:center;gap:13px;width:100%;
  min-height:44px;padding:10px var(--gutter);
  border:0;border-bottom:1px solid var(--rule);
  background:none;text-align:left;
}
.ruta{
  flex:0 0 19px;width:19px;height:19px;
  border:1.5px solid var(--ink-3);      /* RÄTTELSE 2 */
  display:flex;align-items:center;justify-content:center;
}
.ruta svg{display:none}
.ruta svg path{stroke:var(--paper);stroke-width:1.8;fill:none}
.vara .txt{flex:1;min-width:0;font-size:14px}
.vara .mangd{margin-left:7px;font-size:11.5px;color:var(--ink-3)}

.vara--klar .ruta{background:var(--ink);border-color:var(--ink)}
.vara--klar .ruta svg{display:block}
.vara--klar .txt,.vara--klar .mangd,.vara--klar .pris{
  color:var(--ink-3);text-decoration:line-through;
}
.vara:active{background:var(--paper-2)}
```

- Hela raden är träffytan (`<button aria-pressed>`), 44px hög × full bredd. Kryssrutan är
  19px men har ingen egen lyssnare — det är rätt lösning, inte ett undantag från 44-regeln.
- Avbockat kodas i tre kanaler: ifylld ruta, genomstruken text, dämpad färg. Ingen opacitet
  — `opacity` under 1 sänker kontrasten okontrollerat (se rivningslistan).
- `aria-pressed="true"/"false"` på knappen, inte `aria-checked`.
- Ingen `transition` på färgen längre än 120ms; ingen `transform`.

### 5.6 Avdelningsrubrik

```css
.avdelning{
  position:sticky;top:44px;z-index:2;
  display:flex;align-items:baseline;justify-content:space-between;
  padding:10px var(--gutter) 5px;
  border-top:1px solid var(--rule-2);
  background:var(--paper);              /* obligatoriskt — annars skiner listan igenom */
}
.avdelning .namn{font:600 10px/1.5 var(--f-ui);letter-spacing:.2em;
                 text-transform:uppercase;color:var(--ink-2)}
.avdelning .antal{font:600 10px/1.5 var(--f-ui);letter-spacing:.2em;
                  text-transform:uppercase;color:var(--ink-3)}
```

`position:sticky` under topplisten (44px) är avsiktligt: man går genom butiken avdelning
för avdelning och måste kunna se vilken avdelning man är i utan att skrolla upp. Rubriken
är inte klickbar.

### 5.7 Summeringsblock

Sist i inköpslistan, tryckt mot botten med `margin-top:auto`.

```css
.kassa{
  margin-top:auto;padding:12px var(--gutter) 13px;
  border-top:1px solid var(--rule-2);background:var(--paper-2);
}
.kassa .toppen{display:flex;align-items:baseline;justify-content:space-between}
.kassa .kap{color:var(--ink-2)}                    /* RÄTTELSE 1 */
.kassa .summa{font:400 26px/1.1 var(--f-disp)}
.kassa .noter{margin-top:8px;display:flex;flex-direction:column;gap:5px}
.kassa .not{display:flex;align-items:center;gap:9px;font-size:11px;color:var(--ink-2)}

/* teckenförklaringens glyfer — samma tre former som prisreglerna */
.prick   {flex:0 0 22px;width:22px;height:1.5px;background:var(--ink)}
.streck  {flex:0 0 22px;width:22px;height:0;border-bottom:1.5px dashed var(--ink-3)}
.fyrkant {flex:0 0 22px;width:22px;height:12px;border:1px solid var(--ink-3)}
```

Teckenförklaringen är inte dekoration — den är hela skälet till att prisreglerna går att
lära sig. Den ska stå kvar även när alla priser är kontrollerade; då lyder raden
"Alla priser kontrollerade mot Willys i morse."

### 5.8 Budgetremsa

```css
.remsa{
  margin-top:10px;padding:9px var(--gutter) 11px;
  border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
  background:var(--paper-2);
}
.remsa .rad{display:flex;align-items:baseline;justify-content:space-between;gap:10px}
.remsa .kap{color:var(--ink-2)}                    /* RÄTTELSE 1 */
.remsa .kvar{font-size:12.5px;color:var(--ink-2)}
.remsa .kvar b{color:var(--ink);font-weight:600}
.meter{position:relative;margin-top:7px;height:3px;background:var(--rule)}
.meter i{position:absolute;inset:0 auto 0 0;background:var(--accent)}
.meter::after{                                     /* markören */
  content:"";position:absolute;top:-3px;bottom:-3px;
  left:var(--andel,0%);width:1px;background:var(--ink);
}
```

- Fyllnadsgraden sätts som `style="--andel:28%"` på `.meter` och `width:var(--andel)` på
  `.meter i`. Ett värde, två användningar, ingen risk att de glider isär.
- **Markören är formkodningen.** En 3px-remsa i accentfärg går inte att läsa i gråskala;
  den 1px svarta strecket som sticker ut över och under spåret gör det.
- `role="img"` på `.meter` med `aria-label="238 kronor av 850 använda"`. Aldrig bara
  procent — 28 % av vad är ingen upplysning i en affär.
- **Över budget:** remsan blir inte röd. Fyllnaden går till 100 %, markören flyttar till
  `100%`, och `.kvar` byter text till `<b>84 kr</b> över 850 kr`. Överskridandet står i
  ord, inte i färg.
- Remsan är hela komponentens träffyta när den är klickbar: `min-height:44px` på det
  omslutande `<button>`.

### 5.9 Statistikrad (månadsdiagram på Sparat)

```css
.manader{display:flex;align-items:flex-end;gap:10px;height:64px;margin:18px var(--gutter) 0}
.man{flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:6px;height:100%}
.man i{display:block;flex:0 0 auto;background:var(--ink-3)}   /* RÄTTELSE 2 */
.man--topp i{background:var(--accent)}
.man span{font:600 9.5px/1.4 var(--f-ui);letter-spacing:.14em;
          text-transform:uppercase;color:var(--ink-3)}
.manrad{display:flex;gap:10px;margin:0 var(--gutter);padding-top:6px;
        border-top:1px solid var(--rule)}
.manrad div{flex:1;font-size:10.5px;color:var(--ink-3);font-variant-numeric:tabular-nums}
```

- Stapelhöjd sätts inline (`style="height:41%"`) mot diagrammets 64px.
- Värdena står utskrivna i `.manrad` under staplarna. Diagrammet är alltså läsbart även om
  man inte kan tolka staplarnas längd — det är kravet, inte en bonus.
- `role="img"` på `.manader` med en `aria-label` som räknar upp alla värden.
- Diagrammet är inte interaktivt. Blir det det, måste varje stapel bli en 44px hög
  träffyta — hela `.man`-kolumnen, inte bara stapeln.

### 5.10 Tomt tillstånd

Ingen streckad ruta, ingen ikon, ingen centrerad text.

```css
.tomt{
  padding:16px var(--gutter) 18px;
  border-top:1px solid var(--rule-2);
}
.tomt p{margin:0;font:italic 400 16px/1.4 var(--f-disp);color:var(--ink-2);max-width:28ch}
.tomt .btn-text{margin-top:8px}
```

Ett tomt tillstånd är en mening i kursiv Newsreader och en textknapp. Meningen säger vad
som saknas, knappen säger vad man gör åt det:

- "Ingen middag planerad" + `Lägg till middag`
- "Inköpslistan är tom tills du planerat veckan" + `Planera veckan`
- "Inga sparade pengar än — vi räknar från din första vecka" + (ingen knapp, det är inget
  att göra åt)

### 5.11 Laddningsskelett

```css
.skelett{
  background:var(--paper-2);
  position:relative;overflow:hidden;
}
.skelett::after{
  content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,transparent,var(--rule),transparent);
  transform:translateX(-100%);
  animation:skelett 1.4s var(--ease) infinite;
}
@keyframes skelett{to{transform:translateX(100%)}}

/* mått som matchar det som ska komma */
.skelett--rad{height:44px}
.skelett--bild{aspect-ratio:390/268;max-width:100%}
.skelett--rubrik{height:24px;max-width:16ch}
.skelett--pris{height:14px;width:72px;margin-left:auto}
```

Regler:
- Skelettet har **samma mått som innehållet som ersätter det**. En 44px rad blir 44px
  skelett. Inget hoppar när data kommer.
- Ingen radie, ingen puls som ändrar opacitet — bara ett svep i `--rule` över `--paper-2`.
- Behållaren får `aria-busy="true"` och en `<span class="sr-only">Hämtar priser</span>`.
- **Priser laddas aldrig som skelett.** Ett pris som inte kommit fram är "pris saknas"
  enligt regel 3, inte en grå låda. Skelett används för rader, bilder och rubriker.
- `prefers-reduced-motion`: `::after` får `display:none`, ytan blir stilla `--paper-2`.

### 5.12 Toast

En tryckt remsa mot botten, inte en flytande pillerknapp.

```css
.toast{
  position:fixed;left:0;right:0;
  bottom:calc(64px + env(safe-area-inset-bottom));
  z-index:40;
  display:flex;align-items:center;justify-content:space-between;gap:14px;
  min-height:48px;padding:10px var(--gutter);
  background:var(--ink);color:var(--paper);   /* 15,17:1 */
  font-size:13px;
}
.toast[hidden]{display:none}
.toast span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toast button{
  flex:none;min-height:44px;padding:0 2px;
  background:none;border:0;color:var(--paper);
  font:600 10px/1 var(--f-ui);letter-spacing:.14em;text-transform:uppercase;
}
.toast button > span{border-bottom:1px solid var(--paper);padding-bottom:2px}
.toast button:focus-visible{outline:2px solid var(--paper);outline-offset:2px}
```

- Sitter direkt ovanpå bottennavigeringen, kant till kant, ingen radie, ingen skugga.
- `role="status"` (artigt) — inte `alert`. En ångra-toast ska inte avbryta skärmläsaren.
- Livslängd 6 s när den har en åtgärd, 3,5 s utan. Timern pausas medan toasten har fokus.
- Max en toast åt gången. En ny ersätter den gamla i samma DOM-nod.
- Åtgärdsknappen har 44px höjd även om texten är liten.

### 5.13 Bottenark

```css
.ark-bakgrund{
  position:fixed;inset:0;z-index:55;
  display:flex;align-items:flex-end;justify-content:center;
  background:rgba(10,12,13,.5);
}
.ark-bakgrund[hidden]{display:none}
.ark{
  width:100%;max-width:480px;max-height:86dvh;overflow:auto;
  padding:16px var(--gutter) calc(24px + env(safe-area-inset-bottom));
  border-radius:0;
  border-top:1px solid var(--rule-2);
  background:var(--paper);
  box-shadow:var(--shadow-sheet);        /* enda tillåtna skuggan */
}
.ark-topp{
  display:flex;align-items:baseline;justify-content:space-between;gap:12px;
  padding-bottom:10px;margin-bottom:12px;border-bottom:1px solid var(--rule);
}
.ark-topp h2{margin:0;font:400 22px/1.15 var(--f-disp);letter-spacing:-.01em}
.ark-stang{
  flex:none;display:flex;align-items:center;justify-content:center;
  width:44px;height:44px;margin:-10px -10px -10px 0;
  background:none;border:0;color:var(--ink-2);font-size:20px;line-height:1;
}
```

- Ingen dragregel-pill upptill. Panelens överkant är en 1px `--rule-2`-linje.
- Stängknappen är 44×44 och dras ut i marginalen med negativ margin, så den ser liten ut
  men är stor att träffa.
- Krav på beteende: fokusfälla, `Escape` stänger, klick på bakgrunden stänger,
  `role="dialog" aria-modal="true" aria-labelledby`. Se 5.16.
- Öppning: se 7. Ingen fjäder, ingen studs.

### 5.14 Bottennavigering

```css
.nav{
  position:fixed;left:0;right:0;bottom:0;z-index:30;
  display:flex;
  height:calc(64px + env(safe-area-inset-bottom));
  padding-bottom:env(safe-area-inset-bottom);
  border-top:1px solid var(--rule-2);
  background:var(--paper);              /* ogenomskinlig — ingen blur */
}
.nav button{
  flex:1;min-height:44px;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;
  background:none;border:0;
  font:600 9.5px/1 var(--f-ui);letter-spacing:.14em;text-transform:uppercase;
  color:var(--ink-3);                   /* 4,68:1 ✓ */
}
.nav button .mark{width:16px;height:2px;background:transparent}
.nav button[aria-current="page"]{color:var(--ink)}
.nav button[aria-current="page"] .mark{background:var(--accent)}
.nav button:active{background:var(--paper-2)}
.nav button:focus-visible{outline:2px solid var(--accent);outline-offset:-3px}
```

- Fem flikar, `flex:1` var, alltså ≥78px bred × 64px hög på en 390px-skärm. Långt över 44×44.
- Aktiv flik kodas i två kanaler: mörkare text **och** accentstrecket ovanför. I gråskala
  syns strecket ändå eftersom det är fyllt mot tomt.
- Ingen bakgrundsblur, ingen skugga, ingen radie. Navigeringen är en fot på sidan.
- Ingen ikon behövs — etiketten i kapitäler är märket. Om ikoner läggs till får de vara
  16×16 och `stroke:currentColor`.
- `<nav aria-label="Huvudmeny">`, varje knapp `aria-current="page"` när den är vald.

### 5.15 Modal

Samma panel som bottenarket, men centrerad på breda skärmar.

```css
.modal{position:fixed;inset:0;z-index:60;display:flex;
       align-items:flex-end;justify-content:center;background:rgba(10,12,13,.5)}
.modal[hidden]{display:none}
.modal-panel{
  width:100%;max-width:480px;max-height:88dvh;overflow:auto;
  padding:20px var(--gutter) calc(24px + env(safe-area-inset-bottom));
  border:0;border-top:1px solid var(--rule-2);border-radius:0;
  background:var(--paper);box-shadow:var(--shadow-sheet);
}
@media(min-width:481px){
  .modal{align-items:center;padding:24px}
  .modal-panel{border:1px solid var(--rule-2)}
}
```

### 5.16 Fokusfälla och Escape (gäller 5.13 och 5.15)

Krav, inte förslag. Implementeras en gång och återanvänds för bottenark, modal och
inbjudningsvyn.

```js
const FOKUSERBARA =
  'a[href],button:not([disabled]),summary,input,select,textarea,[tabindex]:not([tabindex="-1"])';

function oppnaLager(panel, oppnare){
  panel.closest('[hidden]')?.removeAttribute('hidden');
  const forra = oppnare || document.activeElement;
  document.body.style.overflow = 'hidden';           // bakgrunden får inte skrolla

  const forsta = panel.querySelector(FOKUSERBARA);
  (forsta || panel).focus();                          // panel behöver tabindex="-1"

  function tangent(e){
    if (e.key === 'Escape'){ e.preventDefault(); stang(); return; }
    if (e.key !== 'Tab') return;
    const rutor = [...panel.querySelectorAll(FOKUSERBARA)].filter(el => el.offsetParent);
    if (!rutor.length) return;
    const [f, s] = [rutor[0], rutor[rutor.length - 1]];
    if (e.shiftKey && document.activeElement === f){ e.preventDefault(); s.focus(); }
    else if (!e.shiftKey && document.activeElement === s){ e.preventDefault(); f.focus(); }
  }

  function stang(){
    document.removeEventListener('keydown', tangent, true);
    document.body.style.overflow = '';
    panel.closest('[role="dialog"],.modal,.ark-bakgrund').setAttribute('hidden','');
    forra?.focus();                                   // fokus tillbaka dit det kom ifrån
  }

  document.addEventListener('keydown', tangent, true);
  return stang;
}
```

Panelen måste ha `role="dialog" aria-modal="true"` och antingen `aria-labelledby` mot sin
`<h2>` eller `aria-label`. Bakgrundsklick anropar samma `stang()`.

---

## 6. De tre prisreglerna

Prisets säkerhet är den enda information i appen som *måste* överleva gråskala, en dålig
telefonskärm i en butik och rödgrön färgblindhet. Därför kodas den i **form**, inte i färg.
De tre formerna är: **hel siffra**, **streckad siffra**, **tom ram**.

| Regel | Betyder | Form | Färg | Skärmläsare |
|---|---|---|---|---|
| 1. Kontrollerat pris | Vi har hämtat priset från butiken | Hel siffra, ingen dekoration | `--ink` | `38,50 kronor` |
| 2. Uppskattat pris | Vi räknar, vi vet inte | Kapitälprefix "ca" + siffra med **streckad** understrykning | `--ink-2`, prefix `--ink-3`, strecket `--ink-3` | `ungefär 41 kronor` |
| 3. Pris saknas | Vi vet inte, och vi gissar inte | **Tom ram** med tankstreck + "pris saknas" i kapitäler | `--ink-3` på `--paper`, ram `--ink-3` | `pris saknas` |

```css
.pris{
  font-variant-numeric:tabular-nums;
  font-size:14px;color:var(--ink);white-space:nowrap;
}

/* 2 — uppskattat */
.pris--ca{color:var(--ink-2)}
.pris--ca .cirka{
  margin-right:5px;vertical-align:.08em;
  font:600 9.5px/1 var(--f-ui);letter-spacing:.16em;text-transform:uppercase;
  color:var(--ink-3);
}
.pris--ca .tal{
  border-bottom:1.5px dashed var(--ink-3);   /* RÄTTELSE 2: var --rule-2, 1,68:1 */
  padding-bottom:1px;
}

/* 3 — saknas */
.saknas{
  display:inline-flex;align-items:center;justify-content:center;
  min-width:52px;height:20px;padding:0 7px;
  border:1px solid var(--ink-3);             /* RÄTTELSE 2: var --rule-2, 1,68:1 */
  color:var(--ink-3);
  font:600 10px/1 var(--f-ui);letter-spacing:.14em;text-transform:uppercase;
}
.saknas::before{content:"—";margin-right:6px;color:var(--ink-3)}
```

Markup:

```html
<span class="pris">38,50 kr</span>

<span class="pris pris--ca">
  <span class="cirka">ca</span><span class="tal">41 kr</span>
  <span class="sr-only">, uppskattat pris</span>
</span>

<span class="pris"><span class="saknas">pris saknas</span></span>
```

**Gråskaletest, som en utvecklare kan köra själv:** öppna skärmen Handla i
devtools → Rendering → *Emulate vision deficiencies: Achromatopsia*. Alla tre priserna
ska fortfarande gå att skilja åt. Om de inte gör det har någon smugit tillbaka färgkodning.

### Varför saknat pris aldrig är rött

Fyra skäl, i ordning efter tyngd:

1. **Rött är redan taget.** Systemets enda accent är oxblod `#8A1F42` — ett mörkt rött.
   En röd prislapp skulle läsas som *accentuerad*, alltså "här är du, här går vägen vidare".
   Det är raka motsatsen till "vi vet inte". Ett rött pris skulle framhäva just den siffra
   som har minst att säga.
2. **Rött betyder "något är fel, och det går att laga".** Ett saknat pris är ingen av
   delarna. Butiken har inte publicerat priset. Användaren har inte gjort något fel, appen
   har inte kraschat, och det finns ingenting att trycka på för att åtgärda det. Ett larm
   utan handling är bara oro.
3. **Rött och gult skalar inte.** En lista med tio varor där tre är gula och en är röd
   ser ut som en havererad instrumentpanel. Skärmen ska se ut som en inköpslista, för det
   är vad den är. Formkodningen — hel, streckad, tom — är tyst nog att tåla tio rader.
4. **Rött överlever inte det här användningsfallet.** Rödgrön färgblindhet drabbar ungefär
   var tolfte man. Skärmen läses ofta i butiksbelysning på en telefon med nedskruvad
   ljusstyrka. Färg är det första som försvinner; form är det sista.

Nuvarande kod gör exakt fel: `.price-status.missing{color:#b91c1c}` med ⚪-emoji (rad 186–187)
och `.chain-item.is-missing{background:#fdf1ef}` (rad 198) — rosa "felrad" för något som
inte är ett fel. Det rivs, se 10.

---

## 7. Rörelse

```css
--ease:cubic-bezier(.2,.6,.2,1);
--t-snabb:120ms;
--t-normal:180ms;
--t-lugn:240ms;
```

| Övergång | Egenskap | Längd | Easing |
|---|---|---|---|
| Vybyte (skärm → skärm) | `opacity` 0→1 | 160ms | `--ease` |
| Bottenark / modal in | `opacity` 0→1 + `translateY(12px)`→0 på panelen | 240ms | `--ease` |
| Bottenark / modal ut | `opacity` 1→0 | 140ms | `linear` |
| Bakgrundsdimma in/ut | `opacity` | 180ms / 140ms | `--ease` |
| Toast in | `opacity` + `translateY(8px)`→0 | 180ms | `--ease` |
| Toast ut | `opacity` | 140ms | `linear` |
| Tryckt tillstånd (rad, knapp, flik) | `background-color` | 90ms | `linear` |
| Avbockning i listan | `color`, `text-decoration-color` | 120ms | `linear` |
| Budgetmätarens fyllnad | `width` | 400ms | `--ease` |
| Laddningsskelett | `transform` svep | 1400ms | `--ease`, `infinite` |

Förbjudet:
- `transform: scale()` som tryckrespons. Alla `:active{transform:scale(.9x)}` i nuvarande
  CSS rivs. En tidningssida hoppar inte när man rör vid den.
- `cubic-bezier` med studs (`--ease-spring` i nuvarande fil). Aliasas till `--ease`.
- `transition:all`. Alltid namngivna egenskaper.
- Animering av `height`, `top`, `left`, `width` (utom mätarens `width`, som är en
  informationsförändring och inte en layoutanimering).
- `backdrop-filter`.

Vybytet flyttar ingenting i sidled. En mattidning bläddras inte, man slår upp ett uppslag.

```css
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{
    animation-duration:.001ms!important;
    animation-iteration-count:1!important;
    transition-duration:.001ms!important;
    scroll-behavior:auto!important;
  }
  .skelett::after{display:none}
}
```

Regeln nollar tiden, inte sluttillståndet: allt hamnar där det ska, direkt. Skelettets
svep är den enda animering som stängs av helt, eftersom ett svep utan tid bara är en grå
rand som står still mitt i rutan.

---

## 8. Text i gränssnittet

Kort stilregel. Gäller all synlig text, inklusive `aria-label` och felmeddelanden.

**Tankstreck.** I löpande text används tankstreck – (U+2013, en dash) med mellanslag runt:
"Ett pris saknas – vi gissar inte." Aldrig bindestreck som tankstreck. I intervall står
tankstrecket utan mellanslag: `7–13 september`, `20–25 min`. Ersättningstecknet för ett
tomt värde i en tabell eller ram är också tankstreck, inte bindestreck.

**Versaler.** Versal i början av meningen, gemener i övrigt. Ingen versal på substantiv i
mitten av en rubrik. Kapitäletiketter skrivs som **vanlig text i HTML** ("Veckans budget")
och versaliseras med `text-transform:uppercase` — versaler i källtexten gör att
skärmläsaren stavar dem bokstav för bokstav.

**Inga engelska tekniska felmeddelanden.** Ingen `Failed to fetch`, ingen `500`, inget
`NetworkError`. Varje fel översätts till vad som hände och vad man gör:

| I stället för | Skriv |
|---|---|
| `Failed to fetch` | "Vi når inte butikens priser just nu. Försök igen om en stund." |
| `500 Internal Server Error` | "Något gick fel hos oss. Vi tittar på det – försök igen om en stund." |
| `Invalid credentials` | "Fel e-post eller lösenord." |
| `Timeout` | "Butiken svarar inte. Priserna nedan är från i morse." |
| `No results` | "Inga recept matchar det du sökt." |

**Knapptexter i aktiv form som säger vad som händer.** Verbet först, objektet efter.

| I stället för | Skriv |
|---|---|
| OK / Klar / Skicka | Spara budgeten / Lägg till middag / Skicka svaret |
| Avbryt | Behåll som det är (i destruktiva val) |
| + | Lägg till vara |
| Visa alla | Visa alla 42 recept |
| Ja / Nej | Ta bort veckan / Behåll veckan |

**Priser i text** följer talformatet i 3.4. **Butiksnamn** skrivs som butiken skriver det
(Willys Årsta), aldrig versaliserat av CSS. **Vi/du:** appen säger "vi" om sig själv och
"du" om användaren; aldrig "man", aldrig "användaren".

---

## 9. Migreringstabell

### 9.1 Aliasskiktet

Nuvarande `styles.css` refererar till de gamla variabelnamnen i 800 rader kod. Vi byter
**inte** namnen i alla regler på en gång. I stället läggs ett aliasskikt **överst i filen**,
före allt annat, som definierar de nya tokens och sedan omdefinierar de gamla namnen i
termer av de nya. Då byter hela appen palett, radie och skuggor i ett enda commit, utan att
en enda befintlig regel rörs — och sedan kan reglerna rivas i etapper utan att appen går
sönder mitt i.

```css
/* ==========================================================================
   ALIASSKIKT — tillfälligt. Läggs FÖRST i styles.css, före alla gamla regler.
   Nya tokens definieras här; de gamla namnen pekar på dem. Raderas i etapp 7.
   ========================================================================== */
:root{
  /* --- nya tokens (full definition, se 2.1) --- */
  --paper:#ECEEEF; --paper-2:#E2E5E7;
  --ink:#16191B; --ink-2:#5A6367; --ink-3:#626B6F;
  --rule:#CBD1D3; --rule-2:#B3BBBE;
  --accent:#8A1F42; --accent-press:#6E1935; --accent-soft:#EBDDE2; --on-accent:#FFFFFF;
  --shot:#D2D7D9; --shadow:rgba(18,24,26,.22); --scrim:rgba(10,12,13,.78);
  --f-disp:"Newsreader",Georgia,"Times New Roman",serif;
  --f-ui:"Archivo","Helvetica Neue",Helvetica,Arial,sans-serif;
  --gutter:20px; --radius:0;
  --shadow-sheet:0 -16px 48px -24px var(--shadow);
  --ease:cubic-bezier(.2,.6,.2,1);

  /* --- alias: gamla namn pekar på nya --- */
  --bg:var(--paper);
  --surface:var(--paper);
  --surface-2:var(--paper-2);
  --primary:var(--accent);
  --primary-2:var(--accent-press);
  --primary-soft:var(--paper-2);      /* OBS: inte --accent-soft, se anmärkning */
  --on-primary:var(--on-accent);
  --accent-2:var(--accent-press);
  --accent-3:var(--ink);              /* var "grön för positivt" — blir neutral */
  --text:var(--ink);
  --muted:var(--ink-2);
  --text-muted:var(--ink-2);
  --line:var(--rule);
  --border:var(--rule);
  --danger:var(--ink);                /* rött utgår ur appen */
  --gold:var(--ink-2); --gold-2:var(--ink-2); --gold-soft:var(--paper-2);
  --r-sm:0; --r-md:0; --r-lg:0; --r-xl:0;
  --shadow:none;                      /* gamla --shadow var redan none */
  --shadow-lg:none; --shadow-gold:none; --noise:none;
  --ease-spring:var(--ease);
  --font-display:var(--f-disp);
  --font-body:var(--f-ui);
}
```

Två fällor att känna till innan du klistrar in:

- **Namnkrock på `--shadow`.** Gamla filen har `--shadow:none`, nya systemet vill ha
  `--shadow:rgba(...)` som skuggfärg. Lös det genom att döpa den nya till `--shadow-color`
  under alias-perioden och byta tillbaka i etapp 7. Blanda dem aldrig.
- **`--primary-soft` aliasas till `--paper-2`, inte till `--accent-soft`.** Gamla filen
  använder `--primary-soft` som "ljus bakgrundsplatta" på ett femtiotal ställen (chips,
  ikonrutor, tryckta rader). Pekar man den på `--accent-soft` blir halva appen svagt rosa,
  vilket bryter accentregeln direkt. `--paper-2` är rätt översättning av dess faktiska roll.

### 9.2 Tabell

| Nuvarande variabel (`styles.css` rad 1) | Ny token | Anmärkning |
|---|---|---|
| `--bg:#f6f7f4` | `--paper` | Cream → sval pappersvit. Hela appens ton ändras här. |
| `--surface:#fff` | `--paper` | **Ingen egen ytfärg.** Kort försvinner; det som var vitt på cream blir samma papper som runt omkring, avgränsat med linje. |
| `--surface-2:#eef0ec` | `--paper-2` | Nedsänkt fält. Rollen är oförändrad. |
| `--primary:#146c43` | `--accent` | Endast där accentregeln (2.3) tillåter. Alla andra förekomster ska bli `--ink` eller `--ink-2` — det är etapp 3-arbetet. |
| `--primary-2:#0f5233` | `--accent-press` | Enbart tryckt tillstånd. |
| `--primary-soft:#e4efe7` | `--paper-2` | Se fällan ovan. `--accent-soft` används i praktiken inte. |
| `--on-primary:#fff` | `--on-accent` | Oförändrad roll. |
| `--accent:#146c43` | `--accent` | Duplikat av `--primary` idag. Slås ihop. |
| `--accent-2:#0f5233` | `--accent-press` | Duplikat av `--primary-2`. |
| `--accent-3:#146c43` | `--ink` | Användes för "positivt" (besparing, kampanj). Blir neutral text — besparingar får inte egen färg. |
| `--ink:#17211b` | `--ink` | Namnet behålls, värdet byts. |
| `--text:#17211b` | `--ink` | Duplikat av `--ink`. Slås ihop. |
| `--muted:#6b756e` | `--ink-2` | **Obs:** gamla `--muted` ger 4,44:1 mot `--bg` — under AA. Nya `--ink-2` ger 5,28:1. Bytet lagar ett befintligt fel. |
| `--text-muted:#6b756e` | `--ink-2` | Duplikat av `--muted`. |
| *(saknas)* | `--ink-3` | **Ny.** Gamla filen har ingen tredje textnivå — kapitäletiketter fick `--muted`. |
| `--line:#e6e9e6` | `--rule` | Oförändrad roll (avdelare). |
| `--border:#e6e9e6` | `--rule` | Duplikat av `--line`. Efter etapp 3 har den ingen användning kvar: kortramar finns inte, bara avdelare. |
| *(saknas)* | `--rule-2` | **Ny.** Tyngre sektionslinje. |
| `--danger:#c0392b` | — | **Utgår.** Rött finns inte i appen. Destruktiva val skrivs i ord. Se rivningslistan för de sex ställen som använder det. |
| `--gold:#9a7a3a` | — | **Utgår.** 4,02:1 mot vitt, alltså underkänt redan idag. Premium markeras med ordet "Premium" i kapitäler. |
| `--gold-2:#7d6230` | — | Utgår. |
| `--gold-soft:#f4eee0` | `--paper-2` | Utgår som guld; de tre varningsrutorna som använder den blir nedsänkta fält. |
| `--r-sm:12px` | `--radius` (`0`) | |
| `--r-md:16px` | `--radius` (`0`) | |
| `--r-lg:20px` | `--radius` (`0`) | |
| `--r-xl:28px` | `--radius` (`0`) | |
| `--shadow:none` | — | Var redan `none`. Namnet frigörs till skuggfärgen, se fällan ovan. |
| `--shadow-lg:0 20px 40px -24px …` | `--shadow-sheet` | **Riktningen vänder skuggan uppåt** (`0 -16px 48px -24px`) eftersom den bara får finnas på ark och modal som kommer underifrån. |
| `--shadow-gold:none` | — | Utgår. |
| `--noise:none` | — | Utgår. Oanvänd. |
| `--ease:cubic-bezier(.2,.8,.2,1)` | `--ease` (`cubic-bezier(.2,.6,.2,1)`) | Mjukare utgång, mindre "snärt". |
| `--ease-spring:cubic-bezier(.2,.8,.2,1)` | `--ease` | Var redan identisk med `--ease`; aliasas bort. |
| `--font-display:"Bricolage Grotesque"…` | `--f-disp` (`"Newsreader"…`) | Grotesk → antikva. Största enskilda visuella förändringen efter paletten. |
| `--font-body:"Manrope"…` | `--f-ui` (`"Archivo"…`) | |
| *(saknas)* | `--gutter:20px` | **Ny.** Gamla filen har `padding:4px 20px` på `.app` (rad 436) och `padding-inline:12px` under 340px (rad 75) — samma tal, spritt på flera ställen. |
| *(saknas)* | `--sp-1`…`--sp-8` | **Ny.** Gamla filen har inga spacing-tokens alls. |

### 9.3 Hårdkodade hex som inte går via variabler

De här värdena står direkt i regler och nås alltså inte av aliasskiktet. De måste bytas för
hand. Uträknad kontrast mot vit yta i parentes.

| Värde | Rad | Var | Ny token |
|---|---|---|---|
| `#879089` | 70 | `.bottom-nav-item` inaktiv (3,29:1 — **underkänt**) | `--ink-3` |
| `#7d867f` | 597 | `.bottom-nav-item` inaktiv, v2 (3,76:1 — **underkänt**) | `--ink-3` |
| `#a9b1aa` | 318 | `.shopping-remove` (2,20:1 — **underkänt**) | `--ink-3` |
| `#d8d3c4` | 71 | `.recipe-star` tom (1,50:1 — praktiskt osynlig) | `--ink-3` som ram, tom stjärna ritas som kontur |
| `#cfd5d0` | 506, 541, 568, 590, 680 | Streckade ramar och kryssrutor (1,49:1) | `--ink-3` (kryssruta, bär betydelse) / `--rule-2` (dekorativ) |
| `#b7c1b9` | 67, 99 | Kryssrutans ram (1,85:1) | `--ink-3` |
| `#e3e7e3` | 460 | `.progress-track` spår | `--rule` |
| `#aebbb1` | 69 | `.add-pantry-btn` streckad ram | `--rule-2` |
| `#bf3636` | 320, 402 | Hover-rött, `.sync-error` | `--ink` + ordbaserat fel |
| `#fbe4e1` | 69, 79, 80 | Rosa "fel"-bakgrund | `--paper-2` |
| `#fdf1ef` | 198 | `.chain-item.is-missing` rosa rad | **tas bort helt** — se 10 |
| `#b91c1c` | 186, 207 | Rött för saknat pris **och** för kampanj | `--ink-3` (saknat) / `--ink` (kampanj) |
| `#a16207` | 184 | Gult för uppskattat pris (4,92:1) | `--ink-2` + streckad form |
| `#15803d` | 194 | Grönt för besparing (5,02:1) | `--ink` |
| `#86efac` | 234 | Mörkt läge-grönt | Utgår med `--accent-3` |
| `#ff9b8f` | 66 | Över budget | Utgår — överskridande skrivs i ord |
| `#285b43` | 69 | Gradientstopp `.pantry-hero` | Utgår med gradienten |
| `#eceeea` | 2 | `html{background}` | `--paper` |
| `#5b6470`, `#e3e6ea`, `#14181f`, `#14532d`, `#6b665c`, `#ddd`, `#111` | 180–228, 706, 713 | Fallback-värden i `var(x, fallback)` | Ta bort fallbacken. Om variabeln kan saknas är det en bugg, inte något att kompensera. |

---

## 10. Rivningslista

Radnummer avser `/home/claude/matjakt/frontend/app/styles.css` som den ser ut idag (816 rader).
Flera regler står på samma rad eftersom filen delvis är minifierad — sök på selektorn.

### 10.1 Bekräftade fel

| # | Rad | Regel | Vad som är fel | Åtgärd |
|---|---|---|---|---|
| R1 | **96** | `.stats-card.highlight strong{color:var(--primary)}` | Mörkgrönt på mörkgrön gradient, kontrast ≈1:1. Regeln är idag maskerad av rad 576–578 som gör kortet ljust — men den ligger kvar och slår till i samma sekund någon river rad 576. | Ta bort regeln på rad 96. Rör den **före** rad 576, annars introducerar rivningen buggen på riktigt. |
| R2 | **451** | `.home-screen>.week-card{order:1}` / `.home-screen>.next-meal-section{order:2}` | Budgeten ligger över maten på startsidan. Riktningens hela poäng är motsatsen: klockan fem är frågan vad det blir till middag, inte hur mycket pengar som är kvar. | Kasta om: `.next-meal-section{order:1}`, `.week-card{order:2}`. Budgetkortet blir dessutom `.remsa` (5.8) i etapp 5. |
| R3 | 305 | `.week-sheet-plus{width:28px;height:28px}` | Träffyta 28×28 | 44×44, eller `.tapmin` |
| R4 | 455 | `.week-sheet-plus,.week-sheet-plus-corner{width:32px;height:32px}` | 32×32 | 44×44, eller `.tapmin` |
| R5 | 318 | `.shopping-remove{width:30px;height:30px}` | 30×30, dessutom `#a9b1aa` = 2,20:1 | 44×44 + `--ink-3` |
| R6 | 547 | `.shopping-item .shopping-remove,.extra-item .extra-remove{width:28px;height:28px}` | 28×28 | 44×44, eller `.tapmin` |
| R7 | 99 | `.week-plan-menu summary{width:28px;height:28px}` | 28×28 | 44×44 |
| R8 | 278 | `.extra-remove{width:24px;height:24px}` | 24×24 | 44×44, eller `.tapmin` |
| R9 | 276 | `.extra-qty button{width:26px;height:26px}` | 26×26 | 44×44 |
| R10 | 71 | `.recipe-star{width:30px;height:30px}` | 30×30, och `color:#d8d3c4` = 1,50:1 | 44×44 + kontur i `--ink-3` |
| R11 | 69 | `.pantry-item-controls button{width:36px;height:36px}` | 36×36 | 44×44 |
| R12 | 18 | `.account-modal-close{width:36px;height:36px}` | 36×36 | 44×44, negativ margin så den ser liten ut |
| R13 | 478 | `.hero-meal-swap{min-height:36px}` | 36px hög | 44px |

### 10.2 Fler underkända träffytor (hittade i genomgången)

| # | Rad | Selektor | Mått | Åtgärd |
|---|---|---|---|---|
| R14 | 609 | `.modal-close,.account-modal-close` | 34×34 | 44×44 |
| R15 | 696 | `.week-today-swap` | `min-height:36px` | 44px |
| R16 | 99 | `.week-plan-swap-btn` | `min-height:30px` | 44px |
| R17 | 99 | `.week-plan-menu-options button` | `min-height:38px` | 44px |
| R18 | 95 | `.week-store-switch button` | `min-height:38px` | 44px |
| R19 | 800 | `.swap-intent` | `min-height:34px` | 44px |
| R20 | 724 | `.shopping-action` | `min-height:40px` | 44px |
| R21 | 743 | `.assumed-chip` | `min-height:40px` | 44px |
| R22 | 749 | `.staple-prompt-actions .btn` | `min-height:40px` | 44px |
| R23 | 89 | `.account-link-btn` | `min-height:36px` | 44px |
| R24 | 76 | `.onboarding-skip` | `min-height:40px` | 44px |
| R25 | 76 | `.ob-tag button` | 20×20 | 44×44 via `.tapmin` |
| R26 | 3 / 432 | `.profile-btn` | 42×42, sedan 36×36 | 44×44 |
| R27 | 397 / 434 | `.feedback-btn` | 38×38, sedan 36×36 | 44×44 |
| R28 | 65 | `.favorite-btn` | 42×42 | 44×44 |
| R29 | 69 | `.pantry-item button` | 42×42 | 44×44 |
| R30 | 69 | `.segmented button` | `min-height:42px` | 44px |
| R31 | 66 | `.basket-line-actions button` | `min-height:42px` | 44px |
| R32 | 80 | `.basket-feedback-btn` | `width:42px` | 44px |
| R33 | 199 | `.chain-item input[type="checkbox"]` | 20×20 | Hela raden blir träffytan, som `.vara` |
| R34 | 240 | `.recipe-tag` | `padding:.4rem .8rem`, ingen `min-height` (≈30px) | `min-height:44px` |
| R35 | 281 | `.campaign-deal-add` | `padding:6px 12px` (≈28px) | `min-height:44px` |
| R36 | 19 | `.pantry-pick-add` | `padding:7px 12px` (≈29px) | `min-height:44px` |
| R37 | 66 | `.store-compare-row` | `padding:6px 4px`, 13px text (≈31px) | `min-height:44px` |
| R38 | 88 / 296 / 306 / 392 / 769 | `.store-compare-updated`, `.paywall-continue`, `.week-secondary`, `.report-price-btn`, `.household-remove` | Textknappar utan höjd (24–38px) | `.btn-text` med `min-height:44px` |

### 10.3 Fokus, färg och form

| # | Rad | Regel | Vad som är fel | Åtgärd |
|---|---|---|---|---|
| R39 | **15, 64** | `:focus{outline:0}` (i `.budget-row input:focus` och `.recipe-search input:focus`) | Filen har `:focus{outline:0}` men **ingen `:focus-visible`-regel någonstans** — kontrollerat: noll träffar i hela filen. Tangentbordsanvändare ser inget alls på knappar och länkar. | Ta bort båda. Lägg in `:focus-visible`-regeln från kap. 5. |
| R40 | 513 | `input:focus,select:focus,textarea:focus{outline:0;box-shadow:0 0 0 3px var(--primary-soft)}` | Fokusringen är en 3px soft-grön glow som efter aliasbytet blir `--paper-2` mot `--paper` — 1,2:1, alltså osynlig. | Ersätt med `outline:2px solid var(--accent);outline-offset:2px`. |
| R41 | **183–187** | `.price-status.current::before{content:"🟢"}` / `.estimated::before{content:"🟡"}` / `.missing::before{content:"⚪"}` + `color:#a16207` / `#b91c1c` | Trafikljus i emoji. Emojin renderas olika per plattform, läses upp som "grön cirkel" av skärmläsare, och färgerna bryter mot accentregeln. Rött för saknat pris är dessutom direkt förbjudet (kap. 6). | Riv hela blocket. Ersätt med `.pris`, `.pris--ca`, `.saknas` från kap. 6. |
| R42 | 198 | `.chain-item.is-missing{background:#fdf1ef}` | Rosa "felrad" för en vara utan pris. Det är inget fel. | Ta bort. Raden ser ut som alla andra; priset bär `.saknas`. |
| R43 | 207 | `.chain-item-campaign{color:#b91c1c}` | Rött för en **kampanj**, alltså goda nyheter i felfärg. | `--ink`. Kampanjen framgår av texten. |
| R44 | 194 | `.chain-list-savings{color:#15803d}` | Grönt för besparing. Bryter accentregeln (färg som betygsättning). | `--ink`. |
| R45 | 67, 546, 730 | `.shopping-item.checked{opacity:.6}` / `.55` / `.62` | `--muted` vid 55 % opacitet blir 2,13:1 mot vitt. Uträknat: `.55`→2,13 · `.62`→2,39 · `.75`→2,96. Alla underkända. | Ta bort `opacity`. Avbockat kodas med `--ink-3` + `line-through` + ifylld ruta (5.5). |
| R46 | 88, 214, 215, 268, 293, 297, 733 | `opacity:.6` / `.65` / `.68` / `.7` / `.75` / `.85` / `.92` på textbärande element | Samma problem: okontrollerad kontraktsförlust. | Ersätt med explicit `--ink-2` eller `--ink-3`. |
| R47 | **814** | `.week-summary li::before{content:"—";color:var(--border)}` | Ett tankstreck i ramfärg: `#e6e9e6` på vitt = 1,22:1. Punktlistans markörer är osynliga. | `color:var(--ink-3)`. |
| R48 | 66 | `.week-summary .over-budget strong{color:#ff9b8f}` | Över budget signaleras med korallrött, som dessutom är ljust på ljust. | Överskridandet skrivs i ord (5.8). |
| R49 | 6, 66, 69, 96, 347 | `background-image:linear-gradient(...)` på `.week-overview>strong`, `.week-summary`, `.store-compare`, `.pantry-hero`, `.stats-card.highlight`, `.hero-meal-invite` | Gröna gradientpaneler och gradient-clippad text. Systemet har inga gradienter och inga färgade paneler. | Riv gradienterna. Panelerna blir `--paper` med linjer, siffran blir `--ink`. |
| R50 | 3, 70, 429, 596, 645 | `backdrop-filter:blur(...) saturate(...)` på topplist, bottennav, favoritknapp | Genomskinlig blur mot papper ger oförutsägbar kontrast och kostar prestanda på äldre telefoner. | Ta bort. Ogenomskinlig `--paper` + 1px linje. |
| R51 | 3, 15, 17, 65, 66, 71, 78, 318, 495, 501, 596, 601, 606, 689, 696, 706 | Alla `box-shadow` utom bottenark och modal | Systemet har en skugga. | `box-shadow:none`. Behåll bara `--shadow-sheet` på `.ark` och `.modal-panel`. |
| R52 | 3, 15, 17, 65, 67, 70, 71, 78, 99, 319, 496 | Alla `:active{transform:scale(...)}` | Fjädrande tryckrespons hör inte hemma i en tidningssättning, och `scale` på en rad med text ger flimrande textrendering. | Ersätt med `background:var(--paper-2)` under 90ms. |
| R53 | Hela filen | `border-radius` i 90+ regler (`99px`, `999px`, `50%`, `--r-*`, `12–30px`) | Radie används inte. Pillerformade chips är uttryckligen bortvalda. | Aliasskiktet nollar `--r-*` direkt; de hårdkodade (`99px`, `999px`, `50%`, `24px`…) måste bytas för hand, se etapp 3. |
| R54 | 2, 424 | `html{scroll-behavior:smooth}` | Mjukskroll är kvar även med `prefers-reduced-motion` i rad 138-blocket eftersom `scroll-behavior` sätts på `html` och `*`-regeln träffar det — kontrollera efter bytet. | Behåll `scroll-behavior:auto!important` i reduced-motion-blocket och verifiera i devtools. |
| R55 | 65 | `.recipe-fallback.kind-fisk/-kyckling/-kott/-vego/-soppa/-gryta` — sex färgade gradienter | Kategorifärg. Bryter accentregeln. | En platta i `--shot` med rättens namn i Newsreader. |
| R56 | 16, 84, 91, 92, 195, 464 | `.premium-badge`, `.premium-price-tab.active`, `.verify-email-notice`, `.nutrition-warning`, `.chain-list-warning` — guld | Guldfärgen är 4,02:1, alltså underkänd, och en andra accent. | `--paper-2`-fält, ordet "Premium" i kapitäler. |
| R57 | 71, 79, 80, 93, 18 | `.recipe-star.filled`, `.feedback-btn.dislike.active`, `.basket-feedback-btn[data-skipped].marked`, `.account-delete-btn`, `.account-logout-btn` — `--danger`/`--gold` | Röda och guldiga tillstånd. | `--ink` + tydlig text. |
| R58 | 421–423 | Kommentaren `MATJAKT DESIGN V2 — "Ren och tyst" … Ligger sist i filen och vinner kaskaden` | Filen innehåller **två** designsystem ovanpå varandra; hälften av reglerna i rad 1–418 är döda men går inte att se vilka. | Efter etapp 6: kör en täckningsanalys (devtools Coverage) på alla sex vyer och radera det som aldrig matchar. Det är den enda säkra metoden här. |

---

## 11. Införandeordning

Sju etapper. Varje etapp går att släppa för sig och lämnar appen i ett fungerande läge.

### Etapp 0 — Aliasskiktet och typsnitten *(1 commit, hela appen byter utseende)*

1. Lägg in blocket från 9.1 **först** i `styles.css`.
2. Byt `<link>` i `index.html` rad 38 till Newsreader + Archivo.
3. Byt `?v=42` på rad 39 så cachen släpper.

Efter detta är appen grå-vit med oxblod, utan radier och utan skuggor, men med all gammal
struktur kvar (kort, chips, gradienter är nu färglösa rutor). Det ser halvfärdigt ut —
det är meningen. **Släpp inte till användare efter etapp 0 ensam;** slå ihop den med
etapp 1 och 2 i samma release.

*Måste vara klart innan något annat påbörjas.* Allt nedan förutsätter att tokens finns.

### Etapp 1 — Tillgänglighet *(parallellt med etapp 2)*

- Ta bort `:focus{outline:0}` (R39) och lägg in `:focus-visible`-regeln. **Gör det först i
  etappen** — resten av arbetet blir granskningsbart när fokus syns.
- Alla träffytor i 10.1 och 10.2 (R3–R38).
- Ta bort alla `opacity` på textbärande element (R45, R46).
- Fokusfälla + Escape i `app.js` för bottenark, modal och inbjudningsvyn (5.16).
  Filen har idag två `Escape`-lyssnare totalt; alla lager behöver en.

Rör bara knappmått, fokus och opacitet. Inga färger, inga linjer. Därför kolliderar den
aldrig med etapp 2 eller 3.

### Etapp 2 — Prisreglerna *(parallellt med etapp 1)*

- Lägg in `.pris`, `.pris--ca`, `.saknas` från kap. 6.
- Riv `.price-status`-blocket, rad 180–187 (R41).
- Riv `.chain-item.is-missing`, rad 198 (R42), `.chain-item-campaign`-rött rad 207 (R43),
  `.chain-list-savings`-grönt rad 194 (R44).
- Riv `.price-missing{font-style:italic}` rad 67 — kursiv är kickerns röst, inte prisets.
- Uppdatera prisrenderingen i `app.js` så den skriver ut de tre formerna.
- Kör gråskaletestet från kap. 6.

Rör bara priselement. Ingen krock med etapp 1.

### Etapp 3 — Kort blir linjer *(kräver etapp 0; blockerar 4, 5, 6)*

Det här är den stora etappen och den som inte går att dela upp mellan två utvecklare, för
den ändrar samma selektorer på flera ställen i filen.

1. **Ta bort R1 (rad 96) innan du rör rad 576.** Rad 576–578 maskerar idag den 1:1-kontrast
   som rad 96 skapar. Rör man 576 först blir buggen synlig i produktion.
2. Riv gradientpanelerna (R49) och kategorigradienterna (R55).
3. Riv alla `box-shadow` utom ark och modal (R51).
4. Riv alla `border-radius` som inte går via `--r-*` (R53).
5. Riv alla `transform:scale` (R52) och alla `backdrop-filter` (R50).
6. Ersätt kortselektorn på rad 532 (den som ger 30 komponenter ram + radie + yta) med
   linjebaserade varianter: `.vara` (5.5), `.dag` (5.4), `.avdelning` (5.6).
7. Byt hårdkodade hex enligt 9.3.

**Släppbart läge efter etapp 3:** appen är hel, i rätt palett, med linjer i stället för kort.
Typografin är fortfarande fel storlek på sina ställen — det tas i etapp 4.

### Etapp 4 — Typografi *(efter 3)*

- Skalan i 3.2 på rubriker, etiketter, priser och bildtexter.
- `font-variant-numeric` enligt 3.3, inklusive återdeklarationerna.
- Talformat enligt 3.4 i `app.js` (decimalkomma, U+202F, hårt mellanslag före `kr`).
- Kapitälettiketterna: **ändra HTML:en till gemener** och versalisera i CSS, annars stavar
  skärmläsaren dem.

Måste vänta på etapp 3 eftersom rubrikstorlekar sätts i samma regler som kortpaddingen.

### Etapp 5 — Skärmarnas struktur *(efter 3; 5a och 5b kan gå parallellt)*

**5a Hem/Ikväll**
- R2: kasta om ordningen, `.next-meal-section{order:1}`, `.week-card{order:2}` (rad 451).
- Bygg hjälten (5.2) och budgetremsan (5.8) — budgetkortet upphör att vara ett kort.
- `.hero-meal-*` (rad 336–349, 466–481) rivs och ersätts.

**5b Vecka/Handla/Sparat**
- Dagraden (5.4), varuraden (5.5), avdelningsrubriken (5.6), summeringsblocket (5.7),
  statistikraden (5.9), tomma tillstånd (5.10), laddningsskelett (5.11).

De två spåren rör olika selektorer och olika vyer och kan tas av två personer samtidigt.

### Etapp 6 — Ramverk kring innehållet *(efter 5)*

- Bottennavigering (5.14) — ersätter rad 70, 596–602, 645–646.
- Bottenark (5.13) och modal (5.15) — ersätter rad 18, 285–309, 604–612.
- Toast (5.12) — ersätter rad 323–327, 601.
- Rörelsereglerna i kap. 7, inklusive `prefers-reduced-motion` (R54).
- Texten i gränssnittet enligt kap. 8: felmeddelanden och knapptexter i `app.js`.

Måste vänta på etapp 5: bottennavigeringens höjd bestämmer scrollytans bottenmarginal, och
toastens position bestämms av navigeringen.

### Etapp 7 — Riv aliasskiktet *(sist, ingen får ligga före)*

1. Sök–ersätt de gamla variabelnamnen mot de nya i hela filen (`--primary` → `--accent`
   och så vidare, enligt 9.2). Gör det **ett namn i taget** med en granskning per namn —
   `--primary` betyder inte alltid `--accent`, se accentregeln.
2. Ta bort aliasblocket.
3. Byt tillbaka `--shadow-color` → `--shadow` (namnkrocken i 9.1).
4. Kör Coverage-analysen i R58 på alla sex vyer och radera död CSS.
5. Kontrollmätning: gråskaletestet (kap. 6), tangentbordsgenomgång av alla lager
   (etapp 1), och kontrasttabellen i 2.2 stickprovad mot verkliga skärmdumpar.

**Får inte påbörjas** förrän 1–6 är i produktion. Så länge aliasskiktet finns kvar går varje
etapp att rulla tillbaka för sig; efteråt gör den inte det.

### Sammanfattning av beroenden

```
Etapp 0  ──┬── Etapp 1 (tillgänglighet)   ──┐
           ├── Etapp 2 (prisregler)        ──┤
           └── Etapp 3 (kort → linjer)  ─────┼── Etapp 6 ── Etapp 7
                        │                     │
                        ├── Etapp 4 (typografi)
                        └── Etapp 5a / 5b (skärmar) ──┘
```

Parallellt: 1 ‖ 2 ‖ 3 · 4 ‖ 5a ‖ 5b.
Sekventiellt: 0 → allt · 3 → 4, 5 · 5 → 6 · 6 → 7.
