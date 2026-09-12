// Native-lagret och webmanifestet bär appens färg INNAN appen hunnit rita.
//
// G1 bytte paletten i styles.css genom ett aliasskikt, och hela appen bytte
// utseende. Fyra ställen följde inte med, eftersom de inte är CSS:
//
//   capacitor.config.json  ios/android backgroundColor  #f6f7f4  (gammal creme)
//   index.html             <meta name="theme-color">     #f6f7f4
//   manifest.json          background_color              #f6f7f4
//   manifest.json          theme_color                   #146c43  (gamla gröna)
//
// Det sista var värst: theme_color är statusfältets färg i en installerad
// app, så appen hade grönt statusfält ovanför en pappersvit yta - i just den
// gröna nyans design D tog bort helt. Och backgroundColor är det native-appen
// blinkar till innan webbvyn hunnit måla, alltså användarens allra första
// intryck.
//
// Testet läser paletten ur DESIGNSYSTEM-D.md i stället för att upprepa den:
// byts --paper där ska det här failar, inte tyst gå isär.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const läs = p => readFileSync(join(root, p), "utf8");

function papperUrDesignsystemet() {
  const m = /--paper:\s*(#[0-9A-Fa-f]{6})/.exec(läs("frontend/app/styles.css"));
  assert.ok(m, "--paper hittades inte i styles.css");
  return m[1].toUpperCase();
}

test("capacitor backgroundColor är designsystemets papper, inte den gamla cremen", () => {
  const papper = papperUrDesignsystemet();
  const cfg = JSON.parse(läs("capacitor.config.json"));
  for (const plattform of ["ios", "android"]) {
    assert.equal((cfg[plattform]?.backgroundColor || "").toUpperCase(), papper,
      `${plattform}: appen blinkar till i fel färg innan webbvyn målat`);
  }
});

test("manifestets background_color och theme_color är papper", () => {
  const papper = papperUrDesignsystemet();
  const m = JSON.parse(läs("frontend/app/manifest.json"));
  assert.equal((m.background_color || "").toUpperCase(), papper);
  assert.equal((m.theme_color || "").toUpperCase(), papper,
    "theme_color är statusfältets färg i en installerad app");
});

test("index.html theme-color följer manifestet", () => {
  const papper = papperUrDesignsystemet();
  const m = /<meta name="theme-color" content="(#[0-9A-Fa-f]{6})">/.exec(läs("frontend/app/index.html"));
  assert.ok(m, "theme-color-metataggen saknas");
  assert.equal(m[1].toUpperCase(), papper);
});

test("den gamla gröna finns inte kvar i något av de fyra ställena", () => {
  // #146c43 var accentgrönt före design D. Ett enda kvarglömt ställe räcker
  // för att en användare ska se det - statusfältet syns på varje skärm.
  for (const fil of ["capacitor.config.json", "frontend/app/manifest.json", "frontend/app/index.html"]) {
    const t = läs(fil).toLowerCase();
    assert.doesNotMatch(t, /#146c43/, `${fil} bär den gamla gröna`);
    assert.doesNotMatch(t, /#f6f7f4/, `${fil} bär den gamla cremen`);
  }
});
