import test from "node:test";
import assert from "node:assert/strict";
import { comboProtein, comboVariety, inBudgetPool, limitCandidatePool, pickBalanced, pickCheapest, pickProtein } from "../frontend/app/src/services/planning.js";

const cheapVeg = { id: "cheapveg", proteinkalla: "vegetariskt", protein: 10, inkopspris: 50 };
const cheapVeg2 = { id: "cheapveg2", proteinkalla: "vegetariskt", protein: 12, inkopspris: 55 };
const midFish = { id: "midfish", proteinkalla: "fisk", protein: 30, inkopspris: 90 };
const pricyMeat = { id: "pricymeat", proteinkalla: "notkott", protein: 40, inkopspris: 200 };

test("pickCheapest picks the lowest-cost combo regardless of variety or protein", () => {
  const pool = [
    { combo: [cheapVeg, cheapVeg2], cost: 100 },
    { combo: [midFish, pricyMeat], cost: 250 },
  ];
  const best = pickCheapest(pool);
  assert.equal(best.cost, 100);
});

test("pickBalanced prefers protein-source variety over the raw-cheapest combo when the price gap is small", () => {
  const cheapestSameCategory = { combo: [cheapVeg, cheapVeg2], cost: 100 };
  const variedNearCheapest = { combo: [cheapVeg, midFish], cost: 120 }; // within the 1.35x band of 100
  const pool = [cheapestSameCategory, variedNearCheapest];
  const best = pickBalanced(pool, 500);
  assert.equal(best, variedNearCheapest, "balanced should pick the more varied combo, not just the cheapest");
  assert.equal(comboVariety(best.combo), 2);
});

test("pickBalanced does not chase variety far outside the cheapest combo's price band", () => {
  const cheapestSameCategory = { combo: [cheapVeg, cheapVeg2], cost: 100 };
  const variedButFarPricier = { combo: [midFish, pricyMeat], cost: 400 }; // way outside 1.35x of 100
  const pool = [cheapestSameCategory, variedButFarPricier];
  const best = pickBalanced(pool, 500);
  assert.equal(best, cheapestSameCategory, "balanced should not pick a combo far outside the cheapest's price band just for variety");
});

test("pickProtein picks the highest-protein combo even when it costs more", () => {
  const lowProtein = { combo: [cheapVeg, cheapVeg2], cost: 100 };
  const highProtein = { combo: [midFish, pricyMeat], cost: 250 };
  const pool = [lowProtein, highProtein];
  const best = pickProtein(pool);
  assert.equal(best, highProtein);
  assert.equal(comboProtein(best.combo), 70);
});

test("the three objectives can genuinely disagree on the same pool", () => {
  const pool = [
    { combo: [cheapVeg, cheapVeg2], cost: 100 },
    { combo: [cheapVeg, midFish], cost: 120 },
    { combo: [midFish, pricyMeat], cost: 250 },
  ];
  const cheapest = pickCheapest(pool);
  const balanced = pickBalanced(pool, 500);
  const protein = pickProtein(pool);
  assert.notEqual(cheapest, protein, "cheapest and protein plans should differ");
  assert.notEqual(cheapest, balanced, "cheapest and balanced plans should differ when a varied option is nearly as cheap");
});

test("inBudgetPool falls back to the full pool only when nothing fits budget", () => {
  const pool = [{ combo: [cheapVeg], cost: 100 }, { combo: [midFish], cost: 300 }];
  assert.deepEqual(inBudgetPool(pool, 150), [pool[0]]);
  assert.deepEqual(inBudgetPool(pool, 10), pool);
});

test("limitCandidatePool keeps representation from every category instead of only the globally cheapest", () => {
  const manyVeg = Array.from({ length: 30 }, (_, i) => ({ id: `veg${i}`, proteinkalla: "vegetariskt", inkopspris: 40 + i }));
  const oneFish = { id: "fisk1", proteinkalla: "fisk", inkopspris: 500 };
  const oneMeat = { id: "meat1", proteinkalla: "notkott", inkopspris: 600 };
  const catalog = [...manyVeg, oneFish, oneMeat];
  const limited = limitCandidatePool(catalog, 6, 24);
  assert.ok(limited.some(r => r.id === "fisk1"), "fisk category must survive the cap even though it is pricier");
  assert.ok(limited.some(r => r.id === "meat1"), "notkott category must survive the cap even though it is pricier");
  assert.ok(limited.length <= 24);
});

// =============================================================================
// Regression: "Skapa min vecka" kraschade när poolen svalt veckan
// =============================================================================
// A 7-dinner week whose candidates all share one protein source: the
// 6-per-category cap produced a 6-recipe pool, C(6,7) built zero combos, and
// pickBalanced read .cost off null - the button died with a TypeError and no
// week was ever created. Found live in the browser, not by a test, which is
// why these exist now.
test("pickBalanced tål en tom pool", () => {
  assert.equal(pickBalanced([], 800), null);
});

test("poolbegränsningen svälter aldrig veckan", () => {
  const recipes = Array.from({ length: 30 }, (_, i) => ({
    id: `r${i}`, proteinkalla: "vego", inkopspris: 50 + i,
  }));
  const pool = limitCandidatePool(recipes, 6, 18, "proteinkalla", "inkopspris", 8);
  assert.ok(pool.length >= 8, `poolen har ${pool.length} recept, veckan behöver 8`);
});
