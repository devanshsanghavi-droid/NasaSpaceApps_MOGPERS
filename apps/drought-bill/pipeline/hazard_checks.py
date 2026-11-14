"""hazard module: sanity checks on hazard_county_year.parquet and usdm_county_year.parquet (prints a report).

Re-run: /home/user/venv-db/bin/python pipeline/hazard_checks.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
hz = pd.read_parquet(PROC / "hazard_county_year.parquet")
us = pd.read_parquet(PROC / "usdm_county_year.parquet")
pd.set_option("display.width", 200)

print("== hazard coverage: rows", len(hz), "counties", hz.fips.nunique(), "years", hz.year.min(), "-", hz.year.max(),
      "| null hazard_z", int(hz.hazard_z.isna().sum()))
print("== usdm coverage: rows", len(us), "counties", us.fips.nunique(), "years", us.year.min(), "-", us.year.max())

# 1. Most extreme year
st_year = hz.groupby(["state_abbr", "year"])[["hazard_z", "edd30_jja", "spi_jja"]].mean()
print("\n== top-3 state-mean hazard_z years (1981-2025)")
for st, g in st_year.groupby(level=0):
    t = g.hazard_z.droplevel(0).sort_values(ascending=False).head(3)
    print(f"  {st}: " + ", ".join(f"{y} ({v:.2f})" for y, v in t.items()))
reg = hz.groupby("year")[["hazard_z", "edd30_jja", "spi_jja", "prcp_jja_anom_pct", "gwetroot_jja_pct"]].mean()
print("\n== region-mean top-5 hazard_z years\n", reg.sort_values("hazard_z", ascending=False).head(5).round(2))
mx = hz.loc[hz.groupby("fips").hazard_z.idxmax(), ["fips", "state_abbr", "year"]]
print("\n== share of counties whose max-hazard_z year is 2012:", round((mx.year == 2012).mean(), 3))
print("   by state:", mx.assign(is12=mx.year == 2012).groupby("state_abbr").is12.mean().round(2).to_dict())
print("   most common max years:", mx.year.value_counts().head(5).to_dict())
for col, fn in [("edd30_jja", "idxmax"), ("spi_jja", "idxmin")]:
    yy = hz.loc[getattr(hz.groupby("fips")[col], fn)(), "year"]
    print(f"   share of counties whose {fn[3:]} {col} year is 2012: {(yy == 2012).mean():.3f}")

# 2./3. 2022 and 2023 by state
print("\n== 2012 / 2022 / 2023 state means (spi_jja, prcp_jja_anom_pct, edd30_jja, gwetroot_jja_pct, hazard_z)")
cols = ["spi_jja", "prcp_jja_anom_pct", "edd30_jja", "gwetroot_jja_pct", "hazard_z"]
clim = hz[hz.year.between(1991, 2020)].groupby("state_abbr").edd30_jja.mean().rename("edd30_clim_9120")
for y in (2012, 2022, 2023):
    t = hz[hz.year == y].groupby("state_abbr")[cols].mean().join(clim).round(2)
    t["frac_cty_spi_lt_-1"] = hz[hz.year == y].assign(d=lambda d: d.spi_jja < -1).groupby("state_abbr").d.mean().round(2)
    print(f"-- {y}\n{t.to_string()}")
u = us.merge(hz[["fips", "state_abbr"]].drop_duplicates(), on="fips")
print("\n== USDM state means of dsci_jja_mean: 2012 / 2022 / 2023")
print(u[u.year.isin([2012, 2022, 2023])].pivot_table(index="state_abbr", columns="year", values="dsci_jja_mean").round(1))

# 4. Correlation with USDM
m = hz.merge(us, on=["fips", "year"], how="inner")
m = m[m.year.between(2000, 2024)]
print(f"\n== hazard_z vs USDM dsci_jja_mean, county-years 2000-2024 (n={len(m)})")
for c in ["hazard_z", "spi_jja", "edd30_jja", "gwetroot_jja", "gwetroot_jja_pct"]:
    print(f"  {c:18s} pearson {m[c].corr(m.dsci_jja_mean):+.3f}  spearman "
          f"{m[c].corr(m.dsci_jja_mean, method='spearman'):+.3f}")
dm = m[["hazard_z", "dsci_jja_mean"]] - m.groupby("fips")[["hazard_z", "dsci_jja_mean"]].transform("mean")
print(f"  within-county (county-demeaned) pearson hazard_z~dsci: {dm.hazard_z.corr(dm.dsci_jja_mean):+.3f}")
print("  by state pearson:", m.groupby("state_abbr").apply(
    lambda g: round(g.hazard_z.corr(g.dsci_jja_mean), 3), include_groups=False).to_dict())
print("  hazard_z vs d2plus_pct_jja_max pearson:", round(m.hazard_z.corr(m.d2plus_pct_jja_max), 3))
ym = m.groupby("year")[["hazard_z", "dsci_jja_mean"]].mean()
print("  region-year means pearson (n=25):", round(ym.hazard_z.corr(ym.dsci_jja_mean), 3))
print(ym.round(2).T.to_string())
