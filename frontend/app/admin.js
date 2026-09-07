// Kontrollrummets skript. Ligger i en egen fil för att serverns
// Content-Security-Policy (script-src 'self') blockerar inline-skript -
// admin-sidan serveras av backend-servern själv, inte av GitHub Pages.
const API = document.querySelector('meta[name="matjakt-api-url"]')?.content?.trim() || "/api";
// In memory only, deliberately - see the note in the markup.
let token = "";
let timer = null;

const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function ago(seconds) {
  if (seconds == null) return "—";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min sedan`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h sedan` : `${Math.round(hours / 24)} dygn sedan`;
}

function when(value) {
  return value ? new Date(value * 1000).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" }) : "—";
}

// Status is a claim about whether we can collect, not about whether the data
// is good - a blocked chain can still be serving a perfectly good import from
// two days ago, so the two are shown side by side rather than merged.
// Driftstatusen svarar på "behöver jag göra något?". Den är avsiktligt
// konservativ: okänt underlag ger aldrig grönt, och "released" är en flagga
// - inte ett friskhetsbesked. En publik kedja kan mycket väl vara stale.
const HEALTH_CLASS = {
  healthy: "ok", ready_for_release: "warn", stale: "warn",
  failed: "bad", limited: "off", never_imported: "off",
};
const HEALTH_LABEL = {
  healthy: "Frisk", ready_for_release: "Redo att släppas", stale: "Inaktuell",
  failed: "Trasig", limited: "Begränsad", never_imported: "Aldrig importerad",
};

const STATUS_CLASS = {
  working: "ok",
  working_but_unreliable: "warn",
  working_but_rate_limited: "warn",
  blocked_requires_vendor_credential: "bad",
  not_available_no_public_prices: "off",
};

async function call(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { "X-Admin-Token": token, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  // Servern svarar 404 på fel token (enhetligt med okänd väg) - 403 fanns förr.
  if (response.status === 403 || response.status === 404) throw new Error("Fel admin-token (servern svarar 404)");
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${response.status}`);
  }
  return response.json();
}

async function refresh() {
  const data = await call("/admin/grocery-import");
  renderImport(data.import);
  // Driftstatusen får inte falla om health gör det - och ska då visa att
  // den inte kunde läsas, inte tyst se frisk ut.
  let health = null;
  try { health = await (await fetch(`${API}/health`)).json(); } catch { /* visas som okänt */ }
  renderOps(health, data.providers);
  renderChains(data.providers, data.scheduler);
  renderScheduler(data.scheduler);
  // Kontrollrummet får inte falla om prisdatan gör det, och tvärtom.
  try { renderInsights(await call("/admin/insights")); }
  catch (error) { $("totals").innerHTML = `<p class="note">Kunde inte läsa tratten: ${esc(error.message)}</p>`; }
}

function renderInsights(data) {
  const t = data.tratt?.totalt || {};
  const stat = (value, label) => `<div class="stat"><b>${value ?? "—"}</b><span>${label}</span></div>`;
  $("totals").innerHTML =
    stat(t.registrerade, "konton totalt") +
    stat(t.registreradeSenaste7Dagarna, "nya senaste 7 dagarna") +
    stat(t.aktivaSenaste7Dagarna, "aktiva senaste 7 dagarna") +
    stat(t.aktivaSenaste28Dagarna, "aktiva senaste 28 dagarna") +
    stat(t.premium, "Premium");

  const cohorts = data.tratt?.kohorter || [];
  const pct = (part, whole) => whole ? ` <span class="quiet">(${Math.round(100 * part / whole)}%)</span>` : "";
  $("cohorts").querySelector("tbody").innerHTML = cohorts.length ? cohorts.map(c => `<tr>
      <td><strong>${esc(c.vecka)}</strong>${c.mogen ? "" : ` <span class="pill warn">ofullständig</span>`}</td>
      <td>${c.registrerade}</td>
      <td>${c.skapadeVecka}${pct(c.skapadeVecka, c.registrerade)}</td>
      <td>${c.tillbakaEfter7Dagar}${pct(c.tillbakaEfter7Dagar, c.registrerade)}</td>
      <td>${c.premium}${pct(c.premium, c.registrerade)}</td>
    </tr>`).join("") : `<tr><td colspan="5" class="wrap">Inga registreringar de senaste åtta veckorna.</td></tr>`;
  const defs = data.tratt?.definitioner || {};
  $("cohortNote").textContent = `"Ofullständig" = ${defs.mogen || "alla har inte haft sju dagar på sig än"}.`;

  const days = data.handelser?.dagar || [];
  const events = Object.entries(data.handelser?.events || {})
    .sort((a, b) => b[1].total - a[1].total);
  const peak = Math.max(1, ...events.flatMap(([, e]) => days.map(d => e.perDag[d] || 0)));
  $("events").querySelector("tbody").innerHTML = events.map(([name, e]) => `<tr>
      <td>${esc(name)}</td>
      <td>${e.total}</td>
      <td>${e.unikaKonton}</td>
      <td><span class="bars" title="${esc(days.map(d => `${d}: ${e.perDag[d] || 0}`).join("\n"))}">${
        days.map(d => `<i style="height:${Math.max(1, Math.round(16 * (e.perDag[d] || 0) / peak))}px"></i>`).join("")
      }</span></td>
    </tr>`).join("");

  const mail = data.utskick || {};
  const sent = mail.skickadeSenaste30Dagarna || {};
  const who = mail.mottagare || {};
  $("mailings").innerHTML =
    `<span class="pill ${mail.blockerat ? "off" : "ok"}">${mail.blockerat ? "av" : "på"}</span> ` +
    (mail.blockerat ? esc(mail.blockerat) + ". " : `Skickas kl. ${esc(mail.skickasKl)} (${esc(mail.timezone)}), Kampanjtorget på ${esc(mail.kampanjtorgetDag)}. `) +
    `<br>Tackat ja: ${who.tackatJa ?? "—"}, varav verifierade (får utskick): ${who.tackatJaOchVerifierade ?? "—"}.` +
    `<br>Senaste 30 dagarna: välkommen dag 3 ${sent.welcome_3 ?? 0}, dag 7 ${sent.welcome_7 ?? 0}, Kampanjtorget ${sent.kampanjtorget ?? 0}.` +
    (mail.senasteKorning ? `<br>Senaste körning ${esc(mail.senasteKorning.dag)}: ${esc(JSON.stringify(mail.senasteKorning.skickat))}` +
      (mail.senasteKorning.blockerat ? ` (blockerat: ${esc(mail.senasteKorning.blockerat)})` : "") : "");

  const feedback = data.feedback || [];
  $("feedback").innerHTML = feedback.length
    ? feedback.map(f => `<li><span class="quiet">${esc((f.createdAt || "").slice(0, 16).replace("T", " "))} · ${esc(f.screen || "")}</span><br>${esc(f.text)}</li>`).join("")
    : `<li class="quiet">Ingen feedback ännu.</li>`;
}

function renderImport(state) {
  const busy = state.running;
  if (busy) {
    const done = state.categoriesDone, total = state.categoriesTotal;
    $("importProgress").hidden = !total;
    $("importProgress").max = total || 100;
    $("importProgress").value = done || 0;
    $("importStatus").innerHTML =
      `<strong>${esc(state.chain)}</strong> kör &mdash; ${done}/${total || "?"} kategorier, ` +
      `${state.productsSaved} produkter sparade, ${Math.round(state.elapsedSeconds || 0)} s.<br>` +
      `<span style="color:var(--muted)">${esc(state.currentCategory || "")}</span>`;
  } else {
    $("importProgress").hidden = true;
    $("importStatus").textContent = state.status === "idle"
      ? "Ingen import kör."
      : `Senaste: ${state.chain} — ${state.status}, ${state.productsSaved} produkter` +
        (state.message ? ` (${state.message})` : "");
  }
  document.querySelectorAll("[data-import]").forEach(button => { button.disabled = busy; });
}

function healthPill(health) {
  if (!health) return `<span class="pill off">okänt</span>`;
  const ålder = health.ageHours == null ? "" :
    ` <span class="quiet">${health.ageHours} h</span>`;
  return `<span class="pill ${HEALTH_CLASS[health.status] || "off"}">` +
         `${esc(HEALTH_LABEL[health.status] || health.status)}</span>${ålder}`;
}

// Ett systemkort. "okänt" är ett eget läge, aldrig grönt: ett kort som inte
// kunde läsas får inte se friskt ut bara för att inget fel rapporterades.
function opsCard(label, klass, värde, detalj) {
  return `<div class="stat"><span class="pill ${klass}">${esc(värde)}</span>` +
         `<span style="display:block;margin-top:.35rem">${esc(label)}</span>` +
         `<span>${esc(detalj || "")}</span></div>`;
}

function renderOps(health, providers) {
  const nu = new Date().toLocaleTimeString("sv-SE", { timeStyle: "short" });
  $("opsCheckedAt").textContent = `kontrollerad ${nu}`;

  if (!health) {
    $("opsSummary").textContent = "Kunde inte läsa driftstatus";
    $("opsSystems").innerHTML = opsCard("Backend", "bad", "svarar inte", "");
    return;
  }

  const kedjor = providers || [];
  const trasiga = kedjor.filter(p => p.health?.status === "failed");
  const inaktuella = kedjor.filter(p => p.health?.status === "stale");
  const behöverBlick = [...trasiga, ...inaktuella];

  // Sammanfattningen namnger antal och kedja, inte bara en färg - "1 kedja
  // behöver uppmärksamhet" utan att säga vilken tvingar fram ett klick.
  $("opsSummary").textContent = trasiga.length
    ? `Prisplattformen har problem: ${trasiga.map(p => p.chain).join(", ")}`
    : inaktuella.length
      ? `${inaktuella.length} kedja${inaktuella.length > 1 ? "r" : ""} behöver uppmärksamhet: ${inaktuella.map(p => p.chain).join(", ")}`
      : "Alla kontrollerade system fungerar";

  const audit = health.pricingAudit || {};
  const larm = health.adminAlerts || {};
  // Larmen är skarpa först när BÅDE mottagare och transport finns. Ett av
  // dem ensamt betyder tysta larm respektive larm som aldrig når fram.
  const larmSkarpa = larm.recipientConfigured && larm.transportConfigured;
  const larmText = larm.recipientConfigured === undefined ? "okänt"
    : larmSkarpa ? "aktiva"
    : larm.recipientConfigured ? "ingen SMTP"
    : "ingen mottagare";
  const släppta = kedjor.filter(p => p.health?.released);
  const friska = släppta.filter(p => p.health?.status === "healthy");

  $("opsSystems").innerHTML =
    opsCard("Backend", health.ok ? "ok" : "bad", health.ok ? "uppe" : "nere",
            health.commit ? `commit ${String(health.commit).slice(0, 7)}` : "commit okänd") +
    opsCard("Prisrevision", audit.gate === "GRÖN" ? "ok" : audit.gate ? "bad" : "off",
            audit.gate || "ingen data",
            audit.kontroller ? `${audit.kontroller} kontroller` : "inga kontroller") +
    opsCard("Släppta kedjor", friska.length === släppta.length && släppta.length ? "ok" : "warn",
            `${friska.length}/${släppta.length}`, "friska av släppta") +
    opsCard("Driftlarm", larmSkarpa ? "ok" : larm.recipientConfigured === undefined ? "off" : "warn",
            larmText, larm.recipientDomain ? `till ${larm.recipientDomain}` : "") +
    opsCard("Utgående mejl", health.mail ? "ok" : "warn", health.mail ? "konfigurerat" : "saknas",
            health.mailFrom ? `från ${health.mailFrom}` : "") +
    opsCard("Utvecklingslåset", health.gate ? "warn" : "ok", health.gate ? "på" : "av",
            health.gate ? "appen är inte öppen" : "appen är öppen");

  $("opsAttention").innerHTML = behöverBlick.length
    ? `<p class="note" style="margin-top:.8rem"><strong>Behöver uppmärksamhet:</strong> ` +
      behöverBlick.map(p => `${esc(p.chain)} &mdash; ${esc(p.health.reason || p.health.status)}`).join(" · ") +
      `</p>`
    : "";
}

function renderChains(providers, scheduler) {
  const next = Object.fromEntries((scheduler.schedule || []).map(entry => [entry.chain, entry]));
  $("chains").querySelector("tbody").innerHTML = providers.map(provider => {
    const nightly = next[provider.chain];
    const blocked = scheduler.notScheduled?.[provider.chain];
    const action = provider.collectable || provider.chain === "ICA"
      ? `<button data-import="${esc(provider.chain)}">${provider.chain === "ICA" ? "Uppdatera manuellt" : "Starta import"}</button>`
      : "—";
    const last = provider.lastRun, success = provider.lastSuccessfulRun;
    return `<tr>
      <td><strong>${esc(provider.chain)}</strong></td>
      <td>${healthPill(provider.health)}</td>
      <td>${provider.health?.released ? "JA" : `<span class="quiet">nej</span>`}</td>
      <td><span class="pill ${STATUS_CLASS[provider.status] || "off"}">${esc(provider.status)}</span></td>
      <td>${provider.products}</td>
      <td>${provider.prices}</td>
      <td>${provider.gtinPercent}%</td>
      <td>${provider.imagePercent}%</td>
      <td>${provider.categoryPercent}%</td>
      <td>${success ? when(success.finishedAt) : "—"}</td>
      <td>${last ? `${esc(last.status)} · ${when(last.finishedAt || last.startedAt)}` : "—"}</td>
      <td>${nightly ? esc(nightly.time) : `<span style="color:var(--muted)">ingen</span>`}</td>
      <td>${action}</td>
    </tr>${last?.errorMessage ? `<tr><td colspan="13" class="wrap">⚠ ${esc(last.errorMessage)}</td></tr>` : ""}
    ${blocked ? `<tr><td colspan="13" class="wrap">Ingen nattkörning: ${esc(blocked)}</td></tr>` : ""}`;
  }).join("");

  $("chainNotes").innerHTML = providers
    .map(provider => `<p class="note"><strong>${esc(provider.chain)}:</strong> ${esc(provider.note)}</p>`)
    .join("");

  document.querySelectorAll("[data-import]").forEach(button =>
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const result = await call("/admin/grocery-import", {
          method: "POST", body: JSON.stringify({ chain: button.dataset.import }),
        });
        // "already_running" is not an error - one import at a time is the
        // design, so say so plainly instead of showing a failure.
        if (!result.started) alert(result.reason === "already_running"
          ? "En import kör redan. Bara en åt gången."
          : `Kunde inte starta: ${result.reason}`);
        await refresh();
      } catch (error) {
        alert(error.message);
        button.disabled = false;
      }
    }));
}

function renderScheduler(scheduler) {
  const rows = (scheduler.schedule || [])
    .map(entry => `${esc(entry.chain)} kl. ${esc(entry.time)} (nästa ${when(Date.parse(entry.nextRunAt) / 1000)})`)
    .join("<br>");
  $("scheduler").innerHTML =
    `<span class="pill ${scheduler.enabled ? "ok" : "off"}">${scheduler.enabled ? "på" : "av"}</span> ` +
    `Tidszon ${esc(scheduler.timezone)}.<br>${rows || "Inget schema."}` +
    `<p class="note">Slås på med <code>MATJAKT_GROCERY_SCHEDULE_ENABLED=1</code>, ` +
    `tider via <code>MATJAKT_GROCERY_SCHEDULE</code>.</p>`;
}

$("connect").addEventListener("click", async () => {
  token = $("token").value.trim();
  $("authError").textContent = "";
  try {
    await refresh();
    $("authCard").hidden = true;
    $("panel").hidden = false;
    // Poll while an import is running so progress is actually visible.
    timer = setInterval(() => refresh().catch(() => {}), 5000);
  } catch (error) {
    token = "";
    $("authError").textContent = error.message;
  }
});
$("previewMailing").addEventListener("click", async () => {
  $("mailingResult").textContent = "Skickar…";
  try {
    const result = await call("/admin/mailing", { method: "POST", body: JSON.stringify({
      action: "preview", kind: $("previewKind").value, email: $("previewEmail").value.trim() }) });
    $("mailingResult").textContent = `Skickat: "${result.subject}"`;
  } catch (error) { $("mailingResult").textContent = error.message; }
});
$("runMailings").addEventListener("click", async () => {
  $("mailingResult").textContent = "Kör…";
  try {
    const result = await call("/admin/mailing", { method: "POST", body: JSON.stringify({ action: "run" }) });
    $("mailingResult").textContent = result.blockerat
      ? `Inget skickat: ${result.blockerat}`
      : `Skickat: ${JSON.stringify(result.skickat)}${Object.values(result.fel || {}).some(Boolean) ? `, fel: ${JSON.stringify(result.fel)}` : ""}`;
    await refresh();
  } catch (error) { $("mailingResult").textContent = error.message; }
});
$("token").addEventListener("keydown", event => { if (event.key === "Enter") $("connect").click(); });
$("refresh").addEventListener("click", () => refresh().catch(error => alert(error.message)));
window.addEventListener("beforeunload", () => clearInterval(timer));
