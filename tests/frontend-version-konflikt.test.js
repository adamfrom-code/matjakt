// L9:s acceptanskriterium: två grenar som var för sig ändrar frontend/app/**
// mergas utan konflikt.
//
// Det är inte en åsikt om filformat - det är ett påstående om git, och därför
// prövas det mot riktiga git-arbetsträd. Samma bevisform som A4:s
// changelog-test, och av samma skäl: ett grönt test som inte också visar att
// det GAMLA sättet gick sönder bevisar ingenting om att premissen stämmer.
//
// Premissen är mätt. Natten mellan 11 och 12 september låg G5 `DIRTY` med grön
// CI i fyra timmar utan ägare kvar, och D11 konfliktade fyra gånger, baserades
// om lika många, började på v56 och landade på v107. Båda konflikterna var
// enbart de tre versionsraderna - ingen kodkonflikt någonsin.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { PLACEHOLDER, cacheStamp, collectFiles } from "../scripts/frontend_version.mjs";

function git(cwd, ...arg) {
  return execFileSync("git", arg, { cwd, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] });
}

/** Det som står i källan efter L9: ingen version, en platshållare. */
const utanTal = {
  "sw.js": `// app shell\nconst CACHE_NAME = "matjakt-shell-v${PLACEHOLDER}";\n`,
  "index.html": `<!doctype html>\n<link rel="stylesheet" href="styles.css?v=${PLACEHOLDER}">\n`
    + `<script type="module" src="app.js?v=${PLACEHOLDER}"></script>\n`,
};

/** Det som stod i källan före L9: samma tal på tre rader i två filer. */
const medTal = v => ({
  "sw.js": `// app shell\nconst CACHE_NAME = "matjakt-shell-v${v}";\n`,
  "index.html": `<!doctype html>\n<link rel="stylesheet" href="styles.css?v=${v}">\n`
    + `<script type="module" src="app.js?v=${v}"></script>\n`,
});

function skriv(rep, filer) {
  mkdirSync(join(rep, "frontend", "app"), { recursive: true });
  for (const [namn, innehåll] of Object.entries(filer)) {
    writeFileSync(join(rep, "frontend", "app", namn), innehåll);
  }
}

function nyttRepo(bas) {
  const rep = mkdtempSync(join(tmpdir(), "matjakt-l9-"));
  git(rep, "init", "-q", "-b", "main");
  git(rep, "config", "user.email", "test@matjakt.local");
  git(rep, "config", "user.name", "Test");
  skriv(rep, { "app.js": "// app\n", "styles.css": ":root{}\n", ...bas });
  git(rep, "add", "-A");
  git(rep, "commit", "-q", "-m", "bas");
  return rep;
}

const huvudet = rep => git(rep, "rev-parse", "HEAD").trim();

function gren(rep, namn, arbete) {
  git(rep, "checkout", "-q", "main");
  git(rep, "checkout", "-q", "-b", namn);
  arbete(rep);
  git(rep, "add", "-A");
  git(rep, "commit", "-q", "-m", namn);
}

/**
 * Två grenar från samma bas, var sin ändring under frontend/app/, sedan båda
 * in i main - som när två PR:er går in efter varandra. Returnerar om den
 * andra mergen konfliktade, och i så fall på vilka filer.
 */
function tvåGrenarRörFrontenden(bas, agentA, agentB) {
  const rep = nyttRepo(bas);
  const utgångsläge = huvudet(rep);
  gren(rep, "paket-a", agentA);
  gren(rep, "paket-b", agentB);
  git(rep, "checkout", "-q", "main");
  git(rep, "merge", "-q", "--no-edit", "paket-a");
  try {
    git(rep, "merge", "--no-edit", "paket-b");
    return { konflikt: false, rep, utgångsläge };
  } catch (fel) {
    const krockande = git(rep, "diff", "--name-only", "--diff-filter=U").trim().split("\n").filter(Boolean);
    return { konflikt: true, rep, utgångsläge, krockande, meddelande: `${fel.stdout || ""}${fel.stderr || ""}` };
  }
}

// Agenternas arbete. Exakt samma kodändringar i båda världarna - det enda som
// skiljer är om paketet också måste röra versionen.
const rörAppJs = rep => writeFileSync(join(rep, "frontend/app/app.js"), "// G5: ikväll-vyn\n");
const rörCss = rep => writeFileSync(join(rep, "frontend/app/styles.css"), ":root{--x:1}\n");
const ochBumpar = (arbete, v) => rep => { arbete(rep); skriv(rep, medTal(v)); };

test("L9: två grenar som var för sig ändrar frontend/app/** mergas utan konflikt", () => {
  const { konflikt, rep, meddelande } = tvåGrenarRörFrontenden(utanTal, rörAppJs, rörCss);
  try {
    assert.equal(konflikt, false, `merge konfliktade: ${meddelande}`);
    // Och båda ändringarna finns kvar - en merge som "lyckas" genom att tappa
    // ena sidan vore värre än en konflikt.
    assert.match(readFileSync(join(rep, "frontend/app/app.js"), "utf8"), /ikväll-vyn/);
    assert.match(readFileSync(join(rep, "frontend/app/styles.css"), "utf8"), /--x:1/);
    // Versionen är orörd av båda, för den står inte där.
    assert.match(readFileSync(join(rep, "frontend/app/sw.js"), "utf8"),
                 new RegExp(`matjakt-shell-v${PLACEHOLDER}`));
  } finally { rmSync(rep, { recursive: true, force: true }); }
});

test("L9: samma två ändringar med talet kvar i källan KONFLIKTAR - och bara på versionsraderna", () => {
  // Före L9 var bumpen obligatorisk (K5 krävde HÖJD version), och två grenar
  // som räknade fram sitt tal vid olika tillfällen fick olika tal. Det är
  // D11:s natt, ordagrant.
  const { konflikt, rep, krockande } = tvåGrenarRörFrontenden(
    medTal(106), ochBumpar(rörAppJs, 107), ochBumpar(rörCss, 108));
  try {
    assert.equal(konflikt, true,
      "talet i källan konfliktade INTE - då är premissen för L9 fel och testet ovan bevisar inget");
    assert.deepEqual(krockande.sort(), ["frontend/app/index.html", "frontend/app/sw.js"],
      "konflikten ska vara enbart versionsraderna - app.js och styles.css rörde aldrig varandra");
  } finally { rmSync(rep, { recursive: true, force: true }); }
});

test("L9: med talet i källan konfliktar också OMBASERINGEN - det var därför D11 baserades om fyra gånger", () => {
  // Merge är inte den enda vägen in. main är skyddad med strict, så en gren
  // som ligger efter MÅSTE basera om, och då krockar dess 106 -> 107 med ett
  // main som under tiden gått till 108. Fyra gånger på D11:s natt.
  //
  // (Hade båda råkat välja samma tal hade git slagit ihop dem tyst - det är
  // hela skälet till att talet aldrig kunde göras konfliktfritt genom att bara
  // räkna smartare. Två grenar som räknar vid olika tillfällen får olika tal.)
  const rep = nyttRepo(medTal(106));
  try {
    gren(rep, "paket-a", ochBumpar(rörAppJs, 108));
    gren(rep, "paket-b", ochBumpar(rörCss, 107));
    git(rep, "checkout", "-q", "main");
    git(rep, "merge", "-q", "--no-edit", "paket-a");
    git(rep, "checkout", "-q", "paket-b");
    assert.throws(() => git(rep, "rebase", "main"),
      "ombaseringen gick rent - då fanns inte den konflikt D11 baserades om fyra gånger för");
    assert.deepEqual(git(rep, "diff", "--name-only", "--diff-filter=U").trim().split("\n").sort(),
                     ["frontend/app/index.html", "frontend/app/sw.js"]);
    git(rep, "rebase", "--abort");
  } finally { rmSync(rep, { recursive: true, force: true }); }
});

test("L9: utan talet går samma ombasering rent", () => {
  const rep = nyttRepo(utanTal);
  try {
    gren(rep, "paket-a", rörAppJs);
    gren(rep, "paket-b", rörCss);
    git(rep, "checkout", "-q", "main");
    git(rep, "merge", "-q", "--no-edit", "paket-a");
    git(rep, "checkout", "-q", "paket-b");
    git(rep, "rebase", "main");
    assert.match(readFileSync(join(rep, "frontend/app/app.js"), "utf8"), /ikväll-vyn/);
    assert.match(readFileSync(join(rep, "frontend/app/styles.css"), "utf8"), /--x:1/);
  } finally { rmSync(rep, { recursive: true, force: true }); }
});

test("L9: konfliktfriheten är inte köpt med cache-säkerheten - stämpeln byter ändå", () => {
  // Den enda invändning som betyder något mot att ta bort talet: fanns det
  // där för att tvinga fram en NY cache-nyckel? Nej - nyckeln är numera en
  // digest över allt som byggs, så var och en av de två ändringarna byter den,
  // och den sammanslagna byter den till ett tredje värde. Ingen av grenarna
  // behövde veta något om den andra för att det skulle gälla.
  const { konflikt, rep, utgångsläge } = tvåGrenarRörFrontenden(utanTal, rörAppJs, rörCss);
  try {
    assert.equal(konflikt, false);
    const stämpel = () => cacheStamp(110, collectFiles(join(rep, "frontend", "app")));
    const efterBåda = stämpel();
    git(rep, "checkout", "-q", utgångsläge);         // före båda paketen
    const före = stämpel();
    git(rep, "checkout", "-q", "paket-a");           // bara det ena paketet
    const baraA = stämpel();
    assert.notEqual(efterBåda, före, "den sammanslagna frontenden fick samma cache-nyckel som den gamla");
    assert.notEqual(efterBåda, baraA, "två paket in gav samma nyckel som ett - då hade det andra aldrig nått en telefon");
    assert.notEqual(baraA, före);
  } finally { rmSync(rep, { recursive: true, force: true }); }
});
