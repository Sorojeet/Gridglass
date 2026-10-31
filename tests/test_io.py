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
