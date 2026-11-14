"""COUNTERFIELD context module: NASA NEX-GDDP-CMIP6 future climate for the tile + CONUS climate analogs.

Data access
- Primary: NASA NCCS THREDDS NetCDF Subset Service (server-side bbox/time subsetting of the NEX-GDDP-CMIP6 daily files).
  The NetCDF files are internally chunked as one full global day per chunk (1 x 600 x 1440), so any byte-range read
  of a small box from the Planetary Computer blob copies still has to pull ~0.67 MB per variable-day (~100 MB per
  variable-season). At the ~6 MB/s available here, that is hours; NCSS returns only the box.
- Fallback (per file, automatic): Microsoft Planetary Computer `nasa-nex-gddp-cmip6` (STAC, signed blob URLs), reading
  only the needed daily chunks by HTTP range and decompressing locally (gzip + shuffle), then subsetting the box.
- `--pc-check` compares one variable-year tile mean between the two sources and stores the result in the JSON.

Indices per year (computed per 0.25 deg cell, then averaged over the cells whose centres lie inside the tile bounds):
  gdd_may_sep          sum over May-Sep of ((min(max(Tx,10),30) + min(max(Tn,10),30))/2 - 10)   [degC-days] (86/50 method,
                       identical to pipeline/conf_weather.py)
  hdd30_jul_aug        single-sine degree-days above 30C from Tn/Tx (SAME definition as conf_weather.py /
                       data/weather_annual.parquet hdd30_jul_aug)                                 [degC-days]
  hdd30tx_jul_aug      sum over Jul-Aug of max(Tx - 30, 0) (Tmax-excess; ~4x larger than the sine value) [degC-days]
  (The cached .npz indices keep their original internal names: npz 'hdd30_jul_aug' = Tmax-excess, npz
   'hdd30sine_jul_aug' = sine. Output names are mapped in npz_key().)
  days_tmax_gt30_jul_aug  count of Jul-Aug days with Tx > 30C                                     [days]
  prcp_amj, prcp_jja   precipitation totals                                                       [mm]
  tmax_jul             mean July Tx                                                               [degC]

Run: .venv/bin/python pipeline/context_climate.py [--pc-check]
Output: data/climate_future.json ; cache in data/raw/nex_gddp/
"""
import datetime as dt
import json
import re
import sys
import time
import warnings
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import requests
import xarray as xr

warnings.filterwarnings("ignore", message="Mean of empty slice")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "nex_gddp"
NCSS_DIR = RAW / "ncss"
IDX_DIR = RAW / "indices"
for d in (NCSS_DIR, IDX_DIR):
    d.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "data" / "climate_future.json"
UA = {"User-Agent": "counterfield-hackathon"}

MODELS = ["GFDL-ESM4", "MRI-ESM2-0", "ACCESS-CM2"]
VARIANT = "r1i1p1f1"
SCEN_YEARS = {"historical": list(range(1995, 2015)), "ssp245": list(range(2035, 2056)), "ssp585": list(range(2035, 2056))}
VARS = ["tasmax", "tasmin", "pr"]
# day windows per variable (no February -> identical day counts across noleap / gregorian calendars)
WINDOW = {"tasmax": ((5, 1), (9, 30), 153), "tasmin": ((5, 1), (9, 30), 153), "pr": ((4, 1), (8, 31), 153)}

REGION = json.loads((ROOT / "data" / "region.json").read_text())
TW, TS, TE, TN = REGION["tile_bounds_lonlat"]
TILE_BOX = dict(north=42.75, south=41.25, west=360 + TW - 0.25, east=360 + TE + 0.25)
CONUS_BOX = dict(north=49.5, south=24.5, west=235.0, east=293.5)

THREDDS = "https://ds.nccs.nasa.gov/thredds"
NCSS_BASE = f"{THREDDS}/ncss/grid/AMES/NEX/GDDP-CMIP6"
CAT_BASE = f"{THREDDS}/catalog/AMES/NEX/GDDP-CMIP6"

# Output (JSON) name -> internal name used in cell_indices() and the cached .npz files.
_NPZ_NAME = {"hdd30_jul_aug": "hdd30sine_jul_aug", "hdd30tx_jul_aug": "hdd30_jul_aug"}


def npz_key(name):
    return _NPZ_NAME.get(name, name)


# Analogs use the Tmax-excess heat feature (the sine index is only computed for tile cells, not CONUS).
ANALOG_FEATURES = ["gdd_may_sep", "hdd30tx_jul_aug", "prcp_amj", "prcp_jja"]
TILE_VARS = ["gdd_may_sep", "hdd30_jul_aug", "hdd30tx_jul_aug", "days_tmax_gt30_jul_aug", "prcp_amj", "prcp_jja",
             "tmax_jul"]
VAR_META = {
    "gdd_may_sep": ("degC-days", "May-Sep growing degree days, base 10C, Tx and Tn clipped to [10,30]C (86/50 method)"),
    "hdd30_jul_aug": ("degC-days", "Jul-Aug single-sine degree-days above 30C from Tn/Tx (same definition as "
                                   "conf_weather.py / data/weather_annual.parquet hdd30_jul_aug)"),
    "hdd30tx_jul_aug": ("degC-days", "Jul-Aug sum of max(Tx-30C, 0) (Tmax-excess; about 4x the sine value). "
                                     "Used as the heat feature for analogs."),
    "days_tmax_gt30_jul_aug": ("days", "Jul-Aug count of days with Tx > 30C"),
    "prcp_amj": ("mm", "Apr-Jun precipitation total"),
    "prcp_jja": ("mm", "Jun-Aug precipitation total"),
    "tmax_jul": ("degC", "Mean July daily maximum temperature"),
}


# ---------------------------------------------------------------- catalog / file names
_cat_cache = {}


def catalog_files(model, scen, var):
    key = (model, scen, var)
    if key in _cat_cache:
        return _cat_cache[key]
    cache = RAW / "catalog" / f"{model}_{scen}_{var}.txt"
    cache.parent.mkdir(exist_ok=True)
    if cache.exists():
        names = cache.read_text().split()
    else:
        url = f"{CAT_BASE}/{model}/{scen}/{VARIANT}/{var}/catalog.xml"
        txt = http_get(url).text
        names = sorted(set(re.findall(rf'name="({var}_day_{re.escape(model)}_{scen}_{VARIANT}_\w+?_\d{{4}}(?:_v[\d.]+)?\.nc)"', txt)))
        cache.write_text("\n".join(names))
    by_year = {}
    for nm in names:
        m = re.search(r"_(\d{4})(?:_v([\d.]+))?\.nc$", nm)
        yr, ver = int(m.group(1)), m.group(2) or "0"
        vt = tuple(int(x) for x in ver.split("."))
        if yr not in by_year or vt > by_year[yr][1]:
            by_year[yr] = (nm, vt)
    _cat_cache[key] = {y: v[0] for y, v in by_year.items()}
    return _cat_cache[key]


def http_get(url, params=None, tries=5, timeout=300):
    last = None
    for k in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code == 404:
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(3 * (k + 1))
    raise last


# ---------------------------------------------------------------- fetch (NCSS primary, PC fallback)
def cache_path(model, scen, var, year, region):
    return NCSS_DIR / model / scen / f"{var}_{region}_{year}.nc"


def fetch_ncss(model, scen, var, year, region):
    path = cache_path(model, scen, var, year, region)
    if path.exists() and path.stat().st_size > 1000:
        return path, "cache"
    path.parent.mkdir(parents=True, exist_ok=True)
    (m0, d0), (m1, d1), _ = WINDOW[var]
    bx = CONUS_BOX if region == "conus" else TILE_BOX
    try:
        fname = catalog_files(model, scen, var)[year]
        url = f"{NCSS_BASE}/{model}/{scen}/{VARIANT}/{var}/{fname}"
        params = dict(var=var, north=bx["north"], south=bx["south"], west=bx["west"], east=bx["east"], horizStride=1,
                      time_start=f"{year}-{m0:02d}-{d0:02d}T00:00:00Z", time_end=f"{year}-{m1:02d}-{d1:02d}T23:59:59Z",
                      accept="netcdf4")
        r = http_get(url, params=params)
        if not r.content.startswith(b"\x89HDF"):
            raise RuntimeError("NCSS response is not netCDF4/HDF5")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.rename(path)
        (path.parent / (path.name + ".src")).write_text(f"nccs-ncss {fname}")
        return path, "nccs"
    except Exception as e:  # noqa: BLE001
        print(f"  NCSS failed {model} {scen} {var} {year}: {e}; trying Planetary Computer", flush=True)
        read_pc(model, scen, var, year, bx, path)
        return path, "pc"


_pc_client = None


def pc_href(model, scen, var, year):
    global _pc_client
    import planetary_computer
    import pystac_client
    if _pc_client is None:
        _pc_client = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                               modifier=planetary_computer.sign_inplace)
    it = next(_pc_client.search(collections=["nasa-nex-gddp-cmip6"], query={
        "cmip6:model": {"eq": model}, "cmip6:scenario": {"eq": scen}, "cmip6:year": {"eq": year}}).items())
    return it.assets[var].href


def read_pc(model, scen, var, year, bx, out_path):
    """Read only the needed daily chunks from the PC NetCDF via HTTP ranges, subset the box, write a small netCDF."""
    import cftime
    import fsspec
    import h5py
    href = pc_href(model, scen, var, year)
    (m0, d0), (m1, d1), _ = WINDOW[var]
    with fsspec.filesystem("https").open(href, block_size=2 ** 20) as f:
        h = h5py.File(f, "r")
        ds = h[var]
        tv = h["time"][:]
        units = h["time"].attrs["units"].decode()
        cal = h["time"].attrs["calendar"].decode()
        lat = h["lat"][:]
        lon = h["lon"][:]
        dates = cftime.num2date(tv, units, calendar=cal)
        sel = [i for i, t in enumerate(dates) if (t.month, t.day) >= (m0, d0) and (t.month, t.day) <= (m1, d1)]
        infos = [ds.id.get_chunk_info_by_coord((i, 0, 0)) for i in sel]
        shuffle, fill = ds.shuffle, float(ds.fillvalue)
        shape = ds.chunks[1:]
    iy = np.where((lat >= bx["south"]) & (lat <= bx["north"]))[0]
    ix = np.where((lon >= bx["west"]) & (lon <= bx["east"]))[0]

    def get(info):
        a, n = info.byte_offset, info.size
        for k in range(5):
            try:
                r = requests.get(href, headers={**UA, "Range": f"bytes={a}-{a + n - 1}"}, timeout=120)
                if r.status_code in (200, 206) and len(r.content) == n:
                    return r.content
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2 * (k + 1))
        raise RuntimeError("PC range read failed")

    with ThreadPoolExecutor(8) as ex:
        raws = list(ex.map(get, infos))
    arr = np.empty((len(sel), len(iy), len(ix)), np.float32)
    for k, raw in enumerate(raws):
        b = np.frombuffer(zlib.decompress(raw), np.uint8)
        if shuffle:
            b = b.reshape(4, -1).T.ravel()
        a = b.view("<f4").reshape(shape)
        arr[k] = a[iy[0]:iy[-1] + 1, ix[0]:ix[-1] + 1]
    arr[arr > 1e19] = np.nan
    out = xr.Dataset({var: (("time", "lat", "lon"), arr)},
                     coords={"time": ("time", tv[sel], {"units": units, "calendar": cal}), "lat": lat[iy], "lon": lon[ix]})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_netcdf(out_path, engine="h5netcdf")
    (out_path.parent / (out_path.name + ".src")).write_text(f"planetary-computer {href.split('?')[0]}")


# ---------------------------------------------------------------- indices
def open_var(path, var):
    ds = xr.open_dataset(path, engine="h5netcdf", decode_times=xr.coders.CFDatetimeCoder(use_cftime=True))
    da = ds[var].load()
    da = da.where(da < 1e19)
    mon = np.array([t.month for t in da.time.values])
    return da, mon


def sine_dd_above(tmin, tmax, thr):
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


def cell_indices(tx, mtx, tn, mtn, pr, mpr, sine=False):
    """Inputs as numpy (time, lat, lon) in degC / mm/day. Returns dict of 2-D (lat, lon) arrays."""
    for a, m, n in ((tx, mtx, 153), (tn, mtn, 153), (pr, mpr, 153)):
        if a.shape[0] != n:
            raise ValueError(f"expected {n} days, got {a.shape[0]}")
    gx = np.clip(tx, 10, 30)
    gn = np.clip(tn, 10, 30)
    gdd = ((gx + gn) / 2 - 10).sum(0)
    ja = np.isin(mtx, [7, 8])
    out = dict(
        gdd_may_sep=gdd,
        hdd30_jul_aug=np.maximum(tx[ja] - 30, 0).sum(0),
        days_tmax_gt30_jul_aug=(tx[ja] > 30).sum(0).astype(float),
        prcp_amj=pr[np.isin(mpr, [4, 5, 6])].sum(0),
        prcp_jja=pr[np.isin(mpr, [6, 7, 8])].sum(0),
        tmax_jul=tx[mtx == 7].mean(0),
    )
    if sine:
        jan = np.isin(mtn, [7, 8])
        out["hdd30sine_jul_aug"] = sine_dd_above(tn[jan], tx[ja], 30.0).sum(0)
    bad = np.isnan(tx).any(0) | np.isnan(tn).any(0) | np.isnan(pr).any(0)
    for k in out:
        out[k] = np.where(bad, np.nan, out[k])
    return out


def tile_mask(lat, lon):
    lon180 = np.where(lon > 180, lon - 360, lon)
    my = (lat >= TS) & (lat <= TN)
    mx = (lon180 >= TW) & (lon180 <= TE)
    return my, mx


def process_year(model, scen, year):
    """Fetch the three variables and compute indices; caches result as .npz."""
    out = IDX_DIR / f"{model}_{scen}_{year}.npz"
    if out.exists():
        z = np.load(out, allow_pickle=True)
        return {k: z[k] for k in z.files}
    region = "conus" if scen == "historical" else "tile"
    srcs = {}
    arrs = {}
    for v in VARS:
        p, s = fetch_ncss(model, scen, v, year, region)
        srcs[v] = (p.parent / (p.name + ".src")).read_text() if (p.parent / (p.name + ".src")).exists() else s
        da, mon = open_var(p, v)
        arrs[v] = (da, mon)
    tx, mtx = arrs["tasmax"]
    tn, mtn = arrs["tasmin"]
    pr, mpr = arrs["pr"]
    lat, lon = tx.lat.values, tx.lon.values
    for d in (tn, pr):
        assert np.allclose(d.lat.values, lat) and np.allclose(d.lon.values, lon)
    my, mx = tile_mask(lat, lon)
    sub = lambda a: a.values[:, my][:, :, mx]  # noqa: E731
    t = cell_indices(sub(tx) - 273.15, mtx, sub(tn) - 273.15, mtn, sub(pr) * 86400.0, mpr, sine=True)
    res = {f"tile_{k}": np.array(np.nanmean(v)) for k, v in t.items()}
    res["tile_ncells"] = np.array(int(np.isfinite(t["gdd_may_sep"]).sum()))
    res["tile_lat"] = lat[my]
    res["tile_lon"] = np.where(lon[mx] > 180, lon[mx] - 360, lon[mx])
    if region == "conus":
        c = cell_indices(tx.values - 273.15, mtx, tn.values - 273.15, mtn, pr.values * 86400.0, mpr)
        for k in ANALOG_FEATURES:
            res[f"conus_{npz_key(k)}"] = c[npz_key(k)].astype(np.float32)
        res["conus_lat"] = lat
        res["conus_lon"] = np.where(lon > 180, lon - 360, lon)
    res["sources"] = np.array(json.dumps(srcs))
    np.savez_compressed(out, **res)
    return res


# ---------------------------------------------------------------- analogs
def conus_cell_lookup(lat, lon):
    """Map grid cell centres to lower-48 county/state using the Census county polygons."""
    import geopandas as gpd
    sys.path.insert(0, str(ROOT / "pipeline"))
    from context_counties import load_us_counties
    cty = load_us_counties()
    cty = cty[~cty.STUSPS.isin(["AK", "HI", "PR", "VI", "GU", "MP", "AS"])]
    LO, LA = np.meshgrid(lon, lat)
    pts = gpd.GeoDataFrame({"iy": np.repeat(np.arange(len(lat)), len(lon)), "ix": np.tile(np.arange(len(lon)), len(lat))},
                           geometry=gpd.points_from_xy(LO.ravel(), LA.ravel()), crs=4326)
    j = gpd.sjoin(pts, cty[["GEOID", "NAME", "STUSPS", "STATE_NAME", "geometry"]], how="inner", predicate="within")
    j = j.drop_duplicates(["iy", "ix"])
    return j[["iy", "ix", "GEOID", "NAME", "STUSPS", "STATE_NAME"]].reset_index(drop=True)


def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl, dp = np.radians(lon2 - lon1), p2 - p1
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def bearing_word(lon1, lat1, lon2, lat2):
    y = np.sin(np.radians(lon2 - lon1)) * np.cos(np.radians(lat2))
    x = np.cos(np.radians(lat1)) * np.sin(np.radians(lat2)) - np.sin(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.cos(np.radians(lon2 - lon1))
    b = (np.degrees(np.arctan2(y, x)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((b + 22.5) % 360) // 45)], float(b)


def r(x, nd=2):
    if x is None:
        return None
    x = float(x)
    return None if not np.isfinite(x) else round(x, nd)


# ---------------------------------------------------------------- main
def main():
    jobs = [(m, s, y) for m in MODELS for s, ys in SCEN_YEARS.items() for y in ys]
    # warm catalogs serially (27 small requests)
    for m in MODELS:
        for s in SCEN_YEARS:
            for v in VARS:
                files = catalog_files(m, s, v)
                missing = [y for y in SCEN_YEARS[s] if y not in files]
                if missing:
                    print(f"catalog {m} {s} {v}: missing years {missing} (PC fallback will be tried)")
    results, failures = {}, {}
    t0 = time.time()
    with ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(process_year, *j): j for j in jobs}
        for k, f in enumerate(as_completed(futs), 1):
            j = futs[f]
            try:
                results[j] = f.result()
            except Exception as e:  # noqa: BLE001
                failures[j] = repr(e)
                print("FAILED", j, e, flush=True)
            if k % 20 == 0:
                print(f"{k}/{len(jobs)} model-years done ({time.time() - t0:.0f}s)", flush=True)
    print(f"all model-years: {len(results)} ok, {len(failures)} failed")

    # ---------------- per-year tile arrays
    per_year = {}
    src_count = {}
    for m in MODELS:
        per_year[m] = {}
        for s, ys in SCEN_YEARS.items():
            d = {"years": ys}
            for v in TILE_VARS:
                d[v] = [r(results[(m, s, y)][f"tile_{npz_key(v)}"]) if (m, s, y) in results else None for y in ys]
            per_year[m][s] = d
            for y in ys:
                if (m, s, y) in results:
                    for v, src in json.loads(str(results[(m, s, y)]["sources"])).items():
                        key = src.split()[0]
                        src_count[key] = src_count.get(key, 0) + 1
    any_res = next(iter(results.values()))
    tile_cells = [[r(lo, 3), r(la, 3)] for la in any_res["tile_lat"] for lo in any_res["tile_lon"]]

    # ---------------- summaries
    summary = {}
    for s in SCEN_YEARS:
        summary[s] = {}
        for v in TILE_VARS:
            pm = {m: np.nanmean([x for x in per_year[m][s][v] if x is not None]) for m in MODELS}
            pooled = np.array([x for m in MODELS for x in per_year[m][s][v] if x is not None], float)
            e = dict(mmm_mean=r(np.mean(list(pm.values()))), per_model_mean={m: r(x) for m, x in pm.items()},
                     pooled_p10=r(np.percentile(pooled, 10)), pooled_p50=r(np.percentile(pooled, 50)),
                     pooled_p90=r(np.percentile(pooled, 90)), pooled_sd=r(np.std(pooled, ddof=1)), n_model_years=int(len(pooled)))
            if s != "historical":
                hpm = {m: np.nanmean([x for x in per_year[m]["historical"][v] if x is not None]) for m in MODELS}
                dpm = {m: pm[m] - hpm[m] for m in MODELS}
                e["delta_vs_hist_mmm"] = r(np.mean(list(dpm.values())))
                e["delta_vs_hist_per_model"] = {m: r(x) for m, x in dpm.items()}
                e["delta_vs_hist_range"] = [r(min(dpm.values())), r(max(dpm.values()))]
            summary[s][v] = e

    # ---------------- analogs
    hist_keys = [(m, "historical", y) for m in MODELS for y in SCEN_YEARS["historical"] if (m, "historical", y) in results]
    lat = results[hist_keys[0]]["conus_lat"]
    lon = results[hist_keys[0]]["conus_lon"]
    clim = {}  # model -> feature -> 2-D mean
    for m in MODELS:
        ks = [k for k in hist_keys if k[0] == m]
        clim[m] = {f: np.nanmean(np.stack([results[k][f"conus_{npz_key(f)}"] for k in ks]), 0) for f in ANALOG_FEATURES}
    mmm = {f: np.mean(np.stack([clim[m][f] for m in MODELS]), 0) for f in ANALOG_FEATURES}
    target_pm = {m: {f: np.nanmean([x for x in per_year[m]["ssp245"][f] if x is not None]) for f in ANALOG_FEATURES} for m in MODELS}
    target = {f: np.mean([target_pm[m][f] for m in MODELS]) for f in ANALOG_FEATURES}
    tile_hist = {f: summary["historical"][f]["mmm_mean"] for f in ANALOG_FEATURES}

    look = conus_cell_lookup(lat, lon)
    iy, ix = look.iy.values, look.ix.values
    X = np.stack([mmm[f][iy, ix] for f in ANALOG_FEATURES], 1)
    ok = np.isfinite(X).all(1)
    look, X, iy, ix = look[ok].reset_index(drop=True), X[ok], iy[ok], ix[ok]
    sd = X.std(0, ddof=1)
    tvec = np.array([target[f] for f in ANALOG_FEATURES])
    dist = np.sqrt((((X - tvec) / sd) ** 2).sum(1))
    # robustness: per-model distance (model's own historical cells vs model's own ssp245 tile mean)
    dist_pm = {}
    for m in MODELS:
        Xm = np.stack([clim[m][f][iy, ix] for f in ANALOG_FEATURES], 1)
        tm = np.array([target_pm[m][f] for f in ANALOG_FEATURES])
        dist_pm[m] = np.sqrt((((Xm - tm) / sd) ** 2).sum(1))
    order = np.argsort(dist)
    top = order[:25]
    tile_lon_c, tile_lat_c = (TW + TE) / 2, (TS + TN) / 2
    cells = []
    for rank, i in enumerate(top, 1):
        lo, la = float(lon[ix[i]]), float(lat[iy[i]])
        bw, bdeg = bearing_word(tile_lon_c, tile_lat_c, lo, la)
        cells.append(dict(
            rank=rank, lon=r(lo, 3), lat=r(la, 3), state=look.STATE_NAME[i], state_abbr=look.STUSPS[i],
            county_fips=look.GEOID[i], county_name=look.NAME[i], label=f"{look.NAME[i]} County, {look.STUSPS[i]}",
            distance=r(dist[i], 3),
            distance_per_model={m: r(dist_pm[m][i], 3) for m in MODELS},
            rank_per_model={m: int((dist_pm[m] < dist_pm[m][i]).sum() + 1) for m in MODELS},
            km_from_tile=r(haversine_km(tile_lon_c, tile_lat_c, lo, la), 0), direction_from_tile=bw, bearing_deg=r(bdeg, 0),
            hist_climate_1995_2014={f: r(mmm[f][iy[i], ix[i]], 1) for f in ANALOG_FEATURES},
        ))
    # distance of the tile's own historical climate to the target, and its rank among CONUS cells
    th = np.array([tile_hist[f] for f in ANALOG_FEATURES])
    d_tile = float(np.sqrt((((th - tvec) / sd) ** 2).sum()))
    per_model_top = {m: set(np.argsort(dist_pm[m])[:25].tolist()) for m in MODELS}
    w = np.array([1.0 / max(c["distance"], 1e-6) for c in cells])
    clon = float(np.sum(w * [c["lon"] for c in cells]) / w.sum())
    clat = float(np.sum(w * [c["lat"] for c in cells]) / w.sum())
    bw, bdeg = bearing_word(tile_lon_c, tile_lat_c, clon, clat)
    states = {}
    for c in cells:
        states[c["state_abbr"]] = states.get(c["state_abbr"], 0) + 1

    def top_block(dvec, k=25, n_show=5):
        o = np.argsort(dvec)[:k]
        ww = 1.0 / np.maximum(dvec[o], 1e-6)
        los, las = lon[ix[o]], lat[iy[o]]
        cl, ca = float(np.sum(ww * los) / ww.sum()), float(np.sum(ww * las) / ww.sum())
        b_w, b_d = bearing_word(tile_lon_c, tile_lat_c, cl, ca)
        sc = {}
        for i in o:
            sc[look.STUSPS[i]] = sc.get(look.STUSPS[i], 0) + 1
        return dict(
            weighted_centroid=dict(lon=r(cl, 3), lat=r(ca, 3), km_from_tile=r(haversine_km(tile_lon_c, tile_lat_c, cl, ca), 0),
                                   direction_from_tile=b_w, bearing_deg=r(b_d, 0)),
            state_counts=dict(sorted(sc.items(), key=lambda kv: -kv[1])),
            top=[dict(lon=r(lon[ix[i]], 3), lat=r(lat[iy[i]], 3), label=f"{look.NAME[i]} County, {look.STUSPS[i]}",
                      state=look.STATE_NAME[i], distance=r(dvec[i], 3)) for i in o[:n_show]],
        )

    per_model_analogs = {m: top_block(dist_pm[m]) for m in MODELS}
    # sensitivity: scale features by the tile's pooled interannual SD (historical, 60 model-years) instead of CONUS spatial SD
    sd_ia = np.array([summary["historical"][f]["pooled_sd"] for f in ANALOG_FEATURES])
    dist_ia = np.sqrt((((X - tvec) / sd_ia) ** 2).sum(1))
    sens_ia = top_block(dist_ia)
    sens_ia["scale_sd"] = {f: r(s_, 2) for f, s_ in zip(ANALOG_FEATURES, sd_ia)}
    sens_ia["top25_overlap_with_main"] = len(set(np.argsort(dist_ia)[:25].tolist()) & set(top.tolist()))

    analogs = dict(
        method=("Candidate climate = per-cell 1995-2014 mean of each GCM's historical run, averaged over the 3 GCMs "
                "(lower-48 land cells, 0.25 deg, all 20 years). Target = tile-mean 2035-2055 SSP2-4.5 climate, "
                "multi-model mean. Distance = standardised Euclidean over the features, each scaled by its "
                "spatial SD across all CONUS candidate cells. Per-model distances use each GCM's own historical cells "
                "vs its own SSP2-4.5 tile mean (same scaling)."),
        features=ANALOG_FEATURES, scenario="ssp245", target_period=[2035, 2055], candidate_period=[1995, 2014],
        target={f: r(target[f], 1) for f in ANALOG_FEATURES},
        target_per_model={m: {f: r(target_pm[m][f], 1) for f in ANALOG_FEATURES} for m in MODELS},
        tile_hist_1995_2014={f: r(tile_hist[f], 1) for f in ANALOG_FEATURES},
        scale_sd={f: r(s_, 2) for f, s_ in zip(ANALOG_FEATURES, sd)},
        n_candidate_cells=int(len(dist)),
        tile_own_hist_distance=r(d_tile, 3),
        tile_own_hist_rank=int((dist < d_tile).sum() + 1),
        distance_percentiles_all_cells={p: r(np.percentile(dist, p), 3) for p in (1, 5, 50)},
        per_model_top25_overlap_with_mmm={m: len(per_model_top[m] & set(top.tolist())) for m in MODELS},
        weighted_centroid=dict(lon=r(clon, 3), lat=r(clat, 3), km_from_tile=r(haversine_km(tile_lon_c, tile_lat_c, clon, clat), 0),
                               direction_from_tile=bw, bearing_deg=r(bdeg, 0)),
        state_counts=dict(sorted(states.items(), key=lambda kv: -kv[1])),
        per_model=per_model_analogs,
        sensitivity_interannual_scaling=sens_ia,
        cells=cells,
    )
    # flat list in the shape of the web contract's climate.json analogs:[{lon,lat,state,label,distance}]
    analogs_list = [dict(lon=c["lon"], lat=c["lat"], state=c["state_abbr"], label=c["label"], distance=c["distance"])
                    for c in cells]

    # cross-check against NASA POWER tile climatology from the conf module (if present); recommends delta method
    power_cmp = None
    wpath = ROOT / "data" / "weather_annual.parquet"
    if wpath.exists():
        import pandas as pd
        w = pd.read_parquet(wpath)
        w = w[w.year.between(1995, 2014)]
        pairs = {"gdd_may_sep": "gdd_may_sep", "hdd30_jul_aug": "hdd30_jul_aug",
                 "days_tmax_gt30_jul_aug": "days_tmax30_jul_aug", "prcp_amj": "prcp_amj", "prcp_jja": "prcp_jja",
                 "tmax_jul": "tmax_jul"}
        power_cmp = {"period": [1995, 2014], "note": ("POWER values = mean over POWER cells and years from "
                     "data/weather_annual.parquet. NEX-GDDP is bias-corrected to GMFD, POWER is MERRA-2 based, so absolute "
                     "levels differ; apply NEX-GDDP deltas (future minus NEX historical) to POWER baselines rather than "
                     "mixing absolute values."), "variables": {}}
        for nv, pv in pairs.items():
            if pv in w:
                pm_ = float(w[pv].mean())
                power_cmp["variables"][nv] = dict(nex_hist_mmm=summary["historical"][nv]["mmm_mean"], power=r(pm_),
                                                  power_column=pv, diff_nex_minus_power=r(summary["historical"][nv]["mmm_mean"] - pm_))

    pc_check = None
    if "--pc-check" in sys.argv or (RAW / "pc_check" / "MRI-ESM2-0_historical_tasmax_2000.nc").exists():
        pc_check = compare_sources()  # reads the cached PC file; network only if the cache is missing

    out = dict(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        dataset="NASA NEX-GDDP-CMIP6 (daily, 0.25 deg, bias-corrected and statistically downscaled CMIP6)",
        sources=dict(
            primary="NASA NCCS THREDDS NetCDF Subset Service, https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6/catalog.html (latest file version per year, v2.0 where available)",
            fallback="Microsoft Planetary Computer collection nasa-nex-gddp-cmip6 (per-file automatic fallback)",
            files_by_source=src_count,
            pc_vs_nccs_check=pc_check,
        ),
        region=dict(name=REGION["name"], tile_bounds_lonlat=REGION["tile_bounds_lonlat"],
                    cell_rule="0.25 deg cells whose centres fall inside tile_bounds_lonlat; indices computed per cell then averaged",
                    tile_cells_lonlat=tile_cells),
        models=MODELS, variant=VARIANT, scenarios=list(SCEN_YEARS),
        periods={"historical": [1995, 2014], "ssp245": [2035, 2055], "ssp585": [2035, 2055]},
        variables={k: {"units": u, "definition": dfn} for k, (u, dfn) in VAR_META.items()},
        per_year=per_year,
        summary=summary,
        analogs=analogs,
        analogs_list=analogs_list,
        power_comparison=power_cmp,
        failures={f"{m}|{s}|{y}": e for (m, s, y), e in failures.items()},
        notes=[
            "Per-year values are tile means of per-cell indices (20 cells).",
            "Each GCM is one realisation (r1i1p1f1); spread across 3 GCMs understates full CMIP6 uncertainty.",
            "NEX-GDDP-CMIP6 is bias-corrected to GMFD observations over 1960-2014, so historical climatologies are similar across models by construction.",
            ("Historical per_year 'years' (1995-2014) are free-running GCM model-years, NOT observed years: only their "
             "distribution matches reality, not the year-to-year sequence (e.g. no model reproduces the real 2012 "
             "drought in its '2012'). Never join them with observed-year data (POWER, NASS, HLS); use the historical "
             "series only as a distribution / climatology. The same holds for future years."),
            ("hdd30_jul_aug uses the single-sine method and matches data/weather_annual.parquet hdd30_jul_aug (POWER). "
             "hdd30tx_jul_aug is the Tmax-excess sum, about 4x larger; never mix the two. Analog distances use hdd30tx_jul_aug."),
            "analogs_list is the analogs.cells top 25 flattened to {lon,lat,state,label,distance} (state = 2-letter abbreviation).",
        ],
    )
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, f"{OUT.stat().st_size / 1e3:.0f} kB")
    for s in SCEN_YEARS:
        print(s, {v: summary[s][v]["mmm_mean"] for v in TILE_VARS})
    print("analog target", analogs["target"], "tile hist", analogs["tile_hist_1995_2014"])
    for c in cells[:10]:
        print(c["rank"], c["label"], c["lon"], c["lat"], c["distance"], c["km_from_tile"], c["direction_from_tile"])
    print("state counts", analogs["state_counts"], "overlap", analogs["per_model_top25_overlap_with_mmm"])
    for m in MODELS:
        print(m, per_model_analogs[m]["weighted_centroid"], per_model_analogs[m]["state_counts"])
    print("interannual-scaled:", sens_ia["weighted_centroid"], sens_ia["state_counts"], "overlap", sens_ia["top25_overlap_with_main"])


def compare_sources(model="MRI-ESM2-0", scen="historical", year=2000, var="tasmax"):
    """Tile-mean daily series from NCCS (v2.0) vs Planetary Computer for one variable-year."""
    p_nccs = cache_path(model, scen, var, year, "conus")
    if not p_nccs.exists():
        fetch_ncss(model, scen, var, year, "conus")
    p_pc = RAW / "pc_check" / f"{model}_{scen}_{var}_{year}.nc"
    if not p_pc.exists():
        read_pc(model, scen, var, year, TILE_BOX, p_pc)
    a, _ = open_var(p_nccs, var)
    b, _ = open_var(p_pc, var)
    my, mx = tile_mask(a.lat.values, a.lon.values)
    sa = a.values[:, my][:, :, mx].mean((1, 2))
    my, mx = tile_mask(b.lat.values, b.lon.values)
    sb = b.values[:, my][:, :, mx].mean((1, 2))
    d = sa - sb
    res = dict(model=model, scenario=scen, year=year, variable=var, n_days=int(len(d)),
               mean_abs_diff=r(np.abs(d).mean(), 4), max_abs_diff=r(np.abs(d).max(), 4),
               mean_nccs=r(sa.mean(), 3), mean_pc=r(sb.mean(), 3),
               pc_file=(p_pc.parent / (p_pc.name + ".src")).read_text())
    print("PC vs NCCS:", res)
    return res


if __name__ == "__main__":
    main()
