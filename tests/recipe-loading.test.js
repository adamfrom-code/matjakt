import test from "node:test";
import assert from "node:assert/strict";

// Modulkedjan går via api/config.js som läser <meta> för API-adressen, och
// recipes.js löser fallback-URL:en mot document.baseURI (bundelsäkert - se
// kommentaren där). Stubben måste därför likna ett riktigt document på båda
// punkterna; en halv stubb kraschade på "Invalid URL".
globalThis.document = { querySelector: () => null, baseURI: "http://localhost/app/" };
// Dynamisk import EFTER stubben, annars körs config.js först.
const { loadRecipe } = await import("../frontend/app/src/data/recipes.js");

function stubFetch(handler) {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return () => { globalThis.fetch = original; };
}

const jsonResponse = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

test("ett hittat recept returneras", async () => {
  const restore = stubFetch(async () => jsonResponse(200, { recipe: { id: "x", name: "X" } }));
  try {
    const recipe = await loadRecipe("x");
    assert.equal(recipe.id, "x");
    assert.equal(recipe.namn, "X");
  } finally { restore(); }
});

test("404 ger null - ett definitivt 'finns inte', inte ett fel", async () => {
  const restore = stubFetch(async () => jsonResponse(404, { error: "Receptet finns inte" }));
  try {
    assert.equal(await loadRecipe("borta"), null);
  } finally { restore(); }
});

test("ett nätfel KASTAS så anroparen kan försöka igen", async () => {
  const restore = stubFetch(async () => { throw new TypeError("Failed to fetch"); });
  try {
    await assert.rejects(() => loadRecipe("x"), /Failed to fetch/);
  } finally { restore(); }
});

test("ett serverfel kastas också - vi vet ingenting om receptet", async () => {
  const restore = stubFetch(async () => jsonResponse(500, {}));
  try {
    await assert.rejects(() => loadRecipe("x"), /HTTP 500/);
  } finally { restore(); }
});

test("statuskoden följer med felet så anroparen kan växla på orsak", async () => {
  const restore = stubFetch(async () => jsonResponse(503, {}));
  try {
    const error = await loadRecipe("x").catch(e => e);
    assert.equal(error.status, 503);
  } finally { restore(); }
});

test("ett svar utan recept-fält är också 'finns inte'", async () => {
  const restore = stubFetch(async () => jsonResponse(200, {}));
  try {
    assert.equal(await loadRecipe("x"), null);
  } finally { restore(); }
});
