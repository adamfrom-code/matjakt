import test from "node:test";
import assert from "node:assert/strict";
import { expiryStatus, matchLocalRecipesToPantry, normalizePantry, normalizePantryEntry, pantryAmounts } from "../frontend/app/src/services/pantry.js";

test("normalizePantryEntry migrerar gamla platta nummer till skafferi utan datum", () => {
  assert.deepEqual(normalizePantryEntry(5), { amount: 5, location: "skafferi", expiry: null });
});
test("normalizePantryEntry behåller plats och datum, faller tillbaka på skafferi för okänd plats", () => {
  assert.deepEqual(normalizePantryEntry({ amount: 2, location: "frys", expiry: "2026-09-01" }), { amount: 2, location: "frys", expiry: "2026-09-01" });
  assert.equal(normalizePantryEntry({ amount: 1, location: "garage" }).location, "skafferi");
});
test("normalizePantry hanterar en blandad, delvis gammal pantry", () => {
  const result = normalizePantry({ Lök: 3, Kyckling: { amount: 1, location: "frys" } });
  assert.equal(result.Lök.amount, 3);
  assert.equal(result.Kyckling.location, "frys");
});
test("pantryAmounts plattar ut till ren mängd-map för prisberäkning", () => {
  assert.deepEqual(pantryAmounts({ Lök: { amount: 3, location: "skafferi", expiry: null } }), { Lök: 3 });
});
test("matchLocalRecipesToPantry rankar recept med flest matchande ingredienser högst", () => {
  const recipes = [
    { id: "a", ingredienser: ["Lök", "Kycklingfilé", "Ris", "Curry & grönsaker"] },
    { id: "b", ingredienser: ["Lök", "Pasta"] },
    { id: "c", ingredienser: ["Räkor", "Vitlök"] },
  ];
  const matches = matchLocalRecipesToPantry(recipes, ["Lök", "Kycklingfilé", "Pasta"]);
  assert.deepEqual(matches.map(m => m.recipe.id), ["b", "a"]);
  assert.deepEqual(matches[0].matched, ["Lök", "Pasta"]);
});
test("matchLocalRecipesToPantry utesluter recept utan någon matchande ingrediens", () => {
  const recipes = [{ id: "a", ingredienser: ["Räkor"] }];
  assert.equal(matchLocalRecipesToPantry(recipes, ["Lök"]).length, 0);
});
test("expiryStatus klassificerar utgånget, snart och ok", () => {
  const today = new Date("2026-06-15");
  assert.equal(expiryStatus(null, today), null);
  assert.equal(expiryStatus("2026-06-10", today), "expired");
  assert.equal(expiryStatus("2026-06-17", today), "soon");
  assert.equal(expiryStatus("2026-07-01", today), "ok");
});
