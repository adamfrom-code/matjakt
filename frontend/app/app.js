import { readStoredState, writeStoredState } from "./src/state/storage.js";
import { aggregateIngredients, budgetRemaining, calculateLiveShoppingTotal, calculateShoppingTotal, clampBudget, portionFactor } from "./src/services/calculations.js";
import { createDebouncedSearch, filterRecipes, mergeRecipeResults } from "./src/services/recipe-search.js";
import { filterByNutritionGoals, hasActiveNutritionGoals } from "./src/services/nutrition.js";
import { expiryStatus, matchLocalRecipesToPantry, normalizePantry, pantryAmounts } from "./src/services/pantry.js";
import { ALLERGENS, filterByDiet } from "./src/services/diet.js";
import { inBudgetPool, limitCandidatePool, pickBalanced, pickCheapest, pickProtein } from "./src/services/planning.js";
import { campaignsApiUrl, geocodeApiUrl, groceryStatusApiUrl, pricingListApiUrl, pricingWeekApiUrl, productApiUrl as configuredProductApiUrl, productsBatchApiUrl, recipeDetailApiUrl, recipeSearchApiUrl, recipesByPantryApiUrl, storesApiUrl } from "./src/api/config.js";
import { deleteAccount, fetchAccountState, fetchCurrentUser, getStoredToken, login, logout as logoutRequest, openBillingPortal, redeemPremium, register, requestPasswordReset, resendVerification, resetPassword, saveAccountState, startCheckout, startTrial, storeToken, verifyEmail } from "./src/api/auth.js";
import { escapeHtml, safeHttpUrl } from "./src/utils/html.js";

const RECEPT = [
  { id: "kycklinggryta", namn: "Kycklinggryta med ris", emoji: "🍛", bild: "assets/recipes/kycklinggryta.jpg", kcal: 580, protein: 36, kolhydrater: 52, fett: 25, proteinkalla: "kyckling", allergener: [], butik: "Willys", tid: 30, typ: "Familjefavorit", portionspris: 24.5, inkopspris: 105.3, sparar: 31, ingredienser: ["Kycklinglårfilé", "Ris", "Kokosmjölk", "Curry & grönsaker"], hemma: ["Olja", "Salt"] },
  { id: "pastagratang", namn: "Pastagratäng med purjolök", emoji: "🍝", bild: "assets/recipes/pastagratang.jpg", kcal: 404, protein: 16, kolhydrater: 49, fett: 15, proteinkalla: "vegetariskt", allergener: ["gluten", "laktos"], butik: "ICA", tid: 35, typ: "Vegetarisk", portionspris: 18, inkopspris: 72.6, sparar: 22, ingredienser: ["Pasta", "Purjolök", "Grädde", "Riven ost"], hemma: ["Salt", "Peppar"] },
  { id: "linssoppa", namn: "Röd linssoppa", emoji: "🥣", bild: "assets/recipes/linssoppa.jpg", kcal: 405, protein: 19, kolhydrater: 30, fett: 19, proteinkalla: "veganskt", allergener: [], butik: "Willys", tid: 25, typ: "Vegetarisk", portionspris: 12, inkopspris: 48.2, sparar: 18, ingredienser: ["Röda linser", "Kokosmjölk", "Morötter", "Lök & vitlök"], hemma: ["Buljong", "Olja"] },
  { id: "korvstroganoff", namn: "Korvstroganoff", emoji: "🍲", bild: "assets/recipes/korvstroganoff.jpg", kcal: 571, protein: 20, kolhydrater: 61, fett: 27, proteinkalla: "flask", allergener: ["laktos"], butik: "Coop", tid: 25, typ: "Snabbt & enkelt", portionspris: 15.5, inkopspris: 70.2, sparar: 16, ingredienser: ["Falukorv", "Grädde", "Tomatpuré", "Ris"], hemma: ["Salt", "Peppar"] },
  { id: "tacobonor", namn: "Tacobowl med svarta bönor", emoji: "🌮", bild: "assets/recipes/tacobonor.jpg", kcal: 371, protein: 14, kolhydrater: 68, fett: 2, proteinkalla: "vegetariskt", allergener: [], butik: "ICA", tid: 20, typ: "Vegetarisk", portionspris: 16.5, inkopspris: 66.4, sparar: 25, ingredienser: ["Svarta bönor", "Ris", "Majs", "Salsa"], hemma: ["Kryddor"] },
  { id: "fiskpasta", namn: "Krämig fiskpasta", emoji: "🐟", bild: "assets/recipes/fiskpasta.jpg", kcal: 486, protein: 29, kolhydrater: 48, fett: 19, proteinkalla: "fisk", allergener: ["gluten", "laktos", "fisk"], butik: "Coop", tid: 30, typ: "Fisk", portionspris: 27, inkopspris: 109.5, sparar: 20, ingredienser: ["Fryst torsk", "Pasta", "Crème fraiche", "Citron"], hemma: ["Salt", "Peppar"] }
];

const recipePhoto = recipe => recipe.bild ? `<img class="recipe-photo" src="${recipe.bild}" alt="${recipe.namn}" loading="lazy">` : `<span class="recipe-photo recipe-fallback" role="img" aria-label="Ingen matbild tillgänglig"><svg viewBox="0 0 64 64"><path d="M14 48h36M18 44a14 14 0 0 1 28 0M32 20v10M27 20h10"/></svg><small>Matjakt</small></span>`;
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
const state = { budget: savedState.budget || 800, personer: savedState.personer || 2, middagar: savedState.middagar || 4, butik: savedState.butik || "auto", postnummer: savedState.postnummer || "80252", position: null, sokning: "", kategori: "alla", maxTid: savedState.maxTid || 0, baraFavoriter: false, apiRecipes: savedState.apiRecipes || [], pantry: normalizePantry(savedState.pantry || {}), pantryTab: "skafferi", liveProdukter: [], favoriter: new Set(savedState.favoriter || []), valda: new Set(savedState.valda || []), avklarade: new Set(savedState.avklarade || []), expanded: null, authToken: getStoredToken(), user: null, naringsmal: savedState.naringsmal || null, livePriser: {}, liveBranchTotals: {}, liveUpdatedAt: null, dbChainTotals: {}, dbComparison: null, dbPricedAt: null, branches: [], betyg: savedState.betyg || {}, kost: { kosttyp: savedState.kost?.kosttyp || "", avoidAllergens: new Set(savedState.kost?.avoidAllergens || []) }, onboardingComplete: savedState.onboardingComplete || false, hushall: savedState.hushall || { vuxna: savedState.personer || 2, barn: 0 }, ogillar: new Set(savedState.ogillar || []), feedback: savedState.feedback || {}, savingsLog: savedState.savingsLog || [], swapsThisWeek: savedState.swapsThisWeek || 0, pinnedBranch: savedState.pinnedBranch || null,
  // The week's recipe ids in day order (index 0 = Måndag) - the actual
  // source of truth for "which day has which recipe", now that a day swap
  // has to replace exactly one day's recipe in place. state.valda (a Set)
  // stays around alongside it purely as an O(1) "is this recipe anywhere in
  // my week" membership check for recipe-card UI - every place that needs
  // day order or a specific day's recipe reads weekPlan / selectedRecipes(),
  // never valda's own iteration order (a Set has none tied to day position).
  weekPlan: Array.isArray(savedState.weekPlan) ? savedState.weekPlan : [...(savedState.valda || [])] };
function buildSyncPayload() {
  return { budget: state.budget, personer: state.personer, middagar: state.middagar, butik: state.butik, postnummer: state.postnummer, maxTid: state.maxTid, pantry: state.pantry, favoriter: [...state.favoriter], valda: [...state.valda], avklarade: [...state.avklarade], apiRecipes: state.apiRecipes.filter(recipe => state.valda.has(recipe.id)), naringsmal: state.naringsmal, betyg: state.betyg, kost: { kosttyp: state.kost.kosttyp, avoidAllergens: [...state.kost.avoidAllergens] }, onboardingComplete: state.onboardingComplete, hushall: state.hushall, ogillar: [...state.ogillar], feedback: state.feedback, savingsLog: state.savingsLog, swapsThisWeek: state.swapsThisWeek, pinnedBranch: state.pinnedBranch, weekPlan: state.weekPlan };
}
function applySyncBlob(blob) {
  if (!blob) return;
  if (blob.budget !== undefined) state.budget = blob.budget;
  if (blob.personer !== undefined) state.personer = blob.personer;
  if (blob.middagar !== undefined) state.middagar = blob.middagar;
  if (blob.butik !== undefined) state.butik = blob.butik;
  if (blob.postnummer !== undefined) state.postnummer = blob.postnummer;
  if (blob.maxTid !== undefined) state.maxTid = blob.maxTid;
  if (blob.pantry !== undefined) state.pantry = normalizePantry(blob.pantry);
  if (blob.favoriter !== undefined) state.favoriter = new Set(blob.favoriter);
  if (blob.valda !== undefined) state.valda = new Set(blob.valda);
  if (blob.avklarade !== undefined) state.avklarade = new Set(blob.avklarade);
  if (blob.apiRecipes !== undefined) state.apiRecipes = blob.apiRecipes;
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
    } else {
      // First time this account has ever synced - bootstrap the server with
      // whatever was already built up locally (e.g. as a guest before logging in).
      await saveAccountState(state.authToken, buildSyncPayload());
    }
  } catch { /* offline eller serverfel - den lokala datan används tills nästa försök */ }
}
function saveState() { writeStoredState(localStorage, buildSyncPayload()); scheduleServerSync(); }
const FALLBACK_BRANCH = [{ kedja: "Willys", namn: "Butik nära dig (uppskattat)", lat: null, lon: null, avstandKm: 0, prisfaktor: 1 }];
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
RECEPT.push(
  { id: "lax", namn: "Ugnsbakad lax med potatis", emoji: "🐟", bild: "assets/recipes/lax.jpg", kcal: 488, protein: 34, kolhydrater: 36, fett: 22, proteinkalla: "fisk", allergener: ["fisk"], butik: "ICA", tid: 35, typ: "Fisk", portionspris: 29, inkopspris: 116, sparar: 24, ingredienser: ["Laxfilé", "Potatis", "Citron", "Dill"], hemma: ["Salt", "Olja"], beskrivning: "En enkel ugnsmiddag med citron och dill.", steg: ["Sätt ugnen på 200°C.", "Lägg lax och potatis i en form.", "Toppa med citron och dill och baka tills laxen är klar."] },
  { id: "halloumibowl", namn: "Halloumibowl med rostade grönsaker", emoji: "🥗", bild: "assets/recipes/halloumibowl.jpg", kcal: 445, protein: 21, kolhydrater: 51, fett: 15, proteinkalla: "vegetariskt", allergener: ["gluten", "laktos"], butik: "Willys", tid: 30, typ: "Vegetarisk", portionspris: 23, inkopspris: 92, sparar: 19, ingredienser: ["Halloumi", "Matvete", "Paprika", "Yoghurt"], hemma: ["Olja", "Kryddor"], beskrivning: "Färgstark bowl med krispig halloumi.", steg: ["Koka matvetet enligt förpackningen.", "Rosta grönsakerna i ugnen.", "Stek halloumin och servera med yoghurt."] },
  { id: "chili", namn: "Chili sin carne", emoji: "🌶️", bild: "assets/recipes/chili.jpg", kcal: 179, protein: 11, kolhydrater: 24, fett: 2, proteinkalla: "veganskt", allergener: [], butik: "Willys", tid: 35, typ: "Vegetarisk", portionspris: 17, inkopspris: 68, sparar: 21, ingredienser: ["Kidneybönor", "Krossade tomater", "Majs", "Paprika"], hemma: ["Ris", "Chili"], beskrivning: "Mustig vegetarisk chili som blir ännu godare dagen efter.", steg: ["Fräs paprika och lök.", "Tillsätt tomater, bönor och majs.", "Låt sjuda i 20 minuter och servera med ris."] },
  { id: "kycklingwok", namn: "Kycklingwok med nudlar", emoji: "🍜", bild: "assets/recipes/kycklingwok.jpg", kcal: 419, protein: 40, kolhydrater: 49, fett: 5, proteinkalla: "kyckling", allergener: ["gluten", "ägg", "soja"], butik: "Coop", tid: 25, typ: "Snabbt & enkelt", portionspris: 21, inkopspris: 84, sparar: 18, ingredienser: ["Kycklingfilé", "Äggnudlar", "Wokgrönsaker", "Soja"], hemma: ["Olja", "Vitlök"], beskrivning: "Snabb wok med mycket grönsaker och smakrik soja.", steg: ["Koka nudlarna.", "Stek kycklingen tills den är genomstekt.", "Woka grönsakerna och blanda allt med soja."] },
  { id: "tomatsoppa", namn: "Krämig tomatsoppa", emoji: "🍅", bild: "assets/recipes/tomatsoppa.jpg", kcal: 126, protein: 3, kolhydrater: 10, fett: 8, proteinkalla: "vegetariskt", allergener: ["laktos"], butik: "Hemköp", tid: 25, typ: "Vegetarisk", portionspris: 14, inkopspris: 56, sparar: 17, ingredienser: ["Krossade tomater", "Grädde", "Lök", "Basilika"], hemma: ["Buljong", "Peppar"], beskrivning: "Len tomatsoppa med basilika och grädde.", steg: ["Fräs löken mjuk.", "Koka med tomater och buljong.", "Mixa soppan och rör ner grädden."] },
  { id: "pannkakor", namn: "Pannkakor med bär", emoji: "🥞", bild: "assets/recipes/pannkakor.jpg", kcal: 402, protein: 18, kolhydrater: 58, fett: 9, proteinkalla: "vegetariskt", allergener: ["gluten", "laktos", "ägg"], butik: "Hemköp", tid: 25, typ: "Familjefavorit", portionspris: 12, inkopspris: 48, sparar: 14, ingredienser: ["Vetemjöl", "Mjölk", "Ägg", "Bär"], hemma: ["Smör", "Socker"], beskrivning: "Klassiska tunna pannkakor för hela familjen.", steg: ["Vispa ihop smetens ingredienser.", "Stek tunna pannkakor i smör.", "Servera med bär."] },
  { id: "kottbullar", namn: "Köttbullar med potatismos och lingon", emoji: "🍖", bild: "assets/recipes/kottbullar.jpg", kcal: 527, protein: 28, kolhydrater: 44, fett: 25, proteinkalla: "notkott", allergener: ["gluten", "laktos", "ägg"], butik: "ICA", tid: 35, typ: "Familjefavorit", portionspris: 22, inkopspris: 88, sparar: 26, ingredienser: ["Köttfärs", "Potatis", "Grädde", "Lingonsylt"], hemma: ["Ströbröd", "Ägg", "Smör"], beskrivning: "Svensk husmanskost med krämigt mos och söta lingon.", steg: ["Rulla köttbullar av färsen och stek dem gyllenbruna.", "Koka och mosa potatisen med grädde.", "Servera köttbullarna med moset och lingonsylten."], tips: "Fräs lite finhackad lök i smöret innan du blandar den i färsen." },
  { id: "vegetarisklasagne", namn: "Vegetarisk lasagne", emoji: "🧀", bild: "assets/recipes/vegetarisklasagne.jpg", kcal: 442, protein: 20, kolhydrater: 62, fett: 11, proteinkalla: "vegetariskt", allergener: ["gluten", "laktos"], butik: "Willys", tid: 45, typ: "Vegetarisk", portionspris: 19, inkopspris: 76, sparar: 20, ingredienser: ["Lasagneplattor", "Krossade tomater", "Riven ost", "Zucchini"], hemma: ["Olja", "Kryddor"], beskrivning: "Ugnsbakad lasagne med saftig zucchini och gyllene osttäcke.", steg: ["Fräs zucchinin och blanda med de krossade tomaterna.", "Varva plattor, tomatsås och ost i en form.", "Grädda tills lasagnen är genomgräddad och ytan gyllenbrun."], tips: "Låt lasagnen vila 5 minuter innan du skär i den så håller den ihop bättre." },
  { id: "scampi", namn: "Scampi pasta med vitlök och citron", emoji: "🍤", bild: "assets/recipes/scampi.jpg", kcal: 307, protein: 22, kolhydrater: 49, fett: 1, proteinkalla: "skaldjur", allergener: ["skaldjur", "gluten"], butik: "Coop", tid: 25, typ: "Fisk", portionspris: 26, inkopspris: 104, sparar: 22, ingredienser: ["Räkor", "Pasta", "Vitlök", "Citron"], hemma: ["Olja", "Smör", "Persilja"], beskrivning: "Snabblagad pasta med räkor, vitlök och en skvätt citron.", steg: ["Koka pastan enligt anvisningen.", "Fräs vitlöken och räkorna hastigt i smör och olja.", "Vänd ner pastan och pressa över citron precis före servering."], tips: "Ta inte räkorna för hett eller för länge, då blir de sega." },
  { id: "kikartscurry", namn: "Kikärtscurry med ris", emoji: "🫘", bild: "assets/recipes/kikartscurry.jpg", kcal: 531, protein: 13, kolhydrater: 67, fett: 21, proteinkalla: "veganskt", allergener: [], butik: "Hemköp", tid: 30, typ: "Vegetarisk", portionspris: 14, inkopspris: 56, sparar: 19, ingredienser: ["Kikärtor", "Kokosmjölk", "Ris", "Curry & grönsaker"], hemma: ["Olja", "Salt"], beskrivning: "Mild och mättande currygryta med kikärtor och kokosmjölk.", steg: ["Fräs curryn kort i olja så aromerna vaknar.", "Tillsätt kikärtor och kokosmjölk och låt sjuda 10 minuter.", "Servera currygrytan med nykokt ris."], tips: "En klick yoghurt på toppen balanserar currystyrkan fint." },
  { id: "flaskfilerotmos", namn: "Baconlindad fläskfilé med rotsaker", emoji: "🥓", bild: "assets/recipes/flaskfilerotmos.jpg", kcal: 316, protein: 34, kolhydrater: 31, fett: 4, proteinkalla: "flask", allergener: [], butik: "ICA", tid: 40, typ: "Familjefavorit", portionspris: 27, inkopspris: 106, sparar: 24, ingredienser: ["Fläskfilé", "Morötter", "Potatis", "Timjan"], hemma: ["Olja", "Salt", "Peppar"], beskrivning: "Mör fläskfilé i ugn med rotsaker och färsk timjan.", steg: ["Sätt ugnen på 200°C och skär rotsakerna i bitar.", "Krydda fläskfilén och lägg den bland rotsakerna i en form.", "Ugnsbaka tills innertemperaturen är 65°C."], tips: "Låt köttet vila 5 minuter innan du skär i det så blir det saftigare." },
  { id: "biffmedlok", namn: "Biff med lökröra och potatismos", emoji: "🥩", bild: "assets/recipes/biffmedlok.jpg", kcal: 445, protein: 38, kolhydrater: 39, fett: 13, proteinkalla: "notkott", allergener: ["laktos"], butik: "Coop", tid: 25, typ: "Snabbt & enkelt", portionspris: 38, inkopspris: 154, sparar: 28, ingredienser: ["Biff", "Potatis", "Lök", "Grädde"], hemma: ["Smör", "Salt", "Peppar"], beskrivning: "Snabbstekt biff med krämig lökröra och potatismos.", steg: ["Koka och mosa potatisen med grädde och smör.", "Fräs löken gyllenbrun och gör en enkel lökröra.", "Stek biffen till önskad innertemperatur och servera med moset."], tips: "Låt biffen vila några minuter innan servering." },
  { id: "vegobolognese", namn: "Vegobolognese med spaghetti", emoji: "🍝", bild: "assets/recipes/vegobolognese.jpg", kcal: 423, protein: 24, kolhydrater: 55, fett: 10, proteinkalla: "veganskt", allergener: ["gluten", "soja"], butik: "Willys", tid: 30, typ: "Vegetarisk", portionspris: 16, inkopspris: 64, sparar: 18, ingredienser: ["Vegofärs", "Pasta", "Krossade tomater", "Lök"], hemma: ["Olja", "Kryddor"], beskrivning: "Klassisk bolognese fast helt växtbaserad.", steg: ["Fräs löken och vegofärsen i olja.", "Tillsätt krossade tomater och låt såsen sjuda 15 minuter.", "Koka pastan och servera med den täta vegosåsen."], tips: "En skvätt balsamvinäger ger såsen extra djup." },
  { id: "kycklingcouscous", namn: "Ugnskyckling med couscous och paprika", emoji: "🍋", bild: "assets/recipes/kycklingcouscous.jpg", kcal: 404, protein: 36, kolhydrater: 51, fett: 3, proteinkalla: "kyckling", allergener: ["gluten"], butik: "ICA", tid: 35, typ: "Familjefavorit", portionspris: 30, inkopspris: 119, sparar: 22, ingredienser: ["Kycklingfilé", "Matvete", "Paprika", "Citron"], hemma: ["Olja", "Salt", "Peppar"], beskrivning: "Ugnsbakad kyckling med citron, paprika och fluffigt matvete.", steg: ["Ugnsbaka kycklingfilén med paprika och citronskivor.", "Koka matvetet enligt anvisningen.", "Servera kycklingen på matvetet och pressa över lite citron."], tips: "Marinera kycklingen en stund i citron och olja för mer smak." },
  { id: "rotfruktsgratang", namn: "Rotfruktsgratäng med rökt falukorv", emoji: "🥔", bild: "assets/recipes/rotfruktsgratang.jpg", kcal: 538, protein: 23, kolhydrater: 48, fett: 26, proteinkalla: "flask", allergener: ["laktos"], butik: "ICA", tid: 50, typ: "Familjefavorit", portionspris: 13, inkopspris: 52, sparar: 16, ingredienser: ["Falukorv", "Potatis", "Morötter", "Riven ost"], hemma: ["Smör", "Salt", "Peppar", "Muskot"], beskrivning: "Djup, krämig gratäng där söta morötter och salt korv möts under ett gyllene osttäcke — riktig husmanskost fast lite finare.", steg: ["Skiva potatis och morötter tunt på mandolin eller osthyvel för jämn gräddning.", "Varva rotfrukterna med tunna skivor falukorv i en smord form.", "Häll över en lätt uppkokad grädde med muskot, salt och peppar.", "Toppa med riven ost och grädda mitt i ugnen tills ytan är gyllenbrun och potatisen mör.", "Låt gratängen vila 5 minuter innan servering så såsen binder."], tips: "Ett tunt lager senap mellan lagren ger en syrlig kontrast till den feta osten." },
  { id: "butterchicken", namn: "Butter chicken med jasminris", emoji: "🍛", bild: "assets/recipes/butterchicken.jpg", kcal: 253, protein: 32, kolhydrater: 9, fett: 9, proteinkalla: "kyckling", allergener: ["laktos"], butik: "Willys", tid: 40, typ: "Familjefavorit", portionspris: 31, inkopspris: 123, sparar: 27, ingredienser: ["Kycklingfilé", "Krossade tomater", "Grädde", "Curry & grönsaker"], hemma: ["Smör", "Vitlök", "Ingefära", "Ris"], beskrivning: "Krämig, lent kryddad tomatsås med mör kyckling — restaurangens favorit, gjord hemma på under en timme.", steg: ["Marinera kycklingbitarna i yoghurt och kryddor minst 20 minuter om tid finns.", "Bryn kycklingen snabbt i smör tills den fått färg, lyft ur och lägg åt sidan.", "Fräs vitlök, ingefära och curryblandningen i samma panna tills doften vaknar.", "Tillsätt krossade tomater och låt såsen sjuda ihop och tjockna.", "Rör ner grädden och kycklingen, låt det hela sjuda klart och servera över nykokt ris."], tips: "En klick smör i slutet ger såsen den där extra silkiga lyskraften." },
  { id: "fiskgratang", namn: "Fiskgratäng med räkor och dill", emoji: "🍤", bild: "assets/recipes/fiskgratang.jpg", kcal: 220, protein: 33, kolhydrater: 2, fett: 8, proteinkalla: "fisk", allergener: ["fisk", "skaldjur", "laktos"], butik: "Coop", tid: 45, typ: "Fisk", portionspris: 50, inkopspris: 199, sparar: 30, ingredienser: ["Fryst torsk", "Räkor", "Dill", "Grädde"], hemma: ["Smör", "Citron", "Salt", "Peppar"], beskrivning: "En elegant men enkel gratäng där torsk och räkor bakas i en len dillsås — fint nog för helgen.", steg: ["Tina fisken och räkorna försiktigt och klappa torra.", "Lägg fisken i en smord ugnsform och toppa med räkorna.", "Vispa ihop grädde, hackad dill, citronskal och kryddor till en lös sås.", "Häll såsen över fisken så den nästan täcks.", "Grädda tills fisken är genomstekt och ytan fått lite färg, garnera med extra dill."], tips: "Pressa i lite citronsaft precis innan servering för att lyfta smakerna." },
  { id: "tofuwok", namn: "Krispig tofuwok med sesam och soja", emoji: "🥢", bild: "assets/recipes/tofuwok.jpg", kcal: 345, protein: 13, kolhydrater: 56, fett: 6, proteinkalla: "veganskt", allergener: ["soja"], butik: "Hemköp", tid: 25, typ: "Vegetarisk", portionspris: 26, inkopspris: 103, sparar: 20, ingredienser: ["Tofu", "Wokgrönsaker", "Soja", "Ris"], hemma: ["Olja", "Vitlök", "Sesamfrön"], beskrivning: "Knaprig tofu och färgstarka grönsaker i en blank sojaglaze — snabbt, fräscht och mättande.", steg: ["Pressa tofun lätt och tärna den i jämna bitar.", "Stek tofun i het olja på hög värme tills alla sidor är gyllenbruna och knapriga.", "Lyft ur tofun och woka grönsakerna hastigt i samma panna så de behåller tuggmotstånd.", "Blanda ner soja, lite vatten och pressad vitlök och låt puttra en minut.", "Vänd tillbaka tofun i woken, strö över sesamfrön och servera direkt på riset."], tips: "Woka på högsta möjliga värme och rör inte för mycket — då blir grönsakerna krispiga istället för mjäkiga." },
  { id: "ugnstorsk", namn: "Ugnsbakad torsk med sparris och citronsmör", emoji: "🐟", bild: "assets/recipes/ugnstorsk.jpg", kcal: 264, protein: 32, kolhydrater: 28, fett: 1, proteinkalla: "fisk", allergener: ["fisk"], butik: "ICA", tid: 35, typ: "Fisk", portionspris: 51, inkopspris: 204, sparar: 26, ingredienser: ["Fryst torsk", "Citron", "Sparris", "Potatis"], hemma: ["Smör", "Salt", "Peppar"], beskrivning: "Saftig torsk och knaprig sparris bakas ihop under smält citronsmör — en enkel rätt som känns lite finare.", steg: ["Koka potatisen mjuk och håll den varm.", "Bryt av de träiga ändarna på sparrisen och lägg den i en ugnsform.", "Lägg torsken ovanpå sparrisen, salta och peppra generöst.", "Smält smör med citronsaft och citronskal och ringla över fisken.", "Ugnsbaka tills torsken flagnar lätt och sparrisen är mör men har tuggmotstånd."], tips: "Välj sparris i samma tjocklek så gräddas den jämnt." },
  { id: "flaskkarre", namn: "Fläskkarré med äppelmos och rödkål", emoji: "🍎", bild: "assets/recipes/flaskkarre.jpg", kcal: 419, protein: 34, kolhydrater: 57, fett: 4, proteinkalla: "flask", allergener: [], butik: "Coop", tid: 45, typ: "Familjefavorit", portionspris: 26, inkopspris: 105, sparar: 24, ingredienser: ["Fläskfilé", "Äppelmos", "Rödkål", "Potatis"], hemma: ["Smör", "Salt", "Peppar", "Timjan"], beskrivning: "Klassisk höstmiddag — mör fläskfilé med syrlig äppelmos och sötsyrlig rödkål.", steg: ["Krydda fläskfilén med salt, peppar och timjan.", "Bryn den runt om i het panna tills ytan fått fin färg.", "Eftersteg i ugn eller på svag värme tills innertemperaturen når 65°C.", "Värm rödkålen och äppelmoset separat medan köttet vilar.", "Skär fläskfilén i skivor och servera med rödkål, äppelmos och kokt potatis."], tips: "Låt köttet vila minst 5 minuter under folie innan du skär i det, då rinner mindre saft ut." },
  { id: "fetapasta", namn: "Ugnsbakad fetaost-pasta", emoji: "🍅", bild: "assets/recipes/fetapasta.jpg", kcal: 439, protein: 19, kolhydrater: 61, fett: 12, proteinkalla: "vegetariskt", allergener: ["gluten", "laktos"], butik: "Willys", tid: 35, typ: "Vegetarisk", portionspris: 17, inkopspris: 67, sparar: 19, ingredienser: ["Pasta", "Krossade tomater", "Vitlök", "Feta"], hemma: ["Olivolja", "Chiliflakes", "Basilika"], beskrivning: "Den virala favoriten — en hel fetaost bakas med tomater till en krämig, salt sås som smälter samman med pastan.", steg: ["Lägg fetaosten i mitten av en ugnsform och omge den med krossade tomater och hela vitlöksklyftor.", "Ringla över rikligt med olivolja och strö på chiliflakes.", "Ugnsbaka tills tomaterna puttrar och osten fått lite färg på ytan.", "Koka pastan al dente under tiden.", "Mosa ihop fetan och tomaterna till en sås, blanda med pastan och toppa med färsk basilika."], tips: "Spara lite pastavatten — det gör såsen silkigare om den blir för tjock." },
  { id: "kalvschnitzel", namn: "Kalvschnitzel med citron och kapris", emoji: "🍽️", bild: "assets/recipes/kalvschnitzel.jpg", kcal: 302, protein: 34, kolhydrater: 27, fett: 5, proteinkalla: "notkott", allergener: ["gluten", "laktos", "ägg"], butik: "Hemköp", tid: 30, typ: "Snabbt & enkelt", portionspris: 60, inkopspris: 239, sparar: 32, ingredienser: ["Kalvschnitzel", "Potatis", "Citron", "Kapris"], hemma: ["Smör", "Vetemjöl", "Ägg", "Ströbröd"], beskrivning: "Krispigt panerad kalvschnitzel med syrlig kapris och citron — en klassisk restaurangrätt som är enklare hemma än man tror.", steg: ["Bulta ut kalvschnitzlarna tunt mellan plastfolie.", "Panera dem i tur och ordning i mjöl, uppvispat ägg och ströbröd.", "Stek i rikligt med smör på medelhög värme tills paneringen är gyllenbrun och krispig på båda sidor.", "Koka potatisen mjuk under tiden.", "Servera schnitzeln med citronklyfta, kapris och smörstekt potatis."], tips: "Stek inte för många schnitzlar samtidigt — då sjunker temperaturen i pannan och paneringen blir seg istället för krispig." },
  { id: "kycklingmatvete", namn: "Kryddig kycklingbowl med matvete", emoji: "🍗", bild: "assets/recipes/kycklingmatvete.jpg", kcal: 432, protein: 33, kolhydrater: 51, fett: 7, proteinkalla: "kyckling", allergener: ["gluten", "laktos"], butik: "ICA", tid: 30, typ: "Familjefavorit", portionspris: 33, inkopspris: 130, sparar: 29, ingredienser: ["Kycklinglårfilé", "Matvete", "Paprika", "Yoghurt"], hemma: ["Olja", "Spiskummin", "Paprikapulver"], beskrivning: "Kryddstekt kyckling på fluffigt matvete med syrlig yoghurtsås — en enkel bowl med mycket smak.", steg: ["Krydda kycklingen med spiskummin och paprikapulver och stek den gyllenbrun och genomstekt.", "Koka matvetet enligt förpackningen.", "Skär paprikan i strimlor och rör ihop yoghurten med lite salt.", "Bygg bowls med matvete, kyckling, paprika och en klick yoghurtsås."], tips: "Marinera kycklingen en stund i kryddorna och lite olja för djupare smak." },
  { id: "citronkyckling", namn: "Citronkyckling med rostad potatis", emoji: "🍋", bild: "assets/recipes/citronkyckling.jpg", kcal: 342, protein: 33, kolhydrater: 35, fett: 6, proteinkalla: "kyckling", allergener: [], butik: "Willys", tid: 40, typ: "Familjefavorit", portionspris: 29, inkopspris: 115, sparar: 25, ingredienser: ["Kycklinglårfilé", "Potatis", "Timjan", "Citron"], hemma: ["Olja", "Salt", "Peppar"], beskrivning: "Ugnsbakad kyckling med citron och timjan tillsammans med krispig rostad potatis — en enkel söndagsmiddag.", steg: ["Sätt ugnen på 200°C och dela potatisen i klyftor.", "Blanda potatisen med olja, salt och timjan i en ugnsform.", "Lägg kycklinglårfiléerna ovanpå, pressa över citron och baka tills kycklingen är genomstekt och potatisen gyllenbrun."], tips: "Lägg citronskalen kvar i formen under gräddningen för extra arom." },
  { id: "biffmatvetesallad", namn: "Biffsallad med matvete och vitlök", emoji: "🥩", bild: "assets/recipes/biffmatvetesallad.jpg", kcal: 420, protein: 34, kolhydrater: 50, fett: 6, proteinkalla: "notkott", allergener: ["gluten"], butik: "Coop", tid: 25, typ: "Snabbt & enkelt", portionspris: 41, inkopspris: 165, sparar: 36, ingredienser: ["Biff", "Matvete", "Paprika", "Vitlök"], hemma: ["Olja", "Salt", "Peppar"], beskrivning: "Snabbstekt biff i skivor på en fräsch matvetesallad med paprika och vitlöksdressing.", steg: ["Koka matvetet och låt det svalna något.", "Stek biffen till önskad innertemperatur, låt vila och skär i tunna skivor.", "Fräs pressad vitlök hastigt i olja och blanda med matvete och strimlad paprika.", "Toppa saladen med biffskivorna."], tips: "Vila alltid köttet några minuter innan det skärs, då rinner mindre saft ut." },
  { id: "biffwok", namn: "Biffwok med wokgrönsaker", emoji: "🥢", bild: "assets/recipes/biffwok.jpg", kcal: 428, protein: 34, kolhydrater: 55, fett: 6, proteinkalla: "notkott", allergener: ["soja"], butik: "ICA", tid: 20, typ: "Snabbt & enkelt", portionspris: 53, inkopspris: 210, sparar: 46, ingredienser: ["Biff", "Ris", "Wokgrönsaker", "Soja"], hemma: ["Olja", "Vitlök", "Ingefära"], beskrivning: "Snabbwokad biff i strimlor med krispiga grönsaker och blank sojasås — klart på under 20 minuter.", steg: ["Koka riset enligt anvisningen.", "Strimla biffen tunt och wokа den hastigt på hög värme.", "Lyft ur köttet och woka grönsakerna kort så de behåller tuggmotstånd.", "Blanda tillbaka biffen, häll över soja och servera med riset."], tips: "Skär köttet mot fibrerna så blir det mörare." },
  { id: "flaskcurrygryta", namn: "Fläskcurrygryta med kokos", emoji: "🍛", bild: "assets/recipes/flaskcurrygryta.jpg", kcal: 543, protein: 32, kolhydrater: 52, fett: 22, proteinkalla: "flask", allergener: [], butik: "Willys", tid: 35, typ: "Familjefavorit", portionspris: 36, inkopspris: 142, sparar: 31, ingredienser: ["Fläskfilé", "Ris", "Curry & grönsaker", "Kokosmjölk"], hemma: ["Olja", "Salt"], beskrivning: "Mild currygryta med mört fläsk och len kokosmjölk — mättande vardagsmat som värmer.", steg: ["Tärna fläskfilén och bryn den runt om i het olja.", "Rör ner curryblandningen och fräs kort.", "Häll i kokosmjölken och låt grytan sjuda tills köttet är mört.", "Servera med nykokt ris."], tips: "Låt grytan sjuda på svag värme en stund extra — smakerna blir bara bättre." },
  { id: "flasktomatpasta", namn: "Fläskfilé i tomatsås med pasta", emoji: "🍝", bild: "assets/recipes/flasktomatpasta.jpg", kcal: 381, protein: 34, kolhydrater: 48, fett: 4, proteinkalla: "flask", allergener: ["gluten"], butik: "Coop", tid: 30, typ: "Familjefavorit", portionspris: 34, inkopspris: 134, sparar: 29, ingredienser: ["Fläskfilé", "Pasta", "Krossade tomater", "Basilika"], hemma: ["Olja", "Vitlök", "Salt", "Peppar"], beskrivning: "Mör fläskfilé i en enkel tomatsås med färsk basilika, serverad över pasta.", steg: ["Tärna fläskfilén och bryn den i olja tillsammans med lite vitlök.", "Häll i de krossade tomaterna och låt såsen sjuda tills köttet är genomstekt.", "Koka pastan enligt anvisningen.", "Rör ner färsk basilika i såsen och servera över pastan."], tips: "En nypa socker balanserar tomaternas syra." },
  { id: "kalvschnitzelmatvete", namn: "Kalvschnitzel med matvetesallad", emoji: "🍽️", bild: "assets/recipes/kalvschnitzelmatvete.jpg", kcal: 399, protein: 33, kolhydrater: 50, fett: 4, proteinkalla: "notkott", allergener: ["gluten", "laktos", "ägg"], butik: "Hemköp", tid: 30, typ: "Snabbt & enkelt", portionspris: 36, inkopspris: 142, sparar: 31, ingredienser: ["Kalvschnitzel", "Matvete", "Paprika", "Citron"], hemma: ["Smör", "Vetemjöl", "Ägg", "Ströbröd"], beskrivning: "Krispig kalvschnitzel serverad med en fräsch matvetesallad istället för potatis, för en lite lättare middag.", steg: ["Panera schnitzlarna i mjöl, ägg och ströbröd.", "Stek dem gyllenbruna och krispiga i smör.", "Koka matvetet och blanda med strimlad paprika och en skvätt citron.", "Servera schnitzeln på saladen med extra citronklyfta."], tips: "Salta matvetesaladen precis före servering så den inte blir vattnig." },
  { id: "teriyakilax", namn: "Teriyakilax med wokgrönsaker och ris", emoji: "🐟", bild: "assets/recipes/teriyakilax.jpg", kcal: 537, protein: 32, kolhydrater: 56, fett: 19, proteinkalla: "fisk", allergener: ["fisk", "soja"], butik: "ICA", tid: 25, typ: "Fisk", portionspris: 45, inkopspris: 180, sparar: 40, ingredienser: ["Laxfilé", "Ris", "Wokgrönsaker", "Soja"], hemma: ["Olja", "Honung", "Ingefära"], beskrivning: "Blank, sötsalt lax stekt i sojaglaze med krispiga wokgrönsaker och ris.", steg: ["Koka riset enligt anvisningen.", "Stek laxbitarna i het olja tills de nästan är genomstekta.", "Häll i soja och lite honung och låt det bubbla till en blank glaze.", "Woka grönsakerna hastigt och servera allt tillsammans med riset."], tips: "Vänd laxen försiktigt så bitarna inte faller sönder i glazen." },
  { id: "laxsallad", namn: "Laxsallad med matvete och dill", emoji: "🥗", bild: "assets/recipes/laxsallad.jpg", kcal: 523, protein: 32, kolhydrater: 49, fett: 19, proteinkalla: "fisk", allergener: ["fisk", "gluten"], butik: "ICA", tid: 25, typ: "Fisk", portionspris: 34, inkopspris: 135, sparar: 30, ingredienser: ["Laxfilé", "Matvete", "Citron", "Dill"], hemma: ["Olja", "Salt", "Peppar"], beskrivning: "Lätt sommarsallad med stekt lax, fluffigt matvete, citron och rikligt med färsk dill.", steg: ["Koka matvetet och låt det svalna.", "Stek laxbitarna försiktigt i olja tills de precis är genomstekta.", "Blanda matvetet med olja, citronsaft och hackad dill.", "Toppa saladen med de varma laxbitarna."], tips: "Flingsalt och extra citron på toppen lyfter smaken precis innan servering." },
  { id: "torskitomatsas", namn: "Torsk i tomatsås", emoji: "🐟", bild: "assets/recipes/torskitomatsas.jpg", kcal: 251, protein: 27, kolhydrater: 30, fett: 1, proteinkalla: "fisk", allergener: ["fisk"], butik: "Willys", tid: 30, typ: "Fisk", portionspris: 27, inkopspris: 107, sparar: 24, ingredienser: ["Fryst torsk", "Potatis", "Krossade tomater", "Vitlök"], hemma: ["Olja", "Salt", "Peppar", "Basilika"], beskrivning: "Saftig torsk som puttrar färdig i en enkel, smakrik tomatsås med vitlök.", steg: ["Koka potatisen mjuk.", "Fräs pressad vitlök kort i olja och häll i de krossade tomaterna.", "Låt såsen sjuda några minuter, lägg sedan i torskbitarna och låt dem sjuda tills de flagnar lätt.", "Servera med den kokta potatisen."], tips: "Rör inte för mycket i grytan när fisken puttrar, då håller bitarna ihop bättre." },
  { id: "rakcurry", namn: "Räkcurry med kokos och ris", emoji: "🍤", bild: "assets/recipes/rakcurry.jpg", kcal: 467, protein: 19, kolhydrater: 52, fett: 19, proteinkalla: "skaldjur", allergener: ["skaldjur"], butik: "Coop", tid: 20, typ: "Fisk", portionspris: 28, inkopspris: 112, sparar: 25, ingredienser: ["Räkor", "Ris", "Curry & grönsaker", "Kokosmjölk"], hemma: ["Olja", "Salt"], beskrivning: "Snabb och len currygryta med räkor och kokosmjölk — klar på under en halvtimme.", steg: ["Koka riset enligt anvisningen.", "Fräs curryblandningen kort i olja.", "Häll i kokosmjölken och låt puttra några minuter.", "Rör ner räkorna och värm dem varsamt precis innan servering."], tips: "Låt inte räkorna koka för länge, då blir de sega." },
  { id: "raksallad", namn: "Räksallad med matvete", emoji: "🍤", bild: "assets/recipes/raksallad.jpg", kcal: 318, protein: 20, kolhydrater: 48, fett: 2, proteinkalla: "skaldjur", allergener: ["skaldjur", "gluten"], butik: "Coop", tid: 20, typ: "Fisk", portionspris: 24, inkopspris: 95, sparar: 21, ingredienser: ["Räkor", "Matvete", "Citron", "Dill"], hemma: ["Olja", "Salt", "Peppar"], beskrivning: "Fräsch sallad med skalade räkor, matvete, citron och rikligt med dill — perfekt till varma dagar.", steg: ["Koka matvetet och låt det svalna helt.", "Blanda matvetet med olja, citronsaft och hackad dill.", "Vänd ner räkorna försiktigt precis innan servering så de behåller sin fräschör.", "Smaka av med salt och peppar."], tips: "Servera saladen kall, gärna direkt från kylen på en varm dag." },
  { id: "kikartssallad", namn: "Kikärtssallad med matvete", emoji: "🫘", bild: "assets/recipes/kikartssallad.jpg", kcal: 387, protein: 14, kolhydrater: 64, fett: 4, proteinkalla: "veganskt", allergener: ["gluten"], butik: "Hemköp", tid: 20, typ: "Vegetarisk", portionspris: 14, inkopspris: 56, sparar: 12, ingredienser: ["Kikärtor", "Matvete", "Paprika", "Citron"], hemma: ["Olja", "Salt", "Peppar", "Spiskummin"], beskrivning: "Mättande vegansk sallad med kikärtor, matvete och en fräsch citrondressing.", steg: ["Koka matvetet enligt förpackningen.", "Skölj av kikärtorna och blanda med matvetet och strimlad paprika.", "Rör ihop en dressing av olja, citronsaft, spiskummin, salt och peppar.", "Vänd ner dressingen i saladen precis innan servering."], tips: "Saladen håller sig fin i kylen ett par dagar — perfekt att göra extra av." },
  { id: "bonbowlmatvete", namn: "Bönbowl med matvete och salsa", emoji: "🌶️", bild: "assets/recipes/bonbowlmatvete.jpg", kcal: 377, protein: 16, kolhydrater: 63, fett: 2, proteinkalla: "veganskt", allergener: ["gluten"], butik: "ICA", tid: 20, typ: "Vegetarisk", portionspris: 18, inkopspris: 72, sparar: 16, ingredienser: ["Kidneybönor", "Matvete", "Paprika", "Salsa"], hemma: ["Olja", "Spiskummin", "Salt"], beskrivning: "Enkel, mexikoinspirerad bowl med kryddiga bönor, matvete och salsa.", steg: ["Koka matvetet enligt förpackningen.", "Värm kidneybönorna med spiskummin i en het panna.", "Skär paprikan i tärningar.", "Bygg bowls med matvete, bönor, paprika och salsa på toppen."], tips: "Toppa gärna med avokado eller lite riven ost om du har hemma." },
  { id: "svartbonsbowl", namn: "Svartbönsbowl med matvete", emoji: "🌽", bild: "assets/recipes/svartbonsbowl.jpg", kcal: 395, protein: 16, kolhydrater: 65, fett: 3, proteinkalla: "veganskt", allergener: ["gluten"], butik: "ICA", tid: 20, typ: "Vegetarisk", portionspris: 19, inkopspris: 75, sparar: 16, ingredienser: ["Svarta bönor", "Matvete", "Salsa", "Majs"], hemma: ["Olja", "Spiskummin", "Salt"], beskrivning: "Färgstark bowl med svarta bönor, sötaktig majs och salsa på en bädd av matvete.", steg: ["Koka matvetet enligt förpackningen.", "Värm de svarta bönorna med spiskummin.", "Blanda majsen med salsan.", "Bygg bowls med matvete, bönor och majssalsan."], tips: "Pressa över lite lime om du har hemma för extra fräschör." },
  { id: "tofucurry", namn: "Tofucurry med kokos och ris", emoji: "🍛", bild: "assets/recipes/tofucurry.jpg", kcal: 479, protein: 13, kolhydrater: 54, fett: 23, proteinkalla: "veganskt", allergener: ["soja"], butik: "Hemköp", tid: 25, typ: "Vegetarisk", portionspris: 23, inkopspris: 92, sparar: 20, ingredienser: ["Tofu", "Ris", "Curry & grönsaker", "Kokosmjölk"], hemma: ["Olja", "Salt"], beskrivning: "Len och mild currygryta med krispigt stekt tofu och kokosmjölk.", steg: ["Koka riset enligt anvisningen.", "Tärna tofun och stek den gyllenbrun i het olja.", "Rör ner curryblandningen och häll i kokosmjölken.", "Låt sjuda några minuter och servera med riset."], tips: "Pressa tofun lätt innan den steks, då blir den krispigare." },
  { id: "teriyakitofu", namn: "Teriyakitofu med matvetesallad", emoji: "🥢", bild: "assets/recipes/teriyakitofu.jpg", kcal: 327, protein: 14, kolhydrater: 49, fett: 5, proteinkalla: "veganskt", allergener: ["gluten", "soja"], butik: "Hemköp", tid: 25, typ: "Vegetarisk", portionspris: 24, inkopspris: 95, sparar: 21, ingredienser: ["Tofu", "Matvete", "Paprika", "Soja"], hemma: ["Olja", "Honung", "Ingefära"], beskrivning: "Krispig tofu i blank sojaglaze på en fräsch matvetesallad med paprika.", steg: ["Koka matvetet och blanda med strimlad paprika och lite olja.", "Tärna och stek tofun knaprig i het olja.", "Häll i soja och en skvätt honung och låt det bli en blank glaze runt tofun.", "Servera tofun på matvetesaladen."], tips: "Låt tofun steka ostört några minuter i taget så den hinner bli knaprig." },
  { id: "halloumipasta", namn: "Halloumipasta med tomat och basilika", emoji: "🧀", bild: "assets/recipes/halloumipasta.jpg", kcal: 411, protein: 21, kolhydrater: 49, fett: 13, proteinkalla: "vegetariskt", allergener: ["gluten", "laktos"], butik: "Willys", tid: 25, typ: "Vegetarisk", portionspris: 25, inkopspris: 99, sparar: 22, ingredienser: ["Halloumi", "Pasta", "Krossade tomater", "Basilika"], hemma: ["Olja", "Vitlök", "Salt", "Peppar"], beskrivning: "Krispigt stekt halloumi i en enkel tomatsås med basilika, över pasta.", steg: ["Koka pastan enligt anvisningen.", "Skär halloumin i kuber och stek den gyllenbrun i olja.", "Fräs vitlök kort och häll i de krossade tomaterna, låt sjuda några minuter.", "Blanda pastan med såsen, toppa med halloumin och färsk basilika."], tips: "Stek halloumin sist så den hinner vara varm och krispig vid servering." },
  { id: "halloumicurry", namn: "Halloumicurry med ris", emoji: "🍛", bild: "assets/recipes/halloumicurry.jpg", kcal: 414, protein: 18, kolhydrater: 55, fett: 13, proteinkalla: "vegetariskt", allergener: ["laktos"], butik: "Willys", tid: 25, typ: "Vegetarisk", portionspris: 25, inkopspris: 100, sparar: 22, ingredienser: ["Halloumi", "Ris", "Paprika", "Curry & grönsaker"], hemma: ["Olja", "Salt"], beskrivning: "Mild currygryta med paprika och tärnad halloumi som håller formen fint i grytan.", steg: ["Koka riset enligt anvisningen.", "Fräs paprikan och curryblandningen i olja.", "Häll på lite vatten och låt puttra några minuter.", "Vänd ner tärnad halloumi precis innan servering och låt den bli varm."], tips: "Halloumi smälter inte som andra ostar, så den håller formen fint även i en gryta." },
  { id: "fetagryta", namn: "Fetagryta med kikärtor", emoji: "🍅", bild: "assets/recipes/fetagryta.jpg", kcal: 281, protein: 16, kolhydrater: 20, fett: 14, proteinkalla: "vegetariskt", allergener: ["laktos"], butik: "Hemköp", tid: 25, typ: "Vegetarisk", portionspris: 22, inkopspris: 86, sparar: 19, ingredienser: ["Feta", "Krossade tomater", "Kikärtor", "Basilika"], hemma: ["Olja", "Vitlök", "Salt", "Peppar"], beskrivning: "Mustig tomatgryta med kikärtor där fetaosten smälter ner till en krämig, salt sås.", steg: ["Fräs vitlök i olja och häll i de krossade tomaterna och kikärtorna.", "Låt grytan sjuda tills den tjocknat något.", "Bryt fetaosten i bitar och rör ner dem i grytan så de smälter delvis.", "Toppa med färsk basilika och servera."], tips: "Servera med bröd om du har hemma för att svepa upp den krämiga såsen." },
  { id: "vegofarsgryta", namn: "Vegofärsgryta med ris", emoji: "🍚", bild: "assets/recipes/vegofarsgryta.jpg", kcal: 418, protein: 21, kolhydrater: 59, fett: 9, proteinkalla: "veganskt", allergener: ["soja"], butik: "Willys", tid: 25, typ: "Vegetarisk", portionspris: 23, inkopspris: 92, sparar: 20, ingredienser: ["Vegofärs", "Ris", "Krossade tomater", "Paprika"], hemma: ["Olja", "Kryddor", "Salt"], beskrivning: "Enkel, mättande gryta med vegofärs, tomat och paprika över ris.", steg: ["Koka riset enligt anvisningen.", "Fräs vegofärsen och den strimlade paprikan i olja.", "Häll i de krossade tomaterna och låt grytan sjuda 10 minuter.", "Servera grytan över riset."], tips: "Låt grytan sjuda ett tag extra på svag värme för djupare smak." },
  { id: "korvgratang", namn: "Korvgratäng med pasta", emoji: "🌭", bild: "assets/recipes/korvgratang.jpg", kcal: 589, protein: 27, kolhydrater: 57, fett: 27, proteinkalla: "flask", allergener: ["gluten", "laktos"], butik: "ICA", tid: 35, typ: "Familjefavorit", portionspris: 24, inkopspris: 94, sparar: 21, ingredienser: ["Falukorv", "Pasta", "Krossade tomater", "Riven ost"], hemma: ["Olja", "Kryddor", "Salt"], beskrivning: "Enkel vardagsgratäng med skivad falukorv, pasta och tomatsås under ett osttäcke.", steg: ["Koka pastan två minuter kortare än anvisningen.", "Skiva falukorven och blanda med pastan och de krossade tomaterna i en ugnsform.", "Toppa med riven ost och gratinera i ugnen tills ytan är gyllenbrun."], tips: "Krydda tomatsåsen med lite oregano för mer smak." },
  { id: "kottfarssas", namn: "Köttfärssås med pasta", emoji: "🍝", bild: "assets/recipes/kottfarssas.jpg", kcal: 498, protein: 32, kolhydrater: 48, fett: 19, proteinkalla: "notkott", allergener: ["gluten"], butik: "ICA", tid: 30, typ: "Familjefavorit", portionspris: 29, inkopspris: 114, sparar: 25, ingredienser: ["Köttfärs", "Pasta", "Krossade tomater", "Basilika"], hemma: ["Olja", "Lök", "Vitlök", "Salt", "Peppar"], beskrivning: "Klassisk köttfärssås med tomat och basilika — en trygg favorit för hela familjen.", steg: ["Fräs finhackad lök och vitlök i olja.", "Bryn köttfärsen väl så den får fin färg.", "Häll i de krossade tomaterna och låt såsen sjuda minst 15 minuter.", "Koka pastan och servera med den rykande varma såsen och färsk basilika."], tips: "Ju längre såsen får sjuda desto djupare blir smaken." },
  { id: "currykottfarsgryta", namn: "Currykryddad köttfärsgryta", emoji: "🍛", bild: "assets/recipes/currykottfarsgryta.jpg", kcal: 501, protein: 29, kolhydrater: 54, fett: 18, proteinkalla: "notkott", allergener: [], butik: "ICA", tid: 30, typ: "Familjefavorit", portionspris: 29, inkopspris: 115, sparar: 25, ingredienser: ["Köttfärs", "Ris", "Paprika", "Curry & grönsaker"], hemma: ["Olja", "Lök", "Salt"], beskrivning: "Snabb köttfärsgryta med curry och paprika — mustig vardagsmat till hela familjen.", steg: ["Fräs lök i olja och bryn köttfärsen.", "Rör ner curryblandningen och den strimlade paprikan.", "Häll på lite vatten och låt grytan sjuda 10 minuter.", "Servera med nykokt ris."], tips: "En klick crème fraiche på toppen gör grytan lite mildare om det behövs." },
  { id: "tandoorikyckling", namn: "Tandoorikyckling med ris", emoji: "🍗", bild: "assets/recipes/tandoorikyckling.jpg", kcal: 399, protein: 36, kolhydrater: 55, fett: 4, proteinkalla: "kyckling", allergener: ["laktos"], butik: "ICA", tid: 35, typ: "Familjefavorit", portionspris: 38, inkopspris: 150, sparar: 33, ingredienser: ["Kycklingfilé", "Ris", "Curry & grönsaker", "Yoghurt"], hemma: ["Olja", "Vitlök", "Salt"], beskrivning: "Yoghurtmarinerad kyckling med kryddig currysmak, stekt möra och saftiga.", steg: ["Blanda yoghurt, curryblandning och pressad vitlök till en marinad.", "Vänd kycklingbitarna i marinaden och låt stå en stund om tid finns.", "Stek kycklingen i het panna tills den är genomstekt och fått fin färg.", "Servera med nykokt ris."], tips: "Ju längre kycklingen får marinera, desto mörare och smakrikare blir den." },
  { id: "citronflaskfile", namn: "Citronmarinerad fläskfilé med matvete", emoji: "🍋", bild: "assets/recipes/citronflaskfile.jpg", kcal: 392, protein: 32, kolhydrater: 48, fett: 4, proteinkalla: "flask", allergener: ["gluten"], butik: "Coop", tid: 30, typ: "Familjefavorit", portionspris: 31, inkopspris: 125, sparar: 28, ingredienser: ["Fläskfilé", "Matvete", "Citron", "Timjan"], hemma: ["Olja", "Salt", "Peppar"], beskrivning: "Mör fläskfilé marinerad i citron och timjan, serverad med fluffigt matvete.", steg: ["Marinera fläskfilén i olja, citronsaft och timjan en stund om tid finns.", "Stek filén i het panna till önskad innertemperatur och låt vila.", "Koka matvetet enligt förpackningen.", "Skär köttet i skivor och servera på matvetet med lite av stekskyn."], tips: "Spara citronskal till marinaden — det ger extra arom." },
  { id: "biffgraddtimjan", namn: "Helstekt biff med gräddsås och timjanpotatis", emoji: "🥩", bild: "assets/recipes/biffgraddtimjan.jpg", kcal: 394, protein: 32, kolhydrater: 35, fett: 12, proteinkalla: "notkott", allergener: ["laktos"], butik: "Coop", tid: 35, typ: "Familjefavorit", portionspris: 44, inkopspris: 174, sparar: 38, ingredienser: ["Biff", "Potatis", "Grädde", "Timjan"], hemma: ["Smör", "Salt", "Peppar"], beskrivning: "Saftig helstekt biff med en enkel gräddsås och rostad timjanpotatis — helgmiddag i vardagstempo.", steg: ["Sätt ugnen på 200°C och rosta potatisklyftorna med olja, salt och timjan.", "Bryn biffen runt om i het panna och stek klart till önskad innertemperatur, låt sedan vila.", "Häll grädden i samma panna och koka ihop till en enkel sås, smaka av med salt och peppar.", "Skiva biffen och servera med såsen och den rostade potatisen."], tips: "Använd samma panna till såsen — stekskyn ger mycket smak." },
  { id: "zucchinipastafeta", namn: "Zucchinipasta med feta", emoji: "🥒", bild: "assets/recipes/zucchinipastafeta.jpg", kcal: 399, protein: 17, kolhydrater: 53, fett: 12, proteinkalla: "vegetariskt", allergener: ["gluten", "laktos"], butik: "Willys", tid: 25, typ: "Vegetarisk", portionspris: 19, inkopspris: 77, sparar: 17, ingredienser: ["Zucchini", "Pasta", "Krossade tomater", "Feta"], hemma: ["Olja", "Vitlök", "Salt", "Peppar"], beskrivning: "Lätt sommarpasta med stekt zucchini, tomatsås och smulad fetaost.", steg: ["Koka pastan enligt anvisningen.", "Skiva zucchinin och stek den gyllenbrun i olja tillsammans med lite vitlök.", "Häll i de krossade tomaterna och låt sjuda några minuter.", "Blanda med pastan och toppa med smulad feta."], tips: "Stek zucchinin på hög värme så den får färg utan att bli blöt." },
  { id: "sparrispastacitron", namn: "Sparrispasta med citron och vitlök", emoji: "🍝", bild: "assets/recipes/sparrispastacitron.jpg", kcal: 266, protein: 10, kolhydrater: 50, fett: 1, proteinkalla: "vegetariskt", allergener: ["gluten"], butik: "ICA", tid: 20, typ: "Vegetarisk", portionspris: 17, inkopspris: 69, sparar: 15, ingredienser: ["Sparris", "Pasta", "Citron", "Vitlök"], hemma: ["Olja", "Smör", "Salt", "Peppar", "Parmesan"], beskrivning: "Fräsch vårpasta med knaprig sparris, vitlök och en skvätt citron.", steg: ["Koka pastan enligt anvisningen och spara lite pastavatten.", "Bryt av sparrisens träiga ändar och stek den hastigt i olja och smör.", "Fräs i pressad vitlök kort och pressa över citron.", "Blanda med pastan och lite pastavatten till en lätt sås."], tips: "Riven parmesan på toppen om du har hemma lyfter rätten ytterligare." },
  { id: "morotscurry", namn: "Morotscurry med kikärtor", emoji: "🥕", bild: "assets/recipes/morotscurry.jpg", kcal: 399, protein: 13, kolhydrater: 74, fett: 3, proteinkalla: "veganskt", allergener: [], butik: "Hemköp", tid: 30, typ: "Vegetarisk", portionspris: 19, inkopspris: 74, sparar: 16, ingredienser: ["Morötter", "Kikärtor", "Curry & grönsaker", "Ris"], hemma: ["Olja", "Salt"], beskrivning: "Söt och mild currygryta med morötter och kikärtor — mättande vegansk vardagsmat.", steg: ["Koka riset enligt anvisningen.", "Skiva morötterna och fräs dem i olja tillsammans med curryblandningen.", "Häll på lite vatten och låt puttra tills morötterna är mjuka.", "Rör ner kikärtorna, värm igenom och servera med riset."], tips: "Mixa gärna en del av grytan slät om du vill ha en krämigare konsistens." }
);
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
const comboAffinity = combo => combo.reduce((sum, recipe) => sum + recipeAffinity(recipe), 0);
// combinations() is C(pool, count), so a fixed pool size makes the search
// blow up as the week gets longer: with the previous fixed pool of 24 a
// 7-dinner week evaluated 346,104 combos against 10,626 for 4 - measured at
// ~440ms just to build them, before any cost maths. Shrinking the pool for
// longer weeks keeps every week length in the same ballpark (~30-40k combos)
// while still leaving far more candidates than dinners to choose between.
const CANDIDATE_POOL_FOR_COUNT = { 5: 22, 6: 20, 7: 18 };
function evaluateCombos(recipes, count, branch) {
  const pool = limitCandidatePool(recipes, 6, CANDIDATE_POOL_FOR_COUNT[count] || 24);
  return combinations(pool, count).map(combo => ({ combo, cost: shoppingListCost(combo, branch) }));
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
  return Boolean(state.user?.premium) || devPremiumEnabled();
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
function weekPlanCandidates() {
  const dietOnly = localRecipesForUser().filter(recipe => !state.feedback[recipe.id]?.disliked);
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
  return scored.sort((a, b) => a.total - b.total || a.avstandKm - b.avstandKm)[0];
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
  state.livePriser = {};
  state.liveBranchTotals = {};
  saveState();
  render();
  if (shouldScroll) {
    setView("week");
  }
}

function renderRecipes() {
  const search = state.sokning.trim();
  const dietFilterActive = state.kost.kosttyp !== "" || state.kost.avoidAllergens.size > 0;
  const recipes = filterRecipes(search ? [...localRecipesForUser(), ...(dietFilterActive ? [] : state.apiRecipes)] : availableRecipes(), search).filter(recipe => (state.kategori === "alla" || recipe.typ === state.kategori) && (!state.maxTid || recipe.tid <= state.maxTid) && (!state.baraFavoriter || state.favoriter.has(recipe.id)));
  const branch = selectedBranch();
  const premiumStoreAuto = hasPremium();
  const storeLabel = state.butik === "auto" ? `${branch?.namn || "ingen butik hittades"}${premiumStoreAuto ? " (lägst uppskattat)" : " (närmast)"}` : state.butik === "alla" ? "alla butiker" : `${branch?.namn || state.butik}`;
  const loading = !state.branches.length && branchesSync.loading;
  // avstandKm can be null (e.g. a branch source that doesn't report distance,
  // or no state.position yet to measure from) - .toFixed() on that used to
  // throw and silently abort the rest of this render pass.
  const distanceText = Number.isFinite(branch?.avstandKm) ? ` och ligger ${branch.avstandKm.toFixed(1)} km bort` : "";
  $("locationHint").textContent = branch ? `${nearbyBranches().length} butiksprofiler jämförda${loading ? " (hämtar riktiga butiker nära dig...)" : ""} · ${branch.namn} ${premiumStoreAuto ? "har lägst uppskattat pris" : "ligger närmast"}${distanceText}.` : `Hittade inga inlästa butiker nära ${state.postnummer} ännu.`;
  $("menuSummary").textContent = search ? (dietFilterActive ? `${recipes.length} recept hittades. Externa recept visas inte när kost-/allergifilter är aktivt, eftersom de inte har kontrollerade allergiuppgifter.` : `${recipes.length} recept hittades. Externa recept kan vara på engelska och sakna svenska butikspriser.`) : `${plural(Math.min(state.middagar, recipes.length), "middag", "middagar")} för ${plural(state.personer, "person", "personer")} från ${storeLabel}. Priserna är uppskattningar.`;
  $("recipeScroll").innerHTML = recipes.length ? recipes.map(recipe => {
    const selected = state.valda.has(recipe.id), expanded = state.expanded === recipe.id;
    const details = RECIPE_DETAILS[recipe.id] || recipe;
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
  if (!id) { $("top").hidden = false; document.querySelector(".bottom-nav").hidden = false; $("recipePage").hidden = true; window.scrollTo(0, 0); return; }
  let allRecipes = [...RECEPT, ...state.apiRecipes];
  let recipe = allRecipes.find(item => item.id === id);
  if (!recipe && id.includes(":")) {
    try { const response = await fetch(recipeDetailApiUrl(id)); if (response.ok) { const data = await response.json(); recipe = mapApiRecipe(data.recipe); state.apiRecipes.push(recipe); allRecipes = [...RECEPT, ...state.apiRecipes]; } } catch { /* The friendly not-found state below remains visible. */ }
  }
  if (!recipe) return;
  const details = RECIPE_DETAILS[id] || recipe;
  $("top").hidden = true; document.querySelector(".bottom-nav").hidden = true; $("recipePage").hidden = false;
  $("recipePage").innerHTML = `<button class="back-link recipe-back" type="button">← Alla recept</button><article class="full-recipe">${recipe.bild ? `<img src="${recipe.bild}" alt="${recipe.namn}">` : `<div class="full-recipe-fallback">${recipePhoto(recipe)}</div>`}<p class="eyebrow">${recipe.typ}</p><h1>${recipe.namn}</h1><div class="recipe-detail-meta"><span>${recipe.tid ? recipe.tid + " min" : "Tid saknas"}</span><span>${recipe.servings || state.personer} portioner</span><span>${recipe.priceStatus === "unavailable" ? "Pris saknas" : recipe.portionspris ? money(recipe.portionspris) + "/portion" : "Uppskattat butikspris"}</span></div>${recipe.kcal ? `<p class="full-recipe-macros">${macroLine(recipe)}</p>` : ""}<p class="full-recipe-description">${details.beskrivning || "En god svensk vardagsrätt."}</p><button class="btn btn-primary recipe-add-primary" type="button" data-recipe-add="${recipe.id}"><span>${state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"}</span><span>＋</span></button>${recipeRatingMarkup(recipe.id)}${feedbackMarkup(recipe.id)}<h2>Ingredienser</h2><ul>${recipe.ingredienser.map(item => `<li>${item}</li>`).join("")}</ul><h2>Gör så här</h2><ol>${(details.steg || []).map(step => `<li>${step}</li>`).join("")}</ol>${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${details.tips}</p>` : ""}</article>`;
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
async function syncDatabasePricing(shoppingItems) {
  const items = shoppingItems.map(item => ({ name: item.namn, amount: item.total, unit: item.unit }));
  const key = items.map(item => `${item.name}:${item.amount}:${item.unit}`).sort().join("|");
  if (!items.length || databasePricingSync.key === key || databasePricingSync.pending) return;
  databasePricingSync = { key, pending: true };
  try {
    const response = await fetch(pricingWeekApiUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // The shared helper, not a second local copy - "what's already at
      // home" must mean the same thing here as everywhere else.
      body: JSON.stringify({ items, pantry: pantryAmounts(state.pantry || {}) }),
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (databasePricingSync.key !== key) return;
    state.dbChainTotals = {};
    (data.results || []).forEach(result => { state.dbChainTotals[result.chain] = result; });
    state.dbComparison = data.comparison || null;
    state.dbPricedAt = Date.now();
    renderBasket();
  } catch {
    // The price database being unreachable or empty must never break the
    // week view - the existing estimate stays exactly as it was.
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
  const result = state.dbChainTotals[chosenStore()];
  if (!result) return null;
  const item = (result.items || []).find(entry => entry.ingredient === name);
  // A "missing" row is in items[] on purpose - it must stay visible in the
  // list - but it is not a product to price, so it is not a match.
  return item && item.priceStatus !== "missing" ? item : null;
}

function databaseResultFor(branch) {
  return state.dbChainTotals[branch.kedja] || null;
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
  }).sort((a, b) => a.cost - b.cost);
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
    return `<small class="store-compare-coverage">${result.certain} av ${result.totalItems} varor prissatta · ${percent} % täckning${missing > 0 ? detail : ""}</small>`;
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
    const currentPriceText = hasUsablePrice(current)
      ? `<strong>ca ${money(current.cost)}</strong>`
      : `<strong class="price-missing">Pris saknas</strong>`;
    const currentHeading = !hasUsablePrice(current) ? "Inga priser hittades hos"
      : current.source === "database" ? "Pris hos" : current.isLive ? "Pris hos" : "Uppskattat pris hos";
    container.innerHTML = `<div class="store-compare"><div class="store-compare-head"><span>${currentHeading} ${current.branch.namn}</span>${currentPriceText}${coverageLabel(current)}${updatedLabel}</div>${results.length > 1 ? `<button type="button" class="store-compare-upsell" id="storeCompareUpsell-${containerId}">🔒 Prova Premium gratis i 14 dagar och se vilken butik som faktiskt är billigast av ${results.length}</button>` : ""}</div>`;
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
  container.innerHTML = `<div class="store-compare"><div class="store-compare-head"><span>${comparisonIsReal && winner && winner.branch.kedja === cheapest.branch.kedja ? "Lägst pris" : cheapest.isLive ? "Pris hos" : "Uppskattat pris"}</span><strong>${cheapest.branch.namn} · ca ${money(cheapest.cost)}</strong>${savingsAreReal ? (winner && winner.branch.kedja !== cheapest.branch.kedja
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
  const savings = priciestCost == null || !result.comparable ? null : priciestCost - result.cost;
  const color = CHAIN_COLORS[result.branch.kedja] || "var(--primary)";
  // A store whose live match rate is too thin to trust isn't allowed to
  // just show a partial sum as if it were the real total - see
  // branchLiveTotal's matched count. An estimate (matched === null) always
  // covers every item by construction, so it's never held to this bar.
  const coverageOk = hasUsablePrice(result) && (result.comparable || result.source !== "database");
  const coverageNote = result.source === "database"
    ? `${result.matched} av ${result.totalItems} varor har aktuellt pris`
    : result.matched != null ? `${result.matched} av ${result.totalItems} varor` : "Uppskattat";
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chain,
        items: shoppingItems.map(item => ({ name: item.namn, amount: item.total, unit: item.unit })),
        pantry: pantryAmounts(state.pantry || {}),
      }),
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    body.innerHTML = chainShoppingListMarkup(await response.json(), branch);
    body.querySelectorAll("[data-shopping]").forEach(input => input.addEventListener("change", () => {
      input.checked ? state.avklarade.add(input.dataset.shopping) : state.avklarade.delete(input.dataset.shopping);
      saveState();
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
  const head = sticky + `<div class="chain-list-head"><h2>${escapeHtml(storeName)}</h2><small>${escapeHtml([data.chain, distance].filter(Boolean).join(" · "))}</small>${pricedElsewhere}<div class="chain-list-total"><span>Total kassakostnad</span><strong>${money(total)}</strong></div><div class="chain-list-meta"><span>${data.realPriceItems} av ${data.totalItems} varor prissatta · ${coverage} % täckning</span>${data.estimatedItems ? `<span>${data.estimatedItems} med uppskattat antal</span>` : ""}${data.missingItems ? `<span>${data.missingItems} utan pris</span>` : ""}<span>${escapeHtml(updated)}</span>${savings}</div>${warning}</div>`;

  const rows = (data.items || []).map(item => {
    const checked = state.avklarade.has(item.ingredient);
    const missing = item.priceStatus === "missing";
    const photo = item.imageUrl
      ? `<img class="chain-item-photo" src="${escapeHtml(safeHttpUrl(item.imageUrl) || "")}" alt="" loading="lazy">`
      : `<span class="chain-item-photo" aria-hidden="true"></span>`;
    // What the recipe asks for, and what that means at the till: how many
    // whole packages of THIS product you have to put in the basket.
    const need = item.neededAmount != null
      ? `Behövs ${formatAmount(item.neededAmount)} ${escapeHtml(item.neededUnit || "")}` : "";
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
function formatAmount(value) {
  const number = Number(value) || 0;
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
  const bestCoverage = Math.max(0, ...results.map(r => r.matched ?? 0));
  $("comparisonItemCount").textContent = bestCoverage ? `${bestCoverage} av ${shoppingItems.length} varor` : `${shoppingItems.length} varor`;
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
  const activeSavings = priciest.cost - activeResult.cost;
  $("comparisonCampaignCard").hidden = !(activeSavings > 1);
  $("comparisonCampaignText").textContent = `Du sparar ${money(activeSavings)} med ${activeResult.branch.kedja}`;
  $("comparisonUpdated").textContent = state.liveUpdatedAt
    ? `Priserna uppdaterades ${new Date(state.liveUpdatedAt).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" })}`
    : "Uppskattade priser - riktiga priser hämtas när du öppnar Handla.";
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
  const countText = match.packages > 1 ? `${match.packages} st` : "";
  // Flagged, not hidden: when the recipe's unit can't be converted to the
  // pack's unit (a recipe in "st" against a pack in "g") the engine falls
  // back to one package. That is a guess about QUANTITY, and the shopper is
  // the one who can tell whether one is enough.
  const inexact = match.priceStatus === "estimated"
    ? '<small class="item-status estimated">Antal osäkert</small>' : "";
  const meta = escapeHtml([match.brand, packageText, countText].filter(Boolean).join(" · ") || "1 st");
  return `<label class="shopping-item ${checked ? "checked" : ""}"><input type="checkbox" data-shopping="${escapeHtml(item.namn)}" ${checked ? "checked" : ""}>${photo}<span class="shopping-item-info"><strong>${escapeHtml(match.productName)}</strong><small class="shopping-item-meta">${meta}</small>${campaign}</span><span class="shopping-item-price"><strong>${money(match.totalCost)}</strong>${inexact}</span></label>`;
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
  const stillFetching = packages > 0 && !live && livePriceSync.loading && VALID_CHAINS.includes(chain);
  const isEstimated = packages > 0 && !live && !stillFetching;
  const priceLabel = priceMissing ? "Pris saknas" : live ? money(live.pris_kr * (packages || 1)) : product.pris ? money(product.pris * packages) : "";
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
  const meta = !packages ? "Finns hemma" : escapeHtml([brandSize, qty].filter(Boolean).join(" · ") || "1 st");
  const campaign = live?.kampanj?.text ? `<small class="shopping-item-campaign">🏷️ ${escapeHtml(live.kampanj.text)}</small>` : "";
  const status = stillFetching ? '<small class="item-status loading">Hämtar…</small>' : isEstimated ? '<small class="item-status estimated">Uppskattat</small>' : "";
  const photo = live?.bild ? `<img class="shopping-item-image has-image" src="${live.bild}" alt="" loading="lazy">` : categoryIconMarkup(itemCategory(item.namn));
  return `<label class="shopping-item ${state.avklarade.has(item.namn) ? "checked" : ""}"><input type="checkbox" data-shopping="${item.namn}" ${state.avklarade.has(item.namn) ? "checked" : ""}>${photo}<span class="shopping-item-info"><strong>${displayName}</strong><small class="shopping-item-meta">${meta}</small>${campaign}</span><span class="shopping-item-price"><strong class="${priceMissing ? "price-missing" : ""}">${priceLabel}</strong>${status}</span></label>`;
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
function nextMealCardMarkup(recipe) {
  const badge = recipe.typ && recipe.typ !== "Provider-recept" ? `<span class="next-meal-badge">${escapeHtml(recipe.typ)}</span>` : "";
  return `<button type="button" class="next-meal-card" data-week-details="${escapeHtml(recipe.id)}"><span class="next-meal-photo">${recipePhoto(recipe)}</span><span class="next-meal-info"><small>Idag</small><strong>${escapeHtml(recipe.namn)}</strong>${badge}</span><span class="next-meal-arrow" aria-hidden="true">›</span></button>`;
}
function nextMealEmptyMarkup() {
  return `<div class="next-meal-empty"><p>Ingen middag planerad för idag ännu.</p><button type="button" class="btn btn-ghost" data-week-browse-recipes>Bläddra recept</button></div>`;
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
  const live = state.livePriser[item.namn];
  const priceMissing = live && live.pris_kr == null;
  const price = priceMissing ? "Pris saknas" : live ? money(live.pris_kr) : PRODUCT_CATALOG[item.namn]?.pris ? money(PRODUCT_CATALOG[item.namn].pris) : "";
  const campaign = live?.kampanj?.text ? `<small class="week-shopping-campaign">🏷️ ${escapeHtml(live.kampanj.text)}</small>` : "";
  const photo = live?.bild ? `<img class="shopping-item-image has-image" src="${live.bild}" alt="" loading="lazy">` : categoryIconMarkup(itemCategory(item.namn));
  return `<label class="week-shopping-row"><input type="checkbox" data-week-shopping="${escapeHtml(item.namn)}">${photo}<span class="week-shopping-info"><strong>${escapeHtml(item.namn)}</strong>${campaign}</span><strong class="week-shopping-price ${priceMissing ? "price-missing" : ""}">${price}</strong></label>`;
}
function renderWeekOverview(selected, shoppingItems, total) {
  $("weekDayTabs").innerHTML = DAYS.map((day, index) => `<button type="button" class="week-day-tab ${index === weekOverviewDay ? "active" : ""} ${selected[index] ? "" : "empty"}" data-week-day="${index}" role="tab" aria-selected="${index === weekOverviewDay}">${day}</button>`).join("");

  const todayRecipe = selected[weekOverviewDay];
  $("weekTodayCard").innerHTML = todayRecipe ? weekTodayCardMarkup(todayRecipe) : weekEmptyDayMarkup();

  const planVisibleCount = weekPlanExpanded ? selected.length : Math.min(selected.length, WEEK_PLAN_PREVIEW_COUNT);
  $("weekPlanList").innerHTML = selected.slice(0, planVisibleCount).map(weekPlanRowMarkup).join("");
  $("weekPlanToggle").hidden = selected.length <= WEEK_PLAN_PREVIEW_COUNT;
  $("weekPlanToggle").textContent = weekPlanExpanded ? "Visa färre" : "Visa hela veckan";
  $("weekPlanToggle").onclick = () => { weekPlanExpanded = !weekPlanExpanded; renderWeekOverview(selected, shoppingItems, total); };

  const remainingItems = shoppingItems.filter(item => !state.avklarade.has(item.namn));
  $("weekShoppingSummary").textContent = shoppingItems.length ? `${plural(remainingItems.length, "vara kvar", "varor kvar")} · ${money(total)}` : "";
  $("weekShoppingPreview").innerHTML = shoppingItems.length
    ? (remainingItems.length ? remainingItems.slice(0, WEEK_SHOPPING_PREVIEW_COUNT).map(weekShoppingRowMarkup).join("") : `<p class="week-shopping-done">🎉 Allt handlat!</p>`)
    : `<p class="week-shopping-done">Skapa en vecka så samlar vi din inköpslista här.</p>`;
  $("weekShoppingOpenBtn").onclick = () => setView("basket");

  // Hem's "Nästa middag" - always literally today, independent of whichever
  // day tab the user has clicked above (that's a browsing choice on the
  // Vecka page, not a change to what "next" means on Hem). Same recipePhoto
  // call as the Vecka card above, so it's the same image, not a new fetch.
  const heroRecipe = selected[todayIndex()];
  $("nextMealCard").innerHTML = heroRecipe ? nextMealCardMarkup(heroRecipe) : nextMealEmptyMarkup();

  // Hem's budget-progress card - fed the same total this function already
  // received from renderBasket(), never recomputed separately.
  const heroRemaining = budgetRemaining(state.budget, total);
  const percentUsed = state.budget ? Math.min(100, Math.round(total / state.budget * 100)) : 0;
  $("summaryBudgetRemaining").textContent = money(Math.max(0, heroRemaining));
  $("summaryBudgetTotal").textContent = money(state.budget);
  $("summaryBudgetPercent").textContent = `${percentUsed}%`;
  $("summaryBudgetBar").style.width = `${percentUsed}%`;
  $("summaryBudgetBar").classList.toggle("over-budget", heroRemaining < 0);

  // All wired together at the end, once every section above has its final
  // DOM in place - wiring data-week-details right after only the today-card
  // was rendered would miss the plan list's own rows, which don't exist yet
  // at that point.
  document.querySelectorAll("[data-week-day]").forEach(button => button.addEventListener("click", () => { weekOverviewDay = Number(button.dataset.weekDay); renderWeekOverview(selected, shoppingItems, total); }));
  document.querySelectorAll("[data-week-details]").forEach(button => button.addEventListener("click", () => openRecipeTab(button.dataset.weekDetails)));
  document.querySelectorAll("[data-week-add-meal]").forEach(button => button.addEventListener("click", () => setView("home")));
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
  const shoppingItems = aggregateShopping(selected);
  // The header total must be the SAME number the store-comparison widget
  // shows for the currently selected/pinned branch - a live total when one
  // has been fetched, the static per-package estimate otherwise - never a
  // second, independently-computed figure that could quietly disagree with
  // what's shown right below it.
  const branches = nearbyBranches();
  const currentResult = branches.length ? computeStoreResults(selected, branches, shoppingItems).find(r => sameBranch(r.branch, selectedBranch())) : null;
  const total = currentResult ? currentResult.cost : shoppingListCost(selected, selectedBranch());
  const groups = shoppingItems.reduce((result, item) => { const category = itemCategory(item.namn); (result[category] ||= []).push(item); return result; }, {});
  $("shoppingList").innerHTML = shoppingItems.length ? Object.entries(groups).map(([category, items]) => `<section><h3>${category}<span>${items.length}</span></h3>${items.map(shoppingItemMarkup).join("")}</section>`).join("") : `<div class="pantry-empty"><h2>Listan väntar på din vecka</h2><p>Skapa en meny så samlar vi automatiskt allt du behöver handla.</p></div>`;
  document.querySelectorAll("[data-shopping]").forEach(input => input.addEventListener("change", () => { input.checked ? state.avklarade.add(input.dataset.shopping) : state.avklarade.delete(input.dataset.shopping); saveState(); renderBasket(); }));
  const completed = shoppingItems.filter(item => state.avklarade.has(item.namn)).length, itemsLeft = shoppingItems.length - completed, progress = shoppingItems.length ? completed / shoppingItems.length * 100 : 0;
  // No mention of how many items happen to have a live-fetched price, and no
  // fetch timestamp - that's internal plumbing, not something a shopper needs
  // to see. Only the plain, calm facts: what's left, and what it costs.
  $("shoppingProgress").textContent = shoppingItems.length ? plural(itemsLeft, "vara kvar", "varor kvar") : "";
  $("shoppingCost").textContent = `${money(total)} / ${money(state.budget)}`; $("shoppingProgressBar").style.width = `${progress}%`;
  $("shoppingComplete").hidden = !(shoppingItems.length && completed === shoppingItems.length);
  renderAttribution(shoppingItems);
  renderStoreComparison(selected); renderStoreComparison(selected, "basketStoreCompare"); renderPantry();
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
  const names = shoppingItems.map(item => item.namn).sort();
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
function aggregateShopping(selected) {
  return aggregateIngredients(selected.filter(recipe => recipe.priceStatus !== "unavailable"), RECIPE_QUANTITIES, PACKAGE_INFO, state.personer);
}

function updateSummary() { $("summaryPeople").textContent = plural(state.personer, "person", "personer"); $("summaryMeals").textContent = plural(state.middagar, "middag", "middagar"); }
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
function render() { renderGreeting(); renderRecipes(); renderHemRecipePreview(); renderBasket(); updateSummary(); renderStats(); }
function step(key, delta, min, max) { state[key] = Math.min(max, Math.max(min, state[key] + delta)); $(`${key === "personer" ? "people" : "meals"}Value`).textContent = state[key]; saveState(); render(); }
function syncSettingsInputs() {
  $("budgetInput").value = state.budget; $("peopleValue").textContent = state.personer; $("mealsValue").textContent = state.middagar; $("storeInput").value = state.butik; $("postcodeInput").value = state.postnummer;
  $("kosttypInput").value = state.kost.kosttyp;
  document.querySelectorAll("#allergenChips input").forEach(box => { box.checked = state.kost.avoidAllergens.has(box.value); });
  const autoOption = document.querySelector('#storeInput option[value="auto"]');
  if (autoOption) autoOption.textContent = hasPremium() ? "Billigast automatiskt" : "Närmast automatiskt (Premium: billigast)";
}
syncSettingsInputs();
$("budgetInput").addEventListener("input", e => { state.budget = clampBudget(e.target.value); saveState(); updateSummary(); renderBasket(); });
const debouncedGeocode = createDebouncedSearch((zip, signal) => fetch(geocodeApiUrl(zip), { signal }).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }), 400);
$("postcodeInput").addEventListener("input", e => {
  const previous = state.postnummer;
  state.position = null;
  state.postnummer = e.target.value.replace(/\D/g, "");
  // Drop the old town's stores and prices the moment the postcode actually
  // changes, not when the new ones happen to arrive - otherwise the user
  // sees Gävle stores while typing a Stockholm postcode.
  if (state.postnummer !== previous) clearLocationDerivedState();
  saveState(); chooseMenu(false);
  if (state.postnummer.length !== 5) return;
  const zip = state.postnummer;
  syncNearbyBranches();
  debouncedGeocode(zip).then(place => {
    if (state.postnummer !== zip) return;
    state.position = { lat: place.lat, lon: place.lon, ort: place.ort };
    saveState(); chooseMenu(false);
  }).catch(() => { /* geokodning misslyckades - postnumret används ändå för exakt/ungefärlig matchning som innan */ });
});
$("locateBtn").addEventListener("click", () => { if (!navigator.geolocation) return; $("locateBtn").textContent = "Hämtar..."; navigator.geolocation.getCurrentPosition(({ coords }) => { state.position = { lat: coords.latitude, lon: coords.longitude }; $("locateBtn").textContent = "Hittad"; chooseMenu(false); }, () => { $("locateBtn").textContent = "Försök igen"; }); });
$("storeInput").addEventListener("change", e => { state.butik = e.target.value; saveState(); chooseMenu(); renderCampaignSection(); });
$("budgetCardBtn").addEventListener("click", () => { $("advancedSettings").open = true; $("advancedSettings").scrollIntoView({ behavior: "smooth", block: "center" }); });

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
  chooseMenu(false);
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
  saveState(); chooseMenu(false);
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
$("categoryFilter").addEventListener("change", e => { state.kategori = e.target.value; renderRecipes(); });
$("timeFilter").addEventListener("change", e => { state.maxTid = Number(e.target.value); renderRecipes(); });
$("favoriteFilter").addEventListener("change", e => { state.baraFavoriter = e.target.checked; renderRecipes(); });
function setView(view) { $("top").className = `app view-${view}`; document.querySelectorAll(".bottom-nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view)); window.scrollTo({ top: 0, behavior: "smooth" }); }
document.querySelectorAll("[data-view]").forEach(item => item.addEventListener("click", () => setView(item.dataset.view)));
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
    $("startTrialBtn").hidden = state.user.trialUsed;
    $("subscriptionPanel").hidden = !hasSubscription;
    if (hasSubscription) {
      const periodEnd = state.user.subscriptionPeriodEnd ? new Date(state.user.subscriptionPeriodEnd).toLocaleDateString("sv-SE") : "okänt datum";
      const planLabel = state.user.subscriptionPlan === "yearly" ? "499 kr/år" : "59 kr/mån";
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
    $("swapOptions").innerHTML = `<button type="button" class="store-compare-upsell" id="swapUpsell">🔒 Du har använt dina ${FREE_SWAP_LIMIT} gratis byten den här veckan. Prova Premium gratis i 14 dagar för obegränsade byten.</button>`;
    $("swapUpsell").addEventListener("click", () => { closeSwapModal(); openPremiumPitch(); });
    $("swapConfirmBtn").hidden = true; $("swapShowMoreBtn").hidden = true;
    $("swapModal").hidden = false;
    return;
  }
  const selected = selectedRecipes();
  const dayIndex = state.weekPlan.indexOf(currentId);
  const branch = selectedBranch();
  const candidates = candidateRecipesForUser().filter(recipe => !state.valda.has(recipe.id));
  const allOptions = candidates.map(candidate => ({ candidate, total: shoppingListCost(selected.map(recipe => recipe.id === currentId ? candidate : recipe), branch) })).sort((a, b) => a.total - b.total);
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
  saveState(); render(); closeSwapModal();
});
function closeSwapModal() { $("swapModal").hidden = true; swapContext = null; }
document.querySelectorAll("[data-swap-close]").forEach(button => button.addEventListener("click", closeSwapModal));

const PLAN_TYPES = [
  { key: "cheapest", label: "Billigast möjliga vecka", hint: "Lägsta totalkostnaden i kassan." },
  { key: "balanced", label: "Balanserad vecka", hint: "Bra variation och högt betygsatta rätter." },
  { key: "protein", label: "Proteinrik vecka", hint: "Mest protein för pengarna." },
];
function priciestBranchFor(combo) {
  return nearbyBranches().reduce((worst, candidate) => { const cost = shoppingListCost(combo, candidate); return !worst || cost > worst.cost ? { branch: candidate, cost } : worst; }, null);
}
function planCardMarkup(plan, branch) {
  const portionCost = plan.cost / (plan.combo.length * state.personer);
  const priciest = priciestBranchFor(plan.combo);
  const savings = priciest ? priciest.cost - plan.cost : 0;
  return `<div class="plan-card"><div class="plan-card-head"><strong>${plan.label}</strong><span>${plan.hint}</span></div><div class="plan-card-price"><b>${money(plan.cost)}</b><small>ca ${money(portionCost)} / portion hos ${escapeHtml(branch?.namn || "din butik")}</small></div>${savings > 1 ? `<p class="plan-card-savings">Uppskattad besparing ca ${money(savings)} mot ${escapeHtml(priciest.branch.namn)} - priser ej live</p>` : ""}<ul class="plan-card-meals">${plan.combo.map(recipe => `<li>${escapeHtml(recipe.namn)}</li>`).join("")}</ul><button class="btn btn-primary" type="button" data-choose-plan="${plan.key}"><span>Välj den här</span></button></div>`;
}
function openPlanComparison() {
  const branch = selectedBranch();
  const { candidates, nutritionShortfall } = weekPlanCandidates();
  updateNutritionWarning(nutritionShortfall);
  if (!candidates.length) { chooseMenu(); return; }
  const plans = PLAN_TYPES.map(type => { const combo = bestMenuCombo(candidates, state.middagar, state.budget, branch, type.key); return { ...type, combo, cost: shoppingListCost(combo, branch) }; }).filter(plan => plan.combo.length);
  if (plans.length < 2) { chooseMenu(); return; }
  $("planCards").innerHTML = plans.map(plan => planCardMarkup(plan, branch)).join("");
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
    state.livePriser = {};
    state.liveBranchTotals = {};
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
  $("savingsCardValue").textContent = weekEntries.length ? money(savedWeek) : "–";
  $("savingsCardSubtitle").textContent = !state.savingsLog.length ? "Skapa din första vecka för att se detta" : weekEntries.length ? "denna vecka, jämfört med dyraste alternativet" : "Underlag saknas - fler butiker behövs för en jämförelse";
}
$("openStatsBtn").addEventListener("click", () => { renderStats(); setView("stats"); });

const DISLIKE_SUGGESTIONS = ["Lök", "Svamp", "Fisk", "Skaldjur", "Nötter", "Inälvsmat", "Stark mat", "Kokosmjölk"];
const ONBOARDING_STEPS = [
  { title: "Vilka är ni hemma?", render: renderObHushall },
  { title: "Budget & antal middagar", render: renderObBudget },
  { title: "Kost & allergier", render: renderObKost },
  { title: "Något ni hellre slipper?", render: renderObOgillar },
  { title: "Hur mycket tid har ni?", render: renderObTid },
  { title: "Kalorier & makron", render: renderObNaring },
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
  return `<label for="obPostcode">Postnummer</label><div class="location-row"><input id="obPostcode" value="${escapeHtml(state.postnummer)}" inputmode="numeric" maxlength="5"><button type="button" id="obLocateBtn">Hitta mig</button></div><p class="ob-error" id="obPostcodeError"></p><label for="obStore">Favoritbutik</label><select id="obStore"><option value="auto" ${state.butik === "auto" ? "selected" : ""}>Billigast automatiskt</option><option value="alla" ${state.butik === "alla" ? "selected" : ""}>Alla butiker</option><option value="ICA" ${state.butik === "ICA" ? "selected" : ""}>ICA</option><option value="Willys" ${state.butik === "Willys" ? "selected" : ""}>Willys</option><option value="Hemköp" ${state.butik === "Hemköp" ? "selected" : ""}>Hemköp</option><option value="Coop" ${state.butik === "Coop" ? "selected" : ""}>Coop</option></select>`;
}
function wireOnboardingStep() {
  document.querySelectorAll("[data-ob-adj]").forEach(button => button.addEventListener("click", () => {
    const key = button.dataset.obAdj, delta = Number(button.dataset.delta), min = key === "vuxna" ? 1 : 0;
    state.hushall[key] = Math.max(min, state.hushall[key] + delta);
    state.personer = state.hushall.vuxna + state.hushall.barn;
    saveState(); renderOnboardingStep();
  }));
  $("obBudget")?.addEventListener("input", e => { state.budget = clampBudget(e.target.value); saveState(); });
  document.querySelectorAll("[data-ob-meals]").forEach(button => button.addEventListener("click", () => {
    state.middagar = Math.min(MAX_MEALS, Math.max(1, state.middagar + Number(button.dataset.obMeals)));
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
const CAMPAIGN_CHAINS = ["Coop", "Hemköp"];
let campaignFetchKey = null;
function campaignDealMarkup(deal) {
  const recipe = RECEPT.find(item => item.ingredienser.includes(deal.ingrediens));
  // Real photo (Primat first, Open Food Facts by GTIN otherwise - see
  // fill_missing_image on the backend) or a category icon, never a bare
  // emoji standing in for a product - same guaranteed-image rule as the
  // shopping list.
  const photo = deal.bild ? `<img src="${escapeHtml(deal.bild)}" alt="" loading="lazy">` : categoryIconMarkup(itemCategory(deal.ingrediens));
  const discount = deal.kampanj.ordinariePris && deal.pris_kr ? Math.round((1 - deal.pris_kr / deal.kampanj.ordinariePris) * 100) : null;
  const badge = discount && discount > 0 ? `<span class="campaign-deal-badge">−${discount}%</span>` : "";
  const brandSize = deal.marke_och_storlek ? `<small class="campaign-deal-brand">${escapeHtml(deal.marke_och_storlek)}</small>` : "";
  // slutdatum comes straight from Primat's own offer.valid_until - never
  // computed or guessed here, and simply omitted when Primat doesn't have one.
  const endDate = deal.kampanj.slutdatum ? `<small class="campaign-deal-enddate">T.o.m. ${new Date(deal.kampanj.slutdatum).toLocaleDateString("sv-SE", { day: "numeric", month: "short" })}</small>` : "";
  const storeColor = CHAIN_COLORS[deal.kedja] || "var(--primary)";
  const inner = `<span class="campaign-deal-image">${photo}${badge}</span><span class="campaign-deal-info"><strong>${escapeHtml(deal.produktnamn)}</strong>${brandSize}<span class="campaign-deal-price-row"><strong class="campaign-deal-price">${money(deal.pris_kr)}</strong>${deal.kampanj.ordinariePris ? `<s>${money(deal.kampanj.ordinariePris)}</s>` : ""}</span><span class="campaign-deal-condition">${escapeHtml(deal.kampanj.text)}</span><span class="campaign-deal-store" style="color:${storeColor}">${escapeHtml(deal.kedja || "")}</span>${endDate}</span>`;
  // The whole card opens the matched recipe when there is one (real,
  // existing navigation) rather than a small text link easy to miss or
  // overflow - a card with nothing to open stays a plain, non-interactive div.
  return recipe
    ? `<button type="button" class="campaign-deal" data-cook-open="${escapeHtml(recipe.id)}">${inner}</button>`
    : `<div class="campaign-deal">${inner}</div>`;
}
async function renderCampaignSection() {
  const premium = hasPremium();
  $("campaignLocked").hidden = premium;
  if (!premium) { $("campaignList").innerHTML = ""; $("campaignStoreLabel").hidden = true; return; }
  const chain = chosenStore();
  if (!CAMPAIGN_CHAINS.includes(chain)) {
    $("campaignStoreLabel").hidden = true;
    $("campaignList").innerHTML = `<p class="live-loading">Kampanjer visas för Coop och Hemköp. Byt butik i "Justera veckan" för att se dem.</p>`;
    return;
  }
  // Every deal in this list comes from the same chain (the fetch itself is
  // scoped to one) - shown once here instead of repeated on every row, so
  // it's always clear which store's campaigns these are without cluttering
  // each item with a label that would just say the same thing every time.
  $("campaignStoreLabel").textContent = `Hos ${chain}`;
  $("campaignStoreLabel").hidden = false;
  const key = `${chain}|${state.postnummer}`;
  if (campaignFetchKey === key) return;
  campaignFetchKey = key;
  $("campaignList").innerHTML = `<p class="live-loading">Letar efter kampanjer hos ${chain}... kan ta en stund.</p>`;
  try {
    const response = await fetch(campaignsApiUrl(chain, state.postnummer), { headers: { Authorization: `Bearer ${getStoredToken()}` }, signal: AbortSignal.timeout(25000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (chosenStore() !== chain) return;
    const deals = data.kampanjer || [];
    $("campaignList").innerHTML = deals.length ? deals.map(campaignDealMarkup).join("") : `<p class="live-loading">Inga kampanjer hittades just nu.</p>`;
    document.querySelectorAll("[data-cook-open]").forEach(link => link.addEventListener("click", event => { event.preventDefault(); openRecipeTab(link.dataset.cookOpen); }));
    const usesPrimat = deals.some(deal => deal.kalla === "primat"), usesOff = deals.some(deal => deal.bild_kalla === "openfoodfacts");
    $("campaignAttribution").innerHTML = attributionMarkup(usesPrimat, usesOff);
    $("campaignAttribution").hidden = !(usesPrimat || usesOff);
  } catch {
    campaignFetchKey = null;
    $("campaignList").innerHTML = `<p class="live-loading">Kunde inte hämta kampanjer just nu.</p>`;
    $("campaignAttribution").hidden = true;
  }
}
// Every found deal is already rendered (the backend doesn't paginate this
// scan) - "Visa alla" scrolls the row to its end rather than opening a
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
function openPremiumPitch() { openAccountModal(); }
$("startTrialBtn").addEventListener("click", async () => {
  $("trialError").textContent = "";
  if (!state.authToken) { $("trialError").textContent = "Skapa ett konto eller logga in först - provperioden kopplas till ditt konto."; return; }
  try {
    const { user } = await startTrial(state.authToken);
    state.user = user; renderAccount(); chooseMenu(false); renderCampaignSection();
  } catch (error) { $("trialError").textContent = error.message; }
});
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
$("logoutBtn").addEventListener("click", async () => {
  if (state.authToken) { try { await logoutRequest(state.authToken); } catch { /* session redan ogiltig server-side, städa lokalt ändå */ } }
  state.authToken = null; state.user = null; storeToken(null);
  renderAccount(); closeAccountModal();
});
$("peopleMinus").addEventListener("click", () => step("personer", -1, 1, 12)); $("peoplePlus").addEventListener("click", () => step("personer", 1, 1, 12));
$("mealsMinus").addEventListener("click", () => step("middagar", -1, 1, MAX_MEALS)); $("mealsPlus").addEventListener("click", () => step("middagar", 1, 1, MAX_MEALS));
$("generateBtn").addEventListener("click", () => openPlanComparison()); $("refreshBtn").addEventListener("click", () => { RECEPT.push(RECEPT.shift()); chooseMenu(); });
$("startNewWeekBtn").addEventListener("click", () => openPlanComparison());
let pantryPickLocation = "skafferi";
function renderPantryPicker(query) {
  const search = query.trim().toLowerCase();
  const matches = Object.entries(PRODUCT_CATALOG).filter(([key, product]) => !search || key.toLowerCase().includes(search) || product.namn.toLowerCase().includes(search) || product.marke.toLowerCase().includes(search)).slice(0, 30);
  $("pantryPickerList").innerHTML = matches.length ? matches.map(([key, product]) => `<button type="button" class="pantry-pick" data-pantry-pick="${escapeHtml(key)}"><span class="pantry-pick-info"><strong>${escapeHtml(product.namn)}</strong><small>${escapeHtml(product.marke)} · ${escapeHtml(product.storlek)}</small></span><span class="pantry-pick-add">+ Lägg till</span></button>`).join("") : !search ? "" : `<p class="pantry-picker-empty">Inga vanliga varor matchar "${escapeHtml(query)}".</p>`;
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
    state.pantry[key] = { amount: entry.amount + (PACKAGE_INFO[key]?.amount || 1), location: pantryPickLocation, expiry: $("pantryAddExpiry").value || null };
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
if (!state.onboardingComplete) openOnboarding();
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
window.addEventListener("popstate", renderRecipePage);
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => { /* offline-stödet är ett tillägg - appen funkar utan det */ }));
}
