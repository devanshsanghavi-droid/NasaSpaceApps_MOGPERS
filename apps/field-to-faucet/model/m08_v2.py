"""m08: v2 (legacy-N) river simulation model, validation side by side with v1, display-model decision.

Run: python3 model/m08_v2.py   (after m06_history.py, m07_features_v2.py and m02; ~10-15 min)

v2 = v1's monotone quantile GBM (same feature groups that v1's CV chose per site) PLUS the causal N-carryover
store features (featlib.carryover_features; monotone +, prior growing-season rain monotone -), trained on a
longer record for the Raccoon (nitrate from 2012-03-02, covering the 2012 drought -> 2013 flush).
DESIGNED AFTER SEEING THE v1 2025 MISS: its 2023-2025 score is not a clean out-of-time test. The stricter
check trains on 2012-2019 (Raccoon) / 2016-2019 (Des Moines) and tests 2020-2022 and 2023-2025.

Display rule (fixed before computing any 2026 number, does not use 2026):
  use v2 for a site iff (a) v2's leave-one-year-out CV ln-RMSE averaged over the 2016-2022 folds is no worse
  than v1's, AND (b) on the strict check v2's pooled 2020-2025 ln-RMSE is lower than the v1 feature set
  trained on the same years with v1's hyperparameters. Otherwise keep v1.
Outputs: model/out/v2/river_daily_v2.parquet, model/out/models_v2/*, metrics.json keys "v2", "display_model".
v1 files and v1 numbers are not touched.
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import featlib as F  # noqa: E402
import qgbm as Q  # noqa: E402
import m02_river_model as M2  # noqa: E402
import river  # noqa: E402

OUT2 = F.OUT / "v2"
MODELS2 = F.OUT / "models_v2"
TRAIN_END = 2022
FIRST_YEAR = {"05484500": 2012, "05482000": 2016}
STRICT_END = 2019
GRID = dict(num_leaves=[7, 15], min_child_samples=[50, 150], n_estimators=[150, 400, 800],
            k=F.CARRY_K, prior_gs=[False, True])
RULE = ("Use v2 for a site iff (a) v2 leave-one-year-out CV ln-RMSE averaged over the 2016-2022 folds <= v1's "
        "(v1 value from models/config_<site>.json) AND (b) in the strict check (train 2012-2019 Raccoon / "
        "2016-2019 Des Moines, test 2020-2025) v2's pooled ln-RMSE < that of the v1 feature set trained on the "
        "same years with v1's hyperparameters. Rule fixed before any 2026 metric was computed; 2026 not used.")


def fit(g, y, feats, alpha, hp, n=None, base=None, seed=7):
    return Q.fit(g, y, feats, alpha, F.monotone_vector_v2(feats), hp["num_leaves"], hp["min_child_samples"],
                 n or hp["n_estimators"], seed=seed, params=Q.BASE_PARAMS, base=base)


def rmse(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.sqrt(np.mean((a[m] - b[m]) ** 2)))


def cv_v2(g, base_feats, years, ok):
    y = g.lno3.values
    yrs = g.year.values
    res = []
    for nl, mcs, k, pg in itertools.product(GRID["num_leaves"], GRID["min_child_samples"], GRID["k"],
                                            GRID["prior_gs"]):
        feats = base_feats + F.carry_feats(k, pg)
        hp0 = dict(num_leaves=nl, min_child_samples=mcs)
        errs = {n: {} for n in GRID["n_estimators"]}
        for yr in years:
            tr = ok & (yrs != yr)
            te = ok & (yrs == yr)
            if te.sum() < 30:
                continue
            m = fit(g[tr], y[tr], feats, 0.5, hp0, n=max(GRID["n_estimators"]))
            for n in GRID["n_estimators"]:
                errs[n][yr] = rmse(m.predict(g[te], num_iteration=n), y[te])
        for n in GRID["n_estimators"]:
            e = errs[n]
            res.append(dict(num_leaves=nl, min_child_samples=mcs, n_estimators=n, k=k, prior_gs=pg,
                            cv_rmse_log=float(np.mean(list(e.values()))),
                            cv_rmse_log_2016_2022=float(np.mean([v for yy, v in e.items() if 2016 <= yy <= 2022])),
                            by_year={str(a): b for a, b in e.items()}))
    res.sort(key=lambda r: r["cv_rmse_log"])
    return res


def main():
    t0 = time.time()
    OUT2.mkdir(parents=True, exist_ok=True)
    MODELS2.mkdir(parents=True, exist_ok=True)
    fv = pd.read_parquet(F.OUT / "features_v2.parquet")
    mpath = F.OUT / "metrics.json"
    metrics = json.load(open(mpath))
    v2 = dict(description=("v2 (legacy-N): v1 monotone quantile GBM + causal N-carryover store features "
                           "(S_t = S_{t-1} exp(-D_t/k) + corn-share spring input, D = rain x GWETROOT^2), "
                           "Raccoon trained on 2012-2022 (nitrate from 2012-03-02), Des Moines on 2016-2022."),
              caveat=("v2 was designed AFTER seeing the v1 miss of the 2025 crisis, so its 2023-2025 test score "
                      "is NOT a clean out-of-time test. See strict_check for a stricter evaluation."),
              sites={})
    display = dict(rule=RULE, decided_before_2026_metrics=True, sites={})
    rows = []
    for site in ["05484500", "05482000"]:
        g = fv[(fv.site == site) & (fv.date >= f"{FIRST_YEAR[site]}-01-01")].sort_values("date").reset_index(drop=True)
        g["split"] = np.where(g.year <= TRAIN_END, "train", np.where(g.year <= 2025, "test", "live"))
        cfg1 = json.load(open(F.OUT / "models" / f"config_{site}.json"))
        hp1 = cfg1["hp"]
        base_feats = F.gbm_features(hp1["longmem"], hp1["cdl"])
        y = g.lno3.values
        yrs = g.year.values
        okx = g.rain_7.notna().values & g.logq.notna().values & g[F.carry_feats(1000, True)].notna().all(axis=1).values
        ok = (g.split == "train").values & okx & np.isfinite(y)
        train_years = list(range(FIRST_YEAR[site], TRAIN_END + 1))
        print(f"\n=== {site}: v2 CV over folds {train_years[0]}-{train_years[-1]} ({ok.sum()} train days)")
        cv = cv_v2(g, base_feats, train_years, ok)
        hp = cv[0]
        feats = base_feats + F.carry_feats(hp["k"], hp["prior_gs"])
        print(f"  best: leaves {hp['num_leaves']} mcs {hp['min_child_samples']} trees {hp['n_estimators']} "
              f"k {hp['k']} prior_gs {hp['prior_gs']}: CV {hp['cv_rmse_log']:.3f}, 2016-22 folds "
              f"{hp['cv_rmse_log_2016_2022']:.3f} (v1 {hp1['cv_rmse_log']:.3f})")
        # final quantile models
        b50 = fit(g[ok], y[ok], feats, 0.5, hp)
        b10 = fit(g[ok], y[ok], feats, 0.1, hp, base=b50)
        b90 = fit(g[ok], y[ok], feats, 0.9, hp, base=b50)
        b50.save(MODELS2 / f"gbm_{site}_q50.txt")
        b10.save(MODELS2 / f"gbm_{site}_q10.txt", base_file=f"gbm_{site}_q50.txt")
        b90.save(MODELS2 / f"gbm_{site}_q90.txt", base_file=f"gbm_{site}_q50.txt")
        # CQR with LOYO out-of-fold quantiles
        oof = np.full((len(g), 3), np.nan)
        for yr in train_years:
            tr = ok & (yrs != yr)
            te = (g.split == "train").values & okx & (yrs == yr)
            if te.sum() == 0:
                continue
            m50 = fit(g[tr], y[tr], feats, 0.5, hp)
            oof[te, 1] = m50.predict(g[te])
            oof[te, 0] = fit(g[tr], y[tr], feats, 0.1, hp, base=m50).predict(g[te])
            oof[te, 2] = fit(g[tr], y[tr], feats, 0.9, hp, base=m50).predict(g[te])
        mo = ok & np.isfinite(oof).all(axis=1)
        lo_ = np.minimum(oof[mo, 0], oof[mo, 1]); hi_ = np.maximum(oof[mo, 2], oof[mo, 1])
        sc = np.maximum(lo_ - y[mo], y[mo] - hi_)
        n = mo.sum()
        qhat = float(np.quantile(sc, min(1, np.ceil((n + 1) * 0.8) / n)))
        X = g[feats]
        r = np.column_stack([b10.predict(X), b50.predict(X), b90.predict(X)])
        r[~okx] = np.nan
        p50 = np.exp(r[:, 1])
        p10 = np.minimum(np.exp(np.minimum(r[:, 0], r[:, 1]) - qhat), p50)
        p90 = np.maximum(np.exp(np.maximum(r[:, 2], r[:, 1]) + qhat), p50)
        json.dump(dict(site=site, model_version="v2", features=feats, monotone=F.monotone_vector_v2(feats), hp=hp,
                       cqr_qhat_log=qhat, train_years=train_years, base_feature_groups=dict(longmem=hp1["longmem"],
                       cdl=hp1["cdl"]), base_params=Q.BASE_PARAMS),
                  open(MODELS2 / f"config_{site}.json", "w"), indent=1, default=float)

        # v1 daily (for side-by-side on identical days) + baselines from v1 file
        rd1 = pd.read_parquet(F.OUT / "river_daily.parquet")
        rd1 = rd1[rd1.site == site].set_index("date")
        out = pd.DataFrame(dict(site=site, date=g.date, obs=g.no3, q_cfs=g.q_cfs, p10=p10, p50=p50, p90=p90,
                                split=g.split, gbm_loyo_p50=np.exp(oof[:, 1]), cover_src=g.cover_src,
                                no3_qual=g.no3_qual))
        out["v1_p50"] = out.date.map(rd1.p50)
        out["v1_p10"] = out.date.map(rd1.p10)
        out["v1_p90"] = out.date.map(rd1.p90)
        out["clim_p50"] = out.date.map(rd1.clim_p50)
        # ---------------- level-corrected variants (use observed nitrate; absolute levels only)
        for lab, cols in (("v2", ("p10", "p50", "p90")), ("v1", ("v1_p10", "v1_p50", "v1_p90"))):
            pr = out[list(cols)].rename(columns=dict(zip(cols, ("p10", "p50", "p90"))))
            lc = river.level_correct(pr, out.obs, out.date)
            for c in ("p10", "p50", "p90"):
                out[f"lc_{lab}_{c}"] = lc[c].values
            out[f"lc_{lab}_factor"] = lc["level_factor"].values
        rows.append(out)

        # ---------------- PRE-REGISTERED blind check: 2013 (after the 2012 drought), Raccoon only.
        # Hyperparameters (incl. k) re-selected by LOYO CV with 2013 excluded everywhere; then predict 2013.
        blind = None
        if site == "05484500":
            yb = [yy for yy in train_years if yy != 2013]
            okb = ok & (yrs != 2013)
            cvb = cv_v2(g, base_feats, yb, okb)
            hpb = cvb[0]
            fb = base_feats + F.carry_feats(hpb["k"], hpb["prior_gs"])
            mb = fit(g[okb], y[okb], fb, 0.5, hpb)
            m1b = Q.fit(g[okb], y[okb], base_feats, 0.5, F.monotone_vector(base_feats), hp1["num_leaves"],
                        hp1["min_child_samples"], hp1["n_estimators"], params=Q.BASE_PARAMS)
            m13 = okx & (yrs == 2013) & np.isfinite(y)
            o13 = np.exp(y[m13])
            blind = dict(pre_registered=("2013 chosen by the verifier BEFORE v2 was fitted, as the analog of 2025 "
                                         "(record flush after the 2012 drought). v2 hyperparameters and k selected "
                                         "by LOYO CV without 2013."),
                         hp=dict((k, hpb[k]) for k in ("num_leaves", "min_child_samples", "n_estimators", "k",
                                                       "prior_gs")),
                         obs_days_over10=int((o13 > 10).sum()), n_obs_days=int(m13.sum()),
                         obs_peak=float(o13.max()))
            for name, mdl in (("v2", mb), ("v1_features", m1b)):
                p13 = np.exp(mdl.predict(g[m13]))
                blind[name] = dict(pred_days_over10=int((p13 > 10).sum()), NSE=M2.nse(o13, p13), KGE=M2.kge(o13, p13),
                                   bias=float(np.mean(p13 - o13)), pred_peak=float(p13.max()),
                                   rmse_log=rmse(np.log(p13), y[m13]))
            print(f"  BLIND 2013: obs days>10 {blind['obs_days_over10']} | v2 {blind['v2']['pred_days_over10']} "
                  f"(NSE {blind['v2']['NSE']:.2f}) | v1-feats {blind['v1_features']['pred_days_over10']} "
                  f"(NSE {blind['v1_features']['NSE']:.2f})")

        # ---------------- strict check (decided by rule; no 2026)
        strict_tr = ok & (yrs <= STRICT_END)
        strict = {}
        f1 = base_feats
        m_v2 = fit(g[strict_tr], y[strict_tr], feats, 0.5, hp)
        m_v1 = Q.fit(g[strict_tr], y[strict_tr], f1, 0.5, F.monotone_vector(f1), hp1["num_leaves"],
                     hp1["min_child_samples"], hp1["n_estimators"], params=Q.BASE_PARAMS)
        tr16 = strict_tr & (yrs >= 2016)
        m_v1_16 = Q.fit(g[tr16], y[tr16], f1, 0.5, F.monotone_vector(f1), hp1["num_leaves"],
                        hp1["min_child_samples"], hp1["n_estimators"], params=Q.BASE_PARAMS)
        preds = {"v2": m_v2.predict(g), "v1_features_same_years": m_v1.predict(g), "v1_features_2016_2019": m_v1_16.predict(g)}
        for lab, (a, b) in {"2020_2022": (2020, 2022), "2023_2025": (2023, 2025), "2020_2025": (2020, 2025)}.items():
            mm = okx & np.isfinite(y) & (yrs >= a) & (yrs <= b)
            strict[lab] = {}
            for name, pr in preds.items():
                o = np.exp(y[mm]); p = np.exp(pr[mm])
                strict[lab][name] = dict(rmse_log=rmse(pr[mm], y[mm]), NSE=M2.nse(o, p), KGE=M2.kge(o, p),
                                         bias=float(np.mean(p - o)), exceed10=M2.exceed(o, p), n=int(mm.sum()))
        strict["train_years"] = [int(yrs[strict_tr].min()), STRICT_END]
        print("  strict 2020-25 ln-RMSE: v2 {:.3f}  v1-feats same years {:.3f}  v1-feats 2016-19 {:.3f}".format(
            strict["2020_2025"]["v2"]["rmse_log"], strict["2020_2025"]["v1_features_same_years"]["rmse_log"],
            strict["2020_2025"]["v1_features_2016_2019"]["rmse_log"]))

        # ---------------- display decision (rule; computed before any 2026 metric below)
        cond_a = hp["cv_rmse_log_2016_2022"] <= hp1["cv_rmse_log"]
        cond_b = strict["2020_2025"]["v2"]["rmse_log"] < strict["2020_2025"]["v1_features_same_years"]["rmse_log"]
        choice = "v2" if (cond_a and cond_b) else "v1"
        display["sites"][site] = dict(model=choice, cv_v2_2016_2022=hp["cv_rmse_log_2016_2022"],
                                      cv_v1_2016_2022=hp1["cv_rmse_log"], cond_a_cv_no_worse=bool(cond_a),
                                      strict_v2=strict["2020_2025"]["v2"]["rmse_log"],
                                      strict_v1=strict["2020_2025"]["v1_features_same_years"]["rmse_log"],
                                      cond_b_strict_improves=bool(cond_b))
        print(f"  DISPLAY DECISION {site}: {choice} (a={cond_a}, b={cond_b})")

        # ---------------- metrics (same as v1) incl. 2026
        sm = dict(hyperparameters={k: hp[k] for k in ["num_leaves", "min_child_samples", "n_estimators", "k",
                                                      "prior_gs"]},
                  features=feats, train_years=[train_years[0], train_years[-1]],
                  cv_top5=[{k: c[k] for k in ["num_leaves", "min_child_samples", "n_estimators", "k", "prior_gs",
                                               "cv_rmse_log", "cv_rmse_log_2016_2022"]} for c in cv[:5]],
                  cv_best_by_year=hp["by_year"], cqr_qhat_log=qhat, splits={}, strict_check=strict,
                  blind_2013=blind,
                  labels=dict(test="post-hoc (v2 designed after seeing the v1 2025 miss)", live="post-hoc"))
        o_all = out.obs.values
        for sp in ["train", "test", "live"]:
            msp = (out.split == sp).values & (out.date.dt.year >= 2016).values  # v1-comparable days
            sm["splits"][sp] = dict(
                gbm_v2=M2.metric_block(o_all[msp], out.p50.values[msp], out.p10.values[msp], out.p90.values[msp]),
                gbm_v1=M2.metric_block(o_all[msp], out.v1_p50.values[msp], out.v1_p10.values[msp], out.v1_p90.values[msp]))
            if sp == "train":
                sm["splits"][sp]["gbm_v2_loyo_cv"] = M2.metric_block(o_all[msp], out.gbm_loyo_p50.values[msp])
                pre = (out.split == "train").values & (out.date.dt.year < 2016).values
                if np.isfinite(o_all[pre]).sum() > 30:
                    sm["splits"]["train_2012_2015_loyo"] = M2.metric_block(o_all[pre], out.gbm_loyo_p50.values[pre])
        sm["test_by_year"] = {str(yy): {mn: {k: v for k, v in M2.metric_block(o_all[mm], out[c].values[mm]).items()
                                             if k in ("n", "NSE", "KGE", "RMSE", "bias")}
                                        for mn, c in (("gbm_v2", "p50"), ("gbm_v1", "v1_p50"))}
                              for yy in (2023, 2024, 2025) for mm in [(out.date.dt.year == yy).values]}
        o16 = out[out.date >= "2016-01-01"]
        sm["crisis_2025"] = {"gbm_v2": M2.event_block(o16, "p50", 2025, "p90"),
                             "gbm_v1": M2.event_block(o16, "v1_p50", 2025, "v1_p90")}
        sm["live_2026"] = {"gbm_v2": M2.event_block(o16, "p50", 2026, "p90"),
                           "gbm_v1": M2.event_block(o16, "v1_p50", 2026, "v1_p90")}
        sm["residual_diagnostics"] = M2.residual_diagnostics(out.assign(split=out.split))
        lcb = {}
        for lab in ("v2", "v1"):
            lcb[lab] = {}
            for sp in ("test", "live"):
                msp = (out.split == sp).values
                lcb[lab][sp] = M2.metric_block(o_all[msp], out[f"lc_{lab}_p50"].values[msp],
                                               out[f"lc_{lab}_p10"].values[msp], out[f"lc_{lab}_p90"].values[msp])
            lcb[lab]["crisis_2025"] = M2.event_block(o16, f"lc_{lab}_p50", 2025, f"lc_{lab}_p90")
            lcb[lab]["live_2026"] = M2.event_block(o16, f"lc_{lab}_p50", 2026, f"lc_{lab}_p90")
        sm["level_corrected"] = dict(
            method=("p10/p50/p90 x exp(median ln(obs/p50) over the 60 days ending 1 day before t); >= 10 obs "
                    "needed. Uses measured nitrate (nowcast-style) - for absolute levels only; the driver-only "
                    "model stays the basis for relative what-ifs. Compare with persistence_7d/14d in v1 metrics."),
            **lcb)
        v2["sites"][site] = sm
        for sp in ["test", "live"]:
            a, b = sm["splits"][sp]["gbm_v2"], sm["splits"][sp]["gbm_v1"]
            print(f"  {sp}: v2 NSE {a['NSE']:.2f} KGE {a['KGE']:.2f} cov {a['coverage80']:.2f} | "
                  f"v1 NSE {b['NSE']:.2f} KGE {b['KGE']:.2f}")
        c = sm["crisis_2025"]
        print(f"  2025 days>10: obs {c['gbm_v2']['obs_days_over10']} v2 {c['gbm_v2']['pred_days_over10_on_obs_days']} "
              f"v1 {c['gbm_v1']['pred_days_over10_on_obs_days']} | level-corrected v2 "
              f"{lcb['v2']['crisis_2025']['pred_days_over10_on_obs_days']} v1 "
              f"{lcb['v1']['crisis_2025']['pred_days_over10_on_obs_days']}")

    river2 = pd.concat(rows, ignore_index=True)
    river2.to_parquet(OUT2 / "river_daily_v2.parquet", compression="zstd", index=False)
    metrics = json.load(open(mpath))  # re-read: never modify v1 keys
    metrics["v2"] = v2
    metrics["display_model"] = display
    json.dump(metrics, open(mpath, "w"), indent=1, default=float)
    print(f"\nwrote v2/river_daily_v2.parquet, models_v2/, metrics.json['v2','display_model'] [{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
