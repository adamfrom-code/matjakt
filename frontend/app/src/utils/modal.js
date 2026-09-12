// Ett lager över sidan - bottenark, modal, inbjudningslandning.
//
// G6: appen hade EN `Escape`-lyssnare (veckoarket) och EN `overflow:hidden`
// (samma ark). Plan-, byt-, konto-, skafferi-, laga-, betalvägg- och
// onboardingmodalerna hade ingen fokusflytt vid öppning, ingen fokusfälla,
// ingen Escape och ingen spärr mot att sidan bakom skrollade. Tab-ordningen
// fortsatte rakt ner i sidan bakom arket, och onboardingmodalen - det första
// en ny användare möter - gick inte att stänga med tangentbord alls.
//
// Kraven står i DESIGNSYSTEM-D.md §5.16 och är krav, inte förslag. De
// implementeras här en gång och återanvänds av varje lager.
//
// ANSVARSFÖRDELNING. `closeModal()` river bara ner lagret (fokus, inert,
// skrollspärr, `hidden`). Appens egna `closeX()` gör sitt eget arbete - rensar
// felrader, nollar bytkontexten - och anropar `closeModal()` som sista steg.
// Escape och bakgrundsklick går därför via `requestCloseModal()`, som kallar
// appens `onClose` när den finns. Utan den uppdelningen hade Escape stängt
// arket men hoppat över städningen, vilket är samma sorts halva sanning som
// paketet finns för att laga.

const FOKUSERBARA = [
  "a[href]",
  "button:not([disabled])",
  "summary",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/** Öppna lager, innerst sist. Escape stänger alltid det översta. */
const lager = [];

function synlig(el) {
  // offsetParent är null för `display:none` och för position:fixed i vissa
  // lägen - därför båda kontrollerna. jsdom-lösa testmiljöer saknar dem helt,
  // och då räknas elementet som synligt (vi kan inte veta bättre).
  if (el.hidden) return false;
  if (typeof el.offsetParent === "undefined" && typeof el.getClientRects === "undefined") return true;
  if (el.offsetParent) return true;
  return typeof el.getClientRects === "function" ? el.getClientRects().length > 0 : false;
}

function fokuserbaraI(panel) {
  return [...panel.querySelectorAll(FOKUSERBARA)].filter(synlig);
}

/** Rubriken, det första en skärmläsare ska höra när lagret öppnas. */
function rubrikI(panel) {
  return panel.querySelector("[data-modal-title],h1,h2,h3") || null;
}

/**
 * Allt utanför lagret görs `inert`: inte klickbart, inte tabbbart, borta ur
 * tillgänglighetsträdet. `.phone-shell` är det stora fallet (hela appen), men
 * `#recipePage`, inbjudningslandningen och en redan öppen modal ligger som
 * syskon till den - och tab-ordningen bryr sig inte om vilket som är "appen".
 */
function gorBakgrundenInert(root) {
  const rörda = [];
  for (const el of [...root.ownerDocument.body.children]) {
    if (el === root || el.contains(root)) continue;
    if (el.hasAttribute("inert")) continue;              // ett yttre lager äger den redan
    el.setAttribute("inert", "");
    rörda.push(el);
  }
  return rörda;
}

/**
 * Öppnar `root` som ett modalt lager.
 *
 * @param {HTMLElement} root  ytterhöljet (bakgrunden), det som bär `hidden`
 * @param {object} [options]
 * @param {HTMLElement} [options.panel]   panelen med role="dialog"; annars första i root
 * @param {HTMLElement} [options.opener]  knappen som öppnade; annars document.activeElement
 * @param {Function} [options.onClose]    appens egen stängning (Escape/bakgrundsklick)
 * @param {boolean} [options.focus=true]  false när anroparen själv fokuserar ett fält
 * @returns {Function} stäng-funktion (samma som closeModal(root))
 */
export function openModal(root, options = {}) {
  if (!root) return () => {};
  const doc = root.ownerDocument || globalThis.document;
  const befintligt = lager.find(l => l.root === root);
  if (befintligt) {
    // Öppnas ett redan öppet lager igen (renderSwapModal ritar om och sätter
    // hidden=false på nytt) ska varken öppnaren eller fokusfällan bytas ut.
    root.hidden = false;
    return befintligt.stäng;
  }

  const panel = options.panel
    || root.querySelector('[role="dialog"]')
    || root;
  const öppnare = options.opener || doc.activeElement || null;

  root.hidden = false;
  const inerta = gorBakgrundenInert(root);
  // Bakgrunden får inte skrolla under arket. Sparas och återställs, så två
  // lager ovanpå varandra inte släpper spärren när det inre stängs.
  const förraOverflow = doc.body.style.overflow;
  doc.body.style.overflow = "hidden";

  const post = { root, panel, öppnare, inerta, förraOverflow, onClose: options.onClose || null };

  post.tangent = (event) => {
    if (lager[lager.length - 1] !== post) return;        // bara det översta lagret lyssnar
    if (event.key === "Escape") {
      event.preventDefault();
      requestCloseModal(root);
      return;
    }
    if (event.key !== "Tab") return;
    const rutor = fokuserbaraI(panel);
    if (!rutor.length) { event.preventDefault(); return; }
    const första = rutor[0];
    const sista = rutor[rutor.length - 1];
    const aktiv = doc.activeElement;
    // Fokus utanför panelen (första Tab efter att rubriken fått fokus, eller
    // ett klick i bakgrunden innan inert hann sättas) dras in igen.
    if (!panel.contains(aktiv)) { event.preventDefault(); (event.shiftKey ? sista : första).focus(); return; }
    if (event.shiftKey && aktiv === första) { event.preventDefault(); sista.focus(); }
    else if (!event.shiftKey && aktiv === sista) { event.preventDefault(); första.focus(); }
  };

  post.stäng = () => closeModal(root);
  lager.push(post);
  doc.addEventListener("keydown", post.tangent, true);

  // Skyddsnät. Appen har kvar kodvägar som gömmer ett ark genom att sätta
  // `hidden` rakt på elementet (och testerna gör det också, för att hoppa
  // förbi onboardingen). Utan det här hade lagret legat kvar i stacken med
  // `inert` på hela appen - en tyst, total låsning av gränssnittet, som
  // dessutom bara syns för den som råkar ta just den vägen.
  if (typeof MutationObserver !== "undefined") {
    post.vakt = new MutationObserver(() => { if (root.hidden) closeModal(root); });
    post.vakt.observe(root, { attributes: true, attributeFilter: ["hidden"] });
  }

  if (options.focus !== false) {
    // Rubriken först: skärmläsaren ska säga VAD som öppnades, inte läsa upp
    // den första knappen i det. Rubriker är inte fokuserbara av sig själva,
    // så den får tabindex="-1" - programmatiskt fokus utan att hamna i
    // tab-ordningen.
    const rubrik = rubrikI(panel);
    const mål = rubrik || fokuserbaraI(panel)[0] || panel;
    if (typeof mål.setAttribute === "function" && !mål.hasAttribute("tabindex")) {
      mål.setAttribute("tabindex", "-1");
    }
    mål.focus?.();
  }
  return post.stäng;
}

/**
 * River ner lagret. Idempotent, och anropar ALDRIG `onClose` - den vägen går
 * via requestCloseModal(), annars stänger appens egen closeX() sig själv i en
 * evig slinga.
 */
export function closeModal(root) {
  const index = lager.findIndex(l => l.root === root);
  if (index === -1) { if (root) root.hidden = true; return; }
  const post = lager[index];
  lager.splice(index, 1);
  const doc = root.ownerDocument || globalThis.document;
  post.vakt?.disconnect();
  doc.removeEventListener("keydown", post.tangent, true);
  post.inerta.forEach(el => el.removeAttribute("inert"));
  doc.body.style.overflow = post.förraOverflow;
  root.hidden = true;
  // Tillbaka till knappen som öppnade. Utan det hamnar fokus på <body> och
  // nästa Tab börjar om från sidans topp - för den som navigerar med
  // tangentbord betyder det att varje stängt ark kostar hela sidan.
  if (post.öppnare && doc.contains(post.öppnare) && typeof post.öppnare.focus === "function") {
    post.öppnare.focus();
  }
}

/** Escape och bakgrundsklick: låt appens egen stängning göra sitt jobb. */
export function requestCloseModal(root) {
  const post = lager.find(l => l.root === root);
  if (post?.onClose) post.onClose();
  else closeModal(root);
}

/** Är lagret öppet? (Används av test och av knappar som växlar.) */
export function isModalOpen(root) {
  return lager.some(l => l.root === root);
}

/** Antal öppna lager - noll betyder att sidan bakom är fri igen. */
export function openModalCount() {
  return lager.length;
}

/** Bara för testerna: nollställ stacken mellan fall. */
export function resetModalLayers() {
  while (lager.length) closeModal(lager[lager.length - 1].root);
}
