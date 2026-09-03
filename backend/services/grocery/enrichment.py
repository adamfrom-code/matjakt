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
    DABAS_VERIFIED  >  PROVIDER_VERIFIED  >  NORMALIZED  (>  NONE)
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
    provider 450 g  + Dabas saknar  -> PROVIDER_VERIFIED/NORMALIZED oförändrat
    Dabas variabelmått/lösvikt      -> providerns cirkavikt får stå, märkt
Tolerans 2 % för avrundning (ca-vikt 750 vs 745).

KANONISK MATCHNING: dabas_category sparas på produkten och prövas i
prismotorn som en extra REJECT-signal genom samma avdelningsvakt som
kedjornas kategorier - "Kanel" mot Dabas-kategori "Knäckebröd" faller,
oavsett produktnamn. Dabas stärker reglerna, ersätter dem inte.

AKTIVERING (2026-09-02, Adam): PÅ så snart DABAS_API_KEY finns - text,
paket och kategori. Bilder är avstängda i koden oavsett flagga.
MATJAKT_DABAS_ENRICHMENT_ENABLED=0 stänger av. Rate limit observerad:
~300 ms/anrop, inga 429 vid 0,3 s takt (docs/DABAS.md).
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
# 4 000 uppslag per pass vid ~0,3 s/anrop = ~20 min; hela katalogen (15 600
# GTIN) på tre-fyra pass, sedan bara nya och omprövade GTIN per natt.
MAX_PER_RUN = int(os.environ.get("MATJAKT_DABAS_MAX_PER_RUN", "4000"))

# Källnivåer för paketdata (Adams tre nivåer, 2026-09-02):
SOURCE_DABAS = "DABAS_VERIFIED"          # Dabas och provider eniga, eller bara Dabas
SOURCE_PROVIDER = "PROVIDER_VERIFIED"    # providern gav mängd + enhet explicit
SOURCE_NORMALIZED = "NORMALIZED"         # bara tolkat ur size-/namntext
SOURCE_NONE = "NONE"                     # ingen mängd - raden förblir osäker


def enrichment_enabled() -> bool:
    """PÅ så snart DABAS_API_KEY finns (Adam aktiverade text/paket/kategori
    2026-09-02); MATJAKT_DABAS_ENRICHMENT_ENABLED=0 stänger av. Bilder
    berörs aldrig av den här flaggan - de är avstängda i koden."""
    if not os.environ.get("DABAS_API_KEY"):
        return False
    return str(os.environ.get("MATJAKT_DABAS_ENRICHMENT_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}


def _same_amount(a: float, b: float) -> bool:
    return abs(a - b) <= max(a, b) * PACKAGE_TOLERANCE


def provider_view(product):
    """Produkten sedd som PROVIDERN levererade den: provider_* i stället för
    de upplösta fälten, och utan konfliktflaggan (den får prismotorn att
    svara "okänt" - det är fail closed för prissättningen, men för
    verdiktet betyder det inte att providern saknar mängd). Saknas
    provider_* (rad från före kolumnerna) används de upplösta fälten -
    utom när Dabas redan skrivit dem: då är providerns värde okänt."""
    import dataclasses
    has_provider = bool(getattr(product, "provider_size", None) or getattr(product, "provider_quantity", None))
    if has_provider:
        return dataclasses.replace(product, size=product.provider_size, quantity=product.provider_quantity,
                                   unit=product.provider_unit, package_conflict=None)
    if getattr(product, "package_source", None) == SOURCE_DABAS:
        return dataclasses.replace(product, size=None, quantity=None, unit=None, package_conflict=None)
    return dataclasses.replace(product, package_conflict=None)


def _provider_package(product):
    """Providerns tolkning i kanonisk enhet, via prismotorns egen läsning."""
    from .pricing import effective_package
    try:
        quantity, unit = effective_package(provider_view(product))
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


def provider_source(product) -> str:
    """Vilken nivå providerns paketdata har, utan Dabas inblandat:
    explicit mängd+enhet från kedjans API = PROVIDER_VERIFIED, bara tolkad
    ur text = NORMALIZED, inget = NONE."""
    view = provider_view(product)
    if view.quantity and view.unit:
        return SOURCE_PROVIDER
    from .pricing import effective_package
    try:
        quantity, unit = effective_package(view)
    except Exception:
        quantity = None
    return SOURCE_NORMALIZED if quantity else SOURCE_NONE


def backfill_provider_fields(db) -> int:
    """Rader från före provider_*-kolumnerna: kopiera de upplösta värdena
    dit - de ÄR providerns, så länge Dabas inte skrivit dem. Rader som
    Dabas redan fyllt lämnas tomma tills nästa import levererar providerns
    värde (nattjobben för Willys/Hemköp/City Gross gör det automatiskt)."""
    with db.connection:
        cursor = db.connection.execute(
            "UPDATE grocery_products SET provider_size = size, provider_quantity = quantity, provider_unit = unit "
            "WHERE provider_size IS NULL AND provider_quantity IS NULL "
            "AND (size IS NOT NULL OR quantity IS NOT NULL) "
            "AND COALESCE(package_source, '') != 'DABAS_VERIFIED'")
    return cursor.rowcount


def classify_package_sources(db, limit: int | None = None) -> dict:
    """Sätter package_source på produkter som saknar den - så varje rad bär
    sin nivå även utan Dabas-uppslag. Idempotent, rör aldrig Dabas-satta
    rader och aldrig priser."""
    rows = db.connection.execute(
        "SELECT * FROM grocery_products WHERE package_source IS NULL"
        + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    counts = {}
    for row in rows:
        product = db._row_to_product(row)
        source = provider_source(product)
        confidence = ("provider" if source == SOURCE_PROVIDER
                      else "normalized" if source == SOURCE_NORMALIZED else "none")
        db.apply_product_fields(product.id, {"package_source": source, "package_confidence": confidence})
        counts[source] = counts.get(source, 0) + 1
    return counts


# Private label per kedja - för täckningsrapporten "per varumärkestyp".
PRIVATE_LABELS = {"garant", "eldorado", "ica", "ica basic", "ica selection", "ica i love eco", "coop", "änglamark",
                  "xtra", "x-tra", "favorit", "hemköp", "willys", "city gross", "prime", "milbona", "pilos", "freshona",
                  "combino", "solevita", "cien", "dulano", "bellarom", "vemondo", "chef select", "kania"}


def brand_type(brand: str | None) -> str:
    if not brand or not str(brand).strip():
        return "utan varumärke"
    folded = str(brand).strip().lower()
    if folded in PRIVATE_LABELS or folded.startswith(("ica ", "coop ", "garant ")):
        return "private label"
    return "märkesvara"


def coverage_report(db) -> dict:
    """Faktisk Dabas-träffgrad per kedja och varumärkestyp, över de GTIN som
    faktiskt slagits upp (dabas_status satt). Ren aggregering i SQL - den
    körs i /api/health och får inte kosta sekunder."""
    total_row = db.connection.execute(
        "SELECT COUNT(*) AS n, SUM(dabas_status = 'ok') AS ok, SUM(dabas_status IN ('ok', 'not_found')) AS looked "
        "FROM grocery_products WHERE gtin IS NOT NULL AND gtin != ''").fetchone()
    per_chain = {}
    for row in db.connection.execute(
            # DISTINCT produkter per kedja - en produkt kan ha flera externa
            # id:n i samma kedja (Willys räknades 21 736 gånger på 10 854 varor).
            "SELECT chain, SUM(looked) AS looked, SUM(ok) AS ok FROM ("
            "  SELECT x.chain, p.id, MAX(p.dabas_status IN ('ok', 'not_found')) AS looked, MAX(p.dabas_status = 'ok') AS ok "
            "  FROM grocery_product_external_ids x JOIN grocery_products p ON p.id = x.product_id "
            "  WHERE p.gtin IS NOT NULL AND p.gtin != '' GROUP BY x.chain, p.id) GROUP BY chain"):
        per_chain[row["chain"]] = {"uppslagna": row["looked"] or 0, "traff": row["ok"] or 0}
    per_brand = {}
    for row in db.connection.execute(
            "SELECT brand, SUM(dabas_status IN ('ok', 'not_found')) AS looked, SUM(dabas_status = 'ok') AS ok "
            "FROM grocery_products WHERE gtin IS NOT NULL AND gtin != '' AND dabas_status IS NOT NULL GROUP BY brand"):
        b = per_brand.setdefault(brand_type(row["brand"]), {"uppslagna": 0, "traff": 0})
        b["uppslagna"] += row["looked"] or 0
        b["traff"] += row["ok"] or 0
    sources = {row[0] or "NULL": row[1] for row in db.connection.execute(
        "SELECT package_source, COUNT(*) FROM grocery_products WHERE gtin IS NOT NULL AND gtin != '' GROUP BY package_source")}
    confidence = {row[0] or "NULL": row[1] for row in db.connection.execute(
        "SELECT package_confidence, COUNT(*) FROM grocery_products WHERE gtin IS NOT NULL AND gtin != '' GROUP BY package_confidence")}

    def pct(b):
        return round(100 * b["traff"] / b["uppslagna"], 1) if b["uppslagna"] else None

    total = {"uppslagna": total_row["looked"] or 0, "traff": total_row["ok"] or 0}
    return {
        "totalt": {**total, "procent": pct(total)},
        "perKedja": {k: {**v, "procent": pct(v)} for k, v in sorted(per_chain.items())},
        "perVarumarkestyp": {k: {**v, "procent": pct(v)} for k, v in sorted(per_brand.items())},
        "packageSource": sources, "packageConfidence": confidence,
        "gtinTotalt": total_row["n"] or 0,
    }


def _amounts_in_text(text: str | None) -> list[tuple[float, str]]:
    """Alla mängder i en size-/namntext, i kanonisk enhet: "370/240g" ->
    [(370, g), (240, g)], "800g/6l" -> [(800, g), (6000, ml)]."""
    import re
    found = []
    for amount, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*(kg|g|gram|ml|cl|dl|l)\b", (text or "").lower()):
        try:
            value = float(amount.replace(",", "."))
        except ValueError:
            continue
        factor = {"kg": (1000, "g"), "g": (1, "g"), "gram": (1, "g"), "ml": (1, "ml"), "cl": (10, "ml"),
                  "dl": (100, "ml"), "l": (1000, "ml")}[unit]
        found.append((value * factor[0], factor[1]))
    # "370/240g": det första talet ärver enheten från det andra.
    for first, second, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|dl|l)\b", (text or "").lower()):
        factor = {"kg": (1000, "g"), "g": (1, "g"), "ml": (1, "ml"), "cl": (10, "ml"), "dl": (100, "ml"), "l": (1000, "ml")}[unit]
        try:
            found.append((float(first.replace(",", ".")) * factor[0], factor[1]))
        except ValueError:
            pass
    return found


def _equivalent(p_qty, p_unit, d_qty, d_unit) -> bool:
    """Samma mängd, med gram och milliliter likvärdiga: Dabas anger
    nettovikt i gram även för vätskor (1 500 ml mjölk = 1 500 g) och det
    är ingen konflikt - det är densitet ~1, samma köksstandard som
    prismotorn redan använder för mejeri."""
    if p_qty is None or d_qty is None:
        return False
    same_family = p_unit == d_unit or {p_unit, d_unit} <= {"g", "ml"}
    return same_family and _same_amount(p_qty, d_qty)


def package_verdict(product, dabas: DabasProduct) -> dict:
    """Fälten package_source/package_confidence/package_conflict + ev. ny
    quantity/unit/size, utifrån provider mot Dabas.

    Verkliga konflikter (samma mängdfamilj, olika tal, providern explicit)
    faller stängt. Falska larm - som första produktionsmätningen var full
    av - gör det inte:
      - vätska: provider 1 500 ml, Dabas 1 500 g nettovikt -> eniga
      - avrunnen vikt: provider 240 g ur "370/240g", Dabas 370 g -> eniga
        (Dabas talet står i providerns text; motorns avrunnen-regel gäller)
      - torrvara + tillagad volym: provider tolkade "800g/6l" som 6 l,
        Dabas 800 g -> Dabas vinner (talet finns i texten, providerns var
        en texttolkning, inte en explicit mängd)
      - antal mot vikt: Dabas 18 st, provider 750 g -> ingen konflikt,
        providerns vikt står, antalet noteras som multipack"""
    p_qty, p_unit = _provider_package(product)
    d = dabas.package
    base_source = provider_source(product)
    base_conf = "provider" if p_qty else "none"
    view = provider_view(product)
    # Providerns egna värden - de UPPLÖSTA fälten återställs till dem i
    # varje utfall som inte uttryckligen låter Dabas fylla/vinna, så att en
    # tidigare (felaktig) överskrivning hälar när providern är känd.
    restore = ({"size": view.size, "quantity": view.quantity, "unit": view.unit}
               if (view.size or view.quantity) else {})

    if d.variable_measure or d.quantity is None or d.unit is None:
        # Dabas har ingen fast mängd att verifiera mot: providerns nivå
        # står kvar oförändrad - hål skapas aldrig av att Dabas saknar data.
        return {"package_source": base_source, "package_confidence": base_conf, "package_conflict": None, **restore}

    if p_qty is None:
        if getattr(product, "package_source", None) == SOURCE_DABAS and not (view.size or view.quantity):
            # Providerns värde är okänt (raden fylldes av Dabas innan
            # provider_* fanns): rör ingenting förrän nästa import säger
            # vad providern har. Ingen ny fyllning över okända värden.
            return {"package_source": SOURCE_DABAS, "package_confidence": "high", "package_conflict": None}
        return {"package_source": SOURCE_DABAS, "package_confidence": "high", "package_conflict": None,
                "quantity": d.quantity, "unit": d.unit, "size": f"{d.quantity:g} {d.unit}"}

    explicit = bool(view.quantity and view.unit)
    dabas_amounts = [(d.quantity, d.unit)] + (
        [(d.drained_quantity, d.drained_unit)] if d.drained_quantity else [])
    if any(_equivalent(p_qty, p_unit, dq, du) for dq, du in dabas_amounts):
        verdict = {"package_source": SOURCE_DABAS, "package_confidence": "high", "package_conflict": None, **restore}
        if not explicit:
            # Providern hade bara en texttolkning; nu är mängden verifierad -
            # skriv den som explicit mängd (samma tal, Dabas enhet).
            verdict.update({"quantity": d.quantity, "unit": d.unit})
        return verdict

    # Antal mot vikt/volym är två olika sanningar om samma paket, inte en
    # konflikt: "18-pack" och "750 g" stämmer båda.
    if (d.unit == "st") != (p_unit == "st"):
        return {"package_source": base_source, "package_confidence": base_conf, "package_conflict": None, **restore}

    text_amounts = _amounts_in_text(f"{view.size or ''} {product.name or ''}")
    dabas_in_text = any(_equivalent(tq, tu, d.quantity, d.unit) for tq, tu in text_amounts)
    # EXAKT samma enhet (g mot g): nettovikt/avrunnen-paret. Olika familj
    # (ml mot g) är torrvara/tillagad-paret och hanteras nedan.
    if dabas_in_text and p_unit == d.unit:
        # "370/240g": nettovikt och avrunnen vikt i samma text. Providern
        # (motorns regel) valde den avrunna - det är maten, inte lagen -
        # och Dabas nettovikt står i samma text. Eniga, inget byte.
        return {"package_source": SOURCE_DABAS, "package_confidence": "high", "package_conflict": None, **restore}
    if dabas_in_text and not explicit:
        # "800g/6l": torrvara och tillagad volym i samma text - providerns
        # tolkning tog volymen, Dabas pekar ut förpackningen. Dabas vinner.
        return {"package_source": SOURCE_DABAS, "package_confidence": "high", "package_conflict": None,
                "quantity": d.quantity, "unit": d.unit, "size": view.size or f"{d.quantity:g} {d.unit}"}

    # ÄKTA KONFLIKT: flaggas, och de upplösta fälten återställs till
    # providerns - Dabas skriver aldrig över ett explicit providervärde.
    return {"package_source": base_source, "package_confidence": "conflict",
            "package_conflict": f"provider {p_qty:g} {p_unit} / Dabas {d.quantity:g} {d.unit} ({d.kind})", **restore}


def recompute_verdicts(db) -> dict:
    """Räknar om paketverdiktet för alla Dabas-berikade produkter ur den
    sparade dabas_data-ögonblicksbilden - inga nya API-anrop. Körs efter en
    regeländring i package_verdict så gamla falska konflikter försvinner."""
    from .providers.dabas import DabasPackage, DabasProduct as _DP
    rows = db.connection.execute(
        "SELECT * FROM grocery_products WHERE dabas_status = 'ok' AND dabas_data IS NOT NULL").fetchall()
    counts = {}
    for row in rows:
        product = db._row_to_product(row)
        try:
            snap = json.loads(row["dabas_data"])
            snap["package"] = DabasPackage(**{k: v for k, v in (snap.get("package") or {}).items()
                                             if k in DabasPackage.__dataclass_fields__})
            dabas = _DP(**{k: v for k, v in snap.items() if k in _DP.__dataclass_fields__})
        except Exception:
            continue
        verdict = package_verdict(product, dabas)
        db.apply_product_fields(product.id, verdict)
        counts[verdict["package_confidence"]] = counts.get(verdict["package_confidence"], 0) + 1
    return counts


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
