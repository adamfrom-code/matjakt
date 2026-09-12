// J4: NÄR entitlementen ska hämtas om.
//
// Svaret från /api/entitlements hämtades på exakt två ställen: vid boot och
// inuti refreshUser() vid inloggning. En PWA stängs aldrig - telefonen låses
// och appen ligger kvar i bakgrunden i veckor - så för den som redan är
// inloggad är "vid boot" i praktiken "en gång". Två fel följer av det, och de
// pekar åt var sitt håll:
//
//   - Den som säger upp sin prenumeration fortsätter se Premium tills någon
//     laddar om sidan. Betalväggen är öppen för en icke-betalande kund.
//   - Den som just uppgraderat i Stripes kundportal kommer tillbaka till en
//     app som fortfarande ritar lås. Köpflödet har en poll efter webhooken
//     (activatePremiumAfterCheckout); portalflödet hade ingenting.
//
// Modulen avgör bara NÄR svaret ska hämtas om, aldrig vad det betyder - det
// bor kvar i backend (services/accounts/features.py) och i fetchEntitlements.
// Två regler:
//
//   1. Appen vaknar och svaret är gammalt -> hämta om. Åldersspärren behövs
//      för att visibilitychange fyras vid VARJE flikbyte; utan den blir ett
//      vanligt arbetspass framför datorn hundratals anrop mot
//      /api/entitlements, och då rivs raden ut igen nästa gång någon mäter
//      trafiken.
//   2. Personen har varit hos Stripes kundportal -> hämta om direkt, hur
//      färskt svaret än är. Det är den enda platsen där hon själv just ändrat
//      sin prenumeration, och där är spärren fel svar: hon står framför
//      skärmen och väntar på att låsen ska släppa.

// En minut. Kortare än varje rimlig väg mellan "avsluta i kundportalen" och
// "titta på appen igen", och långt över den takt flikbyten kommer i.
export const ENTITLEMENT_STALE_AFTER_MS = 60_000;

export function createEntitlementRefresh({
  refresh,
  now = () => Date.now(),
  staleAfterMs = ENTITLEMENT_STALE_AFTER_MS,
} = {}) {
  // Modulen skapas i samma andetag som appen hämtar entitlementen första
  // gången, så svaret räknas som färskt från start. Annars skulle det första
  // flikbytet efter boot ge ett andra anrop direkt.
  let lastRefreshAt = now();
  let billingVisitPending = false;
  let inFlight = null;

  function isStale(at = now()) {
    return at - lastRefreshAt >= staleAfterMs;
  }

  function run() {
    // Ett svar i luften åt gången. Native-appen skickar både appStateChange
    // och visibilitychange vid samma uppvaknande, men DEN dubbletten fångas
    // redan av åldersspärren nedan - tiden stämplas innan anropet går ut, så
    // det andra uppvaknandet ser ett färskt svar. Raden här behövs för det
    // fall spärren släpper igenom: ett anrop som hänger längre än en minut,
    // telefonen som vaknade i tunneln. Utan den köar en sliten mobil upp
    // parallella anrop mot /api/entitlements.
    if (inFlight) return inFlight;
    // Stämpeln konsumeras bara när ett anrop faktiskt går ut. Hänger ett
    // svar redan i luften gäller portalbesöket nästa uppvaknande i stället.
    billingVisitPending = false;
    lastRefreshAt = now();
    inFlight = Promise.resolve()
      // Ett nätfel får inte rivas vidare: onAppResumed hämtar hushållet och
      // notiserna i samma andetag, och de ska inte falla för att telefonen
      // vaknade i en tunnel. Den gamla planen gäller tills nästa försök.
      .then(() => refresh())
      .catch(() => {})
      .finally(() => { inFlight = null; });
    return inFlight;
  }

  return {
    // Appen skickade just personen till Stripes kundportal.
    markBillingVisit() { billingVisitPending = true; },
    // Entitlementen hämtades någon annanstans ifrån (boot, inloggning) - det
    // svaret är lika färskt som ett vi hämtat själva.
    markRefreshed(at = now()) { lastRefreshAt = at; },
    isStale,
    // Appen vaknar. Returnerar hämtningen om den startades, annars null.
    onResume() {
      if (!billingVisitPending && !isStale()) return null;
      return run();
    },
  };
}
