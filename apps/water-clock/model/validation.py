"""Out-of-time hindcast of the groundwater state model.

Fold B (headline): train on water years <= 2014 (LLT window 1999-2014, weather coefficients and regime term from
data <= 2014 only), predict 2015-2026. Fold A (stability check): train <= 2004, predict 2005-2016.
Two designs per fold:
  temporal holdout - every well with enough training data; predict its own later levels.
  spatial holdout  - 20% of wells per county (random, seed fixed) are removed; their later levels and 10-yr change
                     are predicted from the other 80% by kriging.
Metrics: MAE / RMSE / bias of the predicted 10-yr change (ft) and of the level in each well's latest target year;
80% interval coverage. Baselines: no change; each well's own OLS trend (temporal only); county-mean trend.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from common import to_xy, ols
from wells_state import run_state, weather_coefs, ols_slopes, to_matrix, forecast_var
from water_balance import county_dh, regime_model
from spatial import OKriger, UKriger

Z80 = norm.ppf(0.9)


def metrics(pred, obs, sd=None):
    pred = np.asarray(pred, float); obs = np.asarray(obs, float)
    m = np.isfinite(pred) & np.isfinite(obs)
    e = pred[m] - obs[m]
    out = dict(n=int(m.sum()), mae=float(np.mean(np.abs(e))), rmse=float(np.sqrt(np.mean(e ** 2))), bias=float(np.mean(e)))
    if sd is not None:
        sd = np.asarray(sd, float)[m]
        out["cov80"] = float(np.mean(np.abs(e) <= Z80 * sd))
        out["median_halfwidth80"] = float(np.median(Z80 * sd))
    return out


def regime_sig(d, reg):
    return np.sqrt(reg["floor_ft_yr"] ** 2 + (reg["k_rel"] * np.abs(d)) ** 2)


def fold(A, end, L=16, horizon=12, spatial_frac=0.2, seed=7):
    Atr = A[A.year <= end]
    coefs = weather_coefs(Atr, end)
    wells, Ct, hyper, coefs, Wadj, cum = run_state(Atr, (end - L + 1, end), coefs=coefs, last_min=end - 4)
    dh = county_dh(Atr, end - 32, end)
    reg = regime_model(dh, coefs, windows=((end - 30, end - 20), (end - 20, end - 10), (end - 10, end)))
    Wraw, years = to_matrix(Atr, end - L + 1, end)
    Wraw = Wraw.loc[wells.well_id]
    ols_s = ols_slopes(Wraw)
    wells = wells.merge(ols_s, left_on="well_id", right_index=True, how="left")
    county_ols = wells.groupby("county_fips").ols_slope.mean()
    Tg = A[(A.year > end) & (A.year <= end + horizon) & A.well_id.isin(wells.well_id)]
    # latest target per well (must be at least 6 years after training end)
    last = Tg[Tg.year >= end + 6].sort_values("year").groupby("well_id").last()[["year", "wl_elev_ft"]]
    obs_end = A[(A.year == end)].set_index("well_id").wl_elev_ft
    obs_10 = A[(A.year == end + 10)].set_index("well_id").wl_elev_ft
    W = wells.set_index("well_id")
    res = {"train_end": end, "window": [end - L + 1, end], "hyper": hyper, "weather_coefs": coefs,
           "regime": {k: v for k, v in reg.items() if k != "table"}}

    # ---------------- temporal holdout ----------------
    d = W.join(last, how="inner")
    H = (d.year - end).values
    sd_model = np.sqrt(forecast_var(d.level_var.values, d.lb_cov.values, d.b_var.values, H, hyper)
                       + (H * regime_sig(d.decline_post.values, reg)) ** 2)
    pred_model = d.level_orig.values + d.b_post.values * H
    pred_llt_nopool = d.level_orig.values + d.b.values * H
    pred_nc = d.last_obs_val.values + d.cum_end.values * 0  # last observed (unadjusted) value
    # last_obs_val is in adjusted units; use the raw matrix for the no-change / OLS baselines
    lastraw = Wraw.loc[d.index].apply(lambda r: r[r.last_valid_index()], axis=1).values
    lastyr = Wraw.loc[d.index].apply(lambda r: r.last_valid_index(), axis=1).values
    pred_nc = lastraw
    pred_ols = lastraw + d.ols_slope.values * (d.year.values - lastyr)
    pred_cty = lastraw + d.county_fips.map(county_ols).values * (d.year.values - lastyr)
    obs = d.wl_elev_ft.values
    temporal_level = dict(model=metrics(pred_model, obs, sd_model), model_without_pooling=metrics(pred_llt_nopool, obs),
                          baseline_no_change=metrics(pred_nc, obs), baseline_own_trend=metrics(pred_ols, obs),
                          baseline_county_trend=metrics(pred_cty, obs))
    # 10-yr change end -> end+10 where both observed
    dd = W.join(pd.DataFrame(dict(h0=obs_end, h10=obs_10)), how="inner").dropna(subset=["h0", "h10"])
    oc = (dd.h10 - dd.h0).values
    sdc = np.sqrt(10 * hyper["q_l"] + 100 * (dd.b_post_var.values + regime_sig(dd.decline_post.values, reg) ** 2)
                  + 2 * hyper["r"])
    temporal_change = dict(model=metrics(dd.b_post.values * 10, oc, sdc), model_without_pooling=metrics(dd.b.values * 10, oc),
                           baseline_no_change=metrics(np.zeros(len(oc)), oc),
                           baseline_own_trend=metrics(dd.ols_slope.values * 10, oc),
                           baseline_county_trend=metrics(dd.county_fips.map(county_ols).values * 10, oc),
                           observed_mean_change_ft=float(np.mean(oc)))
    res["temporal_holdout"] = dict(level_latest=temporal_level, change_10yr=temporal_change,
                                   n_wells=int(len(d)), latest_year_range=[int(d.year.min()), int(d.year.max())])

    # ---------------- spatial holdout ----------------
    rng = np.random.default_rng(seed)
    hold = []
    for c, g in W.groupby("county_fips"):
        k = max(1, int(round(spatial_frac * len(g))))
        hold += list(rng.choice(g.index.values, size=k, replace=False))
    hold = set(hold)
    tr = W[~W.index.isin(hold)]
    te = W[W.index.isin(hold)]
    xt, yt = to_xy(tr.lon.values, tr.lat.values)
    xe, ye = to_xy(te.lon.values, te.lat.values)
    dk = OKriger(xt, yt, tr.decline.values)
    dec_e, decv_e = dk.predict(xe, ye, nugget=True)
    lk = UKriger(xt, yt, tr.level_orig.values, err_var=tr.level_var.values)
    lev_e, levv_e = lk.predict(xe, ye)
    cty_tr = tr.groupby("county_fips").ols_slope.mean()
    te = te.assign(dec_k=dec_e, decv_k=decv_e, lev_k=lev_e, levv_k=levv_e)
    s = te.join(last, how="inner")
    Hs = (s.year - end).values
    sd_s = np.sqrt(s.levv_k.values + Hs ** 2 * (s.decv_k.values + regime_sig(s.dec_k.values, reg) ** 2) + Hs * hyper["q_l"])
    spatial_level = dict(model=metrics(s.lev_k.values - s.dec_k.values * Hs, s.wl_elev_ft.values, sd_s),
                         baseline_no_change=metrics(s.lev_k.values, s.wl_elev_ft.values),
                         baseline_county_trend=metrics(s.lev_k.values + s.county_fips.map(cty_tr).values * Hs,
                                                       s.wl_elev_ft.values))
    sc = te.join(pd.DataFrame(dict(h0=obs_end, h10=obs_10)), how="inner").dropna(subset=["h0", "h10"])
    occ = (sc.h10 - sc.h0).values
    sdcs = np.sqrt(100 * (sc.decv_k.values + regime_sig(sc.dec_k.values, reg) ** 2) + 10 * hyper["q_l"] + 2 * hyper["r"])
    spatial_change = dict(model=metrics(-sc.dec_k.values * 10, occ, sdcs),
                          baseline_no_change=metrics(np.zeros(len(occ)), occ),
                          baseline_county_trend=metrics(sc.county_fips.map(cty_tr).values * 10, occ),
                          observed_mean_change_ft=float(np.mean(occ)))
    res["spatial_holdout"] = dict(level_latest=spatial_level, change_10yr=spatial_change, n_train_wells=int(len(tr)),
                                  n_test_wells=int(len(te)), split="20% of wells per county, random (seed 7)")
    # decline-rate skill summary: correlation of predicted vs observed 10-yr change
    res["temporal_holdout"]["change_10yr"]["r_model"] = float(np.corrcoef(dd.b_post.values * 10, oc)[0, 1])
    res["spatial_holdout"]["change_10yr"]["r_model"] = float(np.corrcoef(-sc.dec_k.values * 10, occ)[0, 1])
    return res


def run(A):
    return dict(fold_2014=fold(A, 2014), fold_2004=fold(A, 2004))
