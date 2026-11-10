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

#: While steps are being applied, this resolves another upload's id to its data (Merge, Stack).
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
    bad = list(dict.fromkeys(c for c in cols if not schema[c].is_numeric()))  # each name once
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
    """Repeated rows: remove them, show only them, or mark them in a new column.

    Rows are compared on the given columns, or on every column. `keep` decides which copy is the
    original: the first or the last. "mark" says Yes on the copies that "remove" would drop.
    """

    label: ClassVar[str] = "Remove duplicates"
    op: Literal["remove_duplicates"]
    columns: Cols | None = None
    keep: Literal["first", "last"] = "first"
    action: Literal["remove", "show", "mark"] = "remove"
    mark_column: Col = "Duplicate"

    def apply(self, lf, schema):
        if self.columns:
            need(schema, self.columns)
        key = pl.struct(self.columns or list(schema.names()))
        if self.action == "show":  # every copy of a repeated row, so they can be checked side by side
            return lf.filter(key.is_duplicated())
        if self.action == "mark":
            no_clash(list(schema.names()), [self.mark_column])
            original = key.is_first_distinct() if self.keep == "first" else key.is_last_distinct()
            return lf.with_columns(pl.when(original).then(pl.lit("No")).otherwise(pl.lit("Yes")).alias(self.mark_column))
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


#: Clean-up actions for Replace values. Letters include accents and Indian scripts (with their vowel signs).
CLEANERS: dict[str, Callable[[pl.Expr], pl.Expr]] = {
    "special": lambda c: c.str.replace_all(r"[^\p{L}\p{M}\p{N}\s]", "").str.replace_all(r"\s{2,}", " ").str.strip_chars(),
    "digits": lambda c: c.str.replace_all(r"\D", ""),
    "letters": lambda c: c.str.replace_all(r"[^\p{L}\p{M}\s]", "").str.replace_all(r"\s{2,}", " ").str.strip_chars(),
    "email_domain": lambda c: c.str.extract(r"@\s*([^\s@>]+)", 1).str.to_lowercase(),
    "first_word": lambda c: c.str.strip_chars().str.extract(r"^(\S+)", 1),
    "last_word": lambda c: c.str.strip_chars().str.extract(r"(\S+)$", 1),
}


class ReplaceValues(Step):
    """Find and replace, or clean up text (remove special characters, keep only digits, …)."""

    label: ClassVar[str] = "Replace values"
    op: Literal["replace_values"]
    columns: Cols
    action: Literal["replace", "clean"] = "replace"
    find: str = ""
    replace: str = ""
    match: Literal["whole", "part"] = "whole"
    case_sensitive: bool = True
    clean: Literal["special", "digits", "letters", "email_domain", "first_word", "last_word"] | None = None

    @model_validator(mode="after")
    def _action_fields(self):
        if self.action == "clean" and not self.clean:
            raise ValueError("Choose how to clean the text.")
        return self

    def apply(self, lf, schema):
        need(schema, self.columns)
        if self.action == "clean":
            need_text(schema, self.columns, "Cleaning text")
            fix = CLEANERS[self.clean]
            # Blank results become empty cells, not empty text, so 'is blank' filters find them.
            return lf.with_columns([pl.when(fix(pl.col(c)) == "").then(None).otherwise(fix(pl.col(c))).alias(c)
                                    for c in self.columns])
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


class Rule(Condition):
    """One line of an if-then column: when <condition>, the new column says <then>."""
    then: Annotated[str, StringConstraints(max_length=500)] = ""


_NUMBER = re.compile(r"-?(\d+(\.\d*)?|\.\d+)")

DATE_PARTS = ("year", "month", "month_name", "quarter", "weekday", "day", "week", "year_month", "fy")


def _indian_number(x: float) -> str:
    """1234567.5 -> '12,34,567.5' (Indian grouping), for range labels."""
    neg, x = x < 0, abs(x)
    whole, frac = (f"{x:.10f}".rstrip("0").rstrip(".").split(".") + [""])[:2]
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        whole = f"{head},{tail}"
    return ("-" if neg else "") + whole + (f".{frac}" if frac else "")


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


TEXT_FUNCS = ("first", "last", "middle", "before", "after", "between", "word", "length", "find", "pad")


class AddColumn(Step):
    """Add a column: a fixed value, joined columns, math, totals, rules, date parts, ranges or part of a text."""

    label: ClassVar[str] = "Add column"
    op: Literal["add_column"]
    name: Col
    mode: Literal["constant", "combine", "math", "running_total", "rank", "percent", "if_then", "date_part", "ranges",
                  "text"]
    value: Scalar = None                       # constant
    columns: list[Col] | None = None           # combine
    separator: Annotated[str, StringConstraints(max_length=20)] = " "
    left: Col | None = None                    # math: left <operator> (right_column | right_value)
    operator: Literal["+", "-", "*", "/"] | None = None
    right_column: Col | None = None
    right_value: float | None = None
    within: list[Col] | None = None           # running_total / rank / percent: restart for each group
    descending: bool = True                    # rank: largest first gets 1
    rules: Annotated[list[Rule], Field(max_length=20)] | None = None   # if_then: first matching rule wins
    otherwise: Annotated[str, StringConstraints(max_length=500)] = ""  # if_then: when no rule matches
    part: Literal[DATE_PARTS] | None = None    # date_part
    breaks: Annotated[list[float], Field(max_length=30)] | None = None  # ranges: 100, 500 -> under 100 / 100–500 / 500+
    labels: Annotated[list[Annotated[str, StringConstraints(max_length=100)]], Field(max_length=31)] | None = None
    # text: a piece of a text column, like a spreadsheet's LEFT, RIGHT, MID, TEXTBEFORE, TEXTAFTER, LEN, FIND
    func: Literal[TEXT_FUNCS] | None = None
    count: Annotated[int, Field(ge=1, le=10_000)] | None = None    # first / last / middle / word / pad: how many
    start: Annotated[int, Field(ge=1, le=100_000)] | None = None   # middle: first character is 1
    find_text: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None  # before/after/between/find
    end_text: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None   # between: up to this
    from_end: bool = False                       # before/after/between/find: last match; word: count from the end
    if_missing: Literal["blank", "all"] = "blank"  # before/after/between: when the text isn't there
    ignore_case: bool = False
    pad_with: Annotated[str, StringConstraints(min_length=1, max_length=1)] = "0"

    @model_validator(mode="after")
    def _mode_fields(self):
        if self.mode in ("running_total", "rank", "percent", "ranges") and not self.left:
            raise ValueError("Choose a number column.")
        if self.mode == "date_part" and (not self.left or not self.part):
            raise ValueError("Choose a date column and which part of it.")
        if self.mode == "if_then" and not self.rules:
            raise ValueError("Add at least one rule.")
        if self.mode == "ranges":
            if not self.breaks:
                raise ValueError("Type the numbers where the ranges start, e.g. 100, 500, 1000.")
            if sorted(set(self.breaks)) != self.breaks:
                raise ValueError("Range numbers must go up, with no repeats, e.g. 100, 500, 1000.")
            if self.labels is not None and len(self.labels) != len(self.breaks) + 1:
                raise ValueError(f"{len(self.breaks)} numbers make {len(self.breaks) + 1} ranges, so give "
                                 f"{len(self.breaks) + 1} names (or none).")
        if self.mode == "text":
            if not self.left or not self.func:
                raise ValueError("Choose a column and what to take from it.")
            if self.func in ("first", "last", "middle", "word", "pad") and not self.count:
                raise ValueError("Type how many." if self.func != "word" else "Type which word (1 is the first).")
            if self.func == "middle" and not self.start:
                raise ValueError("Type the character to start at (1 is the first).")
            if self.func in ("before", "after", "between", "find") and not self.find_text:
                raise ValueError("Type the text to look for.")
            if self.func == "between" and not self.end_text:
                raise ValueError("Type the text it ends before.")
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
        if self.mode in ("running_total", "rank", "percent"):
            return lf.with_columns(self._totals(schema).alias(self.name))
        if self.mode == "if_then":
            return lf.with_columns(self._if_then(schema).alias(self.name))
        if self.mode == "date_part":
            return lf.with_columns(self._date_part(schema).alias(self.name))
        if self.mode == "ranges":
            return lf.with_columns(self._ranges(schema).alias(self.name))
        if self.mode == "text":
            return lf.with_columns(self._text(schema).alias(self.name))
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

    def _if_then(self, schema) -> pl.Expr:
        """When … then …, checked in order; the first rule that matches wins. All-number answers make a number column."""
        need(schema, [r.column for r in self.rules])
        answers = [r.then for r in self.rules] + [self.otherwise]
        filled = [a.strip() for a in answers if a.strip()]
        numeric = bool(filled) and all(_NUMBER.fullmatch(a.replace(",", "")) for a in filled)

        def value(text: str) -> pl.Expr:
            if not text.strip():
                return pl.lit(None, dtype=pl.Float64 if numeric else pl.String)
            return pl.lit(float(text.replace(",", "")) if numeric else text)

        expr = pl.when(self.rules[0].expr(schema)).then(value(self.rules[0].then))
        for r in self.rules[1:]:
            expr = expr.when(r.expr(schema)).then(value(r.then))
        expr = expr.otherwise(value(self.otherwise))
        if numeric and all(float(a.replace(",", "")).is_integer() for a in filled):
            expr = expr.cast(pl.Int64)
        return expr

    def _text(self, schema) -> pl.Expr:
        """A piece of a text column. Numbers and dates are read as they're shown (236.5, 2026-03-05)."""
        need(schema, [self.left])
        t = pl.col(self.left).cast(pl.String)
        n = self.count
        if self.func == "first":
            return t.str.head(n)
        if self.func == "last":
            return t.str.tail(n)
        if self.func == "middle":
            return t.str.slice(self.start - 1, n)
        if self.func == "length":
            return t.str.len_chars().cast(pl.Int64)
        if self.func == "pad":  # 7 -> 007; longer values are left as they are
            return t.str.pad_start(n, self.pad_with)
        if self.func == "word":  # words are split by spaces; 1 is the first (or the last, counting from the end)
            return t.str.extract_all(r"\S+").list.get(-n if self.from_end else n - 1, null_on_oob=True)
        flags = "(?s" + ("i" if self.ignore_case else "") + ")"
        a = re.escape(self.find_text)
        lead = ".*" if self.from_end else ".*?"  # greedy: the last match; lazy: the first
        if self.func == "find":  # position of the text, 1 for the first character; blank when it isn't there
            return (t.str.extract(f"{flags}^({lead}){a}", 1).str.len_chars() + 1).cast(pl.Int64)
        if self.func == "before":
            piece = t.str.extract(f"{flags}^({lead}){a}", 1)
        elif self.func == "after":
            piece = t.str.extract(f"{flags}^{lead}{a}(.*)$", 1)
        else:  # between: from the find text up to the next end text
            piece = t.str.extract(f"{flags}^{lead}{a}(.*?){re.escape(self.end_text)}", 1)
        return piece.fill_null(t) if self.if_missing == "all" else piece

    def _date_part(self, schema) -> pl.Expr:
        need(schema, [self.left])
        if not schema[self.left].is_temporal():
            raise ColumnError(f"'{self.left}' isn't a date column. Use Change type to make it a date first.")
        d = pl.col(self.left)
        if self.part == "fy":  # Indian financial year, April to March: 5 Mar 2026 -> FY 2025-26
            start = pl.when(d.dt.month() >= 4).then(d.dt.year()).otherwise(d.dt.year() - 1)
            return pl.concat_str([pl.lit("FY "), start.cast(pl.String), pl.lit("-"),
                                  ((start + 1) % 100).cast(pl.String).str.zfill(2)])
        return {
            "year": lambda: d.dt.year().cast(pl.Int64),
            "month": lambda: d.dt.month().cast(pl.Int64),
            "month_name": lambda: d.dt.strftime("%B"),
            "quarter": lambda: pl.concat_str([pl.lit("Q"), d.dt.quarter().cast(pl.String)]),
            "weekday": lambda: d.dt.strftime("%A"),
            "day": lambda: d.dt.day().cast(pl.Int64),
            "week": lambda: d.dt.week().cast(pl.Int64),
            "year_month": lambda: d.dt.strftime("%Y-%m"),
        }[self.part]()

    def _ranges(self, schema) -> pl.Expr:
        """Group numbers into ranges. A number on a boundary goes into the higher range (100 is in 100–500)."""
        need(schema, [self.left])
        need_numeric(schema, [self.left], "Ranges")
        b = self.breaks
        labels = self.labels or (
            [f"Under {_indian_number(b[0])}"]
            + [f"{_indian_number(lo)} – under {_indian_number(hi)}" for lo, hi in zip(b, b[1:])]
            + [f"{_indian_number(b[-1])} and over"])
        if len(set(labels)) != len(labels):
            raise ColumnError("Each range needs a different name.")
        x = pl.col(self.left)
        expr = pl.when(x.is_null()).then(pl.lit(None, dtype=pl.String))
        for edge, label in zip(b, labels):
            expr = expr.when(x < edge).then(pl.lit(label))
        return expr.otherwise(pl.lit(labels[-1]))

    def _totals(self, schema) -> pl.Expr:
        """Running total (in the current row order), rank (1 = largest, ties share a rank), or % of total."""
        need(schema, [self.left] + (self.within or []))
        need_numeric(schema, [self.left], {"running_total": "A running total", "rank": "Rank",
                                           "percent": "% of total"}[self.mode])
        x = pl.col(self.left)
        if self.mode == "running_total":
            expr = x.fill_null(0).cum_sum()
        elif self.mode == "rank":
            expr = x.rank(method="min", descending=self.descending).cast(pl.Int64)
        else:
            total = x.sum()
            expr = pl.when(total == 0).then(None).otherwise((x / total * 100).round(2))
        return expr.over(self.within) if self.within else expr


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
        right = right.with_columns([_as_type(pl.col(r), rschema[r], schema[l]).alias(r)
                                    for l, r in zip(lefts, rights) if rschema[r] != schema[l]])
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


def _as_type(col: pl.Expr, have: pl.DataType, want: pl.DataType) -> pl.Expr:
    """Convert a key column to another file's type; values that don't fit become blank (they can't match)."""
    if is_text(want):
        return col.cast(pl.String)
    if want == pl.Boolean and not have.is_numeric():  # text can't be cast to true/false directly
        text = col.cast(pl.String).str.strip_chars().str.to_lowercase()
        return pl.when(text.is_in(["true", "yes"])).then(True).when(text.is_in(["false", "no"])).then(False)
    return col.cast(want, strict=False)


class Stack(Step):
    """Put other files' rows under this file's rows, matching columns by name.

    Names match ignoring capitals and extra spaces ('Amount' = 'amount '). A column that only
    some files have is blank for the others. If a column's type differs between files it
    becomes text, so nothing is lost.
    """

    label: ClassVar[str] = "Stack files"
    op: Literal["stack"]
    others: Annotated[list[FileId], Field(min_length=1, max_length=50)]
    other_names: list[Annotated[str, StringConstraints(max_length=255)]] | None = None  # for display and source_column
    this_name: Annotated[str, StringConstraints(max_length=255)] | None = None
    source_column: Col | None = None  # add a column saying which file each row came from

    def apply(self, lf, schema):
        resolve = SOURCES.get()
        frames = []
        for i, other in enumerate(self.others):
            try:
                frame = resolve(other) if resolve else None
            except Exception:
                frame = None
            if frame is None:
                name = self._name(i)
                raise ColumnError(f"{name} has expired or was removed. Please add it again.")
            frames.append(frame)

        if self.source_column and self.source_column in schema:
            raise ColumnError(f"There's already a column called '{self.source_column}'. Choose another name.")
        spelling = {_key(c): c for c in schema.names()}
        parts = [lf]
        for frame in frames:
            names = frame.collect_schema().names()
            rename = {}
            for c in names:  # use this file's spelling for matching names
                target = spelling.setdefault(_key(c), c)
                if target != c:
                    rename[c] = target
            if len(set(rename.values()) | (set(names) - set(rename))) < len(names):
                raise ColumnError("A file has two columns with the same name (ignoring capitals and spaces).")
            parts.append(frame.rename(rename) if rename else frame)
        if self.source_column:
            if any(self.source_column in p.collect_schema().names() for p in parts[1:]):
                raise ColumnError(f"There's already a column called '{self.source_column}'. Choose another name.")
            names = [self.this_name or "This file"] + [self._name(i) for i in range(len(frames))]
            parts = [p.with_columns(pl.lit(n, dtype=pl.String).alias(self.source_column)) for p, n in zip(parts, names)]
        try:
            out = pl.concat(parts, how="diagonal_relaxed")
            if self.source_column:  # last, after columns that only later files have
                out = out.select(pl.exclude(self.source_column), pl.col(self.source_column))
            return out
        except pl.exceptions.PolarsError as exc:
            raise ColumnError(f"These files can't be stacked: {str(exc).splitlines()[0][:120]}") from exc

    def _name(self, i: int) -> str:
        names = self.other_names or []
        return names[i] if i < len(names) and names[i] else f"File {i + 2}"


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


# --------------------------------------------------------------------------- summarize

DECIMALS = 2  # pivot sums, averages and medians are rounded to this, and shown with exactly this many

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
        if self.func in ("sum", "average", "median"):
            e = e.round(DECIMALS)  # money-style totals: 236.67, not 236.66666666666666
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
    filters: Annotated[list[Condition], Field(max_length=20)] = []    # only count rows that match (before grouping)
    filter_match: Literal["all", "any"] = "all"
    # Sort: by the Rows labels (A→Z) or by one of the Values ("Sum of Amount"); None keeps the file's order.
    sort_by: Annotated[str, StringConstraints(min_length=1, max_length=300)] | None = None
    descending: bool = False
    # Report filter (like a spreadsheet pivot's Filters area): only rows whose value in this column is one of
    # `report_values` (empty: every value). Pages: with `pages` set to the same column, one pivot per value.
    report_filter: Col | None = None
    report_values: Annotated[list[str | int | float | bool], Field(max_length=500)] = []
    # Report filter pages: one pivot per value of this column (one sheet each when downloaded as .xlsx).
    pages: Col | None = None
    max_columns: ClassVar[int] = MAX_PIVOT_COLUMNS
    max_pages: ClassVar[int] = 200
    ROWS_ORDER: ClassVar[str] = "rows"
    TOTAL_LABEL: ClassVar[str] = "Grand Total"
    BLANK: ClassVar[str] = "(blank)"
    SEP: ClassVar[str] = " · "

    def apply(self, lf, schema):
        if self.filters:  # e.g. only City is Pune: totals and the Grand Total count just those rows
            need(schema, [c.column for c in self.filters])
            hits = [c.expr(schema) for c in self.filters]
            lf = lf.filter(pl.all_horizontal(hits) if self.filter_match == "all" else pl.any_horizontal(hits))
        if self.report_filter:
            need(schema, [self.report_filter])
            if self.report_values:  # values as the app lists them: text, numbers, true/false or ISO dates
                want = schema[self.report_filter]
                chosen = pl.Series(self.report_values, strict=False)
                if want.is_temporal() and chosen.dtype == pl.String:
                    chosen = chosen.str.to_date(strict=False) if want == pl.Date else chosen.str.to_datetime(strict=False)
                chosen = chosen.cast(want, strict=False)
                lf = lf.filter(pl.col(self.report_filter).is_in(chosen.drop_nulls().implode()))
        aggs = list(self.values) or [Aggregation(func="count_rows")]
        keys = self.rows + ([self.columns] if self.columns else [])
        need(schema, keys + [a.column for a in aggs if a.column])
        if len(set(self.rows)) != len(self.rows):
            raise ColumnError("Each column can only be used once in Rows.")
        if self.columns and self.columns in self.rows:
            raise ColumnError(f"'{self.columns}' can't be in both Rows and Columns.")
        if self.report_filter and self.report_filter in keys:
            raise ColumnError(f"'{self.report_filter}' can't be the report filter and in Rows or Columns.")
        need_numeric(schema, [a.column for a in aggs if a.func in ("sum", "average", "median")],
                     "Sum, average and median")
        names = [a.output_name() for a in aggs]
        dupes = sorted({x for x in names if names.count(x) > 1})
        if dupes:
            raise ColumnError(f"The same value is listed twice: {_q(dupes)}.")
        no_clash(keys, names)
        if self.sort_by and self.sort_by != self.ROWS_ORDER and self.sort_by not in names:
            raise ColumnError(f"Sort by one of the Values ({_q(names)}), or by the Rows.")
        if self.pages:
            need(schema, [self.pages])
            if self.pages in keys:
                raise ColumnError(f"'{self.pages}' can't be both a page and in Rows or Columns.")
            if self.pages in names:
                raise ColumnError(f"'{self.pages}' is also the name of a value. Rename one of them first.")
            return self._pages(lf, aggs, names)
        return self._one(lf, aggs, names)

    def _pages(self, lf, aggs, names) -> pl.LazyFrame:
        """One pivot per value of `pages` (sorted A→Z, blanks last), stacked with that value in the first column.

        Each page has its own Grand Total and sort order, like a spreadsheet's report filter pages.
        """
        df = lf.collect()
        p = pl.col(self.pages)
        page = (pl.when(p.is_null() | (p.cast(pl.String).str.strip_chars() == "")).then(pl.lit(self.BLANK))
                .otherwise(p.cast(pl.String)))
        values = df.get_column(self.pages)
        n = values.n_unique()
        if n > self.max_pages:
            raise ColumnError(f"'{self.pages}' has {n:,} different values — too many pages (limit {self.max_pages}). "
                              "Pick a column with fewer values, or filter first.")
        parts = []
        for key in values.unique().sort(nulls_last=True).to_list():
            rows = df.filter(p.is_null() if key is None else p == key)
            part = self._one(rows.lazy(), aggs, names).collect()
            parts.append(part.select(pl.lit(rows.select(page.first()).item()).alias(self.pages), pl.all()))
        if not parts:  # nothing to show: the columns a page would have
            empty = self._one(df.lazy(), aggs, names).collect()
            return empty.select(pl.lit(None, pl.String).alias(self.pages), pl.all()).lazy()
        out = pl.concat(parts, how="diagonal_relaxed")  # a Columns value missing on one page is blank there
        totals = [c for c in out.columns if c == self.TOTAL_LABEL or c.endswith(f"{self.SEP}{self.TOTAL_LABEL}")]
        return out.select([c for c in out.columns if c not in totals] + totals).lazy()  # totals stay on the right

    def _sorted(self, out: pl.LazyFrame, lf: pl.LazyFrame, exprs, names) -> pl.LazyFrame:
        """Order the rows before the Grand Total is added (it always stays last)."""
        if not self.sort_by:
            return out
        if self.sort_by == self.ROWS_ORDER:
            return out.sort(self.rows, descending=self.descending, nulls_last=True, maintain_order=True)
        if self.sort_by in out.collect_schema().names():  # no Columns field: the value is a column
            return out.sort(self.sort_by, descending=self.descending, nulls_last=True, maintain_order=True)
        # With a Columns field the value is spread out: sort by its total for each row.
        key = "__gridglass_sort__"
        totals = lf.group_by(self.rows).agg(exprs[names.index(self.sort_by)].alias(key))
        return (out.join(totals, on=self.rows, how="left", nulls_equal=True, maintain_order="left")
                .sort(key, descending=self.descending, nulls_last=True, maintain_order=True).drop(key))

    def _one(self, lf, aggs, names) -> pl.LazyFrame:
        """The pivot of these rows: grouped, spread across Columns if any, sorted, with totals."""
        keys = self.rows + ([self.columns] if self.columns else [])
        exprs = [a.expr() for a in aggs]

        if not self.columns:  # group-by
            out = self._sorted(lf.group_by(self.rows, maintain_order=True).agg(exprs), lf, exprs, names)
            if self.totals:
                out = self._with_total(out, lf.select(exprs))
            return out

        # Pivot: aggregate per (rows, column value), then spread the column values out.
        # Column values become headers, so blanks get a "(blank)" label instead of "null".
        c = pl.col(self.columns).cast(pl.String)
        lf = lf.with_columns(pl.when(c.is_null() | (c.str.strip_chars() == "")).then(pl.lit(self.BLANK))
                             .when(c.is_in(self.rows)).then(c + " (2)")  # a value named like a Rows column
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
        wide = self._sorted(wide.lazy(), lf, exprs, names).collect()
        if not self.totals:
            return wide.lazy()

        # Grand totals: a column (per row) and a row (per column).
        total_name = (lambda n: self.TOTAL_LABEL) if len(names) == 1 else (lambda n: f"{n}{self.SEP}{self.TOTAL_LABEL}")
        taken = [total_name(n) for n in names if total_name(n) in wide.columns]
        if taken:
            raise ColumnError(f"There's already a column called {_q(taken)}, so the Grand Total column can't use "
                              "that name. Rename it first, or turn off Grand Total.")
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
    """Reshape a table: unpivot (columns into rows, wide to long) or transpose (flip rows and columns).

    Transpose turns every row into a column. The new column names come from `header` (a column whose
    values become the headers, e.g. Product) or are Column 1, 2, 3…; the old column names become the
    first column. Types are worked out again afterwards, so a column of numbers stays numbers.
    """

    label: ClassVar[str] = "Transpose or unpivot"
    op: Literal["unpivot"]
    mode: Literal["unpivot", "transpose"] = "unpivot"
    keep: Cols | None = None           # unpivot: identifier columns that stay as they are
    columns: Cols | None = None        # unpivot: columns to turn into rows; None = all the others
    attribute_name: Col = "Attribute"
    value_name: Col = "Value"
    header: Col | None = None          # transpose: its values become the new column names
    max_rows: ClassVar[int] = 500      # transpose: one new column per row

    @model_validator(mode="after")
    def _mode_fields(self):
        if self.mode == "unpivot" and not self.keep:
            raise ValueError("Choose the columns to keep as they are.")
        return self

    def apply(self, lf, schema):
        if self.mode == "transpose":
            return self._transpose(lf, schema)
        on = self.columns or [c for c in schema.names() if c not in self.keep]
        need(schema, self.keep + on)
        if not on:
            raise ColumnError("Choose at least one column to unpivot.")
        no_clash(self.keep, [self.attribute_name, self.value_name])
        if len({schema[c] for c in on}) > 1:  # mixed types can't share one column
            lf = lf.with_columns(pl.col(on).cast(pl.String))
        # Temporary names: the table may already have columns called Attribute or Value among those turned into rows.
        attr, val = "__gridglass_attr__", "__gridglass_value__"
        return (lf.unpivot(on=on, index=self.keep, variable_name=attr, value_name=val)
                .rename({attr: self.attribute_name, val: self.value_name}))

    def _transpose(self, lf, schema):
        from .io import _clean_names, infer_types

        if self.header:
            need(schema, [self.header])
        rows = lf.select(pl.len()).collect().item()
        if rows > self.max_rows:
            raise ColumnError(f"Transpose makes one column for each row, so it works on up to {self.max_rows:,} rows; "
                              f"this has {rows:,}. Filter or keep fewer rows first.")
        df = lf.collect()
        body = [c for c in df.columns if c != self.header]
        if not body:
            raise ColumnError("There's nothing to flip besides the header column.")
        if self.header:  # each row's value names its column; blanks become Column N, repeats get (2)
            heads = _clean_names(["" if v is None else str(v) for v in df.get_column(self.header).to_list()])
        else:
            heads = [f"Column {i}" for i in range(1, rows + 1)]
        first = self.header or "Field"  # this column lists the old column names
        while first in heads:
            first += " (field)"
        flipped = df.select([pl.col(c).cast(pl.String) for c in body]).transpose(
            include_header=True, header_name=first, column_names=heads)
        return infer_types(flipped.lazy())


# --------------------------------------------------------------------------- registry

STEP_MODELS: tuple[type[Step], ...] = (
    RemoveDuplicates, Trim, ChangeCase, ReplaceValues, FillBlanks, RemoveBlankRows,
    RemoveColumns, KeepColumns, RenameColumns, FilterRows, SortRows, KeepRows,
    ChangeType, SplitColumn, AddColumn, Merge, Stack, Pivot, Unpivot,
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
