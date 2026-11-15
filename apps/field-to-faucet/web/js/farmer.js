// Farmer view: field map, field facts, leak calendar, recent NDVI, strategy cards re-ranked by farmer priorities.
// Fields and strategies load when this view first opens; field_index.json and field_detail/<huc12>.json on click.
import { clamp, esc, fmt, fmtInt, fmtLbAc, isDarkColor, isNum, link, linkify, meanBand, MON3, MONTHS, monthRange, pct, usd, LEAK_RAMP, parseDate } from "./util.js";
import { colors, timeChart, toXY } from "./charts.js";
import { addLabel, addPlaces, bboxOf, createMap, rampLegend, stepExpr } from "./map.js";
import { ensure, factsMap, getFieldDetail, mockChip, nasaStrip } from "./data.js";

let S;
let farmMap; // undefined = not started, null = failed
let selectedId = null;
let ndviChart;
let currentDetail = null;
let leakyIdx = 0;
let geo = null; // field_id -> {lon, lat, town, km, dir}
const weights = { n: 2, yield: 2, soil: 1, cost: 1 };
const CRIT = [
  { k: "n", label: "Keep nitrogen / cut fertilizer cost", short: "Nitrogen kept" },
  { k: "yield", label: "Protect yield", short: "Yield safety" },
  { k: "soil", label: "Build soil", short: "Soil health" },
  { k: "cost", label: "Low cost & labor", short: "Low net cost" },
];
const WLABEL = ["not at all", "a little", "important", "top priority"];
const CROPS = { C: "corn", S: "soybean", W: "wheat", O: "oats/small grain", H: "hay/alfalfa", P: "pasture", R: "other row crop", X: "other" };
const DRIVER_RAMP = ["#eef4fb", "#c4dbf5", "#86b6ef", "#3f88dc", "#1c5cab", "#0d366b"];

export function initFarmer(store, onSelect) {
  S = store;
  renderPriorities();
  document.getElementById("nasa-strip-farm").innerHTML = nasaStrip(S.data.meta, { compact: true });
  const leakyBtn = document.getElementById("pick-leaky");
  // First a TYPICAL field (near the median leak), so the demo is not cherry-picked; the leaky ones come second.
  document.getElementById("pick-sample").addEventListener("click", async () => {
    await farmReady();
    const id = typicalField();
    if (!id) return;
    leakyBtn.hidden = false;
    onSelect(id);
  });
  leakyBtn.addEventListener("click", async () => {
    await farmReady();
    const ids = leakyFields();
    if (!ids.length) return;
    onSelect(ids[leakyIdx++ % ids.length]);
  });
  const form = document.getElementById("field-find");
  const q = document.getElementById("field-q");
  q.addEventListener("focus", () => { farmReady(); }, { once: true });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    await farmReady();
    const r = findField(q.value);
    if (r.id) { onSelect(r.id); if (r.note) announce(r.note); }
    else announce(r.note);
  });
}

async function farmReady() {
  await Promise.all([ensure(S, "farm"), ensure(S, "map")]);
  if (!geo) buildGeo();
}

function announce(msg) {
  const live = document.getElementById("field-live");
  live.textContent = "";
  setTimeout(() => { live.textContent = msg; }, 30);
}

// ------------------------------------------------------------------ names for humans: "Field near <town>"
const towns = () => (S.data.places || []).filter((p) => isNum(p.lon) && isNum(p.lat) && p.kind !== "intake");
function kmBetween(a, b) {
  const R = 6371, rad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * rad, dLon = (b[0] - a[0]) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function compass(from, to) {
  const dx = (to[0] - from[0]) * Math.cos(from[1] * Math.PI / 180), dy = to[1] - from[1];
  const ang = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
  return ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"][Math.round(ang / 45) % 8];
}
function buildGeo() {
  geo = new Map();
  const ts = towns();
  for (const f of fieldFeatures()) {
    const bb = bboxOf([f]);
    if (!bb) continue;
    const c = [(bb[0][0] + bb[1][0]) / 2, (bb[0][1] + bb[1][1]) / 2];
    let best = null;
    for (const t of ts) { const km = kmBetween(c, [t.lon, t.lat]); if (!best || km < best.km) best = { t, km }; }
    geo.set(f.properties.field_id, { c, town: best?.t.name || null, km: best?.km ?? null, dir: best ? compass([best.t.lon, best.t.lat], c) : "" });
  }
  // datalist for the keyboard / screen-reader field search
  const names = [...new Set([...geo.values()].map((g) => g.town).filter(Boolean))].sort();
  const opts = names.map((n) => `<option value="${esc(n)}"></option>`).concat(fieldFeatures().map((f) => `<option value="${esc(f.properties.field_id)} near ${esc(geo.get(f.properties.field_id)?.town || "")}"></option>`));
  document.getElementById("field-list").innerHTML = opts.join("");
}
export function fieldName(id) {
  const g = geo?.get(id);
  return g?.town ? `Field near ${g.town}` : `Field ${id}`;
}
function whereText(id) {
  const g = geo?.get(id);
  if (!g?.town || !isNum(g.km)) return "";
  return g.km < 1.5 ? `at ${g.town}` : `${fmtInt(g.km)} km ${g.dir} of ${g.town}`;
}
// "F01587", "F01587 near Jefferson" or a town name (nearest field to the town)
function findField(raw) {
  const v = String(raw || "").trim();
  if (!v) return { note: "Type a town name or a field ID such as F01587." };
  const m = /\bF\d{3,}\b/i.exec(v);
  if (m) {
    const id = m[0].toUpperCase();
    return fieldFeatures().some((f) => f.properties.field_id === id) ? { id } : { note: `Field ${id} not found in the focus area.` };
  }
  const t = towns().find((p) => p.name.toLowerCase() === v.toLowerCase()) || towns().find((p) => p.name.toLowerCase().startsWith(v.toLowerCase()));
  if (!t) return { note: `No town or field matches “${v}”.` };
  let best = null;
  for (const [id, g] of geo) { const km = kmBetween(g.c, [t.lon, t.lat]); if (!best || km < best.km) best = { id, km }; }
  return best ? { id: best.id, note: `Nearest field to ${t.name}: ${best.id}, ${fmtInt(best.km)} km away.` } : { note: "No fields loaded." };
}

export function showFieldNotFound(id) {
  document.getElementById("field-content").hidden = true;
  document.getElementById("field-empty").hidden = false;
  document.getElementById("field-empty-msg").innerHTML = `<strong>Field “${esc(id)}” not found.</strong> Tap a square on the map, search by town or ID, or use <em>pick a sample field</em>.`;
  announce(`Field ${id} not found.`);
}

function renderDisclaimer() {
  document.getElementById("strategy-disclaimer").innerHTML = `<strong>${esc(S.data.strategies?.disclaimer || "Decision support, not a replacement for your agronomist.")}</strong> ${mockChip(S.source, "strategies")}`;
}

function fieldFeatures() {
  return S.data.fields?.features || [];
}

// A typical field: closest to the median modelled leak (ties: closest to the 50th percentile, then by id).
function typicalField() {
  const f = fieldFeatures().map((x) => x.properties).filter((p) => isNum(p.lbN_ac_yr_mean ?? p.leak_index));
  if (!f.length) return null;
  const v = (p) => p.lbN_ac_yr_mean ?? p.leak_index;
  const sorted = f.map(v).sort((a, b) => a - b);
  const med = sorted[Math.floor(sorted.length / 2)];
  f.sort((a, b) => Math.abs(v(a) - med) - Math.abs(v(b) - med) || Math.abs((a.leak_pctile ?? 50) - 50) - Math.abs((b.leak_pctile ?? 50) - 50) || a.field_id.localeCompare(b.field_id));
  return f[0].field_id;
}
// High-leak, poorly drained fields: offered second ("show a leaky field").
function leakyFields() {
  const f = fieldFeatures().map((x) => x.properties).filter((p) => isNum(p.leak_pctile));
  const pd = f.filter((p) => /poor/i.test(p.drainage || "") && !/somewhat/i.test(p.drainage || ""));
  const pool = (pd.length >= 5 ? pd : f).sort((a, b) => b.leak_pctile - a.leak_pctile);
  const top = pool.slice(0, Math.max(5, Math.floor(pool.length * 0.1)));
  const out = [];
  for (let i = 0; i < 5 && top.length; i++) out.push(top[Math.floor((i / 5) * top.length)].field_id);
  return out;
}

export async function initFarmMap(onSelect) {
  if (farmMap !== undefined) { farmMap?.resize(); return; }
  farmMap = null;
  const container = document.getElementById("farm-map");
  await farmReady();
  renderDisclaimer();
  const feats = fieldFeatures();
  if (!feats.length) { container.innerHTML = `<div class="map-msg">Field data is not available yet.</div>`; return; }
  const map = await createMap(container, { bounds: bboxOf(feats), attribution: "Fields: 400 m grid from USDA CDL · Cover: NASA HLS" });
  if (!map) return;
  farmMap = map;
  const focusHuc = new Set(feats.map((f) => f.properties.huc12));
  const hucs = (S.data.huc12?.features || []).filter((f) => focusHuc.has(f.properties.huc12));
  if (hucs.length) {
    map.addSource("fhuc", { type: "geojson", data: { type: "FeatureCollection", features: hucs } });
    map.addLayer({ id: "fhuc-fill", type: "fill", source: "fhuc", paint: { "fill-color": "#ffffff", "fill-opacity": 0.55 } });
    map.addLayer({ id: "fhuc-line", type: "line", source: "fhuc", paint: { "line-color": "#5f6b76", "line-width": 1, "line-dasharray": [3, 2] } });
  }
  const ramp = LEAK_RAMP().slice(1);
  map.addSource("fields", { type: "geojson", data: S.data.fields });
  map.addLayer({ id: "fields-fill", type: "fill", source: "fields", paint: { "fill-color": stepExpr("leak_pctile", [20, 40, 60, 80], ramp), "fill-opacity": 0.95 } });
  map.addLayer({ id: "fields-line", type: "line", source: "fields", minzoom: 11.5, paint: { "line-color": "#ffffff", "line-width": 0.6 } });
  map.addLayer({ id: "fields-sel", type: "line", source: "fields", paint: { "line-color": "#0b5f66", "line-width": 3.5 }, filter: ["==", ["get", "field_id"], ""] });
  for (const h of hucs) {
    const bb = bboxOf([h]);
    if (h.properties.name) addLabel(map, [(bb[0][0] + bb[1][0]) / 2, (bb[0][1] + bb[1][1]) / 2], h.properties.name, "huc");
  }
  const fb = bboxOf(feats);
  addPlaces(map, (S.data.places || []).filter((p) => isNum(p.lon) && p.lon > fb[0][0] - 0.1 && p.lon < fb[1][0] + 0.1 && p.lat > fb[0][1] - 0.1 && p.lat < fb[1][1] + 0.1));
  document.getElementById("farm-map-legend").innerHTML = rampLegend(ramp, ["lowest leak", "highest leak"], "Field nitrate leak (long-run average), percentile in this area · fifths") + mockChip(S.source, "fields");
  map.on("mousemove", "fields-fill", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "fields-fill", () => { map.getCanvas().style.cursor = ""; });
  map.on("click", "fields-fill", (e) => {
    const id = e.features?.[0]?.properties?.field_id;
    if (id) onSelect(id);
  });
  if (selectedId) highlight(selectedId, true);
}

function highlight(id, fly) {
  if (!farmMap) return;
  farmMap.setFilter("fields-sel", ["==", ["get", "field_id"], id]);
  if (fly) {
    const f = fieldFeatures().find((x) => x.properties.field_id === id);
    if (f) {
      const bb = bboxOf([f]);
      farmMap.easeTo({ center: [(bb[0][0] + bb[1][0]) / 2, (bb[0][1] + bb[1][1]) / 2], zoom: Math.max(farmMap.getZoom(), 12.5), duration: 600 });
    }
  }
}

export async function selectField(id, { fly = true } = {}) {
  await farmReady();
  renderDisclaimer();
  const f = fieldFeatures().find((x) => x.properties.field_id === id);
  if (!f) return false;
  selectedId = id;
  highlight(id, fly);
  const p = f.properties;
  let detail = await getFieldDetail(S, id, p.huc12);
  if (selectedId !== id) return true; // a newer click won
  const missing = detail?._missing || (!detail ? "no detail record" : null);
  if (detail?._missing) detail = null;
  currentDetail = { props: p, detail, missing };
  document.getElementById("field-empty").hidden = true;
  document.getElementById("field-content").hidden = false;
  renderFieldHead(p, detail, missing);
  renderCalendar(detail);
  renderNdvi(detail);
  renderCards();
  const leak = meanBand(detail?.leak?.lbN_ac_yr)?.mid ?? p.lbN_ac_yr_mean;
  announce(`Selected ${fieldName(id)} (${id}). Modelled leak about ${fmtLbAc(leak)} pounds of nitrogen per acre a year.${missing ? " Some details for this field could not be loaded." : ""}`);
  return true;
}

// ------------------------------------------------------------------ field facts
function hucName(h) {
  return (S.data.huc12?.features || []).find((f) => f.properties.huc12 === h)?.properties?.name;
}
function renderFieldHead(p, d, missing) {
  const leak = meanBand(d?.leak?.lbN_ac_yr) || (isNum(p.lbN_ac_yr_mean) ? { mid: p.lbN_ac_yr_mean, lo: p.lbN_ac_yr_mean, hi: p.lbN_ac_yr_mean } : null);
  const wet = d?.leak?.wet_year_2016;
  const seq = String(d?.seq || p.seq || "");
  const firstYear = 2025 - seq.length + 1;
  const seqHTML = seq ? `<span class="seq" aria-label="Crop sequence">${[...seq].map((ch, i) => `<span class="${esc(ch)}" title="${firstYear + i}: ${esc(CROPS[ch] || ch)}">${esc(ch)}</span>`).join("")}</span>` : "–";
  const letters = [...new Set(seq)].map((ch) => `${ch} = ${CROPS[ch] || ch}`).join(", ");
  const pctile = isNum(p.leak_pctile) ? p.leak_pctile : null;
  const byYear = d?.leak?.by_year || {};
  const yrs = Object.keys(byYear).sort();
  document.getElementById("field-head").innerHTML = `
    <h2>${esc(fieldName(p.field_id))} <span class="muted field-id">(${esc(p.field_id)})</span> ${mockChip(S.source, "fields", "field_detail")}</h2>
    ${missing ? `<p class="wet" role="status"><strong>Some details for this field could not be loaded</strong> (${esc(missing)}). The map values below are shown; the calendar and per-option numbers are not.</p>` : ""}
    <p class="sub" style="margin:0;color:var(--muted)">About 40 acres${whereText(p.field_id) ? `, ${esc(whereText(p.field_id))}` : ""}, in ${esc(hucName(p.huc12) || "HUC-12 " + p.huc12)}${pctile != null ? ` · ${pctile >= 99 ? `among the <strong style="color:var(--ink)">top 1%</strong> of fields nearby for nitrate leak` : `leaks more nitrate than <strong style="color:var(--ink)">${fmtInt(pctile)}%</strong> of fields nearby`}` : ""}</p>
    <div class="facts">
      <div class="fact fact-wide"><div class="fact-v big">${leak ? fmtLbAc(leak.mid) : "–"} <span class="unit">lb N/acre/yr</span></div><div class="fact-l"><strong>modelled leak (estimate, not measured)</strong>: nitrate-N reaching the river, long-run average ${yrs.length ? `${yrs[0]}–${yrs[yrs.length - 1]}` : ""}${leak && leak.hi > leak.lo ? `<br><strong>${fmtLbAc(leak.lo)}–${fmtLbAc(leak.hi)} lb in 8 of 10 years</strong> (dry years deliver little to the river that year; nitrate can leave later)` : ""}</div></div>
      <div class="fact"><div class="fact-v">${esc(d?.drainage || p.drainage || "–")}</div><div class="fact-l">soil drainage (USDA SSURGO)</div></div>
      <div class="fact"><div class="fact-v">${isNum(d?.slope_pct ?? p.slope_pct) ? fmt(d?.slope_pct ?? p.slope_pct, 1) + "%" : "–"}</div><div class="fact-l">average slope (NASADEM)</div></div>
      <div class="fact"><div class="fact-v">${esc(d?.crop_2025 || CROPS[seq.slice(-1)] || "–")}</div><div class="fact-l">crop in 2025 (USDA CDL)</div></div>
    </div>
    ${isNum(wet) ? `<p class="wet"><strong>In a wet year like 2016:</strong> this field lost about <strong>${fmtLbAc(wet)} lb N/acre</strong>${leak ? `, ${leak.mid > 0 ? `${fmt(wet / leak.mid, 1)}× its average` : ""}` : ""}. That is the year a living cover pays off most (see the options below).</p>` : ""}
    ${d?.why_field ? `<p class="fine">${esc(d.why_field)}</p>` : ""}
    <p class="fine">Crops ${firstYear}–2025: ${seqHTML} <span class="muted">${esc(letters)}</span>${coverYearsText(d)}</p>`;
}
function coverYearsText(d) {
  const cy = d?.cover_years;
  if (!cy) return "";
  const yrs = Object.entries(cy).filter(([, v]) => v).map(([y]) => y);
  const n = Object.keys(cy).length;
  return yrs.length ? `<br>Winter living cover seen by NASA HLS in ${yrs.length} of ${n} winters (${yrs.join(", ")}).` : `<br>No winter living cover seen by NASA HLS in ${n} winters.`;
}

// ------------------------------------------------------------------ leak calendar
function riskWindow(risk) {
  let best = 0, bi = 0;
  for (let a = 0; a <= 9; a++) {
    const s = (risk[a] || 0) + (risk[a + 1] || 0) + (risk[a + 2] || 0);
    if (s > best) { best = s; bi = a; }
  }
  return [bi, bi + 2];
}
function renderCalendar(d) {
  const cal = d?.calendar;
  const box = document.getElementById("calendar");
  const explain = document.getElementById("cal-explain");
  if (!cal?.leak_risk?.length) {
    box.innerHTML = "";
    explain.textContent = "The leak calendar for this field has not been exported yet.";
    document.getElementById("cal-note").textContent = "";
    return;
  }
  const order = (cal.months || [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]).map((m) => m - 1);
  const get = (k) => order.map((_, i) => cal[k]?.[i]);
  const interp = get("interp_only").map((v) => v === true);
  const rows = [
    { k: "bare_frac", label: "Bare ground (HLS)", f: (v) => Math.round(v * 100), norm: (v) => v, ramp: DRIVER_RAMP, title: (v, i) => `${Math.round(v * 100)}% bare${interp[i] ? " (no clear satellite view: filled between clear views)" : ""}`, sat: true },
    { k: "rain_mm", label: "Rain, mm", f: (v) => Math.round(v), ramp: DRIVER_RAMP, title: (v) => `${Math.round(v)} mm rain (NASA POWER)` },
    { k: "storm_days", label: "Big-storm days", f: (v) => (v >= 10 ? Math.round(v) : fmt(v, 1)), ramp: DRIVER_RAMP, title: (v) => `${fmt(v, 1)} days with 25 mm+ rain` },
    { k: "wetness", label: "Soil wetness", f: (v) => Math.round(v * 100), ramp: DRIVER_RAMP, minmax: true, title: (v) => `root-zone soil wetness ${fmt(v, 2)} (0–1, NASA POWER GWETROOT)` },
    { k: "leak_risk", label: "Leak risk", f: (v) => Math.round(v * 100), ramp: LEAK_RAMP(), cls: "cal-row-risk", title: (v) => `leak risk ${Math.round(v * 100)} of 100 (riskiest month = 100)` },
    { k: "leak_lb_ac", label: "Leak, lb N/acre", f: (v) => (v >= 10 ? Math.round(v) : v >= 0.05 ? fmt(v, 1) : "0"), ramp: LEAK_RAMP(), cls: "cal-row-risk", title: (v) => `about ${fmt(v, 2)} lb N/acre lost in this month (long-run average)` },
  ];
  const risk = get("leak_risk");
  const [w0, w1] = riskWindow(risk);
  let html = `<div class="cal-h cal-h-blank"></div>` + order.map((m, i) => `<div class="cal-h${interp[i] ? " interp" : ""}" title="${MON3[m]}${interp[i] ? ": no clear satellite view in most years" : ""}">${MONTHS[m]}</div>`).join("");
  for (const r of rows) {
    const vals = get(r.k);
    const nums = vals.filter(isNum);
    if (!nums.length) continue;
    const mx = Math.max(...nums), mn = Math.min(...nums);
    const norm = r.norm || (r.minmax ? (v) => (mx > mn ? (v - mn) / (mx - mn) : 0.5) : (v) => (mx > 0 ? v / mx : 0));
    html += `<div class="cal-l ${r.cls || ""}">${esc(r.label)}</div>`;
    html += vals.map((v, i) => {
      if (!isNum(v)) return `<div class="cal-c" title="no data">·</div>`;
      const c = r.ramp[clamp(Math.round(norm(v) * (r.ramp.length - 1)), 0, r.ramp.length - 1)];
      const win = (r.k === "leak_risk" || r.k === "leak_lb_ac") && i >= w0 && i <= w1 ? " win" : "";
      const grey = interp[i] && r.sat ? " interp" : "";
      return `<div class="cal-c${isDarkColor(c) && !grey ? " dark" : ""}${win}${grey}" style="${grey ? "" : `background:${c}`}" title="${MON3[order[i]]}: ${esc(r.title(v, i))}">${r.f(v)}</div>`;
    }).join("");
  }
  box.innerHTML = html;
  // one plain sentence
  const bare = get("bare_frac"), storms = get("storm_days"), wet = get("wetness"), rain = get("rain_mm"), lb = get("leak_lb_ac");
  const sum = (a, i0 = 0, i1 = 11) => a.slice(i0, i1 + 1).reduce((s, v) => s + (isNum(v) ? v : 0), 0);
  const bareAvg = sum(bare, w0, w1) / 3;
  const stormTot = sum(storms);
  const share = stormTot > 0 ? sum(storms, w0, w1) / stormTot : (sum(rain) > 0 ? sum(rain, w0, w1) / sum(rain) : null);
  const what = stormTot > 0 ? "big storms" : "rain";
  const wetMax = wet.indexOf(Math.max(...wet.filter(isNum)));
  const wetTxt = wetMax >= w0 && wetMax <= w1 ? " and the soil was at its wettest" : "";
  const months = monthRange(order[w0], order[w1]);
  const lbWin = sum(lb, w0, w1), lbTot = sum(lb);
  const lbTxt = lbTot > 0 ? ` About <strong>${pct(lbWin / lbTot)}</strong> of its yearly loss happens then.` : "";
  if (bareAvg >= 0.4) {
    explain.innerHTML = `Your field sat bare (${pct(bareAvg)} of the time) in <strong>${months}</strong>, when ${share != null ? `<strong>${pct(share)}</strong> of the year's ${what} hit` : "storms hit"}${wetTxt}: that is when nitrate washes out to the river.${lbTxt}`;
  } else {
    explain.innerHTML = `Your field had living cover most of ${months} (bare only ${pct(bareAvg)} of the time), the months when ${share != null ? `${pct(share)} of the year's ${what} hit` : "storms hit"}. Living roots hold nitrate in place.${lbTxt}`;
  }
  const anyInterp = interp.some(Boolean);
  document.getElementById("cal-note").innerHTML = `Typical year 2020–25. Each row is shaded within itself (darker = more). Data: bare ground from NASA HLS (Landsat + Sentinel-2) for this field; rain, storms and root-zone soil wetness from NASA POWER; leak = bare × wet-soil drainage × soil drainage, calibrated to USGS river loads. Outlined: the riskiest three months.${anyInterp ? ` <span class="interp-key"></span> Greyed months: no clear satellite view in most years (clouds or snow), so bare ground is filled in between clear views.` : ""} ${mockChip(S.source, "field_detail")}`;
}

// ------------------------------------------------------------------ NDVI
function renderNdvi(d) {
  const nd = d?.ndvi_recent;
  const note = document.getElementById("ndvi-note");
  if (ndviChart) { ndviChart.destroy(); ndviChart = null; }
  if (!nd?.dates?.length) { note.textContent = "No recent satellite greenness for this field."; return; }
  const c = colors();
  const xs = nd.dates.map(parseDate);
  ndviChart = timeChart(document.getElementById("ndvi-chart"), {
    xMin: xs[0], xMax: xs[xs.length - 1], yMax: 1, yHardMax: 1, yLabel: "NDVI", unit: "", digits: 2,
    threshold: { value: 0.3, label: "living cover above 0.30", color: c.accent, align: "left" },
    series: [{ label: "NDVI", data: toXY(xs, nd.ndvi), color: c.ink2, width: 1.4, kind: "points" }],
  });
  if (ndviChart) { ndviChart.data.datasets[0].showLine = true; ndviChart.update("none"); }
  note.innerHTML = `Data: clear-sky NASA HLS (Landsat + Sentinel-2) observations of this field, ${esc(nd.dates[0])} to ${esc(nd.dates[nd.dates.length - 1])}. Below the line the ground is bare or covered only by dead residue. ${mockChip(S.source, "field_detail")}`;
}

// ------------------------------------------------------------------ priorities + cards
function renderPriorities() {
  const box = document.getElementById("prio-sliders");
  box.innerHTML = CRIT.map((c) => `<div class="prio"><label for="w-${c.k}"><span>${esc(c.label)}</span><output id="o-${c.k}" for="w-${c.k}">${WLABEL[weights[c.k]]}</output></label><input type="range" id="w-${c.k}" min="0" max="3" step="1" value="${weights[c.k]}" aria-valuetext="${WLABEL[weights[c.k]]}"></div>`).join("");
  box.addEventListener("input", (e) => {
    const k = e.target.id?.replace("w-", "");
    if (!(k in weights)) return;
    weights[k] = Number(e.target.value);
    document.getElementById("o-" + k).textContent = WLABEL[weights[k]];
    e.target.setAttribute("aria-valuetext", WLABEL[weights[k]]);
    renderCards();
  });
}

const YIELD_SCORE = { low: 1, "low-moderate": 0.75, moderate: 0.5, medium: 0.5, "moderate-high": 0.25, high: 0 };
function yieldLevel(yr) {
  const raw = typeof yr === "string" ? yr : yr?.level || "";
  const m = /^(low|moderate|medium|high)/i.exec(String(raw).trim());
  return m ? m[1].toLowerCase() : null;
}
function yieldText(yr) {
  if (!yr) return "";
  if (typeof yr === "string") return yr.replace(/^(low|moderate|medium|high)\s*[:\-–—.]?\s*/i, "");
  return yr.text || "";
}

// Cost in $/acre/yr: null when either end is unknown (never treated as $0).
function costBand(c) {
  if (!c || !isNum(c.lo) || !isNum(c.hi)) return null;
  return { mid: (c.lo + c.hi) / 2, lo: c.lo, hi: c.hi };
}

// Cost-share $/acre for a strategy: facts.json entries whose URL is one of the strategy's "who pays" programs and
// whose id names a cost-share payment (insurance discounts etc. are not cost-share).
function costShare(s) {
  const F = factsMap(S.data.facts);
  const progs = (s.who_pays || []).filter((w) => w?.url);
  const items = [];
  for (const w of progs) {
    const f = Object.entries(F).find(([id, x]) => x && x.url === w.url && isNum(x.value) && /cost_?share|eqip/i.test(id) && /usd/i.test(x.unit || ""));
    if (f && !items.some((i) => i.url === f[1].url)) {
      const x = f[1];
      // range.lo = lower rate (e.g. IDALS returning users $20); third-party = figure not read on the agency's own page
      const lo = isNum(x.range?.lo) && x.range.lo <= x.value ? x.range.lo : x.value;
      const third = /third/i.test(`${x.source_kind || ""} ${x.source || ""}`);
      const name = shortProgram(w.program);
      items.push({ name, id: x.alias_of || x.id || f[0], url: x.url, lo, hi: x.value, value: x.value, verified: x.verified !== false, third, federal: name === "EQIP" });
    }
  }
  if (!items.length) return progs.length ? { listed: true } : null;
  const state = items.filter((i) => !i.federal);
  const agency = items.filter((i) => !i.third && i.verified);
  return {
    lo: Math.min(...items.map((i) => i.lo)), hi: Math.max(...items.map((i) => i.hi)), items,
    state: state.length ? { lo: Math.min(...state.map((i) => i.lo)), hi: Math.max(...state.map((i) => i.hi)) } : null,
    agencyHi: agency.length ? Math.max(...agency.map((i) => i.hi)) : null,
  };
}
function shortProgram(p) {
  const t = String(p || "program").replace(/\s*\(.*$/, "");
  return /EQIP/.test(t) ? "EQIP" : /IDALS/.test(t) ? "IDALS" : /Greater Des Moines/i.test(t) ? "Greater Des Moines Watershed" : t;
}
const usd0 = (v) => usd(v, { compact: false });
const usdRng = (lo, hi) => (Math.round(lo) === Math.round(hi) ? usd0(lo) : `${usd0(lo)}–${usd0(hi)}`);

function strategyMetrics(s, d) {
  const sd = d?.strategies?.[s.id] || {};
  const leak = meanBand(d?.leak?.lbN_ac_yr);
  let kept = meanBand(sd.lbN_kept_ac);
  if (!kept && leak && s.n_loss_reduction) {
    const nr = s.n_loss_reduction;
    if (isNum(nr.mean)) kept = { mid: leak.mid * nr.mean, lo: leak.lo * (nr.lo ?? nr.mean), hi: leak.hi * (nr.hi ?? nr.mean), derived: true };
  }
  const fert = meanBand(sd.fert_value_usd_ac);
  const wet = meanBand(sd.wet_year_2016?.lbN_kept_ac);
  const cost = costBand(s.cost_usd_ac);
  const yl = yieldLevel(s.yield_risk);
  const soil = isNum(s.soil_score) ? s.soil_score : Array.isArray(s.soil_health) ? s.soil_health.length : null;
  return {
    kept, fert, cost, yl, wet, note: sd.note, share: costShare(s),
    raw: {
      n: kept ? kept.mid : null,
      yield: yl ? YIELD_SCORE[yl] : null,
      soil,
      cost: cost ? -(cost.mid - (fert ? fert.mid : 0)) : null, // unknown cost -> unknown (excluded), not $0
    },
  };
}

// Min-max scale each goal over the options whose input is KNOWN; unknown inputs are left out of the score.
// Score is null ("not scored") when none of the weighted goals is known for an option, or all weights are 0.
function rank(strats, d) {
  const ms = strats.map((s) => ({ s, m: strategyMetrics(s, d) }));
  const norm = {};
  for (const c of CRIT) {
    const v = ms.map((x) => x.m.raw[c.k]).filter(isNum);
    const mn = Math.min(...v), mx = Math.max(...v);
    norm[c.k] = (val) => (!isNum(val) ? null : mx > mn ? (val - mn) / (mx - mn) : 1);
  }
  for (const x of ms) {
    x.n = Object.fromEntries(CRIT.map((c) => [c.k, norm[c.k](x.m.raw[c.k])]));
    const known = CRIT.filter((c) => x.n[c.k] != null);
    const wsum = known.reduce((s, c) => s + weights[c.k], 0);
    x.score = wsum > 0 ? known.reduce((s, c) => s + weights[c.k] * x.n[c.k], 0) / wsum : null;
    x.unknown = CRIT.filter((c) => x.n[c.k] == null).map((c) => c.short.toLowerCase());
  }
  const sc = (x) => (x.score == null ? -1 : x.score);
  return ms.sort((a, b) => sc(b) - sc(a) || a.s.id.localeCompare(b.s.id));
}
const scoreTxt = (x) => (x.score == null ? "not scored" : `${Math.round(x.score * 100)}/100`);

function soilShort(s) {
  const l = Array.isArray(s.soil_health) ? s.soil_health : [];
  if (!l.length) return "–";
  const first = String(l[0]).split(/[:(]/)[0].replace(/\s+(about|by)\s+.*$/i, "").trim().replace(/\.$/, "");
  return `${esc(first)}${l.length > 1 ? ` <span class="muted">+${l.length - 1} more</span>` : ""}`;
}

function compareTable(ranked) {
  const rows = ranked.map((x) => {
    const { s, m } = x;
    const cur = s.id === "S0";
    const kept = cur ? "0 (reference)" : m.kept ? `<strong>${fmtLbAc(m.kept.mid)}</strong>` : "–";
    const cost = m.cost ? (m.cost.hi === 0 ? "$0" : usdRng(m.cost.lo, m.cost.hi)) : `<span class="unknown">not verified</span>`;
    const share = m.share?.items ? usdRng(m.share.lo, m.share.hi) : m.share?.listed ? `<span class="muted">program listed, rate not verified</span>` : "–";
    const yl = m.yl ? `<span class="risk ${m.yl === "moderate" ? "medium" : m.yl}">${esc(m.yl)}</span>` : "–";
    return `<tr${x === ranked[0] && x.score != null ? ' class="best"' : ""}><td><span class="cmp-rank">#${ranked.indexOf(x) + 1}</span> ${esc(s.name)}</td><td class="num">${kept}</td><td class="num">${cost}</td><td class="num">${share}</td><td>${yl}</td><td>${cur ? "–" : soilShort(s)}</td></tr>`;
  }).join("");
  return `<div class="tbl-wrap cmp"><table class="data"><caption class="sr-only">Rotation options compared for this field</caption>
    <thead><tr><th scope="col">Option (ranked for you)</th><th scope="col" class="num">N kept, lb/acre/yr <span class="th-sub">long-run mean</span></th><th scope="col" class="num">Cost, $/acre/yr</th><th scope="col" class="num">Cost-share, $/acre</th><th scope="col">Yield risk</th><th scope="col">Soil benefit</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <p class="fine">N kept: this field's modelled long-run average (estimate). Cost-share: programs listed on each card (sources there); per planted acre, confirm rates and eligibility locally.</p>`;
}

function renderCards() {
  if (!currentDetail) return;
  const strats = S.data.strategies?.strategies || [];
  const box = document.getElementById("strategy-cards");
  const cmp = document.getElementById("strategy-compare");
  if (!strats.length) { box.innerHTML = `<p>Strategy evidence is not available yet.</p>`; cmp.innerHTML = ""; return; }
  const d = currentDetail.detail;
  const ranked = rank(strats, d);
  const axisMax = Math.max(1, ...ranked.map((x) => x.m.kept?.hi || 0));
  const wsum = CRIT.reduce((s, c) => s + weights[c.k], 0);
  document.getElementById("cards-sub").innerHTML = (wsum === 0
    ? `<strong class="prompt">All goals are set to “not at all”: move a slider under “What matters to you?” to rank the options.</strong> `
    : `Ranked for your priorities (top card outlined). `) +
    `The big number is the long-run average lb N/acre a year this practice keeps in your field; the bar shows the range in 8 of 10 years. Where leak happens comes from NASA satellites and weather; how much each practice cuts comes from Iowa field trials. ${mockChip(S.source, "strategies", "field_detail")}`;
  cmp.innerHTML = compareTable(ranked);
  box.innerHTML = ranked.map((x, i) => cardHTML(x, i, axisMax)).join("");
  document.getElementById("how-rank").innerHTML = `
    <p class="fine">Each goal is scored 0–1 across the options whose input is known (best = 1, worst = 0), then weighted by your sliders (0–3). Unknown inputs are left out of that option's score instead of counting as zero cost.</p>
    <div class="formula">score = Σ known (weight × goal score) ÷ Σ known weights<br>weights: ${CRIT.map((c) => `${c.short.toLowerCase()} ${weights[c.k]}`).join(", ")} (Σ = ${wsum})</div>
    <p class="fine">Goal inputs: nitrogen kept = this field's long-run average lb N/acre; yield safety = trial-based yield risk (low 1, moderate 0.5, high 0); soil health = number of evidence-backed soil benefits; low net cost = −(cost − fertilizer value), $/acre.</p>
    <table><thead><tr><th>Option</th>${CRIT.map((c) => `<th>${esc(c.short)}</th>`).join("")}<th>Score</th></tr></thead>
    <tbody>${ranked.map((x) => `<tr><td>${esc(x.s.id)}</td>${CRIT.map((c) => `<td>${x.n[c.k] == null ? `<span title="unknown: left out">n/a</span>` : fmt(x.n[c.k], 2)}</td>`).join("")}<td><strong>${x.score == null ? "not scored" : Math.round(x.score * 100)}</strong></td></tr>`).join("")}</tbody></table>`;
}

function list(items, fn = (t) => esc(t)) {
  if (!Array.isArray(items) || !items.length) return "<p class=\"muted\">None listed.</p>";
  return `<ul>${items.map((t) => `<li>${fn(t)}</li>`).join("")}</ul>`;
}
const fold = (title, body) => `<details class="card-sec card-more"><summary>${title}</summary>${body}</details>`;

// "Costs $12–$28/acre a year ($24–$55 each time it is planted); cost-share of $20–$74/acre (state $20–$30; EQIP ~$74,
// third-party figure) can cover much of it." The verdict uses only rates read on the agencies' own pages.
function moneyLine(s, m) {
  const c = s.cost_usd_ac;
  if (!m.cost || !m.share?.items || m.cost.hi === 0) return "";
  const pp = c?.per_planting && isNum(c.per_planting.lo) && isNum(c.per_planting.hi) ? c.per_planting : null;
  const need = pp ? pp.hi : m.cost.hi, needLo = pp ? pp.lo : m.cost.lo;
  const hi = isNum(m.share.agencyHi) ? m.share.agencyHi : m.share.hi;
  const verdict = hi >= need ? "can cover it" : hi >= needLo ? "can cover much of it" : "covers part of it";
  const fed = m.share.items.filter((i) => i.federal);
  const parts = [
    m.share.state ? `state ${usdRng(m.share.state.lo, m.share.state.hi)}` : "",
    ...fed.map((i) => `${esc(i.name)} ~${usd0(i.value)}${i.third ? ", third-party figure" : i.verified ? "" : ", unverified"}`),
  ].filter(Boolean);
  const srcs = m.share.items.map((i) => `${link(i.url, `${i.name} ${usdRng(i.lo, i.hi)}`)} <span class="muted">(fact ${esc(i.id)}${i.third ? "; third-party guide, agency page not opened" : i.verified ? "" : "; unverified"})</span>`).join(", ");
  return `<p class="money">Costs <strong>${usdRng(m.cost.lo, m.cost.hi)}/acre</strong> a year${pp ? ` (${usdRng(pp.lo, pp.hi)} each time it is planted)` : ""}; cost-share of <strong>${usdRng(m.share.lo, m.share.hi)}/acre</strong>${parts.length > 1 ? ` (${parts.join("; ")})` : ""} ${verdict}.
    <span class="money-src">Cost: ${link(c.url, c.source ? String(c.source).replace(/\s*\(.*$/, "") : "source")}. Cost-share: ${srcs}.</span></p>`;
}

// INRS 2024 update (Table 1): rye cuts the flow-weighted nitrate CONCENTRATION in tile drainage by 28% (SD 26) as a
// corn-soy rotation average and by 30% (SD 27) in the soybean year (facts inrs_cover_rye_pct.inrs_2024_update,
// inrs_rye_soy_year_pct/_sd). Not a cut in load or in nitrogen lost per acre.
const rye = (s) => /rye/i.test(`${s.id === "S1" ? "rye" : ""} ${s.name || ""}`);
function ryeTrialText(nr) {
  const F = factsMap(S.data.facts);
  const up = F.inrs_cover_rye_pct?.inrs_2024_update;
  const soy = F.inrs_rye_soy_year_pct, soySd = F.inrs_rye_soy_year_sd;
  const avg = isNum(up?.value) ? `${up.value}%${isNum(up.sd) ? ` (SD ${up.sd})` : ""}` : pct(nr.mean);
  return `Trials (INRS 2024 update): rye cuts the nitrate concentration in tile-drainage water by <strong>${avg}</strong> averaged across the corn-soy rotation${isNum(soy?.value) ? `, and by <strong>${soy.value}%</strong>${isNum(soySd?.value) ? ` (SD ${soySd.value})` : ""} in the soybean year` : ""}`;
}

function cardHTML(x, i, axisMax) {
  const { s, m } = x;
  const isCurrent = s.id === "S0";
  const kept = m.kept;
  const pos = (v) => `${clamp((v / axisMax) * 100, 0, 100)}%`;
  const bar = kept && kept.hi > 0 ? `<div class="ibar" aria-hidden="true"><div class="axis"></div><div class="rng" style="left:${pos(kept.lo)};width:calc(${pos(kept.hi)} - ${pos(kept.lo)})"></div><div class="mid" style="left:calc(${pos(kept.mid)} - 1px)"></div></div>` : "";
  const nr = s.n_loss_reduction;
  const trialUrl = (s.evidence || []).find((e) => e && e.url && /INRS|nutrientstrategy/i.test(`${e.source} ${e.url}`))?.url;
  const trial = nr && isNum(nr.mean) && nr.mean !== 0 ? `<p>${rye(s) ? ryeTrialText(nr) : `Trials: cuts the nitrate concentration in drainage water by about <strong>${pct(nr.mean)}</strong>`}${isNum(nr.lo) && isNum(nr.hi) ? ` (our 8-in-10 range: ${pct(nr.lo)}–${pct(nr.hi)})` : ""}${nr.source ? ` · <span title="${esc(nr.source)}">${trialUrl ? link(trialUrl, "INRS 2024") : esc(nr.source)}</span>` : ""}</p>` : "";
  const yl = m.yl;
  const c = s.cost_usd_ac;
  const costTxt = m.cost
    ? `${usdRng(m.cost.lo, m.cost.hi)}/acre/yr${c?.url && !isCurrent ? ` <span class="muted">(${link(c.url, "source")})</span>` : ""}`
    : `<span class="unknown">cost not verified</span>${c?.url ? ` <span class="muted">(${link(c.url, "what we know")})</span>` : ""}`;
  const fert = m.fert;
  const money = (v) => (Math.abs(v) < 10 ? `$${v.toFixed(2)}` : usd0(v));
  const fertTxt = isCurrent ? "none (reference)" : fert ? `${money(fert.mid)}/acre/yr <span class="muted">(upper bound)</span>` : "–";
  const wet = m.wet;
  const wetTxt = !isCurrent && wet && wet.mid > 0 ? `<p class="wet-card"><strong>In a wet year like 2016:</strong> about ${fmtLbAc(wet.mid)} lb/acre kept${wet.hi > wet.lo ? ` (${fmtLbAc(wet.lo)}–${fmtLbAc(wet.hi)})` : ""}.</p>` : "";
  const money1 = isCurrent ? "" : moneyLine(s, m);
  return `<article class="card ${i === 0 && x.score != null ? "top" : ""}" aria-label="${esc(s.name)}">
    <div class="card-rank"><span>#${i + 1}${i === 0 && x.score != null ? " for your priorities" : ""}${isCurrent ? " · what you do now" : ""}</span><span class="score${x.score == null ? " unscored" : ""}">${scoreTxt(x)}</span></div>
    <h3>${esc(s.name)}</h3>
    ${s.short ? `<p class="short">${esc(s.short)}</p>` : ""}
    <div class="nkept">
      <div class="nkept-v ${!kept || kept.mid === 0 ? "zero" : ""}">${kept ? fmtLbAc(kept.mid) : "–"} <span class="nkept-u">lb N/acre/yr kept</span></div>
      ${bar}
      <div class="nkept-l">${isCurrent ? "Reference: nothing changes." : kept ? `Long-run average (modelled). In 8 of 10 years: ${fmtLbAc(kept.lo)}–${fmtLbAc(kept.hi)} lb/acre less nitrate leaving your field for the river.${kept.derived ? " (from trials × your field's leak)" : ""}` : "Not estimated for this field."}</div>
      ${wetTxt}
      ${m.note ? `<p class="fine">${esc(m.note)}</p>` : ""}
    </div>
    ${money1}
    <dl class="kv">
      ${money1 ? "" : `<dt>Cost</dt><dd>${costTxt}</dd>`}
      <dt>Fertilizer value</dt><dd>${fertTxt}</dd>
      <dt>Yield risk</dt><dd>${yl ? `<span class="risk ${yl === "moderate" ? "medium" : yl}">${esc(yl)}</span>` : "–"}</dd>
    </dl>
    ${x.unknown?.length ? `<p class="fine" style="margin:0">Ranked without: ${esc(x.unknown.join(", "))} (unknown).</p>` : ""}
    <div class="card-sec"><h4>Why suggested</h4><p>${linkify(s.why || "")}</p></div>
    ${(() => {
      const notes = [
        yieldText(s.yield_risk) ? `<p><strong>Yield:</strong> ${esc(yieldText(s.yield_risk))}</p>` : "",
        c?.basis && !isCurrent ? `<p><strong>Cost basis:</strong> ${esc(c.basis)}${c.source ? ` (${esc(c.source)})` : ""}.</p>` : "",
        money1 ? `<p><strong>Cost:</strong> ${costTxt}</p>` : "",
        s.fert_value_note && !isCurrent ? `<p><strong>Fertilizer value:</strong> ${esc(s.fert_value_note)}</p>` : "",
      ].filter(Boolean).join("");
      return notes ? fold("Yield, cost and fertilizer notes", notes) : "";
    })()}
    ${fold("Evidence", `${trial}${list(s.evidence, (e) => (typeof e === "string" ? esc(e) : `${linkify(e.text || "")}${e.source || e.url ? ` — ${link(e.url, e.source || "source")}` : ""}`))}${s.satellite_evidence ? `<p><strong>From space:</strong> ${esc(s.satellite_evidence)}</p>` : ""}`)}
    ${fold("Soil-health benefits", list(s.soil_health))}
    ${fold("What we don't know yet", list(s.gaps, linkify))}
    ${fold("Check locally before acting", list(s.risks_local_review))}
    ${fold("Who pays", Array.isArray(s.who_pays) && s.who_pays.length ? list(s.who_pays, (w) => `${link(w.url, w.program || "program")}${w.detail ? `: ${linkify(w.detail)}` : ""}`) : `<p class="muted">${isCurrent ? "No change, no payment." : "No program listed."}</p>`)}
  </article>`;
}
