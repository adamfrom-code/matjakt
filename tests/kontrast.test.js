// G4:s acceptanskriterium: ett kontrasttest som failar under 4,5:1 för
// brödtext och 3:1 för stor text.
//
// Felet som utlöste paketet: `.stats-card.highlight strong{color:var(--primary)}`
// stod på en panel med `background-image:linear-gradient(150deg,var(--primary-2),
// var(--primary) 70%)`. Mörkt på mörkt, kontrast 1:1 - och det gällde
// "Uppskattat sparat denna vecka" och "denna månad", de två siffror hela appen
// finns för. Samma fel i `.week-summary .remaining strong` och
// `.store-compare-upsell`.
//
// Testet är värt mer än rättningen. En kontrastbugg är osynlig för den som
// skriver den - man ser sin egen skärm, i sitt eget ljus, med sina egna ögon -
// och den upptäcks först av någon som inte kan läsa siffran. Det här hindrar
// nästa från att mergas.

import assert from "node:assert/strict";
import test from "node:test";
import { deklarationer, läsStyles, lösVar, parseRegler, rotVariabler }
  from "./fixtures/css-parser.mjs";
import {
  KRAV_BRÖDTEXT, KRAV_STOR_TEXT, beskriv, kontrast, svepKontrast, tolkaFärg,
} from "./fixtures/kontrast.mjs";

const css = läsStyles();

test("kontrasträkningen stämmer mot de värden designsystemet räknat fram", () => {
  // Om matten är fel är hela svepet nedan värdelöst. §2.2 i DESIGNSYSTEM-D.md
  // har tabellen uträknad enligt WCAG 2.1 relativ luminans - den används här
  // som facit åt andra hållet.
  const par = [
    ["#16191B", "#ECEEEF", 15.17],   // --ink på --paper
    ["#16191B", "#E2E5E7", 13.96],   // --ink på --paper-2
    ["#5A6367", "#ECEEEF", 5.28],    // --ink-2 på --paper
    ["#5A6367", "#E2E5E7", 4.86],    // --ink-2 på --paper-2
    ["#626B6F", "#ECEEEF", 4.68],    // --ink-3 på --paper
    ["#626B6F", "#E2E5E7", 4.31],    // --ink-3 på --paper-2: UNDERKÄNT, RÄTTELSE 1
    ["#8A1F42", "#ECEEEF", 7.66],    // --accent på --paper
    ["#FFFFFF", "#8A1F42", 8.92],    // --on-accent på --accent
    ["#FFFFFF", "#6E1935", 11.33],   // --on-accent på --accent-press
    ["#B3BBBE", "#ECEEEF", 1.68],    // --rule-2: dekorativ, får aldrig bära betydelse
  ];
  for (const [a, b, väntat] of par) {
    const r = kontrast(tolkaFärg(a), tolkaFärg(b));
    assert.ok(Math.abs(r - väntat) < 0.02,
      `${a} på ${b} räknades till ${r.toFixed(2)}:1, designsystemet säger ${väntat}:1`);
  }
});

test("ingen textfärg i styles.css underskrider WCAG AA", () => {
  const fynd = svepKontrast(css);
  assert.deepEqual(fynd.map(beskriv), [],
    `\n${fynd.length} kontrastfel i frontend/app/styles.css:\n` +
    fynd.map((f) => "  " + beskriv(f)).join("\n") +
    `\n\nKravet är ${KRAV_BRÖDTEXT}:1 för brödtext och ${KRAV_STOR_TEXT}:1 för stor text ` +
    "(≥24px, eller ≥18,66px i halvfet stil eller fetare).\n" +
    "Paletten och de uträknade paren står i DESIGNSYSTEM-D.md §2.\n");
});

test("svepet ser en mörk siffra på mörk platta - annars bevisar det ingenting", () => {
  // Ett grönt test säger bara något om det kan bli rött. Här återinförs exakt
  // det fel G4 rättade, och svepet måste hitta det.
  const återinfört = css + `
    .stats-card.highlight{background-image:linear-gradient(150deg,var(--primary-2),var(--primary) 70%)}
    .stats-card.highlight strong{color:var(--primary)}
  `;
  const fynd = svepKontrast(återinfört)
    .filter((f) => f.selektor === ".stats-card.highlight strong");
  assert.equal(fynd.length, 1, "svepet missade en siffra i accentfärg på accentfärgad platta");
  assert.ok(fynd[0].ratio < 1.1, `kontrasten räknades till ${fynd[0].ratio.toFixed(2)}:1, väntat ~1:1`);
});

test("svepet ser en maskerad regel, inte bara slutvärdet", () => {
  // Hela poängen med ögonblicksbilden. En regel som är skriven mörkt-på-mörkt
  // och sedan maskeras av en senare regel är fortfarande ett fel: den slår
  // till i samma sekund någon river masken. Den fällan är dokumenterad i
  // §10 R1 och är precis hur felet överlevde i den här filen.
  const maskerad = css + `
    .g4-prov{background:var(--accent);color:var(--accent)}
    .g4-prov{background:var(--paper);color:var(--ink)}
  `;
  const fynd = svepKontrast(maskerad).filter((f) => f.selektor === ".g4-prov");
  assert.equal(fynd.length, 1,
    "svepet mätte bara slutvärdet - då ser det aldrig landminan som R1 varnar för");
});

test("besparingar och prisstatus bär ingen accentfärg (§2.3)", () => {
  // Accenten betyder en enda sak: här är du, och här går vägen vidare. Ett
  // sparat belopp är varken. Färgade siffror läses dessutom som betygsättning,
  // och en besparing som råkar bli röd eller grön lär användaren fel sak.
  const regler = parseRegler(css);
  const vars = rotVariabler(regler);
  const accent = (vars.get("--accent") || "").toLowerCase();

  const siffror = [
    ".stats-card.highlight strong",   // "Uppskattat sparat denna vecka" / "denna månad"
    ".week-summary .remaining strong",
    ".chain-list-savings",
  ];
  for (const selektor of siffror) {
    let färg = null;
    for (const r of regler) {
      if (!r.delar.includes(selektor)) continue;
      for (const d of deklarationer(r.block)) if (d.prop === "color") färg = d.värde;
    }
    assert.ok(färg, `${selektor} har ingen färgregel längre - har selektorn bytt namn?`);
    assert.notEqual(lösVar(färg, vars).trim().toLowerCase(), accent,
      `${selektor} står i accentfärg. Sparsiffror är varken nuläge eller nästa steg (§2.3).`);
  }
});
