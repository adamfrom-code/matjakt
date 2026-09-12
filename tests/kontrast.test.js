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
  KRAV_BRÖDTEXT, KRAV_STOR_TEXT, beskriv, kontrast, luminans, svepKontrast, tolkaFärg,
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
    ".sparat-hero-value",             // L5: appens hjältesiffra
    ".sparat-varde b",                // L5: månadsvärdena under staplarna
    ".sparat-tal-varde",              // L5: nyckeltalsraderna
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

// ---------------------------------------------------------------------------
// L5 · SPARSUMMAN PÅ DEN MÖRKA YTAN
//
// G4 rättade en siffra som stod mörkgrönt på mörkgrönt. L5 flyttar samma
// siffra till motsatsen: appens starkaste kontrast, papper på bläck. Det är
// ett påstående om två färger, alltså ett påstående som måste mätas - och
// mätas i BÅDA lägena, för hela poängen med en tokenbaserad yta är att den
// vänder med temat i stället för att bli ljus text på ljus platta.
// ---------------------------------------------------------------------------

/** Det sista värdet en regel sätter för `prop` på `selektor`, variabler lösta. */
function deklareratVärde(selektor, prop, tema = "") {
  const regler = parseRegler(css);
  const vars = rotVariabler(regler, tema);
  let värde = null;
  for (const r of regler) {
    if (!r.delar.includes(selektor)) continue;
    for (const d of deklarationer(r.block)) if (d.prop === prop) värde = d.värde;
  }
  return värde === null ? null : lösVar(värde, vars).trim().toLowerCase();
}

test("L5: sparsumman ligger på en yta som faktiskt är mörk", () => {
  // "Mörk yta" är inte en smaksak. Den mäts som relativ luminans, och den ska
  // ligga under allt annat papper i systemet - annars är det ingen mörk yta,
  // det är bara en till platta.
  const yta = deklareratVärde(".sparat-hero", "background");
  assert.ok(yta, ".sparat-hero har ingen bakgrundsregel - har klassen bytt namn?");
  const ljushet = luminans(tolkaFärg(yta));
  assert.ok(ljushet < 0.05,
    `.sparat-hero har luminans ${ljushet.toFixed(4)} - det är ingen mörk yta`);
  for (const papper of ["--paper", "--paper-2"]) {
    const annat = luminans(tolkaFärg(rotVariabler(parseRegler(css)).get(papper)));
    assert.ok(ljushet < annat, `.sparat-hero är inte mörkare än ${papper}`);
  }
});

test("L5: hjältesiffran klarar AAA på den mörka ytan - i båda lägena", () => {
  for (const [namn, tema] of [["ljust", ""], ["mörkt", '[data-theme="dark"]']]) {
    const bakgrund = tolkaFärg(deklareratVärde(".sparat-hero", "background", tema));
    for (const selektor of [".sparat-hero-value", ".sparat-hero-label", ".sparat-hero-note"]) {
      const färg = deklareratVärde(selektor, "color", tema);
      assert.ok(färg, `${selektor} saknar färgregel`);
      const r = kontrast(tolkaFärg(färg), bakgrund);
      assert.ok(r >= 7,
        `${namn} läge: ${selektor} ger ${r.toFixed(2)}:1 mot .sparat-hero. `
        + "Appens viktigaste siffra ska ha appens starkaste kontrast, alltså AAA (7:1).");
    }
  }
});

test("L5: svepet hittar Sparat-skärmen även i mörkt läge", () => {
  // Ytan är byggd av tokens just för att vända med temat. Går den sönder är
  // det ljus text på ljus platta - exakt G4:s fel, en gång till.
  const fynd = svepKontrast(css, { tema: '[data-theme="dark"]' })
    .filter((f) => f.selektor.startsWith(".sparat") || f.selektor.startsWith(".btn-sekundar"));
  assert.deepEqual(fynd.map(beskriv), [],
    `\n${fynd.length} kontrastfel på Sparat i mörkt läge:\n`
    + fynd.map((f) => "  " + beskriv(f)).join("\n") + "\n");
});

test("L5: svepet ser en hjältesiffra som tappat sin mörka yta", () => {
  // Ett grönt test säger bara något om det kan bli rött. Det här är den
  // riktiga muteringen, inte en tillagd regel på slutet: ytan görs ljus DÄR
  // DEN STÅR, så siffran mäts mot papper på papper - 1:1, och den siffran är
  // hela skärmen.
  const trasig = css.replace("background:var(--ink);color:var(--paper);",
                             "background:var(--paper);color:var(--paper);");
  assert.notEqual(trasig, css,
    "muteringen träffade ingenting - står `.sparat-hero` fortfarande på var(--ink)?");
  const fynd = svepKontrast(trasig)
    .filter((f) => f.selektor === ".sparat-hero-value" || f.selektor === ".sparat-hero");
  assert.ok(fynd.length >= 2,
    `svepet missade hjältesiffran utan sin mörka yta (hittade ${fynd.length} av 2)`);
  for (const f of fynd) {
    assert.ok(f.ratio < 1.1, `${f.selektor} räknades till ${f.ratio.toFixed(2)}:1, väntat ~1:1`);
  }
});

// ---------------------------------------------------------------------------
// G15 · MÖRKT LÄGE, HELA FILEN
//
// L5 sveper mörkt läge, men bara `.sparat*` och `.btn-sekundar*` - skärmen
// paketet byggde. Utanför det filtret mätte ingenting mörkt läge alls, och
// där stod `.btn-primary{background:var(--text);color:#fff}`: i mörkt läge
// aliasar --text till --ink = #E9ECEE, alltså vit text på nästan vit platta.
// 1,19:1, på varenda primärknapp i appen - betalväggens köpknapp inräknad.
//
// Felet är inte att någon skrev #fff. Det är att #fff inte kan vändas. Ett
// hårdkodat ljust värde är per definition rätt i ett läge och fel i det
// andra, och filen hade 85 av dem. Svepet nedan är därför ofiltrerat: varje
// regel i filen mäts i båda lägena, och den enda vägen att klara det är att
// färgen kommer ur en token som vänder med temat.
// ---------------------------------------------------------------------------

const MÖRKT = '[data-theme="dark"]';

test("G15: ingen textfärg i styles.css underskrider WCAG AA i MÖRKT läge", () => {
  const fynd = svepKontrast(css, { tema: MÖRKT });
  assert.deepEqual(fynd.map(beskriv), [],
    `\n${fynd.length} kontrastfel i mörkt läge:\n` +
    fynd.map((f) => "  " + beskriv(f)).join("\n") +
    "\n\nFärgen måste komma ur en token som vänder med temat: --paper på mörk platta, " +
    "--on-accent på accentfärgad, --ink/--ink-2/--ink-3 på papper (DESIGNSYSTEM-D.md §2.1).\n");
});

test("G15: svepet ser primärknappen tillbaka i hårdkodad vit", () => {
  // Den riktiga muteringen, där regeln står. Utan den säger testet ovan bara
  // att filen är grön just nu - inte att den skulle bli röd om felet kom åter.
  const trasig = css.replace("background:var(--text);color:var(--paper);",
                             "background:var(--text);color:#fff;");
  assert.notEqual(trasig, css,
    "muteringen träffade ingenting - står .btn-primary fortfarande på var(--text)?");
  const fynd = svepKontrast(trasig, { tema: MÖRKT }).filter((f) => f.selektor === ".btn-primary");
  assert.equal(fynd.length, 1, "svepet missade vit text på nästan vit platta i mörkt läge");
  assert.ok(fynd[0].ratio < 1.3,
    `kontrasten räknades till ${fynd[0].ratio.toFixed(2)}:1, väntat ~1,19:1`);
});

test("G15: betalväggens köpknapp och prisflikar är läsbara i båda lägena", () => {
  // Den dyraste ytan i appen: går den inte att läsa går köpet inte att göra.
  // Namngiven för sig så att ett fel här aldrig drunknar i en lång lista.
  for (const [namn, tema] of [["ljust", ""], ["mörkt", MÖRKT]]) {
    const fynd = svepKontrast(css, { tema }).filter((f) =>
      f.selektor === ".btn-primary" || f.selektor.startsWith(".premium-price-tab"));
    assert.deepEqual(fynd.map(beskriv), [],
      `\nBetalväggen är oläsbar i ${namn} läge:\n` + fynd.map((f) => "  " + beskriv(f)).join("\n") + "\n");
  }
});

/**
 * Selektorer som FÅR bära ett hårdkodat ljust värde, med skälet utskrivet.
 * Gemensamt för alla: ytan under texten följer inte heller temat, så en
 * token som vände med temat vore FEL här - inte mer rätt.
 */
const LJUS_MED_FLIT = new Set([
  // Hela hjältekortet ligger på fotot, under .hero-meal-scrim. Scrim är
  // "samma i båda lägen - den ska mörklägga fotot, inte följa temat" (§2.1),
  // och §2.2 räknar vit på foto+scrim till 10,23:1 i värsta fall. Texten,
  // bytlänkens understrykning och båda fokusringarna hör alla dit.
  ".hero-meal-info", ".hero-meal-info small", ".hero-meal-info strong",
  ".hero-meal-meta", ".hero-meal-open:focus-visible",
  ".hero-meal-swap", ".hero-meal-swap span", ".hero-meal-swap:focus-visible",
  // app.js sätter bakgrunden inline per butikskedja - en varumärkesfärg.
  ".chain-mark",
  ".store-card .chain-mark,.week-store-switch .chain-mark,.comparison-store-main .chain-mark",
]);

test("G15: inget hårdkodat ljust värde står kvar utan ett utskrivet skäl", () => {
  // Spärren mot återfall, och den mäter LJUSHET - inte stavningen "#fff".
  // Skälet är konkret: .topbar stod på rgba(246,247,244,.86), alltså en
  // ljus platta som ingen sökning efter "white" hittar, och som i mörkt läge
  // gav en ljus remsa tvärs över toppen med appens namn nästan osynligt i.
  // Det enda som skiljer den från #fff är två siffror.
  const kvar = [];
  for (const regel of parseRegler(css)) {
    if (regel.delar.some((d) => d.startsWith(":root"))) continue;   // tokenblocken ÄR paletten
    if (LJUS_MED_FLIT.has(regel.selektor)) continue;
    for (const d of deklarationer(regel.block)) {
      for (const m of d.värde.matchAll(/#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g)) {
        const f = tolkaFärg(m[0]);
        if (!f || f[3] < 0.2) continue;              // nästan genomskinligt skymmer ingenting
        if (luminans(f) < 0.35) continue;            // mörka literaler vänder inte fel håll
        kvar.push(`styles.css:${regel.rad}  ${regel.selektor.slice(0, 60)}  ${d.prop}:${m[0]}`);
      }
    }
  }
  assert.deepEqual(kvar, [],
    `\n${kvar.length} hårdkodade ljusa värden i styles.css:\n  ` + kvar.join("\n  ") +
    "\n\nEtt hårdkodat ljust värde är rätt i ett läge och fel i det andra. Använd en token " +
    "(--paper, --paper-2, --paper-frost, --on-accent, --on-accent-2, --shot), eller skriv i " +
    "filen varför ytan under inte heller vänder med temat och lägg selektorn i " +
    "LJUS_MED_FLIT här.\n");
});

test("G15: de tillåtna undantagen finns kvar - annars är listan en lögn", () => {
  // En undantagslista som pekar på selektorer som inte längre finns döljer
  // nästa fel i stället för att beskriva det här.
  const selektorer = new Set(parseRegler(css).map((r) => r.selektor));
  for (const sel of LJUS_MED_FLIT) {
    assert.ok(selektorer.has(sel), `${sel} finns inte längre - städa LJUS_MED_FLIT ovan`);
  }
});

test("G15: color-scheme deklareras i båda lägena", () => {
  // Tokens når inte in i NATIVA kontroller. Kryssrutan i samtyckesraden,
  // select, rullningslist, textmarkör och datumväljare ritas av webbläsaren,
  // och utan color-scheme ritas de i ljust standardutseende även när resten
  // av appen är mörk - en vit ruta mitt i en mörk rad. Det är en deklaration,
  // och den är den enda som styr dem.
  const lägen = new Map([[":root", "light"], [':root[data-theme="dark"]', "dark"]]);
  for (const [selektor, väntat] of lägen) {
    let värde = null;
    for (const r of parseRegler(css)) {
      if (!r.delar.includes(selektor)) continue;
      for (const d of deklarationer(r.block)) if (d.prop === "color-scheme") värde = d.värde.trim();
    }
    assert.equal(värde, väntat,
      `${selektor} deklarerar color-scheme:${värde} - väntat ${väntat}. ` +
      "Utan den ritas nativa kontroller i fel läge.");
  }
});
