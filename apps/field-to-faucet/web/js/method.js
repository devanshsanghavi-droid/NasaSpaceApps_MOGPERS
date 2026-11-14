// Method & evidence view: validation table, data sources, caveats, provenance of each data file.
import { esc, fmt, isNum, link } from "./util.js";
import { mockChip, provenanceTable } from "./data.js";

const MODEL_LABEL = {
  gbm: "Our model (satellite + weather drivers)", reservoir: "Two-reservoir nitrate model", climatology: "Climatology (average for the date)",
  persistence_7d: "Persistence (value 7 days earlier)", persistence_14d: "Persistence (value 14 days earlier)",
};
const COLS = [
  { k: ["NSE", "nse"], label: "NSE", hint: "1 = perfect, 0 = no better than the average", best: "max" },
  { k: ["KGE", "kge"], label: "KGE", hint: "1 = perfect", best: "max" },
  { k: ["RMSE", "rmse"], label: "RMSE mg/L", hint: "typical error", best: "min" },
  { k: ["MAE", "mae"], label: "MAE mg/L", best: "min" },
  { k: ["coverage80"], label: "80% band hit", hint: "should be near 0.80", pct: true },
  { k: ["CSI", "csi"], label: "Exceedance CSI", hint: "skill at catching days above 10 mg/L", best: "max" },
];
const pick = (o, keys) => { for (const k of keys) if (o && isNum(o[k])) return o[k]; return null; };

// Accepts {sites:{<site>:{name, by_split:{<split>:{<model>:{...}}}}}} or the raw metrics.json shape {<site>:{<split>:{<model>:{...}}}}
function normalize(v) {
  if (!v) return [];
  const sites = v.sites || v;
  return Object.entries(sites).filter(([, s]) => s && typeof s === "object").map(([site, s]) => {
    const splits = s.by_split || s.splits || Object.fromEntries(Object.entries(s).filter(([k, x]) => ["train", "test", "live"].includes(k) && x && typeof x === "object"));
    return { site, name: s.name || site, splits, rows: s.rows };
  }).filter((x) => Object.keys(x.splits || {}).length || x.rows);
}

export function renderMethod(store) {
  const { data, source } = store;
  const v = data.validation;
  const box = document.getElementById("validation");
  const sites = normalize(v);
  let html = "";
  if (Array.isArray(v?.lines) && v.lines.length) html += `<div class="val-lines">${v.lines.map((l) => `<p>${esc(l)}</p>`).join("")}</div>`;
  if (v?.crisis_2025?.text) html += `<p><strong>2025 crisis:</strong> ${esc(v.crisis_2025.text)}</p>`;
  for (const s of sites) {
    const split = s.splits.test ? "test" : Object.keys(s.splits)[0];
    const models = s.splits[split] || {};
    const order = Object.keys(models).sort((a, b) => (a === "gbm" ? -1 : b === "gbm" ? 1 : 0));
    const best = {};
    for (const c of COLS) {
      if (!c.best) continue;
      const vals = order.map((m) => pick(models[m], c.k)).filter(isNum);
      if (vals.length) best[c.label] = c.best === "max" ? Math.max(...vals) : Math.min(...vals);
    }
    const period = v?.splits?.[split] || v?.split?.[split];
    html += `<h3>${esc(s.name)} <span class="muted">· ${split === "test" ? "out-of-time test" : esc(split)}${period ? ` ${esc(period[0])} to ${esc(period[1])}` : ""}</span> ${mockChip(source, "validation")}</h3>
      <div class="tbl-wrap"><table class="data"><thead><tr><th>Model</th>${COLS.map((c) => `<th title="${esc(c.hint || "")}">${esc(c.label)}</th>`).join("")}</tr></thead><tbody>
      ${order.map((m) => `<tr class="${m === "gbm" ? "best" : ""}"><td>${esc(MODEL_LABEL[m] || m)}</td>${COLS.map((c) => {
        const val = pick(models[m], c.k);
        const isBest = isNum(val) && best[c.label] === val;
        return `<td class="num">${isNum(val) ? (c.pct ? Math.round(val * 100) + "%" : fmt(val, 2)) : "–"}${isBest ? " ★" : ""}</td>`;
      }).join("")}</tr>`).join("")}
      </tbody></table></div>`;
  }
  if (!html) html = "<p>Validation results are not available yet.</p>";
  html += `<p class="fine">★ = best in column. The model is trained on 2016–2022 and scored on 2023–2025, which it never saw, including the 2025 crisis. NSE and KGE: 1 is perfect. CSI: share of correctly called days above 10 mg/L among all called or observed exceedance days.</p>`;
  box.innerHTML = html;

  const m = data.meta;
  const src = m?.sources || [];
  document.getElementById("sources").innerHTML = src.length
    ? `<div class="tbl-wrap"><table class="data"><thead><tr><th>Dataset</th><th></th><th>Role in the app</th></tr></thead><tbody>${src.map((s) => `<tr><td>${link(s.url, s.name)}</td><td>${s.nasa ? `<span class="nasa">NASA</span>` : ""}</td><td>${esc(s.role || "")}</td></tr>`).join("")}</tbody></table></div>
       <p class="fine">Data through: ${Object.entries(m.data_through || {}).map(([k, d]) => `${esc(k.toUpperCase())} ${esc(d)}`).join(" · ")}. Generated ${esc(m.generated_at || "")}. ${mockChip(source, "meta")}</p>`
    : "<p>Source list not available yet.</p>";
  const cav = m?.caveats || [];
  document.getElementById("caveats").innerHTML = cav.length ? cav.map((c) => `<li>${esc(c)}</li>`).join("") : "<li>Caveats not available yet.</li>";
  document.getElementById("provenance").innerHTML = provenanceTable(source);
}
