import { readStoredState, writeStoredState } from "./src/state/storage.js";
import { aggregateIngredients, budgetRemaining, calculateShoppingTotal, portionFactor } from "./src/services/calculations.js";
import { filterRecipes } from "./src/services/recipe-search.js";
import { productApiUrl as configuredProductApiUrl, recipeDetailApiUrl, recipeSearchApiUrl } from "./src/api/config.js";
import { escapeHtml, safeHttpUrl } from "./src/utils/html.js";

const RECEPT = [
  { id: "kycklinggryta", namn: "Kycklinggryta med ris", emoji: "🍛", butik: "Willys", tid: 30, typ: "Familjefavorit", portionspris: 24.5, inkopspris: 105.3, sparar: 31, ingredienser: ["Kycklinglårfilé", "Ris", "Kokosmjölk", "Curry & grönsaker"], hemma: ["Olja", "Salt"] },
  { id: "pastagratang", namn: "Pastagratäng med purjolök", emoji: "🍝", butik: "ICA", tid: 35, typ: "Vegetarisk", portionspris: 18, inkopspris: 72.6, sparar: 22, ingredienser: ["Pasta", "Purjolök", "Grädde", "Riven ost"], hemma: ["Salt", "Peppar"] },
  { id: "linssoppa", namn: "Röd linssoppa", emoji: "🥣", butik: "Willys", tid: 25, typ: "Vegetarisk", portionspris: 12, inkopspris: 48.2, sparar: 18, ingredienser: ["Röda linser", "Kokosmjölk", "Morötter", "Lök & vitlök"], hemma: ["Buljong", "Olja"] },
  { id: "korvstroganoff", namn: "Korvstroganoff", emoji: "🍲", butik: "Coop", tid: 25, typ: "Snabbt & enkelt", portionspris: 15.5, inkopspris: 70.2, sparar: 16, ingredienser: ["Falukorv", "Grädde", "Tomatpuré", "Ris"], hemma: ["Salt", "Peppar"] },
  { id: "tacobonor", namn: "Tacobowl med svarta bönor", emoji: "🌮", butik: "ICA", tid: 20, typ: "Vegetarisk", portionspris: 16.5, inkopspris: 66.4, sparar: 25, ingredienser: ["Svarta bönor", "Ris", "Majs", "Salsa"], hemma: ["Kryddor"] },
  { id: "fiskpasta", namn: "Krämig fiskpasta", emoji: "🐟", butik: "Coop", tid: 30, typ: "Fisk", portionspris: 27, inkopspris: 109.5, sparar: 20, ingredienser: ["Fryst torsk", "Pasta", "Crème fraiche", "Citron"], hemma: ["Salt", "Peppar"] }
];

const recipePhoto = recipe => recipe.bild ? `<img class="recipe-photo" src="${recipe.bild}" alt="${recipe.namn}" loading="lazy">` : `<span class="recipe-photo recipe-fallback" role="img" aria-label="Ingen matbild tillgänglig"><svg viewBox="0 0 64 64"><path d="M14 48h36M18 44a14 14 0 0 1 28 0M32 20v10M27 20h10"/></svg><small>Matjakt</small></span>`;

const DAYS = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
const savedState = readStoredState(localStorage);
const state = { budget: savedState.budget || 800, personer: savedState.personer || 2, middagar: savedState.middagar || 4, butik: savedState.butik || "auto", postnummer: savedState.postnummer || "80313", position: null, sokning: "", kategori: "alla", maxTid: 0, baraFavoriter: false, apiRecipes: [], pantry: savedState.pantry || {}, liveValda: savedState.liveValda || [], liveProdukter: [], liveProduktMap: {}, liveLaddar: new Set(), valdaProdukter: savedState.valdaProdukter || {}, antal: savedState.antal || {}, favoriter: new Set(savedState.favoriter || []), plan: savedState.plan || {}, valda: new Set(), avklarade: new Set(), expanded: null };
function saveState() { writeStoredState(localStorage, { budget: state.budget, personer: state.personer, middagar: state.middagar, butik: state.butik, postnummer: state.postnummer, pantry: state.pantry, liveValda: state.liveValda, valdaProdukter: state.valdaProdukter, antal: state.antal, favoriter: [...state.favoriter], plan: state.plan }); }
const BRANCHES = [
  { kedja: "ICA", namn: "ICA Strömsbro", postnummer: "80313", lat: 60.692, lon: 17.168, avstandKm: 2.1, prisfaktor: 0.96 },
  { kedja: "ICA", namn: "ICA Söder", postnummer: "80313", lat: 60.667, lon: 17.141, avstandKm: 3.3, prisfaktor: 1.04 },
  { kedja: "Willys", namn: "Willys Gävle", postnummer: "80313", lat: 60.675, lon: 17.142, avstandKm: 2.8, prisfaktor: 1 },
  { kedja: "Hemköp", namn: "Hemköp Gävle", postnummer: "80313", lat: 60.674, lon: 17.145, avstandKm: 2.9, prisfaktor: 1.02 },
  { kedja: "Coop", namn: "Coop Gävle", postnummer: "80313", lat: 60.677, lon: 17.150, avstandKm: 2.5, prisfaktor: 1.01 }
];
const STORE_SEARCH = {
  ICA: item => `https://handla.ica.se/sok?q=${encodeURIComponent(item)}`,
  Willys: item => `https://www.willys.se/sok?searchQuery=${encodeURIComponent(item)}`,
  Hemköp: item => `https://www.hemkop.se/sok?q=${encodeURIComponent(item)}`,
  Coop: item => `https://www.coop.se/handla/sok/?q=${encodeURIComponent(item)}`
};
const PRODUCT_CATALOG = {
  "Grädde": { namn: "Mat grädde 15%", marke: "Arla", storlek: "2 dl", pris: 15.95 },
  "Majs": { namn: "Majs", marke: "ICA", storlek: "340 g", pris: 12.95 },
  "Pasta": { namn: "Spaghetti", marke: "Kungsörnen", storlek: "500 g", pris: 16.95 },
  "Purjolök": { namn: "Purjolök", marke: "ICA", storlek: "1 st", pris: 18.95 },
  "Ris": { namn: "Jasminris", marke: "ICA", storlek: "1 kg", pris: 29.95 },
  "Riven ost": { namn: "Riven hushållsost", marke: "ICA", storlek: "150 g", pris: 24.95 },
  "Salsa": { namn: "Chunky Salsa Medium", marke: "Santa Maria", storlek: "230 g", pris: 22.95 },
  "Svarta bönor": { namn: "Svarta bönor", marke: "ICA", storlek: "380 g", pris: 13.95 },
  "Curry & grönsaker": { namn: "Curry & grönsaker", marke: "Santa Maria", storlek: "28 g", pris: 14.95 },
  "Kokosmjölk": { namn: "Kokosmjölk", marke: "ICA", storlek: "400 ml", pris: 16.95 },
  "Kycklinglårfilé": { namn: "Kycklinglårfilé", marke: "ICA", storlek: "ca 600 g", pris: 69.95 },
  "Lök & vitlök": { namn: "Gul lök & vitlök", marke: "ICA", storlek: "500 g", pris: 19.95 },
  "Morötter": { namn: "Morötter", marke: "ICA", storlek: "1 kg", pris: 14.95 },
  "Röda linser": { namn: "Röda linser", marke: "ICA", storlek: "400 g", pris: 19.95 },
  "Falukorv": { namn: "Falukorv", marke: "Scan", storlek: "800 g", pris: 39.95 },
  "Tomatpuré": { namn: "Tomatpuré", marke: "Mutti", storlek: "140 g", pris: 14.95 },
  "Fryst torsk": { namn: "Fryst torskfilé", marke: "Findus", storlek: "450 g", pris: 59.95 },
  "Citron": { namn: "Citron", marke: "ICA", storlek: "1 st", pris: 6.95 },
  "Laxfilé": { namn: "Laxfilé", marke: "ICA", storlek: "ca 600 g", pris: 89.95 },
  "Dill": { namn: "Dill", marke: "ICA", storlek: "1 knippe", pris: 12.95 },
  "Kidneybönor": { namn: "Kidneybönor", marke: "ICA", storlek: "400 g", pris: 13.95 },
  "Paprika": { namn: "Paprika", marke: "ICA", storlek: "1 st", pris: 9.95 },
  "Halloumi": { namn: "Halloumi", marke: "Arla", storlek: "225 g", pris: 44.95 },
  "Matvete": { namn: "Matvete", marke: "Kungsörnen", storlek: "500 g", pris: 24.95 },
  "Yoghurt": { namn: "Turkisk yoghurt", marke: "Arla", storlek: "500 g", pris: 24.95 },
  "Kycklingfilé": { namn: "Kycklingfilé", marke: "ICA", storlek: "ca 500 g", pris: 79.95 },
  "Äggnudlar": { namn: "Äggnudlar", marke: "Santa Maria", storlek: "250 g", pris: 19.95 },
  "Wokgrönsaker": { namn: "Wokgrönsaker", marke: "Findus", storlek: "400 g", pris: 29.95 },
  "Soja": { namn: "Sojasås", marke: "Kikkoman", storlek: "150 ml", pris: 29.95 },
  "Lök": { namn: "Gul lök", marke: "ICA", storlek: "1 st", pris: 3.95 },
  "Basilika": { namn: "Basilika", marke: "ICA", storlek: "1 kruka", pris: 24.95 },
  "Ägg": { namn: "Ägg", marke: "ICA", storlek: "6-pack", pris: 34.95 },
  "Bär": { namn: "Frysta bär", marke: "ICA", storlek: "300 g", pris: 29.95 },
  "Mjölk": { namn: "Mjölk", marke: "Arla", storlek: "1 l", pris: 12.95 },
  "Krossade tomater": { namn: "Krossade tomater", marke: "ICA", storlek: "400 g", pris: 11.95 },
  "Vetemjöl": { namn: "Vetemjöl", marke: "Kungsörnen", storlek: "2 kg", pris: 24.95 },
  "Crème fraiche": { namn: "Crème fraiche", marke: "Arla", storlek: "2 dl", pris: 15.95 },
  "Potatis": { namn: "Potatis", marke: "ICA", storlek: "2 kg", pris: 24.95 }
};
const PACKAGE_INFO = {
  Pasta: { amount: 500, unit: "g" }, Ris: { amount: 1000, unit: "g" }, Grädde: { amount: 200, unit: "ml" },
  "Riven ost": { amount: 150, unit: "g" }, Majs: { amount: 340, unit: "g" }, "Svarta bönor": { amount: 380, unit: "g" },
  "Röda linser": { amount: 400, unit: "g" }, Kokosmjölk: { amount: 400, unit: "ml" }, "Krossade tomater": { amount: 400, unit: "g" },
  Falukorv: { amount: 800, unit: "g" }, "Tomatpuré": { amount: 140, unit: "g" }, "Fryst torsk": { amount: 450, unit: "g" },
  Citron: { amount: 1, unit: "st" }, "Laxfilé": { amount: 600, unit: "g" }, Dill: { amount: 1, unit: "st" },
  "Kidneybönor": { amount: 400, unit: "g" }, Paprika: { amount: 1, unit: "st" }, Halloumi: { amount: 225, unit: "g" },
  Matvete: { amount: 500, unit: "g" }, Yoghurt: { amount: 500, unit: "g" }, "Kycklingfilé": { amount: 500, unit: "g" },
  "Äggnudlar": { amount: 250, unit: "g" }, Wokgrönsaker: { amount: 400, unit: "g" }, Soja: { amount: 150, unit: "ml" },
  Lök: { amount: 1, unit: "st" }, Basilika: { amount: 1, unit: "st" }, Ägg: { amount: 6, unit: "st" }, Bär: { amount: 300, unit: "g" },
  Mjölk: { amount: 1000, unit: "ml" }, Vetemjöl: { amount: 2000, unit: "g" }, "Kycklinglårfilé": { amount: 600, unit: "g" },
  "Curry & grönsaker": { amount: 28, unit: "g" }, Salsa: { amount: 230, unit: "g" }, "Lök & vitlök": { amount: 500, unit: "g" },
  Morötter: { amount: 1000, unit: "g" }, "Crème fraiche": { amount: 200, unit: "g" }, Potatis: { amount: 2000, unit: "g" }
};
const RECIPE_QUANTITIES = {
  pastagratang: { Pasta: [250, "g"], "Purjolök": [0.5, "st"], Grädde: [200, "ml"], "Riven ost": [100, "g"] },
  fiskpasta: { "Fryst torsk": [450, "g"], Pasta: [250, "g"], "Crème fraiche": [200, "g"], Citron: [1, "st"] },
  kycklinggryta: { "Kycklinglårfilé": [600, "g"], Ris: [250, "g"], Kokosmjölk: [400, "ml"], "Curry & grönsaker": [28, "g"] },
  linssoppa: { "Röda linser": [250, "g"], Kokosmjölk: [400, "ml"], Morötter: [300, "g"], "Lök & vitlök": [150, "g"] },
  korvstroganoff: { Falukorv: [400, "g"], Grädde: [200, "ml"], "Tomatpuré": [70, "g"], Ris: [250, "g"] },
  tacobonor: { "Svarta bönor": [380, "g"], Ris: [250, "g"], Majs: [150, "g"], Salsa: [230, "g"] },
  lax: { "Laxfilé": [600, "g"], Potatis: [800, "g"], Citron: [1, "st"], Dill: [1, "st"] },
  halloumibowl: { Halloumi: [225, "g"], Matvete: [250, "g"], Paprika: [1, "st"], Yoghurt: [200, "g"] },
  chili: { "Kidneybönor": [400, "g"], "Krossade tomater": [400, "g"], Majs: [150, "g"], Paprika: [2, "st"] },
  kycklingwok: { "Kycklingfilé": [500, "g"], "Äggnudlar": [250, "g"], Wokgrönsaker: [400, "g"], Soja: [30, "ml"] },
  tomatsoppa: { "Krossade tomater": [400, "g"], Grädde: [200, "ml"], Lök: [2, "st"], Basilika: [1, "st"] },
  pannkakor: { "Vetemjöl": [250, "g"], Mjölk: [600, "ml"], Ägg: [4, "st"], Bär: [300, "g"] }
};
function mapApiRecipe(recipe) {
  const ingredients = (recipe.ingredients || []).map(item => escapeHtml(`${item.measure || ""} ${item.name || ""}`.trim())).filter(Boolean);
  return { id: recipe.id, provider: recipe.provider, providerRecipeId: recipe.providerRecipeId, namn: escapeHtml(recipe.title), butik: "alla", tid: Number(recipe.prepMinutes) || 0, typ: "Provider-recept", portionspris: 0, inkopspris: 0, sparar: 0, ingredienser: ingredients, hemma: [], beskrivning: "Recept från extern receptkälla.", steg: (recipe.instructions || []).map(escapeHtml), bild: safeHttpUrl(recipe.imageUrl), imageSource: recipe.imageSource, servings: recipe.servings };
}
RECEPT.push(
  { id: "lax", namn: "Ugnsbakad lax med potatis", emoji: "🐟", butik: "ICA", tid: 35, typ: "Fisk", portionspris: 29, inkopspris: 116, sparar: 24, ingredienser: ["Laxfilé", "Potatis", "Citron", "Dill"], hemma: ["Salt", "Olja"], beskrivning: "En enkel ugnsmiddag med citron och dill.", steg: ["Sätt ugnen på 200°C.", "Lägg lax och potatis i en form.", "Toppa med citron och dill och baka tills laxen är klar."] },
  { id: "halloumibowl", namn: "Halloumibowl med rostade grönsaker", emoji: "🥗", butik: "Willys", tid: 30, typ: "Vegetarisk", portionspris: 23, inkopspris: 92, sparar: 19, ingredienser: ["Halloumi", "Matvete", "Paprika", "Yoghurt"], hemma: ["Olja", "Kryddor"], beskrivning: "Färgstark bowl med krispig halloumi.", steg: ["Koka matvetet enligt förpackningen.", "Rosta grönsakerna i ugnen.", "Stek halloumin och servera med yoghurt."] },
  { id: "chili", namn: "Chili sin carne", emoji: "🌶️", butik: "Willys", tid: 35, typ: "Vegetarisk", portionspris: 17, inkopspris: 68, sparar: 21, ingredienser: ["Kidneybönor", "Krossade tomater", "Majs", "Paprika"], hemma: ["Ris", "Chili"], beskrivning: "Mustig vegetarisk chili som blir ännu godare dagen efter.", steg: ["Fräs paprika och lök.", "Tillsätt tomater, bönor och majs.", "Låt sjuda i 20 minuter och servera med ris."] },
  { id: "kycklingwok", namn: "Kycklingwok med nudlar", emoji: "🍜", butik: "Coop", tid: 25, typ: "Snabbt & enkelt", portionspris: 21, inkopspris: 84, sparar: 18, ingredienser: ["Kycklingfilé", "Äggnudlar", "Wokgrönsaker", "Soja"], hemma: ["Olja", "Vitlök"], beskrivning: "Snabb wok med mycket grönsaker och smakrik soja.", steg: ["Koka nudlarna.", "Stek kycklingen tills den är genomstekt.", "Woka grönsakerna och blanda allt med soja."] },
  { id: "tomatsoppa", namn: "Krämig tomatsoppa", emoji: "🍅", butik: "Hemköp", tid: 25, typ: "Vegetarisk", portionspris: 14, inkopspris: 56, sparar: 17, ingredienser: ["Krossade tomater", "Grädde", "Lök", "Basilika"], hemma: ["Buljong", "Peppar"], beskrivning: "Len tomatsoppa med basilika och grädde.", steg: ["Fräs löken mjuk.", "Koka med tomater och buljong.", "Mixa soppan och rör ner grädden."] },
  { id: "pannkakor", namn: "Pannkakor med bär", emoji: "🥞", butik: "Hemköp", tid: 25, typ: "Familjefavorit", portionspris: 12, inkopspris: 48, sparar: 14, ingredienser: ["Vetemjöl", "Mjölk", "Ägg", "Bär"], hemma: ["Smör", "Socker"], beskrivning: "Klassiska tunna pannkakor för hela familjen.", steg: ["Vispa ihop smetens ingredienser.", "Stek tunna pannkakor i smör.", "Servera med bär."] }
);
const RECIPE_DETAILS = {
  kycklinggryta: { beskrivning: "Krämig kycklinggryta med kokos, curry och söta grönsaker.", steg: ["Bryn kycklingen i en het panna.", "Fräs curry och grönsaker tills de mjuknar.", "Häll i kokosmjölken och låt sjuda tills kycklingen är genomstekt."], tips: "Servera med lime och färsk koriander om du har hemma." },
  pastagratang: { beskrivning: "Krämig pastagratäng med purjolök och ett gyllene osttäcke.", steg: ["Koka pastan två minuter kortare än anvisningen.", "Fräs purjolök och rör ner grädde.", "Blanda med pastan, toppa med ost och gratinera tills ytan fått färg."], tips: "Spara lite pastavatten för en extra krämig sås." },
  linssoppa: { beskrivning: "Värmande och mättande linssoppa med kokosmjölk och rotfrukter.", steg: ["Fräs lök, vitlök och morot i olja.", "Tillsätt linser, buljong och kokosmjölk.", "Låt sjuda tills linserna är mjuka och smaka av."], tips: "Toppa med yoghurt eller citron för friskare smak." },
  korvstroganoff: { beskrivning: "En svensk vardagsklassiker med tomat, grädde och mild paprika.", steg: ["Skär korven och bryn den lätt.", "Fräs tomatpuré och paprika innan du tillsätter grädde.", "Låt såsen sjuda några minuter och servera med ris."], tips: "En skvätt soja ger såsen mer djup." },
  tacobonor: { beskrivning: "Fräsch tacobowl med svarta bönor, majs, ris och salsa.", steg: ["Koka riset och värm bönorna med kryddor.", "Skär grönsakerna och blanda majsen med salsan.", "Bygg skålar med ris, bönor, grönsaker och salsa."], tips: "Pressa över lime precis före servering." },
  fiskpasta: { beskrivning: "Len fiskpasta med citron, crème fraiche och dill.", steg: ["Koka pastan och spara lite pastavatten.", "Tillaga fisken försiktigt i en krämig citronsås.", "Vänd ner pastan och späd med pastavatten till rätt konsistens."], tips: "Koka inte fisken för hårt, då blir den saftigare." },
  lax: { beskrivning: "Ugnsbakad lax med citron, dill och rostad potatis.", steg: ["Sätt ugnen på 200°C.", "Lägg lax och potatis i en form.", "Toppa med citron och dill och baka tills laxen är klar."], tips: "Laxen är klar när den precis börjar dela sig i lameller." },
  halloumibowl: { beskrivning: "Krispig halloumi med rostade grönsaker och krämig yoghurt.", steg: ["Koka matvetet enligt förpackningen.", "Rosta grönsakerna i ugnen.", "Stek halloumin och servera med yoghurt."], tips: "Stek halloumin sist så håller den sig varm och krispig." },
  chili: { beskrivning: "Mustig chili sin carne med bönor, tomat och paprika.", steg: ["Fräs paprika och lök.", "Tillsätt tomater, bönor och majs.", "Låt sjuda i 20 minuter och servera med ris."], tips: "Låt chilin vila tio minuter före servering för djupare smak." },
  kycklingwok: { beskrivning: "Snabb wok med kyckling, nudlar och krispiga grönsaker.", steg: ["Koka nudlarna.", "Stek kycklingen tills den är genomstekt.", "Woka grönsakerna och blanda allt med soja."], tips: "Ha alla ingredienser framme innan du börjar woka." },
  tomatsoppa: { beskrivning: "Len tomatsoppa med basilika och en skvätt grädde.", steg: ["Fräs löken mjuk.", "Koka med tomater och buljong.", "Mixa soppan och rör ner grädden."], tips: "En liten nypa socker balanserar syrliga tomater." },
  pannkakor: { beskrivning: "Klassiska tunna pannkakor med sötsyrliga bär.", steg: ["Vispa ihop smetens ingredienser.", "Stek tunna pannkakor i smör.", "Servera med bär."], tips: "Låt smeten vila en stund så blir pannkakorna jämnare." }
};
const $ = id => document.getElementById(id);
const money = value => `${Math.round(value).toLocaleString("sv-SE")} kr`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const scaledPurchasePrice = (recipe, branch = selectedBranch()) => recipe.inkopspris * portionFactor(state.personer) * (branch?.prisfaktor || 1);
function shoppingListCost(selected, branch) {
  const factor = branch?.prisfaktor || 1;
  return calculateShoppingTotal(aggregateShopping(selected), PRODUCT_CATALOG, state.pantry, factor);
}
function combinations(list, size) {
  if (size === 0) return [[]];
  if (list.length < size) return [];
  const [first, ...rest] = list;
  return [...combinations(rest, size - 1).map(combo => [first, ...combo]), ...combinations(rest, size)];
}
function bestMenuCombo(recipes, count, budget, branch) {
  if (!recipes.length) return [];
  if (recipes.length <= count) return [...recipes];
  let best = null, bestCost = -1, fallback = null, fallbackCost = Infinity;
  combinations(recipes, count).forEach(combo => {
    const cost = shoppingListCost(combo, branch);
    if (cost <= budget && cost > bestCost) { best = combo; bestCost = cost; }
    if (cost < fallbackCost) { fallback = combo; fallbackCost = cost; }
  });
  return best || fallback || [];
}
function distanceKm(lat1, lon1, lat2, lon2) {
  const earthRadius = 6371, latDelta = (lat2 - lat1) * Math.PI / 180, lonDelta = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(latDelta / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(lonDelta / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
function nearbyBranches() { return state.position ? BRANCHES : BRANCHES.filter(branch => branch.postnummer === state.postnummer); }
function cheapestBranch(chain = null) {
  const branches = nearbyBranches().filter(branch => !chain || branch.kedja === chain);
  return branches.map(branch => {
    const candidates = RECEPT.filter(recipe => recipe.butik === branch.kedja);
    const recipes = bestMenuCombo(candidates, state.middagar, state.budget, branch);
    const avstandKm = state.position ? distanceKm(state.position.lat, state.position.lon, branch.lat, branch.lon) : branch.avstandKm;
    return { ...branch, avstandKm, recipes, total: shoppingListCost(recipes, branch) };
  }).filter(result => result.recipes.length).sort((a, b) => a.total - b.total || a.avstandKm - b.avstandKm)[0] || null;
}
function selectedBranch() { return state.butik === "auto" ? cheapestBranch() : cheapestBranch(state.butik); }
function cheapestStore() {
  return selectedBranch();
}

const chosenStore = () => cheapestStore()?.kedja || state.butik;
const productApiUrl = (store, query) => configuredProductApiUrl(store, query, state.postnummer);
function sanitizeApiPayload(payload) {
  if (!Array.isArray(payload?.produkter)) return payload;
  return { ...payload, produkter: payload.produkter.map(product => ({ ...product, produktnamn: escapeHtml(product.produktnamn), marke_och_storlek: escapeHtml(product.marke_och_storlek), bild: safeHttpUrl(product.bild), url: safeHttpUrl(product.url), pris_kr: Number(product.pris_kr) || 0 })) };
}
const availableRecipes = () => state.butik === "alla" ? RECEPT : RECEPT.filter(recipe => recipe.butik === chosenStore());

function chooseMenu(shouldScroll = true) {
  const branch = selectedBranch();
  const combo = bestMenuCombo(availableRecipes(), state.middagar, state.budget, branch);
  state.valda.clear();
  combo.forEach(r => state.valda.add(r.id));
  render();
  if (shouldScroll) {
    setView("week");
  }
}

function renderRecipes() {
  const search = state.sokning.trim();
  const recipes = filterRecipes(search ? [...RECEPT, ...state.apiRecipes] : availableRecipes(), search).filter(recipe => (state.kategori === "alla" || recipe.typ === state.kategori) && (!state.maxTid || recipe.tid <= state.maxTid) && (!state.baraFavoriter || state.favoriter.has(recipe.id)));
  const branch = selectedBranch();
  const storeLabel = state.butik === "auto" ? `${branch?.namn || "ingen butik hittades"} (billigast automatiskt)` : state.butik === "alla" ? "alla butiker" : `${branch?.namn || state.butik}`;
  $("locationHint").textContent = branch ? `${nearbyBranches().length} butiker jämförda · ${branch.namn} är billigast och ${branch.avstandKm.toFixed(1)} km bort.` : `Hittade inga inlästa butiker nära ${state.postnummer} ännu.`;
  $("menuSummary").textContent = search ? `${recipes.length} svenska recept hittades. Tryck på en rätt för ingredienser.` : `${plural(Math.min(state.middagar, recipes.length), "middag", "middagar")} för ${plural(state.personer, "person", "personer")} från ${storeLabel}. Tryck på en rätt för ingredienser.`;
  $("recipeScroll").innerHTML = recipes.length ? recipes.map(recipe => {
    const selected = state.valda.has(recipe.id), expanded = state.expanded === recipe.id;
    const details = RECIPE_DETAILS[recipe.id] || recipe;
    return `<article class="recipe-card ${selected ? "selected" : ""}">
      <button class="recipe-details" data-details="${recipe.id}" aria-expanded="${expanded}">
        <span class="recipe-photo-wrap">${recipePhoto(recipe)}<span class="saving">${recipe.sparar ? `Spara ca ${money(recipe.sparar)}` : "Från receptdatabas"}</span></span>
        <span class="recipe-name">${recipe.namn}</span><span class="recipe-meta">${recipe.tid} min · ${recipe.typ}</span><span class="recipe-store">Billigast på ${recipe.butik}</span>
        <span class="price-tag">${recipe.inkopspris ? `${money(scaledPurchasePrice(recipe))} i butik` : "Pris hämtas från butik"}</span><span class="portion-price">${recipe.portionspris ? `ca ${money(recipe.portionspris)} per portion` : "Ingredienser och instruktioner finns"}</span>
      </button>
      ${expanded ? `<div class="ingredients"><p class="recipe-description">${details.beskrivning || "En god vardagsrätt med enkla råvaror."}</p><strong>Du behöver köpa</strong><p>${recipe.ingredienser.join(", ")}</p><small>Hemma: ${recipe.hemma.join(", ")}</small>${details.steg ? `<ol class="recipe-steps">${details.steg.map(step => `<li>${step}</li>`).join("")}</ol>` : ""}${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${details.tips}</p>` : ""}</div>` : ""}
      <button class="favorite-btn ${state.favoriter.has(recipe.id) ? "is-favorite" : ""}" data-favorite="${recipe.id}" aria-label="${state.favoriter.has(recipe.id) ? "Ta bort favorit" : "Spara som favorit"}">${state.favoriter.has(recipe.id) ? "★" : "☆"}</button><button class="add-btn" data-add="${recipe.id}">${selected ? "✓ Tillagd" : "+ Lägg till"}</button>
    </article>`;
  }).join("") : `<p class="empty-state">Inga recept matchar din sökning eller butik ännu.</p>`;
  document.querySelectorAll("[data-details]").forEach(btn => btn.addEventListener("click", () => openRecipeTab(btn.dataset.details)));
  document.querySelectorAll("[data-add]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.add; state.valda.has(id) ? state.valda.delete(id) : state.valda.add(id); render(); }));
  document.querySelectorAll("[data-favorite]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.favorite; state.favoriter.has(id) ? state.favoriter.delete(id) : state.favoriter.add(id); saveState(); renderRecipes(); }));
}

function openRecipeTab(id) { history.pushState({ recept: id }, "", `${location.pathname}?recept=${encodeURIComponent(id)}`); renderRecipePage(); }
async function renderRecipePage() {
  const id = new URLSearchParams(location.search).get("recept");
  if (!id) { $("top").hidden = false; document.querySelector(".bottom-nav").hidden = false; $("recipePage").hidden = true; window.scrollTo(0, 0); return; }
  let allRecipes = [...RECEPT, ...state.apiRecipes];
  let recipe = allRecipes.find(item => item.id === id);
  if (!recipe && id.includes(":")) {
    try { const response = await fetch(recipeDetailApiUrl(id)); if (response.ok) { const data = await response.json(); recipe = mapApiRecipe(data.recipe); state.apiRecipes.push(recipe); allRecipes = [...RECEPT, ...state.apiRecipes]; } } catch { /* The friendly not-found state below remains visible. */ }
  }
  if (!recipe) return;
  const details = RECIPE_DETAILS[id] || recipe;
  $("top").hidden = true; document.querySelector(".bottom-nav").hidden = true; $("recipePage").hidden = false;
  $("recipePage").innerHTML = `<button class="back-link recipe-back" type="button">← Alla recept</button><article class="full-recipe">${recipe.bild ? `<img src="${recipe.bild}" alt="${recipe.namn}">` : `<div class="full-recipe-fallback">${recipePhoto(recipe)}</div>`}<p class="eyebrow">${recipe.typ}</p><h1>${recipe.namn}</h1><div class="recipe-detail-meta"><span>${recipe.tid ? recipe.tid + " min" : "Tid saknas"}</span><span>${recipe.servings || state.personer} portioner</span><span>${recipe.portionspris ? money(recipe.portionspris) + "/portion" : "Pris i butik"}</span></div><p class="full-recipe-description">${details.beskrivning || "En god svensk vardagsrätt."}</p><button class="btn btn-primary recipe-add-primary" type="button" data-recipe-add="${recipe.id}"><span>${state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"}</span><span>＋</span></button><h2>Ingredienser</h2><ul>${recipe.ingredienser.map(item => `<li>${item}</li>`).join("")}</ul><h2>Gör så här</h2><ol>${(details.steg || []).map(step => `<li>${step}</li>`).join("")}</ol>${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${details.tips}</p>` : ""}</article>`;
  $("recipePage").querySelector(".recipe-back").addEventListener("click", () => history.back());
  $("recipePage").querySelector("[data-recipe-add]").addEventListener("click", event => { state.valda.has(recipe.id) ? state.valda.delete(recipe.id) : state.valda.add(recipe.id); render(); event.currentTarget.querySelector("span").textContent = state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"; });
  requestAnimationFrame(() => window.scrollTo(0, 0));
  let touchStartX = 0; $("recipePage").ontouchstart = event => { touchStartX = event.changedTouches[0].screenX; }; $("recipePage").ontouchend = event => { const distance = event.changedTouches[0].screenX - touchStartX; if (Math.abs(distance) < 70) return; const ids = allRecipes.map(item => item.id), currentIndex = ids.indexOf(id), targetIndex = distance < 0 ? currentIndex + 1 : currentIndex - 1; if (targetIndex >= 0 && targetIndex < ids.length) openRecipeTab(ids[targetIndex]); else if (distance > 0) history.back(); };
}

function renderStoreComparison(selected) {
  const container = $("storeCompare");
  if (!container) return;
  const branches = nearbyBranches();
  if (!selected.length || !branches.length) { container.innerHTML = ""; return; }
  const results = branches.map(branch => ({ branch, cost: shoppingListCost(selected, branch) })).sort((a, b) => a.cost - b.cost);
  const cheapest = results[0], priciest = results[results.length - 1];
  const savings = priciest.cost - cheapest.cost;
  container.innerHTML = `<div class="store-compare"><div class="store-compare-head"><span>Billigast just nu</span><strong>${cheapest.branch.namn} · ${money(cheapest.cost)}</strong>${savings > 1 ? `<small>Du sparar ${money(savings)} mot ${priciest.branch.namn}</small>` : ""}</div><div class="store-compare-list">${results.map(r => `<div class="store-compare-row ${r.branch === cheapest.branch ? "cheapest" : ""}"><span>${r.branch.namn}</span><strong>${money(r.cost)}</strong></div>`).join("")}</div></div>`;
}

const CATEGORY_MAP = { "Frukt & grönt": ["Purjolök", "Morötter", "Lök", "Paprika", "Citron", "Dill", "Basilika", "Lök & vitlök"], Mejeri: ["Grädde", "Riven ost", "Yoghurt", "Mjölk", "Crème fraiche", "Ägg", "Halloumi"], "Kött & fisk": ["Kycklinglårfilé", "Kycklingfilé", "Falukorv", "Fryst torsk", "Laxfilé"], Torrvaror: ["Pasta", "Ris", "Matvete", "Äggnudlar", "Vetemjöl", "Röda linser", "Kidneybönor", "Svarta bönor", "Majs", "Krossade tomater", "Tomatpuré", "Salsa", "Soja"], Frys: ["Wokgrönsaker", "Bär"] };
function itemCategory(name) { return Object.entries(CATEGORY_MAP).find(([, names]) => names.includes(name))?.[0] || "Övrigt"; }
function shoppingItemMarkup(item) { const product = PRODUCT_CATALOG[item.namn] || { namn: item.namn, marke: "", pris: 0 }; const pantry = state.pantry[item.namn] || 0; const needed = Math.max(0, item.total - pantry); const packages = item.package ? Math.ceil(needed / item.package.amount) : Math.ceil(needed); const amount = packages ? `${packages} × ${item.package?.amount || 1} ${item.package?.unit || item.unit}` : "Finns hemma"; return `<label class="shopping-item ${state.avklarade.has(item.namn) ? "checked" : ""}"><input type="checkbox" data-shopping="${item.namn}" ${state.avklarade.has(item.namn) ? "checked" : ""}><span class="product-info"><strong>${item.namn}</strong><small>${product.marke ? `${product.marke} · ` : ""}${amount}</small></span><strong>${product.pris ? money(product.pris * packages) : ""}</strong></label>`; }
function renderPantry() { const items = Object.entries(state.pantry).filter(([, amount]) => Number(amount) > 0); $("pantryCount").textContent = items.length; $("pantryList").innerHTML = items.length ? items.map(([name, amount]) => `<div class="pantry-item"><span><strong>${name}</strong><small>${amount} ${PACKAGE_INFO[name]?.unit || "st"}</small></span><button type="button" data-remove-pantry="${name}" aria-label="Ta bort ${name}">×</button></div>`).join("") : `<div class="pantry-empty"><svg viewBox="0 0 64 64"><path d="M12 22h40v34H12zM20 22v-9h24v9M20 33h24M20 43h16"/></svg><h2>Ditt skafferi är tomt</h2><p>Lägg in det du redan har hemma så hjälper Matjakt dig att handla mindre.</p></div>`; document.querySelectorAll("[data-remove-pantry]").forEach(button => button.addEventListener("click", () => { delete state.pantry[button.dataset.removePantry]; saveState(); render(); })); }
function renderBasket() {
  const selected = [...RECEPT, ...state.apiRecipes].filter((recipe, index, recipes) => state.valda.has(recipe.id) && recipes.findIndex(item => item.id === recipe.id) === index);
  const total = shoppingListCost(selected, selectedBranch()), remaining = budgetRemaining(state.budget, total), shoppingItems = aggregateShopping(selected);
  $("basketCount").textContent = plural(selected.length, "middag", "middagar"); $("weekBudget").textContent = money(state.budget);
  $("basketLines").innerHTML = selected.length ? selected.map((recipe, index) => `<article class="basket-line"><span><small>${DAYS[index] || `Dag ${index + 1}`}</small>${recipe.namn}</span><strong>${money(scaledPurchasePrice(recipe))}</strong><div class="basket-line-actions"><button type="button" data-details="${recipe.id}">Visa recept</button><button type="button" data-swap="${recipe.id}">Byt rätt</button></div></article>`).join("") : `<div class="basket-empty"><strong>Ingen vecka ännu</strong><p>Gå till Hem och skapa din första matvecka.</p></div>`;
  const groups = shoppingItems.reduce((result, item) => { const category = itemCategory(item.namn); (result[category] ||= []).push(item); return result; }, {});
  $("shoppingList").innerHTML = shoppingItems.length ? Object.entries(groups).map(([category, items]) => `<section><h3>${category}<span>${items.length}</span></h3>${items.map(shoppingItemMarkup).join("")}</section>`).join("") : `<div class="pantry-empty"><h2>Listan väntar på din vecka</h2><p>Skapa en meny så samlar vi automatiskt allt du behöver handla.</p></div>`;
  document.querySelectorAll("[data-shopping]").forEach(input => input.addEventListener("change", () => { input.checked ? state.avklarade.add(input.dataset.shopping) : state.avklarade.delete(input.dataset.shopping); renderBasket(); }));
  document.querySelectorAll("[data-details]").forEach(button => button.addEventListener("click", () => openRecipeTab(button.dataset.details)));
  document.querySelectorAll("[data-swap]").forEach(button => button.addEventListener("click", () => { const current = button.dataset.swap; const replacement = availableRecipes().find(recipe => !state.valda.has(recipe.id)); state.valda.delete(current); if (replacement) state.valda.add(replacement.id); render(); }));
  const completed = shoppingItems.filter(item => state.avklarade.has(item.namn)).length, progress = shoppingItems.length ? completed / shoppingItems.length * 100 : 0;
  $("shoppingProgress").textContent = `${completed} av ${shoppingItems.length} varor`; $("shoppingCost").textContent = `${money(total)} / ${money(state.budget)}`; $("shoppingProgressBar").style.width = `${progress}%`;
  $("basketTotal").textContent = money(total); $("basketRemaining").textContent = money(Math.abs(remaining)); $("basketRemainingRow").classList.toggle("over-budget", remaining < 0); $("basketRemainingRow").querySelector("span").textContent = remaining < 0 ? "Över budget" : "Kvar";
  renderStoreComparison(selected); renderPantry();
}

function aggregateShopping(selected) {
  return aggregateIngredients(selected, RECIPE_QUANTITIES, PACKAGE_INFO, state.personer);
}

function updateSummary() { $("summaryBudget").textContent = money(state.budget); $("summaryPeople").textContent = plural(state.personer, "person", "personer"); $("summaryMeals").textContent = plural(state.middagar, "middag", "middagar"); }
function render() { renderRecipes(); renderBasket(); renderLiveSelection(); updateSummary(); }
function step(key, delta, min, max) { state[key] = Math.min(max, Math.max(min, state[key] + delta)); $(`${key === "personer" ? "people" : "meals"}Value`).textContent = state[key]; saveState(); render(); }
$("budgetInput").value = state.budget; $("peopleValue").textContent = state.personer; $("mealsValue").textContent = state.middagar; $("storeInput").value = state.butik; $("postcodeInput").value = state.postnummer;
$("budgetInput").addEventListener("input", e => { state.budget = Number(e.target.value) || 0; saveState(); updateSummary(); renderBasket(); });
$("postcodeInput").addEventListener("input", e => { state.position = null; state.postnummer = e.target.value.replace(/\D/g, ""); saveState(); chooseMenu(false); });
$("locateBtn").addEventListener("click", () => { if (!navigator.geolocation) return; $("locateBtn").textContent = "Hämtar..."; navigator.geolocation.getCurrentPosition(({ coords }) => { state.position = { lat: coords.latitude, lon: coords.longitude }; $("locateBtn").textContent = "Hittad"; chooseMenu(false); }, () => { $("locateBtn").textContent = "Försök igen"; }); });
$("storeInput").addEventListener("change", e => { state.butik = e.target.value; saveState(); chooseMenu(); });
let recipeApiRequestId = 0;
async function fetchApiRecipes(query) {
  const requestId = ++recipeApiRequestId;
  try {
    const response = await fetch(recipeSearchApiUrl(query));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (requestId !== recipeApiRequestId) return;
    state.apiRecipes = (data.recipes || []).map(mapApiRecipe);
    renderRecipes();
  } catch { if (requestId !== recipeApiRequestId) return; state.apiRecipes = []; renderRecipes(); }
}
$("recipeSearch").addEventListener("input", async e => { state.sokning = e.target.value; const query = state.sokning.trim(); state.apiRecipes = []; renderRecipes(); if (query.length >= 3) fetchApiRecipes(query); if (query.length < 2 || state.butik === "alla") { $("liveProducts").innerHTML = ""; return; } $("liveProducts").innerHTML = `<p class="live-loading">Söker liveprodukter hos ${selectedBranch()?.namn || chosenStore()}...</p>`; try { const response = await fetch(productApiUrl(chosenStore(), query)); if (!response.ok) throw new Error(`HTTP ${response.status}`); const data = sanitizeApiPayload(await response.json()); if (state.sokning.trim() !== query) return; state.liveProdukter = data.produkter || []; $("liveProducts").innerHTML = state.liveProdukter.length ? `<div class="live-products-head"><span>LIVE FRÅN BUTIKEN</span><strong>${state.liveProdukter.length} produkter</strong></div><div class="live-product-grid">${state.liveProdukter.map(product => `<a class="live-product" href="${product.url}" target="_blank" rel="noopener"><span class="live-product-name">${product.produktnamn}</span><small>${product.marke_och_storlek || "Storlek visas hos butiken"}</small><strong>${product.pris_kr.toLocaleString("sv-SE", { minimumFractionDigits: 2 })} kr</strong></a>`).join("")}</div>` : `<p class="live-loading">Inga liveprodukter hittades.</p>`; renderBasket(); } catch { state.liveProdukter = []; $("liveProducts").innerHTML = `<p class="live-loading">Livebutiken svarar inte just nu.</p>`; } });
$("categoryFilter").addEventListener("change", e => { state.kategori = e.target.value; renderRecipes(); });
function renderLiveSelection() { const existing = document.querySelector(".live-selection"); if (existing) existing.remove(); if (!state.liveValda.length) return; $("shoppingList").insertAdjacentHTML("afterbegin", `<div class="live-selection"><h3>Valda butikprodukter</h3>${state.liveValda.map(product => `<div class="live-selection-item"><img src="${product.bild || ""}" alt="" onerror="this.remove()"><span><strong>${product.produktnamn}</strong><small>${product.marke_och_storlek || ""} · ${product.pris_kr.toLocaleString("sv-SE", { minimumFractionDigits: 2 })} kr</small></span><a href="${product.url}" target="_blank" rel="noopener">Öppna</a></div>`).join("")}</div>`); }
$("timeFilter").addEventListener("change", e => { state.maxTid = Number(e.target.value); renderRecipes(); });
$("favoriteFilter").addEventListener("change", e => { state.baraFavoriter = e.target.checked; renderRecipes(); });
function setView(view) { $("top").className = `app view-${view}`; document.querySelectorAll(".bottom-nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view)); window.scrollTo({ top: 0, behavior: "smooth" }); }
document.querySelectorAll("[data-view]").forEach(item => item.addEventListener("click", () => setView(item.dataset.view)));
$("peopleMinus").addEventListener("click", () => step("personer", -1, 1, 12)); $("peoplePlus").addEventListener("click", () => step("personer", 1, 1, 12));
$("mealsMinus").addEventListener("click", () => step("middagar", -1, 1, 6)); $("mealsPlus").addEventListener("click", () => step("middagar", 1, 1, 6));
$("generateBtn").addEventListener("click", chooseMenu); $("refreshBtn").addEventListener("click", () => { RECEPT.push(RECEPT.shift()); chooseMenu(); });
$("addPantryBtn").addEventListener("click", () => { const name = window.prompt("Vilken vara vill du lägga till?")?.trim(); if (!name) return; const amount = Number(window.prompt("Hur mycket har du hemma?", "1")); state.pantry[name] = Number.isFinite(amount) && amount > 0 ? amount : 1; saveState(); render(); });
chooseMenu(false);
renderRecipePage();
window.addEventListener("popstate", renderRecipePage);
