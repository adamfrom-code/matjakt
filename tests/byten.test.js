// G10:s acceptanskriterium: ett tryck byter rätten.
//
// Flödet var "Byt" → modal → tryck på alternativet (som bara MARKERADE) →
// "Byt till denna rätt". Två tryck där ett räcker, och en bekräftelseknapp
// för en handling som är helt riskfri. Dessutom `FREE_SWAP_LIMIT = 3`, som
// stängde dörren efter tre byten - utan förvarning, och synlig först när man
// slagit i taket.
//
// Byte är den handling som gör veckan TILL DIN. Att strypa den straffar
// precis det engagemang som bygger vana, och det som såldes var "fler av
// samma sak". Det som säljs nu är byten MED AVSIKT.
//
// Att trycket verkligen byter och att Ångra verkligen tar tillbaka prövas i
// webbläsaren: test_ett_tryck_byter_ratten_och_angra_tar_tillbaka_den.

import assert from "node:assert/strict";
import test from "node:test";
import { läsFil } from "./fixtures/css-parser.mjs";
import { initAppState, selectedRecipes, setWeekPlan, state, swapWeekPlanDay }
  from "../frontend/app/src/state/app-state.js";

const html = läsFil("frontend/app/index.html");
const app = läsFil("frontend/app/app.js");

// Prosa i en kommentar är ingen kod. Paketet FÅR skriva "FREE_SWAP_LIMIT = 3
// stängde dörren" i en förklaring - det är just den sortens rad som gör att
// nästa läsare förstår varför taket är borta. Svepet nedan läser därför bara
// kod. (Samma knep som app-imports.test.js.)
const utanKommentarer = (text) => text
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .split("\n").filter((rad) => !/^\s*\/\//.test(rad)).join("\n");
const appKod = utanKommentarer(app);

// ---------------------------------------------------------------------------
// TAKET
// ---------------------------------------------------------------------------

test("det finns inget tak på antalet byten", () => {
  assert.ok(!/FREE_SWAP_LIMIT/.test(appKod),
    "FREE_SWAP_LIMIT finns kvar i koden - bytena är fortfarande ransonerade");
  assert.ok(!/swapsThisWeek >= /.test(appKod),
    "något jämför fortfarande veckans byten mot ett tak");
  assert.ok(!/gratis byten den här veckan/.test(appKod),
    "texten om förbrukade gratisbyten finns kvar");
});

test("premiumlistan lovar inte längre något som är gratis", () => {
  assert.ok(!/Obegränsade byten/.test(html),
    'premiumlistan säljer fortfarande "obegränsade byten", som numera ingår gratis');
  assert.match(html, /Byten med avsikt/,
    "listan säger inte vad som faktiskt är Premium i bytena");
});

// ---------------------------------------------------------------------------
// ETT TRYCK
// ---------------------------------------------------------------------------

test('"Byt till denna rätt" är borta ur både markup och kod', () => {
  assert.ok(!/swapConfirmBtn/.test(html), "bekräftelseknappen finns kvar i index.html");
  assert.ok(!/swapConfirmBtn/.test(appKod), "app.js rör fortfarande bekräftelseknappen");
});

test("trycket på ett alternativ byter rätten direkt", () => {
  assert.match(app, /\[data-choose-swap\][\s\S]{0,200}swapDay\(dayIndex, button\.dataset\.chooseSwap\)/,
    "ett tryck på alternativet gör fortfarande något annat än att byta");
  // Markeringen var hela mellansteget. Finns den kvar finns två tryck kvar.
  assert.ok(!/swapContext\.selectedId/.test(appKod),
    "alternativen markeras fortfarande i stället för att byta");
});

test("bytet har Ångra i toasten, inte en bekräftelse före", () => {
  assert.match(app, /function swapDay\(dayIndex, newId\)[\s\S]{0,900}showUndoToast\(/,
    "bytet visar ingen Ångra-toast");
  assert.match(app, /showUndoToast\([\s\S]{0,160}applySwap\(dayIndex, previousId\)/,
    "Ångra i toasten lägger inte tillbaka den förra rätten");
});

// ---------------------------------------------------------------------------
// DET SOM SÄLJS I STÄLLET
// ---------------------------------------------------------------------------

test('"Något annat" är gratis, avsikterna är Premium', () => {
  assert.match(app, /const swapIntentLocked = intentId => Boolean\(intentId\) && !hasPremium\(\)/,
    "låset sitter inte på avsikten - antingen låses allt eller inget");
  assert.match(app, /if \(swapIntentLocked\(id\)\) \{[^}]*openPaywall\("swap_intent"\)/,
    "en låst avsikt öppnar inte betalväggen");
});

test("låset syns på knappen, inte först efter trycket", () => {
  // En vägg man går in i är något annat än ett erbjudande man ser. Låset
  // bärs dessutom av ett ORD och inte bara av en klass, så det överlever
  // gråskala och når skärmläsaren - samma regel som prisreglerna i L0, och
  // samma ordval som det låsta butikskortets "Se pris med Premium". En
  // hänglåsemoji vore både en ikon som inte säger något och ett brott mot
  // designregeln i test_frontend_contract.
  assert.match(app, /locked \? " locked" : ""/, "den låsta avsikten får ingen egen klass");
  assert.match(app, /locked \? ' <span class="swap-intent-lock">Premium<\/span>' : ""/,
    "låset syns inte i knappens egen form");
  assert.match(app, /ingår i Premium/, "skärmläsaren får inte veta att avsikten är låst");
});

// ---------------------------------------------------------------------------
// ...OCH ATT ETT BYTE GÅR ATT TA TILLBAKA
// ---------------------------------------------------------------------------

test("ett byte och dess ångrande lämnar veckan precis som den var", () => {
  // Grunden Ångra-toasten vilar på: dagen byts på plats, och att byta
  // tillbaka samma dag ger exakt ursprungsveckan - inte en vecka med samma
  // rätter i annan ordning, och inte ett valda-Set som glömt något.
  initAppState({ storage: null, recipeBank: [] });
  setWeekPlan(["mån", "tis", "ons", "tor"]);
  const innan = [...state.weekPlan];
  const valdaInnan = [...state.valda].sort();

  swapWeekPlanDay(2, "ny-ons");
  assert.deepEqual(state.weekPlan, ["mån", "tis", "ny-ons", "tor"]);
  assert.ok(state.valda.has("ny-ons") && !state.valda.has("ons"));

  swapWeekPlanDay(2, "ons");
  assert.deepEqual(state.weekPlan, innan, "veckan kom inte tillbaka som den var");
  assert.deepEqual([...state.valda].sort(), valdaInnan, "valda-setet läkte inte");
});

test("ett byte flyttar ingen annan dag", () => {
  // E2:s dagsindexfel i en annan form: byts dagen genom att ta bort och
  // lägga till hamnar rätten sist i veckan i stället för på sin dag.
  initAppState({ storage: null, recipeBank: [] });
  setWeekPlan(["a", "b", "c", "d", "e"]);
  swapWeekPlanDay(0, "ny");
  assert.deepEqual(state.weekPlan, ["ny", "b", "c", "d", "e"]);
  assert.equal(selectedRecipes().length, 5, "veckan bytte längd av ett byte");
});
