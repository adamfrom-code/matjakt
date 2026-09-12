// H1: SÖNDAGSNOTISEN, KLIENTHALVAN.
//
// Två saker prövas här, och de är de två som avgör om paketet är byggt eller
// bara påstått:
//
//   1. `push` visar en notis och KASTAR ALDRIG. En push-händelse som kastar
//      får webbläsaren att visa sin egen "den här sajten uppdaterades i
//      bakgrunden" i stället - en notis ingen bad om och ingen kan tolka.
//   2. `notificationclick` leder till en SKAPAD VECKA, inte till startsidan.
//      Antingen genom att öppna ?notis=vecka, eller - om appen redan är
//      öppen - genom att skicka avsikten till den fliken.
//
// Service workern körs på riktigt i en vm, som i tests/service-worker.test.js.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

import {
  PUSH_DENIED, PUSH_NOT_ASKED, PUSH_NO_KEY, PUSH_OFF, PUSH_UNSUPPORTED,
  applicationServerKey, notificationIntent, pushSupported, syncWeeklyPush,
} from "../frontend/app/src/services/weekly-push.js";

const ORIGIN = "https://matjakt.store";
const swSource = readFileSync(new URL("../frontend/app/sw.js", import.meta.url), "utf8");

// ---- service workern -------------------------------------------------------

function loadServiceWorker({ windows = [] } = {}) {
  const listeners = {};
  const shown = [];
  const opened = [];
  const clients = windows.map(url => {
    const client = { url, messages: [], focused: false };
    client.postMessage = message => client.messages.push(message);
    client.focus = () => { client.focused = true; return Promise.resolve(client); };
    return client;
  });
  const self = {
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    skipWaiting: () => {},
    location: { origin: ORIGIN, href: `${ORIGIN}/app/sw.js` },
    registration: {
      showNotification: (title, options) => { shown.push({ title, options }); return Promise.resolve(); },
    },
    clients: {
      claim: () => {},
      matchAll: () => Promise.resolve(clients),
      openWindow: url => { opened.push(url); return Promise.resolve({ url }); },
    },
  };
  vm.runInNewContext(swSource, {
    self, caches: { open: () => Promise.resolve({ put: () => Promise.resolve() }), match: () => Promise.resolve(undefined), keys: () => Promise.resolve([]), delete: () => Promise.resolve(true) },
    fetch: () => Promise.reject(new Error("inget nät i det här testet")),
    Request: class {}, URL, Promise, console,
  });

  return {
    shown, opened, clients,
    push(data) {
      const waited = [];
      listeners.push.forEach(fn => fn({ data, waitUntil: promise => waited.push(promise) }));
      return Promise.all(waited);
    },
    click(notification) {
      const waited = [];
      let closed = false;
      const event = {
        notification: { ...notification, close: () => { closed = true; } },
        waitUntil: promise => waited.push(promise),
      };
      listeners.notificationclick.forEach(fn => fn(event));
      return Promise.all(waited).then(() => closed);
    },
  };
}

const pushData = payload => ({
  json: () => JSON.parse(payload),
  text: () => payload,
});

test("H1: söndagsnotisen visas med serverns text", async () => {
  const sw = loadServiceWorker();
  await sw.push(pushData(JSON.stringify({
    title: "Dags att planera veckan",
    body: "5 middagar för 4 personer — förslaget är redan klart.",
    url: "https://matjakt.store/app/?notis=vecka",
    tag: "matjakt-vecka",
  })));
  assert.equal(sw.shown.length, 1);
  assert.equal(sw.shown[0].title, "Dags att planera veckan");
  assert.equal(sw.shown[0].options.body, "5 middagar för 4 personer — förslaget är redan klart.");
  assert.equal(sw.shown[0].options.tag, "matjakt-vecka",
    "samma tag varje söndag - en oläst notis ska ERSÄTTAS, inte läggas på hög");
});

test("H1: en trasig nyttolast ger ändå en läsbar notis, aldrig ett kast", async () => {
  for (const data of [undefined, pushData("inte json alls"),
                      { json: () => { throw new TypeError("nope"); }, text: () => { throw new TypeError("nope"); } }]) {
    const sw = loadServiceWorker();
    await sw.push(data);
    assert.equal(sw.shown.length, 1, "en push utan giltig nyttolast måste ändå visa något");
    assert.equal(sw.shown[0].title, "Dags att planera veckan");
    assert.ok(sw.shown[0].options.body, "reservtexten får inte vara tom");
  }
});

test("H1: ett tryck öppnar veckan - inte startsidan", async () => {
  const sw = loadServiceWorker();
  const stängd = await sw.click({ data: { url: "https://matjakt.store/app/?notis=vecka" } });
  assert.equal(stängd, true, "notisen ska stängas när den tryckts");
  assert.deepEqual(sw.opened, ["https://matjakt.store/app/?notis=vecka"]);
});

test("H1: utan url i notisen öppnas ändå veckoavsikten, aldrig bara appen", async () => {
  const sw = loadServiceWorker();
  await sw.click({ data: {} });
  assert.equal(sw.opened.length, 1);
  assert.ok(sw.opened[0].endsWith("?notis=vecka"),
    `en notis utan url ska ändå leda till en vecka, fick ${sw.opened[0]}`);
});

test("H1: en redan öppen app får avsikten skickad till sig och lyfts fram", async () => {
  const sw = loadServiceWorker({ windows: [`${ORIGIN}/app/`] });
  await sw.click({ data: { url: `${ORIGIN}/app/?notis=vecka` } });
  assert.deepEqual(sw.opened, [], "en ny flik ska inte öppnas när appen redan är uppe");
  assert.equal(sw.clients[0].messages.length, 1);
  // Fälten, inte objektet: vm:ens Object har en annan prototyp än testets.
  assert.equal(sw.clients[0].messages[0].type, "matjakt-notis");
  assert.equal(sw.clients[0].messages[0].url, `${ORIGIN}/app/?notis=vecka`);
  assert.equal(sw.clients[0].focused, true);
});

test("H1: en flik på ett annat ursprung räknas inte som appen", async () => {
  const sw = loadServiceWorker({ windows: ["https://exempel.se/"] });
  await sw.click({ data: { url: `${ORIGIN}/app/?notis=vecka` } });
  assert.equal(sw.opened.length, 1, "en främmande flik får aldrig ta emot appens avsikt");
  assert.deepEqual(sw.clients[0].messages, []);
});

// ---- prenumerationen på klienten -------------------------------------------

function fakeScope({ permission = "granted", subscription = null, publicKeySeen = [] } = {}) {
  const saved = [];
  const requested = [];
  let current = subscription;
  const scope = {
    atob: globalThis.atob,
    PushManager: class {},
    Notification: {
      permission,
      requestPermission: () => {
        requested.push(true);
        return Promise.resolve(permission === "default" ? "granted" : permission);
      },
    },
    navigator: {
      serviceWorker: {
        ready: Promise.resolve({
          pushManager: {
            getSubscription: () => Promise.resolve(current),
            subscribe: options => {
              publicKeySeen.push(options.applicationServerKey);
              current = {
                endpoint: "https://push.example/abc",
                toJSON: () => ({ endpoint: "https://push.example/abc", keys: { p256dh: "P", auth: "A" } }),
                unsubscribe: () => { current = null; return Promise.resolve(true); },
              };
              return Promise.resolve(current);
            },
          },
        }),
      },
    },
  };
  return { scope, saved, requested, publicKeySeen, current: () => current };
}

const NYCKEL = "BCd0_ZqA1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_11223344556677889900aabb";

test("H1: samtycke krävs - ett påslaget tillstånd räcker inte", async () => {
  const { scope } = fakeScope({ permission: "granted" });
  const svar = await syncWeeklyPush({
    scope, publicKey: NYCKEL, wantsWeek: false, prompt: true,
    save: () => assert.fail("ingen prenumeration utan samtycke"),
    forget: () => Promise.resolve(),
  });
  assert.deepEqual(svar, { ok: false, reason: PUSH_OFF });
});

test("H1: ett nej frågas aldrig om igen", async () => {
  const { scope, requested } = fakeScope({ permission: "denied" });
  const svar = await syncWeeklyPush({
    scope, publicKey: NYCKEL, wantsWeek: true, prompt: true,
    save: () => assert.fail("nekat tillstånd får aldrig ge en prenumeration"),
  });
  assert.deepEqual(svar, { ok: false, reason: PUSH_DENIED });
  assert.deepEqual(requested, [], "dialogen ska inte ens visas för ett permanent nej");
});

test("H1: en bakgrundssynk visar aldrig tillståndsdialogen", async () => {
  const { scope, requested } = fakeScope({ permission: "default" });
  const svar = await syncWeeklyPush({ scope, publicKey: NYCKEL, wantsWeek: true, prompt: false, save: () => {} });
  assert.deepEqual(svar, { ok: false, reason: PUSH_NOT_ASKED });
  assert.deepEqual(requested, [], "bara ett tryck på 'Ny vecka' får fråga");
});

test("H1: utan VAPID-nyckel händer ingenting - och ingen dialog visas", async () => {
  const { scope, requested } = fakeScope({ permission: "default" });
  const svar = await syncWeeklyPush({ scope, publicKey: "", wantsWeek: true, prompt: true, save: () => {} });
  assert.deepEqual(svar, { ok: false, reason: PUSH_NO_KEY });
  assert.deepEqual(requested, [], "utan nyckel finns ingenting att prenumerera på");
});

test("H1: ja + tillstånd ger en prenumeration som skickas till servern", async () => {
  const sedda = [];
  const { scope } = fakeScope({ permission: "default", publicKeySeen: sedda });
  const skickat = [];
  const svar = await syncWeeklyPush({
    scope, publicKey: NYCKEL, wantsWeek: true, prompt: true, platform: "web",
    save: (json, platform) => { skickat.push({ json, platform }); return Promise.resolve(); },
  });
  assert.equal(svar.ok, true);
  assert.equal(skickat.length, 1);
  assert.equal(skickat[0].json.endpoint, "https://push.example/abc");
  assert.ok(sedda[0] instanceof Uint8Array, "applicationServerKey måste vara byte, inte en sträng");
});

test("H1: att slå av 'Ny vecka' säger upp prenumerationen hos BÅDE servern och webbläsaren", async () => {
  const befintlig = {
    endpoint: "https://push.example/abc",
    toJSON: () => ({ endpoint: "https://push.example/abc", keys: {} }),
    unsubscribe: () => { befintlig.uppsagd = true; return Promise.resolve(true); },
  };
  const { scope } = fakeScope({ permission: "granted", subscription: befintlig });
  const glömda = [];
  await syncWeeklyPush({
    scope, publicKey: NYCKEL, wantsWeek: false,
    save: () => assert.fail("inget ska sparas"),
    forget: endpoint => { glömda.push(endpoint); return Promise.resolve(); },
  });
  assert.deepEqual(glömda, ["https://push.example/abc"], "servern måste få veta först");
  assert.equal(befintlig.uppsagd, true);
});

test("H1: en webbläsare utan Web Push (Safari-fliken på iOS) rör ingenting", async () => {
  const scope = { navigator: { serviceWorker: {} } };   // ingen PushManager
  assert.equal(pushSupported(scope), false);
  const svar = await syncWeeklyPush({ scope, publicKey: NYCKEL, wantsWeek: true, prompt: true, save: () => {} });
  assert.deepEqual(svar, { ok: false, reason: PUSH_UNSUPPORTED });
});

test("H1: ?notis=vecka läses ur adressen, allt annat ignoreras", () => {
  assert.equal(notificationIntent("https://matjakt.store/app/?notis=vecka"), "vecka");
  assert.equal(notificationIntent("https://matjakt.store/app/?recept=korv"), "");
  assert.equal(notificationIntent("inte en adress"), "");
});

test("H1: VAPID-nyckeln blir samma byte som base64url beskriver", () => {
  const bytes = applicationServerKey("BAEC_-8", globalThis);
  assert.deepEqual([...bytes], [4, 1, 2, 255, 239]);
});

// ---------------------------------------------------------------------------
// Utloggningen får aldrig hänga på en service worker som inte finns
//
// navigator.serviceWorker.ready varken infrias eller avvisas när ingen worker
// blivit aktiv. Utloggningsknappen väntade på det anropet, och kontomodalen
// blev stående öppen - browser-E2E:n (test_full_consumer_journey) föll på att
// den fortfarande syntes. Ett try/catch hade inte hjälpt: det finns inget fel
// att fånga, bara ett await som aldrig återvänder.
// ---------------------------------------------------------------------------

/** Ett scope vars `ready` ALDRIG settlar - precis som en riktig webbläsare
 *  utan aktiv service worker. setTimeout skjuts fram direkt, så testet mäter
 *  att det finns ett tak, inte hur många millisekunder taket är. */
function hangingScope(permission = "granted") {
  return {
    atob: globalThis.atob,
    PushManager: class {},
    Notification: { permission, requestPermission: () => Promise.resolve(permission) },
    navigator: { serviceWorker: { ready: new Promise(() => { /* aldrig */ }) } },
    setTimeout: fn => globalThis.setTimeout(fn, 0),
  };
}

test("H1: avstängning ger upp när service workern aldrig blir klar - utloggningen hänger inte", async () => {
  const scope = hangingScope();
  // MUTATIONSPROVET: utan taket i readyRegistration() återvänder det här
  // await:et aldrig och testet tajmar ut i stället för att passera.
  const svar = await syncWeeklyPush({
    scope, publicKey: NYCKEL, wantsWeek: false,
    save: () => assert.fail("inget ska sparas"),
    forget: () => assert.fail("det finns ingen prenumeration att glömma"),
  });
  assert.deepEqual(svar, { ok: false, reason: PUSH_OFF });
});

test("H1: påslagning ger också upp - en worker som inte svarar tar inte emot push heller", async () => {
  const scope = hangingScope();
  const svar = await syncWeeklyPush({
    scope, publicKey: NYCKEL, wantsWeek: true, prompt: false,
    save: () => assert.fail("ingen prenumeration kunde skapas"),
  });
  assert.deepEqual(svar, { ok: false, reason: PUSH_UNSUPPORTED });
});
