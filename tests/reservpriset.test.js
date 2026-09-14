// L7b: RESERVPRISET GJORDE L7:s "PRIS SAKNAS" ONÅBAR
//
// L7 flyttade Premium-skärmens belopp till src/views/premiumskarmen.js och
// skrev i docs/changelog.d/L7.md: "Saknas svaret från /api/entitlements
// renderas 'pris saknas' - ett tomt fack är sant, ett påhittat tal är det
// inte." Modulen gör precis det. Men app.js premiumPricing() lade ett
// reservobjekt med 59 och 399 mellan svaret och vyn, så vyn fick aldrig se
// ett saknat pris. L7:s eget test kom åt vägen bara genom att anropa modulen
// direkt med {} - alltså en väg som fanns i testet men inte i appen.
//
// Det här testet går den väg appen faktiskt går: premiumPricing() ur app.js,
// in i premiumskarmen.js. Utan ändringen ritar den "59"/"399" och faller.
//
// Varför reserven och inte påståendet fick vika: app.js skriver två rader
// ovanför renderPriceTabs() att "59/399 bor på exakt ett ställe: backend
// (features.py -> /api/entitlements)" och att hårdkodad prismarkup "kunde
// tyst börja ljuga". Reservobjektet var den sortens hårdkodning, i samma fil
// som förbudet. L7 tog bort kontoarkets egna reservsiffror av exakt det
// skälet ("en reservsiffra i en mening om vad kunden BETALAR är den
// farligaste sorten") men lämnade kvar den som de alla hämtade sitt värde ur.
// Prisinformationslagen (2004:347) kräver dessutom att priset en konsument
// visas är det hon betalar - ett inaktuellt reservpris på en betalvägg är
// inte ett designfel utan ett lagkrav som inte hålls.

import assert from "node:assert/strict";
import test from "node:test";

import { läsFil } from "./fixtures/css-parser.mjs";
import { paywallPlanMarkup, planMarkup, planetikett, årsrabatt }
  from "../frontend/app/src/views/premiumskarmen.js";

const appKälla = läsFil("frontend/app/app.js");

// app.js är en webbläsarmodul som rör DOM:en redan vid import och går därför
// inte att importera här. Funktionen plockas ut ur källan och körs med
// `entitlements` som parameter - samma namn som modulvariabeln den läser.
function premiumPricingUrKällan() {
  const träff = appKälla.match(/function premiumPricing\(\) \{[\s\S]*?\n\}/);
  assert.ok(träff, "premiumPricing() hittades inte i app.js");
  return new Function("entitlements", `${träff[0]}\nreturn premiumPricing();`);
}

const premiumPricing = premiumPricingUrKällan();

test("utan svar från /api/entitlements renderar skärmen \"pris saknas\"", () => {
  // Svaret har inte kommit än, eller kom utan pricing. Det är exakt det läge
  // L7.md beskriver, och det enda läget där reservobjektet någonsin användes.
  const pricing = premiumPricing({});

  const delar = planMarkup(pricing);
  assert.match(delar.month, /class="saknas">pris saknas</,
    "månadsknappen ritar ett tal som inte kommer från backend");
  assert.match(delar.year, /class="saknas">pris saknas</,
    "årsknappen ritar ett tal som inte kommer från backend");
  assert.match(paywallPlanMarkup(pricing), /class="saknas">pris saknas</,
    "betalväggen ritar ett tal som inte kommer från backend");

  // Och ingenting får lova en rabatt eller en plan den inte kan belägga.
  assert.equal(årsrabatt(pricing), null);
  assert.equal(planetikett(pricing, "yearly"), "din plan");
  assert.equal(planetikett(pricing, "monthly"), "din plan");
});

test("premiumPricing() bär inga priser och inga döda fält", () => {
  // Kommentarerna bort först. Den här funktionens kommentar NAMNGER talen den
  // inte längre får returnera ("reservobjektet bar 59/399"), och en grind som
  // fäller sin egen förklaring tvingar fram en sämre kommentar. Funktionen har
  // inga strängar med "//" i sig, så en radvis strykning räcker.
  const träff = appKälla.match(/function premiumPricing\(\) \{[\s\S]*?\n\}/);
  const kropp = träff[0].replace(/\/\/.*$/gm, "");

  // 59, 399, 33 och 309 - alla fyra talen L7 räknade upp. De bor i
  // backend/services/accounts/features.py och ska nå klienten därifrån.
  for (const tal of ["59", "399", "33", "309"]) {
    assert.ok(!new RegExp(`\\b${tal}\\b`).test(kropp),
      `premiumPricing() har kvar talet ${tal} - priset bor i features.PRICING`);
  }

  // Fälten som L7 slutade läsa. De låg kvar och bar hårdkodade priser i ett
  // publikt repo, utan en enda läsare kvar i frontend/.
  for (const fält of ["priceText", "perMonthText", "savingsText", "badge"]) {
    assert.ok(!kropp.includes(fält),
      `premiumPricing() har kvar det döda fältet ${fält}`);
  }
});

test("priset från backend går fram oförändrat", () => {
  // Grinden ovan går att passera genom att sluta lämna vidare svaret också.
  // 49/349 är inte appens priser, så talen kan bara komma ur indatan - och
  // 239 måste räknas fram (49 * 12 - 349), inte hämtas ur ett minne.
  const pricing = premiumPricing({
    pricing: { monthly: { pricePerMonth: 49 }, yearly: { pricePerYear: 349 } },
  });

  assert.match(planMarkup(pricing).month, />49 kr</);
  assert.match(planMarkup(pricing).year, />349 kr</);
  assert.equal(årsrabatt(pricing), 239);
  assert.equal(planetikett(pricing, "yearly"), "349 kr per år");
  assert.equal(planetikett(pricing, "monthly"), "49 kr per månad");
});
