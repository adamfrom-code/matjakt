import test from "node:test";
import assert from "node:assert/strict";
import { CATEGORY_ORDER, categoryFor, groupByCategory } from "../frontend/app/src/services/categories.js";

test("ingrediensnamnet avgör hyllan när vi känner igen det", () => {
  assert.equal(categoryFor("Mjölk"), "Mejeri");
  assert.equal(categoryFor("Kycklingfilé"), "Kött & fisk");
  assert.equal(categoryFor("Lök"), "Frukt & grönt");
  assert.equal(categoryFor("Wokgrönsaker"), "Frys");
  assert.equal(categoryFor("Pasta"), "Skafferi");
});

test("kedjans egen kategorisökväg används när namnet är okänt", () => {
  assert.equal(categoryFor("Arla Ko Standardmjölk", "Mejeri, ost & ägg/Mjölk & grädde"), "Mejeri");
  assert.equal(categoryFor("Okänd vara", "Fryst/Grönsaker"), "Frys",
    "fryst grönsak ska bli Frys, inte Frukt & grönt");
  assert.equal(categoryFor("Okänd vara", "Bröd & bageri/Matbröd"), "Bröd");
});

test("en vara vi inte känner igen får INTE en påhittad hylla", () => {
  assert.equal(categoryFor("Blöjor"), "Övrigt");
  assert.equal(categoryFor("Diskmedel", "Städ & hushåll/Disk"), "Övrigt");
});

test("skiftläge och diakriter spelar ingen roll", () => {
  assert.equal(categoryFor("crème fraiche"), "Mejeri");
  assert.equal(categoryFor("CREME FRAICHE"), "Mejeri");
});

test("sammansatta svenska namn ärver huvudordets hylla", () => {
  assert.equal(categoryFor("Kycklingfärs"), "Kött & fisk");
  assert.equal(categoryFor("Havregrynsgröt"), "Skafferi");
});

test("grupperingen följer butiksordningen, inte bokstavsordningen", () => {
  const items = [
    { namn: "Ärtor", category: "Frys" },
    { namn: "Mjölk", category: "Mejeri" },
    { namn: "Lök", category: "Frukt & grönt" },
    { namn: "Blöjor", category: "Övrigt" },
  ];
  const groups = groupByCategory(items, item => item.category);
  assert.deepEqual(groups.map(([name]) => name), ["Frukt & grönt", "Mejeri", "Frys", "Övrigt"]);
});

test("tomma hyllor ritas inte", () => {
  const groups = groupByCategory([{ category: "Mejeri" }], item => item.category);
  assert.deepEqual(groups.map(([name]) => name), ["Mejeri"]);
});

test("en okänd hylla hamnar under Övrigt i stället för att försvinna", () => {
  const groups = groupByCategory([{ category: "Kiosken" }], item => item.category);
  assert.deepEqual(groups, [["Övrigt", [{ category: "Kiosken" }]]]);
});

test("Övrigt ligger sist i ordningen", () => {
  assert.equal(CATEGORY_ORDER[CATEGORY_ORDER.length - 1], "Övrigt");
  assert.equal(CATEGORY_ORDER[0], "Frukt & grönt");
});
