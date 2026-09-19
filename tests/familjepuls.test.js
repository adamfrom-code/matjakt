// W1 Familjepuls: händelser blir meningar, tider blir relativa, och panelen
// finns bara bakom flaggan hushall.puls.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { handelseText, pulsMarkup, relativTid } from "../frontend/app/src/views/familjepuls.js";

const läs = rel => readFileSync(new URL(`../${rel}`, import.meta.url), "utf8");

test("kända typer blir meningar, okända en läsbar reserv - aldrig tomt", () => {
  assert.equal(handelseText({ type: "household.shopping_item_added", payload: { name: "Mjölk" } }), "lade till Mjölk");
  assert.equal(handelseText({ type: "household.member_joined", payload: {} }), "gick med i hushållet");
  assert.equal(handelseText({ type: "household.week_changed" }), "ändrade veckan");
  assert.equal(handelseText({ type: "household.nagot_nytt", payload: { subject: "Tacos" } }), "nagot nytt: Tacos");
  assert.equal(handelseText({ type: "", payload: {} }), "gjorde något");
  assert.equal(handelseText(null), "gjorde något");
});

test("relativ tid: nyss, minuter, timmar, dagar, sedan datum", () => {
  const nu = Date.parse("2026-09-19T12:00:00Z");
  assert.equal(relativTid("2026-09-19T11:59:40Z", nu), "nyss");
  assert.equal(relativTid("2026-09-19T11:55:00Z", nu), "för 5 min sedan");
  assert.equal(relativTid("2026-09-19T10:00:00Z", nu), "för 2 h sedan");
  assert.equal(relativTid("2026-09-18T12:00:00Z", nu), "för 1 dag sedan");
  assert.equal(relativTid("2026-09-16T12:00:00Z", nu), "för 3 dagar sedan");
  assert.match(relativTid("2026-08-01T12:00:00Z", nu), /2026/);
  assert.equal(relativTid("trasigt", nu), "");
});

test("markupen: du/namn/Någon, escapad, tom lista har en mening", () => {
  const nu = Date.parse("2026-09-19T12:00:00Z");
  const html = pulsMarkup([
    { type: "household.shopping_item_added", actor: "Sara", isMe: false, createdAt: "2026-09-19T10:00:00Z", payload: { name: "<b>Mjölk</b>" } },
    { type: "household.member_joined", actor: null, isMe: true, createdAt: "2026-09-19T11:59:50Z", payload: {} },
    { type: "household.inventory_changed", actor: null, isMe: false, createdAt: "2026-09-19T11:00:00Z", payload: {} },
  ], { now: nu });
  assert.match(html, /<strong>Sara<\/strong> lade till &lt;b&gt;Mjölk&lt;\/b&gt;<small>för 2 h sedan<\/small>/);
  assert.match(html, /<strong>Du<\/strong> gick med i hushållet<small>nyss<\/small>/);
  assert.match(html, /<strong>Någon<\/strong> ändrade i skafferiet/);
  assert.match(pulsMarkup([]), /Inget har hänt i hushållet än/);
});

test("panelen ritas bara bakom flaggan och hämtas en gång per hushållsrevision", () => {
  const account = läs("frontend/app/src/views/account.js");
  const start = account.indexOf("function renderFamiljepuls");
  const body = account.slice(start, account.indexOf("\n}\n", start));
  assert.match(body, /app\.flagga\("hushall\.puls"\) && app\.householdActive\(\)/);
  assert.match(body, /panel\.hidden = !pa/);
  assert.match(body, /fetchEvents\(state\.authToken, 30\)/);
  assert.match(body, /pulsHamtadFor === nyckel/);
  assert.match(läs("frontend/app/index.html"), /<details class="household-puls-panel" id="householdPulsPanel" hidden>/);
  assert.match(läs("frontend/app/src/api/household.js"), /fetchEvents = \(token, limit = 30\) => get\(`\/events\?limit=/);
});
