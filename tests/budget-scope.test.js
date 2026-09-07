import test from "node:test";
import assert from "node:assert/strict";
import { BUDGET_UTANFOR, budgetOmfattning, budgetScopeText } from "../frontend/app/src/services/budget-scope.js";

test("omfattningen namnger middagar och personer, inte 'veckan'", () => {
  assert.equal(budgetOmfattning(4, 2), "4 middagar för 2 personer");
  assert.equal(budgetOmfattning(7, 5), "7 middagar för 5 personer");
});

test("entalsformerna är rätt - 1 middag för 1 person, aldrig '1 personer'", () => {
  assert.equal(budgetOmfattning(1, 1), "1 middag för 1 person");
  assert.equal(budgetOmfattning(1, 3), "1 middag för 3 personer");
  assert.equal(budgetOmfattning(3, 1), "3 middagar för 1 person");
});

test("texten säger uttryckligen vad som INTE ingår", () => {
  // Hela poängen med U01: utan den här meningen läses 800 kr som hela
  // veckans mat, och appen ser dyr ut för att den räknade på annat.
  const text = budgetScopeText(4, 2);
  assert.match(text, /Frukost, lunch och hushållsvaror ingår inte\./);
  assert.ok(text.startsWith("Gäller 4 middagar för 2 personer."), text);
  assert.equal(BUDGET_UTANFOR, "Frukost, lunch och hushållsvaror ingår inte.");
});

test("trasiga värden ger ingen NaN-text i gränssnittet", () => {
  assert.equal(budgetOmfattning(undefined, null), "0 middagar för 0 personer");
  assert.equal(budgetOmfattning("3", "2"), "3 middagar för 2 personer");
  assert.equal(budgetOmfattning(-5, -1), "0 middagar för 0 personer");
});
