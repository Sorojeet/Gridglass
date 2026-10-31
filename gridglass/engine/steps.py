"""Every Gridglass tool is one step: a validated pydantic model that turns a LazyFrame into a new one.

A step arrives from the browser as JSON, e.g. {"op": "trim", "columns": ["Name"]}.
`parse_steps` validates the whole list; `Step.apply` checks the step against the current
schema (columns exist, types fit) and returns a new LazyFrame. Nothing is computed until
the pipeline collects — except `pivot`, whose output columns depend on the data.
"""
from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Annotated, Any, Callable, ClassVar, Literal, Union, get_args

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, model_validator

from .errors import ColumnError
from .dtypes import clean_number, coerce, friendly_dtype, is_text

Col = Annotated[str, StringConstraints(min_length=1, max_length=255)]
FileId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{22}$")]

#: While steps are being applied, this resolves another upload's id to its data (used by Merge).
#: The pipeline sets it; steps never touch storage directly.
SOURCES: ContextVar[Callable[[str], pl.LazyFrame] | None] = ContextVar("gridglass_sources", default=None)
Cols = Annotated[list[Col], Field(min_length=1, max_length=2000)]
Scalar = Union[bool, int, float, str, None]

MAX_PIVOT_COLUMNS = 200


# --------------------------------------------------------------------------- helpers

def _q(names: list[str]) -> str:
    return ", ".join(f"'{n}'" for n in names)


def need(schema: pl.Schema, cols: list[str]) -> None:
    missing = [c for c in cols if c not in schema]
    if missing:
        noun = "Column" if len(missing) == 1 else "Columns"
        raise ColumnError(f"{noun} not found: {_q(missing)}.")


def need_text(schema: pl.Schema, cols: list[str], tool: str) -> None:
    bad = [c for c in cols if not is_text(schema[c])]
    if bad:
        raise ColumnError(f"{tool} works on text columns. Not text: {_q(bad)}.")


def need_numeric(schema: pl.Schema, cols: list[str], tool: str) -> None:
    bad = [c for c in cols if not schema[c].is_numeric()]
    if bad:
        raise ColumnError(f"{tool} needs number columns. Not numbers: {_q(bad)}.")


def no_clash(existing: list[str], new: list[str]) -> None:
    dupes = sorted({n for n in new if new.count(n) > 1})
    if dupes:
        raise ColumnError(f"New column names repeat: {_q(dupes)}.")
    taken = [n for n in new if n in existing]
    if taken:
        raise ColumnError(f"A column with this name already exists: {_q(taken)}.")


def blank(col: str, dtype: pl.DataType) -> pl.Expr:
    """True where a cell is empty: null, or only whitespace for text."""
    e = pl.col(col).is_null()
    if is_text(dtype):
        e = e | (pl.col(col).str.strip_chars() == "")
    return e


def text_cols(schema: pl.Schema) -> list[str]:
    return [c for c, t in schema.items() if is_text(t)]


# --------------------------------------------------------------------------- base

class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: ClassVar[str] = "Step"

    def apply(self, lf: pl.LazyFrame, schema: pl.Schema) -> pl.LazyFrame:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- clean

class RemoveDuplicates(Step):
    """Drop repeated rows. Compares the given columns, or every column."""

    label: ClassVar[str] = "Remove duplicates"
    op: Literal["remove_duplicates"]
    columns: Cols | None = None
    keep: Literal["first", "last"] = "first"

    def apply(self, lf, schema):
        if self.columns:
            need(schema, self.columns)
        return lf.unique(subset=self.columns, keep=self.keep, maintain_order=True)


class Trim(Step):
    """Remove spaces at the start and end of text; optionally squash inner runs of spaces."""

    label: ClassVar[str] = "Trim spaces"
    op: Literal["trim"]
    columns: Cols | None = None  # None = every text column
    collapse_spaces: bool = False

    def apply(self, lf, schema):
        cols = self.columns or text_cols(schema)
        if not cols:
            return lf
        need(schema, cols)
        need_text(schema, cols, "Trim spaces")
        e = pl.col(cols)
        if self.collapse_spaces:
            e = e.str.replace_all(r"\s+", " ")
        return lf.with_columns(e.str.strip_chars())


class ChangeCase(Step):
    label: ClassVar[str] = "Change case"
    op: Literal["change_case"]
    columns: Cols
    case: Literal["upper", "lower", "title"]

    def apply(self, lf, schema):
        need(schema, self.columns)
        need_text(schema, self.columns, "Change case")
        e = pl.col(self.columns).str
        e = {"upper": e.to_uppercase, "lower": e.to_lowercase, "title": e.to_titlecase}[self.case]()
        return lf.with_columns(e)


class ReplaceValues(Step):
    label: ClassVar[str] = "Replace values"
    op: Literal["replace_values"]
    columns: Cols
    find: str
    replace: str = ""
    match: Literal["whole", "part"] = "whole"
    case_sensitive: bool = True

    def apply(self, lf, schema):
        need(schema, self.columns)
        if self.match == "part":
            need_text(schema, self.columns, "Replace part of a value")
        exprs = []
        for c in self.columns:
            col = pl.col(c)
            if self.match == "part":
                if self.case_sensitive:
                    exprs.append(col.str.replace_all(self.find, self.replace, literal=True))
                else:
                    pattern = "(?i)" + re.escape(self.find)
                    exprs.append(col.str.replace_all(pattern, self.replace.replace("$", "$$")))
            elif is_text(schema[c]):
                hit = (col == self.find) if self.case_sensitive else (col.str.to_lowercase() == self.find.lower())
                exprs.append(pl.when(hit).then(pl.lit(self.replace)).otherwise(col).alias(c))
            else:
                old = coerce(self.find, schema[c], c)
                new = coerce(self.replace, schema[c], c) if self.replace != "" else None
                exprs.append(pl.when(col == old).then(pl.lit(new, dtype=schema[c])).otherwise(col).alias(c))
        return lf.with_columns(exprs)


class FillBlanks(Step):
    """Fill empty cells with a value, or copy the value from the row above (down) or below (up)."""

    label: ClassVar[str] = "Fill blanks"
    op: Literal["fill_blanks"]
    columns: Cols | None = None
    method: Literal["value", "down", "up"] = "value"
    value: Scalar = None

    @model_validator(mode="after")
    def _value_needed(self):
        if self.method == "value" and self.value is None:
            raise ValueError("Choose a value to fill blanks with.")
        return self

    def apply(self, lf, schema):
        cols = self.columns or list(schema.names())
        need(schema, cols)
        exprs = []
        for c in cols:
            col = pl.col(c)
            if is_text(schema[c]):  # treat "" and "   " as blank too
                col = pl.when(col.str.strip_chars() == "").then(None).otherwise(col)
            if self.method == "down":
                col = col.fill_null(strategy="forward")
            elif self.method == "up":
                col = col.fill_null(strategy="backward")
            else:
                col = col.fill_null(pl.lit(coerce(self.value, schema[c], c)))
            exprs.append(col.alias(c))
        return lf.with_columns(exprs)


class RemoveBlankRows(Step):
    label: ClassVar[str] = "Remove blank rows"
    op: Literal["remove_blank_rows"]
    columns: Cols | None = None
    when: Literal["all_blank", "any_blank"] = "all_blank"

    def apply(self, lf, schema):
        cols = self.columns or list(schema.names())
        need(schema, cols)
        blanks = [blank(c, schema[c]) for c in cols]
        hit = pl.all_horizontal(blanks) if self.when == "all_blank" else pl.any_horizontal(blanks)
        return lf.filter(~hit)


# --------------------------------------------------------------------------- shape

class RemoveColumns(Step):
    label: ClassVar[str] = "Remove columns"
    op: Literal["remove_columns"]
    columns: Cols

    def apply(self, lf, schema):
        need(schema, self.columns)
        if set(self.columns) >= set(schema.names()):
            raise ColumnError("You can't remove every column — keep at least one.")
        return lf.drop(self.columns)


class KeepColumns(Step):
    """Keep only these columns, in this order (also used to reorder)."""

    label: ClassVar[str] = "Choose columns"
    op: Literal["keep_columns"]
    columns: Cols

    def apply(self, lf, schema):
        need(schema, self.columns)
        if len(set(self.columns)) != len(self.columns):
            raise ColumnError("Each column can only be chosen once.")
        return lf.select(self.columns)


class RenameColumns(Step):
    label: ClassVar[str] = "Rename columns"
    op: Literal["rename_columns"]
    mapping: Annotated[dict[Col, Col], Field(min_length=1)]

    def apply(self, lf, schema):
        need(schema, list(self.mapping))
        untouched = [c for c in schema.names() if c not in self.mapping]
        no_clash(untouched, list(self.mapping.values()))
        return lf.rename(self.mapping)


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    column: Col
    operator: Literal[
        "equals", "not_equals", "greater_than", "greater_or_equal", "less_than", "less_or_equal",
        "contains", "not_contains", "starts_with", "ends_with", "is_blank", "not_blank", "in_list",
    ]
    value: Scalar | list[Scalar] = None
    case_sensitive: bool = False

    @model_validator(mode="after")
    def _value_shape(self):
        if self.operator in ("is_blank", "not_blank"):
            return self
        if self.operator == "in_list":
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("'in_list' needs a list of values.")
        elif self.value is None or isinstance(self.value, list):
            raise ValueError(f"'{self.operator}' needs a single value.")
        return self

    def expr(self, schema: pl.Schema) -> pl.Expr:
        c, dtype, op = self.column, schema[self.column], self.operator
        col = pl.col(c)
        if op == "is_blank":
            return blank(c, dtype)
        if op == "not_blank":
            return ~blank(c, dtype)
        if op in ("contains", "not_contains", "starts_with", "ends_with"):
            s, v = col.cast(pl.String), str(self.value)
            if not self.case_sensitive:
                s, v = s.str.to_lowercase(), v.lower()
            if op == "starts_with":
                return s.str.starts_with(v)
            if op == "ends_with":
                return s.str.ends_with(v)
            hit = s.str.contains(v, literal=True)
            return hit if op == "contains" else (~hit | col.is_null())
        if op == "in_list":
            vals = [coerce(v, dtype, c) for v in self.value]
            if is_text(dtype) and not self.case_sensitive:
                return col.str.to_lowercase().is_in([str(v).lower() for v in vals])
            return col.is_in(vals)
        v = coerce(self.value, dtype, c)
        if is_text(dtype) and not self.case_sensitive and op in ("equals", "not_equals"):
            col, v = col.str.to_lowercase(), v.lower()
        return {
            "equals": lambda: col == v,
            "not_equals": lambda: (col != v) | col.is_null(),  # blanks are "not equal" too
            "greater_than": lambda: col > v,
            "greater_or_equal": lambda: col >= v,
            "less_than": lambda: col < v,
            "less_or_equal": lambda: col <= v,
        }[op]()


class FilterRows(Step):
    label: ClassVar[str] = "Filter rows"
    op: Literal["filter_rows"]
    conditions: Annotated[list[Condition], Field(min_length=1, max_length=20)]
    match: Literal["all", "any"] = "all"

    def apply(self, lf, schema):
        need(schema, [c.column for c in self.conditions])
        exprs = [c.expr(schema) for c in self.conditions]
        hit = pl.all_horizontal(exprs) if self.match == "all" else pl.any_horizontal(exprs)
        return lf.filter(hit)


class SortKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    column: Col
    descending: bool = False


class SortRows(Step):
    label: ClassVar[str] = "Sort rows"
    op: Literal["sort_rows"]
    by: Annotated[list[SortKey], Field(min_length=1, max_length=10)]

    def apply(self, lf, schema):
        need(schema, [k.column for k in self.by])
        return lf.sort(
            by=[k.column for k in self.by],
            descending=[k.descending for k in self.by],
            nulls_last=True,
            maintain_order=True,
        )


class KeepRows(Step):
    label: ClassVar[str] = "Keep top or bottom rows"
    op: Literal["keep_rows"]
    position: Literal["top", "bottom"] = "top"
    count: Annotated[int, Field(ge=1, le=10_000_000)]

    def apply(self, lf, schema):
        return lf.head(self.count) if self.position == "top" else lf.tail(self.count)


class ChangeType(Step):
    """Convert columns to text, integer, decimal, boolean, date or datetime. Unreadable cells become blank."""

    label: ClassVar[str] = "Change type"
    op: Literal["change_type"]
    columns: Annotated[
        dict[Col, Literal["text", "integer", "decimal", "boolean", "date", "datetime"]], Field(min_length=1)
    ]
    date_format: Annotated[str, StringConstraints(max_length=40)] | None = None  # e.g. "%d/%m/%Y"

    def apply(self, lf, schema):
        need(schema, list(self.columns))
        return lf.with_columns([self._convert(c, t, schema[c]).alias(c) for c, t in self.columns.items()])

    def _convert(self, c: str, target: str, src: pl.DataType) -> pl.Expr:
        col = pl.col(c)
        if target == "text":
            return col.cast(pl.String)
        if is_text(src):
            s = col.str.strip_chars()
            if target in ("integer", "decimal"):
                num = s.str.replace_all(r"[,\s₹$€£¥%]", "").cast(pl.Float64, strict=False)
                return num if target == "decimal" else num.round(0).cast(pl.Int64, strict=False)
            if target == "boolean":
                low = s.str.to_lowercase()
                return (
                    pl.when(low.is_in(["true", "yes", "y", "1", "t"])).then(True)
                    .when(low.is_in(["false", "no", "n", "0", "f"])).then(False)
                    .otherwise(None)
                )
            if target == "date":
                return s.str.to_date(format=self.date_format, strict=False)
            return s.str.to_datetime(format=self.date_format, strict=False)
        dtype = {"integer": pl.Int64, "decimal": pl.Float64, "boolean": pl.Boolean,
                 "date": pl.Date, "datetime": pl.Datetime}[target]
        return col.cast(dtype, strict=False)


class SplitColumn(Step):
    label: ClassVar[str] = "Split column"
    op: Literal["split_column"]
    column: Col
    delimiter: Annotated[str, StringConstraints(min_length=1, max_length=10)]
    parts: Annotated[int, Field(ge=2, le=50)] = 2
    names: list[Col] | None = None
    keep_original: bool = False
    trim_parts: bool = True

    @model_validator(mode="after")
    def _names_match(self):
        if self.names is not None and len(self.names) != self.parts:
            raise ValueError(f"Give exactly {self.parts} names for the new columns.")
        return self

    def apply(self, lf, schema):
        need(schema, [self.column])
        need_text(schema, [self.column], "Split column")
        names = self.names or [f"{self.column} {i}" for i in range(1, self.parts + 1)]
        others = [n for n in schema.names() if n != self.column or self.keep_original]
        no_clash(others, names)
        tmp = "__gridglass_split__"
        out = lf.with_columns(
            pl.col(self.column).str.splitn(self.delimiter, self.parts).struct.rename_fields(names).alias(tmp)
        )
        if not self.keep_original:
            out = out.drop(self.column)  # lets a new part reuse the original name
        out = out.unnest(tmp)
        if self.trim_parts:
            out = out.with_columns(pl.col(names).str.strip_chars())
        # put the new columns where the original was
        order: list[str] = []
        for n in schema.names():
            if n == self.column:
                if self.keep_original:
                    order.append(n)
                order.extend(names)
            else:
                order.append(n)
        return out.select(order)


class AddColumn(Step):
    """Add a column: a fixed value, several columns joined together, or simple math."""

    label: ClassVar[str] = "Add column"
    op: Literal["add_column"]
    name: Col
    mode: Literal["constant", "combine", "math"]
    value: Scalar = None                       # constant
    columns: list[Col] | None = None           # combine
    separator: Annotated[str, StringConstraints(max_length=20)] = " "
    left: Col | None = None                    # math: left <operator> (right_column | right_value)
    operator: Literal["+", "-", "*", "/"] | None = None
    right_column: Col | None = None
    right_value: float | None = None

    @model_validator(mode="after")
    def _mode_fields(self):
        if self.mode == "combine" and not self.columns:
            raise ValueError("Choose the columns to combine.")
        if self.mode == "math":
            if not self.left or not self.operator:
                raise ValueError("Math needs a column and an operator.")
            if (self.right_column is None) == (self.right_value is None):
                raise ValueError("Math needs either a second column or a number, not both.")
        return self

    def apply(self, lf, schema):
        no_clash(list(schema.names()), [self.name])
        if self.mode == "constant":
            return lf.with_columns(pl.lit(self.value).alias(self.name))
        if self.mode == "combine":
            need(schema, self.columns)
            parts = [pl.col(c).cast(pl.String) for c in self.columns]
            return lf.with_columns(pl.concat_str(parts, separator=self.separator, ignore_nulls=True).alias(self.name))
        cols = [self.left] + ([self.right_column] if self.right_column else [])
        need(schema, cols)
        need_numeric(schema, cols, "Math")
        a = pl.col(self.left)
        b = pl.col(self.right_column) if self.right_column else pl.lit(self.right_value)
        if self.operator == "/":
            res = pl.when(b == 0).then(None).otherwise(a / b)  # no infinities in a spreadsheet
        else:
            res = {"+": a + b, "-": a - b, "*": a * b}[self.operator]
        return lf.with_columns(res.alias(self.name))


class JoinKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    left: Col    # column in this file
    right: Col   # matching column in the second file


class Merge(Step):
    """Bring in columns from a second file by matching keys (a lookup), with every kind of join."""

    label: ClassVar[str] = "Merge files"
    op: Literal["merge"]
    other: FileId                                     # the second upload
    other_name: Annotated[str, StringConstraints(max_length=255)] | None = None  # for display only
    keys: Annotated[list[JoinKey], Field(min_length=1, max_length=5)]
    how: Literal["left", "inner", "right", "full", "anti", "semi"] = "left"
    columns: list[Col] | None = None                  # second-file columns to bring; None = all
    first_match: bool = True                          # repeated keys in the second file: use the first
    suffix: Annotated[str, StringConstraints(min_length=1, max_length=20)] = " (2)"

    ORDER: ClassVar[dict[str, str]] = {"left": "left", "inner": "left", "semi": "left", "anti": "left",
                                       "right": "right", "full": "left_right"}

    def apply(self, lf, schema):
        resolve = SOURCES.get()
        try:
            right = resolve(self.other) if resolve else None
        except Exception:
            right = None
        if right is None:
            raise ColumnError("The second file has expired or was removed. Please upload it again.")
        rschema = right.collect_schema()
        lefts, rights = [k.left for k in self.keys], [k.right for k in self.keys]
        need(schema, lefts)
        missing = [c for c in rights + (self.columns or []) if c not in rschema]
        if missing:
            raise ColumnError(f"Not in the second file: {_q(missing)}.")

        bring = [] if self.how in ("anti", "semi") else (
            self.columns if self.columns is not None else [c for c in rschema.names() if c not in rights])
        right = right.select(list(dict.fromkeys(rights + bring)))
        # Keys must have the same type to match: convert the second file's keys to this file's types.
        right = right.with_columns([
            (pl.col(r).cast(pl.String) if is_text(schema[l]) else pl.col(r).cast(schema[l], strict=False)).alias(r)
            for l, r in zip(lefts, rights) if rschema[r] != schema[l]
        ])
        if self.first_match and self.how not in ("anti", "semi"):
            right = right.unique(subset=rights, keep="first", maintain_order=True)
        # Give the second file's keys this file's names, so every join type shows one key column named as here.
        clash = {c: f"{c}{self.suffix}" for c in bring if c in lefts and c not in rights}
        right = right.rename(clash).rename({r: l for l, r in zip(lefts, rights) if r != l})
        out = lf.join(right, on=lefts, how=self.how, suffix=self.suffix,
                      coalesce=True, maintain_order=self.ORDER[self.how])
        names = out.collect_schema().names()  # keep this file's column order, new columns after
        first = [c for c in schema.names() if c in names]
        return out.select(first + [c for c in names if c not in first])


# --------------------------------------------------------------------------- summarize

_AGG_TITLE = {  # readable names: "Sum of Amount"
    "sum": "Sum of {c}", "average": "Average of {c}", "min": "Min of {c}", "max": "Max of {c}",
    "median": "Median of {c}", "count": "Count of {c}", "count_distinct": "Distinct {c}",
    "first": "First {c}", "last": "Last {c}",
}


class Aggregation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    func: Literal["sum", "average", "min", "max", "median", "count", "count_distinct",
                  "first", "last", "count_rows"]
    column: Col | None = None   # not used by count_rows
    name: Col | None = None

    @model_validator(mode="after")
    def _column_needed(self):
        if self.func != "count_rows" and not self.column:
            raise ValueError(f"'{self.func}' needs a column.")
        return self

    def output_name(self) -> str:
        if self.name:
            return self.name
        return "Count" if self.func == "count_rows" else _AGG_TITLE[self.func].format(c=self.column)

    def expr(self) -> pl.Expr:
        if self.func == "count_rows":
            return pl.len().alias(self.output_name())
        c = pl.col(self.column)
        e = {
            "sum": c.sum, "average": c.mean, "min": c.min, "max": c.max, "median": c.median,
            "count": c.count, "count_distinct": c.n_unique, "first": c.first, "last": c.last,
        }[self.func]()
        return e.alias(self.output_name())


class Pivot(Step):
    """Summarize like a classic pivot table: Rows, an optional Columns field, and one or more Values.

    Without Columns it's a group-by: one row per group with the totals you ask for.
    With Columns, each distinct value of that column becomes its own column.
    """

    label: ClassVar[str] = "Pivot table"
    op: Literal["pivot"]
    rows: Cols                                                        # Rows
    columns: Col | None = None                                        # Columns (optional)
    values: Annotated[list[Aggregation], Field(max_length=20)] = []   # Values (default: count)
    totals: bool = False                                              # Grand Total row
    max_columns: ClassVar[int] = MAX_PIVOT_COLUMNS
    TOTAL_LABEL: ClassVar[str] = "Grand Total"
    BLANK: ClassVar[str] = "(blank)"
    SEP: ClassVar[str] = " · "

    def apply(self, lf, schema):
        aggs = list(self.values) or [Aggregation(func="count_rows")]
        keys = self.rows + ([self.columns] if self.columns else [])
        need(schema, keys + [a.column for a in aggs if a.column])
        if len(set(self.rows)) != len(self.rows):
            raise ColumnError("Each column can only be used once in Rows.")
        if self.columns and self.columns in self.rows:
            raise ColumnError(f"'{self.columns}' can't be in both Rows and Columns.")
        need_numeric(schema, [a.column for a in aggs if a.func in ("sum", "average", "median")],
                     "Sum, average and median")
        names = [a.output_name() for a in aggs]
        dupes = sorted({x for x in names if names.count(x) > 1})
        if dupes:
            raise ColumnError(f"The same value is listed twice: {_q(dupes)}.")
        no_clash(keys, names)
        exprs = [a.expr() for a in aggs]

        if not self.columns:  # group-by
            out = lf.group_by(self.rows, maintain_order=True).agg(exprs)
            if self.totals:
                out = self._with_total(out, lf.select(exprs))
            return out

        # Pivot: aggregate per (rows, column value), then spread the column values out.
        # Column values become headers, so blanks get a "(blank)" label instead of "null".
        c = pl.col(self.columns).cast(pl.String)
        lf = lf.with_columns(pl.when(c.is_null() | (c.str.strip_chars() == "")).then(pl.lit(self.BLANK))
                             .otherwise(c).alias(self.columns))
        long = lf.group_by(keys, maintain_order=True).agg(exprs).collect()
        n = long.get_column(self.columns).n_unique()
        if n * len(aggs) > self.max_columns:
            raise ColumnError(
                f"'{self.columns}' has {n:,} different values — that would make too many columns "
                f"(limit {self.max_columns}). Pick a column with fewer distinct values, or filter first."
            )
        wide = long.pivot(on=self.columns, index=self.rows, values=names,
                          aggregate_function="first", separator=self.SEP)
        if not self.totals:
            return wide.lazy()

        # Grand totals: a column (per row) and a row (per column).
        total_name = (lambda n: self.TOTAL_LABEL) if len(names) == 1 else (lambda n: f"{n}{self.SEP}{self.TOTAL_LABEL}")
        row_totals = (lf.group_by(self.rows, maintain_order=True).agg(exprs)
                      .rename({n: total_name(n) for n in names}).collect())
        wide = wide.join(row_totals, on=self.rows, how="left", nulls_equal=True, maintain_order="left")
        tmp = "__gridglass_total__"
        bottom = (lf.group_by(self.columns, maintain_order=True).agg(exprs)
                  .with_columns(pl.lit(tmp).alias(tmp)).collect()
                  .pivot(on=self.columns, index=tmp, values=names, aggregate_function="first", separator=self.SEP)
                  .drop(tmp))
        corner = lf.select(exprs).rename({n: total_name(n) for n in names}).collect()
        return self._with_total(wide.lazy(), pl.concat([bottom, corner], how="horizontal").lazy())

    def _with_total(self, out: pl.LazyFrame, total: pl.LazyFrame) -> pl.LazyFrame:
        """Append a Grand Total row; the first Rows column holds the label, so it becomes text."""
        order = out.collect_schema().names()
        first = self.rows[0]
        out = out.with_columns(pl.col(first).cast(pl.String))
        total = total.with_columns(pl.lit(self.TOTAL_LABEL).alias(first))
        return pl.concat([out, total], how="diagonal_relaxed").select(order)


class Unpivot(Step):
    """Turn columns into rows (wide table to long table)."""

    label: ClassVar[str] = "Unpivot columns"
    op: Literal["unpivot"]
    keep: Cols                         # identifier columns that stay as they are
    columns: Cols | None = None        # columns to turn into rows; None = all the others
    attribute_name: Col = "Attribute"
    value_name: Col = "Value"

    def apply(self, lf, schema):
        on = self.columns or [c for c in schema.names() if c not in self.keep]
        need(schema, self.keep + on)
        if not on:
            raise ColumnError("Choose at least one column to unpivot.")
        no_clash(self.keep, [self.attribute_name, self.value_name])
        if len({schema[c] for c in on}) > 1:  # mixed types can't share one column
            lf = lf.with_columns(pl.col(on).cast(pl.String))
        return lf.unpivot(on=on, index=self.keep, variable_name=self.attribute_name, value_name=self.value_name)


# --------------------------------------------------------------------------- registry

STEP_MODELS: tuple[type[Step], ...] = (
    RemoveDuplicates, Trim, ChangeCase, ReplaceValues, FillBlanks, RemoveBlankRows,
    RemoveColumns, KeepColumns, RenameColumns, FilterRows, SortRows, KeepRows,
    ChangeType, SplitColumn, AddColumn, Merge, Pivot, Unpivot,
)

AnyStep = Annotated[Union[STEP_MODELS], Field(discriminator="op")]

#: op name -> step model, e.g. OPS["trim"] is Trim
OPS: dict[str, type[Step]] = {get_args(m.model_fields["op"].annotation)[0]: m for m in STEP_MODELS}

_adapter = TypeAdapter(list[AnyStep])


def parse_steps(raw: Any, max_steps: int = 200) -> list[Step]:
    """Validate a JSON list of steps. Raises InvalidStepsError with field-level messages."""
    from pydantic import ValidationError

    from .errors import InvalidStepsError

    if not isinstance(raw, list):
        raise InvalidStepsError("Steps must be a list.")
    if len(raw) > max_steps:
        raise InvalidStepsError(f"Too many steps (limit {max_steps}).")
    try:
        return _adapter.validate_python(raw)
    except ValidationError as exc:
        problems = []
        for err in exc.errors(include_url=False, include_input=False):
            loc = list(err["loc"])
            index = loc[0] if loc and isinstance(loc[0], int) else None
            field = ".".join(str(p) for p in loc[2:]) or None  # loc[1] is the op name
            if err["type"] == "union_tag_invalid":
                msg = f"Unknown tool '{err.get('ctx', {}).get('tag', '?')}'."
            elif err["type"] == "union_tag_not_found":
                msg = "Each step needs an 'op' naming the tool."
            else:
                msg = err["msg"].removeprefix("Value error, ")
                if field:
                    msg = f"{field}: {msg}"
            problems.append({"step_index": index, "field": field, "message": msg})
        first = problems[0]
        where = f"Step {first['step_index'] + 1}: " if first["step_index"] is not None else ""
        raise InvalidStepsError(f"{where}{first['message']}", problems=problems) from None


__all__ = ["Step", "OPS", "parse_steps", "friendly_dtype", "clean_number"]
