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

const FALLBACK_URL = new URL("../../data/recipes.json", import.meta.url);

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
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

/** Every recipe, for the week planner - which genuinely needs the whole set
 *  to build combinations from. Falls back to the bundled JSON so a backend
 *  outage leaves the app usable rather than empty. */
export async function loadRecipes() {
  try {
    const data = await getJson("/recipes?limit=200");
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
export async function loadRecipe(id) {
  try {
    const data = await getJson(`/recipes/${encodeURIComponent(id)}`);
    return data.recipe ? fromApi(data.recipe) : null;
  } catch {
    return null;
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
    typ: recipe.categories?.[0] ?? recipe.typ,
    kosttyp: recipe.dietFlags?.[0] ?? recipe.kosttyp,
    tags: recipe.tags ?? [],
    // The week planner needs ingredient NAMES; the pricing engine gets the
    // structured version straight from the backend.
    ingredienser: recipe.ingredienser
      ?? (recipe.ingredients || []).filter(i => !i.pantryStaple).map(i => i.name),
    hemma: recipe.hemma
      ?? (recipe.ingredients || []).filter(i => i.pantryStaple).map(i => i.name),
  };
}

export function hasTag(recipe, tag) {
  return Array.isArray(recipe.tags) && recipe.tags.includes(tag);
}

export function matchesAllTags(recipe, tags) {
  return !tags?.length || tags.every(tag => hasTag(recipe, tag));
}
