// Farmer view: field map, field facts, leak calendar, recent NDVI, strategy cards re-ranked by farmer priorities.
// Fields and strategies load when this view first opens; field_index.json and field_detail/<huc12>.json on click.
import { clamp, esc, fmt, fmtInt, fmtLbAc, isDarkColor, isNum, link, linkify, meanBand, MON3, MONTHS, monthRange, pct, usd, LEAK_RAMP, parseDate } from "./util.js";
import { colors, timeChart, toXY } from "./charts.js";
import { addLabel, addPlaces, bboxOf, createMap, rampLegend, stepExpr } from "./map.js";
import { ensure, getFieldDetail, mockChip, nasaStrip } from "./data.js";

let S;
let farmMap; // undefined = not started, null = failed
let selectedId = null;
let ndviChart;
let currentDetail = null;
let sampleIdx = 0;
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
  document.getElementById("pick-sample").addEventListener("click", async () => {
    await ensure(S, "farm");
    const ids = sampleFields();
    if (!ids.length) return;
    const id = ids[sampleIdx % ids.length];
    sampleIdx++;
    onSelect(id);
  });
}

function renderDisclaimer() {
  document.getElementById("strategy-disclaimer").innerHTML = `<strong>${esc(S.data.strategies?.disclaimer || "Decision support, not a replacement for your agronomist.")}</strong> ${mockChip(S.source, "strategies")}`;
}

function fieldFeatures() {
  return S.data.fields?.features || [];
}

// High-leak, poorly drained fields first: the story the demo tells.
function sampleFields() {
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
  await Promise.all([ensure(S, "farm"), ensure(S, "map")]);
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
  await ensure(S, "farm");
  renderDisclaimer();
  const f = fieldFeatures().find((x) => x.properties.field_id === id);
  if (!f) return false;
  selectedId = id;
  highlight(id, fly);
  const p = f.properties;
  const detail = await getFieldDetail(S, id, p.huc12);
  if (selectedId !== id) return true; // a newer click won
  currentDetail = { props: p, detail };
  document.getElementById("field-empty").hidden = true;
  document.getElementById("field-content").hidden = false;
  renderFieldHead(p, detail);
  renderCalendar(detail);
  renderNdvi(detail);
  renderCards();
  return true;
}

// ------------------------------------------------------------------ field facts
function hucName(h) {
  return (S.data.huc12?.features || []).find((f) => f.properties.huc12 === h)?.properties?.name;
}
function renderFieldHead(p, d) {
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
    <h2>Field ${esc(p.field_id)} ${mockChip(S.source, "fields", "field_detail")}</h2>
    <p class="sub" style="margin:0;color:var(--muted)">About 40 acres in ${esc(hucName(p.huc12) || "HUC-12 " + p.huc12)}${pctile != null ? ` · ${pctile >= 99 ? `among the <strong style="color:var(--ink)">top 1%</strong> of fields nearby for nitrate leak` : `leaks more nitrate than <strong style="color:var(--ink)">${fmtInt(pctile)}%</strong> of fields nearby`}` : ""}</p>
    <div class="facts">
      <div class="fact fact-wide"><div class="fact-v big">${leak ? fmtLbAc(leak.mid) : "–"} <span class="unit">lb N/acre/yr</span></div><div class="fact-l">nitrate-N lost to the river, long-run average ${yrs.length ? `${yrs[0]}–${yrs[yrs.length - 1]}` : ""}${leak && leak.hi > leak.lo ? `<br><strong>${fmtLbAc(leak.lo)}–${fmtLbAc(leak.hi)} lb in 8 of 10 years</strong> (dry years lose almost nothing)` : ""}</div></div>
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
    threshold: { value: 0.3, label: "living cover above 0.30", color: c.accent },
    series: [{ label: "NDVI", data: toXY(xs, nd.ndvi), color: c.ink2, width: 1.4, kind: "points" }],
  });
  ndviChart.data.datasets[0].showLine = true;
  ndviChart.update("none");
  note.innerHTML = `Data: clear-sky NASA HLS (Landsat + Sentinel-2) observations of this field, ${esc(nd.dates[0])} to ${esc(nd.dates[nd.dates.length - 1])}. Below the line the ground is bare or covered only by dead residue. ${mockChip(S.source, "field_detail")}`;
}

// ------------------------------------------------------------------ priorities + cards
function renderPriorities() {
  const box = document.getElementById("prio-sliders");
  box.innerHTML = CRIT.map((c) => `<div class="prio"><label for="w-${c.k}"><span>${esc(c.label)}</span><output id="o-${c.k}">${WLABEL[weights[c.k]]}</output></label><input type="range" id="w-${c.k}" min="0" max="3" step="1" value="${weights[c.k]}"></div>`).join("");
  box.addEventListener("input", (e) => {
    const k = e.target.id?.replace("w-", "");
    if (!(k in weights)) return;
    weights[k] = Number(e.target.value);
    document.getElementById("o-" + k).textContent = WLABEL[weights[k]];
    renderFormula();
    renderCards();
  });
  renderFormula();
}
function renderFormula() {
  document.getElementById("prio-formula").innerHTML = `score = Σ (weight × goal score 0–1) ÷ Σ weights<br>weights now: ${CRIT.map((c) => `${c.short.toLowerCase()} ${weights[c.k]}`).join(", ")}<br><span class="muted">An unknown input (e.g. an unverified cost) is left out of that option's sum, not counted as $0.</span>`;
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
    kept, fert, cost, yl, wet, note: sd.note,
    raw: {
      n: kept ? kept.mid : null,
      yield: yl ? YIELD_SCORE[yl] : null,
      soil,
      cost: cost ? -(cost.mid - (fert ? fert.mid : 0)) : null, // unknown cost -> unknown (excluded), not $0
    },
  };
}

// Min-max scale each goal over the options whose input is KNOWN; unknown inputs are left out of the score.
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
    x.score = wsum > 0 ? known.reduce((s, c) => s + weights[c.k] * x.n[c.k], 0) / wsum : 0;
    x.unknown = CRIT.filter((c) => x.n[c.k] == null).map((c) => c.short.toLowerCase());
  }
  return ms.sort((a, b) => b.score - a.score || a.s.id.localeCompare(b.s.id));
}

function renderCards() {
  if (!currentDetail) return;
  const strats = S.data.strategies?.strategies || [];
  const box = document.getElementById("strategy-cards");
  if (!strats.length) { box.innerHTML = `<p>Strategy evidence is not available yet.</p>`; return; }
  const d = currentDetail.detail;
  const ranked = rank(strats, d);
  const axisMax = Math.max(1, ...ranked.map((x) => x.m.kept?.hi || 0));
  document.getElementById("cards-sub").innerHTML = `Ranked for your priorities (top card outlined). The big number is the long-run average lb N/acre a year; the bar shows the range in 8 of 10 years. Where leak happens comes from NASA satellites and weather; how much each practice cuts comes from Iowa field trials. ${mockChip(S.source, "strategies", "field_detail")}`;
  box.innerHTML = ranked.map((x, i) => cardHTML(x, i, axisMax)).join("");
  const wsum = CRIT.reduce((s, c) => s + weights[c.k], 0);
  document.getElementById("how-rank").innerHTML = `
    <p class="fine">Each goal is scored 0–1 across the options whose input is known (best = 1, worst = 0), then weighted by your sliders (0–3). Unknown inputs are left out of that option's score instead of counting as zero cost.</p>
    <div class="formula">score = Σ known (weight × goal score) ÷ Σ known weights<br>weights: ${CRIT.map((c) => `${c.short.toLowerCase()} ${weights[c.k]}`).join(", ")} (Σ = ${wsum})</div>
    <p class="fine">Goal inputs: nitrogen kept = this field's long-run average lb N/acre; yield safety = trial-based yield risk (low 1, moderate 0.5, high 0); soil health = number of evidence-backed soil benefits; low net cost = −(cost − fertilizer value), $/acre.</p>
    <table><thead><tr><th>Option</th>${CRIT.map((c) => `<th>${esc(c.short)}</th>`).join("")}<th>Score</th></tr></thead>
    <tbody>${ranked.map((x) => `<tr><td>${esc(x.s.id)}</td>${CRIT.map((c) => `<td>${x.n[c.k] == null ? `<span title="unknown: left out">n/a</span>` : fmt(x.n[c.k], 2)}</td>`).join("")}<td><strong>${Math.round(x.score * 100)}</strong></td></tr>`).join("")}</tbody></table>`;
}

function list(items, fn = (t) => esc(t)) {
  if (!Array.isArray(items) || !items.length) return "<p class=\"muted\">None listed.</p>";
  return `<ul>${items.map((t) => `<li>${fn(t)}</li>`).join("")}</ul>`;
}

function cardHTML(x, i, axisMax) {
  const { s, m } = x;
  const isCurrent = s.id === "S0";
  const kept = m.kept;
  const pos = (v) => `${clamp((v / axisMax) * 100, 0, 100)}%`;
  const bar = kept && kept.hi > 0 ? `<div class="ibar" aria-hidden="true"><div class="axis"></div><div class="rng" style="left:${pos(kept.lo)};width:calc(${pos(kept.hi)} - ${pos(kept.lo)})"></div><div class="mid" style="left:calc(${pos(kept.mid)} - 1px)"></div></div>` : "";
  const nr = s.n_loss_reduction;
  const trialUrl = (s.evidence || []).find((e) => e && e.url && /INRS|nutrientstrategy/i.test(`${e.source} ${e.url}`))?.url;
  const trial = nr && isNum(nr.mean) && nr.mean !== 0 ? `<p>Trials: cuts nitrate in drainage by about <strong>${pct(nr.mean)}</strong>${isNum(nr.lo) && isNum(nr.hi) ? ` (8 in 10: ${pct(nr.lo)}–${pct(nr.hi)})` : ""}${nr.source ? ` · <span title="${esc(nr.source)}">${trialUrl ? link(trialUrl, "INRS 2024") : esc(nr.source)}</span>` : ""}</p>` : "";
  const yl = m.yl;
  const c = s.cost_usd_ac;
  const costTxt = m.cost
    ? `${m.cost.lo === m.cost.hi ? usd(m.cost.lo, { compact: false }) : `${usd(m.cost.lo, { compact: false })}–${usd(m.cost.hi, { compact: false })}`}/acre/yr${c?.url && !isCurrent ? ` <span class="muted">(${link(c.url, "source")})</span>` : ""}`
    : `<span class="unknown">cost not verified</span>${c?.url ? ` <span class="muted">(${link(c.url, "what we know")})</span>` : ""}`;
  const fert = m.fert;
  const money = (v) => (Math.abs(v) < 10 ? `$${v.toFixed(2)}` : usd(v, { compact: false }));
  const fertTxt = isCurrent ? "none (reference)" : fert ? `${money(fert.mid)}/acre/yr <span class="muted">(upper bound)</span>` : "–";
  const wet = m.wet;
  const wetTxt = !isCurrent && wet && wet.mid > 0 ? `<p class="wet-card"><strong>In a wet year like 2016:</strong> about ${fmtLbAc(wet.mid)} lb/acre kept${wet.hi > wet.lo ? ` (${fmtLbAc(wet.lo)}–${fmtLbAc(wet.hi)})` : ""}.</p>` : "";
  return `<article class="card ${i === 0 ? "top" : ""}" aria-label="${esc(s.name)}">
    <div class="card-rank"><span>#${i + 1}${i === 0 ? " for your priorities" : ""}${isCurrent ? " · what you do now" : ""}</span><span class="score">${Math.round(x.score * 100)}/100</span></div>
    <h3>${esc(s.name)}</h3>
    ${s.short ? `<p class="short">${esc(s.short)}</p>` : ""}
    <div class="nkept">
      <div class="nkept-v ${!kept || kept.mid === 0 ? "zero" : ""}">${kept ? fmtLbAc(kept.mid) : "–"} <span class="nkept-u">lb N/acre/yr kept</span></div>
      ${bar}
      <div class="nkept-l">${isCurrent ? "Reference: nothing changes." : kept ? `Long-run average. In 8 of 10 years: ${fmtLbAc(kept.lo)}–${fmtLbAc(kept.hi)} lb/acre stays in your field instead of the river.${kept.derived ? " (from trials × your field's leak)" : ""}` : "Not estimated for this field."}</div>
      ${wetTxt}
      ${m.note ? `<p class="fine">${esc(m.note)}</p>` : ""}
    </div>
    <dl class="kv">
      <dt>Fertilizer value</dt><dd>${fertTxt}</dd>
      <dt>Cost</dt><dd>${costTxt}</dd>
      <dt>Yield risk</dt><dd>${yl ? `<span class="risk ${yl === "moderate" ? "medium" : yl}">${esc(yl)}</span>` : "–"}</dd>
    </dl>
    ${s.fert_value_note && !isCurrent ? `<p class="fine" style="margin:0">${esc(s.fert_value_note)}</p>` : ""}
    ${c?.basis && !isCurrent ? `<p class="fine" style="margin:0">Cost basis: ${esc(c.basis)}${c.source ? ` (${esc(c.source)})` : ""}.</p>` : ""}
    ${x.unknown?.length ? `<p class="fine" style="margin:0">Ranked without: ${esc(x.unknown.join(", "))} (unknown).</p>` : ""}
    ${yieldText(s.yield_risk) ? `<p class="fine" style="margin:0">${esc(yieldText(s.yield_risk))}</p>` : ""}
    <div class="card-sec"><h4>Why suggested</h4><p>${linkify(s.why || "")}</p></div>
    <div class="card-sec"><h4>Evidence</h4>${trial}${list(s.evidence, (e) => (typeof e === "string" ? esc(e) : `${linkify(e.text || "")}${e.source || e.url ? ` — ${link(e.url, e.source || "source")}` : ""}`))}${s.satellite_evidence ? `<p><strong>From space:</strong> ${esc(s.satellite_evidence)}</p>` : ""}</div>
    <div class="card-sec"><h4>Soil-health benefits</h4>${list(s.soil_health)}</div>
    <div class="card-sec"><h4>What we don't know yet</h4>${list(s.gaps, linkify)}</div>
    <div class="card-sec"><h4>Check locally before acting</h4>${list(s.risks_local_review)}</div>
    <div class="card-sec"><h4>Who pays</h4>${Array.isArray(s.who_pays) && s.who_pays.length ? list(s.who_pays, (w) => `${link(w.url, w.program || "program")}${w.detail ? `: ${linkify(w.detail)}` : ""}`) : `<p class="muted">${isCurrent ? "No change, no payment." : "No program listed."}</p>`}</div>
  </article>`;
}
