import test from "node:test";
import assert from "node:assert/strict";
import { createDebouncedSearch, filterRecipes, mergeRecipeResults } from "../frontend/app/src/services/recipe-search.js";

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

// ---- E15 (3): promises som aldrig settlade -------------------------------
//
// Varje tangenttryck skapade en ny promise, och clearTimeout tog bort det
// enda som någonsin kunde settla den föregående: sökningen som aldrig blev
// av. Kvar låg promisen med hela sin closure för resten av besöket - tre fält
// i appen använder den här, så en stunds skrivande lämnade hundratals.
//
// Att en promise läcker syns inte i minnet från ett test. Det som GÅR att
// pröva är villkoret som gör läckan möjlig: settlar den föregående eller
// inte? Det är samma sak, och det är det anroparna beror på.

// En promise som settlar noteras; en som inte gör det syns som "väntar".
function track(promise) {
  const record = { state: "väntar", reason: null };
  promise.then(() => { record.state = "löst"; }, error => { record.state = "avbruten"; record.reason = error; });
  return record;
}

// En riktig timertick: debouncen är byggd på setTimeout, så det är den kön
// som måste få vända innan något har hänt.
const flush = () => new Promise(resolve => setTimeout(resolve, 1));

test("E15: den övergivna sökningen settlar i stället för att bli kvar", async () => {
  const search = createDebouncedSearch(query => Promise.resolve(query), 0);
  const först = track(search("kor"));
  const sedan = track(search("korv"));
  await flush();
  assert.equal(först.state, "avbruten", "den övergivna promisen måste settla - annars frigörs den aldrig");
  assert.equal(först.reason?.name, "AbortError", "anroparna skiljer redan på AbortError och riktiga fel");
  await flush();
  assert.equal(sedan.state, "löst", "den sista sökningen är den som ska svara");
});

test("E15: tio tangenttryck lämnar noll väntande promises", async () => {
  const search = createDebouncedSearch(query => Promise.resolve(query), 0);
  const alla = "korvstroganoff".slice(0, 10).split("").map((_, i) => track(search("korvstroganoff".slice(0, i + 1))));
  await flush();
  await flush();
  assert.equal(alla.filter(entry => entry.state === "väntar").length, 0, "ingen enda får bli kvar");
  assert.equal(alla.filter(entry => entry.state === "löst").length, 1, "exakt den sista svarar");
  assert.ok(alla.slice(0, -1).every(entry => entry.reason?.name === "AbortError"));
});

test("E15: en sökning som HUNNIT starta settlar via sitt eget svar", async () => {
  const search = createDebouncedSearch(query => Promise.resolve(`svar:${query}`), 0);
  const ensam = track(search("linssoppa"));
  await flush();
  await flush();
  assert.equal(ensam.state, "löst");
});

test("E15: ett riktigt fel är fortfarande ett riktigt fel", async () => {
  const search = createDebouncedSearch(() => Promise.reject(new Error("HTTP 500")), 0);
  const svar = track(search("korv"));
  await flush();
  await flush();
  assert.equal(svar.state, "avbruten");
  assert.equal(svar.reason.message, "HTTP 500", "servern som svarar 500 får inte maskeras som ett avbrott");
  assert.notEqual(svar.reason.name, "AbortError");
});

test("E15: den pågående sökningen avbryts fortfarande med sin signal", async () => {
  const signaler = [];
  const search = createDebouncedSearch((query, signal) => { signaler.push(signal); return new Promise(() => {}); }, 0);
  search("kor");
  await flush();
  search("korv");
  await flush();
  assert.equal(signaler.length, 2);
  assert.equal(signaler[0].aborted, true, "det påbörjade nätanropet ska avbrytas, som förut");
  assert.equal(signaler[1].aborted, false);
});
