"""m04: 14-day nitrate outlook issued at the last NWIS nitrate date -> model/out/outlook.json

Run: python3 model/m04_outlook.py   (after m01; ~1-2 min)

For each lead h = 1..14 a LightGBM quantile model predicts log(no3[t+h] / no3[t]) from the last observed
nitrate, its recent trend, streamflow (observed through t) and drivers known at issue time: soil wetness,
recent rain, snowpack/melt, temperature, causal MODIS bare share, season. NO WEATHER FORECAST is used
(none is available here), so rain after the issue date is implicitly "typical for the season".
POWER lags NWIS by L days (L computed at run time); weather/cover features are taken as of t-L in
training AND at issue, so the validation mimics the real information set.

Validation: models trained 2016-2022, tested 2023-2025 at every lead against persistence (no change) and
climatology-of-change (day-of-year median change in train years). Also a live check on 2026 with models
trained 2016-2025. The issued outlook uses models trained on all data available at issue.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import featlib as F  # noqa: E402

H = list(range(1, 15))
TAUS = [0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95]
MCL = 10.0
PARAMS = dict(objective="quantile", learning_rate=0.03, num_leaves=7, min_child_samples=50,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, max_bin=127,
              verbose=-1, num_threads=4, seed=11)
N_TREES = 300
DRIVERS = ["rain_3", "rain_7", "rain_14", "rain_30", "rain_90", "api_k95", "gwr", "gwt", "gwr_30",
           "wetrain_7", "wetrain_30", "melt_7", "snodp", "t2m_7", "gdd5_mar1", "bare", "bare_30", "barewet_30"]
NOW = ["lno3", "dlno3_3", "dlno3_7", "logq", "dlogq", "dlogq_7", "logq_30", "doy_sin", "doy_cos"]


def build(g: pd.DataFrame, lag: int) -> pd.DataFrame:
    g = g.sort_values("date").reset_index(drop=True).copy()
    for c in DRIVERS:
        g[c] = g[c].shift(lag)  # drivers known at issue time (POWER latency)
    g["dlno3_3"] = g["lno3"] - g["lno3"].shift(3)
    g["dlno3_7"] = g["lno3"] - g["lno3"].shift(7)
    for h in H:
        g[f"y{h}"] = g["lno3"].shift(-h) - g["lno3"]
    return g


FEATS = NOW + DRIVERS


def fit_models(d: pd.DataFrame, mask: np.ndarray, hs=H):
    models = {}
    base = mask & d["lno3"].notna().values & d["rain_7"].notna().values
    for h in hs:
        m = base & d[f"y{h}"].notna().values
        models[h] = {t: lgb.train(dict(PARAMS, alpha=t), lgb.Dataset(d.loc[m, FEATS], d.loc[m, f"y{h}"]),
                                  num_boost_round=N_TREES) for t in TAUS}
    return models


def predict_q(models_h, X) -> np.ndarray:
    q = np.column_stack([models_h[t].predict(X) for t in TAUS])
    return np.sort(q, axis=1)  # remove quantile crossing


def prob_over(lq: np.ndarray, thr=MCL) -> np.ndarray:
    """P(no3 > thr) from log-quantiles (rows) by linear interpolation of the quantile function;
    tails beyond tau 0.05/0.95 extended linearly and clipped to [0.01, 0.99]."""
    lt = np.log(thr)
    out = np.empty(len(lq))
    for i, row in enumerate(lq):
        if lt <= row[0]:
            slope = (TAUS[1] - TAUS[0]) / max(row[1] - row[0], 1e-6)
            F_ = TAUS[0] - slope * (row[0] - lt)
        elif lt >= row[-1]:
            slope = (TAUS[-1] - TAUS[-2]) / max(row[-1] - row[-2], 1e-6)
            F_ = TAUS[-1] + slope * (lt - row[-1])
        else:
            F_ = np.interp(lt, row, TAUS)
        out[i] = 1 - F_
    return np.clip(out, 0.01, 0.99)


def clim_change(d: pd.DataFrame, train: np.ndarray, h: int, halfwin=15):
    doy = d.date.dt.dayofyear.clip(upper=365).values
    y = d[f"y{h}"].values
    tab = {}
    for D in range(1, 366):
        dist = np.minimum(np.abs(doy - D), 365 - np.abs(doy - D))
        m = train & np.isfinite(y) & (dist <= halfwin)
        tab[D] = np.quantile(y[m], TAUS)
    return np.array([tab[x] for x in doy])


def scores(o, p, plo, phi, prob, base_o):
    """o: observed no3 at t+h; p: predicted median; prob: P(>10)."""
    m = np.isfinite(o) & np.isfinite(p)
    o, p, plo, phi, prob = o[m], p[m], plo[m], phi[m], prob[m]
    oe, pe = o > MCL, p > MCL
    hits, miss, fa = int((oe & pe).sum()), int((oe & ~pe).sum()), int((~oe & pe).sum())
    return dict(n=int(m.sum()), RMSE=float(np.sqrt(np.mean((p - o) ** 2))), MAE=float(np.mean(np.abs(p - o))),
                bias=float(np.mean(p - o)),
                NSE=float(1 - np.sum((o - p) ** 2) / np.sum((o - o.mean()) ** 2)),
                coverage80=float(np.mean((o >= plo) & (o <= phi))),
                brier_over10=float(np.mean((prob - oe) ** 2)),
                exceed10=dict(obs_days=int(oe.sum()), pred_days=int(pe.sum()), hits=hits, misses=miss,
                              false_alarms=fa, hit_rate=hits / (hits + miss) if hits + miss else None,
                              false_alarm_ratio=fa / (hits + fa) if hits + fa else None,
                              csi=hits / (hits + miss + fa) if hits + miss + fa else None))


def evaluate(d, models, train_mask, test_mask, label):
    res = {}
    X = d[FEATS]
    l0 = d["lno3"].values
    for h in H:
        o = np.exp(d["lno3"].shift(-h).values)
        ok = test_mask & np.isfinite(l0) & np.isfinite(o) & d["rain_7"].notna().values
        lq = l0[:, None] + predict_q(models[h], X)
        cq = l0[:, None] + clim_change(d, train_mask, h)
        pers_prob = (np.exp(l0) > MCL).astype(float)
        i10, i50, i90 = TAUS.index(0.1), TAUS.index(0.5), TAUS.index(0.9)
        # persistence interval: train-period quantiles of the h-day log change (all seasons)
        yq = np.nanquantile(d.loc[train_mask, f"y{h}"], [0.1, 0.9])
        r = dict(
            gbm=scores(o[ok], np.exp(lq[ok, i50]), np.exp(lq[ok, i10]), np.exp(lq[ok, i90]), prob_over(lq[ok]), o),
            persistence=scores(o[ok], np.exp(l0[ok]), np.exp(l0[ok] + yq[0]), np.exp(l0[ok] + yq[1]),
                               pers_prob[ok], o),
            climatology_of_change=scores(o[ok], np.exp(cq[ok, i50]), np.exp(cq[ok, i10]), np.exp(cq[ok, i90]),
                                         prob_over(cq[ok]), o))
        for k in ("gbm", "climatology_of_change"):
            r[k]["skill_vs_persistence_mse"] = float(1 - r[k]["RMSE"] ** 2 / r["persistence"]["RMSE"] ** 2)
            r[k]["brier_skill_vs_persistence"] = float(1 - r[k]["brier_over10"] / r["persistence"]["brier_over10"]) \
                if r["persistence"]["brier_over10"] > 0 else None
        res[f"h{h}"] = r
    s7, s14 = res["h7"], res["h14"]
    print(f"  [{label}] h7  RMSE gbm {s7['gbm']['RMSE']:.2f} pers {s7['persistence']['RMSE']:.2f} "
          f"clim {s7['climatology_of_change']['RMSE']:.2f} | cov80 {s7['gbm']['coverage80']:.2f} | "
          f"Brier gbm {s7['gbm']['brier_over10']:.3f} pers {s7['persistence']['brier_over10']:.3f}")
    print(f"  [{label}] h14 RMSE gbm {s14['gbm']['RMSE']:.2f} pers {s14['persistence']['RMSE']:.2f} "
          f"clim {s14['climatology_of_change']['RMSE']:.2f} | cov80 {s14['gbm']['coverage80']:.2f} | "
          f"Brier gbm {s14['gbm']['brier_over10']:.3f} pers {s14['persistence']['brier_over10']:.3f}")
    return res


def pctile_same_window(d: pd.DataFrame, col: str, t: pd.Timestamp, value: float, halfwin=7):
    doy = d.date.dt.dayofyear.values
    D = t.dayofyear
    dist = np.minimum(np.abs(doy - D), 365 - np.abs(doy - D))
    m = (d.date.dt.year >= 2016).values & (d.date.dt.year <= 2025).values & (dist <= halfwin) & d[col].notna().values
    v = d.loc[m, col].values
    return float(100 * np.mean(v <= value)) if len(v) else None, int(len(v))


def describe(p):
    if p is None:
        return "unknown"
    if p >= 90:
        return "much higher than usual"
    if p >= 70:
        return "higher than usual"
    if p > 30:
        return "near normal"
    if p > 10:
        return "lower than usual"
    return "much lower than usual"


def main():
    feats = pd.read_parquet(F.OUT / "features.parquet")
    out = dict(sites={})
    metrics_out = dict(method=("LightGBM quantile regression (taus " + ", ".join(map(str, TAUS)) +
                               f") of log(no3[t+h]/no3[t]), h=1..14, {N_TREES} trees, 7 leaves; no weather forecast"),
                       sites={})
    for site, g0 in feats.groupby("site"):
        g0 = g0.sort_values("date").reset_index(drop=True)
        last_no3 = g0.loc[g0.no3.notna(), "date"].max()
        last_pow = g0.loc[g0.power_ok.astype(bool), "date"].max()
        lag = max(0, (last_no3 - last_pow).days)
        print(f"=== {site}: issue {last_no3.date()}, POWER through {last_pow.date()} -> driver lag {lag} d")
        d = build(g0, lag)
        yr = d.date.dt.year.values
        train = (yr >= 2016) & (yr <= 2022)
        test = (yr >= 2023) & (yr <= 2025)
        m_val = fit_models(d, train)
        ev_test = evaluate(d, m_val, train, test, "test 2023-2025")
        # live check on 2026 with models trained 2016-2025 (targets must lie before the issue date)
        tr2 = (yr >= 2016) & (yr <= 2025)
        m_25 = fit_models(d, tr2)
        ev_live = evaluate(d, m_25, tr2, yr == 2026, "live 2026")
        # operational models: all data with known targets (y_h NaN automatically excluded)
        m_op = fit_models(d, yr >= 2016)
        it = d.index[d.date == last_no3][0]
        x = d.loc[[it], FEATS]
        l0 = float(d.loc[it, "lno3"])
        lq = np.vstack([l0 + predict_q(m_op[h], x)[0] for h in H])
        pr = prob_over(lq)
        i10, i50, i90 = TAUS.index(0.1), TAUS.index(0.5), TAUS.index(0.9)
        dates = [str((last_no3 + pd.Timedelta(days=h)).date()) for h in H]
        # drivers as of the last POWER day (raw, un-lagged values from features.parquet)
        gp = g0.set_index("date")
        rain7 = float(gp.loc[last_pow, "rain_7"]); gwr = float(gp.loc[last_pow, "gwr"])
        bare = float(gp.loc[last_pow, "bare"]); snod = float(gp.loc[last_pow, "snodp"])
        r7p, nr = pctile_same_window(g0, "rain_7", last_pow, rain7)
        gwp, _ = pctile_same_window(g0, "gwr", last_pow, gwr)
        bp, _ = pctile_same_window(g0, "bare", last_pow, bare)
        r30 = float(gp.loc[last_pow, "rain_30"]); r30p, _ = pctile_same_window(g0, "rain_30", last_pow, r30)
        last_val = float(np.exp(l0))
        p50_14, p10_14, p90_14 = np.exp(lq[-1, i50]), np.exp(lq[-1, i10]), np.exp(lq[-1, i90])
        n_over = int(round(np.sum(pr)))
        name = F.SITE_NAMES[site]
        sk7 = ev_test["h7"]["gbm"]["skill_vs_persistence_mse"]
        sk14 = ev_test["h14"]["gbm"]["skill_vs_persistence_mse"]
        skill_txt = ("In 2023-2025 tests this outlook beat 'no change' by "
                     f"{100 * sk7:.0f}% (1 week) and {100 * sk14:.0f}% (2 weeks) in squared error."
                     if sk7 > 0 and sk14 > 0 else
                     "In 2023-2025 tests this outlook was NOT better than simply assuming no change "
                     f"(skill {100 * sk7:+.0f}% at 1 week, {100 * sk14:+.0f}% at 2 weeks), so treat it as a "
                     "rough guide.")
        trend = ("rise" if p50_14 > last_val * 1.05 else "fall" if p50_14 < last_val * 0.95 else "stay about level")
        text = (f"{name}: {last_val:.1f} mg/L nitrate-N on {last_no3:%b %d, %Y} "
                f"({'above' if last_val > MCL else 'below'} the 10 mg/L drinking-water limit). "
                f"Over the next 14 days the river is expected to {trend}: by {pd.Timestamp(dates[-1]):%b %d} "
                f"the middle estimate is {p50_14:.1f} mg/L, and 8 in 10 outcomes fall between {p10_14:.1f} and "
                f"{p90_14:.1f}. Expect about {n_over} of the next 14 days above 10 mg/L "
                f"(chance on day 14: {100 * pr[-1]:.0f}%). "
                f"Soil moisture is {describe(gwp)} for this time of year (root-zone wetness at the "
                f"{gwp:.0f}th percentile of 2016-2025), the last 7 days brought {rain7:.0f} mm of rain "
                f"({describe(r7p)}), and satellite bare cropland is at the {bp:.0f}th percentile. "
                "No weather forecast is used: a big storm would push nitrate outside this range. " + skill_txt)
        so = dict(issued=str(pd.Timestamp.now(tz="UTC").date()), issue_basis_date=str(last_no3.date()), site=site,
                  name=name, last_obs=dict(date=str(last_no3.date()), value=round(last_val, 2)),
                  dates=dates, p10=[round(float(np.exp(v)), 2) for v in lq[:, i10]],
                  p50=[round(float(np.exp(v)), 2) for v in lq[:, i50]],
                  p90=[round(float(np.exp(v)), 2) for v in lq[:, i90]],
                  p05=[round(float(np.exp(v)), 2) for v in lq[:, 0]], p95=[round(float(np.exp(v)), 2) for v in lq[:, -1]],
                  prob_over10=[round(float(v), 3) for v in pr],
                  expected_days_over10=round(float(np.sum(pr)), 1),
                  drivers=dict(as_of=str(last_pow.date()), rain_7d_mm=round(rain7, 1), rain_7d_pctile=round(r7p, 0),
                               rain_30d_mm=round(r30, 1), rain_30d_pctile=round(r30p, 0),
                               gwetroot=round(gwr, 3), gwetroot_pctile=round(gwp, 0),
                               bare_share=round(bare, 3), bare_share_pctile=round(bp, 0),
                               bare_share_source=str(gp.loc[last_pow, "cover_src"]),
                               bare_share_age_days=float(gp.loc[last_pow, "cover_age_days"]),
                               snow_depth_cm=round(snod, 1),
                               pctile_reference=f"same calendar window (+-7 days) in 2016-2025, n={nr} days"),
                  skill=dict(test_2023_2025_h7=ev_test["h7"]["gbm"]["skill_vs_persistence_mse"],
                             test_2023_2025_h14=ev_test["h14"]["gbm"]["skill_vs_persistence_mse"],
                             coverage80_h7=ev_test["h7"]["gbm"]["coverage80"],
                             coverage80_h14=ev_test["h14"]["gbm"]["coverage80"]),
                  weather_forecast_used=False, driver_lag_days=lag, text=text)
        out["sites"][site] = so
        metrics_out["sites"][site] = dict(driver_lag_days=lag, test_2023_2025=ev_test, live_2026=ev_live)
        print("  ", text)
    prim = out["sites"]["05484500"]
    top = {k: prim[k] for k in ["issued", "site", "last_obs", "dates", "p10", "p50", "p90", "prob_over10",
                                "drivers", "text"]}
    top.update(issue_basis_date=prim["issue_basis_date"], name=prim["name"], weather_forecast_used=False,
               method=metrics_out["method"], sites=out["sites"])
    json.dump(top, open(F.OUT / "outlook.json", "w"), indent=1)
    mpath = F.OUT / "metrics.json"
    mt = json.load(open(mpath)) if mpath.exists() else {}
    mt["outlook"] = metrics_out
    json.dump(mt, open(mpath, "w"), indent=1, default=float)
    print("wrote outlook.json and metrics.json['outlook']")


if __name__ == "__main__":
    main()
