---
paket: N0b
titel: Typsnitten ligger i appen, inte hos Google
---

`frontend/app/index.html` hade tre rader som hämtade Newsreader och Archivo
från Googles fontvärdar: två `preconnect` och en `<link>`. De kostade två
saker som båda står i vägen för iOS-bygget.

Första starten utan nät visade fel typsnitt. En native-app som hämtar sina
bokstäver över nätet sätter hela gränssnittet i fallbackstacken på flygplanet,
i tunnelbanan och de första sekunderna på en dålig uppkoppling — och
skillnaden mellan Newsreader och Georgia i en 82 px-rubrik är inte subtil.

Och CSP:n måste släppa in två tredjepartsvärdar enbart för att hämta text:
en i `style-src`, en i `font-src`. Appens policy är i övrigt kompromisslös —
`script-src` har varken `'unsafe-inline'` eller CDN, just för att
sessionstoken är en bearer-credential i localStorage. Två fontvärdar var det
enda kvarvarande undantaget.

Nu ligger typsnitten i `frontend/app/assets/fonts/` och deklareras med tre
`@font-face` överst i `styles.css`. Länken är borta, `preconnect` är borta,
och appens CSP är `style-src 'self' 'unsafe-inline'; font-src 'self'`.

## Vad som buntades, och varför precis det

| Fil | Familj | Omfång | kB |
|---|---|---|---|
| `newsreader-variable-latin.woff2` | Newsreader | variabel, `opsz 6–72`, `wght 400–700`, rak | 87,6 |
| `archivo-variable-latin.woff2` | Archivo | variabel, `wght 400–700`, rak | 31,5 |
| `archivo-italic-latin.woff2` | Archivo | statisk 400, kursiv | 14,3 |

**133,4 kB totalt.** Vikterna är hämtade ur `styles.css`, inte ur
designsystemets tabell: filen sätter Newsreader i 400 och 700, Archivo i
400/500/600/700, och kursiv Archivo på `<em>` i ingredienslistan och på
tidsstämpeln i butiksjämförelsen. `wdth` är bortlåst — appen ändrar aldrig
bredd — och `wght` kapat från 100–900 till 400–700.

Variabel slår statiska snitt i båda familjerna, mätt på samma delmängd:

| | variabel | statiska snitt |
|---|---|---|
| Archivo (400/500/600/700) | **31,5 kB** | 51,7 kB (fyra filer) |
| Newsreader (400/700) | **87,6 kB** | 110,3 kB (två filer) |

`opsz` är kvar i Newsreader trots att axeln kostar 51 kB (87,6 mot 36,2 kB
spikad på 18). §3.2 sätter samma familj från 13 px till 82 px, och stortalet
på Sparat-skärmen — appens enda hjälterubrik — är synligt grövre och bredare
när axeln spikas. Det är den siffran hela skärmen är byggd runt.

Delmängden är Google Fonts **latin**-omfång. `latin-ext` är medvetet inte med:
hela repot innehåller fem tecken ur det omfånget, och de två filerna hade
vuxit med 58 kB för att täcka dem. De sätts ur fallbackstacken i stället, som
allt annat utanför latin. `tnum` är med i alla tre — §3.3 sätter
`font-variant-numeric:tabular-nums` globalt, och utan den featuren i fonten är
hela regeln verkningslös och priskolumnen slutar stå i kolumn.

## Licens och proveniens

Båda familjerna är SIL Open Font License 1.1, som tillåter buntning och kräver
att licenstexten följer med. `OFL-Archivo.txt` och `OFL-Newsreader.txt` ligger
bredvid typsnitten. Ingen av familjerna har ett Reserved Font Name — deras
copyrightrader saknar reservatet, i både `OFL.txt` och fontens `name`-tabell —
och familjenamnen är ändå orörda; filnamnen beskriver delmängden.

Filerna är hämtade ur `github.com/google/fonts` på angivna commits (Archivo
2.001, Newsreader 1.003) och delmängdade med fontTools. Källa, commit, version,
SHA-256 på originalen och den exakta kommandoraden står i
`frontend/app/assets/fonts/README.md`, så vem som helst kan bygga om precis de
här filerna.

## Grinden

`tests/typsnitt.test.js`, åtta tester:

- **Ingen av Googles två fontvärdar får förekomma** i `frontend/app/index.html`
  eller i `styles.css` — ren textsökning över hela filen, inte en sökning efter
  `<link>`-taggar. En URL i en kommentar eller i en `@import` är lika fel.
  Därför nämns värdarna inte vid namn någonstans under `frontend/app/`:
  undantag är hur en grind blir verkningslös.
- `style-src` och `font-src` i CSP-metataggen får inte peka ut **någon** extern
  värd. Nästa font-CDN är lika fel som det förra.
- Varje `@font-face` pekar på en fil som finns, som börjar med `wOF2`, och som
  har `font-display:swap`.
- Varje vikt och stil `styles.css` använder täcks av ett deklarerat snitt.
- Fallbackstacken innehåller Georgia respektive Helvetica — utan den är sidan
  satt i webbläsarens standardsnitt medan typsnittet laddar.
- Licensfilen finns, är en hel OFL-text, och nämner båda familjerna.
- Typsnitten är spårade i git (ett `.gitignore`-mönster som råkar svälja
  katalogen ger gröna tester lokalt och ett bygge utan typsnitt i CI).
- `build_frontend.mjs --native` tar med filerna, och minifieringen skriver inte
  om `url()`:erna.

Prövat åt båda hållen: med en återinförd `<link>` failar tre av dem, med en
borttagen fontfil eller borttagen licensfil failar tre.

## Vad som inte ändrades

`backend/api_server.py` skickar fortfarande fontvärdarna i sin CSP-header.
Landningssidan och de juridiska sidorna under `frontend/` hämtar ännu sina
typsnitt från Google, och headern är gemensam för hela servern. Appen påverkas
inte: metataggen är den snävare av de två, och webbläsaren tillämpar snittet.
Att bunta typsnitten även för sajten är ett eget paket i `Z-SITE`.
