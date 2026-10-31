from __future__ import annotations

import io
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone

import polars as pl
import pytest
import xlsxwriter

from gridglass import create_app
from gridglass.config import TestConfig

CSV = b"Name,City,Amount\n  Asha ,Pune,100\nRavi,Delhi,250.5\nRavi,Delhi,250.5\nMeera,Pune,80\n"


@pytest.fixture
def app(tmp_path):
    return create_app(TestConfig, DATA_DIR=tmp_path / "data", MAX_CONTENT_LENGTH=200_000, MAX_UPLOAD_MB=0.2)


@pytest.fixture
def client(app):
    return app.test_client()


def upload(client, content=CSV, name="orders.csv", **form):
    return client.post("/api/v1/files", data={"file": (io.BytesIO(content), name), **form},
                       content_type="multipart/form-data")


@pytest.fixture
def file_id(client):
    return upload(client).get_json()["file"]["id"]


# --------------------------------------------------------------------------- basics

def test_healthz(client):
    body = client.get("/healthz").get_json()
    assert body["status"] == "ok" and body["tools"] == 18


def test_tools_list(client):
    body = client.get("/api/v1/tools").get_json()
    assert len(body["tools"]) == 18 and body["export_formats"] == ["csv", "json", "pdf", "xlsx"]
    trim = next(t for t in body["tools"] if t["op"] == "trim")
    assert trim["category"] == "clean" and trim["label"] == "Trim spaces"
    assert "collapse_spaces" in trim["schema"]["properties"]


def test_security_headers(client):
    r = client.get("/api/v1/tools")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["Cache-Control"] == "no-store"


# --------------------------------------------------------------------------- upload

def test_upload_returns_meta_and_preview(client):
    r = upload(client)
    assert r.status_code == 201
    body = r.get_json()
    assert body["file"]["rows"] == 4 and body["file"]["columns"] == ["Name", "City", "Amount"]
    assert body["file"]["filename"] == "orders.csv" and len(body["file"]["id"]) == 22
    assert body["preview"]["total_rows"] == 4


def test_upload_without_file(client):
    r = client.post("/api/v1/files", data={}, content_type="multipart/form-data")
    assert r.status_code == 400 and "Choose a file" in r.get_json()["error"]["message"]


def test_upload_bad_type(client):
    r = upload(client, b"%PDF", "x.pdf")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "bad_file"


def test_upload_too_large(client):
    r = upload(client, b"A\n" + b"1\n" * 150_000)
    assert r.status_code == 413 and "MB limit" in r.get_json()["error"]["message"]


def test_failed_upload_leaves_nothing_behind(client, app):
    upload(client, b"", "empty.csv")
    assert list(app.extensions["gridglass_store"].root.iterdir()) == []


def test_excel_sheets(client, tmp_path):
    path = tmp_path / "b.xlsx"
    with xlsxwriter.Workbook(path) as wb:
        wb.add_worksheet("Jan").write_row(0, 0, ["A"])
        ws = wb.add_worksheet("Feb")
        ws.write_row(0, 0, ["B"]); ws.write_row(1, 0, [1]); ws.write_row(2, 0, [2])
    body = upload(client, path.read_bytes(), "b.xlsx").get_json()
    fid = body["file"]["id"]
    assert body["file"]["sheets"] == ["Jan", "Feb"] and body["file"]["sheet"] == "Jan"
    r = client.put(f"/api/v1/files/{fid}/sheet", json={"sheet": "Feb"})
    assert r.status_code == 200 and r.get_json()["file"]["columns"] == ["B"] and r.get_json()["preview"]["total_rows"] == 2
    assert client.put(f"/api/v1/files/{fid}/sheet", json={"sheet": "Mar"}).status_code == 400


def test_csv_has_no_sheets(client, file_id):
    assert client.put(f"/api/v1/files/{file_id}/sheet", json={"sheet": "x"}).status_code == 400


# --------------------------------------------------------------------------- steps

def test_append_steps_and_undo(client, file_id):
    r = client.post(f"/api/v1/files/{file_id}/steps", json={"op": "trim"})
    assert r.status_code == 200 and r.get_json()["preview"]["rows"][0][0] == "Asha"
    r = client.post(f"/api/v1/files/{file_id}/steps", json={"op": "remove_duplicates"})
    assert r.get_json()["preview"]["total_rows"] == 3 and len(r.get_json()["file"]["steps"]) == 2
    r = client.delete(f"/api/v1/files/{file_id}/steps/1")
    assert r.get_json()["preview"]["total_rows"] == 4 and [s["op"] for s in r.get_json()["file"]["steps"]] == ["trim"]
    r = client.delete(f"/api/v1/files/{file_id}/steps")
    assert r.get_json()["file"]["steps"] == []


def test_steps_are_stored_with_defaults(client, file_id):
    client.post(f"/api/v1/files/{file_id}/steps", json={"op": "remove_duplicates"})
    step = client.get(f"/api/v1/files/{file_id}").get_json()["file"]["steps"][0]
    assert step == {"op": "remove_duplicates", "columns": None, "keep": "first"}


def test_replace_steps(client, file_id):
    r = client.put(f"/api/v1/files/{file_id}/steps", json={"steps": [
        {"op": "pivot", "rows": ["City"], "values": [{"func": "sum", "column": "Amount", "name": "Total"}]}]})
    assert r.get_json()["preview"]["rows"] == [["Pune", 180.0], ["Delhi", 501.0]]


def test_invalid_step_is_400_and_not_saved(client, file_id):
    r = client.post(f"/api/v1/files/{file_id}/steps", json={"op": "nope"})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_steps"
    assert client.get(f"/api/v1/files/{file_id}").get_json()["file"]["steps"] == []


def test_step_that_does_not_fit_data_is_422_with_index(client, file_id):
    client.post(f"/api/v1/files/{file_id}/steps", json={"op": "trim"})
    r = client.post(f"/api/v1/files/{file_id}/steps", json={"op": "remove_columns", "columns": ["Ghost"]})
    err = r.get_json()["error"]
    assert r.status_code == 422 and err["step_index"] == 1 and "'Ghost'" in err["message"]


def test_remove_missing_step_index(client, file_id):
    assert client.delete(f"/api/v1/files/{file_id}/steps/5").status_code == 404


def test_non_json_body(client, file_id):
    r = client.post(f"/api/v1/files/{file_id}/steps", data="hello", content_type="text/plain")
    assert r.status_code == 400


# --------------------------------------------------------------------------- preview & columns

def test_draft_preview_does_not_save(client, file_id):
    r = client.post(f"/api/v1/files/{file_id}/preview", json={"steps": [{"op": "keep_rows", "count": 1}]})
    assert r.get_json()["preview"]["total_rows"] == 1
    assert client.get(f"/api/v1/files/{file_id}/preview").get_json()["preview"]["total_rows"] == 4


def test_preview_limit_is_capped(client, file_id):
    assert len(client.get(f"/api/v1/files/{file_id}/preview?limit=2").get_json()["preview"]["rows"]) == 2
    assert len(client.get(f"/api/v1/files/{file_id}/preview?limit=99999").get_json()["preview"]["rows"]) == 4


def test_columns_follow_steps(client, file_id):
    client.post(f"/api/v1/files/{file_id}/steps", json={"op": "remove_columns", "columns": ["Amount"]})
    cols = client.get(f"/api/v1/files/{file_id}/columns").get_json()["columns"]
    assert [c["name"] for c in cols] == ["Name", "City"] and cols[1]["distinct"] == 2


# --------------------------------------------------------------------------- export

@pytest.mark.parametrize("fmt, mime, magic", [
    ("csv", "text/csv", b"\xef\xbb\xbfName"),
    ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK"),
    ("json", "application/json", b"["),
    ("pdf", "application/pdf", b"%PDF"),
])
def test_export_formats(client, file_id, fmt, mime, magic):
    client.post(f"/api/v1/files/{file_id}/steps", json={"op": "remove_duplicates"})
    r = client.get(f"/api/v1/files/{file_id}/export?format={fmt}")
    assert r.status_code == 200 and r.mimetype == mime and r.data.startswith(magic)
    assert f'orders-gridglass.{fmt}' in r.headers["Content-Disposition"]
    r.close()


def test_export_applies_steps(client, file_id):
    client.post(f"/api/v1/files/{file_id}/steps", json={"op": "remove_duplicates"})
    r = client.get(f"/api/v1/files/{file_id}/export?format=json")
    assert len(json.loads(r.data)) == 3
    r.close()


def test_export_file_is_cleaned_up(client, app, file_id):
    r = client.get(f"/api/v1/files/{file_id}/export?format=csv")
    r.close()
    assert list((app.extensions["gridglass_store"].root / file_id / "exports").iterdir()) == []


def test_export_unknown_format(client, file_id):
    r = client.get(f"/api/v1/files/{file_id}/export?format=parquet")
    assert r.status_code == 422 and "CSV, XLSX, JSON or PDF" in r.get_json()["error"]["message"]


# --------------------------------------------------------------------------- lifecycle

def test_unknown_and_malformed_ids(client):
    assert client.get("/api/v1/files/AAAAAAAAAAAAAAAAAAAAAA").status_code == 404
    assert client.get("/api/v1/files/..%2F..%2Fetc").status_code == 404


def test_delete(client, file_id):
    assert client.delete(f"/api/v1/files/{file_id}").status_code == 204
    assert client.get(f"/api/v1/files/{file_id}").status_code == 404


def _expire(app, file_id):
    store = app.extensions["gridglass_store"]
    meta_path = store.root / file_id / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    meta_path.write_text(json.dumps(meta))
    return store


def test_expired_file_is_gone(client, app, file_id):
    store = _expire(app, file_id)
    r = client.get(f"/api/v1/files/{file_id}")
    assert r.status_code == 404 and "expired" in r.get_json()["error"]["message"]
    assert not (store.root / file_id).exists()


def test_purge(client, app, file_id):
    keep = upload(client).get_json()["file"]["id"]
    store = _expire(app, file_id)
    (store.root / "half-finished").mkdir()  # fresh, no meta: kept until it's older than retention
    assert store.purge_expired() == 1
    assert sorted(p.name for p in store.root.iterdir()) == sorted([keep, "half-finished"])


def test_purge_cli(app, file_id):
    _expire(app, file_id)
    result = app.test_cli_runner().invoke(args=["purge"])
    assert "Removed 1" in result.output


def test_unexpected_error_is_json(client, file_id, monkeypatch):
    import gridglass.api as api

    monkeypatch.setattr(api, "profile", lambda lf: 1 / 0)
    r = client.get(f"/api/v1/files/{file_id}/columns")
    assert r.status_code == 500 and r.get_json()["error"]["code"] == "server_error"


# --------------------------------------------------------------------------- frontend

def test_index_and_static(client):
    r = client.get("/")
    assert r.status_code == 200 and b'id="view"' in r.data
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert client.get("/static/js/app.js").status_code == 200
    assert client.get("/static/css/app.css").status_code == 200
    m = client.get("/static/manifest.webmanifest")
    assert m.status_code == 200 and m.mimetype == "application/manifest+json"
    m.close()


def test_service_worker_at_root(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and b"gridglass-v7" in r.data and r.headers["Cache-Control"] == "no-cache"
    r.close()


def test_client_config(client):
    body = client.get("/api/v1/config").get_json()
    assert body["retention_minutes"] == 60 and body["export_formats"] == ["csv", "json", "pdf", "xlsx"]


# --------------------------------------------------------------------------- production hardening

def test_rate_limit_on_uploads(tmp_path):
    app = create_app(TestConfig, DATA_DIR=tmp_path / "d", RATELIMIT_ENABLED=True, RATE_LIMIT_UPLOADS="2 per minute")
    c = app.test_client()
    assert upload(c).status_code == 201 and upload(c).status_code == 201
    r = upload(c)
    assert r.status_code == 429 and "wait a minute" in r.get_json()["error"]["message"]
    assert c.get("/api/v1/tools").status_code == 200  # other endpoints still work


def test_rate_limits_are_per_client_ip_behind_proxy(tmp_path):
    app = create_app(TestConfig, DATA_DIR=tmp_path / "d", RATELIMIT_ENABLED=True, TRUST_PROXY=1,
                     RATE_LIMIT_UPLOADS="1 per minute")
    c = app.test_client()
    a = {"X-Forwarded-For": "203.0.113.1"}
    b = {"X-Forwarded-For": "203.0.113.2"}
    post = lambda h: c.post("/api/v1/files", data={"file": (io.BytesIO(CSV), "a.csv")}, headers=h)
    assert post(a).status_code == 201 and post(a).status_code == 429
    assert post(b).status_code == 201  # a different visitor isn't blocked


def test_hsts_only_over_https(tmp_path):
    app = create_app(TestConfig, DATA_DIR=tmp_path / "d", TRUST_PROXY=1)
    c = app.test_client()
    assert "Strict-Transport-Security" not in c.get("/").headers
    r = c.get("/", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["Strict-Transport-Security"].startswith("max-age=")
    assert "camera=()" in r.headers["Permissions-Policy"]


# --------------------------------------------------------------------------- values & paging

def test_column_values_for_dropdown(client, file_id):
    body = client.get(f"/api/v1/files/{file_id}/values?column=City").get_json()
    assert body["values"] == [{"value": "Delhi", "count": 2}, {"value": "Pune", "count": 2}]
    assert body["distinct"] == 2 and body["truncated"] is False and body["type"] == "text"


def test_column_values_search_and_limit(client, file_id):
    body = client.get(f"/api/v1/files/{file_id}/values?column=Name&q=AV").get_json()
    assert [v["value"] for v in body["values"]] == ["Ravi"]
    body = client.get(f"/api/v1/files/{file_id}/values?column=Name&limit=1").get_json()
    assert body["truncated"] is True and body["values"] == [{"value": "Ravi", "count": 2}]  # most common kept


def test_column_values_follow_steps(client, file_id):
    client.post(f"/api/v1/files/{file_id}/steps", json={"op": "trim"})
    names = [v["value"] for v in client.get(f"/api/v1/files/{file_id}/values?column=Name").get_json()["values"]]
    assert "Asha" in names and "  Asha " not in names


def test_column_values_unknown_column(client, file_id):
    r = client.get(f"/api/v1/files/{file_id}/values?column=Nope")
    assert r.status_code == 422 and "not found" in r.get_json()["error"]["message"]


def test_preview_pages(client):
    rows = b"n\n" + b"".join(f"{i}\n".encode() for i in range(2500))
    fid = upload(client, rows, "big.csv").get_json()["file"]["id"]
    p = client.get(f"/api/v1/files/{fid}/preview?limit=1000&offset=1000").get_json()["preview"]
    assert p["offset"] == 1000 and len(p["rows"]) == 1000 and p["rows"][0] == [1000] and p["total_rows"] == 2500
    p = client.get(f"/api/v1/files/{fid}/preview?limit=1000&offset=2000").get_json()["preview"]
    assert len(p["rows"]) == 500
    p = client.get(f"/api/v1/files/{fid}/preview?limit=5000").get_json()["preview"]
    assert len(p["rows"]) == 1000  # one page at most
    p = client.post(f"/api/v1/files/{fid}/preview?limit=1000&offset=1000",
                    json={"steps": [{"op": "sort_rows", "by": [{"column": "n", "descending": True}]}]}).get_json()["preview"]
    assert p["rows"][0] == [1499]


def test_preview_offset_stops_at_browse_limit(client, app):
    app.config["BROWSE_MAX_ROWS"] = 1500
    rows = b"n\n" + b"".join(f"{i}\n".encode() for i in range(3000))
    fid = upload(client, rows, "big.csv").get_json()["file"]["id"]
    p = client.get(f"/api/v1/files/{fid}/preview?limit=1000&offset=2000").get_json()["preview"]
    assert p["offset"] == 500  # clamped: browsing ends at row 1,500



# --------------------------------------------------------------------------- merge across uploads

REGIONS_CSV = b"Town,Region\nPune,West\nDelhi,North\nChennai,South\n"


def test_merge_two_uploads(client, file_id):
    other = upload(client, REGIONS_CSV, "regions.csv").get_json()["file"]["id"]
    step = {"op": "merge", "other": other, "other_name": "regions.csv", "keys": [{"left": "City", "right": "Town"}]}
    r = client.post(f"/api/v1/files/{file_id}/steps", json=step)
    assert r.status_code == 200
    body = r.get_json()
    assert [c["name"] for c in body["preview"]["columns"]] == ["Name", "City", "Amount", "Region"]
    assert body["preview"]["rows"][0][3] == "West"
    r = client.post(f"/api/v1/files/{file_id}/preview", json={"steps": [{**step, "how": "full"}]})
    assert r.get_json()["preview"]["total_rows"] == 5  # 4 orders + Chennai


def test_merge_with_deleted_second_file(client, file_id):
    other = upload(client, REGIONS_CSV, "regions.csv").get_json()["file"]["id"]
    client.delete(f"/api/v1/files/{other}")
    r = client.post(f"/api/v1/files/{file_id}/steps", json={"op": "merge", "other": other, "keys": [{"left": "City", "right": "Town"}]})
    assert r.status_code == 422 and "upload it again" in r.get_json()["error"]["message"]


def test_export_split_by(client, file_id):
    import fastexcel

    r = client.get(f"/api/v1/files/{file_id}/export?format=xlsx&split_by=City")
    path = Path(__file__).parent / "_split.xlsx"
    try:
        path.write_bytes(r.data)
        assert fastexcel.read_excel(str(path)).sheet_names == ["Delhi", "Pune"]
    finally:
        path.unlink(missing_ok=True)
        r.close()
    r = client.get(f"/api/v1/files/{file_id}/export?format=csv&split_by=City")
    assert r.status_code == 422



def test_columns_and_values_before_a_step(client, file_id):
    client.put(f"/api/v1/files/{file_id}/steps", json={"steps": [
        {"op": "trim"}, {"op": "remove_columns", "columns": ["Amount"]}]})
    names = lambda q: [c["name"] for c in client.get(f"/api/v1/files/{file_id}/columns{q}").get_json()["columns"]]
    assert names("") == ["Name", "City"]
    assert names("?upto=1") == ["Name", "City", "Amount"]          # as it was before step 2
    assert names("?upto=0") == ["Name", "City", "Amount"]
    vals = client.get(f"/api/v1/files/{file_id}/values?column=Name&upto=0").get_json()["values"]
    assert "  Asha " in [v["value"] for v in vals]                   # before trim
    assert client.get(f"/api/v1/files/{file_id}/columns?upto=x").status_code == 400
