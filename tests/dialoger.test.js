// G12:s acceptanskriterium: ingen systemdialog finns kvar i frontend/app/,
// och ersättaren svarar rätt.
//
// Det första testet är en SPÄRR, inte en mätning av dagens läge. `alert()`,
// `confirm()` och `prompt()` går att skriva av misstag i vilken vy som helst -
// de är globala, de kräver ingen import, och de ser ut att fungera när man
// provar i en webbläsare på skrivbordet. Det är i den native-paketerade
// iOS-appen de går sönder: WKWebView renderar dem som systemdialoger med
// appens bundle-ID i rubriken. Den som lägger tillbaka ett anrop ska få veta
// det här, inte av en användare i TestFlight.
//
// Svepet räknar bara riktig kod: kommentarer och stränginnehåll tas bort
// först, annars hade filernas egna förklaringar av varför anropen är borta
// fällt testet.
//
// Det andra blocket prövar src/views/dialog.js mot en liten fejk-DOM. Egen
// fejk-DOM och inte tests/fixtures/fejk-dom.mjs: den är byggd för modal.js och
// saknar createElement, elementlyssnare och remove(). Att bygga ut den hade
// dragit in G6:s testfil i den här grenen utan anledning.

import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import test from "node:test";
import { resetModalLayers } from "../frontend/app/src/utils/modal.js";

const APP_DIR = new URL("../frontend/app/", import.meta.url);

// ---------------------------------------------------------------------------
// SPÄRREN
// ---------------------------------------------------------------------------

function filer(dir = APP_DIR) {
  const funna = [];
  for (const namn of readdirSync(dir).sort()) {
    const sökväg = new URL(namn, dir);
    if (statSync(sökväg).isDirectory()) funna.push(...filer(new URL(namn + "/", dir)));
    else if (/\.(js|mjs|html)$/.test(namn)) funna.push(sökväg);
  }
  return funna;
}

/**
 * Tar bort kommentarer och stränginnehåll så att svepet bara ser kod.
 * Radnumren bevaras: varje borttaget radbyte skrivs tillbaka.
 */
export function skalaAvKod(text) {
  let ut = "";
  let i = 0;
  const behållRader = s => s.replace(/[^\n]/g, "");
  while (i < text.length) {
    const rest = text.slice(i);
    let m;
    if ((m = /^<!--[\s\S]*?-->/.exec(rest)) || (m = /^\/\*[\s\S]*?\*\//.exec(rest))) {
      ut += behållRader(m[0]); i += m[0].length; continue;
    }
    if ((m = /^\/\/[^\n]*/.exec(rest))) { i += m[0].length; continue; }
    if ((m = /^(["'`])(?:\\.|(?!\1)[\s\S])*\1/.exec(rest))) {
      ut += m[1] + m[1] + behållRader(m[0]); i += m[0].length; continue;
    }
    ut += text[i]; i += 1;
  }
  return ut;
}

// Ett anrop, inte ett namn: `window.confirm(` och `confirm(` fastnar,
// `confirmLabel` och `askConfirm(` gör det inte.
const SYSTEMDIALOG = /(?:^|[^.\w$])(?:window\s*\.\s*)?(alert|confirm|prompt)\s*\(/;

export function systemdialoger(text) {
  return skalaAvKod(text).split("\n")
    .map((rad, index) => ({ rad: index + 1, träff: SYSTEMDIALOG.exec(rad)?.[1] }))
    .filter(post => post.träff);
}

test("spärren känner igen ett anrop och låter kringliggande text vara", () => {
  // Utan den här kontrollen kan svepet nedan bli grönt för att det slutat
  // hitta något alls - den tystaste sorten av trasigt test.
  assert.deepEqual(systemdialoger('if (!confirm("x")) return;').map(p => p.träff), ["confirm"]);
  assert.deepEqual(systemdialoger("window.alert(text)").map(p => p.träff), ["alert"]);
  assert.deepEqual(systemdialoger("const svar = prompt ( 'namn' )").map(p => p.träff), ["prompt"]);
  assert.deepEqual(systemdialoger("// alert(text) är borta härifrån"), []);
  assert.deepEqual(systemdialoger("/* confirm(x) */"), []);
  assert.deepEqual(systemdialoger('<!-- prompt("x") -->'), []);
  assert.deepEqual(systemdialoger('const t = "skriv confirm(x) i chatten";'), []);
  assert.deepEqual(systemdialoger("askConfirm({ confirmLabel: 'Radera' })"), []);
  assert.deepEqual(systemdialoger("el.confirm(1)"), []);
  assert.equal(systemdialoger("rad ett\nrad två\nalert(3)")[0].rad, 3);
});

test("ingen fil i frontend/app/ anropar alert(), confirm() eller prompt()", () => {
  const fynd = [];
  for (const fil of filer()) {
    for (const post of systemdialoger(readFileSync(fil, "utf8"))) {
      fynd.push(`${fil.pathname.split("/frontend/")[1]}:${post.rad}: ${post.träff}()`);
    }
  }
  assert.deepEqual(fynd, [],
    "systemdialoger tillbaka i appen - i iOS-bygget visas de med appens bundle-ID som rubrik.\n"
    + "Använd askConfirm()/showNotice() ur src/views/dialog.js i stället:\n  " + fynd.join("\n  "));
});

// ---------------------------------------------------------------------------
// ERSÄTTAREN
// ---------------------------------------------------------------------------

class El {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.attribut = new Map();
    this.barn = [];
    this.parentNode = null;
    this.style = { overflow: "" };
    this.lyssnare = new Map();
    this._text = "";
    this._doc = null;
  }
  get ownerDocument() { return this._doc || this.parentNode?.ownerDocument || null; }
  get children() { return [...this.barn]; }
  get hidden() { return this.attribut.has("hidden"); }
  set hidden(v) { if (v) this.attribut.set("hidden", ""); else this.attribut.delete("hidden"); }
  get textContent() { return this._text || this.barn.map(b => b.textContent).join(""); }
  set textContent(v) { this._text = String(v); this.barn = []; }
  hasAttribute(n) { return this.attribut.has(n); }
  getAttribute(n) { return this.attribut.get(n) ?? null; }
  setAttribute(n, v) { this.attribut.set(n, String(v)); }
  removeAttribute(n) { this.attribut.delete(n); }
  append(...noder) { for (const n of noder) { n.parentNode = this; this.barn.push(n); } return this; }
  remove() {
    const syskon = this.parentNode?.barn;
    if (syskon) syskon.splice(syskon.indexOf(this), 1);
    this.parentNode = null;
  }
  contains(n) { for (let p = n; p; p = p.parentNode) if (p === this) return true; return false; }
  alla() { return this.barn.flatMap(b => [b, ...b.alla()]); }
  querySelector(s) { return this.querySelectorAll(s)[0] ?? null; }
  querySelectorAll(selektor) {
    return this.alla().filter(el => selektor.split(",").some(sel => {
      const s = sel.trim();
      if (s.startsWith(".")) return (el.getAttribute("class") || "").split(/\s+/).includes(s.slice(1));
      const attr = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(s);
      if (attr) return attr[2] === undefined ? el.hasAttribute(attr[1]) : el.getAttribute(attr[1]) === attr[2];
      if (/^[a-z]/i.test(s)) return el.tagName === s.toUpperCase();
      return false;
    }));
  }
  addEventListener(typ, fn) { this.lyssnare.set(typ, [...(this.lyssnare.get(typ) || []), fn]); }
  klicka() { (this.lyssnare.get("click") || []).forEach(fn => fn({})); }
  focus() { const d = this.ownerDocument; if (d) d.activeElement = this; }
  getClientRects() { return this.hidden ? [] : [{}]; }
}

class Doc {
  constructor() {
    this.body = new El("body");
    this.body._doc = this;
    this.activeElement = this.body;
    this.lyssnare = [];
  }
  get ownerDocument() { return this; }
  createElement(tag) { const el = new El(tag); el._doc = this; return el; }
  addEventListener(typ, fn, capture) { this.lyssnare.push({ typ, fn, capture }); }
  removeEventListener(typ, fn, capture) {
    const i = this.lyssnare.findIndex(l => l.typ === typ && l.fn === fn && l.capture === capture);
    if (i !== -1) this.lyssnare.splice(i, 1);
  }
  contains(n) { return n === this.body || this.body.contains(n); }
  tryck(key) {
    const h = { key, shiftKey: false, preventDefault() {} };
    for (const l of [...this.lyssnare]) if (l.typ === "keydown") l.fn(h);
  }
}

let dialog;
const föreDoc = globalThis.document;
const föreObserver = globalThis.MutationObserver;

async function scen() {
  resetModalLayers();
  const doc = new Doc();
  const appen = new El("div");
  appen.setAttribute("class", "phone-shell");
  doc.body.append(appen);
  globalThis.document = doc;
  // modal.js sätter upp en MutationObserver när den finns. Fejk-DOM:en har
  // inga attributhändelser, så den ska vara borta här.
  globalThis.MutationObserver = undefined;
  dialog ??= await import("../frontend/app/src/views/dialog.js");
  return doc;
}

function städa() {
  resetModalLayers();
  globalThis.document = föreDoc;
  globalThis.MutationObserver = föreObserver;
}

const knapparI = doc => doc.body.querySelector(".account-modal-card").querySelectorAll("button");

test("askConfirm svarar true när ja-knappen trycks", async () => {
  const doc = await scen();
  try {
    const svar = dialog.askConfirm({ title: "Radera ditt konto?", confirmLabel: "Radera kontot" });
    const ja = knapparI(doc).find(k => k.textContent === "Radera kontot");
    assert.ok(ja, "ja-knappen saknas");
    ja.klicka();
    assert.equal(await svar, true);
  } finally { städa(); }
});

test("askConfirm svarar false på avbryt, Escape och bakgrundsklick", async () => {
  for (const väg of ["knapp", "escape", "bakgrund"]) {
    const doc = await scen();
    try {
      const svar = dialog.askConfirm({ title: "Lämna hushållet?", confirmLabel: "Lämna", cancelLabel: "Stanna kvar" });
      if (väg === "knapp") knapparI(doc).find(k => k.textContent === "Stanna kvar").klicka();
      if (väg === "escape") doc.tryck("Escape");
      if (väg === "bakgrund") doc.body.querySelector(".account-modal-backdrop").klicka();
      assert.equal(await svar, false, `${väg} gav inte nej`);
    } finally { städa(); }
  }
});

test("ja-knappen heter vad den gör, aldrig OK", async () => {
  const doc = await scen();
  try {
    dialog.askConfirm({ title: "Radera ditt konto?", confirmLabel: "Radera kontot", cancelLabel: "Behåll kontot", danger: true });
    const namn = knapparI(doc).map(k => k.textContent);
    assert.deepEqual(namn, ["Behåll kontot", "Radera kontot"],
      "vid en destruktiv fråga ska det säkra valet ligga först och vara primärknappen");
    assert.ok(!namn.includes("OK"));
  } finally { städa(); }
});

test("knapparna bär data-dialog - det enda fästet som inte är en stilfråga", async () => {
  // E2E klickar på den här, inte på etiketten: "Lämna hushållet" står både på
  // knappen man tryckte på och på knappen i dialogen, och en textselektor
  // hade träffat fel av de två. Klassen är Z-STYLE:s att byta när den vill.
  const doc = await scen();
  try {
    const nejsvar = dialog.askConfirm({ title: "Lämna?", confirmLabel: "Lämna hushållet", cancelLabel: "Stanna kvar", danger: true });
    assert.equal(doc.body.querySelector('[data-dialog="confirm"]').textContent, "Lämna hushållet");
    doc.body.querySelector('[data-dialog="cancel"]').klicka();
    assert.equal(await nejsvar, false, "cancel-fästet klickar inte igenom till svaret");

    const jasvar = dialog.askConfirm({ title: "Lämna?", confirmLabel: "Lämna hushållet", danger: true });
    doc.body.querySelector('[data-dialog="confirm"]').klicka();
    assert.equal(await jasvar, true, "confirm-fästet klickar inte igenom till svaret");
  } finally { städa(); }
});

test("showNotice-knappen är märkt close, inte confirm", async () => {
  const doc = await scen();
  try {
    dialog.showNotice({ title: "Betalningen kom inte igång" });
    assert.equal(doc.body.querySelectorAll('[data-dialog="confirm"]').length, 0,
      "ett besked har inget ja-svar och ska inte se ut att ha ett");
    assert.equal(doc.body.querySelector('[data-dialog="close"]').textContent, "Stäng");
  } finally { städa(); }
});

test("dialogen städas bort ur DOM:en när svaret är givet", async () => {
  const doc = await scen();
  try {
    const svar = dialog.askConfirm({ title: "Radera?", confirmLabel: "Radera" });
    assert.equal(doc.body.querySelectorAll(".app-dialog").length, 1);
    doc.tryck("Escape");
    await svar;
    assert.equal(doc.body.querySelectorAll(".app-dialog").length, 0,
      "ett kvarliggande lager blir inert nästa gång ett ark öppnas - synligt men dött");
    assert.equal(doc.body.style.overflow, "", "skrollspärren släpptes inte");
  } finally { städa(); }
});

test("två dialoger i rad går båda att svara på", async () => {
  const doc = await scen();
  try {
    const första = dialog.askConfirm({ title: "Ett", confirmLabel: "Ja" });
    knapparI(doc).find(k => k.textContent === "Ja").klicka();
    assert.equal(await första, true);
    const andra = dialog.askConfirm({ title: "Två", confirmLabel: "Ja igen" });
    knapparI(doc).find(k => k.textContent === "Ja igen").klicka();
    assert.equal(await andra, true);
  } finally { städa(); }
});

test("showNotice visar texten och löser sig när den kvitteras", async () => {
  const doc = await scen();
  try {
    const klar = dialog.showNotice({ title: "Betalningen kom inte igång", body: "Försök igen om en stund." });
    const kort = doc.body.querySelector(".account-modal-card");
    assert.equal(kort.querySelector("h2").textContent, "Betalningen kom inte igång");
    assert.equal(kort.querySelector("p").textContent, "Försök igen om en stund.");
    knapparI(doc)[0].klicka();
    assert.equal(await klar, undefined);
    assert.equal(doc.body.querySelectorAll(".app-dialog").length, 0);
  } finally { städa(); }
});

test("dialogen är ett riktigt modallager: role=dialog och rubriken är märkt", async () => {
  const doc = await scen();
  try {
    dialog.askConfirm({ title: "Radera?", body: "Går inte att ångra.", confirmLabel: "Radera" });
    const kort = doc.body.querySelector('[role="dialog"]');
    assert.ok(kort, "panelen saknar role=dialog");
    assert.equal(kort.getAttribute("aria-modal"), "true");
    assert.equal(kort.getAttribute("aria-labelledby"), kort.querySelector("h2").getAttribute("id"));
    assert.equal(doc.body.querySelector(".phone-shell").hasAttribute("inert"), true,
      "appen bakom dialogen gjordes inte inert");
  } finally { städa(); }
});

test("texten sätts som text, aldrig som markup", async () => {
  // Hushållsnamnet går rakt in i rubriken, och det är användarens egen sträng.
  const doc = await scen();
  try {
    dialog.askConfirm({ title: "Lämna <img src=x onerror=1>?", confirmLabel: "Lämna" });
    const rubrik = doc.body.querySelector("h2");
    assert.equal(rubrik.textContent, "Lämna <img src=x onerror=1>?");
    assert.equal(rubrik.barn.length, 0, "rubriken fick barnnoder - texten tolkades som markup");
  } finally { städa(); }
});
