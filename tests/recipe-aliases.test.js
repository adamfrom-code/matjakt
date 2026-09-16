// P04b: ett recept-id som blivit alias betyder fortfarande samma rätt.
//
// Servern tolkar varken kontoblobben eller hushållsdokumenten, så favoriter,
// veckan, historiken och betygen som skrevs med de gamla id:na pekas om HÄR,
// där appen läser dem. Testerna är acceptansen för klientsidan: en vecka med
// ett gammalt id överlever, migreringen är idempotent, och ingenting som inte
// är ett alias i den laddade banken rörs.
import test from "node:test";
import assert from "node:assert/strict";
import { aliasMap, canonicalRecipeId, findRecipe, migrateRecipeIds } from "../frontend/app/src/services/recipe-aliases.js";
import {
  applySyncBlob, initAppState, reconcileRecipeAliases, selectedRecipes, setWeekPlan, state,
} from "../frontend/app/src/state/app-state.js";

const BANK = [
  { id: "rakpasta-vitlok", namn: "Räkpasta", aliases: ["scampi"] },
  { id: "linssoppa-rod", namn: "Röd linssoppa", aliases: ["linssoppa"] },
  { id: "korvgryta", namn: "Korvgryta", aliases: [] },
  { id: "fiskpasta", namn: "Fiskpasta" },
];

function memoryStorage(initial = null) {
  let value = initial;
  return { getItem: () => value, setItem: (_key, next) => { value = next; }, read: () => value };
}

// ---- den rena modulen -----------------------------------------------------

test("aliasMap: gamla id -> kanoniska, ur bankens `aliases`", () => {
  const map = aliasMap(BANK);
  assert.deepEqual([...map.entries()], [["scampi", "rakpasta-vitlok"], ["linssoppa", "linssoppa-rod"]]);
  assert.equal(canonicalRecipeId("scampi", map), "rakpasta-vitlok");
  assert.equal(canonicalRecipeId("korvgryta", map), "korvgryta", "ett kanoniskt id är sig självt");
  assert.equal(canonicalRecipeId("okant", map), "okant", "ett okänt id gissas aldrig om");
});

test("aliasMap: ett recept som pekar på sig självt eller saknar fältet ger ingen post", () => {
  const map = aliasMap([{ id: "a", aliases: ["a", "", null] }, { id: "b" }, null]);
  assert.equal(map.size, 0);
});

test("findRecipe: slår upp på id, sedan på alias, annars null", () => {
  assert.equal(findRecipe(BANK, "scampi").id, "rakpasta-vitlok");
  assert.equal(findRecipe(BANK, "korvgryta").id, "korvgryta");
  assert.equal(findRecipe(BANK, "borttaget"), null);
});

test("migrateRecipeIds: favoriter, vecka, historik, betyg och omdömen pekas om - dagordningen bevaras", () => {
  const map = aliasMap(BANK);
  const tillstand = {
    favoriter: new Set(["scampi", "korvgryta", "rakpasta-vitlok"]),
    valda: new Set(["linssoppa", "fiskpasta"]),
    weekPlan: ["linssoppa", null, "scampi", "korvgryta"],
    weekHistory: [{ plan: ["scampi", "fiskpasta"], savedAt: 1 }, { plan: ["korvgryta"], savedAt: 2 }, { trasig: true }],
    apiRecipes: [{ id: "scampi", namn: "Scampi" }, { id: "fiskpasta", namn: "Fiskpasta" }],
    betyg: { scampi: 5, "rakpasta-vitlok": 3, korvgryta: 2 },
    feedback: { linssoppa: { liked: true }, scampi: { disliked: true }, "rakpasta-vitlok": { liked: true } },
  };
  assert.equal(migrateRecipeIds(tillstand, map), true);
  assert.deepEqual([...tillstand.favoriter], ["rakpasta-vitlok", "korvgryta"], "alias och kanoniskt blir EN favorit");
  assert.deepEqual([...tillstand.valda], ["linssoppa-rod", "fiskpasta"]);
  assert.deepEqual(tillstand.weekPlan, ["linssoppa-rod", null, "rakpasta-vitlok", "korvgryta"],
                   "veckan behåller sina dagar - måndagen är fortfarande måndag");
  assert.deepEqual(tillstand.weekHistory[0].plan, ["rakpasta-vitlok", "fiskpasta"]);
  assert.deepEqual(tillstand.weekHistory[1], { plan: ["korvgryta"], savedAt: 2 }, "en orörd post är orörd");
  assert.deepEqual(tillstand.weekHistory[2], { trasig: true }, "en post utan plan lämnas åt normalizeState");
  assert.deepEqual(tillstand.apiRecipes.map(r => r.id), ["rakpasta-vitlok", "fiskpasta"]);
  assert.equal(tillstand.apiRecipes[0].namn, "Scampi", "posten byter id, inte innehåll - detaljerna hämtas om per id");
  assert.deepEqual(tillstand.betyg, { "rakpasta-vitlok": 5, korvgryta: 2 }, "högsta betyget vinner");
  assert.deepEqual(tillstand.feedback, { "linssoppa-rod": { liked: true }, "rakpasta-vitlok": { liked: true } },
                   "det kanoniska id:ts omdöme vinner när båda finns");
});

test("migrateRecipeIds: två poster för samma rätt blir en, och den kanoniska behålls", () => {
  const tillstand = { apiRecipes: [{ id: "scampi", namn: "Scampi" }, { id: "rakpasta-vitlok", namn: "Räkpasta" }] };
  migrateRecipeIds(tillstand, aliasMap(BANK));
  assert.deepEqual(tillstand.apiRecipes, [{ id: "rakpasta-vitlok", namn: "Räkpasta" }]);
});

test("migrateRecipeIds: en vecka där alias och kanoniskt stod på två dagar blir samma rätt två dagar - inte en påhittad", () => {
  const tillstand = { weekPlan: ["scampi", "rakpasta-vitlok", "korvgryta"] };
  migrateRecipeIds(tillstand, aliasMap(BANK));
  assert.deepEqual(tillstand.weekPlan, ["rakpasta-vitlok", "rakpasta-vitlok", "korvgryta"]);
});

test("migrateRecipeIds: idempotent, och rör ingenting utan alias", () => {
  const map = aliasMap(BANK);
  const tillstand = { favoriter: new Set(["korvgryta"]), weekPlan: ["fiskpasta", "okant-recept"], betyg: { korvgryta: 4 } };
  assert.equal(migrateRecipeIds(tillstand, map), false, "inget att peka om -> false");
  assert.deepEqual(tillstand.weekPlan, ["fiskpasta", "okant-recept"], "ett okänt id lämnas - banken kan sakna det just nu");
  const migrerat = { weekPlan: ["scampi"] };
  assert.equal(migrateRecipeIds(migrerat, map), true);
  assert.equal(migrateRecipeIds(migrerat, map), false, "andra körningen har inget kvar att göra");
  assert.equal(migrateRecipeIds({ weekPlan: ["scampi"] }, new Map()), false, "tom bank pekar om ingenting");
  assert.equal(migrateRecipeIds(null, map), false);
});

// ---- tillståndet ---------------------------------------------------------

test("en sparad vecka med ett gammalt id ritar rätt rätt - redan innan tillståndet pekats om", () => {
  initAppState({ storage: memoryStorage(JSON.stringify({ weekPlan: ["scampi", "korvgryta"], valda: ["scampi", "korvgryta"] })),
                 recipeBank: BANK });
  const dagar = selectedRecipes();
  assert.equal(dagar[0].id, "rakpasta-vitlok", "aliaset slås upp på sin rätt");
  assert.equal(dagar[1].id, "korvgryta");
});

test("reconcileRecipeAliases: pekar om tillståndet mot den laddade banken och säger till", () => {
  initAppState({ storage: memoryStorage(JSON.stringify({
    favoriter: ["scampi"], weekPlan: ["linssoppa", "korvgryta"], valda: ["linssoppa", "korvgryta"],
    weekHistory: [{ plan: ["scampi"], savedAt: 1 }], betyg: { scampi: 4 },
  })), recipeBank: BANK });
  assert.equal(reconcileRecipeAliases(), true);
  assert.deepEqual([...state.favoriter], ["rakpasta-vitlok"]);
  assert.deepEqual(state.weekPlan, ["linssoppa-rod", "korvgryta"]);
  assert.deepEqual([...state.valda], ["linssoppa-rod", "korvgryta"]);
  assert.deepEqual(state.weekHistory[0].plan, ["rakpasta-vitlok"]);
  assert.deepEqual(state.betyg, { "rakpasta-vitlok": 4 });
  assert.equal(reconcileRecipeAliases(), false, "en gång räcker");
});

test("reconcileRecipeAliases: utan laddad bank pekas ingenting om", () => {
  initAppState({ storage: memoryStorage(JSON.stringify({ weekPlan: ["scampi"] })), recipeBank: [] });
  assert.equal(reconcileRecipeAliases(), false);
  assert.deepEqual(state.weekPlan, ["scampi"], "ett id vi inte kan slå upp lämnas i fred");
});

test("applySyncBlob: en kontoblob skriven före sammanslagningen pekas om när den tas emot", () => {
  initAppState({ storage: memoryStorage(), recipeBank: BANK });
  setWeekPlan(["korvgryta"]);
  assert.equal(applySyncBlob({ favoriter: ["linssoppa", "scampi"], weekPlan: ["scampi", "fiskpasta"],
                               feedback: { scampi: { liked: true } } }), true);
  assert.deepEqual(state.weekPlan, ["rakpasta-vitlok", "fiskpasta"]);
  assert.deepEqual([...state.favoriter], ["linssoppa-rod", "rakpasta-vitlok"]);
  assert.deepEqual(state.feedback, { "rakpasta-vitlok": { liked: true } });
});
