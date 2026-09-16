// P02d: StoreKit-vägen i appen - det som går att bevisa utan en iPhone.
//
// Tre saker prövas: att premiumskärmen ritar StoreKits pris i stället för
// ett tal när det finns (och räknar ingen sparsumma på Apples tal), att
// köpknappen, betalväggen och portalknappen faktiskt FRÅGAR om StoreKit-läget
// innan de går till Stripe, och att markupen bär återställningsknappen och
// kodnotisens id som app.js växlar. Ett köp genom pluginet går inte att
// köra här - det som går är att se till att vägen dit finns och att
// Stripe-vägen står orörd när läget är av.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { paywallPlanMarkup, planMarkup, årsrabatt } from "../frontend/app/src/views/premiumskarmen.js";

const läs = rel => readFileSync(new URL(`../${rel}`, import.meta.url), "utf8");
const appJs = läs("frontend/app/app.js");
const accountJs = läs("frontend/app/src/views/account.js");
const indexHtml = läs("frontend/app/index.html");

const PRISER = {
  monthly: { pricePerMonth: 59, storekitProductId: "se.matjakt.premium.monthly" },
  yearly: { pricePerYear: 399, storekitProductId: "se.matjakt.premium.yearly" },
};
const STOREKIT = {
  monthly: { ...PRISER.monthly, displayPrice: "59,00 kr" },
  yearly: { ...PRISER.yearly, displayPrice: "399,00 kr" },
};

test("med StoreKits pris ritas strängen som den är, och ingen sparsumma räknas", () => {
  const delar = planMarkup(STOREKIT);
  assert.match(delar.month, /class="pris prem-plan-tal">59,00 kr</);
  assert.match(delar.year, /class="pris prem-plan-tal">399,00 kr</);
  assert.doesNotMatch(delar.year, /spara/, "12 x månad - år är webbens aritmetik, inte Apples");
  assert.equal(årsrabatt(STOREKIT), null);
  const vägg = paywallPlanMarkup(STOREKIT);
  assert.match(vägg, /399,00 kr/);
  assert.doesNotMatch(vägg, /motsvarar|spara/);
  // Strängen escapas: ett pris får inte kunna bära markup.
  assert.match(planMarkup({ monthly: { displayPrice: "<b>1</b>" } }).month, /&lt;b&gt;1&lt;\/b&gt;/);
});

test("utan StoreKits pris är skärmen exakt som förut", () => {
  const delar = planMarkup(PRISER);
  assert.match(delar.month, /prem-plan-tal/);
  assert.match(delar.year, /spara 309 kr/);
  assert.equal(årsrabatt(PRISER), 309);
  assert.match(paywallPlanMarkup(PRISER), /motsvarar 33 kr per månad/);
  // Tom eller blank displayPrice räknas inte som ett pris.
  assert.match(planMarkup({ monthly: { pricePerMonth: 59, displayPrice: "  " } }).month, /59/);
});

test("köpknappen frågar om StoreKit-läget innan den går till Stripe", () => {
  const start = appJs.indexOf('$("subscribeBtn").addEventListener');
  assert.notEqual(start, -1);
  const handler = appJs.slice(start, appJs.indexOf("startCheckout(", start));
  assert.match(handler, /if \(storeKitActive\(\)\) \{ await purchaseWithStoreKit\(selectedPlan\); return; \}/,
    "StoreKit-grenen ska ligga före Stripe-anropet i köpknappens lyssnare");
});

test("betalväggen går samma väg som köpknappen", () => {
  const start = accountJs.indexOf("export async function beginCheckout");
  const body = accountJs.slice(start, accountJs.indexOf("startCheckout(", start));
  assert.match(body, /app\.storeKitActive\?\.\(\)/);
  assert.match(body, /app\.purchaseWithStoreKit\(plan/);
  // och hookarna skickas in från app.js
  assert.match(appJs, /storeKitActive, purchaseWithStoreKit, storeKitPricing,/);
  // Betalväggens knappar visar samma pris som kontoarkets flikar: StoreKits
  // i StoreKit-läget. premiumPricing() själv är orörd (reservpriset.test.js
  // klipper ut den ur källan och kör den fristående).
  assert.match(accountJs, /paywallPlanMarkup\(app\.storeKitPricing \? app\.storeKitPricing\(\) : pricing\)/);
  assert.match(appJs, /const pricing = storeKitPricing\(\);\n(?:.*\n){3}\s*ritaPlanval\(pricing\);/);
  const premiumPricing = appJs.match(/function premiumPricing\(\) \{[\s\S]*?\n\}/)[0];
  assert.doesNotMatch(premiumPricing, /storeKit/, "premiumPricing() ska förbli självständig");
});

test("Hantera prenumeration går till Apple när källan är Apple", () => {
  const start = appJs.indexOf('$("manageBillingBtn").addEventListener');
  const handler = appJs.slice(start, appJs.indexOf("openBillingPortal(", start));
  assert.match(handler, /entitlementSource === "apple"/);
  assert.match(handler, /manageSubscriptions/);
  assert.match(handler, /MANAGE_SUBSCRIPTIONS_URL/);
});

test("pluginet registreras som proxy och köpet anmäls till servern", () => {
  assert.match(appJs, /NativePurchases: registerPlugin\(STOREKIT_PLUGIN\)/);
  assert.match(appJs, /claimAppleTransaction\(state\.authToken, jws\)/);
  assert.match(appJs, /purchaseProduct\(options\)/);
  assert.match(appJs, /onlyCurrentEntitlements: true/);
  // Ingen egen kopia av produkt-id:na i app.js: de läses ur entitlements.
  assert.doesNotMatch(appJs, /se\.matjakt\.premium\./);
});

test("ångerrättsrutan ritas inte i StoreKit-läget", () => {
  const start = appJs.indexOf("function withdrawalConsentMarkup(");
  const body = appJs.slice(start, appJs.indexOf("function withdrawalConsentGiven"));
  assert.match(body, /if \(storeKitActive\(\)\) return "";/);
});

test("markupen bär återställningsknappen (dold) och kodnotisens id", () => {
  assert.match(indexHtml, /id="restorePurchasesBtn" hidden>Återställ köp</);
  assert.match(indexHtml, /id="premiumCodeNote"/);
  assert.match(appJs, /\$\("restorePurchasesBtn"\)\.addEventListener\("click", restoreWithStoreKit\)/);
  for (const id of ["premiumCodeNote", "accountRedeemForm"]) assert.match(appJs, new RegExp(`"${id}"`));
});
