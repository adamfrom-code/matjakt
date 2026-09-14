// A4:s acceptanskriterium: två agenter kan skriva changelog samtidigt utan
// konflikt. Det är inte en åsikt om filformat - det är ett påstående om git,
// och därför prövas det mot ett riktigt git-arbetsträd.
//
// Testet bevisar BÅDA riktningarna. Att det nya sättet fungerar säger
// ingenting om det inte också visas att det gamla faktiskt gick sönder.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { läsFragment, väv } from "../scripts/weave_checkpoint.mjs";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

function git(cwd, ...arg) {
  return execFileSync("git", arg, { cwd, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] });
}

/** Två grenar från samma bas, var sin ändring, sedan merge. Returnerar om det konfliktade. */
function tvåAgenterSkriver(förbered, agentA, agentB) {
  const rep = mkdtempSync(join(tmpdir(), "matjakt-changelog-"));
  try {
    git(rep, "init", "-q", "-b", "main");
    git(rep, "config", "user.email", "test@matjakt.local");
    git(rep, "config", "user.name", "Test");
    förbered(rep);
    git(rep, "add", "-A");
    git(rep, "commit", "-q", "-m", "bas");

    git(rep, "checkout", "-q", "-b", "paket-a");
    agentA(rep);
    git(rep, "add", "-A");
    git(rep, "commit", "-q", "-m", "agent A");

    git(rep, "checkout", "-q", "main");
    git(rep, "checkout", "-q", "-b", "paket-b");
    agentB(rep);
    git(rep, "add", "-A");
    git(rep, "commit", "-q", "-m", "agent B");

    // Båda mergas till main, som när två PR:er går in efter varandra.
    git(rep, "checkout", "-q", "main");
    git(rep, "merge", "-q", "--no-edit", "paket-a");
    try {
      git(rep, "merge", "--no-edit", "paket-b");
      return { konflikt: false, rep };
    } catch (fel) {
      return { konflikt: true, rep, meddelande: `${fel.stdout || ""}${fel.stderr || ""}` };
    }
  } finally {
    // rep behövs efter retur i det gröna fallet - städas av anroparen.
  }
}

const fragment = (paket, titel, text) =>
  `---\npaket: ${paket}\ntitel: ${titel}\n---\n\n${text}\n`;

test("två agenter som lägger var sitt fragment kolliderar inte", () => {
  const { konflikt, rep, meddelande } = tvåAgenterSkriver(
    r => { mkdirSync(join(r, "docs", "changelog.d"), { recursive: true });
           writeFileSync(join(r, "docs", "changelog.d", "README.md"), "# fragment\n"); },
    r => writeFileSync(join(r, "docs", "changelog.d", "C2.md"),
                       fragment("C2", "Multipack", "390 g 4-pack lästes som 390 g.")),
    r => writeFileSync(join(r, "docs", "changelog.d", "B7.md"),
                       fragment("B7", "Reset-token i adressfältet", "Token stod kvar i URL:en.")));
  try {
    assert.equal(konflikt, false, `merge konfliktade: ${meddelande}`);
    // Och båda finns kvar - en merge som "lyckas" genom att tappa ena sidan
    // vore värre än en konflikt.
    for (const fil of ["C2.md", "B7.md"]) {
      assert.ok(readFileSync(join(rep, "docs", "changelog.d", fil), "utf8").includes("paket:"),
                `${fil} överlevde inte mergen`);
    }
  } finally { rmSync(rep, { recursive: true, force: true }); }
});

test("samma två agenter i CHECKPOINT.md konfliktar - det är därför katalogen finns", () => {
  const bas = "# Checkpoint\n\n## Senaste\n\n- rad ett\n";
  const { konflikt, rep } = tvåAgenterSkriver(
    r => writeFileSync(join(r, "CHECKPOINT.md"), bas),
    r => writeFileSync(join(r, "CHECKPOINT.md"), bas.replace("- rad ett", "- C2: multipack\n- rad ett")),
    r => writeFileSync(join(r, "CHECKPOINT.md"), bas.replace("- rad ett", "- B7: reset-token\n- rad ett")));
  try {
    assert.equal(konflikt, true,
      "CHECKPOINT.md konfliktade INTE - då är premissen för A4 fel och testet ovan bevisar inget");
  } finally { rmSync(rep, { recursive: true, force: true }); }
});

test("vävningen sorterar A1 < A2 < A10 < B1, inte alfabetiskt", () => {
  const kat = mkdtempSync(join(tmpdir(), "matjakt-vav-"));
  try {
    for (const [id, titel] of [["B1", "Stripe"], ["A10", "Tionde"], ["A2", "Andra"], ["A1", "Första"]]) {
      writeFileSync(join(kat, `${id}.md`), fragment(id, titel, `Text för ${id}.`));
    }
    assert.deepEqual(läsFragment(kat).map(f => f.paket), ["A1", "A2", "A10", "B1"]);
    const ut = väv(läsFragment(kat), "v1.0");
    assert.ok(ut.indexOf("A2 · Andra") < ut.indexOf("A10 · Tionde"), "A10 hamnade före A2");
    assert.match(ut, /^## v1\.0 — \d{4}-\d{2}-\d{2}$/m);
  } finally { rmSync(kat, { recursive: true, force: true }); }
});

test("ett fragment vars filnamn inte matchar paket-ID avvisas", () => {
  const kat = mkdtempSync(join(tmpdir(), "matjakt-vav-"));
  try {
    writeFileSync(join(kat, "C2.md"), fragment("C3", "Fel ID", "..."));
    assert.throws(() => läsFragment(kat), /heter "C2"/);
  } finally { rmSync(kat, { recursive: true, force: true }); }
});

test("front matter som saknas eller är ofullständig avvisas", () => {
  const kat = mkdtempSync(join(tmpdir(), "matjakt-vav-"));
  try {
    writeFileSync(join(kat, "C2.md"), "Bara text, ingen front matter.\n");
    assert.throws(() => läsFragment(kat), /front matter/);
    writeFileSync(join(kat, "C2.md"), "---\npaket: C2\n---\n\nIngen titel.\n");
    assert.throws(() => läsFragment(kat), /"titel" saknas/);
  } finally { rmSync(kat, { recursive: true, force: true }); }
});

// A4b: de fem testerna ovan prövar vävningen mot temporära kataloger. Ingen
// av dem läser den riktiga docs/changelog.d/ - och därför kunde tre fragment
// utan front matter mergas gröna och blockera varje release. Grinden som
// saknades är den enklaste: väv det som faktiskt ligger i repot.
const FRAGMENTKATALOG = join(root, "docs", "changelog.d");
const CHECKPOINT_MD = join(root, "CHECKPOINT.md");

test("varje fragment i docs/changelog.d/ går faktiskt att väva", () => {
  const filer = readdirSync(FRAGMENTKATALOG)
    .filter(namn => namn.endsWith(".md") && namn !== "README.md")
    .sort();
  assert.ok(filer.length > 0, "inga fragment att pröva - då bevisar testet inget");

  // läsFragment kastar på första trasiga filen. Felmeddelandet namnger den,
  // och det är den enda uppgift den som ska laga det behöver.
  const fragment = läsFragment(FRAGMENTKATALOG);

  assert.deepEqual(fragment.map(f => f.fil).sort(), filer,
    "vävningen tappade eller hittade på fragment");

  // Och resultatet måste innehålla varenda ett. En väv som "lyckas" med
  // halva katalogen är ett tystare fel än ett kast.
  const ut = väv(fragment, "PROV");
  for (const f of fragment) {
    assert.ok(ut.includes(`### ${f.paket} · ${f.titel}`),
      `${f.fil} kom inte med i det vävda avsnittet`);
  }
});

test("ett fragment upprepar inte sin egen titel som rubrik i kroppen", () => {
  // väv() skriver redan "### <paket> · <titel>". Ett fragment som dessutom
  // öppnar med sin titel som rubrik får den två gånger i CHECKPOINT.md.
  // Underrubriker längre ned är däremot husets sätt att skriva - K6 och N0b
  // är båda avsiktligt indelade.
  for (const f of läsFragment(FRAGMENTKATALOG)) {
    const rubrik = /^#{1,6}\s+(.+?)\s*$/m.exec(f.text.split(/\r?\n/)[0]);
    if (!rubrik) continue;
    assert.notEqual(rubrik[1].toLocaleLowerCase("sv"), f.titel.toLocaleLowerCase("sv"),
      `${f.fil} öppnar med sin egen titel som rubrik - den står redan i front matter`);
  }
});

// A6: testerna ovan anropar läsFragment() och väv() som funktioner. Det
// bevisar att logiken håller - men det var inte logiken som var trasig, det
// var kommandot. `node scripts/weave_checkpoint.mjs` kastade på main medan
// CI stod grön, för ingenting körde någonsin skriptet som skript.
test("weave_checkpoint.mjs går att köra som kommando", () => {
  const före = readFileSync(CHECKPOINT_MD, "utf8");
  let ut;
  try {
    ut = execFileSync(process.execPath, [join(root, "scripts", "weave_checkpoint.mjs")],
      { cwd: root, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] });
  } catch (fel) {
    assert.fail("`node scripts/weave_checkpoint.mjs` gick inte att köra - ingen release kan vävas:\n" +
      (fel.stderr || fel.message).trim().split(/\r?\n/).slice(0, 3).map(r => `  ${r}`).join("\n"));
  }

  // Varje fragment ska synas i utskriften. "Den kraschade inte" är ett
  // svagare påstående än "den skrev ut allt som skulle med".
  for (const f of läsFragment(FRAGMENTKATALOG)) {
    assert.ok(ut.includes(`### ${f.paket} · ${f.titel}`),
      `${f.fil} saknas i torrkörningens utskrift`);
  }

  // Skriptets egen utfästelse, ur dess huvudkommentar: utan --apply skrivs
  // bara resultatet till stdout. Ett släppverktyg som ändrar filer när man
  // bara ville titta blir ett verktyg ingen vågar köra.
  assert.equal(readFileSync(CHECKPOINT_MD, "utf8"), före,
    "torrkörningen skrev i CHECKPOINT.md - utan --apply ska den bara skriva till stdout");
});

test("CHECKPOINT.md säger att den inte ska redigeras direkt", () => {
  const text = readFileSync(CHECKPOINT_MD, "utf8");
  assert.match(text, /changelog\.d/,
    "CHECKPOINT.md pekar inte på docs/changelog.d - då kommer nästa agent att redigera den direkt");
});
