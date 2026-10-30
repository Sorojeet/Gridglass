from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from gridglass.engine import build, parse_steps


@pytest.fixture
def orders() -> pl.LazyFrame:
    """A small, messy orders table: one exact duplicate, stray spaces, a blank name, mixed text."""
    return pl.LazyFrame({
        "Order ID": [1, 2, 2, 3, 4, 5],
        "Customer": ["  Asha  Rao ", "Ravi", "Ravi", "meera", None, ""],
        "City": ["Pune", "Delhi", "Delhi", "Pune", "Mumbai", "Pune"],
        "Amount": [100.0, 250.5, 250.5, 80.0, 40.0, 60.0],
        "Date": [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 6), date(2026, 2, 1), None, date(2026, 2, 3)],
        "Full name": ["Asha Rao", "Ravi Kumar", "Ravi Kumar", "Meera", None, "Dev Singh Rathore"],
    })


@pytest.fixture
def apply():
    """apply(lf, {"op": ...}, ...) -> collected DataFrame."""
    def _apply(lf: pl.LazyFrame, *steps: dict) -> pl.DataFrame:
        return build(lf, parse_steps(list(steps))).collect()
    return _apply
