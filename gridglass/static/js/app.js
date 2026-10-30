import {
  AGG_FUNCS, CATS, FORMATS, NO_VALUE_OPS, OPERATORS, SUGGEST, TOOL, TOOLS, TYPES, UI, defaults, icon, incomplete, toStep,
} from './tools.js';

const API = '/api/v1';
const desktop = window.matchMedia('(min-width: 1024px)');
const previewRows = () => (desktop.matches ? 200 : 50); // the big desktop preview shows more rows
const $ = (s, el = document) => el.querySelector(s);
const view = $('#view');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const num = (x) => Number(x).toLocaleString('en-IN');
const plural = (k, w) => `${num(k)} ${w}${k === 1 ? '' : 's'}`;
const ui = (name, cls) => icon(UI[name], cls);

const config = { max_upload_mb: 50, retention_minutes: 60 };
const state = {
  file: null,      // server metadata of the current upload (id, filename, steps …)
  cols: [],        // column stats after the saved steps
  tool: null,
  stage: 'upload', // upload | options | done
  draft: {},
  before: 0,       // rows before the step being designed
  result: null,    // { before, after } after applying
  previewOk: false,
};

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
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// ============================================================================ routing & shared bits

let firstRoute = true;

function route() {
  const m = location.hash.match(/^#\/tool\/([a-z_]+)/);
  if (m && TOOL[m[1]]) openTool(TOOL[m[1]]);
  else renderHome();
  window.scrollTo(0, 0);
  // Move focus to the new screen for screen readers, but not on first load (keeps "Skip to content" first).
  if (!firstRoute) view.focus({ preventScroll: true });
  firstRoute = false;
}

function topbar({ back, title, close } = {}) {
  const left = back
    ? `<a class="icon-btn" href="${back}" aria-label="Back">${ui('back')}</a><span class="topbar-title">${esc(title)}</span>`
    : close
      ? `<span class="topbar-title">${esc(title || '')}</span>`
      : `<a class="brand" href="#/" aria-label="Gridglass home">${logo()}<span>Gridglass</span></a>`;
  const right = close ? `<a class="icon-btn" href="${close}" aria-label="Close">${ui('close')}</a>` : '';
  const label = document.documentElement.dataset.theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
  return `<header class="topbar">${left}<span class="spacer"></span>
    <button class="icon-btn glass theme-btn" type="button" data-action="theme" aria-label="${label}">${ui('moon', 'when-light')}${ui('sun', 'when-dark')}</button>${right}</header>`;
}

const logo = () => `<svg class="logo" viewBox="0 0 30 30" aria-hidden="true"><rect x="1" y="1" width="28" height="28" rx="8"/><path d="M8 11h14M8 15.5h14M8 20h14M12.5 8v14M17.5 8v14"/></svg>`;
const privacy = () => `<footer class="privacy">${ui('lock')}<span>Your files are private and deleted automatically after ${config.retention_minutes} minutes.</span></footer>`;

function fileChip() {
  const f = state.file;
  const sheets = f.sheets?.length > 1
    ? `<label class="sr-only" for="sheet">Sheet</label><select id="sheet" class="input input-sm">${f.sheets.map((s) =>
      `<option ${s === f.sheet ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select>` : '';
  return `<div class="file-chip glass">
    <span class="file-icon">${ui('file')}</span>
    <span class="file-text"><strong>${esc(f.filename)}</strong><small>${plural(state.before, 'row')} · ${plural(state.cols.length, 'column')}${f.steps.length ? ` · ${plural(f.steps.length, 'step')} applied` : ''}</small></span>
    ${sheets}
    <button class="btn-link" type="button" data-action="newfile">Change</button>
  </div>`;
}

function table(pv) {
  if (!pv.columns.length) return '<p class="empty">No columns left.</p>';
  const head = pv.columns.map((c) => `<th scope="col"><span>${esc(c.name)}</span><small>${esc(c.type)}</small></th>`).join('');
  const body = pv.rows.length
    ? pv.rows.map((r) => `<tr>${r.map((v) => (v === null
      ? '<td class="null"><span class="sr-only">blank</span></td>'
      : `<td title="${esc(v)}">${esc(typeof v === 'boolean' ? (v ? 'true' : 'false') : v)}</td>`)).join('')}</tr>`).join('')
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
      <button class="btn-link" type="button" data-action="startover">Clear</button>
    </div>` : '';
  view.dataset.screen = 'home';
  view.innerHTML = `${topbar()}
    <section class="hero">
      <h1>Every spreadsheet tool you need, one tap away.</h1>
      <p>Clean, reshape and convert CSV and Excel files on your phone or computer. Free, no sign-up.</p>
    </section>
    ${working}
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
  state.tool = tool;
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
  view.innerHTML = `${topbar({ back: '#/', title: 'All tools' })}
    <section class="intro">
      <span class="badge cat-${t.cat}">${CATS[t.cat]}</span>
      <h1>${t.label}</h1>
      <p>${t.intro}</p>
    </section>
    <section class="dropzone glass" id="drop">
      <span class="drop-icon">${ui('upload')}</span>
      <label class="btn btn-primary btn-lg" for="file">Choose a file</label>
      <input id="file" class="sr-only" type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.json,.jsonl,.ndjson">
      <p class="hint">CSV, Excel or JSON · up to ${config.max_upload_mb} MB</p>
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
  } catch (err) {
    progress.hidden = true;
    view.querySelectorAll('.busy').forEach((el) => el.classList.remove('busy'));
    $('#file').value = '';
    toast(err.message, 'error');
  }
}

function sampleFile() {
  const rows = [['Order ID', 'Customer', 'Email', 'City', 'Amount', 'Order date']];
  const people = [['  Asha Rao ', 'asha@example.com'], ['Ravi Kumar', 'ravi@example.com'], ['meera iyer', 'meera@example.com'],
    ['Dev Singh', 'dev@example.com'], ['', ''], ['Priya  Nair', 'priya@example.com']];
  const cities = ['Pune', 'Delhi', 'Mumbai', 'Bengaluru', 'Chennai'];
  for (let i = 1; i <= 40; i += 1) {
    const [name, email] = people[i % people.length];
    rows.push([1000 + i, name, email, cities[(i * 7) % cities.length], (i * 137.5) % 900 + 99,
      `2026-${String((i % 9) + 1).padStart(2, '0')}-${String((i % 27) + 1).padStart(2, '0')}`]);
    if (i % 8 === 0) rows.push([...rows.at(-1)]); // a few exact duplicates
  }
  const csv = rows.map((r) => r.map((v) => (/[",]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v)).join(',')).join('\n');
  return new File([csv], 'sample-orders.csv', { type: 'text/csv' });
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
  renderOptions();
}

function renderOptions() {
  const t = state.tool;
  state.stage = 'options';
  view.dataset.screen = 'options';
  const action = t.convert
    ? `<div class="field"><label class="field-label" for="fmt">Save as</label>${formatSelect()}</div>`
    : '';
  view.innerHTML = `${topbar({ back: '#/', title: t.label })}
    ${fileChip()}
    ${t.convert ? '' : `<form id="opts" class="form" novalidate autocomplete="off"></form>`}
    ${action}
    <section class="preview" aria-labelledby="pv-title">
      <div class="preview-head"><h2 id="pv-title">Preview</h2><span class="pill" id="pv-badge" aria-live="polite"></span></div>
      <div class="table-wrap glass" id="pv" tabindex="0" aria-label="Preview table"><div class="skeleton"></div></div>
      <p class="hint" id="pv-note"></p>
    </section>
    <div class="action-bar">
      ${t.convert
        ? `<button class="btn btn-primary btn-lg btn-block" type="button" data-action="download">${ui('download')} Download</button>`
        : `<button class="btn btn-primary btn-lg btn-block" type="button" id="apply" disabled>${esc(t.verb)}</button>`}
    </div>`;
  $('[data-action="newfile"]').addEventListener('click', newFile);
  $('#sheet')?.addEventListener('change', (e) => changeSheet(e.target.value));
  if (t.convert) {
    $('[data-action="download"]').addEventListener('click', (e) => download($('#fmt').value, e.currentTarget));
    showPreview(state.file.steps);
    return;
  }
  const form = $('#opts');
  renderForm();
  form.addEventListener('input', onFormInput);
  form.addEventListener('change', onFormInput);
  form.addEventListener('click', onFormClick);
  form.addEventListener('submit', (e) => e.preventDefault());
  $('#apply').addEventListener('click', apply);
  schedulePreview(0);
}

function formatSelect() {
  const ext = (state.file.filename.split('.').pop() || '').toLowerCase();
  const pick = ['csv', 'json'].includes(ext) ? 'xlsx' : 'csv';
  return `<select id="fmt" class="input">${FORMATS.map(([v, l]) => `<option value="${v}" ${v === pick ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
}

// ---------------------------------------------------------------------------- form

const colsFor = (filter) => state.cols.filter((c) => !filter
  || (filter === 'text' ? c.type === 'text' : filter === 'number' ? ['integer', 'decimal'].includes(c.type) : true));

const opt = (v, l, sel) => `<option value="${esc(v)}" ${v === sel ? 'selected' : ''}>${esc(l)}</option>`;
const colOptions = (filter, sel, placeholder = 'Choose a column') =>
  `<option value="" ${sel ? '' : 'selected'} disabled>${placeholder}</option>${colsFor(filter).map((c) => opt(c.name, c.name, sel)).join('')}`;

function seg(key, options, value, label) {
  return `<div class="seg" role="group" aria-label="${esc(label)}">${options.map(([v, l]) =>
    `<button type="button" data-seg="${key}" data-val="${esc(v)}" aria-pressed="${v === value}">${esc(l)}</button>`).join('')}</div>`;
}

const FIELD = {
  columns(f, v) {
    const all = f.optional && v === null;
    const cols = colsFor(f.filter);
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
  column: (f, v) => `<select class="input" id="f-${f.key}" data-key="${f.key}">${colOptions(f.filter, v)}</select>`,
  select: (f, v) => `<select class="input" id="f-${f.key}" data-key="${f.key}">${f.options.map(([o, l]) => opt(o, l, v)).join('')}</select>`,
  choice: (f, v) => seg(f.key, f.options, v, f.label),
  text: (f, v) => `<input class="input" id="f-${f.key}" data-key="${f.key}" value="${esc(v)}" placeholder="${esc(f.placeholder || '')}">`,
  number: (f, v) => `<input class="input" id="f-${f.key}" data-key="${f.key}" type="number" inputmode="decimal" value="${esc(v)}"
    ${f.min !== undefined ? `min="${f.min}"` : ''} ${f.max !== undefined ? `max="${f.max}"` : ''} step="${f.step || 1}">`,
  toggle: (f, v) => `<label class="toggle"><input type="checkbox" data-key="${f.key}" ${v ? 'checked' : ''}><span class="switch" aria-hidden="true"></span><span>${esc(f.label)}</span></label>`,
  conditions(f, rows) {
    return `${rows.map((c, i) => `<div class="row-card glass">
      <div class="row-grid">
        <label class="sr-only" for="c${i}col">Column</label>
        <select class="input" id="c${i}col" data-list="conditions" data-i="${i}" data-prop="column">${colOptions(null, c.column)}</select>
        <label class="sr-only" for="c${i}op">Condition</label>
        <select class="input" id="c${i}op" data-list="conditions" data-i="${i}" data-prop="operator" data-rerender>${OPERATORS.map(([o, l]) => opt(o, l, c.operator)).join('')}</select>
        ${NO_VALUE_OPS.has(c.operator) ? '' : `<label class="sr-only" for="c${i}v">Value</label>
        <input class="input" id="c${i}v" data-list="conditions" data-i="${i}" data-prop="value" value="${esc(c.value)}"
          placeholder="${c.operator === 'in_list' ? 'Pune, Delhi, Mumbai' : 'Value'}">`}
      </div>
      ${rows.length > 1 ? `<button type="button" class="icon-btn small" data-remove="conditions" data-i="${i}" aria-label="Remove condition ${i + 1}">${ui('trash')}</button>` : ''}
    </div>`).join('')}
    <button type="button" class="btn btn-secondary btn-sm" data-add="conditions">${ui('plus')} Add condition</button>`;
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
      <button type="button" class="btn btn-secondary btn-sm" data-add="aggs">${ui('plus')} Add calculation</button>`;
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
  rename(f, mapping) {
    return `<div class="rename-list">${state.cols.map((c, i) => `<div class="rename-row">
      <label for="r${i}">${esc(c.name)}</label>
      <input class="input" id="r${i}" data-rename="${esc(c.name)}" value="${esc(mapping[c.name] || '')}" placeholder="${esc(c.name)}">
    </div>`).join('')}</div>`;
  },
};

const NEW_ROW = {
  conditions: () => ({ column: state.cols[0]?.name ?? '', operator: 'equals', value: '' }),
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
  if (el.dataset.key) {
    d[el.dataset.key] = el.type === 'checkbox' ? el.checked : el.value;
    if (e.type === 'change' && (el.tagName === 'SELECT' || el.type === 'checkbox')) renderForm();
  } else if (el.dataset.list) {
    d[el.dataset.list][Number(el.dataset.i)][el.dataset.prop] = el.value;
    if (e.type === 'change' && 'rerender' in el.dataset) renderForm();
  } else if (el.dataset.rename !== undefined) {
    d.mapping[el.dataset.rename] = el.value;
  } else return;
  if (e.type === 'input' || el.tagName === 'SELECT' || el.type === 'checkbox') schedulePreview();
}

function onFormClick(e) {
  const b = e.target.closest('button');
  if (!b) return;
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
    d[f.key] = colsFor(f.filter).map((c) => c.name);
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

// ---------------------------------------------------------------------------- preview

let previewTimer;
let previewSeq = 0;

function schedulePreview(delay = 350) {
  state.previewOk = false;
  const btn = $('#apply');
  if (btn) btn.disabled = true;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => {
    const hint = incomplete(state.tool, state.draft);
    if (hint) { showPreview(state.file.steps, null, hint); return; } // show the data as it is, plus what's missing
    const step = toStep(state.tool, state.draft);
    showPreview([...state.file.steps, step], step);
  }, delay);
}

async function showPreview(steps, step, hint = null) {
  const seq = ++previewSeq;
  const box = $('#pv');
  const badge = $('#pv-badge');
  const note = $('#pv-note');
  box.classList.add('loading');
  try {
    const { preview } = await api(`/files/${state.file.id}/preview?limit=${previewRows()}`, { method: 'POST', body: { steps } });
    if (seq !== previewSeq) return;
    box.classList.remove('loading', 'error');
    box.innerHTML = table(preview);
    const diff = preview.total_rows - state.before;
    badge.dataset.kind = diff < 0 ? 'warn' : 'ok';
    badge.textContent = hint ? '' : !step ? plural(preview.total_rows, 'row')
      : diff < 0 ? `${num(-diff)} fewer rows` : diff > 0 ? `${num(diff)} more rows` : plural(preview.total_rows, 'row');
    const colDiff = preview.columns.length - state.cols.length;
    note.classList.toggle('needs', Boolean(hint));
    note.textContent = [
      hint || '',
      preview.truncated ? `Showing the first ${num(preview.rows.length)} of ${num(preview.total_rows)} rows.` : '',
      colDiff ? `${colDiff > 0 ? '+' : '−'}${plural(Math.abs(colDiff), 'column')}.` : '',
    ].filter(Boolean).join(' ');
    state.previewOk = !hint;
    const btn = $('#apply');
    if (btn) btn.disabled = Boolean(hint);
  } catch (err) {
    if (seq !== previewSeq) return;
    box.classList.remove('loading');
    box.classList.add('error');
    badge.textContent = '';
    note.textContent = '';
    box.innerHTML = `<p class="form-error">${ui('alert')}<span>${esc(friendly(err))}</span></p>`;
  }
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
  try {
    const res = await api(`/files/${state.file.id}/steps`, { method: 'POST', body: toStep(state.tool, state.draft) });
    remember(res.file);
    state.result = { before: state.before, after: res.preview.total_rows };
    renderDone();
  } catch (err) {
    btn.classList.remove('busy');
    btn.disabled = false;
    toast(friendly(err), 'error');
  }
}

function renderDone() {
  const t = state.tool;
  const { before, after } = state.result;
  state.stage = 'done';
  view.dataset.screen = 'done';
  const title = t.done ? t.done(before, after) : `${t.label} done`;
  const suggestions = SUGGEST.filter((op) => op !== t.op).slice(0, 6);
  const steps = state.file.steps;
  view.innerHTML = `${topbar({ close: '#/' })}
    <section class="done">
      <span class="done-icon">${ui('check')}</span>
      <h1>${esc(title)}</h1>
      <p>${before === after ? plural(after, 'row') : `${num(before)} rows → ${num(after)} rows`}</p>
    </section>
    <section class="card glass">
      <div class="field"><label class="field-label" for="fmt">Download as</label>${formatSelect()}</div>
      <button class="btn btn-primary btn-lg btn-block" type="button" data-action="download">${ui('download')} Download file</button>
      ${navigator.share ? `<button class="btn btn-secondary btn-block" type="button" data-action="share">${ui('share')} Share</button>` : ''}
    </section>
    <section class="next">
      <h2>Keep working on this file</h2>
      <p class="hint">The result goes straight into the next tool.</p>
      <div class="chips wrap">${suggestions.map((op) => `<a class="chip" href="#/tool/${op}">${TOOL[op].label}</a>`).join('')}
        <a class="chip" href="#/">All tools…</a></div>
    </section>
    <section class="applied">
      <h2>Applied steps</h2>
      <ol class="step-list">${steps.map((s, i) => `<li class="glass"><span class="step-n">${i + 1}</span>
        <span class="step-name">${esc(TOOL[s.op]?.label || s.op)}</span>
        <button type="button" class="icon-btn small" data-undo="${i}" aria-label="Undo step ${i + 1}: ${esc(TOOL[s.op]?.label || s.op)}">${ui('trash')}</button></li>`).join('')
        || '<li class="glass empty">No steps — this is your original file.</li>'}</ol>
    </section>
    <footer class="done-foot"><button type="button" class="btn-link" data-action="startover">Start over with a new file</button></footer>`;
  $('[data-action="download"]').addEventListener('click', (e) => download($('#fmt').value, e.currentTarget));
  $('[data-action="share"]')?.addEventListener('click', (e) => share($('#fmt').value, e.currentTarget));
  $('[data-action="startover"]').addEventListener('click', startOver);
  view.querySelectorAll('[data-undo]').forEach((b) => b.addEventListener('click', () => undo(Number(b.dataset.undo))));
}

async function undo(i) {
  try {
    const res = await api(`/files/${state.file.id}/steps/${i}`, { method: 'DELETE' });
    remember(res.file);
    state.result = { ...state.result, after: res.preview.total_rows };
    renderDone();
    toast('Step removed.');
  } catch (err) { toast(err.message, 'error'); }
}

// ---------------------------------------------------------------------------- download & share

async function fetchExport(fmt) {
  const res = await fetch(`${API}/files/${state.file.id}/export?format=${encodeURIComponent(fmt)}`).catch(() => null);
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

function download(fmt, btn) {
  return withBusy(btn, async () => {
    const { blob, name } = await fetchExport(fmt);
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement('a'), { href: url, download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
    toast(`Saved ${name}`);
  });
}

function share(fmt, btn) {
  return withBusy(btn, async () => {
    const { blob, name } = await fetchExport(fmt);
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
  } catch (err) { toast(err.message, 'error'); }
}

function forget() {
  if (state.file) api(`/files/${state.file.id}`, { method: 'DELETE' }).catch(() => {}); // privacy: delete right away
  remember(null);
}

function newFile() { forget(); renderUpload(); }

function startOver() {
  forget();
  if (location.hash === '#/' || !location.hash) renderHome(); else location.hash = '#/';
}

boot();
