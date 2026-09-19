// E15 (1): offline fungerade inte för URL:er med query.
//
// `caches.match(request)` matchar på EXAKT URL. Varje djuplänk appen själv
// delar ut bär en query - ?recept=, ?invite=, ?verify=, ?reset=,
// ?billing=success - och ingen av dem finns i cachen, för de har aldrig
// hämtats förut. Offline gav alltså webbläsarens dinosaurie på precis de
// adresser som skickas i mejl och delas vidare.
//
// Testet kör den RIKTIGA sw.js i en vm med en webbläsare i miniatyr omkring
// sig: en cache som beter sig som Cache Storage (inklusive ignoreSearch) och
// ett nät som går att slå av.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const ORIGIN = "https://matjakt.store";
const swSource = readFileSync(new URL("../frontend/app/sw.js", import.meta.url), "utf8");

class FakeRequest {
  constructor(input, init = {}) {
    const base = typeof input === "string" ? { url: input } : input;
    this.url = base.url;
    this.method = init.method || base.method || "GET";
    this.mode = init.mode || base.mode || "no-cors";
    this.cache = init.cache || base.cache || "default";
  }
}

const navigation = url => new FakeRequest({ url, mode: "navigate" });
const asset = url => new FakeRequest({ url, mode: "cors" });

// Cache Storage i miniatyr: nyckeln är hela URL:en, och ignoreSearch letar
// utan query - precis som webbläsarens.
function fakeCaches() {
  const stores = new Map();
  const precached = [];
  const open = name => {
    if (!stores.has(name)) stores.set(name, new Map());
    const store = stores.get(name);
    return Promise.resolve({
      put: (request, response) => { store.set(request.url, response); return Promise.resolve(); },
      // AN2: addAll hämtar och lägger in - här bokförs bara vad som begärdes,
      // och en stubb läggs in så att offline-vägen kan hitta den.
      addAll: urls => {
        for (const url of urls) {
          const full = new URL(url, `${ORIGIN}/app/sw.js`).href;
          precached.push(full);
          store.set(full, { body: `FÖRHANDSCACHAD:${full}`, ok: true, clone: () => ({ body: full }) });
        }
        return Promise.resolve();
      },
    });
  };
  const lookup = (request, options = {}) => {
    const wanted = typeof request === "string" ? new URL(request, `${ORIGIN}/app/sw.js`).href : request.url;
    for (const store of stores.values()) {
      if (store.has(wanted)) return store.get(wanted);
      if (options.ignoreSearch) {
        const bare = wanted.split("?")[0];
        for (const [url, response] of store) if (url.split("?")[0] === bare) return response;
      }
    }
    return undefined;
  };
  return {
    api: {
      open,
      match: (request, options) => Promise.resolve(lookup(request, options)),
      keys: () => Promise.resolve([...stores.keys()]),
      delete: name => Promise.resolve(stores.delete(name)),
    },
    seed: (name, url, response) => {
      if (!stores.has(name)) stores.set(name, new Map());
      stores.get(name).set(url, response);
    },
    names: () => [...stores.keys()],
    precached,
  };
}

function loadServiceWorker({ online = true, cached = [] } = {}) {
  const listeners = {};
  const caches = fakeCaches();
  cached.forEach(url => caches.seed("matjakt-shell-vTEST", url, { body: url, ok: true, clone: () => ({ body: url }) }));
  const self = {
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    skipWaiting: () => {},
    clients: { claim: () => {} },
    location: { origin: ORIGIN },
  };
  const network = request => (online
    ? Promise.resolve({ ok: true, body: `NÄT:${request.url}`, clone: () => ({ body: `NÄT:${request.url}` }) })
    : Promise.reject(new TypeError("Failed to fetch")));

  vm.runInNewContext(swSource, { self, caches: caches.api, fetch: network, Request: FakeRequest, URL, Promise, console });

  return {
    caches,
    fire(type, request) {
      let answered;
      const event = { request, respondWith: promise => { answered = promise; }, waitUntil: () => {} };
      listeners[type].forEach(fn => fn(event));
      return answered;
    },
    install() {
      const waited = [];
      listeners.install.forEach(fn => fn({ waitUntil: promise => waited.push(promise) }));
      return Promise.all(waited);
    },
    activate() {
      const waited = [];
      listeners.activate.forEach(fn => fn({ waitUntil: promise => waited.push(promise) }));
      return Promise.all(waited);
    },
  };
}

test("E15: offline når en djuplänk med query appskalet i stället för ingenting", async () => {
  const sw = loadServiceWorker({ online: false, cached: [`${ORIGIN}/app/`] });
  const svar = await sw.fire("fetch", navigation(`${ORIGIN}/app/?recept=korvstroganoff`));
  assert.ok(svar, "en djuplänk ska inte ge webbläsarens felsida offline");
  assert.equal(svar.body, `${ORIGIN}/app/`, "appskalet är samma dokument oavsett query");
});

test("E15: varje djuplänk appen själv delar ut fungerar offline", async () => {
  const länkar = ["?recept=fiskpasta", "?invite=abc123", "?verify=xyz", "?reset=hemligt", "?billing=success"];
  for (const query of länkar) {
    const sw = loadServiceWorker({ online: false, cached: [`${ORIGIN}/app/`] });
    const svar = await sw.fire("fetch", navigation(`${ORIGIN}/app/${query}`));
    assert.ok(svar, `${query} gav ingen sida offline`);
  }
});

test("E15: en exakt cachad adress vinner över skalet", async () => {
  const sw = loadServiceWorker({ online: false, cached: [`${ORIGIN}/app/`, `${ORIGIN}/app/?recept=korv`] });
  const svar = await sw.fire("fetch", navigation(`${ORIGIN}/app/?recept=korv`));
  assert.equal(svar.body, `${ORIGIN}/app/?recept=korv`);
});

test("E15: bara NAVIGERINGAR faller tillbaka på skalet", async () => {
  // En bild eller ett API-anrop som saknas ska sakna svar - att svara med
  // HTML-skalet på en produktbild vore värre än att inte svara alls.
  const sw = loadServiceWorker({ online: false, cached: [`${ORIGIN}/app/`] });
  assert.equal(await sw.fire("fetch", asset(`${ORIGIN}/app/bild.png?w=480`)), undefined);
});

test("E15: nätet går före cachen när det finns", async () => {
  const sw = loadServiceWorker({ online: true, cached: [`${ORIGIN}/app/`] });
  const svar = await sw.fire("fetch", navigation(`${ORIGIN}/app/?recept=korv`));
  assert.equal(svar.body, `NÄT:${ORIGIN}/app/?recept=korv`);
});

test("E15: /api/ lämnas orört - priser och inloggning får aldrig komma ur en cache", async () => {
  const sw = loadServiceWorker({ online: false, cached: [`${ORIGIN}/app/`] });
  assert.equal(sw.fire("fetch", asset(`${ORIGIN}/api/pricing/week?x=1`)), undefined,
    "service workern ska inte ens svara på API-anrop");
});

test("E15: gamla cachar städas bort vid aktivering", async () => {
  const sw = loadServiceWorker({ cached: [`${ORIGIN}/app/`] });
  await sw.activate();
  assert.deepEqual(sw.caches.names(), [], "en cache med ett annat namn än det nuvarande ska bort");
});

// AN2: reservbanken förhandscachas vid install och finns offline.
test("AN2: reservbanken förhandscachas vid install", async () => {
  const sw = loadServiceWorker({ online: true });
  await sw.install();
  assert.deepEqual(sw.caches.precached, [`${ORIGIN}/app/data/recipes.json`]);
});

test("AN2: offline svarar reservbanken ur förhandscachen", async () => {
  const sw = loadServiceWorker({ online: true });
  await sw.install();
  // Nätet försvinner efter installationen: hämtningen faller, cachen svarar.
  const offline = loadServiceWorker({ online: false, cached: [] });
  offline.caches.seed("matjakt-shell-vTEST", `${ORIGIN}/app/data/recipes.json`, { body: "BANKEN", ok: true, clone: () => ({}) });
  const svar = await offline.fire("fetch", asset(`${ORIGIN}/app/data/recipes.json`));
  assert.equal(svar.body, "BANKEN");
});

test("AN2: en misslyckad förhandscachning stoppar inte installationen", async () => {
  const sw = loadServiceWorker({ online: false });
  await assert.doesNotReject(sw.install());
});
