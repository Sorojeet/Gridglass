"""File import (CSV, TSV, XLSX, XLS, JSON, NDJSON -> Parquet cache) and export (CSV, XLSX, JSON, PDF)."""
from __future__ import annotations

import codecs
import csv
import io
import json
import math
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from .errors import ExportError, IngestError

INPUT_FORMATS = {"csv", "tsv", "xlsx", "xls", "json", "ndjson"}
EXPORT_FORMATS = {"csv", "xlsx", "json", "pdf"}
XLSX_MAX_ROWS = 1_048_575  # plus one header row
MAX_SPLIT_PAGES = 200       # sheets/pages when splitting by a column
_EXT_ALIASES = {"txt": "csv", "jsonl": "ndjson", "xlsm": "xlsx"}
_SAMPLE = 64 * 1024
_DUPLICATED = re.compile(r"^(.*)_duplicated_\d+$")

#: `header=AUTO` finds the header row; an int picks it (0 = first row); None means there isn't one.
AUTO = "auto"
HEADER_FORMATS = {"csv", "tsv", "xlsx", "xls"}
HEADER_SCAN_ROWS = 30   # the header row is looked for this far down
TOP_ROWS = 50           # rows read to judge how wide the table is
_NUMBERISH = re.compile(r"^[\s₹$€£¥%+\-().,:/0-9]*$")


@dataclass
class IngestResult:
    rows: int
    columns: list[str]
    format: str
    sheets: list[str] = field(default_factory=list)  # .xlsx/.xls only
    sheet: str | None = None
    header_row: int | None = 0  # rows above it were skipped; None = the file has no header row


# --------------------------------------------------------------------------- detect

def detect_format(filename: str, path: str | Path) -> str:
    """Pick the format from the extension, then check the file's first bytes agree."""
    ext = Path(filename).suffix.lower().lstrip(".")
    fmt = _EXT_ALIASES.get(ext, ext)
    if fmt not in INPUT_FORMATS:
        raise IngestError(f"Gridglass can't open .{ext or '?'} files. Try CSV, XLSX or JSON.")
    with open(path, "rb") as fh:
        head = fh.read(_SAMPLE)
    if not head.strip():
        raise IngestError("This file is empty.")
    zip_magic, ole_magic = head.startswith(b"PK\x03\x04"), head.startswith(b"\xd0\xcf\x11\xe0")
    if fmt == "xlsx" and not zip_magic:
        raise IngestError("This doesn't look like a real .xlsx spreadsheet.")
    if fmt == "xls" and not ole_magic:
        if zip_magic:
            return "xlsx"  # renamed .xlsx, common in the wild
        raise IngestError("This doesn't look like a real .xls spreadsheet.")
    if fmt in ("csv", "tsv", "json", "ndjson") and (zip_magic or ole_magic or b"\x00" in head):
        raise IngestError("This file looks like a binary file, not text. Is it a spreadsheet with the wrong file extension?")
    if fmt == "json":
        first = head.lstrip(codecs.BOM_UTF8).lstrip()[:1]
        if first not in (b"[", b"{"):
            raise IngestError("This isn't valid JSON — it should start with [ or {.")
        if first == b"{" and b"\n{" in head:
            return "ndjson"
    return fmt


def workbook_sheets(path: str | Path) -> list[str]:
    import fastexcel

    try:
        return list(fastexcel.read_excel(str(path)).sheet_names)
    except Exception as exc:  # fastexcel raises its own error types
        raise IngestError("Couldn't open this spreadsheet. It may be damaged or password-protected.") from exc


# --------------------------------------------------------------------------- ingest

def ingest(src: str | Path, filename: str, dest: str | Path, *, sheet: str | None = None,
           header: int | None | str = AUTO, max_bytes: int | None = None) -> IngestResult:
    """Read an upload once and store it as Parquet at `dest`; every later step scans that file."""
    src, dest = Path(src), Path(dest)
    if max_bytes is not None and src.stat().st_size > max_bytes:
        raise IngestError(f"This file is larger than the {max_bytes // (1024 * 1024)} MB limit.")
    fmt = detect_format(filename, src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheets: list[str] = []
    header_row: int | None = 0
    try:
        # Everything is read as text first, so a column that changes type part-way down
        # (numbers, then "EW1565…") never fails or loses values. Types are then chosen
        # from the whole column (see infer_types).
        raw = dest.with_name(dest.stem + ".raw.parquet")
        try:
            if fmt in ("csv", "tsv"):
                text = _ensure_utf8(src)
                try:
                    sep, top = _text_top(text, fmt, TOP_ROWS)
                    header_row = _resolve_header(header, top)
                    lf = _scan_text(text, sep, header_row)
                    names = lf.collect_schema().names()
                    lf.rename(dict(zip(names, _clean_names(names if header_row is not None else [""] * len(names))))
                              ).sink_parquet(raw)
                finally:
                    if text != src:
                        text.unlink(missing_ok=True)
            elif fmt in ("xlsx", "xls"):
                sheets = workbook_sheets(src)
                if sheet is not None and sheet not in sheets:
                    raise IngestError(f"There's no sheet called '{sheet}'.")
                sheet = sheet or sheets[0]
                grid = _read_sheet(src, sheet)
                header_row = _resolve_header(header, grid.head(TOP_ROWS).rows())
                _with_header(grid, header_row).write_parquet(raw)
            elif fmt == "json":
                _write(_as_text(pl.read_json(src, infer_schema_length=None)), raw)
            else:
                _write(_as_text(pl.read_ndjson(src, infer_schema_length=None)), raw)
            infer_types(pl.scan_parquet(raw)).sink_parquet(dest)
        finally:
            raw.unlink(missing_ok=True)
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
                        sheet=sheet if fmt in ("xlsx", "xls") else None,
                        header_row=header_row if fmt in HEADER_FORMATS else 0)


# --------------------------------------------------------------------------- header row

def find_header_row(rows: list[tuple | list]) -> int:
    """Where the headers are when a file starts with titles, notes or blank rows.

    The header row is the first row that fills at least half the table's width, is about as wide
    as the row below it, and is mostly words, not numbers. A normal file gets 0, so nothing
    changes for it.
    """
    filled = [[str(v).strip() for v in row if v is not None and str(v).strip()] for row in rows]
    width = max((len(cells) for cells in filled), default=0)
    if width == 0:
        return 0
    need = max(min(2, width), math.ceil(width / 2))
    for i, cells in enumerate(filled[:HEADER_SCAN_ROWS]):
        if len(cells) < need:
            continue
        below = next((len(c) for c in filled[i + 1:] if c), 0)
        if len(cells) * 4 < below * 3:  # a 'Total: 1,234' line is narrower than the table under it
            continue
        words = sum(1 for c in cells if not _NUMBERISH.match(c))
        if words * 2 >= len(cells):
            return i
    return 0  # numbers all the way down: probably no header row, so keep the old behaviour


def _resolve_header(header: int | None | str, top: list) -> int | None:
    if header == AUTO:
        return find_header_row(top)
    if header is None:
        return None
    if not isinstance(header, int) or isinstance(header, bool) or header < 0:
        raise IngestError("Choose the row that holds the headers.")
    if header >= len(top):
        raise IngestError(f"This file has fewer than {header + 1} rows at the top to choose from.")
    return header


def top_rows(src: str | Path, filename: str, *, sheet: str | None = None, n: int = 20) -> list[list[str | None]]:
    """The first rows exactly as they are in the file, so the user can point at the header row."""
    src = Path(src)
    fmt = detect_format(filename, src)
    if fmt not in HEADER_FORMATS:
        raise IngestError("Only CSV and spreadsheet files have a header row to choose.")
    if fmt in ("xlsx", "xls"):
        sheets = workbook_sheets(src)
        rows = _read_sheet(src, sheet if sheet in sheets else sheets[0], n_rows=n).rows()
    else:
        text = _ensure_utf8(src)
        try:
            rows = _text_top(text, fmt, n)[1]
        finally:
            if text != src:
                text.unlink(missing_ok=True)
    return [[None if v is None or not str(v).strip() else str(v) for v in row] for row in rows[:n]]


def _read_sheet(src: Path, sheet: str, n_rows: int | None = None) -> pl.DataFrame:
    """Every cell as text, no header row, blank rows kept (so row positions stay true)."""
    import fastexcel

    try:
        loaded = fastexcel.read_excel(str(src)).load_sheet(sheet, header_row=None, n_rows=n_rows, dtypes="string")
    except Exception as exc:
        raise IngestError("Couldn't open this spreadsheet. It may be damaged or password-protected.") from exc
    df = loaded.to_polars()
    return df.select(pl.all().cast(pl.String))


def _with_header(grid: pl.DataFrame, header_row: int | None) -> pl.DataFrame:
    """Use row `header_row` as the column names and drop everything above it."""
    if header_row is None:
        names, body = [""] * grid.width, grid
    else:
        names = ["" if v is None else str(v) for v in grid.row(header_row)] if grid.height else [""] * grid.width
        body = grid.slice(header_row + 1)
        # A column with no header and nothing in it is just the margin around a titled table.
        empty = body.select(pl.all().is_null().all()).row(0) if body.height else [True] * grid.width
        keep = [i for i, (n, e) in enumerate(zip(names, empty)) if n.strip() or not e]
        names, body = [names[i] for i in keep], body.select([body.columns[i] for i in keep])
    body = body.filter(~pl.all_horizontal(pl.all().is_null())) if body.width else body  # blank rows
    body = body.rename(dict(zip(body.columns, [f"__c{i}" for i in range(body.width)])))
    return body.rename(dict(zip(body.columns, _clean_names(names))))


def _text_top(src: Path, fmt: str, n: int) -> tuple[str, list[list[str]]]:
    """The separator and the first `n` records of a UTF-8 text file."""
    with open(src, "rb") as fh:
        raw = fh.read(_SAMPLE * 4)
    full = len(raw) < _SAMPLE * 4
    sample = raw.decode("utf-8", errors="ignore").lstrip("\ufeff")
    sep = "\t" if fmt == "tsv" else _sniff_separator(_table_part(sample))
    if not full:
        sample = sample[: sample.rfind("\n") + 1]  # never judge from a half-read last line
    rows = []
    for row in csv.reader(io.StringIO(sample, newline=""), delimiter=sep):
        rows.append(row)
        if len(rows) >= n:
            break
    return sep, rows


def _write(df: pl.DataFrame, dest: Path) -> None:
    df.rename(_clean_headers(df.columns)).write_parquet(dest)


def _scan_text(src: Path, sep: str, header_row: int | None) -> pl.LazyFrame:
    return pl.scan_csv(
        src,
        separator=sep,
        has_header=header_row is not None,
        skip_rows=header_row or 0,
        infer_schema=False,  # all text; infer_types() decides from every row
        truncate_ragged_lines=True,
        encoding="utf8-lossy",
    )


def _as_text(df: pl.DataFrame) -> pl.DataFrame:
    """JSON can hold nested lists/objects; keep those as JSON text, everything else as plain text."""
    out = []
    for name, dtype in df.schema.items():
        col = pl.col(name)
        if isinstance(dtype, (pl.List, pl.Array, pl.Struct)):
            out.append(col.map_elements(lambda v: None if v is None else json.dumps(_plain(v), ensure_ascii=False),
                                        return_dtype=pl.String).alias(name))
        elif dtype == pl.Boolean:
            out.append(pl.when(col).then(pl.lit("true")).when(~col).then(pl.lit("false")).alias(name))
        else:
            out.append(col.cast(pl.String).alias(name))
    return df.select(out)


def _plain(v):
    if isinstance(v, pl.Series):
        return [_plain(x) for x in v.to_list()]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


# --------------------------------------------------------------------------- types

#: Whole numbers with more digits than this stay text: long IDs, card and phone numbers.
#: Spreadsheet apps keep only 15 significant digits, so as numbers they'd be silently changed.
MAX_NUMBER_DIGITS = 10

_INT = r"^-?\d+$"
_FLOAT = r"^-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$"
_LEADING_ZERO = r"^-?0\d"
_LONG_WHOLE_PART = r"^-?\d{%d,}" % (MAX_NUMBER_DIGITS + 1)
_DATE_FORMATS = ["%Y-%m-%d"]
_DATETIME_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M",
                     "%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%dT%H:%M:%S%.f"]


def infer_types(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Turn an all-text table into typed columns, looking at every value (not a sample).

    A column becomes a number, date, date-time or true/false only if *every* non-blank cell fits.
    It stays text if any cell doesn't, if a number has a leading zero (011001), or if a whole
    number has more than MAX_NUMBER_DIGITS digits (1565432273931034624).

    To stay fast, the first rows pick which types are possible for each column; only those are
    then checked against the whole column.
    """
    schema = lf.collect_schema()
    names = [n for n, t in schema.items() if t == pl.String]
    if not names:
        return lf

    sample = lf.select(names).head(1000).collect()
    candidates = {name: _possible_types(sample.get_column(name)) for name in names}
    exprs = []
    for i, name in enumerate(names):
        s, filled = _clean(name)
        exprs.append(filled.sum().alias(f"n{i}"))
        for kind in candidates[name]:
            exprs.append((filled & _fits(kind, s)).sum().alias(f"{kind}{i}"))
        if "int" in candidates[name] or "float" in candidates[name]:
            exprs.append((filled & s.str.contains(_FLOAT)
                          & (s.str.contains(_LEADING_ZERO) | s.str.contains(_LONG_WHOLE_PART))).sum().alias(f"keep{i}"))
        if "datetime" in candidates[name]:
            exprs.append((filled & (_stamp(s).dt.time() != pl.time(0))).sum().alias(f"tod{i}"))
    stats = lf.select(exprs).collect().row(0, named=True)

    casts = []
    for i, name in enumerate(names):
        n = stats[f"n{i}"]
        if n == 0 or stats.get(f"keep{i}"):
            continue  # empty, or numbers that must keep every digit / leading zeros: stay text
        kind = next((k for k in candidates[name] if stats[f"{k}{i}"] == n), None)
        if kind:
            casts.append(_cast(kind, name, midnight_only=stats.get(f"tod{i}") == 0))
    return lf.with_columns(casts) if casts else lf


_ORDER = ("int", "float", "date", "datetime", "bool")


def _clean(name: str) -> tuple[pl.Expr, pl.Expr]:
    s = pl.col(name).str.strip_chars()
    return s, s.is_not_null() & (s != "")


def _stamp(s: pl.Expr) -> pl.Expr:
    return pl.coalesce([s.str.to_datetime(f, strict=False, time_unit="us") for f in _DATETIME_FORMATS])


def _fits(kind: str, s: pl.Expr) -> pl.Expr:
    if kind == "int":
        return s.str.contains(_INT)
    if kind == "float":
        return s.str.contains(_FLOAT)
    if kind == "date":
        return (s.str.len_chars() == 10) & s.str.to_date(_DATE_FORMATS[0], strict=False).is_not_null()
    if kind == "datetime":
        return _stamp(s).is_not_null()
    return s.str.to_lowercase().is_in(["true", "false"])


def _possible_types(sample: pl.Series) -> list[str]:
    """Types every non-blank value in the sample fits, most specific first."""
    values = sample.str.strip_chars()
    values = values.filter(values.is_not_null() & (values != ""))
    if values.is_empty():
        return list(_ORDER)  # nothing to go on yet: let the whole column decide
    frame = values.to_frame("v")
    return [k for k in _ORDER if frame.select(_fits(k, pl.col("v")).all()).item()]


def _cast(kind: str, name: str, midnight_only: bool) -> pl.Expr:
    s, filled = _clean(name)
    value = pl.when(filled).then(s)
    if kind == "int":
        return value.cast(pl.Int64).alias(name)
    if kind == "float":
        return value.cast(pl.Float64).alias(name)
    if kind == "date":
        return s.str.to_date(_DATE_FORMATS[0], strict=False).alias(name)
    if kind == "datetime":
        stamp = _stamp(s)
        return (stamp.dt.date() if midnight_only else stamp).alias(name)  # all midnight: just a date
    low = s.str.to_lowercase()
    return pl.when(low == "true").then(True).when(low == "false").then(False).otherwise(None).alias(name)


def _table_part(sample: str) -> str:
    """Title lines above a table confuse separator sniffing; judge from the widest part instead."""
    lines = sample.splitlines()
    if len(lines) < 4:
        return sample
    marks = lambda line: max(line.count(c) for c in ",;\t|")  # noqa: E731
    widest = max(marks(line) for line in lines[:TOP_ROWS])
    start = next((i for i, line in enumerate(lines) if widest and marks(line) * 2 >= widest), 0)
    return "\n".join(lines[start:])


def _sniff_separator(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _ensure_utf8(src: Path) -> Path:
    """Spreadsheet apps on Windows often save CSV as cp1252. Re-encode those to UTF-8 so accents survive."""
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
    return dict(zip(names, _clean_names(names)))


def _clean_names(names: list[str]) -> list[str]:
    used: set[str] = set()
    out: list[str] = []
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
        out.append(name)
    return out


# --------------------------------------------------------------------------- export

def export(lf: pl.LazyFrame, fmt: str, dest: str | Path, *, title: str = "Gridglass export",
           max_pdf_rows: int = 10_000, split_by: str | None = None, max_pages: int = MAX_SPLIT_PAGES) -> Path:
    """Write the result as CSV, XLSX, JSON or PDF.

    `split_by` makes one sheet (.xlsx), or one PDF page, per value of that column.
    """
    fmt = fmt.lower()
    if fmt not in EXPORT_FORMATS:
        raise ExportError(f"Can't export as {fmt}. Choose CSV, XLSX, JSON or PDF.")
    if split_by and fmt not in ("xlsx", "pdf"):
        raise ExportError("Splitting into pages works for XLSX and PDF.")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if fmt == "csv":
            lf.collect().write_csv(dest, include_bom=True)  # BOM: spreadsheet apps then open UTF-8 correctly
            return dest
        if fmt == "json":
            lf.collect().write_json(dest)
            return dest
        df = lf.collect()
        if fmt == "xlsx" and df.height > XLSX_MAX_ROWS:
            raise ExportError(f"A .xlsx sheet holds at most {XLSX_MAX_ROWS:,} rows; this has {df.height:,}. Export as CSV instead.")
        if fmt == "pdf" and df.height > max_pdf_rows:
            raise ExportError(f"PDF export is limited to {max_pdf_rows:,} rows; this has {df.height:,}. "
                              "Filter it down first, or export as XLSX or CSV.")
        parts = _split(df, split_by, max_pages) if split_by else None
        if fmt == "xlsx":
            _write_xlsx(dest, parts or [("Data", df)])
        else:
            from .pdf import write_pdf, write_pdf_sections

            if parts:
                write_pdf_sections([(f"{split_by}: {label}", part) for label, part in parts], dest, title=title)
            else:
                write_pdf(df, dest, title=title)
    except ExportError:
        raise
    except pl.exceptions.PolarsError as exc:
        raise ExportError(f"Export failed: {str(exc).splitlines()[0][:160]}") from exc
    return dest


def _split(df: pl.DataFrame, column: str, max_pages: int) -> list[tuple[str, pl.DataFrame]]:
    """One (label, rows) pair per distinct value of `column`, sorted A→Z with blanks last."""
    if column not in df.columns:
        raise ExportError(f"Column not found: '{column}'.")
    n = df.get_column(column).n_unique()
    if n > max_pages:
        raise ExportError(f"'{column}' has {n:,} different values — too many pages (limit {max_pages}). "
                          "Pick a column with fewer values.")
    keys = df.get_column(column).unique().sort(nulls_last=True).to_list()
    out = []
    for key in keys:
        part = df.filter(pl.col(column).is_null() if key is None else pl.col(column) == key)
        label = "(blank)" if key is None or (isinstance(key, str) and not key.strip()) else str(key)
        out.append((label, part))
    return out


_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def sheet_names(labels: list[str]) -> list[str]:
    r"""Sheet names for .xlsx: no []:*?/\, at most 31 characters, unique (case-insensitive), never empty."""
    used: set[str] = set()
    names = []
    for label in labels:
        base = _BAD_SHEET_CHARS.sub("_", label).strip("' ")[:31] or "Sheet"
        name, k = base, 2
        while name.lower() in used:
            tail = f" ({k})"
            name, k = base[: 31 - len(tail)] + tail, k + 1
        used.add(name.lower())
        names.append(name)
    return names


#: Numbers are written with the spreadsheet's plain "General" style: no thousands commas, no fixed
#: decimals, no red negatives — they show exactly as in the data and the preview.
PLAIN_NUMBERS = {dtype: "General" for dtype in (pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16,
                                                pl.UInt32, pl.UInt64, pl.Float32, pl.Float64, pl.Decimal)}


def _write_xlsx(dest: Path, parts: list[tuple[str, pl.DataFrame]]) -> None:
    import xlsxwriter

    with xlsxwriter.Workbook(dest) as wb:
        for name, (_, part) in zip(sheet_names([label for label, _ in parts]), parts):
            part.write_excel(workbook=wb, worksheet=name, autofit=True, freeze_panes=(1, 0),
                             header_format={"bold": True}, dtype_formats=PLAIN_NUMBERS)
