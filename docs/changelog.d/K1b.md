---
paket: K1b
titel: Linten var röd på main
---

K1 slog på ruff och eslint, och grinden gick grönt på sitt eget paket. Nästa
merge — I5, skärmbildsgeneratorn — bröt den på `B006`, muterbar
standardparameter:

```python
def konto(sida, _räknare=[0]):
```

Det är den medvetna "statisk räknare"-idiomen och inte ett slarvfel, men ruff
har rätt i att den är en fälla: listan delas mellan alla anrop, och den som
råkar kalla `konto(sida, [0])` nollställer den tyst för alla. `itertools.count`
gör samma sak utan den egenskapen.

Att felet nådde main säger något om ordningen: `Lint (ruff + eslint)` står
medvetet **inte** i rulesetets obligatoriska checkar, eftersom fem agenter
hade öppna grenar när K1 landade och en ny grind hade gjort dem alla röda av
skäl som inte rörde deras paket. Priset är att den kan bli röd på main utan
att blockera något. Kommandot som gör den obligatorisk står i K1:s PR och bör
köras när grenarna är inne.
