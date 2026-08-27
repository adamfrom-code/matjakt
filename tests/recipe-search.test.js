import test from "node:test";
import assert from "node:assert/strict";
import { filterRecipes } from "../frontend/src/services/recipe-search.js";

const recipes = [{ namn: "Krämig fiskpasta", typ: "Fisk", ingredienser: ["Torsk", "Citron"] }, { namn: "Linssoppa", typ: "Vegetarisk", ingredienser: ["Linser", "Morot"] }];
test("receptsökning matchar namn, kategori och ingrediens", () => { assert.equal(filterRecipes(recipes, "FISK").length, 1); assert.equal(filterRecipes(recipes, "citron")[0].namn, "Krämig fiskpasta"); assert.equal(filterRecipes(recipes, "vegetarisk")[0].namn, "Linssoppa"); });
