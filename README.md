# Skärmdumpar för PR "L1: Ikväll blev ett fotokort"

Sex PNG:er, tagna med Playwright i 390×844 (mobil viewport), ljust och mörkt
läge. Grenen finns BARA för att PR-beskrivningen ska kunna visa dem; den
innehåller ingen kod, mergas aldrig, och kan raderas när PR:en är granskad.

| Fil | Vad den visar |
|---|---|
| `L1-fore-light.png` / `L1-fore-dark.png` | `main` före paketet: Ikväll som en rad |
| `L1-efter-light.png` / `L1-efter-dark.png` | Ikväll som fotokort |
| `L1-utan-foto-light.png` / `L1-utan-foto-dark.png` | samma skärm med ett recept UTAN foto, alltså M2:s reservkort som hjälteytans underlag |

Mörkt läge ligger tills vidare bakom ett uttryckligt `[data-theme="dark"]`
och inte bakom `prefers-color-scheme` (styles.css, etapp 3) — dumparna sätter
därför attributet innan bilden tas.

Rätten utan foto är Pitepalt med fläsk, en av de tio `middag`-rätter i
receptbanken som inte har någon bild vi får publicera.
