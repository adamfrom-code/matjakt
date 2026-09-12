// Kontrollrummet följer inte med in i appen.
//
// `admin.html` och `admin.js` ligger i `app/` för att backend-servern ska
// kunna servera dem på samma origin som API:t - kontrollrummet är en
// driftsida, inte en konsumentskärm. I ett WEBBYGGE är det rätt: den som
// kan adressen möts ändå av admin-tokengrinden, som svarar 404 för alla
// andra (O12 bevisade det per väg).
//
// I NATIVE-BUNDLET är det fel. Sidan hamnar i en app som laddas ner från App
// Store, och den som packar upp .ipa:n hittar den. Ingen säkerhetslucka -
// grinden ligger på servern - men en granskare som ser en inloggningssida
// för "drift" i en matbudgetapp kommer att fråga, och frågan är dyrare att
// besvara än filen är att utesluta.
//
// Upptäckt när det första arkivet byggdes: `App.app/public/` innehöll
// admin.html och admin.js.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const script = join(root, "scripts", "build_frontend.mjs");

function bygg(...extra) {
  const ut = mkdtempSync(join(tmpdir(), "matjakt-adm-"));
  execFileSync(process.execPath, [script, ut, ...extra], { stdio: "pipe" });
  return ut;
}

test("native-bygget bär inte kontrollrummet", () => {
  const ut = bygg("--native", "--api-url=https://matjakt.onrender.com/api");
  try {
    for (const namn of ["admin.html", "admin.js"]) {
      assert.ok(!existsSync(join(ut, "app", namn)),
        `${namn} ligger i native-bundlet - den hamnar i appen som laddas ner ` +
        `från App Store och syns för den som packar upp .ipa:n`);
    }
    // Och appen ska fortfarande fungera: index och bundle finns kvar.
    assert.ok(existsSync(join(ut, "app", "index.html")));
    assert.ok(existsSync(join(ut, "app", "app.js")));
    assert.ok(existsSync(join(ut, "app", "sw.js")));
  } finally { rmSync(ut, { recursive: true, force: true }); }
});

test("webbygget behåller kontrollrummet", () => {
  // Det här är den andra riktningen, och den är lika viktig: tar någon bort
  // filerna för generellt slutar driftsidan fungera på matjakt.store.
  const ut = bygg();
  try {
    for (const namn of ["admin.html", "admin.js"]) {
      assert.ok(existsSync(join(ut, "app", namn)),
        `${namn} saknas i webbygget - kontrollrummet serveras därifrån`);
    }
  } finally { rmSync(ut, { recursive: true, force: true }); }
});
