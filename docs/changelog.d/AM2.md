---
paket: AM2
titel: Hyllorna hämtas en gång per start, hur många gånger vyn än ritas om
---

Mätt i webbläsaren mot dev-servern: `/api/recipes/shelves?perShelf=12`
gick **två gånger vid varje start** (130 kB). `renderRecipeShelves()` körs
vid varje omritning, och vakten `state.hyllor.length` är tom tills första
svaret kommit — så varje omritning före svaret startade ett nytt anrop.

Ett anrop i luften delas nu av alla som frågar, precis som entitlementen
(AM1). Anropet går ut direkt som förut; det är delningen som är ett löfte.
`loadShelves` är injicerbar via vyns `host`, så spärren går att pröva utan
nät. Ett tomt svar öppnar för ett nytt försök vid nästa omritning; ett
nätfel river inte omritningen.
