import test from "node:test";
import assert from "node:assert/strict";
import {
  BUDGET_ALERT_MIN_WEEKS, SWAP_INTENTS, pantryOverlap, rankSwapOptions,
  recentlyEatenPenalty, swapCostText, swapReasonText, weekCostAlert,
} from "../frontend/app/src/services/swap.js";

const current = { id: "nu", namn: "Lax", portionspris: 60, tid: 40, protein: 30, ingredienser: ["Laxfilé", "Potatis"] };
const candidates = [
  { id: "billig", namn: "Pasta", portionspris: 25, tid: 25, protein: 12, ingredienser: ["Pasta", "Tomat"], taggar: [] },
  { id: "dyr", namn: "Entrecôte", portionspris: 95, tid: 30, protein: 40, ingredienser: ["Biff"], taggar: [] },
  { id: "snabb", namn: "Omelett", portionspris: 30, tid: 15, protein: 22, ingredienser: ["Ägg", "Ost"], taggar: [] },
  { id: "barn", namn: "Pannkakor", portionspris: 20, tid: 35, protein: 10, ingredienser: ["Mjölk", "Ägg"], taggar: ["barn"] },
  { id: "okand", namn: "Okänd", portionspris: null, tid: null, protein: null, ingredienser: ["Ris"], taggar: [] },
];

test("billigare listar bara rätter som FAKTISKT är billigare", () => {
  const ids = rankSwapOptions(current, candidates, "cheaper").map(o => o.candidate.id);
  assert.deepEqual(ids, ["barn", "billig", "snabb"]);
  assert.ok(!ids.includes("dyr"), "en dyrare rätt får aldrig listas under Billigare");
  assert.ok(!ids.includes("okand"), "en rätt utan pris kan inte påstås vara billigare");
});

test("snabbare listar bara kortare tillagningstid", () => {
  const ids = rankSwapOptions(current, candidates, "faster").map(o => o.candidate.id);
  assert.deepEqual(ids, ["snabb", "billig", "dyr", "barn"]);
  assert.ok(!ids.includes("okand"), "en rätt utan tid kan inte påstås vara snabbare");
});

test("barnvänligt är en egenskap receptet har, inte en skala vi räknar fram", () => {
  const ids = rankSwapOptions(current, candidates, "kids").map(o => o.candidate.id);
  assert.deepEqual(ids, ["barn"]);
});

test("mer protein kräver mer protein än den nuvarande rätten", () => {
  const ids = rankSwapOptions(current, candidates, "protein").map(o => o.candidate.id);
  assert.deepEqual(ids, ["dyr"]);
});

test("använd det vi har hemma rankar på faktisk överlappning", () => {
  const options = rankSwapOptions(current, candidates, "pantry", ["Ägg", "Ost", "Pasta"]);
  assert.deepEqual(options.map(o => o.candidate.id), ["snabb", "barn", "billig"]);
  assert.equal(options[0].overlap, 2);
});

test("tomt skafferi ger inga skafferiförslag i stället för alla", () => {
  assert.deepEqual(rankSwapOptions(current, candidates, "pantry", []), []);
});

test("utan avsikt är det billigast först, som förut", () => {
  const ids = rankSwapOptions(current, candidates, "").map(o => o.candidate.id);
  assert.equal(ids[0], "barn");
});

test("anledningen säger något konkret, eller ingenting", () => {
  const cheaper = rankSwapOptions(current, candidates, "cheaper")[0];
  assert.equal(swapReasonText(cheaper, "cheaper", current), "40 kr billigare per portion");
  const faster = rankSwapOptions(current, candidates, "faster")[0];
  assert.equal(swapReasonText(faster, "faster", current), "25 minuter snabbare");
  assert.equal(swapReasonText(cheaper, "", current), "");
});

test("överlappning räknar oberoende av skiftläge", () => {
  assert.equal(pantryOverlap({ ingredienser: ["Ägg", "Ost"] }, ["ägg"]), 1);
  assert.equal(pantryOverlap({ ingredienser: ["Ägg"] }, []), 0);
});

test("nyss ätna rätter straffas mest, äldre allt mindre", () => {
  const history = [{ plan: ["a"] }, { plan: ["b"] }, { plan: ["c"] }];
  assert.equal(recentlyEatenPenalty("a", history), 3);
  assert.equal(recentlyEatenPenalty("b", history), 2);
  assert.equal(recentlyEatenPenalty("c", history), 1);
  assert.equal(recentlyEatenPenalty("d", history), 0, "en rätt de inte ätit straffas inte");
});

test("favoriter får återkomma tidigare än andra rätter", () => {
  const history = [{ plan: ["favvo"] }];
  assert.ok(recentlyEatenPenalty("favvo", history, new Set(["favvo"]))
    < recentlyEatenPenalty("favvo", history, new Set()));
});

test("budgetvarningen kräver riktiga tal och en riktig skillnad", () => {
  const usual = [{ total: 700 }, { total: 720 }, { total: 690 }, { total: 710 }];
  assert.equal(weekCostAlert(880, usual).difference, 175);
  assert.equal(weekCostAlert(880, usual).usual, 705);
  assert.equal(weekCostAlert(720, usual), null, "en normal vecka utlöser ingen varning");
  assert.equal(weekCostAlert(880, usual.slice(0, 2)), null, "för få veckor att jämföra med");
  assert.equal(weekCostAlert(null, usual), null);
});

test("veckor utan riktig total räknas inte in i snittet", () => {
  const mixed = [{ total: null }, { total: 700 }, { total: 720 }, { total: 690 }, { total: 710 }];
  assert.equal(weekCostAlert(880, mixed).usual, 705, "en oprissatt vecka får inte dra ner snittet");
  const tooFew = [{ total: null }, { total: null }, { total: 700 }, { total: 720 }];
  assert.equal(weekCostAlert(880, tooFew), null);
});

test("alla fem avsikter finns och har etiketter", () => {
  assert.equal(SWAP_INTENTS.length, 5);
  assert.ok(SWAP_INTENTS.every(intent => intent.id && intent.label));
  assert.equal(BUDGET_ALERT_MIN_WEEKS, 4);
});

test("prisändringen står FÖRE bytet, även när man byter av andra skäl", () => {
  // U21. swapReasonText säger bara något om priset när avsikten är att
  // spara pengar. Byter man för att det ska gå fortare kan veckan bli
  // dyrare utan ett ord - och det är just det man behöver veta.
  const current = { portionspris: 30 };
  assert.equal(swapCostText({ price: 22 }, current), "8 kr billigare per portion");
  assert.equal(swapCostText({ price: 41 }, current), "11 kr dyrare per portion");
  assert.equal(swapCostText({ price: 30 }, current), "Samma pris per portion");
});

test("saknad prisdata sägs rakt ut, den ser inte ut som noll skillnad", () => {
  // "Saknas data: ange det" står uttryckligen i kravet.
  assert.equal(swapCostText({ price: null }, { portionspris: 30 }), "Prisändring okänd");
  assert.equal(swapCostText({ price: 22 }, { portionspris: null }), "Prisändring okänd");
  assert.equal(swapCostText({}, {}), "Prisändring okänd");
  assert.equal(swapCostText(null, null), "Prisändring okänd");
});
