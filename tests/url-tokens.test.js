import test from "node:test";
import assert from "node:assert/strict";
import { SENSITIVE_URL_PARAMS, takeUrlTokens } from "../frontend/app/src/services/url-tokens.js";

/** Ett minimalt window: adressraden och den replaceState som skriver om den. */
function fönster(href) {
  const win = {
    location: { get href() { return win._href; }, },
    _href: href,
    skrivningar: [],
    history: {
      replaceState(_state, _title, url) {
        win.skrivningar.push(url);
        win._href = new URL(url, win._href).href;
      },
    },
  };
  return win;
}

const sök = win => new URL(win._href).search;

test("reset plockas ut OCH försvinner ur adressen", () => {
  const win = fönster("https://matjakt.store/app/?reset=hemlig-token-123");
  assert.deepEqual(takeUrlTokens(win), { reset: "hemlig-token-123" });
  assert.equal(sök(win), "", `token kvar i adressen: ${win._href}`);
  assert.equal(new URL(win._href).pathname, "/app/");
});

test("verify behandlas likadant", () => {
  const win = fönster("https://matjakt.store/app/?verify=verifieringstoken");
  assert.deepEqual(takeUrlTokens(win), { verify: "verifieringstoken" });
  assert.equal(sök(win), "");
});

test("adressen skrivs om EN gång, med replaceState - token får inte gå att bläddra tillbaka till", () => {
  const win = fönster("https://matjakt.store/app/?reset=t&verify=v");
  assert.deepEqual(takeUrlTokens(win), { reset: "t", verify: "v" });
  assert.equal(win.skrivningar.length, 1, win.skrivningar);
});

test("resten av query-strängen rörs inte - recept, invite och billing behövs längre fram", () => {
  // Att svepa hela query-strängen (history.replaceState(null, "", location.pathname))
  // skulle ta med sig det delade receptet som var HELA anledningen till besöket.
  const win = fönster("https://matjakt.store/app/?recept=42&reset=hemlig&invite=abc#steg");
  assert.deepEqual(takeUrlTokens(win), { reset: "hemlig" });
  const kvar = new URL(win._href);
  assert.equal(kvar.searchParams.get("recept"), "42");
  assert.equal(kvar.searchParams.get("invite"), "abc");
  assert.equal(kvar.searchParams.get("reset"), null);
  assert.equal(kvar.hash, "#steg");
});

test("en tom parameter tas också bort, och räknas inte som ett token", () => {
  const win = fönster("https://matjakt.store/app/?reset=");
  assert.deepEqual(takeUrlTokens(win), {});
  assert.equal(sök(win), "");
});

test("utan token skrivs adressen inte om alls", () => {
  const win = fönster("https://matjakt.store/app/?recept=42");
  assert.deepEqual(takeUrlTokens(win), {});
  assert.deepEqual(win.skrivningar, []);
  assert.equal(sök(win), "?recept=42");
});

test("en webbläsare som vägrar skriva om historiken stoppar inte starten", () => {
  const win = fönster("https://matjakt.store/app/?reset=hemlig");
  win.history.replaceState = () => { throw new Error("SecurityError"); };
  assert.deepEqual(takeUrlTokens(win), { reset: "hemlig" });
});

test("listan är precis de två engångstoken som är hemligheter", () => {
  assert.deepEqual(SENSITIVE_URL_PARAMS, ["reset", "verify"]);
});
