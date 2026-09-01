import test from "node:test";
import assert from "node:assert/strict";
import { aggregateIngredients, budgetRemaining, calculateLiveShoppingTotal, calculateShoppingTotal, clampBudget, packagesFor, portionFactor } from "../frontend/app/src/services/calculations.js";

const recipes = [{ id: "pasta", ingredienser: ["Pasta", "Tomat"] }, { id: "soppa", ingredienser: ["Tomat"] }];
const quantities = { pasta: { Pasta: [250, "g"], Tomat: [1, "st"] }, soppa: { Tomat: [2, "st"] } };
const packages = { Pasta: { amount: 500, unit: "g" }, Tomat: { amount: 1, unit: "st" } };

test("portionsskalning ökar jämnt med antal personer, inte hoppvis var 4:e person", () => { assert.equal(portionFactor(4), 1); assert.equal(portionFactor(2), 0.5); assert.equal(portionFactor(8), 2); assert.equal(portionFactor(1), 0.25); assert.ok(portionFactor(2) < portionFactor(3), "fler personer ska alltid ge mer mat"); });
test("ingredienssummering", () => { const items = aggregateIngredients(recipes, quantities, packages, 5); assert.equal(items.find(item => item.namn === "Pasta").total, 312.5); assert.equal(items.find(item => item.namn === "Tomat").total, 3.75); });
test("shoppinglistans totalsumma använder hela paket och skafferi", () => { const items = aggregateIngredients([recipes[0]], quantities, packages, 4); assert.equal(calculateShoppingTotal(items, { Pasta: { pris: 20 }, Tomat: { pris: 5 } }, { Pasta: 100 }), 25); });
test("budgetberäkning", () => { assert.equal(budgetRemaining(500, 420), 80); assert.equal(budgetRemaining(400, 420), -20); });
test("budget klampas till 0 eller mer", () => { assert.equal(clampBudget(-100), 0); assert.equal(clampBudget("abc"), 0); assert.equal(clampBudget("650"), 650); });

test("live-totalsumma räknar aldrig en saknad pris (null) som 0 kr", () => {
  const items = [{ namn: "Citron", total: 1, package: null }, { namn: "Ris", total: 250, package: { amount: 1000 } }];
  const chainProducts = { Citron: { pris_kr: null }, Ris: { pris_kr: 28 } };
  const result = calculateLiveShoppingTotal(items, chainProducts);
  assert.equal(result.cost, 28, "endast Ris pris ska räknas in - Citrons null-pris ska inte tolkas som 0");
  assert.equal(result.matched, 2, "båda varorna hittade en produkt");
  assert.equal(result.certain, 1, "bara Ris har ett säkert pris");
  assert.equal(result.totalItems, 2);
});

test("live-totalsumma skiljer på 'ingen produkt hittad' och 'produkt hittad men pris saknas'", () => {
  const items = [{ namn: "Saffran", total: 1, package: null }, { namn: "Ris", total: 250, package: { amount: 1000 } }];
  // Saffran has no entry at all in chainProducts (no confident match found by best_match)
  const chainProducts = { Ris: { pris_kr: null } };
  const result = calculateLiveShoppingTotal(items, chainProducts);
  assert.equal(result.matched, 1, "bara Ris hittades alls som produkt");
  assert.equal(result.certain, 0, "Ris produkt hittades men saknar pris - inte säkert");
  assert.equal(result.cost, 0);
});

test("live-totalsumma räknar bort det som redan finns i skafferiet, precis som den statiska", () => {
  const items = [{ namn: "Ris", total: 500, package: { amount: 1000 } }];
  const chainProducts = { Ris: { pris_kr: 28 } };
  assert.equal(calculateLiveShoppingTotal(items, chainProducts, { Ris: 500 }).cost, 0, "500g behövs, 500g finns redan hemma");
});

// ---- Enhetsmedvetet aggregat (RC-audit 2026-09-01) -------------------------
// "2 st morötter" + "400 g morötter" är inte "402 st" - en verklig rad ur
// banken som visades exakt så. Samma familj summeras i basenheter; olika
// familjer förblir egna rader, precis som backend-aggregatet.
test("blandade enheter summeras aldrig numeriskt", () => {
  const recipes = [
    { servings: 4, ingredients: [{ name: "Morötter", amount: 2, unit: "st" }] },
    { servings: 4, ingredients: [{ name: "Morötter", amount: 400, unit: "g" }] },
    { servings: 4, ingredients: [{ name: "Mjölk", amount: 1, unit: "l" }] },
    { servings: 4, ingredients: [{ name: "Mjölk", amount: 1, unit: "dl" }] },
  ];
  const rows = aggregateIngredients(recipes, {}, {}, 4);
  const carrots = rows.filter(row => row.namn === "Morötter");
  assert.equal(carrots.length, 2, "st och g är egna rader");
  const milk = rows.filter(row => row.namn === "Mjölk");
  assert.equal(milk.length, 1, "l + dl är samma volymfamilj");
  assert.equal(milk[0].baseAmount, 1100, "1 l + 1 dl = 1100 ml");
  assert.equal(milk[0].unit, "l");
});

test("skafferi och paket räknar i samma basenheter", () => {
  const item = { namn: "Grädde", total: 5, unit: "dl", baseAmount: 500,
                 family: "vol", package: { amount: 200, unit: "ml" } };
  // 500 ml behov - 200 ml hemma = 300 ml -> 2 paket à 200 ml
  assert.equal(packagesFor(item, { "Grädde": 200 }), 2);
  // Utan skafferi: 3 paket
  assert.equal(packagesFor(item, {}), 3);
  // Allt hemma: 0 paket
  assert.equal(packagesFor(item, { "Grädde": 500 }), 0);
});

// ---- RELEASE GATE (2026-09-02): 224 g fiskpinnar blev 224 paket ------------
// Vikt/volym utan känd förpackning får ALDRIG räknas som styck. null betyder
// "antal osäkert" - raden hålls utanför summor och certain-räknaren.
test("vikt utan paketinfo ger null - aldrig gram-som-paket", () => {
  const item = { namn: "Fiskpinnar", total: 224, unit: "g", baseAmount: 224, family: "vikt" };
  assert.equal(packagesFor(item, {}), null);
  const live = calculateLiveShoppingTotal([item], { Fiskpinnar: { pris_kr: 29.29 } }, {});
  assert.equal(live.cost, 0, "6 561 kr-buggen: osäker rad får inte kosta");
  assert.equal(live.certain, 0, "osäker rad är inte 'säkert pris'");
  assert.equal(live.matched, 1, "produkten är ändå identifierad");
});

test("styck utan paketinfo räknas fortfarande (1 vara = 1 st)", () => {
  const item = { namn: "Gurka", total: 2, unit: "st", baseAmount: 2, family: "styck:st" };
  assert.equal(packagesFor(item, {}), 2);
});

test("persilja 10 g mot 50 g-paket är 1 förpackning", () => {
  const item = { namn: "Persilja", total: 10, unit: "g", baseAmount: 10,
                 family: "vikt", package: { amount: 50, unit: "g" } };
  assert.equal(packagesFor(item, {}), 1);
});
