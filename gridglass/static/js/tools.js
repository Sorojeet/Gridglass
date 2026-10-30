// Tool catalogue: what each tool is called, which options it asks for, and how those options
// become an API step. The server validates every step, so these are UI hints, not the rules.

export const CATS = {
  clean: 'Clean',
  shape: 'Shape',
  summarize: 'Summarize',
  convert: 'Convert',
};

const P = {
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 4H6a2 2 0 0 0-2 2v10"/>',
  trim: '<path d="M4 12h16M4 12l3-3M4 12l3 3M20 12l-3-3M20 12l-3 3"/>',
  case: '<path d="M3 18 7 6l4 12M4.5 14h5M14 18v-4.5a2.75 2.75 0 0 1 5.5 0V18M14 15.5h5.5"/>',
  replace: '<path d="M4 7h11l-3-3M20 17H9l3 3"/>',
  fill: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  blankrows: '<rect x="4" y="4" width="16" height="5" rx="1.5"/><rect x="4" y="15" width="16" height="5" rx="1.5"/><path d="M9 12h6"/>',
  removecols: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 4v16M15 10l4 4M19 10l-4 4"/>',
  keepcols: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9.5 4v16M14.5 4v16"/>',
  rename: '<path d="M4 20h4L19 9l-4-4L4 16v4zM13 7l4 4"/>',
  filter: '<path d="M4 5h16l-6 8v6l-4-2v-4L4 5z"/>',
  sort: '<path d="M7 4v16M4 17l3 3 3-3M13 6h7M13 12h5M13 18h3"/>',
  keeprows: '<path d="M4 6h16M4 10.5h16M4 15h9M4 19.5h5"/>',
  type: '<path d="M5 7V5h14v2M12 5v14M9 19h6"/>',
  split: '<rect x="3" y="6" width="7" height="12" rx="2"/><rect x="14" y="6" width="7" height="12" rx="2"/>',
  addcol: '<rect x="3" y="4" width="11" height="16" rx="2"/><path d="M19 9v6M16 12h6"/>',
  group: '<path d="M5 20V10M12 20V4M19 20v-7"/>',
  pivot: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 9.5h16M9.5 4v16"/>',
  unpivot: '<path d="M6 4v16h14M10 8h8M10 12h8M10 16h8"/>',
  convert: '<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
};

export const icon = (name, cls = '') =>
  `<svg class="ico ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] ?? name}</svg>`;

export const UI = {
  back: '<path d="M15 5l-7 7 7 7"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
  download: '<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>',
  share: '<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v13"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"/><path d="M14 3v5h5"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  sample: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M10 4v16"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/>',
};

// ----------------------------------------------------------------------------- option labels

export const OPERATORS = [
  ['equals', 'is'], ['not_equals', 'is not'], ['contains', 'contains'], ['not_contains', "doesn't contain"],
  ['starts_with', 'starts with'], ['ends_with', 'ends with'], ['greater_than', 'is more than'],
  ['greater_or_equal', 'is at least'], ['less_than', 'is less than'], ['less_or_equal', 'is at most'],
  ['is_blank', 'is blank'], ['not_blank', 'is not blank'], ['in_list', 'is one of'],
];
export const NO_VALUE_OPS = new Set(['is_blank', 'not_blank']);

export const AGG_FUNCS = [
  ['sum', 'Sum'], ['average', 'Average'], ['count_rows', 'Count rows'], ['count', 'Count values'],
  ['count_distinct', 'Count unique'], ['min', 'Smallest'], ['max', 'Largest'], ['median', 'Median'],
  ['first', 'First'], ['last', 'Last'],
];

export const TYPES = [
  ['text', 'Text'], ['integer', 'Whole number'], ['decimal', 'Decimal number'],
  ['boolean', 'True / false'], ['date', 'Date'], ['datetime', 'Date & time'],
];

const DELIMS = [[',', 'Comma ,'], [' ', 'Space'], [';', 'Semicolon ;'], ['-', 'Dash -'], ['/', 'Slash /'],
  ['|', 'Bar |'], ['custom', 'Something else']];

const n = (x) => Number(x).toLocaleString('en-IN');
const plural = (k, word) => `${n(k)} ${word}${k === 1 ? '' : 's'}`;
const first = (cols, type) => (cols.find((c) => !type || c.type === type) ?? cols[0])?.name ?? '';

// ----------------------------------------------------------------------------- tools
// field types: columns (multi), column (single), choice, select, text, number, toggle,
//              conditions, aggs, sortkeys, types, rename.  `show(d)` hides a field.

export const TOOLS = [
  {
    op: 'remove_duplicates', cat: 'clean', icon: 'copy', label: 'Remove duplicates',
    desc: 'Find and drop repeated rows', keywords: 'dedupe unique repeated same',
    intro: "We'll find repeated rows, show you what's left, and give you a clean file back.",
    verb: 'Remove duplicates',
    fields: [
      { key: 'columns', type: 'columns', label: 'A row is a duplicate when', optional: true,
        allLabel: 'All columns match', someLabel: 'Chosen columns match', default: null },
      { key: 'keep', type: 'choice', label: 'Which copy to keep', default: 'first',
        options: [['first', 'First one'], ['last', 'Last one']] },
    ],
    build: (d) => ({ columns: d.columns, keep: d.keep }),
    done: (b, a) => (b > a ? `${plural(b - a, 'duplicate row')} removed` : 'No duplicates found'),
  },
  {
    op: 'trim', cat: 'clean', icon: 'trim', label: 'Trim spaces',
    desc: 'Strip extra spaces from text', keywords: 'whitespace clean spaces strip',
    intro: 'Removes spaces before and after text, which often break matching and lookups.',
    verb: 'Trim spaces',
    fields: [
      { key: 'columns', type: 'columns', label: 'Columns', optional: true, filter: 'text',
        allLabel: 'All text columns', default: null },
      { key: 'collapse_spaces', type: 'toggle', label: 'Also turn double spaces inside text into one', default: true },
    ],
    build: (d) => ({ columns: d.columns, collapse_spaces: d.collapse_spaces }),
  },
  {
    op: 'change_case', cat: 'clean', icon: 'case', label: 'Change case',
    desc: 'UPPER, lower or Title Case', keywords: 'capital uppercase lowercase proper',
    intro: 'Make text consistent: all capitals, all small letters, or Each Word Capitalised.',
    verb: 'Change case',
    fields: [
      { key: 'columns', type: 'columns', label: 'Columns', filter: 'text', default: [] },
      { key: 'case', type: 'choice', label: 'Change to', default: 'title',
        options: [['upper', 'UPPER'], ['lower', 'lower'], ['title', 'Title']] },
    ],
    build: (d) => ({ columns: d.columns, case: d.case }),
  },
  {
    op: 'replace_values', cat: 'clean', icon: 'replace', label: 'Replace values',
    desc: 'Find and replace in columns', keywords: 'find substitute swap',
    intro: 'Swap one value for another, as a whole cell or anywhere inside the text.',
    verb: 'Replace',
    fields: [
      { key: 'columns', type: 'columns', label: 'Columns', default: [] },
      { key: 'find', type: 'text', label: 'Find', placeholder: 'e.g. N/A', default: '' },
      { key: 'replace', type: 'text', label: 'Replace with', placeholder: 'leave empty to clear it', default: '' },
      { key: 'match', type: 'choice', label: 'Match', default: 'whole',
        options: [['whole', 'Whole cell'], ['part', 'Part of the text']] },
      { key: 'case_sensitive', type: 'toggle', label: 'Match capital letters exactly', default: false },
    ],
    build: (d) => ({ columns: d.columns, find: d.find, replace: d.replace, match: d.match, case_sensitive: d.case_sensitive }),
    ready: (d) => (d.find ? null : 'Type what to find.'),
  },
  {
    op: 'fill_blanks', cat: 'clean', icon: 'fill', label: 'Fill blanks',
    desc: 'Fill empty cells or copy down', keywords: 'empty missing null fill down',
    intro: 'Put a value into empty cells, or copy the value from the row above.',
    verb: 'Fill blanks',
    fields: [
      { key: 'columns', type: 'columns', label: 'Columns', optional: true, default: null },
      { key: 'method', type: 'choice', label: 'Fill with', default: 'value',
        options: [['value', 'A value'], ['down', 'Row above'], ['up', 'Row below']] },
      { key: 'value', type: 'text', label: 'Value', placeholder: 'e.g. 0 or Unknown', default: '',
        show: (d) => d.method === 'value' },
    ],
    build: (d) => ({ columns: d.columns, method: d.method, value: d.method === 'value' ? d.value : undefined }),
    ready: (d) => (d.method === 'value' && !d.value ? 'Type a value to fill the blanks with.' : null),
  },
  {
    op: 'remove_blank_rows', cat: 'clean', icon: 'blankrows', label: 'Remove blank rows',
    desc: 'Drop empty or incomplete rows', keywords: 'empty rows delete',
    intro: 'Get rid of empty rows — or rows missing something important.',
    verb: 'Remove blank rows',
    fields: [
      { key: 'when', type: 'choice', label: 'Remove a row when', default: 'all_blank',
        options: [['all_blank', 'Every cell is blank'], ['any_blank', 'Any cell is blank']] },
      { key: 'columns', type: 'columns', label: 'Look at', optional: true, default: null },
    ],
    build: (d) => ({ columns: d.columns, when: d.when }),
    done: (b, a) => (b > a ? `${plural(b - a, 'blank row')} removed` : 'No blank rows found'),
  },
  {
    op: 'filter_rows', cat: 'shape', icon: 'filter', label: 'Filter rows',
    desc: 'Keep only rows that match', keywords: 'where condition search keep',
    intro: 'Keep the rows you need: by text, numbers, dates or blanks.',
    verb: 'Filter rows',
    fields: [
      { key: 'conditions', type: 'conditions', label: 'Keep rows where',
        default: (cols) => [{ column: first(cols, 'text'), operator: 'equals', value: '' }] },
      { key: 'match', type: 'choice', label: 'Rows must match', default: 'all',
        options: [['all', 'All conditions'], ['any', 'Any condition']], show: (d) => d.conditions.length > 1 },
    ],
    build: (d) => ({
      match: d.match,
      conditions: d.conditions.map((c) => ({
        column: c.column, operator: c.operator,
        ...(NO_VALUE_OPS.has(c.operator) ? {} : {
          value: c.operator === 'in_list' ? c.value.split(',').map((s) => s.trim()).filter(Boolean) : c.value,
        }),
      })),
    }),
    done: (b, a) => `${plural(a, 'row')} kept of ${n(b)}`,
    ready: (d) => (d.conditions.some((c) => !NO_VALUE_OPS.has(c.operator) && !String(c.value).trim()) ? 'Type a value to filter by.' : null),
  },
  {
    op: 'sort_rows', cat: 'shape', icon: 'sort', label: 'Sort rows',
    desc: 'A to Z, smallest first and more', keywords: 'order arrange ascending descending',
    intro: 'Sort by one column, then by another to break ties.',
    verb: 'Sort rows',
    fields: [{ key: 'by', type: 'sortkeys', label: 'Sort by', default: (cols) => [{ column: first(cols), order: 'asc' }] }],
    build: (d) => ({ by: d.by.map((k) => ({ column: k.column, descending: k.order === 'desc' })) }),
  },
  {
    op: 'remove_columns', cat: 'shape', icon: 'removecols', label: 'Remove columns',
    desc: "Delete the columns you don't need", keywords: 'delete drop columns',
    intro: 'Tap the columns to remove.',
    verb: 'Remove columns',
    fields: [{ key: 'columns', type: 'columns', label: 'Columns to remove', default: [] }],
    build: (d) => ({ columns: d.columns }),
  },
  {
    op: 'keep_columns', cat: 'shape', icon: 'keepcols', label: 'Choose & reorder columns',
    desc: 'Keep some columns, in your order', keywords: 'select reorder arrange move columns',
    intro: 'Tap columns in the order you want them. Everything else is left out.',
    verb: 'Keep these columns',
    fields: [{ key: 'columns', type: 'columns', label: 'Columns, in order', ordered: true, default: [] }],
    build: (d) => ({ columns: d.columns }),
  },
  {
    op: 'rename_columns', cat: 'shape', icon: 'rename', label: 'Rename columns',
    desc: 'Give columns clearer names', keywords: 'header title name',
    intro: 'Type a new name next to any column you want to rename.',
    verb: 'Rename columns',
    fields: [{ key: 'mapping', type: 'rename', label: 'New names', default: () => ({}) }],
    build: (d) => ({
      mapping: Object.fromEntries(Object.entries(d.mapping)
        .map(([k, v]) => [k, v.trim()]).filter(([k, v]) => v && v !== k)),
    }),
    ready: (d) => (Object.values(d.mapping).some((v) => v.trim()) ? null : 'Type a new name next to any column.'),
  },
  {
    op: 'keep_rows', cat: 'shape', icon: 'keeprows', label: 'Keep top or bottom rows',
    desc: 'First or last N rows', keywords: 'limit head tail top bottom first last',
    intro: 'Keep only the first or last rows — handy after sorting.',
    verb: 'Keep rows',
    fields: [
      { key: 'position', type: 'choice', label: 'Keep', default: 'top', options: [['top', 'First rows'], ['bottom', 'Last rows']] },
      { key: 'count', type: 'number', label: 'How many', min: 1, default: '10' },
    ],
    build: (d) => ({ position: d.position, count: Number(d.count) || undefined }),
    ready: (d) => (Number(d.count) >= 1 ? null : 'Type how many rows to keep.'),
  },
  {
    op: 'change_type', cat: 'shape', icon: 'type', label: 'Change type',
    desc: 'Numbers, dates, text and more', keywords: 'convert format number date text cast',
    intro: "Turn text into numbers or dates so they sort and add up properly. Cells that can't convert become blank.",
    verb: 'Change type',
    fields: [
      { key: 'types', type: 'types', label: 'Convert', default: (cols) => [{ column: first(cols, 'text'), to: 'decimal' }] },
      { key: 'date_format', type: 'text', label: 'Date format (optional)', placeholder: 'e.g. %d/%m/%Y for 31/12/2026',
        default: '', show: (d) => d.types.some((r) => r.to === 'date' || r.to === 'datetime') },
    ],
    build: (d) => ({
      columns: Object.fromEntries(d.types.filter((r) => r.column).map((r) => [r.column, r.to])),
      date_format: d.date_format || undefined,
    }),
  },
  {
    op: 'split_column', cat: 'shape', icon: 'split', label: 'Split column',
    desc: 'Break one column by a separator', keywords: 'separate delimiter text to columns first last name',
    intro: 'Split text like "Asha Rao" into First and Last name columns.',
    verb: 'Split column',
    fields: [
      { key: 'column', type: 'column', label: 'Column', filter: 'text', default: (cols) => first(cols, 'text') },
      { key: 'delim', type: 'select', label: 'Split at each', options: DELIMS, default: ' ' },
      { key: 'custom', type: 'text', label: 'Separator', placeholder: 'e.g. :', default: '', show: (d) => d.delim === 'custom' },
      { key: 'parts', type: 'number', label: 'Into how many columns', min: 2, max: 50, default: '2' },
      { key: 'keep_original', type: 'toggle', label: 'Keep the original column', default: false },
    ],
    build: (d) => ({
      column: d.column, delimiter: d.delim === 'custom' ? d.custom : d.delim,
      parts: Number(d.parts) || undefined, keep_original: d.keep_original,
    }),
    ready: (d) => (!d.column ? 'Choose a text column to split.' : d.delim === 'custom' && !d.custom ? 'Type the separator.' : null),
  },
  {
    op: 'add_column', cat: 'shape', icon: 'addcol', label: 'Add column',
    desc: 'Combine, calculate or fill in', keywords: 'new column formula calculate concat merge join math',
    intro: 'Add a new column: join columns together, do simple math, or fill in one value.',
    verb: 'Add column',
    fields: [
      { key: 'name', type: 'text', label: 'New column name', placeholder: 'e.g. Total', default: '' },
      { key: 'mode', type: 'choice', label: 'Make it from', default: 'combine',
        options: [['combine', 'Join columns'], ['math', 'Math'], ['constant', 'One value']] },
      { key: 'columns', type: 'columns', label: 'Columns to join, in order', ordered: true, default: [],
        show: (d) => d.mode === 'combine' },
      { key: 'separator', type: 'text', label: 'Put between them', placeholder: 'a space', default: ' ',
        show: (d) => d.mode === 'combine' },
      { key: 'left', type: 'column', label: 'Column', filter: 'number', default: (cols) => first(cols, 'decimal') || first(cols, 'integer'),
        show: (d) => d.mode === 'math' },
      { key: 'operator', type: 'choice', label: 'Operation', default: '*',
        options: [['+', '+'], ['-', '−'], ['*', '×'], ['/', '÷']], show: (d) => d.mode === 'math' },
      { key: 'rightKind', type: 'choice', label: 'With', default: 'value',
        options: [['value', 'A number'], ['column', 'Another column']], show: (d) => d.mode === 'math' },
      { key: 'right_value', type: 'number', label: 'Number', default: '', step: 'any',
        show: (d) => d.mode === 'math' && d.rightKind === 'value' },
      { key: 'right_column', type: 'column', label: 'Second column', filter: 'number', default: '',
        show: (d) => d.mode === 'math' && d.rightKind === 'column' },
      { key: 'value', type: 'text', label: 'Value', placeholder: 'e.g. India', default: '', show: (d) => d.mode === 'constant' },
    ],
    build: (d) => {
      const base = { name: d.name.trim(), mode: d.mode };
      if (d.mode === 'combine') return { ...base, columns: d.columns, separator: d.separator };
      if (d.mode === 'constant') return { ...base, value: d.value };
      return {
        ...base, left: d.left, operator: d.operator,
        ...(d.rightKind === 'column' ? { right_column: d.right_column }
          : { right_value: d.right_value === '' ? undefined : Number(d.right_value) }),
      };
    },
    ready: (d) => (!d.name.trim() ? 'Give the new column a name.'
      : d.mode === 'math' && !d.left ? 'Choose a number column.'
        : d.mode === 'math' && d.rightKind === 'value' && d.right_value === '' ? 'Type a number.'
          : d.mode === 'math' && d.rightKind === 'column' && !d.right_column ? 'Choose the second column.' : null),
  },
  {
    op: 'pivot', cat: 'summarize', icon: 'pivot', label: 'Pivot table',
    desc: 'Group, total and cross-tab, like Excel', keywords: 'group by summary total subtotal aggregate crosstab matrix sum count average',
    intro: 'Like an Excel pivot table: pick the Rows and what to calculate. Add a Columns field to spread the totals across columns.',
    verb: 'Make pivot table',
    fields: [
      { key: 'rows', type: 'columns', label: 'Rows', default: (cols) => [first(cols, 'text')].filter(Boolean) },
      { key: 'pcol', type: 'column', label: 'Columns (optional)', optional: true,
        emptyLabel: 'None — one row per group', default: '' },
      { key: 'aggs', type: 'aggs', label: 'Values', addLabel: 'Add value',
        default: (cols) => {
          const numeric = first(cols, 'decimal') || first(cols, 'integer');
          return [numeric ? { func: 'sum', column: numeric } : { func: 'count_rows', column: '' }];
        } },
      { key: 'totals', type: 'toggle', label: 'Show Grand Total', default: true },
    ],
    build: (d) => ({
      rows: d.rows,
      columns: d.pcol || undefined,
      values: d.aggs.map((a) => (a.func === 'count_rows' ? { func: 'count_rows' } : { func: a.func, column: a.column })),
      totals: d.totals,
    }),
    ready: (d) => (d.aggs.some((a) => a.func !== 'count_rows' && !a.column) ? 'Choose a column for each value.'
      : d.pcol && d.rows.includes(d.pcol) ? 'Pick a Columns field that isn’t already in Rows.' : null),
    done: (b, a) => `Pivot table ready — ${plural(a, 'row')}`,
  },
  {
    op: 'unpivot', cat: 'summarize', icon: 'unpivot', label: 'Unpivot columns',
    desc: 'Turn columns into rows', keywords: 'melt reshape long wide transpose',
    intro: 'Turns a wide table (Jan, Feb, Mar columns) into a long one with Month and Value columns.',
    verb: 'Unpivot',
    fields: [
      { key: 'keep', type: 'columns', label: 'Keep these as they are', default: (cols) => cols.slice(0, 1).map((c) => c.name) },
      { key: 'columns', type: 'columns', label: 'Turn into rows', optional: true, allLabel: 'All other columns', default: null },
      { key: 'attribute_name', type: 'text', label: 'Name for the new label column', default: 'Attribute' },
      { key: 'value_name', type: 'text', label: 'Name for the new value column', default: 'Value' },
    ],
    build: (d) => ({ keep: d.keep, columns: d.columns, attribute_name: d.attribute_name, value_name: d.value_name }),
  },
  {
    op: 'convert', cat: 'convert', icon: 'convert', label: 'Convert file',
    desc: 'Excel, CSV, JSON or PDF', keywords: 'export save xlsx csv json pdf excel format change',
    intro: 'Open a spreadsheet and save it in another format.',
    convert: true,
    fields: [],
  },
];

export const TOOL = Object.fromEntries(TOOLS.map((t) => [t.op, t]));

export const FORMATS = [['xlsx', 'Excel (.xlsx)'], ['csv', 'CSV (.csv)'], ['json', 'JSON (.json)'], ['pdf', 'PDF (.pdf)']];

export const SUGGEST = ['trim', 'remove_duplicates', 'filter_rows', 'sort_rows', 'pivot', 'change_type', 'convert'];

export function defaults(tool, cols) {
  const d = {};
  for (const f of tool.fields) d[f.key] = typeof f.default === 'function' ? f.default(cols) : structuredClone(f.default);
  return d;
}

/** A friendly hint while required options are still empty, or null when the step can be previewed. */
export function incomplete(tool, d) {
  const own = tool.ready ? tool.ready(d) : null; // tool-specific hints come first: they follow the form's order
  if (own) return own;
  for (const f of tool.fields) {
    if (f.show && !f.show(d)) continue;
    const picked = d[f.key];
    if (f.type === 'columns' && (f.optional ? Array.isArray(picked) && !picked.length : !(picked || []).length)) {
      return 'Choose at least one column.';
    }
    if (f.type === 'column' && !f.optional && !d[f.key]) return `Choose a column for “${f.label}”.`;
  }
  return null;
}

export function toStep(tool, d) {
  const step = { op: tool.op, ...tool.build(d) };
  for (const [k, v] of Object.entries(step)) if (v === undefined || v === null || v === '') delete step[k];
  return step;
}
