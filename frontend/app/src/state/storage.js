export const STORAGE_KEY = "matjakt-state";

// Den oläsbara blobben flyttas hit i stället för att skrivas över (E3).
// Texten är allt som finns kvar av veckan, listan och skafferiet på en enhet
// utan konto - att låta nästa sparning lägga sig över den är att kasta den
// för gott. EN nyckel, inte en per gång: karantänen får inte bli en växande
// kyrkogård i en lagring som redan visat sig vara trång.
export const QUARANTINE_KEY = "matjakt-state-trasig";

/**
 * Läser den sparade blobben OCH säger vad som hände med den.
 *
 * Skillnaden mellan "det fanns ingenting" och "det fanns något som inte gick
 * att läsa" var den som saknades: båda gav `{}`, appen nollställdes tyst till
 * standardvärdena och skrev över den trasiga texten vid nästa sparning. Den
 * som öppnade appen såg en tom vecka utan ett ord om varför.
 *
 * @returns {{state: object, status: "ok"|"tom"|"trasig", raw?: string}}
 */
export function readStoredStateResult(storage, key = STORAGE_KEY) {
  let raw = null;
  try {
    raw = storage.getItem(key);
  } catch {
    // Lagringen går inte att läsa alls (privat läge, avstängda kakor). Det är
    // inte en trasig blob - det finns ingen.
    return { state: {}, status: "tom" };
  }
  if (raw === null || raw === undefined || raw === "") return { state: {}, status: "tom" };
  let value;
  try {
    value = JSON.parse(raw);
  } catch {
    return { state: {}, status: "trasig", raw };
  }
  // Giltig JSON som ändå inte är ett tillstånd - en lista, en siffra, null -
  // är precis lika oläsbar för appen som en avhuggen sträng.
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { state: {}, status: "trasig", raw };
  }
  return { state: value, status: "ok" };
}

export function readStoredState(storage, key = STORAGE_KEY) {
  return readStoredStateResult(storage, key).state;
}

/**
 * Flyttar undan en oläsbar blob så att nästa sparning inte skriver över den.
 *
 * FLYTTAR, inte kopierar: en kopia hade dubblat utrymmet för data som redan
 * kan ha fyllt lagringen, och originalet är ändå på väg att skrivas över.
 * Går inte karantänen att skriva (full enhet) lämnas originalet i fred -
 * sämre än att flytta, men aldrig sämre än i dag.
 *
 * @returns {boolean} om texten är räddad undan.
 */
export function quarantineStoredState(storage, raw, { key = STORAGE_KEY, quarantineKey = QUARANTINE_KEY } = {}) {
  if (typeof raw !== "string") return false;
  try {
    storage.setItem(quarantineKey, raw);
  } catch {
    return false;
  }
  try {
    if (typeof storage.removeItem === "function") storage.removeItem(key);
  } catch { /* nästa sparning skriver ändå över den - texten är redan räddad */ }
  return true;
}

export function writeStoredState(storage, value, key = STORAGE_KEY) {
  try {
    storage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
