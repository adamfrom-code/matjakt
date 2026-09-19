---
paket: N1b
titel: Releasebygge 2 — byggnummer och ljust systemgränssnitt
---

`CURRENT_PROJECT_VERSION` 1 → 2 i båda konfigurationerna: TestFlight
1.0 (1) laddades upp 2026-09-12 och nästa uppladdning måste ha ett högre
nummer. Höjningen görs i repot så att det som skickades går att läsa av i
historiken; `test_ios_nycklarna` kräver 2 och förbjuder 1.

`UIUserInterfaceStyle = Light` i `Info.plist`: appen är ljus (mörkt läge
är ett uttryckligt `data-theme`, inte `prefers-color-scheme`), och utan
nyckeln följde tangentbord, ark och statusfält telefonens mörka läge över
en ljus app.
