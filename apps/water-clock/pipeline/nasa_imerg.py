"""GPM IMERG precipitation for the Water Clock region counties (2001-2025) + comparison with NASA POWER PRECTOTCORR.

Why not the Planetary Computer IMERG Zarr for annual totals: the `gpm-imerg-hhr` Zarr (IMERG V06B half-hourly,
precipitationCal) ends 2021-05-31 and is chunked as 12 half-hours x the full globe (~55 MB per chunk), so one year at
one point = 1460 chunks (~80 GB). At the measured few MB/s that is many hours per year -> infeasible here.
Primary route instead: NASA POWER serves IMERG daily totals at native 0.1 deg resolution:
  https://power.larc.nasa.gov/api/temporal/daily/point?parameters=IMERG_PRECTOT&community=AG&longitude=<lon>
      &latitude=<lat>&start=20000101&end=20251231&time-standard=UTC&format=JSON
  (IMERG is only offered on the UTC day standard; POWER says "The IMERG Source Data is not available at the Local
   Solar Time (LST) standard" otherwise). Header 'sources': ['IMERG'].
One point per county = the county equal-area centroid (same points as nasa_power.py) => the 0.1 deg IMERG cell
containing each centroid (a point sample, not a county area mean).
Cross-check (env IMERG_PC_CHECK=1, default on): for the 4 wettest region days of 2019-2020 (by POWER-IMERG), the
48 half-hourly fields of each UTC day are read from the Planetary Computer Zarr (4 chunks/day, box only kept and
cached in data/raw/imerg/pc_chunk_<i>.npz) and daily sums at the centroid cells are compared with POWER IMERG.
Outputs: data/processed/imerg_county_annual.parquet (county_fips, year, imerg_precip_in, imerg_precip_gs_in,
power_precip_in, power_precip_gs_in, n_days), data/raw/imerg/imerg_summary.json (correlation, bias, PC check).
Re-run: python3 pipeline/nasa_imerg.py
"""
import datetime as dt
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nasa_common import PROC, RAW, http_get, region_counties  # noqa: E402

D = RAW / "imerg"
D.mkdir(parents=True, exist_ok=True)
API = "https://power.larc.nasa.gov/api/temporal/daily/point"
Y0, Y1 = 2001, 2025


def fetch(row):
    f = D / f"power_imerg_{row.fips}.json"
    if f.exists():
        return row.fips, json.loads(f.read_text())
    r = http_get(API, params=dict(parameters="IMERG_PRECTOT", community="AG", longitude=row.lon, latitude=row.lat,
                                  start="20000101", end="20251231", **{"time-standard": "UTC"}, format="JSON"),
                 timeout=300)
    j = r.json()
    f.write_text(json.dumps(j))
    time.sleep(0.5)
    return row.fips, j


def pc_check(counties, daily):
    import planetary_computer
    import pystac_client
    import xarray as xr
    c = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                  modifier=planetary_computer.sign_inplace)
    a = c.get_collection("gpm-imerg-hhr").assets["zarr-abfs"]
    ds = xr.open_zarr(a.href, storage_options=a.extra_fields["xarray:storage_options"], consolidated=True,
                      decode_times=xr.coders.CFDatetimeCoder(use_cftime=True))
    t0 = dt.datetime(2000, 6, 1)
    reg = daily[(daily.date >= "2019-01-01") & (daily.date <= "2020-12-31")].groupby("date").imerg_mm.mean()
    days = list(reg.sort_values(ascending=False).index[:4])
    box = (counties.lon.min() - 0.2, counties.lat.min() - 0.2, counties.lon.max() + 0.2, counties.lat.max() + 0.2)
    first = ds.time.values[0]
    t0 = dt.datetime(first.year, first.month, first.day, first.hour, first.minute)

    def chunk(ci):
        f = D / f"pc_chunk_{ci}.npz"
        if f.exists():
            z = np.load(f)
            return ci, (z["p"], z["lat"], z["lon"])
        v = ds.precipitationCal.isel(time=slice(ci * 12, ci * 12 + 12)).sel(
            lon=slice(box[0], box[2]), lat=slice(box[1], box[3])).load()
        p = v.transpose("time", "lat", "lon").values.astype(np.float32)
        np.savez_compressed(f, p=p, lat=v.lat.values, lon=v.lon.values)
        return ci, (p, v.lat.values, v.lon.values)

    jobs = []
    for d in days:
        i0 = int((pd.Timestamp(d).to_pydatetime() - t0).total_seconds() // 1800)
        jobs += [(i0 // 12) + k for k in range(4)]
    with ThreadPoolExecutor(4) as ex:
        res = dict(ex.map(chunk, jobs))
    rows = []
    for d in days:
        i0 = int((pd.Timestamp(d).to_pydatetime() - t0).total_seconds() // 1800) // 12
        p = np.concatenate([res[i0 + k][0] for k in range(4)], axis=0)
        lat, lon = res[i0][1], res[i0][2]
        p = np.where(p < 0, np.nan, p)
        dsum = np.nansum(p * 0.5, axis=0)  # mm/h per half hour -> mm/day
        for r in counties.itertuples():
            i, j = np.abs(lat - r.lat).argmin(), np.abs(lon - r.lon).argmin()
            pw = daily[(daily.fips == r.fips) & (daily.date == d)].imerg_mm
            rows.append(dict(date=str(pd.Timestamp(d).date()), fips=r.fips, pc_v06_mm=float(dsum[i, j]),
                             power_imerg_mm=float(pw.iloc[0])))
    df = pd.DataFrame(rows)
    df.to_csv(D / "pc_check.csv", index=False)
    return dict(days=[str(pd.Timestamp(d).date()) for d in days], n_pairs=len(df),
                r=round(float(df.pc_v06_mm.corr(df.power_imerg_mm)), 3),
                mean_pc_v06_mm=round(float(df.pc_v06_mm.mean()), 2), mean_power_imerg_mm=round(float(df.power_imerg_mm.mean()), 2),
                note="PC = IMERG V06B precipitationCal half-hourly summed over the UTC day at the 0.1 deg cell nearest the "
                     "county centroid; POWER = IMERG daily via POWER (UTC). Version differences (V06 vs POWER's IMERG "
                     "version) mean the match is not expected to be exact.")


def main():
    counties = region_counties()
    with ThreadPoolExecutor(3) as ex:
        res = dict(ex.map(fetch, counties.itertuples()))
    frames = []
    for f, j in res.items():
        v = j["properties"]["parameter"]["IMERG_PRECTOT"]
        s = pd.Series(v, dtype=float)
        s.index = pd.to_datetime(s.index, format="%Y%m%d")
        frames.append(pd.DataFrame({"date": s.index, "fips": f, "imerg_mm": s.replace(-999.0, np.nan).values}))
    daily = pd.concat(frames, ignore_index=True)
    daily.to_parquet(D / "imerg_county_daily.parquet", index=False)
    d = daily[daily.date.dt.year.between(Y0, Y1)].copy()
    d["year"] = d.date.dt.year
    d["gs"] = d.date.dt.month.between(4, 9)
    ann = d.groupby(["fips", "year"]).agg(imerg_precip_mm=("imerg_mm", lambda x: x.sum(min_count=360)),
                                          n_days=("imerg_mm", "count")).reset_index()
    gs = d[d.gs].groupby(["fips", "year"]).imerg_mm.sum(min_count=180).rename("imerg_gs_mm").reset_index()
    ann = ann.merge(gs, on=["fips", "year"])
    ann["imerg_precip_in"] = (ann.imerg_precip_mm / 25.4).round(3)
    ann["imerg_precip_gs_in"] = (ann.imerg_gs_mm / 25.4).round(3)
    ann = ann.rename(columns={"fips": "county_fips"})[["county_fips", "year", "imerg_precip_in", "imerg_precip_gs_in", "n_days"]]
    pw = pd.read_parquet(PROC / "power_county_annual.parquet")[["county_fips", "year", "precip_in", "precip_gs_in"]]
    ann = ann.merge(pw.rename(columns={"precip_in": "power_precip_in", "precip_gs_in": "power_precip_gs_in"}),
                    on=["county_fips", "year"], how="left")
    ann["source"] = "GPM IMERG daily via NASA POWER (IMERG_PRECTOT, UTC days, 0.1 deg cell at county centroid)"
    ann.to_parquet(PROC / "imerg_county_annual.parquet", index=False)
    # comparison
    ok = ann.dropna(subset=["imerg_precip_in", "power_precip_in"])
    reg = ok.groupby("year")[["imerg_precip_in", "power_precip_in", "imerg_precip_gs_in", "power_precip_gs_in"]].mean()
    per_c = ok.groupby("county_fips").apply(lambda g: pd.Series(dict(
        r=g.imerg_precip_in.corr(g.power_precip_in), bias_in=(g.imerg_precip_in - g.power_precip_in).mean())),
        include_groups=False)
    summ = dict(
        years=[int(ok.year.min()), int(ok.year.max())], n_counties=int(ok.county_fips.nunique()), n_county_years=len(ok),
        region_annual_r=round(float(reg.imerg_precip_in.corr(reg.power_precip_in)), 3),
        region_gs_r=round(float(reg.imerg_precip_gs_in.corr(reg.power_precip_gs_in)), 3),
        region_mean_imerg_in=round(float(reg.imerg_precip_in.mean()), 2),
        region_mean_power_in=round(float(reg.power_precip_in.mean()), 2),
        region_bias_in=round(float((reg.imerg_precip_in - reg.power_precip_in).mean()), 2),
        region_bias_pct=round(float(100 * (reg.imerg_precip_in.mean() / reg.power_precip_in.mean() - 1)), 1),
        county_year_r=round(float(ok.imerg_precip_in.corr(ok.power_precip_in)), 3),
        county_r_median=round(float(per_c.r.median()), 3), county_r_min=round(float(per_c.r.min()), 3),
        county_bias_in_range=[round(float(per_c.bias_in.min()), 2), round(float(per_c.bias_in.max()), 2)],
        region_series={int(y): {k: round(float(v), 2) for k, v in r.items()} for y, r in reg.iterrows()})
    if os.environ.get("IMERG_PC_CHECK", "1") == "1":
        try:
            summ["pc_zarr_check"] = pc_check(counties, daily)
        except Exception as e:  # noqa: BLE001
            summ["pc_zarr_check"] = {"error": repr(e)[:500]}
    (D / "imerg_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps({k: v for k, v in summ.items() if k != "region_series"}, indent=1))
    print(reg.round(2).to_string())


if __name__ == "__main__":
    main()
