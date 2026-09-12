// ---------------------------------------------------------------------------
// SPARAT-VYN (L5) — facit: docs/matjakt-design-D.html, skärmen "Sparat".
//
// Appens viktigaste siffra fanns, men den låg i en 2x2-ruta bland tre andra
// tal och hette "Uppskattat sparat denna vecka". Den här vyn gör den till en
// hjälterubrik på den enda mörka ytan i appen — den starkaste kontrasten
// systemet har (`--paper` på `--ink`, 15,17:1 i ljust läge, 15,59:1 i mörkt).
//
// TRE BESLUT SOM BÄR HELA MODULEN
//
// 1. EN TOM MÅNAD ÄR INTE EN MÅNAD UTAN SPARANDE. En månad utan jämförbart
//    underlag renderas som `saknas` — en öppen ram och ett tankstreck i
//    värderaden — aldrig som en nollstapel. En nollstapel är ett påstående
//    ("ni sparade ingenting"), och det påståendet har vi inte täckning för.
//    En månad som HAR underlag och landar på noll skrivs däremot ut som 0,
//    med ett streck vid baslinjen. Skillnaden är hela produktens existens.
//
// 2. STAPLARNA STÅR MOT EN GEMENSAM SKALA. Höjden är `kronor / max` över
//    HELA serien, inte per stapel. En dubbelt så hög stapel betyder alltså
//    dubbelt så mycket pengar. Skalan fuskas aldrig upp för att en liten
//    stapel ska synas — den synligheten löses med `min-height` i CSS, som
//    inte ljuger om förhållandet mellan två tal.
//
// 3. VYN SKRIVER INGEN PRISMARKUP, OCH KALLAR HELLER INGEN.
//    De tre prisreglerna ägs av L0 i src/views/pris.js och får inte byggas
//    två gånger — den här modulen bygger dem alltså inte, och `tests/
//    prisregler.test.js` ("ingen vy bygger egen prismarkup") vaktar det.
//
//    Den kallar dem inte heller, och det är ett val värt att kunna försvara:
//    Sparat visar BESPARINGAR och ANTAL, inte priser. `prisMarkup(null,
//    SAKNAS)` skriver ordagrant "pris saknas", och det är fel påstående om
//    en månad där ingen vecka har jämförbart underlag — det är inte priset
//    som saknas, det är veckorna. `prisMarkup(v, UPPSKATTAT)` skriver
//    dessutom "ca 210 kr" med streckad understrykning, vilket varken ryms i
//    en sexkolumners månadsremsa eller går att sätta i 82/26 px som
//    hjälterubriken kräver. Facit ritar samma sak: `.stortal` och bara
//    siffror i `.manrad`.
//
//    Därför har den här vyn sitt eget, icke-prisliga ordförråd: det tomma
//    facket heter `.sparat-manad-tomt`, inte `.saknas`. Byter någon senare
//    det mot L0:s delade glyf är det EN klass som flyttar, inte en rad
//    logik.
//
// Modulen känner DOM:en bara genom det den får in via initSparatView().
// Allt nedanför `sparatModell()` är rena funktioner, och det är de som
// testas i tests/sparat.test.js.
// ---------------------------------------------------------------------------

import { escapeHtml } from "../utils/html.js";

const app = {};
export function initSparatView(dependencies) {
  Object.assign(app, dependencies);
}

export const MÅNAD_KORT = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"];
export const MÅNAD_LÅNG = ["januari", "februari", "mars", "april", "maj", "juni",
                           "juli", "augusti", "september", "oktober", "november", "december"];

// Hur många månader diagrammet visar. Sex ryms på 320 px utan att etiketterna
// staplas på varandra, och sex månader är också så långt bakåt sparloggen
// (60 poster, en per vecka) i praktiken räcker.
export const MÅNADER_I_DIAGRAMMET = 6;

// ---------------------------------------------------------------------------
// Datum → månadsnyckel
// ---------------------------------------------------------------------------

const tvåsiffrigt = n => String(n).padStart(2, "0");

/** En `Date` som "2026-09". Lokal tid: posterna skrivs med lokalt datum. */
export function månadsNyckel(datum) {
  return `${datum.getFullYear()}-${tvåsiffrigt(datum.getMonth() + 1)}`;
}

/**
 * Postens månad, eller null när datumet inte går att lita på.
 *
 * Posterna skrivs som `new Date().toISOString().slice(0, 10)`, men loggen
 * synkas mellan klienter och kan ha stått i localStorage i ett år. Ett
 * oläsbart datum får inte hamna i fel månad — det får inte hamna någonstans.
 */
export function nyckelFörPost(post) {
  const rå = post?.date;
  if (typeof rå !== "string" && !(rå instanceof Date)) return null;
  if (typeof rå === "string") {
    const m = /^(\d{4})-(\d{2})(?:-\d{2})?/.exec(rå.trim());
    if (m) {
      const månad = Number(m[2]);
      return månad >= 1 && månad <= 12 ? `${m[1]}-${m[2]}` : null;
    }
  }
  const datum = rå instanceof Date ? rå : new Date(rå);
  return Number.isNaN(datum.getTime()) ? null : månadsNyckel(datum);
}

/**
 * Bär posten en besparing vi kan stå för?
 *
 * `hasComparison` är false när veckan aldrig fick två jämförbara kedjor att
 * ställa mot varandra. Då finns ingen besparing att påstå — bara en vecka som
 * handlades. Att räkna den som 0 kr vore att svara på en fråga vi inte har
 * ställt, och `renderStats` har filtrerat på exakt det här sedan F4.
 */
export function bärUnderlag(post) {
  return Boolean(post?.hasComparison) && Number.isFinite(Number(post?.savings));
}

// ---------------------------------------------------------------------------
// Månadsserien
// ---------------------------------------------------------------------------

/**
 * De `antal` senaste kalendermånaderna, äldst först, med sparsumman i varje.
 *
 * `status: "saknas"` betyder att månaden inte har EN enda post med jämförbart
 * underlag. `status: "data"` med `kronor: 0` betyder att den har poster och
 * att de summerar till noll. De två får aldrig se likadana ut.
 */
export function månadsSerie(logg, { now = new Date(), antal = MÅNADER_I_DIAGRAMMET } = {}) {
  const summor = new Map();
  for (const post of Array.isArray(logg) ? logg : []) {
    if (!bärUnderlag(post)) continue;
    const nyckel = nyckelFörPost(post);
    if (!nyckel) continue;
    const förra = summor.get(nyckel) || { kronor: 0, poster: 0, middagar: 0 };
    förra.kronor += Math.max(0, Number(post.savings));
    förra.poster += 1;
    // Veckonyckeln ÄR veckans rätter ("id|id|id") — antalet middagar den
    // veckan går alltså att räkna ur loggen, daterat, utan ett nytt fält.
    förra.middagar += typeof post.weekKey === "string" && post.weekKey
      ? post.weekKey.split("|").filter(Boolean).length : 0;
    summor.set(nyckel, förra);
  }

  const nuNyckel = månadsNyckel(now);
  const serie = [];
  for (let steg = antal - 1; steg >= 0; steg--) {
    const datum = new Date(now.getFullYear(), now.getMonth() - steg, 1);
    const nyckel = månadsNyckel(datum);
    const träff = summor.get(nyckel);
    serie.push({
      nyckel,
      år: datum.getFullYear(),
      månad: datum.getMonth(),
      kort: MÅNAD_KORT[datum.getMonth()],
      lång: MÅNAD_LÅNG[datum.getMonth()],
      status: träff ? "data" : "saknas",
      kronor: träff ? träff.kronor : null,
      poster: träff ? träff.poster : 0,
      middagar: träff ? träff.middagar : 0,
      pågående: nyckel === nuNyckel,
      procent: null,
    });
  }
  return sättGemensamSkala(serie);
}

/**
 * Stapelhöjderna, i procent av diagrammets höjd, mot EN skala för hela serien.
 *
 * Det är hela poängen med ett diagram: en hög stapel ska betyda mer pengar än
 * en låg. Normaliseras varje stapel mot sig själv blir bilden en lögn som ser
 * ut som statistik. Månader utan underlag får `procent: null` — de har ingen
 * höjd, de har ett tomt fack.
 */
export function sättGemensamSkala(serie) {
  const värden = serie.filter(m => m.status === "data").map(m => m.kronor);
  const max = värden.length ? Math.max(...värden) : 0;
  return serie.map(m => ({
    ...m,
    procent: m.status !== "data" ? null : (max > 0 ? (m.kronor / max) * 100 : 0),
  }));
}

// ---------------------------------------------------------------------------
// Summorna
// ---------------------------------------------------------------------------

/** Sparat sedan första daterade posten med underlag. */
export function sparatSedan(logg) {
  const poster = (Array.isArray(logg) ? logg : [])
    .filter(bärUnderlag)
    .map(post => ({ nyckel: nyckelFörPost(post), kronor: Math.max(0, Number(post.savings)) }))
    .filter(post => post.nyckel);
  if (!poster.length) return { kronor: null, sedan: null, sedanNyckel: null, poster: 0 };
  const tidigast = poster.reduce((a, b) => (a.nyckel <= b.nyckel ? a : b)).nyckel;
  return {
    kronor: poster.reduce((summa, post) => summa + post.kronor, 0),
    sedan: MÅNAD_LÅNG[Number(tidigast.slice(5, 7)) - 1],
    sedanNyckel: tidigast,
    poster: poster.length,
  };
}

/** Summan för de senaste `dagar` dygnen. `null` när ingen post bär underlag. */
export function summaSenasteDygn(logg, dagar, { now = new Date() } = {}) {
  const gräns = now.getTime() - dagar * 86400000;
  const poster = (Array.isArray(logg) ? logg : []).filter(post => {
    if (!bärUnderlag(post)) return false;
    const tid = new Date(post.date).getTime();
    return Number.isFinite(tid) && tid >= gräns;
  });
  return poster.length ? poster.reduce((summa, post) => summa + Math.max(0, Number(post.savings)), 0) : null;
}

// ---------------------------------------------------------------------------
// Modellen
// ---------------------------------------------------------------------------

/**
 * Allt skärmen visar, som data. Ingen DOM, inga strängar som beror på
 * webbläsaren — därför går hela skärmen att pröva i node.
 *
 * `vecka` är det app.js vet om veckan som ligger planerad NU: antal middagar
 * och antal kampanjvaror i inköpslistan. Båda får vara `null`, och då säger
 * raden att underlaget saknas i stället för att skriva ut en nolla vi inte
 * har täckning för (priserna kan helt enkelt inte vara hämtade än).
 */
export function sparatModell(logg, { now = new Date(), antal = MÅNADER_I_DIAGRAMMET, vecka = {} } = {}) {
  const serie = månadsSerie(logg, { now, antal });
  const total = sparatSedan(logg);
  const dennaMånad = serie[serie.length - 1];
  const dennaVecka = summaSenasteDygn(logg, 7, { now });

  const rader = [
    { id: "vecka", etikett: "Den här veckan", kronor: dennaVecka },
    { id: "manad", etikett: "Den här månaden", kronor: dennaMånad?.status === "data" ? dennaMånad.kronor : null },
    { id: "middagar", etikett: "Middagar planerade", antal: Number.isFinite(vecka?.middagar) ? vecka.middagar : null },
    { id: "kampanj", etikett: "Kampanjvaror i maten", antal: Number.isFinite(vecka?.kampanjvaror) ? vecka.kampanjvaror : null },
  ];

  // Delning: bara när det finns en riktig månadssumma att dela. En tom delning
  // är värre än ingen knapp — den lär avsändaren att appen inte vet något.
  const delbar = dennaMånad?.status === "data" && dennaMånad.kronor > 0;

  return {
    total,
    serie,
    dennaMånad,
    rader,
    delbar,
    delningstext: delbar ? delningstext(dennaMånad) : "",
  };
}

/**
 * Texten som delas. H4 gör den här till en 1080×1080-bild; tills dess delas
 * exakt samma mening som ren text, och knappen lovar inte mer än så.
 */
export function delningstext(månad) {
  if (!månad || månad.status !== "data") return "";
  const kronor = Math.round(månad.kronor).toLocaleString("sv-SE");
  const när = månad.pågående ? `hittills i ${månad.lång}` : `på maten i ${månad.lång}`;
  return `Jag sparade ${kronor} kr ${när} · matjakt.store`;
}

// ---------------------------------------------------------------------------
// Markup
// ---------------------------------------------------------------------------

const kr = värde => `${Math.round(värde).toLocaleString("sv-SE")} kr`;

/** `aria-label` för diagrammet: varje värde i ord, inklusive de som saknas. */
export function diagramEtikett(serie) {
  const delar = serie.map(m => {
    if (m.status !== "data") return `${m.lång} saknar underlag`;
    const suffix = m.pågående ? " hittills" : "";
    return `${m.lång} ${Math.round(m.kronor)} kronor${suffix}`;
  });
  return `Sparat per månad: ${delar.join(", ")}.`;
}

/**
 * Staplarna. Höjden står inline mot diagrammets spår, precis som i §5.9 —
 * det är det enda stället i systemet där ett inline-mått är rätt, för talet
 * kommer ur datan och kan inte stå i stilmallen.
 */
export function månadsdiagramMarkup(serie) {
  return serie.map(m => {
    const pågående = m.pågående ? " sparat-manad--pagaende" : "";
    let stapel;
    if (m.status !== "data") {
      stapel = `<i class="sparat-manad-tomt"></i>`;
    } else if (m.kronor > 0) {
      stapel = `<i class="sparat-manad-fyll" style="height:${m.procent.toFixed(1)}%"></i>`;
    } else {
      stapel = `<i class="sparat-manad-noll"></i>`;
    }
    return `<span class="sparat-manad${pågående}">`
      + `<span class="sparat-manad-spar">${stapel}</span>`
      + `<span class="sparat-manad-namn">${escapeHtml(m.kort)}</span></span>`;
  }).join("");
}

/**
 * Värderaden under staplarna. §5.9: diagrammet ska gå att läsa även av den
 * som inte kan tolka en stapellängd — det är kravet, inte en bonus. Här står
 * också skillnaden mellan 0 och saknas utskriven i tecken, inte i höjd.
 */
export function månadsvärdenMarkup(serie) {
  return serie.map(m => {
    if (m.status !== "data") {
      return `<div class="sparat-varde sparat-varde--tomt"><b aria-hidden="true">–</b><small>saknas</small></div>`;
    }
    const hittills = m.pågående ? `<small>hittills</small>` : "";
    return `<div class="sparat-varde"><b>${escapeHtml(Math.round(m.kronor).toLocaleString("sv-SE"))}</b>${hittills}</div>`;
  }).join("");
}

/** Nyckeltalsraderna: etikett till vänster, värdet till höger, 52 px per rad. */
export function nyckeltalMarkup(rader) {
  return rader.map(rad => {
    let värde;
    if ("kronor" in rad) värde = rad.kronor == null ? "Underlag saknas" : kr(rad.kronor);
    else värde = rad.antal == null ? "Underlag saknas" : String(rad.antal);
    const tomt = värde === "Underlag saknas" ? " sparat-tal-varde--tomt" : "";
    return `<li class="sparat-tal-rad"><span class="sparat-tal-etikett">${escapeHtml(rad.etikett)}</span>`
      + `<span class="sparat-tal-varde${tomt}">${escapeHtml(värde)}</span></li>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

export function renderSparat(modell) {
  const $ = app.$;
  if (!$) return modell;

  const hjälte = $("sparatHeroValue");
  const etikett = $("sparatHeroLabel");
  const not = $("sparatHeroNote");
  if (hjälte && etikett && not) {
    if (modell.total.kronor == null) {
      etikett.textContent = "Uppskattat sparat";
      hjälte.innerHTML = `<span class="sparat-hero-tom">Ingen handlad vecka än</span>`;
      not.textContent = "Välj en vecka i Matjakt, så börjar siffran här räknas.";
    } else {
      etikett.textContent = `Sparat sedan i ${modell.total.sedan}`;
      hjälte.innerHTML = `${escapeHtml(Math.round(modell.total.kronor).toLocaleString("sv-SE"))}<small>kr</small>`;
      not.textContent = "Uppskattat mot den dyraste jämförbara kedjan, för de veckor du valt i Matjakt.";
    }
  }

  const diagram = $("sparatManader");
  if (diagram) {
    diagram.innerHTML = månadsdiagramMarkup(modell.serie);
    diagram.setAttribute("aria-label", diagramEtikett(modell.serie));
  }
  const värden = $("sparatManvarden");
  if (värden) värden.innerHTML = månadsvärdenMarkup(modell.serie);

  const tal = $("sparatTal");
  if (tal) tal.innerHTML = nyckeltalMarkup(modell.rader);

  const dela = $("sparatShareBtn");
  if (dela) dela.hidden = !modell.delbar;
  const status = $("sparatShareStatus");
  if (status) status.textContent = "";

  senasteModell = modell;
  return modell;
}

let senasteModell = null;

/**
 * "Dela din månad" — den enkla vägen, inte H4:s bild.
 *
 * H4 gör den här till en 1080×1080-bild i canvas. Tills dess delar knappen
 * exakt den mening bilden kommer att bära, som ren text: `navigator.share`
 * där den finns, urklipp där den inte gör det. Knappen visas bara när det
 * FINNS en månadssumma att dela, och saknas båda vägarna säger den det rakt
 * ut i stället för att se ut att ha gjort något.
 */
export async function delaMånaden(modell = senasteModell) {
  const status = app.$ ? app.$("sparatShareStatus") : null;
  const säg = text => { if (status) status.textContent = text; };
  if (!modell?.delbar) { säg("Det finns ingen månadssumma att dela än."); return "ingen-data"; }
  const text = modell.delningstext;
  try {
    if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
      await navigator.share({ text, url: "https://matjakt.store" });
      säg("");
      return "delad";
    }
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      säg("Texten är kopierad — klistra in den där du vill dela.");
      return "kopierad";
    }
  } catch (fel) {
    // AbortError = användaren stängde delningsarket. Det är inget fel, och
    // det ska inte se ut som ett.
    if (fel?.name === "AbortError") { säg(""); return "avbruten"; }
  }
  säg("Den här webbläsaren kan inte dela. Siffran står kvar här ovanför.");
  return "kan-inte";
}
