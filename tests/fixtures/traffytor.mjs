// Träffytemotorn bakom G5:s acceptanstest.
//
// Frågan "är det här något man trycker på?" besvaras inte ur en handskriven
// lista. Den läses ur markupen - index.html och varje .js under frontend/app/
// som bygger HTML: varje klass som sitter på ett <button>, <a>, <summary>,
// <input>, <select>, <textarea> eller <label> är en interaktiv klass. Till det kommer selektorer
// vars sista led ÄR ett sådant element, [role="button"], och regler som säger
// cursor:pointer - CSS:ens egen utsaga om att något går att trycka på.
//
// Kravet är 44x44 CSS-px (WCAG 2.5.5 / DESIGNSYSTEM-D.md kap. 5). Måttet som
// mäts är det SLUTLIGA i kaskaden: webbläsaren räknar ut ett värde, och det
// är det värdet tummen möter.

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { deklarationer, lösVar, parseRegler, rotVariabler } from "./css-parser.mjs";

export const MINSTA = 44;

const ELEMENT = new Set(["button", "a", "summary", "input", "select", "textarea", "label"]);
const MÅTT = ["height", "min-height", "width", "min-width"];
const ROT = new URL("../../", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const MARKUP_ROT = "frontend/app";

/**
 * All markup i appen: index.html plus varje .js som bygger HTML. Katalogen
 * genomsöks i stället för att räknas upp, för app.js håller på att styckas i
 * moduler under src/views/ - en handskriven lista hade blivit tyst inaktuell
 * i samma stund som nästa vy flyttade ut.
 */
function markupFiler(katalog = MARKUP_ROT, ut = []) {
  for (const post of readdirSync(join(ROT, katalog), { withFileTypes: true })) {
    const rel = `${katalog}/${post.name}`;
    if (post.isDirectory()) { if (post.name !== "assets" && post.name !== "data") markupFiler(rel, ut); }
    else if (/\.(js|html)$/.test(post.name)) ut.push(rel);
  }
  return ut;
}

/** Klasser som i markupen sitter på ett interaktivt element. */
export function interaktivaKlasser() {
  const klasser = new Set();
  for (const fil of markupFiler()) {
    const kod = readFileSync(join(ROT, fil), "utf8");
    for (const m of kod.matchAll(/<(button|a|summary|input|select|textarea|label)\b([^>]*)>/g)) {
      const c = /class="([^"]*)"/.exec(m[2]);
      if (!c) continue;
      // Mallsträngarna interpolerar: dela på allt som inte kan vara ett klassnamn.
      for (const t of c[1].split(/[\s${}?:()`+]+/)) if (/^[a-z][\w-]*$/.test(t)) klasser.add(t);
    }
  }
  return klasser;
}

const utanPseudo = (s) => s.replace(/::?[a-z-]+(\([^)]*\))?/g, "").trim();

export function sistaLed(selektor) {
  const bitar = utanPseudo(selektor).split(/\s*[>+~]\s*|\s+/).filter(Boolean);
  return bitar[bitar.length - 1] || "";
}

export function förfäder(selektor) {
  const bitar = utanPseudo(selektor).split(/\s*[>+~]\s*|\s+/).filter(Boolean);
  return bitar.slice(0, -1);
}

const px = (v) => {
  const m = /^(\d*\.?\d+)px$/.exec(String(v).trim());
  return m ? parseFloat(m[1]) : null;
};

/**
 * Varje interaktiv regel vars slutliga mått underskrider 44 px.
 *
 * Två sätt att vara godkänd under 44 px, båda utskrivna i CSS:en själv:
 *  - `.tapmin`-mönstret i kap. 5: ett ::after som är minst 44x44 och vidgar
 *    träffytan utan att flytta något visuellt.
 *  - En kryssruta vars RAD är träffytan (§5.5). Kryssrutan har ingen egen
 *    lyssnare; raden är knappen. Då prövas radens höjd i stället.
 */
export function svepTräffytor(cssRå) {
  const regler = parseRegler(cssRå);
  const vars = rotVariabler(regler);
  const klasser = interaktivaKlasser();

  const pekare = new Set();
  const gömda = new Set();
  for (const r of regler) {
    const d = deklarationer(r.block);
    if (d.some((x) => x.prop === "cursor" && x.värde.trim() === "pointer")) {
      for (const del of r.delar) pekare.add(sistaLed(del));
    }
    // Visuellt gömd text (sr-only) och display:none är inga träffytor.
    if (d.some((x) => x.prop === "clip" && /rect\(/.test(x.värde))
        || d.some((x) => x.prop === "display" && x.värde.trim() === "none")) {
      for (const del of r.delar) gömda.add(del.trim());
    }
  }

  const ärInteraktiv = (selektor) => {
    const sista = sistaLed(selektor);
    if (!sista) return false;
    const tagg = /^[a-z]+/.exec(sista);
    if (tagg && ELEMENT.has(tagg[0])) return true;
    if (/\[role="?button"?\]/.test(selektor)) return true;
    const första = /\.([\w-]+)/.exec(sista);
    if (första && klasser.has(första[1])) return true;
    return pekare.has(sista);
  };

  // Slutliga mått per selektor, i dokumentordning.
  const mått = new Map();
  const vidgade = new Set();
  for (const r of regler) {
    const d = deklarationer(r.block);
    const max44 = (p) => d.some((x) => x.prop === p && /max\([^)]*44px/.test(x.värde));
    for (const del of r.delar) {
      const nyckel = del.trim();
      if (/::(after|before)$/.test(nyckel)) {
        if (max44("width") && max44("height")) vidgade.add(nyckel.replace(/::(after|before)$/, ""));
        continue;
      }
      const m = mått.get(nyckel) || { rad: r.rad };
      for (const dek of d) {
        if (!MÅTT.includes(dek.prop)) continue;
        const v = px(lösVar(dek.värde, vars));
        if (v !== null) { m[dek.prop] = v; m.rad = r.rad; }
      }
      if (Object.keys(m).length > 1) mått.set(nyckel, m);
    }
  }

  const radHöjd = (selektor) => {
    const m = mått.get(selektor);
    return Math.max(m?.height ?? 0, m?.["min-height"] ?? 0);
  };

  const fynd = [];
  for (const [nyckel, m] of mått) {
    if (!ärInteraktiv(nyckel) || gömda.has(nyckel)) continue;
    const bas = nyckel.replace(/:(hover|active|focus|focus-visible|disabled|checked)\b/g, "").trim();
    if (vidgade.has(bas) || vidgade.has(nyckel)) continue;

    // §5.5: kryssrutan är inte knappen, raden är det.
    const sista = sistaLed(nyckel);
    if (/^input/.test(sista) && förfäder(nyckel).some((f) => radHöjd(f) >= MINSTA)) continue;

    for (const prop of MÅTT) {
      const v = m[prop];
      if (v === undefined || v >= MINSTA) continue;
      // min-width/min-height är ett golv: ett större height vinner.
      if (prop === "min-height" && (m.height ?? 0) >= MINSTA) continue;
      if (prop === "min-width" && (m.width ?? 0) >= MINSTA) continue;
      if (prop === "height" && (m["min-height"] ?? 0) >= MINSTA) continue;
      if (prop === "width" && (m["min-width"] ?? 0) >= MINSTA) continue;
      fynd.push({ selektor: nyckel, rad: m.rad, prop, px: v });
    }
  }
  return fynd.sort((a, b) => a.rad - b.rad || a.selektor.localeCompare(b.selektor));
}

export const beskriv = (f) => `styles.css:${f.rad}  ${f.prop}:${f.px}px  ${f.selektor}`;
