// P03a: reservbanken översätts av SAMMA fromApi() som serversvaret.
//
// Filen frontend/app/data/recipes.json är API-formen, genererad ur källorna
// av backend/scripts/generate_recipe_fallback.py. Det här testet bevisar
// den andra halvan av kontraktet: att appen kan läsa den formen och får ut
// exakt det den får ut av ett serversvar - svenska fältnamn, kcal, portioner
// - och att inget påhittat följer med (butik, sparar, emoji fanns i den gamla
// handredigerade filen och såg ut som pris- och butiksdata).
//
// Byte-för-byte-grinden mot källorna ligger i backend/tests/
// test_receptsanningen.py. Här prövas översättningen, inte innehållet.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const rot = new URL("..", import.meta.url);
const bank = JSON.parse(readFileSync(new URL("frontend/app/data/recipes.json", rot), "utf8"));

// Modulkedjan går via api/config.js, som läser <meta> ur document vid
// import, och recipes.js löser fallback-URL:en mot document.baseURI. Samma
// stubb som recipe-loading.test.js - en halv stubb kraschar på "Invalid URL".
globalThis.document = { querySelector: () => null, baseURI: "http://localhost/app/" };

// fromApi är inte exporterad - loadRecipes() är vägen in. Fejka ett
// backendavbrott (första fetch kastar) så att reservbanken läses, exakt
// som i drift.
async function viaReservbanken() {
  const original = globalThis.fetch;
  globalThis.fetch = async (url) => {
    // API-anropet är /recipes?limit=500; reservbanken är data/recipes.json.
    // Båda innehåller "/recipes" - skilj dem på filändelsen, annars kastar
    // stubben även för reservbanken och testet mäter ingenting.
    if (!String(url).endsWith("recipes.json")) throw new TypeError("Failed to fetch");
    return { ok: true, status: 200, json: async () => bank };
  };
  try {
    const { loadRecipes } = await import("../frontend/app/src/data/recipes.js");
    return await loadRecipes();
  } finally {
    globalThis.fetch = original;
  }
}

test("reservbanken är API-formen, inte appens", () => {
  assert.ok(bank.length > 200, `bara ${bank.length} recept`);
  for (const r of bank.slice(0, 5)) {
    assert.ok("name" in r && "servings" in r && "nutrition" in r, `${r.id} saknar API-fält`);
    assert.ok(!("namn" in r), `${r.id} har handredigerats tillbaka till appens form`);
  }
});

test("reservbanken läses genom fromApi och blir appens form", async () => {
  const recept = await viaReservbanken();
  assert.equal(recept.length, bank.length);
  const r = recept.find(x => x.id === "kottbullar-potatismos");
  assert.ok(r, "kottbullar-potatismos saknas");
  assert.equal(r.namn, "Köttbullar med potatismos och lingon");
  assert.equal(r.kcal, 640);          // källans värde - reservbanken sa 527
  assert.equal(r.portioner, 4);
  assert.equal(r.mealType, "middag");
  assert.ok(Array.isArray(r.ingredienser) && r.ingredienser.length > 0);
  assert.ok(Array.isArray(r.tags));
});

test("inget påhittat följer med", async () => {
  const recept = await viaReservbanken();
  for (const r of recept) {
    assert.equal(r.butik, undefined, `${r.id} bär ett påhittat butiksval`);
    assert.equal(r.sparar, undefined, `${r.id} bär en påhittad besparing`);
    assert.equal(r.emoji, undefined);
  }
});

test("ett tomt serversvar faller också tillbaka - genom samma översättning", async () => {
  // Felet i auditen: `data.recipes.length` falskt -> reservbanken. Den vägen
  // måste ge samma form som nätfelsvägen.
  const original = globalThis.fetch;
  globalThis.fetch = async (url) =>
    String(url).endsWith("recipes.json")
      ? { ok: true, status: 200, json: async () => bank }
      : { ok: true, status: 200, json: async () => ({ recipes: [] }) };
  try {
    const { loadRecipes } = await import("../frontend/app/src/data/recipes.js");
    const recept = await loadRecipes();
    assert.equal(recept.length, bank.length);
    assert.equal(recept[0].namn, bank[0].name);
  } finally {
    globalThis.fetch = original;
  }
});
