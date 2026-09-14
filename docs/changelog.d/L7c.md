---
paket: L7c
titel: Kommentaren som beskrev reservpriset efter att det tagits bort
---

L7b tog bort reservvärdet ur `app.js premiumPricing()`; funktionen returnerar
sedan dess `entitlements.pricing || {}`. Filhuvudet i
`src/views/premiumskarmen.js` beskrev fortfarande det som togs bort:

> app.js premiumPricing() har ett reservvärde för de första hundra
> millisekunderna

Det var precis det reservvärdet som var problemet — det låg mellan svaret och
vyn och gjorde modulens egen **"pris saknas"**-väg onåbar i appen. Kommentaren
utlovade alltså ett beteende som L7b avskaffade, i samma filhuvud som fyra
rader tidigare skriver att skärmen renderar "pris saknas" när
`/api/entitlements` inte svarat. Två meningar i samma block sa emot varandra,
och den falska stod närmast talen.

Halvan är omskriven till vad som faktiskt händer: `premiumPricing()` lägger
ingenting emellan, så utan svar får modulen ett tomt objekt och renderar "pris
saknas". Kommentarens poäng står kvar orörd — 59 och 399 bor i backend
(`features.PRICING`) och modulen har ingen egen åsikt om dem.

## Om `account.js`

Noten vid `paywallPlanMarkup`-importen (`src/views/account.js`, rad 22–25)
kontrollerades med. Den nämner `priceText` men står i **imperfekt** —
*"Betalväggen hade egna strängar med `priceText` som reserv"* — och beskriver
det L7 tog bort, inte ett reservvärde som finns nu. `git grep priceText` i
`frontend/` hittar bara de två kommentarerna; betalväggen ritar sina belopp med
`paywallPlanMarkup(pricing)`. Påståendet är alltså sant och lämnades orört. Det
skiljer sig från det rättade: det stod i presens om en funktion som inte längre
gör det.

Ingen beteendeändring — bara kommentarer, och därför inget nytt acceptanstest.
`tests/reservpriset.test.js` från L7b är den grind som bevakar att beskrivningen
förblir sann.
