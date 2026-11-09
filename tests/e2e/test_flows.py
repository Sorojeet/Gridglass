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
    "change_type", "split_column", "add_column", "merge", "stack", "pivot", "chart", "unpivot", "convert", "split_pages",
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
    expect(page.locator(".tool-card")).to_have_count(3)
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
    page.select_option("#f-mode", "math")
    page.select_option("#f-left", "Amount")
    page.click('[data-seg="operator"][data-val="*"]')
    page.fill("#f-right_value", "1.18")
    apply(page)
    rows = result_json(page)
    assert all(abs(r["With GST"] - r["Amount"] * 1.18) < 1e-6 for r in rows)


def test_add_column_part_of_a_text(phone):
    page = phone.upload_sample("add_column")
    page.fill("#f-name", "Domain")
    page.select_option("#f-mode", "text")
    page.select_option("#f-text_left", "Email")
    page.select_option("#f-func", "after")                      # Text after… "@"
    page.fill("#f-find_text", "@")
    expect(page.locator("#pv")).to_contain_text("example.com")
    page.select_option("#f-func", "first")                      # the fields follow the choice
    expect(page.locator("#f-find_text")).to_be_hidden()
    page.fill("#f-count", "4")
    page.select_option("#f-func", "word")
    page.select_option("#f-text_left", "Customer")
    page.click('[data-seg="word_from"][data-val="true"]')       # last word: the surname
    apply(page)
    rows = result_json(page)
    assert rows[0]["Customer"] == "Ravi Kumar" and rows[0]["Domain"] == "Kumar"


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
    page.click('[data-seg="mode"][data-val="unpivot"]')
    page.click('[data-seg="columns__mode"][data-val="some"]')
    page.click('[data-field="columns"] [data-col="City"]')
    page.click('[data-field="columns"] [data-col="Amount"]')
    apply(page)
    rows = result_json(page)
    assert len(rows) == 6 and {"Attribute", "Value"} <= set(rows[0])


def test_transpose(phone):
    page = phone.upload_sample("unpivot")                       # opens on Flip rows and columns
    page.select_option("#f-header", "Order ID")
    apply(page)
    rows = result_json(page)
    assert list(rows[0])[0] == "Order ID" and rows[0]["Order ID"] == "Customer"
    assert len(rows[0]) > 2 and "Order ID" not in [r["Order ID"] for r in rows]  # each order is now a column


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


def test_header_row_found_and_changed(phone, tmp_path):
    book = tmp_path / "report.xlsx"
    with xlsxwriter.Workbook(book) as wb:
        ws = wb.add_worksheet("Report")
        ws.write(0, 0, "Monthly Sales Report")
        ws.write_row(2, 0, ["Region", "Customer", "Amount"])
        ws.write_row(3, 0, ["North", "Asha", 100])
        ws.write_row(4, 0, ["South", "Ravi", 250])
    page = phone.open("/#/tool/sort_rows")
    page.set_input_files("#file", str(book))
    page.wait_for_selector("#pv table")
    expect(page.locator("#toast")).to_contain_text("Skipped 2 rows above the column names")
    expect(page.locator(".file-chip")).to_contain_text("2 top rows skipped")
    expect(page.locator("#pv thead")).to_contain_text("Customer")

    page.click('[data-action="headers"]')
    rows = page.locator(".hp-row")
    expect(rows).to_have_count(5)
    expect(rows.nth(2)).to_have_attribute("aria-pressed", "true")
    expect(rows.nth(1)).to_contain_text("blank row")
    page.click('#header-pick [data-row="none"]')
    expect(page.locator(".file-chip")).to_contain_text("no header row")
    expect(page.locator("#pv thead")).to_contain_text("Column 1")
    expect(page.locator(".file-chip")).to_contain_text("4 rows")  # blank rows are dropped

    page.click('[data-action="headers"]')
    page.locator(".hp-row").nth(2).click()
    expect(page.locator(".file-chip")).to_contain_text("2 rows")
    expect(page.locator("#pv thead")).to_contain_text("Region")


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
    expect(options.first).to_contain_text("Bengaluru")          # sorted A→Z
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



# ----------------------------------------------------------------------------- merge (lookup + joins)

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


# ----------------------------------------------------------------------------- files shared from other apps

def test_shared_file_opens_on_home(phone):
    import urllib.request, uuid

    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"shared.csv\"\r\n"
            f"Content-Type: text/csv\r\n\r\nName,City\nAsha,Pune\n\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(phone.base + "/share", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    try:
        urllib.request.build_opener(NoRedirect).open(req)
    except urllib.error.HTTPError as exc:
        location = exc.headers["Location"]
    page = phone.open(location)
    expect(page.locator(".working")).to_contain_text("shared.csv")
    expect(page.locator("#toast")).to_contain_text("shared.csv is ready")
    assert page.evaluate("location.hash") == "#/"
    page.click('a[href="#/tool/sort_rows"]')
    expect(page.locator(".file-chip")).to_contain_text("shared.csv")


def test_shared_file_error_is_shown(phone):
    page = phone.open("/#/open?error=" + "This%20file%20is%20empty.")
    expect(page.locator("#toast")).to_contain_text("This file is empty.")


# ----------------------------------------------------------------------------- stack files

def test_stack_files(phone, tmp_path):
    feb, mar = tmp_path / "feb.csv", tmp_path / "mar.csv"
    feb.write_text("customer,ORDER ID,Amount\nZara,2001,10\n")
    mar.write_text("Order ID,Customer,Amount,Note\n3001,Yash,20,late\n3002,Ira,30,\n")
    page = phone.upload_sample("stack")
    expect(page.locator(".file-chip").first).to_contain_text("45 rows")
    page.set_input_files("#file3", [str(feb), str(mar)])
    expect(page.locator(".stack-list li")).to_have_count(2)
    expect(page.locator(".preview-head")).to_contain_text("3 more rows")
    page.locator("label.toggle", has_text="which file").click()
    expect(page.locator("#pv thead")).to_contain_text("Source file")
    page.click('[data-stack-remove="0"]')
    expect(page.locator(".stack-list li")).to_have_count(1)
    expect(page.locator(".preview-head")).to_contain_text("2 more rows")
    apply(page)
    expect(page.locator(".done h1")).to_contain_text("Stacked")
    data = download(page, "csv").read_text(encoding="utf-8-sig").splitlines()
    assert data[0] == "Order ID,Customer,Email,City,Amount,Order date,Note,Source file"
    assert data[-1].startswith("3002,Ira,") and data[-1].endswith(",mar.csv")


# ----------------------------------------------------------------------------- recipes

def test_save_and_reuse_a_recipe(phone, tmp_path):
    page = phone.upload_sample("trim")
    apply(page)
    page.goto(phone.base + "/#/tool/remove_duplicates")
    page.wait_for_selector("#apply")
    apply(page)
    page.click('[data-action="save-recipe"]')
    page.fill("#recipe-name", "Monthly cleanup")
    page.click('.recipe-form button[type="submit"]')
    expect(page.locator(".recipe-saved")).to_contain_text("Saved “Monthly cleanup”")

    page.click('[data-action="startover"]')
    expect(page.locator(".recipe")).to_contain_text("Monthly cleanup")
    expect(page.locator(".recipe")).to_contain_text("2 steps · Trim spaces → Remove duplicates")
    page.click('.recipe a:has-text("Use")')
    expect(page.locator(".recipe-steps li")).to_have_count(2)
    nxt = tmp_path / "next.csv"
    nxt.write_text("Name,City\n  Asha ,Pune\nAsha,Pune\nRavi,Delhi\n")
    page.set_input_files("#file", str(nxt))
    expect(page.locator(".done h1")).to_contain_text("Ran “Monthly cleanup”")
    expect(page.locator(".done p")).to_contain_text("3 rows → 2 rows")
    expect(page.locator(".step-list li")).to_have_count(2)


def test_recipe_stops_at_a_step_that_does_not_fit(phone, tmp_path):
    page = phone.open("/")
    page.evaluate("""localStorage.setItem('gg.recipes', JSON.stringify([{id: 'r1', name: 'Tidy', steps: [
        {op: 'trim'}, {op: 'sort_rows', by: [{column: 'Amount', descending: true}]}]}]))""")
    page.goto(phone.base + "/#/recipe/r1")
    other = tmp_path / "other.csv"
    other.write_text("Name\n  Zed \n")
    page.set_input_files("#file", str(other))
    expect(page.locator(".done h1")).to_contain_text("Ran “Tidy”")
    expect(page.locator("#toast")).to_contain_text("Step 2 of the recipe (Sort rows) doesn't fit")
    expect(page.locator(".step-list li")).to_have_count(1)


def test_rename_and_delete_recipes(phone):
    page = phone.open("/")
    page.evaluate("localStorage.setItem('gg.recipes', JSON.stringify([{id: 'r1', name: 'Old name', steps: [{op: 'trim'}]}]))")
    page.reload()
    page.click('[data-recipe-rename="r1"]')
    page.fill("#rn-r1", "New name")
    page.click('.recipe-rename button[type="submit"]')
    expect(page.locator(".recipe strong")).to_have_text("New name")
    page.click('[data-recipe-delete="r1"]')
    expect(page.locator('[data-recipe-delete="r1"]')).to_have_text("Tap again to delete")
    page.click('[data-recipe-delete="r1"]')
    expect(page.locator(".recipes")).to_have_count(0)


def test_recipe_with_merge_asks_for_the_other_file(phone, tmp_path):
    towns = tmp_path / "towns.csv"
    towns.write_text("Town,Zone\nPune,W\nDelhi,N\n")
    page = phone.upload_sample("merge")
    page.set_input_files("#file2", str(towns))
    expect(page.locator(".file-chip.second")).to_contain_text("towns.csv")
    page.select_option("#k0l", "City")
    page.select_option("#k0r", "Town")
    apply(page)
    expect(page.locator(".recipe-save .hint")).to_contain_text("choose the file to merge or stack each time")
    page.click('[data-action="save-recipe"]')
    page.fill("#recipe-name", "Add zones")
    page.click('.recipe-form button[type="submit"]')
    stored = page.evaluate("JSON.parse(localStorage.getItem('gg.recipes'))[0].steps[0]")
    assert stored["op"] == "merge" and stored["other"] is None  # the expiring upload isn't kept

    page.click('[data-action="startover"]')
    page.click('.recipe a:has-text("Use")')
    expect(page.locator(".recipe-slot")).to_contain_text("Last time: towns.csv")
    main = tmp_path / "april.csv"
    main.write_text("Name,City\nAsha,Pune\nRavi,Delhi\nMeena,Goa\n")
    page.set_input_files("#file", str(main))
    expect(page.locator("#ptext")).to_contain_text("Now choose the other file")
    zones = tmp_path / "zones-new.csv"
    zones.write_text("Town,Zone\nPune,West\nGoa,South\n")
    page.set_input_files("#slot-0", str(zones))
    expect(page.locator(".done h1")).to_contain_text("Ran “Add zones”")
    rows = result_json(page)
    assert {r["Name"]: r["Zone"] for r in rows} == {"Asha": "West", "Ravi": None, "Meena": "South"}


def test_leaving_a_recipe_deletes_its_unused_files(phone, tmp_path):
    page = phone.open("/")
    page.evaluate("""localStorage.setItem('gg.recipes', JSON.stringify([{id: 'r1', name: 'Zones', steps: [
        {op: 'merge', other: null, other_name: 'towns.csv', keys: [{left: 'City', right: 'Town'}]}]}]))""")
    page.goto(phone.base + "/#/recipe/r1")
    (tmp_path / "towns.csv").write_text("Town,Zone\nPune,W\n")
    page.set_input_files("#slot-0", str(tmp_path / "towns.csv"))
    expect(page.locator(".recipe-slot.done")).to_have_count(1)
    with page.expect_response(lambda r: r.request.method == "DELETE" and "/api/v1/files/" in r.url) as gone:
        page.click('a[aria-label="Back"]')
    assert gone.value.ok and page.request.get(gone.value.url).status == 404   # the merge file is gone
    expect(page.locator("#toast")).not_to_be_visible()


def test_recipe_with_stack_asks_for_each_file(phone, tmp_path):
    page = phone.open("/")
    page.evaluate("""localStorage.setItem('gg.recipes', JSON.stringify([{id: 'r1', name: 'Combine', steps: [
        {op: 'stack', others: [null, null], other_names: ['feb.csv', 'mar.csv'], this_name: 'jan.csv',
         source_column: 'Month file'}]}]))""")
    page.goto(phone.base + "/#/recipe/r1")
    expect(page.locator(".recipe-slot")).to_have_count(2)
    for name, body in (("may.csv", "Item\nB\n"), ("jun.csv", "Item\nC\n")):
        (tmp_path / name).write_text(body)
    page.set_input_files("#slot-0", str(tmp_path / "may.csv"))
    page.set_input_files("#slot-1", str(tmp_path / "jun.csv"))
    expect(page.locator(".recipe-slot.done")).to_have_count(2)
    (tmp_path / "apr.csv").write_text("Item\nA\n")
    page.set_input_files("#file", str(tmp_path / "apr.csv"))
    expect(page.locator(".done h1")).to_contain_text("Ran “Combine”")
    rows = result_json(page)
    assert [(r["Item"], r["Month file"]) for r in rows] == [("A", "apr.csv"), ("B", "may.csv"), ("C", "jun.csv")]


# ----------------------------------------------------------------------------- information pages

def test_tool_page_leads_into_the_app(phone):
    page = phone.open("/tools/stack-files")
    expect(page.locator("h1")).to_contain_text("Combine multiple CSV files into one")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    before = page.evaluate("document.documentElement.dataset.theme")
    page.click('[data-action="theme"]')
    assert page.evaluate("document.documentElement.dataset.theme") != before
    page.locator(".faqs summary").first.click()
    expect(page.locator(".faqs details").first).to_have_attribute("open", "")
    page.locator("a.btn", has_text="Open Stack files").first.click()
    expect(page.locator(".intro h1")).to_have_text("Stack files")


def test_app_links_to_information_pages(phone):
    page = phone.open("/")
    page.click('.app-links a[href="/privacy"]')
    expect(page.locator("h1")).to_have_text("Privacy policy")
    page.click(".site-top .brand")
    expect(page.locator(".tool-card").first).to_be_visible()


def test_guides_are_easy_to_find(phone):
    page = phone.open("/")
    expect(page.locator(".topbar .top-link")).to_have_text("Guides")
    page.goto(phone.base + "/#/tool/pivot")
    expect(page.locator(".intro-link")).to_have_attribute("href", "/tools/pivot-table")
    page.click('[data-action="sample"]')
    page.wait_for_selector("#pv table")
    page.click('.topbar a[aria-label="How to use Pivot table"]')
    expect(page.locator("h1")).to_contain_text("pivot table")


# ----------------------------------------------------------------------------- more options (1.8)

def test_show_and_mark_duplicates(phone):
    page = phone.upload_sample("remove_duplicates")
    page.click('[data-seg="action"][data-val="show"]')
    expect(page.locator(".preview-head")).to_contain_text("35 fewer rows")  # 45 → 10: 5 rows, each with its copy
    page.click('[data-seg="action"][data-val="mark"]')
    expect(page.locator("#pv thead")).to_contain_text("Duplicate")
    apply(page)
    expect(page.locator(".done h1")).to_have_text("Duplicates marked")
    rows = result_json(page)
    assert len(rows) == 45 and sum(r["Duplicate"] == "Yes" for r in rows) == 5


def test_clean_up_text(phone):
    page = phone.upload_sample("replace_values")
    page.click('[data-seg="action"][data-val="clean"]')
    page.click('[data-col-toggle="columns"][data-col="Email"]')
    page.select_option("#f-clean", "email_domain")
    apply(page)
    assert {r["Email"] for r in result_json(page)} == {"example.com", None}


def test_rank_within_each_city(phone):
    page = phone.upload_sample("add_column")
    page.fill("#f-name", "Rank in city")
    page.select_option("#f-mode", "rank")
    page.select_option("#f-left", "Amount")
    page.click('[data-seg="within__mode"][data-val="some"]')
    page.click('[data-col-toggle="within"][data-col="City"]')
    apply(page)
    rows = result_json(page)
    for city in {r["City"] for r in rows}:
        best = max((r for r in rows if r["City"] == city), key=lambda r: r["Amount"])
        assert best["Rank in city"] == 1


def test_split_every_n_rows_into_separate_files(phone):
    import zipfile

    page = phone.upload_sample("split_pages")
    page.click('[data-seg="splitby"][data-val="rows"]')
    page.fill("#split-n", "20")
    expect(page.locator(".page-list li")).to_have_count(3)                # 45 rows → 20 + 20 + 5
    page.click('[data-seg="splitfmt"][data-val="zip"]')
    expect(page.locator('[data-action="download"]')).to_contain_text("Download 3 files (.zip)")
    with page.expect_download() as dl:
        page.click('[data-action="download"]')
    names = zipfile.ZipFile(dl.value.path()).namelist()
    assert names == ["sample-orders - Rows 1–20.csv", "sample-orders - Rows 21–40.csv", "sample-orders - Rows 41–45.csv"]
    page.fill("#split-n", "0")
    expect(page.locator('[data-action="download"]')).to_be_disabled()


def test_pdf_options_in_convert(phone):
    page = phone.upload_sample("convert")
    expect(page.locator("#pdf-opts")).to_be_hidden()
    page.select_option("#fmt", "pdf")
    page.click('[data-seg="orient"][data-val="portrait"]')
    page.fill("#pdf-title", "Orders for March")
    page.click('[data-seg="pdfcols"][data-val="some"]')
    page.click('[data-pdfcol="Email"]')
    with page.expect_download() as dl:
        page.click('[data-action="download"]')
    data = Path(dl.value.path()).read_bytes()
    assert data.startswith(b"%PDF") and b"Orders for March" in data
    w, h = (float(x) for x in re.search(rb"/MediaBox \[\s*[\d.]+ [\d.]+ ([\d.]+) ([\d.]+)", data).groups())
    assert w < h


# ----------------------------------------------------------------------------- 1.9: smarter add column, health check, headers

def test_if_then_column(phone):
    page = phone.upload_sample("add_column")
    page.fill("#f-name", "Size")
    page.select_option("#f-mode", "if_then")
    page.select_option("#r0col", "Amount")
    page.select_option("#r0op", "greater_or_equal")
    page.fill("#r0v", "500")
    page.fill("#r0then", "Big")
    page.click('[data-add="rules"]')
    page.select_option("#r1col", "City")
    page.fill("#r1v", "Pune")
    page.keyboard.press("Escape")
    page.fill("#r1then", "Pune order")
    page.fill("#f-otherwise", "Small")
    apply(page)
    for r in result_json(page):
        want = "Big" if r["Amount"] >= 500 else "Pune order" if r["City"] == "Pune" else "Small"
        assert r["Size"] == want


def test_date_part_and_ranges(phone):
    page = phone.upload_sample("add_column")
    page.fill("#f-name", "FY")
    page.select_option("#f-mode", "date_part")
    page.select_option("#f-part", "fy")
    expect(page.locator("#pv thead")).to_contain_text("FY")
    apply(page)
    assert all(r["FY"].startswith("FY 202") for r in result_json(page))
    page.goto(phone.base + "/#/tool/add_column")
    page.wait_for_selector("#f-mode")
    page.fill("#f-name", "Band")
    page.select_option("#f-mode", "ranges")
    page.select_option("#f-left", "Amount")
    page.fill("#f-breaks", "300, 600")
    apply(page)
    bands = {r["Band"] for r in result_json(page)}
    assert bands <= {"Under 300", "300 – under 600", "600 and over"} and len(bands) == 3


def test_health_check_and_one_tap_fix(phone):
    page = phone.upload_sample("sort_rows")
    page.click('[data-action="check"]')
    expect(page.locator("#health")).to_contain_text("exact copies")
    expect(page.locator("#health")).to_contain_text("extra spaces")
    page.locator("#health [data-fix]", has_text="Remove copies").click()
    expect(page.locator("#toast")).to_contain_text("Remove copies: done")
    expect(page.locator(".file-chip")).to_contain_text("1 step applied")
    expect(page.locator("#health")).not_to_contain_text("exact copies")
    page.locator("#health summary").click()
    expect(page.locator("#health table")).to_contain_text("Customer")


def test_headers_for_a_stacked_file(phone, tmp_path):
    extra = tmp_path / "titled.csv"
    extra.write_text("Order report\n\nOrder ID,Customer,Amount\n9001,Zed,5\n")
    page = phone.upload_sample("stack")
    page.set_input_files("#file3", str(extra))
    expect(page.locator(".stack-list li")).to_contain_text("1 row")
    page.click('[data-stack-headers="0"]')
    page.locator("#header-pick3 .hp-row").nth(0).click()        # use the title line as headers instead
    expect(page.locator("#toast")).to_contain_text("row 1")
    expect(page.locator(".stack-list li")).to_contain_text("3 rows")


# ----------------------------------------------------------------------------- charts (1.10)

def test_make_a_chart_opens_on_the_chart(phone):
    page = phone.open("/")
    page.click('a[href="#/tool/chart"]')
    expect(page.locator(".intro h1")).to_have_text("Make a chart")
    page.click('[data-action="sample"]')
    expect(page.locator(".topbar-title")).to_have_text("Make a chart")
    expect(page.locator("#tab-chart")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#chart-panel")).to_be_visible()
    expect(page.locator("#pv")).to_be_hidden()
    expect(page.locator("#chart svg")).to_be_visible()


def test_chart_customisation(phone):
    page = phone.upload_sample("pivot")
    page.click("#tab-chart")
    expect(page.locator("#chart svg")).to_be_visible()
    page.locator("#chart-custom summary").click()
    page.fill("#ch-title", "Orders by city")
    page.fill("#ch-x", "City")
    page.fill("#ch-y", "Orders")
    expect(page.locator("#chart svg")).to_contain_text("Orders by city")
    page.click('[data-palette="sunset"]')
    expect(page.locator("#chart svg rect.grow-y").first).to_have_attribute("fill", "#EA580C")
    page.locator("label.toggle", has_text="Show data labels").click()
    page.click('[data-seg="chsort"][data-val="desc"]')
    page.click('[data-seg="chtop"][data-val="5"]')
    bars = page.locator("#chart svg rect.grow-y")
    expect(bars).to_have_count(6)                                    # the top 5, plus "Other" for the rest
    expect(page.locator("#chart svg")).to_contain_text("Other (")
    page.click('[data-seg="chshape"][data-val="square"]')
    expect(page.locator("#chart svg")).to_have_attribute("viewBox", re.compile(r"^0 0 (\d+) \1$"))  # square, at the phone's width
    for kind in ("area", "donut"):
        page.click(f'[data-seg="charttype"][data-val="{kind}"]')
        expect(page.locator("#chart svg")).to_be_visible()
    expect(page.locator("#chart svg")).to_contain_text("Total")       # the donut's middle
    with page.expect_download() as dl:
        page.click('[data-chart-save="svg"]')
    svg = Path(dl.value.path()).read_text()
    assert "Orders by city" in svg and 'viewBox="0 0 560 560"' in svg and dl.value.suggested_filename.startswith("Orders by city-donut")
    page.click("[data-chart-reset]")
    expect(page.locator('[data-palette="theme"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#ch-title")).to_have_value("Orders by city")  # words are kept


def test_chart_fits_the_phone_and_stays_in_view(phone):
    page = phone.upload_sample("pivot")
    page.click("#tab-chart")
    svg = page.locator("#chart svg")
    expect(svg).to_be_visible()
    box_w = page.evaluate("document.querySelector('#chart').clientWidth")
    assert abs(int(svg.get_attribute("width")) - box_w) <= 1           # drawn at the phone's width, not shrunk
    types = page.locator('[data-seg="charttype"]')
    assert types.nth(0).bounding_box()["y"] < types.nth(3).bounding_box()["y"]   # two rows of three on a phone
    page.locator("#chart-custom summary").click()
    page.locator("label.toggle", has_text="grid lines").scroll_into_view_if_needed()
    chart = page.locator(".chart-stick").bounding_box()
    assert chart["y"] >= -1 and chart["y"] < 40                            # pinned at the top while scrolling the options
    toggle = page.locator("label.toggle", has_text="grid lines").bounding_box()
    assert toggle["y"] >= chart["y"] + chart["height"] - 1                 # the option shows below the chart, not under it
    assert page.evaluate("getComputedStyle(document.querySelector('.action-bar')).position") == "static"


def test_pivot_filter_and_percentage_labels(phone):
    page = phone.upload_sample("pivot")
    expect(page.locator("#opts")).to_contain_text("No filter: every row is counted.")
    page.click('[data-add="filters"]')
    page.select_option("#pf0col", "City")
    page.fill("#pf0v", "Pune")
    page.keyboard.press("Escape")
    page.click("#tab-chart")
    page.locator("#chart-custom summary").click()
    page.click('[data-seg="charttype"][data-val="pie"]')
    page.locator("label.toggle", has_text="Show data labels").click()
    for part, on in (("name", "true"), ("value", "false"), ("percent", "true")):    # pies default to name + %
        expect(page.locator(f'[data-labelpart="{part}"]')).to_have_attribute("aria-pressed", on)
    labels = page.locator("#chart svg text[fill='#FFFFFF']")
    expect(labels.first).to_be_visible()
    texts = labels.all_text_contents()
    assert any(t.endswith("%") for t in texts) and any(t.startswith(("Asha", "Ravi", "Priya", "meera", "Dev", "(blank")) for t in texts)
    page.click('[data-labelpart="value"]')                                       # name + value + %
    expect(page.locator('[data-labelpart="value"]')).to_have_attribute("aria-pressed", "true")
    page.click('[data-labelpart="name"]')
    page.click('[data-labelpart="percent"]')
    page.click('[data-labelpart="value"]')                                       # the last one can't be turned off
    expect(page.locator('[data-labelpart="value"]')).to_have_attribute("aria-pressed", "true")
    page.click('[data-labelpart="percent"]')
    texts = labels.all_text_contents()
    assert any(t.endswith("%") for t in texts) and any(not t.endswith("%") for t in texts)   # value and % lines
    shares = [float(t.split("%")[0]) for t in page.locator("#chart svg text[text-anchor='end']").all_text_contents() if "%" in t]
    assert shares == sorted(shares, reverse=True) and len(shares) >= 2           # biggest slice first in the legend
    page.click('[data-seg="charttype"][data-val="column"]')
    expect(page.locator('[data-labelpart="name"]')).to_be_hidden()               # names are on the axis already
    expect(page.locator("#chart svg")).to_contain_text("%")
    apply(page)
    step = page.evaluate("""async () => {
        const id = sessionStorage.getItem('gg.file');
        return (await (await fetch(`/api/v1/files/${id}`)).json()).file.steps[0];
    }""")
    assert step["filters"] == [{"column": "City", "operator": "equals", "value": "Pune", "case_sensitive": False}]
