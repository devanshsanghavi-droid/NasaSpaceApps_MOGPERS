// Field panel: header, season ribbon, twins, 2045 outlook, preferences, strategy cards, signpost.
import { esc, isNum, signed, fmt, fmtInt, pct, strategyColor, BADGE_LABEL, BADGE_LEVEL, MONTHS, MONTH_NAMES } from "./util.js";
import { OUTCOMES, PREF_KEYS, rankStrategies, transportFraction, transportEffect } from "./model.js";
import { synthControlChart, climateChart, setMarker } from "./charts.js";

const SCEN_LABEL = { ssp245: "SSP2-4.5", ssp585: "SSP5-8.5" };
// Letters as emitted by pipeline/cdl_fields.py (crop_seq_2016_2024)
const CROP = { C: "corn", S: "soybean", R: "other row crop", W: "wheat", O: "oats/barley/rye (small grain)", H: "hay/alfalfa/clover", P: "grass/pasture", X: "other", "?": "no data" };

// ------------------------------------------------------------------ helpers
export function typeLabel(app, typeId) { return app.types.get(typeId)?.label || `Field type ${typeId}`; }
export function strategyName(app, sid) { return app.strategies.get(sid)?.name || sid; }
export function strategyShort(app, sid) { return app.strategies.get(sid)?.short || sid; }

export function badgeTip(app, badge) {
  const cal = app.calibration?.[badge];
  const label = BADGE_LABEL[badge] || badge;
  if (badge === "beyond") {
    return "Beyond evidence: too few comparable fields or trials, or the future climate is outside anything observed. Treat this as a question for a strip trial, not an answer.";
  }
  if (!cal || !isNum(cal.empirical_error_rate)) return `${label} evidence. Calibration for this badge is not available yet.`;
  const cov = isNum(cal.coverage) ? ` Its 90% intervals contained the true effect ${pct(cal.coverage)} of the time.` : "";
  return `${label} evidence. In a benchmark with known effects and hidden confounders, ${label.toLowerCase()}-badged estimates were wrong ${pct(cal.empirical_error_rate)} of the time (n = ${fmtInt(cal.n)}).${cov}`;
}

export function badgeHtml(app, badge) {
  const lvl = BADGE_LEVEL[badge] ?? 0;
  const bars = [1, 2, 3].map((i) => `<i class="${i <= lvl ? "on" : ""}"></i>`).join("");
  return `<span class="badge ${esc(badge)}" tabindex="0" data-tip="${esc(badgeTip(app, badge))}"><span class="bars4" aria-hidden="true">${bars}</span>${esc(BADGE_LABEL[badge] || badge)}</span>`;
}

function verdict(o, oc) {
  if (!isNum(oc.lo) || !isNum(oc.hi)) return ["", ""];
  const a = o.sign * oc.lo, b = o.sign * oc.hi;
  if (a > 0 && b > 0) return ["good", "likely better"];
  if (a < 0 && b < 0) return ["bad", "likely worse"];
  return ["", "could go either way"];
}

function outcomeRow(o, oc, domain, extra = {}) {
  const [dmin, dmax] = domain;
  const P = (v) => `${(((v - dmin) / (dmax - dmin)) * 100).toFixed(2)}%`;
  const W = (a, b) => `${Math.max(0.6, ((b - a) / (dmax - dmin)) * 100).toFixed(2)}%`;
  const show = extra.shifted || oc;
  const measured = oc.measured !== false;
  const cls = extra.beyond ? "beyond" : measured ? "" : "modelled";
  const today = extra.shifted && isNum(oc.lo) ? `<div class="range today" style="left:${P(oc.lo)};width:${W(oc.lo, oc.hi)}"></div>` : "";
  const range = isNum(show.lo) && isNum(show.hi) ? `<div class="range ${cls}" style="left:${P(show.lo)};width:${W(show.lo, show.hi)}"></div>` : "";
  const ptm = isNum(show.est) ? `<div class="pt" style="left:${P(show.est)}"></div>` : "";
  const [vc, vt] = extra.beyond ? ["", "beyond evidence"] : verdict(o, show);
  const tip = `${o.label}: ${o.sign > 0 ? "higher" : "lower"} is better. ${measured ? "Measured from satellite outcomes on twin fields." : "Modelled from published trials (not measured from space)."}${extra.shifted ? ` Pale bar: today. Dark bar: ${extra.tag}.` : ""}`;
  return `<div class="orow">
    <div class="olabel">${esc(o.label)}<small>${measured ? "measured" : "modelled"}${extra.shifted ? " · " + esc(extra.tag) : ""}</small></div>
    <div class="ibar" data-tip="${esc(tip)}" tabindex="0" aria-label="${esc(o.label)} interval">
      <div class="axis"></div><div class="zero" style="left:${P(0)}"></div>${today}${range}${ptm}
    </div>
    <div class="otext">${isNum(show.est)
      ? `<b>${signed(show.est, o.nd)}${esc(o.unit)}</b>${isNum(show.lo) && isNum(show.hi) ? ` <span class="muted">(${signed(show.lo, o.nd)} to ${signed(show.hi, o.nd)})</span>` : ""}<span class="verdict ${vc}">${vt}</span>`
      : `<span class="muted">not estimated</span>`}</div>
  </div>`;
}

function domainFor(typeEff, key, extraVals = []) {
  const vals = [0, ...extraVals];
  for (const s of Object.values(typeEff)) {
    const oc = s?.outcomes?.[key];
    if (oc) [oc.lo, oc.hi, oc.est].forEach((v) => isNum(v) && vals.push(v));
  }
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
}

// ------------------------------------------------------------------ intro
export function renderIntro(app) {
  const body = document.getElementById("panel-body");
  const heroes = [...app.heroes.values()];
  const nf = app.fields.size;
  body.innerHTML = `
    <div class="panel-section intro">
      <p class="eyebrow">${esc(app.meta?.region || "Region")}</p>
      <h3>What would your field do under a rotation it has never grown?</h3>
      <p>Each dot is one of ${fmtInt(nf)} field samples. Click one to see what each strategy has actually done on fields of the same type, how sure that evidence is, and whether it still holds in a 2045 climate.</p>
      ${heroes.length ? `<div class="hero-list">${heroes.map((h) => `
        <button class="hero-item" data-hero="${esc(h.field_id)}"><strong>${esc(h.name || h.field_id)} →</strong><span class="small">${esc(typeLabel(app, h.type_id))}</span></button>`).join("")}</div>` : ""}
    </div>
    <div class="panel-section" id="signpost-slot"></div>`;
  body.querySelectorAll("[data-hero]").forEach((b) => b.addEventListener("click", () => app.select(b.dataset.hero, { fly: true })));
  renderSignpost(app, body.querySelector("#signpost-slot"));
}

// ------------------------------------------------------------------ field
export function renderField(app, fieldId) {
  const f = app.fields.get(fieldId);
  const body = document.getElementById("panel-body");
  if (!f) { body.innerHTML = `<div class="panel-section"><p>Field ${esc(fieldId)} is not in the field index.</p></div>`; return; }
  const hero = app.heroes.get(fieldId);
  const type = app.types.get(f.type_id);
  const nType = type?.n_fields ?? [...app.fields.values()].filter((x) => x.type_id === f.type_id).length;
  const seq = String(f.seq || "");
  const y0 = 2025 - seq.length; // seq covers 2016-2024 per contract (9 letters)
  const chips = [...seq].map((c, i) => `<span class="chip ${c === "?" ? "nodata" : esc(c)}" data-tip="${y0 + i}: ${esc(CROP[c] || c)}">${esc(c)}<small>${String(y0 + i).slice(2)}</small></span>`).join("");
  const cropKey = [...new Set(seq)].map((c) => `${c} ${CROP[c] || "unlabelled class"}`).join(", ");
  const defn = type?.definition;
  const defVal = (v) => (Array.isArray(v) ? v.map(String).join("-") : v && typeof v === "object" ? JSON.stringify(v) : String(v));
  const defRows = defn && typeof defn === "object" ? Object.entries(defn).filter(([, v]) => v != null) : [];
  const defHtml = defRows.length
    ? `<details class="more type-def"><summary>How this type is defined</summary><dl>${defRows.map(([k, v]) => `<dt>${esc(k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " "))}</dt><dd>${esc(defVal(v))}</dd>`).join("")}</dl></details>`
    : typeof defn === "string" && defn ? `<details class="more type-def"><summary>How this type is defined</summary><p class="small">${esc(defn)}</p></details>` : "";
  const hasSpeech = "speechSynthesis" in window;

  body.innerHTML = `
    <div class="panel-section field-head">
      <p class="eyebrow">Field sample ${esc(f.field_id)}${f.county ? " · " + esc(f.county) + " County" : ""}</p>
      <h3>${esc(typeLabel(app, f.type_id))}</h3>
      ${defHtml}
      <div class="meta-line"><span>${fmtInt(nType)} fields of this type in the region</span><span class="num">${fmt(f.lat, 3)}° N, ${fmt(Math.abs(f.lon), 3)}° W</span></div>
      ${chips ? `<div class="chips" aria-label="Crop sequence">${chips}</div><div class="small muted">Crop sequence ${y0}-2024 (${esc(cropKey)})</div>` : ""}
      ${hero?.story ? `<p class="story">${esc(hero.story)}</p>` : ""}
      <div class="head-actions">
        <button class="btn primary" id="btn-listen" ${hasSpeech ? "" : "disabled title=\"Speech is not supported in this browser\""}>Listen</button>
        ${hero ? `<button class="btn" id="btn-twins" aria-pressed="true">Meet your twins</button>` : `<button class="btn" id="btn-sametype" aria-pressed="true">Same-type fields: on</button>`}
        <button class="btn" id="btn-zoom">Zoom to field</button>
      </div>
    </div>
    ${hero ? ribbonSection(hero) : ""}
    ${hero ? twinsSection(app, hero) : noTwinsSection(app, f)}
    <div class="panel-section" id="outlook"></div>
    <div class="panel-section" id="prefs"></div>
    <div class="panel-section" style="padding-bottom:6px"><h4>Strategies for this field type</h4>
      <div class="bar-legend"><span><i></i>measured</span><span><i class="m"></i>modelled from trials</span><span><i class="b"></i>beyond evidence</span></div>
    </div>
    <div class="cards" id="cards"></div>
    <div class="panel-section" id="signpost-slot"></div>`;

  // actions
  body.querySelector("#btn-listen")?.addEventListener("click", (e) => app.speak(e.currentTarget));
  body.querySelector("#btn-zoom").addEventListener("click", () => app.map.flyTo(f, 13));
  const tw = body.querySelector("#btn-twins");
  if (tw) tw.addEventListener("click", () => {
    const on = tw.getAttribute("aria-pressed") !== "true";
    tw.setAttribute("aria-pressed", String(on));
    tw.textContent = on ? "Meet your twins" : "Show twins";
    app.showTwins(on ? hero : null);
  });
  const st = body.querySelector("#btn-sametype");
  if (st) st.addEventListener("click", () => {
    const on = st.getAttribute("aria-pressed") !== "true";
    st.setAttribute("aria-pressed", String(on));
    st.textContent = `Same-type fields: ${on ? "on" : "off"}`;
    app.map.setEmphasisType(on ? f.type_id : null);
  });
  body.querySelectorAll("[data-hero]").forEach((b) => b.addEventListener("click", () => app.select(b.dataset.hero, { fly: true })));

  if (hero?.synth_control?.years?.length) synthControlChart(body.querySelector("#sc-chart"), hero.synth_control);
  renderOutlook(app, f);
  renderPrefs(app, f);
  renderCards(app, f);
  renderSignpost(app, body.querySelector("#signpost-slot"));
}

function ribbonSection(hero) {
  const rb = hero.ribbon;
  if (!rb || !Array.isArray(rb.months)) return "";
  const rows = [
    { key: "bare_frac", label: "Bare soil", cls: "", tip: (v) => `${pct(v)} of the field bare`, max: 1 },
    { key: "erosivity", label: "Rain erosivity", cls: "ero", tip: (v, m) => `erosivity ${fmt(v, 1)} (${pct(v / m)} of the peak month)` },
    { key: "heat_risk", label: "Heat risk", cls: "heat", tip: (v) => `heat-stress risk ${fmt(v, 2)}` },
  ];
  let html = "";
  for (const r of rows) {
    const vals = rb[r.key];
    if (!Array.isArray(vals)) continue;
    const mx = r.max || Math.max(1e-9, ...vals.filter(isNum));
    const scaleMax = r.key === "heat_risk" ? Math.max(1, mx) : mx;
    html += `<div class="rlabel">${r.label}</div>` + rb.months.map((m, i) => {
      const v = vals[i];
      const h = isNum(v) ? Math.max(2, (v / scaleMax) * 100) : 0;
      return `<div class="cell ${r.cls}" tabindex="-1" data-tip="${MONTH_NAMES[(m - 1) % 12]}: ${isNum(v) ? esc(r.tip(v, mx)) : "no data"}"><span style="height:${h}%"></span></div>`;
    }).join("");
  }
  html += `<div></div>` + rb.months.map((m) => `<div class="mon">${MONTHS[(m - 1) % 12]}</div>`).join("");
  return `<div class="panel-section"><h4>Season ribbon</h4><div class="ribbon" aria-label="Monthly bare soil, rainfall erosivity and heat risk">${html}</div>
    <p class="chart-note">Bare soil is the share of the field without cover. Erosivity is scaled to the peak month. Overlap of bare soil and erosive rain is when soil is lost.</p></div>`;
}

function twinsSection(app, hero) {
  const sc = hero.synth_control;
  const n = (hero.twins || []).length;
  let stats = "";
  if (sc?.years?.length) {
    const pre = [], post = [];
    sc.years.forEach((y, i) => {
      if (!isNum(sc.actual[i]) || !isNum(sc.counterfactual[i])) return;
      (y < sc.switch_year ? pre : post).push(sc.actual[i] - sc.counterfactual[i]);
    });
    const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
    const unit = sc.outcome === "yield_bu_ac" ? "bu/ac" : "";
    if (pre.length) stats += `Before the switch the field tracks its twins within ${fmt(mean(pre.map(Math.abs)), 1)} ${unit} on average. `;
    if (post.length) stats += `After it, the average gap is ${signed(mean(post), 1)} ${unit}.`;
  }
  return `<div class="panel-section"><h4>Meet your twins</h4>
    <p class="small">${fmtInt(n)} fields of the same type that changed strategy are outlined on the map. The dashed line is what those twins say this field would have done without the change.</p>
    ${sc?.years?.length ? `<div class="chart-box"><canvas id="sc-chart" aria-label="Synthetic control chart"></canvas></div><p class="chart-note">${esc(stats)}</p>` : `<p class="muted small">No synthetic-control series exported for this field.</p>`}
  </div>`;
}

function noTwinsSection(app, f) {
  const heroes = [...app.heroes.values()];
  return `<div class="panel-section"><h4>Your twins</h4>
    <p class="small">Fields of the same type are highlighted on the map; their outcomes are what the cards below are built from. Fully worked twin comparisons are available for:</p>
    ${heroes.map((h) => `<button class="btn link" data-hero="${esc(h.field_id)}">${esc(h.name || h.field_id)}</button>`).join("<br>")}
  </div>`;
}

// ------------------------------------------------------------------ outlook (drag to 2045)
export function renderOutlook(app, f) {
  const box = document.getElementById("outlook");
  if (!box) return;
  const hasClimate = !!app.climate?.scenarios;
  box.innerHTML = `<h4>Drag to 2045</h4>
    <div class="outlook-controls">
      <div class="year-row"><span class="year-val" id="year-val">${app.year}</span>
        <input type="range" id="year-slider" min="2025" max="2055" step="1" value="${app.year}" aria-label="Outlook year"></div>
      <div class="scen" role="group" aria-label="Emissions scenario">
        ${["ssp245", "ssp585"].map((s) => `<button data-scen="${s}" aria-pressed="${app.scenario === s}">${SCEN_LABEL[s]}</button>`).join("")}
      </div>
    </div>
    <p class="small muted" id="transport-note" style="margin-top:8px"></p>
    ${hasClimate ? `<div class="chart-box short"><canvas id="climate-chart" aria-label="Projected July-August heat"></canvas></div>
      <p class="chart-note">Jul-Aug heat above 30 C, NASA NEX-GDDP-CMIP6 multi-model mean. SSP lines are 11-year running means; the dotted line is a straight-line interpolation over years with no model output exported.</p><div id="clim-means"></div>` : `<p class="muted small">Climate projections not available.</p>`}
    <div class="analogs"><div id="analog-slot"></div><div id="analog-side"></div></div>`;
  const slider = box.querySelector("#year-slider");
  slider.addEventListener("input", () => { app.year = Number(slider.value); box.querySelector("#year-val").textContent = app.year; updateOutlook(app, f); renderCards(app, f); });
  box.querySelectorAll("[data-scen]").forEach((b) => b.addEventListener("click", () => {
    app.scenario = b.dataset.scen;
    box.querySelectorAll("[data-scen]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.scen === app.scenario)));
    if (hasClimate) climateChart(box.querySelector("#climate-chart"), app.climate, app.scenario, app.year);
    updateOutlook(app, f); renderCards(app, f);
  }));
  if (hasClimate) climateChart(box.querySelector("#climate-chart"), app.climate, app.scenario, app.year);
  updateOutlook(app, f);
}

const CLIM_VARS = [
  { key: "hdd30", label: "Heat >30 C, Jul-Aug", unit: "C-days", nd: 0 },
  { key: "gdd", label: "Degree days, May-Sep", unit: "C-days", nd: 0 },
  { key: "prcp_amj", label: "Rain, Apr-Jun", unit: "mm", nd: 0 },
];
const meanOf = (a) => { const v = (Array.isArray(a) ? a : []).filter(isNum); return v.length ? v.reduce((x, y) => x + y, 0) / v.length : null; };

function climateMeans(app) {
  const c = app.climate;
  const sc = c?.scenarios?.[app.scenario];
  if (!sc) return "";
  const yrs = Array.isArray(sc.years) ? sc.years : [];
  const win = (k) => meanOf((sc[k] || []).filter((_, i) => yrs[i] >= 2035 && yrs[i] <= 2055));
  const hy = Array.isArray(c.historical?.years) ? c.historical.years.filter(isNum) : [];
  const histLabel = hy.length ? `${Math.min(...hy)}-${Math.max(...hy)}` : "historical";
  const rows = CLIM_VARS.map((v) => {
    const h = meanOf(c.historical?.[v.key]), fut = win(v.key);
    if (!isNum(h) && !isNum(fut)) return "";
    const u = typeof c.units?.[v.key] === "string" && c.units[v.key] ? c.units[v.key] : v.unit;
    const d = isNum(h) && isNum(fut) ? `<span class="muted">${signed(fut - h, v.nd)}</span>` : "";
    return `<tr><th scope="row">${esc(v.label)}<div class="small muted">${esc(u)}</div></th><td class="num">${isNum(h) ? fmt(h, v.nd) : "n/a"}</td><td class="num"><b>${isNum(fut) ? fmt(fut, v.nd) : "n/a"}</b></td><td class="num">${d}</td></tr>`;
  }).join("");
  if (!rows) return "";
  return `<table class="clim-table"><thead><tr><th></th><th>${esc(histLabel)}</th><th>2035-2055 ${SCEN_LABEL[app.scenario]}</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="chart-note">Period means of the CMIP6 multi-model series. Only the heat path moves the yield effects; degree days and rain are context.</p>`;
}

function updateOutlook(app, f) {
  setMarker("climate-chart", app.year);
  const cm = document.getElementById("clim-means");
  if (cm) cm.innerHTML = climateMeans(app);
  const tf = transportFraction(app.climate, app.scenario, app.year);
  const note = document.getElementById("transport-note");
  if (note) note.textContent = app.year === 2025
    ? "Today's evidence. Drag the year to move the yield effect along the CMIP6 multi-model heat trajectory toward its 2035-2055 estimate."
    : `${app.year}, ${SCEN_LABEL[app.scenario]}: yield effects are ${Math.round(tf.f * 100)}% of the way from today's estimate to the 2035-2055 estimate (${tf.method}).`;
  // Contract: a list. Also accept the climate module's raw {cells:[...]} block so analogs still show.
  const rawA = app.climate?.analogs;
  const analogs = Array.isArray(rawA) ? rawA : Array.isArray(rawA?.cells) ? rawA.cells : [];
  const show = app.year >= 2035 && analogs.length > 0;
  app.analogMap.mount(document.getElementById("analog-slot"), analogs, show);
  const typeEff = app.effects?.by_type?.[f.type_id] || {};
  const out = Object.entries(typeEff).filter(([sid, s]) => sid !== "S0" && s?.climate?.[app.scenario]?.in_support === false);
  const side = document.getElementById("analog-side");
  let html = "";
  if (app.year < 2035) html = `<p class="small muted">Climate analogs, places that already live this field's future climate, appear from 2035.</p>`;
  else if (show) html = `<p class="small" style="margin-bottom:4px"><strong>Already living this climate</strong></p><ul class="analog-list">${analogs.slice(0, 5).map((a) => `<li><span>${esc(a.label || a.state || "")}</span><span class="muted num">${isNum(a.distance) ? fmt(a.distance, 2) : ""}</span></li>`).join("")}</ul>`;
  else html = `<p class="small muted">No climate analogs exported.</p>`;
  if (app.year >= 2035 && out.length) html += `<div class="beyond-box" style="margin-top:8px">${out.map(([sid]) => esc(strategyShort(app, sid))).join(", ")}: beyond evidence under ${SCEN_LABEL[app.scenario]}. Strip trial recommended.</div>`;
  side.innerHTML = html;
}

// ------------------------------------------------------------------ preferences
function futureList(oc) {
  return PREF_KEYS.map((k) => {
    const o = OUTCOMES.find((x) => x.key === k);
    const v = oc?.[k];
    return v && isNum(v.est) ? `<li>${esc(o.label)}: <b>${signed(v.est, o.nd)}${esc(o.unit)}</b>${v.measured === false ? " <span class=\"muted\">(modelled)</span>" : ""}</li>` : "";
  }).join("");
}

export function renderPrefs(app, f) {
  const box = document.getElementById("prefs");
  if (!box) return;
  const typeEff = app.effects?.by_type?.[f.type_id];
  if (!typeEff) { box.innerHTML = ""; return; }
  const P = app.pref;
  if (!P.started) {
    box.innerHTML = `<h4>What matters to you?</h4>
      <p class="small">Answer six quick "which future would you rather have?" questions. Your answers re-rank the strategies. They never change the evidence.</p>
      <button class="btn primary" id="pref-start">Start: 6 choices</button>`;
    box.querySelector("#pref-start").addEventListener("click", () => { app.startPrefs(f.type_id); renderPrefs(app, f); });
    return;
  }
  if (P.index < P.queue.length) {
    const [a, b] = P.queue[P.index];
    const oa = P.typeEff[a]?.outcomes, ob = P.typeEff[b]?.outcomes;
    box.innerHTML = `<h4>What matters to you?</h4>
      <div class="pref-card">
        <div class="pref-q"><span>Which future would you rather have?</span><span class="muted num">${P.index + 1} of ${P.queue.length}</span></div>
        <div class="pref-opts">
          <button class="pref-opt" data-pick="0"><strong>Future A</strong><ul>${futureList(oa)}</ul></button>
          <button class="pref-opt" data-pick="1"><strong>Future B</strong><ul>${futureList(ob)}</ul></button>
        </div>
      </div>
      <p class="invariant">Each future is one of this field type's strategies, shown without its name. Numbers are the evidence estimates.</p>`;
    box.querySelectorAll("[data-pick]").forEach((btn) => btn.addEventListener("click", () => {
      const pick = Number(btn.dataset.pick);
      app.answerPref(pick === 0 ? oa : ob, pick === 0 ? ob : oa);
      renderPrefs(app, f);
      renderCards(app, f);
    }));
    return;
  }
  // done
  const w = app.weights;
  const rawTotal = PREF_KEYS.reduce((s, k) => s + (w[k] || 0), 0);
  const total = rawTotal || 1;
  const ranking = rankStrategies(typeEff, w, app.scales);
  box.innerHTML = `<h4>What matters to you?</h4>
    <p class="small">Learned from your six choices (Bradley-Terry model on the trade-offs you picked):</p>
    ${rawTotal < 1 ? `<p class="small muted">Your choices pulled in different directions, so no single priority stands out strongly. Treat this ranking as close to a tie.</p>` : ""}
    <div class="weights">${PREF_KEYS.map((k) => {
      const o = OUTCOMES.find((x) => x.key === k);
      const share = (w[k] || 0) / total;
      return `<div class="wrow"><span>${esc(o.label)}</span><div class="wbar"><span style="width:${(share * 100).toFixed(1)}%"></span></div><span class="num small">${pct(share)}</span></div>`;
    }).join("")}</div>
    <p class="small" style="margin-bottom:2px"><strong>Your ranking for this field type</strong></p>
    <ol class="rank-list">${ranking.map((sid) => `<li>${esc(strategyName(app, sid))}</li>`).join("")}</ol>
    ${ranking.missing?.length ? `<p class="small muted">Ranking ignores missing outcomes (${ranking.missing.length} not estimated); they count as no change.</p>` : ""}
    <p class="invariant">Evidence values changed by your answers: <b>${app.evidenceChanged()}</b>. Only the order of the cards changed.</p>
    <button class="btn" id="pref-reset" style="margin-top:8px">Start over</button>`;
  box.querySelector("#pref-reset").addEventListener("click", () => { app.resetPrefs(); renderPrefs(app, f); renderCards(app, f); });
}

// ------------------------------------------------------------------ cards
export function renderCards(app, f) {
  const box = document.getElementById("cards");
  if (!box) return;
  const typeEff = app.effects?.by_type?.[f.type_id];
  if (!typeEff) { box.innerHTML = `<div class="card"><p>No effect estimates exported for this field type yet.</p></div>`; return; }
  const ranked = rankStrategies(typeEff, app.weights, app.scales);
  const ranking = ranked.filter((s) => s !== "S0");
  const missingNote = ranked.missing?.length
    ? `<p class="small muted missing-note" data-tip="${esc("Missing estimates: " + ranked.missing.map((m) => `${strategyShort(app, m.sid)} ${OUTCOMES.find((o) => o.key === m.key)?.label || m.key}`).join(", "))}" tabindex="0">Ranking ignores missing outcomes (${ranked.missing.length} not estimated); they count as no change.</p>`
    : "";
  const order = [...(typeEff.S0 ? ["S0"] : []), ...ranking];
  const tf = transportFraction(app.climate, app.scenario, app.year);
  const shifted = app.year > 2025;
  const tag = `${app.year}, ${SCEN_LABEL[app.scenario]}`;
  const climVals = [];
  for (const s of Object.values(typeEff)) { const c = s?.climate?.[app.scenario]; if (c) [c.lo, c.hi].forEach((v) => isNum(v) && climVals.push(v)); }
  const domains = Object.fromEntries(OUTCOMES.map((o) => [o.key, domainFor(typeEff, o.key, o.key === "yield_pct" ? climVals : [])]));
  const byPrefs = app.pref.answers.length > 0;

  box.innerHTML = missingNote + order.map((sid) => {
    const s = typeEff[sid];
    const strat = app.strategies.get(sid) || { name: sid };
    const isCur = sid === "S0";
    const rankIdx = ranking.indexOf(sid);
    const ev = s.evidence || {};
    const evParts = [];
    if (isNum(ev.n_twin_fields)) evParts.push(`${fmtInt(ev.n_twin_fields)} twin fields`);
    if (isNum(ev.n_trials)) evParts.push(`${fmtInt(ev.n_trials)} randomized trials`);
    if (ev.quasi_experiment) evParts.push(`natural experiment: ${esc(ev.quasi_experiment)}`);
    if (isNum(ev.gamma)) evParts.push(`<span data-tip="Sensitivity: a hidden factor would have to shift the odds of adopting by ${fmt(ev.gamma, 2)}x to erase this effect. Higher is sturdier." tabindex="0" style="text-decoration:underline dotted">Γ ${fmt(ev.gamma, 2)}</span>`);
    if (isNum(ev.overlap)) evParts.push(`<span data-tip="Overlap: how well fields that did and did not adopt cover the same conditions (0 none, 1 complete)." tabindex="0" style="text-decoration:underline dotted">overlap ${fmt(ev.overlap, 2)}</span>`);

    let outcomesHtml = "";
    let climateHtml = "";
    if (!isCur) {
      const clim = s.climate?.[app.scenario];
      const moved = shifted ? transportEffect(s.outcomes?.yield_pct, clim, tf.f) : null;
      outcomesHtml = OUTCOMES.filter((o) => s.outcomes?.[o.key]).map((o) => {
        const oc = s.outcomes[o.key];
        if (o.key === "yield_pct" && moved) return outcomeRow(o, oc, domains[o.key], { shifted: moved, beyond: moved.beyond, tag });
        return outcomeRow(o, oc, domains[o.key]);
      }).join("");
      if (shifted && !(clim && isNum(clim.est))) {
        climateHtml = `<div class="climate-line">No 2035-2055 estimate exported for this strategy under ${SCEN_LABEL[app.scenario]}; showing today's evidence.</div>`;
      } else if (shifted && clim) {
        climateHtml = moved?.beyond
          ? `<div class="climate-line beyond"><strong>Beyond evidence in ${tag}.</strong> ${esc(s.climate.analog_note || "No fields of this kind live this climate today, so the number is not supported. Strip trial recommended.")}</div>`
          : `<div class="climate-line">In ${tag}, the yield effect moves to <b>${signed(moved?.est, 1)}%</b> (${signed(moved?.lo, 1)} to ${signed(moved?.hi, 1)}). ${esc(s.climate.analog_note || "")}</div>`;
      }
    } else {
      outcomesHtml = `<p class="small muted">The reference point: every effect on the other cards is a change from what fields of this type do today.</p>`;
    }

    const list = (arr) => (Array.isArray(arr) && arr.length ? `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : `<span class="muted">none listed</span>`);
    const est = ev.estimators || {};
    const estRows = Object.entries(est).filter(([, v]) => v && isNum(v.est));
    const kv = isCur ? "" : `<div class="kv">
      <div><h5>Information gaps</h5>${list(s.gaps)}</div>
      <div><h5>Risks needing local review</h5>${list(s.risks)}</div>
      ${s.failure_box ? `<div class="wide"><h5>When it fails</h5><span class="failure">${esc(s.failure_box)}</span></div>` : ""}
      ${s.signpost ? `<div class="wide"><h5>Signpost <span style="text-transform:none;letter-spacing:0;font-weight:500">(agronomic guidance, not an identified effect)</span></h5>${esc(s.signpost)}</div>` : ""}
      ${s.next_step ? `<div><h5>Next best step</h5>${esc(s.next_step)}</div>` : ""}
      <div><h5>Who pays</h5>${list(s.who_pays)}</div>
    </div>
    ${estRows.length ? `<details class="more"><summary>Estimator cross-check (yield %)</summary><table><tr><th>Estimator</th><th>Estimate</th><th>Interval</th></tr>
      ${estRows.map(([k, v]) => `<tr><td>${esc({ dr_learner: "DR-learner", did: "Staggered DiD", forest: "Causal forest" }[k] || k)}</td><td>${signed(v.est, 1)}</td><td>${signed(v.lo, 1)} to ${signed(v.hi, 1)}</td></tr>`).join("")}
    </table></details>` : ""}`;

    const rankText = isCur ? "Current" : `#${rankIdx + 1} ${byPrefs ? "for your priorities" : "by default balance"}`;
    return `<article class="card ${isCur ? "current" : ""}" data-sid="${esc(sid)}">
      <div class="card-top">
        <div><p class="rank"><span class="swatch" style="display:inline-block;background:${strategyColor(sid)};margin-right:6px;vertical-align:-1px"></span>${esc(sid)} · ${rankText}</p><h3>${esc(strat.name)}</h3></div>
        ${badgeHtml(app, s.badge)}
      </div>
      ${strat.description ? `<p class="small strat-desc">${esc(strat.description)}</p>` : ""}
      ${strat.applies_to ? `<p class="small muted strat-applies">Applies to: ${esc(strat.applies_to)}</p>` : ""}
      ${s.why ? `<p class="why"><strong>Why suggested:</strong> ${esc(s.why)}</p>` : ""}
      ${evParts.length ? `<p class="evidence-line">Evidence: ${evParts.join(" · ")}</p>` : ""}
      ${climateHtml}
      <div class="outcomes">${outcomesHtml}</div>
      ${kv}
    </article>`;
  }).join("");
}

// ------------------------------------------------------------------ signpost
export function renderSignpost(app, slot) {
  const sp = app.signpost;
  if (!slot) return;
  if (!sp) { slot.innerHTML = `<h4>The plan keeps watching</h4><p class="muted small">No signpost exported.</p>`; return; }
  const p = isNum(sp.percentile) ? Math.max(0, Math.min(100, sp.percentile)) : null;
  const thr = isNum(sp.threshold_percentile) ? sp.threshold_percentile : null;
  const cy = Array.isArray(sp.climatology_years) ? sp.climatology_years.filter(isNum) : [];
  const yrs = cy.length ? (Math.min(...cy) === Math.max(...cy) ? String(cy[0]) : `${Math.min(...cy)}-${Math.max(...cy)}`) : (typeof sp.climatology_years === "string" ? sp.climatology_years : "");
  slot.innerHTML = `<h4>The plan keeps watching</h4>
    <div class="signpost-status ${sp.triggered ? "triggered" : ""}"><span class="dot" aria-hidden="true"></span>${sp.triggered ? "Signpost triggered" : "Signpost quiet"}</div>
    <p class="small" style="margin:6px 0 0">${esc(sp.variable || "")}</p>
    ${p != null ? `<div class="pctbar" aria-label="Percentile ${p}">
      <div class="track"></div>${thr != null ? `<div class="zone" style="width:${thr}%"></div>` : ""}
      <div class="mark" style="left:calc(${p}% - 1px)"></div><div class="lab" style="left:${p}%">${Math.round(p)}th percentile</div>
      <div class="ticks"><span>0</span><span>50th</span><span>100th</span></div></div>` : ""}
    <p style="margin-top:22px">${esc(sp.message || "")}</p>
    <p class="small muted">Current value ${isNum(sp.current_value) ? fmt(sp.current_value, 2) : "n/a"} · ${esc(sp.source || "")}${yrs ? ` · climatology ${esc(yrs)}` : ""}. Agronomic guidance, not an identified effect.</p>`;
}
