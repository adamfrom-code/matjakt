// G6:s acceptanskriterium: Escape stänger varje modal och fokus återvänder
// till knappen som öppnade.
//
// Appen hade EN Escape-lyssnare (veckoarket) och EN skrollspärr (samma ark).
// Plan-, byt-, konto-, skafferi-, laga-, betalvägg- och onboardingmodalerna
// hade ingen fokusflytt, ingen fokusfälla, ingen Escape och ingen spärr mot
// att sidan bakom skrollade. Tab-ordningen fortsatte rakt ner i sidan bakom
// arket, och onboardingmodalen - det FÖRSTA en ny användare möter - gick inte
// att stänga med tangentbord alls.
//
// Två sorters prövning här, för att fyndet har två sidor:
//
//   * beteendet i src/utils/modal.js mot en liten fejk-DOM (fixtures/), och
//   * att varje modal i appen faktiskt GÅR genom modulen - en modal som
//     fortfarande sätter `hidden` själv har ingen av egenskaperna ovan, hur
//     bra modulen än är.
//
// Att `inert` verkligen gör bakgrunden otabbbar och att Escape når fram genom
// en riktig händelsekedja prövas i webbläsaren: se
// test_varje_modal_stangs_med_escape_och_lamnar_tillbaka_fokus.

import assert from "node:assert/strict";
import test from "node:test";
import { läsFil } from "./fixtures/css-parser.mjs";
import { FejkDoc, FejkEl, byggModal } from "./fixtures/fejk-dom.mjs";
import {
  closeModal, isModalOpen, openModal, openModalCount, requestCloseModal, resetModalLayers,
} from "../frontend/app/src/utils/modal.js";

function scen() {
  resetModalLayers();
  const doc = new FejkDoc();
  const appen = new FejkEl("div", { class: "phone-shell" });
  const öppnare = new FejkEl("button", { id: "oppna" });
  appen.append(öppnare);
  doc.body.append(appen);
  const modal = byggModal(doc, "provModal");
  öppnare.focus();
  return { doc, appen, öppnare, ...modal };
}

// ---------------------------------------------------------------------------
// ESCAPE OCH FOKUS - kärnan i kriteriet
// ---------------------------------------------------------------------------

test("Escape stänger modalen", () => {
  const { doc, bakgrund, öppnare } = scen();
  openModal(bakgrund, { opener: öppnare });
  assert.equal(bakgrund.hidden, false);
  doc.tryck("Escape");
  assert.equal(bakgrund.hidden, true, "Escape stängde inte modalen");
  assert.equal(openModalCount(), 0);
});

test("fokus återvänder till knappen som öppnade", () => {
  const { doc, bakgrund, öppnare } = scen();
  openModal(bakgrund, { opener: öppnare });
  assert.notEqual(doc.activeElement, öppnare, "fokus stannade kvar utanför modalen");
  doc.tryck("Escape");
  assert.equal(doc.activeElement, öppnare,
    "fokus hamnade inte tillbaka på knappen som öppnade.\n" +
    "Utan det landar fokus på <body>, och nästa Tab börjar om från sidans\n" +
    "topp - för den som navigerar med tangentbord kostar varje stängt ark\n" +
    "då hela sidan en gång till.");
});

test("fokus går till rubriken, inte till första knappen", () => {
  const { doc, bakgrund, rubrik, öppnare } = scen();
  openModal(bakgrund, { opener: öppnare });
  assert.equal(doc.activeElement, rubrik, "rubriken fick inte fokus");
  assert.equal(rubrik.getAttribute("tabindex"), "-1",
    "rubriken fick fokus utan tabindex=-1 - den går då inte att fokusera alls");
});

test("Escape kallar appens egen stängning, inte bara nedrivningen", () => {
  // closeSwapModal nollar bytkontexten, closeAccountModal rensar felrader.
  // Stängde Escape förbi dem hade arket försvunnit men städningen uteblivit.
  const { doc, bakgrund, öppnare } = scen();
  let städat = 0;
  openModal(bakgrund, { opener: öppnare, onClose: () => { städat += 1; closeModal(bakgrund); } });
  doc.tryck("Escape");
  assert.equal(städat, 1, "appens onClose kördes inte");
  assert.equal(bakgrund.hidden, true);
});

test("onClose som stänger lagret ger ingen evig slinga", () => {
  // closeX() anropar closeModal(), och closeModal() får därför ALDRIG kalla
  // onClose tillbaka. requestCloseModal är den enda vägen in i onClose.
  const { bakgrund, öppnare } = scen();
  let varv = 0;
  openModal(bakgrund, { opener: öppnare, onClose: () => { varv += 1; closeModal(bakgrund); } });
  requestCloseModal(bakgrund);
  assert.equal(varv, 1);
  closeModal(bakgrund);           // ska vara helt tyst
  assert.equal(varv, 1);
});

// ---------------------------------------------------------------------------
// FOKUSFÄLLAN
// ---------------------------------------------------------------------------

test("Tab från sista rutan går till den första, inte ut i sidan bakom", () => {
  const { doc, bakgrund, knappar, öppnare } = scen();
  openModal(bakgrund, { opener: öppnare });
  knappar[knappar.length - 1].focus();
  const händelse = doc.tryck("Tab");
  assert.equal(händelse.förhindrad, true, "Tab fick fortsätta ut ur modalen");
  assert.equal(doc.activeElement, knappar[0]);
});

test("Shift+Tab från första rutan går till den sista", () => {
  const { doc, bakgrund, knappar, öppnare } = scen();
  openModal(bakgrund, { opener: öppnare });
  knappar[0].focus();
  doc.tryck("Tab", { shiftKey: true });
  assert.equal(doc.activeElement, knappar[knappar.length - 1]);
});

test("Tab när fokus hamnat utanför panelen dras in i den igen", () => {
  // Kan hända när ett klick landar i bakgrunden innan inert hunnit gälla,
  // eller när något i appen flyttar fokus medan arket är öppet.
  const { doc, bakgrund, knappar, öppnare } = scen();
  openModal(bakgrund, { opener: öppnare });
  öppnare.focus();                                  // fokus ute i sidan bakom
  const händelse = doc.tryck("Tab");
  assert.equal(händelse.förhindrad, true);
  assert.equal(doc.activeElement, knappar[0], "fokus drogs inte tillbaka in i modalen");

  öppnare.focus();
  doc.tryck("Tab", { shiftKey: true });
  assert.equal(doc.activeElement, knappar[knappar.length - 1]);
});

test("en dold knapp i modalen är inte en fokusruta", () => {
  const { doc, bakgrund, knappar, öppnare } = scen();
  knappar[1].hidden = true;                       // t.ex. swapConfirmBtn
  openModal(bakgrund, { opener: öppnare });
  knappar[0].focus();
  doc.tryck("Tab");
  assert.equal(doc.activeElement, knappar[0], "fällan räknade en dold knapp som en ruta");
});

// ---------------------------------------------------------------------------
// BAKGRUNDEN
// ---------------------------------------------------------------------------

test("appen bakom blir inert och blir det inte permanent", () => {
  const { bakgrund, appen, öppnare } = scen();
  openModal(bakgrund, { opener: öppnare });
  assert.equal(appen.hasAttribute("inert"), true, ".phone-shell blev inte inert");
  assert.equal(bakgrund.hasAttribute("inert"), false, "modalen gjorde sig själv inert");
  closeModal(bakgrund);
  assert.equal(appen.hasAttribute("inert"), false, "inert låg kvar efter stängning");
});

test("sidan bakom får inte skrolla, och får skrolla igen efteråt", () => {
  const { doc, bakgrund, öppnare } = scen();
  assert.equal(doc.body.style.overflow ?? "", "");
  openModal(bakgrund, { opener: öppnare });
  assert.equal(doc.body.style.overflow, "hidden");
  closeModal(bakgrund);
  assert.equal(doc.body.style.overflow, "");
});

// ---------------------------------------------------------------------------
// TVÅ LAGER PÅ VARANDRA (byt -> betalvägg, konto -> betalvägg)
// ---------------------------------------------------------------------------

test("Escape stänger det översta lagret, inte båda", () => {
  const { doc, bakgrund, öppnare } = scen();
  const inre = byggModal(doc, "inreModal");
  const iModalenKnapp = bakgrund.querySelector("button");
  openModal(bakgrund, { opener: öppnare });
  openModal(inre.bakgrund, { opener: iModalenKnapp });

  doc.tryck("Escape");
  assert.equal(inre.bakgrund.hidden, true, "det inre lagret stängdes inte");
  assert.equal(bakgrund.hidden, false, "Escape stängde BÅDA lagren");
  assert.equal(doc.activeElement, iModalenKnapp, "fokus gick inte tillbaka till det yttre lagret");

  doc.tryck("Escape");
  assert.equal(bakgrund.hidden, true);
  assert.equal(doc.activeElement, öppnare);
});

test("skrollspärren släpper först när sista lagret är stängt", () => {
  const { doc, bakgrund, öppnare } = scen();
  const inre = byggModal(doc, "inreModal");
  openModal(bakgrund, { opener: öppnare });
  openModal(inre.bakgrund, { opener: bakgrund.querySelector("button") });
  closeModal(inre.bakgrund);
  assert.equal(doc.body.style.overflow, "hidden", "sidan bakom kunde skrolla med ett ark kvar öppet");
  closeModal(bakgrund);
  assert.equal(doc.body.style.overflow, "");
});

test("det yttre lagret behåller sin inert när det inre stänger", () => {
  const { doc, bakgrund, appen, öppnare } = scen();
  const inre = byggModal(doc, "inreModal");
  openModal(bakgrund, { opener: öppnare });
  openModal(inre.bakgrund, { opener: bakgrund.querySelector("button") });
  closeModal(inre.bakgrund);
  assert.equal(appen.hasAttribute("inert"), true,
    "appen bakom blev tabbbar igen trots att ett ark låg kvar öppet");
});

test("att öppna ett redan öppet lager byter inte öppnare", () => {
  // renderSwapModal ritar om och kallar openModal igen. Hade öppnaren bytts
  // till det som råkade ha fokus då (en knapp INNE i modalen) hade fokus
  // efter stängning hamnat på en nod som inte längre finns på skärmen.
  const { doc, bakgrund, knappar, öppnare } = scen();
  openModal(bakgrund, { opener: öppnare });
  knappar[0].focus();
  openModal(bakgrund);
  assert.equal(openModalCount(), 1, "samma lager registrerades två gånger");
  doc.tryck("Escape");
  assert.equal(doc.activeElement, öppnare);
});

test("isModalOpen svarar på verkligheten", () => {
  const { bakgrund, öppnare } = scen();
  assert.equal(isModalOpen(bakgrund), false);
  openModal(bakgrund, { opener: öppnare });
  assert.equal(isModalOpen(bakgrund), true);
  closeModal(bakgrund);
  assert.equal(isModalOpen(bakgrund), false);
});

// ---------------------------------------------------------------------------
// ...OCH ATT APPENS MODALER FAKTISKT GÅR GENOM MODULEN
// ---------------------------------------------------------------------------

const html = läsFil("frontend/app/index.html");
const app = läsFil("frontend/app/app.js");
const konto = läsFil("frontend/app/src/views/account.js");

const MODALER = ["weekSheet", "feedbackSheet", "accountModal", "pantryModal", "cookModal",
                 "onboardingModal", "planModal", "swapModal", "inviteLanding"];

test("ingen modal öppnas eller stängs förbi modulen", () => {
  // Regex, inte en handskriven lista: nästa modal någon lägger till fångas
  // också. `hidden = false` på en modalrot betyder öppning utan fokusfälla.
  const fusk = [];
  for (const källa of [app, konto]) {
    for (const m of källa.matchAll(/\$\("(\w+)"\)\.hidden = (true|false)|getElementById\("(\w+)"\)\.hidden = (true|false)/g)) {
      const id = m[1] || m[3];
      if (MODALER.includes(id)) fusk.push(`${id}.hidden = ${m[2] || m[4]}`);
    }
  }
  assert.deepEqual(fusk, [], `modaler som sätter hidden själva: ${fusk.join(", ")}`);
});

test("varje modal har en panel med role=dialog och ett namn", () => {
  // Utan role="dialog" aria-modal="true" säger skärmläsaren aldrig att man är
  // inne i en modal - och utan aria-label/labelledby säger den inte vilken.
  const saknas = [];
  for (const id of MODALER) {
    const start = html.indexOf(`id="${id}"`);
    if (start === -1) { saknas.push(`${id}: finns inte i index.html`); continue; }
    const bit = html.slice(start, start + 1400);
    if (!/role="dialog"/.test(bit)) saknas.push(`${id}: ingen role="dialog"`);
    else if (!/aria-modal="true"/.test(bit)) saknas.push(`${id}: ingen aria-modal`);
    else if (!/aria-label(ledby)?="/.test(bit)) saknas.push(`${id}: inget tillgängligt namn`);
  }
  assert.deepEqual(saknas, [], saknas.join("\n"));
});

test("veckoarket ligger utanför .phone-shell", () => {
  // openModal gör allt annat på body-nivå inert. Låg arket INUTI det den
  // spärrar av hade spärren antingen missat sidan bakom eller stängt av
  // arket självt - och det senare syns inte i något test som bara läser
  // attribut, bara i en app som slutar svara.
  const skal = html.indexOf('class="phone-shell"');
  const slut = html.indexOf('id="recipePage"');
  const ark = html.indexOf('id="weekSheet"');
  assert.ok(skal !== -1 && slut !== -1 && ark !== -1);
  assert.ok(ark > slut, "weekSheet ligger kvar inuti .phone-shell");
});

test("den gamla ensamma Escape-lyssnaren är borta", () => {
  assert.ok(!/keydown[\s\S]{0,120}Escape[\s\S]{0,80}weekSheet/.test(app),
    "app.js har kvar sin egen Escape-lyssnare för veckoarket");
});
