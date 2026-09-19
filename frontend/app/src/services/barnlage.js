// U1 · BARNLÄGE - när hushållet har barn väger barnvänliga rätter tyngre.
//
// Roadmapens U: etiketten `barn` finns på 83 recept, filtret "Barn" och
// veckotypen Familjevecka använder den - men planeraren i standardveckan
// visste inget om vilka som bor hemma. Nu får varje barnvänlig rätt i en
// kombination en mjuk bonus när hushållet har barn (S1: medlemmarnas slag,
// eller onboardingens barnräknare). Mjuk: ett "gillar" är 3 poäng, en
// barnrätt 1 - barnen tippar valet, de bestämmer inte det. Ingen hård
// spärr, inget som tas bort: familjen kan fortfarande välja vad den vill.
//
// Ren funktion, prövad i node; app.js kopplar in den bakom flaggan
// planering.barn.

export const BARN_BONUS_PER_RATT = 1;

/** Är rätten märkt barnvänlig? Samma regel som Familjevecka-filtret. */
export function arBarnvanlig(recipe) {
  return (Array.isArray(recipe?.tags) && recipe.tags.includes("barn")) || recipe?.typ === "Familjefavorit";
}

/**
 * Bonusen för en kombination. Noll utan barn i hushållet, annars
 * BARN_BONUS_PER_RATT per barnvänlig rätt - oavsett hur många barnen är:
 * ett barn räcker för att rätterna ska spela roll, och tre barn gör inte
 * köttbullar tre gånger viktigare.
 */
export function barnBonus(combo, { children = 0 } = {}) {
  if (!(Number(children) > 0) || !Array.isArray(combo)) return 0;
  return combo.filter(arBarnvanlig).length * BARN_BONUS_PER_RATT;
}
