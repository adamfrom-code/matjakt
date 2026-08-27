# Matjakt

Matjakt är en mobile-first prototyp för veckoplanering, budgetoptimering och prisjämförelse. Produktlöftet är: **Säg din budget. Matjakt löser resten.**

Fas 1 stabiliserar prototypen. Prisuppgifterna är ännu en blandning av lokal katalogdata och best-effort-sökning på butikernas publika webbplatser, inte en färdig prisdatabas.

## Krav och installation

- Node.js 20+
- Python 3.10+
- Playwright/Chromium för liveproduktsökning

```bash
npm install
python -m venv backend/venv
# Aktivera den virtuella miljön, därefter:
pip install -r backend/requirements.txt
playwright install chromium
```

## Starta frontend och backend

```bash
npm run frontend
npm run backend
```

Backendservern exponerar både appen och API:t på `http://127.0.0.1:8000`, vilket ger fungerande same-origin-anrop. `npm run frontend` kan fortfarande användas på `http://localhost:5500` för ren statisk UI-utveckling. ES-moduler kräver webbserver, så öppna inte HTML-filen via `file://`.

Frontend använder `/api` som same-origin-standard. Om API:t finns på annan origin sätter deploymenten basadressen med `<meta name="matjakt-api-url" content="https://api.example.se/api">` i `frontend/index.html`. Lägg aldrig hemligheter där. För separat lokal drift kan metan tillfälligt peka på `http://127.0.0.1:8000/api`.

API-endpoints inkluderar:

- `GET /api/health`
- `GET /api/products?butik=ICA&q=pasta&zip=80313`
- `GET /api/v1/recipes/search?q=chicken`
- `GET /api/v1/recipes/themealdb:52772`

Recept-API:t använder ett providerlager under `backend/services/recipe_providers/`. Frontend får alltid normaliserad titel, bild, ingredienser och instruktioner från samma providerresultat och känner inte till leverantörens externa API.

## Miljövariabler

Se `.env.example`. Pythonservern läser processmiljön direkt; en `.env` behöver laddas av skalet/processverktyget.

| Variabel | Standard | Beskrivning |
| --- | --- | --- |
| `MATJAKT_HOST` | `127.0.0.1` | Backendens bind-adress |
| `MATJAKT_PORT` | `8000` | Backendens port |
| `MATJAKT_FRONTEND_ORIGIN` | `http://localhost:5500` | Tillåten CORS-origin |
| `MATJAKT_API_URL` | `/api` i frontend | Dokumenterat runtime-värde för meta-taggen |

Inga API-nycklar krävs och `.env` ignoreras av Git.

## Tester och kontroller

```bash
npm test
npm run check
npm --prefix mobile exec tsc -- --noEmit
```

Testerna täcker portionsskalning, ingredienssummering, budget, shoppingtotal, persistent state, receptsökning samt backendens prisparsning.

## Arkitektur

```text
frontend/
  index.html, styles.css, app.js  UI och applikationsorkestrering
  src/api/                       runtime-konfiguration och API-URL:er
  src/services/                  ren beräknings- och söklogik
  src/state/                     tolerant localStorage-persistens
  src/utils/                     säker HTML- och URL-hantering
backend/
  api_server.py                  HTTP-API och kortlivad cache
  *_scraper.py, common.py        fristående Playwright-scrapers
mobile/                          tidigt Expo-skal
android/                         Capacitor Android-projekt
tests/                           frontendens enhetstester
```

`frontend/app.js` är fortfarande UI-kompositören, men domänlogik flyttas stegvis till `src/`. En full React/React Native-migrering ingår inte i Fas 1.

## Kända begränsningar

- Butikernas DOM och villkor kan ändras; selektorer och rätt till storskalig datainsamling måste verifieras före produktion.
- Produktmatchning och priser är inte ännu auktoritativa.
- API-cachen ligger i minnet och delas inte mellan processer.
- Expo-katalogen är ett separat tidigt skal; Capacitor-webbfrontenden är prototypen som används.
