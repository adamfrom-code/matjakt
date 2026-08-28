export function hasActiveNutritionGoals(goals) {
  if (!goals) return false;
  const { kcalMin, kcalMax, proteinMin, carbsMin, carbsMax, fatMin, fatMax, proteinSources } = goals;
  return [kcalMin, kcalMax, proteinMin, carbsMin, carbsMax, fatMin, fatMax].some(value => value != null)
    || Boolean(proteinSources && proteinSources.size);
}

export function filterByNutritionGoals(recipes, goals) {
  if (!hasActiveNutritionGoals(goals)) return recipes;
  const { kcalMin, kcalMax, proteinMin, carbsMin, carbsMax, fatMin, fatMax, proteinSources } = goals;
  return recipes.filter(recipe => {
    if (proteinSources && proteinSources.size && !proteinSources.has(recipe.proteinkalla)) return false;
    if (recipe.kcal == null) return false;
    if (kcalMin != null && recipe.kcal < kcalMin) return false;
    if (kcalMax != null && recipe.kcal > kcalMax) return false;
    if (proteinMin != null && recipe.protein < proteinMin) return false;
    if (carbsMin != null && recipe.kolhydrater < carbsMin) return false;
    if (carbsMax != null && recipe.kolhydrater > carbsMax) return false;
    if (fatMin != null && recipe.fett < fatMin) return false;
    if (fatMax != null && recipe.fett > fatMax) return false;
    return true;
  });
}
