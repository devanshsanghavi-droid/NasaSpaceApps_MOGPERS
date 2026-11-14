// Chart.js charts: synthetic control (actual vs counterfactual with band) and the CMIP6 heat trajectory.
import { cssVar, isNum, fmt } from "./util.js";
import { smoothedSeries, heatPath } from "./model.js";

const registry = new Map();
export function destroyChart(id) { const c = registry.get(id); if (c) { c.destroy(); registry.delete(id); } }

function alpha(hex, a) {
  const h = hex.replace("#", "");
  if (h.length !== 6) return hex;
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function baseOptions() {
  const muted = cssVar("--muted"), line = cssVar("--line"), ink = cssVar("--ink");
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "bottom", align: "start", labels: { color: ink, boxWidth: 14, boxHeight: 2, font: { size: 11 } } },
      tooltip: { backgroundColor: ink, titleColor: cssVar("--ground"), bodyColor: cssVar("--ground"), padding: 8, cornerRadius: 4, displayColors: true, boxWidth: 8, boxHeight: 8 },
    },
    scales: {
      x: { grid: { display: false }, border: { color: line }, ticks: { color: muted, font: { size: 11 } } },
      y: { grid: { color: line }, border: { display: false }, ticks: { color: muted, font: { size: 11 }, maxTicksLimit: 5 } },
    },
  };
}

// Vertical marker line at a given x label (switch year / selected year)
const markerPlugin = {
  id: "marker",
  afterDatasetsDraw(chart, _args, opts) {
    if (opts == null || opts.value == null) return;
    const xs = chart.scales.x;
    const x = xs.getPixelForValue(opts.value);
    if (!isNum(x)) return;
    const { top, bottom } = chart.chartArea;
    const ctx = chart.ctx;
    ctx.save();
    ctx.strokeStyle = opts.color; ctx.lineWidth = 1.5; ctx.setLineDash(opts.dash || []);
    ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = opts.color; ctx.font = "600 11px system-ui, sans-serif"; ctx.textAlign = x > chart.chartArea.right - 60 ? "right" : "left";
    ctx.fillText(opts.label || "", x + (ctx.textAlign === "right" ? -5 : 5), top + 11);
    ctx.restore();
  },
};

export function synthControlChart(canvas, sc) {
  destroyChart(canvas.id);
  const accent = cssVar("--accent"), ink = cssVar("--ink"), bar = cssVar("--muted");
  const unit = sc.outcome === "yield_bu_ac" ? "bu/ac" : sc.outcome || "";
  const labels = sc.years.map(String);
  const opts = baseOptions();
  opts.plugins.legend.labels.filter = (item) => item.text !== "_lo";
  opts.plugins.tooltip.filter = (item) => item.dataset.label !== "_lo";
  opts.plugins.tooltip.callbacks = { label: (c) => ` ${c.dataset.label === "90% band" ? "Band high" : c.dataset.label}: ${fmt(c.parsed.y, 1)} ${unit}` };
  opts.plugins.marker = { value: String(sc.switch_year), label: `switch ${sc.switch_year}`, color: ink, dash: [4, 3] };
  opts.scales.y.title = { display: true, text: unit, color: cssVar("--muted"), font: { size: 11 } };
  const chart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "90% band", data: sc.hi, borderWidth: 0, pointRadius: 0, backgroundColor: alpha(bar, 0.18), fill: "+1" },
        { label: "_lo", data: sc.lo, borderWidth: 0, pointRadius: 0, fill: false },
        { label: "Twins (counterfactual)", data: sc.counterfactual, borderColor: bar, borderWidth: 2, borderDash: [5, 4], pointRadius: 0, pointHoverRadius: 4, tension: 0.25 },
        { label: "This field (actual)", data: sc.actual, borderColor: accent, backgroundColor: accent, borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, tension: 0.25 },
      ],
    },
    options: opts,
    plugins: [markerPlugin],
  });
  registry.set(canvas.id, chart);
  return chart;
}

// Linear year axis: CMIP6 historical (per year), the interpolated gap before the scenario years (dotted),
// and both SSPs (11-year running mean) over their exported years. Marker = selected slider year (numeric).
export function climateChart(canvas, climate, scenario, year) {
  destroyChart(canvas.id);
  const ink = cssVar("--ink"), muted = cssVar("--muted"), accent = cssVar("--accent");
  const pts = (years, vals) => years.map((y, i) => ({ x: y, y: vals[i] })).filter((d) => isNum(d.x) && isNum(d.y));
  const s245 = smoothedSeries(climate, "ssp245", "hdd30");
  const s585 = smoothedSeries(climate, "ssp585", "hdd30");
  if (!s245 && !s585) return null;
  const unitRaw = climate?.units?.hdd30;
  const unit = typeof unitRaw === "string" && unitRaw.trim() ? unitRaw.trim() : "C-days > 30 C";
  const hist = climate?.historical || {};
  const hv = Array.isArray(hist.hdd30) ? hist.hdd30 : [];
  const hy = Array.isArray(hist.years) && hist.years.length === hv.length ? hist.years : null;

  const opts = baseOptions();
  opts.interaction = { mode: "nearest", axis: "x", intersect: false };
  opts.plugins.marker = { value: Number(year), label: String(year), color: accent };
  opts.plugins.legend.labels.filter = (item) => !item.text.startsWith("_");
  opts.plugins.tooltip.filter = (item) => !item.dataset.label.startsWith("_");
  opts.plugins.tooltip.callbacks = {
    title: (items) => (items.length ? String(items[0].parsed.x) : ""),
    label: (c) => ` ${c.dataset.label}: ${fmt(c.parsed.y, 1)} ${unit}`,
  };
  opts.scales.y.title = { display: true, text: unit, color: muted, font: { size: 11 } };
  const allYears = [...(hy || []), ...(s245?.years || []), ...(s585?.years || []), Number(year), 2025].filter(isNum);
  opts.scales.x.type = "linear";
  opts.scales.x.min = Math.min(...allYears);
  opts.scales.x.max = Math.max(...allYears);
  opts.scales.x.ticks = { ...opts.scales.x.ticks, stepSize: 10, callback: (v) => String(v) };

  const ds = [];
  if (hy) ds.push({ label: `Historical ${Math.min(...hy)}-${Math.max(...hy)}`, data: pts(hy, hv), borderColor: muted, borderWidth: 1.2, pointRadius: 0, pointHoverRadius: 3, tension: 0.2 });
  const p = heatPath(climate, scenario);
  if (p?.anchor && isNum(p.firstYear)) {
    const gap = [];
    const start = hy ? Math.max(...hy) : Math.ceil(p.anchor.year); // do not draw over the historical years
    for (let y = start; y < p.firstYear; y++) gap.push({ x: y, y: p.H(y) });
    gap.push({ x: p.firstYear, y: p.H(p.firstYear) });
    ds.push({ label: "Interpolated", data: gap.filter((d) => isNum(d.y)), borderColor: muted, borderWidth: 1, borderDash: [2, 3], pointRadius: 0, pointHoverRadius: 0 });
  }
  const scen = (key, label, s, dash) => s && ds.push({ label, data: pts(s.years, s.smooth),
    borderColor: scenario === key ? ink : muted, borderWidth: scenario === key ? 2.5 : 1.2, borderDash: dash, pointRadius: 0, pointHoverRadius: 3, tension: 0.3 });
  scen("ssp245", "SSP2-4.5", s245, []);
  scen("ssp585", "SSP5-8.5", s585, [6, 3]);
  const chart = new Chart(canvas, { type: "line", data: { datasets: ds }, options: opts, plugins: [markerPlugin] });
  registry.set(canvas.id, chart);
  return chart;
}

export function setMarker(id, year) {
  const c = registry.get(id);
  if (!c) return;
  c.options.plugins.marker.value = Number(year);
  c.options.plugins.marker.label = String(year);
  c.update("none");
}
