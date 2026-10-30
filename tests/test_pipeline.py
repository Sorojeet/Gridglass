from __future__ import annotations

import json

import polars as pl

from gridglass.engine import preview, profile, run


def test_preview_is_json_ready_and_limited(orders):
    data = preview(orders, limit=3)
    assert [c["name"] for c in data["columns"]][:2] == ["Order ID", "Customer"]
    assert {c["name"]: c["type"] for c in data["columns"]}["Date"] == "date"
    assert len(data["rows"]) == 3 and data["total_rows"] == 6 and data["truncated"] is True
    assert data["rows"][0][4] == "2026-01-05"
    json.dumps(data)  # must not raise


def test_preview_drops_nan():
    data = preview(pl.LazyFrame({"x": [float("nan"), 1.5]}))
    assert data["rows"] == [[None], [1.5]]


def test_profile(orders):
    cols = {c["name"]: c for c in profile(orders)}
    assert cols["Customer"]["blanks"] == 1           # null only; "" is text
    assert cols["City"]["distinct"] == 3
    assert cols["City"]["examples"] == ["Pune", "Delhi", "Mumbai"]
    assert cols["Amount"]["type"] == "decimal" and cols["Order ID"]["type"] == "integer"


def test_run_from_parquet(tmp_path, orders):
    src = tmp_path / "data.parquet"
    orders.collect().write_parquet(src)
    out = run(src, [{"op": "remove_duplicates"}, {"op": "keep_columns", "columns": ["City"]}]).collect()
    assert out.shape == (5, 1)
