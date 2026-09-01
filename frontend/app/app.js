// ---------------------------------------------------------------------------
// UTVECKLINGSLÅSET. Servern kräver X-Gate-Token på varje data-anrop medan
// Matjakt är stängt för allmänheten. En wrapper på fetch skickar token på
// alla API-anrop så ingen enskild anropsplats kan glömmas; ett 401 med
// gate-flaggan (utgången/ogiltig token) låser skärmen igen.
(function () {
  const gateToken = () => { try { return localStorage.getItem("matjakt-gate") || ""; } catch (e) { return ""; } };
  const local = ["localhost", "127.0.0.1"].includes(location.hostname);
  const lock = () => {
    try { localStorage.removeItem("matjakt-gate"); } catch (e) {}
    if (!local) location.replace("../");
  };
  const original = window.fetch.bind(window);
  window.fetch = (resource, options = {}) => {
    const url = typeof resource === "string" ? resource : resource?.url || "";
    if (url.includes("/api/")) {
      options = { ...options, headers: { ...(options.headers || {}), "X-Gate-Token": gateToken() } };
      return original(resource, options).then(response => {
        if (response.status === 401) {
          response.clone().json().then(body => { if (body && body.gate) lock(); }).catch(() => {});
        }
        return response;
      });
    }
    return original(resource, options);
  };
  window.__matjaktGateLock = lock;
})();

import { readStoredState, writeStoredState } from "./src/state/storage.js";
import { aggregateIngredients, budgetRemaining, calculateLiveShoppingTotal, calculateShoppingTotal, clampBudget, portionFactor } from "./src/services/calculations.js";
import { createDebouncedSearch, filterRecipes, mergeRecipeResults } from "./src/services/recipe-search.js";
import { filterByNutritionGoals, hasActiveNutritionGoals } from "./src/services/nutrition.js";
import { expiryStatus, matchLocalRecipesToPantry, normalizePantry, pantryAmounts } from "./src/services/pantry.js";
import { extraLineTotal, extraUnitPrice, extrasTotal, newExtraItem, removeExtra, setQty } from "./src/services/extras.js";
import { ALLERGENS, filterByDiet } from "./src/services/diet.js";
import { inBudgetPool, limitCandidatePool, pickBalanced, pickCheapest, pickProtein } from "./src/services/planning.js";
import { API_BASE_URL, entitlementsApiUrl, geocodeApiUrl, groceryStatusApiUrl, pricingListApiUrl, pricingWeekApiUrl, productApiUrl as configuredProductApiUrl, productsBatchApiUrl, recipeDetailApiUrl, recipeSearchApiUrl, recipesByPantryApiUrl, storesApiUrl } from "./src/api/config.js";
import { changePassword, deleteAccount, fetchAccountState, fetchCurrentUser, getStoredToken, login, logout as logoutRequest, openBillingPortal, redeemPremium, register, requestPasswordReset, resendVerification, resetPassword, saveAccountState, startCheckout, storeToken, verifyEmail } from "./src/api/auth.js";
import { escapeHtml, safeHttpUrl } from "./src/utils/html.js";
import { TAG_LABELS, hasTag, loadRecipe, loadRecipes, loadShelves, matchesAllTags } from "./src/data/recipes.js";

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
const recipePhoto = recipe => recipe.bild ? `<img class="recipe-photo" src="${cardImageUrl(recipe.bild)}" alt="${recipe.namn}" loading="lazy" decoding="async">` : `<span class="recipe-photo recipe-fallback" role="img" aria-label="Ingen matbild tillgänglig"><svg viewBox="0 0 64 64"><path d="M14 48h36M18 44a14 14 0 0 1 28 0M32 20v10M27 20h10"/></svg><small>Matjakt</small></span>`;
// A photo URL that 404s or is blocked must degrade into the same calm icon
// as "no photo at all". Without this the card showed the browser's
// broken-image glyph with the alt text spilled across it - which reads as a
// bug, in the one place a food app is supposed to look appetising.
window.addEventListener("error", event => {
  const img = event.target;
  if (img?.tagName === "IMG" && img.classList?.contains("recipe-photo") && !img.dataset.fell) {
    img.dataset.fell = "1";
    const holder = document.createElement("span");
    holder.innerHTML = recipePhoto({});
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
  return `<div class="recipe-feedback"><button type="button" class="feedback-btn ${fb.liked ? "active" : ""}" data-like-recipe="${recipeId}">👍 Gillar</button><button type="button" class="feedback-btn dislike ${fb.disliked ? "active" : ""}" data-dislike-recipe="${recipeId}">👎 Gillar inte</button></div>`;
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
function setWeekPlan(ids) { state.weekPlan = [...ids]; state.valda = new Set(ids); }
function addToWeekPlan(id) { if (!state.weekPlan.includes(id)) state.weekPlan.push(id); state.valda.add(id); }
function removeFromWeekPlan(id) { state.weekPlan = state.weekPlan.filter(existing => existing !== id); state.valda.delete(id); }
// Replaces exactly the recipe at this day's position - every other day's
// recipe keeps its own position untouched, which is the whole point of
// swapping "this day" rather than clearing and re-picking the week.
function swapWeekPlanDay(dayIndex, newId) { state.weekPlan = state.weekPlan.map((id, index) => index === dayIndex ? newId : id); state.valda = new Set(state.weekPlan); }
const savedState = readStoredState(localStorage);
const state = { budget: savedState.budget || 800, personer: Math.min(12, Math.max(1, Number(savedState.personer) || 2)), middagar: savedState.middagar || 4, butik: savedState.butik || "auto", postnummer: savedState.postnummer || "", position: null, sokning: "", kategori: "alla", maxTid: savedState.maxTid || 0, baraFavoriter: false, apiRecipes: savedState.apiRecipes || [], pantry: normalizePantry(savedState.pantry || {}), pantryTab: "skafferi", liveProdukter: [], favoriter: new Set(savedState.favoriter || []), valda: new Set(savedState.valda || []), avklarade: new Set(savedState.avklarade || []), removedItems: new Set(savedState.removedItems || []), expanded: null, authToken: getStoredToken(), user: null, naringsmal: savedState.naringsmal || null, livePriser: {}, liveBranchTotals: {}, liveUpdatedAt: null, receptTaggar: new Set(), minProtein: 0, maxKcal: 0, hyllor: [], dbChainTotals: {}, dbComparison: null, dbPricedAt: null, dbPricingFailedAt: null, dbLockedChains: [], extraItems: savedState.extraItems || [], extraMatches: {}, branches: [], betyg: savedState.betyg || {}, kost: { kosttyp: savedState.kost?.kosttyp || "", avoidAllergens: new Set(savedState.kost?.avoidAllergens || []) }, onboardingComplete: savedState.onboardingComplete || false, hushall: savedState.hushall || { vuxna: savedState.personer || 2, barn: 0 }, ogillar: new Set(savedState.ogillar || []), feedback: savedState.feedback || {}, savingsLog: savedState.savingsLog || [], swapsThisWeek: savedState.swapsThisWeek || 0, pinnedBranch: savedState.pinnedBranch || null,
  // The week's recipe ids in day order (index 0 = Måndag) - the actual
  // source of truth for "which day has which recipe", now that a day swap
  // has to replace exactly one day's recipe in place. state.valda (a Set)
  // stays around alongside it purely as an O(1) "is this recipe anywhere in
  // my week" membership check for recipe-card UI - every place that needs
  // day order or a specific day's recipe reads weekPlan / selectedRecipes(),
  // never valda's own iteration order (a Set has none tied to day position).
  weekPlan: Array.isArray(savedState.weekPlan) ? savedState.weekPlan : [...(savedState.valda || [])] };
function buildSyncPayload() {
  return { budget: state.budget, personer: state.personer, middagar: state.middagar, butik: state.butik, postnummer: state.postnummer, maxTid: state.maxTid, pantry: state.pantry, favoriter: [...state.favoriter], valda: [...state.valda], avklarade: [...state.avklarade], removedItems: [...state.removedItems], apiRecipes: state.apiRecipes.filter(recipe => state.valda.has(recipe.id)), naringsmal: state.naringsmal, betyg: state.betyg, kost: { kosttyp: state.kost.kosttyp, avoidAllergens: [...state.kost.avoidAllergens] }, onboardingComplete: state.onboardingComplete, hushall: state.hushall, ogillar: [...state.ogillar], feedback: state.feedback, savingsLog: state.savingsLog, swapsThisWeek: state.swapsThisWeek, pinnedBranch: state.pinnedBranch, weekPlan: state.weekPlan, extraItems: state.extraItems,
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
function scheduleServerSync() {
  if (!state.authToken) return;
  clearTimeout(serverSyncTimer);
  // Debounced: saveState() fires on nearly every interaction (pantry +/-, ratings,
  // swaps...) - pushing to the server on every single one would be wasteful and
  // could race with itself. One request ~1.5s after the last change is enough for
  // "follows you to another phone", which is the actual requirement here.
  serverSyncTimer = setTimeout(() => {
    saveAccountState(state.authToken, buildSyncPayload()).catch(() => { /* nästa saveState-anrop försöker igen */ });
  }, 1500);
}
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
  lax: { "Laxfilé": [600, "g"], Potatis: [800, "g"], Citron: [1, "st"], Dill: [1, "st"] },
  halloumibowl: { Halloumi: [225, "g"], Matvete: [250, "g"], Paprika: [1, "st"], Yoghurt: [200, "g"] },
  chili: { "Kidneybönor": [400, "g"], "Krossade tomater": [400, "g"], Majs: [150, "g"], Paprika: [2, "st"] },
  kycklingwok: { "Kycklingfilé": [500, "g"], "Äggnudlar": [250, "g"], Wokgrönsaker: [400, "g"], Soja: [30, "ml"] },
  tomatsoppa: { "Krossade tomater": [400, "g"], Grädde: [200, "ml"], Lök: [2, "st"], Basilika: [1, "st"] },
  pannkakor: { "Vetemjöl": [250, "g"], Mjölk: [600, "ml"], Ägg: [4, "st"], Bär: [300, "g"] },
  kottbullar: { "Köttfärs": [500, "g"], Potatis: [800, "g"], Grädde: [200, "ml"], Lingonsylt: [100, "g"] },
  vegetarisklasagne: { Lasagneplattor: [300, "g"], "Krossade tomater": [400, "g"], "Riven ost": [150, "g"], Zucchini: [2, "st"] },
  scampi: { "Räkor": [300, "g"], Pasta: [250, "g"], Vitlök: [1, "st"], Citron: [1, "st"] },
  kikartscurry: { Kikärtor: [380, "g"], Kokosmjölk: [400, "ml"], Ris: [250, "g"], "Curry & grönsaker": [28, "g"] },
  flaskfilerotmos: { "Fläskfilé": [600, "g"], Morötter: [400, "g"], Potatis: [600, "g"], Timjan: [1, "st"] },
  biffmedlok: { Biff: [600, "g"], Potatis: [800, "g"], Lök: [2, "st"], Grädde: [200, "ml"] },
  vegobolognese: { "Vegofärs": [400, "g"], Pasta: [250, "g"], "Krossade tomater": [400, "g"], Lök: [1, "st"] },
  kycklingcouscous: { Kycklingfilé: [500, "g"], Matvete: [250, "g"], Paprika: [2, "st"], Citron: [1, "st"] },
  rotfruktsgratang: { Falukorv: [400, "g"], Potatis: [800, "g"], Morötter: [400, "g"], "Riven ost": [100, "g"] },
  butterchicken: { Kycklingfilé: [500, "g"], "Krossade tomater": [400, "g"], Grädde: [200, "ml"], "Curry & grönsaker": [28, "g"] },
  fiskgratang: { "Fryst torsk": [500, "g"], Räkor: [200, "g"], Dill: [1, "st"], Grädde: [200, "g"] },
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
  const ingredients = (recipe.ingredients || []).map(item => escapeHtml(`${item.measure || ""} ${item.name || ""}`.trim())).filter(Boolean);
  return { id: recipe.id, provider: recipe.provider, providerRecipeId: recipe.providerRecipeId, namn: escapeHtml(recipe.title), butik: "alla", tid: Number(recipe.prepMinutes) || 0, typ: "Provider-recept", portionspris: null, inkopspris: null, sparar: 0, ingredienser: ingredients, hemma: [], beskrivning: "Recept från extern receptkälla. Pris beräknas först när ingredienserna har matchats mot svenska butikprodukter.", steg: (recipe.instructions || []).map(escapeHtml), bild: safeHttpUrl(recipe.imageUrl), imageSource: recipe.imageSource, sourceUrl: safeHttpUrl(recipe.sourceUrl), servings: recipe.servings, priceStatus: "unavailable" };
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
  lax: { beskrivning: "Ugnsbakad lax med citron, dill och rostad potatis.", steg: ["Sätt ugnen på 200°C.", "Lägg lax och potatis i en form.", "Toppa med citron och dill och baka tills laxen är klar."], tips: "Laxen är klar när den precis börjar dela sig i lameller." },
  halloumibowl: { beskrivning: "Krispig halloumi med rostade grönsaker och krämig yoghurt.", steg: ["Koka matvetet enligt förpackningen.", "Rosta grönsakerna i ugnen.", "Stek halloumin och servera med yoghurt."], tips: "Stek halloumin sist så håller den sig varm och krispig." },
  chili: { beskrivning: "Mustig chili sin carne med bönor, tomat och paprika.", steg: ["Fräs paprika och lök.", "Tillsätt tomater, bönor och majs.", "Låt sjuda i 20 minuter och servera med ris."], tips: "Låt chilin vila tio minuter före servering för djupare smak." },
  kycklingwok: { beskrivning: "Snabb wok med kyckling, nudlar och krispiga grönsaker.", steg: ["Koka nudlarna.", "Stek kycklingen tills den är genomstekt.", "Woka grönsakerna och blanda allt med soja."], tips: "Ha alla ingredienser framme innan du börjar woka." },
  tomatsoppa: { beskrivning: "Len tomatsoppa med basilika och en skvätt grädde.", steg: ["Fräs löken mjuk.", "Koka med tomater och buljong.", "Mixa soppan och rör ner grädden."], tips: "En liten nypa socker balanserar syrliga tomater." },
  pannkakor: { beskrivning: "Klassiska tunna pannkakor med sötsyrliga bär.", steg: ["Vispa ihop smetens ingredienser.", "Stek tunna pannkakor i smör.", "Servera med bär."], tips: "Låt smeten vila en stund så blir pannkakorna jämnare." }
};
const $ = id => document.getElementById(id);
const money = value => `${Math.round(value).toLocaleString("sv-SE")} kr`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const scaledPurchasePrice = (recipe, branch = selectedBranch()) => recipe.inkopspris * portionFactor(state.personer) * (branch?.prisfaktor || 1);
function shoppingListCost(selected, branch) {
  const factor = branch?.prisfaktor || 1;
  return calculateShoppingTotal(aggregateShopping(selected), PRODUCT_CATALOG, pantryAmounts(state.pantry), factor);
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

const comboAffinity = combo => combo.reduce((sum, recipe) => sum + recipeAffinity(recipe), 0)
  - comboVarietyPenalty(combo);
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
const FREE_ENTITLEMENTS = { plan: "free", isPremium: false, maxDinners: 4, features: {}, pricing: null };
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
  return entitlements.pricing || {
    monthly: { priceText: "59 kr/mån" },
    yearly: { priceText: "399 kr/år", perMonthText: "≈ 33 kr/mån",
              savingsText: "Spara 309 kr jämfört med månadsbetalning", badge: "Bäst värde" },
  };
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
    state.branches = (data.butiker || []).map(store => ({ kedja: store.kedja, namn: store.namn, lat: store.lat, lon: store.lon, avstandKm: store.avstandKm, prisfaktor: 1, primatKey: store.primatKey || "" }));
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
function recipeMatchesDislikes(recipe) {
  if (!state.ogillar.size) return false;
  const text = recipe.ingredienser.join(" ").toLowerCase();
  return [...state.ogillar].some(term => text.includes(term.toLowerCase()));
}
function localRecipesForUser() {
  return filterByDiet(RECEPT, state.kost).filter(recipe => !recipeMatchesDislikes(recipe));
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
function updateNutritionWarning(nutritionShortfall) {
  $("nutritionWarning").hidden = !nutritionShortfall;
  if (nutritionShortfall) $("nutritionWarning").textContent = "Dina näringsmål matchade för få recept den här veckan, så vi visar de närmaste alternativen istället. Testa att justera målen om du vill ha en bättre träff.";
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
  updateNutritionWarning(nutritionShortfall);
  const combo = bestMenuCombo(candidates, state.middagar, state.budget, branch);
  setWeekPlan(combo.map(r => r.id));
  // A new set of meals makes any checked-off shopping items and cached live
  // prices from the previous week meaningless - without this, starting a new
  // week could show ingredients as "already bought" just because an item with
  // the same name was checked off last week.
  state.avklarade.clear();
  state.removedItems.clear();
  state.swapsThisWeek = 0;
  clearPriceSnapshots();
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
  const dietFilterActive = state.kost.kosttyp !== "" || state.kost.avoidAllergens.size > 0;
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
      <button class="recipe-details" data-details="${recipe.id}" aria-expanded="${expanded}">
        <span class="recipe-photo-wrap">${recipePhoto(recipe)}<span class="saving">${recipe.sparar ? `Spara ca ${money(recipe.sparar)}` : "Från receptdatabas"}</span></span>
        <span class="recipe-name">${recipe.namn}</span><span class="recipe-meta">${recipe.tid} min · ${recipe.typ}</span><span class="recipe-store">Billigast på ${recipe.butik}</span>
        <span class="price-tag">${recipe.inkopspris ? `${money(scaledPurchasePrice(recipe))} i butik` : "Pris hämtas från butik"}</span><span class="portion-price">${recipe.portionspris ? `ca ${money(recipe.portionspris)} per portion` : "Ingredienser och instruktioner finns"}</span>
        ${recipe.kcal ? `<span class="recipe-macros">${macroLine(recipe)}</span>` : ""}
      </button>
      ${expanded ? `<div class="ingredients"><p class="recipe-description">${details.beskrivning || "En god vardagsrätt med enkla råvaror."}</p><strong>Du behöver köpa</strong><p>${recipe.ingredienser.join(", ")}</p><small>Hemma: ${recipe.hemma.join(", ")}</small>${details.steg ? `<ol class="recipe-steps">${details.steg.map(step => `<li>${step}</li>`).join("")}</ol>` : ""}${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${details.tips}</p>` : ""}</div>` : ""}
      <button class="favorite-btn ${state.favoriter.has(recipe.id) ? "is-favorite" : ""}" data-favorite="${recipe.id}" aria-label="${state.favoriter.has(recipe.id) ? "Ta bort favorit" : "Spara som favorit"}">${state.favoriter.has(recipe.id) ? "★" : "☆"}</button><button class="add-btn" data-add="${recipe.id}">${selected ? "✓ Tillagd" : "+ Lägg till"}</button>
    </article>`;
  }).join("") : `<p class="empty-state">Inga recept matchar din sökning eller butik ännu.</p>`;
  document.querySelectorAll("[data-details]").forEach(btn => btn.addEventListener("click", () => openRecipeTab(btn.dataset.details)));
  document.querySelectorAll("[data-add]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.add; state.valda.has(id) ? removeFromWeekPlan(id) : addToWeekPlan(id); saveState(); render(); }));
  document.querySelectorAll("[data-favorite]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.favorite; state.favoriter.has(id) ? state.favoriter.delete(id) : state.favoriter.add(id); saveState(); renderRecipes(); }));
}

function openRecipeTab(id) { history.pushState({ recept: id }, "", `${location.pathname}?recept=${encodeURIComponent(id)}`); renderRecipePage(); }
const FAVORITE_ICON = '<svg viewBox="0 0 24 24"><path d="M12 21s-7-4.6-9.5-9C.7 8.2 2.4 5 5.7 5c2 0 3.4 1.1 4.3 2.4C11 6.1 12.4 5 14.4 5c3.3 0 5 3.2 3.2 7-2.5 4.4-9.5 9-9.5 9Z"/></svg>';
const PRICE_TAG_ICON = '<svg viewBox="0 0 24 24"><path d="M20 12 12.5 4.5a2 2 0 0 0-1.4-.5H5a1 1 0 0 0-1 1v6.1a2 2 0 0 0 .6 1.4L12 20"/><circle cx="8" cy="8" r="1.3"/></svg>';
function recipeNutritionMarkup(recipe) {
  if (!recipe.kcal) return "";
  const items = [[recipe.kcal, "kcal"], [recipe.protein, "protein"], [recipe.kolhydrater, "kolhydrater"], [recipe.fett, "fett"]];
  return `<div class="recipe-nutrition"><p class="recipe-nutrition-label">Näring per portion</p><div class="recipe-nutrition-row">${items.map(([value, label]) => `<div class="recipe-nutrition-item"><strong>${value}${label === "kcal" ? "" : " g"}</strong><span>${label}</span></div>`).join("")}</div></div>`;
}
function recipeIngredientListMarkup(recipe) {
  const factor = portionFactor(state.personer);
  const quantities = RECIPE_QUANTITIES[recipe.id] || {};
  return recipe.ingredienser.map(name => {
    const quantity = quantities[name];
    const amountText = quantity ? `${Math.round(quantity[0] * factor)} ${quantity[1]}` : "";
    // Diskret, not hidden - a pantry match is useful context ("you already
    // have this"), not a reason to remove the line from the list.
    const inPantry = (state.pantry[name]?.amount || 0) > 0;
    return `<li class="recipe-ingredient ${inPantry ? "in-pantry" : ""}"><svg class="recipe-ingredient-check" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m8 12.5 2.5 2.5 5-5.5"/></svg><span class="recipe-ingredient-name">${escapeHtml(name)}${inPantry ? '<small>Finns i skafferiet</small>' : ""}</span><span class="recipe-ingredient-amount">${escapeHtml(amountText)}</span></li>`;
  }).join("");
}
async function renderRecipePage() {
  const id = new URLSearchParams(location.search).get("recept");
  if (!id) { $("top").hidden = false; $("recipePage").hidden = true; window.scrollTo(0, 0); return; }
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
      if (!detail) { recipeDetailFetches.delete(found.id); return; }
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
  $("recipePage").innerHTML = `<button class="recipe-back" type="button" aria-label="Tillbaka till recepten"></button><article class="full-recipe">${recipe.bild ? `<img class="recipe-photo full-recipe-hero" src="${recipe.bild}" alt="${recipe.namn}">` : `<div class="full-recipe-fallback">${recipePhoto(recipe)}</div>`}<p class="eyebrow">${recipe.typ}</p><h1>${recipe.namn}</h1><div class="recipe-detail-meta"><span>${recipe.tid ? recipe.tid + " min" : "Tid saknas"}</span><span>${recipe.servings || state.personer} portioner</span><span>${recipe.priceStatus === "unavailable" ? "Pris saknas" : recipe.portionspris ? money(recipe.portionspris) + "/portion" : "Pris saknas"}</span></div>${recipe.kcal ? `<p class="full-recipe-macros">${macroLine(recipe)}</p>` : ""}<p class="full-recipe-description">${details.beskrivning || "En god svensk vardagsrätt."}</p><button class="btn btn-primary recipe-add-primary" type="button" data-recipe-add="${recipe.id}"><span>${state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"}</span><span>＋</span></button>${recipeRatingMarkup(recipe.id)}${feedbackMarkup(recipe.id)}<h2>Ingredienser</h2><ul>${recipe.ingredienser.map(item => `<li>${item}</li>`).join("")}</ul><h2>Gör så här</h2><ol>${(details.steg || []).map(step => `<li>${step}</li>`).join("")}</ol>${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${details.tips}</p>` : ""}</article>`;
  $("recipePage").querySelector(".recipe-back").addEventListener("click", () => history.back());
  $("recipePage").querySelector("[data-recipe-add]").addEventListener("click", event => { state.valda.has(recipe.id) ? removeFromWeekPlan(recipe.id) : addToWeekPlan(recipe.id); saveState(); render(); event.currentTarget.querySelector("span").textContent = state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"; });
  wireRatingStars($("recipePage"), recipe.id);
  wireFeedbackButtons($("recipePage"), recipe.id);
  requestAnimationFrame(() => window.scrollTo(0, 0));
  let touchStartX = 0; $("recipePage").ontouchstart = event => { touchStartX = event.changedTouches[0].screenX; }; $("recipePage").ontouchend = event => { const distance = event.changedTouches[0].screenX - touchStartX; if (Math.abs(distance) < 70) return; const ids = allRecipes.map(item => item.id), currentIndex = ids.indexOf(id), targetIndex = distance < 0 ? currentIndex + 1 : currentIndex - 1; if (targetIndex >= 0 && targetIndex < ids.length) openRecipeTab(ids[targetIndex]); else if (distance > 0) history.back(); };
}

function branchLiveTotal(shoppingItems, chainProducts) {
  return calculateLiveShoppingTotal(shoppingItems, chainProducts, pantryAmounts(state.pantry));
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
function weekPricingBody(shoppingItems) {
  const selected = selectedRecipes();
  const bankRecipes = selected.filter(recipe => recipe.priceStatus !== "unavailable"
    && (!Array.isArray(recipe.ingredients) || recipe.ingredients.length || recipe.slug));
  const recipeIds = bankRecipes.map(recipe => recipe.id);
  const body = { people: state.personer, pantry: pantryAmounts(state.pantry || {}) };
  // Borttagna varor måste följa med: recipeIds-vägen aggregerar om veckan på
  // servern, och utan denna lista skulle butiksjämförelsen fortsätta prissätta
  // varor användaren tagit bort.
  if (state.removedItems.size) body.excludeItems = [...state.removedItems].sort();
  if (recipeIds.length) body.recipeIds = recipeIds;
  else body.items = shoppingItems.map(item => ({ name: item.namn, amount: item.total, unit: item.unit }));
  return body;
}
async function syncDatabasePricing(shoppingItems) {
  const body = weekPricingBody(shoppingItems);
  if (!body.recipeIds?.length && !body.items?.length) return;
  const key = JSON.stringify(body);
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
    setTimeout(() => renderBasket(), 8000);
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

function extrasTotalForChain(chain) {
  return extrasTotal(state.extraItems, chain, state.extraMatches[chain] || {});
}

function addExtraItem(fields) {
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
  if (extra.source === "campaign") metaBits.push(`🏷️ Kampanj hos ${extra.chain}`);
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
      <strong>${escapeHtml(chain)}</strong><span>🔒 Se pris med Premium</span></button>`;
  }
  if (unavailable) {
    return `<div class="store-card unavailable"><strong>${escapeHtml(chain)}</strong><span>Pris ej tillgängligt – för få varor prissatta</span></div>`;
  }
  return `<button type="button" class="store-card ${active ? "active" : ""}" data-store-card="${escapeHtml(chain)}">
    <strong>${escapeHtml(chain)}</strong><span>${money(total)}</span>${cheapest ? '<em class="store-card-badge">Billigast</em>' : ""}</button>`;
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
  container.innerHTML = entries.map(storeCardMarkup).join("");
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
    container.innerHTML = `<div class="store-compare"><div class="store-compare-head"><span>${currentHeading} ${current.branch.namn}</span>${currentPriceText}${coverageLabel(current)}${updatedLabel}</div>${results.length > 1 ? `<button type="button" class="store-compare-upsell" id="storeCompareUpsell-${containerId}">🔒 Se vilken butik som faktiskt är billigast av ${results.length} – med Premium</button>` : ""}</div>`;
    $(`storeCompareUpsell-${containerId}`)?.addEventListener("click", openPremiumPitch);
    syncDatabasePricing(shoppingItems);
    syncBranchComparison(shoppingItems, branches);
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
    const inner = `<span>${r.branch.namn}${isCheapest ? '<span class="live-badge cheapest-badge">Billigast</span>' : ""}${isPinned ? '<span class="live-badge pinned">Vald</span>' : ""}${priceSourceBadge(r)}${rowCoverage}</span><strong${hasUsablePrice(r) ? "" : ' class="price-missing"'}>${hasUsablePrice(r) ? money(r.cost) : "Pris saknas"}</strong>`;
    return r.branch.primatKey
      ? `<button type="button" class="store-compare-row ${tag}" data-pick-branch="${index}">${inner}</button>`
      : `<div class="store-compare-row ${tag} not-pickable">${inner}</div>`;
  }).join("")}</div>`;
  // Same rule as the free tier: the head never prints the flat estimate as
  // a price. "Uppskattat pris Coop Nian - ca 578 kr" is the exact banner the
  // no-fabricated-totals rule exists to kill.
  const headIsEstimate = cheapest.source === "estimate";
  const headFetching = headIsEstimate && (databasePricingSync.pending || (!state.dbPricedAt && !state.dbPricingFailedAt));
  container.innerHTML = `<div class="store-compare"><div class="store-compare-head"><span>${comparisonIsReal && winner && winner.branch.kedja === cheapest.branch.kedja ? "Lägst pris" : "Pris hos"}</span><strong>${cheapest.branch.namn}${headIsEstimate ? ` · ${headFetching ? "pris hämtas…" : "pris saknas just nu"}` : ` · ca ${money(cheapest.cost)}`}</strong>${savingsAreReal ? (winner && winner.branch.kedja !== cheapest.branch.kedja
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
    state.pinnedBranch = alreadyPinned ? null : { kedja: branch.kedja, namn: branch.namn, primatKey: branch.primatKey };
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
  return `<${tag} class="comparison-store-card ${isCheapest && coverageOk ? "cheapest" : ""}${openable ? " openable" : ""}"${attrs}><div class="comparison-store-main"><span class="comparison-store-name" style="color:${color}">${escapeHtml(result.branch.kedja)}</span><small class="comparison-store-coverage">${coverageNote}</small></div><div class="comparison-store-price">${isCheapest && coverageOk ? '<span class="comparison-billigast">Billigast</span>' : ""}${coverageOk ? `<strong>${money(result.cost)}</strong>${savings != null && savings > 1 ? `<small class="comparison-savings">Du sparar ${money(savings)}</small>` : ""}` : `<small class="comparison-savings">${!hasUsablePrice(result) ? "Inga priser hittades" : "För få aktuella priser för en jämförelse"}</small>`}</div>${openable ? '<span class="comparison-store-arrow" aria-hidden="true">›</span>' : ""}</${tag}>`;
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
      input.checked ? state.avklarade.add(input.dataset.shopping) : state.avklarade.delete(input.dataset.shopping);
      saveState();
      // Handla-vyn delar samma avbockningar - utan omritning såg dess lista,
      // progress och "Allt handlat" inget förrän någon orelaterad render.
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
  // looks suspiciously low.
  const warning = !data.comparable
    ? `<p class="chain-list-warning">För få av varorna har aktuellt pris för att den här summan ska gå att jämföra med en annan butik.</p>` : "";
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
  const head = sticky + `<div class="chain-list-head"><h2>${escapeHtml(storeName)}</h2><small>${escapeHtml([data.chain, distance].filter(Boolean).join(" · "))}</small>${pricedElsewhere}<div class="chain-list-total"><span>Total kassakostnad</span><strong>${money(total)}</strong></div><div class="chain-list-meta"><span>${data.realPriceItems} av ${data.totalItems} varor har pris</span>${data.estimatedItems ? `<span>${data.estimatedItems} med uppskattat antal</span>` : ""}${data.missingItems ? `<span>${data.missingItems} utan pris</span>` : ""}<span>${escapeHtml(updated)}</span>${savings}</div>${warning}</div>`;

  const rows = (data.items || []).map(item => {
    const checked = state.avklarade.has(item.ingredient);
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
  const activeResult = results.find(r => r.branch.kedja === chosenStore()) || cheapest;
  // priciest is null whenever no shop qualified for a comparison - and a
  // saving measured against nothing is not a saving. Say nothing instead of
  // crashing the whole render, which is what reading .cost off null did.
  const activeSavings = priciest && activeResult ? priciest.cost - activeResult.cost : 0;
  $("comparisonCampaignCard").hidden = !(activeSavings > 1);
  if (activeSavings > 1) {
    $("comparisonCampaignText").textContent = `Du sparar ${money(activeSavings)} med ${activeResult.branch.kedja}`;
  }
  const pricedStamp = state.dbPricedAt || state.liveUpdatedAt;
  $("comparisonUpdated").textContent = pricedStamp
    ? `Priserna uppdaterades ${new Date(pricedStamp).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" })}`
    : "Priser hämtas…";
}

const CATEGORY_MAP = { "Frukt & grönt": ["Purjolök", "Morötter", "Lök", "Paprika", "Citron", "Dill", "Basilika", "Lök & vitlök", "Zucchini", "Vitlök", "Timjan", "Sparris", "Rödkål"], Mejeri: ["Grädde", "Riven ost", "Yoghurt", "Mjölk", "Crème fraiche", "Ägg", "Halloumi", "Feta"], "Kött & fisk": ["Kycklinglårfilé", "Kycklingfilé", "Falukorv", "Fryst torsk", "Laxfilé", "Köttfärs", "Fläskfilé", "Biff", "Kalvschnitzel"], Torrvaror: ["Pasta", "Ris", "Matvete", "Äggnudlar", "Vetemjöl", "Röda linser", "Kidneybönor", "Svarta bönor", "Majs", "Krossade tomater", "Tomatpuré", "Salsa", "Soja", "Lasagneplattor", "Kikärtor", "Lingonsylt", "Vegofärs", "Tofu", "Äppelmos", "Kapris"], Frys: ["Wokgrönsaker", "Bär", "Räkor"] };
function itemCategory(name) { return Object.entries(CATEGORY_MAP).find(([, names]) => names.includes(name))?.[0] || "Övrigt"; }
// Bundled locally (no network fetch) so every shopping item always shows something
// relevant even offline or before a real product photo has loaded - never a bare
// letter or a broken image. One simple, on-brand line icon per category; picking
// the wrong product's photo to fill the space would be worse than an icon, so this
// is deliberately generic rather than a guess.
const CATEGORY_ICONS = {
  "Frukt & grönt": '<path d="M12 9c-3 0-5.5 2.7-5.5 6.2C6.5 19 8.8 21 11 21c.7 0 1-.3 1-.3s.3.3 1 .3c2.2 0 4.5-2 4.5-5.8C17.5 11.7 15 9 12 9Z"/><path d="M12 9c0-2 1.2-3.3 2.8-3.6"/>',
  Mejeri: '<path d="M10 3h4v3l2 2v11a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2V8l2-2V3Z"/><path d="M9 13h6"/>',
  "Kött & fisk": '<path d="M4 12c4-5 10-6 15-3-1 1-1 5 0 6-5 3-11 2-15-3Z"/><path d="M17 9l3-2v10l-3-2"/>',
  Torrvaror: '<path d="M7 8h10v11a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V8Z"/><path d="M9 8V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3M8 12h8"/>',
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
function databaseShoppingItemMarkup(item, match) {
  const checked = state.avklarade.has(item.namn);
  const photo = match.imageUrl
    ? `<img class="shopping-item-image has-image" src="${escapeHtml(safeHttpUrl(match.imageUrl) || "")}" alt="" loading="lazy">`
    : categoryIconMarkup(itemCategory(item.namn));
  // A campaign price is only worth a badge when it is actually lower than
  // the ordinary price - showing "kampanj" on a product at its normal price
  // would invent a discount.
  const onCampaign = match.campaignPrice != null && match.regularPrice != null
    && match.campaignPrice < match.regularPrice;
  const campaign = onCampaign
    ? `<small class="shopping-item-campaign">🏷️ Kampanj ${money(match.campaignPrice)} (ord. ${money(match.regularPrice)})</small>`
    : "";
  const packageText = match.packageSize && match.packageSize !== "1 st" ? match.packageSize : "";
  // What the RECIPES need and what the SHOPPER buys, side by side. "2 st"
  // alone answered neither question - you want to know that the week needs
  // 750 g and that two 400 g packs cover it.
  const neededText = match.neededAmount
    ? `Behöver ${amountLabel(match.neededAmount, match.neededUnit)}` : "";
  const countText = match.packages > 1
    ? `Köp ${match.packages} × ${packageText || "1 st"}`
    : (packageText ? `Köp 1 × ${packageText}` : "");
  // Flagged, not hidden: when the recipe's unit can't be converted to the
  // pack's unit (a recipe in "st" against a pack in "g") the engine falls
  // back to one package. That is a guess about QUANTITY, and the shopper is
  // the one who can tell whether one is enough.
  const inexact = match.priceStatus === "estimated"
    ? '<small class="item-status estimated">Antal osäkert</small>' : "";
  const meta = escapeHtml([match.brand, neededText, countText].filter(Boolean).join(" · ") || "1 st");
  return `<label class="shopping-item ${checked ? "checked" : ""}"><input type="checkbox" data-shopping="${escapeHtml(item.namn)}" ${checked ? "checked" : ""}>${photo}<span class="shopping-item-info"><strong>${escapeHtml(match.productName)}</strong><small class="shopping-item-meta">${meta}</small>${campaign}</span><span class="shopping-item-price"><strong>${money(match.totalCost)}</strong>${inexact}</span><button type="button" class="shopping-remove" data-remove-item="${escapeHtml(item.namn)}" aria-label="Ta bort ${escapeHtml(item.namn)} från listan">×</button></label>`;
}

function shoppingItemMarkup(item) {
  // A real product from Matjakt's own price database beats everything below
  // it: it is a named product on a real shelf, at a real price, with the
  // real number of packages you have to buy. The rest of this function is
  // the fallback for lines the database could not price - which stay
  // visible and honestly labelled rather than being hidden.
  const fromDatabase = databaseItemFor(item.namn);
  if (fromDatabase) return databaseShoppingItemMarkup(item, fromDatabase);
  const product = PRODUCT_CATALOG[item.namn] || { namn: item.namn, marke: "", pris: 0 };
  const pantry = state.pantry[item.namn]?.amount || 0;
  const needed = Math.max(0, item.total - pantry);
  const packages = item.package ? Math.ceil(needed / item.package.amount) : Math.ceil(needed);
  const live = state.livePriser[item.namn];
  const chain = chosenStore();
  // The only two moments worth calling out to the user: a fetch for this
  // specific item is genuinely still in flight, or the price shown is a
  // static guess rather than a real captured one. A settled real price gets
  // no badge at all - see the "no Live/Uppdaterad" reasoning this replaced.
  // live can exist with pris_kr === null (a confidently matched product, or
  // no confident match at all - either way, the backend has already decided
  // and this is not "still fetching" or "just an estimate") - that must show
  // "Pris saknas", never 0 kr, and must never enter a total (see
  // shoppingListCost/branchLiveTotal).
  const priceMissing = live && live.pris_kr == null;
  // While the database sync is still working the row says so; once it has
  // answered (this line was in missingItems) the row says "Pris saknas".
  // The static catalogue price is never printed: "Bär 30 kr - Uppskattat"
  // is an invented number in a column of real ones, and the moment it later
  // jumps to a real price the whole list looks unreliable.
  const dbSyncPending = databasePricingSync.pending || (!state.dbPricedAt && !state.dbPricingFailedAt);
  const stillFetching = packages > 0 && !live && (dbSyncPending || (livePriceSync.loading && VALID_CHAINS.includes(chain)));
  const isEstimated = false;
  const priceLabel = priceMissing ? "Pris saknas" : live ? money(live.pris_kr * (packages || 1)) : stillFetching ? "" : "Pris saknas";
  const displayName = live ? escapeHtml(live.produktnamn) : escapeHtml(item.namn);
  // PRODUCT_CATALOG uses "ICA" as a generic placeholder brand for estimated
  // prices, not a claim that the item comes from ICA specifically - showing it
  // next to a Willys/Coop list read as a store mismatch, so it's only shown
  // when it names a real distinguishing brand.
  // "1 st" as a package size is a no-op worth hiding (every produce item not
  // sold by weight has one) - stating it next to a "1 st" quantity read as a
  // typo ("1 st · 1 st"). Real sizes (g/ml/kruka/knippe) and quantities above
  // one are the only pieces of this line actually worth a shopper's glance.
  const sizeText = product.storlek && product.storlek !== "1 st" ? product.storlek : "";
  const brandSize = live ? live.markeOchStorlek : [product.marke && product.marke !== "ICA" ? product.marke : "", sizeText].filter(Boolean).join(" ");
  const qty = packages > 1 ? `${packages} st` : "";
  const neededPlain = needed > 0 ? `Behöver ${amountLabel(needed, item.unit)}` : "";
  const meta = !packages ? "Finns hemma" : escapeHtml([brandSize, neededPlain, qty].filter(Boolean).join(" · ") || "1 st");
  const campaign = live?.kampanj?.text ? `<small class="shopping-item-campaign">🏷️ ${escapeHtml(live.kampanj.text)}</small>` : "";
  const status = stillFetching ? '<small class="item-status loading">pris hämtas…</small>' : "";
  const photo = live?.bild ? `<img class="shopping-item-image has-image" src="${live.bild}" alt="" loading="lazy">` : categoryIconMarkup(itemCategory(item.namn));
  // Checkboxen betyder "jag har handlat den". X betyder "ut ur listan" -
  // finns hemma, redan köpt, köps någon annanstans. Två olika beteenden.
  return `<label class="shopping-item ${state.avklarade.has(item.namn) ? "checked" : ""}"><input type="checkbox" data-shopping="${item.namn}" ${state.avklarade.has(item.namn) ? "checked" : ""}>${photo}<span class="shopping-item-info"><strong>${displayName}</strong><small class="shopping-item-meta">${meta}</small>${campaign}</span><span class="shopping-item-price"><strong class="${priceLabel === "Pris saknas" ? "price-missing" : ""}">${priceLabel}</strong>${status}</span><button type="button" class="shopping-remove" data-remove-item="${item.namn}" aria-label="Ta bort ${item.namn} från listan">×</button></label>`;
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
function renderPantry() {
  const allItems = Object.entries(state.pantry).filter(([, entry]) => entry.amount > 0);
  $("pantryCount").textContent = allItems.length;
  document.querySelectorAll("#pantryTabs button").forEach(button => button.classList.toggle("active", button.dataset.pantryTab === state.pantryTab));
  const items = allItems.filter(([, entry]) => entry.location === state.pantryTab);
  $("pantryList").innerHTML = items.length ? items.map(([name, entry]) => {
    const status = expiryStatus(entry.expiry);
    const unit = PACKAGE_INFO[name]?.unit || "st";
    return `<div class="pantry-item"><span><strong>${escapeHtml(name)}</strong><small>${entry.amount} ${unit}${entry.expiry ? ` · Bäst före ${entry.expiry}` : ""}</small>${status === "expired" ? '<small class="pantry-expiry-badge expired">Utgången</small>' : status === "soon" ? '<small class="pantry-expiry-badge soon">Går ut snart</small>' : ""}</span><div class="pantry-item-controls"><button type="button" class="pantry-step" data-pantry-decrement="${escapeHtml(name)}" aria-label="Mindre ${escapeHtml(name)}">−</button><button type="button" class="pantry-step" data-pantry-increment="${escapeHtml(name)}" aria-label="Mer ${escapeHtml(name)}">+</button><button type="button" data-remove-pantry="${escapeHtml(name)}" aria-label="Ta bort ${escapeHtml(name)}">×</button></div></div>`;
  }).join("") : `<div class="pantry-empty"><svg viewBox="0 0 64 64"><path d="M12 22h40v34H12zM20 22v-9h24v9M20 33h24M20 43h16"/></svg><h2>${PANTRY_TAB_LABELS[state.pantryTab]} är tomt</h2><p>Lägg in det du redan har hemma så hjälper Matjakt dig att handla mindre.</p></div>`;
  document.querySelectorAll("[data-remove-pantry]").forEach(button => button.addEventListener("click", () => { delete state.pantry[button.dataset.removePantry]; saveState(); render(); }));
  document.querySelectorAll("[data-pantry-increment]").forEach(button => button.addEventListener("click", () => { const name = button.dataset.pantryIncrement; state.pantry[name].amount += pantryStep(name); saveState(); render(); }));
  document.querySelectorAll("[data-pantry-decrement]").forEach(button => button.addEventListener("click", () => { const name = button.dataset.pantryDecrement; const next = state.pantry[name].amount - pantryStep(name); if (next <= 0) delete state.pantry[name]; else state.pantry[name].amount = next; saveState(); render(); }));
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
  const meta = [recipe.tid ? metaIconItem(CLOCK_ICON, `${recipe.tid} min`) : "", metaIconItem(PORTIONS_ICON, `${state.personer} port`)].filter(Boolean).join("");
  return `<button type="button" class="week-today-card" data-week-details="${escapeHtml(recipe.id)}"><span class="week-today-photo">${recipePhoto(recipe)}</span><span class="week-today-info"><strong>${escapeHtml(recipe.namn)}</strong>${badge}<span class="week-today-meta">${meta}</span></span><span class="week-today-arrow" aria-hidden="true">›</span>${fb.cooked ? '<span class="week-today-flag" title="Lagade den här">✓</span>' : ""}</button>`;
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
  const campaign = live?.kampanj?.text ? `<small class="week-shopping-campaign">🏷️ ${escapeHtml(live.kampanj.text)}</small>` : "";
  const image = match?.imageUrl || live?.bild;
  const photo = image ? `<img class="shopping-item-image has-image" src="${escapeHtml(safeHttpUrl(image) || "")}" alt="" loading="lazy">` : categoryIconMarkup(itemCategory(item.namn));
  return `<label class="week-shopping-row"><input type="checkbox" data-week-shopping="${escapeHtml(item.namn)}">${photo}<span class="week-shopping-info"><strong>${escapeHtml(item.namn)}</strong>${campaign}</span><strong class="week-shopping-price ${missing ? "price-missing" : ""}">${price}</strong></label>`;
}
let weekDayAutoPicked = false;
function renderWeekOverview(selected, shoppingItems, total) {
  // Bara vid FÖRSTA målningen: att öppna appen en fredag med en
  // 4-middagarsvecka ska visa en planerad dag, inte "Ingen middag". Men den
  // som själv klickar på söndagsfliken ska självklart få se söndagen.
  if (!weekDayAutoPicked) {
    weekDayAutoPicked = true;
    if (!selected[weekOverviewDay]) weekOverviewDay = firstPlannedDayFrom(selected, weekOverviewDay);
  }
  $("weekDayTabs").innerHTML = DAYS.map((day, index) => `<button type="button" class="week-day-tab ${index === weekOverviewDay ? "active" : ""} ${selected[index] ? "" : "empty"}" data-week-day="${index}" role="tab" aria-selected="${index === weekOverviewDay}">${day}</button>`).join("");

  const todayRecipe = selected[weekOverviewDay];
  $("weekTodayCard").innerHTML = todayRecipe ? weekTodayCardMarkup(todayRecipe) : weekEmptyDayMarkup();

  const planVisibleCount = weekPlanExpanded ? selected.length : Math.min(selected.length, WEEK_PLAN_PREVIEW_COUNT);
  $("weekPlanList").innerHTML = selected.slice(0, planVisibleCount).map(weekPlanRowMarkup).join("");
  $("weekPlanToggle").hidden = selected.length <= WEEK_PLAN_PREVIEW_COUNT;
  $("weekPlanToggle").textContent = weekPlanExpanded ? "Visa färre" : "Visa hela veckan";
  $("weekPlanToggle").onclick = () => { weekPlanExpanded = !weekPlanExpanded; renderWeekOverview(selected, shoppingItems, total); };

  const remainingItems = shoppingItems.filter(item => !state.avklarade.has(item.namn));
  $("weekShoppingSummary").textContent = shoppingItems.length ? `${plural(remainingItems.length, "vara kvar", "varor kvar")}${total == null ? "" : ` · ${money(total)}`}` : "";
  $("weekShoppingPreview").innerHTML = shoppingItems.length
    ? (remainingItems.length ? remainingItems.slice(0, WEEK_SHOPPING_PREVIEW_COUNT).map(weekShoppingRowMarkup).join("") : `<p class="week-shopping-done">🎉 Allt handlat!</p>`)
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
  $("summaryBudgetRemaining").textContent = totalKnown ? money(Math.max(0, heroRemaining)) : "–";
  $("summaryBudgetTotal").textContent = money(state.budget);
  $("summaryBudgetPercent").textContent = totalKnown ? `${percentUsed}%` : "hämtas…";
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
  document.querySelectorAll("[data-week-browse-recipes]").forEach(button => button.addEventListener("click", () => $("recipeScroll")?.scrollIntoView({ behavior: "smooth" })));
  document.querySelectorAll("[data-week-shopping]").forEach(input => {
    input.checked = state.avklarade.has(input.dataset.weekShopping);
    input.addEventListener("change", () => { input.checked ? state.avklarade.add(input.dataset.weekShopping) : state.avklarade.delete(input.dataset.weekShopping); saveState(); renderBasket(); });
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
  $("homeGreeting").innerHTML = `${escapeHtml(name ? `${timeGreeting}, ${name}!` : `${timeGreeting}!`)} <span aria-hidden="true">👋</span>`;
}
function renderBasket() {
  const selected = selectedRecipes();
  ensureWeekRecipeDetails();
  const shoppingItems = aggregateShopping(selected);
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
  const activeDb = state.dbChainTotals[activeChain];
  const total = activeDb ? activeDb.totalCheckoutCost + extrasCost
    : currentResult && currentResult.source !== "estimate"
      ? currentResult.cost + extrasCost : null;
  const groups = shoppingItems.reduce((result, item) => { const category = itemCategory(item.namn); (result[category] ||= []).push(item); return result; }, {});
  // Tom lista av två helt olika skäl: ingen meny finns, eller användaren
  // har tagit bort varenda rad själv. Samma tomtillstånd för båda vore en
  // lögn om det första.
  const emptyState = state.removedItems.size
    ? `<div class="pantry-empty"><h2>Allt är borttaget ur listan</h2><p>Du har markerat varje vara som borttagen. Återställ dem nedan om du ångrar dig.</p></div>`
    : `<div class="pantry-empty"><h2>Listan väntar på din vecka</h2><p>Skapa en meny så samlar vi automatiskt allt du behöver handla.</p></div>`;
  $("shoppingList").innerHTML = shoppingItems.length ? Object.entries(groups).map(([category, items]) => `<section><h3>${category}<span>${items.length}</span></h3>${items.map(shoppingItemMarkup).join("")}</section>`).join("") : emptyState;
  if (state.removedItems.size) {
    $("shoppingList").insertAdjacentHTML("beforeend",
      `<button type="button" class="restore-removed" id="restoreRemovedBtn">${plural(state.removedItems.size, "borttagen vara", "borttagna varor")} · Återställ alla</button>`);
    $("restoreRemovedBtn").addEventListener("click", () => { state.removedItems.clear(); saveState(); render(); });
  }
  document.querySelectorAll("[data-shopping]").forEach(input => input.addEventListener("change", () => { input.checked ? state.avklarade.add(input.dataset.shopping) : state.avklarade.delete(input.dataset.shopping); saveState(); renderBasket(); }));
  document.querySelectorAll("[data-remove-item]").forEach(button => button.addEventListener("click", event => {
    // Knappen bor i en <label> - utan detta togglar klicket också checkboxen.
    event.preventDefault();
    event.stopPropagation();
    removeShoppingItem(button.dataset.removeItem);
  }));
  const completed = shoppingItems.filter(item => state.avklarade.has(item.namn)).length, itemsLeft = shoppingItems.length - completed, progress = shoppingItems.length ? completed / shoppingItems.length * 100 : 0;
  // No mention of how many items happen to have a live-fetched price, and no
  // fetch timestamp - that's internal plumbing, not something a shopper needs
  // to see. Only the plain, calm facts: what's left, and what it costs.
  $("shoppingProgress").textContent = shoppingItems.length ? plural(itemsLeft, "vara kvar", "varor kvar") : "";
  const nothingPlanned = !shoppingItems.length && !state.extraItems.length;
  $("shoppingCost").textContent = nothingPlanned
    ? `– / ${money(state.budget)}`
    : total == null && !shoppingItems.length && state.extraItems.length
      ? `${money(extrasCost)} / ${money(state.budget)}`
      : `${total == null ? "pris hämtas…" : money(total)} / ${money(state.budget)}`; $("shoppingProgressBar").style.width = `${progress}%`;
  // "Allt handlat" celebrates a finished list, never an empty one - and
  // extras count: a week isn't done while the added coffee is unbought.
  const extrasDone = state.extraItems.every(extra => extra.checked);
  $("shoppingComplete").hidden = !((shoppingItems.length || state.extraItems.length)
    && completed === shoppingItems.length && extrasDone);
  renderAttribution(shoppingItems);
  renderStoreComparison(selected); renderStoreCards(); renderExtraItems(activeChain); renderPantry();
  renderWeekStoreTabs();
  updateWeekStoreStatus();
  // Fed the exact same selected/shoppingItems/total this function just
  // computed - the overview and the full page below it are two views onto
  // one render pass, never two separate computations that could drift.
  renderWeekOverview(selected, shoppingItems, total);
  syncLivePrices(shoppingItems);
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
  const fromStores = [...new Set(nearbyBranches().map(branch => branch.kedja))].filter(Boolean);
  return fromStores.sort((a, b) => a.localeCompare(b, "sv"));
}

// Kept for the few places that ask "is this a real chain name" rather than
// "which chains are nearby" - now derived, so it can never drift from the
// store data.
const VALID_CHAINS = ["ICA", "Willys", "Hemköp", "Coop", "City Gross"];

function renderWeekStoreTabs() {
  const tabs = document.querySelector('[aria-label="Byt butik för veckan"]');
  if (!tabs) return;
  const fixed = ["auto", "alla"];
  const chains = availableChains();
  const wanted = [...fixed, ...chains];
  const current = [...tabs.querySelectorAll("[data-week-store]")].map(b => b.dataset.weekStore);
  if (current.join("|") !== wanted.join("|")) {
    tabs.innerHTML = wanted.map(value =>
      `<button type="button" data-week-store="${escapeHtml(value)}">${escapeHtml(value === "auto" ? "Auto" : value === "alla" ? "Alla" : value)}</button>`
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
const LIVE_PRICE_CONCURRENCY = 2;
async function fetchProductsBatch(chain, zip, names, onItem, storeKey, primatOnly) {
  const produkter = {};
  let nextIndex = 0;
  async function worker() {
    while (nextIndex < names.length) {
      const name = names[nextIndex++];
      try {
        // 35s timeout to give Coop's slower pages room to finish (matches the backend's own 30s bound on how long it'll wait per item).
        // primatOnly-fetches never scrape server-side (see the backend's own
        // docstring for why), so they're always fast regardless of this
        // timeout - it's sized for the non-primatOnly case.
        const response = await fetch(productsBatchApiUrl(), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ butik: chain, zip, varor: [name], ...(storeKey ? { butiksnyckel: storeKey } : {}), ...(primatOnly ? { primatOnly: true } : {}) }), signal: AbortSignal.timeout(35000) });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const found = (await response.json()).produkter || {};
        Object.assign(produkter, found);
        onItem?.(found);
      } catch { /* den här varan missade - resten av listan hämtas ändå */ }
    }
  }
  await Promise.all(Array.from({ length: Math.min(LIVE_PRICE_CONCURRENCY, names.length) }, worker));
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
      // loadRecipe swallows network errors and resolves null - a deploy
      // window's failed fetch must not poison the once-per-id set, or the
      // shopping list stays empty until a full reload.
      if (!detail) { recipeDetailFetches.delete(recipe.id); return; }
      // Merge in place: every list, week and favourites reference THIS
      // object, so replacing it would orphan them.
      Object.assign(recipe, detail, { steg: detail.instructions || detail.steg || [] });
      renderBasket();
    }).catch(() => recipeDetailFetches.delete(recipe.id));
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
  if (everything.length && (state.removedItems.size || state.avklarade.size)) {
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

function removeShoppingItem(name) {
  state.removedItems.add(name);
  // A removed item is not a BOUGHT item - it left the list entirely.
  state.avklarade.delete(name);
  // Cached live totals priced the removed item; painting them once more
  // would show the OLD sum next to the new list. Drop them and let the
  // refetch fill honest numbers in.
  clearPriceSnapshots();
  saveState();
  render();
  showUndoToast(`${name} borttagen`, () => {
    state.removedItems.delete(name);
    clearPriceSnapshots();
    saveState();
    render();
  });
}

// En enda toast åt gången: en ny borttagning ersätter den förra i stället
// för att stapla remsor över navigeringen.
let undoToastTimer = null;
function showUndoToast(message, onUndo) {
  const toast = $("undoToast");
  toast.querySelector("span").textContent = message;
  toast.hidden = false;
  const button = toast.querySelector("button");
  button.onclick = () => { clearTimeout(undoToastTimer); toast.hidden = true; onUndo(); };
  clearTimeout(undoToastTimer);
  undoToastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
}

function updateSummary() {
  const hasWeek = selectedRecipes().length > 0;
  $("generateBtnLabel").textContent = hasWeek ? "Öppna veckan" : "Skapa min vecka";
  $("newWeekBtn").hidden = !hasWeek;
  $("weekCardStatus").textContent = hasWeek ? "Veckan är klar" : "Redo";
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
function syncSettingsInputs() {
  $("budgetInput").value = state.budget; $("peopleValue").textContent = state.personer; $("mealsValue").textContent = state.middagar; $("storeInput").value = state.butik; $("postcodeInput").value = state.postnummer;
  $("kosttypInput").value = state.kost.kosttyp;
  document.querySelectorAll("#allergenChips input").forEach(box => { box.checked = state.kost.avoidAllergens.has(box.value);   const timeFilter = $("timeFilter");
  if (timeFilter) timeFilter.value = String(state.maxTid || "");
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

function openWeekSheet() { $("weekSheet").hidden = false; document.body.style.overflow = "hidden"; }
function closeWeekSheet() { $("weekSheet").hidden = true; document.body.style.overflow = ""; }
$("budgetCardBtn").addEventListener("click", openWeekSheet);
$("weekSheetOpen").addEventListener("click", openWeekSheet);
$("weekSheetClose").addEventListener("click", closeWeekSheet);
$("weekSheetDone").addEventListener("click", closeWeekSheet);
$("weekSheet").addEventListener("click", event => { if (event.target === $("weekSheet")) closeWeekSheet(); });
document.addEventListener("keydown", event => { if (event.key === "Escape" && !$("weekSheet").hidden) closeWeekSheet(); });
$("sheetPlanBtn").addEventListener("click", () => { closeWeekSheet(); openPlanComparison(); });

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
function setView(view) { $("top").className = `app view-${view}`; document.querySelectorAll(".bottom-nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view)); window.scrollTo({ top: 0, behavior: "smooth" }); }
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
function renderAccount() {
  const loggedIn = Boolean(state.user);
  $("accountLoggedOut").hidden = loggedIn;
  $("accountLoggedIn").hidden = !loggedIn;
  $("profileBtn").textContent = loggedIn ? state.user.email.slice(0, 2).toUpperCase() : "MJ";
  $("profileBtn").classList.toggle("is-premium", hasPremium());
  syncSettingsInputs();
  if (loggedIn) {
    $("accountEmail").textContent = state.user.email;
    $("verifyEmailNotice").hidden = state.user.emailVerified;
    const daysLeft = state.user.trialEndsAt ? Math.max(1, Math.ceil((new Date(state.user.trialEndsAt) - Date.now()) / 86400000)) : 0;
    const hasSubscription = ["active", "trialing", "past_due", "canceled", "unpaid"].includes(state.user.subscriptionStatus);
    $("accountPremiumStatus").textContent = daysLeft ? `✓ Provperiod aktiv - ${plural(daysLeft, "dag", "dagar")} kvar (ingen betalning krävs)` : state.user.premium ? "✓ Premium aktiverat" : "Inget Premium ännu";
    $("premiumPitch").hidden = state.user.premium;
    $("subscriptionPanel").hidden = !hasSubscription;
    if (hasSubscription) {
      const periodEnd = state.user.subscriptionPeriodEnd ? new Date(state.user.subscriptionPeriodEnd).toLocaleDateString("sv-SE") : "okänt datum";
      const planLabel = state.user.subscriptionPlan === "yearly" ? "399 kr/år" : "59 kr/mån";
      let line;
      if (state.user.subscriptionStatus === "active" && state.user.subscriptionCancelAtPeriodEnd) line = `Din prenumeration (${planLabel}) är uppsagd och gäller till ${periodEnd}, sedan återgår kontot till gratisversionen.`;
      else if (state.user.subscriptionStatus === "active") line = `Din prenumeration (${planLabel}) förnyas automatiskt ${periodEnd}.`;
      else if (state.user.subscriptionStatus === "past_due") line = `Senaste betalningen (${planLabel}) gick inte igenom - uppdatera din betalmetod för att behålla Premium.`;
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
  const campaignNote = campaignIngredient ? `<small class="swap-option-campaign">🏷️ Kampanj på ${escapeHtml(campaignIngredient)}</small>` : "";
  return `<button type="button" class="swap-option ${isSelected ? "selected" : ""}" data-choose-swap="${escapeHtml(recipe.id)}"><span class="swap-option-photo">${recipePhoto(recipe)}</span><span class="swap-option-info"><strong>${escapeHtml(recipe.namn)}</strong>${badge}<small class="swap-option-meta">${[recipe.tid ? `${recipe.tid} min` : "", price].filter(Boolean).join(" · ")}</small>${campaignNote}</span>${isSelected ? '<span class="swap-option-check" aria-hidden="true">✓</span>' : ""}</button>`;
}
const FREE_SWAP_LIMIT = 3;
function openSwapModal(currentId) {
  if (!hasPremium() && state.swapsThisWeek >= FREE_SWAP_LIMIT) {
    $("swapModalHint").textContent = "";
    $("swapOptions").innerHTML = `<button type="button" class="store-compare-upsell" id="swapUpsell">🔒 Du har använt dina ${FREE_SWAP_LIMIT} gratis byten den här veckan. Med Premium byter du hur mycket du vill.</button>`;
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
  const allOptions = candidates.map(candidate => ({ candidate, total: candidate.portionspris || 9999 })).sort((a, b) => a.total - b.total);
  if (!allOptions.length) { $("swapModalHint").textContent = ""; $("swapOptions").innerHTML = `<p class="live-loading">Inga alternativ hittades som passar budget, butik och dina filter just nu.</p>`; $("swapConfirmBtn").hidden = true; $("swapShowMoreBtn").hidden = true; $("swapModal").hidden = false; return; }
  swapContext = { currentId, dayIndex, allOptions, visibleCount: SWAP_OPTIONS_BATCH, selectedId: null };
  renderSwapModal();
  $("swapModal").hidden = false;
}
function renderSwapModal() {
  if (!swapContext) return;
  const { currentId, dayIndex, allOptions, visibleCount, selectedId } = swapContext;
  const currentRecipe = selectedRecipes().find(r => r.id === currentId);
  const dayLabel = DAYS[dayIndex] || `Dag ${dayIndex + 1}`;
  $("swapModalHint").innerHTML = `${dayLabel}s middag${currentRecipe ? ` · nuvarande: ${escapeHtml(currentRecipe.namn)}` : ""}`;
  $("swapOptions").innerHTML = allOptions.slice(0, visibleCount).map(option => swapOptionMarkup(option, option.candidate.id === selectedId)).join("");
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
    ? `<button class="btn btn-primary plan-locked-btn" type="button" data-plan-paywall="${plan.key}"><span>🔒 Lås upp med Premium</span></button>`
    : `<button class="btn btn-primary" type="button" data-choose-plan="${plan.key}"><span>Välj den här</span></button>`;
  return `<div class="plan-card ${locked ? "plan-card-locked" : ""}"><div class="plan-card-head"><strong>${locked ? "🔒 " : ""}${plan.label}</strong><span>${plan.hint}</span></div><div class="plan-card-price" data-plan-price="${plan.key}"><b>pris beräknas…</b><small>mot riktiga butikspriser</small></div>${plan.highlight ? `<p class="plan-card-highlight">${escapeHtml(String(plan.highlight(plan.combo, plan.cost, portions)))}</p>` : ""}<ul class="plan-card-meals">${plan.combo.map(recipe => `<li>${escapeHtml(recipe.namn)}</li>`).join("")}</ul>${chooseButton}</div>`;
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
        body: JSON.stringify({ recipeIds, people: state.personer, pantry: pantryAmounts(state.pantry || {}) }),
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
    state.savingsLog.push({ date: new Date().toISOString().slice(0, 10), savings: Math.max(0, (priciest?.cost || plan.cost) - plan.cost), hasComparison: hasRealComparison, branch: branch?.namn || "", portionCost: plan.cost / (plan.combo.length * state.personer) });
    state.savingsLog = state.savingsLog.slice(-60);
    state.swapsThisWeek = 0;
    setWeekPlan(plan.combo.map(recipe => recipe.id));
    state.avklarade.clear();
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
  const branchCounts = {};
  state.savingsLog.forEach(entry => { if (entry.branch) branchCounts[entry.branch] = (branchCounts[entry.branch] || 0) + 1; });
  const cheapestName = Object.entries(branchCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || selectedBranch()?.namn || "-";
  const avgPortion = state.savingsLog.length ? state.savingsLog.reduce((sum, entry) => sum + entry.portionCost, 0) / state.savingsLog.length : 0;
  const reused = reusedIngredientCount();
  $("statSavedWeek").textContent = weekEntries.length ? money(savedWeek) : "Underlag saknas";
  $("statSavedMonth").textContent = monthEntries.length ? money(savedMonth) : "Underlag saknas";
  $("statCheapestStore").textContent = cheapestName;
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

const DISLIKE_SUGGESTIONS = ["Lök", "Svamp", "Fisk", "Skaldjur", "Nötter", "Inälvsmat", "Stark mat", "Kokosmjölk"];
// Fyra steg, inte sju. En förstagångare ska svara på det Matjakt inte kan
// gissa - vilka ni är, vad ni vill lägga, vad ni inte äter, var ni handlar -
// och sedan SE sin vecka. Tidsfiltret bor i Recept-fliken och kalorier/makron
// är en Premium-inställning i "Justera veckan"; mitt i onboardingen var de
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
  return `<label for="obBudget">Veckobudget</label><div class="budget-row"><input type="number" id="obBudget" value="${state.budget}" min="0" step="50" inputmode="numeric"><span>kr</span></div><div class="settings-grid"><div><label>Middagar per vecka</label><div class="stepper"><button type="button" data-ob-meals="-1" aria-label="Färre middagar">−</button><span>${state.middagar}</span><button type="button" data-ob-meals="1" aria-label="Fler middagar">+</button></div></div></div>`;
}
function renderObKost() {
  return `<label for="obKosttyp">Kosttyp</label><select id="obKosttyp"><option value="" ${!state.kost.kosttyp ? "selected" : ""}>Vanlig, allt</option><option value="vegetariskt" ${state.kost.kosttyp === "vegetariskt" ? "selected" : ""}>Vegetariskt</option><option value="veganskt" ${state.kost.kosttyp === "veganskt" ? "selected" : ""}>Veganskt</option></select><label>Allergier att undvika</label><div class="protein-source-chips" id="obAllergenChips">${ALLERGENS.map(a => `<label><input type="checkbox" value="${a}" ${state.kost.avoidAllergens.has(a) ? "checked" : ""}> ${a[0].toUpperCase() + a.slice(1)}</label>`).join("")}</div>`;
}
function renderObOgillar() {
  const chips = DISLIKE_SUGGESTIONS.map(term => `<label><input type="checkbox" value="${term}" ${state.ogillar.has(term) ? "checked" : ""}> ${term}</label>`).join("");
  const tags = state.ogillar.size ? `<div class="ob-tag-list">${[...state.ogillar].filter(term => !DISLIKE_SUGGESTIONS.includes(term)).map(term => `<span class="ob-tag">${escapeHtml(term)}<button type="button" data-ob-remove-dislike="${escapeHtml(term)}" aria-label="Ta bort ${escapeHtml(term)}">×</button></span>`).join("")}</div>` : "";
  return `<label>Vanliga saker att slippa</label><div class="protein-source-chips" id="obDislikeChips">${chips}</div><label for="obDislikeCustom">Något annat? Skriv och tryck Enter</label><input id="obDislikeCustom" type="text" placeholder="t.ex. oliver">${tags}`;
}
function renderObTid() {
  return `<label for="obMaxTid">Hur lång tid vill ni lägga på matlagning?</label><select id="obMaxTid"><option value="0" ${!state.maxTid ? "selected" : ""}>Ingen gräns</option><option value="20" ${state.maxTid === 20 ? "selected" : ""}>Max 20 min</option><option value="30" ${state.maxTid === 30 ? "selected" : ""}>Max 30 min</option><option value="45" ${state.maxTid === 45 ? "selected" : ""}>Max 45 min</option></select>`;
}
function renderObNaring() {
  const premium = hasPremium();
  return `<p class="ob-teaser">${premium ? `Du har redan Premium - ställ in exakta mål för kalorier, protein, kolhydrater och fett under "Justera veckan" på Hem.` : `Med Premium kan Matjakt styra veckan efter kalorier, protein, kolhydrater, fett och proteinkälla per måltid - inte bara pris. Du kan sätta det senare under "Justera veckan".`}</p>${premium ? "" : `<div class="ob-premium-badge">59 kr/mån · Premium</div>`}`;
}
function renderObButik() {
  return `<label for="obPostcode">Postnummer</label><div class="location-row"><input id="obPostcode" value="${escapeHtml(state.postnummer)}" inputmode="numeric" maxlength="5"><button type="button" id="obLocateBtn">Hitta mig</button></div><p class="ob-error" id="obPostcodeError"></p><label for="obStore">Favoritbutik</label><select id="obStore"><option value="auto" ${state.butik === "auto" ? "selected" : ""}>Välj åt mig</option><option value="alla" ${state.butik === "alla" ? "selected" : ""}>Alla butiker</option><option value="ICA" ${state.butik === "ICA" ? "selected" : ""}>ICA</option><option value="Willys" ${state.butik === "Willys" ? "selected" : ""}>Willys</option><option value="Hemköp" ${state.butik === "Hemköp" ? "selected" : ""}>Hemköp</option><option value="City Gross" ${state.butik === "City Gross" ? "selected" : ""}>City Gross</option></select>`;
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
  document.querySelectorAll("#obDislikeChips input").forEach(box => box.addEventListener("change", () => { box.checked ? state.ogillar.add(box.value) : state.ogillar.delete(box.value); saveState(); renderOnboardingStep(); }));
  const customDislike = $("obDislikeCustom");
  customDislike?.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); const value = customDislike.value.trim(); if (value) { state.ogillar.add(value); saveState(); renderOnboardingStep(); } } });
  document.querySelectorAll("[data-ob-remove-dislike]").forEach(button => button.addEventListener("click", () => { state.ogillar.delete(button.dataset.obRemoveDislike); saveState(); renderOnboardingStep(); }));
  $("obMaxTid")?.addEventListener("change", e => { state.maxTid = Number(e.target.value); saveState(); });
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
$("forgotPasswordForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("forgotError").textContent = ""; $("forgotSuccess").hidden = true;
  try {
    await requestPasswordReset($("forgotEmail").value);
    $("forgotSuccess").hidden = false;
    event.target.reset();
  } catch (error) { $("forgotError").textContent = error.message; }
});
let pendingResetToken = new URLSearchParams(location.search).get("reset");
$("resetPasswordForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("resetError").textContent = "";
  try {
    await resetPassword(pendingResetToken, $("resetPasswordInput").value);
    pendingResetToken = null;
    history.replaceState(null, "", location.pathname);
    showAccountForm("login");
    $("loginError").textContent = "Lösenordet är ändrat. Logga in med det nya lösenordet.";
    event.target.reset();
  } catch (error) { $("resetError").textContent = error.message; }
});
$("resendVerificationBtn").addEventListener("click", async () => {
  $("verifyError").textContent = "";
  try {
    await resendVerification(state.authToken);
    $("verifyError").textContent = "Skickat! Kolla din inkorg.";
  } catch (error) { $("verifyError").textContent = error.message; }
});
$("deleteAccountBtn").addEventListener("click", async () => {
  $("deleteError").textContent = "";
  if (!confirm("Radera ditt konto permanent? Det går inte att ångra.")) return;
  try {
    await deleteAccount(state.authToken);
    state.authToken = null; state.user = null; storeToken(null);
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
  } catch {
    state.authToken = null;
    storeToken(null);
    state.user = null;
  }
  renderAccount();
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
      return `<div class="campaign-deal"><span class="campaign-deal-image">${photo}<span class="campaign-deal-badge">−${deal.discountPercent}%</span></span><span class="campaign-deal-info"><strong>${escapeHtml(deal.name)}</strong>${deal.brand || deal.size ? `<small class="campaign-deal-brand">${escapeHtml([deal.brand, deal.size].filter(Boolean).join(" · "))}</small>` : ""}<span class="campaign-deal-price-row"><strong class="campaign-deal-price">${money(deal.campaignPrice)}</strong><s>${money(deal.regularPrice)}</s></span><span class="campaign-deal-store" style="color:${storeColor}">${escapeHtml(deal.chain)}</span>${addButton}</span></div>`;
    }).join("");
    ownCampaignDeals = all;
    document.querySelectorAll("[data-deal-add]").forEach(button => button.addEventListener("click", () => {
      const deal = ownCampaignDeals.find(d => String(d.productId) === button.dataset.dealAdd);
      if (!deal) return;
      addExtraItem({
        name: deal.name, source: "campaign", chain: deal.chain,
        productId: deal.productId, gtin: deal.gtin, imageUrl: deal.imageUrl,
        packageSize: deal.size, campaignPrice: deal.campaignPrice,
        regularPrice: deal.regularPrice, validUntil: deal.validUntil,
      });
      button.textContent = "✓ Tillagd"; button.disabled = true; button.classList.add("added");
    }));
  } catch {
    ownCampaignFetchKey = null;
    $("campaignList").innerHTML = `<p class="live-loading">Kunde inte hämta kampanjer just nu.</p>`;
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
$("accountLoginForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("loginError").textContent = "";
  try {
    const { token, user } = await login($("loginEmail").value, $("loginPassword").value);
    state.authToken = token; state.user = user; storeToken(token);
    await pullAccountState();
    event.target.reset(); renderAccount(); closeAccountModal();
  } catch (error) { $("loginError").textContent = error.message; }
});
$("accountRegisterForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("registerError").textContent = "";
  try {
    const { token, user } = await register($("registerEmail").value, $("registerPassword").value);
    state.authToken = token; state.user = user; storeToken(token);
    await pullAccountState();
    event.target.reset(); renderAccount(); closeAccountModal();
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
    <button type="button" class="paywall-continue" data-paywall-close>Fortsätt gratis</button>
  </div>`;
  modal.hidden = false;
  modal.querySelectorAll("[data-paywall-close]").forEach(el =>
    el.addEventListener("click", () => { modal.hidden = true; }));
  modal.querySelectorAll("[data-paywall-plan]").forEach(el =>
    el.addEventListener("click", () => beginCheckout(el.dataset.paywallPlan)));
}

async function beginCheckout(plan) {
  if (!state.user) {
    document.getElementById("paywallModal").hidden = true;
    openAccountModal?.();
    return;
  }
  try {
    const { url } = await startCheckout(getStoredToken(), plan);
    if (url) location.href = url;
  } catch (error) {
    alert(error?.message || "Kunde inte starta betalningen just nu.");
  }
}

function openPremiumPitch() { openPaywall(); }
let selectedPlan = "monthly";
document.querySelectorAll("[data-price-tab]").forEach(tab => tab.addEventListener("click", () => { selectedPlan = tab.dataset.plan; document.querySelectorAll("[data-price-tab]").forEach(t => t.classList.toggle("active", t === tab)); }));
$("subscribeBtn").addEventListener("click", async () => {
  $("checkoutError").textContent = "";
  if (!state.authToken) { $("checkoutError").textContent = "Skapa ett konto eller logga in först."; return; }
  try {
    const { url } = await startCheckout(state.authToken, selectedPlan);
    window.location.href = url;
  } catch (error) { $("checkoutError").textContent = error.message; }
});
$("manageBillingBtn").addEventListener("click", async () => {
  $("portalError").textContent = "";
  try {
    const { url } = await openBillingPortal(state.authToken);
    window.location.href = url;
  } catch (error) { $("portalError").textContent = error.message; }
});
$("gateLogoutBtn").addEventListener("click", () => window.__matjaktGateLock());
$("logoutBtn").addEventListener("click", async () => {
  if (state.authToken) { try { await logoutRequest(state.authToken); } catch { /* session redan ogiltig server-side, städa lokalt ändå */ } }
  state.authToken = null; state.user = null; storeToken(null);
  // Utloggning är ett byte av person, inte en paus: skafferi, vecka,
  // allergival och historik tillhör KONTOT. Kvarlämnat laddades det upp
  // till NÄSTA konto som registrerades på enheten (bootstrap-grenen i
  // pullAccountState) - förra användarens allergier och skafferi blev
  // den nyas. Inställningar av apparat-karaktär (postnummer, butik,
  // onboarding klar) får stanna.
  state.pantry = {};
  state.valda = new Set(); state.weekPlan = [];
  state.avklarade = new Set(); state.removedItems = new Set();
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
  $("pantryPickerList").innerHTML = matches.length ? matches.map(([key, product]) => `<button type="button" class="pantry-pick" data-pantry-pick="${escapeHtml(key)}"><span class="pantry-pick-info"><strong>${escapeHtml(product.namn)}</strong><small>${escapeHtml([product.marke && product.marke !== "ICA" ? product.marke : "", product.storlek].filter(Boolean).join(" · "))}</small></span><span class="pantry-pick-add">+ Lägg till</span></button>`).join("") : !search ? "" : `<p class="pantry-picker-empty">Inga vanliga varor matchar "${escapeHtml(query)}".</p>`;
  document.querySelectorAll("[data-pantry-pick]").forEach(button => button.addEventListener("click", () => openPantryAddConfirm(button.dataset.pantryPick, PRODUCT_CATALOG[button.dataset.pantryPick])));
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
      if (product) openPantryAddConfirm(product.produktnamn, { namn: product.produktnamn, marke: product.marke_och_storlek || "", storlek: "" });
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
    const entry = state.pantry[key] || { amount: 0, location: pantryPickLocation, expiry: null };
    // Ett påfyllt paket ska inte RADERA vad som redan är känt: lämnas
    // datumfältet tomt behålls befintligt bäst före-datum, och en vara som
    // redan har en plats behåller den om användaren inte aktivt bytt flik.
    state.pantry[key] = {
      amount: entry.amount + (PACKAGE_INFO[key]?.amount || 1),
      location: pantryPickLocation,
      expiry: $("pantryAddExpiry").value || entry.expiry || null,
    };
    saveState(); render(); closePantryModal();
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
  return `<button type="button" class="cook-match" data-cook-open="${escapeHtml(id)}">${bild ? `<img src="${escapeHtml(bild)}" alt="">` : `<span class="cook-match-fallback">🍽️</span>`}<span class="cook-match-info"><strong>${escapeHtml(namn)}</strong><small>Matchar: ${matched.map(escapeHtml).join(", ")}</small></span></button>`;
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
  const pantryNames = Object.keys(state.pantry);
  const dietFilterActive = state.kost.kosttyp !== "" || state.kost.avoidAllergens.size > 0;
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
if (!state.valda.size) chooseMenu(false); else render();
renderRecipePage();
refreshUser();
syncNearbyBranches();
// A first-time visitor arriving through a SHARED RECIPE LINK came for the
// recipe - onboarding on top of it would bury the very thing that brought
// them here. It opens on their next natural visit instead.
if (!state.onboardingComplete && !new URLSearchParams(location.search).get("recept")) openOnboarding();
const billingResult = new URLSearchParams(location.search).get("billing");
if (billingResult) {
  history.replaceState(null, "", location.pathname);
  if (billingResult === "success") { refreshUser().then(() => openAccountModal()); chooseMenu(false); }
}
if (pendingResetToken) { openAccountModal(); showAccountForm("reset"); }
const pendingVerifyToken = new URLSearchParams(location.search).get("verify");
if (pendingVerifyToken) {
  verifyEmail(pendingVerifyToken).then(({ user }) => {
    if (state.user) state.user = user;
    history.replaceState(null, "", location.pathname);
    renderAccount();
    openAccountModal();
  }).catch(() => { history.replaceState(null, "", location.pathname); });
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
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => { /* offline-stödet är ett tillägg - appen funkar utan det */ }));
}
