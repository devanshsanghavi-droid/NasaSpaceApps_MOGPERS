// Shared helpers: escaping, number formatting, colours, small DOM helpers.

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const isNum = (v) => typeof v === "number" && Number.isFinite(v);
export const $ = (sel, root = document) => root.querySelector(sel);
export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

export function fmt(v, nd = 0) {
  if (!isNum(v)) return "–";
  return v.toLocaleString("en-US", { minimumFractionDigits: nd, maximumFractionDigits: nd });
}
export const fmtInt = (v) => (isNum(v) ? Math.round(v).toLocaleString("en-US") : "–");
export const pct = (v, nd = 0) => (isNum(v) ? (v * 100).toFixed(nd) + "%" : "–");

// $2.2M, $16k, $420
export function usd(v, { compact = true } = {}) {
  if (!isNum(v)) return "–";
  const a = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  if (!compact || a < 1000) return sign + "$" + Math.round(a).toLocaleString("en-US");
  if (a < 1e6) return sign + "$" + (a / 1e3).toFixed(a < 1e4 ? 1 : 0).replace(/\.0$/, "") + "k";
  return sign + "$" + (a / 1e6).toFixed(a < 1e7 ? 1 : 0).replace(/\.0$/, "") + "M";
}

// "{p10,p50,p90}" or "{p50,lo,hi}" -> {mid, lo, hi}
export function band(o) {
  if (o == null) return null;
  if (isNum(o)) return { mid: o, lo: o, hi: o };
  const mid = o.p50 ?? o.mid ?? o.mean ?? o.value;
  const lo = o.lo ?? o.p10 ?? o.low;
  const hi = o.hi ?? o.p90 ?? o.high;
  if (!isNum(mid)) return null;
  return { mid, lo: isNum(lo) ? lo : mid, hi: isNum(hi) ? hi : mid };
}

export const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
export const MON3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
export const LEAK_RAMP = () => [0, 1, 2, 3, 4, 5].map((i) => cssVar(`--leak-${i}`));

// relative luminance -> pick white text on dark cells
export function isDarkColor(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return false;
  const n = parseInt(m[1], 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    c /= 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2] < 0.25;
}

export function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function link(url, text) {
  if (!url) return esc(text);
  return `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>`;
}

export const parseDate = (s) => {
  // "YYYY-MM-DD" -> UTC ms (no timezone drift)
  const [y, m, d] = String(s).split("-").map(Number);
  return Date.UTC(y, (m || 1) - 1, d || 1);
};
export const fmtDate = (ms, opts = { month: "short", day: "numeric", year: "numeric" }) =>
  new Date(ms).toLocaleDateString("en-US", { timeZone: "UTC", ...opts });

// Segmented control: buttons with aria-pressed. Returns a setter.
export function segmented(container, options, initial, onChange) {
  container.innerHTML = options.map((o) => `<button type="button" data-v="${esc(o.value)}" aria-pressed="${o.value === initial}">${esc(o.label)}</button>`).join("");
  container.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    set(b.dataset.v);
    onChange(b.dataset.v);
  });
  function set(v) {
    container.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.v === v)));
  }
  return set;
}

// "about 1 day in 3"
export function naturalFreq(days, total) {
  if (!isNum(days) || !isNum(total) || total <= 0) return "";
  if (days <= 0) return "no days";
  const r = total / days;
  if (r < 1.15) return "almost every day";
  if (r < 1.6) return "about 2 days in 3";
  if (r < 2.4) return "about 1 day in 2";
  return `about 1 day in ${Math.round(r)}`;
}

export function monthRange(a, b) {
  return a === b ? MONTH_NAMES[a] : `${MONTH_NAMES[a]}–${MONTH_NAMES[b]}`;
}
