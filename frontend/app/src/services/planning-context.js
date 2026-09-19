// R1 · PLANERINGSKONTEXTEN - allt planeraren vet om hushållet, på ETT ställe.
//
// Roadmapens R: planeraren har hårda filter (kost, allergener, ogillar,
// meal_type) och mjuka poäng (budget, variation, historik, skafferi, betyg)
// - men indatan är utspridd över state.* och läses inne i app.js-funktioner.
// Ingen kan se VAD en vecka byggdes på, och en ny term (vem äter hemma,
// barnandel, rester) hade fått läsa ännu ett hörn av state.
//
// planningContext(state, …) samlar ihop det till ett fryst, rent objekt.
// Den ändrar ingenting: chooseMenu skickar samma tal till bestMenuCombo som
// förut (dinners = state.middagar, budget = state.budget, branch =
// selectedBranch()) - testet i tests/planning-context.test.js bevisar att
// kontexten återger state exakt. Det som är nytt är att nästa paket (S: kind
// per medlem, T: närvaro per dag) får ett fält att sätta i stället för en
// state-läsning att gömma.
//
// Ingen DOM, inget nät: modulen prövas i node.

const TAL = (v, reserv) => (Number.isFinite(Number(v)) && v !== null && v !== "" ? Number(v) : reserv);

/**
 * @param state       appens tillstånd (src/state/app-state.js)
 * @param premium     hasPremium() - näringsmål gäller bara Premium
 * @param goals       currentNutritionGoals() eller null
 * @param branch      selectedBranch() eller null
 * @param objective   "cheapest" | "balanced" | "protein" (veckotypens)
 */
export function planningContext(state, { premium = false, goals = null, branch = null, objective = "cheapest" } = {}) {
  const hushall = state.hushall || {};
  const adults = Math.max(0, TAL(hushall.vuxna, TAL(state.personer, 2)));
  const children = Math.max(0, TAL(hushall.barn, 0));
  const feedback = state.feedback || {};
  return Object.freeze({
    // Personer: dagens enda tal (state.personer, klampat 1-12 i state).
    // adults/children bär hushållsformuläret så att S/T kan härleda i stället.
    people: Math.min(12, Math.max(1, TAL(state.personer, adults + children || 2))),
    adults,
    children,
    dinners: Math.max(1, TAL(state.middagar, 4)),
    budget: Math.max(0, TAL(state.budget, 0)),
    diet: Object.freeze({
      kosttyp: state.kost?.kosttyp || "",
      avoidAllergens: new Set(state.kost?.avoidAllergens || []),
    }),
    dislikes: new Set(state.ogillar || []),
    dislikedIds: new Set(Object.keys(feedback).filter(id => feedback[id]?.disliked)),
    pantry: Object.freeze(Object.keys(state.pantry || {})),
    // De senaste veckorna, nyast först - recentlyEatenPenalty läser samma.
    history: Object.freeze((state.weekHistory || []).slice(0, 4).map(w => Object.freeze([...(w?.plan || [])]))),
    goals: premium && goals ? Object.freeze({ ...goals }) : null,
    branch,
    objective: ["cheapest", "balanced", "protein"].includes(objective) ? objective : "cheapest",
    premium: Boolean(premium),
  });
}

/** En läsbar rad för loggar och felrapporter - inga id, bara talen. */
export function describeContext(ctx) {
  return `${ctx.dinners} middagar för ${ctx.people} (${ctx.adults}+${ctx.children}), budget ${ctx.budget} kr, `
    + `${ctx.diet.kosttyp || "ingen kost"}, ${ctx.diet.avoidAllergens.size} allergener, ${ctx.dislikes.size} ogillar, `
    + `${ctx.pantry.length} i skafferiet, ${ctx.history.length} veckor historik, ${ctx.objective}${ctx.goals ? ", näringsmål" : ""}`;
}
