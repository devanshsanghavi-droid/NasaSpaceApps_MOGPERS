// Method & evidence view: the honest miss, validation tables (v1/v2, every period), outlook skill, the plant/ban
// proxy-rule test, data sources (NASA tag), caveats, provenance of each data file.
import { esc, fmt, fmtInt, isNum, link } from "./util.js";
import { factsMap, mockChip, nasaStrip, provenanceTable } from "./data.js";
import { honestLine } from "./city.js";

const MODEL_LABEL = {
  gbm: "Model v1: NASA weather + satellite cover (clean test)",
  gbm_v2: "Model v2: v1 + drought carry-over (built after the 2025 miss)",
  reservoir: "Two-reservoir nitrate model",
  climatology: "Usual level for the date (climatology)",
  persistence_7d: "Same as 7 days ago (needs last week's measurement)",
  persistence_14d: "Same as 14 days ago (needs a measurement)",
};
const MODEL_ORDER = ["gbm", "gbm_v2", "reservoir", "climatology", "persistence_7d", "persistence_14d"];
const COLS = [
  { k: ["NSE", "nse"], label: "NSE", hint: "1 = perfect, 0 = no better than the average", best: "max" },
  { k: ["KGE", "kge"], label: "KGE", hint: "1 = perfect", best: "max" },
  { k: ["RMSE", "rmse"], label: "RMSE mg/L", hint: "typical error", best: "min" },
  { k: ["coverage80"], label: "80% band hit", hint: "should be near 80%", pct: true },
  { k: ["CSI", "csi"], label: "Days > 10 skill (CSI)", hint: "share of correctly called days above 10 mg/L", best: "max" },
];
const SPLIT_LABEL = { train: "Training years (leave-one-year-out score)", test: "Out-of-time test (never seen)", live: "Live 2026" };
const pick = (o, keys) => { for (const k of keys) if (o && isNum(o[k])) return o[k]; return null; };
const cell = (c, val) => (isNum(val) ? (c.pct ? Math.round(val * 100) + "%" : fmt(val, 2)) : "–");

// Accepts {sites:{<site>:{name, by_split:{<split>:{<model>:{...}}}}}} or the raw metrics.json shape {<site>:{<split>:{<model>:{...}}}}
function normalize(v) {
  if (!v) return [];
  const sites = v.sites || v;
  return Object.entries(sites).filter(([, s]) => s && typeof s === "object").map(([site, s]) => {
    const splits = s.by_split || s.splits || Object.fromEntries(Object.entries(s).filter(([k, x]) => ["train", "test", "live"].includes(k) && x && typeof x === "object"));
    return { site, name: s.name || site, splits, raw: s };
  }).filter((x) => Object.keys(x.splits || {}).length);
}
function displayFor(v, site) {
  const d = v?.display_model;
  return (typeof d === "string" ? d : d?.[site]) || v?.sites?.[site]?.display_model || "v1";
}
const modelKey = (dm) => (dm === "v2" ? "gbm_v2" : "gbm");

export function renderMethod(store) {
  const { data, source } = store;
  const v = data.validation;
  document.getElementById("nasa-strip-method").innerHTML = nasaStrip(data.meta);

  // ---- the honest miss
  const hl = honestLine(v);
  const crisis = v?.crisis_2025?.text;
  document.getElementById("method-honest").innerHTML = hl
    ? `<p class="honest"><strong>In one line:</strong> ${esc(hl)}</p>${crisis ? `<p>${esc(crisis)}</p>` : ""}${mockChip(source, "validation")}`
    : "<p>Validation results are not available yet.</p>";

  // ---- validation
  const box = document.getElementById("validation");
  const sites = normalize(v);
  let html = "";
  // lines already quoted in the "honest miss" block above are not repeated
  const lines = (v?.lines || []).filter((l) => !(crisis && crisis.includes(String(l).slice(0, 60))));
  if (lines.length) html += `<ul class="val-lines">${lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>`;
  for (const s of sites) {
    const dm = displayFor(v, s.site);
    const shown = modelKey(dm);
    const split = s.splits.test ? "test" : Object.keys(s.splits)[0];
    const models = s.splits[split] || {};
    const order = MODEL_ORDER.filter((m) => models[m]).concat(Object.keys(models).filter((m) => !MODEL_ORDER.includes(m)));
    const best = {};
    for (const c of COLS) {
      if (!c.best) continue;
      const vals = order.map((m) => pick(models[m], c.k)).filter(isNum);
      if (vals.length) best[c.label] = c.best === "max" ? Math.max(...vals) : Math.min(...vals);
    }
    const period = v?.splits?.[split] || v?.split?.[split];
    html += `<h3>${esc(s.name)} <span class="muted">· ${split === "test" ? "out-of-time test" : esc(split)}${period ? ` ${esc(period[0])} to ${esc(period[1] || "now")}` : ""}</span> ${mockChip(source, "validation")}</h3>
      <div class="tbl-wrap"><table class="data"><thead><tr><th>Model</th>${COLS.map((c) => `<th title="${esc(c.hint || "")}">${esc(c.label)}</th>`).join("")}<th>Days &gt; 10 measured / called</th></tr></thead><tbody>
      ${order.map((m) => `<tr class="${m === shown ? "best" : ""}"><td>${esc(MODEL_LABEL[m] || m)}${m === shown ? ` <span class="tag">shown in charts</span>` : ""}</td>${COLS.map((c) => {
        const val = pick(models[m], c.k);
        const isBest = isNum(val) && best[c.label] === val;
        return `<td class="num">${cell(c, val)}${isBest ? " ★" : ""}</td>`;
      }).join("")}<td class="num">${isNum(models[m]?.obs_days_over10) ? `${fmtInt(models[m].obs_days_over10)} / ${fmtInt(models[m].pred_days_over10)}` : "–"}</td></tr>`).join("")}
      </tbody></table></div>`;
    // the two learned models in every period (train row = leave-one-year-out CV)
    const learned = ["gbm", "gbm_v2"].filter((m) => Object.values(s.splits).some((sp) => sp?.[m]));
    if (learned.length) {
      html += `<h4 class="h4">Our models in every period <span class="muted">· the training row is the leave-one-year-out score, not the in-sample fit</span></h4>
      <div class="tbl-wrap"><table class="data"><thead><tr><th>Period</th><th>Model</th>${COLS.map((c) => `<th>${esc(c.label)}</th>`).join("")}</tr></thead><tbody>
      ${["train", "test", "live"].filter((sp) => s.splits[sp]).flatMap((sp) => learned.filter((m) => s.splits[sp][m]).map((m) => `<tr${m === shown ? ' class="best"' : ""}><td>${esc(SPLIT_LABEL[sp] || sp)}</td><td>${m === "gbm" ? "v1" : "v2"}${m === "gbm_v2" && sp !== "train" ? " <span class=\"muted\">(post-hoc)</span>" : ""}</td>${COLS.map((c) => `<td class="num">${cell(c, pick(s.splits[sp][m], c.k))}</td>`).join("")}</tr>`)).join("")}
      </tbody></table></div>`;
    }
    const b13 = s.raw?.v2?.blind_2013;
    if (b13 && isNum(b13.obs_days_over10)) html += `<p class="fine">Pre-registered blind check on 2013 (the flush after the 2012 drought, held out before v2 was fitted): measured ${fmtInt(b13.obs_days_over10)} days above 10 mg/L, v2 called ${fmtInt(b13.v2?.pred_days_over10)}${isNum(b13.v2?.NSE) ? ` (NSE ${fmt(b13.v2.NSE, 2)})` : ""}.</p>`;
  }
  if (!sites.length) html += "<p>Validation results are not available yet.</p>";
  html += `<p class="fine">★ = best in column. Models learn from 2016–2022 and are scored on 2023–2025, which they never saw. v2 was designed after seeing the 2025 miss, so its test and live scores are post-hoc. NSE and KGE: 1 is perfect, 0 is no better than the average. CSI: correctly called days above 10 mg/L among all called or measured ones. Persistence uses last week's measurement, so it is a forecast, not an explanation.</p>`;
  box.innerHTML = html;

  // ---- outlook skill
  const os = v?.outlook_skill || {};
  const osSites = Object.keys(os);
  const oBox = document.getElementById("outlook-val");
  if (osSites.length) {
    const leads = [1, 3, 7, 10, 14];
    oBox.innerHTML = `<p>The outlook starts from the latest USGS measurement and uses NASA POWER soil wetness and rain to date and satellite bare cropland. <strong>No weather forecast is used.</strong> Scored on 2023–25 against "no change" (persistence).</p>
      <div class="tbl-wrap"><table class="data"><thead><tr><th>Gauge</th><th>Measure</th>${leads.map((h) => `<th>${h} day${h > 1 ? "s" : ""}</th>`).join("")}</tr></thead><tbody>
      ${osSites.flatMap((site) => {
        const name = esc((v.sites?.[site]?.name || site).split(",")[0].replace(/ at .*/, ""));
        const g = (h, k) => os[site]?.[`h${h}`]?.gbm?.[k];
        const sk = (x) => (isNum(x) ? `${x >= 0 ? "+" : "−"}${Math.abs(Math.round(x * 100))}%` : "–");
        return [
          `<tr><td>${name}</td><td>Error vs "no change" (squared error skill)</td>${leads.map((h) => `<td class="num">${sk(g(h, "skill_vs_persistence_mse"))}</td>`).join("")}</tr>`,
          `<tr><td></td><td>Chance above 10 mg/L vs "no change" (Brier skill)</td>${leads.map((h) => { const x = g(h, "brier_skill_vs_persistence"); return `<td class="num${isNum(x) && x < 0.05 ? " noskill-t" : ""}">${sk(x)}</td>`; }).join("")}</tr>`,
          `<tr><td></td><td>80% band held the measured value</td>${leads.map((h) => `<td class="num">${isNum(g(h, "coverage80")) ? Math.round(g(h, "coverage80") * 100) + "%" : "–"}</td>`).join("")}</tr>`,
        ];
      }).join("")}
      </tbody></table></div>
      <p class="fine">Positive = better than "no change". Greyed: below +5%, which we read as no real probability skill.${(() => { const none = osSites.filter((site) => { const b = os[site]?.h14?.gbm?.brier_skill_vs_persistence; return isNum(b) && b < 0.05; }).map((site) => (v.sites?.[site]?.name || site).split(",")[0].replace(/ at .*/, "")); return none.length ? ` At 14 days the chance above 10 mg/L has no probability skill at ${none.length === osSites.length ? "either gauge" : esc(none.join(", "))}, so the app fades the late days.` : ""; })()}</p>`;
  } else oBox.innerHTML = "<p>Outlook skill not available yet.</p>";

  // ---- proxy rules
  const th = data.scenarios?.thresholds;
  const cal = th?.calibration;
  const pBox = document.getElementById("proxy-val");
  if (cal) {
    const F = factsMap(data.facts);
    const row = (what, r, real) => (r ? `<tr><td>${what}</td><td class="num">${fmtInt(r.pred_days)}</td><td class="num">${fmtInt(r.true_days)}${real ? ` <span class="muted">${real}</span>` : ""}</td><td class="num">${fmtInt(r.hits)}</td><td class="num">${fmtInt(r.false_alarms)}</td><td class="num">${fmtInt(r.misses)}</td><td class="num">${fmt(r.f1, 2)}</td></tr>` : "");
    const pl = cal.plant || {}, bn = cal.ban || {};
    pBox.innerHTML = `<p>The utility's operating rules are not public, so plant and ban days in the replay come from simple rules on the measured rivers, fitted on 2025 and checked on 2026 without refitting.</p>
      <ul class="caveats"><li><strong>Plant:</strong> ${esc(th.plant_rule || pl.rule || "")}.</li><li><strong>Ban:</strong> ${esc(th.ban_rule || bn.rule || "")}.${bn.T_source ? ` Threshold ${esc(bn.T_source)}.` : ""}</li></ul>
      <div class="tbl-wrap"><table class="data"><thead><tr><th>Rule, year</th><th>Proxy days</th><th>Reported days</th><th>Hits</th><th>False alarms</th><th>Misses</th><th>Daily F1</th></tr></thead><tbody>
      ${row("Plant, 2025 (fit)", pl.fit_2025, F.plant_days_2025 ? link(F.plant_days_2025.url, "source") : "")}
      ${row("Plant, 2026 Jan–Jul (test)", pl.test_2026_jan_jul, F.plant_days_2026 ? link(F.plant_days_2026.url, "source") : "")}
      ${row("Ban, 2025 (fit)", bn.fit_2025, F.ban_days_2025 ? link(F.ban_days_2025.url, "source") : "")}
      ${row("Ban, 2026 (test)", bn.test_2026, F.ban_days_2026 ? link(F.ban_days_2026.url, "source") : "")}
      </tbody></table></div>
      <p class="fine">${esc(bn.caveat || "")} ${bn.fitted_start_threshold_check?.note ? esc(bn.fitted_start_threshold_check.note) : ""} ${th.cost_note ? `Cost: ${esc(th.cost_note)}` : ""}</p>`;
  } else pBox.innerHTML = "<p>Proxy-rule calibration not available yet.</p>";

  // ---- sources, caveats, provenance
  const m = data.meta;
  const src = m?.sources || [];
  document.getElementById("sources").innerHTML = src.length
    ? `<div class="tbl-wrap"><table class="data"><thead><tr><th>Dataset</th><th></th><th>Role in the app</th></tr></thead><tbody>${src.map((s) => `<tr><td>${link(s.url, s.name)}</td><td>${s.nasa ? `<span class="nasa">NASA</span>` : ""}</td><td>${esc(s.role || "")}</td></tr>`).join("")}</tbody></table></div>
       <p class="fine">Data through: ${Object.entries(m.data_through || {}).map(([k, d]) => `${esc(k.replace(/_/g, " ").toUpperCase())} ${esc(d)}`).join(" · ")}. Generated ${esc(m.generated_at || "")}. ${mockChip(source, "meta")}</p>`
    : "<p>Source list not available yet.</p>";
  const cav = [...(m?.caveats || [])];
  document.getElementById("caveats").innerHTML = cav.length ? cav.map((c) => `<li>${esc(c)}</li>`).join("") : "<li>Caveats not available yet.</li>";
  renderProvenance(store);
}

export function renderProvenance(store) {
  document.getElementById("provenance").innerHTML = provenanceTable(store.source);
}
