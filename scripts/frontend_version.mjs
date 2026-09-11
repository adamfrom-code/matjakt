// ---------------------------------------------------------------------------
// FRONTENDENS CACHE-VERSION — ett ställe, två jobb
//
// Versionen stod på TRE ställen och höjdes för hand: `CACHE_NAME` i sw.js och
// `?v=` två gånger i index.html. Tre handredigerade tal som måste vara lika.
// backend/scripts/check_frontend_version.py (K5) vaktar redan både att de är
// lika och att de HÖJTS när frontenden ändrats — den grinden rörs inte här.
// Det som saknades är det som gör grinden möjlig att uppfylla: något som
// räknar fram talet åt en.
//
// Två jobb, medvetet åtskilda, för de har olika krav:
//
//   1. BUMPEN (kräver git, körs för hand, före commit)
//      `node scripts/frontend_version.mjs --bump`
//      Räknar upp från det HÖGSTA tal som någonsin stått i main — inte från
//      det som råkar ligga i den egna grenen. Det är hela skillnaden. Sju
//      grenar är i luften samtidigt och de flesta ligger UNDER main: en gren
//      som bumpar 48 till 49 när main står på 52 SÄNKER versionen vid merge,
//      och då kan Pages servera gammal app.js under en URL telefonen redan
//      sett. Ett tal som kan gå ner är värre än tre tal som kan gå isär.
//      Historiken läses, inte bara main:s topp, så ett tal som redan varit
//      ute en gång aldrig kan återanvändas.
//
//   2. STÄMPELN (kräver inte git, körs i byggsteget, deterministisk)
//      scripts/build_frontend.mjs skriver alla tre ställena i BYGGET ur ETT
//      värde: releasenumret plus en hash av det som faktiskt byggdes.
//      `matjakt-shell-v53-a1b2c3d4e5`, `?v=53-a1b2c3d4e5`. Hashen är det som
//      gör jobbet när bumpen ändå missas: två grenar som båda höjde 51 till
//      52 blir EN höjning vid ombasering — git ser identiska ändringar och
//      slår ihop dem utan ett ord, och de tre talen stämmer fortfarande
//      överens. Ändrad kod ger alltid ny stämpel, oförändrad kod alltid
//      samma, oavsett vad talet säger.
//
// Källfilerna behåller sitt rena `v53` / `?v=53`. Utvecklingsservern serverar
// frontend/ direkt, och check_frontend_version.py läser samma heltal som
// förut — därför fungerar både den och en handbump oförändrat. Det är
// BYGGETS kopia som stämplas, och den kopian committas aldrig.
// ---------------------------------------------------------------------------

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const SW_PATH = join(ROOT, "frontend", "app", "sw.js");
export const HTML_PATH = join(ROOT, "frontend", "app", "index.html");

// Förankrade i tilldelningen respektive attributet, inte i namnet: en
// kommentar som NÄMNER cachenamnet är inte cachenamnet. `[^"']*` och inte
// `\d+` för att också kunna läsa en stämplad kopia (`53-a1b2c3d4e5`).
const SW_STAMP = /CACHE_NAME = "matjakt-shell-v([^"]*)"/;
const APP_STAMP = /app\.js\?v=([^"']*)/;
const CSS_STAMP = /styles\.css\?v=([^"']*)/;
const SW_STAMP_ALL = /CACHE_NAME = "matjakt-shell-v[^"]*"/g;
const APP_STAMP_ALL = /app\.js\?v=[^"']*/g;
const CSS_STAMP_ALL = /styles\.css\?v=[^"']*/g;

/** Vad de tre ställena säger, precis som de står. Okända ställen blir null. */
export function stampsIn(swSource, htmlSource) {
  return {
    "sw.js CACHE_NAME": SW_STAMP.exec(swSource)?.[1] ?? null,
    "index.html app.js?v": APP_STAMP.exec(htmlSource)?.[1] ?? null,
    "index.html styles.css?v": CSS_STAMP.exec(htmlSource)?.[1] ?? null,
  };
}

/**
 * Releasenumret — och samtidigt en grind. Säger de tre ställena olika saker
 * är det ett fel att bygga vidare på, inte något att välja bland: ett bygge
 * på en skev version är ingenting att deploya.
 */
export function frontendRelease(swSource, htmlSource) {
  const found = stampsIn(swSource, htmlSource);
  const missing = Object.entries(found).filter(([, value]) => value === null).map(([where]) => where);
  if (missing.length) throw new Error(`hittade ingen frontend-version i: ${missing.join(", ")}`);
  if (new Set(Object.values(found)).size !== 1) {
    throw new Error(`VERSIONSSKEVHET: ${JSON.stringify(found)}`);
  }
  const release = Number(found["sw.js CACHE_NAME"]);
  if (!Number.isInteger(release) || release < 1) {
    throw new Error(`frontend-versionen är inte ett heltal: ${found["sw.js CACHE_NAME"]}`);
  }
  return release;
}

/**
 * Varje releasenummer som förekommer i en textmassa — en fil, eller utdata
 * från `git log -p`. Bara heltal räknas: en stämplad kopia (`53-a1b2c3d4e5`)
 * är ett bygge, inte en release någon kan ha bumpat till.
 */
export function releasesIn(text) {
  const numbers = [];
  for (const pattern of [/matjakt-shell-v(\d+)(?![\w-])/g, /app\.js\?v=(\d+)(?![\w-])/g, /styles\.css\?v=(\d+)(?![\w-])/g]) {
    for (const match of String(text).matchAll(pattern)) numbers.push(Number(match[1]));
  }
  return numbers;
}

/**
 * Nästa release: ett STRIKT högre tal än allt som setts.
 *
 * Det här är den enda regeln som betyder något. `max + 1` och inte
 * `nuvarande + 1`, för "nuvarande" är den egna grenens tal och det ligger
 * nästan alltid under main:s när sju grenar är igång.
 */
export function nextRelease(seen) {
  const numbers = [...seen].filter(value => Number.isInteger(value) && value > 0);
  return (numbers.length ? Math.max(...numbers) : 0) + 1;
}

const gitRunner = (cwd = ROOT) => (...args) =>
  execFileSync("git", args, { cwd, encoding: "utf8", maxBuffer: 64 * 1024 * 1024, stdio: ["ignore", "pipe", "ignore"] });

/**
 * Varje releasenummer som NÅGONSIN stått i main — inte bara det som står där
 * nu. Skillnaden spelar roll: slås två grenars merge ihop i fel ordning kan
 * main:s tal gå NER, och då är main:s topp ett tal som redan varit ute.
 *
 * Bästa ansträngning. Går git inte att fråga — ingen `origin/main` hämtad, en
 * grund klon (CI checkar ut med djup 1), inget repo alls — svarar den tomt i
 * stället för att stanna. Anroparen väger in de lokala talen ändå, så bumpen
 * blir i värsta fall den gamla "lokala + 1" och aldrig ett fel.
 */
export function mainReleases({ cwd = ROOT, refs = ["origin/main", "main"], run = gitRunner(cwd) } = {}) {
  for (const ref of refs) {
    try {
      run("rev-parse", "--verify", `${ref}^{commit}`);
    } catch {
      continue;
    }
    const numbers = [];
    try {
      numbers.push(...releasesIn(run("show", `${ref}:frontend/app/sw.js`)));
      numbers.push(...releasesIn(run("show", `${ref}:frontend/app/index.html`)));
    } catch { /* filerna kan saknas - historiken nedan är ändå den som räknar */ }
    try {
      // Hela historiken för de två filerna i ETT git-anrop (~0,2 s här).
      // Bara tillagda rader: en BORTTAGEN v49 är en version som varit ute.
      const patch = run("log", ref, "-p", "--format=", "--", "frontend/app/sw.js", "frontend/app/index.html");
      const added = patch.split("\n").filter(line => line.startsWith("+")).join("\n");
      numbers.push(...releasesIn(added));
    } catch { /* grund klon: historiken finns inte, toppen ovan får räcka */ }
    if (numbers.length) return numbers;
  }
  return [];
}

/** Alla tre ställena, ur ETT värde. Ingen annan rör de här raderna. */
export function stampServiceWorker(swSource, stamp) {
  return swSource.replace(SW_STAMP_ALL, `CACHE_NAME = "matjakt-shell-v${stamp}"`);
}

export function stampIndexHtml(htmlSource, stamp) {
  return htmlSource
    .replace(APP_STAMP_ALL, `app.js?v=${stamp}`)
    .replace(CSS_STAMP_ALL, `styles.css?v=${stamp}`);
}

/**
 * Byggets stämpel: releasenumret för människor, hashen för webbläsaren.
 *
 * Hashen tas över det som FAKTISKT byggdes — den buntade app.js och den
 * minifierade styles.css — inte över källorna. Det är de två filerna `?v=`
 * finns för, och det är deras innehåll en webbläsare riskerar att återanvända
 * ur sin HTTP-cache. (index.html hashas inte: stämpeln står i den.)
 */
export function cacheStamp(release, ...builtFiles) {
  const digest = createHash("sha256");
  builtFiles.forEach(content => digest.update(content));
  return `${release}-${digest.digest("hex").slice(0, 10)}`;
}

// ---- bumpen ---------------------------------------------------------------

/** Ren funktion: källorna in, källorna med det nya talet ut. */
export function bumpSources(swSource, htmlSource, release) {
  return { sw: stampServiceWorker(swSource, release), html: stampIndexHtml(htmlSource, release) };
}

/**
 * Vilket tal ska den här arbetskopian bumpa till? Lokalt + allt main någonsin
 * sett, plus ett. Returnerar också om main faktiskt gick att läsa, så en bump
 * som tyst föll tillbaka på gamla "lokala + 1" inte ser ut som en som räknade
 * rätt.
 */
export function planBump({ cwd = ROOT, sw = readFileSync(SW_PATH, "utf8"), html = readFileSync(HTML_PATH, "utf8"), run } = {}) {
  const local = releasesIn(sw).concat(releasesIn(html));
  const main = mainReleases(run ? { cwd, run } : { cwd });
  return { next: nextRelease([...local, ...main]), local, main, sawMain: main.length > 0 };
}

function cli(argv) {
  const plan = planBump();

  if (argv.includes("--next")) { process.stdout.write(`${plan.next}\n`); return 0; }

  if (!argv.includes("--bump")) {
    console.log(`frontend-version nu: ${JSON.stringify(stampsIn(readFileSync(SW_PATH, "utf8"), readFileSync(HTML_PATH, "utf8")))}`);
    console.log(`nästa: ${plan.next}${plan.sawMain ? ` (högst någonsin i main: ${Math.max(...plan.main)})` : " - main gick inte att läsa, bara lokala tal vägdes in"}`);
    console.log("\n  node scripts/frontend_version.mjs --bump    skriver talet till alla tre ställena");
    return 0;
  }

  const { sw, html } = bumpSources(readFileSync(SW_PATH, "utf8"), readFileSync(HTML_PATH, "utf8"), plan.next);
  writeFileSync(SW_PATH, sw);
  writeFileSync(HTML_PATH, html);
  console.log(`frontend-version -> ${plan.next} på alla tre ställena`);
  if (!plan.sawMain) {
    console.warn("VARNING: main gick inte att läsa (ingen origin/main hämtad?). Talet är högre än\n"
      + "         den här arbetskopians, men kanske inte högre än main:s. Kör `git fetch origin`\n"
      + "         och kör om innan du committar.");
  }
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  process.exit(cli(process.argv.slice(2)));
}
