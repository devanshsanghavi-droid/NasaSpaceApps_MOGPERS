"""Loss model selection (leave-one-year-out CV inside 2001-2020 ONLY) and the out-of-time test (train <= 2020,
test 2021-2024) against baseline_mean (M0) and baseline_hazard_only (M1).

Selection rule (fixed before looking at any test year): lowest pooled county-level RMSE of principal-crop drought
indemnity in $/insured acre over the 20 leave-one-year-out folds (county-years with >= 2,000 principal insured acres).
Test years 2021-2024 are touched exactly once, after the choice, by `--stage test`.

Outputs: model/outputs/cv_results.json, model/outputs/model_config.json, model/outputs/validation.json,
         model/outputs/hindcast_county.parquet, web/data/hindcast.json
Run: python model/fit_loss.py --stage cv ; python model/fit_loss.py --stage test
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from common import (MIN_ACRES_PRINCIPAL, OUT, STATES, TEST_YEARS, TRAIN_END, WEB, save_json)  # noqa: E402
from lossmodel import fit_predict, load_crop_panel, to_principal  # noqa: E402

M0 = {"name": "baseline_mean", "kind": "mean", "k": 5.0}
M1 = {"name": "baseline_hazard_only", "kind": "lgb", "hazard": "full", "n": 400, "leaves": 15}

CANDIDATES = [
    {"name": "lgb_haz_static", "kind": "lgb", "hazard": "full", "static": True},
    {"name": "lgb_haz_static_enc", "kind": "lgb", "hazard": "full", "static": True, "enc": True, "k": 5.0},
    {"name": "lgb_haz_static_enc_k2", "kind": "lgb", "hazard": "full", "static": True, "enc": True, "k": 2.0},
    {"name": "lgb_haz_static_enc_k10", "kind": "lgb", "hazard": "full", "static": True, "enc": True, "k": 10.0},
    {"name": "lgb_haz_static_enc_year", "kind": "lgb", "hazard": "full", "static": True, "enc": True, "k": 5.0,
     "year": True},
    {"name": "lgb_small_static_enc", "kind": "lgb", "hazard": "small", "static": True, "enc": True, "k": 5.0},
    {"name": "lgb_haz_static_enc_state", "kind": "lgb", "hazard": "full", "static": True, "enc": True, "k": 5.0,
     "state": True},
    {"name": "lgb_haz_static_enc_l31", "kind": "lgb", "hazard": "full", "static": True, "enc": True, "k": 5.0,
     "leaves": 31, "n": 400},
    {"name": "lgb_haz_static_enc_n800", "kind": "lgb", "hazard": "full", "static": True, "enc": True, "k": 5.0,
     "n": 800},
    {"name": "lgb_haz_static_enc_tvp12", "kind": "lgb", "hazard": "full", "static": True, "enc": True, "k": 5.0,
     "tvp": 1.2},
    {"name": "lgb_haz_static_enc_tvp18", "kind": "lgb", "hazard": "full", "static": True, "enc": True, "k": 5.0,
     "tvp": 1.8},
    {"name": "glm_spline_enc", "kind": "glm", "k": 5.0},
]
CANDIDATES += [  # second batch, added after batch 1 (still CV inside 2001-2020 only): batch 1 showed the county
    # mean encoding hurts (it is confounded by each county's 2012 exposure), so try no-encoding variants and a
    # hazard-relative (credibility ratio) encoding
    {"name": "lgb_haz_static_tvp12", "kind": "lgb", "hazard": "full", "static": True, "tvp": 1.2},
    {"name": "lgb_haz_static_l31", "kind": "lgb", "hazard": "full", "static": True, "leaves": 31},
    {"name": "lgb_haz_static_n800", "kind": "lgb", "hazard": "full", "static": True, "n": 800},
    {"name": "lgb_haz_static_state", "kind": "lgb", "hazard": "full", "static": True, "state": True},
    {"name": "ratio_haz_static_a1", "kind": "ratio", "hazard": "full", "static": True, "k": 5.0, "alpha_r": 1.0},
    {"name": "ratio_haz_static_a05", "kind": "ratio", "hazard": "full", "static": True, "k": 5.0, "alpha_r": 0.5},
]
ABLATIONS = [  # reported, never used for selection of the headline model
    {"name": "ablation_plus_usdm", "kind": "lgb", "hazard": "full", "static": True, "usdm": True},
]


# ------------------------------------------------------------------ metrics
def county_metrics(pc, pred="pred_usd", act="actual_usd", per="insured_acres"):
    d = pc[pc.insured_acres >= MIN_ACRES_PRINCIPAL]
    yp = d[pred] / d[per]
    ya = d[act] / d[per]
    e = yp - ya
    out = {
        "n": int(len(d)),
        "mae": float(np.mean(np.abs(e))),
        "rmse": float(np.sqrt(np.mean(e ** 2))),
        "r2": float(1 - np.sum(e ** 2) / np.sum((ya - ya.mean()) ** 2)),
        "spearman": float(stats.spearmanr(yp, ya).correlation),
        "total_bias_pct": float(100 * (pc[pred].sum() - pc[act].sum()) / pc[act].sum()),
    }
    return out


def lcr_metrics(pc):
    d = pc[pc.insured_acres >= MIN_ACRES_PRINCIPAL]
    yp = d.pred_usd / d.liability_usd
    ya = d.actual_usd / d.liability_usd
    e = yp - ya
    return {"mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e ** 2))),
            "r2": float(1 - np.sum(e ** 2) / np.sum((ya - ya.mean()) ** 2)),
            "spearman": float(stats.spearmanr(yp, ya).correlation)}


def by_year_spearman(pc):
    d = pc[pc.insured_acres >= MIN_ACRES_PRINCIPAL]
    return float(np.mean([stats.spearmanr(g.pred_usd / g.insured_acres, g.actual_usd / g.insured_acres).correlation
                          for _, g in d.groupby("year") if g.actual_usd.sum() > 0]))


def year_totals(pc):
    t = pc.groupby("year")[["pred_usd", "actual_usd"]].sum()
    t["ape"] = 100 * np.abs(t.pred_usd - t.actual_usd) / t.actual_usd
    return t


# ------------------------------------------------------------------ CV
def loyo(cfg, data, years):
    parts = []
    for y in years:
        tr = data[(data.year != y) & data.year.isin(years)]
        te = data[data.year == y]
        p, _ = fit_predict(cfg, tr, te)
        parts.append(te.assign(pred=p))
    return pd.concat(parts)


def stage_cv():
    data = load_crop_panel()
    years = list(range(2001, TRAIN_END + 1))
    res, oof_store = {}, {}
    prev = OUT / "cv_results_partial.json"
    if prev.exists():  # incremental: keep earlier results, run only configs not yet evaluated
        res = json.load(open(prev))["results"]
        for k in list(res):
            fp = OUT / "cv_oof" / f"{k}.parquet"
            if fp.exists():
                oof_store[k] = pd.read_parquet(fp)
            else:
                res.pop(k)
    for cfg in [M0, M1] + CANDIDATES + ABLATIONS:
        if cfg["name"] in res and res[cfg["name"]]["cfg"] == cfg:
            continue
        t0 = time.time()
        oof = loyo(cfg, data, years)
        pc = to_principal(oof)
        m = county_metrics(pc)
        m["lcr"] = lcr_metrics(pc)
        m["mean_within_year_spearman"] = by_year_spearman(pc)
        yt = year_totals(pc)
        m["year_total_median_ape"] = float(yt.ape.median())
        m["year_total_mean_ape"] = float(yt.ape.mean())
        m["year_total_corr"] = float(np.corrcoef(yt.pred_usd, yt.actual_usd)[0, 1])
        m["year_totals_musd"] = {int(y): [round(a / 1e6, 1), round(b / 1e6, 1)] for y, a, b in
                                 zip(yt.index, yt.pred_usd, yt.actual_usd)}
        corn = oof[oof.crop == "corn"]
        m["corn"] = county_metrics(to_principal(corn))
        m["cfg"] = cfg
        m["seconds"] = round(time.time() - t0, 1)
        res[cfg["name"]] = m
        oof_store[cfg["name"]] = oof[["fips", "crop", "year", "pred"]]
        (OUT / "cv_oof").mkdir(exist_ok=True)
        oof_store[cfg["name"]].to_parquet(OUT / "cv_oof" / f"{cfg['name']}.parquet", index=False)
        save_json({"results": res}, OUT / "cv_results_partial.json", 1)
        print(f"{cfg['name']:32s} rmse={m['rmse']:.3f} mae={m['mae']:.3f} r2={m['r2']:.3f} sp={m['spearman']:.3f} "
              f"wy_sp={m['mean_within_year_spearman']:.3f} yrAPE_med={m['year_total_median_ape']:.1f} "
              f"bias={m['total_bias_pct']:.1f} corn_rmse={m['corn']['rmse']:.3f} ({m['seconds']}s)", flush=True)
    cands = [c["name"] for c in CANDIDATES]
    best = min(cands, key=lambda n: res[n]["rmse"])
    print("selected:", best)
    save_json({"selection_rule": "lowest pooled LOYO county-level RMSE of principal-crop $/insured acre, "
                                 "2001-2020 only", "selected": best, "results": res}, OUT / "cv_results.json", 1)
    cfg = dict(next(c for c in CANDIDATES if c["name"] == best))
    save_json({"main": cfg, "baseline_mean": M0, "baseline_hazard_only": M1}, OUT / "model_config.json", 1)
    pd.concat([v.assign(model=k) for k, v in oof_store.items()]).to_parquet(OUT / "cv_oof.parquet", index=False)


# ------------------------------------------------------------------ test
def boot_years(train_years, rng):
    return rng.choice(train_years, size=len(train_years), replace=True)


def resample_by_years(data, yrs):
    parts = []
    for i, y in enumerate(yrs):
        parts.append(data[data.year == y])
    return pd.concat(parts, ignore_index=True)


def stage_test(B=100):
    cfgs = json.load(open(OUT / "model_config.json"))
    data = load_crop_panel()
    train = data[data.year <= TRAIN_END]
    test = data[data.year.isin(TEST_YEARS)]
    train_years = np.arange(2001, TRAIN_END + 1)
    rng = np.random.default_rng(20261114)
    models = {"model": cfgs["main"], "baseline_mean": cfgs["baseline_mean"],
              "baseline_hazard_only": cfgs["baseline_hazard_only"]}
    preds = {}
    boots = {}
    for key, cfg in models.items():
        p, _ = fit_predict(cfg, train, test)
        preds[key] = p
        bs = np.zeros((B, len(test)))
        for b in range(B):
            yrs = boot_years(train_years, rng)
            trb = resample_by_years(train, yrs)
            bs[b], _ = fit_predict(cfg, trb, test, seed=b)
        boots[key] = bs
        print(key, "done", flush=True)
    np.savez_compressed(OUT / "hindcast_boot.npz", **boots)
    # --- assemble
    out = {"train_years": [2001, TRAIN_END], "test_years": TEST_YEARS,
           "metrics_units": "USD per insured acre (principal crops: corn+soybeans+wheat+sorghum, nominal USD); "
                            "r2/spearman unitless; total_bias_pct in percent",
           "unit_of_analysis": "county x year, principal crops, counties with >= 2,000 insured acres",
           "metrics": {}, "metrics_lcr": {}, "metrics_ci": {}, "by_year": {}, "by_state": [],
           "by_year_models": {}, "metrics_by_year": {}, "metrics_corn": {}}
    test = test.copy()
    pcs = {}
    for key in models:
        t = test.assign(pred=preds[key])
        pc = to_principal(t)
        # bootstrap principal predictions
        bt = np.stack([to_principal(test.assign(pred=boots[key][b])).pred_usd.to_numpy() for b in range(B)])
        pc["lo"] = np.percentile(bt, 5, axis=0)
        pc["hi"] = np.percentile(bt, 95, axis=0)
        pcs[key] = (pc, bt)
        out["metrics"][key] = county_metrics(pc)
        out["metrics_lcr"][key] = lcr_metrics(pc)
        out["metrics_corn"][key] = county_metrics(to_principal(t[t.crop == "corn"]))
        out["metrics_by_year"][key] = {int(y): county_metrics(g) for y, g in pc.groupby("year")}
        out["by_year_models"][key] = {}
        for y in TEST_YEARS:
            m = (pc.year == y).to_numpy()
            tot_b = bt[:, m].sum(axis=1)
            out["by_year_models"][key][int(y)] = {
                "pred_total_usd": float(pc.pred_usd[m].sum()), "lo": float(np.percentile(tot_b, 5)),
                "hi": float(np.percentile(tot_b, 95)), "actual_total_usd": float(pc.actual_usd[m].sum())}
    # metric CIs: bootstrap over counties (B=1000), with paired model-minus-baseline differences
    rng2 = np.random.default_rng(7)
    base = pcs["model"][0]
    keep = base.insured_acres >= MIN_ACRES_PRINCIPAL
    fipsu = base.loc[keep, "fips"].unique()
    idx_by_f = {f: np.where((base.fips == f).to_numpy() & keep.to_numpy())[0] for f in fipsu}
    acts = (base.actual_usd / base.insured_acres).to_numpy()
    pr = {k: (pcs[k][0].pred_usd / pcs[k][0].insured_acres).to_numpy() for k in models}
    stat = {k: {"mae": [], "rmse": [], "r2": [], "spearman": []} for k in models}
    diff = {k: {"mae": [], "rmse": []} for k in ["baseline_mean", "baseline_hazard_only"]}
    for _ in range(1000):
        fs = rng2.choice(fipsu, size=len(fipsu), replace=True)
        ii = np.concatenate([idx_by_f[f] for f in fs])
        a = acts[ii]
        vals = {}
        for k in models:
            e = pr[k][ii] - a
            vals[k] = (np.mean(np.abs(e)), np.sqrt(np.mean(e ** 2)))
            stat[k]["mae"].append(vals[k][0])
            stat[k]["rmse"].append(vals[k][1])
            stat[k]["r2"].append(1 - np.sum(e ** 2) / np.sum((a - a.mean()) ** 2))
            stat[k]["spearman"].append(stats.spearmanr(pr[k][ii], a).correlation)
        for k in diff:
            diff[k]["mae"].append(vals["model"][0] - vals[k][0])
            diff[k]["rmse"].append(vals["model"][1] - vals[k][1])
    for k in models:
        out["metrics_ci"][k] = {m: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
                                for m, v in stat[k].items()}
    out["metrics_ci"]["model_minus_baseline"] = {
        k: {m: {"est": float(np.mean(v)), "ci95": [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]}
            for m, v in d.items()} for k, d in diff.items()}
    out["by_year"] = out["by_year_models"]["model"]
    pc, bt = pcs["model"]
    for y in TEST_YEARS:
        for s in STATES:
            m = ((pc.year == y) & (pc.state_abbr == s)).to_numpy()
            tb = bt[:, m].sum(axis=1)
            out["by_state"].append({"state": s, "year": int(y), "pred_total_usd": float(pc.pred_usd[m].sum()),
                                    "lo": float(np.percentile(tb, 5)), "hi": float(np.percentile(tb, 95)),
                                    "actual_total_usd": float(pc.actual_usd[m].sum())})
    # interval coverage (county level) and calibration
    kk = (pc.insured_acres >= MIN_ACRES_PRINCIPAL)
    out["county_interval_coverage_90"] = float(((pc.actual_usd >= pc.lo) & (pc.actual_usd <= pc.hi))[kk].mean())
    out["interval_note"] = ("lo/hi are 5th/95th percentiles over 100 block-bootstrap refits (training years resampled "
                            "with replacement): parameter/sampling uncertainty of the fitted loss function, not a full "
                            "predictive interval; county-level 90% coverage is reported to show the gap.")
    # save county hindcast
    hc = pcs["model"][0][["fips", "state_abbr", "year", "insured_acres", "liability_usd", "actual_usd", "pred_usd",
                          "lo", "hi"]].copy()
    for k in ["baseline_mean", "baseline_hazard_only"]:
        hc[f"pred_usd_{k}"] = pcs[k][0].pred_usd.to_numpy()
    hc.to_parquet(OUT / "hindcast_county.parquet", index=False)
    # crop-level hindcast for the strategy engine / notes
    test.assign(pred=preds["model"])[["fips", "crop", "year", "liability_usd", "insured_acres", "indem_drought_usd",
                                      "pred"]].to_parquet(OUT / "hindcast_crop.parquet", index=False)
    out["selected_model"] = cfgs["main"]
    cv = json.load(open(OUT / "cv_results.json"))
    out["cv"] = {"selection_rule": cv["selection_rule"], "selected": cv["selected"],
                 "candidates": {k: {kk: v[kk] for kk in ["rmse", "mae", "r2", "spearman", "mean_within_year_spearman",
                                                         "year_total_median_ape", "total_bias_pct", "cfg"]}
                                for k, v in cv["results"].items()}}
    save_json(out, OUT / "validation.json", 1)
    web = {k: out[k] for k in ["train_years", "test_years", "metrics_units", "metrics", "by_year", "by_state"]}
    web["metrics_ci"] = {k: out["metrics_ci"][k] for k in models}
    web["by_year_models"] = out["by_year_models"]
    web["notes"] = ["Train 2001-2020, test 2021-2024; model chosen by leave-one-year-out CV inside 2001-2020 only.",
                    "Totals are principal crops (corn, soybeans, wheat, sorghum) drought indemnity, nominal USD, "
                    "7 states.", out["interval_note"]]
    web["mock"] = False
    save_json(web, WEB / "hindcast.json", 1)
    for k in models:
        print(k, {m: round(v, 3) for m, v in out["metrics"][k].items()})
    print(json.dumps(out["by_year"], indent=0))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["cv", "test"], required=True)
    ap.add_argument("--B", type=int, default=100)
    a = ap.parse_args()
    stage_cv() if a.stage == "cv" else stage_test(a.B)
