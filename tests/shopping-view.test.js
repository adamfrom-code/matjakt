// Handla-vyn: acceptanskriterierna för E10, E11 och E14.
//
// src/views/shopping.js känner till DOM:en bara genom det den får in, så de
// tre buggarna går att pröva utan webbläsare. Varje test nedan failar på
// koden som fanns före F3 - det är hela poängen med att de står här.
import test from "node:test";
import assert from "node:assert/strict";
import { initAppState, state } from "../frontend/app/src/state/app-state.js";
import {
  aggregateShopping, chainListTotal, chainRowAmount, initShoppingView,
  prunePhantomItemNames, resetPhantomPruneGuard, weekIngredientNames,
  wireReportPriceButtons,
} from "../frontend/app/src/views/shopping.js";

function start() {
  initAppState({ storage: null, recipeBank: [] });
  initShoppingView({ recipeQuantities: {}, packageInfo: {} });
  resetPhantomPruneGuard();
}

// ---------------------------------------------------------------------------
// E10 · ETT KLICK, EN HÄNDELSE
// ---------------------------------------------------------------------------

// Precis så mycket DOM som wireReportPriceButtons rör: en nod med dataset,
// lyssnare och text. Antalet lyssnare är det testet handlar om, så noden
// räknar dem själv i stället för att låtsas vara en riktig EventTarget.
function reportButton() {
  const listeners = [];
  return {
    dataset: {},
    textContent: "Ser något fel ut?",
    disabled: false,
    addEventListener(type, handler) { if (type === "click") listeners.push(handler); },
    click() { listeners.slice().forEach(handler => handler()); },
    get listenerCount() { return listeners.length; },
  };
}

function chainListBody(buttons) {
  return { querySelectorAll: selector => (selector === "[data-report-price]" ? buttons : []) };
}

test("E10: knappen binds en gång oavsett hur många omritningar som passerar", () => {
  const button = reportButton();
  const body = chainListBody([button]);
  let events = 0;
  // Förr band renderBasket() om samma nod vid varje livepris, varje
  // synksvar och varje avbockning. Tjugo omritningar = tjugo lyssnare.
  for (let i = 0; i < 20; i += 1) {
    wireReportPriceButtons(body, { onReport: () => { events += 1; } });
  }
  assert.equal(button.listenerCount, 1, "en nod ska aldrig få mer än en lyssnare");
  button.click();
  assert.equal(events, 1, "ett klick ska skicka EN prisfel_rapporterat, inte N");
});

test("E10: klicket kvitteras på knappen och stänger av den", () => {
  const button = reportButton();
  wireReportPriceButtons(chainListBody([button]), { onReport: () => {} });
  button.click();
  assert.equal(button.textContent, "Tack! Vi kollar på det.");
  assert.equal(button.disabled, true);
});

test("E10: en ny lista som öppnas får sin egen bindning", () => {
  let events = 0;
  const onReport = () => { events += 1; };
  const first = reportButton();
  wireReportPriceButtons(chainListBody([first]), { onReport });
  const second = reportButton();
  wireReportPriceButtons(chainListBody([second]), { onReport });
  second.click();
  assert.equal(events, 1);
  first.click();
  assert.equal(events, 2, "den tidigare listans knapp ska fortfarande fungera");
});

// ---------------------------------------------------------------------------
// E11 · RADERNA SUMMERAR TILL RUBRIKEN
// ---------------------------------------------------------------------------

const twentyRows = Array.from({ length: 20 }, (_, index) => ({
  ingredient: `Vara ${index + 1}`,
  priceStatus: "current",
  totalCost: 12.49,
}));

test("E11: rubriken är summan av de belopp raderna faktiskt visar", () => {
  // Flyttalssumman är 249,80 och rundas till 250. Raderna skriver ut 12 kr
  // var - tjugo rader som läser 240. Tio kronors skillnad i den enda ruta
  // vars uppgift är att rubriken och listan säger samma sak.
  const floatSum = twentyRows.reduce((sum, item) => sum + item.totalCost, 0);
  assert.equal(Math.round(floatSum), 250, "så räknade den gamla rubriken");
  assert.equal(chainListTotal(twentyRows), 240);
  assert.equal(
    chainListTotal(twentyRows),
    twentyRows.reduce((sum, item) => sum + chainRowAmount(item), 0),
    "rubriken måste vara exakt summan av radbeloppen",
  );
});

test("E11: rader utan belopp bidrar med ingenting", () => {
  const items = [
    { ingredient: "Mjölk", priceStatus: "current", totalCost: 17.5 },
    { ingredient: "Honung", priceStatus: "current", totalCost: null },   // antal osäkert
    { ingredient: "Saffran", priceStatus: "missing", totalCost: 39 },    // pris saknas
    { ingredient: "Skräp", priceStatus: "current", totalCost: "inte ett tal" },
  ];
  assert.equal(chainRowAmount(items[1]), null);
  assert.equal(chainRowAmount(items[2]), null);
  assert.equal(chainRowAmount(items[3]), null);
  assert.equal(chainListTotal(items), 18);
});

test("E11: hundra rader driver inte iväg i flyttalsbråk", () => {
  const items = Array.from({ length: 100 }, () => ({ priceStatus: "current", totalCost: 0.7 }));
  // 0,7 avrundas till 1 kr på raden; hundra rader är alltså exakt 100 kr.
  assert.equal(chainListTotal(items), 100);
  assert.equal(chainListTotal([]), 0);
  assert.equal(chainListTotal(undefined), 0);
});

// ---------------------------------------------------------------------------
// E14 · AGGREGATET RÄKNAR, DET MUTERAR INTE
// ---------------------------------------------------------------------------

// Ett kort utan receptdetaljer: bara namnen, valfria ingredienser inkluderade.
const pastaCard = {
  id: "pasta",
  namn: "Pasta med sardeller",
  ingredienser: ["Pasta", "Sardeller", "Persilja"],
};

// Samma recept när detaljen landat: strukturerade rader, och persiljan
// märkt optional - vilket aggregatet filtrerar bort.
const pastaDetail = {
  id: "pasta",
  namn: "Pasta med sardeller",
  servings: 4,
  ingredienser: ["Pasta", "Sardeller", "Persilja"],
  ingredients: [
    { name: "Pasta", amount: 400, unit: "g" },
    { name: "Sardeller", amount: 1, unit: "burk" },
    { name: "Persilja", amount: 1, unit: "kruka", optional: true },
  ],
};

test("E14: aggregateShopping muterar ingenting", () => {
  start();
  state.removedItems.add("Spöknamn");
  state.avklarade.add("Pasta");
  state.harHemma.add("Persilja");
  const before = {
    removed: [...state.removedItems],
    avklarade: [...state.avklarade],
    harHemma: [...state.harHemma],
  };
  aggregateShopping([pastaDetail]);
  aggregateShopping([pastaDetail]);
  assert.deepEqual([...state.removedItems], before.removed);
  assert.deepEqual([...state.avklarade], before.avklarade);
  assert.deepEqual([...state.harHemma], before.harHemma);
});

test("E14: en valfri ingrediens tappar inte sin köpt-status när detaljen landar", () => {
  start();
  state.avklarade.add("Persilja");
  state.avklarade.add("Pasta");
  // Aggregatet känner INTE persiljan: den strukturerade grenen filtrerar
  // bort optional. En namnlista byggd på aggregatet ensamt hade raderat
  // användarens avbockning tyst, i samma sekund som detaljen landade.
  assert.ok(!aggregateShopping([pastaDetail]).some(item => item.namn === "Persilja"));
  assert.ok(weekIngredientNames([pastaDetail]).has("Persilja"));
  prunePhantomItemNames([pastaDetail]);
  assert.ok(state.avklarade.has("Persilja"), "valfria ingredienser är riktiga varor");
  assert.ok(state.avklarade.has("Pasta"));
});

test("E14: spöknamn efter ett receptbyte beskärs", () => {
  start();
  state.removedItems.add("Sardeller");   // fanns i förra veckans rätt
  state.avklarade.add("Sardeller");
  state.harHemma.add("Sardeller");
  state.avklarade.add("Pasta");
  const soppa = { id: "soppa", namn: "Linssoppa", servings: 4,
                  ingredienser: ["Linser", "Pasta"],
                  ingredients: [{ name: "Linser", amount: 300, unit: "g" },
                                { name: "Pasta", amount: 200, unit: "g" }] };
  assert.equal(prunePhantomItemNames([soppa]), true);
  assert.ok(!state.removedItems.has("Sardeller"));
  assert.ok(!state.avklarade.has("Sardeller"));
  assert.ok(!state.harHemma.has("Sardeller"));
  assert.ok(state.avklarade.has("Pasta"), "namn som veckan fortfarande ber om rörs inte");
});

test("E14: beskärningen körs en gång per vecka, inte per omritning", () => {
  start();
  state.removedItems.add("Sardeller");
  assert.equal(prunePhantomItemNames([pastaCard]), false,
               "kortets egna namn räknas - sardellerna är inte spöken än");
  state.removedItems.add("Kapris");
  // Samma vecka i samma laddningsläge: ingen ny beskärning, alltså ingen
  // sparning och ingen omritning heller.
  assert.equal(prunePhantomItemNames([pastaCard]), false);
  assert.ok(state.removedItems.has("Kapris"));
  // Detaljen landar - veckan har ett nytt laddningsläge och beskärs på nytt.
  assert.equal(prunePhantomItemNames([pastaDetail]), true);
  assert.ok(!state.removedItems.has("Kapris"));
  assert.ok(state.removedItems.has("Sardeller"), "sardellerna står kvar i receptet");
});

test("E14: en tom vecka beskär ingenting", () => {
  start();
  state.removedItems.add("Sardeller");
  state.avklarade.add("Pasta");
  assert.equal(prunePhantomItemNames([]), false, "under uppstart är veckan tom, inte ogiltig");
  assert.equal(prunePhantomItemNames([null, null]), false);
  assert.ok(state.removedItems.has("Sardeller"));
  assert.ok(state.avklarade.has("Pasta"));
});
