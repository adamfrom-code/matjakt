// P02d: STOREKIT I APPEN - logiken, utan DOM och utan plugin.
//
// Apples App Store Review Guidelines 3.1.1 kräver In-App Purchase för det
// som låser upp digitala funktioner, och 3.1.1(a) förbjuder knappar som leder
// till andra betalvägar på alla storefronter utom den amerikanska. Knappen
// "Prenumerera" -> Stripe i SFSafariViewController var därför ett stopp i
// App Review (docs/IAP_COMPLIANCE.md). I iOS-appen köps Premium nu via
// StoreKit 2, och den verifierade transaktionen (JWS) anmäls till servern,
// som är den enda som avgör vad kontot har (P02b, P02c).
//
// Den här modulen avgör NÄR StoreKit-vägen gäller och ÖVERSÄTTER mellan
// serverns kontrakt (/api/entitlements -> `apple`-blocket, `pricing` med
// storekitProductId) och pluginets (@capgo/native-purchases: Product,
// Transaction). app.js håller tillstånd och ropar på pluginet; här finns
// ingenting som inte går att pröva i node.
//
// FLAGGAN ÄR SERVERNS. `entitlements.apple.enabled` kommer ur
// MATJAKT_APPLE_IAP på servern. Av = exakt dagens beteende (Stripe-knappen
// står kvar för intern TestFlight, som VAG-N-appstore.md §0 tillåter). På
// gäller bara i iOS-appen: webben rör sig inte, och Android har inga
// produkter i Play.
//
// PRISET ÄR STOREKITS. Apples prispunkt väljs i App Store Connect och kan
// skilja sig från 59/399 på webben; det pris som visas ska vara det som dras
// (prisinformationslagen, och 3.1.2(c): "clearly describe what the user will
// get for the price"). Därför läggs pluginets `priceString` - lokaliserat,
// med valuta - som `displayPrice` ovanpå serverns prisobjekt, och
// premiumskarmen.js ritar den strängen i stället för ett tal. Ingen
// sparräkning görs på Apples pris: 12 x månad - år är webbens aritmetik, och
// vi vet inte att Apples två punkter står i samma förhållande.

export const PLUGIN_NAME = "NativePurchases";
export const PRODUCT_TYPE = "subs";
// Apples egen sida för att hantera prenumerationer - dit "Hantera
// prenumeration" pekar för en App Store-kund som sitter på webben.
export const MANAGE_SUBSCRIPTIONS_URL = "https://apps.apple.com/account/subscriptions";
export const PLANS = ["monthly", "yearly"];

/** Ska köpet gå via StoreKit? Bara iOS-appen, bara när servern säger på. */
export function storeKitActive(entitlements, { native = false, platform = "" } = {}) {
  if (!native) return false;
  if (String(platform || "").toLowerCase() === "android") return false;
  return Boolean(entitlements?.apple?.enabled);
}

/** Produkt-id:t för en plan, ur serverns apple-block (features.PRICING). */
export function productForPlan(entitlements, plan) {
  const id = entitlements?.apple?.products?.[plan];
  return typeof id === "string" && id ? id : null;
}

/** Omvänt: vilken plan ett produkt-id är, eller null. */
export function planForProduct(entitlements, productId) {
  if (!productId) return null;
  for (const plan of PLANS) {
    if (productForPlan(entitlements, plan) === productId) return plan;
  }
  return null;
}

/** Alla våra produkt-id:n, i planordning. */
export function productIdentifiers(entitlements) {
  return PLANS.map(plan => productForPlan(entitlements, plan)).filter(Boolean);
}

/** Argumenten till pluginets purchaseProduct() - eller null om något saknas. */
export function purchaseOptions(entitlements, plan) {
  const productIdentifier = productForPlan(entitlements, plan);
  const appAccountToken = entitlements?.apple?.appAccountToken;
  if (!productIdentifier || typeof appAccountToken !== "string" || !appAccountToken) return null;
  return { productIdentifier, productType: PRODUCT_TYPE, appAccountToken };
}

/**
 * Serverns prisobjekt med StoreKits lokaliserade pris ovanpå.
 *
 * Returnerar en KOPIA: serverns tal finns kvar (jämförelsetabellen och
 * sparräkningen på webben läser dem), men varje plan vars produkt pluginet
 * levererat får `displayPrice`. Utan produkter returneras objektet orört.
 */
export function overlayStoreKitPrices(pricing, products) {
  if (!Array.isArray(products) || !products.length || !pricing) return pricing;
  const byId = new Map(products
    .filter(p => p && typeof p.identifier === "string" && typeof p.priceString === "string" && p.priceString.trim())
    .map(p => [p.identifier, p.priceString.trim()]));
  const out = {};
  let hit = false;
  for (const [plan, entry] of Object.entries(pricing)) {
    const displayPrice = entry && byId.get(entry.storekitProductId);
    out[plan] = displayPrice ? { ...entry, displayPrice } : entry;
    hit = hit || Boolean(displayPrice);
  }
  return hit ? out : pricing;
}

/**
 * JWS:erna att anmäla efter "Återställ köp": pluginets aktiva köp som är
 * någon av VÅRA produkter. Andra appars köp på samma Apple-konto ska inte
 * skickas till vår server, och ett köp utan JWS går inte att verifiera.
 */
export function restorableTransactions(purchases, entitlements) {
  const ours = new Set(productIdentifiers(entitlements));
  return (Array.isArray(purchases) ? purchases : [])
    .filter(p => p && ours.has(p.productIdentifier) && typeof p.jwsRepresentation === "string" && p.jwsRepresentation)
    .filter(p => p.isActive !== false)
    .map(p => p.jwsRepresentation);
}

/** Avbröt kunden själv? Då är det inget fel att visa. */
export function isUserCancelled(error) {
  const text = String(error?.message || error || "").toLowerCase();
  return /cancel|avbr|user_cancelled|userCancelled/i.test(text);
}
