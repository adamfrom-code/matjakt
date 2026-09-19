// Z2: "Laga med det jag har" frågar banken (Z1) bakom flaggan skafferi.laga-nu.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.document = { querySelector: () => null, baseURI: "http://localhost/app/" };
const { searchRecipes } = await import("../frontend/app/src/data/recipes.js");
const läs = rel => readFileSync(new URL(`../${rel}`, import.meta.url), "utf8");

test("searchRecipes skickar en ingredient per vara och tiden, och behåller matchedIngredients", async () => {
  const original = globalThis.fetch;
  let url = "";
  globalThis.fetch = async (u) => { url = String(u); return { ok: true, status: 200, json: async () => ({ recipes: [
    { id: "a", name: "Tomatsoppa", servings: 4, nutrition: {}, ingredients: [], instructions: [], tags: [], matchedIngredients: ["Tomater", "Gul lök"] },
  ] }) }; };
  try {
    const hits = await searchRecipes({ ingredients: ["lök", "tomat", ""], maxTime: 20, limit: 12 });
    const params = new URL(url, "http://localhost").searchParams;
    assert.deepEqual(params.getAll("ingredient"), ["lök", "tomat"]);
    assert.equal(params.get("maxTime"), "20");
    assert.equal(params.get("limit"), "12");
    assert.equal(hits[0].namn, "Tomatsoppa");
    assert.deepEqual(hits[0].matchedIngredients, ["Tomater", "Gul lök"]);
  } finally {
    globalThis.fetch = original;
  }
});

test("utan ingredienser skickas ingen ingredient-parameter (sökningen är som förut)", async () => {
  const original = globalThis.fetch;
  let url = "";
  globalThis.fetch = async (u) => { url = String(u); return { ok: true, status: 200, json: async () => ({ recipes: [] }) }; };
  try {
    await searchRecipes({ query: "soppa" });
    assert.deepEqual(new URL(url, "http://localhost").searchParams.getAll("ingredient"), []);
  } finally {
    globalThis.fetch = original;
  }
});

test("app.js frågar banken bara bakom flaggan, snävar till kostfiltret och har ett tidsval", () => {
  const appJs = läs("frontend/app/app.js");
  const start = appJs.indexOf("async function serverMatchesForPantry");
  assert.notEqual(start, -1);
  const body = appJs.slice(start, appJs.indexOf("async function openCookModal"));
  assert.match(body, /localRecipesForUser\(\)\.map\(recipe => \[recipe\.id, recipe\]\)/, "kost-/allergifiltret gäller även serverns svar");
  assert.match(body, /searchRecipes\(\{ ingredients: pantryNames, maxTime, limit: 12 \}\)/);
  assert.match(body, /hits\.filter\(hit => tillatna\.has\(hit\.id\)\)/);
  const modal = appJs.slice(appJs.indexOf("async function openCookModal"), appJs.indexOf("function closeCookModal"));
  assert.match(modal, /const lagaNu = flagga\("skafferi\.laga-nu"\)/);
  assert.match(modal, /filters\.hidden = !lagaNu/);
  assert.match(modal, /if \(lagaNu && pantryNames\.length\)/);
  assert.match(appJs, /\$\("cookMaxTime"\)\?\.addEventListener\("change"/);
  assert.match(läs("frontend/app/index.html"), /<div id="cookFilters" hidden>/);
});
