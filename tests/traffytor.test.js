// G5:s acceptanskriterium: ett test som läser styles.css och failar på varje
// interaktiv regel under 44 px.
//
// Fjorton kända träffytor stod i rivningslistan, och genomgången hittade
// tjugofem till. Den värsta var inte den minsta: `.week-sheet-plus` på 28x28
// är ENDA vägen till kost och allergier - det mest säkerhetskritiska i hela
// appen - och den satt i ett hörn, omärkt, med ett plustecken.
//
// Vad som räknas som "något man trycker på" läses ur markupen, inte ur en
// handskriven lista: varje klass som i index.html eller i app.js mallsträngar
// sitter på ett <button>, <a>, <summary>, <input>, <select>, <textarea> eller
// <label>. Då fångas också nästa knapp någon lägger till.

import assert from "node:assert/strict";
import test from "node:test";
import { deklarationer, läsStyles, parseRegler } from "./fixtures/css-parser.mjs";
import { MINSTA, beskriv, interaktivaKlasser, svepTräffytor } from "./fixtures/traffytor.mjs";

const css = läsStyles();

test("markupen känns igen som markup - annars vet testet inte vad som är en knapp", () => {
  const klasser = interaktivaKlasser();
  assert.ok(klasser.size > 50, `bara ${klasser.size} interaktiva klasser hittades i markupen`);
  // Stickprov ur rivningslistan. Tappas läsningen ur app.js mallsträngar blir
  // svepet tyst grönt, och det är värre än inget test alls.
  for (const k of ["week-sheet-plus", "shopping-remove", "recipe-star", "extra-remove",
                   "account-modal-close", "hero-meal-swap", "swap-intent", "onboarding-skip"]) {
    assert.ok(klasser.has(k), `${k} känns inte igen som en knapp - läsningen ur markupen är trasig`);
  }
});

test("ingen interaktiv regel i styles.css är mindre än 44 px", () => {
  const fynd = svepTräffytor(css);
  assert.deepEqual(fynd.map(beskriv), [],
    `\n${fynd.length} träffytor under ${MINSTA} px i frontend/app/styles.css:\n` +
    fynd.map((f) => "  " + beskriv(f)).join("\n") +
    "\n\nMinsta träffyta är 44x44 CSS-px (WCAG 2.5.5, DESIGNSYSTEM-D.md kap. 5).\n" +
    "Ska kontrollen SE mindre ut: ge den .tapmin, som vidgar träffytan utan att\n" +
    "flytta något visuellt. Är det en kryssruta där RADEN är knappen: ge raden\n" +
    "min-height:44px, så är kryssrutans egen storlek fri (§5.5).\n");
});

test("svepet ser en för liten knapp - annars bevisar det ingenting", () => {
  const fynd = svepTräffytor(css + "\n.week-sheet-plus{width:28px;height:28px}\n")
    .filter((f) => f.selektor === ".week-sheet-plus");
  assert.equal(fynd.length, 2, "svepet missade en 28x28-knapp");
  assert.deepEqual(fynd.map((f) => f.prop).sort(), ["height", "width"]);
});

test(".tapmin och radregeln är verkliga undantag, inte tysta hål", () => {
  // En kontroll som ser liten ut men har vidgad träffyta ska godkännas...
  const medTapmin = svepTräffytor(css + `
    .g5-liten-knapp{width:20px;height:20px;cursor:pointer;position:relative}
    .g5-liten-knapp::after{content:"";width:max(100%,44px);height:max(100%,44px)}
  `).filter((f) => f.selektor === ".g5-liten-knapp");
  assert.deepEqual(medTapmin, [], ".tapmin-utvidgningen godkändes inte");

  // ...men en lika liten knapp UTAN den ska inte det.
  const utan = svepTräffytor(css + `
    .g5-liten-knapp{width:20px;height:20px;cursor:pointer}
  `).filter((f) => f.selektor === ".g5-liten-knapp");
  assert.equal(utan.length, 2, "en 20x20-knapp utan vidgad träffyta slank igenom");
});

test("fokus syns: inget :focus{outline:0} kvar, och :focus-visible finns", () => {
  // Filen hade tre `outline:0` och NOLL :focus-visible-regler. Tangentbords-
  // navigering var alltså osynlig i hela appen - man kunde tabba runt utan att
  // se var man var. Det är inte en detalj för en skärmläsaranvändare; det är
  // vad som händer för alla som lagt ifrån sig musen.
  const regler = parseRegler(css);
  const nollade = [];
  for (const r of regler) {
    const harNoll = deklarationer(r.block).some((d) =>
      d.prop === "outline" && /^(0|none)$/.test(d.värde.trim()));
    if (!harNoll) continue;
    for (const del of r.delar) {
      if (/:focus(?!-visible)/.test(del) || del === "*" || del === ":where(*)") {
        nollade.push(`styles.css:${r.rad}  ${del}`);
      }
    }
  }
  assert.deepEqual(nollade, [],
    `fokusringen nollas här:\n${nollade.join("\n")}\n:focus{outline:0} är förbjudet i filen.`);

  const synliga = regler.filter((r) =>
    r.delar.some((d) => d.includes(":focus-visible")) &&
    deklarationer(r.block).some((d) => d.prop.startsWith("outline")));
  assert.ok(synliga.length >= 2,
    "det finns ingen :focus-visible-regel med outline - fokus är fortfarande osynligt");

  const grund = synliga.find((r) => r.delar.some((d) => /^:where\(/.test(d)));
  assert.ok(grund, "grundregeln för fokus saknas (kap. 5)");
  const outline = deklarationer(grund.block).find((d) => d.prop === "outline");
  assert.match(outline.värde, /2px solid/, "fokusringen är tunnare än 2px");
});

test("ta bort ligger utanför tumzonen, men är kvar för tangentbordet", () => {
  // Att flytta krysset ur vägen får inte betyda att det försvinner: den som
  // inte kan svepa måste ha kvar en väg till samma handling.
  const regler = parseRegler(css);
  const utanför = regler.find((r) =>
    r.delar.includes(".shopping-item .shopping-remove") &&
    deklarationer(r.block).some((d) => d.prop === "transform" && /translateX\(100%\)/.test(d.värde)));
  assert.ok(utanför, "krysset ligger fortfarande kvar i raden - det var hela poängen med G5");
  // Tumzonen är en pekskärmsfråga. Med mus finns inget fettfinger, och då ska
  // krysset stå kvar där det stod - annars tas en fungerande väg bort i onödan.
  assert.ok(utanför.media.some((m) => /pointer\s*:\s*coarse/.test(m)),
    "krysset flyttas även för musanvändare - regeln ska gälla pekskärm");

  const vidFokus = regler.find((r) =>
    r.delar.some((d) => d.includes(":focus-within") || d.includes(":focus-visible")) &&
    r.delar.some((d) => d.includes("shopping-remove")) &&
    deklarationer(r.block).some((d) => d.prop === "transform" && /translateX\(0\)/.test(d.värde)));
  assert.ok(vidFokus, "krysset kommer inte fram vid fokus - då är det oåtkomligt med tangentbord");
});
