// H2:s acceptanskriterier — sparkvittot efter avbockad lista.
//
// Fyra påståenden, ett test var (plus bokföringen som håller ihop kvittot och
// Sparat-skärmen). Alla fyra är formulerade så att de kan bli RÖDA: varje
// block nedan har ett mutationsprov som återinför precis det fel regeln finns
// för att stoppa.
//
//   1. besparingen mäts mot dyraste JÄMFÖRBARA butik, och bara när servern
//      faktiskt kröner en billigaste kedja
//   2. osäkra rader gör veckans tal till ett golv, och inget tal på kortet
//      får stå naket
//   3. utan giltig jämförelse står ett besked - aldrig "0 kr"
//   4. vilar jämförelsen på riktpriser står det i texten
//
// Modulen känner DOM:en bara genom det $ som skickas in, så allt nedan körs
// utan webbläsare.

import assert from "node:assert/strict";
import test from "node:test";

import { initAppState, state } from "../frontend/app/src/state/app-state.js";
import { KONTROLLERAT, UPPSKATTAT } from "../frontend/app/src/views/pris.js";
import { sparatSedan as sparatSedanL5 } from "../frontend/app/src/views/sparat.js";
import {
  RIKTPRISTEXT, SKÄLTEXT, SKÄL_OKÄNT,
  bokförKvitto, initSparkvitto, minnsJämförelse, renderSparkvitto,
  sparatSedan, sparkvittoMarkup, sparkvittoModell, återställSparkvitto,
} from "../frontend/app/src/views/sparkvitto.js";

// ---------------------------------------------------------------------------
// Motorns former, som de faktiskt ser ut på tråden
// ---------------------------------------------------------------------------

// format_chain_result() i backend/services/grocery/api.py. Bara de fält
// kvittot läser - men med motorns namn och motorns värden, aldrig egna.
const kassa = (extra = {}) => ({
  chain: "Willys",
  totalCheckoutCost: 612,
  totalIsFloor: false,
  uncertainRows: 0,
  pricingBasis: "VERIFIED",
  coveragePercent: 100,
  comparable: true,
  ...extra,
});

// compare_chains() + _comparison_basis(), Premium-vyn.
const krönt = (extra = {}) => ({
  cheapestChain: "Willys",
  cheapestTotal: 612,
  priciestChain: "Hemköp",
  priciestTotal: 695,
  savings: 83,
  comparedChains: 2,
  reason: null,
  basis: "verified",
  ...extra,
});

const totaler = (extra = {}) => ({
  Willys: kassa(),
  Hemköp: kassa({ chain: "Hemköp", totalCheckoutCost: 695 }),
  ...extra,
});

// En sparlogg med tre veckor som bär underlag och en som inte gör det.
const logg = () => [
  { date: "2026-09-02", weekKey: "a|b", savings: 140, hasComparison: true, branch: "Willys", portionCost: 26 },
  { date: "2026-09-09", weekKey: "c|d", savings: 96, hasComparison: true, branch: "Willys", portionCost: 24 },
  { date: "2026-09-16", weekKey: "e|f", savings: 300, hasComparison: false, branch: "Hemköp", portionCost: 31 },
  { date: "2026-10-01", weekKey: "g|h", savings: 77, hasComparison: true, branch: "Hemköp", portionCost: 25 },
];

const modellen = (extra = {}) => sparkvittoModell({
  jämförelse: krönt(),
  kedjeTotaler: totaler(),
  logg: logg(),
  ...extra,
});

// Varje belopp på kortet ligger i en L0-lapp. Ett naket tal utanför en
// prislapp betyder att vyn skrivit sin egen markup - och då gäller varken
// golvet eller ca-formen för det talet.
const golvlapp = /class="pris[^"]*pris--golv/;
const calapp = /class="pris[^"]*pris--ca/;

// Klasslistan på varje prislapp i markupen. En lapp UTAN modifierare är
// komponentens sätt att säga "det här talet är kontrollerat och exakt" - det
// är precis det påstående som inte får stå på ett osäkert underlag.
const prislappar = html => [...html.matchAll(/<span class="(pris[^"]*)"/g)].map(träff => träff[1]);
const naken = klasser => !/\bpris--(ca|golv)\b/.test(klasser);

// Raderna om DEN HÄR VECKAN. Den löpande summan är ett annat påstående om
// andra veckor och bär sin egen säkerhet - att låta den ligga kvar när
// veckans former prövas gör varje sådant test tomt sant.
const veckansRader = html => html.replace(/<p class="sparkvitto-lopande">[\s\S]*?<\/p>/, "");

// ---------------------------------------------------------------------------
// 1 · Efter avbockad lista: veckans kostnad, besparingen och den löpande summan
// ---------------------------------------------------------------------------

test("kvittot säger vad veckan kostade, mot dyraste jämförbara butik, plus löpande summa", () => {
  const modell = modellen();
  assert.equal(modell.giltig, true);
  assert.equal(modell.kedja, "Willys");
  assert.equal(modell.dyrasteKedja, "Hemköp");
  assert.equal(modell.vecka.värde, 612);
  // Serverns tal, oförändrat. Kvittot räknar aldrig 695 - 612 själv: den
  // subtraktionen är compare_chains egen och får bara göras på ett ställe.
  assert.equal(modell.besparing.värde, 83);
  assert.equal(modell.löpande.värde, 140 + 96 + 77);
  assert.equal(modell.löpande.sedan, "september");
  assert.equal(modell.löpande.veckor, 3);

  const html = sparkvittoMarkup(modell);
  assert.match(html, /Veckan kostade/);
  assert.match(html, />612 kr</);
  assert.match(html, />83 kr</);
  assert.match(html, /Hemköp, den dyraste butiken vi kunde jämföra med/);
  assert.match(html, /Ni har sparat/);
  assert.match(html, /sedan i september/);
});

test("kvittot och Sparat-skärmen summerar samma logg till samma krona", () => {
  // EN VECKA, EN SUMMA - och det här är testet som gör det till ett krav och
  // inte en avsikt. Sparkvittots sparatSedan() är ett tunt skal kring L5:s;
  // den dagen någon kopierar tillbaka uträkningen hit och de två börjar driva
  // isär, står kvittot och Sparat-skärmen och påstår olika saker om samma
  // pengar. Då ska det här falla, inte upptäckas av en användare.
  const loggar = [
    logg(),
    logg().map(post => ({ ...post, hasComparison: true })),
    [],
    [{ date: "2026-09-01", weekKey: "x", savings: 40, hasComparison: true }],
    // Negativ besparing, saknat datum och trasigt datum: tre kanter där en
    // kopia lättast avviker (Math.max(0, …), filtret på nyckel).
    [{ date: "2026-09-02", weekKey: "y", savings: -50, hasComparison: true },
      { date: "2026-10-02", weekKey: "z", savings: 90, hasComparison: true },
      { weekKey: "utan-datum", savings: 70, hasComparison: true },
      { date: "inte-ett-datum", weekKey: "trasig", savings: 70, hasComparison: true }],
  ];
  for (const rader of loggar) {
    const facit = sparatSedanL5(rader);
    const kvitto = sparatSedan(rader);
    assert.equal(kvitto.kronor, facit.kronor, `kronor skilde sig för ${JSON.stringify(rader)}`);
    assert.equal(kvitto.sedan, facit.sedan, "första månaden skilde sig");
    assert.equal(kvitto.veckor, facit.poster, "antalet poster skilde sig");
  }
});

test("en vecka utan jämförbart underlag räknas inte in i den löpande summan", () => {
  // hasComparison:false betyder "veckan handlades, men det fanns ingen
  // besparing att påstå". Räknades den som 300 kr vore den löpande summan
  // ett svar på en fråga ingen ställt.
  const utan = sparatSedan(logg());
  assert.equal(utan.kronor, 313);
  const med = sparatSedan(logg().map(post => ({ ...post, hasComparison: true })));
  assert.equal(med.kronor, 613, "mutationsprov: filtret på hasComparison bär hela skillnaden");
});

test("servern kröner, inte kvittot - blockerad jämförelse ger ingen besparing", () => {
  // MUTATIONSPROVET FÖR REGEL 1. Totalerna finns, de är olika, och en naiv
  // klient skulle räkna 695 - 612 = 83 kr. Men compare_chains vägrade kröna
  // (butikerna prissatte inte samma varor), och då är 83 kr ett falskt besked
  // om användarens pengar - de tre varor som saknas kan kosta mer än så.
  const blockerad = sparkvittoModell({
    jämförelse: { cheapestChain: null, savings: null, comparedChains: 2, reason: "different_baskets" },
    kedjeTotaler: totaler(),
    logg: logg(),
  });
  assert.equal(blockerad.giltig, false);
  assert.equal(blockerad.skäl, "different_baskets");
  assert.doesNotMatch(veckansRader(sparkvittoMarkup(blockerad)), />\d+ kr</,
    "ett belopp för DEN HÄR VECKAN ritades trots att jämförelsen inte höll");
});

// ---------------------------------------------------------------------------
// 2 · Osäkra rader: golv, aldrig ett exakt tal (C7)
// ---------------------------------------------------------------------------

test("en vecka med osäkra rader visas som golv - minst N kr, aldrig ett exakt tal", () => {
  const osäker = modellen({
    kedjeTotaler: totaler({ Willys: kassa({ totalIsFloor: true, uncertainRows: 3 }) }),
  });
  assert.equal(osäker.vecka.golv, true);
  assert.equal(osäker.vecka.osäkraRader, 3);
  assert.equal(osäker.exakt, false);

  const html = sparkvittoMarkup(osäker);
  assert.match(html, golvlapp, "veckans tal saknar golvform");
  assert.match(html, /minst/, "golvet skrivs inte ut i ord");
  assert.match(html, /3 varor saknar säkert antal/);
  // Kärnan i C7, flyttad till en mer synlig plats: INGET tal på kortet får
  // stå naket när underlaget är osäkert. Ett naket tal är komponentens sätt
  // att säga "det här är kontrollerat".
  const lappar = prislappar(veckansRader(html));
  assert.equal(lappar.length, 2, "kvittot ska bära två belopp: veckans kostnad och besparingen");
  assert.ok(!lappar.some(naken),
    `ett exakt, omarkerat belopp står på ett kvitto vars underlag är osäkert: ${lappar}`);
});

test("besparingen är uppskattad, inte ett golv, när någon kassa är osäker", () => {
  // Golvet gäller en SUMMA - den kan bara växa. Besparingen är en SKILLNAD
  // mellan två summor, och en rad kan vara osäker i den ena kassen och exakt
  // i den andra (exactPackaging avgörs per butik och produkt). Då rör sig
  // skillnaden åt båda hållen, och "minst 83 kr" vore ett påstående åt det
  // farliga hållet.
  const osäker = modellen({
    kedjeTotaler: totaler({ Hemköp: kassa({ chain: "Hemköp", totalCheckoutCost: 695, totalIsFloor: true, uncertainRows: 1 }) }),
  });
  assert.equal(osäker.besparing.tillstånd, UPPSKATTAT);
  assert.equal(osäker.vecka.golv, false, "det är Hemköps kassa som är osäker, inte veckans");
  const html = sparkvittoMarkup(osäker);
  assert.match(html, calapp, "besparingen saknar ca-form fast underlaget är osäkert");
  assert.doesNotMatch(html, golvlapp, "besparingen ritades som ett golv - den kan sjunka också");
});

test("är varje kassa exakt och butiksverifierad står talen nakna", () => {
  // Mutationsprovet åt andra hållet: utan det här beviset kunde regeln ovan
  // uppfyllas genom att ALLTID skriva "ca", och då betyder markeringen inget.
  const säker = modellen();
  assert.equal(säker.exakt, true);
  assert.equal(säker.besparing.tillstånd, KONTROLLERAT);
  const html = veckansRader(sparkvittoMarkup(säker));
  const lappar = prislappar(html);
  assert.equal(lappar.length, 2);
  assert.ok(lappar.every(naken), `nakna tal väntades, fick ${lappar}`);
  assert.doesNotMatch(html, calapp);
  assert.doesNotMatch(html, golvlapp);
});

test("ser vi bara den ena kassan kan vi inte lova att skillnaden är exakt", () => {
  // Free-vyn: servern maskar de låsta kedjorna och skickar spridningen som
  // ETT tal (mask_pricing_for_free). Kedjan vi ser kan vara exakt medan den
  // andra inte är det - och det vi inte kan se får vi inte påstå något om.
  const free = sparkvittoModell({
    jämförelse: { cheapestChain: "Willys", reason: null, locked: true, priceSpread: 83 },
    kedjeTotaler: { Willys: kassa() },
    logg: logg(),
  });
  assert.equal(free.giltig, true);
  assert.equal(free.besparing.värde, 83, "priceSpread är samma tal som savings, maskat");
  assert.equal(free.besparing.tillstånd, UPPSKATTAT);
  assert.match(sparkvittoMarkup(free), /än den dyraste butiken vi kunde jämföra med/);
});

// ---------------------------------------------------------------------------
// 3 · Utan underlag: ett besked, aldrig "0 kr"
// ---------------------------------------------------------------------------

test("en vecka utan giltig jämförelse säger det - den visar inte 0 kr", () => {
  for (const [skäl, text] of Object.entries(SKÄLTEXT)) {
    const modell = sparkvittoModell({
      jämförelse: { cheapestChain: null, savings: null, reason: skäl },
      kedjeTotaler: totaler(),
      logg: logg(),
    });
    assert.equal(modell.giltig, false);
    const html = sparkvittoMarkup(modell);
    assert.match(html, /Vi kunde inte jämföra den här veckan\./);
    assert.match(html, new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
      `skälet ${skäl} skrevs inte ut i klartext`);
    assert.doesNotMatch(html, /0 kr/, "kortet skrev en nolla i stället för ett besked");
  }
});

test("ett okänt skäl tystar inte kortet", () => {
  const modell = sparkvittoModell({ jämförelse: { cheapestChain: null, reason: "nytt_skal_2027" }, logg: [] });
  assert.equal(modell.skältext, SKÄL_OKÄNT);
  assert.match(sparkvittoMarkup(modell), /Underlaget räckte inte/);
});

test("en kassa utan säker total blir inte 0 kr", () => {
  // price_list() lämnar totalCheckoutCost som null när ingen rad var säker -
  // "0 kr vore ett pris, och det vore fel". Number(null) är 0 och 0 är ett
  // finit tal, så den fällan är ett tecken bred.
  const utanKassa = modellen({ kedjeTotaler: totaler({ Willys: kassa({ totalCheckoutCost: null }) }) });
  assert.equal(utanKassa.vecka.värde, null);
  const html = veckansRader(sparkvittoMarkup(utanKassa));
  assert.doesNotMatch(html, /Veckan kostade/, "en kassa som saknas skrevs ut som en kostnad");
  assert.doesNotMatch(html, />0 kr</);
  assert.match(html, />83 kr</, "besparingen är serverns och står kvar");
});

test("den löpande summan står kvar även när veckan inte gick att jämföra", () => {
  // Den handlar om alla veckor, inte om den här - och är det enda som gör
  // kortet värt något den vecka jämförelsen inte höll.
  const modell = sparkvittoModell({ jämförelse: null, kedjeTotaler: {}, logg: logg() });
  assert.equal(modell.giltig, false);
  assert.match(sparkvittoMarkup(modell), /Ni har sparat/);
  // …men bara när den finns. En tom logg får inte bli "0 kr sparat".
  const tom = sparkvittoMarkup(sparkvittoModell({ jämförelse: null, kedjeTotaler: {}, logg: [] }));
  assert.doesNotMatch(tom, /Ni har sparat/);
  assert.doesNotMatch(tom, /kr/);
});

// ---------------------------------------------------------------------------
// 4 · Riktpriser syns i texten (D11)
// ---------------------------------------------------------------------------

test("vilar jämförelsen delvis på riktpriser står det, och beloppen blir uppskattade", () => {
  const blandad = modellen({
    jämförelse: krönt({ basis: "mixed" }),
    kedjeTotaler: totaler({ Hemköp: kassa({ chain: "Hemköp", totalCheckoutCost: 695, pricingBasis: "MIXED" }) }),
  });
  assert.equal(blandad.riktprisläge, "mixed");
  assert.equal(blandad.exakt, false);
  const html = sparkvittoMarkup(blandad);
  assert.match(html, new RegExp(RIKTPRISTEXT.mixed));
  assert.match(html, calapp);
});

test("vilar den helt på riktpriser sägs det utan reservation", () => {
  const referens = modellen({
    jämförelse: krönt({ cheapestChain: "ICA", priciestChain: "Hemköp", basis: "reference" }),
    kedjeTotaler: {
      ICA: kassa({ chain: "ICA", pricingBasis: "REFERENCE" }),
      Hemköp: kassa({ chain: "Hemköp", totalCheckoutCost: 695, pricingBasis: "REFERENCE" }),
    },
  });
  assert.equal(referens.riktprisläge, "reference");
  assert.match(sparkvittoMarkup(referens), new RegExp(RIKTPRISTEXT.reference));
  // Mutationsprov: är varje kassa butiksverifierad ska raden INTE stå där -
  // annars är beskedet bara bakgrundsbrus som ingen läser.
  assert.equal(modellen().riktprisläge, null);
  assert.doesNotMatch(sparkvittoMarkup(modellen()), /riktpriser/);
});

// ---------------------------------------------------------------------------
// 5 · En vecka, en summa: kvittot bokförs i sparloggen
// ---------------------------------------------------------------------------

test("kvittots riktiga tal ersätter planerarens uppskattning på samma veckonyckel", () => {
  // Sparloggen skrevs när veckan VALDES, ur den statiska katalogen. Läser
  // kvittot serverns 83 kr medan den löpande summan bär planerarens 140 kr,
  // säger samma kort två olika saker om samma vecka.
  const före = logg();
  const efter = bokförKvitto(före, "a|b", modellen());
  assert.equal(efter.length, före.length, "bokföringen fick inte lägga till en vecka");
  const post = efter.find(rad => rad.weekKey === "a|b");
  assert.equal(post.savings, 83);
  assert.equal(post.kvitto, true);
  assert.equal(post.exakt, true);
  assert.equal(post.date, "2026-09-02", "postens datum är veckans, inte kvittots");
  assert.equal(sparatSedan(efter).kronor, 83 + 96 + 77);
});

test("bokföringen är tyst när ingenting ändrats", () => {
  const bokförd = bokförKvitto(logg(), "a|b", modellen());
  assert.equal(bokförKvitto(bokförd, "a|b", modellen()), null,
    "en omritning till skulle ha skrivit localStorage igen");
  assert.equal(bokförKvitto(logg(), "a|b", sparkvittoModell({ jämförelse: null, logg: logg() })), null,
    "en ogiltig jämförelse skrev ändå in ett tal");
});

test("en handlad vecka utan post i loggen får en - annars är loggen tom för de flesta", () => {
  // SPARLOGGENS HÅL. Bara planjämförelsen ("Välj den här") skriver en post.
  // Den vanliga vägen - "Skapa min vecka" -> chooseMenu() - skriver ingenting,
  // och browser-E2E:n visar det svart på vitt: savingsLog är [] efter en
  // normalt skapad vecka. Utan den här posten kan den löpande summan aldrig
  // visas för den som inte råkat gå genom jämförelsen.
  const ny = bokförKvitto([], "a|b", modellen(), { datum: "2026-09-20", portionCost: 25.5 });
  assert.equal(ny.length, 1);
  assert.deepEqual(ny[0], {
    date: "2026-09-20", weekKey: "a|b", savings: 83, hasComparison: true,
    branch: "Willys", portionCost: 25.5, kvitto: true, exakt: true,
  });
  assert.equal(sparatSedan(ny).sedan, "september");

  // …men bara när varje fält är ett uppmätt tal. En post utan datum hamnar i
  // ingen månad, och portionCost 0 drar ner snittet med en siffra som aldrig
  // mätts.
  assert.equal(bokförKvitto([], "a|b", modellen()), null);
  assert.equal(bokförKvitto([], "a|b", modellen(), { datum: "2026-09-20", portionCost: 0 }), null);
  assert.equal(bokförKvitto([], "a|b", modellen(), { portionCost: 25.5 }), null);
});

test("en logg helt av kvitton ger en kontrollerad löpande summa, annars uppskattad", () => {
  const blandad = sparatSedan(bokförKvitto(logg(), "a|b", modellen()));
  assert.equal(blandad.exakt, false, "två poster bär fortfarande planerarens gissning");
  const allaKvitton = logg()
    .filter(post => post.hasComparison)
    .map(post => ({ ...post, kvitto: true, exakt: true }));
  assert.equal(sparatSedan(allaKvitton).exakt, true);
  assert.equal(sparkvittoModell({ jämförelse: null, logg: allaKvitton }).löpande.tillstånd, KONTROLLERAT);
  assert.equal(sparkvittoModell({ jämförelse: null, logg: logg() }).löpande.tillstånd, UPPSKATTAT);
});

// ---------------------------------------------------------------------------
// 6 · Jämförelsen överlever avbockningen
// ---------------------------------------------------------------------------

test("den sista avbockningen nollar jämförelsen - kvittot minns den ändå", () => {
  // clearPriceSnapshots() körs vid VARJE avbockning och sätter
  // state.dbComparison = null. Utan minnet är jämförelsen alltså borta i
  // exakt det ögonblick kvittot ska ritas, och kortet visar "–".
  återställSparkvitto();
  minnsJämförelse("a|b", krönt(), totaler());
  const kvar = minnsJämförelse("a|b", null, {});
  assert.equal(kvar.jämförelse.cheapestChain, "Willys");
  assert.equal(kvar.kedjeTotaler.Willys.totalCheckoutCost, 612);

  // …men bara för DEN VECKAN. En ny vecka har inte veckans jämförelse, och
  // förra veckans krona får aldrig målas som fakta över en ny lista.
  assert.equal(minnsJämförelse("x|y", null, {}).jämförelse, null);
});

test("en ogiltig jämförelse skriver inte över en giltig, men en giltig gör det", () => {
  återställSparkvitto();
  minnsJämförelse("a|b", krönt(), totaler());
  minnsJämförelse("a|b", { cheapestChain: null, reason: "tied_cheapest" }, {});
  assert.equal(minnsJämförelse("a|b", null, {}).jämförelse.savings, 83);
  minnsJämförelse("a|b", krönt({ savings: 44 }), totaler());
  assert.equal(minnsJämförelse("a|b", null, {}).jämförelse.savings, 44);
});

// ---------------------------------------------------------------------------
// 7 · Inkopplingen: Handla bestämmer när kvittot syns
// ---------------------------------------------------------------------------

function nod() {
  return { innerHTML: "" };
}

test("kvittot ritas när listan är avbockad och är tomt annars", () => {
  const värd = nod();
  initSparkvitto({ $: id => (id === "sparkvitto" ? värd : null) });
  initAppState({ storage: null, recipeBank: [] });
  återställSparkvitto();
  state.weekPlan = ["a", "b"];
  state.savingsLog = logg();
  state.dbComparison = krönt();
  state.dbChainTotals = totaler();

  // Medan listan handlas: inget kvitto på skärmen - men jämförelsen fångas.
  assert.equal(renderSparkvitto({ synligt: false }), null);
  assert.equal(värd.innerHTML, "");

  // Sista varan bockas av: clearPriceSnapshots har nollat jämförelsen.
  state.dbComparison = null;
  state.dbChainTotals = {};
  const modell = renderSparkvitto({ synligt: true });
  assert.equal(modell.giltig, true);
  assert.match(värd.innerHTML, />612 kr</);
  assert.match(värd.innerHTML, />83 kr</);
  // …och veckans post bär nu kvittots tal, inte planerarens.
  assert.equal(state.savingsLog.find(post => post.weekKey === "a|b").savings, 83);
  // Den löpande summan på kortet räknar med det talet REDAN vid första
  // omritningen - annars säger kortets två rader olika om samma vecka.
  assert.equal(modell.löpande.värde, 83 + 96 + 77);
  assert.match(värd.innerHTML, />256 kr</);
});

test("en vecka som aldrig gick genom planjämförelsen får sin post av kvittot", () => {
  const värd = nod();
  initSparkvitto({ $: id => (id === "sparkvitto" ? värd : null) });
  initAppState({ storage: null, recipeBank: [] });
  återställSparkvitto();
  state.weekPlan = ["a", "b", "c", "d"];
  state.personer = 4;
  state.savingsLog = [];                 // chooseMenu() skriver ingen post
  state.dbComparison = krönt();
  state.dbChainTotals = totaler();

  const modell = renderSparkvitto({ synligt: true });
  assert.equal(state.savingsLog.length, 1);
  const post = state.savingsLog[0];
  assert.equal(post.savings, 83);
  assert.equal(post.weekKey, "a|b|c|d");
  assert.equal(post.branch, "Willys");
  // Portionspriset räknas ur veckans uppmätta kostnad: 612 / (4 rätter x 4
  // personer). Katalogens gissning rörs aldrig.
  assert.equal(post.portionCost, 612 / 16);
  assert.equal(modell.löpande.värde, 83, "kortets löpande summa läser den post det just skrev");
  assert.match(värd.innerHTML, /Ni har sparat/);
});
