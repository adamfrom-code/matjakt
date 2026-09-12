// ---------------------------------------------------------------------------
// FRONTENDENS CACHE-VERSION — härledd ur bygget, aldrig skriven i källan
//
// Versionen stod på TRE ställen i två filer: `CACHE_NAME` i sw.js och `?v=`
// två gånger i index.html. E15 slutade redigera dem för hand och lät en
// generator räkna fram talet; L9 tog bort talet ur källan helt. Skälet till
// båda stegen är mätt, inte befarat:
//
//   - Tre handredigerade tal som måste vara lika GLIDER ISÄR. (K5 vaktar det.)
//   - "Ta det högsta du ser och lägg på ett" lät versionen SJUNKA när grenar
//     mergade i annan ordning än de skapades. `app.js?v=` gick 102 -> 25
//     (964d45e), upp till 103 (7aeb57c) och ner till 26 igen (3a36dd2). En
//     version som går ner gör att Pages serverar gammal app.js under en URL
//     telefonen redan sett - exakt det fel service workern finns för.
//   - Och raden i källan var en KONFLIKTRAD. Natten mellan 11 och 12 september
//     låg G5 `DIRTY` med grön CI i fyra timmar utan ägare kvar, och D11
//     konfliktade fyra gånger och gick från v56 till v107. Båda konflikterna
//     var enbart de tre versionsraderna. Ingen kodkonflikt någonsin.
//
// Därför står det ingen version i källan längre. sw.js och index.html bär
// `__MATJAKT_VERSION__`, och BYGGET stämplar in ett värde som är HÄRLETT ur
// det som faktiskt byggts:
//
//     matjakt-shell-v120-a1b2c3d4e5      ?v=120-a1b2c3d4e5
//     └────────────┘  └┘  └────────┘
//       skalets namn   |  digest över ALLT under app/ i bygget
//                   RELEASE (eran; en läsbar etikett, se nedan)
//
// Två egenskaper följer av att stämpeln är en digest och inte ett tal:
//
//   1. ÄNDRAD KOD KAN ALDRIG GÖMMA SIG BAKOM EN ADRESS SOM REDAN SERVERATS.
//      Digesten täcker varje fil under app/ i bygget - bundeln, den
//      minifierade CSS:en, index.html, admin-sidan, manifestet, receptbanken
//      i data/ och varje bild i assets/. Ändras en byte byter cache-nyckeln.
//      Det är starkare än "någon kom ihåg att höja talet", för det kan inte
//      glömmas bort.
//   2. INGEN GREN BEHÖVER VETA VILKET NUMMER NÅGON ANNAN TOG. Det finns ingen
//      rad att slåss om. Två grenar som var för sig rör frontend/app/**
//      mergas rent - tests/frontend-version-konflikt.test.js bevisar båda
//      riktningarna: med talet kvar i källan konfliktar samma två ändringar.
//
// RELEASE är eran, inte cache-nyckeln. Den står här - i en fil som inga
// frontendpaket rör - enbart så att en människa kan säga "v120" om en release
// i stället för tio hexsiffror. Den får aldrig sänkas under något main redan
// delat ut, och tests/frontend-version.test.js håller den där. (Att sänka den
// vore inte samma fel som förr - `v110` och `v110-a1b2c3d4e5` är olika
// strängar och kan aldrig kollidera - men en etikett som går bakåt ljuger.)
//
// 120 och inte 111: main stod på 110 när platshållaren landade och steg med
// ungefär ett i timmen medan paketet låg i kön. Marginalen är till för det
// fönstret. Efter L9 växer mängden tal i main inte längre - ingen källa
// innehåller ett - så golvet står stilla och eran höjs bara vid release.
//
// Grinden mot allt det här är backend/scripts/check_frontend_version.py, som
// räknar om digesten ur bygget med en EGEN implementation och jämför. Två
// oberoende implementationer som är eniga är det enda som gör regeln nedan
// entydig. Byggsteget failar dessutom högt om en platshållare står kvar i
// utdatan: en ostämplad `CACHE_NAME` i produktion vore en trasig cache-nyckel,
// och tyst genomsläpp är det farligaste utfallet av allihop.
//
// DIGESTENS REGEL (samma i JS och Python - ändra aldrig den ena ensam):
//
//     sha256 över, för varje fil under <bygge>/app sorterad på relativ
//     sökväg (POSIX, byte-ordning):
//         sökvägens utf8-byte
//         0x00
//         sha256(filens byte).digest()
//
//     app/sw.js och app/index.html normaliseras först: deras stämplar byts
//     tillbaka mot __MATJAKT_VERSION__. Utan det hade digesten berott på sig
//     själv. Inget annat i de filerna rörs, så en ändrad rad i dem syns.
// ---------------------------------------------------------------------------

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, posix, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const SW_PATH = join(ROOT, "frontend", "app", "sw.js");
export const HTML_PATH = join(ROOT, "frontend", "app", "index.html");

/** Det som står i källan i stället för ett tal. Bygget byter ut den; står den
 *  kvar i utdatan är bygget trasigt och ska stanna, inte deployas. */
export const PLACEHOLDER = "__MATJAKT_VERSION__";

/** Eran. Läsbar etikett, inte cache-nyckel. Höjs av `--bump`, aldrig av ett
 *  arbetspaket. Raden nedan skrivs om av skriptet självt - lämna formen. */
export const RELEASE = 120;

// Förankrade i tilldelningen respektive attributet, inte i namnet: en
// kommentar som NÄMNER cachenamnet är inte cachenamnet. `[^"']*` och inte
// `\d+` - de här läser både platshållaren och en stämplad kopia.
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
 * Den ENDA stämpeln de tre ställena bär - eller ett fel. Säger de olika saker
 * är det inget att välja bland: ett bygge på en skev version är ingenting att
 * deploya.
 */
export function sharedStamp(swSource, htmlSource) {
  const found = stampsIn(swSource, htmlSource);
  const missing = Object.entries(found).filter(([, value]) => value === null).map(([where]) => where);
  if (missing.length) throw new Error(`hittade ingen frontend-version i: ${missing.join(", ")}`);
  if (new Set(Object.values(found)).size !== 1) {
    throw new Error(`VERSIONSSKEVHET: ${JSON.stringify(found)}`);
  }
  return found["sw.js CACHE_NAME"];
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

// ---- digesten över bygget -------------------------------------------------

/**
 * Filens byte som de ska hashas. De två stämplade filerna normaliseras
 * tillbaka till platshållaren - annars hade digesten berott på sig själv.
 * Allt annat hashas rått, inklusive bilderna i assets/: ett utbytt receptfoto
 * under samma filnamn är precis en sådan ändring som service workerns cache
 * annars hade fortsatt servera.
 */
export function normalizeForDigest(relPath, bytes) {
  if (relPath === "sw.js") return Buffer.from(stampServiceWorker(bytes.toString("utf8"), PLACEHOLDER), "utf8");
  if (relPath === "index.html") return Buffer.from(stampIndexHtml(bytes.toString("utf8"), PLACEHOLDER), "utf8");
  return bytes;
}

/** Varje fil under katalogen, som [relativ POSIX-sökväg, innehåll], sorterad. */
export function collectFiles(dir) {
  const files = [];
  const walk = current => {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const full = join(current, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile()) files.push([relative(dir, full).split(sep).join(posix.sep), readFileSync(full)]);
    }
  };
  walk(dir);
  return files.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
}

/** Digesten. Regeln står i huvudkommentaren och finns i två implementationer. */
export function contentDigest(files) {
  const digest = createHash("sha256");
  for (const [relPath, bytes] of files) {
    digest.update(Buffer.from(relPath, "utf8"));
    digest.update(Buffer.from([0]));
    digest.update(createHash("sha256").update(normalizeForDigest(relPath, bytes)).digest());
  }
  return digest.digest("hex");
}

/** Byggets stämpel: eran för människor, digesten för webbläsaren. */
export function cacheStamp(release, files) {
  return `${release}-${contentDigest(files).slice(0, 10)}`;
}

/** Filer som fortfarande bär platshållaren. Tom lista är det enda godkända. */
export function placeholdersIn(files) {
  return files.filter(([, bytes]) => bytes.includes(PLACEHOLDER)).map(([relPath]) => relPath);
}

/**
 * Stämplar ett färdigt bygge och lämnar tillbaka stämpeln.
 *
 * Ordningen är hela poängen: digesten tas över trädet SOM DET ÄR (med
 * platshållarna kvar, normaliserade), stämpeln skrivs, och sedan läses trädet
 * om för att se att ingen platshållare står kvar. En ostämplad `CACHE_NAME` i
 * produktion är en trasig cache-nyckel, och ett tyst genomsläpp är det
 * farligaste utfallet här - därför kastar den, högt, med filnamnen i felet.
 */
export function stampBuild(appDir, release = RELEASE) {
  const stamp = cacheStamp(release, collectFiles(appDir));
  const swPath = join(appDir, "sw.js");
  const indexPath = join(appDir, "index.html");
  writeFileSync(swPath, stampServiceWorker(readFileSync(swPath, "utf8"), stamp));
  writeFileSync(indexPath, stampIndexHtml(readFileSync(indexPath, "utf8"), stamp));

  const kvar = placeholdersIn(collectFiles(appDir));
  if (kvar.length) {
    throw new Error(`${PLACEHOLDER} står kvar i bygget efter stämplingen: ${kvar.join(", ")}\n`
      + "Ett bygge med en ostämplad cache-nyckel får inte deployas. Stämplingen känner\n"
      + "bara igen `CACHE_NAME = \"matjakt-shell-v...\"` i app/sw.js och `app.js?v=` /\n"
      + "`styles.css?v=` i app/index.html - står platshållaren någon annanstans måste\n"
      + "den antingen bort eller stämplas av scripts/frontend_version.mjs.");
  }
  const skrivna = stampsIn(readFileSync(swPath, "utf8"), readFileSync(indexPath, "utf8"));
  if (Object.values(skrivna).some(värde => värde !== stamp)) {
    throw new Error(`stämplingen träffade inte alla tre ställena: ${JSON.stringify(skrivna)}`);
  }
  return stamp;
}

// ---- eran: ett tal som aldrig går bakåt -----------------------------------

/**
 * Varje releasenummer som förekommer i en textmassa - en fil, eller utdata
 * från `git log -p`. Bara heltal räknas: en stämplad kopia (`110-a1b2c3d4e5`)
 * är ett bygge, inte en era någon kan ha bumpat till.
 */
export function releasesIn(text) {
  const numbers = [];
  for (const pattern of [/matjakt-shell-v(\d+)(?![\w-])/g, /app\.js\?v=(\d+)(?![\w-])/g, /styles\.css\?v=(\d+)(?![\w-])/g]) {
    for (const match of String(text).matchAll(pattern)) numbers.push(Number(match[1]));
  }
  return numbers;
}

/** Nästa era: ett STRIKT högre tal än allt som setts. */
export function nextRelease(seen) {
  const numbers = [...seen].filter(value => Number.isInteger(value) && value > 0);
  return (numbers.length ? Math.max(...numbers) : 0) + 1;
}

const gitRunner = (cwd = ROOT) => (...args) =>
  execFileSync("git", args, { cwd, encoding: "utf8", maxBuffer: 64 * 1024 * 1024, stdio: ["ignore", "pipe", "ignore"] });

/**
 * Varje releasenummer som NÅGONSIN stått i main - inte bara det som står där
 * nu. Skillnaden spelar roll: slås två grenars merge ihop i fel ordning kan
 * main:s tal gå NER, och då är main:s topp ett tal som redan varit ute.
 *
 * Efter L9 växer den här mängden inte längre (källan bär en platshållare).
 * Den är golvet under eran: allt som en gång faktiskt serverats.
 *
 * Bästa ansträngning. Går git inte att fråga - ingen `origin/main` hämtad, en
 * grund klon (CI checkar ut med djup 1), inget repo alls - svarar den tomt i
 * stället för att stanna.
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

/** Vilken era skulle en bump landa på? Allt main någonsin sett, plus ett. */
export function planBump({ cwd = ROOT, run } = {}) {
  const main = mainReleases(run ? { cwd, run } : { cwd });
  return { next: nextRelease([...main, RELEASE]), main, sawMain: main.length > 0 };
}

function cli(argv) {
  if (argv.includes("--next")) { process.stdout.write(`${planBump().next}\n`); return 0; }

  if (argv.includes("--bump")) {
    const { next, sawMain } = planBump();
    const self = fileURLToPath(import.meta.url);
    const källa = readFileSync(self, "utf8");
    const ny = källa.replace(/^export const RELEASE = \d+;$/m, `export const RELEASE = ${next};`);
    if (ny === källa) throw new Error("hittade inte raden `export const RELEASE = <tal>;` att skriva om");
    writeFileSync(self, ny);
    console.log(`eran ${RELEASE} -> ${next} i scripts/frontend_version.mjs`);
    if (!sawMain) console.warn("VARNING: main gick inte att läsa (ingen origin/main hämtad?).");
    return 0;
  }

  const sw = readFileSync(SW_PATH, "utf8");
  const html = readFileSync(HTML_PATH, "utf8");
  console.log(`källan: ${JSON.stringify(stampsIn(sw, html))}`);
  console.log(`eran: ${RELEASE} (nästa vid --bump: ${planBump().next})`);
  console.log("\nVersionen står inte i källan - bygget stämplar in den:\n"
    + "  npm run build                                            bygger och stämplar\n"
    + "  python backend/scripts/check_frontend_version.py --build dist/frontend\n"
    + "  node scripts/frontend_version.mjs --bump                 höjer ERAN (inte per paket)");
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  process.exit(cli(process.argv.slice(2)));
}
