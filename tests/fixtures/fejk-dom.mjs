// Precis så mycket DOM som src/utils/modal.js rör vid.
//
// Modulen behöver inte en webbläsare för att gå att pröva - den rör ett
// dussin API:er, och alla är små: attribut, barn, fokus, en tangentlyssnare
// på document och `body.style.overflow`. Det som verkligen KRÄVER en
// webbläsare (att `inert` gör bakgrunden otabbbar, att Escape når fram genom
// en riktig händelsekedja) prövas i Playwright-resan i stället.
//
// Ligger under fixtures/ och inte i tests/ direkt: allt som heter *.test.js
// där körs som testfil av `node --test`. Det här är verktyg.

/** Matchar en ENKEL selektor: tagg + [attr] + [attr="v"] + :not(...). */
function matchaEnkel(el, selektor) {
  let rest = selektor.trim();
  const tagg = /^[a-z][a-z0-9]*/i.exec(rest);
  if (tagg) {
    if (el.tagName !== tagg[0].toUpperCase()) return false;
    rest = rest.slice(tagg[0].length);
  }
  const delar = /(:not\()?\[([\w-]+)(?:="([^"]*)")?\]\)?/g;
  for (let m; (m = delar.exec(rest)); ) {
    const negerad = Boolean(m[1]);
    const finns = el.hasAttribute(m[2]);
    const träff = m[3] === undefined ? finns : finns && el.getAttribute(m[2]) === m[3];
    if (negerad ? träff : !träff) return false;
  }
  return true;
}

function matchar(el, selektorlista) {
  return selektorlista.split(",").some((sel) => matchaEnkel(el, sel));
}

export class FejkEl {
  constructor(tagName, attribut = {}) {
    this.tagName = String(tagName).toUpperCase();
    this.attribut = new Map(Object.entries(attribut));
    this.barn = [];
    this.parentNode = null;
    this.style = { overflow: "" };
    this.fokusräknare = 0;
    this._doc = null;
  }

  get ownerDocument() { return this._doc || this.parentNode?.ownerDocument || null; }
  get children() { return [...this.barn]; }

  get hidden() { return this.hasAttribute("hidden"); }
  set hidden(värde) {
    if (värde) this.setAttribute("hidden", "");
    else this.removeAttribute("hidden");
  }

  hasAttribute(namn) { return this.attribut.has(namn); }
  getAttribute(namn) { return this.attribut.get(namn) ?? null; }
  setAttribute(namn, värde) { this.attribut.set(namn, String(värde)); }
  removeAttribute(namn) { this.attribut.delete(namn); }

  append(...noder) {
    for (const nod of noder) { nod.parentNode = this; this.barn.push(nod); }
    return this;
  }

  contains(nod) {
    for (let p = nod; p; p = p.parentNode) if (p === this) return true;
    return false;
  }

  alla() {
    return this.barn.flatMap((b) => [b, ...b.alla()]);
  }

  querySelector(selektor) { return this.querySelectorAll(selektor)[0] ?? null; }
  querySelectorAll(selektor) { return this.alla().filter((el) => matchar(el, selektor)); }

  focus() {
    this.fokusräknare += 1;
    const doc = this.ownerDocument;
    if (doc) doc.activeElement = this;
  }

  /** Synlighet: modal.js frågar efter offsetParent/getClientRects. */
  getClientRects() { return this.hidden ? [] : [{}]; }
}

export class FejkDoc {
  constructor() {
    this.body = new FejkEl("body");
    this.body._doc = this;
    this.activeElement = this.body;
    this.lyssnare = [];
  }

  get ownerDocument() { return this; }

  addEventListener(typ, fn, capture) { this.lyssnare.push({ typ, fn, capture }); }
  removeEventListener(typ, fn, capture) {
    const i = this.lyssnare.findIndex((l) => l.typ === typ && l.fn === fn && l.capture === capture);
    if (i !== -1) this.lyssnare.splice(i, 1);
  }

  contains(nod) { return nod === this.body || this.body.contains(nod); }

  /** Skickar en tangent till lyssnarna i registreringsordning. */
  tryck(key, { shiftKey = false } = {}) {
    const händelse = { key, shiftKey, förhindrad: false, preventDefault() { this.förhindrad = true; } };
    for (const l of [...this.lyssnare]) if (l.typ === "keydown") l.fn(händelse);
    return händelse;
  }
}

/**
 * En modal: bakgrund > panel(role=dialog) > rubrik + knappar.
 * Returnerar delarna så testet kan peka på dem.
 */
export function byggModal(doc, id, { knappar = ["stäng", "ok"] } = {}) {
  const bakgrund = new FejkEl("div", { id });
  const panel = new FejkEl("div", { role: "dialog", "aria-modal": "true" });
  const rubrik = new FejkEl("h2");
  const knapp = knappar.map((namn) => new FejkEl("button", { "data-namn": namn }));
  panel.append(rubrik, ...knapp);
  bakgrund.append(panel);
  bakgrund.hidden = true;
  doc.body.append(bakgrund);
  return { bakgrund, panel, rubrik, knappar: knapp };
}
