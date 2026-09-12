// J4: entitlementen hämtades bara vid boot och vid inloggning.
//
// En PWA stängs aldrig. Telefonen låses, appen ligger kvar i bakgrunden i
// veckor, och den fortsätter rita det Premium den råkade se den morgon den
// startades. Säger någon upp sin prenumeration - eller går den ut, eller
// nekas kortet - står Premium kvar tills någon laddar om. Åt andra hållet är
// det lika fel: den som just uppgraderat i Stripes kundportal kommer tillbaka
// till en app som fortfarande visar lås. Köpflödet har en poll efter
// webhooken; portalen hade ingen.
//
// Testerna nedan är acceptanskriteriet. De första sex kör modulen som avgör
// NÄR svaret ska hämtas om; de sista fyra håller inkopplingen i app.js på
// plats, för en regel som ingen anropar är ingen regel.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ENTITLEMENT_STALE_AFTER_MS, createEntitlementRefresh } from "../frontend/app/src/services/entitlement-refresh.js";

const source = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");

// En app med en klocka man kan vrida på: `tick` är tiden telefonen låg i
// fickan, `calls` är varje gång appen faktiskt gick ut på nätet.
function app({ staleAfterMs, refresh } = {}) {
  let clock = 1_000_000;
  const calls = [];
  const refresher = createEntitlementRefresh({
    refresh: () => { calls.push(clock); return refresh ? refresh() : Promise.resolve(); },
    now: () => clock,
    ...(staleAfterMs === undefined ? {} : { staleAfterMs }),
  });
  return { refresher, calls, tick: ms => { clock += ms; } };
}

const THREE_WEEKS = 21 * 24 * 60 * 60 * 1000;

test("J4: appen som legat i bakgrunden i tre veckor hämtar entitlementen när den vaknar", async () => {
  // Själva förlusten: uppsägningen gick igenom hos Stripe för sjutton dagar
  // sedan och den här telefonen har inte frågat en enda gång sedan dess.
  const { refresher, calls, tick } = app();
  tick(THREE_WEEKS);

  await refresher.onResume();

  assert.deepEqual(calls.length, 1, "ett uppvaknande efter tre veckor måste fråga servern om planen igen");
});

test("J4: ett flikbyte sekunden efter svaret ger inget nytt anrop", async () => {
  // visibilitychange fyras vid varje alt-tab. Utan spärren blir ett vanligt
  // arbetspass hundratals anrop mot /api/entitlements - och då blir det
  // ogjort igen nästa gång någon mäter trafiken.
  const { refresher, calls, tick } = app();
  tick(1000);

  await refresher.onResume();

  assert.deepEqual(calls, [], "ett färskt svar ska inte hämtas om vid varje flikbyte");
});

test("J4: återkomsten från Stripes kundportal hämtar direkt, hur färskt svaret än är", async () => {
  // Den enda platsen där personen SJÄLV just ändrat sin prenumeration. Där
  // är spärren fel svar: hon står kvar framför skärmen och väntar på att
  // låsen ska släppa.
  const { refresher, calls, tick } = app();
  refresher.markBillingVisit();
  tick(1000);

  await refresher.onResume();

  assert.deepEqual(calls.length, 1, "efter kundportalen ska entitlementen hämtas om även om svaret är en sekund gammalt");
});

test("J4: portalbesöket är en engångsstämpel", async () => {
  const { refresher, calls, tick } = app();
  refresher.markBillingVisit();
  tick(1000);
  await refresher.onResume();

  tick(1000);
  await refresher.onResume();

  assert.deepEqual(calls.length, 1, "stämpeln gäller nästa uppvaknande, inte varje uppvaknande resten av dagen");
});

test("J4: två uppvaknanden i samma ögonblick ger ett anrop", async () => {
  // Native-appen skickar både appStateChange och visibilitychange när den
  // kommer tillbaka från bakgrunden. Det är ett uppvaknande, inte två.
  // (Det är åldersspärren som bär den här: hämtningen stämplar tiden innan
  // den går ut på nätet, så det andra uppvaknandet ser ett färskt svar.
  // Spärren i luften prövas av testet under.)
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const { refresher, calls, tick } = app({ refresh: () => pending });
  tick(THREE_WEEKS);

  const first = refresher.onResume();
  const second = refresher.onResume();
  release();
  await Promise.all([first, second]);

  assert.deepEqual(calls.length, 1, "ett svar i luften räcker - det andra uppvaknandet ska hänga på");
});

test("J4: ett svar som fortfarande är i luften när spärren löpt ut ger inget andra anrop", async () => {
  // Åldersspärren räcker bara så länge svaret kommer inom en minut. Ett
  // anrop som hänger längre än så - telefonen vaknade i tunneln och fetchen
  // väntar på sin timeout - släpper förbi nästa uppvaknande, och då är det
  // BARA spärren i luften som står mellan en sliten mobil och en kö av
  // parallella anrop mot /api/entitlements.
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const { refresher, calls, tick } = app({ refresh: () => pending });
  tick(THREE_WEEKS);

  const first = refresher.onResume();
  tick(ENTITLEMENT_STALE_AFTER_MS);
  const second = refresher.onResume();
  release();
  await Promise.all([first, second]);

  assert.deepEqual(calls.length, 1, "ett svar åt gången - det andra uppvaknandet ska hänga på det som redan är ute");
});

test("J4: ett nätfel river inte uppvaknandet, och nästa försök får komma", async () => {
  // Resten av onAppResumed() - hushållet och notiserna - får inte falla för
  // att telefonen vaknade i en tunnel.
  let fails = true;
  const { refresher, calls, tick } = app({
    refresh: () => (fails ? Promise.reject(new Error("nätet nere")) : Promise.resolve()),
  });
  tick(THREE_WEEKS);

  await refresher.onResume();
  assert.deepEqual(calls.length, 1);

  fails = false;
  tick(ENTITLEMENT_STALE_AFTER_MS);
  await refresher.onResume();

  assert.deepEqual(calls.length, 2, "ett misslyckat försök ska inte låsa vägen för nästa");
});

// --- Inkopplingen i app.js ------------------------------------------------

function blockAfter(marker) {
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, `${marker} finns inte i app.js`);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === "{") depth++;
    if (source[i] === "}") { depth--; if (depth === 0) return source.slice(start, i + 1); }
  }
  throw new Error(`Kunde inte läsa slut på ${marker}`);
}

test("J4: onAppResumed frågar om entitlementen", () => {
  assert.match(blockAfter("function onAppResumed("), /entitlementRefresh\.onResume\(/,
    "en app som vaknar måste fråga om planen - annars gäller fortfarande svaret från boot");
});

test("J4: knappen till kundportalen stämplar besöket", () => {
  assert.match(blockAfter('$("manageBillingBtn")'), /markBillingVisit\(/,
    "utan stämpeln vet appen inte att personen var hos Stripe och ändrade sin prenumeration");
});

test("J4: entitlementen hämtas förbi webbläsarens cache", () => {
  // Backend svarar redan `Cache-Control: no-store` (api_server.py send_json).
  // Klienten ska be om samma sak: ett cachat svar är per definition en gammal
  // plan, och det är hela felet paketet handlar om.
  const body = blockAfter("function fetchEntitlements(");
  assert.match(body, /cache:\s*"no-store"/,
    'fetch mot /api/entitlements ska skicka cache: "no-store"');
  assert.match(body, /entitlementRefresh\.markRefreshed\(/,
    "boot och inloggning hämtar också - deras svar måste räknas som färskt, annars hämtar nästa uppvaknande i onödan");
});

test("J4: kontots premiumflagga följer med entitlementen", () => {
  // hasPremium() läser entitlements.isPremium ELLER state.user.premium, och
  // kontoarket i views/account.js läser state.user.premium rakt av. Hämtas
  // bara entitlementen om står den uppsagda kvar som Premium ändå.
  assert.match(blockAfter("function fetchEntitlements("), /state\.user\.premium\s*=/,
    "en färsk entitlement måste också rätta den gamla premiumflaggan på kontot");
});
