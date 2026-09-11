# Baslinjeschema — databasen som den ser ut i FÖREGÅENDE release

En fil per lager, dumpad ur `sqlite_master`. **Aldrig en `.db`**: spårade
databasfiler är förbjudna i det här repot, och anledningen står i `CLAUDE.md`.

`backend/tests/test_migrationer.py` bygger en databas ur varje fil, skriver en
rad i den, och låter **dagens** kod öppna den. Då körs migrationerna på
riktigt, mot ett riktigt äldre schema, med data i — och testerna säger till om
en tabell, en kolumn eller en rad inte överlever.

Det spelar roll sedan K4: `rollback`-jobbet startar den föregående
live-deployen av sig själv när rökprovet faller. Efter en återställning kör
**gammal kod mot en databas som ny kod redan migrerat**. Det går bra så länge
varje migration är rent additiv — och det är precis det de här filerna är till
för att bevisa.

## Var baslinjen kommer ifrån

Nuvarande baslinje: **`87dc496`** (2026-09-07). Två migrationer är levande mot
den just nu — `users.withdrawal_consent_at`/`_version` (B3) och
`product_cache.parser_version` — så testerna är skarpa från dag ett och inte
ett löfte om framtiden.

## När den ska flyttas fram

Vid en release, när den gamla baslinjen inte längre kör någonstans:

    python backend/tests/test_migrationer.py --spara

Den dumpar dagens schema. Flytta den **inte** i samma commit som en
schemaändring — då prövas den ändringen aldrig av någon, och filen blir en
kopia av koden i stället för ett minne av vad som står i drift.
