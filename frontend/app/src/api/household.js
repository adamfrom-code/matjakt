import { API_BASE_URL } from "./config.js";

/**
 * Hushållets API-klient.
 *
 * En regel genom hela filen: klienten skickar ALDRIG med ett household_id.
 * Servern slår upp hushållet från sessionen, så det finns ingenting här att
 * manipulera - se services/household/routes.py.
 */

async function parseJsonResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || `HTTP ${response.status}`), { status: response.status, code: data.code });
  return data;
}

function authed(token, extra = {}) {
  return { Authorization: `Bearer ${token}`, ...extra };
}

function post(path, token, body) {
  return fetch(`${API_BASE_URL}/household${path}`, {
    method: "POST",
    headers: authed(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(body || {}),
  }).then(parseJsonResponse);
}

function get(path, token) {
  return fetch(`${API_BASE_URL}/household${path}`, { headers: token ? authed(token) : {} })
    .then(parseJsonResponse);
}

export const fetchHousehold = token => get("", token);
export const syncHousehold = (token, since = 0) => get(`/sync?since=${encodeURIComponent(since)}`, token);
export const createHousehold = (token, name) => post("/create", token, { name });
export const renameHousehold = (token, name) => post("/rename", token, { name });
export const saveHouseholdProfile = (token, fields) => post("/profile", token, fields);
export const createInvite = token => post("/invite", token);
export const revokeInvites = token => post("/invite/revoke", token);
export const joinHousehold = (token, inviteToken) => post("/join", token, { token: inviteToken });
export const leaveHousehold = token => post("/leave", token);
export const removeMember = (token, userId) => post("/remove-member", token, { userId });

// Inbjudningslandningen: enda vägen som fungerar utan inloggning, och den
// visar bara hushållets namn och vem som bjöd in.
export const previewInvite = inviteToken => get(`/invite?token=${encodeURIComponent(inviteToken)}`);

export const upsertShoppingItem = (token, item) => post("/shopping/item", token, item);
export const setShoppingStatus = (token, key, status) => post("/shopping/status", token, { key, status });
export const replaceWeekItems = (token, items) => post("/shopping/week", token, { items });
export const deleteShoppingItem = (token, key) => post("/shopping/delete", token, { key });
export const markAtHome = (token, key, location) => post("/shopping/at-home", token, { key, location });
export const markPurchased = (token, key, options = {}) => post("/shopping/purchased", token, { key, ...options });
export const undoShoppingAction = (token, undo) => post("/shopping/undo", token, undo);

export const upsertInventoryItem = (token, item) => post("/inventory/item", token, item);
export const adjustInventory = (token, key, delta) => post("/inventory/adjust", token, { key, delta });
export const removeInventoryItem = (token, key) => post("/inventory/remove", token, { key });

export const saveHouseholdDoc = (token, doc, body, meta = {}) => post("/doc", token, { doc, body, ...meta });

export const fetchNotifications = token => get("/notifications", token);
export const saveNotificationPrefs = (token, preferences) => post("/notifications/prefs", token, { preferences });
export const registerDevice = (token, deviceToken, platform) => post("/notifications/device", token, { token: deviceToken, platform });
