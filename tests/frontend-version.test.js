// E15 (2): versionsbumpen var trippelmanuell.
// L9: talet står inte i källan längre - bygget stämplar in det.
//
// `CACHE_NAME` i sw.js och `?v=` två gånger i index.html - tre handredigerade
// tal som måste vara lika. Glider de isär kan en telefon köra gammal app.js
// mot ny CSS. Och det finns ett tystare fel än så: en gren som bumpar 48 till
// 49 medan main står på 52 SÄNKER versionen när den mergas, och då serverar
// Pages gammal app.js under en URL telefonen redan sett. Ett tal som kan gå
// ner är värre än tre tal som kan gå isär.
//
// E15 löste riktningen (ett tal som aldrig går ner) men lämnade raden kvar i
// källan, där åtta parallella grenar konfliktade på den. L9 tog bort talet:
// källan bär en platshållare, bygget stämplar in eran plus en digest över
// varje fil under app/ i utdatan. Konfliktfriheten prövas i
// tests/frontend-version-konflikt.test.js; här prövas att stämpeln gör sitt
// jobb.
import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { cpSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  PLACEHOLDER, RELEASE, cacheStamp, collectFiles, contentDigest, mainReleases,
  nextRelease, placeholdersIn, releasesIn, sharedStamp, stampBuild, stampIndexHtml,
  stampServiceWorker, stampsIn,
} from "../scripts/frontend_version.mjs";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const swSource = readFileSync(join(ROOT, "frontend/app/sw.js"), "utf8");
const htmlSource = readFileSync(join(ROOT, "frontend/app/index.html"), "utf8");

// ---- källorna: ingen version att konflikta om -----------------------------

test("L9: de tre ställena i källan bär platshållaren, inte ett tal", () => {
  assert.deepEqual(stampsIn(swSource, htmlSource), {
    "sw.js CACHE_NAME": PLACEHOLDER,
    "index.html app.js?v": PLACEHOLDER,
    "index.html styles.css?v": PLACEHOLDER,
  });
});

test("L9: ett tal som smugit tillbaka in i källan syns", () => {
  // Det här är vad grinden (backend/scripts/check_frontend_version.py) letar
  // efter. En rad med ett tal i är en rad varje frontendgren måste ändra.
  const medTal = stampServiceWorker(swSource, "107");
  assert.equal(stampsIn(medTal, htmlSource)["sw.js CACHE_NAME"], "107");
});

test("E15: en skev version är ett fel att bygga vidare på, inte ett val", () => {
  const skevt = stampIndexHtml(htmlSource, "1");
  assert.throws(() => sharedStamp(swSource, skevt), /VERSIONSSKEVHET/);
  assert.throws(() => sharedStamp("// ingen cache här", htmlSource), /hittade ingen frontend-version/);
  assert.equal(sharedStamp(swSource, htmlSource), PLACEHOLDER);
});

// ---- eran: en etikett som aldrig går bakåt --------------------------------

test("E15: nästa era är strikt högre än ALLT som setts", () => {
  assert.equal(nextRelease([48, 52, 49]), 53);
  assert.equal(nextRelease([52]), 53);
  assert.equal(nextRelease([]), 1, "ett tomt repo börjar på 1, inte på NaN");
  // Två grenar mergade i fel ordning: main gick 52 -> 49. Toppen säger 49, och
  // 50-52 har redan varit ute. Nästa måste bli 53, inte 50.
  assert.equal(nextRelease([40, 52, 49]), 53);
});

test("E15: bara hela releasetal räknas, inte byggets stämplar", () => {
  assert.deepEqual(releasesIn('CACHE_NAME = "matjakt-shell-v53"'), [53]);
  assert.deepEqual(releasesIn('CACHE_NAME = "matjakt-shell-v53-a1b2c3d4e5"'), [],
    "en stämplad kopia är ett bygge, inte en era någon kan ha bumpat till");
  assert.deepEqual(releasesIn(`CACHE_NAME = "matjakt-shell-v${PLACEHOLDER}"`), [],
    "platshållaren är inget tal");
  assert.deepEqual(releasesIn('src="app.js?v=12" href="styles.css?v=12"'), [12, 12]);
});

// Ett riktigt litet git-repo med en riktig historik. Det är det enda sättet
// att pröva "högre än allt som finns i main" utan att låtsas om git.
function repoMedHistorik(versioner) {
  const repo = mkdtempSync(join(tmpdir(), "matjakt-main-"));
  const git = (...args) => execFileSync("git", args, { cwd: repo, stdio: "pipe" });
  git("init", "-q", "-b", "main");
  git("config", "user.email", "test@matjakt.invalid");
  git("config", "user.name", "E15");
  mkdirSync(join(repo, "frontend/app"), { recursive: true });
  for (const version of versioner) {
    writeFileSync(join(repo, "frontend/app/sw.js"), `const CACHE_NAME = "matjakt-shell-v${version}";\n`);
    writeFileSync(join(repo, "frontend/app/index.html"), `<link href="styles.css?v=${version}"><script src="app.js?v=${version}"></script>\n`);
    git("add", "-A");
    git("commit", "-q", "-m", `v${version}`);
  }
  return repo;
}

test("E15: generatorn läser hela main, inte bara toppen", () => {
  // Main har VARIT på 52 och står nu på 49 - exakt vad två merges i fel
  // ordning gör. 50 vore ett tal som redan varit ute.
  const repo = repoMedHistorik([47, 52, 49]);
  try {
    const sedda = mainReleases({ cwd: repo, refs: ["main"] });
    assert.ok(sedda.includes(52), `52 har varit ute i main men syns inte: ${sedda}`);
    assert.equal(nextRelease(sedda), 53);
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("E15: utan git stannar generatorn inte - den säger bara att den inte vet", () => {
  // CI checkar ut med djup 1 och har ingen origin/main. En generator som
  // kastar där blir en som ingen kör.
  const tomt = mkdtempSync(join(tmpdir(), "matjakt-ingen-git-"));
  try {
    assert.deepEqual(mainReleases({ cwd: tomt, refs: ["origin/main", "main"] }), []);
  } finally {
    rmSync(tomt, { recursive: true, force: true });
  }
});

test("L9: eran ligger över allt main någonsin delat ut", t => {
  // Efter L9 växer inte mängden tal i main längre - den är golvet under eran.
  // Etiketten får inte gå bakåt under det som en gång faktiskt serverats.
  // Går main inte att läsa (grund klon - CI checkar ut med djup 1) finns inget
  // att pröva, och testet hoppas över i stället för att ljuga.
  const main = mainReleases();
  if (!main.length) return t.skip("ingen läsbar origin/main - grund klon");
  assert.ok(RELEASE >= Math.max(...main),
    `eran ${RELEASE} ligger under main:s högsta ${Math.max(...main)} - en etikett som går bakåt ljuger`);
});

// ---- stämplingen ---------------------------------------------------------

test("E15: stämplingen träffar alla tre ställena och bara dem", () => {
  const sw = stampServiceWorker(swSource, "53-abcdef0123");
  const html = stampIndexHtml(htmlSource, "53-abcdef0123");
  assert.deepEqual(stampsIn(sw, html), {
    "sw.js CACHE_NAME": "53-abcdef0123",
    "index.html app.js?v": "53-abcdef0123",
    "index.html styles.css?v": "53-abcdef0123",
  });
  // Inget annat i index.html rörs - api-url-metataggen är deployens enda
  // andra ingrepp i samma fil och får inte hamna i vägen.
  assert.equal(html.replace(/\?v=[^"']*/g, ""), htmlSource.replace(/\?v=[^"']*/g, ""));
});

const fil = (namn, text) => [namn, Buffer.from(text)];
const litetBygge = () => [
  fil("app.js", "console.log('v1')"),
  fil("index.html", `<link href="styles.css?v=${PLACEHOLDER}"><script src="app.js?v=${PLACEHOLDER}">`),
  fil("styles.css", "body{color:#000}"),
  fil("sw.js", `const CACHE_NAME = "matjakt-shell-v${PLACEHOLDER}";`),
  fil("data/recipes.json", "[]"),
  fil("assets/recipes/chili.jpg", "JPEG-ish"),
];

test("L9: digesten täcker VARJE fil under app/, inte bara bundeln och CSS:en", () => {
  // Det var den gamla stämpelns tysta hål: en ändrad receptbank eller ett nytt
  // receptfoto under samma filnamn ändrade varken app.js eller styles.css, men
  // ligger bakom samma cache-nyckel och serverades ur service workerns kopia.
  const bas = cacheStamp(RELEASE, litetBygge());
  for (const [namn, nyttInnehåll] of [
    ["app.js", "console.log('v2')"],
    ["styles.css", "body{color:#fff}"],
    ["data/recipes.json", '[{"id":1}]'],
    ["assets/recipes/chili.jpg", "JPEG-annat"],
    ["index.html", `<p>ny rad</p><link href="styles.css?v=${PLACEHOLDER}"><script src="app.js?v=${PLACEHOLDER}">`],
    ["sw.js", `// ny logik\nconst CACHE_NAME = "matjakt-shell-v${PLACEHOLDER}";`],
  ]) {
    const ändrat = litetBygge().map(([n, b]) => (n === namn ? fil(n, nyttInnehåll) : [n, b]));
    assert.notEqual(cacheStamp(RELEASE, ändrat), bas, `en ändrad ${namn} bytte inte cache-nyckel`);
  }
  assert.notEqual(cacheStamp(RELEASE, [...litetBygge(), fil("nytt.js", "")]), bas, "en tillagd fil syns inte");
  assert.notEqual(cacheStamp(RELEASE, litetBygge().filter(([n]) => n !== "data/recipes.json")), bas,
    "en borttagen fil syns inte");
  // Sökvägen räknas, inte bara innehållet: samma byte under ett annat namn är
  // en annan sak att servera.
  const omdöpt = litetBygge().map(([n, b]) => (n === "assets/recipes/chili.jpg" ? ["assets/recipes/chili2.jpg", b] : [n, b]));
  assert.notEqual(cacheStamp(RELEASE, omdöpt), bas, "ett omdöpt recept bytte inte cache-nyckel");
});

test("L9: stämpeln i filerna räknas INTE in i digesten - annars hade den berott på sig själv", () => {
  const bas = cacheStamp(RELEASE, litetBygge());
  const stämplat = litetBygge().map(([namn, byte]) => {
    if (namn === "sw.js") return fil(namn, stampServiceWorker(byte.toString(), "999-deadbeef99"));
    if (namn === "index.html") return fil(namn, stampIndexHtml(byte.toString(), "999-deadbeef99"));
    return [namn, byte];
  });
  assert.equal(cacheStamp(RELEASE, stämplat), bas,
    "att stämpla om ett bygge får inte ändra digesten - då hade den aldrig gått att kontrollera");
});

test("E15: oförändrad kod ger samma stämpel - bygget är inte slumpartat", () => {
  assert.equal(cacheStamp(RELEASE, litetBygge()), cacheStamp(RELEASE, litetBygge()));
  assert.equal(contentDigest(litetBygge()).length, 64);
});

test("L9: stämpeln bär eran så en människa känner igen releasen", () => {
  assert.match(cacheStamp(53, litetBygge()), /^53-[0-9a-f]{10}$/);
  assert.notEqual(cacheStamp(54, litetBygge()), cacheStamp(53, litetBygge()));
});

// ---- byggsteget, på riktigt ----------------------------------------------

function byggTill() {
  const out = mkdtempSync(join(tmpdir(), "matjakt-version-"));
  execFileSync(process.execPath, [join(ROOT, "scripts/build_frontend.mjs"), out], { stdio: "pipe" });
  return out;
}

const stämpelI = out => sharedStamp(readFileSync(join(out, "app/sw.js"), "utf8"),
                                    readFileSync(join(out, "app/index.html"), "utf8"));

test("L9: bygget stämplar alla tre ställena med ETT värde, härlett ur bygget", () => {
  const out = byggTill();
  try {
    const app = join(out, "app");
    const stämplar = stampsIn(readFileSync(join(app, "sw.js"), "utf8"), readFileSync(join(app, "index.html"), "utf8"));
    assert.equal(new Set(Object.values(stämplar)).size, 1, `bygget lämnade skeva stämplar: ${JSON.stringify(stämplar)}`);
    assert.match(stämplar["sw.js CACHE_NAME"], /^\d+-[0-9a-f]{10}$/);
    assert.equal(stämplar["sw.js CACHE_NAME"], cacheStamp(RELEASE, collectFiles(app)),
      "stämpeln i bygget är inte digesten av bygget - då kontrollerar den ingenting");
  } finally { rmSync(out, { recursive: true, force: true }); }
});

test("L9: ingen platshållare når utdatan", () => {
  const out = byggTill();
  try {
    assert.deepEqual(placeholdersIn(collectFiles(join(out, "app"))), [],
      "en ostämplad cache-nyckel i produktion är en nyckel som aldrig byter");
  } finally { rmSync(out, { recursive: true, force: true }); }
});

test("L9: en platshållare som INTE går att stämpla stannar bygget - högt", () => {
  // Det farligaste utfallet här är ett tyst genomsläpp: service workern hade
  // cachat under ett namn som aldrig byter, och ingen deploy efter den hade
  // nått en telefon som redan varit inne. Stämplingen känner bara igen de tre
  // ställena; står platshållaren någon annanstans måste bygget stanna.
  const bygge = mkdtempSync(join(tmpdir(), "matjakt-platshallare-"));
  const lägg = ([namn, innehåll]) => {
    mkdirSync(dirname(join(bygge, namn)), { recursive: true });
    writeFileSync(join(bygge, namn), innehåll);
  };
  try {
    litetBygge().forEach(lägg);
    assert.match(stampBuild(bygge), /^\d+-[0-9a-f]{10}$/, "ett välformat bygge ska gå igenom");

    litetBygge().forEach(lägg);   // ställ tillbaka de nyss stämplade filerna
    lägg(fil("admin.html", `<script src="admin.js?v=${PLACEHOLDER}"></script>`));
    assert.throws(() => stampBuild(bygge), /admin\.html/,
      "bygget släppte igenom en ostämplad platshållare");
  } finally { rmSync(bygge, { recursive: true, force: true }); }
});

test("L9: två byggen av samma källa ger samma stämpel", () => {
  const en = byggTill();
  const två = byggTill();
  try {
    assert.equal(stämpelI(en), stämpelI(två),
      "bygget får inte vara slumpartat - då bytte varje deploy URL i onödan");
  } finally {
    rmSync(en, { recursive: true, force: true });
    rmSync(två, { recursive: true, force: true });
  }
});

test("L9: en ändrad frontend ger ett bygge med en annan stämpel - utan att någon bumpar något", () => {
  // Hela poängen med att ta bort talet: det som förr krävde tre handredigerade
  // rader (och gav en konflikt per gren) sker nu av sig självt.
  const out = byggTill();
  const kopia = mkdtempSync(join(tmpdir(), "matjakt-andrad-"));
  try {
    const före = stämpelI(out);
    cpSync(join(out, "app"), join(kopia, "app"), { recursive: true });
    const app = join(kopia, "app");
    writeFileSync(join(app, "app.js"), `${readFileSync(join(app, "app.js"), "utf8")}\n// G5: ikväll-vyn\n`);
    assert.notEqual(stampBuild(app), före,
      "en ändrad app.js gav samma cache-nyckel - då når den aldrig en telefon som varit inne");
  } finally {
    rmSync(out, { recursive: true, force: true });
    rmSync(kopia, { recursive: true, force: true });
  }
});
