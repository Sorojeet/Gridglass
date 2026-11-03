import {
  AGG_FUNCS, CATS, FORMATS, JOINS, NO_VALUE_OPS, OPERATORS, PAGE, TOOL, TOOLS, TYPES, UI, defaults, icon, incomplete, suggestFor,
  toDraft, toStep,
} from './tools.js';
import { DEFAULT_OPTIONS, MAX_CATEGORIES, PALETTES, arrange, chartData, chartSVG, labelParts, saveChart, themeColors } from './chart.js';

const API = '/api/v1';
const desktop = window.matchMedia('(min-width: 1024px)');
// Quick preview: 50 rows on phones, 200 on desktop. "Show all rows" pages through up to 10k, 1,000 at a time.
const previewRows = () => (state.browse.all ? config.page_rows : desktop.matches ? 200 : 50);
const $ = (s, el = document) => el.querySelector(s);
const view = $('#view');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const num = (x) => Number(x).toLocaleString('en-IN');
const plural = (k, w) => `${num(k)} ${w}${k === 1 ? '' : 's'}`;
const ui = (name, cls) => icon(UI[name], cls);

const config = { max_upload_mb: 100, retention_minutes: 60, page_rows: 1000, browse_max_rows: 10000 };
const state = {
  file: null,      // server metadata of the current upload (id, filename, steps …)
  cols: [],        // column stats after the saved steps
  tool: null,
  stage: 'upload', // upload | options | done
  draft: {},
  before: 0,       // rows before the step being designed
  result: null,    // { before, after, op } after applying
  previewOk: false,
  browse: { all: false, page: 0 }, // paged "show all rows" mode in the preview
  values: {},      // column -> distinct values for the filter dropdown
  editIndex: null, // editing saved step n (null = adding a new step at the end)
  wantChart: false, // open the pivot editor on its Chart tab
  other: null,     // Merge: metadata of the second file
  otherCols: [],   // Merge: its columns
  view: 'table',   // Pivot preview: table | chart
  split: null,     // Split into pages: { column, format, pages }
  chart: { ...DEFAULT_OPTIONS }, // chart look: type, titles, colours, labels…
  alias: null,     // a card that opens another tool (Make a chart -> Pivot table, on its Chart tab)
  pvData: null,    // the preview on screen, for the chart
};
const ACCEPT = '.csv,.tsv,.txt,.xlsx,.xlsm,.xls,.json,.jsonl,.ndjson';

// ============================================================================ API

class ApiError extends Error {
  constructor(info, status) {
    super(info?.message || 'Something went wrong. Please try again.');
    this.info = info || {};
    this.status = status;
  }
}

async function api(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(API + path, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError({ message: "Can't reach Gridglass. Check your internet connection." }, 0);
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(data?.error, res.status);
  return data;
}

function uploadFile(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append('file', file, file.name);
    xhr.open('POST', `${API}/files`);
    xhr.responseType = 'json';
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300
      ? resolve(xhr.response) : reject(new ApiError(xhr.response?.error, xhr.status)));
    xhr.onerror = () => reject(new ApiError({ message: "Upload failed. Check your connection and try again." }, 0));
    xhr.send(form);
  });
}

// ============================================================================ theme, toast, boot

function setTheme(theme, save = true) {
  document.documentElement.dataset.theme = theme;
  if (save) try { localStorage.setItem('gg.theme', theme); } catch { /* private mode */ }
  $('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#070B12' : '#EEF3F6');
  document.querySelectorAll('[data-action="theme"]').forEach((b) =>
    b.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'));
  if (state.view === 'chart' && $('#chart')) requestAnimationFrame(renderChart);
}

let toastTimer;
function toast(message, kind = 'info') {
  const el = $('#toast');
  el.textContent = message;
  el.dataset.kind = kind;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4200);
}

function remember(file) {
  if (file?.id !== state.file?.id || file?.steps.length !== state.file?.steps.length) state.values = {};
  state.file = file;
  try {
    if (file) sessionStorage.setItem('gg.file', file.id); else sessionStorage.removeItem('gg.file');
  } catch { /* storage blocked */ }
}

async function boot() {
  setTheme(document.documentElement.dataset.theme, false);
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-action="theme"]')) {
      setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    }
  });
  api('/config').then((c) => Object.assign(config, c)).catch(() => {});
  let saved = null;
  try { saved = sessionStorage.getItem('gg.file'); } catch { /* ignore */ }
  if (saved) {
    try { remember((await api(`/files/${saved}`)).file); } catch { remember(null); }
  }
  window.addEventListener('hashchange', route);
  route();
  // Installed on a computer: "Open with Gridglass" on a CSV or spreadsheet file lands here.
  if ('launchQueue' in window) {
    window.launchQueue.setConsumer(async ({ files }) => {
      if (!files?.length) return;
      try { await openFromDevice(await files[0].getFile()); } catch (err) { toast(err.message, 'error'); }
    });
  }
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// ============================================================================ routing & shared bits

/** Steps the tool being edited builds on: all of them, or only those before the step being edited. */
const baseSteps = () => (state.editIndex === null ? state.file.steps : state.file.steps.slice(0, state.editIndex));
const upto = () => (state.editIndex === null ? '' : `upto=${state.editIndex}`);

let firstRoute = true;

function route() {
  const h = location.hash;
  if (h.startsWith('#/open')) { openShared(h); return; }
  const tool = h.match(/^#\/tool\/([a-z_]+)/);
  const edit = h.match(/^#\/edit\/(\d+)$/);
  const recipe = h.match(/^#\/recipe\/([\w-]+)$/);
  if (recipe) { renderRecipe(recipe[1]); return finishRoute(); }
  leaveRecipe();
  if (h === '#/result' && state.file) showResult();
  else if (edit && state.file) editStep(Number(edit[1]));
  else if (tool && TOOL[tool[1]]) openTool(TOOL[tool[1]]);
  else renderHome();
  finishRoute();
}

function finishRoute() {
  window.scrollTo(0, 0);
  // Move focus to the new screen for screen readers, but not on first load (keeps "Skip to content" first).
  if (!firstRoute) view.focus({ preventScroll: true });
  firstRoute = false;
}

const helpFor = (t) => (PAGE[t.op] ? { slug: PAGE[t.op], label: t.label } : null);

function topbar({ back, title, close, edit, help, guides } = {}) {
  const left = edit
    ? `<a class="icon-btn" href="${edit}" aria-label="Back to the editor">${ui('back')}</a><span class="topbar-title">${esc(title)}</span>`
    : back
    ? `<a class="icon-btn" href="${back}" aria-label="Back">${ui('back')}</a><span class="topbar-title">${esc(title)}</span>`
    : close
      ? `<span class="topbar-title">${esc(title || '')}</span>`
      : `<a class="brand" href="#/" aria-label="Gridglass home">${logo()}<span>Gridglass</span></a>`;
  const right = close ? `<a class="icon-btn" href="${close}" aria-label="Close">${ui('close')}</a>` : '';
  const label = document.documentElement.dataset.theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
  const aid = help
    ? `<a class="icon-btn glass" href="/tools/${help.slug}" aria-label="How to use ${esc(help.label)}" title="How to use ${esc(help.label)}">${ui('help')}</a>`
    : guides ? `<a class="top-link glass" href="/guides">${ui('help')}<span>Guides</span></a>` : '';
  return `<header class="topbar">${left}<span class="spacer"></span>${aid}
    <button class="icon-btn glass theme-btn" type="button" data-action="theme" aria-label="${label}">${ui('moon', 'when-light')}${ui('sun', 'when-dark')}</button>${right}</header>`;
}

const logo = () => `<svg class="logo" viewBox="0 0 30 30" aria-hidden="true"><rect x="1" y="1" width="28" height="28" rx="8"/><path d="M8 11h14M8 15.5h14M8 20h14M12.5 8v14M17.5 8v14"/></svg>`;
const privacy = () => `<footer class="privacy">${ui('lock')}<span>Your files are private and deleted automatically after ${config.retention_minutes} minutes.</span></footer>
  <nav class="app-links" aria-label="More"><a href="/tools">Tool guides</a><a href="/guides">How-tos</a><a href="/about">About</a><a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/contact">Contact</a></nav>`;

function fileChip() {
  const f = state.file;
  const sheets = f.sheets?.length > 1
    ? `<label class="sr-only" for="sheet">Sheet</label><select id="sheet" class="input input-sm">${f.sheets.map((s) =>
      `<option ${s === f.sheet ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select>` : '';
  return `<div class="file-chip glass">
    <span class="file-icon">${ui('file')}</span>
    <span class="file-text"><strong>${esc(f.filename)}</strong><small>${plural(state.before, 'row')} · ${plural(state.cols.length, 'column')}${
      state.editIndex !== null ? ` · editing step ${state.editIndex + 1} of ${f.steps.length}`
        : f.steps.length ? ` · ${plural(f.steps.length, 'step')} applied` : ''}${headerNote(f)}</small></span>
    <span class="file-actions">${sheets}
    <button class="btn-link" type="button" data-action="check" aria-expanded="false" aria-controls="health">Check</button>
    ${hasHeaderRow(f) ? `<button class="btn-link" type="button" data-action="headers" aria-expanded="false" aria-controls="header-pick">Headers</button>` : ''}
    <button class="btn-link" type="button" data-action="newfile">Change</button></span>
  </div>
  <section class="header-pick glass" id="header-pick" aria-labelledby="header-pick-title" hidden></section>
  <section class="health glass" id="health" aria-labelledby="health-title" hidden></section>`;
}

const HEADER_FORMATS = ['csv', 'tsv', 'xlsx', 'xls'];
const hasHeaderRow = (f) => HEADER_FORMATS.includes(f.format ?? (f.name || f.filename || '').split('.').pop().toLowerCase());

/** "· 3 top rows skipped" / "· no header row": what Gridglass did with the top of the file. */
function headerNote(f) {
  if (!hasHeaderRow(f)) return '';
  if (f.header_row === null) return ' · no header row';
  return f.header_row > 0 ? ` · ${plural(f.header_row, 'top row')} skipped` : '';
}

// ---------------------------------------------------------------------------- header row

/** Open or close a header-row picker in `panel` for the upload `fileId`; `then(meta, row)` runs after a pick. */
async function toggleHeaderPanel(panel, btn, fileId, { steps = 0, then }) {
  if (!panel.hidden) { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); return; }
  btn.setAttribute('aria-expanded', 'true');
  panel.hidden = false;
  panel.innerHTML = '<p class="hint">Reading the top of the file…</p>';
  panel.pick = { fileId, then };
  panel.onclick = pickHeader;
  try {
    const { rows, header_row: current } = await api(`/files/${fileId}/top`);
    const cells = (r) => {
      const filled = r.filter((v) => v !== null);
      return filled.length
        ? filled.slice(0, 6).map((v) => `<span>${esc(v.length > 24 ? `${v.slice(0, 23)}…` : v)}</span>`).join('') + (filled.length > 6 ? `<span>+${filled.length - 6}</span>` : '')
        : '<em>blank row</em>';
    };
    panel.innerHTML = `
      <h2 id="${panel.id}-title">Which row has the column names?</h2>
      <p class="hint">Tap it. Rows above it are skipped.${steps ? ` Your ${plural(steps, 'applied step')} will be cleared.` : ''}</p>
      <ol class="hp-rows">${rows.map((r, i) => `<li><button type="button" class="hp-row" data-row="${i}" aria-pressed="${i === current}"
        aria-label="Row ${i + 1}${i === current ? ' (current headers)' : ''}: ${esc(r.filter((v) => v !== null).slice(0, 6).join(', ') || 'blank row')}">
        <b>${i + 1}</b><span class="hp-cells">${cells(r)}</span></button></li>`).join('')}</ol>
      <button type="button" class="btn btn-secondary btn-sm" data-row="none" aria-pressed="${current === null}">No header row (name them Column 1, 2, 3…)</button>`;
    panel.querySelector('[aria-pressed="true"]')?.focus();
  } catch (err) {
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    toast(err.message, 'error');
  }
}

function toggleHeaders() {
  closePanels('#header-pick');
  return toggleHeaderPanel($('#header-pick'), $('[data-action="headers"]'), state.file.id, {
    steps: state.file.steps.length,
    then: async (meta) => { remember(meta); await enterOptions(); },
  });
}

async function pickHeader(e) {
  const panel = e.currentTarget;
  const pick = e.target.closest('[data-row]');
  if (!pick || pick.getAttribute('aria-pressed') === 'true') return;
  e.stopPropagation(); // the panel may sit inside the options form
  const row = pick.dataset.row === 'none' ? null : Number(pick.dataset.row);
  panel.querySelectorAll('button').forEach((b) => { b.disabled = true; });
  try {
    const res = await api(`/files/${panel.pick.fileId}/header`, { method: 'PUT', body: { row } });
    await panel.pick.then(res.file, row);
    toast(row === null ? 'Columns are now named Column 1, 2, 3…' : `Using row ${row + 1} as the column names.`);
  } catch (err) {
    panel.querySelectorAll('button').forEach((b) => { b.disabled = false; });
    toast(err.message, 'error');
  }
}

/** Only one panel under the file card at a time. */
function closePanels(except) {
  ['#header-pick', '#health'].filter((sel) => sel !== except).forEach((sel) => {
    const panel = $(sel);
    if (panel && !panel.hidden) {
      panel.hidden = true;
      $(`[aria-controls="${panel.id}"]`)?.setAttribute('aria-expanded', 'false');
    }
  });
}

// ---------------------------------------------------------------------------- data health check

async function toggleHealth() {
  const panel = $('#health');
  const btn = $('[data-action="check"]');
  if (!panel.hidden) { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); return; }
  closePanels('#health');
  btn.setAttribute('aria-expanded', 'true');
  panel.hidden = false;
  panel.innerHTML = '<p class="hint">Checking every row…</p>';
  try {
    const report = await api(`/files/${state.file.id}/health?${upto()}`);
    renderHealth(panel, report);
  } catch (err) {
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    toast(err.message, 'error');
  }
}

function renderHealth(panel, report) {
  const editing = state.editIndex !== null; // fixes would land after later steps, so only point to tools
  const fix = (it, i) => (it.fix.step && !editing
    ? `<button type="button" class="btn btn-primary btn-sm" data-fix="${i}">${esc(it.fix.label)}</button>`
    : it.fix.tool && TOOL[it.fix.tool] ? `<a class="btn btn-secondary btn-sm" href="#/tool/${it.fix.tool}">Open ${esc(TOOL[it.fix.tool].label)}</a>` : '');
  const examples = (it) => {
    if (!it.examples?.length) return '';
    const shown = it.examples.map((x) => (Array.isArray(x) ? x.map((v) => `“${esc(v)}”`).join(' = ') : `“${esc(x)}”`));
    return `<p class="health-eg">For example: ${shown.join(' · ')}</p>`;
  };
  panel.innerHTML = `
    <h2 id="health-title">Check this file</h2>
    <p class="hint">Looked at all ${plural(report.rows, 'row')} and ${plural(report.columns.length, 'column')}.</p>
    ${report.issues.length ? `<ul class="health-list">${report.issues.map((it, i) => `<li class="health-item">
        <span class="health-dot" aria-hidden="true"></span>
        <div class="health-body"><p>${esc(it.message)}</p>${examples(it)}<div class="health-fix">${fix(it, i)}</div></div></li>`).join('')}</ul>`
      : `<p class="health-ok">${ui('check')} No common problems found.</p>`}
    <details class="health-cols"><summary>Column details</summary>
      <div class="table-wrap"><table><thead><tr><th scope="col">Column</th><th scope="col">Type</th><th scope="col">Blank</th><th scope="col">Different values</th></tr></thead>
      <tbody>${report.columns.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.type)}</td><td>${num(c.blanks)}</td><td>${num(c.distinct)}</td></tr>`).join('')}</tbody></table></div>
    </details>`;
  panel.onclick = async (e) => {
    const b = e.target.closest('[data-fix]');
    if (!b) return;
    const it = report.issues[Number(b.dataset.fix)];
    await withBusy(b, async () => {
      const res = await api(`/files/${state.file.id}/steps`, { method: 'POST', body: it.fix.step });
      remember(res.file);
      state.result = null;
      await enterOptions();
      toast(`${it.fix.label}: done. You can undo it on the result screen.`);
      await toggleHealth();
    });
  };
}
/** After a pivot table, decimals show with exactly this many places (236.50), as the downloads do. */
const PIVOT_DECIMALS = 2;

function table(pv, decimals = null) {
  if (!pv.columns.length) return '<p class="empty">No columns left.</p>';
  const head = pv.columns.map((c) => `<th scope="col"><span>${esc(c.name)}</span><small>${esc(c.type)}</small></th>`).join('');
  const fixed = pv.columns.map((c) => decimals !== null && c.type === 'decimal');
  const show = (v, i) => (typeof v === 'boolean' ? (v ? 'true' : 'false') : fixed[i] && typeof v === 'number' ? v.toFixed(decimals) : v);
  const body = pv.rows.length
    ? pv.rows.map((r) => `<tr>${r.map((v, i) => (v === null
      ? '<td class="null"><span class="sr-only">blank</span></td>'
      : `<td title="${esc(show(v, i))}">${esc(show(v, i))}</td>`)).join('')}</tr>`).join('')
    : `<tr><td class="empty" colspan="${pv.columns.length}">No rows match.</td></tr>`;
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

// ============================================================================ home

let homeQuery = '';
let homeCat = 'all';

function renderHome() {
  state.tool = null;
  document.title = 'Gridglass — simple spreadsheet tools';
  const working = state.file ? `<div class="working glass">
      <span class="file-icon">${ui('file')}</span>
      <span class="file-text"><strong>${esc(state.file.filename)}</strong><small>${state.file.steps.length ? `${plural(state.file.steps.length, 'step')} applied · ` : ''}pick any tool to keep going</small></span>
      <a class="btn btn-secondary btn-sm" href="#/result">${ui('download')} Back to result</a>
      <button class="btn-link" type="button" data-action="startover">Clear</button>
    </div>` : '';
  view.dataset.screen = 'home';
  view.innerHTML = `${topbar({ guides: true })}
    <section class="hero">
      <h1>Every spreadsheet tool you need, one tap away.</h1>
      <p>Clean, reshape and convert CSV and spreadsheet files on your phone or computer. Free, no sign-up.</p>
    </section>
    ${working}
    ${recipesSection()}
    <div class="search glass">${ui('search')}
      <label class="sr-only" for="q">Search tools</label>
      <input id="q" type="search" placeholder="Search tools, e.g. duplicates" value="${esc(homeQuery)}" autocomplete="off">
    </div>
    <nav class="chips" aria-label="Tool categories">
      ${[['all', 'All'], ...Object.entries(CATS)].map(([k, l]) =>
        `<button type="button" class="chip" data-cat="${k}" aria-pressed="${k === homeCat}">${l}</button>`).join('')}
    </nav>
    <section class="tool-grid" id="grid" aria-label="Tools"></section>
    ${privacy()}`;
  fillGrid();
  $('#q').addEventListener('input', (e) => { homeQuery = e.target.value; fillGrid(); });
  view.querySelectorAll('[data-cat]').forEach((b) => b.addEventListener('click', () => {
    homeCat = b.dataset.cat;
    view.querySelectorAll('[data-cat]').forEach((x) => x.setAttribute('aria-pressed', x === b));
    fillGrid();
  }));
  $('[data-action="startover"]')?.addEventListener('click', startOver);
  $('#recipes')?.addEventListener('click', onRecipeClick);
  $('#recipes')?.addEventListener('submit', onRecipeRename);
}

function fillGrid() {
  const q = homeQuery.trim().toLowerCase();
  const list = TOOLS.filter((t) => (homeCat === 'all' || t.cat === homeCat)
    && (!q || `${t.label} ${t.desc} ${t.keywords}`.toLowerCase().includes(q)));
  $('#grid').innerHTML = list.length ? list.map((t) => `
    <a class="tool-card glass" href="#/tool/${t.op}">
      <span class="tool-icon cat-${t.cat}">${icon(t.icon)}</span>
      <span class="tool-name">${t.label}</span>
      <span class="tool-desc">${t.desc}</span>
    </a>`).join('') : `<p class="empty">No tool matches “${esc(q)}”.</p>`;
}

// ============================================================================ tool flow

async function openTool(tool) {
  state.alias = tool.opens ? tool : null;
  tool = tool.opens ? TOOL[tool.opens] : tool;
  state.tool = tool;
  state.editIndex = null;
  state.values = {};
  state.result = null;
  document.title = `${tool.label} — Gridglass`;
  if (state.file) await enterOptions();
  else renderUpload();
}

// ---------------------------------------------------------------------------- upload

function renderUpload() {
  const t = state.tool;
  state.stage = 'upload';
  view.dataset.screen = 'upload';
  const shown = state.alias ?? t;
  view.innerHTML = `${topbar({ back: '#/', title: 'All tools', help: helpFor(shown) })}
    <section class="intro">
      <span class="badge cat-${shown.cat}">${CATS[shown.cat]}</span>
      <h1>${shown.label}</h1>
      <p>${shown.intro}</p>
      ${PAGE[shown.op] ? `<a class="intro-link" href="/tools/${PAGE[shown.op]}">${ui('help')} How it works, with an example</a>` : ''}
    </section>
    <section class="dropzone glass" id="drop">
      <span class="drop-icon">${ui('upload')}</span>
      <label class="btn btn-primary btn-lg" for="file">Choose a file</label>
      <input id="file" class="sr-only" type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.json,.jsonl,.ndjson">
      <p class="hint">CSV, XLSX or JSON · up to ${config.max_upload_mb} MB</p>
      <div class="progress" id="progress" hidden><div class="bar"><span id="bar"></span></div><p id="ptext" aria-live="polite">Uploading…</p></div>
    </section>
    <button class="btn btn-secondary btn-block" type="button" data-action="sample">${ui('sample')} Try a sample file</button>
    <section class="how">
      <h2>How it works</h2>
      <ol>
        <li><span>1</span>Pick your file — nothing is changed yet.</li>
        <li><span>2</span>Choose the options and watch the preview update.</li>
        <li><span>3</span>Download the result, or send it to another tool.</li>
      </ol>
    </section>
    ${privacy()}`;
  const input = $('#file');
  input.addEventListener('change', () => input.files[0] && startUpload(input.files[0]));
  $('[data-action="sample"]').addEventListener('click', () => startUpload(sampleFile()));
  const drop = $('#drop');
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove('over')));
  drop.addEventListener('drop', (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) startUpload(f); });
}

async function startUpload(file) {
  if (file.size > config.max_upload_mb * 1024 * 1024) {
    toast(`That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is ${config.max_upload_mb} MB.`, 'error');
    return;
  }
  const progress = $('#progress');
  progress.hidden = false;
  view.querySelectorAll('.dropzone label, [data-action="sample"]').forEach((el) => el.classList.add('busy'));
  try {
    const res = await uploadFile(file, (p) => {
      $('#bar').style.width = `${Math.round(p * 100)}%`;
      $('#ptext').textContent = p < 1 ? `Uploading… ${Math.round(p * 100)}%` : 'Reading your file…';
    });
    remember(res.file);
    await enterOptions();
    if (res.file.header_row > 0) {
      toast(`Skipped ${plural(res.file.header_row, 'row')} above the column names. Tap Headers to change.`);
    }
  } catch (err) {
    progress.hidden = true;
    view.querySelectorAll('.busy').forEach((el) => el.classList.remove('busy'));
    $('#file').value = '';
    toast(err.message, 'error');
  }
}

function sampleFile(name = 'sample-orders.csv', start = 1) {
  const rows = [['Order ID', 'Customer', 'Email', 'City', 'Amount', 'Order date']];
  const people = [['  Asha Rao ', 'asha@example.com'], ['Ravi Kumar', 'ravi@example.com'], ['meera iyer', 'meera@example.com'],
    ['Dev Singh', 'dev@example.com'], ['', ''], ['Priya  Nair', 'priya@example.com']];
  const cities = ['Pune', 'Delhi', 'Mumbai', 'Bengaluru', 'Chennai'];
  for (let i = start; i < start + 40; i += 1) {
    const [person, email] = people[i % people.length];
    rows.push([1000 + i, person, email, cities[(i * 7) % cities.length], (i * 137.5) % 900 + 99,
      `2026-${String((i % 9) + 1).padStart(2, '0')}-${String((i % 27) + 1).padStart(2, '0')}`]);
    if (i % 8 === 0) rows.push([...rows.at(-1)]); // a few exact duplicates
  }
  const csv = rows.map((r) => r.map((v) => (/[",]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v)).join(',')).join('\n');
  return new File([csv], name, { type: 'text/csv' });
}

// ---------------------------------------------------------------------------- options

async function enterOptions() {
  try {
    state.cols = (await api(`/files/${state.file.id}/columns`)).columns;
  } catch (err) {
    if (err.status === 404) { remember(null); toast('That file has expired. Please upload it again.', 'error'); renderUpload(); return; }
    // a saved step stopped fitting (rare): still let the user continue from the raw data
    toast(err.message, 'error');
    state.cols = [];
  }
  state.before = state.cols[0]?.rows ?? state.file.rows;
  state.draft = defaults(state.tool, state.cols);
  if (state.tool.op === 'stack') state.draft.this_name = state.file.filename;
  state.browse = { all: false, page: 0 };
  state.other = null;
  state.otherCols = [];
  state.view = state.alias ? 'chart' : 'table';
  renderOptions();
}

function renderOptions() {
  const t = state.tool;
  state.stage = 'options';
  view.dataset.screen = 'options';
  const action = t.convert ? downloadFields('Save as', { columns: true }) : t.splitter ? splitFields() : '';
  const pivot = t.op === 'pivot';
  const chart = pivot && state.view === 'chart';
  const editing = state.editIndex !== null;
  const shown = !editing && state.alias ? state.alias : t;
  view.innerHTML = `${topbar({ back: editing ? '#/result' : '#/', title: editing ? `Edit: ${t.label}` : shown.label, help: helpFor(shown) })}
    ${fileChip()}
    ${t.convert || t.splitter ? '' : `<form id="opts" class="form" novalidate autocomplete="off"></form>`}
    ${action}
    <section class="preview" aria-labelledby="pv-title">
      <div class="preview-head"><h2 id="pv-title">Preview</h2>
        ${pivot ? `<div class="tabs" role="tablist" aria-label="Show the result as">
          <button type="button" role="tab" id="tab-table" aria-controls="pv" aria-selected="${!chart}" tabindex="${chart ? -1 : 0}">Table</button>
          <button type="button" role="tab" id="tab-chart" aria-controls="chart-panel" aria-selected="${chart}" tabindex="${chart ? 0 : -1}">Chart</button>
        </div>` : ''}
        <span class="pill" id="pv-badge" aria-live="polite"></span></div>
      <div class="table-wrap glass" id="pv" tabindex="0" aria-label="Preview table" ${pivot ? 'role="tabpanel" aria-labelledby="tab-table"' : ''} ${chart ? 'hidden' : ''}><div class="skeleton"></div></div>
      ${pivot ? `<div class="chart-panel glass" id="chart-panel" role="tabpanel" aria-labelledby="tab-chart" ${chart ? '' : 'hidden'}>
        <div class="chart-types">${seg('charttype', CHART_TYPES, state.chart.type, 'Chart type')}</div>
        <div class="chart-stick"><div class="chart" id="chart"></div></div>
        <p class="hint" id="chart-note"></p>
        ${chartCustomiser()}
        <div class="chart-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-chart-save="png">${ui('download')} PNG</button>
          <button type="button" class="btn btn-secondary btn-sm" data-chart-save="svg">${ui('download')} SVG</button>
        </div>
      </div>` : ''}
      <div class="pager" id="pv-pager" ${chart ? 'hidden' : ''}></div>
      <p class="hint" id="pv-note"></p>
    </section>
    <div class="action-bar">
      ${t.convert || t.splitter
        ? `<button class="btn btn-primary btn-lg btn-block" type="button" data-action="download">${ui('download')} Download</button>`
        : `<button class="btn btn-primary btn-lg btn-block" type="button" id="apply" disabled>${esc(editing ? 'Save changes' : t.verb)}</button>`}
    </div>`;
  $('[data-action="newfile"]').addEventListener('click', newFile);
  $('[data-action="headers"]')?.addEventListener('click', toggleHeaders);
  $('[data-action="check"]').addEventListener('click', toggleHealth);
  $('#sheet')?.addEventListener('change', (e) => changeSheet(e.target.value));
  $('#pv-pager').addEventListener('click', onPager);
  if (pivot) wireChart();
  if (t.convert || t.splitter) {
    if (t.convert) wireDownload(); else wireSplit();
    showPreview(state.file.steps);
    return;
  }
  const form = $('#opts');
  renderForm();
  form.addEventListener('input', onFormInput);
  form.addEventListener('change', onFormInput);
  form.addEventListener('click', onFormClick);
  form.addEventListener('mousedown', (e) => { if (e.target.closest('.combo-list')) e.preventDefault(); }); // keep focus in the box
  form.addEventListener('focusin', (e) => { if (e.target.getAttribute('role') === 'combobox') comboOpen(e.target); });
  form.addEventListener('focusout', (e) => {
    const combo = e.target.closest('.combo');
    if (combo) setTimeout(() => { if (!combo.contains(document.activeElement)) comboClose($('[role="combobox"]', combo)); }, 120);
  });
  form.addEventListener('keydown', onComboKey);
  form.addEventListener('submit', (e) => e.preventDefault());
  $('#apply').addEventListener('click', apply);
  schedulePreview(0);
}

/** The format picker shared by Convert and the result screen. */
function downloadFields(label = 'Download as', { columns = false } = {}) {
  const stem = state.file.filename.replace(/\.[^.]+$/, '');
  return `<div class="field"><label class="field-label" for="fmt">${label}</label>${formatSelect()}</div>
    <div class="pdf-opts" id="pdf-opts" hidden>
      <div class="field"><span class="field-label">Page</span>
        ${seg('orient', [['auto', 'Auto'], ['portrait', 'Portrait'], ['landscape', 'Landscape']], 'auto', 'Page orientation')}</div>
      <div class="field"><label class="field-label" for="pdf-title">Title on the first page</label>
        <input class="input" id="pdf-title" maxlength="120" placeholder="${esc(stem)}" autocomplete="off"></div>
      ${columns && state.cols.length ? `<div class="field"><span class="field-label">Columns</span>
        ${seg('pdfcols', [['all', 'All columns'], ['some', 'Choose columns']], 'all', 'Columns in the PDF')}
        <div class="col-chips" id="pdf-cols" hidden>${state.cols.map((c) => `<button type="button" class="col-chip"
          data-pdfcol="${esc(c.name)}" aria-pressed="true"><span>${esc(c.name)}</span><small>${c.type}</small></button>`).join('')}</div></div>` : ''}
    </div>`;
}

/** Seg buttons outside the options form: keep one pressed per group. */
function pressSeg(b) {
  b.closest('.seg').querySelectorAll('[data-seg]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
}

function wireDownload() {
  const fmt = $('#fmt');
  const box = $('#pdf-opts');
  const sync = () => { box.hidden = fmt.value !== 'pdf'; };
  fmt.addEventListener('change', sync);
  sync();
  box.addEventListener('click', (e) => {
    const b = e.target.closest('[data-seg], [data-pdfcol]');
    if (!b) return;
    if (b.dataset.pdfcol) { b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true')); return; }
    pressSeg(b);
    if (b.dataset.seg === 'pdfcols') $('#pdf-cols').hidden = b.dataset.val !== 'some';
  });
  const opts = () => {
    if (fmt.value !== 'pdf') return {};
    const o = { orientation: $('#pdf-opts [data-seg="orient"][aria-pressed="true"]').dataset.val, title: $('#pdf-title').value.trim() };
    if ($('#pdf-cols') && !$('#pdf-cols').hidden) {
      o.columns = [...view.querySelectorAll('[data-pdfcol][aria-pressed="true"]')].map((b) => b.dataset.pdfcol);
      if (!o.columns.length) throw new ApiError({ message: 'Choose at least one column for the PDF.' }, 0);
    }
    return o;
  };
  $('[data-action="download"]').addEventListener('click', (e) => download(fmt.value, e.currentTarget, opts));
  $('[data-action="share"]')?.addEventListener('click', (e) => share(fmt.value, e.currentTarget, opts));
}

const pageColumns = () => state.cols.filter((c) => c.distinct >= 1 && c.distinct <= 200);
const MAX_PARTS = 200;
const PART = { xlsx: 'sheet', pdf: 'page', zip: 'file' };

function splitFields() {
  const usable = pageColumns();
  const pick = usable.find((c) => c.type === 'text') ?? usable[0];
  const old = state.split ?? {};
  state.split = { by: old.by ?? (usable.length ? 'column' : 'rows'), column: pick?.name ?? '', rows: old.rows ?? 10000,
    format: old.format ?? 'xlsx', fileType: old.fileType ?? 'csv', pages: 0 };
  const sp = state.split;
  return `<div class="field" id="split-by"><span class="field-label">Split</span>
      ${seg('splitby', [['column', 'By a column'], ['rows', 'Every N rows']], sp.by, 'Split')}</div>
    <div class="field" id="split-col" ${sp.by === 'column' ? '' : 'hidden'}>
      <label class="field-label" for="split">One part for each value of</label>
      ${usable.length ? `<select id="split" class="input">${usable.map((c) =>
        `<option value="${esc(c.name)}" ${c === pick ? 'selected' : ''}>${esc(c.name)} — ${plural(c.distinct, 'value')}</option>`).join('')}</select>`
        : `<p class="hint">No column has between 1 and ${MAX_PARTS} different values to split by.</p>`}
    </div>
    <div class="field" id="split-rows" ${sp.by === 'rows' ? '' : 'hidden'}>
      <label class="field-label" for="split-n">Rows in each part</label>
      <input id="split-n" class="input" type="number" inputmode="numeric" min="1" step="1" value="${sp.rows}">
    </div>
    <div class="field" id="split-format"><span class="field-label">Save as</span>
      ${seg('splitfmt', [['xlsx', 'Sheets (.xlsx)'], ['pdf', 'PDF pages'], ['zip', 'Separate files']], sp.format, 'Save as')}
      <p class="hint" id="split-format-hint"></p></div>
    <div class="field" id="split-type" ${sp.format === 'zip' ? '' : 'hidden'}><span class="field-label">Each file as</span>
      ${seg('splittype', [['csv', 'CSV'], ['xlsx', 'XLSX'], ['pdf', 'PDF']], sp.fileType, 'Each file as')}</div>
    <section class="pages" aria-labelledby="pages-title">
      <h2 id="pages-title">Parts</h2>
      <ol class="page-list" id="page-list"><li class="glass empty">Loading…</li></ol>
    </section>`;
}

function wireSplit() {
  const sp = state.split;
  const btn = $('[data-action="download"]');
  const list = $('#page-list');
  const label = () => {
    const unit = PART[sp.format];
    btn.innerHTML = `${ui('download')} Download ${sp.pages ? plural(sp.pages, unit) : ''}${sp.format === 'zip' && sp.pages ? ' (.zip)' : ''}`;
    btn.disabled = !sp.pages || sp.pages > MAX_PARTS || (sp.by === 'column' && !sp.column);
    $('#split-format-hint').textContent = sp.format === 'zip' ? 'A .zip with one file per part — handy for upload limits.' : '';
  };
  const show = (pages) => {
    sp.pages = pages.length;
    list.innerHTML = pages.slice(0, MAX_PARTS).map(([name, n], i) => `<li class="glass"><span class="step-n">${i + 1}</span>
      <span class="page-name">${esc(name)}</span><small>${plural(n, 'row')}</small></li>`).join('');
    label();
  };
  const loadRows = () => {
    const size = Math.floor(Number(sp.rows));
    if (!(size >= 1)) { sp.pages = 0; list.innerHTML = '<li class="glass empty">Type how many rows go in each part.</li>'; label(); return; }
    const total = state.before;
    const n = Math.max(1, Math.ceil(total / size));
    if (n > MAX_PARTS) {
      sp.pages = n;
      list.innerHTML = `<li class="glass empty">That makes ${num(n)} parts — the limit is ${MAX_PARTS}. Choose bigger parts.</li>`;
      label();
      return;
    }
    show(Array.from({ length: n }, (_, i) => [`Rows ${num(i * size + 1)}–${num(Math.min((i + 1) * size, total))}`,
      Math.min(size, total - i * size)]));
  };
  const loadColumn = async () => {
    const column = sp.column;
    if (!column) { sp.pages = 0; list.innerHTML = ''; label(); return; }
    list.innerHTML = '<li class="glass empty">Loading…</li>';
    try {
      const data = await api(`/files/${state.file.id}/values?${new URLSearchParams({ column, limit: String(MAX_PARTS) })}`);
      if (sp.column !== column || sp.by !== 'column') return;
      const blanks = state.before - data.values.reduce((sum, v) => sum + v.count, 0);
      show([...data.values.map((v) => [String(v.value), v.count]), ...(blanks > 0 ? [['(blank)', blanks]] : [])]);
    } catch (err) {
      list.innerHTML = `<li class="glass empty">${esc(err.message)}</li>`;
    }
  };
  const load = () => (sp.by === 'rows' ? loadRows() : loadColumn());
  $('#split')?.addEventListener('change', (e) => { sp.column = e.target.value; load(); });
  $('#split-n').addEventListener('input', (e) => { sp.rows = e.target.value; loadRows(); });
  view.querySelectorAll('#split-by, #split-format, #split-type').forEach((box) => box.addEventListener('click', (e) => {
    const b = e.target.closest('[data-seg]');
    if (!b) return;
    pressSeg(b);
    if (b.dataset.seg === 'splitby') {
      sp.by = b.dataset.val;
      $('#split-col').hidden = sp.by !== 'column';
      $('#split-rows').hidden = sp.by !== 'rows';
      load();
    } else if (b.dataset.seg === 'splitfmt') {
      sp.format = b.dataset.val;
      $('#split-type').hidden = sp.format !== 'zip';
      label();
    } else sp.fileType = b.dataset.val;
  }));
  btn.addEventListener('click', (e) => {
    const opts = sp.by === 'rows' ? { split_rows: String(Math.floor(Number(sp.rows))) } : { split_by: sp.column };
    if (sp.format === 'zip') download(sp.fileType, e.currentTarget, { ...opts, files: '1' });
    else download(sp.format, e.currentTarget, opts);
  });
  load();
}

function formatSelect() {
  const ext = (state.file.filename.split('.').pop() || '').toLowerCase();
  const pick = ['csv', 'json'].includes(ext) ? 'xlsx' : 'csv';
  return `<select id="fmt" class="input">${FORMATS.map(([v, l]) => `<option value="${v}" ${v === pick ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
}

// ---------------------------------------------------------------------------- form

const colsFor = (filter, source) => (source === 'other' ? state.otherCols : state.cols).filter((c) => !filter
  || (filter === 'text' ? c.type === 'text' : filter === 'number' ? ['integer', 'decimal'].includes(c.type)
    : filter === 'date' ? ['date', 'datetime'].includes(c.type) : true));

const opt = (v, l, sel) => `<option value="${esc(v)}" ${v === sel ? 'selected' : ''}>${esc(l)}</option>`;
const colOptions = (filter, sel, placeholder = 'Choose a column', source) =>
  `<option value="" ${sel ? '' : 'selected'} disabled>${placeholder}</option>${colsFor(filter, source).map((c) => opt(c.name, c.name, sel)).join('')}`;

function seg(key, options, value, label) {
  return `<div class="seg" role="group" aria-label="${esc(label)}">${options.map(([v, l]) =>
    `<button type="button" data-seg="${key}" data-val="${esc(v)}" aria-pressed="${v === value}">${esc(l)}</button>`).join('')}</div>`;
}

const FIELD = {
  columns(f, v) {
    const all = f.optional && v === null;
    const cols = colsFor(f.filter, f.source);
    const mode = f.optional ? seg(`${f.key}__mode`, [['all', f.allLabel || 'All columns'], ['some', f.someLabel || 'Choose columns']], all ? 'all' : 'some', f.label) : '';
    if (all) return mode;
    if (!cols.length) return `${mode}<p class="hint">No ${f.filter || ''} columns in this file.</p>`;
    const chips = cols.map((c) => {
      const i = (v || []).indexOf(c.name);
      return `<button type="button" class="col-chip" data-col-toggle="${f.key}" data-col="${esc(c.name)}" aria-pressed="${i >= 0}">
        ${f.ordered && i >= 0 ? `<b>${i + 1}</b>` : ''}<span>${esc(c.name)}</span><small>${c.type}</small></button>`;
    }).join('');
    return `${mode}<div class="col-chips">${chips}</div>
      <div class="row-links"><button type="button" class="btn-link" data-col-all="${f.key}">Select all</button>
      <button type="button" class="btn-link" data-col-none="${f.key}">Clear</button></div>`;
  },
  column: (f, v) => `<select class="input" id="f-${f.key}" data-key="${f.key}">${f.optional
    ? `<option value="" ${v ? '' : 'selected'}>${esc(f.emptyLabel || 'None')}</option>${colsFor(f.filter).map((c) => opt(c.name, c.name, v)).join('')}`
    : colOptions(f.filter, v)}</select>`,
  select: (f, v) => `<select class="input" id="f-${f.key}" data-key="${f.key}">${f.options.map(([o, l]) => opt(o, l, v)).join('')}</select>`,
  choice: (f, v) => seg(f.key, f.options, v, f.label),
  text: (f, v) => `<input class="input" id="f-${f.key}" data-key="${f.key}" value="${esc(v)}" placeholder="${esc(f.placeholder || '')}">`,
  number: (f, v) => `<input class="input" id="f-${f.key}" data-key="${f.key}" type="number" inputmode="decimal" value="${esc(v)}"
    ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.max !== undefined ? `max="${f.max}"` : ''} step="${f.step || 1}">`,
  toggle: (f, v) => `<label class="toggle"><input type="checkbox" data-key="${f.key}" ${v ? 'checked' : ''}><span class="switch" aria-hidden="true"></span><span>${esc(f.label)}</span></label>`,
  conditions(f, rows) {
    const key = f.key;
    const p = { conditions: 'c', rules: 'r', filters: 'pf' }[key] ?? key; // ids: c0col (filter), r0col (rules), pf0col (pivot)
    const noun = f.noun ?? (f.then ? 'rule' : 'condition');
    const empty = f.optional && !rows.length ? `<p class="hint">${esc(f.emptyHint ?? 'None yet.')}</p>` : '';
    return `${empty}${rows.map((c, i) => `<div class="row-card glass${f.then ? ' rule' : ''}">
      <div class="row-grid">
        ${f.then ? `<span class="rule-word" aria-hidden="true">${i ? 'Else if' : 'If'}</span>` : ''}
        <label class="sr-only" for="${p}${i}col">Column</label>
        <select class="input" id="${p}${i}col" data-list="${key}" data-i="${i}" data-prop="column" data-rerender>${colOptions(null, c.column)}</select>
        <label class="sr-only" for="${p}${i}op">Condition</label>
        <select class="input" id="${p}${i}op" data-list="${key}" data-i="${i}" data-prop="operator" data-rerender>${OPERATORS.map(([o, l]) => opt(o, l, c.operator)).join('')}</select>
        ${NO_VALUE_OPS.has(c.operator) ? '' : `<label class="sr-only" for="${p}${i}v">Value</label>
        <div class="combo">
          <input class="input" id="${p}${i}v" data-list="${key}" data-i="${i}" data-prop="value" value="${esc(c.value)}"
            role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="${p}${i}list" autocomplete="off"
            data-values-for="${esc(c.column)}" data-multi="${c.operator === 'in_list'}"
            placeholder="${c.operator === 'in_list' ? 'Pick or type: Pune, Delhi…' : 'Pick or type a value'}">
          <button type="button" class="combo-btn" data-combo-toggle="${p}${i}v" aria-label="Show values for ${esc(c.column)}" tabindex="-1">
            <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></button>
          <ul class="combo-list glass" id="${p}${i}list" role="listbox" aria-label="Values in ${esc(c.column)}" hidden></ul>
        </div>`}
        ${f.then ? `<label class="rule-then" for="${p}${i}then"><span>then</span>
          <input class="input" id="${p}${i}then" data-list="${key}" data-i="${i}" data-prop="then" value="${esc(c.then ?? '')}" placeholder="e.g. High" autocomplete="off"></label>` : ''}
      </div>
      ${rows.length > 1 || f.optional ? `<button type="button" class="icon-btn small" data-remove="${key}" data-i="${i}" aria-label="Remove ${noun} ${i + 1}">${ui('trash')}</button>` : ''}
    </div>`).join('')}
    <button type="button" class="btn btn-secondary btn-sm" data-add="${key}">${ui('plus')} Add ${noun}</button>`;
  },
  sortkeys(f, rows) {
    return `${rows.map((k, i) => `<div class="row-card glass"><div class="row-grid two">
        <label class="sr-only" for="s${i}c">Column</label>
        <select class="input" id="s${i}c" data-list="by" data-i="${i}" data-prop="column">${colOptions(null, k.column)}</select>
        <label class="sr-only" for="s${i}o">Order</label>
        <select class="input" id="s${i}o" data-list="by" data-i="${i}" data-prop="order">${opt('asc', 'A → Z, small → large', k.order)}${opt('desc', 'Z → A, large → small', k.order)}</select>
      </div>${rows.length > 1 ? `<button type="button" class="icon-btn small" data-remove="by" data-i="${i}" aria-label="Remove sort ${i + 1}">${ui('trash')}</button>` : ''}</div>`).join('')}
      ${rows.length < 10 ? `<button type="button" class="btn btn-secondary btn-sm" data-add="by">${ui('plus')} Then by</button>` : ''}`;
  },
  aggs(f, rows) {
    return `${rows.map((a, i) => `<div class="row-card glass"><div class="row-grid two">
        <label class="sr-only" for="a${i}f">Calculation</label>
        <select class="input" id="a${i}f" data-list="aggs" data-i="${i}" data-prop="func" data-rerender>${AGG_FUNCS.map(([o, l]) => opt(o, l, a.func)).join('')}</select>
        ${a.func === 'count_rows' ? '<span class="hint inline">in each group</span>' : `<label class="sr-only" for="a${i}c">Column</label>
        <select class="input" id="a${i}c" data-list="aggs" data-i="${i}" data-prop="column">${colOptions(['sum', 'average', 'median'].includes(a.func) ? 'number' : null, a.column)}</select>`}
      </div>${rows.length > 1 ? `<button type="button" class="icon-btn small" data-remove="aggs" data-i="${i}" aria-label="Remove calculation ${i + 1}">${ui('trash')}</button>` : ''}</div>`).join('')}
      <button type="button" class="btn btn-secondary btn-sm" data-add="aggs">${ui('plus')} ${esc(f.addLabel || 'Add calculation')}</button>`;
  },
  types(f, rows) {
    return `${rows.map((r, i) => `<div class="row-card glass"><div class="row-grid two">
        <label class="sr-only" for="t${i}c">Column</label>
        <select class="input" id="t${i}c" data-list="types" data-i="${i}" data-prop="column">${colOptions(null, r.column)}</select>
        <label class="sr-only" for="t${i}t">New type</label>
        <select class="input" id="t${i}t" data-list="types" data-i="${i}" data-prop="to" data-rerender>${TYPES.map(([o, l]) => opt(o, l, r.to)).join('')}</select>
      </div>${rows.length > 1 ? `<button type="button" class="icon-btn small" data-remove="types" data-i="${i}" aria-label="Remove ${i + 1}">${ui('trash')}</button>` : ''}</div>`).join('')}
      <button type="button" class="btn btn-secondary btn-sm" data-add="types">${ui('plus')} Another column</button>`;
  },
  otherfile(f, id) {
    if (!id) {
      return `<div class="mini-drop glass" id="drop2">
        <span class="drop-icon small">${ui('upload')}</span>
        <span class="mini-drop-text"><strong>Add the file to look values up in</strong><small>CSV, XLSX or JSON · up to ${config.max_upload_mb} MB</small></span>
        <label class="btn btn-secondary btn-sm" for="file2">Choose second file</label>
        <input id="file2" class="sr-only" type="file" accept="${ACCEPT}">
        <button type="button" class="btn-link" data-action="sample2">Try a sample lookup file</button>
        <div class="progress" id="progress2" hidden><div class="bar"><span id="bar2"></span></div><p id="ptext2" aria-live="polite">Uploading…</p></div>
      </div>`;
    }
    const o = state.other;
    const sheets = o?.sheets?.length > 1
      ? `<label class="sr-only" for="sheet2">Sheet in the second file</label><select id="sheet2" class="input input-sm">${o.sheets.map((s) =>
        `<option ${s === o.sheet ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select>` : '';
    return `<div class="file-chip glass second">
      <span class="file-icon combine">${icon('merge')}</span>
      <span class="file-text"><strong>${esc(o?.filename || state.draft.other_name || 'Second file')}</strong>
        <small>${o ? `${plural(o.rows, 'row')} · ${plural(state.otherCols.length, 'column')}` : 'Loading…'}</small></span>
      <span class="file-actions">${sheets}
      ${o && hasHeaderRow(o) ? '<button class="btn-link" type="button" data-action="other-headers" aria-expanded="false" aria-controls="header-pick2">Headers</button>' : ''}
      <button class="btn-link" type="button" data-action="other-change">Change</button></span>
    </div>
    <section class="header-pick glass" id="header-pick2" aria-labelledby="header-pick2-title" hidden></section>`;
  },
  stackfiles(f, files) {
    const list = files.map((x, i) => `<li class="file-chip glass second">
      <span class="file-icon combine">${icon('stack')}</span>
      <span class="file-text"><strong>${esc(x.name)}</strong><small>${x.rows != null ? `${plural(x.rows, 'row')} · ${plural(x.columns, 'column')}` : 'Added'}</small></span>
      <span class="file-actions">${hasHeaderRow(x) ? `<button class="btn-link" type="button" data-stack-headers="${i}"
        aria-expanded="false" aria-controls="header-pick3" aria-label="Headers of ${esc(x.name)}">Headers</button>` : ''}
      <button class="btn-link" type="button" data-stack-remove="${i}" aria-label="Remove ${esc(x.name)}">Remove</button></span>
    </li>`).join('');
    return `${files.length ? `<ol class="stack-list">${list}</ol>
      <section class="header-pick glass" id="header-pick3" aria-labelledby="header-pick3-title" hidden></section>` : ''}
      <div class="mini-drop glass" id="drop3">
        <span class="drop-icon small">${ui('upload')}</span>
        <span class="mini-drop-text"><strong>${files.length ? 'Add another file' : 'Add the files to put underneath'}</strong><small>Choose one or several · CSV, XLSX or JSON</small></span>
        <label class="btn btn-secondary btn-sm" for="file3">${files.length ? 'Choose more files' : 'Choose files'}</label>
        <input id="file3" class="sr-only" type="file" accept="${ACCEPT}" multiple>
        ${files.length ? '' : '<button type="button" class="btn-link" data-action="sample3">Try a sample: next month\'s orders</button>'}
        <div class="progress" id="progress3" hidden><div class="bar"><span id="bar3"></span></div><p id="ptext3" aria-live="polite">Uploading…</p></div>
      </div>`;
  },
  joinkeys(f, rows) {
    return `${rows.map((k, i) => `<div class="row-card glass"><div class="row-grid two join">
        <label class="sr-only" for="k${i}l">Column in this file</label>
        <select class="input" id="k${i}l" data-list="keys" data-i="${i}" data-prop="left">${colOptions(null, k.left, 'Column here')}</select>
        <span class="eq" aria-hidden="true">=</span>
        <label class="sr-only" for="k${i}r">Matching column in the second file</label>
        <select class="input" id="k${i}r" data-list="keys" data-i="${i}" data-prop="right">${colOptions(null, k.right, 'In second file', 'other')}</select>
      </div>${rows.length > 1 ? `<button type="button" class="icon-btn small" data-remove="keys" data-i="${i}" aria-label="Remove match ${i + 1}">${ui('trash')}</button>` : ''}</div>`).join('')}
      ${rows.length < 5 ? `<button type="button" class="btn btn-secondary btn-sm" data-add="keys">${ui('plus')} Match on another column too</button>` : ''}`;
  },
  rename(f, mapping) {
    return `<div class="rename-list">${state.cols.map((c, i) => `<div class="rename-row">
      <label for="r${i}">${esc(c.name)}</label>
      <input class="input" id="r${i}" data-rename="${esc(c.name)}" value="${esc(mapping[c.name] || '')}" placeholder="${esc(c.name)}">
    </div>`).join('')}</div>`;
  },
};

const NEW_ROW = {
  keys: () => ({ left: state.cols[0]?.name ?? '', right: state.otherCols[0]?.name ?? '' }),
  conditions: () => ({ column: state.cols[0]?.name ?? '', operator: 'equals', value: '' }),
  rules: () => ({ column: state.cols[0]?.name ?? '', operator: 'equals', value: '', then: '' }),
  filters: () => ({ column: (state.cols.find((c) => c.type === 'text') ?? state.cols[0])?.name ?? '', operator: 'equals', value: '' }),
  by: () => ({ column: state.cols[0]?.name ?? '', order: 'asc' }),
  aggs: () => ({ func: 'sum', column: colsFor('number')[0]?.name ?? '' }),
  types: () => ({ column: state.cols[0]?.name ?? '', to: 'text' }),
};

function renderForm() {
  const t = state.tool;
  const d = state.draft;
  $('#opts').innerHTML = t.fields.filter((f) => !f.show || f.show(d)).map((f) => {
    const control = FIELD[f.type](f, d[f.key]);
    if (f.type === 'toggle') return `<div class="field">${control}</div>`;
    const labelled = ['text', 'number', 'column', 'select'].includes(f.type);
    return `<div class="field" data-field="${f.key}">
      ${labelled ? `<label class="field-label" for="f-${f.key}">${esc(f.label)}</label>` : `<span class="field-label">${esc(f.label)}</span>`}
      ${control}</div>`;
  }).join('');
}

function onFormInput(e) {
  const el = e.target;
  const d = state.draft;
  if (el.id === 'file2') { if (e.type === 'change' && el.files[0]) startOtherUpload(el.files[0]); return; }
  if (el.id === 'file3') { if (e.type === 'change' && el.files.length) startStackUpload([...el.files]); return; }
  if (el.id === 'sheet2') { if (e.type === 'change') changeOtherSheet(el.value); return; }
  if (el.dataset.key) {
    d[el.dataset.key] = el.type === 'checkbox' ? el.checked : el.value;
    if (e.type === 'change' && (el.tagName === 'SELECT' || el.type === 'checkbox')) renderForm();
  } else if (el.dataset.list) {
    d[el.dataset.list][Number(el.dataset.i)][el.dataset.prop] = el.value;
    if (e.type === 'change' && 'rerender' in el.dataset) renderForm();
  } else if (el.dataset.rename !== undefined) {
    d.mapping[el.dataset.rename] = el.value;
  } else return;
  if (e.type === 'input' && el.getAttribute('role') === 'combobox') comboRefresh(el);
  if (e.type === 'input' || el.tagName === 'SELECT' || el.type === 'checkbox') schedulePreview();
}

function onFormClick(e) {
  const pick = e.target.closest('.combo-list [role="option"]');
  if (pick) { comboChoose(pick); return; }
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.action === 'sample2') { startOtherUpload(sampleLookupFile()); return; }
  if (b.dataset.action === 'other-change') { changeOther(); return; }
  if (b.dataset.action === 'other-headers') {
    toggleHeaderPanel($('#header-pick2'), b, state.draft.other, { then: (meta) => useOther(meta) });
    return;
  }
  if (b.dataset.stackHeaders) {
    const i = Number(b.dataset.stackHeaders);
    const f = state.draft.files[i];
    toggleHeaderPanel($('#header-pick3'), b, f.id, {
      then: (meta) => {
        Object.assign(state.draft.files[i], { rows: meta.rows, columns: meta.columns.length });
        renderForm();
        schedulePreview(0);
      },
    });
    return;
  }
  if (b.dataset.action === 'sample3') { startStackUpload([sampleFile('sample-orders-next-month.csv', 41)]); return; }
  if (b.dataset.stackRemove) { removeStackFile(Number(b.dataset.stackRemove)); return; }
  if (b.dataset.comboToggle) {
    const input = $(`#${b.dataset.comboToggle}`);
    if (input.getAttribute('aria-expanded') === 'true') comboClose(input); else { input.focus(); comboOpen(input); }
    return;
  }
  const d = state.draft;
  if (b.dataset.seg) {
    const key = b.dataset.seg;
    if (key.endsWith('__mode')) {
      const k = key.slice(0, -6);
      d[k] = b.dataset.val === 'all' ? null : [];
    } else d[key] = b.dataset.val;
  } else if (b.dataset.colToggle) {
    const k = b.dataset.colToggle;
    const list = d[k] || [];
    const c = b.dataset.col;
    d[k] = list.includes(c) ? list.filter((x) => x !== c) : [...list, c];
  } else if (b.dataset.colAll) {
    const f = state.tool.fields.find((x) => x.key === b.dataset.colAll);
    d[f.key] = colsFor(f.filter, f.source).map((c) => c.name);
  } else if (b.dataset.colNone) {
    d[b.dataset.colNone] = [];
  } else if (b.dataset.add) {
    d[b.dataset.add].push(NEW_ROW[b.dataset.add]());
  } else if (b.dataset.remove) {
    d[b.dataset.remove].splice(Number(b.dataset.i), 1);
  } else return;
  const focusKey = b.dataset.seg ? `[data-seg="${b.dataset.seg}"][data-val="${CSS.escape(b.dataset.val)}"]`
    : b.dataset.colToggle ? `[data-col-toggle="${b.dataset.colToggle}"][data-col="${CSS.escape(b.dataset.col)}"]` : null;
  renderForm();
  if (focusKey) $(focusKey, $('#opts'))?.focus();
  schedulePreview();
}

// ---------------------------------------------------------------------------- merge: the second file

async function startOtherUpload(file) {
  if (file.size > config.max_upload_mb * 1024 * 1024) {
    toast(`That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is ${config.max_upload_mb} MB.`, 'error');
    return;
  }
  const progress = $('#progress2');
  progress.hidden = false;
  try {
    const res = await uploadFile(file, (p) => {
      $('#bar2').style.width = `${Math.round(p * 100)}%`;
      $('#ptext2').textContent = p < 1 ? `Uploading… ${Math.round(p * 100)}%` : 'Reading your file…';
    });
    await useOther(res.file);
  } catch (err) {
    if ($('#progress2')) $('#progress2').hidden = true;
    toast(err.message, 'error');
  }
}

async function loadOther(id) {
  try {
    state.other = (await api(`/files/${id}`)).file;
    state.otherCols = (await api(`/files/${id}/columns`)).columns;
    return true;
  } catch {
    state.other = null;
    state.otherCols = [];
    return false;
  }
}

/** Matching columns: a column with the same name in both files if there is one (text first). */
function defaultKeys() {
  const byName = new Map(state.otherCols.map((c) => [c.name.toLowerCase(), c.name]));
  const shared = [...state.cols].sort((a, b) => (a.type === 'text' ? -1 : 0) - (b.type === 'text' ? -1 : 0))
    .find((c) => byName.has(c.name.toLowerCase()));
  if (shared) return [{ left: shared.name, right: byName.get(shared.name.toLowerCase()) }];
  return [{ left: (state.cols.find((c) => c.type === 'text') ?? state.cols[0])?.name ?? '', right: state.otherCols[0]?.name ?? '' }];
}

async function useOther(meta) {
  await loadOther(meta.id);
  Object.assign(state.draft, { other: meta.id, other_name: meta.filename, keys: defaultKeys(), columns: null });
  renderForm();
  schedulePreview(0);
}

async function changeOtherSheet(sheet) {
  try {
    const res = await api(`/files/${state.draft.other}/sheet`, { method: 'PUT', body: { sheet } });
    await useOther(res.file);
  } catch (err) { toast(err.message, 'error'); }
}

function changeOther() {
  const id = state.draft.other;
  const inUse = state.file.steps.some((s) => s.op === 'merge' && s.other === id);
  if (id && !inUse) api(`/files/${id}`, { method: 'DELETE' }).catch(() => {}); // privacy: delete right away
  Object.assign(state.draft, { other: '', other_name: '', keys: [], columns: null });
  state.other = null;
  state.otherCols = [];
  renderForm();
  schedulePreview(0);
}

function sampleLookupFile() {
  const csv = 'City,Region,State\nPune,West,Maharashtra\nMumbai,West,Maharashtra\nDelhi,North,Delhi\n'
    + 'Bengaluru,South,Karnataka\nChennai,South,Tamil Nadu\nHyderabad,South,Telangana\n';
  return new File([csv], 'city-regions.csv', { type: 'text/csv' });
}

// ---------------------------------------------------------------------------- stack: more files

/** Editing a Stack step: show each file's size, and drop files that have expired. */
async function loadStackFiles() {
  const d = state.draft;
  d.this_name = d.this_name || state.file.filename;
  const kept = [];
  for (const f of d.files) {
    try {
      const meta = (await api(`/files/${f.id}`)).file;
      kept.push({ ...f, rows: meta.rows, columns: meta.columns.length });
    } catch { toast(`${f.name} has expired. Please add it again.`, 'error'); }
  }
  d.files = kept;
}

async function startStackUpload(files) {
  const big = files.find((f) => f.size > config.max_upload_mb * 1024 * 1024);
  if (big) { toast(`${big.name} is ${(big.size / 1048576).toFixed(1)} MB. The limit is ${config.max_upload_mb} MB.`, 'error'); return; }
  $('#progress3').hidden = false;
  let added = 0;
  for (const [n, file] of files.entries()) {
    try {
      const res = await uploadFile(file, (p) => {
        if (!$('#bar3')) return;
        $('#bar3').style.width = `${Math.round(p * 100)}%`;
        const which = files.length > 1 ? ` ${n + 1} of ${files.length}` : '';
        $('#ptext3').textContent = p < 1 ? `Uploading${which}… ${Math.round(p * 100)}%` : `Reading file${which}…`;
      });
      const f = res.file;
      state.draft.files.push({ id: f.id, name: f.filename, rows: f.rows, columns: f.columns.length });
      added += 1;
    } catch (err) {
      toast(`${file.name}: ${err.message}`, 'error');
    }
  }
  renderForm();
  if (added) schedulePreview(0);
}

function removeStackFile(i) {
  const [gone] = state.draft.files.splice(i, 1);
  const inUse = state.file.steps.some((s) => s.op === 'stack' && s.others.includes(gone.id));
  if (!inUse) api(`/files/${gone.id}`, { method: 'DELETE' }).catch(() => {}); // privacy: delete right away
  renderForm();
  schedulePreview(0);
}

/** Files a step reads besides the main one (Merge's second file, Stack's files). */
const otherFiles = (step) => (step.op === 'merge' ? [step.other] : step.op === 'stack' ? step.others : []);

// ---------------------------------------------------------------------------- pivot chart

const CHART_TYPES = [['column', 'Column'], ['bar', 'Bar'], ['line', 'Line'], ['area', 'Area'], ['pie', 'Pie'], ['donut', 'Donut']];
const PALETTE_NAMES = { theme: 'Gridglass', ocean: 'Ocean', sunset: 'Sunset', forest: 'Forest', berry: 'Berry', mono: 'Grey' };

function chartCustomiser() {
  const c = state.chart;
  const swatches = Object.keys(PALETTES).map((key) => {
    const cols = themeColors(key).series.slice(0, 5);
    return `<button type="button" class="swatch" data-palette="${key}" aria-pressed="${c.palette === key}" aria-label="${PALETTE_NAMES[key]} colours">
      <svg viewBox="0 0 50 14" aria-hidden="true">${cols.map((col, i) => `<rect x="${i * 10}" width="10" height="14" fill="${col}"/>`).join('')}</svg>
      <span>${PALETTE_NAMES[key]}</span></button>`;
  }).join('');
  const toggle = (key, label) => `<label class="toggle"><input type="checkbox" data-chart-opt="${key}" ${c[key] ? 'checked' : ''}><span class="switch" aria-hidden="true"></span><span>${label}</span></label>`;
  return `<details class="chart-custom" id="chart-custom"${state.chartCustomOpen ? ' open' : ''}>
    <summary>Customise the chart</summary>
    <div class="chart-fields">
      <div class="field"><label class="field-label" for="ch-title">Title</label>
        <input class="input" id="ch-title" data-chart-text="title" value="${esc(c.title)}" maxlength="70" placeholder="e.g. Sales by city" autocomplete="off"></div>
      <div class="field two-inputs" id="ch-axes"><span class="field-label">Axis titles</span>
        <label class="sr-only" for="ch-x">Across the bottom</label><input class="input" id="ch-x" data-chart-text="xTitle" value="${esc(c.xTitle)}" maxlength="60" placeholder="Across, e.g. City" autocomplete="off">
        <label class="sr-only" for="ch-y">Up the side</label><input class="input" id="ch-y" data-chart-text="yTitle" value="${esc(c.yTitle)}" maxlength="50" placeholder="Up, e.g. Sales (₹)" autocomplete="off"></div>
      <div class="field"><span class="field-label">Colours</span><div class="swatches">${swatches}</div></div>
      <div class="field"><span class="field-label">Order</span>
        ${seg('chsort', [['none', 'As in table'], ['desc', 'Largest first'], ['asc', 'Smallest first'], ['az', 'A → Z']], c.sort, 'Order')}</div>
      <div class="field"><span class="field-label">Show</span>
        ${seg('chtop', [['0', 'All'], ['5', 'Top 5'], ['10', 'Top 10'], ['20', 'Top 20']], String(c.top), 'Show')}</div>
      <div class="field"><span class="field-label">Numbers</span>
        ${seg('chnum', [['short', 'Short (1.2L)'], ['full', 'Full (1,23,456)']], c.numbers, 'Numbers')}</div>
      <div class="field"><span class="field-label">Shape</span>
        ${seg('chshape', [['wide', 'Wide'], ['square', 'Square'], ['tall', 'Tall']], c.shape, 'Shape')}</div>
      <div class="field toggles">
        ${toggle('labels', 'Show data labels on the chart')}
        <div class="field" id="ch-labelas" ${c.labels ? '' : 'hidden'}><span class="field-label">Labels show</span>
          <div class="label-parts" role="group" aria-label="Labels show">${labelChips(c)}</div></div>
        ${toggle('legend', 'Show the legend')}
        ${toggle('grid', 'Show grid lines')}
        <span id="ch-stack-wrap">${toggle('stacked', 'Stack the series')}</span>
      </div>
      <button type="button" class="btn-link" data-chart-reset>Reset the look</button>
    </div>
  </details>`;
}

const SEG_OPT = { chsort: 'sort', chtop: 'top', chnum: 'numbers', chshape: 'shape' };

/** Name / Value / % switches for the data labels; Name only on pies and donuts (other charts have an axis). */
function labelChips(c) {
  const on = labelParts(c);
  const round = c.type === 'pie' || c.type === 'donut';
  return [['name', 'Name'], ['value', 'Value'], ['percent', '%']].map(([k, l]) => `<button type="button" class="col-chip"
    data-labelpart="${k}" aria-pressed="${on[k]}" ${k === 'name' && !round ? 'hidden' : ''}><span>${l}</span></button>`).join('');
}

function wireChart() {
  const tabs = [$('#tab-table'), $('#tab-chart')];
  const select = (view) => {
    state.view = view;
    const chart = view === 'chart';
    tabs.forEach((t) => {
      const on = (t.id === 'tab-chart') === chart;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
    });
    $('#pv').hidden = chart;
    $('#pv-pager').hidden = chart;
    $('#chart-panel').hidden = !chart;
    if (chart) renderChart();
  };
  tabs.forEach((t) => t.addEventListener('click', () => select(t.id === 'tab-chart' ? 'chart' : 'table')));
  $('.tabs').addEventListener('keydown', (e) => { // arrow keys move between tabs
    if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    const next = state.view === 'chart' ? tabs[0] : tabs[1];
    select(next.id === 'tab-chart' ? 'chart' : 'table');
    next.focus();
  });
  const panel = $('#chart-panel');
  panel.addEventListener('click', async (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.dataset.seg === 'charttype' || SEG_OPT[b.dataset.seg]) {
      pressSeg(b);
      if (b.dataset.seg === 'charttype') {
        state.chart.type = b.dataset.val;
        const chips = $('.label-parts');
        if (chips) chips.innerHTML = labelChips(state.chart);
      }
      else state.chart[SEG_OPT[b.dataset.seg]] = b.dataset.seg === 'chtop' ? Number(b.dataset.val) : b.dataset.val;
      renderChart();
    } else if (b.dataset.labelpart) {
      const round = state.chart.type === 'pie' || state.chart.type === 'donut';
      const on = labelParts(state.chart);
      on[b.dataset.labelpart] = !on[b.dataset.labelpart];
      const list = Object.keys(on).filter((k) => on[k] && (k !== 'name' || round));
      if (!list.length) return; // keep at least one
      state.chart.labelAs = list;
      $('.label-parts').innerHTML = labelChips(state.chart);
      renderChart();
    } else if (b.dataset.palette) {
      state.chart.palette = b.dataset.palette;
      panel.querySelectorAll('[data-palette]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      renderChart();
    } else if ('chartReset' in b.dataset) {
      const { title, xTitle, yTitle, type } = state.chart; // keep the words and the type; reset the look
      state.chart = { ...DEFAULT_OPTIONS, title, xTitle, yTitle, type };
      $('#chart-custom').outerHTML = chartCustomiser();
      renderChart();
    } else if (b.dataset.chartSave) {
      const data = chartReady();
      if (!data) return;
      const svg = chartSVG(data, themeColors(state.chart.palette), { ...state.chart, background: true });
      const stem = (state.chart.title || state.file.filename.replace(/\.[^.]+$/, '')).replace(/[\\/:*?"<>|]+/g, '-');
      await withBusy(b, async () => {
        const { blob, name } = await saveChart(svg, `${stem}-${state.chart.type}-chart`, b.dataset.chartSave);
        saveBlob(blob, name);
      });
    }
  });
  let typing;
  panel.addEventListener('input', (e) => {
    const el = e.target;
    if (el.dataset.chartText) {
      state.chart[el.dataset.chartText] = el.value;
      clearTimeout(typing);
      typing = setTimeout(renderChart, 250);
    } else if (el.dataset.chartOpt) {
      state.chart[el.dataset.chartOpt] = el.checked;
      if (el.dataset.chartOpt === 'labels') $('#ch-labelas').hidden = !el.checked;
      renderChart();
    }
  });
  panel.addEventListener('toggle', (e) => { if (e.target.id === 'chart-custom') state.chartCustomOpen = e.target.open; }, true);
  if (state.view === 'chart') renderChart();
}

let chartWidth = 0;
window.addEventListener('resize', () => { // rotate or resize: redraw at the new width
  const el = $('#chart');
  if (!el || el.offsetParent === null || Math.abs(el.clientWidth - chartWidth) < 24) return;
  chartWidth = el.clientWidth;
  clearTimeout(window.chartResize);
  window.chartResize = setTimeout(renderChart, 120);
});

/** The preview as chart data, sorted and trimmed the way the options say; null when there's nothing to draw. */
function chartReady() {
  const data = state.pvData ? chartData(state.pvData) : null;
  return data && !data.error ? arrange(data, state.chart) : null;
}

function renderChart() {
  const el = $('#chart');
  if (!el) return;
  const note = $('#chart-note');
  const c = state.chart;
  const raw = state.pvData ? chartData(state.pvData) : { error: 'Finish the pivot options to see a chart.' };
  $('#chart-panel').querySelectorAll('[data-chart-save]').forEach((b) => { b.disabled = Boolean(raw.error); });
  if (raw.error) {
    el.innerHTML = `<p class="empty">${esc(raw.error)}</p>`;
    note.textContent = '';
    return;
  }
  const data = arrange(raw, c);
  const round = c.type === 'pie' || c.type === 'donut';
  const stackable = data.series.length > 1 && !round && c.type !== 'line';
  const wrap = $('#ch-stack-wrap');
  if (wrap) wrap.hidden = !stackable;
  el.dataset.shape = c.shape;
  el.innerHTML = chartSVG(data, themeColors(c.palette), { ...c, fit: el.clientWidth || undefined });
  // Options scroll in below the pinned chart, never behind it (CSS reads this for scroll-margin-top).
  $('#chart-panel').style.setProperty('--stick-h', `${el.parentElement.offsetHeight}px`);
  note.textContent = [
    round && data.series.length > 1 ? `The ${c.type} shows ${data.series[0].name}.` : '',
    data.truncated ? `Showing the first ${MAX_CATEGORIES} of ${num(data.total)} ${data.categoryName} values. Use Show: Top 10 to group the rest.` : '',
  ].filter(Boolean).join(' ');
}

// ---------------------------------------------------------------------------- value dropdown (combobox)
// The filter's value box: tap for the column's real values (with counts), or type anything.

async function loadValues(column, q = '') {
  const key = q ? `${column}\u0000${q.toLowerCase()}` : column;
  if (!state.values[key]) {
    const qs = new URLSearchParams({ column, limit: '200', ...(q ? { q } : {}), ...(state.editIndex !== null ? { upto: state.editIndex } : {}) });
    state.values[key] = api(`/files/${state.file.id}/values?${qs}`).catch(() => ({ values: [], truncated: false }));
  }
  return state.values[key];
}

const comboToken = (input) => (input.dataset.multi === 'true' ? input.value.split(',').pop() : input.value).trim().toLowerCase();

let comboSearch;
async function comboOpen(input) {
  const column = input.dataset.valuesFor;
  if (!column) return;
  delete input.dataset.chosen; // opening on purpose shows the list again
  const asked = performance.now();
  const data = await loadValues(column);
  if (Number(input.dataset.closedAt || 0) > asked) return; // closed (Esc, a pick) while the values were loading
  if (document.activeElement !== input && input.getAttribute('aria-expanded') !== 'true') return;
  comboRender(input, data);
}

async function comboRefresh(input) {
  if (!input.dataset.valuesFor) return;
  const data = await loadValues(input.dataset.valuesFor);
  comboRender(input, data);
  const token = comboToken(input);
  if (data.truncated && token) { // more values on the server than we have here: ask for matches
    clearTimeout(comboSearch);
    comboSearch = setTimeout(async () => {
      const more = await loadValues(input.dataset.valuesFor, token);
      if (comboToken(input) === token) comboRender(input, more);
    }, 250);
  }
}

function comboRender(input, data) {
  const list = $(`#${input.getAttribute('aria-controls')}`);
  if (!list) return;
  if (input.dataset.chosen !== undefined && input.dataset.chosen === input.value) { comboClose(input); return; } // just picked
  delete input.dataset.chosen;
  const token = comboToken(input);
  const taken = input.dataset.multi === 'true'
    ? new Set(input.value.split(',').slice(0, -1).map((v) => v.trim().toLowerCase())) : new Set();
  const matches = data.values
    .filter((v) => !taken.has(String(v.value).toLowerCase()))
    .filter((v) => !token || String(v.value).toLowerCase().includes(token))
    .slice(0, 100);
  if (input.dataset.multi !== 'true' && matches.length === 1 && String(matches[0].value).toLowerCase() === token) {
    comboClose(input); // what you typed is exactly the only match: nothing left to pick
    return;
  }
  list.innerHTML = matches.length
    ? matches.map((v, k) => `<li role="option" id="${list.id}-${k}" data-value="${esc(v.value)}" aria-selected="false">
        <span>${esc(v.value)}</span><small>${num(v.count)}</small></li>`).join('')
      + (data.truncated && !token ? `<li class="combo-more" aria-hidden="true">Type to search all ${num(data.distinct)} values</li>` : '')
    : `<li class="combo-more" aria-hidden="true">${token ? 'No match — your typed value will be used' : 'No values'}</li>`;
  const opening = list.hidden;
  list.hidden = false;
  input.setAttribute('aria-expanded', 'true');
  input.removeAttribute('aria-activedescendant');
  if (opening) keepAboveBar(list);
}

/** On phones the action button sticks to the bottom; scroll so an opened list isn't hidden behind it. */
function keepAboveBar(list) {
  const bar = $('.action-bar');
  if (!bar || getComputedStyle(bar).position !== 'sticky') return;
  const over = list.getBoundingClientRect().bottom + 8 - bar.getBoundingClientRect().top;
  if (over > 0) window.scrollBy({ top: over, behavior: 'instant' });
}

function comboClose(input) {
  if (!input) return;
  input.dataset.closedAt = String(performance.now());
  const list = $(`#${input.getAttribute('aria-controls')}`);
  if (list) list.hidden = true;
  input.setAttribute('aria-expanded', 'false');
  input.removeAttribute('aria-activedescendant');
}

function comboChoose(li) {
  const input = li.closest('.combo').querySelector('[role="combobox"]');
  const value = li.dataset.value;
  if (input.dataset.multi === 'true') {
    const parts = input.value.split(',').slice(0, -1).map((v) => v.trim()).filter(Boolean);
    input.value = `${[...parts, value].join(', ')}, `;
  } else {
    input.value = value;
    input.dataset.chosen = value; // keep the list shut until the user types again
  }
  input.dispatchEvent(new Event('input', { bubbles: true })); // updates the draft and the preview
  if (input.dataset.multi === 'true') input.focus(); else comboClose(input);
}

function onComboKey(e) {
  const input = e.target;
  if (input.getAttribute('role') !== 'combobox') return;
  const list = $(`#${input.getAttribute('aria-controls')}`);
  const options = [...list.querySelectorAll('[role="option"]')];
  const current = options.findIndex((o) => o.getAttribute('aria-selected') === 'true');
  const move = (k) => {
    options.forEach((o, j) => o.setAttribute('aria-selected', String(j === k)));
    if (options[k]) { input.setAttribute('aria-activedescendant', options[k].id); options[k].scrollIntoView({ block: 'nearest' }); }
  };
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (list.hidden) comboOpen(input); else move(Math.min(current + 1, options.length - 1));
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    move(Math.max(current - 1, 0));
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (current >= 0) comboChoose(options[current]); else comboClose(input);
  } else if (e.key === 'Escape') {
    comboClose(input);
  }
}

// ---------------------------------------------------------------------------- preview

let previewTimer;
let previewSeq = 0;

function schedulePreview(delay = 350) {
  state.previewOk = false;
  const btn = $('#apply');
  if (btn) btn.disabled = true;
  clearTimeout(previewTimer);
  state.browse.page = 0; // options changed: back to the first page
  previewTimer = setTimeout(() => {
    const hint = incomplete(state.tool, state.draft);
    if (hint) { showPreview(baseSteps(), null, hint); return; } // show the data as it is, plus what's missing
    const step = toStep(state.tool, state.draft);
    showPreview([...baseSteps(), step], step);
  }, delay);
}

let lastPreview = null; // what's on screen, so the pager can ask for another page of it

async function showPreview(steps, step, hint = null) {
  lastPreview = { steps, step, hint };
  const seq = ++previewSeq;
  const box = $('#pv');
  const badge = $('#pv-badge');
  const note = $('#pv-note');
  box.classList.add('loading');
  try {
    const offset = state.browse.all ? state.browse.page * config.page_rows : 0;
    const { preview } = await api(`/files/${state.file.id}/preview?limit=${previewRows()}&offset=${offset}`, { method: 'POST', body: { steps } });
    if (seq !== previewSeq) return;
    if (state.browse.all && preview.total_rows > config.browse_max_rows) { // grew past the limit: back to quick view
      state.browse = { all: false, page: 0 };
      showPreview(steps, step, hint);
      return;
    }
    box.classList.remove('loading', 'error');
    box.innerHTML = table(preview, steps.some((x) => x.op === 'pivot') ? PIVOT_DECIMALS : null);
    state.pvData = hint ? null : preview;
    if (state.view === 'chart') renderChart();
    const diff = preview.total_rows - state.before;
    badge.dataset.kind = diff < 0 ? 'warn' : 'ok';
    badge.textContent = hint ? '' : !step ? plural(preview.total_rows, 'row')
      : diff < 0 ? `${num(-diff)} fewer rows` : diff > 0 ? `${num(diff)} more rows` : plural(preview.total_rows, 'row');
    const colDiff = preview.columns.length - state.cols.length;
    note.classList.toggle('needs', Boolean(hint));
    note.textContent = [
      hint || '',
      preview.truncated && !state.browse.all ? `Showing the first ${num(preview.rows.length)} of ${num(preview.total_rows)} rows.` : '',
      !state.browse.all && preview.total_rows > config.browse_max_rows ? 'Download the file to see every row.' : '',
      colDiff ? `${colDiff > 0 ? '+' : '−'}${plural(Math.abs(colDiff), 'column')}.` : '',
    ].filter(Boolean).join(' ');
    renderPager(preview);
    state.previewOk = !hint;
    const btn = $('#apply');
    if (btn) btn.disabled = Boolean(hint);
  } catch (err) {
    if (seq !== previewSeq) return;
    box.classList.remove('loading');
    box.classList.add('error');
    badge.textContent = '';
    note.textContent = '';
    $('#pv-pager').innerHTML = '';
    box.innerHTML = `<p class="form-error">${ui('alert')}<span>${esc(friendly(err))}</span></p>`;
  }
}

function renderPager(pv) {
  const el = $('#pv-pager');
  const total = pv.total_rows;
  if (!state.browse.all) {
    el.innerHTML = pv.truncated && total <= config.browse_max_rows
      ? `<button type="button" class="btn btn-secondary btn-sm" data-page="all">Show all ${num(total)} rows</button>` : '';
    return;
  }
  const pages = Math.max(1, Math.ceil(total / config.page_rows));
  const p = state.browse.page;
  const from = total ? p * config.page_rows + 1 : 0;
  const to = Math.min(total, (p + 1) * config.page_rows);
  el.innerHTML = `
    <button type="button" class="btn btn-secondary btn-sm" data-page="prev" ${p === 0 ? 'disabled' : ''} aria-label="Previous page">‹ Prev</button>
    <span class="pager-text" aria-live="polite">Rows ${num(from)}–${num(to)} of ${num(total)}${pages > 1 ? ` · page ${p + 1} of ${pages}` : ''}</span>
    <button type="button" class="btn btn-secondary btn-sm" data-page="next" ${p >= pages - 1 ? 'disabled' : ''} aria-label="Next page">Next ›</button>
    <button type="button" class="btn-link" data-page="less">Quick view</button>`;
}

function onPager(e) {
  const b = e.target.closest('[data-page]');
  if (!b || !lastPreview) return;
  const action = b.dataset.page;
  if (action === 'all') state.browse = { all: true, page: 0 };
  else if (action === 'less') state.browse = { all: false, page: 0 };
  else state.browse.page += action === 'next' ? 1 : -1;
  $('#pv').scrollTop = 0;
  showPreview(lastPreview.steps, lastPreview.step, lastPreview.hint);
}

function friendly(err) {
  const p = err.info?.problems?.[0];
  if (!p) return err.message.replace(/^Step \d+: /, '');
  const field = state.tool?.fields.find((f) => p.field && (p.field === f.key || p.field.startsWith(`${f.key}.`)));
  const label = field?.label?.toLowerCase() || 'this option';
  const m = p.message.replace(/^[\w.]+: /, '');
  if (/at least 1 item/.test(m)) return field?.type === 'rename' ? 'Type a new name for at least one column.' : 'Choose at least one column.';
  if (/Field required|should be a valid string|String should have at least 1/.test(m)) return `Fill in “${label}”.`;
  if (/valid (integer|number)|greater than or equal|less than or equal/.test(m)) return `Check the number in “${label}”.`;
  return m;
}

// ---------------------------------------------------------------------------- apply & result

async function apply() {
  if (!state.previewOk) return;
  const btn = $('#apply');
  btn.disabled = true;
  btn.classList.add('busy');
  const step = toStep(state.tool, state.draft);
  const i = state.editIndex;
  try {
    const res = i === null
      ? await api(`/files/${state.file.id}/steps`, { method: 'POST', body: step })
      : await api(`/files/${state.file.id}/steps`, {
        method: 'PUT', body: { steps: [...state.file.steps.slice(0, i), step, ...state.file.steps.slice(i + 1)] },
      });
    remember(res.file);
    state.result = { before: state.before, after: res.preview.total_rows, op: state.tool.op, edited: i !== null };
    state.editIndex = null;
    if (location.hash === '#/result') renderDone(); else location.hash = '#/result';
  } catch (err) {
    btn.classList.remove('busy');
    btn.disabled = false;
    const later = err.info?.step_index;
    if (i !== null && Number.isInteger(later) && later > i) {
      const name = TOOL[state.file.steps[later]?.op]?.label ?? 'a later step';
      toast(`This change doesn't fit step ${later + 1} (${name}): ${err.message.replace(/^Step \d+: /, '')} Edit or remove that step first.`, 'error');
    } else {
      toast(friendly(err), 'error');
    }
  }
}

/** The result page (#/result): works after a reload too, by asking the server for the current row count. */
async function showResult() {
  if (!state.result) {
    try {
      const { preview } = await api(`/files/${state.file.id}/preview?limit=1`);
      state.result = { before: state.file.rows, after: preview.total_rows, op: state.file.steps.at(-1)?.op ?? null };
    } catch (err) {
      if (err.status === 404) { remember(null); toast('That file has expired. Please upload it again.', 'error'); renderHome(); return; }
      toast(err.message, 'error');
      return;
    }
  }
  renderDone();
}

function renderDone() {
  const { before, after, op, edited } = state.result;
  const t = TOOL[op];
  state.tool = t ?? null;
  state.stage = 'done';
  view.dataset.screen = 'done';
  document.title = 'Your result — Gridglass';
  const title = state.result.recipe ? `Ran “${state.result.recipe}”` : edited ? 'Changes saved' : t?.done ? t.done(before, after, state.file.steps.at(-1)) : t ? `${t.label} done` : 'Your file is ready';
  const steps = state.file.steps;
  const last = steps.length - 1;
  const lastTool = TOOL[steps[last]?.op];
  const pencil = icon('rename');
  view.innerHTML = `${topbar(last >= 0 ? { edit: `#/edit/${last}`, title: `Edit ${lastTool?.label ?? 'last step'}`, close: '#/' } : { close: '#/' })}
    <section class="done">
      <span class="done-icon">${ui('check')}</span>
      <h1>${esc(title)}</h1>
      <p>${before === after ? plural(after, 'row') : `${num(before)} rows → ${num(after)} rows`}</p>
      <div class="done-actions">
        ${last >= 0 ? `<a class="btn btn-secondary btn-sm" href="#/edit/${last}">${pencil} Edit options</a>` : ''}
        ${lastTool?.op === 'pivot' ? `<a class="btn btn-secondary btn-sm" href="#/edit/${last}" data-action="chart">${icon('group')} Make a chart</a>` : ''}
      </div>
    </section>
    <section class="card glass">
      ${downloadFields()}
      <button class="btn btn-primary btn-lg btn-block" type="button" data-action="download">${ui('download')} Download file</button>
      ${navigator.share ? `<button class="btn btn-secondary btn-block" type="button" data-action="share">${ui('share')} Share</button>` : ''}
    </section>
    <section class="next">
      <h2>Keep working on this file</h2>
      <p class="hint">${t ? `Tools that often come after ${esc(t.label.toLowerCase())}.` : 'The result goes straight into the next tool.'}</p>
      <div class="chips wrap">${suggestFor(lastTool?.op ?? op).map((x) => `<a class="chip" href="#/tool/${x}">${TOOL[x].label}</a>`).join('')}
        <a class="chip" href="#/">All tools…</a></div>
    </section>
    <section class="applied">
      <h2>Applied steps</h2>
      <ol class="step-list">${steps.map((s, i) => {
        const label = esc(TOOL[s.op]?.label || s.op);
        return `<li class="glass"><span class="step-n">${i + 1}</span>
        <span class="step-name">${label}</span>
        <a class="icon-btn small" href="#/edit/${i}" aria-label="Edit step ${i + 1}: ${label}">${pencil}</a>
        <button type="button" class="icon-btn small" data-undo="${i}" aria-label="Remove step ${i + 1}: ${label}">${ui('trash')}</button></li>`;
      }).join('') || '<li class="glass empty">No steps — this is your original file.</li>'}</ol>
      ${steps.length ? recipeSaver(steps) : ''}
    </section>
    <footer class="done-foot"><button type="button" class="btn-link" data-action="startover">Start over with a new file</button></footer>`;
  wireDownload();
  $('[data-action="startover"]').addEventListener('click', startOver);
  $('[data-action="chart"]')?.addEventListener('click', () => { state.wantChart = true; });
  view.querySelectorAll('[data-undo]').forEach((b) => b.addEventListener('click', () => undo(Number(b.dataset.undo))));
  $('#recipe-save')?.addEventListener('click', onSaverClick);
  $('#recipe-save')?.addEventListener('submit', onSaverSubmit);
}

async function undo(i) {
  try {
    const res = await api(`/files/${state.file.id}/steps/${i}`, { method: 'DELETE' });
    remember(res.file);
    state.result = { ...state.result, after: res.preview.total_rows, edited: false };
    renderDone();
    toast('Step removed.');
  } catch (err) { toast(err.message, 'error'); }
}

/** Edit saved step i (#/edit/i): its tool opens with the saved options, on the data as it was before that step. */
async function editStep(i) {
  const step = state.file.steps[i];
  const tool = TOOL[step?.op];
  if (!tool) { location.replace('#/result'); return; }
  try {
    state.tool = tool;
    state.editIndex = i;
    state.values = {};
    state.result = null;
    state.cols = (await api(`/files/${state.file.id}/columns?${upto()}`)).columns;
    state.before = state.cols[0]?.rows ?? state.file.rows;
    state.draft = toDraft(tool, step, state.cols);
    state.browse = { all: false, page: 0 };
    state.view = state.wantChart ? 'chart' : 'table';
    state.wantChart = false;
    state.other = null;
    state.otherCols = [];
    if (tool.op === 'merge' && !(await loadOther(step.other))) {
      Object.assign(state.draft, { other: '', other_name: '', keys: [] });
      toast('The second file has expired. Please add it again.', 'error');
    }
    if (tool.op === 'stack') await loadStackFiles();
    document.title = `Edit ${tool.label} — Gridglass`;
    renderOptions();
  } catch (err) {
    if (err.status === 404) { remember(null); toast('That file has expired. Please upload it again.', 'error'); renderHome(); return; }
    toast(err.message, 'error');
  }
}

// ---------------------------------------------------------------------------- download & share

/** `opts`: extra export settings (split_by, split_rows, files, orientation, title, columns), or a function returning them. */
async function fetchExport(fmt, opts = {}) {
  const qs = new URLSearchParams({ format: fmt });
  for (const [k, v] of Object.entries(typeof opts === 'function' ? opts() : opts)) {
    if (Array.isArray(v)) v.forEach((x) => qs.append(k, x));
    else if (v !== '' && v !== undefined && v !== null) qs.set(k, v);
  }
  const res = await fetch(`${API}/files/${state.file.id}/export?${qs}`).catch(() => null);
  if (!res) throw new ApiError({ message: "Can't reach Gridglass. Check your connection." }, 0);
  if (!res.ok) throw new ApiError((await res.json().catch(() => null))?.error, res.status);
  const cd = res.headers.get('Content-Disposition') || '';
  const name = decodeURIComponent((cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="?([^";]+)"?/) || [])[1] || `gridglass.${fmt}`);
  return { blob: await res.blob(), name };
}

async function withBusy(btn, fn) {
  btn.classList.add('busy');
  btn.disabled = true;
  try { await fn(); } catch (err) { if (err.name !== 'AbortError') toast(err.message, 'error'); } finally {
    btn.classList.remove('busy');
    btn.disabled = false;
  }
}

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
  toast(`Saved ${name}`);
}

function download(fmt, btn, opts = {}) {
  return withBusy(btn, async () => {
    const { blob, name } = await fetchExport(fmt, opts);
    saveBlob(blob, name);
  });
}

function share(fmt, btn, opts = {}) {
  return withBusy(btn, async () => {
    const { blob, name } = await fetchExport(fmt, opts);
    const file = new File([blob], name, { type: blob.type });
    if (navigator.canShare?.({ files: [file] })) await navigator.share({ files: [file], title: name });
    else toast("This browser can't share files — use Download instead.");
  });
}

// ---------------------------------------------------------------------------- file changes

async function changeSheet(sheet) {
  try {
    const res = await api(`/files/${state.file.id}/sheet`, { method: 'PUT', body: { sheet } });
    remember(res.file);
    await enterOptions();
    if (res.file.header_row > 0) toast(`Skipped ${plural(res.file.header_row, 'row')} above the column names.`);
  } catch (err) { toast(err.message, 'error'); }
}

// ---------------------------------------------------------------------------- recipes (saved on this device)

const RECIPES_KEY = 'gg.recipes';
const MAX_RECIPES = 50;

function loadRecipes() {
  try {
    const list = JSON.parse(localStorage.getItem(RECIPES_KEY) || '[]');
    return Array.isArray(list) ? list.filter((r) => r && typeof r.name === 'string' && Array.isArray(r.steps) && r.steps.length) : [];
  } catch { return []; }
}

function storeRecipes(list) {
  try { localStorage.setItem(RECIPES_KEY, JSON.stringify(list)); return true; } catch {
    toast("This browser isn't letting Gridglass save recipes. Private browsing can block it.", 'error');
    return false;
  }
}

const findRecipe = (id) => loadRecipes().find((r) => r.id === id);
const stepNames = (steps) => steps.map((s) => TOOL[s.op]?.label ?? s.op);
/**
 * Merge and Stack use extra uploads, which are deleted after an hour. A recipe keeps those steps
 * without the files, and asks for a file in each place when it runs.
 */
const withoutFiles = (steps) => steps.map((s) => (s.op === 'merge' ? { ...s, other: null }
  : s.op === 'stack' ? { ...s, others: s.others.map(() => null) } : s));
/** The extra files a recipe asks for: one per Merge, one per file in a Stack. */
function slotsOf(steps) {
  const out = [];
  steps.forEach((s, i) => {
    if (s.op === 'merge') out.push({ step: i, k: 0, label: 'Merge files', was: s.other_name || '' });
    if (s.op === 'stack') s.others.forEach((_, k) => out.push({ step: i, k, label: 'Stack files', was: s.other_names?.[k] || '' }));
  });
  return out;
}
/** Put the newly chosen files into the recipe's steps. */
function fillFiles(steps, slots, files, main) {
  const out = structuredClone(steps);
  slots.forEach((sl, n) => {
    const s = out[sl.step];
    const f = files[n];
    if (s.op === 'merge') Object.assign(s, { other: f.id, other_name: f.filename });
    else {
      s.others[sl.k] = f.id;
      s.other_names = s.others.map((_, k) => s.other_names?.[k] ?? '');
      s.other_names[sl.k] = f.filename;
      if (s.this_name) s.this_name = main.filename;
    }
  });
  return out;
}
const newId = () => (crypto.randomUUID?.() ?? `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`).replace(/[^\w-]/g, '');

function recipesSection() {
  const list = loadRecipes();
  if (!list.length) return '';
  return `<section class="recipes" id="recipes" aria-labelledby="rc-title">
    <h2 id="rc-title">My recipes</h2>
    <ul class="recipe-list">${list.map((r) => `<li class="recipe glass" data-id="${esc(r.id)}">
      <span class="file-icon">${ui('recipe')}</span>
      <span class="file-text"><strong>${esc(r.name)}</strong><small>${plural(r.steps.length, 'step')} · ${esc(stepNames(r.steps).join(' → '))}</small></span>
      <span class="recipe-actions">
        <a class="btn btn-secondary btn-sm" href="#/recipe/${esc(r.id)}" aria-label="Use ${esc(r.name)}">Use</a>
        <button class="btn-link" type="button" data-recipe-rename="${esc(r.id)}" aria-label="Rename ${esc(r.name)}">Rename</button>
        <button class="btn-link" type="button" data-recipe-delete="${esc(r.id)}" aria-label="Delete ${esc(r.name)}">Delete</button>
      </span></li>`).join('')}</ul>
    <p class="hint">Saved on this device only.</p>
  </section>`;
}

function onRecipeClick(e) {
  const rename = e.target.closest('[data-recipe-rename]');
  const del = e.target.closest('[data-recipe-delete]');
  if (rename) {
    const r = findRecipe(rename.dataset.recipeRename);
    const li = rename.closest('li');
    li.innerHTML = `<form class="recipe-rename" data-id="${esc(r.id)}">
      <label class="sr-only" for="rn-${esc(r.id)}">New name</label>
      <input class="input" id="rn-${esc(r.id)}" name="name" value="${esc(r.name)}" maxlength="80" required>
      <button class="btn btn-primary btn-sm" type="submit">Save</button>
      <button class="btn-link" type="button" data-recipe-cancel>Cancel</button></form>`;
    li.querySelector('input').select();
  } else if (e.target.closest('[data-recipe-cancel]')) {
    renderHome();
  } else if (del) {
    if (del.dataset.armed) {
      const id = del.dataset.recipeDelete;
      const gone = findRecipe(id);
      if (storeRecipes(loadRecipes().filter((r) => r.id !== id))) { renderHome(); toast(`Deleted “${gone?.name}”.`); }
      return;
    }
    del.dataset.armed = '1';
    del.textContent = 'Tap again to delete';
    del.classList.add('danger');
    setTimeout(() => { if (del.isConnected) { delete del.dataset.armed; del.textContent = 'Delete'; del.classList.remove('danger'); } }, 3500);
  }
}

function onRecipeRename(e) {
  e.preventDefault();
  const name = e.target.elements.name.value.trim();
  if (!name) return;
  const list = loadRecipes();
  const r = list.find((x) => x.id === e.target.dataset.id);
  if (r) { r.name = name; storeRecipes(list); }
  renderHome();
}

function recipeSaver(steps) {
  const extra = slotsOf(steps).length;
  return `<div class="recipe-save" id="recipe-save">
    <button class="btn btn-secondary btn-sm" type="button" data-action="save-recipe">${ui('recipe')} Save these steps as a recipe</button>
    <p class="hint">${extra ? `Run them on another file in one tap. You'll choose the ${extra === 1 ? 'file to merge or stack' : `${extra} files to merge or stack`} each time, because extra files are deleted after an hour.`
    : 'Run them on another file in one tap.'}</p></div>`;
}

function onSaverClick(e) {
  const box = $('#recipe-save');
  if (e.target.closest('[data-action="save-recipe"]')) {
    const base = state.file.filename.replace(/\.[^.]+$/, '');
    box.innerHTML = `<form class="recipe-form">
      <label for="recipe-name">Recipe name</label>
      <div class="recipe-form-row"><input class="input" id="recipe-name" name="name" value="${esc(`${base} steps`.slice(0, 80))}" maxlength="80" required>
      <button class="btn btn-primary btn-sm" type="submit">Save</button>
      <button class="btn-link" type="button" data-action="cancel-recipe">Cancel</button></div>
      <p class="hint">Saved on this device. Use it from the home screen.</p></form>`;
    $('#recipe-name').select();
  } else if (e.target.closest('[data-action="cancel-recipe"]')) {
    box.outerHTML = recipeSaver(state.file.steps);
    $('#recipe-save')?.addEventListener('click', onSaverClick);
    $('#recipe-save')?.addEventListener('submit', onSaverSubmit);
  }
}

function onSaverSubmit(e) {
  e.preventDefault();
  const name = e.target.elements.name.value.trim();
  if (!name) return;
  const list = loadRecipes();
  const same = list.find((r) => r.name.toLowerCase() === name.toLowerCase());
  const steps = withoutFiles(structuredClone(state.file.steps));
  if (same) Object.assign(same, { name, steps, updated: Date.now() });
  else {
    if (list.length >= MAX_RECIPES) { toast(`You can keep up to ${MAX_RECIPES} recipes. Delete one on the home screen first.`, 'error'); return; }
    list.unshift({ id: newId(), name, steps, created: Date.now() });
  }
  if (!storeRecipes(list)) return;
  $('#recipe-save').innerHTML = `<p class="recipe-saved">${ui('check')} ${same ? 'Updated' : 'Saved'} “${esc(name)}”. It's on the home screen.</p>`;
}

function renderRecipe(id) {
  const r = findRecipe(id);
  if (!r) { history.replaceState(null, '', '#/'); renderHome(); toast("That recipe isn't saved on this device.", 'error'); return; }
  state.tool = null;
  view.dataset.screen = 'upload';
  document.title = `${r.name} — Gridglass`;
  leaveRecipe(); // a fresh start: files chosen on an earlier visit aren't reused
  const open = state.file;
  const slots = slotsOf(r.steps);
  pending = { recipe: r, slots, files: slots.map(() => null), main: null, busy: false };
  view.innerHTML = `${topbar({ back: '#/', title: 'Recipe' })}
    <section class="intro">
      <span class="badge cat-combine">Recipe</span>
      <h1>${esc(r.name)}</h1>
      <p>Choose a file and these steps run on it, in order:</p>
      <ol class="recipe-steps">${stepNames(r.steps).map((n) => `<li>${esc(n)}</li>`).join('')}</ol>
    </section>
    ${slots.length ? `<section class="recipe-files" aria-labelledby="rf-title">
      <h2 id="rf-title">${slots.length === 1 ? 'The other file' : 'The other files'}</h2>
      <ul class="recipe-slots">${slots.map((sl, n) => `<li class="recipe-slot glass" data-slot="${n}">
        <span class="file-icon">${ui('file')}</span>
        <span class="file-text"><strong>Step ${sl.step + 1}: ${esc(sl.label)}</strong>
          <small id="slot-${n}-text">${sl.was ? `Last time: ${esc(sl.was)}` : 'Choose a file'}</small></span>
        <label class="btn btn-secondary btn-sm" for="slot-${n}">Choose</label>
        <input id="slot-${n}" class="sr-only" type="file" accept="${ACCEPT}" data-slot-input="${n}"
          aria-label="File for step ${sl.step + 1}, ${esc(sl.label)}">
      </li>`).join('')}</ul></section>` : ''}
    <section class="dropzone glass" id="drop">
      <span class="drop-icon">${ui('upload')}</span>
      <label class="btn btn-primary btn-lg" for="file">Choose a file</label>
      <input id="file" class="sr-only" type="file" accept="${ACCEPT}">
      <p class="hint">${slots.length ? 'The file to run the recipe on · ' : ''}CSV, XLSX or JSON · up to ${config.max_upload_mb} MB</p>
      <div class="progress" id="progress" hidden><div class="bar"><span id="bar"></span></div><p id="ptext" aria-live="polite">Uploading…</p></div>
    </section>
    ${open ? `<button class="btn btn-secondary btn-block" type="button" data-action="run-open">${ui('file')} Run on ${esc(open.filename)}${open.steps.length ? ' (after its steps)' : ''}</button>` : ''}
    ${privacy()}`;
  const input = $('#file');
  input.addEventListener('change', () => input.files[0] && uploadForRecipe(r, input.files[0]));
  $('[data-action="run-open"]')?.addEventListener('click', (e) => {
    e.target.closest('button').disabled = true;
    pending.main = state.file;
    readyToRun();
  });
  view.querySelectorAll('[data-slot-input]').forEach((el) => el.addEventListener('change', () => el.files[0] && uploadSlot(Number(el.dataset.slotInput), el.files[0])));
  const drop = $('#drop');
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove('over')));
  drop.addEventListener('drop', (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) uploadForRecipe(r, f); });
}

async function uploadForRecipe(r, file) {
  if (file.size > config.max_upload_mb * 1024 * 1024) {
    toast(`That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is ${config.max_upload_mb} MB.`, 'error');
    return;
  }
  const mine = pending;
  $('#progress').hidden = false;
  $('#drop label').classList.add('busy');
  try {
    const res = await uploadFile(file, (p) => { // the screen may have been left meanwhile
      if ($('#bar')) $('#bar').style.width = `${Math.round(p * 100)}%`;
      if ($('#ptext')) $('#ptext').textContent = p < 1 ? `Uploading… ${Math.round(p * 100)}%` : 'Reading your file…';
    });
    if (state.file) forget();
    remember(res.file);
    if (mine !== pending) return; // left the recipe: keep the file open, but don't run anything
    mine.main = res.file;
    await readyToRun();
  } catch (err) {
    if ($('#progress')) $('#progress').hidden = true;
    $('#drop label')?.classList.remove('busy');
    toast(err.message, 'error');
  }
}

/** The recipe screen's choices so far: the main file and one file per Merge or Stack slot. */
let pending = null;

/** Leaving the recipe screen: its extra files won't be used, so delete them now (privacy) and stop any run. */
function leaveRecipe() {
  if (!pending) return;
  pending.files.forEach((f) => f && api(`/files/${f.id}`, { method: 'DELETE' }).catch(() => {}));
  pending = null;
}

async function uploadSlot(n, file) {
  if (file.size > config.max_upload_mb * 1024 * 1024) {
    toast(`That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is ${config.max_upload_mb} MB.`, 'error');
    return;
  }
  const p = pending;
  const text = $(`#slot-${n}-text`);
  const row = $(`[data-slot="${n}"]`);
  row.classList.add('busy');
  try {
    const res = await uploadFile(file, (x) => { text.textContent = x < 1 ? `Uploading… ${Math.round(x * 100)}%` : 'Reading the file…'; });
    if (p !== pending) { api(`/files/${res.file.id}`, { method: 'DELETE' }).catch(() => {}); return; } // left the screen
    if (p.files[n]) api(`/files/${p.files[n].id}`, { method: 'DELETE' }).catch(() => {}); // replaced
    p.files[n] = res.file;
    text.textContent = `${res.file.filename} · ${plural(res.file.rows, 'row')}`;
    row.classList.add('done');
    await readyToRun();
  } catch (err) {
    text.textContent = 'Choose a file';
    toast(err.message, 'error');
  } finally { row.classList.remove('busy'); }
}

/** Run once the main file and every extra file are in; until then say what's still needed. */
async function readyToRun() {
  const p = pending;
  if (!p?.main || p.busy) return;
  const missing = p.files.filter((f) => !f).length;
  if (missing) {
    $('#progress').hidden = false;
    $('#bar').style.width = '100%';
    $('#drop label')?.classList.remove('busy');
    $('[data-action="run-open"]')?.remove(); // the main file is chosen
    $('#ptext').textContent = `${p.main.filename} is ready. Now choose ${missing === 1 ? 'the other file' : `the ${missing} other files`} above.`;
    $('.recipe-slot:not(.done) label')?.focus();
    return;
  }
  p.busy = true;
  pending = null; // the extra files now belong to the main file's steps (Start over deletes them with it)
  $('#progress').hidden = false;
  $('#ptext').textContent = 'Running the recipe…';
  const r = p.recipe;
  await runRecipe({ ...r, steps: fillFiles(r.steps, p.slots, p.files, p.main) }, p.main);
  const used = new Set((state.file?.steps ?? []).flatMap(otherFiles)); // a step that didn't fit wasn't kept
  p.files.forEach((f) => used.has(f.id) || api(`/files/${f.id}`, { method: 'DELETE' }).catch(() => {}));
}

/** Add the recipe's steps after the file's own. If one doesn't fit, keep the ones before it and say which. */
async function runRecipe(r, file) {
  const base = file.steps;
  const all = [...base, ...structuredClone(r.steps)];
  const finish = (res, extra) => {
    remember(res.file);
    state.result = { before: file.rows, after: res.preview.total_rows, op: res.file.steps.at(-1)?.op ?? null, recipe: r.name };
    location.hash = '#/result';
    if (extra) setTimeout(() => toast(extra, 'error'), 50);
  };
  try {
    finish(await api(`/files/${file.id}/steps`, { method: 'PUT', body: { steps: all } }));
  } catch (err) {
    const at = err.info?.step_index;
    if (at === undefined || at < base.length) { toast(err.message, 'error'); renderRecipe(r.id); return; }
    const n = at - base.length;
    const why = `Step ${n + 1} of the recipe (${stepNames([r.steps[n]])[0]}) doesn't fit this file: ${err.message.replace(/^Step \d+: /, '')}`;
    if (n === 0) {
      toast(`${why} Nothing was changed.`, 'error');
      if (location.hash === '#/') renderHome(); else location.hash = '#/';
      return;
    }
    try {
      finish(await api(`/files/${file.id}/steps`, { method: 'PUT', body: { steps: all.slice(0, at) } }),
        `${why} The ${plural(n, 'step')} before it ${n === 1 ? 'was' : 'were'} applied.`);
    } catch (err2) { toast(err2.message, 'error'); }
  }
}

// ---------------------------------------------------------------------------- files from other apps

/** A file shared to Gridglass from another app arrives as #/open/<id> (or #/open?error=…). */
async function openShared(hash) {
  const id = hash.match(/^#\/open\/([A-Za-z0-9_-]{22})$/)?.[1];
  const error = new URLSearchParams(hash.split('?')[1] || '').get('error');
  history.replaceState(null, '', '#/');
  renderHome();
  if (!id) { toast(error || "Couldn't open that file.", 'error'); return; }
  try {
    const meta = (await api(`/files/${id}`)).file;
    if (state.file && state.file.id !== meta.id) forget();
    remember(meta);
    renderHome();
    toast(`${meta.filename} is ready. Pick a tool.`);
  } catch (err) {
    toast(err.status === 404 ? 'That file has expired. Please share it again.' : err.message, 'error');
  }
}

async function openFromDevice(file) {
  if (file.size > config.max_upload_mb * 1024 * 1024) {
    toast(`That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is ${config.max_upload_mb} MB.`, 'error');
    return;
  }
  toast(`Opening ${file.name}…`);
  const res = await uploadFile(file, () => {});
  if (state.file) forget();
  remember(res.file);
  if (location.hash && location.hash !== '#/') location.hash = '#/'; else renderHome();
  toast(`${res.file.filename} is ready. Pick a tool.`);
}

function forget() {
  if (state.file) { // privacy: delete right away, including any second files used by Merge
    const ids = new Set([state.file.id, ...state.file.steps.flatMap(otherFiles)]);
    if (state.draft?.other) ids.add(state.draft.other);
    (state.draft?.files ?? []).forEach((f) => ids.add(f.id));
    ids.forEach((id) => api(`/files/${id}`, { method: 'DELETE' }).catch(() => {}));
  }
  remember(null);
  state.other = null;
  state.otherCols = [];
  state.result = null;
  state.editIndex = null;
}

function newFile() { forget(); renderUpload(); }

function startOver() {
  forget();
  if (location.hash === '#/' || !location.hash) renderHome(); else location.hash = '#/';
}

boot();
