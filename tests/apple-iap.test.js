// P02d: StoreKit-logiken utan DOM och utan plugin.
//
// Modulen avgör NÄR köpet går via Apple och ÖVERSÄTTER mellan serverns
// kontrakt (/api/entitlements: apple-blocket, pricing med storekitProductId)
// och pluginets (Product, Transaction). Allt här är rena funktioner - det
// är hela poängen med att de inte ligger i app.js.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PENDING_TEXT, isPending,
  MANAGE_SUBSCRIPTIONS_URL, PLUGIN_NAME, isUserCancelled, overlayStoreKitPrices, planForProduct,
  productForPlan, productIdentifiers, purchaseOptions, restorableTransactions, storeKitActive,
} from "../frontend/app/src/services/apple-iap.js";

const MONTHLY = "se.matjakt.premium.monthly";
const YEARLY = "se.matjakt.premium.yearly";
const ENT = {
  apple: { enabled: true, products: { monthly: MONTHLY, yearly: YEARLY }, appAccountToken: "2f1d0a3e-6a1c-5b3d-9c2e-1f0a9b8c7d6e" },
  pricing: {
    monthly: { plan: "premium_monthly", label: "Premium", pricePerMonth: 59, storekitProductId: MONTHLY },
    yearly: { plan: "premium_yearly", label: "Premium År", pricePerYear: 399, storekitProductId: YEARLY },
  },
};

test("StoreKit-vägen gäller bara i iOS-appen och bara när servern sagt på", () => {
  assert.equal(storeKitActive(ENT, { native: true, platform: "ios" }), true);
  assert.equal(storeKitActive(ENT, { native: false, platform: "web" }), false, "webben rör sig inte");
  assert.equal(storeKitActive(ENT, { native: true, platform: "android" }), false, "Play har inga produkter");
  assert.equal(storeKitActive({ apple: { enabled: false } }, { native: true, platform: "ios" }), false, "flaggan av = dagens beteende");
  assert.equal(storeKitActive({}, { native: true, platform: "ios" }), false, "inget apple-block = av");
  assert.equal(storeKitActive(null, { native: true }), false);
});

test("produkt-id:na kommer ur serverns apple-block, inte ur en egen kopia", () => {
  assert.equal(productForPlan(ENT, "monthly"), MONTHLY);
  assert.equal(productForPlan(ENT, "yearly"), YEARLY);
  assert.equal(productForPlan(ENT, "weekly"), null);
  assert.equal(productForPlan({}, "monthly"), null);
  assert.equal(planForProduct(ENT, YEARLY), "yearly");
  assert.equal(planForProduct(ENT, "se.annan.app.premium"), null);
  assert.deepEqual(productIdentifiers(ENT), [MONTHLY, YEARLY]);
  assert.deepEqual(productIdentifiers({}), []);
});

test("köpet bär kontots appAccountToken - utan det inget köp", () => {
  assert.deepEqual(purchaseOptions(ENT, "yearly"),
    { productIdentifier: YEARLY, productType: "subs", appAccountToken: ENT.apple.appAccountToken });
  assert.equal(purchaseOptions({ apple: { enabled: true, products: ENT.apple.products } }, "yearly"), null,
    "anonym (ingen token) kan inte köpa - köpet skulle inte gå att knyta till ett konto");
  assert.equal(purchaseOptions(ENT, "weekly"), null);
});

test("StoreKits pris läggs ovanpå serverns tal som displayPrice, serverns tal står kvar", () => {
  const products = [
    { identifier: MONTHLY, priceString: "59,00 kr", price: 59, currencyCode: "SEK" },
    { identifier: YEARLY, priceString: "399,00 kr", price: 399, currencyCode: "SEK" },
  ];
  const ut = overlayStoreKitPrices(ENT.pricing, products);
  assert.equal(ut.monthly.displayPrice, "59,00 kr");
  assert.equal(ut.yearly.displayPrice, "399,00 kr");
  assert.equal(ut.monthly.pricePerMonth, 59, "serverns tal finns kvar under");
  assert.equal(ENT.pricing.monthly.displayPrice, undefined, "originalet rörs inte");
  // En produkt Apple inte känner (fel id) ger ingen displayPrice för den planen.
  const bara_ar = overlayStoreKitPrices(ENT.pricing, [products[1]]);
  assert.equal(bara_ar.monthly.displayPrice, undefined);
  assert.equal(bara_ar.yearly.displayPrice, "399,00 kr");
  // Tomt, null, skräp: objektet returneras orört.
  assert.equal(overlayStoreKitPrices(ENT.pricing, []), ENT.pricing);
  assert.equal(overlayStoreKitPrices(ENT.pricing, null), ENT.pricing);
  assert.equal(overlayStoreKitPrices(ENT.pricing, [{ identifier: MONTHLY, priceString: "  " }]), ENT.pricing);
  assert.equal(overlayStoreKitPrices(null, products), null);
});

test("återställning anmäler bara VÅRA aktiva köp med en JWS", () => {
  const purchases = [
    { productIdentifier: YEARLY, jwsRepresentation: "a.b.c", isActive: true },
    { productIdentifier: MONTHLY, jwsRepresentation: "d.e.f" },                 // isActive saknas = räknas
    { productIdentifier: MONTHLY, jwsRepresentation: "g.h.i", isActive: false }, // gammalt köp
    { productIdentifier: "se.annan.app.pro", jwsRepresentation: "j.k.l", isActive: true },
    { productIdentifier: YEARLY, isActive: true },                              // ingen JWS = kan inte verifieras
  ];
  assert.deepEqual(restorableTransactions(purchases, ENT), ["a.b.c", "d.e.f"]);
  assert.deepEqual(restorableTransactions([], ENT), []);
  assert.deepEqual(restorableTransactions(undefined, ENT), []);
});

test("ett köp som väntar på godkännande är inget fel - och inget köp", () => {
  assert.equal(isPending(new Error("Transaction pending")), true);
  assert.equal(isPending({ message: "purchase deferred" }), true);
  assert.equal(isPending(new Error("User cancelled")), false);
  assert.equal(isPending(null), false);
  assert.match(PENDING_TEXT, /godkänn/);
});

test("att kunden stänger köparket är inget fel", () => {
  assert.equal(isUserCancelled(new Error("Purchase was cancelled by the user")), true);
  assert.equal(isUserCancelled({ message: "userCancelled" }), true);
  assert.equal(isUserCancelled(new Error("Network error")), false);
  assert.equal(isUserCancelled(null), false);
});

test("konstanterna är de pluginet och Apple använder", () => {
  assert.equal(PLUGIN_NAME, "NativePurchases");
  assert.equal(MANAGE_SUBSCRIPTIONS_URL, "https://apps.apple.com/account/subscriptions");
});
