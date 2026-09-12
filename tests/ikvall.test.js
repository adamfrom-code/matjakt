// L1:s acceptanskriterium: fotot fyller bredden, rubriken ligger på det, och
// texten klarar 4,5:1 mot toningen RÄKNAT MOT VÄRSTA FALL — ett helvitt foto
// under.
//
// Värsta fallet är hela poängen. Fotot är inte vårt: det kommer ur
// assets/recipes/ i dag och ur en receptleverantör i morgon, och nästa bild
// kan vara ett fat ljus fisk i motljus mot en vit duk. En text-shadow som ser
// bra ut över korv stroganoff är värdelös där. Därför mäts inte det foto vi
// råkar ha valt, utan det ljusaste foto som över huvud taget kan förekomma,
// och toningen måste ensam bära kontrasten mot det.
//
// Två saker gör beviset värt något:
//
//   1. TALET ÄR HÄMTAT, INTE HITTAT PÅ. --scrim står i :root och läses
//      därifrån. Sänker någon .78 till .55 för att fotot ska "synas bättre"
//      failar testet med ett tal, inte med en åsikt.
//
//   2. ZONEN MÄTS, INTE BARA FÄRGEN. Att gradienten NÅR full --scrim någon
//      gång längst ned hjälper inte om texten ligger ovanför den punkten.
//      Testet räknar därför ut var toningen blir full och var textblocket
//      högst kan sträcka sig, och kräver att texten ligger inom skyddet -
//      oavsett hur lång rubriken är.

import assert from "node:assert/strict";
import test from "node:test";
import {
  deklarationer, läsFil, läsStyles, lösVar, parseRegler, rotVariabler,
} from "./fixtures/css-parser.mjs";
import { KRAV_BRÖDTEXT, kontrast, lägg, tolkaFärg } from "./fixtures/kontrast.mjs";
import { färgerI, rita } from "./fixtures/prisrender.mjs";
import {
  budgetremsaText, fyndradMarkup, ikvallMarkup, ikvallTomMarkup,
} from "../frontend/app/src/views/ikvall.js";
import { prisMarkup } from "../frontend/app/src/views/pris.js";
// M2 äger receptets bildyta. Hjälten ritar aldrig sin egen <img> och aldrig
// sitt eget reservkort - den ber komponenten om en yta och lägger den på plats.
import { receptbildMarkup } from "../frontend/app/src/views/receptbild.js";

const css = läsStyles();
const regler = parseRegler(css);
const vars = rotVariabler(regler);
const mörk = rotVariabler(regler, '[data-theme="dark"]');

const RÄTT = {
  id: "korvstroganoff", namn: "Korv Stroganoff", tid: 25, servings: 4,
  portionspris: 38.5, priceStatus: "priced", priceTier: "VERIFIED_STORE_PRICE",
};
const FOTO = '<img class="recipe-photo" src="assets/recipes/korvstroganoff.jpg" alt="Korv Stroganoff">';
const KORT = ikvallMarkup(RÄTT, {
  ögonbryn: "Ikväll · onsdag", meta: "25 min · 4 portioner", foto: FOTO,
});
const ritad = rita(KORT, css, vars);

/** Det ritade elementet som bär klassen - inte pseudo-elementet. */
function nod(klass) {
  const träff = ritad.find((n) => n.klasser.includes(klass) && !n.tagg.startsWith("::"));
  assert.ok(träff, `${klass} finns inte i den markup ikvallMarkup() skriver`);
  return träff;
}

/** Deklarationerna styles.css ger en EXAKT selektor, sist vinner. */
function regelStil(selektor, media = null) {
  const stil = new Map();
  for (const r of regler) {
    const iMedia = media === null ? !r.media.length : r.media.some((m) => m.includes(media));
    if (!iMedia) continue;
    if (!r.delar.some((d) => d.trim() === selektor)) continue;
    for (const d of deklarationer(r.block)) stil.set(d.prop, lösVar(d.värde, vars).trim());
  }
  return stil;
}

/** Delar ett värde på kommatecken/blanksteg som ligger utanför parenteser. */
function delar(värde, tecken) {
  const ut = [];
  let djup = 0, bit = "";
  for (const c of värde) {
    if (c === "(") djup++;
    if (c === ")") djup--;
    if (djup === 0 && (tecken === "," ? c === "," : /\s/.test(c))) {
      if (bit.trim()) ut.push(bit.trim());
      bit = "";
      continue;
    }
    bit += c;
  }
  if (bit.trim()) ut.push(bit.trim());
  return ut;
}

/** px ur "14px", "calc(116px - 14px)" och "-20px". */
function pxSumma(värde) {
  const inne = /^calc\((.*)\)$/.exec(värde.trim());
  if (inne) {
    let summa = 0, tecken = 1;
    for (const bit of inne[1].split(/\s+/)) {
      if (bit === "-") { tecken = -1; continue; }
      if (bit === "+") { tecken = 1; continue; }
      const m = /^(-?\d*\.?\d+)px$/.exec(bit);
      if (m) { summa += tecken * parseFloat(m[1]); tecken = 1; }
    }
    return summa;
  }
  const m = /^(-?\d*\.?\d+)(px)?$/.exec(värde.trim());
  if (!m) return null;
  // Ett rent "0" är noll pixlar; allt annat utan enhet är inte ett mått.
  return m[2] || parseFloat(m[1]) === 0 ? parseFloat(m[1]) : null;
}

/** Sidopaddingen i en padding-kortform: "4px 20px calc(...)" -> 20. */
function sidpadding(värde) {
  const d = delar(värde, " ");
  const höger = d.length === 1 ? d[0] : d[1];
  if (d.length === 4) assert.equal(d[3], höger, `.app har olika vänster- och högermarginal: ${värde}`);
  return pxSumma(höger);
}

/** Färgstoppen i en linjär gradient, som [färg, position]. */
function gradientstopp(värde) {
  const inne = /^linear-gradient\((.*)\)$/.exec(värde.trim());
  assert.ok(inne, `skärmen är ingen linear-gradient: ${värde}`);
  return delar(inne[1], ",").slice(1).map((stopp) => {
    const bitar = delar(stopp, " ");
    return { färg: bitar[0], plats: bitar.slice(1).join(" ") };
  });
}

// En skärm har åtta bitar per kanal. Kompositen avrundas därför till hela
// kanalvärden innan den mäts - det är de talen som faktiskt lyser, och det är
// så DESIGNSYSTEM-D.md §2.2 räknat fram 10,23:1.
const avrunda = (färg) => färg.map((k, i) => (i === 3 ? k : Math.round(k)));
const HELVITT_FOTO = [255, 255, 255, 1];

// ---------------------------------------------------------------------------
// ACCEPTANSEN
// ---------------------------------------------------------------------------

test("toningen ensam bär texten mot ett helvitt foto - 10,23:1", () => {
  const skärm = tolkaFärg(vars.get("--scrim"));
  assert.ok(skärm, "--scrim finns inte i :root");
  assert.equal(skärm[3], 0.78,
    `--scrim har genomskinlighet ${skärm[3]}, designsystemet specar 0,78 (§5.2). ` +
    "Talet är golvet för kontrasten mot ett helvitt foto - ändras det ändras golvet.");

  const bakgrund = avrunda(lägg(skärm, HELVITT_FOTO));
  const ratio = kontrast(tolkaFärg("#FFFFFF"), bakgrund);

  assert.ok(ratio >= KRAV_BRÖDTEXT,
    `vit text mot toningen över ett helvitt foto ger ${ratio.toFixed(2)}:1, kravet är ${KRAV_BRÖDTEXT}:1`);
  assert.ok(Math.abs(ratio - 10.23) < 0.01,
    `kontrasten räknades till ${ratio.toFixed(2)}:1, designsystemet säger 10,23:1 (§2.2)`);
});

test("utan toning är samma text oläslig - annars bevisar talet ovan ingenting", () => {
  // Ett grönt test är värt något först när det kan bli rött. Tas skärmen bort
  // ligger vit text direkt på ett helvitt foto.
  const utanSkärm = kontrast(tolkaFärg("#FFFFFF"), HELVITT_FOTO);
  assert.ok(utanSkärm < KRAV_BRÖDTEXT,
    `vit text direkt på ett helvitt foto räknades till ${utanSkärm.toFixed(2)}:1`);
  assert.ok(Math.abs(utanSkärm - 1) < 0.001, "vitt på vitt är 1:1");
});

test("toningen är FULL --scrim under hela textblocket, inte bara längst ned", () => {
  const skärm = nod("hero-meal-scrim");
  const stopp = gradientstopp(skärm.stil.background);
  const scrim = tolkaFärg(vars.get("--scrim"));

  const sista = stopp[stopp.length - 1];
  assert.equal(sista.plats, "100%", "toningen slutar inte vid fotots underkant");
  assert.deepEqual(tolkaFärg(sista.färg), scrim, "sista stoppet är inte --scrim");

  // Stoppet där toningen blir full: samma färg som det sista, alltså platt
  // därifrån och ned.
  const platt = stopp.filter((s) => JSON.stringify(tolkaFärg(s.färg)) === JSON.stringify(scrim));
  assert.ok(platt.length >= 2,
    "toningen når full --scrim först i sista stoppet - då är bara fotots understa rad skyddad, " +
    "och texten ovanför den ligger på en svagare ton än den 10,23:1 räknats på");
  const skyddad = -pxSumma(platt[0].plats.replace(/^calc\(100%/, "calc(0px"));
  assert.ok(skyddad > 0, `kunde inte läsa ut den skyddade zonens höjd ur "${platt[0].plats}"`);

  // ...och textblocket kan inte sträcka sig utanför den zonen, hur lång
  // rubriken än blir.
  const text = nod("hero-meal-info");
  const botten = pxSumma(text.stil.bottom);
  const maxhöjd = pxSumma(text.stil["max-height"]);
  assert.ok(botten != null && maxhöjd != null,
    "hjältetexten saknar bottom/max-height - då kan en lång rubrik växa uppåt ur skyddet");
  assert.equal(text.stil.overflow, "hidden",
    "utan overflow:hidden är max-height ingen gräns, bara en förhoppning");
  assert.ok(botten + maxhöjd <= skyddad,
    `texten kan nå ${botten + maxhöjd}px över fotots underkant, men toningen är full först ` +
    `${skyddad}px upp. Den delen av texten ligger på en svagare ton än 10,23:1.`);
});

test("skärmen gör jobbet - ingen text-shadow, och alltid låst vitt", () => {
  const påFotot = ritad.filter((n) => n.väg.includes("hero-meal-info") || n.klasser.includes("hero-meal-meta"));
  assert.ok(påFotot.length >= 4, "hittade inte hjältetexten i den ritade markupen");
  for (const n of påFotot) {
    const skugga = n.stil["text-shadow"];
    if (skugga === undefined) continue;
    assert.equal(skugga, "none",
      `${n.väg} har text-shadow: ${skugga}. En skugga är ingen kontrast - den är en ` +
      "förhandling med fotot, och den förhandlingen förlorar mot en ljus bild (§5.2).");
  }
  const rubrik = ritad.find((n) => n.tagg === "strong" && n.väg.includes("hero-meal-info"));
  assert.ok(rubrik, "rättens namn står inte i hjältetexten");
  assert.equal(tolkaFärg(rubrik.stil.color)?.join(), "255,255,255,1",
    "rubriken på fotot är inte låst vit. Ett foto har inget tema - --ink följer " +
    "läget och blir nästan vit i mörkt läge och nästan svart i ljust (§5.2).");
});

test("--scrim följer inte temat: ett foto är lika ljust i mörkt läge", () => {
  assert.ok(mörk.size > 0, "det mörka läget har inga tokens alls");
  assert.equal(mörk.get("--scrim") ?? vars.get("--scrim"), vars.get("--scrim"),
    "--scrim är omdefinierad i mörkt läge. Skärmen ska mörklägga FOTOT, inte " +
    "följa användarens tema - fotot är lika ljust i båda lägena (§2.1).");
});

test("fotot fyller bredden - helbleed, inte ett kort med marginal", () => {
  const bild = ritad.find((n) => n.klasser.includes("recipe-photo"));
  assert.ok(bild, "hjältefotot finns inte i markupen");
  assert.equal(bild.stil.width, "100%", "fotot är inte lika brett som sin behållare");
  assert.equal(pxSumma(bild.stil.height), 278, "hjältefotot är inte 278px högt");
  assert.equal(bild.stil["object-fit"], "cover", "fotot beskärs inte, det förvrängs");
  assert.equal(pxSumma(bild.stil["border-radius"]), 0, "fotot har rundade hörn (--radius är 0, §4.3)");

  // Behållaren måste dra sig UT ur sidmarginalen, annars blir "helbleed" en
  // vit remsa på vardera sidan. Talen jämförs mot .app:s faktiska padding,
  // så en ändrad sidmarginal fångas här i stället för på en skärmdump.
  for (const media of [null, "max-width:340px"]) {
    const padding = regelStil(".app", media).get("padding")
      ?? regelStil(".app", media).get("padding-inline");
    if (padding === undefined) continue;
    const gutter = sidpadding(padding);
    const marginal = pxSumma(regelStil(".ikvall-bild", media).get("margin-inline") ?? "");
    assert.equal(marginal, -gutter,
      `.app har ${gutter}px sidmarginal men fotot dras ut ${marginal}px ` +
      `${media ? `(${media})` : ""} - helbleed blir en vit remsa på vardera sidan`);
  }
});

test("rubriken ligger PÅ fotot, inte under det", () => {
  const bild = nod("hero-meal-photo");
  const text = nod("hero-meal-info");
  const skärm = nod("hero-meal-scrim");

  // Samma behållare, alltså samma yta.
  const behållare = (n) => n.väg.slice(0, n.väg.lastIndexOf(" "));
  assert.equal(behållare(text), behållare(bild),
    "texten och fotot ligger inte i samma behållare - då ligger texten bredvid bilden");
  assert.equal(behållare(skärm), behållare(bild), "skärmen ligger inte över fotot");

  assert.equal(regelStil(".ikvall-bild").get("position"), "relative",
    "fotots behållare är inte positionerad - då fäster texten mot något annat");
  assert.equal(text.stil.position, "absolute", "hjältetexten ligger i flödet, alltså under fotot");
  assert.equal(skärm.stil.position, "absolute", "skärmen ligger i flödet, alltså inte över fotot");

  const rubrik = ritad.find((n) => n.tagg === "strong" && n.väg.includes("hero-meal-info"));
  assert.equal(rubrik.text.trim(), RÄTT.namn, "det är inte rättens namn som ligger på fotot");
  const ögonbryn = ritad.find((n) => n.tagg === "small" && n.väg.includes("hero-meal-info"));
  assert.equal(ögonbryn.text.trim(), "Ikväll · onsdag");
  assert.equal(ögonbryn.stil["text-transform"], "uppercase",
    "ögonbrynet versaliseras inte i CSS. Versaler i HTML får skärmläsaren att " +
    "stava dem bokstav för bokstav: \"I-K-V-Ä-L-L\" (§8).");
  assert.ok(KORT.includes("Ikväll · onsdag"),
    "ögonbrynet står versaliserat i källan i stället för i CSS");
});

// ---------------------------------------------------------------------------
// DET ANDRA VÄRSTA FALLET — ETT RECEPT UTAN FOTO
//
// Kravet säger "ett helvitt foto under". Sedan M2 har hjälteytan ett underlag
// till: elva av receptbankens rätter har inget foto vi får publicera, och TIO
// AV DEM ÄR `middag` — alltså rätter veckoplaneraren faktiskt lägger på
// Ikväll. Reservkortet är ingen randfallsyta på den här skärmen; det är
// bildytans andra normalläge, och toningen måste bära rubriken över det
// också.
//
// Beviset är inte en skärmdump av just Kroppkakor. Testet ritar hjälten med
// kortet under, plockar ut VARJE färg som faktiskt målas inne i bildytan —
// yta, ram, kapitäler, linje, monogram — i båda lägena, lägger skärmen över
// och räknar. Får kortet en ny yta i morgon räknas den med utan att någon
// behöver komma ihåg det här testet.
// ---------------------------------------------------------------------------

const UTAN_FOTO = {
  id: "kroppkakor", namn: "Kroppkakor med smör och lingon", typ: "Husmanskost",
  tid: 60, servings: 4, portionspris: 21, priceStatus: "priced",
  priceTier: "VERIFIED_STORE_PRICE",
};
// Exakt det app.js skickar in: komponentens yta, `namn: false`.
const RESERVKORT = ikvallMarkup(UTAN_FOTO, {
  ögonbryn: "Ikväll · onsdag", meta: "60 min · 4 portioner",
  foto: receptbildMarkup(UTAN_FOTO, { namn: false }),
});
const ritatKort = rita(RESERVKORT, css, vars);

// Allt som ligger OVANPÅ skärmen är text, inte underlag - det är den texten
// vi mäter, inte det den ligger på.
const ÖVER_SKÄRMEN = /hero-meal-info|hero-meal-meta|hero-meal-scrim|hero-meal-swap/;
const FÄRGEGENSKAP = /^(color|background|background-color|background-image|outline|outline-color|border(-(top|right|bottom|left))?-color|border|fill|stroke)$/;

/** Varje färg som faktiskt målas inne i hjältens bildrektangel. */
function underlagsfärger(ritning) {
  const ut = new Map();
  for (const n of ritning) {
    if (!n.väg.includes("hero-meal-open") || ÖVER_SKÄRMEN.test(n.väg)) continue;
    if (n.dolt) continue;                       // display:none målar ingenting
    for (const [prop, värde] of Object.entries(n.stil)) {
      if (!FÄRGEGENSKAP.test(prop)) continue;
      for (const { text, f } of färgerI(värde)) {
        if (f[3] === 0) continue;               // genomskinligt målar ingenting
        ut.set(`${n.väg} { ${prop}: ${text} }`, f);
      }
    }
  }
  return ut;
}

test("skärmen ligger över reservkortet, lika mörk som över ett foto", () => {
  // Det här är provet som kan bli rött. Färgsvepet nedan är ett BEVIS — ingen
  // färg i sRGB är ljusare än vitt, så ett kort kan aldrig bli ett värre
  // underlag än det helvita fotot. Det som däremot går att råka göra är att
  // ta bort skyddet just här: dölja toningen när det inte finns något foto
  // att tona ("kortet syns ju ändå"), eller lyfta kortet över den. Då står
  // rubriken på bar yta, och färgsvepet hade inte märkt något.
  const medFoto = ritad.find((n) => n.klasser.includes("hero-meal-scrim"));
  const utanFoto = ritatKort.find((n) => n.klasser.includes("hero-meal-scrim"));
  assert.ok(utanFoto, "hjälten ritar ingen skärm alls när receptet saknar foto");
  assert.ok(!utanFoto.dolt,
    "skärmen är dold över ett recept utan foto - då ligger den vita rubriken på kortets " +
    "egen pappersyta, och 10,23:1 gäller inte längre någonting");
  assert.equal(utanFoto.stil.background, medFoto.stil.background,
    "toningen är en annan över reservkortet än över ett foto. Kortet är ett underlag " +
    "som alla andra - dämpas det mindre är kravet uträknat på fel bakgrund.");

  // Kortet får inte resa sig ur skyddet. Både kortet (position:relative ur
  // .reservkort) och skärmen är positionerade med automatiskt lager, så det
  // är dokumentordningen som avgör - tills någon sätter ett z-index.
  const kort = ritatKort.find((n) => n.klasser.includes("reservkort"));
  const lager = (n) => Number(n.stil["z-index"]) || 0;
  assert.ok(lager(utanFoto) >= lager(kort),
    `reservkortet ligger i lager ${lager(kort)} och skärmen i ${lager(utanFoto)} - ` +
    "kortet reser sig över toningen i stället för att ligga under den");
});

test("reservkortet är hjälteytans andra underlag - toningen bär texten över det med", () => {
  const skärm = tolkaFärg(vars.get("--scrim"));
  const vit = tolkaFärg("#FFFFFF");
  // Golvet från provet högst upp: vit text på toningen över ett helvitt foto.
  const golv = kontrast(vit, avrunda(lägg(skärm, HELVITT_FOTO)));

  for (const [läge, tema] of [["ljust", vars], ["mörkt", mörk]]) {
    const färger = underlagsfärger(rita(RESERVKORT, css, tema));
    assert.ok(färger.size >= 3,
      `hittade bara ${färger.size} målade färger i hjältens bildyta i ${läge} läge - ` +
      "testet mäter då inte reservkortet utan en tom ruta");

    for (const [ursprung, färg] of färger) {
      const ratio = kontrast(vit, avrunda(lägg(skärm, färg)));
      assert.ok(ratio >= KRAV_BRÖDTEXT,
        `${läge} läge: rubriken mot toningen över ${ursprung} ger ${ratio.toFixed(2)}:1, ` +
        `kravet är ${KRAV_BRÖDTEXT}:1`);
      // Och kortet får inte vara ett VÄRRE underlag än det värsta foto vi
      // räknat på. Mörkt läge är den intressanta raden: där är --ink nästan
      // vit, alltså är monogrammet kortets ljusaste punkt - men fortfarande
      // mörkare än #FFFFFF, så golvet håller.
      assert.ok(ratio >= golv - 0.005,
        `${läge} läge: ${ursprung} är ljusare än ett helvitt foto (${ratio.toFixed(2)}:1 mot ` +
        `golvets ${golv.toFixed(2)}:1). Då bär inte det uträknade golvet den här skärmen.`);
    }
  }
});

test("utan foto står rätten EN gång - rubriken på bilden, monogrammet på kortet", () => {
  assert.ok(!RESERVKORT.includes("<img"),
    "ett recept utan foto renderar en <img> utan adress - det är hålet M2 stängde");
  assert.match(RESERVKORT, /class="[^"]*\breservkort--utan-namn\b/,
    "hjälteytan ber om ett kort MED namn. Rubriken ligger redan PÅ bilden, och två " +
    "namn i samma rektangel är inte en design - det är ett misstag (`namn: false`).");
  assert.ok(!RESERVKORT.includes("reservkort-namn"), "kortet skriver rättens namn en andra gång");

  // Synligt, alltså inte det som bara finns för skärmläsaren: kortets
  // aria-label bär rätten också, och det ska den.
  const synliga = ritatKort.filter((n) => !n.dolt && n.text.includes(UTAN_FOTO.namn));
  assert.equal(synliga.length, 1,
    `rättens namn syns ${synliga.length} gånger i hjälteytan: ${synliga.map((n) => n.väg).join(", ")}`);
  assert.equal(synliga[0].tagg, "strong", "namnet står inte som rubrik på bilden");
  assert.match(RESERVKORT, /aria-label="Foto saknas[^"]*Kroppkakor/,
    "kortet säger inte åt skärmläsaren att fotot saknas");

  // Det som står kvar i rektangeln är monogrammet.
  const märke = ritatKort.find((n) => n.klasser.includes("reservkort-monogram"));
  assert.ok(märke && !märke.dolt,
    "monogrammet är dolt - då är kortet en tom platta med en rubrik på, alltså den grå rutan igen");
});

test("hjälten sätter kortets MÅTT, aldrig dess utseende", () => {
  const hjälte = regelStil(".hero-meal-photo .recipe-fallback");
  assert.equal(pxSumma(hjälte.get("height")), 278,
    "reservkortet fyller inte samma 278 px som fotot");
  assert.equal(hjälte.get("width"), "100%", "kortet är inte lika brett som bildytan");
  assert.equal(pxSumma(hjälte.get("border-radius")), 0, "kortet har rundade hörn (--radius är 0, §4.3)");

  for (const prop of ["background", "background-color", "background-image", "padding",
                      "display", "flex-direction", "align-items", "justify-content"]) {
    assert.ok(!hjälte.has(prop),
      `.hero-meal-photo .recipe-fallback sätter ${prop}. Hjälten äger måttet, komponenten ` +
      "äger utseendet: en egen bakgrund (--shot) eller en egen layout här lägger tillbaka " +
      "den grå rutan ovanpå M2:s kort, med en rubrik på.");
  }

  // Och kortet ligger under samma skärm som rubriken: syskon till bildytan,
  // senare i dokumentet, alltså ovanpå.
  const kort = ritatKort.find((n) => n.klasser.includes("reservkort"));
  const skärm = ritatKort.find((n) => n.klasser.includes("hero-meal-scrim"));
  assert.ok(kort?.väg.includes("hero-meal-photo"),
    "reservkortet ligger utanför bildytan - då ligger det inte under skärmen");
  assert.ok(ritatKort.indexOf(kort) < ritatKort.indexOf(skärm),
    "skärmen ritas före kortet - då ligger kortet ovanpå toningen i stället för under");
});

// ---------------------------------------------------------------------------
// PRISET, BUDGETEN, FYNDET
// ---------------------------------------------------------------------------

test("prisraden skriver INGEN egen prismarkup - den kallar L0:s komponent", () => {
  assert.ok(KORT.includes(prisMarkup(38.5, "kontrollerat", { klass: "ikvall-belopp" })),
    "prisraden innehåller inte exakt det prisMarkup() skriver");

  // Och modulen får inte kunna göra det själv. Sju vyer som var för sig
  // skriver <span class="pris"> är sju ställen där en prisregel kan brytas
  // utan att någon märker det.
  const källa = läsFil("frontend/app/src/views/ikvall.js");
  for (const klass of ["pris", "pris--ca", "saknas", "cirka", "minst"]) {
    assert.ok(!new RegExp(`class="[^"]*\\b${klass.replace("--", "--")}\\b`).test(källa),
      `src/views/ikvall.js skriver egen markup med klassen "${klass}". ` +
      "De tre prisreglerna finns i src/views/pris.js och ingen annanstans.");
  }
});

test("ett saknat portionspris blir ett tomt fack - aldrig rött", () => {
  const utanPris = ikvallMarkup(
    { ...RÄTT, portionspris: null, priceStatus: "unavailable" },
    { ögonbryn: "Ikväll · onsdag", meta: "25 min", foto: FOTO });
  assert.ok(utanPris.includes("pris saknas"), "ett saknat pris visas inte som ett tomt fack");
  const stil = rita(utanPris, css, vars).find((n) => n.klasser.includes("saknas"));
  assert.equal(tolkaFärg(stil.stil.color)?.join(), tolkaFärg(vars.get("--ink-3")).join(),
    "det tomma facket ritas i något annat än --ink-3");
});

test("vägen vidare står till höger om priset, i accentfärg", () => {
  assert.ok(KORT.indexOf("ikvall-portion") < KORT.indexOf("ikvall-recept"),
    "priset står inte till vänster om vägen vidare");
  const knapp = nod("ikvall-recept");
  assert.equal(tolkaFärg(knapp.stil.color).join(), tolkaFärg(vars.get("--accent")).join(),
    "\"Se receptet\" är inte accentfärgad");
  assert.ok(pxSumma(knapp.stil["min-height"]) >= 44, "träffytan är under 44px");
});

test("budgetremsan säger vad den vet, och säger över budget i ORD", () => {
  const money = (v) => `${Math.round(v)} kr`;

  const inom = budgetremsaText({ budget: 800, använt: 188, money });
  assert.equal(inom.belopp, "612 kr");
  assert.equal(inom.efter, "kvar av 800 kr");
  assert.equal(inom.andel, 24);
  assert.equal(inom.etikett, "188 kr av 800 kr använda",
    "mätarens etikett är bara en procent - \"24 % av vad\" är ingen upplysning i en affär (§5.8)");

  const över = budgetremsaText({ budget: 800, använt: 884, money });
  assert.equal(över.belopp, "84 kr");
  assert.equal(över.efter, "över 800 kr", "överskridandet står inte i ord");
  assert.equal(över.andel, 100, "fyllnaden går inte till 100 % över budget");

  const ovecka = budgetremsaText({ budget: 800, använt: null, harVecka: false, money });
  assert.equal(ovecka.belopp, "800 kr");
  assert.equal(ovecka.efter, "veckobudget");
  assert.equal(ovecka.andel, 0);

  // total == null betyder "priset är inte hämtat", inte "veckan kostar 0 kr".
  const hämtas = budgetremsaText({ budget: 800, använt: null, money });
  assert.equal(hämtas.belopp, "–");
  assert.equal(hämtas.not, "hämtas…");
  assert.equal(hämtas.andel, 0);
  assert.equal(hämtas.etikett, "", "mätaren påstår en förbrukning som inte är känd");
});

test("mätaren är en 6px remsa vars markör bär betydelsen i FORM", () => {
  const spår = regelStil(".ikvall-remsa .progress-track");
  assert.equal(pxSumma(spår.get("height")), 6, "mätaren är inte 6px hög");
  assert.equal(pxSumma(spår.get("border-radius")), 0, "mätaren har rundade hörn (--radius är 0)");

  const fyllnad = regelStil(".ikvall-remsa .progress-track i");
  const markör = regelStil(".ikvall-remsa .progress-track::after");
  assert.equal(fyllnad.get("width"), vars.get("--andel"),
    "fyllnaden läser inte samma --andel som markören - två tal som kan glida isär");
  assert.equal(markör.get("left"), vars.get("--andel"));
  assert.equal(pxSumma(markör.get("width")), 1, "markören är inte ett 1px streck");
  assert.equal(tolkaFärg(markör.get("background")).join(), tolkaFärg(vars.get("--ink")).join(),
    "markören ritas inte i --ink. En accentfärgad fyllnad går inte att läsa i " +
    "gråskala; det svarta strecket gör det (§5.8).");

  // RÄTTELSE 1: --ink-3 får aldrig ligga på --paper-2.
  assert.equal(tolkaFärg(regelStil(".ikvall-remsa .ikvall-kap").get("color")).join(),
    tolkaFärg(vars.get("--ink-2")).join(),
    "etiketten i remsan står i --ink-3 på --paper-2 (4,31:1) - RÄTTELSE 1 kräver --ink-2");
});

test("fyndraden lovar bara det den kan hålla", () => {
  const money = (v) => `${Math.round(v)} kr`;
  const glass = { name: "Glass", chain: "Willys", campaignPrice: 8, regularPrice: 12 };
  const karré = { name: "Fläskkarré", chain: "Willys", campaignPrice: 96, regularPrice: 120 };

  assert.equal(fyndradMarkup([], { money }), "",
    "en rubrik över en tom rad är sämre än tystnad");
  assert.equal(fyndradMarkup(null, { money }), "");

  // Utan C11 finns ingen receptkoppling. Raden säger varan, kedjan och
  // priset - och hittar aldrig på en rätt att byta in.
  const utan = fyndradMarkup([glass, karré], { money });
  assert.ok(utan.includes("Fläskkarré"), "fyndet rankas på procent i stället för kronor");
  assert.ok(!/Byt in/.test(utan), "raden lovar ett byte utan att veta vilken rätt det gäller");
  assert.ok(utan.includes("96 kr") && utan.includes("120 kr"));

  // Med C11:s recipeIds/savesOnWeek säger raden vad fyndet gör med VECKAN.
  const med = fyndradMarkup(
    [glass, { ...karré, recipeIds: ["flaskfilerotmos"], savesOnWeek: 24.2 }],
    { receptNamn: (id) => (id === "flaskfilerotmos" ? "Fläskfilé med rotmos" : ""), money });
  assert.ok(med.includes("Byt in Fläskfilé med rotmos"), `fyndraden säger: ${med}`);
  assert.ok(med.includes("24 kr billigare den här veckan"));
});

test("ingen vecka: inbjudan på papper, inte vit text utan foto under", () => {
  const tom = ikvallTomMarkup();
  assert.ok(!/hero-meal-scrim/.test(tom), "inbjudan har en skärm men inget foto att skärma");
  const rubrik = rita(tom, css, vars).find((n) => n.tagg === "strong");
  assert.equal(tolkaFärg(regelStil(".hero-meal-invite").get("color")).join(),
    tolkaFärg(vars.get("--ink")).join(),
    "inbjudan står i vitt utan ett foto under - alltså vitt på papper");
  assert.ok(rubrik.text.includes("middag"), "inbjudan frågar inte om middagen");
});
