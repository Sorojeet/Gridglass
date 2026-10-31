"""REST API, mounted at /api/v1.

    GET    /config                         upload limit, retention, preview size
    GET    /tools                          every tool, its category and its option schema
    POST   /files                          upload (multipart "file", optional "sheet")
    GET    /files/<id>                     metadata and saved steps
    DELETE /files/<id>                     delete now
    PUT    /files/<id>/sheet               switch the sheet of a .xlsx/.xls {"sheet": "..."} (clears steps)
    GET    /files/<id>/preview             preview with the saved steps (?limit=&offset= to page)
    POST   /files/<id>/preview             preview a draft {"steps": [...]} without saving
    GET    /files/<id>/columns             column stats after the saved steps (?upto=n: after the first n)
    GET    /files/<id>/values?column=      distinct values of a column with counts (filter dropdown)
    PUT    /files/<id>/steps               replace all steps {"steps": [...]}
    POST   /files/<id>/steps               append one step {...}
    DELETE /files/<id>/steps               remove all steps
    DELETE /files/<id>/steps/<n>           remove step n (undo)
    GET    /files/<id>/export?format=csv   download the result (csv | xlsx | json | pdf);
                                           &split_by=<column>: one sheet (.xlsx) / page (PDF) per value
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request, send_file

from .engine import (OPS, GridglassError, IngestError, InvalidStepsError, build, distinct_values, open_source,
                     parse_steps, preview, profile)
from .engine.io import EXPORT_FORMATS, export
from .limits import from_config, limiter
from .storage import NotFound, Store

bp = Blueprint("api", __name__, url_prefix="/api/v1")
limiter.limit(from_config("RATE_LIMIT_API"))(bp)

CATEGORIES = {
    "clean": ["remove_duplicates", "trim", "change_case", "replace_values", "fill_blanks", "remove_blank_rows"],
    "shape": ["remove_columns", "keep_columns", "rename_columns", "filter_rows", "sort_rows", "keep_rows",
              "change_type", "split_column", "add_column"],
    "combine": ["merge"],
    "summarize": ["pivot", "unpivot"],
}
MIMETYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
    "pdf": "application/pdf",
}


def store() -> Store:
    return current_app.extensions["gridglass_store"]


def _cfg(key: str):
    return current_app.config[key]


def _steps_and_frame(file_id: str, raw_steps: list[dict[str, Any]]):
    steps = parse_steps(raw_steps, max_steps=_cfg("MAX_STEPS"))
    st = store()

    def resolve(other_id: str):  # a second upload used by Merge; must still exist (not expired)
        st.meta(other_id)
        return open_source(st.source(other_id))

    return steps, build(open_source(st.source(file_id)), steps, resolve=resolve)


def _saved_steps(file_id: str) -> list[dict[str, Any]]:
    """The saved steps, or only the first `?upto=` of them (how the data looked before a step being edited)."""
    steps = store().meta(file_id)["steps"]
    upto = request.args.get("upto")
    if upto is None or upto == "":
        return steps
    try:
        return steps[: max(0, int(upto))]
    except ValueError:
        raise InvalidStepsError("upto must be a number.") from None


def _limit() -> int:
    """Rows per preview: PREVIEW_ROWS by default, at most PAGE_ROWS (one page of the full view)."""
    try:
        return max(1, min(int(request.args.get("limit", _cfg("PREVIEW_ROWS"))), _cfg("PAGE_ROWS")))
    except ValueError:
        return _cfg("PREVIEW_ROWS")


def _offset(limit: int) -> int:
    """Where the page starts. Browsing stops at BROWSE_MAX_ROWS; beyond that people download."""
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return 0
    return min(offset, max(0, _cfg("BROWSE_MAX_ROWS") - limit))


def _page(lf):
    limit = _limit()
    return preview(lf, limit, _offset(limit))


def _body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise InvalidStepsError("Send a JSON object.")
    return body


def _save(file_id: str, raw_steps: list[dict[str, Any]]):
    """Validate the steps against the data, store them, and return the new state with a preview."""
    steps, lf = _steps_and_frame(file_id, raw_steps)
    meta = store().save_steps(file_id, [s.model_dump(mode="json") for s in steps])
    return jsonify(file=meta, preview=_page(lf))


# ---------------------------------------------------------------------- config & tools

@bp.get("/config")
def client_config():
    """Limits the app shows to users before they upload."""
    c = current_app.config
    return jsonify(max_upload_mb=c["MAX_UPLOAD_MB"], retention_minutes=c["FILE_RETENTION_MINUTES"],
                   preview_rows=c["PREVIEW_ROWS"], page_rows=c["PAGE_ROWS"], browse_max_rows=c["BROWSE_MAX_ROWS"],
                   export_formats=sorted(EXPORT_FORMATS))


@bp.get("/tools")
def tools():
    out = []
    for category, ops in CATEGORIES.items():
        for op in ops:
            model = OPS[op]
            out.append({
                "op": op,
                "label": model.label,
                "category": category,
                "description": (model.__doc__ or "").strip().splitlines()[0] if model.__doc__ else "",
                "schema": model.model_json_schema(),
            })
    return jsonify(tools=out, export_formats=sorted(EXPORT_FORMATS))


# ---------------------------------------------------------------------- files

@bp.post("/files")
@limiter.limit(from_config("RATE_LIMIT_UPLOADS"))
def upload():
    file = request.files.get("file")
    if file is None or not file.filename:
        raise IngestError("Choose a file to upload.")
    meta = store().create(file.stream, file.filename, sheet=request.form.get("sheet") or None)
    lf = open_source(store().source(meta["id"]))
    return jsonify(file=meta, preview=_page(lf)), 201


@bp.get("/files/<file_id>")
def get_file(file_id):
    return jsonify(file=store().meta(file_id))


@bp.delete("/files/<file_id>")
def delete_file(file_id):
    store().meta(file_id)  # 404 if missing
    store().delete(file_id)
    return "", 204


@bp.put("/files/<file_id>/sheet")
def change_sheet(file_id):
    sheet = _body().get("sheet")
    if not isinstance(sheet, str) or not sheet:
        raise IngestError("Choose a sheet.")
    meta = store().change_sheet(file_id, sheet)
    return jsonify(file=meta, preview=_page(open_source(store().source(file_id))))


# ---------------------------------------------------------------------- preview & columns

@bp.get("/files/<file_id>/preview")
def get_preview(file_id):
    _, lf = _steps_and_frame(file_id, store().meta(file_id)["steps"])
    return jsonify(preview=_page(lf))


@bp.post("/files/<file_id>/preview")
def draft_preview(file_id):
    """Live preview while the user adjusts a tool's options. Nothing is saved."""
    raw = _body().get("steps", store().meta(file_id)["steps"])
    _, lf = _steps_and_frame(file_id, raw)
    return jsonify(preview=_page(lf))


@bp.get("/files/<file_id>/values")
def column_values(file_id):
    """Distinct values of one column (after the saved steps), for the filter's dropdown. ?column=&q=&limit="""
    column = request.args.get("column", "")
    try:
        limit = max(1, min(int(request.args.get("limit", 200)), 500))
    except ValueError:
        limit = 200
    _, lf = _steps_and_frame(file_id, _saved_steps(file_id))
    return jsonify(distinct_values(lf, column, request.args.get("q") or None, limit))


@bp.get("/files/<file_id>/columns")
def columns(file_id):
    _, lf = _steps_and_frame(file_id, _saved_steps(file_id))
    return jsonify(columns=profile(lf))


# ---------------------------------------------------------------------- steps

@bp.put("/files/<file_id>/steps")
def replace_steps(file_id):
    store().meta(file_id)
    return _save(file_id, _body().get("steps", []))


@bp.post("/files/<file_id>/steps")
def append_step(file_id):
    current = store().meta(file_id)["steps"]
    return _save(file_id, current + [_body()])


@bp.delete("/files/<file_id>/steps")
def clear_steps(file_id):
    store().meta(file_id)
    return _save(file_id, [])


@bp.delete("/files/<file_id>/steps/<int:index>")
def remove_step(file_id, index):
    current = store().meta(file_id)["steps"]
    if not 0 <= index < len(current):
        raise NotFound(file_id)
    return _save(file_id, current[:index] + current[index + 1:])


# ---------------------------------------------------------------------- export

@bp.get("/files/<file_id>/export")
@limiter.limit(from_config("RATE_LIMIT_EXPORTS"))
def download(file_id):
    meta = store().meta(file_id)
    fmt = (request.args.get("format") or "csv").lower()
    _, lf = _steps_and_frame(file_id, meta["steps"])
    stem = Path(meta["filename"]).stem or "data"
    dest = store().export_path(file_id, fmt if fmt in EXPORT_FORMATS else "out")
    split_by = request.args.get("split_by") or None
    export(lf, fmt, dest, title=stem, max_pdf_rows=_cfg("MAX_PDF_ROWS"), split_by=split_by)
    fh = open(dest, "rb")
    try:
        dest.unlink()  # the open handle keeps the data readable; nothing is left on disk
    except OSError:     # Windows can't delete open files — clean up when the response closes
        fh.close()
        fh = None
    response = send_file(fh or dest, mimetype=MIMETYPES[fmt], as_attachment=True,
                         download_name=f"{stem}-gridglass.{fmt}", max_age=0)
    if fh is None:
        response.call_on_close(lambda: dest.unlink(missing_ok=True))
    return response


# ---------------------------------------------------------------------- errors

_STATUS = {"invalid_steps": 400, "bad_file": 400, "step_failed": 422, "export_failed": 422}


@bp.errorhandler(GridglassError)
def _engine_error(exc: GridglassError):
    return jsonify(error=exc.to_dict()), _STATUS.get(exc.code, 422)


@bp.errorhandler(NotFound)
def _not_found(_exc):
    return jsonify(error={"code": "not_found",
                          "message": "This file doesn't exist or has expired. Files are deleted after an hour."}), 404
