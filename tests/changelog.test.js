// A4:s acceptanskriterium: två agenter kan skriva changelog samtidigt utan
// konflikt. Det är inte en åsikt om filformat - det är ett påstående om git,
// och därför prövas det mot ett riktigt git-arbetsträd.
//
// Testet bevisar BÅDA riktningarna. Att det nya sättet fungerar säger
// ingenting om det inte också visas att det gamla faktiskt gick sönder.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

test("CHECKPOINT.md säger att den inte ska redigeras direkt", () => {
  const text = readFileSync(join(root, "CHECKPOINT.md"), "utf8");
  assert.match(text, /changelog\.d/,
    "CHECKPOINT.md pekar inte på docs/changelog.d - då kommer nästa agent att redigera den direkt");
});
