import test from "node:test";
import assert from "node:assert/strict";
import { ALLERGENS, filterByDiet } from "../frontend/app/src/services/diet.js";

const recipes = [
  { id: "a", proteinkalla: "kyckling", allergener: ["gluten"] },
  { id: "b", proteinkalla: "vegetariskt", allergener: ["laktos"] },
  { id: "c", proteinkalla: "veganskt", allergener: [] },
  { id: "d", proteinkalla: "fisk", allergener: ["fisk", "gluten"] },
];

test("ingen kosttyp eller allergi vald returnerar allt", () => {
  assert.equal(filterByDiet(recipes, {}).length, 4);
  assert.equal(filterByDiet(recipes).length, 4);
});
test("vegetariskt inkluderar både vegetariska och veganska recept", () => {
  const result = filterByDiet(recipes, { kosttyp: "vegetariskt" });
  assert.deepEqual(result.map(r => r.id), ["b", "c"]);
});
test("veganskt visar bara veganska recept", () => {
  const result = filterByDiet(recipes, { kosttyp: "veganskt" });
  assert.deepEqual(result.map(r => r.id), ["c"]);
});
test("undviker recept som innehåller en vald allergen", () => {
  const result = filterByDiet(recipes, { avoidAllergens: new Set(["gluten"]) });
  assert.deepEqual(result.map(r => r.id), ["b", "c"]);
});
test("kombinerar kosttyp och allergenfilter", () => {
  const result = filterByDiet(recipes, { kosttyp: "vegetariskt", avoidAllergens: new Set(["laktos"]) });
  assert.deepEqual(result.map(r => r.id), ["c"]);
});

// Säkerhetskritiskt (RC-audit 2026-09-01): ett recept märkt "mjölk" får
// ALDRIG passera ett laktos-filter för att orden skiljer, och en vegetarian
// får aldrig en tom lista för att bankens taggar blev samlingsordet "vego".
test("allergen-synonymer fångas: mjölk är laktos, blötdjur är skaldjur", () => {
  const bank = [
    { proteinkalla: "vegetariskt", allergener: ["mjölk"] },
    { proteinkalla: "veganskt", allergener: ["blötdjur"] },
    { proteinkalla: "kött", allergener: ["laktos"] },
  ];
  assert.equal(filterByDiet(bank, { kosttyp: "vegetariskt" }).length, 2);
  assert.equal(filterByDiet(bank, { avoidAllergens: ["laktos"] }).length, 1);
  assert.equal(filterByDiet(bank, { avoidAllergens: ["skaldjur"] }).length, 2);
  assert.ok(ALLERGENS.includes("jordnötter") && ALLERGENS.includes("sesam"));
});
