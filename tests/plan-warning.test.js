import test from "node:test";
import assert from "node:assert/strict";
import { NUTRITION_TEXT, planWarning } from "../frontend/app/src/services/plan-warning.js";

test("färre middagar än man bad om förklaras, inte tigs ihjäl", () => {
  const text = planWarning({ önskade: 7, fick: 5, kosttyp: "veganskt", allergener: 2 });
  assert.match(text, /7 middagar/);
  assert.match(text, /Du fick 5/);
  assert.match(text, /veganskt/);
});

test("ALLERGIER FÖRESLÅS ALDRIG BORT", () => {
  // Kravet säger det uttryckligen, och det är den enda regeln här som
  // handlar om någons hälsa. Texten får nämna att allergier begränsar
  // utbudet - aldrig att man kan stänga av dem.
  const text = planWarning({ önskade: 7, fick: 3, allergener: 3, kosttyp: "veganskt", ogillar: 2 });
  for (const farligt of ["stäng av", "ta bort din allergi", "ignorera", "bortse från",
                         "slå av", "lätta på"]) {
    assert.ok(!text.toLowerCase().includes(farligt), `texten föreslog "${farligt}": ${text}`);
  }
  assert.match(text, /allergier rör vi inte/);
});

test("bara valbara krav föreslås ändras", () => {
  const text = planWarning({ önskade: 5, fick: 2, kosttyp: "vegetariskt", ogillar: 1 });
  assert.match(text, /färre middagar/);
  assert.match(text, /bredda kosttypen/);
  assert.match(text, /råvara du valt bort/);
});

test("utan krav skylls det på utbudet, inte på användaren", () => {
  const text = planWarning({ önskade: 7, fick: 4 });
  assert.match(text, /Receptutbudet räcker inte/);
  assert.ok(!text.includes("Dina krav"), text);
});

test("svenskan håller i både ental och plural", () => {
  // "råvara" i plural är "råvaror". Första utkastet skrev "råvaraor".
  const en = planWarning({ önskade: 4, fick: 2, ogillar: 1, allergener: 1 });
  assert.match(en, /1 bortvald råvara[,.)]/);
  assert.match(en, /1 allergi att undvika/);
  const flera = planWarning({ önskade: 4, fick: 2, ogillar: 9, allergener: 3 });
  assert.match(flera, /9 bortvalda råvaror/);
  assert.match(flera, /3 allergier att undvika/);
  assert.ok(!flera.includes("råvaraor"), flera);
});

test("en hel vecka ger ingen varning alls", () => {
  assert.equal(planWarning({ önskade: 4, fick: 4 }), "");
  assert.equal(planWarning({}), "");
});

test("näringsmålen varnar bara när veckan ändå blev hel", () => {
  // Den viktigare varningen vinner: att veckan är för kort betyder mer än
  // att näringsmålen inte gick att träffa.
  assert.equal(planWarning({ önskade: 4, fick: 4, nutritionShortfall: true }), NUTRITION_TEXT);
  assert.match(planWarning({ önskade: 7, fick: 5, nutritionShortfall: true }), /Du fick 5/);
});

test("NOLL rätter är det värsta fallet och måste förklaras", () => {
  // Första utkastet lät det här passera tyst. Testet fastställde då min
  // egen kod i stället för vad användaren behöver: en tom skärm utan
  // förklaring får appen att se trasig ut just när den lyder kraven.
  const text = planWarning({ önskade: 4, fick: 0, kosttyp: "veganskt", allergener: 5, ogillar: 9 });
  assert.match(text, /Inga rätter klarar dina krav/);
  assert.match(text, /veganskt/);
  assert.match(text, /allergier rör vi inte/);
  for (const farligt of ["stäng av", "ignorera", "bortse från", "lätta på"]) {
    assert.ok(!text.toLowerCase().includes(farligt), text);
  }
});

test("noll rätter utan några krav skyller på utbudet", () => {
  assert.match(planWarning({ önskade: 4, fick: 0 }), /inga rätter till veckan/i);
});

test("tomt utbud är laddning, inte ett besked om för hårda krav", () => {
  // Under uppstart är kandidaterna noll av tekniska skäl. Att då skriva
  // "Inga rätter klarar dina krav" vore att skrämmas i onödan.
  assert.equal(planWarning({ önskade: 4, fick: 0, utbud: 0, kosttyp: "veganskt" }), "");
  // Men med ett utbud som finns är noll träffar ett riktigt besked.
  assert.match(planWarning({ önskade: 4, fick: 0, utbud: 240, kosttyp: "veganskt" }),
               /Inga rätter klarar dina krav/);
});

test("ingen begärd vecka ger ingen varning", () => {
  assert.equal(planWarning({ önskade: 0, fick: 0 }), "");
});
