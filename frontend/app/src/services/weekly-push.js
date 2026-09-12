// ---------------------------------------------------------------------------
// H1: VECKONOTISEN PÅ KLIENTEN
//
// En notis är push till någons telefon. Den här modulen finns för att hålla
// isär tre saker som är lätta att blanda ihop, och som blir obehagliga när
// de blandas:
//
//   1. VAD ANVÄNDAREN BAD OM   notification_prefs.week ("Ny vecka")
//   2. VAD WEBBLÄSAREN TILLÅTER Notification.permission
//   3. VAD SERVERN KAN GÖRA    finns det ett VAPID-nyckelpar?
//
// Ett ja på (2) är inte ett ja på (1). Att webbläsaren tillåter notiser
// betyder att den inte hindrar dem - inte att någon bett om en påminnelse
// varje söndag. Därför prenumereras det ALDRIG på enbart ett tillstånd:
// `wantsWeek` måste vara sant, och det värdet kommer ur samma
// notification_prefs som hushållsnotiserna. Inget andra system bredvid.
//
// OCH ETT NEJ FRÅGAS ALDRIG OM IGEN. `prompt` är false överallt utom i det
// enda anropet som kommer ur ett tryck på "Ny vecka". En bakgrundssynk som
// råkar fråga varje söndag är precis den sortens app folk stänger av notiser
// för - och `Notification.permission === "denied"` är permanent: då görs
// ingenting alls, för alltid, tills användaren själv ändrar det i
// webbläsarens inställningar.
//
// Utan en publik VAPID-nyckel händer ingenting och ingen ser en dialog.
// Fail closed: notisen uteblir, appen märks inte av det.
// ---------------------------------------------------------------------------

// Varför varje väg tog slut. Bara till loggning och test - ingen av dem
// visas för en användare, för ingen av dem är något användaren kan göra
// något åt just då.
export const PUSH_NO_KEY = "nyckel-saknas";
export const PUSH_UNSUPPORTED = "stods-inte";
export const PUSH_DENIED = "nekad";
export const PUSH_NOT_ASKED = "ej-fragad";
export const PUSH_OFF = "avstangd";
export const PUSH_OK = "ok";

/** `?notis=<vad>` ur en adress. Tom sträng när det inte står något. */
export function notificationIntent(href) {
  try {
    return new URL(href).searchParams.get("notis") || "";
  } catch {
    return "";
  }
}

/**
 * VAPID-nyckeln som webbläsaren vill ha den: råa byte, inte base64url.
 * `applicationServerKey` tar en BufferSource, och en sträng där ger
 * "InvalidCharacterError" i Chrome och tystnad i Safari.
 */
export function applicationServerKey(base64url, scope = globalThis) {
  const padded = String(base64url || "").replace(/-/g, "+").replace(/_/g, "/");
  const binary = scope.atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

/**
 * Kan den här webbläsaren ta emot push överhuvudtaget?
 *
 * iOS är hela anledningen till att frågan ställs så här och inte som
 * "är det Safari?": iOS 16.4+ HAR Web Push, men bara för en PWA som lagts
 * till på hemskärmen. I Safari-fliken saknas PushManager helt. Att fråga
 * efter förmågan i stället för efter webbläsaren gör att båda fallen
 * hamnar rätt utan en enda User-Agent-sträng.
 */
export function pushSupported(scope = globalThis) {
  return Boolean(scope && scope.navigator && scope.navigator.serviceWorker
    && scope.PushManager && scope.Notification);
}

async function permissionFor(scope, prompt) {
  const current = scope.Notification.permission;
  if (current === "granted") return "granted";
  if (current === "denied") return "denied";
  if (!prompt) return "default";
  try {
    return await scope.Notification.requestPermission();
  } catch {
    return "denied";
  }
}

/**
 * Ställer prenumerationen i linje med vad användaren bett om.
 *
 * @param {object}   options
 * @param {object}   options.scope      window (injicerat för testbarhet)
 * @param {string}   options.publicKey  serverns publika VAPID-nyckel, "" = av
 * @param {boolean}  options.wantsWeek  notification_prefs.week
 * @param {Function} options.save       (json, platform) => Promise, till servern
 * @param {Function} options.forget     (endpoint) => Promise, till servern
 * @param {boolean}  options.prompt     får vi visa tillståndsdialogen?
 * @returns {Promise<{ok: boolean, reason: string}>}
 */
export async function syncWeeklyPush({ scope = globalThis, publicKey = "", wantsWeek = false,
                                       save, forget, prompt = false, platform = "web" } = {}) {
  if (!pushSupported(scope)) return { ok: false, reason: PUSH_UNSUPPORTED };
  // AVSTÄNGT GÅR FÖRE ALLT. Den som just slog av "Ny vecka" ska bli av med
  // sin prenumeration även om nyckeln försvunnit ur servern under tiden -
  // annars ligger en tyst prenumeration kvar och väcks den dag nyckeln
  // kommer tillbaka.
  if (!wantsWeek) {
    await dropSubscription(scope, forget);
    return { ok: false, reason: PUSH_OFF };
  }
  if (!publicKey) return { ok: false, reason: PUSH_NO_KEY };

  const permission = await permissionFor(scope, prompt);
  if (permission === "denied") return { ok: false, reason: PUSH_DENIED };
  if (permission !== "granted") return { ok: false, reason: PUSH_NOT_ASKED };

  const registration = await scope.navigator.serviceWorker.ready;
  const manager = registration && registration.pushManager;
  if (!manager) return { ok: false, reason: PUSH_UNSUPPORTED };
  // En befintlig prenumeration återanvänds. Att avregistrera och registrera
  // om varje gång appen startar hade gett servern en ny endpoint per start
  // och en tabell full av döda rader.
  let subscription = await manager.getSubscription();
  if (!subscription) {
    subscription = await manager.subscribe({
      // userVisibleOnly är inte valfritt i Chrome: en push som INTE visar
      // något för användaren är precis det webbläsarna byggde kravet mot.
      userVisibleOnly: true,
      applicationServerKey: applicationServerKey(publicKey, scope),
    });
  }
  await save(subscription.toJSON(), platform);
  return { ok: true, reason: PUSH_OK };
}

async function dropSubscription(scope, forget) {
  try {
    const registration = await scope.navigator.serviceWorker.ready;
    const subscription = registration && registration.pushManager
      && await registration.pushManager.getSubscription();
    if (!subscription) return;
    // Servern först. Lyckas webbläsarens unsubscribe men inte vårt anrop
    // fortsätter servern skicka till en endpoint som inte finns - och det
    // enda som märks är ett fel i loggen varje söndag.
    if (forget) await forget(subscription.endpoint);
    await subscription.unsubscribe();
  } catch {
    /* en webbläsare utan prenumeration att säga upp är redan i mål */
  }
}
