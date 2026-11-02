"""A quick check of a table for common problems, each with a one-step fix or the tool that fixes it.

Looks at every row (one pass of aggregates), so the counts are exact:
- repeated rows and completely blank rows
- columns with nothing in them
- text with stray spaces, and the same value written differently ('Pune', 'pune ')
- columns that are almost all numbers but stay text because of a few values like 'N/A'
- blank cells per column
"""
from __future__ import annotations

from typing import Any

import polars as pl

from .dtypes import friendly_dtype, is_text
from .io import _NUM_FLOAT, _number_text, _plain_number

#: A text column is "almost numbers" when at least this share of its filled cells are numbers.
NUMBERS_SHARE = 0.8
EXAMPLES = 3


def check(lf: pl.LazyFrame) -> dict[str, Any]:
    schema = lf.collect_schema()
    names = schema.names()
    if not names:
        return {"rows": 0, "columns": [], "issues": []}

    blank = {c: _blank(c, schema[c]) for c in names}
    blank_row = pl.all_horizontal(list(blank.values()))
    exprs = [pl.len().alias("rows"), pl.struct(names).n_unique().alias("unique_rows"), blank_row.sum().alias("blank_rows")]
    for i, c in enumerate(names):
        col = pl.col(c)
        exprs += [blank[c].sum().alias(f"blank{i}"), col.drop_nulls().n_unique().alias(f"distinct{i}"),
                  (blank[c] & ~blank_row).sum().alias(f"gaps{i}")]  # blanks in rows that have something else
        if is_text(schema[c]):
            filled = ~blank[c]
            exprs += [
                (filled & ((col != col.str.strip_chars()) | col.str.contains("  ", literal=True))).sum().alias(f"spaces{i}"),
                (col.drop_nulls().n_unique() - col.drop_nulls().str.strip_chars().str.to_lowercase().n_unique()).alias(f"variants{i}"),
                (filled & _plain_number(_number_text(col.str.strip_chars())).str.contains(_NUM_FLOAT)).sum().alias(f"numbers{i}"),
            ]
    stats = lf.select(exprs).collect().row(0, named=True)
    rows = stats["rows"]

    columns, issues = [], []
    spaces, empty, gaps = [], [], []
    for i, c in enumerate(names):
        blanks = stats[f"blank{i}"]
        columns.append({"name": c, "type": friendly_dtype(schema[c]), "blanks": blanks, "distinct": stats[f"distinct{i}"]})
        if rows and blanks == rows:
            empty.append(c)
            continue
        if stats[f"gaps{i}"]:
            gaps.append((c, stats[f"gaps{i}"]))
        if not is_text(schema[c]):
            continue
        if stats[f"spaces{i}"]:
            spaces.append((c, stats[f"spaces{i}"]))
        if stats[f"variants{i}"] > 0:
            issues.append({
                "kind": "variants", "column": c, "count": stats[f"variants{i}"],
                "message": f"‘{c}’ has the same value written in different ways, such as different capitals or spaces.",
                "examples": _variant_examples(lf, c),
                "fix": {"tool": "change_case"},
            })
        filled = rows - blanks
        numbers = stats[f"numbers{i}"]
        if filled and numbers < filled and numbers / filled >= NUMBERS_SHARE:
            others = (lf.select(pl.col(c)).filter(~blank[c] & ~_plain_number(_number_text(pl.col(c).str.strip_chars()))
                                                  .str.contains(_NUM_FLOAT))
                      .unique(maintain_order=True).head(EXAMPLES).collect().get_column(c).to_list())
            issues.append({
                "kind": "numbers_as_text", "column": c, "count": filled - numbers,
                "message": f"‘{c}’ is almost all numbers, but {filled - numbers:,} "
                           f"{'cell keeps' if filled - numbers == 1 else 'cells keep'} it as text, so it can't be added up.",
                "examples": others,
                "fix": {"tool": "replace_values"},
            })

    dupes = rows - stats["unique_rows"]
    if dupes:
        issues.insert(0, {"kind": "duplicates", "count": dupes,
                          "message": f"{dupes:,} {'row is an exact copy' if dupes == 1 else 'rows are exact copies'} of another row.",
                          "fix": {"step": {"op": "remove_duplicates"}, "label": "Remove copies"}})
    if stats["blank_rows"]:
        n = stats["blank_rows"]
        issues.insert(0, {"kind": "blank_rows", "count": n,
                          "message": f"{n:,} {'row is' if n == 1 else 'rows are'} completely blank.",
                          "fix": {"step": {"op": "remove_blank_rows", "when": "all_blank"}, "label": "Remove blank rows"}})
    if empty and len(empty) < len(names):
        issues.insert(0, {"kind": "empty_columns", "columns": empty, "count": len(empty),
                          "message": f"{_names(empty)} {'has' if len(empty) == 1 else 'have'} nothing in {'it' if len(empty) == 1 else 'them'}.",
                          "fix": {"step": {"op": "remove_columns", "columns": empty},
                                  "label": "Remove " + ("it" if len(empty) == 1 else "them")}})
    if spaces:
        cols = [c for c, _ in spaces]
        total = sum(n for _, n in spaces)
        issues.append({"kind": "spaces", "columns": cols, "count": total,
                       "message": f"{total:,} {'cell has' if total == 1 else 'cells have'} extra spaces, in {_names(cols)}. "
                                  "Spaces you can't see stop filters and lookups from matching.",
                       "fix": {"step": {"op": "trim", "columns": cols, "collapse_spaces": True}, "label": "Trim spaces"}})
    if gaps:
        cols = [c for c, _ in gaps]
        total = sum(n for _, n in gaps)
        issues.append({"kind": "blanks", "columns": cols, "count": total,
                       "message": f"{total:,} blank {'cell' if total == 1 else 'cells'} in {_names(cols)}. "
                                  "Fill them in, or remove the rows that are missing something important.",
                       "fix": {"tool": "fill_blanks"}})
    return {"rows": rows, "columns": columns, "issues": issues}


def _blank(c: str, dtype: pl.DataType) -> pl.Expr:
    col = pl.col(c)
    return (col.is_null() | (col.str.strip_chars() == "")) if is_text(dtype) else col.is_null()


def _variant_examples(lf: pl.LazyFrame, c: str) -> list[list[str]]:
    """A few groups of spellings that only differ by capitals or spaces: [['Pune', 'pune ']]."""
    key = pl.col(c).str.strip_chars().str.to_lowercase()
    groups = (lf.select(pl.col(c)).drop_nulls().unique()
              .group_by(key.alias("_k")).agg(pl.col(c).sort().alias("v"), pl.len().alias("n"))
              .filter(pl.col("n") > 1).sort("n", descending=True).head(EXAMPLES).collect())
    return [vals[:4] for vals in groups.get_column("v").to_list()]


def _names(cols: list[str]) -> str:
    quoted = [f"‘{c}’" for c in cols[:4]]
    more = len(cols) - 4
    text = ", ".join(quoted[:-1]) + (" and " if len(quoted) > 1 else "") + quoted[-1]
    return text + (f" and {more} more" if more > 0 else "")
