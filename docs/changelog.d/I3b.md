---
paket: I3b
titel: Datakartan beskrev fjolårets kod — tre rader stämde inte längre
---

`docs/DATA_MAP.md` och `docs/RETENTION.md` är grunden för
integritetspolicyn och App Store-etiketterna. De skrevs 2026-09-06 och blev
sedan stående medan koden gick vidare. Det upptäcktes när I3 skrev om
`frontend/integritetspolicy.html` **mot källkoden** och tre rader föll isär.

## Klient-IP låg inte i processminnet

Datakartan sa "bara i processminne för rate limit". Det stämde en gång.
`services/accounts/ratelimit.py` har sedan dess en rubrik som heter
PERSISTENT: räknarna ligger i `rate_limit_hits (action, identifier, ts)` i
en egen SQLite-fil, `ratelimit.db`, i datakatalogen (`api_server.py:511`).

Skillnaden är inte akademisk. `backup.take_backup()` kopierar varje `*.db` i
datakatalogen, så filen följer med i de nattliga backupseten och i tar.gz:en
från `/api/admin/backup-download`. En datakarta som säger "processminne" om
data som ligger i backupen på disk beskriver fel mängd persondata, och det är
just den mängden App Store-etiketten och policyn ska svara för.

`identifier` är dessutom mer än IP. `_rate_limit()` skriver klientens IP på
**varje** väg och lägger till e-postadressen på login, registrering och
lösenordsåterställning; sessionsvägar skickar en domänseparerad hash av
tokenen (`token_identifier`, B9) — aldrig tokenen själv. Raderna rensas när
de faller ur det längsta fönstret i `LIMITS`, 3600 sekunder.

Retentionstabellen bar samma fel omvänt: "i processminne, max 1 timme |
vid omstart". Att räknarna **överlever** omstarten är hela poängen — en
deploy ska inte förlåta en pågående attack.

## Analysen ligger i kontodatabasen, och en tabell är per konto

Datakartan sa `prices.db` (KV-cache), "bara räknare per händelsenamn".
`services/analytics/store.py` har numera två tabeller, och de ligger i
KONTOdatabasen på `AccountStore`:s egen anslutning:

    analytics_daily      händelse × dag   → antal   (anonymt, som förut)
    analytics_user_days  konto × dag × händelse → antal   (bara inloggade)

Den andra är en materiell skillnad för en datakarta: det finns en rad per
konto. KV-cachen dög inte längre eftersom den rensar allt äldre än sju
dagar — "senaste fjorton dagarna" tappade tyst hälften, och mätdata är inte
cache.

Därför ändrades också "Vem ser den": kontoinnehavaren ser sina egna rader via
`GET /api/account/export`, och raderna raderas med kontot (`delete_account`
kör `DELETE FROM analytics_user_days`). Samma föråldrade fakta stod på två
ställen till — principen överst ("räknare utan identitet") och raden
"Invändning mot analytics" — och rättades med. Någon egen avstängning av
mätningen finns inte i dag; det står nu som det är i stället för att antydas
bort.

## Exporten finns, knappen gör det inte

Raden "Tillgång/export" sa att bara `GET /api/account/state` fanns.
`GET /api/account/export` finns sedan B10 (`api_server.py:2686`,
`services/accounts/data_export.py`) och ger hela kontot i sju namngivna
kategorier — aldrig lösenordshash, salt, token eller sessioner. UI:t saknas
fortfarande: ingen fil under `frontend/app/` anropar endpointen. Det står nu
som det är, med båda halvorna.

## Acceptanstestet

`backend/tests/test_datakartan.py` jämför inte dokumentet med en andra kopia
av samma text — då hade det bara flyttat påståendet. Varje rad prövas mot den
kod som äger den: räknaren skrivs och läses på riktigt (och raden i
`rate_limit_hits` visas bära IP och e-post), en backup tas på riktigt och
`ratelimit.db` letas upp i setet, tabellnamnen läses ur `sqlite_master`,
kontot registreras och raderas och mätraderna eftersöks.

Gränsen gäller åt båda hållen. `test_ui_saknas_fortfarande_och_raden_sager_det`
söker igenom `frontend/app/` efter en anropare av exportendpointen och blir
röd den dagen knappen byggs — så att datakartan inte blir stående i fjolårets
sanning en gång till. Nio av tio prov faller på texten som stod här innan.

Ingen kod ändrades i det här paketet. `frontend/integritetspolicy.html` är
redan rättad av I3 och rördes inte.
