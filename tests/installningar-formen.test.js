// L6:s acceptanskriterium: Inställningar ser ut som telefon 7 i design D -
// och den obesvarade allergiraden märks av FORM, inte av färg.
//
// G11 byggde innehållet: åtta grupper, en rad per inställning, värdet till
// höger, och ordet "Ej ifyllt" på en tom allergirad. Det paketet prövade att
// raderna SÄGER rätt saker (tests/installningar.test.js). Det här paketet
// prövar hur de SER UT, och det är en annan sorts påstående - det går inte
// att läsa ur markupen, bara ur stilmallen.
//
// VARFÖR DET ÄR ETT TEST OCH INTE EN ÅSIKT.
// Allergiraden är appens mest säkerhetskritiska inställning. Den bodde till
// och med G11 bakom ett omärkt "＋" på 28×28 px, och kravet är att en TOM rad
// ska se ut som något man inte har svarat på - inte som något som inte finns.
// "Den ska synas" är en åsikt. "Den går att skilja från en ifylld rad när all
// färg är borttagen" är ett mätbart påstående, och det är det som står här.
//
// Provet är L0:s, ordagrant lånat från tests/prisregler.test.js:
//
//   gråskala   varje färg blir sin relativa luminans - vad en användare utan
//              färgseende ser.
//   utan färg  ton OCH ljushet bort. Kvar står formen: kantmarkeringen,
//              indragningen, märkets ram, det extra elementet.
//
// Det andra filtret är det som har tänder, så det prövas på ett FUSK byggt
// för att smita förbi: två rader vars enda skillnad är en bakgrundsfärg. Ett
// test som inte kan visa hur det failar är bara en åsikt med semikolon.
//
// Och accenten står inte i den här skärmen. Riktningen ritar den markerade
// raden i oxblod, men §2.3 räknar upp accentens förbjudna betydelser och
// "status, varning, fel, 'över budget', 'saknas'" står med. §2.4 ger formen i
// stället: nedsänkt --paper-2-fält med 3 px kantmarkering i --ink-3 till
// vänster. Det är den som prövas här.

import assert from "node:assert/strict";
import test from "node:test";

import { läsFil, läsStyles, parseRegler, rotVariabler, deklarationer } from "./fixtures/css-parser.mjs";
import { kontrast, tolkaFärg } from "./fixtures/kontrast.mjs";
import { avtryck, färgerI, gråskala, okändaSelektorer, rita, synligt, utanFärg }
  from "./fixtures/prisrender.mjs";
import { initAppState, state } from "../frontend/app/src/state/app-state.js";
import { settingsMarkup } from "../frontend/app/src/views/settings.js";

const css = läsStyles();
const regler = parseRegler(css);
const TEMAN = {
  ljust: rotVariabler(regler),
  mörkt: rotVariabler(regler, '[data-theme="dark"]'),
};

/** Reglerna som hör till L6:s block - allt annat i filen ägs av andra paket. */
const SKÄRMENS_KLASSER = [
  "settings-screen", "settings-groups", "settings-group-title", "settings-row",
  "settings-row-text", "settings-row-label", "settings-row-note",
  "settings-row-value", "settings-row-flag",
];
const skärmensRegler = regler.filter(r =>
  r.delar.some(del => SKÄRMENS_KLASSER.some(k => new RegExp(`\\.${k}(?![\\w-])`).test(del))));

const regel = (selektor) => skärmensRegler.find(r => r.delar.includes(selektor));
const deklaration = (selektor, prop) => {
  const r = regel(selektor);
  if (!r) return null;
  const d = deklarationer(r.block).filter(x => x.prop === prop);
  return d.length ? d[d.length - 1].värde.trim() : null;
};

// Samma rad i två lägen, med SAMMA synliga text. Skiljer sig lapparna åt är
// det stilmallens förtjänst och ingenting annat - hade den tomma raden fått
// behålla sin egen text ("Inga angivna", "Ej ifyllt") vore provet meningslöst,
// för då skiljer sig lapparna redan på orden.
const rad = (extraKlass, extraNod = "") => `<div class="view-settings">
  <section class="screen settings-screen">
    <div class="settings-groups">
      <button class="settings-row${extraKlass}">
        <span class="settings-row-text">
          <span class="settings-row-label">Allergier och specialkost</span>
          <span class="settings-row-note">Recepten filtreras först när du fyllt i.</span>
          ${extraNod}
        </span>
        <span class="settings-row-value">Inga angivna</span>
      </button>
    </div>
  </section>
</div>`;

const IFYLLD = rad("");
const TOM = rad(" marked", `<span class="settings-row-flag">Ej ifyllt</span>`);

const ritaAlla = (lappar, stilmall = css, tema = "ljust") =>
  Object.fromEntries(Object.entries(lappar).map(([namn, html]) =>
    [namn, rita(html, stilmall, TEMAN[tema])]));

/** Sant när de två lapparna är omöjliga att skilja åt efter ett filter. */
const lika = (ritade, a, b, filter) => avtryck(filter(ritade[a])) === avtryck(filter(ritade[b]));

// ---------------------------------------------------------------------------
// 1. DEN TOMMA ALLERGIRADEN MÄRKS AV FORM
// ---------------------------------------------------------------------------

test("en tom allergirad går att skilja från en ifylld i gråskala, i båda lägena", () => {
  for (const tema of Object.keys(TEMAN)) {
    const ritade = ritaAlla({ tom: TOM, ifylld: IFYLLD }, css, tema);
    assert.ok(!lika(ritade, "tom", "ifylld", gråskala),
      `i ${tema} läge blev en obesvarad allergirad identisk med en ifylld i gråskala`);
  }
});

test("...och även när all färginformation är borta", () => {
  // Det hårda provet. Gråskala behåller LJUSHET, så ett nedsänkt fält räcker
  // för att passera det. Här tas också ljusheten bort: klarar raden det bärs
  // märkningen av FORM - kantmarkeringens bredd, indragningen och märkets ram
  // - och av ingenting annat.
  for (const tema of Object.keys(TEMAN)) {
    const ritade = ritaAlla({ tom: TOM, ifylld: IFYLLD }, css, tema);
    assert.ok(!lika(ritade, "tom", "ifylld", utanFärg),
      `i ${tema} läge fanns skillnaden mellan obesvarad och ifylld bara i färg`);
  }

  // Och märkningen får inte hänga på ordet ENSAMT. "Ej ifyllt" är en nod som
  // finns i den ena lappen och saknas i den andra, och den skillnaden syns i
  // varje filter oavsett hur raden är stilsatt. Här tas ordet bort ur båda:
  // kvar står klassen, och alltså bara det stilmallen gör av den. Klarar
  // raden provet ändå bärs märkningen av kantmarkeringen och indragningen -
  // vilket är det §2.4 kräver, och det G11:s ruta inte gjorde.
  for (const tema of Object.keys(TEMAN)) {
    const bara = ritaAlla({ tom: rad(" marked"), ifylld: IFYLLD }, css, tema);
    assert.ok(!lika(bara, "tom", "ifylld", utanFärg),
      `i ${tema} läge gjorde stilmallen ingen skillnad alls på en märkt rad - `
      + `hela märkningen vilar på ordet "Ej ifyllt"`);
  }

  // Och skillnaden måste vara SYNLIG. En .sr-only-text räknas inte: en
  // skärmläsare ser ingen kantmarkering, och ett seende öga ser ingen klass.
  const ritade = ritaAlla({ tom: TOM, ifylld: IFYLLD });
  for (const namn of ["tom", "ifylld"]) {
    assert.ok(synligt(ritade[namn]).length > 0, `${namn} renderar ingenting synligt`);
  }
});

test("formprovet har tänder: en markering som bara är en bakgrundsfärg fälls", () => {
  // FUSKET: exakt den markering §2.4 säger inte räcker - ett nedsänkt fält och
  // ingenting mer. Det SLIPPER igenom gråskalefiltret, eftersom gråskala
  // bevarar ljushet, och det är just därför kriteriet kräver mer än gråskala.
  const fuskCss = ".settings-row{padding:7px 0}.settings-row.marked{background:#E2E5E7}";
  const fuskat = ritaAlla({ tom: rad(" marked"), ifylld: IFYLLD }, fuskCss);
  assert.ok(!lika(fuskat, "tom", "ifylld", gråskala),
    "gråskala ensamt godkänner ett fält som bara skiljer sig i ton - kriteriet vore tandlöst");
  assert.ok(lika(fuskat, "tom", "ifylld", utanFärg),
    "färgfiltret släppte igenom två rader vars enda skillnad var en bakgrundsfärg");
});

test("kantmarkeringen är 3 px och ritas i --ink-3, inte i accenten (§2.4)", () => {
  const kant = deklaration(".settings-row.marked", "border-left");
  assert.ok(kant, ".settings-row.marked har ingen kantmarkering - då bärs märkningen av bakgrunden");
  assert.match(kant, /^3px solid var\(--ink-3\)$/,
    `kantmarkeringen är "${kant}". §2.4: 3 px i --ink-3. "en varning är inte 'här går vägen`
    + ` vidare'. Den är ett fält som skiljer sig i relief, inte i temperatur."`);
  assert.equal(deklaration(".settings-row.marked", "background"), "var(--paper-2)",
    "reliefen saknas - fältet ska vara nedsänkt (§2.4)");
});

test("märket är ett ord i en ram, inte en färgprick", () => {
  const r = regel(".settings-row-flag");
  assert.ok(r, ".settings-row-flag finns inte - då är raden omärkt");
  assert.match(r.block, /text-transform:uppercase/, "märket står inte i kapitäler");
  assert.match(r.block, /border:1px solid var\(--ink-3\)/,
    "ramen saknas eller ritas i en ren avdelarlinje - märket är ett grafiskt objekt (RÄTTELSE 2)");
  // Ordet står som VANLIG text i källan och versaliseras i CSS (§8): versaler
  // i markupen får skärmläsaren att stava dem bokstav för bokstav.
  const vy = läsFil("frontend/app/src/views/settings.js");
  assert.ok(vy.includes('"Ej ifyllt"'), "märkets ord står inte i vyn");
  assert.ok(!vy.includes("EJ IFYLLT"), "märket är versaliserat i källan - skärmläsaren stavar E-J");
});

// ---------------------------------------------------------------------------
// 2. SKÄRMEN ÄR BYGGD SOM TELEFON 7
// ---------------------------------------------------------------------------

test("varje rad är minst 52 px hög", () => {
  const höjd = deklaration(".settings-row", "min-height");
  assert.ok(höjd, ".settings-row har ingen min-height");
  assert.ok(parseFloat(höjd) >= 52, `raden är ${höjd}, uppdraget säger minst 52px`);
  // Och den markerade raden får inte krympa under golvet av sin indragning.
  const märkt = regel(".settings-row.marked");
  assert.ok(!/min-height/.test(märkt.block), "den markerade raden sätter en egen min-height");
});

test("värdet står till höger", () => {
  assert.equal(deklaration(".settings-row", "justify-content"), "space-between");
  assert.equal(deklaration(".settings-row-value", "text-align"), "right");
  // Belopp och postnummer ska stå i kolumn med varandra (§3.3).
  assert.equal(deklaration(".settings-row-value", "font-variant-numeric"), "tabular-nums");
});

test("grupperna skiljs av hårlinjer, raderna av hårlinjer", () => {
  assert.match(deklaration(".settings-group-title", "border-top") || "",
    /^1px solid var\(--rule-2\)$/, "gruppen har ingen hårlinje över sin rubrik");
  assert.match(deklaration(".settings-row", "border-bottom") || "",
    /^1px solid var\(--rule\)$/, "raderna avdelas inte av en hårlinje");
  // Den första gruppen ska inte bära en linje mot rubrikplattan ovanför.
  assert.equal(deklaration(".settings-group-title:first-child", "border-top"), "0");
});

test("skärmen är skriven i systemets tokens, inte i aliasskiktet (§9.1)", () => {
  // Aliasnamnen pekar rätt idag, men skiktet rivs i etapp 7. En skärm som
  // byggs nu ska överleva den rivningen utan att röras.
  const ALIAS = /var\(\s*--(muted|text|text-muted|border|line|surface|surface-2|bg|font-body|font-display|primary|primary-soft|primary-2|accent-2|accent-3|gold|gold-2|gold-soft|danger|r-sm|r-md|r-lg|r-xl|shadow|shadow-lg)\b/;
  const fynd = skärmensRegler
    .filter(r => ALIAS.test(r.block))
    .map(r => `styles.css:${r.rad} ${r.selektor}`);
  assert.deepEqual(fynd, [], "skärmen använder aliasnamn i stället för tokens:\n" + fynd.join("\n"));
});

test("ingen vikt över 600 - det finns ingen sådan i systemet (§3.2)", () => {
  const fynd = [];
  for (const r of skärmensRegler) {
    for (const m of r.block.matchAll(/font(?:-weight)?:[^;]*?(?:^|\s|:)([1-9]00|bold)\b/g)) {
      const vikt = m[1] === "bold" ? 700 : Number(m[1]);
      if (vikt > 600) fynd.push(`styles.css:${r.rad} ${r.selektor} - ${m[1]}`);
    }
  }
  assert.deepEqual(fynd, [], "Archivo laddas i 400/500/600 och punkt slut:\n" + fynd.join("\n"));
});

// ---------------------------------------------------------------------------
// 3. ACCENTEN STÅR INTE I DEN HÄR SKÄRMEN (§2.3)
// ---------------------------------------------------------------------------

test("ingen regel i Inställningar bär accenten", () => {
  // Riktningen ritar .instrad--markt, .markkap och dess värde i accent. Det
  // är precis "status" och "saknas", som §2.3 förbjuder utan undantag - och
  // det skulle dessutom ge skärmen en tredje accentmarkering.
  const fynd = skärmensRegler
    .filter(r => /var\(\s*--(accent|primary)/.test(r.block))
    .map(r => `styles.css:${r.rad} ${r.selektor}`);
  assert.deepEqual(fynd, [],
    "accenten betyder nuläget och vägen vidare, aldrig status (§2.3):\n" + fynd.join("\n"));
});

// ---------------------------------------------------------------------------
// 4. KONTRASTEN I DET NEDSÄNKTA FÄLTET (RÄTTELSE 1)
// ---------------------------------------------------------------------------

test("ingenting i det nedsänkta fältet står i --ink-3 - det är 4,31:1", () => {
  // G4:s kontrastsvep löser bakgrunden ur namnprefixet och ser därför
  // .settings-row-note som text på --paper (5,28:1). Inne i den markerade
  // raden ligger den på --paper-2, och där gäller RÄTTELSE 1: --ink-3 bara på
  // --paper, --ink-2 på --paper-2. Svepet kan inte se det. Det här kan.
  const brister = [];
  for (const tema of Object.keys(TEMAN)) {
    const yta = tolkaFärg(TEMAN[tema].get("--paper-2"));
    for (const post of rita(TOM, css, TEMAN[tema])) {
      if (post.dolt || !post.text.trim()) continue;
      const f = tolkaFärg(post.stil.color || "");
      if (!f) continue;
      const r = kontrast(f, yta);
      if (r < 4.5) brister.push(`${tema}: ${post.väg} ger ${r.toFixed(2)}:1 mot --paper-2`);
    }
  }
  assert.deepEqual(brister, [],
    "text under AA i det nedsänkta fältet:\n" + brister.join("\n"));
});

test("kantmarkeringen och märkets ram når 3:1 - de bär betydelse (RÄTTELSE 2)", () => {
  const GRAFIK = /^(border(-left)?(-color)?|outline|outline-color)$/;
  const brister = [];
  for (const tema of Object.keys(TEMAN)) {
    const vars = TEMAN[tema];
    for (const namn of ["--paper", "--paper-2"]) {
      const yta = tolkaFärg(vars.get(namn));
      for (const post of rita(TOM, css, vars)) {
        if (post.dolt) continue;
        for (const [prop, värde] of Object.entries(post.stil)) {
          if (!GRAFIK.test(prop)) continue;
          for (const { text, f } of färgerI(värde)) {
            const r = kontrast(f, yta);
            if (r < 3) brister.push(`${tema}: ${post.väg} { ${prop}: ${text} } ger ${r.toFixed(2)}:1 mot ${namn}`);
          }
        }
      }
    }
  }
  assert.deepEqual(brister, [],
    "en markering under 3:1 är en form som inte syns:\n" + brister.join("\n"));
});

// ---------------------------------------------------------------------------
// 5. GRANSKNINGEN GRANSKAR NÅGOT
// ---------------------------------------------------------------------------

test("motorn läser varenda regel i skärmen - ingen granskas bort tyst", () => {
  // En regel skriven i en selektorform renderaren inte förstår hoppas över
  // utan ett ord, och då vore formprovet ovan ett påstående utan täckning.
  //
  // Två selektorer står med flit utanför motorn, och de räknas upp vid namn i
  // stället för att filtreras bort på mönster: listan ska bli RÖD den dag en
  // tredje dyker upp, så att någon får ta ställning till om den bär
  // skillnaden mellan besvarad och obesvarad.
  //
  //   .settings-row:active          tryckåterkoppling, borta i nästa ögonblick.
  //                                 Plattan är samma --paper-2 som det
  //                                 nedsänkta fältet, och det gör ingenting:
  //                                 den obesvarade raden känns igen på sin
  //                                 3 px kantmarkering, inte på plattan.
  //   .settings-group-title:first-child   tar bort en hårlinje mot rubriken
  //                                 ovanför. Ren typografi.
  assert.deepEqual(okändaSelektorer(css, SKÄRMENS_KLASSER),
    [".settings-group-title:first-child", ".settings-row:active"],
    "en regel i Inställningar står i en selektorform testet inte kan läsa - då granskas den inte");
  assert.ok(skärmensRegler.length >= 10,
    `bara ${skärmensRegler.length} regler hittades - då mäter testet fel fil`);
});

test("den riktiga tomma allergiraden bär verkligen klassen som märker den", () => {
  // Provet ovan ritar en konstruerad lapp för att isolera stilmallen. Den
  // lappen är värdelös om vyn inte sätter samma klasser, så bandet mellan dem
  // knyts här - mot markupen settings.js faktiskt producerar.
  initAppState({ storage: null, recipeBank: [] });
  Object.assign(state, { kost: { kosttyp: "", avoidAllergens: new Set() } });
  const bit = settingsMarkup().split("</button>")
    .find(del => del.includes("Allergier och specialkost"));
  assert.ok(bit, "allergiraden finns inte i markupen");
  assert.match(bit, /class="settings-row marked"/, "den tomma raden är inte märkt");
  assert.match(bit, /<span class="settings-row-flag">Ej ifyllt<\/span>/);
});
