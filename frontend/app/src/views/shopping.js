// ---------------------------------------------------------------------------
// HANDLA-VYN
//
// Inköpslistan: aggregatet bakom den, raderna den ritar, knapparna på varje
// rad och de extra varorna under den. Låg tidigare utspritt över fyra
// hundraradersblock i app.js.
//
// Modulen känner till DOM:en bara genom det den får in ($, render*-anropen,
// wiring). Allt som hör till prissättning, butiksval, hushåll och skafferi
// stannar i app.js och skickas in via initShoppingView() - det är det som
// gör det här testbart utan webbläsare.
//
// Tre buggar löstes när koden flyttade hit:
//
//   E10  "Ser något fel ut?" band en ny lyssnare vid VARJE omritning på en
//        knapp som aldrig ritades om. Bindningen sitter nu där knappen
//        faktiskt skapas, och binder aldrig samma nod två gånger.
//   E11  Kedjelistans rubriksumma räknades i fullt flyttal medan raderna
//        skrevs ut avrundade var för sig. Rubriken summerar nu exakt de tal
//        raderna visar.
//   E14  aggregateShopping() såg ut som en ren beräkning men raderade ur
//        state under rendering, utan att spara. Den är ren nu; beskärningen
//        av spöknamn är sin egen funktion som körs när veckans recept är
//        färdigladdade.
// ---------------------------------------------------------------------------

import { aggregateIngredients, packagesFor } from "../services/calculations.js";
import { categoryFor, groupByCategory } from "../services/categories.js";
import { extraLineTotal, extraUnitPrice, removeExtra, setQty } from "../services/extras.js";
import { ALREADY_HAVE, NEED_TO_BUY, PURCHASED, REMOVED, foldName, shoppingRows } from "../services/household-state.js";
import { saveState, selectedRecipes, state } from "../state/app-state.js";
import { escapeHtml, safeHttpUrl } from "../utils/html.js";
import { teckenförklaringMarkup } from "./pris.js";
import { initSparkvitto, renderSparkvitto } from "./sparkvitto.js";

// Allt vyn behöver men inte äger. Skickas in en gång vid uppstart; namnen
// är exakt de app.js använder, så varje flyttad rad står oförändrad nedan.
const app = {};
export function initShoppingView(dependencies) {
  Object.assign(app, dependencies);
  // H2 · sparkvittot ritar i sin egen nod inne i #shoppingComplete och behöver
  // inget annat av appen än vägen till DOM:en. Det är Handla som vet när
  // listan är avbockad, så det är härifrån kvittot beställs - aldrig med en
  // egen andra bedömning av när veckan är färdighandlad.
  initSparkvitto({ $: app.$ });
}

// ---------------------------------------------------------------------------
// E11 · RUBRIKEN SUMMERAR DET RADERNA VISAR
//
// Kedjelistans rubrik lade ihop item.totalCost i fullt flyttal och rundade
// summan, medan varje rad skrevs ut avrundad för sig (money() = hela
// kronor). Tjugo rader à 12,49 kr blev "250 kr" i rubriken över tjugo rader
// som läser 12 kr - 240 kr. Tio kronors skillnad, i den ruta vars hela
// existensberättigande är att rubriken och listan säger samma sak.
//
// Nu räknas summan i ÖRE över de belopp raderna faktiskt skriver ut. Öret
// finns för att hundra additioner inte ska driva iväg i binära bråk; det är
// de avrundade radbeloppen, inte råpriserna, som läggs ihop.
// ---------------------------------------------------------------------------

// Beloppet raden skriver ut, i kronor - eller null när raden inte visar
// något belopp alls ("Pris saknas", "Antal osäkert"). Samma avrundning som
// money() gör, på ett ställe, så rubriken inte kan tolka den annorlunda.
export function chainRowAmount(item) {
  if (!item || item.priceStatus === "missing") return null;
  if (item.totalCost == null) return null;
  const value = Number(item.totalCost);
  return Number.isFinite(value) ? Math.round(value) : null;
}

export function chainListTotal(items) {
  const ore = (items || []).reduce((sum, item) => {
    const amount = chainRowAmount(item);
    return amount == null ? sum : sum + Math.round(amount * 100);
  }, 0);
  return ore / 100;
}

// ---------------------------------------------------------------------------
// E10 · EN KNAPP, EN LYSSNARE
//
// "Ser något fel ut?" renderas in i #chainListBody av
// chainShoppingListMarkup - en nod som ingen omritning av Handla rör.
// Bindningen låg ändå i veckoöversikten, som ritas om vid varje livepris,
// varje synksvar och varje avbockning: efter en stund satt N lyssnare på
// SAMMA knapp och ett klick skickade N prisfel_rapporterat.
//
// Bindningen sitter nu där knappen skapas, och en nod som redan är bunden
// binds aldrig om - oavsett vem som råkar anropa det här en gång till.
// ---------------------------------------------------------------------------

export function wireReportPriceButtons(container, { onReport } = {}) {
  if (!container) return 0;
  let wired = 0;
  container.querySelectorAll("[data-report-price]").forEach(button => {
    if (button.dataset.reportWired) return;
    button.dataset.reportWired = "1";
    wired += 1;
    button.addEventListener("click", () => {
      if (onReport) onReport();
      button.textContent = "Tack! Vi kollar på det.";
      button.disabled = true;
    });
  });
  return wired;
}

// ---------------------------------------------------------------------------
// E14 · SPÖKNAMN BESKÄRS EN GÅNG, INTE UNDER RENDERING
//
// Ett receptBYTE kan stryka ingredienser vars namn ligger kvar i
// removedItems, avklarade och harHemma - spöknamn som får "Återställ alla"
// att ljuga om antalet och som visar en vara förbockad som "redan handlad"
// när ett senare byte återinför samma namn.
//
// Beskärningen låg inuti aggregateShopping(), som anropas från ett halvdussin
// ställen mitt under rendering och dessutom aldrig sparade det den raderade.
// Två fel i ett: en "ren" beräkning som muterade delat tillstånd, och en
// mutation som inte överlevde en omladdning.
//
// Värre: namnlistan byggdes på aggregatet, och aggregatet filtrerar bort
// optional-ingredienser i den strukturerade grenen medan kortprojektionen
// behåller dem. Så fort receptdetaljerna landade försvann de valfria
// ingredienserna ur aggregatet - och användarens "köpt"/"har hemma" på dem
// raderades tyst. Namnlistan nedan är därför UNIONEN av allt veckans recept
// kan tänkas be om: aggregatet, kortets ingredienser och varje strukturerad
// rad, valfria och skafferivaror inkluderade. Ett namn beskärs bara när
// ingen av dem känner igen det.
// ---------------------------------------------------------------------------

export function weekIngredientNames(recipes) {
  const names = new Set();
  const add = name => { if (typeof name === "string" && name) names.add(name); };
  const usable = (recipes || []).filter(Boolean);
  aggregateIngredients(usable.filter(recipe => recipe.priceStatus !== "unavailable"),
                       app.recipeQuantities || {}, app.packageInfo || {}, state.personer)
    .forEach(item => add(item.namn));
  usable.forEach(recipe => {
    (recipe.ingredienser || []).forEach(add);
    (Array.isArray(recipe.ingredients) ? recipe.ingredients : []).forEach(item => add(item?.name));
    (recipe.hemma || []).forEach(add);
  });
  return names;
}

// Veckan som beskärningen senast kördes mot. Beskärningen ska köras EN gång
// per färdigladdad vecka - inte per omritning, och inte per aggregat.
let prunedWeekSignature = null;
export function resetPhantomPruneGuard() { prunedWeekSignature = null; }

// Returnerar true när något faktiskt beskars, så anroparen vet om den har
// något att spara och rita om. Falskt vid oförändrad vecka, tom vecka och
// när ingenting var ett spöknamn.
export function prunePhantomItemNames(recipes) {
  const usable = (recipes || []).filter(Boolean);
  // Under uppstart är veckan tom för att recepten inte laddats än, inte för
  // att borttagningarna blivit ogiltiga. Att beskära då hade raderat allt.
  if (!usable.length) return false;
  const signature = usable.map(recipe => `${recipe.id}:${Array.isArray(recipe.ingredients) ? recipe.ingredients.length : 0}`).join("|");
  if (signature === prunedWeekSignature) return false;
  prunedWeekSignature = signature;
  const names = weekIngredientNames(usable);
  if (!names.size) return false;
  let pruned = false;
  for (const set of [state.removedItems, state.avklarade, state.harHemma]) {
    for (const name of [...set]) {
      if (!names.has(name)) { set.delete(name); pruned = true; }
    }
  }
  return pruned;
}

// REN. Aggregatet för veckan, minus det användaren tagit bort. Ingenting
// skrivs, ingenting raderas - sex anropsplatser mitt under rendering delar
// den här funktionen och ingen av dem ska kunna ändra tillståndet genom att
// bara räkna.
export function aggregateShopping(selected) {
  // The removal filter lives HERE, at the single choke point every consumer
  // reads from: the Handla list, the totals, the budget, the store
  // comparison, coverage and the per-store carts all recompute from this
  // one function - so a removed item cannot linger in any of them. (The
  // recipeIds pricing path re-aggregates server side and honours the same
  // removals via excludeItems in weekPricingBody.)
  const everything = aggregateIngredients(selected.filter(recipe => recipe.priceStatus !== "unavailable"),
                                          app.recipeQuantities || {}, app.packageInfo || {}, state.personer);
  return everything.filter(item => !state.removedItems.has(item.namn));
}

// ---------------------------------------------------------------------------
// HANDLA: EN RAD
//
// Frågorna en rad ska besvara på ett ögonkast, i den ordningen (§30):
//   Vad är varan?  Hur mycket behöver vi?  Har vi den?  Vad kostar den?
//   Var köps den?
//
// Bilden får aldrig ta över. Den är 44 px, ligger till vänster och ersätts
// av en neutral kategorisymbol när vi inte har en bild vi får visa (§9) -
// aldrig av en annan produkts bild för att fylla tomrummet.
//
// Produktnamn, märke och förpackning skrivs BARA ut när de kommer från en
// riktig matchning i prisdatabasen. En osäker matchning blir inte säker av
// att den får en bild (§35).
// ---------------------------------------------------------------------------

const AT_HOME_ICON = '<svg viewBox="0 0 24 24"><path d="m4 11 8-6 8 6v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1Z"/></svg>';
const BOUGHT_ICON = '<svg viewBox="0 0 24 24"><path d="m5 13 4 4L19 7"/></svg>';

function shoppingActionsMarkup(name, status) {
  if (status === NEED_TO_BUY) {
    return `<div class="shopping-actions">`
      + `<button type="button" class="shopping-action" data-at-home="${escapeHtml(name)}">${AT_HOME_ICON}<span>Har hemma</span></button>`
      + `<button type="button" class="shopping-action buy" data-bought="${escapeHtml(name)}">${BOUGHT_ICON}<span>Köpt</span></button>`
      + `</div>`;
  }
  const label = status === PURCHASED ? "Köpt" : "Finns hemma";
  return `<div class="shopping-actions handled"><span class="shopping-handled-label">${label}</span>`
    + `<button type="button" class="shopping-action" data-need="${escapeHtml(name)}">Behöver köpa</button></div>`;
}

export function amountLabel(amount, unit) {
  // Pieces are bought whole - "Behöver 0.5 st citron" is true in the pot
  // but useless in the store, so st rounds up.
  if (!unit || unit === "st") return `${Math.max(1, Math.ceil(amount))} st`;
  const rounded = amount >= 100 ? Math.round(amount) : Math.round(amount * 10) / 10;
  return `${rounded} ${unit}`;
}

// Vad raden ska säga om mängd. "2 st" ensamt svarade varken på vad veckan
// behöver eller vad man ska lägga i korgen - båda står här.
function quantityTextFor(item, match, status = NEED_TO_BUY) {
  if (!match) {
    const needed = Math.max(0, item.total - (app.pantryForPricing()[item.namn] || 0));
    if (needed > 0) return `Behöver ${amountLabel(needed, item.unit)}`;
    // Skafferiavdraget är en SLUTSATS; att användaren tryckt "behöver köpa"
    // är ett BESKED. Beskedet vinner - annars stod det "Finns hemma" på en
    // rad personen just sagt att de måste handla.
    return status === NEED_TO_BUY ? `Behöver ${amountLabel(item.total, item.unit)}` : "Finns hemma";
  }
  const packageText = match.packageSize && match.packageSize !== "1 st" ? match.packageSize : "";
  const needed = match.neededAmount ? `Behöver ${amountLabel(match.neededAmount, match.neededUnit)}` : "";
  const count = match.packages > 1
    ? `${match.packages} × ${packageText || "förpackning"}`
    : (packageText ? `1 × ${packageText}` : "");
  return [needed, count].filter(Boolean).join(" · ");
}

export function shoppingRowMarkup(item) {
  const match = app.databaseItemFor(item.namn);
  const status = app.itemStatus(item.namn);
  const category = categoryFor(item.namn, match?.category);
  const live = state.livePriser[item.namn];
  // BILDEN: bara en bild vi faktiskt har rätt att visa för just den här
  // produkten. Saknas den ritas kategorisymbolen - aldrig någon annans bild.
  const imageUrl = match?.imageUrl || live?.bild;
  const photo = imageUrl
    ? `<img class="shopping-item-image has-image" src="${escapeHtml(safeHttpUrl(imageUrl) || "")}" alt="" loading="lazy" decoding="async">`
    : app.categoryIconMarkup(category);
  const title = match ? match.productName : (live ? live.produktnamn : item.namn);
  const quantity = quantityTextFor(item, match, status);
  const brand = match ? match.brand : (live ? live.markeOchStorlek : "");
  const meta = escapeHtml([brand, quantity].filter(Boolean).join(" · "));
  // Priset: bara ett riktigt pris får skrivas ut. Ett statiskt katalogpris
  // är en gissning i en kolumn av fakta och skrivs aldrig.
  const dbSyncPending = app.pricingPending() || (!state.dbPricedAt && !state.dbPricingFailedAt);
  const priceMissing = live && live.pris_kr == null;
  // SAMMA räkning som totalsumman (packagesFor), inte en egen kopia: kopian
  // räknade veckans behov i det VISADE måttet (6 dl) mot förpackningens
  // basmått (200 ml) och kom fram till ett paket i stället för tre - raden
  // sa "Behöver 6 dl" och visade priset för en burk. null = antal osäkert
  // (vikt/volym utan paketinfo), 0 = allt finns redan hemma.
  const packages = match ? match.packages : packagesFor(item, app.pantryForPricing());
  const stillFetching = !match && !live && (dbSyncPending || (app.livePricesLoading() && app.validChains.includes(app.chosenStore())));
  const price = match && match.totalCost != null ? app.money(match.totalCost)
    : priceMissing ? "Pris saknas"
      : live ? (packages == null ? "" : app.money(live.pris_kr * packages))
        : stillFetching ? "" : "Pris saknas";
  const store = match ? (state.dbChainTotals[app.currentPricedChain()]?.chain || app.currentPricedChain() || "") : "";
  const onCampaign = match && match.campaignPrice != null && match.regularPrice != null
    && match.campaignPrice < match.regularPrice;
  const campaign = onCampaign
    ? `<small class="shopping-item-campaign">Kampanj ${app.money(match.campaignPrice)} (ord. ${app.money(match.regularPrice)})</small>`
    : (live?.kampanj?.text ? `<small class="shopping-item-campaign">${escapeHtml(live.kampanj.text)}</small>` : "");
  // Flaggad, inte gömd: när receptets enhet inte går att räkna om mot
  // förpackningens gissar motorn "en förpackning". Det är en gissning om
  // ANTAL, och den som står i affären är den som kan avgöra.
  // Antalet är osäkert både när prisdatabasen säger det och när ett livepris
  // saknar paketinfo för en vikt-/volymvara - i båda fallen ska raden säga
  // det i stället för att visa ett tal vi inte kan stå för.
  const inexact = match?.priceStatus === "estimated" || (!match && live && packages == null)
    ? '<small class="item-status estimated">Antal osäkert</small>'
    : (stillFetching ? '<small class="item-status loading">pris hämtas…</small>' : "");
  const comparePrice = match?.comparisonPrice != null
    ? `<small class="shopping-item-compare">${app.money(match.comparisonPrice)}/${/l|ml|dl/.test(match.packageUnit || "") ? "l" : "kg"}</small>` : "";
  return `<article class="shopping-item status-${status.toLowerCase()}">`
    + `<div class="shopping-item-main">${photo}`
    + `<span class="shopping-item-info"><strong>${escapeHtml(title)}</strong>`
    + `<small class="shopping-item-meta">${meta}</small>${campaign}</span>`
    + `<span class="shopping-item-price"><strong class="${price === "Pris saknas" ? "price-missing" : ""}">${price}</strong>`
    + `${store ? `<small class="shopping-item-store">${escapeHtml(store)}</small>` : ""}${comparePrice}${inexact}</span>`
    + `<button type="button" class="shopping-remove" data-remove-item="${escapeHtml(item.namn)}" aria-label="Ta bort ${escapeHtml(item.namn)} ur listan">×</button></div>`
    + shoppingActionsMarkup(item.namn, status)
    + `</article>`;
}

// Handlade och hemmavarande rader samlas under listan i stället för att
// försvinna: den som bockat fel ska kunna se det och ta tillbaka varan.
export function handledRowMarkup(item) {
  const status = app.itemStatus(item.namn);
  const label = status === PURCHASED ? "Köpt" : "Finns hemma";
  return `<div class="shopping-handled-row"><span><strong>${escapeHtml(item.namn)}</strong><small>${label}</small></span>`
    + `<button type="button" class="btn-ghost" data-need="${escapeHtml(item.namn)}">Behöver köpa</button></div>`;
}

export function wireShoppingRowActions(container) {
  container.querySelectorAll("[data-at-home]").forEach(button => button.addEventListener("click", () => {
    const name = button.dataset.atHome;
    app.setItemStatus(name, ALREADY_HAVE, { location: app.suggestedLocationFor(name) });
    app.showUndoToast(`${name} · finns hemma, lagt i ${app.pantryTabLabels[app.suggestedLocationFor(name)]}`, app.undoLastShoppingAction);
  }));
  container.querySelectorAll("[data-bought]").forEach(button => button.addEventListener("click", () => {
    const name = button.dataset.bought;
    if (!window.__matjaktListaAnvand) { window.__matjaktListaAnvand = true; app.trackEvent("lista_anvand"); }
    app.setItemStatus(name, PURCHASED, { addToPantry: true, location: app.suggestedLocationFor(name) });
    app.noteStaplePurchase(name);
    app.showUndoToast(`${name} · köpt, lagt i ${app.pantryTabLabels[app.suggestedLocationFor(name)]}`, app.undoLastShoppingAction);
  }));
  container.querySelectorAll("[data-need]").forEach(button => button.addEventListener("click", () => {
    app.setItemStatus(button.dataset.need, NEED_TO_BUY);
  }));
  container.querySelectorAll("[data-remove-item]").forEach(button => button.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    app.removeShoppingItem(button.dataset.removeItem);
  }));
}

// ---- Extra varor under listan ----------------------------------------------

function extraRowMarkup(extra, chain) {
  const match = (state.extraMatches[chain] || {})[extra.id];
  const line = extraLineTotal(extra, chain, match);
  const unit = extraUnitPrice(extra, chain, match);
  const fromOtherChain = extra.chain && extra.chain !== chain;
  const photo = (match?.imageUrl || extra.imageUrl)
    ? `<img class="shopping-item-image has-image" src="${escapeHtml(safeHttpUrl(match?.imageUrl || extra.imageUrl) || "")}" alt="" loading="lazy">`
    : app.categoryIconMarkup("Övrigt");
  const displayName = match?.productName || extra.name;
  const metaBits = [];
  if (match?.packageSize || extra.packageSize) metaBits.push(match?.packageSize || extra.packageSize);
  if (extra.source === "campaign") metaBits.push(`Kampanj hos ${extra.chain}`);
  if (fromOtherChain && !match) metaBits.push(`Ingen matchande produkt hos ${chain}`);
  if (!extra.chain && !match) metaBits.push("Ingen säker prismatch – egen rad");
  const priceText = line != null ? app.money(line)
    : '<span class="price-missing">–</span>';
  const unitNote = extra.qty > 1 && unit != null ? `<small>${extra.qty} × ${app.money(unit)}</small>` : "";
  return `<div class="shopping-item extra-item ${extra.checked ? "checked" : ""}">
    <input type="checkbox" data-extra-check="${extra.id}" ${extra.checked ? "checked" : ""}>
    ${photo}
    <span class="shopping-item-info"><strong>${escapeHtml(displayName)}</strong>
      <small class="shopping-item-meta">${escapeHtml(metaBits.join(" · "))}</small></span>
    <span class="extra-qty"><button type="button" data-extra-minus="${extra.id}">−</button><b>${extra.qty}</b><button type="button" data-extra-plus="${extra.id}">+</button></span>
    <span class="shopping-item-price"><strong>${priceText}</strong>${unitNote}</span>
    <button type="button" class="extra-remove" data-extra-remove="${extra.id}" aria-label="Ta bort">×</button>
  </div>`;
}

export function renderExtraItems(chain) {
  const section = app.$("extraItemsSection");
  if (!section) return;
  section.hidden = !state.extraItems.length;
  app.$("weekListTitle").hidden = !state.extraItems.length;
  if (!state.extraItems.length) return;
  app.$("extraItemsList").innerHTML = state.extraItems.map(extra => extraRowMarkup(extra, chain)).join("");
  section.querySelectorAll("[data-extra-check]").forEach(el => el.addEventListener("change", () => {
    state.extraItems = state.extraItems.map(e => e.id === el.dataset.extraCheck ? { ...e, checked: el.checked } : e);
    saveState();
    // Utan omritning fick raden aldrig sin checked-stil och "Allt handlat"
    // utvärderades inte när sista extra-varan bockades av.
    renderBasket();
  }));
  section.querySelectorAll("[data-extra-plus]").forEach(el => el.addEventListener("click", () => {
    const current = state.extraItems.find(e => e.id === el.dataset.extraPlus);
    state.extraItems = setQty(state.extraItems, el.dataset.extraPlus, (current?.qty || 1) + 1);
    saveState(); renderBasket();
  }));
  section.querySelectorAll("[data-extra-minus]").forEach(el => el.addEventListener("click", () => {
    const current = state.extraItems.find(e => e.id === el.dataset.extraMinus);
    state.extraItems = setQty(state.extraItems, el.dataset.extraMinus, (current?.qty || 1) - 1);
    saveState(); renderBasket();
  }));
  section.querySelectorAll("[data-extra-remove]").forEach(el => el.addEventListener("click", () => {
    state.extraItems = removeExtra(state.extraItems, el.dataset.extraRemove);
    saveState(); renderBasket();
  }));
  app.syncExtraMatches(chain);
}

// Listan som Handla faktiskt ritar.
//
// Utan hushåll: veckans aggregat, precis som förut.
// Med hushåll: serverns rader - så en vara någon ANNAN lade till syns här -
// berikade med veckans mängd och förpackning där raderna möts. En rad som
// bara finns hos hushållet (manuellt tillagd, eller från den andres vecka)
// får sin mängd från raden själv.
export function shoppingItemsForView(selected) {
  const weekItems = aggregateShopping(selected);
  if (!app.householdActive()) return weekItems;
  const byName = new Map(weekItems.map(item => [foldName(item.namn), item]));
  const rows = shoppingRows(state.household).filter(row => row.status !== REMOVED);
  const merged = rows.map(row => {
    const weekItem = byName.get(foldName(row.name));
    if (weekItem) { byName.delete(foldName(row.name)); return weekItem; }
    return { namn: row.name, total: row.amount || 1, unit: row.unit || "st", package: null };
  });
  // Veckans rader som ännu inte hunnit ut till servern visas ändå - annars
  // blinkade listan tom den sekund en ny vecka skapades.
  return [...merged, ...byName.values()];
}

export function renderBasket() {
  // Två vyer på samma vecka: veckoöversikten ritar DAGAR och behöver de tomma
  // platserna kvar (weekDays), medan allt som aggregerar, prissätter och
  // jämför frågar efter RÄTTER (selected). Se plannedRecipes() längst upp.
  const weekDays = selectedRecipes();
  const selected = weekDays.filter(Boolean);
  app.ensureWeekRecipeDetails();
  const shoppingItems = shoppingItemsForView(selected);
  // The header total must be the SAME number the store-comparison widget
  // shows for the currently selected/pinned branch - a live total when one
  // has been fetched, the static per-package estimate otherwise - never a
  // second, independently-computed figure that could quietly disagree with
  // what's shown right below it.
  const branches = app.nearbyBranches();
  const currentResult = branches.length ? app.computeStoreResults(selected, branches, shoppingItems).find(r => app.sameBranch(r.branch, app.selectedBranch())) : null;
  // Null when no REAL price exists yet - never the static estimate. This
  // value also feeds renderWeekOverview, so one fabricated figure here would
  // show up as fact in two places.
  const activeChain = app.currentPricedChain();
  const extrasCost = app.extrasTotalForChain(activeChain);
  // The header total is the PRICED chain's database result - the same
  // number its store card shows. Falling back to the branch-keyed result
  // left Free showing "pris hämtas…" forever whenever the nearest branch
  // was a chain the server had masked.
  const headerDb = state.dbChainTotals[app.headerPricedChain()];
  const total = headerDb ? headerDb.totalCheckoutCost + extrasCost
    : currentResult && currentResult.source !== "estimate" && currentResult.comparable !== false && app.hasUsablePrice(currentResult)
      ? currentResult.cost + extrasCost : null;
  // ATT HANDLA vs REDAN LÖST. Varor som är köpta eller redan finns hemma
  // lämnar den aktiva listan men försvinner inte: de samlas under den, så
  // ett felklick går att se och ta tillbaka (§5, §6).
  const activeItems = shoppingItems.filter(item => app.itemStatus(item.namn) === NEED_TO_BUY);
  const handledItems = shoppingItems.filter(item => {
    const status = app.itemStatus(item.namn);
    return status === PURCHASED || status === ALREADY_HAVE;
  });
  // Butiksordning, inte alfabetisk: frukt & grönt först, frysen sist (§31).
  const groups = groupByCategory(activeItems, item => app.itemCategory(item.namn));
  // Tom lista av två helt olika skäl: ingen meny finns, eller användaren
  // har tagit bort varenda rad själv. Samma tomtillstånd för båda vore en
  // lögn om det första.
  const emptyState = state.removedItems.size
    ? `<div class="pantry-empty"><h2>Allt är borttaget ur listan</h2><p>Du har markerat varje vara som borttagen. Återställ dem nedan om du ångrar dig.</p></div>`
    : handledItems.length
      ? `<div class="pantry-empty"><h2>Allt är avbockat</h2><p>Ingenting kvar att handla den här veckan.</p></div>`
      : `<div class="pantry-empty"><h2>Listan väntar på din vecka</h2><p>Skapa en meny så samlar vi automatiskt allt du behöver handla.</p></div>`;
  const alreadyHome = handledItems.filter(item => app.itemStatus(item.namn) === ALREADY_HAVE).length;
  const handledSection = handledItems.length
    ? `<section class="shopping-handled"><h3>Klart${alreadyHome ? ` · ${app.plural(alreadyHome, "vara finns hemma", "varor finns hemma")}` : ""}<span>${handledItems.length}</span></h3>${handledItems.map(handledRowMarkup).join("")}</section>`
    : "";
  app.$("shoppingList").innerHTML = (activeItems.length
    ? groups.map(([category, items]) => `<section><h3>${category}<span>${items.length}</span></h3>${items.map(shoppingRowMarkup).join("")}</section>`).join("")
    : (shoppingItems.length ? "" : emptyState)) + handledSection;
  if (shoppingItems.length && !activeItems.length && !handledItems.length) app.$("shoppingList").innerHTML = emptyState;
  const removedCount = app.removedRowsForView().length;
  if (removedCount) {
    app.$("shoppingList").insertAdjacentHTML("beforeend",
      `<button type="button" class="restore-removed" id="restoreRemovedBtn">${app.plural(removedCount, "borttagen vara", "borttagna varor")} · Återställ alla</button>`);
    app.$("restoreRemovedBtn").addEventListener("click", app.restoreRemovedRows);
  }
  wireShoppingRowActions(app.$("shoppingList"));
  const completed = handledItems.length, itemsLeft = activeItems.length, progress = shoppingItems.length ? completed / shoppingItems.length * 100 : 0;
  // No mention of how many items happen to have a live-fetched price, and no
  // fetch timestamp - that's internal plumbing, not something a shopper needs
  // to see. Only the plain, calm facts: what's left, and what it costs.
  app.$("shoppingProgress").textContent = shoppingItems.length ? app.plural(itemsLeft, "vara kvar", "varor kvar") : "";
  // Hem's Handla-siffra: samma itemsLeft som Handla-vyn, aldrig en egen räkning.
  const homeCheapest = state.dbComparison?.cheapestChain && !state.dbComparison.locked ? state.dbComparison.cheapestChain : null;
  app.$("homeShoppingCount").textContent = shoppingItems.length ? app.plural(itemsLeft, "vara", "varor") : "–";
  app.$("homeShoppingStore").textContent = shoppingItems.length
    ? (homeCheapest ? `kvar · billigast hos ${homeCheapest}` : "kvar att plocka")
    : "Skapa en vecka först";
  // Var priserna kommer ifrån och hur färska de är - förtroende byggs av
  // att säga det, inte av att låta användaren gissa.
  // SAMMA prioritetskedja som raderna (databaseItemFor) - annars kan noten
  // hävda en annan kedja än den vars priser faktiskt visas.
  const sourceResult = state.dbChainTotals[app.chosenStore()]
    || state.dbChainTotals[app.selectedBranch()?.kedja]
    || Object.values(state.dbChainTotals)[0];
  // Dabas villkor: källan ska anges. Diskret, bara här och bara när
  // minst en rad faktiskt bygger på Dabas-verifierad förpackningsdata.
  const dabasNote = app.$("dabasNote");
  if (dabasNote) {
    const fromDabas = shoppingItems.some(item => app.databaseItemFor(item.namn)?.packageSource === "DABAS_VERIFIED");
    dabasNote.hidden = !fromDabas;
    dabasNote.textContent = fromDabas ? "Produktinformation från Dabas" : "";
  }
  // L0 · TECKENFÖRKLARINGEN. Prisets säkerhet bärs av form, och en form som
  // ingen har fått förklarad för sig är bara en tystare version av att inte
  // säga något. Nyckeln står därför kvar i foten oavsett vad listan innehåller
  // - också när varje pris är kontrollerat (§5.7). Markupen är statisk och
  // skrivs en gång, inte vid varje omritning.
  const prisnyckel = app.$("prisnyckel");
  if (prisnyckel && !prisnyckel.firstChild) prisnyckel.innerHTML = teckenförklaringMarkup();
  const sourceNote = app.$("priceSourceNote");
  if (sourceNote) {
    if (sourceResult?.updatedAt) {
      const updatedDate = new Date(sourceResult.updatedAt * 1000);
      const today = new Date().toDateString() === updatedDate.toDateString();
      const when = today ? `idag ${updatedDate.toTimeString().slice(0, 5)}` : updatedDate.toLocaleDateString("sv-SE");
      sourceNote.textContent = `Priser från ${sourceResult.chain} · uppdaterade ${when}`;
      sourceNote.hidden = false;
    } else {
      sourceNote.hidden = true;
    }
  }
  const nothingPlanned = !shoppingItems.length && !state.extraItems.length;
  app.$("shoppingCost").textContent = nothingPlanned
    ? `– / ${app.money(state.budget)}`
    : total == null && !shoppingItems.length && state.extraItems.length
      ? `${app.money(extrasCost)} / ${app.money(state.budget)}`
      // "hämtas…" bara medan det faktiskt hämtas. Är prissättningen klar och
      // ingen kedja kunde prissätta listan är det ärligare att säga det.
      : `${total == null
            ? (app.pricingPending() || (!state.dbPricedAt && !state.dbPricingFailedAt) ? "pris hämtas…" : "pris saknas just nu")
            : app.money(total)} / ${app.money(state.budget)}`; app.$("shoppingProgressBar").style.width = `${progress}%`;
  // "Allt handlat" celebrates a finished list, never an empty one - and
  // extras count: a week isn't done while the added coffee is unbought.
  const extrasDone = state.extraItems.every(extra => extra.checked);
  const alltHandlat = Boolean((shoppingItems.length || state.extraItems.length)
    && completed === shoppingItems.length && extrasDone);
  app.$("shoppingComplete").hidden = !alltHandlat;
  // H2 · sparkvittot. EN bedömning av "klar", inte två: kortet och kvittot
  // läser samma `alltHandlat`. Kallas vid varje omritning också när listan
  // inte är klar - kvittot måste se jämförelsen MEDAN den är giltig, eftersom
  // varje avbockning nollar state.dbComparison (clearPriceSnapshots).
  renderSparkvitto({ synligt: alltHandlat });
  const basketNote = app.$("basketHouseholdNote");
  if (basketNote) {
    basketNote.hidden = !app.householdActive();
    if (app.householdActive()) basketNote.textContent = `Delas med ${state.household.name}`;
  }
  // Bara en riktig total får bli historik eller jämförelsegrund.
  if (total != null) app.setLastRealWeekTotal(total);
  app.renderWeekCostAlert(total);
  app.renderStaplePrompt(shoppingItems);
  app.renderAssumedHome(shoppingItems);
  app.renderAttribution(shoppingItems);
  app.renderStoreComparison(selected); app.renderStoreCards(); renderExtraItems(activeChain); app.renderPantry();
  app.renderWeekStoreTabs();
  app.updateWeekStoreStatus();
  // Fed the exact same shoppingItems/total this function just computed - the
  // overview and the full page below it are two views onto one render pass,
  // never two separate computations that could drift. Dagordnat, med de tomma
  // dagarna kvar: det är veckoöversikten som numrerar dagarna.
  app.renderWeekOverview(weekDays, shoppingItems, total);
  app.syncLivePrices(shoppingItems);
  // Veckans behov ut till familjens delade lista. Debouncad och idempotent:
  // en oförändrad vecka skickar ingenting.
  app.pushWeekToHousehold();
}
