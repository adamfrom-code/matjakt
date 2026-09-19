// S1: slaget i kontoarket och flaggan - bara bakom hushall.medlemmar.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { memberKind } from "../frontend/app/src/services/planning-context.js";

const läs = rel => readFileSync(new URL(`../${rel}`, import.meta.url), "utf8");

test("memberKind: serverns kind, annars J3:s child, annars vuxen", () => {
  assert.equal(memberKind({ kind: "guest" }), "guest");
  assert.equal(memberKind({ profile: { child: true } }), "child");
  assert.equal(memberKind({ kind: "drake" }), "adult");
  assert.equal(memberKind(null), "adult");
});

test("kontoarket visar och sparar slaget bara bakom flaggan", () => {
  const account = läs("frontend/app/src/views/account.js");
  assert.match(account, /kindRow\.hidden = !app\.flagga\("hushall\.medlemmar"\)/);
  assert.match(account, /app\.flagga\("hushall\.medlemmar"\) && \$\("householdKind"\) \? \{ kind: \$\("householdKind"\)\.value \} : \{\}/);
  const html = läs("frontend/app/index.html");
  assert.match(html, /<div id="householdKindRow" hidden>/);
  for (const v of ["adult", "child", "guest"]) assert.match(html, new RegExp(`<option value="${v}">`));
  // app.js skickar in flaggan i vyn
  assert.match(läs("frontend/app/app.js"), /initAccountView\(\{\n  flagga,/);
});
