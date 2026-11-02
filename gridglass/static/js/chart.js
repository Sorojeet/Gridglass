// Small, dependency-free SVG charts for pivot results: column, bar, line, area, pie and donut.
// Colours are written into the SVG itself, so the same markup can be shown on screen
// and downloaded as SVG or PNG. Animations are CSS classes that only apply on screen.

const SHAPES = { wide: [720, 400], square: [560, 560], tall: [480, 640] };
const FORMAT = {
  short: new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 }), // 1.2L, 3.4Cr
  full: new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }),                       // 1,23,456.5
};
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const clip = (s, n) => (String(s).length > n ? `${String(s).slice(0, n - 1)}…` : String(s));

export const MAX_CATEGORIES = 30;
const TOTAL = /(^| · )Grand Total$/;

/** Colour sets. 'theme' follows light/dark mode; the others are mid-tones that read on both. */
export const PALETTES = {
  theme: null,
  ocean: ['#0369A1', '#0EA5E9', '#14B8A6', '#6366F1', '#22D3EE', '#1E40AF', '#5EEAD4', '#818CF8'],
  sunset: ['#EA580C', '#F59E0B', '#E11D48', '#A855F7', '#FB7185', '#CA8A04', '#F97316', '#BE185D'],
  forest: ['#15803D', '#65A30D', '#0D9488', '#A16207', '#4ADE80', '#166534', '#84CC16', '#78716C'],
  berry: ['#9333EA', '#DB2777', '#6366F1', '#E879F9', '#F43F5E', '#7C3AED', '#C026D3', '#FB7185'],
  mono: ['#334155', '#64748B', '#94A3B8', '#1E293B', '#475569', '#CBD5E1', '#0F172A', '#E2E8F0'],
};

export const DEFAULT_OPTIONS = {
  type: 'column', stacked: false, title: '', xTitle: '', yTitle: '', palette: 'theme',
  // labelAs: what labels show, a list of 'name' | 'value' | 'percent' (null: name + % on pies and donuts, the value elsewhere)
  labels: false, labelAs: null, legend: true, grid: true, sort: 'none', top: 0, numbers: 'short', shape: 'wide',
};

/** Pick chart data out of a preview: first column = categories, number columns = series. Grand totals are left out. */
export function chartData(preview) {
  const cols = preview.columns;
  if (!cols.length) return { error: 'Nothing to chart yet.' };
  const seriesIdx = cols.map((c, i) => i).filter((i) => i > 0 && ['integer', 'decimal'].includes(cols[i].type) && !TOTAL.test(cols[i].name));
  if (!seriesIdx.length) return { error: 'Add a number value (like Sum of Amount) to draw a chart.' };
  const rows = preview.rows.filter((r) => r[0] !== 'Grand Total');
  return {
    categoryName: cols[0].name,
    categories: rows.map((r) => (r[0] === null || r[0] === '' ? '(blank)' : String(r[0]))),
    series: seriesIdx.slice(0, 8).map((i) => ({ name: cols[i].name, values: rows.map((r) => (typeof r[i] === 'number' ? r[i] : 0)) })),
  };
}

/** Sort, keep the top N (the rest become "Other") and cap at MAX_CATEGORIES. Returns a new data object. */
export function arrange(data, { sort = 'none', top = 0 } = {}) {
  let idx = data.categories.map((_, i) => i);
  const sum = (i) => data.series.reduce((t, s) => t + s.values[i], 0);
  if (sort === 'desc') idx.sort((a, b) => sum(b) - sum(a));
  else if (sort === 'asc') idx.sort((a, b) => sum(a) - sum(b));
  else if (sort === 'az') idx.sort((a, b) => data.categories[a].localeCompare(data.categories[b], 'en-IN', { numeric: true }));
  const limit = top > 0 ? top : MAX_CATEGORIES;
  let rest = [];
  if (idx.length > limit) {
    if (top > 0) { // the biggest N stay; everything else is added up as "Other"
      const biggest = [...idx].sort((a, b) => sum(b) - sum(a)).slice(0, top);
      const keep = new Set(biggest);
      rest = idx.filter((i) => !keep.has(i));
      idx = idx.filter((i) => keep.has(i));
    } else idx = idx.slice(0, limit);
  }
  const pick = (values) => idx.map((i) => values[i]);
  const out = {
    categoryName: data.categoryName,
    categories: pick(data.categories),
    series: data.series.map((s) => ({ name: s.name, values: pick(s.values) })),
    truncated: top <= 0 && data.categories.length > MAX_CATEGORIES,
    total: data.categories.length,
  };
  if (rest.length) {
    out.categories.push(`Other (${rest.length})`);
    out.series.forEach((s, k) => s.values.push(rest.reduce((t, i) => t + data.series[k].values[i], 0)));
  }
  return out;
}

/** Colours for the current theme, read from CSS custom properties. */
export function themeColors(palette = 'theme') {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  return {
    series: PALETTES[palette] ?? [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--c${i}`)),
    ink: v('--ink'), muted: v('--muted'), grid: v('--chart-grid'), bg: v('--ground'),
  };
}

function niceScale(min, max, ticks = 5) {
  if (min === max) { max = min + 1; }
  const span = max - min;
  const step0 = span / ticks;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const out = [];
  for (let t = lo; t <= hi + step / 2; t += step) out.push(Math.round(t / step) * step);
  return { lo, hi, ticks: out };
}

function legend(series, colors, y, width) {
  let x = 0;
  let row = 0;
  const items = series.map((s, i) => {
    const w = Math.min(clip(s.name, 28).length * 7 + 30, width);
    if (x + w > width) { x = 0; row += 1; }
    const out = `<g transform="translate(${x},${y + row * 22})"><rect width="12" height="12" rx="3" fill="${colors.series[i % 8]}"/>
      <text x="18" y="10.5" font-size="12" fill="${colors.ink}">${esc(clip(s.name, 28))}</text></g>`;
    x += w;
    return out;
  });
  return { svg: items.join(''), height: (row + 1) * 22 + 6 };
}

function frame(inner, colors, { background, label, w, h }) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(label)}"
    font-family="Manrope, system-ui, -apple-system, Segoe UI, sans-serif">${background ? `<rect width="${w}" height="${h}" fill="${colors.bg}"/>` : ''}${inner}</svg>`;
}

/**
 * Width and height. Downloads use the shape's fixed size. On screen (`fit` = the box's width in CSS pixels)
 * the chart is drawn at that width, so text stays a readable size on phones instead of being shrunk.
 */
function size({ shape, fit }) {
  const [W, H] = SHAPES[shape] ?? SHAPES.wide;
  if (!fit) return [W, H];
  const w = Math.round(Math.min(Math.max(fit, 300), 900));
  if (shape === 'square') return [w, w];
  if (shape === 'tall') return [w, Math.round(w * (H / W))];
  return [w, Math.max(240, Math.round(w * (H / W)))]; // wide: never flatter than 240px on a phone
}

/** Cumulative bottoms and tops per series, stacking positives up and negatives down. */
function stackOf(series, n) {
  const pos = Array(n).fill(0);
  const neg = Array(n).fill(0);
  return series.map((s) => s.values.map((v, i) => {
    const base = v >= 0 ? pos[i] : neg[i];
    if (v >= 0) pos[i] += v; else neg[i] += v;
    return [base, base + v];
  }));
}

/**
 * Draw `data` (from chartData/arrange) as an SVG string.
 * opts: type (column | bar | line | area | pie | donut), stacked, title, xTitle, yTitle, labels, legend, grid,
 *       numbers (short | full), shape (wide | square | tall), background (solid fill, for downloads).
 */
export function chartSVG(data, colors, opts = {}) {
  const o = { ...DEFAULT_OPTIONS, ...opts };
  let [w, h] = size(o);
  if ((o.type === 'pie' || o.type === 'donut') && o.legend && w < 560) {
    // Narrow screens: the legend goes under the pie, so make room for one line per slice.
    const slices = Math.min(data.categories.length, o.top > 0 ? o.top + 1 : 10);
    h = Math.max(h, Math.round(w * 0.78) + (o.title ? 38 : 12) + slices * 24 + 16);
  }
  const fmt = FORMAT[o.numbers] ?? FORMAT.short;
  const exact = FORMAT.full;
  const label = `${o.title || `${o.type} chart`} of ${data.series.map((s) => s.name).join(', ')} by ${data.categoryName}`;
  const titleSvg = o.title
    ? `<text x="${w / 2}" y="22" text-anchor="middle" font-size="16" font-weight="800" fill="${colors.ink}">${esc(clip(o.title, 70))}</text>` : '';
  let top = o.title ? 38 : 12;
  if (o.type === 'pie' || o.type === 'donut') {
    return frame(titleSvg + pie(data, colors, o, { w, h, top, fmt }), colors, { background: o.background, label, w, h });
  }
  const multi = data.series.length > 1;
  const lg = multi && o.legend ? legend(data.series, colors, top - 4, w) : { svg: '', height: 0 };
  top += lg.height;
  const n = data.categories.length;
  const stacked = o.stacked && multi && o.type !== 'line';
  const stack = stacked ? stackOf(data.series, n) : null;
  const all = stacked ? stack.flat(2) : data.series.flatMap((s) => s.values);
  const { lo, hi, ticks } = niceScale(Math.min(0, ...all), Math.max(0, ...all));
  const color = (k) => colors.series[k % 8];
  const tip = (c, s, v) => `<title>${esc(c)} — ${esc(s)}: ${exact.format(v)}</title>`;
  // % = share of the series total, or of the stack when stacked (how much of this column each part is).
  const parts = labelParts(o);
  const both = parts.value && parts.percent;
  const seriesTotal = data.series.map((s) => s.values.reduce((t, v) => t + v, 0));
  const share = (v, k, i) => {
    const base = stacked ? data.series.reduce((t, s) => t + s.values[i], 0) : seriesTotal[k];
    return base ? pctText((v / base) * 100) : '';
  };
  /** One or two label lines at (x, y); `twoLines` stacks value over % (columns), else "value · %". */
  const valueText = (x, y, v, k, i, { anchor = 'middle', fill = colors.ink, twoLines = false, room = Infinity } = {}) => {
    const t = (text, dy = 0, size = 11) => `<text x="${x}" y="${y + dy}" text-anchor="${anchor}" font-size="${size}" font-weight="700" fill="${fill}">${text}</text>`;
    const pct = share(v, k, i);
    if ((parts.percent && !parts.value) || (both && room < 26)) return t(pct || fmt.format(v));
    if (both && pct) return twoLines ? t(fmt.format(v), -13) + t(pct, 0, 10) : t(`${fmt.format(v)} · ${pct}`);
    return t(fmt.format(v));
  };
  let body = '';

  if (o.type === 'bar') { // horizontal bars, category labels on the left
    const left = Math.min(Math.round(w * 0.24), 12 + Math.max(...data.categories.map((c) => clip(c, 20).length)) * 7) + (o.yTitle ? 18 : 0);
    const right = w - (o.labels ? (both ? 92 : 52) : 16);
    const bottom = h - 30 - (o.xTitle ? 20 : 0);
    const x = (v) => left + ((v - lo) / (hi - lo)) * (right - left);
    const band = (bottom - top) / n;
    const groups = stacked ? 1 : data.series.length;
    const bw = Math.min(28, (band * 0.75) / groups);
    body += ticks.map((t) => `${o.grid ? `<line x1="${x(t)}" y1="${top}" x2="${x(t)}" y2="${bottom}" stroke="${colors.grid}"/>` : ''}
      <text x="${x(t)}" y="${bottom + 18}" text-anchor="middle" font-size="11" fill="${colors.muted}">${fmt.format(t)}</text>`).join('');
    data.categories.forEach((c, i) => {
      const cy = top + band * i + band / 2;
      body += `<text x="${left - 8}" y="${cy + 4}" text-anchor="end" font-size="12" fill="${colors.ink}">${esc(clip(c, 20))}</text>`;
      data.series.forEach((s, k) => {
        const v = s.values[i];
        const [a, b] = stacked ? stack[k][i] : [0, v];
        const y0 = stacked ? cy - bw / 2 : cy - (bw * groups) / 2 + k * bw;
        const x0 = x(Math.min(a, b));
        const len = Math.max(1, Math.abs(x(b) - x(a)));
        body += `<rect class="grow-x" x="${x0}" y="${y0}" width="${len}" height="${bw - 2}" rx="3" fill="${color(k)}">${tip(c, s.name, v)}</rect>`;
        if (o.labels && v && (!stacked || len > 34)) {
          body += stacked ? valueText(x0 + len / 2, y0 + bw / 2 + 3, v, k, i, { fill: '#FFFFFF', room: bw })
            : valueText(x(b) + (v >= 0 ? 4 : -4), y0 + bw / 2 + 3, v, k, i, { anchor: v >= 0 ? 'start' : 'end' });
        }
      });
    });
    body += `<line x1="${x(0)}" y1="${top}" x2="${x(0)}" y2="${bottom}" stroke="${colors.muted}"/>`;
    body += axisTitles(o, colors, { w, h, left: 0, cy: (top + bottom) / 2, xCenter: (left + right) / 2 });
    return frame(titleSvg + lg.svg + body, colors, { background: o.background, label, w, h });
  }

  // column, line and area share a vertical value axis
  const rotate = n > Math.floor(w / 80);
  const left = 56 + (o.yTitle ? 18 : 0);
  const bottom = h - (rotate ? 78 : 34) - (o.xTitle ? 20 : 0);
  const y = (v) => bottom - ((v - lo) / (hi - lo)) * (bottom - top - (o.labels ? (both ? 28 : 14) : 0));
  const band = (w - left - 12) / n;
  const cx = (i) => left + band * i + band / 2;
  body += ticks.map((t) => `${o.grid ? `<line x1="${left}" y1="${y(t)}" x2="${w - 8}" y2="${y(t)}" stroke="${colors.grid}"/>` : ''}
    <text x="${left - 8}" y="${y(t) + 4}" text-anchor="end" font-size="11" fill="${colors.muted}">${fmt.format(t)}</text>`).join('');
  body += data.categories.map((c, i) => (rotate
    ? `<text transform="translate(${cx(i)},${bottom + 12}) rotate(-40)" text-anchor="end" font-size="11" fill="${colors.ink}">${esc(clip(c, 14))}</text>`
    : `<text x="${cx(i)}" y="${bottom + 20}" text-anchor="middle" font-size="12" fill="${colors.ink}">${esc(clip(c, Math.max(4, Math.floor(band / 7))))}</text>`)).join('');

  if (o.type === 'line' || o.type === 'area') {
    const showDots = n <= 40;
    data.series.forEach((s, k) => {
      const tops = s.values.map((v, i) => (stacked ? stack[k][i][1] : v));
      const bases = s.values.map((v, i) => (stacked ? stack[k][i][0] : 0));
      const pts = tops.map((v, i) => `${cx(i)},${y(v)}`);
      if (o.type === 'area') {
        const under = bases.map((v, i) => `${cx(i)},${y(v)}`).reverse();
        body += `<polygon class="fade" points="${[...pts, ...under].join(' ')}" fill="${color(k)}" fill-opacity="${stacked ? 0.75 : 0.22}"/>`;
      }
      body += `<polyline class="draw" pathLength="1" points="${pts.join(' ')}" fill="none" stroke="${color(k)}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
      if (showDots) body += s.values.map((v, i) => `<circle class="pop" cx="${cx(i)}" cy="${y(tops[i])}" r="${o.type === 'area' ? 3 : 4}" fill="${color(k)}">${tip(data.categories[i], s.name, v)}</circle>`).join('');
      if (o.labels && n <= 24) body += s.values.map((v, i) => valueText(cx(i), y(tops[i]) - 8, v, k, i, { twoLines: true })).join('');
    });
  } else {
    const groups = stacked ? 1 : data.series.length;
    const bw = Math.min(stacked ? 56 : 40, (band * 0.75) / groups);
    data.categories.forEach((c, i) => {
      data.series.forEach((s, k) => {
        const v = s.values[i];
        const [a, b] = stacked ? stack[k][i] : [0, v];
        const x0 = stacked ? cx(i) - bw / 2 : cx(i) - (bw * groups) / 2 + k * bw;
        const yTop = y(Math.max(a, b));
        const tall = Math.max(1, Math.abs(y(b) - y(a)));
        body += `<rect class="grow-y" x="${x0}" y="${yTop}" width="${bw - 2}" height="${tall}" rx="3" fill="${color(k)}">${tip(c, s.name, v)}</rect>`;
        if (o.labels && v && (stacked ? tall > 16 && bw > 26 : bw > 14)) {
          body += stacked ? valueText(x0 + (bw - 2) / 2, yTop + tall / 2 + (both && tall >= 30 ? 10 : 4), v, k, i,
            { fill: '#FFFFFF', twoLines: true, room: tall })
            : valueText(x0 + (bw - 2) / 2, v >= 0 ? yTop - 5 : yTop + tall + (both ? 26 : 13), v, k, i, { twoLines: true });
        }
      });
    });
  }
  body += `<line x1="${left}" y1="${y(0)}" x2="${w - 8}" y2="${y(0)}" stroke="${colors.muted}"/>`;
  body += axisTitles(o, colors, { w, h, left: 0, cy: (top + bottom) / 2, xCenter: (left + w - 8) / 2 });
  return frame(titleSvg + lg.svg + body, colors, { background: o.background, label, w, h });
}

function axisTitles(o, colors, { h, cy, xCenter }) {
  let out = '';
  if (o.xTitle) out += `<text x="${xCenter}" y="${h - 8}" text-anchor="middle" font-size="12" font-weight="700" fill="${colors.muted}">${esc(clip(o.xTitle, 60))}</text>`;
  if (o.yTitle) out += `<text transform="translate(14,${cy}) rotate(-90)" text-anchor="middle" font-size="12" font-weight="700" fill="${colors.muted}">${esc(clip(o.yTitle, 50))}</text>`;
  return out;
}

function pie(data, colors, o, { w, h, top, fmt }) {
  const s = data.series[0];
  let items = data.categories.map((c, i) => ({ c, v: Math.max(0, s.values[i]) })).filter((d) => d.v > 0);
  if (o.sort === 'none' || o.sort === 'desc') items.sort((a, b) => b.v - a.v); // biggest slice first reads best
  const most = o.top > 0 ? o.top + 1 : 10;
  if (items.length > most) {
    const keep = most - 1;
    const rest = items.slice(keep).reduce((sum, d) => sum + d.v, 0);
    items = [...items.slice(0, keep), { c: 'Other', v: rest }];
  }
  const total = items.reduce((sum, d) => sum + d.v, 0);
  if (!total) return `<text x="${w / 2}" y="${h / 2}" text-anchor="middle" fill="${colors.muted}">No positive values to show.</text>`;
  const side = w >= 560 && w >= h * 1.3; // legend beside the pie on wide charts, below it otherwise
  const legendRows = items.length;
  const r = side ? Math.min((h - top - 24) / 2, w * 0.24) : Math.min((w - 40) / 2, (h - top - 28 - legendRows * 24) / 2);
  const cx = side ? 24 + r : w / 2;
  const cy = top + 14 + r;
  const inner = o.type === 'donut' ? r * 0.58 : 0;
  let a0 = -Math.PI / 2;
  let out = o.title ? '' : `<text x="${cx}" y="${top + 4}" text-anchor="middle" font-size="13" font-weight="700" fill="${colors.ink}">${esc(clip(s.name, 40))}</text>`;
  const pt = (a, rad) => `${cx + rad * Math.cos(a)},${cy + rad * Math.sin(a)}`;
  items.forEach((d, i) => {
    const a1 = a0 + (d.v / total) * Math.PI * 2;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    let path;
    if (items.length === 1) {
      path = `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r} Z`
        + (inner ? ` M ${cx} ${cy - inner} A ${inner} ${inner} 0 1 0 ${cx + 0.01} ${cy - inner} Z` : '');
    } else if (inner) {
      path = `M ${pt(a0, r)} A ${r} ${r} 0 ${large} 1 ${pt(a1, r)} L ${pt(a1, inner)} A ${inner} ${inner} 0 ${large} 0 ${pt(a0, inner)} Z`;
    } else {
      path = `M ${cx} ${cy} L ${pt(a0, r)} A ${r} ${r} 0 ${large} 1 ${pt(a1, r)} Z`;
    }
    out += `<path class="pop" d="${path}" fill="${colors.series[i % 8]}" fill-rule="evenodd" stroke="${colors.bg}" stroke-width="2"><title>${esc(d.c)}: ${FORMAT.full.format(d.v)} (${((d.v / total) * 100).toFixed(1)}%)</title></path>`;
    const parts = labelParts(o);
    const lines = [parts.name && 'name', parts.value && 'value', parts.percent && 'percent'].filter(Boolean);
    if (o.labels && d.v / total >= 0.04 + 0.03 * (lines.length - 1)) { // small slices: the legend has everything
      const mid = (a0 + a1) / 2;
      const rad = inner ? (r + inner) / 2 : r * 0.6;
      const lx = cx + rad * Math.cos(mid);
      const ly = cy + rad * Math.sin(mid);
      // How many letters of the name fit: the slice's width at the label, or the ring's thickness on a donut.
      const across = Math.min(2 * rad * Math.sin(Math.min((a1 - a0) / 2, Math.PI / 2)), inner ? (r - inner) * 1.7 : r * 1.1);
      const chars = Math.max(5, Math.min(18, Math.floor(across / 6.6)));
      const text = { name: esc(clip(d.c, chars)), value: fmt.format(d.v), percent: pctText((d.v / total) * 100) };
      const y0 = ly - ((lines.length - 1) * 13) / 2 + 4;
      out += lines.map((kind, n) => `<text x="${lx}" y="${y0 + n * 13}" text-anchor="middle" font-size="${kind === 'name' ? 11.5 : 11}"
        font-weight="${kind === 'percent' && lines.length > 1 ? 600 : 700}" fill="#FFFFFF">${text[kind]}</text>`).join('');
    }
    a0 = a1;
  });
  if (inner) {
    out += `<text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="18" font-weight="800" fill="${colors.ink}">${fmt.format(total)}</text>
      <text x="${cx}" y="${cy + 16}" text-anchor="middle" font-size="11" fill="${colors.muted}">Total</text>`;
  }
  if (o.legend) {
    const lx = side ? cx + r + 36 : 20;
    const ly = side ? Math.max(top + 10, cy - (legendRows * 28) / 2) : cy + r + 22;
    const step = side ? 28 : 24;
    items.forEach((d, i) => {
      const y = ly + i * step;
      const pct = `${((d.v / total) * 100).toFixed(1)}%`;
      const val = ` · ${fmt.format(d.v)}`;
      out += `<rect x="${lx}" y="${y}" width="14" height="14" rx="3" fill="${colors.series[i % 8]}"/>
        <text x="${lx + 22}" y="${y + 12}" font-size="13" fill="${colors.ink}">${esc(clip(d.c, side ? 24 : 30))}</text>
        <text x="${w - 12}" y="${y + 12}" text-anchor="end" font-size="13" fill="${colors.muted}">${pct}${val}</text>`;
    });
  }
  return out;
}

/**
 * What data labels show, as { name, value, percent }. Names only go on pies and donuts (other charts
 * have them on an axis). Defaults: name + % on pies and donuts, the value elsewhere.
 */
export function labelParts(o) {
  const round = o.type === 'pie' || o.type === 'donut';
  let list = o.labelAs ?? (round ? ['name', 'percent'] : ['value']);
  if (typeof list === 'string') list = list === 'both' ? ['value', 'percent'] : [list]; // older saved choice
  const parts = { name: round && list.includes('name'), value: list.includes('value'), percent: list.includes('percent') };
  if (!parts.value && !parts.percent && !parts.name) parts.value = true;
  if (!round && !parts.value && !parts.percent) parts.value = true;
  return parts;
}

/** 21% · 8.5% · 0.3% — whole numbers from 10% up, one decimal below. */
function pctText(p) {
  return `${Math.abs(p) >= 10 || p === 0 ? p.toFixed(0) : p.toFixed(1)}%`;
}

/** Download the chart as an SVG file or a 2× PNG (with a solid background). */
export async function saveChart(svg, name, format) {
  const blob = new Blob([svg], { type: 'image/svg+xml' });
  if (format === 'svg') return { blob, name: `${name}.svg` };
  const [, w, h] = svg.match(/viewBox="0 0 (\d+) (\d+)"/).map(Number);
  const url = URL.createObjectURL(blob);
  try {
    const img = await new Promise((resolve, reject) => {
      const im = new Image();
      im.onload = () => resolve(im);
      im.onerror = reject;
      im.src = url;
    });
    const canvas = Object.assign(document.createElement('canvas'), { width: w * 2, height: h * 2 });
    canvas.getContext('2d').drawImage(img, 0, 0, w * 2, h * 2);
    const png = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    return { blob: png, name: `${name}.png` };
  } finally {
    URL.revokeObjectURL(url);
  }
}
