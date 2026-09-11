// E15 (2): versionsbumpen var trippelmanuell.
//
// `CACHE_NAME` i sw.js och `?v=` två gånger i index.html - tre handredigerade
// tal som måste vara lika. Glider de isär kan en telefon köra gammal app.js
// mot ny CSS. Och det finns ett tystare fel än så: en gren som bumpar 48 till
// 49 medan main står på 52 SÄNKER versionen när den mergas, och då serverar
// Pages gammal app.js under en URL telefonen redan sett. Ett tal som kan gå
// ner är värre än tre tal som kan gå isär.
//
// Två lås här nere, ett per jobb i scripts/frontend_version.mjs:
//   - generatorn ger ett tal som är strikt högre än allt main någonsin sett
//   - byggsteget stämplar alla tre ställena med ETT värde, härlett ur bygget
import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  bumpSources, cacheStamp, frontendRelease, mainReleases, nextRelease,
  planBump, releasesIn, stampIndexHtml, stampServiceWorker, stampsIn,
} from "../scripts/frontend_version.mjs";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const swSource = readFileSync(join(ROOT, "frontend/app/sw.js"), "utf8");
const htmlSource = readFileSync(join(ROOT, "frontend/app/index.html"), "utf8");

// ---- källorna -------------------------------------------------------------

test("E15: de tre ställena i källan säger samma sak", () => {
  const release = frontendRelease(swSource, htmlSource);
  assert.ok(Number.isInteger(release) && release > 0, `orimligt releasenummer: ${release}`);
});

test("E15: en skev version är ett fel att bygga vidare på, inte ett val", () => {
  const skevt = htmlSource.replace(/app\.js\?v=\d+/, "app.js?v=1");
  assert.throws(() => frontendRelease(swSource, skevt), /VERSIONSSKEVHET/);
  assert.throws(() => frontendRelease("// ingen cache här", htmlSource), /hittade ingen frontend-version/);
});

test("E15: källorna behåller sitt rena tal - utvecklingsservern och K5-grinden läser dem", () => {
  // backend/scripts/check_frontend_version.py matchar på (\d+). Stämplas
  // källorna med hashen slutar både den grinden och `--bump` att fungera,
  // och de sju grenar som bumpar för hand skulle stå utan grind.
  assert.match(swSource, /CACHE_NAME = "matjakt-shell-v\d+"/);
  assert.match(htmlSource, /app\.js\?v=\d+"/);
  assert.match(htmlSource, /styles\.css\?v=\d+"/);
});

// ---- generatorn: ett tal som aldrig går ner -------------------------------

test("E15: nästa release är strikt högre än ALLT som setts", () => {
  assert.equal(nextRelease([48, 52, 49]), 53);
  assert.equal(nextRelease([52]), 53);
  assert.equal(nextRelease([]), 1, "ett tomt repo börjar på 1, inte på NaN");
});

test("E15: ett main som gått NER ger ändå ett tal högre än toppen det haft", () => {
  // Två grenar mergas i fel ordning: main går 52 -> 49. Toppen säger 49, och
  // 50-52 har redan varit ute. Nästa måste bli 53, inte 50.
  assert.equal(nextRelease([40, 52, 49]), 53);
});

test("E15: den egna grenens tal räcker inte som utgångspunkt", () => {
  // Grenen står på 48, main på 52. 49 hade sänkt versionen vid merge.
  const gren = [48, 48, 48];
  assert.equal(nextRelease(gren), 49, "utan main är det gamla svaret 49");
  assert.equal(nextRelease([...gren, 52]), 53, "med main blir det 53");
});

test("E15: bara hela releasetal räknas, inte byggets stämplar", () => {
  assert.deepEqual(releasesIn('CACHE_NAME = "matjakt-shell-v53"'), [53]);
  assert.deepEqual(releasesIn('CACHE_NAME = "matjakt-shell-v53-a1b2c3d4e5"'), [],
    "en stämplad kopia är ett bygge, inte en release någon kan ha bumpat till");
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

test("E15: en gren som ligger efter main får ändå ett tal högre än main", () => {
  const repo = repoMedHistorik([50, 51, 52]);
  try {
    // Arbetskopian står på 48 - en gren som grenades av före de tre merges
    // som tagit main till 52. Det gamla svaret var 49.
    const plan = planBump({
      cwd: repo,
      sw: 'const CACHE_NAME = "matjakt-shell-v48";',
      html: '<link href="styles.css?v=48"><script src="app.js?v=48"></script>',
      run: (...args) => execFileSync("git", args, { cwd: repo, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }),
    });
    assert.equal(plan.sawMain, true);
    assert.equal(plan.next, 53, "talet måste vara strikt högre än main:s 52, inte grenens 48 + 1");
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
    const plan = planBump({ cwd: tomt, sw: 'const CACHE_NAME = "matjakt-shell-v48";', html: '"app.js?v=48" "styles.css?v=48"' });
    assert.equal(plan.sawMain, false, "och den säger rakt ut att main inte gick att läsa");
    assert.equal(plan.next, 49);
  } finally {
    rmSync(tomt, { recursive: true, force: true });
  }
});

test("E15: bumpen skriver alla tre ställena och rör inget annat", () => {
  const { sw, html } = bumpSources(swSource, htmlSource, 99);
  assert.deepEqual(stampsIn(sw, html), {
    "sw.js CACHE_NAME": "99", "index.html app.js?v": "99", "index.html styles.css?v": "99",
  });
  assert.equal(html.replace(/\?v=[^"']*/g, ""), htmlSource.replace(/\?v=[^"']*/g, ""));
});

// Den skarpa varianten: mot det RIKTIGA main, i det här repot. Går main inte
// att läsa (grund klon - CI checkar ut med djup 1) finns inget att pröva, och
// testet hoppas över i stället för att ljuga. Det syntetiska repot ovan är
// det som körs överallt.
//
// Notera vad som INTE prövas här: att den här grenens egna tre tal redan är
// högre än main:s. Det är K5:s grind (check_frontend_version.py
// --require-bump), och den mäter mot rätt bas. Ett node-test som krävde det
// hade blivit rött i sju arbetskopior som råkar ligga efter main, av skäl som
// inte har med deras paket att göra.
test("E15: generatorns tal är högre än det som ligger i main", t => {
  const main = mainReleases();
  if (!main.length) return t.skip("ingen läsbar origin/main - grund klon");
  const plan = planBump();
  assert.ok(plan.next > Math.max(...main),
    `nästa release ${plan.next} är inte högre än main:s högsta ${Math.max(...main)}`);
});

// ---- stämpeln -------------------------------------------------------------

test("E15: ändrad kod ger ALLTID en ny stämpel", () => {
  const app = "console.log('v1')";
  const css = "body{color:#000}";
  const före = cacheStamp(53, app, css);
  assert.notEqual(cacheStamp(53, app + " ", css), före, "en ändrad app.js måste byta stämpel");
  assert.notEqual(cacheStamp(53, app, css + " "), före, "en ändrad styles.css måste byta stämpel");
  assert.notEqual(cacheStamp(54, app, css), före, "ett höjt releasenummer syns också");
});

test("E15: oförändrad kod ger samma stämpel - bygget är inte slumpartat", () => {
  assert.equal(cacheStamp(53, "app", "css"), cacheStamp(53, "app", "css"));
});

test("E15: stämpeln bär releasenumret så en människa känner igen releasen", () => {
  assert.match(cacheStamp(53, "app", "css"), /^53-[0-9a-f]{10}$/);
});

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

// ---- byggsteget, på riktigt ----------------------------------------------

function buildInto() {
  const out = mkdtempSync(join(tmpdir(), "matjakt-version-"));
  try {
    execFileSync(process.execPath, [join(ROOT, "scripts/build_frontend.mjs"), out], { stdio: "pipe" });
    return {
      sw: readFileSync(join(out, "app/sw.js"), "utf8"),
      html: readFileSync(join(out, "app/index.html"), "utf8"),
    };
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
}

test("E15: bygget stämplar alla tre ställena med ETT värde", () => {
  const built = buildInto();
  const stämplar = stampsIn(built.sw, built.html);
  assert.equal(new Set(Object.values(stämplar)).size, 1, `bygget lämnade skeva stämplar: ${JSON.stringify(stämplar)}`);
  const stämpel = stämplar["sw.js CACHE_NAME"];
  assert.match(stämpel, /^\d+-[0-9a-f]{10}$/);

  // Stämpeln ska vara HÄRLEDD ur bygget, inte kopierad ur källan. Det är hela
  // skillnaden mot ett handskrivet tal: den kan inte råka bli densamma som
  // förra releasens medan koden är en annan.
  const release = frontendRelease(swSource, htmlSource);
  assert.equal(stämpel.split("-")[0], String(release), "releasenumret ska följa med");
  assert.notEqual(stämpel, String(release), "stämpeln får inte vara bara talet");
});

test("E15: två byggen av samma källa ger samma stämpel", () => {
  const stämpel = () => { const built = buildInto(); return stampsIn(built.sw, built.html)["sw.js CACHE_NAME"]; };
  assert.equal(stämpel(), stämpel(), "bygget får inte vara slumpartat - då bytte varje deploy URL i onödan");
});
