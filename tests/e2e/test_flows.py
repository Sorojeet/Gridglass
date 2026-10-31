"""Gridglass end to end, the way people use it: on a phone, tapping through real screens against a real server."""
from __future__ import annotations

import json
import re
from pathlib import Path

import polars as pl
import pytest
import xlsxwriter
from playwright.sync_api import expect

ALL_OPS = [
    "remove_duplicates", "trim", "change_case", "replace_values", "fill_blanks", "remove_blank_rows",
    "filter_rows", "sort_rows", "remove_columns", "keep_columns", "rename_columns", "keep_rows",
    "change_type", "split_column", "add_column", "merge", "pivot", "unpivot", "convert", "split_pages",
]
SAMPLE_ROWS = 45  # the built-in sample: 40 orders + 5 exact duplicates


# ----------------------------------------------------------------------------- helpers

def download(page, fmt: str) -> Path:
    page.select_option("#fmt", fmt)
    with page.expect_download() as dl:
        page.click('[data-action="download"]')
    return Path(dl.value.path())


def result_json(page) -> list[dict]:
    return json.loads(download(page, "json").read_text())


def apply(page):
    expect(page.locator("#apply")).to_be_enabled()
    page.click("#apply")
    expect(page.locator(".done h1")).to_be_visible()


# ----------------------------------------------------------------------------- home

def test_home_lists_every_tool_and_searches(phone):
    page = phone.open("/")
    expect(page.locator(".tool-card")).to_have_count(len(ALL_OPS))
    page.fill("#q", "duplicates")
    expect(page.locator(".tool-card")).to_have_count(1)
    page.fill("#q", "zzz")
    expect(page.locator(".empty")).to_contain_text("No tool matches")
    page.fill("#q", "")
    page.click('[data-cat="summarize"]')
    expect(page.locator(".tool-card")).to_have_count(2)
    expect(page.locator('[data-cat="summarize"]')).to_have_attribute("aria-pressed", "true")


@pytest.mark.parametrize("device", ["iPhone SE", "iPhone 14", "Pixel 7", "Desktop Chrome"])
def test_no_sideways_scrolling(make_phone, device):
    phone = make_phone(device)
    for path in ("/", "/#/tool/filter_rows"):
        page = phone.open(path)
        page.wait_for_selector(".topbar")
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 0, f"{device} {path} scrolls sideways by {overflow}px"


def test_desktop_home_uses_wide_grid(make_phone):
    page = make_phone("Desktop Chrome").open("/")  # 1280 px wide
    cols = page.evaluate("getComputedStyle(document.querySelector('.tool-grid')).gridTemplateColumns.split(' ').length")
    assert cols == 4
    assert page.locator("main").bounding_box()["width"] > 1100


def _box(page, sel):
    return page.locator(sel).first.bounding_box()


def test_desktop_options_side_by_side(make_phone):
    phone = make_phone("Desktop Chrome")
    page = phone.upload_sample("filter_rows")
    form, preview, apply_btn = _box(page, "#opts"), _box(page, ".preview"), _box(page, "#apply")
    assert preview["x"] > form["x"] + form["width"] - 1          # preview sits to the right of the options
    assert abs(preview["y"] - _box(page, ".file-chip")["y"]) < 40  # and starts at the top
    assert apply_btn["x"] < preview["x"]                          # apply button stays with the options
    assert preview["width"] > 700
    page.select_option("#c0col", "City")
    page.fill("#c0v", "Pune")
    page.wait_for_selector("#pv-badge:not(:empty)")
    rows = page.locator("#pv tbody tr").count()
    assert rows > 0
    apply(page)
    done, nxt = _box(page, ".done"), _box(page, ".next")
    assert nxt["x"] > done["x"] + done["width"] - 1                # result: next steps on the right


def test_desktop_preview_shows_more_rows(make_phone):
    phone = make_phone("Desktop Chrome")
    page = phone.upload_sample("sort_rows")
    expect(page.locator("#pv tbody tr")).to_have_count(45)       # whole sample (phones show 45 too; cap is 50 vs 200)


def test_desktop_upload_side_by_side(make_phone):
    page = make_phone("Desktop Chrome").open("/#/tool/trim")
    intro, drop = _box(page, ".intro"), _box(page, ".dropzone")
    assert drop["x"] > intro["x"] + intro["width"] - 1


def test_phone_layout_unchanged(phone):
    page = phone.upload_sample("filter_rows")
    form, preview = _box(page, "#opts"), _box(page, ".preview")
    assert preview["y"] > form["y"] + form["height"] - 1          # stacked: preview below the options


# ----------------------------------------------------------------------------- every tool

@pytest.mark.parametrize("op", ALL_OPS)
def test_every_tool_opens_without_errors(phone, op):
    """With the sample file, each tool shows a preview and either a ready button or a friendly hint — never a red error."""
    page = phone.upload_sample(op)
    page.wait_for_timeout(500)  # let the debounced draft preview land
    expect(page.locator(".form-error")).to_have_count(0)
    if op in ("convert", "split_pages"):
        expect(page.locator('[data-action="download"]')).to_be_enabled()
        return
    ready = page.locator("#apply").is_enabled()
    hint = page.locator("#pv-note.needs").count() == 1
    assert ready or hint, f"{op}: neither ready nor showing a hint"


@pytest.mark.parametrize("op", [op for op in ALL_OPS if op not in ("convert", "split_pages")])
def test_every_form_control_is_labelled(phone, op):
    page = phone.upload_sample(op)
    unlabelled = page.evaluate("""() => [...document.querySelectorAll('#opts input, #opts select, #opts button')]
        .filter(el => !(el.labels?.length || el.getAttribute('aria-label') || el.textContent.trim()))
        .map(el => el.outerHTML.slice(0, 80))""")
    assert unlabelled == []


# ----------------------------------------------------------------------------- tool outcomes

def test_remove_duplicates_and_download_excel(phone):
    page = phone.upload_sample("remove_duplicates")
    expect(page.locator("#pv-badge")).to_have_text("5 fewer rows")
    apply(page)
    expect(page.locator(".done h1")).to_have_text("5 duplicate rows removed")
    expect(page.locator(".done p")).to_have_text("45 rows → 40 rows")
    xlsx = download(page, "xlsx")
    df = pl.read_excel(xlsx, engine="calamine")
    assert df.height == 40 and df.columns[0] == "Order ID"


def test_duplicates_by_chosen_columns(phone):
    page = phone.upload_sample("remove_duplicates")
    page.click('[data-seg="columns__mode"][data-val="some"]')
    expect(page.locator("#pv-note")).to_contain_text("Choose at least one column")
    expect(page.locator("#apply")).to_be_disabled()
    page.click('[data-col="City"]')
    expect(page.locator("#pv-badge")).to_have_text("40 fewer rows")  # 5 cities left
    apply(page)
    assert len(result_json(page)) == 5


def test_trim_and_change_case_chain(phone):
    page = phone.upload_sample("trim")
    apply(page)
    page.click('.next a[href="#/tool/change_case"]')  # chain without uploading again (a related suggestion)
    expect(page.locator(".file-chip")).to_contain_text("1 step applied")
    page.goto(phone.base + "/#/tool/change_case")
    page.wait_for_selector("#opts")
    page.click('[data-col="City"]')
    page.click('[data-seg="case"][data-val="upper"]')
    apply(page)
    rows = result_json(page)
    assert all(r["City"] == r["City"].upper() for r in rows)
    assert all(r["Customer"] == r["Customer"].strip() for r in rows if r["Customer"])
    assert not any("  " in (r["Customer"] or "") for r in rows)


def test_filter_with_two_conditions_then_undo(phone):
    page = phone.upload_sample("filter_rows")
    expect(page.locator("#pv-note")).to_contain_text("Type a value")
    expect(page.locator("#apply")).to_be_disabled()
    page.select_option("#c0col", "City")
    page.fill("#c0v", "pune")  # case-insensitive
    page.click('[data-add="conditions"]')
    page.select_option("#c1col", "Amount")
    page.select_option("#c1op", "greater_than")
    page.fill("#c1v", "₹300")
    apply(page)
    rows = result_json(page)
    assert rows and all(r["City"] == "Pune" and r["Amount"] > 300 for r in rows)
    page.click('[data-undo="0"]')
    expect(page.locator(".step-list li.empty")).to_be_visible()
    expect(page.locator(".done p")).to_contain_text("45 rows")


def test_replace_and_fill_blanks(phone):
    page = phone.upload_sample("fill_blanks")
    page.click('[data-seg="columns__mode"][data-val="some"]')
    page.click('[data-col="Customer"]')
    page.fill("#f-value", "Unknown")
    apply(page)
    page.goto(phone.base + "/#/tool/replace_values")
    page.wait_for_selector("#opts")
    page.click('[data-col="City"]')
    page.fill("#f-find", "Bengaluru")
    page.fill("#f-replace", "Bangalore")
    apply(page)
    rows = result_json(page)
    assert all(r["Customer"] for r in rows)
    assert {"Bangalore"} <= {r["City"] for r in rows} and "Bengaluru" not in {r["City"] for r in rows}


def test_split_rename_and_keep_columns(phone):
    page = phone.upload_sample("split_column")
    page.select_option("#f-column", "Customer")
    apply(page)
    page.goto(phone.base + "/#/tool/rename_columns")
    page.wait_for_selector("#opts")
    expect(page.locator("#pv-note")).to_contain_text("Type a new name")
    page.locator('input[data-rename="Customer 1"]').fill("First name")
    apply(page)
    page.goto(phone.base + "/#/tool/keep_columns")
    page.wait_for_selector("#opts")
    page.click('[data-col="City"]')
    page.click('[data-col="First name"]')
    expect(page.locator('[data-col="First name"] b')).to_have_text("2")  # order badges
    apply(page)
    rows = result_json(page)
    assert list(rows[0]) == ["City", "First name"]


def test_add_column_math(phone):
    page = phone.upload_sample("add_column")
    expect(page.locator("#pv-note")).to_contain_text("Give the new column a name")
    page.fill("#f-name", "With GST")
    page.click('[data-seg="mode"][data-val="math"]')
    page.select_option("#f-left", "Amount")
    page.click('[data-seg="operator"][data-val="*"]')
    page.fill("#f-right_value", "1.18")
    apply(page)
    rows = result_json(page)
    assert all(abs(r["With GST"] - r["Amount"] * 1.18) < 1e-6 for r in rows)


def test_change_type_and_sort(phone):
    page = phone.upload_sample("change_type")
    page.select_option("#t0c", "Order date")
    page.select_option("#t0t", "date")
    expect(page.locator("#f-date_format")).to_be_visible()
    apply(page)
    page.goto(phone.base + "/#/tool/sort_rows")
    page.wait_for_selector("#opts")
    page.select_option("#s0c", "Amount")
    page.select_option("#s0o", "desc")
    apply(page)
    amounts = [r["Amount"] for r in result_json(page)]
    assert amounts == sorted(amounts, reverse=True)


def test_pivot_works_like_group_by(phone):
    page = phone.upload_sample("pivot")
    page.click('[data-col-none="rows"]')
    page.click('[data-field="rows"] [data-col="City"]')
    expect(page.locator("#f-pcol")).to_have_value("")          # no Columns field: a plain group-by
    expect(page.locator("#a0c")).to_have_value("Amount")       # sum of the first number column by default
    apply(page)
    expect(page.locator(".done h1")).to_have_text("Pivot table ready — 6 rows")  # 5 cities + Grand Total
    rows = result_json(page)
    assert list(rows[0]) == ["City", "Sum of Amount"]
    assert rows[-1]["City"] == "Grand Total"
    assert abs(rows[-1]["Sum of Amount"] - sum(r["Sum of Amount"] for r in rows[:-1])) < 1e-6


def test_pivot_with_columns_and_two_values(phone):
    page = phone.upload_sample("pivot")
    page.click('[data-col-none="rows"]')
    page.click('[data-field="rows"] [data-col="City"]')
    page.select_option("#f-pcol", "Order date")
    page.click('[data-add="aggs"]')
    page.select_option("#a1f", "count_rows")
    page.locator("#opts .toggle").click()                       # Grand Total off
    apply(page)
    rows = result_json(page)
    cols = list(rows[0])
    assert cols[0] == "City" and any(c.startswith("Sum of Amount · ") for c in cols)
    assert any(c.startswith("Count · ") for c in cols) and not any("Grand Total" in c for c in cols)
    assert len(rows) == 5


def test_pivot_hint_when_columns_also_in_rows(phone):
    page = phone.upload_sample("pivot")
    page.select_option("#f-pcol", "Customer")                   # Customer is already the default Rows field
    expect(page.locator("#pv-note")).to_contain_text("isn’t already in Rows")
    expect(page.locator("#apply")).to_be_disabled()


def test_keep_rows_and_unpivot(phone):
    page = phone.upload_sample("keep_rows")
    page.fill("#f-count", "3")
    apply(page)
    page.goto(phone.base + "/#/tool/unpivot")
    page.wait_for_selector("#opts")
    page.click('[data-seg="columns__mode"][data-val="some"]')
    page.click('[data-field="columns"] [data-col="City"]')
    page.click('[data-field="columns"] [data-col="Amount"]')
    apply(page)
    rows = result_json(page)
    assert len(rows) == 6 and {"Attribute", "Value"} <= set(rows[0])


@pytest.mark.parametrize("fmt, magic", [("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK"), ("json", b"["), ("pdf", b"%PDF")])
def test_convert_to_every_format(phone, fmt, magic):
    page = phone.upload_sample("convert")
    assert download(page, fmt).read_bytes().startswith(magic)


# ----------------------------------------------------------------------------- files & errors

def test_excel_sheets(phone, tmp_path):
    book = tmp_path / "book.xlsx"
    with xlsxwriter.Workbook(book) as wb:
        wb.add_worksheet("Jan").write_column(0, 0, ["Sales", 1, 2])
        wb.add_worksheet("Feb").write_column(0, 0, ["Sales", 1, 2, 3, 4])
    page = phone.open("/#/tool/sort_rows")
    page.set_input_files("#file", str(book))
    page.wait_for_selector("#pv table")
    expect(page.locator(".file-chip")).to_contain_text("2 rows")
    page.select_option("#sheet", "Feb")
    expect(page.locator(".file-chip")).to_contain_text("4 rows")


def test_bad_file_shows_friendly_error(phone, tmp_path):
    fake = tmp_path / "notes.pdf"
    fake.write_bytes(b"%PDF-1.7 not a spreadsheet")
    page = phone.open("/#/tool/trim")
    page.set_input_files("#file", str(fake))
    expect(page.locator("#toast")).to_contain_text("can't open .pdf")
    expect(page.locator("#progress")).to_be_hidden()
    expect(page.locator("h1")).to_have_text("Trim spaces")  # still on the upload screen


def test_size_limit_checked_before_upload(phone, tmp_path):
    phone.page.route("**/api/v1/config", lambda r: r.fulfill(json={"max_upload_mb": 0.001, "retention_minutes": 60}))
    big = tmp_path / "big.csv"
    big.write_text("A\n" + "1\n" * 2000)
    page = phone.open("/#/tool/trim")
    page.wait_for_timeout(200)
    page.set_input_files("#file", str(big))
    expect(page.locator("#toast")).to_contain_text("The limit is")


def test_file_survives_reload_and_start_over_deletes_it(phone):
    page = phone.upload_sample("trim")
    file_id = page.evaluate("sessionStorage.getItem('gg.file')")
    page.reload()
    expect(page.locator(".file-chip")).to_contain_text("sample-orders.csv")
    page.goto(phone.base + "/")
    page.click('[data-action="startover"]')
    expect(page.locator(".working")).to_have_count(0)
    page.wait_for_timeout(300)
    assert page.request.get(f"{phone.base}/api/v1/files/{file_id}").status == 404


def test_expired_file_sends_you_back_to_upload(phone):
    page = phone.upload_sample("trim")
    file_id = page.evaluate("sessionStorage.getItem('gg.file')")
    page.request.delete(f"{phone.base}/api/v1/files/{file_id}")  # as if the hour ran out
    page.goto(phone.base + "/#/tool/sort_rows")
    expect(page.locator("#toast")).to_contain_text("expired")
    expect(page.locator("label[for=file]")).to_be_visible()


# ----------------------------------------------------------------------------- theme & keyboard

def test_dark_mode_follows_phone_then_remembers_choice(make_phone):
    phone = make_phone(color_scheme="dark")
    page = phone.open("/")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.click('[data-action="theme"]')
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    page.reload()
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    expect(page.locator('[data-action="theme"]')).to_have_attribute("aria-label", "Switch to dark mode")


def test_keyboard_only(phone):
    page = phone.open("/")
    page.keyboard.press("Tab")  # skip link
    expect(page.locator(".skip")).to_be_focused()
    page.focus('[data-action="theme"]')
    page.keyboard.press("Enter")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.focus('a.tool-card[href="#/tool/trim"]')
    page.keyboard.press("Enter")
    expect(page.locator("h1")).to_have_text("Trim spaces")


def test_service_worker_registers(phone):
    page = phone.open("/")
    page.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller !== undefined")
    ready = page.evaluate("navigator.serviceWorker.ready.then(r => !!r.active)")
    assert ready


def test_fonts_are_self_hosted_and_nothing_external_loads(make_phone):
    phone = make_phone()
    external = []
    phone.page.on("request", lambda r: not r.url.startswith(phone.base) and not r.url.startswith("blob:")
                  and not r.url.startswith("data:") and external.append(r.url))
    page = phone.upload_sample("trim")
    page.evaluate("document.fonts.ready")
    assert page.evaluate("document.fonts.check('700 16px Manrope')")
    assert page.evaluate("getComputedStyle(document.body).fontFamily").startswith("Manrope")
    assert external == []



# ----------------------------------------------------------------------------- filter value dropdown

def test_filter_value_dropdown_pick_and_type(phone):
    page = phone.upload_sample("filter_rows")
    page.select_option("#c0col", "City")
    page.click("#c0v")
    options = page.locator("#c0list [role=option]")
    expect(options).to_have_count(5)                            # the 5 cities, with counts
    expect(options.first).to_contain_text("Bengaluru")          # sorted A→Z, like Excel
    page.locator("#c0list [role=option]", has_text="Pune").click()
    expect(page.locator("#c0v")).to_have_value("Pune")
    expect(page.locator("#c0list")).to_be_hidden()
    expect(page.locator("#pv-badge")).to_contain_text("fewer rows")

    page.fill("#c0v", "del")                                    # typing narrows the list
    expect(options).to_have_count(1)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page.locator("#c0v")).to_have_value("Delhi")
    apply(page)
    assert {r["City"] for r in result_json(page)} == {"Delhi"}


def test_filter_dropdown_builds_a_list(phone):
    page = phone.upload_sample("filter_rows")
    page.select_option("#c0col", "City")
    page.select_option("#c0op", "in_list")
    page.click("#c0v")
    page.locator("#c0list [role=option]", has_text="Pune").click()
    page.locator("#c0list [role=option]", has_text="Chennai").click()
    expect(page.locator("#c0v")).to_have_value("Pune, Chennai, ")
    expect(page.locator("#c0list [role=option]")).to_have_count(3)   # already-picked values drop out
    apply(page)
    assert {r["City"] for r in result_json(page)} == {"Pune", "Chennai"}


def test_filter_typed_value_still_works(phone):
    page = phone.upload_sample("filter_rows")
    page.select_option("#c0col", "Amount")
    page.select_option("#c0op", "greater_than")
    page.fill("#c0v", "700")                                    # a value that isn't in the list
    page.keyboard.press("Escape")
    apply(page)
    assert all(r["Amount"] > 700 for r in result_json(page))


# ----------------------------------------------------------------------------- show all rows

def _numbers_csv(tmp_path, n):
    f = tmp_path / f"n{n}.csv"
    f.write_text("n,label\n" + "".join(f"{i},row {i}\n" for i in range(n)))
    return str(f)


def test_show_all_rows_in_pages_of_1000(phone, tmp_path):
    page = phone.open("/#/tool/sort_rows")
    page.set_input_files("#file", _numbers_csv(tmp_path, 2500))
    page.wait_for_selector("#pv table")
    rows = page.locator("#pv tbody tr")
    expect(rows).to_have_count(50)                              # quick preview on a phone
    page.click('[data-page="all"]')
    expect(rows).to_have_count(1000)
    expect(page.locator(".pager-text")).to_have_text("Rows 1–1,000 of 2,500 · page 1 of 3")
    expect(page.locator('[data-page="prev"]')).to_be_disabled()
    page.click('[data-page="next"]')
    expect(page.locator("#pv tbody tr").first.locator("td").first).to_have_text("1000")
    page.click('[data-page="next"]')
    expect(rows).to_have_count(500)
    expect(page.locator('[data-page="next"]')).to_be_disabled()
    page.select_option("#s0o", "desc")                         # changing options goes back to page 1
    expect(page.locator(".pager-text")).to_contain_text("Rows 1–1,000")
    expect(page.locator("#pv tbody tr").first.locator("td").first).to_have_text("2499")
    page.click('[data-page="less"]')
    expect(rows).to_have_count(50)


def test_big_files_offer_download_instead(phone, tmp_path):
    page = phone.open("/#/tool/sort_rows")
    page.set_input_files("#file", _numbers_csv(tmp_path, 12000))
    page.wait_for_selector("#pv table")
    expect(page.locator('[data-page="all"]')).to_have_count(0)
    expect(page.locator("#pv-note")).to_contain_text("Download the file to see every row")


# ----------------------------------------------------------------------------- back to the editor

def test_edit_options_after_apply(phone):
    page = phone.upload_sample("filter_rows")
    page.select_option("#c0col", "City")
    page.fill("#c0v", "Pune")
    apply(page)
    expect(page.locator(".step-list li")).to_have_count(1)
    page.click('.done a[href="#/edit/0"]')
    expect(page.locator("#c0v")).to_have_value("Pune")          # options come back as they were
    expect(page.locator(".file-chip")).to_contain_text("editing step 1 of 1")
    expect(page.locator(".file-chip")).to_contain_text("45 rows")  # the data as it was before this step
    page.fill("#c0v", "Delhi")
    apply(page)
    expect(page.locator(".step-list li")).to_have_count(1)      # replaced, not added twice
    assert {r["City"] for r in result_json(page)} == {"Delhi"}


def test_edit_from_top_bar_keeps_earlier_steps(phone):
    page = phone.upload_sample("trim")
    apply(page)
    page.goto(phone.base + "/#/tool/remove_duplicates")
    page.wait_for_selector("#opts")
    apply(page)
    page.click('.topbar a[aria-label="Back to the editor"]')
    expect(page.locator("h1, .topbar-title").first).to_contain_text("Remove duplicates")
    expect(page.locator(".file-chip")).to_contain_text("editing step 2 of 2")   # trim is still there
    apply(page)
    expect(page.locator(".step-list li")).to_have_count(2)



# ----------------------------------------------------------------------------- merge (VLOOKUP + joins)

def _merge_with_sample(phone):
    page = phone.upload_sample("merge")
    expect(page.locator("#pv-note")).to_contain_text("Add the second file")
    page.click('[data-action="sample2"]')
    expect(page.locator(".file-chip.second")).to_contain_text("city-regions.csv")
    expect(page.locator(".file-chip.second")).to_contain_text("6 rows")
    expect(page.locator("#k0l")).to_have_value("City")          # same-named column matched automatically
    expect(page.locator("#k0r")).to_have_value("City")
    return page


def test_merge_like_vlookup(phone):
    page = _merge_with_sample(phone)
    expect(page.locator("#pv thead")).to_contain_text("Region")
    apply(page)
    expect(page.locator(".done h1")).to_have_text("Merged — 45 rows")
    rows = result_json(page)
    pune = next(r for r in rows if r["City"] == "Pune")
    assert pune["Region"] == "West" and pune["State"] == "Maharashtra"


@pytest.mark.parametrize("how, rows", [("inner", 45), ("full", 46), ("right", 46), ("anti", 0), ("semi", 45)])
def test_merge_join_types(phone, how, rows):
    page = _merge_with_sample(phone)
    page.select_option("#f-how", how)
    expect(page.locator("#apply")).to_be_enabled()
    apply(page)
    expect(page.locator(".done p")).to_contain_text(f"{rows} rows")


def test_merge_choose_columns_and_own_file(phone, tmp_path):
    other = tmp_path / "towns.csv"
    other.write_text("Town,Zone,Code\nPune,W,1\nDelhi,N,2\n")
    page = phone.upload_sample("merge")
    page.set_input_files("#file2", str(other))
    expect(page.locator(".file-chip.second")).to_contain_text("towns.csv")
    page.select_option("#k0l", "City")
    page.select_option("#k0r", "Town")
    page.click('[data-seg="columns__mode"][data-val="some"]')
    page.click('[data-field="columns"] [data-col="Zone"]')
    apply(page)
    rows = result_json(page)
    assert "Zone" in rows[0] and "Code" not in rows[0] and "Town" not in rows[0]
    assert {r["Zone"] for r in rows if r["City"] == "Delhi"} == {"N"}


def test_merge_change_second_file_and_edit(phone):
    page = _merge_with_sample(phone)
    page.click('[data-action="other-change"]')
    expect(page.locator("#drop2")).to_be_visible()
    page.click('[data-action="sample2"]')
    expect(page.locator(".file-chip.second")).to_be_visible()
    apply(page)
    page.click('.done a[href^="#/edit/"]')
    expect(page.locator(".file-chip.second")).to_contain_text("city-regions.csv")  # second file comes back
    page.select_option("#f-how", "inner")
    apply(page)
    expect(page.locator(".step-list li")).to_have_count(1)


# ----------------------------------------------------------------------------- split into pages (its own tool)

def test_split_pages_tool_spreadsheet(phone):
    import fastexcel

    page = phone.upload_sample("split_pages")
    expect(page.locator("#split")).to_have_value("Customer")            # first text column with few values
    page.select_option("#split", "City")
    expect(page.locator("#page-list li")).to_have_count(5)
    expect(page.locator("#page-list li").first).to_contain_text("Bengaluru")
    expect(page.locator("#page-list li").first).to_contain_text("9 rows")
    expect(page.locator('[data-action="download"]')).to_contain_text("Download 5 sheets")
    with page.expect_download() as dl:
        page.click('[data-action="download"]')
    assert fastexcel.read_excel(dl.value.path()).sheet_names == ["Bengaluru", "Chennai", "Delhi", "Mumbai", "Pune"]


def test_split_pages_tool_pdf_and_blanks(phone):
    page = phone.upload_sample("split_pages")
    expect(page.locator("#page-list li", has_text="(blank)")).to_have_count(1)  # blank customers get their own page
    page.select_option("#split", "City")
    page.click('[data-seg="splitfmt"][data-val="pdf"]')
    expect(page.locator('[data-action="download"]')).to_contain_text("Download 5 pages")
    with page.expect_download() as dl:
        page.click('[data-action="download"]')
    assert len(re.findall(rb"/Type\s*/Page[^s]", Path(dl.value.path()).read_bytes())) == 5


def test_split_is_not_on_the_download_card(phone):
    page = phone.upload_sample("trim")
    apply(page)
    expect(page.locator("#split")).to_have_count(0)
    page.goto(phone.base + "/#/tool/convert")
    page.wait_for_selector("#pv table")
    expect(page.locator("#split")).to_have_count(0)


def test_no_brand_names_in_the_app(phone):
    page = phone.open("/")
    seen = page.evaluate("document.body.innerText")
    for tool in ALL_OPS:
        page.goto(f"{phone.base}/#/tool/{tool}")
        page.wait_for_selector("h1")
        seen += page.evaluate("document.body.innerText")
    for word in ("Excel", "VLOOKUP", "XLOOKUP", "Power Query", "Report Filter"):
        assert word.lower() not in seen.lower(), word


# ----------------------------------------------------------------------------- pivot charts

def _pivot_by_city(phone, device=None):
    page = phone.upload_sample("pivot")
    page.click('[data-col-none="rows"]')
    page.click('[data-field="rows"] [data-col="City"]')
    page.wait_for_selector("#pv-badge:not(:empty)")
    return page


def test_pivot_chart_types(phone):
    page = _pivot_by_city(phone)
    page.click("#tab-chart")
    expect(page.locator("#tab-chart")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#pv")).to_be_hidden()
    expect(page.locator("#chart svg rect.grow-y")).to_have_count(5)    # 5 cities, Grand Total left out
    page.click('[data-seg="charttype"][data-val="bar"]')
    expect(page.locator("#chart svg rect.grow-x")).to_have_count(5)
    page.click('[data-seg="charttype"][data-val="line"]')
    expect(page.locator("#chart svg polyline")).to_have_count(1)
    page.click('[data-seg="charttype"][data-val="pie"]')
    expect(page.locator("#chart svg path")).to_have_count(5)
    page.click("#tab-table")
    expect(page.locator("#pv")).to_be_visible()


def test_pivot_chart_downloads(phone):
    page = _pivot_by_city(phone)
    page.click("#tab-chart")
    with page.expect_download() as dl:
        page.click('[data-chart-save="png"]')
    assert dl.value.suggested_filename.endswith("-column-chart.png")
    assert Path(dl.value.path()).read_bytes().startswith(b"\x89PNG")
    with page.expect_download() as dl:
        page.click('[data-chart-save="svg"]')
    assert b"<svg" in Path(dl.value.path()).read_bytes()[:200]


def test_chart_with_columns_has_one_series_per_column(phone):
    page = _pivot_by_city(phone)
    page.select_option("#f-pcol", "Customer")
    page.click("#tab-chart")
    expect(page.locator("#chart svg rect.grow-y")).to_have_count(30)  # 5 cities x 6 customers; totals left out


def test_make_a_chart_from_result(phone):
    page = _pivot_by_city(phone)
    apply(page)
    page.click('[data-action="chart"]')
    expect(page.locator("#tab-chart")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#chart svg rect.grow-y")).to_have_count(5)


def test_chart_follows_theme(make_phone):
    phone = make_phone(color_scheme="light")
    page = _pivot_by_city(phone)
    page.click("#tab-chart")
    light = page.locator("#chart svg rect.grow-y").first.get_attribute("fill")
    page.click('[data-action="theme"]')
    expect(page.locator("#chart svg rect.grow-y").first).not_to_have_attribute("fill", light)


# ----------------------------------------------------------------------------- motion

def test_animations_play_and_respect_reduced_motion(make_phone):
    page = make_phone().open("/")
    assert page.evaluate("getComputedStyle(document.querySelector('.tool-card')).animationName") == "card-in"
    calm = make_phone(reduced_motion="reduce").open("/")
    assert calm.evaluate("getComputedStyle(document.querySelector('.tool-card')).animationName") == "none"


def test_dropdown_stays_above_preview(phone):
    page = phone.upload_sample("filter_rows")
    page.select_option("#c0col", "City")
    page.click("#c0v")
    last = page.locator("#c0list [role=option]").last
    expect(last).to_be_visible()
    box = last.bounding_box()
    on_top = page.evaluate("([x, y]) => document.elementFromPoint(x, y)?.closest('[role=option]') !== null",
                           [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2])
    assert on_top



# ----------------------------------------------------------------------------- edit any applied step

def test_edit_an_earlier_step_and_later_steps_rerun(phone):
    page = phone.upload_sample("filter_rows")
    page.select_option("#c0col", "City")
    page.fill("#c0v", "Pune")
    apply(page)
    page.goto(phone.base + "/#/tool/sort_rows")
    page.wait_for_selector("#opts")
    page.select_option("#s0c", "Amount")
    apply(page)
    expect(page.locator(".step-list li")).to_have_count(2)
    page.click('.step-list a[href="#/edit/0"]')                  # edit the first step, the filter
    expect(page.locator(".topbar-title")).to_have_text("Edit: Filter rows")
    expect(page.locator("#c0v")).to_have_value("Pune")
    expect(page.locator("#apply")).to_have_text("Save changes")
    page.fill("#c0v", "Delhi")
    page.click("#apply")
    expect(page.locator(".done h1")).to_have_text("Changes saved")
    expect(page.locator(".step-list li")).to_have_count(2)      # replaced in place, sort still applied
    rows = result_json(page)
    assert {r["City"] for r in rows} == {"Delhi"}
    assert [r["Amount"] for r in rows] == sorted(r["Amount"] for r in rows)


def test_every_tool_can_be_edited_with_its_options(phone):
    """Each saved step reopens with the options it was saved with."""
    page = phone.upload_sample("split_column")
    page.select_option("#f-column", "Customer")
    page.fill("#f-parts", "3")
    apply(page)
    page.goto(phone.base + "/#/tool/change_type")
    page.wait_for_selector("#opts")
    page.select_option("#t0c", "Order date")
    page.select_option("#t0t", "date")
    apply(page)
    page.goto(phone.base + "/#/tool/pivot")
    page.wait_for_selector("#opts")
    page.click('[data-col-none="rows"]')
    page.click('[data-field="rows"] [data-col="City"]')
    page.click('[data-add="aggs"]')
    page.select_option("#a1f", "count_rows")
    apply(page)
    page.click('.step-list a[href="#/edit/0"]')
    expect(page.locator("#f-column")).to_have_value("Customer")
    expect(page.locator("#f-parts")).to_have_value("3")
    page.go_back()
    page.click('.step-list a[href="#/edit/1"]')
    expect(page.locator("#t0c")).to_have_value("Order date")
    expect(page.locator("#t0t")).to_have_value("date")
    page.go_back()
    page.click('.step-list a[href="#/edit/2"]')
    expect(page.locator('[data-field="rows"] [data-col="City"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#a0f")).to_have_value("sum")
    expect(page.locator("#a1f")).to_have_value("count_rows")


def test_edit_that_breaks_a_later_step_explains_why(phone):
    page = phone.upload_sample("split_column")
    page.select_option("#f-column", "Customer")
    apply(page)
    page.goto(phone.base + "/#/tool/rename_columns")
    page.wait_for_selector("#opts")
    page.locator('input[data-rename="Customer 1"]').fill("First")
    apply(page)
    page.click('.step-list a[href="#/edit/0"]')
    page.select_option("#f-column", "Email")                    # "Customer 1" won't exist any more
    page.click("#apply")
    expect(page.locator("#toast")).to_contain_text("doesn't fit step 2 (Rename columns)")
    expect(page.locator("#apply")).to_be_visible()               # still in the editor, nothing lost


# ----------------------------------------------------------------------------- related suggestions

@pytest.mark.parametrize("tool, expected", [
    ("remove_columns", ["Choose & reorder columns", "Rename columns", "Add column", "Split column"]),
    ("filter_rows", ["Sort rows", "Pivot table"]),
])
def test_suggestions_follow_the_last_tool(phone, tool, expected):
    page = phone.upload_sample(tool)
    if tool == "remove_columns":
        page.click('[data-col="Email"]')
    else:
        page.select_option("#c0col", "City")
        page.fill("#c0v", "Pune")
    apply(page)
    chips = page.locator(".next .chip").all_inner_texts()
    assert chips[: len(expected)] == expected


# ----------------------------------------------------------------------------- back to the result

def test_back_returns_to_the_result(phone):
    page = phone.upload_sample("trim")
    apply(page)
    expect(page).to_have_url(re.compile(r"#/result$"))
    page.click('.next .chip:has-text("All tools")')
    expect(page.locator(".tool-card").first).to_be_visible()
    page.go_back()                                               # browser / phone back button
    expect(page.locator(".done h1")).to_be_visible()
    page.click('.next .chip:has-text("All tools")')
    page.click('.working a[href="#/result"]')                    # or the link on the home screen
    expect(page.locator(".done h1")).to_be_visible()


def test_result_page_survives_reload(phone):
    page = phone.upload_sample("remove_duplicates")
    apply(page)
    page.reload()
    expect(page.locator(".done p")).to_contain_text("40 rows")
    expect(page.locator(".step-list li")).to_have_count(1)


# ----------------------------------------------------------------------------- sticky button stays on top

def test_bottom_button_stays_above_options_while_typing(phone):
    page = phone.upload_sample("filter_rows")
    page.select_option("#c0col", "City")
    page.click("#c0v")                                           # focus inside the form (lifts it)
    page.keyboard.press("Escape")                                # close the value list
    page.click('[data-add="conditions"]')
    page.click('[data-add="conditions"]')
    page.locator("#c2v").focus()
    page.evaluate("window.scrollBy(0, -120)")                   # scroll up a little, form under the bar
    box = page.locator(".action-bar").bounding_box()
    hit = page.evaluate("([x, y]) => !!document.elementFromPoint(x, y)?.closest('.action-bar')",
                        [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2])
    assert hit, "the options form covered the bottom button"
