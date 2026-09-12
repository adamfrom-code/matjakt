// L5:s acceptanskriterium: Sparat-skärmen, byggd som i design D.
//
// Fyra påståenden, alla mätbara:
//
//   1. sparsumman ligger på en mörk yta och klarar kontrastkravet
//      (tests/kontrast.test.js — G4:s svep, utökat)
//   2. månadsstaplarna står mot en GEMENSAM skala, så en hög stapel faktiskt
//      betyder mer än en låg
//   3. en månad utan data renderas som "saknas", aldrig som noll
//   4. pågående månad är märkt som pågående
//
// Punkt 2-4 prövas här, mot markupen modulen faktiskt skriver. Punkt 1 ligger
// i kontrasttestet, för det är där färgerna bor.

import assert from "node:assert/strict";
import test from "node:test";
import {
  MÅNADER_I_DIAGRAMMET, bärUnderlag, delningstext, diagramEtikett,
  månadsSerie, månadsdiagramMarkup, månadsvärdenMarkup, nyckelFörPost,
  nyckeltalMarkup, sparatModell, sparatSedan, summaSenasteDygn, sättGemensamSkala,
} from "../frontend/app/src/views/sparat.js";

const post = (date, savings, extra = {}) => ({
  date, savings, weekKey: "a|b|c|d", hasComparison: true, branch: "Willys", portionCost: 25, ...extra,
});

const NU = new Date(2026, 8, 15);              // 15 september 2026
const månad = (serie, nyckel) => serie.find(m => m.nyckel === nyckel);
const höjd = markup => [...markup.matchAll(/height:([\d.]+)%/g)].map(m => Number(m[1]));

// ---------------------------------------------------------------------------
// 2. Gemensam skala
// ---------------------------------------------------------------------------

test("L5: dubbelt så mycket sparat ger en dubbelt så hög stapel", () => {
  // Hela poängen med ett diagram. Normaliseras varje stapel mot sig själv blir
  // bilden en lögn som ser ut som statistik.
  const serie = månadsSerie([post("2026-08-10", 210), post("2026-09-07", 420)],
                            { now: NU, antal: 2 });
  const aug = månad(serie, "2026-08");
  const sep = månad(serie, "2026-09");
  assert.equal(sep.procent, 100, "den största månaden fyller spåret");
  assert.equal(aug.procent, 50, "halva pengarna ska ge halva stapeln");
  assert.equal(sep.procent / aug.procent, 2);

  const höjder = höjd(månadsdiagramMarkup(serie));
  assert.deepEqual(höjder, [50, 100], "markupen bär samma förhållande som modellen");
});

test("L5: skalan räknas över HELA serien, inte per stapel", () => {
  // Tre månader, en topp. Varje stapel ska mätas mot toppen - inte mot sig
  // själv, och inte mot den närmast föregående.
  const serie = månadsSerie(
    [post("2026-07-06", 100), post("2026-08-10", 400), post("2026-09-07", 200)],
    { now: NU, antal: 3 });
  assert.deepEqual(serie.map(m => m.procent), [25, 100, 50]);
});

test("L5: flera veckor i samma månad läggs ihop till EN stapel", () => {
  const serie = månadsSerie(
    [post("2026-09-01", 120), post("2026-09-08", 80), post("2026-08-11", 100)],
    { now: NU, antal: 2 });
  assert.equal(månad(serie, "2026-09").kronor, 200);
  assert.equal(månad(serie, "2026-09").poster, 2);
  assert.equal(månad(serie, "2026-09").procent, 100);
  assert.equal(månad(serie, "2026-08").procent, 50);
});

test("L5: en serie helt utan sparande ger inga staplar, inte en delning med noll", () => {
  const serie = sättGemensamSkala([
    { nyckel: "2026-08", status: "data", kronor: 0 },
    { nyckel: "2026-09", status: "data", kronor: 0 },
  ]);
  assert.deepEqual(serie.map(m => m.procent), [0, 0], "max = 0 får inte bli NaN eller Infinity");
});

// ---------------------------------------------------------------------------
// 3. Saknas är inte noll
// ---------------------------------------------------------------------------

test("L5: en månad utan underlag renderas som saknas - aldrig som noll", () => {
  const serie = månadsSerie([post("2026-09-07", 300)], { now: NU, antal: 3 });
  assert.equal(månad(serie, "2026-07").status, "saknas");
  assert.equal(månad(serie, "2026-07").kronor, null, "en tom månad har inget belopp, inte beloppet 0");
  assert.equal(månad(serie, "2026-07").procent, null, "en tom månad har ingen stapelhöjd");

  const diagram = månadsdiagramMarkup(serie);
  assert.match(diagram, /sparat-manad-tomt/, "tomt fack saknas i diagrammet");
  assert.equal((diagram.match(/sparat-manad-tomt/g) || []).length, 2);
  assert.equal((diagram.match(/height:0\.0%/g) || []).length, 0,
    "en månad utan underlag får inte ritas som en nollhög stapel");

  const värden = månadsvärdenMarkup(serie);
  assert.match(värden, /saknas/, "värderaden ska säga saknas i klartext");
});

test("L5: en månad MED underlag som landar på noll är inte samma sak som en tom månad", () => {
  // Det är precis den här skillnaden produkten lever på: "ni sparade
  // ingenting" är ett påstående, "vi vet inte" är ett annat.
  const serie = månadsSerie([post("2026-08-10", 0), post("2026-09-07", 300)],
                            { now: NU, antal: 3 });
  const tom = månad(serie, "2026-07");
  const noll = månad(serie, "2026-08");
  assert.equal(tom.status, "saknas");
  assert.equal(noll.status, "data");
  assert.equal(noll.kronor, 0);
  assert.equal(noll.procent, 0);

  const diagram = månadsdiagramMarkup(serie);
  assert.match(diagram, /sparat-manad-noll/, "nollmånaden ska ha sin egen form");
  assert.match(diagram, /sparat-manad-tomt/, "den tomma månaden ska ha en annan");

  const värden = månadsvärdenMarkup(serie);
  assert.match(värden, /<b>0<\/b>/, "noll kronor skrivs ut som 0");
  assert.match(värden, /<b aria-hidden="true">–<\/b><small>saknas<\/small>/,
    "saknad månad skrivs ut som ett streck plus ordet saknas");
});

test("L5: en vecka utan jämförbara butiker skapar ingen månad alls", () => {
  // hasComparison:false = veckan handlades, men två jämförbara kedjor fanns
  // aldrig. Det finns ingen besparing att påstå, inte ens en på noll kronor.
  const serie = månadsSerie([post("2026-09-07", 0, { hasComparison: false })],
                            { now: NU, antal: 2 });
  assert.equal(månad(serie, "2026-09").status, "saknas");
  assert.equal(bärUnderlag(post("2026-09-07", 40, { hasComparison: false })), false);
  assert.equal(bärUnderlag(post("2026-09-07", 40)), true);
});

test("L5: ett oläsbart datum hamnar inte i fel månad - det hamnar ingenstans", () => {
  assert.equal(nyckelFörPost({ date: "2026-09-07" }), "2026-09");
  assert.equal(nyckelFörPost({ date: "2026-13-07" }), null, "månad 13 finns inte");
  assert.equal(nyckelFörPost({ date: "i förrgår" }), null);
  assert.equal(nyckelFörPost({ date: null }), null);
  assert.equal(nyckelFörPost({}), null);
  const serie = månadsSerie([post("hittepå", 500), post("2026-09-07", 100)], { now: NU, antal: 2 });
  assert.equal(månad(serie, "2026-09").kronor, 100, "skräpposten fick inte smita in i en riktig månad");
});

// ---------------------------------------------------------------------------
// 4. Pågående månad
// ---------------------------------------------------------------------------

test("L5: pågående månad är märkt som pågående - i klass, i ord och i etiketten", () => {
  const serie = månadsSerie([post("2026-08-10", 200), post("2026-09-07", 300)],
                            { now: NU, antal: 2 });
  assert.equal(månad(serie, "2026-09").pågående, true);
  assert.equal(månad(serie, "2026-08").pågående, false);

  const diagram = månadsdiagramMarkup(serie);
  assert.equal((diagram.match(/sparat-manad--pagaende/g) || []).length, 1,
    "exakt en månad får vara den pågående");

  // Färg ensam överlever inte gråskala: ordet står också i värderaden.
  assert.match(månadsvärdenMarkup(serie), /<b>300<\/b><small>hittills<\/small>/);
  assert.match(diagramEtikett(serie), /september 300 kronor hittills/);
});

test("L5: diagramets aria-label räknar upp varje värde, även de som saknas", () => {
  // §5.9: diagrammet ska gå att läsa utan att tolka en stapellängd.
  const etikett = diagramEtikett(månadsSerie([post("2026-09-07", 300)], { now: NU, antal: 3 }));
  assert.match(etikett, /juli saknar underlag/);
  assert.match(etikett, /augusti saknar underlag/);
  assert.match(etikett, /september 300 kronor hittills/);
});

test("L5: fönstret är de sex senaste månaderna och går över ett årsskifte", () => {
  const serie = månadsSerie([], { now: new Date(2027, 0, 20) });
  assert.equal(serie.length, MÅNADER_I_DIAGRAMMET);
  assert.deepEqual(serie.map(m => m.nyckel),
    ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12", "2027-01"]);
  assert.equal(serie[serie.length - 1].pågående, true);
});

// ---------------------------------------------------------------------------
// Hjältesiffran och nyckeltalen
// ---------------------------------------------------------------------------

test("L5: hjältesiffran är summan sedan första månaden med underlag", () => {
  const total = sparatSedan([post("2026-06-02", 210), post("2026-07-06", 295), post("2026-09-07", 455)]);
  assert.equal(total.kronor, 960);
  assert.equal(total.sedan, "juni");
  assert.equal(total.poster, 3);
});

test("L5: utan en enda handlad vecka finns ingen siffra att visa", () => {
  const tom = sparatSedan([]);
  assert.equal(tom.kronor, null, "noll kronor sparat och inget underlag alls är inte samma sak");
  assert.equal(tom.sedan, null);
});

test("L5: nyckeltalsraderna säger 'Underlag saknas', inte 0", () => {
  const modell = sparatModell([], { now: NU, vecka: { middagar: null, kampanjvaror: null } });
  assert.deepEqual(modell.rader.map(r => r.id), ["vecka", "manad", "middagar", "kampanj"]);
  const markup = nyckeltalMarkup(modell.rader);
  assert.equal((markup.match(/Underlag saknas/g) || []).length, 4);
  assert.doesNotMatch(markup, />0</, "en nolla vi inte har täckning för får inte skrivas ut");
});

test("L5: de fyra raderna är veckan, månaden, middagarna och kampanjvarorna", () => {
  const modell = sparatModell([post("2026-09-14", 120), post("2026-08-10", 400)],
                              { now: NU, vecka: { middagar: 4, kampanjvaror: 0 } });
  const markup = nyckeltalMarkup(modell.rader);
  assert.match(markup, /Den här veckan<\/span><span class="sparat-tal-varde">120 kr/);
  assert.match(markup, /Den här månaden<\/span><span class="sparat-tal-varde">120 kr/);
  assert.match(markup, /Middagar planerade<\/span><span class="sparat-tal-varde">4/);
  // Noll kampanjvaror i en prissatt vecka ÄR ett svar, och det skrivs ut.
  assert.match(markup, /Kampanjvaror i maten<\/span><span class="sparat-tal-varde">0/);
});

test("L5: 'den här månaden' är kalendermånaden som stapeln visar", () => {
  // Raden och stapeln får inte kunna säga olika saker om samma månad. Den
  // gamla vyn räknade 30 dygn bakåt medan diagrammet visar kalendermånader.
  const logg = [post("2026-08-31", 500), post("2026-09-07", 120)];
  const modell = sparatModell(logg, { now: NU });
  const sep = månad(modell.serie, "2026-09");
  assert.equal(modell.rader.find(r => r.id === "manad").kronor, sep.kronor);
  assert.equal(sep.kronor, 120, "augusti hör till augusti, även 15 dagar senare");
});

test("L5: 'den här veckan' är de senaste sju dygnen", () => {
  const logg = [post("2026-09-14", 120), post("2026-09-01", 400)];
  assert.equal(summaSenasteDygn(logg, 7, { now: NU }), 120);
  assert.equal(summaSenasteDygn([], 7, { now: NU }), null, "inget underlag är null, inte 0");
});

// ---------------------------------------------------------------------------
// Dela din månad
// ---------------------------------------------------------------------------

test("L5: dela-knappen visas bara när det finns en månadssumma att dela", () => {
  const utan = sparatModell([], { now: NU });
  assert.equal(utan.delbar, false);
  assert.equal(utan.delningstext, "");

  const med = sparatModell([post("2026-09-07", 742)], { now: NU });
  assert.equal(med.delbar, true);
  assert.equal(med.delningstext, "Jag sparade 742 kr hittills i september · matjakt.store");
});

test("L5: en avslutad månad delas utan 'hittills'", () => {
  assert.equal(
    delningstext({ status: "data", kronor: 742, lång: "augusti", pågående: false }),
    "Jag sparade 742 kr på maten i augusti · matjakt.store");
  assert.equal(delningstext({ status: "saknas", kronor: null, lång: "augusti" }), "");
});

// ---------------------------------------------------------------------------
// Markupen är inte prismarkup
// ---------------------------------------------------------------------------

test("L5: vyn skriver ingen prismarkup - de tre prisreglerna ägs av L0", () => {
  // Sparat visar aggregat och antal, inte priser. Skulle den börja skriva
  // "ca", streckade siffror eller pris-saknas-ramar vore prisreglerna byggda
  // två gånger på olika sätt, och det är det enda paketet som inte får det.
  const serie = månadsSerie([post("2026-09-07", 300), post("2026-08-10", 0)], { now: NU, antal: 3 });
  const allt = månadsdiagramMarkup(serie) + månadsvärdenMarkup(serie)
    + nyckeltalMarkup(sparatModell([], { now: NU }).rader);
  for (const klass of ["pris--ca", "pris--saknas", "class=\"pris", "cirka"]) {
    assert.equal(allt.includes(klass), false, `${klass} hör hemma i src/views/pris.js, inte här`);
  }
});

test("L5: allt som skrivs ut är escapat", () => {
  const markup = nyckeltalMarkup([{ id: "x", etikett: `<img src=x onerror=alert(1)>`, antal: 1 }]);
  assert.doesNotMatch(markup, /<img/);
  assert.match(markup, /&lt;img/);
});
