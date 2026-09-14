// Affärsmodellen läst som DATA, direkt ur backend/services/accounts/features.py.
//
// J1 gjorde grindarna härledda ur FEATURES i stället för handskrivna, och J3
// flyttade sedan gränsen åt båda hållen utan att röra en enda grind. Samma
// disciplin ska gälla det som SÄLJS: premiumlistan i frontenden får inte vara
// en andra sanning bredvid features.py, den ska vara en projektion av den.
//
// Därför läser den här filen Python-källan i stället för att upprepa den.
// Node kan inte importera en .py, och en JSON-export vid sidan om vore precis
// den kopia som glider isär - det var så listan kunde sälja "Laga med det du
// redan har hemma" ett dygn efter att J3 gjort funktionen gratis.
//
// EN PARSER SOM TIGER ÄR VÄRRE ÄN INGEN PARSER.
// En regex som inte hittar något returnerar en tom mängd, och ett test mot en
// tom mängd är grönt för evigt. Varje läsare här kastar därför hellre än
// returnerar tomt, och läserFeatures() räknar dessutom raderna i blocket mot
// antalet den lyckades tolka: en rad i en form parsern inte känner igen får
// inte kunna försvinna tyst.

import { readFileSync } from "node:fs";

const ROT = new URL("../../", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

export const FEATURES_PY = "backend/services/accounts/features.py";
export const ACTIVATION_PY = "backend/services/billing/activation.py";

export function läsPython(relativ) {
  return readFileSync(ROT + relativ, "utf8");
}

/** Tar bort # -kommentarer men behåller radbrytningarna, så radnummer står kvar. */
function utanKommentarer(källa) {
  return källa.split("\n").map((rad) => rad.replace(/(^|\s)#.*$/, "$1")).join("\n");
}

/** Blocket mellan `NAMN = {` och den avslutande `}` i kolumn noll. */
function dictBlock(källa, namn) {
  const start = källa.indexOf(`\n${namn} = {`);
  if (start < 0) throw new Error(`${namn} finns inte i källan - har modellen döpts om?`);
  const från = källa.indexOf("{", start) + 1;
  const till = källa.indexOf("\n}", från);
  if (till < 0) throw new Error(`${namn} har ingen avslutande } i kolumn noll`);
  return källa.slice(från, till);
}

/**
 * FEATURES som Map<nyckel, fri>. `fri` är exakt det `allowed(FREE, nyckel)`
 * svarar: True i modellen betyder att gratisplanen har funktionen.
 */
export function läsFeatures(källa = läsPython(FEATURES_PY)) {
  const block = utanKommentarer(dictBlock(källa, "FEATURES"));
  const funktioner = new Map();
  for (const m of block.matchAll(/"([a-z_0-9]+)"\s*:\s*\{\s*"free"\s*:\s*(True|False)\s*\}/g)) {
    funktioner.set(m[1], m[2] === "True");
  }
  // Varje rad i blocket som över huvud taget nämner en nyckel MÅSTE ha tolkats.
  const rader = block.split("\n").filter((rad) => /^\s*"[a-z_0-9]+"\s*:/.test(rad));
  if (rader.length !== funktioner.size) {
    throw new Error(`FEATURES har ${rader.length} rader men bara ${funktioner.size} gick att läsa `
      + `- en rad står i en form parsern inte känner igen och skulle granskas bort tyst`);
  }
  if (!funktioner.size) throw new Error("FEATURES lästes som tom - då granskar testet ingenting");
  return funktioner;
}

/** Ett `NAMN = <heltal>` på modulnivå. Saknas det är det ett fel, inte en nolla. */
export function läsKonstant(namn, källa = läsPython(FEATURES_PY)) {
  const m = new RegExp(`^${namn}\\s*=\\s*(-?\\d+)\\s*$`, "m").exec(utanKommentarer(källa));
  if (!m) throw new Error(`${namn} finns inte som heltal på modulnivå`);
  return Number(m[1]);
}

/** PRICING: bara talen. Textsträngarna är marknadsföring, talen är priset. */
export function läsPriser(källa = läsPython(FEATURES_PY)) {
  const block = utanKommentarer(dictBlock(källa, "PRICING"));
  const tal = (namn) => {
    const m = new RegExp(`"${namn}"\\s*:\\s*(\\d+)`).exec(block);
    if (!m) throw new Error(`PRICING saknar ${namn}`);
    return Number(m[1]);
  };
  return { perMånad: tal("pricePerMonth"), perÅr: tal("pricePerYear") };
}

/**
 * Hela modellen i den form tabellens granskning vill ha den:
 * { funktioner: Map<nyckel, fri>, tal: {...}, priser: {...} }.
 */
export function läsAffärsmodell() {
  const källa = läsPython(FEATURES_PY);
  return {
    funktioner: läsFeatures(källa),
    tal: Object.fromEntries([
      "FREE_MAX_DINNERS", "PREMIUM_MAX_DINNERS",
      "FREE_MAX_HOUSEHOLD_MEMBERS", "PREMIUM_MAX_HOUSEHOLD_MEMBERS",
      "FREE_SAVINGS_WEEKS", "PREMIUM_SAVINGS_WEEKS",
    ].map((namn) => [namn, läsKonstant(namn, källa)])),
    priser: läsPriser(källa),
  };
}

/** En kopia av modellen med en funktion flyttad till andra sidan gränsen. */
export function flyttad(modell, funktion, fri) {
  const funktioner = new Map(modell.funktioner);
  if (!funktioner.has(funktion)) throw new Error(`${funktion} finns inte att flytta`);
  funktioner.set(funktion, fri);
  return { ...modell, funktioner };
}
