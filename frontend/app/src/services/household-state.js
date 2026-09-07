/**
 * Hushållets lokala kopia av serverns rader.
 *
 * MERGE PER RAD, ALDRIG HELA LISTAN. Servern svarar med "det här har ändrats
 * sedan revision N", och den här modulen lägger in de raderna en och en.
 * Adam och Sara kan därför stå i samma affär och ändra varsin vara utan att
 * den enes svar skriver över den andres - vilket är exakt det som händer om
 * en klient skickar tillbaka hela sin lista (§26).
 *
 * En äldre revision vinner aldrig över en nyare: ett svar som blev fördröjt
 * i mobilnätet kan komma efter ett färskare, och utan den kontrollen hade
 * "köpt" hoppat tillbaka till "behöver köpa" av sig självt.
 */

export const NEED_TO_BUY = "NEED_TO_BUY";
export const ALREADY_HAVE = "ALREADY_HAVE";
export const PURCHASED = "PURCHASED";
export const REMOVED = "REMOVED";

export const LOCATIONS = ["skafferi", "kyl", "frys"];

/**
 * Radens identitet i hushållet - SAMMA formel som serverns fold()/item_key()
 * i backend/services/household/store.py. Går de isär hittar servern ingen
 * rad, svarar 400, och klientens optimistiska rad blir en dubblett som inte
 * går att bocka av (hänt på riktigt 2026-09-07: skrivvägen nycklade på GTIN
 * medan veckans rader låg namn-nycklade). tests/fixtures/household-keys.json
 * läses av både nod- och Python-testerna och låser fast att de räknar lika.
 */
export function foldName(name) {
  return String(name || "").toLowerCase().normalize("NFD").replace(/\p{Mn}/gu, "").replace(/\s+/g, " ").trim();
}

/** Inköpslistans rader nycklas på NAMN. Skafferiet har egna rader och egen
 * nyckel (gtin när varan är känd) - blanda aldrig de två. */
export function shoppingKey(name) {
  return `name:${foldName(name)}`;
}

export function emptyHouseholdState() {
  return { id: null, name: "", role: null, members: [], revision: 0, shopping: {}, inventory: {}, docs: {} };
}

export function applySync(current, payload) {
  const next = current && current.id ? current : emptyHouseholdState();
  if (!payload) return next;
  const state = {
    ...next,
    shopping: { ...next.shopping },
    inventory: { ...next.inventory },
    docs: { ...next.docs },
  };
  if (payload.household) {
    state.id = payload.household.id;
    state.name = payload.household.name;
    state.role = payload.household.role;
    state.members = payload.household.members || [];
  } else if (payload.householdId) {
    state.id = payload.householdId;
  }
  if (Array.isArray(payload.members) && payload.members.length) state.members = payload.members;
  (payload.shopping || []).forEach(item => mergeRow(state.shopping, item));
  (payload.inventory || []).forEach(item => mergeRow(state.inventory, item));
  Object.entries(payload.docs || {}).forEach(([name, entry]) => {
    const existing = state.docs[name];
    if (!existing || (entry.revision || 0) >= (existing.revision || 0)) state.docs[name] = entry;
  });
  if (typeof payload.revision === "number") state.revision = Math.max(state.revision, payload.revision);
  return state;
}

function mergeRow(bucket, item) {
  if (!item || !item.key) return;
  const existing = bucket[item.key];
  // Lika revision skriver också: samma rad kan hämtas om (since=0) och ska
  // då landa som servern har den.
  if (existing && (existing.revision || 0) > (item.revision || 0)) return;
  bucket[item.key] = item;
}

/** En rad som klienten just ändrat, innan serverns svar hunnit fram. Optimistisk
 * uppdatering är skillnaden mellan en knapp som känns direkt och en som känns
 * trög i en affär med dålig täckning. */
export function applyLocalRow(current, kind, item) {
  const bucket = kind === "inventory" ? "inventory" : "shopping";
  return { ...current, [bucket]: { ...current[bucket], [item.key]: { ...current[bucket][item.key], ...item } } };
}

/** Gravstenar (deleted) ligger kvar i state så en äldre revision aldrig kan
 * återuppliva raden, men de är inte rader någon ska se. */
export function shoppingRows(state) {
  return Object.values(state.shopping || {}).filter(item => !item.deleted);
}

/** Det som faktiskt ska handlas. REMOVED är ute ur listan; PURCHASED och
 * ALREADY_HAVE har lämnat behovet men visas i sina egna sektioner. */
export function needToBuy(state) {
  return shoppingRows(state).filter(item => item.status === NEED_TO_BUY);
}

export function handled(state) {
  return shoppingRows(state).filter(item => item.status === PURCHASED || item.status === ALREADY_HAVE);
}

export function inventoryRows(state, location = null) {
  return Object.values(state.inventory || {})
    .filter(item => !item.deleted && (!location || item.location === location));
}

/**
 * Vad prismotorn får veta om vad som finns hemma.
 *
 * KONSERVATIVT (§10/§11): bara rader med en mängd vi faktiskt vet. En vara
 * utan mängd säger "vi har den", inte "vi har tillräckligt", och att skicka
 * den som ett tal hade fått motorn att räkna bort ett behov på en gissning.
 */
export function pantryAmountsFor(state) {
  const amounts = {};
  inventoryRows(state).forEach(item => {
    const amount = Number(item.amount);
    if (Number.isFinite(amount) && amount > 0) amounts[item.name] = amount;
  });
  return amounts;
}

/** Namnen på det hushållet har hemma - för "laga med det jag har" och för
 * receptval som vill använda upp råvaror (§17). */
export function inventoryNames(state) {
  return inventoryRows(state).map(item => item.name);
}

export function memberById(state, userId) {
  return (state.members || []).find(member => member.userId === userId) || null;
}

export function memberName(state, userId) {
  const member = memberById(state, userId);
  if (!member) return "";
  return member.displayName || (member.email ? member.email.split("@")[0] : "");
}

/** Hushållets samlade matpreferenser, för veckogeneratorn (§3).
 * Allergier och ogillar SLÅS IHOP - det någon inte tål gäller hela bordet.
 * Kosttyp gör det inte: att en är vegetarian gör inte veckan vegetarisk. */
export function householdDietary(state) {
  const allergies = new Set();
  const dislikes = new Set();
  let anyChild = false;
  let mildestSpice = null;
  (state.members || []).forEach(member => {
    const profile = member.profile || {};
    (profile.allergies || []).forEach(value => allergies.add(value));
    (profile.dislikes || []).forEach(value => dislikes.add(value));
    if (profile.child) anyChild = true;
    if (profile.spice === "mild" || (profile.spice === "medel" && mildestSpice !== "mild")) {
      mildestSpice = profile.spice;
    }
  });
  return { allergies: [...allergies], dislikes: [...dislikes], anyChild, spice: mildestSpice };
}
