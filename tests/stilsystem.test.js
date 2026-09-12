// G1:s acceptanskriterium.
//
// Aliasskiktet (DESIGNSYSTEM-D.md §9.1) är hela poängen med paketet: de nya
// tokens läggs BREDVID den gamla paletten och de gamla namnen pekas på dem.
// Ingen av de ~800 gamla reglerna rörs. Det som kan gå sönder i ett sådant
// byte är exakt en sak - att ett gammalt namn tappas bort på vägen och
// hundra regler tyst faller tillbaka på "ingen färg alls".
//
// Därför prövar testet skiktet på det sätt webbläsaren gör det: varje
// var(--x) som filen slår upp måste lösas till ett värde, och varje gammalt
// namn måste landa på rätt ny token.

import assert from "node:assert/strict";
import test from "node:test";
import {
  användaVariabler, deklarationer, läsFil, läsStyles, lösVar, parseRegler, rotVariabler,
} from "./fixtures/css-parser.mjs";

const css = läsStyles();
const regler = parseRegler(css);
const ljus = rotVariabler(regler);
const mörk = rotVariabler(regler, '[data-theme="dark"]');

const lös = (namn, vars = ljus) => lösVar(vars.get(namn) ?? "", vars).trim().toLowerCase();

test("varje var(--x) i styles.css löser till ett värde", () => {
  const saknade = [...användaVariabler(css)].filter((namn) => !ljus.has(namn)).sort();
  assert.deepEqual(saknade, [],
    `Variabler som används men aldrig definieras: ${saknade.join(", ")}. ` +
    "En odefinierad variabel utan fallback blir tom - regeln försvinner tyst.");
});

test("aliasskiktet lämnar inget gammalt namn bakom sig", () => {
  // Namnen i :root som den såg ut före G1. Tappas ett av dem slutar de regler
  // som slår upp det att fungera, och det syns inte förrän någon öppnar vyn.
  const gamla = [
    "--bg", "--surface", "--surface-2", "--primary", "--primary-2", "--primary-soft",
    "--on-primary", "--ink", "--accent", "--accent-2", "--accent-3", "--accent-soft",
    "--gold", "--gold-2", "--gold-soft", "--text", "--muted", "--text-muted", "--line",
    "--border", "--danger", "--r-sm", "--r-md", "--r-lg", "--r-xl", "--shadow",
    "--shadow-lg", "--shadow-gold", "--ease", "--ease-spring", "--noise",
    "--font-display", "--font-body",
  ];
  for (const namn of gamla) {
    assert.ok(ljus.has(namn), `${namn} finns inte kvar i :root efter aliasbytet`);
    assert.notEqual(lös(namn), "", `${namn} löser till tomt`);
  }
});

test("de nya tokens har de värden designsystemet räknat på (§2.1)", () => {
  // Kontrasttabellen i §2.2 är uträknad på exakt de här hexvärdena. Ändras ett
  // av dem tyst slutar varje ratio i dokumentet att gälla.
  const väntat = {
    "--paper": "#eceeef", "--paper-2": "#e2e5e7",
    "--ink": "#16191b", "--ink-2": "#5a6367", "--ink-3": "#626b6f",
    "--rule": "#cbd1d3", "--rule-2": "#b3bbbe",
    "--accent": "#8a1f42", "--accent-press": "#6e1935", "--on-accent": "#ffffff",
    "--shot": "#d2d7d9",
  };
  for (const [namn, värde] of Object.entries(väntat)) {
    assert.equal(lös(namn), värde, `${namn} har fel värde`);
  }
  assert.equal(lös("--gutter"), "20px");
  assert.equal(lös("--radius"), "0");
  assert.match(lös("--f-disp"), /newsreader/);
  assert.match(lös("--f-ui"), /archivo/);
});

test("de gamla namnen pekar på de nya tokens, inte på gamla hex", () => {
  const väntat = {
    "--bg": "#eceeef",
    "--surface": "#eceeef",        // kort försvinner: vitt på cream blir samma papper
    "--surface-2": "#e2e5e7",
    "--primary": "#8a1f42",
    "--primary-2": "#6e1935",
    "--on-primary": "#ffffff",
    "--accent": "#8a1f42",
    "--accent-2": "#6e1935",
    "--accent-3": "#16191b",       // var "grönt för positivt" - besparingar får ingen egen färg
    "--text": "#16191b",
    "--ink": "#16191b",
    "--muted": "#5a6367",          // gamla #6b756e gav 4,44:1, alltså under AA
    "--text-muted": "#5a6367",
    "--line": "#cbd1d3",
    "--border": "#cbd1d3",
    "--danger": "#16191b",         // rött utgår ur appen
    "--gold": "#5a6367", "--gold-2": "#5a6367", "--gold-soft": "#e2e5e7",
  };
  for (const [namn, värde] of Object.entries(väntat)) {
    assert.equal(lös(namn), värde, `${namn} landade inte på rätt ny token`);
  }
  for (const namn of ["--r-sm", "--r-md", "--r-lg", "--r-xl"]) {
    assert.equal(lös(namn), "0", `${namn} är inte nollad - radie används inte inuti appen (§4.3)`);
  }
  for (const namn of ["--shadow", "--shadow-lg", "--shadow-gold", "--noise"]) {
    assert.equal(lös(namn), "none", `${namn} är inte none - systemet har en enda skugga (§4.5)`);
  }
  assert.equal(lös("--font-display"), lös("--f-disp"));
  assert.equal(lös("--font-body"), lös("--f-ui"));
  assert.equal(lös("--ease-spring"), lös("--ease"), "studsen ska vara aliasad bort (§7)");
});

test("de två fällorna i §9.1 är undvikna", () => {
  // 1. --primary-soft är "ljus bakgrundsplatta" på ett femtiotal ställen. Pekas
  //    den på accenttonen blir halva appen svagt rosa och accentregeln bryts i
  //    samma sekund. Samma sak gäller gamla --accent-soft, som har samma roll.
  assert.equal(lös("--primary-soft"), "#e2e5e7",
    "--primary-soft ska vara --paper-2, inte accenttonen");
  assert.equal(lös("--accent-soft"), "#e2e5e7",
    "--accent-soft ska vara --paper-2, inte accenttonen");
  // 2. Namnkrocken: gamla --shadow betyder "ingen skugga" i box-shadow.
  //    Skuggfärgen måste därför heta något annat under aliasperioden.
  assert.equal(lös("--shadow"), "none");
  assert.match(lös("--shadow-color"), /^rgba\(/, "skuggfärgen saknas som --shadow-color");
  assert.ok(lös("--shadow-sheet").includes("rgba("),
    "--shadow-sheet ska bära den riktiga skuggfärgen - den enda tillåtna skuggan (§4.5)");
});

test("mörka läget är definierat men bara bakom ett uttryckligt val", () => {
  // Värdena i §2.1 ska finnas och gå att granska. De får däremot inte hänga på
  // prefers-color-scheme förrän de hårdkodade ljusa hexvärdena i §9.3 är borta:
  // ett halvbytt mörkt läge ger ljusa fläckar med ljus text.
  assert.equal(lös("--paper", mörk), "#111416");
  assert.equal(lös("--ink", mörk), "#e9ecee");
  assert.equal(lös("--accent", mörk), "#ee93ab");
  const mörkaMedia = regler.filter((r) =>
    r.media.some((m) => /prefers-color-scheme\s*:\s*dark/.test(m)) &&
    r.delar.some((d) => d.startsWith(":root")));
  assert.deepEqual(mörkaMedia, [],
    "mörka tokens ligger bakom prefers-color-scheme innan §9.3 är gjord");
});

test("saknat pris signaleras i form, aldrig i rött (§6)", () => {
  const emoji = css.match(/\p{Extended_Pictographic}/gu) || [];
  assert.deepEqual(emoji, [],
    `emoji kvar i styles.css: ${emoji.join(" ")} - trafikljuset i emoji är rivet (R41)`);

  const färgFör = (selektor) => {
    let färg = null;
    for (const r of regler) {
      if (!r.delar.includes(selektor)) continue;
      for (const d of deklarationer(r.block)) if (d.prop === "color") färg = d.värde;
    }
    return färg === null ? null : lösVar(färg, ljus).trim().toLowerCase();
  };
  assert.equal(färgFör(".price-status.missing"), "#626b6f",
    "saknat pris ska vara --ink-3, inte en varningsfärg");
  assert.equal(färgFör(".chain-item-campaign"), "#16191b",
    "kampanj är goda nyheter och ska inte stå i felfärg (R43)");
  assert.equal(färgFör(".chain-list-savings"), "#16191b",
    "besparing får ingen egen färg (R44)");
  assert.ok(!css.includes(".chain-item.is-missing"),
    "den rosa felraden för en vara utan pris ska vara borta (R42)");

  // De tre formerna finns som klasser: hel siffra, streckad siffra, tom ram.
  for (const [selektor, prop, väntat] of [
    [".pris", "color", "#16191b"],
    [".pris--ca", "color", "#5a6367"],
    [".pris--ca .tal", "border-bottom", "1.5px dashed #626b6f"],
    [".saknas", "border", "1px solid #626b6f"],
  ]) {
    const regel = regler.find((r) => r.delar.includes(selektor));
    assert.ok(regel, `${selektor} saknas - prisreglerna i §6 är inte införda`);
    const d = deklarationer(regel.block).findLast((x) => x.prop === prop);
    assert.ok(d, `${selektor} saknar ${prop}`);
    assert.equal(lösVar(d.värde, ljus).trim().toLowerCase(), väntat,
      `${selektor} { ${prop} } - betydelsebärande linjer ritas i --ink-3, inte --rule-2 (RÄTTELSE 2)`);
  }
});

test("typsnitten är bytta överallt, inte bara i länken", () => {
  const html = läsFil("frontend/app/index.html");
  assert.match(html, /fonts\.googleapis\.com[^"]*family=Archivo/, "Archivo laddas inte");
  assert.match(html, /fonts\.googleapis\.com[^"]*family=Newsreader/, "Newsreader laddas inte");
  assert.doesNotMatch(html, /Bricolage|Manrope/, "gamla typsnitt laddas fortfarande");
  assert.doesNotMatch(css, /Manrope|Bricolage/,
    "styles.css hårdkodar ett typsnitt som inte längre laddas - då blir det systemfont");
});

test("versionen står inte i källan - de tre ställena bär platshållaren", () => {
  // Tre ställen, ett värde. Släpar ett efter serverar service workern gammal
  // CSS mot ny HTML, och användaren ser en halvbytt app tills cachen råkar
  // rensas. L9 gjorde det omöjligt att bumpa dem isär genom att inte bumpa dem
  // alls: bygget skriver alla tre ur en digest över det som byggts. Stämpeln
  // prövas i tests/frontend-version.test.js; här vaktas bara att inget tal
  // smugit tillbaka in i källan.
  const sw = läsFil("frontend/app/sw.js");
  const html = läsFil("frontend/app/index.html");
  assert.match(sw, /CACHE_NAME = "matjakt-shell-v__MATJAKT_VERSION__"/,
    "sw.js CACHE_NAME bär inte platshållaren");
  const versioner = [...html.matchAll(/\?v=([^"']*)/g)].map((m) => m[1]);
  assert.ok(versioner.length >= 2, "index.html saknar ?v= på styles.css och app.js");
  for (const v of versioner) {
    assert.equal(v, "__MATJAKT_VERSION__",
      `index.html har ?v=${v} - ett tal där är raden varje frontendgren konfliktar på`);
  }
});
