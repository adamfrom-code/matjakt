// iOS 15 (Capacitors deployment target) saknar AbortSignal.timeout - utan
// polyfillen kastar varje prisanrop TypeError och listan står på "hämtas…".
if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout !== "function") {
  AbortSignal.timeout = ms => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(new DOMException("TimeoutError", "TimeoutError")), ms);
    return controller.signal;
  };
}
import { readStoredState, writeStoredState } from "./src/state/storage.js";
import { aggregateIngredients, budgetRemaining, calculateLiveShoppingTotal, calculateShoppingTotal, clampBudget, packagesFor, portionFactor } from "./src/services/calculations.js";
import { createDebouncedSearch, filterRecipes, mergeRecipeResults } from "./src/services/recipe-search.js";
import { filterByNutritionGoals, hasActiveNutritionGoals } from "./src/services/nutrition.js";
import { PANTRY_LOCATIONS, expiryStatus, matchLocalRecipesToPantry, normalizePantry, pantryAmounts } from "./src/services/pantry.js";
import { extraLineTotal, extraUnitPrice, extrasTotal, newExtraItem, removeExtra, setQty } from "./src/services/extras.js";
import { ALLERGENS, filterByDiet, mergeDiet } from "./src/services/diet.js";
import { inBudgetPool, limitCandidatePool, pickBalanced, pickCheapest, pickProtein } from "./src/services/planning.js";
import { API_BASE_URL, entitlementsApiUrl, geocodeApiUrl, pricingListApiUrl, pricingWeekApiUrl, productApiUrl as configuredProductApiUrl, productsBatchApiUrl, recipeDetailApiUrl, recipeSearchApiUrl, recipesByPantryApiUrl, storesApiUrl } from "./src/api/config.js";
import { setMarketingConsent, changePassword, deleteAccount, fetchAccountState, fetchCurrentUser, getStoredToken, login, logout as logoutRequest, openBillingPortal, redeemPremium, register, requestPasswordReset, resendVerification, resetPassword, saveAccountState, startCheckout, storeToken, verifyEmail } from "./src/api/auth.js";
import { escapeHtml, safeHttpUrl } from "./src/utils/html.js";
import { TAG_LABELS, hasTag, loadRecipe, loadRecipes, loadShelves, matchesAllTags } from "./src/data/recipes.js";
import { adjustInventory, createHousehold, createInvite, fetchHousehold, fetchNotifications, joinHousehold, leaveHousehold, markAtHome, markPurchased, previewInvite, removeInventoryItem, removeMember, replaceWeekItems, saveHouseholdProfile, saveNotificationPrefs, setShoppingStatus, syncHousehold, undoShoppingAction, upsertInventoryItem, upsertShoppingItem } from "./src/api/household.js";
import { ALREADY_HAVE, NEED_TO_BUY, PURCHASED, REMOVED, applyLocalRow, applySync, emptyHouseholdState, foldName, householdDietary, inventoryNames, inventoryRows, pantryAmountsFor, shoppingKey, shoppingRows } from "./src/services/household-state.js";
import { categoryFor, groupByCategory } from "./src/services/categories.js";
import { SWAP_INTENTS, pantryOverlap, rankSwapOptions, recentlyEatenPenalty, swapCostText, swapReasonText, weekCostAlert } from "./src/services/swap.js";
import { RECIPE_FALLBACK_ART, RECIPE_FALLBACK_LABEL, kindFor as recipeFallbackKind } from "./src/services/recipe-fallback.js";
import { recordWeekSaving, weekKeyFor } from "./src/services/savings-log.js";
import { budgetScopeText as budgetScopeFor } from "./src/services/budget-scope.js";
import { planWarning } from "./src/services/plan-warning.js";
import { ASSUMED_STATE, assumedHomeItems, assumedState } from "./src/services/assumed-home.js";
import { takeUrlTokens } from "./src/services/url-tokens.js";

// FÖRST AV ALLT, före en enda rad annan startkod: engångstoken ur
// adressfältet. `?reset=` är ett fullständigt kontoövertagande i klartext
// och låg kvar i adressfält, historik och sessionsåterställning ända tills
// det nya lösenordet hunnit skickas in - och besöksstatistiken
// (Plausible/Umami, tillåtna i CSP:n) skickar sidans FULLA URL som
// sidvisning. Se src/services/url-tokens.js för hela resonemanget.
// Värdena lever i minnet resten av besöket; adressraden får dem aldrig igen.
const urlTokens = takeUrlTokens();

// The recipe bank is DATA, loaded from data/recipes.json - see
// src/data/recipes.js. It used to be two hardcoded arrays right here, which
// made every new recipe a change to the UI file. Filled once at startup;
// everything below reads it exactly as it did before.
const RECEPT = [];

// Kort och rader ritar bilden i som mest ~400 px - att ladda 940px-varianten
// där är 3x bandbredd för ingenting (85 kB -> 27 kB per kort, mätt).
// Pexels CDN skalar via query-parametrar; receptdetaljen behåller originalet.
const cardImageUrl = url => typeof url === "string" && url.includes("images.pexels.com")
  ? url.replace(/([?&])h=\d+&w=\d+/, "$1h=330&w=480")
  : url;
function recipeFallbackMarkup(recipe) {
  const kind = recipeFallbackKind(recipe);
  const label = RECIPE_FALLBACK_LABEL[kind];
  // aria-label säger att bilden saknas, inte vad ikonen föreställer: en
  // skärmläsare ska inte tro att vi visar ett foto av rätten.
  return `<span class="recipe-photo recipe-fallback kind-${kind}" role="img" aria-label="Ingen matbild tillgänglig"><svg viewBox="0 0 64 64">${RECIPE_FALLBACK_ART[kind]}</svg><small>${label}</small></span>`;
}
const recipePhoto = recipe => recipe.bild ? `<img class="recipe-photo" src="${escapeHtml(safeHttpUrl(cardImageUrl(recipe.bild)) || "")}" alt="${escapeHtml(recipe.namn)}" loading="lazy" decoding="async">` : recipeFallbackMarkup(recipe);
// A photo URL that 404s or is blocked must degrade into the same calm icon
// as "no photo at all". Without this the card showed the browser's
// broken-image glyph with the alt text spilled across it - which reads as a
// bug, in the one place a food app is supposed to look appetising.
window.addEventListener("error", event => {
  const img = event.target;
  if (img?.tagName === "IMG" && !img.dataset.fell
      && (img.classList?.contains("shopping-item-image") || img.classList?.contains("chain-item-photo"))) {
    // Produktbild som 404:ar eller blockeras: kategori-ikonen i stället för
    // webbläsarens trasiga-bild-glyf. Varunamnet sitter på radens checkbox.
    img.dataset.fell = "1";
    const name = img.closest("label, .shopping-item")?.querySelector("[data-shopping]")?.dataset.shopping || "";
    const holder = document.createElement("span");
    holder.innerHTML = categoryIconMarkup(itemCategory(name));
    if (holder.firstChild) img.replaceWith(holder.firstChild);
    return;
  }
  if (img?.tagName === "IMG" && img.classList?.contains("recipe-photo") && !img.dataset.fell) {
    img.dataset.fell = "1";
    const holder = document.createElement("span");
    // alt bär rättens namn (recipePhoto sätter det), så en bild som 404:ar
    // får samma kategoriikon som ett recept helt utan foto - inte den
    // generiska. Utan det såg ett trasigt fotolänk annorlunda ut än ett
    // saknat, vilket är förvirrande på samma kort.
    holder.innerHTML = recipeFallbackMarkup({ namn: img.alt || "" });
    img.replaceWith(holder.firstChild);
  }
}, true);
const macroLine = recipe => recipe.kcal ? `${recipe.kcal} kcal · ${recipe.protein} g protein · ${recipe.kolhydrater} g kolhydrater · ${recipe.fett} g fett` : "";
function recipeRatingMarkup(recipeId) {
  const current = state.betyg[recipeId] || 0;
  const stars = [1, 2, 3, 4, 5].map(n => `<button type="button" class="recipe-star ${n <= current ? "filled" : ""}" data-rate-recipe="${n}" aria-label="Betygsätt ${n} av 5">★</button>`).join("");
  return `<div class="recipe-rating"><span>${current ? "Ditt betyg" : "Har du lagat den här? Betygsätt den"}</span><div class="recipe-stars">${stars}</div></div>`;
}
function wireRatingStars(container, recipeId) {
  container.querySelectorAll("[data-rate-recipe]").forEach(button => button.addEventListener("click", () => {
    const value = Number(button.dataset.rateRecipe);
    state.betyg[recipeId] = state.betyg[recipeId] === value ? undefined : value;
    if (state.betyg[recipeId] === undefined) delete state.betyg[recipeId];
    saveState();
    const holder = container.querySelector(".recipe-rating");
    if (holder) holder.outerHTML = recipeRatingMarkup(recipeId);
    wireRatingStars(container, recipeId);
  }));
}
function recipeFeedback(recipeId) { return state.feedback[recipeId] || {}; }
function feedbackMarkup(recipeId) {
  const fb = recipeFeedback(recipeId);
  return `<div class="recipe-feedback"><button type="button" class="feedback-btn ${fb.liked ? "active" : ""}" data-like-recipe="${escapeHtml(recipeId)}">Gillar</button><button type="button" class="feedback-btn dislike ${fb.disliked ? "active" : ""}" data-dislike-recipe="${escapeHtml(recipeId)}">Gillar inte</button></div>`;
}
function wireFeedbackButtons(container, recipeId) {
  container.querySelector("[data-like-recipe]")?.addEventListener("click", () => {
    const fb = state.feedback[recipeId] || {};
    state.feedback[recipeId] = { ...fb, liked: !fb.liked, disliked: false };
    saveState();
    const holder = container.querySelector(".recipe-feedback");
    if (holder) holder.outerHTML = feedbackMarkup(recipeId);
    wireFeedbackButtons(container, recipeId);
  });
  container.querySelector("[data-dislike-recipe]")?.addEventListener("click", () => {
    const fb = state.feedback[recipeId] || {};
    state.feedback[recipeId] = { ...fb, disliked: !fb.disliked, liked: false };
    saveState();
    const holder = container.querySelector(".recipe-feedback");
    if (holder) holder.outerHTML = feedbackMarkup(recipeId);
    wireFeedbackButtons(container, recipeId);
  });
}

const DAYS_LONG = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"];
const DAYS = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
// One dinner per weekday is the real ceiling - derived from DAYS so the
// stepper, the onboarding stepper and the week view can never disagree
// about how many meals a week can hold (they previously all hardcoded 6).
const MAX_MEALS = DAYS.length;
// The single source of truth for "this week's recipes, in day order" - every
// render site reads this instead of re-deriving order from state.valda
// (a Set has no day-position semantics) or from RECEPT's own fixed array
// order (which is unrelated to when a recipe was picked).
function selectedRecipes() {
  const allRecipes = [...RECEPT, ...state.apiRecipes];
  return state.weekPlan.map(id => allRecipes.find(recipe => recipe.id === id)).filter(Boolean);
}
// Den senaste RIKTIGA veckototalen - aldrig ett uppskattat pris. Sätts i
// renderBasket och sparas med veckan när den byts ut, så budgethjälpen
// (§18) har verkliga tal att jämföra mot i stället för gissningar.
let lastRealWeekTotal = null;

function setWeekPlan(ids) {
  // Papperskorgen: den vecka som just ersätts läggs överst i historiken
  // (de tolv senaste behålls, synkas med kontot). "Skapa ny vecka" av
  // misstag ska aldrig kosta en kurerad vecka, och historiken är dessutom
  // det som gör att samma rätter inte kommer tillbaka direkt (§15).
  if (state.weekPlan?.length && state.weekPlan.join() !== [...ids].join()) {
    // Totalen sparas MED veckan så budgethjälpen har riktiga tal att
    // jämföra mot (§18). Bara en riktig, prissatt total - null när veckan
    // aldrig hann prissättas, så snittet aldrig bygger på en gissning.
    state.weekHistory = [{ plan: [...state.weekPlan], savedAt: Date.now(),
                           total: lastRealWeekTotal },
                         ...(state.weekHistory || [])].slice(0, 12);
  }
  state.weekPlan = [...ids]; state.valda = new Set(ids);
}

function restorePreviousWeek() {
  const previous = (state.weekHistory || [])[0];
  if (!previous) return;
  state.weekHistory = state.weekHistory.slice(1);
  state.weekPlan = [...previous.plan]; state.valda = new Set(previous.plan);
  state.avklarade.clear(); state.harHemma.clear(); state.removedItems.clear();
  clearPriceSnapshots();
  saveState(); render();
  showUndoToast("Förra veckan är tillbaka", () => {});
}
function addToWeekPlan(id) { if (!state.weekPlan.includes(id)) state.weekPlan.push(id); state.valda.add(id); }
function removeFromWeekPlan(id) { state.weekPlan = state.weekPlan.filter(existing => existing !== id); state.valda.delete(id); }
// Replaces exactly the recipe at this day's position - every other day's
// recipe keeps its own position untouched, which is the whole point of
// swapping "this day" rather than clearing and re-picking the week.
function swapWeekPlanDay(dayIndex, newId) { state.weekPlan = state.weekPlan.map((id, index) => index === dayIndex ? newId : id); state.valda = new Set(state.weekPlan); }
const savedState = readStoredState(localStorage);
const state = { budget: savedState.budget || 800, personer: Math.min(12, Math.max(1, Number(savedState.personer) || 2)), middagar: savedState.middagar || 4, butik: savedState.butik || "auto", postnummer: savedState.postnummer || "", position: null, sokning: "", kategori: "alla", maxTid: savedState.maxTid || 0, baraFavoriter: false, apiRecipes: savedState.apiRecipes || [], pantry: normalizePantry(savedState.pantry || {}), pantryTab: "skafferi", liveProdukter: [], favoriter: new Set(savedState.favoriter || []), valda: new Set(savedState.valda || []), avklarade: new Set(savedState.avklarade || []), removedItems: new Set(savedState.removedItems || []), expanded: null, authToken: getStoredToken(), user: null, naringsmal: savedState.naringsmal || null, livePriser: {}, liveBranchTotals: {}, liveUpdatedAt: null, receptTaggar: new Set(), minProtein: 0, maxKcal: 0, hyllor: [], dbChainTotals: {}, dbComparison: null, dbPricedAt: null, dbPricingFailedAt: null, dbLockedChains: [], extraItems: savedState.extraItems || [], extraMatches: {}, branches: [], betyg: savedState.betyg || {}, kost: { kosttyp: savedState.kost?.kosttyp || "", avoidAllergens: new Set(savedState.kost?.avoidAllergens || []) }, onboardingComplete: savedState.onboardingComplete || false, hushall: savedState.hushall || { vuxna: savedState.personer || 2, barn: 0 }, ogillar: new Set(savedState.ogillar || []), feedback: savedState.feedback || {}, savingsLog: savedState.savingsLog || [], swapsThisWeek: savedState.swapsThisWeek || 0, pinnedBranch: savedState.pinnedBranch || null, weekHistory: savedState.weekHistory || [], foljdaVaror: savedState.foljdaVaror || [], harHemma: new Set(savedState.harHemma || []), stapleItems: savedState.stapleItems || [], stapleAsked: savedState.stapleAsked || {}, household: emptyHouseholdState(), householdLoaded: false, notiser: [],
  // The week's recipe ids in day order (index 0 = Måndag) - the actual
  // source of truth for "which day has which recipe", now that a day swap
  // has to replace exactly one day's recipe in place. state.valda (a Set)
  // stays around alongside it purely as an O(1) "is this recipe anywhere in
  // my week" membership check for recipe-card UI - every place that needs
  // day order or a specific day's recipe reads weekPlan / selectedRecipes(),
  // never valda's own iteration order (a Set has none tied to day position).
  weekPlan: Array.isArray(savedState.weekPlan) ? savedState.weekPlan : [...(savedState.valda || [])] };
function buildSyncPayload() {
  return { budget: state.budget, personer: state.personer, middagar: state.middagar, butik: state.butik, postnummer: state.postnummer, maxTid: state.maxTid, pantry: state.pantry, favoriter: [...state.favoriter], valda: [...state.valda], avklarade: [...state.avklarade], removedItems: [...state.removedItems], apiRecipes: state.apiRecipes.filter(recipe => state.valda.has(recipe.id)), naringsmal: state.naringsmal, betyg: state.betyg, kost: { kosttyp: state.kost.kosttyp, avoidAllergens: [...state.kost.avoidAllergens] }, onboardingComplete: state.onboardingComplete, hushall: state.hushall, ogillar: [...state.ogillar], feedback: state.feedback, savingsLog: state.savingsLog, swapsThisWeek: state.swapsThisWeek, pinnedBranch: state.pinnedBranch, weekPlan: state.weekPlan, weekHistory: state.weekHistory, foljdaVaror: state.foljdaVaror, extraItems: state.extraItems, harHemma: [...state.harHemma], stapleItems: state.stapleItems, stapleAsked: state.stapleAsked,
    // The last real pricing snapshot. Painted immediately on next visit with
    // its own timestamp while a fresh fetch runs - the difference between
    // "pris hämtas…" for seconds on every open and prices that are simply
    // there. Never extended, never displayed without its "Uppdaterad" stamp.
    dbChainTotals: state.dbChainTotals, dbComparison: state.dbComparison, dbPricedAt: state.dbPricedAt };
}
function applySyncBlob(blob) {
  if (!blob) return;
  if (blob.budget !== undefined) state.budget = blob.budget;
  if (blob.personer !== undefined) state.personer = Math.min(12, Math.max(1, Number(blob.personer) || 2));
  if (blob.middagar !== undefined) state.middagar = blob.middagar;
  if (blob.butik !== undefined) state.butik = blob.butik;
  if (blob.postnummer !== undefined) state.postnummer = blob.postnummer;
  if (blob.maxTid !== undefined) state.maxTid = blob.maxTid;
  if (blob.pantry !== undefined) state.pantry = normalizePantry(blob.pantry);
  if (blob.favoriter !== undefined) state.favoriter = new Set(blob.favoriter);
  if (blob.valda !== undefined) state.valda = new Set(blob.valda);
  if (blob.avklarade !== undefined) state.avklarade = new Set(blob.avklarade);
  if (blob.removedItems !== undefined) state.removedItems = new Set(blob.removedItems);
  if (blob.apiRecipes !== undefined) state.apiRecipes = blob.apiRecipes;
  if (blob.extraItems !== undefined) state.extraItems = blob.extraItems;
  if (blob.weekHistory !== undefined) state.weekHistory = blob.weekHistory;
  if (blob.foljdaVaror !== undefined) state.foljdaVaror = blob.foljdaVaror;
  if (blob.harHemma !== undefined) state.harHemma = new Set(blob.harHemma);
  if (blob.stapleItems !== undefined) state.stapleItems = blob.stapleItems;
  if (blob.stapleAsked !== undefined) state.stapleAsked = blob.stapleAsked;
  if (blob.dbChainTotals) { state.dbChainTotals = blob.dbChainTotals; state.dbComparison = blob.dbComparison || null; state.dbPricedAt = blob.dbPricedAt || null; }
  if (blob.naringsmal !== undefined) state.naringsmal = blob.naringsmal;
  if (blob.betyg !== undefined) state.betyg = blob.betyg;
  if (blob.kost !== undefined) state.kost = { kosttyp: blob.kost.kosttyp || "", avoidAllergens: new Set(blob.kost.avoidAllergens || []) };
  if (blob.onboardingComplete !== undefined) state.onboardingComplete = blob.onboardingComplete;
  if (blob.hushall !== undefined) state.hushall = blob.hushall;
  if (blob.ogillar !== undefined) state.ogillar = new Set(blob.ogillar);
  if (blob.feedback !== undefined) state.feedback = blob.feedback;
  if (blob.savingsLog !== undefined) state.savingsLog = blob.savingsLog;
  if (blob.swapsThisWeek !== undefined) state.swapsThisWeek = blob.swapsThisWeek;
  if (blob.pinnedBranch !== undefined) state.pinnedBranch = blob.pinnedBranch;
  if (blob.weekPlan !== undefined) state.weekPlan = blob.weekPlan;
}
let serverSyncTimer = null;
// Sparat / synkar / kunde inte synka - sanningen om var datat är, visad
// diskret i kontovyn. Lokalt sparas ALLTID (localStorage, synkront);
// statusen gäller resan till kontot.
let syncStatus = "idle";
function setSyncStatus(status) {
  syncStatus = status;
  const label = $("syncStatusLabel");
  if (!label) return;
  label.textContent = status === "pending" ? "Synkar…"
    : status === "error" ? "Kunde inte synka - försöker igen"
    : state.authToken ? "Allt sparat på ditt konto" : "Sparat på den här enheten";
  label.classList.toggle("sync-error", status === "error");
}

function scheduleServerSync() {
  if (!state.authToken) { setSyncStatus("idle"); return; }
  clearTimeout(serverSyncTimer);
  setSyncStatus("pending");
  // Debounced: saveState() fires on nearly every interaction (pantry +/-, ratings,
  // swaps...) - pushing to the server on every single one would be wasteful and
  // could race with itself. One request ~1.5s after the last change is enough for
  // "follows you to another phone", which is the actual requirement here.
  serverSyncTimer = setTimeout(() => {
    serverSyncTimer = null;
    saveAccountState(state.authToken, buildSyncPayload())
      .then(() => setSyncStatus("idle"))
      .catch(() => { setSyncStatus("error"); /* nästa saveState-anrop försöker igen */ });
  }, 1500);
}
// Skicka en väntande synk NU. Lämnas sidan (Stripe Checkout, portalen,
// fliken stängs) inom 1,5 s efter sista ändringen försvann annars den
// väntande timern med sidan - och nästa öppning hämtade serverns ÄLDRE
// blob och skrev över veckan och onboardingflaggan som just gjorts.
// Sett i CI: efter checkout var Handla tom och onboarding "ogjord".
async function flushServerSync({ keepalive = false } = {}) {
  if (!serverSyncTimer || !state.authToken) return;
  clearTimeout(serverSyncTimer); serverSyncTimer = null;
  try {
    await saveAccountState(state.authToken, buildSyncPayload(), { keepalive });
    setSyncStatus("idle");
  } catch { setSyncStatus("error"); }
}
window.addEventListener("pagehide", () => { flushServerSync({ keepalive: true }); });
async function pullAccountState() {
  if (!state.authToken) return;
  try {
    const { state: remote } = await fetchAccountState(state.authToken);
    if (remote) {
      applySyncBlob(remote);
      writeStoredState(localStorage, buildSyncPayload());
      syncSettingsInputs(); render(); renderPantry(); restoreNutritionGoalsForm();
      // A returning account on a NEW device: the synced state already says
      // onboarding is done, but the modal decided to show itself before the
      // sync arrived - and then sat on top of a fully restored app.
      if (state.onboardingComplete) closeOnboarding();
    } else {
      // First time this account has ever synced - bootstrap the server with
      // whatever was already built up locally (e.g. as a guest before logging in).
      await saveAccountState(state.authToken, buildSyncPayload());
    }
  } catch { /* offline eller serverfel - den lokala datan används tills nästa försök */ }
}
function saveState() { writeStoredState(localStorage, buildSyncPayload()); scheduleServerSync(); }

// ---------------------------------------------------------------------------
// HUSHÅLLET
//
// En vara i Handla har fyra tillstånd (§6): behöver köpa, har hemma, köpt,
// borttagen. Modellen gäller ALLA - den som handlar ensam får samma fyra
// tillstånd som en familj. Hushållet ändrar bara VAR de bor: i serverns
// delade rader i stället för i den här enhetens localStorage.
//
// Adaptern nedan är den enda platsen som vet vilket av de två som gäller.
// Resten av appen frågar itemStatus()/setItemStatus() och bryr sig inte.
// ---------------------------------------------------------------------------

const householdActive = () => Boolean(state.household.id);
const itemKeyFor = (name, gtin) => gtin ? `gtin:${gtin}` : `name:${foldName(name)}`;
// INKÖPSLISTAN NYCKLAS PÅ NAMN, ALDRIG PÅ GTIN. Veckans rader läggs in av
// pushWeekToHousehold utan produktdata, så servern lagrar dem som
// `name:<varan>` - skrev klienten i stället på `gtin:...` (så fort ett pris
// matchats) hittade servern ingen rad, svarade 400, och den optimistiska
// raden blev en dubblett som aldrig gick att bocka av. Skafferiet är en
// annan bucket med egna rader och behåller sin gtin-nyckel.
const shoppingKeyFor = shoppingKey;

function householdRow(name) {
  return state.household.shopping[shoppingKeyFor(name)] || null;
}

function itemStatus(name) {
  if (householdActive()) return householdRow(name)?.status || NEED_TO_BUY;
  if (state.removedItems.has(name)) return REMOVED;
  if (state.avklarade.has(name)) return PURCHASED;
  if (state.harHemma.has(name)) return ALREADY_HAVE;
  return NEED_TO_BUY;
}

// Vad varan var innan senaste ändringen, så "Ångra" kan lämna tillbaka
// exakt det - inte en gissning om vad användaren troligen menade.
let lastShoppingUndo = null;

function setItemStatus(name, status, options = {}) {
  const previous = itemStatus(name);
  if (previous === status) return;
  if (householdActive()) {
    setHouseholdStatus(name, status, previous, options);
    return;
  }
  state.removedItems.delete(name);
  state.avklarade.delete(name);
  state.harHemma.delete(name);
  if (status === REMOVED) state.removedItems.add(name);
  if (status === PURCHASED) state.avklarade.add(name);
  if (status === ALREADY_HAVE) state.harHemma.add(name);
  let addedToPantry = false;
  // "Har hemma" ska BETYDA något (§5): varan lämnar behovet OCH hamnar i
  // skafferiet. Detsamma för "köpt" när användaren bett om det.
  if (status === ALREADY_HAVE || (status === PURCHASED && options.addToPantry)) {
    addedToPantry = addLocalPantryItem(name, options);
  }
  lastShoppingUndo = { name, status: previous, pantryAdded: addedToPantry, gtin: options.gtin };
  clearPriceSnapshots();
  saveState();
  render();
}

function addLocalPantryItem(name, options = {}) {
  const location = PANTRY_LOCATIONS.includes(options.location) ? options.location : "skafferi";
  if (state.pantry[name]?.amount > 0) {
    // Fanns redan hemma: rör inte mängden. Ångra ska inte kunna radera
    // familjens riktiga vara bara för att någon tryckte fel i Handla.
    state.pantry[name] = { ...state.pantry[name], location };
    return false;
  }
  state.pantry[name] = { amount: 1, location, expiry: null };
  return true;
}

async function setHouseholdStatus(name, status, previous, options = {}) {
  const key = options.key || shoppingKeyFor(name);
  // Optimistiskt: knappen svarar direkt, även i en affär med dålig täckning.
  // Raden som fanns före den optimistiska ändringen: utan den kan ett
  // avvisat svar aldrig städas bort, eftersom delta-synken bara lägger TILL
  // rader (en rad servern inte känner till kommer aldrig i svaret).
  const rowBefore = state.household.shopping[key];
  state.household = applyLocalRow(state.household, "shopping", { key, name, status });
  // Ångra-beskrivningen sätts INNAN svaret: remsan visas direkt, och ett
  // "Ångra" som hinner före servern får inte backa FÖRRA varan.
  lastShoppingUndo = { key, name, status: previous };
  render();
  try {
    const location = PANTRY_LOCATIONS.includes(options.location) ? options.location : "skafferi";
    let response;
    if (status === ALREADY_HAVE) response = await markAtHome(state.authToken, key, location);
    else if (status === PURCHASED) response = await markPurchased(state.authToken, key, { addToInventory: Boolean(options.addToPantry), location });
    else response = await setShoppingStatus(state.authToken, key, status);
    // Serverns beskrivning (med skafferinyckeln) - bara om ångra fortfarande
    // gäller den här varan.
    if (lastShoppingUndo?.key === key && response.undo) lastShoppingUndo = { ...response.undo, name };
    applyHouseholdResponse(response);
  } catch (error) {
    // Skrivningen gick inte fram - ta tillbaka den optimistiska raden och
    // hämta serverns sanning. Utan tillbakarullningen stod varan kvar i fel
    // tillstånd hela sessionen, medan partnern såg tvärtom.
    const shopping = { ...state.household.shopping };
    if (rowBefore) shopping[key] = rowBefore; else delete shopping[key];
    state.household = { ...state.household, shopping };
    if (lastShoppingUndo?.key === key) lastShoppingUndo = null;
    render();
    pullHousehold(true);
  }
}

function applyHouseholdResponse(response) {
  if (!response) return;
  const rows = { revision: response.revision, shopping: [], inventory: [] };
  if (response.item) rows.shopping.push(response.item);
  if (response.inventory && response.inventory.key) rows.inventory.push(response.inventory);
  if (Array.isArray(response.items)) rows.shopping.push(...response.items);
  state.household = applySync(state.household, rows);
  render();
}

function undoLastShoppingAction() {
  const undo = lastShoppingUndo;
  lastShoppingUndo = null;
  if (!undo) return;
  if (householdActive()) {
    state.household = applyLocalRow(state.household, "shopping", { key: undo.key, status: undo.status });
    render();
    undoShoppingAction(state.authToken, undo).then(applyHouseholdResponse).catch(() => pullHousehold(true));
    return;
  }
  state.removedItems.delete(undo.name);
  state.avklarade.delete(undo.name);
  state.harHemma.delete(undo.name);
  if (undo.status === REMOVED) state.removedItems.add(undo.name);
  if (undo.status === PURCHASED) state.avklarade.add(undo.name);
  if (undo.status === ALREADY_HAVE) state.harHemma.add(undo.name);
  // Bara en rad som HANDLINGEN skapade tas bort igen.
  if (undo.pantryAdded) delete state.pantry[undo.name];
  clearPriceSnapshots();
  saveState();
  render();
}

// ---- skafferiet: hushållets rader eller enhetens egna ---------------------

// Skafferiet som EN lista, oavsett var det bor. Vyerna nedan läser bara
// härifrån, så de ser likadana ut i båda lägena.
function pantryList(location = null) {
  if (householdActive()) {
    return inventoryRows(state.household, location).map(item => ({
      key: item.key, name: item.name, amount: item.amount, unit: item.unit || "st",
      location: item.location, expiry: item.expiry, product: item.product || null,
      category: item.category || categoryFor(item.name, item.product?.category),
    }));
  }
  return Object.entries(state.pantry)
    .filter(([, entry]) => entry.amount > 0 && (!location || entry.location === location))
    .map(([name, entry]) => ({
      key: itemKeyFor(name), name, amount: entry.amount,
      unit: PACKAGE_INFO[name]?.unit || "st", location: entry.location, expiry: entry.expiry,
      product: null, category: categoryFor(name),
    }));
}

// Vad prismotorn får veta om vad som finns hemma. Konservativt (§10):
// bara mängder vi faktiskt vet.
function pantryForPricing() {
  return householdActive() ? pantryAmountsFor(state.household) : pantryAmounts(state.pantry);
}

function pantryNamesForCooking() {
  return householdActive() ? inventoryNames(state.household) : Object.keys(state.pantry);
}

function addPantryItem(fields) {
  const location = PANTRY_LOCATIONS.includes(fields.location) ? fields.location : "skafferi";
  if (householdActive()) {
    const key = itemKeyFor(fields.name, fields.gtin);
    state.household = applyLocalRow(state.household, "inventory", {
      key, name: fields.name, amount: fields.amount || 1, unit: fields.unit || "st",
      location, product: fields.product || null, deleted: false,
    });
    render();
    upsertInventoryItem(state.authToken, { ...fields, location, key })
      .then(applyHouseholdInventory).catch(() => pullHousehold(true));
    return;
  }
  state.pantry[fields.name] = {
    amount: Math.max(0, Number(fields.amount) || 1), location,
    expiry: fields.expiry || null,
  };
  saveState();
  render();
}

function applyHouseholdInventory(response) {
  if (!response || !response.item) return;
  state.household = applySync(state.household, { revision: response.revision, inventory: [response.item] });
  render();
}

function stepPantryItem(entry, delta) {
  if (householdActive()) {
    const amount = Math.max(0, (Number(entry.amount) || 0) + delta);
    state.household = applyLocalRow(state.household, "inventory", { key: entry.key, amount, deleted: amount <= 0 });
    render();
    adjustInventory(state.authToken, entry.key, delta).then(applyHouseholdInventory).catch(() => pullHousehold(true));
    return;
  }
  const next = (state.pantry[entry.name]?.amount || 0) + delta;
  if (next <= 0) delete state.pantry[entry.name];
  else state.pantry[entry.name].amount = next;
  saveState();
  render();
}

function removePantryItem(entry) {
  if (householdActive()) {
    state.household = applyLocalRow(state.household, "inventory", { key: entry.key, deleted: true });
    render();
    removeInventoryItem(state.authToken, entry.key).then(applyHouseholdInventory).catch(() => pullHousehold(true));
    return;
  }
  delete state.pantry[entry.name];
  saveState();
  render();
}

// ---- synk ----------------------------------------------------------------
//
// Enklaste robusta lösningen (§25): hämta det som ändrats sedan förra
// revisionen. Ingen WebSocket, ingen ny infrastruktur - en GET som nästan
// alltid svarar tomt. Den går när appen är synlig, efter varje egen
// ändring, och när telefonen kommer tillbaka från bakgrunden.
const HOUSEHOLD_POLL_MS = 20000;
let householdPollTimer = null;
let householdPullInFlight = false;

async function pullHousehold(force = false) {
  if (!state.authToken || !householdActive()) return;
  if (householdPullInFlight && !force) return;
  householdPullInFlight = true;
  try {
    const payload = await syncHousehold(state.authToken, state.household.revision);
    const before = state.household.revision;
    state.household = applySync(state.household, payload);
    if (state.household.revision !== before) render();
  } catch (error) {
    // 404 = kontot är inte längre med i hushållet (utkastad, eller lämnade
    // från en annan enhet). Appen faller tillbaka till enhetens egen data
    // i stället för att visa en familj som inte längre finns.
    if (error.status === 404) { state.household = emptyHouseholdState(); renderAccount(); render(); }
    // 401 = sessionen är död (utloggad från annan enhet, utgången). Samma
    // hantering som refreshUser - annars pollar appen var 20:e sekund med
    // en död token och visar familjens data vidare.
    if (error.status === 401) {
      state.authToken = null; storeToken(null); state.user = null;
      clearHouseholdSession(); renderAccount(); render();
    }
  } finally {
    householdPullInFlight = false;
  }
}

function startHouseholdSync() {
  clearInterval(householdPollTimer);
  if (!householdActive()) return;
  householdPollTimer = setInterval(() => {
    if (document.visibilityState === "visible") pullHousehold();
  }, HOUSEHOLD_POLL_MS);
}

async function loadHousehold() {
  if (!state.authToken) { state.household = emptyHouseholdState(); startHouseholdSync(); return; }
  try {
    const { household } = await fetchHousehold(state.authToken);
    if (household) {
      state.household = applySync(emptyHouseholdState(), { household, revision: 0 });
      await pullHousehold(true);
      pushWeekToHousehold({ onlyIfEmpty: true });
    } else {
      state.household = emptyHouseholdState();
    }
  } catch { /* offline - appen fungerar lokalt tills nästa försök */ }
  state.householdLoaded = true;
  startHouseholdSync();
  renderAccount();
  render();
}

// Veckans behov ut till hushållets lista.
//
// Skickar BARA veckans rader; det familjen själv bestämt om en vara ("har
// hemma", "köpt", manuellt tillagd) rörs inte av servern. Utan debouncen
// hade varje receptbyte skickat hela listan på nytt.
let weekPushTimer = null;
let lastWeekPushKey = null;
function pushWeekToHousehold({ onlyIfEmpty = false } = {}) {
  if (!householdActive()) return;
  const items = aggregateShopping(selectedRecipes()).map(item => ({
    name: item.namn, amount: item.total, unit: item.unit,
    category: categoryFor(item.namn, databaseItemFor(item.namn)?.category),
  }));
  // TOMT ÄR INTE ETT VECKOFÖRSLAG. Servern speglar listan och tar bort de
  // veckorader som inte kommer med - den i familjen som öppnar appen utan
  // egen plan hade annars raderat den andres lista mitt i affären.
  if (!items.length) return;
  // Vid inloggning/hushållsladdning ska den egna (kanske gamla) veckan inte
  // skriva över en lista familjen redan har. Då seedar vi bara ett tomt hushåll.
  if (onlyIfEmpty && shoppingRows(state.household).some(row => row.source === "week")) return;
  const key = JSON.stringify(items);
  if (key === lastWeekPushKey) return;
  clearTimeout(weekPushTimer);
  weekPushTimer = setTimeout(() => {
    lastWeekPushKey = key;
    replaceWeekItems(state.authToken, items)
      .then(payload => { state.household = applySync(state.household, payload); render(); })
      .catch(() => { lastWeekPushKey = null; });
  }, 900);
}

// Shown only when no real branch list could be fetched. The name says what
// the price actually is: Willys prices are verified national, so the total
// is real - it is the BRANCH that is unknown, not the price.
const FALLBACK_BRANCH = [{ kedja: "Willys", namn: "Willys (riksgemensamt pris)", lat: null, lon: null, avstandKm: 0, prisfaktor: 1 }];
const PRODUCT_CATALOG = {
  "Grädde": { namn: "Mat grädde 15%", marke: "Arla", storlek: "2 dl", pris: 15.95 },
  "Majs": { namn: "Majs", marke: "ICA", storlek: "340 g", pris: 12.95 },
  "Pasta": { namn: "Spaghetti", marke: "Kungsörnen", storlek: "500 g", pris: 16.95 },
  "Purjolök": { namn: "Purjolök", marke: "ICA", storlek: "1 st", pris: 18.95 },
  "Ris": { namn: "Jasminris", marke: "ICA", storlek: "1 kg", pris: 29.95 },
  "Riven ost": { namn: "Riven hushållsost", marke: "ICA", storlek: "150 g", pris: 24.95 },
  "Salsa": { namn: "Chunky Salsa Medium", marke: "Santa Maria", storlek: "230 g", pris: 22.95 },
  "Svarta bönor": { namn: "Svarta bönor", marke: "ICA", storlek: "380 g", pris: 13.95 },
  "Curry & grönsaker": { namn: "Curry & grönsaker", marke: "Santa Maria", storlek: "28 g", pris: 14.95 },
  "Kokosmjölk": { namn: "Kokosmjölk", marke: "ICA", storlek: "400 ml", pris: 16.95 },
  "Kycklinglårfilé": { namn: "Kycklinglårfilé", marke: "ICA", storlek: "ca 600 g", pris: 69.95 },
  "Lök & vitlök": { namn: "Gul lök & vitlök", marke: "ICA", storlek: "500 g", pris: 19.95 },
  "Morötter": { namn: "Morötter", marke: "ICA", storlek: "1 kg", pris: 14.95 },
  "Röda linser": { namn: "Röda linser", marke: "ICA", storlek: "400 g", pris: 19.95 },
  "Falukorv": { namn: "Falukorv", marke: "Scan", storlek: "800 g", pris: 39.95 },
  "Tomatpuré": { namn: "Tomatpuré", marke: "Mutti", storlek: "140 g", pris: 14.95 },
  "Fryst torsk": { namn: "Fryst torskfilé", marke: "Findus", storlek: "450 g", pris: 59.95 },
  "Citron": { namn: "Citron", marke: "ICA", storlek: "1 st", pris: 6.95 },
  "Laxfilé": { namn: "Laxfilé", marke: "ICA", storlek: "ca 600 g", pris: 89.95 },
  "Dill": { namn: "Dill", marke: "ICA", storlek: "1 knippe", pris: 12.95 },
  "Kidneybönor": { namn: "Kidneybönor", marke: "ICA", storlek: "400 g", pris: 13.95 },
  "Paprika": { namn: "Paprika", marke: "ICA", storlek: "1 st", pris: 9.95 },
  "Halloumi": { namn: "Halloumi", marke: "Arla", storlek: "225 g", pris: 44.95 },
  "Matvete": { namn: "Matvete", marke: "Kungsörnen", storlek: "500 g", pris: 24.95 },
  "Yoghurt": { namn: "Turkisk yoghurt", marke: "Arla", storlek: "500 g", pris: 24.95 },
  "Kycklingfilé": { namn: "Kycklingfilé", marke: "ICA", storlek: "ca 500 g", pris: 79.95 },
  "Äggnudlar": { namn: "Äggnudlar", marke: "Santa Maria", storlek: "250 g", pris: 19.95 },
  "Wokgrönsaker": { namn: "Wokgrönsaker", marke: "Findus", storlek: "400 g", pris: 29.95 },
  "Soja": { namn: "Sojasås", marke: "Kikkoman", storlek: "150 ml", pris: 29.95 },
  "Lök": { namn: "Gul lök", marke: "ICA", storlek: "1 st", pris: 3.95 },
  "Basilika": { namn: "Basilika", marke: "ICA", storlek: "1 kruka", pris: 24.95 },
  "Ägg": { namn: "Ägg", marke: "ICA", storlek: "6-pack", pris: 34.95 },
  "Bär": { namn: "Frysta bär", marke: "ICA", storlek: "300 g", pris: 29.95 },
  "Mjölk": { namn: "Mjölk", marke: "Arla", storlek: "1 l", pris: 12.95 },
  "Krossade tomater": { namn: "Krossade tomater", marke: "ICA", storlek: "400 g", pris: 11.95 },
  "Vetemjöl": { namn: "Vetemjöl", marke: "Kungsörnen", storlek: "2 kg", pris: 24.95 },
  "Crème fraiche": { namn: "Crème fraiche", marke: "Arla", storlek: "2 dl", pris: 15.95 },
  "Potatis": { namn: "Potatis", marke: "ICA", storlek: "2 kg", pris: 24.95 },
  "Köttfärs": { namn: "Blandfärs", marke: "ICA", storlek: "500 g", pris: 59.95 },
  "Lingonsylt": { namn: "Lingonsylt", marke: "Felix", storlek: "400 g", pris: 24.95 },
  "Lasagneplattor": { namn: "Lasagneplattor", marke: "Kungsörnen", storlek: "400 g", pris: 22.95 },
  "Zucchini": { namn: "Zucchini", marke: "ICA", storlek: "1 st", pris: 12.95 },
  "Räkor": { namn: "Skalade räkor", marke: "Findus", storlek: "300 g", pris: 49.95 },
  "Vitlök": { namn: "Vitlök", marke: "ICA", storlek: "1 st", pris: 9.95 },
  "Kikärtor": { namn: "Kikärtor", marke: "ICA", storlek: "380 g", pris: 13.95 },
  "Fläskfilé": { namn: "Fläskfilé", marke: "ICA", storlek: "ca 600 g", pris: 79.95 },
  "Timjan": { namn: "Färsk timjan", marke: "ICA", storlek: "1 knippe", pris: 12.95 },
  "Biff": { namn: "Nöt ryggbiff", marke: "ICA", storlek: "ca 600 g", pris: 119.95 },
  "Vegofärs": { namn: "Vegofärs", marke: "Anamma", storlek: "400 g", pris: 39.95 },
  "Tofu": { namn: "Naturell tofu", marke: "Anamma", storlek: "300 g", pris: 29.95 },
  "Sparris": { namn: "Grön sparris", marke: "ICA", storlek: "250 g", pris: 34.95 },
  "Äppelmos": { namn: "Äppelmos", marke: "ICA", storlek: "350 g", pris: 19.95 },
  "Rödkål": { namn: "Rödkål", marke: "ICA", storlek: "ca 800 g", pris: 16.95 },
  "Feta": { namn: "Fetaost", marke: "Apetina", storlek: "200 g", pris: 34.95 },
  "Kalvschnitzel": { namn: "Kalvschnitzel", marke: "ICA", storlek: "500 g", pris: 99.95 },
  "Kapris": { namn: "Kapris", marke: "Santa Maria", storlek: "100 g", pris: 24.95 }
};
const PACKAGE_INFO = {
  Pasta: { amount: 500, unit: "g" }, Ris: { amount: 1000, unit: "g" }, Grädde: { amount: 200, unit: "ml" },
  "Riven ost": { amount: 150, unit: "g" }, Majs: { amount: 340, unit: "g" }, "Svarta bönor": { amount: 380, unit: "g" },
  "Röda linser": { amount: 400, unit: "g" }, Kokosmjölk: { amount: 400, unit: "ml" }, "Krossade tomater": { amount: 400, unit: "g" },
  Falukorv: { amount: 800, unit: "g" }, "Tomatpuré": { amount: 140, unit: "g" }, "Fryst torsk": { amount: 450, unit: "g" },
  Citron: { amount: 1, unit: "st" }, "Laxfilé": { amount: 600, unit: "g" }, Dill: { amount: 1, unit: "st" },
  "Kidneybönor": { amount: 400, unit: "g" }, Paprika: { amount: 1, unit: "st" }, Halloumi: { amount: 225, unit: "g" },
  Matvete: { amount: 500, unit: "g" }, Yoghurt: { amount: 500, unit: "g" }, "Kycklingfilé": { amount: 500, unit: "g" },
  "Äggnudlar": { amount: 250, unit: "g" }, Wokgrönsaker: { amount: 400, unit: "g" }, Soja: { amount: 150, unit: "ml" },
  Lök: { amount: 1, unit: "st" }, Basilika: { amount: 1, unit: "st" }, Ägg: { amount: 6, unit: "st" }, Bär: { amount: 300, unit: "g" },
  Mjölk: { amount: 1000, unit: "ml" }, Vetemjöl: { amount: 2000, unit: "g" }, "Kycklinglårfilé": { amount: 600, unit: "g" },
  "Curry & grönsaker": { amount: 28, unit: "g" }, Salsa: { amount: 230, unit: "g" }, "Lök & vitlök": { amount: 500, unit: "g" },
  Morötter: { amount: 1000, unit: "g" }, "Crème fraiche": { amount: 200, unit: "g" }, Potatis: { amount: 2000, unit: "g" },
  "Köttfärs": { amount: 500, unit: "g" }, Lingonsylt: { amount: 400, unit: "g" }, Lasagneplattor: { amount: 400, unit: "g" },
  Zucchini: { amount: 1, unit: "st" }, "Räkor": { amount: 300, unit: "g" }, Vitlök: { amount: 1, unit: "st" }, Kikärtor: { amount: 380, unit: "g" },
  "Fläskfilé": { amount: 600, unit: "g" }, Timjan: { amount: 1, unit: "st" }, Biff: { amount: 600, unit: "g" }, "Vegofärs": { amount: 400, unit: "g" },
  Tofu: { amount: 300, unit: "g" }, Sparris: { amount: 250, unit: "g" }, "Äppelmos": { amount: 350, unit: "g" }, Rödkål: { amount: 800, unit: "g" },
  Feta: { amount: 200, unit: "g" }, Kalvschnitzel: { amount: 500, unit: "g" }, Kapris: { amount: 100, unit: "g" }
};
const RECIPE_QUANTITIES = {
  pastagratang: { Pasta: [250, "g"], "Purjolök": [0.5, "st"], Grädde: [200, "ml"], "Riven ost": [100, "g"] },
  fiskpasta: { "Fryst torsk": [450, "g"], Pasta: [250, "g"], "Crème fraiche": [200, "g"], Citron: [1, "st"] },
  kycklinggryta: { "Kycklinglårfilé": [600, "g"], Ris: [250, "g"], Kokosmjölk: [400, "ml"], "Curry & grönsaker": [28, "g"] },
  linssoppa: { "Röda linser": [250, "g"], Kokosmjölk: [400, "ml"], Morötter: [300, "g"], "Lök & vitlök": [150, "g"] },
  korvstroganoff: { Falukorv: [400, "g"], Grädde: [200, "ml"], "Tomatpuré": [70, "g"], Ris: [250, "g"] },
  tacobonor: { "Svarta bönor": [380, "g"], Ris: [250, "g"], Majs: [150, "g"], Salsa: [230, "g"] },
  "ugnslax-citron": { "Laxfilé": [600, "g"], Potatis: [800, "g"], Citron: [1, "st"], Dill: [1, "st"] },
  halloumibowl: { Halloumi: [225, "g"], Matvete: [250, "g"], Paprika: [1, "st"], Yoghurt: [200, "g"] },
  "chili-sin-carne-budget": { "Kidneybönor": [400, "g"], "Krossade tomater": [400, "g"], Majs: [150, "g"], Paprika: [2, "st"] },
  "kycklingwok-nudlar-protein": { "Kycklingfilé": [500, "g"], "Äggnudlar": [250, "g"], Wokgrönsaker: [400, "g"], Soja: [30, "ml"] },
  tomatsoppa: { "Krossade tomater": [400, "g"], Grädde: [200, "ml"], Lök: [2, "st"], Basilika: [1, "st"] },
  pannkakor: { "Vetemjöl": [250, "g"], Mjölk: [600, "ml"], Ägg: [4, "st"], Bär: [300, "g"] },
  "kottbullar-potatismos": { "Köttfärs": [500, "g"], Potatis: [800, "g"], Grädde: [200, "ml"], Lingonsylt: [100, "g"] },
  vegetarisklasagne: { Lasagneplattor: [300, "g"], "Krossade tomater": [400, "g"], "Riven ost": [150, "g"], Zucchini: [2, "st"] },
  scampi: { "Räkor": [300, "g"], Pasta: [250, "g"], Vitlök: [1, "st"], Citron: [1, "st"] },
  kikartscurry: { Kikärtor: [380, "g"], Kokosmjölk: [400, "ml"], Ris: [250, "g"], "Curry & grönsaker": [28, "g"] },
  flaskfilerotmos: { "Fläskfilé": [600, "g"], Morötter: [400, "g"], Potatis: [600, "g"], Timjan: [1, "st"] },
  biffmedlok: { Biff: [600, "g"], Potatis: [800, "g"], Lök: [2, "st"], Grädde: [200, "ml"] },
  vegobolognese: { "Vegofärs": [400, "g"], Pasta: [250, "g"], "Krossade tomater": [400, "g"], Lök: [1, "st"] },
  kycklingcouscous: { Kycklingfilé: [500, "g"], Matvete: [250, "g"], Paprika: [2, "st"], Citron: [1, "st"] },
  rotfruktsgratang: { Falukorv: [400, "g"], Potatis: [800, "g"], Morötter: [400, "g"], "Riven ost": [100, "g"] },
  butterchicken: { Kycklingfilé: [500, "g"], "Krossade tomater": [400, "g"], Grädde: [200, "ml"], "Curry & grönsaker": [28, "g"] },
  "fiskgratang-dill": { "Fryst torsk": [500, "g"], Räkor: [200, "g"], Dill: [1, "st"], Grädde: [200, "g"] },
  tofuwok: { Tofu: [400, "g"], Wokgrönsaker: [400, "g"], Soja: [30, "ml"], Ris: [250, "g"] },
  ugnstorsk: { "Fryst torsk": [600, "g"], Citron: [1, "st"], Sparris: [300, "g"], Potatis: [600, "g"] },
  flaskkarre: { "Fläskfilé": [600, "g"], "Äppelmos": [200, "g"], Rödkål: [300, "g"], Potatis: [600, "g"] },
  fetapasta: { Pasta: [300, "g"], "Krossade tomater": [400, "g"], Vitlök: [1, "st"], Feta: [200, "g"] },
  kalvschnitzel: { Kalvschnitzel: [600, "g"], Potatis: [600, "g"], Citron: [1, "st"], Kapris: [30, "g"] },
  kycklingmatvete: { "Kycklinglårfilé": [500, "g"], Matvete: [250, "g"], Paprika: [2, "st"], Yoghurt: [200, "g"] },
  citronkyckling: { "Kycklinglårfilé": [600, "g"], Potatis: [800, "g"], Timjan: [1, "st"], Citron: [1, "st"] },
  biffmatvetesallad: { Biff: [500, "g"], Matvete: [250, "g"], Paprika: [1, "st"], Vitlök: [1, "st"] },
  biffwok: { Biff: [500, "g"], Ris: [250, "g"], Wokgrönsaker: [400, "g"], Soja: [30, "ml"] },
  flaskcurrygryta: { "Fläskfilé": [500, "g"], Ris: [250, "g"], "Curry & grönsaker": [28, "g"], Kokosmjölk: [400, "ml"] },
  flasktomatpasta: { "Fläskfilé": [500, "g"], Pasta: [250, "g"], "Krossade tomater": [400, "g"], Basilika: [1, "st"] },
  kalvschnitzelmatvete: { Kalvschnitzel: [500, "g"], Matvete: [250, "g"], Paprika: [1, "st"], Citron: [1, "st"] },
  teriyakilax: { "Laxfilé": [500, "g"], Ris: [250, "g"], Wokgrönsaker: [400, "g"], Soja: [30, "ml"] },
  laxsallad: { "Laxfilé": [500, "g"], Matvete: [250, "g"], Citron: [1, "st"], Dill: [1, "st"] },
  torskitomatsas: { "Fryst torsk": [500, "g"], Potatis: [600, "g"], "Krossade tomater": [400, "g"], Vitlök: [1, "st"] },
  rakcurry: { "Räkor": [300, "g"], Ris: [250, "g"], "Curry & grönsaker": [28, "g"], Kokosmjölk: [400, "ml"] },
  raksallad: { "Räkor": [300, "g"], Matvete: [250, "g"], Citron: [1, "st"], Dill: [1, "st"] },
  kikartssallad: { Kikärtor: [380, "g"], Matvete: [250, "g"], Paprika: [1, "st"], Citron: [1, "st"] },
  bonbowlmatvete: { "Kidneybönor": [400, "g"], Matvete: [250, "g"], Paprika: [1, "st"], Salsa: [230, "g"] },
  svartbonsbowl: { "Svarta bönor": [380, "g"], Matvete: [250, "g"], Salsa: [230, "g"], Majs: [150, "g"] },
  tofucurry: { Tofu: [400, "g"], Ris: [250, "g"], "Curry & grönsaker": [28, "g"], Kokosmjölk: [400, "ml"] },
  teriyakitofu: { Tofu: [400, "g"], Matvete: [250, "g"], Paprika: [1, "st"], Soja: [30, "ml"] },
  halloumipasta: { Halloumi: [225, "g"], Pasta: [250, "g"], "Krossade tomater": [400, "g"], Basilika: [1, "st"] },
  halloumicurry: { Halloumi: [225, "g"], Ris: [250, "g"], Paprika: [1, "st"], "Curry & grönsaker": [28, "g"] },
  fetagryta: { Feta: [200, "g"], "Krossade tomater": [400, "g"], Kikärtor: [380, "g"], Basilika: [1, "st"] },
  vegofarsgryta: { "Vegofärs": [400, "g"], Ris: [250, "g"], "Krossade tomater": [400, "g"], Paprika: [1, "st"] },
  korvgratang: { Falukorv: [400, "g"], Pasta: [250, "g"], "Krossade tomater": [400, "g"], "Riven ost": [100, "g"] },
  kottfarssas: { "Köttfärs": [500, "g"], Pasta: [250, "g"], "Krossade tomater": [400, "g"], Basilika: [1, "st"] },
  currykottfarsgryta: { "Köttfärs": [500, "g"], Ris: [250, "g"], Paprika: [1, "st"], "Curry & grönsaker": [28, "g"] },
  tandoorikyckling: { Kycklingfilé: [500, "g"], Ris: [250, "g"], "Curry & grönsaker": [28, "g"], Yoghurt: [200, "g"] },
  citronflaskfile: { "Fläskfilé": [500, "g"], Matvete: [250, "g"], Citron: [1, "st"], Timjan: [1, "st"] },
  biffgraddtimjan: { Biff: [500, "g"], Potatis: [800, "g"], Grädde: [200, "ml"], Timjan: [1, "st"] },
  zucchinipastafeta: { Zucchini: [2, "st"], Pasta: [250, "g"], "Krossade tomater": [400, "g"], Feta: [200, "g"] },
  sparrispastacitron: { Sparris: [300, "g"], Pasta: [250, "g"], Citron: [1, "st"], Vitlök: [1, "st"] },
  morotscurry: { Morötter: [400, "g"], Kikärtor: [380, "g"], "Curry & grönsaker": [28, "g"], Ris: [250, "g"] }
};
function mapApiRecipe(recipe) {
  // Rå text i state - escapas vid rendering som allt annat. Escape vid
  // intag gav dubbelescapade namn i Vecka/Hem och skickade "&amp;" som
  // varunamn till prismotorn.
  const ingredients = (recipe.ingredients || []).map(item => `${item.measure || ""} ${item.name || ""}`.trim()).filter(Boolean);
  return { id: recipe.id, provider: recipe.provider, providerRecipeId: recipe.providerRecipeId, namn: String(recipe.title || ""), butik: "alla", tid: Number(recipe.prepMinutes) || 0, typ: "Provider-recept", portionspris: null, inkopspris: null, sparar: 0, ingredienser: ingredients, hemma: [], beskrivning: "Recept från extern receptkälla. Pris beräknas först när ingredienserna har matchats mot svenska butikprodukter.", steg: (recipe.instructions || []).map(escapeHtml), bild: safeHttpUrl(recipe.imageUrl), imageSource: recipe.imageSource, sourceUrl: safeHttpUrl(recipe.sourceUrl), servings: recipe.servings, priceStatus: "unavailable" };
}

// The recipe bank's OWN text always wins - description and steps written
// for the recipe beat the legacy hand-typed map, which only still exists as
// a fallback for pre-bank local recipes.
function detailsFor(recipe) {
  const legacy = RECIPE_DETAILS[recipe.id] || {};
  return {
    beskrivning: recipe.beskrivning || recipe.description || legacy.beskrivning,
    steg: (Array.isArray(recipe.steg) && recipe.steg.length ? recipe.steg : legacy.steg) || [],
    tips: legacy.tips,
  };
}

const RECIPE_DETAILS = {
  kycklinggryta: { beskrivning: "Krämig kycklinggryta med kokos, curry och söta grönsaker.", steg: ["Bryn kycklingen i en het panna.", "Fräs curry och grönsaker tills de mjuknar.", "Häll i kokosmjölken och låt sjuda tills kycklingen är genomstekt."], tips: "Servera med lime och färsk koriander om du har hemma." },
  pastagratang: { beskrivning: "Krämig pastagratäng med purjolök och ett gyllene osttäcke.", steg: ["Koka pastan två minuter kortare än anvisningen.", "Fräs purjolök och rör ner grädde.", "Blanda med pastan, toppa med ost och gratinera tills ytan fått färg."], tips: "Spara lite pastavatten för en extra krämig sås." },
  linssoppa: { beskrivning: "Värmande och mättande linssoppa med kokosmjölk och rotfrukter.", steg: ["Fräs lök, vitlök och morot i olja.", "Tillsätt linser, buljong och kokosmjölk.", "Låt sjuda tills linserna är mjuka och smaka av."], tips: "Toppa med yoghurt eller citron för friskare smak." },
  korvstroganoff: { beskrivning: "En svensk vardagsklassiker med tomat, grädde och mild paprika.", steg: ["Skär korven och bryn den lätt.", "Fräs tomatpuré och paprika innan du tillsätter grädde.", "Låt såsen sjuda några minuter och servera med ris."], tips: "En skvätt soja ger såsen mer djup." },
  tacobonor: { beskrivning: "Fräsch tacobowl med svarta bönor, majs, ris och salsa.", steg: ["Koka riset och värm bönorna med kryddor.", "Skär grönsakerna och blanda majsen med salsan.", "Bygg skålar med ris, bönor, grönsaker och salsa."], tips: "Pressa över lime precis före servering." },
  fiskpasta: { beskrivning: "Len fiskpasta med citron, crème fraiche och dill.", steg: ["Koka pastan och spara lite pastavatten.", "Tillaga fisken försiktigt i en krämig citronsås.", "Vänd ner pastan och späd med pastavatten till rätt konsistens."], tips: "Koka inte fisken för hårt, då blir den saftigare." },
  "ugnslax-citron": { beskrivning: "Ugnsbakad lax med citron, dill och rostad potatis.", steg: ["Sätt ugnen på 200°C.", "Lägg lax och potatis i en form.", "Toppa med citron och dill och baka tills laxen är klar."], tips: "Laxen är klar när den precis börjar dela sig i lameller." },
  halloumibowl: { beskrivning: "Krispig halloumi med rostade grönsaker och krämig yoghurt.", steg: ["Koka matvetet enligt förpackningen.", "Rosta grönsakerna i ugnen.", "Stek halloumin och servera med yoghurt."], tips: "Stek halloumin sist så håller den sig varm och krispig." },
  "chili-sin-carne-budget": { beskrivning: "Mustig chili sin carne med bönor, tomat och paprika.", steg: ["Fräs paprika och lök.", "Tillsätt tomater, bönor och majs.", "Låt sjuda i 20 minuter och servera med ris."], tips: "Låt chilin vila tio minuter före servering för djupare smak." },
  "kycklingwok-nudlar-protein": { beskrivning: "Snabb wok med kyckling, nudlar och krispiga grönsaker.", steg: ["Koka nudlarna.", "Stek kycklingen tills den är genomstekt.", "Woka grönsakerna och blanda allt med soja."], tips: "Ha alla ingredienser framme innan du börjar woka." },
  tomatsoppa: { beskrivning: "Len tomatsoppa med basilika och en skvätt grädde.", steg: ["Fräs löken mjuk.", "Koka med tomater och buljong.", "Mixa soppan och rör ner grädden."], tips: "En liten nypa socker balanserar syrliga tomater." },
  pannkakor: { beskrivning: "Klassiska tunna pannkakor med sötsyrliga bär.", steg: ["Vispa ihop smetens ingredienser.", "Stek tunna pannkakor i smör.", "Servera med bär."], tips: "Låt smeten vila en stund så blir pannkakorna jämnare." }
};
const $ = id => document.getElementById(id);
const money = value => `${Math.round(value).toLocaleString("sv-SE")} kr`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const scaledPurchasePrice = (recipe, branch = selectedBranch()) => recipe.inkopspris * portionFactor(state.personer) * (branch?.prisfaktor || 1);
function shoppingListCost(selected, branch) {
  const factor = branch?.prisfaktor || 1;
  return calculateShoppingTotal(aggregateShopping(selected), PRODUCT_CATALOG, pantryForPricing(), factor);
}
function combinations(list, size) {
  if (size === 0) return [[]];
  if (list.length < size) return [];
  const [first, ...rest] = list;
  return [...combinations(rest, size - 1).map(combo => [first, ...combo]), ...combinations(rest, size)];
}
const comboRating = combo => combo.reduce((sum, recipe) => sum + (state.betyg[recipe.id] || 0), 0);
function recipeAffinity(recipe) {
  const fb = state.feedback[recipe.id];
  if (!fb) return 0;
  return (fb.liked ? 3 : 0) + Math.min(fb.cooked || 0, 3) * 1.5 - Math.min(fb.skipped || 0, 3);
}
// Vilken sorts rätt ett recept ÄR, för variationsräkningen. Grov och
// medveten indelning: korv, pasta, soppa, gratäng, gröt/pannkaka - resten
// faller tillbaka på proteinkällan. Grovheten är poängen: två korvrätter är
// "samma sorts middag" för en familj oavsett om den ena är gryta.
function dishFamily(recipe) {
  const name = (recipe.namn || "").toLowerCase();
  const cats = (recipe.kategorier || recipe.categories || []).map(c => String(c).toLowerCase());
  if (/korv|falukorv|isterband/.test(name)) return "korv";
  if (/pasta|makaron|spaghetti|lasagne|carbonara/.test(name) || cats.includes("pasta")) return "pasta";
  if (/soppa/.test(name) || cats.includes("soppa")) return "soppa";
  if (/gratäng|pudding|låda/.test(name)) return "gratäng";
  if (/pannkak|gröt|plätt|raggmunk|palt|kroppkak|våffl/.test(name)) return "pannkaka";
  if (/tacos|fajitas|burrito|quesadilla/.test(name)) return "tacos";
  return recipe.proteinkalla || "övrigt";
}

// Variation i veckan: en normal familjevecka ska inte bli fyra korvrätter
// eller samma protein varje dag. Straffet växer kvadratiskt med varje
// UPPREPNING utöver den andra av samma sorts rätt eller protein - två
// pastarätter i veckan är vardag, fyra är tjat. Priserna röras aldrig:
// detta viktar bara VALET mellan kombinationer vars kostnader förblir
// ärliga.
function comboVarietyPenalty(combo) {
  const families = {};
  const proteins = {};
  combo.forEach(recipe => {
    const family = dishFamily(recipe);
    families[family] = (families[family] || 0) + 1;
    const protein = recipe.proteinkalla || "övrigt";
    proteins[protein] = (proteins[protein] || 0) + 1;
  });
  let penalty = 0;
  Object.values(families).forEach(n => { if (n > 2) penalty += (n - 2) ** 2 * 4; });
  Object.values(proteins).forEach(n => { if (n > 2) penalty += (n - 2) ** 2 * 3; });
  return penalty;
}

// Vad familjen NYSS åt drar ner, vad de HAR HEMMA drar upp.
//
// Båda är mjuka termer i samma poäng, inte spärrar. Tacos varje fredag är
// ett val familjen får göra; poängen ska bara sluta föreslå det av sig
// självt vecka efter vecka (§15). Och en rätt som använder kycklingen och
// paprikan som redan står i kylen är värd mer än en som inte gör det, utan
// att bli obligatorisk (§17).
function comboHistoryPenalty(combo) {
  return combo.reduce((sum, recipe) =>
    sum + recentlyEatenPenalty(recipe.id, state.weekHistory, state.favoriter), 0);
}

// Skalan är avsiktligt låg: en vara hemma är värd ungefär en tredjedel av
// ett "gillar"-betyg. Att låta skafferiet styra hårdare hade gjort veckan
// till en resthantering i stället för en matsedel.
const PANTRY_BONUS_PER_ITEM = 0.4;
function comboPantryBonus(combo) {
  const home = pantryNamesForCooking();
  if (!home.length) return 0;
  return combo.reduce((sum, recipe) => sum + pantryOverlap(recipe, home), 0) * PANTRY_BONUS_PER_ITEM;
}

const comboAffinity = combo => combo.reduce((sum, recipe) => sum + recipeAffinity(recipe), 0)
  - comboVarietyPenalty(combo)
  - comboHistoryPenalty(combo)
  + comboPantryBonus(combo);
// combinations() is C(pool, count), so a fixed pool size makes the search
// blow up as the week gets longer: with the previous fixed pool of 24 a
// 7-dinner week evaluated 346,104 combos against 10,626 for 4 - measured at
// ~440ms just to build them, before any cost maths. Shrinking the pool for
// longer weeks keeps every week length in the same ballpark (~30-40k combos)
// while still leaving far more candidates than dinners to choose between.
const CANDIDATE_POOL_FOR_COUNT = { 5: 22, 6: 20, 7: 18 };
// One recipe's purchase cost for the current household. Bank recipes carry a
// REAL inkopspris (from the pricing run); one that could not be priced
// borrows the bank's median so planning still works - that median never
// reaches a screen, it only keeps an unpriced recipe from looking free.
let _medianInkopspris = null;
function medianInkopspris() {
  if (_medianInkopspris != null) return _medianInkopspris;
  const priced = [...RECEPT, ...state.apiRecipes]
    .map(recipe => recipe.inkopspris).filter(value => value != null).sort((a, b) => a - b);
  _medianInkopspris = priced.length ? priced[Math.floor(priced.length / 2)] : 100;
  return _medianInkopspris;
}
function comboEstimatedCost(combo) {
  const factor = portionFactor(state.personer);
  return combo.reduce((sum, recipe) =>
    sum + (recipe.inkopspris ?? medianInkopspris()) * factor, 0);
}
function evaluateCombos(recipes, count, branch) {
  // minTotal: however hard the pool is capped, a `count`-dinner week needs
  // at least count+1 candidates or there is nothing to choose between.
  // Enkel vardagsmat överlever poolklippet: rank 0 för vardags-/husman-
  // taggade recept, 1 för övriga. Priset styr fortfarande inom varje klass
  // och budgeten räknas på ärliga kostnader - det här ändrar bara VILKA som
  // får vara med och tävla.
  const everydayRank = recipe => {
    const tags = recipe.taggar || recipe.tags || [];
    // Heltalsdelen är klassen (vardagsmat före övrigt); decimalen är slump
    // INOM klassen. Utan den var urvalet helt deterministiskt - "Skapa ny
    // vecka" gav exakt samma vecka varje gång. Slumpen väljer bara vilka
    // kandidater av samma klass som får tävla; budget och kostnader räknas
    // oförändrat på riktiga priser nedströms.
    return (tags.includes("vardagsmat") || tags.includes("husmanskost") ? 0 : 10) + Math.random();
  };
  const pool = limitCandidatePool(recipes, 6, CANDIDATE_POOL_FOR_COUNT[count] || 24,
                                  "proteinkalla", "inkopspris", count + 1, everydayRank);
  // comboEstimatedCost, not shoppingListCost: the static catalogue does not
  // know the bank's ingredients, so it priced every bank-recipe week at
  // 0 kr - and a planner whose every option is "free" picks arbitrarily.
  return combinations(pool, count).map(combo => ({ combo, cost: comboEstimatedCost(combo) }));
}
function bestMenuCombo(recipes, count, budget, branch, objective = "cheapest") {
  if (!recipes.length) return [];
  if (recipes.length <= count) return [...recipes];
  const evaluated = evaluateCombos(recipes, count, branch);
  const pool = inBudgetPool(evaluated, budget);
  let best;
  if (objective === "protein") best = pickProtein(pool, comboAffinity);
  else if (objective === "balanced") best = pickBalanced(pool, budget, comboRating, comboAffinity);
  else best = pickCheapest(pool, comboAffinity);
  return best ? best.combo : [];
}
function distanceKm(lat1, lon1, lat2, lon2) {
  const earthRadius = 6371, latDelta = (lat2 - lat1) * Math.PI / 180, lonDelta = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(latDelta / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(lonDelta / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
// =============================================================================
// ENTITLEMENTS - the Free/Premium contract, fetched from the backend
// =============================================================================
// The backend is the source of truth (see services/accounts/features.py).
// The frontend never decides what Premium means: it asks, caches the answer,
// and renders locks from it. Until the answer arrives we assume FREE - a
// paywall that flashes open is annoying, Premium data leaking to Free is a
// broken business model.
// Speglar Free-svaret i backend/services/accounts/features.py. Om
// /api/entitlements inte kan nås gäller detta - inte "allt öppet".
const FREE_FEATURES = {
  standard_week: true, family_week: false, budget_week: false, training_week: false,
  bulk_week: false, quick_week: false, vegetarian_week: false, balanced_week: false,
  seven_dinners: false, cheapest_store_price: true, cheapest_store_basket: true,
  all_store_prices: false, all_store_baskets: false, store_comparison: false,
  live_prices: false,
  recipe_search: true, advanced_nutrition: false, meal_prep: false,
  basic_pantry: true, full_pantry: false, favorites: true,
};
const FREE_ENTITLEMENTS = { plan: "free", isPremium: false, maxDinners: 4, features: FREE_FEATURES, pricing: null };
let entitlements = FREE_ENTITLEMENTS;
// Starts as "free" (the boot assumption), so a premium user's first fetch
// counts as a plan CHANGE and clears any persisted free-masked snapshot.
let lastEntitlementPlan = "free";
async function fetchEntitlements() {
  try {
    const token = getStoredToken();
    const response = await fetch(entitlementsApiUrl(), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    entitlements = await response.json();
  } catch {
    // Nätet nere: behåll det vi har. Free är alltid ett säkert antagande.
  }
  // A plan change makes every cached pricing answer stale: the masked
  // Free response must not survive into Premium (locked cards after an
  // upgrade), and a Premium snapshot must not leak into Free. Throw the
  // whole price picture away and fetch it again under the new plan.
  if (lastEntitlementPlan !== entitlements.plan) {
    databasePricingSync = { key: null, pending: false };
    state.dbChainTotals = {}; state.dbLockedChains = []; state.dbComparison = null;
    state.dbPricedAt = null; state.extraMatches = {}; extraMatchSync = {};
  }
  lastEntitlementPlan = entitlements.plan;
  // Priserna kommer med svaret - rita om flikarna nu, annars står de kvar
  // med reservvärdena tills något annat råkar rendera kontoarket.
  renderPriceTabs();
  // A saved dinner count above the plan's cap quietly clamps for the NEXT
  // generated week. The already-chosen week is untouched - a paywall must
  // never eat food someone already planned.
  if (!hasPremium() && state.middagar > maxDinners()) {
    state.middagar = maxDinners();
    saveState();
  }
  render();
}
function can(feature) {
  if (hasPremium()) return true;
  const features = entitlements.features || {};
  return feature in features ? Boolean(features[feature]) : true;
}
function maxDinners() { return hasPremium() ? 7 : (entitlements.maxDinners || 4); }
function premiumPricing() {
  // Reservvärdet gäller bara innan /api/entitlements svarat. Det bär samma
  // siffror som backend (features.PRICING) så flikarna aldrig visar tomt.
  return entitlements.pricing || {
    monthly: { priceText: "59 kr/mån", pricePerMonth: 59 },
    yearly: { priceText: "399 kr/år", pricePerYear: 399, perMonthText: "≈ 33 kr/mån",
              savingsText: "Spara 309 kr jämfört med månadsbetalning", badge: "Bäst värde" },
  };
}
// Ångerrätten (distansavtalslagen). Texten kommer från backend precis som
// priserna - reservvärdet gäller bara innan /api/entitlements svarat, och
// bär samma sträng som services/billing/withdrawal.py. Kryssar användaren i
// rutan mot reservtexten är det ändå backends version som sparas.
function withdrawalTerms() {
  return entitlements.withdrawal || {
    text: "Jag vill få tillgång till Premium direkt och godkänner att min ångerrätt upphör när tjänsten levererats.",
    note: "Utan det här kan vi inte öppna Premium direkt, eftersom du då har fjorton dagars ångerrätt på en tjänst som redan levererats.",
  };
}
function withdrawalConsentMarkup(id) {
  const terms = withdrawalTerms();
  return `<label class="withdrawal-consent" for="${id}">
    <input type="checkbox" id="${id}" data-withdrawal-consent>
    <span>${escapeHtml(terms.text)}</span>
  </label>
  <p class="withdrawal-consent-note">${escapeHtml(terms.note || "")}</p>`;
}
function withdrawalConsentGiven(root) {
  return Boolean(root?.querySelector("[data-withdrawal-consent]")?.checked);
}

// =============================================================================
// LOCAL DEVELOPMENT ONLY - Premium UI unlock
// =============================================================================
// Lets a developer walk the whole Premium flow in a browser without creating
// an account. It CANNOT be turned on in production, by design and not by
// convention:
//
//   1. It is gated on the page being served from a loopback host. Production
//      is https://matjakt.store, which is not one, so the switch is dead
//      there no matter what anyone puts in storage.
//   2. It only affects what this browser DRAWS. Every Premium capability the
//      server actually guards - campaigns, billing, account state - is still
//      checked server-side against a real account, so flipping this unlocks
//      no data and no paid feature.
//
// Turn on from the console:  localStorage.setItem("matjakt-dev-premium","1")
const DEV_PREMIUM_KEY = "matjakt-dev-premium";

function isLoopbackHost() {
  return ["localhost", "127.0.0.1", "[::1]", "0.0.0.0"].includes(location.hostname);
}

function devPremiumEnabled() {
  if (!isLoopbackHost()) return false;
  try {
    return localStorage.getItem(DEV_PREMIUM_KEY) === "1";
  } catch {
    return false;
  }
}

// The single place the UI asks "is this user Premium". Everything else reads
// this, so the dev switch has exactly one entry point rather than being
// sprinkled through every call site.
function hasPremium() {
  // Server-side entitlement first (fetched from /api/entitlements), the
  // user payload as backup, the loopback-only dev switch last. Nothing here
  // GRANTS Premium - the backend masks Premium data regardless, this only
  // decides which UI state to draw.
  if (entitlements.isPremium) return true;
  if (state.user?.premium) return true;
  return devPremiumEnabled();
}

function nearbyBranches() { return state.branches.length ? state.branches : FALLBACK_BRANCH; }
// Everything that describes WHERE the user shops. A new postcode invalidates
// all of it: keeping Gävle's branches, Gävle's fetched prices or a pinned
// Gävle store after a move to Stockholm would show the user a shop they
// cannot walk into and a total they cannot pay.
function clearLocationDerivedState() {
  state.branches = [];
  state.liveBranchTotals = {};
  state.livePriser = {};
  state.dbChainTotals = {};
  state.dbComparison = null;
  state.dbPricedAt = null;
  state.liveUpdatedAt = null;
  // A branch pinned in the old town is not reachable from the new one.
  state.pinnedBranch = null;
  // Both sync guards must forget their old key, or the refetch for the new
  // postcode is skipped as "already done".
  databasePricingSync = { key: null, pending: false };
  branchComparisonSync = { key: null, branches: new Set() };
}

let branchesSync = { key: null, loading: false };
async function syncNearbyBranches() {
  const zip = state.postnummer;
  if (!/^\d{5}$/.test(zip) || branchesSync.key === zip) return;
  // A fetch already in flight used to make this return outright, so a
  // postcode typed while the previous one was loading was dropped and never
  // retried - the old town's stores simply stayed on screen. Remember the
  // pending postcode instead and pick it up when the current fetch settles.
  if (branchesSync.loading) { branchesSync.pending = zip; return; }
  branchesSync = { key: zip, loading: true, pending: null };
  clearLocationDerivedState();
  render();
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
    state.branches = (data.butiker || []).map(store => ({ kedja: store.kedja, namn: store.namn, ort: store.ort || "", lat: store.lat, lon: store.lon, avstandKm: store.avstandKm, prisfaktor: 1, primatKey: store.primatKey || "",
      // Nationella butiksmodellen: butikens eget id + hur kedjan prissätter
      // (nationellt/per butik) + om den här butikens priser går att få.
      externalStoreId: store.externalStoreId || "", pricingScope: store.pricingScope || "", prisbar: store.prisbar !== false }));
    state.liveBranchTotals = {};
    // Only auto-pick a week here when the user doesn't already have one (same
    // guard as the startup call below) - this resolves on every single app
    // open once real branch data replaces the FALLBACK_BRANCH estimate, and
    // unconditionally regenerating would silently discard checked-off items,
    // cached prices, and even reshuffle an already-chosen week on every visit.
    if (!state.valda.size) chooseMenu(false); else render();
  } catch {
    // The network did not answer. The estimated fallback branch is shown
    // until this can be retried - but the key is cleared so the next attempt
    // is not skipped as "already fetched".
    branchesSync.key = null;
  }
  finally {
    branchesSync.loading = false;
    const pending = branchesSync.pending;
    if (pending && pending !== state.postnummer) branchesSync.pending = null;
    if (pending) { branchesSync.pending = null; syncNearbyBranches(); }
  }
}
// Vad veckan ska ta hänsyn till: enhetens egen kost OCH hushållets
// allergier. Uppgifterna familjen fyller i ska påverka maten - annars är
// formuläret ett löfte som aldrig hålls.
function activeDiet() {
  return mergeDiet(state.kost, householdDietary(state.household));
}
function dietFilterIsActive() {
  const diet = activeDiet();
  return diet.kosttyp !== "" || diet.avoidAllergens.size > 0;
}
function recipeMatchesDislikes(recipe) {
  const disliked = new Set([...state.ogillar, ...householdDietary(state.household).dislikes]);
  if (!disliked.size) return false;
  const text = recipe.ingredienser.join(" ").toLowerCase();
  return [...disliked].some(term => term && text.includes(String(term).toLowerCase()));
}
function localRecipesForUser() {
  return filterByDiet(RECEPT, activeDiet()).filter(recipe => !recipeMatchesDislikes(recipe));
}
function nutritionFilteredRecipes() {
  const dietFiltered = localRecipesForUser();
  if (!hasPremium()) return dietFiltered;
  return filterByNutritionGoals(dietFiltered, currentNutritionGoals());
}
function candidateRecipesForUser() {
  return nutritionFilteredRecipes().filter(recipe => !state.feedback[recipe.id]?.disliked);
}
// candidateRecipesForUser() alone can silently return too few (or zero) recipes
// when the user's näringsmål are stricter than what the recipe catalog can ever
// match - bestMenuCombo() then quietly builds an empty week with no explanation.
// This is the single choke point both chooseMenu() and openPlanComparison() go
// through to generate a week, so falling back to the diet-only pool (and
// surfacing #nutritionWarning) here fixes it everywhere a week gets (re)built.
// Enkel svensk vardagsmat först i förslagspoolen. En ny användares första
// vecka ska kännas som "korv stroganoff, köttbullar, kyckling med ris" -
// inte fem Instagram-recept. Stabil sortering: vardags-/husmanskostrecepten
// leder, resten följer i sin gamla ordning så variationen finns kvar (och
// urvalslogiken blandar fortfarande in annat via sina egna poäng).
function everydayFirst(recipes) {
  const score = recipe => {
    const tags = recipe.taggar || recipe.tags || [];
    return (tags.includes("vardagsmat") ? 2 : 0)
         + (tags.includes("husmanskost") ? 1 : 0)
         + (tags.includes("barn") ? 1 : 0);
  };
  return recipes.map((recipe, index) => ({ recipe, index, score: score(recipe) }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map(entry => entry.recipe);
}

function weekPlanCandidates() {
  const dietOnly = everydayFirst(localRecipesForUser().filter(recipe => !state.feedback[recipe.id]?.disliked));
  const goalsActive = hasPremium() && hasActiveNutritionGoals(currentNutritionGoals());
  if (!goalsActive) return { candidates: dietOnly, nutritionShortfall: false };
  const nutritionCandidates = candidateRecipesForUser();
  if (nutritionCandidates.length < state.middagar) return { candidates: dietOnly, nutritionShortfall: true };
  return { candidates: nutritionCandidates, nutritionShortfall: false };
}
// U17: säg när budget, kostkrav och receptutbud inte går ihop.
//
// bestMenuCombo returnerar allt den har när kandidaterna är färre än
// antalet middagar - utan ett ord. Den som ber om sju middagar och får fem
// tror att appen är trasig. Näringsmålen hade en text; kostkraven var tysta.
function updateNutritionWarning(nutritionShortfall, fick = null) {
  const text = planWarning({
    önskade: state.middagar,
    fick: fick == null ? state.middagar : fick,
    nutritionShortfall,
    kosttyp: state.kost.kosttyp,
    allergener: state.kost.avoidAllergens.size,
    ogillar: state.ogillar.size,
    // Hela utbudet före användarens filter. Är det tomt har recepten inte
    // laddats än, och då är noll träffar ett laddningstillstånd - inte ett
    // besked om att kraven är för hårda.
    utbud: RECEPT.length,
  });
  $("nutritionWarning").hidden = !text;
  if (text) $("nutritionWarning").textContent = text;
}
function cheapestBranch(chain = null) {
  const branches = nearbyBranches().filter(branch => !chain || branch.kedja === chain);
  const candidates = candidateRecipesForUser();
  const scored = branches.map(branch => {
    const recipes = bestMenuCombo(candidates, state.middagar, state.budget, branch);
    const avstandKm = state.position ? distanceKm(state.position.lat, state.position.lon, branch.lat, branch.lon) : branch.avstandKm;
    return { ...branch, avstandKm, recipes, total: shoppingListCost(recipes, branch) };
  }).filter(result => result.recipes.length);
  if (!scored.length) return null;
  // Without Premium, every branch shares the same flat price estimate (no real
  // per-chain data exists until live prices are fetched, which only happens after
  // a week is chosen) - sorting that by "total" would just be an arbitrary tie,
  // which is exactly how a wrong "X is cheapest" claim happens. Pick by distance
  // instead and never claim it's the cheapest; real cross-store comparison lives
  // in renderStoreComparison() using live data, gated to Premium.
  if (!hasPremium()) return scored.sort((a, b) => a.avstandKm - b.avstandKm)[0];
  // Premium auto-pick: the server's own comparison decides which CHAIN is
  // cheapest (real prices, real coverage guards, see compare_chains); the
  // nearest branch of that chain wins. The static estimates all share
  // prisfaktor 1, so sorting by their "total" was an arbitrary tie - the
  // very thing the "Billigast" guards exist to prevent.
  const winnerChain = state.dbComparison?.cheapestChain;
  const ofWinner = winnerChain ? scored.filter(branch => branch.kedja === winnerChain) : [];
  const pool = ofWinner.length ? ofWinner : scored;
  return pool.sort((a, b) => a.avstandKm - b.avstandKm)[0];
}
// A branch the user explicitly picked from the store comparison list (e.g.
// "Coop Tullhuset" over the auto-picked "Coop Nian") overrides the normal
// nearest/cheapest logic for as long as it's still relevant - i.e. its own
// chain still matches the currently selected chain tab. Re-matched against
// the current nearbyBranches() list (by primatKey, each branch's stable
// identity) rather than trusted as-is, so distance/pricing stay current;
// falls back to the stored snapshot itself if that exact branch has since
// dropped out of range.
function pinnedBranchMatch() {
  if (!state.pinnedBranch || state.pinnedBranch.kedja !== state.butik) return null;
  return nearbyBranches().find(branch => branch.primatKey && branch.primatKey === state.pinnedBranch.primatKey) || state.pinnedBranch;
}
let branchCache = { key: null, value: null };
function selectedBranch() {
  const key = JSON.stringify([state.budget, state.middagar, state.butik, state.postnummer, state.position, RECEPT.length, state.apiRecipes.length, hasPremium(), state.naringsmal, state.pinnedBranch, state.branches.length]);
  if (branchCache.key !== key) branchCache = { key, value: pinnedBranchMatch() || (state.butik === "auto" ? cheapestBranch() : cheapestBranch(state.butik)) };
  return branchCache.value;
}
function cheapestStore() {
  return selectedBranch();
}

const chosenStore = () => cheapestStore()?.kedja || state.butik;
const productApiUrl = (store, query) => { const branch = selectedBranch(); return configuredProductApiUrl(store, query, state.postnummer, branch?.kedja === store ? branch.primatKey : ""); };
function sanitizeApiPayload(payload) {
  if (!Array.isArray(payload?.produkter)) return payload;
  // pris_kr must stay null when the source has no price for this product -
  // "Number(x) || 0" used to turn that into a real, spendable-looking 0 kr
  // (and let it silently count as free in any total that summed it), which
  // is exactly the "0 kr" bug this was rewritten to fix.
  return { ...payload, produkter: payload.produkter.map(product => ({ ...product, produktnamn: escapeHtml(product.produktnamn), marke_och_storlek: escapeHtml(product.marke_och_storlek), bild: product.bild ? safeHttpUrl(product.bild) : "", url: safeHttpUrl(product.url), pris_kr: product.pris_kr == null ? null : Number(product.pris_kr) })) };
}
const availableRecipes = () => candidateRecipesForUser();

function chooseMenu(shouldScroll = true) {
  const branch = selectedBranch();
  const { candidates, nutritionShortfall } = weekPlanCandidates();
  const combo = bestMenuCombo(candidates, state.middagar, state.budget, branch);
  // Varningen efter valet, inte före: först då vet vi hur många rätter
  // veckan faktiskt fick.
  updateNutritionWarning(nutritionShortfall, combo.length);
  setWeekPlan(combo.map(r => r.id));
  // A new set of meals makes any checked-off shopping items and cached live
  // prices from the previous week meaningless - without this, starting a new
  // week could show ingredients as "already bought" just because an item with
  // the same name was checked off last week.
  state.avklarade.clear();
  state.harHemma.clear();
  state.removedItems.clear();
  state.swapsThisWeek = 0;
  clearPriceSnapshots();
  trackEvent("vecka_skapad");
  saveState();
  render();
  if (shouldScroll) {
    setView("week");
  }
}

// The filter row. Order matters: the ones people reach for most (Barn,
// snabbt, billigt) sit first, so the useful filters are not behind a scroll
// on a phone.
const RECIPE_FILTER_TAGS = ["barn", "snabbt", "billigt", "proteinrikt",
                            "vegetariskt", "fisk", "kyckling", "kott", "mealprep"];

function renderRecipeTagFilters() {
  const container = $("recipeTagFilters");
  if (!container) return;
  container.innerHTML = RECIPE_FILTER_TAGS.map(tag => {
    const active = state.receptTaggar.has(tag);
    return `<button type="button" class="recipe-tag ${active ? "active" : ""}" data-recipe-tag="${tag}" aria-pressed="${active}">${escapeHtml(TAG_LABELS[tag] || tag)}</button>`;
  }).join("");
  container.querySelectorAll("[data-recipe-tag]").forEach(button =>
    button.addEventListener("click", () => {
      const tag = button.dataset.recipeTag;
      state.receptTaggar.has(tag) ? state.receptTaggar.delete(tag) : state.receptTaggar.add(tag);
      renderRecipes();
    }));
}

// True when the user is browsing rather than looking for something specific.
// Shelves answer "what should we eat this week"; a flat list answers "show me
// the quick vegetarian ones". Showing both at once would be noise.
function recipeBrowsingMode() {
  return !state.sokning.trim() && !state.receptTaggar.size && !state.maxTid
    && !state.minProtein && !state.maxKcal && !state.baraFavoriter
    && state.kategori === "alla";
}

async function syncRecipeShelves() {
  if (state.hyllor.length) return;
  state.hyllor = await loadShelves(12);
  if (state.hyllor.length) renderRecipes();
}

function renderRecipeShelves() {
  const container = $("recipeShelves");
  if (!container) return;
  if (!recipeBrowsingMode()) { container.innerHTML = ""; return; }
  syncRecipeShelves();
  container.innerHTML = state.hyllor.map(shelf => `
    <section class="recipe-shelf">
      <h2>${escapeHtml(shelf.title)}</h2>
      <div class="recipe-shelf-row">${shelf.recipes.map(recipeShelfCard).join("")}</div>
    </section>`).join("");
  container.querySelectorAll("[data-shelf-recipe]").forEach(card =>
    card.addEventListener("click", () => openRecipeTab(card.dataset.shelfRecipe)));
}

function recipeShelfCard(recipe) {
  const time = recipe.tid ? `${recipe.tid} min` : "";
  const kcal = recipe.kcal ? `${Math.round(recipe.kcal)} kcal` : "";
  return `<button type="button" class="recipe-shelf-card" data-shelf-recipe="${escapeHtml(recipe.id)}">
    <span class="recipe-shelf-photo">${recipePhoto(recipe)}</span>
    <strong>${escapeHtml(recipe.namn)}</strong>
    <small>${escapeHtml([time, kcal].filter(Boolean).join(" · "))}</small>
  </button>`;
}

function renderRecipes() {
  const search = state.sokning.trim();
  const dietFilterActive = dietFilterIsActive();
  const recipes = filterRecipes(search ? [...localRecipesForUser(), ...(dietFilterActive ? [] : state.apiRecipes)] : availableRecipes(), search).filter(recipe => (state.kategori === "alla" || recipe.typ === state.kategori)
      && (!state.maxTid || recipe.tid <= state.maxTid)
      && (!state.minProtein || (recipe.protein || 0) >= state.minProtein)
      && (!state.maxKcal || (recipe.kcal || 0) <= state.maxKcal)
      && matchesAllTags(recipe, [...state.receptTaggar])
      && (!state.baraFavoriter || state.favoriter.has(recipe.id)));
  const branch = selectedBranch();
  // "Billigast" in a label is a claim; it is only made when the server's
  // real comparison crowned this branch's chain. Otherwise the honest word
  // is "närmast", which is how the branch was actually picked.
  const autoIsWinner = hasPremium() && state.dbComparison?.cheapestChain
    && branch?.kedja === state.dbComparison.cheapestChain;
  const storeLabel = state.butik === "auto" ? `${branch?.namn || "ingen butik hittades"}${autoIsWinner ? " (billigast för din lista)" : " (närmast)"}` : state.butik === "alla" ? "alla butiker" : `${branch?.namn || state.butik}`;
  const loading = !state.branches.length && branchesSync.loading;
  // avstandKm can be null (e.g. a branch source that doesn't report distance,
  // or no state.position yet to measure from) - .toFixed() on that used to
  // throw and silently abort the rest of this render pass.
  const distanceText = Number.isFinite(branch?.avstandKm) ? ` och ligger ${branch.avstandKm.toFixed(1)} km bort` : "";
  $("locationHint").textContent = branch ? `${nearbyBranches().length} butiksprofiler jämförda${loading ? " (hämtar riktiga butiker nära dig...)" : ""} · ${branch.namn} ${autoIsWinner ? "är billigast för din lista just nu" : "ligger närmast"}${distanceText}.` : (state.postnummer ? `Hittade inga inlästa butiker nära ${state.postnummer} ännu.` : "Ange ditt postnummer så hittar vi butiker nära dig.");
  $("menuSummary").textContent = search ? (dietFilterActive ? `${recipes.length} recept hittades. Externa recept visas inte när kost-/allergifilter är aktivt, eftersom de inte har kontrollerade allergiuppgifter.` : `${recipes.length} recept hittades. Externa recept kan vara på engelska och sakna svenska butikspriser.`) : `${plural(Math.min(state.middagar, recipes.length), "middag", "middagar")} för ${plural(state.personer, "person", "personer")} från ${storeLabel}. Priserna är uppskattningar.`;
  renderRecipeTagFilters();
  renderRecipeShelves();
  // The flat list is hidden while browsing - the shelves ARE the list then.
  const browsing = recipeBrowsingMode();
  $("recipeScroll").hidden = browsing;
  if (browsing) { $("menuSummary").textContent = ""; return; }
  $("recipeScroll").innerHTML = recipes.length ? recipes.map(recipe => {
    const selected = state.valda.has(recipe.id), expanded = state.expanded === recipe.id;
    const details = detailsFor(recipe);
    return `<article class="recipe-card ${selected ? "selected" : ""}">
      <button class="recipe-details" data-details="${escapeHtml(recipe.id)}" aria-expanded="${expanded}">
        <span class="recipe-photo-wrap">${recipePhoto(recipe)}<span class="saving">${recipe.sparar ? `Spara ca ${money(recipe.sparar)}` : "Från receptdatabas"}</span></span>
        <span class="recipe-name">${escapeHtml(recipe.namn)}</span><span class="recipe-meta">${escapeHtml(recipe.tid)} min · ${escapeHtml(recipe.typ)}</span><span class="recipe-store">Billigast på ${escapeHtml(recipe.butik)}</span>
        <span class="price-tag">${recipe.inkopspris ? `${money(scaledPurchasePrice(recipe))} i butik` : "Pris hämtas från butik"}</span><span class="portion-price">${recipe.portionspris ? `ca ${money(recipe.portionspris)} per portion` : "Ingredienser och instruktioner finns"}</span>
        ${recipe.kcal ? `<span class="recipe-macros">${macroLine(recipe)}</span>` : ""}
      </button>
      ${expanded ? `<div class="ingredients"><p class="recipe-description">${escapeHtml(details.beskrivning || "En god vardagsrätt med enkla råvaror.")}</p><strong>Du behöver köpa</strong><p>${escapeHtml(recipe.ingredienser.join(", "))}</p><small>Hemma: ${escapeHtml(recipe.hemma.join(", "))}</small>${details.steg ? `<ol class="recipe-steps">${details.steg.map(step => `<li>${escapeHtml(step)}</li>`).join("")}</ol>` : ""}${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${escapeHtml(details.tips)}</p>` : ""}</div>` : ""}
      <button class="favorite-btn ${state.favoriter.has(recipe.id) ? "is-favorite" : ""}" data-favorite="${escapeHtml(recipe.id)}" aria-label="${state.favoriter.has(recipe.id) ? "Ta bort favorit" : "Spara som favorit"}">${state.favoriter.has(recipe.id) ? "★" : "☆"}</button><button class="add-btn" data-add="${escapeHtml(recipe.id)}">${selected ? "✓ Tillagd" : "+ Lägg till"}</button>
    </article>`;
  }).join("") : `<p class="empty-state">Inga recept matchar din sökning eller butik ännu.</p>`;
  document.querySelectorAll("[data-details]").forEach(btn => btn.addEventListener("click", () => openRecipeTab(btn.dataset.details)));
  document.querySelectorAll("[data-add]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.add; state.valda.has(id) ? removeFromWeekPlan(id) : addToWeekPlan(id); saveState(); render(); }));
  document.querySelectorAll("[data-favorite]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.favorite; state.favoriter.has(id) ? state.favoriter.delete(id) : state.favoriter.add(id); saveState(); renderRecipes(); }));
}

// U65: kom ihåg var i listan man var.
//
// Att öppna ett recept ska börja överst i receptet - men att gå TILLBAKA
// ska lämna en där man stod. Förut gjorde tillbakavägen scrollTo(0, 0),
// alltså nollställdes platsen med flit, och den som bläddrade i en lång
// receptlista fick börja om efter varje titt. Filtren låg redan kvar i
// state; det enda som tappades var raden man tittade på.
let listScrollY = 0;
// Webbläsaren återställer SIN ihågkomna position vid bakåtnavigering, och
// den positionen är var man stod INNE i receptet. Den slogs mot appens egen
// återställning och landade emellan - 1200 px före, 1472 px efter i test.
// Med "manual" äger appen scrollen, vilket är enda sättet att göra löftet i
// U65 sant.
if ("scrollRestoration" in history) history.scrollRestoration = "manual";

function openRecipeTab(id) {
  listScrollY = window.scrollY;
  history.pushState({ recept: id }, "", `${location.pathname}?recept=${encodeURIComponent(id)}`);
  renderRecipePage();
}
const FAVORITE_ICON = '<svg viewBox="0 0 24 24"><path d="M12 21s-7-4.6-9.5-9C.7 8.2 2.4 5 5.7 5c2 0 3.4 1.1 4.3 2.4C11 6.1 12.4 5 14.4 5c3.3 0 5 3.2 3.2 7-2.5 4.4-9.5 9-9.5 9Z"/></svg>';
const PRICE_TAG_ICON = '<svg viewBox="0 0 24 24"><path d="M20 12 12.5 4.5a2 2 0 0 0-1.4-.5H5a1 1 0 0 0-1 1v6.1a2 2 0 0 0 .6 1.4L12 20"/><circle cx="8" cy="8" r="1.3"/></svg>';
function formatMeasure(amount) {
  if (amount == null) return "";
  const whole = Math.floor(amount);
  const fraction = Math.round((amount - whole) * 100) / 100;
  const parts = { 0.25: "¼", 0.33: "⅓", 0.5: "½", 0.67: "⅔", 0.75: "¾" };
  if (parts[fraction]) return whole ? `${whole} ${parts[fraction]}` : parts[fraction];
  return Number.isInteger(amount) ? String(amount) : String(Math.round(amount * 10) / 10);
}

// Ingrediensmängderna skalas till HUSHÅLLET - receptbankens rader gäller
// recipe.servings portioner, men veckan lagas för state.personer.
function scaledIngredientRows(recipe) {
  const structured = Array.isArray(recipe.ingredients) ? recipe.ingredients : [];
  if (!structured.length) return null;
  const scale = state.personer / (recipe.servings || 4);
  const rows = { buy: [], home: [] };
  structured.forEach(item => {
    const target = item.pantryStaple ? rows.home : rows.buy;
    const amount = item.amount != null && !item.pantryStaple ? formatMeasure(item.amount * scale) : "";
    target.push({ amount, unit: item.pantryStaple ? "" : (item.unit || ""), name: item.name, optional: item.optional });
  });
  return rows;
}

async function renderRecipePage() {
  const id = new URLSearchParams(location.search).get("recept");
  if (!id) {
    $("top").hidden = false;
    $("recipePage").hidden = true;
    // Efter renderingen, annars är sidan ännu för kort och scrollen klipps
    // till noll. setView() scrollar också till toppen, så återställningen
    // måste komma efter den - därför två bildrutor, inte en.
    // MOMENTAN, inte mjuk. styles.css sätter html{scroll-behavior:smooth},
    // så ett vanligt scrollTo blir en animation över ~300 ms - och en
    // animation går att störa. Mätt: återställningen landade rätt på 1198 px
    // och drogs sedan vidare till 1477 av något annat som hann emellan.
    // Att komma tillbaka dit man var ska inte se ut som en resa.
    const mål = listScrollY;
    requestAnimationFrame(() => requestAnimationFrame(
      () => window.scrollTo({ top: mål, left: 0, behavior: "instant" })));
    return;
  }
  let allRecipes = [...RECEPT, ...state.apiRecipes];
  // A card deliberately ships without steps and structured ingredients (the
  // list payload stays small). The detail PAGE is the one place that needs
  // everything, so fetch the full recipe once and merge it into the same
  // object every list references.
  const found = allRecipes.find(r => r.id === new URLSearchParams(location.search).get("recept"));
  if (found && found.priceStatus !== "unavailable"
      && (!Array.isArray(found.steg) || !found.steg.length)
      && !recipeDetailFetches.has(found.id)) {
    recipeDetailFetches.add(found.id);
    loadRecipe(found.id).then(detail => {
      // Samma regel som i ensureWeekRecipeDetails: null är ett definitivt
      // "finns inte" och frågas aldrig om igen; ett kastat fel är okänt och
      // släpper id:t fritt för nästa försök.
      if (!detail) return;
      Object.assign(found, detail, { steg: detail.instructions || detail.steg || [] });
      renderRecipePage();
    }).catch(() => recipeDetailFetches.delete(found.id));
  }
  let recipe = allRecipes.find(item => item.id === id);
  if (!recipe && id.includes(":")) {
    try { const response = await fetch(recipeDetailApiUrl(id)); if (response.ok) { const data = await response.json(); recipe = mapApiRecipe(data.recipe); state.apiRecipes.push(recipe); allRecipes = [...RECEPT, ...state.apiRecipes]; } } catch { /* The friendly not-found state below remains visible. */ }
  }
  if (!recipe) {
    // A deep link (?recept=...) arrives BEFORE the recipe bank has loaded.
    // Returning to Hem here made every shared recipe link land on the start
    // page; show the page in a calm loading state instead - the bank's
    // loadRecipes().then() re-runs this render the moment recipes exist.
    $("top").hidden = true;
    $("recipePage").hidden = false;
    $("recipePage").innerHTML = `<button class="recipe-back" type="button" aria-label="Tillbaka till recepten"></button><article class="full-recipe"><div class="full-recipe-fallback">${recipePhoto({})}</div><h1>Hämtar receptet…</h1><p class="full-recipe-description">Ett ögonblick.</p></article>`;
    $("recipePage").querySelector(".recipe-back").addEventListener("click", () => { history.pushState(null, "", location.pathname); renderRecipePage(); setView("recipes"); });
    return;
  }
  const details = detailsFor(recipe);
  $("top").hidden = true;
  document.querySelectorAll(".bottom-nav-item").forEach(item =>
    item.classList.toggle("active", item.dataset.view === "recipes")); /* bottennavigeringen följer med in på receptsidan - flikarna ska alltid
     vara ett tryck bort */ $("recipePage").hidden = false;
  const chips = [
    recipe.tid ? `${recipe.tid} min` : null,
    `${state.personer} portioner`,
    recipe.difficulty || null,
    recipe.priceStatus !== "unavailable" && recipe.portionspris ? `${money(recipe.portionspris)}/portion` : null,
  ].filter(Boolean);
  const ingredientRows = scaledIngredientRows(recipe);
  const ingredientsMarkup = ingredientRows
    ? `${ingredientRows.buy.map(row => `<div class="ing-row${row.optional ? " ing-optional" : ""}"><strong>${escapeHtml([row.amount, row.unit].filter(Boolean).join(" "))}</strong><span>${escapeHtml(row.name)}${row.optional ? " <em>(valfritt)</em>" : ""}</span></div>`).join("")}${ingredientRows.home.length ? `<p class="ing-home-label">Har du säkert hemma</p>${ingredientRows.home.map(row => `<div class="ing-row ing-home"><strong></strong><span>${escapeHtml(row.name)}</span></div>`).join("")}` : ""}`
    : `${recipe.ingredienser.map(item => `<div class="ing-row"><strong></strong><span>${escapeHtml(item)}</span></div>`).join("")}`;
  const stepsMarkup = (details.steg || []).map((step, index) => `<label class="step-row"><input type="checkbox" data-step-check="${index}"><span class="step-number">${index + 1}</span><span class="step-text">${escapeHtml(step)}</span></label>`).join("");
  $("recipePage").innerHTML = `<button class="recipe-back" type="button" aria-label="Tillbaka till recepten"></button><article class="full-recipe">${recipe.bild ? `<img class="recipe-photo full-recipe-hero" src="${escapeHtml(safeHttpUrl(recipe.bild) || "")}" alt="${escapeHtml(recipe.namn)}">` : `<div class="full-recipe-fallback">${recipePhoto(recipe)}</div>`}<p class="eyebrow">${escapeHtml(recipe.typ)}</p><h1>${escapeHtml(recipe.namn)}</h1><div class="recipe-chips">${chips.map(chip => `<span class="recipe-chip">${escapeHtml(chip)}</span>`).join("")}</div>${recipe.kcal ? `<p class="full-recipe-macros">${macroLine(recipe)}</p>` : ""}<p class="full-recipe-description">${escapeHtml(details.beskrivning || "En god svensk vardagsrätt.")}</p><div class="recipe-cta-row"><button class="btn btn-primary recipe-add-primary" type="button" data-recipe-add="${escapeHtml(recipe.id)}"><span>${state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"}</span><span>＋</span></button><button type="button" class="recipe-share-btn" data-recipe-share aria-label="Dela receptet">Dela</button></div><section class="recipe-block"><div class="ing-head"><h2>Ingredienser</h2><span>${state.personer} portioner</span></div>${ingredientsMarkup}</section><section class="recipe-block"><h2>Gör så här</h2><div class="steps">${stepsMarkup}</div></section>${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${escapeHtml(details.tips)}</p>` : ""}<div class="recipe-block">${recipeRatingMarkup(recipe.id)}${feedbackMarkup(recipe.id)}</div></article>`;
  $("recipePage").querySelector(".recipe-back").addEventListener("click", () => history.back());
  // Avbockade steg medan man lagar - sparas lokalt per recept så ett
  // vridet-bort-och-tillbaka på telefonen inte tappar var man var.
  const stepKey = `matjakt-steps-${recipe.id}`;
  let done = [];
  try { done = JSON.parse(localStorage.getItem(stepKey) || "[]"); } catch { /* trasig lagring = börja om */ }
  $("recipePage").querySelectorAll("[data-step-check]").forEach(box => {
    const index = Number(box.dataset.stepCheck);
    box.checked = done.includes(index);
    box.closest(".step-row").classList.toggle("step-done", box.checked);
    box.addEventListener("change", () => {
      box.checked ? done.push(index) : (done = done.filter(x => x !== index));
      box.closest(".step-row").classList.toggle("step-done", box.checked);
      try { localStorage.setItem(stepKey, JSON.stringify(done)); } catch { /* full lagring - bocken lever ändå i DOM */ }
    });
  });
  $("recipePage").querySelector("[data-recipe-share]")?.addEventListener("click", async () => {
    const url = `https://matjakt.store/app/?recept=${encodeURIComponent(recipe.id)}`;
    trackEvent("recept_delat");
    // Web Share där det finns (mobilen), annars urklipp - båda vägarna
    // slutar i samma delbara djuplänk.
    if (navigator.share) {
      try { await navigator.share({ title: recipe.namn, url }); } catch { /* avbruten delning är inget fel */ }
    } else {
      try { await navigator.clipboard.writeText(url); showUndoToast("Länk kopierad", () => {}); } catch { /* utan urklippsrättighet finns adressfältet */ }
    }
  });
  $("recipePage").querySelector("[data-recipe-add]").addEventListener("click", event => { state.valda.has(recipe.id) ? removeFromWeekPlan(recipe.id) : addToWeekPlan(recipe.id); saveState(); render(); event.currentTarget.querySelector("span").textContent = state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"; });
  wireRatingStars($("recipePage"), recipe.id);
  wireFeedbackButtons($("recipePage"), recipe.id);
  requestAnimationFrame(() => window.scrollTo(0, 0));
  let touchStartX = 0; $("recipePage").ontouchstart = event => { touchStartX = event.changedTouches[0].screenX; }; $("recipePage").ontouchend = event => { const distance = event.changedTouches[0].screenX - touchStartX; if (Math.abs(distance) < 70) return; const ids = allRecipes.map(item => item.id), currentIndex = ids.indexOf(id), targetIndex = distance < 0 ? currentIndex + 1 : currentIndex - 1; if (targetIndex >= 0 && targetIndex < ids.length) openRecipeTab(ids[targetIndex]); else if (distance > 0) history.back(); };
}

function branchLiveTotal(shoppingItems, chainProducts) {
  return calculateLiveShoppingTotal(shoppingItems, chainProducts, pantryForPricing());
}
// A branch's stable identity for state.liveBranchTotals - primatKey, not
// chain name, since two branches of the same chain can genuinely have
// different prices (member deals, local campaigns - see cache_scope's
// docstring server-side). A branch with no primatKey (pure scrape fallback,
// nothing concrete to target) has no branch-specific live price to key -
// callers must check for that and leave it out rather than fetch it.
function branchLiveKey(branch) { return branch.primatKey ? `${branch.kedja}#${branch.primatKey}` : null; }
let branchComparisonSync = { key: null, branches: new Set() };
async function syncBranchComparison(shoppingItems, branches) {
  const names = shoppingItems.map(item => item.namn).sort();
  const key = `${state.postnummer}|${names.join(",")}`;
  if (branchComparisonSync.key !== key) { branchComparisonSync = { key, branches: new Set() }; state.liveBranchTotals = {}; }
  if (!names.length) return;
  // Filialpriser är Premium (servern nekar Free med 403) och pausas efter
  // 429/403 - annars blev varje filial ett avvisat anrop till.
  if (!hasPremium() || Date.now() < livePriceCooldownUntil) return;
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
      if (matched.length) { state.liveBranchTotals[branchLiveKey(branch)] = branchLiveTotal(shoppingItems, produkter); state.liveUpdatedAt = Date.now(); renderBasket(); }
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
// Nya försök efter nätfel glesas ut (8 s, 16 s, ... max 2 min) och nollställs
// vid lyckat svar: offline på tåget ska inte ge ett anrop var åttonde
// sekund tills täckningen är tillbaka.
const RETRY_BASE_MS = 8000;
const RETRY_MAX_MS = 120_000;
let pricingRetryCount = 0;
let campaignRetryCount = 0;
function retryDelay(count) { return Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** count); }
// The pricing request for the week's recipes: recipe IDS, not a client-built
// item list. The server aggregates from its own recipe rows - the same rows
// the recipe page shows - so the priced list can never drift from the
// recipes. Legacy/offline recipes without a bank id fall back to item lines.
function pricingHeaders() {
  // The pricing endpoints decide Free vs Premium SERVER-SIDE - but only if
  // they know who is asking. Without the token every user was anonymous,
  // and a paying customer got the masked Free response.
  const token = getStoredToken();
  return { "Content-Type": "application/json",
           ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}
function storeSelectionForPricing() {
  // Användarens butiker till prissättningen: närmaste butik per kedja (listan
  // är avståndssorterad från servern), pinnad butik vinner över närmaste.
  // Servern gör resten ärligt: nationellt prissatta kedjor etiketteras med
  // butiken, butiksspecifika prissätts BARA om just den butikens katalog
  // finns - annars rapporteras kedjan som otillgänglig i stället för att en
  // annan butiks priser visas under fel namn.
  const selection = {};
  for (const branch of nearbyBranches()) {
    if (branch.externalStoreId && !selection[branch.kedja]) selection[branch.kedja] = branch.externalStoreId;
  }
  const pinned = state.pinnedBranch;
  if (pinned?.externalStoreId && pinned.kedja) selection[pinned.kedja] = pinned.externalStoreId;
  return selection;
}

function weekPricingBody(shoppingItems) {
  const selected = selectedRecipes();
  const bankRecipes = selected.filter(recipe => recipe.priceStatus !== "unavailable"
    && (!Array.isArray(recipe.ingredients) || recipe.ingredients.length || recipe.slug));
  const recipeIds = bankRecipes.map(recipe => recipe.id);
  const body = { people: state.personer, pantry: pantryForPricing() };
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
async function syncDatabasePricing(shoppingItems) {
  const body = weekPricingBody(shoppingItems);
  if (!body.recipeIds?.length && !body.items?.length) return;
  // Planen ingår i nyckeln: servern maskar Free-svaret (låsta kedjor), och
  // utan planen i nyckeln låg det maskade svaret kvar efter att Premium
  // aktiverats tills veckan råkade ändras (sett i E2E efter checkout).
  const key = `${hasPremium() ? "premium" : "free"}|${JSON.stringify(body)}`;
  if (databasePricingSync.key === key || databasePricingSync.pending) return;
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
    pricingRetryCount = 0;
    renderBasket();
  } catch {
    // The price database being unreachable must never break the week view.
    // Nothing fake fills the gap - the views show "pris saknas", and this
    // timestamp is how they know the fetch actually failed rather than
    // simply not having finished yet.
    state.dbPricingFailedAt = Date.now();
    // A failure must not park the key forever: with the key left in place,
    // every later render concluded "already fetched" and the header said
    // "pris hämtas…" until a full reload. One deploy window was enough to
    // strand every open phone. Clear the key and retry shortly.
    databasePricingSync.key = null;
    setTimeout(() => renderBasket(), retryDelay(pricingRetryCount++));
  } finally {
    databasePricingSync.pending = false;
  }
}

// The real product the price database picked for one shopping line at the
// chain currently in use - the actual thing to put in the basket, with its
// image, pack size, package count and price. Null when this line could not
// be priced against a real product, which is a fact the card must show
// rather than paper over with the static estimate.
function databaseItemFor(name) {
  // The same chain the header total shows. chosenStore() can be "alla" (the
  // user picked "alla butiker") or a chain the database has no result for -
  // keying the rows on it then made EVERY row fall back to the old scrape
  // path while the header proudly showed 18/18 from the database. The rows
  // and the total must come from one and the same result.
  const result = state.dbChainTotals[chosenStore()]
    || state.dbChainTotals[selectedBranch()?.kedja]
    || Object.values(state.dbChainTotals)[0];
  if (!result) return null;
  // Servern delar en blandenhetsingrediens i en rad per enhet (Grädde
  // 200 g + 1 dl blir två rader med samma namn). Klientens enda rad måste
  // summera ALLA - att visa första radens delpris bredvid en header som
  // summerar samtliga fick radsumman att motsäga totalen.
  const rows = (result.items || []).filter(entry =>
    entry.ingredient === name && entry.priceStatus !== "missing");
  if (!rows.length) return null;
  if (rows.length === 1) return rows[0];
  return {
    ...rows[0],
    packages: rows.reduce((sum, row) => sum + (row.packages || 0), 0),
    totalCost: Math.round(rows.reduce((sum, row) => sum + (row.totalCost || 0), 0) * 100) / 100,
  };
}

function databaseResultFor(branch) {
  return state.dbChainTotals[branch.kedja] || null;
}

// =============================================================================
// EXTRA ITEMS - campaign finds and manual lines on the shopping list
// =============================================================================
// Prices per chain resolve through src/services/extras.js: a real match at
// the current chain, or the item's own campaign price at its own chain,
// or nothing. state.extraMatches[chain][id] = { unitPrice, productName,
// imageUrl } - fetched from the same pricing API as everything else.
let extraMatchSync = {};
async function syncExtraMatches(chain) {
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
    renderBasket();
  } catch {
    extraMatchSync[chain] = null; // försök igen nästa render
  }
}

function currentPricedChain() {
  const chain = chosenStore();
  if (state.dbChainTotals[chain]) return chain;
  return selectedBranch()?.kedja && state.dbChainTotals[selectedBranch().kedja]
    ? selectedBranch().kedja
    : Object.keys(state.dbChainTotals)[0] || chain;
}

// Kedjan vars totalsumma får stå som VECKANS pris i Handla-headern. En kedja
// som servern dömt ut (comparable=false, för få varor prissatta) har en
// riktig men ofullständig summa - butikskortet säger "Pris ej tillgängligt"
// och headern får inte samtidigt visa den som veckans pris.
function headerPricedChain() {
  const chain = currentPricedChain();
  const result = state.dbChainTotals[chain];
  return result && result.comparable !== false && (result.realPriceItems || 0) > 0 ? chain : null;
}

function extrasTotalForChain(chain) {
  return extrasTotal(state.extraItems, chain, state.extraMatches[chain] || {});
}

function addExtraItem(fields) {
  // Varna - men hindra aldrig - när varan redan står i listan eller ligger
  // i skafferiet. Dubbelköp är pengar i sjön, men användaren bestämmer.
  const foldName = String(fields.name || "").toLowerCase();
  const inList = aggregateShopping(selectedRecipes()).some(item => item.namn.toLowerCase() === foldName)
    || state.extraItems.some(item => (item.name || "").toLowerCase() === foldName);
  const inPantry = pantryNamesForCooking().some(key => key.toLowerCase() === foldName);
  if (inList || inPantry) {
    showUndoToast(inPantry ? `${fields.name} finns redan i ditt skafferi` : `${fields.name} står redan i listan`, () => {});
  }
  if (householdActive()) {
    // I ett hushåll är en tillagd vara familjens, inte den här telefonens.
    const key = itemKeyFor(fields.name);
    state.household = applyLocalRow(state.household, "shopping",
                                    { key, name: fields.name, status: NEED_TO_BUY, source: "manual" });
    renderBasket();
    upsertShoppingItem(state.authToken, { name: fields.name, source: "manual", category: categoryFor(fields.name) })
      .then(applyHouseholdResponse).catch(() => pullHousehold(true));
    return { id: key, name: fields.name };
  }
  const extra = newExtraItem(fields);
  state.extraItems = [...state.extraItems, extra];
  state.extraMatches = {}; extraMatchSync = {};
  saveState(); renderBasket();
  return extra;
}

function extraRowMarkup(extra, chain) {
  const match = (state.extraMatches[chain] || {})[extra.id];
  const line = extraLineTotal(extra, chain, match);
  const unit = extraUnitPrice(extra, chain, match);
  const fromOtherChain = extra.chain && extra.chain !== chain;
  const photo = (match?.imageUrl || extra.imageUrl)
    ? `<img class="shopping-item-image has-image" src="${escapeHtml(safeHttpUrl(match?.imageUrl || extra.imageUrl) || "")}" alt="" loading="lazy">`
    : categoryIconMarkup("Övrigt");
  const displayName = match?.productName || extra.name;
  const metaBits = [];
  if (match?.packageSize || extra.packageSize) metaBits.push(match?.packageSize || extra.packageSize);
  if (extra.source === "campaign") metaBits.push(`Kampanj hos ${extra.chain}`);
  if (fromOtherChain && !match) metaBits.push(`Ingen matchande produkt hos ${chain}`);
  if (!extra.chain && !match) metaBits.push("Ingen säker prismatch – egen rad");
  const priceText = line != null ? money(line)
    : '<span class="price-missing">–</span>';
  const unitNote = extra.qty > 1 && unit != null ? `<small>${extra.qty} × ${money(unit)}</small>` : "";
  return `<div class="shopping-item extra-item ${extra.checked ? "checked" : ""}">
    <input type="checkbox" data-extra-check="${extra.id}" ${extra.checked ? "checked" : ""}>
    ${photo}
    <span class="shopping-item-info"><strong>${escapeHtml(displayName)}</strong>
      <small class="shopping-item-meta">${escapeHtml(metaBits.join(" · "))}</small></span>
    <span class="extra-qty"><button type="button" data-extra-minus="${extra.id}">−</button><b>${extra.qty}</b><button type="button" data-extra-plus="${extra.id}">+</button></span>
    <span class="shopping-item-price"><strong>${priceText}</strong>${unitNote}</span>
    <button type="button" class="extra-remove" data-extra-remove="${extra.id}" aria-label="Ta bort">×</button>
  </div>`;
}

function renderExtraItems(chain) {
  const section = $("extraItemsSection");
  if (!section) return;
  section.hidden = !state.extraItems.length;
  $("weekListTitle").hidden = !state.extraItems.length;
  if (!state.extraItems.length) return;
  $("extraItemsList").innerHTML = state.extraItems.map(extra => extraRowMarkup(extra, chain)).join("");
  section.querySelectorAll("[data-extra-check]").forEach(el => el.addEventListener("change", () => {
    state.extraItems = state.extraItems.map(e => e.id === el.dataset.extraCheck ? { ...e, checked: el.checked } : e);
    saveState();
    // Utan omritning fick raden aldrig sin checked-stil och "Allt handlat"
    // utvärderades inte när sista extra-varan bockades av.
    renderBasket();
  }));
  section.querySelectorAll("[data-extra-plus]").forEach(el => el.addEventListener("click", () => {
    const current = state.extraItems.find(e => e.id === el.dataset.extraPlus);
    state.extraItems = setQty(state.extraItems, el.dataset.extraPlus, (current?.qty || 1) + 1);
    saveState(); renderBasket();
  }));
  section.querySelectorAll("[data-extra-minus]").forEach(el => el.addEventListener("click", () => {
    const current = state.extraItems.find(e => e.id === el.dataset.extraMinus);
    state.extraItems = setQty(state.extraItems, el.dataset.extraMinus, (current?.qty || 1) - 1);
    saveState(); renderBasket();
  }));
  section.querySelectorAll("[data-extra-remove]").forEach(el => el.addEventListener("click", () => {
    state.extraItems = removeExtra(state.extraItems, el.dataset.extraRemove);
    saveState(); renderBasket();
  }));
  syncExtraMatches(chain);
}

// ---- Butikskorten överst i Handla -------------------------------------------
function storeCardMarkup(entry) {
  const { chain, total, locked, cheapest, active, unavailable } = entry;
  if (locked) {
    return `<button type="button" class="store-card locked" data-store-card-paywall="${escapeHtml(chain)}">
      ${chainMarkMarkup(chain)}<strong>${escapeHtml(chain)}</strong><span>Se pris med Premium</span></button>`;
  }
  if (unavailable) {
    return `<div class="store-card unavailable">${chainMarkMarkup(chain)}<strong>${escapeHtml(chain)}</strong><span>Pris ej tillgängligt – för få varor prissatta</span></div>`;
  }
  // Butiksnamnet när servern vet vilken butik priset gäller ("Willys
  // Älvsjö", inte bara "Willys") - nationell tjänst, användarens butik.
  const storeLabel = entry.storeName && entry.storeName !== chain
    ? `<small class="store-card-store">${escapeHtml(entry.storeName)}</small>` : "";
  // Prisnivån är konsumentens skydd: "Verifierat lokalt pris" eller
  // "<Kedja> referenspris" - servern sätter texten, vi visar den.
  const tierLabel = entry.priceLabel
    ? `<small class="store-card-tier${entry.verified ? " verified" : ""}">${entry.verified ? "✓ " : ""}${escapeHtml(entry.priceLabel)}</small>` : "";
  return `<button type="button" class="store-card ${active ? "active" : ""}" data-store-card="${escapeHtml(chain)}">
    ${chainMarkMarkup(chain)}<strong>${escapeHtml(chain)}</strong>${storeLabel}<span>${money(total)}</span>${tierLabel}${cheapest ? '<em class="store-card-badge">Billigast</em>' : ""}</button>`;
}

function renderStoreCards() {
  const container = $("storeCards");
  if (!container) return;
  const chain = currentPricedChain();
  const priced = Object.values(state.dbChainTotals);
  if (!priced.length && !state.dbLockedChains.length) { container.innerHTML = ""; $("storeSpreadTeaser").hidden = true; return; }
  const cheapestChain = state.dbComparison?.cheapestChain;
  // Only QUALIFIED chains get a total on their card. ICA pricing 3 of 26
  // items produces a "25 kr" that would sort to the top and read as the
  // cheapest shop in town - a number that is true and a message that is
  // false. Unqualified chains keep their card, marked honestly.
  const qualified = priced.filter(result => result.comparable !== false);
  const unqualified = priced.filter(result => result.comparable === false);
  const entries = qualified
    .map(result => ({
      chain: result.chain,
      // Sorteras på SAMMA underlag som serverns Billigast-krona - den
      // kanoniska matkorgen utan extras. Extras i sorteringen lät ett kort
      // utan kronan lägga sig först och motsäga badgen.
      total: result.totalCheckoutCost,
      storeName: result.store?.name || "",
      priceLabel: result.priceLabel || "",
      verified: result.pricingBasis === "VERIFIED",
      cheapest: result.chain === cheapestChain,
      active: result.chain === chain,
    }))
    .sort((a, b) => a.total - b.total);
  unqualified.forEach(result => entries.push({ chain: result.chain, unavailable: true }));
  state.dbLockedChains.forEach(lockedEntry => entries.push(
    // A lock is a promise that Premium shows a price. A chain that is not
    // comparable has no price to show anyone - its card says so instead of
    // selling a padlock with nothing behind it.
    lockedEntry.hasData && lockedEntry.comparable
      ? { chain: lockedEntry.chain, locked: true }
      : { chain: lockedEntry.chain, unavailable: true }));
  // Vad kröningen vilar på: "Billigast enligt aktuella referenspriser"
  // eller "Billigast bland dina valda butiker" - enkelt för konsumenten,
  // och aldrig ett starkare påstående än datan bär.
  const basisLabel = state.dbComparison?.basisLabel;
  // Jämförelsesidan (view-comparison) nås härifrån: veckans kompakta
  // widget är dold på Vecka-skärmen, så utan den här knappen fanns ingen
  // väg till "Exakt jämförelse mellan butikerna" som Premium lovar.
  const comparableCount = entries.filter(entry => !entry.locked && !entry.unavailable).length;
  const compareButton = hasPremium() && comparableCount > 1
    ? `<button type="button" class="store-compare-open store-cards-compare" id="storeCardsCompareBtn">Jämför butiker →</button>` : "";
  container.innerHTML = entries.map(storeCardMarkup).join("")
    + (basisLabel ? `<p class="store-basis">${escapeHtml(basisLabel)}</p>` : "")
    + compareButton;
  $("storeCardsCompareBtn")?.addEventListener("click", () => { renderStoreComparisonPage(selectedRecipes()); setView("comparison"); });
  container.querySelectorAll("[data-store-card]").forEach(card => card.addEventListener("click", () => {
    if (card.dataset.storeCard === chosenStore()) return;
    // switchWeekStore, inte bara state.butik: livepriserna är nyckelsatta på
    // varunamn UTAN kedja, så utan rensning visade raderna förra kedjans
    // produktnamn och kampanjer under nya kedjans kort tills omhämtningen.
    switchWeekStore(card.dataset.storeCard);
  }));
  container.querySelectorAll("[data-store-card-paywall]").forEach(card =>
    card.addEventListener("click", () => openPaywall("all_store_baskets")));
  // Free får veta ATT priserna skiljer sig - beloppet är riktig aritmetik
  // från servern, aldrig påhittat (mask_pricing_for_free).
  const spread = state.dbComparison?.priceSpread;
  const teaser = $("storeSpreadTeaser");
  if (!hasPremium() && spread != null && spread > 1) {
    teaser.textContent = `Priserna skiljer sig med upp till ${money(spread)} mellan butikerna den här veckan.`;
    teaser.hidden = false;
  } else teaser.hidden = true;
}

// Shared by the compact widget (renderStoreComparison) and the full
// Butiksjämförelse page - one computation of "what does this shopping list
// cost at each branch", never two that could quietly disagree.
function computeStoreResults(selected, branches, shoppingItems) {
  return branches.map(branch => {
    // Priority: Matjakt's own price database first (a real checkout cost
    // computed from real products and real pack sizes), then a live text
    // search of the store site, then the flat static estimate. Only the
    // first two are real prices, and only the first knows how many packages
    // you actually have to buy.
    const fromDatabase = databaseResultFor(branch);
    if (fromDatabase) {
      return {
        branch, cost: fromDatabase.totalCheckoutCost, isLive: true, source: "database",
        matched: fromDatabase.realPriceItems, certain: fromDatabase.realPriceItems,
        estimatedItems: fromDatabase.estimatedItems || 0,
        totalItems: fromDatabase.totalItems || shoppingItems.length,
        missingNames: fromDatabase.missingItemNames || [],
        comparable: fromDatabase.comparable !== false,
        savings: fromDatabase.savings,
        updatedAt: fromDatabase.updatedAt,
      };
    }
    const live = state.liveBranchTotals[branchLiveKey(branch)];
    return { branch, cost: live ? live.cost : shoppingListCost(selected, branch), isLive: live != null, source: live ? "live" : "estimate", matched: live?.matched ?? null, certain: live?.certain ?? null, estimatedItems: 0, totalItems: shoppingItems.length, missingNames: [], comparable: false, savings: null, updatedAt: null };
    // Estimates last, always. Their cost exists only so week PLANNING has a
    // number to work with; sorted in among real prices, the flat estimate
    // could headline as "cheapest", which is a claim about a shop built on a
    // figure no shop ever quoted.
  }).sort((a, b) => (a.source === "estimate") - (b.source === "estimate") || a.cost - b.cost);
}
// Three genuinely different things, and calling them all "Live" would
// overstate two of them:
//   database - a real checkout cost from Matjakt's own collected prices,
//              with real package maths. The best number we have, but it is
//              as fresh as the last import, not as of this second.
//   live     - a best-effort text search of the store's site right now.
//   estimate - the flat static figure. Not a price at all.
// A live total that managed to price NOTHING is not a cheap shop, it is an
// absent answer. Seen live: "Pris hos Coop Nianca - ca 0 kr, 0 av 10 varor
// har säkert pris". Showing 0 kr there states a price we do not have, which
// is the same failure the "Billigast" guards exist to prevent - so the row
// says so instead of naming a figure.
function hasUsablePrice(result) {
  return !(result.isLive && result.certain === 0);
}

// cheapestBranch() builds a NEW object ({...branch, avstandKm, recipes,
// total}), so an identity check against a row's own branch never matched and
// every caller silently fell through to "the cheapest row" instead. That is
// why the week view could show "Pris hos ICA Nära Stortorget" while the
// shopping list below it listed Willys products. Compare on a stable
// identity instead: primatKey when both sides have one, otherwise chain plus
// name.
function sameBranch(a, b) {
  if (!a || !b) return false;
  if (a.primatKey && b.primatKey) return a.primatKey === b.primatKey;
  return a.kedja === b.kedja && a.namn === b.namn;
}

// A shopper does not need to know WHERE a price came from - "Live",
// "Riktigt pris", "Uppskattat" are our plumbing, and they were also
// contradicting each other on screen (an ICA row read "Riktigt pris" and
// "Pris saknas" at once). What a shopper needs is how much of their list a
// shop could actually price, which every row now states outright. The
// technical provenance lives in the admin panel.
//
// The one thing still worth flagging is a shop we could NOT price, because
// its number is not a total at all.
function priceSourceBadge(result) {
  return hasUsablePrice(result) ? "" : '<span class="live-badge estimate">Inget pris</span>';
}

function coverageLabel(result) {
  // "certain" (a confident match AND a real price) is the number that
  // actually contributed to result.cost - "matched" alone would overstate
  // coverage now that a confidently-matched product can still have no price
  // (see best_match/calculateLiveShoppingTotal).
  if (result.certain == null) return "";
  const missing = result.totalItems - result.certain;
  if (result.source === "database") {
    // Named, not just counted: "3 utan pris" leaves the user guessing which
    // three, and whether the total is missing something expensive.
    const names = (result.missingNames || []).filter(Boolean);
    const detail = names.length ? ` · saknar ${escapeHtml(names.slice(0, 3).join(", "))}${names.length > 3 ? ` +${names.length - 3}` : ""}` : "";
      const percent = result.totalItems ? Math.round(100 * result.certain / result.totalItems) : 0;
    return `<small class="store-compare-coverage">${result.certain} av ${result.totalItems} varor har pris${missing > 0 ? detail : ""}</small>`;
  }
  return `<small class="store-compare-coverage">${result.certain} av ${result.totalItems} varor har säkert pris${missing > 0 ? ` · ${missing} utan pris` : ""}</small>`;
}
function renderStoreComparison(selected, containerId = "storeCompare") {
  const container = $(containerId);
  if (!container) return;
  const branches = nearbyBranches();
  if (!selected.length || !branches.length) { container.innerHTML = ""; return; }
  const shoppingItems = aggregateShopping(selected);
  const results = computeStoreResults(selected, branches, shoppingItems);
  const premium = hasPremium();
  const anyLive = results.some(r => r.isLive);
  const updatedLabel = anyLive && state.liveUpdatedAt ? `<small class="store-compare-updated">Uppdaterad ${new Date(state.liveUpdatedAt).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" })}</small>` : "";
  if (!premium) {
    // Free tier never claims a store is "cheapest" - without live data for every
    // chain that would just be a guess (see cheapestBranch()'s flat estimate),
    // and showing it as fact is exactly the kind of mismatch users have reported.
    // Show only the price at the store actually in use, plainly labeled.
    const current = results.find(r => sameBranch(r.branch, selectedBranch())) || results[0];
    // A flat estimate is never printed as a store price. While the real
    // fetch is still under way the head says so; if it came back empty the
    // head says that instead. A made-up "ca 512 kr" says neither.
    const stillFetching = databasePricingSync.pending || (!state.dbPricedAt && !state.dbPricingFailedAt);
    const currentPriceText = current.source === "estimate"
      ? `<strong class="price-missing">${stillFetching ? "pris hämtas…" : "pris saknas just nu"}</strong>`
      : hasUsablePrice(current)
        ? `<strong>ca ${money(current.cost)}</strong>`
        : `<strong class="price-missing">Pris saknas</strong>`;
    const currentHeading = !hasUsablePrice(current) && current.source !== "estimate"
      ? "Inga priser hittades hos" : "Pris hos";
    container.innerHTML = `<div class="store-compare"><div class="store-compare-head"><span>${currentHeading} ${escapeHtml(current.branch.namn)}</span>${currentPriceText}${coverageLabel(current)}${updatedLabel}</div>${results.length > 1 ? `<button type="button" class="store-compare-upsell" id="storeCompareUpsell-${containerId}">Se vilken butik som faktiskt är billigast av ${results.length} – med Premium</button>` : ""}</div>`;
    $(`storeCompareUpsell-${containerId}`)?.addEventListener("click", openPremiumPitch);
    // Free: priset kommer ur prisdatabasen. Inga filialanrop - de är
    // Premium och servern nekar dem ändå.
    syncDatabasePricing(shoppingItems);
    return;
  }
  // Sorted by cost, so the lowest number wins the top of this widget - and a
  // chain that priced almost nothing produces the lowest number. Seen live:
  // ICA headlined at "ca 29 kr" with 1 of 17 items priced (6 % coverage),
  // sitting above Willys at 237 kr with 15 of 17. The number was real; the
  // impression that ICA is the cheap shop was not.
  //
  // So a row only counts as a candidate for the headline or the badge when
  // it has a usable price AND enough coverage to mean something. "comparable"
  // is the server's own judgement (see compare_chains), not a second opinion
  // computed here.
  const priceable = results.filter(hasUsablePrice);
  const comparableRows = priceable.filter(r => r.comparable);
  // The headline is the user's own branch when they have one - that is the
  // shop they are actually going to. Otherwise the cheapest row that can
  // carry the claim, and only as a last resort the best-covered row.
  const byCoverage = [...results].sort((a, b) =>
    (b.certain ?? 0) / (b.totalItems || 1) - (a.certain ?? 0) / (a.totalItems || 1));
  // The user's own branch headlines only when it actually has a real price.
  // Seen live: "Uppskattat pris Coop Nian - ca 578 kr" sitting above Willys
  // with 18 of 21 items priced against real products. An estimate must never
  // outrank a real price, whichever branch happens to be selected.
  const selectedRow = results.find(r => sameBranch(r.branch, selectedBranch()));
  const cheapest = (selectedRow && selectedRow.source === "database" && hasUsablePrice(selectedRow) ? selectedRow : null)
    || comparableRows[0] || byCoverage.find(r => r.source === "database" && hasUsablePrice(r))
    || selectedRow || byCoverage[0] || results[0];
  const priciest = comparableRows.length
    ? comparableRows[comparableRows.length - 1]
    : (priceable.length ? priceable[priceable.length - 1] : results[results.length - 1]);
  // A "Billigast" badge is a factual claim, so it needs a comparison that
  // actually holds up. Three things can each make it meaningless:
  //  - the cheapest row is only an estimate (isLive false), so its number
  //    isn't a real price at all;
  //  - every row costs the same, which is what happens when they're all the
  //    same flat estimate - crowning one of several identical numbers is
  //    exactly the "Coop 351 / Willys 351 / ICA 351, one marked cheapest"
  //    problem;
  //  - the cheapest row's live prices cover too little of the list to be
  //    comparable with the row it's being compared against.
  // When any of those hold we show the prices without a badge and without a
  // savings figure, rather than asserting something we can't back up.
  // "Riktiga butiksspecifika priser saknas" was shown even when the cheapest
  // row had 15 of 16 items priced against real products - the prices were
  // not what was missing, a SECOND comparable chain was. The server already
  // knows which of the four blocks applied, so its reason is used rather
  // than a single catch-all sentence that is wrong more often than right.
  const COMPARISON_REASONS = {
    too_few_comparable_chains: "Bara en butik har tillräckligt med aktuella priser för en jämförelse",
    all_totals_identical: "Butikerna landar på samma summa - ingen är billigast",
  };
  const MIN_COVERAGE_FOR_CLAIM = 0.6;
  const coverageOf = r => (r.certain == null || !r.totalItems) ? 0 : r.certain / r.totalItems;
  const pricesDiffer = comparableRows.some(r => Math.abs(r.cost - cheapest.cost) > 0.5);
  // When the cheapest row came from Matjakt's own price database, the SERVER
  // already decided whether a cheapest chain may be named - it applies the
  // same guards plus two this side can't see (a chain with zero real matches
  // totalling 0 kr, and data too stale to compare against fresh data). Two
  // independent verdicts on the same question would eventually disagree, and
  // the disagreement would show up as a badge the totals don't support, so
  // there is one authority: the server's.
  // The row that headlines and the row that is CHEAPEST are different
  // questions. The headline is the shop the user is going to; the badge
  // belongs on whichever shop actually won. Tying the badge to the headline
  // row meant that when the user's own branch was not the cheapest, the
  // comparison vanished entirely and the screen claimed "riktiga
  // butiksspecifika priser saknas" - with two shops on it at 94 % coverage.
  const winner = state.dbComparison?.cheapestChain
    ? comparableRows.find(r => r.branch.kedja === state.dbComparison.cheapestChain)
    : null;
  // Cheapest of one is not a comparison. Two qualified shops is the minimum
  // for the word to mean anything.
  const enoughToCompare = comparableRows.length >= 2;
  const comparisonIsReal = cheapest.source === "database"
    ? enoughToCompare && Boolean(winner) && pricesDiffer
    : cheapest.isLive && pricesDiffer && coverageOf(cheapest) >= MIN_COVERAGE_FOR_CLAIM;
  const savings = winner ? (state.dbComparison?.savings ?? 0) : priciest.cost - cheapest.cost;
  const savingsAreReal = comparisonIsReal && savings > 1;
  const pinned = pinnedBranchMatch();
  // Only a Primat-sourced branch (has a primatKey) can be individually
  // targeted - a scrape-sourced fallback branch has nothing concrete to pin
  // a price search to, so those rows render as plain, non-interactive text
  // instead of a button that would do nothing when pressed.
  // ONLY shops that qualify for a real price comparison are listed. A shop
  // we cannot price is not a cheap alternative - and shown in the same list
  // as real totals, "uppskattat 300 kr" reads as a competing offer. Why a
  // shop is absent (Coop has no public API, ICA is rate-limited, a chain's
  // coverage is too thin) is engineering detail and lives in the admin
  // panel, not among a shopper's price options.
  const shown = results.filter(r => r.comparable && hasUsablePrice(r));
  const list = shown.length < 2 ? "" : `<div class="store-compare-list">${shown.map((r, index) => {
    const isPinned = pinned && r.branch.primatKey && r.branch.primatKey === pinned.primatKey;
    const isCheapest = comparisonIsReal && winner
      && r.branch.kedja === winner.branch.kedja && r.cost === winner.cost;
    const tag = `${isCheapest ? "cheapest" : ""} ${isPinned ? "pinned" : ""}`.trim();
    // Coverage on every row: without it "29 kr" and "237 kr" look like two
    // prices for the same basket, when one of them is a basket with one item
    // in it.
    const rowCoverage = r.certain != null && r.totalItems
      ? `<small class="store-compare-row-coverage">${r.certain}/${r.totalItems} varor</small>` : "";
    const inner = `<span>${escapeHtml(r.branch.namn)}${isCheapest ? '<span class="live-badge cheapest-badge">Billigast</span>' : ""}${isPinned ? '<span class="live-badge pinned">Vald</span>' : ""}${priceSourceBadge(r)}${rowCoverage}</span><strong${hasUsablePrice(r) ? "" : ' class="price-missing"'}>${hasUsablePrice(r) ? money(r.cost) : "Pris saknas"}</strong>`;
    return r.branch.primatKey
      ? `<button type="button" class="store-compare-row ${tag}" data-pick-branch="${index}">${inner}</button>`
      : `<div class="store-compare-row ${tag} not-pickable">${inner}</div>`;
  }).join("")}</div>`;
  // Same rule as the free tier: the head never prints the flat estimate as
  // a price. "Uppskattat pris Coop Nian - ca 578 kr" is the exact banner the
  // no-fabricated-totals rule exists to kill.
  const headIsEstimate = cheapest.source === "estimate";
  const headFetching = headIsEstimate && (databasePricingSync.pending || (!state.dbPricedAt && !state.dbPricingFailedAt));
  container.innerHTML = `<div class="store-compare"><div class="store-compare-head"><span>${comparisonIsReal && winner && winner.branch.kedja === cheapest.branch.kedja ? "Lägst pris" : "Pris hos"}</span><strong>${escapeHtml(cheapest.branch.namn)}${headIsEstimate ? ` · ${headFetching ? "pris hämtas…" : "pris saknas just nu"}` : ` · ca ${money(cheapest.cost)}`}</strong>${savingsAreReal ? (winner && winner.branch.kedja !== cheapest.branch.kedja
      ? `<small>Billigast: ${escapeHtml(winner.branch.namn)} ${money(winner.cost)} · du sparar ${money(savings)}</small>`
      : `<small>Du sparar ${money(savings)}${state.dbComparison?.priciestTotal ? ` · ${Math.round(100 * savings / state.dbComparison.priciestTotal)} % billigare än dyraste jämförbara butik` : ""}</small>`)
    : !comparisonIsReal && shown.length > 1 ? `<small>${escapeHtml(cheapest.source === "database" && state.dbComparison?.reason ? (COMPARISON_REASONS[state.dbComparison.reason] || "Underlaget räcker inte för en jämförelse") : "Riktiga butiksspecifika priser saknas för en jämförelse")}</small>` : ""}${coverageLabel(cheapest)}${updatedLabel}</div>${list}${pinned ? `<button type="button" class="store-compare-unpin" id="storeCompareUnpin-${containerId}">Välj automatiskt istället</button>` : ""}${results.length > 1 ? `<button type="button" class="store-compare-open" id="storeCompareOpenBtn-${containerId}">Jämför butiker →</button>` : ""}</div>`;
  $(`storeCompareOpenBtn-${containerId}`)?.addEventListener("click", () => { renderStoreComparisonPage(selected); setView("comparison"); });
  container.querySelectorAll("[data-pick-branch]").forEach(button => button.addEventListener("click", () => {
    // Indexes `shown`, not `results` - they differ whenever a shop was left
    // out of the comparison, and indexing the wrong array pins a different
    // store than the one tapped.
    const branch = shown[Number(button.dataset.pickBranch)].branch;
    const alreadyPinned = state.pinnedBranch && state.pinnedBranch.primatKey === branch.primatKey;
    state.pinnedBranch = alreadyPinned ? null : { kedja: branch.kedja, namn: branch.namn, primatKey: branch.primatKey, externalStoreId: branch.externalStoreId || "" };
    state.butik = branch.kedja;
    state.livePriser = {};
    state.liveBranchTotals = {};
    saveState();
    render();
    renderCampaignSection();
    syncSettingsInputs();
  }));
  $(`storeCompareUnpin-${containerId}`)?.addEventListener("click", () => {
    state.pinnedBranch = null;
    state.livePriser = {};
    state.liveBranchTotals = {};
    saveState();
    render();
    renderCampaignSection();
    syncSettingsInputs();
  });
  syncDatabasePricing(shoppingItems);
  syncBranchComparison(shoppingItems, branches);
}
// Real, approximate brand colors for chain-name text - no logo assets exist
// in this project and Primat's API doesn't supply any (checked directly
// against its response fields before building this), so a real logo would
// have to come from scraping/hotlinking the chains' own sites, which this
// app deliberately never does. Styled text in the chain's own color is the
// honest stand-in.
// Known brand colours. A chain that is not listed is not excluded from
// anything - it just draws in the app's own accent colour. The store
// comparison is driven by the DATA, never by this map.
const CHAIN_COLORS = { ICA: "#E2231A", Willys: "#171717", Coop: "#00953B", "Hemköp": "#E4032E", "City Gross": "#C8102E" };
// Kedjemärke i kedjans färg - igenkänning utan att skeppa deras logotyper
// (varumärken). Byts mot riktiga loggor i assets/chains/ om Adam tar in dem.
function chainMarkMarkup(chain, size = "") {
  const color = CHAIN_COLORS[chain] || "#146c43";
  const label = chain === "ICA" ? "ICA" : chain === "City Gross" ? "CG" : (chain || "?").slice(0, 1).toUpperCase();
  return `<span class="chain-mark${size ? ` chain-mark-${size}` : ""}" style="background:${color}" aria-hidden="true">${escapeHtml(label)}</span>`;
}
function comparisonStoreRowMarkup(result, isCheapest, priciestCost) {
  // null means "no comparable shop to measure against", which is different
  // from "the saving is zero".
  // Only the winner gets a "du sparar" figure. Shown on every row that is
  // not the dearest, it reads as though each shop were a deal - three rows
  // all claiming a saving against each other is not information.
  const savings = priciestCost == null || !result.comparable || !isCheapest
    ? null : priciestCost - result.cost;
  const color = CHAIN_COLORS[result.branch.kedja] || "var(--primary)";
  // A store whose live match rate is too thin to trust isn't allowed to
  // just show a partial sum as if it were the real total - see
  // branchLiveTotal's matched count. An estimate (matched === null) always
  // covers every item by construction, so it's never held to this bar.
  const coverageOk = hasUsablePrice(result) && (result.comparable || result.source !== "database");
  const coverageNote = result.source === "database"
    ? `${result.matched} av ${result.totalItems} varor har aktuellt pris`
    : result.matched != null ? `${result.matched} av ${result.totalItems} varor` : "Pris saknas";
  // Only a database-priced chain has a real shopping list behind it to open.
  // The card has always shown a "›" affordance; making a row clickable that
  // leads nowhere is worse than showing it as plain text.
  const openable = result.source === "database";
  const tag = openable ? "button" : "div";
  const attrs = openable
    ? ` type="button" data-open-chain="${escapeHtml(result.branch.kedja)}"`
    : "";
  return `<${tag} class="comparison-store-card ${isCheapest && coverageOk ? "cheapest" : ""}${openable ? " openable" : ""}"${attrs}><div class="comparison-store-main">${chainMarkMarkup(result.branch.kedja, "sm")}<span class="comparison-store-name" style="color:${color}">${escapeHtml(result.branch.kedja)}</span><small class="comparison-store-coverage">${coverageNote}</small></div><div class="comparison-store-price">${isCheapest && coverageOk ? '<span class="comparison-billigast">Billigast</span>' : ""}${coverageOk ? `<strong>${money(result.cost)}</strong>${savings != null && savings > 1 ? `<small class="comparison-savings">Du sparar ${money(savings)}</small>` : ""}` : `<small class="comparison-savings">${!hasUsablePrice(result) ? "Inga priser hittades" : "För få aktuella priser för en jämförelse"}</small>`}</div>${openable ? '<span class="comparison-store-arrow" aria-hidden="true">›</span>' : ""}</${tag}>`;
}
// =============================================================================
// ONE CHAIN'S REAL SHOPPING LIST
// =============================================================================
// Opened by tapping a store card. Everything shown is fetched fresh from the
// pricing API for that chain rather than reused from the week view's cached
// per-chain totals, so the list can never show products that belong to a
// different total than the one in its own header.
async function openChainShoppingList(chain, branch = null) {
  const selected = selectedRecipes();
  const shoppingItems = aggregateShopping(selected);
  const body = $("chainListBody");
  $("chainListTitle").textContent = `Inköpslista · ${chain}`;
  body.innerHTML = `<p class="live-loading">Hämtar ${escapeHtml(chain)}s priser…</p>`;
  setView("chainlist");
  try {
    const response = await fetch(pricingListApiUrl(), {
      method: "POST",
      headers: pricingHeaders(),
      body: JSON.stringify({ chain, ...weekPricingBody(shoppingItems) }),
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    body.innerHTML = chainShoppingListMarkup(await response.json(), branch);
    body.querySelectorAll("[data-shopping]").forEach(input => input.addEventListener("change", () => {
      // Samma fyra statusar som Handla, inte en egen kryssruta: en avbockning
      // här ÄR ett köp, och ska hamna i skafferiet på samma villkor.
      const name = input.dataset.shopping;
      setItemStatus(name, input.checked ? PURCHASED : NEED_TO_BUY,
                    { addToPantry: input.checked, location: suggestedLocationFor(name),
                      });
      renderBasket();
    }));
  } catch {
    body.innerHTML = `<p class="live-loading">Kunde inte hämta ${escapeHtml(chain)}s priser just nu.</p>`;
  }
}

function priceStatusLabel(status) {
  if (status === "current") return '<span class="price-status current">Aktuellt pris</span>';
  if (status === "estimated") return '<span class="price-status estimated">Uppskattat antal</span>';
  return '<span class="price-status missing">Pris saknas</span>';
}

// Orsakskoderna från backend (comparability_reasons i grocery/pricing.py),
// en mening var. Åldern nämns först när båda gäller: den förklarar varför
// summan inte går att lita på ens där varorna FINNS.
const COMPARABILITY_WARNINGS = {
  too_old: "Priserna för den här butiken är för gamla för att summan ska gå att jämföra med en annan butik.",
  low_coverage: "För få av varorna har aktuellt pris för att den här summan ska gå att jämföra med en annan butik.",
  no_real_prices: "Ingen av varorna har ett säkert pris hos den här butiken, så summan går inte att jämföra.",
};

function comparabilityWarning(reasons) {
  const list = Array.isArray(reasons) ? reasons : [];
  for (const code of ["no_real_prices", "too_old", "low_coverage"]) {
    if (list.includes(code)) return COMPARABILITY_WARNINGS[code];
  }
  return COMPARABILITY_WARNINGS.low_coverage;
}

function chainShoppingListMarkup(data, branch = null) {
  if (data.error === "no_data_for_chain") {
    return `<p class="live-loading">Matjakt har ingen prisdata för ${escapeHtml(data.chain || "den här kedjan")} ännu.</p>`;
  }
  const updated = data.updatedAt
    ? `Uppdaterad ${new Date(data.updatedAt * 1000).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" })}`
    : "Uppdateringstid okänd";
  const savings = data.savings != null && data.savings > 1
    ? `<span class="chain-list-savings">Du sparar ${money(data.savings)} mot dyraste jämförbara butik</span>` : "";
  // Said plainly rather than left for the user to infer from a total that
  // looks suspiciously low - och med RÄTT anledning. Flaggan comparable slog
  // förr ihop täckning och ålder i ett enda nej, så en kedja vars priser var
  // för GAMLA fick ändå texten "för få av varorna har aktuellt pris".
  // Orsakskoderna kommer nu med i svaret (comparability_reasons i pricing.py).
  const warning = !data.comparable
    ? `<p class="chain-list-warning">${escapeHtml(comparabilityWarning(data.comparableReasons))}</p>` : "";
  // Summed from the rows actually rendered below, not taken from the payload.
  // The two agree today (the server builds the total the same way), and this
  // guarantees they keep agreeing: a header that quietly disagreed with its
  // own list is the exact failure this screen exists to remove.
  const total = (data.items || [])
    .filter(item => item.priceStatus !== "missing")
    .reduce((sum, item) => sum + (Number(item.totalCost) || 0), 0);
  const coverage = data.totalItems ? Math.round(100 * data.realPriceItems / data.totalItems) : 0;
  // Which shop this is has to survive scrolling: on a phone the list is far
  // longer than the screen, and a shopper standing in one shop reading
  // another shop's prices is the worst outcome this screen can produce.
  const distance = branch?.avstandKm != null ? `${branch.avstandKm} km bort` : "";
  const storeName = branch?.namn || data.store?.name || data.chain || "";
  // Where the prices actually come from. Only worth saying when it is not
  // the shop whose name is at the top: for Willys and Hemköp the price is
  // verified national, so any branch pays it. For City Gross and ICA it is
  // not - a price collected in Gävle under a Stockholm branch's name would
  // be a quiet lie, so the screen says which store it was collected in.
  const pricedStore = data.store?.name;
  const perStore = data.pricingScope === "store";
  const pricedElsewhere = perStore && pricedStore && branch?.namn && pricedStore !== branch.namn
    ? `<p class="chain-list-warning">Priserna är hämtade i ${escapeHtml(pricedStore)}. ${escapeHtml(data.chain)} sätter priser per butik, så ${escapeHtml(branch.namn)} kan skilja sig.</p>`
    : "";
  const sticky = `<div class="chain-list-sticky"><strong>${escapeHtml(storeName)}</strong><span>${money(total)} · ${data.realPriceItems}/${data.totalItems} varor</span></div>`;
  const head = sticky + `<div class="chain-list-head"><h2>${escapeHtml(storeName)}</h2><small>${escapeHtml([data.chain, distance].filter(Boolean).join(" · "))}</small>${pricedElsewhere}<div class="chain-list-total"><span>Total kassakostnad</span><strong>${money(total)}</strong></div><div class="chain-list-meta"><span>${data.realPriceItems} av ${data.totalItems} varor har pris</span>${data.estimatedItems ? `<span>${data.estimatedItems} med uppskattat antal</span>` : ""}${data.missingItems ? `<span>${data.missingItems} utan pris</span>` : ""}<span>${escapeHtml(updated)}</span><button type="button" class="report-price-btn" data-report-price>Ser något fel ut?</button>${savings}</div>${warning}</div>`;

  const rows = (data.items || []).map(item => {
    const checked = itemStatus(item.ingredient) !== NEED_TO_BUY;
    const missing = item.priceStatus === "missing";
    const photo = item.imageUrl
      ? `<img class="chain-item-photo" src="${escapeHtml(safeHttpUrl(item.imageUrl) || "")}" alt="" loading="lazy">`
      : `<span class="chain-item-photo" aria-hidden="true"></span>`;
    // What the recipe asks for, and what that means at the till: how many
    // whole packages of THIS product you have to put in the basket.
    const need = item.neededAmount != null
      ? `Behövs ${formatAmount(item.neededAmount, item.neededUnit || item.unit)} ${escapeHtml(item.neededUnit || "")}` : "";
    const pack = item.packageSize ? `Förpackning ${escapeHtml(item.packageSize)}` : "";
    const count = item.packages ? `${item.packages} ${item.packages === 1 ? "paket" : "paket"}` : "";
    // A campaign price is only a discount when it is genuinely below the
    // ordinary price; otherwise showing both would invent one.
    const onCampaign = item.campaignPrice != null && item.regularPrice != null
      && item.campaignPrice < item.regularPrice;
    // unitPrice is what one package actually costs today (campaign price when
    // one is running, otherwise the ordinary price) - it is what totalCost is
    // built from, so showing it makes the arithmetic checkable: 2 x 12,20 =
    // 24,40. comparisonPrice is the shelf's kr/kg, a different number
    // entirely, and labelling either as the other would mislead.
    const perUnit = item.unitPrice != null && item.packages > 1
      ? `<small class="chain-item-compare">${item.packages} × ${money(item.unitPrice)}</small>` : "";
    const priceBlock = missing
      ? `<small class="chain-item-compare">Pris saknas</small>`
      : item.totalCost == null
      ? `<small class="chain-item-compare">Antal osäkert · ${item.unitPrice != null ? `${money(item.unitPrice)}/förp` : "pris per förpackning okänt"}</small>`
      : `<strong>${money(item.totalCost)}</strong>${perUnit}${onCampaign
          ? `<small class="chain-item-campaign">Kampanj ${money(item.campaignPrice)}/st</small><small class="chain-item-was">Ord. ${money(item.regularPrice)}/st</small>`
          : item.regularPrice != null ? `<small class="chain-item-compare">${money(item.regularPrice)}/st</small>` : ""}${
          item.comparisonPrice != null ? `<small class="chain-item-compare">Jmf ${money(item.comparisonPrice)}</small>` : ""}`;
    const title = missing ? escapeHtml(item.ingredient) : escapeHtml(item.productName || item.ingredient);
    const sub = missing
      ? `Ingen produkt kunde matchas för "${escapeHtml(item.ingredient)}"`
      : escapeHtml([item.brand, pack, count].filter(Boolean).join(" · "));
    return `<label class="chain-item ${missing ? "is-missing" : ""}"><input type="checkbox" data-shopping="${escapeHtml(item.ingredient)}" ${checked ? "checked" : ""}>${photo}<span class="chain-item-info"><strong>${title}</strong><small class="chain-item-need">${need}</small><small>${sub}</small>${priceStatusLabel(item.priceStatus)}</span><span class="chain-item-prices">${priceBlock}</span></label>`;
  }).join("");

  return head + (rows || `<p class="live-loading">Listan är tom.</p>`);
}

// Whole numbers stay whole ("2 st", not "2.0 st"); fractions keep one decimal.
function formatAmount(value, unit) {
  const number = Number(value) || 0;
  // "Behöver 0.5 st citron" är sann i grytan men värdelös i butiken - hela
  // styck avrundas uppåt, precis som amountLabel gör.
  if ((unit || "").toLowerCase() === "st" || (unit || "").toLowerCase() === "förp") {
    return String(Math.max(1, Math.ceil(number)));
  }
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

function renderStoreComparisonPage(selected) {
  const branches = nearbyBranches();
  const shoppingItems = aggregateShopping(selected);
  // computeStoreResults returns one row per physical branch, each with its
  // own genuinely distinct price (see branchLiveKey) - that's exactly what
  // the compact widget's pin-a-specific-branch feature needs, but this page
  // compares chains, not addresses. computeStoreResults already sorts by
  // cost, so keeping only the first occurrence per chain here means "each
  // chain's cheapest nearby branch" - a real comparison now, not a
  // coincidence of every branch sharing one fake chain-wide price.
  const seenChains = new Set();
  const results = computeStoreResults(selected, branches, shoppingItems).filter(r => {
    if (seenChains.has(r.branch.kedja)) return false;
    seenChains.add(r.branch.kedja);
    return true;
  });
  if (!results.length) { $("comparisonStoreList").innerHTML = `<p class="live-loading">Ingen data att jämföra ännu.</p>`; $("comparisonItemCount").textContent = "0 varor"; $("comparisonCampaignCard").hidden = true; $("comparisonUpdated").textContent = ""; return; }
  // The same rule as everywhere else: only shops with enough REAL coverage
  // take part. Two things were wrong on this page - Hemköp at 13 of 16
  // (81 %, under the threshold) was being priced and compared, and every
  // real shop showed "Du sparar 85 kr" measured against COOP'S ESTIMATE of
  // 300 kr. Saving money against a number we made up is not a saving.
  const validResults = results.filter(r => r.comparable && hasUsablePrice(r));
  const cheapest = (validResults.length ? validResults : results)[0];
  // Priciest is the dearest COMPARABLE shop, never an estimate.
  const priciest = validResults.length ? validResults[validResults.length - 1] : null;
  // Counted against the RESULT'S own totalItems, never against the client
  // aggregate: the server splits a mixed-unit line in two, so its item count
  // can differ from ours - which printed the impossible "21 av 20 varor".
  const bestResult = results.reduce((best, r) =>
    (r.matched ?? 0) > (best?.matched ?? -1) ? r : best, null);
  $("comparisonItemCount").textContent = bestResult?.matched
    ? `${bestResult.matched} av ${bestResult.totalItems} varor`
    : `${shoppingItems.length} varor`;
  // A saving is only shown when there are at least two comparable shops -
  // one shop cannot be cheaper than itself.
  const priciestCost = validResults.length > 1 ? priciest.cost : null;
  // Same rule as the compact widget: a shopper's list of price alternatives
  // contains only shops that actually have prices to compare.
  if (!validResults.length) {
    $("comparisonStoreList").innerHTML =
      `<p class="live-loading">Ingen butik i närheten har tillräckligt med aktuella priser för en jämförelse ännu.</p>`;
  } else {
    $("comparisonStoreList").innerHTML = validResults
      .map(r => comparisonStoreRowMarkup(r, validResults.length > 1 && r === cheapest, priciestCost))
      .join("");
  }
  document.querySelectorAll("[data-open-chain]").forEach(card =>
    card.addEventListener("click", () => {
      const row = validResults.find(r => r.branch.kedja === card.dataset.openChain);
      openChainShoppingList(card.dataset.openChain, row?.branch || null);
    }));
  // "vald butik" - the chain actually in use right now, not necessarily the
  // cheapest one shown above, so this reflects what the user would really
  // save with the choice they've already made.
  // Bara JÄMFÖRBARA butiker får bära besparingen. Den aktiva kedjan kan
  // sakna priser helt (raden blir en statisk uppskattning) - att mäta en
  // riktig totalsumma mot den uppskattningen gav "Du sparar 220 kr med
  // Coop" för en butik som inte hade ett enda pris. Hittas den aktiva
  // kedjan inte bland de jämförbara faller vi tillbaka på den billigaste
  // jämförbara, och priciestCost är null när färre än två kan jämföras.
  const activeResult = validResults.find(r => r.branch.kedja === chosenStore()) || validResults[0] || null;
  const activeSavings = priciestCost != null && activeResult ? priciestCost - activeResult.cost : 0;
  $("comparisonCampaignCard").hidden = !(activeSavings > 1);
  if (activeSavings > 1) {
    $("comparisonCampaignText").textContent = `Du sparar ${money(activeSavings)} med ${activeResult.branch.kedja}`;
  }
  const pricedStamp = state.dbPricedAt || state.liveUpdatedAt;
  $("comparisonUpdated").textContent = pricedStamp
    ? `Priserna uppdaterades ${new Date(pricedStamp).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" })}`
    : "Priser hämtas…";
}

// Kategorierna bor i src/services/categories.js så att Handla, Skafferi
// och veckan alla sorterar likadant - se §31 (butiksordning).
const itemCategory = name => categoryFor(name, databaseItemFor(name)?.category);
// Bundled locally (no network fetch) so every shopping item always shows something
// relevant even offline or before a real product photo has loaded - never a bare
// letter or a broken image. One simple, on-brand line icon per category; picking
// the wrong product's photo to fill the space would be worse than an icon, so this
// is deliberately generic rather than a guess.
const CATEGORY_ICONS = {
  "Frukt & grönt": '<path d="M12 9c-3 0-5.5 2.7-5.5 6.2C6.5 19 8.8 21 11 21c.7 0 1-.3 1-.3s.3.3 1 .3c2.2 0 4.5-2 4.5-5.8C17.5 11.7 15 9 12 9Z"/><path d="M12 9c0-2 1.2-3.3 2.8-3.6"/>',
  Mejeri: '<path d="M10 3h4v3l2 2v11a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V8l2-2V3Z"/><path d="M9 13h6"/>',
  "Kött & fisk": '<path d="M4 12c4-5 10-6 15-3-1 1-1 5 0 6-5 3-11 2-15-3Z"/><path d="M17 9l3-2v10l-3-2"/>',
  Skafferi: '<path d="M7 8h10v11a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V8Z"/><path d="M9 8V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3M8 12h8"/>',
  "Bröd": '<path d="M5 11a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2Z"/><path d="M9 8V6m3 2V6m3 2V6"/>',
  Frys: '<path d="M12 3v18M4.5 7.5l15 9M19.5 7.5l-15 9"/>',
  Övrigt: '<path d="M6 8h12l-1 12a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L6 8ZM9 8V6a3 3 0 0 1 6 0v2"/>',
};
function categoryIconMarkup(category) {
  return `<span class="shopping-item-image placeholder" aria-hidden="true"><svg viewBox="0 0 24 24">${CATEGORY_ICONS[category] || CATEGORY_ICONS["Övrigt"]}</svg></span>`;
}
function attributionMarkup(usesPrimat, usesOff) {
  const parts = [];
  if (usesPrimat) parts.push('Prisdata från <a href="https://primat.nu" target="_blank" rel="noopener">primat.nu</a>');
  if (usesOff) parts.push('Bilddata från <a href="https://openfoodfacts.org" target="_blank" rel="noopener">Open Food Facts</a> (CC BY-SA)');
  return parts.join(" · ");
}
function renderAttribution(shoppingItems) {
  // Both Primat and Open Food Facts require visible attribution wherever
  // their data/images actually appear, not unconditionally - shown only for
  // whichever source(s) are actually behind something currently on screen.
  const usesPrimat = shoppingItems.some(item => state.livePriser[item.namn]?.kalla === "primat");
  const usesOff = shoppingItems.some(item => state.livePriser[item.namn]?.bildKalla === "openfoodfacts");
  $("primatAttribution").innerHTML = attributionMarkup(usesPrimat, usesOff);
  $("primatAttribution").hidden = !(usesPrimat || usesOff);
}
// One shopping line as a real product card. Everything shown here is a fact
// from the price database - the product name, its pack size, how many
// packages this week's amount actually needs, and what that costs. Nothing
// is estimated, so nothing here carries an "Uppskattat" badge.
// ---------------------------------------------------------------------------
// HANDLA: EN RAD
//
// Frågorna en rad ska besvara på ett ögonkast, i den ordningen (§30):
//   Vad är varan?  Hur mycket behöver vi?  Har vi den?  Vad kostar den?
//   Var köps den?
//
// Bilden får aldrig ta över. Den är 44 px, ligger till vänster och ersätts
// av en neutral kategorisymbol när vi inte har en bild vi får visa (§9) -
// aldrig av en annan produkts bild för att fylla tomrummet.
//
// Produktnamn, märke och förpackning skrivs BARA ut när de kommer från en
// riktig matchning i prisdatabasen. En osäker matchning blir inte säker av
// att den får en bild (§35).
// ---------------------------------------------------------------------------

const AT_HOME_ICON = '<svg viewBox="0 0 24 24"><path d="m4 11 8-6 8 6v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1Z"/></svg>';
const BOUGHT_ICON = '<svg viewBox="0 0 24 24"><path d="m5 13 4 4L19 7"/></svg>';

function shoppingActionsMarkup(name, status) {
  if (status === NEED_TO_BUY) {
    return `<div class="shopping-actions">`
      + `<button type="button" class="shopping-action" data-at-home="${escapeHtml(name)}">${AT_HOME_ICON}<span>Har hemma</span></button>`
      + `<button type="button" class="shopping-action buy" data-bought="${escapeHtml(name)}">${BOUGHT_ICON}<span>Köpt</span></button>`
      + `</div>`;
  }
  const label = status === PURCHASED ? "Köpt" : "Finns hemma";
  return `<div class="shopping-actions handled"><span class="shopping-handled-label">${label}</span>`
    + `<button type="button" class="shopping-action" data-need="${escapeHtml(name)}">Behöver köpa</button></div>`;
}

// Vad raden ska säga om mängd. "2 st" ensamt svarade varken på vad veckan
// behöver eller vad man ska lägga i korgen - båda står här.
function quantityTextFor(item, match, status = NEED_TO_BUY) {
  if (!match) {
    const needed = Math.max(0, item.total - (pantryForPricing()[item.namn] || 0));
    if (needed > 0) return `Behöver ${amountLabel(needed, item.unit)}`;
    // Skafferiavdraget är en SLUTSATS; att användaren tryckt "behöver köpa"
    // är ett BESKED. Beskedet vinner - annars stod det "Finns hemma" på en
    // rad personen just sagt att de måste handla.
    return status === NEED_TO_BUY ? `Behöver ${amountLabel(item.total, item.unit)}` : "Finns hemma";
  }
  const packageText = match.packageSize && match.packageSize !== "1 st" ? match.packageSize : "";
  const needed = match.neededAmount ? `Behöver ${amountLabel(match.neededAmount, match.neededUnit)}` : "";
  const count = match.packages > 1
    ? `${match.packages} × ${packageText || "förpackning"}`
    : (packageText ? `1 × ${packageText}` : "");
  return [needed, count].filter(Boolean).join(" · ");
}

function shoppingRowMarkup(item) {
  const match = databaseItemFor(item.namn);
  const status = itemStatus(item.namn);
  const category = categoryFor(item.namn, match?.category);
  const live = state.livePriser[item.namn];
  // BILDEN: bara en bild vi faktiskt har rätt att visa för just den här
  // produkten. Saknas den ritas kategorisymbolen - aldrig någon annans bild.
  const imageUrl = match?.imageUrl || live?.bild;
  const photo = imageUrl
    ? `<img class="shopping-item-image has-image" src="${escapeHtml(safeHttpUrl(imageUrl) || "")}" alt="" loading="lazy" decoding="async">`
    : categoryIconMarkup(category);
  const title = match ? match.productName : (live ? live.produktnamn : item.namn);
  const quantity = quantityTextFor(item, match, status);
  const brand = match ? match.brand : (live ? live.markeOchStorlek : "");
  const meta = escapeHtml([brand, quantity].filter(Boolean).join(" · "));
  // Priset: bara ett riktigt pris får skrivas ut. Ett statiskt katalogpris
  // är en gissning i en kolumn av fakta och skrivs aldrig.
  const dbSyncPending = databasePricingSync.pending || (!state.dbPricedAt && !state.dbPricingFailedAt);
  const priceMissing = live && live.pris_kr == null;
  // SAMMA räkning som totalsumman (packagesFor), inte en egen kopia: kopian
  // räknade veckans behov i det VISADE måttet (6 dl) mot förpackningens
  // basmått (200 ml) och kom fram till ett paket i stället för tre - raden
  // sa "Behöver 6 dl" och visade priset för en burk. null = antal osäkert
  // (vikt/volym utan paketinfo), 0 = allt finns redan hemma.
  const packages = match ? match.packages : packagesFor(item, pantryForPricing());
  const stillFetching = !match && !live && (dbSyncPending || (livePriceSync.loading && VALID_CHAINS.includes(chosenStore())));
  const price = match && match.totalCost != null ? money(match.totalCost)
    : priceMissing ? "Pris saknas"
      : live ? (packages == null ? "" : money(live.pris_kr * packages))
        : stillFetching ? "" : "Pris saknas";
  const store = match ? (state.dbChainTotals[currentPricedChain()]?.chain || currentPricedChain() || "") : "";
  const onCampaign = match && match.campaignPrice != null && match.regularPrice != null
    && match.campaignPrice < match.regularPrice;
  const campaign = onCampaign
    ? `<small class="shopping-item-campaign">Kampanj ${money(match.campaignPrice)} (ord. ${money(match.regularPrice)})</small>`
    : (live?.kampanj?.text ? `<small class="shopping-item-campaign">${escapeHtml(live.kampanj.text)}</small>` : "");
  // Flaggad, inte gömd: när receptets enhet inte går att räkna om mot
  // förpackningens gissar motorn "en förpackning". Det är en gissning om
  // ANTAL, och den som står i affären är den som kan avgöra.
  // Antalet är osäkert både när prisdatabasen säger det och när ett livepris
  // saknar paketinfo för en vikt-/volymvara - i båda fallen ska raden säga
  // det i stället för att visa ett tal vi inte kan stå för.
  const inexact = match?.priceStatus === "estimated" || (!match && live && packages == null)
    ? '<small class="item-status estimated">Antal osäkert</small>'
    : (stillFetching ? '<small class="item-status loading">pris hämtas…</small>' : "");
  const comparePrice = match?.comparisonPrice != null
    ? `<small class="shopping-item-compare">${money(match.comparisonPrice)}/${/l|ml|dl/.test(match.packageUnit || "") ? "l" : "kg"}</small>` : "";
  return `<article class="shopping-item status-${status.toLowerCase()}">`
    + `<div class="shopping-item-main">${photo}`
    + `<span class="shopping-item-info"><strong>${escapeHtml(title)}</strong>`
    + `<small class="shopping-item-meta">${meta}</small>${campaign}</span>`
    + `<span class="shopping-item-price"><strong class="${price === "Pris saknas" ? "price-missing" : ""}">${price}</strong>`
    + `${store ? `<small class="shopping-item-store">${escapeHtml(store)}</small>` : ""}${comparePrice}${inexact}</span>`
    + `<button type="button" class="shopping-remove" data-remove-item="${escapeHtml(item.namn)}" aria-label="Ta bort ${escapeHtml(item.namn)} ur listan">×</button></div>`
    + shoppingActionsMarkup(item.namn, status)
    + `</article>`;
}

// Handlade och hemmavarande rader samlas under listan i stället för att
// försvinna: den som bockat fel ska kunna se det och ta tillbaka varan.
function handledRowMarkup(item) {
  const status = itemStatus(item.namn);
  const label = status === PURCHASED ? "Köpt" : "Finns hemma";
  return `<div class="shopping-handled-row"><span><strong>${escapeHtml(item.namn)}</strong><small>${label}</small></span>`
    + `<button type="button" class="btn-ghost" data-need="${escapeHtml(item.namn)}">Behöver köpa</button></div>`;
}

function wireShoppingRowActions(container) {
  container.querySelectorAll("[data-at-home]").forEach(button => button.addEventListener("click", () => {
    const name = button.dataset.atHome;
    setItemStatus(name, ALREADY_HAVE, { location: suggestedLocationFor(name) });
    showUndoToast(`${name} · finns hemma, lagt i ${PANTRY_TAB_LABELS[suggestedLocationFor(name)]}`, undoLastShoppingAction);
  }));
  container.querySelectorAll("[data-bought]").forEach(button => button.addEventListener("click", () => {
    const name = button.dataset.bought;
    if (!window.__matjaktListaAnvand) { window.__matjaktListaAnvand = true; trackEvent("lista_anvand"); }
    setItemStatus(name, PURCHASED, { addToPantry: true, location: suggestedLocationFor(name) });
    noteStaplePurchase(name);
    showUndoToast(`${name} · köpt, lagt i ${PANTRY_TAB_LABELS[suggestedLocationFor(name)]}`, undoLastShoppingAction);
  }));
  container.querySelectorAll("[data-need]").forEach(button => button.addEventListener("click", () => {
    setItemStatus(button.dataset.need, NEED_TO_BUY);
  }));
  container.querySelectorAll("[data-remove-item]").forEach(button => button.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    removeShoppingItem(button.dataset.removeItem);
  }));
}

// Var varan rimligen hör hemma. Härlett ur kategorin vi redan har - inte
// gissat per vara, och aldrig något användaren inte kan flytta efteråt.
const CATEGORY_TO_LOCATION = { Mejeri: "kyl", "Kött & fisk": "kyl", Frys: "frys" };
function suggestedLocationFor(name) {
  return CATEGORY_TO_LOCATION[categoryFor(name, databaseItemFor(name)?.category)] || "skafferi";
}

function amountLabel(amount, unit) {
  // Pieces are bought whole - "Behöver 0.5 st citron" is true in the pot
  // but useless in the store, so st rounds up.
  if (!unit || unit === "st") return `${Math.max(1, Math.ceil(amount))} st`;
  const rounded = amount >= 100 ? Math.round(amount) : Math.round(amount * 10) / 10;
  return `${rounded} ${unit}`;
}
function pantryStep(name) { return (PACKAGE_INFO[name]?.unit || "st") === "st" ? 1 : 50; }
const PANTRY_TAB_LABELS = { skafferi: "Skafferi", kyl: "Kyl", frys: "Frys" };
function renderFollowedProducts() {
  const section = $("followedSection");
  if (!section) return;
  section.hidden = !state.foljdaVaror.length;
  if (!state.foljdaVaror.length) return;
  $("followedList").innerHTML = state.foljdaVaror.map(item =>
    `<div class="ing-row"><strong>♥</strong><span>${escapeHtml(item.name)}${item.chain ? ` <em>(${escapeHtml(item.chain)})</em>` : ""}</span><button type="button" class="shopping-remove" data-unfollow="${escapeHtml(item.name)}" aria-label="Sluta följa">×</button></div>`).join("");
  $("followedList").querySelectorAll("[data-unfollow]").forEach(button => button.addEventListener("click", () => {
    state.foljdaVaror = state.foljdaVaror.filter(f => f.name !== button.dataset.unfollow);
    saveState(); renderFollowedProducts();
  }));
}

// ---------------------------------------------------------------------------
// SKAFFERI / KYL / FRYS
//
// En rad visar produkten när vi FAKTISKT vet vilken produkt det är (bild,
// märke, förpackningsstorlek, GTIN internt) och bara namnet när vi inte gör
// det (§7-§8). Lök, potatis och persilja har inget varumärke, och att hitta
// på ett vore värre än att låta bli.
//
// Bilden följer samma regel som i Handla (§9): bara en bild vi har rätt att
// visa för just den produkten, annars en neutral kategorisymbol. Aldrig en
// annan produkts bild för att fylla tomrummet.
// ---------------------------------------------------------------------------

function pantryItemMarkup(entry) {
  const product = entry.product || null;
  const status = expiryStatus(entry.expiry);
  const image = product?.imageUrl
    ? `<img class="pantry-item-image" src="${escapeHtml(safeHttpUrl(product.imageUrl) || "")}" alt="" loading="lazy" decoding="async">`
    : categoryIconMarkup(entry.category || categoryFor(entry.name));
  // Märke och storlek bara när produkten är känd. Mängden hemma står alltid.
  const amountText = `${formatPantryAmount(entry.amount)} ${escapeHtml(entry.unit || "st")}`;
  const facts = [product?.brand, product?.packageSize].filter(Boolean).map(escapeHtml).join(" · ");
  const expiry = entry.expiry ? `Bäst före ${escapeHtml(entry.expiry)}` : "";
  const badge = status === "expired" ? '<small class="pantry-expiry-badge expired">Utgången</small>'
    : status === "soon" ? '<small class="pantry-expiry-badge soon">Går ut snart</small>' : "";
  return `<div class="pantry-item">${image}`
    + `<span class="pantry-item-info"><strong>${escapeHtml(product?.productName || entry.name)}</strong>`
    + `<small>${[facts, amountText, expiry].filter(Boolean).join(" · ")}</small>${badge}</span>`
    + `<div class="pantry-item-controls">`
    + `<button type="button" class="pantry-step" data-pantry-step="-1" data-pantry-key="${escapeHtml(entry.key)}" aria-label="Mindre ${escapeHtml(entry.name)}">−</button>`
    + `<span class="pantry-item-count">${formatPantryAmount(entry.amount)}</span>`
    + `<button type="button" class="pantry-step" data-pantry-step="1" data-pantry-key="${escapeHtml(entry.key)}" aria-label="Mer ${escapeHtml(entry.name)}">+</button>`
    + `<button type="button" data-remove-pantry="${escapeHtml(entry.key)}" aria-label="Ta bort ${escapeHtml(entry.name)}">×</button>`
    + `</div></div>`;
}

// Hela tal skrivs som hela tal: "3 st", inte "3.0 st". Halvor får finnas.
function formatPantryAmount(amount) {
  const value = Number(amount) || 0;
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 10) / 10);
}

// Steget i +/- följer varans enhet: styckvaror går ett i taget, vikt och
// volym i 50-steg. Att öka ris med "1 gram" hade varit meningslöst.
function pantryStepFor(entry) {
  return (entry.unit || "st") === "st" ? 1 : 50;
}

function renderPantry() {
  renderFollowedProducts();
  const all = pantryList();
  $("pantryCount").textContent = all.length;
  document.querySelectorAll("#pantryTabs button").forEach(button => button.classList.toggle("active", button.dataset.pantryTab === state.pantryTab));
  const items = all.filter(entry => entry.location === state.pantryTab);
  const byKey = new Map(all.map(entry => [entry.key, entry]));
  $("pantryList").innerHTML = items.length
    ? items.map(pantryItemMarkup).join("")
    : `<div class="pantry-empty"><svg viewBox="0 0 64 64"><path d="M12 22h40v34H12zM20 22v-9h24v9M20 33h24M20 43h16"/></svg><h2>${PANTRY_TAB_LABELS[state.pantryTab]} är tomt</h2><p>Lägg in det du redan har hemma så hjälper Matjakt dig att handla mindre.</p></div>`;
  $("pantryList").querySelectorAll("[data-remove-pantry]").forEach(button => button.addEventListener("click", () => {
    const entry = byKey.get(button.dataset.removePantry);
    if (entry) removePantryItem(entry);
  }));
  $("pantryList").querySelectorAll("[data-pantry-step]").forEach(button => button.addEventListener("click", () => {
    const entry = byKey.get(button.dataset.pantryKey);
    if (entry) stepPantryItem(entry, Number(button.dataset.pantryStep) * pantryStepFor(entry));
  }));
  renderHouseholdPantryNote();
}

// Diskret rad om att skafferiet är familjens, inte bara den här telefonens.
// En mening, ingen banner - annars är det marknadsföring i en vardagsvy.
function renderHouseholdPantryNote() {
  const note = $("pantryHouseholdNote");
  if (!note) return;
  note.hidden = !householdActive();
  if (householdActive()) note.textContent = `Delas med ${state.household.name}`;
}

// Which day tab is showing in the "Min matvecka" overview - defaults to
// today (Mon=0..Sun=6, converting from JS's native Sun=0..Sat=6), since
// "Dagens middag" only makes sense pointed at the actual current day.
// Recipes aren't stored per-weekday anywhere in the data model - a recipe's
// "day" has always just been its position in the selected list (see DAYS
// use in renderBasket) - so this only ever indexes into that same array,
// never a separate day-assignment concept.
let weekOverviewDay = (new Date().getDay() + 6) % 7;
// En 4-middagarsvecka har inget på fre-sön: att öppna Vecka på en tom dag
// (och visa "Ingen middag planerad" på Hem) fast fyra rätter väntar läser
// som en trasig app. Först dagens middag, annars nästa planerade.
function firstPlannedDayFrom(selected, startIndex) {
  for (let offset = 0; offset < 7; offset++) {
    const index = (startIndex + offset) % 7;
    if (selected[index]) return index;
  }
  return startIndex;
}
let weekPlanExpanded = false;
const WEEK_PLAN_PREVIEW_COUNT = 4;
const WEEK_SHOPPING_PREVIEW_COUNT = 4;
// Small line icons reused everywhere a "time" or "portions" fact is shown
// next to a recipe (Vecka's Dagens middag, the full recipe page) - one
// definition so they stay visually identical instead of drifting.
const CLOCK_ICON = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>';
const PORTIONS_ICON = '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/></svg>';
function metaIconItem(icon, text) { return `<span class="meta-icon-item">${icon}${escapeHtml(text)}</span>`; }
function weekTodayCardMarkup(recipe) {
  const fb = recipeFeedback(recipe.id);
  const badge = recipe.typ && recipe.typ !== "Provider-recept" ? `<span class="week-today-badge">${escapeHtml(recipe.typ)}</span>` : "";
  const portion = recipe.priceStatus === "unavailable" ? "Pris saknas" : recipe.portionspris ? `${money(recipe.portionspris)}/portion` : "";
  const meta = [recipe.tid ? metaIconItem(CLOCK_ICON, `${recipe.tid} min`) : "", metaIconItem(PORTIONS_ICON, `${state.personer} port`), portion ? metaIconItem(PRICE_TAG_ICON, portion) : ""].filter(Boolean).join("");
  const dayName = DAYS_LONG[weekOverviewDay] || DAYS[weekOverviewDay] || "";
  // Byt ligger som syskon ovanpå kortet (inte knapp-i-knapp) - listan
  // "Veckans plan" som bar den förut är dold.
  return `<div class="week-today-wrap"><button type="button" class="week-today-swap" data-week-swap="${escapeHtml(recipe.id)}">Byt</button><button type="button" class="week-today-card" data-week-details="${escapeHtml(recipe.id)}"><span class="week-today-photo">${recipePhoto(recipe)}</span><span class="week-today-info"><span class="week-today-day">${escapeHtml(dayName)}</span><strong>${escapeHtml(recipe.namn)}</strong>${badge}<span class="week-today-meta">${meta}</span></span><span class="week-today-arrow" aria-hidden="true">›</span>${fb.cooked ? '<span class="week-today-flag" title="Lagade den här">✓</span>' : ""}</button></div>`;
}
function weekEmptyDayMarkup() {
  // data-week-add-meal, not an id - this markup can end up on screen twice at
  // once (the Vecka day card and the Hem "Nästa middag" card can both be
  // showing an empty day simultaneously), and two elements sharing one id
  // would leave the second's button silently unwired.
  return `<div class="week-today-empty"><p>Ingen middag inplanerad den här dagen ännu.</p><button type="button" class="btn btn-ghost" data-week-add-meal>+ Lägg till middag</button></div>`;
}
function todayIndex() { return (new Date().getDay() + 6) % 7; }
function nextMealCardMarkup(recipe, dayLabel = "Ikväll") {
  const meta = [recipe.tid ? `${recipe.tid} min` : null,
                `${recipe.servings || state.personer} portioner`].filter(Boolean).join(" · ");
  // Fotot ÄR kortet: hela ytan öppnar receptet, "Byt" ligger som egen knapp
  // ovanpå (syskon, inte kapslad knapp-i-knapp).
  return `<div class="hero-meal-card">
    <button type="button" class="hero-meal-open" data-week-details="${escapeHtml(recipe.id)}" aria-label="Öppna ${escapeHtml(recipe.namn)}">
      <span class="hero-meal-photo">${recipePhoto(recipe)}</span>
      <span class="hero-meal-scrim" aria-hidden="true"></span>
      <span class="hero-meal-info"><small>${escapeHtml(dayLabel)}</small><strong>${escapeHtml(recipe.namn)}</strong><span class="hero-meal-meta">${escapeHtml(meta)}</span></span>
    </button>
    <button type="button" class="hero-meal-swap" data-week-swap="${escapeHtml(recipe.id)}">Byt</button>
  </div>`;
}
function nextMealEmptyMarkup() {
  // Ingen vecka: hjälteytan blir inbjudan i stället för ett tomt hål.
  return `<button type="button" class="hero-meal-card hero-meal-invite" data-hem-create>
    <strong>Vad blir det för middag i veckan?</strong>
    <p>Tryck här så sätter Matjakt ihop veckans middagar - med riktiga priser från butikerna nära dig.</p>
  </button>`;
}
function weekPlanRowMarkup(recipe, index) {
  const price = recipe.priceStatus === "unavailable" ? "Pris saknas" : recipe.portionspris ? money(recipe.portionspris) : "–";
  const fb = recipeFeedback(recipe.id);
  // Not a nested button-in-button: opening the recipe, swapping the day, and
  // the cooked/skipped menu are three separate interactive siblings inside a
  // plain container, not one control nested inside another.
  return `<div class="week-plan-row ${index === weekOverviewDay ? "active" : ""}">
    <button type="button" class="week-plan-row-main" data-week-details="${escapeHtml(recipe.id)}">
      <span class="week-plan-day">${DAYS[index] || `Dag ${index + 1}`}</span>
      <span class="week-plan-photo">${recipePhoto(recipe)}</span>
      <span class="week-plan-name">${escapeHtml(recipe.namn)}</span>
      <strong class="week-plan-price">${price}</strong>
    </button>
    <button type="button" class="week-plan-swap-btn" data-week-swap="${escapeHtml(recipe.id)}">Byt</button>
    <details class="week-plan-menu">
      <summary aria-label="Fler val">⋯</summary>
      <div class="week-plan-menu-options">
        <button type="button" class="${fb.cooked ? "marked" : ""}" data-cooked="${escapeHtml(recipe.id)}">✓ Lagad</button>
        <button type="button" class="${fb.skipped ? "marked" : ""}" data-skipped="${escapeHtml(recipe.id)}">✗ Hoppade över</button>
      </div>
    </details>
  </div>`;
}
function weekShoppingRowMarkup(item) {
  // SAMMA prisdisciplin som Handla-fliken: databasens riktiga pris först,
  // livepriset sedan, och när inget av dem finns - INGET pris. Den gamla
  // PRODUCT_CATALOG-fallbacken skrev ut en hårdkodad demosiffra som fakta,
  // så samma vara kunde kosta olika på Vecka och Handla, och Vecka-priset
  // kunde vara rent påhitt.
  const match = databaseItemFor(item.namn);
  const live = state.livePriser[item.namn];
  let price = "";
  let missing = false;
  if (match && match.totalCost != null) price = money(match.totalCost);
  else if (live && live.pris_kr != null) price = money(live.pris_kr);
  else if (live) { price = "Pris saknas"; missing = true; }
  const campaign = live?.kampanj?.text ? `<small class="week-shopping-campaign">${escapeHtml(live.kampanj.text)}</small>` : "";
  const image = match?.imageUrl || live?.bild;
  const photo = image ? `<img class="shopping-item-image has-image" src="${escapeHtml(safeHttpUrl(image) || "")}" alt="" loading="lazy">` : categoryIconMarkup(itemCategory(item.namn));
  return `<label class="week-shopping-row"><input type="checkbox" data-week-shopping="${escapeHtml(item.namn)}">${photo}<span class="week-shopping-info"><strong>${escapeHtml(item.namn)}</strong>${campaign}</span><strong class="week-shopping-price ${missing ? "price-missing" : ""}">${price}</strong></label>`;
}
let weekDayAutoPicked = false;
// §14: veckan sammanfattad i fyra rader innan man dyker ner i dagarna.
//
// Varje rad är RÄKNAD, inte påstådd. "3 familjefavoriter" räknas på
// betyg/gillamarkeringar som faktiskt finns, "7 ingredienser finns redan
// hemma" på skafferiet, och kostnaden skrivs bara ut när den är en riktig
// prissatt total - aldrig ett uppskattat pris med "ca" framför.
function weekSummaryFacts(selected, shoppingItems, total) {
  const favourites = selected.filter(recipe =>
    state.favoriter.has(recipe.id) || (state.betyg[recipe.id] || 0) >= 4 || state.feedback[recipe.id]?.liked).length;
  const home = pantryForPricing();
  const atHome = shoppingItems.filter(item => (home[item.namn] || 0) > 0).length;
  const onCampaign = shoppingItems.filter(item => {
    const match = databaseItemFor(item.namn);
    return match && match.campaignPrice != null && match.regularPrice != null
      && match.campaignPrice < match.regularPrice;
  }).length;
  return { dinners: selected.length, favourites, fresh: selected.length - favourites, atHome, onCampaign, total };
}

function renderWeekSummary(selected, shoppingItems, total) {
  const box = $("weekSummary");
  if (!box) return;
  box.hidden = !selected.length;
  if (!selected.length) return;
  const facts = weekSummaryFacts(selected, shoppingItems, total);
  const lines = [
    `${plural(facts.dinners, "middag", "middagar")}`,
    facts.favourites ? `${facts.favourites} ${facts.favourites === 1 ? "familjefavorit" : "familjefavoriter"}` : "",
    facts.fresh ? `${facts.fresh} ${facts.fresh === 1 ? "ny rätt" : "nya rätter"}` : "",
    facts.atHome ? `${plural(facts.atHome, "ingrediens", "ingredienser")} finns redan hemma` : "",
    facts.onCampaign ? `${plural(facts.onCampaign, "kampanjvara", "kampanjvaror")} används` : "",
  ].filter(Boolean);
  const heading = householdActive() ? `Veckan är klar för ${state.household.name}` : "Veckan är klar";
  box.innerHTML = `<h2>${escapeHtml(heading)}</h2><ul>${lines.map(line => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
    // Kostnaden står bara här när den är RIKTIG. "Beräknad matkasse" på en
    // uppskattning hade varit den sortens siffra hela prismotorn finns för
    // att inte producera.
    + (facts.total != null ? `<p class="week-summary-total">Beräknad matkasse ${money(facts.total)}</p>` : "");
}

function renderWeekOverview(selected, shoppingItems, total) {
  renderWeekSummary(selected, shoppingItems, total);
  // Bara vid FÖRSTA målningen: att öppna appen en fredag med en
  // 4-middagarsvecka ska visa en planerad dag, inte "Ingen middag". Men den
  // som själv klickar på söndagsfliken ska självklart få se söndagen.
  if (!weekDayAutoPicked) {
    weekDayAutoPicked = true;
    if (!selected[weekOverviewDay]) weekOverviewDay = firstPlannedDayFrom(selected, weekOverviewDay);
  }
  // Dagfliken bär portionspriset: veckan läses som en rad siffror utan att
  // öppna varje dag. Tom dag visar en punkt, saknat pris ett streck.
  $("weekDayTabs").innerHTML = DAYS.map((day, index) => {
    const recipe = selected[index];
    const price = !recipe ? "·" : recipe.priceStatus === "unavailable" ? "–" : recipe.portionspris ? money(recipe.portionspris) : "–";
    return `<button type="button" class="week-day-tab ${index === weekOverviewDay ? "active" : ""} ${recipe ? "" : "empty"}" data-week-day="${index}" role="tab" aria-selected="${index === weekOverviewDay}"><span class="week-day-tab-name">${day}</span><small class="week-day-tab-price">${escapeHtml(price)}</small></button>`;
  }).join("");

  const todayRecipe = selected[weekOverviewDay];
  $("weekTodayCard").innerHTML = todayRecipe ? weekTodayCardMarkup(todayRecipe) : weekEmptyDayMarkup();

  const planVisibleCount = weekPlanExpanded ? selected.length : Math.min(selected.length, WEEK_PLAN_PREVIEW_COUNT);
  $("weekPlanList").innerHTML = selected.slice(0, planVisibleCount).map(weekPlanRowMarkup).join("");
  $("weekPlanToggle").hidden = selected.length <= WEEK_PLAN_PREVIEW_COUNT;
  $("weekPlanToggle").textContent = weekPlanExpanded ? "Visa färre" : "Visa hela veckan";
  $("weekPlanToggle").onclick = () => { weekPlanExpanded = !weekPlanExpanded; renderWeekOverview(selected, shoppingItems, total); };

  const remainingItems = shoppingItems.filter(item => itemStatus(item.namn) === NEED_TO_BUY);
  $("weekShoppingSummary").textContent = shoppingItems.length ? `${plural(remainingItems.length, "vara kvar", "varor kvar")}${total == null ? "" : ` · ${money(total)}`}` : "";
  $("weekShoppingPreview").innerHTML = shoppingItems.length
    ? (remainingItems.length ? remainingItems.slice(0, WEEK_SHOPPING_PREVIEW_COUNT).map(weekShoppingRowMarkup).join("") : `<p class="week-shopping-done">Allt handlat!</p>`)
    : `<p class="week-shopping-done">Skapa en vecka så samlar vi din inköpslista här.</p>`;
  $("weekShoppingOpenBtn").onclick = () => setView("basket");

  // Hem's "Nästa middag" - always literally today, independent of whichever
  // day tab the user has clicked above (that's a browsing choice on the
  // Vecka page, not a change to what "next" means on Hem). Same recipePhoto
  // call as the Vecka card above, so it's the same image, not a new fetch.
  const heroIndex = selected[todayIndex()] ? todayIndex() : firstPlannedDayFrom(selected, todayIndex());
  const heroRecipe = selected[heroIndex];
  const heroLabel = heroIndex === todayIndex() ? "Ikväll" : `På ${DAYS_LONG[heroIndex] || DAYS[heroIndex]}`;
  $("nextMealCard").innerHTML = heroRecipe ? nextMealCardMarkup(heroRecipe, heroLabel) : nextMealEmptyMarkup();

  // Hem's budget-progress card - fed the same total this function already
  // received from renderBasket(), never recomputed separately.
  const heroRemaining = budgetRemaining(state.budget, total);
  // total == null betyder "riktigt pris ej hämtat ännu" - inte "veckan
  // kostar 0 kr". Kortet visar då ett lugnt hämtningsläge i stället för
  // "800 kr kvar · 0%" som fakta.
  const totalKnown = total != null;
  const percentUsed = totalKnown && state.budget ? Math.min(100, Math.round(total / state.budget * 100)) : 0;
  // Ingen vecka alls: siffran är budgeten själv ("800 kr veckobudget"),
  // inte ett streck - strecket betyder "pris hämtas" och finns bara när
  // det faktiskt finns en vecka att prissätta.
  const nothingPlanned = !selected.length;
  $("summaryBudgetRemaining").textContent = nothingPlanned ? money(state.budget) : totalKnown ? money(Math.max(0, heroRemaining)) : "–";
  $("summaryBudgetPrefix").textContent = nothingPlanned ? "veckobudget" : "kvar av";
  $("summaryBudgetTotal").textContent = nothingPlanned ? "" : money(state.budget);
  $("summaryBudgetPercent").textContent = nothingPlanned ? "" : totalKnown ? `${percentUsed}%` : "hämtas…";
  $("summaryBudgetBar").style.width = `${percentUsed}%`;
  $("summaryBudgetBar").classList.toggle("over-budget", heroRemaining < 0);

  // All wired together at the end, once every section above has its final
  // DOM in place - wiring data-week-details right after only the today-card
  // was rendered would miss the plan list's own rows, which don't exist yet
  // at that point.
  document.querySelectorAll("[data-week-day]").forEach(button => button.addEventListener("click", () => { weekOverviewDay = Number(button.dataset.weekDay); renderWeekOverview(selected, shoppingItems, total); }));
  document.querySelectorAll("[data-week-details]").forEach(button => button.addEventListener("click", () => openRecipeTab(button.dataset.weekDetails)));
  document.querySelectorAll("[data-week-add-meal]").forEach(button => button.addEventListener("click", () => setView("recipes")));
  document.querySelectorAll("[data-hem-create]").forEach(button => button.addEventListener("click", () => openPlanComparison()));
  document.querySelectorAll("[data-report-price]").forEach(button => button.addEventListener("click", () => {
    trackEvent("prisfel_rapporterat");
    button.textContent = "Tack! Vi kollar på det.";
    button.disabled = true;
  }));
  document.querySelectorAll("[data-week-browse-recipes]").forEach(button => button.addEventListener("click", () => $("recipeScroll")?.scrollIntoView({ behavior: "smooth" })));
  document.querySelectorAll("[data-week-shopping]").forEach(input => {
    input.checked = itemStatus(input.dataset.weekShopping) !== NEED_TO_BUY;
    input.addEventListener("change", () => {
      const name = input.dataset.weekShopping;
      setItemStatus(name, input.checked ? PURCHASED : NEED_TO_BUY,
                    { addToPantry: input.checked, location: suggestedLocationFor(name),
                      });
      renderBasket();
    });
  });
  document.querySelectorAll("[data-week-swap]").forEach(button => button.addEventListener("click", () => openSwapModal(button.dataset.weekSwap)));
  document.querySelectorAll("[data-cooked]").forEach(button => button.addEventListener("click", () => { const id = button.dataset.cooked; const fb = state.feedback[id] || {}; state.feedback[id] = { ...fb, cooked: (fb.cooked || 0) + 1 }; saveState(); renderBasket(); }));
  document.querySelectorAll("[data-skipped]").forEach(button => button.addEventListener("click", () => { const id = button.dataset.skipped; const fb = state.feedback[id] || {}; state.feedback[id] = { ...fb, skipped: (fb.skipped || 0) + 1 }; saveState(); renderBasket(); }));
}
function renderGreeting() {
  const hour = new Date().getHours();
  const timeGreeting = hour < 10 ? "God morgon" : hour < 17 ? "God dag" : "God kväll";
  // Only a real, stored identifier - the account system has no display-name
  // field, so the email's local part is the only honest "name" available,
  // and only when actually logged in. Never a placeholder like "Adam".
  // Skipped when it doesn't actually read as a name (auto-generated/test
  // addresses are long id-looking strings, e.g. "user-b9db1998cdbd4f47...")
  // - showing that verbatim overflowed the header instead of greeting
  // anyone. A short, mostly-letters local part is kept; anything longer or
  // digit-heavy just falls back to the plain time greeting.
  const rawName = state.user?.email?.split("@")[0] || "";
  const name = rawName.length <= 18 && !/\d{4,}/.test(rawName) ? rawName : "";
  $("homeGreeting").textContent = name ? `${timeGreeting}, ${name}` : timeGreeting;
}

// ---------------------------------------------------------------------------
// ÅTERKOMMANDE BASVAROR (§13)
//
// Matjakt lägger ALDRIG in dem själv. Den frågar - en vara i taget, en rad
// diskret ovanför listan - och ett nej gäller resten av veckan. Att fylla
// listan med tio saker familjen inte bett om är precis den administration
// appen ska ta bort, inte skapa.
//
// Vad som räknas som en basvara lär vi oss av vad som faktiskt köpts, inte
// av en fast lista över vad folk "brukar" ha hemma.
// ---------------------------------------------------------------------------

const STAPLE_THRESHOLD = 3;          // köpt så här många veckor -> "köper ofta"
const STAPLE_MEMORY_WEEKS = 8;

function weekStamp(date = new Date()) {
  // ISO-veckonummer räcker som "den här veckan" - vi behöver bara veta att
  // två köp låg i olika veckor, inte exakt vilken.
  const target = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  target.setUTCDate(target.getUTCDate() + 4 - (target.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
  return `${target.getUTCFullYear()}-${Math.ceil(((target - yearStart) / 86400000 + 1) / 7)}`;
}

// Kallas när en vara faktiskt KÖPS - inte när den bara står i listan.
function noteStaplePurchase(name) {
  const stamp = weekStamp();
  const entry = state.stapleItems.find(item => item.name === name);
  if (entry) {
    if (!entry.weeks.includes(stamp)) entry.weeks = [...entry.weeks, stamp].slice(-STAPLE_MEMORY_WEEKS);
  } else {
    state.stapleItems = [...state.stapleItems, { name, weeks: [stamp] }].slice(-60);
  }
  saveState();
}

function staplesToOffer(shoppingItems) {
  const stamp = weekStamp();
  const inList = new Set(shoppingItems.map(item => item.namn));
  const athome = new Set(pantryList().map(entry => entry.name));
  return state.stapleItems
    .filter(item => item.weeks.length >= STAPLE_THRESHOLD)
    .filter(item => !item.weeks.includes(stamp))     // redan köpt i veckan
    .filter(item => !inList.has(item.name) && !athome.has(item.name))
    .filter(item => state.stapleAsked[item.name] !== stamp);   // nej gäller veckan ut
}

// U06: säg vad vi ANTAR att du redan har - se src/services/assumed-home.js.
const ASSUMED_ETIKETT = {
  [ASSUMED_STATE.ON_LIST]: "står redan på listan",
  [ASSUMED_STATE.ADDED]: "tillagd",
  [ASSUMED_STATE.AT_HOME]: "i skafferiet",
};
const ASSUMED_KLASS = {
  [ASSUMED_STATE.ON_LIST]: "is-onlist",
  [ASSUMED_STATE.ADDED]: "is-added",
  [ASSUMED_STATE.AT_HOME]: "is-athome",
};

function renderAssumedHome(shoppingItems) {
  const section = $("assumedHomeSection"), box = $("assumedHomeList");
  if (!section || !box) return;
  const items = assumedHomeItems(selectedRecipes());
  section.hidden = !items.length;
  if (!items.length) return;
  const tillagda = new Set(state.extraItems.map(e => String(e.name || "").trim().toLowerCase()));
  // pantryList(), inte pantryNamesForCooking(): den senare läser nycklarna
  // rakt av och räknar ett tomt fack som "hemma". Ett skafferi med 0 kvar
  // är inget skafferi.
  const iSkafferi = new Set(pantryList().map(rad => String(rad.name || "").trim().toLowerCase()));
  const påListan = new Set((shoppingItems || []).map(rad => String(rad.namn || rad.name || "").trim().toLowerCase()));
  box.innerHTML = items.map(namn => {
    const läge = assumedState(namn, tillagda, iSkafferi, påListan);
    if (läge !== ASSUMED_STATE.OFFER)
      return `<span class="assumed-chip ${ASSUMED_KLASS[läge]}">`
        + `${escapeHtml(namn)} · ${ASSUMED_ETIKETT[läge]}</span>`;
    return `<button type="button" class="assumed-chip" data-assumed-add="${escapeHtml(namn)}">`
      + `${escapeHtml(namn)}<span aria-hidden="true">+</span>`
      + `<span class="sr-only">lägg till i inköpslistan</span></button>`;
  }).join("");
  box.querySelectorAll("[data-assumed-add]").forEach(knapp => knapp.addEventListener("click", () => {
    addExtraItem({ name: knapp.dataset.assumedAdd, source: "assumed_home" });
    render();
  }));
}

function renderStaplePrompt(shoppingItems) {
  const box = $("staplePrompt");
  if (!box) return;
  const offers = staplesToOffer(shoppingItems);
  box.hidden = !offers.length;
  if (!offers.length) return;
  // EN vara åt gången. En lista med kryssrutor är en till uppgift; en fråga
  // är en fråga.
  const item = offers[0];
  box.innerHTML = `<p>Behöver ni ${escapeHtml(item.name.toLowerCase())} den här veckan?</p>`
    + `<div class="staple-prompt-actions">`
    + `<button type="button" class="btn btn-ghost" data-staple-no="${escapeHtml(item.name)}">Nej tack</button>`
    + `<button type="button" class="btn btn-primary" data-staple-yes="${escapeHtml(item.name)}"><span>Lägg till</span></button>`
    + `</div>`;
  box.querySelector("[data-staple-yes]").addEventListener("click", () => {
    addExtraItem({ name: item.name, source: "staple" });
    state.stapleAsked[item.name] = weekStamp();
    saveState();
    render();
  });
  box.querySelector("[data-staple-no]").addEventListener("click", () => {
    state.stapleAsked[item.name] = weekStamp();
    saveState();
    renderStaplePrompt(shoppingItems);
  });
}

// Listan som Handla faktiskt ritar.
//
// Utan hushåll: veckans aggregat, precis som förut.
// Med hushåll: serverns rader - så en vara någon ANNAN lade till syns här -
// berikade med veckans mängd och förpackning där raderna möts. En rad som
// bara finns hos hushållet (manuellt tillagd, eller från den andres vecka)
// får sin mängd från raden själv.
function shoppingItemsForView(selected) {
  const weekItems = aggregateShopping(selected);
  if (!householdActive()) return weekItems;
  const byName = new Map(weekItems.map(item => [foldName(item.namn), item]));
  const rows = shoppingRows(state.household).filter(row => row.status !== REMOVED);
  const merged = rows.map(row => {
    const weekItem = byName.get(foldName(row.name));
    if (weekItem) { byName.delete(foldName(row.name)); return weekItem; }
    return { namn: row.name, total: row.amount || 1, unit: row.unit || "st", package: null };
  });
  // Veckans rader som ännu inte hunnit ut till servern visas ändå - annars
  // blinkade listan tom den sekund en ny vecka skapades.
  return [...merged, ...byName.values()];
}

// Är veckan dyrare än hushållets vanliga? En mening och en väg vidare -
// inga procent, inga påhittade besparingar. Regeln (minst fyra prissatta
// veckor, minst 75 kr) bor i src/services/swap.js.
function renderWeekCostAlert(total) {
  const box = $("weekCostAlert");
  if (!box) return;
  const alert = weekCostAlert(total, state.weekHistory);
  box.hidden = !alert;
  if (!alert) return;
  box.innerHTML = `<p>Den här veckan blev cirka ${money(alert.difference)} dyrare än er vanliga vecka (${money(alert.usual)}).</p>`
    + `<button type="button" class="btn btn-ghost" id="lowerCostBtn">Sänk priset</button>`;
  // "Sänk priset" öppnar bytesrutan på veckans DYRASTE rätt med avsikten
  // billigare förvald - konkreta byten, inte ett råd.
  $("lowerCostBtn").addEventListener("click", () => {
    const priciest = selectedRecipes().filter(recipe => recipe.portionspris)
      .sort((a, b) => b.portionspris - a.portionspris)[0];
    if (!priciest) return;
    openSwapModal(priciest.id);
    if (swapContext) {
      swapContext.intent = "cheaper";
      swapContext.allOptions = swapOptionsFor(swapContext.current, swapContext.candidates, "cheaper");
      renderSwapModal();
    }
  });
}

function renderBasket() {
  const selected = selectedRecipes();
  ensureWeekRecipeDetails();
  const shoppingItems = shoppingItemsForView(selected);
  // The header total must be the SAME number the store-comparison widget
  // shows for the currently selected/pinned branch - a live total when one
  // has been fetched, the static per-package estimate otherwise - never a
  // second, independently-computed figure that could quietly disagree with
  // what's shown right below it.
  const branches = nearbyBranches();
  const currentResult = branches.length ? computeStoreResults(selected, branches, shoppingItems).find(r => sameBranch(r.branch, selectedBranch())) : null;
  // Null when no REAL price exists yet - never the static estimate. This
  // value also feeds renderWeekOverview, so one fabricated figure here would
  // show up as fact in two places.
  const activeChain = currentPricedChain();
  const extrasCost = extrasTotalForChain(activeChain);
  // The header total is the PRICED chain's database result - the same
  // number its store card shows. Falling back to the branch-keyed result
  // left Free showing "pris hämtas…" forever whenever the nearest branch
  // was a chain the server had masked.
  const headerDb = state.dbChainTotals[headerPricedChain()];
  const total = headerDb ? headerDb.totalCheckoutCost + extrasCost
    : currentResult && currentResult.source !== "estimate" && currentResult.comparable !== false && hasUsablePrice(currentResult)
      ? currentResult.cost + extrasCost : null;
  // ATT HANDLA vs REDAN LÖST. Varor som är köpta eller redan finns hemma
  // lämnar den aktiva listan men försvinner inte: de samlas under den, så
  // ett felklick går att se och ta tillbaka (§5, §6).
  const activeItems = shoppingItems.filter(item => itemStatus(item.namn) === NEED_TO_BUY);
  const handledItems = shoppingItems.filter(item => {
    const status = itemStatus(item.namn);
    return status === PURCHASED || status === ALREADY_HAVE;
  });
  // Butiksordning, inte alfabetisk: frukt & grönt först, frysen sist (§31).
  const groups = groupByCategory(activeItems, item => itemCategory(item.namn));
  // Tom lista av två helt olika skäl: ingen meny finns, eller användaren
  // har tagit bort varenda rad själv. Samma tomtillstånd för båda vore en
  // lögn om det första.
  const emptyState = state.removedItems.size
    ? `<div class="pantry-empty"><h2>Allt är borttaget ur listan</h2><p>Du har markerat varje vara som borttagen. Återställ dem nedan om du ångrar dig.</p></div>`
    : handledItems.length
      ? `<div class="pantry-empty"><h2>Allt är avbockat</h2><p>Ingenting kvar att handla den här veckan.</p></div>`
      : `<div class="pantry-empty"><h2>Listan väntar på din vecka</h2><p>Skapa en meny så samlar vi automatiskt allt du behöver handla.</p></div>`;
  const alreadyHome = handledItems.filter(item => itemStatus(item.namn) === ALREADY_HAVE).length;
  const handledSection = handledItems.length
    ? `<section class="shopping-handled"><h3>Klart${alreadyHome ? ` · ${plural(alreadyHome, "vara finns hemma", "varor finns hemma")}` : ""}<span>${handledItems.length}</span></h3>${handledItems.map(handledRowMarkup).join("")}</section>`
    : "";
  $("shoppingList").innerHTML = (activeItems.length
    ? groups.map(([category, items]) => `<section><h3>${category}<span>${items.length}</span></h3>${items.map(shoppingRowMarkup).join("")}</section>`).join("")
    : (shoppingItems.length ? "" : emptyState)) + handledSection;
  if (shoppingItems.length && !activeItems.length && !handledItems.length) $("shoppingList").innerHTML = emptyState;
  const removedCount = removedRowsForView().length;
  if (removedCount) {
    $("shoppingList").insertAdjacentHTML("beforeend",
      `<button type="button" class="restore-removed" id="restoreRemovedBtn">${plural(removedCount, "borttagen vara", "borttagna varor")} · Återställ alla</button>`);
    $("restoreRemovedBtn").addEventListener("click", restoreRemovedRows);
  }
  wireShoppingRowActions($("shoppingList"));
  const completed = handledItems.length, itemsLeft = activeItems.length, progress = shoppingItems.length ? completed / shoppingItems.length * 100 : 0;
  // No mention of how many items happen to have a live-fetched price, and no
  // fetch timestamp - that's internal plumbing, not something a shopper needs
  // to see. Only the plain, calm facts: what's left, and what it costs.
  $("shoppingProgress").textContent = shoppingItems.length ? plural(itemsLeft, "vara kvar", "varor kvar") : "";
  // Hem's Handla-siffra: samma itemsLeft som Handla-vyn, aldrig en egen räkning.
  const homeCheapest = state.dbComparison?.cheapestChain && !state.dbComparison.locked ? state.dbComparison.cheapestChain : null;
  $("homeShoppingCount").textContent = shoppingItems.length ? plural(itemsLeft, "vara", "varor") : "–";
  $("homeShoppingStore").textContent = shoppingItems.length
    ? (homeCheapest ? `kvar · billigast hos ${homeCheapest}` : "kvar att plocka")
    : "Skapa en vecka först";
  // Var priserna kommer ifrån och hur färska de är - förtroende byggs av
  // att säga det, inte av att låta användaren gissa.
  // SAMMA prioritetskedja som raderna (databaseItemFor) - annars kan noten
  // hävda en annan kedja än den vars priser faktiskt visas.
  const sourceResult = state.dbChainTotals[chosenStore()]
    || state.dbChainTotals[selectedBranch()?.kedja]
    || Object.values(state.dbChainTotals)[0];
  // Dabas villkor: källan ska anges. Diskret, bara här och bara när
  // minst en rad faktiskt bygger på Dabas-verifierad förpackningsdata.
  const dabasNote = $("dabasNote");
  if (dabasNote) {
    const fromDabas = shoppingItems.some(item => databaseItemFor(item.namn)?.packageSource === "DABAS_VERIFIED");
    dabasNote.hidden = !fromDabas;
    dabasNote.textContent = fromDabas ? "Produktinformation från Dabas" : "";
  }
  const sourceNote = $("priceSourceNote");
  if (sourceNote) {
    if (sourceResult?.updatedAt) {
      const updatedDate = new Date(sourceResult.updatedAt * 1000);
      const today = new Date().toDateString() === updatedDate.toDateString();
      const when = today ? `idag ${updatedDate.toTimeString().slice(0, 5)}` : updatedDate.toLocaleDateString("sv-SE");
      sourceNote.textContent = `Priser från ${sourceResult.chain} · uppdaterade ${when}`;
      sourceNote.hidden = false;
    } else {
      sourceNote.hidden = true;
    }
  }
  const nothingPlanned = !shoppingItems.length && !state.extraItems.length;
  $("shoppingCost").textContent = nothingPlanned
    ? `– / ${money(state.budget)}`
    : total == null && !shoppingItems.length && state.extraItems.length
      ? `${money(extrasCost)} / ${money(state.budget)}`
      // "hämtas…" bara medan det faktiskt hämtas. Är prissättningen klar och
      // ingen kedja kunde prissätta listan är det ärligare att säga det.
      : `${total == null
            ? (databasePricingSync.pending || (!state.dbPricedAt && !state.dbPricingFailedAt) ? "pris hämtas…" : "pris saknas just nu")
            : money(total)} / ${money(state.budget)}`; $("shoppingProgressBar").style.width = `${progress}%`;
  // "Allt handlat" celebrates a finished list, never an empty one - and
  // extras count: a week isn't done while the added coffee is unbought.
  const extrasDone = state.extraItems.every(extra => extra.checked);
  $("shoppingComplete").hidden = !((shoppingItems.length || state.extraItems.length)
    && completed === shoppingItems.length && extrasDone);
  const basketNote = $("basketHouseholdNote");
  if (basketNote) {
    basketNote.hidden = !householdActive();
    if (householdActive()) basketNote.textContent = `Delas med ${state.household.name}`;
  }
  // Bara en riktig total får bli historik eller jämförelsegrund.
  if (total != null) lastRealWeekTotal = total;
  renderWeekCostAlert(total);
  renderStaplePrompt(shoppingItems);
  renderAssumedHome(shoppingItems);
  renderAttribution(shoppingItems);
  renderStoreComparison(selected); renderStoreCards(); renderExtraItems(activeChain); renderPantry();
  renderWeekStoreTabs();
  updateWeekStoreStatus();
  // Fed the exact same selected/shoppingItems/total this function just
  // computed - the overview and the full page below it are two views onto
  // one render pass, never two separate computations that could drift.
  renderWeekOverview(selected, shoppingItems, total);
  syncLivePrices(shoppingItems);
  // Veckans behov ut till familjens delade lista. Debouncad och idempotent:
  // en oförändrad vecka skickar ingenting.
  pushWeekToHousehold();
}
function updateWeekStoreStatus() {
  const selected = selectedRecipes();
  if (!selected.length) { $("weekStoreStatus").textContent = ""; return; }
  const shoppingItems = aggregateShopping(selected);
  const liveCount = shoppingItems.filter(item => state.livePriser[item.namn]).length;
  const chain = chosenStore();
  const fetchingLive = livePriceSync.loading;
  $("weekStoreStatus").textContent = fetchingLive ? `Hämtar priser hos ${chain}...` : VALID_CHAINS.includes(chain) ? (liveCount ? `Visar priser hos ${chain}` : `Uppskattat pris - hämtar priser hos ${chain}...`) : chain === "alla" ? "Visar uppskattade priser, jämfört mot alla butiker" : "Visar uppskattade priser";
  $("weekStoreStatus").classList.toggle("loading", fetchingLive);
}
function switchWeekStore(chain) {
  if (state.butik === chain) return;
  state.butik = chain;
  state.livePriser = {};
  state.liveBranchTotals = {};
  // dbChainTotals behålls - de är per kedja och fortfarande sanna - men
  // jämförelse-snapshotten för DENNA lista mot förra butiken rensas via
  // renderns egen omhämtning.
  saveState();
  render();
  renderCampaignSection();
  syncSettingsInputs();
}

// Every chain we actually have a nearby store for, in a stable order. Built
// from the store lookup rather than hardcoded: City Gross was invisible in
// the week view for exactly as long as this was a fixed list, even once we
// held four thousand of its prices. A chain added to the backend now appears
// here on its own.
function availableChains() {
  const fromStores = [...new Set(nearbyBranches().map(branch => branch.kedja))]
    .filter(chain => chain && RELEASED_CHAINS.includes(chain));
  return fromStores.sort((a, b) => a.localeCompare(b, "sv"));
}
// Alternativen i butiksväljarna byggs från samma lista - aldrig hårdkodade
// i HTML där en gated kedja kan ligga kvar.
function storeOptionsMarkup(selected, autoLabel) {
  const option = (value, label) => `<option value="${escapeHtml(value)}" ${selected === value ? "selected" : ""}>${escapeHtml(label)}</option>`;
  return [option("auto", autoLabel), option("alla", "Alla butiker"), ...RELEASED_CHAINS.map(chain => option(chain, chain))].join("");
}

// Kept for the few places that ask "is this a real chain name" rather than
// "which chains are nearby" - now derived, so it can never drift from the
// store data.
// SLÄPPTA KEDJOR. Speglar backend/services/grocery/api.py RELEASED_CHAINS -
// ett test (backend/tests/test_frontend_contract.py) låser att listorna är
// lika. ICA, Coop och Lidl finns i butiksregistret men är gated tills
// kvalitet och rättigheter räcker; de ska inte gå att välja i appen.
const RELEASED_CHAINS = ["Willys", "Hemköp", "City Gross"];
const VALID_CHAINS = RELEASED_CHAINS;

function renderWeekStoreTabs() {
  const tabs = document.querySelector('[aria-label="Byt butik för veckan"]');
  if (!tabs) return;
  const fixed = ["auto", "alla"];
  const chains = availableChains();
  const wanted = [...fixed, ...chains];
  const current = [...tabs.querySelectorAll("[data-week-store]")].map(b => b.dataset.weekStore);
  if (current.join("|") !== wanted.join("|")) {
    tabs.innerHTML = wanted.map(value =>
      `<button type="button" data-week-store="${escapeHtml(value)}">${fixed.includes(value) ? "" : chainMarkMarkup(value, "sm")}${escapeHtml(value === "auto" ? "Auto" : value === "alla" ? "Alla" : value)}</button>`
    ).join("");
    tabs.querySelectorAll("[data-week-store]").forEach(button =>
      button.addEventListener("click", () => switchWeekStore(button.dataset.weekStore)));
  }
  tabs.querySelectorAll("[data-week-store]").forEach(button =>
    button.classList.toggle("active", button.dataset.weekStore === state.butik));
}
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
async function fetchProductsBatch(chain, zip, names, onItem, storeKey, primatOnly) {
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
async function syncLivePrices(shoppingItems) {
  const chain = chosenStore();
  // A pinned branch only applies here once selectedBranch() actually
  // resolved to it (i.e. its chain matches the chain being shopped) -
  // otherwise this is a plain chain-level fetch, same as always.
  const branch = selectedBranch();
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
  if (!hasPremium()) return;
  if (Date.now() < livePriceCooldownUntil) return;
  if (!names.length || !VALID_CHAINS.includes(chain) || livePriceSync.loading || livePriceSync.key === key) return;
  livePriceSync = { key, loading: true };
  updateWeekStoreStatus();
  try {
    // Applied per item as it arrives (not once at the end) - a full week can
    // take over a minute even when every item eventually succeeds, and
    // showing prices land one by one is a much better wait than a blank
    // "Hämtar..." the whole time.
    await fetchProductsBatch(chain, state.postnummer, names, found => {
      if (chosenStore() !== chain) return;
      const mapped = mapLiveProducts(found);
      if (Object.keys(mapped).length) { Object.assign(state.livePriser, mapped); state.liveUpdatedAt = Date.now(); renderBasket(); }
    }, storeKey);
  } catch { /* live-priser är ett tillägg ovanpå uppskattningen - misslyckas det visas bara uppskattningen kvar */ }
  finally { livePriceSync.loading = false; updateWeekStoreStatus(); }
}
// The chosen week's recipes need their STRUCTURED ingredients (a card
// deliberately ships without them) before the shopping list can render its
// lines. Fetched once per recipe, in the background; each arrival re-renders.
const recipeDetailFetches = new Set();
function ensureWeekRecipeDetails() {
  selectedRecipes().forEach(recipe => {
    if (Array.isArray(recipe.ingredients) && recipe.ingredients.length) return;
    if (recipe.priceStatus === "unavailable") return; // provider-recept har inget att hämta
    if (recipeDetailFetches.has(recipe.id)) return;
    recipeDetailFetches.add(recipe.id);
    loadRecipe(recipe.id).then(detail => {
      // null = backend säger att receptet inte finns. Det svaret ändrar sig
      // inte, så id:t stannar i mängden och vi frågar aldrig igen. Utan den
      // skillnaden blev ett borttaget recept-id en 404-loop som gick om på
      // varje omritning (femdubblad av hushållssynkens omritningar).
      if (!detail) return;
      // Merge in place: every list, week and favourites reference THIS
      // object, so replacing it would orphan them.
      Object.assign(recipe, detail, { steg: detail.instructions || detail.steg || [] });
      renderBasket();
      // Öppnades receptet medan hämtningen pågick (byt rätt -> tryck på
      // rätten) ritades sidan utan mängder och ritades aldrig om - den
      // vägen hämtar inte själv när ett anrop redan är på väg.
      if (new URLSearchParams(location.search).get("recept") === recipe.id) renderRecipePage();
    }).catch(() => {
      // Nätfel eller serverfel: vi vet ingenting om receptet. Släpp id:t
      // fritt så nästa omritning försöker igen - annars står inköpslistan
      // tom tills sidan laddas om. (Ett 404 släpper INTE id:t: se
      // if (!detail) ovan.)
      recipeDetailFetches.delete(recipe.id);
    });
  });
}

function aggregateShopping(selected) {
  // The removal filter lives HERE, at the single choke point every consumer
  // reads from: the Handla list, the totals, the budget, the store
  // comparison, coverage and the per-store carts all recompute from this
  // one function - so a removed item cannot linger in any of them. (The
  // recipeIds pricing path re-aggregates server side and honours the same
  // removals via excludeItems in weekPricingBody.)
  const everything = aggregateIngredients(selected.filter(recipe => recipe.priceStatus !== "unavailable"), RECIPE_QUANTITIES, PACKAGE_INFO, state.personer);
  // Ett receptBYTE kan stryka ingredienser vars namn ligger kvar i
  // removedItems - spöknamn som får "Återställ alla" att ljuga om antalet.
  // Beskär mot det verkliga aggregatet - men bara när det finns ett: under
  // uppstart är listan tom för att recepten inte laddats än, inte för att
  // borttagningarna blivit ogiltiga.
  if (everything.length && (state.removedItems.size || state.avklarade.size || state.harHemma.size)) {
    const names = new Set(everything.map(item => item.namn));
    for (const name of [...state.removedItems]) {
      if (!names.has(name)) state.removedItems.delete(name);
    }
    // Samma spöknamnsfälla för avbockade: ett receptbyte stryker varan,
    // namnet ligger kvar, och när ett senare byte återinför samma namn
    // visas varan förbockad som "redan handlad".
    for (const name of [...state.avklarade]) {
      if (!names.has(name)) state.avklarade.delete(name);
    }
    for (const name of [...state.harHemma]) {
      if (!names.has(name)) state.harHemma.delete(name);
    }
  }
  return everything.filter(item => !state.removedItems.has(item.namn));
}

function clearPriceSnapshots() {
  // Allt som prissatte den FÖRRA listan: live-totaler, databastotaler och
  // jämförelsen. En veckomutation utan denna rensning målade förra veckans
  // "Billigast"-krona och totaler som fakta tills en omhämtning råkade ske.
  state.livePriser = {};
  state.liveBranchTotals = {};
  state.dbChainTotals = {};
  state.dbComparison = null;
  state.dbPricedAt = null;
}

// Produkthändelseräknare - får aldrig blockera ett klick, aldrig kasta.
// Räknar kärnhändelserna som avgör om Matjakt fungerar: skapade veckor
// och använda listor, inte nedladdningar. Inloggad skickas sessionen
// med, så servern kan räkna PERSONER och inte klick (den sparar bara
// konto + dag + händelsenamn, aldrig klockslag eller sida).
function trackEvent(name) {
  try {
    const token = getStoredToken();
    fetch(`${API_BASE_URL}/analytics/event`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ event: name }),
      keepalive: true,
    }).catch(() => {});
  } catch { /* mätning får aldrig störa appen */ }
}

function removeShoppingItem(name) {
  state.removedItems.add(name);
  // A removed item is not a BOUGHT item - it left the list entirely.
  state.avklarade.delete(name);
  state.harHemma.delete(name);
  if (householdActive()) setHouseholdStatus(name, REMOVED, itemStatus(name));
  // Cached live totals priced the removed item; painting them once more
  // would show the OLD sum next to the new list. Drop them and let the
  // refetch fill honest numbers in.
  clearPriceSnapshots();
  saveState();
  render();
  showUndoToast(`${name} borttagen`, () => {
    state.removedItems.delete(name);
    // I hushållet är REMOVED serverns status - ångra måste också gå dit,
    // annars ligger raden osynlig kvar utan väg tillbaka.
    if (householdActive()) setHouseholdStatus(name, NEED_TO_BUY, REMOVED);
    clearPriceSnapshots();
    saveState();
    render();
  });
}
function removedRowsForView() {
  return householdActive()
    ? shoppingRows(state.household).filter(row => row.status === REMOVED).map(row => row.name)
    : [...state.removedItems];
}
function restoreRemovedRows() {
  const names = removedRowsForView();
  state.removedItems.clear();
  if (householdActive()) names.forEach(name => setHouseholdStatus(name, NEED_TO_BUY, REMOVED));
  saveState();
  render();
}

// En enda toast åt gången: en ny borttagning ersätter den förra i stället
// för att stapla remsor över navigeringen.
let undoToastTimer = null;
function showUndoToast(message, onUndo, onOpen = null) {
  const toast = $("undoToast");
  toast.querySelector("span").textContent = message;
  toast.hidden = false;
  const button = toast.querySelector("button");
  // Samma remsa, två roller: "Ångra" efter en egen ändring, "Öppna" när det
  // är en notis om något NÅGON ANNAN gjort. Att ångra någon annans ändring
  // vore fel knapp på fel handling.
  const action = onUndo || onOpen;
  button.textContent = onUndo ? "Ångra" : "Öppna";
  button.hidden = !action;
  button.onclick = () => { clearTimeout(undoToastTimer); toast.hidden = true; if (action) action(); };
  clearTimeout(undoToastTimer);
  undoToastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
}

// U01: budgeten måste säga VAD den räcker till - se src/services/budget-scope.js.
function budgetScopeText() { return budgetScopeFor(state.middagar, state.personer); }

function updateSummary() {
  const hasWeek = selectedRecipes().length > 0;
  $("generateBtnLabel").textContent = hasWeek ? "Öppna veckan" : "Skapa min vecka";
  $("newWeekBtn").hidden = !hasWeek;
  $("weekCardStatus").textContent = hasWeek ? "Veckan är klar" : "Redo";
  const scope = $("budgetScopeNote");
  if (scope) scope.textContent = budgetScopeText();
  // Hemkortet är avsiktligt kompakt och får inte en textrad till, men den
  // som lyssnar sig igenom sidan ska höra omfattningen utan att först
  // öppna inställningarna.
  $("budgetCardBtn")?.setAttribute("aria-label", `Budget: ${budgetScopeText()}`);
}
function hemRecipePreviewMarkup(recipe) {
  const badge = recipe.typ && recipe.typ !== "Provider-recept" ? `<span class="hem-recipe-badge">${escapeHtml(recipe.typ)}</span>` : "";
  const price = recipe.portionspris ? `${money(recipe.portionspris)}/portion` : "";
  // Distinct data-hem-* attributes, not data-details/data-add/data-favorite -
  // the full library on the Recept tab wires those same names document-wide
  // (see renderRecipes), and this preview sits in the DOM at the same time
  // it does (both screens always exist, just toggled by CSS) - reusing the
  // names would double-bind every click.
  return `<button type="button" class="hem-recipe-card" data-hem-details="${escapeHtml(recipe.id)}"><span class="hem-recipe-photo">${recipePhoto(recipe)}</span><span class="hem-recipe-info"><strong>${escapeHtml(recipe.namn)}</strong>${badge}<small>${escapeHtml([recipe.tid ? `${recipe.tid} min` : "", price].filter(Boolean).join(" · "))}</small></span></button>`;
}
function renderHemRecipePreview() {
  const recipes = availableRecipes().slice(0, 8);
  $("hemRecipePreview").innerHTML = recipes.length ? recipes.map(hemRecipePreviewMarkup).join("") : `<p class="empty-state">Inga recept matchar din butik ännu.</p>`;
  document.querySelectorAll("[data-hem-details]").forEach(btn => btn.addEventListener("click", () => openRecipeTab(btn.dataset.hemDetails)));
}
function render() { renderGreeting(); renderRecipes(); renderHemRecipePreview(); renderBasket(); updateSummary(); renderStats(); renderCampaignSection(); }
function step(key, delta, min, max) { state[key] = Math.min(max, Math.max(min, state[key] + delta)); $(`${key === "personer" ? "people" : "meals"}Value`).textContent = state[key]; saveState(); render(); }
const DISLIKE_SUGGESTIONS = ["Lök", "Svamp", "Fisk", "Skaldjur", "Nötter", "Inälvsmat", "Stark mat", "Kokosmjölk"];
function renderDislikeChips() {
  // "Något ni hellre slipper" bodde i onboardingen; sedan den kortades
  // till fyra steg är detta den enda platsen där state.ogillar kan sättas.
  const chips = $("dislikeChips");
  if (!chips) return;
  chips.innerHTML = DISLIKE_SUGGESTIONS.map(term => `<label><input type="checkbox" value="${term}" ${state.ogillar.has(term) ? "checked" : ""}> ${term}</label>`).join("");
  const custom = [...state.ogillar].filter(term => !DISLIKE_SUGGESTIONS.includes(term));
  $("dislikeTags").innerHTML = custom.map(term => `<span class="ob-tag">${escapeHtml(term)}<button type="button" data-remove-dislike="${escapeHtml(term)}" aria-label="Ta bort ${escapeHtml(term)}">×</button></span>`).join("");
  chips.querySelectorAll("input").forEach(box => box.addEventListener("change", () => { box.checked ? state.ogillar.add(box.value) : state.ogillar.delete(box.value); onDislikesChanged(); }));
  document.querySelectorAll("[data-remove-dislike]").forEach(button => button.addEventListener("click", () => { state.ogillar.delete(button.dataset.removeDislike); onDislikesChanged(); }));
}
function onDislikesChanged() { saveState(); renderDislikeChips(); refreshAfterSettingsChange(); }
$("dislikeCustom")?.addEventListener("keydown", e => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  const value = e.target.value.trim();
  if (value) { state.ogillar.add(value); e.target.value = ""; onDislikesChanged(); }
});
function syncSettingsInputs() {
  if (!["auto", "alla", ...RELEASED_CHAINS].includes(state.butik)) { state.butik = "auto"; saveState(); }
  const storeSelect = $("storeInput");
  if (storeSelect && storeSelect.dataset.rendered !== RELEASED_CHAINS.join("|")) {
    storeSelect.innerHTML = storeOptionsMarkup(state.butik, "Billigast automatiskt");
    storeSelect.dataset.rendered = RELEASED_CHAINS.join("|");
  }
  $("budgetInput").value = state.budget; $("peopleValue").textContent = state.personer; $("mealsValue").textContent = state.middagar; $("storeInput").value = state.butik; $("postcodeInput").value = state.postnummer;
  $("kosttypInput").value = state.kost.kosttyp;
  renderDislikeChips();
  document.querySelectorAll("#allergenChips input").forEach(box => { box.checked = state.kost.avoidAllergens.has(box.value);   const timeFilter = $("timeFilter");
  if (timeFilter) timeFilter.value = String(state.maxTid || 0);
});
  const autoOption = document.querySelector('#storeInput option[value="auto"]');
  if (autoOption) autoOption.textContent = hasPremium() ? "Billigast automatiskt" : "Närmast automatiskt (Premium: billigast)";
}
syncSettingsInputs();
$("budgetInput").addEventListener("input", e => { state.budget = clampBudget(e.target.value); saveState(); updateSummary(); renderBasket(); });
const debouncedGeocode = createDebouncedSearch((zip, signal) => fetch(geocodeApiUrl(zip), { signal }).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }), 400);
$("changePasswordForm")?.addEventListener("submit", async event => {
  event.preventDefault();
  const error = $("changePasswordError"), success = $("changePasswordSuccess");
  error.textContent = ""; success.hidden = true;
  try {
    // The server drops every OTHER session on success, so this device stays
    // logged in and any other one does not - which is the whole point of
    // changing a password.
    const { user } = await changePassword(state.authToken,
      $("currentPasswordInput").value, $("newPasswordInput").value);
    if (user) state.user = user;
    $("currentPasswordInput").value = ""; $("newPasswordInput").value = "";
    success.hidden = false;
    render();
  } catch (problem) {
    error.textContent = problem.message;
  }
});

$("postcodeInput").addEventListener("input", e => {
  const previous = state.postnummer;
  state.position = null;
  state.postnummer = e.target.value.replace(/\D/g, "");
  // Drop the old town's stores and prices the moment the postcode actually
  // changes, not when the new ones happen to arrive - otherwise the user
  // sees Gävle stores while typing a Stockholm postcode.
  if (state.postnummer !== previous) clearLocationDerivedState();
  saveState(); refreshAfterSettingsChange();
  if (state.postnummer.length !== 5) return;
  const zip = state.postnummer;
  syncNearbyBranches();
  debouncedGeocode(zip).then(place => {
    if (state.postnummer !== zip) return;
    state.position = { lat: place.lat, lon: place.lon, ort: place.ort };
    saveState(); refreshAfterSettingsChange();
  }).catch(() => { /* geokodning misslyckades - postnumret används ändå för exakt/ungefärlig matchning som innan */ });
});
$("locateBtn").addEventListener("click", () => { if (!navigator.geolocation) return; $("locateBtn").textContent = "Hämtar..."; navigator.geolocation.getCurrentPosition(({ coords }) => { state.position = { lat: coords.latitude, lon: coords.longitude }; $("locateBtn").textContent = "Hittad"; refreshAfterSettingsChange(); }, () => { $("locateBtn").textContent = "Försök igen"; }); });
$("storeInput").addEventListener("change", e => {
  // Via switchWeekStore, inte bara state.butik: livepriserna är nyckelsatta
  // på varunamn UTAN kedja och måste rensas vid varje byte.
  state.livePriser = {}; state.liveBranchTotals = {};
  state.butik = e.target.value;
  saveState(); refreshAfterSettingsChange(); renderCampaignSection();
});
// En inställningsändring (postnummer, butik, kost, näringsmål) påverkar
// NÄSTA vecka och det som räknas om automatiskt (butiker, priser). Den får
// aldrig tyst regenerera en befintlig vecka - det kastade användarens valda
// recept, manuella byten, avbockade varor och borttagningar på varje
// TANGENTTRYCK i postnummerfältet. Finns ingen vecka byggs förslaget om som
// förut; finns en, ritas allt om mot de nya inställningarna med veckan kvar.
function refreshAfterSettingsChange() {
  if (state.valda.size) render();
  else chooseMenu(false);
}

$("feedbackBtn").addEventListener("click", () => { $("feedbackSheet").hidden = false; $("feedbackStatus").textContent = ""; $("feedbackText").focus(); });
$("feedbackClose").addEventListener("click", () => { $("feedbackSheet").hidden = true; });
$("feedbackSheet").addEventListener("click", event => { if (event.target === $("feedbackSheet")) $("feedbackSheet").hidden = true; });
$("feedbackSend").addEventListener("click", async () => {
  const text = $("feedbackText").value.trim();
  if (!text) { $("feedbackStatus").textContent = "Skriv något först."; return; }
  $("feedbackSend").disabled = true;
  try {
    const screen = ($("top").className.match(/view-(\w+)/) || [])[1] || "";
    const response = await fetch(`${API_BASE_URL}/feedback`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ screen, text }) });
    if (!response.ok) throw new Error();
    $("feedbackText").value = "";
    $("feedbackStatus").textContent = "Tack! Din feedback är framme.";
    setTimeout(() => { $("feedbackSheet").hidden = true; }, 1400);
  } catch {
    $("feedbackStatus").textContent = "Gick inte att skicka just nu - försök igen.";
  } finally {
    $("feedbackSend").disabled = false;
  }
});

function openWeekSheet() {
  $("restoreWeekBtn").hidden = !(state.weekHistory || []).length;
  $("weekSheet").hidden = false; document.body.style.overflow = "hidden";
}
function closeWeekSheet() { $("weekSheet").hidden = true; document.body.style.overflow = ""; }
$("budgetCardBtn").addEventListener("click", openWeekSheet);
$("weekSheetOpen").addEventListener("click", openWeekSheet);
$("weekSheetClose").addEventListener("click", closeWeekSheet);
$("weekSheetDone").addEventListener("click", closeWeekSheet);
$("weekSheet").addEventListener("click", event => { if (event.target === $("weekSheet")) closeWeekSheet(); });
document.addEventListener("keydown", event => { if (event.key === "Escape" && !$("weekSheet").hidden) closeWeekSheet(); });
$("sheetPlanBtn").addEventListener("click", () => { closeWeekSheet(); openPlanComparison(); });
$("restoreWeekBtn").addEventListener("click", () => { closeWeekSheet(); restorePreviousWeek(); });

const GOAL_PRESETS = {
  hogprotein: { kcalGoal: "", proteinGoal: "40" },
  lagkalori: { kcalGoal: "0-400", proteinGoal: "" },
  bulk: { kcalGoal: "700-900", proteinGoal: "40" },
  cut: { kcalGoal: "400-500", proteinGoal: "40" },
  underhall: { kcalGoal: "500-600", proteinGoal: "30" },
};
function parseGoalRange(value) {
  if (!value) return { min: null, max: null };
  const [min, max] = value.split("-").map(Number);
  return { min, max };
}
function currentNutritionGoals() {
  const kcal = parseGoalRange($("kcalGoal").value);
  const carbs = parseGoalRange($("carbsGoal").value);
  const fat = parseGoalRange($("fatGoal").value);
  const proteinGoal = $("proteinGoal").value;
  const proteinSources = new Set([...document.querySelectorAll("#proteinSourceChips input:checked")].map(input => input.value));
  return { kcalMin: kcal.min, kcalMax: kcal.max, proteinMin: proteinGoal ? Number(proteinGoal) : null, carbsMin: carbs.min, carbsMax: carbs.max, fatMin: fat.min, fatMax: fat.max, proteinSources };
}
function nutritionGoalsSnapshot() {
  return {
    goalPreset: $("goalPreset").value, kcalGoal: $("kcalGoal").value, proteinGoal: $("proteinGoal").value,
    carbsGoal: $("carbsGoal").value, fatGoal: $("fatGoal").value,
    proteinSources: [...document.querySelectorAll("#proteinSourceChips input:checked")].map(input => input.value),
  };
}
function restoreNutritionGoalsForm() {
  if (!state.naringsmal) return;
  const { goalPreset, kcalGoal, proteinGoal, carbsGoal, fatGoal, proteinSources } = state.naringsmal;
  if (goalPreset) $("goalPreset").value = goalPreset;
  if (kcalGoal) $("kcalGoal").value = kcalGoal;
  if (proteinGoal) $("proteinGoal").value = proteinGoal;
  if (carbsGoal) $("carbsGoal").value = carbsGoal;
  if (fatGoal) $("fatGoal").value = fatGoal;
  (proteinSources || []).forEach(value => { const box = document.querySelector(`#proteinSourceChips input[value="${value}"]`); if (box) box.checked = true; });
}
function onNutritionGoalsChanged() {
  state.naringsmal = nutritionGoalsSnapshot();
  saveState();
  refreshAfterSettingsChange();
}
$("goalPreset").addEventListener("change", e => {
  const preset = GOAL_PRESETS[e.target.value];
  if (preset) { $("kcalGoal").value = preset.kcalGoal; $("proteinGoal").value = preset.proteinGoal; }
  onNutritionGoalsChanged();
});
["kcalGoal", "proteinGoal", "carbsGoal", "fatGoal"].forEach(id => $(id).addEventListener("change", onNutritionGoalsChanged));
document.querySelectorAll("#proteinSourceChips input").forEach(box => box.addEventListener("change", onNutritionGoalsChanged));
function onDietChanged() {
  state.kost = { kosttyp: $("kosttypInput").value, avoidAllergens: new Set([...document.querySelectorAll("#allergenChips input:checked")].map(box => box.value)) };
  saveState(); refreshAfterSettingsChange();
}
$("kosttypInput").addEventListener("change", onDietChanged);
document.querySelectorAll("#allergenChips input").forEach(box => box.addEventListener("change", onDietChanged));
const debouncedRecipeSearch = createDebouncedSearch((query, signal) => fetch(recipeSearchApiUrl(query), { signal }).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }), 300);
async function fetchApiRecipes(query) {
  try {
    const data = await debouncedRecipeSearch(query);
    const retained = state.apiRecipes.filter(recipe => state.valda.has(recipe.id));
    state.apiRecipes = mergeRecipeResults(retained, (data.recipes || []).map(mapApiRecipe));
    renderRecipes();
  } catch (error) {
    if (error?.name === "AbortError") return;
    state.apiRecipes = state.apiRecipes.filter(recipe => state.valda.has(recipe.id));
    renderRecipes();
  }
}
const debouncedLiveSearch = createDebouncedSearch((query, signal) => fetch(productApiUrl(chosenStore(), query), { signal }).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }), 300);
$("recipeSearch").addEventListener("input", e => {
  state.sokning = e.target.value;
  const query = state.sokning.trim();
  state.apiRecipes = state.apiRecipes.filter(recipe => state.valda.has(recipe.id));
  renderRecipes();
  if (query.length >= 3) fetchApiRecipes(query);
  if (query.length < 2 || state.butik === "alla") { $("liveProducts").innerHTML = ""; return; }
  $("liveProducts").innerHTML = `<p class="live-loading">Söker liveprodukter hos ${selectedBranch()?.namn || chosenStore()}...</p>`;
  debouncedLiveSearch(query).then(payload => {
    const data = sanitizeApiPayload(payload);
    state.liveProdukter = data.produkter || [];
    $("liveProducts").innerHTML = state.liveProdukter.length ? `<div class="live-products-head"><span>LIVE FRÅN BUTIKEN</span><strong>${state.liveProdukter.length} produkter</strong></div><div class="live-product-grid">${state.liveProdukter.map(product => `<a class="live-product" href="${product.url}" target="_blank" rel="noopener"><span class="live-product-name">${product.produktnamn}</span><small>${product.marke_och_storlek || "Storlek visas hos butiken"}</small><strong>${product.pris_kr == null ? "Pris saknas" : `${product.pris_kr.toLocaleString("sv-SE", { minimumFractionDigits: 2 })} kr`}</strong></a>`).join("")}</div>` : `<p class="live-loading">Inga liveprodukter hittades.</p>`;
    renderBasket();
  }).catch(error => {
    if (error?.name === "AbortError") return;
    state.liveProdukter = [];
    $("liveProducts").innerHTML = `<p class="live-loading">Livebutiken svarar inte just nu.</p>`;
  });
});
// The category dropdown was replaced by the tag filter row - the tags are
// the recipe bank's own vocabulary, so they cannot drift from what the
// backend can actually filter on.
$("timeFilter").addEventListener("change", e => { state.maxTid = Number(e.target.value); renderRecipes(); });
$("proteinFilter").addEventListener("change", e => { state.minProtein = Number(e.target.value); renderRecipes(); });
$("kcalFilter").addEventListener("change", e => { state.maxKcal = Number(e.target.value); renderRecipes(); });
$("favoriteFilter").addEventListener("change", e => { state.baraFavoriter = e.target.checked; renderRecipes(); });
function setView(view) { $("top").className = `app view-${view}`;
  // Grov tratt för testrundorna: en räknare per flikbesök, inget mer.
  trackEvent(`view_${view}`); document.querySelectorAll(".bottom-nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view)); window.scrollTo({ top: 0, behavior: "smooth" }); }
document.querySelectorAll("[data-view]").forEach(item => item.addEventListener("click", () => {
  // Från receptsidan ska ett tryck i menyn landa direkt i rätt flik - inte
  // kräva ett extra "tillbaka" först.
  if (new URLSearchParams(location.search).get("recept")) {
    history.pushState(null, "", location.pathname);
    renderRecipePage();
  }
  setView(item.dataset.view);
}));
document.querySelector(".wordmark").addEventListener("click", event => {
  event.preventDefault();
  if (new URLSearchParams(location.search).get("recept")) { history.pushState(null, "", location.pathname); renderRecipePage(); }
  setView("home");
});
// Betalningen är klar hos Stripe, men Premium sätts av webhooken - den kommer
// normalt inom sekunder och kan i värsta fall dröja. Att bara läsa kontot en
// gång visade "Inget Premium ännu" med en Prenumerera-knapp som hade startat
// ett andra köp. Vi säger vad som händer och läser om tills det är klart.
// 59/399 bor på exakt ett ställe: backend (features.py -> /api/entitlements).
// Flikarna i kontoarket var hårdkodad HTML och kunde tyst börja ljuga.
function renderPriceTabs() {
  const pricing = premiumPricing();
  const month = document.querySelector('[data-price-tab="month"]');
  const year = document.querySelector('[data-price-tab="year"]');
  // Beloppet i <strong>, villkoret i <small> - priceText bär redan "/mån"
  // och skulle annars läsas som "59 kr/mån /mån".
  const perMonth = pricing.monthly?.pricePerMonth;
  const perYear = pricing.yearly?.pricePerYear;
  if (month) month.innerHTML = `<span>Månad</span><strong>${escapeHtml(perMonth ? `${perMonth} kr` : (pricing.monthly?.priceText || ""))}</strong><small>/mån</small>`;
  if (year) {
    const savings = perMonth && perYear ? `spara ${perMonth * 12 - perYear} kr` : "";
    const extra = ["/år", pricing.yearly?.perMonthText, savings].filter(Boolean).join(" · ");
    year.innerHTML = `<span>År · Bäst värde</span><strong>${escapeHtml(perYear ? `${perYear} kr` : (pricing.yearly?.priceText || ""))}</strong><small>${escapeHtml(extra)}</small>`;
  }
  // Ångerrättsrutan i kontoarket ritas härifrån av samma skäl som priserna:
  // texten bor i backend, och hårdkodad HTML kan tyst börja ljuga om vad
  // kunden godkände. Bocken nollställs inte vid omritning - det är ett
  // aktivt val användaren just gjort, inte något vi ska ta ifrån henne.
  const box = document.getElementById("premiumWithdrawal");
  if (box) {
    const wasChecked = withdrawalConsentGiven(box);
    box.innerHTML = withdrawalConsentMarkup("premiumWithdrawalConsent");
    if (wasChecked) box.querySelector("[data-withdrawal-consent]").checked = true;
  }
}
let awaitingPremiumActivation = false;
let premiumPollInFlight = false;
async function activatePremiumAfterCheckout() {
  // Bara en poll åt gången: i native-appen kan visibilitychange komma
  // flera gånger medan vi redan väntar på Stripes webhook.
  if (premiumPollInFlight) return;
  premiumPollInFlight = true;
  try { await pollPremiumAfterCheckout(); } finally { premiumPollInFlight = false; }
}
async function pollPremiumAfterCheckout() {
  awaitingPremiumActivation = true;
  openAccountModal();
  renderAccount();
  for (let attempt = 0; attempt < 15; attempt++) {
    await refreshUser();
    // hasPremium() är den enda vägen till premiumflaggan (se tests/premium.test.js);
    // på loopback kortsluter dev-luckan pollen, vilket är ofarligt där.
    if (hasPremium()) break;
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  awaitingPremiumActivation = false;
  renderAccount();
  // Premium just nu: veckans priser hämtas om utan mask (nyckeln bär planen).
  if (hasPremium()) renderBasket();
  if (!hasPremium()) {
    // Vi VET inte om betalningen gjordes: användaren kan ha stängt Stripes
    // sida utan att betala. Säg vad som gäller i båda fallen i stället för
    // att påstå ett köp och skicka en icke-betalande kund till supporten.
    $("accountPremiumStatus").textContent = "Ingen betalning har registrerats än. Avbröt du köpet är du kvar på Free och kan prova igen. Gick betalningen igenom dyker Premium upp inom någon minut - hör av dig till supporten om det dröjer längre.";
  }
}

// ---------------------------------------------------------------------------
// MITT HUSHÅLL (Konto → Hushåll)
//
// Flödet är avsiktligt tre steg och inte fler (§1):
//   skriv namnet → Bjud in → skicka länken.
// Ingen kod att läsa upp, ingen inställningssida att gå igenom först.
// ---------------------------------------------------------------------------

const NOTIFY_LABELS = {
  week: "Ny vecka",
  shopping: "Ändringar i inköpslistan",
  plan: "Ändringar i veckoplaneringen",
  inventory: "Skafferi, kyl och frys",
  price: "Prisbevakningar",
};

function renderHousehold() {
  const panel = $("householdPanel");
  if (!panel) return;
  // Hushållet kräver ett konto - det är där medlemskapet bor.
  panel.hidden = !state.authToken;
  if (!state.authToken) return;
  const active = householdActive();
  $("householdNone").hidden = active;
  $("householdCurrent").hidden = !active;
  if (!active) return;
  $("householdNameLabel").textContent = state.household.name;
  const me = state.household.members.find(member => member.isMe);
  const isAdmin = state.household.role === "admin";
  $("householdMembers").innerHTML = state.household.members.map(member => {
    const name = member.displayName || (member.email ? member.email.split("@")[0] : "Medlem");
    const tags = [member.role === "admin" ? "administratör" : "", member.isMe ? "du" : ""].filter(Boolean).join(" · ");
    const remove = isAdmin && !member.isMe
      ? `<button type="button" class="household-remove" data-remove-member="${escapeHtml(String(member.userId))}" aria-label="Ta bort ${escapeHtml(name)}">Ta bort</button>` : "";
    return `<li><span><strong>${escapeHtml(name)}</strong>${tags ? `<small>${escapeHtml(tags)}</small>` : ""}</span>${remove}</li>`;
  }).join("");
  $("householdMembers").querySelectorAll("[data-remove-member]").forEach(button => button.addEventListener("click", () => {
    const userId = Number(button.dataset.removeMember);
    removeMember(state.authToken, userId)
      .then(({ household }) => { state.household = applySync(state.household, { household, revision: state.household.revision }); state.household.members = household.members; renderHousehold(); })
      .catch(error => { $("householdInviteError").textContent = error.message; });
  }));
  // Bara administratören kan bjuda in - samma regel som servern håller.
  $("householdInviteBtn").hidden = !isAdmin;
  if (me) {
    $("householdDisplayName").value = me.displayName || "";
    $("householdSpice").value = me.profile?.spice || "";
    $("householdDiet").value = me.profile?.diet || "";
    $("householdAllergies").value = (me.profile?.allergies || []).join(", ");
  }
  renderNotificationPrefs();
}

function renderNotificationPrefs() {
  const list = $("householdNotifyList");
  if (!list || !state.notisInstallningar) return;
  const prefs = state.notisInstallningar;
  const rows = Object.entries(NOTIFY_LABELS).map(([key, label]) =>
    `<label class="household-notify-row"><span>${label}</span><input type="checkbox" data-notify-pref="${key}" ${prefs[key] === false ? "" : "checked"}></label>`).join("");
  list.innerHTML = `<label class="household-notify-row main"><span>Alla notiser</span><input type="checkbox" data-notify-pref="all" ${prefs.all === false ? "" : "checked"}></label>${rows}`;
  list.querySelectorAll("[data-notify-pref]").forEach(input => input.addEventListener("change", () => {
    const next = { ...prefs, [input.dataset.notifyPref]: input.checked };
    state.notisInstallningar = next;
    saveNotificationPrefs(state.authToken, next)
      .then(({ preferences }) => { state.notisInstallningar = preferences; })
      .catch(() => { /* nästa ändring försöker igen */ });
  }));
}

async function loadNotifications() {
  if (!state.authToken || !householdActive()) return;
  try {
    const payload = await fetchNotifications(state.authToken);
    state.notisInstallningar = payload.preferences;
    if (payload.notifications.length) showHouseholdNotice(payload.notifications);
    renderNotificationPrefs();
  } catch { /* notiser är aldrig värt att störa appen för */ }
}

// Notisen i appen. När push är produktionsklart är detta samma data från
// samma utkorg - bara en annan transport (se services/household/notifications.py).
function showHouseholdNotice(notices) {
  const notice = notices[notices.length - 1];
  showUndoToast(notice.body, null, notice.deeplink ? () => openDeeplink(notice.deeplink) : null);
}

const DEEPLINK_VIEWS = { "/handla": "basket", "/vecka": "week", "/skafferi": "pantry", "/konto": null };
function openDeeplink(deeplink) {
  const view = DEEPLINK_VIEWS[deeplink];
  if (view) setView(view);
  else if (deeplink === "/konto") openAccountModal();
}

// Hushållet hör till KONTOT, inte till telefonen. Utan den här städningen
// låg familjens vecka, lista och skafferi kvar på skärmen efter utloggning -
// och nästa person som loggade in på enheten såg dem.
function clearHouseholdSession() {
  state.household = emptyHouseholdState();
  state.notisInstallningar = null;
  lastWeekPushKey = null;
  clearInterval(householdPollTimer);
}

function wireHouseholdUi() {
  $("householdCreateForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    $("householdCreateError").textContent = "";
    try {
      const { household } = await createHousehold(state.authToken, $("householdNameInput").value);
      state.household = applySync(emptyHouseholdState(), { household, revision: 0 });
      await pullHousehold(true);
      // Veckan som redan finns på den här enheten blir familjens första vecka.
      lastWeekPushKey = null;
      pushWeekToHousehold();
      pushPantryToHousehold();
      startHouseholdSync();
      renderHousehold();
      loadNotifications();
      render();
    } catch (error) {
      $("householdCreateError").textContent = error.message;
    }
  });

  $("householdInviteBtn")?.addEventListener("click", async () => {
    $("householdInviteError").textContent = "";
    try {
      const invite = await createInvite(state.authToken);
      $("householdInviteBox").hidden = false;
      $("householdInviteLink").value = invite.url;
      // Systemets egen delningsruta när den finns: SMS, WhatsApp, Messenger -
      // alla på en gång, utan att vi bygger en egen lista över appar.
      const canShare = typeof navigator.share === "function";
      $("householdShareBtn").hidden = !canShare;
      $("householdShareBtn").onclick = () => navigator.share({ title: invite.shareTitle, text: invite.shareText, url: invite.url }).catch(() => {});
      $("householdCopyBtn").onclick = async () => {
        try {
          await navigator.clipboard.writeText(invite.url);
          $("householdCopyBtn").textContent = "Kopierad";
          setTimeout(() => { $("householdCopyBtn").textContent = "Kopiera"; }, 2000);
        } catch {
          $("householdInviteLink").select();
        }
      };
    } catch (error) {
      $("householdInviteError").textContent = error.message;
    }
  });

  $("householdProfileForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    $("householdProfileError").textContent = "";
    try {
      const { household } = await saveHouseholdProfile(state.authToken, {
        displayName: $("householdDisplayName").value,
        profile: {
          spice: $("householdSpice").value || undefined,
          diet: $("householdDiet").value || undefined,
          allergies: $("householdAllergies").value.split(",").map(value => value.trim()).filter(Boolean),
        },
      });
      state.household = applySync(state.household, { household, revision: state.household.revision });
      state.household.members = household.members;
      renderHousehold();
    } catch (error) {
      $("householdProfileError").textContent = error.message;
    }
  });

  $("householdLeaveBtn")?.addEventListener("click", async () => {
    if (!confirm(`Lämna ${state.household.name}? Den gemensamma veckan, listan och skafferiet stannar hos de andra.`)) return;
    try {
      await leaveHousehold(state.authToken);
    } catch { /* redan ute, eller offline - lokalt läge gäller ändå */ }
    state.household = emptyHouseholdState();
    startHouseholdSync();
    renderHousehold();
    render();
  });

  $("inviteDismissBtn")?.addEventListener("click", () => { $("inviteLanding").hidden = true; clearInviteFromUrl(); });
}

// Skafferiet som redan finns på enheten följer med in i det nya hushållet.
// Utan detta stod familjen med ett tomt skafferi första dagen, trots att
// den som skapade hushållet redan hade fyllt sitt.
function pushPantryToHousehold() {
  Object.entries(state.pantry).forEach(([name, entry]) => {
    if (!(entry.amount > 0)) return;
    upsertInventoryItem(state.authToken, {
      name, amount: entry.amount, unit: PACKAGE_INFO[name]?.unit || "st",
      location: entry.location, expiry: entry.expiry, category: categoryFor(name),
    }).then(applyHouseholdInventory).catch(() => {});
  });
}

// ---- inbjudningslandningen ------------------------------------------------

function clearInviteFromUrl() {
  const url = new URL(location.href);
  url.searchParams.delete("invite");
  history.replaceState(null, "", url.pathname + url.search + url.hash);
}

const pendingInviteToken = new URLSearchParams(location.search).get("invite");

async function handlePendingInvite() {
  if (!pendingInviteToken) return;
  let preview;
  try {
    preview = await previewInvite(pendingInviteToken);
  } catch (error) {
    $("inviteLanding").hidden = false;
    $("inviteLandingTitle").textContent = "Inbjudan gäller inte längre";
    $("inviteLandingBody").textContent = "Be den som bjöd in dig att skicka en ny länk.";
    $("inviteJoinBtn").hidden = true;
    return;
  }
  $("inviteLanding").hidden = false;
  $("inviteLandingTitle").textContent = `${preview.invitedBy || "Någon"} har bjudit in dig till ${preview.householdName}`;
  $("inviteLandingBody").textContent = state.authToken
    ? "Ni delar veckan, inköpslistan och skafferiet."
    : "Logga in eller skapa ett konto så är du med.";
  $("inviteJoinBtn").querySelector("span").textContent = state.authToken ? `Gå med i ${preview.householdName}` : "Logga in och gå med";
  $("inviteJoinBtn").onclick = async () => {
    if (!state.authToken) { $("inviteLanding").hidden = true; openAccountModal(); return; }
    $("inviteLandingError").textContent = "";
    try {
      const { household } = await joinHousehold(state.authToken, pendingInviteToken);
      state.household = applySync(emptyHouseholdState(), { household, revision: 0 });
      await pullHousehold(true);
      startHouseholdSync();
      clearInviteFromUrl();
      $("inviteLanding").hidden = true;
      renderHousehold();
      loadNotifications();
      render();
      setView("week");
    } catch (error) {
      $("inviteLandingError").textContent = error.message;
    }
  };
}

function renderAccount() {
  const loggedIn = Boolean(state.user);
  $("accountLoggedOut").hidden = loggedIn;
  $("accountLoggedIn").hidden = !loggedIn;
  $("profileBtn").textContent = loggedIn ? state.user.email.slice(0, 2).toUpperCase() : "MJ";
  $("profileBtn").classList.toggle("is-premium", hasPremium());
  syncSettingsInputs();
  renderPriceTabs();
  renderHousehold();
  if (loggedIn) {
    $("accountEmail").textContent = state.user.email;
    $("verifyEmailNotice").hidden = state.user.emailVerified;
    $("marketingToggle").checked = Boolean(state.user.marketingConsent);
    // Utskick går bara till verifierade adresser - säg det, i stället för
    // att låta någon tacka ja och undra varför inget kommer.
    $("marketingNote").textContent = state.user.marketingConsent && !state.user.emailVerified
      ? "(skickas när adressen är verifierad)" : "";
    const daysLeft = state.user.trialEndsAt ? Math.max(1, Math.ceil((new Date(state.user.trialEndsAt) - Date.now()) / 86400000)) : 0;
    const hasSubscription = ["active", "trialing", "past_due", "canceled", "unpaid"].includes(state.user.subscriptionStatus);
    const pastDue = ["past_due", "unpaid", "incomplete"].includes(state.user.subscriptionStatus);
    $("accountPremiumStatus").textContent = awaitingPremiumActivation && !hasPremium()
      ? "Kontrollerar om betalningen gått igenom…"
      : daysLeft ? `✓ Provperiod aktiv - ${plural(daysLeft, "dag", "dagar")} kvar (ingen betalning krävs)`
      : state.user.premium ? "✓ Premium aktiverat"
      : pastDue ? "Premium är pausat tills betalningen gått igenom"
      : "Inget Premium ännu";
    // Köpknappen döljs bara när det FINNS något att fixa i portalen. Medan
    // vi kontrollerar en betalning står den kvar: i native-appen kan
    // användaren ha stängt betalsidan utan att betala, och då vore en
    // borttagen köpknapp en återvändsgränd. Servern nekar ändå ett andra
    // köp (409) om prenumerationen redan finns.
    $("premiumPitch").hidden = state.user.premium || pastDue;
    $("subscriptionPanel").hidden = !hasSubscription;
    if (hasSubscription) {
      const periodEnd = state.user.subscriptionPeriodEnd ? new Date(state.user.subscriptionPeriodEnd).toLocaleDateString("sv-SE") : "okänt datum";
      // Planetiketten kommer från samma källa som paywallen (backend), och
      // en okänd plan påstår ingenting om priset.
      const pricing = premiumPricing();
      const planLabel = state.user.subscriptionPlan === "yearly" ? (pricing.yearly?.priceText || "399 kr/år")
        : state.user.subscriptionPlan === "monthly" ? (pricing.monthly?.priceText || "59 kr/mån")
        : "din plan";
      let line;
      if (state.user.subscriptionStatus === "active" && state.user.subscriptionCancelAtPeriodEnd) line = `Din prenumeration (${planLabel}) är uppsagd och gäller till ${periodEnd}, sedan återgår kontot till gratisversionen.`;
      else if (state.user.subscriptionStatus === "active") line = `Din prenumeration (${planLabel}) förnyas automatiskt ${periodEnd}.`;
      else if (["past_due", "unpaid"].includes(state.user.subscriptionStatus)) line = `Senaste betalningen (${planLabel}) gick inte igenom, så Premium är pausat. Uppdatera betalmetoden under Hantera prenumeration så aktiveras det igen.`;
      else if (state.user.subscriptionStatus === "incomplete") line = `Betalningen är påbörjad men inte klar. Slutför den under Hantera prenumeration.`;
      else line = `Din prenumeration är avslutad. Prenumerera igen när du vill.`;
      $("subscriptionPanelLine").textContent = line;
    }
  }
  const premium = hasPremium();
  $("nutritionLocked").hidden = premium;
  $("nutritionFields").hidden = !premium;
}
let swapContext = null;
const SWAP_OPTIONS_BATCH = 3;
function swapOptionMarkup(option, isSelected) {
  const recipe = option.candidate;
  const badge = recipe.typ && recipe.typ !== "Provider-recept" ? `<span class="swap-option-badge">${escapeHtml(recipe.typ)}</span>` : "";
  const price = recipe.priceStatus === "unavailable" ? "Pris saknas" : recipe.portionspris ? `${money(recipe.portionspris)}/portion` : "";
  // Only a genuine, already-fetched campaign on one of this recipe's own
  // ingredients - never guessed or shown for a recipe just because some
  // other product happens to be on offer right now.
  const campaignIngredient = recipe.ingredienser.find(name => state.livePriser[name]?.kampanj?.text);
  const campaignNote = campaignIngredient ? `<small class="swap-option-campaign">Kampanj på ${escapeHtml(campaignIngredient)}</small>` : "";
  // VARFÖR det här alternativet dök upp. En rad som säger "12 kr billigare
  // per portion" är en anledning; en osorterad lista är bara brus.
  const reason = option.reason ? `<small class="swap-option-reason">${escapeHtml(option.reason)}</small>` : "";
  // Prisändringen står alltid, även när den är okänd - annars ser ett
  // okänt pris ut som "ingen skillnad". Utelämnas bara när reason redan
  // säger exakt samma sak, så raden inte upprepar sig själv.
  const kostnad = option.cost && option.cost !== option.reason
    ? `<small class="swap-option-cost">${escapeHtml(option.cost)}</small>` : "";
  return `<button type="button" class="swap-option ${isSelected ? "selected" : ""}" data-choose-swap="${escapeHtml(recipe.id)}"><span class="swap-option-photo">${recipePhoto(recipe)}</span><span class="swap-option-info"><strong>${escapeHtml(recipe.namn)}</strong>${badge}<small class="swap-option-meta">${[recipe.tid ? `${recipe.tid} min` : "", price].filter(Boolean).join(" · ")}</small>${reason}${kostnad}${campaignNote}</span>${isSelected ? '<span class="swap-option-check" aria-hidden="true">✓</span>' : ""}</button>`;
}
const FREE_SWAP_LIMIT = 3;
function openSwapModal(currentId) {
  if (!hasPremium() && state.swapsThisWeek >= FREE_SWAP_LIMIT) {
    $("swapModalHint").textContent = "";
    $("swapOptions").innerHTML = `<button type="button" class="store-compare-upsell" id="swapUpsell">Du har använt dina ${FREE_SWAP_LIMIT} gratis byten den här veckan. Med Premium byter du hur mycket du vill.</button>`;
    $("swapUpsell").addEventListener("click", () => { closeSwapModal(); openPremiumPitch(); });
    $("swapConfirmBtn").hidden = true; $("swapShowMoreBtn").hidden = true;
    $("swapModal").hidden = false;
    return;
  }
  const selected = selectedRecipes();
  const dayIndex = state.weekPlan.indexOf(currentId);
  const branch = selectedBranch();
  const candidates = candidateRecipesForUser().filter(recipe => !state.valda.has(recipe.id));
  // Sorteras på kandidatens RIKTIGA portionspris (databasprissatt vid
  // import). shoppingListCost gick via statiska PRODUCT_CATALOG som inte
  // känner bankreceptens ingredienser - varje kandidat kostade ~samma och
  // "billigast först" blev slumpartad.
  const current = selected.find(recipe => recipe.id === currentId);
  const allOptions = swapOptionsFor(current, candidates, "");
  if (!allOptions.length) { $("swapModalHint").textContent = ""; $("swapOptions").innerHTML = `<p class="live-loading">Inga alternativ hittades som passar budget, butik och dina filter just nu.</p>`; $("swapConfirmBtn").hidden = true; $("swapShowMoreBtn").hidden = true; $("swapModal").hidden = false; return; }
  swapContext = { currentId, dayIndex, current, candidates, intent: "", allOptions, visibleCount: SWAP_OPTIONS_BATCH, selectedId: null };
  renderSwapModal();
  $("swapModal").hidden = false;
}
// Alternativen som faktiskt är bättre i den valda meningen. Rankningen och
// ärlighetsreglerna bor i src/services/swap.js.
function swapOptionsFor(current, candidates, intent) {
  return rankSwapOptions(current, candidates, intent, pantryNamesForCooking())
    .map(option => ({ ...option, total: option.price ?? 9999,
                      reason: swapReasonText(option, intent, current),
                      // U21: alltid, inte bara när man byter för pengarnas skull.
                      cost: swapCostText(option, current) }));
}

function renderSwapModal() {
  if (!swapContext) return;
  const { currentId, dayIndex, allOptions, visibleCount, selectedId, intent } = swapContext;
  const currentRecipe = selectedRecipes().find(r => r.id === currentId);
  const dayLabel = DAYS[dayIndex] || `Dag ${dayIndex + 1}`;
  // Avsikten först, alternativen sedan. Fem knappar räcker - det här ska
  // vara ett val, inte ett formulär.
  const intents = `<div class="swap-intents">${["", ...SWAP_INTENTS.map(option => option.id)].map(id => {
    const label = id ? SWAP_INTENTS.find(option => option.id === id).label : "Något annat";
    return `<button type="button" class="swap-intent ${id === intent ? "active" : ""}" data-swap-intent="${escapeHtml(id)}">${escapeHtml(label)}</button>`;
  }).join("")}</div>`;
  $("swapModalHint").innerHTML = `${dayLabel}s middag${currentRecipe ? ` · nuvarande: ${escapeHtml(currentRecipe.namn)}` : ""}` + intents;
  $("swapModalHint").querySelectorAll("[data-swap-intent]").forEach(button => button.addEventListener("click", () => {
    swapContext.intent = button.dataset.swapIntent;
    swapContext.allOptions = swapOptionsFor(swapContext.current, swapContext.candidates, swapContext.intent);
    swapContext.visibleCount = SWAP_OPTIONS_BATCH;
    swapContext.selectedId = null;
    renderSwapModal();
  }));
  // En tom lista är ett ärligare svar än en påhittad: det finns helt enkelt
  // inget billigare/snabbare alternativ som också passar kost och budget.
  $("swapOptions").innerHTML = allOptions.length
    ? allOptions.slice(0, visibleCount).map(option => swapOptionMarkup(option, option.candidate.id === selectedId)).join("")
    : `<p class="live-loading">Ingen av de rätter som passar er är ${escapeHtml((SWAP_INTENTS.find(o => o.id === intent)?.label || "annorlunda").toLowerCase())} än den här.</p>`;
  document.querySelectorAll("[data-choose-swap]").forEach(button => button.addEventListener("click", () => {
    swapContext.selectedId = swapContext.selectedId === button.dataset.chooseSwap ? null : button.dataset.chooseSwap;
    renderSwapModal();
  }));
  $("swapShowMoreBtn").hidden = visibleCount >= allOptions.length;
  $("swapConfirmBtn").hidden = !selectedId;
}
$("swapShowMoreBtn").addEventListener("click", () => { if (swapContext) { swapContext.visibleCount += SWAP_OPTIONS_BATCH; renderSwapModal(); } });
$("swapConfirmBtn").addEventListener("click", () => {
  if (!swapContext?.selectedId) return;
  swapWeekPlanDay(swapContext.dayIndex, swapContext.selectedId);
  trackEvent("recept_bytt");
  if (!hasPremium()) state.swapsThisWeek++;
  // Ett byte är en ny lista: förra listans totaler och Billigast-krona får
  // inte målas som fakta medan omhämtningen pågår.
  clearPriceSnapshots();
  saveState(); render(); closeSwapModal();
});
function closeSwapModal() { $("swapModal").hidden = true; swapContext = null; }
document.querySelectorAll("[data-swap-close]").forEach(button => button.addEventListener("click", closeSwapModal));

// =============================================================================
// VECKOTYPER
// =============================================================================
// A week type is two things, kept apart on purpose:
//   filter    which recipes are even eligible - "a vegetarian week" is a
//             statement about the food, not about the optimiser
//   objective what to optimise among the eligible ones
//
// Every type still runs through the SAME planner as before, so a week is
// always inside the budget, for the right number of people and dinners, and
// already filtered by allergies, diet and disliked dishes (see
// weekPlanCandidates). A type narrows the choice; it never overrides those.
//
// A type whose filter leaves too few recipes to fill the week is not shown at
// all, rather than shown and then quietly filled with something else.
const PLAN_TYPES = [
  {
    // FREE. The one week type everyone can build: the same planner, the
    // same real prices, no themed filter.
    key: "standard", label: "Standardvecka", objective: "balanced",
    hint: "En vanlig, varierad matvecka som håller din budget.",
    feature: "standard_week",
    filter: () => true,
  },
  {
    key: "familj", label: "Familjevecka", objective: "balanced", feature: "family_week",
    hint: "Rätter hela familjen äter, utan krångel.",
    filter: recipe => hasTag(recipe, "barn") || recipe.typ === "Familjefavorit",
    highlight: combo => `${combo.filter(r => hasTag(r, "barn")).length} av ${combo.length} är barnfavoriter`,
  },
  {
    key: "budget", feature: "budget_week", label: "Budgetvecka", objective: "cheapest",
    hint: "Lägsta kassakostnaden för veckan.",
    filter: () => true,
    // No highlight: the per-portion price on this card comes from the real
    // pricing fill-in, and a second, estimate-based figure next to it would
    // contradict it.
  },
  {
    key: "traning", feature: "training_week", label: "Träningsvecka", objective: "protein",
    hint: "Mycket protein per portion, jämnt över veckan.",
    filter: recipe => recipe.protein >= 25,
    highlight: combo => `${Math.round(combo.reduce((sum, r) => sum + r.protein, 0) / combo.length)} g protein per portion i snitt`,
  },
  {
    key: "bulk", feature: "bulk_week", label: "Bulkvecka", objective: "protein",
    hint: "Kalorier och protein för den som bygger.",
    // 500 kcal and 25 g protein - the real bulk rule. It was temporarily
    // 450 when the bank held 58 recipes and only 7 qualified; the bank now
    // holds 200+ with 88 qualifying, so the honest threshold is back.
    filter: recipe => recipe.kcal >= 500 && recipe.protein >= 25,
    highlight: combo => `${Math.round(combo.reduce((sum, r) => sum + r.kcal, 0) / combo.length)} kcal per portion i snitt`,
  },
  {
    key: "snabb", feature: "quick_week", label: "Snabb vecka", objective: "balanced",
    hint: "Allt på bordet inom 25 minuter.",
    filter: recipe => recipe.tid <= 25,
    highlight: combo => `längst ${Math.max(...combo.map(r => r.tid))} min per middag`,
  },
  {
    key: "vegetarisk", feature: "vegetarian_week", label: "Vegetarisk vecka", objective: "balanced",
    hint: "Helt utan kött och fisk.",
    filter: recipe => hasTag(recipe, "vegetariskt"),
    highlight: combo => `${combo.filter(r => hasTag(r, "veganskt")).length} av ${combo.length} är dessutom veganska`,
  },
  {
    key: "balanserad", feature: "balanced_week", label: "Balanserad vecka", objective: "balanced",
    hint: "Variation mellan kött, fisk och vegetariskt.",
    filter: () => true,
    highlight: combo => `${new Set(combo.map(r => r.proteinkalla)).size} olika proteinkällor`,
  },
];

// A week needs real choice, not just enough recipes to fill the days - with
// exactly `middagar` eligible recipes there is only one possible week, which
// is not a plan, it is a coincidence.
const MIN_CANDIDATES_PER_TYPE = 2;
function priciestBranchFor(combo) {
  return nearbyBranches().reduce((worst, candidate) => { const cost = shoppingListCost(combo, candidate); return !worst || cost > worst.cost ? { branch: candidate, cost } : worst; }, null);
}
function planCardMarkup(plan, branch) {
  const portions = plan.combo.length * state.personer;
  // The number on a plan card comes from the REAL pricing API, filled in by
  // syncPlanPricing right after render. The static estimate still steers
  // which recipes fit the budget - that is planning, not a price claim - but
  // it is never printed: "637 kr hos Willys" computed from a hardcoded
  // catalogue is exactly the fabricated store total this app must not show.
  const locked = plan.feature ? !can(plan.feature) : false;
  const chooseButton = locked
    ? `<button class="btn btn-primary plan-locked-btn" type="button" data-plan-paywall="${plan.key}"><span>Lås upp med Premium</span></button>`
    : `<button class="btn btn-primary" type="button" data-choose-plan="${plan.key}"><span>Välj den här</span></button>`;
  return `<div class="plan-card ${locked ? "plan-card-locked" : ""}"><div class="plan-card-head"><strong>${locked ? "" : ""}${plan.label}</strong><span>${plan.hint}</span></div><div class="plan-card-price" data-plan-price="${plan.key}"><b>pris beräknas…</b><small>mot riktiga butikspriser</small></div>${plan.highlight ? `<p class="plan-card-highlight">${escapeHtml(String(plan.highlight(plan.combo, plan.cost, portions)))}</p>` : ""}<ul class="plan-card-meals">${plan.combo.map(recipe => `<li>${escapeHtml(recipe.namn)}</li>`).join("")}</ul>${chooseButton}</div>`;
}

// Prices every plan card against Matjakt's own price database - the same
// endpoint, the same package maths and the same coverage rules as the
// basket. One request per plan, in parallel; a card whose request fails says
// "pris saknas" rather than falling back to the catalogue estimate.
async function syncPlanPricing(plans) {
  await Promise.all(plans.map(async plan => {
    const recipeIds = plan.combo.filter(recipe => recipe.priceStatus !== "unavailable")
      .map(recipe => recipe.id);
    const box = () => document.querySelector(`[data-plan-price="${CSS.escape(plan.key)}"]`);
    if (!recipeIds.length) { const t = box(); if (t) t.innerHTML = `<b class="price-missing">Pris saknas just nu</b>`; return; }
    try {
      const response = await fetch(pricingWeekApiUrl(), {
        method: "POST",
        headers: pricingHeaders(),
        body: JSON.stringify({ recipeIds, people: state.personer, pantry: pantryForPricing(),
          ...(Object.keys(storeSelectionForPricing()).length ? { stores: storeSelectionForPricing() } : {}) }),
        signal: AbortSignal.timeout(20000),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const results = (data.results || []).filter(r => (r.realPriceItems || 0) > 0);
      // The chain the user is actually shopping at when it priced anything,
      // otherwise the cheapest chain that did.
      const result = results.find(r => r.chain === chosenStore())
        || results.sort((a, b) => a.totalCheckoutCost - b.totalCheckoutCost)[0];
      const target = box();
      if (!target) return; // modalen är stängd
      if (!result) { target.innerHTML = `<b class="price-missing">Pris saknas just nu</b>`; return; }
      const portionsNow = plan.combo.length * state.personer;
      target.innerHTML = `<b>${money(result.totalCheckoutCost)}</b><small>ca ${money(result.totalCheckoutCost / portionsNow)} / portion · ${result.realPriceItems} av ${result.totalItems} varor prissatta hos ${escapeHtml(result.chain)}</small>`;
    } catch {
      const target = box();
      if (target) target.innerHTML = `<b class="price-missing">Pris saknas just nu</b>`;
    }
  }));
}
function openPlanComparison() {
  const branch = selectedBranch();
  const { candidates, nutritionShortfall } = weekPlanCandidates();
  updateNutritionWarning(nutritionShortfall);
  if (!candidates.length) { chooseMenu(); return; }
  const plans = PLAN_TYPES.map(type => {
    // The type's own filter first, THEN the planner. Filtering afterwards
    // would let the optimiser pick a week and only then discover half of it
    // does not belong in this type.
    const eligible = candidates.filter(type.filter);
    if (eligible.length < state.middagar + MIN_CANDIDATES_PER_TYPE) return null;
    const combo = bestMenuCombo(eligible, state.middagar, state.budget, branch, type.objective);
    if (!combo.length) return null;
    return { ...type, combo, cost: shoppingListCost(combo, branch) };
  }).filter(Boolean);
  if (plans.length < 2) { chooseMenu(); return; }
  $("planCards").innerHTML = plans.map(plan => planCardMarkup(plan, branch)).join("");
  document.querySelectorAll("[data-plan-paywall]").forEach(button =>
    button.addEventListener("click", () => { closePlanModal(); openPaywall(); }));
  syncPlanPricing(plans);
  document.querySelectorAll("[data-choose-plan]").forEach(button => button.addEventListener("click", () => {
    const plan = plans.find(candidate => candidate.key === button.dataset.choosePlan);
    const priciest = priciestBranchFor(plan.combo);
    // A genuine price difference, not just "more than one branch nearby" -
    // every branch's static estimate uses the same prisfaktor:1 (see
    // shoppingListCost), so priciest.cost === plan.cost whenever no live
    // price data was actually used, regardless of how many branches exist.
    // Without this, "Du sparar" showed a literal "0 kr" for that structurally
    // guaranteed-zero case instead of the honest "underlag saknas" state.
    const hasRealComparison = (priciest?.cost || plan.cost) > plan.cost;
    // EN POST PER VECKA, inte per klick. Att öppna jämförelsen tre gånger
    // och välja varje gång gav förut tre poster som alla summerades - samma
    // vecka räknades som tre veckors besparing. Posten ersätts därför på
    // veckonyckeln i stället för att läggas till.
    //
    // Nyckeln är veckans plan, inte dagens datum: byter man vecka samma dag
    // är det en ny handling, och väljer man om samma vecka är det inte det.
    const veckoNyckel = weekKeyFor(plan.combo.map(recipe => recipe.id));
    const post = {
      date: new Date().toISOString().slice(0, 10),
      weekKey: veckoNyckel,
      savings: Math.max(0, (priciest?.cost || plan.cost) - plan.cost),
      hasComparison: hasRealComparison,
      branch: branch?.namn || "",
      portionCost: plan.cost / (plan.combo.length * state.personer),
    };
    state.savingsLog = recordWeekSaving(state.savingsLog, post).slice(-60);
    state.swapsThisWeek = 0;
    setWeekPlan(plan.combo.map(recipe => recipe.id));
    state.avklarade.clear();
  state.harHemma.clear();
    // Samma regel som i chooseMenu: en ny vecka är en ny lista, och förra
    // veckans "finns hemma"-borttagningar får inte tyst filtrera bort samma
    // ingrediensnamn ur den nya.
    state.removedItems.clear();
    clearPriceSnapshots();
    saveState(); render(); closePlanModal(); setView("week");
  }));
  $("planModal").hidden = false;
}
function closePlanModal() { $("planModal").hidden = true; }
document.querySelectorAll("[data-plan-close]").forEach(button => button.addEventListener("click", closePlanModal));

function logEntriesSince(daysAgo) {
  const cutoff = Date.now() - daysAgo * 86400000;
  return state.savingsLog.filter(entry => new Date(entry.date).getTime() >= cutoff);
}
function reusedIngredientCount() {
  const selected = selectedRecipes();
  if (!selected.length) return 0;
  const shoppingItems = aggregateShopping(selected);
  return shoppingItems.filter(item => selected.filter(recipe => recipe.ingredienser.includes(item.namn)).length > 1).length;
}
function renderStats() {
  const weekEntries = logEntriesSince(7).filter(entry => entry.hasComparison);
  const monthEntries = logEntriesSince(30).filter(entry => entry.hasComparison);
  const savedWeek = weekEntries.reduce((sum, entry) => sum + entry.savings, 0);
  const savedMonth = monthEntries.reduce((sum, entry) => sum + entry.savings, 0);
  // OFTAST VALD, INTE BILLIGAST. Det här är läget av entry.branch - alltså
  // vilken butik användaren valt flest gånger. Ingen prisjämförelse ingår.
  // Etiketten hette "Billigaste butiken för dig", vilket var ett osant
  // påstående om användarens pengar: en butik kan vara vald av vana, för
  // att den ligger nära, eller för att den var förvald.
  const branchCounts = {};
  state.savingsLog.forEach(entry => { if (entry.branch) branchCounts[entry.branch] = (branchCounts[entry.branch] || 0) + 1; });
  const mostChosenName = Object.entries(branchCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || selectedBranch()?.namn || "-";
  const avgPortion = state.savingsLog.length ? state.savingsLog.reduce((sum, entry) => sum + entry.portionCost, 0) / state.savingsLog.length : 0;
  const reused = reusedIngredientCount();
  $("statSavedWeek").textContent = weekEntries.length ? money(savedWeek) : "Underlag saknas";
  $("statSavedMonth").textContent = monthEntries.length ? money(savedMonth) : "Underlag saknas";
  $("statCheapestStore").textContent = mostChosenName;
  $("statAvgPortion").textContent = state.savingsLog.length ? money(avgPortion) : "-";
  $("statWasteReduced").textContent = reused ? `${plural(reused, "ingrediens", "ingredienser")} återanvänds i flera rätter denna vecka` : "Skapa en vecka för att se detta";
  // The hero savings card only ever shows REAL arithmetic: the server's own
  // verdict for the CURRENT week (cheapest vs priciest comparable chain).
  // The old estimate-based log said "Uppskattat sparat" - a number nobody
  // could pay or verify. When the data cannot carry a claim, the card says
  // so instead of decorating a guess.
  const comparison = state.dbComparison;
  const realSaving = comparison?.cheapestChain && comparison?.savings > 1 && !comparison.locked
    ? comparison.savings
    : comparison?.locked && comparison?.priceSpread > 1 ? comparison.priceSpread : null;
  if (realSaving != null) {
    $("openStatsBtn").hidden = false;
    $("savingsCardValue").textContent = money(realSaving);
    $("savingsCardSubtitle").textContent = comparison.locked
      ? "så mycket skiljer det mellan butikerna den här veckan"
      : `genom att handla veckan hos ${comparison.cheapestChain}`;
  } else {
    // Ingen rad alls när det inte finns något sant att säga - en synlig
    // ursäkt ("kan inte beräknas ännu...") är bara brus på Hem.
    $("openStatsBtn").hidden = true;
    $("savingsCardValue").textContent = "–";
    $("savingsCardSubtitle").textContent = selectedRecipes().length
      ? "Kan inte beräknas ännu – kräver två jämförbara butiker"
      : "Skapa din första vecka för att se detta";
  }
}
$("openStatsBtn").addEventListener("click", () => { renderStats(); setView("stats"); });
$("homeShoppingStat").addEventListener("click", () => setView("basket"));

// Fyra steg, inte sju. En förstagångare ska svara på det Matjakt inte kan
// gissa - vilka ni är, vad ni vill lägga, vad ni inte äter, var ni handlar -
// och sedan SE sin vecka. Tidsfiltret bor i Recept-fliken, "något ni hellre
// slipper" och kalorier/makron i "Justera veckan"; mitt i onboardingen var de
// bara friktion (och ett Premium-formulär för någon som inte ens sett appen).
const ONBOARDING_STEPS = [
  { title: "Vilka är ni hemma?", render: renderObHushall },
  { title: "Budget & antal middagar", render: renderObBudget },
  { title: "Kost & allergier", render: renderObKost },
  { title: "Var handlar ni?", render: renderObButik },
];
let onboardingStep = 0;
function renderObHushall() {
  return `<div class="settings-grid"><div><label>Vuxna</label><div class="stepper"><button type="button" data-ob-adj="vuxna" data-delta="-1" aria-label="Färre vuxna">−</button><span>${state.hushall.vuxna}</span><button type="button" data-ob-adj="vuxna" data-delta="1" aria-label="Fler vuxna">+</button></div></div><div><label>Barn</label><div class="stepper"><button type="button" data-ob-adj="barn" data-delta="-1" aria-label="Färre barn">−</button><span>${state.hushall.barn}</span><button type="button" data-ob-adj="barn" data-delta="1" aria-label="Fler barn">+</button></div></div></div>`;
}
function renderObBudget() {
  return `<label for="obBudget">Veckobudget</label><div class="budget-row"><input type="number" id="obBudget" value="${state.budget}" min="0" step="50" inputmode="numeric"><span>kr</span></div><p class="budget-scope">${escapeHtml(budgetScopeText())}</p><div class="settings-grid"><div><label>Middagar per vecka</label><div class="stepper"><button type="button" data-ob-meals="-1" aria-label="Färre middagar">−</button><span>${state.middagar}</span><button type="button" data-ob-meals="1" aria-label="Fler middagar">+</button></div></div></div>`;
}
function renderObKost() {
  return `<label for="obKosttyp">Kosttyp</label><select id="obKosttyp"><option value="" ${!state.kost.kosttyp ? "selected" : ""}>Vanlig, allt</option><option value="vegetariskt" ${state.kost.kosttyp === "vegetariskt" ? "selected" : ""}>Vegetariskt</option><option value="veganskt" ${state.kost.kosttyp === "veganskt" ? "selected" : ""}>Veganskt</option></select><label>Allergier att undvika</label><div class="protein-source-chips" id="obAllergenChips">${ALLERGENS.map(a => `<label><input type="checkbox" value="${a}" ${state.kost.avoidAllergens.has(a) ? "checked" : ""}> ${a[0].toUpperCase() + a.slice(1)}</label>`).join("")}</div>`;
}
function renderObButik() {
  return `<label for="obPostcode">Postnummer</label><div class="location-row"><input id="obPostcode" value="${escapeHtml(state.postnummer)}" inputmode="numeric" maxlength="5"><button type="button" id="obLocateBtn">Hitta mig</button></div><p class="ob-error" id="obPostcodeError"></p><label for="obStore">Favoritbutik</label><select id="obStore">${storeOptionsMarkup(state.butik, "Välj åt mig")}</select>`;
}
function wireOnboardingStep() {
  document.querySelectorAll("[data-ob-adj]").forEach(button => button.addEventListener("click", () => {
    const key = button.dataset.obAdj, delta = Number(button.dataset.delta), min = key === "vuxna" ? 1 : 0;
    state.hushall[key] = Math.max(min, state.hushall[key] + delta);
    state.personer = Math.min(12, Math.max(1, state.hushall.vuxna + state.hushall.barn));
    saveState(); renderOnboardingStep();
  }));
  $("obBudget")?.addEventListener("input", e => { state.budget = clampBudget(e.target.value); saveState(); });
  document.querySelectorAll("[data-ob-meals]").forEach(button => button.addEventListener("click", () => {
    state.middagar = Math.min(Math.min(MAX_MEALS, maxDinners()), Math.max(1, state.middagar + Number(button.dataset.obMeals)));
    saveState(); renderOnboardingStep();
  }));
  $("obKosttyp")?.addEventListener("change", e => { state.kost.kosttyp = e.target.value; saveState(); });
  document.querySelectorAll("#obAllergenChips input").forEach(box => box.addEventListener("change", () => { state.kost.avoidAllergens = new Set([...document.querySelectorAll("#obAllergenChips input:checked")].map(b => b.value)); saveState(); }));
  $("obPostcode")?.addEventListener("input", e => {
    const previous = state.postnummer;
    state.postnummer = e.target.value.replace(/\D/g, "").slice(0, 5);
    if (state.postnummer !== previous) clearLocationDerivedState();
    saveState();
    syncNearbyBranches();
  });
  $("obStore")?.addEventListener("change", e => { state.butik = e.target.value; saveState(); });
  $("obLocateBtn")?.addEventListener("click", () => { if (!navigator.geolocation) return; navigator.geolocation.getCurrentPosition(({ coords }) => { state.position = { lat: coords.latitude, lon: coords.longitude }; saveState(); }, () => {}); });
}
function renderOnboardingStep() {
  const current = ONBOARDING_STEPS[onboardingStep];
  $("onboardingTitle").textContent = current.title;
  $("onboardingBody").innerHTML = current.render();
  wireOnboardingStep();
  $("onboardingDots").innerHTML = ONBOARDING_STEPS.map((_, index) => `<i class="${index === onboardingStep ? "active" : ""}"></i>`).join("");
  $("onboardingBack").hidden = onboardingStep === 0;
  $("onboardingNext").querySelector("span").textContent = onboardingStep === ONBOARDING_STEPS.length - 1 ? "Skapa min vecka" : "Nästa";
}
function openOnboarding() { onboardingStep = 0; $("onboardingModal").hidden = false; renderOnboardingStep(); }
function closeOnboarding() { $("onboardingModal").hidden = true; }
$("onboardingNext").addEventListener("click", () => {
  if (onboardingStep === ONBOARDING_STEPS.length - 1) {
    if (!/^\d{5}$/.test(state.postnummer)) { $("obPostcodeError").textContent = "Ange ett giltigt postnummer (5 siffror)."; return; }
    state.onboardingComplete = true; saveState(); closeOnboarding(); syncNearbyBranches(); openPlanComparison();
    return;
  }
  onboardingStep++; renderOnboardingStep();
});
$("onboardingBack").addEventListener("click", () => { onboardingStep = Math.max(0, onboardingStep - 1); renderOnboardingStep(); });
$("onboardingSkip").addEventListener("click", () => { state.onboardingComplete = true; saveState(); closeOnboarding(); });

function openAccountModal() { $("accountModal").hidden = false; }
function closeAccountModal() { $("accountModal").hidden = true; $("loginError").textContent = ""; $("registerError").textContent = ""; $("redeemError").textContent = ""; $("forgotError").textContent = ""; $("resetError").textContent = ""; $("deleteError").textContent = ""; }
$("profileBtn").addEventListener("click", openAccountModal);
document.querySelectorAll("[data-account-close]").forEach(button => button.addEventListener("click", closeAccountModal));
function showAccountForm(name) {
  $("accountLoginForm").hidden = name !== "login";
  $("accountRegisterForm").hidden = name !== "register";
  $("forgotPasswordForm").hidden = name !== "forgot";
  $("resetPasswordForm").hidden = name !== "reset";
  document.querySelectorAll("[data-account-tab]").forEach(t => t.classList.toggle("active", t.dataset.accountTab === name));
}
document.querySelectorAll("[data-account-tab]").forEach(tab => tab.addEventListener("click", () => showAccountForm(tab.dataset.accountTab)));
$("forgotPasswordLink").addEventListener("click", () => showAccountForm("forgot"));
$("backToLoginLink").addEventListener("click", () => showAccountForm("login"));
// Servern skickar en maskinläsbar kod när mejl inte kan gå iväg - texten
// här lovar aldrig ett mejl som inte skickats.
function mailErrorText(error) {
  if (error.code === "MAIL_NOT_CONFIGURED") return "E-postutskick är inte aktiverat på servern ännu. Kontakta support så hjälper vi dig.";
  if (error.code === "MAIL_SEND_FAILED") return "Mejlservern svarar inte just nu. Försök igen om en stund.";
  return error.message;
}
$("forgotPasswordForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("forgotError").textContent = ""; $("forgotSuccess").hidden = true;
  try {
    await requestPasswordReset($("forgotEmail").value);
    $("forgotSuccess").hidden = false;
    event.target.reset();
  } catch (error) { $("forgotError").textContent = mailErrorText(error); }
});
// Redan ur adressfältet vid start (takeUrlTokens överst); härifrån och
// framåt finns token bara i den här variabeln.
let pendingResetToken = urlTokens.reset;
$("resetPasswordForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("resetError").textContent = "";
  try {
    await resetPassword(pendingResetToken, $("resetPasswordInput").value);
    pendingResetToken = null;
    showAccountForm("login");
    $("loginError").textContent = "Lösenordet är ändrat. Logga in med det nya lösenordet.";
    event.target.reset();
  } catch (error) { $("resetError").textContent = error.message; }
});
$("marketingToggle").addEventListener("change", async event => {
  if (!state.authToken) return;
  const wanted = event.target.checked;
  try {
    const { user } = await setMarketingConsent(state.authToken, wanted);
    state.user = user;
  } catch {
    event.target.checked = !wanted; // servern sa nej: visa sanningen, inte önskan
  }
  renderAccount();
});
$("resendVerificationBtn").addEventListener("click", async () => {
  $("verifyError").textContent = "";
  try {
    await resendVerification(state.authToken);
    $("verifyError").textContent = "Skickat! Kolla din inkorg (och skräpposten).";
  } catch (error) { $("verifyError").textContent = mailErrorText(error); }
});
$("deleteAccountBtn").addEventListener("click", async () => {
  $("deleteError").textContent = "";
  if (!confirm("Radera ditt konto permanent? Det går inte att ångra.")) return;
  try {
    await deleteAccount(state.authToken);
    state.authToken = null; state.user = null; storeToken(null);
    clearHouseholdSession();
    closeAccountModal(); renderAccount();
  } catch (error) { $("deleteError").textContent = error.message; }
});
async function refreshUser() {
  fetchEntitlements();
  if (!state.authToken) { renderAccount(); return; }
  try {
    const { user } = await fetchCurrentUser(state.authToken);
    state.user = user;
    await pullAccountState();
  } catch (error) {
    // Bara en avvisad session (401) loggar ut. Ett nätfel eller ett
    // tillfälligt serverfel ska inte kasta ut användaren ur sitt konto.
    if (error?.status === 401) {
      state.authToken = null;
      storeToken(null);
      state.user = null;
    }
  }
  renderAccount();
  // Hushållet hämtas EFTER kontot: utan ett giltigt user_id finns inget
  // medlemskap att slå upp.
  loadHousehold().then(loadNotifications);
  // Editing a goal already regenerates the week directly (see
  // onNutritionGoalsChanged) - doing it again here unconditionally on every
  // login/session refresh would silently wipe checked-off items and cached
  // prices on every app open for premium users with goals set, for no reason
  // (nothing about their existing week actually changed).
  if (hasPremium() && hasActiveNutritionGoals(currentNutritionGoals()) && !state.valda.size) chooseMenu(false);
  renderCampaignSection();
}
let ownCampaignFetchKey = null;
let ownCampaignDeals = [];
async function renderOwnCampaigns() {
  if (ownCampaignFetchKey === "done") return;
  ownCampaignFetchKey = "done";
  // Ett lugnt laddläge - utan det står rubriken över en tom rad i upp till
  // 15 sekunder innan hämtningen svarar.
  $("campaignList").innerHTML = `<p class="live-loading">Hämtar veckans fynd…</p>`;
  try {
    const response = await fetch(`${API_BASE_URL}/grocery/campaigns`, { signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    campaignRetryCount = 0;
    const all = Object.values(data.deals || {}).flat()
      .sort((a, b) => b.discountPercent - a.discountPercent);
    if (!all.length) { $("campaignList").innerHTML = `<p class="live-loading">Inga kampanjer i butikernas data just nu.</p>`; return; }
    $("campaignList").innerHTML = all.slice(0, 18).map(deal => {
      const photo = deal.imageUrl ? `<img src="${escapeHtml(safeHttpUrl(deal.imageUrl) || "")}" alt="" loading="lazy">` : categoryIconMarkup("Övrigt");
      const storeColor = CHAIN_COLORS[deal.chain] || "var(--primary)";
      const added = state.extraItems.some(e => e.source === "campaign" && e.productId === deal.productId);
      const addButton = added
        ? `<button type="button" class="campaign-deal-add added" disabled>✓ Tillagd</button>`
        : `<button type="button" class="campaign-deal-add" data-deal-add="${escapeHtml(String(deal.productId))}">+ Lägg i inköpslistan</button>`;
      return `<div class="campaign-deal"><span class="campaign-deal-image">${photo}<span class="campaign-deal-badge">−${deal.discountPercent}%</span></span><span class="campaign-deal-info"><strong>${escapeHtml(deal.name)}</strong>${deal.brand || deal.size ? `<small class="campaign-deal-brand">${escapeHtml([deal.brand, deal.size].filter(Boolean).join(" · "))}</small>` : ""}<span class="campaign-deal-price-row"><strong class="campaign-deal-price">${money(deal.campaignPrice)}</strong><s>${money(deal.regularPrice)}</s></span>${deal.lowestSeen != null ? (deal.campaignPrice <= deal.lowestSeen ? `<small class="campaign-history good">Lägsta pris vi sett</small>` : `<small class="campaign-history">Har nyligen kostat ${money(deal.lowestSeen)}</small>`) : ""}<span class="campaign-deal-store" style="color:${storeColor}">${escapeHtml(deal.chain)}</span>${addButton}<button type="button" class="campaign-follow ${state.foljdaVaror.some(f => f.name === deal.name) ? "following" : ""}" data-deal-follow="${escapeHtml(deal.name)}" aria-label="Följ ${escapeHtml(deal.name)}">${state.foljdaVaror.some(f => f.name === deal.name) ? "♥ Följer" : "♡ Följ varan"}</button></span></div>`;
    }).join("");
    ownCampaignDeals = all;
    document.querySelectorAll("[data-deal-follow]").forEach(button => button.addEventListener("click", () => {
      const name = button.dataset.dealFollow;
      const deal = ownCampaignDeals.find(d => d.name === name);
      const already = state.foljdaVaror.some(f => f.name === name);
      // Grunden för prisbevakningar: en följd vara är namn+gtin, inget mer.
      // Notisen som säger till när priset dyker kommer med App Store-appen.
      state.foljdaVaror = already
        ? state.foljdaVaror.filter(f => f.name !== name)
        : [...state.foljdaVaror, { name, gtin: deal?.gtin || null, chain: deal?.chain || null }];
      saveState();
      button.classList.toggle("following", !already);
      button.textContent = already ? "♡ Följ varan" : "♥ Följer";
    }));
    document.querySelectorAll("[data-deal-add]").forEach(button => button.addEventListener("click", () => {
      const deal = ownCampaignDeals.find(d => String(d.productId) === button.dataset.dealAdd);
      if (!deal) return;
      trackEvent("fynd_tillagt"); addExtraItem({
        name: deal.name, source: "campaign", chain: deal.chain,
        productId: deal.productId, gtin: deal.gtin, imageUrl: deal.imageUrl,
        packageSize: deal.size, campaignPrice: deal.campaignPrice,
        regularPrice: deal.regularPrice, validUntil: deal.validUntil,
      });
      button.textContent = "✓ Tillagd"; button.disabled = true; button.classList.add("added");
    }));
  } catch {
    ownCampaignFetchKey = null;
    $("campaignList").innerHTML = `<p class="live-loading">Kunde inte hämta erbjudanden just nu - försöker igen strax.</p>`;
    // Utan egen omstart låg felet kvar tills någon annan render råkade ske.
    setTimeout(() => renderOwnCampaigns(), retryDelay(campaignRetryCount++));
  }
}

async function renderCampaignSection() {
  renderOwnCampaigns();
}

// "Visa alla" scrollar raden till sitt slut i stället för att öppna en
// separate "all campaigns" page that doesn't exist, so it's a real action
// and not a dead link.
$("campaignShowAllBtn").addEventListener("click", () => $("campaignList").scrollTo({ left: $("campaignList").scrollWidth, behavior: "smooth" }));
$("hemShowAllRecipesBtn").addEventListener("click", () => setView("recipes"));
// Sara klickar Adams inbjudningslänk, trycker "Logga in och gå med" och
// loggar in - och landade förr i en tom app: inbjudan hanterades bara vid
// sidladdningen. Nu fullföljs den så fort en session finns.
async function resumePendingInvite() {
  if (!pendingInviteToken || !state.authToken || householdActive()) return;
  try {
    const { household } = await joinHousehold(state.authToken, pendingInviteToken);
    state.household = applySync(emptyHouseholdState(), { household, revision: 0 });
    await pullHousehold(true);
    startHouseholdSync();
    clearInviteFromUrl();
    $("inviteLanding").hidden = true;
    renderAccount();
    render();
    showUndoToast(`Du är med i ${household.name}`, null);
  } catch {
    // Länken kan ha hunnit gå ut eller redan använts - visa landningen igen
    // med sitt eget felmeddelande i stället för att tiga.
    handlePendingInvite();
  }
}

$("accountLoginForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("loginError").textContent = "";
  try {
    const { token, user } = await login($("loginEmail").value, $("loginPassword").value);
    state.authToken = token; state.user = user; storeToken(token);
    await pullAccountState();
    event.target.reset(); renderAccount(); closeAccountModal();
    await resumePendingInvite();
  } catch (error) { $("loginError").textContent = error.message; }
});
$("accountRegisterForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("registerError").textContent = "";
  try {
    const { token, user, verificationMail } = await register($("registerEmail").value, $("registerPassword").value, $("registerMarketing").checked);
    state.authToken = token; state.user = user; storeToken(token);
    await pullAccountState();
    event.target.reset(); renderAccount();
    if (verificationMail && verificationMail !== "sent") {
      // Kontot finns, men mejlet gick inte iväg - säg det, stäng inte tyst.
      $("verifyError").textContent = verificationMail === "failed"
        ? "Kontot är skapat, men verifieringsmejlet kunde inte skickas. Prova \"Skicka verifieringsmejl igen\" om en stund."
        : "Kontot är skapat. E-postverifiering är inte aktiverad på servern ännu - du kan använda Matjakt som vanligt.";
    } else {
      closeAccountModal();
    }
    await resumePendingInvite();
  } catch (error) { $("registerError").textContent = error.message; }
});
$("accountRedeemForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("redeemError").textContent = "";
  try {
    const { user } = await redeemPremium(state.authToken, $("premiumCode").value);
    state.user = user; renderAccount(); event.target.reset(); chooseMenu(false); renderCampaignSection();
  } catch (error) { $("redeemError").textContent = error.message; }
});
// The paywall sells VALUE, never just says "Premium krävs". Opened from
// every locked control; prices come from the central config via
// /api/entitlements, so 59/399 exist in exactly one place (the backend).
function openPaywall(triggerFeature = "") {
  const pricing = premiumPricing();
  const yearly = pricing.yearly || {};
  const monthly = pricing.monthly || {};
  let modal = document.getElementById("paywallModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "paywallModal";
    modal.className = "modal paywall-modal";
    document.body.appendChild(modal);
  }
  modal.innerHTML = `<div class="modal-card paywall-card">
    <button type="button" class="modal-close" data-paywall-close aria-label="Stäng">×</button>
    <p class="eyebrow">Matjakt Premium</p>
    <h2>Lås upp hela matveckan</h2>
    <p class="paywall-lead">Planera veckan efter familj, budget eller träning. Jämför riktiga matpriser hos alla kvalificerade butiker och få exakt inköpslista för varje butik.</p>
    <ul class="paywall-points">
      <li>Alla 7 veckotyper och 1–7 middagar</li>
      <li>Alla butikers riktiga priser och butikskorgar</li>
      <li>Näringsmål, kcal- och proteinfilter</li>
      <li>Fullt skafferi och "Laga med det jag har"</li>
    </ul>
    <button type="button" class="btn btn-primary paywall-yearly" data-paywall-plan="yearly">
      <span class="paywall-plan-label">${escapeHtml(yearly.badge || "Bäst värde")}</span>
      <strong>${escapeHtml(yearly.priceText || "399 kr/år")}</strong>
      <small>${escapeHtml(yearly.perMonthText || "≈ 33 kr/mån")} · ${escapeHtml(yearly.savingsText || "Spara 309 kr jämfört med månadsbetalning")}</small>
    </button>
    <button type="button" class="btn btn-ghost paywall-monthly" data-paywall-plan="monthly">
      <strong>${escapeHtml(monthly.priceText || "59 kr/mån")}</strong>
    </button>
    ${withdrawalConsentMarkup("paywallWithdrawalConsent")}
    <p class="account-error" id="paywallError"></p>
    <button type="button" class="paywall-continue" data-paywall-close>Fortsätt gratis</button>
  </div>`;
  modal.hidden = false;
  modal.querySelectorAll("[data-paywall-close]").forEach(el =>
    el.addEventListener("click", () => { modal.hidden = true; }));
  modal.querySelectorAll("[data-paywall-plan]").forEach(el =>
    el.addEventListener("click", () => beginCheckout(el.dataset.paywallPlan, modal)));
}

// I native-appen (Capacitor) ska Stripe öppnas i systemets webbläsare -
// navigeras webviewen till stripe.com lämnar användaren appen och landar
// efteråt i webbversionen. Vid återkomst pollas Premium (visibilitychange).
function isNativeApp() { return Boolean(window.Capacitor?.isNativePlatform?.()); }
// Native-bryggan (native-bridge.js) ger window.Capacitor med isNativePlatform
// och nativePromise, men plugin-proxies skapas av @capacitor/core i JS.
// Core importeras därför dynamiskt BARA i native - esbuild buntar in den
// i native-bygget, och på webben körs raden aldrig (ingen bare-import i
// källläget). Plugin-paketens JS behövs inte: proxies talar med de
// native-pods som cap sync installerat (@capacitor/app, @capacitor/browser).
let nativePluginsReady = null;
function loadNativePlugins() {
  if (!isNativeApp()) return Promise.resolve(null);
  if (!nativePluginsReady) {
    nativePluginsReady = import("@capacitor/core")
      .then(({ registerPlugin }) => ({ App: registerPlugin("App"), Browser: registerPlugin("Browser") }))
      .catch(() => null);
  }
  return nativePluginsReady;
}
function openExternal(rawUrl) {
  // Bara https-adresser navigeras till - även om de kommer från vår egen
  // server ska en oväntad "javascript:"-sträng aldrig kunna köras.
  const url = safeHttpUrl(rawUrl);
  if (!url) return;
  if (isNativeApp()) {
    // @capacitor/browser (SFSafariViewController) när den finns; annars
    // window.open, som Capacitors webview lämnar till systemets webbläsare
    // (WebViewDelegationHandler.createWebViewWith → UIApplication.open).
    loadNativePlugins().then(plugins => {
      if (plugins?.Browser?.open) return plugins.Browser.open({ url }).catch(() => window.open(url, "_blank"));
      window.open(url, "_blank");
    });
    return;
  }
  location.href = url;
}
async function beginCheckout(plan, root = document.getElementById("paywallModal")) {
  if (!state.user) {
    document.getElementById("paywallModal").hidden = true;
    openAccountModal?.();
    return;
  }
  const errorLine = root?.querySelector("#paywallError");
  if (errorLine) errorLine.textContent = "";
  // Ångerrätten kryssas i FÖRE knappen, inte bort efteråt: en digital tjänst
  // som levereras direkt får bara undantas från fjorton dagars ångerrätt om
  // kunden uttryckligen avstått den. Servern vägrar ändå utan samtycket -
  // det här är bara för att slippa gå till servern för att få veta det.
  const consent = withdrawalConsentGiven(root);
  if (!consent) {
    const text = "Kryssa i rutan om ångerrätten för att kunna gå vidare till betalningen.";
    if (errorLine) errorLine.textContent = text; else alert(text);
    root?.querySelector("[data-withdrawal-consent]")?.focus();
    return;
  }
  try {
    await flushServerSync();
    const { url } = await startCheckout(getStoredToken(), plan, consent);
    if (url) { if (isNativeApp()) awaitingPremiumActivation = true; openExternal(url); }
  } catch (error) {
    const text = error?.message || "Kunde inte starta betalningen just nu.";
    if (errorLine) errorLine.textContent = text; else alert(text);
  }
}

function openPremiumPitch() { openPaywall(); }
let selectedPlan = "monthly";
document.querySelectorAll("[data-price-tab]").forEach(tab => tab.addEventListener("click", () => { selectedPlan = tab.dataset.plan; document.querySelectorAll("[data-price-tab]").forEach(t => t.classList.toggle("active", t === tab)); }));
$("subscribeBtn").addEventListener("click", async () => {
  $("checkoutError").textContent = "";
  if (!state.authToken) { $("checkoutError").textContent = "Skapa ett konto eller logga in först."; return; }
  const consent = withdrawalConsentGiven($("premiumPitch"));
  if (!consent) {
    $("checkoutError").textContent = "Kryssa i rutan om ångerrätten för att kunna gå vidare till betalningen.";
    $("premiumPitch").querySelector("[data-withdrawal-consent]")?.focus();
    return;
  }
  try {
    await flushServerSync();
    const { url } = await startCheckout(state.authToken, selectedPlan, consent);
    if (isNativeApp()) awaitingPremiumActivation = true;
    openExternal(url);
  } catch (error) { $("checkoutError").textContent = error.message; }
});
$("manageBillingBtn").addEventListener("click", async () => {
  $("portalError").textContent = "";
  try {
    await flushServerSync();
    const { url } = await openBillingPortal(state.authToken);
    openExternal(url);
  } catch (error) { $("portalError").textContent = error.message; }
});
$("logoutBtn").addEventListener("click", async () => {
  if (state.authToken) { try { await logoutRequest(state.authToken, state.pushDeviceToken || null); } catch { /* session redan ogiltig server-side, städa lokalt ändå */ } }
  state.authToken = null; state.user = null; storeToken(null);
  clearHouseholdSession();
  // Utloggning är ett byte av person, inte en paus: skafferi, vecka,
  // allergival och historik tillhör KONTOT. Kvarlämnat laddades det upp
  // till NÄSTA konto som registrerades på enheten (bootstrap-grenen i
  // pullAccountState) - förra användarens allergier och skafferi blev
  // den nyas. Inställningar av apparat-karaktär (postnummer, butik,
  // onboarding klar) får stanna.
  state.pantry = {};
  state.valda = new Set(); state.weekPlan = [];
  state.avklarade = new Set(); state.harHemma = new Set(); state.removedItems = new Set();
  state.favoriter = new Set(); state.ogillar = new Set();
  state.betyg = {}; state.feedback = {}; state.extraItems = [];
  state.kost = { kosttyp: "", avoidAllergens: new Set() };
  state.naringsmal = null; state.savingsLog = []; state.swapsThisWeek = 0;
  state.apiRecipes = []; state.dbChainTotals = {}; state.dbComparison = null;
  state.dbPricedAt = null; state.livePriser = {}; state.liveBranchTotals = {};
  saveState();
  renderAccount(); closeAccountModal(); render();
});
$("peopleMinus").addEventListener("click", () => step("personer", -1, 1, 12)); $("peoplePlus").addEventListener("click", () => step("personer", 1, 1, 12));
$("mealsMinus").addEventListener("click", () => step("middagar", -1, 1, MAX_MEALS));
$("mealsPlus").addEventListener("click", () => {
  // Free plans up to the server-decided cap; the fifth dinner is the
  // paywall's job to sell, not a dead button's job to refuse.
  if (state.middagar >= maxDinners() && !hasPremium()) { openPaywall("seven_dinners"); return; }
  step("middagar", 1, 1, Math.min(MAX_MEALS, maxDinners()));
});
// One primary action: create the week when there is none, open it when
// there is. "Skapa ny vecka" stays as a quiet secondary path.
$("generateBtn").addEventListener("click", () => {
  if (selectedRecipes().length) setView("week");
  else openPlanComparison();
});
$("newWeekBtn").addEventListener("click", () => openPlanComparison()); $("refreshBtn").addEventListener("click", () => {
  // Roterar ENDAST förslagsraden. Tidigare regenererades hela veckan (och
  // avbockade/borttagna varor rensades) plus att fliken byttes - av en knapp
  // som lovar nya förslag.
  RECEPT.push(...RECEPT.splice(0, 8));
  render();
});
$("startNewWeekBtn").addEventListener("click", () => openPlanComparison());
let pantryPickLocation = "skafferi";
function renderPantryPicker(query) {
  const search = query.trim().toLowerCase();
  const matches = Object.entries(PRODUCT_CATALOG).filter(([key, product]) => !search || key.toLowerCase().includes(search) || product.namn.toLowerCase().includes(search) || product.marke.toLowerCase().includes(search)).slice(0, 30);
  const typed = query.trim();
  // "Mjölk - generell": en vara utan varumärke är ett fullgott svar, inte
  // ett misslyckande. Erbjuds alltid, överst, så flödet aldrig kör fast.
  const generic = typed
    ? `<button type="button" class="pantry-pick generic" data-pantry-generic="${escapeHtml(typed)}"><span class="pantry-pick-info"><strong>${escapeHtml(typed)}</strong><small>Generell vara - utan märke</small></span><span class="pantry-pick-add">+ Lägg till</span></button>`
    : "";
  $("pantryPickerList").innerHTML = generic + (matches.length ? matches.map(([key, product]) => `<button type="button" class="pantry-pick" data-pantry-pick="${escapeHtml(key)}"><span class="pantry-pick-info"><strong>${escapeHtml(product.namn)}</strong><small>${escapeHtml([product.marke && product.marke !== "ICA" ? product.marke : "", product.storlek].filter(Boolean).join(" · "))}</small></span><span class="pantry-pick-add">+ Lägg till</span></button>`).join("") : "");
  document.querySelectorAll("[data-pantry-pick]").forEach(button => button.addEventListener("click", () => openPantryAddConfirm(button.dataset.pantryPick, PRODUCT_CATALOG[button.dataset.pantryPick])));
  document.querySelectorAll("[data-pantry-generic]").forEach(button => button.addEventListener("click", () => openPantryAddConfirm(button.dataset.pantryGeneric, { namn: button.dataset.pantryGeneric })));
}
let pantryLiveResults = [];
const debouncedPantrySearch = createDebouncedSearch((query, signal) => fetch(productApiUrl(chosenStore(), query), { signal }).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }), 300);
function renderPantryLiveSearch(query) {
  const search = query.trim();
  const chain = chosenStore();
  if (search.length < 2 || !VALID_CHAINS.includes(chain)) { $("pantryLiveResults").innerHTML = ""; return; }
  $("pantryLiveResults").innerHTML = `<p class="live-loading">Söker hos ${chain}...</p>`;
  debouncedPantrySearch(search).then(payload => {
    const data = sanitizeApiPayload(payload);
    pantryLiveResults = (data.produkter || []).slice(0, 12);
    $("pantryLiveResults").innerHTML = pantryLiveResults.length ? `<p class="pantry-picker-section-label">Från ${chain}</p>${pantryLiveResults.map((product, index) => `<button type="button" class="pantry-pick" data-pantry-pick-live="${index}">${product.bild ? `<img class="pantry-pick-photo" src="${product.bild}" alt="" loading="lazy">` : `<span class="pantry-pick-photo placeholder" aria-hidden="true">${escapeHtml(product.produktnamn.slice(0, 1))}</span>`}<span class="pantry-pick-info"><strong>${product.produktnamn}</strong><small>${product.marke_och_storlek || (product.pris_kr == null ? "Pris saknas" : `${product.pris_kr.toLocaleString("sv-SE", { minimumFractionDigits: 2 })} kr`)}</small></span><span class="pantry-pick-add">+ Lägg till</span></button>`).join("")}` : `<p class="pantry-picker-empty">Inga produkter hos ${chain} matchar "${escapeHtml(search)}".</p>`;
    document.querySelectorAll("[data-pantry-pick-live]").forEach(button => button.addEventListener("click", () => {
      const product = pantryLiveResults[Number(button.dataset.pantryPickLive)];
      if (product) openPantryAddConfirm(product.produktnamn, {
        namn: product.produktnamn, marke: product.marke_och_storlek || "", storlek: "",
        bild: product.bild || "", gtin: product.gtin || "",
      });
    }));
  }).catch(error => {
    if (error?.name === "AbortError") return;
    $("pantryLiveResults").innerHTML = `<p class="pantry-picker-empty">Kunde inte söka hos ${chain} just nu.</p>`;
  });
}
function openPantryAddConfirm(key, product) {
  pantryPickLocation = state.pantryTab;
  $("pantryPickerList").hidden = true; $("pantrySearch").hidden = true; $("pantryLiveResults").hidden = true;
  $("pantryAddConfirm").hidden = false;
  $("pantryAddConfirmName").textContent = product.namn;
  $("pantryAddExpiry").value = "";
  document.querySelectorAll("#pantryAddLocation button").forEach(button => button.classList.toggle("active", button.dataset.location === pantryPickLocation));
  $("pantryAddConfirmBtn").onclick = () => {
    // Ett påfyllt paket ska inte RADERA vad som redan är känt: lämnas
    // datumfältet tomt behålls befintligt bäst före-datum, och en vara som
    // redan har en plats behåller den om användaren inte aktivt bytt flik.
    const existing = pantryList().find(entry => entry.key === itemKeyFor(key, product.gtin));
    // Produktdata följer bara med när vi FAKTISKT har den. En generisk vara
    // ("Mjölk - generell") ska inte tilldelas ett varumärke vi gissat oss till.
    const productData = product.marke || product.storlek || product.bild || product.gtin
      ? { productName: product.namn, brand: product.marke || undefined,
          packageSize: product.storlek || undefined, gtin: product.gtin || undefined,
          imageUrl: product.bild || undefined }
      : null;
    addPantryItem({
      name: key,
      gtin: product.gtin,
      amount: (existing?.amount || 0) + (PACKAGE_INFO[key]?.amount || 1),
      unit: PACKAGE_INFO[key]?.unit || "st",
      location: pantryPickLocation,
      expiry: $("pantryAddExpiry").value || existing?.expiry || null,
      category: categoryFor(key),
      product: productData,
    });
    closePantryModal();
  };
}
document.querySelectorAll("#pantryAddLocation button").forEach(button => button.addEventListener("click", () => { pantryPickLocation = button.dataset.location; document.querySelectorAll("#pantryAddLocation button").forEach(b => b.classList.toggle("active", b === button)); }));
function openPantryModal() {
  $("pantrySearch").value = ""; $("pantrySearch").hidden = false; $("pantryPickerList").hidden = false; $("pantryLiveResults").hidden = false; $("pantryAddConfirm").hidden = true;
  renderPantryPicker(""); $("pantryLiveResults").innerHTML = ""; $("pantryModal").hidden = false; $("pantrySearch").focus();
}
function closePantryModal() { $("pantryModal").hidden = true; }
$("addPantryBtn").addEventListener("click", openPantryModal);
document.querySelectorAll("[data-pantry-close]").forEach(button => button.addEventListener("click", closePantryModal));
document.querySelectorAll("#pantryTabs button").forEach(button => button.addEventListener("click", () => { state.pantryTab = button.dataset.pantryTab; renderPantry(); }));
$("pantrySearch").addEventListener("input", e => { renderPantryPicker(e.target.value); renderPantryLiveSearch(e.target.value); });

function cookMatchRow(id, namn, matched, bild) {
  return `<button type="button" class="cook-match" data-cook-open="${escapeHtml(id)}">${bild ? `<img src="${escapeHtml(safeHttpUrl(bild) || "")}" alt="">` : `<span class="cook-match-fallback" aria-hidden="true"></span>`}<span class="cook-match-info"><strong>${escapeHtml(namn)}</strong><small>Matchar: ${matched.map(escapeHtml).join(", ")}</small></span></button>`;
}
function renderCookResults(localMatches, externalRecipes, hiddenByDiet = false) {
  const localHtml = localMatches.length ? `<h3>Från dina recept</h3><div class="cook-match-list">${localMatches.map(({ recipe, matched }) => cookMatchRow(recipe.id, recipe.namn, matched, recipe.bild)).join("")}</div>` : "";
  const externalHtml = hiddenByDiet
    ? `<p class="live-loading">Recept från receptdatabasen visas inte när kost-/allergifilter är aktivt, eftersom de inte har kontrollerade allergiuppgifter.</p>`
    : externalRecipes === null
    ? `<h3>Från receptdatabasen</h3><p class="live-loading">Söker fler recept...</p>`
    : externalRecipes.length
      ? `<h3>Från receptdatabasen</h3><div class="cook-match-list">${externalRecipes.map(recipe => cookMatchRow(recipe.id, recipe.title, recipe.matchedIngredients, recipe.imageUrl)).join("")}</div>`
      : localMatches.length ? "" : `<p class="live-loading">Inga recept hittades för det du har hemma just nu.</p>`;
  $("cookResults").innerHTML = (localHtml || externalHtml) ? localHtml + externalHtml : `<p class="live-loading">Lägg till varor i skafferiet så letar vi fram recept du kan laga direkt.</p>`;
  document.querySelectorAll("[data-cook-open]").forEach(button => button.addEventListener("click", () => { closeCookModal(); openRecipeTab(button.dataset.cookOpen); }));
}
async function openCookModal() {
  $("cookModal").hidden = false;
  const pantryNames = pantryNamesForCooking();
  const dietFilterActive = dietFilterIsActive();
  const localMatches = matchLocalRecipesToPantry(localRecipesForUser(), pantryNames);
  if (dietFilterActive) { renderCookResults(localMatches, [], true); return; }
  renderCookResults(localMatches, null);
  if (!pantryNames.length) { renderCookResults([], []); return; }
  try {
    const response = await fetch(recipesByPantryApiUrl(pantryNames), { signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderCookResults(localMatches, data.recipes || []);
  } catch {
    renderCookResults(localMatches, []);
  }
}
function closeCookModal() { $("cookModal").hidden = true; }
$("cookFromPantryBtn").addEventListener("click", openCookModal);
document.querySelectorAll("[data-cook-close]").forEach(button => button.addEventListener("click", closeCookModal));
restoreNutritionGoalsForm();
wireHouseholdUi();
if (!state.valda.size) chooseMenu(false); else render();
renderRecipePage();
refreshUser();
syncNearbyBranches();
// En inbjudningslänk är det FÖRSTA som ska hända: personen kom hit för att
// gå med i en familj, inte för att titta på appen.
handlePendingInvite();
// Telefonen tillbaka från bakgrunden: hämta det familjen ändrat under tiden.
// Det här är vad som gör att Adam ser Saras avbockning "snart" (§25) utan
// att vi bygger en WebSocket-infrastruktur för det.
function onAppResumed() {
  pullHousehold(); loadNotifications();
  // Tillbaka från Stripe i native-appen: hämta Premium-status.
  if (awaitingPremiumActivation && isNativeApp()) activatePremiumAfterCheckout();
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") onAppResumed();
});
// Native (Capacitor): appen vaknar och djuplänkar. @capacitor/app ger
// appStateChange när appen kommer tillbaka från bakgrunden (webviewen
// skickar inte alltid visibilitychange då) och appUrlOpen när en
// universell länk (matjakt.store/app/?verify=|?reset=|?invite=|?recept=)
// öppnar appen: query-strängen får aldrig tappas - appen laddas om med
// den så samma startkod som på webben tar hand om länken.
// Externa länkar (villkor, policy, butikssidor, källor) öppnas i appens
// egen webbläsarvy i stället för att kasta ut användaren till Safari.
if (isNativeApp()) {
  document.addEventListener("click", event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey) return;
    const anchor = event.target?.closest?.("a[href]");
    if (!anchor) return;
    let target;
    try { target = new URL(anchor.href, location.href); } catch { return; }
    if (!/^https?:$/.test(target.protocol) || target.origin === location.origin) return;
    event.preventDefault();
    openExternal(target.href);
  }, true);
}
loadNativePlugins().then(plugins => {
  const nativeApp = plugins?.App;
  if (!nativeApp?.addListener) return;
  nativeApp.addListener("appStateChange", ({ isActive }) => { if (isActive) onAppResumed(); });
  nativeApp.addListener("appUrlOpen", ({ url }) => {
    let search = "";
    try { search = new URL(url).search; } catch { return; }
    if (!search) return;
    location.href = `${location.pathname}${search}`;
  });
});
// A first-time visitor arriving through a SHARED RECIPE LINK came for the
// recipe - onboarding on top of it would bury the very thing that brought
// them here. It opens on their next natural visit instead.
if (!state.onboardingComplete && !new URLSearchParams(location.search).get("recept")) openOnboarding();
const billingResult = new URLSearchParams(location.search).get("billing");
if (billingResult) {
  history.replaceState(null, "", location.pathname);
  if (billingResult === "success") { activatePremiumAfterCheckout(); chooseMenu(false); }
}
if (pendingResetToken) { openAccountModal(); showAccountForm("reset"); }
const pendingVerifyToken = urlTokens.verify;      // också redan ur adressfältet
if (pendingVerifyToken) {
  verifyEmail(pendingVerifyToken).then(({ user }) => {
    if (state.user) state.user = user;
    renderAccount();
    openAccountModal();
  }).catch(() => {
    openAccountModal();
    (state.user ? $("verifyError") : $("loginError")).textContent = "Verifieringslänken är ogiltig eller redan använd. Begär en ny under Ditt konto.";
  });
}
// Fill the recipe bank, then draw. Everything that reads RECEPT runs after
// this resolves; an empty bank (network gone, file missing) leaves the app
// working with whatever the account already had rather than throwing.
fetchEntitlements();
loadRecipes().then(recipes => {
  RECEPT.push(...recipes);
  if (new URLSearchParams(location.search).get("recept")) renderRecipePage();
  if (!RECEPT.length) return;
  if (!state.valda.size && state.onboardingComplete) chooseMenu(false);
  else render();
  renderRecipes();
});

$("manualItemAdd")?.addEventListener("click", () => {
  const input = $("manualItemInput");
  const name = (input.value || "").trim();
  if (!name) return;
  addExtraItem({ name, source: "manual" });
  input.value = "";
});
$("manualItemInput")?.addEventListener("keydown", event => {
  if (event.key === "Enter") { event.preventDefault(); $("manualItemAdd").click(); }
});

window.addEventListener("popstate", renderRecipePage);
// Offline är inget fel: listan och veckan bor i localStorage och fungerar.
// Men det ska SÄGAS - annars ser misslyckade prisuppdateringar ut som
// buggar. En stilla rad, inte en skrikande banner.
function renderOfflineNote() {
  document.body.classList.toggle("is-offline", !navigator.onLine);
}
window.addEventListener("online", () => { renderOfflineNote(); render(); });
window.addEventListener("offline", renderOfflineNote);
renderOfflineNote();
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => { /* offline-stödet är ett tillägg - appen funkar utan det */ }));
  // När en ny service worker tagit över kör fliken fortfarande gammal
  // app.js mot ett nytt API. En diskret rad i stället för tyst skevhet.
  let hadController = Boolean(navigator.serviceWorker.controller);
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!hadController) { hadController = true; return; }   // första installationen
    const note = document.createElement("button");
    note.type = "button";
    note.className = "update-note";
    note.textContent = "Ny version av Matjakt finns - tryck för att ladda om";
    note.addEventListener("click", () => location.reload());
    document.body.appendChild(note);
  });
}
