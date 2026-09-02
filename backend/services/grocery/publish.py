# -*- coding: utf-8 -*-
"""Staging -> validering -> quality gate -> atomisk publicering.

En import (nattjobb, manuell körning eller partnerfeed) får ALDRIG skriva
rakt in i grocery_current_prices. Raderna landar i grocery_price_staging,
saneras rad för rad, körningen bedöms som helhet, och först då publiceras
det som passerat - i en transaktion. Faller körningen på gaten behålls
senaste godkända prisdataset orört: appen visar hellre "uppdaterat igår"
än ett fel pris.

RADGATE (varje rad, oberoende av källa - partnerbutik eller kedje-API):
  - ett pris måste finnas (ordinarie eller kampanj), > 0 och <= 30 000 kr
  - kampanj som inte är lägre än ordinarie är ingen kampanj (nollas)
  - jämförpris, om det finns, måste vara > 0 och <= 5 000 kr/enhet
  - produkten måste finnas i katalogen med ett namn
Rader som fälls får PRICE_MISSING-öde: de publiceras inte alls. Ingen
gissning, ingen "närmaste rimliga" korrigering.

KÖRNINGSGATE (hela körningen):
  - minst en godkänd rad
  - andelen godkända rader >= PUBLISH_MIN_GATE_PERCENT
  - en KOMPLETT körning som ger mindre än PUBLISH_MIN_RATIO_OF_PREVIOUS av
    butikens tidigare prisantal är misstänkt trasig (halv katalog, fel
    butik, ändrad API-form) och publiceras inte. En körning som källan
    själv avbröt (blocked) är förväntat partiell och slås ihop.

Publicering är MERGE (upsert per produkt), inte utbyte: en partiell körning
raderar aldrig priser för produkter den inte såg. Färskheten syns per rad
via verified_at, och prissättningen slutar lita på ett butikspris som
blivit äldre än MAX_STORE_PRICE_AGE_SECONDS (se pricing.py).

REFERENSPRISER publiceras från samma körning när kedjan är nationellt
prissatt (varje butiks katalog är kedjans pris) eller när butiken är
kedjans utsedda referensbutik (STORE_SPECIFIC-kedjor). Se register.py.
"""

import logging
import time

logger = logging.getLogger("matjakt.grocery.publish")

PUBLISH_MIN_GATE_PERCENT = 95.0
PUBLISH_MIN_RATIO_OF_PREVIOUS = 0.3
MAX_PRICE_SEK = 30000.0
MAX_UNIT_PRICE_SEK = 5000.0


def _sane_price(value):
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if value is None or value <= 0 or value > MAX_PRICE_SEK:
        return None
    return value


def gate_row(row: dict, product_name: str | None) -> tuple[bool, str | None, dict]:
    """(godkänd, orsak, sanerade priser). Orsaken är för adminvyn - den
    säger vad som var fel, aldrig vad vi 'antog' i stället."""
    regular = _sane_price(row.get("regular_price"))
    campaign = _sane_price(row.get("campaign_price"))
    member = _sane_price(row.get("member_price"))
    multibuy = _sane_price(row.get("multibuy_price"))
    unit_price = row.get("unit_price")
    try:
        unit_price = float(unit_price) if unit_price is not None else None
    except (TypeError, ValueError):
        unit_price = None
    raw_regular = row.get("regular_price")
    raw_campaign = row.get("campaign_price")

    if not product_name:
        return False, "produkt_saknar_namn", {}
    if regular is None and campaign is None:
        if raw_regular is not None or raw_campaign is not None:
            try:
                bad = float(raw_regular if raw_regular is not None else raw_campaign)
            except (TypeError, ValueError):
                return False, "pris_inte_ett_tal", {}
            if bad <= 0:
                return False, "pris_noll_eller_negativt", {}
            return False, "pris_orimligt_hogt", {}
        return False, "pris_saknas", {}
    if campaign is not None and regular is not None and campaign >= regular:
        campaign = None
    if unit_price is not None and not (0 < unit_price <= MAX_UNIT_PRICE_SEK):
        return False, "jamforpris_orimligt", {}
    return True, None, {
        "regular_price": regular, "campaign_price": campaign, "member_price": member,
        "multibuy_price": multibuy, "unit_price": unit_price,
    }


def backfill_reference_prices(db, chains: list[str] | None = None) -> dict:
    """FÖRSTA REFERENSPUBLICERINGEN ur redan verifierad data.

    Innan referenstabellen fanns låg kedjornas priser bara som butikspriser
    på importbutiken. Den här backfillen lyfter dem till referensnivån EN
    gång enligt samma regel som nattjobbet: NATIONAL-kedjornas importerade
    katalog och STORE_SPECIFIC-kedjornas utsedda referensbutik. Idempotent
    (upsert) och saneringen är densamma - ett pris som inte klarar gaten
    blir inte referens heller."""
    from .register import CHAIN_PRICING_SCOPE, CHAIN_REFERENCE_STORE

    import sqlite3

    chains = chains or list(CHAIN_PRICING_SCOPE)
    summary = {}
    skipped = 0
    for chain in chains:
        scope = CHAIN_PRICING_SCOPE.get(chain)
        if scope == "NATIONAL":
            stores = db.connection.execute(
                "SELECT DISTINCT s.id, s.external_store_id FROM grocery_stores s "
                "JOIN grocery_current_prices cp ON cp.store_id = s.id WHERE s.chain = ?",
                (chain,)).fetchall()
        else:
            reference_id = CHAIN_REFERENCE_STORE.get(chain)
            stores = db.connection.execute(
                "SELECT id, external_store_id FROM grocery_stores WHERE chain = ? AND external_store_id = ?",
                (chain, reference_id)).fetchall() if reference_id else []
        published = 0
        for store_row in stores:
            for price in db.connection.execute(
                    "SELECT * FROM grocery_current_prices WHERE store_id = ?", (store_row["id"],)):
                keys = price.keys()
                # PARTNERPRISER BLIR ALDRIG REFERENS - de är ett påstående om
                # EN butik. Utan filtret lyfte backfillen en partnerbutiks
                # priser till hela kedjans referensnivå (hittat i E2E).
                if "source" in keys and (price["source"] or "").startswith("partner:"):
                    continue
                ok, _, cleaned = gate_row(dict(price), "x")
                if not ok:
                    continue
                source = (price["source"] if "source" in keys and price["source"]
                          else f"{chain.lower()}:{store_row['external_store_id']}")
                try:
                    if db.upsert_reference_price(
                            product_id=price["product_id"], chain=chain,
                            regular_price=cleaned["regular_price"], campaign_price=cleaned["campaign_price"],
                            member_price=cleaned["member_price"], multibuy_price=cleaned["multibuy_price"],
                            unit_price=cleaned["unit_price"], currency=price["currency"] or "SEK",
                            source=source, valid_to=price["valid_to"] if "valid_to" in keys else None,
                            verified_at=(price["verified_at"] if "verified_at" in keys and price["verified_at"]
                                         else price["fetched_at"])):
                        published += 1
                except (sqlite3.Error, ValueError, TypeError) as error:
                    # EN dålig rad (t.ex. en gammal prisrad vars produkt inte
                    # längre finns - FK-fel) får aldrig döda hela backfillen.
                    # Produktion stannade på exakt 2 862 rader två gånger
                    # innan detta fanns.
                    skipped += 1
                    if skipped <= 5:
                        logger.warning("Backfill hoppade över produkt %s (%s): %s",
                                       price["product_id"], chain, error)
        summary[chain] = published
    if skipped:
        summary["skipped"] = skipped
    logger.info("Referenspriser backfillade: %s", summary)
    return summary


def publish_run(db, run_id: int, store_id: int, chain: str, *, source: str,
                blocked: bool = False, partial: bool = False,
                publish_reference: bool | None = None) -> dict:
    """Bedömer och publicerar en stagead körning. Returnerar en sammanfattning
    med gate-procent, publicerade rader och besked - samma siffror som
    adminvyn visar som 'Quality gate: 99,7 %'."""
    from .register import CHAIN_PRICING_SCOPE, CHAIN_REFERENCE_STORE

    rows = db.staged_rows(run_id)
    staged = len(rows)
    if staged == 0:
        db.record_run_gate(run_id, rows_staged=0, gate_percent=None, published=False,
                           message="inga rader att publicera")
        return {"staged": 0, "passed": 0, "published": 0, "gatePercent": None,
                "published_ok": False, "message": "inga rader att publicera"}

    product_names = {}
    for row in db.connection.execute(
            "SELECT p.id, p.name FROM grocery_products p WHERE p.id IN "
            f"(SELECT DISTINCT product_id FROM grocery_price_staging WHERE run_id = {int(run_id)})"):
        product_names[row["id"]] = row["name"]

    passed_rows = []
    with db.connection:
        for row in rows:
            ok, reason, cleaned = gate_row(dict(row), product_names.get(row["product_id"]))
            db.mark_staged(row["id"], "ok" if ok else "rejected", reason)
            if ok:
                passed_rows.append((row, cleaned))
    gate_percent = round(100.0 * len(passed_rows) / staged, 1)

    previous = db.price_count_for_store(store_id)
    message = None
    publish_ok = True
    if not passed_rows:
        publish_ok, message = False, "ingen rad klarade prisgaten"
    elif gate_percent < PUBLISH_MIN_GATE_PERCENT:
        publish_ok, message = False, (f"bara {gate_percent} % av raderna klarade gaten "
                                      f"(krav {PUBLISH_MIN_GATE_PERCENT:g} %) - senaste godkända "
                                      f"priser behålls")
    elif (not blocked and not partial and previous
            and len(passed_rows) < previous * PUBLISH_MIN_RATIO_OF_PREVIOUS):
        # partial = anroparen BEGÄRDE en begränsad körning (t.ex. några
        # produkter per kategori i en rök) - då är få rader förväntat, inte
        # misstänkt, och resultatet slås ihop precis som en avbruten körning.
        publish_ok, message = False, (f"komplett körning gav {len(passed_rows)} rader mot "
                                      f"{previous} tidigare - misstänkt trasig, inget publicerat")

    if not publish_ok:
        db.record_run_gate(run_id, rows_staged=staged, gate_percent=gate_percent,
                           published=False, message=message)
        db.clear_staging(run_id)
        logger.warning("Körning %s (%s/butik %s) INTE publicerad: %s", run_id, chain, store_id, message)
        return {"staged": staged, "passed": len(passed_rows), "published": 0,
                "gatePercent": gate_percent, "published_ok": False, "message": message}

    scope = CHAIN_PRICING_SCOPE.get(chain, "STORE_SPECIFIC")
    if publish_reference is None:
        store_row = db.get_store_by_id(store_id)
        external_id = store_row.external_store_id if store_row else None
        publish_reference = (scope == "NATIONAL"
                             or (external_id is not None
                                 and CHAIN_REFERENCE_STORE.get(chain) == external_id))

    published = 0
    reference_published = 0
    now = time.time()
    for row, cleaned in passed_rows:
        try:
            db.upsert_current_price(
                product_id=row["product_id"], store_id=store_id,
                regular_price=cleaned["regular_price"], campaign_price=cleaned["campaign_price"],
                member_price=cleaned["member_price"], multibuy_price=cleaned["multibuy_price"],
                unit_price=cleaned["unit_price"], currency=row["currency"] or "SEK",
                source_url=row["source_url"], fetched_at=row["fetched_at"] or now,
                source=row["source"] or source, valid_to=row["valid_to"])
            published += 1
            if publish_reference:
                if db.upsert_reference_price(
                        product_id=row["product_id"], chain=chain,
                        regular_price=cleaned["regular_price"], campaign_price=cleaned["campaign_price"],
                        member_price=cleaned["member_price"], multibuy_price=cleaned["multibuy_price"],
                        unit_price=cleaned["unit_price"], currency=row["currency"] or "SEK",
                        source=row["source"] or source, valid_to=row["valid_to"],
                        verified_at=row["fetched_at"] or now):
                    reference_published += 1
        except (ValueError, TypeError) as error:
            # upsert_current_price vägrade (dubbelt hängslen mot ett pris som
            # slank igenom radgaten) - raden hoppas över, inget gissas.
            logger.warning("Rad för produkt %s hoppades över vid publicering: %s", row["product_id"], error)
            continue
        except Exception as error:  # sqlite3.Error m.fl. - en rad, inte körningen
            logger.warning("Rad för produkt %s kunde inte publiceras: %s", row["product_id"], error)
            continue

    if blocked:
        message = f"partiell körning (källan avbröt): {published} rader publicerade"
    db.record_run_gate(run_id, rows_staged=staged, gate_percent=gate_percent,
                       published=True, message=message)
    db.clear_staging(run_id)
    logger.info("Körning %s publicerad: %d/%d rader (%s %%), %d referenspriser",
                run_id, published, staged, gate_percent, reference_published)
    return {"staged": staged, "passed": len(passed_rows), "published": published,
            "referencePublished": reference_published, "gatePercent": gate_percent,
            "published_ok": True, "message": message}
