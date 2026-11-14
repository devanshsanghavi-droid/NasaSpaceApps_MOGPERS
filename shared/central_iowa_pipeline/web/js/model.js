// Client-side decision logic: outcome metadata, utility + Bradley-Terry preference learning,
// and climate transport of the yield effect along the CMIP6 heat trajectory.
// None of this changes an evidence number; it only re-weights and interpolates exported values.

import { isNum } from "./util.js";

export const OUTCOMES = [
  { key: "yield_pct", label: "Yield", unit: "%", sign: +1, nd: 1, speak: "percent" },
  { key: "erosion_t_ac", label: "Soil loss", unit: " t/ac/yr", sign: -1, nd: 1, speak: "tons per acre per year" },
  { key: "drought_loss_pct", label: "Drought-year loss", unit: "%", sign: -1, nd: 0, speak: "percent" },
  { key: "nitrate_pct", label: "Nitrate leaching", unit: "%", sign: -1, nd: 0, speak: "percent" },
  { key: "n2o_pct", label: "N₂O emissions", unit: "%", sign: -1, nd: 0, speak: "percent" },
];
export const PREF_KEYS = ["yield_pct", "erosion_t_ac", "drought_loss_pct", "nitrate_pct"];
export const DEFAULT_WEIGHTS = { yield_pct: 1, erosion_t_ac: 1, drought_loss_pct: 1, nitrate_pct: 1 };

// Scale each outcome by its spread across all types x strategies so weights are comparable.
export function outcomeScales(effects) {
  const scales = {};
  for (const { key } of OUTCOMES) {
    const vals = [];
    for (const t of Object.values(effects?.by_type || {})) {
      for (const s of Object.values(t)) {
        const v = s?.outcomes?.[key]?.est;
        if (isNum(v)) vals.push(v);
      }
    }
    if (vals.length < 2) { scales[key] = 1; continue; }
    const m = vals.reduce((a, b) => a + b, 0) / vals.length;
    const sd = Math.sqrt(vals.reduce((a, b) => a + (b - m) ** 2, 0) / (vals.length - 1));
    scales[key] = sd > 1e-9 ? sd : 1;
  }
  return scales;
}

const meta = Object.fromEntries(OUTCOMES.map((o) => [o.key, o]));

// Goodness-signed, scaled feature vector of a strategy's point estimates
export function features(outcomes, scales) {
  return PREF_KEYS.map((k) => {
    const v = outcomes?.[k]?.est;
    return isNum(v) ? (meta[k].sign * v) / (scales[k] || 1) : 0;
  });
}

export function utility(outcomes, weights, scales) {
  const x = features(outcomes, scales);
  return PREF_KEYS.reduce((acc, k, i) => acc + (weights[k] ?? 0) * x[i], 0);
}

// Returns strategy ids best -> worst. The array carries `.missing = [{sid, key}]` for any preference outcome
// whose estimate is null; those count as "no effect" (0) in the utility, and the UI says so.
export function rankStrategies(typeEffects, weights, scales) {
  if (!typeEffects) return Object.assign([], { missing: [] });
  const missing = [];
  for (const [sid, s] of Object.entries(typeEffects)) {
    if (sid === "S0") continue;
    for (const k of PREF_KEYS) if (!isNum(s?.outcomes?.[k]?.est)) missing.push({ sid, key: k });
  }
  const order = Object.keys(typeEffects)
    .map((sid) => ({ sid, u: utility(typeEffects[sid].outcomes, weights, scales) }))
    .sort((a, b) => b.u - a.u || a.sid.localeCompare(b.sid))
    .map((d) => d.sid);
  return Object.assign(order, { missing });
}

// Bradley-Terry / logistic choice model on attribute differences:
// P(A chosen over B) = sigmoid(w . (x_A - x_B)). MAP estimate with a Gaussian prior at the default weights,
// non-negative weights (more of a good thing is never worse).
export function fitWeights(answers, scales, prior = DEFAULT_WEIGHTS, lambda = 1.5, iters = 400, lr = 0.08) {
  const w0 = PREF_KEYS.map((k) => prior[k]);
  const w = w0.slice();
  const diffs = answers.map((a) => {
    const xa = features(a.chosen, scales), xb = features(a.other, scales);
    return xa.map((v, i) => v - xb[i]);
  });
  for (let it = 0; it < iters; it++) {
    const g = w.map((wi, i) => lambda * (wi - w0[i]));
    for (const d of diffs) {
      const z = d.reduce((acc, di, i) => acc + di * w[i], 0);
      const p = 1 / (1 + Math.exp(-z));
      for (let i = 0; i < w.length; i++) g[i] -= (1 - p) * d[i];
    }
    for (let i = 0; i < w.length; i++) w[i] = Math.max(0, w[i] - lr * g[i]);
  }
  return Object.fromEntries(PREF_KEYS.map((k, i) => [k, w[i]]));
}

// ---------------- climate transport ----------------
function runningMean(arr, k = 11) {
  const h = Math.floor(k / 2);
  return arr.map((_, i) => {
    let s = 0, n = 0;
    for (let j = Math.max(0, i - h); j <= Math.min(arr.length - 1, i + h); j++) if (isNum(arr[j])) { s += arr[j]; n++; }
    return n ? s / n : null;
  });
}

export function smoothedSeries(climate, scenario, variable = "hdd30") {
  const sc = climate?.scenarios?.[scenario];
  if (!sc || !Array.isArray(sc.years) || !Array.isArray(sc[variable])) return null;
  return { years: sc.years, raw: sc[variable], smooth: runningMean(sc[variable]) };
}

const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);

// Heat path H(y) for one scenario, built only from exported values:
//  - inside the scenario's own years (2035-2055 in the real export): 11-year running mean of hdd30
//  - before them: linear between an anchor (the CMIP6 historical mean at the centre of its years, ~2005,
//    or an optional observed `climate.recent = {year, hdd30}`) and the 2035-2055 window mean at 2045.
export function heatPath(climate, scenario) {
  const s = smoothedSeries(climate, scenario, "hdd30");
  if (!s) return null;
  const win = s.years.map((y, i) => (y >= 2035 && y <= 2055 ? s.raw[i] : null)).filter(isNum);
  const h45 = mean(win);
  if (!isNum(h45)) return null;
  let anchor = null;
  const rec = climate?.recent;
  if (rec && isNum(rec.year) && isNum(rec.hdd30)) anchor = { year: rec.year, h: rec.hdd30, label: `observed ${rec.year}` };
  else {
    const hist = climate?.historical || {};
    const hv = Array.isArray(hist.hdd30) ? hist.hdd30 : [];
    const hy = Array.isArray(hist.years) && hist.years.length === hv.length ? hist.years : null;
    const pairs = hv.map((v, i) => [hy ? hy[i] : null, v]).filter(([, v]) => isNum(v));
    if (pairs.length) {
      const yrs = pairs.map(([y]) => y).filter(isNum);
      const cy = yrs.length ? mean(yrs) : 2004.5;
      anchor = { year: cy, h: mean(pairs.map(([, v]) => v)), label: yrs.length ? `CMIP6 historical ${Math.min(...yrs)}-${Math.max(...yrs)} mean` : "CMIP6 historical mean" };
    }
  }
  const first = s.years.filter((y, i) => isNum(s.smooth[i]))[0];
  const H = (y) => {
    const i = s.years.indexOf(y);
    if (i >= 0 && isNum(s.smooth[i])) return s.smooth[i];
    if (anchor && y < first && 2045 > anchor.year) return anchor.h + ((y - anchor.year) / (2045 - anchor.year)) * (h45 - anchor.h);
    return null;
  };
  return { H, h45, anchor, firstYear: first, lastYear: s.years[s.years.length - 1] };
}

// Fraction of the way from today's climate to the 2035-2055 window, measured along the heat (hdd30) path.
export function transportFraction(climate, scenario, year, baseYear = 2025) {
  const fallback = Math.min(1, Math.max(0, (year - baseYear) / 20));
  const p = heatPath(climate, scenario);
  if (!p) return { f: fallback, method: "linear in time (no climate series)" };
  const h0 = p.H(baseYear), hy = p.H(year);
  if (!isNum(h0) || !isNum(hy) || Math.abs(p.h45 - h0) < 1e-6) return { f: fallback, method: "linear in time" };
  const f = Math.min(1, Math.max(0, (hy - h0) / (p.h45 - h0)));
  const viaCmip = "along the smoothed CMIP6 Jul-Aug heat trajectory";
  const method = year >= p.firstYear ? viaCmip
    : p.anchor ? `heat interpolated between the ${p.anchor.label} and the 2035-2055 CMIP6 mean; from ${p.firstYear} ${viaCmip}`
    : viaCmip;
  return { f, method };
}

export function transportEffect(today, clim, f) {
  if (!today || !clim || !isNum(clim.est)) return null;
  const lerp = (a, b) => (isNum(a) && isNum(b) ? a + f * (b - a) : null);
  return {
    est: lerp(today.est, clim.est), lo: lerp(today.lo, clim.lo), hi: lerp(today.hi, clim.hi),
    in_support: clim.in_support !== false,
    beyond: clim.in_support === false && f >= 0.5,
  };
}
