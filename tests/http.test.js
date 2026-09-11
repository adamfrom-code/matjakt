// Acceptanskriterierna för F2 - alltså för E6 (tidsgräns) och E7 (svensk
// text). Båda fanns bara som frånvaro tidigare: auth.js och household.js
// hade varken signal eller översättning, och det syns inte i någon annan
// svit. Modulen känner ingen DOM, så testerna kör i Node.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// api/config.js läser <meta> för API-adressen vid import - samma stubb som i
// recipe-loading.test.js. Dynamisk import EFTER stubben.
globalThis.document = { querySelector: () => null, baseURI: "http://localhost/app/" };
const {
  NETWORK_ERROR_TEXT, REQUEST_TIMEOUT_MS, SERVER_ERROR_TEXT, TIMEOUT_ERROR_TEXT,
  errorText, request,
} = await import("../frontend/app/src/api/http.js");
const auth = await import("../frontend/app/src/api/auth.js");
const household = await import("../frontend/app/src/api/household.js");

const APP_DIR = new URL("../frontend/app/", import.meta.url);
const read = relative => readFileSync(new URL(relative, APP_DIR), "utf8");

function stubFetch(handler) {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return () => { globalThis.fetch = original; };
}

const jsonResponse = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

/** En server som tar emot anropet och sedan aldrig svarar - tills signalen avbryter. */
function deadServer(seen = {}) {
  return (url, init) => {
    seen.url = url;
    seen.init = init;
    return new Promise((_resolve, reject) => {
      if (!init?.signal) return; // ingen signal = hänger för evigt, precis som buggen
      init.signal.addEventListener("abort", () => reject(init.signal.reason
        || Object.assign(new Error("aborted"), { name: "AbortError" })));
    });
  };
}

// ---- E6: anropet avbryts, det hänger inte -------------------------------

test("E6: ett anrop som aldrig svarar avbryts av tidsgränsen", async () => {
  const restore = stubFetch(deadServer());
  try {
    const started = Date.now();
    const error = await request("/auth/me", { timeout: 40 }).catch(e => e);
    const waited = Date.now() - started;
    assert.ok(error instanceof Error, "anropet löstes i stället för att avbrytas");
    assert.equal(error.kind, "timeout");
    assert.ok(waited < 2000, `väntade ${waited} ms - tidsgränsen slog inte till`);
  } finally { restore(); }
});

test("E6: utan tidsgräns hänger samma anrop för evigt - därför behövs den", async () => {
  // Beviset att testet ovan mäter något: samma döda server, ingen signal.
  const restore = stubFetch(deadServer());
  try {
    const raced = await Promise.race([
      request("/auth/me", { timeout: 0 }).then(() => "svarade", () => "avbröts"),
      new Promise(resolve => setTimeout(() => resolve("hänger"), 120)),
    ]);
    assert.equal(raced, "hänger");
  } finally { restore(); }
});

test("E6: standardtiden är 15 sekunder och signalen följer med anropet", async () => {
  assert.equal(REQUEST_TIMEOUT_MS, 15000);
  const seen = {};
  const restore = stubFetch((url, init) => { seen.url = url; seen.init = init; return jsonResponse(200, {}); });
  try {
    await request("/auth/me", { token: "t" });
    assert.ok(seen.init.signal, "anropet saknade AbortSignal");
    assert.equal(seen.init.headers.Authorization, "Bearer t");
  } finally { restore(); }
});

test("E6: varje anrop i auth.js och household.js går genom request()", async () => {
  // Den verkliga regressionen vore ett nytt anrop som ropar fetch direkt och
  // därmed tappar både tidsgräns och översättning. Källan får vakta det.
  for (const file of ["src/api/auth.js", "src/api/household.js"]) {
    const source = read(file);
    assert.ok(!/(?<![\w.])fetch\s*\(/.test(source), `${file} anropar fetch direkt - då saknar det anropet tidsgräns`);
    assert.match(source, /from "\.\/http\.js"/, `${file} importerar inte den delade klienten`);
  }
});

test("E6: de riktiga auth- och hushållsanropen bär signalen", async () => {
  const calls = [];
  const restore = stubFetch((url, init) => { calls.push({ url, init }); return jsonResponse(200, {}); });
  try {
    await auth.login("a@b.se", "hemligt");
    await auth.fetchCurrentUser("t");
    await auth.fetchAccountState("t");
    await household.fetchHousehold("t");
    await household.createInvite("t");
    await household.previewInvite("inbjudan");
    assert.equal(calls.length, 6);
    for (const { url, init } of calls) assert.ok(init.signal, `${url} saknade tidsgräns`);
    assert.ok(calls[5].url.includes("/household/invite?token=inbjudan"));
    assert.equal(calls[5].init.headers.Authorization, undefined, "inbjudningslandningen ska fungera utan token");
  } finally { restore(); }
});

test("E6: ett keepalive-anrop får ingen tidsgräns - det ska överleva sidan", async () => {
  const seen = {};
  const restore = stubFetch((url, init) => { seen.init = init; return jsonResponse(200, {}); });
  try {
    await auth.saveAccountState("t", { weekPlan: [] }, { keepalive: true });
    assert.equal(seen.init.keepalive, true);
    assert.equal(seen.init.signal, undefined, "pagehide-synken dödas av en tidsgräns i ett döende dokument");
  } finally { restore(); }
});

// ---- E7: ingen engelsk teknikprosa på skärmen ---------------------------

test("E7: en TypeError från fetch blir svensk text, inte \"Failed to fetch\"", async () => {
  const restore = stubFetch(async () => { throw new TypeError("Failed to fetch"); });
  try {
    const error = await auth.login("a@b.se", "hemligt").catch(e => e);
    assert.equal(error.message, NETWORK_ERROR_TEXT);
    assert.equal(error.message, "Ingen kontakt med Matjakt. Kolla nätet och försök igen.");
    assert.ok(!/failed to fetch/i.test(error.message));
    assert.equal(errorText(error), NETWORK_ERROR_TEXT);
    // Orsaken finns kvar för den som felsöker - den visas bara inte.
    assert.equal(error.cause.message, "Failed to fetch");
  } finally { restore(); }
});

test("E7: timeouten har sin egen text - den ljuger inte om nätet", async () => {
  const restore = stubFetch(deadServer());
  try {
    const error = await request("/household", { token: "t", timeout: 30 }).catch(e => e);
    assert.equal(error.message, TIMEOUT_ERROR_TEXT);
    assert.equal(errorText(error), TIMEOUT_ERROR_TEXT);
    assert.ok(!/abort|timeout|signal/i.test(error.message), `teknisk term läckte: ${error.message}`);
  } finally { restore(); }
});

test("E7: \"HTTP 500\" når aldrig användaren", async () => {
  const restore = stubFetch(async () => jsonResponse(500, {}));
  try {
    const error = await auth.fetchCurrentUser("t").catch(e => e);
    assert.equal(error.message, SERVER_ERROR_TEXT);
    assert.ok(!/HTTP/.test(error.message));
  } finally { restore(); }
});

test("E7: serverns egen svenska text vinner över den generiska", async () => {
  const restore = stubFetch(async () => jsonResponse(400, { error: "Ange ett giltigt postnummer (5 siffror)" }));
  try {
    const error = await auth.login("a@b.se", "x").catch(e => e);
    assert.equal(error.message, "Ange ett giltigt postnummer (5 siffror)");
    assert.equal(errorText(error), "Ange ett giltigt postnummer (5 siffror)");
  } finally { restore(); }
});

test("E7: status och code följer med felet - 401 loggar fortfarande ut", async () => {
  // refreshUser() växlar på error.status === 401 och mailErrorText på
  // error.code. Tappas de tyst loggas ingen ut vid avvisad session.
  const restore = stubFetch(async () => jsonResponse(401, { code: "SESSION_EXPIRED" }));
  try {
    const error = await auth.fetchCurrentUser("gammal").catch(e => e);
    assert.equal(error.status, 401);
    assert.equal(error.code, "SESSION_EXPIRED");
    assert.equal(error.message, "Du är inte inloggad längre. Logga in igen.");
  } finally { restore(); }
});

test("E7: errorText tål ett rått fel från vilket håll som helst", () => {
  assert.equal(errorText(new TypeError("Failed to fetch")), NETWORK_ERROR_TEXT);
  assert.equal(errorText(new TypeError("Load failed")), NETWORK_ERROR_TEXT);
  assert.equal(errorText(Object.assign(new Error("signal timed out"), { name: "TimeoutError" })), TIMEOUT_ERROR_TEXT);
  assert.equal(errorText(Object.assign(new Error("aborted"), { name: "AbortError" })), TIMEOUT_ERROR_TEXT);
  assert.equal(errorText(new Error("Fel e-post eller lösenord")), "Fel e-post eller lösenord");
  assert.equal(errorText(undefined), SERVER_ERROR_TEXT);
});

test("E7: app.js skriver inget rått error.message i en felrad", () => {
  const source = read("app.js");
  const raw = source.split("\n")
    .map((line, index) => [index + 1, line])
    .filter(([, line]) => /textContent\s*=\s*(?:error|err|e)\??\.message/.test(line));
  assert.deepEqual(raw, [], `raderna nedan visar serverns/fetchs råa text för användaren:\n${raw.map(([n, l]) => `${n}: ${l.trim()}`).join("\n")}`);
});

test("E6: inloggningsknappen stängs av under anropet och släpps alltid", () => {
  const source = read("app.js");
  const handler = source.slice(source.indexOf(`$("accountLoginForm").addEventListener`));
  const body = handler.slice(0, handler.indexOf("\n});") + 4);
  assert.match(body, /submit\.disabled = true/, "knappen stängs aldrig av - dubbelsubmit mot en död knapp");
  assert.match(body, /finally\s*\{[^}]*submit\.disabled = false/, "knappen släpps inte i finally - ett fel låser formuläret");
});
