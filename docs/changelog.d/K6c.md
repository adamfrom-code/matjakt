---
paket: K6c
titel: Kontoschemats baslinje låg fyra releaser efter drift
---

`backend/tests/fixturer/scheman/konton.sql` är den databas K6:s
rollback-tester bygger, skriver en rad i, och låter dagens kod öppna. Hela
värdet ligger i att den är schemat som *står i drift* — backenden deployas på
push till main, så varje merge är en release och det K4:s `rollback`-jobb
startar mitt i natten är föregående main-commit.

Den låg efter. `users` hade vuxit med åtta kolumner sedan fixturen dumpades i
K6 (#110), och ingen av dem fanns i baslinjen: `withdrawal_consent_at` och
`withdrawal_consent_version` (B3, #63 — mergad samma dygn som K6, men före),
`first_week_at` (J3, #114) och `past_due_since`, `pending_email`,
`pending_email_token`, `pending_email_expires_at`, `renewal_reminder_for`
(J5, #135).

Det syntes inte, och det är poängen. Sviten var grön hela tiden: migrationerna
är additiva, så allt fixturen kände till överlevde. Men
`test_ingen_tabell_och_ingen_kolumn_forsvinner` skyddar exakt de kolumner
fixturen känner till — åtta kolumner som ligger i produktion stod utanför.
Hade någon av de fyra mellanliggande releaserna döpt om eller tappat en av
dem hade testet tigit, och en återställning hade blivit en andra incident i
stället för en väg tillbaka.

Baslinjen är omgenererad med `test_migrationer.py --spara`. Kvar blir en
grind: `test_konton_schemabaslinje.py` jämför fixturens CREATE-satser mot
dem dagens `AccountStore` bygger från en tom databas, och failar när de
skiljer sig. Nästa ändring i kontoschemat måste alltså ta med sin baslinje —
vilket är vad docstringen i `test_migrationer.py` redan bad om.

Bara kontolagrets fixtur ligger i det här paketet. `priscache.sql` (Z-PRICING)
och `recept.sql` (Z-GROCERY) släpar på samma sätt, men i andra zoner.
