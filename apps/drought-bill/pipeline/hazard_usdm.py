"""hazard module: US Drought Monitor county statistics 2000-2025 -> data/processed/usdm_county_year.parquet.

Source: USDM Data Services REST API (https://usdmdataservices.unl.edu/api/), per state and calendar year:
  CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent?aoi=<ST>&startdate=1/1/Y&enddate=12/31/Y&statisticsType=1
      weekly % of county area; statisticsType=1 = cumulative ("traditional"): d1 = % area in D1-D4, d2 = D2-D4, ...
  CountyStatistics/GetDSCI?aoi=<ST>&startdate=...&enddate=...&statisticsType=1
      weekly Drought Severity and Coverage Index (0-500) = d0 + d1 + d2 + d3 + d4 (cumulative percents)
Raw JSON responses are cached in data/raw/usdm/. Weekly rows are assigned to a month by mapDate (the USDM valid date,
a Tuesday); rows outside the requested year are dropped (GetDSCI returns the week before startdate too).

Re-run: /home/user/venv-db/bin/python pipeline/hazard_usdm.py
"""
import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "usdm"
PROC = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
BASE = "https://usdmdataservices.unl.edu/api/CountyStatistics/"
STATES = ["IA", "NE", "KS", "MO", "IL", "SD", "MN"]
Y0, Y1 = 2000, 2025
UA = {"User-Agent": "drought-bill-hackathon", "Accept": "application/json"}
EP = {"area": "GetDroughtSeverityStatisticsByAreaPercent", "dsci": "GetDSCI"}


def fetch(kind, st, yr):
    f = RAW / f"{kind}_{st}_{yr}.json.gz"
    if f.exists() and f.stat().st_size > 100:
        with gzip.open(f, "rt") as fh:
            return kind, st, yr, json.load(fh)
    url = f"{BASE}{EP[kind]}?aoi={st}&startdate=1/1/{yr}&enddate=12/31/{yr}&statisticsType=1"
    last = None
    for attempt in range(6):
        try:
            r = requests.get(url, headers=UA, timeout=180)
            if r.status_code == 200:
                d = r.json()
                if isinstance(d, list) and d:
                    with gzip.open(f, "wt") as fh:
                        json.dump(d, fh)
                    return kind, st, yr, d
                last = f"empty/unexpected payload: {str(d)[:200]}"
            else:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        time.sleep(3 * 2 ** attempt)
    print("FAILED", kind, st, yr, last)
    return kind, st, yr, None


def main():
    t0 = time.time()
    jobs = [(k, s, y) for k in EP for s in STATES for y in range(Y0, Y1 + 1)]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda j: fetch(*j), jobs))
    failed = [(k, s, y) for k, s, y, d in res if d is None]
    area_rows, dsci_rows = [], []
    for k, s, y, d in res:
        if not d:
            continue
        for r in d:
            date = r["mapDate"][:10]
            if int(date[:4]) != y:
                continue
            if k == "area":
                area_rows.append((str(r["fips"]).zfill(5), date, float(r["none"]), float(r["d0"]), float(r["d1"]),
                                  float(r["d2"]), float(r["d3"]), float(r["d4"])))
            else:
                dsci_rows.append((str(r["fips"]).zfill(5), date, float(r["dsci"])))
    a = pd.DataFrame(area_rows, columns=["fips", "date", "none", "d0", "d1", "d2", "d3", "d4"]).drop_duplicates(
        ["fips", "date"])
    s = pd.DataFrame(dsci_rows, columns=["fips", "date", "dsci"]).drop_duplicates(["fips", "date"])
    w = a.merge(s, on=["fips", "date"], how="outer")
    w["date"] = pd.to_datetime(w.date)
    w["dsci_calc"] = w[["d0", "d1", "d2", "d3", "d4"]].sum(axis=1, min_count=5)
    w = w.sort_values(["fips", "date"]).reset_index(drop=True)
    w.to_parquet(RAW / "usdm_county_weekly.parquet", index=False)

    # keep only counties in the geo county list when available
    cf = PROC / "counties.parquet"
    if cf.exists():
        keep = set(pd.read_parquet(cf).fips)
        extra = sorted(set(w.fips) - keep)
        missing = sorted(keep - set(w.fips))
        print("USDM fips not in counties.parquet (dropped):", extra, "| counties without USDM:", missing)
        w = w[w.fips.isin(keep)]

    chk = w.dropna(subset=["dsci", "dsci_calc"])
    diff = (chk.dsci - chk.dsci_calc).abs()
    mono = ((w.d0 >= w.d1 - 0.01) & (w.d1 >= w.d2 - 0.01) & (w.d2 >= w.d3 - 0.01) & (w.d3 >= w.d4 - 0.01)).mean()
    print(f"weekly rows {len(w)}; GetDSCI vs sum(d0..d4): max abs diff {diff.max():.2f}, "
          f"share |diff|>1: {(diff > 1).mean():.4f}; cumulative monotone share {mono:.4f}")

    w["year"] = w.date.dt.year
    w["month"] = w.date.dt.month
    w["dsci_best"] = w.dsci.fillna(w.dsci_calc)
    jja = w[w.month.between(6, 8)]
    mjjas = w[w.month.between(5, 9)]
    g = jja.groupby(["fips", "year"])
    out = pd.DataFrame({
        "dsci_jja_mean": g.dsci_best.mean(),
        "dsci_jja_max": g.dsci_best.max(),
        "d1plus_pct_jja_mean": g.d1.mean(),
        "d2plus_pct_jja_mean": g.d2.mean(),
        "d2plus_pct_jja_max": g.d2.max(),
        "d3plus_pct_jja_max": g.d3.max(),
        "weeks_d2plus_jja": g.d2.apply(lambda x: int((x > 0).sum())),
        "weeks_d2plus50_jja": g.d2.apply(lambda x: int((x >= 50).sum())),
        "n_weeks_jja": g.size(),
    })
    out["dsci_mjjas_mean"] = mjjas.groupby(["fips", "year"]).dsci_best.mean()
    out["dsci_annual_mean"] = w.groupby(["fips", "year"]).dsci_best.mean()
    out = out.reset_index()
    # complete grid (fips x year); absent = null
    fips = sorted(w.fips.unique())
    grid = pd.MultiIndex.from_product([fips, range(Y0, Y1 + 1)], names=["fips", "year"]).to_frame(index=False)
    out = grid.merge(out, on=["fips", "year"], how="left")
    fl = out.select_dtypes("float64").columns
    out[fl] = out[fl].round(3)
    out.to_parquet(PROC / "usdm_county_year.parquet", index=False)
    print("usdm_county_year rows", len(out), "counties", out.fips.nunique(), "years", out.year.min(), out.year.max(),
          "null dsci_jja_mean:", int(out.dsci_jja_mean.isna().sum()), "failed requests:", failed)
    print(out.describe().T[["count", "mean", "min", "max"]].round(2).to_string())
    print(f"runtime {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
