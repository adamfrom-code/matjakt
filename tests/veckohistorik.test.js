// H3:s acceptanskriterium: de tolv veckorna i `state.weekHistory` syns.
//
// Fältet har funnits sedan app-state.js skrevs och lästes på fyra ställen -
// "Återställ förra veckan", bytesförslagens straff för nyss ätna rätter,
// kostnadsvarningen och synken. Ingen av dem VISAR den. Det som fanns var
// alltså innehållet; det som saknades var skärmen.
//
// Provet nedan är därför lika mycket ett prov på att datan tas på allvar som
// på att markupen blir rätt: en vecka utan total ska få sin rad ändå, en rätt
// som lämnat banken ska inte radera veckan den åts i, och talet ska ritas av
// L0 och inte av den här vyn.

import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import { SAKNAS, UPPSKATTAT, prisMarkup } from "../frontend/app/src/views/pris.js";
import {
  VECKOR_I_HISTORIKEN, datumEtikett, initVeckohistorik, renderVeckohistorik,
  snittPerVecka, säsongen, veckohistorikMarkup, veckohistorikModell, veckoradMarkup,
} from "../frontend/app/src/views/veckohistorik.js";

const BANK = {
  "korv-stroganoff": "Korv Stroganoff",
  "fisk-gratang": "Fiskgratäng",
  "linsgryta": "Linsgryta med spiskummin",
};

function rigga() {
  initVeckohistorik({ namnFör: id => BANK[id] || null });
}

const vecka = (extra = {}) => ({
  plan: ["korv-stroganoff", "fisk-gratang"],
  savedAt: Date.UTC(2026, 8, 8, 10, 0, 0),
  total: 612,
  ...extra,
});

// ---------------------------------------------------------------------------
// 1. VECKORNA SYNS - OCH DE SYNS ALLA
// ---------------------------------------------------------------------------

test("varje sparad vecka blir en rad", () => {
  rigga();
  const modell = veckohistorikModell([vecka(), vecka({ total: 540 }), vecka({ total: null })]);
  assert.equal(modell.veckor.length, 3);
  assert.equal(modell.tom, false);
  const html = veckohistorikMarkup(modell);
  assert.equal((html.match(/class="vh-vecka"/g) || []).length, 3,
    "alla tre veckorna ritas inte");
});

test("historiken går inte längre bakåt än de tolv som sparas", () => {
  rigga();
  // app-state.js kapar redan listan till tolv. Vyn får inte vara den som
  // tyst börjar visa fler den dag någon höjer taket i state utan att titta
  // på skärmen - eller färre.
  const många = Array.from({ length: 20 }, (_, i) => vecka({ total: 500 + i }));
  assert.equal(veckohistorikModell(många).veckor.length, VECKOR_I_HISTORIKEN);
});

test("en vecka som aldrig prissattes får sin rad ändå", () => {
  rigga();
  // `total: null` skrivs med flit av app-state.js när veckan aldrig hann
  // prissättas. Att hoppa över raden hade gjort historiken glesare än
  // verkligheten - och fått snittet att se ut att gälla fler veckor än det gör.
  const modell = veckohistorikModell([vecka({ total: null })]);
  assert.equal(modell.veckor.length, 1);
  assert.equal(modell.veckor[0].kronor, null);
  assert.equal(modell.veckor[0].tillstånd, SAKNAS);
  assert.match(veckoradMarkup(modell.veckor[0]), /Korv Stroganoff/,
    "veckan utan pris tappade också sina rätter");
});

test("en rätt som lämnat banken raderar inte veckan den åts i", () => {
  rigga();
  const modell = veckohistorikModell([vecka({ plan: ["korv-stroganoff", "borttagen-ratt"] })]);
  const rad = modell.veckor[0];
  // Middagen räknas - den åts - men namnet finns inte att skriva ut.
  assert.equal(rad.dagar, 2);
  assert.deepEqual(rad.rätter, ["Korv Stroganoff"]);
});

test("en vecka vars alla rätter är borta säger det, i stället för att visa en tom rad", () => {
  rigga();
  const modell = veckohistorikModell([vecka({ plan: ["vad-som-helst"] })]);
  assert.match(veckoradMarkup(modell.veckor[0]), /Rätterna finns inte kvar i banken/);
});

// ---------------------------------------------------------------------------
// 2. TALET ÄR L0:s, INTE VYNS
// ---------------------------------------------------------------------------

test("veckans total ritas av prisMarkup, tecken för tecken", () => {
  rigga();
  const modell = veckohistorikModell([vecka({ total: 612 }), vecka({ total: null })]);
  const [medPris, utanPris] = modell.veckor.map(veckoradMarkup);
  assert.ok(medPris.includes(prisMarkup(612, UPPSKATTAT)),
    "raden skrev en EGEN prismarkup i stället för L0:s komponent");
  assert.ok(utanPris.includes(prisMarkup(null, SAKNAS)),
    "den oprissatta veckan fick inte L0:s tomma fack");
  // ...och de två är faktiskt olika. Utan det här kunde båda vara "pris
  // saknas" och proven ovan ändå passera.
  assert.notEqual(prisMarkup(612, UPPSKATTAT), prisMarkup(null, SAKNAS));
});

test("modulen bygger ingen prismarkup av eget märke", () => {
  const källa = readFileSync(new URL("../frontend/app/src/views/veckohistorik.js", import.meta.url), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "").split("\n").filter(rad => !/^\s*\/\//.test(rad)).join("\n");
  // Klasserna ÄGS av pris.js. Står någon av dem i en mallsträng här har vyn
  // börjat bygga en egen kopia av komponenten.
  for (const klass of ["pris--ca", "pris--golv", "cirka", "minst", '"saknas"']) {
    assert.ok(!källa.includes(klass),
      `src/views/veckohistorik.js bygger egen prismarkup: ${klass} hör hemma i pris.js`);
  }
});

test("snittet räknas bara på de veckor som har ett tal", () => {
  rigga();
  // Att räkna en oprissatt vecka som noll hade dragit ner snittet med en
  // vecka som aldrig kostade noll - den kostade något vi inte vet.
  const modell = veckohistorikModell([vecka({ total: 600 }), vecka({ total: null }), vecka({ total: 400 })]);
  assert.equal(snittPerVecka(modell), 500);
  assert.equal(snittPerVecka(veckohistorikModell([vecka({ total: null })])), null);
  assert.ok(!veckohistorikMarkup(veckohistorikModell([vecka({ total: null })])).includes("I snitt"),
    "snittraden skrivs ut utan ett enda tal att grunda den på");
});

// ---------------------------------------------------------------------------
// 3. RUBRIKEN OCH DET TOMMA TILLSTÅNDET
// ---------------------------------------------------------------------------

test("rubriken säger vilken årstid det är nu, inte vilken det var", () => {
  rigga();
  const i = (månad) => veckohistorikModell([], { now: new Date(2026, månad, 15) }).rubrik;
  assert.equal(i(8), "Så här har ni ätit i hösten");     // september
  assert.equal(i(0), "Så här har ni ätit i vintern");    // januari
  assert.equal(i(3), "Så här har ni ätit i våren");      // april
  assert.equal(i(6), "Så här har ni ätit i sommaren");   // juli
  assert.equal(säsongen(new Date(2026, 11, 1)), "vintern");
});

test("en tom historik är en mening, inte en tom lista", () => {
  rigga();
  // §5.10: ingen streckad ruta, ingen ikon, ingen centrerad text - en mening
  // i kursiv Newsreader. Och ingen knapp: veckan sparas av sig själv, det
  // finns inget att trycka på.
  for (const ingen of [[], null, undefined]) {
    const modell = veckohistorikModell(ingen);
    assert.equal(modell.tom, true, `${ingen} gav inte ett tomt tillstånd`);
    const html = veckohistorikMarkup(modell);
    assert.match(html, /class="vh-tomt"/);
    assert.match(html, /Ingen vecka bakåt än/);
    assert.ok(!html.includes("<button"), "det tomma tillståndet fick en knapp");
    assert.ok(!html.includes("vh-vecka"), "det tomma tillståndet ritade ändå en rad");
  }
});

test("datumet skrivs kort, och ett trasigt datum blir tomt i stället för NaN", () => {
  assert.equal(datumEtikett(Date.UTC(2026, 8, 8, 10)), "8 sep");
  assert.equal(datumEtikett(undefined), "");
  assert.equal(datumEtikett("inte ett datum"), "");
});

// ---------------------------------------------------------------------------
// 4. SKÄRMEN: BLOCKET FINNS, OCH DET RITAS
// ---------------------------------------------------------------------------

test("Sparat har behållaren, under nyckeltalen", () => {
  const html = readFileSync(new URL("../frontend/app/index.html", import.meta.url), "utf8");
  const start = html.indexOf('<section class="screen stats-screen');
  const slut = html.indexOf('<section class="screen', start + 1);
  const sparat = html.slice(start, slut === -1 ? html.length : slut);
  assert.notEqual(start, -1, "Sparat-skärmen hittades inte");
  const block = sparat.indexOf('id="veckohistorik"');
  assert.notEqual(block, -1, "behållaren för veckohistoriken saknas på Sparat");
  assert.ok(block > sparat.indexOf('id="sparatTal"'),
    "historiken står ovanför nyckeltalen - den är det man läser sist, inte först");
});

test("app.js ritar historiken när Sparat ritas", () => {
  const app = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
  assert.match(app, /renderVeckohistorik\(veckohistorikModell\(state\.weekHistory\)\)/,
    "renderStats ritar inte veckohistoriken");
  assert.match(app, /initVeckohistorik\(/,
    "modulen får aldrig veta hur den slår upp ett receptnamn");
});

test("renderVeckohistorik skriver i behållaren, och bara i den", () => {
  const box = { innerHTML: "" };
  initVeckohistorik({ $: (id) => (id === "veckohistorik" ? box : null), namnFör: id => BANK[id] || null });
  renderVeckohistorik(veckohistorikModell([vecka()]));
  assert.match(box.innerHTML, /vh-vecka/);
  assert.match(box.innerHTML, /Korv Stroganoff/);
});
