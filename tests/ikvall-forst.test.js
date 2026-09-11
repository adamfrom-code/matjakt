// G2:s acceptanskriterium: att `order` faktiskt sätter Ikväll först.
//
// `styles.css` sa `.home-screen>.week-card{order:1}` och
// `.home-screen>.next-meal-section{order:2}` - tvärtemot kommentaren i
// index.html som stod två rader ovanför markupen och sa "IKVÄLL FÖRST".
// Kommentaren hade rätt om avsikten och fel om verkligheten, och ingenting
// i bygget kunde se skillnaden.
//
// Därför prövas inte de två talen mot varandra. Testet räknar ut den ORDNING
// SKÄRMEN FAKTISKT FÅR: index.html ger barnen till .home-screen i
// dokumentordning, styles.css ger varje barn sitt `order`, och flexlayoutens
// egen regel - sortera på order, behåll dokumentordning inom samma värde -
// ger resultatet. Då fångas också den som lägger ett nytt block med order:0
// eller flyttar markupen i stället för CSS:en.

import assert from "node:assert/strict";
import test from "node:test";
import { deklarationer, läsFil, läsStyles, lösVar, parseRegler, rotVariabler }
  from "./fixtures/css-parser.mjs";

const css = läsStyles();
const html = läsFil("frontend/app/index.html");
const regler = parseRegler(css);
const vars = rotVariabler(regler);

/** Direkta barn till ett element, i dokumentordning, med sina klasser. */
function barnTill(markup, startTagg) {
  const start = markup.indexOf(startTagg);
  assert.notEqual(start, -1, `hittade inte ${startTagg} i index.html`);
  let i = markup.indexOf(">", start) + 1;
  let djup = 0;
  const barn = [];
  const taggar = /<(\/?)([a-z][\w-]*)([^>]*)>/gi;
  taggar.lastIndex = i;
  for (let m; (m = taggar.exec(markup)); ) {
    const [hel, slut, namn, attr] = m;
    if (/\/>$/.test(hel) || /^(br|hr|img|input|meta|link|source|path|rect|circle|use)$/i.test(namn)) continue;
    if (slut) {
      if (djup === 0) break;                       // stängde behållaren
      djup--;
      continue;
    }
    if (djup === 0) {
      const klass = /class="([^"]*)"/.exec(attr);
      barn.push({ namn, klasser: klass ? klass[1].split(/\s+/).filter(Boolean) : [] });
    }
    djup++;
  }
  return barn;
}

/** Det `order` styles.css ger ett barn, sist vinner. 0 om inget sätts. */
function orderFör(klasser) {
  let order = 0;
  for (const r of regler) {
    if (r.media.length) continue;                  // basordningen, inte desktopnätet
    for (const del of r.delar) {
      const m = /^\.home-screen>\.([\w-]+)$/.exec(del.trim());
      if (!m || !klasser.includes(m[1])) continue;
      for (const d of deklarationer(r.block)) {
        if (d.prop === "order") order = parseInt(lösVar(d.värde, vars), 10);
      }
    }
  }
  return order;
}

test("startsidan är en flexkolumn - annars betyder order ingenting alls", () => {
  const layout = regler.filter((r) => !r.media.length
    && r.delar.some((d) => /\.home-screen$/.test(d.trim())));
  const platt = layout.flatMap((r) => deklarationer(r.block));
  assert.ok(platt.some((d) => d.prop === "display" && d.värde.trim() === "flex"),
    ".home-screen är inte display:flex - order-egenskapen ignoreras då tyst");
  assert.ok(platt.some((d) => d.prop === "flex-direction" && d.värde.trim() === "column"),
    ".home-screen är inte en kolumn");
});

test("kvällens middag ritas före budgeten på startsidan", () => {
  const barn = barnTill(html, '<section class="screen home-screen"')
    .map((b, i) => ({ ...b, dok: i, order: orderFör(b.klasser) }))
    .sort((a, b) => a.order - b.order || a.dok - b.dok);

  const plats = (klass) => barn.findIndex((b) => b.klasser.includes(klass));
  const ikväll = plats("next-meal-section");
  const vecka = plats("week-card");

  assert.notEqual(ikväll, -1, "next-meal-section finns inte längre på startsidan");
  assert.notEqual(vecka, -1, "week-card finns inte längre på startsidan");
  assert.ok(ikväll < vecka,
    "budgetkortet ritas före kvällens middag.\n" +
    "Ordningen skärmen får:\n" +
    barn.map((b, i) => `  ${i + 1}. ${b.klasser[0] || b.namn} (order:${b.order})`).join("\n") +
    "\n\nEn trött förälder klockan 16:10 ska mötas av kvällens mat, inte av en\n" +
    "budgetmätare. Budgetverktyg öppnar man en gång i månaden; middagsappar\n" +
    "öppnar man varje dag.");
});

test("budgeten är en smal rad, inte sidans största element", () => {
  // Kronbeloppet stod i 54px - större än allt annat på startsidan, inklusive
  // rättens namn. Under maten hör den hemma i brödtextstorlek.
  let font = null;
  for (const r of regler) {
    if (!r.delar.includes(".week-budget-text strong")) continue;
    for (const d of deklarationer(r.block)) {
      if (d.prop === "font" || d.prop === "font-size") font = lösVar(d.värde, vars);
    }
  }
  assert.ok(font, ".week-budget-text strong har ingen storlek längre");
  const px = parseFloat(/(\d*\.?\d+)px/.exec(font)?.[1] ?? "0");
  assert.ok(px > 0 && px <= 20,
    `kronbeloppet står i ${px}px - budgeten ska vara en rad under maten, inte hjälterubriken`);
});

test("fliken heter samma sak som skärmen lovar", () => {
  const nav = /<button class="bottom-nav-item[^"]*" type="button" data-view="home">[\s\S]*?<small>([^<]*)<\/small>/
    .exec(html);
  assert.ok(nav, "hem-fliken hittades inte i bottennavigeringen");
  assert.equal(nav[1], "Ikväll",
    "fliken heter något annat än skärmen levererar - namnet är ett löfte");
});
