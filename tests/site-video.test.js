// Landningssidans film, körd som kod - inte läst som text.
//
// Regeln site-video.js är skriven för står först i filen: SIDAN VÄNTAR ALDRIG
// PÅ VIDEO. Den regeln går att bryta tyst, för alla fel här ser likadana ut
// utifrån (en sida som laddar) och olika ut för besökaren (en sida utan
// innehåll). Därför körs skriptet i en liten DOM-attrapp i stället för att
// granskas med reguljära uttryck.
//
// Det som prövas är de tre vägar som kostar en besökare något:
//   1. Data Saver / prefers-reduced-motion -> stillbilder, inga hämtningar
//   2. webbläsare utan IntersectionObserver -> stillbilder, INTE osynliga rutor
//   3. normalfallet -> ingen video har src förrän den behövs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const KÄLLA = readFileSync(new URL("../frontend/site-video.js", import.meta.url), "utf8");

/** Minsta möjliga DOM: bara det site-video.js faktiskt rör. */
function kör({ reduceMotion = false, saveData = false, effectiveType = "4g",
               harObserver = true, filmKlipp = 6, heroKlipp = 2 } = {}) {
  const observerade = [];
  const element = (extra = {}) => ({
    dataset: {},
    classList: { lista: new Set(), add(k) { this.lista.add(k); }, remove(k) { this.lista.delete(k); } },
    lyssnare: {},
    addEventListener(namn, fn) { this.lyssnare[namn] = fn; },
    removeEventListener(namn) { delete this.lyssnare[namn]; },
    load() { this.laddad = true; },
    play() { this.spelade = true; return { catch() {} }; },
    pause() { this.pausad = true; },
    closest() { return { classList: { add() {} } }; },
    ...extra,
  });

  const hero = Array.from({ length: heroKlipp }, () => element());
  const film = Array.from({ length: filmKlipp }, (_, i) => element({ dataset: { filmSrc: `site/video/k${i}.mp4` } }));
  const rot = { attribut: {}, setAttribute(namn, värde) { this.attribut[namn] = värde; } };

  const fönster = {
    matchMedia: () => ({ matches: reduceMotion }),
    navigator: { connection: { saveData, effectiveType } },
    document: {
      documentElement: rot,
      hidden: false,
      querySelectorAll(väljare) {
        if (väljare === "[data-hero-clip]") return hero;
        if (väljare === "[data-film-src]") return film;
        return [];
      },
      addEventListener() {},
    },
    setInterval() { return 1; },
  };
  if (harObserver) {
    fönster.IntersectionObserver = class {
      constructor(fn) { this.fn = fn; }
      observe(el) { observerade.push(el); }
      disconnect() {}
    };
  }
  const sandlåda = { window: fönster, ...fönster, navigator: fönster.navigator, document: fönster.document };
  sandlåda.globalThis = sandlåda;
  vm.createContext(sandlåda);
  vm.runInContext(KÄLLA, sandlåda);
  return { rot, hero, film, observerade };
}

test("Data Saver ger stillbilder - ingen video hämtas alls", () => {
  const { rot, hero, film } = kör({ saveData: true });
  assert.equal(rot.attribut["data-video"], "still");
  assert.ok([...hero, ...film].every(v => !v.laddad), "ett klipp hämtades trots Data Saver");
});

test("prefers-reduced-motion ger stillbilder", () => {
  const { rot, film } = kör({ reduceMotion: true });
  assert.equal(rot.attribut["data-video"], "still");
  assert.ok(film.every(v => !v.laddad));
});

test("2g räknas som stillbilder även om besökaren inte bett om det", () => {
  assert.equal(kör({ effectiveType: "slow-2g" }).rot.attribut["data-video"], "still");
  assert.equal(kör({ effectiveType: "2g" }).rot.attribut["data-video"], "still");
});

test("utan IntersectionObserver lämnas scenerna SYNLIGA, inte osynliga", () => {
  // Avslöjningsanimationen döljer varje scen tills observatören säger att den
  // är på skärmen. Utan observatör finns ingen som säger det - står "motion"
  // kvar får besökaren sju osynliga rutor i stället för sju stillbilder.
  const { rot, film } = kör({ harObserver: false });
  assert.equal(rot.attribut["data-video"], "still",
    'skriptet lämnade kvar data-video="motion" utan en observatör att ta bort döljandet');
  assert.ok(film.every(v => !v.laddad), "sex klipp hämtades på en gång");
});

test("normalfallet: hjälten börjar med ETT klipp, presentationen med noll", () => {
  const { rot, hero, film, observerade } = kör();
  assert.equal(rot.attribut["data-video"], "motion");
  assert.equal(hero[0].laddad, true, "hjältens första klipp startade inte");
  assert.equal(hero[1].laddad, undefined, "hjältens andra klipp hämtades innan det första spelade");
  assert.ok(film.every(v => !v.laddad), "en scen hämtades innan den var på skärmen");
  assert.equal(observerade.length, film.length, "alla scener observeras inte");
});

test("hjältens andra klipp hämtas först när det första faktiskt spelar", () => {
  const { hero } = kör();
  assert.equal(typeof hero[0].lyssnare.playing, "function");
  hero[0].lyssnare.playing();
  assert.equal(hero[1].laddad, true);
});

test("en sida utan klipp kraschar inte skriptet", () => {
  const { rot } = kör({ filmKlipp: 0, heroKlipp: 0 });
  assert.equal(rot.attribut["data-video"], "motion");
});
