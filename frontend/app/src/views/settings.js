// Inställningar — skärmen appen inte hade.
//
// G11: kost och allergier, det mest säkerhetskritiska i hela appen, bodde i
// ett bottenark bakom ett OMÄRKT "＋" på 28×28 px i hörnet av veckokortet.
// Konto, hushåll, lösenord, prenumeration och radera konto låg i ett enda
// långt modalt scroll. Det fanns ingen skärm som hette Inställningar, och
// därför ingen plats där man kunde SE vad man hade svarat.
//
// Den här modulen bygger skärmen: åtta grupper, en rad per inställning,
// värdet till höger. Raden är en genväg till den yta där inställningen
// faktiskt bor - veckoarket eller kontoarket - så ingen logik dupliceras och
// inget värde kan börja ljuga för att det står på två ställen.
//
// Allergiraden märks särskilt när den är tom. Det är appens mest
// säkerhetskritiska inställning, och "Inga angivna" ska inte gå att förväxla
// med "inget att visa".
//
// L6 bygger om skärmen efter design D (telefon 7). Det här paketet gör att
// den FINNS, med rätt innehåll i rätt grupper.

import { escapeHtml } from "../utils/html.js";
import { state } from "../state/app-state.js";
import { mergeDiet } from "../services/diet.js";
import { householdDietary } from "../services/household-state.js";

let app = {
  $: () => null,
  householdActive: () => false,
  hasPremium: () => false,
  openWeekSheet: () => {},
  openAccountModal: () => {},
  openPaywall: () => {},
  setView: () => {},
  plural: (n, one, many) => `${n} ${n === 1 ? one : many}`,
  money: (n) => `${n} kr`,
  trackEvent: () => {},
};

const $ = id => app.$(id);

export function initSettingsView(overrides = {}) {
  app = { ...app, ...overrides };
  wireSettings();
  renderSettings();
}

const KOSTTYP_ETIKETT = { vegetariskt: "Vegetariskt", veganskt: "Veganskt" };

/**
 * Kost och allergier, sammanfattat i en rad.
 *
 * Läser BÅDA källorna - enhetens egen kost och hushållets allergier - genom
 * samma mergeDiet() som veckoplaneraren använder. Skulle raden bara läsa
 * state.kost kunde den säga "Inga angivna" medan veckan faktiskt filtrerades
 * på hushållets nötallergi, och det är precis den sortens halva sanning som
 * inte får finnas i just den här raden.
 */
export function dietSummary(kost = state.kost, household = state.household) {
  // EXAKT samma två källor som activeDiet() i app.js slår ihop innan veckan
  // planeras. Läser raden något annat kan den säga "Inga angivna" om en vecka
  // som faktiskt filtrerats.
  const merged = mergeDiet(kost, householdDietary(household || {}));
  const delar = [];
  if (merged.kosttyp) delar.push(KOSTTYP_ETIKETT[merged.kosttyp] || merged.kosttyp);
  const allergener = [...merged.avoidAllergens].filter(Boolean);
  if (allergener.length) {
    delar.push(allergener.map(a => a[0].toUpperCase() + a.slice(1)).join(", "));
  }
  return { text: delar.join(" · "), tom: delar.length === 0 };
}

function husholdVärde() {
  if (app.householdActive()) return state.household?.name || "Delat";
  return "Inte delat";
}

function personerVärde() {
  const vuxna = state.hushall?.vuxna ?? 0;
  const barn = state.hushall?.barn ?? 0;
  if (!vuxna && !barn) return app.plural(state.personer, "person", "personer");
  const delar = [app.plural(vuxna, "vuxen", "vuxna")];
  if (barn) delar.push(app.plural(barn, "barn", "barn"));
  return delar.join(" + ");
}

function butikVärde() {
  if (state.butik === "auto" || !state.butik) return "Billigast automatiskt";
  if (state.butik === "alla") return "Alla butiker";
  return state.butik;
}

function planVärde() {
  if (app.hasPremium()) return "Premium";
  return state.user ? "Gratis" : "Gratis (inget konto)";
}

/** En rad: etikett, eventuell underrad, värde till höger. */
function rad({ id, etikett, note = "", värde, markerad = false, märke = "" }) {
  return `<button type="button" class="settings-row${markerad ? " marked" : ""}" data-settings="${escapeHtml(id)}">
    <span class="settings-row-text">
      <span class="settings-row-label">${escapeHtml(etikett)}</span>
      ${note ? `<span class="settings-row-note">${escapeHtml(note)}</span>` : ""}
      ${märke ? `<span class="settings-row-flag">${escapeHtml(märke)}</span>` : ""}
    </span>
    <span class="settings-row-value">${escapeHtml(värde)}</span>
  </button>`;
}

function grupp(titel, rader) {
  return `<h2 class="settings-group-title">${escapeHtml(titel)}</h2>${rader.join("")}`;
}

export function settingsMarkup() {
  const kost = dietSummary();
  return [
    grupp("Hushåll & personer", [
      rad({ id: "personer", etikett: "Antal personer", värde: personerVärde() }),
      rad({ id: "hushall", etikett: "Delas med",
            note: "Samma vecka, lista och skafferi hos er båda.",
            värde: husholdVärde() }),
    ]),
    // ALLERGIRADEN STÅR FÖRST BLAND VALEN och märks när den är tom. Den bodde
    // bakom ett omärkt plustecken på 28x28 px; att bara flytta den hit utan
    // att säga att den är tom vore att byta ett gömställe mot ett annat.
    grupp("Kost och allergier", [
      rad({ id: "kost", etikett: "Allergier och specialkost",
            note: "Recepten filtreras först när du fyllt i.",
            märke: kost.tom ? "Ej ifyllt" : "",
            markerad: kost.tom,
            värde: kost.tom ? "Inga angivna" : kost.text }),
    ]),
    grupp("Budget", [
      rad({ id: "budget", etikett: "Veckobudget", värde: `${app.money(state.budget)}/vecka` }),
      rad({ id: "middagar", etikett: "Middagar per vecka",
            värde: app.plural(state.middagar, "middag", "middagar") }),
    ]),
    grupp("Butik & plats", [
      rad({ id: "butik", etikett: "Butik", note: "Priserna hämtas härifrån.",
            värde: butikVärde() }),
      rad({ id: "postnummer", etikett: "Postnummer",
            note: state.postnummer ? "" : "Utan postnummer visar vi riksgemensamma priser.",
            värde: state.postnummer || "Inte angivet" }),
    ]),
    grupp("Konto", [
      rad({ id: "konto", etikett: "Inloggad som",
            värde: state.user?.email || "Inte inloggad" }),
    ]),
    grupp("Prenumeration", [
      rad({ id: "prenumeration", etikett: "Plan",
            note: app.hasPremium() ? "" : "Se vad Premium innehåller.",
            värde: planVärde() }),
    ]),
    grupp("Notiser", [
      rad({ id: "notiser", etikett: "Notiser",
            note: "Vad ni får besked om när någon i hushållet ändrar något.",
            värde: app.householdActive() ? "Hantera" : "Kräver hushåll" }),
    ]),
    grupp("Integritet", [
      rad({ id: "integritet", etikett: "Integritet och data",
            note: "Policy, villkor och att radera kontot.",
            värde: "Hantera" }),
    ]),
  ].join("");
}

// Vart varje rad leder. Inställningen BOR kvar där den bor - veckoarket eller
// kontoarket - och raden är genvägen dit. Att kopiera fälten hit hade gett
// två ställen att ändra samma sak på, och därmed två svar på samma fråga.
const MÅL = {
  personer: () => app.openWeekSheet(),
  budget: () => app.openWeekSheet(),
  middagar: () => app.openWeekSheet(),
  butik: () => app.openWeekSheet(),
  postnummer: () => { app.openWeekSheet(); $("postcodeInput")?.focus(); },
  kost: () => { app.openWeekSheet(); $("kosttypInput")?.scrollIntoView({ block: "center" }); },
  hushall: () => app.openAccountModal("householdPanel"),
  konto: () => app.openAccountModal(),
  prenumeration: () => (app.hasPremium() ? app.openAccountModal("subscriptionPanel") : app.openPaywall("settings")),
  notiser: () => app.openAccountModal("householdPanel"),
  integritet: () => app.openAccountModal("accountLegal"),
};

export function renderSettings() {
  const box = $("settingsGroups");
  if (!box) return;
  box.innerHTML = settingsMarkup();
  box.querySelectorAll("[data-settings]").forEach(button =>
    button.addEventListener("click", () => {
      app.trackEvent(`installning_${button.dataset.settings}`);
      MÅL[button.dataset.settings]?.();
    }));
}

function wireSettings() {
  const knapp = $("profileBtn");
  if (!knapp || knapp.dataset.settingsWired) return;
  knapp.dataset.settingsWired = "1";
  // Knappen hette redan "Öppna profil och inställningar" i sin aria-label.
  // Den öppnade kontoarket. Nu leder den dit den sa att den ledde.
  knapp.addEventListener("click", () => { renderSettings(); app.setView("settings"); });
}
