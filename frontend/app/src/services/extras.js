// Extra items on the shopping list: campaign finds and manually added goods.
//
// THE PRICE RULE, in code where tests can hold it down: an extra's price at
// a chain comes from (1) a real product match AT THAT CHAIN, or (2) the
// item's own stored campaign price ONLY when the item came from that very
// chain. A Willys campaign price never travels to Hemköp, and a manual line
// with no match has NO price - a plain row, never an invented figure.

export function newExtraItem(fields) {
  return {
    id: fields.id || `x${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`,
    name: fields.name,
    qty: Math.max(1, fields.qty || 1),
    source: fields.source || "manual",          // "campaign" | "manual"
    chain: fields.chain || null,                 // kedjan erbjudandet kom från
    storeId: fields.storeId || null,
    productId: fields.productId || null,
    gtin: fields.gtin || null,
    imageUrl: fields.imageUrl || null,
    packageSize: fields.packageSize || null,
    campaignPrice: fields.campaignPrice ?? null,
    regularPrice: fields.regularPrice ?? null,
    validUntil: fields.validUntil || null,
    addedAt: fields.addedAt || Date.now(),
    checked: Boolean(fields.checked),
  };
}

/** Whether a stored campaign is still worth trusting. An expired offer's
 *  price is yesterday's truth - the item stays, its price does not. */
export function campaignStillValid(extra, now = Date.now()) {
  if (!extra.validUntil) return true; // ingen sluttid insamlad = lita på insamlingen
  const until = new Date(extra.validUntil).getTime();
  return Number.isFinite(until) ? until >= now : true;
}

/** The price of ONE unit of this extra at `chain`, or null.
 *  `match` is the chain's own product match for the item (from the pricing
 *  API), shaped { unitPrice } - real data or absent. */
export function extraUnitPrice(extra, chain, match, now = Date.now()) {
  if (match && match.unitPrice != null) return match.unitPrice;
  if (extra.chain === chain && extra.campaignPrice != null && campaignStillValid(extra, now)) {
    return extra.campaignPrice;
  }
  return null;
}

export function extraLineTotal(extra, chain, match, now = Date.now()) {
  const unit = extraUnitPrice(extra, chain, match, now);
  return unit == null ? null : Math.round(unit * extra.qty * 100) / 100;
}

/** Sum of every PRICED extra at this chain. Unpriced lines contribute
 *  nothing - they are visible rows, not hidden costs. */
export function extrasTotal(extras, chain, matches = {}, now = Date.now()) {
  return Math.round(extras.reduce((sum, extra) => {
    const line = extraLineTotal(extra, chain, matches[extra.id], now);
    return sum + (line || 0);
  }, 0) * 100) / 100;
}

export function setQty(extras, id, qty) {
  return extras.map(extra => extra.id === id
    ? { ...extra, qty: Math.max(1, Math.min(99, qty)) } : extra);
}

export function removeExtra(extras, id) {
  return extras.filter(extra => extra.id !== id);
}
