# -*- coding: utf-8 -*-
"""Partnerfeed-parser: butikens prisfil -> normaliserade FeedRow-rader.

En partnerbutik skickar sina priser som CSV, JSON (fil eller HTTP-POST-
kropp, formatet "API") eller XLSX. Den här modulen gör EN sak: läser
feeden och plockar ut de kolumner vi känner igen, i normaliserad form.
Kanonisk matchning, paketparser, prissanering och quality gate ligger i
andra delar av systemet - inget som kommer härifrån publiceras direkt,
så butiken kan aldrig trycka in dålig data i appen via den här vägen.

Kontraktet är "ärlig och robust":
- En trasig rad ger en FeedError med radnummer och orsak; övriga rader
  bearbetas som vanligt. Feeden som helhet kraschar aldrig på en rad.
- Inga gissningar. Ett pris som inte går att tolka blir ett radfel (raden
  utesluts), inte 0. Ett datum som inte går att tolka blir None plus en
  notis. En GTIN vars kontrollsiffra inte stämmer blir None (raden behålls
  om den kan identifieras på annat sätt), eftersom en felaktig GTIN skulle
  slå ihop två olika produkter i den kanoniska matchningen - exakt det
  felet matchningsreglerna finns för att förhindra.
- Inga sidoeffekter, ingen nätverksåtkomst, bara stdlib (som resten av
  backend/services/*).

Radnumrering: line_number räknar DATARADER (1 = första raden efter
rubrikraden) i alla format, så att samma innehåll som CSV, JSON och XLSX
ger samma radnummer. Excel-radnumret är alltså line_number + 1. Fysiska
radnummer i en CSV är ändå inte pålitliga (citerade fält får innehålla
radbrytningar). line_number 0 betyder "hela feeden" - t.ex. ogiltig JSON,
en xlsx som inte går att öppna eller en rubrikrad utan identitetskolumn.

Flera FeedError kan gälla samma rad (t.ex. både en GTIN-notis och ett
datumfel) - listan är en felrapport till partnern, inte en boolean.
"""

import csv
import io
import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone

__all__ = [
    "FEED_FORMATS", "MAX_ROWS", "FeedRow", "FeedError", "ParsedFeed", "parse_feed",
]

FEED_FORMATS = ("CSV", "JSON", "XLSX", "API")

# Taket skyddar servern, inte partnern: 50 000 rader täcker det största
# sortiment vi sett (en Maxi-katalog är ~25 000 artiklar) med marginal, och
# allt över det är nästan säkert en felexport (dubblerade rader, hela
# prishistoriken) som gör mer nytta som ett tidigt stopp än som en timmes
# bearbetning. Läses vid anrop, inte vid import, så tester kan patcha det.
MAX_ROWS = 50_000

# Ett blad i en xlsx är zip-komprimerat; en avsiktligt konstruerad fil kan
# packa upp till gigabyte ur några kilobyte. 200 MB rå-XML räcker gott för
# MAX_ROWS rader med ett dussin kolumner.
_MAX_XLSX_PART_BYTES = 200 * 1024 * 1024

# Kolumnalias, svenska och engelska. Nycklarna är FeedRow-fälten; varje alias
# är skrivet i samma normaliserade form som _normalize_header producerar
# (gemener, understreck), så uppslaget blir ett rent dict-uppslag.
_COLUMN_ALIASES = {
    "gtin": ("gtin", "ean", "streckkod"),
    "external_product_id": ("artikelnummer", "external_product_id", "sku", "artnr"),
    # "Produktnamn" är den rubrik en butik skriver först - den måste tas.
    "name": ("namn", "name", "produkt", "product", "benämning", "produktnamn",
             "varunamn", "artikelnamn", "product_name"),
    "brand": ("märke", "brand", "varumärke"),
    "package": ("storlek", "package", "förpackning", "size", "pack"),
    "regular_price": ("pris", "regular_price", "ordinarie", "ordinarie_pris", "price"),
    "campaign_price": ("kampanjpris", "campaign_price", "kampanj", "extrapris"),
    "member_price": ("medlemspris", "member_price"),
    "campaign_valid_to": ("kampanj_till", "campaign_valid_to", "giltig_till", "valid_to"),
    "category": ("kategori", "category"),
}
_FIELD_BY_ALIAS = {
    alias: field for field, aliases in _COLUMN_ALIASES.items() for alias in aliases
}

# Minst en av dessa måste finnas för att en rad ska kunna betyda något
# nedströms - utan identitet finns inget att matcha priset mot.
_IDENTITY_FIELDS = ("name", "gtin", "external_product_id")

# (fält, etikett i felrapporten) - etiketten är svensk eftersom rapporten
# läses av partnerns butiksansvarige, inte av en utvecklare.
_PRICE_FIELDS = (
    ("regular_price", "pris"),
    ("campaign_price", "kampanjpris"),
    ("member_price", "medlemspris"),
)

# Nycklar under vilka ett JSON-objekt kan bära sin radlista.
_JSON_LIST_KEYS = ("rows", "items", "produkter", "products")

_UTC = timezone.utc
# Excel räknar dagar från 1899-12-30 (dag 1 = 1900-01-01, med den kända
# 1900-skottårsbuggen inbakad). 25569 = antal dagar fram till 1970-01-01.
_EXCEL_EPOCH_OFFSET_DAYS = 25569
_EXCEL_SERIAL_MAX = 2958465  # 9999-12-31

_XLSX_REL_ID_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_XLSX_DEFAULT_SHEET = "xl/worksheets/sheet1.xml"

_PRICE_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_CURRENCY_SUFFIX_RE = re.compile(r"\s*(?:kr|sek|:-)\.?\s*$", re.IGNORECASE)
# \u00a0 (hårt mellanslag) och \u202f (smalt hårt mellanslag) är vad Excel och
# LibreOffice skriver som tusentalsavgränsare i svensk lokal.
_ANY_WHITESPACE_RE = re.compile("[\\s\u00a0\u202f]+")
_BOM = "\ufeff"
_SCIENTIFIC_RE = re.compile(r"^\d+(?:\.\d+)?[eE][+-]?\d+$")
_TRAILING_ZERO_DECIMALS_RE = re.compile(r"^\d+\.0+$")
# "30/9 2026", "30/9-2026", "30/09/2026", "30.9.2026", valfritt "23:59[:59]".
_SWEDISH_DATE_RE = re.compile(
    r"^(\d{1,2})[./](\d{1,2})[\s./-]+(\d{4})"
    r"(?:[\sT]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)
_CELL_REF_RE = re.compile(r"^([A-Za-z]+)(\d*)$")


@dataclass(frozen=True)
class FeedRow:
    """En rad ur feeden, normaliserad men INTE sanerad: priserna är vad
    butiken skrev (bara tolkade till tal), package är råtexten ("500 g",
    "1,5 l", "6-pack") som paketparsern tar hand om, gtin är antingen en
    kontrollsiffre-validerad 14-siffrig kod eller None."""

    gtin: str | None
    external_product_id: str | None
    name: str
    brand: str | None
    package: str | None
    regular_price: float | None
    campaign_price: float | None
    member_price: float | None
    campaign_valid_to: float | None
    category: str | None
    line_number: int


@dataclass
class FeedError:
    """Ett problem på en rad (line_number >= 1) eller med hela feeden
    (line_number == 0). reason är skriven för partnern, på svenska."""

    line_number: int
    reason: str


@dataclass
class ParsedFeed:
    """rows: raderna som gick att tolka. errors: allt som inte gick, plus
    notiser om fält som sattes till None. total_lines: antal datarader som
    lästes (tomma rader medräknade, rubrikraden inte) - så att
    len(rows) + uteslutna = total_lines går att stämma av."""

    rows: list[FeedRow]
    errors: list[FeedError]
    format: str
    total_lines: int


def parse_feed(format: str, payload: bytes | str | list | dict) -> ParsedFeed:
    """Parsar en partnerfeed. format är ett av FEED_FORMATS ("API" är en
    JSON-kropp från en HTTP-POST och parsas exakt som "JSON"; skillnaden
    finns bara så att ParsedFeed.format speglar varifrån feeden kom).

    Fel i DATAN rapporteras alltid som FeedError, aldrig som undantag.
    Fel i ANROPET (okänt format, payload av fel typ för formatet) är
    programmeringsfel hos anroparen och ger ValueError/TypeError."""
    fmt = str(format or "").strip().upper()
    if fmt not in FEED_FORMATS:
        raise ValueError(f"Okänt feedformat {format!r} - förväntade ett av {FEED_FORMATS}")

    if fmt == "CSV":
        if not isinstance(payload, (bytes, bytearray, str)):
            raise TypeError("CSV-feed måste vara bytes eller str")
        text = _decode_text(payload)
        return _parse_table(_csv_rows(text), fmt, excel_dates=False)

    if fmt in ("JSON", "API"):
        return _parse_json(payload, fmt)

    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("XLSX-feed måste vara bytes")
    return _parse_xlsx(bytes(payload))


# --------------------------------------------------------------------------
# Rubriker och fältvärden (gemensamt för alla format)
# --------------------------------------------------------------------------

def _normalize_header(text) -> str:
    """"Ordinarie Pris (kr)" -> "ordinarie_pris". Skiftläge, mellanslag/
    understreck/bindestreck och en avslutande parentes ("(kr)", "(EAN-13)")
    ska inte avgöra om en kolumn känns igen - det är partnerns exportverktyg
    som väljer sådant, inte partnern."""
    value = str(text if text is not None else "").replace(_BOM, "").strip().casefold()
    value = re.sub(r"\s*\([^)]*\)\s*$", "", value)
    return re.sub(r"[\s_\-]+", "_", value).strip("_")


def _map_header(cells) -> tuple[dict[int, str], list[str]]:
    """Kolumnindex -> FeedRow-fält för de rubriker vi känner igen, plus en
    lista över dem vi inte gjorde (till felrapporten). Första förekomsten
    vinner om två rubriker pekar på samma fält - deterministiskt, och det
    vanligaste fallet är en duplicerad kolumn med samma innehåll."""
    column_map: dict[int, str] = {}
    unknown: list[str] = []
    for index, cell in enumerate(cells):
        if cell is None or (isinstance(cell, str) and not cell.strip()):
            continue
        field = _FIELD_BY_ALIAS.get(_normalize_header(cell))
        if field is None:
            unknown.append(str(cell).strip())
        elif field not in column_map.values():
            column_map[index] = field
    return column_map, unknown


def _text(value) -> tuple[str | None, str | None]:
    """Råvärde -> textfält, (värde, felorsak). Tomt -> None. Tal från Excel/
    JSON blir text ("12345.0" -> "12345") eftersom artikelnummer och
    storlekar ofta ligger som tal i kalkylblad. Bool/objekt/listor är inte
    text: felet rapporteras hellre än att "True" eller "{...}" smyger in
    som varumärke."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "ogiltigt värde (sant/falskt)"
    if isinstance(value, int):
        return str(value), None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None, "ogiltigt värde (inte ett ändligt tal)"
        return (str(int(value)) if value.is_integer() else repr(value)), None
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped or None), None
    return None, f"ogiltigt värde ({type(value).__name__})"


def _parse_price(value) -> tuple[float | None, str | None]:
    """"19,90" / "19,90 kr" / "1 234,50" / "19:90" / 19.9 -> tal. Tomt ->
    (None, None). Negativt eller otolkbart -> (None, orsak): anroparen
    utesluter raden, för ett pris vi inte förstår får aldrig bli 0 eller
    "ungefär rätt"."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "icke-numeriskt pris (sant/falskt)"
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None, "icke-numeriskt pris"
        return _reject_negative(number, str(value))
    if not isinstance(value, str):
        return None, f"icke-numeriskt pris ({type(value).__name__})"

    original = value.strip()
    if not original:
        return None, None
    text = _CURRENCY_SUFFIX_RE.sub("", original)
    # Mellanslag (även hårda) är tusentalsavgränsare i svensk skrivning.
    text = _ANY_WHITESPACE_RE.sub("", text)
    # "19:90" är butiksskyltarnas sätt att skriva 19,90.
    if re.fullmatch(r"\d+:\d{2}", text):
        text = text.replace(":", ".")
    if "," in text and "." in text:
        # Båda finns: det sista tecknet är decimaltecknet, det andra
        # tusentalsavgränsare ("1.234,50" resp. "1,234.50").
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    if not _PRICE_RE.match(text):
        return None, f"icke-numeriskt pris: {original!r}"
    return _reject_negative(float(text), original)


def _reject_negative(number: float, shown: str) -> tuple[float | None, str | None]:
    if number < 0:
        return None, f"negativt pris: {shown}"
    return number, None


def _gtin_checksum_ok(code: str) -> bool:
    """GS1 mod-10-kontrollsiffra, samma regel som providers/axfood.py och
    providers/citygross.py använder: vikterna växlar 3,1,3,1... räknat från
    siffran närmast kontrollsiffran. Kopierad hit i stället för importerad,
    eftersom ingenting utanför en providers egen fil ska bero på den."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body = digits[:-1][::-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(body))
    return (10 - total % 10) % 10 == digits[-1]


def _parse_gtin(value) -> tuple[str | None, str | None]:
    """Råvärde -> 14-siffrig GTIN eller None. Nollutfyllnad till 14 är samma
    normalisering som resten av systemet gör (City Gross EAN-13 och Axfoods
    GTIN-14 är samma produkt), annars misslyckas matchningen tyst."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "ogiltig GTIN (sant/falskt)"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
            return None, f"ogiltig GTIN (decimaltal): {value!r}"
        text = str(int(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None, None
        # Excel-exporter skriver gärna långa tal som "7.31086509353E+12" eller
        # "7310865093530.0"; att bara plocka siffror ur dem ger fel kod.
        if _SCIENTIFIC_RE.match(text) or _TRAILING_ZERO_DECIMALS_RE.match(text):
            text = str(int(float(text)))
    else:
        return None, f"ogiltig GTIN ({type(value).__name__})"

    digits = re.sub(r"\D", "", text)
    if not digits:
        return None, f"ogiltig GTIN: {value!r}"
    if len(digits) not in (8, 12, 13, 14):
        return None, f"GTIN {digits} har {len(digits)} siffror (8, 12, 13 eller 14 förväntas)"
    if not _gtin_checksum_ok(digits):
        return None, f"GTIN {digits} har ogiltig kontrollsiffra"
    return digits.zfill(14), None


def _parse_date(value, excel_serial: bool) -> tuple[float | None, str | None]:
    """Datum/tid -> epoksekunder (UTC). Tid utan tidszon tolkas som UTC och
    ett datum utan klockslag som 00:00 - om "giltig till 30/9" ska betyda
    dygnets slut är det mottagarens beslut, inte parserns gissning.

    excel_serial: i XLSX är ett numeriskt datum ett Excel-serienummer
    (dagar sedan 1899-12-30). I JSON tolkas ett tal som epoksekunder, men
    bara i ett spann där det inte kan förväxlas med ÅÅÅÅMMDD - 20260930 som
    epok vore augusti 1970, en tyst påhittad tid."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "ogiltigt datum (sant/falskt)"
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None, "ogiltigt datum"
        if excel_serial:
            if not 1 <= number <= _EXCEL_SERIAL_MAX:
                return None, f"ogiltigt Excel-datum: {value!r}"
            return float(round((number - _EXCEL_EPOCH_OFFSET_DAYS) * 86400)), None
        if 1_000_000_000 <= number < 100_000_000_000:
            return number, None
        return None, f"ogiltigt datum: {value!r} (ange ISO 8601, t.ex. 2026-09-30)"
    if not isinstance(value, str):
        return None, f"ogiltigt datum ({type(value).__name__})"

    text = value.strip()
    if not text:
        return None, None
    try:
        match = _SWEDISH_DATE_RE.match(text)
        if match:
            day, month, year, hour, minute, second = match.groups()
            moment = datetime(int(year), int(month), int(day),
                              int(hour or 0), int(minute or 0), int(second or 0), tzinfo=_UTC)
        else:
            # "Z" stöds av fromisoformat först i 3.11; skriv om explicit så att
            # beteendet inte beror på tolkversion.
            iso = text[:-1] + "+00:00" if text[-1] in "Zz" else text
            moment = datetime.fromisoformat(iso)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=_UTC)
    except ValueError:
        return None, f"ogiltigt datum: {text!r}"
    return moment.timestamp(), None


def _normalize_record(values: dict, line_number: int, excel_dates: bool) -> tuple[FeedRow | None, list[FeedError]]:
    """Ett mappat rådvärdes-dict (FeedRow-fält -> råvärde) -> (FeedRow eller
    None, felen/notiserna för raden). Regeln för vad som är dödligt:
    - ingen identitet alls -> utesluts (går inte att använda)
    - otolkbart/negativt pris -> utesluts (ett fel pris är värre än inget)
    - allt annat (GTIN, datum, textfält) -> fältet blir None + notis, raden
      behålls, för resten av raden är fortfarande sann."""
    errors: list[FeedError] = []

    def notice(reason: str) -> None:
        errors.append(FeedError(line_number, reason))

    name, err = _text(values.get("name"))
    if err:
        notice(f"namn: {err}")
    gtin, err = _parse_gtin(values.get("gtin"))
    if err:
        notice(f"gtin: {err} - fältet sätts till tomt")
    external_id, err = _text(values.get("external_product_id"))
    if err:
        notice(f"artikelnummer: {err}")

    if not name and not gtin and not external_id:
        notice("raden saknar identitet (varken namn, giltig GTIN eller artikelnummer) - raden utesluts")
        return None, errors

    fatal = False
    prices: dict[str, float | None] = {}
    for field, label in _PRICE_FIELDS:
        prices[field], err = _parse_price(values.get(field))
        if err:
            notice(f"{label}: {err} - raden utesluts")
            fatal = True

    valid_to, err = _parse_date(values.get("campaign_valid_to"), excel_dates)
    if err:
        notice(f"kampanj_till: {err} - fältet sätts till tomt")

    optional_text = {}
    for field, label in (("brand", "märke"), ("package", "storlek"), ("category", "kategori")):
        optional_text[field], err = _text(values.get(field))
        if err:
            notice(f"{label}: {err} - fältet sätts till tomt")

    if fatal:
        return None, errors
    return FeedRow(
        gtin=gtin,
        external_product_id=external_id,
        name=name or "",
        brand=optional_text["brand"],
        package=optional_text["package"],
        regular_price=prices["regular_price"],
        campaign_price=prices["campaign_price"],
        member_price=prices["member_price"],
        campaign_valid_to=valid_to,
        category=optional_text["category"],
        line_number=line_number,
    ), errors


# --------------------------------------------------------------------------
# Tabellformat (CSV och XLSX): första raden med innehåll är rubrikraden
# --------------------------------------------------------------------------

def _is_blank(cells) -> bool:
    return all(cell is None or (isinstance(cell, str) and not cell.strip()) for cell in cells)


def _parse_table(source_rows, fmt: str, excel_dates: bool) -> ParsedFeed:
    """source_rows: iterabel av (radnummer i källan, celler) där celler
    antingen är en lista eller ett Exception (källan kunde inte läsas
    vidare). Radnumret i källan används bara relativt rubrikraden, så
    tomma rader före rubriken inte förskjuter numreringen."""
    iterator = iter(source_rows)
    header_cells = None
    header_row = 0
    for row_number, cells in iterator:
        if isinstance(cells, Exception):
            return ParsedFeed([], [FeedError(0, f"Kunde inte läsa feeden: {cells}")], fmt, 0)
        if not _is_blank(cells):
            header_cells, header_row = cells, row_number
            break
    if header_cells is None:
        return ParsedFeed([], [FeedError(0, "Feeden är tom - ingen rubrikrad hittades")], fmt, 0)

    column_map, unknown = _map_header(header_cells)
    if not any(field in _IDENTITY_FIELDS for field in column_map.values()):
        known = ", ".join(sorted(_FIELD_BY_ALIAS))
        return ParsedFeed([], [FeedError(
            0,
            "Rubrikraden saknar identitetskolumn (namn, gtin eller artikelnummer). "
            f"Okända rubriker: {', '.join(unknown) or '(inga)'}. Kända rubriker: {known}",
        )], fmt, 0)

    rows: list[FeedRow] = []
    errors: list[FeedError] = []
    total = 0
    with_content = 0
    header_width = len(header_cells)
    while header_width and _is_blank(header_cells[header_width - 1:]):
        header_width -= 1

    for row_number, cells in iterator:
        line_number = row_number - header_row
        total += 1
        if isinstance(cells, Exception):
            errors.append(FeedError(line_number, f"Kunde inte läsa vidare i feeden: {cells}"))
            break
        if _is_blank(cells):
            continue
        with_content += 1
        if with_content > MAX_ROWS:
            errors.append(FeedError(
                line_number, f"Feeden har fler än {MAX_ROWS} rader - bearbetningen stoppades här"))
            break

        # Fler fält än rubriker i en CSV betyder nästan alltid ett oskyddat
        # avgränsartecken i ett fält ("Kaffe, malet") - då har alla kolumner
        # till höger förskjutits och priset står i fel kolumn. Avslutande
        # tomma fält (Excel skriver gärna "...;;;") räknas inte. I XLSX är
        # extra kolumner däremot bara okommenterade celler.
        width = len(cells)
        while width and _is_blank(cells[width - 1:]):
            width -= 1
        if fmt == "CSV" and width > header_width:
            errors.append(FeedError(
                line_number,
                f"raden har {width} fält men rubrikraden {header_width} - troligen ett "
                "oskyddat avgränsartecken i ett fält; raden utesluts"))
            continue

        values = {
            field: (cells[index] if index < len(cells) else None)
            for index, field in column_map.items()
        }
        row, row_errors = _normalize_record(values, line_number, excel_dates)
        errors.extend(row_errors)
        if row is not None:
            rows.append(row)
    return ParsedFeed(rows, errors, fmt, total)


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

def _decode_text(payload) -> str:
    """UTF-8 (med eller utan BOM) först, sedan cp1252 - Excel på svenska
    Windows sparar fortfarande CSV i cp1252 om man inte väljer "CSV UTF-8".
    latin-1 sist eftersom det aldrig misslyckas; det fångar de fem
    kodpunkter cp1252 saknar."""
    if isinstance(payload, str):
        return payload.lstrip(_BOM)
    data = bytes(payload)
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _detect_delimiter(text: str) -> str:
    """csv.Sniffer på de första kilobytena, men resultatet måste finnas i
    rubrikraden - Sniffer kan låta sig luras av svenska decimalkommatecken
    i datan ("19,90"). Faller tillbaka på det av ; , tab som förekommer
    mest i rubrikraden, och till sist ';' (svensk Excel-standard)."""
    sample = text[:8192]
    first_line = sample.split("\n", 1)[0].rstrip("\r")
    candidates = (";", ",", "\t")
    try:
        sniffed = csv.Sniffer().sniff(sample, delimiters="".join(candidates)).delimiter
    except csv.Error:
        sniffed = None
    if sniffed in candidates and sniffed in first_line:
        return sniffed
    counts = {delimiter: first_line.count(delimiter) for delimiter in candidates}
    best = max(candidates, key=counts.__getitem__)
    return best if counts[best] > 0 else ";"


def _csv_rows(text: str):
    """Genererar (radnummer, celler). Ett csv.Error (t.ex. ett fält över
    csv.field_size_limit) avslutar generatorn med ett Exception-värde i
    stället för att kasta - raderna före felet är fortfarande giltiga."""
    reader = csv.reader(io.StringIO(text), delimiter=_detect_delimiter(text))
    row_number = 0
    try:
        for record in reader:
            row_number += 1
            yield row_number, record
    except csv.Error as exc:
        yield row_number + 1, exc


# --------------------------------------------------------------------------
# JSON / API
# --------------------------------------------------------------------------

def _parse_json(payload, fmt: str) -> ParsedFeed:
    if isinstance(payload, (bytes, bytearray, str)):
        raw = payload.lstrip(_BOM) if isinstance(payload, str) else bytes(payload)
        try:
            # json.loads tar bytes direkt och känner själv igen BOM/UTF-16.
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            return ParsedFeed([], [FeedError(0, f"Ogiltig JSON: {exc}")], fmt, 0)
    elif isinstance(payload, (list, dict)):
        data = payload
    else:
        raise TypeError("JSON/API-feed måste vara bytes, str, list eller dict")

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = next((data[key] for key in _JSON_LIST_KEYS if isinstance(data.get(key), list)), None)
        if items is None:
            return ParsedFeed([], [FeedError(
                0, "JSON-objektet saknar en radlista under någon av nycklarna "
                   + ", ".join(repr(key) for key in _JSON_LIST_KEYS))], fmt, 0)
    else:
        return ParsedFeed([], [FeedError(
            0, "JSON-toppnivån måste vara en lista av objekt eller ett objekt med en radlista")], fmt, 0)
    return _parse_objects(items, fmt)


def _parse_objects(items: list, fmt: str) -> ParsedFeed:
    rows: list[FeedRow] = []
    errors: list[FeedError] = []
    total = 0
    for line_number, item in enumerate(items, start=1):
        total += 1
        if line_number > MAX_ROWS:
            errors.append(FeedError(
                line_number, f"Feeden har fler än {MAX_ROWS} rader - bearbetningen stoppades här"))
            break
        if not isinstance(item, dict):
            errors.append(FeedError(
                line_number, f"posten är inte ett objekt utan {type(item).__name__} - raden utesluts"))
            continue
        values: dict = {}
        for key, value in item.items():
            field = _FIELD_BY_ALIAS.get(_normalize_header(key))
            if field is not None and field not in values:
                values[field] = value
        row, row_errors = _normalize_record(values, line_number, excel_dates=False)
        errors.extend(row_errors)
        if row is not None:
            rows.append(row)
    return ParsedFeed(rows, errors, fmt, total)


# --------------------------------------------------------------------------
# XLSX - minimal läsare: zipfile + xml.etree, inga beroenden
# --------------------------------------------------------------------------

def _local(tag) -> str:
    """"{ns}row" -> "row". Matchar på lokalt namn så att blad utan default-
    namnrymd (vissa generatorer) läses lika bra som Excels egna."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _parse_xlsx(payload: bytes) -> ParsedFeed:
    fmt = "XLSX"
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            sheet_path = _xlsx_first_sheet_path(archive)
            for part in (sheet_path, "xl/sharedStrings.xml"):
                try:
                    size = archive.getinfo(part).file_size
                except KeyError:
                    continue
                if size > _MAX_XLSX_PART_BYTES:
                    return ParsedFeed([], [FeedError(
                        0, f"{part} är {size} byte uppackad - över taket på {_MAX_XLSX_PART_BYTES}")], fmt, 0)
            shared = _xlsx_shared_strings(archive)
            try:
                sheet_xml = archive.read(sheet_path)
            except KeyError:
                return ParsedFeed([], [FeedError(0, f"Filen saknar kalkylbladet {sheet_path}")], fmt, 0)
    except zipfile.BadZipFile:
        return ParsedFeed([], [FeedError(0, "Filen är inte en giltig xlsx (zip-arkivet går inte att läsa)")], fmt, 0)
    except ET.ParseError as exc:
        return ParsedFeed([], [FeedError(0, f"Filen är inte en giltig xlsx (trasig XML): {exc}")], fmt, 0)
    return _parse_table(_xlsx_rows(sheet_xml, shared), fmt, excel_dates=True)


def _xlsx_first_sheet_path(archive: zipfile.ZipFile) -> str:
    """Första bladet enligt workbook.xml + dess relations-fil. Excel döper
    inte om filerna när blad tas bort, så "första bladet" kan mycket väl
    ligga i sheet3.xml. Faller tillbaka på sheet1.xml om uppslaget inte
    går att göra."""
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        return _XLSX_DEFAULT_SHEET
    first = next((el for el in workbook.iter() if _local(el.tag) == "sheet"), None)
    if first is None:
        return _XLSX_DEFAULT_SHEET
    rel_id = first.get(_XLSX_REL_ID_ATTR)
    for rel in rels.iter():
        if _local(rel.tag) == "Relationship" and rel.get("Id") == rel_id and rel.get("Target"):
            target = rel.get("Target").lstrip("/")
            return target if target.startswith("xl/") else "xl/" + target
    return _XLSX_DEFAULT_SHEET


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """xl/sharedStrings.xml -> lista indexerad som cellernas <v>. Rik text
    (<r><t>..</t></r>) slås ihop till en sträng - formatteringen är
    ointressant, texten är allt."""
    try:
        data = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    strings: list[str] = []
    for item in ET.fromstring(data):
        if _local(item.tag) != "si":
            continue
        strings.append("".join(
            node.text or "" for node in item.iter()
            if _local(node.tag) == "t"))
    return strings


def _column_index(ref: str | None) -> int | None:
    """"A1" -> 0, "AB12" -> 27. None om referensen saknas (vissa generatorer
    skriver celler utan r-attribut; då räknas de i ordning)."""
    match = _CELL_REF_RE.match(ref or "")
    if not match:
        return None
    index = 0
    for char in match.group(1).upper():
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _cell_value(cell, shared: list[str]):
    """<c> -> Python-värde: str, float, bool eller None. t="s" delad sträng,
    "inlineStr" inline, "str" formelresultat, "b" bool, "e" fel (#N/A ->
    None), annars tal. Ett tal som inte går att tolka lämnas som text så
    att fältparsern får rapportera det med sitt eget felmeddelande."""
    kind = cell.get("t", "n")
    v_text = None
    inline = None
    for child in cell:
        name = _local(child.tag)
        if name == "v":
            v_text = child.text
        elif name == "is":
            inline = "".join(node.text or "" for node in child.iter() if _local(node.tag) == "t")
    if kind == "s":
        try:
            return shared[int(v_text)]
        except (TypeError, ValueError, IndexError):
            return None
    if kind == "inlineStr":
        return inline
    if kind == "str":
        return v_text
    if kind == "b":
        return None if v_text is None else v_text.strip() in ("1", "true")
    if kind == "e" or v_text is None:
        return None
    try:
        return float(v_text)
    except ValueError:
        return v_text


def _xlsx_rows(sheet_xml: bytes, shared: list[str]):
    """Genererar (Excel-radnummer, celler) från första bladet. iterparse i
    stället för fromstring så att ett 50 000-raders blad inte behöver ligga
    som ett helt elementträd i minnet; varje <row> rensas när den lästs.
    Radnumret kommer från r-attributet så att tomma rader Excel hoppar över
    i XML:en ändå räknas - line_number ska stämma med vad partnern ser."""
    last_row = 0
    try:
        for _event, element in ET.iterparse(io.BytesIO(sheet_xml), events=("end",)):
            if _local(element.tag) != "row":
                continue
            r_attr = element.get("r")
            row_number = int(r_attr) if r_attr and r_attr.isdigit() and int(r_attr) > last_row else last_row + 1
            last_row = row_number
            cells: list = []
            next_index = 0
            for cell in element:
                if _local(cell.tag) != "c":
                    continue
                index = _column_index(cell.get("r"))
                if index is None:
                    index = next_index
                next_index = index + 1
                while len(cells) <= index:
                    cells.append(None)
                cells[index] = _cell_value(cell, shared)
            element.clear()
            yield row_number, cells
    except ET.ParseError as exc:
        yield last_row + 1, exc
