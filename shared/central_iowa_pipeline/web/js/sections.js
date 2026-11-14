// Region-wide sections: hindcast, county policy tree, data sources / caveats.
import { esc, isNum, fmt, fmtInt, pct, strategyColor, prefersReducedMotion } from "./util.js";
import { typeLabel, strategyName, strategyShort } from "./panel.js";

const MODELS = [
  { key: "causal", label: "COUNTERFIELD causal model" },
  { key: "rule_baseline", label: "Rule-based selector" },
  { key: "correlational_ml", label: "Correlational ML" },
];

const yr = (r) => (Array.isArray(r) ? (r[0] === r[1] ? String(r[0]) : `${r[0]}-${r[1]}`) : "");

export function renderHindcast(app) {
  const box = document.getElementById("hindcast-body");
  const h = app.hindcast;
  if (!h) { box.innerHTML = `<p class="muted">Hindcast results not exported yet.</p>`; return; }
  const test = yr(h.test_years), train = yr(h.train_years);
  document.getElementById("hindcast-lede").textContent =
    `The model is frozen after ${train} and ranks strategies for each field type in ${test}. Then the realised outcomes are revealed next to a rule-based selector and a correlational machine-learning model.`;
  const m = h.metrics || {};
  const units = h.units || {};
  const metricCell = (mod) => {
    const v = m[mod.key] || {};
    const row = (label, val, tip) => `<div class="metric-row"${tip ? ` data-tip="${esc(tip)}"` : ""}><span>${label}</span><b>${val}</b></div>`;
    return `<div class="cell ${mod.key === "causal" ? "highlight" : ""}">
      <p class="eyebrow">${esc(mod.label)}</p>
      <div class="stat">${isNum(v.kendall_tau) ? fmt(v.kendall_tau, 2) : "n/a"}</div>
      <div class="stat-label">Kendall τ: agreement of its ranking with what happened (1 = perfect)</div>
      <div class="metric-rows">
        ${row("Top-1 regret", isNum(v.top1_regret) ? fmt(v.top1_regret, 2) + (units.top1_regret ? ` <span class="muted small">${esc(units.top1_regret)}</span>` : "") : "n/a", "How much worse its first choice did than the best choice, averaged over field types. Lower is better.")}
        ${row("Interval coverage", isNum(v.coverage) ? pct(v.coverage) : "n/a", units.coverage || "Share of intervals that contained the realised effect.")}
      </div>
    </div>`;
  };
  const byType = Array.isArray(h.by_type) ? h.by_type.filter((r) => r && Array.isArray(r.actual)) : [];
  const badShape = Array.isArray(h.by_type) && h.by_type.length > 0 && !byType.length;
  if (badShape) console.warn("[counterfield] hindcast.by_type has an unexpected shape", h.by_type[0]);
  const hits = Object.fromEntries(MODELS.map((mod) => [mod.key, byType.filter((r) => Array.isArray(r[mod.key]) && r[mod.key][0] === r.actual[0]).length]));
  const chip = (sid, cls = "") => `<span class="rk ${cls}"><span class="sw" style="background:${strategyColor(sid)}"></span>${esc(strategyShort(app, sid))}</span>`;
  const seq = (arr, actual, revealed) => `<div class="rank-seq">${(arr || []).map((sid, i) => chip(sid, revealed && actual ? (actual[i] === sid ? "hit" : "miss") : "")).join("")}</div>`;

  box.innerHTML = `<div class="grid cols-3">${MODELS.map(metricCell).join("")}</div>
    ${byType.length ? `<div class="hindcast-actions"><button class="btn primary" id="btn-hindcast">Press hindcast: reveal ${esc(test)}</button>
      <span class="small muted" id="hindcast-score"></span></div>
    <div style="overflow-x:auto"><table class="rank-table" id="rank-table">
      <thead><tr><th>Field type</th><th>What happened in ${esc(test)}</th>${MODELS.map((mod) => `<th>${esc(mod.label)}</th>`).join("")}</tr></thead>
      <tbody>${byType.map((r, i) => `<tr data-row="${i}">
        <td class="type">${esc(typeLabel(app, r.type_id))}${isNum(r.n_fields) ? `<div class="small muted">${fmtInt(r.n_fields)} fields</div>` : ""}</td>
        <td class="actual-cell hidden">${seq(r.actual)}</td>
        ${MODELS.map((mod) => `<td class="pred" data-model="${mod.key}">${seq(r[mod.key])}</td>`).join("")}
      </tr>`).join("")}</tbody></table></div>
    <p class="chart-note">Strategies listed best to worst. After the reveal, a solid outline means the model put that strategy in the right place; dashed means it did not. A tick marks a correct first choice.</p>`
    : badShape ? `<p class="muted">Per-type rankings exported in an unexpected shape (expected actual/causal/rule_baseline/correlational_ml arrays).</p>` : ""}`;

  const btn = box.querySelector("#btn-hindcast");
  if (!btn) return;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    const rows = [...box.querySelectorAll("tbody tr")];
    // Motion-as-content exception: the staggered reveal IS the demo moment. Instant under prefers-reduced-motion.
    const delay = prefersReducedMotion() ? 0 : 450;
    rows.forEach((tr, i) => setTimeout(() => {
      const r = byType[i];
      tr.querySelector(".actual-cell").classList.remove("hidden");
      tr.querySelectorAll("td.pred").forEach((td) => {
        const arr = r[td.dataset.model];
        const ok = Array.isArray(arr) && arr[0] === r.actual[0];
        td.innerHTML = seq(arr, r.actual, true) + `<span class="hit-mark ${ok ? "good" : "bad"}">${ok ? "✓ first choice right" : "✗ first choice wrong"}</span>`;
      });
      if (i === rows.length - 1) {
        box.querySelector("#hindcast-score").textContent =
          `First choice right: ${MODELS.map((mod) => `${mod.label.replace("COUNTERFIELD ", "")} ${hits[mod.key]}/${byType.length}`).join(" · ")}`;
        btn.textContent = "Revealed";
      }
    }, delay * (i + 1)));
  });
}

export function renderCounty(app) {
  const box = document.getElementById("county-body");
  const p = app.policy;
  if (!p || !Array.isArray(p.tree)) { box.innerHTML = `<p class="muted">Policy tree not exported yet.</p>`; return; }
  const v = p.value_vs_uniform || {};
  const unit = p.value_unit || "value per dollar";
  box.innerHTML = `<div class="grid cols-2" style="margin-bottom:24px">
      <div class="cell"><p class="eyebrow">Targeted vs. uniform cost-share</p>
        <div class="stat">${isNum(v.est) ? fmt(v.est, 2) + "×" : "n/a"}</div>
        <div class="stat-label">value of following the tree relative to paying for every practice everywhere${isNum(v.lo) ? ` (interval ${fmt(v.lo, 2)} to ${fmt(v.hi, 2)})` : ""}</div></div>
      <div class="cell"><p class="eyebrow">How to read it</p><p class="small" style="margin:0">Rules are checked top to bottom. Each field gets the first rule it matches. Value per dollar is ${esc(unit)}, scored with a doubly-robust policy evaluation on held-out fields.</p></div>
    </div>
    <div class="policy">${p.tree.map((n) => `<div class="prule">
      <span class="node">${esc(n.node)}</span>
      <span class="rule">${esc(n.rule)}</span>
      <span class="rec"><span class="swatch" style="display:inline-block;background:${strategyColor(n.recommended)};margin-right:6px;vertical-align:-1px"></span>${esc(strategyName(app, n.recommended))}<div class="small muted">${fmtInt(n.n)} fields</div></span>
      <span class="vpd">${isNum(n.value_per_dollar) ? fmt(n.value_per_dollar, 2) : "n/a"}<small>per $1</small></span>
    </div>`).join("")}</div>`;
}

export function renderAbout(app) {
  const box = document.getElementById("about-body");
  const meta = app.meta || {};
  const src = Array.isArray(meta.data_sources) ? meta.data_sources : [];
  const cav = Array.isArray(meta.caveats) ? meta.caveats : [];
  const files = Object.entries(app.source);
  box.innerHTML = `<div class="grid cols-2">
    <div class="cell"><p class="eyebrow">Data sources</p><ul class="sources">${src.map((s) => `<li>
      <span class="tag ${s.nasa ? "nasa" : ""}">${s.nasa ? "NASA" : "OTHER"}</span>
      <span><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a><br><span class="small muted">${esc(s.role || "")}</span></span></li>`).join("") || "<li>No sources listed.</li>"}</ul></div>
    <div class="cell"><p class="eyebrow">Caveats</p><ul class="caveats">${cav.map((c) => `<li>${esc(c)}</li>`).join("")}
      <li>Decision support, not a replacement for your agronomist. Thin and beyond-evidence results go to local review.</li></ul>
      <p class="eyebrow" style="margin-top:22px">Files behind this page</p>
      <table class="rank-table" style="margin-top:4px"><tbody>${files.sort().map(([k, v]) => `<tr><td class="num">${esc(k)}</td><td>${v === "data" ? "exported results" : v === "mock" ? "<strong>MOCK</strong> placeholder" : "missing"}</td></tr>`).join("")}</tbody></table>
    </div></div>`;
  document.getElementById("footer-generated").textContent = meta.generated_at ? `Data generated ${meta.generated_at}` : "";
}
