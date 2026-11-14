"""m03: learned sensitivity of river nitrate to bare soil in Oct 15 - May 31 -> model/out/sensitivity.json

Run: python3 model/m03_sensitivity.py   (after m02; ~2-4 min)

Counterfactual perturbation: daily causal bare share is cut by 10/25/50% of its value on Oct 15 - May 31
(living share rises by the same amount), all cover-derived features (30/90/180-d means, bare x wet sums)
are recomputed (river.perturb_cover), and the models re-predict. Reported per site:
  * gbm: % change of the p50 simulation (window days, Apr-Jul, whole year), elasticity d ln C / d bare,
         days > 10 mg/L avoided per year when the model's ratio is applied to the OBSERVED series
         ("obs-anchored"), with uncertainty from >= 20 refits on bootstrap-resampled training YEARS
         plus the shift of the p10/p90 quantile models;
  * reservoir: the same perturbation through the conceptual model (uptake by living cover);
  * identification diagnostics: how much of bare-share variation is seasonal, how far the perturbation
         leaves the training range, and how much leave-one-year-out CV skill bare-share features add.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import featlib as F  # noqa: E402
import qgbm as Q  # noqa: E402
import river  # noqa: E402

FRACS = [0.10, 0.25, 0.50]
N_BOOT = 30
YEARS = list(range(2016, 2026))
MCL = 10.0


def window(d):
    md = d.dt.month * 100 + d.dt.day
    return ((md >= 1015) | (md <= 531)).values


def effects(g, base, cf):
    """g: site frame; base, cf: p50 arrays (mg/L). Returns summary + per-year dict."""
    d = g.date
    yr = d.dt.year.values
    win = window(d)
    aj = d.dt.month.isin([4, 5, 6, 7]).values
    ok = np.isfinite(base) & np.isfinite(cf)
    sel = ok & (yr >= 2016) & (yr <= 2025)
    ratio = cf / base
    obs = g.no3.values
    out = dict(
        pct_change_window=float(100 * (cf[sel & win].mean() / base[sel & win].mean() - 1)),
        pct_change_aprjul=float(100 * (cf[sel & aj].mean() / base[sel & aj].mean() - 1)),
        pct_change_year=float(100 * (cf[sel].mean() / base[sel].mean() - 1)),
    )
    by = {}
    dd = []
    for y in YEARS + [2026]:
        m = ok & (yr == y)
        mo = m & np.isfinite(obs)
        ob = int((obs[mo] > MCL).sum())
        cfo = int((obs[mo] * ratio[mo] > MCL).sum())
        by[str(y)] = dict(obs_days_over10=ob, cf_obs_anchored_days_over10=cfo, days_avoided=ob - cfo,
                          pct_change_mean=float(100 * (cf[m].mean() / base[m].mean() - 1)) if m.any() else None)
        if y <= 2025:
            dd.append(ob - cfo)
    out["days_avoided_per_year_mean_2016_2025"] = float(np.mean(dd))
    out["days_avoided_2025"] = by["2025"]["days_avoided"]
    out["by_year"] = by
    return out


def elasticity(g, base, cf, bare0, bare1):
    win = window(g.date) & np.isfinite(base) & np.isfinite(cf)
    db = (bare1 - bare0)[win].mean()
    dl = (np.log(cf) - np.log(base))[win].mean()
    return float(dl / db) if db != 0 else None


def summarize(vals):
    v = np.array([x for x in vals if x is not None and np.isfinite(x)])
    return dict(p50=float(np.median(v)), lo=float(np.quantile(v, 0.05)), hi=float(np.quantile(v, 0.95)), n=int(len(v)))


VERSION = "v2" if "--v2" in sys.argv else "v1"


def mono(fs):
    return F.monotone_vector_v2(fs) if VERSION == "v2" else mono(fs)


def main():
    feats = river.load_features(VERSION)
    M = river.load_models(model_version=VERSION)
    res = dict(
        generated_at=pd.Timestamp.now(tz="UTC").isoformat(),
        perturbation=dict(variable="daily causal MODIS bare share of persistent row-crop land (living = 1 - bare)",
                          window="Oct 15 - May 31 every year", fracs=FRACS,
                          recomputed=F.COVER_DERIVED, api="model/river.py: perturb_cover(features_df, frac, months)"),
        uncertainty=(f"{N_BOOT} refits of the median GBM on bootstrap-resampled training years (2016-2022, whole "
                     "years drawn with replacement) -> 5-95% range; plus the effect seen by the p10 and p90 quantile "
                     "models; plus the conceptual reservoir model as a structurally different estimate."),
        identification_caveat=(
            "Historical bare-share variation is overwhelmingly seasonal (bare in winter/spring, green in summer) and "
            "its year-to-year differences are driven by weather (planting/green-up timing, harvest date), not by "
            "cover-crop adoption, which stayed at single-digit % of cropland. The model therefore never saw a "
            "watershed with much more winter living cover, so the learned sensitivity is weakly identified: the "
            "monotone constraint fixes its sign (less bare soil never raises nitrate), but its size is uncertain and "
            "a 50% cut takes winter bare share far outside the training range, where trees extrapolate flat (the "
            "effect saturates). This is why the scenario engine blends it with field-trial priors."),
        sites={})
    for site, g in feats.groupby("site"):
        if site not in M:
            continue
        g = g.sort_values("date").reset_index(drop=True)
        g = g[g.date >= ("2015-10-01" if VERSION == "v1" else "2009-01-01")].reset_index(drop=True)
        cfg = M[site]["cfg"]
        hp = cfg["hp"]
        fl = cfg["features"]
        print(f"=== {site} ===")
        base = river.predict(g, site, M)
        M1 = M if VERSION == "v1" else river.load_models(model_version="v1")
        g_res = g[g.date >= "2015-10-01"]
        base_res = np.full(len(g), np.nan)
        base_res[g_res.index] = river.predict_reservoir(g_res, site, M1).values
        out = dict(gbm={}, gbm_p10={}, gbm_p90={}, reservoir={}, diagnostics={})
        pert = {f: river.perturb_cover(g, f) for f in FRACS}
        for f in FRACS:
            cf = river.predict(pert[f], site, M)
            e = effects(g, base.p50.values, cf.p50.values)
            e["elasticity_dlnC_dbare"] = elasticity(g, base.p50.values, cf.p50.values, g.bare.values, pert[f].bare.values)
            out["gbm"][str(f)] = dict(central=e)
            for qn in ("p10", "p90"):
                eq = effects(g, base[qn].values, cf[qn].values)
                out[f"gbm_{qn}"][str(f)] = {k: eq[k] for k in ("pct_change_window", "pct_change_aprjul",
                                                               "pct_change_year")}
            cr = np.full(len(g), np.nan)
            cr[g_res.index] = river.predict_reservoir(pert[f].loc[g_res.index], site, M1).values
            er = effects(g, base_res, cr)
            er["elasticity_dlnC_dbare"] = elasticity(g, base_res, cr, g.bare.values, pert[f].bare.values)
            out["reservoir"][str(f)] = er
            print(f"  frac {f:.2f}: gbm window {e['pct_change_window']:+.1f}%  AprJul {e['pct_change_aprjul']:+.1f}%  "
                  f"days avoided/yr {e['days_avoided_per_year_mean_2016_2025']:.1f} (2025: {e['days_avoided_2025']}) | "
                  f"reservoir window {er['pct_change_window']:+.1f}% days/yr {er['days_avoided_per_year_mean_2016_2025']:.1f}")
        # ---- bootstrap over training years (median model)
        y = g.lno3.values
        yrs = g.year.values
        valid = g.rain_7.notna().values & g.logq.notna().values & np.isfinite(y)
        tr_years = np.arange(2016, 2023) if VERSION == "v1" else np.array(cfg["train_years"])
        rng = np.random.default_rng(42)
        boot = {str(f): dict(win=[], aj=[], yr=[], days=[], d25=[], el=[]) for f in FRACS}
        Xb = g[fl]
        okp = g.rain_7.notna().values & g.logq.notna().values
        for b in range(N_BOOT):
            pick = rng.choice(tr_years, size=len(tr_years), replace=True)
            idx = np.concatenate([np.where(valid & (yrs == yy))[0] for yy in pick])
            mdl = Q.fit(g.iloc[idx], y[idx], fl, 0.5, mono(fl), hp["num_leaves"],
                        hp["min_child_samples"], hp["n_estimators"], seed=100 + b)
            p0 = np.where(okp, np.exp(mdl.predict(Xb)), np.nan)
            for f in FRACS:
                p1 = np.where(okp, np.exp(mdl.predict(pert[f][fl])), np.nan)
                e = effects(g, p0, p1)
                bb = boot[str(f)]
                bb["win"].append(e["pct_change_window"]); bb["aj"].append(e["pct_change_aprjul"])
                bb["yr"].append(e["pct_change_year"]); bb["days"].append(e["days_avoided_per_year_mean_2016_2025"])
                bb["d25"].append(e["days_avoided_2025"])
                bb["el"].append(elasticity(g, p0, p1, g.bare.values, pert[f].bare.values))
        for f in FRACS:
            bb = boot[str(f)]
            out["gbm"][str(f)]["bootstrap"] = dict(
                pct_change_window=summarize(bb["win"]), pct_change_aprjul=summarize(bb["aj"]),
                pct_change_year=summarize(bb["yr"]), days_avoided_per_year_mean_2016_2025=summarize(bb["days"]),
                days_avoided_2025=summarize(bb["d25"]), elasticity_dlnC_dbare=summarize(bb["el"]))
            s = out["gbm"][str(f)]["bootstrap"]
            print(f"  boot frac {f:.2f}: window {s['pct_change_window']['p50']:+.1f}% "
                  f"[{s['pct_change_window']['lo']:+.1f}, {s['pct_change_window']['hi']:+.1f}]  "
                  f"days/yr {s['days_avoided_per_year_mean_2016_2025']['p50']:.1f} "
                  f"[{s['days_avoided_per_year_mean_2016_2025']['lo']:.1f}, "
                  f"{s['days_avoided_per_year_mean_2016_2025']['hi']:.1f}]")
        # ---- identification diagnostics
        d = g.date
        clim = F.doy_climatology(d, g.bare, years=(2016, 2022))
        cl = clim.reindex(d.dt.dayofyear).values
        tr = np.isin(g.year.values, tr_years)
        r2 = 1 - np.nanvar(g.bare.values[tr] - cl[tr]) / np.nanvar(g.bare.values[tr])
        win = window(d)
        wy = np.where(d.dt.month >= 10, d.dt.year + 1, d.dt.year)  # Oct-May season labelled by its spring year
        seas = pd.Series(g.bare.values[win]).groupby(wy[win]).mean()
        seas = seas[(seas.index >= 2016) & (seas.index <= 2026)]
        oor = {}
        doy = d.dt.dayofyear.values
        btr = g.bare.values[tr]
        dtr = doy[tr]
        for f in FRACS:
            pb = pert[f].bare.values
            below = []
            for i in np.where(win & (g.year.values >= 2016) & (g.year.values <= 2025))[0]:
                dist = np.minimum(np.abs(dtr - doy[i]), 365 - np.abs(dtr - doy[i]))
                below.append(pb[i] < np.nanmin(btr[dist <= 7]))
            oor[str(f)] = float(np.mean(below))
        # CV value of bare features: LOYO with vs without them (median model, chosen hyperparameters)
        nob = [c for c in fl if c not in F.BARE_FEATS + F.BAREWET_FEATS]
        cvr = {}
        for name, fs in (("with_bare", fl), ("without_bare", nob)):
            errs = []
            for yy in tr_years:
                trm = valid & tr & (yrs != yy); tem = valid & (yrs == yy)
                mdl = Q.fit(g[trm], y[trm], fs, 0.5, mono(fs), hp["num_leaves"],
                            hp["min_child_samples"], hp["n_estimators"])
                errs.append(float(np.sqrt(np.mean((mdl.predict(g[tem]) - y[tem]) ** 2))))
            cvr[name] = dict(mean_rmse_log=float(np.mean(errs)), by_year=dict(zip(map(str, tr_years), errs)))
        out["diagnostics"] = dict(
            bare_variance_explained_by_doy_climatology_train=float(r2),
            octmay_mean_bare_by_season=dict(zip(map(str, seas.index), map(float, seas.values.round(4)))),
            octmay_mean_bare_interannual_sd=float(seas.std()),
            perturbation_size_vs_interannual_sd={str(f): float(f * seas.mean() / seas.std()) for f in FRACS},
            share_of_window_days_below_training_range=oor,
            loyo_cv_median_model=cvr,
            cv_rmse_log_gain_from_bare_features=float(cvr["without_bare"]["mean_rmse_log"] -
                                                      cvr["with_bare"]["mean_rmse_log"]))
        print(f"  diagnostics: seasonal R2 {r2:.2f}, interannual SD {seas.std():.3f}, "
              f"out-of-range days {oor}, CV rmse with {cvr['with_bare']['mean_rmse_log']:.3f} "
              f"without {cvr['without_bare']['mean_rmse_log']:.3f}")
        res["sites"][site] = out
    path = F.OUT / "sensitivity.json"
    old = json.load(open(path)) if path.exists() else {}
    if VERSION == "v1":
        if "v2" in old:
            res["v2"] = old["v2"]  # keep the v2 block written by a --v2 run
        json.dump(res, open(path, "w"), indent=1, default=float)
    else:
        res["model_version"] = "v2"
        res["note"] = ("v2 (legacy-N) GBM; reservoir block repeats the v1 conceptual model for reference. The carryover "
                       "store does not depend on cover, so cover acts only through the bare-share features.")
        old["v2"] = res
        json.dump(old, open(path, "w"), indent=1, default=float)
    print("wrote sensitivity.json")


if __name__ == "__main__":
    main()
