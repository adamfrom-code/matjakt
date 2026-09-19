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
export function planningContext(state, { premium = false, goals = null, branch = null, objective = "cheapest",
                                         members = null, deriveFromMembers = false } = {}) {
  const hushall = state.hushall || {};
  const feedback = state.feedback || {};
  // S1: bakom flaggan hushall.medlemmar härleds personer ur hushållets
  // medlemmar (slag + portionsfaktor från servern) i stället för ur talet
  // i inställningarna. Utan flagga, eller utan hushåll: som förut.
  const kinds = Array.isArray(members) ? members.map(memberKind) : [];
  const derived = Boolean(deriveFromMembers) && kinds.length > 0;
  const portionSum = derived
    ? members.reduce((sum, m) => sum + (Number.isFinite(Number(m?.portionFactor)) ? Number(m.portionFactor) : 1), 0)
    : 0;
  const adults = derived ? kinds.filter(k => k !== "child").length : Math.max(0, TAL(hushall.vuxna, TAL(state.personer, 2)));
  const children = derived ? kinds.filter(k => k === "child").length : Math.max(0, TAL(hushall.barn, 0));
  return Object.freeze({
    // Personer: dagens enda tal (state.personer, klampat 1-12 i state) -
    // eller, härlett, summan av medlemmarnas portionsfaktorer.
    people: derived ? Math.min(12, Math.max(1, portionSum)) : Math.min(12, Math.max(1, TAL(state.personer, adults + children || 2))),
    peopleSource: derived ? "medlemmar" : "installningar",
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
    // T1: vem äter hemma per dag (null = alla). Läses av planeraren först
    // när prissättningen kan räkna per dag (T2); tills dess en synlig fakta.
    presence: Object.freeze(Array.isArray(state.narvaro) ? [...state.narvaro] : []),
    branch,
    objective: ["cheapest", "balanced", "protein"].includes(objective) ? objective : "cheapest",
    premium: Boolean(premium),
  });
}

/** Medlemmens slag: serverns `kind`, annars härlett ur J3:s `child`. */
export function memberKind(member) {
  const kind = String(member?.kind || "").toLowerCase();
  if (["adult", "child", "guest"].includes(kind)) return kind;
  return member?.profile?.child ? "child" : "adult";
}

/** En läsbar rad för loggar och felrapporter - inga id, bara talen. */
export function describeContext(ctx) {
  return `${ctx.dinners} middagar för ${ctx.people} (${ctx.adults}+${ctx.children}), budget ${ctx.budget} kr, `
    + `${ctx.diet.kosttyp || "ingen kost"}, ${ctx.diet.avoidAllergens.size} allergener, ${ctx.dislikes.size} ogillar, `
    + `${ctx.pantry.length} i skafferiet, ${ctx.history.length} veckor historik, ${ctx.objective}${ctx.goals ? ", näringsmål" : ""}`;
}
