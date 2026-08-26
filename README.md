# Veckokassen

En app där du anger hur mycket pengar du har att handla mat för denna
vecka och antal personer i hushållet, och får receptförslag +
inköpslista baserat på de billigaste priserna hos butiker i din närhet.

## Projektstruktur

```
veckokassen/
├── backend/
│   ├── common.py           # Delade dataklasser (Prisrad) + CSV/JSON-hjälpare
│   ├── ica_scraper.py       # Playwright-scraper för handla.ica.se
│   ├── willys_scraper.py    # Playwright-scraper för willys.se
│   ├── coop_scraper.py      # Playwright-scraper för coop.se
│   ├── requirements.txt
│   └── sample_data/
│       └── produkter.json   # Vilka produkter som ska prisjämföras
└── frontend/
    ├── index.html            # Prototyp av appens UI
    ├── styles.css
    └── app.js                # Mockdata just nu, redo att kopplas mot riktig data
```

## Kom igång (backend/scraping)

```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python ica_scraper.py
```

### Starta Matjakt API

```bash
cd backend
python api_server.py
```

API:t kör därefter på `http://127.0.0.1:8000`. Om frontend ligger på en annan
adress vid hosting kan CORS-adressen ställas med miljövariabeln
`MATJAKT_FRONTEND_ORIGIN`.

**Viktigt:** CSS-selektorerna i scraperfilerna (t.ex. `[data-testid=product-price]`)
är gissningar. Öppna respektive butiks webbplats i Chrome, tryck F12,
högerklicka på "Välj butik"-knappen och på priset → Inspect, och
uppdatera selektorerna i koden. Se kommentarerna i varje fil.

## Kom igång (frontend)

Öppna bara `frontend/index.html` i webbläsaren — inget byggsteg krävs.
Just nu använder den mockdata (`MOCK_RECEPT` i app.js) istället för
riktig prisdata, så du kan jobba på UI:t oberoende av scraperna.

## Varför Playwright och inte `requests`?

Ingen av ICA, Willys eller Coop visar priser i den statiska HTML:en —
priset laddas via JavaScript efter att en butik är vald. Playwright
kör en riktig (headless) webbläsare som kan simulera det flödet.
Ett snabbare men mer avancerat alternativ: hitta butikens interna
JSON-API via webbläsarens nätverksflik (F12 → Network → Fetch/XHR)
och anropa det direkt med `requests`. Se kommentaren längst ner i
`ica_scraper.py` för hur man letar reda på det.

## Roadmap / att fylla på

- [ ] Hitta och verifiera rätt CSS-selektorer per butik (eller byta till
      internt API-anrop, se ovan)
- [ ] Lägg till fler produkter i `sample_data/produkter.json`
- [ ] Bygg en receptdatabas (ingredienser + mängd + kostnad per portion)
- [ ] Matcha recept mot budget + antal personer (enkel algoritm:
      sortera recept efter kostnad/portion, plocka så många som ryms
      i budgeten, med viktning så inte samma recept upprepas varje vecka)
- [ ] Koppla frontend mot riktig data istället för mockdata i app.js
- [ ] Geolokalisering: hitta närmaste butik per kedja (t.ex. Google Places API)
- [ ] Juridik: se över butikernas användarvillkor innan skalning,
      och överväg att kontakta butiker/befintliga prisjämförelsetjänster
      (t.ex. matmoms.se, matpriser.nu) om datalicensiering istället för
      egen skrapning i stor skala
- [ ] I ett senare skede: partnerskap med kedjor för annonsering/rabatter
