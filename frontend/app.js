const API_BASE = "http://127.0.0.1:8000";
const RECEPT = [
  { id: "kycklinggryta", namn: "Kycklinggryta med ris", emoji: "🍛", butik: "Willys", tid: 30, typ: "Familjefavorit", portionspris: 24.5, inkopspris: 105.3, sparar: 31, ingredienser: ["Kycklinglårfilé", "Ris", "Kokosmjölk", "Curry & grönsaker"], hemma: ["Olja", "Salt"] },
  { id: "pastagratang", namn: "Pastagratäng med purjolök", emoji: "🍝", butik: "ICA", tid: 35, typ: "Vegetarisk", portionspris: 18, inkopspris: 72.6, sparar: 22, ingredienser: ["Pasta", "Purjolök", "Grädde", "Riven ost"], hemma: ["Salt", "Peppar"] },
  { id: "linssoppa", namn: "Röd linssoppa", emoji: "🥣", butik: "Willys", tid: 25, typ: "Vegetarisk", portionspris: 12, inkopspris: 48.2, sparar: 18, ingredienser: ["Röda linser", "Kokosmjölk", "Morötter", "Lök & vitlök"], hemma: ["Buljong", "Olja"] },
  { id: "korvstroganoff", namn: "Korvstroganoff", emoji: "🍲", butik: "Coop", tid: 25, typ: "Snabbt & enkelt", portionspris: 15.5, inkopspris: 70.2, sparar: 16, ingredienser: ["Falukorv", "Grädde", "Tomatpuré", "Ris"], hemma: ["Salt", "Peppar"] },
  { id: "tacobonor", namn: "Tacobowl med svarta bönor", emoji: "🌮", butik: "ICA", tid: 20, typ: "Vegetarisk", portionspris: 16.5, inkopspris: 66.4, sparar: 25, ingredienser: ["Svarta bönor", "Ris", "Majs", "Salsa"], hemma: ["Kryddor"] },
  { id: "fiskpasta", namn: "Krämig fiskpasta", emoji: "🐟", butik: "Coop", tid: 30, typ: "Fisk", portionspris: 27, inkopspris: 109.5, sparar: 20, ingredienser: ["Fryst torsk", "Pasta", "Crème fraiche", "Citron"], hemma: ["Salt", "Peppar"] }
];

const RECIPE_IMAGES = {
  kycklinggryta: "assets/recipes/kycklinggryta.png",
  pastagratang: "assets/recipes/pastagratang.png",
  linssoppa: "assets/recipes/linssoppa.png",
  korvstroganoff: "assets/recipes/korvstroganoff.png",
  tacobonor: "assets/recipes/tacobonor.png",
  fiskpasta: "assets/recipes/fiskpasta.png",
  lax: "assets/recipes/fiskpasta.png",
  halloumibowl: "assets/recipes/tacobonor.png",
  chili: "assets/recipes/linssoppa.png",
  kycklingwok: "assets/recipes/kycklinggryta.png",
  tomatsoppa: "assets/recipes/linssoppa.png",
  pannkakor: "assets/recipes/pastagratang.png"
};

const DAYS = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
const savedState = JSON.parse(localStorage.getItem("matjakt-state") || "{}");
const state = { budget: savedState.budget || 800, personer: savedState.personer || 2, middagar: savedState.middagar || 4, butik: savedState.butik || "auto", postnummer: savedState.postnummer || "80313", position: null, sokning: "", kategori: "alla", maxTid: 0, baraFavoriter: false, apiRecipes: [], pantry: savedState.pantry || {}, liveValda: savedState.liveValda || [], liveProdukter: [], liveProduktMap: {}, liveLaddar: new Set(), valdaProdukter: savedState.valdaProdukter || {}, antal: savedState.antal || {}, favoriter: new Set(savedState.favoriter || []), plan: savedState.plan || {}, valda: new Set(), avklarade: new Set(), expanded: null };
function saveState() { localStorage.setItem("matjakt-state", JSON.stringify({ budget: state.budget, personer: state.personer, middagar: state.middagar, butik: state.butik, postnummer: state.postnummer, pantry: state.pantry, liveValda: state.liveValda, liveProdukter: state.liveProdukter, valdaProdukter: state.valdaProdukter, antal: state.antal, favoriter: [...state.favoriter], plan: state.plan })); }
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
  "Röda linser": { namn: "Röda linser", marke: "ICA", storlek: "400 g", pris: 19.95 }
};
const PACKAGE_INFO = { Pasta: { amount: 500, unit: "g" }, Ris: { amount: 1000, unit: "g" }, Grädde: { amount: 200, unit: "ml" }, "Riven ost": { amount: 150, unit: "g" }, Majs: { amount: 340, unit: "g" }, "Svarta bönor": { amount: 380, unit: "g" }, "Röda linser": { amount: 400, unit: "g" }, Kokosmjölk: { amount: 400, unit: "ml" }, "Krossade tomater": { amount: 400, unit: "g" } };
const RECIPE_QUANTITIES = {
  pastagratang: { Pasta: [250, "g"], "Purjolök": [0.5, "st"], Grädde: [200, "ml"], "Riven ost": [100, "g"] },
  fiskpasta: { Pasta: [250, "g"], "Crème fraiche": [200, "g"] },
  kycklinggryta: { Ris: [250, "g"], Kokosmjölk: [400, "ml"] },
  linssoppa: { "Röda linser": [250, "g"], Kokosmjölk: [400, "ml"] },
  korvstroganoff: { Ris: [250, "g"], Grädde: [200, "ml"] },
  tacobonor: { Ris: [250, "g"], Majs: [150, "g"], "Svarta bönor": [380, "g"] },
  lax: { Potatis: [800, "g"] },
  chili: { Majs: [150, "g"], "Svarta bönor": [380, "g"] },
  pannkakor: { "Vetemjöl": [250, "g"], Mjölk: [600, "ml"] }
};
function mapApiMeal(meal) {
  const ingredients = Array.from({ length: 20 }, (_, index) => ({ name: meal[`strIngredient${index + 1}`], measure: meal[`strMeasure${index + 1}`] })).filter(item => item.name).map(item => `${item.measure || ""} ${item.name}`.trim());
  return { id: `meal-${meal.idMeal}`, namn: meal.strMeal, emoji: "🍽️", butik: "alla", tid: 0, typ: meal.strCategory || "Recept", portionspris: 0, inkopspris: 0, sparar: 0, ingredienser: ingredients, hemma: [], beskrivning: meal.strArea ? `${meal.strArea}-inspirerad rätt från TheMealDB.` : "Recept från TheMealDB.", steg: (meal.strInstructions || "").split(/\r?\n/).map(step => step.trim()).filter(Boolean), bild: meal.strMealThumb };
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
const scaledPurchasePrice = (recipe, branch = selectedBranch()) => recipe.inkopspris * Math.max(1, Math.ceil(state.personer / 4)) * (branch?.prisfaktor || 1);
function distanceKm(lat1, lon1, lat2, lon2) {
  const earthRadius = 6371, latDelta = (lat2 - lat1) * Math.PI / 180, lonDelta = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(latDelta / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(lonDelta / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
function nearbyBranches() { return state.position ? BRANCHES : BRANCHES.filter(branch => branch.postnummer === state.postnummer); }
function cheapestBranch(chain = null) {
  const branches = nearbyBranches().filter(branch => !chain || branch.kedja === chain);
  return branches.map(branch => {
    const recipes = RECEPT.filter(recipe => recipe.butik === branch.kedja).sort((a, b) => a.portionspris - b.portionspris).slice(0, state.middagar);
    const avstandKm = state.position ? distanceKm(state.position.lat, state.position.lon, branch.lat, branch.lon) : branch.avstandKm;
    return { ...branch, avstandKm, recipes, total: recipes.reduce((sum, recipe) => sum + scaledPurchasePrice(recipe, branch), 0) };
  }).filter(result => result.recipes.length).sort((a, b) => a.total - b.total || a.avstandKm - b.avstandKm)[0] || null;
}
function selectedBranch() { return state.butik === "auto" ? cheapestBranch() : cheapestBranch(state.butik); }
function cheapestStore() {
  return selectedBranch();
}

const chosenStore = () => cheapestStore()?.kedja || state.butik;
const availableRecipes = () => state.butik === "alla" ? RECEPT : RECEPT.filter(recipe => recipe.butik === chosenStore());

function chooseMenu(shouldScroll = true) {
  state.valda.clear();
  [...availableRecipes()].sort((a, b) => a.portionspris - b.portionspris).slice(0, state.middagar).forEach(r => state.valda.add(r.id));
  render();
  if (shouldScroll) $("recipesHeading").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderRecipes() {
  const search = state.sokning.trim().toLocaleLowerCase("sv");
  const recipes = (search ? RECEPT : availableRecipes()).filter(recipe => (!search || [recipe.namn, recipe.typ, ...recipe.ingredienser].join(" ").toLocaleLowerCase("sv").includes(search)) && (state.kategori === "alla" || recipe.typ === state.kategori) && (!state.maxTid || recipe.tid <= state.maxTid) && (!state.baraFavoriter || state.favoriter.has(recipe.id)));
  const branch = selectedBranch();
  const storeLabel = state.butik === "auto" ? `${branch?.namn || "ingen butik hittades"} (billigast automatiskt)` : state.butik === "alla" ? "alla butiker" : `${branch?.namn || state.butik}`;
  $("locationHint").textContent = branch ? `${nearbyBranches().length} butiker jämförda · ${branch.namn} är billigast och ${branch.avstandKm.toFixed(1)} km bort.` : `Hittade inga inlästa butiker nära ${state.postnummer} ännu.`;
  $("menuSummary").textContent = search ? `${recipes.length} svenska recept hittades. Tryck på en rätt för ingredienser.` : `${plural(Math.min(state.middagar, recipes.length), "middag", "middagar")} för ${plural(state.personer, "person", "personer")} från ${storeLabel}. Tryck på en rätt för ingredienser.`;
  $("recipeScroll").innerHTML = recipes.length ? recipes.map(recipe => {
    const selected = state.valda.has(recipe.id), expanded = state.expanded === recipe.id;
    const details = RECIPE_DETAILS[recipe.id] || recipe;
    return `<article class="recipe-card ${selected ? "selected" : ""}">
      <button class="recipe-details" data-details="${recipe.id}" aria-expanded="${expanded}">
        <span class="recipe-photo-wrap"><img class="recipe-photo" src="${RECIPE_IMAGES[recipe.id] || recipe.bild}" alt="${recipe.namn}" loading="lazy"><span class="saving">${recipe.sparar ? `Spara ca ${money(recipe.sparar)}` : "Från receptdatabas"}</span></span>
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
function renderRecipePage() {
  const id = new URLSearchParams(location.search).get("recept");
  if (!id) { $("top").hidden = false; document.querySelector(".bottom-nav").hidden = false; $("recipePage").hidden = true; window.scrollTo(0, 0); return; }
  const recipe = RECEPT.find(item => item.id === id);
  if (!recipe) return;
  const details = RECIPE_DETAILS[id] || recipe;
  $("top").hidden = true; document.querySelector(".bottom-nav").hidden = true; $("recipePage").hidden = false;
  $("recipePage").innerHTML = `<button class="back-link recipe-back" type="button">← Alla recept</button><article class="full-recipe"><img src="${RECIPE_IMAGES[id] || recipe.bild}" alt="${recipe.namn}"><p class="eyebrow">${recipe.typ}</p><h1>${recipe.namn}</h1><p class="full-recipe-description">${details.beskrivning || "En god svensk vardagsrätt."}</p><h2>Ingredienser</h2><ul>${recipe.ingredienser.map(item => `<li>${item}</li>`).join("")}</ul><h2>Gör så här</h2><ol>${(details.steg || []).map(step => `<li>${step}</li>`).join("")}</ol>${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${details.tips}</p>` : ""}</article>`;
  $("recipePage").querySelector(".recipe-back").addEventListener("click", () => history.back());
  requestAnimationFrame(() => window.scrollTo(0, 0));
  let touchStartX = 0; $("recipePage").ontouchstart = event => { touchStartX = event.changedTouches[0].screenX; }; $("recipePage").ontouchend = event => { const distance = event.changedTouches[0].screenX - touchStartX; if (Math.abs(distance) < 70) return; const ids = RECEPT.map(item => item.id), currentIndex = ids.indexOf(id), targetIndex = distance < 0 ? currentIndex + 1 : currentIndex - 1; if (targetIndex >= 0 && targetIndex < ids.length) openRecipeTab(ids[targetIndex]); else if (distance > 0) history.back(); };
}

function renderBasket() {
  const selected = [...RECEPT, ...state.apiRecipes].filter((recipe, index, recipes) => state.valda.has(recipe.id) && recipes.findIndex(item => item.id === recipe.id) === index);
  const total = selected.reduce((sum, r) => sum + scaledPurchasePrice(r), 0), remaining = state.budget - total;
  $("basketCount").textContent = plural(selected.length, "middag", "middagar");
  $("basketLines").innerHTML = selected.length ? selected.map(r => `<div class="basket-line"><span><select data-day="${r.id}" aria-label="Dag för ${r.namn}">${DAYS.map(day => `<option ${state.plan[r.id] === day ? "selected" : ""}>${day}</option>`).join("")}</select> ${r.emoji} ${r.namn}</span><strong>${money(scaledPurchasePrice(r))}</strong></div>`).join("") : `<div class="basket-empty">Skapa en meny eller lägg till en rätt ovan.</div>`;
  document.querySelectorAll("[data-day]").forEach(input => input.addEventListener("change", () => { state.plan[input.dataset.day] = input.value; saveState(); }));
  const shoppingItems = aggregateShopping(selected);
  const shoppingBranch = selectedBranch();
  const shoppingStore = state.butik === "alla" ? (selected[0]?.butik || "ICA") : chosenStore();
  $("shoppingList").innerHTML = shoppingItems.length ? `<h3>Inköpslista <span>${shoppingItems.length} varor</span></h3><p class="shopping-store">Handla hos ${shoppingBranch?.namn || shoppingStore} · mängder sammanräknade</p>${shoppingItems.map(item => { const product = PRODUCT_CATALOG[item.namn] || { namn: item.namn, marke: "Produkt hittas i butik", storlek: "", pris: 0 }; const pantry = state.pantry[item.namn] || 0; const kvar = Math.max(0, item.total - pantry); const packages = item.package ? Math.ceil(kvar / item.package.amount) : Math.ceil(kvar); const purchaseText = packages ? (item.package ? `köp ${packages} x ${item.package.amount} ${item.package.unit}` : `köp ${packages} förpackning${packages === 1 ? "" : "ar"}`) : "Du har tillräckligt hemma"; const selectedProduct = state.valdaProdukter[item.namn] ? [...state.liveProdukter, ...state.liveValda].find(candidate => candidate.url === state.valdaProdukter[item.namn]) : null; const shownProduct = selectedProduct || product; return `<label class="shopping-item ${state.avklarade.has(item.namn) ? "checked" : ""}"><input type="checkbox" data-shopping="${item.namn}" ${state.avklarade.has(item.namn) ? "checked" : ""}><img class="shopping-product-image ${shownProduct.bild ? "has-image" : ""}" src="${shownProduct.bild || ""}" alt="${shownProduct.marke_och_storlek || shownProduct.namn || item.namn}" loading="lazy"><span class="product-info"><strong>${shownProduct.marke ? `${shownProduct.marke} ` : ""}${shownProduct.namn || item.namn}</strong><small>${shownProduct.marke_och_storlek || (item.package ? `${item.total} ${item.unit} totalt · ${purchaseText}` : `${item.total} st · ${purchaseText}`)}</small>${state.liveProdukter.length ? `<select class="product-choice-inline" data-product-choice="${item.namn}" aria-label="Välj märke och förpackning för ${item.namn}"><option value="">Byt märke eller storlek</option>${state.liveProdukter.map(candidate => `<option value="${candidate.url}" ${state.valdaProdukter[item.namn] === candidate.url ? "selected" : ""}>${candidate.marke_och_storlek || candidate.produktnamn} · ${candidate.pris_kr.toLocaleString("sv-SE")} kr</option>`).join("")}</select>` : ""}</span><span class="pantry-control"><small>Hemma</small><input type="number" min="0" step="50" value="${pantry || ""}" placeholder="0" data-pantry="${item.namn}" aria-label="Hur mycket ${item.namn} du har hemma">${item.package ? `<em>${item.unit}</em>` : ""}</span><a href="${shownProduct.url || STORE_SEARCH[shoppingStore](shownProduct.namn)}" target="_blank" rel="noopener" aria-label="Öppna ${shownProduct.namn} hos ${shoppingBranch?.namn || shoppingStore}">Öppna</a></label>`; }).join("")}` : "";
  loadBasketProductImages(shoppingItems, shoppingStore);
  renderProductChoices();
  document.querySelectorAll("[data-shopping]").forEach(input => input.addEventListener("change", () => { input.checked ? state.avklarade.add(input.dataset.shopping) : state.avklarade.delete(input.dataset.shopping); renderBasket(); }));
  document.querySelectorAll("[data-pantry]").forEach(input => input.addEventListener("input", () => { state.pantry[input.dataset.pantry] = Number(input.value) || 0; saveState(); renderBasket(); }));
  document.querySelectorAll("[data-product-choice]").forEach(select => select.addEventListener("change", () => { state.valdaProdukter[select.dataset.productChoice] = select.value; saveState(); renderBasket(); }));
  const stores = selected.reduce((acc, r) => { acc[r.butik] = (acc[r.butik] || 0) + scaledPurchasePrice(r); return acc; }, {});
  $("storeSummary").innerHTML = Object.keys(stores).length ? `<h3>Butiksstopp</h3>${Object.entries(stores).map(([store, price]) => `<div><span>${shoppingBranch?.namn || store}</span><strong>${money(price)}</strong></div>`).join("")}` : "";
  $("basketTotal").textContent = money(total); $("basketRemaining").textContent = money(Math.abs(remaining));
  $("basketRemainingRow").classList.toggle("over-budget", remaining < 0);
  $("basketRemainingRow").querySelector("span").textContent = remaining < 0 ? "Över budget" : "Kvar av budgeten";
}

function loadBasketProductImages(items, store) { if (!["Willys", "Hemköp"].includes(store)) return; const fallback = state.liveProdukter[0]; items.filter(item => !state.liveProduktMap[item.namn] && !state.liveLaddar.has(item.namn)).forEach(async item => { state.liveLaddar.add(item.namn); try { const response = await fetch(`${API_BASE}/api/products?butik=${encodeURIComponent(store)}&q=${encodeURIComponent(item.namn)}`); const data = await response.json(); state.liveProduktMap[item.namn] = data.produkter?.[0] || fallback || null; } catch { state.liveProduktMap[item.namn] = fallback || null; } finally { state.liveLaddar.delete(item.namn); renderBasket(); applyLiveImages(); } }); }
function applyLiveImages() { document.querySelectorAll("[data-pantry]").forEach(input => { const product = state.liveProduktMap[input.dataset.pantry]; const image = input.closest(".shopping-item")?.querySelector(".shopping-product-image"); if (product?.bild && image) { image.src = product.bild; image.classList.add("has-image"); image.alt = product.marke_och_storlek || product.produktnamn; } }); }
function renderProductChoices() {}

function aggregateShopping(selected) {
  const totals = {};
  selected.forEach(recipe => recipe.ingredienser.forEach(ingredient => {
    const quantity = RECIPE_QUANTITIES[recipe.id]?.[ingredient];
    const packageInfo = PACKAGE_INFO[ingredient];
    const amount = quantity ? quantity[0] : 1, unit = quantity ? quantity[1] : "st";
    if (!totals[ingredient]) totals[ingredient] = { namn: ingredient, total: 0, unit, package: packageInfo };
    totals[ingredient].total += amount;
  }));
  return Object.values(totals).sort((a, b) => a.namn.localeCompare(b.namn, "sv"));
}

function render() { renderRecipes(); renderBasket(); renderLiveSelection(); }
function step(key, delta, min, max) { state[key] = Math.min(max, Math.max(min, state[key] + delta)); $(`${key === "personer" ? "people" : "meals"}Value`).textContent = state[key]; saveState(); render(); }
$("budgetInput").value = state.budget; $("peopleValue").textContent = state.personer; $("mealsValue").textContent = state.middagar; $("storeInput").value = state.butik; $("postcodeInput").value = state.postnummer;
$("budgetInput").addEventListener("input", e => { state.budget = Number(e.target.value) || 0; saveState(); renderBasket(); });
$("postcodeInput").addEventListener("input", e => { state.position = null; state.postnummer = e.target.value.replace(/\D/g, ""); saveState(); chooseMenu(false); });
$("locateBtn").addEventListener("click", () => { if (!navigator.geolocation) return; $("locateBtn").textContent = "Hämtar..."; navigator.geolocation.getCurrentPosition(({ coords }) => { state.position = { lat: coords.latitude, lon: coords.longitude }; $("locateBtn").textContent = "Hittad"; chooseMenu(false); }, () => { $("locateBtn").textContent = "Försök igen"; }); });
$("storeInput").addEventListener("change", e => { state.butik = e.target.value; saveState(); chooseMenu(); });
let searchDebounceTimer = null;
$("recipeSearch").addEventListener("input", e => {
  state.sokning = e.target.value;
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    state.apiRecipes = [];
    renderRecipes();
    refreshLiveProducts();
  }, 200);
});
$("categoryFilter").addEventListener("change", e => { state.kategori = e.target.value; renderRecipes(); });
let liveRequestId = 0;
async function refreshLiveProducts() { const query = state.sokning.trim(); const requestId = ++liveRequestId; if (query.length < 2 || state.butik === "alla") { $("liveProducts").innerHTML = ""; state.liveProdukter = []; renderBasket(); return; } $("liveProducts").innerHTML = `<p class="live-loading">Söker liveprodukter hos ${selectedBranch()?.namn || chosenStore()}...</p>`; try { const response = await fetch(`${API_BASE}/api/products?butik=${encodeURIComponent(chosenStore())}&q=${encodeURIComponent(query)}`); const data = await response.json(); if (requestId !== liveRequestId || state.sokning.trim() !== query) return; state.liveProdukter = data.produkter || []; $("liveProducts").innerHTML = state.liveProdukter.length ? `<div class="live-products-head"><span>LIVE FRÅN BUTIKEN</span><strong>${state.liveProdukter.length} produkter</strong></div><div class="live-product-grid">${state.liveProdukter.map(product => { const selected = state.liveValda.some(item => item.url === product.url); return `<article class="live-product ${selected ? "live-product-selected" : ""}"><img src="${product.bild || ""}" alt="${product.produktnamn}" loading="lazy"><span class="live-product-name">${product.produktnamn}</span><small>${product.marke_och_storlek || "Storlek visas hos butiken"}</small><strong>${product.pris_kr.toLocaleString("sv-SE", { minimumFractionDigits: 2 })} kr</strong><button type="button" data-live-product='${JSON.stringify(product).replace(/'/g, "&#39;")}' aria-label="Välj ${product.produktnamn}">${selected ? "Vald i listan" : "Välj denna"}</button></article>`; }).join("")}</div>` : `<p class="live-loading">Inga liveprodukter hittades.</p>`; document.querySelectorAll("[data-live-product]").forEach(button => button.addEventListener("click", () => { const product = JSON.parse(button.dataset.liveProduct); state.liveValda = state.liveValda.some(item => item.url === product.url) ? state.liveValda.filter(item => item.url !== product.url) : [...state.liveValda, product]; saveState(); renderLiveSelection(); refreshLiveProducts(); })); renderBasket(); } catch { if (requestId !== liveRequestId) return; state.liveProdukter = []; $("liveProducts").innerHTML = `<p class="live-loading">Livebutiken svarar inte just nu.</p>`; } }
function renderLiveSelection() { const existing = document.querySelector(".live-selection"); if (existing) existing.remove(); if (!state.liveValda.length) return; $("shoppingList").insertAdjacentHTML("afterbegin", `<div class="live-selection"><h3>Valda butikprodukter</h3>${state.liveValda.map(product => `<div class="live-selection-item"><img src="${product.bild || ""}" alt=""><span><strong>${product.produktnamn}</strong><small>${product.marke_och_storlek || ""} · ${product.pris_kr.toLocaleString("sv-SE", { minimumFractionDigits: 2 })} kr</small></span><a href="${product.url}" target="_blank" rel="noopener">Öppna</a></div>`).join("")}</div>`); }
$("timeFilter").addEventListener("change", e => { state.maxTid = Number(e.target.value); renderRecipes(); });
$("favoriteFilter").addEventListener("change", e => { state.baraFavoriter = e.target.checked; renderRecipes(); });
document.querySelectorAll("[data-view]").forEach(item => item.addEventListener("click", () => { const view = item.dataset.view; $("top").className = `app view-${view}`; document.querySelectorAll(".bottom-nav-item").forEach(navItem => navItem.classList.toggle("active", navItem === item)); window.scrollTo({ top: 0, behavior: "smooth" }); }));
$("peopleMinus").addEventListener("click", () => step("personer", -1, 1, 12)); $("peoplePlus").addEventListener("click", () => step("personer", 1, 1, 12));
$("mealsMinus").addEventListener("click", () => step("middagar", -1, 1, 6)); $("mealsPlus").addEventListener("click", () => step("middagar", 1, 1, 6));
$("generateBtn").addEventListener("click", chooseMenu); $("refreshBtn").addEventListener("click", () => { RECEPT.push(RECEPT.shift()); chooseMenu(); });
const now = new Date(), first = new Date(now.getFullYear(), 0, 1); $("weekTag").textContent = `v. ${Math.ceil((((now - first) / 86400000) + first.getDay() + 1) / 7)}`;
chooseMenu(false);
renderRecipePage();
window.addEventListener("popstate", renderRecipePage);
