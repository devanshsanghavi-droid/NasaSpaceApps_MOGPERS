// Shared helpers: escaping, number formatting, CSS-token colours, tooltips.

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const isNum = (v) => typeof v === "number" && Number.isFinite(v);

// Signed number with a real minus sign, e.g. "+1.2", "−0.4"
export function signed(v, nd = 1) {
  if (!isNum(v)) return "n/a";
  const s = Math.abs(v).toFixed(nd);
  if (Number(s) === 0) return (0).toFixed(nd);
  return (v > 0 ? "+" : "−") + s;
}
export function fmt(v, nd = 1) {
  if (!isNum(v)) return "n/a";
  return v.toLocaleString(undefined, { minimumFractionDigits: nd, maximumFractionDigits: nd });
}
export const fmtInt = (v) => (isNum(v) ? Math.round(v).toLocaleString() : "n/a");
export const pct = (v, nd = 0) => (isNum(v) ? (v * 100).toFixed(nd) + "%" : "n/a");

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export const STRATEGY_VARS = { S0: "--s0", S1: "--s1", S2: "--s2", S3: "--s3" };
export const TYPE_VARS = ["--t1", "--t2", "--t3", "--t4", "--t5", "--t6"];
export const BADGE_VARS = { strong: "--b-strong", moderate: "--b-moderate", thin: "--b-thin", beyond: "--b-beyond" };
export const BADGE_LABEL = { strong: "Strong", moderate: "Moderate", thin: "Thin", beyond: "Beyond evidence" };
export const BADGE_LEVEL = { strong: 3, moderate: 2, thin: 1, beyond: 0 };

export const strategyColor = (sid) => cssVar(STRATEGY_VARS[sid] || "--s0") || "#888";
export function typeColor(typeId, typeOrder) {
  const i = typeOrder.indexOf(typeId);
  // Only six categorical slots are defined. Beyond six types the colour folds to grey; the panel names the type in words.
  return i >= 0 && i < TYPE_VARS.length ? cssVar(TYPE_VARS[i]) : cssVar("--s0");
}

export const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
export const isDark = () => {
  const t = document.documentElement.dataset.theme;
  if (t) return t === "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
};

// ---- tooltip: any element with data-tip gets a hover/focus tooltip
export function initTooltips() {
  const tip = document.getElementById("tooltip");
  let current = null;
  const show = (el) => {
    const text = el.getAttribute("data-tip");
    if (!text) return;
    current = el;
    tip.textContent = text;
    tip.hidden = false;
    const r = el.getBoundingClientRect();
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let x = Math.min(Math.max(8, r.left + r.width / 2 - tw / 2), window.innerWidth - tw - 8);
    let y = r.top - th - 8;
    if (y < 8) y = r.bottom + 8;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  };
  const hide = (el) => { if (!el || el === current) { tip.hidden = true; current = null; } };
  document.addEventListener("mouseover", (e) => { const el = e.target.closest("[data-tip]"); if (el) show(el); });
  document.addEventListener("mouseout", (e) => { const el = e.target.closest("[data-tip]"); if (el) hide(el); });
  document.addEventListener("focusin", (e) => { const el = e.target.closest("[data-tip]"); if (el) show(el); });
  document.addEventListener("focusout", (e) => { const el = e.target.closest("[data-tip]"); if (el) hide(el); });
  window.addEventListener("scroll", () => hide(), true);
}

export function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
