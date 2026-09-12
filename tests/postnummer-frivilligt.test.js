// G9:s acceptanskriterium: postnumret är ett frivilligt steg, inte en grind.
//
// `/^\d{5}$/` krävdes för att passera steg 4 av 4 i onboardingen. Ett
// integritetsmotstånd precis före det ögonblick då appen för första gången
// levererar något: den som inte ville lämna sin adress kom aldrig till en
// enda måltid. Och "Hitta mig" bredvid fältet svalde ALLA fel tyst - nekad
// platsdelning gav ingen text alls, och en webbläsare utan geolocation gjorde
// knappen till en död yta. Grind plus återvändsgränd, i samma steg.
//
// FALLBACK_BRANCH bär redan hela vägen utan postnummer (riksgemensamma
// Willys-priser). Det som saknades var att säga det, inte att kunna det.
//
// Att veckan verkligen blir till utan postnummer prövas i webbläsaren:
// test_postnumret_ar_inte_en_grind_fore_forsta_veckan.

import assert from "node:assert/strict";
import test from "node:test";
import { läsFil } from "./fixtures/css-parser.mjs";
import { initAppState, state } from "../frontend/app/src/state/app-state.js";

// src/api/config.js läser <meta name="matjakt-api-url"> vid import, alltså
// innan någon funktion körts. Kedjan account.js -> auth.js -> config.js drar
// därför in ett `document`-beroende som inte har med kontovyn att göra. Ett
// minimalt document räcker; importen måste vara dynamisk för att globalen ska
// hinna finnas när modulen läses.
globalThis.document ??= { querySelector: () => null };
const { initAccountView, renderPostcodePrompt } =
  await import("../frontend/app/src/views/account.js");

const html = läsFil("frontend/app/index.html");
const app = läsFil("frontend/app/app.js");
const konto = läsFil("frontend/app/src/views/account.js");

// ---------------------------------------------------------------------------
// GRINDEN
// ---------------------------------------------------------------------------

test("onboardingen vägrar inte längre ett tomt postnummer", () => {
  // Den gamla raden: if (!/^\d{5}$/.test(state.postnummer)) { ...; return; }
  // Ett `return` på ett tomt postnummer är grinden, oavsett hur den stavas.
  const avbryter = /!\/\^\\d\{5\}\\?\$\/\.test\(state\.postnummer\)[^\n]*return/.test(konto);
  assert.ok(!avbryter,
    "onboardingen avbryter fortfarande på ett postnummer som inte är fem siffror.\n" +
    "Det är en hård grind före det första värde appen levererar.");
});

test("ett halvskrivet postnummer släpps igenom vid andra försöket", () => {
  // Skillnaden mellan ATT AVSTÅ och ATT AVBRYTA: tomt fält går igenom direkt,
  // "123" får en rad om att det saknas siffror - en gång, inte varje gång.
  assert.match(konto, /const halvskrivet = state\.postnummer && !\/\^\\d\{5\}\\?\$\/\.test\(state\.postnummer\)/,
    "skillnaden mellan tomt och halvskrivet postnummer görs inte längre");
  assert.match(konto, /halvskrivet && !postcodeNoticeShown/,
    "raden om det halvskrivna postnumret spärrar mer än en gång");
});

test("veckan byggs samma väg oavsett om postnumret fylldes i", () => {
  assert.match(konto, /function finishOnboarding\(\)[\s\S]{0,400}app\.chooseMenu\(\)/,
    "onboardingen har ingen gemensam avslutning som bygger veckan");
  assert.match(konto, /\$\("obSkipPostcode"\)\?\.addEventListener\("click", \(\) => finishOnboarding\(\)\)/,
    "att hoppa över postnumret tar inte samma väg som att fylla i det");
});

// ---------------------------------------------------------------------------
// ERBJUDANDET
// ---------------------------------------------------------------------------

test("steget erbjuder att hoppa över, med vad man avstår", () => {
  assert.match(konto, /id="obSkipPostcode">Hoppa över &ndash; vi visar riksgemensamma priser tills vidare</,
    "knappen som hoppar över postnumret saknas eller säger inte vad man avstår");
  assert.match(konto, /Postnummer \(frivilligt\)/, "fältet är inte märkt som frivilligt");
  assert.match(konto, /id="obPostcodeHint"[^>]*>[^<]*riksgemensamma priser/,
    "raden under fältet säger inte vad som händer utan postnummer");
});

// ---------------------------------------------------------------------------
// ÅTERVÄNDSGRÄNDEN
// ---------------------------------------------------------------------------

test('"Hitta mig" är tyst på inget fel längre', () => {
  // Två knappar, samma tystnad: onboardingens #obLocateBtn och veckoarkets
  // #locateBtn. Båda gjorde INGENTING utan geolocation, och onboardingens
  // svalde dessutom ett nej från användaren i en tom pilfunktion.
  assert.ok(!/if \(!navigator\.geolocation\) return;/.test(konto + app),
    "en Hitta mig-knapp gör fortfarande ingenting alls utan geolocation");
  assert.ok(!/getCurrentPosition\([^;]*, \(\) => \{\}\)/.test(konto),
    "onboardingens Hitta mig sväljer fortfarande ett nej i en tom funktion");
  for (const [namn, källa] of [["onboardingen", konto], ["veckoarket", app]]) {
    assert.match(källa, /kan inte dela din plats/,
      `${namn}: ingen text när webbläsaren saknar geolocation`);
    assert.match(källa, /Vi fick inte din plats/,
      `${namn}: ingen text när platsdelningen nekas`);
  }
});

// ---------------------------------------------------------------------------
// FRÅGAN FLYTTAD TILL HANDLA
// ---------------------------------------------------------------------------

test("Handla har raden som frågar om postnummer", () => {
  assert.match(html, /id="basketPostcodePrompt"[^>]*hidden>[^<]*Ange postnummer/,
    "raden i Handla saknas");
  assert.match(konto, /app\.openWeekSheet\(\)/,
    "raden i Handla leder inte till fältet");
  assert.match(app, /\["basket", renderPostcodePrompt\]/,
    "raden ritas aldrig om, så den ligger kvar när postnumret väl fyllts i");
});

test("raden syns bara när postnumret saknas", () => {
  // Den enda riktiga beteendeprövningen som går utan webbläsare: funktionen
  // tar emot ett tillstånd och sätter hidden. Nod: en knapp som bara har det
  // renderPostcodePrompt rör vid.
  const rad = { hidden: false, dataset: {}, addEventListener() {} };
  initAppState({ storage: null, recipeBank: [] });
  initAccountView({ $: (id) => (id === "basketPostcodePrompt" ? rad : null) });

  state.postnummer = "";
  renderPostcodePrompt();
  assert.equal(rad.hidden, false, "raden göms trots att postnumret saknas");

  state.postnummer = "802";
  renderPostcodePrompt();
  assert.equal(rad.hidden, false, "ett halvskrivet postnummer räknades som ifyllt");

  state.postnummer = "80252";
  renderPostcodePrompt();
  assert.equal(rad.hidden, true, "raden ligger kvar när postnumret är ifyllt");
});
