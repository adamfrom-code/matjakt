// Prishämtningen: src/pricing/sync.js.
//
// Testerna nedan är acceptanskriterierna för E5 (kampanj- och prishämtningen
// blir en anropsstorm efter fel) och E13 (misslyckad butikshämtning ger
// permanent tomt tillstånd). Modulen känner varken till DOM eller nät - nätet
// stubbas, klockan och timerfunktionerna skickas in - så de körs i Node.
//
// Varje storm-test bevisar BÅDA riktningarna: att det nya sättet håller, och
// att det gamla faktiskt gick sönder. Utan den andra halvan säger den första
// ingenting.
import test from "node:test";
import assert from "node:assert/strict";

// Modulkedjan går via api/config.js som läser <meta> för API-adressen (samma
// stub som recipe-loading.test.js använder). Dynamisk import EFTER stubben.
globalThis.document = { querySelector: () => null, baseURI: "http://localhost/app/" };
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };

const { initAppState, state } = await import("../frontend/app/src/state/app-state.js");
const {
  RETRY_BASE_MS, branchesLoading, clearLocationDerivedState, createRetryGate,
  initPricingSync, pricingIsPending, resetBranchesSync, resetPricingSync,
  retryDelay, syncDatabasePricing, syncNearbyBranches,
} = await import("../frontend/app/src/pricing/sync.js");

// En klocka och en timerkö som testet självt styr: ingen väntan på riktiga
// åtta sekunder, och full insyn i hur många timers som ligger och väntar.
function fakeClock() {
  let now = 1_000_000;
  let nextId = 1;
  const timers = new Map();
  return {
    now: () => now,
    setTimer(fn, ms) { const id = nextId++; timers.set(id, { fn, at: now + ms }); return id; },
    clearTimer(id) { timers.delete(id); },
    waiting: () => timers.size,
    /** Flyttar klockan framåt och kör de timers som förfaller. */
    async advance(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) {
        if (timer.at <= now) { timers.delete(id); await timer.fn(); }
      }
    },
  };
}

function stubFetch(handler) {
  const original = globalThis.fetch;
  globalThis.fetch = handler;
  return () => { globalThis.fetch = original; };
}

const jsonResponse = body => ({ ok: true, status: 200, json: async () => body });

// ---- omförsöksgrinden ------------------------------------------------------

test("backoffen glesar ut och taket håller", () => {
  assert.equal(retryDelay(0), RETRY_BASE_MS);
  assert.equal(retryDelay(1), RETRY_BASE_MS * 2);
  assert.equal(retryDelay(2), RETRY_BASE_MS * 4);
  assert.equal(retryDelay(50), 120_000, "utan tak blir åttonde felet en timme");
});

test("E5: grinden är stängd under hela väntetiden - inte bara vid felet", () => {
  const clock = fakeClock();
  const gate = createRetryGate(() => {}, clock);
  assert.equal(gate.ready(), true);
  gate.failed();
  // Det här är hela buggen i en rad: render-bussen körs vid varje
  // interaktion, och varje körning frågade grinden om lov.
  for (let interaction = 0; interaction < 50; interaction++) {
    assert.equal(gate.ready(), false, "grinden släppte igenom ett anrop per interaktion");
  }
});

test("E5: tio fel ger EN väntande timer, inte tio parallella kedjor", () => {
  const clock = fakeClock();
  const gate = createRetryGate(() => {}, clock);
  for (let attempt = 0; attempt < 10; attempt++) gate.failed();
  assert.equal(clock.waiting(), 1, "den gamla timern avbröts inte innan en ny sattes");
  assert.equal(gate.failures(), 10, "backoffen ska ändå räkna varje fel");
});

test("ett lyckat svar nollställer både räknaren och den väntande timern", () => {
  const clock = fakeClock();
  const gate = createRetryGate(() => {}, clock);
  gate.failed();
  gate.succeeded();
  assert.equal(clock.waiting(), 0, "en timer som överlever ett lyckat svar ger en omritning för ingenting");
  assert.equal(gate.ready(), true);
  assert.equal(gate.failures(), 0);
});

test("när väntetiden gått ut körs omförsöket, en gång", async () => {
  const clock = fakeClock();
  let retries = 0;
  const gate = createRetryGate(() => { retries++; }, clock);
  gate.failed();
  await clock.advance(RETRY_BASE_MS - 1);
  assert.equal(retries, 0);
  await clock.advance(1);
  assert.equal(retries, 1);
  assert.equal(gate.ready(), true, "efter omförsöket ska grinden vara öppen igen");
});

// ---- E5: kampanjhämtningen -------------------------------------------------
//
// renderOwnCampaigns() i app.js ritar DOM och hör därför hemma där, men
// anropsmönstret är grindens. Testet kör exakt det mönstret: samma grind,
// samma ordning, en misslyckad hämtning och sedan en hög interaktioner.

function kampanjhamtning({ gate, hamta }) {
  const fetchState = { done: false, inFlight: false };
  return async function renderOwnCampaigns() {
    if (fetchState.done || fetchState.inFlight) return;
    if (!gate.ready()) return;
    fetchState.inFlight = true;
    try {
      await hamta();
      fetchState.done = true;
      gate.succeeded();
    } catch {
      gate.failed();
    } finally {
      fetchState.inFlight = false;
    }
  };
}

test("E5: en misslyckad kampanjhämtning ger INTE ett anrop per interaktion", async () => {
  const clock = fakeClock();
  let calls = 0;
  const gate = createRetryGate(() => render(), clock);
  const render = kampanjhamtning({ gate, hamta: async () => { calls++; throw new Error("nätet nere"); } });

  await render();
  assert.equal(calls, 1);
  // Tjugo knapptryck medan nätet fortfarande är nere. Render-bussen kör
  // renderCampaignSection() -> renderOwnCampaigns() vid varje.
  for (let tryck = 0; tryck < 20; tryck++) await render();
  assert.equal(calls, 1, "ett /grocery/campaigns-anrop per knapptryck - det är stormen");
  assert.equal(clock.waiting(), 1, "en omförsökskedja per fel staplar timers");

  // Och när backoffen löpt ut görs exakt ETT nytt försök.
  await clock.advance(RETRY_BASE_MS);
  assert.equal(calls, 2);
});

test("E5: det gamla mönstret gav ett anrop per interaktion - premissen håller", async () => {
  // Så såg koden ut: nyckeln nollades vid fel, och nästa render sköt iväg ett
  // nytt anrop. Utan det här testet bevisar testet ovan ingenting.
  let key = null;
  let calls = 0;
  const gammalRender = async () => {
    if (key === "done") return;
    key = "done";
    try { calls++; throw new Error("nätet nere"); } catch { key = null; }
  };
  await gammalRender();
  for (let tryck = 0; tryck < 20; tryck++) await gammalRender();
  assert.equal(calls, 21, "premissen för E5 stämmer inte - då mäter testet ovan fel sak");
});

// ---- E5: prisretryn --------------------------------------------------------

const VECKANS_VAROR = [{ namn: "Linser", total: 500, unit: "g" }];

// Ett tomt utgångsläge med testets egen klocka: modulens grindar lever i
// modulen och överlever mellan testerna, precis som i en körande app.
function startaTillstand({ onPricesChanged = () => {} } = {}) {
  const clock = fakeClock();
  initAppState({ storage: null, recipeBank: [] });
  state.postnummer = "12345";
  resetPricingSync();
  resetBranchesSync();
  initPricingSync({
    hasPremium: () => false,
    chosenStore: () => "Willys",
    selectedBranch: () => null,
    nearbyBranches: () => [],
    plannedRecipes: () => [],
    pantryForPricing: () => ({}),
    pantryForServer: () => ({}),
    isPricedChain: () => true,
    onPricesChanged,
    onLiveStatusChanged: () => {},
    onBranchesChanged: () => {},
    onBranchesLoaded: () => {},
    timers: clock,
  });
  return clock;
}

test("E5: en misslyckad prishämtning ger inte ett anrop per omritning", async () => {
  const clock = startaTillstand();
  let calls = 0;
  const restore = stubFetch(async () => { calls++; throw new Error("nätet nere"); });
  try {
    await syncDatabasePricing(VECKANS_VAROR);
    assert.equal(calls, 1);
    assert.equal(state.dbPricingFailedAt > 0, true, "vyerna måste kunna se att hämtningen faktiskt misslyckades");
    // Varje avbockning, varje synksvar, varje livepris-chunk kör renderBasket,
    // och renderBasket kör syncDatabasePricing.
    for (let omritning = 0; omritning < 20; omritning++) await syncDatabasePricing(VECKANS_VAROR);
    assert.equal(calls, 1, "nyckeln nollades vid fel och nästa omritning sköt iväg ett nytt anrop");
    assert.equal(pricingIsPending(), false);
    assert.equal(clock.waiting(), 1, "tjugo omritningar efter ett fel staplade tjugo omförsökstimers");
  } finally { restore(); }
});

test("E5: prisretryn väcker en omritning när backoffen gått ut", async () => {
  let omritningar = 0;
  const clock = startaTillstand({ onPricesChanged: () => { omritningar++; } });
  const restore = stubFetch(async () => { throw new Error("nätet nere"); });
  try {
    await syncDatabasePricing(VECKANS_VAROR);
    assert.equal(omritningar, 0);
    await clock.advance(RETRY_BASE_MS);
    assert.equal(omritningar, 1, "utan väckningen låg felet kvar tills något annat råkade rita om");
  } finally { restore(); }
});

test("prishämtningen fungerar som förut när servern svarar", async () => {
  startaTillstand();
  const restore = stubFetch(async () => jsonResponse({
    results: [{ chain: "Willys", totalCheckoutCost: 812, realPriceItems: 8, items: [] },
              { chain: "Hemköp", locked: true }],
    comparison: { cheapestChain: "Willys" },
  }));
  try {
    await syncDatabasePricing(VECKANS_VAROR);
    assert.equal(state.dbChainTotals.Willys.totalCheckoutCost, 812);
    assert.deepEqual(state.dbLockedChains.map(r => r.chain), ["Hemköp"], "maskade kedjor får aldrig in i dbChainTotals");
    assert.equal(state.dbComparison.cheapestChain, "Willys");
    assert.ok(state.dbPricedAt > 0);
  } finally { restore(); }
});

// ---- E13: butikshämtningen -------------------------------------------------

const BUTIKSSVAR = jsonResponse({ butiker: [
  { kedja: "Willys", namn: "Willys Gävle", primatKey: "willys-gavle", externalStoreId: "1" },
] });

test("E13: en misslyckad butikshämtning lämnar inte ett permanent tomt tillstånd", async () => {
  const clock = startaTillstand();
  // Så här ser det ut för någon som redan har butiker på skärmen.
  state.branches = [{ kedja: "Hemköp", namn: "Hemköp Centrum", primatKey: "hemkop-centrum" }];

  let calls = 0;
  let nere = true;
  const restore = stubFetch(async () => { calls++; if (nere) throw new Error("nätet nere"); return BUTIKSSVAR; });
  try {
    await syncNearbyBranches();
    assert.equal(calls, 1);
    // Butikslistan står kvar. Förut kördes clearLocationDerivedState() FÖRE
    // anropet, så listan var redan tömd när nätfelet kom - och användaren stod
    // kvar vid "Hittade inga inlästa butiker nära 12345 ännu" tills hon råkade
    // redigera postnummerfältet.
    assert.equal(state.branches.length, 1, "butikslistan tömdes av en hämtning som aldrig lyckades");
    assert.equal(branchesLoading(), false);

    // Och hämtningen försöker igen av sig själv - det är hela E13. Inget
    // anrop dessförinnan, hur många omritningar som än sker.
    for (let omritning = 0; omritning < 10; omritning++) await syncNearbyBranches();
    assert.equal(calls, 1, "grinden släppte igenom ett anrop per omritning");

    nere = false;
    await clock.advance(RETRY_BASE_MS);
    assert.equal(calls, 2, "inget nytt försök schemalades - listan fylls först om användaren råkar redigera postnumret");
    assert.equal(state.branches[0].namn, "Willys Gävle", "omförsöket fyllde inte listan");
    assert.equal(state.branches[0].prisbar, true, "prisbar ska tolkas som true när servern inte säger annat");
  } finally { restore(); }
});

test("E13: backoffen glesar ut försöken i stället för att hamra på ett dött nät", async () => {
  const clock = startaTillstand();
  let calls = 0;
  const restore = stubFetch(async () => { calls++; throw new Error("nätet nere"); });
  try {
    await syncNearbyBranches();
    assert.equal(calls, 1);
    await clock.advance(RETRY_BASE_MS);
    assert.equal(calls, 2);
    // Nästa försök ligger dubbelt så långt bort, inte lika nära.
    await clock.advance(RETRY_BASE_MS);
    assert.equal(calls, 2, "backoffen glesade inte ut - offline på tåget blir ett anrop var åttonde sekund");
    await clock.advance(RETRY_BASE_MS);
    assert.equal(calls, 3);
    assert.equal(clock.waiting(), 1, "tre fel ska ge en väntande timer, inte tre");
  } finally { restore(); }
});

test("E13: ett nytt postnummer rensar fortfarande den gamla stadens butiker och priser", async () => {
  startaTillstand();
  state.branches = [{ kedja: "Willys", namn: "Willys Gävle" }];
  state.dbChainTotals = { Willys: { chain: "Willys" } };
  state.pinnedBranch = { kedja: "Willys", primatKey: "willys-gavle" };
  clearLocationDerivedState();
  assert.deepEqual(state.branches, [], "Gävles butiker får inte stå kvar efter en flytt till Stockholm");
  assert.deepEqual(state.dbChainTotals, {});
  assert.equal(state.pinnedBranch, null);
});

test("butikshämtningen byter ut listan först när det nya svaret anlänt", async () => {
  startaTillstand();
  state.branches = [{ kedja: "Hemköp", namn: "Hemköp Centrum" }];
  state.postnummer = "12345";
  let sagtUnderHamtning = null;
  const restore = stubFetch(async () => {
    // Mitt i hämtningen: den gamla listan ska fortfarande synas, och raden ska
    // säga att en hämtning pågår.
    sagtUnderHamtning = { branches: state.branches.length, loading: branchesLoading() };
    return BUTIKSSVAR;
  });
  try {
    await syncNearbyBranches();
    assert.deepEqual(sagtUnderHamtning, { branches: 1, loading: true });
    assert.equal(state.branches[0].kedja, "Willys", "det nya svaret ska ersätta det gamla");
  } finally { restore(); }
});

test("prisbilden rensas däremot när hämtningen startar - Gävles summor får inte stå under Stockholms butiker", async () => {
  startaTillstand();
  state.branches = [{ kedja: "Hemköp", namn: "Hemköp Centrum" }];
  state.dbChainTotals = { Hemköp: { chain: "Hemköp", totalCheckoutCost: 780 } };
  state.pinnedBranch = { kedja: "Hemköp", primatKey: "hemkop-centrum" };
  const restore = stubFetch(async () => BUTIKSSVAR);
  try {
    await syncNearbyBranches();
    assert.deepEqual(state.dbChainTotals, {});
    assert.equal(state.pinnedBranch, null, "en butik pinnad i den gamla staden går inte att gå till från den nya");
  } finally { restore(); }
});

// ---- T3: grinden måste veta om svaret fortfarande står kvar ----------------
//
// Grindens nyckel är veckan plus planen. Den svarar alltså på OM VI FRÅGAT,
// aldrig på OM SVARET STÅR KVAR - och byter någon ut prisbilden utan att
// veckan ändras ser den ingenting. E16 rättade den överskrivning som utlöste
// det i CI (`count '3', Actual value: 1` efter ett premiumköp) och pekade
// samtidigt ut grinden som skälet att den blev permanent: "nyckeln är redan
// den premiumnyckeln, så den som betalat blir kvar i Free-vyn". Hålet finns
// kvar utan kontosynken - clearPriceSnapshots och utloggningen tömmer båda
// bilden utan att fråga grinden.

const PREMIUMSVAR = jsonResponse({
  results: [{ chain: "Willys", totalCheckoutCost: 491, realPriceItems: 17 },
            { chain: "Hemköp", totalCheckoutCost: 579, realPriceItems: 17 },
            { chain: "City Gross", totalCheckoutCost: 535, realPriceItems: 17 }],
  comparison: { cheapestChain: "Willys" },
});

test("T3: när prisbilden bytts ut bakom grindens rygg hämtas veckan om", async () => {
  startaTillstand();
  let calls = 0;
  const restore = stubFetch(async () => { calls++; return PREMIUMSVAR; });
  try {
    await syncDatabasePricing(VECKANS_VAROR);
    assert.equal(Object.keys(state.dbChainTotals).length, 3);
    assert.equal(calls, 1);

    // Oförändrad prisbild: grinden ska INTE hämta om. Det är den halvan som
    // håller nere anropen, och den får inte offras för den andra.
    for (let omritning = 0; omritning < 10; omritning++) await syncDatabasePricing(VECKANS_VAROR);
    assert.equal(calls, 1, "en oförändrad vecka får inte ge ett anrop per omritning");

    // Kontots blob landar och ersätter svaret med en äldre bild. Grinden såg
    // ingenting: samma vecka, samma plan, samma nyckel - och svarade "redan
    // hämtat" för alltid. Trettio sekunder senare stod EN kedja kvar på
    // skärmen, och det var så CI-felet såg ut.
    state.dbChainTotals = { Willys: { chain: "Willys", totalCheckoutCost: 491 } };
    state.dbPricedAt = 1;
    await syncDatabasePricing(VECKANS_VAROR);
    assert.equal(calls, 2, "grinden svarade 'redan hämtat' om ett svar som inte längre fanns kvar");
    assert.equal(Object.keys(state.dbChainTotals).length, 3);
  } finally { restore(); }
});

test("T3: en ersatt hämtning nollar inte den nya hämtningens pending-flagga", async () => {
  startaTillstand();
  let calls = 0;
  const grindar = [];
  const restore = stubFetch(async () => {
    calls++;
    await new Promise(resolve => grindar.push(resolve));   // hänger tills testet släpper
    return PREMIUMSVAR;
  });
  try {
    // Stubben hänger på sin egen grind, så hämtningen ligger kvar i luften
    // efter anropet. `await null` släpper fram en microtask så det som köats
    // har kört innan läget läses - svaret har ändå inte kommit.
    const freeAnropet = syncDatabasePricing(VECKANS_VAROR);
    await null;
    assert.equal(calls, 1);
    assert.equal(pricingIsPending(), true);

    // Premium slår till mitt i: fetchEntitlements nollar grinden och rensar
    // prisbilden, och nästa omritning startar hämtningen på nytt.
    resetPricingSync();
    state.dbChainTotals = {}; state.dbLockedChains = []; state.dbPricedAt = null;
    const premiumAnropet = syncDatabasePricing(VECKANS_VAROR);
    await null;
    assert.equal(calls, 2);
    assert.equal(pricingIsPending(), true);

    // Nu svarar den ÖVERGIVNA hämtningen. Dess `finally` skrev
    // `databasePricingSync.pending = false` på MODULVARIABELN - alltså på den
    // nya hämtningens post, som fortfarande var i luften. Efter det stod
    // grinden öppen mitt under ett pågående anrop.
    grindar[0]();
    await freeAnropet;
    assert.equal(pricingIsPending(), true, "den övergivna hämtningen nollade den nya hämtningens flagga");
    await syncDatabasePricing(VECKANS_VAROR);
    assert.equal(calls, 2, "en tredje hämtning startade parallellt med den som redan pågick");

    grindar[1]();
    await premiumAnropet;
    assert.equal(pricingIsPending(), false);
    assert.equal(Object.keys(state.dbChainTotals).length, 3);
  } finally { restore(); grindar.forEach(slapp => slapp()); }
});
