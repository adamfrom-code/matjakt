import test from "node:test";
import assert from "node:assert/strict";
import { filterRecipes, mergeRecipeResults } from "../frontend/src/services/recipe-search.js";

const recipes = [{ namn: "Krämig fiskpasta", typ: "Fisk", ingredienser: ["Torsk", "Citron"] }, { namn: "Linssoppa", typ: "Vegetarisk", ingredienser: ["Linser", "Morot"] }];
test("receptsökning matchar namn, kategori och ingrediens", () => { assert.equal(filterRecipes(recipes, "FISK").length, 1); assert.equal(filterRecipes(recipes, "citron")[0].namn, "Krämig fiskpasta"); assert.equal(filterRecipes(recipes, "vegetarisk")[0].namn, "Linssoppa"); });

test("mergeRecipeResults behåller tidigare valda recept även om de saknas i en ny sökning", () => {
  const retained = [{ id: "themealdb:1", namn: "Sparat recept" }];
  const fresh = [{ id: "themealdb:2", namn: "Nytt sökresultat" }];
  const merged = mergeRecipeResults(retained, fresh);
  assert.equal(merged.length, 2);
  assert.ok(merged.some(recipe => recipe.id === "themealdb:1"));
});

test("mergeRecipeResults dedupar på id", () => {
  const retained = [{ id: "themealdb:1", namn: "Gammal version" }];
  const fresh = [{ id: "themealdb:1", namn: "Ny version" }];
  const merged = mergeRecipeResults(retained, fresh);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].namn, "Gammal version");
});
