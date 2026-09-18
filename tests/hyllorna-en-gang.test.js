// AM2: hyllorna hämtas en gång per start, hur många gånger vyn än ritas om.
//
// Mätt i webbläsaren mot dev-servern: /api/recipes/shelves?perShelf=12 två
// gånger vid boot (130 kB). renderRecipeShelves() körs vid varje omritning,
// och vakten state.hyllor.length är tom tills första svaret kommit.
import test from "node:test";
import assert from "node:assert/strict";

function fakeNode() {
  return { hidden: false, className: "", textContent: "", innerHTML: "", dataset: {},
    classList: { toggle() {}, contains: () => false, add() {}, remove() {} },
    addEventListener() {}, querySelector: () => fakeNode(), querySelectorAll: () => [] };
}
const nodes = new Map();
const byId = id => { if (!nodes.has(id)) nodes.set(id, fakeNode()); return nodes.get(id); };
globalThis.document = { baseURI: "http://localhost/app/", querySelector: () => null,
  querySelectorAll: () => [], getElementById: byId, createElement: () => fakeNode() };
globalThis.window = { location: { href: "http://localhost/app/" }, scrollTo() {}, scrollY: 0, addEventListener() {} };
globalThis.location = { search: "", pathname: "/app/", href: "http://localhost/app/" };
globalThis.history = { scrollRestoration: "auto", pushState() {}, back() {} };
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.requestAnimationFrame = () => 0;

const { initAppState, state } = await import("../frontend/app/src/state/app-state.js");
const { initRecipesView, renderRecipeShelves } = await import("../frontend/app/src/views/recipes.js");

function boot() {
  initAppState({ storage: null });
  state.hyllor = [];
  const anrop = [];
  let svara;
  const invalideringar = [];
  initRecipesView({
    loadShelves: n => { anrop.push(n); return new Promise(r => { svara = r; }); },
    invalidate: vy => invalideringar.push(vy),
    localRecipesForUser: () => [], dietFilterIsActive: () => false,
  });
  return { anrop, invalideringar, svara: hyllor => svara(hyllor) };
}

test("AM2: tre omritningar före svaret ger ETT anrop", async () => {
  const { anrop, svara, invalideringar } = boot();
  renderRecipeShelves(); renderRecipeShelves(); renderRecipeShelves();
  assert.equal(anrop.length, 1, "varje omritning startade förr ett eget anrop");
  svara([{ title: "Snabbt", recipes: [] }]);
  await new Promise(r => setTimeout(r, 0));
  assert.equal(state.hyllor.length, 1);
  assert.deepEqual(invalideringar, ["recipes"], "en omritning när hyllorna kommit, inte en per anrop");
});

test("AM2: när hyllorna finns hämtas ingenting alls", () => {
  const { anrop } = boot();
  state.hyllor = [{ title: "Finns", recipes: [] }];
  renderRecipeShelves(); renderRecipeShelves();
  assert.equal(anrop.length, 0);
});

test("AM2: ett tomt svar öppnar för ett nytt försök senare - men inte medan svaret är i luften", async () => {
  const { anrop, svara } = boot();
  renderRecipeShelves();
  renderRecipeShelves();
  assert.equal(anrop.length, 1);
  svara([]);
  await new Promise(r => setTimeout(r, 0));
  renderRecipeShelves();
  assert.equal(anrop.length, 2, "efter ett tomt svar får nästa omritning försöka igen");
  // Lämna inget i luften: shelvesInFlight är modulnivå-tillstånd, och en
  // obesvarad begäran här gjorde nästa test tomt - dess avvisande laddare
  // anropades aldrig, och sabotaget "ta bort .catch" kunde inte fälla det.
  svara([]);
  await new Promise(r => setTimeout(r, 0));
});

test("AM2: ett nätfel river inte omritningen - och läcker inte som ohanterad avvisning", async () => {
  // En ohanterad avvisning kastar inte in i anroparen, så doesNotThrow räcker
  // inte: den loggas som fel i webbläsaren. Vakten nedan gör att sabotaget
  // "ta bort .catch" faktiskt fäller testet.
  initAppState({ storage: null }); state.hyllor = [];
  let anropad = 0;
  initRecipesView({ loadShelves: () => { anropad++; return Promise.reject(new Error("nätet nere")); },
    invalidate() {}, localRecipesForUser: () => [], dietFilterIsActive: () => false });
  const ohanterade = [];
  const lyssnare = fel => ohanterade.push(fel);
  process.on("unhandledRejection", lyssnare);
  try {
    assert.doesNotThrow(() => renderRecipeShelves());
    await new Promise(r => setTimeout(r, 10));
    assert.equal(anropad, 1, "laddaren anropades inte - testet är tomt");
    assert.equal(state.hyllor.length, 0);
    assert.deepEqual(ohanterade.map(String), [], "nätfelet läckte som ohanterad avvisning");
  } finally {
    process.off("unhandledRejection", lyssnare);
  }
});
