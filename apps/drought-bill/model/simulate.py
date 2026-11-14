"""Climatological simulation of the drought bill.

For every county and crop, the selected loss model (refit on 2001-2024; 2025 RMA is provisional and excluded) is
applied to each NASA POWER hazard year 1981-2024 while holding today's county characteristics fixed (county encoding
from 2001-2024, 2020-2024 irrigated insured share, soils, crop mix and liability per acre). That gives 44 simulated
loss-cost years per county-crop:
  expected bill = mean, 1-in-5 = 80th percentile, 1-in-10 = 90th percentile.
$/insured acre = simulated lcr x 2020-2024 mean liability per insured acre (nominal USD).
Intervals: 5th-95th percentile over B block-bootstrap refits (2001-2024 training years resampled with replacement).
2045: NEX-GDDP-CMIP6 deltas (2035-2054 vs 1995-2014) applied to the POWER daily/seasonal inputs (delta method), features
recomputed against the observed 1991-2020 climatology, model rerun; ensemble over GCMs.

Outputs: model/outputs/county_sim.parquet, model/outputs/sim_county_crop.parquet, model/outputs/sim_future.parquet,
         model/outputs/sim_summary.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import CROPS, LAST_COMPLETE_YEAR, MIN_ACRES_CROP, OUT, PROC, RECENT, SIM_YEARS, save_json  # noqa: E402
from hazard_features import (cell_season, county_cells, daily_jja_arrays, load_daily,  # noqa: E402
                             perturb_county_season, standardise)
from hazard_features import MS_FEATURES, WW_FEATURES  # noqa: E402
from lossmodel import add_encodings, county_encoding, fit, load_crop_panel, needs_enc, predict  # noqa: E402

MS_ALL = set(MS_FEATURES + WW_FEATURES + ["gwetroot_son_prior", "prcp_ondjfm_mm", "prcp_ww_mm", "gwetroot_ww",
                                           "edd30_ww"])
MIN_YEARS_CROP = 5  # years with >= 1,000 insured acres (2001-2024) for a crop to get its own simulated distribution


def recent_crop_table(data):
    """Per county x crop: 2020-2024 mean liability, acres, liability/acre, irrigated insured share, history."""
    r = data[data.year.isin(RECENT)]
    g = r.groupby(["fips", "crop"]).agg(liab_recent=("liability_usd", "mean"), acres_recent=("insured_acres", "mean"),
                                         prem_recent=("premium_usd", "mean"), subs_recent=("subsidy_usd", "mean"))
    # mean over the 5 years (missing years count as 0 insurance)
    cnt = r.groupby(["fips", "crop"]).size()
    for c in ["liab_recent", "acres_recent", "prem_recent", "subs_recent"]:
        g[c] = g[c] * cnt / len(RECENT)
    irr = r.assign(ia=r.irrigated_insured_share * r.insured_acres).groupby(["fips", "crop"]).agg(
        ia=("ia", "sum"), a=("insured_acres", "sum"))
    g["irrigated_insured_share"] = irr.ia / irr.a.replace(0, np.nan)
    hist = data[data.insured_acres >= MIN_ACRES_CROP].groupby(["fips", "crop"]).year.nunique().rename("n_years_hist")
    g = g.join(hist, how="left").fillna({"n_years_hist": 0})
    g["liab_per_ac_recent"] = g.liab_recent / g.acres_recent.replace(0, np.nan)
    return g.reset_index()


def sim_frame(data, feat, rc, cfg):
    """Rows (fips, crop, hazard_year) with today's county characteristics and each year's hazard features."""
    keep = rc[rc.liab_recent > 0][["fips", "crop", "irrigated_insured_share", "liab_recent", "acres_recent",
                                    "liab_per_ac_recent", "n_years_hist"]]
    st = data.drop_duplicates("fips").set_index("fips")[["state_abbr", "state_code", "aws0_150_mm", "aws0_100_mm",
                                                          "nccpi", "irrigated_share"]]
    keep = keep.join(st, on="fips", how="inner")
    from lossmodel import CROP_CODE
    keep["crop_code"] = keep.crop.map(CROP_CODE)
    f = feat[feat.year.isin(SIM_YEARS)].rename(columns={"year": "hazard_year"})
    sf = keep.merge(f, on="fips", how="inner")
    sf["year"] = LAST_COMPLETE_YEAR  # today's regime if the model uses a year term
    sf["lcr"] = np.nan
    sf["train_ok"] = False
    return sf


def fit_models(cfg, data, B, rng):
    years = np.arange(data.year.min(), LAST_COMPLETE_YEAR + 1)
    out = []
    for b in range(B + 1):
        if b == 0:
            tr = data
        else:
            yrs = rng.choice(years, size=len(years), replace=True)
            tr = pd.concat([data[data.year == y] for y in yrs], ignore_index=True)
        if needs_enc(cfg):
            st = tr[tr.train_ok]
            tr = tr.copy()
            tr["enc_lcr"] = county_encoding(st, tr, k=cfg.get("k", 5.0), loo_mask=tr.train_ok.to_numpy())
        m = fit(cfg, tr, seed=b)
        out.append((m, tr[tr.train_ok] if needs_enc(cfg) else None))
    return out


def predict_rows(cfg, m, stats_rows, rows):
    if needs_enc(cfg):
        rows = rows.copy()
        rows["enc_lcr"] = county_encoding(stats_rows, rows, k=cfg.get("k", 5.0))
    return predict(cfg, m, rows)


def summarise(sf, lcr, rc_pr):
    """From per-row lcr -> per-county principal and corn $/ac stats."""
    d = sf[["fips", "crop", "hazard_year", "liab_recent", "liab_per_ac_recent"]].copy()
    d["usd"] = lcr * d.liab_recent
    pr = d.groupby(["fips", "hazard_year"]).usd.sum().unstack("hazard_year")
    acres = rc_pr.reindex(pr.index)
    pr_ac = pr.div(acres, axis=0)
    corn = d[d.crop == "corn"].assign(v=lambda x: lcr[x.index] * x.liab_per_ac_recent).pivot(
        index="fips", columns="hazard_year", values="v")
    return pr_ac, corn


def stats_from(mat):
    a = mat.to_numpy()
    return pd.DataFrame({"mean": a.mean(1), "p80": np.percentile(a, 80, axis=1), "p90": np.percentile(a, 90, axis=1),
                         "y2012": mat[2012].to_numpy(), "y2022": mat[2022].to_numpy(), "y2023": mat[2023].to_numpy()},
                        index=mat.index)


def main(B=100, B_future=30):
    t0 = time.time()
    cfg = json.load(open(OUT / "model_config.json"))["main"]
    data = load_crop_panel(max_year=LAST_COMPLETE_YEAR)
    feat = pd.read_parquet(OUT / "hazard_features.parquet")
    rc = recent_crop_table(data)
    acres_pr = rc.groupby("fips").acres_recent.sum()
    sf = sim_frame(data, feat, rc, cfg).reset_index(drop=True)
    rng = np.random.default_rng(42)
    models = fit_models(cfg, data, B, rng)
    print(f"fitted {len(models)} models in {time.time() - t0:.0f}s", flush=True)
    L = np.stack([predict_rows(cfg, m, st, sf) for m, st in models])  # (B+1, rows)
    # per-crop simulated distributions
    sc = sf[["fips", "crop", "hazard_year", "state_abbr", "liab_per_ac_recent", "liab_recent", "acres_recent",
             "n_years_hist"]].copy()
    sc["lcr_sim"] = L[0]
    sc["lcr_sim_lo"] = np.percentile(L[1:], 5, axis=0)
    sc["lcr_sim_hi"] = np.percentile(L[1:], 95, axis=0)
    sc["usd_per_ac_sim"] = sc.lcr_sim * sc.liab_per_ac_recent
    sc["enough_history"] = sc.n_years_hist >= MIN_YEARS_CROP
    sc.to_parquet(OUT / "sim_county_crop.parquet", index=False)
    # county stats with bootstrap intervals
    res = {}
    allstats = []
    for b in range(B + 1):
        pr_ac, corn = summarise(sf, L[b], acres_pr)
        allstats.append((stats_from(pr_ac), stats_from(corn)))
        if b == 0:
            pr0, corn0 = pr_ac, corn
    cs = []
    for which, idx in [("principal", 0), ("corn", 1)]:
        point = allstats[0][idx]
        arr = np.stack([s[idx].reindex(point.index).to_numpy() for s in allstats[1:]])
        lo = pd.DataFrame(np.nanpercentile(arr, 5, axis=0), index=point.index, columns=point.columns)
        hi = pd.DataFrame(np.nanpercentile(arr, 95, axis=0), index=point.index, columns=point.columns)
        t = point.add_prefix(f"{which}_").join(lo.add_prefix(f"{which}_").add_suffix("_lo")).join(
            hi.add_prefix(f"{which}_").add_suffix("_hi"))
        cs.append(t)
    # region / state totals per bootstrap draw (for correctly correlated intervals on totals)
    st_of = data.drop_duplicates("fips").set_index("fips").state_abbr
    tot = []
    for b in range(B + 1):
        m = allstats[b][0]["mean"]
        v = (m * acres_pr.reindex(m.index)).groupby(st_of.reindex(m.index)).sum()
        tot.append(pd.DataFrame({"boot": b, "state": v.index, "expected_usd": v.to_numpy()}))
    pd.concat(tot).to_parquet(OUT / "sim_totals_boot.parquet", index=False)
    county = cs[0].join(cs[1], how="left")
    county.index.name = "fips"
    county = county.reset_index()
    # save the per-year simulated principal distribution (wide) for later use
    pr0.columns = [f"y{c}" for c in pr0.columns]
    pr0.reset_index().to_parquet(OUT / "sim_principal_by_year.parquet", index=False)
    print(f"historical sim done {time.time() - t0:.0f}s", flush=True)

    # county attributes
    pr_rc = rc.groupby("fips")[["liab_recent", "acres_recent", "prem_recent", "subs_recent"]].sum()
    pr_rc["liab_per_ac"] = pr_rc.liab_recent / pr_rc.acres_recent
    pr_rc["subsidy_share"] = pr_rc.subs_recent / pr_rc.prem_recent
    county = county.merge(pr_rc.reset_index(), on="fips", how="left")
    county.to_parquet(OUT / "county_sim_hist.parquet", index=False)
    hist_means = [(s_[0]["mean"], s_[1]["mean"]) for s_ in allstats]
    with gzip.open(OUT / "sim_state.pkl.gz", "wb", compresslevel=6) as fh:  # ~40 MB; regenerable, do not commit
        pickle.dump({"cfg": cfg, "models": models, "sf": sf, "acres_pr": acres_pr, "hist_means": hist_means}, fh)
    print(f"historical done {time.time() - t0:.0f}s; counties={len(county)}", flush=True)
    future(B_future)


def future(B_future=30):
    """2045 simulation with the saved bootstrap models (re-runnable when more CMIP6 GCMs land)."""
    t0 = time.time()
    with gzip.open(OUT / "sim_state.pkl.gz", "rb") as fh:
        st_ = pickle.load(fh)
    cfg, models, sf, acres_pr, hist_means = st_["cfg"], st_["models"], st_["sf"], st_["acres_pr"], st_["hist_means"]
    feat = pd.read_parquet(OUT / "hazard_features.parquet")
    county = pd.read_parquet(OUT / "county_sim_hist.parquet")
    fut_rows = []
    dp = PROC / "cmip6_deltas.parquet"
    if dp.exists():
        deltas = pd.read_parquet(dp)
        bsd = pickle.load(open(OUT / "power_base_stats.pkl", "rb"))
        bs, emu = bsd["base_stats"], bsd["emulator"]
        daily = load_daily()
        cy = cell_season(daily)
        cs_obs = county_cells().merge(cy, on="cell_id")
        cs_obs = cs_obs[cs_obs.year.isin(SIM_YEARS)].reset_index(drop=True)
        cs_obs["clim_prcp_mj_mm"] = bs.loc[cs_obs.cell_id, "prcp_mj_mm_mu"].to_numpy()
        cs_obs["clim_prcp_jja_mm"] = bs.loc[cs_obs.cell_id, "prcp_jja_mm_mu"].to_numpy()
        dj = daily_jja_arrays(daily)
        sub = models[:1] + models[1:B_future + 1]
        # only the features the delta method recomputes are replaced; out-of-season (v2) features have no CMIP6
        # delta in this build and are held at their observed values
        hcols = [c for c in feat.columns if c not in ("fips", "year", "cell_id") and c not in MS_ALL]
        base = sf.drop(columns=[c for c in hcols if c in sf.columns])
        feat_shift = []
        # Two soil-moisture assumptions are treated as structural uncertainty (see notes 4.1, decomposition):
        # "emulator" shifts root-zone wetness with the POWER-fitted emulator (its temperature slope is likely inflated
        # by land-atmosphere feedback: dry soils make hot summers), "no_emulator" holds root-zone wetness at observed.
        emu0 = {k: {**v, "beta": [0.0] * len(v["beta"])} for k, v in emu.items()}
        for (gcm, scen), dg in deltas.groupby(["gcm", "scenario"]):
            dd = dg.set_index("fips")
            for soil, e in (("emulator", emu), ("no_emulator", emu0)):
                fs = perturb_county_season(cs_obs, dd, e, daily_jja=dj)
                fz = standardise(fs, bs)
                fz = fz[fz.fips.isin(dd.index)]
                ff = fz.rename(columns={"year": "hazard_year"})
                sff = base.merge(ff[["fips", "hazard_year"] + [c for c in hcols if c in ff.columns]],
                                 on=["fips", "hazard_year"], how="inner")
                fsum = ff.groupby("fips")[["hazard_z", "edd30_jja", "spi_jja", "gwetroot_jja", "vpd_jja_kpa"]].mean()
                feat_shift.append(fsum.assign(gcm=gcm, scenario=scen, soil=soil).reset_index())
                for bi, (m, stt) in enumerate(sub):
                    lf = predict_rows(cfg, m, stt, sff)
                    pr_ac, corn = summarise(sff, lf, acres_pr)
                    fut_rows.append(pd.DataFrame({"fips": pr_ac.index, "gcm": gcm, "scenario": scen, "soil": soil,
                                                  "boot": bi, "principal_mean": pr_ac.mean(axis=1).to_numpy(),
                                                  "principal_p90": np.percentile(pr_ac.to_numpy(), 90, axis=1),
                                                  "corn_mean": corn.mean(axis=1).reindex(pr_ac.index).to_numpy()}))
                print(f"  {gcm} {scen} {soil} done {time.time() - t0:.0f}s", flush=True)
        pd.concat(feat_shift).to_parquet(OUT / "sim_future_features.parquet", index=False)
        fut = pd.concat(fut_rows, ignore_index=True)
        hist = []
        for bi in range(len(sub)):
            hp, hc = hist_means[bi]
            hist.append(pd.DataFrame({"fips": hp.index, "boot": bi, "hist_principal_mean": hp.to_numpy(),
                                      "hist_corn_mean": hc.reindex(hp.index).to_numpy()}))
        fut = fut.merge(pd.concat(hist), on=["fips", "boot"], how="left")
        fut.to_parquet(OUT / "sim_future.parquet", index=False)
        for scen, g in fut.groupby("scenario"):
            p0 = g[g.boot == 0].groupby("fips").principal_mean.median()
            allv = g.groupby("fips").principal_mean
            county = county.merge(pd.DataFrame({
                f"principal_2045_{scen}": p0, f"principal_2045_{scen}_lo": allv.quantile(0.05),
                f"principal_2045_{scen}_hi": allv.quantile(0.95)}).reset_index(), on="fips", how="left")
            c0 = g[g.boot == 0].groupby("fips").corn_mean.median()
            callv = g.groupby("fips").corn_mean
            county = county.merge(pd.DataFrame({
                f"corn_2045_{scen}": c0, f"corn_2045_{scen}_lo": callv.quantile(0.05),
                f"corn_2045_{scen}_hi": callv.quantile(0.95)}).reset_index(), on="fips", how="left")
        county["n_gcms"] = deltas.gcm.nunique()
        county["gcms_2045"] = ",".join(sorted(deltas.gcm.unique()))
    else:
        print("[warn] cmip6_deltas.parquet missing: 2045 fields will be null")
    county.to_parquet(OUT / "county_sim.parquet", index=False)
    print(f"future done {time.time() - t0:.0f}s")


def decompose():
    """Decompose the 2045 change (point model, region total) into heat, precipitation and soil-moisture-emulator
    parts by re-running the delta method with parts of the CMIP6 deltas switched off."""
    with gzip.open(OUT / "sim_state.pkl.gz", "rb") as fh:
        st_ = pickle.load(fh)
    cfg, models, sf, acres_pr, hist_means = st_["cfg"], st_["models"], st_["sf"], st_["acres_pr"], st_["hist_means"]
    m0, stt = models[0]
    feat = pd.read_parquet(OUT / "hazard_features.parquet")
    deltas = pd.read_parquet(PROC / "cmip6_deltas.parquet")
    bsd = pickle.load(open(OUT / "power_base_stats.pkl", "rb"))
    bs, emu = bsd["base_stats"], bsd["emulator"]
    emu0 = {k: {**v, "beta": [0.0] * len(v["beta"])} for k, v in emu.items()}
    daily = load_daily()
    cy = cell_season(daily)
    cs_obs = county_cells().merge(cy, on="cell_id")
    cs_obs = cs_obs[cs_obs.year.isin(SIM_YEARS)].reset_index(drop=True)
    cs_obs["clim_prcp_mj_mm"] = bs.loc[cs_obs.cell_id, "prcp_mj_mm_mu"].to_numpy()
    cs_obs["clim_prcp_jja_mm"] = bs.loc[cs_obs.cell_id, "prcp_jja_mm_mu"].to_numpy()
    dj = daily_jja_arrays(daily)
    hcols = [c for c in feat.columns if c not in ("fips", "year", "cell_id") and c not in MS_ALL]
    base = sf.drop(columns=[c for c in hcols if c in sf.columns])
    hist_total = float((hist_means[0][0] * acres_pr.reindex(hist_means[0][0].index)).sum())
    pcols = [c for c in deltas.columns if c.startswith("d_prcp")]
    tcols = [c for c in deltas.columns if c.startswith(("d_tmax", "d_tmin", "d_edd", "d_vpd"))]
    variants = {
        "full": (lambda d: d, emu),
        "heat_only (temperature/VPD; soil wetness responds to temperature)": (lambda d: d.assign(**{c: 0.0 for c in pcols}), emu),
        "heat_only_no_emulator (temperature/VPD; soil wetness unchanged)": (lambda d: d.assign(**{c: 0.0 for c in pcols}), emu0),
        "precip_only (soil wetness responds to precipitation)": (lambda d: d.assign(**{c: 0.0 for c in tcols}), emu),
        "full_no_emulator (soil wetness held at observed)": (lambda d: d, emu0),
    }
    rows = []
    for (gcm, scen), dg in deltas.groupby(["gcm", "scenario"]):
        for vn, (fn, e) in variants.items():
            dd = fn(dg.set_index("fips").copy())
            fz = standardise(perturb_county_season(cs_obs, dd, e, daily_jja=dj), bs)
            ff = fz[fz.fips.isin(dd.index)].rename(columns={"year": "hazard_year"})
            sff = base.merge(ff[["fips", "hazard_year"] + [c for c in hcols if c in ff.columns]],
                             on=["fips", "hazard_year"], how="inner")
            lf = predict_rows(cfg, m0, stt, sff)
            pr_ac, _ = summarise(sff, lf, acres_pr)
            tot = float((pr_ac.mean(axis=1) * acres_pr.reindex(pr_ac.index)).sum())
            rows.append({"gcm": gcm, "scenario": scen, "variant": vn, "total_usd": tot,
                         "change_pct": 100 * (tot / hist_total - 1),
                         "mean_d_hazard_z": float(ff.groupby("fips").hazard_z.mean().mean()
                                                  - feat[feat.year.isin(SIM_YEARS)].groupby("fips").hazard_z.mean().mean())})
            print(gcm, scen, vn[:30], round(rows[-1]["change_pct"], 1), flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "future_decomposition.parquet", index=False)
    summ = {"hist_total_usd": hist_total, "gcms": sorted(deltas.gcm.unique().tolist()),
            "by_gcm": {f"{r.gcm}|{r.scenario}|{r.variant}": round(r.change_pct, 1) for r in df.itertuples()},
            "median_over_gcms": {s: g.groupby("variant").change_pct.median().round(1).to_dict()
                                 for s, g in df.groupby("scenario")}}
    save_json(summ, OUT / "future_decomposition.json", 1)
    print(json.dumps(summ["median_over_gcms"], indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--B", type=int, default=100)
    ap.add_argument("--B_future", type=int, default=30)
    ap.add_argument("--future-only", action="store_true")
    ap.add_argument("--decompose", action="store_true")
    a = ap.parse_args()
    if a.decompose:
        decompose()
    elif a.future_only:
        future(a.B_future)
    else:
        main(a.B, a.B_future)
