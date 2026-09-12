// G5: svep vänster tar bort en vara ur inköpslistan.
//
// Gesten ersätter ett 30x30-kryss som satt i tumzonen, intill "Köpt". Den
// enda intressanta frågan om en sådan gest är när den INTE ska utlösa: en
// skrollning genom en lång lista får aldrig råka radera en vara.

import assert from "node:assert/strict";
import test from "node:test";
import { LUTNING, TRÖSKEL_PX, kopplaSvepBort, ärBorttagssvep }
  from "../frontend/app/src/utils/swipe-remove.js";

test("ett långt svep åt vänster är ett borttag", () => {
  assert.equal(ärBorttagssvep(-120, 4), true);
  assert.equal(ärBorttagssvep(-TRÖSKEL_PX - 1, 0), true);
});

test("en skrollning är inte ett borttag, hur lång den än är", () => {
  assert.equal(ärBorttagssvep(-120, 300), false, "en lodrät rörelse räknades som svep");
  assert.equal(ärBorttagssvep(-100, 100), false, "en diagonal rörelse räknades som svep");
  // Precis på gränsen: lika mycket vågrätt som lutningen kräver räcker inte.
  assert.equal(ärBorttagssvep(-100, 100 / LUTNING), false);
});

test("kort, eller åt höger, är inte ett borttag", () => {
  assert.equal(ärBorttagssvep(-TRÖSKEL_PX + 1, 0), false, "ett kort svep räckte");
  assert.equal(ärBorttagssvep(120, 0), false, "ett svep åt höger tog bort en vara");
  assert.equal(ärBorttagssvep(0, 0), false, "ett rent tryck tog bort en vara");
});

/** Minsta möjliga stubbar: modulen rör bara addEventListener, style och closest. */
function rigga({ rad = { style: {} } } = {}) {
  const lyssnare = {};
  const behållare = {
    addEventListener: (typ, fn) => { lyssnare[typ] = fn; },
    removeEventListener: (typ) => { delete lyssnare[typ]; },
  };
  const borttagna = [];
  const koppla = kopplaSvepBort(behållare, { väljRad: () => rad, taBort: (r) => borttagna.push(r) });
  const peka = (typ, x, y, extra = {}) =>
    lyssnare[typ]?.({ pointerType: "touch", clientX: x, clientY: y, target: {}, ...extra });
  return { peka, borttagna, rad, koppla, lyssnare };
}

test("svepet tar bort raden och låter den följa fingret på vägen", () => {
  const { peka, borttagna, rad } = rigga();
  peka("pointerdown", 300, 200);
  peka("pointermove", 260, 202);
  assert.equal(rad.style.transform, "translateX(-40px)", "raden följde inte fingret");
  peka("pointermove", 180, 204);
  peka("pointerup", 180, 204);
  assert.equal(borttagna.length, 1);
  assert.equal(rad.style.transform, "", "raden lämnades förskjuten efter svepet");
});

test("en skrollning släpper raden direkt och tar inte bort något", () => {
  const { peka, borttagna, rad } = rigga();
  peka("pointerdown", 300, 200);
  peka("pointermove", 292, 260);        // mest lodrätt: det här är en skrollning
  assert.equal(rad.style.transform, "", "raden flyttade sig under en skrollning");
  peka("pointermove", 150, 400);        // även om fingret sedan råkar dra åt vänster
  peka("pointerup", 150, 400);
  assert.deepEqual(borttagna, [], "en skrollning tog bort en vara");
});

test("mus sveper inte - där finns krysset kvar", () => {
  const { peka, borttagna } = rigga();
  peka("pointerdown", 300, 200, { pointerType: "mouse" });
  peka("pointerup", 100, 200, { pointerType: "mouse" });
  assert.deepEqual(borttagna, []);
});

test("ett avbrutet svep lämnar ingenting efter sig", () => {
  const { peka, borttagna, rad } = rigga();
  peka("pointerdown", 300, 200);
  peka("pointermove", 200, 202);
  peka("pointercancel", 200, 202);
  assert.equal(rad.style.transform, "");
  peka("pointerup", 120, 202);
  assert.deepEqual(borttagna, [], "ett avbrutet svep tog ändå bort varan");
});

test("utan en rad att svepa händer ingenting", () => {
  const lyssnare = {};
  const behållare = { addEventListener: (t, f) => { lyssnare[t] = f; }, removeEventListener() {} };
  const borttagna = [];
  kopplaSvepBort(behållare, { väljRad: () => null, taBort: (r) => borttagna.push(r) });
  lyssnare.pointerdown({ pointerType: "touch", clientX: 300, clientY: 200, target: {} });
  lyssnare.pointerup({ pointerType: "touch", clientX: 100, clientY: 200, target: {} });
  assert.deepEqual(borttagna, []);
});

test("saknas behållaren kraschar inte appen", () => {
  assert.doesNotThrow(() => kopplaSvepBort(null, { väljRad: () => null, taBort: () => {} })());
  assert.doesNotThrow(() => kopplaSvepBort({ addEventListener() {} })());
});

// ---------------------------------------------------------------------------
// L3 · SAMMA HANDLING, UTAN FINGER
//
// Ett svep är otillgängligt i samma sekund som det är ENDA vägen: den som
// styr med tangentbord har inget finger att dra med, och den som lyssnar på
// en skärmläsare får aldrig veta att gesten finns. Design D:s varurad har
// inget kryss inuti sig - krysset ligger i .vara-sido utanför radens kant -
// så vägen måste finnas på raden själv.
//
// Kravet är inte "det finns en tangent som råkar ta bort något". Kravet är
// att de två vägarna gör SAMMA sak: samma taBort, alltså samma borttagning
// och samma Ångra-toast. Skulle de kalla var sin kopia vore tangentbords-
// vägen en sämre variant, och den skillnaden syns inte förrän någon står
// utan mus. Därför prövas de här mot samma funktion, och app.js läses för
// att bevisa att den skickar in just den.
// ---------------------------------------------------------------------------

import { readFileSync } from "node:fs";
import { BORTTAGSTANGENTER, kopplaTangentbordsBorttag } from "../frontend/app/src/utils/swipe-remove.js";

/** Behållaren, med en rad som "har fokus" när tangenten trycks. */
function riggaTangent({ rad = { style: {} }, väljRad } = {}) {
  const lyssnare = {};
  const behållare = {
    addEventListener: (typ, fn) => { lyssnare[typ] = fn; },
    removeEventListener: (typ) => { delete lyssnare[typ]; },
  };
  const borttagna = [];
  const koppla = kopplaTangentbordsBorttag(behållare, {
    väljRad: väljRad || (() => rad),
    taBort: (r) => borttagna.push(r),
  });
  let hejdade = 0;
  const tryck = (key, extra = {}) => lyssnare.keydown?.({
    key, target: {}, preventDefault: () => { hejdade += 1; }, ...extra,
  });
  return { tryck, borttagna, rad, koppla, hejdat: () => hejdade };
}

test("L3: Delete och Backspace på den fokuserade raden tar bort den", () => {
  for (const tangent of BORTTAGSTANGENTER) {
    const { tryck, borttagna, rad, hejdat } = riggaTangent();
    tryck(tangent);
    assert.deepEqual(borttagna, [rad], `${tangent} tog inte bort raden`);
    assert.equal(hejdat(), 1, `${tangent} lämnades kvar åt webbläsaren (Backspace = bakåt)`);
  }
});

test("L3: tangentbordsvägen och svepet kallar SAMMA taBort", () => {
  // Det är hela kravet. Två vägar, en handling - inte två implementationer
  // som råkar likna varandra idag och glider isär i morgon.
  const lyssnare = {};
  const behållare = {
    addEventListener: (typ, fn) => { lyssnare[typ] = fn; },
    removeEventListener() {},
  };
  const rad = { style: {} };
  const kallade = [];
  const taBort = (r) => kallade.push(r);
  const väljRad = () => rad;
  kopplaSvepBort(behållare, { väljRad, taBort });
  kopplaTangentbordsBorttag(behållare, { väljRad, taBort });

  lyssnare.pointerdown({ pointerType: "touch", clientX: 300, clientY: 200, target: {} });
  lyssnare.pointermove({ pointerType: "touch", clientX: 150, clientY: 202, target: {} });
  lyssnare.pointerup({ pointerType: "touch", clientX: 150, clientY: 202, target: {} });
  lyssnare.keydown({ key: "Delete", target: {}, preventDefault() {} });

  assert.deepEqual(kallade, [rad, rad], "svepet och tangenten gick inte till samma borttagning");
});

test("L3: app.js binder båda vägarna till samma funktion", () => {
  // En grind, inte en gissning: byter någon ut den ena vägens taBort mot en
  // egen kopia faller det här, och kravet är brutet i just den raden.
  const källa = readFileSync(new URL("../frontend/app/app.js", import.meta.url), "utf8");
  const svep = källa.match(/kopplaSvepBort\(([^;]*?)\);/s);
  const tangent = källa.match(/kopplaTangentbordsBorttag\(([^;]*?)\);/s);
  assert.ok(svep, "app.js kopplar inget svep till inköpslistan");
  assert.ok(tangent, "app.js kopplar ingen tangentbordsväg till inköpslistan - svepet är enda vägen");
  const argument = text => {
    const träff = text.match(/\{\s*väljRad:\s*([A-Za-zÅÄÖåäö_$][\w$]*)\s*,\s*taBort:\s*([A-Za-zÅÄÖåäö_$][\w$]*)\s*\}/);
    assert.ok(träff, `kopplingen skickar in en egen funktion i stället för en delad:\n${text}`);
    return { väljRad: träff[1], taBort: träff[2] };
  };
  assert.deepEqual(argument(tangent[1]), argument(svep[1]),
    "tangentbordsvägen fick en egen väljRad/taBort - då är den en sämre kopia av svepet");
});

test("L3: i ett textfält betyder Backspace fortfarande 'radera ett tecken'", () => {
  for (const fält of [{ tagName: "INPUT" }, { tagName: "TEXTAREA" }, { isContentEditable: true }]) {
    const { tryck, borttagna } = riggaTangent();
    tryck("Backspace", { target: fält });
    assert.deepEqual(borttagna, [], `Backspace i ${fält.tagName || "contenteditable"} raderade en vara`);
  }
});

test("L3: en modifierare betyder något annat i systemet", () => {
  for (const modifierare of ["altKey", "ctrlKey", "metaKey"]) {
    const { tryck, borttagna } = riggaTangent();
    tryck("Backspace", { [modifierare]: true });
    assert.deepEqual(borttagna, [], `${modifierare}+Backspace tolkades som "ta bort varan"`);
  }
});

test("L3: andra tangenter, och fokus utanför en rad, gör ingenting", () => {
  const { tryck, borttagna } = riggaTangent();
  for (const tangent of ["Enter", " ", "ArrowLeft", "x", "Escape"]) tryck(tangent);
  assert.deepEqual(borttagna, [], "en vanlig tangent tog bort en vara");

  const utanför = riggaTangent({ väljRad: () => null });
  utanför.tryck("Delete");
  assert.deepEqual(utanför.borttagna, [], "Delete utanför listan tog bort något");
});

test("L3: kopplingen går att koppla bort, och tål att behållaren saknas", () => {
  const { tryck, borttagna, koppla } = riggaTangent();
  koppla();
  tryck("Delete");
  assert.deepEqual(borttagna, [], "lyssnaren satt kvar efter avkoppling");
  assert.doesNotThrow(() => kopplaTangentbordsBorttag(null, { väljRad: () => null, taBort() {} })());
  assert.doesNotThrow(() => kopplaTangentbordsBorttag({ addEventListener() {} })());
});

test("L3: raden är ett fokuserbart element och säger att tangenten finns", async () => {
  // En tangentbordsväg som ingen kan nå eller få veta om är ingen väg. Radens
  // knapp är tabbstoppet, och aria-keyshortcuts är det enda sättet en
  // skärmläsare kan berätta att Delete gör något just här.
  const { initAppState } = await import("../frontend/app/src/state/app-state.js");
  const { initShoppingView, shoppingRowMarkup } = await import("../frontend/app/src/views/shopping.js");
  initAppState({ storage: null, recipeBank: [] });
  initShoppingView({
    databaseItemFor: () => null, itemStatus: () => "NEED_TO_BUY", itemCategory: () => "Övrigt",
    money: v => `${v} kr`, plural: (n, en, fler) => `${n} ${n === 1 ? en : fler}`,
    pantryForPricing: () => ({}), pricingPending: () => false, livePricesLoading: () => false,
    validChains: [], chosenStore: () => "Willys",
  });
  const html = shoppingRowMarkup({ namn: "Gul lök", total: 1, unit: "kg" });
  assert.match(html, /<button type="button" class="vara"[^>]*aria-keyshortcuts="Delete"/,
    "varuraden är inte fokuserbar, eller berättar inte att Delete tar bort den");
});
