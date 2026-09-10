# Changelog-fragment — en fil per paket

`CHECKPOINT.md` är 283 rader välskriven berättelse. Utmärkt för en människa,
en garanterad konflikt när tjugo agenter redigerar den samtidigt: alla skriver
i samma stycke, i samma fil, på samma rad.

Så här gör vi i stället. **Varje paket lägger EN ny fil här** och rör aldrig
någon annans:

    docs/changelog.d/<paket-ID>.md      t.ex. C2.md, B7.md, G4.md

Två agenter som skapar var sin ny fil i samma katalog kan aldrig kollidera —
git slår ihop dem utan att fråga. Det är hela poängen.

## Formatet

```markdown
---
paket: C2
titel: Multipack lästes som enkelförpackning
pr: 61
---

"Krossade Tomater 390 g 4-pack" tolkades som 390 g. En vecka som behövde
1 500 g fick fyra förpackningar à 390 g — sexton burkar i stället för fyra.

Raden var dessutom märkt `exactPackaging=True` och gick alltså in i den
"säkra" totalen och i Billigast-underlaget.
```

`paket` och `titel` krävs. `pr` är valfritt men bör finnas.

Skriv brödtext, inte punktlistor med commit-rubriker. Den som läser det här
om ett halvår vill veta **vad som var fel och vad som gäller nu** — inte
vilka filer som rördes. Det står i diffen.

## Vid release

    node scripts/weave_checkpoint.mjs                    # visa vad som skulle vävas
    node scripts/weave_checkpoint.mjs --apply "v1.0"     # väv in i CHECKPOINT.md

Fragmenten flyttas då till `docs/changelog.d/arkiv/<release>/` — de raderas
aldrig, för då försvinner den enda ordagranna beskrivningen av varje paket.
