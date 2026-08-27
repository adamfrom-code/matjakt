import test from "node:test";
import assert from "node:assert/strict";
import { aggregateIngredients, budgetRemaining, calculateShoppingTotal, portionFactor } from "../frontend/src/services/calculations.js";

const recipes = [{ id: "pasta", ingredienser: ["Pasta", "Tomat"] }, { id: "soppa", ingredienser: ["Tomat"] }];
const quantities = { pasta: { Pasta: [250, "g"], Tomat: [1, "st"] }, soppa: { Tomat: [2, "st"] } };
const packages = { Pasta: { amount: 500, unit: "g" }, Tomat: { amount: 1, unit: "st" } };

test("portionsskalning", () => { assert.equal(portionFactor(4), 1); assert.equal(portionFactor(5), 2); });
test("ingredienssummering", () => { const items = aggregateIngredients(recipes, quantities, packages, 5); assert.equal(items.find(item => item.namn === "Pasta").total, 500); assert.equal(items.find(item => item.namn === "Tomat").total, 6); });
test("shoppinglistans totalsumma använder hela paket och skafferi", () => { const items = aggregateIngredients([recipes[0]], quantities, packages, 4); assert.equal(calculateShoppingTotal(items, { Pasta: { pris: 20 }, Tomat: { pris: 5 } }, { Pasta: 100 }), 25); });
test("budgetberäkning", () => { assert.equal(budgetRemaining(500, 420), 80); assert.equal(budgetRemaining(400, 420), -20); });
