// Funktionsflaggorna: av för alla, på per webbläsare - och okända namn kan
// inte slås på.
import test from "node:test";
import assert from "node:assert/strict";
import { FLAGGOR, flagga } from "../frontend/app/src/services/flaggor.js";

const minne = (json) => ({ getItem: () => json });

test("alla flaggor är av som standard", () => {
  for (const namn of Object.keys(FLAGGOR)) assert.equal(flagga(namn, { storage: minne(null), search: "" }), false, namn);
  assert.ok(Object.isFrozen(FLAGGOR));
});

test("en flagga slås på per webbläsare - lagring eller adress", () => {
  assert.equal(flagga("hushall.medlemmar", { storage: minne('{"hushall.medlemmar": true}'), search: "" }), true);
  assert.equal(flagga("hushall.medlemmar", { storage: minne('{"hushall.medlemmar": false}'), search: "" }), false);
  assert.equal(flagga("vecka.narvaro", { storage: minne(null), search: "?flagga=vecka.narvaro,hushall.medlemmar" }), true);
  assert.equal(flagga("vecka.rester", { storage: minne(null), search: "?flagga=vecka.narvaro" }), false);
});

test("okända namn och trasig lagring är alltid av", () => {
  assert.equal(flagga("finns.inte", { storage: minne('{"finns.inte": true}'), search: "?flagga=finns.inte" }), false);
  assert.equal(flagga("hushall.medlemmar", { storage: minne("{trasig json"), search: "" }), false);
  assert.equal(flagga("hushall.medlemmar", { storage: { getItem: () => { throw new Error("privat läge"); } }, search: "" }), false);
});
