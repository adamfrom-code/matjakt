// The recipe bank comes from Matjakt's own backend, not from this file.
//
// It was two hardcoded arrays inside app.js, then a static JSON file. Both
// worked at 58 recipes and neither scales: a phone should not download the
// whole catalogue to draw ten cards, and filtering thousands of recipes in
// JavaScript is work the database does better.
//
// So the app asks for what the screen needs. Shelves come in ONE request
// (the recipe page draws them together; nine requests on a phone is nine
// chances to be slow), a filtered list is a query, and the full recipe -
// ingredients and steps - is fetched only when someone opens one.
//
// The static JSON stays as a FALLBACK, not as the source. If the backend is
// unreachable the app still has recipes to show, which matters more than
// being pure about where they came from.

import { API_BASE_URL } from "../api/config.js";

// Relativt SIDAN, inte modulen: efter esbuild-bygget är import.meta.url
// bundelns adress (app/app.js) och "../../data" skulle peka fel.
const FALLBACK_URL = typeof document !== "undefined"
  ? new URL("data/recipes.json", document.baseURI)
  : new URL("../../data/recipes.json", import.meta.url);

// The filter row on the recipe page. Kept here rather than in the markup so
// "proteinrikt" means the same thing in the filter, the shelf and the
// backend query.
export const TAG_LABELS = {
  snabbt: "Under 20 minuter",
  billigt: "Under 25 kr/portion",
  proteinrikt: "Proteinrikt",
  vegetariskt: "Vegetariskt",
  veganskt: "Veganskt",
  fisk: "Fisk",
  kyckling: "Kyckling",
  kott: "Kött",
  barn: "Barn",
  mealprep: "Meal prep",
  helgmiddag: "Helgmiddag",
};

async function getJson(path, { timeout = 12000 } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    signal: AbortSignal.timeout(timeout),
  });
  // Statuskoden följer med: en 404 är ett SVAR ("finns inte") medan ett
  // nätfel eller en 500 är ett uteblivet svar. Anroparen måste kunna skilja
  // dem åt för att veta om det är någon idé att försöka igen.
  if (!response.ok) throw Object.assign(new Error(`HTTP ${response.status}`), { status: response.status });
  return response.json();
}

/** Every recipe, for the week planner - which genuinely needs the whole set
 *  to build combinations from. Falls back to the bundled JSON so a backend
 *  outage leaves the app usable rather than empty. */
export async function loadRecipes() {
  try {
    const data = await getJson("/recipes?limit=500");
    if (Array.isArray(data.recipes) && data.recipes.length) return data.recipes.map(fromApi);
  } catch {
    // fall through to the bundled copy
  }
  try {
    const response = await fetch(FALLBACK_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const recipes = await response.json();
    return Array.isArray(recipes) ? recipes : [];
  } catch {
    return [];
  }
}

/** The recipe page's shelves, in one request. Returns [] on failure so the
 *  page renders its other content instead of breaking. */
export async function loadShelves(perShelf = 12) {
  try {
    const data = await getJson(`/recipes/shelves?perShelf=${perShelf}`);
    return (data.shelves || []).map(shelf => ({
      ...shelf, recipes: shelf.recipes.map(fromApi),
    }));
  } catch {
    return [];
  }
}

/** A filtered list. tags are ANDed - "barn" plus "snabbt" means both, which
 *  is what a row of filter toggles means to the person using it. */
export async function searchRecipes({ tags = [], maxTime, minProtein, maxKcal, query, limit = 60 } = {}) {
  const params = new URLSearchParams();
  if (tags.length) params.set("tag", tags.join(","));
  if (maxTime) params.set("maxTime", maxTime);
  if (minProtein) params.set("minProtein", minProtein);
  if (maxKcal) params.set("maxKcal", maxKcal);
  if (query) params.set("q", query);
  params.set("limit", limit);
  try {
    const data = await getJson(`/recipes?${params}`);
    return (data.recipes || []).map(fromApi);
  } catch {
    return [];
  }
}

/** One full recipe, with ingredients and steps. Only this call returns
 *  everything, because only the detail screen needs it. */
/**
 * Ett recept, eller null när det BEVISLIGEN inte finns.
 *
 * null betyder "backend säger att receptet inte finns" - ett definitivt
 * svar det inte är någon idé att fråga om igen. Allt annat (nätfel, 500,
 * timeout) kastas vidare, för då vet vi ingenting och ett omförsök är
 * rimligt. Tidigare svaldes båda och blev null, vilket gjorde ett
 * permanent 404 omöjligt att skilja från en tillfällig störning - och
 * anroparen försökte då om i evighet på varje omritning.
 */
export async function loadRecipe(id) {
  try {
    const data = await getJson(`/recipes/${encodeURIComponent(id)}`);
    return data.recipe ? fromApi(data.recipe) : null;
  } catch (error) {
    if (error?.status === 404) return null;
    throw error;
  }
}

// The backend speaks the recipe model; the app still speaks Swedish field
// names throughout its rendering. Translating here, once, is far less
// disruptive than renaming every use site - and keeps the API free to be
// the clean model it should be.
function fromApi(recipe) {
  return {
    ...recipe,
    namn: recipe.name ?? recipe.namn,
    bild: recipe.image ?? recipe.bild,
    tid: recipe.totalTime ?? recipe.tid,
    portioner: recipe.servings ?? recipe.portioner,
    kcal: recipe.nutrition?.kcal ?? recipe.kcal,
    protein: recipe.nutrition?.protein ?? recipe.protein,
    kolhydrater: recipe.nutrition?.carbs ?? recipe.kolhydrater,
    fett: recipe.nutrition?.fat ?? recipe.fett,
    allergener: recipe.allergens ?? recipe.allergener ?? [],
    // Vad rätten är till för. Följer med listprojektionen från backenden och
    // är det enda veckoplaneraren behöver för att kunna säga nej till en
    // frukost. Fältet heter likadant i båda världarna, så det översätts inte
    // - men det tas heller inte bort av en `...recipe`-spridning som råkar
    // sakna det, eftersom ett saknat värde betyder "aldrig middag".
    mealType: recipe.mealType ?? null,
    typ: recipe.categories?.[0] ?? recipe.typ,
    kosttyp: recipe.dietFlags?.[0] ?? recipe.kosttyp,
    tags: recipe.tags ?? [],
    // The week planner needs ingredient NAMES; the pricing engine gets the
    // structured version straight from the backend.
    ingredienser: recipe.ingredienser
      ?? ((recipe.ingredients || []).length
        ? (recipe.ingredients || []).filter(i => !i.pantryStaple).map(i => i.name)
        // Listprojektionen bär ingredientNames (bara namn) - utan dem såg
        // "Laga med det jag har" aldrig ett enda bankrecept.
        : (recipe.ingredientNames || [])),
    hemma: recipe.hemma
      ?? (recipe.ingredients || []).filter(i => i.pantryStaple).map(i => i.name),
    // A REAL portion price, computed by the backend's pricing run against
    // collected store prices - or null, which the UI must show as "pris
    // saknas". Never a hand-typed figure.
    portionspris: recipe.pricePerPortion ?? recipe.portionspris ?? null,
    // The planner's budget maths run on a whole-recipe cost at the standard
    // 4-portion base (portionFactor scales from there). Derived from the
    // same real portion price; legacy bundled recipes carry their own.
    inkopspris: recipe.pricePerPortion != null
      ? Math.round(recipe.pricePerPortion * 4 * 10) / 10
      : recipe.inkopspris ?? null,
    priceChain: recipe.priceChain ?? null,
    // Protein-source variety drives the "Balanserad vecka". The bank
    // expresses it as tags; the planner wants one word.
    proteinkalla: recipe.proteinkalla ?? proteinSourceFromTags(recipe.tags ?? []),
  };
}

function proteinSourceFromTags(tags) {
  if (tags.includes("kyckling")) return "kyckling";
  if (tags.includes("fisk")) return "fisk";
  if (tags.includes("kott")) return "kött";
  // Exakta värden, inte samlingsordet "vego": kosttypfiltret jämför mot
  // "veganskt"/"vegetariskt", och med "vego" här fick en vegetarian en TOM
  // receptlista - varje bankrecept föll bort.
  if (tags.includes("veganskt")) return "veganskt";
  if (tags.includes("vegetariskt")) return "vegetariskt";
  return "övrigt";
}

export function hasTag(recipe, tag) {
  return Array.isArray(recipe.tags) && recipe.tags.includes(tag);
}

export function matchesAllTags(recipe, tags) {
  return !tags?.length || tags.every(tag => hasTag(recipe, tag));
}
