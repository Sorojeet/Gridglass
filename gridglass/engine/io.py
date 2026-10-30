"""File import (CSV, TSV, XLSX, XLS, JSON, NDJSON -> Parquet cache) and export (CSV, XLSX, JSON, PDF)."""
from __future__ import annotations

import codecs
import csv
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from .errors import ExportError, IngestError

INPUT_FORMATS = {"csv", "tsv", "xlsx", "xls", "json", "ndjson"}
EXPORT_FORMATS = {"csv", "xlsx", "json", "pdf"}
EXCEL_MAX_ROWS = 1_048_575  # plus one header row
_EXT_ALIASES = {"txt": "csv", "jsonl": "ndjson", "xlsm": "xlsx"}
_SAMPLE = 64 * 1024
_DUPLICATED = re.compile(r"^(.*)_duplicated_\d+$")


@dataclass
class IngestResult:
    rows: int
    columns: list[str]
    format: str
    sheets: list[str] = field(default_factory=list)  # Excel only
    sheet: str | None = None


# --------------------------------------------------------------------------- detect

def detect_format(filename: str, path: str | Path) -> str:
    """Pick the format from the extension, then check the file's first bytes agree."""
    ext = Path(filename).suffix.lower().lstrip(".")
    fmt = _EXT_ALIASES.get(ext, ext)
    if fmt not in INPUT_FORMATS:
        raise IngestError(f"Gridglass can't open .{ext or '?'} files. Try CSV, Excel or JSON.")
    with open(path, "rb") as fh:
        head = fh.read(_SAMPLE)
    if not head.strip():
        raise IngestError("This file is empty.")
    zip_magic, ole_magic = head.startswith(b"PK\x03\x04"), head.startswith(b"\xd0\xcf\x11\xe0")
    if fmt == "xlsx" and not zip_magic:
        raise IngestError("This doesn't look like a real Excel (.xlsx) file.")
    if fmt == "xls" and not ole_magic:
        if zip_magic:
            return "xlsx"  # renamed .xlsx, common in the wild
        raise IngestError("This doesn't look like a real Excel (.xls) file.")
    if fmt in ("csv", "tsv", "json", "ndjson") and (zip_magic or ole_magic or b"\x00" in head):
        raise IngestError("This file looks like a binary file, not text. Is it an Excel file with the wrong name?")
    if fmt == "json":
        first = head.lstrip(codecs.BOM_UTF8).lstrip()[:1]
        if first not in (b"[", b"{"):
            raise IngestError("This isn't valid JSON — it should start with [ or {.")
        if first == b"{" and b"\n{" in head:
            return "ndjson"
    return fmt


def excel_sheets(path: str | Path) -> list[str]:
    import fastexcel

    try:
        return list(fastexcel.read_excel(str(path)).sheet_names)
    except Exception as exc:  # fastexcel raises its own error types
        raise IngestError("Couldn't open this Excel file. It may be damaged or password-protected.") from exc


# --------------------------------------------------------------------------- ingest

def ingest(src: str | Path, filename: str, dest: str | Path, *, sheet: str | None = None,
           max_bytes: int | None = None) -> IngestResult:
    """Read an upload once and store it as Parquet at `dest`; every later step scans that file."""
    src, dest = Path(src), Path(dest)
    if max_bytes is not None and src.stat().st_size > max_bytes:
        raise IngestError(f"This file is larger than the {max_bytes // (1024 * 1024)} MB limit.")
    fmt = detect_format(filename, src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheets: list[str] = []
    try:
        if fmt in ("csv", "tsv"):
            text = _ensure_utf8(src)
            try:
                lf = _scan_text(text, fmt)
                lf.rename(_clean_headers(lf.collect_schema().names())).sink_parquet(dest)
            finally:
                if text != src:
                    text.unlink(missing_ok=True)
        elif fmt in ("xlsx", "xls"):
            sheets = excel_sheets(src)
            if sheet is not None and sheet not in sheets:
                raise IngestError(f"There's no sheet called '{sheet}'.")
            sheet = sheet or sheets[0]
            df = pl.read_excel(src, sheet_name=sheet, engine="calamine")
            _write(df, dest)
        elif fmt == "json":
            _write(pl.read_json(src), dest)
        else:
            _write(pl.read_ndjson(src), dest)
    except IngestError:
        raise
    except (pl.exceptions.PolarsError, ValueError, OSError) as exc:
        raise IngestError(f"Couldn't read this {fmt.upper()} file: {str(exc).splitlines()[0][:160]}") from exc

    meta = pl.scan_parquet(dest)
    columns = meta.collect_schema().names()
    if not columns:
        raise IngestError("This file has no columns.")
    rows = meta.select(pl.len()).collect().item()
    return IngestResult(rows=rows, columns=columns, format=fmt, sheets=sheets,
                        sheet=sheet if fmt in ("xlsx", "xls") else None)


def _write(df: pl.DataFrame, dest: Path) -> None:
    df.rename(_clean_headers(df.columns)).write_parquet(dest)


def _scan_text(src: Path, fmt: str) -> pl.LazyFrame:
    with open(src, "rb") as fh:
        sample = fh.read(_SAMPLE).decode("utf-8", errors="ignore")
    sep = "\t" if fmt == "tsv" else _sniff_separator(sample)
    return pl.scan_csv(
        src,
        separator=sep,
        infer_schema_length=10_000,
        try_parse_dates=True,
        truncate_ragged_lines=True,
        encoding="utf8-lossy",
    )


def _sniff_separator(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _ensure_utf8(src: Path) -> Path:
    """Excel on Windows often saves CSV as cp1252. Re-encode those to UTF-8 so accents survive."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        with open(src, "rb") as fh:
            while chunk := fh.read(1024 * 1024):
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
        return src
    except UnicodeDecodeError:
        out = Path(tempfile.mkstemp(suffix=".csv")[1])
        with open(src, encoding="cp1252", errors="replace") as fin, open(out, "w", encoding="utf-8") as fout:
            shutil.copyfileobj(fin, fout)
        return out


def _clean_headers(names: list[str]) -> dict[str, str]:
    """Give blank headers a name and make every header unique: '', 'A', 'A' -> 'Column 1', 'A', 'A (2)'."""
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for i, raw in enumerate(names, start=1):
        base = str(raw).lstrip("\ufeff").strip()
        if m := _DUPLICATED.match(base):  # Polars' name for a repeated CSV header
            base = m.group(1).strip()
        if not base or base.startswith("__UNNAMED__"):  # blank header (calamine)
            base = f"Column {i}"
        name, k = base, 2
        while name in used:
            name, k = f"{base} ({k})", k + 1
        used.add(name)
        mapping[raw] = name
    return mapping


# --------------------------------------------------------------------------- export

def export(lf: pl.LazyFrame, fmt: str, dest: str | Path, *, title: str = "Gridglass export",
           max_pdf_rows: int = 10_000) -> Path:
    fmt = fmt.lower()
    if fmt not in EXPORT_FORMATS:
        raise ExportError(f"Can't export as {fmt}. Choose CSV, Excel, JSON or PDF.")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if fmt == "csv":
            lf.collect().write_csv(dest, include_bom=True)  # BOM: Excel then opens UTF-8 correctly
        elif fmt == "json":
            lf.collect().write_json(dest)
        elif fmt == "xlsx":
            df = lf.collect()
            if df.height > EXCEL_MAX_ROWS:
                raise ExportError(f"Excel allows at most {EXCEL_MAX_ROWS:,} rows; this has {df.height:,}. Export as CSV instead.")
            df.write_excel(dest, worksheet="Data", autofit=True, freeze_panes=(1, 0),
                           header_format={"bold": True})
        else:
            from .pdf import write_pdf

            df = lf.collect()
            if df.height > max_pdf_rows:
                raise ExportError(f"PDF export is limited to {max_pdf_rows:,} rows; this has {df.height:,}. "
                                  "Filter it down first, or export as Excel or CSV.")
            write_pdf(df, dest, title=title)
    except ExportError:
        raise
    except pl.exceptions.PolarsError as exc:
        raise ExportError(f"Export failed: {str(exc).splitlines()[0][:160]}") from exc
    return dest
