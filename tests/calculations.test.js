import test from "node:test";
import assert from "node:assert/strict";
import { aggregateIngredients, budgetRemaining, calculateShoppingTotal, clampBudget, portionFactor } from "../frontend/src/services/calculations.js";

const recipes = [{ id: "pasta", ingredienser: ["Pasta", "Tomat"] }, { id: "soppa", ingredienser: ["Tomat"] }];
const quantities = { pasta: { Pasta: [250, "g"], Tomat: [1, "st"] }, soppa: { Tomat: [2, "st"] } };
const packages = { Pasta: { amount: 500, unit: "g" }, Tomat: { amount: 1, unit: "st" } };

test("portionsskalning ökar jämnt med antal personer, inte hoppvis var 4:e person", () => { assert.equal(portionFactor(4), 1); assert.equal(portionFactor(2), 0.5); assert.equal(portionFactor(8), 2); assert.equal(portionFactor(1), 0.25); assert.ok(portionFactor(2) < portionFactor(3), "fler personer ska alltid ge mer mat"); });
test("ingredienssummering", () => { const items = aggregateIngredients(recipes, quantities, packages, 5); assert.equal(items.find(item => item.namn === "Pasta").total, 312.5); assert.equal(items.find(item => item.namn === "Tomat").total, 3.75); });
test("shoppinglistans totalsumma använder hela paket och skafferi", () => { const items = aggregateIngredients([recipes[0]], quantities, packages, 4); assert.equal(calculateShoppingTotal(items, { Pasta: { pris: 20 }, Tomat: { pris: 5 } }, { Pasta: 100 }), 25); });
test("budgetberäkning", () => { assert.equal(budgetRemaining(500, 420), 80); assert.equal(budgetRemaining(400, 420), -20); });
test("budget klampas till 0 eller mer", () => { assert.equal(clampBudget(-100), 0); assert.equal(clampBudget("abc"), 0); assert.equal(clampBudget("650"), 650); });
