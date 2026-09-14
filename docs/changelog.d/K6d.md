---
paket: K6d
titel: Priscachens baslinje kände inte till parser_version
---

`backend/tests/fixturer/scheman/priscache.sql` är den databas K6:s
rollback-tester bygger, skriver en rad i, och låter dagens kod öppna. Hela
värdet ligger i att den är schemat som *står i drift* — backenden deployas på
push till main, så varje merge är en release och det K4:s `rollback`-jobb
startar mitt i natten är föregående main-commit.

Den kände inte till `product_cache.parser_version`, som kom med #7 den
2026-09-07 — fyra dagar innan fixturen över huvud taget dumpades i K6 (#110).
Baslinjen föddes alltså redan efterbliven.

Just den kolumnen är den vassaste av dem alla: `parser_version TEXT NOT NULL
DEFAULT ''` är den enda migrerade NOT NULL-kolumnen i repot, och en NOT
NULL-kolumn utan DEFAULT är exakt det som gör en återställning till en andra
incident — den gamla koden skriver inte kolumnen, och varje INSERT den gör
avvisas. `test_en_insert_med_bara_gamla_kolumner_gar_fortfarande_igenom`
finns till för att fånga det. Med en baslinje som saknade kolumnen hade den
ingenting att fånga.

Baslinjen är omgenererad med `test_migrationer.py --spara`. Kvar blir en
grind: `test_priscache_schemabaslinje.py` jämför fixturens CREATE-satser mot
dem dagens `PriceCacheStore` bygger från en tom databas, och failar när de
skiljer sig. Nästa ändring i priscachens schema måste alltså ta med sin
baslinje — vilket är vad docstringen i `test_migrationer.py` redan bad om.

Bara priscachens fixtur ligger i det här paketet. `konton.sql` (Z-AUTH) och
`recept.sql` (Z-GROCERY) släpar på samma sätt, men i andra zoner.
