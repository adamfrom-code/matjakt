export function comboVariety(combo, key = "proteinkalla") {
  return new Set(combo.map(item => item[key])).size;
}

export function comboProtein(combo) {
  return combo.reduce((sum, item) => sum + (item.protein || 0), 0);
}

export function pickBest(pool, scoreFn) {
  let best = null, bestScore = -Infinity;
  pool.forEach(entry => {
    const score = scoreFn(entry);
    if (!best || score > bestScore || (score === bestScore && entry.cost < best.cost)) { best = entry; bestScore = score; }
  });
  return best;
}

export function inBudgetPool(evaluated, budget) {
  const inBudget = evaluated.filter(entry => entry.cost <= budget);
  return inBudget.length ? inBudget : evaluated;
}

export function pickCheapest(pool, affinityFn = () => 0) {
  return pickBest(pool, entry => -entry.cost + affinityFn(entry.combo) * 3);
}

// "Balanced" prioritizes protein-source variety and rating over raw cost - but only
// among combos that aren't wildly pricier than the cheapest option, so it never
// collapses into "most expensive combo that still fits budget" by accident.
export function pickBalanced(pool, budget, ratingFn = () => 0, affinityFn = () => 0, band_factor = 1.35) {
  const cheapest = pickBest(pool, entry => -entry.cost);
  // An empty pool has no cheapest combo. Reading .cost off null here crashed
  // "Skapa min vecka" outright for a 7-dinner week whose candidates all
  // shared one protein source - see limitCandidatePool's minTotal for why
  // that pool ended up smaller than the week.
  if (!cheapest) return null;
  const band = Math.min(budget, cheapest.cost * band_factor);
  const nearCheapest = pool.filter(entry => entry.cost <= band);
  return pickBest(nearCheapest.length ? nearCheapest : pool, entry => comboVariety(entry.combo) * 20 + ratingFn(entry.combo) * 10 + affinityFn(entry.combo) * 8 - entry.cost * 0.02);
}

export function pickProtein(pool, affinityFn = () => 0) {
  return pickBest(pool, entry => comboProtein(entry.combo) + affinityFn(entry.combo) * 2 - entry.cost * 0.01);
}

// Exhaustive combinations() over the whole candidate pool is fine at a few dozen
// recipes but becomes infeasible as the catalog grows (C(300,4) is ~328 million).
// Cap the search space per generation by keeping the cheapest few recipes from
// EVERY category (not just globally cheapest), so "balanced"/"protein" still have
// real cross-category candidates regardless of how large the recipe catalog gets.
export function limitCandidatePool(recipes, maxPerCategory = 6, maxTotal = 24, key = "proteinkalla", costKey = "inkopspris", minTotal = 0) {
  if (recipes.length <= maxTotal) return recipes;
  const byCategory = {};
  recipes.forEach(recipe => { (byCategory[recipe[key]] ||= []).push(recipe); });
  let picked = [];
  Object.values(byCategory).forEach(group => {
    picked.push(...[...group].sort((a, b) => (a[costKey] || 0) - (b[costKey] || 0)).slice(0, maxPerCategory));
  });
  if (picked.length > maxTotal) picked = picked.sort((a, b) => (a[costKey] || 0) - (b[costKey] || 0)).slice(0, maxTotal);
  // The cap must never starve the week itself. With every candidate sharing
  // one protein source, 6-per-category produced a pool of 6 for a 7-dinner
  // week - C(6,7) is no combos at all, and the planner fell over. Top up
  // with the cheapest of what was cut until the week can at least be filled.
  if (picked.length < minTotal) {
    const chosen = new Set(picked);
    const rest = recipes.filter(recipe => !chosen.has(recipe))
      .sort((a, b) => (a[costKey] || 0) - (b[costKey] || 0));
    picked = [...picked, ...rest.slice(0, minTotal - picked.length)];
  }
  return picked;
}
