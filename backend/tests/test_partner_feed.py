# -*- coding: utf-8 -*-
"""partner_feed - parsning av partnerbutikers prisfeeds (CSV/JSON/API/XLSX).

Allt körs i minnet utan nätverk. XLSX-filerna byggs i testet med zipfile
så att läsaren testas mot exakt den OOXML-struktur den påstår sig klara,
inte mot vad ett tredjepartsbibliotek råkar skriva."""

import io
import sys
import unittest
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grocery import partner_feed  # noqa: E402
from services.grocery.partner_feed import (  # noqa: E402
    FEED_FORMATS, FeedError, FeedRow, ParsedFeed, parse_feed,
)

# Riktiga koder med giltig GS1-kontrollsiffra, i olika längder.
EAN13 = "7310865093530"
EAN13_AS_GTIN14 = "07310865093530"
EAN8 = "96385074"
UPC12 = "036000291452"
EAN13_BAD_CHECK = "7310865093531"

UTC = timezone.utc


def _epoch(*args):
    return datetime(*args, tzinfo=UTC).timestamp()


def _reasons(parsed: ParsedFeed, line_number=None) -> list[str]:
    return [e.reason for e in parsed.errors if line_number is None or e.line_number == line_number]


# --------------------------------------------------------------------------
# XLSX-byggare: minsta giltiga OOXML-paket
# --------------------------------------------------------------------------

_XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _shared_cell(ref, index):
    return f'<c r="{ref}" t="s"><v>{index}</v></c>'


def _number_cell(ref, value):
    return f'<c r="{ref}"><v>{value}</v></c>'


def _inline_cell(ref, text):
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _build_xlsx(shared_strings, rows_xml, sheet_file="sheet1.xml"):
    """rows_xml: lista av färdiga <row>-element. sheet_file gör det möjligt
    att lägga första bladet i sheet2.xml, som Excel gör efter att ett blad
    tagits bort."""
    shared = "".join(f"<si><t>{s}</t></si>" for s in shared_strings)
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f'<Override PartName="/xl/worksheets/{sheet_file}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{_XLSX_NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Priser" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/{sheet_file}"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
            "</Relationships>"
        ),
        "xl/sharedStrings.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<sst xmlns="{_XLSX_NS}" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
            f"{shared}</sst>"
        ),
        f"xl/worksheets/{sheet_file}": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{_XLSX_NS}"><sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content.encode("utf-8"))
    return buffer.getvalue()


def _excel_serial(year, month, day):
    return (date(year, month, day) - date(1899, 12, 30)).days


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

class CsvFeeds(unittest.TestCase):
    def test_semicolon_with_swedish_decimals_and_kr(self):
        payload = (
            "GTIN;Namn;Märke;Storlek;Pris;Kampanjpris;Medlemspris;Kampanj till;Kategori\n"
            f"{EAN13};Mellanmjölk;Arla;1,5 l;19,90 kr;15,90 kr;;2026-09-30;Mejeri\n"
            "8712345678906;Kaffe;Gevalia;450 g;1 234,50;;59:90;;Kaffe\n"
        )
        parsed = parse_feed("CSV", payload)
        self.assertEqual(parsed.format, "CSV")
        self.assertEqual(parsed.total_lines, 2)
        self.assertEqual(parsed.errors, [])
        self.assertEqual(len(parsed.rows), 2)

        milk = parsed.rows[0]
        self.assertIsInstance(milk, FeedRow)
        self.assertEqual(milk.gtin, EAN13_AS_GTIN14)
        self.assertEqual(milk.name, "Mellanmjölk")
        self.assertEqual(milk.brand, "Arla")
        self.assertEqual(milk.package, "1,5 l")
        self.assertEqual(milk.regular_price, 19.90)
        self.assertEqual(milk.campaign_price, 15.90)
        self.assertIsNone(milk.member_price)
        self.assertEqual(milk.campaign_valid_to, _epoch(2026, 9, 30))
        self.assertEqual(milk.category, "Mejeri")
        self.assertEqual(milk.line_number, 1)

        coffee = parsed.rows[1]
        self.assertEqual(coffee.regular_price, 1234.50)   # mellanslag som tusentalsavgränsare
        self.assertEqual(coffee.member_price, 59.90)      # "59:90" - butiksskyltning
        self.assertIsNone(coffee.campaign_price)
        self.assertIsNone(coffee.campaign_valid_to)
        self.assertEqual(coffee.line_number, 2)

    def test_comma_with_english_headers(self):
        payload = (
            "ean,sku,name,brand,size,price,campaign_price,member_price,valid_to,category\n"
            f"{UPC12},A-1001,Peanut butter,Skippy,340 g,39.90,,34.90,2026-09-30T23:59:59Z,Pantry\n"
        )
        parsed = parse_feed("CSV", payload)
        self.assertEqual(parsed.errors, [])
        row = parsed.rows[0]
        self.assertEqual(row.gtin, "00" + UPC12)
        self.assertEqual(row.external_product_id, "A-1001")
        self.assertEqual(row.name, "Peanut butter")
        self.assertEqual(row.package, "340 g")
        self.assertEqual(row.regular_price, 39.90)
        self.assertEqual(row.member_price, 34.90)
        self.assertEqual(row.campaign_valid_to, _epoch(2026, 9, 30, 23, 59, 59))

    def test_cp1252_encoded_with_swedish_letters(self):
        payload = (
            "artnr;namn;pris\n"
            "1;Räksallad med gräslök å ä ö Å Ä Ö;29,90\n"
        ).encode("cp1252")
        parsed = parse_feed("CSV", payload)
        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.rows[0].name, "Räksallad med gräslök å ä ö Å Ä Ö")
        self.assertEqual(parsed.rows[0].external_product_id, "1")

    def test_utf8_with_bom_and_tab_delimiter(self):
        payload = "\ufeffgtin\tnamn\tpris\n" + f"{EAN13}\tMjölk\t12,5\n"
        parsed = parse_feed("CSV", payload.encode("utf-8"))
        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.rows[0].gtin, EAN13_AS_GTIN14)   # BOM får inte fastna i rubriken
        self.assertEqual(parsed.rows[0].regular_price, 12.5)

    def test_header_aliases_are_case_and_space_insensitive(self):
        payload = (
            "Streckkod;BENÄMNING;Varumärke;Förpackning;Ordinarie Pris (kr);Extrapris;Giltig till\n"
            f"{EAN8};Knäckebröd;Wasa;6-pack;24,90;19,90;30/9 2026\n"
        )
        parsed = parse_feed("CSV", payload)
        self.assertEqual(parsed.errors, [])
        row = parsed.rows[0]
        self.assertEqual(row.gtin, EAN8.zfill(14))
        self.assertEqual(row.name, "Knäckebröd")
        self.assertEqual(row.brand, "Wasa")
        self.assertEqual(row.package, "6-pack")
        self.assertEqual(row.regular_price, 24.90)
        self.assertEqual(row.campaign_price, 19.90)
        self.assertEqual(row.campaign_valid_to, _epoch(2026, 9, 30))

    def test_blank_lines_are_skipped_but_counted(self):
        payload = f"gtin;namn;pris\n{EAN13};Mjölk;19,90\n\n;;\n{EAN8};Bröd;24,90\n"
        parsed = parse_feed("CSV", payload)
        self.assertEqual(parsed.errors, [])
        self.assertEqual([r.line_number for r in parsed.rows], [1, 4])
        self.assertEqual(parsed.total_lines, 4)

    def test_unquoted_delimiter_in_field_is_reported_not_misread(self):
        # "Kaffe;malet" utan citattecken förskjuter kolumnerna - priset skulle
        # hamna i storlek-kolumnen och storleken bli pris. Hellre ett radfel.
        payload = f"gtin;namn;storlek;pris\n{EAN13};Kaffe;malet;450 g;59,90\n{EAN8};Te;20 p;29,90;;\n"
        parsed = parse_feed("CSV", payload)
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(parsed.rows[0].name, "Te")   # avslutande tomma fält är ofarliga
        self.assertIn("5 fält", _reasons(parsed, 1)[0])

    def test_header_without_identity_column_is_a_feed_level_error(self):
        parsed = parse_feed("CSV", "pris;kampanjpris\n19,90;15,90\n")
        self.assertEqual(parsed.rows, [])
        self.assertEqual(parsed.errors[0].line_number, 0)
        self.assertIn("identitetskolumn", parsed.errors[0].reason)

    def test_empty_feed(self):
        parsed = parse_feed("CSV", "")
        self.assertEqual(parsed.rows, [])
        self.assertEqual(parsed.errors[0].line_number, 0)
        self.assertEqual(parsed.total_lines, 0)


# --------------------------------------------------------------------------
# Fältregler (körs via CSV eftersom det är kortast att skriva)
# --------------------------------------------------------------------------

class FieldRules(unittest.TestCase):
    def _one(self, header, line):
        return parse_feed("CSV", f"{header}\n{line}\n")

    def test_invalid_gtin_check_digit_gives_none_but_keeps_row(self):
        parsed = self._one("gtin;namn;pris", f"{EAN13_BAD_CHECK};Mjölk;19,90")
        self.assertEqual(len(parsed.rows), 1)
        self.assertIsNone(parsed.rows[0].gtin)
        self.assertEqual(parsed.rows[0].name, "Mjölk")
        self.assertEqual(len(parsed.errors), 1)
        self.assertIn("kontrollsiffra", parsed.errors[0].reason)
        self.assertEqual(parsed.errors[0].line_number, 1)

    def test_gtin_lengths_normalize_to_14_digits(self):
        for code in (EAN8, UPC12, EAN13):
            parsed = self._one("gtin;namn", f"{code};X")
            self.assertEqual(parsed.rows[0].gtin, code.zfill(14), code)
        parsed = self._one("gtin;namn", f"{EAN13_AS_GTIN14};X")
        self.assertEqual(parsed.rows[0].gtin, EAN13_AS_GTIN14)

    def test_gtin_wrong_length_is_a_notice(self):
        parsed = self._one("gtin;namn", "12345;X")
        self.assertIsNone(parsed.rows[0].gtin)
        self.assertIn("5 siffror", parsed.errors[0].reason)

    def test_gtin_written_by_excel_as_scientific_or_float(self):
        parsed = self._one("gtin;namn", "7.31086509353E+12;X")
        self.assertEqual(parsed.rows[0].gtin, EAN13_AS_GTIN14)
        parsed = self._one("gtin;namn", f"{EAN13}.0;X")
        self.assertEqual(parsed.rows[0].gtin, EAN13_AS_GTIN14)

    def test_gtin_keeps_only_digits(self):
        parsed = self._one("gtin;namn", "731-0865-09353-0;X")
        self.assertEqual(parsed.rows[0].gtin, EAN13_AS_GTIN14)

    def test_negative_price_is_row_error_and_row_excluded(self):
        parsed = self._one("gtin;namn;pris", f"{EAN13};Mjölk;-19,90")
        self.assertEqual(parsed.rows, [])
        self.assertEqual(parsed.total_lines, 1)
        self.assertEqual(parsed.errors[0].line_number, 1)
        self.assertIn("negativt pris", parsed.errors[0].reason)

    def test_non_numeric_price_is_row_error_and_row_excluded(self):
        parsed = self._one("gtin;namn;pris;kampanjpris", f"{EAN13};Mjölk;19,90;två för 30")
        self.assertEqual(parsed.rows, [])
        self.assertIn("kampanjpris", parsed.errors[0].reason)
        self.assertIn("icke-numeriskt", parsed.errors[0].reason)

    def test_empty_price_is_none_not_zero(self):
        parsed = self._one("gtin;namn;pris", f"{EAN13};Mjölk;")
        self.assertEqual(parsed.errors, [])
        self.assertIsNone(parsed.rows[0].regular_price)

    def test_row_without_identity_is_excluded(self):
        parsed = self._one("gtin;artikelnummer;namn;pris", ";;;19,90")
        self.assertEqual(parsed.rows, [])
        self.assertIn("saknar identitet", parsed.errors[0].reason)
        # Ogiltig GTIN + inget annat = fortfarande ingen identitet.
        parsed = self._one("gtin;artikelnummer;namn;pris", f"{EAN13_BAD_CHECK};;;19,90")
        self.assertEqual(parsed.rows, [])
        self.assertTrue(any("saknar identitet" in r for r in _reasons(parsed)))

    def test_name_alone_or_article_number_alone_is_enough(self):
        parsed = self._one("gtin;artikelnummer;namn", ";;Bara ett namn")
        self.assertEqual(parsed.rows[0].name, "Bara ett namn")
        parsed = self._one("gtin;artikelnummer;namn", ";A1;")
        self.assertEqual(parsed.rows[0].external_product_id, "A1")
        self.assertEqual(parsed.rows[0].name, "")

    def test_date_variants(self):
        cases = {
            "2026-09-30": _epoch(2026, 9, 30),
            "2026-09-30T23:59:59Z": _epoch(2026, 9, 30, 23, 59, 59),
            "2026-09-30 23:59": _epoch(2026, 9, 30, 23, 59),
            "2026-09-30T23:59:59+02:00": _epoch(2026, 9, 30, 21, 59, 59),
            "30/9 2026": _epoch(2026, 9, 30),
            "30/09/2026": _epoch(2026, 9, 30),
            "30/9-2026 12:00": _epoch(2026, 9, 30, 12, 0),
        }
        for text, expected in cases.items():
            parsed = self._one("namn;kampanj_till", f"X;{text}")
            self.assertEqual(parsed.errors, [], text)
            self.assertEqual(parsed.rows[0].campaign_valid_to, expected, text)

    def test_invalid_date_is_none_with_notice_and_row_kept(self):
        for text in ("nästa vecka", "2026-13-45", "9/30/2026"):
            parsed = self._one("namn;kampanj_till", f"X;{text}")
            self.assertEqual(len(parsed.rows), 1, text)
            self.assertIsNone(parsed.rows[0].campaign_valid_to, text)
            self.assertEqual(len(parsed.errors), 1, text)
            self.assertIn("ogiltigt datum", parsed.errors[0].reason, text)


# --------------------------------------------------------------------------
# JSON / API
# --------------------------------------------------------------------------

class JsonFeeds(unittest.TestCase):
    def test_list_of_objects_with_numbers_and_strings(self):
        payload = [
            {"gtin": EAN13, "name": "Mjölk", "price": 19.9, "campaign_price": "15,90",
             "campaign_valid_to": "2026-09-30", "brand": "Arla", "size": "1,5 l"},
            {"GTIN": int(EAN8), "Namn": "Bröd", "Pris": "24.90", "Artikelnummer": 4711},
        ]
        parsed = parse_feed("JSON", payload)
        self.assertEqual(parsed.format, "JSON")
        self.assertEqual(parsed.errors, [])
        self.assertEqual(parsed.total_lines, 2)
        first, second = parsed.rows
        self.assertEqual(first.gtin, EAN13_AS_GTIN14)
        self.assertEqual(first.regular_price, 19.9)
        self.assertEqual(first.campaign_price, 15.9)
        self.assertEqual(first.campaign_valid_to, _epoch(2026, 9, 30))
        self.assertEqual(first.package, "1,5 l")
        self.assertEqual(second.gtin, EAN8.zfill(14))          # tal som GTIN
        self.assertEqual(second.regular_price, 24.9)
        self.assertEqual(second.external_product_id, "4711")   # tal som artikelnummer
        self.assertEqual(second.line_number, 2)

    def test_wrapped_lists(self):
        item = {"namn": "Mjölk", "pris": "19,90"}
        for key in ("rows", "items", "produkter"):
            parsed = parse_feed("JSON", {key: [item]})
            self.assertEqual(len(parsed.rows), 1, key)
            self.assertEqual(parsed.rows[0].regular_price, 19.9, key)

    def test_api_format_takes_already_decoded_body_and_bytes(self):
        parsed = parse_feed("API", {"items": [{"namn": "Mjölk", "pris": 19.9}]})
        self.assertEqual(parsed.format, "API")
        self.assertEqual(parsed.rows[0].regular_price, 19.9)
        parsed = parse_feed("API", b'\xef\xbb\xbf[{"namn": "Mj\xc3\xb6lk", "pris": "19,90"}]')
        self.assertEqual(parsed.rows[0].name, "Mjölk")

    def test_bad_rows_do_not_break_the_feed(self):
        payload = [
            {"namn": "Bra", "pris": 10},
            "inte ett objekt",
            {"namn": "Negativt", "pris": -1},
            {"pris": 5},
            {"namn": "Också bra", "pris": "12,50", "kampanj_till": "igår"},
        ]
        parsed = parse_feed("JSON", payload)
        self.assertEqual([r.name for r in parsed.rows], ["Bra", "Också bra"])
        self.assertEqual([e.line_number for e in parsed.errors], [2, 3, 4, 5])
        self.assertEqual(parsed.total_lines, 5)

    def test_invalid_json_is_feed_level_error(self):
        parsed = parse_feed("JSON", "{not json")
        self.assertEqual(parsed.rows, [])
        self.assertEqual(parsed.errors[0].line_number, 0)
        self.assertIn("Ogiltig JSON", parsed.errors[0].reason)
        parsed = parse_feed("JSON", {"foo": []})
        self.assertEqual(parsed.errors[0].line_number, 0)

    def test_json_number_in_date_column_is_epoch_only_in_a_safe_range(self):
        parsed = parse_feed("JSON", [{"namn": "X", "kampanj_till": 1790000000}])
        self.assertEqual(parsed.rows[0].campaign_valid_to, 1790000000.0)
        # 20260930 som epok vore 1970 - det får inte bli ett tyst påhittat datum.
        parsed = parse_feed("JSON", [{"namn": "X", "kampanj_till": 20260930}])
        self.assertIsNone(parsed.rows[0].campaign_valid_to)
        self.assertEqual(len(parsed.errors), 1)


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------

class XlsxFeeds(unittest.TestCase):
    def _rows(self):
        shared = ["GTIN", "Namn", "Pris", "Kampanj till", "Märke", "Artikelnummer",
                  "Mellanmjölk 1,5 l", "Bananer", "24,90 kr"]
        rows = [
            "<row r=\"1\">" + "".join(
                _shared_cell(f"{col}1", i) for i, col in enumerate("ABCDEF")) + "</row>",
            "<row r=\"2\">"
            + _number_cell("A2", EAN13)
            + _shared_cell("B2", 6)
            + _number_cell("C2", "19.9")
            + _number_cell("D2", _excel_serial(2026, 9, 30))
            + _inline_cell("E2", "Arla")
            + _number_cell("F2", "12345")
            + "</row>",
            # Rad 3 saknas helt i XML:en (tom rad i Excel) - rad 4 ska ändå få rätt nummer.
            "<row r=\"4\">"
            + _shared_cell("B4", 7)
            + _shared_cell("C4", 8)
            + _number_cell("F4", "777")
            + "</row>",
        ]
        return shared, rows

    def test_shared_inline_numeric_and_date_cells(self):
        shared, rows = self._rows()
        parsed = parse_feed("XLSX", _build_xlsx(shared, rows))
        self.assertEqual(parsed.format, "XLSX")
        self.assertEqual(parsed.errors, [])
        self.assertEqual(len(parsed.rows), 2)

        milk = parsed.rows[0]
        self.assertEqual(milk.gtin, EAN13_AS_GTIN14)          # numerisk cell -> GTIN
        self.assertEqual(milk.name, "Mellanmjölk 1,5 l")     # delad sträng
        self.assertEqual(milk.regular_price, 19.9)            # numerisk cell
        self.assertEqual(milk.campaign_valid_to, _epoch(2026, 9, 30))   # Excel-serienummer
        self.assertEqual(milk.brand, "Arla")                  # inline-sträng
        self.assertEqual(milk.external_product_id, "12345")   # tal -> text utan ".0"
        self.assertEqual(milk.line_number, 1)

        bananas = parsed.rows[1]
        self.assertIsNone(bananas.gtin)
        self.assertEqual(bananas.name, "Bananer")
        self.assertEqual(bananas.regular_price, 24.9)         # strängcell med "kr"
        self.assertEqual(bananas.external_product_id, "777")
        self.assertEqual(bananas.line_number, 3)              # Excel-rad 4 = datarad 3

    def test_first_sheet_is_resolved_via_workbook_rels(self):
        shared, rows = self._rows()
        parsed = parse_feed("XLSX", _build_xlsx(shared, rows, sheet_file="sheet2.xml"))
        self.assertEqual(parsed.errors, [])
        self.assertEqual(len(parsed.rows), 2)

    def test_excel_datetime_serial_keeps_time_of_day(self):
        shared = ["namn", "kampanj_till"]
        serial = _excel_serial(2026, 9, 30) + 0.5   # 12:00
        rows = ["<row r=\"1\">" + _shared_cell("A1", 0) + _shared_cell("B1", 1) + "</row>",
                "<row r=\"2\">" + _inline_cell("A2", "X") + _number_cell("B2", serial) + "</row>"]
        parsed = parse_feed("XLSX", _build_xlsx(shared, rows))
        self.assertEqual(parsed.rows[0].campaign_valid_to, _epoch(2026, 9, 30, 12, 0))

    def test_not_a_zip_is_feed_level_error(self):
        parsed = parse_feed("XLSX", b"detta \xc3\xa4r inte en xlsx")
        self.assertEqual(parsed.rows, [])
        self.assertEqual(parsed.errors[0].line_number, 0)
        self.assertIn("xlsx", parsed.errors[0].reason)

    def test_str_payload_is_a_caller_error(self):
        with self.assertRaises(TypeError):
            parse_feed("XLSX", "inte bytes")


# --------------------------------------------------------------------------
# Radtak och API-ytan
# --------------------------------------------------------------------------

class RowCapAndApi(unittest.TestCase):
    def test_feed_formats(self):
        self.assertEqual(FEED_FORMATS, ("CSV", "JSON", "XLSX", "API"))
        with self.assertRaises(ValueError):
            parse_feed("XML", "<x/>")

    def test_format_is_case_insensitive(self):
        parsed = parse_feed("csv", f"gtin;namn\n{EAN13};X\n")
        self.assertEqual(parsed.format, "CSV")

    def test_row_cap_csv(self):
        payload = "namn;pris\n" + "".join(f"Vara {i};{i},00\n" for i in range(1, 6))
        with patch.object(partner_feed, "MAX_ROWS", 3):
            parsed = parse_feed("CSV", payload)
        self.assertEqual([r.name for r in parsed.rows], ["Vara 1", "Vara 2", "Vara 3"])
        self.assertEqual(len(parsed.errors), 1)
        self.assertEqual(parsed.errors[0].line_number, 4)
        self.assertIn("fler än 3 rader", parsed.errors[0].reason)
        self.assertEqual(parsed.total_lines, 4)   # stoppade vid raden som bröt taket

    def test_row_cap_json(self):
        payload = [{"namn": f"Vara {i}"} for i in range(1, 6)]
        with patch.object(partner_feed, "MAX_ROWS", 2):
            parsed = parse_feed("JSON", payload)
        self.assertEqual(len(parsed.rows), 2)
        self.assertEqual(parsed.errors[0].line_number, 3)

    def test_feed_error_and_rows_are_plain_dataclasses(self):
        parsed = parse_feed("CSV", "namn;pris\nX;abc\n")
        self.assertIsInstance(parsed.errors[0], FeedError)
        self.assertEqual(parsed.errors[0].line_number, 1)


if __name__ == "__main__":
    unittest.main()
