#!/usr/bin/env python3
"""m07_scenarios.py: "what if X% more upstream row-crop acres add a living cover?" -> model/out/scenarios.json

Run (from apps/field-to-faucet/):  python3 model/m07_scenarios.py      (~1 min, no network)
Re-run after any change to data/processed/nwis_daily.parquet, model/out/{features.parquet, models/, sensitivity.json,
metrics.json, basin_index_check.json} or docs/facts.json. No code change is needed.

Lever. X in {0, 5, ..., 50}% of ALL upstream corn/soy acres add a cereal-rye-type living cover (Oct-May), beyond the
~17% already covered statewide (X = 25 takes coverage from ~17% to ~42%), in both intake basins (Raccoon at Van Meter
05484500, Des Moines River at 2nd Ave 05482000).

Two evidence paths, combined in one Monte Carlo (common random numbers across levels and years):
  (a) trial prior   relative load cut on window days = X * e * s ; annual load cut dL = X * e * s * w
        e  INRS 2024 cereal-rye efficiency (facts.json inrs_cover_rye_pct.inrs_2024_update, SD from
           inrs_cover_rye_sd.inrs_2024_update), normal truncated to [0, 1], location solved so the mean is 28%.
        s  share of the river N load that comes from row-crop land, U[lo, hi] from basin_index_check.json
           (fields_model; 0.759-0.892).
        w  share of the year's measured (gap-filled) load that passes in the window cover crops act on: drainage
           from fall (Oct) to the next July. Daily: the trial cut applies on Oct-Jul days, not in Aug-Sep.
  (b) river-model sensitivity  daily relative change of the simulated concentration when the causal bare share is
        cut by X on Oct 15 - May 31 (river.perturb_cover + river.predict, v1 median model). Spread: Bayesian-
        bootstrap refits over training years (sensitivity.json, 5-95%) plus the spread between the median and the
        p10/p90 models' responses. NOT validated: the bare-soil features add almost no leave-one-year-out skill
        (sensitivity.json diagnostics.cv_rmse_log_gain_from_bare_features, ~0.002-0.005 ln units).
  Blend: equal-weight MIXTURE. Half the Monte Carlo draws use D_a(t), half D_b(t) (MIX_TRIAL). Inverse-variance
        weights on the pooled 2016-2025 annual load cut are computed and reported only as a diagnostic (they would
        put most weight on (b), whose bootstrap spread omits its identification problem). Every level also carries
        a trials-only result (levels[].trials_only.avoided) so the unvalidated path's influence is visible.
Impact: the cut is applied as a RELATIVE change to the OBSERVED daily series, C'(t) = C_obs(t) * (1 - D(t)) (the
simulation misses the 2025-26 level, so simulated absolute levels are never used for counts). Flow is unchanged.
Counts per calendar year, p50 / p10 / p90 over draws; "avoided" = baseline minus scenario computed inside each draw.

Operating rules are proxies (the utility's rules are not public), fitted on 2025 and tested on 2026 without refit:
  plant: 7-day trailing mean of <aggregate of the two rivers> > T  (aggregate in {higher, average, lower} and T
         chosen by daily F1 against the reported 2025 run days)
  ban:   Jun-Aug demand season AND plant on AND the lower river's 7-day mean > 10 mg/L (CIWW's stated lift rule:
         at least one source <= 10 mg/L; fact ban_lift_rule). A start threshold fitted to 2025 is reported as a check.
  Plant days counted: in years with reported run dates (2025, 2026; PLANT_RUNS) a plant day is a day the proxy says
         "on" AND the real plant ran (pl & truth), so avoided plant days are only days the plant really ran that
         the scenario would switch off. Other years have no run dates and use the proxy alone. Proxy-only counts
         are kept as plant_days_proxy (diagnostic).
Cost: plant days x operating cost per day ~ U[2025 O&M / 2025 plant days, cost per day at full capacity] (facts).
      No source gives a partial-operation daily cost (the ~$4k/day sometimes quoted is not on the CIWW page), so the
      range is kept; a lower-rate sensitivity uses Q1-2026 O&M / Q1-2026 run days (~$8.4k, both facts-derived).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats

APP = Path(__file__).resolve().parents[1]
PROC = APP / "data" / "processed"
OUT = APP / "model" / "out"
FACTS = APP / "docs" / "facts.json"
sys.path.insert(0, str(APP / "model"))

SITES = {"05484500": "raccoon", "05482000": "desmoines"}
SITE_NAMES = {"05484500": "Raccoon River at Van Meter", "05482000": "Des Moines River at 2nd Ave, Des Moines"}
PRIMARY = "05484500"
LEVELS = list(range(0, 55, 5))
YEARS = list(range(2016, 2027))
REPLAY_YEARS = [2025, 2026]
POOL_YEARS = list(range(2016, 2026))     # complete years used for the blend weights
N_DRAWS = 4000
SEED = 20261114
MCL = 10.0
ROLL = 7                                 # days in the trailing mean of the proxy rules
ROLL_MIN = 4                             # minimum measured days inside that window
LEAD = 14                                # lead-in days so the rolling mean is defined on Jan 1
CFS_MGL_TO_KG_DAY = 2.4466
KG_TO_LB = 1.0 / 0.453592
DEMAND_SEASON = (6, 8)                   # Jun-Aug (ban proxy)
TRIAL_WINDOW_OFF_MONTHS = (8, 9)         # Aug-Sep: no living-cover effect on drainage (Oct-Jul window)
PLANT_T_GRID = np.round(np.arange(8.0, 13.0001, 0.1), 2)
PLANT_T_TOL = 0.025                      # thresholds within this F1 of the best (2025) are drawn in the Monte Carlo
BAN_T_GRID = np.round(np.arange(9.0, 15.0001, 0.25), 2)
AGGS = {"higher": np.fmax, "average": None, "lower": np.fmin}

# Run windows that facts.json gives only in its claim text (structured values are the totals, checked at run time).
PLANT_RUNS = {
    2025: {"fact": "plant_days_2025", "runs": [("2025-04-10", "2025-04-18"), ("2025-04-28", "2025-08-08")]},
    2026: {"fact": "plant_days_2026", "runs": [("2026-01-06", "2026-03-02"), ("2026-03-09", "2026-07-23")]},
}
# The 2026 run ended Jul 23 and no fall restart was reported when facts were checked (fact notes); the 2026 test
# window is therefore Jan 1 - Jul 31, and Aug onward is reported separately as "unverified".
PLANT_TEST_END_2026 = "2026-07-31"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------------------- facts
def load_facts() -> dict:
    d = json.loads(FACTS.read_text())
    return {f["id"]: f for f in d["facts"] if f.get("verification") != "unverified"}


def fval(facts, fid):
    f = facts.get(fid)
    if f is None:
        raise KeyError(f"facts.json: {fid} missing or unverified")
    return f["value"]


def fref(facts, fid):
    f = facts[fid]
    return {"id": fid, "url": f.get("url"), "verification": f.get("verification")}


# ----------------------------------------------------------------------------- observed series
def _design(dates, lnq, years):
    doy = dates.dayofyear.to_numpy() / 365.25 * 2 * np.pi
    cols = [np.ones(len(dates)), lnq, lnq ** 2, np.sin(doy), np.cos(doy), np.sin(2 * doy), np.cos(2 * doy)]
    for y in years[1:]:
        cols.append((dates.year == y).astype(float))
    return np.column_stack(cols)


def fill_concentration(dates, c, q, obs):
    """Same gap filler as model/m05_fields.py (copied): ln C on ln Q, ln Q^2, two harmonics and a calendar-year
    level, plus residuals interpolated linearly in time. Used only for LOADS (counts use measured days only)."""
    lnq = np.log(np.clip(q, 1.0, None))
    X = _design(dates, lnq, sorted(set(dates.year)))
    lnc = np.log(np.clip(c, 0.05, None))
    beta, *_ = np.linalg.lstsq(X[obs], lnc[obs], rcond=None)
    pred = X @ beta
    t = np.arange(len(dates))
    res = np.interp(t, t[obs], (lnc - pred)[obs])
    return np.exp(pred + res)


def observed():
    nw = pd.read_parquet(PROC / "nwis_daily.parquet")
    nw["date"] = pd.to_datetime(nw["date"])
    start = pd.Timestamp("2015-10-01")
    end = nw["date"].max()
    idx = pd.date_range(start, end, freq="D")
    out = {}
    for site in SITES:
        g = nw[nw["site"] == site].set_index("date").reindex(idx)
        c = g["no3_mgL"].to_numpy(float)
        q = g["q_cfs"].interpolate(limit_direction="both").to_numpy(float)
        obs = np.isfinite(c)
        cf = np.where(obs, c, fill_concentration(idx, c, q, obs))
        out[site] = dict(c=c, q=q, obs=obs, load=cf * q * CFS_MGL_TO_KG_DAY, filled=~obs)
    return idx, out


# ----------------------------------------------------------------------------- proxy rules (work on 1-D or 2-D)
def roll_mean(a: np.ndarray, w: int = ROLL, minp: int = ROLL_MIN) -> np.ndarray:
    """Trailing mean over the last w days (inclusive) of the measured values; NaN where fewer than minp."""
    a = np.atleast_2d(a)
    v = np.nan_to_num(a, nan=0.0)
    n = np.isfinite(a).astype(float)
    cv = np.cumsum(v, axis=1)
    cn = np.cumsum(n, axis=1)
    cv = np.concatenate([np.zeros((a.shape[0], 1)), cv], axis=1)
    cn = np.concatenate([np.zeros((a.shape[0], 1)), cn], axis=1)
    T = a.shape[1]
    hi = np.arange(1, T + 1)
    lo = np.maximum(0, hi - w)
    s = cv[:, hi] - cv[:, lo]
    k = cn[:, hi] - cn[:, lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        m = np.where(k >= minp, s / np.maximum(k, 1), np.nan)
    return m


def agg2(a, b, how):
    if how == "average":
        with np.errstate(invalid="ignore"):
            return np.where(np.isfinite(a) & np.isfinite(b), 0.5 * (a + b), np.where(np.isfinite(a), a, b))
    return AGGS[how](a, b)


def plant_on(r7, d7, rule):
    with np.errstate(invalid="ignore"):
        return agg2(r7, d7, rule["agg"]) > rule["T"]


def ban_on(r7, d7, plant, season_mask, t_ban):
    with np.errstate(invalid="ignore"):
        return plant & season_mask[None, :] & (np.fmin(r7, d7) > t_ban)


def truth_mask(idx, runs):
    m = np.zeros(len(idx), bool)
    for a, b in runs:
        m |= (idx >= pd.Timestamp(a)) & (idx <= pd.Timestamp(b))
    return m


def agreement(pred, truth, sel):
    p, t = pred[sel], truth[sel]
    tp, fp, fn = int((p & t).sum()), int((p & ~t).sum()), int((~p & t).sum())
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else None
    return dict(pred_days=int(p.sum()), true_days=int(t.sum()), hits=tp, false_alarms=fp, misses=fn,
                f1=None if f1 is None else round(f1, 3))


def first_last(idx, m):
    w = np.where(m)[0]
    return [str(idx[w[0]].date()), str(idx[w[-1]].date())] if len(w) else None


def runs_of(idx, m):
    w = np.where(m)[0]
    if not len(w):
        return []
    out, s = [], w[0]
    for i, j in zip(w[:-1], w[1:]):
        if j != i + 1:
            out.append([str(idx[s].date()), str(idx[i].date())])
            s = j
    out.append([str(idx[s].date()), str(idx[w[-1]].date())])
    return out


def calibrate_rules(idx, O, facts):
    r7 = roll_mean(O["05484500"]["c"])[0]
    d7 = roll_mean(O["05482000"]["c"])[0]
    yr = idx.year.to_numpy()
    truth = {}
    for y, spec in PLANT_RUNS.items():
        m = truth_mask(idx, spec["runs"])
        n = int(m.sum())
        if n != fval(facts, spec["fact"]):
            raise ValueError(f"plant run windows for {y} give {n} days, facts {spec['fact']} = {fval(facts, spec['fact'])}")
        truth[y] = m
    sel25 = yr == 2025
    sel26 = (yr == 2026) & (idx <= pd.Timestamp(PLANT_TEST_END_2026))
    fall26 = (yr == 2026) & (idx > pd.Timestamp(PLANT_TEST_END_2026))
    cands = []
    for agg in AGGS:
        for T in PLANT_T_GRID:
            p = plant_on(r7[None], d7[None], dict(agg=agg, T=T))[0]
            a = agreement(p, truth[2025], sel25)
            cands.append((a["f1"], -abs(a["pred_days"] - a["true_days"]), -T, agg, float(T), a))
    best_by_agg = {}
    for c in cands:
        if c[3] not in best_by_agg or c[:3] > best_by_agg[c[3]][:3]:
            best_by_agg[c[3]] = c
    best = max(best_by_agg.values(), key=lambda c: c[:3])
    rule = dict(agg=best[3], T=best[4])
    plant_obs = plant_on(r7[None], d7[None], rule)[0]
    t_set = sorted(c[4] for c in cands if c[3] == rule["agg"] and c[0] is not None and c[0] >= best[0] - PLANT_T_TOL)
    rule["T_set"] = t_set
    alts = {}
    for agg, c in best_by_agg.items():
        p = plant_on(r7[None], d7[None], dict(agg=agg, T=c[4]))[0]
        alts[agg] = dict(T=c[4], fit_2025=c[5], test_2026_jan_jul=agreement(p, truth[2026], sel26),
                         aug_nov_2026_pred_days=int(p[fall26].sum()))
    plant_cal = dict(
        rule=f"plant runs when the 7-day mean of the {rule['agg']} of the two rivers' measured nitrate exceeds {rule['T']:.1f} mg/L",
        agg=rule["agg"], T_mgL=rule["T"], window_days=ROLL, min_measured_days=ROLL_MIN,
        T_uncertainty=dict(drawn_from=t_set, why=(f"every threshold whose 2025 daily F1 is within {PLANT_T_TOL} of the best "
                                                  "fits 2025 about equally well, so the Monte Carlo draws T uniformly from them")),
        fit_2025=agreement(plant_obs, truth[2025], sel25),
        fit_2025_runs=runs_of(idx, plant_obs & sel25),
        true_2025_runs=[list(r) for r in PLANT_RUNS[2025]["runs"]],
        test_2026_jan_jul=agreement(plant_obs, truth[2026], sel26),
        test_2026_runs=runs_of(idx, plant_obs & sel26),
        true_2026_runs=[list(r) for r in PLANT_RUNS[2026]["runs"]],
        aug_nov_2026_pred_days=int(plant_obs[fall26].sum()),
        aug_nov_2026_note=("No fall-2026 restart of the facility had been reported when facts were checked "
                           "(facts.json plant_days_2026 notes), so these proxy days are probably false alarms; "
                           "they are unverified either way."),
        selection="aggregate and T chosen by daily F1 on 2025 only (ties: day count closest to 112, then lower T); 2026 never used for fitting",
        alternatives=alts,
        sources=[fref(facts, PLANT_RUNS[2025]["fact"]), fref(facts, PLANT_RUNS[2026]["fact"])])
    # --- ban proxy
    season = (idx.month >= DEMAND_SEASON[0]) & (idx.month <= DEMAND_SEASON[1])
    t_ban = float(fval(facts, "ban_lift_rule"))
    btruth = {}
    for y in (2025, 2026):
        s0 = pd.Timestamp(fval(facts, f"ban_{y}_start"))
        e0 = pd.Timestamp(fval(facts, f"ban_{y}_end"))
        h0 = pd.Timestamp(fval(facts, f"ban_{y}_residential_eased"))
        all_m = (idx >= s0) & (idx < e0)
        home_m = (idx >= s0) & (idx < h0)
        if int(all_m.sum()) != fval(facts, f"ban_{y}_days"):
            log(f"WARNING ban {y}: {int(all_m.sum())} days from dates vs fact {fval(facts, f'ban_{y}_days')}")
        btruth[y] = dict(all=all_m, homes=home_m)
    ban_obs = ban_on(r7[None], d7[None], plant_obs[None], season, t_ban)[0]
    sel = {y: yr == y for y in (2025, 2026)}
    # fitted alternative (check only): in the demand season, once the plant proxy is on and the lower river's 7-day
    # mean exceeds T_start, the ban stays on while the plant proxy stays on (no concentration condition after the
    # start). T_start chosen on 2025, then tested on 2026, to show whether a fitted start trigger transfers.
    lower7 = np.fmin(r7, d7)
    run_ok = plant_obs & season

    def ban_start_rule(T):
        out = np.zeros(len(idx), bool)
        on = False
        for i in range(len(idx)):
            if not run_ok[i]:
                on = False
            elif not on and lower7[i] > T:
                on = True
            out[i] = on
        return out

    fitc = []
    for T in BAN_T_GRID:
        a = agreement(ban_start_rule(T), btruth[2025]["all"], sel[2025])
        fitc.append((a["f1"], -abs(a["pred_days"] - a["true_days"]), -T, float(T)))
    Tfit = max(fitc)[3]
    bfit = ban_start_rule(Tfit)
    ban_cal = dict(
        rule=(f"lawn-watering ban when, in the {DEMAND_SEASON[0]:02d}-{DEMAND_SEASON[1]:02d} (Jun-Aug) demand season, "
              f"the plant proxy is on and the 7-day mean of BOTH rivers is above {t_ban:g} mg/L"),
        T_mgL=t_ban,
        T_source=("not fitted: CIWW's 2025 lift rule says at least one source must read 10 mg/L or less "
                  "(facts.json ban_lift_rule)"),
        fit_2025=agreement(ban_obs, btruth[2025]["all"], sel[2025]),
        fit_2025_vs_homes=agreement(ban_obs, btruth[2025]["homes"], sel[2025]),
        pred_2025_dates=first_last(idx, ban_obs & sel[2025]),
        true_2025=[str(fval(facts, "ban_2025_start")), str(fval(facts, "ban_2025_end")), "homes released " + str(fval(facts, "ban_2025_residential_eased"))],
        test_2026=agreement(ban_obs, btruth[2026]["all"], sel[2026]),
        test_2026_vs_homes=agreement(ban_obs, btruth[2026]["homes"], sel[2026]),
        pred_2026_dates=first_last(idx, ban_obs & sel[2026]),
        true_2026=[str(fval(facts, "ban_2026_start")), str(fval(facts, "ban_2026_end")), "homes released " + str(fval(facts, "ban_2026_residential_eased"))],
        fitted_start_threshold_check=dict(
            rule="Jun-Aug: the ban starts once the plant proxy is on and the lower river's 7-day mean exceeds T_start (fitted on 2025), and lasts while the plant proxy stays on",
            T_start_mgL=Tfit, pred_2025_dates=first_last(idx, bfit & sel[2025]), pred_2026_dates=first_last(idx, bfit & sel[2026]), fit_2025=agreement(bfit, btruth[2025]["all"], sel[2025]),
            test_2026=agreement(bfit, btruth[2026]["all"], sel[2026]),
            note=("A start threshold fitted to 2025 matches 2025 almost exactly but finds no ban at all in 2026, when "
                  "the ban came at lower nitrate (demand and capacity drove it). Over-fitted, so NOT used." if
                  agreement(bfit, btruth[2026]["all"], sel[2026])["pred_days"] < 0.5 * fval(facts, "ban_2026_days") else
                  "A start threshold fitted to 2025; compare its 2026 test with the unfitted rule. Not used (one-year fit).")),
        caveat=("A ban also depends on water demand (heat, lawn watering up to ~40% of summer demand), treatment "
                "capacity and the infiltration gallery, which this proxy cannot see. Ban counts use the "
                "all-customer Stage III window (2025: 56 days; homes 40). Treat ban-day changes as indicative."),
        sources=[fref(facts, k) for k in ("ban_lift_rule", "ban_2025_start", "ban_2025_end", "ban_2025_residential_eased",
                                          "ban_2025_days", "ban_2026_start", "ban_2026_end",
                                          "ban_2026_residential_eased", "ban_2026_days", "stage3_trigger_demand_pct",
                                          "lawn_watering_share_pct") if k in facts])
    return rule, t_ban, season, plant_cal, ban_cal


# ----------------------------------------------------------------------------- evidence paths
def trunc_draws(mean, sd, n, rng):
    """Normal truncated to [0, 1], location solved so the truncated mean equals `mean` (as m06)."""
    f = lambda mu: stats.truncnorm((0 - mu) / sd, (1 - mu) / sd, loc=mu, scale=sd).mean() - mean
    mu = optimize.brentq(f, -3.0, 1.0)
    a, b = (0 - mu) / sd, (1 - mu) / sd
    return stats.truncnorm.rvs(a, b, loc=mu, scale=sd, size=n, random_state=rng), mu


def learned_daily(idx, display_model):
    """Daily relative cut D_b(x, t) = 1 - cf/base of the median simulation, per site and level."""
    import river  # noqa: E402  (model/river.py; the river modeler keeps this API for any model version)
    feats = pd.read_parquet(OUT / "features.parquet")
    feats["date"] = pd.to_datetime(feats["date"])
    M = river.load_models()
    out = {}
    for site in SITES:
        g = feats[(feats.site == site) & (feats.date >= "2015-10-01")].sort_values("date").reset_index(drop=True)
        base = river.predict(g, site, M)["p50"].to_numpy()
        out[site] = {0: np.zeros(len(idx))}
        for x in LEVELS[1:]:
            cf = river.predict(river.perturb_cover(g, x / 100.0), site, M)["p50"].to_numpy()
            with np.errstate(invalid="ignore", divide="ignore"):
                d = np.clip(1.0 - cf / base, 0.0, 1.0)
            s = pd.Series(d, index=g.date).reindex(idx).ffill().fillna(0.0)
            out[site][x] = s.to_numpy()
    return out


def sens_block(sens, site, display_model):
    """The learned path uses the v1 GBM sensitivity (sensitivity.json 'gbm'). sensitivity.json also has a v2 block,
    but the modeler keeps the driver-only v1 model as the basis for relative what-ifs."""
    s = sens["sites"][site]
    key = "gbm"
    return s[key], s.get(f"{key}_p10", s.get("gbm_p10", {})), s.get(f"{key}_p90", s.get("gbm_p90", {}))


def learned_spread(sens, site, display_model):
    """Relative spread of the learned effect as a function of X: bootstrap 5-95% (relative to its median) and the
    SD of the median/p10/p90 models' responses (relative). Interpolated linearly in X between the fracs run."""
    med, q10, q90 = sens_block(sens, site, display_model)
    fr = sorted(float(f) for f in med)
    r_lo, r_hi, sd_q = [], [], []
    for f in fr:
        b = med[str(f)]["bootstrap"]["pct_change_window"]
        m50 = abs(b["p50"])
        mags = sorted([abs(b["lo"]), abs(b["hi"])])
        r_lo.append(mags[0] / m50)
        r_hi.append(mags[1] / m50)
        c = abs(med[str(f)]["central"]["pct_change_window"])
        rel = [1.0] + [abs(q[str(f)]["pct_change_window"]) / c for q in (q10, q90) if str(f) in q]
        sd_q.append(float(np.std(rel, ddof=1)) if len(rel) > 1 else 0.0)
    fr = np.array(fr) * 100
    return lambda x: (float(np.interp(x, fr, r_lo)), float(np.interp(x, fr, r_hi)), float(np.interp(x, fr, sd_q)))


def stat(v, nd=None):
    v = np.asarray(v, float)
    q = np.quantile(v, [0.5, 0.1, 0.9])
    r = (lambda z: round(float(z), nd)) if nd is not None else (lambda z: int(round(float(z))))
    return {"p50": r(q[0]), "lo": r(q[1]), "hi": r(q[2])}


def sig(x, n=3):
    if x is None or not np.isfinite(x) or x == 0:
        return 0 if x == 0 else None
    return float(f"{x:.{n}g}")


# ----------------------------------------------------------------------------- main
def main():
    t0 = time.time()
    facts = load_facts()
    metrics = json.loads((OUT / "metrics.json").read_text())
    dm_raw = metrics.get("display_model", "v1")
    display_by_site = {site: (dm_raw if isinstance(dm_raw, str) else
                              (dm_raw.get("sites", {}).get(site, {}).get("model", "v1") if isinstance(dm_raw, dict) else "v1"))
                       for site in SITES}
    display_model = display_by_site[PRIMARY]
    sens = json.loads((OUT / "sensitivity.json").read_text())
    bic = json.loads((OUT / "basin_index_check.json").read_text())
    rng = np.random.default_rng(SEED)
    log(f"display_model={display_model}")

    idx, O = observed()
    yr = idx.year.to_numpy()
    rule, t_ban, season, plant_cal, ban_cal = calibrate_rules(idx, O, facts)
    log(f"plant proxy: {plant_cal['rule']} | 2025 {plant_cal['fit_2025']} | 2026 test {plant_cal['test_2026_jan_jul']}")
    log(f"ban proxy: 2025 {ban_cal['fit_2025']} | 2026 test {ban_cal['test_2026']}")

    # --- path (a) inputs
    rye = facts["inrs_cover_rye_pct"]
    e_mean = rye.get("inrs_2024_update", {}).get("value", rye["value"]) / 100.0
    rsd = facts["inrs_cover_rye_sd"]
    e_sd = rsd.get("inrs_2024_update", {}).get("value", rsd["value"]) / 100.0
    e, e_mu = trunc_draws(e_mean, e_sd, N_DRAWS, rng)
    s_rng = bic["rowcrop_share_of_river_load"]
    s = rng.uniform(s_rng["lo"], s_rng["hi"], N_DRAWS)
    win_a = ~np.isin(idx.month.to_numpy(), TRIAL_WINDOW_OFF_MONTHS)
    w_year = {site: {} for site in SITES}
    for site in SITES:
        L = O[site]["load"]
        for y in YEARS:
            m = yr == y
            w_year[site][y] = float(L[m & win_a].sum() / L[m].sum())
    pool = np.isin(yr, POOL_YEARS)
    w_pool = {site: float(O[site]["load"][pool & win_a].sum() / O[site]["load"][pool].sum()) for site in SITES}

    # --- path (b) inputs
    log("learned path: perturbing cover and re-predicting ...")
    Db = learned_daily(idx, display_model)
    zb = {site: rng.standard_normal(N_DRAWS) for site in SITES}
    zq = {site: rng.standard_normal(N_DRAWS) for site in SITES}
    spread = {site: learned_spread(sens, site, display_model) for site in SITES}

    def k_draws(site, x):
        r_lo, r_hi, sdq = spread[site](x)
        z = zb[site]
        kb = np.where(z > 0, 1 + z * (r_hi - 1) / 1.645, 1 + z * (1 - r_lo) / 1.645)
        return np.clip(kb + zq[site] * sdq, 0.0, None)

    # --- real run days (years with reported run dates); plant days are counted only where the plant really ran
    TRUTH = {y: truth_mask(idx, spec["runs"]) for y, spec in PLANT_RUNS.items()}

    # --- cost per plant day. The facts give only the 2025 average ($1.6M / 112 days) and the full-capacity cost;
    # no quoted partial-operation cost exists (the CIWW page has no ~$4k/day figure), so the range is kept.
    cpd_lo = fval(facts, "plant_om_cost_2025_usd") / fval(facts, "plant_days_2025")
    cpd_hi = float(fval(facts, "plant_cost_per_day_usd"))
    cpd = rng.uniform(cpd_lo, cpd_hi, N_DRAWS)
    q1_26 = (idx >= pd.Timestamp("2026-01-01")) & (idx <= pd.Timestamp("2026-03-31"))
    q1_days = int((TRUTH[2026] & q1_26).sum())
    cpd_q1 = fval(facts, "plant_om_cost_2026_q1_usd") / q1_days if "plant_om_cost_2026_q1_usd" in facts else None
    rule_mc = dict(agg=rule["agg"], T=rng.choice(np.array(rule["T_set"]), N_DRAWS)[:, None])

    # --- blend weights (pooled 2016-2025 annual load cut, per site and level)
    weights, paths = {site: {} for site in SITES}, {site: {} for site in SITES}
    K = {site: {} for site in SITES}
    for site in SITES:
        L = O[site]["load"]
        for x in LEVELS:
            K[site][x] = k_draws(site, x) if x else np.zeros(N_DRAWS)
            if x == 0:
                weights[site][0] = None
                continue
            dla = x / 100.0 * e * s * w_pool[site]
            dlb_c = float((L[pool] * Db[site][x][pool]).sum() / L[pool].sum())
            dlb = dlb_c * K[site][x]
            va, vb = dla.var(), dlb.var()
            wa = (1 / va) / (1 / va + 1 / vb)
            weights[site][x] = dict(trial=round(float(wa), 3), learned=round(float(1 - wa), 3))
            paths[site][x] = dict(
                trial_load_cut_pct=stat(100 * dla, 2), learned_load_cut_pct=stat(100 * dlb, 2),
                learned_central_pct=round(100 * dlb_c, 2),
                blended_load_cut_pct=stat(100 * (wa * dla + (1 - wa) * dlb), 2))
    MIX_TRIAL = np.arange(N_DRAWS) % 2 == 0      # equal-weight mixture of the two evidence paths
    w25 = {site: weights[site][25] for site in SITES}
    log(f"weights at 25%: {w25}")

    # --- Monte Carlo engine
    def run_year(y, wmode="blend", keep_daily=False):
        m_year = yr == y
        i0 = max(0, np.where(m_year)[0][0] - LEAD)
        i1 = np.where(m_year)[0][-1] + 1
        sl = slice(i0, i1)
        inyr = m_year[sl]
        seas = season[sl]
        res, daily = {}, {}
        base = None
        for x in LEVELS:
            C, Ld = {}, {}
            for site in SITES:
                if x == 0:
                    D = np.zeros((N_DRAWS, i1 - i0))
                else:
                    Da = (x / 100.0) * (e * s)[:, None] * win_a[sl][None, :]
                    Dl = K[site][x][:, None] * Db[site][x][sl][None, :]
                    if wmode == "blend":
                        # Equal-weight MIXTURE: half the draws follow the trial path, half the learned path.
                        # Inverse-variance weights (reported as a diagnostic) put ~97% on the learned model only
                        # because its bootstrap spread omits its identification problem; a mixture keeps the
                        # estimate anchored to Iowa trials and the range honest.
                        D = np.where(MIX_TRIAL[:, None], Da, Dl)
                    else:
                        D = Da if wmode == "trial" else Dl
                    D = np.clip(D, 0.0, 1.0)
                C[site] = O[site]["c"][sl][None, :] * (1 - D)
                Ld[site] = O[site]["load"][sl][None, :] * (1 - D)
            r7, d7 = roll_mean(C["05484500"]), roll_mean(C["05482000"])
            pl = plant_on(r7, d7, rule_mc)
            bn = ban_on(r7, d7, pl, seas, t_ban)
            pl_count = (pl & TRUTH[y][sl][None, :]) if y in TRUTH else pl
            with np.errstate(invalid="ignore"):
                over_r = (C["05484500"][:, inyr] > MCL).sum(1)
                over_d = (C["05482000"][:, inyr] > MCL).sum(1)
            pdays = pl_count[:, inyr].sum(1)
            pdays_proxy = pl[:, inyr].sum(1)
            bdays = bn[:, inyr].sum(1)
            load_r = Ld["05484500"][:, inyr].sum(1) / 1000.0
            load_d = Ld["05482000"][:, inyr].sum(1) / 1000.0
            v = dict(days_over10=over_r, days_over10_dm=over_d, plant_days=pdays, plant_days_proxy=pdays_proxy,
                     cost_usd=pdays * cpd, cost_usd_q1_2026_rate=pdays * (cpd_q1 or np.nan),
                     ban_days=bdays, load_tN=load_r + load_d, load_tN_raccoon=load_r, load_tN_desmoines=load_d)
            if base is None:
                base = v
            v["lbN_kept"] = (base["load_tN"] - v["load_tN"]) * 1000.0 * KG_TO_LB
            lvl = {"x": x, "plant_days_basis": ("proxy on AND plant really ran (reported run dates)" if y in TRUTH
                                                else "proxy only (no reported run dates)")}
            for k in ("days_over10", "days_over10_dm", "plant_days", "plant_days_proxy", "ban_days"):
                lvl[k] = stat(v[k])
            lvl["cost_usd"] = {k: int(round(val, -3)) for k, val in stat(v["cost_usd"]).items()}
            for k in ("load_tN", "load_tN_raccoon", "load_tN_desmoines"):
                lvl[k] = {kk: int(round(val)) for kk, val in stat(v[k]).items()}
            lvl["lbN_kept"] = {kk: int(round(val, -4)) for kk, val in stat(v["lbN_kept"]).items()}
            av = {}
            for k in ("days_over10", "days_over10_dm", "plant_days", "plant_days_proxy", "ban_days"):
                av[k] = stat(base[k] - v[k])
            av["cost_usd"] = {kk: int(round(val, -3)) for kk, val in stat(base["cost_usd"] - v["cost_usd"]).items()}
            if cpd_q1:
                av["cost_usd_q1_2026_rate"] = {kk: int(round(val, -3)) for kk, val in
                                               stat(base["cost_usd_q1_2026_rate"] - v["cost_usd_q1_2026_rate"]).items()}
            av["load_tN"] = {kk: int(round(val)) for kk, val in stat(base["load_tN"] - v["load_tN"]).items()}
            av["lbN_kept"] = lvl["lbN_kept"]
            lvl["avoided"] = av
            res[x] = lvl
            if keep_daily:
                daily[x] = {site: np.quantile(C[site][:, inyr], [0.5, 0.1, 0.9], axis=0) if x else
                            np.vstack([C[site][0, inyr]] * 3) for site in SITES}
        return res, daily, idx[sl][inyr]

    by_year, replays, path_only = {}, {}, {}
    hist = {}
    for y in YEARS:
        res, daily, dts = run_year(y, keep_daily=y in REPLAY_YEARS)
        res_trial, _, _ = run_year(y, wmode="trial")
        for x in LEVELS:
            res[x]["trials_only"] = dict(avoided=res_trial[x]["avoided"])
        m = yr == y
        obs_r = O["05484500"]["c"][m]
        obs_d = O["05482000"]["c"][m]
        observed_block = dict(
            days_over10=int((obs_r[np.isfinite(obs_r)] > MCL).sum()),
            days_over10_dm=int((obs_d[np.isfinite(obs_d)] > MCL).sum()),
            measured_days=int(np.isfinite(obs_r).sum()), measured_days_dm=int(np.isfinite(obs_d).sum()),
            days_in_series=int(m.sum()),
            plant_days=fval(facts, f"plant_days_{y}") if f"plant_days_{y}" in facts else None,
            ban_days=(fval(facts, f"ban_{y}_days") if f"ban_{y}_days" in facts else (0 if y < 2025 else None)),
            ban_days_homes=(facts[f"ban_{y}_days"]["range"]["lo"] if f"ban_{y}_days" in facts else (0 if y < 2025 else None)),
            proxy_plant_days=res[0]["plant_days_proxy"]["p50"], proxy_ban_days=res[0]["ban_days"]["p50"],
            counted_plant_days=res[0]["plant_days"]["p50"],
            counted_plant_days_note=("proxy-on days that fall inside the reported run windows (the only days a "
                                     "scenario can avoid)" if y in TRUTH else "no reported run dates: proxy days"),
            load_tN=res[0]["load_tN"]["p50"],
            load_tN_raccoon=res[0]["load_tN_raccoon"]["p50"], load_tN_desmoines=res[0]["load_tN_desmoines"]["p50"],
        )
        if y < 2025:
            observed_block["ban_days_note"] = "2025's ban was CIWW's first-ever lawn-watering ban (facts.json ban_2025_start)"
        if y == 2026:
            observed_block["partial_year_through"] = str(idx[-1].date())
            observed_block["plant_days_note"] = "193 days through Jul 23; no fall restart reported when facts were checked"
        by_year[str(y)] = dict(site=PRIMARY, observed=observed_block, levels=[res[x] for x in LEVELS])
        if y in REPLAY_YEARS:
            dstr = [str(d.date()) for d in dts]
            rp = dict(year=y, site=PRIMARY, name=SITE_NAMES[PRIMARY], dates=dstr,
                      obs=[None if not np.isfinite(v) else round(float(v), 2) for v in obs_r],
                      base_p50=[None if not np.isfinite(v) else round(float(v), 2) for v in obs_r],
                      base_kind="observed",
                      by_level={}, by_level_lo={}, by_level_hi={}, other_sites={})
            for x in LEVELS:
                q = daily[x][PRIMARY]
                rp["by_level"][str(x)] = [None if not np.isfinite(v) else round(float(v), 2) for v in q[0]]
                rp["by_level_lo"][str(x)] = [None if not np.isfinite(v) else round(float(v), 2) for v in q[1]]
                rp["by_level_hi"][str(x)] = [None if not np.isfinite(v) else round(float(v), 2) for v in q[2]]
            od = {"name": SITE_NAMES["05482000"],
                  "obs": [None if not np.isfinite(v) else round(float(v), 2) for v in obs_d], "by_level": {}}
            for x in LEVELS:
                od["by_level"][str(x)] = [None if not np.isfinite(v) else round(float(v), 2) for v in daily[x]["05482000"][0]]
            rp["other_sites"]["05482000"] = od
            # display-model simulation for reference (never used for counts)
            rd_path = OUT / "v2" / "river_daily_v2.parquet"
            if display_model != "v2" or not rd_path.exists():
                rd_path = OUT / "river_daily.parquet"
            rd = pd.read_parquet(rd_path)
            rd["date"] = pd.to_datetime(rd["date"])
            sim = rd[rd.site == PRIMARY].set_index("date")["p50"].reindex(dts)
            rp["sim_p50"] = [None if not np.isfinite(v) else round(float(v), 2) for v in sim.to_numpy()]
            rp["sim_model"] = ("v2" if rd_path.name.endswith("_v2.parquet") else "v1") + \
                " driver-only simulation, for reference only (never used for counts)"
            if y in PLANT_RUNS:
                rp["plant_on_reported"] = [list(r) for r in PLANT_RUNS[y]["runs"]]
            rp["proxy_plant_on"] = runs_of(dts, plant_on(roll_mean(O["05484500"]["c"])[0][None],
                                                         roll_mean(O["05482000"]["c"])[0][None], rule)[0][m])
            replays[str(y)] = rp
            path_only[str(y)] = {}
            path_only[str(y)]["trial"] = {str(x): res_trial[x]["avoided"] for x in LEVELS if x}
            r2, _, _ = run_year(y, wmode="learned")
            path_only[str(y)]["learned"] = {str(x): r2[x]["avoided"] for x in LEVELS if x}
        hist[y] = res
        log(f"{y}: obs >10 {observed_block['days_over10']} | 25%: avoided days {res[25]['avoided']['days_over10']} "
            f"plant {res[25]['avoided']['plant_days']} ban {res[25]['avoided']['ban_days']} "
            f"$ {res[25]['avoided']['cost_usd']}")

    people = fval(facts, "water_people_served")
    adopt_now = facts.get("iowa_cover_share_pct")
    adopt_txt = f"~{adopt_now['value']:.0f}% (statewide)" if adopt_now else "current adoption"
    adopt_v = round(adopt_now["value"]) if adopt_now else 17
    x_definition = (f"X% of all upstream corn/soy acres add cover, beyond the ~{adopt_v}% already covered statewide "
                    f"(X = 25 takes coverage from ~{adopt_v}% to ~{adopt_v + 25}%)")
    # --- how much does the unvalidated river-model path drive the mixture? (2025, 25%)
    cv_gain = {site: sens["sites"][site]["diagnostics"].get("cv_rmse_log_gain_from_bare_features") for site in SITES}
    po25 = {m: path_only["2025"][m]["25"] for m in ("trial", "learned")}
    mix25 = hist[2025][25]["avoided"]
    lc = {site: (paths[site][25]["trial_load_cut_pct"]["p50"], paths[site][25]["learned_load_cut_pct"]["p50"]) for site in SITES}
    pd_t, pd_l, pd_m = po25["trial"]["plant_days"]["p50"], po25["learned"]["plant_days"]["p50"], mix25["plant_days"]["p50"]
    dominated = pd_l > 1.5 * max(pd_t, 1)
    dom_txt = (f"The mixture's plant-day and cost results lean on the river-model half: in 2025 at 25% it avoids "
               f"{pd_l} plant days against {pd_t} for trials only (mixture {pd_m}). Read 'trials only' as the "
               f"conservative, trial-anchored figure. " if dominated else
               f"In 2025 at 25% the two halves give {pd_t} (trials only) and {pd_l} (river model only) avoided plant "
               f"days; the mixture gives {pd_m}. ")
    # HLS winter-cover detection rate per crop year (fields module output; 2020 has no fall window, so 2021 on)
    try:
        fy = pd.read_parquet(PROC / "field_year.parquet", columns=["year", "winter_cover"])
        r = fy[fy.year >= 2021].groupby("year")["winter_cover"].mean() * 100
        hls_pct = dict(lo=round(float(r.min()), 1), hi=round(float(r.max()), 1),
                       by_year={str(k): round(float(v), 1) for k, v in r.items()},
                       source="data/processed/field_year.parquet winter_cover (notes/fields.md), focus-area fields, crop years 2021-2026",
                       note="lower bound on cover-crop use, not an adoption estimate")
    except Exception as ex:  # noqa: BLE001
        log(f"WARNING field_year.parquet unreadable ({ex}); using notes/fields.md 0.8-4.2%")
        hls_pct = dict(lo=0.8, hi=4.2, source="notes/fields.md", note="lower bound on cover-crop use, not an adoption estimate")
    hls_txt = (f"Satellite (HLS, 30 m) detects winter cover on only {hls_pct['lo']:.1f}-{hls_pct['hi']:.1f}% of fields "
               f"a year, against ~{adopt_v}% statewide adoption: it sees only cover that has grown enough by late fall "
               "or early spring, so it is a lower bound (many covers are drilled late or stay small).")
    method = (
        f"What-if replay on the MEASURED river. X = {x_definition}. Each day's nitrate is cut by a share taken half "
        f"from Iowa trial results (INRS 2024: cereal rye cuts drainage nitrate {e_mean:.0%} on average, SD "
        f"{e_sd:.0%}; applied Oct-Jul, scaled by the row-crop share of river nitrate) and half from a river-model "
        f"sensitivity (bare-soil features add no tested skill) to less bare soil (Oct 15-May 31). The headline is "
        f"this 50/50 mixture, shown next to 'trials only'. The river-model half is not validated: its bare-soil "
        f"features improve leave-one-year-out error by only {min(cv_gain.values()):.3f}-{max(cv_gain.values()):.3f} "
        f"(ln units), yet at 25% it cuts the annual load by {lc['05482000'][1]:.1f}% at the Des Moines River and "
        f"{lc['05484500'][1]:.1f}% at the Raccoon (trials: {lc['05484500'][0]:.1f}%). {dom_txt}"
        f"Plant and ban days use proxy rules fitted to 2025 and tested on 2026; in 2025 and 2026 a plant day counts "
        f"only if the plant really ran that day. Adopters are assumed to be typical fields; the river may take "
        f"more than one season to respond (legacy nitrate). {hls_txt}")
    sc = dict(
        generated_at=pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        module="m07_scenarios", display_model=display_by_site,
        learned_path_model="v1 GBM (model/models, sensitivity.json); relative changes only; no tested skill from bare-soil features",
        adoption_levels=LEVELS,
        x_definition=x_definition,
        hls_winter_cover_pct=hls_pct,
        lever=("X% of all upstream corn/soy acres (both intake basins) add a cereal-rye-type living cover Oct-May, "
               "beyond the ~17% already covered statewide"),
        headline=dict(
            shown="equal-weight mixture (levels[].avoided), with trials only (levels[].trials_only.avoided) alongside",
            why=("The mixture keeps both lines of evidence in the range. The river-model half has no tested skill "
                 "(bare-soil features barely change leave-one-year-out error), so trials-only is shown next to it "
                 "as the trial-anchored figure."),
            river_model_dominates_plant_days=bool(dominated),
            check_2025_25pct=dict(plant_days_trials_only=po25["trial"]["plant_days"], plant_days_river_model_only=po25["learned"]["plant_days"],
                                  plant_days_mixture=mix25["plant_days"], annual_load_cut_pct_p50={SITES[k]: dict(trials=v[0], river_model=v[1]) for k, v in lc.items()},
                                  cv_rmse_log_gain_from_bare_features={SITES[k]: v for k, v in cv_gain.items()})),
        people_served=people, people_served_source=fref(facts, "water_people_served"),
        method=method,
        method_detail=dict(
            n_draws=N_DRAWS, seed=SEED, quantiles="p50 = median; lo/hi = 10th/90th percentile of draws (8 in 10)",
            impact_basis=("relative change applied to the OBSERVED daily concentration, C'(t) = C_obs(t) x (1 - D(t)); "
                          "flow unchanged; counts on measured days only; loads use measured flow x gap-filled concentration"),
            avoided="computed inside each draw (baseline minus scenario), then summarised",
            plant_day_rule=("2025 and 2026 (reported run dates, facts plant_days_<year>): a plant day is a day the proxy "
                            "says 'on' AND the real plant ran, so avoided plant days are real run days the scenario "
                            "switches off. Aug-Nov 2026 proxy days (no reported run) never count. 2016-2024: no run dates, "
                            "proxy only. plant_days_proxy keeps the proxy-only count as a diagnostic."),
            plant_run_windows={str(y): [list(r) for r in spec["runs"]] for y, spec in PLANT_RUNS.items()},
            trials_only="levels[].trials_only.avoided: same engine with every draw on the trial path (a), for every year and level",
            hls_cover_detection=hls_txt,
            path_a_trial=dict(
                formula="daily cut on Oct-Jul days = X * e * s; annual load cut dL = X * e * s * w",
                e=dict(dist="normal truncated to [0,1], location solved so the mean equals the stated efficiency",
                       mean=round(e_mean, 3), sd=round(e_sd, 3), location=round(float(e_mu), 3),
                       draw_mean=round(float(e.mean()), 3), draw_p10_p90=[round(float(np.quantile(e, .1)), 3), round(float(np.quantile(e, .9)), 3)],
                       source=dict(rye["inrs_2024_update"], id="inrs_cover_rye_pct") if "inrs_2024_update" in rye else fref(facts, "inrs_cover_rye_pct")),
                s=dict(dist="uniform", lo=s_rng["lo"], hi=s_rng["hi"], source="model/out/basin_index_check.json rowcrop_share_of_river_load (notes/fields_model.md: 1 - INRS point share x row-crop share of land load)"),
                w=dict(definition="share of the calendar year's measured (gap-filled) load passing Jan-Jul and Oct-Dec, i.e. the fall-to-July drainage window cover crops act on",
                       pooled_2016_2025={site: round(w_pool[site], 3) for site in SITES},
                       by_year={site: {str(y): round(v, 3) for y, v in w_year[site].items()} for site in SITES})),
            path_b_learned=dict(
                definition="relative change of the simulated median concentration when the causal bare share is cut by X (relative) on Oct 15-May 31, all cover features recomputed (model/river.py perturb_cover + predict)",
                spread="bootstrap refits over training years (sensitivity.json, 5-95%, split-normal) + SD of the median/p10/p90 models' responses",
                caveat=sens.get("identification_caveat", "")[:600],
                skill=("bare-soil features add no tested skill: leave-one-year-out ln-RMSE gain "
                       + ", ".join(f"{SITES[k]} {v:.4f}" for k, v in cv_gain.items()) + " (sensitivity.json diagnostics)"),
                note="the bootstrap spread does not capture the identification problem (historic cover variation is seasonal), so inverse-variance weights favour this path; path-only results are reported for comparison"),
            blend="equal-weight mixture: 50% of Monte Carlo draws use the trial-prior path, 50% the learned-model path (so the range spans both lines of evidence); inverse-variance weights are reported only as a diagnostic because the learned path's bootstrap spread omits its identification problem",
            weights={site: {str(x): weights[site][x] for x in LEVELS if x} for site in SITES},
            load_cut_by_path={site: {str(x): paths[site][x] for x in LEVELS if x} for site in SITES},
            path_only_avoided=path_only,
        ),
        priors=[
            dict(name="Cereal rye cover crop: nitrate cut in field drainage (INRS 2024 update)", effect=-round(e_mean, 3),
                 range=[-round(float(np.quantile(e, .9)), 3), -round(float(np.quantile(e, .1)), 3)],
                 source="Iowa Nutrient Reduction Strategy Science Team, 2024 practice efficiencies, Table 1",
                 url=rye.get("inrs_2024_update", {}).get("url", rye.get("url"))),
            dict(name="Share of river nitrate from row-crop land", effect=round((s_rng["lo"] + s_rng["hi"]) / 2, 3),
                 range=[s_rng["lo"], s_rng["hi"]], source="INRS nonpoint 92% x CDL row-crop share (fields_model)",
                 url=facts["inrs_nonpoint_share_pct"]["url"] if "inrs_nonpoint_share_pct" in facts else None),
            dict(name="Learned river response, 25% less bare soil Oct 15-May 31 (Raccoon)",
                 effect=-round(paths[PRIMARY][25]["learned_central_pct"] / 100, 4),
                 range=[-paths[PRIMARY][25]["learned_load_cut_pct"]["hi"] / 100, -paths[PRIMARY][25]["learned_load_cut_pct"]["lo"] / 100],
                 source="Field to Faucet river model (NASA POWER + MODIS/HLS cover + USGS flow), sensitivity.json; bare-soil features add no tested skill", url=None),
        ],
        thresholds=dict(
            plant_on_mgL=rule["T"], plant_on_mgL_range=[min(rule["T_set"]), max(rule["T_set"])], plant_rule=plant_cal["rule"],
            ban_mgL=t_ban, ban_rule=ban_cal["rule"],
            cost_per_plant_day=dict(lo=int(round(cpd_lo)), hi=int(round(cpd_hi))),
            cost_per_plant_day_q1_2026=(None if cpd_q1 is None else dict(
                value=int(round(cpd_q1)), basis=f"Q1-2026 O&M $660k / {q1_days} Q1-2026 run days (facts plant_om_cost_2026_q1_usd, plant_days_2026)",
                use="lower-rate sensitivity only (avoided.cost_usd_q1_2026_rate)")),
            cost_note=("operating (O&M) cost only: 2025 O&M $1.6M / 112 days = low end; ~$16k/day at full capacity = high end. "
                       "Capital ($0.6M in 2025; ~$40M expansion) is not avoided in the short run. Avoided days are "
                       "shoulder-season days, when partial operation can cost less; no source gives a partial-operation "
                       "daily cost (CIWW says only that full capacity costs ~$16k/day), so the range is kept. "
                       + (f"Q1-2026 O&M per run day was ~${cpd_q1 / 1000:.1f}k (winter, partial operation); "
                          "avoided.cost_usd_q1_2026_rate uses that rate as a lower sensitivity." if cpd_q1 else "")),
            source=("Proxy operating rules fitted to 2025 CIWW plant/ban dates (KCCI, CIWW), tested on 2026; costs from "
                    "CIWW 'What is the Nitrate Removal Facility?'"),
            sources=[fref(facts, k) for k in ("plant_om_cost_2025_usd", "plant_days_2025", "plant_cost_per_day_usd",
                                              "plant_cost_2025_usd", "capital_nrf_expansion_cost_usd", "mcl_mgL") if k in facts],
            calibration=dict(plant=plant_cal, ban=ban_cal)),
        by_year=by_year,
        replay=replays["2025"],
        replays=replays,
        caveats=[
            "Legacy nitrate: soils and groundwater hold years of nitrate, so a change on fields takes more than one season to show in the river; results describe the effect once it has developed, replayed on that year's weather.",
            f"Current adoption is already ~{adopt_now['value']:.0f}% of Iowa corn+soy acres (statewide, {adopt_now['verification']}); X is a share of ALL upstream corn/soy acres ADDED on top (X = 25: ~{adopt_v}% -> ~{adopt_v + 25}%)." if adopt_now else "X is additional acres on top of current adoption.",
            hls_txt,
            "The river-model half of the mixture has no tested skill (bare-soil features barely change leave-one-year-out error); 'trials only' is shown alongside.",
            "Plant days avoided count only days the plant really ran (2025, 2026 reported run dates).",
            "Adopters are assumed to be typical fields; targeting leaky, tile-drained fields would do more, poor establishment less.",
            "Trial efficiencies are mean drainage-concentration cuts with a large SD (28 +/- 26%); the river-model response is weakly identified (historic cover variation is mostly seasonal).",
            "Plant and ban days come from proxy rules (the utility's rules are not public); 2026 test: see thresholds.calibration.",
            "Cost avoided is operating cost only; capital is not avoided in the short run.",
            "lb N kept = nitrate that would have reached the two gauges; on-farm retention is larger (in-stream removal not counted).",
            "2026 is a partial year (data through " + str(idx[-1].date()) + "); 2026 nitrate data are partly provisional.",
        ],
        inputs=dict(
            nwis_through=str(idx[-1].date()),
            mtimes={p.name: time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)) for p in
                    [PROC / "nwis_daily.parquet", OUT / "features.parquet", OUT / "sensitivity.json",
                     OUT / "metrics.json", OUT / "basin_index_check.json", FACTS]}),
    )
    (OUT / "scenarios.json").write_text(json.dumps(sc, separators=(",", ":"), allow_nan=False))
    log(f"wrote model/out/scenarios.json ({(OUT / 'scenarios.json').stat().st_size / 1e3:.0f} kB) in {time.time() - t0:.0f} s")

    # --- short report
    print("\n2025 / 2026 results (avoided vs today, p50 [p10-p90]):")
    for y in ("2025", "2026"):
        b = by_year[y]
        print(f" {y}: observed >10 {b['observed']['days_over10']} (DM {b['observed']['days_over10_dm']}), plant {b['observed']['plant_days']} "
              f"(proxy {b['observed']['proxy_plant_days']}), ban {b['observed']['ban_days']} (proxy {b['observed']['proxy_ban_days']})")
        for lv in b["levels"]:
            if lv["x"] in (10, 25, 50):
                a = lv["avoided"]
                f = lambda d: f"{d['p50']} [{d['lo']}-{d['hi']}]"
                print(f"   X={lv['x']:2d}%: days>10 {f(a['days_over10'])}  DM {f(a['days_over10_dm'])}  plant {f(a['plant_days'])}  "
                      f"$ {f(a['cost_usd'])}  ban {f(a['ban_days'])}  load t {f(a['load_tN'])}  lb kept {f(a['lbN_kept'])}")
        for mode in ("trial", "learned"):
            a = path_only[y][mode]["25"]
            print(f"   25% {mode}-only: days>10 {a['days_over10']} DM {a['days_over10_dm']} plant {a['plant_days']} "
                  f"(proxy-only {a['plant_days_proxy']}) $ {a['cost_usd']} ban {a['ban_days']} lb {a['lbN_kept']}")
        a = b["levels"][LEVELS.index(25)]["avoided"]
        print(f"   25% mixture: plant proxy-only {a['plant_days_proxy']}; $ at Q1-2026 rate {a.get('cost_usd_q1_2026_rate')}")
    print("weights (trial share) by level, Raccoon:", {x: weights[PRIMARY][x]["trial"] for x in LEVELS if x})
    print("weights (trial share) by level, Des Moines:", {x: weights["05482000"][x]["trial"] for x in LEVELS if x})


if __name__ == "__main__":
    main()
