// U1: barnvänliga rätter väger tyngre när hushållet har barn - mjukt, och
// bara bakom flaggan planering.barn.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BARN_BONUS_PER_RATT, arBarnvanlig, barnBonus } from "../frontend/app/src/services/barnlage.js";

const kottbullar = { id: "k", tags: ["barn", "husmanskost"] };
const chili = { id: "c", tags: ["kryddigt"] };
const favorit = { id: "f", tags: [], typ: "Familjefavorit" };

test("barnvänlig = taggen barn eller typen Familjefavorit", () => {
  assert.equal(arBarnvanlig(kottbullar), true);
  assert.equal(arBarnvanlig(favorit), true);
  assert.equal(arBarnvanlig(chili), false);
  assert.equal(arBarnvanlig(null), false);
});

test("utan barn ingen bonus; med barn en bonus per barnvänlig rätt, oavsett antal barn", () => {
  assert.equal(barnBonus([kottbullar, chili, favorit], { children: 0 }), 0);
  assert.equal(barnBonus([kottbullar, chili, favorit], { children: 1 }), 2 * BARN_BONUS_PER_RATT);
  assert.equal(barnBonus([kottbullar, chili, favorit], { children: 3 }), 2 * BARN_BONUS_PER_RATT);
  assert.equal(barnBonus([chili], { children: 2 }), 0);
  assert.equal(barnBonus(null, { children: 2 }), 0);
  assert.equal(barnBonus([kottbullar], { children: "x" }), 0);
});

test("bonusen är mjuk: mindre än ett gillar-betyg per rätt", () => {
  // recipeAffinity ger 3 för "gillar" (app.js). Barnen tippar valet, de
  // bestämmer det inte.
  assert.ok(BARN_BONUS_PER_RATT > 0 && BARN_BONUS_PER_RATT < 3);
});

test("app.js lägger bonusen i comboAffinity bara bakom flaggan, med barn ur hushållet eller medlemmarna", () => {
  const appJs = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
  const start = appJs.indexOf("function comboBarnBonus");
  const body = appJs.slice(start, appJs.indexOf("const comboAffinity", start));
  assert.match(body, /if \(!flagga\("planering\.barn"\)\) return 0;/);
  assert.match(body, /m\.kind === "child" \|\| m\.profile\?\.child/);
  assert.match(body, /Number\(state\.hushall\?\.barn\) \|\| 0/);
  const affinity = appJs.slice(appJs.indexOf("const comboAffinity"), appJs.indexOf("const comboAffinity") + 260);
  assert.match(affinity, /\+ comboPantryBonus\(combo\)\n  \+ comboBarnBonus\(combo\);/);
});
