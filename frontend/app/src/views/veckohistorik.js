// ---------------------------------------------------------------------------
// H3 · VECKOHISTORIKEN
//
// `state.weekHistory` har sparat tolv veckor med plan och total sedan länge
// (app-state.js, setWeekPlan). Den lästes på fyra ställen och syntes på ett:
// knappen "Återställ förra veckan" i veckoarket, som bara säger ATT det finns
// en förra vecka. Vad ni faktiskt åt, och vad det kostade, låg i datan utan
// att någonsin ritas.
//
// Det här är alltså inget nytt fält och ingen ny insamling - det är innehåll
// som redan är betalt. Den bor på Sparat, under nyckeltalen: skärmen heter
// redan "Din historik", och den som gått dit har gått dit för att se bakåt.
//
// TRE REGLER MODULEN HÅLLER
//
// 1. TALET GÅR GENOM L0. En veckas total ÄR ett pris, till skillnad från
//    Sparats besparingar, så den ritas av prisMarkup() i src/views/pris.js
//    och aldrig här. Tillståndet är UPPSKATTAT: talet räknades på veckans
//    planerade rätter hos en kedja, det är inte ett kvitto - och en vecka som
//    aldrig hann prissättas har inget tal alls, inte ett lågt.
//
// 2. EN VECKA UTAN TOTAL FÅR SIN RAD ÄNDÅ. `total: null` skrivs med flit av
//    app-state.js när veckan aldrig prissattes. Att hoppa över raden hade
//    gjort historiken glesare än verkligheten och fått snittet att se ut att
//    gälla fler veckor än det gör.
//
// 3. MODULEN KÄNNER DOM:EN BARA GENOM initVeckohistorik(). Allt ovanför
//    renderVeckohistorik() är rena funktioner, och det är de som prövas i
//    tests/veckohistorik.test.js.
// ---------------------------------------------------------------------------

import { escapeHtml } from "../utils/html.js";
import { SAKNAS, UPPSKATTAT, prisMarkup } from "./pris.js";

let app = {
  $: null,
  /** Rättens namn ur receptbanken, eller null när rätten inte finns kvar. */
  namnFör: () => null,
};

export function initVeckohistorik(dependencies = {}) {
  app = { ...app, ...dependencies };
}

/** Hur många veckor bakåt som ritas. app-state.js kapar listan till tolv. */
export const VECKOR_I_HISTORIKEN = 12;

const MÅNAD_KORT = ["jan", "feb", "mar", "apr", "maj", "jun",
                    "jul", "aug", "sep", "okt", "nov", "dec"];

// Årstiden är inte kosmetik: "Så här har ni ätit i höst" är en mening om NU,
// och i februari är "i höst" fel om den står kvar från september.
const SÄSONGER = ["vintern", "vintern", "våren", "våren", "våren", "sommaren",
                  "sommaren", "sommaren", "hösten", "hösten", "hösten", "vintern"];

export function säsongen(datum = new Date()) {
  return SÄSONGER[datum.getMonth()] || "år";
}

/** "8 sep" - samma korta form som månadsremsan ovanför använder. */
export function datumEtikett(tid) {
  const datum = new Date(tid);
  if (!Number.isFinite(datum.getTime())) return "";
  return `${datum.getDate()} ${MÅNAD_KORT[datum.getMonth()]}`;
}

/**
 * Historiken som vyn behöver den.
 *
 * `historik` är state.weekHistory: [{ plan, savedAt, total }], nyast först.
 * Poster utan plan är redan bortsanerade av app-state.js, men en tom lista
 * och en saknad lista ska ge samma modell - annars blir det tomma
 * tillståndet två olika saker beroende på var användaren kom ifrån.
 */
export function veckohistorikModell(historik, { now = new Date() } = {}) {
  const poster = Array.isArray(historik) ? historik : [];
  const veckor = poster.slice(0, VECKOR_I_HISTORIKEN).map(post => {
    const plan = Array.isArray(post?.plan) ? post.plan : [];
    // En rätt som tagits bort ur banken sedan dess har inget namn kvar. Den
    // räknas ändå som en middag - den åts.
    const rätter = plan.map(id => app.namnFör(id)).filter(Boolean);
    const kronor = Number.isFinite(post?.total) ? post.total : null;
    return {
      datum: datumEtikett(post?.savedAt),
      dagar: plan.length,
      rätter,
      kronor,
      tillstånd: kronor == null ? SAKNAS : UPPSKATTAT,
    };
  });
  return {
    rubrik: `Så här har ni ätit i ${säsongen(now)}`,
    veckor,
    tom: veckor.length === 0,
  };
}

/** Snittet över de veckor som FAKTISKT har ett tal. Null när ingen har det. */
export function snittPerVecka(modell) {
  const tal = modell.veckor.map(v => v.kronor).filter(v => v != null);
  if (!tal.length) return null;
  return Math.round(tal.reduce((summa, v) => summa + v, 0) / tal.length);
}

export function veckoradMarkup(vecka) {
  // Middagarna i klartext är hela innehållet - "4 middagar" säger hur många,
  // inte vilka, och det är vilka man går till historiken för att se.
  const rätter = vecka.rätter.length
    ? escapeHtml(vecka.rätter.join(" · "))
    : `<span class="vh-utan-ratter">Rätterna finns inte kvar i banken</span>`;
  const antal = `${vecka.dagar} ${vecka.dagar === 1 ? "middag" : "middagar"}`;
  return `<li class="vh-vecka">`
    + `<span class="vh-datum">${escapeHtml(vecka.datum)}</span>`
    + `<span class="vh-text"><span class="vh-ratter">${rätter}</span>`
    + `<small class="vh-antal">${escapeHtml(antal)}</small></span>`
    + `<span class="vh-pris">${prisMarkup(vecka.kronor, vecka.tillstånd)}</span>`
    + `</li>`;
}

export function veckohistorikMarkup(modell) {
  // §5.10: ett tomt tillstånd är en mening i kursiv Newsreader. Ingen knapp
  // här - veckan sparas av sig själv när nästa planeras, och det finns inget
  // att trycka på för att få fram en historik som ännu inte hänt.
  if (modell.tom) {
    return `<h2 class="vh-rubrik">${escapeHtml(modell.rubrik)}</h2>`
      + `<div class="vh-tomt"><p>Ingen vecka bakåt än — vi sparar veckan åt er när ni planerar nästa.</p></div>`;
  }
  const snitt = snittPerVecka(modell);
  // Snittet står under listan och inte över: det är en sammanfattning av det
  // man just läst, inte en rubrik över något man inte sett än.
  const fot = snitt == null ? ""
    : `<p class="vh-snitt">I snitt ${prisMarkup(snitt, UPPSKATTAT)} per vecka.</p>`;
  return `<h2 class="vh-rubrik">${escapeHtml(modell.rubrik)}</h2>`
    + `<ul class="vh-lista">${modell.veckor.map(veckoradMarkup).join("")}</ul>`
    + fot;
}

export function renderVeckohistorik(modell) {
  const $ = app.$;
  if (!$) return modell;
  const box = $("veckohistorik");
  if (box) box.innerHTML = veckohistorikMarkup(modell);
  return modell;
}
