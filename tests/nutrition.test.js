import test from "node:test";
import assert from "node:assert/strict";
import { filterByNutritionGoals, hasActiveNutritionGoals } from "../frontend/src/services/nutrition.js";

const recipes = [
  { id: "a", kcal: 638, protein: 48, kolhydrater: 67, fett: 18, proteinkalla: "kyckling" },
  { id: "b", kcal: 300, protein: 10, kolhydrater: 20, fett: 5, proteinkalla: "vegetariskt" },
  { id: "c", kcal: 700, protein: 50, kolhydrater: 80, fett: 30, proteinkalla: "fisk" },
  { id: "d", kcal: 620, protein: 46, kolhydrater: 40, fett: 12, proteinkalla: "kyckling" },
];

test("inga mål satta ger tillbaka alla recept oförändrat", () => {
  assert.deepEqual(filterByNutritionGoals(recipes, null), recipes);
  assert.deepEqual(filterByNutritionGoals(recipes, {}), recipes);
});

test("kcal-intervall filtrerar bort recept utanför spannet", () => {
  const result = filterByNutritionGoals(recipes, { kcalMin: 600, kcalMax: 690 });
  assert.deepEqual(result.map(r => r.id), ["a", "d"]);
});

test("protein-minimum och kcal-intervall kombineras (budget+makro samtidigt)", () => {
  const result = filterByNutritionGoals(recipes, { kcalMin: 600, kcalMax: 700, proteinMin: 45 });
  assert.deepEqual(result.map(r => r.id), ["a", "c", "d"]);
  const strict = filterByNutritionGoals(recipes, { kcalMin: 600, kcalMax: 700, proteinMin: 49 });
  assert.deepEqual(strict.map(r => r.id), ["c"]);
});

test("proteinkälla-filter matchar bara valda källor", () => {
  const result = filterByNutritionGoals(recipes, { proteinSources: new Set(["fisk", "vegetariskt"]) });
  assert.deepEqual(result.map(r => r.id), ["b", "c"]);
});

test("recept utan näringsdata exkluderas när ett näringsmål är aktivt", () => {
  const withUnknown = [...recipes, { id: "e", kcal: null }];
  const result = filterByNutritionGoals(withUnknown, { kcalMin: 0 });
  assert.ok(!result.some(r => r.id === "e"));
});

test("hasActiveNutritionGoals känner igen satta respektive tomma mål", () => {
  assert.equal(hasActiveNutritionGoals(null), false);
  assert.equal(hasActiveNutritionGoals({}), false);
  assert.equal(hasActiveNutritionGoals({ proteinSources: new Set() }), false);
  assert.equal(hasActiveNutritionGoals({ kcalMin: 500 }), true);
  assert.equal(hasActiveNutritionGoals({ proteinSources: new Set(["fisk"]) }), true);
});
