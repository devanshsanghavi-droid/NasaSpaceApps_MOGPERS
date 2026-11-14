// Small helpers shared by every view. Everything tolerates missing values and renders "n/a".

export const NA = 'n/a';

export const isNum = (x) => typeof x === 'number' && Number.isFinite(x);

/** Normalise a value that may be a number, {est,lo,hi}, or missing into {est,lo,hi} (fields may be null). */
export function val(x) {
  if (isNum(x)) return { est: x, lo: null, hi: null };
  if (x && typeof x === 'object') {
    const est = isNum(x.est) ? x.est : isNum(x.pred) ? x.pred : isNum(x.value) ? x.value : null;
    return { est, lo: isNum(x.lo) ? x.lo : null, hi: isNum(x.hi) ? x.hi : null };
  }
  return { est: null, lo: null, hi: null };
}

/** Multiply an {est,lo,hi} by a scalar. */
export function scale(v, k) {
  const m = (a) => (isNum(a) && isNum(k) ? a * k : null);
  return { est: m(v.est), lo: m(v.lo), hi: m(v.hi) };
}

/** First defined property among aliases. */
export function pick(obj, ...keys) {
  if (!obj) return undefined;
  for (const k of keys) if (obj[k] !== undefined && obj[k] !== null) return obj[k];
  return undefined;
}

/** "$1.2B", "$340M", "$12K" for totals. */
export function usdBig(x) {
  if (!isNum(x)) return NA;
  const a = Math.abs(x), s = x < 0 ? '−' : '';
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(a >= 1e10 ? 0 : 1)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(a >= 1e8 ? 0 : 1)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`;
  return `${s}$${a.toFixed(0)}`;
}

/** "$38" per acre (whole dollars; one decimal under $10). */
export function usd(x, { sign = false } = {}) {
  if (!isNum(x)) return NA;
  const a = Math.abs(x);
  const body = a < 9.95 && a !== 0 ? a.toFixed(1) : Math.round(a).toLocaleString('en-US');
  const s = x < 0 ? '−' : sign && x > 0 ? '+' : '';
  return `${s}$${body}`;
}

/** Range text "$30–$45" (or "" when no range). */
export function rangeTxt(v, f = usd) {
  if (!v || !isNum(v.lo) || !isNum(v.hi)) return '';
  return `${f(v.lo)}–${f(v.hi)}`;
}

export function pct(x, digits = 0) {
  return isNum(x) ? `${(x * 100).toFixed(digits)}%` : NA;
}

export function num(x, digits = 2) {
  return isNum(x) ? x.toFixed(digits) : NA;
}

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

/** Linear interpolation of ys at x over sorted xs (clamped). */
export function interp(xs, ys, x) {
  if (!Array.isArray(xs) || !Array.isArray(ys) || !xs.length || !isNum(x)) return null;
  const pts = xs.map((v, i) => [v, ys[i]]).filter((p) => isNum(p[0]) && isNum(p[1])).sort((a, b) => a[0] - b[0]);
  if (!pts.length) return null;
  if (x <= pts[0][0]) return pts[0][1];
  if (x >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 1; i < pts.length; i++) {
    if (x <= pts[i][0]) {
      const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
      return x1 === x0 ? y1 : y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
    }
  }
  return null;
}

export function $(sel, root = document) { return root.querySelector(sel); }

/** Show a tooltip near a pointer event. */
export function showTip(html, ev) {
  const tip = document.getElementById('tooltip');
  if (!tip) return;
  tip.innerHTML = html;
  tip.hidden = false;
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > window.innerWidth - 8) x = ev.clientX - w - pad;
  if (y + h > window.innerHeight - 8) y = ev.clientY - h - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
export function hideTip() { const t = document.getElementById('tooltip'); if (t) t.hidden = true; }

export const STATE_NAMES = { IA: 'Iowa', NE: 'Nebraska', KS: 'Kansas', MO: 'Missouri', IL: 'Illinois', SD: 'South Dakota', MN: 'Minnesota' };
