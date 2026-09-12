// G3:s acceptanskriterium: sju rader syns utan att man klickar.
//
// "Veckans plan" var dold på två sätt samtidigt, och båda måste bort för att
// frågan appen finns för - *vad äter vi i veckan* - ska gå att besvara med
// ögonen:
//
//   1. `<div class="week-overview-section week-plan-section" hidden>` i
//      index.html, med `.week-plan-section[hidden]{display:none!important}`
//      i styles.css som ryggrad.
//   2. `selected.slice(0, WEEK_PLAN_PREVIEW_COUNT)` i renderWeekOverview -
//      fyra rader och en "Visa hela veckan"-knapp, alltså ett klick till även
//      om sektionen hade varit synlig.
//
// Därför prövas båda lagren, och det tredje som gör sjuan till en sanning:
// weekPlan är bara så lång som antalet middagar (fyra), medan dagflikarna
// ovanför alltid ritar sju dagar. Listan måste fylla ut veckan själv, annars
// står det fyra rader under sju flikar.

import assert from "node:assert/strict";
import test from "node:test";
import { deklarationer, läsFil, läsStyles, parseRegler } from "./fixtures/css-parser.mjs";
import { WEEK_DAY_COUNT, weekPlanDays } from "../frontend/app/src/views/week.js";

const html = läsFil("frontend/app/index.html");
const css = läsStyles();
const app = läsFil("frontend/app/app.js");

/** Attributen på den tagg som bär `klass`. */
function taggMed(markup, klass) {
  const träff = new RegExp(`<([a-z][\\w-]*)([^>]*\\bclass="[^"]*\\b${klass}\\b[^"]*"[^>]*)>`, "i")
    .exec(markup);
  return träff ? { namn: träff[1], attr: träff[2] } : null;
}

// ---------------------------------------------------------------------------
// LAGER 1 · MARKUPEN
// ---------------------------------------------------------------------------

test("veckolistan är inte längre dold i markupen", () => {
  const tagg = taggMed(html, "week-plan-section");
  assert.ok(tagg, ".week-plan-section finns inte längre i index.html");
  assert.ok(!/\bhidden\b/.test(tagg.attr),
    "week-plan-section är fortfarande `hidden`.\n" +
    "Listan med veckans sju rätter är det enda stället i appen där hela\n" +
    'veckan går att se, och "✓ Lagad" / "✗ Hoppade över" finns bara där.');
});

test("ingen CSS-regel gömmer veckolistan villkorslöst", () => {
  // `[hidden]`-regeln får finnas kvar - den gör ingenting när attributet är
  // borta. En regel som gömmer sektionen UTAN attributvillkor är däremot
  // samma fel i ett annat lager.
  const gömmer = [];
  for (const regel of parseRegler(css)) {
    for (const del of regel.delar) {
      const selektor = del.trim();
      if (!/\.week-plan-section|\.week-plan-list|#weekPlanList/.test(selektor)) continue;
      if (/\[hidden\]/.test(selektor)) continue;          // villkorat på attributet
      for (const d of deklarationer(regel.block)) {
        if (d.prop === "display" && /^none/.test(d.värde.trim())) gömmer.push(selektor);
        if (d.prop === "visibility" && /^hidden/.test(d.värde.trim())) gömmer.push(selektor);
      }
    }
  }
  assert.deepEqual(gömmer, [], `CSS gömmer veckolistan: ${gömmer.join(", ")}`);
});

// ---------------------------------------------------------------------------
// LAGER 2 · INGEN KNAPP MELLAN ANVÄNDAREN OCH VECKAN
// ---------------------------------------------------------------------------

test('"Visa hela veckan"-knappen finns inte kvar någonstans', () => {
  // Knappen var det andra lagret: fyra rader, och resten bakom ett klick.
  // Den ska vara borta ur BÅDA filerna - en kvarglömd `$("weekPlanToggle")`
  // i app.js hade kastat på varje omritning av Vecka-vyn.
  assert.ok(!/weekPlanToggle/.test(html), "weekPlanToggle finns kvar i index.html");
  assert.ok(!/weekPlanToggle/.test(app), "app.js rör fortfarande weekPlanToggle");
  assert.ok(!/WEEK_PLAN_PREVIEW_COUNT/.test(app),
    "veckolistan har fortfarande ett förhandsvisningstak");
});

// ---------------------------------------------------------------------------
// LAGER 3 · SJU RADER, OCKSÅ NÄR VECKAN HAR FYRA MIDDAGAR
// ---------------------------------------------------------------------------

const rätt = (id) => ({ id, namn: id });

test("sju rader ritas även när veckan bara har fyra middagar", () => {
  const fyra = ["mån", "tis", "ons", "tor"].map(rätt);
  const dagar = weekPlanDays(fyra);
  assert.equal(dagar.length, WEEK_DAY_COUNT, "veckan ritades inte som sju dagar");
  assert.deepEqual(dagar.slice(0, 4).map((d) => d.id), ["mån", "tis", "ons", "tor"]);
  assert.deepEqual(dagar.slice(4), [null, null, null],
    "de planlösa dagarna föll bort i stället för att bli tomma rader");
});

test("en tom dag mitt i veckan behåller sin plats", () => {
  // Samma fel som E2 lagade i dagflikarna: filtreras null bort förskjuts
  // alla senare dagar ett steg, och torsdagens rätt hamnar på onsdagen.
  const medLucka = [rätt("mån"), null, rätt("ons"), null, rätt("fre")];
  const dagar = weekPlanDays(medLucka);
  assert.equal(dagar.length, WEEK_DAY_COUNT);
  assert.deepEqual(dagar.map((d) => d?.id ?? null),
    ["mån", null, "ons", null, "fre", null, null]);
});

test("sju middagar ger sju rader - inga fyra bakom en knapp", () => {
  const heleVeckan = ["1", "2", "3", "4", "5", "6", "7"].map(rätt);
  const dagar = weekPlanDays(heleVeckan);
  assert.equal(dagar.length, 7);
  assert.equal(dagar.filter(Boolean).length, 7,
    "en rätt tappades - listan visar inte hela veckan");
});

test("en längre vecka än sju dagar tappar ingen rätt", () => {
  // Ett gammalt sparat läge kan ha fler platser än sju. Att klippa vid sju
  // vore att gömma en rad igen, i tysthet.
  const åtta = ["1", "2", "3", "4", "5", "6", "7", "8"].map(rätt);
  assert.equal(weekPlanDays(åtta).length, 8);
});

test("ingen vecka alls ger sju tomma dagar, inte noll rader", () => {
  assert.deepEqual(weekPlanDays([]), Array(WEEK_DAY_COUNT).fill(null));
  assert.deepEqual(weekPlanDays(undefined), Array(WEEK_DAY_COUNT).fill(null));
});

test("renderWeekOverview ritar listan ur weekPlanDays", () => {
  // Bindningen mellan de rena dagarna ovan och skärmen. Utan den kunde
  // funktionen vara aldrig så rätt medan renderingen fortsatte klippa.
  assert.match(app, /\$\("weekPlanList"\)\.innerHTML\s*=\s*weekPlanDays\(/,
    "veckolistan fylls inte ur weekPlanDays()");
});
