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
    lead = c[["fips", "year", "div_shannon_5y"]].assign(year=c.year - 5).rename(
        columns={"div_shannon_5y": "div_shannon_5y_lead5"})
    d = p[(p.year <= 2024) & (p.liability_usd > 0)].copy()
    d = d.merge(lag, on=["fips", "year"], how="left").merge(cur, on=["fips", "year"], how="left").merge(
        lead, on=["fips", "year"], how="left")
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
def main():
    d0 = load()
    res = {"question": "Does higher rotation diversity (CDL 5-yr Shannon, window ending t-1) reduce drought loss "
                       "cost (RMA drought indemnity / liability) in county x year data?",
           "treatment": "div_shannon_5y of the CDL window ending t-1 (mean per-pixel Shannon entropy of crop classes)",
           "hazard": "NASA POWER hazard_z (JJA composite; z of -SPI, EDD>30C, -root-zone wetness)",
           "bowles_2020": BOWLES}
    corn = d0[(d0.crop == "corn") & (d0.insured_acres >= 1000)].copy()
    corn = corn[corn.div_shannon_5y_lag.notna() & (corn.n_px_lag >= 500)]
    mu_D = corn.div_shannon_5y_lag.mean()
    for dd in (corn,):
        dd["Dc"] = dd.div_shannon_5y_lag - mu_D
    corn["aws_c"] = (corn.aws0_150_mm - 236) / 47
    corn["clim_prcp_c"] = (corn.clim_prcp_jja_mm - corn.clim_prcp_jja_mm.mean()) / corn.clim_prcp_jja_mm.std()
    corn["clim_edd_c"] = (corn.clim_edd30_jja - corn.clim_edd30_jja.mean()) / corn.clim_edd30_jja.std()

    # ---------------- descriptives / confounding
    cm = corn.groupby("fips").agg(D=("div_shannon_5y_lag", "mean"), lcr=("lcr", "mean"), aws=("aws0_150_mm", "first"),
                                  irr=("irr", "mean"), clim_prcp=("clim_prcp_jja_mm", "first"),
                                  clim_edd=("clim_edd30_jja", "first"), lon=("lon", "first"),
                                  state=("state_abbr", "first"), H=("H", "mean"))
    sp = lambda a, b: float(stats.spearmanr(cm[a], cm[b]).correlation)  # noqa: E731
    within = corn.div_shannon_5y_lag - corn.groupby("fips").div_shannon_5y_lag.transform("mean")
    res["descriptives"] = {
        "n_county_years": int(len(corn)), "n_counties": int(corn.fips.nunique()),
        "years": [int(corn.year.min()), int(corn.year.max())],
        "D_mean": float(mu_D), "D_sd_total": float(corn.div_shannon_5y_lag.std()),
        "D_sd_between_counties": float(cm.D.std()), "D_sd_within_county": float(within.std()),
        "D_within_share_of_variance": float(within.var() / corn.div_shannon_5y_lag.var()),
        "D_p10_p50_p90": [float(x) for x in corn.div_shannon_5y_lag.quantile([.1, .5, .9])],
        "spearman_county_means": {"D_vs_mean_corn_lcr": sp("D", "lcr"), "D_vs_aws": sp("D", "aws"),
                                  "D_vs_irrigated_share": sp("D", "irr"), "D_vs_clim_jja_prcp": sp("D", "clim_prcp"),
                                  "D_vs_clim_edd30": sp("D", "clim_edd"), "D_vs_longitude": sp("D", "lon"),
                                  "D_vs_mean_hazard": sp("D", "H")},
        "D_by_state": {s: [float(x) for x in g.D.quantile([.1, .5, .9])] for s, g in cm.groupby("state")},
        "high_hazard_county_years": int((corn.H > HIGH).sum()),
        "high_hazard_by_year": {int(k): int(v) for k, v in corn[corn.H > HIGH].groupby("year").size().items()},
    }
    # pooled raw correlation of D with lcr in high-hazard years, then with controls (no FE)
    hi = corn[corn.H > HIGH]
    res["descriptives"]["raw_spearman_D_lcr_high_hazard"] = float(stats.spearmanr(hi.Dc, hi.lcr).correlation)

    specs = {}
    # (1) pooled, state-year FE + controls (between + within variation; confounded by geography)
    specs["ols_stateyearFE_controls"] = interaction_model(corn, fe=("sy",))
    # (2) county FE + state-year FE (within-county variation only) -- headline
    specs["ols_countyFE_stateyearFE"] = interaction_model(corn)
    # (3) PPML (proportional effect) with the same FE
    specs["ppml_countyFE_stateyearFE"] = interaction_model(corn, kind="ppml")
    specs["ppml_stateyearFE_controls"] = interaction_model(corn, fe=("sy",), kind="ppml")
    # (4) spring-inclusive hazard
    specs["ols_countyFE_H_mjja"] = interaction_model(corn, H="H2")
    # (5) alternative treatments
    for alt, sign in [("n_crops_5y_lag", 1), ("share_3plus_lag", 1), ("share_cont_corn_lag", 1)]:
        c2 = corn.copy()
        c2["Dc"] = c2[alt] - c2[alt].mean()
        specs[f"ols_countyFE_T_{alt}"] = interaction_model(c2.dropna(subset=["Dc"]))
    # (6) contemporaneous window (ends in t; includes the crop planted in year t before the summer hazard) adds 2012
    c3 = d0[(d0.crop == "corn") & (d0.insured_acres >= 1000) & d0.div_shannon_5y_cur.notna()].copy()
    c3["Dc"] = c3.div_shannon_5y_cur - c3.div_shannon_5y_cur.mean()
    c3["corn_share_lag"] = c3.corn_share_cur
    c3["aws_c"] = (c3.aws0_150_mm - 236) / 47
    specs["ols_countyFE_contemporaneous_D_incl2012"] = interaction_model(c3)
    specs["ppml_countyFE_contemporaneous_D_incl2012"] = interaction_model(c3, kind="ppml")
    # (7) principal crops outcome (secondary)
    pr = d0[(d0.crop == "principal") & (d0.insured_acres >= 2000) & d0.div_shannon_5y_lag.notna()].copy()
    pr["Dc"] = pr.div_shannon_5y_lag - mu_D
    pr["aws_c"] = (pr.aws0_150_mm - 236) / 47
    specs["ols_countyFE_principal_crops"] = interaction_model(pr)
    # (8) unweighted
    c4 = corn.copy()
    c4["w"] = 1.0
    specs["ols_countyFE_unweighted"] = interaction_model(c4)

    # ---------------- placebos
    plac = {}
    # low-hazard years only: D should not matter for drought losses
    lo = corn[corn.H < LOW].copy()
    m, dd = fe_ols(lo, "lcr", ["Dc", "corn_share_lag"])
    plac["low_hazard_years_D_on_drought_lcr"] = {**coef(m, "Dc"), "n": int(m.nobs),
                                                 "mean_y": float(np.average(dd.lcr, weights=dd.w))}
    hi = corn[corn.H > HIGH].copy()
    m, dd = fe_ols(hi, "lcr", ["Dc", "corn_share_lag"])
    plac["high_hazard_years_D_on_drought_lcr_(for_contrast)"] = {**coef(m, "Dc"), "n": int(m.nobs),
                                                                 "mean_y": float(np.average(dd.lcr, weights=dd.w))}
    # excess-moisture losses
    o = interaction_model(corn, y="lcr_ex")
    plac["excess_moisture_lcr_interaction_model"] = {k: v for k, v in o.items() if k != "_model"}
    m, dd = fe_ols(corn, "lcr_ex", ["Dc", "corn_share_lag"])
    plac["excess_moisture_lcr_D_all_years"] = {**coef(m, "Dc"), "n": int(m.nobs)}
    # lead test: D of the window t+1..t+5 (disjoint from t-5..t-1) should not predict year-t loss given lagged D
    c5 = corn[corn.div_shannon_5y_lead5.notna()].copy()
    c5["Dlead_c"] = c5.div_shannon_5y_lead5 - mu_D
    c5["DleadH"] = c5.Dlead_c * c5.H
    o = interaction_model(c5, extra=("Dlead_c", "DleadH"))
    plac["lead_test_window_t+1_to_t+5"] = {k: v for k, v in o.items() if k != "_model"}
    res["placebos"] = plac

    # ---------------- overlap / common support
    q = corn.groupby("state_abbr").div_shannon_5y_lag.quantile([0.05, 0.95]).unstack()
    lo_cs, hi_cs = float(q[0.05].max()), float(q[0.95].min())
    # use states with enough mass: common support = overlap of the central 90% of each state's distribution, but
    # require at least 25% of the state's rows inside it; otherwise drop the state
    inside = corn.div_shannon_5y_lag.between(lo_cs, hi_cs)
    share_in = inside.groupby(corn.state_abbr).mean()
    res["overlap"] = {"state_p05_p95": {s: [float(a), float(b)] for s, (a, b) in q.iterrows()},
                      "common_support_interval": [lo_cs, hi_cs], "share_rows_inside_by_state": share_in.to_dict(),
                      "share_rows_inside_total": float(inside.mean())}
    if inside.sum() > 500:
        ct = corn[inside].copy()
        specs["ols_countyFE_common_support"] = interaction_model(ct)
    # residual variation of D after controls (how much is left to identify from)
    Xc = pd.get_dummies(corn.sy, dtype=float, drop_first=True)
    Xc[["aws_c", "irr", "clim_prcp_c", "clim_edd_c", "corn_share_lag"]] = corn[
        ["aws_c", "irr", "clim_prcp_c", "clim_edd_c", "corn_share_lag"]]
    r2_ctrl = sm.OLS(corn.div_shannon_5y_lag, Xc.fillna(0)).fit().rsquared
    Xf = pd.concat([Xc.iloc[:, :0], fe_dummies(corn, ("fips", "sy")),
                    Xc[["aws_c", "irr", "clim_prcp_c", "clim_edd_c", "corn_share_lag"]]], axis=1).fillna(0)
    Xf = sm.add_constant(Xf)
    Xc = sm.add_constant(Xc)
    r2_fe = sm.OLS(corn.div_shannon_5y_lag, Xf).fit().rsquared
    res["overlap"]["r2_D_on_controls_stateyearFE"] = float(r2_ctrl)
    res["overlap"]["r2_D_on_controls_countyFE"] = float(r2_fe)

    # ---------------- sensitivity (Cinelli-Hazlett) on the headline FE interaction
    head = specs["ols_countyFE_stateyearFE"]
    hm = head["_model"]
    sens = {"coefficient": "D_x_H (county FE + state-year FE, corn)",
            **robustness_value(head["t_DH"], head["df_resid"]),
            "benchmark_H_x_irrigation": benchmark_bound(hm, "DH", "H_irr"),
            "benchmark_H_x_irrigation_3x": benchmark_bound(hm, "DH", "H_irr", kd=3, ky=3),
            "benchmark_H_x_aws": benchmark_bound(hm, "DH", "H_aws")}
    pm = specs["ols_stateyearFE_controls"]
    sens["pooled_spec"] = {"coefficient": "D_x_H (state-year FE + controls, corn)",
                           **robustness_value(pm["t_DH"], pm["df_resid"]),
                           "benchmark_irrigation": benchmark_bound(pm["_model"], "DH", "H_irr"),
                           "benchmark_irrigation_3x": benchmark_bound(pm["_model"], "DH", "H_irr", kd=3, ky=3)}
    res["sensitivity"] = sens

    # ---------------- DML
    dmlres = {}
    for nm, kw in ([] if "--no-dml" in sys.argv else [("linear_dml", {}), ("linear_dml_mundlak", {"mundlak": True}), ("causal_forest_dml", {"forest": True}),
                   ("causal_forest_dml_mundlak", {"forest": True, "mundlak": True})]):
        try:
            dmlres[nm] = dml(corn, **kw)
            print(nm, {k: v for k, v in dmlres[nm].items() if k in ("high_hazard", "low_hazard")}, flush=True)
        except Exception as e:  # noqa: BLE001
            dmlres[nm] = {"error": repr(e)}
            print(nm, "failed", e)
    res["dml"] = dmlres

    # ---------------- relative effects, Bowles comparison
    rel = {}
    for nm, o in specs.items():
        kind = "ppml" if nm.startswith("ppml") else "ols"
        if "_T_" in nm:
            continue
        rel[nm] = rel_effect(o, kind)
    res["relative_effects_high_hazard_per_0.1_shannon"] = rel
    # implied reduction for the Bowles contrast if ALL fields moved corn-soy -> 4-crop (delta 0.66) and for the
    # county p10 -> p90 contrast
    p10, p50, p90 = res["descriptives"]["D_p10_p50_p90"]
    pp = specs["ppml_countyFE_stateyearFE"]["effect_high_hazard"]
    imp = lambda b, dD: 100 * (1 - np.exp(b * dD))  # noqa: E731
    res["bowles_comparison"] = {
        "headline_spec": "ppml_countyFE_stateyearFE (proportional effect in high-hazard years)",
        "implied_loss_reduction_pct_for_delta_0.66": {"est": imp(pp["est"], 0.66),
                                                      "ci95": sorted([imp(pp["ci95"][0], 0.66),
                                                                      imp(pp["ci95"][1], 0.66)])},
        "implied_loss_reduction_pct_county_p10_to_p90": {"delta": p90 - p10, "est": imp(pp["est"], p90 - p10),
                                                         "ci95": sorted([imp(pp["ci95"][0], p90 - p10),
                                                                         imp(pp["ci95"][1], p90 - p10)])},
        "trial_range_pct": BOWLES["range_pct"],
        "note": "Positive = diversity reduces drought loss cost. Trials measure yield-loss reduction on a field; RMA "
                "loss cost is indemnity below a guarantee on a county aggregate, so magnitudes are not identical.",
    }
    for o in specs.values():
        o.pop("_model", None)
    res["specs"] = specs

    # ---------------- verdict and app effect
    head = specs["ols_countyFE_stateyearFE"]
    hp = specs["ppml_countyFE_stateyearFE"]
    e_ols = head["effect_high_hazard"]
    e_pp = hp["effect_high_hazard"]
    sig_neg = e_pp["ci95"][1] < 0 and e_ols["ci95"][1] < 0
    sig_pos = e_pp["ci95"][0] > 0 and e_ols["ci95"][0] > 0
    plac_ok = (abs(plac["low_hazard_years_D_on_drought_lcr"]["est"]) < 1.96 * plac["low_hazard_years_D_on_drought_lcr"]["se"])
    res["verdict_inputs"] = {"headline_ols_effect_high_hazard": e_ols, "headline_ppml_effect_high_hazard": e_pp,
                             "significantly_protective": bool(sig_neg), "significantly_harmful": bool(sig_pos),
                             "low_hazard_placebo_passes": bool(plac_ok)}
    rr = BOWLES["range_pct"]
    dlt = BOWLES["delta_shannon_field"]
    if sig_neg and plac_ok:
        res["app_effect"] = {
            "source": "observational", "form": "multiplier = exp(theta * (D - D_now)) on drought loss cost",
            "theta_per_unit_D": {"est": e_pp["est"], "lo": e_pp["ci95"][0], "hi": e_pp["ci95"][1]},
            "label": "Observational estimate (county FE + state-year FE PPML, high-hazard years)"}
    else:
        res["app_effect"] = {
            "source": "trial_prior_scenario",
            "form": "multiplier = max(0.05, 1 - r * (D - D_now) / delta_shannon_field) on drought loss cost, for "
                    "D >= D_now (and 1 + r*(D_now - D)/delta for D < D_now)",
            "delta_shannon_field": dlt,
            "r": {"est": rr[0] / 100, "lo": 0.0, "hi": rr[1] / 100},
            "label": "Scenario assumption from field trials (Bowles et al. 2020: 14-90% smaller maize drought-year "
                     "yield losses in diversified rotations); est = trial lower bound, lo = no effect (the "
                     "observational county estimate is not distinguishable from zero), hi = trial upper bound. "
                     "Not estimated from the county data."}
    res["verdict"] = verdict_text(res)
    save_json(res, OUT / "diversity_effect.json", 1)
    print(res["verdict"])


def verdict_text(res):
    s = res["specs"]
    h = s["ols_countyFE_stateyearFE"]
    p = s["ppml_countyFE_stateyearFE"]
    r = res["relative_effects_high_hazard_per_0.1_shannon"]
    d = res["descriptives"]
    pl = res["placebos"]
    b = res["bowles_comparison"]
    lines = []
    lines.append(
        f"Data: {d['n_county_years']} corn county-years ({d['years'][0]}-{d['years'][1]}, {d['n_counties']} counties), "
        f"{d['high_hazard_county_years']} of them high-hazard (hazard_z > 1). Diversity varies mostly between counties: "
        f"within-county SD {d['D_sd_within_county']:.3f} vs between-county SD {d['D_sd_between_counties']:.3f} "
        f"({100 * d['D_within_share_of_variance']:.0f}% of variance is within county).")
    lines.append(
        f"Raw: more diverse counties are drier/western (Spearman D vs longitude {d['spearman_county_means']['D_vs_longitude']:+.2f}, "
        f"vs JJA climatology {d['spearman_county_means']['D_vs_clim_jja_prcp']:+.2f}, vs irrigation "
        f"{d['spearman_county_means']['D_vs_irrigated_share']:+.2f}) and have higher mean corn drought loss cost "
        f"(Spearman {d['spearman_county_means']['D_vs_mean_corn_lcr']:+.2f}) - the raw association is confounded by climate.")
    lines.append(
        f"Headline (county FE + state-year FE, corn): effect of +0.1 Shannon in high-hazard years = "
        f"{r['ols_countyFE_stateyearFE']['est_pct']:+.1f}% of mean loss cost (95% CI "
        f"{r['ols_countyFE_stateyearFE']['ci95_pct'][0]:+.1f} to {r['ols_countyFE_stateyearFE']['ci95_pct'][1]:+.1f}); "
        f"PPML {r['ppml_countyFE_stateyearFE']['est_pct']:+.1f}% (CI {r['ppml_countyFE_stateyearFE']['ci95_pct'][0]:+.1f} "
        f"to {r['ppml_countyFE_stateyearFE']['ci95_pct'][1]:+.1f}). Negative = protective.")
    lines.append(
        f"Bowles et al. 2020 trials: 14-90% smaller drought-year maize yield losses. Implied by the PPML estimate for "
        f"the same corn-soy -> 4-crop contrast (+0.66 Shannon): {b['implied_loss_reduction_pct_for_delta_0.66']['est']:.0f}% "
        f"reduction (CI {b['implied_loss_reduction_pct_for_delta_0.66']['ci95'][0]:.0f} to "
        f"{b['implied_loss_reduction_pct_for_delta_0.66']['ci95'][1]:.0f}).")
    lp = pl["low_hazard_years_D_on_drought_lcr"]
    lines.append(f"Placebo, low-hazard years: D coefficient {lp['est']:+.4f} (CI {lp['ci95'][0]:+.4f} to {lp['ci95'][1]:+.4f}).")
    vi = res["verdict_inputs"]
    if vi["significantly_protective"] and vi["low_hazard_placebo_passes"]:
        lines.append("Verdict: the observational data show a protective diversity effect in drought years that "
                     "survives county and state-year fixed effects; it is used (with its CI) in the app.")
    elif vi["significantly_harmful"]:
        lines.append("Verdict: the observational estimate is WRONG-SIGNED (more diversity, more drought loss) even "
                     "within counties. We do not believe this is causal (residual confounding by shifts toward "
                     "drought-prone crops/land and very little within-county variation), but the data do not "
                     "support a protective effect. The app uses the field-trial range as a labelled scenario.")
    else:
        lines.append("Verdict: the observational county-level effect is NOT distinguishable from zero once climate, "
                     "soils and fixed effects are controlled. The data neither confirm nor rule out the trial "
                     "effect at county scale. The app uses the field-trial range (Bowles et al. 2020) as a labelled "
                     "scenario assumption, not as an estimate from these data.")
    return " ".join(lines)


if __name__ == "__main__":
    main()
