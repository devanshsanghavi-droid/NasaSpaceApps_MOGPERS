"""Model v2 (POST-HOC) and honesty checks.

v1 (fit_loss.py) is the pre-registered headline and is left untouched (snapshot in model/outputs/v1/).
v2 = v1 + multi-season NASA POWER features (planting-time root-zone wetness, prior Oct-Mar precipitation, prior-fall
root-zone wetness, winter-wheat window). The feature idea came AFTER seeing v1's 2022-23 shortfall, so v2 is labelled
"post-hoc" everywhere. Feature-set choice inside v2: leave-one-year-out CV within 2001-2020 only, same rule as v1.

Extra tests (both v1 and v2, plus the two baselines):
  * second out-of-time test: train 2001-2011, predict 2012 (2012 was not used to decide the v2 features; note that the
    2001-2020 LOYO CV used for choosing configurations does contain 2012 as one fold, for v1 and v2 alike);
  * 2021-2024 as before (train 2001-2020).
Calibrated prediction intervals (replace parameter-bootstrap bands as PREDICTION intervals):
  * county level: split-conformal, Mondrian by predicted-value bin: from leave-one-year-out out-of-fold residuals
    (actual - predicted, principal $/insured acre) in the training years, 10 bins of the out-of-fold prediction;
    interval = [max(0, pred + q05_bin), pred + q95_bin] (nominal 90%);
  * region annual totals: 5th/95th percentile of log(actual/predicted) of the out-of-fold region-year totals.
Decision rule (fixed before running the holdout): v2 is used in the app only if its 2001-2020 LOYO CV RMSE AND its
2012-holdout county RMSE are both lower than v1's; otherwise the app keeps v1.

Run: python model/fit_v2.py --stage cv ; python model/fit_v2.py --stage eval
Outputs: model/outputs/cv_results_v2.json, model_config.json (adds v2, app), validation.json (v1 nested + v2 + holdout +
intervals + decision), web/data/hindcast.json (v1 fields kept, v2 fields added), hindcast_county.parquet (app model)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import MIN_ACRES_PRINCIPAL, OUT, STATES, TEST_YEARS, WEB, save_json  # noqa: E402
from fit_loss import county_metrics, lcr_metrics, loyo, year_totals  # noqa: E402
from lossmodel import fit_predict, load_crop_panel, to_principal  # noqa: E402

POSTHOC = "post-hoc (feature idea came after seeing the 2022-23 shortfall)"


def v1_cfg():
    return json.load(open(OUT / "v1" / "model_config.json"))["main"]


def v2_candidates():
    b = {k: v for k, v in v1_cfg().items() if k != "name"}
    return [
        {**b, "name": "v2_ms_wwwheat", "ms": True, "ww": "wheat"},
        {**b, "name": "v2_ms_wwall", "ms": True, "ww": "all"},
        {**b, "name": "v2_ms_nofall_wwwheat", "ms": True, "ms_no_fall": True, "ww": "wheat"},
        {**b, "name": "v2_ms_only", "ms": True},
    ]


def cv_summary(oof):
    pc = to_principal(oof)
    m = county_metrics(pc)
    m["lcr"] = lcr_metrics(pc)
    yt = year_totals(pc)
    m["year_total_median_ape"] = float(yt.ape.median())
    m["year_totals_musd"] = {int(y): [round(a / 1e6, 1), round(b / 1e6, 1)] for y, a, b in
                             zip(yt.index, yt.pred_usd, yt.actual_usd)}
    m["corn"] = county_metrics(to_principal(oof[oof.crop == "corn"]))
    return m


def stage_cv():
    data = load_crop_panel()
    years = list(range(2001, 2021))
    res = {}
    v1 = json.load(open(OUT / "cv_results.json"))["results"][v1_cfg()["name"]]
    res["v1 (" + v1_cfg()["name"] + ")"] = {k: v1[k] for k in ("rmse", "mae", "r2", "spearman", "total_bias_pct",
                                                               "year_total_median_ape")}
    (OUT / "cv_oof").mkdir(exist_ok=True)
    for cfg in v2_candidates():
        oof = loyo(cfg, data, years)
        oof[["fips", "crop", "year", "pred"]].to_parquet(OUT / "cv_oof" / f"{cfg['name']}.parquet", index=False)
        m = cv_summary(oof)
        m["cfg"] = cfg
        res[cfg["name"]] = m
        print(f"{cfg['name']:24s} rmse={m['rmse']:.3f} mae={m['mae']:.3f} r2={m['r2']:.3f} sp={m['spearman']:.3f} "
              f"yrAPE={m['year_total_median_ape']:.1f} bias={m['total_bias_pct']:.1f}", flush=True)
        save_json({"label": POSTHOC, "results": res}, OUT / "cv_results_v2.json", 1)
    best = min([c["name"] for c in v2_candidates()], key=lambda n: res[n]["rmse"])
    print("selected v2:", best)
    save_json({"label": POSTHOC, "selection_rule": "lowest pooled LOYO county RMSE (principal $/ac), 2001-2020",
               "selected": best, "results": res}, OUT / "cv_results_v2.json", 1)
    mc = json.load(open(OUT / "model_config.json"))
    mc["main"] = v1_cfg()  # v1 stays the pre-registered main
    mc["v2"] = next(c for c in v2_candidates() if c["name"] == best)
    mc["v2"]["label"] = POSTHOC
    save_json(mc, OUT / "model_config.json", 1)


# ------------------------------------------------------------------ prediction intervals
def principal_oof(oof_crop, data):
    d = data.merge(oof_crop[["fips", "crop", "year", "pred"]], on=["fips", "crop", "year"], how="inner")
    return to_principal(d)


def fit_conformal(pc_oof, nbins=10):
    d = pc_oof[pc_oof.insured_acres >= MIN_ACRES_PRINCIPAL]
    yhat = (d.pred_usd / d.insured_acres).to_numpy()
    y = (d.actual_usd / d.insured_acres).to_numpy()
    edges = np.unique(np.quantile(yhat, np.linspace(0, 1, nbins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    b = np.digitize(yhat, edges[1:-1])
    q = {}
    for k in range(len(edges) - 1):
        r = (y - yhat)[b == k]
        q[k] = (float(np.quantile(r, 0.05)), float(np.quantile(r, 0.95)), int(len(r)))
    # region totals
    yt = pc_oof.groupby("year")[["pred_usd", "actual_usd"]].sum()
    lr = np.log(yt.actual_usd / yt.pred_usd)
    return {"edges": edges.tolist(), "q": q, "tot_q05": float(np.quantile(lr, 0.05)),
            "tot_q95": float(np.quantile(lr, 0.95)), "n_years": int(len(yt)), "n_county_years": int(len(d))}


def apply_conformal(cf, pred_per_ac):
    edges = np.array(cf["edges"])
    b = np.digitize(pred_per_ac, edges[1:-1])
    lo = np.array([cf["q"][k][0] for k in b])
    hi = np.array([cf["q"][k][1] for k in b])
    return np.maximum(0, pred_per_ac + lo), pred_per_ac + hi


def coverage(pc, cf):
    d = pc[pc.insured_acres >= MIN_ACRES_PRINCIPAL]
    p = (d.pred_usd / d.insured_acres).to_numpy()
    a = (d.actual_usd / d.insured_acres).to_numpy()
    lo, hi = apply_conformal(cf, p)
    cov = (a >= lo) & (a <= hi)
    out = {"pooled": float(cov.mean()), "n": int(len(d)), "mean_width_usd_per_ac": float(np.mean(hi - lo))}
    out["by_year"] = {int(y): float(cov[(d.year == y).to_numpy()].mean()) for y in sorted(d.year.unique())}
    return out


# ------------------------------------------------------------------ evaluation
def stage_eval():
    mc = json.load(open(OUT / "model_config.json"))
    v1, v2 = mc["main"], mc["v2"]
    M0, M1 = mc["baseline_mean"], mc["baseline_hazard_only"]
    models = {"v1": v1, "v2": v2, "baseline_mean": M0, "baseline_hazard_only": M1}
    data = load_crop_panel()
    out = {"labels": {"v1": "pre-registered headline (features fixed before any test year was seen)",
                      "v2": POSTHOC}, "configs": models}
    # ---- calibration sets: LOYO out-of-fold residuals
    oof20 = {"v1": pd.read_parquet(OUT / "cv_oof" / f"{v1['name']}.parquet"),
             "v2": pd.read_parquet(OUT / "cv_oof" / f"{v2['name']}.parquet")}
    cf20 = {k: fit_conformal(principal_oof(v, data)) for k, v in oof20.items()}
    yrs11 = list(range(2001, 2012))
    cf11 = {}
    for k in ("v1", "v2"):
        oof = loyo(models[k], data, yrs11)
        cf11[k] = fit_conformal(to_principal(oof))
        print("calib <=2011", k, "done", flush=True)
    # ---- tests
    tests = {"2012_holdout": (range(2001, 2012), [2012], cf11), "2021_2024": (range(2001, 2021), TEST_YEARS, cf20)}
    hc_store = {}
    for tname, (tr_years, te_years, cf) in tests.items():
        train = data[data.year.isin(list(tr_years))]
        test = data[data.year.isin(te_years)]
        res = {"train_years": [min(tr_years), max(tr_years)], "test_years": list(te_years), "models": {}}
        for k, cfg in models.items():
            p, _ = fit_predict(cfg, train, test)
            pc = to_principal(test.assign(pred=p))
            r = county_metrics(pc)
            r["lcr"] = lcr_metrics(pc)
            r["corn"] = county_metrics(to_principal(test.assign(pred=p)[test.crop == "corn"]))
            r["by_year"] = {}
            for y in te_years:
                g = pc[pc.year == y]
                yr = {"pred_total_usd": float(g.pred_usd.sum()), "actual_total_usd": float(g.actual_usd.sum()),
                      "county": county_metrics(g)}
                if k in cf:
                    yr["pi90_lo"] = float(g.pred_usd.sum() * np.exp(cf[k]["tot_q05"]))
                    yr["pi90_hi"] = float(g.pred_usd.sum() * np.exp(cf[k]["tot_q95"]))
                    yr["actual_inside_pi"] = bool(yr["pi90_lo"] <= yr["actual_total_usd"] <= yr["pi90_hi"])
                r["by_year"][int(y)] = yr
            r["by_state"] = [{"state": s, "year": int(y), "pred_total_usd": float(g.pred_usd.sum()),
                              "actual_total_usd": float(g.actual_usd.sum())}
                             for (y, s), g in pc.groupby(["year", "state_abbr"])]
            if k in cf:
                r["county_pi90_coverage"] = coverage(pc, cf[k])
            res["models"][k] = r
            hc_store[(tname, k)] = (pc, test.assign(pred=p))
            print(tname, k, {m: round(r[m], 3) for m in ("mae", "rmse", "r2", "spearman", "total_bias_pct")},
                  {y: (round(v["pred_total_usd"] / 1e6), round(v["actual_total_usd"] / 1e6))
                   for y, v in r["by_year"].items()}, flush=True)
        out[tname] = res
    out["calibration"] = {"county": "split-conformal, Mondrian by 10 bins of predicted principal $/insured acre, "
                                    "from LOYO out-of-fold residuals in the training years; nominal 90%",
                          "region_total": "5th/95th pct of log(actual/pred) of LOYO out-of-fold region-year totals",
                          "fit_on_2001_2020": {k: {kk: v[kk] for kk in ("tot_q05", "tot_q95", "n_years",
                                                                         "n_county_years")} for k, v in cf20.items()},
                          "fit_on_2001_2011": {k: {kk: v[kk] for kk in ("tot_q05", "tot_q95", "n_years",
                                                                         "n_county_years")} for k, v in cf11.items()},
                          "note": "With 20 (11) training years the 5th/95th percentiles of the year-total ratio are "
                                  "close to the most extreme observed ratios."}
    # ---- decision
    cvv2 = json.load(open(OUT / "cv_results_v2.json"))["results"][v2["name"]]["rmse"]
    cvv1 = json.load(open(OUT / "cv_results.json"))["results"][v1["name"]]["rmse"]
    h1 = out["2012_holdout"]["models"]["v1"]["rmse"]
    h2 = out["2012_holdout"]["models"]["v2"]["rmse"]
    use_v2 = (cvv2 < cvv1) and (h2 < h1)
    out["decision"] = {"rule": "use v2 only if LOYO CV RMSE (2001-2020) AND 2012-holdout county RMSE are both lower "
                               "than v1's", "cv_rmse": {"v1": cvv1, "v2": cvv2},
                       "holdout_2012_rmse": {"v1": h1, "v2": h2}, "app_model": "v2" if use_v2 else "v1"}
    app = "v2" if use_v2 else "v1"
    print("decision:", out["decision"])
    mc["app"] = dict(models[app])
    mc["app"]["version"] = app
    save_json(mc, OUT / "model_config.json", 1)
    # ---- county hindcast for the app model (2021-2024) with calibrated PIs
    pc, crop = hc_store[("2021_2024", app)]
    pc = pc.copy()
    lo, hi = apply_conformal(cf20[app], (pc.pred_usd / pc.insured_acres.replace(0, np.nan)).fillna(0).to_numpy())
    pc["pi90_lo"] = lo * pc.insured_acres
    pc["pi90_hi"] = hi * pc.insured_acres
    pc["lo"], pc["hi"] = pc.pi90_lo, pc.pi90_hi
    for k in ("v1", "v2", "baseline_mean", "baseline_hazard_only"):
        pc[f"pred_usd_{k}"] = hc_store[("2021_2024", k)][0].pred_usd.to_numpy()
    pc["model_version"] = app
    pc.to_parquet(OUT / "hindcast_county.parquet", index=False)
    crop[["fips", "crop", "year", "liability_usd", "insured_acres", "indem_drought_usd", "pred"]].to_parquet(
        OUT / "hindcast_crop.parquet", index=False)
    save_json({"cf20": cf20, "cf11": cf11}, OUT / "conformal_params.json", 1)
    # ---- validation.json: v1 nested untouched + v2 + holdout + intervals
    v1val = json.load(open(OUT / "v1" / "validation_v1.json"))
    cv2 = json.load(open(OUT / "cv_results_v2.json"))
    val = {"v1": v1val, "v2_and_holdout": out, "cv_v2": cv2, "app_model": app,
           "note": "v1 = pre-registered headline (unchanged). v2 = " + POSTHOC + "."}
    save_json(val, OUT / "validation.json", 1)
    # ---- hindcast.json: keep v1 fields, add v2 + holdout + calibrated intervals
    h = json.load(open(OUT / "v1" / "hindcast_v1.json"))
    h["v1_label"] = out["labels"]["v1"]
    t = out["2021_2024"]["models"]
    h["v2"] = {"label": POSTHOC, "metrics": {k: {m: t[k][m] for m in ("n", "mae", "rmse", "r2", "spearman",
                                                                     "total_bias_pct")} for k in t},
               "by_year": {y: {kk: v[kk] for kk in ("pred_total_usd", "actual_total_usd", "pi90_lo", "pi90_hi")}
                           for y, v in t["v2"]["by_year"].items()},
               "by_state": [r for r in t["v2"]["by_state"]]}
    h["v1_prediction_interval_by_year"] = {y: {kk: v[kk] for kk in ("pred_total_usd", "pi90_lo", "pi90_hi",
                                                                     "actual_total_usd", "actual_inside_pi")}
                                           for y, v in t["v1"]["by_year"].items()}
    ho = out["2012_holdout"]["models"]
    h["holdout_2012"] = {"train_years": [2001, 2011], "test_year": 2012,
                         "note": "second out-of-time test; 2012 was not used to decide the v2 features (the "
                                 "2001-2020 CV used to pick configurations includes 2012 as one fold)",
                         "metrics": {k: {m: ho[k][m] for m in ("n", "mae", "rmse", "r2", "spearman", "total_bias_pct")}
                                     for k in ho},
                         "total": {k: {kk: v for kk, v in ho[k]["by_year"][2012].items() if kk != "county"}
                                   for k in ho}}
    h["prediction_intervals"] = {"method": out["calibration"]["county"] + "; " + out["calibration"]["region_total"],
                                 "county_coverage_2021_2024": {k: t[k]["county_pi90_coverage"] for k in ("v1", "v2")},
                                 "county_coverage_2012": {k: ho[k]["county_pi90_coverage"] for k in ("v1", "v2")},
                                 "bootstrap_note": "the older lo/hi in by_year/by_state are parameter-bootstrap ranges "
                                                   "(v1), NOT prediction intervals"}
    h["app_model"] = app
    h["decision"] = out["decision"]
    save_json(h, WEB / "hindcast.json", 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["cv", "eval"], required=True)
    a = ap.parse_args()
    stage_cv() if a.stage == "cv" else stage_eval()
