---
paket: K3c
titel: Hälsogrinden ställde fel fråga och gjorde main permanent röd
---

Grinden frågade *"kör drift EXAKT den här committen?"*. Render slår ihop
snabba pushar och deployar den **senaste** — en natt med tjugo merger ger
därför grindkörningar som aldrig kan bli gröna, för produktionen kommer
aldrig att köra mellanläggen.

Det hände: K6c:s `e4e55836` pollades i 466 sekunder medan drift stod på
`9968f6d`, och drift gick sedan vidare till `e836a3d` utan att stanna på
vår commit.

Invarianten som faktiskt ska skyddas är att **frontenden aldrig är nyare än
backenden**. En backend som ligger före är i sin ordning. Frågan är alltså
*"är drift minst lika ny?"* — är vår commit förfader till den drift kör.

Det spelar roll bortom en röd bock: en main som alltid är röd lär alla att
ignorera röd CI, och då är grinden sämre än ingen grind.
