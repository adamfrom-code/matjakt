/**
 * "Byt rätt" med en ANLEDNING (§16).
 *
 * Förut var alternativen bara sorterade på pris. Nu kan användaren säga
 * varför de vill byta - billigare, snabbare, barnvänligare, mer protein,
 * eller "använd det vi redan har hemma" - och listan sorteras därefter.
 *
 * TVÅ REGLER SOM GÖR DET ÄRLIGT
 *
 * 1. Ett alternativ visas bara under en avsikt om det FAKTISKT är bättre i
 *    den meningen. "Billigare" som listar dyrare rätter är en lögn, och en
 *    tom lista är ett ärligare svar än en påhittad.
 * 2. Vi hittar aldrig på data. En rätt utan tidsuppgift kan inte vara
 *    "snabbare", och en utan proteinvärde kan inte vara "mer protein" -
 *    de faller ur den avsikten i stället för att antas vara medelmåttiga.
 */

export const SWAP_INTENTS = [
  { id: "cheaper", label: "Billigare" },
  { id: "faster", label: "Snabbare" },
  { id: "kids", label: "Barnvänligare" },
  { id: "protein", label: "Mer protein" },
  { id: "pantry", label: "Använd det vi har hemma" },
];

const number = value => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** Hur många av receptets ingredienser hushållet redan har hemma. */
export function pantryOverlap(recipe, pantryNames) {
  if (!pantryNames?.length) return 0;
  const home = new Set(pantryNames.map(name => String(name).toLowerCase()));
  return (recipe.ingredienser || []).filter(name => home.has(String(name).toLowerCase())).length;
}

/**
 * @param {object} current  rätten som ska bytas ut
 * @param {object[]} candidates  möjliga ersättare (redan filtrerade på kost/allergi)
 * @param {string} intent  en av SWAP_INTENTS
 * @param {string[]} pantryNames  vad hushållet har hemma
 */
export function rankSwapOptions(current, candidates, intent, pantryNames = []) {
  const currentPrice = number(current?.portionspris);
  const currentTime = number(current?.tid);
  const scored = candidates.map(candidate => ({
    candidate,
    price: number(candidate.portionspris),
    time: number(candidate.tid),
    protein: number(candidate.protein),
    overlap: pantryOverlap(candidate, pantryNames),
    kidFriendly: Boolean(candidate.taggar?.includes?.("barn")),
  }));

  if (intent === "cheaper") {
    return scored
      .filter(option => option.price != null && (currentPrice == null || option.price < currentPrice))
      .sort((a, b) => a.price - b.price);
  }
  if (intent === "faster") {
    return scored
      .filter(option => option.time != null && (currentTime == null || option.time < currentTime))
      .sort((a, b) => a.time - b.time);
  }
  if (intent === "kids") {
    // Barnvänligt är en EGENSKAP receptet har eller inte har - inte en skala
    // vi räknar fram. Rätter utan taggen listas inte som barnvänligare.
    return scored.filter(option => option.kidFriendly)
      .sort((a, b) => (a.price ?? 9999) - (b.price ?? 9999));
  }
  if (intent === "protein") {
    const currentProtein = number(current?.protein);
    return scored
      .filter(option => option.protein != null && (currentProtein == null || option.protein > currentProtein))
      .sort((a, b) => b.protein - a.protein);
  }
  if (intent === "pantry") {
    return scored.filter(option => option.overlap > 0)
      .sort((a, b) => b.overlap - a.overlap || (a.price ?? 9999) - (b.price ?? 9999));
  }
  // Utan avsikt: billigast först, som förut.
  return scored.sort((a, b) => (a.price ?? 9999) - (b.price ?? 9999));
}

/** Varför just det här alternativet dök upp - en kort rad under namnet. */
export function swapReasonText(option, intent, current) {
  if (intent === "cheaper" && option.price != null && current?.portionspris) {
    return `${Math.round(current.portionspris - option.price)} kr billigare per portion`;
  }
  if (intent === "faster" && option.time != null && current?.tid) {
    return `${current.tid - option.time} minuter snabbare`;
  }
  if (intent === "kids") return "Barnvänlig";
  if (intent === "protein" && option.protein != null) return `${Math.round(option.protein)} g protein`;
  if (intent === "pantry" && option.overlap) {
    return `Använder ${option.overlap} ${option.overlap === 1 ? "vara" : "varor"} ni har hemma`;
  }
  return "";
}

/**
 * VARIATION (§15): rätter familjen nyss ätit ska inte komma tillbaka direkt.
 *
 * Straffet är mjukt och tidsavtagande - en favorit får återkomma, bara inte
 * varje vecka. En hård spärr hade tömt receptbanken för den som lagar samma
 * fem rätter och gillar det.
 */
export function recentlyEatenPenalty(recipeId, weekHistory, favourites = new Set()) {
  const index = (weekHistory || []).findIndex(week => (week.plan || []).includes(recipeId));
  if (index === -1) return 0;
  const base = index === 0 ? 3 : index === 1 ? 2 : 1;
  return favourites.has(recipeId) ? base / 2 : base;
}

/**
 * BUDGETHJÄLP (§18): är veckan dyrare än hushållets vanliga vecka?
 *
 * Bara RIKTIGA totaler räknas. Ett uppskattat pris jämfört med ett riktigt
 * ger ett påhittat "180 kr dyrare", och en falsk besparingssiffra är värre
 * än ingen siffra alls. Under fyra tidigare veckor finns inget "vanligt"
 * att jämföra med, och då säger vi ingenting.
 */
export const BUDGET_ALERT_MIN_WEEKS = 4;
export const BUDGET_ALERT_THRESHOLD_KR = 75;

export function weekCostAlert(currentTotal, history) {
  const totals = (history || [])
    .map(week => (typeof week.total === "number" && week.total > 0 ? week.total : null))
    .filter(total => total != null);
  if (typeof currentTotal !== "number" || !(currentTotal > 0)) return null;
  if (totals.length < BUDGET_ALERT_MIN_WEEKS) return null;
  const usual = totals.reduce((sum, total) => sum + total, 0) / totals.length;
  const difference = currentTotal - usual;
  if (difference < BUDGET_ALERT_THRESHOLD_KR) return null;
  return { usual: Math.round(usual), difference: Math.round(difference) };
}
