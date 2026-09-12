// ---------------------------------------------------------------------------
// JÄMFÖRELSETABELLEN GRATIS / PREMIUM — BARA SANNA RADER
//
// Premiumlistan sålde "Aktuella erbjudanden och kampanjer" och "Laga med det
// du redan har hemma". Båda var gratis och ogatade. Den sa "Obegränsade
// byten" och "Upp till 7 middagar" utan att säga vad fritt är. Varje
// användare som testade en "Premium-funktion" och såg att den redan
// fungerade lärde sig att listan ljuger — och en lista man vet ljuger säljer
// ingenting, inte ens det som faktiskt ingår.
//
// FELET VAR INTE ORDEN, DET VAR ATT DE VAR HANDSKRIVNA.
// Listan stod som nio <li> i index.html bredvid en kodsanning i
// backend/services/accounts/features.py. Två texter om samma sak, och bara
// den ena kördes. J3 flyttade sedan gränsen åt båda hållen (veckotyperna,
// näringsfiltret, meal prep och skafferiet ner till gratis; hushållet och
// sparhistoriken upp) och listan följde inte med, för ingenting tvingade
// den. En ny handskriven text löser ingenting.
//
// DÄRFÖR ÄR TABELLEN EN DATASTRUKTUR OCH INTE EN TEXT.
// Varje rad här nämner de funktionsnycklar ur FEATURES den beskriver, och
// tests/premiumtabellen.test.js läser features.py och kräver att raden
// stämmer mot modellen — i BÅDA riktningarna:
//
//   * varje nyckel i FEATURES ligger i exakt en rad (inget kan glömmas bort,
//     och inget kan säljas två gånger),
//   * varje rads `har` är samma svar som `allowed(FREE, nyckel)` ger,
//   * talen nedan är samma tal som FREE_MAX_DINNERS, PREMIUM_MAX_DINNERS,
//     FREE_MAX_HOUSEHOLD_MEMBERS, PREMIUM_MAX_HOUSEHOLD_MEMBERS,
//     FREE_SAVINGS_WEEKS och PREMIUM_SAVINGS_WEEKS.
//
// Flyttas en funktion mellan nivåerna blir tabellen RÖD, inte tyst fel. Det
// är hela paketet; markupen nedanför är bara hur den ser ut.
//
// FORM, INTE BARA FÄRG (DESIGNSYSTEM-D.md §2.4).
// Ett nej sätts med tankstreck och ett ja med en fylld ruta — samma princip
// som de tre prisreglerna i src/views/pris.js: formen bär betydelsen, så den
// överlever gråskala, färgblindhet och en svartvit utskrift. Och Premium
// märks med ORDET i spärrade kapitäler, aldrig med accenten: §2.3 förbjuder
// uttryckligen accenten för "kvalitet, betyg, favorit, Premium". Systemet har
// en färg och den betyder "här är du, här går vägen vidare".
//
// PRISET GÅR GENOM L0.
// Varje belopp ritas av prisMarkup() i src/views/pris.js. Tabellen skriver
// ingen egen prismarkup, och kan därför inte avrunda eller formatera ett
// belopp annorlunda än resten av appen. Beloppen kommer ur
// /api/entitlements (features.PRICING), så 59 och 399 bor på ett ställe:
// backend. Saknas svaret ännu renderar komponenten "pris saknas" — ett tomt
// fack är sant, ett påhittat tal är det inte.
//
// Priserna är TOTALPRIS INKLUSIVE MOMS. Prisinformationslagen kräver att det
// pris som visas en konsument är det hon betalar, och B2 kontrollerar samma
// sak på Stripe-sidan (backend/tests/test_billing_moms.py). Därför står
// momsraden i foten och inte i ett villkorsdokument.
//
// PROVPERIODEN STÅR MED FLIT INTE I TABELLEN.
// J3 gav sju dagars Premium efter den FÖRSTA skapade veckan
// (billing/activation.py ACTIVATION_TRIAL_DAYS). Det är en belöning bunden
// till kontots historik och kan bara delas ut en gång — för den som redan
// förbrukat den vore "sju dagar ingår" en ny osanning av precis den sort
// paketet finns för att ta bort. /api/entitlements svarar inte heller med
// den, så klienten kan i dag inte veta vem den talar med. Den raden skrivs
// när svaret bär informationen, inte innan.
// ---------------------------------------------------------------------------

import { escapeHtml } from "../utils/html.js";
import { prisMarkup } from "./pris.js";

// Samma tal som backend/services/accounts/features.py. De står här för att
// markupen ska kunna byggas utan ett serversvar, och testet kräver att de är
// identiska med modellens — en kopia som inte får glida isär är något annat
// än en andra sanning.
export const GRATIS_MAX_MIDDAGAR = 5;
export const PREMIUM_MAX_MIDDAGAR = 7;
export const GRATIS_MAX_HUSHALL = 2;
export const PREMIUM_MAX_HUSHALL = 12;
export const GRATIS_SPARVECKOR = 1;
export const PREMIUM_SPARVECKOR = 52;

// Tankstreck (U+2013), aldrig bindestreck (§8). Ett nej är ett tomt fack.
export const TANKSTRECK = "–";

/**
 * Raderna. `funktioner` är nycklarna ur FEATURES som raden beskriver, och
 * `har` är svaret på "ingår det i den här nivån?". `text` är ett värde som
 * ersätter ja/nej-glyfen — den används där skillnaden är ett TAL och inte ett
 * på/av: Free planerar fem middagar, inte "inga middagar".
 *
 * En rad får bara gruppera funktioner som ligger på SAMMA nivå. Gör den inte
 * det faller testet, för då döljer rubriken en skillnad.
 */
export const RADER = [
  {
    nyckel: "middagar",
    etikett: "Middagar per vecka",
    funktioner: ["seven_dinners"],
    gratis: { har: false, text: `1–${GRATIS_MAX_MIDDAGAR}` },
    premium: { har: true, text: `1–${PREMIUM_MAX_MIDDAGAR}` },
  },
  {
    nyckel: "veckotyper",
    etikett: "Alla veckotyper: familj, budget, träning, bulk, snabb, vegetarisk, balanserad",
    funktioner: ["standard_week", "family_week", "budget_week", "training_week",
      "bulk_week", "quick_week", "vegetarian_week", "balanced_week"],
    gratis: { har: true },
    premium: { har: true },
  },
  {
    nyckel: "recept",
    etikett: "Receptbanken och favoriter",
    funktioner: ["recipe_search", "favorites"],
    gratis: { har: true },
    premium: { har: true },
  },
  {
    nyckel: "naring",
    etikett: "Näringsmål, kcal- och proteinfilter, meal prep",
    funktioner: ["advanced_nutrition", "meal_prep"],
    gratis: { har: true },
    premium: { har: true },
  },
  {
    nyckel: "skafferi",
    etikett: "Skafferiet och ”Laga med det jag har”",
    funktioner: ["basic_pantry", "full_pantry"],
    gratis: { har: true },
    premium: { har: true },
  },
  {
    nyckel: "billigast",
    etikett: "Riktigt pris och inköpslista hos billigaste butiken",
    funktioner: ["cheapest_store_price", "cheapest_store_basket"],
    gratis: { har: true },
    premium: { har: true },
  },
  {
    nyckel: "allabutiker",
    etikett: "Alla butikers priser och inköpslistor",
    funktioner: ["all_store_prices", "all_store_baskets"],
    gratis: { har: false },
    premium: { har: true },
  },
  {
    nyckel: "jamforelse",
    etikett: "Exakt jämförelse mellan butikerna",
    funktioner: ["store_comparison"],
    gratis: { har: false },
    premium: { har: true },
  },
  {
    nyckel: "livepriser",
    etikett: "Pris per vara, hämtat hos butiken",
    funktioner: ["live_prices"],
    gratis: { har: false },
    premium: { har: true },
  },
  {
    nyckel: "hushall",
    etikett: "Dela vecka, lista och skafferi i hushållet",
    funktioner: ["household_sharing"],
    gratis: { har: false, text: `${GRATIS_MAX_HUSHALL} personer` },
    premium: { har: true, text: `Upp till ${PREMIUM_MAX_HUSHALL} personer` },
  },
  {
    nyckel: "sparhistorik",
    etikett: "Sparhistorik och månadsrapport",
    funktioner: ["savings_history"],
    gratis: { har: false, text: GRATIS_SPARVECKOR === 1 ? "Senaste veckan" : `${GRATIS_SPARVECKOR} veckor bakåt` },
    premium: { har: true, text: `${PREMIUM_SPARVECKOR} veckor bakåt` },
  },
];

/**
 * Avvikelser mellan tabellen och affärsmodellen. `modell` är features.py läst
 * som data: { funktioner: Map<nyckel, fri>, tal: { ... } }.
 *
 * Funktionen bor i modulen och inte i testet med avsikt: den är kontraktet,
 * och ett kontrakt som bara finns i sitt eget test går att skriva om
 * tillsammans med testet. Testet matar den med både den riktiga modellen och
 * saboterade modeller, och kräver att rätt rader pekas ut i båda fallen.
 */
export function avvikelser(modell, rader = RADER) {
  const fynd = [];
  const sedda = new Map();

  for (const rad of rader) {
    if (!rad.funktioner?.length) {
      fynd.push(`${rad.nyckel}: raden nämner ingen funktion i features.py`);
      continue;
    }
    if (rad.premium?.har !== true) {
      fynd.push(`${rad.nyckel}: Premium har varje funktion i modellen (allowed() säger ja)`);
    }
    for (const funktion of rad.funktioner) {
      if (sedda.has(funktion)) {
        fynd.push(`${funktion}: ligger i både raden ${sedda.get(funktion)} och ${rad.nyckel}`);
      }
      sedda.set(funktion, rad.nyckel);
      if (!modell.funktioner.has(funktion)) {
        fynd.push(`${funktion} (raden ${rad.nyckel}): finns inte i FEATURES`);
        continue;
      }
      const fri = modell.funktioner.get(funktion);
      if (fri !== Boolean(rad.gratis?.har)) {
        fynd.push(fri
          ? `${funktion} (raden ${rad.nyckel}): är gratis i features.py men säljs som Premium`
          : `${funktion} (raden ${rad.nyckel}): är Premium i features.py men utlovas gratis`);
      }
    }
  }

  for (const funktion of modell.funktioner.keys()) {
    if (!sedda.has(funktion)) fynd.push(`${funktion}: finns i FEATURES men i ingen rad i tabellen`);
  }

  const tal = [
    ["FREE_MAX_DINNERS", GRATIS_MAX_MIDDAGAR],
    ["PREMIUM_MAX_DINNERS", PREMIUM_MAX_MIDDAGAR],
    ["FREE_MAX_HOUSEHOLD_MEMBERS", GRATIS_MAX_HUSHALL],
    ["PREMIUM_MAX_HOUSEHOLD_MEMBERS", PREMIUM_MAX_HUSHALL],
    ["FREE_SAVINGS_WEEKS", GRATIS_SPARVECKOR],
    ["PREMIUM_SAVINGS_WEEKS", PREMIUM_SPARVECKOR],
  ];
  for (const [namn, vårt] of tal) {
    const deras = modell.tal?.[namn];
    if (deras !== vårt) fynd.push(`${namn}: tabellen säger ${vårt}, features.py säger ${deras}`);
  }

  return fynd;
}

// ------------------------------------------------------------------- markup

/**
 * En cell. Ett tal eller ett värde skrivs som text; ett rent ja/nej bärs av
 * FORM — fylld ruta mot tankstreck — och upprepas i ord för skärmläsaren,
 * som varken ser en ruta eller ett streck.
 */
function cell(svar) {
  if (svar?.text) {
    return `<td class="jamfor-cell"><span class="jamfor-varde">${escapeHtml(svar.text)}</span></td>`;
  }
  return svar?.har
    ? `<td class="jamfor-cell"><span class="jamfor-ja"></span><span class="sr-only">ingår</span></td>`
    : `<td class="jamfor-cell"><span class="jamfor-nej"></span><span class="sr-only">ingår inte</span></td>`;
}

/**
 * Prisraden. Beloppen ritas av L0:s komponent, aldrig av den här filen.
 * `pricing` är features.PRICING så som /api/entitlements lämnar den.
 */
function prisrad(pricing = {}) {
  const månad = pricing.monthly?.pricePerMonth;
  const år = pricing.yearly?.pricePerYear;
  return `<tr class="jamfor-rad jamfor-rad--pris">`
    + `<th scope="row" class="jamfor-etikett">Pris</th>`
    + `<td class="jamfor-cell">${prisMarkup(0)}</td>`
    + `<td class="jamfor-cell">${prisMarkup(månad)}<span class="jamfor-per">per månad</span>`
    + `${prisMarkup(år)}<span class="jamfor-per">per år</span></td>`
    + `</tr>`;
}

/**
 * Hela tabellen. Samma markup i kontoarket och i betalväggen — två listor
 * som säger olika saker om samma produkt är exakt det fel paketet tar bort.
 */
export function jamforelseMarkup(pricing = {}) {
  const rader = RADER.map(rad =>
    `<tr class="jamfor-rad">`
    + `<th scope="row" class="jamfor-etikett">${escapeHtml(rad.etikett)}</th>`
    + cell(rad.gratis) + cell(rad.premium)
    + `</tr>`).join("");

  return `<table class="jamfor">`
    + `<caption class="sr-only">Vad som ingår i gratisversionen och vad som ingår i Premium</caption>`
    + `<thead><tr class="jamfor-rad">`
    + `<td class="jamfor-tom"></td>`
    + `<th scope="col" class="jamfor-rubrik"><span class="jamfor-niva">Gratis</span></th>`
    + `<th scope="col" class="jamfor-rubrik"><span class="jamfor-niva jamfor-premium">Premium</span></th>`
    + `</tr></thead>`
    + `<tbody>${prisrad(pricing)}${rader}</tbody>`
    + `</table>`
    + `<p class="jamfor-not">`
    + `<span class="jamfor-not-rad"><span class="jamfor-ja" aria-hidden="true"></span>Ingår.</span>`
    + `<span class="jamfor-not-rad"><span class="jamfor-nej" aria-hidden="true"></span>Ingår inte.</span>`
    + `<span class="jamfor-not-rad">Alla priser är totalpris inklusive moms.</span>`
    + `</p>`;
}
