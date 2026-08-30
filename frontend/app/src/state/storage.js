export const STORAGE_KEY = "matjakt-state";

export function readStoredState(storage, key = STORAGE_KEY) {
  try {
    const value = JSON.parse(storage.getItem(key) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

export function writeStoredState(storage, value, key = STORAGE_KEY) {
  try {
    storage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
