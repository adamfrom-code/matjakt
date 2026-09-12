// M2:s acceptanskriterium: INGET recept renderar en tom bildyta.
//
// Kriteriet är formulerat på det sätt som gör det svårt att fuska med.
// "Rendera receptkortet och kolla att bilden syns" är grönt även när
// reservkortet är sönder, för de 209 recept som HAR foto renderar precis som
// förut. Testet matar därför in ett recept UTAN bild i varje väg som ritar en
// bildyta - Ikväll, Veckan och receptvyn - och kräver att det som kommer ut
// har både yta och innehåll.
//
// Tre lager, för att hålet kan öppna sig i tre olika skikt:
//
//   1. KOMPONENTEN   receptbildMarkup() ska aldrig lämna ifrån sig en
//                    <img src=""> eller en tom span. Också en bild vars
//                    ADRESS inte går att använda räknas som ingen bild -
//                    det var precis den buggen som gjorde receptvyns hjälte
//                    till ett hål i den native appen.
//   2. STILEN        kortet ska ha en yta och synlig text vid BÅDA
//                    storlekarna. Ett kort som bara är ritat för 278 px blir
//                    oläsligt i 52-pixelsraden, och ett kort där allt är
//                    display:none är en grå ruta med extra steg.
//   3. VÄGARNA       varje vy som ritar en receptbild ska gå genom
//                    komponenten. Skriver en vy sin egen <img> är regeln
//                    bruten i just den vyn och ingen upptäcker det.
//
// Plus provenansen: ett foto utan licensuppgift är en juridisk skuld i ett
// publikt repo, inte en bild.

import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import test from "node:test";

import { deklarationer, läsFil, läsStyles, lösVar, parseRegler, rotVariabler }
  from "./fixtures/css-parser.mjs";
import { kontrast, tolkaFärg } from "./fixtures/kontrast.mjs";
import { receptbildMarkup, receptbildUrl, reservkortMarkup }
  from "../frontend/app/src/views/receptbild.js";

const css = läsStyles();
const regler = parseRegler(css);
const TEMAN = { ljust: rotVariabler(regler), mörkt: rotVariabler(regler, '[data-theme="dark"]') };

// En riktig rätt ur banken, vald för att den INTE har något foto och heller
// inte lär få något: Commons har kroppkakor, men bilderna är hemmaknäppta.
const UTAN_BILD = { id: "kroppkakor", namn: "Kroppkakor med smör och lingon", typ: "Husmanskost" };
const MED_BILD = {
  id: "kroppkakor", namn: "Kroppkakor med smör och lingon",
  bild: "assets/recipes/kroppkakor.jpg",
};

/** Texten som faktiskt står i markupen, taggarna borträknade. */
const text = markup => markup.replace(/<[^>]*>/g, "").trim();

// ---------------------------------------------------------------------------
// LAGER 1 · KOMPONENTEN
// ---------------------------------------------------------------------------

test("ett recept utan bild ger ett kort med innehåll, inte en tom yta", () => {
  const markup = receptbildMarkup(UTAN_BILD);
  assert.ok(!markup.includes("<img"), `en <img> utan bild att visa: ${markup}`);
  assert.match(markup, /class="[^"]*\breservkort\b/);
  assert.ok(text(markup).length > 0, "kortet är tomt - det är samma grå ruta som förut");
  assert.ok(markup.includes("Kroppkakor med smör och lingon"),
    "rättens namn står inte på kortet");
});

test("kortet bär BÅDA storlekarnas innehåll, så CSS:en har något att välja mellan", () => {
  const markup = reservkortMarkup(UTAN_BILD);
  for (const del of ["reservkort-kap", "reservkort-linje", "reservkort-namn", "reservkort-monogram"]) {
    assert.ok(markup.includes(del), `${del} saknas i markupen`);
  }
  // Monogrammet är rättens egen begynnelsebokstav - ingen gissad ikon.
  assert.match(markup, /class="reservkort-monogram"[^>]*>K</);
});

test("monogrammet klarar svenska versaler och rätter utan namn", () => {
  assert.match(reservkortMarkup({ namn: "Örtbakad torskrygg" }), /reservkort-monogram"[^>]*>Ö</);
  // Tom rätt: receptvyns laddningsläge ritar bildytan innan receptet finns.
  const tom = receptbildMarkup({});
  assert.ok(!tom.includes("<img"));
  assert.ok(text(tom).length > 0, "laddningslägets bildyta är tom");
});

test("kortet säger i ord att fotot saknas, och säger det EN gång", () => {
  const markup = reservkortMarkup(UTAN_BILD);
  assert.match(markup, /role="img"/);
  assert.match(markup, /aria-label="Foto saknas – Kroppkakor med smör och lingon"/);
  // Delarna inuti är aria-hidden: skärmläsaren ska höra rätten en gång.
  const synligaDelar = [...markup.matchAll(/<span class="reservkort-[^"]*"(?![^>]*aria-hidden)/g)];
  assert.equal(synligaDelar.length, 0,
    "en del av kortet läses upp extra - namnet står redan i aria-label");
});

test("namnet går att stänga av för en vy som skriver ut det PÅ bilden", () => {
  // Receptvyns uppslag (L4) och Ikvälls hjälteyta (L1) lägger båda rubriken
  // på fotot. Två namn i samma rektangel är inte en design.
  const utan = reservkortMarkup(UTAN_BILD, { namn: false });
  assert.ok(!utan.includes("reservkort-namn"));
  assert.ok(text(utan).length > 0, "kortet blev tomt när namnet stängdes av");
  assert.ok(utan.includes("reservkort-kap") && utan.includes("reservkort-monogram"));
  // Utan namn måste monogrammet tillbaka i det stora läget, annars är
  // hjälteytan en kapitäletikett på en tom platta.
  assert.match(utan, /\breservkort--utan-namn\b/);
  const märke = regelFör(".reservkort--utan-namn .reservkort-monogram",
                         { container: "min-width" });
  assert.ok(märke.get("display") && märke.get("display") !== "none",
    "kortet utan namn visar inget monogram i det stora läget");
  // Och det står i kolumnen, inte mitt på kortet: rubriken som vyn lägger
  // PÅ bilden ligger nedtill, och en centrerad bokstav hamnar bakom den så
  // fort rubriken går i tre rader - vilket den gör vid 320 px.
  assert.equal(märke.get("position"), "static",
    "monogrammet ligger kvar centrerat och kan skymmas av rubriken på bilden");
});

test("ett recept MED bild renderar fotot, annars mäter testet ingenting", () => {
  const markup = receptbildMarkup(MED_BILD);
  assert.match(markup, /^<img class="recipe-photo" src="assets\/recipes\/kroppkakor\.jpg"/);
  assert.match(markup, /alt="Kroppkakor med smör och lingon"/);
});

test("en bild vars adress inte går att använda är ingen bild - då gäller kortet", () => {
  // Det här var hålet i receptvyn: `recipe.bild ? <img> : kort` frågade om
  // FÄLTET fanns, inte om adressen gick att sätta i src. En bild som filtret
  // vägrade gav <img src=""> - webbläsarens trasiga-bild-glyf, inte ett kort.
  for (const bild of ["javascript:alert(1)", "   ", "data:image/png;base64,AAAA"]) {
    const markup = receptbildMarkup({ ...UTAN_BILD, bild });
    assert.ok(!markup.includes("<img"), `${bild} blev en <img>`);
    assert.match(markup, /\breservkort\b/);
  }
  assert.ok(!/src=""/.test(receptbildMarkup({ ...UTAN_BILD, bild: "javascript:alert(1)" })));
});

test("appens egna receptfoton överlever även när sidan inte är http", () => {
  // Native-appen körs på capacitor://localhost. safeHttpUrl() släpper bara
  // igenom http/https och skulle kasta bort varje relativ adress - alltså
  // exakt de 74 foton vi själva har lagt i bygget.
  assert.equal(receptbildUrl("assets/recipes/kroppkakor.jpg"), "assets/recipes/kroppkakor.jpg");
  // Men bara vårt eget mönster. Allt annat går genom filtret som förut.
  assert.equal(receptbildUrl("assets/../../etc/passwd"), "");
  assert.equal(receptbildUrl("javascript:alert(1)"), "");
});

// ---------------------------------------------------------------------------
// LAGER 2 · STILEN - kortet i båda storlekarna
// ---------------------------------------------------------------------------

/**
 * Deklarationerna som gäller för selektorn `väljare`, sist vinner. `container`
 * väljer sida: null = utanför varje @container-fråga (grundläget, det som en
 * webbläsare utan container-queries ser), en sträng = inuti den frågan.
 */
function regelFör(väljare, { container = null } = {}) {
  const ut = new Map();
  for (const regel of regler) {
    const iContainer = regel.media.some(m => m.startsWith("@container"));
    if (container === null ? iContainer : !iContainer) continue;
    if (container && !regel.media.some(m => m.includes(container))) continue;
    if (!regel.delar.some(del => del.trim() === väljare)) continue;
    for (const d of deklarationer(regel.block)) ut.set(d.prop, d.värde);
  }
  return ut;
}

test("kortet har en pappersyta ur designsystemet, inte en grå platshållarton", () => {
  const bas = regelFör(".reservkort");
  assert.ok(bas.has("background"), ".reservkort saknar bakgrund - då är kortet genomskinligt");
  for (const [läge, vars] of Object.entries(TEMAN)) {
    const färg = tolkaFärg(lösVar(bas.get("background"), vars).trim());
    assert.ok(färg && färg[3] > 0, `bakgrunden löser inte till en färg i ${läge} läge`);
    // --shot är platshållartonen bakom foton som inte laddat. Reservkortet är
    // inte ett foto som inte laddat - det är ett medvetet kort.
    const shot = tolkaFärg(lösVar(vars.get("--shot") || "", vars).trim());
    assert.notDeepEqual(färg.slice(0, 3), shot.slice(0, 3),
      `kortet ligger på --shot i ${läge} läge - det är platshållartonen, inte en yta`);
  }
});

test("kortets ram är hårfin och ritad i en linjetoken", () => {
  const ram = regelFör(".recipe-fallback.reservkort").get("outline") || "";
  assert.match(ram, /1px\s+solid\s+var\(--rule/, `ramen är inte en hårfin linjetoken: ${ram}`);
});

test("det lilla läget: monogrammet är det som syns, och det syns", () => {
  for (const del of [".reservkort-kap", ".reservkort-linje", ".reservkort-namn"]) {
    assert.equal(regelFör(del).get("display"), "none",
      `${del} är inte dold i grundläget - den får inte plats i 52 px`);
  }
  const märke = regelFör(".reservkort-monogram");
  assert.notEqual(märke.get("display"), "none",
    "både namnet och monogrammet är dolda i grundläget - kortet är då en tom ruta");
  assert.match(märke.get("font-family") || "", /--f-disp/,
    "monogrammet sätts inte i display-serifen");
});

/**
 * Container-frågans tröskel. Den mäter containerns CONTENT-box - kortet MINUS
 * paddingen - och är därför inte samma tal som kortets utvändiga bredd.
 */
function containerTröskel() {
  const frågor = regler.flatMap(r => r.media.filter(m => m.startsWith("@container")));
  assert.ok(frågor.length > 0, "det finns ingen @container-fråga - kortet har bara en storlek");
  const träff = /min-width:\s*([\d.]+)px/.exec(frågor[0]);
  assert.ok(träff, `container-frågan mäter inte en bredd: ${frågor[0]}`);
  return Number(träff[1]);
}

/**
 * Kortets padding som funktion av dess UTVÄNDIGA bredd, räknad ur CSS:en.
 *
 * Paddingen står i procent och inte i `cqi`, och det är hela poängen. `cqi` i
 * en deklaration PÅ själva query-containern kan inte lösa mot containern - det
 * vore cirkulärt - så den löser mot närmaste förfaders container, och finns
 * ingen sådan mot viewporten. Den skrivningen gav 18 px padding på varje kort
 * på en 390-pixelsskärm: lika mycket på en 44-pixelsruta som på en
 * 350-pixelshjälte. Procent mäter förälderns bredd, och kortet fyller sin
 * förälder i varje kontext - alltså kortets egen bredd, utan cirkeln.
 */
function paddingVid() {
  const padding = (regelFör(".recipe-fallback.reservkort").get("padding") || "").trim();
  assert.ok(!/\bcq(i|w|b|h|min|max)\b/.test(padding),
    `kortets padding är satt i container-enheter: ${padding}. På själva ` +
    "query-containern löser de mot viewporten, inte mot kortet.");
  const c = /^clamp\(\s*([\d.]+)px\s*,\s*([\d.]+)%\s*,\s*([\d.]+)px\s*\)$/.exec(padding);
  assert.ok(c, `paddingen går inte att räkna på: ${padding}`);
  const [, min, procent, max] = c.map(Number);
  return bredd => Math.min(max, Math.max(min, (procent / 100) * bredd));
}

/** Kortets content-box vid en given utvändig bredd. */
const innerBredd = (bredd, pad) => bredd - 2 * pad(bredd);

/** Den UTVÄNDIGA bredd där kortet byter till det stora läget. */
function brytpunkt() {
  const pad = paddingVid(), tröskel = containerTröskel();
  let låg = 0, hög = 1000;                 // innerBredd() växer med bredden
  for (let i = 0; i < 50; i++) {
    const mitt = (låg + hög) / 2;
    if (innerBredd(mitt, pad) >= tröskel) hög = mitt; else låg = mitt;
  }
  return hög;
}

// De fyra ytor kortet faktiskt ligger på, uppmätta i Chromium på 390 px bred
// skärm. `litet` = monogrammet ensamt, `stort` = kapitäler, linje och namnet.
const KONTEXTER = [
  ["veckoraden", 44, "litet"],
  ["Ikväll-thumbnailen", 76, "litet"],
  ["recepthyllan", 146, "stort"],
  ["receptvyns hjälte", 350, "stort"],
];

test("brytpunkten ligger på den UTVÄNDIGA bredd kommentaren lovar", () => {
  // Det här är testet som inte fanns. Att läsa talet i @container-frågan
  // bevisar ingenting om kortet: frågan mäter content-boxen, så den bredd
  // användaren ser byta läge är tröskeln PLUS paddingen. Med 18 px per sida
  // slog det stora läget inte in förrän kortet var ~168 px brett utvändigt,
  // och @container-frågan sa fortfarande 132.
  const vid = brytpunkt();
  assert.ok(Math.abs(vid - 132) <= 1,
    `det stora läget slår in vid ${vid.toFixed(1)} px utvändigt, inte vid 132 px ` +
    `(tröskeln i @container är ${containerTröskel()} px och mäter content-boxen)`);
});

test("varje kontext hamnar i sitt läge - recepthyllan visar namnet", () => {
  // Talen är mätta, men två av dem står i stilmallen och kan ändras av ett
  // annat paket. Då ska kontexterna mätas om, inte glida i tysthet.
  for (const [väljare, bredd] of [[".week-plan-photo", 44], [".hero-meal-photo", 76]]) {
    const iCss = /([\d.]+)px/.exec(regelFör(väljare).get("width") || "");
    assert.equal(Number(iCss?.[1]), bredd,
      `${väljare} är inte längre ${bredd} px - mät om kontexterna i webbläsaren`);
  }
  const pad = paddingVid(), tröskel = containerTröskel();
  for (const [namn, bredd, väntat] of KONTEXTER) {
    const inner = innerBredd(bredd, pad);
    assert.equal(inner >= tröskel ? "stort" : "litet", väntat,
      `${namn} (${bredd} px utvändigt) får fel läge: content-boxen är ` +
      `${inner.toFixed(1)} px mot tröskeln ${tröskel} px`);
  }
});

test("paddingen äter aldrig upp kortet - content-boxen är en yta, inte en rest", () => {
  // Det lilla lägets monogram är `position:absolute;inset:0` och struntar i
  // paddingen. Därför SYNTES det inte att 44-pixelskortet hade 18 px per sida
  // och en content-box på 8 px. Gör någon monogrammet statiskt även i det
  // lilla läget kollapsar kortet - och den fällan gillrar man inte om igen.
  const pad = paddingVid();
  for (const [namn, bredd] of KONTEXTER) {
    const inner = innerBredd(bredd, pad);
    assert.ok(inner >= 0.6 * bredd,
      `${namn}: paddingen lämnar ${inner.toFixed(1)} px av ${bredd} px åt innehållet`);
  }
});

test("det stora läget: container-frågan byter kort, inte skärmen", () => {
  // En mediefråga kan inte skilja dem åt: samma kort ligger i en
  // 44-pixelsrad och i en 350-pixelshjälte på SAMMA skärm. Att frågan finns
  // och VAR den går mäts av de tre testerna ovan - containerTröskel() failar
  // om frågan försvinner. Här mäts vad den byter.
  containerTröskel();

  const namn = regelFör(".reservkort-namn", { container: "min-width" });
  assert.ok(namn.get("display") && namn.get("display") !== "none",
    "namnet syns aldrig - då bär kortet ingen typografi");
  assert.match(namn.get("font") || "", /var\(--f-disp\)/, "namnet sätts inte i Newsreader");
  const kap = regelFör(".reservkort-kap", { container: "min-width" });
  assert.match(kap.get("letter-spacing") || "", /0?\.2em/, "kapitälerna är inte spärrade");
  assert.equal(kap.get("text-transform"), "uppercase");
  assert.equal(regelFör(".reservkort-monogram", { container: "min-width" }).get("display"), "none",
    "monogrammet står kvar bakom namnet i det stora läget");
});

test("kortets text klarar AA mot sin egen yta, i ljust och mörkt", () => {
  const yta = regelFör(".reservkort").get("background");
  const delar = [
    [".reservkort-kap", regelFör(".reservkort-kap", { container: "min-width" }).get("color")],
    [".reservkort-namn", regelFör(".reservkort-namn", { container: "min-width" }).get("color")],
    [".reservkort-monogram", regelFör(".reservkort-monogram").get("color")],
  ];
  for (const [väljare, färg] of delar) {
    assert.ok(färg, `${väljare} saknar färg`);
    for (const [läge, vars] of Object.entries(TEMAN)) {
      const ratio = kontrast(
        tolkaFärg(lösVar(färg, vars).trim()), tolkaFärg(lösVar(yta, vars).trim()));
      assert.ok(ratio >= 4.5,
        `${väljare} i ${läge} läge: ${ratio.toFixed(2)}:1, krävs 4,5:1`);
    }
  }
});

test("kortet bär ingen accentfärg - att sakna ett foto är inget nuläge (§2.3)", () => {
  for (const väljare of [".reservkort", ".recipe-fallback.reservkort", ".reservkort-kap",
                         ".reservkort-namn", ".reservkort-monogram", ".reservkort-linje"]) {
    for (const container of [null, "min-width"]) {
      for (const [prop, värde] of regelFör(väljare, { container })) {
        assert.ok(!/--accent/.test(värde),
          `${väljare} { ${prop}: ${värde} } använder accenten`);
      }
    }
  }
});

test("den gamla ikonfallbacken är borta ur stilmallen", () => {
  // .kind-* var sex toningar i den gamla gröna paletten, hårdkodade i hex.
  assert.ok(!/\.recipe-fallback\.kind-/.test(css), "kind-toningarna finns kvar");
  assert.ok(!/\.recipe-fallback\s+svg\{/.test(css), "ikonregeln finns kvar men ingen ikon ritas");
});

// ---------------------------------------------------------------------------
// LAGER 3 · VÄGARNA - varje skärm går genom komponenten
// ---------------------------------------------------------------------------

const app = läsFil("frontend/app/app.js");
const receptvy = läsFil("frontend/app/src/views/recipes.js");

test("Ikväll, Veckan och receptvyn ritar sin bildyta med komponenten", () => {
  const vägar = [
    ["Ikväll", app, /class="hero-meal-photo">\$\{recipePhoto\(recipe, \{ namn: false \}\)\}/],
    ["Veckan, raden", app, /class="week-plan-photo">\$\{recipePhoto\(/],
    ["Veckan, dagens kort", app, /class="week-today-photo">\$\{recipePhoto\(/],
    // L4:s uppslag lägger rubriken PÅ bilden i ett pappersfält, precis som
    // Ikväll gör - alltså samma `namn: false` där.
    ["receptvyn, hjälten", receptvy, /heroMedia = receptbildMarkup\(recipe, \{[^}]*namn: false/],
    ["receptvyn, listan", receptvy, /recipePhoto\(recipe\)/],
  ];
  for (const [namn, källa, mönster] of vägar) {
    assert.match(källa, mönster, `${namn} ritar inte sin bildyta genom komponenten`);
  }
});

test("ingen vy skriver sin egen receptbild", () => {
  // En egen <img class="recipe-photo"> utanför komponenten är ett hål som
  // öppnar sig igen så fort receptet saknar foto.
  for (const fil of ["frontend/app/app.js", ...readdirSync("frontend/app/src/views")
    .filter(f => f.endsWith(".js") && f !== "receptbild.js")
    .map(f => `frontend/app/src/views/${f}`)]) {
    const källa = readFileSync(fil, "utf8");
    for (const träff of källa.matchAll(/<img[^>]*class="[^"]*\brecipe-photo\b/g)) {
      assert.fail(`${fil} skriver en egen receptbild: ${träff[0]}`);
    }
  }
});

// ---------------------------------------------------------------------------
// PROVENANSEN - ett foto utan licens läggs inte in
// ---------------------------------------------------------------------------

function receptbanken() {
  const alla = [];
  for (const fil of readdirSync("backend/recipe_sources").filter(f => f.endsWith(".json"))) {
    alla.push(...JSON.parse(readFileSync(`backend/recipe_sources/${fil}`, "utf8")));
  }
  return alla;
}

test("varje recept med en bild har en ifylld licens, källa och upphovsperson", () => {
  const banken = receptbanken();
  assert.ok(banken.length > 200, "receptbanken är tom - testet mäter ingenting");
  const medBild = banken.filter(r => r.image);
  assert.ok(medBild.length > 200, "nästan inga recept har bild - något har gått sönder");
  for (const recept of medBild) {
    for (const fält of ["imageLicense", "imageSourceUrl", "imageCredit"]) {
      assert.ok(String(recept[fält] || "").trim(),
        `${recept.id} har en bild men saknar ${fält}. Repot är publikt: en bild ` +
        "utan proveniens är en juridisk skuld, inte en bild.");
    }
    assert.equal(recept.imageStatus, "ok");
  }
});

test("varje eget receptfoto ligger i bygget och är krediterat", () => {
  const credits = readFileSync("frontend/app/assets/recipes/CREDITS.md", "utf8");
  const egna = receptbanken().filter(r => String(r.image || "").startsWith("assets/"));
  assert.ok(egna.length > 0, "inget recept pekar på ett eget foto - testet mäter ingenting");
  for (const recept of egna) {
    const fil = `frontend/app/${recept.image}`;
    assert.ok(existsSync(fil), `${recept.id} pekar på ${recept.image} som inte finns i bygget`);
    assert.ok(credits.includes(recept.image.split("/").pop()),
      `${recept.image} saknar rad i assets/recipes/CREDITS.md`);
  }
});

test("varje fil i CREDITS.md står EN gång", () => {
  // Byts en bild ut mot en bättre måste den gamla raden bort. Två rader för
  // samma fil betyder att en av dem krediterar fel fotograf - och det är
  // sämre än ingen kreditering alls.
  const rader = readFileSync("frontend/app/assets/recipes/CREDITS.md", "utf8")
    .split("\n").filter(rad => /^\|\s+\S+\.jpe?g\s+\|/.test(rad));
  assert.ok(rader.length > 50, "CREDITS.md är tom - testet mäter ingenting");
  const filer = rader.map(rad => rad.split("|")[1].trim());
  const dubbletter = filer.filter((fil, i) => filer.indexOf(fil) !== i);
  assert.deepEqual([...new Set(dubbletter)], [], "samma fil krediteras två gånger");
});

test("reservkortet prövas mot recept som verkligen saknar foto", () => {
  // Om banken en dag har foton överallt är det här testet meningslöst, inte
  // grönt: då ska någon ta bort det, inte låta det stå och intyga ingenting.
  const utan = receptbanken().filter(r => !r.image);
  assert.ok(utan.length > 0,
    "alla recept har foto - flytta reservkortets bevis till en påhittad rätt " +
    "eller ta bort det här testet. Ett test utan indata är en åsikt.");
  for (const recept of utan) {
    const markup = receptbildMarkup({ namn: recept.name, typ: (recept.categories || []).join(" ") });
    assert.ok(!markup.includes("<img"), `${recept.name} renderade en <img> utan bild`);
    assert.ok(text(markup).includes(recept.name), `${recept.name} saknas på sitt eget kort`);
  }
});
