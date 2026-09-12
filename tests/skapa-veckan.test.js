// G7:s acceptanskriterium: ett tryck ger en färdig vecka, inte en modal.
//
// `index.html` har en knapp som heter "Skapa min vecka". Den öppnade
// `openPlanComparison()` - ett formulär med åtta veckotyper, sju av dem
// låsta för en gratisanvändare. En knapp som lovar ett resultat och levererar
// ett formulär är den klassiska tillitsläckan, och den fanns på fyra ställen,
// inte ett:
//
//   #generateBtn        "Skapa min vecka"
//   #newWeekBtn         "Skapa ny vecka"
//   #startNewWeekBtn    "Skapa nästa vecka"
//   [data-hem-create]   "Tryck här så sätter Matjakt ihop veckans middagar"
//
// Testet nedan läser LÖFTET ur markupen och KOPPLINGEN ur app.js, och kräver
// att de går ihop. Det är därför det inte räcker att räkna upp fyra
// knapp-id:n: nästa knapp någon döper till "Skapa ..." fångas av samma regel.
//
// Att veckan verkligen blir till prövas i webbläsaren:
// test_skapa_min_vecka_skapar_en_vecka_inte_ett_formular.

import assert from "node:assert/strict";
import test from "node:test";
import { läsFil } from "./fixtures/css-parser.mjs";

const html = läsFil("frontend/app/index.html");
const app = läsFil("frontend/app/app.js");

/** Klickhanterarens kropp för ett id, så långt den går på en rad. */
function klickHanterare(id) {
  const m = new RegExp(`\\$\\("${id}"\\)\\.addEventListener\\("click",([\\s\\S]*?)\\n(?=[$/a-z])`)
    .exec(app);
  return m ? m[1] : null;
}

// ---------------------------------------------------------------------------
// LÖFTET
// ---------------------------------------------------------------------------

test("knapparna lovar fortfarande en vecka - annars prövar testet fel sak", () => {
  // Ändras texten till något som inte lovar ett resultat är kravet nedan inte
  // längre rätt krav. Då ska testet falla, inte tyst godkänna.
  assert.match(html, /id="generateBtnLabel">Skapa min vecka</);
  assert.match(html, /id="newWeekBtn"[^>]*>Skapa ny vecka</);
  assert.match(html, /id="startNewWeekBtn"[^>]*><span>Skapa nästa vecka</);
  assert.match(app, /data-hem-create>\s*<strong>Vad blir det för middag i veckan\?<\/strong>/);
});

// ---------------------------------------------------------------------------
// KOPPLINGEN
// ---------------------------------------------------------------------------

test("ingen knapp som lovar en vecka öppnar planjämförelsen", () => {
  const fusk = [];
  for (const id of ["generateBtn", "newWeekBtn", "startNewWeekBtn"]) {
    const kropp = klickHanterare(id);
    assert.ok(kropp, `hittade ingen klickhanterare för #${id}`);
    if (/openPlanComparison\(/.test(kropp)) fusk.push(id);
    else if (!/chooseMenu\(|setView\(/.test(kropp)) fusk.push(`${id} (varken chooseMenu eller setView)`);
  }
  assert.deepEqual(fusk, [], `knappar som lovar en vecka men levererar ett formulär: ${fusk.join(", ")}`);
});

test("hjälteytans inbjudan skapar veckan i stället för att fråga om veckotyp", () => {
  const rad = app.split("\n").find(l => l.includes("data-hem-create]"));
  assert.ok(rad, "hittade ingen bindning för [data-hem-create]");
  assert.ok(!/openPlanComparison/.test(rad),
    'hjälteytan lovar "Matjakt sätter ihop veckans middagar" men öppnar planjämförelsen');
  assert.match(rad, /chooseMenu\(/);
});

// ---------------------------------------------------------------------------
// ...OCH ATT DEN SEKUNDÄRA VÄGEN FINNS KVAR
// ---------------------------------------------------------------------------

test('"Välj veckotyp" finns kvar som sekundär väg', () => {
  // Att ta bort valet vore ett annat fel än det här paketet lagar. Det ska
  // finnas - efter leveransen, inte före den.
  assert.match(html, /id="sheetPlanBtn"[^>]*>Välj veckotyp/,
    "raden i veckoarket är borta - då finns ingen väg till veckotyperna alls");
  assert.match(app, /\$\("sheetPlanBtn"\)\.addEventListener\("click",[^\n]*openPlanComparison\(\)/,
    "sheetPlanBtn leder inte längre till planjämförelsen");
  assert.match(html, /id="weekPlanUpsell"[^>]*>Vill du ha en familjevecka/,
    "raden ovanför den färdiga veckan är borta (G8)");
});

test("planjämförelsen finns kvar och går fortfarande att öppna", () => {
  assert.match(app, /function openPlanComparison\(/);
  assert.match(html, /id="planModal"/);
});
