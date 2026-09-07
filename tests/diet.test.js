import test from "node:test";
import assert from "node:assert/strict";
import { ALLERGENS, filterByDiet, mergeDiet } from "../frontend/app/src/services/diet.js";

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

// Hushållets allergier: fylls i per medlem och måste gälla hela veckan.
test("hushållets allergier läggs till enhetens egna", () => {
  const diet = mergeDiet({ kosttyp: "", avoidAllergens: new Set(["gluten"]) }, { allergies: ["Nötter", " skaldjur "] });
  assert.deepEqual([...diet.avoidAllergens].sort(), ["gluten", "nötter", "skaldjur"]);
  const kvar = filterByDiet([
    { id: "nöt", proteinkalla: "kyckling", allergener: ["nötter"] },
    { id: "ren", proteinkalla: "kyckling", allergener: [] },
  ], diet);
  assert.deepEqual(kvar.map(r => r.id), ["ren"], "en nöträtt får aldrig komma igenom");
});

test("kosttypen slås inte ihop - bara allergierna", () => {
  const diet = mergeDiet({ kosttyp: "", avoidAllergens: new Set() }, { allergies: [], dislikes: ["svamp"] });
  assert.equal(diet.kosttyp, "", "en vegetarian i hushållet gör inte hela veckan vegetarisk");
  assert.equal(diet.avoidAllergens.size, 0);
});

test("tomt hushåll ändrar ingenting", () => {
  const kost = { kosttyp: "vegetariskt", avoidAllergens: new Set(["laktos"]) };
  const diet = mergeDiet(kost, {});
  assert.equal(diet.kosttyp, "vegetariskt");
  assert.deepEqual([...diet.avoidAllergens], ["laktos"]);
  assert.notEqual(diet.avoidAllergens, kost.avoidAllergens, "originalet får inte muteras");
});

test("dubbletter och tomma värden städas bort", () => {
  const diet = mergeDiet({ avoidAllergens: ["nötter"] }, { allergies: ["nötter", "", "  ", "NÖTTER"] });
  assert.deepEqual([...diet.avoidAllergens], ["nötter"]);
});

