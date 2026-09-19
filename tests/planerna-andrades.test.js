// Y1: "Planerna ändrades" - flytta en middag till en annan dag, bakom
// flaggan vecka.flytta.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.document = { querySelector: () => null, baseURI: "http://localhost/app/" };

const { initAppState, moveWeekPlanDay, setPresence, state } = await import("../frontend/app/src/state/app-state.js");
const { initWeekView, veckoDagMarkup } = await import("../frontend/app/src/views/week.js");

const minne = json => ({ getItem: () => json, setItem: () => {} });
const starta = plan => initAppState({ storage: minne(JSON.stringify({ schemaVersion: 1, personer: 4, weekPlan: plan, valda: plan.filter(Boolean) })) });

test("flytt till en tom dag: rätten byter dag, avsändardagen blir tom", () => {
  starta(["a", "b", "c"]);
  assert.equal(moveWeekPlanDay(0, 5), true);
  assert.deepEqual(state.weekPlan, [null, "b", "c", null, null, "a"]);
  assert.deepEqual([...state.valda].sort(), ["a", "b", "c"], "samma rätter i veckan");
});

test("flytt till en upptagen dag: de två byter plats", () => {
  starta(["a", "b", "c"]);
  assert.equal(moveWeekPlanDay(2, 0), true);
  assert.deepEqual(state.weekPlan, ["c", "b", "a"]);
});

test("ogiltiga flyttar är no-op: samma dag, tom avsändare, utanför veckan", () => {
  starta(["a", null, "c"]);
  assert.equal(moveWeekPlanDay(0, 0), false);
  assert.equal(moveWeekPlanDay(1, 3), false, "ingen middag att flytta");
  assert.equal(moveWeekPlanDay(0, 7), false);
  assert.equal(moveWeekPlanDay(-1, 2), false);
  assert.equal(moveWeekPlanDay("0", 2), false);
  assert.deepEqual(state.weekPlan, ["a", null, "c"]);
});

test("närvaron hör till dagen och följer inte med rätten", () => {
  starta(["a", "b", "c"]);
  setPresence(0, 2);
  moveWeekPlanDay(0, 2);
  assert.deepEqual(state.weekPlan, ["c", "b", "a"]);
  assert.equal(state.narvaro[0], 2, "måndag har fortfarande två hemma");
  assert.equal(state.narvaro[2], null);
});

test("dagmenyn bär 'Flytta till' bara bakom flaggan, en knapp per annan dag", () => {
  const recipe = { id: "r1", namn: "Korvstroganoff", tid: 25, portionspris: 27 };
  let flagga = false;
  initWeekView({ money: v => `${v} kr`, plural: (n, a, b) => `${n} ${n === 1 ? a : b}`, personer: () => 4,
                 flyttaPa: () => flagga, recipeFeedback: () => ({}) });
  assert.doesNotMatch(veckoDagMarkup(recipe, 1, { idag: -1 }), /data-week-move|Flytta till/);
  flagga = true;
  const rad = veckoDagMarkup(recipe, 1, { idag: -1 });
  assert.match(rad, /Flytta till/);
  const mål = [...rad.matchAll(/data-week-move="1:(\d)"/g)].map(m => Number(m[1]));
  assert.deepEqual(mål, [0, 2, 3, 4, 5, 6], "alla dagar utom den egna");
  assert.match(rad, /aria-label="Flytta tisdags middag till onsdag"/);
});

test("app.js kopplar knappen till moveWeekPlanDay utan att röra prisbilden", () => {
  const appJs = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
  assert.match(appJs, /flyttaPa: \(\) => flagga\("vecka\.flytta"\)/);
  const start = appJs.indexOf('document.querySelectorAll("[data-week-move]")');
  assert.notEqual(start, -1);
  const body = appJs.slice(start, start + 420);
  assert.match(body, /moveWeekPlanDay\(from, to\)/);
  assert.match(body, /saveState\(\); invalidate\("week", "home"\)/);
  assert.doesNotMatch(body, /clearPriceSnapshots/, "samma rätter - priserna står kvar");
});

test("en vecka med en tom dag mitt i överlever sparning och synk", async () => {
  const { buildSyncPayload, applySyncBlob, normalizeState } = await import("../frontend/app/src/state/app-state.js");
  starta(["a", "b", "c"]);
  moveWeekPlanDay(0, 4);
  const payload = buildSyncPayload();
  assert.deepEqual(payload.weekPlan, [null, "b", "c", null, "a"]);
  starta([]);
  applySyncBlob(payload);
  assert.deepEqual(state.weekPlan, [null, "b", "c", null, "a"], "hålet ska stå kvar - annars förskjuts dagarna");
  // Formen garanteras: skräp bort, tomma platser på slutet bort
  assert.deepEqual(normalizeState({ weekPlan: ["a", null, 3, {}, "b", null, null] }).weekPlan, ["a", null, "b"]);
});
