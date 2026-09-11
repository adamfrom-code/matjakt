# Sparade svar från kedjornas egna API:er

Varje fil här är formen på ett **riktigt** svar, med riktiga fältnamn och
riktiga värden ur importerna 2026-08-30/31 (samma som står dokumenterade
överst i `backend/services/grocery/providers/axfood.py` och
`providers/citygross.py`). Listorna är förkortade till några produkter —
formen är poängen, inte mängden.

`backend/tests/test_collector_kontrakt.py` kör kedjornas riktiga
parsningskod mot de här filerna. Ingen nättrafik, inget beroende av att
Willys WAF släpper igenom just i dag.

**Ändra aldrig en fil här för att få ett test grönt.** Den dagen en kedja
byter fältnamn är testets rödhet hela poängen: `normalize_product` läser
varje fält med `.get()`, så en omdöpt nyckel kastar inget undantag — den
ger `regular_price=None`, och kollektorn sparar produkten och rapporterar
`status="success"`. En import som tyst slutat bära priser ser exakt likadan
ut som en frisk. Filerna uppdateras när kedjans svar *verkligen* har ändrats,
och då i samma commit som koden som läser det nya fältet.
