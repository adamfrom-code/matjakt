import test from "node:test";
import assert from "node:assert/strict";
import { campaignStillValid, extraLineTotal, extraUnitPrice, extrasTotal,
         newExtraItem, removeExtra, setQty } from "../frontend/app/src/services/extras.js";

// =============================================================================
// Regeln som aldrig får brytas: kampanjpriset följer sin kedja.
// =============================================================================
const willysDeal = () => newExtraItem({
  name: "Kaffe Gevalia 450 g", source: "campaign", chain: "Willys",
  campaignPrice: 39.9, regularPrice: 54.9, qty: 1,
});

test("kampanjpriset gäller hos sin egen kedja", () => {
  assert.equal(extraUnitPrice(willysDeal(), "Willys", undefined), 39.9);
});

test("kampanjpriset följer ALDRIG med till fel kedja", () => {
  assert.equal(extraUnitPrice(willysDeal(), "Hemköp", undefined), null);
});

test("hos en annan kedja gäller bara dess egen riktiga match", () => {
  assert.equal(extraUnitPrice(willysDeal(), "Hemköp", { unitPrice: 47.5 }), 47.5);
});

test("en riktig match hos egna kedjan vinner över det sparade kampanjpriset", () => {
  // Matchen är färskare data från samma kedja - kampanjen kan ha bytts ut.
  assert.equal(extraUnitPrice(willysDeal(), "Willys", { unitPrice: 41.0 }), 41.0);
});

test("en manuell vara utan match har inget pris - aldrig ett påhittat", () => {
  const manual = newExtraItem({ name: "Toalettpapper" });
  assert.equal(extraUnitPrice(manual, "Willys", undefined), null);
  assert.equal(extraLineTotal(manual, "Willys", undefined), null);
});

test("utgången kampanj prissätter inte längre raden", () => {
  const expired = newExtraItem({
    name: "Cola", source: "campaign", chain: "Willys",
    campaignPrice: 12.0, validUntil: "2020-01-01",
  });
  assert.equal(extraUnitPrice(expired, "Willys", undefined), null);
  assert.equal(campaignStillValid(expired), false);
});

test("antal 1 -> 2 dubblar radens totalsumma", () => {
  const deal = willysDeal();
  assert.equal(extraLineTotal(deal, "Willys", undefined), 39.9);
  const doubled = setQty([deal], deal.id, 2)[0];
  assert.equal(extraLineTotal(doubled, "Willys", undefined), 79.8);
});

test("borttagning ändrar totalsumman", () => {
  const a = willysDeal();
  const b = newExtraItem({ name: "Mjölk", source: "campaign", chain: "Willys", campaignPrice: 14.9 });
  assert.equal(extrasTotal([a, b], "Willys"), 54.8);
  assert.equal(extrasTotal(removeExtra([a, b], b.id), "Willys"), 39.9);
});

test("oprissatta rader bidrar med noll, inte med gissningar", () => {
  const priced = willysDeal();
  const manual = newExtraItem({ name: "Tandkräm" });
  assert.equal(extrasTotal([priced, manual], "Willys"), 39.9);
});

test("antal går inte under 1", () => {
  const deal = willysDeal();
  assert.equal(setQty([deal], deal.id, 0)[0].qty, 1);
});
