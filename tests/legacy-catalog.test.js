// Den gamla katalogen: fyra handskrivna tabeller som flyttat ut ur app.js
// (F6). En ren dataflytt har inget beteende att pröva - men de fyra
// tabellerna refererar till VARANDRA, och de referenserna har aldrig varit
// mätta. Faller en av dem tyst igenom är följden inte ett fel utan ett
// tystare fel: `PACKAGE_INFO[namn]?.unit || "st"` svarar "st" om raden
// saknas, och ett gram blir en styck utan att någon får veta det.
//
// Testerna nedan är därför två saker på en gång: kvitto på att flytten är
// gjord, och den första kontrollen av att tabellerna hänger ihop.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { PACKAGE_INFO, PRODUCT_CATALOG, RECIPE_DETAILS, RECIPE_QUANTITIES }
  from "../frontend/app/src/data/legacy-catalog.js";

const APP = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
const NAMN = ["PRODUCT_CATALOG", "PACKAGE_INFO", "RECIPE_QUANTITIES", "RECIPE_DETAILS"];

// Alla varunamn som de lokala recepten faktiskt ber om.
const ingredienser = [...new Set(Object.values(RECIPE_QUANTITIES).flatMap(Object.keys))];

test("F6: app.js deklarerar inte längre katalogen - den importeras", () => {
  for (const namn of NAMN) {
    assert.equal(new RegExp(`^const ${namn} = \\{`, "m").test(APP), false,
                 `${namn} deklareras fortfarande i app.js`);
    assert.ok(APP.includes(namn), `${namn} används inte längre i app.js alls`);
  }
  assert.match(APP, /import \{[^}]*\} from "\.\/src\/data\/legacy-catalog\.js";/);
});

test("varje ingrediens ett lokalt recept ber om finns i prislistan", () => {
  // PRODUCT_CATALOG är uppslagsboken bakom skafferiets "lägg till
  // vara"-sökning: namn, märke och förpackningsstorlek. Ett receptnamn utan
  // rad där går inte att slå upp.
  const saknas = ingredienser.filter(namn => !PRODUCT_CATALOG[namn]);
  assert.deepEqual(saknas, [], `ingredienser utan rad i PRODUCT_CATALOG: ${saknas.join(", ")}`);
});

test("en vara utan förpackningsrad är en styckvara - annars ljuger fallbacken", () => {
  // `PACKAGE_INFO[namn]?.unit || "st"` och `?.amount || 1` är tysta svar,
  // inte fel. De är RÄTT svar för en styckvara som köps i ettor, och fel för
  // allt annat: en gramvara utan rad blir plötsligt "1 st".
  //
  // Purjolök är den enda varan som saknar rad idag, och den begärs som
  // [0.5, "st"] - fallbacken säger alltså samma sak som en riktig rad skulle
  // ha gjort. Testet står här för att nästa vara som glöms bort inte ska
  // kunna vara en gramvara.
  const utanRad = ingredienser.filter(namn => !PACKAGE_INFO[namn]);
  for (const namn of utanRad) {
    for (const [receptId, rader] of Object.entries(RECIPE_QUANTITIES)) {
      if (!rader[namn]) continue;
      assert.equal(rader[namn][1], "st",
                   `${namn} saknar PACKAGE_INFO men begärs i ${receptId} som ${rader[namn].join(" ")}`);
    }
  }
});

test("förpackningsraderna har en mängd och en enhet appen känner igen", () => {
  for (const [namn, rad] of Object.entries(PACKAGE_INFO)) {
    assert.ok(rad.amount > 0, `${namn} har ingen förpackningsmängd`);
    assert.ok(["g", "ml", "st"].includes(rad.unit), `${namn} har okänd enhet ${rad.unit}`);
  }
});

test("prislistans rader är fullständiga - namn, märke, storlek och ett pris", () => {
  for (const [nyckel, rad] of Object.entries(PRODUCT_CATALOG)) {
    for (const fält of ["namn", "marke", "storlek"]) {
      assert.ok(rad[fält], `${nyckel} saknar ${fält}`);
    }
    assert.ok(typeof rad.pris === "number" && rad.pris > 0, `${nyckel} saknar pris`);
  }
});

test("ingen receptbeskrivning utan recept att beskriva", () => {
  // RECIPE_DETAILS är text för de LOKALA recepten. En nyckel som inte finns
  // i RECIPE_QUANTITIES är text som aldrig visas för någon.
  const foraldralosa = Object.keys(RECIPE_DETAILS).filter(id => !RECIPE_QUANTITIES[id]);
  assert.deepEqual(foraldralosa, [], `beskrivningar utan recept: ${foraldralosa.join(", ")}`);
});
