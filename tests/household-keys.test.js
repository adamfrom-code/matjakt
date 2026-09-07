// Klientens halva av nyckelkontraktet. Serverns halva ligger i
// backend/tests/test_household_store.py (samma fixtur).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { foldName, shoppingKey } from "../frontend/app/src/services/household-state.js";

const fixture = JSON.parse(readFileSync(new URL("fixtures/household-keys.json", import.meta.url), "utf8"));

test("klientens radnyckel följer den gemensamma tabellen", () => {
  for (const [name, expected] of Object.entries(fixture.keys)) {
    assert.equal(shoppingKey(name), expected, `nyckeln för ${JSON.stringify(name)} ändrades`);
  }
});

test("inköpslistan nycklas på namn - aldrig på GTIN", () => {
  // Veckans rader läggs in utan produktdata, så servern lagrar dem
  // namn-nycklade. En gtin-nyckel härifrån gör raden omöjlig att bocka av.
  assert.equal(shoppingKey("Mjölk"), "name:mjolk");
  assert.ok(!shoppingKey("Mjölk").startsWith("gtin:"));
});

test("vikningen tål versaler, diakriter och extra blanksteg", () => {
  assert.equal(foldName("  ÄGG  "), "agg");
  assert.equal(foldName("Crème   fraiche"), "creme fraiche");
  assert.equal(foldName(null), "");
  assert.equal(shoppingKey("Röd Paprika"), shoppingKey("röd  paprika"));
});
