/**
 * Home search that understands questions as well as tool names.
 *
 * "I want to extract a number from text" → Add column (Part of a text) and Replace values (Keep only digits).
 *
 * How it works, all in the browser (nothing typed leaves the device):
 *  1. The query is split into words; filler words ("I want to", "how do I") are dropped, plurals and
 *     endings are trimmed (duplicates → duplicat), and common synonyms map to one word (extract, get,
 *     pull → take; vlookup → lookup).
 *  2. Each tool scores by where the words appear: its name, keywords, description, then intro.
 *  3. A list of everyday tasks (INTENTS) adds a strong match and a ready-made setup, so the result opens
 *     the tool with the right option already chosen.
 * Prefixes count while typing (dup → duplicates) and one-letter typos count for longer words.
 */
import { TOOLS } from './tools.js';

const STOP = new Set(`a an the i im i'm me my we our you your it its this that these those to of in into on onto at
for from with without and or but so if then than as is are was were be been being do does did can could would should
will shall may might must want wants wanted need needs like please help how what which who whom when why way
ways just also some any all each every there here them their they he she his her use using used make made got
have has had about let lets let's i'd tell me thing things stuff something someone anyone etc`.split(/\s+/));

/** Words that appear in almost every tool: they count, but only a little. */
const WEAK = new Set(['column', 'row', 'file', 'data', 'value', 'cell', 'sheet', 'list', 'table', 'new']);

/** Synonyms → one canonical word (applied before endings are trimmed). */
const SYN = {
  extract: 'take', pull: 'take', grab: 'take', fetch: 'take', retrieve: 'take', obtain: 'take', separate: 'split',
  delete: 'remove', drop: 'remove', erase: 'remove', eliminate: 'remove', discard: 'remove', clear: 'remove', get: 'take',
  dedupe: 'duplicate', dedup: 'duplicate', dupe: 'duplicate', dupes: 'duplicate', duplicates: 'duplicate', duplicated: 'duplicate',
  repeated: 'duplicate', repeat: 'duplicate', repeats: 'duplicate', unique: 'duplicate', distinct: 'duplicate',
  vlookup: 'lookup', xlookup: 'lookup', hlookup: 'lookup', index: 'lookup', lookups: 'lookup', match: 'lookup',
  total: 'sum', totals: 'sum', subtotal: 'sum', subtotals: 'sum', aggregate: 'sum', summarise: 'summary', summarize: 'summary',
  summary: 'summary', group: 'group', per: 'group', by: 'group', wise: 'group', breakdown: 'group', grouped: 'group', grouping: 'group', groupby: 'group',
  graph: 'chart', plot: 'chart', visual: 'chart', visualise: 'chart', visualize: 'chart', diagram: 'chart', pie: 'chart', bar: 'chart',
  blank: 'blank', blanks: 'blank', empty: 'blank', missing: 'blank', null: 'blank', nulls: 'blank', na: 'blank', nan: 'blank',
  capital: 'upper', capitals: 'upper', uppercase: 'upper', caps: 'upper', upper: 'upper', lowercase: 'lower', small: 'lower',
  proper: 'title', titlecase: 'title', capitalise: 'title', capitalize: 'title',
  number: 'number', numbers: 'number', digit: 'number', digits: 'number', numeric: 'number', integer: 'number', decimal: 'number',
  numerical: 'number', figures: 'number',
  rows: 'row', record: 'row', records: 'row', line: 'row', lines: 'row', entries: 'row', entry: 'row',
  columns: 'column', field: 'column', fields: 'column', col: 'column', cols: 'column',
  tab: 'sheet', tabs: 'sheet', worksheet: 'sheet', worksheets: 'sheet', workbook: 'sheet',
  left: 'first', beginning: 'first', start: 'first', starting: 'first', leading: 'first', initial: 'first',
  right: 'last', ending: 'last', end: 'last', trailing: 'last', final: 'last', mid: 'middle', middle: 'middle',
  flip: 'transpose', rotate: 'transpose', swap: 'transpose', invert: 'transpose', transposed: 'transpose',
  arrange: 'sort', ordering: 'sort', alphabetical: 'sort', alphabetically: 'sort', ascending: 'sort',
  descending: 'sort', rearrange: 'sort', sorted: 'sort', sorting: 'sort',
  where: 'filter', condition: 'filter', conditions: 'filter', criteria: 'filter', filtered: 'filter', filtering: 'filter',
  gst: 'math', tax: 'math', vat: 'math', multiply: 'math', divide: 'math', plus: 'math', minus: 'math', times: 'math',
  calculate: 'math', calculation: 'math', formula: 'math', formulas: 'math', product: 'math', subtract: 'math', difference: 'math',
  percent: 'percent', percentage: 'percent', share: 'percent', proportion: 'percent', '%': 'percent',
  cumulative: 'running', running: 'running', ytd: 'running',
  financial: 'financial', fy: 'financial', fiscal: 'financial',
  combine: 'join', concatenate: 'join', concat: 'join', joined: 'join', joining: 'join', glue: 'join', together: 'join',
  append: 'stack', appending: 'stack', stacked: 'stack', consolidate: 'stack', monthly: 'stack',
  space: 'space', spaces: 'space', whitespace: 'space', spacing: 'space',
  convert: 'convert', converting: 'convert', export: 'convert', save: 'convert', excel: 'xlsx', xls: 'xlsx', spreadsheet: 'xlsx',
  rename: 'rename', renaming: 'rename', heading: 'header', headings: 'header', headers: 'header', titles: 'header',
  label: 'label', labels: 'label', categorise: 'label', categorize: 'label', category: 'label', categories: 'label',
  classify: 'label', tag: 'label', flag: 'label', mark: 'label',
  bucket: 'range', buckets: 'range', band: 'range', bands: 'range', bin: 'range', bins: 'range', slab: 'range', slabs: 'range',
  ranges: 'range', bracket: 'range', brackets: 'range',
  length: 'length', len: 'length', characters: 'character', chars: 'character', char: 'character', letters: 'letter',
  textbefore: 'before', textafter: 'after', substring: 'part', piece: 'part', portion: 'part', section: 'part',
  domain: 'domain', email: 'email', emails: 'email', mail: 'email',
  pad: 'pad', padding: 'pad', zeros: 'zero', zeroes: 'zero',
  pivot: 'pivot', pivottable: 'pivot', crosstab: 'pivot', unpivot: 'unpivot', melt: 'unpivot', wide: 'unpivot', long: 'unpivot',
  count: 'count', counts: 'count', counting: 'count', countif: 'count', countifs: 'count', sumif: 'sum', sumifs: 'sum',
  how_many: 'count', frequency: 'count', occurrences: 'count', tally: 'count',
  top: 'top', bottom: 'bottom', highest: 'top', lowest: 'bottom', largest: 'top', smallest: 'bottom', biggest: 'top',
  limit: 'top', head: 'top', tail: 'bottom', sample: 'top',
  fill: 'fill', autofill: 'fill', ditto: 'fill', copy: 'fill',
  pdf: 'pdf', csv: 'csv', json: 'json', xlsx: 'xlsx',
  name: 'name', names: 'name', surname: 'surname', firstname: 'name', lastname: 'surname', fullname: 'name',
  date: 'date', dates: 'date', month: 'month', months: 'month', quarter: 'quarter', quarters: 'quarter', year: 'year',
  years: 'year', weekday: 'weekday', week: 'week',
  special: 'special', symbol: 'special', symbols: 'special', punctuation: 'special', junk: 'special',
  type: 'type', types: 'type', format: 'type', formats: 'type', datatype: 'type',
};

const STEMMED = new Map();
function stem(w) {
  if (STEMMED.has(w)) return STEMMED.get(w);
  let s = w;
  if (s.length > 4 && s.endsWith('ies')) s = `${s.slice(0, -3)}y`;
  else if (s.length > 5 && s.endsWith('ing')) s = s.slice(0, -3);
  else if (s.length > 4 && s.endsWith('ed')) s = s.slice(0, -2);
  else if (s.length > 4 && /(ss|x|ch|sh)es$/.test(s)) s = s.slice(0, -2);
  else if (s.length > 3 && s.endsWith('s') && !s.endsWith('ss')) s = s.slice(0, -1);
  if (s.length > 4 && s.endsWith('e')) s = s.slice(0, -1);
  STEMMED.set(w, s);
  return s;
}

/** Text → the words that matter, trimmed and mapped to one spelling each. */
export function words(text) {
  const raw = String(text).toLowerCase()
    .replace(/<[^>]+>/g, ' ')
    .replace(/how many/g, 'how_many')
    .replace(/%/g, ' % ')
    .match(/[\p{L}\p{N}_%@'-]+/gu) || [];
  const out = [];
  for (let w of raw) {
    w = w.replace(/^['-]+|['-]+$/g, '');
    if (!w || STOP.has(w)) continue;
    if (w.includes('-') && !SYN[w]) { out.push(...words(w.replace(/-/g, ' '))); continue; }
    out.push(stem(SYN[w] ?? w));
  }
  return out;
}

/** Everyday tasks: what people ask → the tool, with its options already set. Order breaks ties. */
const INTENTS = [
  // text pieces (Add column → Part of a text)
  { q: 'take number from text code', op: 'add_column', preset: { mode: 'text', func: 'after' }, hint: 'Part of a text: text after a symbol, or first/last characters' },
  { q: 'take part of text before after between character', op: 'add_column', preset: { mode: 'text', func: 'before' }, hint: 'Part of a text' },
  { q: 'text before symbol dash comma', op: 'add_column', preset: { mode: 'text', func: 'before' }, hint: 'Part of a text → Text before…' },
  { q: 'text after symbol dash @', op: 'add_column', preset: { mode: 'text', func: 'after' }, hint: 'Part of a text → Text after…' },
  { q: 'between brackets parentheses', op: 'add_column', preset: { mode: 'text', func: 'between', find_text: '(', end_text: ')' }, hint: 'Part of a text → Text between…' },
  { q: 'first character letter', op: 'add_column', preset: { mode: 'text', func: 'first' }, hint: 'Part of a text → First characters' },
  { q: 'last character digit', op: 'add_column', preset: { mode: 'text', func: 'last' }, hint: 'Part of a text → Last characters' },
  { q: 'middle character', op: 'add_column', preset: { mode: 'text', func: 'middle' }, hint: 'Part of a text → Characters from the middle' },
  { q: 'length character count text', op: 'add_column', preset: { mode: 'text', func: 'length' }, hint: 'Part of a text → Length' },
  { q: 'find position text', op: 'add_column', preset: { mode: 'text', func: 'find' }, hint: 'Part of a text → Position of…' },
  { q: 'pad first zero', op: 'add_column', preset: { mode: 'text', func: 'pad' }, hint: 'Part of a text → Pad to a length (7 → 00007)' },
  { q: 'surname last name word', op: 'add_column', preset: { mode: 'text', func: 'word', word_from: 'true' }, hint: 'Part of a text → A word (counted from the end)' },
  { q: 'first name word', op: 'add_column', preset: { mode: 'text', func: 'word' }, hint: 'Part of a text → A word' },
  { q: 'email domain', op: 'add_column', preset: { mode: 'text', func: 'after', find_text: '@' }, hint: 'Part of a text → Text after “@”' },
  // cleaning text
  { q: 'take number only keep remove letter', op: 'replace_values', preset: { action: 'clean', clean: 'digits' }, hint: 'Clean up text → Keep only digits' },
  { q: 'remove number keep letter only', op: 'replace_values', preset: { action: 'clean', clean: 'letters' }, hint: 'Clean up text → Keep only letters' },
  { q: 'remove special character', op: 'replace_values', preset: { action: 'clean', clean: 'special' }, hint: 'Clean up text → Remove special characters' },
  { q: 'find replace substitute', op: 'replace_values', preset: { action: 'replace' }, hint: 'Find & replace' },
  { q: 'remove space trim extra', op: 'trim', hint: 'Remove spaces before, after and doubled' },
  { q: 'upper', op: 'change_case', preset: { case: 'upper' }, hint: 'Change to UPPER' },
  { q: 'lower', op: 'change_case', preset: { case: 'lower' }, hint: 'Change to lower' },
  { q: 'title', op: 'change_case', preset: { case: 'title' }, hint: 'Change to Title Case' },
  // duplicates and blanks
  { q: 'remove duplicate', op: 'remove_duplicates', preset: { action: 'remove' }, hint: 'Remove them' },
  { q: 'find show duplicate check highlight see', op: 'remove_duplicates', preset: { action: 'show' }, hint: 'Show only the duplicates' },
  { q: 'label duplicate', op: 'remove_duplicates', preset: { action: 'mark' }, hint: 'Mark them in a new column' },
  { q: 'remove blank row', op: 'remove_blank_rows', hint: 'Rows where every cell is blank' },
  { q: 'fill blank', op: 'fill_blanks', hint: 'With a value, or the row above' },
  { q: 'fill down above previous', op: 'fill_blanks', preset: { method: 'down' }, hint: 'Fill with the row above' },
  // rows and columns
  { q: 'filter row only condition', op: 'filter_rows', hint: 'Keep rows that match conditions' },
  { q: 'remove row filter contain', op: 'filter_rows', hint: 'Keep only the rows you want' },
  { q: 'sort', op: 'sort_rows' },
  { q: 'keep top bottom first last row', op: 'keep_rows' },
  { q: 'remove column', op: 'remove_columns' },
  { q: 'reorder move column', op: 'keep_columns', hint: 'Choose and reorder columns' },
  { q: 'rename header column', op: 'rename_columns' },
  { q: 'header row title first', op: 'rename_columns', hint: 'Tip: the Headers button on the file card picks the header row' },
  { q: 'text to number convert type', op: 'change_type', hint: 'Change text to numbers or dates' },
  { q: 'text to date convert type', op: 'change_type', hint: 'Change text to dates' },
  { q: 'split column comma space', op: 'split_column' },
  { q: 'split name first surname', op: 'split_column', preset: { delim: ' ' }, hint: 'Split at each space' },
  // new columns
  { q: 'join column first last name combine', op: 'add_column', preset: { mode: 'combine' }, hint: 'Join columns (first + last name)' },
  { q: 'math', op: 'add_column', preset: { mode: 'math' }, hint: 'Math (+ − × ÷)' },
  { q: 'percent sum share', op: 'add_column', preset: { mode: 'percent' }, hint: '% of total' },
  { q: 'rank', op: 'add_column', preset: { mode: 'rank' }, hint: 'Rank (1, 2, 3…)' },
  { q: 'running sum', op: 'add_column', preset: { mode: 'running_total' }, hint: 'Running total' },
  { q: 'if then else label high low', op: 'add_column', preset: { mode: 'if_then' }, hint: 'If … then … rules' },
  { q: 'month year quarter weekday date financial', op: 'add_column', preset: { mode: 'date_part' }, hint: 'Part of a date' },
  { q: 'financial year', op: 'add_column', preset: { mode: 'date_part', part: 'fy' }, hint: 'Part of a date → Financial year (FY 2025-26)' },
  { q: 'range age group number', op: 'add_column', preset: { mode: 'ranges' }, hint: 'Number ranges (0–100, 100–500…)' },
  { q: 'same value every row constant', op: 'add_column', preset: { mode: 'constant' }, hint: 'One value for every row' },
  // combining files
  { q: 'lookup two file', op: 'merge', hint: 'Bring in columns from a second file' },
  { q: 'combine two file common column', op: 'merge', hint: 'Match rows on a common column' },
  { q: 'compare two file missing', op: 'merge', hint: 'Choose “Only rows not in the other file”' },
  { q: 'stack file combine many', op: 'stack', hint: 'One file under another' },
  // summaries
  { q: 'sum group summary', op: 'pivot', hint: 'Totals for each group' },
  { q: 'count group', op: 'pivot', hint: 'Count rows in each group' },
  { q: 'average mean median group', op: 'pivot', hint: 'Average for each group' },
  { q: 'pivot', op: 'pivot' },
  { q: 'report filter page pivot sheet each group', op: 'pivot', hint: 'One sheet for each (report filter pages)' },
  { q: 'sort pivot sum largest top customer', op: 'pivot', hint: 'Sort by a value, largest first' },
  { q: 'chart', op: 'chart' },
  { q: 'transpose', op: 'unpivot', preset: { mode: 'transpose' }, hint: 'Flip rows and columns' },
  { q: 'unpivot month column row', op: 'unpivot', preset: { mode: 'unpivot' }, hint: 'Columns into rows' },
  // converting
  { q: 'convert xlsx csv json pdf', op: 'convert' },
  { q: 'split sheet file page each group separate', op: 'split_pages', hint: 'A sheet, page or file for each value' },
  { q: 'print pdf', op: 'convert', hint: 'Save as a PDF' },
];

const FIELDS = [['label', 3], ['keywords', 2], ['desc', 2], ['intro', 1]];
const INDEX = TOOLS.map((t) => ({
  tool: t,
  parts: FIELDS.map(([k, weight]) => ({ weight, set: new Set(words(t[k] || '')) })),
}));
const PARSED = INTENTS.map((it) => ({ ...it, terms: [...new Set(words(it.q))] }));

/** 0 (no match) to 1 (same word): exact, a prefix while typing, or one typo in a longer word. */
function likeness(q, word, typing = false) {
  if (q === word) return 1;
  if (typing && q.length >= 3 && word.startsWith(q)) return 0.7;
  if (q.length >= 5 && word.length >= 5 && Math.abs(q.length - word.length) <= 1 && oneEdit(q, word)) return 0.6;
  return 0;
}
function oneEdit(a, b) {
  let i = 0;
  while (i < a.length && a[i] === b[i]) i += 1;
  return a.slice(i + (a.length >= b.length ? 1 : 0)) === b.slice(i + (b.length >= a.length ? 1 : 0))
    || (a.length === b.length && a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2));
}
const best = (q, set, typing) => { let m = 0; for (const w of set) { m = Math.max(m, likeness(q, w, typing)); if (m === 1) break; } return m; };

/**
 * Rank tools for what was typed. Each result: { tool, score, hint, preset }.
 * One result per tool; a matching everyday task adds its hint and ready-made options.
 */
export function searchTools(query) {
  const q = words(query);
  if (!q.length) return [];
  // Only the last word may be unfinished ("remove dup"): it matches the start of longer words.
  const typing = (i) => i === q.length - 1 && !/\s$/.test(query);
  const results = new Map();
  for (const { tool, parts } of INDEX) {
    let score = 0;
    q.forEach((term, i) => {
      const weak = WEAK.has(term) ? 0.3 : 1;
      score += weak * Math.max(...parts.map((p) => p.weight * best(term, p.set, typing(i))));
    });
    if (score > 0) results.set(tool.op, { tool, base: score, intent: 0, hint: '', preset: null });
  }
  for (const it of PARSED) {
    let hits = 0;
    for (const term of it.terms) hits += Math.max(...q.map((x, i) => (WEAK.has(x) ? 0.6 : 1) * likeness(x, term, typing(i))));
    // how much of the question this task explains
    const covered = q.filter((x, i) => it.terms.some((t) => likeness(x, t, typing(i)) > 0)).length / q.length;
    // two words in common, or everything that was asked ("vlookup", "surname")
    if (hits < Math.min(2, it.terms.length) * 0.8 && !(covered === 1 && hits >= 0.7)) continue;
    const score = 4 * hits + 6 * covered;
    const r = results.get(it.op) ?? { tool: TOOLS.find((t) => t.op === it.op), base: 0, intent: 0, hint: '', preset: null };
    if (score > r.intent) Object.assign(r, { intent: score, hint: it.hint || '', preset: it.preset || null });
    results.set(it.op, r);
  }
  return [...results.values()].map((r) => ({ ...r, score: r.base + r.intent })).sort((a, b) => b.score - a.score);
}

/** The address that opens a tool with a result's options already chosen. */
export function hrefFor(r) {
  const p = r.preset ? `?${new URLSearchParams(r.preset)}` : '';
  return `#/tool/${r.tool.op}${p}`;
}
