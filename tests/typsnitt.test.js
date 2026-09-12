// N0b:s acceptanskriterium: typsnitten ligger i appen, inte hos Google.
//
// Grinden är inte att det "ser rätt ut" i dag. Grinden är att nästa gång
// någon klistrar tillbaka en <link> mot Googles fontvärdar - för att det är
// det snabbaste sättet att få en ny vikt - blir bygget rött. Två saker
// hänger på det:
//
//   1. Första starten utan nät. En native-app som hämtar sina bokstäver över
//      nätet visar fallbackstacken på flygplanet och i tunnelbanan, och
//      skillnaden mellan Newsreader och Georgia i en 82px-rubrik är inte
//      subtil.
//   2. CSP:n. Två tredjepartsvärdar var inne i policyn enbart för att hämta
//      text. De är ute nu, och style-src/font-src är 'self'.
//
// Därför är värdnamnen en ren textsökning över hela filen, inte en sökning
// efter <link>-taggar: en URL i en kommentar, i ett attribut eller i en
// @import är lika fel. Av samma skäl nämns värdarna inte vid namn någonstans
// under frontend/app/ - undantag är hur en grind blir verkningslös.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, normalize } from "node:path";
import { test } from "node:test";

const rot = new URL("../", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const appKatalog = join(rot, "frontend", "app");
const fontKatalog = join(appKatalog, "assets", "fonts");

const läs = (...delar) => readFileSync(join(appKatalog, ...delar), "utf8");
const index = läs("index.html");
const css = läs("styles.css");

const GOOGLES_FONTVÄRDAR = ["fonts.googleapis.com", "fonts.gstatic.com"];

/** Alla @font-face-block i styles.css, som { deklaration: värde }. */
function fontFaces(källa) {
  return [...källa.matchAll(/@font-face\s*\{([^}]*)\}/g)].map(([, block]) => {
    const regler = {};
    for (const rad of block.split(";")) {
      const i = rad.indexOf(":");
      if (i === -1) continue;
      regler[rad.slice(0, i).trim().toLowerCase()] = rad.slice(i + 1).trim();
    }
    return regler;
  });
}

/** Värdet för ett direktiv i en CSP-sträng, som lista av källor. */
function direktiv(csp, namn) {
  const del = csp.split(";").map((d) => d.trim()).find((d) => d.startsWith(`${namn} `));
  return del ? del.slice(namn.length).trim().split(/\s+/) : null;
}

function cspUrIndex() {
  const m = /<meta http-equiv="Content-Security-Policy" content="([^"]+)">/.exec(index);
  assert.ok(m, "index.html har ingen CSP-metatagg - den är appens enda egna policy");
  return m[1];
}

test("varken index.html eller styles.css nämner Googles fontvärdar", () => {
  for (const värd of GOOGLES_FONTVÄRDAR) {
    assert.ok(!index.includes(värd),
      `${värd} finns i frontend/app/index.html. Typsnitten ligger i appen ` +
      "(assets/fonts/) och laddas via @font-face i styles.css - en länk, en " +
      "preconnect eller en CSP-post mot Google tar tillbaka både offline-buggen " +
      "och de två tredjepartsvärdarna i policyn.");
    assert.ok(!css.includes(värd),
      `${värd} finns i frontend/app/styles.css. En @import mot Google är samma ` +
      "fel som en <link> i index.html, bara svårare att se.");
  }
});

test("CSP:n släpper inte in någon fontvärd: style-src och font-src är 'self'", () => {
  const csp = cspUrIndex();
  for (const värd of GOOGLES_FONTVÄRDAR) {
    assert.ok(!csp.includes(värd), `${värd} står kvar i CSP-metataggen`);
  }
  // Starkare än en textsökning: ingen av de två direktiven får peka ut NÅGON
  // extern värd. Nästa font-CDN är lika fel som det förra.
  assert.deepEqual(direktiv(csp, "font-src"), ["'self'"],
    "font-src ska vara exakt 'self' - typsnitten ligger i appen");
  assert.deepEqual(direktiv(csp, "style-src"), ["'self'", "'unsafe-inline'"],
    "style-src ska vara 'self' 'unsafe-inline' (appen sätter style=\"\" på element) " +
    "och inget mer - ingen extern stilmall behövs längre");
});

test("varje @font-face pekar på en fil som finns, och filen är en woff2", () => {
  const faces = fontFaces(css);
  assert.ok(faces.length >= 3,
    `styles.css deklarerar ${faces.length} @font-face - Newsreader rak, Archivo rak ` +
    "och Archivo kursiv ska alla finnas");

  for (const face of faces) {
    const familj = face["font-family"];
    const m = /url\(\s*["']?([^"')]+)["']?\s*\)/.exec(face.src || "");
    assert.ok(m, `@font-face för ${familj} har ingen url() i src`);

    const relativ = m[1].split("?")[0];
    assert.ok(!/^([a-z]+:)?\/\//i.test(relativ),
      `${familj} laddas från ${relativ} - en absolut URL är per definition inte buntad`);

    const fil = join(appKatalog, normalize(relativ));
    assert.ok(existsSync(fil),
      `@font-face för ${familj} pekar på ${relativ}, som inte finns. En trasig ` +
      "sökväg syns inte i något annat test: sidan faller tyst tillbaka på Georgia.");

    // wOF2-magin. Fångar en trunkerad fil, en LFS-pekare och en woff1 som
    // döpts om - allt sådant renderas som "typsnittet laddade inte".
    const huvud = readFileSync(fil).subarray(0, 4).toString("latin1");
    assert.equal(huvud, "wOF2", `${relativ} är ingen woff2-fil (magi: ${JSON.stringify(huvud)})`);

    assert.match(face["font-display"] || "", /swap/,
      `${familj} saknar font-display:swap - utan swap är texten OSYNLIG medan ` +
      "typsnittet laddas i stället för satt i fallbacken");
  }
});

test("de vikter och stilar styles.css använder täcks av ett @font-face", () => {
  const faces = fontFaces(css);
  const täcker = (familj, vikt, stil) => faces.some((f) => {
    if (!(f["font-family"] || "").includes(familj)) return false;
    if ((f["font-style"] || "normal") !== stil) return false;
    const [min, max = min] = (f["font-weight"] || "400").split(/\s+/).map(Number);
    return vikt >= min && vikt <= max;
  });

  // Hämtade ur styles.css, inte ur designsystemets tabell: filen sätter
  // Newsreader i 400 och 700, Archivo i 400/500/600/700, och kursiv Archivo
  // på <em> i ingredienslistan och på tidsstämpeln i butiksjämförelsen.
  for (const vikt of [400, 700]) {
    assert.ok(täcker("Newsreader", vikt, "normal"), `Newsreader ${vikt} saknar snitt`);
  }
  for (const vikt of [400, 500, 600, 700]) {
    assert.ok(täcker("Archivo", vikt, "normal"), `Archivo ${vikt} saknar snitt`);
  }
  assert.ok(täcker("Archivo", 400, "italic"),
    "styles.css sätter font-style:italic men inget kursivt snitt är deklarerat - " +
    "webbläsaren lutar det raka snittet på egen hand, och det syns");
});

test("fallbackstacken är satt så att sidan är läsbar innan typsnittet laddat", () => {
  // Ett buntat typsnitt laddar snabbt, men inte omedelbart - och laddar det
  // inte alls (trasig sökväg, korrupt fil) är stacken det enda som står kvar.
  for (const [token, buntad, fallback] of [
    ["--f-disp", "Newsreader", ["Georgia", "serif"]],
    ["--f-ui", "Archivo", ["Helvetica", "sans-serif"]],
  ]) {
    const m = new RegExp(`${token}\\s*:\\s*([^;]+);`).exec(css);
    assert.ok(m, `${token} finns inte i styles.css`);
    const stack = m[1];
    assert.ok(stack.includes(buntad), `${token} börjar inte med ${buntad}`);
    for (const namn of fallback) {
      assert.ok(stack.includes(namn),
        `${token} saknar ${namn} - utan en riktig fallback är sidan satt i ` +
        "webbläsarens standardsnitt när typsnittet inte kommit fram");
    }
  }
});

test("licensen följer med typsnitten", () => {
  // OFL 1.1 §2: licenstexten ska följa med varje kopia av fonten. Ett publikt
  // repo som buntar en font utan licensfil bryter mot villkoret för att få
  // bunta den över huvud taget.
  const filer = readdirSync(fontKatalog);
  const licenser = filer.filter((f) => /^(OFL|LICENSE|COPYING)/i.test(f));
  const typsnitt = filer.filter((f) => f.endsWith(".woff2"));

  assert.ok(typsnitt.length > 0, "inga woff2-filer i assets/fonts/");
  assert.ok(licenser.length > 0,
    `assets/fonts/ innehåller ${typsnitt.join(", ")} men ingen licensfil`);
  for (const licens of licenser) {
    const text = readFileSync(join(fontKatalog, licens), "utf8");
    assert.match(text, /SIL Open Font License/i, `${licens} är inte en OFL-text`);
    assert.match(text, /PERMISSION\s*&\s*CONDITIONS/i,
      `${licens} ser avkortad ut - hela licenstexten ska följa med, inte en rad om den`);
  }

  // En familj utan licensfil är lika fel som ingen licensfil alls.
  for (const familj of ["Archivo", "Newsreader"]) {
    assert.ok(licenser.some((f) => f.toLowerCase().includes(familj.toLowerCase())),
      `ingen licensfil nämner ${familj}`);
  }
});

test("typsnitten är spårade källfiler, inte något .gitignore råkar svälja", () => {
  // A3:s CI-grind vägrar spårade byggartefakter. Fonterna är källa: de byggs
  // inte, de kopieras. Motsatsen - att ett mönster i .gitignore råkar matcha
  // assets/fonts/ - är tystare och värre: filerna finns lokalt, testerna är
  // gröna, och bygget i CI saknar dem.
  const relativa = readdirSync(fontKatalog).map((f) => `frontend/app/assets/fonts/${f}`);
  const spårade = execFileSync("git", ["-C", rot, "ls-files", "--", "frontend/app/assets/fonts/"],
    { encoding: "utf8" }).split("\n").filter(Boolean);
  for (const fil of relativa) {
    assert.ok(spårade.includes(fil), `${fil} är inte spårad i git`);
  }
});

test("bygget tar med typsnitten (npm run build:native)", () => {
  const ut = mkdtempSync(join(tmpdir(), "matjakt-typsnitt-"));
  try {
    execFileSync(process.execPath,
      [join(rot, "scripts", "build_frontend.mjs"), ut, "--native", "--api-url=https://matjakt.onrender.com/api"],
      { stdio: "pipe" });

    const byggdFontKatalog = join(ut, "app", "assets", "fonts");
    assert.ok(existsSync(byggdFontKatalog), "dist/native/app/assets/fonts/ saknas i bygget");

    for (const face of fontFaces(css)) {
      const relativ = /url\(\s*["']?([^"')]+)["']?\s*\)/.exec(face.src)[1].split("?")[0];
      assert.ok(existsSync(join(ut, "app", normalize(relativ))),
        `${relativ} kom inte med i bygget - @font-face pekar i tomma luften i den ` +
        "app som faktiskt paketeras");
    }

    // Minifieringen får inte skriva om url():erna till något annat.
    const byggdCss = readFileSync(join(ut, "app", "styles.css"), "utf8");
    assert.match(byggdCss, /assets\/fonts\//, "url() till assets/fonts/ överlevde inte minifieringen");
    for (const värd of GOOGLES_FONTVÄRDAR) {
      assert.ok(!byggdCss.includes(värd), `${värd} i den byggda styles.css`);
      assert.ok(!readFileSync(join(ut, "app", "index.html"), "utf8").includes(värd),
        `${värd} i den byggda index.html`);
    }
  } finally {
    rmSync(ut, { recursive: true, force: true });
  }
});
