// T1: vem äter hemma, per dag - tillståndet, raden och kontrollen, bakom
// flaggan vecka.narvaro. Utan flagga: exakt som förut.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.document = { querySelector: () => null, baseURI: "http://localhost/app/" };

const { initAppState, normalizeState, presenceForDay, setPresence, setWeekPlan, state, buildSyncPayload, applySyncBlob, WEEK_DAY_COUNT } =
  await import("../frontend/app/src/state/app-state.js");
const { initWeekView, veckoDagMarkup } = await import("../frontend/app/src/views/week.js");
const { planningContext } = await import("../frontend/app/src/services/planning-context.js");

function memoryStorage(initial = null) {
  let value = initial;
  return { getItem: () => value, setItem: (_k, next) => { value = next; }, read: () => value };
}

test("närvaron är sju platser med null = alla, klampad 1-12, och formen garanteras", () => {
  initAppState({ storage: memoryStorage(JSON.stringify({ schemaVersion: 1, personer: 4, narvaro: [2, "3", null, 40, "x", 0] })) });
  assert.equal(state.personer, 4);
  assert.deepEqual(state.narvaro, [2, 3, null, 12, null, null, null], "0 är inte ett tal att räkna portioner på");
  assert.equal(presenceForDay(0), 2);
  assert.equal(presenceForDay(2), 4, "null = alla hemma");
  assert.equal(presenceForDay(6), 4);
  // Trasig form släpps - standard är alla hemma
  assert.equal(normalizeState({ narvaro: "tre" }).narvaro, undefined);
  initAppState({ storage: memoryStorage(JSON.stringify({ schemaVersion: 1, personer: 3 })) });
  assert.deepEqual(state.narvaro, Array(WEEK_DAY_COUNT).fill(null));
});

test("setPresence: ett tal under hushållet sparas, alla eller mer blir null", () => {
  initAppState({ storage: memoryStorage(JSON.stringify({ schemaVersion: 1, personer: 4 })) });
  assert.equal(setPresence(1, 2), 2);
  assert.equal(setPresence(2, 4), null, "fyra av fyra är alla");
  assert.equal(setPresence(3, 9), null);
  assert.equal(setPresence(4, 0), null);
  assert.deepEqual(state.narvaro, [null, 2, null, null, null, null, null]);
  // Följer med i synken och kommer tillbaka
  const payload = buildSyncPayload();
  assert.deepEqual(payload.narvaro, [null, 2, null, null, null, null, null]);
  initAppState({ storage: memoryStorage(JSON.stringify({ schemaVersion: 1, personer: 4 })) });
  applySyncBlob({ ...payload });
  assert.deepEqual(state.narvaro, [null, 2, null, null, null, null, null]);
});

test("en ny vecka börjar med alla hemma", () => {
  initAppState({ storage: memoryStorage(JSON.stringify({ schemaVersion: 1, personer: 4, narvaro: [1, 2, 3, null, null, null, null] })) });
  setWeekPlan(["a", "b"]);
  assert.deepEqual(state.narvaro, Array(WEEK_DAY_COUNT).fill(null));
});

test("dagraden säger '2 av 4 hemma' och bär kontrollen - bara bakom flaggan", () => {
  const recipe = { id: "r1", namn: "Korvstroganoff", tid: 25, portionspris: 27 };
  let flagga = false;
  initWeekView({ money: v => `${v} kr`, plural: (n, a, b) => `${n} ${n === 1 ? a : b}`, personer: () => 4,
                 narvaroPa: () => flagga, personerForDay: index => (index === 1 ? 2 : 4), recipeFeedback: () => ({}) });
  const av = veckoDagMarkup(recipe, 1, { idag: -1 });
  assert.match(av, /4 port/);
  assert.doesNotMatch(av, /hemma|data-week-people/);
  flagga = true;
  const pa = veckoDagMarkup(recipe, 1, { idag: -1 });
  assert.match(pa, /2 av 4 hemma/);
  assert.match(pa, /data-week-people="1"/);
  assert.match(pa, /aria-label="Vilka äter hemma på tisdag\? Nu 2"/);
  const alla = veckoDagMarkup(recipe, 0, { idag: -1 });
  assert.match(alla, /4 port/, "alla hemma skrivs som förut");
  assert.match(alla, /data-week-people="0"/);
});

test("planeringskontexten bär närvaron", () => {
  const ctx = planningContext({ personer: 4, narvaro: [null, 2, null, null, null, null, null] });
  assert.deepEqual([...ctx.presence], [null, 2, null, null, null, null, null]);
  assert.deepEqual([...planningContext({}).presence], []);
});

test("app.js stegar närvaron nedåt och tillbaka till alla, bakom flaggan", () => {
  const appJs = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
  assert.match(appJs, /narvaroPa: \(\) => flagga\("vecka\.narvaro"\)/);
  assert.match(appJs, /personerForDay: index => presenceForDay\(index\)/);
  const start = appJs.indexOf('document.querySelectorAll("[data-week-people]")');
  assert.notEqual(start, -1);
  const body = appJs.slice(start, start + 400);
  assert.match(body, /setPresence\(index, nu > 1 \? nu - 1 : state\.personer\)/);
  assert.match(body, /saveState\(\); invalidate\("week"\)/);
});
