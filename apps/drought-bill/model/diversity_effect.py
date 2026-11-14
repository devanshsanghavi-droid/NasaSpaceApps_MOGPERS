"""Does higher crop-rotation diversity (CDL, 5-year window measured BEFORE the loss year) reduce drought loss
sensitivity? Observational estimates with the confounding diagnostics required by notes/MODEL_PLAN.md section 3.

Unit: county x year, corn (within-crop outcome isolates rotation from crop-mix effects); principal crops secondary.
Treatment D = div_shannon_5y of the CDL window ending t-1 (lagged, pre-determined). Window-end years 2012-2024, so
the lagged-D sample is 2013-2024 (2025 RMA provisional, excluded). Hazard H = NASA POWER hazard_z (JJA composite).
Output: model/outputs/diversity_effect.json
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from common import N_THREADS, OUT, PROC, save_json  # noqa: E402

warnings.filterwarnings("ignore")
BOWLES = {"citation": "Bowles TM et al. (2020) Long-term evidence shows that crop-rotation diversification increases "
                      "agricultural resilience to adverse growing conditions in North America. One Earth 2(3):284-293. "
                      "doi:10.1016/j.oneear.2020.02.007",
          "finding": "diversified rotations reduced maize yield losses in drought years by 14-90% across 11 long-term "
                     "North American trials (relative to simple rotations)",
          "range_pct": [14.0, 90.0],
          # field-level Shannon contrast used to translate the trial range into county diversity units:
          # 5-yr window of corn-soy (C S C S C: H = 0.673) vs a 4-crop rotation with small grain + forage
          # (C S O A C: H = 1.332). Delta = 0.66.
          "delta_shannon_field": 0.66}
HIGH = 1.0  # high-hazard years: hazard_z > 1
LOW = 0.0   # low-hazard placebo years: hazard_z < 0


def load():
    p = pd.read_parquet(OUT / "panel.parquet")
    cdl = pd.read_parquet(PROC / "cdl_county_year.parquet")
    keep = ["div_shannon_5y", "n_crops_5y", "share_3plus", "share_cont_corn", "corn_share", "share_perennial_5y",
            "share_small_grain_5y", "n_px"]
    c = cdl[["fips", "year"] + keep]
    lag = c.assign(year=c.year + 1).add_suffix("_lag").rename(columns={"fips_lag": "fips", "year_lag": "year"})
    cur = c.add_suffix("_cur").rename(columns={"fips_cur": "fips", "year_cur": "year"})
    d = p[(p.year <= 2024) & (p.liability_usd > 0)].copy()
    d = d.merge(lag, on=["fips", "year"], how="left").merge(cur, on=["fips", "year"], how="left")
    lpa = d[d.crop != "principal"].groupby("year").apply(lambda g: g.liability_usd.sum() / g.insured_acres.sum())
    d["w"] = d.liability_usd / d.year.map(lpa)
    d["lcr"] = d.lcr_drought.clip(lower=0)
    d["lcr_ex"] = d.lcr_excess.clip(lower=0)
    d["irr"] = d.irrigated_insured_share.fillna(d.irrigated_share).fillna(0)
    d["H"] = d.hazard_z
    d["H2"] = d.hazard_z_mjja
    d["sy"] = d.state_abbr + "_" + d.year.astype(str)
    return d


# ------------------------------------------------------------------ regression helpers
def fe_dummies(d, fe):
    """Full-rank FE dummies. County FE are nested in states, so with state-year FE the base year of every state is
    dropped (otherwise the county and state-year dummies are collinear and the clustered covariance breaks)."""
    parts = []
    if "fips" in fe:
        parts.append(pd.get_dummies(d["fips"], prefix="c", drop_first=True, dtype=float))
    if "sy" in fe:
        sy = pd.get_dummies(d["sy"], prefix="sy", dtype=float)
        if "fips" in fe:
            base = d.groupby("state_abbr").year.transform("min")
            drop = set(("sy_" + d.state_abbr + "_" + base.astype(str)).unique())
        else:
            drop = {sy.columns[0]}
        parts.append(sy.drop(columns=[c for c in sy.columns if c in drop]))
    return pd.concat(parts, axis=1)


def fe_ols(d, y, terms, fe=("fips", "sy"), w="w", cluster="fips"):
    d = d.dropna(subset=[y] + terms).copy()
    X = pd.concat([d[terms].astype(float), fe_dummies(d, fe)], axis=1)
    X = sm.add_constant(X, has_constant="add")
    m = sm.WLS(d[y].astype(float), X, weights=d[w] if w else None).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(d[cluster])[0]})
    return m, d


def ppml(d, y, terms, fe=("fips", "sy"), w="w", cluster="fips"):
    d = d.dropna(subset=[y] + terms).copy()
    # drop FE groups with all-zero outcome (perfectly predicted under PPML)
    for f in fe:
        pos = d.groupby(f)[y].transform("sum") > 0
        d = d[pos]
    X = pd.concat([d[terms].astype(float), fe_dummies(d, fe)], axis=1)
    X = sm.add_constant(X, has_constant="add")
    m = sm.GLM(d[y].astype(float), X, family=sm.families.Poisson(), var_weights=d[w] / d[w].mean()).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(d[cluster])[0]}, maxiter=300)
    return m, d


def lincomb(m, weights):
    names = list(weights)
    a = np.array([weights[n] for n in names])
    b = m.params[names].to_numpy()
    V = m.cov_params().loc[names, names].to_numpy()
    est = float(a @ b)
    se = float(np.sqrt(a @ V @ a))
    return {"est": est, "se": se, "ci95": [est - 1.96 * se, est + 1.96 * se], "p": float(2 * stats.norm.sf(abs(est / se)))}


def coef(m, n):
    return {"est": float(m.params[n]), "se": float(m.bse[n]),
            "ci95": [float(m.params[n] - 1.96 * m.bse[n]), float(m.params[n] + 1.96 * m.bse[n])],
            "p": float(m.pvalues[n])}


def interaction_model(d, y="lcr", D="Dc", H="H", fe=("fips", "sy"), extra=(), kind="ols"):
    """y ~ D + D x H + H x (aws, irr) + corn_share (+ x H) + FE. D is centred (Dc). Returns effect of D at mean H of
    high-hazard rows, at mean H of low-hazard rows, and the interaction coefficient."""
    d = d.copy()
    d["DH"] = d[D] * d[H]
    d["H_aws"] = d[H] * d.aws_c
    d["H_irr"] = d[H] * d.irr
    d["cs"] = d.corn_share_lag
    d["cs_H"] = d.cs * d[H]
    terms = [D, "DH", H, "H_aws", "H_irr", "cs", "cs_H"] + list(extra)
    if "fips" not in fe:
        terms += ["aws_c", "irr", "clim_prcp_c", "clim_edd_c"]
    m, dd = (fe_ols if kind == "ols" else ppml)(d, y, terms, fe=fe)
    hh = dd.loc[dd[H] > HIGH, H]
    hl = dd.loc[dd[H] < LOW, H]
    hbar_hi = float(np.average(hh, weights=dd.loc[hh.index, "w"]))
    hbar_lo = float(np.average(hl, weights=dd.loc[hl.index, "w"]))
    out = {"n": int(m.nobs), "n_counties": int(dd.fips.nunique()), "years": [int(dd.year.min()), int(dd.year.max())],
           "fe": list(fe), "kind": kind, "D": coef(m, D), "D_x_H": coef(m, "DH"),
           "effect_high_hazard": lincomb(m, {D: 1.0, "DH": hbar_hi}), "H_high_mean": hbar_hi,
           "effect_low_hazard": lincomb(m, {D: 1.0, "DH": hbar_lo}), "H_low_mean": hbar_lo,
           "mean_y_high_hazard": float(np.average(dd.loc[hh.index, y], weights=dd.loc[hh.index, "w"])),
           "mean_y_low_hazard": float(np.average(dd.loc[hl.index, y], weights=dd.loc[hl.index, "w"]))}
    for e in extra:
        out[e] = coef(m, e)
    if kind == "ols":
        out["df_resid"] = float(m.df_resid)
        out["t_DH"] = float(m.tvalues["DH"])
        out["_model"] = m
    return out


def rel_effect(o, kind, per=0.1):
    """Effect of +`per` Shannon on drought loss cost in high-hazard years, as % of the mean (OLS) or % change (PPML)."""
    e = o["effect_high_hazard"]
    if kind == "ols":
        f = lambda v: 100 * v * per / o["mean_y_high_hazard"]  # noqa: E731
    else:
        f = lambda v: 100 * (np.exp(v * per) - 1)  # noqa: E731
    return {"per_shannon": per, "est_pct": float(f(e["est"])), "ci95_pct": [float(f(e["ci95"][0])),
                                                                             float(f(e["ci95"][1]))]}


def robustness_value(t, df, q=1.0, alpha=0.05):
    """Cinelli & Hazlett (2020) robustness values for a coefficient with t-statistic t and residual df."""
    f = abs(t) / np.sqrt(df)
    rv_q = 0.5 * (np.sqrt(f ** 4 + 4 * f ** 2) - f ** 2) * 1.0 if q == 1.0 else None
    tcrit = stats.t.ppf(1 - alpha / 2, df - 1)
    fa = max(f - tcrit / np.sqrt(df - 1), 0)
    rv_qa = 0.5 * (np.sqrt(fa ** 4 + 4 * fa ** 2) - fa ** 2)
    return {"partial_r2_treatment_outcome": float(t ** 2 / (t ** 2 + df)), "rv_q1": float(rv_q),
            "rv_q1_alpha05": float(rv_qa)}


def benchmark_bound(m, treat, bench, kd=1.0, ky=1.0):
    """Cinelli-Hazlett bound: how big would the bias be from an unobserved confounder kd/ky times as strong as the
    observed covariate `bench` (with treat and outcome)? Uses partial R2s computed from t-stats of auxiliary fits."""
    # partial R2 of bench with outcome (given treat and the rest) from the main model
    df = m.df_resid
    t_y = m.tvalues[bench]
    r2yxj = t_y ** 2 / (t_y ** 2 + df)
    # partial R2 of bench with the treatment: regress treat on all other regressors
    X = m.model.exog
    names = list(m.model.exog_names)
    j = names.index(treat)
    Xo = np.delete(X, j, axis=1)
    wts = m.model.weights
    aux = sm.WLS(X[:, j], Xo, weights=wts).fit()
    jb = [n for n in names if n != treat].index(bench)
    t_d = aux.tvalues[jb]
    r2dxj = t_d ** 2 / (t_d ** 2 + aux.df_resid)
    r2dz = kd * r2dxj / (1 - r2dxj)
    r2zxj = kd * r2dxj ** 2 / ((1 - kd * r2dxj) * (1 - r2dxj))
    r2yz = ((np.sqrt(ky) + np.sqrt(r2zxj)) / np.sqrt(1 - r2zxj)) ** 2 * (r2yxj / (1 - r2yxj))
    r2yz = min(r2yz, 1.0)
    se = m.bse[treat]
    bias = np.sqrt(r2yz * r2dz / (1 - r2dz)) * se * np.sqrt(df)
    est = m.params[treat]
    adj = est - np.sign(est) * bias
    return {"benchmark": bench, "kd": kd, "ky": ky, "r2_treat_bench": float(r2dxj), "r2_outcome_bench": float(r2yxj),
            "bias_bound": float(bias), "adjusted_est": float(adj),
            "adjusted_ci95": [float(adj - 1.96 * se), float(adj + 1.96 * se)]}


# ------------------------------------------------------------------ DML
def dml(d, y="lcr", D="div_shannon_5y_lag", mundlak=False, forest=False):
    from econml.dml import CausalForestDML, LinearDML
    from lightgbm import LGBMRegressor

    d = d.dropna(subset=[y, D, "H", "aws0_150_mm", "corn_share_lag"]).copy()
    Wcols = ["aws0_150_mm", "nccpi", "irr", "clim_prcp_jja_mm", "clim_edd30_jja", "clim_gwetroot_jja",
             "corn_share_lag", "lon", "lat", "spi_jja", "spi_mj", "edd30_jja_anom", "gwetroot_jja_pct",
             "gwetroot_mj_pct", "year"]
    W = d[Wcols].copy()
    W = pd.concat([W, pd.get_dummies(d.state_abbr, prefix="st", dtype=float)], axis=1)
    if mundlak:
        W["D_county_mean"] = d.groupby("fips")[D].transform("mean")
        W["H_county_mean"] = d.groupby("fips")["H"].transform("mean")
        W["y_county_mean_other"] = (d.groupby("fips")[y].transform("sum") - d[y]) / (
            d.groupby("fips")[y].transform("count") - 1)
    W = W.fillna(W.median())
    mk = lambda: LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=40,  # noqa
                               subsample=0.8, subsample_freq=1, colsample_bytree=0.8, num_threads=N_THREADS,
                               verbose=-1)
    if forest:
        Xc = ["H", "aws0_150_mm", "irr", "clim_prcp_jja_mm", "clim_edd30_jja"]
        X = d[Xc].to_numpy()
        est = CausalForestDML(model_y=mk(), model_t=mk(), n_estimators=400, min_samples_leaf=40, cv=3,
                              random_state=0, n_jobs=N_THREADS)
    else:
        X = d[["H"]].to_numpy()
        est = LinearDML(model_y=mk(), model_t=mk(), cv=3, random_state=0)
    est.fit(d[y].to_numpy(), d[D].to_numpy(), X=X, W=W.to_numpy(), sample_weight=d.w.to_numpy(),
            groups=d.fips.to_numpy())
    out = {"n": int(len(d)), "mundlak": mundlak, "forest": forest}
    for nm, mask in [("high_hazard", d.H > HIGH), ("low_hazard", d.H < LOW), ("all", d.H > -99)]:
        inf = est.ate_inference(X[mask.to_numpy()])
        lo, hi = inf.conf_int_mean(alpha=0.05)
        mu = float(np.average(d.loc[mask, y], weights=d.loc[mask, "w"]))
        e = float(inf.mean_point)
        out[nm] = {"cate_per_unit_D": e, "ci95": [float(lo), float(hi)], "n": int(mask.sum()), "mean_y": mu,
                   "pct_per_0.1_D": 100 * e * 0.1 / mu, "pct_per_0.1_D_ci95": [100 * float(lo) * 0.1 / mu,
                                                                                 100 * float(hi) * 0.1 / mu]}
    try:
        out["first_stage_r2_treatment"] = float(np.mean(est.nuisance_scores_t))
        out["first_stage_r2_outcome"] = float(np.mean(est.nuisance_scores_y))
    except Exception:  # noqa: BLE001
        pass
    return out


# ------------------------------------------------------------------ main
TREATMENTS = {  # primary first (CDL module guidance: Shannon rewards evenness, so a clean corn-soy alternation
    # scores 0.673 and the "how many crops" measures match Bowles' 2-crop vs 3-5 crop contrast better)
    "share_3plus": {"col": "share_3plus", "unit": "share of cropland pixels with >= 3 crop classes in the 5-yr window",
                    "per": 0.1, "per_label": "+10 percentage points of cropland in 3+ crop rotations"},
    "n_crops_5y": {"col": "n_crops_5y", "unit": "mean distinct crop classes per pixel in the 5-yr window",
                   "per": 0.1, "per_label": "+0.1 crops per pixel"},
    "div_shannon_5y": {"col": "div_shannon_5y", "unit": "mean per-pixel Shannon entropy (5-yr window)",
                       "per": 0.1, "per_label": "+0.1 Shannon"},
}
PRIMARY = "share_3plus"


def prep(d0, crop, min_acres, col, lagname="lag"):
    d = d0[(d0.crop == crop) & (d0.insured_acres >= min_acres)].copy()
    d = d[d[f"{col}_{lagname}"].notna() & (d[f"n_px_{lagname}"] >= 500)]
    d["Draw"] = d[f"{col}_{lagname}"]
    d["Dc"] = d.Draw - d.Draw.mean()
    d["corn_share_lag"] = d[f"corn_share_{lagname}"]
    d["aws_c"] = (d.aws0_150_mm - 236) / 47
    d["clim_prcp_c"] = (d.clim_prcp_jja_mm - d.clim_prcp_jja_mm.mean()) / d.clim_prcp_jja_mm.std()
    d["clim_edd_c"] = (d.clim_edd30_jja - d.clim_edd30_jja.mean()) / d.clim_edd30_jja.std()
    return d


def describe(corn):
    cm = corn.groupby("fips").agg(D=("Draw", "mean"), lcr=("lcr", "mean"), aws=("aws0_150_mm", "first"),
                                  irr=("irr", "mean"), clim_prcp=("clim_prcp_jja_mm", "first"),
                                  clim_edd=("clim_edd30_jja", "first"), lon=("lon", "first"),
                                  state=("state_abbr", "first"), H=("H", "mean"), cc=("share_cont_corn_lag", "mean"),
                                  cs=("corn_share_lag", "mean"))
    sp = lambda a, b: float(stats.spearmanr(cm[a], cm[b], nan_policy="omit").correlation)  # noqa: E731
    within = corn.Draw - corn.groupby("fips").Draw.transform("mean")
    hi = corn[corn.H > HIGH]
    return {
        "n_county_years": int(len(corn)), "n_counties": int(corn.fips.nunique()),
        "years": [int(corn.year.min()), int(corn.year.max())],
        "D_mean": float(corn.Draw.mean()), "D_sd_total": float(corn.Draw.std()),
        "D_sd_between_counties": float(cm.D.std()), "D_sd_within_county": float(within.std()),
        "D_within_share_of_variance": float(within.var() / corn.Draw.var()),
        "D_p10_p50_p90": [float(x) for x in corn.Draw.quantile([.1, .5, .9])],
        "spearman_county_means": {"D_vs_mean_corn_lcr": sp("D", "lcr"), "D_vs_aws": sp("D", "aws"),
                                  "D_vs_irrigated_share": sp("D", "irr"), "D_vs_clim_jja_prcp": sp("D", "clim_prcp"),
                                  "D_vs_clim_edd30": sp("D", "clim_edd"), "D_vs_longitude": sp("D", "lon"),
                                  "D_vs_mean_hazard": sp("D", "H"), "D_vs_corn_share": sp("D", "cs"),
                                  "D_vs_share_cont_corn": sp("D", "cc")},
        "D_by_state_p10_p50_p90": {s: [float(x) for x in g.D.quantile([.1, .5, .9])] for s, g in cm.groupby("state")},
        "high_hazard_county_years": int((corn.H > HIGH).sum()),
        "high_hazard_by_year": {int(k): int(v) for k, v in hi.groupby("year").size().items()},
        "raw_spearman_D_lcr_high_hazard_years": float(stats.spearmanr(hi.Draw, hi.lcr).correlation),
    }


def run_treatment(d0, tname, do_dml=True, forest=False):
    T = TREATMENTS[tname]
    col, per = T["col"], T["per"]
    corn = prep(d0, "corn", 1000, col)
    out = {"treatment": tname, "unit": T["unit"], "per": per, "per_label": T["per_label"],
           "descriptives": describe(corn)}
    specs = {}
    specs["ols_stateyearFE_controls"] = interaction_model(corn, fe=("sy",))
    specs["ols_countyFE_stateyearFE"] = interaction_model(corn)
    specs["ppml_countyFE_stateyearFE"] = interaction_model(corn, kind="ppml")
    specs["ppml_stateyearFE_controls"] = interaction_model(corn, fe=("sy",), kind="ppml")
    specs["ols_countyFE_H_mjja"] = interaction_model(corn, H="H2")
    c4 = corn.copy()
    c4["w"] = 1.0
    specs["ols_countyFE_unweighted"] = interaction_model(c4)
    pr = prep(d0, "principal", 2000, col)
    specs["ols_countyFE_principal_crops"] = interaction_model(pr)
    c3 = prep(d0, "corn", 1000, col, lagname="cur")
    specs["ols_countyFE_contemporaneous_window_incl2012"] = interaction_model(c3)
    # overlap / common support
    q = corn.groupby("state_abbr").Draw.quantile([0.05, 0.95]).unstack()
    lo_cs, hi_cs = float(q[0.05].max()), float(q[0.95].min())
    inside = corn.Draw.between(lo_cs, hi_cs)
    Xc = sm.add_constant(pd.concat([pd.get_dummies(corn.sy, dtype=float, drop_first=True),
                                    corn[["aws_c", "irr", "clim_prcp_c", "clim_edd_c", "corn_share_lag"]]], axis=1)
                         .fillna(0))
    r2_ctrl = sm.OLS(corn.Draw, Xc).fit().rsquared
    Xf = sm.add_constant(pd.concat([fe_dummies(corn, ("fips", "sy")), corn[["corn_share_lag"]]], axis=1).fillna(0))
    r2_fe = sm.OLS(corn.Draw, Xf).fit().rsquared
    out["overlap"] = {"state_p05_p95": {s: [float(a), float(b)] for s, (a, b) in q.iterrows()},
                      "common_support_interval": [lo_cs, hi_cs] if lo_cs < hi_cs else None,
                      "share_rows_inside_by_state": inside.groupby(corn.state_abbr).mean().to_dict(),
                      "share_rows_inside_total": float(inside.mean()),
                      "r2_D_on_stateyearFE_and_controls": float(r2_ctrl),
                      "r2_D_on_countyFE_stateyearFE": float(r2_fe),
                      "residual_sd_D_after_countyFE": float(np.sqrt(1 - r2_fe) * corn.Draw.std())}
    if lo_cs < hi_cs and inside.sum() > 500:
        specs["ols_countyFE_common_support"] = interaction_model(corn[inside].copy())
    # placebos
    plac = {}
    lo = corn[corn.H < LOW]
    m, dd = fe_ols(lo, "lcr", ["Dc", "corn_share_lag"])
    plac["low_hazard_years_D_on_drought_lcr"] = {**coef(m, "Dc"), "n": int(m.nobs),
                                                 "mean_y": float(np.average(dd.lcr, weights=dd.w)),
                                                 "pct_per_unit": float(100 * per * m.params["Dc"] /
                                                                       np.average(dd.lcr, weights=dd.w))}
    hi = corn[corn.H > HIGH]
    m, dd = fe_ols(hi, "lcr", ["Dc", "corn_share_lag"])
    plac["high_hazard_years_only_D_on_drought_lcr_(contrast)"] = {**coef(m, "Dc"), "n": int(m.nobs),
                                                                  "mean_y": float(np.average(dd.lcr, weights=dd.w))}
    o = interaction_model(corn, y="lcr_ex")
    plac["excess_moisture_lcr_interaction_model"] = {k: v for k, v in o.items() if k != "_model"}
    c5 = corn.merge(d0[["fips", "year", f"{col}_lead5"]].drop_duplicates(["fips", "year"]), on=["fips", "year"],
                    how="left") if f"{col}_lead5" not in corn else corn.copy()
    c5 = c5[c5[f"{col}_lead5"].notna()].copy()
    c5["Dlead_c"] = c5[f"{col}_lead5"] - corn.Draw.mean()
    c5["DleadH"] = c5.Dlead_c * c5.H
    o = interaction_model(c5, extra=("Dlead_c", "DleadH"))
    plac["lead_test_window_t+1_to_t+5"] = {k: v for k, v in o.items() if k != "_model"}
    out["placebos"] = plac
    # sensitivity (Cinelli-Hazlett) on the FE interaction and the pooled interaction
    head = specs["ols_countyFE_stateyearFE"]
    pm = specs["ols_stateyearFE_controls"]
    out["sensitivity"] = {
        "fe_spec": {"coefficient": "D_x_H (county FE + state-year FE)", **robustness_value(head["t_DH"], head["df_resid"]),
                    "benchmark_H_x_irrigation_1x": benchmark_bound(head["_model"], "DH", "H_irr"),
                    "benchmark_H_x_irrigation_3x": benchmark_bound(head["_model"], "DH", "H_irr", kd=3, ky=3),
                    "benchmark_H_x_aws_1x": benchmark_bound(head["_model"], "DH", "H_aws")},
        "pooled_spec": {"coefficient": "D_x_H (state-year FE + controls)", **robustness_value(pm["t_DH"], pm["df_resid"]),
                        "benchmark_H_x_irrigation_1x": benchmark_bound(pm["_model"], "DH", "H_irr"),
                        "benchmark_H_x_irrigation_3x": benchmark_bound(pm["_model"], "DH", "H_irr", kd=3, ky=3)}}
    # DML
    if do_dml:
        dm = {}
        runs = [("linear_dml", {}), ("linear_dml_mundlak", {"mundlak": True})]
        if forest:
            runs += [("causal_forest_dml", {"forest": True}), ("causal_forest_dml_mundlak", {"forest": True, "mundlak": True})]
        for nm, kw in runs:
            try:
                dm[nm] = dml(corn.assign(Dtreat=corn.Draw), D="Dtreat", **kw)
                for k in ("high_hazard", "low_hazard", "all"):
                    e = dm[nm][k]
                    e["pct_per_unit"] = 100 * per * e["cate_per_unit_D"] / e["mean_y"]
                    e["pct_per_unit_ci95"] = [100 * per * e["ci95"][0] / e["mean_y"], 100 * per * e["ci95"][1] / e["mean_y"]]
                print(tname, nm, {k: round(dm[nm][k]["pct_per_unit"], 1) for k in ("high_hazard", "low_hazard")},
                      flush=True)
            except Exception as e:  # noqa: BLE001
                dm[nm] = {"error": repr(e)}
                print(tname, nm, "failed", e, flush=True)
        out["dml"] = dm
    # relative effects
    rel = {}
    for nm, o in specs.items():
        kind = "ppml" if nm.startswith("ppml") else "ols"
        rel[nm] = rel_effect(o, kind, per=per)
    out["relative_effects_high_hazard"] = rel
    for o in specs.values():
        o.pop("_model", None)
    out["specs"] = specs
    # robustness flags used by the verdict
    h, pp = specs["ols_countyFE_stateyearFE"], specs["ppml_countyFE_stateyearFE"]
    ld = plac["lead_test_window_t+1_to_t+5"]
    out["flags"] = {
        "fe_ols_protective_sig": h["effect_high_hazard"]["ci95"][1] < 0,
        "fe_ols_harmful_sig": h["effect_high_hazard"]["ci95"][0] > 0,
        "fe_ppml_protective_sig": pp["effect_high_hazard"]["ci95"][1] < 0,
        "fe_ppml_harmful_sig": pp["effect_high_hazard"]["ci95"][0] > 0,
        "pooled_protective_sig": specs["ols_stateyearFE_controls"]["effect_high_hazard"]["ci95"][1] < 0,
        "low_hazard_placebo_passes": plac["low_hazard_years_D_on_drought_lcr"]["p"] > 0.05,
        "excess_moisture_placebo_passes": plac["excess_moisture_lcr_interaction_model"]["D_x_H"]["p"] > 0.05,
        "lead_test_passes": ld["DleadH"]["p"] > 0.05 and ld["Dlead_c"]["p"] > 0.05,
        "robust_to_irrigation_strength_confounder": (lambda b: b["adjusted_ci95"][1] < 0 or b["adjusted_ci95"][0] > 0)(
            out["sensitivity"]["fe_spec"]["benchmark_H_x_irrigation_1x"]),
    }
    return out


def main():
    d0 = load()
    for t in TREATMENTS.values():  # lead (window t+1..t+5) for every treatment
        cdl = pd.read_parquet(PROC / "cdl_county_year.parquet")[["fips", "year", t["col"]]]
        d0 = d0.merge(cdl.assign(year=cdl.year - 5).rename(columns={t["col"]: f"{t['col']}_lead5"}),
                      on=["fips", "year"], how="left")
    res = {"question": "Does higher crop-rotation diversity (CDL 5-yr window ending t-1) reduce drought loss cost "
                       "(RMA drought indemnity / liability) for insured corn in county x year data, 2013-2024?",
           "hazard": "NASA POWER hazard_z (JJA composite of -SPI, EDD>30C, -root-zone wetness; z vs 1991-2020); "
                     "high-hazard = hazard_z > 1, low-hazard placebo = hazard_z < 0",
           "outcome": "corn lcr_drought (drought indemnity / liability), weighted by liability in acre-equivalents; "
                      "principal crops as secondary",
           "primary_treatment": PRIMARY, "bowles_2020": BOWLES, "treatments": {}}
    do_dml = "--no-dml" not in sys.argv
    for tname in TREATMENTS:
        res["treatments"][tname] = run_treatment(d0, tname, do_dml=do_dml,
                                                 forest=(tname in (PRIMARY, "div_shannon_5y")))
    P = res["treatments"][PRIMARY]
    # Bowles comparison in primary units: all simple-rotation cropland -> 3+ crops (delta share = 1 - mean share)
    per = TREATMENTS[PRIMARY]["per"]
    comp = {}
    for tname, tr in res["treatments"].items():
        h = tr["specs"]["ols_countyFE_stateyearFE"]
        pp = tr["specs"]["ppml_countyFE_stateyearFE"]
        if tname == "div_shannon_5y":
            dlt = BOWLES["delta_shannon_field"]
        elif tname == "share_3plus":
            dlt = 1.0 - tr["descriptives"]["D_mean"]
        else:
            dlt = 1.0  # one more crop class per pixel
        f_ols = lambda v: -100 * v * dlt / h["mean_y_high_hazard"]  # noqa: E731
        f_pp = lambda v: 100 * (1 - np.exp(v * dlt))  # noqa: E731
        comp[tname] = {"contrast": dlt,
                       "implied_reduction_pct_ols_fe": {"est": f_ols(h["effect_high_hazard"]["est"]),
                                                        "ci95": sorted(f_ols(x) for x in h["effect_high_hazard"]["ci95"])},
                       "implied_reduction_pct_ppml_fe": {"est": f_pp(pp["effect_high_hazard"]["est"]),
                                                         "ci95": sorted(f_pp(x) for x in pp["effect_high_hazard"]["ci95"])}}
    res["bowles_comparison"] = {"trial_range_pct": BOWLES["range_pct"], "by_treatment": comp,
                                "contrasts": "share_3plus: all remaining 2-crop cropland moved to 3+ crop rotations; "
                                             "n_crops_5y: +1 crop class per pixel; div_shannon_5y: +0.66 (corn-soy -> "
                                             "4-crop window)",
                                "note": "Positive = diversity reduces drought loss cost. Trials measure field yield-loss "
                                        "reduction; RMA loss cost is indemnity below a guarantee, aggregated over a "
                                        "county, so magnitudes are not directly comparable. Extrapolating a county "
                                        "slope to a 100% switch is far outside the observed within-county range."}
    fl = P["flags"]
    robust_protective = (fl["fe_ols_protective_sig"] and fl["fe_ppml_protective_sig"] and fl["low_hazard_placebo_passes"]
                         and fl["lead_test_passes"] and fl["excess_moisture_placebo_passes"]
                         and fl["robust_to_irrigation_strength_confounder"])
    res["robust_protective_effect_found"] = bool(robust_protective)
    rr, dlt = BOWLES["range_pct"], BOWLES["delta_shannon_field"]
    if robust_protective:
        e = P["specs"]["ppml_countyFE_stateyearFE"]["effect_high_hazard"]
        res["app_effect"] = {"source": "observational", "metric": PRIMARY,
                             "form": "multiplier m(s) = exp(theta * (s - s_now)) on drought loss cost",
                             "theta": {"est": e["est"], "lo": e["ci95"][0], "hi": e["ci95"][1]},
                             "label": "Observational estimate (corn, county FE + state-year FE PPML, high-hazard years)"}
    else:
        res["app_effect"] = {
            "source": "trial_prior_scenario", "metric": PRIMARY,
            "form": "fields moved from simple to 3+ crop rotations lose r less in drought years: county drought loss "
                    "multiplier m(s) = (1 - r*s) / (1 - r*s_now), s = share of cropland in 3+ crop rotations",
            "r": {"est": rr[0] / 100, "lo": 0.0, "hi": rr[1] / 100},
            "label": "Scenario assumption, not an estimate from the county data: field trials (Bowles et al. 2020) "
                     "found 14-90% smaller maize drought-year yield losses in diversified rotations. est = trial lower "
                     "bound (14%); lo = no effect (the county data show no robust effect); hi = trial upper bound (90%)."}
    res["verdict"] = verdict_text(res)
    save_json(res, OUT / "diversity_effect.json", 1)
    print(res["verdict"])


def _fmt_rel(r):
    return f"{r['est_pct']:+.1f}% (95% CI {r['ci95_pct'][0]:+.1f} to {r['ci95_pct'][1]:+.1f})"


def shannon_clause(res):
    S = res["treatments"]["div_shannon_5y"]
    fs = S["flags"]
    if not (fs["fe_ols_protective_sig"] or fs["pooled_protective_sig"]):
        return "The Shannon index shows no protective effect either."
    fails = []
    if not fs["fe_ppml_protective_sig"]:
        fails.append("the proportional (PPML) model")
    if not fs["lead_test_passes"]:
        fails.append("the lead test")
    if not fs["excess_moisture_placebo_passes"]:
        fails.append("the excess-moisture placebo")
    if not fs["robust_to_irrigation_strength_confounder"]:
        fails.append("a confounder as strong as irrigation")
    cr = S["relative_effects_high_hazard"]["ols_countyFE_contemporaneous_window_incl2012"]
    flip = cr["ci95_pct"][0] > 0
    txt = "The Shannon index does look protective in the linear FE model, but it does not survive " + (
        (", ".join(fails[:-1]) + " or " + fails[-1] if len(fails) > 1 else fails[0]) if fails else "(no failures)") + "."
    if flip:
        txt += " It also flips to a harmful sign when 2012 is added through the contemporaneous window."
    return txt


def verdict_text(res):
    P = res["treatments"][PRIMARY]
    S = res["treatments"]["div_shannon_5y"]
    N = res["treatments"]["n_crops_5y"]
    d = P["descriptives"]
    sc = d["spearman_county_means"]
    L = []
    L.append(f"Data: {d['n_county_years']} insured-corn county-years ({d['years'][0]}-{d['years'][1]}, "
             f"{d['n_counties']} counties), {d['high_hazard_county_years']} high-hazard (NASA POWER hazard_z > 1), "
             f"mostly 2021-2023; 2012 cannot be used with a lagged 5-year CDL window (CDL starts 2008).")
    L.append(f"Primary treatment share_3plus (share of cropland in 3+ crop rotations, window ending t-1): only "
             f"{100 * d['D_within_share_of_variance']:.0f}% of its variance is within county (within SD "
             f"{d['D_sd_within_county']:.3f} vs between {d['D_sd_between_counties']:.3f}). Across counties it tracks "
             f"crop mix and geography (Spearman with corn share {sc['D_vs_corn_share']:+.2f}, irrigation "
             f"{sc['D_vs_irrigated_share']:+.2f}, longitude {sc['D_vs_longitude']:+.2f}, mean corn drought loss cost "
             f"{sc['D_vs_mean_corn_lcr']:+.2f}).")
    r = P["relative_effects_high_hazard"]
    L.append(f"Effect on corn drought loss cost in high-hazard years per {P['per_label']}: county FE + state-year FE "
             f"OLS {_fmt_rel(r['ols_countyFE_stateyearFE'])}; PPML {_fmt_rel(r['ppml_countyFE_stateyearFE'])}; "
             f"pooled with controls {_fmt_rel(r['ols_stateyearFE_controls'])}. Negative = protective.")
    rn, rs = N["relative_effects_high_hazard"], S["relative_effects_high_hazard"]
    L.append(f"Secondary treatments (FE OLS): n_crops_5y per +0.1 crops {_fmt_rel(rn['ols_countyFE_stateyearFE'])}; "
             f"Shannon per +0.1 {_fmt_rel(rs['ols_countyFE_stateyearFE'])}, but Shannon PPML "
             f"{_fmt_rel(rs['ppml_countyFE_stateyearFE'])}.")
    fl, fs = P["flags"], S["flags"]
    yn = lambda b: "passes" if b else "FAILS"  # noqa: E731
    L.append(f"Diagnostics (primary): low-hazard placebo {yn(fl['low_hazard_placebo_passes'])}; excess-moisture "
             f"placebo {yn(fl['excess_moisture_placebo_passes'])}; lead test {yn(fl['lead_test_passes'])}; robust to a "
             f"confounder as strong as hazard x irrigation: {'yes' if fl['robust_to_irrigation_strength_confounder'] else 'no'} "
             f"(robustness value {P['sensitivity']['fe_spec']['rv_q1']:.3f}). Shannon: lead test "
             f"{yn(fs['lead_test_passes'])}, excess-moisture placebo {yn(fs['excess_moisture_placebo_passes'])}, "
             f"robust to irrigation-strength confounder: {'yes' if fs['robust_to_irrigation_strength_confounder'] else 'no'}.")
    cr = res["treatments"]["div_shannon_5y"]["relative_effects_high_hazard"]["ols_countyFE_contemporaneous_window_incl2012"]
    L.append(f"Adding 2012 via the contemporaneous Shannon window (includes the crop planted in year t, before the summer hazard): "
             f"{_fmt_rel(cr)} per +0.1 Shannon.")
    if res["robust_protective_effect_found"]:
        L.append("Verdict: a protective effect of rotation diversity in drought years survives fixed effects, placebos, "
                 "the lead test and the sensitivity benchmark; the app uses it with its CI.")
    else:
        harmful = fl["fe_ols_harmful_sig"] or fl["fe_ppml_harmful_sig"]
        L.append("Verdict: NO robust observational effect. " + (
            "The primary 'how many crops' measure is wrong-signed (more 3+ crop rotation, more corn drought loss) "
            "within counties. " if harmful else "The primary 'how many crops' measure is not distinguishable from zero. ")
            + shannon_clause(res) + " County-year insurance data with little within-county "
              "change in rotations cannot confirm (or rule out) the field-trial effect. The app therefore shows the "
              "Bowles et al. (2020) trial range (14-90% smaller drought-year maize yield losses) as a labelled "
              "scenario assumption, with the low end (no effect) included in its range.")
    return " ".join(L)


if __name__ == "__main__":
    main()
