// ---------------------------------------------------------------------------
// APPENS TILLSTÅND
//
// Veckan, inköpslistan, skafferiet, inställningarna - allt som överlever en
// omladdning och allt som synkas till kontot. Låg tidigare som en
// hundratecken lång objektliteral mitt i app.js, tillsammans med de tio
// funktioner som skriver i den.
//
// Modulen känner inte till DOM:en och inte till nätet. Den som behöver något
// av det skickar in det (`onSyncStatus`, `saveRemote`) - det är också vad som
// gör det här testbart utan webbläsare.
// ---------------------------------------------------------------------------

import { readStoredState, writeStoredState } from "./storage.js";
import { normalizePantry } from "../services/pantry.js";
import { emptyHouseholdState } from "../services/household-state.js";

// Versionen skrivs in i varje sparad blob. Den finns för att en FRAMTIDA
// ändring av vad ett fält betyder ska gå att hantera här, på ett ställe, i
// stället för att varje läsare gissar på innehållet. En blob utan
// schemaVersion är skriven innan versionen fanns (version 0) - inga fältnamn
// skiljer sig, det är bara ingen som sagt det.
export const SCHEMA_VERSION = 1;

// Texten när enheten är full. Sagt rakt ut, med den enda åtgärd som
// faktiskt hjälper - inte "Sparat på den här enheten" över en sparning som
// aldrig gick igenom.
export const STORAGE_FULL_TEXT = "Enhetens lagring är full - logga in så sparas veckan på kontot.";

const isPlainObject = value => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const finiteNumber = value => (typeof value === "number" && Number.isFinite(value) ? value : undefined);
const text = value => (typeof value === "string" ? value : undefined);
const flag = value => (typeof value === "boolean" ? value : undefined);
const names = value => (Array.isArray(value) ? value.filter(item => typeof item === "string") : undefined);
const records = value => (Array.isArray(value) ? value.filter(isPlainObject) : undefined);
const record = value => (isPlainObject(value) ? value : undefined);
const recordOrNull = value => (isPlainObject(value) ? value : value === null ? null : undefined);
const numberOrNull = value => (Number.isFinite(value) ? value : value === null ? null : undefined);

// normalizeState GARANTERAR FORMEN, inte innehållet.
//
// Den enda regel som lägger till en gräns är personer 1-12, och den fanns
// redan på boot-raden. Allt annat gör exakt en sak: ser till att ett fält som
// finns med har den typ appen förutsätter, och SLÄPPER det annars. Ett släppt
// fält betyder "som om det inte stod i blobben" - på boot faller standarden
// in, i applySyncBlob lämnas det som redan finns i minnet ifred.
//
// Det var precis det som saknades. En gammal serverblob med weekPlan som
// objekt gav `TypeError: state.weekPlan.map is not a function` - och
// pullAccountState svalde felet, så synken misslyckades tyst för alltid.
const FIELDS = {
  budget: finiteNumber,
  personer: value => (value === undefined ? undefined : Math.min(12, Math.max(1, Number(value) || 2))),
  middagar: finiteNumber,
  butik: text,
  postnummer: text,
  maxTid: finiteNumber,
  swapsThisWeek: finiteNumber,
  onboardingComplete: flag,
  pantry: value => (isPlainObject(value) ? normalizePantry(value) : undefined),
  favoriter: names,
  valda: names,
  avklarade: names,
  removedItems: names,
  harHemma: names,
  ogillar: names,
  weekPlan: names,
  apiRecipes: records,
  extraItems: records,
  savingsLog: records,
  stapleItems: records,
  foljdaVaror: records,
  // En historikpost utan sin `plan` är inget att gå tillbaka till, och
  // restorePreviousWeek kastar på den (`[...previous.plan]`).
  weekHistory: value => (Array.isArray(value)
    ? value.filter(entry => isPlainObject(entry) && Array.isArray(entry.plan))
    : undefined),
  betyg: record,
  feedback: record,
  stapleAsked: record,
  hushall: record,
  dbChainTotals: record,
  naringsmal: recordOrNull,
  pinnedBranch: recordOrNull,
  dbComparison: recordOrNull,
  dbPricedAt: numberOrNull,
  kost: value => (isPlainObject(value)
    ? { kosttyp: text(value.kosttyp) || "", avoidAllergens: names(value.avoidAllergens) || [] }
    : undefined),
};

export function normalizeState(blob) {
  if (!isPlainObject(blob)) return {};
  const clean = {};
  // Versionen bärs vidare som den lästes. En blob från en NYARE klient
  // normaliseras på samma sätt som alla andra - fälten vi känner igen
  // valideras, resten står kvar i blobben orörd.
  const version = finiteNumber(blob.schemaVersion);
  clean.schemaVersion = version === undefined ? 0 : version;
  Object.entries(FIELDS).forEach(([key, validate]) => {
    if (blob[key] === undefined) return;
    const value = validate(blob[key]);
    if (value !== undefined) clean[key] = value;
  });
  return clean;
}

// Det appen behöver av omvärlden: var tillståndet sparas, vilken receptbank
// veckoplanen slår upp i, hur en synkstatus visas och hur en blob når kontot.
let runtime = {
  storage: null,
  recipeBank: [],
  onSyncStatus: () => {},
  saveRemote: null,
  weekTotal: () => null,
};

export const state = {};

export function initAppState({ storage = null, authToken = null, recipeBank = [],
                               onSyncStatus = () => {}, saveRemote = null,
                               weekTotal = () => null } = {}) {
  runtime = { storage, recipeBank, onSyncStatus, saveRemote, weekTotal };
  const saved = normalizeState(storage ? readStoredState(storage) : {});
  Object.assign(state, {
    budget: saved.budget || 800,
    personer: saved.personer || 2,
    middagar: saved.middagar || 4,
    butik: saved.butik || "auto",
    postnummer: saved.postnummer || "",
    position: null,
    sokning: "",
    kategori: "alla",
    maxTid: saved.maxTid || 0,
    baraFavoriter: false,
    apiRecipes: saved.apiRecipes || [],
    pantry: saved.pantry || {},
    pantryTab: "skafferi",
    liveProdukter: [],
    favoriter: new Set(saved.favoriter || []),
    valda: new Set(saved.valda || []),
    avklarade: new Set(saved.avklarade || []),
    removedItems: new Set(saved.removedItems || []),
    expanded: null,
    authToken,
    user: null,
    naringsmal: saved.naringsmal || null,
    livePriser: {},
    liveBranchTotals: {},
    liveUpdatedAt: null,
    receptTaggar: new Set(),
    minProtein: 0,
    maxKcal: 0,
    hyllor: [],
    // Prissnapshotten återställs INTE härifrån utan ur kontots blob
    // (applySyncBlob). Den lokala vägen har aldrig gjort det, och att börja
    // nu vore en annan ändring än den här.
    dbChainTotals: {},
    dbComparison: null,
    dbPricedAt: null,
    dbPricingFailedAt: null,
    dbLockedChains: [],
    extraItems: saved.extraItems || [],
    extraMatches: {},
    branches: [],
    betyg: saved.betyg || {},
    kost: { kosttyp: saved.kost?.kosttyp || "", avoidAllergens: new Set(saved.kost?.avoidAllergens || []) },
    onboardingComplete: saved.onboardingComplete || false,
    hushall: saved.hushall || { vuxna: saved.personer || 2, barn: 0 },
    ogillar: new Set(saved.ogillar || []),
    feedback: saved.feedback || {},
    savingsLog: saved.savingsLog || [],
    swapsThisWeek: saved.swapsThisWeek || 0,
    pinnedBranch: saved.pinnedBranch || null,
    weekHistory: saved.weekHistory || [],
    foljdaVaror: saved.foljdaVaror || [],
    harHemma: new Set(saved.harHemma || []),
    stapleItems: saved.stapleItems || [],
    stapleAsked: saved.stapleAsked || {},
    household: emptyHouseholdState(),
    householdLoaded: false,
    notiser: [],
    // Veckans recept-id i dagordning (index 0 = måndag) - den egentliga
    // sanningen om "vilken dag har vilken rätt", nu när ett dagbyte ska
    // ersätta exakt en dags rätt på plats. state.valda (ett Set) finns kvar
    // vid sidan av som ett O(1)-medlemskapstest för receptkortens UI. Varje
    // plats som behöver dagordning läser weekPlan/selectedRecipes(), aldrig
    // valdas egen iterationsordning (ett Set har ingen knuten till dagar).
    weekPlan: saved.weekPlan || [...(saved.valda || [])],
  });
  return state;
}

// ---- veckoplanen ----------------------------------------------------------

// Veckans recept i DAGORDNING. En dag vars recept inte går att slå upp -
// receptbanken inte laddad än, receptet borttaget i backend, provider-recept
// rensat vid utloggning - blir `null`, inte borta.
//
// Förut filtrerades de bort, och då förskjöts alla EFTERFÖLJANDE dagar ett
// steg: onsdagens rätt märktes "Tis". Samtidigt indexerar swapWeekPlanDay in
// i den ofiltrerade weekPlan, så de två indexrymderna divergerade och
// bytesrutan kunde säga "Ons middag · nuvarande: <tisdagens rätt>".
export function selectedRecipes() {
  const all = [...runtime.recipeBank, ...state.apiRecipes];
  return state.weekPlan.map(id => all.find(recipe => recipe.id === id) ?? null);
}

export function setWeekPlan(ids) {
  // Papperskorgen: den vecka som just ersätts läggs överst i historiken (de
  // tolv senaste behålls, synkas med kontot). "Skapa ny vecka" av misstag ska
  // aldrig kosta en kurerad vecka, och historiken är dessutom det som gör att
  // samma rätter inte kommer tillbaka direkt (§15).
  if (state.weekPlan?.length && state.weekPlan.join() !== [...ids].join()) {
    // Totalen sparas MED veckan så budgethjälpen har riktiga tal att jämföra
    // mot (§18). Bara en riktig, prissatt total - null när veckan aldrig hann
    // prissättas, så snittet aldrig bygger på en gissning.
    state.weekHistory = [{ plan: [...state.weekPlan], savedAt: Date.now(),
                           total: runtime.weekTotal() },
                         ...(state.weekHistory || [])].slice(0, 12);
  }
  state.weekPlan = [...ids];
  state.valda = new Set(ids);
}

export function addToWeekPlan(id) {
  if (!state.weekPlan.includes(id)) state.weekPlan.push(id);
  state.valda.add(id);
}

export function removeFromWeekPlan(id) {
  state.weekPlan = state.weekPlan.filter(existing => existing !== id);
  state.valda.delete(id);
}

// Ersätter exakt receptet på den här dagens plats - varje annan dags rätt
// behåller sin egen plats, vilket är hela poängen med att byta "den här
// dagen" i stället för att rensa och välja om veckan.
export function swapWeekPlanDay(dayIndex, newId) {
  state.weekPlan = state.weekPlan.map((id, index) => (index === dayIndex ? newId : id));
  state.valda = new Set(state.weekPlan);
}

// ---- sparning och synk ----------------------------------------------------

export function buildSyncPayload() {
  return { schemaVersion: SCHEMA_VERSION, budget: state.budget, personer: state.personer, middagar: state.middagar, butik: state.butik, postnummer: state.postnummer, maxTid: state.maxTid, pantry: state.pantry, favoriter: [...state.favoriter], valda: [...state.valda], avklarade: [...state.avklarade], removedItems: [...state.removedItems], apiRecipes: state.apiRecipes.filter(recipe => state.valda.has(recipe.id)), naringsmal: state.naringsmal, betyg: state.betyg, kost: { kosttyp: state.kost.kosttyp, avoidAllergens: [...state.kost.avoidAllergens] }, onboardingComplete: state.onboardingComplete, hushall: state.hushall, ogillar: [...state.ogillar], feedback: state.feedback, savingsLog: state.savingsLog, swapsThisWeek: state.swapsThisWeek, pinnedBranch: state.pinnedBranch, weekPlan: state.weekPlan, weekHistory: state.weekHistory, foljdaVaror: state.foljdaVaror, extraItems: state.extraItems, harHemma: [...state.harHemma], stapleItems: state.stapleItems, stapleAsked: state.stapleAsked,
    // Den senaste riktiga prissnapshotten. Målas direkt vid nästa besök med
    // sin egen tidsstämpel medan en ny hämtning körs - skillnaden mellan
    // "pris hämtas…" i sekunder vid varje öppning och priser som helt enkelt
    // är där. Förlängs aldrig, visas aldrig utan sin "Uppdaterad"-stämpel.
    dbChainTotals: state.dbChainTotals, dbComparison: state.dbComparison, dbPricedAt: state.dbPricedAt };
}

// Kontots blob in i tillståndet. Går genom exakt samma normalizeState som
// boot-raden: servern är inte mer betrodd än localStorage.
//
// EN BLOB ÄR EN ÖGONBLICKSBILD, INTE ETT FACIT. Den begärdes vid ett visst
// tillfälle och kan landa långt senare: boot-radens `refreshUser()` väntas
// inte in, och på `?billing=success` startar premiumpollen en andra hämtning
// i samma andetag - två kontosynkar i luften samtidigt, utan inbördes
// ordning. På en lastad maskin hinner enheten skriva nyare saker under tiden,
// och den blob som landar sist raderar dem tyst. Båda fallen nedan har sänkt
// browser-E2E:n, omväxlande, och gått igenom vid omkörning:
//
//   * ONBOARDINGSVAREN. Blobben togs före onboardingen (budget 800, tomt
//     postnummer); användaren har just skrivit 900 och sitt eget postnummer.
//     Fältet skrivs över utan att rutan på skärmen ändras - den visar 900
//     medan tillståndet säger 800.
//   * PRISBILDEN. Blobben bär Free-vyns maskade bild med EN prissatt kedja;
//     skärmen visar de tre kedjor Premium just betalats för. Efteråt hämtas
//     ingen ny prissättning (nyckeln är redan den premiumnyckeln), så den
//     som betalat blir kvar i Free-vyn tills veckan råkar ändras.
//
// Två frågor avgör saken, och båda har ett svar i datan:
//
//   1. SATT ANVÄNDAREN OCH SVARADE? `onboardingOpen` säger det, och
//      anroparen läser av rutan BÅDE när hämtningen går ut och när svaret
//      kommer (app.js): sista knappen stänger rutan, så en blob som landar
//      efter den är precis lika gammal som en som landar före. Säger blobben
//      då uttryckligen att onboardingen inte är gjord, är HELA den äldre än
//      svaren - ingenting av den skrivs in.
//
//      Frågan ställs om RUTAN, inte om `state.onboardingComplete`: den
//      flaggan överlever en utloggning med flit (den är av apparat-karaktär,
//      se utloggningen i app.js), och att läsa den hade tystat blobben för
//      nästa person som loggar in på telefonen - en gäst som aldrig gjort
//      onboardingen men mycket väl kan ha en vecka på sitt konto.
//   2. ÄR PRISBILDEN ÄLDRE? Den bär sin egen datumstämpel (`dbPricedAt`).
//      Den äldre av två daterade bilder får aldrig lägga sig över den nyare.
//
// Vad som INTE görs: ingen sammanslagning fält för fält. Blobben är ETT
// ögonblick och behandlas som ett - samma hållning som E8 tog för den andra
// fliken (se src/state/tab-sync.js). Det lokala läget ligger kvar och den
// debouncade synken skickar upp det, så servern kommer i kapp av sig själv.
//
// Returnerar om blobben skrevs in, så anroparen slipper rita om och spara
// ned ett läge som inte ändrats.
export function applySyncBlob(blob, { onboardingOpen = false } = {}) {
  if (!blob) return false;
  const clean = normalizeState(blob);
  if (onboardingOpen && clean.onboardingComplete === false) return false;
  const set = (key, apply) => { if (clean[key] !== undefined) apply(clean[key]); };
  set("budget", value => { state.budget = value; });
  set("personer", value => { state.personer = value; });
  set("middagar", value => { state.middagar = value; });
  set("butik", value => { state.butik = value; });
  set("postnummer", value => { state.postnummer = value; });
  set("maxTid", value => { state.maxTid = value; });
  set("pantry", value => { state.pantry = value; });
  set("favoriter", value => { state.favoriter = new Set(value); });
  set("valda", value => { state.valda = new Set(value); });
  set("avklarade", value => { state.avklarade = new Set(value); });
  set("removedItems", value => { state.removedItems = new Set(value); });
  set("apiRecipes", value => { state.apiRecipes = value; });
  set("extraItems", value => { state.extraItems = value; });
  set("weekHistory", value => { state.weekHistory = value; });
  set("foljdaVaror", value => { state.foljdaVaror = value; });
  set("harHemma", value => { state.harHemma = new Set(value); });
  set("stapleItems", value => { state.stapleItems = value; });
  set("stapleAsked", value => { state.stapleAsked = value; });
  // Prisbilden hör ihop och byts i ett stycke - eller inte alls. Lika gamla
  // (eller odaterade i båda ändar) räknas som blobbens: det är fallet där
  // enheten inte har någon egen bild, och att måla den sparade i stället för
  // "pris hämtas…" är hela skälet till att den ligger i blobben.
  if (clean.dbChainTotals && (clean.dbPricedAt || 0) >= (state.dbPricedAt || 0)) {
    state.dbChainTotals = clean.dbChainTotals;
    state.dbComparison = clean.dbComparison || null;
    state.dbPricedAt = clean.dbPricedAt || null;
  }
  set("naringsmal", value => { state.naringsmal = value; });
  set("betyg", value => { state.betyg = value; });
  set("kost", value => { state.kost = { kosttyp: value.kosttyp, avoidAllergens: new Set(value.avoidAllergens) }; });
  set("onboardingComplete", value => { state.onboardingComplete = value; });
  set("hushall", value => { state.hushall = value; });
  set("ogillar", value => { state.ogillar = new Set(value); });
  set("feedback", value => { state.feedback = value; });
  set("savingsLog", value => { state.savingsLog = value; });
  set("swapsThisWeek", value => { state.swapsThisWeek = value; });
  set("pinnedBranch", value => { state.pinnedBranch = value; });
  set("weekPlan", value => { state.weekPlan = value; });
  return true;
}

// Skriv till enheten utan att röra kontot - efter en HÄMTNING från kontot är
// det precis vad som ska hända, inte en ny push tillbaka av det vi nyss fick.
export function persistLocally() {
  if (!runtime.storage) return true;
  return writeStoredState(runtime.storage, buildSyncPayload());
}

let serverSyncTimer = null;

export function scheduleServerSync() {
  if (!state.authToken || !runtime.saveRemote) { runtime.onSyncStatus("idle"); return; }
  clearTimeout(serverSyncTimer);
  runtime.onSyncStatus("pending");
  // Debouncad: saveState() körs vid nästan varje interaktion (skafferiets
  // +/-, betyg, byten…) - att skicka till servern vid varenda en vore slöseri
  // och kunde kapplöpa med sig själv. En begäran ~1,5 s efter sista ändringen
  // räcker för "följer med till en annan telefon", vilket är kravet här.
  serverSyncTimer = setTimeout(() => {
    serverSyncTimer = null;
    runtime.saveRemote(state.authToken, buildSyncPayload())
      .then(() => runtime.onSyncStatus("idle"))
      .catch(() => runtime.onSyncStatus("error"));   // nästa saveState försöker igen
  }, 1500);
}

// Skicka en väntande synk NU. Lämnas sidan (Stripe Checkout, portalen, fliken
// stängs) inom 1,5 s efter sista ändringen försvann annars den väntande
// timern med sidan - och nästa öppning hämtade serverns ÄLDRE blob och skrev
// över veckan och onboardingflaggan som just gjorts. Sett i CI: efter checkout
// var Handla tom och onboarding "ogjord".
export async function flushServerSync({ keepalive = false } = {}) {
  if (!serverSyncTimer || !state.authToken || !runtime.saveRemote) return;
  clearTimeout(serverSyncTimer);
  serverSyncTimer = null;
  try {
    await runtime.saveRemote(state.authToken, buildSyncPayload(), { keepalive });
    runtime.onSyncStatus("idle");
  } catch {
    runtime.onSyncStatus("error");
  }
}

// Lokalt sparas ALLTID, synkront - utom när enheten är full. Returvärdet från
// writeStoredState ignorerades förut, och användaren fick läsa "Sparat på den
// här enheten" över en veckoplan som aldrig lämnade minnet. På iOS Safari
// (5 MB) är den gränsen nåbar: weekHistory, savingsLog, stapleItems,
// apiRecipes och dbChainTotals med hela sina radlistor bor i samma blob.
export function saveState() {
  const stored = persistLocally();
  scheduleServerSync();
  // Efter scheduleServerSync, med flit: dess "pending"/"idle" får inte skriva
  // över beskedet om att sparningen misslyckades. Lyckas kontosynken sedan är
  // veckan faktiskt räddad, och statusen går över till "allt sparat" - vilket
  // då är sant.
  if (!stored) runtime.onSyncStatus("error", STORAGE_FULL_TEXT);
  return stored;
}
