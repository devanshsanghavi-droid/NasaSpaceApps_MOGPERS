"""conf module: GPM IMERG (half-hourly, 0.1 deg, precipitationCal) storm intensity / erosivity for AMJ.

Constraints found (2026-11-14):
  * The Planetary Computer gpm-imerg-hhr Zarr ends 2021-05-31 (collection temporal extent), so only AMJ
    2016-2020 are complete inside the 2016-2024 panel. 2021 (no June) and 2022-2024 stay null.
  * Zarr chunks are (12 half-hours x full globe) ~55 MB compressed; measured aggregate throughput ~4 MB/s,
    so a full AMJ season (364 chunks, ~20 GB) takes >1 h per year.
  => Time subsample: per year, the TOP_K wettest AMJ local days by NASA POWER PRECTOTCORR (max over the 9
     POWER cells covering the tile). For each, the 4 chunks spanning the local day (06 UTC d .. 06 UTC d+1,
     ~CST) are read and the IMERG box over the POWER cells is kept (cached per chunk in data/raw/imerg/).
Metrics per POWER cell and year (IMERG pixels whose centres fall inside the cell):
  imerg_max30min_amj: max half-hourly rate (mm/h) over the sampled days and pixels (cell max)
  imerg_r_factor: mean over pixels of sum over sampled days of EI30 (MJ mm ha-1 h-1); a storm = one local day
     with >=12.7 mm at the pixel; e = 0.29[1-0.72 exp(-0.05 i)] MJ ha-1 mm-1 (RUSLE, Brown & Foster 1987);
     I30 = max half-hour intensity. This is a LOWER BOUND on the AMJ erosivity (only the TOP_K days).
Output: data/raw/conf/imerg_annual.parquet (merged into data/weather_annual.parquet by conf_assemble.py)
Re-run: .venv/bin/python pipeline/conf_imerg.py   (env TOP_K, YEARS="2016-2020")
"""
import datetime as dt
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "imerg"
OUT = ROOT / "data" / "raw" / "conf"
RAW.mkdir(parents=True, exist_ok=True)
TOP_K = int(os.environ.get("TOP_K", "6"))
Y0, Y1 = (int(v) for v in os.environ.get("YEARS", "2016-2020").split("-"))
T0 = dt.datetime(2000, 6, 1)
DLAT, DLON = 0.5, 0.625


def open_ds():
    c = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                  modifier=planetary_computer.sign_inplace)
    a = c.get_collection("gpm-imerg-hhr").assets["zarr-abfs"]
    return xr.open_zarr(a.href, storage_options=a.extra_fields["xarray:storage_options"], consolidated=True,
                        decode_times=xr.coders.CFDatetimeCoder(use_cftime=True))


def chunk_ids(day):
    start = dt.datetime(day.year, day.month, day.day, 6)
    i0 = int((start - T0).total_seconds() // 1800)
    assert i0 % 12 == 0
    return [i0 // 12 + k for k in range(4)]


def get_chunk(ds, ci, box, tries=4):
    f = RAW / f"chunk_{ci}.npz"
    if f.exists():
        z = np.load(f)
        return z["p"], z["lat"], z["lon"], z["t"]
    last = None
    for a in range(tries):
        try:
            v = ds.precipitationCal.isel(time=slice(ci * 12, ci * 12 + 12)).sel(
                lon=slice(box[0], box[2]), lat=slice(box[1], box[3])).load()
            p = v.transpose("time", "lat", "lon").values.astype(np.float32)
            t = np.array([str(x) for x in v.time.values])
            np.savez_compressed(f, p=p, lat=v.lat.values, lon=v.lon.values, t=t)
            return p, v.lat.values, v.lon.values, t
        except Exception as e:  # noqa
            last = e
            time.sleep(5)
    raise RuntimeError(f"chunk {ci}: {last!r}")


def main():
    daily = pd.read_parquet(ROOT / "data" / "weather_daily_power.parquet")
    cells = daily[["power_cell_id", "cell_lat", "cell_lon"]].drop_duplicates().reset_index(drop=True)
    box = (cells.cell_lon.min() - DLON / 2, cells.cell_lat.min() - DLAT / 2,
           cells.cell_lon.max() + DLON / 2, cells.cell_lat.max() + DLAT / 2)
    amj = daily[daily.date.dt.month.between(4, 6) & daily.date.dt.year.between(Y0, Y1)]
    dmax = amj.groupby("date").PRECTOTCORR.max()
    days = []
    for yr, s in dmax.groupby(dmax.index.year):
        days += list(s.sort_values(ascending=False).index[:TOP_K])
    days = sorted(days)
    print("sampled days", len(days), [d.strftime("%Y-%m-%d") for d in days], flush=True)
    ds = open_ds()
    jobs = sorted({ci for d in days for ci in chunk_ids(d)})
    print("chunks", len(jobs), flush=True)
    t0 = time.time()
    done = [0]

    def work(ci):
        r = get_chunk(ds, ci, box)
        done[0] += 1
        if done[0] % 10 == 0:
            print(f"{done[0]}/{len(jobs)} chunks, {time.time() - t0:.0f}s", flush=True)
        return ci, r

    with ThreadPoolExecutor(10) as ex:
        res = dict(ex.map(work, jobs))
    lat = res[jobs[0]][1]; lon = res[jobs[0]][2]
    rows = []
    for _, cr in cells.iterrows():
        mlat = (lat >= cr.cell_lat - DLAT / 2) & (lat < cr.cell_lat + DLAT / 2)
        mlon = (lon >= cr.cell_lon - DLON / 2) & (lon < cr.cell_lon + DLON / 2)
        for yr in range(Y0, Y1 + 1):
            ydays = [d for d in days if d.year == yr]
            ei_sum = None
            mx = -np.inf
            n_storm = []
            for d in ydays:
                p = np.concatenate([res[ci][0] for ci in chunk_ids(d)], axis=0)[:, mlat][:, :, mlon]
                p = np.where(p < 0, np.nan, p)  # mm/h per half hour
                depth = p * 0.5
                tot = np.nansum(depth, axis=0)
                e = 0.29 * (1 - 0.72 * np.exp(-0.05 * p))
                E = np.nansum(e * depth, axis=0)
                i30 = np.nanmax(p, axis=0)
                ei = np.where(tot >= 12.7, E * i30, 0.0)
                ei_sum = ei if ei_sum is None else ei_sum + ei
                mx = max(mx, float(np.nanmax(p)))
                n_storm.append(float((tot >= 12.7).mean()))
            rows.append(dict(power_cell_id=cr.power_cell_id, year=yr, imerg_max30min_amj=mx,
                             imerg_r_factor=float(np.nanmean(ei_sum)), imerg_n_days_sampled=len(ydays),
                             imerg_mean_erosive_frac=float(np.mean(n_storm)), imerg_n_pixels=int(mlat.sum() * mlon.sum())))
    out = pd.DataFrame(rows)
    out.to_parquet(OUT / "imerg_annual.parquet", index=False)
    (OUT / "imerg_sampled_days.json").write_text(json.dumps([d.strftime("%Y-%m-%d") for d in days]))
    print(out.round(2).to_string())


if __name__ == "__main__":
    main()
