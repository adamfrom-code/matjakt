// ---------------------------------------------------------------------------
// APPENS EGNA DIALOGER (G12)
//
// `confirm()` och `alert()` är webbläsarens dialoger, inte appens. Tre skäl
// till att de inte får finnas kvar:
//
//   1. De ser ut som operativsystemet, mitt i en app som annars har
//      välarbetade bottenark. I den native-paketerade iOS-appen är det värre
//      än så: WKWebView renderar dem som systemdialoger med appens bundle-ID
//      i rubriken, så användaren får se "se.matjakt.app" fråga om hon vill
//      radera sitt konto. Det ser inte ut som en app - det ser ut som ett fel.
//   2. Texten går inte att styra. Ja-knappen heter "OK" på en fråga som inte
//      har ett OK-svar ("Radera ditt konto permanent?"), och avbryt-knappen
//      heter "Avbryt" även när det rätta svaret är "Behåll kontot".
//   3. De blockerar tråden. Ingen av G6:s egenskaper - fokusflytt, fokusfälla,
//      Escape, skrollspärr - finns i dem, och de kan inte få dem.
//
// Ersättningen är ett vanligt modalt lager genom `src/utils/modal.js`, så
// Escape, fokusfällan, `inert` och skrollspärren gäller här utan att skrivas
// om. Svaret kommer som ett löfte i stället för som ett returvärde, vilket är
// hela skillnaden mot `confirm()`: anroparen blir `await`:ande i stället för
// blockerande.
//
// LAGRET BYGGS FÄRSKT VARJE GÅNG och plockas bort när svaret är givet. Det är
// avsiktligt. En dialog som ligger kvar i DOM:en blir `inert` nästa gång ett
// annat ark öppnas (modal.js gör allt utanför lagret inert), och när den sedan
// öppnas UR det arket - "Radera konto" och "Lämna hushåll" sitter båda inne i
// kontoarket - hade den blivit synlig men död. Ett färskt element har ingen
// sådan historia.
//
// Ingen ny CSS: klasserna nedan är kontoarkets egna (`.account-modal`,
// `.account-modal-card`, `.btn`), samma som byt-rätt-modalen använder.
// ---------------------------------------------------------------------------

import { closeModal, openModal } from "../utils/modal.js";

let räknare = 0;

function doc() {
  return globalThis.document;
}

function el(tag, attribut = {}, text) {
  const nod = doc().createElement(tag);
  for (const [namn, värde] of Object.entries(attribut)) {
    if (värde !== undefined && värde !== null && värde !== false) nod.setAttribute(namn, värde);
  }
  // textContent, aldrig innerHTML: texterna kommer från serverfel och från
  // hushållsnamn som användare skrivit själva.
  if (text !== undefined && text !== null) nod.textContent = text;
  return nod;
}

/**
 * Bygger lagret och returnerar delarna. Knapparna läggs i `val`-ordning;
 * varje val är { etikett, svar, stil }.
 */
function byggDialog({ title, body, val }) {
  const id = `appDialogTitle${++räknare}`;
  const rot = el("div", { class: "account-modal app-dialog" });
  const bakgrund = el("button", { type: "button", class: "account-modal-backdrop", "aria-label": "Stäng" });
  const kort = el("div", {
    class: "account-modal-card app-dialog-card",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": id,
  });
  kort.append(el("h2", { id }, title));
  if (body) kort.append(el("p", { class: "plan-modal-hint" }, body));

  const knappar = val.map(({ etikett, stil }) => {
    const knapp = el("button", { type: "button", class: stil });
    // Primärknappen bär sin text i ett <span> - `.btn-primary` är en flexrad
    // med `justify-content:space-between`, och en naken textnod hamnar då i
    // vänsterkanten i stället för i mitten.
    if (stil.includes("btn-primary")) knapp.append(el("span", {}, etikett));
    else knapp.textContent = etikett;
    kort.append(knapp);
    return knapp;
  });

  rot.append(bakgrund, kort);
  return { rot, bakgrund, knappar };
}

/**
 * Visar en fråga och svarar med ett löfte. Escape, bakgrundsklick och
 * avbryt-knappen ger alla samma svar: `false`.
 *
 * @param {object} options
 * @param {string} options.title          frågan, som rubrik
 * @param {string} [options.body]         vad svaret innebär
 * @param {string} options.confirmLabel   vad ja-knappen GÖR - aldrig "OK"
 * @param {string} [options.cancelLabel]  vad nej-knappen bevarar
 * @param {boolean} [options.danger]      destruktiv handling: nej blir primärt
 * @returns {Promise<boolean>}
 */
export function askConfirm({ title, body, confirmLabel, cancelLabel = "Avbryt", danger = false }) {
  // Vid en destruktiv handling är det SÄKRA valet det stora: "Behåll kontot"
  // ligger som primärknapp och "Radera kontot" som röd textknapp. En dialog
  // som gör raderingen till den självklara knappen är en fälla, inte en fråga.
  const val = danger
    ? [
      { etikett: cancelLabel, svar: false, stil: "btn btn-primary" },
      { etikett: confirmLabel, svar: true, stil: "btn account-logout-btn" },
    ]
    : [
      { etikett: confirmLabel, svar: true, stil: "btn btn-primary" },
      { etikett: cancelLabel, svar: false, stil: "btn btn-ghost" },
    ];
  return visa({ title, body, val }, false);
}

/**
 * Visar ett besked som bara går att kvittera. Ersätter `alert()` på de ställen
 * där det inte finns någon felrad att skriva i.
 *
 * @returns {Promise<void>} löst när beskedet kvitterats
 */
export function showNotice({ title, body, closeLabel = "Stäng" }) {
  return visa({ title, body, val: [{ etikett: closeLabel, svar: undefined, stil: "btn btn-primary" }] }, undefined)
    .then(() => undefined);
}

function visa({ title, body, val }, avbrottssvar) {
  const d = doc();
  if (!d?.body) return Promise.resolve(avbrottssvar);
  const { rot, bakgrund, knappar } = byggDialog({ title, body, val });
  d.body.append(rot);

  return new Promise(resolve => {
    let klar = false;
    const svara = värde => {
      if (klar) return;
      klar = true;
      closeModal(rot);
      rot.remove?.();
      resolve(värde);
    };
    // onClose fångar Escape och bakgrundsklick genom modal.js
    // requestCloseModal - båda betyder nej, aldrig ja.
    openModal(rot, { onClose: () => svara(avbrottssvar) });
    bakgrund.addEventListener("click", () => svara(avbrottssvar));
    knappar.forEach((knapp, index) => knapp.addEventListener("click", () => svara(val[index].svar)));
  });
}
