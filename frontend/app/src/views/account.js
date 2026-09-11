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
  // Hushållsraden hör inte till en inloggning: den som aldrig skapat ett
  // konto är precis den som ska se den. Den ritas därför redan här, inte
  // först när refreshUser() hunnit svara.
  renderHouseholdInvitePrompt();
}

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
    const next = { ...prefs, [input.dataset.notifyPref]: input.checked };
    state.notisInstallningar = next;
    saveNotificationPrefs(state.authToken, next)
      .then(({ preferences }) => { state.notisInstallningar = preferences; })
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

  $("inviteDismissBtn")?.addEventListener("click", () => { $("inviteLanding").hidden = true; app.clearInviteFromUrl(); });
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
      const planLabel = state.user.subscriptionPlan === "yearly" ? (pricing.yearly?.priceText || "399 kr/år")
        : state.user.subscriptionPlan === "monthly" ? (pricing.monthly?.priceText || "59 kr/mån")
        : "din plan";
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
function renderObButik() {
  return `<label for="obPostcode">Postnummer</label><div class="location-row"><input id="obPostcode" value="${escapeHtml(state.postnummer)}" inputmode="numeric" maxlength="5"><button type="button" id="obLocateBtn">Hitta mig</button></div><p class="ob-error" id="obPostcodeError"></p><label for="obStore">Favoritbutik</label><select id="obStore">${app.storeOptionsMarkup(state.butik, "Välj åt mig")}</select>`;
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
  $("obLocateBtn")?.addEventListener("click", () => { if (!navigator.geolocation) return; navigator.geolocation.getCurrentPosition(({ coords }) => { state.position = { lat: coords.latitude, lon: coords.longitude }; saveState(); }, () => {}); });
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
export function openOnboarding() { onboardingStep = 0; $("onboardingModal").hidden = false; renderOnboardingStep(); }
export function closeOnboarding() { $("onboardingModal").hidden = true; }

function wireOnboardingButtons() {
  const next = $("onboardingNext");
  if (!next || next.dataset.wired) return;
  next.dataset.wired = "1";
  next.addEventListener("click", () => {
    if (onboardingStep === ONBOARDING_STEPS.length - 1) {
      if (!/^\d{5}$/.test(state.postnummer)) { $("obPostcodeError").textContent = "Ange ett giltigt postnummer (5 siffror)."; return; }
      state.onboardingComplete = true; saveState(); closeOnboarding(); app.syncNearbyBranches();
      // G8: KNAPPEN HETER "SKAPA MIN VECKA" OCH SKAPAR NU EN VECKA.
      //
      // Den öppnade planjämförelsen, där sju av åtta veckotyper är låsta för
      // en gratisanvändare. Det första en ny användare såg av produkten var
      // alltså en hänglåsvägg - innan hon sett en enda måltid eller en enda
      // prislapp, och innan appen bevisat att den kan något alls.
      //
      // chooseMenu() bygger veckan av exakt de svar hon nyss gav och tar
      // henne till Vecka-vyn. Erbjudandet om en annan veckotyp står kvar,
      // men som en rad OVANFÖR den färdiga veckan (renderWeekPlanUpsell):
      // sälj efter leverans, inte före.
      app.chooseMenu();
      return;
    }
    onboardingStep++; renderOnboardingStep();
  });
  $("onboardingBack").addEventListener("click", () => { onboardingStep = Math.max(0, onboardingStep - 1); renderOnboardingStep(); });
  $("onboardingSkip").addEventListener("click", () => { state.onboardingComplete = true; saveState(); closeOnboarding(); });
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
  const yearly = pricing.yearly || {};
  const monthly = pricing.monthly || {};
  let modal = document.getElementById("paywallModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "paywallModal";
    modal.className = "modal paywall-modal";
    document.body.appendChild(modal);
  }
  modal.innerHTML = `<div class="modal-card paywall-card">
    <button type="button" class="modal-close" data-paywall-close aria-label="Stäng">×</button>
    <p class="eyebrow">Matjakt Premium</p>
    <h2>Lås upp hela matveckan</h2>
    <p class="paywall-lead">Planera veckan efter familj, budget eller träning. Jämför riktiga matpriser hos alla kvalificerade butiker och få exakt inköpslista för varje butik.</p>
    <ul class="paywall-points">
      <li>Alla 7 veckotyper och 1–7 middagar</li>
      <li>Alla butikers riktiga priser och butikskorgar</li>
      <li>Näringsmål, kcal- och proteinfilter</li>
      <li>Fullt skafferi och "Laga med det jag har"</li>
    </ul>
    <button type="button" class="btn btn-primary paywall-yearly" data-paywall-plan="yearly">
      <span class="paywall-plan-label">${escapeHtml(yearly.badge || "Bäst värde")}</span>
      <strong>${escapeHtml(yearly.priceText || "399 kr/år")}</strong>
      <small>${escapeHtml(yearly.perMonthText || "≈ 33 kr/mån")} · ${escapeHtml(yearly.savingsText || "Spara 309 kr jämfört med månadsbetalning")}</small>
    </button>
    <button type="button" class="btn btn-ghost paywall-monthly" data-paywall-plan="monthly">
      <strong>${escapeHtml(monthly.priceText || "59 kr/mån")}</strong>
    </button>
    ${app.withdrawalConsentMarkup("paywallWithdrawalConsent")}
    <p class="account-error" id="paywallError"></p>
    <button type="button" class="paywall-continue" data-paywall-close>Fortsätt gratis</button>
  </div>`;
  modal.hidden = false;
  modal.querySelectorAll("[data-paywall-close]").forEach(el =>
    el.addEventListener("click", () => { modal.hidden = true; }));
  modal.querySelectorAll("[data-paywall-plan]").forEach(el =>
    el.addEventListener("click", () => beginCheckout(el.dataset.paywallPlan, modal)));
}

export async function beginCheckout(plan, root = document.getElementById("paywallModal")) {
  if (!state.user) {
    document.getElementById("paywallModal").hidden = true;
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
