export const ALLERGENS = ["gluten", "laktos", "nötter", "jordnötter", "sesam", "skaldjur", "fisk", "ägg", "soja"];

// Banken skrevs under en period med två ord för samma sak. Datat är numera
// normaliserat vid import, men filtret förlåter ändå synonymer - ett recept
// som säger "mjölk" ska ALDRIG passera ett laktos-filter för att orden
// skiljer. Allergifiltrering är säkerhetskritisk: hellre dubbelt skydd.
const ALLERGEN_SYNONYMS = {
  laktos: ["laktos", "mjölk"],
  skaldjur: ["skaldjur", "blötdjur"],
  nötter: ["nötter", "hasselnötter", "valnötter", "mandel", "cashewnötter"],
};

export function filterByDiet(recipes, { kosttyp, avoidAllergens } = {}) {
  const avoid = avoidAllergens instanceof Set ? avoidAllergens : new Set(avoidAllergens || []);
  const avoidExpanded = new Set();
  for (const allergen of avoid) {
    for (const synonym of ALLERGEN_SYNONYMS[allergen] || [allergen]) avoidExpanded.add(synonym);
  }
  return recipes.filter(recipe => {
    if (kosttyp === "veganskt" && recipe.proteinkalla !== "veganskt") return false;
    if (kosttyp === "vegetariskt" && !["veganskt", "vegetariskt"].includes(recipe.proteinkalla)) return false;
    if (avoidExpanded.size && (recipe.allergener || []).some(allergen => avoidExpanded.has(allergen))) return false;
    return true;
  });
}

/**
 * Enhetens egen kostinställning PLUS hushållets allergier.
 *
 * Familjen fyller i allergier per medlem (Konto → Hushåll). De uppgifterna
 * sparades men användes inte av något - Sara kunde skriva "nötter" och ändå
 * få nöträtter föreslagna. Allergi är säkerhet, så de slås ihop: det någon
 * vid bordet inte tål gäller hela veckan.
 *
 * Kosttypen slås INTE ihop. Att en i hushållet är vegetarian gör inte hela
 * familjens vecka vegetarisk - det är ett val, inte en medicinsk gräns.
 * Fritexten normaliseras (gemener, trimmad); ord som inte finns i ALLERGENS
 * följer med ändå och matchas mot receptens egna allergenord.
 */
export function mergeDiet(kost = {}, dietary = {}) {
  const merged = new Set(kost.avoidAllergens instanceof Set
    ? kost.avoidAllergens
    : (kost.avoidAllergens || []));
  (dietary.allergies || []).forEach(value => {
    const clean = String(value || "").trim().toLowerCase();
    if (clean) merged.add(clean);
  });
  return { kosttyp: kost.kosttyp || "", avoidAllergens: merged };
}

