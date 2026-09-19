// W1 · FAMILJEPULS - hushållets senaste händelser som en läsbar lista.
//
// Roadmapens W: substratet fanns (household_events: typ, aktör, tid), inget
// visade det. Modulen gör markup av serverns händelser (GET
// /api/household/events) - ren, utan DOM, prövad i node. Vem som gjorde
// vad, och när: "Sara lade till Mjölk · för 2 h sedan". Aldrig e-post -
// servern skickar visningsnamn eller null.
import { escapeHtml } from "../utils/html.js";

// Händelsetyp -> mening. Okända typer får en läsbar reserv (understreck
// blir mellanslag), aldrig ett fel och aldrig ett tomt kort.
const TEXT = {
  "household.shopping_item_added": (p) => `lade till ${p.name || p.subject || "en vara"}`,
  "household.shopping_item_purchased": (p) => `köpte ${p.name || p.subject || "en vara"}`,
  "household.shopping_item_at_home": (p) => `har ${p.name || p.subject || "en vara"} hemma`,
  "household.inventory_changed": () => "ändrade i skafferiet",
  "household.member_joined": () => "gick med i hushållet",
  "household.week_changed": () => "ändrade veckan",
};

export function handelseText(event) {
  const p = event?.payload || {};
  const fn = TEXT[event?.type];
  if (fn) return fn(p);
  const subject = p.subject || p.name;
  const bas = String(event?.type || "").replace(/^household\./, "").replace(/_/g, " ").trim() || "gjorde något";
  return subject ? `${bas}: ${subject}` : bas;
}

/** "nyss", "för 5 min sedan", "för 2 h sedan", "för 3 dagar sedan" - eller datumet. */
export function relativTid(iso, now = Date.now()) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return "nyss";
  const min = Math.round(s / 60);
  if (min < 60) return `för ${min} min sedan`;
  const h = Math.round(min / 60);
  if (h < 24) return `för ${h} h sedan`;
  const d = Math.round(h / 24);
  if (d < 14) return `för ${d} ${d === 1 ? "dag" : "dagar"} sedan`;
  return new Date(t).toLocaleDateString("sv-SE");
}

export function pulsMarkup(events, { now = Date.now() } = {}) {
  const lista = Array.isArray(events) ? events : [];
  if (!lista.length) return `<p class="household-puls-tom">Inget har hänt i hushållet än.</p>`;
  return `<ul class="household-puls">` + lista.map(e => {
    const vem = e.isMe ? "Du" : (e.actor || "Någon");
    return `<li><strong>${escapeHtml(vem)}</strong> ${escapeHtml(handelseText(e))}`
      + `<small>${escapeHtml(relativTid(e.createdAt, now))}</small></li>`;
  }).join("") + `</ul>`;
}
