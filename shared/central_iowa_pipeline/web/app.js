// COUNTERFIELD front end: wiring and state. Data flow:
// loadAll() (web/data -> web/mock fallback) -> app state -> FieldMap + panel + sections.
import { loadAll, indexFields } from "./js/data.js";
import { initTooltips, esc, strategyColor, typeColor, cssVar, BADGE_VARS, BADGE_LABEL, fmtInt } from "./js/util.js";
import { FieldMap, AnalogMap, describeFieldHtml } from "./js/map.js";
import { outcomeScales, rankStrategies, fitWeights, DEFAULT_WEIGHTS } from "./js/model.js";
import { renderIntro, renderField, renderCards, typeLabel, strategyName } from "./js/panel.js";
import { renderHindcast, renderCounty, renderAbout } from "./js/sections.js";
import { speak } from "./js/voice.js";

const TILE_BOUNDS = [[-94.2165, 41.4575], [-92.8813, 42.4527]]; // data/region.json tile_bounds_lonlat

function numericLeaves(obj, out = []) {
  if (typeof obj === "number") out.push(obj);
  else if (obj && typeof obj === "object") for (const v of Object.values(obj)) numericLeaves(v, out);
  return out;
}

async function main() {
  initTooltips();
  const { data, source } = await loadAll();

  const app = {
    data, source,
    meta: data.meta, effects: data.effects, climate: data.climate, hindcast: data.hindcast,
    policy: data.policy, signpost: data.signpost,
    calibration: data.badge_calibration?.badge || data.badge_calibration || {},
    fields: indexFields(data.fields_index),
    types: new Map((data.field_types?.types || []).map((t) => [t.type_id, t])),
    strategies: new Map((data.effects?.strategies || []).map((s) => [s.strategy_id, s])),
    heroes: new Map(),
    year: 2025, scenario: "ssp245", selected: null,
    weights: { ...DEFAULT_WEIGHTS },
    pref: { started: false, queue: [], index: 0, answers: [], typeEff: null },
  };
  // Heroes must be selectable fields; drop (and report) any hero that is not in fields_index.
  for (const h of Array.isArray(data.hero_fields) ? data.hero_fields : []) {
    if (h && app.fields.has(h.field_id)) app.heroes.set(h.field_id, h);
    else console.warn(`[counterfield] hero ${h?.field_id} is not in fields_index (is_field rows only); hidden`);
  }
  app.scales = outcomeScales(app.effects);
  app.typeOrder = [...app.types.keys()];
  for (const f of app.fields.values()) if (!app.typeOrder.includes(f.type_id)) app.typeOrder.push(f.type_id);
  const evidenceSnapshot = numericLeaves(app.effects);
  app.evidenceChanged = () => { const now = numericLeaves(app.effects); return now.reduce((n, v, i) => n + (v !== evidenceSnapshot[i] ? 1 : 0), 0) + Math.abs(now.length - evidenceSnapshot.length); };

  // ---- banner
  // counties.geojson is outside the web contract (outlines only, no numbers): it never triggers the banner on its own.
  const contractKeys = Object.keys(source).filter((k) => k !== "counties");
  const allContractReal = contractKeys.every((k) => source[k] === "data");
  const mocked = Object.entries(source).filter(([k, v]) => v === "mock" && !(k === "counties" && allContractReal)).map(([k]) => k);
  const missing = Object.entries(source).filter(([, v]) => v === "missing").map(([k]) => k);
  const banner = document.getElementById("mock-banner");
  if (mocked.length || missing.length) {
    banner.hidden = false;
    const all = contractKeys.every((k) => source[k] === "mock"); // real county outlines alone do not make numbers real
    document.getElementById("mock-banner-text").textContent = all
      ? "Every number on this page is a synthetic placeholder for interface testing. Real NASA-derived estimates load automatically from web/data/ once exported."
      : `${mocked.length ? `Placeholder (synthetic) files: ${mocked.join(", ")}.` : ""} ${missing.length ? `Missing: ${missing.join(", ")}.` : ""} Other files are real exports.`;
    document.documentElement.style.setProperty("--banner-h", banner.offsetHeight + "px");
    window.addEventListener("resize", () => document.documentElement.style.setProperty("--banner-h", banner.offsetHeight + "px"));
  }
  if (app.meta?.region) document.getElementById("region-name").textContent = app.meta.region;

  // ---- best strategy per type under current weights
  const bestByType = () => {
    const out = {};
    for (const [tid, te] of Object.entries(app.effects?.by_type || {})) {
      const sid = rankStrategies(te, app.weights, app.scales)[0];
      out[tid] = { sid, badge: te[sid]?.badge };
    }
    return out;
  };
  const buildFieldsGeo = () => {
    const best = bestByType();
    const useCol = app.pref.answers.length === 0;
    return {
      type: "FeatureCollection",
      features: [...app.fields.values()].map((f) => ({
        type: "Feature",
        properties: { id: f.field_id, t: f.type_id, s: best[f.type_id]?.sid || "S0",
          b: (useCol && f.badge_best && BADGE_LABEL[f.badge_best] ? f.badge_best : best[f.type_id]?.badge) || "beyond" },
        geometry: { type: "Point", coordinates: [f.lon, f.lat] },
      })),
    };
  };

  // ---- map
  let bounds = TILE_BOUNDS;
  if (app.fields.size) {
    let x0 = 180, y0 = 90, x1 = -180, y1 = -90;
    for (const f of app.fields.values()) { x0 = Math.min(x0, f.lon); x1 = Math.max(x1, f.lon); y0 = Math.min(y0, f.lat); y1 = Math.max(y1, f.lat); }
    bounds = [[x0, y0], [x1, y1]];
  }
  app.map = new FieldMap(document.getElementById("map"), {
    bounds,
    onSelect: (id) => app.select(id),
    describe: (id) => { const f = app.fields.get(id); return f ? describeFieldHtml(f, typeLabel(app, f.type_id)) : esc(id); },
  });
  const heroGeo = { type: "FeatureCollection", features: [...app.heroes.values()].filter((h) => typeof h.lon === "number")
    .map((h) => ({ type: "Feature", properties: { id: h.field_id, name: h.name || h.field_id }, geometry: { type: "Point", coordinates: [h.lon, h.lat] } })) };
  app.map.setData({ fieldsGeo: buildFieldsGeo(), countiesGeo: data.counties, heroGeo, typeOrder: app.typeOrder });
  const center = [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2];
  app.analogMap = new AnalogMap(center);

  // ---- legend
  const legend = document.getElementById("legend");
  let colorBy = "strategy";
  const renderLegend = () => {
    const counts = {};
    const geo = app.map.fieldsGeo.features;
    const key = colorBy === "strategy" ? "s" : colorBy === "badge" ? "b" : "t";
    for (const ft of geo) counts[ft.properties[key]] = (counts[ft.properties[key]] || 0) + 1;
    let rows = [];
    if (colorBy === "strategy") rows = ["S0", "S1", "S2", "S3"].filter((s) => app.strategies.has(s)).map((s) => [strategyColor(s), app.strategies.get(s).short || s, counts[s], false]);
    else if (colorBy === "badge") rows = ["strong", "moderate", "thin", "beyond"].map((b) => [cssVar(BADGE_VARS[b]), BADGE_LABEL[b], counts[b], b === "beyond"]);
    else rows = app.typeOrder.map((t) => [typeColor(t, app.typeOrder), typeLabel(app, t), counts[t], false]);
    legend.innerHTML = (colorBy === "strategy" ? `<div class="small muted">Top-ranked strategy for the field's type${app.pref.answers.length ? " (your priorities)" : ""}</div>` :
      colorBy === "badge" ? `<div class="small muted">Evidence behind the top-ranked strategy</div>` : "") +
      rows.map(([c, label, n, hollow]) => `<div class="legend-row"><span class="swatch ${hollow ? "hollow" : ""}" style="background:${c}"></span><span>${esc(label)} <span class="muted">${fmtInt(n || 0)}</span></span></div>`).join("");
  };
  document.querySelectorAll('input[name="colorby"]').forEach((r) => r.addEventListener("change", () => { colorBy = r.value; app.map.setColorBy(colorBy); renderLegend(); }));
  renderLegend();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { renderLegend(); if (app.selected) renderField(app, app.selected); });

  // ---- selection
  app.showTwins = (hero) => {
    const twins = hero ? (hero.twins || []).map((id) => app.fields.get(id)).filter(Boolean) : [];
    app.map.showTwins(hero, twins);
  };
  app.select = (id, opts = {}) => {
    if (!app.fields.has(id)) return;
    app.selected = id;
    const f = app.fields.get(id);
    if (location.hash !== "#" + id) history.replaceState(null, "", "#" + id);
    window.speechSynthesis?.cancel();
    app.map.select(f);
    app.map.setEmphasisType(f.type_id);
    const hero = app.heroes.get(id);
    if (hero) app.showTwins(hero);
    else { app.showTwins(null); if (opts.fly) app.map.flyTo(f); }
    renderField(app, id);
    document.getElementById("panel").scrollTop = 0;
    if (window.innerWidth <= 860 && opts.scroll !== false) document.getElementById("panel").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  app.deselect = () => {
    app.selected = null;
    history.replaceState(null, "", location.pathname);
    app.map.select(null); app.map.setEmphasisType(null); app.showTwins(null);
    app.map.map.fitBounds(bounds, { padding: 24, duration: 700 });
    renderIntro(app);
  };
  document.getElementById("home-link").addEventListener("click", (e) => { e.preventDefault(); app.deselect(); window.scrollTo(0, 0); });
  app.speak = (btn) => speak(app, btn);

  // ---- preferences (Bradley-Terry)
  app.startPrefs = (typeId) => {
    const typeEff = app.effects?.by_type?.[typeId];
    const sids = Object.keys(typeEff || {}).sort();
    const pairs = [];
    for (let i = 0; i < sids.length; i++) for (let j = i + 1; j < sids.length; j++) pairs.push([sids[i], sids[j]]);
    const order = [3, 0, 5, 1, 4, 2].filter((k) => k < pairs.length);
    const rest = pairs.map((_, k) => k).filter((k) => !order.includes(k));
    app.pref = { started: true, index: 0, answers: [], typeEff,
      queue: [...order, ...rest].slice(0, 6).map((k, n) => (n % 2 ? pairs[k].slice().reverse() : pairs[k])) };
  };
  app.answerPref = (chosen, other) => {
    app.pref.answers.push({ chosen, other });
    app.pref.index += 1;
    app.weights = fitWeights(app.pref.answers, app.scales);
    app.map.updateFieldProps(buildFieldsGeo());
    renderLegend();
  };
  app.resetPrefs = () => {
    app.pref = { started: false, queue: [], index: 0, answers: [], typeEff: null };
    app.weights = { ...DEFAULT_WEIGHTS };
    app.map.updateFieldProps(buildFieldsGeo());
    renderLegend();
  };

  // ---- sections
  renderHindcast(app);
  renderCounty(app);
  renderAbout(app);

  const fromHash = location.hash.slice(1);
  if (fromHash && app.fields.has(fromHash)) app.select(fromHash, { fly: true, scroll: false });
  else renderIntro(app);

  window.__counterfield = app; // for debugging in the console
}

main().catch((e) => {
  console.error(e);
  document.getElementById("panel-body").innerHTML = `<div class="panel-section"><p>Could not start: ${esc(e.message)}</p></div>`;
});
