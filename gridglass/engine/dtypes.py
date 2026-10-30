"""Friendly names for Polars data types, and value coercion for user-typed values."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import polars as pl

from .errors import ColumnError

_NUMBER_JUNK = re.compile(r"[,\s₹$€£¥%]")
_TRUE = {"true", "yes", "y", "1", "t"}
_FALSE = {"false", "no", "n", "0", "f"}

# Friendly type names used in the UI and in step options.
TYPE_NAMES = ("text", "integer", "decimal", "boolean", "date", "datetime")


def friendly_dtype(dtype: pl.DataType) -> str:
    if dtype == pl.String or dtype == pl.Categorical or isinstance(dtype, pl.Enum):
        return "text"
    if dtype.is_integer():
        return "integer"
    if dtype.is_float() or isinstance(dtype, pl.Decimal):
        return "decimal"
    if dtype == pl.Boolean:
        return "boolean"
    if dtype == pl.Date:
        return "date"
    if isinstance(dtype, pl.Datetime) or dtype == pl.Datetime:
        return "datetime"
    if dtype == pl.Null:
        return "empty"
    return str(dtype).lower()


def is_text(dtype: pl.DataType) -> bool:
    return dtype == pl.String


def clean_number(text: str) -> str:
    """'₹1,250.50 ' -> '1250.50'"""
    return _NUMBER_JUNK.sub("", text)


def parse_bool(text: str) -> bool | None:
    t = text.strip().lower()
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    return None


def coerce(value: Any, dtype: pl.DataType, column: str) -> Any:
    """Turn a value the user typed (usually a string) into something comparable with `column`."""
    if value is None:
        return None
    try:
        if dtype == pl.String:
            return str(value)
        if dtype.is_numeric():
            if isinstance(value, bool):
                raise ValueError
            if isinstance(value, (int, float)):
                return value
            s = clean_number(str(value))
            return int(s) if re.fullmatch(r"-?\d+", s) else float(s)
        if dtype == pl.Boolean:
            if isinstance(value, bool):
                return value
            parsed = parse_bool(str(value))
            if parsed is None:
                raise ValueError
            return parsed
        if dtype == pl.Date:
            return value if isinstance(value, date) else date.fromisoformat(str(value).strip()[:10])
        if isinstance(dtype, pl.Datetime):
            return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip())
    except (ValueError, TypeError):
        raise ColumnError(
            f"{value!r} isn't a valid {friendly_dtype(dtype)} for column '{column}'."
        ) from None
    return value
