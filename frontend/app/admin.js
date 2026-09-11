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
// failing: senaste FÖRSÖKET misslyckades trots att det finns äldre godkänd
// data kvar. Röd, inte orange - kedjan uppdateras inte längre, och varje
// annan siffra på raden (produktantal, ålder) ser fortfarande normal ut.
const HEALTH_CLASS = {
  healthy: "ok", ready_for_release: "warn", stale: "warn",
  failed: "bad", failing: "bad", limited: "off", never_imported: "off",
};
const HEALTH_LABEL = {
  healthy: "Frisk", ready_for_release: "Redo att släppas", stale: "Inaktuell",
  failed: "Trasig", failing: "Slutade uppdatera", limited: "Begränsad",
  never_imported: "Aldrig importerad",
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
  // Primat får inte fälla driftstatusen om den är långsam eller nere.
  let primat = null;
  try { primat = await call("/admin/primat-status"); } catch { /* visas som okänt */ }
  renderOps(health, data.providers, primat);
  renderChains(data.providers, data.scheduler);
  renderScheduler(data.scheduler);
  // O8: Primat visas ur sin egen endpoint - configured utan nyckeln, kvot
  // bara ur Primats egna siffror (GET /me), annars "Ej tillgängligt".
  try { renderPrimat(await call("/admin/primat-status")); }
  catch (error) { $("primatStatus").textContent = `Kunde inte läsa Primat: ${error.message}`; }
  // Incidenterna får inte falla med tratten, och tvärtom.
  try { renderIncidents(await call("/admin/incidents")); }
  catch (error) { $("incidentsActive").textContent = `Kunde inte läsa incidenter: ${error.message}`; }
  // Kontrollrummet får inte falla om prisdatan gör det, och tvärtom.
  try { renderInsights(await call("/admin/insights")); }
  catch (error) { $("totals").innerHTML = `<p class="note">Kunde inte läsa tratten: ${esc(error.message)}</p>`; }
}

// O5/O6. Mejlstatusen visas som den ÄR: sent, failed, not_configured,
// pending. En oklar JA-markering för ett försök som misslyckats vore en lögn
// i just den ruta ägaren tittar i när något är fel.
const MAIL_LABEL = { sent: "skickat", failed: "MISSLYCKADES", not_configured: "e-post ej konfigurerad", pending: "väntar" };
const mailPill = s => `<span class="pill ${s === "sent" ? "ok" : s === "failed" ? "bad" : "warn"}">${esc(MAIL_LABEL[s] || s || "—")}</span>`;
const varade = sek => sek == null ? "—" : sek < 3600 ? `${Math.round(sek / 60)} min` : sek < 172800 ? `${(sek / 3600).toFixed(1)} h` : `${(sek / 86400).toFixed(1)} dygn`;

// O8. Configured JA/NEJ ur serverns svar - nyckeln själv finns inte i svaret.
// Kvoten visas BARA om Primats /me svarat med den; vi räknar inte fram
// någon ur antalet importerade rader, och 20 000/100 000 ur gamla repo-
// anteckningar är inte bekräftad abonnemangsdata.
function renderPrimat(data) {
  const box = $("primatStatus");
  if (!data.configured) { box.innerHTML = `Nyckel: <span class="pill warn">NEJ</span> <span class="quiet">ICA- och Coop-importen kan inte köras utan den.</span>`; return; }
  const st = data.status || {};
  const rad = (k, v) => v == null ? "" : `<div class="stat"><b>${esc(v)}</b><span>${esc(k)}</span></div>`;
  const kvot = [rad("plan", st.plan), rad("rader använda i dag", st.rowsUsedToday ?? st.rows_used_today),
                rad("dygnsgräns", st.dailyRowLimit ?? st.daily_row_limit), rad("nollställs", st.resetsAt ?? st.resets_at)].join("");
  box.innerHTML = `Nyckel: <span class="pill ok">JA</span> ` +
    (data.error ? `<span class="pill bad">Primat svarade inte: ${esc(data.error)}</span>` :
     kvot ? `<div class="stats" style="margin-top:.5rem">${kvot}</div><p class="note">Siffrorna kommer från Primats eget /me-svar, inte från vår räkning.</p>`
          : `<span class="quiet">Kvot: Ej tillgängligt - /me svarade utan kvotfält.</span>`);
}

function renderIncidents(data) {
  const aktiva = data.active || [];
  $("incidentsActive").innerHTML = aktiva.length
    ? aktiva.map(a => `<div style="margin:.5rem 0;padding:.5rem .7rem;border:1px solid var(--line);border-radius:10px">
        <div class="row" style="justify-content:space-between"><strong>${esc(a.chain || "Primat")}</strong>
          <span>${mailPill(a.mail?.status)} <span class="quiet">${esc(a.ageHours)} h</span></span></div>
        <div><b>Vad är fel:</b> ${esc(a.vadArFel)}</div>
        <div><b>Påverkas kunder:</b> ${esc(a.paverkasKunder)}</div>
        <div><b>Vad göra:</b> ${esc(a.vadGora)}</div>
      </div>`).join("")
    : `Inga öppna incidenter. <span class="quiet">Larm dedupliceras per problem, ett kvitto vid återställning, cooldown ${Math.round((data.cooldownSeconds || 0) / 86400)} dygn.</span>`;
  $("incidentsHistory").querySelector("tbody").innerHTML = (data.history || []).map(h => `<tr>
    <td data-label="Start">${when(h.openedAt)}</td><td data-label="Löst">${when(h.recoveredAt)}</td><td data-label="Varade">${varade(h.durationSeconds)}</td>
    <td data-label="Kedja">${esc(h.chain || "Primat")}</td><td data-label="Vad" class="wrap">${esc(h.summary || h.title || h.key)}</td>
    <td data-label="Larm">${mailPill(h.mail?.opened)}</td><td data-label="Kvitto">${mailPill(h.mail?.recovered)}</td></tr>`).join("")
    || `<tr><td colspan="7" class="quiet">Ingen historik än</td></tr>`;
}

function renderInsights(data) {
  const t = data.tratt?.totalt || {};
  const stat = (value, label) => `<div class="stat"><b>${value ?? "—"}</b><span>${label}</span></div>`;
  $("totals").innerHTML =
    stat(t.registrerade, "konton totalt") +
    stat(t.registreradeSenaste7Dagarna, "nya senaste 7 dagarna") +
    stat(t.aktivaSenaste7Dagarna, "aktiva senaste 7 dagarna") +
    stat(t.aktivaSenaste28Dagarna, "aktiva senaste 28 dagarna") +
    // A01: BETALANDE FÖRST, och kompenserad för sig. Ett samlat "Premium"
    // svarar inte på frågan om affären bär - en inlöst kod och en betalande
    // prenumerant såg likadana ut, och det är den enda siffran här som
    // handlar om pengar. Ingen intäkt räknas fram; det här är konton.
    stat(t.premiumBetalande, "betalande Premium") +
    stat(t.premiumKompenserad, "kompenserad Premium") +
    stat(t.premiumProv, "Premium på prov") +
    stat(t.premium, "Premium totalt");

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
  // O4: orsaken följer med pillret. Limited ska inte larma, men den som
  // undrar VARFÖR Lidl är begränsad ska inte behöva gissa - orsaken finns
  // i API:t (health.reason) och visades förut ingenstans.
  const orsak = health.reason ? ` title="${esc(health.reason)}"` : "";
  return `<span class="pill ${HEALTH_CLASS[health.status] || "off"}"${orsak}>` +
         `${esc(HEALTH_LABEL[health.status] || health.status)}</span>${ålder}`;
}

// Ett systemkort. "okänt" är ett eget läge, aldrig grönt: ett kort som inte
// kunde läsas får inte se friskt ut bara för att inget fel rapporterades.
function opsCard(label, klass, värde, detalj) {
  return `<div class="stat"><span class="pill ${klass}">${esc(värde)}</span>` +
         `<span style="display:block;margin-top:.35rem">${esc(label)}</span>` +
         `<span>${esc(detalj || "")}</span></div>`;
}

function renderOps(health, providers, primat) {
  const nu = new Date().toLocaleTimeString("sv-SE", { timeStyle: "short" });
  $("opsCheckedAt").textContent = `kontrollerad ${nu}`;

  if (!health) {
    $("opsSummary").textContent = "Kunde inte läsa driftstatus";
    $("opsSystems").innerHTML = opsCard("Backend", "bad", "svarar inte", "") + primatKort(primat);
    return;
  }

  const kedjor = providers || [];
  const trasiga = kedjor.filter(p => p.health?.status === "failed");
  const inaktuella = kedjor.filter(p => p.health?.status === "stale");
  const behöverBlick = [...trasiga, ...inaktuella];

  const audit = health.pricingAudit || {};

  // Sammanfattningen namnger antal och kedja, inte bara en färg - "1 kedja
  // behöver uppmärksamhet" utan att säga vilken tvingar fram ett klick.
  //
  // PRISREVISIONEN VÄGER IN. Rubriken läste förut bara kedjornas hälsa, så
  // en röd revision kunde stå bredvid "Alla kontrollerade system fungerar" -
  // kedjorna importerade ju precis som de skulle. Men en röd revision säger
  // att priserna kan vara FEL, vilket är värre än att de är gamla, och en
  // rubrik som säger grönt över ett rött kort lär ägaren att strunta i båda.
  const auditTrasig = audit.gate === "RÖD" || audit.gate === "FEL";
  const auditOkand = !audit.gate || audit.gate === "INGEN DATA";
  $("opsSummary").textContent = trasiga.length
    ? `Prisplattformen har problem: ${trasiga.map(p => p.chain).join(", ")}`
    : auditTrasig
      ? `Prisrevisionen är ${audit.gate.toLowerCase()}: ${auditDetalj(audit)}`
      : inaktuella.length
        ? `${inaktuella.length} kedja${inaktuella.length > 1 ? "r" : ""} behöver uppmärksamhet: ${inaktuella.map(p => p.chain).join(", ")}`
        : auditOkand
          ? "Kedjorna fungerar, men prisrevisionen har inte kunnat granska dem"
          : "Alla kontrollerade system fungerar";
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
            audit.gate || "ingen data", auditDetalj(audit)) +
    opsCard("Släppta kedjor", friska.length === släppta.length && släppta.length ? "ok" : "warn",
            `${friska.length}/${släppta.length}`, "friska av släppta") +
    opsCard("Driftlarm", larmSkarpa ? "ok" : larm.recipientConfigured === undefined ? "off" : "warn",
            larmText, larm.recipientDomain ? `till ${larm.recipientDomain}` : "") +
    opsCard("Utgående mejl", health.mail ? "ok" : "warn", health.mail ? "konfigurerat" : "saknas",
            health.mailFrom ? `från ${health.mailFrom}` : "") +
    primatKort(primat) +
    opsCard("Utvecklingslåset", health.gate ? "warn" : "ok", health.gate ? "på" : "av",
            health.gate ? "appen är inte öppen" : "appen är öppen");

  $("opsAttention").innerHTML = (behöverBlick.length
    ? `<p class="note" style="margin-top:.8rem"><strong>Behöver uppmärksamhet:</strong> ` +
      behöverBlick.map(p => `${esc(p.chain)} &mdash; ${esc(p.health.reason || p.health.status)}`).join(" · ") +
      `</p>`
    : "") + osäkraIngredienser(audit);
}

// GATENS EGNA FLAGGOR, inte antalet kontroller. "4 596 kontroller" under ett
// rött kvitto svarar på fel fråga: den som ser rött vill veta VAD som är
// fel, inte hur mycket som granskades.
const GATE_FLAGGOR = {
  gram_som_styck: "gram som styck", volym_som_styck: "volym som styck",
  estimat: "osäkra rader", otolkad_paketstorlek: "otolkade paket",
  kilopris_som_paketpris: "kilopris som paketpris",
};

// O8: PRIMAT. Configured JA/NEJ går alltid att svara på. Kvoten gör det
// INTE - den kommer ur Primats eget /me, och hittas fälten inte där står
// "Ej tillgängligt". Ett tal som ser mätt ut men är gissat är värre än en
// tom ruta, för det går inte att skilja från ett riktigt.
function primatKort(primat) {
  if (!primat) return opsCard("Primat", "off", "okänt", "kunde inte läsas");
  if (!primat.configured) return opsCard("Primat", "off", "ej konfigurerad", "ingen API-nyckel");
  if (primat.error) return opsCard("Primat", "bad", "svarar inte", esc(String(primat.error).slice(0, 60)));
  const q = primat.quota;
  if (!q) return opsCard("Primat", "ok", "konfigurerad", "kvot: Ej tillgängligt");
  const andel = Math.round(100 * q.rowsUsedToday / q.dailyRowLimit);
  // Samma tröskel som driftlarmet (QUOTA_WARN_FRACTION 0,85), så kortet och
  // mejlet aldrig säger olika saker om samma dygn.
  return opsCard("Primat", andel >= 85 ? "warn" : "ok", `${andel}%`,
                 `${q.rowsUsedToday} av ${q.dailyRowLimit} rader i dag`
                 + (q.plan ? ` · ${esc(String(q.plan))}` : ""));
}

function auditDetalj(audit) {
  const kontroller = audit.kontroller ? `${audit.kontroller} kontroller` : "inga kontroller";
  if (audit.gate !== "RÖD") return kontroller;
  const fel = Object.entries(GATE_FLAGGOR)
    .filter(([nyckel]) => (audit.flaggor || {})[nyckel])
    .map(([nyckel, text]) => `${audit.flaggor[nyckel]} ${text}`);
  // Röd utan flagga = röd på TÄCKNING. Säg det i stället för att visa tomt.
  return fel.length ? fel.join(", ") : `${kontroller}, för låg täckning`;
}

// Vilka ingredienser som är osäkra. Utan namnen är "30 osäkra rader" inte
// åtgärdbar: siffran säger att något inte går att räkna ut, men inte vad.
function osäkraIngredienser(audit) {
  const rader = Object.entries(audit.estimatPerIngrediens || {});
  if (!rader.length) return "";
  return `<p class="note" style="margin-top:.6rem"><strong>Osäkra rader:</strong> ` +
    rader.map(([namn, antal]) => `${esc(namn)} &times;${antal}`).join(" · ") +
    ` <span class="quiet">&mdash; måttet går inte att räkna om till förpackningens enhet. ` +
    `Raderna hålls utanför säkra totaler och billigast-jämförelsen.</span></p>`;
}

// O15: FYRA TAL SOM ALLA HETER "BUTIKER". Ett register med tusentals
// adresser är inte tusentals prissatta butiker. Talen visas i ordning från
// störst till minst så att gapet syns: 412 i registret, 118 aktiva, 41
// färska, 41 kundtillgängliga - och för en osläppt kedja är det sista noll
// hur färsk datan än är.
function butikerText(b) {
  if (!b) return "—";
  const rad = `${b.iRegistret} reg · ${b.aktiva} aktiva · ${b.farska} färska · ${b.kundtillgangliga} kund`;
  return `<span title="${esc(`Färsk = ${b.farskGrans}. Kundtillgänglig = aktiv, färsk och släppt kedja. Källa: ${b.kalla}.`)}">${esc(rad)}</span>`;
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
    // O13: varje cell bär sin rubrik i data-label. Under 720 px döljs
    // tabellhuvudet och raden ritas som ett kort med rubrik-värde-par -
    // tretton kolumner i ett 341 px brett kort var fyra skärmbredder att
    // svepa genom, och det är den här tabellen driften läser i handen.
    return `<tr>
      <td data-label="Kedja"><strong>${esc(provider.chain)}</strong></td>
      <td data-label="Drift">${healthPill(provider.health)}</td>
      <td data-label="Släppt">${provider.health?.released ? "JA" : `<span class="quiet">nej</span>`}</td>
      <td data-label="Provider"><span class="pill ${STATUS_CLASS[provider.status] || "off"}">${esc(provider.status)}</span></td>
      <td data-label="Butiker">${butikerText(provider.butiker)}</td>
      <td data-label="Produkter">${provider.products}</td>
      <td data-label="Priser">${provider.prices}</td>
      <td data-label="GTIN">${provider.gtinPercent}%</td>
      <td data-label="Bild">${provider.imagePercent}%</td>
      <td data-label="Kategori">${provider.categoryPercent}%</td>
      <td data-label="Senaste lyckade">${success ? when(success.finishedAt) : "—"}</td>
      <td data-label="Senaste försök">${last ? `${esc(last.status)} · ${when(last.finishedAt || last.startedAt)}` : "—"}</td>
      <td data-label="Nästa nattkörning">${nightly ? esc(nightly.time) : `<span style="color:var(--muted)">ingen</span>`}</td>
      <td data-label="Åtgärd">${action}</td>
    </tr>${last?.errorMessage ? `<tr><td colspan="14" class="wrap">⚠ ${esc(last.errorMessage)}</td></tr>` : ""}
    ${blocked ? `<tr><td colspan="14" class="wrap">Ingen nattkörning: ${esc(blocked)}</td></tr>` : ""}`;
  }).join("");

  $("chainNotes").innerHTML = providers
    .map(provider => `<p class="note"><strong>${esc(provider.chain)}:</strong> ${esc(provider.note)}` +
      // O4: begränsad eller trasig kedja bär sin orsak även i klartext, inte
      // bara i en tooltip som inte går att hovra på en telefon.
      (provider.health?.reason && provider.health.status !== "healthy"
        ? ` <em>${esc(HEALTH_LABEL[provider.health.status] || provider.health.status)}: ${esc(provider.health.reason)}</em>` : "") +
      `</p>`)
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
