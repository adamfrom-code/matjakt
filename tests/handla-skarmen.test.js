// L3:s acceptanskriterium, i två delar:
//
//   1. "De tre pristillstånden renderas med L0:s komponent, inte med egen
//      markup."  Beviset är bokstavligt: prislappen i raden måste vara
//      TECKEN FÖR TECKEN samma sträng som prisMarkup() ger. En kopia som
//      "bara ser likadan ut" faller, och det är hela poängen - L0 är det enda
//      paketet som inte får byggas två gånger på olika sätt, och en vy som
//      skriver `<strong>${money(x)}</strong>` bryter regeln i just den vyn
//      utan att någon upptäcker det.
//
//   2. "Svep-för-ta-bort fungerar med tangentbord också."  Det provet ligger
//      i tests/svep-bort.test.js, där svepet redan bor: de två vägarna prövas
//      mot SAMMA taBort, för det är kravet - inte att det finns en tangent
//      som råkar ta bort något.
//
// Resten här nere är skärmen som design D (telefon 3) beskriver den:
// avdelningsgrupper, avbockad rad kvar på plats, och en fot som säger "minst"
// så fort summan är ett golv (C7).

import assert from "node:assert/strict";
import test from "node:test";

import { initAppState, state } from "../frontend/app/src/state/app-state.js";
import {
  KONTROLLERAT, SAKNAS, UPPSKATTAT, prisMarkup,
} from "../frontend/app/src/views/pris.js";
import {
  avdelningMarkup, initShoppingView, kassaUnderlag, radPrisTillstånd,
  saknarSäkertAntal, shoppingRowMarkup,
} from "../frontend/app/src/views/shopping.js";

const money = value => `${Math.round(value).toLocaleString("sv-SE")} kr`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/**
 * Handla-vyn med sin omvärld utbytt mot rena stubbar. Vyn känner DOM:en bara
 * genom det den får in (F3), så hela skärmen går att rita utan webbläsare.
 */
function rigga({ matchningar = {}, status = {}, livePriser = {}, hämtar = false } = {}) {
  initAppState({ storage: null, recipeBank: [] });
  state.livePriser = livePriser;
  state.dbPricedAt = hämtar ? null : Date.now();
  state.dbPricingFailedAt = null;
  initShoppingView({
    databaseItemFor: namn => matchningar[namn] || null,
    itemStatus: namn => status[namn] || "NEED_TO_BUY",
    itemCategory: () => "Frukt & grönt",
    money, plural,
    pantryForPricing: () => ({}),
    pricingPending: () => hämtar,
    livePricesLoading: () => hämtar,
    validChains: ["Willys"],
    chosenStore: () => "Willys",
    recipeQuantities: {}, packageInfo: {},
  });
}

const vara = (namn, extra = {}) => ({ namn, total: 1, unit: "st", package: null, ...extra });

/** Prislappen ur en rad: allt från första <span class="pris" till radens slut. */
function prislappen(html) {
  const start = html.indexOf('<span class="pris');
  assert.notEqual(start, -1, `raden innehåller ingen prislapp:\n${html}`);
  const slut = html.indexOf("</button>", start);
  return html.slice(start, slut);
}

// ---------------------------------------------------------------------------
// 1. DE TRE TILLSTÅNDEN KOMMER UR L0:s KOMPONENT
// ---------------------------------------------------------------------------

// Samma belopp i de två som visar ett tal: med olika siffror skiljer sig
// strängarna redan i text, och då bevisar jämförelsen ingenting om markupen.
const BELOPP = 38.5;
const RADER = {
  kontrollerat: { namn: "Gul lök", match: { productName: "Gul lök", totalCost: BELOPP, packages: 1, exactPackaging: true, priceTier: "VERIFIED_STORE_PRICE", priceStatus: "current" } },
  uppskattat: { namn: "Champinjoner", match: { productName: "Champinjoner", totalCost: BELOPP, packages: 1, exactPackaging: true, priceTier: "REFERENCE_PRICE", priceStatus: "current" } },
  saknas: { namn: "Dill", match: null },
};

test("de tre pristillstånden renderas av prisMarkup, tecken för tecken", () => {
  const matchningar = {};
  for (const { namn, match } of Object.values(RADER)) if (match) matchningar[namn] = match;
  rigga({ matchningar });

  const väntat = {
    kontrollerat: prisMarkup(money(BELOPP), KONTROLLERAT),
    uppskattat: prisMarkup(money(BELOPP), UPPSKATTAT),
    saknas: prisMarkup(null, SAKNAS),
  };
  for (const [läge, { namn }] of Object.entries(RADER)) {
    assert.equal(prislappen(shoppingRowMarkup(vara(namn))), väntat[läge],
      `${läge}: raden skrev en EGEN prismarkup i stället för L0:s komponent`);
  }
  // ...och de tre är faktiskt olika. Utan det här kunde alla tre vara
  // "pris saknas" och testet ovan ändå passera.
  assert.equal(new Set(Object.values(väntat)).size, 3);
});

test("Handla-modulen skriver ingen prismarkup av eget märke", async () => {
  const { readFileSync } = await import("node:fs");
  const källa = readFileSync(new URL("../frontend/app/src/views/shopping.js", import.meta.url), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "").split("\n").filter(rad => !/^\s*\/\//.test(rad)).join("\n");
  // Klasserna ÄGS av pris.js. Står någon av dem i en mallsträng här har vyn
  // börjat bygga en egen kopia av komponenten.
  for (const klass of ["pris--ca", "saknas", "cirka", "pris--golv", '"tal"', "price-missing"]) {
    assert.ok(!källa.includes(klass),
      `src/views/shopping.js bygger egen prismarkup: ${klass} hör hemma i pris.js`);
  }
});

test("ett gissat paketantal blir en tom ram, inte ett tal vi inte kan stå för", () => {
  // C8: en rad med känt styckpris men gissat antal har ingen ärlig radtotal.
  // Motorn säger det (exactPackaging:false / rowUncertain), och raden ska då
  // visa L0:s tomma fack - inte "22 kr" och inte en liten varning i marginalen.
  const osäker = { productName: "Honung", totalCost: null, packages: 1, exactPackaging: false, priceStatus: "current" };
  rigga({ matchningar: { Honung: osäker } });
  assert.equal(radPrisTillstånd({ match: osäker }).tillstånd, SAKNAS);
  assert.equal(prislappen(shoppingRowMarkup(vara("Honung"))), prisMarkup(null, SAKNAS));
  assert.equal(saknarSäkertAntal(vara("Honung")), true);
});

test("ett livepris utan paketantal är inte ett pris", () => {
  // Vikt- och volymvaror utan förpackningsinfo: packagesFor() svarar null
  // (fail closed, efter 224 g fiskpinnar som blev 224 paket och 6 561 kr).
  rigga({ livePriser: { Grädde: { pris_kr: 21.9, produktnamn: "Grädde 40%" } } });
  const flytande = vara("Grädde", { total: 600, unit: "ml", family: "vol" });
  assert.equal(prislappen(shoppingRowMarkup(flytande)), prisMarkup(null, SAKNAS));
  assert.equal(saknarSäkertAntal(flytande), true);
});

test("medan priset hämtas lånar raden ingen av de tre formerna", () => {
  // Frånvaron av ett svar är inte ett pristillstånd. En tom ram medan
  // hämtningen pågår vore ett påstående vi inte har täckning för.
  rigga({ hämtar: true });
  const html = shoppingRowMarkup(vara("Dill"));
  assert.ok(html.includes("pris hämtas"), html);
  assert.ok(!html.includes('class="saknas"'), "en pågående hämtning ritades som saknat pris");
});

// ---------------------------------------------------------------------------
// 2. RADEN OCH AVDELNINGEN (design D, telefon 3)
// ---------------------------------------------------------------------------

test("raden är kryssrutan: en knapp, inte tre", () => {
  rigga({ matchningar: { "Gul lök": RADER.kontrollerat.match } });
  const html = shoppingRowMarkup(vara("Gul lök", { total: 1, unit: "kg" }));
  assert.ok(html.includes('<button type="button" class="vara" data-bought="Gul lök"'), html);
  assert.ok(html.includes('aria-pressed="false"'), "obockad rad saknar aria-pressed");
  assert.ok(html.includes('class="ruta"'), "kryssrutan saknas");
  // Mängden är en egen underrad, inte en svans efter namnet.
  assert.match(html, /<strong>Gul lök<\/strong><small class="mangd">Behöver 1 kg<\/small>/);
  // Krysset finns kvar - i .vara-sido, utanför radens text, aldrig inuti
  // radens egen knapp (en knapp i en knapp är ogiltig markup).
  assert.ok(html.includes('data-remove-item="Gul lök"'), "krysset försvann ur DOM:en");
  assert.ok(html.indexOf("</button>") < html.indexOf("vara-sido"),
    "sidoknapparna ligger inuti radens knapp");
});

test("avbockad rad står kvar i sin avdelning, genomstruken och tonad", () => {
  rigga({ matchningar: { "Gul lök": RADER.kontrollerat.match }, status: { "Gul lök": "PURCHASED" } });
  const html = shoppingRowMarkup(vara("Gul lök"));
  assert.ok(html.includes("vara--klar"), "avbockad rad saknar sitt tillstånd");
  assert.ok(html.includes('aria-pressed="true"'));
  // Och den går att ångra på samma ställe som den bockades av: knappen byter
  // till data-need, inte till en ny kontroll längst ner på skärmen.
  assert.ok(html.includes('data-need="Gul lök"'), html);
  assert.ok(!html.includes("data-bought="), "en avbockad rad kan inte bockas av igen");
  // "Har hemma" erbjuds inte på en vara som redan är avklarad.
  assert.ok(!html.includes("data-at-home="), html);
});

test("avdelningen får hårlinjerubrik i kapitäler och sitt antal", () => {
  rigga();
  const html = avdelningMarkup("Frukt & grönt", [vara("Gul lök"), vara("Dill")]);
  assert.ok(html.startsWith('<section class="avdelningsgrupp">'), html);
  assert.match(html, /<h3 class="avdelning"><span class="kap kap-ink">Frukt &amp; grönt<\/span>/);
  assert.ok(html.includes('<span class="kap">2 varor</span>'), html);
  // Kapitälerna sätts i CSS. Versaler i källan får en skärmläsare att stava
  // rubriken bokstav för bokstav (§8).
  assert.ok(!html.includes("FRUKT"), "rubriken är versaliserad i markupen i stället för i CSS");
});

// ---------------------------------------------------------------------------
// 3. FOTEN: GOLVET (C7)
// ---------------------------------------------------------------------------

const kassa = (extra = {}) => kassaUnderlag({
  shoppingItems: [], total: 100, headerDb: null, activeChain: "Willys", ...extra,
});

test("C7: en osäker rad gör summan till ett golv och räknas i foten", () => {
  const osäker = { productName: "Honung", totalCost: null, packages: 1, exactPackaging: false, priceStatus: "current" };
  rigga({ matchningar: { Honung: osäker, "Gul lök": RADER.kontrollerat.match } });
  const underlag = kassa({ shoppingItems: [vara("Honung"), vara("Gul lök")] });
  assert.equal(underlag.osäkertAntal, 1);
  assert.equal(underlag.golv, true, "summan visades som ett exakt tal trots en osäker rad");
});

test("C7: en vara helt utan pris räknas för sig, inte som ett osäkert antal", () => {
  rigga({ matchningar: { "Gul lök": RADER.kontrollerat.match } });
  const underlag = kassa({ shoppingItems: [vara("Dill"), vara("Gul lök")] });
  assert.equal(underlag.utanPris, 1, "en vara utan pris räknades inte");
  assert.equal(underlag.osäkertAntal, 0, "utan pris är inte samma sak som utan säkert antal");
  assert.equal(underlag.golv, true);
});

test("C7: serverns golvflagga räknas med, men listan får överrösta den", () => {
  rigga({ matchningar: { "Gul lök": RADER.kontrollerat.match } });
  // Servern vet vad DEN prissatte; listan kan bära hushållsrader och
  // extravaror servern aldrig såg. Går de isär vinner golvet.
  assert.equal(kassa({ shoppingItems: [vara("Gul lök")], headerDb: { totalIsFloor: true } }).golv, true);
  assert.equal(kassa({ shoppingItems: [vara("Dill")], headerDb: { totalIsFloor: false } }).golv, true);
});

test("en helt prissatt lista är inget golv - då är talet kassans belopp", () => {
  rigga({ matchningar: { "Gul lök": RADER.kontrollerat.match } });
  const underlag = kassa({
    shoppingItems: [vara("Gul lök")],
    headerDb: { totalIsFloor: false, pricingBasis: "VERIFIED", totalCheckoutCost: 38.5 },
  });
  assert.deepEqual({ golv: underlag.golv, tillstånd: underlag.tillstånd },
    { golv: false, tillstånd: KONTROLLERAT });
});

test("en summa som inte är butiksverifierad hela vägen är uppskattad", () => {
  rigga();
  assert.equal(kassa({ headerDb: { pricingBasis: "MIXED", totalCheckoutCost: 90 } }).tillstånd, UPPSKATTAT);
  assert.equal(kassa({ headerDb: null }).tillstånd, UPPSKATTAT, "ett tal utan databasresultat är en beräkning");
  assert.equal(kassa({ total: null }).tillstånd, SAKNAS);
});

// ---------------------------------------------------------------------------
// 4. FOTEN, RITAD
// ---------------------------------------------------------------------------

/** Precis så mycket DOM som renderKassa rör. */
function kassaDom() {
  const noder = {};
  const nod = () => ({ textContent: "", innerHTML: "", hidden: false, firstChild: null });
  for (const id of ["shoppingCost", "shoppingTotalLabel", "shoppingUncertain", "prisnyckel"]) noder[id] = nod();
  return { noder, $: id => noder[id] || null };
}

test("foten säger MINST när talet är ett golv, och SUMMA när det inte är det", async () => {
  const { renderKassaFörTest } = await import("../frontend/app/src/views/shopping.js");
  const osäker = { productName: "Honung", totalCost: null, packages: 1, exactPackaging: false, priceStatus: "current" };
  const dom = kassaDom();
  rigga({ matchningar: { Honung: osäker, "Gul lök": RADER.kontrollerat.match } });
  initShoppingView({ $: dom.$ });

  renderKassaFörTest({
    shoppingItems: [vara("Honung"), vara("Gul lök")], total: 612, extrasCost: 0,
    headerDb: { totalIsFloor: true, pricingBasis: "VERIFIED" }, activeChain: "Willys",
  });
  assert.equal(dom.noder.shoppingTotalLabel.textContent, "Minst att betala");
  assert.equal(dom.noder.shoppingUncertain.textContent, "1 vara utan säkert antal");
  assert.equal(dom.noder.shoppingUncertain.hidden, false);
  // Talet självt är L0:s komponent med golvmodifieraren - ingen egen sträng.
  assert.ok(dom.noder.shoppingCost.innerHTML.startsWith(prisMarkup(money(612), KONTROLLERAT, { golv: true })),
    dom.noder.shoppingCost.innerHTML);
  assert.ok(dom.noder.shoppingCost.innerHTML.includes("/ 800 kr"), "budgeten försvann ur kassan");
  assert.ok(dom.noder.prisnyckel.innerHTML.includes("prisnyckel"), "teckenförklaringen saknas i foten");

  renderKassaFörTest({
    shoppingItems: [vara("Gul lök")], total: 39, extrasCost: 0,
    headerDb: { totalIsFloor: false, pricingBasis: "VERIFIED" }, activeChain: "Willys",
  });
  assert.equal(dom.noder.shoppingTotalLabel.textContent, "Summa i kassan");
  assert.equal(dom.noder.shoppingUncertain.hidden, true);
  assert.equal(dom.noder.shoppingCost.innerHTML, `${prisMarkup(money(39), KONTROLLERAT)} <span class="kassa-budget">/ 800 kr</span>`);
});

test("en misslyckad prissättning visar L0:s tomma ram, inte en evig spinner", () => {
  const dom = kassaDom();
  rigga();
  state.dbPricingFailedAt = Date.now();
  initShoppingView({ $: dom.$, pricingPending: () => false });
  // eslint-disable-next-line no-undef
  return import("../frontend/app/src/views/shopping.js").then(({ renderKassaFörTest }) => {
    renderKassaFörTest({ shoppingItems: [vara("Dill")], total: null, extrasCost: 0, headerDb: null, activeChain: "Willys" });
    assert.ok(dom.noder.shoppingCost.innerHTML.startsWith(prisMarkup(null, SAKNAS)), dom.noder.shoppingCost.innerHTML);
    assert.ok(!dom.noder.shoppingCost.innerHTML.includes("hämtas"), "beskedet uteblev - det är en spinner utan ände");
  });
});
