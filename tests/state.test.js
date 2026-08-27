import test from "node:test";
import assert from "node:assert/strict";
import { readStoredState, writeStoredState } from "../frontend/src/state/storage.js";

function memoryStorage(initial = null) { let value = initial; return { getItem: () => value, setItem: (_key, next) => { value = next; } }; }
test("state överlever omladdning", () => { const storage = memoryStorage(); assert.equal(writeStoredState(storage, { budget: 725, pantry: { Ris: 200 } }), true); assert.deepEqual(readStoredState(storage), { budget: 725, pantry: { Ris: 200 } }); });
test("trasig lagrad JSON kraschar inte appen", () => { assert.deepEqual(readStoredState(memoryStorage("{trasigt")), {}); });
