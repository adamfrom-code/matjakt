// ---------------------------------------------------------------------------
// IKVÄLL — STARTSIDANS FOTOKORT (design D, telefon 1)
//
// Klockan fem finns exakt en fråga: vad blir det till middag. G2 flyttade
// upp svaret på skärmen. Det här paketet gör svaret till ett FOTOKORT: ett
// helbleed foto som fyller bredden, rubriken liggande på bilden, priset som
// bildtext under och budgeten som en remsa — inte som en mätartavla.
//
// TVÅ SAKER ÄR REGLER, INTE SMAK:
//
// 1. TEXTEN PÅ FOTOT BÄRS AV SKÄRMEN, INTE AV EN SKUGGA (§5.2).
//    Fotot är inte vårt. Nästa recept kan ha en nästan vit bild — ett fat
//    med ris i motljus — och då är en text-shadow ingenting värd. Därför
//    ligger en gradient mellan fotot och texten, och den gradienten är
//    FULL `--scrim` (rgba(10,12,13,.78)) från textblockets överkant och
//    nedåt. Mot ett helvitt foto ger det vit text 10,23:1. Det är golvet,
//    räknat på det värsta foto vi kan råka få — inte på det foto vi råkar
//    ha valt.
//
//    Därför är textblockets höjd en variabel (`--hjalte-text`) som
//    BÅDE gradienten och textblockets maxhöjd läser. Ett ord för mycket i
//    en rubrik kan då inte skjuta upp texten ur den skyddade zonen; den
//    zonen är definierad av samma tal som ritar den.
//
// 2. INGEN EGEN PRISMARKUP.
//    Priset skrivs av prisMarkup() i ./pris.js, aldrig här. De tre
//    prisreglerna (kontrollerat / uppskattat / saknas) är produktens själ
//    och får finnas i exakt en implementation. Den här modulen översätter
//    bara receptets fält till motorns vokabulär (portionsprisRad) och låter
//    komponenten bestämma formen.
//
// Modulen är REN: den tar in data och lämnar en sträng. Fotot, pengarna och
// dagnamnen räknas ut av app.js och skickas in, precis som i recipes.js och
// shopping.js. Det är det som gör skärmen prövbar utan webbläsare.
// ---------------------------------------------------------------------------

import { escapeHtml } from "../utils/html.js";
import { prisMarkup, prisTillstånd } from "./pris.js";

/**
 * Receptets prisfält -> den rad prisTillstånd() läser.
 *
 * Ett recept bär `portionspris` och `priceStatus`; motorn talar om
 * `totalCost`, `priceTier` och `rowUncertain`. Översättningen står HÄR och
 * inte i pris.js, för det är vyn som vet vilket av receptets tal som är det
 * pris skärmen visar. pris.js ska inte behöva känna till receptmodellen.
 */
export function portionsprisRad(rätt) {
  if (!rätt) return null;
  return {
    priceStatus: rätt.priceStatus,
    priceTier: rätt.priceTier,
    totalCost: rätt.portionspris ?? null,
  };
}

/**
 * Hjälten: fotot, skärmen och texten som ligger på fotot.
 *
 * Hela fotot är knappen som öppnar receptet (§5.2) — långt över 44x44. Byt
 * ligger som SYSKON ovanpå, aldrig som knapp i knapp, och nere i den zon
 * där skärmen är full.
 */
export function hjälteMarkup(rätt, { ögonbryn = "", meta = "", foto = "" } = {}) {
  const id = escapeHtml(rätt.id);
  // Ögonbrynet skrivs med gemener i källan och versaliseras med
  // text-transform (§8). Versaler i HTML får skärmläsaren att stava dem
  // bokstav för bokstav: "I-K-V-Ä-L-L".
  return `<div class="ikvall-bild">`
    + `<button type="button" class="hero-meal-open" data-week-details="${id}">`
      + `<span class="hero-meal-photo">${foto}</span>`
      + `<span class="hero-meal-scrim" aria-hidden="true"></span>`
      + `<span class="hero-meal-info">`
        + `<small>${escapeHtml(ögonbryn)}</small>`
        + `<strong>${escapeHtml(rätt.namn || "")}</strong>`
        + (meta ? `<span class="hero-meal-meta">${escapeHtml(meta)}</span>` : "")
      + `</span>`
      + `<span class="sr-only">Öppna receptet</span>`
    + `</button>`
    + `<button type="button" class="hero-meal-swap" data-week-swap="${id}">`
      + `<span>Byt</span></button>`
    + `</div>`;
}

/**
 * Prisraden under fotot: portionspriset stort till vänster, vägen vidare
 * till höger. Bildtextsförhållandet (§5.3) — etiketten säger vad, siffran
 * säger hur mycket, ingen av dem skriker.
 *
 * `Se receptet` är skärmens ENDA accentmarkering vid sidan av mätarens
 * förbrukade del (§2.3: nuläget och vägen vidare, inget tredje).
 */
export function prisradMarkup(rätt) {
  const rad = portionsprisRad(rätt);
  const pris = prisMarkup(rätt.portionspris, prisTillstånd(rad), { klass: "ikvall-belopp" });
  return `<div class="ikvall-prisrad">`
    + `<span class="ikvall-portion">${pris}<span class="ikvall-kap">per portion</span></span>`
    + `<button type="button" class="ikvall-recept" data-week-details="${escapeHtml(rätt.id)}">`
      + `<span>Se receptet</span></button>`
    + `</div>`;
}

/** Hela kortet: foto, rubrik på bilden, prisrad under. */
export function ikvallMarkup(rätt, options = {}) {
  return `<div class="hero-meal-card">`
    + hjälteMarkup(rätt, options)
    + prisradMarkup(rätt)
    + `</div>`;
}

/**
 * Ingen vecka alls. Hjälteytan blir en inbjudan i stället för ett tomt hål —
 * men utan foto finns ingen skärm, alltså ingen vit text: inbjudan sätts på
 * papper med vanlig bläckfärg.
 */
export function ikvallTomMarkup() {
  return `<button type="button" class="hero-meal-card hero-meal-invite" data-hem-create>`
    + `<span class="ikvall-kap">Ikväll</span>`
    + `<strong>Vad blir det för middag i veckan?</strong>`
    + `<p>Tryck här så sätter Matjakt ihop veckans middagar — med riktiga priser `
    + `från butikerna nära dig.</p>`
    + `</button>`;
}

/**
 * Budgetremsan (§5.8). En remsa under maten, inte en mätartavla över den.
 *
 * `andel` är ETT värde med TVÅ användningar: mätarens fyllnad och markörens
 * läge. De kan därför inte glida isär. Markören — det 1px svarta strecket
 * som sticker ut över och under spåret — är formkodningen: en färgad remsa
 * går inte att läsa i gråskala, det gör strecket.
 *
 * Över budget blir remsan inte röd. Fyllnaden går till 100 %, och texten
 * byter ord: "84 kr över 800 kr". Överskridandet står i ord, inte i färg.
 */
export function budgetremsaText({ budget, använt, harVecka = true, money = String }) {
  if (!harVecka) {
    return { belopp: money(budget), efter: "veckobudget", andel: 0, not: "", etikett: "" };
  }
  if (använt == null) {
    // "Priset hämtas" är inte "veckan kostar 0 kr". Mätaren står stilla och
    // säger det i ord i stället för att rita en tom stapel som fakta.
    return { belopp: "–", efter: `kvar av ${money(budget)}`, andel: 0, not: "hämtas…", etikett: "" };
  }
  const kvar = budget - använt;
  const andel = budget > 0 ? Math.min(100, Math.max(0, Math.round((använt / budget) * 100))) : 0;
  const etikett = `${money(använt)} av ${money(budget)} använda`;
  return kvar < 0
    ? { belopp: money(-kvar), efter: `över ${money(budget)}`, andel: 100, not: "", etikett }
    : { belopp: money(kvar), efter: `kvar av ${money(budget)}`, andel, not: "", etikett };
}

/**
 * Fyndraden under remsan.
 *
 * C11 ger varje fynd `recipeIds` och `savesOnWeek` — kopplingen som gör ett
 * fynd till något man kan göra i stället för något man kan titta på. Finns
 * den, säger raden vad fyndet gör med VECKAN. Finns den inte (C11 är inte
 * byggd än), säger raden vad den faktiskt vet: varan, kedjan och priset.
 * Den gissar aldrig ihop en receptkoppling ur ett varunamn.
 *
 * Inga fynd alls: ingenting alls. En rubrik över en tom rad är sämre än
 * tystnad.
 */
export function fyndradMarkup(fynd, { receptNamn = () => "", money = String } = {}) {
  const lista = Array.isArray(fynd) ? fynd.filter(Boolean) : [];
  if (!lista.length) return "";

  const kopplade = lista.filter(f => Array.isArray(f.recipeIds) && f.recipeIds.length);
  const bäst = kopplade.length
    ? kopplade.slice().sort((a, b) => (b.savesOnWeek ?? 0) - (a.savesOnWeek ?? 0))[0]
    : lista.slice().sort((a, b) => kronorAv(b) - kronorAv(a))[0];
  if (!bäst) return "";

  const namn = kopplade.length ? (receptNamn(bäst.recipeIds[0]) || bäst.name) : bäst.name;
  const text = kopplade.length && bäst.savesOnWeek != null
    ? `Byt in ${namn} — ${money(bäst.savesOnWeek)} billigare den här veckan`
    : kopplade.length
      ? `${namn} är billigare den här veckan`
      : `${bäst.name} hos ${bäst.chain} — ${money(bäst.campaignPrice)} i stället för ${money(bäst.regularPrice)}`;

  return `<div class="ikvall-rubrikrad">`
      + `<span class="ikvall-kap">Veckans fynd</span><span class="ikvall-linje"></span>`
    + `</div>`
    + `<p class="ikvall-fyndtext">${escapeHtml(text)}</p>`
    + `<button type="button" class="ikvall-recept" data-ikvall-fynd>`
      + `<span>Se veckans fynd</span></button>`;
}

/** Kronor av på ett fynd — inte procent. 30 % på 12 kr är 3,60 kr. */
function kronorAv(fynd) {
  if (fynd?.savesOnWeek != null) return Number(fynd.savesOnWeek) || 0;
  const ordinarie = Number(fynd?.regularPrice);
  const kampanj = Number(fynd?.campaignPrice);
  return Number.isFinite(ordinarie) && Number.isFinite(kampanj) ? ordinarie - kampanj : 0;
}
