// ---------------------------------------------------------------------------
// DE TRE PRISREGLERNA — EN KOMPONENT, INTE SJU KOPIOR
//
// Prisets säkerhet är den enda information i appen som MÅSTE överleva
// gråskala, butiksbelysning på en telefon med nedskruvad ljusstyrka och
// rödgrön färgblindhet. Därför bärs den av FORM, inte av färg
// (DESIGNSYSTEM-D.md §6):
//
//   1. KONTROLLERAT   naken siffra, ingen utsmyckning.
//                     Det som inte är markerat är det du kan lita på.
//   2. UPPSKATTAT     "ca" i kapitäler före talet, plus streckad
//                     understrykning. Vi räknar, vi vet inte.
//   3. SAKNAS         öppen ram med tankstreck. ALDRIG RÖTT: ett saknat
//                     pris är ingen varning, det är ett tomt fack. Rött
//                     skulle lära användaren att systemets ärlighet är ett
//                     fel — och accenten (#8A1F42, ett mörkt rött) betyder
//                     "här är du, här går vägen vidare", raka motsatsen till
//                     "vi vet inte" (§2.3).
//
// Modulen finns för att de sju vyerna i våg L inte ska bygga var sin
// prismarkup. Skriver en vy sin egen `<strong>${pris} kr</strong>` är
// regeln bruten i just den vyn och ingen upptäcker det — det var precis så
// trafikljuset i emoji (R41) kunde leva kvar bredvid den riktiga
// komponenten. Alla vyer kallar prisMarkup(); ingen vy skriver egen markup.
//
// MOTORN ÄGER TILLSTÅNDET, INTE DEN HÄR MODULEN.
// Begreppen finns redan i backend/services/grocery/pricing.py och mappas
// hit av prisTillstånd() — komponenten uttrycker det motorn vet, den
// uppfinner ingen fjärde sanning:
//
//   priceTier VERIFIED_STORE_PRICE + exactPackaging  ->  KONTROLLERAT
//   priceTier REFERENCE_PRICE      + exactPackaging  ->  UPPSKATTAT
//       (priset är riktigt men hämtat ur kedjans referenspriser, inte
//        verifierat i just den butiken)
//   rowUncertain / exactPackaging:false / totalCost:null  ->  SAKNAS
//       (C8: en orimlig rad blir OSÄKER i stället för dyr. Produkten och
//        styckpriset står kvar, men radtotalen är ärligt okänd. Ett tomt
//        fack är sant, 538 kr är det inte.)
//   priceStatus "missing" / "unavailable"            ->  SAKNAS
//
// GOLVET ÄR INGET FJÄRDE TILLSTÅND, DET ÄR EN MODIFIERARE.
// C7: så fort någon rad saknar radtotal är SUMMAN ett golv, inte ett tal —
// "minst 612 kr", aldrig ett exakt belopp. Golvet säger något om summan
// (den kan bara bli högre), tillståndet säger något om talets säkerhet.
// De är ortogonala, och därför är golvet ett tillval på de två tillstånd
// som faktiskt visar ett tal.
// ---------------------------------------------------------------------------

import { escapeHtml } from "../utils/html.js";

export const KONTROLLERAT = "kontrollerat";
export const UPPSKATTAT = "uppskattat";
export const SAKNAS = "saknas";

export const TILLSTÅND = [KONTROLLERAT, UPPSKATTAT, SAKNAS];

// Samma avrundning som money() i app.js. Kopian finns för att en vy ska
// kunna skicka in ett tal utan att först behöva be app.js formatera det —
// och för att den formateringen då aldrig kan skilja sig mellan två vyer.
// Vill en vy skriva "38,50 kr" skickar den in strängen färdig.
function kronor(värde) {
  return `${Math.round(värde).toLocaleString("sv-SE")} kr`;
}

/**
 * Talet som ska stå i markupen, eller null när det inte finns något tal.
 * null, undefined, NaN och Infinity är alla "inget tal" — och komponenten
 * får hellre falla tillbaka på "pris saknas" än skriva ut "NaN kr".
 */
function talet(värde) {
  if (värde == null) return null;
  if (typeof värde === "number") return Number.isFinite(värde) ? kronor(värde) : null;
  const text = String(värde).trim();
  return text === "" ? null : text;
}

/**
 * En prislapp i ett av de tre tillstånden.
 *
 * @param värde      Belopp i kronor (tal) eller färdig sträng ("38,50 kr").
 *                   Saknas talet renderas SAKNAS oavsett vad anroparen bad
 *                   om — komponenten kan inte skriva ut ett tal den inte har.
 * @param tillstånd  KONTROLLERAT | UPPSKATTAT | SAKNAS. Okänt värde tolkas
 *                   som SAKNAS: hellre ett tomt fack än ett tal vi inte kan
 *                   stå för.
 * @param golv       true när talet är ett golv och inte ett belopp (C7).
 *                   Skrivs "minst 612 kr". Ignoreras för SAKNAS — ett golv
 *                   för ett tal som inte finns är ingenting.
 * @param klass      Extra klass på yttersta elementet, för vyer som behöver
 *                   sätta storlek eller placering (t.ex. `summa`).
 */
export function prisMarkup(värde, tillstånd = KONTROLLERAT, { golv = false, klass = "" } = {}) {
  const tal = talet(värde);
  const läge = tal == null || !TILLSTÅND.includes(tillstånd) ? SAKNAS : tillstånd;
  const extra = klass ? ` ${escapeHtml(klass)}` : "";

  // 3 — SAKNAS. Öppen ram; tankstrecket kommer ur .saknas::before så att
  // texten i DOM:en är hela meningen skärmläsaren ska läsa upp.
  if (läge === SAKNAS) {
    return `<span class="pris${extra}"><span class="saknas">pris saknas</span></span>`;
  }

  // Kapitälmarkörerna skrivs som VANLIG TEXT i källan och versaliseras med
  // text-transform (§8). Versaler i HTML gör att skärmläsaren stavar dem
  // bokstav för bokstav: "C-A" i stället för "ca".
  const minst = golv ? `<span class="minst">minst</span>` : "";
  const cirka = läge === UPPSKATTAT ? `<span class="cirka">ca</span>` : "";
  const lägen = [läge === UPPSKATTAT ? "pris--ca" : "", golv ? "pris--golv" : ""].filter(Boolean);
  const klasser = ["pris", ...lägen].join(" ");

  // 1 — KONTROLLERAT utan golv: naken siffra, inget svep av element runt
  // den. Det som inte är markerat är det du kan lita på, och det gäller
  // markupen också.
  if (!minst && !cirka) return `<span class="${klasser}${extra}">${escapeHtml(tal)}</span>`;

  // 2 — UPPSKATTAT (och/eller golv). Strecket sitter på .tal, inte på hela
  // lappen, så understrykningen ligger under SIFFRAN och inte under "ca".
  // sr-only säger i ord det formen säger med streck — en skärmläsare ser
  // ingen streckad linje.
  const ord = [golv ? ", minst" : "", läge === UPPSKATTAT ? ", uppskattat pris" : ""].join("");
  return `<span class="${klasser}${extra}">${minst}${cirka}`
    + `<span class="tal">${escapeHtml(tal)}</span>`
    + `<span class="sr-only">${ord}</span></span>`;
}

/**
 * Motorns rad -> tillstånd. En rad är vad `format_chain_result()` skickar
 * (priceStatus, priceTier, totalCost) eller vad price_list() lämnar internt
 * (exactPackaging, rowUncertain). Båda formerna läses, för båda når vyerna.
 */
export function prisTillstånd(rad) {
  if (!rad) return SAKNAS;
  // Radtotalen är ärligt okänd: gissat paketantal (exactPackaging:false)
  // eller orimlig rad (C8). Priset per styck kan stå kvar, men det är inte
  // det här talet.
  if (rad.rowUncertain === true) return SAKNAS;
  if (rad.exactPackaging === false) return SAKNAS;
  if (rad.priceStatus === "missing" || rad.priceStatus === "estimated") return SAKNAS;
  if (rad.priceStatus === "unavailable") return SAKNAS;
  if (rad.totalCost == null && rad.pris == null) return SAKNAS;
  // Kedjans referenspris är ett riktigt pris, men inte verifierat i just
  // den här butiken. Det är "vi räknar, vi vet inte" — alltså uppskattat.
  if (rad.priceTier === "REFERENCE_PRICE") return UPPSKATTAT;
  return KONTROLLERAT;
}

/**
 * Motorns kedjeresultat -> {tillstånd, golv} för SUMMAN.
 *
 * pricingBasis säger vad summan vilar på (VERIFIED / REFERENCE / MIXED) och
 * totalIsFloor om den är ett golv. MIXED är uppskattat: en summa där bara
 * en del av raderna är butiksverifierade är inte en kontrollerad summa.
 */
export function summaTillstånd(resultat) {
  if (!resultat) return { tillstånd: SAKNAS, golv: false };
  const summa = resultat.totalCheckoutCost != null ? resultat.totalCheckoutCost : resultat.cost;
  if (summa == null) return { tillstånd: SAKNAS, golv: false };
  const basis = resultat.pricingBasis || resultat._pricing_basis;
  return {
    tillstånd: basis && basis !== "VERIFIED" ? UPPSKATTAT : KONTROLLERAT,
    golv: resultat.totalIsFloor === true,
  };
}

/**
 * Teckenförklaringen (§5.7). Tre rader, en per form, med glyfen ritad i
 * samma form som prislappen själv: hel linje, streckad linje, tom ram.
 *
 * Den är inte dekoration — den är hela skälet till att prisreglerna går att
 * LÄRA SIG. Utan den måste man ha memorerat systemet för att kunna läsa det,
 * och då är formkodningen bara en tystare version av att inte säga något.
 * Därför står den kvar även när varje pris är kontrollerat.
 *
 * Glyferna är aria-hidden och tomma: formen upprepas i ord på samma rad, så
 * en skärmläsare får hela innebörden utan att höra "bild" tre gånger.
 */
export function teckenförklaringMarkup() {
  const rad = (glyf, text) =>
    `<span class="not"><span class="${glyf}" aria-hidden="true"></span>${text}</span>`;
  return `<div class="prisnyckel" role="note" aria-label="Så läser du priserna">`
    + rad("prick", "Hel siffra – priset är hämtat hos butiken.")
    + rad("streck", "Streckad siffra med ca – priset är uppskattat.")
    + rad("fyrkant", "Tom ram – priset saknas, och vi gissar inte.")
    + `</div>`;
}
