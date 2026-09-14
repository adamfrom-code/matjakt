import test from "node:test";
import assert from "node:assert/strict";
import { QUARANTINE_KEY, STORAGE_KEY, quarantineStoredState, readStoredState, readStoredStateResult, writeStoredState } from "../frontend/app/src/state/storage.js";

function memoryStorage(initial = null) { let value = initial; return { getItem: () => value, setItem: (_key, next) => { value = next; } }; }

// En lagring med riktiga nycklar - karantänen bor i en EGEN nyckel, och den
// skillnaden är hela poängen med den.
function keyedStorage(initial = {}) {
  const data = { ...initial };
  return { data,
           getItem: key => (key in data ? data[key] : null),
           setItem: (key, value) => { data[key] = String(value); },
           removeItem: key => { delete data[key]; } };
}
test("state överlever omladdning", () => { const storage = memoryStorage(); assert.equal(writeStoredState(storage, { budget: 725, pantry: { Ris: 200 } }), true); assert.deepEqual(readStoredState(storage), { budget: 725, pantry: { Ris: 200 } }); });
test("trasig lagrad JSON kraschar inte appen", () => { assert.deepEqual(readStoredState(memoryStorage("{trasigt")), {}); });
test("vald veckoplan och avklarade varor kan sparas", () => { const storage = memoryStorage(); const state = { valda: ["linssoppa", "fiskpasta"], avklarade: ["Pasta"] }; writeStoredState(storage, state); assert.deepEqual(readStoredState(storage), state); });

// ---- E3: tomt och trasigt är inte samma sak -------------------------------
//
// Båda gav `{}` förut, och därmed samma tysta nollställning till
// standardvärdena - följd av att nästa sparning skrev över den text som var
// allt som fanns kvar av veckan på en enhet utan konto.

test("E3: läsningen skiljer tomt från trasigt", () => {
  assert.equal(readStoredStateResult(memoryStorage(null)).status, "tom");
  assert.equal(readStoredStateResult(memoryStorage("")).status, "tom");
  assert.equal(readStoredStateResult(memoryStorage("{trasigt")).status, "trasig");
  // Giltig JSON som ändå inte är ett tillstånd är precis lika oläsbar.
  assert.equal(readStoredStateResult(memoryStorage("[1,2,3]")).status, "trasig");
  assert.equal(readStoredStateResult(memoryStorage("null")).status, "trasig");
  const ok = readStoredStateResult(memoryStorage('{"budget":725}'));
  assert.equal(ok.status, "ok");
  assert.deepEqual(ok.state, { budget: 725 });
});

test("E3: en lagring som inte går att läsa alls är tom, inte trasig", () => {
  // Privat läge, avstängda kakor: getItem kastar. Det finns ingen text att
  // rädda undan och ingenting att berätta.
  const trasigLagring = { getItem: () => { throw new Error("SecurityError"); }, setItem: () => {} };
  assert.equal(readStoredStateResult(trasigLagring).status, "tom");
});

test("E3: den oläsbara texten flyttas undan - den skrivs inte över", () => {
  const storage = keyedStorage({ [STORAGE_KEY]: '{"weekPlan":["linssoppa"' });
  assert.equal(quarantineStoredState(storage, '{"weekPlan":["linssoppa"'), true);
  assert.equal(storage.data[QUARANTINE_KEY], '{"weekPlan":["linssoppa"');
  assert.equal(STORAGE_KEY in storage.data, false, "originalet flyttas, det kopieras inte");
  writeStoredState(storage, { budget: 900 });
  assert.equal(storage.data[QUARANTINE_KEY], '{"weekPlan":["linssoppa"',
               "nästa sparning får inte röra karantänen");
});

test("E3: på en full enhet räddas ingenting - och originalet lämnas i fred", () => {
  const full = { getItem: () => "{trasigt", setItem: () => { throw new Error("QuotaExceededError"); },
                 removeItem: () => { throw new Error("ska inte röras"); } };
  assert.equal(quarantineStoredState(full, "{trasigt"), false);
});
