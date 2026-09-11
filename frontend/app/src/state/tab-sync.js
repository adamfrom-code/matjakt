// ---------------------------------------------------------------------------
// TVÅ FLIKAR OM SAMMA VECKA
//
// Varje flik håller hela tillståndet i minnet och skriver HELA blobben vid
// varje saveState(). Bockar man av varor i flik A och byter recept i flik B
// skriver B:s blob över A:s bockningar - lokalt direkt, och med konto via den
// debouncade /account/state där sista skrivningen vinner. Ingenting i appen
// märkte det: det fanns inget `storage`-lyssnande någonstans i koden.
//
// Det här är INTE en sammanslagning. De två flikarna har ingen gemensam
// sanning att slås ihop mot, och att gissa vems bockning som "vann" vore
// värre än att säga som det är. Beskedet är hela åtgärden: den som får veta
// kan ladda om och se den senaste versionen, den som inte får veta tappar
// sin vecka tyst.
//
// `storage`-eventet fyras BARA i de andra flikarna på samma origin - aldrig i
// den som skrev. Varje event som når hit kommer alltså per definition från
// någon annan flik; det behövs ingen egen märkning av vem som skrev.
// ---------------------------------------------------------------------------

import { STORAGE_KEY } from "./storage.js";

export const OTHER_TAB_TEXT = "Matjakt är öppen i en annan flik - ladda om för att se den senaste versionen.";

// En annan flik som sparar gör det ofta: varje kryss i Handla, varje steg i
// skafferiet, varje tangenttryck i budgeten. Beskedet ska komma fram en gång,
// inte hamra en gång per skrivning.
export const OTHER_TAB_QUIET_MS = 30000;

export function watchOtherTabs({ target, key = STORAGE_KEY, onOtherTab,
                                 quietMs = OTHER_TAB_QUIET_MS,
                                 now = () => Date.now() } = {}) {
  if (!target?.addEventListener || typeof onOtherTab !== "function") return () => {};
  let toldAt = null;
  const handler = event => {
    // key === null betyder att en annan flik körde storage.clear(): då är
    // allt borta, inte bara vår nyckel. Alla andra nycklar (t.ex. token) är
    // inte veckan och angår inte det här beskedet.
    if (event.key != null && event.key !== key) return;
    // Samma blob igen är ingen ändring. En flik som just hämtat kontots
    // tillstånd skriver ofta tillbaka exakt det som redan står i lagringen,
    // och det är inget att varna för.
    if (event.key != null && event.newValue === event.oldValue) return;
    const at = now();
    if (toldAt !== null && at - toldAt < quietMs) return;
    toldAt = at;
    onOtherTab(OTHER_TAB_TEXT);
  };
  target.addEventListener("storage", handler);
  return () => target.removeEventListener("storage", handler);
}
