# Typsnitten i Matjakt — varifrån de kommer

Tre woff2-filer, buntade i appen (N0b). De är **källa**, inte byggutdata: de
byggs inte om av `npm run build`, de spåras i git och de kopieras rakt av in i
`dist/` som vilken bild som helst.

Ett typsnitt utan proveniens i ett publikt repo går inte att granska. Därför
står allt som behövs för att göra om exakt de här filerna här nedanför.

## Källa

| | Archivo | Newsreader |
|---|---|---|
| Utgivare | Omnibus-Type | Production Type |
| Licens | SIL Open Font License 1.1 | SIL Open Font License 1.1 |
| Licensfil | `OFL-Archivo.txt` | `OFL-Newsreader.txt` |
| Licenstext | <https://scripts.sil.org/OFL> | <https://scripts.sil.org/OFL> |
| Version (name ID 5) | 2.001 | 1.003 |
| Hämtad från | `github.com/google/fonts`, `ofl/archivo/` | `github.com/google/fonts`, `ofl/newsreader/` |
| Commit | `95f4904fc8bcf26d3420fe315560c96417c6dec7` | `8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5` |
| Uppström | <https://github.com/Omnibus-Type/Archivo> | <https://github.com/productiontype/Newsreader> |

SHA-256 på de nedladdade variabel-TTF:erna, före delmängd:

```
0e094a7d3c7c4c25cf1310c4b30014f1dae9332220b1c2c88f4fa996f0b05053  Archivo[wdth,wght].ttf
305d13b4eb80e62f7d517f78d7c045250d977552a420f2dbed906f314e761305  Archivo-Italic[wdth,wght].ttf
8a08d13f8a6c0d51be379a60af84f945f65369a67e509ee3c3bdcc421254d7c1  Newsreader[opsz,wght].ttf
```

## Reserved Font Name

**Ingen av familjerna har ett.** OFL §1 låter upphovspersonen reservera
teckensnittsnamnet med formuleringen "with Reserved Font Name" i
copyrightraden; då måste en modifierad version byta namn. Copyrightraden är i
båda fallen `Copyright 2020 The <Familj> Project Authors (…)` — utan reservat,
i både `OFL.txt` och fontens `name`-tabell (name ID 0).

Filerna nedan är ändå delmängder av originalen, så familjenamnet i
`name`-tabellen är orört: `Archivo` respektive `Newsreader`, precis som
`font-family` i `styles.css` slår upp dem. Filnamnen beskriver delmängden
(`-variable-latin`, `-italic-latin`) och får inte skrivas om till något som
läser som ett eget familjenamn — `Archivo Matjakt`, `Newsreader Light` och
liknande vore fel namn på en font som inte är en egen familj.

## Delmängden

`fontTools 4.60.2`. Först `varLib.instancer` (låser bort axlar och kapar
viktomfånget), sedan `subset` (tecken, features, woff2):

```sh
python -m fontTools.varLib.instancer 'Archivo[wdth,wght].ttf' \
    wdth=100 wght=400:400:700 -o archivo-var.ttf
python -m fontTools.varLib.instancer 'Archivo-Italic[wdth,wght].ttf' \
    wdth=100 wght=400 -o archivo-italic.ttf
python -m fontTools.varLib.instancer 'Newsreader[opsz,wght].ttf' \
    wght=400:400:700 -o newsreader-var.ttf

# samma tre flaggor för var och en:
python -m fontTools.subset <in>.ttf --output-file=<ut>.woff2 --flavor=woff2 \
    --layout-features+=tnum,rvrn --name-IDs+=13,14,16,17 \
    --unicodes=U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD
```

- `--unicodes` är Google Fonts **latin**-omfång, ordagrant. `latin-ext` är
  medvetet inte med: hela repot innehåller fem tecken ur det omfånget, och de
  två filerna hade vuxit med 58 kB för att täcka dem. De sätts ur
  fallbackstacken (Georgia / Helvetica) i stället, som allt annat utanför
  latin — kyrilliska, arabiska, emoji.
- `tnum` **måste** med. Designsystemet §3.3 sätter
  `font-variant-numeric:tabular-nums` globalt och deklarerar om det på varje
  belopp; utan `tnum` i fonten är hela regeln verkningslös och priskolumnen
  slutar stå i kolumn. `rvrn` är variabelfontens obligatoriska feature.
- `--name-IDs+=13,14` behåller licensnotisen och licens-URL:en inuti filen,
  utöver `OFL-*.txt` bredvid.

## Vad som faktiskt ligger i filerna

| Fil | Familj | Axlar | Stil | kB |
|---|---|---|---|---|
| `newsreader-variable-latin.woff2` | Newsreader | `opsz 6–72`, `wght 400–700` | rak | 87,6 |
| `archivo-variable-latin.woff2` | Archivo | `wght 400–700` | rak | 31,5 |
| `archivo-italic-latin.woff2` | Archivo | — (statisk 400) | kursiv | 14,3 |

Vikterna är de som `styles.css` verkligen använder: Newsreader 400 och 700,
Archivo 400/500/600/700 rak samt 400 kursiv. `wdth` är bortlåst på 100 —
appen ändrar aldrig bredd. `opsz` är kvar i Newsreader därför att §3.2 sätter
samma familj från 13 px till 82 px.
