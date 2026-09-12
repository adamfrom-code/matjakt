// L2:s acceptanskriterium, i två delar:
//
//   1. "Sju rader ryms utan scroll på 844 px tillsammans med rubrik och
//      summering." Det är en MÄTNING i en webbläsare och ligger därför i
//      backend/tests/e2e/test_consumer_journey.py
//      (`test_veckan_ryms_pa_en_skarm_med_rubrik_och_summering`). Här nere
//      ligger det som går att bevisa utan en webbläsare - och som måste vara
//      sant för att mätningen ska betyda något.
//
//   2. "Två tomma dagar renderas rätt." Det provas här: en tom dag är en
//      rad med en streckad ruta, orden "Ingen middag planerad" och ett
//      plustecken - och två av dem är två rader, var och en på sin egen dag.
//
// Resten är skärmen som design D (telefon 2) beskriver den: alla sju dagarna
// synliga, inga dagflikar, priset ur L0:s komponent och en summering vars
// tal säger vad det grundar sig på (C7).

import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import { SAKNAS, UPPSKATTAT, prisMarkup } from "../frontend/app/src/views/pris.js";
import {
  DAYS, WEEK_DAY_COUNT, dagPrisTillstånd, initWeekView, todayIndex,
  veckoDagMarkup, veckoDagarMarkup, veckoIntervall, veckoUnderlag, veckofotMarkup,
} from "../frontend/app/src/views/week.js";

const läsFil = (namn) => readFileSync(new URL(`../${namn}`, import.meta.url), "utf8");
const money = (v) => `${Math.round(v).toLocaleString("sv-SE")} kr`;
const plural = (n, en, fler) => `${n} ${n === 1 ? en : fler}`;

function rigga({ hemma = () => false, harPris = () => true } = {}) {
  initWeekView({
    money, plural,
    personer: () => 4,
    recipeFeedback: () => ({}),
    itemHasPrice: harPris,
    itemAtHome: hemma,
  });
}

const rätt = (id, extra = {}) => ({ id, namn: id, tid: 25, portionspris: 38, ...extra });
const vara = (namn) => ({ namn });

/** Raderna som strängar, en per dag. Radens rot är det enda element vars
 *  klass är exakt `vecka-dag` - allt inuti heter `vecka-dag-<något>`. */
function rader(html) {
  const start = [...html.matchAll(/<div class="vecka-dag[ "]/g)].map((m) => m.index);
  return start.map((i, n) => html.slice(i, start[n + 1] ?? html.length));
}

// ---------------------------------------------------------------------------
// 1. SJU DAGAR, ALLTID - OCH INGA DAGFLIKAR
// ---------------------------------------------------------------------------

test("alla sju dagarna ritas, också när veckan har fyra middagar", () => {
  rigga();
  const rad = rader(veckoDagarMarkup(["a", "b", "c", "d"].map((id) => rätt(id))));
  assert.equal(rad.length, WEEK_DAY_COUNT);
  // Dagförkortningen står i klartext på varje rad, i rätt ordning. En vecka
  // vars rader inte bär sin dag är sju rätter, inte en vecka.
  DAYS.forEach((dag, index) => assert.ok(rad[index].includes(`>${dag}<`),
    `rad ${index} bär inte dagförkortningen ${dag}`));
});

test("dagflikarna och dagskortet finns inte kvar någonstans", () => {
  // Lagret G3 lämnade: sju flikar och ETT kort ovanför listan, alltså två
  // påståenden om samma vecka på samma skärm. En kvarglömd
  // `$("weekTodayCard")` i app.js hade dessutom kastat vid varje omritning.
  const html = läsFil("frontend/app/index.html");
  const app = läsFil("frontend/app/app.js");
  const css = läsFil("frontend/app/styles.css");
  for (const [namn, källa] of [["index.html", html], ["app.js", app], ["styles.css", css]]) {
    for (const spår of ["weekDayTabs", "week-day-tab", "weekTodayCard", "week-today"]) {
      assert.ok(!källa.includes(spår), `${namn} rör fortfarande ${spår}`);
    }
  }
});

test("dagens rad märks i TVÅ kanaler, inte bara i färg", () => {
  // Färgen på dagförkortningen överlever inte gråskala. Ordet gör det.
  rigga();
  const html = veckoDagMarkup(rätt("torsdag"), 3, { idag: 3 });
  assert.ok(html.includes("vecka-dag--idag"), "dagens rad saknar sitt tillstånd");
  assert.match(html, /class="vecka-dag-meta">Ikväll /,
    'dagens rad säger inte "Ikväll" - då bärs idag bara av en färg');
  const annan = veckoDagMarkup(rätt("fredag"), 4, { idag: 3 });
  assert.ok(!annan.includes("vecka-dag--idag") && !annan.includes("Ikväll"));
});

test("todayIndex räknar måndag som veckans första dag", () => {
  assert.equal(todayIndex(new Date(2026, 8, 7)), 0, "måndag 7 september är inte dag 0");
  assert.equal(todayIndex(new Date(2026, 8, 13)), 6, "söndagen hamnade först i veckan");
});

test("ögonbrynet säger vilken vecka det är, också över ett månadsskifte", () => {
  assert.equal(veckoIntervall(new Date(2026, 8, 12)), "7–13 september");
  assert.equal(veckoIntervall(new Date(2026, 8, 30)), "28 september–4 oktober");
});

// ---------------------------------------------------------------------------
// 2. TVÅ TOMMA DAGAR
// ---------------------------------------------------------------------------

test("två tomma dagar blir två rader, var och en på sin egen dag", () => {
  rigga();
  // Onsdag och söndag tomma - exakt veckan i design D, telefon 2.
  const vecka = [rätt("mån"), rätt("tis"), null, rätt("tor"), rätt("fre"), rätt("lör"), null];
  const rad = rader(veckoDagarMarkup(vecka));
  assert.equal(rad.length, 7);
  const tomma = rad.map((r, i) => (r.includes("vecka-dag--tom") ? i : -1)).filter((i) => i >= 0);
  assert.deepEqual(tomma, [2, 6],
    "de tomma dagarna hamnade inte på onsdag och söndag - raderna förskjuts");
  for (const index of tomma) {
    const r = rad[index];
    assert.ok(r.includes('class="vecka-dag-ruta"'), "den tomma dagen saknar sin streckade ruta");
    assert.ok(r.includes("Ingen middag planerad"), "den tomma dagen säger inte vad som saknas");
    assert.ok(r.includes("＋"), "den tomma dagen har ingen väg in");
    assert.ok(r.includes('data-week-add-meal'), "plustecknet leder ingenstans");
    // Sju likadana plus i rad är sju likadana knappar för den som lyssnar.
    assert.match(r, new RegExp(`aria-label="Lägg till middag på ${index === 2 ? "onsdag" : "söndag"}"`),
      "plustecknet säger inte vilken dag det gäller");
    assert.ok(!r.includes("<img"), "den tomma dagen ritade en bild");
    assert.ok(!r.includes("data-week-swap"), "det går att byta en rätt som inte finns");
  }
});

test("en tom dag mitt i veckan skjuter inte de senare dagarna uppåt", () => {
  rigga();
  const rad = rader(veckoDagarMarkup([rätt("mån"), null, rätt("ons")]));
  assert.ok(rad[1].includes("vecka-dag--tom"), "tisdagen blev inte tom");
  assert.ok(rad[2].includes(">ons<"), "onsdagens rätt hamnade på tisdagen");
});

// ---------------------------------------------------------------------------
// 3. RADEN: TRE SYSKON, ALDRIG EN KNAPP I EN KNAPP
// ---------------------------------------------------------------------------

test("raden öppnar rätten, byter den och minns vad som blev av den", () => {
  rigga();
  const html = veckoDagMarkup(rätt("kottbullar", { namn: "Köttbullar med potatismos" }), 0);
  assert.ok(html.includes('data-week-details="kottbullar"'), "raden öppnar inte receptet");
  assert.ok(html.includes('data-week-swap="kottbullar"'), "bytesknappen saknas");
  // G3: "✓ Lagad" och "✗ Hoppade över" fanns bara i planlistans radmeny, och
  // var därför oåtkomliga bakom ett hidden-attribut. De får inte bli
  // oåtkomliga igen för att raden blev vackrare.
  assert.ok(html.includes('data-cooked="kottbullar"'), "✓ Lagad försvann ur veckan");
  assert.ok(html.includes('data-skipped="kottbullar"'), "✗ Hoppade över försvann ur veckan");
  // Tre syskon i en behållare. En knapp inuti en knapp är ogiltig markup och
  // ger en tabbordning ingen kan förutse.
  const öppna = html.indexOf('class="vecka-dag-oppna"');
  const slutPåÖppna = html.indexOf("</button>", öppna);
  assert.ok(slutPåÖppna < html.indexOf("vecka-dag-byt"), "bytesknappen ligger inuti radens knapp");
  assert.ok(slutPåÖppna < html.indexOf("vecka-dag-meny"), "radmenyn ligger inuti radens knapp");
  // Bilden kommer ur M2:s komponent - ett foto, eller reservkortet.
  assert.match(html, /class="recipe-photo vecka-dag-foto"|class="recipe-photo recipe-fallback reservkort/);
});

test("ett recept utan foto får reservkortet i raden, aldrig ett hål", () => {
  // M2: tio av de elva rätter som saknar foto är middagar. Reservkortet i den
  // här raden är alltså vardag, inte randfall.
  rigga();
  const html = veckoDagMarkup(rätt("pitepalt", { namn: "Pitepalt", bild: "" }), 1);
  assert.ok(html.includes("reservkort"), "en rätt utan foto lämnade en tom bildyta");
  assert.ok(!html.includes("<img"), "en rätt utan foto fick ändå en <img>");
});

// ---------------------------------------------------------------------------
// 4. PRISET KOMMER UR L0
// ---------------------------------------------------------------------------

test("dagradens pris är L0:s komponent, tecken för tecken", () => {
  rigga();
  const uppskattat = veckoDagMarkup(rätt("a", { portionspris: 38 }), 0);
  assert.ok(uppskattat.includes(prisMarkup(money(38), UPPSKATTAT)),
    `raden skrev en EGEN prismarkup:\n${uppskattat}`);
  // Bankens portionspris är räknat för ett standardhushåll ur kedjans
  // priser - riktigt, men inte verifierat i butiken användaren går till.
  // Det är alltså uppskattat, aldrig kontrollerat.
  assert.equal(dagPrisTillstånd(rätt("a")), UPPSKATTAT);
});

test("en rätt utan pris får en tom ram, inte ett streck och inte en nolla", () => {
  rigga();
  for (const utan of [rätt("a", { portionspris: null }), rätt("b", { priceStatus: "unavailable" })]) {
    assert.equal(dagPrisTillstånd(utan), SAKNAS);
    assert.ok(veckoDagMarkup(utan, 0).includes(prisMarkup(null, SAKNAS)),
      "en rätt utan pris ritades inte som L0:s tomma fack");
  }
});

test("veckovyn skriver ingen prismarkup av eget märke", () => {
  const källa = läsFil("frontend/app/src/views/week.js")
    .replace(/\/\*[\s\S]*?\*\//g, "").split("\n").filter((r) => !/^\s*\/\//.test(r)).join("\n");
  for (const klass of ["pris--ca", "pris--golv", '"cirka"', '"saknas"', '"minst"', "price-missing"]) {
    assert.ok(!källa.includes(klass),
      `src/views/week.js bygger egen prismarkup: ${klass} hör hemma i pris.js`);
  }
});

// ---------------------------------------------------------------------------
// 5. SUMMERINGEN: DELPOSTER, LINJE, SUMMA - OCH C7:s GOLV
// ---------------------------------------------------------------------------

const underlag = (extra = {}) => veckoUnderlag({
  selected: [rätt("a"), rätt("b"), rätt("c"), rätt("d"), rätt("e")],
  shoppingItems: [vara("Gul lök"), vara("Dill")],
  total: 612,
  headerDb: { pricingBasis: "VERIFIED", totalIsFloor: false },
  ...extra,
});

test("summeringen räknar veckan, inte platserna i den", () => {
  rigga();
  const u = underlag();
  assert.equal(u.middagar, 5);
  assert.equal(u.tomma, 2, "två planlösa dagar räknades inte");
  assert.equal(u.varor, 2);
  const html = veckofotMarkup(u);
  assert.ok(html.includes("<b>5</b> av 7 dagar"), html);
  assert.ok(html.includes("<b>2</b> tomma dagar"), html);
  assert.ok(html.includes("<b>2</b> varor"), html);
});

test("C7: en rätt utan pris gör summan till ett golv, och foten säger MINST", () => {
  rigga();
  const u = underlag({
    selected: [rätt("a"), rätt("b", { portionspris: null }), rätt("c")],
  });
  assert.equal(u.utanPris, 1);
  assert.equal(u.golv, true, "summan visades som ett exakt tal trots en rätt utan pris");
  const html = veckofotMarkup(u);
  assert.ok(html.includes("Minst att handla för"), html);
  assert.ok(html.includes(prisMarkup(money(612), "kontrollerat", { golv: true, klass: "vecka-fot-tal" })),
    "golvet ritades inte med L0:s komponent");
  // Och summan säger vad den grundar sig på.
  assert.ok(html.includes("1 middag saknar pris"), html);
  assert.ok(html.includes("kassan kan bli högre, aldrig lägre"), html);
});

test("C7: en vara utan pris gör summan till ett golv den också", () => {
  rigga({ harPris: (item) => item.namn !== "Dill" });
  const u = underlag();
  assert.equal(u.varorUtanPris, 1);
  assert.equal(u.golv, true);
  // Två olika brister, aldrig hopslagna till ett tal.
  const html = veckofotMarkup(u);
  assert.ok(html.includes("1 vara saknar pris"), html);
  assert.ok(!html.includes("middag saknar pris"), "en vara räknades som en middag");
});

test("C7: serverns golvflagga räknas med, men veckan får överrösta den", () => {
  rigga();
  // Servern vet vad DEN prissatte; veckan kan bära rader den aldrig såg.
  assert.equal(underlag({ headerDb: { pricingBasis: "VERIFIED", totalIsFloor: true } }).golv, true);
  assert.equal(underlag({
    headerDb: { pricingBasis: "VERIFIED", totalIsFloor: false },
    selected: [rätt("a", { portionspris: null })],
  }).golv, true);
});

test("en helt prissatt vecka är inget golv - då är talet veckans belopp", () => {
  rigga();
  const u = underlag();
  assert.equal(u.golv, false);
  assert.equal(u.tillstånd, "kontrollerat");
  const html = veckofotMarkup(u);
  assert.ok(html.includes("Att handla för") && !html.includes("Minst att handla för"), html);
  assert.ok(html.includes("Räknat på 5 prissatta middagar och 2 varor."), html);
});

test("en summa som inte är butiksverifierad hela vägen är uppskattad", () => {
  rigga();
  assert.equal(underlag({ headerDb: { pricingBasis: "MIXED" } }).tillstånd, UPPSKATTAT);
  assert.equal(underlag({ headerDb: null }).tillstånd, UPPSKATTAT,
    "ett tal utan kedjeresultat är en beräkning, inte ett kontrollerat pris");
  assert.equal(underlag({ total: null }).tillstånd, SAKNAS);
});

test("utan pris säger foten att priset hämtas - inte att veckan är gratis", () => {
  rigga();
  const html = veckofotMarkup(underlag({ total: null }));
  assert.ok(html.includes(prisMarkup(null, SAKNAS, { klass: "vecka-fot-tal" })), html);
  assert.ok(html.includes("Priset hämtas när veckan är prissatt hos en butik."), html);
  assert.ok(!/\b0 kr\b/.test(html), "en oprissatt vecka skrevs ut som noll kronor");
});
