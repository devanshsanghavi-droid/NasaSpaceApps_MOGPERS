"""Build the modelling panel: county x crop year (2001-2025) for corn, soybeans, wheat, sorghum and the
`principal` aggregate (sum of the four), joined to NASA POWER hazard features, static modifiers, USDM, and (when
present) MODIS and CDL rotation diversity.

Outputs
  model/outputs/hazard_features.parquet  county x year 1981-2025 observed hazard features (recomputed from POWER daily)
  model/outputs/county_season_obs.parquet  seasonal aggregates per county-year (input for CMIP6 perturbation)
  model/outputs/power_base_stats.pkl       per-cell 1991-2020 base stats (for standardising perturbed weather)
  model/outputs/panel.parquet            modelling panel
Run: /home/user/venv-db/bin/python model/build_panel.py
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import CROPS, OUT, PRINCIPAL, PROC, PROVISIONAL_YEARS, save_json  # noqa: E402
from hazard_features import (base_stats, cell_season, county_cells, fit_wetness_emulator, load_daily,  # noqa: E402
                             standardise)

SUMS = ["insured_acres", "liability_usd", "premium_usd", "subsidy_usd", "indem_total_usd", "indem_drought_usd",
        "indem_heat_usd", "indem_excess_moist_usd", "det_acres_drought"]


def hazard():
    daily = load_daily()
    cy = cell_season(daily)
    bs = base_stats(cy)
    cyz = standardise(cy, bs)
    cc = county_cells()
    feat = cc.merge(cyz, on="cell_id", how="left")
    # check reproduction of the hazard module's columns
    hz = pd.read_parquet(PROC / "hazard_county_year.parquet")
    chk = feat.merge(hz, on=["fips", "year"], suffixes=("", "_hz"))
    report = {}
    for c in ["prcp_jja_mm", "edd30_jja", "spi_jja", "gwetroot_jja", "gwetroot_jja_pct", "vpd_jja_kpa", "hazard_z",
              "prcp_mj_anom_pct"]:
        report[c] = float(np.nanmax(np.abs(chk[c] - chk[c + "_hz"])))
    print("max |recomputed - hazard module|:", {k: round(v, 5) for k, v in report.items()})
    emu = fit_wetness_emulator(cy, bs)
    print("wetness emulator:", emu)
    feat.to_parquet(OUT / "hazard_features.parquet", index=False)
    with open(OUT / "power_base_stats.pkl", "wb") as f:
        pickle.dump({"base_stats": bs, "emulator": emu}, f)
    save_json({"reproduction_max_abs_diff": report, "wetness_emulator": emu}, OUT / "hazard_features_check.json", 1)
    return feat


# RMA county codes that are not Census counties: RMA splits a few large counties into two rating areas
# (Pottawattamie IA, Otter Tail MN, Polk MN) and still uses the old Shannon SD code. They are merged into the
# Census county so that every row joins to NASA POWER hazard and soils.
RMA_FIPS_MAP = {"19156": "19155", "27112": "27111", "27120": "27119", "46113": "46102"}


def rma_panel():
    r = pd.read_parquet(PROC / "rma_county_year.parquet")
    r = r[r.crop.isin(CROPS)].copy()
    r["irr_ac"] = r.irrigated_insured_share * r.insured_acres
    r["irr_den"] = np.where(r.irrigated_insured_share.notna(), r.insured_acres, np.nan)
    r["fips"] = r.fips.replace(RMA_FIPS_MAP)
    r = r.groupby(["fips", "year", "crop"], as_index=False)[SUMS + ["irr_ac", "irr_den"]].sum(min_count=1)
    r["irrigated_insured_share"] = r.irr_ac / r.irr_den
    r = r.drop(columns=["irr_den"])
    p = r.groupby(["fips", "year"], as_index=False)[SUMS + ["irr_ac"]].sum(min_count=1)
    irr_den = r[r.irrigated_insured_share.notna()].groupby(["fips", "year"]).insured_acres.sum()
    p = p.merge(irr_den.rename("irr_den").reset_index(), on=["fips", "year"], how="left")
    p["irrigated_insured_share"] = p.irr_ac / p.irr_den
    p["crop"] = PRINCIPAL
    # crop mix of the principal aggregate (liability shares)
    mix = r.pivot_table(index=["fips", "year"], columns="crop", values="liability_usd", aggfunc="sum").fillna(0)
    tot = mix.sum(axis=1).replace(0, np.nan)
    mix = mix.div(tot, axis=0).add_prefix("liab_share_").reset_index()
    p = p.drop(columns=["irr_ac", "irr_den"])
    r = r.drop(columns=["irr_ac"])
    out = pd.concat([r, p], ignore_index=True)
    out = out.merge(mix, on=["fips", "year"], how="left")
    out["lcr_drought"] = np.where(out.liability_usd > 0, out.indem_drought_usd / out.liability_usd, np.nan)
    out["lcr_excess"] = np.where(out.liability_usd > 0, out.indem_excess_moist_usd / out.liability_usd, np.nan)
    out["lcr_total"] = np.where(out.liability_usd > 0, out.indem_total_usd / out.liability_usd, np.nan)
    out["drought_usd_per_ac"] = np.where(out.insured_acres > 0, out.indem_drought_usd / out.insured_acres, np.nan)
    out["liab_per_ac"] = np.where(out.insured_acres > 0, out.liability_usd / out.insured_acres, np.nan)
    out["subsidy_share"] = np.where(out.premium_usd > 0, out.subsidy_usd / out.premium_usd, np.nan)
    out["provisional"] = out.year.isin(PROVISIONAL_YEARS)
    return out


def static():
    s = pd.read_parquet(PROC / "county_static.parquet")[
        ["fips", "aws0_100_mm", "aws0_150_mm", "nccpi", "irrigated_share", "cropland_share"]]
    c = pd.read_parquet(PROC / "counties.parquet")[["fips", "state_abbr", "name", "lon", "lat"]]
    return c.merge(s, on="fips", how="left")


def optional(name, cols=None):
    p = PROC / f"{name}.parquet"
    if not p.exists():
        print(f"[info] {name}.parquet not present yet")
        return None
    d = pd.read_parquet(p)
    return d if cols is None else d[[c for c in cols if c in d.columns]]


def main():
    feat = hazard()
    rma = rma_panel()
    st = static()
    panel = rma.merge(st, on="fips", how="left").merge(feat.drop(columns=["cell_id"]), on=["fips", "year"],
                                                        how="left")
    panel = panel.merge(feat[["fips", "cell_id"]].drop_duplicates(), on="fips", how="left")
    usdm = pd.read_parquet(PROC / "usdm_county_year.parquet")[["fips", "year", "dsci_jja_mean", "d2plus_pct_jja_max",
                                                              "dsci_mjjas_mean"]]
    panel = panel.merge(usdm, on=["fips", "year"], how="left")
    modis = optional("modis_county_year", ["fips", "year", "ndvi_jul_aug", "vci_jul_aug", "ndvi_z"])
    if modis is not None:
        panel = panel.merge(modis, on=["fips", "year"], how="left")
    panel = panel.sort_values(["crop", "fips", "year"]).reset_index(drop=True)
    panel.to_parquet(OUT / "panel.parquet", index=False)
    print("panel:", panel.shape, panel.groupby("crop").size().to_dict())
    print(panel[panel.crop == PRINCIPAL].groupby("year")[["indem_drought_usd", "liability_usd"]].sum().tail(6) / 1e6)


if __name__ == "__main__":
    main()
