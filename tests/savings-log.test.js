import test from "node:test";
import assert from "node:assert/strict";
import { recordWeekSaving, weekKeyFor } from "../frontend/app/src/services/savings-log.js";

const post = (weekKey, savings, branch = "Willys") =>
  ({ weekKey, savings, branch, hasComparison: true, portionCost: 25, date: "2026-09-07" });

test("samma vecka vald flera gånger ger EN post", () => {
  // Förut gav tre klick tre poster, och renderStats summerar posterna -
  // samma vecka räknades som tre veckors besparing.
  let log = [];
  for (let i = 0; i < 3; i++) log = recordWeekSaving(log, post("a|b|c", 40));
  assert.equal(log.length, 1);
  assert.equal(log.reduce((sum, e) => sum + e.savings, 0), 40);
});

test("omval av samma vecka ersätter posten, den läggs inte till", () => {
  let log = recordWeekSaving([], post("a|b|c", 40, "Willys"));
  log = recordWeekSaving(log, post("a|b|c", 55, "Hemköp"));
  assert.equal(log.length, 1);
  assert.equal(log[0].savings, 55);
  assert.equal(log[0].branch, "Hemköp");
});

test("en annan vecka är en ny handling och får en egen post", () => {
  let log = recordWeekSaving([], post("a|b|c", 40));
  log = recordWeekSaving(log, post("d|e|f", 30));
  assert.equal(log.length, 2);
});

test("veckonyckeln är oberoende av rätternas ordning", () => {
  // Samma vecka i annan ordning är samma vecka - annars slinker en dubblett
  // igenom så fort planeraren råkar sortera annorlunda.
  assert.equal(weekKeyFor(["c", "a", "b"]), weekKeyFor(["a", "b", "c"]));
});

test("tom eller saknad logg kraschar inte", () => {
  assert.equal(recordWeekSaving(undefined, post("a", 10)).length, 1);
  assert.equal(recordWeekSaving(null, post("a", 10)).length, 1);
});

test("indata muteras inte", () => {
  const original = [post("a|b|c", 40)];
  const kopia = JSON.parse(JSON.stringify(original));
  recordWeekSaving(original, post("d|e|f", 30));
  assert.deepEqual(original, kopia);
});
