"""Write the web data files from the model outputs:
web/data/county_bill.json, web/data/regional_summary.json, web/data/meta.json (hindcast.json is written by
fit_loss.py --stage test). Run after build_panel, fit_loss (cv, test), diversity_effect and simulate.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import OUT, PROC, STATES, WEB, r2d, r3, save_json  # noqa: E402

DOLLAR_YEAR = "2020-2024 nominal"
NOW_WINDOW_END = 2023  # CDL guidance: 2024 relabels other hay as grass, so use the 2019-2023 window as "now"
SLIDER_GRID = [round(x, 2) for x in np.linspace(0, 1, 11)]


def eh(est, lo, hi, f=r3):
    if est is None or not np.isfinite(est):
        return None
    return {"est": f(est), "lo": f(lo) if lo is not None and np.isfinite(lo) else None,
            "hi": f(hi) if hi is not None and np.isfinite(hi) else None}


def multiplier(s, s_now, eff, which="est"):
    """Drought-loss multiplier when the share of cropland in 3+ crop rotations moves from s_now to s."""
    if eff["source"] == "trial_prior_scenario":
        r = eff["r"][which]
        return (1 - r * s) / (1 - r * s_now)
    th = eff["theta"][which]
    return float(np.exp(th * (s - s_now)))


def main():
    cs = pd.read_parquet(OUT / "county_sim.parquet").set_index("fips")
    counties = pd.read_parquet(PROC / "counties.parquet").set_index("fips")
    static = pd.read_parquet(PROC / "county_static.parquet").set_index("fips")
    panel = pd.read_parquet(OUT / "panel.parquet")
    pr = panel[panel.crop == "principal"]
    hc = pd.read_parquet(OUT / "hindcast_county.parquet")
    div = json.load(open(OUT / "diversity_effect.json"))
    eff = div["app_effect"]
    val = json.load(open(OUT / "validation.json"))
    cdl = pd.read_parquet(PROC / "cdl_county_year.parquet")
    now = cdl[cdl.year == NOW_WINDOW_END].set_index("fips")
    # acre-weighted regional p90 of share_3plus (insured principal acres 2020-2024)
    s3 = now.share_3plus.reindex(cs.index)
    w = cs.acres_recent
    ok = s3.notna() & w.notna()
    order = np.argsort(s3[ok].to_numpy())
    cw = np.cumsum(w[ok].to_numpy()[order]) / w[ok].sum()
    p90 = float(s3[ok].to_numpy()[order][np.searchsorted(cw, 0.9)])

    actual = pr.pivot_table(index="fips", columns="year", values="drought_usd_per_ac")
    out = {"units": "USD per insured acre per year", "dollar_year": DOLLAR_YEAR, "mock": False,
           "crops": "principal crops = corn + soybeans + wheat + sorghum (RMA); corn also given separately",
           "diversity_metric": {"name": "share_3plus", "label": "share of cropland in 3+ crop rotations (CDL, 5-year "
                                                                 f"window {NOW_WINDOW_END - 4}-{NOW_WINDOW_END})",
                                "range": [0, 1], "p90_region": round(p90, 3)},
           "slider_effect": {"source": eff["source"], "label": eff["label"], "form": eff["form"]},
           "counties": {}}
    hc22 = hc[hc.year.isin([2022, 2023])].set_index(["fips", "year"])
    sav = {"est": {}, "lo": {}, "hi": {}}
    for f, c in cs.iterrows():
        if not np.isfinite(c.get("principal_mean", np.nan)) or not (c.acres_recent > 0):
            continue
        ss = c.subsidy_share
        rec = {"name": counties.name.get(f), "state": counties.state_abbr.get(f),
               "insured_acres": int(round(c.acres_recent)), "liab_per_ac": r2d(c.liab_per_ac),
               "subsidy_share": round(float(ss), 3) if np.isfinite(ss) else None,
               "expected_bill": eh(c.principal_mean, c.principal_mean_lo, c.principal_mean_hi),
               "bill_1in5": eh(c.principal_p80, c.principal_p80_lo, c.principal_p80_hi),
               "bill_1in10": eh(c.principal_p90, c.principal_p90_lo, c.principal_p90_hi),
               "taxpayer_expected_bill": eh(ss * c.principal_mean, ss * c.principal_mean_lo, ss * c.principal_mean_hi)
               if np.isfinite(ss) else None,
               "actual": {str(y): r2d(actual.loc[f, y]) if f in actual.index and y in actual.columns else None
                          for y in (2012, 2022, 2023)},
               "hindcast": {}, "bill_2045": None, "corn": None}
        for y in (2022, 2023):
            if (f, y) in hc22.index:
                h = hc22.loc[(f, y)]
                a = h.insured_acres
                rec["hindcast"][str(y)] = {"pred": r2d(h.pred_usd / a), "lo": r2d(h.lo / a), "hi": r2d(h.hi / a),
                                           "actual": r2d(h.actual_usd / a)} if a > 0 else None
        if "principal_2045_ssp245" in cs.columns and np.isfinite(c.get("principal_2045_ssp245", np.nan)):
            rec["bill_2045"] = {s: eh(c[f"principal_2045_{s}"], c[f"principal_2045_{s}_lo"], c[f"principal_2045_{s}_hi"])
                                for s in ("ssp245", "ssp585")}
        if np.isfinite(c.get("corn_mean", np.nan)):
            rec["corn"] = {"expected_bill": eh(c.corn_mean, c.corn_mean_lo, c.corn_mean_hi),
                           "bill_1in10": eh(c.corn_p90, c.corn_p90_lo, c.corn_p90_hi)}
            if "corn_2045_ssp245" in cs.columns and np.isfinite(c.get("corn_2045_ssp245", np.nan)):
                rec["corn"]["bill_2045"] = {s: eh(c[f"corn_2045_{s}"], c[f"corn_2045_{s}_lo"], c[f"corn_2045_{s}_hi"])
                                            for s in ("ssp245", "ssp585")}
        # diversity + slider
        if f in now.index and np.isfinite(now.share_3plus.get(f, np.nan)):
            s_now = float(now.share_3plus[f])
            rec["diversity"] = {"now": round(s_now, 3), "p90_region": round(p90, 3),
                                "n_crops_now": round(float(now.n_crops_5y[f]), 2),
                                "share_cont_corn": round(float(now.share_cont_corn[f]), 3),
                                "shannon_now": round(float(now.div_shannon_5y[f]), 3)}
            b22, b22lo, b22hi = c.principal_y2022, c.principal_y2022_lo, c.principal_y2022_hi
            ms = {k: [multiplier(s, s_now, eff, k) for s in SLIDER_GRID] for k in ("est", "lo", "hi")}
            rec["slider"] = {
                "div_values": SLIDER_GRID, "metric": "share_3plus", "hazard_year": 2022,
                "bill_2022_style": [r3(b22 * m) for m in ms["est"]],
                "lo": [r3(b22lo * min(a, b)) for a, b in zip(ms["lo"], ms["hi"])],
                "hi": [r3(b22hi * max(a, b)) for a, b in zip(ms["lo"], ms["hi"])],
                "bill_2012_style": [r3(c.principal_y2012 * m) for m in ms["est"]]}
            tgt = max(s_now, p90)
            for k in ("est", "lo", "hi"):
                sav[k][f] = c.principal_mean * c.acres_recent * (1 - multiplier(tgt, s_now, eff, k))
        else:
            rec["diversity"] = None
            rec["slider"] = None
        rec["irrigated_share"] = round(float(static.irrigated_share.get(f)), 3) if np.isfinite(
            static.irrigated_share.get(f, np.nan)) else None
        rec["aws_mm"] = round(float(static.aws0_150_mm.get(f)), 0)
        out["counties"][f] = rec
    out["notes"] = ["Expected bill = mean of 44 simulated years (NASA POWER hazard 1981-2024 applied to today's county "
                    "characteristics); 1-in-5 / 1-in-10 = 80th / 90th percentile. lo/hi = 5th-95th percentile over "
                    "100 block-bootstrap refits (parameter uncertainty).",
                    "aws_mm = available water storage 0-150 cm (SSURGO).",
                    "actual = RMA drought indemnity per insured acre that year (nominal); hindcast = out-of-time "
                    "prediction from the model trained on 2001-2020.",
                    "taxpayer_expected_bill = subsidy_share x expected_bill (actuarial approximation: premiums are set "
                    "to cover expected losses, and the federal subsidy pays subsidy_share of premiums).",
                    "slider: " + eff["label"]]
    save_json(out, WEB / "county_bill.json")
    print("county_bill.json:", len(out["counties"]), "counties,",
          round((WEB / "county_bill.json").stat().st_size / 1e6, 2), "MB")

    # ------------------------------------------------------------ regional summary
    tb = pd.read_parquet(OUT / "sim_totals_boot.parquet")
    st_of = counties.state_abbr
    cs["state"] = st_of.reindex(cs.index)
    cs["exp_usd"] = cs.principal_mean * cs.acres_recent
    cs["tax_usd"] = cs.principal_mean * cs.acres_recent * cs.subsidy_share
    act = pr.groupby(["state_abbr", "year"]).indem_drought_usd.sum()
    fut = pd.read_parquet(OUT / "sim_future.parquet") if (OUT / "sim_future.parquet").exists() else None
    if fut is not None:
        fut = fut.merge(cs[["acres_recent", "state"]].reset_index(), on="fips", how="left")
        fut["fut_usd"] = fut.principal_mean * fut.acres_recent
        fut["hist_usd"] = fut.hist_principal_mean * fut.acres_recent
    savs = {k: pd.Series(v) for k, v in sav.items()}

    def block(states):
        m = cs.state.isin(states)
        e = cs.exp_usd[m].sum()
        t = cs.tax_usd[m].sum()
        bt = tb[tb.state.isin(states) & (tb.boot > 0)].groupby("boot").expected_usd.sum()
        lo, hi = np.percentile(bt, 5), np.percentile(bt, 95)
        r = t / e
        blk = {"insured_acres": int(cs.acres_recent[m].sum()),
               "expected_bill_usd": {"est": r3(e), "lo": r3(lo), "hi": r3(hi)},
               "taxpayer_share_usd": {"est": r3(t), "lo": r3(lo * r), "hi": r3(hi * r)},
               "taxpayer_fraction": round(float(r), 3),
               "actual_2022_usd": r3(sum(act.get((s, 2022), 0) for s in states)),
               "actual_2023_usd": r3(sum(act.get((s, 2023), 0) for s in states)),
               "actual_2012_usd": r3(sum(act.get((s, 2012), 0) for s in states)),
               "actual_mean_2001_2024_usd_nominal": r3(np.mean([sum(act.get((s, y), 0) for s in states)
                                                                for y in range(2001, 2025)])),
               "expected_bill_per_insured_acre": r2d(e / cs.acres_recent[m].sum())}
        fs = savs["est"].index.map(st_of).isin(states)
        blk["diversity_savings_usd"] = {"est": r3(savs["est"][fs].sum()), "lo": r3(savs["lo"][fs].sum()),
                                        "hi": r3(savs["hi"][fs].sum())}
        if fut is not None:
            fm = fut[fut.state.isin(states)]
            g = fm.groupby(["scenario", "gcm", "boot"])[["fut_usd", "hist_usd"]].sum().reset_index()
            g["chg"] = 100 * (g.fut_usd / g.hist_usd - 1)
            blk["bill_2045_usd"], blk["change_2045_pct"], blk["change_2045_pct_by_gcm"] = {}, {}, {}
            for s, gs in g.groupby("scenario"):
                b0 = gs[gs.boot == 0]
                blk["bill_2045_usd"][s] = {"est": r3(b0.fut_usd.median()), "lo": r3(gs.fut_usd.quantile(0.05)),
                                           "hi": r3(gs.fut_usd.quantile(0.95))}
                blk["change_2045_pct"][s] = {"est": round(float(b0.chg.median()), 1),
                                             "lo": round(float(gs.chg.quantile(0.05)), 1),
                                             "hi": round(float(gs.chg.quantile(0.95)), 1)}
                blk["change_2045_pct_by_gcm"][s] = {k: round(float(v), 1) for k, v in zip(b0.gcm, b0.chg)}
        else:
            blk["bill_2045_usd"] = None
            blk["change_2045_pct"] = None
        return blk

    reg = block(STATES)
    reg["name"] = "7 Corn Belt and Plains states (IA, NE, KS, MO, IL, SD, MN)"
    if fut is not None:
        reg["gcms_2045"] = sorted(fut.gcm.unique().tolist())
    summ = {"units": "USD per year (principal crops: corn, soybeans, wheat, sorghum)", "dollar_year": DOLLAR_YEAR,
            "mock": False, "region": reg, "states": {s: block([s]) for s in STATES},
            "notes": ["expected_bill_usd: expected annual crop-insurance drought indemnity at today's insured acres and "
                      "2020-2024 average liability per acre; lo/hi from 100 block-bootstrap refits.",
                      "taxpayer_share_usd = federal premium subsidy share (2020-2024) x expected bill; lo/hi scale the "
                      "bill interval by the same fraction.",
                      "actual_2022_usd / actual_2023_usd: RMA drought indemnity for the principal crops (nominal).",
                      "change_2045_pct: NEX-GDDP-CMIP6 2035-2054 vs 1995-2014 deltas applied to NASA POWER weather; "
                      "est = median over GCMs, lo/hi = 5th-95th percentile over GCM x bootstrap draws.",
                      "diversity_savings_usd: expected annual bill reduction if every county's share of cropland in 3+ "
                      "crop rotations rose to at least the regional insured-acre-weighted 90th percentile; "
                      + eff["label"]]}
    save_json(summ, WEB / "regional_summary.json", 1)
    print("region:", json.dumps({k: reg[k] for k in ("expected_bill_usd", "taxpayer_share_usd", "actual_2022_usd",
                                                     "actual_2023_usd", "change_2045_pct", "diversity_savings_usd")}))

    # ------------------------------------------------------------ meta
    has_cmip = (PROC / "cmip6_deltas.parquet").exists()
    gcms = sorted(pd.read_parquet(PROC / "cmip6_deltas.parquet").gcm.unique()) if has_cmip else []
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mock": False,
        "region": {"states": STATES},
        "data_sources": [
            {"name": "NASA POWER daily (MERRA-2 bias-corrected precipitation, temperature, root-zone soil wetness)",
             "nasa": True, "role": "Drought hazard features for every county and year 1981-2025 (the model's inputs)",
             "url": "https://power.larc.nasa.gov/"},
            {"name": "NASA NEX-GDDP-CMIP6 (via Microsoft Planetary Computer)", "nasa": True,
             "role": "2045 climate shift (2035-2054 vs 1995-2014 deltas)" if has_cmip else "2045 climate shift "
             "(not available in this build)", "url": "https://planetarycomputer.microsoft.com/dataset/nasa-nex-gddp-cmip6"},
            {"name": "NASA MODIS MOD13Q1 NDVI (via Microsoft Planetary Computer)", "nasa": True,
             "role": "Independent check and ablation of the hazard signal (not used in the headline model)",
             "url": "https://planetarycomputer.microsoft.com/dataset/modis-13Q1-061"},
            {"name": "USDA RMA Cause of Loss and Summary of Business", "nasa": False,
             "role": "Insured drought losses, liability, premiums and subsidies (the outcome)",
             "url": "https://www.rma.usda.gov/tools-reports/summary-of-business"},
            {"name": "USDA NASS Cropland Data Layer", "nasa": False, "role": "Crop-rotation diversity",
             "url": "https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php"},
            {"name": "USDA NRCS SSURGO (Soil Data Access)", "nasa": False, "role": "Soil available water storage",
             "url": "https://sdmdataaccess.sc.egov.usda.gov/"},
            {"name": "USDA NASS Census of Agriculture 2017/2022", "nasa": False, "role": "Irrigated share",
             "url": "https://www.nass.usda.gov/AgCensus/"},
            {"name": "US Drought Monitor", "nasa": False,
             "role": "Comparison only (ablation); not used in the headline model",
             "url": "https://droughtmonitor.unl.edu/"},
            {"name": "US Census cartographic boundaries 2023", "nasa": False, "role": "County shapes",
             "url": "https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html"},
        ],
        "caveats": [
            "Dollars are nominal; the expected bill uses each county's 2020-2024 average liability per insured acre, "
            "so it reflects 2020-2024 crop prices.",
            "Principal crops only (corn, soybeans, wheat, sorghum). RMA 'all crops' totals include rainfall-index "
            "pasture acres and other crops and are not used.",
            "Drought = RMA cause-of-loss code 11 only; heat, hot wind and area-plan (SCO/ECO) payouts are excluded, so "
            "the drought bill is a lower bound of weather-driven losses.",
            "RMA 2025 data are provisional and are not used for training, testing or the bill.",
            "NASA POWER weather is on a ~50 km MERRA-2 grid; counties in the same cell share weather.",
            "Out-of-time test: trained 2001-2020, tested 2021-2024. Intervals are bootstrap parameter intervals, not "
            "full predictive intervals (see hindcast.json for their coverage).",
            "Taxpayer share is an actuarial approximation (subsidy share x expected losses); it excludes delivery "
            "(A&O) reimbursements and underwriting gains.",
            "Rotation diversity: county insurance data show no robust drought-protection effect of rotation "
            "diversity; the slider uses the field-trial range (Bowles et al. 2020) as a labelled scenario."
            if eff["source"] == "trial_prior_scenario" else
            "Rotation diversity effect is an observational estimate; see notes/model.md for diagnostics.",
            (f"2045: NEX-GDDP-CMIP6 deltas from {len(gcms)} GCM(s) ({', '.join(gcms)}; 10 sampled years per 20-year "
             "period) applied to observed 1981-2024 NASA POWER weather (delta method; root-zone wetness shifted with an "
             "emulator fitted to NASA POWER; year-to-year variability held at today's). The rise is driven mostly by "
             "more extreme heat (EDD > 30 C); the loss model learned heat effects from years when heat came with "
             "drought, so the size of the rise is uncertain and the GCM spread is wide. No adaptation is assumed.")
            if has_cmip else "2045 projections not available in this build.",
            "Precipitation is NASA POWER (MERRA-2), not GPM IMERG: the IMERG host was not reachable from the build "
            "environment.",
        ],
        "validation": {k: val["metrics"][k] for k in val["metrics"]},
    }
    save_json(meta, WEB / "meta.json", 1)
    print("meta.json written")


if __name__ == "__main__":
    main()
