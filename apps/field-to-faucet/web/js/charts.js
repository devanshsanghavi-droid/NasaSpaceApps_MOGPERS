// Chart.js helpers: daily time-series on a linear millisecond axis (no date adapter needed), nulls drawn as gaps.
/* global Chart */
import { cssVar, fmtDate, isNum, MON3 } from "./util.js";

const DAY = 86400000;

export function colors() {
  return {
    ink: cssVar("--ink"), ink2: cssVar("--ink-2"), muted: cssVar("--muted"), line: cssVar("--line"),
    accent: cssVar("--accent"), nitrate: cssVar("--nitrate"), obs: cssVar("--obs"), base: cssVar("--base"), band: cssVar("--band"),
  };
}

function setDefaults() {
  if (setDefaults.done) return;
  setDefaults.done = true;
  const c = colors();
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = c.muted;
  Chart.defaults.borderColor = c.line;
  Chart.defaults.animation = false;
  Chart.defaults.maintainAspectRatio = false;
}

// Year ticks for long spans, month ticks for short ones, day ticks for ~2 weeks.
function timeTicks(scale) {
  const min = scale.min, max = scale.max, span = max - min;
  const out = [];
  const d0 = new Date(min);
  if (span > 2.5 * 365 * DAY) {
    for (let y = d0.getUTCFullYear(); ; y++) { const t = Date.UTC(y, 0, 1); if (t > max) break; if (t >= min) out.push({ value: t }); }
  } else if (span > 60 * DAY) {
    const stepM = span > 400 * DAY ? 3 : span > 200 * DAY ? 2 : 1;
    for (let y = d0.getUTCFullYear(), m = d0.getUTCMonth(); ; m++) {
      if (m > 11) { m = 0; y++; }
      const t = Date.UTC(y, m, 1);
      if (t > max) break;
      if (t >= min && m % stepM === 0) out.push({ value: t });
    }
  } else {
    const step = span > 20 * DAY ? 7 : 2;
    for (let t = Math.ceil(min / DAY) * DAY, i = 0; t <= max; t += DAY, i++) if (i % step === 0) out.push({ value: t });
  }
  scale.ticks = out;
}
function tickLabel(value, span) {
  const d = new Date(value);
  if (span > 2.5 * 365 * DAY) return String(d.getUTCFullYear());
  if (span > 60 * DAY) return d.getUTCMonth() === 0 ? `${MON3[0]} ${d.getUTCFullYear()}` : MON3[d.getUTCMonth()];
  return `${MON3[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

// Draws shaded train/test/live periods and labels them.
const splitPlugin = {
  id: "splitShade",
  beforeDatasetsDraw(chart, _a, opts) {
    const spans = opts?.spans;
    if (!spans?.length) return;
    const { ctx, chartArea: a, scales: { x } } = chart;
    ctx.save();
    for (const s of spans) {
      const x0 = Math.max(a.left, x.getPixelForValue(s.from)), x1 = Math.min(a.right, x.getPixelForValue(s.to + DAY));
      if (x1 <= x0) continue;
      ctx.fillStyle = s.fill;
      ctx.fillRect(x0, a.top, x1 - x0, a.bottom - a.top);
      if (x1 - x0 > 46) {
        ctx.fillStyle = colors().muted;
        ctx.font = "600 11px " + Chart.defaults.font.family;
        ctx.textBaseline = "top";
        ctx.fillText(s.label, x0 + 5, a.top + 4);
      }
    }
    ctx.restore();
  },
};

// Horizontal threshold (EPA limit) with a label.
const thresholdPlugin = {
  id: "threshold",
  afterDatasetsDraw(chart, _a, opts) {
    if (!isNum(opts?.value)) return;
    const { ctx, chartArea: a, scales: { y } } = chart;
    const py = y.getPixelForValue(opts.value);
    if (py < a.top || py > a.bottom) return;
    const c = colors();
    ctx.save();
    ctx.strokeStyle = opts.color || c.nitrate;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.moveTo(a.left, py); ctx.lineTo(a.right, py); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = opts.color || c.nitrate;
    ctx.font = "700 11px " + Chart.defaults.font.family;
    ctx.textAlign = opts.align === "left" ? "left" : "right";
    ctx.textBaseline = "bottom";
    ctx.fillText(opts.label || `Limit ${opts.value}`, opts.align === "left" ? a.left + 4 : a.right - 4, py - 3);
    ctx.restore();
  },
};

// Vertical crosshair at the hovered x.
const crosshairPlugin = {
  id: "crosshair",
  afterDatasetsDraw(chart) {
    const act = chart.tooltip?.getActiveElements?.();
    if (!act?.length) return;
    const { ctx, chartArea: a } = chart;
    const px = act[0].element.x;
    ctx.save();
    ctx.strokeStyle = colors().muted;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
    ctx.restore();
  },
};

export const toXY = (dates, vals) => dates.map((d, i) => ({ x: typeof d === "number" ? d : Date.parse(d + "T00:00:00Z"), y: isNum(vals?.[i]) ? vals[i] : null }));

/**
 * Generic time-series chart.
 * series: [{label, data:[{x,y}], color, width, dash, fill, kind:'line'|'bandLo'|'bandHi'|'points', hideInTooltip}]
 */
export function timeChart(canvas, { series, xMin, xMax, yMax, yHardMax, yLabel = "Nitrate (mg/L as N)", threshold, spans, unit = "mg/L", digits = 1, bandLabel = "8-in-10 model range" }) {
  // Vendored Chart.js missing (blocked or failed download): say so in place of the chart; callers handle null.
  if (typeof Chart === "undefined") {
    const box = canvas?.parentElement;
    if (box && !box.querySelector(".map-msg")) box.insertAdjacentHTML("beforeend", `<div class="map-msg">The chart library did not load, so this chart cannot be drawn. The numbers in the text still apply.</div>`);
    return null;
  }
  setDefaults();
  const c = colors();
  const datasets = series.map((s) => ({
    label: s.label,
    data: s.data,
    borderColor: s.kind === "bandLo" || s.kind === "bandHi" ? "transparent" : s.color,
    backgroundColor: s.kind === "bandHi" ? c.band : s.color,
    borderWidth: s.width ?? 2,
    borderDash: s.dash || [],
    pointRadius: s.kind === "points" ? 2 : 0,
    pointHoverRadius: s.kind === "points" ? 4 : 3,
    showLine: s.kind !== "points",
    fill: s.kind === "bandHi" ? "-1" : false,
    spanGaps: false,
    tension: 0,
    order: s.order ?? 0,
    _hide: s.hideInTooltip || s.kind === "bandLo" || s.kind === "bandHi",
    _band: s.kind === "bandHi",
  }));
  const chart = new Chart(canvas, {
    type: "line",
    data: { datasets },
    options: {
      parsing: false,
      normalized: true,
      interaction: { mode: "index", intersect: false },
      layout: { padding: { top: 4, right: 6 } },
      scales: {
        x: {
          type: "linear", min: xMin, max: xMax,
          afterBuildTicks: timeTicks,
          ticks: { autoSkip: true, maxRotation: 0, callback(v) { return tickLabel(v, this.max - this.min); } },
          grid: { display: false },
        },
        y: {
          beginAtZero: true, suggestedMax: yMax ?? 12, max: yHardMax,
          title: { display: !!yLabel, text: yLabel, color: c.muted },
          grid: { color: c.line },
          ticks: { maxTicksLimit: 6 },
        },
      },
      plugins: {
        legend: { display: false },
        decimation: { enabled: false },
        splitShade: { spans },
        threshold,
        tooltip: {
          backgroundColor: "rgba(16,24,31,0.92)",
          padding: 8,
          filter: (item) => !item.dataset._hide && item.raw && isNum(item.raw.y),
          callbacks: {
            title: (items) => (items.length ? fmtDate(items[0].raw.x) : ""),
            label: (item) => ` ${item.dataset.label}: ${item.raw.y.toFixed(digits)} ${unit}`,
            afterBody: (items) => {
              if (!items.length) return "";
              const i = items[0].dataIndex;
              const hi = chart.data.datasets.find((d) => d._band && !d.hidden);
              if (!hi) return "";
              const lo = chart.data.datasets[chart.data.datasets.indexOf(hi) - 1];
              const a = lo?.data[i]?.y, b = hi.data[i]?.y;
              return isNum(a) && isNum(b) ? ` ${bandLabel}: ${a.toFixed(digits)}–${b.toFixed(digits)} ${unit}` : "";
            },
          },
        },
      },
    },
    plugins: [splitPlugin, thresholdPlugin, crosshairPlugin],
  });
  return chart;
}

export function legendHTML(items) {
  // band swatches take an explicit rgba fill when given (e.g. "kept out of the river"), else the shared band tint
  return items.map((it) => `<span><span class="sw ${it.kind || ""}" style="color:${it.color}${it.kind === "band" && /^rgba/.test(it.color) ? `;background:${it.color}` : ""}"></span>${it.label}</span>`).join("");
}
