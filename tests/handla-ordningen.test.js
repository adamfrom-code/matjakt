// G13:s acceptanskriterium: i butiken är listan det första man ser, och den
// som handlar ensam får veta att hon inte behöver göra det.
//
// Handla-vyn började med hushållsnot → kostnadsvarning → basvarufråga →
// priskällenot → "Var blir det billigast?" → butikskort → framstegsmätare,
// och FÖRST därefter varorna. Sju block att skrolla förbi med en kundvagn i
// handen, varav ett - butiksvalet - är ett beslut man fattar innan man går
// hemifrån och aldrig i gången. Det bor på Vecka nu.
//
// Omflyttningen finns i markupen. Det som saknades var en grind: ingenting
// hindrade nästa paket från att lägga tillbaka ett block ovanför listan, och
// det är precis så ordningen växte fram första gången - ett block i taget,
// vart och ett rimligt för sig.
//
// Ordningen mäts på KÄLLAN och inte på en renderad DOM med flit: de block som
// ska ligga under listan är `hidden` till vardags, och en mätning som bara
// ser de synliga hade sagt "listan är först" även den dag ett block ovanför
// den råkar fyllas.

import assert from "node:assert/strict";
import test from "node:test";
import { läsFil } from "./fixtures/css-parser.mjs";
import { initAppState, state } from "../frontend/app/src/state/app-state.js";

// Samma skäl som i postnummer-frivilligt.test.js: kedjan account.js →
// auth.js → config.js läser <meta> vid import, alltså innan någon funktion
// körts. Ett minimalt document räcker, och importen måste vara dynamisk för
// att globalen ska hinna finnas.
globalThis.document ??= { querySelector: () => null };
const { initAccountView, renderHousehold } =
  await import("../frontend/app/src/views/account.js");

const html = läsFil("frontend/app/index.html");

/** En skärms källa, från sektionens början till nästa skärm. Kommentarerna
 *  tas bort: just den här filens kommentarer räknar UPP de block som flyttade,
 *  ordagrant, och ett prov som läser dem mäter sin egen motivering. */
function skärmen(klass) {
  const start = html.indexOf(`<section class="screen ${klass}`);
  assert.notEqual(start, -1, `skärmen ${klass} hittades inte i index.html`);
  const slut = html.indexOf('<section class="screen', start + 1);
  return html.slice(start, slut === -1 ? html.length : slut)
    .replace(/<!--[\s\S]*?-->/g, "");
}

const handlaSkärmen = () => skärmen("shopping-screen");

/** Var i Handla-källan ett id står. -1 när det inte står där alls. */
function platsen(skärm, id) {
  return skärm.indexOf(`id="${id}"`);
}

// ---------------------------------------------------------------------------
// LISTAN FÖRST
// ---------------------------------------------------------------------------

test("varulistan står före allt som förut låg ovanför den", () => {
  const skärm = handlaSkärmen();
  const lista = platsen(skärm, "shoppingList");
  assert.notEqual(lista, -1, "#shoppingList finns inte i Handla");

  // Vart och ett av de här blocken låg en gång ovanför varorna. De får ligga
  // kvar i skärmen - de säger riktiga saker - men under listan.
  const efter = {
    shoppingProgress: "framstegsmätaren",
    weekCostAlert: "kostnadsvarningen",
    staplePrompt: "basvarufrågan",
    priceSourceNote: "priskällenoten",
    dabasNote: "Dabas-noten",
    primatAttribution: "priskällans attribution",
  };
  for (const [id, vad] of Object.entries(efter)) {
    const plats = platsen(skärm, id);
    if (plats === -1) continue;                 // blocket är borttaget, också ok
    assert.ok(plats > lista, `${vad} (#${id}) står ovanför varulistan igen`);
  }
});

test("butiksvalet bor på Vecka, inte i Handla", () => {
  const skärm = handlaSkärmen();
  // Butikskorten och jämförelsen är ett beslut man fattar innan man går
  // hemifrån. I gången är de sju block att skrolla förbi.
  for (const id of ["storeCards", "storeCompare", "weekStoreSwitch"]) {
    assert.equal(platsen(skärm, id), -1,
      `#${id} har flyttat tillbaka in i Handla`);
  }
  assert.ok(!skärm.includes("Var blir det billigast?"),
    "butiksjämförelsens rubrik står i Handla igen");

  // ...och de finns kvar, på Vecka. Ett test som bara kräver att de är BORTA
  // passerar också den dag någon raderar dem.
  const veckan = skärmen("week-screen");
  assert.ok(veckan.includes('id="storeCards"'), "butikskorten finns inte på Vecka");
  assert.ok(veckan.includes("Var blir det billigast?"),
    "butiksjämförelsens rubrik finns inte på Vecka");
});

// ---------------------------------------------------------------------------
// HUSHÅLLET SOM ETT ERBJUDANDE, INTE SOM EN INSTÄLLNING
// ---------------------------------------------------------------------------

test("Handla har raden som föreslår hushållet, överst", () => {
  const skärm = handlaSkärmen();
  const rad = platsen(skärm, "basketHouseholdInvite");
  assert.notEqual(rad, -1, "raden som föreslår hushållet saknas i Handla");
  assert.ok(rad < platsen(skärm, "shoppingList"),
    "hushållsraden står under listan - den ska vara det första man ser");
  assert.match(skärm.slice(rad, rad + 400), /Handlar ni ihop/,
    "raden säger inte vad den erbjuder");
  // Raden är dold tills den behövs: markupen får inte visa den för den som
  // redan delar listan.
  assert.match(skärm.slice(rad - 120, rad + 200), /hidden/,
    "raden är inte dold i utgångsläget");
});

test("raden syns bara för den som inte redan delar listan", () => {
  // Den enda riktiga beteendeprövningen som går utan webbläsare: hushållets
  // tillstånd in, `hidden` ut. Nod: en knapp som bara bär det renderingen rör.
  const rad = { hidden: true, dataset: {}, addEventListener() {} };
  initAppState({ storage: null, recipeBank: [] });
  initAccountView({
    $: (id) => (id === "basketHouseholdInvite" ? rad : null),
    householdActive: () => Boolean(state.household.id),
  });

  state.household.id = "";
  renderHousehold();
  assert.equal(rad.hidden, false, "raden döljs för den som handlar ensam");

  state.household.id = "h-1";
  renderHousehold();
  assert.equal(rad.hidden, true, "raden står kvar sedan hushållet väl finns");
});
