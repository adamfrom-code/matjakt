// ---------------------------------------------------------------------------
// PRISHÄMTNINGEN
//
// Allt som går ut på nätet för att sätta ett pris på veckan: Matjakts egen
// prisdatabas, livepriserna hos den valda kedjan, filialjämförelsen, extra-
// varornas matchningar och butikslistan för postnumret. Låg tidigare utspritt
// i app.js på två håll (prisblocket och livepris-blocket) med sina egna
// modulvariabler mellan sig.
//
// Modulen känner inte till DOM:en. Den som behöver rita om något skickar in
// det (`onPricesChanged`, `onLiveStatusChanged`, `onBranchesChanged`) - det är
// också vad som gör det här prövbart utan webbläsare.
//
// OMFÖRSÖK PÅ ETT STÄLLE. Varje hämtning här kan misslyckas, och varje
// misslyckad hämtning brukade lösa det på sitt eget sätt: prisretryn staplade
// en ny setTimeout-kedja per fel, kampanjhämtningen nollade sin nyckel så
// nästa render sköt iväg ett nytt anrop, och butikshämtningen gjorde
// ingenting alls. `createRetryGate` är det enda mönstret nu: EN väntande
// timer, och en cooldown som säger nej till nya försök innan den löpt ut.
// ---------------------------------------------------------------------------

import { state } from "../state/app-state.js";
import { calculateLiveShoppingTotal } from "../services/calculations.js";
import { safeHttpUrl } from "../utils/html.js";
import { pricingListApiUrl, pricingWeekApiUrl, productsBatchApiUrl, storesApiUrl } from "../api/config.js";
import { getStoredToken } from "../api/auth.js";

// Det modulen behöver av appen: vem som frågar (Premium eller inte), vilken
// butik och vilken vecka det gäller, vad som finns hemma - och hur en
// omritning beställs. Inget av det bor här, och inget av det behövs för att
// pröva logiken.
let runtime = {
  hasPremium: () => false,
  chosenStore: () => "",
  selectedBranch: () => null,
  nearbyBranches: () => [],
  plannedRecipes: () => [],
  pantryForPricing: () => ({}),
  pantryForServer: () => ({}),
  // Kedjor vi faktiskt släppt live-hämtning för (app.js: VALID_CHAINS).
  isPricedChain: () => false,
  onPricesChanged: () => {},
  onLiveStatusChanged: () => {},
  onBranchesChanged: () => {},
  onBranchesLoaded: () => {},
  // Klockan och timerfunktionerna modulens egna omförsöksgrindar går genom.
  // De finns för att backoffen ska gå att pröva utan att åtta sekunder
  // faktiskt passerar; i appen är de setTimeout och Date.now.
  timers: null,
};

const clock = {
  now: () => (runtime.timers ? runtime.timers.now() : Date.now()),
  setTimer: (fn, ms) => (runtime.timers ? runtime.timers.setTimer(fn, ms) : setTimeout(fn, ms)),
  clearTimer: id => (runtime.timers ? runtime.timers.clearTimer(id) : clearTimeout(id)),
};

export function initPricingSync(overrides = {}) {
  runtime = { ...runtime, ...overrides };
}

// ---- omförsök ---------------------------------------------------------------

// Nya försök efter nätfel glesas ut (8 s, 16 s, ... max 2 min) och nollställs
// vid lyckat svar: offline på tåget ska inte ge ett anrop var åttonde
// sekund tills täckningen är tillbaka.
export const RETRY_BASE_MS = 8000;
export const RETRY_MAX_MS = 120_000;
export function retryDelay(count, base = RETRY_BASE_MS, max = RETRY_MAX_MS) {
  return Math.min(max, base * 2 ** count);
}

// En omförsöksgrind. Två löften, och det är de två som saknades:
//
//   1. `ready()` är FALSKT under hela väntetiden. Utan den räckte det att
//      nolla hämtningens nyckel vid fel för att nästa rendering skulle skjuta
//      iväg ett nytt anrop - och render-bussen körs vid varje interaktion, så
//      det blev ett anrop per knapptryck ovanpå den exponentiella kedjan.
//   2. EN väntande timer. `failed()` avbryter den gamla innan den sätter en
//      ny, så tio fel ger tio försök i följd - inte tio parallella kedjor som
//      var och en dubblar sig själv.
//
// Klockan och timerfunktionerna går att skicka in, vilket är hela skälet till
// att grinden går att pröva i Node utan att vänta åtta sekunder.
export function createRetryGate(onRetry, {
  base = RETRY_BASE_MS,
  max = RETRY_MAX_MS,
  now = () => Date.now(),
  setTimer = (fn, ms) => setTimeout(fn, ms),
  clearTimer = id => clearTimeout(id),
} = {}) {
  let failures = 0;
  let timer = null;
  let nextAttemptAt = 0;
  const stopTimer = () => { if (timer !== null) { clearTimer(timer); timer = null; } };
  return {
    // Får ett nytt försök göras nu?
    ready: () => now() >= nextAttemptAt,
    // Svaret kom: glöm väntetiden och den väntande timern.
    succeeded() { failures = 0; nextAttemptAt = 0; stopTimer(); },
    // Anropet misslyckades: stäng grinden så länge, och lägg EN ny väckning.
    failed() {
      const wait = retryDelay(failures, base, max);
      failures += 1;
      nextAttemptAt = now() + wait;
      stopTimer();
      timer = setTimer(() => { timer = null; nextAttemptAt = 0; onRetry(); }, wait);
      return wait;
    },
    // Ny avsikt från användaren (nytt postnummer, ny vecka) - då är den gamla
    // väntetiden inte längre relevant.
    reset() { failures = 0; nextAttemptAt = 0; stopTimer(); },
    // Insyn för tester och felsökning.
    waiting: () => timer !== null,
    failures: () => failures,
  };
}

// ---- gemensamt --------------------------------------------------------------

export function pricingHeaders() {
  // The pricing endpoints decide Free vs Premium SERVER-SIDE - but only if
  // they know who is asking. Without the token every user was anonymous,
  // and a paying customer got the masked Free response.
  const token = getStoredToken();
  return { "Content-Type": "application/json",
           ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

export function storeSelectionForPricing() {
  // Användarens butiker till prissättningen: närmaste butik per kedja (listan
  // är avståndssorterad från servern), pinnad butik vinner över närmaste.
  // Servern gör resten ärligt: nationellt prissatta kedjor etiketteras med
  // butiken, butiksspecifika prissätts BARA om just den butikens katalog
  // finns - annars rapporteras kedjan som otillgänglig i stället för att en
  // annan butiks priser visas under fel namn.
  const selection = {};
  for (const branch of runtime.nearbyBranches()) {
    if (branch.externalStoreId && !selection[branch.kedja]) selection[branch.kedja] = branch.externalStoreId;
  }
  const pinned = state.pinnedBranch;
  if (pinned?.externalStoreId && pinned.kedja) selection[pinned.kedja] = pinned.externalStoreId;
  return selection;
}

// The pricing request for the week's recipes: recipe IDS, not a client-built
// item list. The server aggregates from its own recipe rows - the same rows
// the recipe page shows - so the priced list can never drift from the
// recipes. Legacy/offline recipes without a bank id fall back to item lines.
export function weekPricingBody(shoppingItems) {
  const selected = runtime.plannedRecipes();
  const bankRecipes = selected.filter(recipe => recipe.priceStatus !== "unavailable"
    && (!Array.isArray(recipe.ingredients) || recipe.ingredients.length || recipe.slug));
  const recipeIds = bankRecipes.map(recipe => recipe.id);
  const body = { people: state.personer, pantry: runtime.pantryForServer() };
  // Borttagna varor måste följa med: recipeIds-vägen aggregerar om veckan på
  // servern, och utan denna lista skulle butiksjämförelsen fortsätta prissätta
  // varor användaren tagit bort.
  if (state.removedItems.size) body.excludeItems = [...state.removedItems].sort();
  if (recipeIds.length) body.recipeIds = recipeIds;
  else body.items = shoppingItems.map(item => ({ name: item.namn, amount: item.total, unit: item.unit }));
  const stores = storeSelectionForPricing();
  if (Object.keys(stores).length) body.stores = stores;
  return body;
}

// ---- butikerna nära användaren ---------------------------------------------

// Everything that describes WHERE the user shops. A new postcode invalidates
// all of it: keeping Gävle's branches, Gävle's fetched prices or a pinned
// Gävle store after a move to Stockholm would show the user a shop they
// cannot walk into and a total they cannot pay.
export function clearLocationDerivedState() {
  state.branches = [];
  clearPricesForNewBranches();
  // Ett nytt postnummer är en ny avsikt: den gamla väntetiden efter ett nätfel
  // ska inte hindra hämtningen för den stad användaren just skrev in.
  branchesRetry.reset();
}

// Prisbilden, men INTE butikslistan.
//
// Priserna hör ihop med butikerna och måste bort så fort en ny hämtning
// startar: Gävles summor får inte stå kvar under Stockholms butiker medan den
// nya listan är på väg. Butikslistan själv är en annan sak - den är vad
// användaren står och tittar på, och den ska bytas först när den nya faktiskt
// anlänt. Att den också tömdes i förväg var E13: vid nätfel var listan redan
// borta, inget nytt försök schemalades, och användaren stod kvar vid "Hittade
// inga inlästa butiker nära 12345 ännu" tills hon råkade redigera
// postnummerfältet.
function clearPricesForNewBranches() {
  state.liveBranchTotals = {};
  state.livePriser = {};
  state.dbChainTotals = {};
  state.dbComparison = null;
  state.dbPricedAt = null;
  state.liveUpdatedAt = null;
  // A branch pinned in the old town is not reachable from the new one.
  state.pinnedBranch = null;
  // Båda synkgrindarna måste glömma sin gamla nyckel, annars hoppas hämtningen
  // för det nya läget över som "redan gjord".
  databasePricingSync = { key: null, pending: false };
  branchComparisonSync = { key: null, branches: new Set() };
}

let branchesSync = { key: null, loading: false, pending: null };
const branchesRetry = createRetryGate(() => syncNearbyBranches(), clock);
export const branchesLoading = () => branchesSync.loading;
// Bara för tester: glöm vilket postnummer som senast hämtades.
export function resetBranchesSync() {
  branchesSync = { key: null, loading: false, pending: null };
  branchesRetry.reset();
}

export async function syncNearbyBranches() {
  const zip = state.postnummer;
  if (!/^\d{5}$/.test(zip) || branchesSync.key === zip) return;
  // A fetch already in flight used to make this return outright, so a
  // postcode typed while the previous one was loading was dropped and never
  // retried - the old town's stores simply stayed on screen. Remember the
  // pending postcode instead and pick it up when the current fetch settles.
  if (branchesSync.loading) { branchesSync.pending = zip; return; }
  // Efter ett nätfel väntar vi ut backoffen. Utan den grinden hade det nya
  // försöket nedan blivit ett anrop per render i stället för ett per period.
  if (!branchesRetry.ready()) return;
  branchesSync = { key: zip, loading: true, pending: null };
  // Här stod clearLocationDerivedState(), som också tömde butikslistan. Nu
  // rensas bara prisbilden: listan byts först när den nya faktiskt anlänt, och
  // under tiden säger butiksraden "(hämtar riktiga butiker nära dig...)" - det
  // är vad branchesSync.loading är till för.
  clearPricesForNewBranches();
  runtime.onBranchesChanged();
  try {
    // Always revalidate. A store list served from the browser's own cache is
    // how a user ends up looking at shops that are no longer near them (and
    // how a chain we just started carrying stays invisible). The server's own
    // cache still absorbs the cost - this only stops the CLIENT from holding
    // a stale copy.
    const response = await fetch(storesApiUrl(zip), { cache: "no-cache", signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (state.postnummer !== zip) return;
    // NU har den nya listan anlänt. Först här byts den gamla ut.
    state.branches = (data.butiker || []).map(store => ({ kedja: store.kedja, namn: store.namn, ort: store.ort || "", lat: store.lat, lon: store.lon, avstandKm: store.avstandKm, prisfaktor: 1, primatKey: store.primatKey || "",
      // Nationella butiksmodellen: butikens eget id + hur kedjan prissätter
      // (nationellt/per butik) + om den här butikens priser går att få.
      externalStoreId: store.externalStoreId || "", pricingScope: store.pricingScope || "", prisbar: store.prisbar !== false }));
    state.liveBranchTotals = {};
    branchesRetry.succeeded();
    // Only auto-pick a week here when the user doesn't already have one (same
    // guard as the startup call below) - this resolves on every single app
    // open once real branch data replaces the FALLBACK_BRANCH estimate, and
    // unconditionally regenerating would silently discard checked-off items,
    // cached prices, and even reshuffle an already-chosen week on every visit.
    if (!state.valda.size) runtime.onBranchesLoaded(); else runtime.onBranchesChanged();
  } catch {
    // The network did not answer. Vad som helst annat än ett nytt försök
    // lämnar användaren vid "Hittade inga inlästa butiker nära 12345 ännu"
    // tills hon råkar redigera postnummerfältet igen (E13). Nyckeln nollas så
    // nästa försök inte hoppas över som "redan hämtat", och grinden håller
    // takten: 8 s, 16 s, ... max 2 min, EN väntande timer.
    branchesSync.key = null;
    branchesRetry.failed();
  }
  finally {
    branchesSync.loading = false;
    const pending = branchesSync.pending;
    if (pending && pending !== state.postnummer) branchesSync.pending = null;
    if (pending) { branchesSync.pending = null; syncNearbyBranches(); }
  }
}

// ---- filialjämförelsen ------------------------------------------------------

function branchLiveTotal(shoppingItems, chainProducts) {
  return calculateLiveShoppingTotal(shoppingItems, chainProducts, runtime.pantryForPricing());
}
// A branch's stable identity for state.liveBranchTotals - primatKey, not
// chain name, since two branches of the same chain can genuinely have
// different prices (member deals, local campaigns - see cache_scope's
// docstring server-side). A branch with no primatKey (pure scrape fallback,
// nothing concrete to target) has no branch-specific live price to key -
// callers must check for that and leave it out rather than fetch it.
export function branchLiveKey(branch) { return branch.primatKey ? `${branch.kedja}#${branch.primatKey}` : null; }

let branchComparisonSync = { key: null, branches: new Set() };
export async function syncBranchComparison(shoppingItems, branches) {
  const names = shoppingItems.map(item => item.namn).sort();
  const key = `${state.postnummer}|${names.join(",")}`;
  if (branchComparisonSync.key !== key) { branchComparisonSync = { key, branches: new Set() }; state.liveBranchTotals = {}; }
  if (!names.length) return;
  // Filialpriser är Premium (servern nekar Free med 403) och pausas efter
  // 429/403 - annars blev varje filial ett avvisat anrop till.
  if (!runtime.hasPremium() || Date.now() < livePriceCooldownUntil) return;
  // Every nearby branch gets its own live fetch, keyed by its own primatKey -
  // this used to fetch once per CHAIN and let every branch of that chain
  // show that single result as if it were each branch's own live price
  // (found live 2026-08-30: four different Coop branches all showing an
  // identical "20 kr LIVE"). primatOnly:true because a scrape genuinely
  // can't answer "this specific branch" any differently from another branch
  // of the same chain (only Primat's store_key can) - with up to a dozen
  // nearby branches, this keeps every one of these calls on the fast
  // Primat/cache path and never triggers Playwright.
  const targets = branches.filter(branch => branch.primatKey && !branchComparisonSync.branches.has(branchLiveKey(branch)));
  targets.forEach(branch => branchComparisonSync.branches.add(branchLiveKey(branch)));
  // Each branch is fetched independently and in parallel - a slow/timed-out
  // one must not delay the others from starting or completing.
  await Promise.allSettled(targets.map(async branch => {
    if (branchComparisonSync.key !== key) return;
    try {
      const produkter = await fetchProductsBatch(branch.kedja, state.postnummer, names, undefined, branch.primatKey, true);
      if (branchComparisonSync.key !== key) return;
      const matched = Object.values(produkter).filter(Boolean);
      if (matched.length) { state.liveBranchTotals[branchLiveKey(branch)] = branchLiveTotal(shoppingItems, produkter); state.liveUpdatedAt = Date.now(); runtime.onPricesChanged(); }
    } catch { /* den här filialen visar kvar den statiska uppskattningen om livehämtningen misslyckas */ }
  }));
}

// =============================================================================
// REAL CHECKOUT PRICES FROM MATJAKT'S OWN PRICE DATABASE
// =============================================================================
// This is the good source. Everything else on this screen is either a flat
// static estimate or a best-effort text search of a store's site; this one
// prices the week against products actually collected into grocery.db, with
// real package maths (600 g of a 700 g pack costs a whole pack) and a
// coverage figure saying how much of the list it could really price.
//
// It is keyed by CHAIN, not by branch, because that is what the data
// honestly supports: Willys and Hemköp prices are verified national (the
// same query with two different storeIds returns byte-identical responses).
// Claiming a branch-specific number here would be inventing precision.
let databasePricingSync = { key: null, pending: false };
const pricingRetry = createRetryGate(() => runtime.onPricesChanged(), clock);
export const pricingIsPending = () => databasePricingSync.pending;
// Bara för tester och för planbytet nedan: glöm den senast prissatta veckan.
export function resetPricingSync() { databasePricingSync = { key: null, pending: false }; pricingRetry.reset(); }

export async function syncDatabasePricing(shoppingItems) {
  const body = weekPricingBody(shoppingItems);
  if (!body.recipeIds?.length && !body.items?.length) return;
  // Planen ingår i nyckeln: servern maskar Free-svaret (låsta kedjor), och
  // utan planen i nyckeln låg det maskade svaret kvar efter att Premium
  // aktiverats tills veckan råkade ändras (sett i E2E efter checkout).
  const key = `${runtime.hasPremium() ? "premium" : "free"}|${JSON.stringify(body)}`;
  if (databasePricingSync.key === key || databasePricingSync.pending) return;
  // Efter ett fel nollas nyckeln (se catch) - utan den här grinden betyder det
  // att NÄSTA rendering skjuter iväg ett nytt anrop, och render-bussen körs
  // vid varje interaktion. Ett anrop per knapptryck, ovanpå den väntande
  // omförsökstimern.
  if (!pricingRetry.ready()) return;
  databasePricingSync = { key, pending: true };
  try {
    const response = await fetch(pricingWeekApiUrl(), {
      method: "POST",
      headers: pricingHeaders(),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (databasePricingSync.key !== key) return;
    state.dbChainTotals = {};
    state.dbLockedChains = [];
    (data.results || []).forEach(result => {
      // Free's masked view: locked chains carry name + status only. They go
      // in their own list for the store cards; only full results may ever
      // enter dbChainTotals, so nothing downstream can mistake a silhouette
      // for a priced chain.
      if (result.locked) state.dbLockedChains.push(result);
      else state.dbChainTotals[result.chain] = result;
    });
    state.dbComparison = data.comparison || null;
    state.dbPricedAt = Date.now();
    pricingRetry.succeeded();
    runtime.onPricesChanged();
  } catch {
    // The price database being unreachable must never break the week view.
    // Nothing fake fills the gap - the views show "pris saknas", and this
    // timestamp is how they know the fetch actually failed rather than
    // simply not having finished yet.
    state.dbPricingFailedAt = Date.now();
    // A failure must not park the key forever: with the key left in place,
    // every later render concluded "already fetched" and the header said
    // "pris hämtas…" until a full reload. One deploy window was enough to
    // strand every open phone. Clear the key - grinden ovan håller takten.
    databasePricingSync.key = null;
    pricingRetry.failed();
  } finally {
    databasePricingSync.pending = false;
  }
}

// ---- extravarornas matchningar ---------------------------------------------

// Prices per chain resolve through src/services/extras.js: a real match at
// the current chain, or the item's own campaign price at its own chain,
// or nothing. state.extraMatches[chain][id] = { unitPrice, productName,
// imageUrl } - fetched from the same pricing API as everything else.
let extraMatchSync = {};
export function resetExtraMatchSync() { extraMatchSync = {}; }

export async function syncExtraMatches(chain) {
  const extras = state.extraItems;
  if (!extras.length || !chain || chain === "alla") return;
  const key = `${chain}|${extras.map(e => e.id + ":" + e.name).sort().join(",")}`;
  if (extraMatchSync[chain] === key) return;
  extraMatchSync[chain] = key;
  try {
    const response = await fetch(pricingListApiUrl(), {
      method: "POST",
      headers: pricingHeaders(),
      body: JSON.stringify({ chain, items: extras.map(e => ({ name: e.name, amount: 1, unit: "st" })) }),
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const byName = {};
    (data.items || []).forEach(item => {
      if (item.priceStatus !== "missing" && item.totalCost != null) byName[item.ingredient] = item;
    });
    state.extraMatches[chain] = {};
    extras.forEach(extra => {
      const hit = byName[extra.name];
      if (hit) state.extraMatches[chain][extra.id] = {
        unitPrice: hit.totalCost, productName: hit.productName, imageUrl: hit.imageUrl,
        packageSize: hit.packageSize,
      };
    });
    runtime.onPricesChanged();
  } catch {
    extraMatchSync[chain] = null; // försök igen nästa render
  }
}

// ---- livepriser hos den valda kedjan ---------------------------------------

// Matches the backend's MATJAKT_MAX_SCRAPES (production runs 2) - one item
// per request, up to this many in flight at once via a small worker pool
// below. One item per request (not several bundled into one) because a
// single item's scrape can itself take close to the request timeout (Coop in
// particular runs 18-25s even with nothing else competing for the backend's
// CPU) - bundling several into one request used to make the whole request
// fail together even when most of those items would have succeeded alone.
// Sending more in flight than the backend can actually run concurrently
// wouldn't help (they'd just queue there instead of here), and sending only
// one at a time would leave the backend's second worker idle the whole sync.
// Flera varor per anrop, ett anrop i taget. Varje anrop räknas mot
// serverns skrapspärr (30/min per IP) - ett anrop per vara gjorde en
// veckolista till tjugo anrop och produktionsloggen till en 429-storm.
// Vid 429/403 pausas live-hämtningen en minut i stället för att loopa.
// Skrapvägen tar fem varor per anrop så priserna landar löpande; den snabba
// Primat-/cachevägen (primatOnly) tar serverns max (20) - en filial, ett anrop.
const LIVE_PRICE_CHUNK = 5;
const LIVE_PRICE_CHUNK_FAST = 20;
const LIVE_PRICE_COOLDOWN_MS = 60_000;
let livePriceCooldownUntil = 0;

export async function fetchProductsBatch(chain, zip, names, onItem, storeKey, primatOnly) {
  const produkter = {};
  const size = primatOnly ? LIVE_PRICE_CHUNK_FAST : LIVE_PRICE_CHUNK;
  for (let start = 0; start < names.length; start += size) {
    if (Date.now() < livePriceCooldownUntil) break;
    const chunk = names.slice(start, start + size);
    try {
      const response = await fetch(productsBatchApiUrl(), {
        method: "POST", headers: pricingHeaders(),
        body: JSON.stringify({ butik: chain, zip, varor: chunk, ...(storeKey ? { butiksnyckel: storeKey } : {}), ...(primatOnly ? { primatOnly: true } : {}) }),
        signal: AbortSignal.timeout(35000),
      });
      if (response.status === 429 || response.status === 403) {
        livePriceCooldownUntil = Date.now() + LIVE_PRICE_COOLDOWN_MS;
        break;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const found = (await response.json()).produkter || {};
      Object.assign(produkter, found);
      onItem?.(found);
    } catch { /* den här gruppen missade - nästa grupp hämtas ändå */ }
  }
  return produkter;
}

function mapLiveProducts(produkter) {
  // pris_kr stays null when the backend genuinely has no confident price for
  // a matched product (Primat has the item but no current price, or -
  // filtered([, product]) => product) below keeps this - the entry is
  // entirely absent (null) rather than a wrongly-forced 0. Every downstream
  // reader (shoppingItemMarkup, weekShoppingRowMarkup, branchLiveTotal) must
  // treat pris_kr === null as "Pris saknas", never as a spendable price.
  return Object.fromEntries(Object.entries(produkter).filter(([, product]) => product).map(([namn, product]) => [namn, { pris_kr: product.pris_kr == null ? null : Number(product.pris_kr), produktnamn: String(product.produktnamn || namn), markeOchStorlek: String(product.marke_och_storlek || ""), url: safeHttpUrl(product.url), bild: product.bild ? safeHttpUrl(product.bild) : "", kalla: product.kalla || "", bildKalla: product.bild_kalla || "", kampanj: product.kampanj?.text ? { text: String(product.kampanj.text) } : null }]));
}

let livePriceSync = { key: null, loading: false };
export const livePricesLoading = () => livePriceSync.loading;

export async function syncLivePrices(shoppingItems) {
  const chain = runtime.chosenStore();
  // A pinned branch only applies here once selectedBranch() actually
  // resolved to it (i.e. its chain matches the chain being shopped) -
  // otherwise this is a plain chain-level fetch, same as always.
  const branch = runtime.selectedBranch();
  const storeKey = branch?.kedja === chain ? branch.primatKey : "";
  // ONLY the lines Matjakt's own price database could not answer. Everything
  // it CAN answer is already on screen, from our own collected data, with no
  // request to a chain at all.
  //
  // This is the line between the two halves of the system: collecting from
  // the chains is slow background work, and using Matjakt must never wait on
  // it. Before this, opening Handla fired a live per-item lookup for the
  // whole week even when every single item was already priced from our
  // database - a minute of requests to a chain, to arrive at prices we
  // already had.
  const priced = state.dbChainTotals[chain];
  const answered = new Set((priced?.items || [])
    .filter(item => item.priceStatus !== "missing")
    .map(item => item.ingredient));
  const names = shoppingItems.map(item => item.namn).filter(name => !answered.has(name)).sort();
  const key = `${chain}|${storeKey}|${state.postnummer}|${names.join(",")}`;
  // Free får aldrig live-priser: prisdatabasen svarar för den billigaste
  // butiken, och servern nekar ändå (403). Cooldown efter 429/403.
  if (!runtime.hasPremium()) return;
  if (Date.now() < livePriceCooldownUntil) return;
  if (!names.length || !runtime.isPricedChain(chain) || livePriceSync.loading || livePriceSync.key === key) return;
  livePriceSync = { key, loading: true };
  runtime.onLiveStatusChanged();
  try {
    // Applied per item as it arrives (not once at the end) - a full week can
    // take over a minute even when every item eventually succeeds, and
    // showing prices land one by one is a much better wait than a blank
    // "Hämtar..." the whole time.
    await fetchProductsBatch(chain, state.postnummer, names, found => {
      if (runtime.chosenStore() !== chain) return;
      const mapped = mapLiveProducts(found);
      if (Object.keys(mapped).length) { Object.assign(state.livePriser, mapped); state.liveUpdatedAt = Date.now(); runtime.onPricesChanged(); }
    }, storeKey);
  } catch { /* live-priser är ett tillägg ovanpå uppskattningen - misslyckas det visas bara uppskattningen kvar */ }
  finally { livePriceSync.loading = false; runtime.onLiveStatusChanged(); }
}
