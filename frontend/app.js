import { readStoredState, writeStoredState } from "./src/state/storage.js";
import { aggregateIngredients, budgetRemaining, calculateShoppingTotal, clampBudget, portionFactor } from "./src/services/calculations.js";
import { createDebouncedSearch, filterRecipes, mergeRecipeResults } from "./src/services/recipe-search.js";
import { filterByNutritionGoals, hasActiveNutritionGoals } from "./src/services/nutrition.js";
import { expiryStatus, matchLocalRecipesToPantry, normalizePantry, pantryAmounts } from "./src/services/pantry.js";
import { ALLERGENS, filterByDiet } from "./src/services/diet.js";
import { inBudgetPool, limitCandidatePool, pickBalanced, pickCheapest, pickProtein } from "./src/services/planning.js";
import { campaignsApiUrl, geocodeApiUrl, productApiUrl as configuredProductApiUrl, productsBatchApiUrl, recipeDetailApiUrl, recipeSearchApiUrl, recipesByPantryApiUrl, storesApiUrl } from "./src/api/config.js";
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
const savedState = readStoredState(localStorage);
const state = { budget: savedState.budget || 800, personer: savedState.personer || 2, middagar: savedState.middagar || 4, butik: savedState.butik || "auto", postnummer: savedState.postnummer || "80252", position: null, sokning: "", kategori: "alla", maxTid: savedState.maxTid || 0, baraFavoriter: false, apiRecipes: savedState.apiRecipes || [], pantry: normalizePantry(savedState.pantry || {}), pantryTab: "skafferi", liveProdukter: [], favoriter: new Set(savedState.favoriter || []), valda: new Set(savedState.valda || []), avklarade: new Set(savedState.avklarade || []), expanded: null, authToken: getStoredToken(), user: null, naringsmal: savedState.naringsmal || null, livePriser: {}, liveBranchTotals: {}, liveUpdatedAt: null, branches: [], betyg: savedState.betyg || {}, kost: { kosttyp: savedState.kost?.kosttyp || "", avoidAllergens: new Set(savedState.kost?.avoidAllergens || []) }, onboardingComplete: savedState.onboardingComplete || false, hushall: savedState.hushall || { vuxna: savedState.personer || 2, barn: 0 }, ogillar: new Set(savedState.ogillar || []), feedback: savedState.feedback || {}, savingsLog: savedState.savingsLog || [], swapsThisWeek: savedState.swapsThisWeek || 0 };
function buildSyncPayload() {
  return { budget: state.budget, personer: state.personer, middagar: state.middagar, butik: state.butik, postnummer: state.postnummer, maxTid: state.maxTid, pantry: state.pantry, favoriter: [...state.favoriter], valda: [...state.valda], avklarade: [...state.avklarade], apiRecipes: state.apiRecipes.filter(recipe => state.valda.has(recipe.id)), naringsmal: state.naringsmal, betyg: state.betyg, kost: { kosttyp: state.kost.kosttyp, avoidAllergens: [...state.kost.avoidAllergens] }, onboardingComplete: state.onboardingComplete, hushall: state.hushall, ogillar: [...state.ogillar], feedback: state.feedback, savingsLog: state.savingsLog, swapsThisWeek: state.swapsThisWeek };
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
function evaluateCombos(recipes, count, branch) {
  return combinations(limitCandidatePool(recipes), count).map(combo => ({ combo, cost: shoppingListCost(combo, branch) }));
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
function nearbyBranches() { return state.branches.length ? state.branches : FALLBACK_BRANCH; }
let branchesSync = { key: null, loading: false };
async function syncNearbyBranches() {
  const zip = state.postnummer;
  if (!/^\d{5}$/.test(zip) || branchesSync.key === zip || branchesSync.loading) return;
  branchesSync = { key: zip, loading: true };
  try {
    const response = await fetch(storesApiUrl(zip), { signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (state.postnummer !== zip) return;
    state.branches = (data.butiker || []).map(store => ({ kedja: store.kedja, namn: store.namn, lat: store.lat, lon: store.lon, avstandKm: store.avstandKm, prisfaktor: 1 }));
    state.liveBranchTotals = {};
    chooseMenu(false);
  } catch { /* nätverket svarade inte - den uppskattade fallback-butiken visas kvar tills det går att försöka igen */ }
  finally { branchesSync.loading = false; }
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
  if (!state.user?.premium) return dietFiltered;
  return filterByNutritionGoals(dietFiltered, currentNutritionGoals());
}
function candidateRecipesForUser() {
  return nutritionFilteredRecipes().filter(recipe => !state.feedback[recipe.id]?.disliked);
}
function cheapestBranch(chain = null) {
  const branches = nearbyBranches().filter(branch => !chain || branch.kedja === chain);
  const candidates = candidateRecipesForUser();
  return branches.map(branch => {
    const recipes = bestMenuCombo(candidates, state.middagar, state.budget, branch);
    const avstandKm = state.position ? distanceKm(state.position.lat, state.position.lon, branch.lat, branch.lon) : branch.avstandKm;
    return { ...branch, avstandKm, recipes, total: shoppingListCost(recipes, branch) };
  }).filter(result => result.recipes.length).sort((a, b) => a.total - b.total || a.avstandKm - b.avstandKm)[0] || null;
}
let branchCache = { key: null, value: null };
function selectedBranch() {
  const key = JSON.stringify([state.budget, state.middagar, state.butik, state.postnummer, state.position, RECEPT.length, state.apiRecipes.length, state.user?.premium, state.naringsmal]);
  if (branchCache.key !== key) branchCache = { key, value: state.butik === "auto" ? cheapestBranch() : cheapestBranch(state.butik) };
  return branchCache.value;
}
function cheapestStore() {
  return selectedBranch();
}

const chosenStore = () => cheapestStore()?.kedja || state.butik;
const productApiUrl = (store, query) => configuredProductApiUrl(store, query, state.postnummer);
function sanitizeApiPayload(payload) {
  if (!Array.isArray(payload?.produkter)) return payload;
  return { ...payload, produkter: payload.produkter.map(product => ({ ...product, produktnamn: escapeHtml(product.produktnamn), marke_och_storlek: escapeHtml(product.marke_och_storlek), bild: safeHttpUrl(product.bild), url: safeHttpUrl(product.url), pris_kr: Number(product.pris_kr) || 0 })) };
}
const availableRecipes = () => candidateRecipesForUser();

function chooseMenu(shouldScroll = true) {
  const branch = selectedBranch();
  const combo = bestMenuCombo(availableRecipes(), state.middagar, state.budget, branch);
  state.valda.clear();
  combo.forEach(r => state.valda.add(r.id));
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
  const storeLabel = state.butik === "auto" ? `${branch?.namn || "ingen butik hittades"} (lägst uppskattat)` : state.butik === "alla" ? "alla butiker" : `${branch?.namn || state.butik}`;
  const loading = !state.branches.length && branchesSync.loading;
  $("locationHint").textContent = branch ? `${nearbyBranches().length} butiksprofiler jämförda${loading ? " (hämtar riktiga butiker nära dig...)" : ""} · ${branch.namn} har lägst uppskattat pris och ligger ${branch.avstandKm.toFixed(1)} km bort.` : `Hittade inga inlästa butiker nära ${state.postnummer} ännu.`;
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
  document.querySelectorAll("[data-add]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.add; state.valda.has(id) ? state.valda.delete(id) : state.valda.add(id); saveState(); render(); }));
  document.querySelectorAll("[data-favorite]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.favorite; state.favoriter.has(id) ? state.favoriter.delete(id) : state.favoriter.add(id); saveState(); renderRecipes(); }));
}

function openRecipeTab(id) { history.pushState({ recept: id }, "", `${location.pathname}?recept=${encodeURIComponent(id)}`); renderRecipePage(); }
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
  $("recipePage").querySelector("[data-recipe-add]").addEventListener("click", event => { state.valda.has(recipe.id) ? state.valda.delete(recipe.id) : state.valda.add(recipe.id); saveState(); render(); event.currentTarget.querySelector("span").textContent = state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"; });
  wireRatingStars($("recipePage"), recipe.id);
  wireFeedbackButtons($("recipePage"), recipe.id);
  requestAnimationFrame(() => window.scrollTo(0, 0));
  let touchStartX = 0; $("recipePage").ontouchstart = event => { touchStartX = event.changedTouches[0].screenX; }; $("recipePage").ontouchend = event => { const distance = event.changedTouches[0].screenX - touchStartX; if (Math.abs(distance) < 70) return; const ids = allRecipes.map(item => item.id), currentIndex = ids.indexOf(id), targetIndex = distance < 0 ? currentIndex + 1 : currentIndex - 1; if (targetIndex >= 0 && targetIndex < ids.length) openRecipeTab(ids[targetIndex]); else if (distance > 0) history.back(); };
}

function branchLiveTotal(shoppingItems, chainProducts) {
  return shoppingItems.reduce((sum, item) => {
    const product = chainProducts[item.namn];
    if (!product) return sum;
    const pantry = state.pantry[item.namn]?.amount || 0;
    const needed = Math.max(0, item.total - pantry);
    const packages = item.package ? Math.ceil(needed / item.package.amount) : Math.ceil(needed);
    return sum + Number(product.pris_kr) * packages;
  }, 0);
}
let branchComparisonSync = { key: null, chains: new Set() };
async function syncBranchComparison(shoppingItems, branches) {
  const names = shoppingItems.map(item => item.namn).sort();
  const key = `${state.postnummer}|${names.join(",")}`;
  if (branchComparisonSync.key !== key) { branchComparisonSync = { key, chains: new Set() }; state.liveBranchTotals = {}; }
  const chains = [...new Set(branches.map(branch => branch.kedja))].filter(chain => VALID_CHAINS.includes(chain) && !branchComparisonSync.chains.has(chain));
  if (!names.length) return;
  chains.forEach(chain => branchComparisonSync.chains.add(chain));
  // Each chain is fetched independently and in parallel - a slow/timed-out chain (e.g.
  // Coop) must not delay the others from starting or completing.
  await Promise.allSettled(chains.map(async chain => {
    if (branchComparisonSync.key !== key) return;
    try {
      const produkter = await fetchProductsBatch(chain, state.postnummer, names);
      if (branchComparisonSync.key !== key) return;
      const matched = Object.values(produkter).filter(Boolean);
      if (matched.length) { state.liveBranchTotals[chain] = branchLiveTotal(shoppingItems, produkter); state.liveUpdatedAt = Date.now(); renderBasket(); }
    } catch { /* den här kedjan visar kvar den statiska uppskattningen om livehämtningen misslyckas */ }
  }));
}
function renderStoreComparison(selected) {
  const container = $("storeCompare");
  if (!container) return;
  const branches = nearbyBranches();
  if (!selected.length || !branches.length) { container.innerHTML = ""; return; }
  const shoppingItems = aggregateShopping(selected);
  const results = branches.map(branch => {
    const live = state.liveBranchTotals[branch.kedja];
    return { branch, cost: live != null ? live : shoppingListCost(selected, branch), isLive: live != null };
  }).sort((a, b) => a.cost - b.cost);
  const cheapest = results[0], priciest = results[results.length - 1];
  const savings = priciest.cost - cheapest.cost;
  const premium = Boolean(state.user?.premium);
  const listOrUpsell = results.length < 2 ? "" : premium
    ? `<div class="store-compare-list">${results.map(r => `<div class="store-compare-row ${r.branch === cheapest.branch ? "cheapest" : ""}"><span>${r.branch.namn}${r.isLive ? '<span class="live-badge">Live</span>' : '<span class="live-badge estimate">Uppskattat</span>'}</span><strong>${money(r.cost)}</strong></div>`).join("")}</div>`
    : `<button type="button" class="store-compare-upsell" id="storeCompareUpsell">🔒 Prova Premium gratis i 14 dagar och se hela jämförelsen mellan ${results.length} butiker</button>`;
  const anyLive = results.some(r => r.isLive);
  const updatedLabel = anyLive && state.liveUpdatedAt ? `<small class="store-compare-updated">Uppdaterad ${new Date(state.liveUpdatedAt).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" })}</small>` : "";
  container.innerHTML = `<div class="store-compare"><div class="store-compare-head"><span>${cheapest.isLive ? "Lägst pris" : "Lägst uppskattat pris"}</span><strong>${cheapest.branch.namn} · ca ${money(cheapest.cost)}</strong>${savings > 1 ? `<small>${cheapest.isLive ? "Skillnad" : "Uppskattad skillnad"} ${money(savings)} mot ${priciest.branch.namn}</small>` : ""}${updatedLabel}</div>${listOrUpsell}</div>`;
  $("storeCompareUpsell")?.addEventListener("click", openPremiumPitch);
  syncBranchComparison(shoppingItems, branches);
}

const CATEGORY_MAP = { "Frukt & grönt": ["Purjolök", "Morötter", "Lök", "Paprika", "Citron", "Dill", "Basilika", "Lök & vitlök", "Zucchini", "Vitlök", "Timjan", "Sparris", "Rödkål"], Mejeri: ["Grädde", "Riven ost", "Yoghurt", "Mjölk", "Crème fraiche", "Ägg", "Halloumi", "Feta"], "Kött & fisk": ["Kycklinglårfilé", "Kycklingfilé", "Falukorv", "Fryst torsk", "Laxfilé", "Köttfärs", "Fläskfilé", "Biff", "Kalvschnitzel"], Torrvaror: ["Pasta", "Ris", "Matvete", "Äggnudlar", "Vetemjöl", "Röda linser", "Kidneybönor", "Svarta bönor", "Majs", "Krossade tomater", "Tomatpuré", "Salsa", "Soja", "Lasagneplattor", "Kikärtor", "Lingonsylt", "Vegofärs", "Tofu", "Äppelmos", "Kapris"], Frys: ["Wokgrönsaker", "Bär", "Räkor"] };
function itemCategory(name) { return Object.entries(CATEGORY_MAP).find(([, names]) => names.includes(name))?.[0] || "Övrigt"; }
function shoppingItemMarkup(item) { const product = PRODUCT_CATALOG[item.namn] || { namn: item.namn, marke: "", pris: 0 }; const pantry = state.pantry[item.namn]?.amount || 0; const needed = Math.max(0, item.total - pantry); const packages = item.package ? Math.ceil(needed / item.package.amount) : Math.ceil(needed); const amount = packages ? `${packages} × ${item.package?.amount || 1} ${item.package?.unit || item.unit}` : "Finns hemma"; const live = state.livePriser[item.namn]; const priceLabel = live ? `${money(live.pris_kr * (packages || 1))}<span class="live-badge">Live</span>` : product.pris ? money(product.pris * packages) : ""; return `<label class="shopping-item ${state.avklarade.has(item.namn) ? "checked" : ""}"><input type="checkbox" data-shopping="${item.namn}" ${state.avklarade.has(item.namn) ? "checked" : ""}><span class="product-info"><strong>${item.namn}</strong><small>${live ? escapeHtml(live.produktnamn) : product.marke ? `${product.marke} · ` : ""}${live ? "" : amount}</small></span><strong>${priceLabel}</strong></label>`; }
function pantryStep(name) { return PACKAGE_INFO[name]?.unit === "st" ? 1 : 50; }
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
function renderBasket() {
  const selected = [...RECEPT, ...state.apiRecipes].filter((recipe, index, recipes) => state.valda.has(recipe.id) && recipes.findIndex(item => item.id === recipe.id) === index);
  const total = shoppingListCost(selected, selectedBranch()), remaining = budgetRemaining(state.budget, total), shoppingItems = aggregateShopping(selected);
  $("basketCount").textContent = plural(selected.length, "middag", "middagar"); $("weekBudget").textContent = money(state.budget);
  $("basketLines").innerHTML = selected.length ? selected.map((recipe, index) => { const fb = recipeFeedback(recipe.id); return `<article class="basket-line"><div class="basket-line-photo">${recipePhoto(recipe)}</div><span><small>${DAYS[index] || `Dag ${index + 1}`}</small>${recipe.namn}<em>${recipe.tid ? `${recipe.tid} min` : "Tid saknas"}</em></span><strong>${recipe.priceStatus === "unavailable" ? "Pris saknas" : money(scaledPurchasePrice(recipe))}</strong><div class="basket-line-actions"><button type="button" data-details="${recipe.id}">Visa recept</button><button type="button" data-swap="${recipe.id}">Byt rätt</button><button type="button" class="basket-feedback-btn ${fb.cooked ? "marked" : ""}" data-cooked="${recipe.id}" aria-label="Lagade den här" title="Lagade den här">✓</button><button type="button" class="basket-feedback-btn ${fb.skipped ? "marked" : ""}" data-skipped="${recipe.id}" aria-label="Hoppade över" title="Hoppade över">✗</button></div></article>`; }).join("") : `<div class="basket-empty"><strong>Ingen vecka ännu</strong><p>Gå till Hem och skapa din första matvecka.</p></div>`;
  const groups = shoppingItems.reduce((result, item) => { const category = itemCategory(item.namn); (result[category] ||= []).push(item); return result; }, {});
  $("shoppingList").innerHTML = shoppingItems.length ? Object.entries(groups).map(([category, items]) => `<section><h3>${category}<span>${items.length}</span></h3>${items.map(shoppingItemMarkup).join("")}</section>`).join("") : `<div class="pantry-empty"><h2>Listan väntar på din vecka</h2><p>Skapa en meny så samlar vi automatiskt allt du behöver handla.</p></div>`;
  document.querySelectorAll("[data-shopping]").forEach(input => input.addEventListener("change", () => { input.checked ? state.avklarade.add(input.dataset.shopping) : state.avklarade.delete(input.dataset.shopping); saveState(); renderBasket(); }));
  document.querySelectorAll("[data-details]").forEach(button => button.addEventListener("click", () => openRecipeTab(button.dataset.details)));
  document.querySelectorAll("[data-swap]").forEach(button => button.addEventListener("click", () => openSwapModal(button.dataset.swap)));
  document.querySelectorAll("[data-cooked]").forEach(button => button.addEventListener("click", () => { const id = button.dataset.cooked; const fb = state.feedback[id] || {}; state.feedback[id] = { ...fb, cooked: (fb.cooked || 0) + 1 }; saveState(); renderBasket(); }));
  document.querySelectorAll("[data-skipped]").forEach(button => button.addEventListener("click", () => { const id = button.dataset.skipped; const fb = state.feedback[id] || {}; state.feedback[id] = { ...fb, skipped: (fb.skipped || 0) + 1 }; saveState(); renderBasket(); }));
  const completed = shoppingItems.filter(item => state.avklarade.has(item.namn)).length, progress = shoppingItems.length ? completed / shoppingItems.length * 100 : 0;
  const liveCount = shoppingItems.filter(item => state.livePriser[item.namn]).length;
  const updatedSuffix = liveCount && state.liveUpdatedAt ? ` (${new Date(state.liveUpdatedAt).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" })})` : "";
  $("shoppingProgress").textContent = `${completed} av ${shoppingItems.length} varor${liveCount ? ` · ${liveCount} med livepris${updatedSuffix}` : ""}`; $("shoppingCost").textContent = `${money(total)} / ${money(state.budget)}`; $("shoppingProgressBar").style.width = `${progress}%`;
  $("basketTotal").textContent = money(total); $("basketRemaining").textContent = money(Math.abs(remaining)); $("basketRemainingRow").classList.toggle("over-budget", remaining < 0); $("basketRemainingRow").querySelector("span").textContent = remaining < 0 ? "Över budget" : "Kvar";
  renderStoreComparison(selected); renderPantry();
  syncLivePrices(shoppingItems);
}

const VALID_CHAINS = ["ICA", "Willys", "Hemköp", "Coop"];
const LIVE_PRICE_CHUNK_SIZE = 3;
async function fetchProductsBatch(chain, zip, names) {
  // Small SEQUENTIAL requests instead of one big one - each item takes several
  // seconds to scrape, and a single request holding ~10 items easily exceeds a
  // hosting provider's proxy timeout on a cold cache. Sequential (not
  // Promise.all) on purpose: the backend runs headless Chromium per item, and
  // a resource-constrained host chokes if several scrape requests land at
  // once. A chunk that fails just leaves those items unpriced instead of
  // losing the whole batch.
  const chunks = [];
  for (let i = 0; i < names.length; i += LIVE_PRICE_CHUNK_SIZE) chunks.push(names.slice(i, i + LIVE_PRICE_CHUNK_SIZE));
  const produkter = {};
  for (const chunk of chunks) {
    try {
      const response = await fetch(productsBatchApiUrl(), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ butik: chain, zip, varor: chunk }), signal: AbortSignal.timeout(20000) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      Object.assign(produkter, (await response.json()).produkter || {});
    } catch { /* den här biten missade - resten av listan hämtas ändå */ }
  }
  return produkter;
}
let livePriceSync = { key: null, loading: false };
async function syncLivePrices(shoppingItems) {
  const chain = chosenStore();
  const names = shoppingItems.map(item => item.namn).sort();
  const key = `${chain}|${state.postnummer}|${names.join(",")}`;
  if (!names.length || !VALID_CHAINS.includes(chain) || livePriceSync.loading || livePriceSync.key === key) return;
  livePriceSync = { key, loading: true };
  try {
    const produkter = await fetchProductsBatch(chain, state.postnummer, names);
    if (chosenStore() !== chain) return;
    state.livePriser = Object.fromEntries(Object.entries(produkter).filter(([, product]) => product).map(([namn, product]) => [namn, { pris_kr: Number(product.pris_kr) || 0, produktnamn: String(product.produktnamn || namn), url: safeHttpUrl(product.url) }]));
    if (Object.keys(state.livePriser).length) state.liveUpdatedAt = Date.now();
    renderBasket();
  } catch { /* live-priser är ett tillägg ovanpå uppskattningen - misslyckas det visas bara uppskattningen kvar */ }
  finally { livePriceSync.loading = false; }
}
function aggregateShopping(selected) {
  return aggregateIngredients(selected.filter(recipe => recipe.priceStatus !== "unavailable"), RECIPE_QUANTITIES, PACKAGE_INFO, state.personer);
}

function updateSummary() { $("summaryBudget").textContent = money(state.budget); $("summaryPeople").textContent = plural(state.personer, "person", "personer"); $("summaryMeals").textContent = plural(state.middagar, "middag", "middagar"); }
function render() { renderRecipes(); renderBasket(); updateSummary(); renderStats(); }
function step(key, delta, min, max) { state[key] = Math.min(max, Math.max(min, state[key] + delta)); $(`${key === "personer" ? "people" : "meals"}Value`).textContent = state[key]; saveState(); render(); }
function syncSettingsInputs() {
  $("budgetInput").value = state.budget; $("peopleValue").textContent = state.personer; $("mealsValue").textContent = state.middagar; $("storeInput").value = state.butik; $("postcodeInput").value = state.postnummer;
  $("kosttypInput").value = state.kost.kosttyp;
  document.querySelectorAll("#allergenChips input").forEach(box => { box.checked = state.kost.avoidAllergens.has(box.value); });
}
syncSettingsInputs();
$("budgetInput").addEventListener("input", e => { state.budget = clampBudget(e.target.value); saveState(); updateSummary(); renderBasket(); });
const debouncedGeocode = createDebouncedSearch((zip, signal) => fetch(geocodeApiUrl(zip), { signal }).then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); }), 400);
$("postcodeInput").addEventListener("input", e => {
  state.position = null;
  state.postnummer = e.target.value.replace(/\D/g, "");
  state.livePriser = {}; state.liveBranchTotals = {};
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
$("locateBtn").addEventListener("click", () => { if (!navigator.geolocation) return; $("locateBtn").textContent = "Hämtar..."; navigator.geolocation.getCurrentPosition(({ coords }) => { state.position = { lat: coords.latitude, lon: coords.longitude }; state.livePriser = {}; state.liveBranchTotals = {}; $("locateBtn").textContent = "Hittad"; chooseMenu(false); }, () => { $("locateBtn").textContent = "Försök igen"; }); });
$("storeInput").addEventListener("change", e => { state.butik = e.target.value; state.livePriser = {}; saveState(); chooseMenu(); renderCampaignSection(); });

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
    $("liveProducts").innerHTML = state.liveProdukter.length ? `<div class="live-products-head"><span>LIVE FRÅN BUTIKEN</span><strong>${state.liveProdukter.length} produkter</strong></div><div class="live-product-grid">${state.liveProdukter.map(product => `<a class="live-product" href="${product.url}" target="_blank" rel="noopener"><span class="live-product-name">${product.produktnamn}</span><small>${product.marke_och_storlek || "Storlek visas hos butiken"}</small><strong>${product.pris_kr.toLocaleString("sv-SE", { minimumFractionDigits: 2 })} kr</strong></a>`).join("")}</div>` : `<p class="live-loading">Inga liveprodukter hittades.</p>`;
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
  $("profileBtn").classList.toggle("is-premium", Boolean(state.user?.premium));
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
  const premium = Boolean(state.user?.premium);
  $("nutritionLocked").hidden = premium;
  $("nutritionFields").hidden = !premium;
}
let swapContext = null;
function swapOptionMarkup(option, baseTotal) {
  const delta = option.total - baseTotal;
  const deltaLabel = Math.round(delta) === 0 ? "Samma pris för veckan" : `${delta > 0 ? "+" : "−"}${money(Math.abs(delta))} för veckan`;
  return `<button type="button" class="swap-option" data-choose-swap="${escapeHtml(option.candidate.id)}"><div class="basket-line-photo">${recipePhoto(option.candidate)}</div><span><strong>${escapeHtml(option.candidate.namn)}</strong><small>${deltaLabel}</small></span></button>`;
}
const FREE_SWAP_LIMIT = 3;
function openSwapModal(currentId) {
  if (!state.user?.premium && state.swapsThisWeek >= FREE_SWAP_LIMIT) {
    $("swapModalHint").textContent = "";
    $("swapOptions").innerHTML = `<button type="button" class="store-compare-upsell" id="swapUpsell">🔒 Du har använt dina ${FREE_SWAP_LIMIT} gratis byten den här veckan. Prova Premium gratis i 14 dagar för obegränsade byten.</button>`;
    $("swapUpsell").addEventListener("click", () => { closeSwapModal(); openPremiumPitch(); });
    $("swapModal").hidden = false;
    return;
  }
  const selected = [...RECEPT, ...state.apiRecipes].filter((recipe, index, recipes) => state.valda.has(recipe.id) && recipes.findIndex(item => item.id === recipe.id) === index);
  const branch = selectedBranch();
  const baseTotal = shoppingListCost(selected, branch);
  const candidates = candidateRecipesForUser().filter(recipe => !state.valda.has(recipe.id));
  const options = candidates.map(candidate => ({ candidate, total: shoppingListCost(selected.map(recipe => recipe.id === currentId ? candidate : recipe), branch) })).sort((a, b) => a.total - b.total).slice(0, 3);
  if (!options.length) { $("swapOptions").innerHTML = `<p class="live-loading">Inga alternativ hittades som passar budget, butik och dina filter just nu.</p>`; $("swapModal").hidden = false; return; }
  swapContext = { currentId };
  $("swapModalHint").textContent = "Tre förslag som fortfarande passar din budget, butik, allergier och näringsmål.";
  $("swapOptions").innerHTML = options.map(option => swapOptionMarkup(option, baseTotal)).join("");
  document.querySelectorAll("[data-choose-swap]").forEach(button => button.addEventListener("click", () => {
    state.valda.delete(swapContext.currentId);
    state.valda.add(button.dataset.chooseSwap);
    if (!state.user?.premium) state.swapsThisWeek++;
    saveState(); render(); closeSwapModal();
  }));
  $("swapModal").hidden = false;
}
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
  const candidates = candidateRecipesForUser();
  if (!candidates.length) { chooseMenu(); return; }
  const plans = PLAN_TYPES.map(type => { const combo = bestMenuCombo(candidates, state.middagar, state.budget, branch, type.key); return { ...type, combo, cost: shoppingListCost(combo, branch) }; }).filter(plan => plan.combo.length);
  if (plans.length < 2) { chooseMenu(); return; }
  $("planCards").innerHTML = plans.map(plan => planCardMarkup(plan, branch)).join("");
  document.querySelectorAll("[data-choose-plan]").forEach(button => button.addEventListener("click", () => {
    const plan = plans.find(candidate => candidate.key === button.dataset.choosePlan);
    const priciest = priciestBranchFor(plan.combo);
    state.savingsLog.push({ date: new Date().toISOString().slice(0, 10), savings: Math.max(0, (priciest?.cost || plan.cost) - plan.cost), branch: branch?.namn || "", portionCost: plan.cost / (plan.combo.length * state.personer) });
    state.savingsLog = state.savingsLog.slice(-60);
    state.swapsThisWeek = 0;
    state.valda.clear();
    plan.combo.forEach(recipe => state.valda.add(recipe.id));
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
  const selected = [...RECEPT, ...state.apiRecipes].filter((recipe, index, recipes) => state.valda.has(recipe.id) && recipes.findIndex(item => item.id === recipe.id) === index);
  if (!selected.length) return 0;
  const shoppingItems = aggregateShopping(selected);
  return shoppingItems.filter(item => selected.filter(recipe => recipe.ingredienser.includes(item.namn)).length > 1).length;
}
function renderStats() {
  const savedWeek = logEntriesSince(7).reduce((sum, entry) => sum + entry.savings, 0);
  const savedMonth = logEntriesSince(30).reduce((sum, entry) => sum + entry.savings, 0);
  const branchCounts = {};
  state.savingsLog.forEach(entry => { if (entry.branch) branchCounts[entry.branch] = (branchCounts[entry.branch] || 0) + 1; });
  const cheapestName = Object.entries(branchCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || selectedBranch()?.namn || "-";
  const avgPortion = state.savingsLog.length ? state.savingsLog.reduce((sum, entry) => sum + entry.portionCost, 0) / state.savingsLog.length : 0;
  const reused = reusedIngredientCount();
  $("statSavedWeek").textContent = money(savedWeek);
  $("statSavedMonth").textContent = money(savedMonth);
  $("statCheapestStore").textContent = cheapestName;
  $("statAvgPortion").textContent = state.savingsLog.length ? money(avgPortion) : "-";
  $("statWasteReduced").textContent = reused ? `${plural(reused, "ingrediens", "ingredienser")} återanvänds i flera rätter denna vecka` : "Skapa en vecka för att se detta";
  $("savingsCardValue").textContent = state.savingsLog.length ? `${money(savedWeek)} sparat denna vecka` : "Skapa din första vecka";
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
  const premium = Boolean(state.user?.premium);
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
    state.middagar = Math.min(6, Math.max(1, state.middagar + Number(button.dataset.obMeals)));
    saveState(); renderOnboardingStep();
  }));
  $("obKosttyp")?.addEventListener("change", e => { state.kost.kosttyp = e.target.value; saveState(); });
  document.querySelectorAll("#obAllergenChips input").forEach(box => box.addEventListener("change", () => { state.kost.avoidAllergens = new Set([...document.querySelectorAll("#obAllergenChips input:checked")].map(b => b.value)); saveState(); }));
  document.querySelectorAll("#obDislikeChips input").forEach(box => box.addEventListener("change", () => { box.checked ? state.ogillar.add(box.value) : state.ogillar.delete(box.value); saveState(); renderOnboardingStep(); }));
  const customDislike = $("obDislikeCustom");
  customDislike?.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); const value = customDislike.value.trim(); if (value) { state.ogillar.add(value); saveState(); renderOnboardingStep(); } } });
  document.querySelectorAll("[data-ob-remove-dislike]").forEach(button => button.addEventListener("click", () => { state.ogillar.delete(button.dataset.obRemoveDislike); saveState(); renderOnboardingStep(); }));
  $("obMaxTid")?.addEventListener("change", e => { state.maxTid = Number(e.target.value); saveState(); });
  $("obPostcode")?.addEventListener("input", e => { state.postnummer = e.target.value.replace(/\D/g, "").slice(0, 5); saveState(); syncNearbyBranches(); });
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
  if (state.user?.premium && hasActiveNutritionGoals(currentNutritionGoals())) chooseMenu(false);
  renderCampaignSection();
}
const CAMPAIGN_CHAINS = ["Coop", "Hemköp"];
let campaignFetchKey = null;
function campaignDealMarkup(deal) {
  const recipe = RECEPT.find(item => item.ingredienser.includes(deal.ingrediens));
  return `<div class="campaign-deal">${deal.bild ? `<img src="${escapeHtml(deal.bild)}" alt="">` : `<span class="campaign-deal-fallback">🏷️</span>`}<span class="campaign-deal-info"><strong>${escapeHtml(deal.produktnamn)}</strong><small>${escapeHtml(deal.kampanj.text)}${deal.kampanj.ordinariePris ? ` · ord. ${money(deal.kampanj.ordinariePris)}` : ""}</small>${recipe ? `<a class="campaign-deal-recipe" href="#" data-cook-open="${escapeHtml(recipe.id)}">Laga ${escapeHtml(recipe.namn)} med den här →</a>` : ""}</span></div>`;
}
async function renderCampaignSection() {
  const premium = Boolean(state.user?.premium);
  $("campaignLocked").hidden = premium;
  if (!premium) { $("campaignList").innerHTML = ""; return; }
  const chain = chosenStore();
  if (!CAMPAIGN_CHAINS.includes(chain)) {
    $("campaignList").innerHTML = `<p class="live-loading">Kampanjer visas för Coop och Hemköp. Byt butik i "Justera veckan" för att se dem.</p>`;
    return;
  }
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
  } catch {
    campaignFetchKey = null;
    $("campaignList").innerHTML = `<p class="live-loading">Kunde inte hämta kampanjer just nu.</p>`;
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
$("mealsMinus").addEventListener("click", () => step("middagar", -1, 1, 6)); $("mealsPlus").addEventListener("click", () => step("middagar", 1, 1, 6));
$("generateBtn").addEventListener("click", () => openPlanComparison()); $("refreshBtn").addEventListener("click", () => { RECEPT.push(RECEPT.shift()); chooseMenu(); });
let pantryPickLocation = "skafferi";
function renderPantryPicker(query) {
  const search = query.trim().toLowerCase();
  const matches = Object.entries(PRODUCT_CATALOG).filter(([key, product]) => !search || key.toLowerCase().includes(search) || product.namn.toLowerCase().includes(search) || product.marke.toLowerCase().includes(search)).slice(0, 30);
  $("pantryPickerList").innerHTML = matches.length ? matches.map(([key, product]) => `<button type="button" class="pantry-pick" data-pantry-pick="${escapeHtml(key)}"><span class="pantry-pick-info"><strong>${escapeHtml(product.namn)}</strong><small>${escapeHtml(product.marke)} · ${escapeHtml(product.storlek)}</small></span><span class="pantry-pick-add">+ Lägg till</span></button>`).join("") : `<p class="pantry-picker-empty">Inga varor matchar "${escapeHtml(query)}".</p>`;
  document.querySelectorAll("[data-pantry-pick]").forEach(button => button.addEventListener("click", () => openPantryAddConfirm(button.dataset.pantryPick)));
}
function openPantryAddConfirm(key) {
  const product = PRODUCT_CATALOG[key];
  pantryPickLocation = state.pantryTab;
  $("pantryPickerList").hidden = true; $("pantrySearch").hidden = true;
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
  $("pantrySearch").value = ""; $("pantrySearch").hidden = false; $("pantryPickerList").hidden = false; $("pantryAddConfirm").hidden = true;
  renderPantryPicker(""); $("pantryModal").hidden = false; $("pantrySearch").focus();
}
function closePantryModal() { $("pantryModal").hidden = true; }
$("addPantryBtn").addEventListener("click", openPantryModal);
document.querySelectorAll("[data-pantry-close]").forEach(button => button.addEventListener("click", closePantryModal));
document.querySelectorAll("#pantryTabs button").forEach(button => button.addEventListener("click", () => { state.pantryTab = button.dataset.pantryTab; renderPantry(); }));
$("pantrySearch").addEventListener("input", e => renderPantryPicker(e.target.value));

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
