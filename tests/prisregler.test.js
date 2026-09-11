// L0:s acceptanskriterium: de tre prisreglerna, och beviset att de överlever
// utan färg.
//
// Kriteriet är ovanligt formulerat och det är med flit. "Rendera de tre
// tillstånden och kräv att de skiljer sig" är lätt att uppfylla på fel sätt -
// tre klasser med var sin `color` passerar. Men ett pris läses i
// butiksbelysning, på en telefon med nedskruvad ljusstyrka, av en användare
// som i ungefär vart tolfte fall är rödgrönt färgblind, och ibland på ett
// papper. Färg är det första som försvinner. Form är det sista.
//
// Testet kör därför markupen genom två filter och kräver att de tre
// tillstånden är åtskilda efter BÅDA:
//
//   gråskala   varje färg blir sin relativa luminans - vad en akromatopsisk
//              användare ser.
//   utan färg  all färginformation bort, ton OCH ljushet. Kvar står bara
//              formen: hel siffra, streckad siffra, tom ram.
//
// Det andra filtret är det som har tänder, och för att det ska gå att lita på
// prövas det på två FUSK som är byggda för att smita förbi: tre lappar som
// skiljer sig bara i ton, och tre som skiljer sig bara i ljushet. Ett test
// som inte kan visa hur det failar är bara en åsikt med semikolon.

import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import test from "node:test";

import { läsFil, läsStyles, parseRegler, rotVariabler } from "./fixtures/css-parser.mjs";
import { kontrast, luminans, tolkaFärg } from "./fixtures/kontrast.mjs";
import {
  avtryck, färg, färgerI, gråskala, okändaSelektorer, rita, synligt,
  träffadeRegler, utanFärg,
} from "./fixtures/prisrender.mjs";
import {
  KONTROLLERAT, SAKNAS, TILLSTÅND, UPPSKATTAT,
  prisMarkup, prisTillstånd, summaTillstånd, teckenförklaringMarkup,
} from "../frontend/app/src/views/pris.js";

const css = läsStyles();
const regler = parseRegler(css);
const TEMAN = { ljust: rotVariabler(regler), mörkt: rotVariabler(regler, '[data-theme="dark"]') };

// De tre tillstånden, renderade ur komponenten. SAMMA belopp i de två som
// visar ett tal - det är avgörande. Med olika siffror skiljer sig lapparna
// redan i text, och då kan testet inte se om FORMEN skiljer dem: ett
// kontrollerat "38,50 kr" och ett uppskattat "41 kr" är olika oavsett hur
// mycket utsmyckning man river bort.
const LAPPAR = {
  kontrollerat: prisMarkup("38,50 kr", KONTROLLERAT),
  uppskattat: prisMarkup("38,50 kr", UPPSKATTAT),
  saknas: prisMarkup(null, SAKNAS),
};
const NAMN = Object.keys(LAPPAR);
const PAR = [["kontrollerat", "uppskattat"], ["kontrollerat", "saknas"], ["uppskattat", "saknas"]];

const ritaAlla = (lappar, stilmall = css, tema = "ljust") =>
  Object.fromEntries(Object.entries(lappar).map(([namn, html]) =>
    [namn, rita(html, stilmall, TEMAN[tema])]));

/** Vilka par som INTE går att skilja åt efter ett filter. */
function oskiljbara(ritade, filter) {
  const par = [];
  for (const [a, b] of PAR) {
    if (avtryck(filter(ritade[a])) === avtryck(filter(ritade[b]))) par.push(`${a}/${b}`);
  }
  return par;
}

// ---------------------------------------------------------------------------
// 1. Komponenten
// ---------------------------------------------------------------------------

test("de tre tillstånden får sin form ur §6, inte ur var sin vy", () => {
  // Hel siffra, ingen dekoration. Det som inte är markerat är det du kan
  // lita på - och den regeln gäller markupen lika mycket som skärmen.
  assert.equal(LAPPAR.kontrollerat, '<span class="pris">38,50 kr</span>');
  // Ett tal formateras som money() i app.js gör det, på ett ställe, så två
  // vyer inte kan avrunda samma belopp olika.
  assert.equal(prisMarkup(38.5, KONTROLLERAT), '<span class="pris">39 kr</span>');

  // "ca" i kapitäler före talet plus streckad understrykning. Strecket
  // sitter på .tal och inte på hela lappen, så det ligger under SIFFRAN.
  assert.match(LAPPAR.uppskattat, /class="pris pris--ca"/);
  assert.match(LAPPAR.uppskattat, /<span class="cirka">ca<\/span><span class="tal">38,50 kr<\/span>/);

  // Öppen ram med tankstreck. Tankstrecket kommer ur .saknas::before så att
  // texten i DOM:en är hela meningen skärmläsaren läser upp.
  assert.equal(LAPPAR.saknas, '<span class="pris"><span class="saknas">pris saknas</span></span>');
  assert.match(css, /\.saknas::before\{content:"—"/);

  // Kapitälerna skrivs som vanlig text och versaliseras i CSS (§8): versaler
  // i källan får skärmläsaren att stava dem bokstav för bokstav, "C-A".
  assert.doesNotMatch(LAPPAR.uppskattat, />CA</);
  assert.doesNotMatch(LAPPAR.saknas, />PRIS SAKNAS</);
});

test("komponenten skriver aldrig ut ett tal den inte har", () => {
  // Den enda vägen till ett tomt fack får inte vara att anroparen kommer
  // ihåg att byta tillstånd. Saknas talet är svaret "pris saknas", oavsett
  // vad vyn bad om - annars står det "NaN kr" eller "undefined kr" i en
  // kolumn av fakta.
  for (const tomt of [null, undefined, NaN, Infinity, "", "   "]) {
    assert.equal(prisMarkup(tomt, KONTROLLERAT), LAPPAR.saknas, `${String(tomt)} blev inte "pris saknas"`);
    assert.equal(prisMarkup(tomt, UPPSKATTAT), LAPPAR.saknas, `${String(tomt)} blev inte "pris saknas"`);
  }
  // Ett okänt tillstånd är inte ett fjärde tillstånd - det är ett okänt, och
  // ett okänt pris visas som okänt.
  assert.equal(prisMarkup(41, "kampanj"), LAPPAR.saknas);
  assert.deepEqual(TILLSTÅND, [KONTROLLERAT, UPPSKATTAT, SAKNAS]);
});

test("golvet är en modifierare, inte ett fjärde tillstånd (C7)", () => {
  // "Den här SUMMAN är minst X" var det begrepp som saknades när tre
  // msk-rader gjorde sextio kronor osynliga. Golvet säger något om summan,
  // tillståndet något om talets säkerhet - de är ortogonala.
  const golv = prisMarkup(612, KONTROLLERAT, { golv: true });
  assert.match(golv, /class="pris pris--golv"/);
  assert.match(golv, /<span class="minst">minst<\/span><span class="tal">612 kr<\/span>/);
  // Ett golv för ett tal som inte finns är ingenting.
  assert.equal(prisMarkup(null, KONTROLLERAT, { golv: true }), LAPPAR.saknas);
  // Golv och uppskattat kan gälla samtidigt, och då sägs båda.
  const båda = prisMarkup(612, UPPSKATTAT, { golv: true });
  assert.match(båda, /class="pris pris--ca pris--golv"/);
  assert.match(båda, /minst<\/span><span class="cirka">ca<\/span>/);
});

// ---------------------------------------------------------------------------
// 2. Acceptansen: skillnaden överlever gråskala, och överlever ingen färg alls
// ---------------------------------------------------------------------------

test("de tre tillstånden går att skilja åt i gråskala", () => {
  for (const tema of Object.keys(TEMAN)) {
    const ritade = ritaAlla(LAPPAR, css, tema);
    assert.deepEqual(oskiljbara(ritade, gråskala), [],
      `i ${tema} läge blev pristillstånd identiska när färgen gjordes om till gråskala`);
  }
});

test("de går att skilja åt även utan någon färginformation alls", () => {
  // Det hårda provet, och det som gör kriteriet värt att skriva: gråskala
  // behåller LJUSHET, så två gråtoner räcker för att passera det. Här tas
  // också ljusheten bort. Klarar de tre tillstånden det bärs skillnaden av
  // form - streckad linje, tom ram, kapitälmarkör - och ingenting annat.
  for (const tema of Object.keys(TEMAN)) {
    const ritade = ritaAlla(LAPPAR, css, tema);
    assert.deepEqual(oskiljbara(ritade, utanFärg), [],
      `i ${tema} läge fanns skillnaden mellan pristillstånden bara i färg`);
  }

  // Och skillnaden får inte vara osynlig. .sr-only-texten (", uppskattat
  // pris") finns för skärmläsaren och räknas inte som synlig skillnad; det
  // som blir kvar efter synligt() måste ändå skilja sig.
  const synliga = ritaAlla(LAPPAR);
  for (const namn of NAMN) {
    assert.ok(synligt(synliga[namn]).length > 0, `${namn} renderar ingenting synligt`);
  }
  assert.ok(JSON.stringify(synligt(ritaAlla(LAPPAR).uppskattat)).includes("dashed"),
    "det uppskattade prisets streckade understrykning är borta - då är 'ca' ensamt kvar");
  assert.ok(JSON.stringify(synligt(ritaAlla(LAPPAR).saknas)).includes("solid"),
    "ramen runt 'pris saknas' är borta - ett tomt fack utan fack är ingen form");
});

test("filtren har tänder: två fusk som är byggda för att smita förbi", () => {
  // FUSK 1 - skillnad bara i TON. Tre lappar med samma text och samma form,
  // färgade i tre kulörer med exakt samma relativa luminans. Ett öga som
  // inte ser färg ser tre identiska lappar. Gråskalefiltret ska säga det.
  const sammaLjushet = (hex) => {
    const L = luminans(tolkaFärg(hex));
    const s = L <= 0.0031308 ? L * 12.92 : 1.055 * L ** (1 / 2.4) - 0.055;
    const v = (s * 255).toFixed(4);
    return `rgb(${v},${v},${v})`;
  };
  const tonCss = ".fusk{font-size:14px}"
    + ".fusk--a{color:#ff0000}"
    + `.fusk--b{color:${sammaLjushet("#ff0000")}}`
    + ".fusk--c{color:#ff0000}";
  const ton = {
    kontrollerat: '<span class="fusk fusk--a">38,50 kr</span>',
    uppskattat: '<span class="fusk fusk--b">38,50 kr</span>',
    saknas: '<span class="fusk fusk--c">38,50 kr</span>',
  };
  const ritadTon = ritaAlla(ton, tonCss);
  assert.deepEqual(oskiljbara(ritadTon, gråskala).sort(),
    ["kontrollerat/saknas", "kontrollerat/uppskattat", "uppskattat/saknas"],
    "gråskalefiltret ser inte att tre kulörer med samma luminans är samma grå");

  // FUSK 2 - skillnad bara i LJUSHET. Tre gråtoner. Det här SLIPPER igenom
  // gråskalefiltret, för gråskala bevarar ljushet, och det är precis därför
  // kriteriet kräver mer än gråskala: skillnaden finns fortfarande bara i
  // färg, och försvinner i en svartvit utskrift eller vid nedskruvad
  // ljusstyrka. Det andra filtret ska fälla den.
  const ljusCss = ".fusk{font-size:14px}.fusk--a{color:#16191b}.fusk--b{color:#5a6367}.fusk--c{color:#626b6f}";
  const ljus = {
    kontrollerat: '<span class="fusk fusk--a">38,50 kr</span>',
    uppskattat: '<span class="fusk fusk--b">38,50 kr</span>',
    saknas: '<span class="fusk fusk--c">38,50 kr</span>',
  };
  const ritadLjus = ritaAlla(ljus, ljusCss);
  assert.deepEqual(oskiljbara(ritadLjus, gråskala), [],
    "gråskala ensamt skulle godkänna tre lappar som bara skiljer sig i gråton - kriteriet vore tandlöst");
  assert.deepEqual(oskiljbara(ritadLjus, utanFärg).sort(),
    ["kontrollerat/saknas", "kontrollerat/uppskattat", "uppskattat/saknas"],
    "färgfiltret släppte igenom tre lappar vars enda skillnad var färg");

  // FUSK 3 - skillnad bara för skärmläsaren. En osynlig .sr-only-text är
  // ingen visuell skillnad, och får inte kunna rädda ett tillstånd.
  const dolt = {
    kontrollerat: '<span class="fusk">38,50 kr</span>',
    uppskattat: '<span class="fusk">38,50 kr<span class="sr-only">, uppskattat</span></span>',
    saknas: '<span class="fusk">38,50 kr<span class="sr-only">, saknas</span></span>',
  };
  assert.deepEqual(oskiljbara(ritaAlla(dolt, css), utanFärg).sort(),
    ["kontrollerat/saknas", "kontrollerat/uppskattat", "uppskattat/saknas"],
    "en skillnad som bara skärmläsaren hör räknades som synlig form");
});

// ---------------------------------------------------------------------------
// 3. Aldrig rött
// ---------------------------------------------------------------------------

// Rött i prismarkupen är förbjudet av fyra skäl (§6), och det tyngsta är att
// systemets enda accent ÄR ett mörkt rött: en röd prislapp läses som
// accentuerad, alltså "här är du, här går vägen vidare" - raka motsatsen till
// "vi vet inte". Därför fälls accenten här också, inte bara larmfärger.
const ärRöd = (f) => f && f[3] > 0 && f[0] > f[1] && f[0] > f[2] && f[0] - Math.max(f[1], f[2]) >= 24;
const FÖRBJUDNA_NAMN = /--(red|danger|error|warning|alert|gold)\b|\b(red|crimson|firebrick|maroon|darkred|indianred|tomato|orangered|salmon)\b/i;

test("ingen röd färg, och ingen accent, någonstans i prismarkupen", () => {
  const markup = [...Object.values(LAPPAR), prisMarkup(612, UPPSKATTAT, { golv: true }), teckenförklaringMarkup()].join("");
  const fynd = [];

  for (const regel of träffadeRegler(markup, css)) {
    if (FÖRBJUDNA_NAMN.test(regel.block)) fynd.push(`styles.css:${regel.rad} ${regel.selektor} - förbjudet färgnamn`);
    if (/var\(\s*--accent/.test(regel.block)) fynd.push(`styles.css:${regel.rad} ${regel.selektor} - accenten får inte bära pris (§2.3)`);
    for (const tema of Object.keys(TEMAN)) {
      for (const { text, f } of färgerI(regel.block.replace(/var\(\s*(--[\w-]+)[^)]*\)/g,
        (_, namn) => TEMAN[tema].get(namn) ?? ""))) {
        if (ärRöd(f)) fynd.push(`styles.css:${regel.rad} ${regel.selektor} - ${text} är röd i ${tema} läge`);
      }
    }
  }

  // Kommentarerna räknas bort: en prosarad som NÄMNER accentens hexvärde
  // målar ingenting. Allt som är kod granskas.
  const modul = läsFil("frontend/app/src/views/pris.js")
    .replace(/\/\*[\s\S]*?\*\//g, "").split("\n").filter((rad) => !/^\s*\/\//.test(rad)).join("\n");
  if (FÖRBJUDNA_NAMN.test(modul)) fynd.push("src/views/pris.js - förbjudet färgnamn i modulen");
  for (const { text, f } of färgerI(modul)) if (ärRöd(f)) fynd.push(`src/views/pris.js - ${text} är röd`);

  assert.deepEqual(fynd, [],
    "ett saknat pris är ingen varning, det är ett tomt fack:\n" + fynd.join("\n"));
});

test("motorn granskas på det den faktiskt matchar, inte på en gissning", () => {
  // Renderingsmotorn förstår bara klass- och taggselektorer med
  // efterföljandekombinator. En prisregel skriven i en form den inte kan läsa
  // skulle tyst hoppas över - och då vore både gråskaleprovet och
  // färggranskningen ovan påståenden utan täckning.
  const klasser = ["pris", "pris--ca", "pris--golv", "cirka", "tal", "minst", "saknas",
    "prisnyckel", "prick", "streck", "fyrkant"];
  assert.deepEqual(okändaSelektorer(css, klasser), [],
    "en prisregel står i en selektorform testet inte kan läsa - då granskas den inte");
});

// ---------------------------------------------------------------------------
// 4. §2.4 - minst 3:1 mellan lägena, mätt på det som faktiskt skiljer dem
// ---------------------------------------------------------------------------

test("varje form som skiljer tillstånden åt når 3:1 mot ytan den ligger på", () => {
  // Kontrasttestet från G4 mäter text mot bakgrund och kan aldrig se att två
  // lägen ser likadana ut - det var därför stjärnbetyget kunde gå sönder
  // tyst. Regeln i §2.4 är därför: minst 3:1 mellan lägena, mätt på DET SOM
  // SKILJER DEM. Här är det strecket under siffran och ramen runt det tomma
  // facket: grafiska objekt som bär information, alltså WCAG 1.4.11.
  //
  // Måttet tas mot båda ytor en prislapp kan hamna på - papperet och det
  // nedsänkta fältet i summeringsblocket - i båda lägena.
  const LINJE = /^(background|background-color|border|border-(top|right|bottom|left)|border-color|outline|text-decoration-color)$/;
  // Kravet gäller de element som BÄR en form, inte de lådor som råkar
  // innehålla dem: en hårlinje i --rule ovanför teckenförklaringen är en
  // avdelare och bär ingen betydelse, och 1,33:1 är rätt för den (§2.1).
  // Ritas däremot strecket under siffran eller ramen runt det tomma facket i
  // en avdelarton faller det här testet - det är hela RÄTTELSE 2.
  const FORMBÄRARE = ["pris", "tal", "cirka", "minst", "saknas", "prick", "streck", "fyrkant"];
  const markup = [...Object.values(LAPPAR), teckenförklaringMarkup()].join("");
  const brister = [];

  for (const tema of Object.keys(TEMAN)) {
    const vars = TEMAN[tema];
    const ytor = ["--paper", "--paper-2"].map((namn) => [namn, tolkaFärg(vars.get(namn))]);
    for (const post of rita(markup, css, vars)) {
      if (post.dolt || !post.klasser.some((k) => FORMBÄRARE.includes(k))) continue;
      for (const [prop, värde] of Object.entries(post.stil)) {
        if (!LINJE.test(prop)) continue;
        for (const { text, f } of färgerI(värde)) {
          for (const [ytnamn, yta] of ytor) {
            const r = kontrast(f, yta);
            if (r < 3) {
              brister.push(`${tema}: ${post.väg} { ${prop}: ${text} } ger ${r.toFixed(2)}:1 mot ${ytnamn}`);
            }
          }
        }
      }
    }
  }
  assert.deepEqual(brister, [],
    "en betydelsebärande linje under 3:1 är en form som inte syns:\n" + brister.join("\n"));
});

test("de tre formerna är tre olika former, inte tre nyanser av samma", () => {
  // Formen är det som bär tillståndet. Hel linje, streckad linje, tom ram -
  // och de måste skilja sig i något annat än tjocklek eller ton, annars är
  // teckenförklaringen en förklaring av ingenting.
  const glyfer = rita(teckenförklaringMarkup(), css, TEMAN.ljust)
    .filter((p) => ["prick", "streck", "fyrkant"].some((k) => p.klasser.includes(k)));
  assert.equal(glyfer.length, 3, "teckenförklaringen ritar inte tre glyfer");
  const former = glyfer.map((g) => JSON.stringify(utanFärg([g])[0].stil));
  assert.equal(new Set(former).size, 3, "två av teckenförklaringens glyfer har samma form utan färg");
});

// ---------------------------------------------------------------------------
// 5. Tillståndet kommer ur motorn
// ---------------------------------------------------------------------------

test("motorns begrepp mappas till de tre reglerna, utan en fjärde sanning", () => {
  // Butiksverifierat pris på en rad med säkert paketantal: kontrollerat.
  assert.equal(prisTillstånd({ priceStatus: "current", priceTier: "VERIFIED_STORE_PRICE", totalCost: 38.5, exactPackaging: true }), KONTROLLERAT);

  // Kedjans referenspris är ett riktigt pris, men inte verifierat i just den
  // butiken. "Vi räknar, vi vet inte" - alltså uppskattat.
  assert.equal(prisTillstånd({ priceStatus: "current", priceTier: "REFERENCE_PRICE", totalCost: 41, exactPackaging: true }), UPPSKATTAT);

  // C8: en orimlig rad blir OSÄKER i stället för dyr. Styckpriset står kvar,
  // radtotalen är ärligt okänd. Ett tomt fack är sant, 538 kr är det inte.
  assert.equal(prisTillstånd({ priceStatus: "current", unitPrice: 269, totalCost: null, rowUncertain: true, unreasonable: "row_cost" }), SAKNAS);

  // Gissat paketantal - samma mekanism, samma svar.
  assert.equal(prisTillstånd({ priceStatus: "estimated", exactPackaging: false, totalCost: null }), SAKNAS);

  // Ingen produkt matchade alls, och receptet utan prisunderlag.
  assert.equal(prisTillstånd({ priceStatus: "missing", totalCost: null }), SAKNAS);
  assert.equal(prisTillstånd({ priceStatus: "unavailable" }), SAKNAS);
  assert.equal(prisTillstånd(null), SAKNAS);

  // Och summan. pricingBasis säger vad jämförelsen vilar på; MIXED är inte
  // en kontrollerad summa, bara en delvis kontrollerad.
  assert.deepEqual(summaTillstånd({ totalCheckoutCost: 612, pricingBasis: "VERIFIED", totalIsFloor: false }),
    { tillstånd: KONTROLLERAT, golv: false });
  assert.deepEqual(summaTillstånd({ totalCheckoutCost: 612, pricingBasis: "MIXED", totalIsFloor: false }),
    { tillstånd: UPPSKATTAT, golv: false });
  assert.deepEqual(summaTillstånd({ totalCheckoutCost: 612, pricingBasis: "REFERENCE", totalIsFloor: true }),
    { tillstånd: UPPSKATTAT, golv: true });
  // C7: en total med osäkra rader är ett golv.
  assert.deepEqual(summaTillstånd({ totalCheckoutCost: 612, pricingBasis: "VERIFIED", totalIsFloor: true }),
    { tillstånd: KONTROLLERAT, golv: true });
  // Ingen rad kunde prissättas: totalen är okänd, och "0 kr" vore ett pris.
  assert.deepEqual(summaTillstånd({ totalCheckoutCost: null, pricingBasis: "VERIFIED", totalIsFloor: true }),
    { tillstånd: SAKNAS, golv: false });
});

// ---------------------------------------------------------------------------
// 6. Teckenförklaringen, och att ingen vy bygger prismarkup själv
// ---------------------------------------------------------------------------

test("teckenförklaringen står i foten på Handla och visar de tre formerna", () => {
  const nyckel = teckenförklaringMarkup();
  for (const glyf of ["prick", "streck", "fyrkant"]) {
    assert.match(nyckel, new RegExp(`class="${glyf}"`), `teckenförklaringen saknar formen ${glyf}`);
  }
  assert.match(nyckel, /ca/, "teckenförklaringen nämner inte kapitälmarkören ca");
  assert.match(nyckel, /saknas/, "teckenförklaringen nämner inte det tomma facket");

  const html = läsFil("frontend/app/index.html");
  const start = html.indexOf('class="screen shopping-screen"');
  assert.ok(start > 0, "Handla-skärmen hittades inte i index.html");
  const nästa = html.indexOf('<section class="screen ', start);
  const handla = html.slice(start, nästa === -1 ? html.length : nästa);
  assert.ok(handla.includes('id="prisnyckel"'),
    "teckenförklaringens plats finns inte på Handla");
  assert.ok(handla.indexOf('id="prisnyckel"') > handla.indexOf('id="shoppingList"'),
    "teckenförklaringen står före listan - den hör hemma i foten, under det den förklarar");

  const vy = läsFil("frontend/app/src/views/shopping.js");
  assert.match(vy, /teckenförklaringMarkup\(\)/,
    "Handla fyller inte teckenförklaringen ur komponenten");
});

test("ingen vy bygger egen prismarkup", () => {
  // Hela poängen med paketet. Sju vyagenter bygger på den här komponenten,
  // och en vy som skriver sin egen <span class="pris"> bryter regeln i just
  // den vyn utan att någon märker det - precis som trafikljuset i emoji kunde
  // leva kvar bredvid den riktiga komponenten (R41).
  const EGEN_MARKUP = /class="[^"]*\b(pris--ca|pris--golv|cirka|saknas|minst)\b|<span class="pris[ "]/;
  const fynd = [];
  const gå = (dir) => {
    for (const namn of readdirSync(dir)) {
      const sökväg = `${dir}/${namn}`;
      if (statSync(sökväg).isDirectory()) { gå(sökväg); continue; }
      if (!namn.endsWith(".js") || sökväg.endsWith("src/views/pris.js")) continue;
      if (EGEN_MARKUP.test(readFileSync(sökväg, "utf8"))) fynd.push(sökväg.split("/frontend/")[1]);
    }
  };
  gå(new URL("../frontend/app", import.meta.url).pathname);
  assert.deepEqual(fynd, [],
    "prismarkup utanför src/views/pris.js - alla vyer ska kalla prisMarkup():\n" + fynd.join("\n"));
});

test("färgmatten stämmer mot designsystemets egna tal", () => {
  // Utan det här är siffrorna ovan bara siffror. §2.2 har tabellen uträknad
  // enligt WCAG 2.1 relativ luminans och används här som facit.
  assert.ok(Math.abs(kontrast(färg("#626B6F"), färg("#ECEEEF")) - 4.68) < 0.02,
    "--ink-3 mot --paper ska ge 4,68:1 - strecket och ramen vilar på det talet");
  assert.ok(Math.abs(kontrast(färg("#B3BBBE"), färg("#ECEEEF")) - 1.68) < 0.02,
    "--rule-2 ger 1,68:1 och får därför aldrig bära betydelse (RÄTTELSE 2)");
  assert.ok(ärRöd(färg("#8A1F42")), "accenten är ett mörkt rött och ska fällas av rödspärren");
  assert.ok(ärRöd(färg("#b91c1c")), "den gamla larmfärgen ska fällas av rödspärren");
  assert.ok(!ärRöd(färg("#626B6F")) && !ärRöd(färg("#16191B")) && !ärRöd(färg("#ECEEEF")),
    "rödspärren får inte fälla systemets gråtoner");
});
