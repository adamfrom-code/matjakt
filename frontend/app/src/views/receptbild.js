// ---------------------------------------------------------------------------
// RECEPTETS BILDYTA — ETT FOTO ELLER ETT RESERVKORT, ALDRIG ETT HÅL
//
// Elva av receptbankens 240 rätter har inget foto vi får publicera. Det var
// kosmetiskt så länge bilden var en liten ruta i ett kort. Sedan design D
// valdes är det något annat: Ikväll ÄR ett helbleed-foto på 278 px med
// rubriken på bilden (L1), och Veckan är sju rader med 52-pixelsfoton (L2).
// Ett recept utan bild blir då ett hål där maten ska vara, på appens
// viktigaste skärm.
//
// Modulen finns för att det ska vara OMÖJLIGT att rendera det hålet. Varje vy
// kallar receptbildMarkup(); ingen vy skriver sin egen <img>. Saknas fotot
// ritas ett reservkort i stället — och reservkortet är inte en platshållare
// som väntar på en bild, det är ett medvetet utseende.
//
// VARFÖR TYPOGRAFI OCH INTE EN IKON
// Den gamla reservbilden var en streckikon på en grön toning: en karott, en
// fisk, ett blad. Två problem. Ikonen måste GISSA vad rätten är, och gissar
// den fel läser den som en bugg. Och vid 52 px var den oläslig — en klubba
// blev en ballong. Ett tryckt uppslag löser samma problem tvärtom: saknas
// fotot sätter man rättens namn som en typografisk plåt. Den kan inte gissa
// fel, för den säger bara det receptet redan heter.
//
// TVÅ STORLEKAR, EN KOMPONENT
// Kortet bär både hela namnet och ett monogram, och CSS:en väljer efter hur
// brett kortet faktiskt är (@container i styles.css, "M2: RESERVKORTET"):
//
//   ≥132 px   spärrade kapitäler, hårfin linje, rättens namn i Newsreader
//   <132 px   monogrammet ensamt, centrerat — samma bokstav, samma stil
//
// Grundläget är det LILLA. En webbläsare utan container-queries får alltså
// monogramkortet överallt: magrare, men aldrig trasigt och aldrig tomt.
//
// TILLGÄNGLIGHET
// Kortet är ETT role="img" med aria-label som säger att fotot saknas och
// vilken rätt det gäller. Delarna inuti är aria-hidden: en skärmläsare ska
// höra rätten en gång, inte tre, och i varje vy står namnet redan bredvid
// eller under bilden.
// ---------------------------------------------------------------------------

import { RECIPE_FALLBACK_LABEL, kindFor } from "../services/recipe-fallback.js";
import { escapeHtml, safeHttpUrl } from "../utils/html.js";

/** Appens egna receptfoton: frontend/app/assets/recipes/<id>.jpg. */
const EGEN_TILLGÅNG = /^assets\/recipes\/[a-z0-9-]+\.(jpe?g|png|webp)$/i;

// Kort och rader ritar bilden i som mest ~400 px - att ladda 940px-varianten
// där är 3x bandbredd för ingenting (85 kB -> 27 kB per kort, mätt).
// Pexels CDN skalar via query-parametrar; receptdetaljen behåller originalet.
const kortvariant = url => typeof url === "string" && url.includes("images.pexels.com")
  ? url.replace(/([?&])h=\d+&w=\d+/, "$1h=330&w=480")
  : url;

/**
 * Adressen att sätta i src, eller "" när det inte finns någon vi vill ladda.
 *
 * safeHttpUrl() släpper bara igenom http/https, och det ska den fortsätta
 * göra för allt som kommer utifrån. Men den löser mot window.location.href,
 * och i den native appen är den `capacitor://localhost/...` - då faller varje
 * RELATIV adress igenom filtret och blir "". Det gäller appens egna
 * receptfoton, som ligger i bygget bredvid index.html och är precis de
 * adresser vi själva har skrivit. Därför släpps det egna mönstret igenom som
 * det är, och allt annat går genom safeHttpUrl som förut.
 */
export function receptbildUrl(bild, { full = false } = {}) {
  const värde = typeof bild === "string" ? bild.trim() : "";
  if (!värde) return "";
  if (EGEN_TILLGÅNG.test(värde)) return värde;
  return safeHttpUrl(full ? värde : kortvariant(värde)) || "";
}

/** Monogrammet: rättens egen begynnelsebokstav, aldrig en gissning. */
function monogram(namn, etikett) {
  const bokstav = [...String(namn || "").trim(), ...String(etikett || "").trim()]
    .find(tecken => /\p{L}|\p{N}/u.test(tecken));
  return (bokstav || "M").toLocaleUpperCase("sv-SE");
}

/**
 * Reservkortet. Ritas när - och bara när - det inte finns något foto.
 *
 * @param recipe  Receptet som vyerna har det (namn/typ/taggar).
 * @param namn    false när vyn själv skriver ut rättens namn ovanpå kortet.
 *                Ikvälls hjälteyta gör det (rubriken ligger PÅ bilden), och
 *                två namn i samma rektangel är inte en design, det är ett
 *                misstag. Kapitälerna, linjen och monogrammet står kvar.
 */
export function reservkortMarkup(recipe, { namn = true, klass = "" } = {}) {
  const rätt = String(recipe?.namn || "").trim();
  const extra = klass ? ` ${escapeHtml(klass)}` : "";
  const etikett = RECIPE_FALLBACK_LABEL[kindFor(recipe)] || RECIPE_FALLBACK_LABEL.standard;
  // Kapitälerna skrivs som vanlig text och versaliseras med text-transform:
  // versaler i HTML får skärmläsaren att stava dem bokstav för bokstav.
  const kapitäl = `<span class="reservkort-kap" aria-hidden="true">${escapeHtml(etikett)}</span>`;
  const linje = `<span class="reservkort-linje" aria-hidden="true"></span>`;
  const rubrik = namn && rätt
    ? `<span class="reservkort-namn" aria-hidden="true">${escapeHtml(rätt)}</span>` : "";
  const märke = `<span class="reservkort-monogram" aria-hidden="true">${escapeHtml(monogram(rätt, etikett))}</span>`;
  const beskrivning = rätt ? `Foto saknas – ${rätt}` : "Foto saknas";
  // Utan namn står monogrammet kvar även i det stora läget. Annars blev
  // hjälteytan en kapitäletikett på en tom platta - alltså den grå rutan
  // igen, med en rubrik.
  const läge = rubrik ? "" : " reservkort--utan-namn";
  return `<span class="recipe-photo recipe-fallback reservkort${läge}${extra}" role="img" `
    + `aria-label="${escapeHtml(beskrivning)}">${kapitäl}${linje}${rubrik}${märke}</span>`;
}

/**
 * Receptets bildyta: fotot om det finns, annars reservkortet.
 *
 * Ett recept vars `bild` inte går att göra en adress av räknas som utan
 * foto - en <img src=""> är exakt det hål komponenten finns för att stänga.
 */
export function receptbildMarkup(recipe, { namn = true, full = false, klass = "", lat = true } = {}) {
  const extra = klass ? ` ${escapeHtml(klass)}` : "";
  const url = receptbildUrl(recipe?.bild, { full });
  if (!url) return reservkortMarkup(recipe, { namn, klass });
  // Hjältebilden är det första man ser - den laddas inte lat.
  return `<img class="recipe-photo${extra}" src="${escapeHtml(url)}" `
    + `alt="${escapeHtml(String(recipe?.namn || ""))}"${lat ? ' loading="lazy"' : ""} decoding="async">`;
}
