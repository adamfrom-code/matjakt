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

// UPPSKATTNINGEN ÄR INTE PRISET, och den får inte ensam förkasta en vecka
// mot användarens riktiga budget (F2).
//
// entry.cost kommer från comboEstimatedCost: receptens separata inköpspriser
// summerade. Det talet har tre kända fel. En förpackning som delas mellan två
// rätter räknas två gånger. Kostnaden skalas linjärt med antal personer fast
// hela förpackningar inte gör det. Och receptens priser kommer från OLIKA
// kedjor (48 Willys, 7 Hemköp, 5 City Gross i banken) men summeras ändå.
//
// MÄTT MOT RIKTIGA PRISER, inte gissat: tolv veckor om fyra rätter för fyra
// personer, uppskattning mot /api/pricing/week. Median +4,6 %, spann
// -12,9 % till +19,5 %. På en budget om 800 kr är det upp till ~160 kr fel
// åt vardera hållet.
//
// Marginalen är satt på den uppmätta överskattningen. Utan den sållades en
// vecka som RYMS bort för att gissningen råkade landa strax över - och den
// veckan fick användaren aldrig se. Med den kan en vecka som inte ryms komma
// med, men då står dess RIKTIGA pris på kortet innan man väljer
// (syncPlanPricing), så ingen luras. Att hellre visa ett dyrare alternativ
// med sant pris än att tyst dölja ett som hade fungerat är rätt håll att
// fela åt.
export const BUDGET_ESTIMATE_MARGIN = 0.2;

export function inBudgetPool(evaluated, budget, margin = BUDGET_ESTIMATE_MARGIN) {
  const tak = budget * (1 + margin);
  const inBudget = evaluated.filter(entry => entry.cost <= tak);
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
export function limitCandidatePool(recipes, maxPerCategory = 6, maxTotal = 24, key = "proteinkalla", costKey = "inkopspris", minTotal = 0, rank = () => 0) {
  if (recipes.length <= maxTotal) return recipes;
  const byCategory = {};
  recipes.forEach(recipe => { (byCategory[recipe[key]] ||= []).push(recipe); });
  // rank före pris: den som anropar kan låta en receptklass (t.ex. enkel
  // vardagsmat) överleva klippet - priset avgör fortfarande inom klassen,
  // och budgetlogiken nedströms räknar på ärliga kostnader precis som förut.
  const order = (a, b) => rank(a) - rank(b) || (a[costKey] || 0) - (b[costKey] || 0);
  let picked = [];
  Object.values(byCategory).forEach(group => {
    picked.push(...[...group].sort(order).slice(0, maxPerCategory));
  });
  if (picked.length > maxTotal) picked = picked.sort(order).slice(0, maxTotal);
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
