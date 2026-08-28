export function portionFactor(people, basePortions = 4) {
  return Math.max(0.25, Number(people) / basePortions);
}

export function aggregateIngredients(recipes, quantities, packages, people) {
  const totals = {};
  const factor = portionFactor(people);
  recipes.forEach(recipe => recipe.ingredienser.forEach(ingredient => {
    const quantity = quantities[recipe.id]?.[ingredient];
    const amount = (quantity ? quantity[0] : 1) * factor;
    const unit = quantity ? quantity[1] : "st";
    if (!totals[ingredient]) totals[ingredient] = { namn: ingredient, total: 0, unit, package: packages[ingredient] };
    totals[ingredient].total += amount;
  }));
  return Object.values(totals).sort((a, b) => a.namn.localeCompare(b.namn, "sv"));
}

export function calculateShoppingTotal(items, catalog, pantry = {}, priceFactor = 1) {
  return items.reduce((sum, item) => {
    const product = catalog[item.namn];
    if (!product) return sum;
    const needed = Math.max(0, item.total - (Number(pantry[item.namn]) || 0));
    const packageCount = item.package ? Math.ceil(needed / item.package.amount) : Math.ceil(needed);
    return sum + packageCount * product.pris * priceFactor;
  }, 0);
}

export function budgetRemaining(budget, total) {
  return Number(budget) - Number(total);
}

export function clampBudget(value) {
  return Math.max(0, Number(value) || 0);
}
