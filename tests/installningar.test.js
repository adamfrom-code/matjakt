// G11:s acceptanskriterium: skärmen finns, och den har rätt saker i sig.
//
// Kost och allergier - det mest säkerhetskritiska i hela appen - bodde i ett
// bottenark bakom ett OMÄRKT "＋" på 28×28 px i hörnet av veckokortet. Konto,
// hushåll, lösenord, prenumeration och radera konto låg i ett enda långt
// modalt scroll. Det fanns ingen skärm som hette Inställningar, och därför
// ingen plats där man kunde SE vad man hade svarat.
//
// Åtta grupper står i uppdraget: Hushåll & personer · Kost och allergier ·
// Budget · Butik & plats · Konto · Prenumeration · Notiser · Integritet.
//
// Skärmen byggs av src/views/settings.js ur tillståndet, så det mesta går att
// pröva på riktigt: sätt ett läge, rendera, läs raderna. Det som kräver en
// webbläsare - att skärmen faktiskt VISAS och att raderna leder någonstans -
// prövas i test_installningarna_ar_en_skarm_med_allergierna_markta.

import assert from "node:assert/strict";
import test from "node:test";
import { läsFil } from "./fixtures/css-parser.mjs";
import { initAppState, state } from "../frontend/app/src/state/app-state.js";
import { dietSummary, settingsMarkup } from "../frontend/app/src/views/settings.js";

const html = läsFil("frontend/app/index.html");
const css = läsFil("frontend/app/styles.css");
const app = läsFil("frontend/app/app.js");

const GRUPPER = ["Hushåll & personer", "Kost och allergier", "Budget",
                 "Butik & plats", "Konto", "Prenumeration", "Notiser", "Integritet"];

function rita(läge = {}) {
  initAppState({ storage: null, recipeBank: [] });
  Object.assign(state, läge);
  return settingsMarkup();
}

const avEscapad = (text) => text.replace(/&amp;/g, "&").replace(/&ndash;/g, "\u2013");

/** Raden med den etiketten: id, värde och märke var för sig. */
function rad(markup, etikett) {
  // Markupen delas per knapp först. Ett svep över hela strängen hade kunnat
  // börja i en knapp och sluta i en annan, och då mäter testet fel rad.
  const bit = markup.split("</button>")
    .find((del) => del.includes(`<span class="settings-row-label">${etikett}</span>`));
  if (!bit) return null;
  return {
    id: /data-settings="([^"]+)"/.exec(bit)?.[1] ?? "",
    värde: avEscapad(/<span class="settings-row-value">([^<]*)</.exec(bit)?.[1] ?? ""),
    märke: avEscapad(/<span class="settings-row-flag">([^<]*)</.exec(bit)?.[1] ?? ""),
    markerad: /class="settings-row marked"/.test(bit),
  };
}

// ---------------------------------------------------------------------------
// SKÄRMEN FINNS
// ---------------------------------------------------------------------------

test("det finns en skärm som heter Inställningar", () => {
  assert.match(html, /<section class="screen settings-screen"/, "skärmen saknas i index.html");
  assert.match(html, /<h1 id="settingsTitle">Inställningar<\/h1>/);
  assert.match(css, /\.view-settings \.settings-screen\{display:block\}/,
    "skärmen kan aldrig visas - ingen regel tänder den");
});

test("profilknappen leder dit den säger att den leder", () => {
  // Knappens aria-label sa "Öppna profil och inställningar" redan förut. Den
  // öppnade kontoarket.
  assert.match(html, /id="profileBtn" aria-label="Öppna profil och inställningar"/);
  assert.ok(!/\$\("profileBtn"\)\.addEventListener\("click", openAccountModal\)/.test(app),
    "profilknappen öppnar fortfarande kontoarket direkt");
  const settings = läsFil("frontend/app/src/views/settings.js");
  assert.match(settings, /app\.setView\("settings"\)/, "ingenting byter till skärmen");
});

test("skärmen går att lämna med en tillbakaknapp", () => {
  assert.match(html, /settings-screen[\s\S]{0,400}class="back-link" type="button" data-view="home"/);
});

// ---------------------------------------------------------------------------
// ...MED RÄTT ÅTTA GRUPPER
// ---------------------------------------------------------------------------

test("alla åtta grupper ur uppdraget finns, i ordning", () => {
  const markup = rita();
  const funna = [...markup.matchAll(/<h2 class="settings-group-title">([^<]+)<\/h2>/g)]
    .map(m => avEscapad(m[1]));
  assert.deepEqual(funna, GRUPPER);
});

test("varje rad leder någonstans", () => {
  const markup = rita();
  const ids = [...markup.matchAll(/data-settings="([^"]+)"/g)].map(m => m[1]);
  assert.ok(ids.length >= GRUPPER.length, `bara ${ids.length} rader för ${GRUPPER.length} grupper`);
  const settings = läsFil("frontend/app/src/views/settings.js");
  for (const id of ids) {
    assert.match(settings, new RegExp(`\\n  ${id}: `), `raden ${id} har inget mål`);
  }
});

// ---------------------------------------------------------------------------
// ALLERGIRADEN
// ---------------------------------------------------------------------------

test("allergiraden märks när den är tom", () => {
  const markup = rita({ kost: { kosttyp: "", avoidAllergens: new Set() } });
  const r = rad(markup, "Allergier och specialkost");
  assert.ok(r, "allergiraden finns inte");
  assert.equal(r.värde, "Inga angivna");
  assert.equal(r.märke, "Ej ifyllt",
    "en tom allergirad ser likadan ut som en ifylld.\n" +
    "Det är appens mest säkerhetskritiska inställning: 'inga angivna' får\n" +
    "inte gå att förväxla med 'inget att visa'.");
  assert.equal(r.markerad, true);
});

test("allergiraden visar vad som faktiskt är ifyllt", () => {
  const markup = rita({ kost: { kosttyp: "vegetariskt", avoidAllergens: new Set(["nötter"]) } });
  const r = rad(markup, "Allergier och specialkost");
  assert.equal(r.värde, "Vegetariskt · Nötter");
  assert.equal(r.märke, "", "en ifylld rad märks som tom");
});

test("allergiraden räknar med hushållets allergier, inte bara enhetens", () => {
  // Veckoplaneraren filtrerar på BÅDA (mergeDiet). Läste raden bara
  // state.kost kunde den säga "Inga angivna" medan veckan faktiskt
  // filtrerades på någon annans nötallergi - en halv sanning i exakt den rad
  // som inte får bära en.
  const sammanfattning = dietSummary(
    { kosttyp: "", avoidAllergens: new Set() },
    { members: [{ profile: { allergies: ["skaldjur"] } }] });
  assert.equal(sammanfattning.tom, false, "hushållets allergi syns inte i raden");
  assert.match(sammanfattning.text, /Skaldjur/);
});

// ---------------------------------------------------------------------------
// VÄRDENA
// ---------------------------------------------------------------------------

test("raderna visar tillståndet, inte platshållare", () => {
  const markup = rita({
    budget: 950, middagar: 5, personer: 4,
    hushall: { vuxna: 2, barn: 2 },
    butik: "Hemköp", postnummer: "80252",
  });
  assert.equal(rad(markup, "Veckobudget").värde, "950 kr/vecka");
  assert.equal(rad(markup, "Middagar per vecka").värde, "5 middagar");
  assert.equal(rad(markup, "Antal personer").värde, "2 vuxna + 2 barn");
  assert.equal(rad(markup, "Butik").värde, "Hemköp");
  assert.equal(rad(markup, "Postnummer").värde, "80252");
});

test("det som saknas står som det som saknas", () => {
  const markup = rita({ butik: "auto", postnummer: "", user: null });
  assert.equal(rad(markup, "Postnummer").värde, "Inte angivet");
  assert.equal(rad(markup, "Butik").värde, "Billigast automatiskt");
  assert.equal(rad(markup, "Inloggad som").värde, "Inte inloggad");
  assert.equal(rad(markup, "Delas med").värde, "Inte delat");
});

test("skärmen ritas om när kontot eller hushållet ändras", () => {
  // Annars står ett gammalt värde kvar och ljuger tills någon byter flik.
  assert.match(app, /\["account", renderSettings\]/,
    "renderSettings står inte i renderingsbussen");
});
