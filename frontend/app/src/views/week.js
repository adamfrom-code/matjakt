// Veckans dagar — vilka rader veckolistan faktiskt ritar.
//
// G3: "Veckans plan" var permanent dold (`hidden` i index.html), och den kod
// som ändå körde ritade bara `WEEK_PLAN_PREVIEW_COUNT` = 4 rader bakom en
// "Visa hela veckan"-knapp. Kärnfrågan appen finns för — *vad äter vi i
// veckan* — gick alltså inte att besvara med ögonen, och "✓ Lagad" /
// "✗ Hoppade över" fanns bara i den dolda listan.
//
// weekPlan är dagordnad men bara så lång som antalet middagar: en vecka med
// fyra middagar ger fyra platser, medan dagflikarna alltid ritar sju. De två
// sa alltså olika saker om samma vecka. Funktionen nedan är den enda källan
// till "vilka dagar ritas": sju dagar, alltid, där en dag utan rätt är `null`
// och behåller sin plats i veckan.

/** Veckan har sju dagar. Antalet middagar är något annat — se state.middagar. */
export const WEEK_DAY_COUNT = 7;

/**
 * Dagordnad lista över veckans dagar, alltid `dayCount` lång.
 *
 * @param {Array<object|null>} selected  selectedRecipes(), dagordnad, kan vara kortare än veckan
 * @param {number} dayCount  antal dagar att rita (sju)
 * @returns {Array<object|null>}  en post per dag; `null` = ingen middag planerad
 */
export function weekPlanDays(selected, dayCount = WEEK_DAY_COUNT) {
  const days = Array.isArray(selected) ? selected : [];
  // En vecka som råkar vara LÄNGRE än sju dagar (gammalt sparat läge, en
  // importerad plan) får inte tappa rätter tyst - då hade en rad i listan
  // varit osynlig igen, vilket är precis felet det här paketet lagar.
  const length = Math.max(dayCount, days.length);
  return Array.from({ length }, (_, index) => days[index] ?? null);
}
