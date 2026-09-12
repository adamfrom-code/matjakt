// ---------------------------------------------------------------------------
// KONTOT, HUSHÅLLET, ONBOARDINGEN OCH BETALVÄGGEN
//
// Allt som rör vem användaren är och vad hon har betalat för: kontoarket,
// "Mitt hushåll", notisvalen, de fyra onboardingstegen och paywallen med
// Stripe-vägen. Låg tidigare utspritt över fyra ställen i app.js med
// swap-modalen och planjämförelsen emellan.
//
// Modulen ritar och binder DOM, men känner varken till prissättningen,
// receptbanken eller vyerna. Det den behöver av app.js skickas in EN gång i
// initAccountView() - samma mönster som src/state/app-state.js, och det som
// gör att den här filen kan läsas utan att app.js ligger uppslagen bredvid.
// ---------------------------------------------------------------------------

import { flushServerSync, saveState, state } from "../state/app-state.js";
import { createHousehold, createInvite, leaveHousehold, removeMember, saveHouseholdProfile, saveNotificationPrefs } from "../api/household.js";
import { applySync, emptyHouseholdState } from "../services/household-state.js";
import { getStoredToken, startCheckout } from "../api/auth.js";
import { clampBudget } from "../services/calculations.js";
import { ALLERGENS } from "../services/diet.js";
import { escapeHtml } from "../utils/html.js";
// L7: betalväggens belopp ritas av samma modul som kontoarkets, och varje
// siffra går genom L0:s prisMarkup(). Betalväggen hade egna strängar med
// `priceText` som reserv - två skärmar som formaterar samma pris var för sig
// är två skärmar som kan börja säga olika saker om det.
import { paywallPlanMarkup, planetikett } from "./premiumskarmen.js";
import { closeModal, openModal } from "../utils/modal.js";
// errorText: inget rått fetch-fel når skärmen. "Failed to fetch" är inte
// svenska, och en användare kan inte göra något åt ett "HTTP 500" (E7).
import { errorText } from "../api/http.js";

// Det modulen behöver av app.js. Namnen är app.js egna - en omdöpning här
// hade bara gjort det svårare att hitta tillbaka.
let app = {
  $: () => null,
  hasPremium: () => false,
  premiumPricing: () => ({}),
  withdrawalConsentMarkup: () => "",
  withdrawalConsentGiven: () => false,
  syncSettingsInputs: () => {},
  renderPriceTabs: () => {},
  householdActive: () => false,
  pullHousehold: () => Promise.resolve(),
  pushWeekToHousehold: () => {},
  pushPantryToHousehold: () => {},
  startHouseholdSync: () => {},
  resetWeekPushKey: () => {},
  loadNotifications: () => {},
  clearInviteFromUrl: () => {},
  openAccountModal: () => {},
  openPlanComparison: () => {},
  chooseMenu: () => {},
  setView: () => {},
  syncNearbyBranches: () => {},
  clearLocationDerivedState: () => {},
  openWeekSheet: () => {},
  storeOptionsMarkup: () => "",
  budgetScopeText: () => "",
  maxDinners: () => 4,
  maxMeals: () => 7,
  isNativeApp: () => false,
  openExternal: () => {},
  plural: (n, one, many) => `${n} ${n === 1 ? one : many}`,
  render: () => {},
  trackEvent: () => {},
};

export function initAccountView(overrides = {}) {
  app = { ...app, ...overrides };
  wireOnboardingButtons();
  wireWeekPlanUpsell();
  wireHouseholdInvitePrompt();
  wirePostcodePrompt();
  // Hushållsraden hör inte till en inloggning: den som aldrig skapat ett
  // konto är precis den som ska se den. Den ritas därför redan här, inte
  // först när refreshUser() hunnit svara.
  renderHouseholdInvitePrompt();
  renderPostcodePrompt();
}

// Postnummerraden ritas om varje gång skärmarna ritas om (render() i app.js),
// så den försvinner i samma stund som postnumret fyllts i - oavsett var det
// fylldes i.
export { renderPostcodePrompt };

const $ = id => app.$(id);

// ---------------------------------------------------------------------------
// MITT HUSHÅLL (Konto → Hushåll)
//
// Flödet är avsiktligt tre steg och inte fler (§1):
//   skriv namnet → Bjud in → skicka länken.
// Ingen kod att läsa upp, ingen inställningssida att gå igenom först.
// ---------------------------------------------------------------------------

export const NOTIFY_LABELS = {
  week: "Ny vecka",
  shopping: "Ändringar i inköpslistan",
  plan: "Ändringar i veckoplaneringen",
  inventory: "Skafferi, kyl och frys",
  price: "Prisbevakningar",
};

export function renderHousehold() {
  // G13: hushållsraden i Handla hänger på precis samma fråga som panelen
  // nedan - finns det ett hushåll? - och ritas därför härifrån.
  renderHouseholdInvitePrompt();
  const panel = $("householdPanel");
  if (!panel) return;
  // Hushållet kräver ett konto - det är där medlemskapet bor.
  panel.hidden = !state.authToken;
  if (!state.authToken) return;
  const active = app.householdActive();
  $("householdNone").hidden = active;
  $("householdCurrent").hidden = !active;
  if (!active) return;
  $("householdNameLabel").textContent = state.household.name;
  const me = state.household.members.find(member => member.isMe);
  const isAdmin = state.household.role === "admin";
  $("householdMembers").innerHTML = state.household.members.map(member => {
    const name = member.displayName || (member.email ? member.email.split("@")[0] : "Medlem");
    const tags = [member.role === "admin" ? "administratör" : "", member.isMe ? "du" : ""].filter(Boolean).join(" · ");
    const remove = isAdmin && !member.isMe
      ? `<button type="button" class="household-remove" data-remove-member="${escapeHtml(String(member.userId))}" aria-label="Ta bort ${escapeHtml(name)}">Ta bort</button>` : "";
    return `<li><span><strong>${escapeHtml(name)}</strong>${tags ? `<small>${escapeHtml(tags)}</small>` : ""}</span>${remove}</li>`;
  }).join("");
  $("householdMembers").querySelectorAll("[data-remove-member]").forEach(button => button.addEventListener("click", () => {
    const userId = Number(button.dataset.removeMember);
    removeMember(state.authToken, userId)
      .then(({ household }) => { state.household = applySync(state.household, { household, revision: state.household.revision }); state.household.members = household.members; renderHousehold(); })
      .catch(error => { $("householdInviteError").textContent = errorText(error); });
  }));
  // Bara administratören kan bjuda in - samma regel som servern håller.
  $("householdInviteBtn").hidden = !isAdmin;
  if (me) {
    $("householdDisplayName").value = me.displayName || "";
    $("householdSpice").value = me.profile?.spice || "";
    $("householdDiet").value = me.profile?.diet || "";
    $("householdAllergies").value = (me.profile?.allergies || []).join(", ");
  }
  renderNotificationPrefs();
}

// G13: HUSHÅLLET ÄR APPENS STARKASTE VIRALA KANAL och marknadsfördes inte en
// enda gång. Vägen till en delad lista var sju-åtta steg som ingen föreslog:
// kontoknappen uppe i hörnet, scrolla, skapa hushåll, bjud in, skicka länken.
//
// Raden står överst i Handla när inget hushåll finns - alltså för den som
// står i butiken och just då har någon hemma som kunde bockat av varor.
// Utloggad leder den till kontoarket (där kontot skapas), inloggad rakt till
// hushållspanelen.
function renderHouseholdInvitePrompt() {
  const row = $("basketHouseholdInvite");
  if (!row) return;
  row.hidden = app.householdActive();
}

// G9: FRÅGAN OM POSTNUMMER FLYTTADE HIT.
//
// Den stod som steg 4 av 4 i onboardingen och krävde fem siffror för att
// släppa igenom - ett integritetsmotstånd precis före det ögonblick då appen
// för första gången levererar något. Här är den i stället ett erbjudande med
// ett tydligt värde: priserna du ser blir din butiks i stället för
// riksgemensamma. Raden syns bara när postnumret saknas.
function renderPostcodePrompt() {
  const row = $("basketPostcodePrompt");
  if (!row) return;
  row.hidden = /^\d{5}$/.test(state.postnummer || "");
}

function wirePostcodePrompt() {
  const row = $("basketPostcodePrompt");
  if (!row || row.dataset.wired) return;
  row.dataset.wired = "1";
  row.addEventListener("click", () => {
    app.trackEvent("postnummer_fran_handla");
    app.openWeekSheet();
    $("postcodeInput")?.focus();
  });
}

function wireHouseholdInvitePrompt() {
  const row = $("basketHouseholdInvite");
  if (!row || row.dataset.wired) return;
  row.dataset.wired = "1";
  row.addEventListener("click", () => {
    app.trackEvent("hushall_fran_handla");
    app.openAccountModal();
    // Kontoarket är långt; hushållet ligger långt ner i det. Att öppna det
    // på rätt ställe är skillnaden mellan ett förslag och en uppmaning.
    $("householdPanel")?.scrollIntoView({ block: "start", behavior: "smooth" });
  });
}

export function renderNotificationPrefs() {
  const list = $("householdNotifyList");
  if (!list || !state.notisInstallningar) return;
  const prefs = state.notisInstallningar;
  const rows = Object.entries(NOTIFY_LABELS).map(([key, label]) =>
    `<label class="household-notify-row"><span>${label}</span><input type="checkbox" data-notify-pref="${key}" ${prefs[key] === false ? "" : "checked"}></label>`).join("");
  list.innerHTML = `<label class="household-notify-row main"><span>Alla notiser</span><input type="checkbox" data-notify-pref="all" ${prefs.all === false ? "" : "checked"}></label>${rows}`;
  list.querySelectorAll("[data-notify-pref]").forEach(input => input.addEventListener("change", () => {
    const pref = input.dataset.notifyPref;
    const next = { ...prefs, [pref]: input.checked };
    state.notisInstallningar = next;
    saveNotificationPrefs(state.authToken, next)
      .then(({ preferences }) => {
        state.notisInstallningar = preferences;
        // H1: "Ny vecka" är brytaren för söndagsnotisen, och det HÄR är det
        // enda stället i appen där tillståndsdialogen får visas - den kom ur
        // ett tryck. Att slå av den säger upp prenumerationen; att slå på den
        // frågar en gång. Ett nej frågas aldrig om igen (weekly-push.js).
        if (pref === "week" || pref === "all") app.syncWeeklyNotification?.({ prompt: input.checked });
      })
      .catch(() => { /* nästa ändring försöker igen */ });
  }));
}

export function wireHouseholdUi() {
  $("householdCreateForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    $("householdCreateError").textContent = "";
    try {
      const { household } = await createHousehold(state.authToken, $("householdNameInput").value);
      state.household = applySync(emptyHouseholdState(), { household, revision: 0 });
      await app.pullHousehold(true);
      // Veckan som redan finns på den här enheten blir familjens första vecka.
      app.resetWeekPushKey();
      app.pushWeekToHousehold();
      app.pushPantryToHousehold();
      app.startHouseholdSync();
      renderHousehold();
      app.loadNotifications();
      app.render();
    } catch (error) {
      $("householdCreateError").textContent = errorText(error);
    }
  });

  $("householdInviteBtn")?.addEventListener("click", async () => {
    $("householdInviteError").textContent = "";
    try {
      const invite = await createInvite(state.authToken);
      $("householdInviteBox").hidden = false;
      $("householdInviteLink").value = invite.url;
      // Systemets egen delningsruta när den finns: SMS, WhatsApp, Messenger -
      // alla på en gång, utan att vi bygger en egen lista över appar.
      const canShare = typeof navigator.share === "function";
      $("householdShareBtn").hidden = !canShare;
      $("householdShareBtn").onclick = () => navigator.share({ title: invite.shareTitle, text: invite.shareText, url: invite.url }).catch(() => {});
      $("householdCopyBtn").onclick = async () => {
        try {
          await navigator.clipboard.writeText(invite.url);
          $("householdCopyBtn").textContent = "Kopierad";
          setTimeout(() => { $("householdCopyBtn").textContent = "Kopiera"; }, 2000);
        } catch {
          $("householdInviteLink").select();
        }
      };
    } catch (error) {
      $("householdInviteError").textContent = errorText(error);
    }
  });

  $("householdProfileForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    $("householdProfileError").textContent = "";
    try {
      const { household } = await saveHouseholdProfile(state.authToken, {
        displayName: $("householdDisplayName").value,
        profile: {
          spice: $("householdSpice").value || undefined,
          diet: $("householdDiet").value || undefined,
          allergies: $("householdAllergies").value.split(",").map(value => value.trim()).filter(Boolean),
        },
      });
      state.household = applySync(state.household, { household, revision: state.household.revision });
      state.household.members = household.members;
      renderHousehold();
    } catch (error) {
      $("householdProfileError").textContent = errorText(error);
    }
  });

  $("householdLeaveBtn")?.addEventListener("click", async () => {
    if (!confirm(`Lämna ${state.household.name}? Den gemensamma veckan, listan och skafferiet stannar hos de andra.`)) return;
    try {
      await leaveHousehold(state.authToken);
    } catch { /* redan ute, eller offline - lokalt läge gäller ändå */ }
    state.household = emptyHouseholdState();
    app.startHouseholdSync();
    renderHousehold();
    app.render();
  });

  $("inviteDismissBtn")?.addEventListener("click", () => { closeModal($("inviteLanding")); app.clearInviteFromUrl(); });
}

// ---------------------------------------------------------------------------
// KONTOARKET
// ---------------------------------------------------------------------------

// Sätts av app.js när användaren är på väg tillbaka från Stripe. Bor här för
// att renderAccount är den enda som visar den, och beginCheckout den enda som
// sätter den i native-flödet.
let awaitingPremiumActivation = false;
export function setAwaitingPremium(value) { awaitingPremiumActivation = Boolean(value); }
export function isAwaitingPremium() { return awaitingPremiumActivation; }

export function renderAccount() {
  const loggedIn = Boolean(state.user);
  $("accountLoggedOut").hidden = loggedIn;
  $("accountLoggedIn").hidden = !loggedIn;
  $("profileBtn").textContent = loggedIn ? state.user.email.slice(0, 2).toUpperCase() : "MJ";
  $("profileBtn").classList.toggle("is-premium", app.hasPremium());
  app.syncSettingsInputs();
  app.renderPriceTabs();
  renderHousehold();
  if (loggedIn) {
    $("accountEmail").textContent = state.user.email;
    $("verifyEmailNotice").hidden = state.user.emailVerified;
    $("marketingToggle").checked = Boolean(state.user.marketingConsent);
    // Utskick går bara till verifierade adresser - säg det, i stället för
    // att låta någon tacka ja och undra varför inget kommer.
    $("marketingNote").textContent = state.user.marketingConsent && !state.user.emailVerified
      ? "(skickas när adressen är verifierad)" : "";
    const daysLeft = state.user.trialEndsAt ? Math.max(1, Math.ceil((new Date(state.user.trialEndsAt) - Date.now()) / 86400000)) : 0;
    const hasSubscription = ["active", "trialing", "past_due", "canceled", "unpaid"].includes(state.user.subscriptionStatus);
    const pastDue = ["past_due", "unpaid", "incomplete"].includes(state.user.subscriptionStatus);
    $("accountPremiumStatus").textContent = awaitingPremiumActivation && !app.hasPremium()
      ? "Kontrollerar om betalningen gått igenom…"
      : daysLeft ? `✓ Provperiod aktiv - ${app.plural(daysLeft, "dag", "dagar")} kvar (ingen betalning krävs)`
      : state.user.premium ? "✓ Premium aktiverat"
      : pastDue ? "Premium är pausat tills betalningen gått igenom"
      : "Inget Premium ännu";
    // Köpknappen döljs bara när det FINNS något att fixa i portalen. Medan
    // vi kontrollerar en betalning står den kvar: i native-appen kan
    // användaren ha stängt betalsidan utan att betala, och då vore en
    // borttagen köpknapp en återvändsgränd. Servern nekar ändå ett andra
    // köp (409) om prenumerationen redan finns.
    $("premiumPitch").hidden = state.user.premium || pastDue;
    $("subscriptionPanel").hidden = !hasSubscription;
    if (hasSubscription) {
      const periodEnd = state.user.subscriptionPeriodEnd ? new Date(state.user.subscriptionPeriodEnd).toLocaleDateString("sv-SE") : "okänt datum";
      // Planetiketten kommer från samma källa som paywallen (backend), och
      // en okänd plan påstår ingenting om priset.
      const pricing = app.premiumPricing();
      const planLabel = planetikett(pricing, state.user.subscriptionPlan);
      let line;
      if (state.user.subscriptionStatus === "active" && state.user.subscriptionCancelAtPeriodEnd) line = `Din prenumeration (${planLabel}) är uppsagd och gäller till ${periodEnd}, sedan återgår kontot till gratisversionen.`;
      else if (state.user.subscriptionStatus === "active") line = `Din prenumeration (${planLabel}) förnyas automatiskt ${periodEnd}.`;
      else if (["past_due", "unpaid"].includes(state.user.subscriptionStatus)) line = `Senaste betalningen (${planLabel}) gick inte igenom, så Premium är pausat. Uppdatera betalmetoden under Hantera prenumeration så aktiveras det igen.`;
      else if (state.user.subscriptionStatus === "incomplete") line = `Betalningen är påbörjad men inte klar. Slutför den under Hantera prenumeration.`;
      else line = `Din prenumeration är avslutad. Prenumerera igen när du vill.`;
      $("subscriptionPanelLine").textContent = line;
    }
  }
  const premium = app.hasPremium();
  $("nutritionLocked").hidden = premium;
  $("nutritionFields").hidden = !premium;
}

// ---------------------------------------------------------------------------
// ONBOARDINGEN
// ---------------------------------------------------------------------------

// Fyra steg, inte sju. En förstagångare ska svara på det Matjakt inte kan
// gissa - vilka ni är, vad ni vill lägga, vad ni inte äter, var ni handlar -
// och sedan SE sin vecka. Tidsfiltret bor i Recept-fliken, "något ni hellre
// slipper" och kalorier/makron i "Justera veckan"; mitt i onboardingen var de
// bara friktion (och ett Premium-formulär för någon som inte ens sett appen).
const ONBOARDING_STEPS = [
  { title: "Vilka är ni hemma?", render: renderObHushall },
  { title: "Budget & antal middagar", render: renderObBudget },
  { title: "Kost & allergier", render: renderObKost },
  { title: "Var handlar ni?", render: renderObButik },
];
let onboardingStep = 0;
function renderObHushall() {
  return `<div class="settings-grid"><div><label>Vuxna</label><div class="stepper"><button type="button" data-ob-adj="vuxna" data-delta="-1" aria-label="Färre vuxna">−</button><span>${state.hushall.vuxna}</span><button type="button" data-ob-adj="vuxna" data-delta="1" aria-label="Fler vuxna">+</button></div></div><div><label>Barn</label><div class="stepper"><button type="button" data-ob-adj="barn" data-delta="-1" aria-label="Färre barn">−</button><span>${state.hushall.barn}</span><button type="button" data-ob-adj="barn" data-delta="1" aria-label="Fler barn">+</button></div></div></div>`;
}
function renderObBudget() {
  return `<label for="obBudget">Veckobudget</label><div class="budget-row"><input type="number" id="obBudget" value="${state.budget}" min="0" step="50" inputmode="numeric"><span>kr</span></div><p class="budget-scope">${escapeHtml(app.budgetScopeText())}</p><div class="settings-grid"><div><label>Middagar per vecka</label><div class="stepper"><button type="button" data-ob-meals="-1" aria-label="Färre middagar">−</button><span>${state.middagar}</span><button type="button" data-ob-meals="1" aria-label="Fler middagar">+</button></div></div></div>`;
}
function renderObKost() {
  return `<label for="obKosttyp">Kosttyp</label><select id="obKosttyp"><option value="" ${!state.kost.kosttyp ? "selected" : ""}>Vanlig, allt</option><option value="vegetariskt" ${state.kost.kosttyp === "vegetariskt" ? "selected" : ""}>Vegetariskt</option><option value="veganskt" ${state.kost.kosttyp === "veganskt" ? "selected" : ""}>Veganskt</option></select><label>Allergier att undvika</label><div class="protein-source-chips" id="obAllergenChips">${ALLERGENS.map(a => `<label><input type="checkbox" value="${a}" ${state.kost.avoidAllergens.has(a) ? "checked" : ""}> ${a[0].toUpperCase() + a.slice(1)}</label>`).join("")}</div>`;
}
// G9: POSTNUMMER ÄR ETT FRIVILLIGT STEG, INTE EN GRIND.
//
// `/^\d{5}$/` krävdes för att passera steg 4 av 4 - alltså stod ett
// integritetsmotstånd precis före det ögonblick då appen för första gången
// levererar något. Den som inte ville lämna sin adress, eller inte kunde sin
// postnummerrad utantill, kom aldrig till en enda måltid.
//
// FALLBACK_BRANCH (app.js) bär redan hela vägen utan postnummer:
// riksgemensamma Willys-priser. Det är ett sämre svar än butiken runt hörnet,
// men det är ett svar - och den skillnaden står nu i klartext på skärmen i
// stället för bakom en spärr.
function renderObButik() {
  return `<label for="obPostcode">Postnummer (frivilligt)</label><div class="location-row"><input id="obPostcode" value="${escapeHtml(state.postnummer)}" inputmode="numeric" maxlength="5"><button type="button" id="obLocateBtn">Hitta mig</button></div><p class="location-hint" id="obPostcodeHint">Med postnummer jämför vi butikerna nära dig. Utan det visar vi riksgemensamma priser.</p><p class="ob-error" id="obPostcodeError"></p><button type="button" class="account-link-btn" id="obSkipPostcode">Hoppa över &ndash; vi visar riksgemensamma priser tills vidare</button><label for="obStore">Favoritbutik</label><select id="obStore">${app.storeOptionsMarkup(state.butik, "Välj åt mig")}</select>`;
}
function wireOnboardingStep() {
  document.querySelectorAll("[data-ob-adj]").forEach(button => button.addEventListener("click", () => {
    const key = button.dataset.obAdj, delta = Number(button.dataset.delta), min = key === "vuxna" ? 1 : 0;
    state.hushall[key] = Math.max(min, state.hushall[key] + delta);
    state.personer = Math.min(12, Math.max(1, state.hushall.vuxna + state.hushall.barn));
    saveState(); renderOnboardingStep();
  }));
  $("obBudget")?.addEventListener("input", e => { state.budget = clampBudget(e.target.value); saveState(); });
  document.querySelectorAll("[data-ob-meals]").forEach(button => button.addEventListener("click", () => {
    state.middagar = Math.min(Math.min(app.maxMeals(), app.maxDinners()), Math.max(1, state.middagar + Number(button.dataset.obMeals)));
    saveState(); renderOnboardingStep();
  }));
  $("obKosttyp")?.addEventListener("change", e => { state.kost.kosttyp = e.target.value; saveState(); });
  document.querySelectorAll("#obAllergenChips input").forEach(box => box.addEventListener("change", () => { state.kost.avoidAllergens = new Set([...document.querySelectorAll("#obAllergenChips input:checked")].map(b => b.value)); saveState(); }));
  $("obPostcode")?.addEventListener("input", e => {
    const previous = state.postnummer;
    state.postnummer = e.target.value.replace(/\D/g, "").slice(0, 5);
    if (state.postnummer !== previous) app.clearLocationDerivedState();
    saveState();
    app.syncNearbyBranches();
  });
  $("obStore")?.addEventListener("change", e => { state.butik = e.target.value; saveState(); });
  // G9: "Hitta mig" svalde ALLA fel tyst. Ingen geolocation i webbläsaren:
  // knappen gjorde ingenting. Nekad platsdelning: knappen gjorde ingenting.
  // En knapp som inte svarar är en återvändsgränd, och den låg mitt i det
  // enda steg som förut var en grind.
  $("obLocateBtn")?.addEventListener("click", () => {
    const knapp = $("obLocateBtn");
    const fel = $("obPostcodeError");
    if (!navigator.geolocation) {
      fel.textContent = "Den här webbläsaren kan inte dela din plats. Skriv postnumret i stället, eller hoppa över.";
      return;
    }
    fel.textContent = "";
    knapp.textContent = "Hämtar…";
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      state.position = { lat: coords.latitude, lon: coords.longitude };
      saveState();
      knapp.textContent = "Hittad";
    }, () => {
      knapp.textContent = "Hitta mig";
      fel.textContent = "Vi fick inte din plats. Skriv postnumret i stället, eller hoppa över.";
    });
  });
  // Steget hoppas över, veckan byggs ändå. Samma väg som knappen "Skapa min
  // vecka" tar - skillnaden är bara att den här säger vad man avstår.
  $("obSkipPostcode")?.addEventListener("click", () => finishOnboarding());
}
function renderOnboardingStep() {
  const current = ONBOARDING_STEPS[onboardingStep];
  $("onboardingTitle").textContent = current.title;
  $("onboardingBody").innerHTML = current.render();
  wireOnboardingStep();
  $("onboardingDots").innerHTML = ONBOARDING_STEPS.map((_, index) => `<i class="${index === onboardingStep ? "active" : ""}"></i>`).join("");
  $("onboardingBack").hidden = onboardingStep === 0;
  $("onboardingNext").querySelector("span").textContent = onboardingStep === ONBOARDING_STEPS.length - 1 ? "Skapa min vecka" : "Nästa";
}
// G6: onboardingmodalen gick inte att stänga med tangentbord ALLS - inget
// Escape, ingen fokusflytt, och tab-ordningen fortsatte rakt ner i appen
// bakom. Det var det första en ny användare mötte. Nu är den ett lager som
// alla andra: rubriken får fokus, appen bakom är inert, Escape stänger.
//
// Escape stänger onboardingen på samma villkor som "Hoppa över, jag ställer
// in senare" - den som backar ur ska inte mötas av samma modal vid nästa
// rendering, och att smyga tillbaka den vore att låsa in henne igen.
export function openOnboarding() {
  onboardingStep = 0;
  postcodeNoticeShown = false;
  renderOnboardingStep();
  openModal($("onboardingModal"), { onClose: skipOnboarding });
}
export function closeOnboarding() { closeModal($("onboardingModal")); }
function skipOnboarding() { state.onboardingComplete = true; saveState(); closeOnboarding(); }

// En gång per onboarding: raden om det halvskrivna postnumret ska påminna,
// inte spärra. Andra trycket går igenom oavsett.
let postcodeNoticeShown = false;

// Onboardingen är klar och veckan byggs. EN väg ut, oavsett om man fyllde i
// postnumret, hittade sig själv eller hoppade över steget.
//
// G8: knappen heter "Skapa min vecka" och skapar nu en vecka. Den öppnade
// planjämförelsen, där sju av åtta veckotyper är låsta för en gratisanvändare
// - det första en ny användare såg av produkten var alltså en hänglåsvägg,
// innan hon sett en enda måltid eller en enda prislapp. chooseMenu() bygger
// veckan av exakt de svar hon nyss gav och tar henne till Vecka-vyn.
// Erbjudandet om en annan veckotyp står kvar som en rad OVANFÖR den färdiga
// veckan (renderWeekPlanUpsell): sälj efter leverans, inte före.
//
// G9: syncNearbyBranches() struntar självt i ett postnummer som inte är fem
// siffror, så utan postnummer står state.branches kvar tomt och
// nearbyBranches() (app.js) svarar FALLBACK_BRANCH - riksgemensamma priser,
// precis det raden vid fältet lovade.
function finishOnboarding() {
  state.onboardingComplete = true;
  saveState();
  closeOnboarding();
  app.syncNearbyBranches();
  app.chooseMenu();
}

function wireOnboardingButtons() {
  const next = $("onboardingNext");
  if (!next || next.dataset.wired) return;
  next.dataset.wired = "1";
  next.addEventListener("click", () => {
    if (onboardingStep === ONBOARDING_STEPS.length - 1) {
      // G9: ETT HALVSKRIVET POSTNUMMER ÄR NÅGOT ANNAT ÄN INGET POSTNUMMER.
      //
      // Grinden är borta: tomt fält går igenom och ger riksgemensamma priser.
      // Men "123" är inte ett val att avstå - det är ett avbrutet försök, och
      // att tyst behandla det som "inget postnummer" vore att slänga det hon
      // skrev. En rad säger vad som saknas; nästa tryck går igenom, och
      // "Hoppa över" bredvid fältet går igenom direkt.
      const halvskrivet = state.postnummer && !/^\d{5}$/.test(state.postnummer);
      if (halvskrivet && !postcodeNoticeShown) {
        postcodeNoticeShown = true;
        $("obPostcodeError").textContent = "Postnumret har fem siffror. Fyll i det, eller hoppa över - vi visar riksgemensamma priser tills vidare.";
        return;
      }
      finishOnboarding();
      return;
    }
    onboardingStep++; renderOnboardingStep();
  });
  $("onboardingBack").addEventListener("click", () => { onboardingStep = Math.max(0, onboardingStep - 1); renderOnboardingStep(); });
  $("onboardingSkip").addEventListener("click", skipOnboarding);
}

// G8, andra halvan: erbjudandet som förut stod i vägen står nu bredvid.
//
// Raden syns så fort det finns en vecka att jämföra med, och leder till
// samma planjämförelse som förut - skillnaden är att användaren då redan
// sett sina sju rätter och sitt pris, och kan avgöra om en familjevecka
// vore bättre. En låst veckotyp är ett erbjudande när man vet vad man har,
// och en vägg när man inte gör det.
export function renderWeekPlanUpsell() {
  const row = $("weekPlanUpsell");
  if (!row) return;
  row.hidden = !state.weekPlan?.length;
}

function wireWeekPlanUpsell() {
  const row = $("weekPlanUpsell");
  if (!row || row.dataset.wired) return;
  row.dataset.wired = "1";
  row.addEventListener("click", () => { app.trackEvent("veckotyp_fran_vecka"); app.openPlanComparison(); });
}

// ---------------------------------------------------------------------------
// BETALVÄGGEN
// ---------------------------------------------------------------------------

// The paywall sells VALUE, never just says "Premium krävs". Opened from
// every locked control; prices come from the central config via
// /api/entitlements, so 59/399 exist in exactly one place (the backend).
export function openPaywall(triggerFeature = "") {
  const pricing = app.premiumPricing();
  let modal = document.getElementById("paywallModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "paywallModal";
    modal.className = "modal paywall-modal";
    document.body.appendChild(modal);
  }
  // G6: betalväggen byggs i JS och hade därför aldrig fått den role/aria som
  // markupmodalerna har - en modal som skärmläsaren inte vet att den är inne
  // i, mitt i ett betalflöde.
  modal.innerHTML = `<div class="modal-card paywall-card" role="dialog" aria-modal="true" aria-labelledby="paywallTitle">
    <button type="button" class="modal-close" data-paywall-close aria-label="Stäng">×</button>
    <p class="prem-kap">Matjakt Premium</p>
    <h2 id="paywallTitle">Alla butikers priser, sida vid sida</h2>
    <p class="paywall-lead">Planera veckan efter familj, budget eller träning. Jämför riktiga matpriser hos alla kvalificerade butiker och få exakt inköpslista för varje butik.</p>
    <ul class="paywall-points">
      <li>Alla 7 veckotyper och 1–7 middagar</li>
      <li>Alla butikers riktiga priser och butikskorgar</li>
      <li>Näringsmål, kcal- och proteinfilter</li>
      <li>Fullt skafferi och "Laga med det jag har"</li>
    </ul>
    ${paywallPlanMarkup(pricing)}
    <p class="prem-moms">Alla priser är totalpris inklusive moms.</p>
    ${app.withdrawalConsentMarkup("paywallWithdrawalConsent")}
    <p class="account-error" id="paywallError"></p>
    <p class="prem-avsluta">Avsluta när du vill, direkt i appen.</p>
    <button type="button" class="paywall-continue" data-paywall-close>Fortsätt gratis</button>
  </div>`;
  openModal(modal, { onClose: () => closeModal(modal) });
  modal.querySelectorAll("[data-paywall-close]").forEach(el =>
    el.addEventListener("click", () => closeModal(modal)));
  modal.querySelectorAll("[data-paywall-plan]").forEach(el =>
    el.addEventListener("click", () => beginCheckout(el.dataset.paywallPlan, modal)));
}

export async function beginCheckout(plan, root = document.getElementById("paywallModal")) {
  if (!state.user) {
    closeModal(document.getElementById("paywallModal"));
    app.openAccountModal();
    return;
  }
  const errorLine = root?.querySelector("#paywallError");
  if (errorLine) errorLine.textContent = "";
  // Ångerrätten kryssas i FÖRE knappen, inte bort efteråt: en digital tjänst
  // som levereras direkt får bara undantas från fjorton dagars ångerrätt om
  // kunden uttryckligen avstått den. Servern vägrar ändå utan samtycket -
  // det här är bara för att slippa gå till servern för att få veta det.
  const consent = app.withdrawalConsentGiven(root);
  if (!consent) {
    const text = "Kryssa i rutan om ångerrätten för att kunna gå vidare till betalningen.";
    if (errorLine) errorLine.textContent = text; else alert(text);
    root?.querySelector("[data-withdrawal-consent]")?.focus();
    return;
  }
  try {
    await flushServerSync();
    const { url } = await startCheckout(getStoredToken(), plan, consent);
    if (url) { if (app.isNativeApp()) awaitingPremiumActivation = true; app.openExternal(url); }
  } catch (error) {
    const text = error ? errorText(error) : "Kunde inte starta betalningen just nu.";
    if (errorLine) errorLine.textContent = text; else alert(text);
  }
}

export function openPremiumPitch() { openPaywall(); }
