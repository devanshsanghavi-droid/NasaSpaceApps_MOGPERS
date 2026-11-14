// City / tap-water view: KPI strip, 2025 replay with adoption slider, river chart, hotspot map, 14-day outlook.
/* global maplibregl */
import { band, esc, fmt, fmtDate, fmtInt, isNum, link, naturalFreq, pct, segmented, usd, LEAK_RAMP, parseDate } from "./util.js";
import { colors, legendHTML, timeChart, toXY } from "./charts.js";
import { addContext, addPlaces, addRivers, addSites, bboxOf, createMap, quantileBreaks, rampLegend, stepExpr } from "./map.js";
import { factsMap, mockChip } from "./data.js";

const PRIMARY = "05484500";
const nwisUrl = (site) => `https://waterdata.usgs.gov/monitoring-location/${site}/`;
const shortSite = (name) => String(name || "").split(",")[0];

let S; // store
let F; // facts map

export function renderCity(store) {
  S = store;
  F = factsMap(store.data.facts);
  renderHeadline();
  renderReplay();
  renderRiver();
  renderOutlook();
  renderHotspotList();
}

function replayYear() {
  return S.data.scenarios?.replay?.year ?? 2025;
}
function yearBlock() {
  const sc = S.data.scenarios;
  const y = replayYear();
  return sc?.by_year?.[y] ?? sc?.by_year?.[String(y)] ?? null;
}
function siteName(site) {
  const rs = S.data.river_series?.sites?.[site];
  const st = (S.data.sites || []).find((s) => s.site === site);
  return rs?.name || st?.name || site;
}
function fact(key) {
  const f = F[key];
  return f && isNum(f.value) ? f : null;
}
function srcLine(...parts) {
  return parts.filter(Boolean).join(" · ");
}

// ------------------------------------------------------------------ headline + KPIs
function renderHeadline() {
  const y = replayYear();
  document.getElementById("city-year").textContent = y;
  document.querySelectorAll(".js-replay-year").forEach((e) => (e.textContent = y));
  const yb = yearBlock();
  const obs = yb?.observed || {};
  const site = yb?.site || S.data.scenarios?.replay?.site || PRIMARY;
  const sc = S.data.scenarios;
  const th = sc?.thresholds || {};
  const people = fact("people_served");
  const chipSc = mockChip(S.source, "scenarios");

  // count measured days in the replay year for the natural frequency
  const rp = sc?.replay;
  const measured = rp?.obs ? rp.obs.filter(isNum).length : null;
  const lede = document.getElementById("city-lede");
  if (isNum(obs.days_over10)) {
    const freq = measured ? ` — ${naturalFreq(obs.days_over10, measured)} with a measurement` : "";
    lede.innerHTML = `In ${y}, the ${esc(shortSite(siteName(site)).replace(/ at .*/, ""))}, a drinking-water source for ${people ? `about <strong>${fmtInt(people.value)} people</strong>` : "central Iowa"}, ran above the federal nitrate limit on <strong class="red">${fmtInt(obs.days_over10)} days</strong>${freq}. NASA satellites show why: upstream fields sat bare while spring storms soaked the soil.`;
  } else {
    lede.textContent = "Scenario data is not available yet.";
  }

  const plantFact = fact(`plant_days_${y}`);
  const plantDays = isNum(obs.plant_days) ? obs.plant_days : plantFact?.value;
  const costFact = fact(`plant_cost_${y}_usd`);
  const cpd = band(th.cost_per_plant_day);
  let costTxt = "–", costSrc = "";
  if (costFact) { costTxt = usd(costFact.value); costSrc = link(costFact.url, costFact.source || "source"); }
  else if (isNum(plantDays) && cpd) { costTxt = cpd.lo === cpd.hi ? usd(plantDays * cpd.mid) : `${usd(plantDays * cpd.lo)}–${usd(plantDays * cpd.hi).replace("$", "")}`; costSrc = `days × ${usd(cpd.lo)}–${usd(cpd.hi)}/day · ${esc(th.source || "")}`; }
  const banFact = fact(`ban_days_${y}`);
  const banDays = isNum(obs.ban_days) ? obs.ban_days : banFact?.value;

  const tiles = [
    { v: fmtInt(obs.days_over10), red: true, l: `days above 10 mg/L at the intake (${y})`, s: srcLine(link(nwisUrl(site), `USGS ${site}`), chipSc) },
    { v: fmtInt(plantDays), l: "days the nitrate-removal plant had to run", s: srcLine(plantFact ? link(plantFact.url, plantFact.source || "source") : esc(th.source ? `model days > ${th.plant_on_mgL ?? "?"} mg/L` : ""), mockChip(S.source, plantFact ? "facts" : "scenarios")) },
    { v: costTxt, l: "spent removing nitrate", s: srcLine(costSrc, mockChip(S.source, costFact ? "facts" : "scenarios")) },
    { v: fmtInt(banDays), l: "days of lawn-watering ban", s: srcLine(isNum(obs.ban_days) ? esc(th.source || "") : banFact ? link(banFact.url, banFact.source || "source") : "", mockChip(S.source, isNum(obs.ban_days) ? "scenarios" : "facts")) },
    { v: people ? (people.value >= 1e5 ? `${Math.round(people.value / 1000)}k` : fmtInt(people.value)) : "–", l: "people drink this water", s: srcLine(people ? link(people.url, people.source || "source") : "", mockChip(S.source, "facts")) },
  ];
  document.getElementById("city-kpis").innerHTML = tiles.map((t) => `<div class="kpi"><div class="kpi-value ${t.red ? "red" : ""}">${t.v}</div><div class="kpi-label">${t.l}</div><div class="kpi-src">${t.s || ""}</div></div>`).join("");
}

// ------------------------------------------------------------------ replay
let replayChart;
function renderReplay() {
  const sc = S.data.scenarios;
  const rp = sc?.replay;
  const yb = yearBlock();
  const slider = document.getElementById("adopt");
  const levels = (yb?.levels || []).slice().sort((a, b) => a.x - b.x);
  const xs = (sc?.adoption_levels?.length ? sc.adoption_levels : levels.map((l) => l.x)).filter(isNum);
  if (!rp || !levels.length || !xs.length) {
    document.getElementById("replay-freq").textContent = "Scenario results are not available yet.";
    return;
  }
  slider.min = Math.min(...xs);
  slider.max = Math.max(...xs);
  slider.step = xs.length > 1 ? xs[1] - xs[0] : 5;
  const ticks = document.querySelector(".slider-ticks");
  const mid = (Number(slider.min) + Number(slider.max)) / 2;
  ticks.innerHTML = `<span>${slider.min}%</span><span>${mid}%</span><span>${slider.max}%</span>`;

  const c = colors();
  const dates = rp.dates.map(parseDate);
  const xMin = dates[0], xMax = dates[dates.length - 1];
  const obsXY = toXY(dates, rp.obs);
  const baseXY = toXY(dates, rp.base_p50);
  replayChart = timeChart(document.getElementById("replay-chart"), {
    xMin, xMax, threshold: { value: S.data.river_series?.mcl ?? 10, label: "EPA limit 10 mg/L" },
    series: [
      { label: "Measured (USGS)", data: obsXY, color: c.obs, width: 1.6, order: 0 },
      { label: "Model, today's fields", data: baseXY, color: c.base, width: 1.6, dash: [4, 3], order: 2 },
      { label: "Model, with living cover", data: baseXY.map((p) => ({ ...p })), color: c.accent, width: 2.2, order: 1 },
    ],
  });
  // fill between "today" and "with cover" to show the nitrate taken out of the river
  const ds = replayChart.data.datasets[2];
  ds.fill = { target: 1, above: "transparent", below: "rgba(11,95,102,0.22)" };

  document.getElementById("replay-legend").innerHTML = legendHTML([
    { label: "Measured at the intake (USGS)", color: c.obs },
    { label: "Model, today's fields", color: c.base, kind: "dash" },
    { label: "Model, with living cover", color: c.accent },
    { label: "Nitrate kept out of the river", color: "rgba(11,95,102,0.35)", kind: "band" },
  ]) + mockChip(S.source, "scenarios");
  document.getElementById("replay-note").innerHTML = `${esc(sc.method || "")} Ranges are 8-in-10 model ranges.`;

  const update = () => {
    const x = Number(slider.value);
    const lvl = levels.reduce((best, l) => (Math.abs(l.x - x) < Math.abs(best.x - x) ? l : best), levels[0]);
    document.getElementById("adopt-val").textContent = `${lvl.x}%`;
    const series = rp.by_level?.[lvl.x] ?? rp.by_level?.[String(lvl.x)];
    ds.data = series ? toXY(dates, series) : baseXY;
    ds.hidden = lvl.x === 0;
    replayChart.update("none");
    renderDeltas(lvl, levels[0], yb, rp);
  };
  slider.addEventListener("input", update);
  // demo moment: open at 25% when available
  const start = xs.includes(25) ? 25 : xs[Math.floor(xs.length / 2)];
  slider.value = start;
  update();
}

function delta(lvl, base, key) {
  const av = lvl.avoided?.[key];
  if (av) { const b = band(av); if (b) return { mid: b.mid, lo: Math.min(b.lo, b.hi), hi: Math.max(b.lo, b.hi) }; }
  const b0 = band(base?.[key]), bx = band(lvl?.[key]);
  if (!b0 || !bx) return null;
  const sign = key === "lbN_kept" ? -1 : 1; // lbN_kept grows with adoption
  const m = sign * (b0.mid - bx.mid);
  const a = sign * (b0.mid - bx.hi), b = sign * (b0.mid - bx.lo);
  return { mid: Math.max(0, m), lo: Math.max(0, Math.min(a, b)), hi: Math.max(0, Math.max(a, b)) };
}

function renderDeltas(lvl, base, yb, rp) {
  const obs = yb.observed || {};
  const measured = rp.obs.filter(isNum).length;
  const d = (k) => delta(lvl, base, k);
  const dd = d("days_over10");
  const freq = document.getElementById("replay-freq");
  if (lvl.x === 0) {
    freq.innerHTML = `Measured in ${rp.year}: above the limit on <strong>${fmtInt(obs.days_over10)} of ${fmtInt(measured)}</strong> measured days (${naturalFreq(obs.days_over10, measured)}). Move the slider to add living cover.`;
  } else if (dd && isNum(obs.days_over10)) {
    const n = Math.max(0, obs.days_over10 - dd.mid), lo = Math.max(0, obs.days_over10 - dd.hi), hi = Math.max(0, obs.days_over10 - dd.lo);
    freq.innerHTML = `Measured: above the limit on <strong>${fmtInt(obs.days_over10)}</strong> days (${naturalFreq(obs.days_over10, measured)}). With ${lvl.x}% living cover the model gives about <strong>${fmtInt(n)} days</strong> (range ${fmtInt(lo)}–${fmtInt(hi)}), ${naturalFreq(n, measured)}.`;
  }
  const fmtD = (b, f) => (b ? (b.lo === b.hi ? f(b.mid) : `range ${f(b.lo)}–${f(b.hi)}`) : "");
  const tiles = [
    { k: "days_over10", lab: "fewer days above 10 mg/L", f: fmtInt },
    { k: "plant_days", lab: "fewer removal-plant days", f: fmtInt },
    { k: "cost_usd", lab: "removal cost avoided", f: usd },
    { k: "ban_days", lab: "fewer watering-ban days", f: fmtInt },
  ];
  const html = tiles.map((t) => {
    const b = d(t.k);
    const zero = !b || b.mid === 0;
    return `<div class="delta"><div class="delta-num ${zero ? "zero" : ""}">${b ? t.f(b.mid) : "–"}</div><div class="delta-lab">${t.lab}</div><div class="delta-rng">${lvl.x === 0 ? "&nbsp;" : fmtD(b, t.f)}</div></div>`;
  }).join("");
  const kept = d("lbN_kept");
  const keptTxt = kept && lvl.x > 0 ? `<p class="fine" style="grid-column:1/-1">Fields would also keep about <strong>${fmtLb(kept.mid)}</strong> of nitrogen (range ${fmtLbRange(kept.lo, kept.hi)}): fertilizer farmers already paid for.</p>` : "";
  document.getElementById("replay-deltas").innerHTML = html + keptTxt;
}
const fmtLbRange = (a, b) => (isNum(b) && b >= 1e6 && a >= 1e5 ? `${(a / 1e6).toFixed(1)}–${(b / 1e6).toFixed(1)} million lb` : `${fmtLb(a)}–${fmtLb(b)}`);
const fmtLb = (v) => (!isNum(v) ? "–" : v >= 1e6 ? `${(v / 1e6).toFixed(1)} million lb` : `${fmtInt(v)} lb`);

// ------------------------------------------------------------------ river chart
let riverChart, riverSite = PRIMARY, riverRange = "test";
function renderRiver() {
  const rs = S.data.river_series;
  const box = document.getElementById("river-chart");
  if (!rs?.sites || !Object.keys(rs.sites).length) {
    document.getElementById("river-note").textContent = "River series not available yet.";
    return;
  }
  const sites = Object.keys(rs.sites).sort((a, b) => (a === PRIMARY ? -1 : b === PRIMARY ? 1 : 0));
  if (!sites.includes(riverSite)) riverSite = sites[0];
  segmented(document.getElementById("river-site"), sites.map((s) => ({ value: s, label: shortSite(rs.sites[s].name).replace(/ River.*/, "") + " River" })), riverSite, (v) => { riverSite = v; drawRiver(); });
  segmented(document.getElementById("river-range"), [
    { value: "all", label: "All years" }, { value: "test", label: "Test 2023+" }, { value: "year", label: String(replayYear()) },
  ], riverRange, (v) => { riverRange = v; drawRiver(); });
  const c = colors();
  document.getElementById("river-legend").innerHTML = legendHTML([
    { label: "Measured (USGS sensor)", color: c.obs },
    { label: "Model (median)", color: c.accent },
    { label: "Model 8-in-10 range", color: c.accent, kind: "band" },
    { label: "EPA limit 10 mg/L", color: c.nitrate, kind: "dash" },
  ]) + mockChip(S.source, "river_series");
  drawRiver();

  function drawRiver() {
    const s = rs.sites[riverSite];
    const dates = s.dates.map(parseDate);
    const sp = rs.split || {};
    const span = (k) => (sp[k] ? { from: parseDate(sp[k][0]), to: parseDate(sp[k][1]) } : null);
    const spans = [
      span("train") && { ...span("train"), label: "Training years", fill: "rgba(0,0,0,0)" },
      span("test") && { ...span("test"), label: "Out-of-time test", fill: "rgba(16,24,31,0.05)" },
      span("live") && { ...span("live"), label: "Live", fill: "rgba(11,95,102,0.07)" },
    ].filter(Boolean);
    const last = dates[dates.length - 1];
    let xMin = dates[0];
    if (riverRange === "test" && span("test")) xMin = span("test").from;
    if (riverRange === "year") xMin = Date.UTC(replayYear(), 0, 1);
    const xMax = riverRange === "year" ? Date.UTC(replayYear(), 11, 31) : last;
    const series = [
      { label: "Model low", data: toXY(dates, s.p10), kind: "bandLo", order: 3 },
      { label: "Model high", data: toXY(dates, s.p90), kind: "bandHi", order: 3 },
      { label: "Model", data: toXY(dates, s.p50), color: c.accent, width: 1.6, order: 1 },
      { label: "Measured", data: toXY(dates, s.obs), color: c.obs, width: 1.4, order: 0 },
    ];
    if (riverChart) riverChart.destroy();
    riverChart = timeChart(box, { series, xMin, xMax, spans, threshold: { value: rs.mcl ?? 10, label: "EPA limit 10 mg/L" } });
    const inRange = s.obs.filter((v, i) => isNum(v) && dates[i] >= xMin && dates[i] <= xMax);
    const over = inRange.filter((v) => v > (rs.mcl ?? 10)).length;
    document.getElementById("river-note").innerHTML = `${esc(s.name)}: ${fmtInt(over)} of ${fmtInt(inRange.length)} measured days in view were above 10 mg/L. Gaps are days without a sensor reading. The model sees only satellite and weather drivers, never the river itself, so the shaded test years are a fair check. ${link(nwisUrl(riverSite), "USGS data")}`;
  }
}

// ------------------------------------------------------------------ hotspot map
let cityMap, cityMetric = "share_of_basin_leak", cityPopup;
const METRICS = {
  share_of_basin_leak: { label: "Share of basin leak", fmt: (v) => pct(v, v < 0.01 ? 2 : 1) },
  leak_index: { label: "Leak intensity", fmt: (v) => fmt(v, 2) },
};

function hucFeatures() {
  return S.data.huc12?.features || [];
}

export async function initCityMap() {
  if (cityMap !== undefined) { cityMap?.resize(); return; }
  cityMap = null;
  const feats = hucFeatures();
  const container = document.getElementById("city-map");
  const bounds = bboxOf(S.data.basins?.features?.length ? S.data.basins.features : feats);
  const map = await createMap(container, { bounds, attribution: "Boundaries: USGS WBD · Rivers: USGS NHD" });
  if (!map) return;
  cityMap = map;
  const hasScores = feats.some((f) => isNum(f.properties.leak_index));
  map.addSource("huc", { type: "geojson", data: S.data.huc12, promoteId: "huc12" });
  map.addLayer({ id: "huc-fill", type: "fill", source: "huc", paint: { "fill-color": "#dddddd", "fill-opacity": 0.92 } });
  map.addLayer({ id: "huc-line", type: "line", source: "huc", paint: { "line-color": "#ffffff", "line-width": 0.5 } });
  map.addLayer({ id: "huc-hover", type: "line", source: "huc", paint: { "line-color": "#10181f", "line-width": 2.2 }, filter: ["==", ["get", "huc12"], ""] });
  map.addLayer({ id: "huc-focus", type: "line", source: "huc", paint: { "line-color": "#0b5f66", "line-width": 2, "line-dasharray": [2, 1.5] }, filter: ["==", ["get", "in_focus"], true] });
  addContext(map, S.data);
  addRivers(map, S.data.rivers);
  addSites(map, S.data.sites);
  addPlaces(map, S.data.places, { townMinZoom: 7.8 });

  segmented(document.getElementById("map-metric"), Object.entries(METRICS).map(([k, m]) => ({ value: k, label: m.label })), cityMetric, (v) => { cityMetric = v; paint(); });
  function paint() {
    const legend = document.getElementById("city-map-legend");
    if (!hasScores) {
      legend.innerHTML = `<span>Leak scores not computed yet; outlines only.</span>`;
      return;
    }
    const ramp = LEAK_RAMP();
    const vals = feats.map((f) => f.properties[cityMetric]);
    const br = quantileBreaks(vals, ramp.length);
    map.setPaintProperty("huc-fill", "fill-color", stepExpr(cityMetric, br, ramp));
    const v = vals.filter(isNum).sort((a, b) => a - b);
    legend.innerHTML = rampLegend(ramp, [`lower (${METRICS[cityMetric].fmt(v[0])})`, `higher (${METRICS[cityMetric].fmt(v[v.length - 1])})`], METRICS[cityMetric].label + " · equal-count classes") +
      `<span><span class="sw" style="display:inline-block;width:18px;border-top:2px dashed #0b5f66;vertical-align:middle;margin-right:6px"></span>Farmer focus area</span>` + mockChip(S.source, "huc12");
  }
  paint();

  map.on("mousemove", "huc-fill", (e) => {
    map.getCanvas().style.cursor = "pointer";
    const id = e.features?.[0]?.properties?.huc12;
    map.setFilter("huc-hover", ["==", ["get", "huc12"], id || ""]);
  });
  map.on("mouseleave", "huc-fill", () => { map.getCanvas().style.cursor = ""; map.setFilter("huc-hover", ["==", ["get", "huc12"], ""]); });
  map.on("click", "huc-fill", (e) => {
    const f = e.features?.[0];
    if (f) openHucPopup(f.properties, e.lngLat);
  });
}

function basinCount(basin) {
  return hucFeatures().filter((f) => f.properties.basin === basin).length;
}

function hucPopupHTML(p) {
  const row = (k, v) => `<tr><td>${k}</td><td>${v}</td></tr>`;
  const basinName = p.basin === "raccoon" ? "Raccoon" : p.basin === "desmoines" ? "Des Moines" : esc(p.basin);
  return `<h4>${esc(p.name || "Sub-watershed")}</h4><div class="fine" style="margin:0 0 4px">HUC-12 ${esc(p.huc12)} · ${basinName} basin${mockChip(S.source, "huc12")}</div>
  <table class="pop-table">
    ${row("Row-crop share", pct(Number(p.row_crop_share)))}
    ${row("Poorly drained cropland", pct(Number(p.poorly_drained_share)))}
    ${row("Bare + wet days / yr", fmtInt(Number(p.bare_days_wet)))}
    ${row("Share of basin leak", pct(Number(p.share_of_basin_leak), 1))}
    ${row("Rank in basin", isNum(Number(p.rank)) && p.rank != null ? `${fmtInt(Number(p.rank))} of ${basinCount(p.basin)}` : "–")}
  </table>`;
}

function openHucPopup(p, lngLat) {
  if (!cityMap) return;
  cityPopup?.remove();
  cityPopup = new maplibregl.Popup({ maxWidth: "280px" }).setLngLat(lngLat).setHTML(hucPopupHTML(p)).addTo(cityMap);
}

function renderHotspotList() {
  const feats = hucFeatures().filter((f) => f.properties.basin === "raccoon" && isNum(Number(f.properties.rank)) && f.properties.rank != null);
  const list = document.getElementById("hotspot-list");
  const note = document.getElementById("hotspot-note");
  document.getElementById("hotspot-basin").textContent = "· Raccoon basin";
  if (!feats.length) { list.innerHTML = "<li>Leak scores not computed yet.</li>"; return; }
  const top = feats.sort((a, b) => a.properties.rank - b.properties.rank).slice(0, 6);
  list.innerHTML = top.map((f) => `<li><button type="button" data-huc="${esc(f.properties.huc12)}">${esc(f.properties.name || f.properties.huc12)}</button><br><span class="muted">${pct(f.properties.share_of_basin_leak, 1)} of the leak · ${pct(f.properties.row_crop_share)} row crops</span></li>`).join("");
  const all = hucFeatures().filter((f) => f.properties.basin === "raccoon");
  const areaAll = all.reduce((s, f) => s + (f.properties.area_km2 || 0), 0);
  const areaTop = top.reduce((s, f) => s + (f.properties.area_km2 || 0), 0);
  const shareTop = top.reduce((s, f) => s + (f.properties.share_of_basin_leak || 0), 0);
  note.innerHTML = `These ${top.length} sub-watersheds cover ${pct(areaTop / areaAll)} of the Raccoon basin but send about <strong>${pct(shareTop)}</strong> of its nitrate leak. ${mockChip(S.source, "huc12")}`;
  list.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-huc]");
    if (!b) return;
    const f = hucFeatures().find((x) => x.properties.huc12 === b.dataset.huc);
    if (!f || !cityMap) return;
    const bb = bboxOf([f]);
    cityMap.fitBounds(bb, { padding: 60, maxZoom: 10, duration: 600 });
    openHucPopup(f.properties, [(bb[0][0] + bb[1][0]) / 2, (bb[0][1] + bb[1][1]) / 2]);
    document.getElementById("city-map").scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

// ------------------------------------------------------------------ outlook
function renderOutlook() {
  const o = S.data.outlook;
  const sub = document.getElementById("outlook-sub");
  if (!o?.dates?.length) { sub.textContent = "Outlook not available yet."; return; }
  const site = o.site || PRIMARY;
  sub.innerHTML = `${esc(siteName(site))}. Issued ${esc(o.issued || "")} from current soil wetness, recent storms and how much cropland is bare. ${mockChip(S.source, "outlook")}`;
  const c = colors();
  const fd = o.dates.map(parseDate);
  // recent measured days leading into the forecast
  const rs = S.data.river_series?.sites?.[site];
  let recent = [];
  if (rs) {
    const end = o.last_obs?.date ? parseDate(o.last_obs.date) : fd[0];
    const from = end - 30 * 86400000;
    rs.dates.forEach((d, i) => { const t = parseDate(d); if (t >= from && t <= end) recent.push({ x: t, y: isNum(rs.obs[i]) ? rs.obs[i] : null }); });
  } else if (o.last_obs) recent = [{ x: parseDate(o.last_obs.date), y: o.last_obs.value }];
  const anchor = o.last_obs && isNum(o.last_obs.value) ? [{ x: parseDate(o.last_obs.date), y: o.last_obs.value }] : [];
  const fan = (arr) => [...anchor, ...toXY(fd, arr)];
  const xMin = recent.length ? recent[0].x : fd[0];
  const xMax = fd[fd.length - 1];
  timeChart(document.getElementById("outlook-chart"), {
    xMin, xMax, threshold: { value: 10, label: "EPA limit 10 mg/L" },
    spans: [{ from: fd[0], to: xMax, label: "Outlook", fill: "rgba(11,95,102,0.06)" }],
    series: [
      { label: "Low", data: fan(o.p10), kind: "bandLo", order: 3 },
      { label: "High", data: fan(o.p90), kind: "bandHi", order: 3 },
      { label: "Outlook (median)", data: fan(o.p50), color: c.accent, width: 2, dash: [5, 3], order: 1 },
      { label: "Measured", data: recent, color: c.obs, width: 1.6, order: 0 },
    ],
  });
  document.getElementById("outlook-legend").innerHTML = legendHTML([
    { label: "Measured, last 30 days", color: c.obs },
    { label: "Outlook (median)", color: c.accent, kind: "dash" },
    { label: "8-in-10 range", color: c.accent, kind: "band" },
  ]);
  const probs = o.prob_over10 || [];
  document.getElementById("outlook-prob").innerHTML = probs.map((p, i) => {
    const cls = p >= 0.5 ? "hot" : p >= 0.2 ? "warm" : "";
    return `<div class="prob-cell ${cls}" title="${fmtDate(fd[i])}: ${Math.round(p * 100)}% chance above 10 mg/L">${isNum(p) ? Math.round(p * 100) : "–"}%</div>`;
  }).join("") + `<div class="prob-cap" style="grid-column:1/-1">Chance above 10 mg/L, each of the next 14 days</div>`;
  const maxP = Math.max(...probs.filter(isNum), 0);
  const iMax = probs.indexOf(maxP);
  const head = document.getElementById("outlook-headline");
  if (maxP >= 0.1) {
    const n10 = Math.round(maxP * 10);
    head.innerHTML = `<span class="red">${Math.round(maxP * 100)}% chance</span> the river tops the safe limit by ${fmtDate(fd[iMax], { month: "short", day: "numeric" })}: in about ${n10} of 10 similar situations it did.`;
  } else {
    head.textContent = "Low chance (under 1 in 10) of crossing the safe limit in the next two weeks.";
  }
  const dr = o.drivers || {};
  const pc = (v) => (isNum(v) ? `wetter than ${Math.round(v)}% of past years at this time` : "");
  const items = [];
  if (isNum(dr.rain_7d_mm)) items.push(`<b>Rain, last 7 days:</b> ${fmt(dr.rain_7d_mm)} mm${isNum(dr.rain_7d_pctile) ? ` — more than in ${Math.round(dr.rain_7d_pctile)}% of past years` : ""}`);
  if (isNum(dr.gwetroot)) items.push(`<b>Soil wetness (root zone):</b> ${fmt(dr.gwetroot, 2)} on a 0–1 scale${isNum(dr.gwetroot_pctile) ? ` — ${pc(dr.gwetroot_pctile)}` : ""}`);
  if (isNum(dr.bare_share)) items.push(`<b>Bare cropland:</b> ${pct(dr.bare_share)} of row-crop land has no living cover${isNum(dr.bare_share_pctile) ? ` — more than in ${Math.round(dr.bare_share_pctile)}% of past years` : ""}`);
  if (o.last_obs && isNum(o.last_obs.value)) items.push(`<b>Last measurement:</b> ${fmt(o.last_obs.value, 1)} mg/L on ${esc(o.last_obs.date)}`);
  document.getElementById("outlook-drivers").innerHTML = items.map((t) => `<li>${t}</li>`).join("");
  document.getElementById("outlook-text").textContent = o.text || "";
}
