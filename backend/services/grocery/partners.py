# -*- coding: utf-8 -*-
"""Butikspartner - B2B-grunden.

En partner (PER_STORE: handlarägd butik, PER_GROUP: Coop-förening med många
store_ids, PER_CHAIN: centralt kedjeavtal) med status ACTIVE får LEVERERA
verifierade lokala priser till Matjakt. Det är hela rättigheten.

BETALNING PÅVERKAR ALDRIG RANKINGEN. compare_chains känner inte till
partnertabellerna, och det ska den aldrig göra - en betalande butik blir
"Billigast" bara om den faktiskt är billigast. Sponsrade placeringar får
senare finnas men måste märkas "Sponsrat" separat; de bor inte här.

Partnerns data går genom EXAKT samma väg som kedje-API:erna: parse ->
katalogförsoning (GTIN först) -> staging -> radgate -> körningsgate ->
publicering (publish.py). Butiken kan inte trycka in dålig data direkt.
Partnerpriser publiceras aldrig som kedjans referenspris - de är ett
påstående om EN butik.

Priset per paket (Matjakt Butik, 1 495 kr/mån) ligger i
grocery_partner_plans, kopieras in på partnern vid teckning och ändras via
data, inte kod. Billing-modellen (PER_STORE/PER_GROUP/PER_CHAIN) följer
partnerns kind.
"""

import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone

from .models import RawProduct

logger = logging.getLogger("matjakt.grocery.partners")

PARTNER_STATUSES = ("NONE", "PENDING", "ACTIVE", "PAUSED", "CANCELLED")
PARTNER_KINDS = ("PER_STORE", "PER_GROUP", "PER_CHAIN")
STAT_EVENTS = ("store_shown", "store_compared", "store_cheapest", "offer_shown", "offer_saved")


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def create_partner(db, *, kind: str, name: str, chain: str | None = None,
                   store_external_ids: list[str] | None = None, plan_code: str = "matjakt_butik",
                   contact_email: str | None = None) -> dict:
    """Skapar partnern PENDING och kopplar butiker. Returnerar API-nyckeln
    EN gång i klartext - bara hashen lagras."""
    if kind not in PARTNER_KINDS:
        raise ValueError(f"okänd partnertyp {kind!r}")
    if kind == "PER_CHAIN" and not chain:
        raise ValueError("kedjeavtal kräver chain")
    api_key = "mjp_" + secrets.token_urlsafe(24)
    partner_id = db.create_partner(kind=kind, name=name, plan_code=plan_code, chain=chain,
                                   contact_email=contact_email, api_key_hash=_hash_key(api_key))
    linked = []
    for external_id in store_external_ids or []:
        store = db.get_store(chain=chain, external_store_id=str(external_id)) if chain else None
        if store is None and not chain:
            row = db.connection.execute(
                "SELECT chain FROM grocery_stores WHERE external_store_id = ?", (str(external_id),)).fetchone()
            store = db.get_store(chain=row["chain"], external_store_id=str(external_id)) if row else None
        if store is None:
            raise ValueError(f"butik {external_id!r} finns inte i registret")
        db.link_partner_store(partner_id, store.id)
        linked.append(store.id)
    if kind == "PER_CHAIN":
        db.set_chain_partner(chain, partner_id)
    _sync_store_statuses(db, partner_id)
    return {"partnerId": partner_id, "apiKey": api_key, "storeIds": linked, "status": "PENDING"}


def set_status(db, partner_id: int, status: str) -> dict:
    """ACTIVE ger leveransrätt. PAUSED/CANCELLED tar bort partnerns
    publicerade priser: utan aktiv leverantör finns ingen som går i god för
    dem, och prissättningen faller tillbaka på kedjans referenspris."""
    if status not in PARTNER_STATUSES or status == "NONE":
        raise ValueError(f"ogiltig status {status!r}")
    partner = db.get_partner(partner_id)
    if partner is None:
        raise ValueError("okänd partner")
    db.set_partner_status(partner_id, status)
    removed = 0
    if status != "ACTIVE":
        removed = db.delete_prices_from_source(f"partner:{partner_id}:")
    _sync_store_statuses(db, partner_id)
    logger.info("Partner %s -> %s (%d priser borttagna)", partner_id, status, removed)
    return {"partnerId": partner_id, "status": status, "pricesRemoved": removed}


def _sync_store_statuses(db, partner_id: int) -> None:
    """Denormaliserad partner_status på butiksraderna (för adminvyn och
    närhetssöket). Sanningen är partnertabellen; detta är en spegel."""
    partner = db.get_partner(partner_id)
    if partner is None:
        return
    with db.connection:
        if partner["kind"] == "PER_CHAIN" and partner["chain"]:
            db.connection.execute(
                "UPDATE grocery_stores SET partner_status = ? WHERE chain = ?",
                (partner["status"], partner["chain"]))
        for store_id in db.partner_store_ids(partner_id):
            db.connection.execute(
                "UPDATE grocery_stores SET partner_status = ? WHERE id = ?",
                (partner["status"], store_id))


def effective_partner_status(db, store_id: int) -> tuple[str, int | None]:
    """(status, partner_id) för en butik: direkt/grupp-koppling först,
    annars kedjeavtal, annars NONE."""
    direct = db.connection.execute(
        "SELECT p.id, p.status FROM grocery_partner_stores ps JOIN grocery_partners p ON p.id = ps.partner_id "
        "WHERE ps.store_id = ? ORDER BY CASE p.status WHEN 'ACTIVE' THEN 0 ELSE 1 END, p.id DESC LIMIT 1",
        (store_id,)).fetchone()
    if direct:
        return direct["status"], direct["id"]
    chain_row = db.connection.execute(
        "SELECT c.chain_partner_id, p.status FROM grocery_stores s "
        "JOIN grocery_chains c ON c.name = s.chain "
        "LEFT JOIN grocery_partners p ON p.id = c.chain_partner_id WHERE s.id = ?",
        (store_id,)).fetchone()
    if chain_row and chain_row["chain_partner_id"] and chain_row["status"]:
        return chain_row["status"], chain_row["chain_partner_id"]
    return "NONE", None


def partner_covers_store(db, partner_id: int, store_id: int) -> bool:
    status, covering = effective_partner_status(db, store_id)
    return covering == partner_id and status == "ACTIVE"


def authenticate_partner(db, api_key: str):
    if not api_key:
        return None
    return db.partner_by_key_hash(_hash_key(api_key))


def ingest_feed(db, *, partner_id: int, store_id: int, format: str, payload) -> dict:
    """Partnerfeed -> samma pipeline som allt annat. Vägrar allt som inte
    kommer från en ACTIVE partner som faktiskt täcker butiken."""
    from .partner_feed import parse_feed
    from .publish import publish_run

    partner = db.get_partner(partner_id)
    if partner is None:
        raise ValueError("okänd partner")
    if partner["status"] != "ACTIVE":
        raise PermissionError(f"partnern är {partner['status']}, inte ACTIVE - feeden tas inte emot")
    if not partner_covers_store(db, partner_id, store_id):
        raise PermissionError("partnern täcker inte den här butiken")
    store = db.get_store_by_id(store_id)
    if store is None:
        raise ValueError("okänd butik")

    parsed = parse_feed(format, payload)
    source = f"partner:{partner_id}:{store.external_store_id}"
    run = db.start_collector_run(chain=store.chain, store_id=store.id)
    staged = 0
    row_errors = list(parsed.errors)
    for row in parsed.rows:
        name = row.name
        if not name and row.gtin:
            # Namnlös rad med känd GTIN: katalogens namn gäller. Okänd GTIN
            # utan namn får ALDRIG skapa en namnlös produkt - raden fälls
            # med besked så butiken kan rätta filen.
            known = db._find_product_by_gtin(row.gtin)
            name = known.name if known else ""
        if not name:
            from .partner_feed import FeedError
            row_errors.append(FeedError(row.line_number, "produktnamn saknas och GTIN är okänd för Matjakt"))
            continue
        raw = RawProduct(
            chain=store.chain,
            external_product_id=row.external_product_id or (f"gtin:{row.gtin}" if row.gtin else f"feed:{row.line_number}"),
            name=name, store_id=store.external_store_id, store_name=store.name,
            gtin=row.gtin, brand=row.brand, size=row.package, category=row.category,
            regular_price=row.regular_price, campaign_price=row.campaign_price,
            member_price=row.member_price, campaign_valid_to=row.campaign_valid_to,
            fetched_at=time.time())
        try:
            product = db.find_or_create_product(raw)
            db.stage_price(run_id=run.id, store_id=store.id, product_id=product.id,
                           regular_price=raw.regular_price, campaign_price=raw.campaign_price,
                           member_price=raw.member_price, source=source,
                           valid_to=raw.campaign_valid_to, fetched_at=raw.fetched_at)
            staged += 1
        except Exception:
            logger.exception("Partnerrad %s kunde inte stageas", row.line_number)

    # Partnerpriser är ett påstående om EN butik - aldrig kedjans referens.
    # partial=True: en feed är per kontrakt en LEVERANS som slås ihop med
    # tidigare (delfiler, dagens ändringar, en avdelning i taget) - få rader
    # är förväntat, inte tecken på trasig katalog. Radgaten och 95 %-kravet
    # gäller fullt ut ändå.
    outcome = publish_run(db, run.id, store.id, store.chain, source=source,
                          blocked=False, partial=True, publish_reference=False)
    db.finish_collector_run(run.id, status="success" if outcome["published_ok"] else "failed",
                            products_found=len(parsed.rows), prices_updated=outcome["published"],
                            errors=len(row_errors) + (0 if outcome["published_ok"] else 1),
                            error_message=outcome["message"])
    db.record_partner_feed(partner_id=partner_id, store_id=store.id, format=format,
                           status="published" if outcome["published_ok"] else "rejected",
                           rows_received=parsed.total_lines, rows_published=outcome["published"],
                           gate_percent=outcome["gatePercent"], message=outcome["message"])
    return {
        "received": parsed.total_lines, "parsed": len(parsed.rows), "staged": staged,
        "published": outcome["published"], "gatePercent": outcome["gatePercent"],
        "publishedOk": outcome["published_ok"], "message": outcome["message"],
        "rowErrors": [{"line": e.line_number, "reason": e.reason} for e in row_errors[:50]],
    }


def record_stat(db, store_id: int | None, event: str) -> None:
    """Anonym räknare per butik och dag - inget om VEM."""
    if not store_id or event not in STAT_EVENTS:
        return
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        db.bump_partner_stat(store_id, event, day)
    except Exception:
        logger.exception("Kunde inte räkna %s för butik %s", event, store_id)


def admin_overview(db) -> list[dict]:
    """Adminvyn: varje butik som är partner ELLER bär priser - status,
    prisantal, senaste synk och quality gate för senaste körningen."""
    rows = db.connection.execute(
        """
        SELECT s.id, s.chain, s.name, s.city, s.external_store_id, s.partner_status, s.partner_id,
               s.pricing_scope,
               (SELECT COUNT(*) FROM grocery_current_prices cp WHERE cp.store_id = s.id) AS prices,
               (SELECT MAX(COALESCE(cp.verified_at, cp.fetched_at)) FROM grocery_current_prices cp
                 WHERE cp.store_id = s.id) AS last_sync,
               (SELECT gate_percent FROM grocery_collector_runs r WHERE r.store_id = s.id
                 ORDER BY r.id DESC LIMIT 1) AS gate_percent,
               (SELECT status FROM grocery_collector_runs r WHERE r.store_id = s.id
                 ORDER BY r.id DESC LIMIT 1) AS last_run_status,
               (SELECT gate_message FROM grocery_collector_runs r WHERE r.store_id = s.id
                 ORDER BY r.id DESC LIMIT 1) AS last_run_message
        FROM grocery_stores s
        WHERE s.partner_status != 'NONE' OR EXISTS (
            SELECT 1 FROM grocery_current_prices cp WHERE cp.store_id = s.id)
        ORDER BY s.chain, s.name
        """).fetchall()
    overview = []
    for row in rows:
        status, partner_id = effective_partner_status(db, row["id"])
        feed = db.latest_partner_feed(row["id"])
        overview.append({
            "storeId": row["id"], "chain": row["chain"], "name": row["name"], "city": row["city"],
            "externalStoreId": row["external_store_id"], "pricingScope": row["pricing_scope"],
            "partnerStatus": status, "partnerId": partner_id,
            "prices": row["prices"], "lastSync": row["last_sync"],
            "gatePercent": row["gate_percent"], "lastRunStatus": row["last_run_status"],
            "lastRunMessage": row["last_run_message"],
            "lastFeed": ({"format": feed["format"], "status": feed["status"],
                          "rowsPublished": feed["rows_published"], "gatePercent": feed["gate_percent"],
                          "receivedAt": feed["received_at"]} if feed else None),
            "stats30d": db.partner_stats(row["id"], 30),
        })
    return overview
