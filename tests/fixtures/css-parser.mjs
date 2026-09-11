// Delad CSS-läsare för stiltesterna (G1 stilsystem, G4 kontrast, G5 träffytor).
//
// Ingen webbläsare och inget beroende: styles.css läses som text, delas i
// regler och variablerna löses ut ur :root. Det räcker långt just för att
// filen är platt - en enda kaskad, inga importer, inga nästlade selektorer.
//
// Filen ligger under tests/fixtures/ och inte i tests/ direkt, för allt som
// heter *.test.js där körs som testfil av `node --test`. Det här är verktyg.

import { readFileSync } from "node:fs";

const rot = new URL("../../", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

export function läsFil(relativ) {
  return readFileSync(rot + relativ, "utf8");
}

export function läsStyles() {
  return läsFil("frontend/app/styles.css");
}

/**
 * Byter varje kommentar mot lika många blanktecken och behåller radbrytningar.
 * Poängen är att radnummer och offset överlever - ett testfel ska kunna peka
 * på rätt rad i den riktiga filen.
 */
export function maskeraKommentarer(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
}

function delaPåFörstaKomma(text) {
  let djup = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "(") djup++;
    else if (c === ")") djup--;
    else if (c === "," && djup === 0) return [text.slice(0, i), text.slice(i + 1)];
  }
  return [text, undefined];
}

/** Delar en selektorlista på komma, men inte inuti :is()/:not()/[attr=","]. */
export function delaSelektorer(selektor) {
  const ut = [];
  let djup = 0, bit = "";
  for (const c of selektor) {
    if (c === "(" || c === "[") djup++;
    else if (c === ")" || c === "]") djup--;
    if (c === "," && djup === 0) { ut.push(bit.trim()); bit = ""; } else bit += c;
  }
  if (bit.trim()) ut.push(bit.trim());
  return ut;
}

/**
 * Parsar hela filen till en platt lista av regler i dokumentordning.
 * @-block följs in (media, supports) utom @keyframes och @font-face, som inte
 * innehåller några selektorer att granska.
 */
export function parseRegler(cssRå) {
  const css = maskeraKommentarer(cssRå);
  const regler = [];

  function radFör(offset) {
    // Selektorn börjar där föregående block slutade - hoppa förbi radbrytningen
    // däremellan, annars pekar varje radnummer på raden ovanför.
    while (offset < css.length && /\s/.test(css[offset])) offset++;
    let rad = 1;
    for (let i = 0; i < offset; i++) if (css[i] === "\n") rad++;
    return rad;
  }

  function gåIgenom(från, till, media) {
    let i = från, start = från;
    while (i < till) {
      const c = css[i];
      if (c === "}") { i++; start = i; continue; }
      if (c !== "{") { i++; continue; }
      const selektor = css.slice(start, i).trim();
      let djup = 1, j = i + 1;
      while (j < till && djup > 0) {
        if (css[j] === "{") djup++;
        else if (css[j] === "}") djup--;
        j++;
      }
      if (selektor.startsWith("@")) {
        if (!/^@(keyframes|-webkit-keyframes|font-face)/.test(selektor)) {
          gåIgenom(i + 1, j - 1, [...media, selektor]);
        }
      } else if (selektor) {
        regler.push({
          selektor,
          delar: delaSelektorer(selektor),
          block: css.slice(i + 1, j - 1),
          media,
          rad: radFör(start),
        });
      }
      i = j;
      start = j;
    }
  }

  gåIgenom(0, css.length, []);
  return regler;
}

/** Deklarationerna i ett block, i ordning, med !important utplockat. */
export function deklarationer(block) {
  const ut = [];
  let djup = 0, bit = "";
  const lägg = (rå) => {
    const t = rå.trim();
    if (!t) return;
    const k = t.indexOf(":");
    if (k < 0) return;
    const prop = t.slice(0, k).trim().toLowerCase();
    let värde = t.slice(k + 1).trim();
    const viktig = /!\s*important$/i.test(värde);
    if (viktig) värde = värde.replace(/!\s*important$/i, "").trim();
    if (prop) ut.push({ prop, värde, viktig });
  };
  for (const c of block) {
    if (c === "(") djup++;
    else if (c === ")") djup--;
    if (c === ";" && djup === 0) { lägg(bit); bit = ""; } else bit += c;
  }
  lägg(bit);
  return ut;
}

/**
 * Variablerna som gäller för en given tema-väljare. `tema` är den selektor
 * vars :root-block ska läggas ovanpå det bara :root - "" betyder ljust läge.
 */
export function rotVariabler(regler, tema = "") {
  const vars = new Map();
  for (const regel of regler) {
    for (const del of regel.delar) {
      const matchar = del === ":root" || (tema && del === `:root${tema}`);
      if (!matchar) continue;
      for (const d of deklarationer(regel.block)) {
        if (d.prop.startsWith("--")) vars.set(d.prop, d.värde);
      }
    }
  }
  return vars;
}

/** Expanderar var(--x, fallback) rekursivt. Okänd variabel utan fallback → "". */
export function lösVar(värde, vars, djup = 0) {
  if (djup > 16 || typeof värde !== "string" || !värde.includes("var(")) return värde;
  let ut = "", i = 0;
  while (i < värde.length) {
    const k = värde.indexOf("var(", i);
    if (k < 0) { ut += värde.slice(i); break; }
    ut += värde.slice(i, k);
    let djupP = 1, j = k + 4;
    while (j < värde.length && djupP > 0) {
      if (värde[j] === "(") djupP++;
      else if (värde[j] === ")") djupP--;
      j++;
    }
    const [namnRå, fallback] = delaPåFörstaKomma(värde.slice(k + 4, j - 1));
    const namn = namnRå.trim();
    const rå = vars.has(namn) ? vars.get(namn) : fallback === undefined ? "" : fallback.trim();
    ut += lösVar(rå, vars, djup + 1);
    i = j;
  }
  return ut;
}

/** Varje --namn som filen faktiskt slår upp med var(). */
export function användaVariabler(cssRå) {
  const namn = new Set();
  for (const m of maskeraKommentarer(cssRå).matchAll(/var\(\s*(--[\w-]+)/g)) namn.add(m[1]);
  return namn;
}
