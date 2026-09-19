---
paket: I5c
titel: Butiksbilderna följer dagens UI — 18 skärmbilder genererade
---

`backend/scripts/make_store_screenshots.py` var skrivet för UI:t före
G11/L2/L5: det loggade in via profilknappen (som nu leder till
Inställningar — kontoraden där öppnar arket), väntade på butikskorten på
Handla (de ritas på Veckan sedan L2) och på `#statSavedWeek` (borta sedan
L5). Nu följer det samma väg som browser-E2E:n (`open_account`,
`fill_onboarding`) och genererar alla arton bilder i fixturläge: sex
scener × iPhone 6,7" (1290×2796), 6,5" (1242×2688) och Play (1080×1920).
Bilderna är genererade och committas inte (CLAUDE.md §6); de laddas upp
till App Store Connect.
