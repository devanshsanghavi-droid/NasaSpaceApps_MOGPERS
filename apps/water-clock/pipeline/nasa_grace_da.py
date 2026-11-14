"""GRACE-DA (GRACE Data Assimilation drought indicators, NASA GSFC / UNL NDMC) for the Water Clock region.

Source: https://nasagrace.unl.edu  (weekly CONUS folders listed on https://nasagrace.unl.edu/ConusData.aspx)
File:   https://nasagrace.unl.edu/data/YYYYMMDD/GRACEDADM_CLSM0125US_7D.AYYYYMMDD.030.nc4
Vars:   gws_inst (groundwater storage), rtzsm_inst (root-zone soil moisture), sfsm_inst (surface soil moisture),
        all PERCENTILES 0-100 relative to the 1948-2012 Catchment open-loop climatology; 0.125 deg; missing -999.
        (Percentiles are a drought indicator, NOT a volume.)

Sampling: the FIRST weekly file of each calendar month, 2002-04 .. latest (one file per month).
Each file is cropped to the wide High Plains box HP_BBOX and cached as data/raw/grace_da/crop/YYYYMMDD.npz
(the full CONUS .nc4 is deleted after cropping to save disk).

Outputs:
  data/processed/grace_region.parquet  (date, gws_pct, rtzsm_pct, sfsm_pct, source, + gmd1/3/4 gws means, n_cells)
  data/raw/grace_da/maps_cache.npz     (annual-mean grids reused by nasa_grace_maps.py)
Region mean = unweighted mean over 0.125 deg cells whose centres fall inside the 26 region county polygons
(cells are near equal-area at this latitude span; cos(lat) varies < 4%).
Re-run: python3 pipeline/nasa_grace_da.py    (env WORKERS=4)
"""
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nasa_common import HP_BBOX, PROC, RAW, http_get, region_counties  # noqa: E402

BASE = "https://nasagrace.unl.edu"
D = RAW / "grace_da"
CROP = D / "crop"
CROP.mkdir(parents=True, exist_ok=True)
VARS = ["gws_inst", "rtzsm_inst", "sfsm_inst"]
WORKERS = int(os.environ.get("WORKERS", "4"))


def list_dates():
    html = http_get(f"{BASE}/ConusData.aspx").text
    (D / "conusdata.html").write_text(html)
    ds = sorted(set(re.findall(r"ConusData\.aspx\?p=(\d{8})", html)))
    return ds


def monthly_first(dates):
    seen, out = set(), []
    for d in dates:
        if d[:6] not in seen:
            seen.add(d[:6])
            out.append(d)
    return out


def download(d):
    """Thread worker: download only (netCDF/HDF5 is not thread-safe, so cropping happens in the main thread)."""
    f = CROP / f"{d}.npz"
    tmp = D / f"tmp_{d}.nc4"
    if f.exists():
        return d, "cache"
    if tmp.exists() and tmp.stat().st_size > 100000:
        return d, "downloaded"
    url = f"{BASE}/data/{d}/GRACEDADM_CLSM0125US_7D.A{d}.030.nc4"
    try:
        r = http_get(url, timeout=300)
        tmp.write_bytes(r.content)
        return d, "downloaded"
    except Exception as e:  # noqa: BLE001
        return d, f"FAIL {e!r}"


def crop(d):
    import xarray as xr
    f = CROP / f"{d}.npz"
    tmp = D / f"tmp_{d}.nc4"
    with xr.open_dataset(tmp) as ds:
        sub = ds.sel(lon=slice(HP_BBOX[0], HP_BBOX[2]), lat=slice(HP_BBOX[1], HP_BBOX[3]))
        arrs = {v: sub[v].values[0].astype(np.float32) for v in VARS}
        for v in VARS:
            arrs[v][arrs[v] < -900] = np.nan
        np.savez_compressed(f, lat=sub.lat.values, lon=sub.lon.values,
                            time=str(pd.Timestamp(sub.time.values[0]).date()), **arrs)
    tmp.unlink()


def region_mask(lat, lon, counties):
    from shapely import contains_xy
    LON, LAT = np.meshgrid(lon, lat)
    union = counties.geometry.union_all()
    m = contains_xy(union, LON, LAT)
    gm = {g: contains_xy(counties[counties.gmd == g].geometry.union_all(), LON, LAT)
          for g in ["GMD1", "GMD3", "GMD4"]}
    return m, gm


def main():
    dates = monthly_first(list_dates())
    print(len(dates), "monthly dates", dates[0], dates[-1], flush=True)
    fails = []
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, (d, st) in enumerate(ex.map(download, dates)):
            if st == "downloaded":
                try:
                    crop(d)
                except Exception as e:  # noqa: BLE001
                    st = f"FAIL crop {e!r}"
            if st.startswith("FAIL"):
                fails.append((d, st))
                print(d, st, flush=True)
            if i % 25 == 0:
                print(i, d, st, flush=True)
    # months whose first weekly file is missing (HTTP 404): try the other weekly files of that month
    alld = list_dates()
    for d, _ in list(fails):
        for alt in [x for x in alld if x[:6] == d[:6] and x != d]:
            a, st = download(alt)
            if st == "downloaded":
                crop(alt)
                dates.append(alt)
                fails.append((d, f"replaced by {alt}"))
                break
    dates = sorted(set(dates))
    (D / "fetch_failures.txt").write_text("\n".join(f"{d}\t{s}" for d, s in fails))
    counties = region_counties()
    rows, grids, lat, lon = [], {}, None, None
    for d in dates:
        f = CROP / f"{d}.npz"
        if not f.exists():
            continue
        z = np.load(f)
        if lat is None:
            lat, lon = z["lat"], z["lon"]
            m, gm = region_mask(lat, lon, counties)
        row = dict(date=pd.Timestamp(d), file_date=d, data_time=str(z["time"]))
        for v in VARS:
            a = z[v]
            row[v.replace("_inst", "_pct")] = float(np.nanmean(a[m]))
        for g, mm in gm.items():
            row[f"gws_pct_{g.lower()}"] = float(np.nanmean(z["gws_inst"][mm]))
        row["n_cells"] = int(np.isfinite(z["gws_inst"][m]).sum())
        rows.append(row)
        grids[d] = z["gws_inst"]
    df = pd.DataFrame(rows)
    df["source"] = "GRACE-DA nasagrace.unl.edu GRACEDADM_CLSM0125US_7D (percentile)"
    df["tws_cm"] = np.nan  # filled by nasa_grace_gfz.py (volumetric GRACE TWS) if obtained
    out = PROC / "grace_region.parquet"
    if out.exists():  # keep TWS columns already merged by nasa_grace_gfz.py
        old = pd.read_parquet(out)
        keep = [c for c in old.columns if c.startswith("tws") or c.startswith("gws_cm") or c == "sm_anom_cm"]
        if keep:
            df = df.drop(columns=[c for c in keep if c in df.columns]).merge(
                old[["date"] + keep], on="date", how="left")
    df.to_parquet(out, index=False)
    # annual-mean grids for maps
    yrs = sorted({d[:4] for d in grids})
    ann = {}
    for y in yrs:
        st = np.stack([g for d, g in grids.items() if d[:4] == y])
        ann[y] = np.nanmean(st, axis=0).astype(np.float32)
    np.savez_compressed(D / "maps_cache.npz", lat=lat, lon=lon, years=np.array(yrs),
                        ann=np.stack([ann[y] for y in yrs]), latest=grids[max(grids)], latest_date=max(grids),
                        region_mask=m)
    print(df[["date", "gws_pct", "rtzsm_pct", "sfsm_pct", "n_cells"]].iloc[::12].to_string())
    print("rows", len(df), "fails", len(fails))


if __name__ == "__main__":
    main()
