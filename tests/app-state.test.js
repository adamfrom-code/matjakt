// Tillståndet: veckoplanen, sparningen och kontosynken.
//
// Testerna nedan är acceptanskriterierna för E2 (dagsindex), E3 (version,
// migrering och full enhet) och E4 (serverns blob är inte mer betrodd än
// enhetens). Modulen känner varken till DOM eller nät, så de körs i Node.
import test from "node:test";
import assert from "node:assert/strict";
import {
  SCHEMA_VERSION, STORAGE_FULL_TEXT, addToWeekPlan, applySyncBlob, buildSyncPayload,
  initAppState, normalizeState, removeFromWeekPlan, saveState, selectedRecipes,
  setWeekPlan, state, swapWeekPlanDay,
} from "../frontend/app/src/state/app-state.js";

function memoryStorage(initial = null) {
  let value = initial;
  return { getItem: () => value, setItem: (_key, next) => { value = next; }, read: () => value };
}

// En lagring som är full: setItem kastar, precis som iOS Safari vid 5 MB.
function fullStorage() {
  return { getItem: () => null, setItem: () => { throw new Error("QuotaExceededError"); } };
}

const RECEPT = [
  { id: "linssoppa", namn: "Linssoppa" },
  { id: "fiskpasta", namn: "Fiskpasta" },
  { id: "korvgryta", namn: "Korvgryta" },
];

function start({ storage = memoryStorage(), ...rest } = {}) {
  initAppState({ storage, recipeBank: RECEPT, ...rest });
  return storage;
}

// ---- E2: dagsindex --------------------------------------------------------

test("E2: ett saknat recept blir en tom dag - det förskjuter inte de följande", () => {
  start();
  setWeekPlan(["linssoppa", "borttaget-recept", "korvgryta"]);
  const dagar = selectedRecipes();
  assert.equal(dagar.length, 3);
  assert.equal(dagar[0].id, "linssoppa");
  assert.equal(dagar[1], null, "den saknade dagen ska vara tom, inte borta");
  assert.equal(dagar[2].id, "korvgryta", "onsdagens rätt ska ligga kvar på onsdagen");
});

test("E2: bytesrutans dagsindex och renderingens är samma indexrymd", () => {
  start();
  setWeekPlan(["linssoppa", "borttaget-recept", "korvgryta"]);
  // Så här räknar openSwapModal fram dagen: i den OFILTRERADE weekPlan.
  const dayIndex = state.weekPlan.indexOf("korvgryta");
  assert.equal(dayIndex, 2);
  assert.equal(selectedRecipes()[dayIndex].id, "korvgryta");
  swapWeekPlanDay(dayIndex, "fiskpasta");
  assert.deepEqual(state.weekPlan, ["linssoppa", "borttaget-recept", "fiskpasta"]);
  assert.equal(selectedRecipes()[2].id, "fiskpasta", "bytet landade på den dag användaren pekade på");
  assert.equal(selectedRecipes()[1], null, "den tomma dagen är kvar som tom");
});

test("veckoplanen: lägg till, ta bort och byt ut hela veckan", () => {
  start();
  setWeekPlan(["linssoppa"]);
  addToWeekPlan("fiskpasta");
  addToWeekPlan("fiskpasta");                       // idempotent
  assert.deepEqual(state.weekPlan, ["linssoppa", "fiskpasta"]);
  assert.ok(state.valda.has("fiskpasta"));
  removeFromWeekPlan("linssoppa");
  assert.deepEqual(state.weekPlan, ["fiskpasta"]);
  assert.equal(state.valda.has("linssoppa"), false);
  setWeekPlan(["korvgryta"]);
  assert.deepEqual(state.weekHistory[0].plan, ["fiskpasta"], "den ersatta veckan hamnar i papperskorgen");
});

// ---- E3: version, migrering och full enhet --------------------------------

test("E3: den sparade blobben bär sin schemaversion", () => {
  const storage = start();
  setWeekPlan(["linssoppa"]);
  saveState();
  const sparat = JSON.parse(storage.read());
  assert.equal(sparat.schemaVersion, SCHEMA_VERSION);
  assert.deepEqual(sparat.weekPlan, ["linssoppa"]);
});

test("E3: en blob utan version läses som version 0 och normaliseras ändå", () => {
  const utan = normalizeState({ budget: 725, weekPlan: ["linssoppa"] });
  assert.equal(utan.schemaVersion, 0);
  assert.equal(utan.budget, 725);
  const med = normalizeState({ schemaVersion: SCHEMA_VERSION, budget: 725 });
  assert.equal(med.schemaVersion, SCHEMA_VERSION);
});

test("E3: en full enhet säger det rakt ut i stället för 'Sparat på den här enheten'", () => {
  const status = [];
  initAppState({ storage: fullStorage(), recipeBank: RECEPT,
                 onSyncStatus: (läge, text) => status.push([läge, text]) });
  assert.equal(saveState(), false, "saveState ska berätta att skrivningen misslyckades");
  assert.deepEqual(status.at(-1), ["error", STORAGE_FULL_TEXT]);
});

test("E3: en lyckad sparning säger ingenting om full lagring", () => {
  const status = [];
  initAppState({ storage: memoryStorage(), recipeBank: RECEPT,
                 onSyncStatus: (läge, text) => status.push([läge, text]) });
  assert.equal(saveState(), true);
  assert.equal(status.some(([, text]) => text === STORAGE_FULL_TEXT), false);
});

test("E3: trasigt lagrat tillstånd nollställer inte appen till något ogiltigt", () => {
  start({ storage: memoryStorage("{trasigt") });
  assert.equal(state.budget, 800);
  assert.equal(state.personer, 2);
  assert.deepEqual(state.weekPlan, []);
  assert.ok(state.valda instanceof Set);
});

test("E3: en lagrad blob med fel typer faller tillbaka på standardvärdena", () => {
  start({ storage: memoryStorage(JSON.stringify({
    weekPlan: { mandag: "linssoppa" },     // objekt, inte lista
    favoriter: "linssoppa",                // sträng, inte lista
    personer: 99,
    pantry: [],                            // lista, inte objekt
  })) });
  assert.deepEqual(state.weekPlan, []);
  assert.equal(state.favoriter.size, 0);
  assert.equal(state.personer, 12);
  assert.deepEqual(state.pantry, {});
});

// ---- E4: serverns blob är inte mer betrodd än enhetens --------------------

test("E4: en gammal serverblob med weekPlan som objekt kan inte krascha synken", () => {
  start();
  setWeekPlan(["linssoppa", "fiskpasta"]);
  applySyncBlob({ weekPlan: { "0": "linssoppa" }, personer: 40, budget: "mycket" });
  assert.deepEqual(state.weekPlan, ["linssoppa", "fiskpasta"], "ogiltigt fält lämnar det som redan finns ifred");
  assert.equal(state.personer, 12, "personer klampas i BÅDA vägarna, inte bara på boot");
  assert.equal(state.budget, 800, "en budget som inte är ett tal skrivs inte in");
  // Och veckan går fortfarande att rita: det var .map på ett objekt som förr
  // kastade TypeError, med pullAccountStates catch {} som svalde felet.
  assert.equal(selectedRecipes().length, 2);
});

test("E4: en giltig serverblob skrivs in som vanligt", () => {
  start();
  applySyncBlob({
    schemaVersion: SCHEMA_VERSION, budget: 1200, personer: 4,
    weekPlan: ["korvgryta"], valda: ["korvgryta"], harHemma: ["Ris"],
    kost: { kosttyp: "vegetariskt", avoidAllergens: ["gluten"] },
    pantry: { Ris: 500 },
  });
  assert.equal(state.budget, 1200);
  assert.equal(state.personer, 4);
  assert.deepEqual(state.weekPlan, ["korvgryta"]);
  assert.ok(state.harHemma.has("Ris"));
  assert.equal(state.kost.kosttyp, "vegetariskt");
  assert.ok(state.kost.avoidAllergens.has("gluten"));
  assert.equal(state.pantry.Ris.amount, 500);
});

test("E4: en historikpost utan sin vecka slängs - restorePreviousWeek kastar på den", () => {
  start();
  applySyncBlob({ weekHistory: [{ plan: ["linssoppa"] }, { savedAt: 1 }, "skräp"] });
  assert.equal(state.weekHistory.length, 1);
  assert.deepEqual(state.weekHistory[0].plan, ["linssoppa"]);
});

test("payloaden ut är samma fält som förut, plus versionen", () => {
  start();
  setWeekPlan(["linssoppa"]);
  state.avklarade.add("Pasta");
  const payload = buildSyncPayload();
  assert.equal(payload.schemaVersion, SCHEMA_VERSION);
  assert.deepEqual(payload.avklarade, ["Pasta"]);
  assert.deepEqual(payload.valda, ["linssoppa"]);
  assert.equal(payload.authToken, undefined, "token bor i sin egen nyckel och får aldrig följa med");
});
