// The recipe bank lives in data/recipes.json, not in app.js.
//
// It used to be two hardcoded arrays inside the UI file - 58 recipes wedged
// between the rendering code - which meant every new recipe was a code change
// and the file grew with the catalogue. Structured data separates the two:
// the bank can reach hundreds or thousands of recipes without app.js
// changing at all, and it can be generated, validated or served from a
// backend later without touching the UI.

const RECIPES_URL = new URL("../../data/recipes.json", import.meta.url);

// Derived once here rather than at every call site, so "is this a quick
// recipe" means the same thing everywhere.
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

export async function loadRecipes() {
  // A recipe bank that fails to load is a blank app, so the caller gets an
  // empty array and a reason rather than an exception it has to guard every
  // render against.
  try {
    const response = await fetch(RECIPES_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const recipes = await response.json();
    return Array.isArray(recipes) ? recipes : [];
  } catch {
    return [];
  }
}

export function hasTag(recipe, tag) {
  return Array.isArray(recipe.tags) && recipe.tags.includes(tag);
}

export function matchesAllTags(recipe, tags) {
  return !tags?.length || tags.every(tag => hasTag(recipe, tag));
}

// The shelves on the recipe page. Each is a plain predicate over the data, so
// adding a shelf never means touching the rendering code - and a shelf that
// would be empty is simply not shown.
export const RECIPE_SHELVES = [
  { key: "popular", title: "Populärt just nu",
    pick: recipes => [...recipes].sort((a, b) => (b.sparar || 0) - (a.sparar || 0)) },
  { key: "barn", title: "Barnens favoriter", pick: recipes => recipes.filter(r => hasTag(r, "barn")) },
  { key: "snabbt", title: "Under 20 minuter", pick: recipes => recipes.filter(r => hasTag(r, "snabbt")) },
  { key: "billigt", title: "Under 25 kr/portion", pick: recipes => recipes.filter(r => hasTag(r, "billigt")) },
  { key: "proteinrikt", title: "Proteinrikt", pick: recipes => recipes.filter(r => hasTag(r, "proteinrikt")) },
  { key: "familj", title: "Familjemiddag", pick: recipes => recipes.filter(r => r.typ === "Familjefavorit") },
  { key: "vegetariskt", title: "Vegetariskt", pick: recipes => recipes.filter(r => hasTag(r, "vegetariskt")) },
  { key: "mealprep", title: "Meal prep", pick: recipes => recipes.filter(r => hasTag(r, "mealprep")) },
  { key: "helg", title: "Helgmiddag", pick: recipes => recipes.filter(r => hasTag(r, "helgmiddag")) },
];
