"""Gridglass end to end, the way people use it: on a phone, tapping through real screens against a real server."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
import xlsxwriter
from playwright.sync_api import expect

ALL_OPS = [
    "remove_duplicates", "trim", "change_case", "replace_values", "fill_blanks", "remove_blank_rows",
    "filter_rows", "sort_rows", "remove_columns", "keep_columns", "rename_columns", "keep_rows",
    "change_type", "split_column", "add_column", "group_by", "pivot", "unpivot", "convert",
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


def test_desktop_uses_three_columns(make_phone):
    page = make_phone("Desktop Chrome").open("/")
    cols = page.evaluate("getComputedStyle(document.querySelector('.tool-grid')).gridTemplateColumns.split(' ').length")
    assert cols == 3


# ----------------------------------------------------------------------------- every tool

@pytest.mark.parametrize("op", ALL_OPS)
def test_every_tool_opens_without_errors(phone, op):
    """With the sample file, each tool shows a preview and either a ready button or a friendly hint — never a red error."""
    page = phone.upload_sample(op)
    page.wait_for_timeout(500)  # let the debounced draft preview land
    expect(page.locator(".form-error")).to_have_count(0)
    if op == "convert":
        expect(page.locator('[data-action="download"]')).to_be_enabled()
        return
    ready = page.locator("#apply").is_enabled()
    hint = page.locator("#pv-note.needs").count() == 1
    assert ready or hint, f"{op}: neither ready nor showing a hint"


@pytest.mark.parametrize("op", [op for op in ALL_OPS if op != "convert"])
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
    page.click('.next a[href="#/tool/sort_rows"]')  # chain without uploading again
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


def test_group_by_and_pivot(phone):
    page = phone.upload_sample("group_by")
    page.click('[data-col-none="by"]')
    page.click('[data-col="City"]')
    page.select_option("#a0f", "sum")
    page.select_option("#a0c", "Amount")
    apply(page)
    expect(page.locator(".done h1")).to_have_text("Grouped into 5 rows")
    rows = result_json(page)
    assert {"City", "Amount (sum)"} == set(rows[0])

    page.click('[data-undo="0"]')
    page.goto(phone.base + "/#/tool/pivot")
    page.wait_for_selector("#opts")
    page.click('[data-col-none="rows"]')
    page.click('[data-col="Customer"]')
    page.select_option("#f-pcol", "City")
    page.select_option("#f-values", "Amount")
    apply(page)
    rows = result_json(page)
    assert {"Pune", "Delhi", "Mumbai"} <= set(rows[0])


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
