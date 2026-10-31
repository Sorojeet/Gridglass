# Gridglass

Simple spreadsheet tools for everyone. Pick a tool, upload a CSV or spreadsheet file, preview the change, and download the result. Gridglass is built for phones first.

## How it works

Every tool is a **step**: a small JSON object validated by a pydantic model.

```json
[
  {"op": "trim", "collapse_spaces": true},
  {"op": "remove_duplicates", "columns": ["Email"], "keep": "first"},
  {"op": "filter_rows", "conditions": [{"column": "City", "operator": "equals", "value": "Pune"}]}
]
```

Uploads are converted **once** into a Parquet cache file. Each request replays the step list on a Polars LazyFrame (`pl.scan_parquet` → steps → `.collect()`). The query optimizer then only touches the columns and rows each request needs:
- **Preview:** `.head(200)`
- **Export:** the full result

Undo means deleting a step, and chaining tools means appending steps.

```
gridglass/
  __init__.py        Flask app factory (API arrives in Phase 4)
  config.py          limits: 100 MB uploads, 200-row previews, 1-hour retention …
  engine/
    steps.py         the 18 tools + parse_steps() validation
    pipeline.py      build(), run(), preview(), profile()
    io.py            ingest (CSV/TSV/XLSX/XLS/JSON/NDJSON → Parquet), export (CSV/XLSX/JSON/PDF)
    pdf.py           table-style PDF export (ReportLab)
    dtypes.py        friendly type names, coercion of user-typed values
    errors.py        user-safe error types
tests/               pytest suite
```

## Tools (step `op` names)

| Clean | Shape | Summarize |
|---|---|---|
| `remove_duplicates` | `remove_columns` | `pivot`: Rows, optional Columns, several Values, Grand Total. With no Columns it works as a group-by. |
| `trim` | `keep_columns` (choose and reorder) | `unpivot` |
| `change_case` | `rename_columns` | |
| `replace_values` | `filter_rows` (13 operators, all/any) | |
| `fill_blanks` (value, down, up) | `sort_rows` | |
| `remove_blank_rows` | `keep_rows` (top/bottom) | |
| | `change_type` | |
| | `split_column` | |
| | `add_column` (constant, combine, math) | |

**Combine:** `merge` brings in columns from a second upload by matching keys (a lookup). It has every join: lookup/left, inner, full outer, right, anti (no match) and semi (has a match).
- It can match on up to 5 key columns.
- "First match only" keeps one match per key when keys repeat.
- The second file's keys are converted to this file's types, and its key columns take this file's names.

Conversion is not a step. Import any supported format and export as CSV (with a BOM so spreadsheet apps read it correctly), XLSX, JSON or PDF.

**Split into pages:** a separate tool. It writes one sheet (.xlsx), or one PDF page, per value of a column (A→Z, blanks last, up to 200). It uses `export?split_by=<column>`.

**Charts:** the pivot preview has Table / Chart tabs, with column, bar, line and pie charts drawn as SVG by `static/js/chart.js`, which has no dependencies. Charts download as SVG or PNG and follow the light/dark theme.

## Frontend

There is no build step. The frontend is plain HTML, CSS and JavaScript modules in `gridglass/static/`:

- `index.html` is the app shell. `js/theme.js` sets light or dark mode before the first paint.
- `js/tools.js` is the tool catalogue. For each tool it holds the label, category, icon and option fields, how those fields become an API step, the result title, and the hints shown while options are incomplete.
- `js/app.js` runs the hash router and the screens:
  - home (search and categories)
  - upload (progress bar, sample file)
  - options (live preview, debounced 350 ms)
  - result (download, share, keep working, undo steps)
- `css/app.css` holds the liquid glass styles. Light and dark mode are token sets. There are solid fallbacks for browsers without `backdrop-filter` and for "reduce transparency".
- Motion: screens rise in, tool cards cascade, the result tick pops in and chart bars grow. All of it is off for "reduce motion", and entry animations leave no lasting layers.
- `sw.js` and `manifest.webmanifest` make it an installable PWA with an offline shell. `/api` is never cached.

Security:
- **Content-Security-Policy:** strict; no inline scripts or styles.
- **File deletion:** files are deleted on the server when the user taps Change or Start over.

## API (`/api/v1`)

| Method | Path | Does |
|---|---|---|
| GET | `/tools` | every tool with its category, label and option schema (drives the UI forms) |
| POST | `/files` | upload (multipart `file`, optional `sheet`) → metadata and preview |
| GET / DELETE | `/files/<id>` | metadata and saved steps / delete now |
| PUT | `/files/<id>/sheet` | switch the sheet of a .xlsx/.xls (clears steps) |
| GET | `/files/<id>/preview` | preview with the saved steps. `?limit=&offset=`: 200 rows by default, pages of up to 1,000, browsing up to 10,000 rows |
| POST | `/files/<id>/preview` | live preview of draft `{"steps": [...]}`; nothing saved |
| GET | `/files/<id>/columns` | column stats: type, blanks, distinct values, examples |
| GET | `/files/<id>/values?column=&q=` | a column's distinct values with counts (filter dropdown) |
| PUT / POST / DELETE | `/files/<id>/steps` | replace all / append one / clear |
| DELETE | `/files/<id>/steps/<n>` | remove one step (undo) |
| GET | `/files/<id>/export?format=` | download as `csv`, `xlsx`, `json` or `pdf` |

**Responses**
- Changing steps returns `{"file": ..., "preview": ...}`, so the UI needs one round trip per tap.
- Errors are `{"error": {"code", "message", ...}}`, with these status codes:
  - `400` for a bad file or an invalid step
  - `422` when a step doesn't fit the data; the error includes `step_index`
  - `404` for missing or expired files
  - `413` for files that are too large

**Storage and cleanup**
- Each upload gets an unguessable 22-character id; there are no accounts in v1.
- Files expire after `FILE_RETENTION_MINUTES` (default 60).
- A background thread purges expired files every 5 minutes. Set `CLEANUP_INTERVAL_SECONDS=0` and run `flask --app gridglass purge` from cron instead.
- Export files are deleted as soon as they're sent.

## Deploy

Gridglass ships as one Docker image, with ready configs for Render (`render.yaml`) and Railway (`railway.json`). See **[DEPLOY.md](DEPLOY.md)** for step-by-step setup, settings and production notes.

```bash
docker build -t gridglass . && docker run -p 8000:8000 gridglass   # http://localhost:8000
```

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -m "not e2e"                    # engine + API tests (seconds)
python -m playwright install chromium  # once
pytest -m e2e                          # real-browser tests on phone viewports (~1 min)
flask --app gridglass run --debug      # open http://localhost:5000 on your phone or browser
```

## Tests

| Suite | What it covers |
|---|---|
| `tests/test_steps.py` | every tool, every filter operator, validation messages, chained recipes |
| `tests/test_pipeline.py` | lazy replay, preview and column stats |
| `tests/test_io.py` | every import and export format, messy files (encodings, headers, fake extensions) |
| `tests/test_app.py` | every API endpoint, errors, expiry and cleanup, security headers, app shell |
| `tests/e2e/` | Playwright on emulated phones (iPhone SE, iPhone 14, Pixel 7) and desktop |

What the end-to-end tests check:
- Every tool opens cleanly, and every form control is labelled.
- Real results are verified by downloading and parsing them.
- File behaviour: workbook sheets, bad files, size limits, expired files, and reload persistence.
- Display: dark mode, keyboard use, the service worker, and no sideways scrolling on any device.
- Any JavaScript error fails a test.
- Screenshots of failures are saved to `test-results/`.

CI (`.github/workflows/ci.yml`) runs:
- the unit and API tests on Python 3.11–3.13
- then the browser tests, on every push and pull request.

## Design decisions

- **Polars lazy, not pandas.** It is multi-threaded, uses predicate and projection pushdown, and reads .xlsx quickly through calamine.
- **Pivot collects eagerly.** Its output columns depend on the data, so the engine collects at that step, then returns to lazy. It is capped at 200 new columns.
- **Errors are user-safe.** Each one carries a plain-language message and, for step errors, the index of the step that failed, so the UI can highlight it.
- **No arbitrary expressions or SQL from users.** Every operation is a typed, whitelisted step.
- **Messy files are cleaned on import.** Headers are made unique and non-blank. Windows-1252 CSVs are re-encoded to UTF-8. The separator is auto-detected, and each file's first bytes are checked against its extension.
