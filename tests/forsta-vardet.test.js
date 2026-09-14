// G8:s acceptanskriterium, halva två: inget hänglås på en leveransskärm.
//
// Halva paketet landade redan: onboardingens sista knapp öppnade
// planjämförelsen med sju av åtta veckotyper låsta, och den vägen är borta -
// finishOnboarding() kör chooseMenu() rakt till Vecka (src/views/account.js),
// och erbjudandet ligger som en rad ovanför veckan (renderWeekPlanUpsell).
//
// Men hänglåsväggen hade bara bytt plats. G13 flyttade butiksvalet till Vecka,
// och skärmen hon landar på ritade "Var blir det billigast?" med två kort som
// sa *Se pris med Premium*, OVANFÖR veckan. En ny användare fick alltså
// fortfarande se ett lås före sin första måltid.
//
// Här prövas regeln som tillstånd (modulen) och som koppling (app.js). Att det
// blir sant i en riktig webbläsare prövas i
// test_forsta_veckan_kommer_utan_betalvagg.

import assert from "node:assert/strict";
import test from "node:test";
import { läsFil } from "./fixtures/css-parser.mjs";
import { utanHanglas, veckanLevereras, vyBytt } from "../frontend/app/src/views/forsta-vardet.js";

const app = läsFil("frontend/app/app.js");

/** Butikskorten som renderStoreCards bygger dem: en prissatt, två låsta. */
const KORT = () => [
  { chain: "Willys", total: 419, cheapest: true, active: true },
  { chain: "City Gross", locked: true },
  { chain: "Hemköp", locked: true },
];

/** Modulen lever i minnet - varje test börjar från ett känt läge. */
function nollställ() {
  vyBytt("home");
  vyBytt("home");
}

// ---------------------------------------------------------------------------
// ÖGONBLICKET
// ---------------------------------------------------------------------------

test("veckan levereras: hennes butik står kvar, hänglåsen inte", () => {
  nollställ();
  veckanLevereras();
  const synliga = utanHanglas(KORT());
  assert.deepEqual(synliga.map(k => k.chain), ["Willys"]);
  assert.equal(synliga.filter(k => k.locked).length, 0);
});

test("ankomsten till Vecka avslutar inte det ögonblick den ÄR", () => {
  nollställ();
  veckanLevereras();
  // chooseMenu() avslutar själv med setView("week"). Räknades det som ett
  // vybyte skulle ögonblicket ta slut i samma andetag som det började, och
  // hänglåsen stå kvar på precis den skärm paketet handlar om.
  assert.equal(vyBytt("week"), false, "ankomsten begärde en omritning");
  assert.equal(utanHanglas(KORT()).length, 1);
});

test("levereras veckan men hamnar hon någon annanstans är ögonblicket slut", () => {
  // levererar-flaggan finns för EN sak: chooseMenu() avslutar själv med
  // setView("week"), och den ankomsten ÄR leveransen. Varje annan vy är ett
  // steg bort från den, och då ska ögonblicket ta slut på en gång - annars
  // ligger det kvar och tystar butikskorten på en skärm som inte är
  // leveransskärmen. Utan det här testet går guarden att byta mot ett blankt
  // "första vybytet räknas aldrig" utan att något blir rött.
  nollställ();
  veckanLevereras();
  assert.equal(vyBytt("basket"), true, "ögonblicket följde med till en annan vy");
  assert.equal(utanHanglas(KORT()).length, 3);
});

test("hon navigerar vidare: erbjudandet tillbaka, och korten ritas om", () => {
  nollställ();
  veckanLevereras();
  vyBytt("week");
  assert.equal(vyBytt("basket"), true, "ingen omritning begärdes när ögonblicket tog slut");
  assert.equal(utanHanglas(KORT()).length, 3, "de låsta butikerna kom inte tillbaka");
});

test("ett tryck på Vecka-fliken är också att navigera", () => {
  // Hon kan gå tillbaka till Vecka utan att passera en annan flik. Det är
  // fortfarande ett val hon gör, inte leveransen - annars vore ögonblicket
  // kvar hela besöket och erbjudandet aldrig synligt igen.
  nollställ();
  veckanLevereras();
  vyBytt("week");
  assert.equal(vyBytt("week"), true);
  assert.equal(utanHanglas(KORT()).length, 3);
});

test("ögonblicket börjar inte om av sig självt", () => {
  nollställ();
  veckanLevereras();
  vyBytt("week");
  vyBytt("basket");
  assert.equal(vyBytt("week"), false);
  assert.equal(utanHanglas(KORT()).length, 3);
});

test("uppstartens tysta vecka är ingen leverans", () => {
  // app.js bygger en vecka vid start om ingen finns - chooseMenu(false), utan
  // vybyte, bakom onboardingrutan. Ingen ser den skärmen, och den ska inte
  // tysta butikskorten på den vy hon råkar stå på.
  nollställ();
  veckanLevereras(false);
  assert.equal(utanHanglas(KORT()).length, 3);
});

test("aldrig noll butikskort: har hon bara låsta står de kvar", () => {
  nollställ();
  veckanLevereras();
  const bara_lasta = [{ chain: "City Gross", locked: true }, { chain: "Hemköp", locked: true }];
  assert.deepEqual(utanHanglas(bara_lasta), bara_lasta,
    'ett tomt "Var blir det billigast?" är sämre än ett ärligt lås');
});

// ---------------------------------------------------------------------------
// KOPPLINGEN I app.js
// ---------------------------------------------------------------------------

test("butikskorten ritas genom utanHanglas", () => {
  // Regeln är verkningslös om korten går rakt ur entries till skärmen igen.
  assert.match(app, /container\.innerHTML = utanHanglas\(entries\)\.map\(storeCardMarkup\)/,
    "renderStoreCards ritar hänglåsen utan att fråga - leveransskärmen låser igen");
});

/**
 * Kroppen av `function <namn>(`, räknad med klammer i stället för med ett
 * lat `\n}`.
 *
 * Skillnaden är inte kosmetisk. `setView` skrivs på tre rader med sista
 * satsen och klammern om varandra; ett lat uttryck går då förbi hela
 * funktionen och fångar NÄSTA funktions kropp i stället. Testet hade blivit
 * grönt av en rad som stod någon helt annanstans - alltså grönt av fel
 * anledning, vilket är värre än rött.
 */
function kroppen(namn) {
  const start = app.indexOf(`function ${namn}(`);
  if (start < 0) return null;
  let i = app.indexOf("{", start), djup = 0;
  for (let j = i; j < app.length; j++) {
    if (app[j] === "{") djup++;
    else if (app[j] === "}" && --djup === 0) return app.slice(i + 1, j);
  }
  return null;
}

/** Prosa i en kommentar är ingen anropsplats. */
const utanKommentarer = text =>
  text.split("\n").filter(rad => !/^\s*\/\//.test(rad)).join("\n");

test("chooseMenu markerar leveransen före renderingen", () => {
  const kropp = kroppen("chooseMenu");
  assert.ok(kropp, "hittade ingen chooseMenu()");
  assert.match(kropp, /veckanLevereras\(shouldScroll\)/,
    "chooseMenu() lämnar över veckan utan att säga till - ögonblicket börjar aldrig");
  const kod = utanKommentarer(kropp);
  assert.ok(kod.indexOf("veckanLevereras") < kod.indexOf("render()"),
    "leveransen markeras efter render() - då hinner hänglåsen ritas ändå");
  // shouldScroll, inte true: uppstartens tysta vecka är ingen leverans.
  assert.ok(!/veckanLevereras\(\s*(true)?\s*\)/.test(kod),
    "veckanLevereras() utan shouldScroll tystar korten även för chooseMenu(false)");
});

test("setView avslutar ögonblicket och ritar om korten", () => {
  const kropp = kroppen("setView");
  assert.ok(kropp, "hittade ingen setView()");
  assert.match(utanKommentarer(kropp), /if \(vyBytt\(view\)\) renderStoreCards\(\)/,
    "utan omritningen saknar korten sina låsta butiker tills något annat råkar rita om dem");
});

test("omritningen sker direkt, inte på nästa bildruta", () => {
  // Den här raden är skriven i blod. Först stod det `invalidate("basket")`,
  // och render-bussen ritar på nästa bildruta (requestAnimationFrame). Vyn
  // hann bytas medan korten fortfarande stod filtrerade, och
  // test_full_consumer_journey läste NOLL låsta butiker direkt efter
  // fliktrycket - locked.count() i Playwright väntar inte, och ska inte
  // behöva göra det. Erbjudandet ska stå där när vyn står där.
  const kod = utanKommentarer(kroppen("setView"));
  assert.ok(!/vyBytt\(view\)\)\s*invalidate\(/.test(kod),
    "omritningen köades igen - då är erbjudandet en bildruta försenat");
});
