// Renderingsmotorn bakom L0:s acceptanstest.
//
// Uppgiften är ovanlig och värd att beskriva: testet ska kunna svara på
// frågan "skiljer sig de tre pristillstånden i något ANNAT än färg?". Ett
// test som jämför `color` per klass kan inte svara på den. Det passerar lika
// glatt när skillnaden är #16191B mot #B91C1C som när den är en streckad
// linje mot en tom ram — och den första skillnaden finns inte för den som är
// färgblind, tittar på en telefon med nedskruvad ljusstyrka i butiksbelysning
// eller skriver ut listan.
//
// Därför bygger den här filen något som liknar det webbläsaren gör: markupen
// parsas till ett träd, stilmallens regler matchas mot varje nod, och
// resultatet blir en lista VISUELLA FAKTA per tillstånd. Sedan kan testet
// köra listan genom två filter:
//
//   gråskala()  varje färg byts mot sin relativa luminans. Det är vad en
//               akromatopsisk användare och en svartvit utskrift ser.
//   utanFärg()  ALL färginformation tas bort - både ton och ljushet.
//               Kvar står bara formen: `1.5px dashed`, `1px solid`, texten,
//               strukturen. Det är det hårda provet, och det är det som
//               avgör om formkodningen är verklig eller bara påstådd.
//
// Motorn kan bara det prismarkupen faktiskt använder: klass- och
// taggselektorer med efterföljandekombinator, plus ::before/::after. Det är
// ett medvetet val. En halvfärdig CSS-motor som TYST hoppar över en selektor
// den inte förstår vore värdelös här, så okända selektorformer räknas som
// icke-matchande och listas av okändaSelektorer() så att testet kan kräva
// att ingen av dem rör prisklasserna.

import { deklarationer, parseRegler, lösVar } from "./css-parser.mjs";
import { luminans, tolkaFärg } from "./kontrast.mjs";

// ------------------------------------------------------------------- markup

const TOMMA_TAGGAR = new Set(["br", "hr", "img", "input", "meta", "link"]);

/** Parsar den markup prisMarkup() skriver till ett träd. */
export function parseraHtml(html) {
  const rot = { tagg: "#rot", klasser: [], attr: {}, barn: [], text: "" };
  const stack = [rot];
  const token = /<\/([a-z0-9-]+)\s*>|<([a-z0-9-]+)((?:\s+[^>]*?)?)\/?>|([^<]+)/gi;
  for (const m of html.matchAll(token)) {
    const [, slut, öppna, attrRå, text] = m;
    const topp = stack[stack.length - 1];
    if (text != null) {
      if (text.trim()) topp.barn.push({ tagg: "#text", text, klasser: [], attr: {}, barn: [] });
      continue;
    }
    if (slut) {
      if (stack.length > 1) stack.pop();
      continue;
    }
    const attr = {};
    for (const a of (attrRå || "").matchAll(/([a-z0-9-]+)\s*=\s*"([^"]*)"/gi)) attr[a[1].toLowerCase()] = a[2];
    const nod = {
      tagg: öppna.toLowerCase(),
      klasser: (attr.class || "").split(/\s+/).filter(Boolean),
      attr, barn: [], text: "",
    };
    topp.barn.push(nod);
    if (!TOMMA_TAGGAR.has(nod.tagg)) stack.push(nod);
  }
  return rot;
}

/** Elementen i dokumentordning, var och en med sin väg från roten. */
export function element(rot) {
  const ut = [];
  const gå = (nod, väg) => {
    for (const barn of nod.barn) {
      if (barn.tagg === "#text") continue;
      const nyVäg = [...väg, barn];
      ut.push({ nod: barn, väg: nyVäg });
      gå(barn, nyVäg);
    }
  };
  gå(rot, []);
  return ut;
}

/** Textinnehållet direkt i noden (inte i barnen). */
const egenText = (nod) => nod.barn.filter((b) => b.tagg === "#text").map((b) => b.text).join("");

// ---------------------------------------------------------------- selektorer

const PSEUDO_ELEMENT = /::?(before|after)$/;
// En compound vi klarar: valfri tagg följd av noll eller fler .klasser.
const COMPOUND = /^([a-z][a-z0-9-]*)?((?:\.[A-Za-z_][\w-]*)*)$/;

function tolkaSelektor(del) {
  let text = del.trim();
  let pseudo = null;
  const p = PSEUDO_ELEMENT.exec(text);
  if (p) { pseudo = p[1]; text = text.slice(0, p.index); }
  if (/[>+~[\]:()*,]/.test(text) || !text) return null;   // utanför det motorn kan
  const compounds = [];
  for (const bit of text.split(/\s+/)) {
    const m = COMPOUND.exec(bit);
    if (!m) return null;
    compounds.push({ tagg: m[1] || null, klasser: m[2] ? m[2].slice(1).split(".") : [] });
  }
  return { compounds, pseudo };
}

const passar = (compound, nod) =>
  (!compound.tagg || compound.tagg === nod.tagg)
  && compound.klasser.every((k) => nod.klasser.includes(k));

/** Matchar en tolkad selektor mot en väg (rot → element) med bara efterföljande. */
function matchar(tolkad, väg) {
  if (!passar(tolkad.compounds[tolkad.compounds.length - 1], väg[väg.length - 1])) return false;
  let i = tolkad.compounds.length - 2, j = väg.length - 2;
  while (i >= 0) {
    if (j < 0) return false;
    if (passar(tolkad.compounds[i], väg[j])) { i--; }
    j--;
  }
  return true;
}

const specificitet = (tolkad) =>
  tolkad.compounds.reduce((n, c) => n + c.klasser.length * 10 + (c.tagg ? 1 : 0), 0);

// ------------------------------------------------------------------ rendering

/**
 * Något som inte syns är ingen synlig skillnad.
 *
 * Det här är inget randfall utan en lucka man annars går rakt in i:
 * prismarkupen bär .sr-only-text (", uppskattat pris") just för att
 * skärmläsaren inte kan höra en streckad linje. Räknades den texten som en
 * visuell fakta skulle testet godkänna tre tillstånd vars enda skillnad var
 * osynlig - alltså exakt det fel testet finns för att hitta.
 */
function ärDolt(stil) {
  if (stil.display === "none") return true;
  if (/rect\(\s*0[\s,]/.test(stil.clip || "")) return true;
  const litet = (v) => /^(0|1)px$/.test((v || "").trim());
  return litet(stil.width) && litet(stil.height) && stil.overflow === "hidden";
}

/**
 * Vad som faktiskt ritas för en bit markup: en post per element och
 * pseudo-element, med de deklarationer stilmallen ger den, i kaskadordning
 * och med var(--x) utlöst.
 */
// parseRegler() räknar radnummer om från filens början för varje regel, så en
// omparsning av hela styles.css är inte gratis. Markupen ritas en gång per
// tillstånd och tema; samma fil parsas alltså ett dussin gånger utan det här.
const parsat = new Map();
function tolkadeRegler(css) {
  if (!parsat.has(css)) {
    parsat.set(css, parseRegler(css).map((r) => ({ regel: r, delar: r.delar.map(tolkaSelektor) })));
  }
  return parsat.get(css);
}

export function rita(html, css, vars) {
  const tolkade = tolkadeRegler(css);
  const ut = [];

  for (const { nod, väg } of element(parseraHtml(html))) {
    for (const pseudo of [null, "before", "after"]) {
      const träffar = [];
      for (const { regel, delar } of tolkade) {
        for (const tolkad of delar) {
          if (!tolkad || tolkad.pseudo !== pseudo) continue;
          if (!matchar(tolkad, väg)) continue;
          träffar.push({ regel, vikt: specificitet(tolkad) });
          break;
        }
      }
      träffar.sort((a, b) => a.vikt - b.vikt || a.regel.rad - b.regel.rad);
      const stil = new Map();
      for (const { regel } of träffar) {
        for (const d of deklarationer(regel.block)) {
          if (d.prop.startsWith("--")) continue;
          stil.set(d.prop, lösVar(d.värde, vars).trim());
        }
      }
      const vägtext = väg.map((n) => [n.tagg, ...n.klasser.map((k) => "." + k)].join("")).join(" ");
      const objekt = Object.fromEntries(stil);
      if (!pseudo) {
        ut.push({
          väg: vägtext, djup: väg.length, tagg: nod.tagg,
          klasser: [...nod.klasser].sort(),
          text: egenText(nod), dolt: ärDolt(objekt),
          stil: objekt,
        });
      } else if (stil.size) {
        // Pseudo-elementet ärver ägarens klasser: .saknas::before ÄR en del
        // av det tomma facket, och en granskning som frågar "vilka element
        // bär en prisform?" måste få med tankstrecket.
        ut.push({
          väg: `${vägtext}::${pseudo}`, djup: väg.length + 1, tagg: `::${pseudo}`,
          klasser: [...nod.klasser].sort(), text: "", dolt: ärDolt(objekt),
          stil: objekt,
        });
      }
    }
  }
  return ut;
}

/** Reglerna som faktiskt rörde markupen - underlaget för färggranskningen. */
export function träffadeRegler(html, css) {
  const vägar = element(parseraHtml(html));
  const ut = [];
  for (const { regel, delar } of tolkadeRegler(css)) {
    if (delar.some((t) => t && vägar.some(({ väg }) => matchar(t, väg)))) ut.push(regel);
  }
  return ut;
}

/** Selektorer motorn inte förstår men som nämner en av de givna klasserna. */
export function okändaSelektorer(css, klasser) {
  const ut = [];
  for (const regel of parseRegler(css)) {
    for (const del of regel.delar) {
      if (tolkaSelektor(del)) continue;
      if (klasser.some((k) => new RegExp(`\\.${k}(?![\\w-])`).test(del))) ut.push(del);
    }
  }
  return ut;
}

// ---------------------------------------------------------------- färgfilter

const NAMNGIVEN_FÄRG = /\b(white|black|red|crimson|firebrick|maroon|darkred|indianred|tomato|salmon|orangered|gray|grey|silver|green|blue|gold|orange|pink|currentcolor|transparent)\b/gi;
const FÄRG_TOKEN = /#[0-9a-fA-F]{3,8}\b|\brgba?\([^)]*\)|\bhsla?\([^)]*\)/g;

/** hsl() som rgb, så att en röd ton inte kan smyga in i en annan notation. */
function hslTillRgb(text) {
  const m = /^hsla?\(([^)]*)\)$/i.exec(text.trim());
  if (!m) return null;
  const d = m[1].split(/[,\s/]+/).filter(Boolean);
  if (d.length < 3) return null;
  const h = ((parseFloat(d[0]) % 360) + 360) % 360;
  const s = parseFloat(d[1]) / 100, l = parseFloat(d[2]) / 100;
  if ([h, s, l].some(Number.isNaN)) return null;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m2 = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
    : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [(r + m2) * 255, (g + m2) * 255, (b + m2) * 255, 1];
}

export const färg = (text) => tolkaFärg(text) || hslTillRgb(text);

/** Varje färg i ett CSS-värde, som text och tolkad. */
export function färgerI(värde) {
  const ut = [];
  for (const m of String(värde).matchAll(FÄRG_TOKEN)) {
    const f = färg(m[0]);
    if (f) ut.push({ text: m[0], f });
  }
  for (const m of String(värde).matchAll(NAMNGIVEN_FÄRG)) {
    const f = färg(m[0]);
    if (f) ut.push({ text: m[0], f });
  }
  return ut;
}

/**
 * Gråskala: varje färg byts mot sin relativa luminans. Två färger som ser
 * olika ut men väger lika mycket ljus blir identiska - precis som på
 * skärmen hos den som inte ser färg.
 */
export function gråskala(ritad) {
  return ritad.map((post) => ({
    ...post,
    stil: Object.fromEntries(Object.entries(post.stil).map(([prop, värde]) => {
      let ut = värde;
      for (const { text, f } of färgerI(värde)) {
        ut = ut.split(text).join(`grå(${luminans(f).toFixed(3)})`);
      }
      return [prop, ut];
    })),
  }));
}

const REN_FÄRGEGENSKAP = /^(color|background|background-color|background-image|border(-(top|right|bottom|left))?-color|outline-color|text-decoration-color|fill|stroke|caret-color|column-rule-color|accent-color)$/;

/**
 * Utan färg: all färginformation bort, både ton och ljushet. Rena
 * färgegenskaper stryks, och färgtoken plockas ur sammansatta värden så att
 * `border-bottom:1.5px dashed #626B6F` blir `1.5px dashed`. Kvar står formen.
 */
export function utanFärg(ritad) {
  return ritad.map((post) => {
    const stil = {};
    for (const [prop, värde] of Object.entries(post.stil)) {
      if (REN_FÄRGEGENSKAP.test(prop)) continue;
      let ut = värde;
      for (const { text } of färgerI(värde)) ut = ut.split(text).join(" ");
      ut = ut.replace(/\s+/g, " ").trim();
      if (ut) stil[prop] = ut;
    }
    return { ...post, stil };
  });
}

/**
 * Det en seende användare faktiskt kan uppfatta - och ingenting mer.
 *
 * Klassnamn och selektorvägar faller bort: ingen ser en klass. Dolda noder
 * faller bort: en skillnad som bara finns för skärmläsaren är ingen VISUELL
 * skillnad, och det är visuell skillnad prisreglerna lovar. Kvar står djup,
 * tagg, synlig text och de deklarationer som gäller.
 */
export const synligt = (ritad) => ritad
  .filter((post) => !post.dolt)
  .map(({ djup, tagg, text, stil }) => ({ djup, tagg, text: text.trim(), stil }));

export const avtryck = (ritad) => JSON.stringify(synligt(ritad));
