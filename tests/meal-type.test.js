// M1: INGA FRUKOSTAR I MIDDAGSVECKAN.
//
// Roten till att risgrynsgröt kunde hamna i en middagsvecka var att inget
// fält sa vad en rätt var till för - kolumnen fanns inte. Veckoplaneraren
// valde bland allt banken hade, och att gröten inte dök upp oftare var tur,
// inte konstruktion.
//
// Testet prövar tre lager, för det krävs alla tre för att påståendet ska
// vara sant hos en användare:
//
//   1. DATAT     - varje recept i den committade banken har ett mealType ur
//                  det stängda värdeförrådet, och de två värdeförråden
//                  (Python och JavaScript) är samma lista.
//   2. VILLKORET - dinnerCandidates() släpper igenom middagar och ingenting
//                  annat, inte heller ett recept utan klassificering.
//   3. INKOPPLINGEN - app.js bygger sin vecka ur weekPlanCandidates(), och
//                  den funktionen kör allt genom dinnerCandidates(). Ett
//                  villkor som är rätt men inte anropat är ingen grind.
//
// Plus det konkreta fallet uppdraget pekar ut vid namn: risgrynsgröten får
// inte förekomma i en genererad vecka.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";
import { DINNER, MEAL_TYPES, dinnerCandidates, isDinner, mealTypeOf }
  from "../frontend/app/src/data/meal-type.js";
import { limitCandidatePool } from "../frontend/app/src/services/planning.js";
import { createSeededRandom } from "../frontend/app/src/services/seeded-random.js";

const ROT = new URL("../", import.meta.url);
const läs = relativ => readFileSync(new URL(relativ, ROT), "utf8");

const KÄLLKATALOG = new URL("backend/recipe_sources/", ROT);
const GRÖT_ID = "risgrynsgrot-lordag";

/** Den committade receptbanken - samma 240 recept backenden importerar. */
function bankenFrånKällorna() {
  return readdirSync(KÄLLKATALOG)
    .filter(namn => namn.endsWith(".json"))
    .sort()
    .flatMap(namn => JSON.parse(readFileSync(new URL(namn, KÄLLKATALOG), "utf8")));
}

/** Reservbanken appen använder när backenden inte svarar. */
function reservbanken() {
  return JSON.parse(läs("frontend/app/data/recipes.json"));
}

// ---------------------------------------------------------------------------
// LAGER 1 · DATAT
// ---------------------------------------------------------------------------

test("varje recept i banken har ett mealType ur värdeförrådet", () => {
  const bank = bankenFrånKällorna();
  assert.ok(bank.length >= 200, `bara ${bank.length} recept lästa - hittade testet källorna?`);
  const utan = bank.filter(r => r.mealType == null).map(r => r.id);
  assert.deepEqual(utan, [],
    `${utan.length} recept saknar mealType. NULL betyder i praktiken ` +
    "'kanske middag', och då är fältet värdelöst. Kör\n" +
    "backend/scripts/classify_recipe_meal_type.py --skriv.");
  const okända = [...new Set(bank.map(r => r.mealType))].filter(v => !MEAL_TYPES.includes(v));
  assert.deepEqual(okända, [], `värden utanför det stängda värdeförrådet: ${okända}`);
});

test("reservbanken bär samma klassificering som källorna", () => {
  // Utan det här beror middagsveckan på om nätet fungerade.
  const frånKällan = new Map(bankenFrånKällorna().map(r => [r.id, r.mealType]));
  for (const recept of reservbanken()) {
    assert.ok(recept.mealType != null, `${recept.id} saknar mealType i reservbanken`);
    if (frånKällan.has(recept.id)) {
      assert.equal(recept.mealType, frånKällan.get(recept.id),
        `${recept.id} är ${recept.mealType} i reservbanken och ` +
        `${frånKällan.get(recept.id)} i källorna`);
    }
  }
});

test("värdeförrådet är samma lista i Python och JavaScript", () => {
  // Två listor som ska vara lika är alltid en risk. Den hålls ihop här, inte
  // av att någon kommer ihåg båda filerna.
  const python = läs("backend/services/recipes/meal_types.py");
  const värden = [...python.matchAll(/^(DINNER|BREAKFAST|LUNCH|DESSERT|SIDE) = "([^"]+)"/gm)]
    .map(m => m[2]);
  assert.deepEqual([...värden].sort(), [...MEAL_TYPES].sort(),
    "backend/services/recipes/meal_types.py och src/data/meal-type.js är oense " +
    "om vilka måltidstyper som finns");
});

test("risgrynsgröten finns i banken och är inte en middag", () => {
  // Halva påståendet är att receptet FINNS. En grind som råkat tömma banken
  // hade annars sett ut som en lyckad grind.
  const gröt = bankenFrånKällorna().find(r => r.id === GRÖT_ID);
  assert.ok(gröt, `${GRÖT_ID} finns inte längre i banken`);
  assert.equal(gröt.mealType, "frukost");
});

// ---------------------------------------------------------------------------
// LAGER 2 · VILLKORET
// ---------------------------------------------------------------------------

test("dinnerCandidates släpper bara igenom middagar", () => {
  const kandidater = dinnerCandidates(bankenFrånKällorna());
  assert.ok(kandidater.length > 100, "för få middagar kvar för att fylla en vecka");
  const fel = kandidater.filter(r => r.mealType !== DINNER).map(r => r.id);
  assert.deepEqual(fel, []);
});

test("ett recept utan klassificering är inte en middag", () => {
  // Fail closed åt rätt håll: den som lägger till ett recept och glömmer
  // fältet får det inte föreslaget, i stället för att få det serverat.
  assert.equal(isDinner({ id: "nytt", namn: "Något nytt" }), false);
  assert.equal(mealTypeOf({ id: "nytt" }), null);
  assert.deepEqual(dinnerCandidates([{ id: "nytt" }]), []);
});

test("fältet läses både som mealType och meal_type", () => {
  // Backenden svarar mealType; en rad läst rakt ur SQLite heter meal_type.
  assert.equal(isDinner({ meal_type: DINNER }), true);
  assert.equal(isDinner({ mealType: DINNER }), true);
});

// ---------------------------------------------------------------------------
// LAGER 3 · EN GENERERAD VECKA
// ---------------------------------------------------------------------------

/**
 * En vecka, byggd som app.js bygger den: kandidaterna genom dinnerCandidates,
 * poolen genom den RIKTIGA limitCandidatePool med app.js egna argument och
 * seedade rankning, och veckan plockad ur poolen.
 *
 * bestMenuCombo väljer alltid en delmängd av poolen - kan gröten inte komma
 * in i poolen kan den inte komma in i veckan.
 */
function genereraVecka(bank, antalMiddagar, frö) {
  const slump = createSeededRandom(frö);
  const rank = recept => {
    const taggar = recept.taggar || recept.tags || [];
    return (taggar.includes("vardagsmat") || taggar.includes("husmanskost") ? 0 : 10) + slump();
  };
  const tak = { 5: 22, 6: 20, 7: 18 }[antalMiddagar] || 24;
  const pool = limitCandidatePool(dinnerCandidates(bank), 6, tak, "proteinkalla",
                                  "inkopspris", antalMiddagar + 1, rank);
  return { pool, vecka: pool.slice(0, antalMiddagar) };
}

test("en genererad vecka innehåller aldrig något som inte är middag", () => {
  const bank = bankenFrånKällorna();
  for (let middagar = 3; middagar <= 7; middagar += 1) {
    for (let frö = 1; frö <= 50; frö += 1) {
      const { pool, vecka } = genereraVecka(bank, middagar, frö);
      assert.equal(vecka.length, middagar,
        `veckan blev ${vecka.length} rätter av ${middagar} begärda`);
      const fel = pool.filter(r => r.mealType !== DINNER).map(r => r.id);
      assert.deepEqual(fel, [],
        `${middagar} middagar, frö ${frö}: poolen bar ${fel.join(", ")}`);
    }
  }
});

test("risgrynsgröten förekommer aldrig i en genererad vecka", () => {
  const bank = bankenFrånKällorna();
  assert.ok(bank.some(r => r.id === GRÖT_ID), "gröten finns inte i banken testet läste");
  for (let middagar = 3; middagar <= 7; middagar += 1) {
    for (let frö = 1; frö <= 200; frö += 1) {
      const { pool } = genereraVecka(bank, middagar, frö);
      assert.ok(!pool.some(r => r.id === GRÖT_ID),
        `risgrynsgröt hamnade i poolen för ${middagar} middagar, frö ${frö}`);
    }
  }
});

test("veckan byggs av reservbanken också när backenden är nere", () => {
  // Reservbanken är 58 recept i appens egna fältnamn. Utan mealType där hade
  // ett backendavbrott gett en veckoplanerare utan grind - eller en tom vecka.
  const { vecka } = genereraVecka(reservbanken(), 5, 7);
  assert.equal(vecka.length, 5);
  assert.deepEqual(vecka.filter(r => !isDinner(r)).map(r => r.id), []);
});

// ---------------------------------------------------------------------------
// LAGER 4 · INKOPPLINGEN
//
// Ett villkor som är rätt men inte anropat är ingen grind. Det här lagret
// läser app.js och kräver att veckoplaneringen faktiskt går genom det.
// ---------------------------------------------------------------------------

const app = läs("frontend/app/app.js");

/** app.js utan hela kommentarsrader. Prosa om en funktion är inget anrop. */
function utanKommentarsrader(källa) {
  return källa
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map(rad => (/^\s*\/\//.test(rad) ? "" : rad))
    .join("\n");
}

/** Kroppen till en funktion deklarerad i vänsterkanten, med klammermatchning. */
function funktionskropp(källa, namn) {
  const start = källa.indexOf(`\nfunction ${namn}(`);
  assert.notEqual(start, -1, `hittade ingen funktion ${namn}() i app.js`);
  const första = källa.indexOf("{", start);
  let djup = 0;
  for (let i = första; i < källa.length; i += 1) {
    if (källa[i] === "{") djup += 1;
    else if (källa[i] === "}") {
      djup -= 1;
      if (djup === 0) return källa.slice(första, i + 1);
    }
  }
  throw new Error(`kunde inte hitta slutet på ${namn}()`);
}

test("app.js importerar villkoret från modulen", () => {
  assert.match(app, /import \{[^}]*\bdinnerCandidates\b[^}]*\} from "\.\/src\/data\/meal-type\.js"/,
    "app.js importerar inte dinnerCandidates - då finns ingen grind att anropa");
});

test("weekPlanCandidates kör varje receptkälla genom dinnerCandidates", () => {
  const kropp = funktionskropp(app, "weekPlanCandidates");
  // Båda grenarna returnerar kandidater: den kostfiltrerade och den
  // näringsmålsfiltrerade. Missar EN av dem läcker frukosten in den vägen.
  for (const källa of ["localRecipesForUser()", "candidateRecipesForUser()"]) {
    const anrop = [...kropp.matchAll(new RegExp(källa.replace(/[()]/g, "\\$&"), "g"))];
    assert.ok(anrop.length > 0, `weekPlanCandidates() läser inte längre ${källa}`);
    assert.ok(kropp.includes(`dinnerCandidates(${källa})`),
      `weekPlanCandidates() använder ${källa} utan att köra den genom\n` +
      "dinnerCandidates(). Då kan en frukost hamna i middagsveckan igen.");
  }
});

test("varje väg som bygger en vecka hämtar sina kandidater från weekPlanCandidates", () => {
  // bestMenuCombo() väljer alltid en delmängd av det den får. Grinden håller
  // därför exakt så länge varje anropsplats får sin lista härifrån.
  // Varken deklarationen eller prosan om den är en anropsplats: app.js
  // förklarar bestMenuCombo() i en kommentar, och den läses annars som ett
  // anrop utan kandidater.
  const kod = utanKommentarsrader(app);
  const anropsplatser = [...kod.matchAll(/(?<!function\s)\bbestMenuCombo\(/g)].map(m => m.index);
  assert.ok(anropsplatser.length >= 2,
    "förväntade minst två vägar som bygger en vecka (chooseMenu, openPlanComparison)");
  for (const index of anropsplatser) {
    const före = kod.slice(Math.max(0, index - 2000), index);
    assert.ok(före.includes("weekPlanCandidates()"),
      "ett anrop till bestMenuCombo() vars kandidater inte kommer från\n" +
      "weekPlanCandidates() - den vägen har ingen middagsgrind.");
  }
});

test("bytesförslagen lyder samma regel som veckan", () => {
  // Ett byte lägger en rätt i veckan. Utan filtret här kunde gröten komma in
  // bakvägen, en dag i taget.
  assert.match(app, /dinnerCandidates\(candidateRecipesForUser\(\)\)\.filter\(recipe => !state\.valda\.has/,
    "bytesförslagen filtreras inte på middag");
});

test("receptfliken filtreras INTE på middag", () => {
  // Katalogen ska visa hela banken. Den som vill laga gröt ska hitta den -
  // det är veckoplaneringen som ska vara kräsen, inte receptlistan.
  const kropp = funktionskropp(app, "localRecipesForUser");
  assert.ok(!kropp.includes("dinnerCandidates"),
    "localRecipesForUser() filtrerar på middag. Då försvinner frukostar och\n" +
    "luncher ur receptfliken, och M1 löste ett problem genom att skapa ett nytt.");
});
