# Gridglass

Simple spreadsheet tools for everyone. Pick a tool, upload a CSV or spreadsheet file, preview the change, and download the result.

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
  __init__.py        Flask app factory, app shell, /share, main-address redirect
  api.py             the JSON API under /api/v1
  site.py            information pages, sitemap, robots.txt, ads.txt
  content.py         the words on those pages (tools, guides, search phrases)
  static/            the app: HTML, CSS, JS modules, service worker
  templates/         app shell and information page templates
  config.py          limits: 100 MB uploads, 200-row previews, 1-hour retention …
  engine/
    steps.py         the 19 step types + parse_steps() validation
    health.py        the Check panel's data problems and their fixes
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
| `trim` | `keep_columns` (choose and reorder) | `unpivot`: **Transpose or unpivot** (see below) |
| `change_case` | `rename_columns` | |
| `replace_values` | `filter_rows` (13 operators, all/any) | |
| `fill_blanks` (value, down, up) | `sort_rows` | |
| `remove_blank_rows` | `keep_rows` (top/bottom) | |
| | `change_type` | |
| | `split_column` | |
| | `add_column` (constant, combine, math, part of a text and more, see below) | |

**Search that understands questions (1.16):** the home search box (`static/js/search.js`) ranks tools for questions like "I want to extract a number from text", entirely in the browser.
- Filler words are dropped, endings trimmed and synonyms mapped (extract/get/pull → take, vlookup → lookup, per/by → group).
- Each tool scores by its name, keywords, description and intro; `INTENTS` (everyday tasks) add a strong match, a hint ("Part of a text → Text after “@”") and options to open with.
- Results link to `#/tool/<op>?<field>=<value>`; the options are applied once to the new form (unknown keys and values are ignored). Enter opens the first result; a clear winner gets a "Best match" badge.
- The last word may be unfinished (dup → duplicates); one-letter typos in longer words still match. `test_search_understands_questions` holds the expected answers.

**Add column → Part of a text (1.15):** `mode: "text"` with `left` (any column, read as text) and `func`:
`first` / `last` (`count` characters), `middle` (`start`, 1-based, and `count`), `before` / `after` / `between` (`find_text`, `end_text` for between; `from_end` uses the last match; `if_missing`: `blank` or `all`; `ignore_case`), `word` (`count`, `from_end` counts from the end), `length`, `find` (1-based position, blank if absent) and `pad` (`count`, `pad_with`). Typed text is matched literally, never as a pattern. Results are text, except `length` and `find`.

```json
{"op": "add_column", "name": "Domain", "mode": "text", "left": "Email", "func": "after", "find_text": "@"}
```

**Transpose or unpivot (1.13):** one card, two modes of the `unpivot` step.
- `mode: "transpose"` flips rows and columns. Optional `header` is a column whose values name the new columns (blank → `Column N`, repeats → `Tea (2)`); without it they are `Column 1, 2, 3…`, and the first column (`Field`) lists the old column names. It works on up to 500 rows, since each row becomes a column. All values are flipped as text, then each new column's type is checked again, so numbers stay numbers.
- `mode: "unpivot"` (the default, so older saved steps still work) turns columns into rows: `keep` stays as it is, `columns` (or all the others) become `attribute_name` / `value_name` pairs.

```json
{"op": "unpivot", "mode": "transpose", "header": "Product"}
```

**Combine:** `stack` (below), and `merge`, which brings in columns from a second upload by matching keys (a lookup). It has every join: lookup/left, inner, full outer, right, anti (no match) and semi (has a match).
- It can match on up to 5 key columns.
- "First match only" keeps one match per key when keys repeat.
- The second file's keys are converted to this file's types, and its key columns take this file's names.

**Stack files:** `stack` puts the rows of one or more other uploads under this file.
- Columns match by name, ignoring capitals and extra spaces.
- A column that only some files have is blank in the others; a column whose type differs between files becomes text.
- An optional `source_column` records which file each row came from.

**Numbers and dates as people type them:** on import, `₹1,23,456.50`, `Rs. 500/-`, `$1,234` and `(250)` become numbers, with either Indian or western comma grouping. `05/03/2026`, `5 Mar 2026`, `March 5, 2026` and `05-Mar-26` become dates: day-first, unless the column shows it's month-first; a column with both orders stays text.
- Every cell must fit, and commas must be in the right places, so `1,2,3` stays text.
- The 10-digit and leading-zero rules still apply.
- This tidying only runs on columns the quick type check couldn't type.

**Recipes:** the applied steps can be saved by name (in the browser, on that device) and run on another file from the home screen (`#/recipe/<id>`).
- If a step doesn't fit the new file, the steps before it are kept and the user is told which one stopped.
- Merge and Stack steps are saved without their extra uploads, which expire (`other: null`, `others: [null, …]`; names are kept). When the recipe runs, its screen asks for one file per Merge and one per stacked file ("Last time: towns.csv"), in any order with the main file, and runs once all are in (1.14). The new files' names replace the old ones, so a Stack `source_column` says which new file each row came from.

**Files from other apps:** the installed app accepts files from the phone's share sheet (`share_target` → `POST /share`) and "Open with" on computers (`file_handlers` + `launchQueue`).
- `/share` refuses posts from other websites (`Sec-Fetch-Site`).
- Results land on `#/open/<id>`.

**Header row:** files often start with a title, a date or blank rows above the table. On import, Gridglass finds the first row that fills at least half the table's width, is about as wide as the row below it, and is mostly words, not numbers. Everything above it is skipped. Normal files keep row 1. The **Headers** button on the file card shows the top 20 rows, so the user can tap the right one or choose "No header row" (columns become Column 1, 2, 3…).

Conversion is not a step. Import any supported format and export as CSV (with a BOM so spreadsheet apps read it correctly), XLSX, JSON or PDF.

**Split into pages:** a separate tool. It splits by a column's values (A→Z, blanks last) or every N rows, up to 200 parts, into sheets (.xlsx), PDF pages, or separate CSV/XLSX/PDF files in a .zip. It uses `export?split_by=` / `split_rows=` and `files=1`.

**Options inside tools (1.8):**
- `remove_duplicates` has `action`: `remove`, `show` (every copy of repeated rows) or `mark` (a Yes/No `mark_column`).
- `replace_values` has `action: "clean"` with `clean`: `special`, `digits`, `letters`, `email_domain`, `first_word` or `last_word`.
- `add_column` has the modes `running_total`, `rank` (ties share a rank; `descending`) and `percent` (% of total), each optionally `within` groups.
- `add_column` (1.9) also has `if_then` (`rules`: filter conditions plus `then`, first match wins, and `otherwise`; all-number answers make a number column), `date_part` (`part`: year, month, month_name, quarter, weekday, day, week, year_month, or `fy` for the April–March financial year) and `ranges` (`breaks`, optional `labels`; boundaries go into the higher range).

**Check (1.9):** `GET /files/<id>/health` reports common problems in the data as it is now (after saved steps; `?upto=` works). These are exact copies, blank rows, empty columns, blank cells, stray spaces, the same value written differently, and columns that are almost all numbers. Each comes with a ready step (`fix.step`) or the tool to open (`fix.tool`). The app shows it from **Check** on the file card. The **Headers** picker also works for the second file in Merge and for each file in Stack.

**Charts:** the pivot preview has Table / Chart tabs. Charts are drawn as SVG by `static/js/chart.js`, which has no dependencies.
- Types: column, bar, line, area, pie and donut; several series can be stacked.
- **Customise the chart** (1.10):
  - a title and axis titles
  - colour sets (Gridglass follows light and dark mode; Ocean, Sunset, Forest, Berry and Grey work on both)
  - order (as in table, largest or smallest first, or A → Z)
  - top 5, 10 or 20, with the rest summed as "Other"
  - value labels, legend and grid lines
  - short (1.2L) or full numbers
  - wide, square or tall shape
- Downloads (SVG, or PNG at 2×) match the preview.
- Data labels show any mix of name (pies and donuts only), value and % (1.11; `labelAs` is a list such as `['name', 'percent']`, the pie default). The % is a slice's share on pies; on other charts it's a share of the series, or of the stack when stacked.
- Pivot `filters` (conditions, `filter_match`) limit rows before grouping (1.11).
- Pivot sums, averages and medians are rounded to 2 places (`steps.DECIMALS`), and after a pivot every decimal is shown with exactly 2 places, in the preview and in CSV (`float_precision`), XLSX (`0.00` format) and PDF downloads (1.14). Other files keep numbers exactly as they are.
- The **Make a chart** card (`op: 'chart'`, `opens: 'pivot'`) opens the Pivot table tool on its Chart tab.

## Frontend

There is no build step. The frontend is plain HTML, CSS and JavaScript modules in `gridglass/static/`, with the app shell in `gridglass/templates/app.html`:

- `templates/app.html` is the app shell. `js/theme.js` sets light or dark mode before the first paint.
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
| GET | `/files/<id>/top` | the first 20 rows exactly as in the file, to choose the header row |
| PUT | `/files/<id>/header` | `{"row": n}` uses row n (0 = first) as column names; `{"row": null}` means no header row (clears steps) |
| GET | `/files/<id>/preview` | preview with the saved steps. `?limit=&offset=`: 200 rows by default, pages of up to 1,000, browsing up to 10,000 rows |
| POST | `/files/<id>/preview` | live preview of draft `{"steps": [...]}`; nothing saved |
| GET | `/files/<id>/columns` | column stats: type, blanks, distinct values, examples |
| GET | `/files/<id>/values?column=&q=` | a column's distinct values with counts (filter dropdown) |
| PUT / POST / DELETE | `/files/<id>/steps` | replace all / append one / clear |
| DELETE | `/files/<id>/steps/<n>` | remove one step (undo) |
| GET | `/files/<id>/export?format=` | download as `csv`, `xlsx`, `json` or `pdf`. Optional: `split_by=<column>` or `split_rows=N` (one sheet/page per part), `files=1` (separate files in a .zip), `columns=` (repeatable), and for PDFs `orientation=auto\|portrait\|landscape` and `title=` |

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

## Information pages

Server-rendered pages (Jinja, `gridglass/site.py`, `templates/site/`, words in `gridglass/content.py`) for search engines and people deciding whether to use a tool:
- `/tools` and `/tools/<slug>`: one page per tool, with what it does, when to use it, steps, an example, options, FAQs and related tools.
- `/guides/<slug>`: how-tos.
- `/about`, `/contact`, `/privacy` and `/terms`.
- `/sitemap.xml`, `/robots.txt` and `/ads.txt`.
- Moved pages forward permanently (301) through `content.MOVED`, e.g. `/tools/unpivot` → `/tools/transpose`.

**One search per tool page (1.12):** `content.SEARCH` gives each tool page the phrase people type, such as "Merge two CSV files by a common column". The phrase is the `<title>`, the `<h1>`, the start of the meta description and part of the first paragraph; tests check all four and that no two pages share a phrase.

**Naming other products (1.12):**
- Information pages may name other products (Excel, VLOOKUP, Google Sheets) in plain text, to say truthfully what files and tasks Gridglass handles, e.g. "Excel files work too".
- They are never used in our tool names, the site name or the domain, never with their logos, and never in a way that suggests endorsement.
- Every page that names one carries `content.TRADEMARKS` in the footer (the Terms page has it too).
- The app's own screens stay neutral.

Tool icons and short descriptions are read from `static/js/tools.js`, so they never drift from the app. With `ADSENSE_CLIENT` set, these pages load ads under a nonce-based CSP (`'strict-dynamic'`); the app itself keeps the strict CSP and never loads ad code.

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
| `tests/test_site.py` | information pages, search phrases, trademark notice, sitemap, redirects, ad isolation |
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
- **Column types come from every row, not a sample.** Files are read as text first, then a column becomes a number, date or true/false only if every cell fits. Whole numbers longer than 10 digits (card and transaction IDs) and numbers with leading zeros stay text, so no digit is ever lost — spreadsheet apps keep only 15 digits of a number.
- **Messy files are cleaned on import.** Headers are made unique and non-blank. Windows-1252 CSVs are re-encoded to UTF-8. The separator is auto-detected, and each file's first bytes are checked against its extension.
