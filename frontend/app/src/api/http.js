import { API_BASE_URL } from "./config.js";

/**
 * Delad HTTP-klient för konto-, auth- och hushållsanropen (E6 + E7).
 *
 * E6 - varje anrop får en tidsgräns. Prisanropen hade AbortSignal.timeout
 * sedan tidigare; auth.js och household.js hade ingenting alls. Ett anrop
 * som aldrig svarar på ett dåligt mobilnät hänger tills operativsystemet
 * tröttnar, och eftersom refreshUser() awaitar fetchCurrentUser INNAN
 * renderAccount(), loadHousehold() och loadNotifications() fryser ett enda
 * hängande anrop hela kontoinitieringen för resten av sessionen.
 *
 * E7 - felet som når skärmen är på svenska. Går nätet ner kastar fetch en
 * TypeError, och den skrevs rakt in i #loginError: användaren läste
 * "Failed to fetch" i en svensk app. Därför bär varje fel härifrån en
 * färdig svensk `message`. Den som vill växla på ORSAK läser `status`,
 * `code` eller `kind` - aldrig texten.
 */

/** Så länge väntar vi innan ett anrop räknas som obesvarat. */
export const REQUEST_TIMEOUT_MS = 15000;

export const NETWORK_ERROR_TEXT = "Ingen kontakt med Matjakt. Kolla nätet och försök igen.";
export const TIMEOUT_ERROR_TEXT = "Matjakt svarade inte i tid. Kolla nätet och försök igen.";
export const SERVER_ERROR_TEXT = "Något gick fel hos oss. Försök igen om en stund.";

/**
 * iOS 15 (Capacitors deployment target) saknar AbortSignal.timeout. Modulen
 * bär sin egen reserv i stället för att lita på att app.js hunnit polyfilla:
 * i ESM körs importerade moduler före importörens kropp.
 */
function timeoutSignal(ms) {
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    return AbortSignal.timeout(ms);
  }
  const controller = new AbortController();
  setTimeout(() => controller.abort(new DOMException("TimeoutError", "TimeoutError")), ms);
  return controller.signal;
}

/** Ett avbrott härifrån kan bara komma från vår egen tidsgräns. */
function isTimeout(error) {
  return error?.name === "TimeoutError" || error?.name === "AbortError";
}

/**
 * Ett fetch-fel som aldrig nådde servern. Webbläsarna är oense om texten -
 * Chrome säger "Failed to fetch", Firefox "NetworkError when attempting to
 * fetch resource", Safari "Load failed" - men alla kastar TypeError.
 */
function isNetworkFailure(error) {
  if (!error) return false;
  if (error.name === "TypeError") return true;
  return /failed to fetch|networkerror|load failed|network request failed/i.test(error.message || "");
}

function statusText(status) {
  if (status === 401 || status === 403) return "Du är inte inloggad längre. Logga in igen.";
  if (status === 429) return "För många försök. Vänta en stund och försök igen.";
  if (status >= 500) return SERVER_ERROR_TEXT;
  return `Något gick fel. Försök igen. (fel ${status})`;
}

/**
 * Den svenska texten för ett fel, oavsett var det kom ifrån. Fel som gått
 * genom request() har redan rätt message; den här funktionen finns för
 * anropsställen som kan få ett rått fel från något annat håll - och som
 * annars skulle visa "Failed to fetch".
 */
export function errorText(error) {
  if (!error) return SERVER_ERROR_TEXT;
  if (error.kind === "timeout") return TIMEOUT_ERROR_TEXT;
  if (error.kind === "network") return NETWORK_ERROR_TEXT;
  if (isTimeout(error)) return TIMEOUT_ERROR_TEXT;
  if (isNetworkFailure(error)) return NETWORK_ERROR_TEXT;
  return error.message || SERVER_ERROR_TEXT;
}

/**
 * Ett anrop mot Matjakts API.
 *
 * @param {string} path      Sökväg under API-basen, t.ex. "/auth/login".
 * @param {object} [options]
 * @param {string} [options.method]     Standard "GET".
 * @param {string|null} [options.token] Bearer-token, utelämnas om null.
 * @param {object} [options.body]       Skickas som JSON. Utelämnad = ingen kropp.
 * @param {number} [options.timeout]    Millisekunder. 0 = ingen tidsgräns.
 * @param {boolean} [options.keepalive] Anropet får överleva att sidan stängs.
 * @returns {Promise<object>} Svarets JSON.
 */
export async function request(path, options = {}) {
  const { method = "GET", token = null, body, keepalive = false } = options;
  // En keepalive-begäran är avsiktligt långlivad: den skickas från pagehide
  // och ska överleva sidan. En tidsgräns som hänger i det döende dokumentet
  // hör inte hemma där, så den stängs av om inte anroparen ber om en.
  const timeout = options.timeout ?? (keepalive ? 0 : REQUEST_TIMEOUT_MS);

  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const init = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  if (keepalive) init.keepalive = true;
  if (timeout > 0) init.signal = timeoutSignal(timeout);

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch (error) {
    if (isTimeout(error)) {
      throw Object.assign(new Error(TIMEOUT_ERROR_TEXT), { kind: "timeout", timeout, cause: error });
    }
    throw Object.assign(new Error(NETWORK_ERROR_TEXT), { kind: "network", cause: error });
  }

  const data = await response.json().catch(() => ({}));
  // status + code följer med så UI:t kan växla på orsak, inte på text.
  // refreshUser() loggar ut på just 401 och får inte förlora den.
  if (!response.ok) {
    throw Object.assign(new Error(data.error || statusText(response.status)), {
      status: response.status,
      code: data.code,
      kind: "http",
    });
  }
  return data;
}
