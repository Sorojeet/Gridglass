from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from gridglass.engine import OPS, InvalidStepsError, StepError, build, parse_steps


# --------------------------------------------------------------------------- validation

def test_every_tool_is_registered():
    assert len(OPS) == 19
    assert {"remove_duplicates", "trim", "filter_rows", "merge", "stack", "pivot", "unpivot"} <= set(OPS)


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


def test_transpose_names_columns_from_a_column(apply):
    lf = pl.LazyFrame({"Product": ["Tea", "Coffee", None, "Tea"], "Jan": [120, 90, 5, 1], "Feb": [135, 80, 6, 2]})
    out = apply(lf, {"op": "unpivot", "mode": "transpose", "header": "Product"})
    assert out.columns == ["Product", "Tea", "Coffee", "Column 3", "Tea (2)"]  # blanks numbered, repeats marked
    assert out["Product"].to_list() == ["Jan", "Feb"]
    assert out["Tea"].dtype == pl.Int64 and out["Coffee"].to_list() == [90, 80]  # numbers come back as numbers


def test_transpose_without_a_header_column(apply):
    lf = pl.LazyFrame({"Name": ["A", "B"], "Score": [1, 2]})
    out = apply(lf, {"op": "unpivot", "mode": "transpose"})
    assert out.columns == ["Field", "Column 1", "Column 2"]
    assert out.rows() == [("Name", "A", "B"), ("Score", "1", "2")]  # mixed columns stay text
    back = apply(out.lazy(), {"op": "unpivot", "mode": "transpose", "header": "Field"})
    assert back.columns == ["Field", "Name", "Score"] and back["Score"].dtype == pl.Int64


def test_transpose_has_a_row_limit(apply):
    from gridglass.engine import StepError

    lf = pl.LazyFrame({"x": list(range(501))})
    with pytest.raises(StepError, match="up to 500 rows"):
        apply(lf, {"op": "unpivot", "mode": "transpose"})


def test_unpivot_still_needs_columns_to_keep():
    with pytest.raises(Exception, match="keep"):
        parse_steps([{"op": "unpivot"}])


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



# --------------------------------------------------------------------------- merge (lookup and joins)

OTHER = "R" * 22
REGIONS = pl.LazyFrame({
    "Town": ["Pune", "Delhi", "Delhi", "Chennai"],
    "Region": ["West", "North", "North again", "South"],
    "Pin": ["411", "110", "110x", "600"],
})


def merge(lf, resolve=lambda _id: REGIONS, **kw):
    step = {"op": "merge", "other": OTHER, "keys": [{"left": "City", "right": "Town"}], **kw}
    return build(lf, parse_steps([step]), resolve=resolve).collect()


@pytest.mark.parametrize("how, rows", [("left", 6), ("inner", 5), ("right", 6), ("full", 7), ("anti", 1), ("semi", 5)])
def test_every_join(orders, how, rows):
    out = merge(orders, how=how)
    assert out.height == rows
    assert out.columns[:6] == orders.collect_schema().names()  # this file's columns keep their order
    if how in ("anti", "semi"):
        assert out.columns == orders.collect_schema().names()  # no columns brought in
    else:
        assert {"Region", "Pin"} <= set(out.columns) and "Town" not in out.columns


def test_vlookup_uses_first_match(orders):
    out = merge(orders)
    delhi = out.filter(pl.col("City") == "Delhi")["Region"].unique().to_list()
    assert delhi == ["North"] and out.height == 6  # no extra rows from the repeated Delhi key


def test_all_matches_can_multiply_rows(orders):
    out = merge(orders, first_match=False)
    assert out.filter(pl.col("City") == "Delhi").height == 4  # 2 orders x 2 matches


def test_full_join_keeps_keys_from_both_sides(orders):
    out = merge(orders, how="full")
    assert "Chennai" in out["City"].to_list() and "Mumbai" in out["City"].to_list()


def test_choose_columns_and_name_clash(orders):
    clash = pl.LazyFrame({"Town": ["Pune"], "Amount": [1.0]})
    out = merge(orders, resolve=lambda _id: clash, columns=["Amount"])
    assert "Amount (2)" in out.columns and out.filter(pl.col("City") == "Pune")["Amount (2)"][0] == 1.0


def test_key_types_are_aligned(orders):
    ids = pl.LazyFrame({"Code": ["1", "2", "x"], "Status": ["new", "paid", "?"]})
    step = {"op": "merge", "other": OTHER, "keys": [{"left": "Order ID", "right": "Code"}]}
    out = build(orders, parse_steps([step]), resolve=lambda _id: ids).collect()
    assert out.filter(pl.col("Order ID") == 2)["Status"].to_list() == ["paid", "paid"]
    assert out["Order ID"].dtype == pl.Int64  # this file's column keeps its type


def test_two_keys(orders):
    other = pl.LazyFrame({"City": ["Pune", "Pune"], "Order ID": [1, 3], "Note": ["a", "b"]})
    step = {"op": "merge", "other": OTHER, "keys": [{"left": "City", "right": "City"}, {"left": "Order ID", "right": "Order ID"}]}
    out = build(orders, parse_steps([step]), resolve=lambda _id: other).collect()
    assert out.filter(pl.col("Note").is_not_null())["Order ID"].to_list() == [1, 3]


def test_missing_second_file_column(orders):
    with pytest.raises(StepError, match="Not in the second file: 'Nope'"):
        merge(orders, columns=["Nope"])


def test_second_file_gone(orders):
    def gone(_id):
        raise FileNotFoundError
    with pytest.raises(StepError, match="expired or was removed"):
        merge(orders, resolve=gone)


def test_bad_other_id_rejected():
    with pytest.raises(InvalidStepsError, match="other"):
        parse_steps([{"op": "merge", "other": "../etc", "keys": [{"left": "a", "right": "b"}]}])


# --------------------------------------------------------------------------- stack files

A_ID, B_ID = "a" * 22, "b" * 22


def stack(lf, files, **kw):
    step = {"op": "stack", "others": list(files), **kw}
    return build(lf, parse_steps([step]), resolve=lambda i: files[i]).collect()


def test_stack_puts_rows_underneath_matching_names():
    jan = pl.LazyFrame({"Order": [1, 2], "Amount": [10.0, 20.0]})
    feb = pl.LazyFrame({" amount ": [30.0], "ORDER": [3], "Note": ["late"]})
    out = stack(jan, {A_ID: feb})
    assert out.columns == ["Order", "Amount", "Note"]
    assert out.rows() == [(1, 10.0, None), (2, 20.0, None), (3, 30.0, "late")]


def test_stack_keeps_values_when_types_differ():
    jan = pl.LazyFrame({"ID": [1, 2]})
    feb = pl.LazyFrame({"ID": ["EW1"]})
    out = stack(jan, {A_ID: feb})
    assert out["ID"].to_list() == ["1", "2", "EW1"]


def test_stack_many_files_with_a_source_column():
    one, two = (pl.LazyFrame({"x": [i]}) for i in (1, 2))
    three = pl.LazyFrame({"x": [3], "late": ["yes"]})
    out = stack(one, {A_ID: two, B_ID: three}, other_names=["feb.csv", "mar.csv"], this_name="jan.csv",
                source_column="Source file")
    assert out.columns == ["x", "late", "Source file"]
    assert out.rows() == [(1, None, "jan.csv"), (2, None, "feb.csv"), (3, "yes", "mar.csv")]


def test_stack_errors_are_friendly():
    lf = pl.LazyFrame({"x": [1], "Source file": ["?"]})
    with pytest.raises(StepError, match="already a column"):
        stack(lf, {A_ID: pl.LazyFrame({"x": [2]})}, source_column="Source file")
    with pytest.raises(StepError, match="feb.csv has expired"):
        def gone(_id):
            raise FileNotFoundError
        build(lf, parse_steps([{"op": "stack", "others": [A_ID], "other_names": ["feb.csv"]}]), resolve=gone).collect()
    with pytest.raises(StepError, match="same name"):
        stack(pl.LazyFrame({"x": [1]}), {A_ID: pl.LazyFrame({"X": [1], "x ": [2]})})
    with pytest.raises(InvalidStepsError):
        parse_steps([{"op": "stack", "others": []}])


# --------------------------------------------------------------------------- duplicates: show / mark

def run(lf, steps):
    return build(lf, parse_steps(steps)).collect()


DUPES = pl.LazyFrame({"Email": ["a@x.in", "b@x.in", "a@x.in", "c@x.in"], "N": [1, 2, 3, 4]})


def test_show_only_duplicates_keeps_every_copy():
    out = run(DUPES, [{"op": "remove_duplicates", "columns": ["Email"], "action": "show"}])
    assert out["N"].to_list() == [1, 3]


@pytest.mark.parametrize("keep, marks", [("first", ["No", "No", "Yes", "No"]), ("last", ["Yes", "No", "No", "No"])])
def test_mark_duplicates(keep, marks):
    out = run(DUPES, [{"op": "remove_duplicates", "columns": ["Email"], "action": "mark", "keep": keep, "mark_column": "Repeat"}])
    assert out["Repeat"].to_list() == marks and out.height == 4


def test_mark_column_must_be_new():
    with pytest.raises(StepError):
        run(DUPES, [{"op": "remove_duplicates", "action": "mark", "mark_column": "Email"}])


# --------------------------------------------------------------------------- replace values: clean up text

@pytest.mark.parametrize("clean, out", [
    ("special", ["Rs 1234 paid", "राम कुमार", "abMailcom", None]),
    ("digits", ["1234", None, None, None]),
    ("letters", ["Rs paid", "राम कुमार", "abMailcom", None]),
    ("email_domain", [None, None, "mail.com", None]),
    ("first_word", ["Rs.", "राम", "a.b@Mail.com", None]),
    ("last_word", ["(paid)!", "कुमार!", "a.b@Mail.com", None]),
])
def test_clean_up_text(clean, out):
    lf = pl.LazyFrame({"T": ["Rs. 1,234/- (paid)!", "  राम  कुमार! ", "a.b@Mail.com", "!!!"]})
    got = run(lf, [{"op": "replace_values", "columns": ["T"], "action": "clean", "clean": clean}])["T"].to_list()
    assert got[:3] == out[:3] and got[3] in (None, "!!!")


def test_clean_up_needs_text_and_a_choice():
    with pytest.raises(StepError):
        run(pl.LazyFrame({"n": [1]}), [{"op": "replace_values", "columns": ["n"], "action": "clean", "clean": "digits"}])
    with pytest.raises(InvalidStepsError):
        parse_steps([{"op": "replace_values", "columns": ["n"], "action": "clean"}])


# --------------------------------------------------------------------------- add column: running total, rank, %

SALES = pl.LazyFrame({"City": ["Pune", "Delhi", "Pune", "Pune", "Delhi"], "Amt": [100.0, 50.0, 100.0, None, 30.0]})


def add(mode, **kw):
    return run(SALES, [{"op": "add_column", "name": "X", "mode": mode, "left": "Amt", **kw}])["X"].to_list()


def test_running_total():
    assert add("running_total") == [100, 150, 250, 250, 280]
    assert add("running_total", within=["City"]) == [100, 50, 200, 200, 80]


def test_rank():
    assert add("rank") == [1, 3, 1, None, 4]                     # ties share a rank; blanks get none
    assert add("rank", descending=False) == [3, 2, 3, None, 1]
    assert add("rank", within=["City"]) == [1, 1, 1, None, 2]


def test_percent_of_total():
    assert add("percent") == [35.71, 17.86, 35.71, None, 10.71]
    assert add("percent", within=["City"]) == [50.0, 62.5, 50.0, None, 37.5]


def test_totals_need_a_number_column():
    with pytest.raises(StepError):
        run(SALES, [{"op": "add_column", "name": "X", "mode": "rank", "left": "City"}])
    with pytest.raises(InvalidStepsError):
        parse_steps([{"op": "add_column", "name": "X", "mode": "rank"}])


# --------------------------------------------------------------------------- add column: if-then, date parts, ranges

from datetime import date as _date  # noqa: E402

PEOPLE = pl.LazyFrame({"City": ["Pune", "Delhi", "Goa", None], "Amt": [50.0, 150000.0, 500.0, None],
                       "D": [_date(2026, 3, 5), _date(2026, 4, 1), _date(2025, 12, 31), None]})


def col(**kw):
    return run(PEOPLE, [{"op": "add_column", "name": "X", **kw}])["X"].to_list()


def test_if_then_first_matching_rule_wins():
    rules = [{"column": "Amt", "operator": "greater_or_equal", "value": 500, "then": "Big"},
             {"column": "City", "operator": "equals", "value": "pune", "then": "Pune, small"}]
    assert col(mode="if_then", rules=rules, otherwise="Other") == ["Pune, small", "Big", "Big", "Other"]
    assert col(mode="if_then", rules=rules) == ["Pune, small", "Big", "Big", None]


def test_if_then_numbers_make_a_number_column():
    rules = [{"column": "Amt", "operator": "greater_than", "value": 1000, "then": "1,500"}]
    out = run(PEOPLE, [{"op": "add_column", "name": "Bonus", "mode": "if_then", "rules": rules, "otherwise": "0"}])
    assert out["Bonus"].dtype == pl.Int64 and out["Bonus"].to_list() == [0, 1500, 0, 0]


@pytest.mark.parametrize("part, values", [
    ("year", [2026, 2026, 2025, None]), ("month", [3, 4, 12, None]), ("month_name", ["March", "April", "December", None]),
    ("quarter", ["Q1", "Q2", "Q4", None]), ("weekday", ["Thursday", "Wednesday", "Wednesday", None]),
    ("day", [5, 1, 31, None]), ("year_month", ["2026-03", "2026-04", "2025-12", None]),
    ("fy", ["FY 2025-26", "FY 2026-27", "FY 2025-26", None]),
])
def test_date_parts(part, values):
    assert col(mode="date_part", left="D", part=part) == values


def test_date_part_needs_a_date_column():
    with pytest.raises(StepError, match="isn't a date"):
        col(mode="date_part", left="City", part="year")


def test_number_ranges():
    assert col(mode="ranges", left="Amt", breaks=[100, 500, 100000]) == [
        "Under 100", "1,00,000 and over", "500 – under 1,00,000", None]  # 500 sits in the higher range
    assert col(mode="ranges", left="Amt", breaks=[100], labels=["Small", "Large"]) == ["Small", "Large", "Large", None]


@pytest.mark.parametrize("bad", [
    {"breaks": [500, 100]}, {"breaks": [100, 100]}, {"breaks": [100], "labels": ["One"]}, {"breaks": []},
])
def test_number_ranges_validation(bad):
    with pytest.raises(InvalidStepsError):
        parse_steps([{"op": "add_column", "name": "X", "mode": "ranges", "left": "Amt", **bad}])


# --------------------------------------------------------------------------- data health check

def test_health_check_finds_common_problems():
    from gridglass.engine.health import check

    lf = pl.LazyFrame({"City": ["Pune", "pune ", "Delhi", "Delhi", None, "Delhi"],
                       "Amt": ["10", "20", "N/A", "30", None, "30"], "Empty": [None] * 6})
    report = check(lf)
    kinds = {it["kind"]: it for it in report["issues"]}
    assert set(kinds) == {"empty_columns", "blank_rows", "duplicates", "variants", "numbers_as_text", "spaces"}
    assert kinds["duplicates"]["count"] == 1 and kinds["duplicates"]["fix"]["step"] == {"op": "remove_duplicates"}
    assert kinds["empty_columns"]["fix"]["step"] == {"op": "remove_columns", "columns": ["Empty"]}
    assert kinds["variants"]["examples"] == [["Pune", "pune "]] and kinds["variants"]["fix"] == {"tool": "change_case"}
    assert kinds["numbers_as_text"]["examples"] == ["N/A"]
    assert kinds["spaces"]["fix"]["step"]["columns"] == ["City"]
    assert [c["blanks"] for c in report["columns"]] == [1, 1, 6]
    for it in report["issues"]:  # every fix step is valid
        if "step" in it["fix"]:
            build(lf, parse_steps([it["fix"]["step"]])).collect()


def test_health_check_on_a_clean_file():
    from gridglass.engine.health import check

    assert check(pl.LazyFrame({"a": [1, 2], "b": ["x", "y"]}))["issues"] == []



def test_health_check_reports_gaps_but_not_blank_rows_twice():
    from gridglass.engine.health import check

    report = check(pl.LazyFrame({"Name": ["Asha", None, None], "Email": ["a@x.in", "b@x.in", None]}))
    kinds = {it["kind"]: it for it in report["issues"]}
    assert kinds["blanks"]["columns"] == ["Name"] and kinds["blanks"]["count"] == 1
    assert kinds["blank_rows"]["count"] == 1 and kinds["blanks"]["fix"] == {"tool": "fill_blanks"}


# --------------------------------------------------------------------------- pivot filters

def test_pivot_filters_rows_before_totalling():
    lf = pl.LazyFrame({"City": ["Pune", "Delhi", "Pune", "Goa"], "Cust": ["A", "B", "A", "C"], "Amt": [10, 20, 30, 40]})
    step = {"op": "pivot", "rows": ["Cust"], "values": [{"func": "sum", "column": "Amt"}], "totals": True,
            "filters": [{"column": "City", "operator": "in_list", "value": ["Pune", "Goa"]},
                        {"column": "Amt", "operator": "greater_than", "value": 15}]}
    assert run(lf, [step]).rows() == [("A", 30), ("C", 40), ("Grand Total", 70)]
    assert run(lf, [{**step, "filter_match": "any"}]).rows() == [("A", 40), ("B", 20), ("C", 40), ("Grand Total", 100)]
    with pytest.raises(StepError):
        run(lf, [{**step, "filters": [{"column": "Nope", "operator": "equals", "value": "x"}]}])


def test_pivot_rounds_sums_and_averages_to_two_places(apply):
    lf = pl.LazyFrame({"C": ["a", "a", "a", "b"], "A": [1, 2, 2, 5], "F": [1.111, 2.222, 0.0, 3.3]})
    out = apply(lf, {"op": "pivot", "rows": ["C"], "totals": True, "values": [
        {"func": "average", "column": "A"}, {"func": "sum", "column": "F"}, {"func": "sum", "column": "A"},
        {"func": "max", "column": "F"}]})
    assert out["Average of A"].to_list() == [1.67, 5.0, 2.5]
    assert out["Sum of F"].to_list() == [3.33, 3.3, 6.63]
    assert out["Sum of A"].dtype == pl.Int64        # whole-number totals stay whole
    assert out["Max of F"].to_list()[0] == 2.222    # min and max are values from the data, kept as they are


# --------------------------------------------------------------------------- found by stress tests (1.14.1)

def test_merge_on_a_true_false_key_with_text_in_the_other_file():
    lf = pl.LazyFrame({"Paid": [True, False], "N": [1, 2]})
    other = pl.LazyFrame({"Flag": [" yes", "FALSE", "maybe"], "Label": ["Paid", "Due", "?"]})
    step = {"op": "merge", "other": OTHER, "keys": [{"left": "Paid", "right": "Flag"}]}
    out = build(lf, parse_steps([step]), resolve=lambda _id: other).collect()
    assert out["Label"].to_list() == ["Paid", "Due"]


def test_unpivot_when_the_table_already_has_attribute_and_value_columns(apply):
    lf = pl.LazyFrame({"Item": ["x"], "Attribute": [1], "Value": [2]})
    out = apply(lf, {"op": "unpivot", "keep": ["Item"]})
    assert out.columns == ["Item", "Attribute", "Value"]
    assert out.rows() == [("x", "Attribute", 1), ("x", "Value", 2)]


def test_pivot_column_value_named_like_a_rows_column(apply):
    lf = pl.LazyFrame({"Customer": ["a", "b"], "Kind": ["Customer", "x"]})
    out = apply(lf, {"op": "pivot", "rows": ["Customer"], "columns": "Kind", "totals": True})
    assert out.columns == ["Customer", "Customer (2)", "x", "Grand Total"]


def test_pivot_grand_total_name_already_taken(apply):
    lf = pl.LazyFrame({"Grand Total": ["a"], "Kind": ["x"]})
    with pytest.raises(StepError, match="already a column called 'Grand Total'"):
        apply(lf, {"op": "pivot", "rows": ["Grand Total"], "columns": "Kind", "totals": True})


def test_number_errors_name_each_column_once(apply):
    lf = pl.LazyFrame({"A": ["x"]})
    with pytest.raises(StepError, match=r"Not numbers: 'A'\.$"):
        apply(lf, {"op": "pivot", "rows": ["A"], "values": [{"func": "sum", "column": "A"}, {"func": "average", "column": "A"}]})


# --------------------------------------------------------------------------- add column: part of a text

TEXTS = pl.LazyFrame({"T": ["INV-2026-001", "Asha Rao (Pune)", None, "no dash", "héllo wörld"], "N": [7, 12345, None, 3, 1]})


@pytest.mark.parametrize("kw, want", [
    ({"func": "first", "count": 3}, ["INV", "Ash", None, "no ", "hél"]),
    ({"func": "last", "count": 3}, ["001", "ne)", None, "ash", "rld"]),
    ({"func": "middle", "start": 5, "count": 4}, ["2026", " Rao", None, "ash", "o wö"]),
    ({"func": "before", "find_text": "-"}, ["INV", None, None, None, None]),
    ({"func": "before", "find_text": "-", "from_end": True}, ["INV-2026", None, None, None, None]),
    ({"func": "after", "find_text": "-"}, ["2026-001", None, None, None, None]),
    ({"func": "after", "find_text": "-", "from_end": True, "if_missing": "all"},
     ["001", "Asha Rao (Pune)", None, "no dash", "héllo wörld"]),
    ({"func": "between", "find_text": "(", "end_text": ")"}, [None, "Pune", None, None, None]),
    ({"func": "word", "count": 2}, [None, "Rao", None, "dash", "wörld"]),
    ({"func": "word", "count": 1, "from_end": True}, ["INV-2026-001", "(Pune)", None, "dash", "wörld"]),
    ({"func": "length"}, [12, 15, None, 7, 11]),
    ({"func": "find", "find_text": "wö"}, [None, None, None, None, 7]),          # counts letters, not bytes
    ({"func": "find", "find_text": "r", "ignore_case": True}, [None, 6, None, None, 9]),
    ({"func": "before", "find_text": ".*"}, [None] * 5),                           # typed text, never a pattern
])
def test_add_column_part_of_a_text(apply, kw, want):
    out = apply(TEXTS, {"op": "add_column", "name": "X", "mode": "text", "left": "T", **kw})
    assert out["X"].to_list() == want


def test_add_column_text_from_a_number_column(apply):
    out = apply(TEXTS, {"op": "add_column", "name": "X", "mode": "text", "left": "N", "func": "pad", "count": 5})
    assert out["X"].to_list() == ["00007", "12345", None, "00003", "00001"]
    out = apply(TEXTS, {"op": "add_column", "name": "X", "mode": "text", "left": "N", "func": "last", "count": 2})
    assert out["X"].to_list() == ["7", "45", None, "3", "1"]


@pytest.mark.parametrize("kw, msg", [
    ({"func": "first"}, "how many"), ({"func": "middle", "count": 2}, "start at"),
    ({"func": "before"}, "text to look for"), ({"func": "between", "find_text": "("}, "ends before"),
    ({}, "what to take"),
])
def test_add_column_text_needs_its_options(kw, msg):
    with pytest.raises(Exception, match=f"(?i){msg}"):
        parse_steps([{"op": "add_column", "name": "X", "mode": "text", "left": "T", **kw}])


# --------------------------------------------------------------------------- pivot: sort and report filter pages (1.17)

PIVOT_SALES = pl.LazyFrame({"Region": ["N", "S", "N", "S", "N", None], "City": ["Delhi", "Chennai", "Agra", "Chennai", "Delhi", "X"],
                      "Kind": ["a", "b", "a", "a", "b", "a"], "Amt": [10, 20, 5, 1, 7, 3]})
SUM = [{"func": "sum", "column": "Amt"}]


def test_pivot_sorts_by_a_value_and_keeps_the_grand_total_last(apply):
    out = apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "values": SUM, "totals": True, "sort_by": "Sum of Amt", "descending": True})
    assert out["City"].to_list() == ["Chennai", "Delhi", "Agra", "X", "Grand Total"]
    out = apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "values": SUM, "sort_by": "rows"})
    assert out["City"].to_list() == ["Agra", "Chennai", "Delhi", "X"]


def test_pivot_with_columns_sorts_by_the_row_total(apply):
    out = apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "columns": "Kind", "values": SUM, "sort_by": "Sum of Amt", "descending": True})
    assert out["City"].to_list() == ["Chennai", "Delhi", "Agra", "X"]


def test_pivot_sort_must_name_a_value(apply):
    with pytest.raises(StepError, match="Sort by one of the Values"):
        apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "values": SUM, "sort_by": "Amt"})


def test_pivot_report_filter_pages(apply):
    out = apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "values": SUM, "totals": True, "pages": "Region",
                        "sort_by": "Sum of Amt", "descending": True})
    assert out.columns == ["Region", "City", "Sum of Amt"]
    assert out.rows() == [("N", "Delhi", 17), ("N", "Agra", 5), ("N", "Grand Total", 22),
                          ("S", "Chennai", 21), ("S", "Grand Total", 21),
                          ("(blank)", "X", 3), ("(blank)", "Grand Total", 3)]  # a total for each page


def test_pivot_pages_keep_grand_total_columns_last(apply):
    lf = PIVOT_SALES.with_columns(pl.when(pl.col("Region") == "S").then(pl.lit("b")).otherwise(pl.lit("a")).alias("Kind"))
    out = apply(lf, {"op": "pivot", "rows": ["City"], "columns": "Kind", "values": SUM, "totals": True, "pages": "Region"})
    assert out.columns == ["Region", "City", "a", "b", "Grand Total"]   # N only has 'a', S only 'b'


@pytest.mark.parametrize("kw, msg", [({"pages": "City"}, "both a page"), ({"pages": "Nope"}, "Nope")])
def test_pivot_pages_errors(apply, kw, msg):
    with pytest.raises(StepError, match=msg):
        apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "values": SUM, **kw})


def test_pivot_pages_limit(apply):
    lf = pl.LazyFrame({"P": [str(i) for i in range(201)], "C": ["x"] * 201})
    with pytest.raises(StepError, match="too many pages"):
        apply(lf, {"op": "pivot", "rows": ["C"], "pages": "P"})


def test_pivot_report_filter_keeps_only_the_chosen_values(apply):
    out = apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "values": SUM, "totals": True,
                              "report_filter": "Region", "report_values": ["N"]})
    assert out.columns == ["City", "Sum of Amt"]                       # no extra column
    assert out.rows() == [("Delhi", 17), ("Agra", 5), ("Grand Total", 22)]
    every = apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "values": SUM, "report_filter": "Region"})
    assert every.height == 4                                           # no values chosen: every row


def test_pivot_report_filter_pages_only_for_the_chosen_values(apply):
    out = apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "values": SUM, "report_filter": "Region",
                              "report_values": ["S", "N"], "pages": "Region"})
    assert out["Region"].unique(maintain_order=True).to_list() == ["N", "S"]


@pytest.mark.parametrize("col, values, want", [
    ("Year", [2026], ["b"]), ("Price", [1.5], ["a"]), ("Day", ["2026-02-01"], ["b"]),
    ("At", ["2026-01-01T10:30:00"], ["a"]), ("Ok", [True], ["a"]),
])
def test_pivot_report_filter_on_numbers_dates_and_true_false(apply, col, values, want):
    import datetime as dt

    lf = pl.LazyFrame({"K": ["a", "b"], "Year": [2025, 2026], "Price": [1.5, 2.0], "Day": [dt.date(2026, 1, 1), dt.date(2026, 2, 1)],
                       "At": [dt.datetime(2026, 1, 1, 10, 30), dt.datetime(2026, 1, 2)], "Ok": [True, False]})
    out = apply(lf, {"op": "pivot", "rows": ["K"], "report_filter": col, "report_values": values})
    assert out["K"].to_list() == want


def test_pivot_report_filter_cant_also_be_a_row(apply):
    with pytest.raises(StepError, match="report filter"):
        apply(PIVOT_SALES, {"op": "pivot", "rows": ["City"], "report_filter": "City"})
