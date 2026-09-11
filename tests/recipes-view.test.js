// E12: provider-recept dubbelescapades.
//
// `mapApiRecipe` escapade instruktionerna vid INTAGET och renderingen
// escapade dem en gång till vid utskrift. Ett recept som säger
// "salt & peppar" stod därför på skärmen som "salt &amp; peppar".
//
// Rättningen är att ta bort den TIDIGA escapningen. Att i stället ta bort
// den sena hade också fått "&"-tecknet att se rätt ut - och samtidigt
// öppnat en XSS-lucka, eftersom instruktionstexten kommer från en extern
// receptkälla. Därför prövar varje test här BÅDA halvorna: att "&" når
// skärmen som "&", och att "<script>" fortfarande escapas på vägen ut.
//
// Testet kör de riktiga renderarna mot en DOM-stubbe i stället för att
// granska markup-strängar för sig: det är hela vägen från API-svar till
// innerHTML som ska vara escapad exakt en gång.
import test from "node:test";
import assert from "node:assert/strict";

function fakeNode() {
  const node = {
    hidden: false,
    className: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    classList: { toggle() {}, contains: () => false, add() {}, remove() {} },
    addEventListener() {},
    querySelector: () => fakeNode(),
    querySelectorAll: () => [],
  };
  return node;
}

const nodes = new Map();
const byId = id => {
  if (!nodes.has(id)) nodes.set(id, fakeNode());
  return nodes.get(id);
};

globalThis.document = {
  baseURI: "http://localhost/app/",
  querySelector: () => null,          // ingen <meta> med API-adress
  querySelectorAll: () => [],
  getElementById: byId,
  createElement: () => fakeNode(),
};
globalThis.window = { location: { href: "http://localhost/app/" }, scrollTo() {}, scrollY: 0, addEventListener() {} };
globalThis.location = { search: "?recept=prov:42", pathname: "/app/", href: "http://localhost/app/?recept=prov:42" };
globalThis.history = { scrollRestoration: "auto", pushState() {}, back() {} };
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.requestAnimationFrame = () => 0;

// Dynamisk import EFTER stubbarna: api/config.js läser <meta> och
// data/recipes.js läser document.baseURI redan vid modulinläsning.
const { initAppState, state } = await import("../frontend/app/src/state/app-state.js");
const { initRecipesView, mapApiRecipe, renderRecipePage, renderRecipes } =
  await import("../frontend/app/src/views/recipes.js");

// Så här ser ett provider-recept ut när det kommer ur /recipes/search.
const API_RECIPE = {
  id: "prov:42",
  provider: "extern",
  providerRecipeId: "42",
  title: "Ugnsbakad torsk",
  prepMinutes: 25,
  servings: 4,
  ingredients: [{ measure: "500 g", name: "Torskrygg" }],
  instructions: [
    "Krydda torsken med salt & peppar.",
    "Servera med <script>alert(1)</script> och citron.",
  ],
};

const SAFE_STEP = "Krydda torsken med salt &amp; peppar.";
const DOUBLE_ESCAPED = "salt &amp;amp; peppar";
const ESCAPED_SCRIPT = "&lt;script&gt;alert(1)&lt;/script&gt;";

function bootView() {
  initAppState({ storage: null });
  initRecipesView({
    recipeBank: [],
    // Samma form som app.js detailsFor ger ett provider-recept: den
    // handskrivna legacy-tabellen har ingen rad för ett provider-id, så
    // receptets egen text är den enda som finns.
    detailsFor: recipe => ({ beskrivning: recipe.beskrivning, steg: recipe.steg || [], tips: undefined }),
    localRecipesForUser: () => [],
    dietFilterIsActive: () => false,
    selectedBranch: () => null,
    nearbyBranches: () => [],
    money: value => `${Math.round(value)} kr`,
    plural: (n, one, many) => `${n} ${n === 1 ? one : many}`,
  });
  const recipe = mapApiRecipe(API_RECIPE);
  state.apiRecipes = [recipe];
  return recipe;
}

test("mapApiRecipe sparar instruktionerna RÅA - escapning hör till utskriften", () => {
  const recipe = mapApiRecipe(API_RECIPE);
  assert.deepEqual(recipe.steg, [
    "Krydda torsken med salt & peppar.",
    "Servera med <script>alert(1)</script> och citron.",
  ]);
});

test("receptsidan visar 'salt & peppar' - och escapar <script> på vägen ut", async () => {
  bootView();
  await renderRecipePage();
  const html = byId("recipePage").innerHTML;

  // Halva ett: tecknet användaren skrev når skärmen som sig självt.
  assert.ok(html.includes(SAFE_STEP), `steget saknas eller är fel escapat:\n${html.slice(0, 400)}`);
  assert.ok(!html.includes(DOUBLE_ESCAPED), "instruktionen är dubbelescapad igen");

  // Halva två: samma text från en extern källa får fortfarande inte bli
  // körbar markup. Utan den här raden skulle testet passera även om man
  // tagit bort escapningen i FEL ände.
  assert.ok(html.includes(ESCAPED_SCRIPT), "instruktionssteget escapas inte vid utskrift");
  assert.ok(!html.includes("<script>"), "rå <script> nådde receptsidans markup");
});

test("receptkortets utfällda steg escapas också exakt en gång", () => {
  const recipe = bootView();
  state.sokning = "torsk";
  state.expanded = recipe.id;
  renderRecipes();
  const html = byId("recipeScroll").innerHTML;

  assert.ok(html.includes(SAFE_STEP), `steget saknas eller är fel escapat:\n${html.slice(0, 400)}`);
  assert.ok(!html.includes(DOUBLE_ESCAPED), "instruktionen är dubbelescapad igen");
  assert.ok(html.includes(ESCAPED_SCRIPT), "instruktionssteget escapas inte vid utskrift");
  assert.ok(!html.includes("<script>"), "rå <script> nådde receptkortets markup");
});

test("receptets NAMN escapas vid utskrift, inte vid intag", () => {
  const recipe = mapApiRecipe({ ...API_RECIPE, title: "Torsk & potatis" });
  assert.equal(recipe.namn, "Torsk & potatis");

  initAppState({ storage: null });
  state.apiRecipes = [recipe];
  state.sokning = "torsk";
  renderRecipes();
  const html = byId("recipeScroll").innerHTML;
  assert.ok(html.includes("Torsk &amp; potatis"));
  assert.ok(!html.includes("Torsk &amp;amp; potatis"));
});
