// Vad budgeten faktiskt räcker till (U01).
//
// VARFÖR DEN HÄR FINNS. Fältet hette bara "Veckobudget". Det läses rimligen
// som hela veckans mat - frukost, lunch, kaffe, disktabletter - och Matjakt
// planerar bara middagar. Den som skriver in 800 kr för allt och får fyra
// middagar för 800 kr drar slutsatsen att appen är dyr, inte att den
// räknade på något helt annat än man trodde.
//
// ANTALET MIDDAGAR ÄR ANTALET DAGAR - en middag per dag - så texten behöver
// inte säga båda. Att fyra middagar inte täcker sju dagar är hela poängen
// med att skriva ut siffran i stället för att säga "veckan".

export const BUDGET_UTANFOR = "Frukost, lunch och hushållsvaror ingår inte.";

export function budgetOmfattning(middagar, personer) {
  const m = Math.max(0, Number(middagar) || 0);
  const p = Math.max(0, Number(personer) || 0);
  return `${m} ${m === 1 ? "middag" : "middagar"} för ${p} ${p === 1 ? "person" : "personer"}`;
}

export function budgetScopeText(middagar, personer) {
  return `Gäller ${budgetOmfattning(middagar, personer)}. ${BUDGET_UTANFOR}`;
}
