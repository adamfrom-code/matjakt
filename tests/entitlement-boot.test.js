// AM1: boot, inloggning och uppvaknande delar EN spärr mot /api/entitlements.
//
// Mätt i webbläsaren mot dev-servern: appens första sekund skickade
// /api/entitlements två gånger - modulens sista rad (boot) och refreshUser()
// (kontot) anropade fetchEntitlements() var för sig, innan något av dem
// svarat. J4:s spärr (createEntitlementRefresh) fanns, men bara uppvaknandet
// gick genom den; boot och inloggning gick förbi.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createEntitlementRefresh } from "../frontend/app/src/services/entitlement-refresh.js";

const rot = new URL("..", import.meta.url);
const appJs = readFileSync(new URL("frontend/app/app.js", rot), "utf8");

function fejk() {
  const calls = [];
  let clock = 1_000_000;
  let settle;
  const refresher = createEntitlementRefresh({
    refresh: () => { calls.push(clock); return new Promise(r => { settle = r; }); },
    now: () => clock,
  });
  return { refresher, calls, tick: ms => { clock += ms; }, svara: () => settle && settle() };
}

test("AM1: två refreshNow() i samma sekund ger ETT anrop", async () => {
  const { refresher, calls, svara } = fejk();
  const a = refresher.refreshNow();
  const b = refresher.refreshNow();
  // run() lägger refresh() i en mikrotask (J4) - töm den innan räkningen,
  // annars räknar testet noll och säger fel sak om rätt beteende.
  await Promise.resolve();
  assert.equal(calls.length, 1, "andra anropet ska dela det första");
  assert.equal(a, b, "samma löfte tillbaka till båda");
  svara(); await a;
});

test("AM1: refreshNow() och ett uppvaknande delar samma anrop", async () => {
  const { refresher, calls, tick, svara } = fejk();
  tick(120_000);                       // spärren har löpt ut - uppvaknandet VILL hämta
  const boot = refresher.refreshNow();
  const vaknar = refresher.onResume();
  await Promise.resolve();
  // Det som spelar roll: ETT anrop. onResume() svarar null när spärren
  // inte längre är gammal (refreshNow stämplade nyss) - det är J4:s
  // kontrakt, inte ett fel - eller det delade löftet om run() hann först.
  assert.equal(calls.length, 1, "uppvaknandet startade ett andra anrop");
  assert.ok(vaknar === null || vaknar === boot);
  svara(); await boot;
});

test("AM1: efter svaret får nästa refreshNow() hämta igen", async () => {
  const { refresher, calls, svara } = fejk();
  const a = refresher.refreshNow(); await Promise.resolve(); svara(); await a;
  refresher.refreshNow(); await Promise.resolve();
  assert.equal(calls.length, 2, "spärren gäller anrop i luften, inte för alltid");
});

test("AM1: app.js hämtar aldrig entitlementen förbi spärren", () => {
  // Varje väg in ska vara refreshNow(); fetchEntitlements() får bara
  // finnas som callbacken spärren äger, och som sin egen definition.
  const träffar = [...appJs.matchAll(/^[ \t]*fetchEntitlements\(\);?\s*$/gm)];
  assert.deepEqual(träffar.map(m => m[0].trim()), [],
    "direkta anrop till fetchEntitlements() i app.js - de går förbi spärren");
  assert.match(appJs, /refresh: fetchEntitlements/, "spärren ska äga hämtningen");
  assert.ok((appJs.match(/entitlementRefresh\.refreshNow\(\)/g) || []).length >= 2,
    "boot och refreshUser ska gå genom refreshNow()");
});
