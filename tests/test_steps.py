from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from gridglass.engine import OPS, InvalidStepsError, StepError, build, parse_steps


# --------------------------------------------------------------------------- validation

def test_every_tool_is_registered():
    assert len(OPS) == 17
    assert {"remove_duplicates", "trim", "filter_rows", "pivot", "unpivot"} <= set(OPS)


@pytest.mark.parametrize("raw, fragment", [
    ([{"op": "explode_everything"}], "Unknown tool 'explode_everything'"),
    ([{"columns": ["A"]}], "needs an 'op'"),
    ([{"op": "trim", "colums": ["A"]}], "colums"),                       # typo -> extra field rejected
    ([{"op": "remove_columns", "columns": []}], "columns"),
    ([{"op": "fill_blanks", "method": "value"}], "Choose a value"),
    ([{"op": "split_column", "column": "A", "delimiter": ",", "parts": 3, "names": ["x"]}], "exactly 3"),
    ([{"op": "add_column", "name": "X", "mode": "math", "left": "A", "operator": "+"}], "second column or a number"),
    ([{"op": "filter_rows", "conditions": [{"column": "A", "operator": "equals"}]}], "single value"),
])
def test_bad_steps_are_rejected_with_a_clear_message(raw, fragment):
    with pytest.raises(InvalidStepsError) as exc:
        parse_steps(raw)
    assert fragment in exc.value.message
    assert exc.value.to_dict()["problems"][0]["step_index"] == 0


def test_step_limit():
    with pytest.raises(InvalidStepsError, match="Too many steps"):
        parse_steps([{"op": "trim"}] * 3, max_steps=2)


def test_missing_column_names_the_failing_step(orders):
    steps = parse_steps([{"op": "trim"}, {"op": "remove_columns", "columns": ["Nope"]}])
    with pytest.raises(StepError) as exc:
        build(orders, steps)
    assert exc.value.step_index == 1
    assert "'Nope'" in exc.value.message


def test_text_tool_on_number_column_is_refused(orders):
    with pytest.raises(StepError, match="text columns"):
        build(orders, parse_steps([{"op": "trim", "columns": ["Amount"]}]))


def test_steps_stay_lazy(orders):
    out = build(orders, parse_steps([{"op": "trim"}, {"op": "filter_rows",
                "conditions": [{"column": "City", "operator": "equals", "value": "pune"}]}]))
    assert isinstance(out, pl.LazyFrame)


# --------------------------------------------------------------------------- clean

def test_remove_duplicates_all_columns(orders, apply):
    out = apply(orders, {"op": "remove_duplicates"})
    assert out.height == 5
    assert out["Order ID"].to_list() == [1, 2, 3, 4, 5]  # original order kept


def test_remove_duplicates_by_column_keep_last(orders, apply):
    out = apply(orders, {"op": "remove_duplicates", "columns": ["City"], "keep": "last"})
    assert sorted(out["City"].to_list()) == ["Delhi", "Mumbai", "Pune"]
    assert out.filter(pl.col("City") == "Pune")["Order ID"].item() == 5


def test_trim_and_collapse(orders, apply):
    out = apply(orders, {"op": "trim", "collapse_spaces": True})
    assert out["Customer"][0] == "Asha Rao"
    assert out["Customer"][5] == ""


def test_change_case(orders, apply):
    out = apply(orders, {"op": "change_case", "columns": ["Customer"], "case": "title"})
    assert out["Customer"][3] == "Meera"


def test_replace_whole_value_case_insensitive(orders, apply):
    out = apply(orders, {"op": "replace_values", "columns": ["City"], "find": "PUNE",
                         "replace": "Pune City", "case_sensitive": False})
    assert out["City"].to_list().count("Pune City") == 3


def test_replace_part_of_value(orders, apply):
    out = apply(orders, {"op": "replace_values", "columns": ["Full name"], "find": "kumar",
                         "replace": "K.", "match": "part", "case_sensitive": False})
    assert out["Full name"][1] == "Ravi K."


def test_replace_number(orders, apply):
    out = apply(orders, {"op": "replace_values", "columns": ["Amount"], "find": "250.5", "replace": "250"})
    assert out["Amount"][1] == 250.0


def test_fill_blanks_with_value_treats_empty_text_as_blank(orders, apply):
    out = apply(orders, {"op": "fill_blanks", "columns": ["Customer"], "value": "Unknown"})
    assert out["Customer"][4] == "Unknown" and out["Customer"][5] == "Unknown"


def test_fill_down(orders, apply):
    out = apply(orders, {"op": "fill_blanks", "columns": ["Date"], "method": "down"})
    assert out["Date"][4] == date(2026, 2, 1)


def test_remove_blank_rows():
    lf = pl.LazyFrame({"A": [1, None, 3], "B": ["x", " ", None]})
    out = build(lf, parse_steps([{"op": "remove_blank_rows"}])).collect()
    assert out["A"].to_list() == [1, 3]
    out = build(lf, parse_steps([{"op": "remove_blank_rows", "when": "any_blank"}])).collect()
    assert out["A"].to_list() == [1]


# --------------------------------------------------------------------------- shape

def test_remove_keep_rename_columns(orders, apply):
    assert "City" not in apply(orders, {"op": "remove_columns", "columns": ["City"]}).columns
    assert apply(orders, {"op": "keep_columns", "columns": ["City", "Order ID"]}).columns == ["City", "Order ID"]
    assert "Town" in apply(orders, {"op": "rename_columns", "mapping": {"City": "Town"}}).columns


def test_cannot_remove_every_column(orders):
    cols = orders.collect_schema().names()
    with pytest.raises(StepError, match="every column"):
        build(orders, parse_steps([{"op": "remove_columns", "columns": cols}]))


def test_rename_clash(orders):
    with pytest.raises(StepError, match="already exists"):
        build(orders, parse_steps([{"op": "rename_columns", "mapping": {"City": "Amount"}}]))


@pytest.mark.parametrize("cond, expected_ids", [
    ({"column": "City", "operator": "equals", "value": "pune"}, [1, 3, 5]),
    ({"column": "City", "operator": "not_equals", "value": "Pune"}, [2, 2, 4]),
    ({"column": "Amount", "operator": "greater_than", "value": "₹90"}, [1, 2, 2]),
    ({"column": "Amount", "operator": "less_or_equal", "value": 60}, [4, 5]),
    ({"column": "Customer", "operator": "contains", "value": "AV"}, [2, 2]),
    ({"column": "Customer", "operator": "not_contains", "value": "a"}, [4, 5]),  # blanks count as "not containing"
    ({"column": "Full name", "operator": "starts_with", "value": "dev"}, [5]),
    ({"column": "Customer", "operator": "is_blank"}, [4, 5]),
    ({"column": "Date", "operator": "greater_or_equal", "value": "2026-02-01"}, [3, 5]),
    ({"column": "City", "operator": "in_list", "value": ["delhi", "mumbai"]}, [2, 2, 4]),
])
def test_filter_operators(orders, apply, cond, expected_ids):
    out = apply(orders, {"op": "filter_rows", "conditions": [cond]})
    assert out["Order ID"].to_list() == expected_ids


def test_filter_any(orders, apply):
    out = apply(orders, {"op": "filter_rows", "match": "any", "conditions": [
        {"column": "City", "operator": "equals", "value": "Mumbai"},
        {"column": "Amount", "operator": "greater_than", "value": 200},
    ]})
    assert out["Order ID"].to_list() == [2, 2, 4]


def test_filter_bad_value_for_type(orders):
    with pytest.raises(StepError, match="isn't a valid decimal"):
        build(orders, parse_steps([{"op": "filter_rows", "conditions": [
            {"column": "Amount", "operator": "greater_than", "value": "lots"}]}]))


def test_sort_and_keep_rows(orders, apply):
    out = apply(orders, {"op": "sort_rows", "by": [{"column": "Amount", "descending": True}]},
                {"op": "keep_rows", "count": 2})
    assert out["Amount"].to_list() == [250.5, 250.5]
    out = apply(orders, {"op": "keep_rows", "position": "bottom", "count": 1})
    assert out["Order ID"].to_list() == [5]


def test_sort_puts_blanks_last(orders, apply):
    out = apply(orders, {"op": "sort_rows", "by": [{"column": "Date"}]})
    assert out["Date"][-1] is None


def test_change_type_from_text():
    lf = pl.LazyFrame({"n": [" ₹1,250 ", "7", "x"], "d": ["05/01/2026", "31/12/2025", ""], "b": ["Yes", "no", "?"]})
    out = build(lf, parse_steps([{"op": "change_type", "columns": {"n": "integer", "b": "boolean"}},
                                 {"op": "change_type", "columns": {"d": "date"}, "date_format": "%d/%m/%Y"}])).collect()
    assert out["n"].to_list() == [1250, 7, None]
    assert out["d"].to_list() == [date(2026, 1, 5), date(2025, 12, 31), None]
    assert out["b"].to_list() == [True, False, None]


def test_change_type_to_text(orders, apply):
    assert apply(orders, {"op": "change_type", "columns": {"Amount": "text"}})["Amount"].dtype == pl.String


def test_split_column_in_place(orders, apply):
    out = apply(orders, {"op": "split_column", "column": "Full name", "delimiter": " ", "names": ["First", "Last"]})
    assert out.columns[-2:] == ["First", "Last"]
    assert out.row(5, named=True)["Last"] == "Singh Rathore"  # remainder stays in the last part
    assert out.row(3, named=True)["Last"] is None


def test_split_can_reuse_original_name(orders, apply):
    out = apply(orders, {"op": "split_column", "column": "Full name", "delimiter": " ",
                         "names": ["Full name", "Surname"]})
    assert out.columns.count("Full name") == 1 and "Surname" in out.columns


def test_add_column_modes(orders, apply):
    out = apply(orders,
                {"op": "add_column", "name": "Country", "mode": "constant", "value": "India"},
                {"op": "add_column", "name": "Label", "mode": "combine", "columns": ["City", "Order ID"], "separator": "-"},
                {"op": "add_column", "name": "With tax", "mode": "math", "left": "Amount", "operator": "*", "right_value": 1.18},
                {"op": "add_column", "name": "Per item", "mode": "math", "left": "Amount", "operator": "/", "right_value": 0})
    row = out.row(0, named=True)
    assert row["Country"] == "India" and row["Label"] == "Pune-1"
    assert row["With tax"] == pytest.approx(118.0) and row["Per item"] is None


def test_add_column_math_needs_numbers(orders):
    with pytest.raises(StepError, match="number columns"):
        build(orders, parse_steps([{"op": "add_column", "name": "X", "mode": "math",
                                    "left": "City", "operator": "+", "right_value": 1}]))


# --------------------------------------------------------------------------- summarize

SUM_AMOUNT = {"func": "sum", "column": "Amount"}


def test_pivot_without_columns_is_a_group_by(orders, apply):
    out = apply(orders, {"op": "pivot", "rows": ["City"], "values": [
        SUM_AMOUNT, {"func": "count_rows"}, {"func": "count_distinct", "column": "Order ID"}]})
    pune = out.filter(pl.col("City") == "Pune").row(0, named=True)
    assert pune["Sum of Amount"] == 240.0 and pune["Count"] == 3 and pune["Distinct Order ID"] == 3
    assert out["City"].to_list() == ["Pune", "Delhi", "Mumbai"]  # first-seen order


def test_pivot_defaults_to_count(orders, apply):
    assert apply(orders, {"op": "pivot", "rows": ["City"]}).columns == ["City", "Count"]


def test_pivot_grand_total_row(orders, apply):
    out = apply(orders, {"op": "pivot", "rows": ["City"], "values": [SUM_AMOUNT], "totals": True})
    assert out.row(-1) == ("Grand Total", pytest.approx(781.0))


def test_pivot_with_columns_and_grand_totals(orders, apply):
    out = apply(orders, {"op": "remove_duplicates"},
                {"op": "pivot", "rows": ["City"], "columns": "Customer", "values": [{"func": "count_rows"}], "totals": True})
    assert out.columns[0] == "City" and out.columns[-1] == "Grand Total"
    assert out.height == 4 and out["City"][-1] == "Grand Total"
    assert out["Grand Total"].to_list() == [3, 1, 1, 5]  # per city, then everything


def test_pivot_blank_column_values_are_labelled(orders, apply):
    out = apply(orders, {"op": "pivot", "rows": ["City"], "columns": "Customer"})
    assert "(blank)" in out.columns and "null" not in out.columns and "" not in out.columns


def test_pivot_multiple_values_name_columns(orders, apply):
    out = apply(orders, {"op": "pivot", "rows": ["Customer"], "columns": "City",
                         "values": [SUM_AMOUNT, {"func": "count_rows"}]})
    assert "Sum of Amount · Pune" in out.columns and "Count · Delhi" in out.columns


def test_pivot_sum_on_text_refused(orders):
    with pytest.raises(StepError, match="number columns"):
        build(orders, parse_steps([{"op": "pivot", "rows": ["City"], "values": [{"func": "sum", "column": "Customer"}]}]))


def test_pivot_same_column_in_rows_and_columns(orders):
    with pytest.raises(StepError, match="both Rows and Columns"):
        build(orders, parse_steps([{"op": "pivot", "rows": ["City"], "columns": "City"}]))


def test_pivot_then_lazy_again(orders, apply):
    out = apply(orders, {"op": "pivot", "rows": ["Customer"], "columns": "City", "values": [SUM_AMOUNT]},
                {"op": "fill_blanks", "method": "value", "value": 0, "columns": ["Delhi"]})
    assert set(out.columns) == {"Customer", "Pune", "Delhi", "Mumbai"}
    assert 0.0 in out["Delhi"].to_list()


def test_pivot_too_many_columns_guard(monkeypatch):
    from gridglass.engine.steps import Pivot

    monkeypatch.setattr(Pivot, "max_columns", 3)
    lf = pl.LazyFrame({"r": ["a"] * 5, "c": list("vwxyz"), "v": [1] * 5})
    with pytest.raises(StepError, match="too many columns"):
        build(lf, parse_steps([{"op": "pivot", "rows": ["r"], "columns": "c"}]))


def test_group_by_is_gone():
    with pytest.raises(InvalidStepsError, match="Unknown tool 'group_by'"):
        parse_steps([{"op": "group_by", "by": ["City"]}])


def test_unpivot_mixed_types(orders, apply):
    out = apply(orders, {"op": "unpivot", "keep": ["Order ID"], "columns": ["City", "Amount"]})
    assert out.columns == ["Order ID", "Attribute", "Value"]
    assert out.height == 12 and out["Value"].dtype == pl.String


# --------------------------------------------------------------------------- chaining

def test_realistic_recipe(orders, apply):
    out = apply(
        orders,
        {"op": "trim", "collapse_spaces": True},
        {"op": "remove_duplicates"},
        {"op": "fill_blanks", "columns": ["Customer"], "value": "Unknown"},
        {"op": "change_case", "columns": ["Customer"], "case": "title"},
        {"op": "filter_rows", "conditions": [{"column": "Amount", "operator": "greater_or_equal", "value": 50}]},
        {"op": "pivot", "rows": ["City"], "values": [{"func": "sum", "column": "Amount", "name": "Total"}]},
        {"op": "sort_rows", "by": [{"column": "Total", "descending": True}]},
    )
    assert out.to_dicts() == [{"City": "Delhi", "Total": 250.5}, {"City": "Pune", "Total": 240.0}]
