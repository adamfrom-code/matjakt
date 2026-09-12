// ---------------------------------------------------------------------------
// SPARKVITTOT (H2) — det som står där när listan är avbockad
//
// "Allt handlat! Redo att planera nästa veckas meny?" var ett artigt intet i
// precis det ögonblick användaren gjort jobbet och är som mest mottaglig. Här
// ska i stället stå vad veckan kostade, hur mycket mindre det är än dyraste
// JÄMFÖRBARA butik, och vad det blivit sammanlagt sedan första veckan.
//
// FYRA REGLER, OCH DE ÄR HELA MODULEN.
//
// 1. JÄMFÖRELSEN MÅSTE HÅLLA. En besparing mot en butik som inte är
//    jämförbar är ingen besparing. Servern avgör det - MIN_COVERAGE_FOR_
//    COMPARISON = 85, samma saknade varor i båda kassarna, ingen delad
//    förstaplats, ingen för gammal data - och kröner en kedja bara när allt
//    det håller (compare_chains i backend/services/grocery/api.py). Den här
//    modulen läser `cheapestChain`; den räknar ALDRIG fram en egen billigast.
//    Två oberoende domar om samma fråga hinner till slut säga olika, och då
//    står det en siffra på skärmen som ingen total stöder.
//
// 2. OSÄKRA RADER GÖR TALET OEXAKT (C7). En rad med känt styckpris men gissat
//    paketantal har ingen radtotal och bidrar med noll kronor - kassan blir
//    alltså högre än summan, aldrig lägre. Veckans kostnad skrivs därför
//    "minst 612 kr" så fort motorn säger `totalIsFloor`.
//
//    BESPARINGEN ÄR DÄREMOT INGET GOLV, och det är en skillnad värd att hålla
//    isär. Golvet gäller en SUMMA: den kan bara växa. Besparingen är en
//    SKILLNAD mellan två summor, och en rad kan vara osäker i den ena kassen
//    och exakt i den andra - `exactPackaging` avgörs per butik och produkt.
//    Då kan skillnaden röra sig åt BÅDA hållen, och "minst 83 kr" vore ett
//    påstående åt det farliga hållet om användarens pengar. Den skrivs därför
//    med L0:s ca-form - vi räknar, vi vet inte - så fort någon kassa vi kan se
//    är ett golv, vilar på riktpriser, eller inte går att se alls (Free får
//    bara sin egen kedja omaskad).
//
// 3. UTAN UNDERLAG SÄGS DET RAKT UT. "0 kr sparat" är en lögn när det inte
//    gick att jämföra; "Vi kunde inte jämföra den här veckan" är ett besked.
//    Servern skickar med SKÄLET, och det skrivs ut i klartext.
//
// 4. VILAR JÄMFÖRELSEN PÅ RIKTPRISER SYNS DET. ICA är släppt på referensnivå
//    (D11), så `mixed` är vanligt: en del rader verifierade i butiken, andra
//    kedjans riktpris. Det står i texten, och beloppen bär ca-formen.
//
// PRISMARKUPEN ÄGS AV L0. Varje belopp går genom prisMarkup() i
// src/views/pris.js, och veckans kostnad genom summaTillstånd(). Den här
// modulen skriver ingen egen prislapp och sätter ingen egen prisklass -
// `tests/prisregler.test.js` vaktar det.
//
// EN VECKA, EN SUMMA. Sparloggen bar hittills planerarens UPPSKATTNING,
// skriven när veckan valdes: priciestBranchFor(combo).cost - plan.cost, ur
// den statiska katalogen. src/services/savings-log.js säger själv vad som
// saknades - "posten skrivs fortfarande när veckan VÄLJS, inte när den
// handlats" - och det är precis det här ögonblicket. Kvittot skriver därför
// serverns riktiga tal tillbaka in i veckans post, på samma veckonyckel, så
// att kvittot och Sparat-skärmen (L5) aldrig kan visa två olika summor för
// samma vecka. En ny post skapas aldrig: en vecka utan post planerades aldrig.
//
// OCH DÄRFÖR RÄKNAS DEN LÖPANDE SUMMAN INTE HÄR. L5 äger uträkningen -
// `bärUnderlag`, `nyckelFörPost` och `sparatSedan` i src/views/sparat.js - och
// kvittot importerar den i stället för att bära en egen kopia. Kopian fanns
// ett tag, medan L5 ännu inte landat, med en lapp om att den skulle bytas mot
// ett import-anrop när den gjorde det. Två uträkningar av samma logg hinner
// till slut säga olika, och då står två skärmar i samma app och påstår olika
// saker om användarens pengar. Det enda kvittot lägger till är `exakt`: en
// fråga om postens ursprung, inte om dess belopp.
// ---------------------------------------------------------------------------

import { recordWeekSaving, weekKeyFor } from "../services/savings-log.js";
import { saveState, state } from "../state/app-state.js";
import { escapeHtml } from "../utils/html.js";
import { KONTROLLERAT, UPPSKATTAT, prisMarkup, summaTillstånd } from "./pris.js";
import { bärUnderlag, nyckelFörPost, sparatSedan as sparatSedanL5 } from "./sparat.js";

export { bärUnderlag, nyckelFörPost };

// Serverns egna skäl (compare_chains) i klartext. Nycklarna är motorns, orden
// är skärmens - och listan är komplett: varje `reason` compare_chains kan
// returnera har en mening här, så kortet aldrig behöver tiga.
export const SKÄLTEXT = {
  too_few_comparable_chains: "Bara en butik hade tillräckligt med aktuella priser för hela listan.",
  different_baskets: "Butikerna kunde inte prissätta samma varor, och då svarar deras summor inte på samma fråga.",
  all_totals_identical: "Butikerna landade på samma summa – ingen var billigare.",
  tied_cheapest: "Två butiker delade förstaplatsen, och då finns ingen billigast.",
};
export const SKÄL_OKÄNT = "Underlaget räckte inte för en jämförelse den här veckan.";

// Riktprisbeskedet (regel 4). `basis` är serverns _comparison_basis; i den
// maskade Free-vyn finns bara den prissatta kedjans egen `pricingBasis`, och
// de två skalorna möts här i ett besked per läge.
export const RIKTPRISTEXT = {
  reference: "Jämförelsen vilar på kedjornas riktpriser, inte på priser verifierade i butiken.",
  mixed: "Jämförelsen vilar delvis på riktpriser, inte på priser verifierade i butiken.",
};

// Ett tal, eller null när det inte FINNS ett tal. null och tom sträng måste
// avvisas uttryckligen: Number(null) och Number("") är båda 0, och 0 är ett
// finit tal. En kassa som motorn lämnat som `totalCheckoutCost: null` - för
// att ingen rad var säker - hade annars blivit "Veckan kostade 0 kr", vilket
// är exakt det prispåstående price_list() vägrar göra.
const tal = värde => {
  if (värde == null || värde === "") return null;
  const n = Number(värde);
  return Number.isFinite(n) ? n : null;
};

// ---------------------------------------------------------------------------
// Sparloggen
// ---------------------------------------------------------------------------

/**
 * Den löpande summan: "Ni har sparat 612 kr sedan i september."
 *
 * KRONORNA KOMMER UR L5. `sparatSedanL5()` i src/views/sparat.js är den enda
 * som summerar sparloggen i appen - samma filter (`bärUnderlag`), samma
 * Math.max(0, …), samma sätt att hitta den första månaden. Kvittot och
 * Sparat-skärmen kan därför inte säga olika om samma vecka, för det finns
 * bara en uträkning att säga något med.
 *
 * Det enda som läggs till här är `exakt`, och det är ingen andra summering
 * utan en fråga om posternas URSPRUNG: bär varje post som ingår ett kvitterat,
 * uppmätt tal, eller finns det fortfarande en planerargissning kvar i högen?
 * En enda uppskattad post gör hela summan uppskattad, och då bär beloppet
 * L0:s ca-form i stället för den exakta.
 *
 * `veckor` är L5:s `poster` under kvittots namn - det är veckor i den här
 * loggen, en post per vecka.
 */
export function sparatSedan(logg) {
  const summa = sparatSedanL5(logg);
  const poster = (Array.isArray(logg) ? logg : [])
    .filter(bärUnderlag)
    .filter(post => nyckelFörPost(post));
  return {
    kronor: summa.kronor,
    sedan: summa.sedan,
    veckor: summa.poster,
    exakt: poster.length > 0 && poster.every(post => post.kvitto === true && post.exakt === true),
  };
}

// ---------------------------------------------------------------------------
// Jämförelsen
// ---------------------------------------------------------------------------

/**
 * Kassan för en kedja, som motorn lämnade den. `dbChainTotals` bär bara
 * OMASKADE resultat - src/pricing/sync.js lägger låsta kedjor för sig - så en
 * träff här är alltid ett riktigt resultat med riktiga fält.
 */
function kassan(kedjeTotaler, kedja) {
  if (!kedja || !kedjeTotaler) return null;
  const resultat = kedjeTotaler[kedja];
  return resultat && typeof resultat === "object" ? resultat : null;
}

/**
 * Vad vi kan SE om jämförelsens säkerhet.
 *
 * `golv` är sant när någon synlig kassa saknar radtotal på någon rad, och
 * `riktprisläge` säger om någon av dem inte är butiksverifierad. `kassor` är
 * hur många av de jämförda kedjorna vi faktiskt har resultat för - Free ser
 * bara sin egen, och då kan vi inte påstå något om den andra sidan.
 */
export function jämförelsensSäkerhet(kedjeTotaler, kedjor) {
  const kassor = kedjor.map(kedja => kassan(kedjeTotaler, kedja)).filter(Boolean);
  const basiser = kassor.map(resultat => resultat.pricingBasis).filter(Boolean);
  return {
    kassor: kassor.length,
    golv: kassor.some(resultat => resultat.totalIsFloor === true),
    osäkraRader: kassor.reduce((störst, resultat) => Math.max(störst, Number(resultat.uncertainRows) || 0), 0),
    verifierad: basiser.length > 0 && basiser.every(basis => basis === "VERIFIED"),
    // "helt riktpriser" bara när ingen synlig kassa är verifierad; blandat så
    // fort de skiljer sig. Ingen basis alls är inget påstående.
    riktprisläge: basiser.length === 0 ? null
      : basiser.every(basis => basis === "REFERENCE") ? "reference"
        : basiser.every(basis => basis === "VERIFIED") ? null : "mixed",
  };
}

/**
 * Kvittots modell. Ren funktion - allt kortet visar bestäms här, och inget av
 * det hämtas ur DOM:en.
 *
 * @param jämförelse    state.dbComparison (eller sessionens senaste giltiga)
 * @param kedjeTotaler  state.dbChainTotals
 * @param logg          state.savingsLog
 */
export function sparkvittoModell({ jämförelse, kedjeTotaler, logg } = {}) {
  const summa = sparatSedan(logg);
  const löpande = summa.kronor == null ? null : {
    värde: summa.kronor,
    sedan: summa.sedan,
    veckor: summa.veckor,
    tillstånd: summa.exakt ? KONTROLLERAT : UPPSKATTAT,
  };

  // REGEL 1. Servern kröner en billigaste kedja bara när jämförelsen faktiskt
  // håller; saknas kronan finns ingen besparing att påstå, hur många totaler
  // som än ligger i minnet.
  const kedja = jämförelse?.cheapestChain || null;
  // Premium får `savings` (dyraste minus billigaste). Free får samma tal under
  // ett annat namn - `priceSpread`, räknat av servern över exakt de kedjor som
  // var jämförbara. Det är inte två uträkningar, det är en, maskad.
  const besparing = tal(jämförelse?.savings) ?? tal(jämförelse?.priceSpread);
  if (!kedja || besparing == null || besparing <= 0) {
    const skäl = jämförelse?.reason || null;
    return {
      giltig: false,
      skäl,
      skältext: (skäl && SKÄLTEXT[skäl]) || SKÄL_OKÄNT,
      löpande,
    };
  }

  const dyrasteKedja = jämförelse.priciestChain || null;
  const kassa = kassan(kedjeTotaler, kedja);
  const säkerhet = jämförelsensSäkerhet(kedjeTotaler, [kedja, dyrasteKedja].filter(Boolean));
  // REGEL 2. Veckans kostnad går genom L0:s egen summaTillstånd() - samma
  // avläsning av `pricingBasis` och `totalIsFloor` som varje annan summa i
  // appen gör. Ingen andra tolkning byggs här.
  const veckoTillstånd = summaTillstånd(kassa);
  const exakt = säkerhet.kassor >= 2 && säkerhet.verifierad && !säkerhet.golv;

  return {
    giltig: true,
    kedja,
    dyrasteKedja,
    vecka: {
      värde: kassa ? (tal(kassa.totalCheckoutCost) ?? tal(kassa.cost)) : null,
      tillstånd: veckoTillstånd.tillstånd,
      golv: veckoTillstånd.golv,
      osäkraRader: säkerhet.osäkraRader,
    },
    besparing: {
      värde: besparing,
      // Skillnaden mellan två golv är inget golv - se modulhuvudet.
      tillstånd: exakt ? KONTROLLERAT : UPPSKATTAT,
    },
    riktprisläge: säkerhet.riktprisläge,
    exakt,
    löpande,
  };
}

// ---------------------------------------------------------------------------
// Markup
// ---------------------------------------------------------------------------

const stycke = (klass, innehåll) => `<p class="${klass}">${innehåll}</p>`;

/** Kortets HTML. Varje belopp kommer ur prisMarkup(); inget skrivs för hand. */
export function sparkvittoMarkup(modell) {
  if (!modell) return "";
  const löpande = modell.löpande
    ? stycke("sparkvitto-lopande",
      `Ni har sparat ${prisMarkup(modell.löpande.värde, modell.löpande.tillstånd, { klass: "sparkvitto-tal" })}`
      + ` sedan i ${escapeHtml(modell.löpande.sedan)}.`)
    : "";

  // REGEL 3. Inget "0 kr sparat" när det inte gick att jämföra. Kortet säger
  // vad som hände och varför - och den löpande summan står kvar, för den
  // handlar om alla veckor, inte om den här.
  if (!modell.giltig) {
    return `<div class="sparkvitto sparkvitto-utan">`
      + stycke("sparkvitto-ingen", "Vi kunde inte jämföra den här veckan.")
      + stycke("sparkvitto-skal", escapeHtml(modell.skältext))
      + löpande
      + `</div>`;
  }

  // Veckans kostnad kan saknas trots att jämförelsen håller (kassan hann
  // rensas). Då står bara besparingen - hellre en mening mindre än en mening
  // som säger "pris saknas" mitt i en annan mening.
  const veckoRad = modell.vecka.värde == null ? "" : stycke("sparkvitto-vecka",
    `Veckan kostade ${prisMarkup(modell.vecka.värde, modell.vecka.tillstånd,
      { golv: modell.vecka.golv, klass: "sparkvitto-tal sparkvitto-tal-stor" })}`
    + ` hos ${escapeHtml(modell.kedja)}.`);

  const mot = modell.dyrasteKedja
    ? `än ${escapeHtml(modell.dyrasteKedja)}, den dyraste butiken vi kunde jämföra med`
    : "än den dyraste butiken vi kunde jämföra med";
  const besparingsRad = stycke("sparkvitto-besparing",
    `${prisMarkup(modell.besparing.värde, modell.besparing.tillstånd, { klass: "sparkvitto-tal" })} mindre ${mot}.`);

  // C7 i ord: talet är ett golv, och här står VARFÖR. Utan den här raden är
  // markören bara ett ord användaren får gissa sig till innebörden av.
  const golvRad = modell.vecka.golv
    ? stycke("sparkvitto-not", modell.vecka.osäkraRader
      ? `${modell.vecka.osäkraRader} ${modell.vecka.osäkraRader === 1 ? "vara" : "varor"} saknar säkert antal, så kassan blir högre än summan – aldrig lägre.`
      : "Någon vara gick inte att prissätta, så kassan blir högre än summan – aldrig lägre.")
    : "";

  // REGEL 4.
  const riktprisRad = modell.riktprisläge
    ? stycke("sparkvitto-not", RIKTPRISTEXT[modell.riktprisläge])
    : "";

  return `<div class="sparkvitto">${veckoRad}${besparingsRad}${golvRad}${riktprisRad}${löpande}</div>`;
}

// ---------------------------------------------------------------------------
// Sessionens senaste GILTIGA jämförelse
//
// Varje avbockning kör clearPriceSnapshots(), som nollar state.dbComparison
// med flit: förra listans "Billigast" får aldrig målas som fakta över en ny
// lista. Följden är att jämförelsen är NULL i exakt det ögonblick den sista
// varan bockas av - omhämtningen är i luften - och det är precis då kvittot
// ska ritas. Det är en stor del av varför sparkortet "ofta visar –".
//
// Kvittot håller därför kvar den senaste jämförelse som FAKTISKT höll, per
// veckonyckel. Den ersätts bara av en annan giltig jämförelse och kastas när
// veckan byts. Ingenting hittas på: det som visas är alltid en dom servern
// har fällt om just den här veckan.
// ---------------------------------------------------------------------------

let senaste = { nyckel: null, jämförelse: null, kedjeTotaler: null };

export function återställSparkvitto() {
  senaste = { nyckel: null, jämförelse: null, kedjeTotaler: null };
}

/** Spara undan jämförelsen om den håller. Returnerar den som gäller nu. */
export function minnsJämförelse(veckoNyckel, jämförelse, kedjeTotaler) {
  if (senaste.nyckel !== veckoNyckel) senaste = { nyckel: veckoNyckel, jämförelse: null, kedjeTotaler: null };
  if (jämförelse?.cheapestChain && (tal(jämförelse.savings) ?? tal(jämförelse.priceSpread)) != null) {
    senaste = { nyckel: veckoNyckel, jämförelse, kedjeTotaler };
  }
  return senaste;
}

// ---------------------------------------------------------------------------
// Bokföringen: kvittots tal tillbaka in i sparloggen
// ---------------------------------------------------------------------------

/**
 * Veckans post med kvittots riktiga tal i stället för planerarens gissning -
 * och en post där ingen fanns.
 *
 * SPARLOGGEN HAR ETT HÅL, och det är därför kvittot får skapa poster. Posten
 * skrivs bara av planjämförelsen ("Välj den här"). Den vanliga vägen -
 * "Skapa min vecka" -> chooseMenu() - skriver INGENTING, så för de flesta
 * användare är loggen tom och den löpande summan har aldrig kunnat visas.
 * Mätt i browser-E2E:n: `savingsLog: []` efter en normalt skapad vecka.
 *
 * En post skapas därför när veckan faktiskt HANDLATS och vi har både veckans
 * kostnad och en jämförelse som håller. Det är ett strängare krav än
 * planerarens: den skrev en uppskattning när veckan valdes, det här är ett
 * uppmätt tal när den är buren hem.
 *
 * En BEFINTLIG post får bara sitt belopp utbytt. `date` är veckans, inte
 * kvittots, och `portionCost` lämnas som den står - den syns inte på kortet,
 * och att skriva om den vore en ändring ingen bett om.
 *
 * Returnerar null när ingenting behöver ändras, så anroparen slipper spara:
 * kvittot ritas om vid varje prisuppdatering och får inte skriva localStorage
 * varje gång.
 */
export function bokförKvitto(logg, veckoNyckel, modell, { datum, portionCost } = {}) {
  if (!veckoNyckel || !modell?.giltig) return null;
  const lista = Array.isArray(logg) ? logg : [];
  const post = lista.find(rad => rad?.weekKey === veckoNyckel);
  const kronor = Math.max(0, Math.round(modell.besparing.värde));
  if (post) {
    if (post.kvitto === true && post.exakt === modell.exakt && Math.round(post.savings) === kronor) return null;
    return recordWeekSaving(lista, {
      ...post,
      savings: kronor,
      hasComparison: true,
      branch: modell.kedja || post.branch,
      kvitto: true,
      exakt: modell.exakt,
    });
  }
  // Ingen post: skapa bara när varje fält är ett uppmätt tal. En post med
  // portionCost 0 skulle dra ner "Snittkostnad per portion" med en siffra som
  // aldrig mätts, och en post utan datum hamnar i ingen månad alls.
  if (!datum || !Number.isFinite(portionCost) || portionCost <= 0) return null;
  return recordWeekSaving(lista, {
    date: datum,
    weekKey: veckoNyckel,
    savings: kronor,
    hasComparison: true,
    branch: modell.kedja || "",
    portionCost,
    kvitto: true,
    exakt: modell.exakt,
  });
}

// ---------------------------------------------------------------------------
// Inkopplingen
// ---------------------------------------------------------------------------

const app = {};
export function initSparkvitto(dependencies) {
  Object.assign(app, dependencies);
}

/**
 * Ritar kvittot i #sparkvitto och bokför veckans riktiga tal.
 *
 * `synligt` är Handla-vyns egen bedömning av om listan är avbockad - kvittot
 * får aldrig ha en andra åsikt om när veckan är färdighandlad.
 *
 * Bokföringen sker FÖRE markupen ritas: skrivs kvittots tal in i loggen efter
 * att den löpande summan räknats, visar kortet gamla summan en omritning till
 * och de två raderna säger olika om samma vecka.
 */
export function renderSparkvitto({ synligt } = {}) {
  const värd = app.$ ? app.$("sparkvitto") : null;
  const veckoNyckel = weekKeyFor(state.weekPlan || []);
  const gällande = minnsJämförelse(veckoNyckel, state.dbComparison, state.dbChainTotals);
  if (!synligt) {
    if (värd) värd.innerHTML = "";
    return null;
  }
  const indata = { jämförelse: gällande.jämförelse, kedjeTotaler: gällande.kedjeTotaler };
  const förslag = sparkvittoModell({ ...indata, logg: state.savingsLog });
  // Portionspriset räknas ur veckans UPPMÄTTA kostnad, inte ur katalogen:
  // samma tal som står på kvittot, delat på de portioner veckan faktiskt
  // innehåller. Går det inte att räkna skapas ingen post (se bokförKvitto).
  const portioner = (state.weekPlan || []).filter(Boolean).length * (state.personer || 0);
  const portionCost = förslag.giltig && förslag.vecka.värde != null && portioner > 0
    ? förslag.vecka.värde / portioner : null;
  const uppdaterad = bokförKvitto(state.savingsLog, veckoNyckel, förslag, {
    datum: new Date().toISOString().slice(0, 10),
    portionCost,
  });
  if (uppdaterad) {
    state.savingsLog = uppdaterad;
    saveState();
  }
  const modell = sparkvittoModell({ ...indata, logg: state.savingsLog });
  if (värd) värd.innerHTML = sparkvittoMarkup(modell);
  return modell;
}
