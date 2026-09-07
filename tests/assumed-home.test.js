import test from "node:test";
import assert from "node:assert/strict";
import { ASSUMED_STATE, assumedHomeItems, assumedState } from "../frontend/app/src/services/assumed-home.js";

const recept = hemma => ({ hemma });

test("samma vara i fyra recept är ETT antagande, inte fyra", () => {
  const items = assumedHomeItems([recept(["Olja", "Salt"]), recept(["Salt", "Peppar"]),
                                  recept(["Buljong", "Olja"]), recept(["Salt", "Peppar"])]);
  assert.deepEqual(items, ["Buljong", "Olja", "Peppar", "Salt"]);
});

test("stavningen är receptets egen, men dubbletter fångas ändå", () => {
  // Vi hittar inte på en normalform åt något användaren ska känna igen -
  // men "Salt" och "salt" är samma antagande.
  assert.deepEqual(assumedHomeItems([recept(["Smör"]), recept(["smör"])]), ["Smör"]);
});

test("sorteringen är svensk - å ä ö sist, inte som i ASCII", () => {
  assert.deepEqual(assumedHomeItems([recept(["Ägg", "Basilika", "Olja"])]),
                   ["Basilika", "Olja", "Ägg"]);
});

test("tomt och trasigt underlag ger en tom lista, aldrig en rad med skräp", () => {
  assert.deepEqual(assumedHomeItems([]), []);
  assert.deepEqual(assumedHomeItems(null), []);
  assert.deepEqual(assumedHomeItems([{}, recept(null), recept(["", "   ", null])]), []);
});

test("en hanterad vara byter tillstånd, den försvinner inte", () => {
  // Annars blir en tom lista tvetydig: antog vi inget, eller är allt klart?
  const tillagda = new Set(["ris"]), iSkafferi = new Set(["salt"]);
  assert.equal(assumedState("Ris", tillagda, iSkafferi), ASSUMED_STATE.ADDED);
  assert.equal(assumedState("Salt", tillagda, iSkafferi), ASSUMED_STATE.AT_HOME);
  assert.equal(assumedState("Peppar", tillagda, iSkafferi), ASSUMED_STATE.OFFER);
});

test("tillagd väger tyngre än i skafferiet när varan är båda", () => {
  const båda = new Set(["olja"]);
  assert.equal(assumedState("Olja", båda, båda), ASSUMED_STATE.ADDED);
});

test("jämförelsen bryr sig inte om skiftläge eller kantmellanslag", () => {
  assert.equal(assumedState("  OLJA ", new Set(["olja"]), new Set()), ASSUMED_STATE.ADDED);
});
