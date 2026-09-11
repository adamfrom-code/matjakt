// ---------------------------------------------------------------------------
// RECEPTVYN
//
// Receptbiblioteket, hyllorna och receptsidan - allt som ritar ett recept på
// skärmen. Låg tidigare utspritt i app.js: bildhjälparna längst upp,
// mapApiRecipe mitt i den gamla produktkatalogen, de tre renderarna i ett
// tvåhundraradersblock trehundra rader längre ned.
//
// Vyn RITAR och binder lyssnare. Den räknar inte ut priser, väljer inte
// butik och avgör inte vem som är premiumkund - allt sådant skickas in en
// gång vid start genom `initRecipesView`, och listan där är avsiktligt lång:
// den visar exakt hur mycket av app.js receptbiblioteket hängde ihop med.
//
// Omritningar går genom render-bussen (E0): en ändring som bara berör
// recepten säger `invalidate("recipes")` i stället för att ropa på
// renderRecipes() direkt. Bussen samlar ihop allt som märkts under samma
// bildruta och kör banan en gång.
// ---------------------------------------------------------------------------

import { addToWeekPlan, removeFromWeekPlan, saveState, state } from "../state/app-state.js";
import { escapeHtml, safeHttpUrl } from "../utils/html.js";
import { filterRecipes } from "../services/recipe-search.js";
import { RECIPE_FALLBACK_ART, RECIPE_FALLBACK_LABEL, kindFor as recipeFallbackKind } from "../services/recipe-fallback.js";
import { loadRecipe, loadShelves, matchesAllTags } from "../data/recipes.js";
import { recipeDetailApiUrl } from "../api/config.js";

const $ = id => document.getElementById(id);

// Det app.js fortfarande äger. Standardvärdena är avsiktligt stumma: en
// modul som importeras utan initRecipesView ska inte låtsas kunna något den
// inte kan, och ett test får skicka in precis de bitar det prövar.
const noop = () => {};
let host = {
  recipeBank: [],                     // RECEPT - samma array, fylld på plats vid start
  recipeDetailFetches: new Set(),     // delas med app.js ensureWeekRecipeDetails
  invalidate: noop,                   // render-bussen (E0)
  render: noop,                       // "allt är inaktuellt"
  money: value => String(value),
  plural: (n, one, many) => `${n} ${n === 1 ? one : many}`,
  macroLine: () => "",
  detailsFor: () => ({}),
  availableRecipes: () => [],
  localRecipesForUser: () => [],
  dietFilterIsActive: () => false,
  selectedBranch: () => null,
  nearbyBranches: () => [],
  branchesLoading: () => false,
  hasPremium: () => false,
  scaledPurchasePrice: () => 0,
  renderRecipeTagFilters: noop,
  recipeRatingMarkup: () => "",
  feedbackMarkup: () => "",
  wireRatingStars: noop,
  wireFeedbackButtons: noop,
  trackEvent: noop,
  showUndoToast: noop,
  setView: noop,
};

export function initRecipesView(overrides = {}) {
  host = { ...host, ...overrides };
}

// Kort och rader ritar bilden i som mest ~400 px - att ladda 940px-varianten
// där är 3x bandbredd för ingenting (85 kB -> 27 kB per kort, mätt).
// Pexels CDN skalar via query-parametrar; receptdetaljen behåller originalet.
const cardImageUrl = url => typeof url === "string" && url.includes("images.pexels.com")
  ? url.replace(/([?&])h=\d+&w=\d+/, "$1h=330&w=480")
  : url;
export function recipeFallbackMarkup(recipe) {
  const kind = recipeFallbackKind(recipe);
  const label = RECIPE_FALLBACK_LABEL[kind];
  // aria-label säger att bilden saknas, inte vad ikonen föreställer: en
  // skärmläsare ska inte tro att vi visar ett foto av rätten.
  return `<span class="recipe-photo recipe-fallback kind-${kind}" role="img" aria-label="Ingen matbild tillgänglig"><svg viewBox="0 0 64 64">${RECIPE_FALLBACK_ART[kind]}</svg><small>${label}</small></span>`;
}
export const recipePhoto = recipe => recipe.bild ? `<img class="recipe-photo" src="${escapeHtml(safeHttpUrl(cardImageUrl(recipe.bild)) || "")}" alt="${escapeHtml(recipe.namn)}" loading="lazy" decoding="async">` : recipeFallbackMarkup(recipe);

export function mapApiRecipe(recipe) {
  // Rå text i state - escapas vid rendering som allt annat. Escape vid
  // intag gav dubbelescapade namn i Vecka/Hem och skickade "&amp;" som
  // varunamn till prismotorn.
  //
  // E12: `steg` var kvar på fel sida av den regeln. Instruktionerna
  // escapades HÄR och en gång till vid utskrift, så ett provider-recept
  // som säger "salt & peppar" stod på skärmen som "salt &amp; peppar".
  // Rättningen är att ta bort den TIDIGA escapningen - aldrig den sena.
  // Rå text i state, escapad vid utskrift: tar man bort fel sida blir ett
  // kosmetiskt fel en XSS-lucka. tests/recipes-view.test.js prövar båda
  // halvorna, just därför.
  const ingredients = (recipe.ingredients || []).map(item => `${item.measure || ""} ${item.name || ""}`.trim()).filter(Boolean);
  return { id: recipe.id, provider: recipe.provider, providerRecipeId: recipe.providerRecipeId, namn: String(recipe.title || ""), butik: "alla", tid: Number(recipe.prepMinutes) || 0, typ: "Provider-recept", portionspris: null, inkopspris: null, sparar: 0, ingredienser: ingredients, hemma: [], beskrivning: "Recept från extern receptkälla. Pris beräknas först när ingredienserna har matchats mot svenska butikprodukter.", steg: recipe.instructions || [], bild: safeHttpUrl(recipe.imageUrl), imageSource: recipe.imageSource, sourceUrl: safeHttpUrl(recipe.sourceUrl), servings: recipe.servings, priceStatus: "unavailable" };
}

// True when the user is browsing rather than looking for something specific.
// Shelves answer "what should we eat this week"; a flat list answers "show me
// the quick vegetarian ones". Showing both at once would be noise.
function recipeBrowsingMode() {
  return !state.sokning.trim() && !state.receptTaggar.size && !state.maxTid
    && !state.minProtein && !state.maxKcal && !state.baraFavoriter
    && state.kategori === "alla";
}

async function syncRecipeShelves() {
  if (state.hyllor.length) return;
  state.hyllor = await loadShelves(12);
  if (state.hyllor.length) host.invalidate("recipes");
}

export function renderRecipeShelves() {
  const container = $("recipeShelves");
  if (!container) return;
  if (!recipeBrowsingMode()) { container.innerHTML = ""; return; }
  syncRecipeShelves();
  container.innerHTML = state.hyllor.map(shelf => `
    <section class="recipe-shelf">
      <h2>${escapeHtml(shelf.title)}</h2>
      <div class="recipe-shelf-row">${shelf.recipes.map(recipeShelfCard).join("")}</div>
    </section>`).join("");
  container.querySelectorAll("[data-shelf-recipe]").forEach(card =>
    card.addEventListener("click", () => openRecipeTab(card.dataset.shelfRecipe)));
}

function recipeShelfCard(recipe) {
  const time = recipe.tid ? `${recipe.tid} min` : "";
  const kcal = recipe.kcal ? `${Math.round(recipe.kcal)} kcal` : "";
  return `<button type="button" class="recipe-shelf-card" data-shelf-recipe="${escapeHtml(recipe.id)}">
    <span class="recipe-shelf-photo">${recipePhoto(recipe)}</span>
    <strong>${escapeHtml(recipe.namn)}</strong>
    <small>${escapeHtml([time, kcal].filter(Boolean).join(" · "))}</small>
  </button>`;
}

export function renderRecipes() {
  const search = state.sokning.trim();
  const dietFilterActive = host.dietFilterIsActive();
  const recipes = filterRecipes(search ? [...host.localRecipesForUser(), ...(dietFilterActive ? [] : state.apiRecipes)] : host.availableRecipes(), search).filter(recipe => (state.kategori === "alla" || recipe.typ === state.kategori)
      && (!state.maxTid || recipe.tid <= state.maxTid)
      && (!state.minProtein || (recipe.protein || 0) >= state.minProtein)
      && (!state.maxKcal || (recipe.kcal || 0) <= state.maxKcal)
      && matchesAllTags(recipe, [...state.receptTaggar])
      && (!state.baraFavoriter || state.favoriter.has(recipe.id)));
  const branch = host.selectedBranch();
  // "Billigast" in a label is a claim; it is only made when the server's
  // real comparison crowned this branch's chain. Otherwise the honest word
  // is "närmast", which is how the branch was actually picked.
  const autoIsWinner = host.hasPremium() && state.dbComparison?.cheapestChain
    && branch?.kedja === state.dbComparison.cheapestChain;
  const storeLabel = state.butik === "auto" ? `${branch?.namn || "ingen butik hittades"}${autoIsWinner ? " (billigast för din lista)" : " (närmast)"}` : state.butik === "alla" ? "alla butiker" : `${branch?.namn || state.butik}`;
  const loading = !state.branches.length && host.branchesLoading();
  // avstandKm can be null (e.g. a branch source that doesn't report distance,
  // or no state.position yet to measure from) - .toFixed() on that used to
  // throw and silently abort the rest of this render pass.
  const distanceText = Number.isFinite(branch?.avstandKm) ? ` och ligger ${branch.avstandKm.toFixed(1)} km bort` : "";
  $("locationHint").textContent = branch ? `${host.nearbyBranches().length} butiksprofiler jämförda${loading ? " (hämtar riktiga butiker nära dig...)" : ""} · ${branch.namn} ${autoIsWinner ? "är billigast för din lista just nu" : "ligger närmast"}${distanceText}.` : (state.postnummer ? `Hittade inga inlästa butiker nära ${state.postnummer} ännu.` : "Ange ditt postnummer så hittar vi butiker nära dig.");
  $("menuSummary").textContent = search ? (dietFilterActive ? `${recipes.length} recept hittades. Externa recept visas inte när kost-/allergifilter är aktivt, eftersom de inte har kontrollerade allergiuppgifter.` : `${recipes.length} recept hittades. Externa recept kan vara på engelska och sakna svenska butikspriser.`) : `${host.plural(Math.min(state.middagar, recipes.length), "middag", "middagar")} för ${host.plural(state.personer, "person", "personer")} från ${storeLabel}. Priserna är uppskattningar.`;
  host.renderRecipeTagFilters();
  renderRecipeShelves();
  // The flat list is hidden while browsing - the shelves ARE the list then.
  const browsing = recipeBrowsingMode();
  $("recipeScroll").hidden = browsing;
  if (browsing) { $("menuSummary").textContent = ""; return; }
  $("recipeScroll").innerHTML = recipes.length ? recipes.map(recipe => {
    const selected = state.valda.has(recipe.id), expanded = state.expanded === recipe.id;
    const details = host.detailsFor(recipe);
    return `<article class="recipe-card ${selected ? "selected" : ""}">
      <button class="recipe-details" data-details="${escapeHtml(recipe.id)}" aria-expanded="${expanded}">
        <span class="recipe-photo-wrap">${recipePhoto(recipe)}<span class="saving">${recipe.sparar ? `Spara ca ${host.money(recipe.sparar)}` : "Från receptdatabas"}</span></span>
        <span class="recipe-name">${escapeHtml(recipe.namn)}</span><span class="recipe-meta">${escapeHtml(recipe.tid)} min · ${escapeHtml(recipe.typ)}</span><span class="recipe-store">Billigast på ${escapeHtml(recipe.butik)}</span>
        <span class="price-tag">${recipe.inkopspris ? `${host.money(host.scaledPurchasePrice(recipe))} i butik` : "Pris hämtas från butik"}</span><span class="portion-price">${recipe.portionspris ? `ca ${host.money(recipe.portionspris)} per portion` : "Ingredienser och instruktioner finns"}</span>
        ${recipe.kcal ? `<span class="recipe-macros">${host.macroLine(recipe)}</span>` : ""}
      </button>
      ${expanded ? `<div class="ingredients"><p class="recipe-description">${escapeHtml(details.beskrivning || "En god vardagsrätt med enkla råvaror.")}</p><strong>Du behöver köpa</strong><p>${escapeHtml(recipe.ingredienser.join(", "))}</p><small>Hemma: ${escapeHtml(recipe.hemma.join(", "))}</small>${details.steg ? `<ol class="recipe-steps">${details.steg.map(step => `<li>${escapeHtml(step)}</li>`).join("")}</ol>` : ""}${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${escapeHtml(details.tips)}</p>` : ""}</div>` : ""}
      <button class="favorite-btn ${state.favoriter.has(recipe.id) ? "is-favorite" : ""}" data-favorite="${escapeHtml(recipe.id)}" aria-label="${state.favoriter.has(recipe.id) ? "Ta bort favorit" : "Spara som favorit"}">${state.favoriter.has(recipe.id) ? "★" : "☆"}</button><button class="add-btn" data-add="${escapeHtml(recipe.id)}">${selected ? "✓ Tillagd" : "+ Lägg till"}</button>
    </article>`;
  }).join("") : `<p class="empty-state">Inga recept matchar din sökning eller butik ännu.</p>`;
  document.querySelectorAll("[data-details]").forEach(btn => btn.addEventListener("click", () => openRecipeTab(btn.dataset.details)));
  document.querySelectorAll("[data-add]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.add; state.valda.has(id) ? removeFromWeekPlan(id) : addToWeekPlan(id); saveState(); host.render(); }));
  document.querySelectorAll("[data-favorite]").forEach(btn => btn.addEventListener("click", () => { const id = btn.dataset.favorite; state.favoriter.has(id) ? state.favoriter.delete(id) : state.favoriter.add(id); saveState(); host.invalidate("recipes"); }));
}

// U65: kom ihåg var i listan man var.
//
// Att öppna ett recept ska börja överst i receptet - men att gå TILLBAKA
// ska lämna en där man stod. Förut gjorde tillbakavägen scrollTo(0, 0),
// alltså nollställdes platsen med flit, och den som bläddrade i en lång
// receptlista fick börja om efter varje titt. Filtren låg redan kvar i
// state; det enda som tappades var raden man tittade på.
let listScrollY = 0;
// Webbläsaren återställer SIN ihågkomna position vid bakåtnavigering, och
// den positionen är var man stod INNE i receptet. Den slogs mot appens egen
// återställning och landade emellan - 1200 px före, 1472 px efter i test.
// Med "manual" äger appen scrollen, vilket är enda sättet att göra löftet i
// U65 sant.
//
// `typeof history` tillkom i flytten: raden körs nu när MODULEN läses in,
// och modulen läses in av tester utan webbläsare. I appen är den oförändrad.
if (typeof history !== "undefined" && "scrollRestoration" in history) history.scrollRestoration = "manual";

export function openRecipeTab(id) {
  listScrollY = window.scrollY;
  history.pushState({ recept: id }, "", `${location.pathname}?recept=${encodeURIComponent(id)}`);
  renderRecipePage();
}

function formatMeasure(amount) {
  if (amount == null) return "";
  const whole = Math.floor(amount);
  const fraction = Math.round((amount - whole) * 100) / 100;
  const parts = { 0.25: "¼", 0.33: "⅓", 0.5: "½", 0.67: "⅔", 0.75: "¾" };
  if (parts[fraction]) return whole ? `${whole} ${parts[fraction]}` : parts[fraction];
  return Number.isInteger(amount) ? String(amount) : String(Math.round(amount * 10) / 10);
}

// Ingrediensmängderna skalas till HUSHÅLLET - receptbankens rader gäller
// recipe.servings portioner, men veckan lagas för state.personer.
function scaledIngredientRows(recipe) {
  const structured = Array.isArray(recipe.ingredients) ? recipe.ingredients : [];
  if (!structured.length) return null;
  const scale = state.personer / (recipe.servings || 4);
  const rows = { buy: [], home: [] };
  structured.forEach(item => {
    const target = item.pantryStaple ? rows.home : rows.buy;
    const amount = item.amount != null && !item.pantryStaple ? formatMeasure(item.amount * scale) : "";
    target.push({ amount, unit: item.pantryStaple ? "" : (item.unit || ""), name: item.name, optional: item.optional });
  });
  return rows;
}

export async function renderRecipePage() {
  const id = new URLSearchParams(location.search).get("recept");
  if (!id) {
    $("top").hidden = false;
    $("recipePage").hidden = true;
    // Efter renderingen, annars är sidan ännu för kort och scrollen klipps
    // till noll. setView() scrollar också till toppen, så återställningen
    // måste komma efter den - därför två bildrutor, inte en.
    // MOMENTAN, inte mjuk. styles.css sätter html{scroll-behavior:smooth},
    // så ett vanligt scrollTo blir en animation över ~300 ms - och en
    // animation går att störa. Mätt: återställningen landade rätt på 1198 px
    // och drogs sedan vidare till 1477 av något annat som hann emellan.
    // Att komma tillbaka dit man var ska inte se ut som en resa.
    const mål = listScrollY;
    requestAnimationFrame(() => requestAnimationFrame(
      () => window.scrollTo({ top: mål, left: 0, behavior: "instant" })));
    return;
  }
  let allRecipes = [...host.recipeBank, ...state.apiRecipes];
  // A card deliberately ships without steps and structured ingredients (the
  // list payload stays small). The detail PAGE is the one place that needs
  // everything, so fetch the full recipe once and merge it into the same
  // object every list references.
  const found = allRecipes.find(r => r.id === new URLSearchParams(location.search).get("recept"));
  if (found && found.priceStatus !== "unavailable"
      && (!Array.isArray(found.steg) || !found.steg.length)
      && !host.recipeDetailFetches.has(found.id)) {
    host.recipeDetailFetches.add(found.id);
    loadRecipe(found.id).then(detail => {
      // Samma regel som i ensureWeekRecipeDetails: null är ett definitivt
      // "finns inte" och frågas aldrig om igen; ett kastat fel är okänt och
      // släpper id:t fritt för nästa försök.
      if (!detail) return;
      Object.assign(found, detail, { steg: detail.instructions || detail.steg || [] });
      renderRecipePage();
    }).catch(() => host.recipeDetailFetches.delete(found.id));
  }
  let recipe = allRecipes.find(item => item.id === id);
  if (!recipe && id.includes(":")) {
    try { const response = await fetch(recipeDetailApiUrl(id)); if (response.ok) { const data = await response.json(); recipe = mapApiRecipe(data.recipe); state.apiRecipes.push(recipe); allRecipes = [...host.recipeBank, ...state.apiRecipes]; } } catch { /* The friendly not-found state below remains visible. */ }
  }
  if (!recipe) {
    // A deep link (?recept=...) arrives BEFORE the recipe bank has loaded.
    // Returning to Hem here made every shared recipe link land on the start
    // page; show the page in a calm loading state instead - the bank's
    // loadRecipes().then() re-runs this render the moment recipes exist.
    $("top").hidden = true;
    $("recipePage").hidden = false;
    $("recipePage").innerHTML = `<button class="recipe-back" type="button" aria-label="Tillbaka till recepten"></button><article class="full-recipe"><div class="full-recipe-fallback">${recipePhoto({})}</div><h1>Hämtar receptet…</h1><p class="full-recipe-description">Ett ögonblick.</p></article>`;
    $("recipePage").querySelector(".recipe-back").addEventListener("click", () => { history.pushState(null, "", location.pathname); renderRecipePage(); host.setView("recipes"); });
    return;
  }
  const details = host.detailsFor(recipe);
  $("top").hidden = true;
  document.querySelectorAll(".bottom-nav-item").forEach(item =>
    item.classList.toggle("active", item.dataset.view === "recipes")); /* bottennavigeringen följer med in på receptsidan - flikarna ska alltid
     vara ett tryck bort */ $("recipePage").hidden = false;
  const chips = [
    recipe.tid ? `${recipe.tid} min` : null,
    `${state.personer} portioner`,
    recipe.difficulty || null,
    recipe.priceStatus !== "unavailable" && recipe.portionspris ? `${host.money(recipe.portionspris)}/portion` : null,
  ].filter(Boolean);
  const ingredientRows = scaledIngredientRows(recipe);
  const ingredientsMarkup = ingredientRows
    ? `${ingredientRows.buy.map(row => `<div class="ing-row${row.optional ? " ing-optional" : ""}"><strong>${escapeHtml([row.amount, row.unit].filter(Boolean).join(" "))}</strong><span>${escapeHtml(row.name)}${row.optional ? " <em>(valfritt)</em>" : ""}</span></div>`).join("")}${ingredientRows.home.length ? `<p class="ing-home-label">Har du säkert hemma</p>${ingredientRows.home.map(row => `<div class="ing-row ing-home"><strong></strong><span>${escapeHtml(row.name)}</span></div>`).join("")}` : ""}`
    : `${recipe.ingredienser.map(item => `<div class="ing-row"><strong></strong><span>${escapeHtml(item)}</span></div>`).join("")}`;
  const stepsMarkup = (details.steg || []).map((step, index) => `<label class="step-row"><input type="checkbox" data-step-check="${index}"><span class="step-number">${index + 1}</span><span class="step-text">${escapeHtml(step)}</span></label>`).join("");
  $("recipePage").innerHTML = `<button class="recipe-back" type="button" aria-label="Tillbaka till recepten"></button><article class="full-recipe">${recipe.bild ? `<img class="recipe-photo full-recipe-hero" src="${escapeHtml(safeHttpUrl(recipe.bild) || "")}" alt="${escapeHtml(recipe.namn)}">` : `<div class="full-recipe-fallback">${recipePhoto(recipe)}</div>`}<p class="eyebrow">${escapeHtml(recipe.typ)}</p><h1>${escapeHtml(recipe.namn)}</h1><div class="recipe-chips">${chips.map(chip => `<span class="recipe-chip">${escapeHtml(chip)}</span>`).join("")}</div>${recipe.kcal ? `<p class="full-recipe-macros">${host.macroLine(recipe)}</p>` : ""}<p class="full-recipe-description">${escapeHtml(details.beskrivning || "En god svensk vardagsrätt.")}</p><div class="recipe-cta-row"><button class="btn btn-primary recipe-add-primary" type="button" data-recipe-add="${escapeHtml(recipe.id)}"><span>${state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"}</span><span>＋</span></button><button type="button" class="recipe-share-btn" data-recipe-share aria-label="Dela receptet">Dela</button></div><section class="recipe-block"><div class="ing-head"><h2>Ingredienser</h2><span>${state.personer} portioner</span></div>${ingredientsMarkup}</section><section class="recipe-block"><h2>Gör så här</h2><div class="steps">${stepsMarkup}</div></section>${details.tips ? `<p class="recipe-tip"><strong>Kökstips:</strong> ${escapeHtml(details.tips)}</p>` : ""}<div class="recipe-block">${host.recipeRatingMarkup(recipe.id)}${host.feedbackMarkup(recipe.id)}</div></article>`;
  $("recipePage").querySelector(".recipe-back").addEventListener("click", () => history.back());
  // Avbockade steg medan man lagar - sparas lokalt per recept så ett
  // vridet-bort-och-tillbaka på telefonen inte tappar var man var.
  const stepKey = `matjakt-steps-${recipe.id}`;
  let done = [];
  try { done = JSON.parse(localStorage.getItem(stepKey) || "[]"); } catch { /* trasig lagring = börja om */ }
  $("recipePage").querySelectorAll("[data-step-check]").forEach(box => {
    const index = Number(box.dataset.stepCheck);
    box.checked = done.includes(index);
    box.closest(".step-row").classList.toggle("step-done", box.checked);
    box.addEventListener("change", () => {
      box.checked ? done.push(index) : (done = done.filter(x => x !== index));
      box.closest(".step-row").classList.toggle("step-done", box.checked);
      try { localStorage.setItem(stepKey, JSON.stringify(done)); } catch { /* full lagring - bocken lever ändå i DOM */ }
    });
  });
  $("recipePage").querySelector("[data-recipe-share]")?.addEventListener("click", async () => {
    const url = `https://matjakt.store/app/?recept=${encodeURIComponent(recipe.id)}`;
    host.trackEvent("recept_delat");
    // Web Share där det finns (mobilen), annars urklipp - båda vägarna
    // slutar i samma delbara djuplänk.
    if (navigator.share) {
      try { await navigator.share({ title: recipe.namn, url }); } catch { /* avbruten delning är inget fel */ }
    } else {
      try { await navigator.clipboard.writeText(url); host.showUndoToast("Länk kopierad", () => {}); } catch { /* utan urklippsrättighet finns adressfältet */ }
    }
  });
  $("recipePage").querySelector("[data-recipe-add]").addEventListener("click", event => { state.valda.has(recipe.id) ? removeFromWeekPlan(recipe.id) : addToWeekPlan(recipe.id); saveState(); host.render(); event.currentTarget.querySelector("span").textContent = state.valda.has(recipe.id) ? "Tillagd i veckan" : "Lägg till i veckan"; });
  host.wireRatingStars($("recipePage"), recipe.id);
  host.wireFeedbackButtons($("recipePage"), recipe.id);
  requestAnimationFrame(() => window.scrollTo(0, 0));
  let touchStartX = 0; $("recipePage").ontouchstart = event => { touchStartX = event.changedTouches[0].screenX; }; $("recipePage").ontouchend = event => { const distance = event.changedTouches[0].screenX - touchStartX; if (Math.abs(distance) < 70) return; const ids = allRecipes.map(item => item.id), currentIndex = ids.indexOf(id), targetIndex = distance < 0 ? currentIndex + 1 : currentIndex - 1; if (targetIndex >= 0 && targetIndex < ids.length) openRecipeTab(ids[targetIndex]); else if (distance > 0) history.back(); };
}
