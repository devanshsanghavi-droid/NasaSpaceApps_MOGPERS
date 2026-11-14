"""m02: watershed river nitrate SIMULATION model (drivers only, no lagged nitrate) + baselines.

Run: python3 model/m02_river_model.py   (after m01; ~3-6 min)

(a) LightGBM quantile models (alpha 0.1/0.5/0.9) on log(no3) with monotone (+) constraints on bare-share,
    soil-wetness and bare x wet features; hyperparameters + optional feature groups chosen by
    leave-one-year-out (LOYO) CV inside 2016-2022 only. The 80% band is conformalized (CQR) with
    LOYO out-of-fold scores so its width is set by out-of-year errors, not in-sample fit.
(b) two-reservoir conceptual model (reservoir.py) fitted with scipy on 2016-2022.
(c) baselines: day-of-year climatology (train years), persistence 7 d / 14 d (these use observed
    nitrate, so they are forecasts, not simulations - shown for reference).
Train 2016-2022, TEST 2023-2025 (out-of-time), LIVE 2026-01-01..latest (out-of-sample).
Outputs: model/out/river_daily.parquet, model/out/metrics.json, model/out/models/*
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import featlib as F  # noqa: E402
import reservoir as RV  # noqa: E402

MODELS = F.OUT / "models"
TRAIN_YEARS = list(range(2016, 2023))
MCL = 10.0
BASE_PARAMS = dict(learning_rate=0.03, feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1,
                   lambda_l2=1.0, max_bin=127, verbose=-1, num_threads=4, seed=7,
                   monotone_constraints_method="advanced")
GRID = dict(num_leaves=[7, 15], min_child_samples=[50, 150], n_estimators=[150, 400, 800],
            longmem=[False, True], cdl=[False, True])


class QGBM:
    """LightGBM booster + constant init score. LightGBM's built-in quantile objective refuses monotone
    constraints (leaf renewal), so quantiles are fitted with a custom pinball-loss objective
    (gradient of the check loss, unit Hessian), which honours monotone constraints."""

    def __init__(self, booster, init, feats, alpha):
        self.booster, self.init, self.feats, self.alpha = booster, float(init), list(feats), alpha

    def predict(self, X, num_iteration=None):
        return self.init + self.booster.predict(X[self.feats], num_iteration=num_iteration)

    def save(self, path):
        self.booster.save_model(str(path))
        json.dump(dict(init=self.init, feats=self.feats, alpha=self.alpha), open(str(path) + ".meta.json", "w"))

    @staticmethod
    def load(path):
        meta = json.load(open(str(path) + ".meta.json"))
        return QGBM(lgb.Booster(model_file=str(path)), meta["init"], meta["feats"], meta["alpha"])


def pinball_obj(alpha):
    def f(preds, data):
        y = data.get_label()
        grad = np.where(y > preds + data.init0, -alpha, 1.0 - alpha)
        return grad, np.ones_like(grad)
    return f


def lgb_fit(X, y, feats, alpha, num_leaves, min_child_samples, n_estimators, seed=7):
    init = float(np.quantile(y, alpha))
    p = dict(BASE_PARAMS, objective=pinball_obj(alpha), num_leaves=num_leaves,
             min_child_samples=min_child_samples, monotone_constraints=F.monotone_vector(feats), seed=seed)
    ds = lgb.Dataset(X[feats], y - init, free_raw_data=False)
    ds.init0 = 0.0  # labels are already centred on the init score
    b = lgb.train(p, ds, num_boost_round=n_estimators)
    return QGBM(b, init, feats, alpha)


# ------------------------------------------------------------------ metrics
def nse(o, p):
    return float(1 - np.sum((o - p) ** 2) / np.sum((o - o.mean()) ** 2))


def kge(o, p):
    r = np.corrcoef(o, p)[0, 1]
    return float(1 - np.sqrt((r - 1) ** 2 + (p.std() / o.std() - 1) ** 2 + (p.mean() / o.mean() - 1) ** 2))


def exceed(o, p, thr=MCL):
    oe, pe = o > thr, p > thr
    hits = int((oe & pe).sum()); miss = int((oe & ~pe).sum()); fa = int((~oe & pe).sum())
    return dict(obs_days=int(oe.sum()), pred_days=int(pe.sum()), hits=hits, misses=miss, false_alarms=fa,
                hit_rate=(hits / (hits + miss) if hits + miss else None),
                false_alarm_ratio=(fa / (hits + fa) if hits + fa else None),
                csi=(hits / (hits + miss + fa) if hits + miss + fa else None))


def metric_block(o, p50, p10=None, p90=None):
    m = np.isfinite(o) & np.isfinite(p50)
    if m.sum() < 30:
        return dict(n=int(m.sum()))
    o_, p_ = o[m], p50[m]
    out = dict(n=int(m.sum()), NSE=nse(o_, p_), KGE=kge(o_, p_), RMSE=float(np.sqrt(np.mean((p_ - o_) ** 2))),
               MAE=float(np.mean(np.abs(p_ - o_))), bias=float(np.mean(p_ - o_)),
               pbias_pct=float(100 * (p_.sum() - o_.sum()) / o_.sum()),
               r=float(np.corrcoef(o_, p_)[0, 1]),
               NSE_log=nse(np.log(o_), np.log(np.clip(p_, 0.05, None))))
    if p10 is not None:
        mm = m & np.isfinite(p10) & np.isfinite(p90)
        out["coverage80"] = float(np.mean((o[mm] >= p10[mm]) & (o[mm] <= p90[mm])))
    out["exceed10"] = exceed(o_, p_)
    return out


def runs(mask: np.ndarray):
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def event_block(df: pd.DataFrame, col: str, year: int):
    g = df[df.date.dt.year == year]
    obs_ok = g.obs.notna()
    o = g.obs.values; p = g[col].values
    pe_all = np.isfinite(p) & (p > MCL)
    out = dict(
        obs_days_over10=int((o[obs_ok] > MCL).sum()), obs_days_with_data=int(obs_ok.sum()),
        pred_days_over10_on_obs_days=int(((p > MCL) & obs_ok.values).sum()),
        pred_days_over10_all_days=int(pe_all.sum()), pred_days_with_value=int(np.isfinite(p).sum()),
        obs_peak=float(np.nanmax(o)), obs_peak_date=str(g.date.iloc[int(np.nanargmax(np.where(obs_ok, o, -1)))].date()),
        pred_peak=float(np.nanmax(p)), pred_peak_date=str(g.date.iloc[int(np.nanargmax(np.where(np.isfinite(p), p, -1)))].date()),
        obs_longest_run_over10=runs(np.where(obs_ok, o > MCL, False)), pred_longest_run_over10=runs(pe_all),
    )
    oo = g.date[obs_ok.values & (o > MCL)]
    pp = g.date[pe_all]
    out["obs_first_last_over10"] = [str(oo.min().date()), str(oo.max().date())] if len(oo) else None
    out["pred_first_last_over10"] = [str(pp.min().date()), str(pp.max().date())] if len(pp) else None
    m = obs_ok.values & np.isfinite(p)
    out["hits_on_obs_days"] = exceed(o[m], p[m])
    return out


# ------------------------------------------------------------------ baselines
def climatology(g: pd.DataFrame, train: np.ndarray, halfwin=15):
    d = g.date
    doy = d.dt.dayofyear.clip(upper=365).values
    ltr = g.lno3.values
    q = {}
    for D in range(1, 366):
        dist = np.minimum(np.abs(doy - D), 365 - np.abs(doy - D))
        m = train & np.isfinite(ltr) & (dist <= halfwin)
        q[D] = np.quantile(ltr[m], [0.1, 0.5, 0.9])
    arr = np.array([q[x] for x in doy])
    return np.exp(arr[:, 0]), np.exp(arr[:, 1]), np.exp(arr[:, 2])


def persistence(g: pd.DataFrame, train: np.ndarray, h: int):
    lo = g.lno3.values
    lag = np.full_like(lo, np.nan)
    lag[h:] = lo[:-h]
    ratio = lo - lag
    qq = np.nanquantile(ratio[train], [0.1, 0.9])
    return np.exp(lag + qq[0]), np.exp(lag), np.exp(lag + qq[1])


# ------------------------------------------------------------------ main pieces
def loyo_cv(g, feats_all, train):
    """Grid search by leave-one-year-out CV of the median model. Score = mean RMSE of log(no3)."""
    years = g.year.values
    y = g.lno3.values
    m_obs = train & np.isfinite(y)
    results = []
    combos = list(itertools.product(GRID["num_leaves"], GRID["min_child_samples"], GRID["longmem"], GRID["cdl"]))
    for nl, mcs, lm, cd in combos:
        feats = F.gbm_features(lm, cd)
        errs = {n: [] for n in GRID["n_estimators"]}
        nse_y = {n: [] for n in GRID["n_estimators"]}
        for yr in TRAIN_YEARS:
            tr = m_obs & (years != yr); te = m_obs & (years == yr)
            b = lgb_fit(g[tr], y[tr], feats, 0.5, nl, mcs, max(GRID["n_estimators"]))
            for n in GRID["n_estimators"]:
                p = b.predict(g.loc[te, feats], num_iteration=n)
                errs[n].append(np.sqrt(np.mean((p - y[te]) ** 2)))
                nse_y[n].append(nse(np.exp(y[te]), np.exp(p)))
        for n in GRID["n_estimators"]:
            results.append(dict(num_leaves=nl, min_child_samples=mcs, n_estimators=n, longmem=lm, cdl=cd,
                                cv_rmse_log=float(np.mean(errs[n])), cv_nse_mean=float(np.mean(nse_y[n])),
                                cv_rmse_log_by_year=dict(zip(map(str, TRAIN_YEARS), map(float, errs[n])))))
    results.sort(key=lambda r: r["cv_rmse_log"])
    return results


def oof_quantiles(g, feats, train, hp):
    """LOYO out-of-fold p10/p50/p90 on training years (for CQR conformal widening + honest CV metrics)."""
    y = g.lno3.values; years = g.year.values
    m_obs = train & np.isfinite(y)
    oof = np.full((len(g), 3), np.nan)
    for yr in TRAIN_YEARS:
        tr = m_obs & (years != yr); te = train & (years == yr) & g[feats].notna().any(axis=1).values
        for j, a in enumerate([0.1, 0.5, 0.9]):
            b = lgb_fit(g[tr], y[tr], feats, a, hp["num_leaves"], hp["min_child_samples"], hp["n_estimators"])
            oof[te, j] = b.predict(g.loc[te, feats])
    return oof


def main():
    t0 = time.time()
    MODELS.mkdir(parents=True, exist_ok=True)
    feats_df = pd.read_parquet(F.OUT / "features.parquet")
    daily_rows, metrics = [], dict(
        generated_at=pd.Timestamp.now(tz="UTC").isoformat(), mcl_mgL=MCL,
        splits=dict(train=list(F.TRAIN), test=list(F.TEST), live=[F.LIVE_START, None]),
        notes=["Simulation models (gbm, reservoir) use drivers only (weather, soil wetness, MODIS cover, CDL, "
               "observed streamflow) - no lagged nitrate. Persistence baselines use nitrate observed 7/14 days "
               "earlier, so they are forecasts with information the simulation models do not get.",
               "Metrics are computed on concentration (mg/L) over days with an observation and a prediction.",
               "gbm p10/p90 are conformalized (CQR) with leave-one-year-out residuals from 2016-2022.",
               "Cover features are causal (as-of MODIS composites; see notes/model.md)."],
        sites={})
    for site, g in feats_df.groupby("site"):
        g = g.sort_values("date").reset_index(drop=True)
        g = g[g.date >= "2015-10-01"].reset_index(drop=True)  # NWIS start
        print(f"\n=== {site} ({F.SITES[site]}) ===")
        train = (g.split == "train").values
        valid_x = g["rain_7"].notna().values & g["logq"].notna().values
        # ---- (a) GBM: LOYO CV for hyperparameters
        cv = loyo_cv(g, None, train & valid_x)
        hp = cv[0]
        print(f"  CV best: {hp['num_leaves']} leaves, mcs {hp['min_child_samples']}, {hp['n_estimators']} trees, "
              f"longmem={hp['longmem']}, cdl={hp['cdl']}  rmse_log={hp['cv_rmse_log']:.3f} nse={hp['cv_nse_mean']:.3f}")
        feats = F.gbm_features(hp["longmem"], hp["cdl"])
        y = g.lno3.values
        m_fit = train & valid_x & np.isfinite(y)
        boosters = {}
        for a in [0.1, 0.5, 0.9]:
            b = lgb_fit(g[m_fit], y[m_fit], feats, a, hp["num_leaves"], hp["min_child_samples"], hp["n_estimators"])
            b.save(MODELS / f"gbm_{site}_q{int(a * 100):02d}.txt")
            boosters[a] = b
        X = g[feats]
        raw = np.column_stack([boosters[a].predict(X) for a in [0.1, 0.5, 0.9]])
        raw[~valid_x] = np.nan
        # CQR with LOYO out-of-fold quantiles
        oof = oof_quantiles(g, feats, train & valid_x, hp)
        mo = train & valid_x & np.isfinite(y) & np.isfinite(oof).all(axis=1)
        lo_ = np.minimum(oof[mo, 0], oof[mo, 1]); hi_ = np.maximum(oof[mo, 2], oof[mo, 1])
        score = np.maximum(lo_ - y[mo], y[mo] - hi_)
        n = mo.sum()
        qhat = float(np.quantile(score, min(1, np.ceil((n + 1) * 0.8) / n)))
        oof_cov_raw = float(np.mean((y[mo] >= lo_) & (y[mo] <= hi_)))
        print(f"  CQR: LOYO raw coverage {oof_cov_raw:.2f}; widen log band by {qhat:+.3f}")
        p50 = np.exp(raw[:, 1])
        p10 = np.exp(np.minimum(raw[:, 0], raw[:, 1]) - qhat)
        p90 = np.exp(np.maximum(raw[:, 2], raw[:, 1]) + qhat)
        p10 = np.minimum(p10, p50); p90 = np.maximum(p90, p50)
        oof_p50 = np.exp(oof[:, 1])
        # ---- (b) reservoir
        print("  fitting reservoir model ...")
        params, qmed = RV.fit(g, train)
        res = RV.predict(params, qmed, g)
        lres = np.log(np.clip(res, 1e-3, None))
        rr = (y - lres)[train & np.isfinite(y) & np.isfinite(lres)]
        rq = np.quantile(rr, [0.1, 0.9])
        res10, res90 = res * np.exp(rq[0]), res * np.exp(rq[1])
        print("  reservoir params:", {k: round(v, 4) for k, v in params.items()})
        # ---- (c) baselines
        c10, c50, c90 = climatology(g, train)
        pers = {h: persistence(g, train, h) for h in (7, 14)}

        out = pd.DataFrame(dict(site=site, date=g.date, obs=g.no3, q_cfs=g.q_cfs, p10=p10, p50=p50, p90=p90,
                                split=g.split, reservoir_p50=res, reservoir_p10=res10, reservoir_p90=res90,
                                clim_p50=c50, clim_p10=c10, clim_p90=c90,
                                pers7=pers[7][1], pers14=pers[14][1], gbm_loyo_p50=oof_p50,
                                cover_src=g.cover_src, no3_qual=g.no3_qual))
        out = out[out.date >= "2016-01-01"].reset_index(drop=True)
        daily_rows.append(out)
        json.dump(dict(site=site, features=feats, monotone=F.monotone_vector(feats), hp=hp, cqr_qhat_log=qhat,
                       oof_coverage_raw=oof_cov_raw, reservoir=params, reservoir_qmed=qmed,
                       reservoir_resid_q10_q90=list(map(float, rq)), base_params=BASE_PARAMS),
                  open(MODELS / f"config_{site}.json", "w"), indent=1)

        # ---- metrics
        sm = dict(name=F.SITE_NAMES[site], hyperparameters={k: hp[k] for k in
                  ["num_leaves", "min_child_samples", "n_estimators", "longmem", "cdl"]},
                  cv_top5=[{k: r[k] for k in ["num_leaves", "min_child_samples", "n_estimators", "longmem", "cdl",
                                               "cv_rmse_log", "cv_nse_mean"]} for r in cv[:5]],
                  cv_best_rmse_log_by_year=hp["cv_rmse_log_by_year"], splits={})
        mod_cols = dict(gbm=("p50", "p10", "p90"), reservoir=("reservoir_p50", "reservoir_p10", "reservoir_p90"),
                        climatology=("clim_p50", "clim_p10", "clim_p90"))
        persq = {7: pers[7], 14: pers[14]}
        o_all = out.obs.values
        for sp in ["train", "test", "live"]:
            msp = (out.split == sp).values
            blk = {}
            for mname, (c5, c1, c9) in mod_cols.items():
                blk[mname] = metric_block(o_all[msp], out[c5].values[msp], out[c1].values[msp], out[c9].values[msp])
            gi = np.searchsorted(g.date.values, out.date.values)
            for h in (7, 14):
                pl, pm, ph = (persq[h][0][gi], persq[h][1][gi], persq[h][2][gi])
                blk[f"persistence_{h}d"] = metric_block(o_all[msp], pm[msp], pl[msp], ph[msp])
            if sp == "train":
                blk["gbm_loyo_cv"] = metric_block(o_all[msp], out.gbm_loyo_p50.values[msp])
            sm["splits"][sp] = blk
        # per test year
        sm["test_by_year"] = {}
        for yr in [2023, 2024, 2025]:
            mm = (out.date.dt.year == yr).values
            sm["test_by_year"][str(yr)] = {mn: {k: v for k, v in metric_block(o_all[mm], out[c5].values[mm]).items()
                                               if k in ("n", "NSE", "KGE", "RMSE", "bias", "r")}
                                          for mn, (c5, _, _) in mod_cols.items()}
        sm["crisis_2025"] = {mn: event_block(out, c5, 2025) for mn, (c5, _, _) in mod_cols.items()}
        sm["live_2026"] = {mn: event_block(out, c5, 2026) for mn, (c5, _, _) in mod_cols.items()}
        sm["by_year_days_over10"] = {}
        for yr in range(2016, 2027):
            gg = out[out.date.dt.year == yr]
            ob = gg.obs.notna()
            sm["by_year_days_over10"][str(yr)] = dict(
                obs=int((gg.obs > MCL).sum()), obs_days_with_data=int(ob.sum()),
                gbm_on_obs_days=int(((gg.p50 > MCL) & ob).sum()), gbm_all_days=int((gg.p50 > MCL).sum()),
                reservoir_all_days=int((gg.reservoir_p50 > MCL).sum()), clim_all_days=int((gg.clim_p50 > MCL).sum()))
        metrics["sites"][site] = sm
        for sp in ["train", "test", "live"]:
            b = sm["splits"][sp]
            print(f"  {sp:5s} " + "  ".join(f"{k}: NSE {v.get('NSE', np.nan):.2f} KGE {v.get('KGE', np.nan):.2f}"
                                           for k, v in b.items() if k in ("gbm", "reservoir", "climatology")))
        c = sm["crisis_2025"]
        print("  2025 obs days>10:", c["gbm"]["obs_days_over10"], "| gbm", c["gbm"]["pred_days_over10_on_obs_days"],
              "| reservoir", c["reservoir"]["pred_days_over10_on_obs_days"], "| clim",
              c["climatology"]["pred_days_over10_on_obs_days"])

    river = pd.concat(daily_rows, ignore_index=True)
    river.to_parquet(F.OUT / "river_daily.parquet", compression="zstd", index=False)
    # keep any blocks written by other scripts (e.g. 'outlook' from m04)
    mpath = F.OUT / "metrics.json"
    if mpath.exists():
        try:
            old = json.load(open(mpath))
            for k in ("outlook",):
                if k in old:
                    metrics[k] = old[k]
        except Exception:
            pass
    json.dump(metrics, open(mpath, "w"), indent=1, default=float)
    print(f"\nwrote river_daily.parquet ({len(river):,} rows), metrics.json  [{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
