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
import { groupByCategory } from "../services/categories.js";
import { extraLineTotal, extraUnitPrice, removeExtra, setQty } from "../services/extras.js";
import { ALREADY_HAVE, NEED_TO_BUY, PURCHASED, REMOVED, foldName, shoppingRows } from "../services/household-state.js";
import { saveState, selectedRecipes, state } from "../state/app-state.js";
import { escapeHtml, safeHttpUrl } from "../utils/html.js";
import {
  KONTROLLERAT, SAKNAS, UPPSKATTAT,
  prisMarkup, prisTillstånd, summaTillstånd, teckenförklaringMarkup,
} from "./pris.js";

// Allt vyn behöver men inte äger. Skickas in en gång vid uppstart; namnen
// är exakt de app.js använder, så varje flyttad rad står oförändrad nedan.
const app = {};
export function initShoppingView(dependencies) {
  Object.assign(app, dependencies);
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
// HANDLA: EN RAD  (L3 — design D, telefon 3)
//
// Frågorna en rad ska besvara på ett ögonkast, i den ordningen (§30):
//   Vad är varan?  Hur mycket behöver vi?  Har vi den?  Vad kostar den?
//
// Raden ÄR kryssrutan. Den gamla raden hade ett foto på 56 px, ett märke, en
// butiksnot, ett jämförpris och därunder en egen knapprad med "Har hemma" och
// "Köpt" - sju upplysningar och tre träffytor på en rad vars uppgift i butik
// är att säga vad man ska lägga i korgen och vad det kostar. Design D ger
// raden fyra saker: kryssrutan, namnet, mängden som underrad och priset till
// höger. Allt annat står kvar i appen, men inte i tumhöjd mitt i listan.
//
// TRE TRÄFFYTOR BLEV EN. Radens knapp är avbockningen: obockad bär den
// data-bought, avbockad data-need, alltså exakt de två lyssnare
// wireShoppingRowActions redan binder. Kryssrutans egen storlek är 21 px men
// träffytan är hela radens 44 (DESIGNSYSTEM-D.md §5.5).
//
// "Har hemma" och "ta bort" är radens sekundära handlingar och ligger i
// .vara-sido, utanför radens högerkant på pekskärm (G5) och framme vid fokus,
// hover och svep. En sekundär handling ska vara nåbar, inte i vägen.
//
// Produktnamn skrivs BARA ut när det kommer från en riktig matchning i
// prisdatabasen. En osäker matchning blir inte säker av att den får ett
// produktnamn (§35).
// ---------------------------------------------------------------------------

const AT_HOME_ICON = '<svg viewBox="0 0 24 24"><path d="m4 11 8-6 8 6v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1Z"/></svg>';
const BOCK = '<svg viewBox="0 0 11 9" width="11" height="9" fill="none" aria-hidden="true">'
  + '<path d="M1 4.6 4 7.6 10 1.2" stroke-width="1.8"/></svg>';

// Radens sekundära handlingar. "Har hemma" är bara sant att erbjuda på en
// vara man ännu inte bockat av; krysset gäller alltid.
function rowSideMarkup(name, status) {
  const atHome = status === NEED_TO_BUY
    ? `<button type="button" class="shopping-action vara-hemma" data-at-home="${escapeHtml(name)}"`
      + ` aria-label="${escapeHtml(name)} finns hemma">${AT_HOME_ICON}<span>Har hemma</span></button>`
    : "";
  return `<div class="vara-sido">${atHome}`
    + `<button type="button" class="shopping-remove" data-remove-item="${escapeHtml(name)}"`
    + ` aria-label="Ta bort ${escapeHtml(name)} ur listan">×</button></div>`;
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

// Det raden behöver veta om sitt eget pris, hämtat en gång. Samma räkning som
// totalsumman (packagesFor), inte en egen kopia: kopian räknade veckans behov
// i det VISADE måttet (6 dl) mot förpackningens basmått (200 ml) och kom fram
// till ett paket i stället för tre - raden sa "Behöver 6 dl" och visade priset
// för en burk. null = antal osäkert (vikt/volym utan paketinfo), 0 = allt
// finns redan hemma.
export function prisUnderlag(item) {
  const match = app.databaseItemFor(item.namn);
  const live = state.livePriser[item.namn];
  const packages = match ? match.packages : packagesFor(item, app.pantryForPricing());
  const dbSyncPending = app.pricingPending() || (!state.dbPricedAt && !state.dbPricingFailedAt);
  const hämtas = !match && !live
    && (dbSyncPending || (app.livePricesLoading() && app.validChains.includes(app.chosenStore())));
  return { match, live, packages, hämtas };
}

// ---------------------------------------------------------------------------
// L3 · PRISET RENDERAS AV L0, ALDRIG AV DEN HÄR FILEN
//
// Handla skrev förut ut tre olika prislappar med tre olika markupar:
// `<strong>${money(x)}</strong>`, `<strong class="price-missing">Pris
// saknas</strong>` och `<small class="item-status estimated">Antal
// osäkert</small>`. Tre former, uppfunna på plats, som ingen annan vy delade
// - och som därför kunde glida isär från resten av appen utan att någon såg
// det. Nu översätter den här funktionen bara motorns rad till ETT av L0:s tre
// tillstånd, och prisMarkup() bestämmer hur det ser ut (§6).
//
// Ett gissat paketantal blir SAKNAS, inte ett tal: radtotalen är ärligt okänd
// när antalet är en gissning (C8), och en tom ram är sann där "22 kr" inte är
// det. Hur många sådana rader veckan har räknas i stället i foten, en gång
// (C7) - raden ska inte behöva bära en varning som hör till summan.
// ---------------------------------------------------------------------------
export function radPrisTillstånd({ match, live, packages }) {
  if (match) return { värde: match.totalCost, tillstånd: prisTillstånd(match) };
  // Ett livepris är hämtat hos kedjan men inte prissatt av motorn; utan
  // paketantal finns ingen radtotal att stå för.
  if (live) {
    return live.pris_kr == null || packages == null
      ? { värde: null, tillstånd: SAKNAS }
      : { värde: live.pris_kr * packages, tillstånd: KONTROLLERAT };
  }
  return { värde: null, tillstånd: SAKNAS };
}

// C7:s golv, räknat på de rader som FAKTISKT står i listan. "Antal osäkert"
// betyder att varan har ett pris men inget säkert antal - den gör kassan
// högre än summan, aldrig lägre.
export function saknarSäkertAntal(item) {
  const { match, live, packages } = prisUnderlag(item);
  if (match) return match.exactPackaging === false || match.rowUncertain === true
    || match.priceStatus === "estimated";
  return !!live && packages == null;
}

export function shoppingRowMarkup(item) {
  const status = app.itemStatus(item.namn);
  const underlag = prisUnderlag(item);
  const { match, live } = underlag;
  const klar = status !== NEED_TO_BUY;
  const title = match ? match.productName : (live ? live.produktnamn : item.namn);
  const quantity = quantityTextFor(item, match, status);
  const onCampaign = match && match.campaignPrice != null && match.regularPrice != null
    && match.campaignPrice < match.regularPrice;
  const campaign = onCampaign
    ? `Kampanj ${app.money(match.campaignPrice)} (ord. ${app.money(match.regularPrice)})`
    : (live?.kampanj?.text || "");
  // Mängden som underrad: vad veckan behöver och hur många förpackningar det
  // blir i korgen. Kampanjen hör till samma rad - den ändrar priset, inte varan.
  const undertext = escapeHtml([quantity, campaign].filter(Boolean).join(" · "));
  // "pris hämtas…" är inget pristillstånd - det är frånvaron av ett svar, och
  // får därför inte låna någon av de tre formerna. En tom ram medan hämtningen
  // pågår vore ett påstående vi inte har täckning för.
  const { värde, tillstånd } = radPrisTillstånd(underlag);
  const pris = underlag.hämtas
    ? `<span class="pris-hamtas">pris hämtas…</span>`
    : prisMarkup(värde, tillstånd);
  // RADEN ÄR KNAPPEN (§5.5). Obockad bär den data-bought, avbockad data-need -
  // samma två lyssnare wireShoppingRowActions redan binder, så avbockningen
  // behöver ingen egen knapp intill priset.
  const toggle = klar
    ? `data-need="${escapeHtml(item.namn)}"`
    : `data-bought="${escapeHtml(item.namn)}"`;
  return `<article class="shopping-item vara-rad status-${status.toLowerCase()}${klar ? " vara--klar" : ""}">`
    + `<button type="button" class="vara" ${toggle} aria-pressed="${klar}" aria-keyshortcuts="Delete">`
    + `<span class="ruta" aria-hidden="true">${BOCK}</span>`
    + `<span class="txt"><strong>${escapeHtml(title)}</strong>`
    + `<small class="mangd">${undertext}</small></span>`
    + pris
    + `</button>`
    + rowSideMarkup(item.namn, status)
    + `</article>`;
}

// ---------------------------------------------------------------------------
// L3 · AVDELNINGEN
//
// Listan är butikens ordning, inte appens: frukt och grönt först, frysen
// sist. Avdelningen märks med en hårlinje längs gruppens vänsterkant och en
// rubrik i spärrade kapitäler - inget kort, ingen ram, ingen skugga. Det är
// hela skillnaden mellan ett uppslag och en samling paneler: innehållet
// skiljs åt av linjer och luft.
//
// Rubriken skrivs som vanlig text och versaliseras i CSS. Versaler i källan
// får en skärmläsare att stava ordet bokstav för bokstav (§8).
// ---------------------------------------------------------------------------
export function avdelningMarkup(category, items) {
  return `<section class="avdelningsgrupp">`
    + `<h3 class="avdelning"><span class="kap kap-ink">${escapeHtml(category)}</span>`
    + `<span class="kap">${app.plural(items.length, "vara", "varor")}</span></h3>`
    + items.map(shoppingRowMarkup).join("")
    + `</section>`;
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
  // L3/L0: extravaran är en rad i Handla som alla andra och får ingen egen
  // prisform. Ett matchat pris är hämtat hos kedjan (kontrollerat); utan
  // matchning finns inget pris, och då är det L0:s tomma fack - inte ett
  // tankstreck i en klass som bara den här funktionen känner till.
  const priceLapp = line != null ? prisMarkup(app.money(line), KONTROLLERAT) : prisMarkup(null, SAKNAS);
  const unitNote = extra.qty > 1 && unit != null ? `<small>${extra.qty} × ${app.money(unit)}</small>` : "";
  return `<div class="shopping-item extra-item ${extra.checked ? "checked" : ""}">
    <input type="checkbox" data-extra-check="${extra.id}" ${extra.checked ? "checked" : ""}>
    ${photo}
    <span class="shopping-item-info"><strong>${escapeHtml(displayName)}</strong>
      <small class="shopping-item-meta">${escapeHtml(metaBits.join(" · "))}</small></span>
    <span class="extra-qty"><button type="button" data-extra-minus="${extra.id}">−</button><b>${extra.qty}</b><button type="button" data-extra-plus="${extra.id}">+</button></span>
    <span class="shopping-item-price">${priceLapp}${unitNote}</span>
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

// ---------------------------------------------------------------------------
// L3 + C7 · FOTEN: "MINST ATT BETALA", OCH VAD SOM SAKNAS
//
// C7:s golv, uttryckt i foten på Handla. En summa som utelämnar de osäkra
// radernas kostnad får aldrig visas som ett exakt tal: tre msk-rader (honung,
// olivolja, tomatpuré) bidrog med noll kronor, användaren budgeterade 640 och
// betalade 700. Rubriken heter därför "Minst att betala" så fort någon rad
// saknar en radtotal, och raden under räknar dem: "3 varor utan säkert antal".
//
// GOLVET RÄKNAS PÅ DE RADER SOM STÅR I LISTAN, inte bara på serverns flagga.
// Servern vet vad DEN prissatte; listan kan därutöver bära hushållsrader och
// extravaror den aldrig såg. Läser foten bara serverns totalIsFloor kan den
// säga "att betala" ovanför en lista med en tom prisram i - och det är exakt
// det fel C7 fanns för att stänga. Flaggan är med som ett OR, aldrig som enda
// källa: går de isär vinner golvet, för golvet kan bara vara för lågt.
//
// Talet självt renderas av L0:s prisMarkup. Foten skriver ingen egen
// prismarkup - "minst" är en modifierare på komponenten, inte en fjärde form.
// ---------------------------------------------------------------------------

export function kassaUnderlag({ shoppingItems, total, headerDb, activeChain }) {
  let osäkertAntal = 0;
  let utanPris = 0;
  let hämtas = 0;
  for (const item of shoppingItems) {
    const underlag = prisUnderlag(item);
    if (underlag.hämtas) { hämtas += 1; continue; }
    if (saknarSäkertAntal(item)) { osäkertAntal += 1; continue; }
    if (radPrisTillstånd(underlag).tillstånd === SAKNAS) utanPris += 1;
  }
  // En extravara utan prismatch bidrar med noll kronor till extrasCost - och
  // gör därmed summan till ett golv på precis samma sätt som en osäker rad.
  const extraUtanPris = state.extraItems.filter(extra =>
    extraLineTotal(extra, activeChain, (state.extraMatches[activeChain] || {})[extra.id]) == null).length;
  const golv = headerDb?.totalIsFloor === true
    || osäkertAntal > 0 || utanPris > 0 || extraUtanPris > 0;
  // En summa som inte är butiksverifierad hela vägen är uppskattad, aldrig
  // kontrollerad. Utan ett databasresultat är talet en beräkning på
  // förpackningspriser - alltså uppskattat per definition.
  // Talet som renderas är headerDb.totalCheckoutCost PLUS extravarorna, och
  // det är det talet vars säkerhet ska beskrivas. summaTillstånd() äger
  // mappningen (pricingBasis -> tillstånd); vyn skickar bara in summan den
  // faktiskt skriver ut, i stället för att lita på att headerDb bär den.
  const tillstånd = total == null ? SAKNAS
    : headerDb ? summaTillstånd({ ...headerDb, totalCheckoutCost: total }).tillstånd : UPPSKATTAT;
  return { osäkertAntal, utanPris, hämtas, golv, tillstånd };
}

export function renderKassa({ shoppingItems, total, extrasCost, headerDb, activeChain }) {
  const kostnad = app.$("shoppingCost");
  if (!kostnad) return;
  const { osäkertAntal, utanPris, golv, tillstånd } = kassaUnderlag({ shoppingItems, total, headerDb, activeChain });
  const nothingPlanned = !shoppingItems.length && !state.extraItems.length;
  const väntar = app.pricingPending() || (!state.dbPricedAt && !state.dbPricingFailedAt);
  const budget = `<span class="kassa-budget">/ ${escapeHtml(app.money(state.budget))}</span>`;
  // Bara extravaror: deras summa är hela kassan, och den är exakt så långt
  // varje extrarad har ett pris.
  const enbartExtra = total == null && !shoppingItems.length && state.extraItems.length;
  // En tom lista har inget pris att sakna. "pris saknas" vore en lögn om en
  // vara som inte finns, så tomrummet får ett tankstreck som INTE är en av
  // L0:s tre former - annars vore frånvaron av en lista ett pristillstånd.
  const lapp = nothingPlanned
    ? `<span class="kassa-tomt">–</span>`
    : enbartExtra
      ? prisMarkup(app.money(extrasCost), KONTROLLERAT, { golv })
      // "hämtas…" bara medan det faktiskt hämtas. Är prissättningen klar och
      // ingen kedja kunde prissätta listan är talet inte på väg - det saknas,
      // och då är det L0:s tomma ram som gäller, inte en evig spinner.
      : total == null
        ? (väntar ? `<span class="pris-hamtas">pris hämtas…</span>` : prisMarkup(null, SAKNAS))
        : prisMarkup(app.money(total), tillstånd, { golv });
  kostnad.innerHTML = `${lapp} ${budget}`;
  // Rubriken säger vad talet ÄR. "Minst att betala" är inte en varning utan en
  // beskrivning: kassan kan bli högre, aldrig lägre.
  const label = app.$("shoppingTotalLabel");
  if (label) label.textContent = golv && total != null ? "Minst att betala" : "Summa i kassan";
  // Och vad som fattas, i klartext. Två olika brister, aldrig hopslagna till
  // ett tal: en vara med känt pris men gissat antal är något annat än en vara
  // vi inte har något pris på alls.
  const not = app.$("shoppingUncertain");
  if (not) {
    const delar = [
      osäkertAntal ? app.plural(osäkertAntal, "vara utan säkert antal", "varor utan säkert antal") : "",
      utanPris ? app.plural(utanPris, "vara utan pris", "varor utan pris") : "",
    ].filter(Boolean);
    not.textContent = delar.join(" · ");
    not.hidden = !delar.length;
  }
  // L0 · TECKENFÖRKLARINGEN, i foten på Handla (§5.7). Prisets säkerhet bärs
  // av form, och en form ingen fått förklarad för sig är bara en tystare
  // version av att inte säga något. Nyckeln står därför kvar oavsett vad
  // listan innehåller - också när varje pris är kontrollerat. Markupen är
  // statisk och skrivs en gång, inte vid varje omritning.
  const prisnyckel = app.$("prisnyckel");
  if (prisnyckel && !prisnyckel.firstChild) prisnyckel.innerHTML = teckenförklaringMarkup();
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
  // L3 · AVBOCKAD RAD STÅR KVAR DÄR DEN HÖR HEMMA.
  //
  // Köpta och hemmavarande varor lyftes förut ur listan och samlades i ett
  // eget "Klart"-block under den. Det löste rätt problem - ett felklick fick
  // inte radera varan ur synfältet - men det löste det genom att flytta den,
  // och i butik betyder det att raden man just bockade av hoppar bort från
  // hyllan man står vid. Design D bockar av på plats: raden blir genomstruken
  // och tonad och ligger kvar i sin avdelning, så listan man läser är samma
  // lista hela vägen genom affären. Ett felklick syns direkt, på raden själv.
  const activeItems = shoppingItems.filter(item => app.itemStatus(item.namn) === NEED_TO_BUY);
  const handledItems = shoppingItems.filter(item => {
    const status = app.itemStatus(item.namn);
    return status === PURCHASED || status === ALREADY_HAVE;
  });
  // Butiksordning, inte alfabetisk: frukt & grönt först, frysen sist (§31).
  const groups = groupByCategory(shoppingItems, item => app.itemCategory(item.namn));
  // Tom lista av två helt olika skäl: ingen meny finns, eller användaren
  // har tagit bort varenda rad själv. Samma tomtillstånd för båda vore en
  // lögn om det första.
  const emptyState = state.removedItems.size
    ? `<div class="pantry-empty"><h2>Allt är borttaget ur listan</h2><p>Du har markerat varje vara som borttagen. Återställ dem nedan om du ångrar dig.</p></div>`
    : `<div class="pantry-empty"><h2>Listan väntar på din vecka</h2><p>Skapa en meny så samlar vi automatiskt allt du behöver handla.</p></div>`;
  app.$("shoppingList").innerHTML = shoppingItems.length
    ? groups.map(([category, items]) => avdelningMarkup(category, items)).join("")
    : emptyState;
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
  renderKassa({ shoppingItems, total, extrasCost, headerDb, activeChain });
  app.$("shoppingProgressBar").style.width = `${progress}%`;
  // "Allt handlat" celebrates a finished list, never an empty one - and
  // extras count: a week isn't done while the added coffee is unbought.
  const extrasDone = state.extraItems.every(extra => extra.checked);
  app.$("shoppingComplete").hidden = !((shoppingItems.length || state.extraItems.length)
    && completed === shoppingItems.length && extrasDone);
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
