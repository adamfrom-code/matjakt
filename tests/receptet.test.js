// L4: Receptet byggt som telefon 4 i design D.
//
// Testet prövar två saker, och båda är sådant som går sönder tyst.
//
// 1. ESCAPNINGEN HÅLLER ÅT BÅDA HÅLLEN. F4 rättade E12 genom att ta bort
//    escapningen vid INTAGET och behålla den vid utskriften. Skärmen byggs nu
//    om, och varje rad som flyttar är ett tillfälle att råka ta bort fel
//    sida. Därför prövas båda halvorna i samma påstående: att "salt & peppar"
//    når skärmen som sig självt, OCH att "<script>" i samma fält fortfarande
//    escapas på vägen ut. Ett test som bara kollade det första hade passerat
//    även på den farliga rättningen - då hade ett kosmetiskt fel bytts mot en
//    XSS-lucka, och texten kommer från en extern receptkälla.
//
//    Nytt i L4: ingrediensnamnen går nu genom mängd/namn-kolumnerna och
//    "Har du hemma"-raden. Det är tre nya utskriftsställen för text från
//    samma källa, och alla tre prövas här.
//
// 2. MÄNGDKOLUMNEN HAR tabular-nums. Utan den är siffrorna olika breda,
//    kolumnen hoppar i sidled mellan raderna och listan går inte att svepa
//    med blicken - vilket är hela poängen med att dela upp raden i två
//    kolumner. Kravet läses ur styles.css, och testet visar att det har
//    tänder genom att också pröva en fil där deklarationen är borta.
//
// Renderaren körs på riktigt mot en DOM-stubbe. Det är hela vägen från
// API-svar till innerHTML som ska stämma, inte en markup-sträng för sig.
import test from "node:test";
import assert from "node:assert/strict";
import { deklarationer, läsStyles, parseRegler } from "./fixtures/css-parser.mjs";

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
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: byId,
  createElement: () => fakeNode(),
};
globalThis.window = { location: { href: "http://localhost/app/" }, scrollTo() {}, scrollY: 0, addEventListener() {} };
globalThis.location = { search: "", pathname: "/app/", href: "http://localhost/app/" };
globalThis.history = { scrollRestoration: "auto", pushState() {}, back() {} };
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.requestAnimationFrame = () => 0;

const { initAppState, state } = await import("../frontend/app/src/state/app-state.js");
const { initRecipesView, mapApiRecipe, renderRecipePage } =
  await import("../frontend/app/src/views/recipes.js");
const { SAKNAS, UPPSKATTAT, prisMarkup } = await import("../frontend/app/src/views/pris.js");

// Ett bankrecept som det ser ut när detaljen har hämtats: strukturerade
// ingredienser med tal och enhet, skafferivaror utpekade, ett riktigt
// portionspris. Namnen bär med flit både "&" och "<script>".
const BANKRECEPT = {
  id: "lax-i-ugn",
  namn: "Laxfilé i ugn med dill",
  typ: "Fisk",
  tid: 20,
  servings: 4,
  portionspris: 52,
  priceStatus: "priced",
  beskrivning: "Laxen i ugnsform med crème fraiche.",
  bild: "https://images.pexels.com/photos/1/lax.jpeg?h=940&w=1400",
  ingredienser: ["Laxfilé", "Färsk dill"],
  hemma: [],
  steg: [
    "Krydda laxen med salt & peppar.",
    "Servera med <script>alert(1)</script> och citron.",
  ],
  ingredients: [
    { name: "Laxfilé", amount: 600, unit: "g" },
    { name: "Dill & persilja", amount: 1, unit: "kruka" },
    { name: "Crème fraiche <script>alert(2)</script>", amount: 2, unit: "dl" },
    { name: "Kapris", amount: 1, unit: "msk", optional: true },
    { name: "Salt & peppar", pantryStaple: true },
    { name: "Smör <script>alert(3)</script>", pantryStaple: true },
  ],
};

// Så ser ett provider-recept ut när det kommer ur /recipes/search: mängden är
// färdig text, och priset finns inte.
const API_RECEPT = {
  id: "prov:42",
  provider: "extern",
  providerRecipeId: "42",
  title: "Ugnsbakad torsk",
  prepMinutes: 25,
  servings: 4,
  ingredients: [
    { measure: "500 g", name: "Torskrygg" },
    { measure: "1 msk", name: "Salt & peppar" },
  ],
  instructions: ["Krydda torsken med salt & peppar."],
};

function boot({ bank = [], api = [] } = {}) {
  initAppState({ storage: null });
  state.personer = 4;
  state.apiRecipes = api;
  initRecipesView({
    recipeBank: bank,
    recipeDetailFetches: new Set(),
    detailsFor: recipe => ({ beskrivning: recipe.beskrivning, steg: recipe.steg || [], tips: undefined }),
    localRecipesForUser: () => [],
    dietFilterIsActive: () => false,
    selectedBranch: () => null,
    nearbyBranches: () => [],
    money: värde => `${Math.round(värde)} kr`,
    plural: (n, one, many) => `${n} ${n === 1 ? one : many}`,
  });
}

async function rita(id, options) {
  boot(options);
  globalThis.location.search = `?recept=${encodeURIComponent(id)}`;
  await renderRecipePage();
  return byId("recipePage").innerHTML;
}

const SÄKER_TEXT = "salt &amp; peppar";
const DUBBELESCAPAD = "&amp;amp;";
const ESCAPAD_SCRIPT = "&lt;script&gt;";

// --------------------------------------------------------------- strukturen

test("fotot är helbleed och rubriken ligger på det", async () => {
  const html = await rita("lax-i-ugn", { bank: [structuredClone(BANKRECEPT)] });
  assert.match(html, /<figure class="recepthero">/,
    "hjältefotot saknas - skärmen börjar inte med bilden");
  // Rubriken ligger INUTI figuren, i bildtextfältet. Ligger den utanför är
  // den inte "på bilden", hur den än ser ut.
  const hero = /<figure class="recepthero">([\s\S]*?)<\/figure>/.exec(html);
  assert.ok(hero, "recepthero är inte en sluten figure");
  assert.match(hero[1], /<figcaption class="titel">[\s\S]*<h1>/,
    "rubriken ligger inte i bildtexten på fotot");
  assert.match(hero[1], /<img class="recipe-photo"/, "fotot renderades inte som bild");
});

test("portionspriset är bildtext, och markupen kommer ur L0:s komponent", async () => {
  const html = await rita("lax-i-ugn", { bank: [structuredClone(BANKRECEPT)] });

  // Bildtext, inte utrop: en kapitäletikett och ett tal - ingen stor siffra
  // och ingen egen prismarkup i den här vyn.
  assert.match(html, /<div class="receptmeta"><span class="kap">Pris per portion<\/span>/,
    "portionspriset står inte som bildtext under fotot");

  // Exakt komponentens utdata. Skulle vyn bygga en egen span som "råkar" se
  // likadan ut idag, glider de isär i morgon - det är hela skälet till att
  // L0 finns. Tillståndet är UPPSKATTAT: bankens portionspris är räknat, inte
  // verifierat i butiken användaren går till.
  assert.ok(html.includes(prisMarkup(52, UPPSKATTAT)),
    `portionspriset är inte prisMarkup(52, UPPSKATTAT):\n${html.slice(0, 600)}`);
});

test("ett recept utan prissättning får en öppen ram, inte ett påhittat tal", async () => {
  const html = await rita("prov:42", { api: [mapApiRecipe(API_RECEPT)] });
  assert.ok(html.includes(prisMarkup(null, SAKNAS)),
    "provider-receptet visar inte pris saknas via L0:s komponent");
  assert.ok(!/ca\s*0\s*kr|NaN/.test(html), "ett tal hittades på där det inte finns något");
});

test("ingredienserna står i två kolumner: mängd för sig, namn bredvid", async () => {
  const html = await rita("lax-i-ugn", { bank: [structuredClone(BANKRECEPT)] });
  const rader = [...html.matchAll(/<div class="ingrrad[^"]*">([\s\S]*?)<\/div>/g)].map(m => m[1]);
  assert.equal(rader.length, 4, `väntade fyra köprader, fick ${rader.length}`);
  for (const rad of rader) {
    assert.match(rad, /^<span class="mangd2">[^<]*<\/span><span class="namn2">/,
      `raden har inte mängden i egen kolumn före namnet: ${rad}`);
  }
  assert.match(rader[0], /<span class="mangd2">600 g<\/span>/, "mängden skalades inte rätt");
  assert.match(rader[3], /\(valfritt\)/, "valfri ingrediens tappade sin markering");
});

test("'Har du hemma' är en tonad rad, inte en utelämnad", async () => {
  const html = await rita("lax-i-ugn", { bank: [structuredClone(BANKRECEPT)] });
  const rad = /<div class="hemma">([\s\S]*?)<\/div>/.exec(html);
  assert.ok(rad, "skafferivarorna försvann ur listan i stället för att tonas ned");
  assert.match(rad[1], /<span class="kap">Har du hemma<\/span>/);
  // Båda skafferivarorna ska stå där. En vara som räknats bort ur priset ska
  // synas att den räknats bort - annars köps saltet en gång till.
  assert.match(rad[1], /Salt &amp; peppar/);
  assert.match(rad[1], /Sm(ö|&ouml;)r/);

  // ...och den är tonad i CSS: nedsänkt fält, inte samma yta som köpraderna.
  const regler = parseRegler(läsStyles());
  const hemma = regler.filter(r => r.delar.includes(".hemma"));
  assert.ok(hemma.length, ".hemma har ingen regel - raden ser ut som vilken rad som helst");
  const bakgrund = hemma.flatMap(r => deklarationer(r.block)).filter(d => d.prop === "background");
  assert.ok(bakgrund.some(d => d.värde.includes("--paper-2")),
    "'Har du hemma' ligger inte på det nedsänkta fältet --paper-2");
});

test("stegen är numrerade och avbockningsbara", async () => {
  const html = await rita("lax-i-ugn", { bank: [structuredClone(BANKRECEPT)] });
  const steg = [...html.matchAll(/<label class="steg">([\s\S]*?)<\/label>/g)].map(m => m[1]);
  assert.equal(steg.length, 2, `väntade två steg, fick ${steg.length}`);
  steg.forEach((rad, index) => {
    assert.match(rad, new RegExp(`<span class="nr">${index + 1}</span>`),
      `steg ${index + 1} är inte numrerat`);
    assert.match(rad, new RegExp(`<input type="checkbox" data-step-check="${index}">`),
      `steg ${index + 1} går inte att bocka av`);
  });
});

// -------------------------------------------------- escapningen, båda hållen

test("skärmen visar 'salt & peppar' - och escapar <script> på vägen ut", async () => {
  const html = await rita("lax-i-ugn", { bank: [structuredClone(BANKRECEPT)] });

  // HALVA ETT: tecknet källan skrev når skärmen som sig självt. Prövas på
  // alla tre ställen L4 skriver ut text: instruktionssteget, ingrediensens
  // namnkolumn och "Har du hemma"-raden.
  assert.ok(html.includes(`Krydda laxen med ${SÄKER_TEXT}.`), "steget är fel escapat");
  assert.ok(html.includes(`<span class="namn2">Dill &amp; persilja</span>`),
    "ingrediensnamnet är fel escapat i namnkolumnen");
  assert.ok(html.includes("Salt &amp; peppar"), "skafferiraden är fel escapad");
  assert.ok(!html.includes(DUBBELESCAPAD), `något är dubbelescapat igen:\n${html.slice(0, 600)}`);

  // HALVA TVÅ: samma text från samma källa får fortfarande inte bli körbar
  // markup. Utan de här raderna skulle testet passera även om escapningen
  // tagits bort i FEL ände - och då vore felet inte längre kosmetiskt.
  assert.equal((html.match(/&lt;script&gt;/g) || []).length, 3,
    "alla tre <script> escapades inte vid utskrift");
  assert.ok(!html.includes("<script>"), "rå <script> nådde receptsidans markup");
  assert.ok(!html.includes("alert(1)</script>"), "ett steg slapp igenom oescapat");
});

test("provider-receptets mängdkolumn escapas också exakt en gång", async () => {
  const recept = mapApiRecipe(API_RECEPT);
  // Rå text i state - escapning hör till utskriften, aldrig till intaget.
  assert.deepEqual(recept.ingrediensrader, [
    { measure: "500 g", name: "Torskrygg" },
    { measure: "1 msk", name: "Salt & peppar" },
  ]);
  assert.deepEqual(recept.steg, ["Krydda torsken med salt & peppar."]);

  const html = await rita("prov:42", { api: [recept] });
  assert.ok(html.includes(`<span class="namn2">Salt &amp; peppar</span>`),
    "provider-ingrediensen är fel escapad");
  assert.ok(html.includes(`Krydda torsken med ${SÄKER_TEXT}.`), "steget är fel escapat");
  assert.ok(!html.includes(DUBBELESCAPAD), "provider-receptet dubbelescapas igen");
});

test("en ingrediens som HETER <script> blir text, inte markup", async () => {
  // Det farliga fallet på raka rör: receptkällan är extern, och ett namn som
  // ser ut som en tagg ska synas som en tagg - inte köras som en.
  const html = await rita("prov:42", {
    api: [mapApiRecipe({ ...API_RECEPT, ingredients: [{ measure: "1 st", name: "<script>alert(9)</script>" }] })],
  });
  assert.ok(html.includes(`${ESCAPAD_SCRIPT}alert(9)&lt;/script&gt;`),
    "ingrediensnamnet escapades inte vid utskrift");
  assert.ok(!html.includes("<script>"), "rå <script> nådde markupen via mängdkolumnen");
});

// ------------------------------------------------------------- tabular-nums

/** Deklarationerna som gäller för en selektor, i dokumentordning. */
function deklarationerFör(css, selektor) {
  return parseRegler(css)
    .filter(r => r.delar.includes(selektor))
    .flatMap(r => deklarationer(r.block));
}

const harTabularNums = (css, selektor) =>
  deklarationerFör(css, selektor)
    .filter(d => d.prop === "font-variant-numeric")
    .some(d => /\btabular-nums\b/.test(d.värde));

test("mängdkolumnen sätts med tabular-nums", () => {
  const css = läsStyles();
  assert.ok(harTabularNums(css, ".ingrrad .mangd2"),
    "mängdkolumnen saknar font-variant-numeric:tabular-nums. Utan den är\n" +
    "siffrorna olika breda, kolumnen hoppar i sidled mellan raderna, och två\n" +
    "kolumner blir svårare att läsa än en.");

  // ...och det är en riktig KOLUMN, inte två ord efter varandra: raden är ett
  // rutnät med ett eget spår för mängden.
  const rad = deklarationerFör(css, ".ingrrad");
  assert.ok(rad.some(d => d.prop === "display" && d.värde.trim() === "grid"),
    ".ingrrad är inget rutnät - mängden har ingen egen kolumn att vara bred i");
  const spår = rad.find(d => d.prop === "grid-template-columns");
  assert.ok(spår && spår.värde.trim().split(/\s+/).length === 2,
    `.ingrrad har inte två spår: ${spår?.värde}`);
});

test("tabular-nums-kravet har tänder - annars bevisar det ingenting", () => {
  // Samma fil med exakt den deklarationen bortplockad. Ser kontrollen inte
  // skillnaden är den bara ett grönt ljus som alltid lyser.
  const utan = läsStyles().replace(/font-variant-numeric:tabular-nums;?/g, "");
  assert.ok(!harTabularNums(utan, ".ingrrad .mangd2"),
    "kontrollen hittar tabular-nums även när deklarationen är borta");
});
