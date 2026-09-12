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

// ---------------------------------------------------------------------------
// L2 · VECKAN SOM I DESIGN D (telefon 2)
//
// G3 tog bort `hidden` och gjorde listan till standardvyn. Kvar ovanför den
// stod sju dagflikar och ETT dagskort i taget - alltså två påståenden om
// samma vecka på samma skärm, och en kalender där svaret på "vad äter vi i
// veckan" skulle stå. Det här paketet bygger raderna.
//
// Skärmen är sju rader och en summering. Inga flikar, inget dagskort, inget
// klick emellan: veckan LÄSES. Varje rad svarar på fyra frågor i den ordning
// ögat ställer dem - vilken dag, vilken rätt, hur lång tid, vad kostar den -
// och bär de två handlingar dagen faktiskt har: byt rätt, eller säg vad som
// blev av den.
//
// DAGEN SOM INTE HAR EN RÄTT ÄR OCKSÅ EN DAG. Den göms inte och hoppas inte
// över; den får en streckad ruta där fotot skulle stått, orden "Ingen middag
// planerad" i kursiv Newsreader och ett plustecken. En tom dag är en öppen
// plats i sättningen, inte ett fel - och att hoppa över den hade skjutit
// varje senare dag ett steg uppåt, så torsdagens rätt stått på onsdagen.
// ---------------------------------------------------------------------------

import { escapeHtml } from "../utils/html.js";
import { SAKNAS, UPPSKATTAT, prisMarkup, summaTillstånd } from "./pris.js";
import { receptbildMarkup } from "./receptbild.js";

/** Dagförkortningarna hör till veckan, och veckan bor här. */
export const DAYS = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
export const DAYS_LONG = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"];

// Det vyn behöver men inte äger. Skickas in en gång vid uppstart, samma
// mönster som src/views/shopping.js - så raderna går att rita i ett test
// utan webbläsare, prisdatabas eller app.js.
const app = {};
export function initWeekView(dependencies) { Object.assign(app, dependencies); }

/** Måndag = 0. Veckan börjar på måndag i Sverige, inte på söndag. */
export function todayIndex(now = new Date()) { return (now.getDay() + 6) % 7; }

/**
 * Ögonbrynet över rubriken: "7–13 september", eller "28 september–4 oktober"
 * när veckan går över ett månadsskifte. Månadsnamnet skrivs en gång när det
 * räcker - "7 september–13 september" är samma upplysning två gånger.
 *
 * Den finns för att svaret på "vilken vecka är det här?" annars bara stod i
 * dagförkortningarna, och "Mån" är sant varje vecka.
 */
export function veckoIntervall(now = new Date()) {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - todayIndex(now));
  const slut = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6);
  const månad = d => d.toLocaleDateString("sv-SE", { month: "long" });
  return månad(start) === månad(slut)
    ? `${start.getDate()}–${slut.getDate()} ${månad(slut)}`
    : `${start.getDate()} ${månad(start)}–${slut.getDate()} ${månad(slut)}`;
}

// ---------------------------------------------------------------------------
// PRISET PÅ EN DAGRAD ÄR ETT UPPSKATTAT PRIS - ALLTID
//
// Portionspriset är räknat ur kedjans priser för ett STANDARDHUSHÅLL: det är
// ett riktigt tal, men inte verifierat i den butik användaren går till och
// inte räknat på hennes portioner. Det är alltså precis L0:s andra tillstånd
// - "vi räknar, vi vet inte" - och samma slutsats som receptvyn drog om
// samma tal (src/views/recipes.js). Att låta raden byta till KONTROLLERAT när
// veckan råkar vara butiksprissatt vore att låna summans säkerhet till ett
// tal som inte är summan.
//
// Ett provider-recept (priceStatus "unavailable") har ingen prissatt
// ingredienslista alls. Då är talet inte lågt, det finns inte - och L0:s
// tomma fack är det enda sanna. "ca 52 kr" på ett tal vi inte har vore den
// sortens artighet som gör att ingen tror på nästa siffra heller.
// ---------------------------------------------------------------------------
export function dagPrisTillstånd(recipe) {
  if (!recipe) return SAKNAS;
  if (recipe.priceStatus === "unavailable" || recipe.priceStatus === "missing") return SAKNAS;
  return recipe.portionspris == null ? SAKNAS : UPPSKATTAT;
}

/** Tiden och portionerna, i den ordning raden läses. Inget påhittat. */
function dagMeta(recipe, { idag = false } = {}) {
  const bitar = [
    idag ? "Ikväll" : "",
    recipe.tid ? `${recipe.tid} min` : "",
    app.personer ? `${app.personer()} port` : "",
  ].filter(Boolean);
  return bitar.join(" · ");
}

/**
 * En dagrad.
 *
 * @param recipe  rätten, eller null för en dag utan middag
 * @param index   0-6, dagens plats i veckan
 * @param ctx     { idag }  index för dagens dag, eller -1
 */
export function veckoDagMarkup(recipe, index, { idag = -1 } = {}) {
  const dag = DAYS[index] || `D${index + 1}`;
  const dagLång = DAYS_LONG[index] || dag;
  const ärIdag = index === idag;

  // TOM DAG. Streckad ruta i stället för foto - en ram utan innehåll säger
  // "här finns plats", en grå fylld ruta säger "här skulle en bild ha
  // laddats". Plustecknet är dagens enda handling och bär dagens namn i sitt
  // aria-label: sju likadana plus i rad är sju likadana knappar för den som
  // lyssnar.
  if (!recipe) {
    return `<div class="vecka-dag vecka-dag--tom${ärIdag ? " vecka-dag--idag" : ""}">`
      + `<span class="vecka-dag-d">${escapeHtml(dag)}</span>`
      + `<span class="vecka-dag-mitt"><span class="vecka-dag-ruta" aria-hidden="true"></span>`
      + `<span class="vecka-dag-tomtext">Ingen middag planerad</span></span>`
      + `<button type="button" class="vecka-dag-lagg" data-week-add-meal data-week-day="${index}"`
      + ` aria-label="Lägg till middag på ${escapeHtml(dagLång)}">`
      + `<span aria-hidden="true">＋</span></button>`
      + `</div>`;
  }

  const fb = app.recipeFeedback ? app.recipeFeedback(recipe.id) : {};
  const pris = prisMarkup(
    recipe.portionspris == null ? null : app.money(recipe.portionspris),
    dagPrisTillstånd(recipe));
  const meta = dagMeta(recipe, { idag: ärIdag });
  // M2: bildytan ritas ALDRIG som en egen <img> här. Elva av receptbankens
  // rätter har inget foto vi får publicera, och tio av dem är middagar -
  // reservkortet i den här raden är alltså vardag, inte randfall.
  const bild = receptbildMarkup(recipe, { klass: "vecka-dag-foto" });
  // Raden är INTE en knapp med knappar i sig. Att öppna rätten, att byta den
  // och att säga vad som blev av den är tre syskon i en behållare.
  return `<div class="vecka-dag${ärIdag ? " vecka-dag--idag" : ""}">`
    + `<button type="button" class="vecka-dag-oppna" data-week-details="${escapeHtml(recipe.id)}">`
    + `<span class="vecka-dag-d">${escapeHtml(dag)}</span>`
    + `<span class="vecka-dag-mitt">${bild}`
    + `<span class="vecka-dag-text"><span class="vecka-dag-namn">${escapeHtml(recipe.namn)}</span>`
    + `${meta ? `<span class="vecka-dag-meta">${escapeHtml(meta)}</span>` : ""}</span></span>`
    + `<span class="vecka-dag-hoger">${pris}</span>`
    + `</button>`
    + `<button type="button" class="vecka-dag-byt" data-week-swap="${escapeHtml(recipe.id)}"`
    + ` aria-label="Byt middag på ${escapeHtml(dagLång)}"><span>Byt</span></button>`
    // G3: "✓ Lagad" och "✗ Hoppade över" finns bara här. De var oåtkomliga
    // bakom ett hidden-attribut en gång; de får inte bli oåtkomliga igen för
    // att raden blev vackrare.
    + `<details class="vecka-dag-meny">`
    + `<summary aria-label="Vad blev det av ${escapeHtml(dagLång)}s middag?">`
    + `<span aria-hidden="true">⋯</span></summary>`
    + `<div class="vecka-dag-meny-val">`
    + `<button type="button" class="${fb.cooked ? "marked" : ""}" data-cooked="${escapeHtml(recipe.id)}">✓ Lagad</button>`
    + `<button type="button" class="${fb.skipped ? "marked" : ""}" data-skipped="${escapeHtml(recipe.id)}">✗ Hoppade över</button>`
    + `</div></details>`
    + `</div>`;
}

/** Alla sju raderna. Sju, alltid - weekPlanDays() fyller ut, aldrig klipper. */
export function veckoDagarMarkup(selected, ctx = {}) {
  return weekPlanDays(selected).map((recipe, index) => veckoDagMarkup(recipe, index, ctx)).join("");
}

// ---------------------------------------------------------------------------
// SUMMERINGEN · KVITTOTS LOGIK, INTE KVITTOTS UTSEENDE
//
// Ett kvitto är trovärdigt för att delposterna står kvar under summan: man
// kan räkna efter. Det är logiken som ska ärvas, inte den perforerade
// remsan. Blocket säger därför vad veckan består av, drar en linje och
// skriver summan - och under summan står vad den GRUNDAR SIG PÅ.
//
// C7: så fort en rad saknar sitt pris är summan ett GOLV. "612 kr" är då ett
// påstående vi inte kan stå för; "minst 612 kr" är sant, och skillnaden är
// hela poängen med en budgetapp. Golvet räknas på de rader som faktiskt står
// i veckan - middagar utan pris och varor utan pris - med serverns egen
// flagga som ett OR, aldrig som enda källa: servern vet vad DEN prissatte,
// veckan kan bära rader den aldrig såg. Går de isär vinner golvet, för
// golvet kan bara vara för lågt.
// ---------------------------------------------------------------------------
export function veckoUnderlag({ selected = [], shoppingItems = [], total = null, headerDb = null } = {}) {
  const dagar = weekPlanDays(selected);
  const planerade = dagar.filter(Boolean);
  const tomma = dagar.length - planerade.length;
  // Summans säkerhet är kedjeresultatets, och mappningen ägs av L0. Talet som
  // faktiskt renderas skickas in - det är det talets säkerhet som beskrivs,
  // inte det tal headerDb råkar bära.
  const summaLäge = headerDb
    ? summaTillstånd({ ...headerDb, totalCheckoutCost: total }).tillstånd
    : UPPSKATTAT;
  const utanPris = planerade.filter(recipe => dagPrisTillstånd(recipe) === SAKNAS).length;
  const varorUtanPris = app.itemHasPrice
    ? shoppingItems.filter(item => !app.itemHasPrice(item)).length : 0;
  const hemma = app.itemAtHome ? shoppingItems.filter(item => app.itemAtHome(item)).length : 0;
  return {
    middagar: planerade.length,
    dagar: dagar.length,
    tomma,
    varor: shoppingItems.length,
    hemma,
    utanPris,
    varorUtanPris,
    total,
    tillstånd: total == null ? SAKNAS : summaLäge,
    golv: headerDb?.totalIsFloor === true || utanPris > 0 || varorUtanPris > 0,
  };
}

/**
 * Summeringsblocket under de sju raderna.
 *
 * Rubriken över talet säger VAD talet är - "Minst att handla för" eller
 * "Att handla för". Ett tal utan det beskedet är precis det C7 förbjuder.
 */
export function veckofotMarkup(underlag) {
  const { middagar, dagar, tomma, varor, hemma, utanPris, varorUtanPris,
    total, tillstånd, golv } = underlag;
  // Delposterna: de tal summan är gjord av, på en rad var för sig så att
  // blocket stannar under vikten. Talet först och ordet efter - en kolumn
  // siffror går att räkna i, en mening gör det inte.
  const poster = [
    [middagar, `av ${dagar} dagar`],
    tomma ? [tomma, tomma === 1 ? "tom dag" : "tomma dagar"] : null,
    varor ? [varor, varor === 1 ? "vara" : "varor"] : null,
    hemma ? [hemma, "finns hemma"] : null,
  ].filter(Boolean);
  // Vad summan GRUNDAR SIG PÅ. Två olika brister, aldrig hopslagna till ett
  // tal: en middag utan pris är något annat än en vara utan pris.
  const grund = [
    utanPris ? app.plural(utanPris, "middag saknar pris", "middagar saknar pris") : "",
    varorUtanPris ? app.plural(varorUtanPris, "vara saknar pris", "varor saknar pris") : "",
  ].filter(Boolean);
  const förklaring = total == null
    ? "Priset hämtas när veckan är prissatt hos en butik."
    : grund.length
      ? `${grund.join(" och ")} – kassan kan bli högre, aldrig lägre.`
      : `Räknat på ${app.plural(middagar, "prissatt middag", "prissatta middagar")}`
        + `${varor ? ` och ${app.plural(varor, "vara", "varor")}` : ""}.`;
  return `<p class="vecka-fot-poster">`
    + poster.map(([tal, namn]) =>
      `<span><b>${escapeHtml(String(tal))}</b> ${escapeHtml(namn)}</span>`).join("")
    + `</p>`
    + `<div class="vecka-fot-summa">`
    + `<span class="kap" id="weekTotalLabel">${golv && total != null ? "Minst att handla för" : "Att handla för"}</span>`
    + prisMarkup(total == null ? null : app.money(total), tillstånd, { golv, klass: "vecka-fot-tal" })
    + `</div>`
    + `<p class="vecka-fot-grund">${escapeHtml(förklaring)}</p>`;
}
