// Native-bygget (scripts/build_frontend.mjs --native --api-url=...) är det
// som Capacitor paketerar. Det får bara skilja sig från webbygget på två
// punkter: API-adressen i metataggen och det borttagna statistikskriptet.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const script = join(root, "scripts", "build_frontend.mjs");

test("native-bygget bär produktionens API-adress och inget landningsskript", () => {
  const out = mkdtempSync(join(tmpdir(), "matjakt-native-"));
  try {
    execFileSync(process.execPath, [script, out, "--native", "--api-url=https://matjakt.onrender.com/api"], { stdio: "pipe" });
    const index = readFileSync(join(out, "app", "index.html"), "utf8");
    assert.match(index, /<meta name="matjakt-api-url" content="https:\/\/matjakt\.onrender\.com\/api">/);
    assert.doesNotMatch(index, /traffic\.js/);
    assert.ok(existsSync(join(out, "app", "app.js")));
    assert.ok(!existsSync(join(out, "app", "src")), "modulerna ska ligga i bundeln");
    // CSP-metataggen tillåter backend-värden - annars blockeras varje anrop i webviewen.
    assert.match(index, /connect-src [^"]*https:\/\/matjakt\.onrender\.com/);
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});

test("webbygget lämnar metataggen tom (same-origin) och behåller statistikskriptet", () => {
  const out = mkdtempSync(join(tmpdir(), "matjakt-web-"));
  try {
    execFileSync(process.execPath, [script, out], { stdio: "pipe" });
    const index = readFileSync(join(out, "app", "index.html"), "utf8");
    assert.match(index, /<meta name="matjakt-api-url" content="">/);
    assert.match(index, /traffic\.js/);
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});

test("en API-adress som inte är https://<värd>/api avvisas", () => {
  const out = mkdtempSync(join(tmpdir(), "matjakt-bad-"));
  try {
    assert.throws(() => execFileSync(process.execPath, [script, out, "--api-url=http://evil.example/api"], { stdio: "pipe" }));
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
});
