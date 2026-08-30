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
