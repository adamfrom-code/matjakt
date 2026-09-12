// J2:s acceptanskriterium: premiumlistan får inte kunna ljuga igen.
//
// Den gamla listan sålde "Aktuella erbjudanden och kampanjer" och "Laga med
// det du redan har hemma". Båda var gratis och helt ogatade. Den sa
// "Obegränsade byten" och "Upp till 7 middagar" utan att säga vad fritt är.
// Felet var inte orden - det var att orden var HANDSKRIVNA bredvid en
// kodsanning i backend/services/accounts/features.py. Två texter om samma
// sak, och bara den ena kördes.
//
// Därför frågar det här testet features.py i stället för sitt eget minne.
// J1 gjorde grindarna härledda ur FEATURES; J3 flyttade sedan gränsen åt båda
// hållen utan att röra en enda grind, och listan följde inte med eftersom
// ingenting tvingade den. Nu gör något det: varje rad i tabellen prövas mot
// modellen, i båda riktningarna, och en funktion som byter nivå gör tabellen
// RÖD i stället för tyst fel.
//
// Och ett grönt test säger bara något om det kan bli rött. Varje grind här
// saboteras därför också med flit - en funktion flyttad ner, en flyttad upp,
// en rad som glömts bort, ett tal som glidit isär, och två färgfusk byggda
// för att smita förbi formprovet.

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import test from "node:test";

import { läsFil, läsStyles, parseRegler, rotVariabler } from "./fixtures/css-parser.mjs";
import { kontrast, tolkaFärg } from "./fixtures/kontrast.mjs";
import {
  avtryck, färg, färgerI, gråskala, okändaSelektorer, rita, synligt,
  träffadeRegler, utanFärg,
} from "./fixtures/prisrender.mjs";
import { flyttad, läsAffärsmodell, läsFeatures, läsKonstant, läsPython, ACTIVATION_PY }
  from "./fixtures/affarsmodell.mjs";
import {
  GRATIS_MAX_HUSHALL, GRATIS_MAX_MIDDAGAR, GRATIS_SPARVECKOR,
  PREMIUM_MAX_HUSHALL, PREMIUM_MAX_MIDDAGAR, PREMIUM_SPARVECKOR,
  RADER, TANKSTRECK, avvikelser, jamforelseMarkup,
} from "../frontend/app/src/views/premiumtabellen.js";

const css = läsStyles();
const regler = parseRegler(css);
const TEMAN = { ljust: rotVariabler(regler), mörkt: rotVariabler(regler, '[data-theme="dark"]') };

const MODELL = läsAffärsmodell();
const PRISER = { monthly: { pricePerMonth: MODELL.priser.perMånad },
                 yearly: { pricePerYear: MODELL.priser.perÅr } };
const MARKUP = jamforelseMarkup(PRISER);

// ---------------------------------------------------------------------------
// 1. Läsaren av features.py - det allt annat vilar på
// ---------------------------------------------------------------------------

test("modellen läses ur features.py, och en tyst tom läsning är omöjlig", () => {
  // Ett test mot en tom mängd är grönt för evigt. Det är den enda vägen det
  // här kriteriet kan bli värdelöst utan att någon märker det, så den stängs
  // först: läsaren kastar hellre än returnerar tomt.
  assert.ok(MODELL.funktioner.size >= 20,
    `FEATURES lästes som ${MODELL.funktioner.size} rader - det är för få för att vara modellen`);
  // Läsaren ska skilja True från False och inte bara svara likadant på allt.
  // Vilka funktioner som ligger var står INTE här: J3:s lärdom var att ett
  // test som minns modellen måste ändras när modellen ändras, och då är det
  // inte längre modellen som styr. Det enda som pinnas är att båda svaren
  // finns - annars vore hela granskningen nedan en konstant.
  assert.deepEqual([...new Set(MODELL.funktioner.values())].sort(), [false, true],
    "FEATURES lästes som bara ett svar - då kan granskningen aldrig se en skillnad");

  // En rad i en form parsern inte känner igen får inte kunna försvinna tyst.
  const källa = läsPython("backend/services/accounts/features.py");
  const smugen = källa.replace('"favorites": {"free": True},',
    '"favorites": dict(free=True),  # samma sak, annan form');
  assert.throws(() => läsFeatures(smugen), /gick att läsa/,
    "en oläsbar rad i FEATURES granskades bort i tystnad");

  // Och ett borttaget namn är ett fel, inte en nolla.
  assert.throws(() => läsKonstant("FREE_MAX_DINNERS", källa.replace(/^FREE_MAX_DINNERS.*$/m, "")),
    /finns inte/);
});

// ---------------------------------------------------------------------------
// 2. Acceptansen: varje rad i tabellen stämmer mot features.py
// ---------------------------------------------------------------------------

test("varje rad i jämförelsetabellen stämmer mot affärsmodellen", () => {
  assert.deepEqual(avvikelser(MODELL), [],
    "tabellen och features.py säger olika saker om samma produkt:\n"
    + avvikelser(MODELL).join("\n"));
});

test("de två raderna som gjorde listan till en lögn finns inte kvar", () => {
  // Kampanjbevakningen har ingen funktionsnyckel alls sedan J3 -
  // renderCampaignSection() körs för alla - och "Laga med det jag har" är
  // full_pantry, som är gratis. Att en rad SAKNAS är svårare att testa än att
  // den finns, så de nämns vid namn: det var de här två som såldes.
  const etiketter = RADER.map(rad => rad.etikett).join(" | ").toLowerCase();
  assert.ok(!/kampanj|erbjudande|rea\b/.test(etiketter),
    "kampanjer säljs igen som Premium - de har ingen grind och ingen nyckel i FEATURES");

  const skafferi = RADER.find(rad => rad.funktioner.includes("full_pantry"));
  assert.ok(skafferi, '”Laga med det jag har” (full_pantry) har ingen rad - då säger tabellen ingenting om den');
  assert.equal(skafferi.gratis.har, MODELL.funktioner.get("full_pantry"),
    "skafferiraden svarar inte det features.py svarar om ”Laga med det jag har”");

  // Byten har ingen nyckel i features.py (FREE_SWAP_LIMIT bor i app.js). En
  // rad utan sanningskälla är precis den sort som gick sönder, så den finns
  // inte - och kan inte läggas till utan att avvikelser() fäller den.
  assert.ok(!/byte/.test(etiketter), "byten säljs igen utan en rad i affärsmodellen");

  const html = läsFil("frontend/app/index.html");
  for (const lögn of ["Aktuella erbjudanden och kampanjer", "Laga med det du redan har hemma",
    "Obegränsade byten", "premium-feature-list"]) {
    assert.ok(!html.includes(lögn), `index.html säljer fortfarande "${lögn}"`);
  }
});

test("talen i tabellen är samma tal som features.py räknar med", () => {
  assert.equal(GRATIS_MAX_MIDDAGAR, MODELL.tal.FREE_MAX_DINNERS);
  assert.equal(PREMIUM_MAX_MIDDAGAR, MODELL.tal.PREMIUM_MAX_DINNERS);
  assert.equal(GRATIS_MAX_HUSHALL, MODELL.tal.FREE_MAX_HOUSEHOLD_MEMBERS);
  assert.equal(PREMIUM_MAX_HUSHALL, MODELL.tal.PREMIUM_MAX_HOUSEHOLD_MEMBERS);
  assert.equal(GRATIS_SPARVECKOR, MODELL.tal.FREE_SAVINGS_WEEKS);
  assert.equal(PREMIUM_SPARVECKOR, MODELL.tal.PREMIUM_SAVINGS_WEEKS);

  // Och talen ska stå i texten användaren läser, inte bara i en konstant.
  const middagar = RADER.find(rad => rad.nyckel === "middagar");
  assert.ok(middagar.gratis.text.includes(String(MODELL.tal.FREE_MAX_DINNERS)),
    `middagsraden säger "${middagar.gratis.text}" men fritt är ${MODELL.tal.FREE_MAX_DINNERS}`);
  assert.ok(middagar.premium.text.includes(String(MODELL.tal.PREMIUM_MAX_DINNERS)));
  const hushåll = RADER.find(rad => rad.nyckel === "hushall");
  assert.ok(hushåll.gratis.text.includes(String(MODELL.tal.FREE_MAX_HOUSEHOLD_MEMBERS)));
  assert.ok(hushåll.premium.text.includes(String(MODELL.tal.PREMIUM_MAX_HOUSEHOLD_MEMBERS)));
});

test("provperioden utlovas inte i tabellen - den är bunden till kontot", () => {
  // J3 ger sju dagar efter FÖRSTA skapade veckan, en gång per konto.
  // /api/entitlements svarar inte med den, så klienten vet inte om den som
  // läser tabellen redan förbrukat sin. "Sju dagar ingår" vore därför en ny
  // osanning av exakt den sort paketet finns för att ta bort. Talet finns och
  // står här så att raden går att skriva den dag svaret bär informationen.
  assert.equal(läsKonstant("ACTIVATION_TRIAL_DAYS", läsPython(ACTIVATION_PY)), 7);
  const text = [...RADER.map(r => r.etikett), MARKUP].join(" ").toLowerCase();
  assert.ok(!/provperiod|gratis i sju dagar|sju dagars/.test(text),
    "tabellen lovar en provperiod den inte kan veta om användaren har kvar");
});

// ---------------------------------------------------------------------------
// 3. Sabotaget: flyttas en funktion blir tabellen röd, inte tyst fel
// ---------------------------------------------------------------------------

test("en funktion som flyttas NER till gratis fäller tabellen", () => {
  // Precis det J3 gjorde med full_pantry, advanced_nutrition och meal_prep -
  // och det som listan inte märkte. Nu märks det.
  const fynd = avvikelser(flyttad(MODELL, "live_prices", true));
  assert.deepEqual(fynd, ["live_prices (raden livepriser): är gratis i features.py men säljs som Premium"]);
});

test("en funktion som flyttas UPP till premium fäller tabellen", () => {
  // Och åt andra hållet: J3 flyttade upp hushållet och sparhistoriken. En
  // tabell som fortsätter lova något gratis efter en sådan flytt är lika
  // trasig - bara åt det håll som gör kunden arg i stället för besviken.
  const fynd = avvikelser(flyttad(MODELL, "meal_prep", false));
  assert.deepEqual(fynd, ["meal_prep (raden naring): är Premium i features.py men utlovas gratis"]);
});

test("en ny funktion i modellen måste få en rad - tystnad räknas inte", () => {
  const utökad = { ...MODELL, funktioner: new Map([...MODELL.funktioner, ["ai_menyplanering", false]]) };
  assert.deepEqual(avvikelser(utökad),
    ["ai_menyplanering: finns i FEATURES men i ingen rad i tabellen"]);
});

test("en rad som grupperar två nivåer under samma rubrik fälls", () => {
  // Det subtila felet: en rubrik som säger "Skafferi" med ett ja i
  // gratiskolumnen, medan en av funktionerna under den i själva verket är
  // Premium. Rubriken döljer då skillnaden, och tabellen är formellt sann men
  // faktiskt falsk.
  const rader = [...RADER.map(rad => ({ ...rad }))];
  const skafferi = rader.find(rad => rad.nyckel === "skafferi");
  skafferi.funktioner = [...skafferi.funktioner, "live_prices"];
  const livepriser = rader.findIndex(rad => rad.nyckel === "livepriser");
  rader.splice(livepriser, 1);
  assert.deepEqual(avvikelser(MODELL, rader),
    ["live_prices (raden skafferi): är Premium i features.py men utlovas gratis"]);
});

test("en funktion får inte säljas två gånger, och en rad utan nyckel är ingen rad", () => {
  const dubbel = [...RADER, { nyckel: "extra", etikett: "Livepriser igen",
    funktioner: ["live_prices"], gratis: { har: false }, premium: { har: true } }];
  assert.deepEqual(avvikelser(MODELL, dubbel),
    ["live_prices: ligger i både raden livepriser och extra"]);

  const lös = [...RADER, { nyckel: "lös", etikett: "Något fint", funktioner: [],
    gratis: { har: false }, premium: { har: true } }];
  assert.deepEqual(avvikelser(MODELL, lös), ["lös: raden nämner ingen funktion i features.py"]);
});

test("ett tal som glider isär från features.py fäller tabellen", () => {
  const ändrad = { ...MODELL, tal: { ...MODELL.tal, FREE_MAX_DINNERS: 4 } };
  assert.deepEqual(avvikelser(ändrad),
    [`FREE_MAX_DINNERS: tabellen säger ${GRATIS_MAX_MIDDAGAR}, features.py säger 4`]);
});

// ---------------------------------------------------------------------------
// 4. Form, inte färg: ja och nej går att skilja åt utan att se färg
// ---------------------------------------------------------------------------

const JA = '<span class="jamfor-ja"></span>';
const NEJ = '<span class="jamfor-nej"></span>';

const ritaAlla = (lappar, stilmall = css, tema = "ljust") =>
  Object.fromEntries(Object.entries(lappar).map(([namn, html]) =>
    [namn, rita(html, stilmall, TEMAN[tema])]));

/** Sant när de två lapparna är omöjliga att skilja åt efter ett filter. */
const lika = (ritade, a, b, filter) => avtryck(filter(ritade[a])) === avtryck(filter(ritade[b]));

test("ja och nej går att skilja åt i gråskala, i båda lägena", () => {
  for (const tema of Object.keys(TEMAN)) {
    const ritade = ritaAlla({ ja: JA, nej: NEJ }, css, tema);
    assert.ok(!lika(ritade, "ja", "nej", gråskala),
      `i ${tema} läge blev ja och nej identiska när färgen gjordes om till gråskala`);
  }
});

test("ja och nej går att skilja åt även utan någon färginformation alls", () => {
  // Det hårda provet, samma som L0:s. Gråskala behåller LJUSHET, så två
  // gråtoner räcker för att passera det. Här tas också ljusheten bort: klarar
  // tabellen det bärs svaret av FORM - fylld ruta mot tankstreck - och av
  // ingenting annat. Det är den enda kodning som överlever butiksbelysning,
  // rödgrön färgblindhet och en svartvit utskrift.
  for (const tema of Object.keys(TEMAN)) {
    const ritade = ritaAlla({ ja: JA, nej: NEJ }, css, tema);
    assert.ok(!lika(ritade, "ja", "nej", utanFärg),
      `i ${tema} läge fanns skillnaden mellan ja och nej bara i färg`);
  }

  // Och skillnaden måste vara SYNLIG. .sr-only-texten ("ingår inte") finns för
  // skärmläsaren och räknas inte - en skärmläsare ser varken ruta eller streck,
  // och ett seende öga ser ingen klass.
  const ritade = ritaAlla({ ja: JA, nej: NEJ });
  for (const namn of ["ja", "nej"]) {
    assert.ok(synligt(ritade[namn]).length > 0, `${namn} renderar ingenting synligt`);
  }
  assert.ok(JSON.stringify(synligt(ritade.nej)).includes(TANKSTRECK),
    "tankstrecket är borta ur nej-glyfen - då är ett nej en tom ruta");
});

test("formprovet har tänder: tre fusk byggda för att smita förbi", () => {
  // FUSK 1 - skillnad bara i LJUSHET. Två rutor med samma form i två gråtoner.
  // Det SLIPPER igenom gråskalefiltret, för gråskala bevarar ljushet, och det
  // är precis därför kriteriet kräver mer än gråskala.
  const ljusCss = ".f{display:inline-block;width:11px;height:11px}"
    + ".f--a{background:#16191B}.f--b{background:#626B6F}";
  const ljus = { ja: '<span class="f f--a"></span>', nej: '<span class="f f--b"></span>' };
  const ritadLjus = ritaAlla(ljus, ljusCss);
  assert.ok(!lika(ritadLjus, "ja", "nej", gråskala),
    "gråskala ensamt godkänner två rutor som bara skiljer sig i gråton - kriteriet vore tandlöst");
  assert.ok(lika(ritadLjus, "ja", "nej", utanFärg),
    "färgfiltret släppte igenom två rutor vars enda skillnad var färg");

  // FUSK 2 - skillnad bara i TON. Två kulörer med exakt samma relativa
  // luminans ser identiska ut för den som inte ser färg. Gråskalefiltret ska
  // säga det.
  const tonCss = ".f{display:inline-block;width:11px;height:11px}"
    + ".f--a{background:#B10000}.f--b{background:#787878}";
  const ton = { ja: '<span class="f f--a"></span>', nej: '<span class="f f--b"></span>' };
  assert.ok(lika(ritaAlla(ton, tonCss), "ja", "nej", utanFärg),
    "två kulörer med samma form skilde sig i något annat än färg - fusket är fel byggt");

  // FUSK 3 - skillnad bara för skärmläsaren. En osynlig .sr-only-text är
  // ingen visuell skillnad och får inte kunna rädda ett tillstånd.
  const dolt = {
    ja: '<span class="jamfor-varde">Ingår</span>',
    nej: '<span class="jamfor-varde">Ingår<span class="sr-only"> inte</span></span>',
  };
  assert.ok(lika(ritaAlla(dolt, css), "ja", "nej", utanFärg),
    "en skillnad som bara skärmläsaren hör räknades som synlig form");
});

test("nejet är ett tankstreck, inte ett bindestreck (§8)", () => {
  assert.equal(TANKSTRECK, "–");
  const regel = regler.find(r => r.delar.includes(".jamfor-nej::before"));
  assert.ok(regel, ".jamfor-nej::before finns inte - då ritas inget streck");
  assert.match(regel.block, /content:"–"/,
    "nejet ritas med något annat än tankstreck - ett bindestreck är inte ersättningstecknet (§8)");
});

test("motorn granskas på det den faktiskt matchar, inte på en gissning", () => {
  // Renderingsmotorn förstår bara klass- och taggselektorer med
  // efterföljandekombinator. En regel skriven i en form den inte kan läsa
  // skulle hoppas över tyst - och då vore formprovet ovan ett påstående utan
  // täckning, precis som L0:s.
  const klasser = ["jamfor", "jamfor-rad", "jamfor-rad--pris", "jamfor-rubrik", "jamfor-tom",
    "jamfor-niva", "jamfor-premium", "jamfor-etikett", "jamfor-cell", "jamfor-varde",
    "jamfor-ja", "jamfor-nej", "jamfor-per", "jamfor-not", "jamfor-not-rad"];
  assert.deepEqual(okändaSelektorer(css, klasser), [],
    "en regel i tabellen står i en selektorform testet inte kan läsa - då granskas den inte");
});

// ---------------------------------------------------------------------------
// 5. Premium märks med ORDET, aldrig med accenten (§2.3, §2.4)
// ---------------------------------------------------------------------------

const ärRöd = (f) => f && f[3] > 0 && f[0] > f[1] && f[0] > f[2] && f[0] - Math.max(f[1], f[2]) >= 24;

test("Premium märks med ordet i spärrade kapitäler, inte med en färg", () => {
  const regel = regler.find(r => r.delar.includes(".jamfor-premium"));
  assert.ok(regel, ".jamfor-premium finns inte - då är nivån omärkt");
  assert.match(regel.block, /text-transform:uppercase/, "kapitälerna sätts inte i CSS");
  const spärr = /letter-spacing:\.?(\d*\.?\d+)em/.exec(regel.block);
  assert.ok(spärr && Number(spärr[1]) >= 0.1,
    `spärrningen är ${spärr ? spärr[1] : "0"}em - kapitäler utan spärr är bara versaler (§2.4)`);

  // §8: kapitäletiketter skrivs som VANLIG TEXT i källan och versaliseras med
  // CSS. Versaler i HTML får skärmläsaren att stava dem bokstav för bokstav.
  assert.ok(MARKUP.includes(">Premium<"), "ordet Premium står inte i tabellen");
  assert.ok(!MARKUP.includes("PREMIUM"), "Premium är versaliserat i källan - skärmläsaren stavar då P-R-E");

  // Och de två nivårubrikerna får inte skilja sig bara i färg: skillnaden är
  // typografisk form, samma princip som stjärnbetyget i §2.4.
  const rubriker = {
    gratis: '<span class="jamfor-niva">Gratis</span>',
    premium: '<span class="jamfor-niva jamfor-premium">Premium</span>',
  };
  const ritade = ritaAlla(rubriker);
  assert.ok(!lika(ritade, "gratis", "premium", utanFärg),
    "Gratis och Premium skiljer sig bara i färg - då är nivån omärkt i gråskala");
});

test("ingen accent och ingen röd färg någonstans i tabellen (§2.3)", () => {
  // §2.3 räknar upp accentens förbjudna betydelser, och "Premium" står med i
  // listan: systemets enda färg betyder "här är du, här går vägen vidare".
  // En guldplatta är dessutom det R56 redan rev ut ur .premium-badge.
  const FÖRBJUDNA_NAMN = /--(red|danger|error|warning|alert|gold)\b|\b(red|crimson|firebrick|maroon|darkred|indianred|tomato|orangered|salmon|gold)\b/i;
  const fynd = [];
  for (const regel of träffadeRegler(MARKUP, css)) {
    if (!regel.delar.some(del => /\.jamfor/.test(del))) continue;
    if (FÖRBJUDNA_NAMN.test(regel.block)) fynd.push(`styles.css:${regel.rad} ${regel.selektor} - förbjudet färgnamn`);
    if (/var\(\s*--accent/.test(regel.block)) fynd.push(`styles.css:${regel.rad} ${regel.selektor} - accenten får inte bära Premium (§2.3)`);
    if (/var\(\s*--primary/.test(regel.block)) fynd.push(`styles.css:${regel.rad} ${regel.selektor} - --primary är accenten under aliasnamn`);
    for (const tema of Object.keys(TEMAN)) {
      const löst = regel.block.replace(/var\(\s*(--[\w-]+)[^)]*\)/g, (_, namn) => TEMAN[tema].get(namn) ?? "");
      for (const { text, f } of färgerI(löst)) {
        if (ärRöd(f)) fynd.push(`styles.css:${regel.rad} ${regel.selektor} - ${text} är röd i ${tema} läge`);
      }
    }
  }
  const modul = läsFil("frontend/app/src/views/premiumtabellen.js")
    .replace(/\/\*[\s\S]*?\*\//g, "").split("\n").filter(rad => !/^\s*\/\//.test(rad)).join("\n");
  for (const { text, f } of färgerI(modul)) if (ärRöd(f)) fynd.push(`premiumtabellen.js - ${text} är röd`);

  assert.deepEqual(fynd, [], "accenten eller en larmfärg bär Premium:\n" + fynd.join("\n"));
  assert.ok(ärRöd(färg("#8A1F42")), "accenten är ett mörkt rött och ska fällas av rödspärren");
  assert.ok(!ärRöd(färg("#626B6F")) && !ärRöd(färg("#16191B")),
    "rödspärren får inte fälla systemets gråtoner");
});

test("ja-rutan och tankstrecket når 3:1 mot ytan de ligger på (§2.4)", () => {
  // Kontrastsvepet i G4 mäter text mot bakgrund och kan aldrig se att två
  // lägen ser likadana ut - det var därför stjärnbetyget kunde gå sönder tyst.
  // Regeln i §2.4 är: minst 3:1 mellan lägena, mätt på DET SOM SKILJER DEM.
  // Här är det rutan och strecket: grafiska objekt som bär information.
  const FORM = /^(background|background-color|border|border-color|outline|color)$/;
  const brister = [];
  for (const tema of Object.keys(TEMAN)) {
    const vars = TEMAN[tema];
    const ytor = ["--paper", "--paper-2"].map(namn => [namn, tolkaFärg(vars.get(namn))]);
    for (const post of rita(JA + NEJ, css, vars)) {
      if (post.dolt) continue;
      for (const [prop, värde] of Object.entries(post.stil)) {
        if (!FORM.test(prop)) continue;
        for (const { text, f } of färgerI(värde)) {
          for (const [ytnamn, yta] of ytor) {
            const r = kontrast(f, yta);
            if (r < 3) brister.push(`${tema}: ${post.väg} { ${prop}: ${text} } ger ${r.toFixed(2)}:1 mot ${ytnamn}`);
          }
        }
      }
    }
  }
  assert.deepEqual(brister, [],
    "ett ja eller nej under 3:1 är en form som inte syns:\n" + brister.join("\n"));
});

// ---------------------------------------------------------------------------
// 6. Beloppen, momsen och den enda källan
// ---------------------------------------------------------------------------

test("varje belopp ritas av L0:s priskomponent, inte av tabellen", () => {
  // 59 och 399 bor i backend (features.PRICING) och når klienten via
  // /api/entitlements. Tabellen får dem som tal och lämnar dem till
  // prisMarkup() - så ingen vy kan avrunda eller formatera ett belopp
  // annorlunda än resten av appen.
  const modul = läsFil("frontend/app/src/views/premiumtabellen.js");
  assert.match(modul, /import \{ prisMarkup \} from "\.\/pris\.js"/);
  assert.ok(!/\$\{[^}]*\}\s*kr/.test(modul), "ett belopp formateras med en egen sträng i stället för prisMarkup()");
  for (const belopp of [MODELL.priser.perMånad, MODELL.priser.perÅr]) {
    assert.ok(MARKUP.includes(`<span class="pris">${belopp} kr</span>`),
      `${belopp} kr ritas inte av priskomponenten`);
  }
  // Och inget belopp är hårdkodat i KODEN: byter backend pris följer tabellen
  // med. Prosa som nämner talet målar ingenting, så kommentarer räknas bort -
  // samma gräns som L0 drar i sin rödgranskning.
  const kod = modul.replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n").filter(rad => !/^\s*\/\//.test(rad)).join("\n");
  assert.ok(!/\b(59|399|309)\b/.test(kod),
    "ett pris står som en siffra i tabellen - då kan backend och skärm säga olika");

  // Saknas svaret ännu säger komponenten "pris saknas". Ett tomt fack är sant,
  // ett påhittat tal är det inte.
  assert.match(jamforelseMarkup({}), /class="saknas"/);
});

test("priset presenteras som totalpris inklusive moms", () => {
  // Prisinformationslagen: det pris en konsument ser ska vara det hon betalar.
  // B2 kontrollerar samma sak på Stripe-sidan (test_billing_moms.py) - det här
  // är att SÄGA det på skärmen, vilket lagen kräver för sig.
  assert.match(MARKUP, /totalpris inklusive moms/i);
});

test("kontoarket och betalväggen ritar SAMMA tabell", () => {
  // Två listor som säger olika saker om samma produkt är exakt det fel
  // paketet finns för att ta bort. Betalväggens gamla fyra punkter sålde
  // veckotyper, näringsfilter och skafferi - alla tre gratis sedan J3.
  const vy = läsFil("frontend/app/src/views/account.js");
  assert.match(vy, /import \{ jamforelseMarkup \} from "\.\/premiumtabellen\.js"/);
  assert.equal([...vy.matchAll(/jamforelseMarkup\(/g)].length, 2,
    "tabellen ska ritas ur modulen på BÅDA ställena: kontoarket och betalväggen");
  assert.ok(!/paywall-points/.test(vy), "betalväggen har kvar sin egen handskrivna lista");
  assert.match(läsFil("frontend/app/index.html"), /id="premiumJamforelse"/);
});

test("ingen vy bygger en egen premiumlista vid sidan av tabellen", () => {
  // Samma grind som L0:s "ingen vy bygger egen prismarkup", och av samma skäl:
  // en andra lista någonstans i frontenden bryter regeln i just den vyn utan
  // att någon märker det. Det var precis så nio <li> kunde överleva J3.
  const EGEN_LISTA = /class="[^"]*\b(premium-feature-list|paywall-points)\b/;
  const fynd = [];
  const gå = (dir) => {
    for (const namn of readdirSync(dir)) {
      const sökväg = `${dir}/${namn}`;
      if (statSync(sökväg).isDirectory()) { gå(sökväg); continue; }
      if (!/\.(js|html)$/.test(namn)) continue;
      if (EGEN_LISTA.test(readFileSync(sökväg, "utf8"))) fynd.push(sökväg.split("/frontend/")[1]);
    }
  };
  gå(new URL("../frontend/app", import.meta.url).pathname);
  assert.deepEqual(fynd, [], "en handskriven premiumlista lever kvar:\n" + fynd.join("\n"));
});
