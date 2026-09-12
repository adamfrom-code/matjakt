// iOS 15 (Capacitors deployment target) saknar AbortSignal.timeout - utan
// polyfillen kastar varje prisanrop TypeError och listan står på "hämtas…".
if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout !== "function") {
  AbortSignal.timeout = ms => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(new DOMException("TimeoutError", "TimeoutError")), ms);
    return controller.signal;
  };
}
import { applySyncBlob, buildSyncPayload, flushServerSync, initAppState, persistLocally, saveState, selectedRecipes, setWeekPlan, state, swapWeekPlanDay } from "./src/state/app-state.js";
import { aggregateShopping, chainListTotal, chainRowAmount, initShoppingView, prunePhantomItemNames, renderBasket, wireReportPriceButtons } from "./src/views/shopping.js";
import { watchOtherTabs } from "./src/state/tab-sync.js";
import { aggregateIngredients, budgetRemaining, calculateShoppingTotal, clampBudget, portionFactor } from "./src/services/calculations.js";
import { branchLiveKey, branchesLoading, clearLocationDerivedState, createRetryGate, initPricingSync, livePricesLoading, pricingHeaders, pricingIsPending, resetExtraMatchSync, resetPricingSync, syncBranchComparison, syncDatabasePricing, syncExtraMatches, syncLivePrices, syncNearbyBranches, storeSelectionForPricing, weekPricingBody } from "./src/pricing/sync.js";
import { createDebouncedSearch, mergeRecipeResults } from "./src/services/recipe-search.js";
import { filterByNutritionGoals, hasActiveNutritionGoals } from "./src/services/nutrition.js";
import { PANTRY_LOCATIONS, expiryStatus, matchLocalRecipesToPantry, pantryAmounts } from "./src/services/pantry.js";
import { extrasTotal, newExtraItem } from "./src/services/extras.js";
import { filterByDiet, mergeDiet } from "./src/services/diet.js";
import { inBudgetPool, limitCandidatePool, pickBalanced, pickCheapest, pickProtein } from "./src/services/planning.js";
import { API_BASE_URL, entitlementsApiUrl, geocodeApiUrl, pricingListApiUrl, pricingWeekApiUrl, productApiUrl as configuredProductApiUrl, recipeSearchApiUrl, recipesByPantryApiUrl } from "./src/api/config.js";
import { setMarketingConsent, changePassword, deleteAccount, fetchAccountState, fetchCurrentUser, getStoredToken, login, logout as logoutRequest, openBillingPortal, redeemPremium, register, requestPasswordReset, resendVerification, resetPassword, saveAccountState, startCheckout, storeToken, verifyEmail } from "./src/api/auth.js";
// errorText: inget rått fetch-fel når skärmen. "Failed to fetch" är inte
// svenska, och en användare kan inte göra något åt ett "HTTP 500" (E7).
import { errorText } from "./src/api/http.js";
import { escapeHtml, safeHttpUrl } from "./src/utils/html.js";
import { closeModal, openModal } from "./src/utils/modal.js";
import { kopplaSvepBort } from "./src/utils/swipe-remove.js";
import { TAG_LABELS, hasTag, loadRecipe, loadRecipes } from "./src/data/recipes.js";
import { PACKAGE_INFO, PRODUCT_CATALOG, RECIPE_DETAILS, RECIPE_QUANTITIES } from "./src/data/legacy-catalog.js";
import { initRecipesView, mapApiRecipe, openRecipeTab, recipeFallbackMarkup, recipePhoto, renderRecipePage, renderRecipes } from "./src/views/recipes.js";
import { weekPlanDays } from "./src/views/week.js";
import { adjustInventory, fetchHousehold, fetchNotifications, joinHousehold, markAtHome, markPurchased, previewInvite, removeInventoryItem, replaceWeekItems, setShoppingStatus, syncHousehold, undoShoppingAction, upsertInventoryItem, upsertShoppingItem } from "./src/api/household.js";
import { ALREADY_HAVE, NEED_TO_BUY, PURCHASED, REMOVED, applyLocalRow, applySync, emptyHouseholdState, foldName, householdDietary, inventoryNames, inventoryRows, pantryAmountsFor, pantryEntriesFor, shoppingKey, shoppingRows } from "./src/services/household-state.js";
import { categoryFor } from "./src/services/categories.js";
import { SWAP_INTENTS, pantryOverlap, rankSwapOptions, recentlyEatenPenalty, swapCostText, swapReasonText, weekCostAlert } from "./src/services/swap.js";
import { recordWeekSaving, weekKeyFor } from "./src/services/savings-log.js";
import { budgetScopeText as budgetScopeFor } from "./src/services/budget-scope.js";
import { planWarning } from "./src/services/plan-warning.js";
import { ASSUMED_STATE, assumedHomeItems, assumedState } from "./src/services/assumed-home.js";
import { takeUrlTokens } from "./src/services/url-tokens.js";
import { branchChoiceKey, canPlanWeek, chooseBranch } from "./src/services/branch-choice.js";
import { createSeededRandom, newSeed } from "./src/services/seeded-random.js";
import { debounce } from "./src/services/debounce.js";
import { closeOnboarding, initAccountView, isAwaitingPremium, openOnboarding, openPaywall, openPremiumPitch, renderAccount, renderHousehold, renderNotificationPrefs, renderWeekPlanUpsell, setAwaitingPremium, wireHouseholdUi } from "./src/views/account.js";
import { delaMånaden, initSparatView, renderSparat, sparatModell } from "./src/views/sparat.js";

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
// TVÅ VYER PÅ SAMMA VECKA, och skillnaden är vilken fråga som ställs.
//
// selectedRecipes() (src/state/app-state.js) svarar "vad står på vilken DAG"
// och har därför en plats per dag i weekPlan - `null` där receptet inte gick
// att slå upp. Allt som numrerar dagar måste läsa den: förr filtrerades de
// tomma platserna bort, och då sköts varje efterföljande dag ett steg, så
// onsdagens rätt märktes "Tis" medan bytesrutan - som indexerar i den
// OFILTRERADE weekPlan - sa något tredje.
//
// plannedRecipes() svarar "vilka rätter finns i veckan" och har ingen
// dagordning att förvalta. Den är det gamla beteendet, ordagrant, och är vad
// aggregat, priser, räkningar och "finns det en vecka alls" ska använda.
const plannedRecipes = () => selectedRecipes().filter(Boolean);
// Den senaste RIKTIGA veckototalen - aldrig ett uppskattat pris. Sätts i
// renderBasket och sparas med veckan när den byts ut, så budgethjälpen
// (§18) har verkliga tal att jämföra mot i stället för gissningar.
let lastRealWeekTotal = null;

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
// Veckoplanen, tillståndet och synken bor numera i
// src/state/app-state.js. Receptbanken, synkstatusraden (DOM) och
// kontovägen skickas in - modulen känner varken till skärmen eller nätet.
initAppState({
  storage: localStorage,
  authToken: getStoredToken(),
  recipeBank: RECEPT,
  onSyncStatus: (status, message) => setSyncStatus(status, message),
  saveRemote: saveAccountState,
  weekTotal: () => lastRealWeekTotal,
});
// Prishämtningen (prisdatabasen, livepriserna, filialjämförelsen,
// extravarorna och butikslistan) bor i src/pricing/sync.js. Den känner inte
// till skärmen: vem som frågar, vilken butik och vilken vecka det gäller
// skickas in, och omritningar beställs via render-bussen. Allt skickas som
// funktioner, inte som värden - de flesta av dem deklareras längre ner i den
// här filen.
initPricingSync({
  hasPremium: () => hasPremium(),
  chosenStore: () => chosenStore(),
  selectedBranch: () => selectedBranch(),
  nearbyBranches: () => nearbyBranches(),
  plannedRecipes: () => plannedRecipes(),
  pantryForPricing: () => pantryForPricing(),
  pantryForServer: () => pantryForServer(),
  isPricedChain: chain => VALID_CHAINS.includes(chain),
  onPricesChanged: () => renderBasket(),
  onLiveStatusChanged: () => updateWeekStoreStatus(),
  onBranchesChanged: () => render(),
  onBranchesLoaded: () => chooseMenu(false),
});
// Sparat / synkar / kunde inte synka - sanningen om var datat är, visad
// diskret i kontovyn. Lokalt sparas ALLTID (localStorage, synkront);
// statusen gäller resan till kontot. Undantaget är en full enhet, och då
// skickar app-state.js med sin egen text: statusen "kunde inte synka" hade
// pekat på nätet när felet satt i telefonen.
function setSyncStatus(status, message = "") {
  const label = $("syncStatusLabel");
  if (!label) return;
  label.textContent = message || (status === "pending" ? "Synkar…"
    : status === "error" ? "Kunde inte synka - försöker igen"
    : state.authToken ? "Allt sparat på ditt konto" : "Sparat på den här enheten");
  label.classList.toggle("sync-error", status === "error");
}
window.addEventListener("pagehide", () => { flushServerSync({ keepalive: true }); });
// E8: en annan flik har skrivit samma blob, och den här flikens minne är
// därmed den gamla veckan. Beskedet - inte en sammanslagning - är hela
// åtgärden; se src/state/tab-sync.js för varför. Remsan ligger kvar tills
// någon trycker: den som missar den tappar sina bockningar tyst.
watchOtherTabs({
  target: window,
  onOtherTab: text => showUndoToast(text, null, () => location.reload(),
                                    { actionLabel: "Ladda om", duration: 0 }),
});
const onboardingIsOpen = () => $("onboardingModal")?.hidden === false;
async function pullAccountState() {
  if (!state.authToken) return;
  // LÄST FÖRE HÄMTNINGEN OCKSÅ, inte bara efter. Att appen kan stå mitt i
  // onboardingen när en blob landar är ingen slump: boot-raden startar
  // refreshUser() utan att vänta in den och öppnar onboardingen i nästa
  // andetag. Och "Skapa min vecka" stänger rutan långt innan ett sent svar
  // kommer - läste vi bara av när blobben landar vore just det ögonblicket
  // oskyddat, och det är det ögonblick veckan skapas i.
  const svaradeVidStart = onboardingIsOpen();
  try {
    const { state: remote } = await fetchAccountState(state.authToken);
    if (remote) {
      if (!applySyncBlob(remote, { onboardingOpen: svaradeVidStart || onboardingIsOpen() })) return;
      persistLocally();
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
  // Bara kassen. En avbockad vara ändrar inget i receptbiblioteket, och att
  // rita om det var hela kostnaden som render-bussen finns för att ta bort.
  invalidate("basket");
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
  invalidate("basket");
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
    invalidate("basket");
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
  invalidate("basket");
}

function undoLastShoppingAction() {
  const undo = lastShoppingUndo;
  lastShoppingUndo = null;
  if (!undo) return;
  if (householdActive()) {
    state.household = applyLocalRow(state.household, "shopping", { key: undo.key, status: undo.status });
    invalidate("basket");
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
  invalidate("basket");
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

// Samma skafferi, men MED enheten - formen som går till prismotorn. Hushållet
// har en enhet per lagerrad; det lokala skafferiet har bara ett antal, och
// skickar därför rena tal precis som förut. Motorn läser båda formerna.
function pantryForServer() {
  return householdActive() ? pantryEntriesFor(state.household) : pantryAmounts(state.pantry);
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
  const items = aggregateShopping(plannedRecipes()).map(item => ({
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
// E9: ETT FRÖ PER "SKAPA VECKA"-TILLFÄLLE.
//
// Slumpen i everydayRank låg i Math.random(), och rankningen kördes om vid
// varje omritning - samma vecka, samma budget, samma butiker kunde ge olika
// svar. Nu dras ett frö när användaren faktiskt ber om en ny vecka, och allt
// som händer inom det tillfället läser samma ström: samma fråga ger samma
// svar, en ny fråga ger en ny vecka. Se src/services/seeded-random.js.
let planRandom = createSeededRandom(newSeed());
function newWeekSeed() { planRandom = createSeededRandom(newSeed()); }
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
    //
    // E9: den kommer ur en SEEDAD ström, inte ur Math.random(). Förut kunde
    // samma indata ge olika svar - i en app vars hela löfte är "vem är
    // billigast" är det en trovärdighetsfråga, inte en smaksak.
    return (tags.includes("vardagsmat") || tags.includes("husmanskost") ? 0 : 10) + planRandom();
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
// SPEGEL av backend/services/accounts/features.py FEATURES. Reservvärdet
// innan /api/entitlements svarat - aldrig en andra affärsmodell.
// test_frontend_contract faller om de två listorna skiljer sig. Uppdaterad
// av J3 (ny paketering): veckotyperna, skafferiet och näringsfiltret ner
// till gratis, hushåll bortom två personer och sparhistoriken upp.
const FREE_FEATURES = {
  standard_week: true, family_week: true, budget_week: true, training_week: true,
  bulk_week: true, quick_week: true, vegetarian_week: true, balanced_week: true,
  seven_dinners: false, cheapest_store_price: true, cheapest_store_basket: true,
  all_store_prices: false, all_store_baskets: false, store_comparison: false,
  live_prices: false,
  recipe_search: true, advanced_nutrition: true, meal_prep: true,
  basic_pantry: true, full_pantry: true, favorites: true,
  household_sharing: false, savings_history: false,
};
const FREE_ENTITLEMENTS = { plan: "free", isPremium: false, maxDinners: 5, features: FREE_FEATURES, pricing: null };
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
    resetPricingSync();
    state.dbChainTotals = {}; state.dbLockedChains = []; state.dbComparison = null;
    state.dbPricedAt = null; state.extraMatches = {}; resetExtraMatchSync();
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
// clearLocationDerivedState() och syncNearbyBranches() bor i
// src/pricing/sync.js tillsammans med resten av prishämtningen - de delar
// synkgrindarna med den, och butikshämtningen har samma omförsöksbehov som
// prishämtningen (E13).
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
// E9: BUTIKSVALET BYGGER INTE LÄNGRE EN VECKOPLAN PER BUTIK.
//
// cheapestBranch() körde en fullständig kombinationssökning för VARJE
// närbutik - 30-40k kombinationer per filial, 300-400k med tio - plus en
// shoppingListCost per resultat. Allt det arbetet slängdes: veckoplanen
// användes till ett `total` ingen läste och till frågan "går det att bygga
// en vecka alls?", som är samma svar för varje filial. Sorteringen som
// faktiskt avgjorde vilken butik det blev var avståndet, i båda grenarna.
//
// Kvar här är bara att plocka ihop appens tillstånd till modulens indata.
// Själva valet - och nyckeln som säger när det behöver göras om - bor i
// src/services/branch-choice.js, där det går att prova utan webbläsare.
function branchChoiceInput() {
  return {
    branches: nearbyBranches(),
    // "auto" är inte en kedja utan frånvaron av ett kedjeval.
    chain: state.butik === "auto" ? null : state.butik,
    position: state.position,
    distanceTo: branch => (state.position
      ? distanceKm(state.position.lat, state.position.lon, branch.lat, branch.lon) : null),
    premium: hasPremium(),
    cheapestChain: state.dbComparison?.cheapestChain || null,
    // Enda kvarvarande beroendet till receptbanken: utan recept finns ingen
    // vecka att handla till, och då ingen butik att visa. Precis som förut,
    // när noll kandidater tömde filiallistan.
    hasMenu: canPlanWeek(candidateRecipesForUser().length, state.middagar),
    pinned: state.pinnedBranch,
  };
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
  // Nyckeln bärs av exakt det valet beror på, och state.budget är inte
  // längre en av dem: budgetfältet kan därför inte trigga ett omval.
  const input = branchChoiceInput();
  const key = branchChoiceKey(input);
  if (branchCache.key !== key) branchCache = { key, value: pinnedBranchMatch() || chooseBranch(input) };
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
  // Ett nytt frö = en ny vecka. Utan det här anropet hade seedningen gjort
  // "Skapa ny vecka" till en knapp som gav samma vecka varje gång.
  newWeekSeed();
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
      invalidate("recipes");
    }));
}

const FAVORITE_ICON = '<svg viewBox="0 0 24 24"><path d="M12 21s-7-4.6-9.5-9C.7 8.2 2.4 5 5.7 5c2 0 3.4 1.1 4.3 2.4C11 6.1 12.4 5 14.4 5c3.3 0 5 3.2 3.2 7-2.5 4.4-9.5 9-9.5 9Z"/></svg>';
const PRICE_TAG_ICON = '<svg viewBox="0 0 24 24"><path d="M20 12 12.5 4.5a2 2 0 0 0-1.4-.5H5a1 1 0 0 0-1 1v6.1a2 2 0 0 0 .6 1.4L12 20"/><circle cx="8" cy="8" r="1.3"/></svg>';

// Prisdatabasen, filialjämförelsen och deras synkgrindar bor i
// src/pricing/sync.js: syncBranchComparison, syncDatabasePricing,
// pricingHeaders, storeSelectionForPricing och weekPricingBody importeras
// därifrån. Omförsöken efter nätfel går genom modulens omförsöksgrind i
// stället för en egen setTimeout-kedja per fel (E5).

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
// Själva hämtningen (syncExtraMatches) bor i src/pricing/sync.js.

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
  const inList = aggregateShopping(plannedRecipes()).some(item => item.namn.toLowerCase() === foldName)
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
  state.extraMatches = {}; resetExtraMatchSync();
  saveState(); renderBasket();
  return extra;
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
  $("storeCardsCompareBtn")?.addEventListener("click", () => { renderStoreComparisonPage(plannedRecipes()); setView("comparison"); });
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

// Butiksvalet returnerar ett NYTT objekt ({...branch, avstandKm}), så en
// identitetskontroll mot en rads egen butik aldrig matchade och
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
    // chain that would just be a guess (see shoppingListCost's flat estimate),
    // and showing it as fact is exactly the kind of mismatch users have reported.
    // Show only the price at the store actually in use, plainly labeled.
    const current = results.find(r => sameBranch(r.branch, selectedBranch())) || results[0];
    // A flat estimate is never printed as a store price. While the real
    // fetch is still under way the head says so; if it came back empty the
    // head says that instead. A made-up "ca 512 kr" says neither.
    const stillFetching = pricingIsPending() || (!state.dbPricedAt && !state.dbPricingFailedAt);
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
  const headFetching = headIsEstimate && (pricingIsPending() || (!state.dbPricedAt && !state.dbPricingFailedAt));
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
  const selected = plannedRecipes();
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
    // Knappen skapas här och binds här - en nod, en lyssnare. Låg bindningen
    // kvar i veckoöversikten fick samma knapp en lyssnare till vid varje
    // omritning av Handla, och ett klick skickade N händelser i stället för en.
    wireReportPriceButtons(body, { onReport: () => trackEvent("prisfel_rapporterat") });
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
  //
  // Löftet var tomt förr. Rubriken lade ihop item.totalCost i fullt flyttal
  // och rundade summan EN gång, medan varje rad rundades för sig - tjugo
  // rader à 12,49 kr gav "250 kr" över tjugo rader som alla läser "12 kr".
  // chainListTotal summerar de tal raderna faktiskt skriver ut, i öre.
  const total = chainListTotal(data.items);
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
  // SUMMAN SOM GOLV. Rubriksiffran presenterades som exakt medan de osäkra
  // radernas kostnad tyst utelämnades - tre msk-rader (honung, olivolja,
  // tomatpuré) bidrog med noll kronor, och användaren budgeterade 640 och
  // betalade 700. Golvet kommer från servern (totalIsFloor), så klienten
  // inte härleder en andra sanning: så fort någon rad saknar radtotal är
  // talet en undre gräns, aldrig kassans belopp.
  const floor = !!data.totalIsFloor;
  const totalLabel = floor ? "Kassakostnad, minst" : "Total kassakostnad";
  const stickyTotal = floor ? `minst ${money(total)}` : money(total);
  const uncertainNote = data.uncertainRows
    ? `<span>+ ${data.uncertainRows} ${data.uncertainRows === 1 ? "vara" : "varor"} utan säkert antal</span>` : "";
  const sticky = `<div class="chain-list-sticky"><strong>${escapeHtml(storeName)}</strong><span>${stickyTotal} · ${data.realPriceItems}/${data.totalItems} varor</span></div>`;
  const head = sticky + `<div class="chain-list-head"><h2>${escapeHtml(storeName)}</h2><small>${escapeHtml([data.chain, distance].filter(Boolean).join(" · "))}</small>${pricedElsewhere}<div class="chain-list-total"><span>${totalLabel}</span><strong>${money(total)}</strong></div><div class="chain-list-meta"><span>${data.realPriceItems} av ${data.totalItems} varor har pris</span>${uncertainNote}${data.missingItems ? `<span>${data.missingItems} utan pris</span>` : ""}<span>${escapeHtml(updated)}</span><button type="button" class="report-price-btn" data-report-price>Ser något fel ut?</button>${savings}</div>${warning}</div>`;

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
      // Samma chainRowAmount som rubriken summerar - raden och headern kan
      // inte avrunda olika när de läser beloppet ur samma funktion.
      : `<strong>${money(chainRowAmount(item))}</strong>${perUnit}${onCampaign
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
// Var varan rimligen hör hemma. Härlett ur kategorin vi redan har - inte
// gissat per vara, och aldrig något användaren inte kan flytta efteråt.
const CATEGORY_TO_LOCATION = { Mejeri: "kyl", "Kött & fisk": "kyl", Frys: "frys" };
function suggestedLocationFor(name) {
  return CATEGORY_TO_LOCATION[categoryFor(name, databaseItemFor(name)?.category)] || "skafferi";
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
// G3: veckolistan har ingen förhandsvisning längre. Den VAR fyra rader bakom
// en "Visa hela veckan"-knapp, i en sektion som dessutom var `hidden` - två
// lager mellan användaren och det enda hon öppnade appen för. Antalet rader
// bestäms nu av weekPlanDays() i src/views/week.js: sju, alltid.
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
  // En dag utan rätt behåller sin plats i listan. Att hoppa över den sköt
  // varje senare dag ett steg uppåt, så torsdagens rätt stod på onsdagen -
  // samma namn, fel dag, och ingen väg tillbaka till den tomma dagen.
  // Samma klasser som en vanlig rad, så inga nya stilregler behövs: dagen, en
  // tom bildruta och texten i samma tre spalter.
  if (!recipe) {
    return `<div class="week-plan-row is-empty ${index === weekOverviewDay ? "active" : ""}">
      <span class="week-plan-row-main">
        <span class="week-plan-day">${DAYS[index] || `Dag ${index + 1}`}</span>
        <span class="week-plan-photo"></span>
        <span class="week-plan-name">Ingen middag inplanerad</span>
      </span>
      <button type="button" class="week-plan-swap-btn" data-week-add-meal>+ Lägg till</button>
    </div>`;
  }
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
  // Listan är dagordnad och kan ha tomma dagar; sammanfattningen räknar
  // rätter. "4 middagar" ska vara fyra rätter, inte fyra platser i veckan.
  const planned = selected.filter(Boolean);
  const favourites = planned.filter(recipe =>
    state.favoriter.has(recipe.id) || (state.betyg[recipe.id] || 0) >= 4 || state.feedback[recipe.id]?.liked).length;
  const home = pantryForPricing();
  const atHome = shoppingItems.filter(item => (home[item.namn] || 0) > 0).length;
  const onCampaign = shoppingItems.filter(item => {
    const match = databaseItemFor(item.namn);
    return match && match.campaignPrice != null && match.regularPrice != null
      && match.campaignPrice < match.regularPrice;
  }).length;
  return { dinners: planned.length, favourites, fresh: planned.length - favourites, atHome, onCampaign, total };
}

function renderWeekSummary(selected, shoppingItems, total) {
  const box = $("weekSummary");
  if (!box) return;
  const harRatter = selected.some(Boolean);
  box.hidden = !harRatter;
  if (!harRatter) return;
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

  // G3: HELA veckan, i en lista som syns utan att någon klickar. Sju rader -
  // weekPlan är bara så lång som antalet middagar, medan dagflikarna ovanför
  // alltid ritar sju dagar, så en vecka med fyra middagar sa två olika saker
  // om samma vecka. En dag utan rätt är en rad som säger just det, med en
  // väg tillbaka till den ("+ Lägg till").
  $("weekPlanList").innerHTML = weekPlanDays(selected).map(weekPlanRowMarkup).join("");

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
  const nothingPlanned = !selected.some(Boolean);
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
  // "Ser något fel ut?" binds INTE här. Knappen finns bara i kedjelistan och
  // ritas aldrig om av den här funktionen - men den här funktionen körs vid
  // varje livepris, varje synksvar och varje avbockning, så bindningen
  // staplade en lyssnare till på samma nod varje gång och ett klick skickade
  // till slut N prisfel_rapporterat. Bindningen sitter i
  // openChainShoppingList, där knappen faktiskt skapas.
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
  const items = assumedHomeItems(plannedRecipes());
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
    const priciest = plannedRecipes().filter(recipe => recipe.portionspris)
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

function updateWeekStoreStatus() {
  const selected = plannedRecipes();
  if (!selected.length) { $("weekStoreStatus").textContent = ""; return; }
  const shoppingItems = aggregateShopping(selected);
  const liveCount = shoppingItems.filter(item => state.livePriser[item.namn]).length;
  const chain = chosenStore();
  const fetchingLive = livePricesLoading();
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
const RELEASED_CHAINS = ["Willys", "Hemköp", "City Gross", "ICA"];
const VALID_CHAINS = RELEASED_CHAINS;

// ---------------------------------------------------------------------------
// HANDLA-VYN FÅR SITT OMVÄRLDSBEROENDE
//
// src/views/shopping.js äger inköpslistan - aggregatet, raderna, knapparna,
// extravarorna. Den känner varken till prissättningen, butiksvalet eller
// hushållet; allt sådant skickas in här, under de namn app.js själv använder,
// så varje flyttad rad står ordagrant kvar i modulen.
//
// Står EFTER VALID_CHAINS med flit: allt nedan som är en const (money,
// plural, itemCategory, PANTRY_TAB_LABELS, VALID_CHAINS) måste vara
// deklarerat innan det går att skicka vidare. Det som byts ut under körningen
// (prishämtningens synkgrindar, lastRealWeekTotal) skickas som funktioner,
// aldrig som värden - annars fryses det första värdet fast. Grindarna bor
// numera i src/pricing/sync.js och frågas via pricingIsPending och
// livePricesLoading.
// ---------------------------------------------------------------------------
initShoppingView({
  $, money, plural,
  categoryIconMarkup, itemCategory, itemStatus, setItemStatus,
  databaseItemFor, pantryForPricing,
  suggestedLocationFor, pantryTabLabels: PANTRY_TAB_LABELS,
  showUndoToast, undoLastShoppingAction,
  trackEvent, noteStaplePurchase, removeShoppingItem,
  removedRowsForView, restoreRemovedRows,
  householdActive,
  chosenStore, currentPricedChain, headerPricedChain, validChains: VALID_CHAINS,
  pricingPending: pricingIsPending,
  livePricesLoading,
  nearbyBranches, computeStoreResults, sameBranch, selectedBranch, hasUsablePrice,
  extrasTotalForChain, syncExtraMatches,
  ensureWeekRecipeDetails,
  renderWeekCostAlert, renderStaplePrompt, renderAssumedHome, renderAttribution,
  renderStoreComparison, renderStoreCards, renderPantry, renderWeekStoreTabs,
  updateWeekStoreStatus, renderWeekOverview,
  syncLivePrices, pushWeekToHousehold,
  setLastRealWeekTotal: value => { lastRealWeekTotal = value; },
  recipeQuantities: RECIPE_QUANTITIES, packageInfo: PACKAGE_INFO,
});

// G5: krysset satt i tumzonen, intill "Köpt" - ett feltryck tog bort varan.
// Svep vänster tar bort raden i stället, med Ångra i toasten. Lyssnaren sitter på
// behållaren, inte på raderna, så den överlever varje omritning av listan.
kopplaSvepBort($("shoppingList"), {
  väljRad: mål => mål?.closest?.("[data-remove-item]")
    ? null                                   // krysset är sin egen väg, inte ett svep
    : mål?.closest?.(".shopping-item"),
  taBort: rad => {
    const namn = rad.querySelector("[data-remove-item]")?.dataset.removeItem;
    if (namn) removeShoppingItem(namn);
  },
});

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
// fetchProductsBatch, mapLiveProducts och syncLivePrices - hämtningen av
// livepriser hos den valda kedjan, med sin gruppstorlek och sin cooldown
// efter 429/403 - bor i src/pricing/sync.js.
// The chosen week's recipes need their STRUCTURED ingredients (a card
// deliberately ships without them) before the shopping list can render its
// lines. Fetched once per recipe, in the background; each arrival re-renders.
const recipeDetailFetches = new Set();
// Hur många receptdetaljer som är i luften just nu. Mängden ovan säger bara
// att ett id har FRÅGATS efter (ett 404 stannar kvar i den för alltid); den
// här räknaren säger när veckan är så laddad den kommer att bli.
let recipeDetailsInFlight = 0;
function ensureWeekRecipeDetails() {
  plannedRecipes().forEach(recipe => {
    if (Array.isArray(recipe.ingredients) && recipe.ingredients.length) return;
    if (recipe.priceStatus === "unavailable") return; // provider-recept har inget att hämta
    if (recipeDetailFetches.has(recipe.id)) return;
    recipeDetailFetches.add(recipe.id);
    recipeDetailsInFlight += 1;
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
    }).finally(() => {
      recipeDetailsInFlight -= 1;
      if (!recipeDetailsInFlight) settleWeekRecipeDetails();
    });
  });
  // Ingenting på väg: veckans recept är färdigladdade redan när vi kommer hit
  // (allt har strukturerade ingredienser, eller är recept vi aldrig hämtar).
  if (!recipeDetailsInFlight) settleWeekRecipeDetails();
}

// DET ENDA STÄLLE SOM BESKÄR SPÖKNAMN.
//
// Beskärningen låg förr inuti aggregateShopping() - en funktion som ser ut
// som en ren beräkning, anropas från ett halvdussin ställen mitt under
// rendering, och raderade ur removedItems/avklarade/harHemma utan att spara.
// Värst av allt gjorde den det på ett ofullständigt aggregat: så fort
// receptdetaljerna landade föll de valfria ingredienserna ur aggregatet
// (aggregateIngredients filtrerar optional; kortprojektionen gör det inte)
// och användarens "köpt" på dem raderades tyst.
//
// Nu körs beskärningen här, en gång per färdigladdad vecka, mot unionen av
// allt veckan kan be om - och det den raderar sparas.
function settleWeekRecipeDetails() {
  if (!prunePhantomItemNames(plannedRecipes())) return;
  saveState();
  invalidate("basket");
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
  invalidate("basket");
  showUndoToast(`${name} borttagen`, () => {
    state.removedItems.delete(name);
    // I hushållet är REMOVED serverns status - ångra måste också gå dit,
    // annars ligger raden osynlig kvar utan väg tillbaka.
    if (householdActive()) setHouseholdStatus(name, NEED_TO_BUY, REMOVED);
    clearPriceSnapshots();
    saveState();
    invalidate("basket");
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
  invalidate("basket");
}

// En enda toast åt gången: en ny borttagning ersätter den förra i stället
// för att stapla remsor över navigeringen.
let undoToastTimer = null;
function showUndoToast(message, onUndo, onOpen = null, options = {}) {
  const toast = $("undoToast");
  toast.querySelector("span").textContent = message;
  toast.hidden = false;
  const button = toast.querySelector("button");
  // Samma remsa, två roller: "Ångra" efter en egen ändring, "Öppna" när det
  // är en notis om något NÅGON ANNAN gjort. Att ångra någon annans ändring
  // vore fel knapp på fel handling. En anropare med en TREDJE handling
  // ("Ladda om" när en annan flik skrivit) säger det i options.actionLabel.
  const action = onUndo || onOpen;
  button.textContent = options.actionLabel || (onUndo ? "Ångra" : "Öppna");
  button.hidden = !action;
  button.onclick = () => { clearTimeout(undoToastTimer); toast.hidden = true; if (action) action(); };
  clearTimeout(undoToastTimer);
  // duration 0 = remsan ligger kvar tills någon trycker. En kvittens ska
  // försvinna av sig själv; ett besked man MÅSTE se innan nästa ändring
  // ska inte hinna tona bort medan telefonen ligger i fickan.
  if (options.duration !== 0) undoToastTimer = setTimeout(() => { toast.hidden = true; }, options.duration || 6000);
}

// U01: budgeten måste säga VAD den räcker till - se src/services/budget-scope.js.
function budgetScopeText() { return budgetScopeFor(state.middagar, state.personer); }

function updateSummary() {
  const hasWeek = plannedRecipes().length > 0;
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
// ---------------------------------------------------------------------------
// RENDER-BUSSEN
//
// render() körde alla sju renderarna vid VARJE interaktion. Att bocka av en
// vara i Handla rev därför ner och byggde upp hela receptbiblioteket - 200+
// kort med bilder - och band om varenda lyssnare, för att en kryssruta i en
// annan vy ändrat färg.
//
// Nu säger anroparen vad som blivit inaktuellt i stället för att beordra en
// omritning: invalidate("basket") märker en bana smutsig, bussen samlar
// ihop allt som hunnit märkas till NÄSTA bildruta och kör bara de banorna.
// Tio anrop under samma bildruta blir alltså en omritning, inte tio.
//
//   basket   - veckan, inköpslistan, skafferiet och deras siffror
//   recipes  - receptbiblioteket, hyllorna och förslagsraden på Hem
//   account  - hälsningen (den enda av de sju som läser state.user)
//
// RENDER_STEPS är render()s gamla ordning, oförändrad. Ett steg som körs får
// alltid sina föregångare i samma inbördes ordning som förut - det är
// därför listan är en ordnad tabell och inte ett uppslag per bana.
// F-paketen kan flytta ut funktionerna härifrån till egna moduler utan att
// röra en enda anropsplats: anroparen känner bara banans namn.
const RENDER_STEPS = [
  ["account", renderGreeting],
  ["recipes", renderRecipes],
  ["recipes", renderHemRecipePreview],
  ["basket", renderBasket],
  // G8-raden ovanför veckan ("Vill du ha en familjevecka i stället?") syns
  // först när det FINNS en vecka att jämföra med - alltså samma bana som
  // veckan själv.
  ["basket", renderWeekPlanUpsell],
  ["basket", updateSummary],
  // renderStats hör till kassen, inte till kontot: clearPriceSnapshots()
  // nollar state.dbComparison vid varje avbockning, och sparkortet läser
  // just den.
  ["basket", renderStats],
  ["basket", renderCampaignSection],
];
const dirtyRenderLanes = new Set();
let renderFrame = null;
function invalidate(...lanes) {
  lanes.forEach(lane => dirtyRenderLanes.add(lane));
  if (renderFrame !== null) return;
  // setTimeout som reserv: requestAnimationFrame saknas i miljöer utan
  // fönster, och en utebliven omritning är värre än en bildruta för sent.
  renderFrame = typeof requestAnimationFrame === "function"
    ? requestAnimationFrame(flushRender)
    : setTimeout(flushRender, 0);
}
function flushRender() {
  renderFrame = null;
  const lanes = new Set(dirtyRenderLanes);
  dirtyRenderLanes.clear();
  RENDER_STEPS.forEach(([lane, step]) => { if (lanes.has(lane)) step(); });
}
// "Allt är inaktuellt". Varje anropsplats som inte vet bättre beter sig
// exakt som förut - bara samlad till en bildruta i stället för direkt.
function render() { invalidate("account", "recipes", "basket"); }
// Receptvyn (F4) ritar banan "recipes". Den känner inte app.js - allt den
// behöver av butiker, priser, premium och navigering skickas in här, en
// gång. Raden står EFTER render-bussen med flit: recipeDetailFetches och
// formatterarna ovan måste vara deklarerade när objektet byggs.
initRecipesView({
  recipeBank: RECEPT,
  recipeDetailFetches,
  invalidate,
  render,
  money,
  plural,
  macroLine,
  detailsFor,
  availableRecipes,
  localRecipesForUser,
  dietFilterIsActive,
  selectedBranch,
  nearbyBranches,
  // branchesSync bor i src/pricing/sync.js sedan F1 - receptvyn frågar
  // modulen i stället för en modulvariabel som inte längre finns här.
  branchesLoading,
  hasPremium,
  scaledPurchasePrice,
  renderRecipeTagFilters,
  recipeRatingMarkup,
  feedbackMarkup,
  wireRatingStars,
  wireFeedbackButtons,
  trackEvent,
  showUndoToast,
  setView,
});
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
// E9: budgetfältets lyssnare körde hela omräkningen vid VARJE tangenttryck -
// och innan butiksvalet gjordes om bar cache-nyckeln state.budget, så varje
// tecken drog igång en kombinationssökning per närbutik. Talet syns direkt i
// fältet; det är bara räkningen som väntar 250 ms på att skrivandet ska ta
// slut. Lämnas fältet (change fyras vid blur, alltså före varje knapptryck
// någon annanstans) gäller det sista värdet omedelbart.
const applyBudget = value => { state.budget = clampBudget(value); saveState(); updateSummary(); renderBasket(); };
const budgetTyped = debounce(applyBudget, 250);
$("budgetInput").addEventListener("input", e => budgetTyped(e.target.value));
$("budgetInput").addEventListener("change", e => budgetTyped.flush(e.target.value));
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

// G6: samma lager som alla andra ark. Här fokuseras textrutan i stället för
// rubriken - skärmen har EN uppgift och den är att skriva - men fokusfällan,
// Escape och återlämnandet av fokus är gemensamma.
function openFeedbackSheet() {
  $("feedbackStatus").textContent = "";
  openModal($("feedbackSheet"), { onClose: closeFeedbackSheet, focus: false });
  $("feedbackText").focus();
}
function closeFeedbackSheet() { closeModal($("feedbackSheet")); }
$("feedbackBtn").addEventListener("click", openFeedbackSheet);
$("feedbackClose").addEventListener("click", closeFeedbackSheet);
$("feedbackSheet").addEventListener("click", event => { if (event.target === $("feedbackSheet")) closeFeedbackSheet(); });
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
    setTimeout(closeFeedbackSheet, 1400);
  } catch {
    $("feedbackStatus").textContent = "Gick inte att skicka just nu - försök igen.";
  } finally {
    $("feedbackSend").disabled = false;
  }
});

function openWeekSheet() {
  $("restoreWeekBtn").hidden = !(state.weekHistory || []).length;
  openModal($("weekSheet"), { onClose: closeWeekSheet });
}
function closeWeekSheet() { closeModal($("weekSheet")); }
$("budgetCardBtn").addEventListener("click", openWeekSheet);
$("weekSheetOpen").addEventListener("click", openWeekSheet);
$("weekSheetClose").addEventListener("click", closeWeekSheet);
$("weekSheetDone").addEventListener("click", closeWeekSheet);
$("weekSheet").addEventListener("click", event => { if (event.target === $("weekSheet")) closeWeekSheet(); });
// G6: den gamla, ENDA Escape-lyssnaren i hela appen stod här och kunde bara
// stänga veckoarket. Escape bor numera i openModal() och stänger det översta
// lagret, vilket det än är - inklusive onboardingmodalen, som inte gick att
// stänga med tangentbord alls.
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
let premiumPollInFlight = false;
async function activatePremiumAfterCheckout() {
  // Bara en poll åt gången: i native-appen kan visibilitychange komma
  // flera gånger medan vi redan väntar på Stripes webhook.
  if (premiumPollInFlight) return;
  premiumPollInFlight = true;
  try { await pollPremiumAfterCheckout(); } finally { premiumPollInFlight = false; }
}
async function pollPremiumAfterCheckout() {
  setAwaitingPremium(true);
  openAccountModal();
  renderAccount();
  for (let attempt = 0; attempt < 15; attempt++) {
    await refreshUser();
    // hasPremium() är den enda vägen till premiumflaggan (se tests/premium.test.js);
    // på loopback kortsluter dev-luckan pollen, vilket är ofarligt där.
    if (hasPremium()) break;
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  setAwaitingPremium(false);
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
// HUSHÅLLET: NOTISER, DJUPLÄNKAR OCH INBJUDNINGSLANDNINGEN
//
// Panelen, medlemslistan och inbjudningsflödet bor i src/views/account.js.
// Kvar här står det som hänger ihop med appens övriga delar: notisutkorgen,
// djuplänkarna, sessionsstädningen och skafferiet som följer med in i ett
// nytt hushåll.
// ---------------------------------------------------------------------------

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
    openModal($("inviteLanding"));
    $("inviteLandingTitle").textContent = "Inbjudan gäller inte längre";
    $("inviteLandingBody").textContent = "Be den som bjöd in dig att skicka en ny länk.";
    $("inviteJoinBtn").hidden = true;
    return;
  }
  // G6: inbjudningslandningen är ett modalt lager som alla andra. Den öppnas
  // av en LÄNK, inte av en knapp i appen, så det finns ingen öppnare att ge
  // fokus tillbaka till - men fällan och Escape gäller ändå.
  openModal($("inviteLanding"));
  $("inviteLandingTitle").textContent = `${preview.invitedBy || "Någon"} har bjudit in dig till ${preview.householdName}`;
  $("inviteLandingBody").textContent = state.authToken
    ? "Ni delar veckan, inköpslistan och skafferiet."
    : "Logga in eller skapa ett konto så är du med.";
  $("inviteJoinBtn").querySelector("span").textContent = state.authToken ? `Gå med i ${preview.householdName}` : "Logga in och gå med";
  $("inviteJoinBtn").onclick = async () => {
    if (!state.authToken) { closeModal($("inviteLanding")); openAccountModal(); return; }
    $("inviteLandingError").textContent = "";
    try {
      const { household } = await joinHousehold(state.authToken, pendingInviteToken);
      state.household = applySync(emptyHouseholdState(), { household, revision: 0 });
      await pullHousehold(true);
      startHouseholdSync();
      clearInviteFromUrl();
      closeModal($("inviteLanding"));
      renderHousehold();
      loadNotifications();
      render();
      setView("week");
    } catch (error) {
      $("inviteLandingError").textContent = errorText(error);
    }
  };
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
    openModal($("swapModal"), { onClose: closeSwapModal });
    return;
  }
  // Dagordnad, med tomma dagar kvar som null: dayIndex kommer ur den
  // OFILTRERADE weekPlan, och de två indexrymderna måste vara samma.
  const selected = selectedRecipes();
  const dayIndex = state.weekPlan.indexOf(currentId);
  const branch = selectedBranch();
  const candidates = candidateRecipesForUser().filter(recipe => !state.valda.has(recipe.id));
  // Sorteras på kandidatens RIKTIGA portionspris (databasprissatt vid
  // import). shoppingListCost gick via statiska PRODUCT_CATALOG som inte
  // känner bankreceptens ingredienser - varje kandidat kostade ~samma och
  // "billigast först" blev slumpartad.
  const current = selected.find(recipe => recipe?.id === currentId);
  const allOptions = swapOptionsFor(current, candidates, "");
  if (!allOptions.length) { $("swapModalHint").textContent = ""; $("swapOptions").innerHTML = `<p class="live-loading">Inga alternativ hittades som passar budget, butik och dina filter just nu.</p>`; $("swapConfirmBtn").hidden = true; $("swapShowMoreBtn").hidden = true; openModal($("swapModal"), { onClose: closeSwapModal }); return; }
  swapContext = { currentId, dayIndex, current, candidates, intent: "", allOptions, visibleCount: SWAP_OPTIONS_BATCH, selectedId: null };
  renderSwapModal();
  openModal($("swapModal"), { onClose: closeSwapModal });
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
  const currentRecipe = selectedRecipes().find(recipe => recipe?.id === currentId);
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
function closeSwapModal() { closeModal($("swapModal")); swapContext = null; }
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
        body: JSON.stringify({ recipeIds, people: state.personer, pantry: pantryForServer(),
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
  // Samma tillfälle, ett frö: de sju veckotyperna nedan drar ur samma ström
  // och korten går därför att räkna fram igen exakt som de visades.
  newWeekSeed();
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
  openModal($("planModal"), { onClose: closePlanModal });
}
function closePlanModal() { closeModal($("planModal")); }
document.querySelectorAll("[data-plan-close]").forEach(button => button.addEventListener("click", closePlanModal));

// L5: veckan som ligger planerad NU, som två räknade tal. Båda är `null` när
// de inte GÅR att räkna - ingen vecka planerad, eller inga priser hämtade än.
// Noll kampanjvaror och "vi vet inte om det finns kampanjvaror" är två olika
// svar, och Sparat skriver ut skillnaden i stället för att gissa en nolla.
function veckansNyckeltal() {
  const selected = plannedRecipes();
  if (!selected.length) return { middagar: null, kampanjvaror: null };
  const shoppingItems = aggregateShopping(selected);
  const prissatt = shoppingItems.some(item => databaseItemFor(item.namn));
  return {
    middagar: selected.length,
    kampanjvaror: prissatt ? weekSummaryFacts(selected, shoppingItems, null).onCampaign : null,
  };
}
function renderStats() {
  renderSparat(sparatModell(state.savingsLog, { vecka: veckansNyckeltal() }));
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
    $("savingsCardSubtitle").textContent = plannedRecipes().length
      ? "Kan inte beräknas ännu – kräver två jämförbara butiker"
      : "Skapa din första vecka för att se detta";
  }
}
$("openStatsBtn").addEventListener("click", () => { renderStats(); setView("stats"); });
$("homeShoppingStat").addEventListener("click", () => setView("basket"));
initSparatView({ $ });
// "Dela din månad" delar tills vidare meningen som ren text. H4 gör samma
// mening till en 1080x1080-bild; knappen byter väg då, inte plats.
$("sparatShareBtn").addEventListener("click", () => { delaMånaden(); });

function openAccountModal() { openModal($("accountModal"), { onClose: closeAccountModal }); }
function closeAccountModal() { closeModal($("accountModal")); $("loginError").textContent = ""; $("registerError").textContent = ""; $("redeemError").textContent = ""; $("forgotError").textContent = ""; $("resetError").textContent = ""; $("deleteError").textContent = ""; }
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
  return errorText(error);
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
  } catch (error) { $("resetError").textContent = errorText(error); }
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
  } catch (error) { $("deleteError").textContent = errorText(error); }
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
// Hämtad, pågående eller avvaktande. Det var en sträng ("done") som nollades
// vid fel, och eftersom render-bussen körs vid varje interaktion sköt nästa
// rendering iväg ett nytt /grocery/campaigns-anrop - ett per knapptryck,
// ovanpå en exponentiell omförsökskedja som aldrig avbröts (E5). Grinden
// nedan håller takten i stället: ETT försök per backoff-period, EN väntande
// timer.
let ownCampaignFetch = { done: false, inFlight: false };
const ownCampaignsRetry = createRetryGate(() => renderOwnCampaigns());
let ownCampaignDeals = [];
async function renderOwnCampaigns() {
  if (ownCampaignFetch.done || ownCampaignFetch.inFlight) return;
  if (!ownCampaignsRetry.ready()) return;
  ownCampaignFetch.inFlight = true;
  // Ett lugnt laddläge - utan det står rubriken över en tom rad i upp till
  // 15 sekunder innan hämtningen svarar.
  $("campaignList").innerHTML = `<p class="live-loading">Hämtar veckans fynd…</p>`;
  try {
    const response = await fetch(`${API_BASE_URL}/grocery/campaigns`, { signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    ownCampaignFetch.done = true;
    ownCampaignsRetry.succeeded();
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
    $("campaignList").innerHTML = `<p class="live-loading">Kunde inte hämta erbjudanden just nu - försöker igen strax.</p>`;
    // Utan egen omstart låg felet kvar tills någon annan render råkade ske.
    // Grinden avbryter den förra väntande timern innan den sätter en ny, så
    // tio fel ger tio försök i följd - inte tio parallella kedjor.
    ownCampaignsRetry.failed();
  } finally {
    ownCampaignFetch.inFlight = false;
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
    closeModal($("inviteLanding"));
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
  // Knappen var aldrig avstängd under anropet: på ett segt nät tryckte
  // användaren igen, och igen, och startade en ny inloggning per tryck (E6).
  const submit = event.target.querySelector('button[type="submit"]');
  if (submit) submit.disabled = true;
  try {
    const { token, user } = await login($("loginEmail").value, $("loginPassword").value);
    state.authToken = token; state.user = user; storeToken(token);
    await pullAccountState();
    event.target.reset(); renderAccount(); closeAccountModal();
    await resumePendingInvite();
  } catch (error) { $("loginError").textContent = errorText(error); }
  finally { if (submit) submit.disabled = false; }
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
  } catch (error) { $("registerError").textContent = errorText(error); }
});
$("accountRedeemForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("redeemError").textContent = "";
  try {
    const { user } = await redeemPremium(state.authToken, $("premiumCode").value);
    state.user = user; renderAccount(); event.target.reset(); chooseMenu(false); renderCampaignSection();
  } catch (error) { $("redeemError").textContent = errorText(error); }
});
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
    if (isNativeApp()) setAwaitingPremium(true);
    openExternal(url);
  } catch (error) { $("checkoutError").textContent = errorText(error); }
});
$("manageBillingBtn").addEventListener("click", async () => {
  $("portalError").textContent = "";
  try {
    await flushServerSync();
    const { url } = await openBillingPortal(state.authToken);
    openExternal(url);
  } catch (error) { $("portalError").textContent = errorText(error); }
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
  if (plannedRecipes().length) setView("week");
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
  renderPantryPicker(""); $("pantryLiveResults").innerHTML = "";
  // Sökrutan är skärmens enda uppgift, så fokus går dit i stället för till
  // rubriken - men fällan, Escape och fokusåterlämningen är gemensamma.
  openModal($("pantryModal"), { onClose: closePantryModal, focus: false });
  $("pantrySearch").focus();
}
function closePantryModal() { closeModal($("pantryModal")); }
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
  openModal($("cookModal"), { onClose: closeCookModal });
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
function closeCookModal() { closeModal($("cookModal")); }
$("cookFromPantryBtn").addEventListener("click", openCookModal);
document.querySelectorAll("[data-cook-close]").forEach(button => button.addEventListener("click", closeCookModal));
restoreNutritionGoalsForm();
// Kontovyn (kontoarket, hushållet, onboardingen, paywallen) bor i
// src/views/account.js och får här sin koppling till resten av appen - en
// gång, före första renderingen. Modulen ritar DOM och känner inte till
// priser, recept eller vyer; allt sådant går genom de här funktionerna.
initAccountView({
  $,
  hasPremium, premiumPricing, withdrawalConsentMarkup, withdrawalConsentGiven,
  syncSettingsInputs, renderPriceTabs,
  householdActive, pullHousehold, pushWeekToHousehold, pushPantryToHousehold,
  startHouseholdSync, loadNotifications, clearInviteFromUrl,
  // lastWeekPushKey är app.js egen debounce-nyckel. Ett nytt hushåll ska få
  // veckan skickad även om exakt samma lista redan gått iväg en gång.
  resetWeekPushKey: () => { lastWeekPushKey = null; },
  openAccountModal, openPlanComparison, chooseMenu, setView,
  syncNearbyBranches, clearLocationDerivedState, storeOptionsMarkup,
  budgetScopeText, maxDinners, maxMeals: () => MAX_MEALS,
  isNativeApp, openExternal, plural, render, trackEvent,
});
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
  if (isAwaitingPremium() && isNativeApp()) activatePremiumAfterCheckout();
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
