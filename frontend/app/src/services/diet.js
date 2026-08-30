export const ALLERGENS = ["gluten", "laktos", "nötter", "skaldjur", "fisk", "ägg", "soja"];

export function filterByDiet(recipes, { kosttyp, avoidAllergens } = {}) {
  const avoid = avoidAllergens instanceof Set ? avoidAllergens : new Set(avoidAllergens || []);
  return recipes.filter(recipe => {
    if (kosttyp === "veganskt" && recipe.proteinkalla !== "veganskt") return false;
    if (kosttyp === "vegetariskt" && !["veganskt", "vegetariskt"].includes(recipe.proteinkalla)) return false;
    if (avoid.size && (recipe.allergener || []).some(allergen => avoid.has(allergen))) return false;
    return true;
  });
}
