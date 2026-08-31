export function portionFactor(people, basePortions = 4) {
  return Math.max(0.25, Number(people) / basePortions);
}

export function aggregateIngredients(recipes, quantities, packages, people) {
  const totals = {};
  const factor = portionFactor(people);
  recipes.forEach(recipe => {
    // Recipes from the recipe bank carry their own structured ingredients
    // (name, amount, unit, per `servings` portions). Those rows are the
    // truth and are used directly. The `quantities` table is only for the
    // legacy bundled recipes that never had structured data - new recipes
    // were never added to it, which is how a week of bank recipes once
    // aggregated to an EMPTY shopping list.
    const structured = Array.isArray(recipe.ingredients)
      ? recipe.ingredients.filter(item => !item.pantryStaple && !item.optional)
      : [];
    if (structured.length) {
      const scale = people / (recipe.servings || 4);
      structured.forEach(item => {
        const name = item.name;
        const unit = item.unit || "st";
        if (!totals[name]) totals[name] = { namn: name, total: 0, unit, package: packages[name] };
        totals[name].total += (item.amount ?? 1) * scale;
      });
      return;
    }
    recipe.ingredienser.forEach(ingredient => {
      const quantity = quantities[recipe.id]?.[ingredient];
      const amount = (quantity ? quantity[0] : 1) * factor;
      const unit = quantity ? quantity[1] : "st";
      if (!totals[ingredient]) totals[ingredient] = { namn: ingredient, total: 0, unit, package: packages[ingredient] };
      totals[ingredient].total += amount;
    });
  });
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

export function calculateLiveShoppingTotal(items, chainProducts, pantry = {}) {
  // A live-priced product can still have pris_kr === null - a confident
  // match (best_match passed) that simply has no current price from the
  // source. That must never be treated as free/0 and must never enter the
  // total; "matched" (a real product was identified) and "certain" (that AND
  // it has a real, summed price) are tracked separately so a caller can show
  // "8 av 10 varor har säkert pris" instead of a total that quietly excludes
  // items without saying so.
  let cost = 0, matched = 0, certain = 0;
  for (const item of items) {
    const product = chainProducts[item.namn];
    if (!product) continue;
    matched++;
    if (product.pris_kr == null) continue;
    certain++;
    const needed = Math.max(0, item.total - (Number(pantry[item.namn]) || 0));
    const packageCount = item.package ? Math.ceil(needed / item.package.amount) : Math.ceil(needed);
    cost += Number(product.pris_kr) * packageCount;
  }
  return { cost, matched, certain, totalItems: items.length };
}

export function budgetRemaining(budget, total) {
  return Number(budget) - Number(total);
}

export function clampBudget(value) {
  return Math.max(0, Number(value) || 0);
}
