import test from "node:test";
import assert from "node:assert/strict";
import { aggregateIngredients, budgetRemaining, calculateLiveShoppingTotal, calculateShoppingTotal, clampBudget, portionFactor } from "../frontend/app/src/services/calculations.js";

const recipes = [{ id: "pasta", ingredienser: ["Pasta", "Tomat"] }, { id: "soppa", ingredienser: ["Tomat"] }];
const quantities = { pasta: { Pasta: [250, "g"], Tomat: [1, "st"] }, soppa: { Tomat: [2, "st"] } };
const packages = { Pasta: { amount: 500, unit: "g" }, Tomat: { amount: 1, unit: "st" } };

test("portionsskalning ökar jämnt med antal personer, inte hoppvis var 4:e person", () => { assert.equal(portionFactor(4), 1); assert.equal(portionFactor(2), 0.5); assert.equal(portionFactor(8), 2); assert.equal(portionFactor(1), 0.25); assert.ok(portionFactor(2) < portionFactor(3), "fler personer ska alltid ge mer mat"); });
test("ingredienssummering", () => { const items = aggregateIngredients(recipes, quantities, packages, 5); assert.equal(items.find(item => item.namn === "Pasta").total, 312.5); assert.equal(items.find(item => item.namn === "Tomat").total, 3.75); });
test("shoppinglistans totalsumma använder hela paket och skafferi", () => { const items = aggregateIngredients([recipes[0]], quantities, packages, 4); assert.equal(calculateShoppingTotal(items, { Pasta: { pris: 20 }, Tomat: { pris: 5 } }, { Pasta: 100 }), 25); });
test("budgetberäkning", () => { assert.equal(budgetRemaining(500, 420), 80); assert.equal(budgetRemaining(400, 420), -20); });
test("budget klampas till 0 eller mer", () => { assert.equal(clampBudget(-100), 0); assert.equal(clampBudget("abc"), 0); assert.equal(clampBudget("650"), 650); });

test("live-totalsumma räknar aldrig en saknad pris (null) som 0 kr", () => {
  const items = [{ namn: "Citron", total: 1, package: null }, { namn: "Ris", total: 250, package: { amount: 1000 } }];
  const chainProducts = { Citron: { pris_kr: null }, Ris: { pris_kr: 28 } };
  const result = calculateLiveShoppingTotal(items, chainProducts);
  assert.equal(result.cost, 28, "endast Ris pris ska räknas in - Citrons null-pris ska inte tolkas som 0");
  assert.equal(result.matched, 2, "båda varorna hittade en produkt");
  assert.equal(result.certain, 1, "bara Ris har ett säkert pris");
  assert.equal(result.totalItems, 2);
});

test("live-totalsumma skiljer på 'ingen produkt hittad' och 'produkt hittad men pris saknas'", () => {
  const items = [{ namn: "Saffran", total: 1, package: null }, { namn: "Ris", total: 250, package: { amount: 1000 } }];
  // Saffran has no entry at all in chainProducts (no confident match found by best_match)
  const chainProducts = { Ris: { pris_kr: null } };
  const result = calculateLiveShoppingTotal(items, chainProducts);
  assert.equal(result.matched, 1, "bara Ris hittades alls som produkt");
  assert.equal(result.certain, 0, "Ris produkt hittades men saknar pris - inte säkert");
  assert.equal(result.cost, 0);
});

test("live-totalsumma räknar bort det som redan finns i skafferiet, precis som den statiska", () => {
  const items = [{ namn: "Ris", total: 500, package: { amount: 1000 } }];
  const chainProducts = { Ris: { pris_kr: 28 } };
  assert.equal(calculateLiveShoppingTotal(items, chainProducts, { Ris: 500 }).cost, 0, "500g behövs, 500g finns redan hemma");
});
