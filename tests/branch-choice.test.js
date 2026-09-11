// E9: butiksvalet körde kombinatorik per butik, per tangenttryck.
//
// Acceptanskriteriet står i uppdraget och är lika mycket en
// trovärdighetsfråga som en prestandafråga: SAMMA INDATA TVÅ GÅNGER SKA GE
// SAMMA BUTIK. En app vars hela löfte är "vem är billigast" får inte svara
// olika på samma fråga.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { branchChoiceKey, canPlanWeek, chooseBranch } from "../frontend/app/src/services/branch-choice.js";

const BRANCHES = [
  { kedja: "Willys", namn: "Willys Nian", primatKey: "willys-nian", avstandKm: 2.4 },
  { kedja: "Coop", namn: "Coop Tullhuset", primatKey: "coop-tullhuset", avstandKm: 1.1 },
  { kedja: "ICA", namn: "ICA Kvantum Ekhagen", primatKey: "ica-ekhagen", avstandKm: 3.8 },
  { kedja: "Coop", namn: "Coop Nian", primatKey: "coop-nian", avstandKm: 4.2 },
];

const input = (extra = {}) => ({ branches: BRANCHES, hasMenu: true, ...extra });

test("E9: samma indata två gånger ger samma butik", () => {
  const fråga = input({ premium: true, cheapestChain: "Coop" });
  const först = chooseBranch(fråga);
  // Femtio gånger, inte två: den gamla koden drog ett Math.random() per
  // recept och kandidat, så felet syntes inte alltid vid andra försöket.
  for (let i = 0; i < 50; i++) {
    assert.deepEqual(chooseBranch(fråga), först, `svar ${i + 2} skilde sig från det första`);
  }
  assert.equal(först.namn, "Coop Tullhuset");
});

test("E9: två butiker på exakt samma avstånd väljs inte med slantsingling", () => {
  const lika = [
    { kedja: "Willys", namn: "Willys Söder", primatKey: "willys-soder", avstandKm: 2 },
    { kedja: "Coop", namn: "Coop Söder", primatKey: "coop-soder", avstandKm: 2 },
  ];
  const svar = new Set();
  for (let i = 0; i < 25; i++) svar.add(chooseBranch(input({ branches: [...lika].reverse() })).namn);
  for (let i = 0; i < 25; i++) svar.add(chooseBranch(input({ branches: lika })).namn);
  assert.equal(svar.size, 1, "oavgjort avstånd ska avgöras på butikens identitet, inte på indataordningen");
});

test("E9: utan Premium är det närmaste butiken - aldrig ett påstående om billigast", () => {
  const vald = chooseBranch(input({ premium: false, cheapestChain: "ICA" }));
  assert.equal(vald.namn, "Coop Tullhuset", "utan Premium finns ingen riktig kedjedata att kröna någon med");
});

test("E9: med Premium vinner närmaste filial av serverns billigaste kedja", () => {
  const vald = chooseBranch(input({ premium: true, cheapestChain: "Willys" }));
  assert.equal(vald.namn, "Willys Nian");
});

test("E9: en billigaste kedja utan filial i närheten faller tillbaka på närmaste", () => {
  const vald = chooseBranch(input({ premium: true, cheapestChain: "Lidl" }));
  assert.equal(vald.namn, "Coop Tullhuset");
});

test("E9: ett kedjeval begränsar urvalet till den kedjan", () => {
  assert.equal(chooseBranch(input({ chain: "Coop" })).namn, "Coop Tullhuset");
  assert.equal(chooseBranch(input({ chain: "Lidl" })), null, "ingen filial av kedjan = ingen butik att visa");
});

test("E9: positionen får gå före butikens egen avståndsuppgift", () => {
  // Som i appen: har vi användarens position räknas avståndet om, och den
  // omräkningen ska styra valet.
  const vald = chooseBranch(input({ distanceTo: branch => (branch.primatKey === "ica-ekhagen" ? 0.2 : 9) }));
  assert.equal(vald.namn, "ICA Kvantum Ekhagen");
  assert.equal(vald.avstandKm, 0.2, "det omräknade avståndet ska följa med till skärmen");
});

test("E9: utan recept finns ingen vecka att handla till, och därmed ingen butik", () => {
  assert.equal(canPlanWeek(0, 4), false);
  assert.equal(canPlanWeek(12, 0), false);
  assert.equal(canPlanWeek(12, 4), true);
  assert.equal(chooseBranch(input({ hasMenu: false })), null);
  assert.equal(chooseBranch(input({ branches: [] })), null);
});

// ---- (a) budgeten kan inte längre trigga omräkningen ----------------------

test("E9: cache-nyckeln bär inte budgeten - den påverkar inte vilken butik det blir", () => {
  const bas = { branches: BRANCHES, chain: null, premium: true, cheapestChain: "Coop", hasMenu: true };
  assert.equal(branchChoiceKey({ ...bas, budget: 700 }), branchChoiceKey({ ...bas, budget: 4000 }));
  assert.doesNotMatch(branchChoiceKey(bas), /700|4000/);
});

test("E9: nyckeln ändras när något valet FAKTISKT beror på ändras", () => {
  const bas = { branches: BRANCHES, chain: null, premium: false, cheapestChain: null, hasMenu: true };
  const nyckel = branchChoiceKey(bas);
  assert.notEqual(branchChoiceKey({ ...bas, premium: true }), nyckel);
  assert.notEqual(branchChoiceKey({ ...bas, chain: "Coop" }), nyckel);
  assert.notEqual(branchChoiceKey({ ...bas, hasMenu: false }), nyckel);
  assert.notEqual(branchChoiceKey({ ...bas, branches: BRANCHES.slice(1) }), nyckel);
  assert.notEqual(branchChoiceKey({ ...bas, position: { lat: 59.3, lon: 18.1 } }), nyckel);
  assert.notEqual(branchChoiceKey({ ...bas, pinned: { primatKey: "coop-nian" } }), nyckel);
  // Serverns billigaste kedja stod INTE i den gamla nyckeln: en ny
  // jämförelse kunde landa utan att butiksvalet någonsin hörde talas om den.
  assert.notEqual(branchChoiceKey({ ...bas, premium: true, cheapestChain: "Willys" }),
                  branchChoiceKey({ ...bas, premium: true, cheapestChain: "Coop" }));
});

// ---- app.js: att modulen finns räcker inte -------------------------------

const source = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
// Kommentarerna bort innan koden granskas: en kommentar som FÖRKLARAR varför
// budgeten inte längre hör hit ska inte få testet att tro att den gör det.
const kod = text => text.replace(/\/\/[^\n]*/g, "");

test("E9: butiksvalet i app.js bygger ingen veckoplan längre", () => {
  const valet = source.match(/function branchChoiceInput\(\)[\s\S]*?\nfunction cheapestStore/);
  assert.ok(valet, "branchChoiceInput() ska finnas mellan planeraren och cheapestStore()");
  assert.doesNotMatch(kod(valet[0]), /bestMenuCombo|shoppingListCost/,
    "butiksvalet ska varken planera veckan eller prissätta den - det var hela kostnaden");
  assert.doesNotMatch(kod(valet[0]), /state\.budget/,
    "budgeten hör inte hemma i butiksvalet");
});

test("E9: budgetfältet räknar inte om per tangenttryck", () => {
  const lyssnare = source.match(/\$\("budgetInput"\)\.addEventListener\("input",[^\n]*/);
  assert.ok(lyssnare, "budgetfältets input-lyssnare ska finnas kvar");
  assert.doesNotMatch(kod(lyssnare[0]), /renderBasket\(|updateSummary\(|saveState\(/,
    "input-lyssnaren ska lämna över till debouncen, inte räkna om direkt");
  assert.match(source, /debounce\(applyBudget, 250\)/, "250 ms, som uppdraget säger");
  assert.match(source, /\$\("budgetInput"\)\.addEventListener\("change"/,
    "lämnas fältet ska det sista värdet gälla omedelbart, inte gå förlorat med timern");
});
