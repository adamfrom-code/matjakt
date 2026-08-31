import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");

function functionBody(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} finns inte i app.js`);
  // Far enough to cover the whole short function, not so far it reaches the
  // next one.
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}") { depth--; if (depth === 0) return source.slice(start, i + 1); }
  }
  throw new Error(`Kunde inte läsa slut på ${name}`);
}

test("hasPremium anropar inte sig själv", () => {
  // A blanket search-and-replace of "Boolean(state.user?.premium)" once
  // rewrote hasPremium's OWN body into `return hasPremium() || ...`. Every
  // render that touched premium then threw RangeError and died silently,
  // leaving a frozen UI that looked like a caching problem for a while.
  const body = functionBody("hasPremium");
  assert.ok(!/return\s+hasPremium\s*\(/.test(body),
    "hasPremium får inte anropa sig själv - det är oändlig rekursion");
});

test("hasPremium läser fortfarande det riktiga kontots premiumflagga", () => {
  const body = functionBody("hasPremium");
  assert.match(body, /state\.user\?\.premium/,
    "ett riktigt Premium-konto måste fortfarande ge Premium");
});

test("dev-luckan kräver en loopback-värd", () => {
  // The guarantee that makes this safe to ship: production is
  // https://matjakt.store, which is not a loopback host, so the switch is
  // dead there whatever anyone puts in localStorage.
  const body = functionBody("devPremiumEnabled");
  assert.match(body, /isLoopbackHost\(\)/);
  const loopback = functionBody("isLoopbackHost");
  assert.match(loopback, /location\.hostname/);
  for (const host of ["localhost", "127.0.0.1"]) {
    assert.ok(loopback.includes(host), `${host} ska räknas som loopback`);
  }
  assert.ok(!/matjakt\.store/.test(loopback),
    "produktionsvärden får aldrig räknas som loopback");
});

test("varje premiumkontroll i UI:t går genom hasPremium", () => {
  // One entry point, so the dev switch (and any future change to what
  // Premium means) cannot be half-applied across call sites.
  const raw = [...source.matchAll(/state\.user\?\.premium/g)];
  assert.equal(raw.length, 1,
    "state.user?.premium ska bara läsas på ett ställe: inuti hasPremium()");
});
