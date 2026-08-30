export const PANTRY_LOCATIONS = ["skafferi", "kyl", "frys"];

export function normalizePantryEntry(value) {
  if (value && typeof value === "object") {
    return {
      amount: Math.max(0, Number(value.amount) || 0),
      location: PANTRY_LOCATIONS.includes(value.location) ? value.location : "skafferi",
      expiry: typeof value.expiry === "string" && value.expiry ? value.expiry : null,
    };
  }
  return { amount: Math.max(0, Number(value) || 0), location: "skafferi", expiry: null };
}

export function normalizePantry(pantry) {
  const result = {};
  Object.entries(pantry || {}).forEach(([name, value]) => { result[name] = normalizePantryEntry(value); });
  return result;
}

export function pantryAmounts(pantry) {
  return Object.fromEntries(Object.entries(pantry).map(([name, entry]) => [name, entry.amount]));
}

export function matchLocalRecipesToPantry(recipes, pantryNames, limit = 8) {
  const pantrySet = new Set(pantryNames);
  return recipes
    .map(recipe => ({ recipe, matched: recipe.ingredienser.filter(name => pantrySet.has(name)) }))
    .filter(({ matched }) => matched.length > 0)
    .sort((a, b) => b.matched.length - a.matched.length || b.matched.length / b.recipe.ingredienser.length - a.matched.length / a.recipe.ingredienser.length)
    .slice(0, limit);
}

export function expiryStatus(expiry, today = new Date()) {
  if (!expiry) return null;
  const parsed = new Date(expiry);
  if (Number.isNaN(parsed.getTime())) return null;
  const days = Math.ceil((parsed - today) / 86400000);
  if (days < 0) return "expired";
  if (days <= 3) return "soon";
  return "ok";
}
