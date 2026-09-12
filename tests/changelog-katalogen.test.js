// Vävningen prövas mot den RIKTIGA katalogen, inte mot en tempkopia.
//
// tests/changelog.test.js bygger upp ett eget litet repo i /tmp med två
// påhittade fragment och väver det. Det testar vävningens LOGIK, och det
// gör det bra - men det säger ingenting om filerna som faktiskt ligger i
// docs/changelog.d/.
//
// Följden: tre fragment (N0d, N0e, N0f) låg på main utan front matter, och
// weave_checkpoint.mjs kastar för HELA katalogen om en enda fil saknar det.
// Ingen releasevävning gick att köra. CI var grön hela tiden.
//
// Ett test som bara prövar sin egen fixtur vaktar ingenting. Det här kör
// skriptet mot repot som det står.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const rot = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const katalog = join(rot, "docs", "changelog.d");

const fragment = readdirSync(katalog)
  .filter((n) => n.endsWith(".md") && n !== "README.md")
  .sort();

test("det finns fragment att väva", () => {
  assert.ok(fragment.length > 0, "docs/changelog.d/ är tom");
});

test("varje fragment har front matter med paket och titel", () => {
  // Per fil, så att felet pekar ut VILKEN fil - vävningens eget
  // felmeddelande gör det också, men det stannar på den första.
  const trasiga = [];
  for (const namn of fragment) {
    const rå = readFileSync(join(katalog, namn), "utf8");
    const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(rå);
    if (!m) {
      trasiga.push(`${namn}: saknar front matter (--- ... ---)`);
      continue;
    }
    const huvud = Object.fromEntries(
      m[1]
        .split(/\r?\n/)
        .map((rad) => /^([a-zA-ZåäöÅÄÖ_]+):\s*(.*)$/.exec(rad.trim()))
        .filter(Boolean)
        .map((p) => [p[1], p[2].trim().replace(/^["']|["']$/g, "")]),
    );
    for (const krav of ["paket", "titel"]) {
      if (!huvud[krav]) trasiga.push(`${namn}: fältet "${krav}" saknas`);
    }
    const filId = namn.replace(/\.md$/, "");
    if (huvud.paket && huvud.paket !== filId) {
      trasiga.push(`${namn}: front matter säger "${huvud.paket}"`);
    }
  }
  assert.deepEqual(trasiga, [], `\n  ${trasiga.join("\n  ")}\n  Se docs/changelog.d/README.md`);
});

test("weave_checkpoint kan köras på repot som det står", () => {
  // Det egentliga beviset: skriptet, inte vår tolkning av det.
  try {
    execFileSync(process.execPath, [join(rot, "scripts", "weave_checkpoint.mjs")], {
      cwd: rot,
      stdio: "pipe",
      encoding: "utf8",
    });
  } catch (e) {
    assert.fail(
      `weave_checkpoint.mjs kastade - en release går inte att väva:\n` +
        `${(e.stderr || e.message).split("\n").slice(0, 4).join("\n")}`,
    );
  }
});
