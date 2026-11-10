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
        kind = f".{ext} files" if ext else "files without an extension (like .csv)"
        raise IngestError(f"Gridglass can't open {kind}. Try CSV, XLSX or JSON.")
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
        if fmt in ("json", "ndjson"):  # the parser's own words ("ExpectedObjectContent…") help no one
            raise IngestError(f"Couldn't read this {fmt.upper()} file. It may be cut off or not valid JSON; "
                              "Gridglass reads a list of records, like [{\"Name\": \"Asha\"}, …].") from exc
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

# Numbers written the way people type them: ₹1,23,456.50  Rs. 500/-  $1,234  (250) for -250.
_CURRENCY = r"(?i)^(-?)\s*(?:rs\.?|inr|[₹$€£¥])\s*"
_WHOLE = r"(\d+|\d{1,3}(,\d{3})+|\d{1,2}(,\d{2})*,\d{3})"  # 1234, 1,234,567 or Indian 12,34,567
_NUM_INT = rf"^-?{_WHOLE}$"
_NUM_FLOAT = rf"^-?({_WHOLE}(\.\d*)?|\.\d+)$"
_PARENS = r"^\((.*)\)$"

# Dates written other ways: 05/03/2026, 5-3-26, 5 Mar 2026, 05-Mar-26, March 5, 2026, 2026/03/05.
_MONTH = r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE_SHAPES = {  # shape (after tidying) -> format, for day-first and month-first readings
    r"^\d{4}-\d{1,2}-\d{1,2}$": ("%Y-%m-%d", "%Y-%m-%d"),
    r"^\d{1,2}-\d{1,2}-\d{4}$": ("%d-%m-%Y", "%m-%d-%Y"),
    r"^\d{1,2}-\d{1,2}-\d{2}$": ("%d-%m-%y", "%m-%d-%y"),
    r"^\d{1,2}-[A-Za-z]{3}-\d{4}$": ("%d-%b-%Y", "%d-%b-%Y"),
    r"^\d{1,2}-[A-Za-z]{3}-\d{2}$": ("%d-%b-%y", "%d-%b-%y"),
    r"^[A-Za-z]{3}-\d{1,2}-\d{4}$": ("%b-%d-%Y", "%b-%d-%Y"),
    r"^[A-Za-z]{3}-\d{1,2}-\d{2}$": ("%b-%d-%y", "%b-%d-%y"),
}
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
    plain, messy = {}, {}
    for name in names:
        kinds = _possible_types(sample.get_column(name))
        base = [k for k in kinds if k in _PLAIN]
        extra = [k for k in kinds if k not in _PLAIN]
        # Clean columns are checked the quick way first; ₹/comma/date tidying only runs on the
        # columns that didn't fit (it is several times slower).
        plain[name] = base or extra
        messy[name] = extra if base else []
    chosen = _choose(lf, plain)
    chosen.update(_choose(lf, {n: k for n, k in messy.items() if n not in chosen}))
    casts = [_cast(v[0], name, v[1]) for name, v in chosen.items() if v]
    return lf.with_columns(casts) if casts else lf


def _choose(lf: pl.LazyFrame, candidates: dict[str, list[str]]) -> dict[str, tuple[str, bool] | None]:
    """One pass over the data: for each column, the first candidate type every non-blank cell fits.

    Returns (type, all-midnight) per column, None for a column that must stay text, and leaves
    out columns where no candidate fitted (so other types can still be tried).
    """
    candidates = {n: k for n, k in candidates.items() if k}
    if not candidates:
        return {}
    exprs, tidied = [], []
    for i, (name, kinds) in enumerate(candidates.items()):
        s, filled = _clean(name)
        if {"nint", "nfloat"} & set(kinds):  # tidy once, then check against the tidied text
            tidied.append(_number_text(s).alias(f"__num{i}"))
        if {"dmy", "mdy"} & set(kinds):
            tidied.append(_date_text(s).alias(f"__date{i}"))
        exprs.append(filled.sum().alias(f"n{i}"))
        for kind in kinds:
            exprs.append((filled & _fits(kind, s, i)).sum().alias(f"{kind}{i}"))
        numeric = {"int", "float", "nint", "nfloat"} & set(kinds)
        if numeric:
            n = _plain_number(pl.col(f"__num{i}")) if numeric - {"int", "float"} else s
            exprs.append((filled & n.str.contains(_FLOAT)
                          & (n.str.contains(_LEADING_ZERO) | n.str.contains(_LONG_WHOLE_PART))).sum().alias(f"keep{i}"))
        if "datetime" in kinds:
            exprs.append((filled & (_stamp(s).dt.time() != pl.time(0))).sum().alias(f"tod{i}"))
    stats = (lf.with_columns(tidied) if tidied else lf).select(exprs).collect().row(0, named=True)

    chosen: dict[str, tuple[str, bool] | None] = {}
    for i, (name, kinds) in enumerate(candidates.items()):
        n = stats[f"n{i}"]
        if n == 0 or stats.get(f"keep{i}"):
            chosen[name] = None  # empty, or numbers that must keep every digit / leading zeros
            continue
        kind = next((k for k in kinds if stats[f"{k}{i}"] == n), None)
        if kind:
            chosen[name] = (kind, stats.get(f"tod{i}") == 0)
    return chosen


#: Most specific first. nint/nfloat are numbers with ₹, commas or brackets; dmy/mdy are dates
#: written day-first or month-first. When both readings fit every date, day-first wins.
_ORDER = ("int", "float", "date", "datetime", "bool", "nint", "nfloat", "dmy", "mdy")
_PLAIN = {"int", "float", "date", "datetime", "bool"}


def _number_text(s: pl.Expr) -> pl.Expr:
    """'₹1,23,456.50' -> '1,23,456.50', '(250)' -> '-250', 'Rs. 500/-' -> '500'.

    Commas stay: _NUM_INT/_NUM_FLOAT check they're in the right places (so '1,2,3' isn't a
    number), and _plain_number removes them.
    """
    return s.str.replace(_PARENS, "-$1").str.replace(_CURRENCY, "$1").str.replace(r"\s*/-$", "")


def _plain_number(t: pl.Expr) -> pl.Expr:
    return t.str.replace_all(",", "", literal=True)


def _date_text(s: pl.Expr) -> pl.Expr:
    """'March 5, 2026' -> 'Mar-5-2026', '05/03/26' -> '05-03-26'."""
    return s.str.replace_all(_MONTH, "$1").str.replace_all(r"[\s./,-]+", "-").str.strip_chars("-")


def _any_date(t: pl.Expr, day_first: bool) -> pl.Expr:
    """`t` is text from _date_text."""
    k = 0 if day_first else 1
    return pl.coalesce([pl.when(t.str.contains(shape)).then(t.str.to_date(fmts[k], strict=False))
                        for shape, fmts in _DATE_SHAPES.items()])


def _clean(name: str) -> tuple[pl.Expr, pl.Expr]:
    s = pl.col(name).str.strip_chars()
    return s, s.is_not_null() & (s != "")


def _stamp(s: pl.Expr) -> pl.Expr:
    return pl.coalesce([s.str.to_datetime(f, strict=False, time_unit="us") for f in _DATETIME_FORMATS])


def _fits(kind: str, s: pl.Expr, i: int | None = None) -> pl.Expr:
    """Does each cell fit `kind`? With `i`, tidied text is read from the __num{i}/__date{i} columns."""
    if kind == "int":
        return s.str.contains(_INT)
    if kind == "float":
        return s.str.contains(_FLOAT)
    if kind == "date":
        return (s.str.len_chars() == 10) & s.str.to_date(_DATE_FORMATS[0], strict=False).is_not_null()
    if kind == "datetime":
        return _stamp(s).is_not_null()
    if kind in ("nint", "nfloat"):
        n = _number_text(s) if i is None else pl.col(f"__num{i}")
        return n.str.contains(_NUM_INT if kind == "nint" else _NUM_FLOAT)
    if kind in ("dmy", "mdy"):
        t = _date_text(s) if i is None else pl.col(f"__date{i}")
        return _any_date(t, day_first=kind == "dmy").is_not_null()
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
    if kind in ("nint", "nfloat"):
        number = pl.when(filled).then(_plain_number(_number_text(s)))
        return number.cast(pl.Int64 if kind == "nint" else pl.Float64).alias(name)
    if kind in ("dmy", "mdy"):
        return _any_date(_date_text(s), day_first=kind == "dmy").alias(name)
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
           max_pdf_rows: int = 10_000, split_by: str | None = None, split_rows: int | None = None,
           files: bool = False, orientation: str = "auto", columns: list[str] | None = None,
           max_pages: int = MAX_SPLIT_PAGES, decimals: int | None = None, drop_split: bool = False) -> Path:
    """Write the result as CSV, XLSX, JSON or PDF.

    - `split_by` makes one part per value of that column; `split_rows` one part per N rows.
      Parts become sheets (.xlsx) or pages (PDF), or with `files` separate files in a .zip.
    - `columns` keeps only those columns, in that order.
    - `orientation` (PDF): auto (landscape when wide), portrait or landscape.
    - `decimals` writes every decimal number with exactly that many places (236.50); pivot results use 2.
    - `drop_split` leaves the `split_by` column out of each part: the sheet name already says it (pivot pages).
    """
    fmt = fmt.lower()
    if fmt not in EXPORT_FORMATS:
        raise ExportError(f"Can't export as {fmt}. Choose CSV, XLSX, JSON or PDF.")
    if orientation not in ("auto", "portrait", "landscape"):
        raise ExportError("Page orientation must be auto, portrait or landscape.")
    if split_by and split_rows:
        raise ExportError("Split by a column or by a number of rows, not both.")
    if split_rows is not None and split_rows < 1:
        raise ExportError("Rows per part must be at least 1.")
    split = bool(split_by or split_rows)
    if split and not files and fmt not in ("xlsx", "pdf"):
        raise ExportError("Splitting into pages works for XLSX and PDF. For CSV or JSON, choose separate files.")
    if files and not split:
        raise ExportError("Separate files need a split: by a column or by a number of rows.")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if columns:
            missing = [c for c in columns if c not in lf.collect_schema().names()]
            if missing:
                raise ExportError(f"Column not found: '{missing[0]}'.")
            lf = lf.select(columns)
        if not split and fmt == "csv":
            lf.collect().write_csv(dest, include_bom=True, float_precision=decimals)  # BOM: spreadsheet apps then open UTF-8 correctly
            return dest
        if not split and fmt == "json":
            lf.collect().write_json(dest)
            return dest
        df = lf.collect()
        parts = (_split(df, split_by, max_pages) if split_by else _chunks(df, split_rows, max_pages)) if split else None
        if parts and split_by and drop_split and df.width > 1:
            parts = [(label, part.drop(split_by)) for label, part in parts]
        if files:
            _write_zip(dest, parts, fmt, title=title, orientation=orientation, max_pdf_rows=max_pdf_rows,
                       decimals=decimals)
            return dest
        _check_size(df, fmt, max_pdf_rows)
        if fmt == "xlsx":
            _write_xlsx(dest, parts or [("Data", df)], decimals=decimals)
        else:
            from .pdf import write_pdf, write_pdf_sections

            if parts:
                heading = (lambda label: f"{split_by}: {label}") if split_by else (lambda label: label)
                write_pdf_sections([(heading(label), part) for label, part in parts], dest, title=title,
                                   orientation=orientation, decimals=decimals)
            else:
                write_pdf(df, dest, title=title, orientation=orientation, decimals=decimals)
    except ExportError:
        raise
    except pl.exceptions.PolarsError as exc:
        raise ExportError(f"Export failed: {str(exc).splitlines()[0][:160]}") from exc
    return dest


def _check_size(df: pl.DataFrame, fmt: str, max_pdf_rows: int) -> None:
    if fmt == "xlsx" and df.height > XLSX_MAX_ROWS:
        raise ExportError(f"A .xlsx sheet holds at most {XLSX_MAX_ROWS:,} rows; this has {df.height:,}. Export as CSV instead.")
    if fmt == "pdf" and df.height > max_pdf_rows:
        raise ExportError(f"PDF export is limited to {max_pdf_rows:,} rows; this has {df.height:,}. "
                          "Filter it down first, or export as XLSX or CSV.")


def _chunks(df: pl.DataFrame, size: int, max_pages: int) -> list[tuple[str, pl.DataFrame]]:
    """Parts of `size` rows each: 'Rows 1–10,000', 'Rows 10,001–20,000', …"""
    n = max(1, -(-df.height // size))
    if n > max_pages:
        raise ExportError(f"{size:,} rows per part makes {n:,} parts — the limit is {max_pages}. Choose bigger parts.")
    return [(f"Rows {i * size + 1:,}–{min((i + 1) * size, df.height):,}", df.slice(i * size, size)) for i in range(n)]


_BAD_FILE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _write_zip(dest: Path, parts: list[tuple[str, pl.DataFrame]], fmt: str, *, title: str, orientation: str,
               max_pdf_rows: int, decimals: int | None = None) -> None:
    """One file per part, in a .zip. Names: '<title> - <part>.<fmt>', made safe and unique."""
    import io as _io
    import zipfile

    used: set[str] = set()
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for label, part in parts:
            _check_size(part, fmt, max_pdf_rows)
            base = _BAD_FILE_CHARS.sub("-", f"{title} - {label}").strip(" .-")[:120] or "part"
            name, k = f"{base}.{fmt}", 2
            while name.lower() in used:
                name, k = f"{base} ({k}).{fmt}", k + 1
            used.add(name.lower())
            buf = _io.BytesIO()
            if fmt == "csv":
                part.write_csv(buf, include_bom=True, float_precision=decimals)
            elif fmt == "json":
                part.write_json(buf)
            else:
                tmp = Path(tempfile.mkstemp(suffix=f".{fmt}", dir=dest.parent)[1])
                try:
                    if fmt == "xlsx":
                        _write_xlsx(tmp, [("Data", part)], decimals=decimals)
                    else:
                        from .pdf import write_pdf

                        write_pdf(part, tmp, title=f"{title} — {label}", orientation=orientation, decimals=decimals)
                    buf.write(tmp.read_bytes())
                finally:
                    tmp.unlink(missing_ok=True)
            zf.writestr(name, buf.getvalue())


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


def _write_xlsx(dest: Path, parts: list[tuple[str, pl.DataFrame]], decimals: int | None = None) -> None:
    import xlsxwriter

    formats = PLAIN_NUMBERS if decimals is None else {
        **PLAIN_NUMBERS, **{t: "0." + "0" * decimals if decimals else "0" for t in (pl.Float32, pl.Float64, pl.Decimal)}}

    with xlsxwriter.Workbook(dest) as wb:
        for name, (_, part) in zip(sheet_names([label for label, _ in parts]), parts):
            part.write_excel(workbook=wb, worksheet=name, autofit=True, freeze_panes=(1, 0),
                             header_format={"bold": True}, dtype_formats=formats)
