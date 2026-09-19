// R1: planeringskontexten återger state exakt - och app.js går genom den.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describeContext, planningContext } from "../frontend/app/src/services/planning-context.js";

const STATE = {
  personer: 3, middagar: 5, budget: 900,
  hushall: { vuxna: 2, barn: 1 },
  kost: { kosttyp: "vegetarisk", avoidAllergens: new Set(["gluten"]) },
  ogillar: new Set(["oliver"]),
  feedback: { "a": { disliked: true }, "b": { liked: true }, "c": { disliked: false } },
  pantry: { "Ris": { amount: 1 }, "Lök": { amount: 3 } },
  weekHistory: [{ plan: ["x", "y"], savedAt: 1 }, { plan: ["z"], savedAt: 0 }],
};

test("kontexten bär exakt det planeraren läste ur state", () => {
  const ctx = planningContext(STATE, { premium: true, goals: { proteinMin: 30 }, branch: { kedja: "willys" }, objective: "balanced" });
  assert.equal(ctx.dinners, 5);
  assert.equal(ctx.budget, 900);
  assert.equal(ctx.people, 3);
  assert.deepEqual([ctx.adults, ctx.children], [2, 1]);
  assert.equal(ctx.diet.kosttyp, "vegetarisk");
  assert.deepEqual([...ctx.diet.avoidAllergens], ["gluten"]);
  assert.deepEqual([...ctx.dislikes], ["oliver"]);
  assert.deepEqual([...ctx.dislikedIds], ["a"]);
  assert.deepEqual([...ctx.pantry], ["Ris", "Lök"]);
  assert.deepEqual(ctx.history.map(v => [...v]), [["x", "y"], ["z"]]);
  assert.deepEqual(ctx.goals, { proteinMin: 30 });
  assert.equal(ctx.branch.kedja, "willys");
  assert.equal(ctx.objective, "balanced");
  assert.ok(Object.isFrozen(ctx) && Object.isFrozen(ctx.diet) && Object.isFrozen(ctx.pantry));
});

test("näringsmål gäller bara Premium, och okänt objective blir cheapest", () => {
  const fri = planningContext(STATE, { premium: false, goals: { proteinMin: 30 }, objective: "snabbast" });
  assert.equal(fri.goals, null);
  assert.equal(fri.objective, "cheapest");
});

test("tomt eller trasigt state ger appens reservvärden, aldrig NaN", () => {
  const ctx = planningContext({});
  assert.deepEqual([ctx.people, ctx.dinners, ctx.budget], [2, 4, 0]);
  assert.deepEqual([[...ctx.dislikes], [...ctx.pantry], [...ctx.history]], [[], [], []]);
  assert.equal(ctx.diet.avoidAllergens.size, 0);
  const konstigt = planningContext({ personer: "abc", middagar: null, budget: undefined, hushall: { vuxna: "2", barn: "x" } });
  assert.deepEqual([konstigt.people, konstigt.dinners, konstigt.adults, konstigt.children], [2, 4, 2, 0]);
});

test("beskrivningen är läsbar och utan id", () => {
  const rad = describeContext(planningContext(STATE, { premium: true, goals: { proteinMin: 30 } }));
  assert.match(rad, /^5 middagar för 3 \(2\+1\), budget 900 kr, vegetarisk, 1 allergener, 1 ogillar, 2 i skafferiet, 2 veckor historik, cheapest, näringsmål$/);
  assert.doesNotMatch(rad, /oliver|Ris/);
});

test("chooseMenu i app.js går genom kontexten - samma tre värden som förut", () => {
  const appJs = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
  const start = appJs.indexOf("function chooseMenu(");
  const body = appJs.slice(start, appJs.indexOf("\n}\n", start));
  assert.match(body, /const ctx = planningContext\(state, \{\n\s+premium: hasPremium\(\), goals: currentNutritionGoals\(\), branch: selectedBranch\(\),/);
  assert.match(body, /deriveFromMembers: flagga\("hushall\.medlemmar"\)/);
  assert.match(body, /bestMenuCombo\(candidates, ctx\.dinners, ctx\.budget, ctx\.branch\)/);
  assert.doesNotMatch(body, /bestMenuCombo\(candidates, state\.middagar/);
});


// S1: personer ur medlemmarna - bara bakom flaggan, och bara med ett hushåll.
test("S1: personer härleds ur medlemmarnas slag och portionsfaktor bakom flaggan", () => {
  const members = [
    { userId: 1, kind: "adult", portionFactor: 1 },
    { userId: 2, kind: "child", portionFactor: 1 },
    { userId: 3, profile: { child: true } },          // gammal post utan kind
    { userId: 4, kind: "guest", portionFactor: 1 },
  ];
  const av = planningContext({ personer: 2, hushall: { vuxna: 2, barn: 0 } }, { members, deriveFromMembers: false });
  assert.deepEqual([av.people, av.adults, av.children, av.peopleSource], [2, 2, 0, "installningar"]);
  const pa = planningContext({ personer: 2, hushall: { vuxna: 2, barn: 0 } }, { members, deriveFromMembers: true });
  assert.deepEqual([pa.people, pa.adults, pa.children, pa.peopleSource], [4, 2, 2, "medlemmar"]);
  // Utan hushåll gör flaggan ingenting.
  const ensam = planningContext({ personer: 3 }, { members: null, deriveFromMembers: true });
  assert.deepEqual([ensam.people, ensam.peopleSource], [3, "installningar"]);
  // Portionsfaktorn från servern styr summan, klampad 1-12.
  const halva = planningContext({}, { members: [{ kind: "adult", portionFactor: 1 }, { kind: "child", portionFactor: 0.5 }], deriveFromMembers: true });
  assert.equal(halva.people, 1.5);
  assert.equal(planningContext({}, { members: Array(20).fill({ kind: "adult", portionFactor: 1 }), deriveFromMembers: true }).people, 12);
});
