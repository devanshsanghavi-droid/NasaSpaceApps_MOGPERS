"""evidence module: US Drought Monitor (USDM) county statistics for the tile counties.

Fetches weekly USDM categorical-cumulative area percentages (statisticsType=1: d1 = % area in D1 or worse, etc.)
for the 14 counties that intersect HLS tile 15TVG (read from data/counties.geojson, owned by `context`),
2016-2024, caches raw JSON under data/raw/usdm/, and writes:
  usdm_tile_weekly.csv   weekly rows, all tile counties
  usdm_tile_summary.csv  May-Sep diagnostics per county x year
  usdm_core_by_year.csv  8 core counties per year, using the SAME aggregation as the canonical
                         `shock_years` block of data/evidence_priors.json (mean over core-county weekly rows
                         within each month, then mean of the May-Sep monthly means)
pipeline/evidence_build.py recomputes shock_years from usdm_tile_weekly.csv with that same method.

Re-run: .venv/bin/python pipeline/evidence_usdm.py
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "usdm")
os.makedirs(RAW, exist_ok=True)

# Counties that intersect the tile: taken from data/counties.geojson (context module), 14 fips.
_GJ = json.load(open(os.path.join(ROOT, "data", "counties.geojson")))
COUNTIES = {f["properties"]["fips"]: f["properties"]["name"] for f in _GJ["features"]}
# Core tile counties (largest share of the tile; region.json focus counties)
CORE = ["19169", "19015", "19153", "19127", "19079", "19083", "19099", "19049"]
assert set(CORE) <= set(COUNTIES), "core county missing from counties.geojson"
URL = ("https://usdmdataservices.unl.edu/api/CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent"
       "?aoi={fips}&startdate=1/1/2016&enddate=12/31/2024&statisticsType=1")


def fetch(fips):
    path = os.path.join(RAW, f"usdm_{fips}_2016_2024.json")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return fips, json.load(open(path))
    for attempt in range(4):
        try:
            r = requests.get(URL.format(fips=fips), headers={"User-Agent": "counterfield-hackathon",
                                                             "Accept": "application/json"}, timeout=90)
            r.raise_for_status()
            data = r.json()
            json.dump(data, open(path, "w"))
            return fips, data
        except Exception as e:  # noqa: BLE001
            print("retry", fips, attempt, e)
            time.sleep(3 * (attempt + 1))
    return fips, None


def main():
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(fetch, COUNTIES))
    rows = []
    for fips, data in sorted(results):
        if not data:
            print("FAILED", fips)
            continue
        for d in data:
            rows.append({"fips": fips, "county": COUNTIES[fips], "date": d["mapDate"][:10],
                         "d0": float(d["d0"]), "d1": float(d["d1"]), "d2": float(d["d2"]),
                         "d3": float(d["d3"]), "d4": float(d["d4"])})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df.date.dt.year
    df.to_csv(os.path.join(RAW, "usdm_tile_weekly.csv"), index=False)
    gs = df[df.date.dt.month.between(5, 9)]
    summ = gs.groupby(["fips", "county", "year"]).agg(
        weeks=("d1", "size"),
        max_d1_pct=("d1", "max"), max_d2_pct=("d2", "max"), max_d3_pct=("d3", "max"),
        mean_d1_pct=("d1", "mean"), mean_d2_pct=("d2", "mean"),
        weeks_d1_over50=("d1", lambda s: int((s > 50).sum())),
        weeks_d2_over50=("d2", lambda s: int((s > 50).sum())),
    ).reset_index()
    summ["core"] = summ.fips.isin(CORE)
    summ.to_csv(os.path.join(RAW, "usdm_tile_summary.csv"), index=False)
    # canonical aggregation (identical to evidence_build.shock_years): monthly mean over core-county weekly rows,
    # rounded to 0.1, then mean of May-Sep monthly means
    c = df[df.fips.isin(CORE)].copy()
    c["month"] = c.date.dt.month
    monthly = c.groupby(["year", "month"])[["d0", "d1", "d2", "d3"]].mean().round(1)
    gsm = monthly[monthly.index.get_level_values("month").isin(range(5, 10))]
    core = gsm.groupby("year").agg(may_sep_mean_D1plus_pct=("d1", "mean"), may_sep_mean_D2plus_pct=("d2", "mean"),
                                   may_sep_max_month_D2plus_pct=("d2", "max"))
    diag = summ[summ.core].groupby("year").agg(
        max_week_d2_any_core_county=("max_d2_pct", "max"), max_week_d3_any_core_county=("max_d3_pct", "max"),
        median_weeks_d1_over50=("weeks_d1_over50", "median"),
        median_weeks_d2_over50=("weeks_d2_over50", "median"))
    core = core.join(diag).round(1)
    core.to_csv(os.path.join(RAW, "usdm_core_by_year.csv"))
    print(core.to_string())


if __name__ == "__main__":
    main()
