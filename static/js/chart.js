// Small, dependency-free SVG charts for pivot results: column, bar, line and pie.
// Colours are written into the SVG itself, so the same markup can be shown on screen
// and downloaded as SVG or PNG. Animations are CSS classes that only apply on screen.

const W = 720;
const H = 400;
const compact = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 });
const full = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const clip = (s, n) => (String(s).length > n ? `${String(s).slice(0, n - 1)}…` : String(s));

export const MAX_CATEGORIES = 30;
const TOTAL = /(^| · )Grand Total$/;

/** Pick chart data out of a preview: first column = categories, number columns = series. Grand totals are left out. */
export function chartData(preview) {
  const cols = preview.columns;
  if (!cols.length) return { error: 'Nothing to chart yet.' };
  const seriesIdx = cols.map((c, i) => i).filter((i) => i > 0 && ['integer', 'decimal'].includes(cols[i].type) && !TOTAL.test(cols[i].name));
  if (!seriesIdx.length) return { error: 'Add a number value (like Sum of Amount) to draw a chart.' };
  let rows = preview.rows.filter((r) => r[0] !== 'Grand Total');
  const truncated = rows.length > MAX_CATEGORIES;
  rows = rows.slice(0, MAX_CATEGORIES);
  return {
    categoryName: cols[0].name,
    categories: rows.map((r) => (r[0] === null || r[0] === '' ? '(blank)' : String(r[0]))),
    series: seriesIdx.slice(0, 8).map((i) => ({ name: cols[i].name, values: rows.map((r) => (typeof r[i] === 'number' ? r[i] : 0)) })),
    truncated,
  };
}

/** Colours for the current theme, read from CSS custom properties. */
export function themeColors() {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  return {
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--c${i}`)),
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

function legend(series, colors, y) {
  if (series.length < 2) return { svg: '', height: 0 };
  let x = 0;
  let row = 0;
  const items = series.map((s, i) => {
    const w = Math.min(clip(s.name, 28).length * 7 + 30, W);
    if (x + w > W) { x = 0; row += 1; }
    const out = `<g transform="translate(${x},${y + row * 22})"><rect width="12" height="12" rx="3" fill="${colors.series[i % 8]}"/>
      <text x="18" y="10.5" font-size="12" fill="${colors.ink}">${esc(clip(s.name, 28))}</text></g>`;
    x += w;
    return out;
  });
  return { svg: items.join(''), height: (row + 1) * 22 + 6 };
}

function frame(inner, colors, { background, label }) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(label)}"
    font-family="Manrope, system-ui, -apple-system, Segoe UI, sans-serif">${background ? `<rect width="${W}" height="${H}" fill="${colors.bg}"/>` : ''}${inner}</svg>`;
}

/** type: column | bar | line | pie. Returns an SVG string. */
export function chartSVG(data, type, colors, { background = false } = {}) {
  const label = `${type} chart of ${data.series.map((s) => s.name).join(', ')} by ${data.categoryName}`;
  if (type === 'pie') return frame(pie(data, colors), colors, { background, label });
  const lg = legend(data.series, colors, 4);
  const top = 12 + lg.height;
  const all = data.series.flatMap((s) => s.values);
  const { lo, hi, ticks } = niceScale(Math.min(0, ...all), Math.max(0, ...all));
  const n = data.categories.length;
  let body = '';

  if (type === 'bar') { // horizontal bars, category labels on the left
    const left = Math.min(150, 12 + Math.max(...data.categories.map((c) => clip(c, 20).length)) * 7);
    const right = W - 16;
    const bottom = H - 30;
    const x = (v) => left + ((v - lo) / (hi - lo)) * (right - left);
    const band = (bottom - top) / n;
    const bw = Math.min(28, (band * 0.75) / data.series.length);
    body += ticks.map((t) => `<line x1="${x(t)}" y1="${top}" x2="${x(t)}" y2="${bottom}" stroke="${colors.grid}"/>
      <text x="${x(t)}" y="${bottom + 18}" text-anchor="middle" font-size="11" fill="${colors.muted}">${compact.format(t)}</text>`).join('');
    data.categories.forEach((c, i) => {
      const cy = top + band * i + band / 2;
      body += `<text x="${left - 8}" y="${cy + 4}" text-anchor="end" font-size="12" fill="${colors.ink}">${esc(clip(c, 20))}</text>`;
      data.series.forEach((s, k) => {
        const v = s.values[i];
        const y0 = cy - (bw * data.series.length) / 2 + k * bw;
        const x0 = x(Math.min(0, v));
        body += `<rect class="grow-x" x="${x0}" y="${y0}" width="${Math.max(1, Math.abs(x(v) - x(0)))}" height="${bw - 2}" rx="3" fill="${colors.series[k % 8]}"><title>${esc(c)} — ${esc(s.name)}: ${full.format(v)}</title></rect>`;
      });
    });
    return frame(lg.svg + body, colors, { background, label });
  }

  // column and line share a vertical value axis
  const rotate = n > 8;
  const left = 56;
  const bottom = H - (rotate ? 78 : 34);
  const y = (v) => bottom - ((v - lo) / (hi - lo)) * (bottom - top);
  const band = (W - left - 12) / n;
  const cx = (i) => left + band * i + band / 2;
  body += ticks.map((t) => `<line x1="${left}" y1="${y(t)}" x2="${W - 8}" y2="${y(t)}" stroke="${colors.grid}"/>
    <text x="${left - 8}" y="${y(t) + 4}" text-anchor="end" font-size="11" fill="${colors.muted}">${compact.format(t)}</text>`).join('');
  body += data.categories.map((c, i) => (rotate
    ? `<text transform="translate(${cx(i)},${bottom + 12}) rotate(-40)" text-anchor="end" font-size="11" fill="${colors.ink}">${esc(clip(c, 14))}</text>`
    : `<text x="${cx(i)}" y="${bottom + 20}" text-anchor="middle" font-size="12" fill="${colors.ink}">${esc(clip(c, Math.max(4, Math.floor(band / 7))))}</text>`)).join('');

  if (type === 'line') {
    data.series.forEach((s, k) => {
      const pts = s.values.map((v, i) => `${cx(i)},${y(v)}`).join(' ');
      body += `<polyline class="draw" pathLength="1" points="${pts}" fill="none" stroke="${colors.series[k % 8]}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
      body += s.values.map((v, i) => `<circle class="pop" cx="${cx(i)}" cy="${y(v)}" r="4" fill="${colors.series[k % 8]}"><title>${esc(data.categories[i])} — ${esc(s.name)}: ${full.format(v)}</title></circle>`).join('');
    });
  } else {
    const bw = Math.min(40, (band * 0.75) / data.series.length);
    data.categories.forEach((c, i) => {
      data.series.forEach((s, k) => {
        const v = s.values[i];
        const x0 = cx(i) - (bw * data.series.length) / 2 + k * bw;
        const yTop = y(Math.max(0, v));
        body += `<rect class="grow-y" x="${x0}" y="${yTop}" width="${bw - 2}" height="${Math.max(1, Math.abs(y(v) - y(0)))}" rx="3" fill="${colors.series[k % 8]}"><title>${esc(c)} — ${esc(s.name)}: ${full.format(v)}</title></rect>`;
      });
    });
  }
  body += `<line x1="${left}" y1="${y(0)}" x2="${W - 8}" y2="${y(0)}" stroke="${colors.muted}"/>`;
  return frame(lg.svg + body, colors, { background, label });
}

function pie(data, colors) {
  const s = data.series[0];
  let items = data.categories.map((c, i) => ({ c, v: Math.max(0, s.values[i]) })).filter((d) => d.v > 0);
  items.sort((a, b) => b.v - a.v);
  if (items.length > 10) {
    const rest = items.slice(9).reduce((sum, d) => sum + d.v, 0);
    items = [...items.slice(0, 9), { c: 'Other', v: rest }];
  }
  const total = items.reduce((sum, d) => sum + d.v, 0);
  if (!total) return `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" fill="${colors.muted}">No positive values to show.</text>`;
  const cx = 200;
  const cy = H / 2;
  const r = 160;
  let a0 = -Math.PI / 2;
  let out = `<text x="${cx}" y="22" text-anchor="middle" font-size="13" font-weight="700" fill="${colors.ink}">${esc(clip(s.name, 40))}</text>`;
  items.forEach((d, i) => {
    const a1 = a0 + (d.v / total) * Math.PI * 2;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const p = (a) => `${cx + r * Math.cos(a)},${cy + 12 + r * Math.sin(a)}`;
    const path = items.length === 1
      ? `M ${cx} ${cy + 12 - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy + 12 - r} Z`
      : `M ${cx} ${cy + 12} L ${p(a0)} A ${r} ${r} 0 ${large} 1 ${p(a1)} Z`;
    out += `<path class="pop" d="${path}" fill="${colors.series[i % 8]}" stroke="${colors.bg}" stroke-width="2"><title>${esc(d.c)}: ${full.format(d.v)} (${((d.v / total) * 100).toFixed(1)}%)</title></path>`;
    a0 = a1;
  });
  items.forEach((d, i) => {
    const y = 60 + i * 28;
    out += `<rect x="400" y="${y}" width="14" height="14" rx="3" fill="${colors.series[i % 8]}"/>
      <text x="422" y="${y + 12}" font-size="13" fill="${colors.ink}">${esc(clip(d.c, 24))}</text>
      <text x="${W - 12}" y="${y + 12}" text-anchor="end" font-size="13" fill="${colors.muted}">${((d.v / total) * 100).toFixed(1)}%</text>`;
  });
  return out;
}

/** Download the chart as an SVG file or a 2× PNG (with a solid background). */
export async function saveChart(svg, name, format) {
  const blob = new Blob([svg], { type: 'image/svg+xml' });
  if (format === 'svg') return { blob, name: `${name}.svg` };
  const url = URL.createObjectURL(blob);
  try {
    const img = await new Promise((resolve, reject) => {
      const im = new Image();
      im.onload = () => resolve(im);
      im.onerror = reject;
      im.src = url;
    });
    const canvas = Object.assign(document.createElement('canvas'), { width: W * 2, height: H * 2 });
    canvas.getContext('2d').drawImage(img, 0, 0, W * 2, H * 2);
    const png = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    return { blob: png, name: `${name}.png` };
  } finally {
    URL.revokeObjectURL(url);
  }
}
