// E9 (c): slumpen i receptvalet seedas per "skapa vecka"-tillfälle.
//
// `everydayRank` drog ett `Math.random()` per recept, och rankningen kördes
// om vid varje omritning. Samma vecka, samma budget och samma butiker kunde
// därför ge olika svar - och "billigaste butik" är inte ett svar om det
// ändrar sig mellan två omritningar.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createSeededRandom, newSeed } from "../frontend/app/src/services/seeded-random.js";
import { limitCandidatePool } from "../frontend/app/src/services/planning.js";

const ström = (seed, antal = 12) => Array.from({ length: antal }, createSeededRandom(seed));

test("E9: samma frö ger samma ström, varje gång", () => {
  assert.deepEqual(ström(20260911), ström(20260911));
});

test("E9: olika frön ger olika strömmar", () => {
  assert.notDeepEqual(ström(1), ström(2));
});

test("E9: värdena ligger i [0,1) och klumpar sig inte", () => {
  const värden = ström(7, 500);
  assert.ok(värden.every(v => v >= 0 && v < 1), "alla värden ska vara giltiga sannolikheter");
  const halvor = värden.filter(v => v < 0.5).length;
  assert.ok(halvor > 200 && halvor < 300, `snedfördelad ström: ${halvor} av 500 under 0,5`);
});

test("E9: frö 0 låser inte strömmen", () => {
  const värden = ström(0, 5);
  assert.equal(new Set(värden).size, 5);
});

test("E9: newSeed ger ett heltal ur 32 bitar", () => {
  assert.equal(newSeed(() => 0), 0);
  assert.equal(newSeed(() => 0.5), 0x80000000);
  const frö = newSeed();
  assert.ok(Number.isInteger(frö) && frö >= 0 && frö <= 0xFFFFFFFF);
});

// ---- det som faktiskt gick fel -------------------------------------------

const RECEPT = Array.from({ length: 40 }, (_, i) => ({
  id: `r${i}`,
  vardagsmat: i % 3 === 0,
  proteinkalla: ["kyckling", "fläsk", "vegetariskt", "fisk"][i % 4],
  inkopspris: 60 + (i % 11) * 7,
}));

// Så här rankar everydayRank: klassen i heltalsdelen, slumpen i decimalen.
const rankMed = random => recipe => (recipe.vardagsmat ? 0 : 10) + random();
const poolMed = random => limitCandidatePool(RECEPT, 6, 18, "proteinkalla", "inkopspris", 5, rankMed(random))
  .map(recipe => recipe.id);

test("E9: samma frö ger samma kandidatpool - alltså samma vecka", () => {
  assert.deepEqual(poolMed(createSeededRandom(4242)), poolMed(createSeededRandom(4242)));
});

test("E9: ett nytt frö ger en ny vecka - slumpen är kvar, den är bara bestämd", () => {
  // Poängen med slumpen är att "Skapa ny vecka" inte ska ge samma vecka varje
  // gång. Med tjugo olika frön ska minst två pooler skilja sig.
  const pooler = new Set(Array.from({ length: 20 }, (_, i) => poolMed(createSeededRandom(i + 1)).join(",")));
  assert.ok(pooler.size > 1, "seedningen får inte göra urvalet konstant");
});

// ---- app.js ---------------------------------------------------------------

const source = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
// Kommentarerna bort: raden som FÖRKLARAR att Math.random är borta ska inte
// få testet att tro att den är kvar.
const kod = text => text.replace(/\/\/[^\n]*/g, "");

test("E9: everydayRank drar inte längre ur Math.random", () => {
  const rank = source.match(/const everydayRank = recipe => \{[\s\S]*?\n  \};/);
  assert.ok(rank, "everydayRank ska finnas kvar");
  assert.doesNotMatch(kod(rank[0]), /Math\.random/);
  assert.match(rank[0], /planRandom\(\)/);
});

test("E9: fröet dras när användaren ber om en ny vecka, inte vid varje omritning", () => {
  assert.match(source, /function chooseMenu\(shouldScroll = true\) \{\n(?:[^\n]*\n)*?\s*newWeekSeed\(\);/,
    "chooseMenu ska dra ett nytt frö");
  assert.match(source, /function openPlanComparison\(\) \{\n(?:[^\n]*\n)*?\s*newWeekSeed\(\);/,
    "veckojämförelsen ska dra ett nytt frö - och sedan låta alla sju korten läsa samma ström");
  assert.equal((source.match(/newWeekSeed\(\)/g) || []).length, 3,
    "en definition och exakt två 'skapa vecka'-tillfällen");
});
