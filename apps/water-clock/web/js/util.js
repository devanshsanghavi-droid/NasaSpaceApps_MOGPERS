// Small helpers shared by every module. No data values live here.

export const CAP = 100; // years-left cap used by the model (">100 years")

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function isNum(v) { return typeof v === 'number' && Number.isFinite(v); }

// Pull a central number out of a scalar or {est|p50|value|mean} object.
export function num(v) {
  if (isNum(v)) return v;
  if (v && typeof v === 'object') {
    for (const k of ['est', 'p50', 'value', 'mean', 'median']) if (isNum(v[k])) return v[k];
  }
  return null;
}
export function lo(v) {
  if (v && typeof v === 'object') for (const k of ['lo', 'p10', 'low', 'min']) if (isNum(v[k])) return v[k];
  return num(v);
}
export function hi(v) {
  if (v && typeof v === 'object') for (const k of ['hi', 'p90', 'high', 'max']) if (isNum(v[k])) return v[k];
  return num(v);
}

export function fmt(v, d = 0) {
  if (!isNum(v)) return 'n/a';
  if (Math.abs(v) < 0.5 * 10 ** -d) v = 0; // no "-0
  return v.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d });
}
export function fmtSigned(v, d = 0) {
  if (!isNum(v)) return 'n/a';
  const s = fmt(Math.abs(v), d);
  if (Math.abs(v) < Math.pow(10, -d) / 2) return fmt(0, d);
  return (v > 0 ? '+' : '−') + s;
}
export function money(v) {
  if (!isNum(v)) return 'n/a';
  const s = '$' + fmt(Math.abs(v), 0);
  return v < 0 ? '−' + s : s;
}

// Years text, honouring the 100-year cap.
export function yrs(v, d = 0) {
  if (!isNum(v)) return 'n/a';
  if (v >= CAP) return '100+';
  return fmt(Math.max(0, v), d);
}

// "est (lo-hi)" with a formatter; drops the range if it collapses.
export function rangeText(v, f = x => fmt(x, 0), unit = '') {
  const c = num(v), a = lo(v), b = hi(v);
  if (!isNum(c)) return 'not available';
  const u = unit ? ' ' + unit : '';
  if (!isNum(a) || !isNum(b) || f(a) === f(b)) return `${f(c)}${u}`;
  return `${f(c)}${u} <span class="rng">(range ${f(Math.min(a, b))} to ${f(Math.max(a, b))})</span>`;
}

export const NA = '<span class="na">not available</span>';

// Colour for years left; same bins everywhere (map, lists, clock).
export const YEAR_BINS = [
  { max: 10, color: '#b2182b', label: 'under 10' },
  { max: 25, color: '#e35a2b', label: '10 to 25' },
  { max: 50, color: '#f2b04f', label: '25 to 50' },
  { max: 100, color: '#5aae9f', label: '50 to 100' },
  { max: Infinity, color: '#1f6f8b', label: '100 or more' },
];
export function yearColor(v) {
  if (!isNum(v)) return '#9aa0a6';
  for (const b of YEAR_BINS) if (v < b.max) return b.color;
  return YEAR_BINS[YEAR_BINS.length - 1].color;
}
// MapLibre "step" expression for the same bins.
export function yearStepExpr(prop) {
  return ['case', ['==', ['typeof', ['get', prop]], 'number'],
    ['step', ['get', prop], YEAR_BINS[0].color, 10, YEAR_BINS[1].color, 25, YEAR_BINS[2].color, 50, YEAR_BINS[3].color, 100, YEAR_BINS[4].color],
    '#9aa0a6'];
}

export function el(tag, attrs = {}, html = '') {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') e.className = v; else e.setAttribute(k, v === true ? '' : v);
  }
  if (html) e.innerHTML = html;
  return e;
}

export function safeUrl(u) {
  try {
    const x = new URL(u, location.href);
    return (x.protocol === 'https:' || x.protocol === 'http:') ? x.href : null;
  } catch { return null; }
}
export function link(text, url) {
  const u = safeUrl(url);
  return u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text);
}

export function list(items) {
  if (!Array.isArray(items) || !items.length) return NA;
  return '<ul>' + items.map(i => `<li>${typeof i === 'string' ? esc(i) : esc(i?.text ?? JSON.stringify(i))}</li>`).join('') + '</ul>';
}

// Parse "YYYY-MM-DD", "YYYYMMDD", "YYYY-MM", "YYYY" or a number into decimal years.
export function decYear(d) {
  if (isNum(d)) return d;
  const s = String(d);
  let m = s.match(/^(\d{4})-?(\d{2})?-?(\d{2})?/);
  if (!m) return null;
  const y = +m[1], mo = m[2] ? +m[2] : 7, da = m[3] ? +m[3] : 1;
  return y + (mo - 1) / 12 + (da - 1) / 365;
}

// Normalise many plausible series shapes into [{x: decimal year, y}].
export function toSeries(s, yKeys = ['cm', 'values', 'value', 'anom_cm', 'storage_cm', 'y']) {
  if (!s) return [];
  if (Array.isArray(s)) {
    return s.map(p => {
      if (Array.isArray(p)) return { x: decYear(p[0]), y: p[1] };
      if (p && typeof p === 'object') {
        const xk = ['date', 'year', 'x', 't'].find(k => k in p);
        const yk = yKeys.find(k => isNum(p[k])) || Object.keys(p).find(k => k !== xk && isNum(p[k]));
        return { x: decYear(p[xk]), y: p[yk] };
      }
      return null;
    }).filter(p => p && isNum(p.x) && isNum(p.y));
  }
  if (typeof s === 'object') {
    const xs = s.dates || s.years || s.x || s.t;
    const yk = yKeys.find(k => Array.isArray(s[k])) || Object.keys(s).find(k => Array.isArray(s[k]) && s[k] !== xs);
    if (Array.isArray(xs) && yk) return xs.map((d, i) => ({ x: decYear(d), y: s[yk][i] })).filter(p => isNum(p.x) && isNum(p.y));
  }
  return [];
}

// Plain-language labels for model keys shown in the Proof & data tables.
const KEY_LABELS = {
  cov80: 'Share inside 80% range (target 0.80)',
  coverage80: 'Share inside 80% range (target 0.80)',
  median_halfwidth80: 'Typical \u00b1 range (ft)',
  halfwidth80: 'Typical \u00b1 range (ft)',
  bias: 'Average over/under (ft)',
  mae: 'Average error (ft)',
  rmse: 'Root-mean-square error (ft)',
  model: 'Water Clock model',
  model_without_pooling: 'Model, each well on its own',
  baseline_own_trend: 'Simple rule: each well keeps its past trend',
  baseline_no_change: 'Simple rule: no change',
  baseline_county_trend: 'Simple rule: county average trend',
  train_end: 'Model trained on data up to',
  test_years: 'Years hidden and predicted',
  n_wells_test: 'Wells tested',
  saturated_thickness_vs_usgs_2009: 'Our water-bearing layer vs the USGS 2009 map',
  water_balance: 'Pumping vs water-table drop (water balance)',
  model_settings: 'Model settings (technical)',
  temporal: 'Wells we kept, later years hidden',
  spatial: 'Wells the model never saw',
  n: 'Number of wells',
  n_wells: 'Number of wells',
};
export function prettyKey(k) {
  if (KEY_LABELS[k]) return KEY_LABELS[k];
  const h = String(k).match(/^hindcast_(\d{4})_(temporal|spatial)_(10yr_change|latest_level)_ft$/);
  if (h) {
    const who = h[2] === 'spatial' ? 'Wells the model never saw' : 'Wells we kept';
    const what = h[3] === '10yr_change' ? `predicted ${h[1]}-${+h[1] + 10} change` : `predicted latest water level after ${h[1]}`;
    return `${who}: ${what} (ft)`;
  }
  return String(k).replace(/_/g, ' ').replace(/\bpct\b/g, '%').replace(/\bft\b/g, 'ft').replace(/\bmae\b/gi, 'MAE')
    .replace(/\brmse\b/gi, 'RMSE').replace(/\bcm yr\b/g, 'cm/yr').replace(/\bft yr\b/g, 'ft/yr').replace(/^./, c => c.toUpperCase());
}
