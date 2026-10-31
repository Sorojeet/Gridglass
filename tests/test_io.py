from __future__ import annotations

import json
import re

import polars as pl
import pytest

from gridglass.engine import ExportError, IngestError
from gridglass.engine.io import _clean_headers, detect_format, export, ingest


def _ingest(tmp_path, name: str, content: bytes, **kw):
    src = tmp_path / name
    src.write_bytes(content)
    res = ingest(src, name, tmp_path / "cache.parquet", **kw)
    return res, pl.read_parquet(tmp_path / "cache.parquet")


# --------------------------------------------------------------------------- import

def test_csv_comma(tmp_path):
    res, df = _ingest(tmp_path, "a.csv", b"Name,Amount,Date\nAsha,100,2026-01-05\nRavi,250.5,2026-01-06\n")
    assert res.rows == 2 and res.format == "csv"
    assert df.schema["Amount"] == pl.Float64 and df.schema["Date"] == pl.Date


def test_csv_semicolon_is_sniffed(tmp_path):
    _, df = _ingest(tmp_path, "a.csv", b"Name;City\nAsha;Pune\nRavi;Delhi\n")
    assert df.columns == ["Name", "City"]


def test_tsv(tmp_path):
    _, df = _ingest(tmp_path, "a.tsv", b"A\tB\n1\t2\n")
    assert df.columns == ["A", "B"]


def test_cp1252_csv_keeps_accents(tmp_path):
    _, df = _ingest(tmp_path, "a.csv", "Name\nJosé\nRenée\n".encode("cp1252"))
    assert df["Name"].to_list() == ["José", "Renée"]


def test_utf8_bom_csv(tmp_path):
    _, df = _ingest(tmp_path, "a.csv", "﻿Name,Age\nAsha,30\n".encode("utf-8"))
    assert df.columns == ["Name", "Age"]


def test_duplicate_and_blank_headers(tmp_path):
    _, df = _ingest(tmp_path, "a.csv", b"Name,Name,,City\n1,2,3,4\n")
    assert df.columns == ["Name", "Name (2)", "Column 3", "City"]


def test_clean_headers_unit():
    assert list(_clean_headers(["A", "A_duplicated_0", " ", "__UNNAMED__3"]).values()) == ["A", "A (2)", "Column 3", "Column 4"]


def test_xlsx_with_sheets(tmp_path):
    src = tmp_path / "book.xlsx"
    with __import__("xlsxwriter").Workbook(src) as wb:
        for sheet, rows in {"Jan": [["A", "B"], [1, "x"]], "Feb": [["A", "B"], [2, "y"], [3, "z"]]}.items():
            ws = wb.add_worksheet(sheet)
            for r, row in enumerate(rows):
                ws.write_row(r, 0, row)
    res = ingest(src, "book.xlsx", tmp_path / "c.parquet")
    assert res.sheets == ["Jan", "Feb"] and res.sheet == "Jan" and res.rows == 1
    res = ingest(src, "book.xlsx", tmp_path / "c.parquet", sheet="Feb")
    assert res.rows == 2
    with pytest.raises(IngestError, match="no sheet"):
        ingest(src, "book.xlsx", tmp_path / "c.parquet", sheet="Mar")


def test_json_and_ndjson(tmp_path):
    res, df = _ingest(tmp_path, "a.json", json.dumps([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]).encode())
    assert res.format == "json" and df.height == 2
    res, df = _ingest(tmp_path, "b.json", b'{"a": 1}\n{"a": 2}\n{"a": 3}\n')
    assert res.format == "ndjson" and df.height == 3


@pytest.mark.parametrize("name, content, fragment", [
    ("a.pdf", b"%PDF-1.7", "can't open .pdf"),
    ("a.csv", b"", "empty"),
    ("a.xlsx", b"Name,City\n", "real .xlsx"),
    ("a.csv", b"PK\x03\x04rest", "binary"),
    ("a.json", b"hello", "valid JSON"),
])
def test_rejects_bad_files(tmp_path, name, content, fragment):
    (tmp_path / name).write_bytes(content)
    with pytest.raises(IngestError, match=fragment):
        ingest(tmp_path / name, name, tmp_path / "c.parquet")


def test_size_limit(tmp_path):
    (tmp_path / "a.csv").write_bytes(b"A\n" + b"1\n" * 1000)
    with pytest.raises(IngestError, match="MB limit"):
        ingest(tmp_path / "a.csv", "a.csv", tmp_path / "c.parquet", max_bytes=100)


def test_renamed_xlsx_as_xls_is_detected(tmp_path):
    p = tmp_path / "a.xls"
    p.write_bytes(b"PK\x03\x04" + b"0" * 10)
    assert detect_format("a.xls", p) == "xlsx"


# --------------------------------------------------------------------------- export

@pytest.fixture
def result(orders):
    return orders


def test_export_csv_has_bom(tmp_path, result):
    out = export(result, "csv", tmp_path / "o.csv")
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"Order ID" in raw


def test_export_xlsx_roundtrip(tmp_path, result):
    out = export(result, "xlsx", tmp_path / "o.xlsx")
    back = pl.read_excel(out, engine="calamine")
    assert back.height == 6 and back.columns[0] == "Order ID"


def test_export_json(tmp_path, result):
    out = export(result, "json", tmp_path / "o.json")
    records = json.loads(out.read_text())
    assert records[0]["City"] == "Pune" and len(records) == 6


def test_export_pdf(tmp_path, result):
    out = export(result, "pdf", tmp_path / "o.pdf", title="Orders")
    assert out.read_bytes().startswith(b"%PDF") and out.stat().st_size > 1000


def test_export_pdf_wide_and_long(tmp_path):
    wide = pl.LazyFrame({f"Col {i}": list(range(300)) for i in range(12)})
    out = export(wide, "pdf", tmp_path / "w.pdf")
    assert out.read_bytes().count(b"/Type /Page") >= 2 or out.stat().st_size > 5000


def test_export_pdf_row_limit(tmp_path):
    with pytest.raises(ExportError, match="limited to 5"):
        export(pl.LazyFrame({"a": range(10)}), "pdf", tmp_path / "x.pdf", max_pdf_rows=5)


def test_parquet_export_is_not_offered(tmp_path, result):
    with pytest.raises(ExportError, match="CSV, XLSX, JSON or PDF"):
        export(result, "parquet", tmp_path / "o.parquet")


def test_export_pdf_prints_rupee_and_hindi(tmp_path):
    from gridglass.engine.pdf import CAN_SHAPE, REGULAR

    df = pl.LazyFrame({"ग्राहक": ["राम कुमार", "क्षत्रिय प्रकाश", "José"], "Amount ₹": [1250.5, 99.0, 15.0]})
    out = export(df, "pdf", tmp_path / "hi.pdf", title="बिक्री — Sales")
    raw = out.read_bytes()
    assert REGULAR == "GridglassSans" and CAN_SHAPE
    assert b"+NotoSans-Regular" in raw and b"+NotoSans-Bold" in raw  # bundled font embedded (subset)


# --------------------------------------------------------------------------- split into pages (report filter pages)

def test_split_to_excel_sheets(tmp_path, result):
    import fastexcel

    out = export(result, "xlsx", tmp_path / "s.xlsx", split_by="City")
    book = fastexcel.read_excel(str(out))
    assert book.sheet_names == ["Delhi", "Mumbai", "Pune"]  # A→Z, one sheet per value
    pune = pl.read_excel(out, sheet_name="Pune", engine="calamine")
    assert pune.height == 3 and set(pune["City"]) == {"Pune"}


def test_split_to_pdf_pages(tmp_path, result):
    out = export(result, "pdf", tmp_path / "s.pdf", split_by="City", title="Orders")
    pages = re.findall(rb"/Type\s*/Page[^s]", out.read_bytes())
    assert len(pages) == 3  # Delhi, Mumbai, Pune: one page each


def test_split_blank_values_get_a_sheet(tmp_path, result):
    import fastexcel

    out = export(result, "xlsx", tmp_path / "b.xlsx", split_by="Customer")
    assert "(blank)" in fastexcel.read_excel(str(out)).sheet_names


def test_split_limits(tmp_path, result):
    with pytest.raises(ExportError, match="XLSX and PDF"):
        export(result, "csv", tmp_path / "x.csv", split_by="City")
    with pytest.raises(ExportError, match="too many pages"):
        export(result, "xlsx", tmp_path / "x.xlsx", split_by="Order ID", max_pages=2)
    with pytest.raises(ExportError, match="not found"):
        export(result, "pdf", tmp_path / "x.pdf", split_by="Nope")


def test_sheet_names_are_safe():
    from gridglass.engine.io import sheet_names

    names = sheet_names(["Pune", "pune", "a/b:c*?[x]", "x" * 40, "x" * 40, ""])
    assert names == ["Pune", "pune (2)", "a_b_c___x_", "x" * 31, "x" * 27 + " (2)", "Sheet"]


# --------------------------------------------------------------------------- column types (whole-column detection)

def test_column_that_changes_type_late_stays_text(tmp_path):
    rows = "".join(f"{i},{1565432273931034624 + i}\n" for i in range(12000))
    _, df = _ingest(tmp_path, "a.csv", ("id,csc_txn\n" + rows + "12000,EW1565432273931034624\n").encode())
    assert df.schema["id"] == pl.Int64 and df.schema["csc_txn"] == pl.String
    assert df["csc_txn"][-1] == "EW1565432273931034624" and df["csc_txn"][0] == "1565432273931034624"


@pytest.mark.parametrize("value, kind", [
    ("1234567890", pl.Int64),          # 10 digits: still a number
    ("12345678901", pl.String),        # 11 digits: text, so no digit is ever lost
    ("-12345678901", pl.String),
    ("12345678901.5", pl.String),      # long whole part, too
    ("1234567.891234", pl.Float64),    # a normal decimal stays a number
    ("011001", pl.String),             # leading zero kept
    ("0", pl.Int64),
    ("0.5", pl.Float64),
])
def test_long_numbers_and_leading_zeros(tmp_path, value, kind):
    _, df = _ingest(tmp_path, "a.csv", f"v\n{value}\n5\n".encode())
    assert df.schema["v"] == kind
    if kind == pl.String:
        assert df["v"][0] == value


def test_types_from_every_row_not_a_sample(tmp_path):
    rows = "".join(f"{i}\n" for i in range(5000)) + "2.5\n"
    _, df = _ingest(tmp_path, "a.csv", ("n\n" + rows).encode())
    assert df.schema["n"] == pl.Float64 and df["n"][-1] == 2.5


def test_dates_datetimes_booleans_and_blanks(tmp_path):
    csv = (b"d,t,b,e,mix\n2026-01-05,2026-01-05 10:30:00,true,,1\n"
           b"2026-02-01,2026-02-01T08:00:00,FALSE,,2026-01-01\n,,,,\n")
    _, df = _ingest(tmp_path, "a.csv", csv)
    assert df.schema["d"] == pl.Date and df.schema["t"] == pl.Datetime("us") and df.schema["b"] == pl.Boolean
    assert df.schema["e"] == pl.String and df.schema["mix"] == pl.String
    assert df["d"][2] is None and df["b"].to_list() == [True, False, None]


def test_xlsx_mixed_column_keeps_every_value(tmp_path):
    import xlsxwriter

    src = tmp_path / "m.xlsx"
    with xlsxwriter.Workbook(src) as wb:
        ws = wb.add_worksheet()
        ws.write_row(0, 0, ["id", "txn"])
        for i in range(1, 1500):
            ws.write_row(i, 0, [i, 15654322 + i])
        ws.write_row(1500, 0, [1500, "EW1565432273931034624"])
    ingest(src, "m.xlsx", tmp_path / "c.parquet")
    df = pl.read_parquet(tmp_path / "c.parquet")
    assert df["txn"][-1] == "EW1565432273931034624"  # used to come back blank
    assert df.schema["id"] == pl.Int64


def test_json_mixed_column(tmp_path):
    data = [{"id": i, "txn": 1565432273931034624 + i} for i in range(200)] + [{"id": 200, "txn": "EW15", "tags": ["a"]}]
    res, df = _ingest(tmp_path, "a.json", json.dumps(data).encode())
    assert res.rows == 201 and df.schema["txn"] == pl.String and df["txn"][-1] == "EW15"
    assert df["tags"][-1] == '["a"]'


def test_long_ids_survive_xlsx_export(tmp_path):
    _, df = _ingest(tmp_path, "a.csv", b"card,amount\n1565432273931034624,10\n0000123456789012,20\n")
    out = export(pl.scan_parquet(tmp_path / "cache.parquet"), "xlsx", tmp_path / "o.xlsx")
    back = pl.read_excel(out, engine="calamine")  # reads cell types as written
    assert back.schema["card"] == pl.String and back["card"].to_list() == ["1565432273931034624", "0000123456789012"]
    assert back.schema["amount"] == pl.Int64 and back["amount"].to_list() == [10, 20]  # numbers stay numbers


# --------------------------------------------------------------------------- numbers are written plainly

def test_xlsx_numbers_have_no_accounting_format(tmp_path):
    import zipfile

    lf = pl.LazyFrame({"qty": [1250, -40], "amount": [125000.5, -500.25]})
    out = export(lf, "xlsx", tmp_path / "n.xlsx")
    styles = zipfile.ZipFile(out).read("xl/styles.xml").decode()
    assert "#,##0" not in styles and "[Red]" not in styles  # no thousands commas, fixed decimals or red negatives
    back = pl.read_excel(out, engine="calamine")
    assert back["qty"].to_list() == [1250, -40] and back["amount"].to_list() == [125000.5, -500.25]


def test_split_sheets_also_plain(tmp_path):
    import zipfile

    lf = pl.LazyFrame({"city": ["Pune", "Delhi"], "amount": [125000.5, 9.0]})
    out = export(lf, "xlsx", tmp_path / "s.xlsx", split_by="city")
    assert "#,##0" not in zipfile.ZipFile(out).read("xl/styles.xml").decode()


@pytest.mark.parametrize("value, text", [
    (1250, "1250"), (-40, "-40"), (125000.5, "125000.5"), (-500.25, "-500.25"),
    (1250.0, "1250"), (0.125, "0.125"), (1e-7, "0.0000001"), (12345678901234.5, "12345678901234.5"),
    (float("nan"), ""), (None, ""),
])
def test_pdf_numbers_are_plain(value, text):
    from gridglass.engine.pdf import _fmt

    assert _fmt(value) == text


# --- PDF: long text wraps inside its own column -------------------------------------------

def _pdf_table(df):
    from gridglass.engine.pdf import _table
    from reportlab.lib.pagesizes import A4, landscape
    usable = landscape(A4)[0] - 2 * 36
    return _table(df, usable), usable


def test_pdf_columns_fit_the_page():
    df = pl.DataFrame({f"Column {i}": ["word " * 30] for i in range(12)})
    table, usable = _pdf_table(df)
    assert sum(table._colWidths) <= usable + 0.5


def test_pdf_long_text_wraps_and_short_text_stays_plain():
    from reportlab.platypus import Paragraph
    df = pl.DataFrame({
        "ID": [1, 2],
        "Address": ["Flat 12, Sunshine Apartments, Near City Mall, Baner Road, Pune, Maharashtra " * 3, "x"],
        "Email": ["asha.rao.verylongname@example-company-domain.com", "m@x.in"],
    })
    table, _ = _pdf_table(df)
    cells = table._cellvalues
    assert isinstance(cells[1][1], Paragraph)          # long address wraps
    assert isinstance(cells[2][1], str)                # short text stays plain
    assert isinstance(cells[1][2], (Paragraph, str))


def test_pdf_headers_are_not_split_mid_word():
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from gridglass.engine.pdf import BOLD
    df = pl.DataFrame({"ID": [1], "Amount": [125000.5], "Note": ["text " * 80]})
    table, _ = _pdf_table(df)
    size = table._cellvalues[0][1].style.fontSize
    assert table._colWidths[1] >= stringWidth("Amount", BOLD, size)
    assert table._colWidths[0] >= stringWidth("ID", BOLD, size)


def test_pdf_keeps_more_of_long_text(tmp_path):
    from gridglass.engine.pdf import _fmt
    assert _fmt("a" * 300) == "a" * 300


# --- header row: titles and notes above the table -------------------------------------------

def _titled_book(path, *, start_col=1):
    import xlsxwriter

    with xlsxwriter.Workbook(path) as wb:
        ws = wb.add_worksheet("Report")
        ws.write(1, start_col, "Monthly Sales Report")
        ws.write(2, start_col, "Generated: 01-10-2026")
        ws.write_row(4, start_col, ["Region", "Customer", "Amount", "Phone"])
        ws.write_row(5, start_col, ["North", "Asha", 100, "9876543210"])
        ws.write_row(6, start_col, ["South", "Ravi", 250.5, "0123456789"])
        ws.write_row(8, start_col, ["East", "Meera", 80, "9000000001"])  # a blank row inside the data


def test_spreadsheet_headers_below_a_title_are_found(tmp_path):
    _titled_book(tmp_path / "r.xlsx")
    res, df = _ingest(tmp_path, "r.xlsx", (tmp_path / "r.xlsx").read_bytes())
    assert df.columns == ["Region", "Customer", "Amount", "Phone"]
    assert res.header_row == 3 and res.rows == 3  # title, note and a blank row skipped; blank data row dropped
    assert df["Amount"].to_list() == [100, 250.5, 80] and df["Phone"][1] == "0123456789"


def test_csv_headers_below_a_title_are_found(tmp_path):
    content = b"Monthly Sales Report\nGenerated: 01-10-2026\n\nRegion;Customer;Amount\nNorth;Asha;100\nSouth;Ravi;250.5\n"
    res, df = _ingest(tmp_path, "r.csv", content)
    assert res.header_row == 3 and df.columns == ["Region", "Customer", "Amount"]
    assert df["Amount"].to_list() == [100, 250.5]


def test_normal_files_keep_their_first_row_as_headers(tmp_path):
    res, df = _ingest(tmp_path, "a.csv", b"Name,City\nAsha,Pune\n")
    assert res.header_row == 0 and df.columns == ["Name", "City"]
    res, df = _ingest(tmp_path, "n.csv", b"1,2,3\n4,5,6\n")  # numbers only: nothing to skip to
    assert res.header_row == 0 and df.columns == ["1", "2", "3"]


@pytest.mark.parametrize("rows, expected", [
    ([["Name", "City", "Amount"], ["Asha", "Pune", "1"]], 0),
    ([["Report"], [], ["Name", "City", "Amount"], ["a", "b", "1"]], 2),
    ([["Total", "1,234"], ["Name", "City", "Amount"], ["a", "b", "1"]], 1),
    ([["2024", "2025", "2026"], ["Name", "City", "Amount"]], 1),  # a row of years isn't a header
    ([], 0),
])
def test_find_header_row(rows, expected):
    from gridglass.engine.io import find_header_row

    assert find_header_row(rows) == expected


def test_header_row_can_be_chosen_or_turned_off(tmp_path):
    content = b"Name,City\nAsha,Pune\nRavi,Delhi\n"
    res, df = _ingest(tmp_path, "a.csv", content, header=1)
    assert df.columns == ["Asha", "Pune"] and res.rows == 1
    res, df = _ingest(tmp_path, "a.csv", content, header=None)
    assert res.header_row is None and df.columns == ["Column 1", "Column 2"] and res.rows == 3
    _titled_book(tmp_path / "r.xlsx")
    res, df = _ingest(tmp_path, "r.xlsx", (tmp_path / "r.xlsx").read_bytes(), header=None)
    assert df.columns == ["Column 1", "Column 2", "Column 3", "Column 4"] and df["Column 1"][0] == "Monthly Sales Report"
    with pytest.raises(IngestError, match="fewer than"):
        _ingest(tmp_path, "a.csv", content, header=40)


def test_top_rows_show_the_file_as_it_is(tmp_path):
    from gridglass.engine.io import top_rows

    _titled_book(tmp_path / "r.xlsx")
    rows = top_rows(tmp_path / "r.xlsx", "r.xlsx", n=5)
    assert rows[0][0] == "Monthly Sales Report" and rows[2] == [None] * 4 and rows[3][0] == "Region"
    (tmp_path / "q.csv").write_bytes(b'"Title, with comma"\n"multi\nline"\nA,B\n1,2\n')
    assert top_rows(tmp_path / "q.csv", "q.csv") == [["Title, with comma"], ["multi\nline"], ["A", "B"], ["1", "2"]]
    res, df = _ingest(tmp_path, "q.csv", (tmp_path / "q.csv").read_bytes(), header=2)
    assert df.columns == ["A", "B"]
