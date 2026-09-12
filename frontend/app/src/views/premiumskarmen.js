// ---------------------------------------------------------------------------
// PREMIUMSKÄRMEN — BELOPPEN OCH VALET
//
// Facit: docs/matjakt-design-D.html, telefon 8. Skärmen är ingen hänglåsvägg
// utan ett uppslag: kapitäl, en rubrik i Newsreader, en ingress, JÄMFÖRELSEN,
// och under den priset och ett val. Den här modulen äger det sista stycket —
// beloppen och valet mellan månad och år.
//
// JÄMFÖRELSETABELLEN BOR INTE HÄR. Den är J2:s (src/views/premiumtabellen.js)
// och härleds ur backend/services/accounts/features.py med ett test som läser
// Python-källan. Två tabeller med olika innehåll vore exakt det fel J2 finns
// för att laga, så L7 bygger ingen. J2 gör listan sann; det här gör skärmen.
//
// INGEN EGEN PRISMARKUP (L0). Varje belopp går genom prisMarkup() i
// src/views/pris.js. Skälet är inte konsekvens för dess egen skull: en vy som
// formaterar sitt eget belopp kan avrunda, tusentalsavgränsa eller falla
// tillbaka annorlunda än resten av appen, och priset är det enda tal en
// användare jämför mot sin egen plånbok. Saknas svaret från /api/entitlements
// ännu renderar komponenten "pris saknas" — ett tomt fack är sant, ett
// påhittat tal är det inte.
//
// 59 OCH 399 STÅR INTE I DEN HÄR FILEN. De bor i backend (features.PRICING)
// och når klienten via /api/entitlements. app.js premiumPricing() har ett
// reservvärde för de första hundra millisekunderna; modulen tar emot talen och
// har ingen egen åsikt om dem.
//
// VALET MÄRKS MED VIKT OCH EN LINJE, ALDRIG MED ACCENTEN. DESIGNSYSTEM-D.md
// §2.3 räknar upp accentens förbjudna betydelser, och "Premium" står med:
// systemets enda färg betyder "här är du, här går vägen vidare", ingenting
// annat. Att välja månad eller år är dessutom inte vägen vidare — det är ett
// val mellan två jämbördiga rader, och vägen vidare är knappen under dem.
//
// OCH VALET SKA HÖRAS. Behållaren bar role="tablist" med två barn som varken
// hade role="tab" eller någon tabpanel att styra: en skärmläsare fick veta att
// den stod i en flikrad och hittade sedan inga flikar. Två växlande knappar i
// en grupp med aria-pressed är vad de faktiskt är.
// ---------------------------------------------------------------------------

import { escapeHtml } from "../utils/html.js";
import { prisMarkup } from "./pris.js";

/** Månadspriset multiplicerat med tolv minus årspriset — det man sparar. */
export function årsrabatt(pricing = {}) {
  const perMånad = pricing.monthly?.pricePerMonth;
  const perÅr = pricing.yearly?.pricePerYear;
  if (!Number.isFinite(perMånad) || !Number.isFinite(perÅr)) return null;
  const rabatt = perMånad * 12 - perÅr;
  return rabatt > 0 ? rabatt : null;
}

/**
 * Innehållet i en av de två planknapparna.
 *
 * Ordningen i DOM:en är namn, belopp, villkor — det är den ordning en
 * skärmläsare läser upp dem i, och den enda som ger en begriplig mening
 * ("År, 399 kr, per år, spara 309 kr"). Att beloppet står ÖVERST på skärmen
 * är CSS:ens sak (`order`), inte markupens.
 */
export function planMarkup(pricing = {}) {
  const perMånad = pricing.monthly?.pricePerMonth;
  const perÅr = pricing.yearly?.pricePerYear;
  const rabatt = årsrabatt(pricing);
  const villkorÅr = ["per år", rabatt ? `spara ${rabatt} kr` : ""].filter(Boolean).join(" · ");
  const rad = (namn, belopp, villkor) =>
    `<span class="prem-plan-namn">${escapeHtml(namn)}</span>`
    + prisMarkup(belopp, undefined, { klass: "prem-plan-tal" })
    + `<span class="prem-plan-villkor">${escapeHtml(villkor)}</span>`;
  return {
    month: rad("Månad", perMånad, "per månad"),
    year: rad("År", perÅr, villkorÅr),
  };
}

/**
 * Fyller de två knapparna och håller aria-pressed i takt med .active.
 *
 * Knapparna BYTS INTE UT, bara deras innehåll: klicklyssnaren sitter på dem
 * sedan uppstart (app.js), och en omritning som ersatte elementen hade tyst
 * kopplat loss valet mitt i ett betalflöde.
 */
export function ritaPlanval(pricing = {}, rot = document) {
  const delar = planMarkup(pricing);
  for (const [nyckel, markup] of Object.entries(delar)) {
    const knapp = rot.querySelector(`[data-price-tab="${nyckel}"]`);
    if (knapp) knapp.innerHTML = markup;
  }
  synkaValet(rot);
}

/** aria-pressed följer den klass som redan bär markeringen visuellt. */
export function synkaValet(rot = document) {
  const knappar = rot.querySelectorAll("[data-price-tab]");
  knappar.forEach(knapp =>
    knapp.setAttribute("aria-pressed", String(knapp.classList.contains("active"))));
}

/**
 * Betalväggens två knappar.
 *
 * Samma belopp, samma komponent och samma ord som i kontoarket. Betalväggen
 * hade egna strängar med `priceText` som reservvärde ("399 kr/år", "≈ 33
 * kr/mån", "Spara 309 kr jämfört med månadsbetalning") — fyra formuleringar av
 * samma fyra tal, skrivna på ett annat ställe än kontoarkets. Två skärmar som
 * formaterar samma pris var för sig är två skärmar som kan börja säga olika
 * saker om det.
 *
 * Knappklasserna står kvar: årsknappen ÄR skärmens primära handling, och §2.3
 * tillåter accenten för precis det ("vägen vidare: primärknappen"). Det som
 * inte får bära accent är Premium som kvalitetsmärke — och det märks med
 * ordet i spärrade kapitäler ovanför.
 */
export function paywallPlanMarkup(pricing = {}) {
  const perMånad = pricing.monthly?.pricePerMonth;
  const perÅr = pricing.yearly?.pricePerYear;
  const rabatt = årsrabatt(pricing);
  const perMånadAvÅr = Number.isFinite(perÅr) ? Math.round(perÅr / 12) : null;
  const villkorÅr = [
    "per år",
    perMånadAvÅr ? `motsvarar ${perMånadAvÅr} kr per månad` : "",
    rabatt ? `spara ${rabatt} kr` : "",
  ].filter(Boolean).join(" · ");
  return `<button type="button" class="btn btn-primary paywall-yearly" data-paywall-plan="yearly">
      <span class="prem-plan-namn">Ett år</span>
      ${prisMarkup(perÅr, undefined, { klass: "prem-plan-tal" })}
      <span class="prem-plan-villkor">${escapeHtml(villkorÅr)}</span>
    </button>
    <button type="button" class="btn btn-ghost paywall-monthly" data-paywall-plan="monthly">
      <span class="prem-plan-namn">Månad för månad</span>
      ${prisMarkup(perMånad, undefined, { klass: "prem-plan-tal" })}
      <span class="prem-plan-villkor">per månad</span>
    </button>`;
}

/**
 * Planens namn i en mening: "Din prenumeration (399 kr per år) förnyas…".
 *
 * Kontoarkets prenumerationsrad skrev det själv, med "399 kr/år" och
 * "59 kr/mån" som reservvärden när /api/entitlements inte svarat. En
 * reservsiffra i en mening om vad kunden BETALAR är den farligaste sorten:
 * den ser rätt ut ända tills backend byter pris. Här finns ingen — vet vi inte
 * beloppet säger raden "din plan", och det är sant.
 *
 * Returnerar ren text, inte markup: raden sätts med textContent i en mening,
 * och prisMarkup() ritar ett element som inte har någonstans att ta vägen där.
 */
export function planetikett(pricing = {}, plan = "") {
  const tal = plan === "yearly" ? pricing.yearly?.pricePerYear
    : plan === "monthly" ? pricing.monthly?.pricePerMonth : null;
  if (!Number.isFinite(tal)) return "din plan";
  return plan === "yearly" ? `${tal} kr per år` : `${tal} kr per månad`;
}
