import test from "node:test";
import assert from "node:assert/strict";
import {
  ALREADY_HAVE, NEED_TO_BUY, PURCHASED, applyLocalRow, applySync, emptyHouseholdState,
  handled, householdDietary, inventoryNames, inventoryRows, memberName, needToBuy,
  pantryAmountsFor, shoppingRows,
} from "../frontend/app/src/services/household-state.js";

const firstSync = {
  householdId: 1,
  revision: 4,
  household: { id: 1, name: "Familjen From", role: "admin", members: [{ userId: 1, displayName: "Adam" }] },
  shopping: [
    { key: "name:mjolk", name: "Mjölk", status: NEED_TO_BUY, revision: 2 },
    { key: "name:kaffe", name: "Kaffe", status: NEED_TO_BUY, revision: 3 },
  ],
  inventory: [{ key: "name:ris", name: "Ris", amount: 1000, unit: "g", location: "skafferi", revision: 4 }],
  docs: { week: { body: { weekPlan: ["tacos"] }, revision: 4 } },
};

test("första synken bygger hela hushållet", () => {
  const state = applySync(emptyHouseholdState(), firstSync);
  assert.equal(state.id, 1);
  assert.equal(state.name, "Familjen From");
  assert.equal(state.revision, 4);
  assert.equal(shoppingRows(state).length, 2);
  assert.deepEqual(state.docs.week.body, { weekPlan: ["tacos"] });
});

test("en delta-sync rör bara de rader som kom med", () => {
  const first = applySync(emptyHouseholdState(), firstSync);
  const next = applySync(first, {
    revision: 5,
    shopping: [{ key: "name:mjolk", name: "Mjölk", status: PURCHASED, revision: 5 }],
  });
  assert.equal(next.shopping["name:mjolk"].status, PURCHASED);
  assert.equal(next.shopping["name:kaffe"].status, NEED_TO_BUY, "Saras orörda rad ska ligga kvar");
  assert.equal(next.revision, 5);
  assert.equal(next.name, "Familjen From", "hushållsnamnet försvinner inte i en delta-sync");
});

test("ett fördröjt svar med ÄLDRE revision får inte skriva över ett nyare", () => {
  // Adam markerar mjölken som köpt (rev 5). Ett svar från en långsam
  // begäran med rev 2 kommer efteråt - utan skyddet hoppar raden tillbaka.
  let state = applySync(emptyHouseholdState(), firstSync);
  state = applySync(state, { revision: 5, shopping: [{ key: "name:mjolk", name: "Mjölk", status: PURCHASED, revision: 5 }] });
  state = applySync(state, { revision: 2, shopping: [{ key: "name:mjolk", name: "Mjölk", status: NEED_TO_BUY, revision: 2 }] });
  assert.equal(state.shopping["name:mjolk"].status, PURCHASED);
  assert.equal(state.revision, 5, "revisionen backar inte heller");
});

test("två medlemmars ändringar i samma sync landar båda", () => {
  const first = applySync(emptyHouseholdState(), firstSync);
  const next = applySync(first, {
    revision: 7,
    shopping: [
      { key: "name:mjolk", name: "Mjölk", status: PURCHASED, revision: 6 },
      { key: "name:kaffe", name: "Kaffe", status: ALREADY_HAVE, revision: 7 },
    ],
  });
  assert.equal(next.shopping["name:mjolk"].status, PURCHASED);
  assert.equal(next.shopping["name:kaffe"].status, ALREADY_HAVE);
});

test("behöver köpa / hanterat delas på status, inte på borttagning", () => {
  const state = applySync(emptyHouseholdState(), {
    revision: 3,
    shopping: [
      { key: "a", name: "Mjölk", status: NEED_TO_BUY, revision: 1 },
      { key: "b", name: "Ketchup", status: ALREADY_HAVE, revision: 2 },
      { key: "c", name: "Kaffe", status: PURCHASED, revision: 3 },
      { key: "d", name: "Lök", status: "REMOVED", revision: 3 },
    ],
  });
  assert.deepEqual(needToBuy(state).map(item => item.name), ["Mjölk"]);
  assert.deepEqual(handled(state).map(item => item.name), ["Ketchup", "Kaffe"]);
});

test("en optimistisk lokal ändring syns direkt och behåller övriga fält", () => {
  const state = applySync(emptyHouseholdState(), firstSync);
  const next = applyLocalRow(state, "shopping", { key: "name:mjolk", status: ALREADY_HAVE });
  assert.equal(next.shopping["name:mjolk"].status, ALREADY_HAVE);
  assert.equal(next.shopping["name:mjolk"].name, "Mjölk");
});

test("skafferiet filtreras på plats och döljer mjukt raderade rader", () => {
  const state = applySync(emptyHouseholdState(), {
    revision: 3,
    inventory: [
      { key: "a", name: "Ris", location: "skafferi", amount: 1, revision: 1 },
      { key: "b", name: "Mjölk", location: "kyl", amount: 1, revision: 2 },
      { key: "c", name: "Ärtor", location: "frys", amount: 1, deleted: true, revision: 3 },
    ],
  });
  assert.deepEqual(inventoryRows(state, "kyl").map(item => item.name), ["Mjölk"]);
  assert.deepEqual(inventoryRows(state, "frys"), []);
  assert.deepEqual(inventoryNames(state).sort(), ["Mjölk", "Ris"]);
});

test("skafferimängder rapporteras bara när vi faktiskt vet dem", () => {
  const state = applySync(emptyHouseholdState(), {
    revision: 4,
    inventory: [
      { key: "a", name: "Ris", amount: 1000, location: "skafferi", revision: 1 },
      { key: "b", name: "Soja", amount: 0, location: "skafferi", revision: 2 },
      { key: "c", name: "Lök", amount: null, location: "skafferi", revision: 3 },
      { key: "d", name: "Ärtor", amount: 500, location: "frys", deleted: true, revision: 4 },
    ],
  });
  assert.deepEqual(pantryAmountsFor(state), { Ris: 1000 },
    "en vara utan känd mängd får inte skickas som ett tal till prismotorn");
});

test("hushållets allergier slås ihop men kosttypen gör det inte", () => {
  const state = applySync(emptyHouseholdState(), {
    revision: 1,
    household: {
      id: 1, name: "Familjen From", role: "admin",
      members: [
        { userId: 1, displayName: "Adam", profile: { spice: "stark" } },
        { userId: 2, displayName: "Sara", profile: { diet: "vegetarisk", allergies: ["Nötter"] } },
        { userId: 3, displayName: "Ella", profile: { child: true, spice: "mild", dislikes: ["Svamp"] } },
      ],
    },
  });
  const dietary = householdDietary(state);
  assert.deepEqual(dietary.allergies, ["Nötter"]);
  assert.deepEqual(dietary.dislikes, ["Svamp"]);
  assert.equal(dietary.anyChild, true);
  assert.equal(dietary.spice, "mild", "den känsligaste i hushållet sätter nivån");
});

test("medlemsnamn faller tillbaka på e-postens lokaldel", () => {
  const state = applySync(emptyHouseholdState(), {
    revision: 1,
    household: {
      id: 1, name: "F", role: "admin",
      members: [{ userId: 1, displayName: null, email: "adam@example.com" }, { userId: 2, displayName: "Sara" }],
    },
  });
  assert.equal(memberName(state, 1), "adam");
  assert.equal(memberName(state, 2), "Sara");
  assert.equal(memberName(state, 99), "");
});

test("en tom sync ändrar ingenting", () => {
  const state = applySync(emptyHouseholdState(), firstSync);
  const next = applySync(state, { revision: 4, shopping: [], inventory: [], docs: {} });
  assert.deepEqual(next.shopping, state.shopping);
  assert.equal(next.revision, 4);
});
