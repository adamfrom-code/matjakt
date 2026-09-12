// VAD EN RÄTT ÄR TILL FÖR — och varför veckoplaneraren måste fråga.
//
// Fram till M1 sa ingenting i receptbanken vad ett recept var till för.
// Veckoplaneraren valde alltså bland allt den hade, och att risgrynsgröt inte
// hamnade i middagsveckan oftare var tur, inte konstruktion.
//
// Värdeförrådet är STÄNGT och speglar backendens
// `backend/services/recipes/meal_types.py`. Två listor som ska vara lika är
// alltid en risk; den hålls ihop av ett test som läser båda filerna, inte av
// att någon kommer ihåg.
//
// FILTRET ÄR ETT LIKHETSVILLKOR, INTE "middag eller okänt". Ett recept utan
// klassificering faller bort tillsammans med frukostarna. Det är rätt håll
// att fela åt: den som lägger till ett recept och glömmer fältet får det inte
// föreslaget, i stället för att få det serverat som middag på en tisdag.

export const DINNER = "middag";
export const MEAL_TYPES = [DINNER, "frukost", "lunch", "efterratt", "tillbehor"];

/** Rättens måltidstyp, oavsett om den kom från API:t eller reservbanken. */
export function mealTypeOf(recipe) {
  return recipe?.mealType ?? recipe?.meal_type ?? null;
}

export function isDinner(recipe) {
  return mealTypeOf(recipe) === DINNER;
}

/**
 * Allt veckoplaneraren FÅR välja bland — och ingenting annat.
 *
 * Enda vägen in i en veckoplan. Att den ligger i en egen modul i stället för
 * som en `.filter()` på anropsstället är hela poängen: ett villkor som bor på
 * ett ställe går att pröva utan webbläsare, och nästa väg som bygger en vecka
 * (byten, planjämförelsen, söndagsnotisen) kan inte råka utelämna det.
 */
export function dinnerCandidates(recipes) {
  return (recipes || []).filter(isDinner);
}
