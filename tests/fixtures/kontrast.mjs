// Kontrastmotorn bakom G4:s acceptanstest.
//
// Den gör tre saker: löser CSS-variablerna, räknar WCAG 2.1-kontrast, och
// parar ihop varje textfärg med den bakgrund den faktiskt hamnar på.
//
// DEN TREDJE ÄR DEN SVÅRA, och valet är medvetet: motorn tar en
// ÖGONBLICKSBILD AV KASKADEN vid varje deklaration, inte bara slutvärdet.
// Skälet står i DESIGNSYSTEM-D.md §10 R1: regeln som ger 1:1 på sparsiffran
// ligger kvar i filen och är maskerad av en senare regel. Ett test som bara
// mäter slutvärdet ser ingenting - och buggen slår till i samma sekund någon
// river den maskerande regeln. En regel som är SKRIVEN mörkt-på-mörkt är ett
// fel även när den för tillfället inte syns.

import { deklarationer, lösVar, parseRegler, rotVariabler } from "./css-parser.mjs";

// --------------------------------------------------------------- färgmatte

const NAMNGIVNA = {
  white: "#ffffff", black: "#000000", transparent: "rgba(0,0,0,0)",
  red: "#ff0000", gray: "#808080", grey: "#808080",
};

export function tolkaFärg(rå) {
  if (!rå) return null;
  const v = String(rå).trim().toLowerCase();
  if (NAMNGIVNA[v]) return tolkaFärg(NAMNGIVNA[v]);
  let m = /^#([0-9a-f]{3,8})$/.exec(v);
  if (m) {
    let h = m[1];
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join("");
    if (h.length !== 6 && h.length !== 8) return null;
    const n = parseInt(h.slice(0, 6), 16);
    const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, a];
  }
  m = /^rgba?\(([^)]+)\)$/.exec(v);
  if (m) {
    const d = m[1].split(/[,\s/]+/).filter(Boolean);
    if (d.length < 3) return null;
    const tal = (x) => (x.endsWith("%") ? (parseFloat(x) / 100) * 255 : parseFloat(x));
    const rgb = [tal(d[0]), tal(d[1]), tal(d[2])];
    if (rgb.some((x) => Number.isNaN(x))) return null;
    return [...rgb, d[3] === undefined ? 1 : parseFloat(d[3])];
  }
  return null;
}

const kanal = (c) => {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};

export const luminans = ([r, g, b]) => 0.2126 * kanal(r) + 0.7152 * kanal(g) + 0.0722 * kanal(b);

export function kontrast(a, b) {
  const [ljus, mörk] = [luminans(a), luminans(b)].sort((x, y) => y - x);
  return (ljus + 0.05) / (mörk + 0.05);
}

/** Lägger en genomskinlig färg ovanpå en ogenomskinlig. */
export function lägg(över, under) {
  if (över[3] >= 1) return över;
  return [0, 1, 2].map((i) => över[i] * över[3] + under[i] * (1 - över[3])).concat(1);
}

export const hex = (f) =>
  "#" + f.slice(0, 3).map((c) => Math.round(c).toString(16).padStart(2, "0")).join("");

/**
 * Färgstoppen i en gradient. Ett helt genomskinligt stopp är ingen bakgrund -
 * där syns det som ligger under, och det är inte stilmallens sak. På en
 * fotoskärm är det mörka stoppet det som gör texten läsbar, och det är det
 * som ska mätas (§5.2 räknar likadant).
 */
function gradientstopp(värde) {
  const ut = [];
  for (const m of värde.matchAll(/(#[0-9a-f]{3,8}|rgba?\([^)]*\))/gi)) {
    const f = tolkaFärg(m[1]);
    if (f && f[3] > 0) ut.push(f);
  }
  return ut;
}

// --------------------------------------------------------------- selektorer

const PSEUDO_TILLSTÅND = /:(hover|active|focus|focus-visible|focus-within|disabled|checked|first-child|last-child|not\([^)]*\))/g;
const PSEUDO_ELEMENT = /::?(before|after|placeholder|selection|marker|-webkit-[\w-]+)\b/g;

const stam = (s) => s.replace(PSEUDO_ELEMENT, "").replace(PSEUDO_TILLSTÅND, "").trim();
const compounds = (s) => s.split(/\s*[>+~]\s*|\s+/).filter(Boolean);

/**
 * .store-compare-row.cheapest → .store-compare-row → .store-compare
 * Filens namnkonvention är den enda strukturinformation CSS:en bär, och den
 * hålls konsekvent här. Den används SIST, efter de strukturella förfäderna,
 * just för att den är en gissning och inte en utsaga.
 */
function namnprefix(compound) {
  const m = /\.([\w-]+)/.exec(compound);
  if (!m) return [];
  const ut = [];
  let namn = m[1];
  if ("." + namn !== compound) ut.push("." + namn);
  while (namn.includes("-")) { namn = namn.slice(0, namn.lastIndexOf("-")); ut.push("." + namn); }
  return ut;
}

/**
 * Struktur som CSS:en omöjligt kan bära: ett element vars bakgrund kommer från
 * ett SYSKON som ligger ovanpå, eller från en förälder vars klassnamn inte är
 * ett prefix av barnets. Varje rad är en utsaga om markupen, inte ett undantag
 * från kravet - paret mäts, det hoppas inte över.
 */
export const STRUKTUR = {
  ".hero-meal-info": ".hero-meal-scrim",   // skärmen ligger som syskon över fotot
  ".hero-meal-meta": ".hero-meal-scrim",
  ".invite-landing-eyebrow": ".invite-landing-card",
};

/**
 * Bakgrunden finns inte i stilmallen alls: app.js sätter den inline per
 * butikskedja (`style="background:${color}"`). Det finns ingenting här att mäta.
 */
export const UTANFÖR_CSS = new Set([
  ".chain-mark", ".store-card .chain-mark",
  ".week-store-switch .chain-mark", ".comparison-store-main .chain-mark",
]);

function kandidater(selektor) {
  const ut = [];
  const lägg = (s) => { const t = (s || "").trim(); if (t && !ut.includes(t)) ut.push(t); };
  lägg(selektor);
  lägg(selektor.replace(PSEUDO_ELEMENT, "").trim());
  lägg(stam(selektor));
  const c = compounds(stam(selektor));
  const sista = c[c.length - 1];
  lägg(sista);
  lägg(STRUKTUR[selektor]);
  lägg(STRUKTUR[sista]);
  for (let i = c.length - 1; i > 0; i--) {      // strukturella förfäder först
    lägg(c.slice(0, i).join(" "));
    lägg(c[i - 1]);
    lägg(STRUKTUR[c[i - 1]]);
    for (const p of namnprefix(c[i - 1])) lägg(p);
  }
  for (const p of namnprefix(sista)) lägg(p);   // namnkonventionen sist
  lägg("body");
  return ut;
}

// ------------------------------------------------------------------ svepet

const STOR_PX = 24;
const STOR_FET_PX = 18.66;
export const KRAV_BRÖDTEXT = 4.5;
export const KRAV_STOR_TEXT = 3;

function sättBakgrund(läge, värde) {
  const v = värde.trim().toLowerCase();
  if (/gradient\(/.test(v)) {
    const stopp = gradientstopp(v);
    if (stopp.length) { läge.bakgrunder = stopp; return; }
  }
  if (v === "none" || v === "transparent") { läge.bakgrunder = []; return; }
  const f = tolkaFärg(v.split(/\s+/)[0]);
  if (f) läge.bakgrunder = f[3] === 0 ? [] : [f];
}

function parsaFontKortform(värde) {
  const ut = {};
  const vikt = /(^|\s)(bold|[1-9]00)(\s|$|\/)/.exec(värde);
  if (vikt) ut.vikt = vikt[2] === "bold" ? 700 : parseInt(vikt[2], 10);
  const px = /(^|\s)(\d*\.?\d+)(px|rem)(\s|\/|$)/.exec(värde);
  if (px) ut.px = parseFloat(px[2]) * (px[3] === "rem" ? 16 : 1);
  return ut;
}

/**
 * Sveper hela filen och returnerar varje par (textfärg, bakgrund) som inte når
 * kravet. Kravet är 4,5:1 för brödtext och 3:1 för stor text (≥24px, eller
 * ≥18,66px i halvfet stil eller fetare) enligt WCAG 2.1 SC 1.4.3.
 */
export function svepKontrast(cssRå, { tema = "" } = {}) {
  const regler = parseRegler(cssRå);
  const vars = rotVariabler(regler, tema);
  const läget = new Map();
  const fynd = [];

  const hämtaBakgrund = (selektor) => {
    const lager = [];
    for (const k of kandidater(selektor)) {
      const l = läget.get(k);
      if (!l || l.dold || !l.bakgrunder?.length) continue;
      lager.push(l.bakgrunder);
      if (l.bakgrunder.every((f) => f[3] >= 1)) break;   // ogenomskinlig: klart
    }
    if (!lager.length) return null;
    const botten = lager.slice(1).reverse()
      .reduce((ack, l) => (ack ? lägg(l[0], ack) : l[0]), null) || [255, 255, 255, 1];
    return lager[0].map((f) => lägg(f, botten));
  };

  const hämtaStorlek = (selektor) => {
    for (const k of kandidater(selektor)) {
      const l = läget.get(k);
      if (l?.px) return { px: l.px, vikt: l.vikt ?? 400 };
    }
    return { px: 15, vikt: 400 };                        // body i V2-blocket
  };

  for (const regel of regler) {
    if (regel.media.some((m) => /\bprint\b/.test(m))) continue;
    const deklar = deklarationer(regel.block);
    for (const del of regel.delar) {
      const nyckel = del.trim();
      const läge = läget.get(nyckel) || { bakgrunder: [], färg: null };
      let rörde = false;
      for (const d of deklar) {
        const värde = lösVar(d.värde, vars).trim();
        switch (d.prop) {
          case "color": {
            const f = tolkaFärg(värde);
            läge.färg = f && f[3] > 0 ? f : null;        // transparent = klippt text
            rörde = true;
            break;
          }
          case "background": läge.bakgrunder = []; sättBakgrund(läge, värde); rörde = true; break;
          case "background-color":
          case "background-image": sättBakgrund(läge, värde); rörde = true; break;
          case "display": läge.dold = värde === "none"; break;
          case "font-size": {
            const m = /(\d*\.?\d+)(px|rem)/.exec(värde);
            if (m) läge.px = parseFloat(m[1]) * (m[2] === "rem" ? 16 : 1);
            break;
          }
          case "font-weight": {
            const w = /^(bold|[1-9]00)$/.exec(värde);
            if (w) läge.vikt = w[1] === "bold" ? 700 : parseInt(w[1], 10);
            break;
          }
          case "font": Object.assign(läge, parsaFontKortform(värde)); break;
        }
      }
      läget.set(nyckel, läge);

      if (!rörde || !läge.färg || läge.dold) continue;   // dold: inget syns, inget att mäta
      if (UTANFÖR_CSS.has(nyckel)) continue;
      const bakgrunder = hämtaBakgrund(nyckel);
      if (!bakgrunder) continue;
      const { px, vikt } = hämtaStorlek(nyckel);
      const krav = px >= STOR_PX || (px >= STOR_FET_PX && vikt >= 700)
        ? KRAV_STOR_TEXT : KRAV_BRÖDTEXT;

      let värst = Infinity, värstBakgrund = null;
      for (const b of bakgrunder) {
        const r = kontrast(lägg(läge.färg, b), b);
        if (r < värst) { värst = r; värstBakgrund = b; }
      }
      if (värst < krav) {
        fynd.push({
          selektor: nyckel, rad: regel.rad, ratio: värst, krav, px, vikt,
          färg: hex(läge.färg), bakgrund: hex(värstBakgrund),
        });
      }
    }
  }
  return fynd;
}

export const beskriv = (f) =>
  `styles.css:${f.rad}  ${f.ratio.toFixed(2)}:1 (krävs ${f.krav}:1)  ` +
  `${f.färg} på ${f.bakgrund}  ${f.px}px/${f.vikt}  ${f.selektor}`;
