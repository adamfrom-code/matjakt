// E8: två flikar skriver över varandra tyst.
//
// Testerna nedan är acceptanskriteriet. Det första återskapar själva
// förlusten - flik A bockar av, flik B skriver sin egen blob, A:s bockningar
// är borta - och kräver att flik A får veta. Resten håller beskedet från att
// bli brus: fel nyckel, oförändrat värde och en skur av skrivningar i samma
// stund ska inte ge ett besked var.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { OTHER_TAB_QUIET_MS, OTHER_TAB_TEXT, watchOtherTabs } from "../frontend/app/src/state/tab-sync.js";
import { STORAGE_KEY, readStoredState, writeStoredState } from "../frontend/app/src/state/storage.js";

// En webbläsare i miniatyr: EN lagring, flera flikar, och regeln som hela
// paketet hänger på - `storage` fyras i alla flikar UTOM den som skrev.
function browser({ clock = () => Date.now() } = {}) {
  let stored = null;
  const tabs = [];
  function openTab(options = {}) {
    const handlers = [];
    const tab = {
      notices: [],
      target: {
        addEventListener: (type, fn) => { if (type === "storage") handlers.push(fn); },
        removeEventListener: (type, fn) => {
          const index = handlers.indexOf(fn);
          if (index >= 0) handlers.splice(index, 1);
        },
      },
      storage: {
        getItem: () => stored,
        setItem: (key, next) => {
          const oldValue = stored;
          stored = next;
          tabs.filter(other => other !== tab)
            .forEach(other => other.receive({ key, oldValue, newValue: next }));
        },
      },
      receive: event => handlers.slice().forEach(fn => fn(event)),
    };
    tabs.push(tab);
    tab.stop = watchOtherTabs({
      target: tab.target, now: clock,
      onOtherTab: text => tab.notices.push(text), ...options,
    });
    return tab;
  }
  return { openTab };
}

test("E8: flik B skriver över flik A - och flik A får äntligen veta", () => {
  const { openTab } = browser();
  const a = openTab();
  const b = openTab();

  // Flik A bockar av två varor i Handla.
  writeStoredState(a.storage, { weekPlan: ["linssoppa"], avklarade: ["Pasta", "Gul lök"] });
  assert.deepEqual(a.notices, [], "den som skrev får inget besked om sin egen skrivning");
  assert.deepEqual(b.notices, [OTHER_TAB_TEXT], "flik B sitter nu på en gammal vecka och får veta det");

  // Flik B laddades innan bockningarna, byter recept och skriver HELA sin
  // blob. A:s bockningar finns inte i den - så här försvinner de.
  writeStoredState(b.storage, { weekPlan: ["korvgryta"], avklarade: [] });

  assert.deepEqual(readStoredState(a.storage).avklarade, [],
    "bockningarna är borta ur lagringen - det är faktumet beskedet finns för");
  assert.deepEqual(a.notices, [OTHER_TAB_TEXT], "flik A ska få beskedet, en gång");
});

test("E8: en annan nyckel i samma lagring angår inte veckan", () => {
  const { openTab } = browser();
  const a = openTab();
  openTab();
  a.receive({ key: "matjakt-token", oldValue: null, newValue: "abc" });
  assert.deepEqual(a.notices, []);
});

test("E8: samma blob igen är ingen ändring att varna för", () => {
  const { openTab } = browser();
  const a = openTab();
  const same = JSON.stringify({ weekPlan: ["linssoppa"] });
  a.receive({ key: STORAGE_KEY, oldValue: same, newValue: same });
  assert.deepEqual(a.notices, [], "en flik som speglar tillbaka kontots blob ändrade ingenting");
});

test("E8: storage.clear() i en annan flik räknas också", () => {
  const { openTab } = browser();
  const a = openTab();
  // Webbläsaren sätter key till null när hela lagringen tömts.
  a.receive({ key: null, oldValue: null, newValue: null });
  assert.deepEqual(a.notices, [OTHER_TAB_TEXT]);
});

test("E8: en skur av skrivningar ger ett besked, inte ett per skrivning", () => {
  let now = 1000;
  const { openTab } = browser({ clock: () => now });
  const a = openTab();
  const b = openTab();
  for (let i = 0; i < 20; i++) { now += 50; writeStoredState(b.storage, { budget: 800 + i }); }
  assert.deepEqual(a.notices, [OTHER_TAB_TEXT], "beskedet ska komma fram, inte hamra");

  // Men tystnaden är en paus, inte ett löfte om att aldrig säga det igen.
  now += OTHER_TAB_QUIET_MS;
  writeStoredState(b.storage, { budget: 1200 });
  assert.deepEqual(a.notices, [OTHER_TAB_TEXT, OTHER_TAB_TEXT]);
});

test("E8: lyssnaren går att koppla bort", () => {
  const { openTab } = browser();
  const a = openTab();
  const b = openTab();
  a.stop();
  writeStoredState(b.storage, { budget: 900 });
  assert.deepEqual(a.notices, []);
});

test("E8: utan fönster eller mottagare gör watchOtherTabs ingenting", () => {
  assert.equal(typeof watchOtherTabs(), "function", "ska ge en avregistrering ändå, inte kasta");
  assert.equal(typeof watchOtherTabs({ target: null, onOtherTab: () => {} }), "function");
});

test("E8: app.js lyssnar faktiskt på en annan flik", () => {
  // Modulen kan vara aldrig så rätt: kopplas den inte in i appen är
  // buggen kvar. Det här är den enda raden i app.js paketet behöver.
  const source = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
  assert.match(source, /watchOtherTabs\(\{/, "app.js ska registrera lyssnaren vid uppstart");
});
