import test from "node:test";
import assert from "node:assert/strict";

// safeHttpUrl resolves against window.location.href, so give Node's ESM (no
// DOM) a minimal stand-in before importing the module under test.
globalThis.window = { location: { href: "https://example.se/" } };
const { escapeHtml, safeHttpUrl } = await import("../frontend/app/src/utils/html.js");

test("escapeHtml neutraliserar taggar och attributbrott", () => {
  assert.equal(escapeHtml(`<b>test</b>`), "&lt;b&gt;test&lt;/b&gt;");
  assert.equal(escapeHtml(`"><img src=x onerror=alert(1)>`), "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;");
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");
});

test("safeHttpUrl släpper igenom http/https men blockar javascript: och data:", () => {
  assert.equal(safeHttpUrl("https://example.se/vara"), "https://example.se/vara");
  assert.equal(safeHttpUrl("javascript:alert(1)"), "");
  assert.equal(safeHttpUrl("data:text/html,<script>alert(1)</script>"), "");
  assert.equal(safeHttpUrl("ftp://example.se/fil", "fallback"), "fallback");
});

test("kontrollrummet vet var backenden finns", async () => {
  // admin.js läser <meta name="matjakt-api-url"> och faller annars tillbaka
  // på "/api". På GitHub Pages pekar "/api" på Pages självt: varje anrop
  // svarar 404, och admin.js översätter 404 till "Fel admin-token" - så
  // felet pekar på token medan problemet är adressen. Lokalt syns det inte,
  // för då ligger /api på samma origin.
  const { readFileSync } = await import("node:fs");
  for (const fil of ["frontend/app/index.html", "frontend/app/admin.html"]) {
    const html = readFileSync(fil, "utf8");
    assert.match(html, /<meta name="matjakt-api-url" content="">/,
                 `${fil} saknar den tomma matjakt-api-url-taggen som deployen fyller i`);
  }
});
