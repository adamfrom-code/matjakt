// AA1: rester = kokta − ätna, en dag i taget. Ren aritmetik, ingen gissning.
import test from "node:test";
import assert from "node:assert/strict";
import { resterDagar, resterPlan, resterText } from "../frontend/app/src/services/rester.js";

test("alla hemma varje dag: inget blir över", () => {
  const plan = resterPlan({ weekPlan: ["a", "b", "c"], people: 4, presence: [] });
  assert.equal(plan.length, 7);
  assert.deepEqual(plan.slice(0, 3).map(r => [r.kokta, r.atna, r.over]), [[4, 4, 0], [4, 4, 0], [4, 4, 0]]);
  assert.deepEqual(resterDagar(plan), []);
  assert.equal(resterText(plan[0]), "");
});

test("två av fyra hemma på måndag: två portioner över, som räcker tisdag om två äter då", () => {
  const plan = resterPlan({ weekPlan: ["a", "b", "c"], people: 4, presence: [2, 2, null] });
  assert.deepEqual([plan[0].kokta, plan[0].atna, plan[0].over], [4, 2, 2]);
  assert.equal(plan[0].rackerImorgon, true);
  assert.equal(plan[1].resterFran, 0);
  assert.equal(plan[1].resterRackerHelaDagen, true, "tisdagens två ätare täcks av måndagens två portioner");
  assert.equal(resterText(plan[0]), "2 portioner över");
  assert.equal(resterText(plan[1]), "Rester från igår räcker");
  assert.deepEqual(resterDagar(plan), [1]);
});

test("rester som inte räcker hela dagen äts upp och förs inte vidare", () => {
  const plan = resterPlan({ weekPlan: ["a", "b", "c"], people: 4, presence: [3, null, null] });
  assert.equal(plan[0].over, 1);
  assert.equal(plan[0].rackerImorgon, false, "en portion räcker inte fyra");
  assert.equal(plan[1].resterFran, 0);
  assert.equal(plan[1].resterRackerHelaDagen, false);
  assert.equal(plan[2].resterFran, null, "onsdag börjar utan rester");
  assert.equal(resterText(plan[0]), "1 portion över");
});

test("en tom dag lagar inget, får inga rester och lämnar inga vidare", () => {
  const plan = resterPlan({ weekPlan: ["a", null, "c"], people: 3, presence: [1, null, null] });
  assert.deepEqual([plan[1].lagas, plan[1].kokta, plan[1].over], [false, 0, 0]);
  assert.equal(plan[1].resterFran, 0, "måndagens rester finns tisdag");
  assert.equal(plan[1].resterRackerHelaDagen, false, "två portioner räcker inte tre");
  assert.equal(plan[2].resterFran, null);
});

test("konstigt indata: närvaro över hushållet klampas, skräp blir alla, tom vecka är sju tomma dagar", () => {
  const plan = resterPlan({ weekPlan: ["a"], people: 2, presence: [9, "x", -1] });
  assert.deepEqual([plan[0].atna, plan[0].over], [2, 0]);
  assert.deepEqual(resterPlan({}).map(r => r.lagas), Array(7).fill(false));
  assert.ok(Object.isFrozen(plan) && Object.isFrozen(plan[0]));
});
