// Farmer view: field map, field facts, leak calendar, recent NDVI, strategy cards re-ranked by farmer priorities.
/* global maplibregl */
import { band, clamp, esc, fmt, fmtInt, isDarkColor, isNum, link, MON3, MONTHS, monthRange, pct, usd, LEAK_RAMP, parseDate } from "./util.js";
import { colors, timeChart, toXY } from "./charts.js";
import { addLabel, addPlaces, bboxOf, createMap, rampLegend, stepExpr } from "./map.js";
import { getFieldDetail, mockChip } from "./data.js";

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
  document.getElementById("pick-sample").addEventListener("click", () => {
    const ids = sampleFields();
    if (!ids.length) return;
    const id = ids[sampleIdx % ids.length];
    sampleIdx++;
    onSelect(id);
  });
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
  // spread picks across the top tenth so repeated clicks show different fields
  const out = [];
  for (let i = 0; i < 5 && top.length; i++) out.push(top[Math.floor((i / 5) * top.length)].field_id);
  return out;
}

export async function initFarmMap(onSelect) {
  if (farmMap !== undefined) { farmMap?.resize(); return; }
  farmMap = null;
  const feats = fieldFeatures();
  const container = document.getElementById("farm-map");
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
  document.getElementById("farm-map-legend").innerHTML = rampLegend(ramp, ["lowest leak", "highest leak"], "Field nitrate leak, percentile in this area (fifths)") + mockChip(S.source, "fields");
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
  const leak = band(d?.leak?.lbN_ac_yr);
  const seq = String(d?.seq || p.seq || "");
  const firstYear = 2025 - seq.length + 1;
  const seqHTML = seq ? `<span class="seq" aria-label="Crop sequence">${[...seq].map((ch, i) => `<span class="${esc(ch)}" title="${firstYear + i}: ${esc(CROPS[ch] || ch)}">${esc(ch)}</span>`).join("")}</span>` : "–";
  const letters = [...new Set(seq)].map((ch) => `${ch} = ${CROPS[ch] || ch}`).join(", ");
  const pctile = isNum(p.leak_pctile) ? p.leak_pctile : null;
  document.getElementById("field-head").innerHTML = `
    <h2>Field ${esc(p.field_id)} ${mockChip(S.source, "fields", "field_detail")}</h2>
    <p class="sub" style="margin:0;color:var(--muted)">About 40 acres in ${esc(hucName(p.huc12) || "HUC-12 " + p.huc12)}${pctile != null ? ` · leaks more nitrate than <strong style="color:var(--ink)">${fmtInt(pctile)}%</strong> of fields nearby` : ""}</p>
    <div class="facts">
      <div class="fact"><div class="fact-v big">${leak ? fmtInt(leak.mid) : "–"}</div><div class="fact-l">lb nitrate-N lost per acre per year${leak ? ` (range ${fmtInt(leak.lo)}–${fmtInt(leak.hi)})` : ""}</div></div>
      <div class="fact"><div class="fact-v">${esc(d?.drainage || p.drainage || "–")}</div><div class="fact-l">soil drainage (SSURGO)</div></div>
      <div class="fact"><div class="fact-v">${isNum(d?.slope_pct ?? p.slope_pct) ? fmt(d?.slope_pct ?? p.slope_pct, 1) + "%" : "–"}</div><div class="fact-l">average slope (NASADEM)</div></div>
      <div class="fact"><div class="fact-v">${esc(d?.crop_2025 || CROPS[seq.slice(-1)] || "–")}</div><div class="fact-l">crop in 2025 (CDL)</div></div>
    </div>
    <p class="fine">Crops ${firstYear}–2025: ${seqHTML} <span class="muted">${esc(letters)}</span>${coverYearsText(d)}</p>`;
}
function coverYearsText(d) {
  const cy = d?.cover_years;
  if (!cy) return "";
  const yrs = Object.entries(cy).filter(([, v]) => v).map(([y]) => y);
  const n = Object.keys(cy).length;
  return yrs.length ? `<br>Winter living cover seen by satellite in ${yrs.length} of ${n} winters (${yrs.join(", ")}).` : `<br>No winter living cover seen by satellite in ${n} winters.`;
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
    return;
  }
  const order = (cal.months || [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]).map((m) => m - 1);
  const get = (k) => order.map((_, i) => cal[k]?.[i]);
  const rows = [
    { k: "bare_frac", label: "Bare ground (HLS)", f: (v) => Math.round(v * 100), norm: (v) => v, ramp: DRIVER_RAMP, title: (v) => `${Math.round(v * 100)}% bare` },
    { k: "rain_mm", label: "Rain, mm", f: (v) => Math.round(v), ramp: DRIVER_RAMP, title: (v) => `${Math.round(v)} mm rain` },
    { k: "storm_days", label: "Big-storm days", f: (v) => (v >= 10 ? Math.round(v) : fmt(v, 1)), ramp: DRIVER_RAMP, title: (v) => `${fmt(v, 1)} big-storm days` },
    { k: "wetness", label: "Soil wetness", f: (v) => Math.round(v * 100), ramp: DRIVER_RAMP, minmax: true, title: (v) => `soil wetness ${fmt(v, 2)} (0–1)` },
    { k: "leak_risk", label: "Leak risk", f: (v) => Math.round(v * 100), ramp: LEAK_RAMP(), cls: "cal-row-risk", title: (v) => `leak risk ${Math.round(v * 100)} of 100` },
  ];
  const risk = get("leak_risk");
  const [w0, w1] = riskWindow(risk);
  let html = `<div class="cal-h cal-h-blank"></div>` + order.map((m) => `<div class="cal-h" title="${MON3[m]}">${MONTHS[m]}</div>`).join("");
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
      const win = r.k === "leak_risk" && i >= w0 && i <= w1 ? " win" : "";
      return `<div class="cal-c${isDarkColor(c) ? " dark" : ""}${win}" style="background:${c}" title="${MON3[order[i]]}: ${esc(r.title(v))}">${r.f(v)}</div>`;
    }).join("");
  }
  box.innerHTML = html;
  // one plain sentence
  const bare = get("bare_frac"), storms = get("storm_days"), wet = get("wetness"), rain = get("rain_mm");
  const sum = (a, i0 = 0, i1 = 11) => a.slice(i0, i1 + 1).reduce((s, v) => s + (isNum(v) ? v : 0), 0);
  const bareAvg = sum(bare, w0, w1) / 3;
  const stormTot = sum(storms);
  const share = stormTot > 0 ? sum(storms, w0, w1) / stormTot : (sum(rain) > 0 ? sum(rain, w0, w1) / sum(rain) : null);
  const what = stormTot > 0 ? "big storms" : "rain";
  const wetMax = wet.indexOf(Math.max(...wet.filter(isNum)));
  const wetTxt = wetMax >= w0 && wetMax <= w1 ? " and the soil was at its wettest" : "";
  const months = monthRange(order[w0], order[w1]);
  if (bareAvg >= 0.4) {
    explain.innerHTML = `Your field sat bare (${pct(bareAvg)} of the time) in <strong>${months}</strong>, when ${share != null ? `<strong>${pct(share)}</strong> of the year's ${what} hit` : "storms hit"}${wetTxt}. That is when nitrate washes out to the river.`;
  } else {
    explain.innerHTML = `Your field had living cover most of ${months} (bare only ${pct(bareAvg)} of the time), the months when ${share != null ? `${pct(share)} of the year's ${what} hit` : "storms hit"}. Living roots hold nitrate in place.`;
  }
  document.getElementById("cal-note").innerHTML = `Each row is shaded within itself (darker = more). Bare ground: NASA HLS (Landsat + Sentinel-2) per field. Rain and storms: GPM IMERG / NASA POWER. Soil wetness: NASA POWER root-zone wetness (SMAP when available). Leak risk combines all of them with soil drainage. The outlined months are the riskiest three. ${mockChip(S.source, "field_detail")}`;
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
  note.innerHTML = `Clear-sky NASA HLS observations. Below the line the ground is bare or covered only by dead residue. ${mockChip(S.source, "field_detail")}`;
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

function strategyMetrics(s, d) {
  const sd = d?.strategies?.[s.id] || {};
  const leak = band(d?.leak?.lbN_ac_yr);
  let kept = band(sd.lbN_kept_ac);
  if (!kept && leak && s.n_loss_reduction) {
    const nr = s.n_loss_reduction;
    if (isNum(nr.mean)) kept = { mid: leak.mid * nr.mean, lo: leak.mid * (nr.lo ?? nr.mean), hi: leak.mid * (nr.hi ?? nr.mean), derived: true };
  }
  const fert = band(sd.fert_value_usd_ac);
  const cost = band(s.cost_usd_ac ? { p50: ((s.cost_usd_ac.lo ?? 0) + (s.cost_usd_ac.hi ?? 0)) / 2, lo: s.cost_usd_ac.lo, hi: s.cost_usd_ac.hi } : null);
  const yl = yieldLevel(s.yield_risk);
  const soil = isNum(s.soil_score) ? s.soil_score : Array.isArray(s.soil_health) ? s.soil_health.length : null;
  return {
    kept, fert, cost, yl,
    raw: {
      n: kept ? kept.mid : null,
      yield: yl ? YIELD_SCORE[yl] : null,
      soil,
      cost: cost ? -(cost.mid - (fert ? fert.mid : 0)) : null,
    },
  };
}

function rank(strats, d) {
  const ms = strats.map((s) => ({ s, m: strategyMetrics(s, d) }));
  const norm = {};
  for (const c of CRIT) {
    const v = ms.map((x) => x.m.raw[c.k]).filter(isNum);
    const mn = Math.min(...v), mx = Math.max(...v);
    norm[c.k] = (val) => (!isNum(val) ? 0 : mx > mn ? (val - mn) / (mx - mn) : 1);
  }
  const wsum = CRIT.reduce((s, c) => s + weights[c.k], 0) || 1;
  for (const x of ms) {
    x.n = Object.fromEntries(CRIT.map((c) => [c.k, norm[c.k](x.m.raw[c.k])]));
    x.score = CRIT.reduce((s, c) => s + weights[c.k] * x.n[c.k], 0) / wsum;
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
  document.getElementById("cards-sub").innerHTML = `Ranked for your priorities (top card outlined). Ranges show where the true value lands in about 8 of 10 years like yours: field numbers come from satellite-seen bare and wet days, anchored to Iowa field trials. ${mockChip(S.source, "strategies", "field_detail")}`;
  box.innerHTML = ranked.map((x, i) => cardHTML(x, i, axisMax)).join("");
  // how we rank
  const wsum = CRIT.reduce((s, c) => s + weights[c.k], 0);
  document.getElementById("how-rank").innerHTML = `
    <p class="fine">Each goal is scored 0–1 across the four options (best = 1, worst = 0), then weighted by your sliders (0–3).</p>
    <div class="formula">score = Σ (weight × goal score) ÷ Σ weights<br>weights: ${CRIT.map((c) => `${c.short.toLowerCase()} ${weights[c.k]}`).join(", ")} (Σ = ${wsum})</div>
    <p class="fine">Goal inputs: nitrogen kept = this field's lb N/acre (median); yield safety = trial-based yield risk (low 1, medium 0.5, high 0); soil health = evidence-based soil score; low net cost = −(cost − fertilizer value), $/acre.</p>
    <table><thead><tr><th>Option</th>${CRIT.map((c) => `<th>${esc(c.short)}</th>`).join("")}<th>Score</th></tr></thead>
    <tbody>${ranked.map((x) => `<tr><td>${esc(x.s.id)}</td>${CRIT.map((c) => `<td>${fmt(x.n[c.k], 2)}</td>`).join("")}<td><strong>${Math.round(x.score * 100)}</strong></td></tr>`).join("")}</tbody></table>`;
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
  const trial = nr && isNum(nr.mean) && nr.mean !== 0 ? `<p>Trials: cuts nitrate loss by about <strong>${pct(nr.mean)}</strong>${isNum(nr.lo) && isNum(nr.hi) ? ` (range ${pct(nr.lo)}–${pct(nr.hi)})` : ""}${nr.source ? ` · ${esc(nr.source)}` : ""}</p>` : "";
  const yl = m.yl;
  const cost = s.cost_usd_ac;
  const costTxt = cost && isNum(cost.lo) ? (cost.lo === cost.hi ? usd(cost.lo, { compact: false }) : `${usd(cost.lo, { compact: false })}–${usd(cost.hi, { compact: false })}`) + "/acre" : "–";
  const fert = m.fert;
  const fertTxt = fert ? `${usd(fert.mid, { compact: false })}/acre${fert.lo !== fert.hi ? ` <span class="muted">(${usd(fert.lo, { compact: false })}–${usd(fert.hi, { compact: false })})</span>` : ""}` : "–";
  return `<article class="card ${i === 0 ? "top" : ""}" aria-label="${esc(s.name)}">
    <div class="card-rank"><span>#${i + 1}${i === 0 ? " for your priorities" : ""}${isCurrent ? " · what you do now" : ""}</span><span class="score">${Math.round(x.score * 100)}/100</span></div>
    <h3>${esc(s.name)}</h3>
    ${s.short ? `<p class="short">${esc(s.short)}</p>` : ""}
    <div class="nkept">
      <div class="nkept-v ${!kept || kept.mid === 0 ? "zero" : ""}">${kept ? fmtInt(kept.mid) : "–"} <span style="font-size:0.9rem;font-family:var(--sans)">lb N/acre kept</span></div>
      ${bar}
      <div class="nkept-l">${isCurrent ? "Reference: nothing changes." : kept ? `In 8 of 10 years: ${fmtInt(kept.lo)}–${fmtInt(kept.hi)} lb/acre stays in your field instead of the river.${kept.derived ? " (from trials × your field's leak)" : ""}` : "Not estimated for this field."}</div>
    </div>
    <dl class="kv">
      <dt>Fertilizer value</dt><dd>${fertTxt}</dd>
      <dt>Cost</dt><dd>${costTxt}</dd>
      <dt>Yield risk</dt><dd>${yl ? `<span class="risk ${yl === "moderate" ? "medium" : yl}">${esc(yl)}</span>` : "–"}</dd>
    </dl>
    ${yieldText(s.yield_risk) ? `<p class="fine" style="margin:0">${esc(yieldText(s.yield_risk))}</p>` : ""}
    <div class="card-sec"><h4>Why suggested</h4><p>${esc(s.why || "")}</p></div>
    <div class="card-sec"><h4>Evidence</h4>${trial}${list(s.evidence, (e) => (typeof e === "string" ? esc(e) : `${esc(e.text || "")}${e.source || e.url ? ` — ${link(e.url, e.source || "source")}` : ""}`))}${s.satellite_evidence ? `<p><strong>From space:</strong> ${esc(s.satellite_evidence)}</p>` : ""}</div>
    <div class="card-sec"><h4>Soil-health benefits</h4>${list(s.soil_health)}</div>
    <div class="card-sec"><h4>What we don't know yet</h4>${list(s.gaps)}</div>
    <div class="card-sec"><h4>Check locally before acting</h4>${list(s.risks_local_review)}</div>
    <div class="card-sec"><h4>Who pays</h4>${Array.isArray(s.who_pays) && s.who_pays.length ? list(s.who_pays, (w) => `${link(w.url, w.program || "program")}${w.detail ? `: ${esc(w.detail)}` : ""}`) : `<p class="muted">${isCurrent ? "No change, no payment." : "No program listed."}</p>`}</div>
  </article>`;
}
