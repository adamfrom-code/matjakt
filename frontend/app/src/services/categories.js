/**
 * Butiksordning för inköpslistan (§31).
 *
 * Ordningen är den man faktiskt går i en svensk matbutik: frukt och grönt
 * först, frysen sist, hushåll allra sist. Poängen är att slippa gå fram och
 * tillbaka - inte att sortera alfabetiskt.
 *
 * TVÅ KÄLLOR, I DEN HÄR ORDNINGEN:
 *   1. INGREDIENSNAMNET. Receptens ingredienser är en känd, ändlig lista och
 *      vi vet var de hör hemma.
 *   2. PRODUKTENS EGEN KATEGORISÖKVÄG från kedjan (match.category). Den finns
 *      bara när en riktig produkt matchats, och den är kedjans egen indelning
 *      - "Mejeri, ost & ägg/Mjölk & grädde".
 * Träffar ingen av dem hamnar varan under Övrigt, som ritas sist. Vi hittar
 * INTE på en hylla åt en vara vi inte känner igen.
 */

export const CATEGORY_ORDER = [
  "Frukt & grönt", "Bröd", "Mejeri", "Kött & fisk", "Skafferi", "Frys", "Övrigt",
];

// Ingrediensnamn -> hylla. Listan är den som funnits i Handla sedan tidigare,
// flyttad hit så att både listan och skafferiet läser samma sanning.
const NAMES = {
  "Frukt & grönt": ["Purjolök", "Morötter", "Lök", "Paprika", "Citron", "Dill", "Basilika",
    "Lök & vitlök", "Zucchini", "Vitlök", "Timjan", "Sparris", "Rödkål", "Potatis", "Banan",
    "Persilja", "Tomat", "Gurka", "Sallad", "Avokado", "Äpple", "Broccoli", "Blomkål",
    "Champinjoner", "Ingefära", "Chili", "Vitkål", "Isbergssallad", "Spenat"],
  Mejeri: ["Grädde", "Riven ost", "Yoghurt", "Mjölk", "Crème fraiche", "Ägg", "Halloumi",
    "Feta", "Smör", "Ost", "Kvarg", "Vispgrädde", "Matlagningsgrädde", "Fetaost", "Créme fraiche"],
  "Kött & fisk": ["Kycklinglårfilé", "Kycklingfilé", "Falukorv", "Fryst torsk", "Laxfilé",
    "Köttfärs", "Fläskfilé", "Biff", "Kalvschnitzel", "Bacon", "Korv", "Kyckling", "Skinka",
    "Fläskkarré", "Torsk", "Lax"],
  Skafferi: ["Pasta", "Ris", "Matvete", "Äggnudlar", "Vetemjöl", "Röda linser", "Kidneybönor",
    "Svarta bönor", "Majs", "Krossade tomater", "Tomatpuré", "Salsa", "Soja", "Lasagneplattor",
    "Kikärtor", "Lingonsylt", "Vegofärs", "Tofu", "Äppelmos", "Kapris", "Kaffe", "Te", "Socker",
    "Salt", "Peppar", "Olivolja", "Rapsolja", "Buljong", "Havregryn", "Müsli", "Ketchup",
    "Senap", "Honung", "Kokosmjölk", "Couscous", "Bulgur", "Linser"],
  Bröd: ["Bröd", "Tortilla", "Tortillabröd", "Knäckebröd", "Hamburgerbröd", "Baguette",
    "Frallor", "Rostbröd"],
  Frys: ["Wokgrönsaker", "Bär", "Räkor", "Ärtor", "Fiskpinnar", "Pommes"],
};

const NAME_TO_CATEGORY = new Map();
Object.entries(NAMES).forEach(([category, names]) => {
  names.forEach(name => NAME_TO_CATEGORY.set(fold(name), category));
});

// Nyckelord i kedjans egen kategorisökväg. Ordningen spelar roll: "fryst
// grönsaker" ska bli Frys, inte Frukt & grönt, så Frys prövas först.
const PATH_RULES = [
  ["Frys", ["frys", "fryst", "glass"]],
  ["Mejeri", ["mejeri", "mjölk", "ost", "ägg", "yoghurt", "grädde", "smör"]],
  ["Kött & fisk", ["kött", "chark", "fisk", "skaldjur", "fågel", "kyckling", "fläsk", "pålägg"]],
  ["Frukt & grönt", ["frukt", "grönt", "grönsak", "sallad", "bär", "rotfrukt", "potatis"]],
  ["Bröd", ["bröd", "bageri", "konditori"]],
  ["Skafferi", ["skafferi", "torrvar", "pasta", "ris", "konserv", "kryddor", "bak", "kaffe",
    "te ", "dryck", "snacks", "godis", "såser", "olja", "flingor", "gröt"]],
];

function fold(text) {
  return String(text || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").trim();
}

/**
 * @param {string} name ingrediens- eller varunamn
 * @param {string} [providerPath] kedjans egen kategorisökväg för den matchade produkten
 */
export function categoryFor(name, providerPath) {
  const direct = NAME_TO_CATEGORY.get(fold(name));
  if (direct) return direct;
  const path = fold(providerPath);
  if (path) {
    for (const [category, keywords] of PATH_RULES) {
      if (keywords.some(keyword => path.includes(keyword))) return category;
    }
  }
  // Sista chansen: sammansatta svenska namn ("Kycklingfärs", "Tomatpuré")
  // delar huvudord med något vi känner igen.
  for (const [known, category] of NAME_TO_CATEGORY) {
    if (known.length >= 4 && fold(name).includes(known)) return category;
  }
  return "Övrigt";
}

/** Grupperar rader i butiksordning. Tomma hyllor utelämnas. */
export function groupByCategory(items, categoryOf = item => item.category) {
  const groups = new Map(CATEGORY_ORDER.map(name => [name, []]));
  items.forEach(item => {
    const category = categoryOf(item) || "Övrigt";
    (groups.get(category) || groups.get("Övrigt")).push(item);
  });
  return [...groups.entries()].filter(([, rows]) => rows.length);
}
