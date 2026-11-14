"""sat module: NASA NEX-GDDP-CMIP6 county deltas for ~2045 (2035-2054 vs 1995-2014), Jun-Aug.

Data: Microsoft Planetary Computer collection `nasa-nex-gddp-cmip6` (STAC, signed blob URLs on
nasagddp.blob.core.windows.net). One NetCDF4/HDF5 file per model/scenario/variable/year, global 0.25 deg daily,
chunked one full global day per chunk (1 x 600 x 1440, gzip+shuffle). We read only the HDF5 metadata (fsspec),
then fetch only the Jun-Aug daily chunks by HTTP range, decompress locally and keep only the region box
(lon -105..-87, lat 35..50). The box subset is cached as .npz under data/raw/nex_gddp/.
Each variable-year still costs ~45-70 MB of transfer (whole-globe chunks), so years are subsampled (see YEARS).

Adapted from shared/central_iowa_pipeline/pipeline/context_climate.py (read_pc, sine_dd_above).

Run:   /home/user/venv-db/bin/python pipeline/sat_cmip6.py            # fetch (skip cached) + compute
       /home/user/venv-db/bin/python pipeline/sat_cmip6.py --compute   # compute from cache only
Outputs: data/processed/cmip6_deltas.parquet, data/processed/cmip6_period_means.parquet
"""
import argparse
import sys
import threading
import time
import warnings
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings("ignore", message="Mean of empty slice")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "nex_gddp"
PROC = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
PROC.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "drought-bill-hackathon"}
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"

MODELS = ["ACCESS-CM2", "GFDL-ESM4", "MPI-ESM1-2-HR", "MRI-ESM2-0", "NorESM2-MM"]
# every other year (10 per 20-year period) to keep transfer at ~45-70 MB per variable-year
YEARS = {"historical": list(range(1995, 2015, 2)), "ssp245": list(range(2035, 2055, 2)),
         "ssp585": list(range(2035, 2055, 2))}
PERIOD = {"historical": "1995-2014", "ssp245": "2035-2054", "ssp585": "2035-2054"}
BOX = dict(west=-105.0, east=-87.0, south=35.0, north=50.0)
STATES = {"19": "IA", "31": "NE", "20": "KS", "29": "MO", "17": "IL", "46": "SD", "27": "MN"}

_client = None
_href = {}
_lock = threading.Lock()


def client():
    global _client
    import planetary_computer
    import pystac_client
    if _client is None:
        _client = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    return _client


def href(model, scen, year, var, refresh=False):
    with _lock:
        return _href_locked(model, scen, year, var, refresh)


def _href_locked(model, scen, year, var, refresh):
    k = (model, scen, year)
    if refresh or k not in _href:
        its = list(client().search(collections=["nasa-nex-gddp-cmip6"], query={
            "cmip6:model": {"eq": model}, "cmip6:scenario": {"eq": scen}, "cmip6:year": {"eq": year}}).items())
        if not its:
            raise RuntimeError(f"no STAC item {k}")
        _href[k] = {v: a.href for v, a in its[0].assets.items()}
    return _href[k][var]


def cache_path(model, scen, var, year):
    return RAW / model / scen / f"{var}_{year}.npz"


def fetch(model, scen, var, year, threads):
    out = cache_path(model, scen, var, year)
    if out.exists():
        return "cached"
    import cftime
    import fsspec
    import h5py
    url = href(model, scen, year, var)
    for attempt in range(3):
        try:
            with fsspec.filesystem("https", client_kwargs={"trust_env": True}).open(url, block_size=2 ** 20) as f:
                h = h5py.File(f, "r")
                ds = h[var]
                tv = h["time"][:]
                units = h["time"].attrs["units"]
                cal = h["time"].attrs.get("calendar", b"standard")
                units = units.decode() if isinstance(units, bytes) else units
                cal = cal.decode() if isinstance(cal, bytes) else cal
                lat = h["lat"][:]
                lon = h["lon"][:]
                dates = cftime.num2date(tv, units, calendar=cal)
                sel = [i for i, t in enumerate(dates) if t.month in (6, 7, 8)]
                infos = [ds.id.get_chunk_info_by_coord((i, 0, 0)) for i in sel]
                shuffle = ds.shuffle
                shape = ds.chunks[1:]
                assert ds.chunks[0] == 1 and tuple(shape) == (len(lat), len(lon)), ds.chunks
            break
        except Exception as e:  # noqa: BLE001
            print(f"  meta retry {model} {scen} {var} {year}: {e}", flush=True)
            time.sleep(5 * (attempt + 1))
            url = href(model, scen, year, var, refresh=True)
    else:
        raise RuntimeError("metadata read failed")
    lon180 = np.where(lon > 180, lon - 360, lon)
    iy = np.where((lat >= BOX["south"]) & (lat <= BOX["north"]))[0]
    ix = np.where((lon180 >= BOX["west"]) & (lon180 <= BOX["east"]))[0]
    state = {"url": url}

    def get(info):
        a, n = info.byte_offset, info.size
        for k in range(6):
            try:
                r = requests.get(state["url"], headers={**UA, "Range": f"bytes={a}-{a + n - 1}"}, timeout=120)
                if r.status_code in (200, 206) and len(r.content) == n:
                    return r.content
                if r.status_code == 403:
                    state["url"] = href(model, scen, year, var, refresh=True)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2 * (k + 1))
        raise RuntimeError("range read failed")

    with ThreadPoolExecutor(threads) as ex:
        raws = list(ex.map(get, infos))
    arr = np.empty((len(sel), len(iy), len(ix)), np.float32)
    for k, raw in enumerate(raws):
        b = np.frombuffer(zlib.decompress(raw), np.uint8)
        if shuffle:
            b = b.reshape(4, -1).T.ravel()
        a = b.view("<f4").reshape(shape)
        arr[k] = a[iy[0]:iy[-1] + 1, ix[0]:ix[-1] + 1]
    arr[arr > 1e19] = np.nan
    months = np.array([dates[i].month for i in sel], np.int8)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, data=arr, lat=lat[iy], lon=lon180[ix], month=months,
                        src=np.array(url.split("?")[0]), calendar=np.array(cal))
    tmp.rename(out)
    return f"{sum(i.size for i in infos) / 1e6:.0f}MB"


# ---------------------------------------------------------------- indices
def sine_dd_above(tmin, tmax, thr):
    """Single-sine degree-days above thr from daily Tmin/Tmax (degC). Same as context_climate.py / hazard module."""
    out = np.zeros_like(tmin)
    m = (tmax + tmin) / 2.0
    a = (tmax - tmin) / 2.0
    full = tmin >= thr
    out[full] = m[full] - thr
    part = (tmax > thr) & (tmin < thr)
    with np.errstate(invalid="ignore", divide="ignore"):
        th = np.arcsin(np.clip((thr - m[part]) / a[part], -1, 1))
        out[part] = ((m[part] - thr) * (np.pi / 2 - th) + a[part] * np.cos(th)) / np.pi
    out[np.isnan(tmin) | np.isnan(tmax)] = np.nan
    return out


def esat_kpa(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def load(model, scen, var, year):
    p = cache_path(model, scen, var, year)
    if not p.exists():
        return None
    z = np.load(p)
    return z["data"], z["month"], z["lat"], z["lon"]


def year_indices(model, scen, year):
    """Per-cell JJA indices (2-D lat x lon) for one model/scenario/year, or None if a core variable is missing."""
    got = {v: load(model, scen, v, year) for v in ("pr", "tasmax", "tasmin", "hurs")}
    if any(got[v] is None for v in ("pr", "tasmax", "tasmin")):
        return None, None
    pr, mon, lat, lon = got["pr"]
    tx = got["tasmax"][0] - 273.15
    tn = got["tasmin"][0] - 273.15
    for v in ("tasmax", "tasmin"):
        assert np.array_equal(got[v][1], mon)
    pr = pr * 86400.0  # kg m-2 s-1 -> mm/day
    tn = np.minimum(tn, tx)  # guard rare tasmin > tasmax
    idx = {"prcp_jja_mm": pr.sum(0), "tmax_jja_c": tx.mean(0), "tmin_jja_c": tn.mean(0),
           "edd30_jja": sine_dd_above(tn, tx, 30.0).sum(0)}
    for m, nm in ((6, "jun"), (7, "jul"), (8, "aug")):
        s = mon == m
        idx[f"prcp_{nm}_mm"] = pr[s].sum(0)
        idx[f"tmax_{nm}_c"] = tx[s].mean(0)
        idx[f"tmin_{nm}_c"] = tn[s].mean(0)
    if got["hurs"] is not None:
        rh = np.clip(got["hurs"][0], 0, 100)
        # same form as the hazard module's RH fallback: es = mean(es(Tmax), es(Tmin)); ea = es(Tmean) * RH
        # (NEX-GDDP `tas` is itself the mean of downscaled tasmax and tasmin)
        es = (esat_kpa(tx) + esat_kpa(tn)) / 2.0
        ea = esat_kpa((tx + tn) / 2.0) * rh / 100.0
        vpd = np.clip(es - ea, 0, None)
        idx["vpd_jja_kpa"] = vpd.mean(0)
        idx["hurs_jja_pct"] = rh.mean(0)
    return idx, (lat, lon)


def county_table():
    """counties.parquet from the geo module if present, else the Census 2023 cartographic file (500k)."""
    import geopandas as gpd
    zp = ROOT / "data" / "raw" / "census" / "cb_2023_us_county_500k.zip"
    if not zp.exists():
        zp.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get("https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip", headers=UA,
                         timeout=300)
        r.raise_for_status()
        zp.write_bytes(r.content)
    g = gpd.read_file(f"zip://{zp}")
    g = g[g["STATEFP"].isin(STATES)].copy()
    g["fips"] = g["STATEFP"] + g["COUNTYFP"]
    g = g.to_crs(4326)
    pt = g.to_crs(5070).representative_point().to_crs(4326)
    g["lon"], g["lat"] = pt.x.values, pt.y.values
    cp = PROC / "counties.parquet"
    if cp.exists():  # prefer the geo module's interior points for consistency with the hazard module
        c = pd.read_parquet(cp)[["fips", "lon", "lat"]]
        g = g.drop(columns=["lon", "lat"]).merge(c, on="fips", how="left")
        miss = g["lon"].isna()
        if miss.any():
            g.loc[miss, "lon"] = pt[miss.values].x.values
            g.loc[miss, "lat"] = pt[miss.values].y.values
    return g[["fips", "lon", "lat", "geometry"]].sort_values("fips").reset_index(drop=True)


def county_cells(g, lat, lon):
    """For each county: flat indices of 0.25 deg cells whose centres fall inside the polygon; if none, the cell
    nearest the interior point."""
    import geopandas as gpd
    LON, LAT = np.meshgrid(lon, lat)
    pts = gpd.GeoDataFrame({"k": np.arange(LON.size)}, geometry=gpd.points_from_xy(LON.ravel(), LAT.ravel()),
                           crs=4326)
    j = gpd.sjoin(pts, g[["fips", "geometry"]], predicate="within")
    cells = j.groupby("fips")["k"].apply(lambda s: np.array(sorted(s))).to_dict()
    method = {}
    for _, r in g.iterrows():
        if r.fips in cells:
            method[r.fips] = "cells_in_county"
        else:
            iy = int(np.abs(lat - r.lat).argmin())
            ix = int(np.abs(lon - r.lon).argmin())
            cells[r.fips] = np.array([iy * len(lon) + ix])
            method[r.fips] = "nearest_cell"
    return cells, method


def compute():
    g = county_table()
    rows = []
    cells = method = None
    for model in MODELS:
        for scen, yrs in YEARS.items():
            acc, used, used_vpd = {}, [], 0
            for y in yrs:
                idx, ll = year_indices(model, scen, y)
                if idx is None:
                    continue
                if cells is None:
                    cells, method = county_cells(g, *ll)
                used.append(y)
                used_vpd += "vpd_jja_kpa" in idx
                for k, v in idx.items():
                    acc.setdefault(k, []).append(v)
            if not used:
                print(f"  no data {model} {scen}")
                continue
            # VPD only if hurs was read for every year used (otherwise the mean mixes year samples)
            if used_vpd != len(used):
                acc.pop("vpd_jja_kpa", None)
                acc.pop("hurs_jja_pct", None)
            per = {k: np.nanmean(np.stack(v), 0).ravel() for k, v in acc.items()}
            for f in g["fips"]:
                c = cells[f]
                rec = {"fips": f, "gcm": model, "scenario": scen, "period": PERIOD[scen], "n_years": len(used),
                       "years_used": ",".join(map(str, used)), "n_cells": len(c), "cell_method": method[f]}
                for k, v in per.items():
                    rec[k] = float(np.nanmean(v[c]))
                rows.append(rec)
    if not rows:
        print("nothing cached yet")
        return
    pm = pd.DataFrame(rows)
    for c in ("vpd_jja_kpa", "hurs_jja_pct"):
        if c not in pm:
            pm[c] = np.nan
    pm.to_parquet(PROC / "cmip6_period_means.parquet", index=False)
    print(f"cmip6_period_means: {len(pm)} rows")

    hist = pm[pm.scenario == "historical"].set_index(["fips", "gcm"])
    out = []
    for scen in ("ssp245", "ssp585"):
        fut = pm[pm.scenario == scen].set_index(["fips", "gcm"])
        j = fut.merge(hist, left_index=True, right_index=True, suffixes=("", "_h"), how="inner")
        if j.empty:
            continue
        d = pd.DataFrame(index=j.index)
        d["scenario"] = scen
        d["d_prcp_jja_pct"] = 100 * (j.prcp_jja_mm / j.prcp_jja_mm_h - 1)
        d["d_edd30_jja"] = j.edd30_jja - j.edd30_jja_h
        d["d_tmax_jja_c"] = j.tmax_jja_c - j.tmax_jja_c_h
        d["d_tmin_jja_c"] = j.tmin_jja_c - j.tmin_jja_c_h
        d["d_vpd_jja"] = j.vpd_jja_kpa - j.vpd_jja_kpa_h
        for nm in ("jun", "jul", "aug"):
            d[f"d_prcp_{nm}_pct"] = 100 * (j[f"prcp_{nm}_mm"] / j[f"prcp_{nm}_mm_h"] - 1)
            d[f"d_tmax_{nm}_c"] = j[f"tmax_{nm}_c"] - j[f"tmax_{nm}_c_h"]
            d[f"d_tmin_{nm}_c"] = j[f"tmin_{nm}_c"] - j[f"tmin_{nm}_c_h"]
        d["hist_period"], d["fut_period"] = "1995-2014", "2035-2054"
        d["n_years_hist"], d["n_years_fut"] = j.n_years_h, j.n_years
        out.append(d.reset_index())
    dl = pd.concat(out, ignore_index=True)
    lead = ["fips", "gcm", "scenario", "d_prcp_jja_pct", "d_edd30_jja", "d_tmax_jja_c", "d_vpd_jja"]
    dl = dl[lead + [c for c in dl.columns if c not in lead]].sort_values(["fips", "gcm", "scenario"])
    dl.to_parquet(PROC / "cmip6_deltas.parquet", index=False)
    print(f"cmip6_deltas: {len(dl)} rows, {dl.fips.nunique()} counties, gcms {sorted(dl.gcm.unique())}")
    print(dl.groupby(["scenario", "gcm"])[["d_prcp_jja_pct", "d_edd30_jja", "d_tmax_jja_c", "d_vpd_jja"]]
          .mean().round(2).to_string())
    print(dl.groupby("scenario")[["d_prcp_jja_pct", "d_edd30_jja", "d_tmax_jja_c", "d_vpd_jja"]].mean().round(2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compute", action="store_true", help="compute from cache only")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--models", nargs="*", default=MODELS)
    ap.add_argument("--files", type=int, default=2, help="files fetched concurrently (threads are split)")
    ap.add_argument("--no-hurs", action="store_true")
    a = ap.parse_args()
    if not a.compute:
        phases = [("pr", "tasmax", "tasmin")] + ([] if a.no_hurs else [("hurs",)])
        t0 = time.time()
        for vars_ in phases:
            for model in a.models:
                tasks = [(scen, y, v) for scen, yrs in YEARS.items() for y in yrs for v in vars_]

                def one(task, model=model):
                    scen, y, v = task
                    t = time.time()
                    try:
                        s = fetch(model, scen, v, y, max(1, a.threads // a.files))
                    except Exception as e:  # noqa: BLE001
                        s = f"FAILED {e}"
                    if s != "cached":
                        print(f"{model} {scen} {y} {v}: {s} {time.time() - t:.0f}s "
                              f"(total {(time.time() - t0) / 60:.1f} min)", flush=True)

                # a.files files in flight at once so one file's HDF5 metadata read overlaps another's chunk reads
                with ThreadPoolExecutor(a.files) as ex:
                    list(ex.map(one, tasks))
                # refresh outputs after each model so partial results are usable
                try:
                    compute()
                except Exception as e:  # noqa: BLE001
                    print(f"compute failed: {e}", flush=True)
    compute()


if __name__ == "__main__":
    sys.exit(main())
