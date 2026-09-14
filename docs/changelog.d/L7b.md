---
paket: L7b
titel: Reservpriset togs bort — "pris saknas" är en väg appen faktiskt går
---

L7 flyttade Premium-skärmens belopp till `src/views/premiumskarmen.js` och
skrev att skärmen renderar **"pris saknas"** när `/api/entitlements` inte
svarat: *"ett tomt fack är sant, ett påhittat tal är det inte."* Modulen gör
precis det. Men `app.js premiumPricing()` låg mellan svaret och vyn och
returnerade ett reservobjekt med 59 och 399 när svaret saknades, så vyn fick
aldrig se ett saknat pris. Påståendet var sant om komponenten och falskt om
appen.

L7:s eget test nådde vägen bara genom att anropa modulen direkt med `{}` —
alltså en väg som fanns i testet men inte i produkten. Ett test som bevakar ett
tillstånd appen inte kan hamna i bevakar ingenting.

## Vad som gällde

```js
return entitlements.pricing || {
  monthly: { priceText: "59 kr/mån", pricePerMonth: 59 },
  yearly: { priceText: "399 kr/år", pricePerYear: 399, perMonthText: "≈ 33 kr/mån",
            savingsText: "Spara 309 kr jämfört med månadsbetalning", badge: "Bäst värde" },
};
```

Fyra av fälten — `priceText`, `perMonthText`, `savingsText` och `badge` — hade
ingen läsare kvar i `frontend/` efter L7. De bar hårdkodade priser i ett publikt
repo utan att rita en enda pixel.

## Vad som gäller nu

`return entitlements.pricing || {};`

Priset bor i `backend/services/accounts/features.py` (`PRICING`) och når
klienten via `/api/entitlements`. Har svaret inte kommit säger skärmen det.

Att reserven och inte påståendet fick vika är inte en smaksak. Två rader ovanför
`renderPriceTabs()` står redan i samma fil att *"59/399 bor på exakt ett ställe:
backend"* och att hårdkodad prismarkup *"kunde tyst börja ljuga"* — reservobjektet
var den sortens hårdkodning, i filen som förbjuder den. L7 tog bort kontoarkets
egna reservsiffror med motiveringen att *"en reservsiffra i en mening om vad
kunden BETALAR är den farligaste sorten"*, men lämnade kvar den som de hämtade
sitt värde ur. Och Prisinformationslagen (2004:347), som L7 självt åberopar för
momsraden, kräver att priset en konsument visas är det hon betalar; ett
inaktuellt reservpris på en betalvägg är inte ett designfel utan ett lagkrav
som inte hålls.

Kostnaden är ett kort "pris saknas" innan svaret kommit, och ett bestående
sådant när nätet är nere. Det senare är rätt utfall: går inte
`/api/entitlements` fram går inte köpet fram heller, och då är ett tomt fack
ärligare än ett tal som kan ha slutat gälla.

## Acceptansen

`tests/reservpriset.test.js` (3 fall) går den väg appen går: `premiumPricing()`
plockas ur `app.js`-källan och körs med `entitlements` som parameter, och
resultatet matas in i `premiumskarmen.js`. Utan ändringen ritar båda knapparna
och betalväggen `59 kr` respektive `399 kr` där `pris saknas` ska stå, och
testet faller.

Andra fallet kräver att `premiumPricing()` inte bär något av talen 59, 399, 33
eller 309 och inget av de fyra döda fälten — kommentarerna maskeras först, så
att grinden inte fäller sin egen förklaring. Tredje fallet är motgrinden: den
går att passera genom att sluta lämna vidare svaret också, så 49/349 matas in
och 239 måste räknas fram ur dem.
