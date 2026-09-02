# -*- coding: utf-8 -*-
"""Dabas (Delfi Marknadspartner AB) - produktMASTERDATA, aldrig priser.

    Prisprovider/partnerbutik  -> GTIN + pris        (vad produkten KOSTAR)
    Dabas                      -> vad produkten ÄR   (namn, märke, tillverkare,
                                                     nettoinnehåll, kategori,
                                                     ingredienser, allergener,
                                                     näring, versioner)
    Matjakt                    -> Product + ReferencePrice/StorePrice

API (Dabas WebApi v1, OpenAPI 3.0.1 hämtad från https://api.dabas.com/swagger/
v1/swagger.json 2026-09-02). Nyckeln skickas som query-parametern apikey; alla
svar finns som JSON eller XML via {format} i sökvägen:

  GET /DABASService/V2/article/gtin/{gtin}/{format}      fullständig artikel
  GET /DABASService/V2/articleversions/gtin/{gtin}/{format}  versioner
  GET /DABASService/V2/completearticlehierarchy/gtin/{gtin}/{format}
                                                          hierarki (multipack,
                                                          konsument-/DFP-enhet)
  GET /DABASService/V2/articles/datetime/{datetime}/{format}
                                                          ändrade sedan datum
  GET /DABASService/V2/categorytree/{format}              kategoriträd
  GET /DABASService/V2/articles/{format}                  alla GTIN
  Svarskoder: 200, 401 (fel nyckel), 404 (ingen artikel), 500.

NYCKELN (DABAS_API_KEY) läses bara ur miljön, loggas aldrig, ingår aldrig i
ett fel, en URL som loggas eller ett API-svar från Matjakt. _redact() tar bort
den ur varje text som kan nå en logg.

FÄLTMAPPNING (T-koder = GS1 Sverige/Validoo):
  GTIN                  GTIN (T0154), 14 siffror efter normalisering
  namn                  Produktnamn (T3337) -> RegleratProduktnamn (T4800)
                        -> Artikelkategori (T0018)
  varumärke             Varumarke.Varumarke (T0143), Undervarumarke (T2230)
  tillverkare           Varumarke.Tillverkare.Namn (T3811)
  uppgiftslämnare       Uppgiftslamnare.Foretagsnamn + GLN
  kategori              Artikelkategori (T0018), GPCKod (T0280),
                        KompletterandeProduktklass
  nettoinnehåll         Nettoinnehall[] (Mängd T0082, Enhet T0311, Typ:
                        nettovikt / volym / avrunnen vikt / antal)
                        + T4330_Nettovikt, Variabelmattsindikator (T0186 =
                        lösvikt/variabelmått)
  multipack             Forpackningar[].Antalenheter, hierarkins AntalEnheter,
                        Komponenter[]
  ingredienser          Ingredienser[].Beskrivning (T4094), Komponenter[].
                        Ingrediensforteckning
  allergener            Allergener[] (Allergen, Nivakod T4079: innehåller /
                        kan innehålla / fri från)
  näringsvärden         Naringsinfo[] -> Naringsvarden[] (Benamning, Mangd
                        T4074, Enhet T5101) per Basmangdsdeklaration (T3824)
  beskrivning           KortMarknadsbudskap[], Marknadsbudskap[],
                        Variantbeskrivning[]
  bilder                Bilder[] / MediaFiler[] (Lank T3405, Filformat T2238)
                        - LÄSES men används/cacheas INTE i produktion förrän
                        bildrättigheterna är verifierade (se docs/DABAS.md)
  version/tid           SenastAndradDatum, SkapadDatum, GiltigFROM, Slutdatum
"""

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

logger = logging.getLogger("matjakt.grocery.dabas")

API_BASE = "https://api.dabas.com/DABASService"
USER_AGENT = "Matjakt/1.0 (+https://matjakt.store)"
TIMEOUT_SECONDS = 10
# Exponentiell backoff på transienta fel (timeout, 5xx, 429). Tre försök
# räcker: ett fjärde skulle bara fördröja nattjobbet, och produkten köas om.
RETRY_DELAYS = (0.5, 1.5, 4.0)
# Rate limits är inte dokumenterade i specen. Tills de är kända håller vi en
# konservativ takt och backar av på 429 utan att bråka.
MIN_SECONDS_BETWEEN_CALLS = 0.25


class DabasError(Exception):
    """Nätverk, 5xx, oväntad form. Transient - produkten köas om."""


class DabasNotFound(DabasError):
    """404: ingen publicerad artikel för GTIN. Slutgiltigt tills nästa
    omprövning - inte ett fel i vår pipeline."""


class DabasUnauthorized(DabasError):
    """401: nyckeln saknas eller är ogiltig. Stoppar allt - ingen retry."""


class DabasRateLimited(DabasError):
    """429: backa av. Aldrig kringgå - vi väntar."""


def _redact(text: str, api_key: str | None) -> str:
    return text.replace(api_key, "***") if api_key and text else text


def normalize_gtin14(code) -> str | None:
    if code is None:
        return None
    digits = re.sub(r"\D", "", str(code))
    if len(digits) not in (8, 12, 13, 14):
        return None
    body = [int(c) for c in digits[:-1]][::-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    if (10 - total % 10) % 10 != int(digits[-1]):
        return None
    return digits.zfill(14)


@dataclass
class DabasPackage:
    """Nettoinnehållet som Matjakts prismotor förstår: mängd + enhet i
    kanonisk form (g / ml / st), plus VAD mängden är."""
    quantity: float | None = None
    unit: str | None = None            # "g", "ml", "st"
    kind: str | None = None            # NETTOVIKT / VOLYM / AVRUNNEN_VIKT / ANTAL
    drained_quantity: float | None = None
    drained_unit: str | None = None
    multipack_count: int | None = None
    variable_measure: bool = False     # lösvikt / variabelmått (T0186)
    raw: list = field(default_factory=list)


@dataclass
class DabasProduct:
    gtin: str
    name: str | None
    regulated_name: str | None
    brand: str | None
    sub_brand: str | None
    manufacturer: str | None
    supplier: str | None
    supplier_gln: str | None
    category: str | None
    gpc_code: str | None
    product_class: str | None
    package: DabasPackage
    ingredients: str | None
    allergens: list                     # [{"allergen", "level", "code"}]
    nutrition: list                     # [{"basis", "values": [{name, amount, unit}]}]
    description: str | None
    images: list                        # [{"url", "format", "type"}] - EJ för produktion
    created_at: str | None
    changed_at: str | None
    valid_from: str | None
    valid_to: str | None
    arident: int | None
    consumer_unit: bool | None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


# ---- Nettoinnehåll -> kanonisk enhet ----------------------------------------
_UNIT_MAP = {
    # massa
    "g": ("g", 1.0), "gr": ("g", 1.0), "gram": ("g", 1.0), "grm": ("g", 1.0),
    "kg": ("g", 1000.0), "kgm": ("g", 1000.0), "hg": ("g", 100.0), "mg": ("g", 0.001), "mgm": ("g", 0.001),
    # volym
    "ml": ("ml", 1.0), "mlt": ("ml", 1.0), "cl": ("ml", 10.0), "clt": ("ml", 10.0),
    "dl": ("ml", 100.0), "dlt": ("ml", 100.0), "l": ("ml", 1000.0), "lt": ("ml", 1000.0), "ltr": ("ml", 1000.0),
    # antal
    "st": ("st", 1.0), "stk": ("st", 1.0), "styck": ("st", 1.0), "pce": ("st", 1.0), "ea": ("st", 1.0),
    "h87": ("st", 1.0), "portion": ("st", 1.0), "port": ("st", 1.0),
}

_KIND_BY_TEXT = (
    ("avrunnen", "AVRUNNEN_VIKT"), ("drained", "AVRUNNEN_VIKT"),
    ("volym", "VOLYM"), ("volume", "VOLYM"),
    ("antal", "ANTAL"), ("count", "ANTAL"), ("styck", "ANTAL"),
    ("vikt", "NETTOVIKT"), ("weight", "NETTOVIKT"),
)


def _canonical(amount, unit_text):
    try:
        amount = float(str(amount).replace(",", "."))
    except (TypeError, ValueError):
        return None, None
    key = (unit_text or "").strip().lower().rstrip(".")
    mapped = _UNIT_MAP.get(key)
    if not mapped:
        return None, None
    unit, factor = mapped
    return amount * factor, unit


def _kind_of(text: str | None, unit: str | None) -> str | None:
    folded = (text or "").lower()
    for needle, kind in _KIND_BY_TEXT:
        if needle in folded:
            return kind
    if unit == "ml":
        return "VOLYM"
    if unit == "g":
        return "NETTOVIKT"
    if unit == "st":
        return "ANTAL"
    return None


def _as_list(value) -> list:
    """JSON ger listor; XML ger ett wrapper-element ({"NetContentModel":
    {...}} eller {"NetContentModel": [...]}) eller ett ensamt objekt. Allt
    blir en lista av dictar - utan att gissa om innehållet."""
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        if len(value) == 1:
            inner = next(iter(value.values()))
            if isinstance(inner, (list, dict)):
                return _as_list(inner)
        return [value]
    return []


def package_from_article(article: dict) -> DabasPackage:
    """Plockar det nettoinnehåll som ska styra paketmatten.

    Prioritet: AVRUNNEN VIKT (det är maten, inte lagen) > NETTOVIKT >
    VOLYM > ANTAL. Ett innehåll utan tolkbar enhet ignoreras - hellre
    "okänt" än gissat. Lösvikt/variabelmått (T0186) flaggas: ett sådant
    GTIN har ingen fast förpackningsmängd."""
    package = DabasPackage(variable_measure=bool(article.get("Variabelmattsindikator")))
    candidates = []
    for entry in _as_list(article.get("Nettoinnehall")):
        quantity, unit = _canonical(entry.get("Mängd", entry.get("Mangd")), entry.get("EnhetKod") or entry.get("Enhet"))
        kind = _kind_of(entry.get("Typ"), unit)
        package.raw.append({"amount": entry.get("Mängd", entry.get("Mangd")), "unit": entry.get("EnhetKod") or entry.get("Enhet"),
                            "type": entry.get("Typ"), "canonical": [quantity, unit, kind]})
        if quantity is None or quantity <= 0:
            continue
        candidates.append((kind, quantity, unit))
    net_weight = article.get("T4330_Nettovikt") or {}
    if isinstance(net_weight, dict) and net_weight.get("T4330_Värde") is not None:
        quantity, unit = _canonical(net_weight.get("T4330_Värde"), net_weight.get("T3780_Kod") or net_weight.get("T3780_Namn"))
        if quantity:
            candidates.append(("NETTOVIKT", quantity, unit))

    priority = {"AVRUNNEN_VIKT": 0, "NETTOVIKT": 1, "VOLYM": 2, "ANTAL": 3, None: 4}
    candidates.sort(key=lambda c: priority.get(c[0], 4))
    for kind, quantity, unit in candidates:
        if kind == "AVRUNNEN_VIKT":
            package.drained_quantity, package.drained_unit = quantity, unit
    for kind, quantity, unit in candidates:
        if kind == "AVRUNNEN_VIKT":
            package.quantity, package.unit, package.kind = quantity, unit, kind
            break
    if package.quantity is None and candidates:
        kind, quantity, unit = candidates[0]
        package.quantity, package.unit, package.kind = quantity, unit, kind

    counts = []
    for wrap in _as_list(article.get("Forpackningar")):
        try:
            n = int(float(str(wrap.get("Antalenheter")).replace(",", ".")))
        except (TypeError, ValueError):
            continue
        if n > 1:
            counts.append(n)
    if counts:
        package.multipack_count = max(counts)
    return package


def normalize_article(article: dict) -> DabasProduct | None:
    """En Dabas-artikel -> DabasProduct. None när GTIN saknas eller inte
    validerar - vi lagrar aldrig masterdata utan giltig nyckel."""
    gtin = normalize_gtin14(article.get("GTIN"))
    if not gtin:
        return None
    brand = article.get("Varumarke") or {}
    supplier = article.get("Uppgiftslamnare") or {}
    allergens = [{"allergen": a.get("Allergen"), "level": a.get("NivakodText") or a.get("Niva"),
                  "code": a.get("Nivakod") or a.get("Allergenkod")}
                 for a in _as_list(article.get("Allergener")) if a.get("Allergen")]
    nutrition = []
    for block in _as_list(article.get("Naringsinfo")):
        values = [{"name": n.get("Benamning"), "amount": n.get("Mangd"), "unit": n.get("Enhet")}
                  for n in _as_list(block.get("Naringsvarden")) if n.get("Benamning")]
        if values:
            nutrition.append({"basis": block.get("Basmangdsdeklaration_Formatted") or block.get("Basmangdsdeklaration"),
                              "basisUnit": block.get("Mattkvalificerarebasmangd"),
                              "state": block.get("Tillagningsstatus"), "values": values})
    ingredients = None
    parts = [i.get("Beskrivning") for i in _as_list(article.get("Ingredienser")) if i.get("Beskrivning")]
    if parts:
        ingredients = " ".join(parts)
    else:
        for component in _as_list(article.get("Komponenter")):
            if component.get("Ingrediensforteckning"):
                ingredients = component["Ingrediensforteckning"]
                break
    description = None
    for key in ("KortMarknadsbudskap", "Marknadsbudskap", "Variantbeskrivning"):
        for item in _as_list(article.get(key)) or ([article.get(key)] if isinstance(article.get(key), str) else []):
            text = item.get("Text") or item.get("Beskrivning") or item.get("Budskap") or (item if isinstance(item, str) else None)
            if text:
                description = str(text)
                break
        if description:
            break
    images = [{"url": m.get("Lank"), "format": m.get("Filformat"), "type": m.get("Informationstyp")}
              for m in (_as_list(article.get("Bilder")) + _as_list(article.get("MediaFiler"))) if m.get("Lank")]

    return DabasProduct(
        gtin=gtin,
        name=article.get("Produktnamn") or article.get("RegleratProduktnamn") or article.get("Artikelkategori"),
        regulated_name=article.get("RegleratProduktnamn"),
        brand=brand.get("Varumarke") if isinstance(brand, dict) else None,
        sub_brand=article.get("Undervarumarke"),
        manufacturer=((brand.get("Tillverkare") or {}).get("Namn") if isinstance(brand, dict) else None),
        supplier=supplier.get("Foretagsnamn") if isinstance(supplier, dict) else None,
        supplier_gln=supplier.get("GLN") if isinstance(supplier, dict) else None,
        category=article.get("Artikelkategori"),
        gpc_code=article.get("GPCKod"),
        product_class=article.get("KompletterandeProduktklass"),
        package=package_from_article(article),
        ingredients=ingredients,
        allergens=allergens,
        nutrition=nutrition,
        description=description,
        images=images,
        created_at=article.get("SkapadDatum"),
        changed_at=article.get("SenastAndradDatum"),
        valid_from=article.get("GiltigFROM"),
        valid_to=article.get("Slutdatum"),
        arident=article.get("ARIDENT"),
        consumer_unit=article.get("Konsumentartikel"),
    )


# ---- XML -> dict (samma form som JSON-svaret) --------------------------------
def _xml_to_obj(element):
    children = list(element)
    if not children:
        return element.text
    # Upprepade barn med samma tagg = lista (Nettoinnehall/NetContentModel).
    tags = [child.tag.split("}")[-1] for child in children]
    if len(set(tags)) == 1 and len(tags) > 1:
        return [_xml_to_obj(child) for child in children]
    result = {}
    for child in children:
        tag = child.tag.split("}")[-1]
        value = _xml_to_obj(child)
        if tag in result:
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(value)
        else:
            result[tag] = value
    return result


def parse_article_payload(body: bytes, content_type: str | None) -> dict:
    """JSON eller XML -> dict. Fel form -> DabasError (aldrig ett halvt
    tolkat objekt)."""
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        raise DabasError("tomt svar")
    is_xml = text.startswith("<") or (content_type or "").lower().find("xml") >= 0
    try:
        if is_xml:
            root = ET.fromstring(text)
            obj = _xml_to_obj(root)
            if not isinstance(obj, dict):
                raise DabasError("oväntad XML-form")
            return obj
        obj = json.loads(text)
    except (ET.ParseError, json.JSONDecodeError) as error:
        raise DabasError(f"svaret gick inte att tolka: {type(error).__name__}")
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    if not isinstance(obj, dict):
        raise DabasError("oväntad svarsform")
    return obj


class DabasClient:
    def __init__(self, api_key: str | None = None, fmt: str = "JSON", opener=None):
        self._api_key = api_key if api_key is not None else os.environ.get("DABAS_API_KEY")
        self._format = fmt
        self._open = opener or urllib.request.urlopen
        self._last_call = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _url(self, path: str) -> str:
        return f"{API_BASE}{path}?{urllib.parse.urlencode({'apikey': self._api_key or ''})}"

    def _get(self, path: str) -> dict:
        if not self._api_key:
            raise DabasUnauthorized("DABAS_API_KEY är inte satt")
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        last_error = None
        for attempt, delay in enumerate((0.0,) + RETRY_DELAYS):
            if delay:
                time.sleep(delay)
            self._last_call = time.monotonic()
            request = urllib.request.Request(self._url(path), headers={
                "User-Agent": USER_AGENT, "Accept": "application/json" if self._format == "JSON" else "application/xml"})
            try:
                with self._open(request, timeout=TIMEOUT_SECONDS) as response:
                    return parse_article_payload(response.read(), response.headers.get("Content-Type"))
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    raise DabasNotFound("ingen publicerad artikel")
                if error.code == 401:
                    raise DabasUnauthorized("Dabas avvisade API-nyckeln (401)")
                if error.code == 429:
                    last_error = DabasRateLimited("Dabas rate limit (429)")
                    continue
                last_error = DabasError(f"HTTP {error.code}")
                if error.code < 500:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = DabasError(_redact(f"nätverksfel: {type(error).__name__}", self._api_key))
            except DabasError as error:
                last_error = error
                break
        raise last_error or DabasError("okänt fel")

    def get_article(self, gtin: str) -> dict:
        code = normalize_gtin14(gtin)
        if not code:
            raise DabasNotFound("ogiltigt GTIN")
        # Dabas kanoniska form är GTIN-14 MED inledande nolla: 07310865093530
        # svarar 200, 7310865093530 svarar 404 (verifierat live 2026-09-02).
        return self._get(f"/V2/article/gtin/{code}/{self._format}")

    def get_product(self, gtin: str) -> DabasProduct | None:
        return normalize_article(self.get_article(gtin))

    def get_hierarchy(self, gtin: str) -> dict:
        code = normalize_gtin14(gtin)
        if not code:
            raise DabasNotFound("ogiltigt GTIN")
        return self._get(f"/V2/completearticlehierarchy/gtin/{code}/{self._format}")

    def changed_since(self, when: str) -> dict:
        return self._get(f"/V2/articles/datetime/{urllib.parse.quote(when)}/{self._format}")

    def category_tree(self) -> dict:
        return self._get(f"/V2/categorytree/{self._format}")
