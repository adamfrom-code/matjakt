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
- `GET /api/products?butik=ICA&q=pasta&zip=80252`
- `POST /api/products/batch` — `{ butik, zip, varor: ["Pasta", "Lök", ...] }`, används av veckans inköpslista för att hämta riktiga aktuella priser från vald butik istället för den statiska uppskattningen. Max 20 varor per anrop, delar samma cache/TTL som `/api/products`.
- `GET /api/v1/recipes/search?q=chicken`
- `GET /api/v1/recipes/themealdb:52772`
- `GET /api/v1/recipes/by-pantry?items=Kycklingfilé,Lök` — matchar skafferi mot både de lokala recepten och TheMealDB (via `backend/services/recipe_providers/ingredient_map.py`), rankat på flest matchande ingredienser. Cachas 30 min per ingrediensuppsättning.
- `GET /api/campaigns?butik=Coop&zip=80252` — Premium-funktion: skannar en liten uppsättning vanliga ingredienser efter kampanjpriser hos Coop/Hemköp (enda butikerna med tydlig kampanjmärkning i sökresultaten). Cachas 1 timme.
- `GET /api/geocode?zip=41118` — postnummer → ort/lat/lon via zippopotam.us, används för riktig avståndsberäkning till butiksprofilerna.
- `GET /api/stores?zip=80252` — riktiga butiker (namn, koordinater, avstånd) nära postnumret för alla fyra kedjor: Willys/Hemköp via Axfoods öppna butiks-REST-API, ICA via samma butiksuppslag som `/api/products`, Coop via en Playwright-driven sökning (deras API kräver en riktig browsersession). Cachas 24h (ICA 1h). Ersätter den tidigare hårdkodade Gävle/Stockholm/Göteborg-listan.
- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/redeem` — konton och Premium-inlösen, se `backend/services/accounts/`.

Recept-API:t använder ett providerlager under `backend/services/recipe_providers/`. Frontend får alltid normaliserad titel, bild, ingredienser och instruktioner från samma providerresultat och känner inte till leverantörens externa API.

## Miljövariabler

Se `.env.example`. Kopiera den till `.env` och fyll i värden — `backend/api_server.py` läser filen automatiskt vid start (utan att skriva över variabler som redan är satta i skalet).

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
```

Testerna täcker portionsskalning, ingredienssummering, budget, shoppingtotal, persistent state, receptsökning samt backendens prisparsning.

## Arkitektur

```text
frontend/
  index.html, styles.css, app.js  UI och applikationsorkestrering
  manifest.json, sw.js           PWA: installerbar på hemskärmen, offline-cachad app-skal
  src/api/                       runtime-konfiguration och API-URL:er
  src/services/                  ren beräknings- och söklogik
  src/state/                     tolerant localStorage-persistens
  src/utils/                     säker HTML- och URL-hantering
backend/
  api_server.py                  HTTP-API, Playwright-scraping och tidsbegränsad cache
android/                         Capacitor Android-projekt (webDir: frontend)
tests/                           frontendens enhetstester
```

`frontend/app.js` är fortfarande UI-kompositören, men domänlogik flyttas stegvis till `src/`. En full React/React Native-migrering ingår inte i Fas 1.

## Landningssida, domän och statistik

`frontend/site/` är en fristående marknadssida (ingen appkod, ingen inloggning) publicerad på `/site/` bredvid appen - appens egen plats/routing är oförändrad. `frontend/CNAME` (innehåller `matjakt.store`) kopplar GitHub Pages till den domänen; filen läses automatiskt av `actions/deploy-pages` vid varje deploy, ingen manuell inställning i GitHub-gränssnittet behövs. Appens ursprungliga `github.io`-adress fortsätter fungera parallellt.

**Anonym statistik** (landningssidan, `frontend/site/index.html`):
- **Sidvisningar** via [Cloudflare Web Analytics](https://www.cloudflare.com/web-analytics/) (gratis, kakfri, ingen fingeravtrycksspårning). Aktivera: skapa ett gratis Cloudflare-konto → Web Analytics → lägg till webbplatsen `matjakt.store` → klistra in det genererade site-token i `<meta name="cf-beacon-token" content="...">` i `frontend/site/index.html`. Detta token är inte hemligt (det är en publik sididentifierare inbäddad i HTML, samma kategori som ett Google Analytics-ID) och är säkert att committa. Tomt värde = ingen analytics-kod laddas alls.
- **Egna produkthändelser** (klick på "Testa gratis", "Logga in", "Se hur det fungerar", samt visning av prissektionen) skickas till `POST /api/analytics/event` med enbart `{"event": "<namn>"}` - ingen cookie, inget konto-id, ingen plats. Backend räknar bara upp en daglig siffra per händelsenamn (`ANALYTICS_ALLOWED_EVENTS` i `backend/api_server.py`); allt annat avvisas. Anropet är "fire and forget" (`fetch(...).catch(() => {})`) och kan aldrig hindra en knapp från att fungera, även om anropet blockeras av en annonsblockerare eller CORS ännu inte tillåter den nya domänen.
- Ingen hemlig nyckel krävs för själva händelseräknaren - den är öppen och validerar bara mot en fast lista av tillåtna händelsenamn.

## Kända begränsningar

- Butikernas DOM och villkor kan ändras; selektorer och rätt till storskalig datainsamling måste verifieras före produktion.
- Produktmatchning och priser är inte ännu auktoritativa. Veckans inköpslista hämtar riktiga liveaktuella priser per vara (`POST /api/products/batch`) genom en textsökning i butikens sökresultat — matchningen föredrar en produkt vars namn faktiskt börjar med varunamnet, men är fortfarande fritextbaserad och kan träffa fel produkt om butiken inte har någon bra sökträff.
- ICA:s livepris-sökning (`/api/products`) är blockerad av en riktig CAPTCHA ("Human Verification") på deras sökresultatsida — inte något vi kan eller ska försöka kringgå. ICA-butiker visas därför alltid med den statiska prisuppskattningen, aldrig med "Live"-märkning. Butiksuppslaget (`resolve_ica_store`, `/api/stores`) fungerar dock fint, det är bara produktsökningen som är spärrad.
- API-cachen ligger i minnet (15 min TTL, max 200 poster) och delas inte mellan processer.
- Postnummer geokodas via `GET /api/geocode` (gratis, nyckelfritt uppslag mot zippopotam.us) och `/api/stores` hittar riktiga butiker var som helst i Sverige — första uppslaget för ett nytt postnummer kan ta upp till någon minut (Coop-sökningen driver en riktig webbläsarsession), därefter är det cachat 24h.
- Android-appen (Capacitor, `webDir: frontend`) laddas inte same-origin med backend som webbfrontenden gör. Sätt `<meta name="matjakt-api-url">` i `frontend/index.html` till en driftsatt backend-URL och kör `npx cap sync android` innan en Android-build används mot något annat än en lokal utvecklingsmiljö.
- Recepten har riktiga näringsvärden beräknade från Livsmedelsverkets öppna näringsdatabas (`backend/scripts/compute_recipe_nutrition.py`), men bara för de kvantifierade ingredienserna i receptet. Tillagningsfett (olja/smör under "Hemma") är inte kvantifierat och räknas inte in, så särskilt fettvärdet kan vara något lägre än verkligheten.
- Premium är kontobaserat (riktig inloggning, se `backend/services/accounts/`) men inte betalningsbaserat ännu — Premium låses upp med en kod (`MATJAKT_PREMIUM_CODE`) tills en riktig betallösning kopplas på.
