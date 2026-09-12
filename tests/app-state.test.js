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

// ---- E16: en blob är en ögonblicksbild, inte ett facit -------------------
//
// Hämtningen av kontots blob väntas inte in någonstans (boot-radens
// refreshUser, premiumpollen) och kan landa långt efter att den här enheten
// skrivit nyare saker. Båda fallen nedan sänkte browser-E2E:n omväxlande och
// gick igenom vid omkörning - det som saknades var inte en längre timeout
// utan en regel om vilken av två bilder som är den äldre.

test("E16: en blob från före onboardingen skriver inte över svaren som just ges", () => {
  start();
  // Användaren står i rutan och har skrivit sitt eget svar. Blobben på
  // servern är från innan hon började: standardbudget, tomt postnummer.
  state.budget = 900;
  state.postnummer = "80252";
  const skrevs = applySyncBlob({ budget: 800, postnummer: "", onboardingComplete: false },
                               { onboardingOpen: true });
  assert.equal(skrevs, false, "blobben är äldre än svaren och ska inte skrivas in");
  assert.equal(state.budget, 900, "budgeten användaren skrev står kvar");
  assert.equal(state.postnummer, "80252");
});

test("E16: inte heller när rutan hunnit stängas innan svaret kom", () => {
  start();
  // "Skapa min vecka" har gjort sitt och rutan är borta. Blobben begärdes
  // medan den stod öppen, och anroparen bär med sig det - annars vore det
  // ögonblick veckan skapas i det enda som saknade skydd.
  state.budget = 900;
  state.onboardingComplete = true;
  setWeekPlan(["linssoppa", "korvgryta"]);
  const skrevs = applySyncBlob({ budget: 800, onboardingComplete: false, weekPlan: [] },
                               { onboardingOpen: true });
  assert.equal(skrevs, false);
  assert.equal(state.budget, 900);
  assert.equal(state.onboardingComplete, true);
  assert.deepEqual(state.weekPlan, ["linssoppa", "korvgryta"], "veckan som just skapades står kvar");
});

test("E16: ett konto som aldrig gjort onboardingen får ändå sin vecka", () => {
  start();
  // Utloggningen låter "onboarding klar" stanna på enheten med flit - den är
  // av apparat-karaktär. Nästa person som loggar in kan vara en gäst som
  // aldrig sett rutan men mycket väl har en vecka på sitt konto, och den
  // frågan avgörs av om NÅGON svarar just nu, inte av vad enheten minns.
  state.onboardingComplete = true;
  const skrevs = applySyncBlob({ weekPlan: ["korvgryta"], onboardingComplete: false });
  assert.equal(skrevs, true);
  assert.deepEqual(state.weekPlan, ["korvgryta"]);
});

test("E16: en blob som KÄNNER till onboardingen är den nyare och skrivs in", () => {
  start();
  state.onboardingComplete = true;
  const skrevs = applySyncBlob({ budget: 1500, onboardingComplete: true, weekPlan: ["korvgryta"] });
  assert.equal(skrevs, true, "kontots egen vecka på en ny telefon ska fortfarande komma fram");
  assert.equal(state.budget, 1500);
  assert.deepEqual(state.weekPlan, ["korvgryta"]);
});

test("E16: en äldre prisbild lägger sig inte över en färskare", () => {
  start();
  // Premium har just prissatt alla tre kedjorna.
  state.dbChainTotals = { Willys: { chain: "Willys" }, Hemköp: { chain: "Hemköp" }, "City Gross": { chain: "City Gross" } };
  state.dbPricedAt = 2000;
  // Blobben begärdes före köpet och bär Free-vyns maskade bild: EN kedja.
  applySyncBlob({ dbChainTotals: { Willys: { chain: "Willys" } }, dbPricedAt: 1000 });
  assert.deepEqual(Object.keys(state.dbChainTotals).sort(), ["City Gross", "Hemköp", "Willys"],
                   "de tre prissatta kedjorna står kvar");
  assert.equal(state.dbPricedAt, 2000);
});

test("E16: en färskare prisbild ur kontot målas som förut", () => {
  start();
  state.dbChainTotals = { Willys: { chain: "Willys" } };
  state.dbPricedAt = 1000;
  applySyncBlob({ dbChainTotals: { Hemköp: { chain: "Hemköp" } }, dbComparison: { cheapestChain: "Hemköp" }, dbPricedAt: 3000 });
  assert.deepEqual(Object.keys(state.dbChainTotals), ["Hemköp"]);
  assert.equal(state.dbComparison.cheapestChain, "Hemköp");
  assert.equal(state.dbPricedAt, 3000);
});

test("E16: utan egen prisbild är kontots alltid den bättre - annars 'pris hämtas…'", () => {
  start();
  assert.equal(state.dbPricedAt, null);
  applySyncBlob({ dbChainTotals: { Willys: { chain: "Willys" } }, dbPricedAt: 1000 });
  assert.deepEqual(Object.keys(state.dbChainTotals), ["Willys"]);
  assert.equal(state.dbPricedAt, 1000);
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
