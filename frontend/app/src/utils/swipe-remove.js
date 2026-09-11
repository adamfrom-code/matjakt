// G5: "ta bort" ur tumzonen.
//
// Krysset låg inne i varuraden, 30x30 px, intill priset och intill "Köpt" -
// alltså i exakt den zon tummen träffar när den siktar på något annat. Ett
// feltryck tog bort varan ur listan, mitt i butiken, med varorna i handen.
//
// Nu tar ett SVEP VÄNSTER bort raden, och Ångra ligger i toasten. Krysset
// finns kvar i DOM:en utanför radens högerkant: nåbart med tangentbord och
// skärmläsare (CSS:en visar det vid fokus), men inte i vägen för tummen.
//
// Modulen känner varken till appens tillstånd eller till DOM-strukturen: den
// får veta hur en rad hittas och vad som ska hända när svepet är fullbordat.

/** Hur långt svepet måste gå innan det räknas som ett borttag. */
export const TRÖSKEL_PX = 64;

/** Hur mycket mer vågrätt än lodrätt rörelsen måste vara för att inte vara en skrollning. */
export const LUTNING = 1.4;

/** Hur många pixlar som får passera innan riktningen avgörs. */
const RIKTNINGSGRÄNS = 8;

/**
 * Ren beslutsfunktion: är rörelsen ett borttagssvep?
 * Åt höger är det inte. Kortare än tröskeln är det inte. Och en rörelse som
 * är lika mycket lodrät som vågrät är en skrollning, inte ett svep - den
 * gränsen är hela skillnaden mellan en gest och en olycka.
 */
export function ärBorttagssvep(dx, dy, { tröskel = TRÖSKEL_PX, lutning = LUTNING } = {}) {
  if (dx > -tröskel) return false;
  return Math.abs(dx) > Math.abs(dy) * lutning;
}

/**
 * Kopplar svep-för-att-ta-bort på en behållare. Delegerat: behållaren byts
 * aldrig ut när listan ritas om, så lyssnaren överlever varje omritning.
 *
 * @param {EventTarget} behållare  elementet listan ritas i
 * @param {(mål:any)=>any} väljRad  ger raden för ett träffat element, eller null
 * @param {(rad:any)=>void} taBort  körs när svepet är fullbordat
 * @returns {() => void} avkoppling
 */
export function kopplaSvepBort(behållare, { väljRad, taBort } = {}) {
  if (!behållare?.addEventListener || typeof väljRad !== "function" || typeof taBort !== "function") {
    return () => {};
  }
  let svep = null;

  const nollställ = () => {
    if (svep?.rad?.style) { svep.rad.style.transform = ""; svep.rad.style.transition = ""; }
    svep = null;
  };

  const ned = (e) => {
    if (e.pointerType === "mouse") return;      // en mus sveper inte, den klickar
    const rad = väljRad(e.target);
    if (!rad) return;
    svep = { x: e.clientX, y: e.clientY, rad, vågrätt: null };
  };

  const rör = (e) => {
    if (!svep) return;
    const dx = e.clientX - svep.x;
    const dy = e.clientY - svep.y;
    if (svep.vågrätt === null) {
      if (Math.abs(dx) < RIKTNINGSGRÄNS && Math.abs(dy) < RIKTNINGSGRÄNS) return;
      svep.vågrätt = Math.abs(dx) > Math.abs(dy) * LUTNING;
      if (!svep.vågrätt) { nollställ(); return; }   // användaren skrollar
    }
    if (!svep.rad.style) return;
    svep.rad.style.transition = "none";
    svep.rad.style.transform = `translateX(${Math.min(0, dx)}px)`;
  };

  const upp = (e) => {
    if (!svep) return;
    const { x, y, rad } = svep;
    nollställ();
    if (ärBorttagssvep(e.clientX - x, e.clientY - y)) taBort(rad);
  };

  behållare.addEventListener("pointerdown", ned, { passive: true });
  behållare.addEventListener("pointermove", rör, { passive: true });
  behållare.addEventListener("pointerup", upp, { passive: true });
  behållare.addEventListener("pointercancel", nollställ, { passive: true });

  return () => {
    behållare.removeEventListener?.("pointerdown", ned);
    behållare.removeEventListener?.("pointermove", rör);
    behållare.removeEventListener?.("pointerup", upp);
    behållare.removeEventListener?.("pointercancel", nollställ);
  };
}
