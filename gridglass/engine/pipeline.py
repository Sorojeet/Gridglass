"""Replay a list of steps over a source file, lazily, and produce previews and column profiles."""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl

from .dtypes import friendly_dtype
from .errors import ColumnError, GridglassError, StepError
from .steps import Step, parse_steps


def build(lf: pl.LazyFrame, steps: list[Step]) -> pl.LazyFrame:
    """Apply each step in order. Errors name the step that failed so the UI can point at it."""
    for i, step in enumerate(steps):
        try:
            schema = lf.collect_schema()
            lf = step.apply(lf, schema)
        except ColumnError as exc:
            raise StepError(str(exc), step_index=i, op=step.op) from None
        except pl.exceptions.PolarsError as exc:
            raise StepError(f"{step.label} couldn't run on this data: {_short(exc)}", step_index=i, op=step.op) from None
    return lf


def open_source(path: str | Path) -> pl.LazyFrame:
    """Every upload is stored as Parquet (see io.ingest), so scanning it is cheap and lazy."""
    return pl.scan_parquet(path)


def run(source: str | Path, raw_steps: Any, max_steps: int = 200) -> pl.LazyFrame:
    return build(open_source(source), parse_steps(raw_steps, max_steps=max_steps))


def collect(lf: pl.LazyFrame) -> pl.DataFrame:
    try:
        return lf.collect()
    except pl.exceptions.PolarsError as exc:
        raise GridglassError(f"Couldn't process the file: {_short(exc)}") from None


def preview(lf: pl.LazyFrame, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    """A page of rows (`offset`, `limit`) plus the total row count, JSON-ready for the grid."""
    page = collect(lf.slice(offset, limit))
    total = collect(lf.select(pl.len())).item()
    return {
        "columns": [{"name": n, "type": friendly_dtype(t)} for n, t in page.schema.items()],
        "rows": [[_cell(v) for v in row] for row in page.iter_rows()],
        "offset": offset,
        "total_rows": total,
        "truncated": total > page.height,
    }


def distinct_values(lf: pl.LazyFrame, column: str, query: str | None = None, limit: int = 200) -> dict[str, Any]:
    """The values in a column with how often each appears — for the filter's value dropdown.

    Sorted A→Z like Excel's filter list. When there are more than `limit`, the most common ones are kept.
    """
    schema = lf.collect_schema()
    if column not in schema:
        raise GridglassError(f"Column not found: '{column}'.")
    v = pl.col("v")
    base = lf.select(pl.col(column).alias("v")).filter(v.is_not_null())
    if schema[column] == pl.String:
        base = base.filter(v.str.strip_chars() != "")
    if query:
        base = base.filter(v.cast(pl.String).str.to_lowercase().str.contains(query.lower(), literal=True))
    counts = base.group_by("v").agg(pl.len().alias("n"))
    distinct = collect(counts.select(pl.len())).item()
    if distinct > limit:
        counts = counts.sort(["n", "v"], descending=[True, False]).head(limit)
    top = collect(counts.sort("v"))
    return {
        "column": column,
        "type": friendly_dtype(schema[column]),
        "values": [{"value": _cell(val), "count": n} for val, n in top.iter_rows()],
        "distinct": distinct,
        "truncated": distinct > limit,
    }


def profile(lf: pl.LazyFrame, sample: int = 3) -> list[dict[str, Any]]:
    """Per-column stats for the column picker: type, blanks, distinct values, a few examples."""
    schema = lf.collect_schema()
    names = list(schema.names())
    if not names:
        return []
    stats = collect(lf.select(
        [pl.len().alias("__rows")]
        + [pl.col(n).null_count().alias(f"__b{i}") for i, n in enumerate(names)]
        + [pl.col(n).n_unique().alias(f"__u{i}") for i, n in enumerate(names)]
    )).row(0, named=True)
    examples = collect(lf.head(500)).select(
        [pl.col(n).drop_nulls().unique(maintain_order=True).head(sample).implode() for n in names]
    ).row(0)
    return [
        {
            "name": n,
            "type": friendly_dtype(schema[n]),
            "rows": stats["__rows"],
            "blanks": stats[f"__b{i}"],
            "distinct": stats[f"__u{i}"],
            "examples": [_cell(v) for v in examples[i]],
        }
        for i, n in enumerate(names)
    ]


def _cell(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, timedelta):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_cell(x) for x in v]
    return str(v)


def _short(exc: Exception, limit: int = 200) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:limit]
