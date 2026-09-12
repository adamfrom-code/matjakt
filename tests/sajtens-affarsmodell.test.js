// ---------------------------------------------------------------------------
// I8: DET SAJTEN SÄLJER ÄR DET KODEN TAR BETALT FÖR
//
// J2 rev ut premiumlistan inne i appen därför att den sålde "Laga med det du
// redan har hemma" ett dygn efter att J3 gjort funktionen gratis. Samma text
// stod kvar på matjakt.store — och där är den värre, för landningssidan är
// det FÖRSTA en besökare läser och det enda en betalande läste innan hon
// betalade. En gratisruta som säger "fyra middagar" när gränsen är fem säljer
// dessutom bort produkten: den underdriver det man får.
//
// FELET ÄR INTE ORDEN, DET ÄR ATT DE ÄR HANDSKRIVNA.
// Listorna står som <li> i frontend/index.html bredvid en kodsanning i
// backend/services/accounts/features.py. Två texter om samma sak, och bara
// den ena kördes. J3 flyttade gränsen åt båda hållen och ingen text följde
// med, för ingenting tvingade den. En ny handskriven text löser ingenting —
// det som behövs är att texten GRANSKAS mot modellen.
//
// EN PARSER SOM TIGER ÄR VÄRRE ÄN INGEN PARSER.
// Node kan inte importera en .py, så modellen läses här som text. En regex
// som inte hittar något returnerar en tom mängd, och ett test mot en tom
// mängd är grönt för evigt. Därför kastar varje läsare nedan hellre än
// returnerar tomt, läsFeatures() räknar raderna i blocket mot antalet den
// lyckades tolka, och SÄLJFRASER måste täcka VARJE nyckel i FEATURES — en ny
// funktion kan inte tyst hamna utanför granskningen.
//
// Granskningen går åt ett håll med flit: premiumlistan får inte nämna något
// som modellen säger är gratis. Det omvända — att varje premiumfunktion
// MÅSTE stå i listan — är marknadsföring, inte sanning, och en lista får
// utelämna ett argument utan att ljuga.
// ---------------------------------------------------------------------------

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const ROT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const läs = (relativ) => readFileSync(ROT + relativ, "utf8");

const FEATURES_PY = "backend/services/accounts/features.py";
const INDEX = "frontend/index.html";
const VILLKOR = "frontend/anvandarvillkor.html";

// --- Modellen, läst som data ------------------------------------------------

/** Tar bort #-kommentarer men behåller radbrytningarna, så radnummer står kvar. */
function utanKommentarer(källa) {
  return källa.split("\n").map((rad) => rad.replace(/(^|\s)#.*$/, "$1")).join("\n");
}

/** Blocket mellan `NAMN = {` och den avslutande `}` i kolumn noll. */
function dictBlock(källa, namn) {
  const start = källa.indexOf(`\n${namn} = {`);
  if (start < 0) throw new Error(`${namn} finns inte i ${FEATURES_PY} - har modellen döpts om?`);
  const från = källa.indexOf("{", start) + 1;
  const till = källa.indexOf("\n}", från);
  if (till < 0) throw new Error(`${namn} har ingen avslutande } i kolumn noll`);
  return källa.slice(från, till);
}

/**
 * FEATURES som Map<nyckel, fri>. `fri` är exakt det `allowed(FREE, nyckel)`
 * svarar: True i modellen betyder att gratisplanen har funktionen.
 */
export function läsFeatures(källa = läs(FEATURES_PY)) {
  const block = utanKommentarer(dictBlock(källa, "FEATURES"));
  const funktioner = new Map();
  for (const m of block.matchAll(/"([a-z_0-9]+)"\s*:\s*\{\s*"free"\s*:\s*(True|False)\s*\}/g)) {
    funktioner.set(m[1], m[2] === "True");
  }
  const rader = block.split("\n").filter((rad) => /^\s*"[a-z_0-9]+"\s*:/.test(rad));
  if (rader.length !== funktioner.size) {
    throw new Error(`FEATURES har ${rader.length} rader men bara ${funktioner.size} gick att läsa `
      + "- en rad står i en form parsern inte känner igen och skulle granskas bort tyst");
  }
  if (!funktioner.size) throw new Error("FEATURES lästes som tom - då granskar testet ingenting");
  return funktioner;
}

/** Ett `NAMN = <heltal>` på modulnivå. Saknas det är det ett fel, inte en nolla. */
export function läsKonstant(namn, källa = läs(FEATURES_PY)) {
  const m = new RegExp(`^${namn}\\s*=\\s*(-?\\d+)\\s*$`, "m").exec(utanKommentarer(källa));
  if (!m) throw new Error(`${namn} finns inte som heltal på modulnivå i ${FEATURES_PY}`);
  return Number(m[1]);
}

const FUNKTIONER = läsFeatures();
const TAL = Object.fromEntries(
  ["FREE_MAX_DINNERS", "PREMIUM_MAX_DINNERS", "FREE_MAX_HOUSEHOLD_MEMBERS",
    "PREMIUM_MAX_HOUSEHOLD_MEMBERS", "FREE_SAVINGS_WEEKS", "PREMIUM_SAVINGS_WEEKS"]
    .map((namn) => [namn, läsKonstant(namn)]));

// Sajten skriver tal med bokstäver ("fem middagar"), inte siffror. Modellen
// skriver siffror. Det här är bron - och den är avsiktligt kort: blir gränsen
// ett tal utan ett svenskt ord här faller testet i stället för att tiga.
const ORD = ["noll", "en", "två", "tre", "fyra", "fem", "sex",
  "sju", "åtta", "nio", "tio", "elva", "tolv"];
function ord(tal) {
  if (!ORD[tal]) throw new Error(`${tal} saknar ord i ORD - lägg till det, gissa inte`);
  return ORD[tal];
}

// --- Vad en mening på sajten betyder i modellen -----------------------------

/**
 * Frasen en säljtext skulle använda om den sålde funktionen. Granskningen är
 * ordagrant "nämner premiumlistan något av det här?", så fraserna ska vara de
 * ord en copywriter faktiskt skriver - inte funktionsnycklarna.
 *
 * Varje nyckel i FEATURES MÅSTE stå här (testet längst ned kräver det). En
 * funktion utan igenkännbar fras är en funktion granskningen inte ser.
 */
const VECKOTYP = [/veckotyp/i, /veckoteman/i];
const SÄLJFRASER = new Map([
  ["standard_week", VECKOTYP],
  ["family_week", [...VECKOTYP, /familjevecka/i]],
  ["budget_week", [...VECKOTYP, /budgetvecka/i]],
  ["training_week", [...VECKOTYP, /träningsvecka/i]],
  ["bulk_week", [...VECKOTYP, /bulkvecka/i]],
  ["quick_week", [...VECKOTYP, /snabbvecka/i]],
  ["vegetarian_week", [...VECKOTYP, /vegetarisk/i]],
  ["balanced_week", [...VECKOTYP, /balanserad vecka/i]],
  ["seven_dinners", [new RegExp(`${ord(TAL.PREMIUM_MAX_DINNERS)} middagar`, "i")]],
  ["cheapest_store_price", [/billigaste butiken/i, /billigaste kvalificerade butiken/i]],
  ["cheapest_store_basket", [/billigaste butikens (inköpslista|lista)/i]],
  ["all_store_prices", [/alla butiker/i, /alla kvalificerade butikers priser/i, /samtliga butiker/i]],
  ["all_store_baskets", [/butikskorgar/i, /inköpslistor hos alla/i]],
  ["store_comparison", [/jämförelse/i, /jämför/i]],
  ["live_prices", [/färska priser/i, /live(-| )priser/i, /priser per vara/i]],
  ["recipe_search", [/receptsök/i, /receptbank/i]],
  ["advanced_nutrition", [/näringsmål/i, /näringsfilter/i, /kcal/i, /proteinfilter/i]],
  ["meal_prep", [/meal ?prep/i, /matlåd/i]],
  ["basic_pantry", [/skafferi/i]],
  ["full_pantry", [/har hemma/i, /har jag hemma/i, /har du hemma/i, /fullt skafferi/i]],
  ["favorites", [/favoriter/i]],
  ["household_sharing", [/hushåll/i, /dela.{0,12}(vecka|lista)/i]],
  ["savings_history", [/sparhistorik/i, /månadsrapport/i, /sparsumma/i]],
]);

// --- Sidorna ----------------------------------------------------------------

/** Text utan markup, med hårda mellanslag och radbrytningar normaliserade. */
function ren(html) {
  return html.replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|\u00a0/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

/** De två prisrutorna på landningssidan, var för sig. */
function planrutor(html = läs(INDEX)) {
  const rutor = [...html.matchAll(/<article class="site-plan">([\s\S]*?)<\/article>/g)]
    .map((m) => m[1]);
  if (rutor.length !== 2) {
    throw new Error(`förväntade två prisrutor i ${INDEX}, hittade ${rutor.length}`);
  }
  const gratis = rutor.find((r) => /<h3>Gratis för alltid<\/h3>/.test(r));
  const premium = rutor.find((r) => /<h3>Premium<\/h3>/.test(r));
  if (!gratis || !premium) {
    throw new Error("hittade inte båda rubrikerna - rutorna kan inte skiljas åt");
  }
  return { gratis, premium };
}

/** Punkterna i en ruta, som ren text. En tom lista är ett fel, inte noll fel. */
function punkter(block) {
  const rader = [...block.matchAll(/<li>([\s\S]*?)<\/li>/g)].map((m) => ren(m[1]));
  if (!rader.length) throw new Error("rutan har inga <li> - då granskas ingenting");
  return rader;
}

/** Premiumpunkten i användarvillkoren: den <li> som nämner vad Premium låser upp. */
function villkorensPremiumrad(html = läs(VILLKOR)) {
  const rader = [...html.matchAll(/<li>([\s\S]*?)<\/li>/g)].map((m) => ren(m[1]));
  const träffar = rader.filter((r) => /^Premium kostar/.test(r));
  if (träffar.length !== 1) {
    throw new Error(`förväntade en "Premium kostar"-rad i ${VILLKOR}, hittade ${träffar.length}`);
  }
  return träffar[0];
}

/** FAQPage-schemat som Map<fråga, svar>. Går JSON:en inte att tolka är det ett fel. */
function faqSchema(html = läs(INDEX)) {
  const skript = [...html.matchAll(
    /<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  if (!skript.length) throw new Error(`${INDEX} har ingen JSON-LD alls`);
  for (const rå of skript) {
    const data = JSON.parse(rå); // en trasig JSON-LD ska falla här, inte tyst hoppas över
    if (data["@type"] !== "FAQPage") continue;
    const poster = data.mainEntity ?? [];
    if (!poster.length) throw new Error("FAQPage-schemat har inga frågor");
    return new Map(poster.map((f) => [f.name, f.acceptedAnswer.text]));
  }
  throw new Error("hittade ingen FAQPage i JSON-LD - schemat granskas då inte");
}

/** Frågorna och svaren som de står i brödtexten. */
function faqBrödtext(html = läs(INDEX)) {
  const poster = [...html.matchAll(
    /<summary>([\s\S]*?)<\/summary>\s*<p>([\s\S]*?)<\/p>/g)];
  if (!poster.length) throw new Error(`${INDEX} har inga <details> med svar`);
  return new Map(poster.map((m) => [ren(m[1]), ren(m[2])]));
}

// --- Granskningen -----------------------------------------------------------

test("premiumlistan på landningssidan säljer inget som modellen ger gratis", () => {
  const text = punkter(planrutor().premium).join(" | ");
  for (const [nyckel, fri] of FUNKTIONER) {
    if (!fri) continue; // premium får säljas som premium
    for (const fras of SÄLJFRASER.get(nyckel) ?? []) {
      assert.ok(!fras.test(text),
        `prisrutan säljer ${nyckel} (${fras}) som Premium - FEATURES säger att den är gratis.\n`
        + `  Listan: ${text}`);
    }
  }
});

test("användarvillkoren säljer inget som modellen ger gratis", () => {
  // Villkoren är det dokument kunden formellt köper enligt. Står en gratis
  // funktion bland det Premium "låser upp" är det ett avtalsvillkor som inte
  // stämmer, inte en slarvig rubrik.
  const rad = villkorensPremiumrad();
  for (const [nyckel, fri] of FUNKTIONER) {
    if (!fri) continue;
    for (const fras of SÄLJFRASER.get(nyckel) ?? []) {
      assert.ok(!fras.test(rad),
        `användarvillkoren låser upp ${nyckel} (${fras}) med Premium - den är gratis.\n`
        + `  Raden: ${rad}`);
    }
  }
});

test("middagstalet i gratisrutan är FREE_MAX_DINNERS", () => {
  const { gratis } = planrutor();
  const m = /Upp till ([a-zåäö]+) middagar/i.exec(ren(gratis));
  assert.ok(m, "gratisrutan säger inte hur många middagar som ingår");
  assert.equal(m[1].toLowerCase(), ord(TAL.FREE_MAX_DINNERS),
    `sajten lovar "${m[1]} middagar", modellen ger ${TAL.FREE_MAX_DINNERS}`);
});

test("premiumrutan lovar PREMIUM_MAX_DINNERS middagar", () => {
  const text = punkter(planrutor().premium).join(" | ");
  assert.match(text, new RegExp(`${ord(TAL.PREMIUM_MAX_DINNERS)} middagar`, "i"),
    `premiumrutan säger inte "${ord(TAL.PREMIUM_MAX_DINNERS)} middagar"`);
});

test("gratisrutan skriver ut de två gränser som faktiskt finns", () => {
  // J3 flyttade hushållet och sparhistoriken UPP. En gratisruta som räknar
  // upp allt man får och tiger om de två sakerna som tar slut är inte
  // osann, men den är den sortens tystnad som gör en uppgradering till en
  // överraskning i stället för ett val.
  //
  // Mönstren byggs ur TALEN, inte ur copyn: ändras gränsen i modellen slutar
  // de matcha och raden måste skrivas om. Att bara leta efter ordet "hushåll"
  // vore verkningslöst - det står redan i första punkten, om något helt annat.
  const text = punkter(planrutor().gratis).join(" | ");
  // Inte \\b: i JS bygger den på [A-Za-z0-9_], så \"två,\" saknar gräns efter å.
  const hushåll = new RegExp(
    `hushåll för ${ord(TAL.FREE_MAX_HOUSEHOLD_MEMBERS)}(?![a-zåäö])`, "i");
  assert.match(text, hushåll,
    `gratisrutan skriver inte ut hushållsgränsen (${TAL.FREE_MAX_HOUSEHOLD_MEMBERS} personer)`);
  const sparveckor = TAL.FREE_SAVINGS_WEEKS === 1
    ? /sparsumman för (den )?senaste veckan/i
    : new RegExp(`${ord(TAL.FREE_SAVINGS_WEEKS)} veckors? spar`, "i");
  assert.match(text, sparveckor,
    `gratisrutan skriver inte ut sparhistorikens gräns (${TAL.FREE_SAVINGS_WEEKS} vecka bakåt)`);
});

test("FAQ-svaret om priset står ordagrant lika i brödtext och FAQPage-schema", () => {
  // Samma sträng på två ställen i samma fil är en kopia som glider isär vid
  // första rättelsen - och den som glider är schemat, för det syns inte i
  // webbläsaren. Google läser det ändå.
  const brödtext = faqBrödtext();
  const schema = faqSchema();
  assert.deepEqual([...schema.keys()], [...brödtext.keys()],
    "FAQPage-schemat och brödtexten har inte samma frågor i samma ordning");
  for (const [fråga, svar] of brödtext) {
    assert.equal(schema.get(fråga), svar,
      `svaret på "${fråga}" skiljer sig mellan brödtext och JSON-LD`);
  }
});

test("prissvaret i FAQ säljer inget som modellen ger gratis", () => {
  const svar = faqBrödtext().get("Vad kostar det?");
  assert.ok(svar, "FAQ har ingen fråga \"Vad kostar det?\"");
  // Bara meningen om vad Premium öppnar granskas; meningen före den handlar
  // om vad som är gratis och SKA nämna gratisfunktioner.
  const mening = svar.split(/(?=Premium kostar)/).find((d) => d.startsWith("Premium kostar"));
  assert.ok(mening, "FAQ-svaret säger inte vad Premium kostar och öppnar");
  for (const [nyckel, fri] of FUNKTIONER) {
    if (!fri) continue;
    for (const fras of SÄLJFRASER.get(nyckel) ?? []) {
      assert.ok(!fras.test(mening),
        `FAQ säger att Premium öppnar ${nyckel} (${fras}) - den är gratis.\n  ${mening}`);
    }
  }
});

test("priserna på sajten är samma tal som modellen", () => {
  // 59 och 399 ändras inte av det här paketet, men de står handskrivna på
  // sajten och i PRICING. Granskas de inte kan de glida isär nästa gång.
  const html = läs(INDEX);
  const källa = läs(FEATURES_PY);
  for (const [namn, mönster] of [["pricePerMonth", /(\d+)&nbsp;kr\/mån/],
    ["pricePerYear", /(\d+)&nbsp;kr\/år/]]) {
    const iModellen = new RegExp(`"${namn}"\\s*:\\s*(\\d+)`).exec(källa);
    assert.ok(iModellen, `PRICING saknar ${namn}`);
    const påSajten = mönster.exec(html);
    assert.ok(påSajten, `sajten saknar ett belopp som matchar ${mönster}`);
    assert.equal(påSajten[1], iModellen[1],
      `sajten säger ${påSajten[1]} kr, PRICING säger ${iModellen[1]} kr`);
  }
});

test("varje funktion i FEATURES har en säljfras att känna igen", () => {
  // Utan det här kan en ny funktionsnyckel läggas till i modellen, säljas på
  // sajten, och granskas av ingenting - grönt för evigt.
  for (const nyckel of FUNKTIONER.keys()) {
    assert.ok(SÄLJFRASER.has(nyckel),
      `${nyckel} saknas i SÄLJFRASER - granskningen skulle inte se den på sajten`);
  }
  for (const nyckel of SÄLJFRASER.keys()) {
    assert.ok(FUNKTIONER.has(nyckel),
      `${nyckel} finns i SÄLJFRASER men inte i FEATURES - fraslistan har blivit inaktuell`);
  }
});

test("läsaren kastar hellre än granskar en tom modell", () => {
  // Hela granskningens värde vilar på att modellen faktiskt lästes. Tre
  // former av tystnad, alla tre ska bli ett fel.
  assert.throws(() => läsFeatures("inget dictblock alls\n"), /FEATURES finns inte/);
  assert.throws(() => läsFeatures('\nFEATURES = {\n    "x": {"free": Kanske},\n}\n'),
    /gick att läsa/, "en rad i okänd form ska falla, inte försvinna");
  assert.throws(() => läsKonstant("FREE_MAX_DINNERS", "FREE_MAX_DINNERS = ungefär fem\n"),
    /finns inte som heltal/);
});
