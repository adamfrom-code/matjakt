// L7:s acceptanskriterium: premiumskärmen är telefon 8 — och de två saker som
// design D gör med FÄRG görs här med FORM och med ORD.
//
// Skärmen var en hänglåsvägg: nio handskrivna säljpunkter, två guldfärgade
// prisflikar och en betalvägg med sina egna prissträngar. J2 tar hand om att
// listan blir SANN (den härleds ur backend/services/accounts/features.py och
// prövas av tests/premiumtabellen.test.js). Det här paketet tar hand om att
// skärmen blir LÄSBAR, och två regler avgör hur den får se ut:
//
//   §2.3  Accenten betyder "här är du, här går vägen vidare" och ingenting
//         annat. "kvalitet, betyg, favorit, Premium" står uttryckligen i
//         listan över förbjudna betydelser. Premium märks därför med ORDET i
//         spärrade kapitäler (§2.4, R56) - aldrig med en färg, och aldrig med
//         den guldplatta R56 redan rev ut.
//
//   §2.4  Ett på/av-läge får inte bäras av färg. Det gällde stjärnbetyget och
//         det gäller det valda betalningsalternativet: en flik som bara byter
//         ton mellan vald och ovald är osynlig i gråskala, i butiksbelysning
//         och på ett papper.
//
// Provet är L0:s, ordagrant lånat ur tests/prisregler.test.js: de två lägena
// ritas ur stilmallen och körs genom gråskala (färg -> relativ luminans) och
// genom ett filter som tar bort ton OCH ljushet. Kvar står formen.
//
// Det andra filtret är det som har tänder, och det prövas därför på det FUSK
// som nästan blev den här skärmen: en understrykning som byter från
// transparent till --ink. Den ser ut som form - det är en linje - men linjen
// finns i båda lägena och skiljer sig bara i färg.
//
// Och beloppen: 59 och 399 står ingenstans i frontenden. De bor i backend
// (features.PRICING), når klienten via /api/entitlements och ritas av L0:s
// prisMarkup(). Saknas svaret renderas "pris saknas" - ett tomt fack är sant,
// ett påhittat tal är det inte.

import assert from "node:assert/strict";
import test from "node:test";

import { deklarationer, läsFil, läsStyles, parseRegler, rotVariabler }
  from "./fixtures/css-parser.mjs";
import { avtryck, färg, färgerI, gråskala, okändaSelektorer, rita, synligt, utanFärg }
  from "./fixtures/prisrender.mjs";
import { paywallPlanMarkup, planMarkup, planetikett, synkaValet, årsrabatt }
  from "../frontend/app/src/views/premiumskarmen.js";

const css = läsStyles();
const regler = parseRegler(css);
const TEMAN = { ljust: rotVariabler(regler), mörkt: rotVariabler(regler, '[data-theme="dark"]') };

const modul = läsFil("frontend/app/src/views/premiumskarmen.js");
const html = läsFil("frontend/app/index.html");
const kontovy = läsFil("frontend/app/src/views/account.js");

// Talen kommer utifrån i alla prov här, precis som i appen. Att de råkar vara
// 59 och 399 i produktion är backendens sak - byter den pris ska skärmen följa
// med utan att en enda rad i frontenden rörs, och det prövas längre ner.
const PRISER = { monthly: { pricePerMonth: 59 }, yearly: { pricePerYear: 399 } };

const KLASSER = ["prem-kap", "prem-ingress", "prem-moms", "prem-avsluta",
  "prem-plan-tal", "prem-plan-namn", "prem-plan-villkor",
  "premium-pitch", "premium-pricing", "premium-price-tab"];

/** Reglerna L7 äger - allt annat i filen tillhör andra paket. */
const L7 = /\.prem-|\.premium-pitch\b|\.premium-pricing\b|\.premium-price-tab\b|\.paywall-lead\b|\.paywall-card\b|\.paywall-yearly\b|\.paywall-monthly\b/;
const minaRegler = regler.filter(r => r.delar.some(del => L7.test(del)));
// SISTA regeln med selektorn, inte första: kaskaden gäller, och de gamla
// .premium-*-raderna högre upp i filen har samma selektorer som L7:s.
const regel = (selektor) =>
  [...minaRegler].reverse().find(r => r.delar.includes(selektor));
const deklaration = (selektor, prop) => {
  const r = regel(selektor);
  if (!r) return null;
  const d = deklarationer(r.block).filter(x => x.prop === prop);
  return d.length ? d[d.length - 1].värde.trim() : null;
};

// De två lägena med EXAKT samma innehåll. Skiljer lapparna sig åt är det
// stilmallens förtjänst och ingenting annat.
const flik = (vald, innehåll = planMarkup(PRISER).month) =>
  `<div class="premium-pitch"><div class="premium-pricing">`
  + `<button class="premium-price-tab${vald ? " active" : ""}">${innehåll}</button>`
  + `</div></div>`;

const ritaAlla = (lappar, stilmall = css, tema = "ljust") =>
  Object.fromEntries(Object.entries(lappar).map(([namn, h]) =>
    [namn, rita(h, stilmall, TEMAN[tema])]));

const lika = (ritade, a, b, filter) => avtryck(filter(ritade[a])) === avtryck(filter(ritade[b]));

// ---------------------------------------------------------------------------
// 1. VALT BETALNINGSSÄTT BÄRS AV FORM (§2.4)
// ---------------------------------------------------------------------------

test("valt och ovalt betalningssätt går att skilja åt i gråskala, i båda lägena", () => {
  for (const tema of Object.keys(TEMAN)) {
    const ritade = ritaAlla({ vald: flik(true), ovald: flik(false) }, css, tema);
    assert.ok(!lika(ritade, "vald", "ovald", gråskala),
      `i ${tema} läge blev vald och ovald plan identiska i gråskala`);
  }
});

test("...och även när all färginformation är borta", () => {
  // Det hårda provet. Gråskala behåller LJUSHET, så två gråtoner räcker för
  // att passera det. Här tas också ljusheten bort: klarar markeringen det
  // bärs den av FORM - en linje som finns eller inte finns, och halvfet stil
  // på beloppet - och av ingenting annat.
  for (const tema of Object.keys(TEMAN)) {
    const ritade = ritaAlla({ vald: flik(true), ovald: flik(false) }, css, tema);
    assert.ok(!lika(ritade, "vald", "ovald", utanFärg),
      `i ${tema} läge fanns skillnaden mellan vald och ovald plan bara i färg`);
  }
  const ritade = ritaAlla({ vald: flik(true), ovald: flik(false) });
  for (const namn of ["vald", "ovald"]) {
    assert.ok(synligt(ritade[namn]).length > 0, `${namn} renderar ingenting synligt`);
  }
});

test("formprovet har tänder: understrykningen som bara byter färg fälls", () => {
  // FUSKET, och det är inte hypotetiskt - det var första utkastet av den här
  // skärmen. En 2 px understrykning som går från `transparent` till `--ink`
  // SER ut som form, för det är en linje. Men linjen finns i båda lägena och
  // har samma bredd i båda; det enda som skiljer dem är en färg. Gråskala
  // släpper igenom det, och färgfiltret ska fälla det.
  const fuskCss = ".premium-price-tab{padding-bottom:7px;border-bottom:2px solid transparent}"
    + ".premium-price-tab.active{border-bottom-color:#16191B}";
  const fuskat = ritaAlla({ vald: flik(true, "59 kr"), ovald: flik(false, "59 kr") }, fuskCss);
  assert.ok(!lika(fuskat, "vald", "ovald", gråskala),
    "gråskala ensamt godkänner en understrykning som bara byter färg - kriteriet vore tandlöst");
  assert.ok(lika(fuskat, "vald", "ovald", utanFärg),
    "färgfiltret släppte igenom två flikar vars enda skillnad var en färg");

  // Och så den riktiga formen, sagd rakt ut: bredden bär markeringen.
  assert.match(deklaration(".premium-pitch .premium-price-tab", "border-bottom") || "",
    /^0 solid /, "den ovalda fliken ritar redan en linje - då kan bara färgen skilja dem");
  assert.equal(deklaration(".premium-pitch .premium-price-tab.active", "border-bottom-width"), "2px");
  assert.equal(deklaration(".premium-pitch .premium-price-tab.active .prem-plan-tal", "font-weight"), "600");
});

test("valet hörs också - aria-pressed följer markeringen", () => {
  // Behållaren bar role="tablist" med två barn som varken hade role="tab"
  // eller någon tabpanel att styra: en skärmläsare fick veta att den stod i en
  // flikrad och hittade sedan inga flikar.
  assert.ok(!/class="premium-pricing" role="tablist"/.test(html),
    "flikraden utan flikar står kvar");
  assert.match(html, /class="premium-pricing" role="group" aria-label="[^"]+"/);
  assert.match(html, /data-price-tab="month"[^>]*aria-pressed="true"/);
  assert.match(html, /data-price-tab="year"[^>]*aria-pressed="false"/);

  // Och attributet får inte bli kvar på fel knapp när valet byts.
  const knappar = [
    { klasser: ["premium-price-tab"], attribut: {} },
    { klasser: ["premium-price-tab", "active"], attribut: {} },
  ].map(k => ({
    classList: { contains: (c) => k.klasser.includes(c) },
    setAttribute: (namn, värde) => { k.attribut[namn] = värde; },
    attribut: k.attribut,
  }));
  synkaValet({ querySelectorAll: () => knappar });
  assert.equal(knappar[0].attribut["aria-pressed"], "false");
  assert.equal(knappar[1].attribut["aria-pressed"], "true");
});

// ---------------------------------------------------------------------------
// 2. PREMIUM MÄRKS MED ORDET, ALDRIG MED ACCENTEN (§2.3, §2.4)
// ---------------------------------------------------------------------------

const ärRöd = (f) => f && f[3] > 0 && f[0] > f[1] && f[0] > f[2] && f[0] - Math.max(f[1], f[2]) >= 24;

test("Premium märks med ordet i spärrade kapitäler", () => {
  const r = regel(".prem-kap");
  assert.ok(r, ".prem-kap finns inte - då är nivån omärkt");
  assert.match(r.block, /text-transform:uppercase/, "kapitälerna sätts inte i CSS");
  const spärr = /letter-spacing:\.?(\d*\.?\d+)em/.exec(r.block);
  assert.ok(spärr && Number(spärr[1]) >= 0.1,
    `spärrningen är ${spärr ? spärr[1] : "0"}em - kapitäler utan spärr är bara versaler (§2.4)`);

  // §8: ordet skrivs som VANLIG text i källan och versaliseras med CSS.
  // Versaler i markupen får skärmläsaren att stava dem bokstav för bokstav.
  assert.match(html, /<p class="prem-kap">Matjakt Premium<\/p>/);
  assert.match(kontovy, /<p class="prem-kap">Matjakt Premium<\/p>/,
    "betalväggen märker Premium på något annat sätt än kontoarket");
  assert.ok(!/MATJAKT PREMIUM/.test(html + kontovy),
    "Premium är versaliserat i källan - skärmläsaren stavar då P-R-E-M-I-U-M");
});

test("ingen regel i premiumskärmen bär accenten eller en larmfärg (§2.3)", () => {
  // Undantaget står i markupen, inte här: betalväggens årsknapp behåller
  // .btn-primary, för den är skärmens PRIMÄRA HANDLING och §2.3 tillåter
  // accenten för precis det ("vägen vidare: primärknappen"). Det som inte får
  // bära accent är Premium som kvalitetsmärke, och det är L7:s egna regler
  // som granskas här.
  const FÖRBJUDNA = /--(red|danger|error|warning|alert|gold)\b|\b(red|crimson|firebrick|maroon|darkred|indianred|tomato|orangered|salmon|gold)\b/i;
  const fynd = [];
  for (const r of minaRegler) {
    if (FÖRBJUDNA.test(r.block)) fynd.push(`styles.css:${r.rad} ${r.selektor} - förbjudet färgnamn`);
    if (/var\(\s*--accent/.test(r.block)) fynd.push(`styles.css:${r.rad} ${r.selektor} - accenten får inte bära Premium (§2.3)`);
    if (/var\(\s*--primary/.test(r.block)) fynd.push(`styles.css:${r.rad} ${r.selektor} - --primary är accenten under aliasnamn`);
    for (const tema of Object.keys(TEMAN)) {
      const löst = r.block.replace(/var\(\s*(--[\w-]+)[^)]*\)/g, (_, namn) => TEMAN[tema].get(namn) ?? "");
      for (const { text, f } of färgerI(löst)) {
        if (ärRöd(f)) fynd.push(`styles.css:${r.rad} ${r.selektor} - ${text} är röd i ${tema} läge`);
      }
    }
  }
  assert.deepEqual(fynd, [], "accenten eller en larmfärg bär Premium:\n" + fynd.join("\n"));
  assert.ok(ärRöd(färg("#8A1F42")), "accenten är ett mörkt rött och ska fällas av rödspärren");
  assert.ok(!ärRöd(färg("#626B6F")) && !ärRöd(färg("#16191B")),
    "rödspärren får inte fälla systemets gråtoner");
});

test("ingen vikt över 600 och ingen guldplatta i rubriken (§3.2)", () => {
  const fynd = [];
  for (const r of minaRegler) {
    for (const m of r.block.matchAll(/font(?:-weight)?:[^;]*?(?:^|\s|:)([1-9]00|bold)\b/g)) {
      const vikt = m[1] === "bold" ? 700 : Number(m[1]);
      if (vikt > 600) fynd.push(`styles.css:${r.rad} ${r.selektor} - ${m[1]}`);
    }
  }
  assert.deepEqual(fynd, [], "Archivo laddas i 400/500/600 och punkt slut:\n" + fynd.join("\n"));
  // Rubriken är Newsreader i 400 - en rubrik blir inte viktigare av att vara
  // fet, den blir bullrig. Gamla raden var `font:700 20px var(--font-display)`.
  assert.match(deklaration(".premium-pitch h3", "font") || "", /^400 29px\/1\.04 var\(--f-disp\)$/);
  assert.match(deklaration(".paywall-card h2", "font") || "", /^400 29px\/1\.04 var\(--f-disp\)$/);
});

// ---------------------------------------------------------------------------
// 3. BELOPPEN GÅR GENOM L0, OCH BOR I BACKEND
// ---------------------------------------------------------------------------

test("varje belopp ritas av L0:s priskomponent", () => {
  assert.match(modul, /import \{ prisMarkup \} from "\.\/pris\.js"/);
  const delar = planMarkup(PRISER);
  assert.match(delar.month, /<span class="pris prem-plan-tal">59 kr<\/span>/);
  assert.match(delar.year, /<span class="pris prem-plan-tal">399 kr<\/span>/);
  assert.match(paywallPlanMarkup(PRISER), /<span class="pris prem-plan-tal">399 kr<\/span>/);

  // Och ingen prislapp är handskriven. Samma grind som L0:s "ingen vy bygger
  // egen prismarkup", på samma regex: en <span class="pris"> skriven här hade
  // kunnat avrunda, tusentalsavgränsa eller falla tillbaka annorlunda än
  // resten av appen utan att någon märker det.
  //
  // Prosa som nämner ett tal målar ingenting, så kommentarer räknas bort -
  // samma gräns som L0 drar i sin rödgranskning.
  const kod = modul.replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n").filter(rad => !/^\s*\/\//.test(rad)).join("\n");
  assert.ok(!/class="[^"]*\b(pris|pris--ca|pris--golv|cirka|saknas|minst)\b/.test(kod),
    "modulen bygger egen prismarkup i stället för att kalla prisMarkup()");

  // Och inget belopp står som en siffra: byter backend pris följer skärmen med.
  // 33 och 309 räknas fram ur de två talen (399/12 respektive 59*12-399), så
  // inte heller de får finnas skrivna.
  assert.ok(!/\b(59|399|309|33)\b/.test(kod),
    "ett pris står som en siffra i modulen - då kan backend och skärm säga olika");
});

test("beloppen kommer ur svaret, inte ur en litteral", () => {
  // Byter backend pris ska skärmen följa med utan att en rad i frontenden
  // rörs. Det prövas genom att mata in något annat än produktionens tal.
  const annat = { monthly: { pricePerMonth: 49 }, yearly: { pricePerYear: 349 } };
  const delar = planMarkup(annat);
  assert.match(delar.month, />49 kr</);
  assert.match(delar.year, />349 kr</);
  assert.equal(årsrabatt(annat), 49 * 12 - 349);
  assert.match(delar.year, /spara 239 kr/);
});

test("saknas priset står det att det saknas - inget påhittat tal", () => {
  // /api/entitlements har inte svarat än, eller svarade utan pricing. Ett tomt
  // fack är sant; en nolla eller ett minnesvärde är det inte.
  const delar = planMarkup({});
  assert.match(delar.month, /class="saknas">pris saknas</);
  assert.match(paywallPlanMarkup({}), /class="saknas">pris saknas</);
  assert.equal(årsrabatt({}), null);
  // Och villkorsraden får inte lova en rabatt den inte kan räkna ut.
  assert.ok(!/spara/.test(delar.year), "årsraden lovar en rabatt utan att veta priserna");
});

test("priset presenteras som totalpris inklusive moms", () => {
  // Prisinformationslagen (2004:347): det pris en konsument visas ska vara det
  // hon betalar. B2 satte tax_behavior "inclusive" på priserna i Stripe; det
  // här är att SÄGA det på skärmen, vilket lagen kräver för sig.
  assert.match(html, /class="prem-moms">[^<]*inklusive moms/i);
  assert.match(kontovy, /class="prem-moms">[^<]*inklusive moms/i,
    "betalväggen säger inte att priset är inklusive moms");
});

test("betalväggen och kontoarket formaterar inte priset var för sig", () => {
  // Betalväggen hade egna strängar med priceText som reservvärde - "399 kr/år",
  // "≈ 33 kr/mån", "Spara 309 kr jämfört med månadsbetalning". Fyra
  // formuleringar av samma fyra tal, skrivna på ett annat ställe än kontoarkets.
  assert.match(kontovy, /import \{ paywallPlanMarkup, planetikett \} from "\.\/premiumskarmen\.js"/);
  for (const sträng of ["399 kr/år", "59 kr/mån", "≈ 33 kr/mån", "Spara 309 kr"]) {
    assert.ok(!kontovy.includes(sträng), `kontovyn skriver fortfarande "${sträng}" själv`);
  }
  assert.ok(!/priceText/.test(paywallPlanMarkup(PRISER)));

  // Prenumerationsraden ("Din prenumeration (399 kr per år) förnyas ...") hade
  // samma två strängar som reservvärde. En reservsiffra i en mening om vad
  // kunden BETALAR är den farligaste sorten: den ser rätt ut ända tills backend
  // byter pris. Vet vi inte beloppet säger raden "din plan", och det är sant.
  assert.equal(planetikett({ yearly: { pricePerYear: 399 } }, "yearly"), "399 kr per år");
  assert.equal(planetikett({ monthly: { pricePerMonth: 59 } }, "monthly"), "59 kr per månad");
  assert.equal(planetikett({}, "yearly"), "din plan");
  assert.equal(planetikett({ yearly: { pricePerYear: 399 } }, "okänd"), "din plan");
});

// ---------------------------------------------------------------------------
// 4. L7 BYGGER INGEN ANDRA JÄMFÖRELSETABELL
// ---------------------------------------------------------------------------

test("skärmen bygger ingen egen funktionslista - den är J2:s", () => {
  // J2 härleder tabellen ur backend/services/accounts/features.py med ett test
  // som läser Python-källan. En andra tabell här, med egna rader och egna ord,
  // vore exakt det fel J2 finns för att laga: två texter om samma produkt, och
  // bara den ena körd. L7 gör skärmen; J2 gör listan sann.
  assert.ok(!/<table|<li\b/.test(modul), "premiumskarmen.js bygger en egen lista");
  for (const funktion of ["veckotyper", "skafferi", "Laga med det", "näringsmål",
    "middagar per vecka", "hushåll", "sparhistorik", "kampanj"]) {
    assert.ok(!new RegExp(funktion, "i").test(modul.replace(/\/\*[\s\S]*?\*\//g, "")),
      `premiumskarmen.js säljer "${funktion}" utan en rad i affärsmodellen`);
  }
});

// ---------------------------------------------------------------------------
// 5. TRÄFFYTOR OCH GRANSKNINGEN SJÄLV
// ---------------------------------------------------------------------------

test("varje knapp på skärmen är minst 44 px (G5)", () => {
  for (const selektor of [".premium-pitch .premium-price-tab", ".paywall-yearly"]) {
    const r = regel(selektor);
    assert.ok(r, `${selektor} saknas`);
    assert.match(r.block, /min-height:44px/, `${selektor} har ingen träffyta`);
  }
});

test("motorn läser varenda regel i skärmen - ingen granskas bort tyst", () => {
  // En regel skriven i en selektorform renderaren inte förstår hoppas över
  // utan ett ord, och då vore formprovet ovan ett påstående utan täckning.
  assert.deepEqual(okändaSelektorer(css, KLASSER), [],
    "en regel i premiumskärmen står i en selektorform testet inte kan läsa");
  assert.ok(minaRegler.length >= 12,
    `bara ${minaRegler.length} regler hittades - då mäter testet fel fil`);
});
