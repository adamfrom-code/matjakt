// T4:s acceptanskriterium.
//
// En ensam `=======` stod kvar i frontend/app/styles.css från H2 (#141) tills
// den hittades. Ingen grind såg den, och det är värt att förstå varför innan
// man skriver nästa grind:
//
//   - `grep '^<<<<<<<'` letade efter den halva som INTE fanns kvar. Den som
//     städade markören tog översta och understa raden men lämnade mittlinjen.
//   - CSS-parsern i tests/fixtures maskerar kommentarer och klistrar därför
//     ihop den vilsna raden med nästa selektor. Regeln "finns" alltså för
//     parsern - bara under ett namn ingen frågar efter.
//   - esbuild varnar (`Unexpected "="`) men bygget går igenom, så utskriften
//     rullade förbi i CI-loggen.
//
// Därför prövas två saker här: att ingen spårad textfil bär en markör, och
// att regeln markören råkade svälja faktiskt ligger kvar.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { deklarationer, läsStyles, lösVar, parseRegler, rotVariabler } from "./fixtures/css-parser.mjs";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

// Git skriver markören som exakt sju tecken följt av blanksteg eller radslut.
// Att kräva exakt sju är inte slarv utan hela precisionen: styles.css egna
// bannrar (`/* ===== G11 · Inställningar ====...`) är tjugo till sextio
// =-tecken, och en grind som gnäller på dem stängs av inom en vecka.
// `|||||||` är diff3-stilens baslinje och hör till samma familj.
const MARKÖR = /^(<{7}|={7}|>{7}|\|{7})(\s|$)/;

/** Raderna i `text` som bär en konfliktmarkör. */
export function markörrader(text) {
  const ut = [];
  const rader = text.split("\n");
  for (let i = 0; i < rader.length; i++) {
    if (MARKÖR.test(rader[i])) ut.push({ rad: i + 1, text: rader[i].slice(0, 40) });
  }
  return ut;
}

/** Spårade filer som är text. Binärt hoppas över på NUL, inte på filändelse:
 *  en ändelselista rostar, och nästa nya filtyp glider igenom obemärkt. */
function spåradeTextfiler() {
  const namn = execFileSync("git", ["ls-files", "-z"], { cwd: root, maxBuffer: 64 * 1024 * 1024 })
    .toString("utf8").split("\0").filter(Boolean);
  const ut = [];
  for (const n of namn) {
    let rå;
    try { rå = readFileSync(join(root, n)); } catch { continue; }  // borttagen i arbetsträdet
    if (rå.includes(0)) continue;
    ut.push([n, rå.toString("utf8")]);
  }
  return ut;
}

test("ingen spårad textfil bär en konfliktmarkör", () => {
  const fynd = [];
  for (const [namn, text] of spåradeTextfiler()) {
    for (const t of markörrader(text)) fynd.push(`${namn}:${t.rad}: ${t.text}`);
  }
  assert.deepEqual(fynd, [],
    `Konfliktmarkör i spårad fil:\n${fynd.join("\n")}\n` +
    "En kvarglömd markör är inte kosmetisk: CSS- och JS-parsern äter allt fram " +
    "till nästa block, så regeln eller satsen EFTER markören försvinner tyst.");
});

// Markörerna byggs med repeat() i stället för att skrivas ut. Skrivs de ut
// blir testfilen själv ett fynd i provet ovan, och då är grinden värdelös.
const START = "<".repeat(7), MITT = "=".repeat(7), SLUT = ">".repeat(7), BAS = "|".repeat(7);

test("grinden tar den ensamma mittlinjen - halvan som saknades här", () => {
  // Exakt formen i styles.css: ingen <<<<<<<, ingen >>>>>>>, bara mitten.
  const css = `.a{color:red}\n${MITT}\n.b{color:blue}\n`;
  assert.deepEqual(markörrader(css).map((t) => t.rad), [2]);

  // Och beviset för att den gamla vanan inte räckte: att leta efter
  // öppningsmarkören hittar ingenting i exakt den här filen.
  assert.equal(/^<{7}(\s|$)/m.test(css), false,
    "Om `^<<<<<<<` hade träffat vore premissen för T4 fel och provet ovan bevisar inget.");

  for (const [namn, m] of [["start", START], ["slut", SLUT], ["diff3-bas", BAS]]) {
    assert.equal(markörrader(`x\n${m} main\ny\n`).length, 1, `${namn}-markören missades`);
  }
});

test("grinden gnäller inte på filens egna =-linjer", () => {
  const oskyldigt = [
    "/* ===== G11 · Inställningar =====================================================",
    "   ========================================================================== */",
    "=".repeat(8),                       // åtta - git skriver aldrig fler än sju
    "if (a <= b && c >= d) return;",
    "  " + MITT,                         // indenterad: inte radbörjan
    "const s = `${MITT}`;".replace("${MITT}", MITT),
  ];
  for (const rad of oskyldigt) {
    assert.deepEqual(markörrader(rad), [], `falskt fynd på: ${rad.slice(0, 50)}`);
  }
});

test("regeln markören svalde ligger kvar: .shopping-complete på --paper", () => {
  // H2:s kommentar säger att ytan MÅSTE vara --paper: ca-markören ritas i
  // --ink-3, som ger 4,68:1 på --paper men 4,31:1 på --paper-2 - RÄTTELSE 1 i
  // DESIGNSYSTEM-D.md. Med markören på plats föll H2:s regel bort och den
  // äldre regeln högre upp i filen tog över med background:var(--primary-soft),
  // som aliasar till just --paper-2. Felet var alltså exakt det kommentaren
  // säger att den undviker, och ingenting prövade påståendet.
  const regler = parseRegler(läsStyles());
  const vars = rotVariabler(regler);
  const träffar = regler.filter((r) => r.media.length === 0 && r.delar.includes(".shopping-complete"));
  assert.ok(träffar.length > 0, "ingen .shopping-complete-regel alls - selektorn är trasig");

  let bakgrund = null;
  for (const r of träffar) {
    for (const d of deklarationer(r.block)) if (d.prop === "background") bakgrund = d.värde;
  }
  const lös = (v) => lösVar(v, vars).trim().toLowerCase();
  assert.equal(lös(bakgrund), lös("var(--paper)"),
    `Sparkvittots yta hamnade på ${bakgrund} (${lös(bakgrund)}) i stället för var(--paper) ` +
    `(${lös("var(--paper)")}). På --paper-2 ger --ink-3 4,31:1 och ca-markören blir oläslig.`);
});
