# -*- coding: utf-8 -*-
"""Dabas-berikning av produktkatalogen - bakgrundsflöde, aldrig i en request.

    Ny produkt från prisprovider
      1. GTIN finns?                      nej -> ingen berikning möjlig
      2. Full Dabas-data redan i vår DB?  ja  -> inget nytt anrop
      3. Köas: products_needing_dabas()
      4. Dabas svarar (JSON/XML)          -> normalize_article
      5. Validera                         -> giltig GTIN, tolkbart innehåll
      6. FÄLTVIS MERGE                    -> se merge_fields()
      7. Spara + statusmetadata           -> dabas_status/last_checked/...

MERGEREGLER (prioritet för verifierad masterdata):
    DABAS_VERIFIED  >  PROVIDER_DATA  >  NORMALIZED_FALLBACK
men ett fält Dabas SAKNAR (null/tomt) rör aldrig fungerande befintlig data.
Produktens visningsnamn (name) är fortsatt kedjans hyllnamn - det är vad
kunden ser i butiken och vad den kanoniska matchningen är kalibrerad på;
Dabas officiella namn sparas i dabas_name. Märke/tillverkare/kategori/
ingredienser/allergener/näring tar Dabas värde när det finns.

PAKETDATA - HÖG PRIORITET (grammen, styckena, multipacken har bitit oss):
    provider 450 g  + Dabas 450 g   -> package_confidence high, DABAS_VERIFIED
    provider saknar + Dabas 450 g   -> high, DABAS_VERIFIED (fyller luckan)
    provider 450 g  + Dabas 500 g   -> CONFLICT: mängden används inte,
                                       raden blir osäker i prismotorn
                                       (effective_package returnerar okänt)
    provider 450 g  + Dabas saknar  -> provider, PROVIDER_DATA (som förut)
    Dabas variabelmått/lösvikt      -> providerns cirkavikt får stå, märkt
Tolerans 2 % för avrundning (ca-vikt 750 vs 745).

KANONISK MATCHNING: dabas_category sparas på produkten och prövas i
prismotorn som en extra REJECT-signal genom samma avdelningsvakt som
kedjornas kategorier - "Kanel" mot Dabas-kategori "Knäckebröd" faller,
oavsett produktnamn. Dabas stärker reglerna, ersätter dem inte.

AKTIVERING: körs bara när DABAS_API_KEY finns OCH
MATJAKT_DABAS_ENRICHMENT_ENABLED=1 - villkor/rate limits ska vara
verifierade innan produktion (docs/DABAS.md).
"""

import json
import logging
import os
import time

from .providers.dabas import (
    DabasClient, DabasError, DabasNotFound, DabasRateLimited, DabasUnauthorized,
    DabasProduct)

logger = logging.getLogger("matjakt.grocery.enrichment")

PACKAGE_TOLERANCE = 0.02
MAX_PER_RUN = int(os.environ.get("MATJAKT_DABAS_MAX_PER_RUN", "300"))


def enrichment_enabled() -> bool:
    return bool(os.environ.get("DABAS_API_KEY")) and str(
        os.environ.get("MATJAKT_DABAS_ENRICHMENT_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}


def _same_amount(a: float, b: float) -> bool:
    return abs(a - b) <= max(a, b) * PACKAGE_TOLERANCE


def _provider_package(product):
    """Providerns tolkning i kanonisk enhet, via prismotorns egen läsning."""
    from .pricing import effective_package
    try:
        quantity, unit = effective_package(product)
    except Exception:
        return None, None
    if quantity is None or unit is None:
        return None, None
    folded = str(unit).lower()
    if folded in ("g", "gram"):
        return float(quantity), "g"
    if folded in ("kg",):
        return float(quantity) * 1000, "g"
    if folded in ("ml",):
        return float(quantity), "ml"
    if folded in ("cl",):
        return float(quantity) * 10, "ml"
    if folded in ("dl",):
        return float(quantity) * 100, "ml"
    if folded in ("l",):
        return float(quantity) * 1000, "ml"
    if folded in ("st", "styck", "p", "pack", "forp", "förp"):
        return float(quantity), "st"
    return None, None


def package_verdict(product, dabas: DabasProduct) -> dict:
    """Fälten package_source/package_confidence/package_conflict + ev. ny
    quantity/unit/size, utifrån provider mot Dabas."""
    p_qty, p_unit = _provider_package(product)
    d = dabas.package
    if d.variable_measure:
        return {"package_source": "PROVIDER_DATA" if p_qty else "NORMALIZED_FALLBACK",
                "package_confidence": "provider" if p_qty else "none",
                "package_conflict": None}
    if d.quantity is None or d.unit is None:
        return {"package_source": "PROVIDER_DATA" if p_qty else "NORMALIZED_FALLBACK",
                "package_confidence": "provider" if p_qty else "none",
                "package_conflict": None}
    if p_qty is None:
        return {"package_source": "DABAS_VERIFIED", "package_confidence": "high",
                "package_conflict": None,
                "quantity": d.quantity, "unit": d.unit,
                "size": f"{d.quantity:g} {d.unit}"}
    if p_unit == d.unit and _same_amount(p_qty, d.quantity):
        return {"package_source": "DABAS_VERIFIED", "package_confidence": "high",
                "package_conflict": None, "quantity": d.quantity, "unit": d.unit}
    # Multipack: provider 6x120 g = 720 g mot Dabas 720 g hanteras redan av
    # effective_package. Kvarstående skillnad = konflikt.
    return {"package_source": "PROVIDER_DATA", "package_confidence": "conflict",
            "package_conflict": f"provider {p_qty:g} {p_unit} / Dabas {d.quantity:g} {d.unit} ({d.kind})"}


def merge_fields(product, dabas: DabasProduct) -> dict:
    """Fältvis: Dabas värde när det finns, annars befintligt. Aldrig null
    över bra data. Returnerar bara det som ska skrivas."""
    fields = {}

    def take(column, value, keep_existing=None):
        if value in (None, "", [], {}):
            return
        if keep_existing is not None and keep_existing not in (None, ""):
            return
        fields[column] = value

    take("dabas_name", dabas.name)
    take("brand", dabas.brand)                      # Dabas > provider
    take("manufacturer", dabas.manufacturer or dabas.supplier)
    take("dabas_category", dabas.category)
    take("dabas_gpc", dabas.gpc_code)
    take("ingredients", dabas.ingredients)
    take("allergens", json.dumps(dabas.allergens, ensure_ascii=False) if dabas.allergens else None)
    take("nutrition", json.dumps(dabas.nutrition, ensure_ascii=False) if dabas.nutrition else None)
    take("description", dabas.description, keep_existing=product.description)
    # Kedjans hyllnamn stannar som name; en NAMNLÖS produkt får Dabas namn.
    if not (product.name or "").strip() and dabas.name:
        fields["name"] = dabas.name
    if not product.category and dabas.category:
        fields["category"] = dabas.category
    fields.update(package_verdict(product, dabas))
    # Normaliserat utdrag (inte bilder i produktion: images bara som
    # referenslista tills bildrättigheterna är verifierade).
    snapshot = json.loads(dabas.to_json())
    snapshot["images"] = [{"format": i.get("format"), "type": i.get("type")} for i in snapshot.get("images", [])]
    fields["dabas_data"] = json.dumps(snapshot, ensure_ascii=False)
    return fields


def enrich_product(db, product, client: DabasClient) -> str:
    """Ett uppslag -> status. Kraschar aldrig anroparen: varje utfall blir
    en status på produkten."""
    try:
        dabas = client.get_product(product.gtin)
    except DabasNotFound:
        db.record_dabas_check(product.id, status="not_found")
        return "not_found"
    except DabasUnauthorized as error:
        db.record_dabas_check(product.id, status="error", error=str(error))
        raise
    except DabasRateLimited as error:
        db.record_dabas_check(product.id, status="error", error=str(error))
        return "rate_limited"
    except DabasError as error:
        db.record_dabas_check(product.id, status="error", error=str(error)[:200])
        return "error"
    if dabas is None:
        db.record_dabas_check(product.id, status="error", error="GTIN i svaret validerar inte")
        return "error"
    if dabas.gtin != product.gtin:
        db.record_dabas_check(product.id, status="error", error=f"Dabas svarade med annat GTIN {dabas.gtin}")
        return "error"
    fields = merge_fields(product, dabas)
    db.apply_product_fields(product.id, fields)
    db.record_dabas_check(product.id, status="ok", source_version=dabas.changed_at or dabas.created_at)
    return "ok"


def run_enrichment(db, client: DabasClient | None = None, limit: int | None = None) -> dict:
    """Bakgrundsjobbet: kön i batchar, artigt, stoppar direkt på 401 och
    backar av på 429. Sammanfattningen är vad adminvyn visar."""
    client = client or DabasClient()
    summary = {"checked": 0, "ok": 0, "not_found": 0, "error": 0, "rate_limited": 0, "stopped": None}
    if not client.configured:
        summary["stopped"] = "DABAS_API_KEY saknas"
        return summary
    for row in db.products_needing_dabas(limit=limit or MAX_PER_RUN):
        product = db._row_to_product(row)
        try:
            outcome = enrich_product(db, product, client)
        except DabasUnauthorized as error:
            summary["stopped"] = str(error)
            break
        summary["checked"] += 1
        summary[outcome] = summary.get(outcome, 0) + 1
        if outcome == "rate_limited":
            summary["stopped"] = "rate limit - fortsätter nästa körning"
            break
    logger.info("Dabas-berikning: %s", summary)
    return summary
