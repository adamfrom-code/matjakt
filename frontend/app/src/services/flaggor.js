// FUNKTIONSFLAGGOR - för det som inte är färdigverifierat (masterordern §16:
// ingen 2.0-funktion får riskera releasebygget).
//
// Alla flaggor är AV i FLAGGOR. En flagga slås på per webbläsare (för
// utveckling, test och en tidig hushållskrets), aldrig för alla:
//   localStorage "matjakt.flaggor" = {"hushall.medlemmar": true}
//   eller ?flagga=hushall.medlemmar,vecka.narvaro i adressen (sparas inte)
// Att slå på en flagga för alla är en kodändring: standardvärdet här byts,
// med test, i ett eget paket.

export const FLAGGOR = Object.freeze({
  "hushall.medlemmar": false,   // S: personer härleds ur medlemmarna (kind + portionsfaktor)
  "vecka.narvaro": false,       // T: vem äter hemma, per dag
  "vecka.rester": false,        // AA: rester som middag
  "vecka.flytta": false,        // Y: flytta en middag till en annan dag
  "hushall.puls": false,        // W: familjepulsen - vem gjorde vad, när
  "planering.barn": false,      // U: barnvänliga rätter väger tyngre när hushållet har barn
  "skafferi.laga-nu": false,    // Z2: "Laga med det jag har" frågar banken med kanoniska alias + tid
});

const NYCKEL = "matjakt.flaggor";

function lasLagrade(storage) {
  try {
    const raw = storage?.getItem?.(NYCKEL);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function lasUrl(search) {
  const ut = {};
  try {
    const params = new URLSearchParams(search || "");
    for (const namn of (params.get("flagga") || "").split(",")) if (namn.trim()) ut[namn.trim()] = true;
  } catch { /* ingen URL - inga flaggor */ }
  return ut;
}

/**
 * Är flaggan på? Okända namn är alltid av - en felstavning kan inte slå på
 * något, och ett namn som tagits bort ur FLAGGOR slutar gälla samma sekund.
 */
export function flagga(namn, { storage = globalThis.localStorage, search = globalThis.location?.search } = {}) {
  if (!(namn in FLAGGOR)) return false;
  const url = lasUrl(search);
  if (namn in url) return true;
  const lagrade = lasLagrade(storage);
  if (namn in lagrade) return Boolean(lagrade[namn]);
  return FLAGGOR[namn];
}
