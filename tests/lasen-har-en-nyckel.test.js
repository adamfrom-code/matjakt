// ---------------------------------------------------------------------------
// J6: ETT LÅS I KLIENTEN MÅSTE NAMNGE EN NYCKEL I AFFÄRSMODELLEN
//
// G10 ritade ordet "Premium" på de fem avsiktsknapparna i bytesarket och lät
// `swapIntentLocked()` fråga `hasPremium()` rakt av. Funktionen fick aldrig
// en rad i `FEATURES`. Den sålde alltså något som affärsmodellen inte visste
// fanns - och eftersom modellen är det enda alla andra delar frågar, föll
// tre skydd samtidigt, alla tysta:
//
//   * J1:s grindlista härleder sin mängd ur FEATURES. En funktion utan
//     nyckel kan per definition inte saknas en serverkontroll, så
//     `unguarded_premium_features()` förblev tom och grön.
//   * J2:s och I8:s premiumtabeller kräver att varje rad pekar ut en nyckel
//     och prövas mot `allowed(FREE, nyckel)`. En funktion utan nyckel får
//     ingen rad - avsikterna gick alltså inte att sälja någonstans.
//   * `/api/entitlements` svarar `{name: allowed(plan, name) for name in
//     FEATURES}`. En funktion utan nyckel nämns inte i svaret, så klienten
//     kunde inte fråga ens om den velat.
//
// DET HÄR TESTET PRÖVAR FORMEN, INTE PRISET.
// Det säger ingenting om huruvida avsikterna ska vara gratis eller Premium -
// det är ett affärsbeslut och det bor i features.py. Det säger att beslutet
// måste FINNAS där, och att klienten måste läsa det i stället för att bära
// en andra kopia av affärsmodellen. Sätts nyckeln till Premium faller J1:s
// acceptanstest tills funktionen fått en riktig serverkontroll - och det är
// precis den kopplingen som saknades när G10 gick in.
//
// SVEPET MÅSTE HITTA NÅGOT.
// En regex som inte matchar ger en tom mängd, och ett test mot en tom mängd
// är grönt för evigt. Varje svep nedan kräver därför träffar, och undantags-
// listan granskas åt båda hållen: den får inte innehålla en nyckel (då vore
// den en väg runt regeln) och den får inte innehålla något som inte längre
// står i koden (då hade den vuxit till en sopgrop).
// ---------------------------------------------------------------------------

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import test from "node:test";
import { läsFeatures } from "./fixtures/affarsmodell.mjs";

const ROT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

const FUNKTIONER = läsFeatures();

/** Varje .js-fil i klienten, som [sökväg, innehåll]. */
function klientfiler() {
  const filer = [];
  const gå = (relativ) => {
    for (const post of readdirSync(ROT + relativ)) {
      const sökväg = `${relativ}/${post}`;
      if (statSync(ROT + sökväg).isDirectory()) gå(sökväg);
      else if (post.endsWith(".js")) filer.push([sökväg, readFileSync(ROT + sökväg, "utf8")]);
    }
  };
  gå("frontend/app/src");
  filer.push(["frontend/app/app.js", readFileSync(ROT + "frontend/app/app.js", "utf8")]);
  if (filer.length < 5) throw new Error(`hittade bara ${filer.length} klientfiler - svepet letar fel`);
  return filer;
}

const KLIENTEN = klientfiler();

/** Alla `mönster`-träffar i klienten som Map<namn, sökvägar>. */
function träffar(mönster) {
  const funna = new Map();
  for (const [sökväg, källa] of KLIENTEN) {
    for (const m of källa.matchAll(mönster)) {
      if (!funna.has(m[1])) funna.set(m[1], []);
      funna.get(m[1]).push(sökväg);
    }
  }
  return funna;
}

// Betalväggen öppnas ibland utan att något är låst: "Prenumeration" i
// Inställningar är en VÄG till erbjudandet, inte en grind framför en
// funktion. De skälen står här, ett i taget och med sin motivering. Listan
// granskas av testet längst ned - den kan varken gömma en riktig funktion
// eller växa av gammal vana.
const INTE_EN_FUNKTION = new Map([
  ["settings", "Inställningar → Prenumeration för den som inte har Premium. "
    + "Öppnar erbjudandet; ingenting är låst bakom raden."],
]);

// ---------------------------------------------------------------------------
// REGELN
// ---------------------------------------------------------------------------

test("varje betalvägg klienten öppnar namnger en funktion i FEATURES", () => {
  const skäl = träffar(/openPaywall\("([a-z_0-9]+)"\)/g);
  assert.ok(skäl.size, "svepet hittade ingen openPaywall(\"...\") alls - då granskas ingenting");
  for (const [namn, sökvägar] of skäl) {
    if (INTE_EN_FUNKTION.has(namn)) continue;
    assert.ok(FUNKTIONER.has(namn),
      `openPaywall("${namn}") i ${sökvägar.join(", ")} pekar inte ut någon rad i FEATURES.\n`
      + "  Ett lås utan nyckel kan varken grindas på servern (J1) eller säljas i en tabell (J2/I8).\n"
      + `  Nycklarna som finns: ${[...FUNKTIONER.keys()].join(", ")}`);
  }
});

test("varje can()- och feature:-literal i klienten namnger en funktion i FEATURES", () => {
  // `can(plan.feature)` slår upp nyckeln i PLAN_TYPES, så literalerna står
  // där i stället. Båda formerna är samma sorts påstående om modellen och
  // granskas därför likadant.
  const literaler = new Map([...träffar(/\bcan\("([a-z_0-9]+)"\)/g),
    ...träffar(/\bfeature:\s*"([a-z_0-9]+)"/g)]);
  assert.ok(literaler.size, "svepet hittade ingen funktionsliteral alls - då granskas ingenting");
  for (const [namn, sökvägar] of literaler) {
    assert.ok(FUNKTIONER.has(namn),
      `"${namn}" i ${sökvägar.join(", ")} finns inte i FEATURES - klienten frågar om en `
      + "funktion affärsmodellen aldrig hört talas om, och får alltid ja");
  }
});

test("bytets avsikter har en nyckel", () => {
  // Den nyckel som saknades. Står den här kan J1 kräva en serverkontroll om
  // den någonsin blir Premium, och tabellerna kan sälja den om den är det.
  assert.ok(FUNKTIONER.has("swap_intents"),
    "swap_intents finns inte i FEATURES - avsikterna i bytesarket säljs fortfarande "
    + "av en klient som är ensam om att veta att de finns");
});

test("låset på avsikten frågar modellen, inte planen", () => {
  const app = readFileSync(ROT + "frontend/app/app.js", "utf8");
  const rad = /const swapIntentLocked = [^\n]*/.exec(app);
  assert.ok(rad, "swapIntentLocked finns inte längre - har låset bytt form?");
  assert.match(rad[0], /can\("swap_intents"\)/,
    "swapIntentLocked läser inte entitlements-svaret. Går låset via hasPremium() bär "
    + "klienten en andra affärsmodell, och en flytt i features.py når aldrig fram");
  assert.ok(!/hasPremium\(\)/.test(rad[0]),
    "swapIntentLocked frågar fortfarande hasPremium() direkt - då avgör planen och inte nyckeln");
});

// ---------------------------------------------------------------------------
// ...OCH UNDANTAGEN ÄR INGEN VÄG RUNT DEN
// ---------------------------------------------------------------------------

test("undantagslistan kan varken gömma en funktion eller växa av gammal vana", () => {
  const skäl = träffar(/openPaywall\("([a-z_0-9]+)"\)/g);
  for (const [namn, motivering] of INTE_EN_FUNKTION) {
    assert.ok(!FUNKTIONER.has(namn),
      `"${namn}" står som undantag men ÄR en funktion i FEATURES - undantaget är en väg `
      + "runt granskningen och ska bort");
    assert.ok(skäl.has(namn),
      `"${namn}" står som undantag men öppnar ingen betalvägg längre - ta bort raden`);
    assert.ok(motivering.length > 30, `undantaget "${namn}" saknar en läsbar motivering`);
  }
});

test("läsaren kastar hellre än granskar en tom modell", () => {
  assert.throws(() => läsFeatures("inget dictblock alls\n"), /FEATURES finns inte/);
  assert.throws(() => läsFeatures('\nFEATURES = {\n    "x": {"free": Kanske},\n}\n'),
    /gick att läsa/, "en rad i okänd form ska falla, inte försvinna");
});
