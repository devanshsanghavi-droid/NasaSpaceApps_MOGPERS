"""NASA NEX-GDDP-CMIP6 (0.25 deg, bias-corrected/downscaled daily CMIP6) climate shift for the Water Clock region.

Access: NASA NCCS THREDDS NetCDF Subset Service (server-side bbox/time subset), one request per model/scenario/var/year:
  https://ds.nccs.nasa.gov/thredds/ncss/grid/AMES/NEX/GDDP-CMIP6/<model>/<scen>/r1i1p1f1/<var>/<file>?var=<var>
      &north=40.1&south=36.9&west=257.9&east=260.5&time_start=YYYY-04-01&time_end=YYYY-09-30&accept=netcdf4
  (file names from the THREDDS catalog.xml; latest version per year, v2.0 where present). Raw subsets are cached in
  data/raw/cmip6/<model>/<scen>/<var>_<year>.nc.  Planetary Computer (nasagddp blob) holds the same files but its
  NetCDF chunking is one global day per chunk, so the NCSS route is far cheaper; it is used here as the only route.
Window: Apr 1 - Sep 30 of every year (growing season; no February => same day count in all model calendars).
Periods: historical 1995-2014 vs ssp245 / ssp585 2035-2055 (21 yrs centred on 2045).
Region: all 0.25 deg cells whose centres fall inside the 26 region county polygons (nasa_common.region_counties);
per-day values computed per cell, season totals per cell, then the region mean.

Per model / scenario / year: pr_gs_in (Apr-Sep precip, in), tasmax_jja_f (mean JJA daily max, F),
  et0_pm_gs_in (FAO-56 Penman-Monteith, Apr-Sep, in) when hurs, rsds and sfcWind exist, et0_hg_gs_in (Hargreaves-Samani
  1985: 0.0023 Ra (T+17.8) sqrt(Tmax-Tmin) * 0.408, Apr-Sep, in) always.
PM inputs: ea = hurs/100 * (e0(Tmax)+e0(Tmin))/2 (FAO-56 eq. 19 with mean RH); Rs = rsds * 0.0864 (W m-2 -> MJ m-2 d-1);
  u2 = sfcWind * 4.87/ln(67.8*10-5.42) (FAO-56 eq. 47, 10 m -> 2 m); P from z = 900 m (eq. 7; region elevations
  ~650-1200 m change gamma by < +-7%, which mostly cancels in the change ratio); Rso = (0.75+2e-5 z) Ra.
Output: data/processed/cmip6_2045.json.
Re-run: python3 pipeline/nasa_cmip6.py   (env MODELS="ACCESS-CM2,GFDL-ESM4,MRI-ESM2-0", WORKERS=4)
"""
import json
import os
import re
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nasa_common import PROC, RAW, http_get, region_counties  # noqa: E402

warnings.filterwarnings("ignore", message="Mean of empty slice")
D = RAW / "cmip6"
THREDDS = "https://ds.nccs.nasa.gov/thredds"
NCSS = f"{THREDDS}/ncss/grid/AMES/NEX/GDDP-CMIP6"
CAT = f"{THREDDS}/catalog/AMES/NEX/GDDP-CMIP6"
VARIANT = "r1i1p1f1"
MODELS = os.environ.get("MODELS", "ACCESS-CM2,GFDL-ESM4,MRI-ESM2-0").split(",")
WORKERS = int(os.environ.get("WORKERS", "4"))
VARS = ["pr", "tasmax", "tasmin", "hurs", "rsds", "sfcWind"]
PERIODS = {"historical": range(1995, 2015), "ssp245": range(2035, 2056), "ssp585": range(2035, 2056)}
BOX = dict(north=40.1, south=36.9, west=257.9, east=260.5)
Z_M = 900.0
_cat = {}


def catalog(model, scen, var):
    k = (model, scen, var)
    if k in _cat:
        return _cat[k]
    f = D / "catalog" / f"{model}_{scen}_{var}.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.exists() and f.stat().st_size > 0:
        names = f.read_text().split()
    else:
        try:
            txt = http_get(f"{CAT}/{model}/{scen}/{VARIANT}/{var}/catalog.xml").text
        except Exception as e:  # noqa: BLE001
            print("catalog fail", model, scen, var, e, flush=True)
            txt = ""
        names = sorted(set(re.findall(rf'name="({var}_day_{re.escape(model)}_{scen}_{VARIANT}_\w+?_\d{{4}}(?:_v[\d.]+)?\.nc)"', txt)))
        if names:  # never cache an empty listing (transient catalog failures)
            f.write_text("\n".join(names))
    by = {}
    for nm in names:
        m = re.search(r"_(\d{4})(?:_v([\d.]+))?\.nc$", nm)
        y, v = int(m.group(1)), tuple(int(x) for x in (m.group(2) or "0").split("."))
        if y not in by or v > by[y][1]:
            by[y] = (nm, v)
    _cat[k] = {y: v[0] for y, v in by.items()}
    return _cat[k]


def fetch(job):
    model, scen, var, year = job
    p = D / model / scen / f"{var}_{year}.nc"
    if p.exists() and p.stat().st_size > 1000:
        return job, "cache"
    files = catalog(model, scen, var)
    if year not in files:
        return job, "missing"
    p.parent.mkdir(parents=True, exist_ok=True)
    params = dict(var=var, horizStride=1, accept="netcdf4", time_start=f"{year}-04-01T00:00:00Z",
                  time_end=f"{year}-09-30T23:59:59Z", **BOX)
    try:
        r = http_get(f"{NCSS}/{model}/{scen}/{VARIANT}/{var}/{files[year]}", params=params, timeout=300)
        if not r.content.startswith(b"\x89HDF"):
            raise RuntimeError("not netCDF4")
        tmp = p.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.rename(p)
        return job, "ok"
    except Exception as e:  # noqa: BLE001
        return job, f"FAIL {e!r}"[:300]


def e0(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def ra_mj(lat_deg, doy):
    phi = np.deg2rad(lat_deg)[None, :, None]
    doy = doy[:, None, None]
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))
    return 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws))


def load(model, scen, var, year):
    import xarray as xr
    p = D / model / scen / f"{var}_{year}.nc"
    if not p.exists():
        return None
    with xr.open_dataset(p, decode_times=xr.coders.CFDatetimeCoder(use_cftime=True)) as ds:
        a = ds[var].values.astype(np.float64)
        a[a > 1e19] = np.nan
        t = ds.time.values
        return a, ds.lat.values, ds.lon.values, np.array([x.month for x in t]), np.array([x.dayofyr for x in t])


def year_stats(model, scen, year, mask):
    out = {}
    tx = load(model, scen, "tasmax", year)
    tn = load(model, scen, "tasmin", year)
    pr = load(model, scen, "pr", year)
    if tx is None or tn is None or pr is None:
        return None
    lat = tx[1]
    mon, doy = tx[3], tx[4]
    Tx, Tn = tx[0] - 273.15, tn[0] - 273.15
    P = pr[0] * 86400.0  # kg m-2 s-1 -> mm/day
    ra = ra_mj(lat, doy)
    T = (Tx + Tn) / 2
    hg = 0.0023 * 0.408 * ra * (T + 17.8) * np.sqrt(np.maximum(Tx - Tn, 0))
    cell = lambda a: float(np.nanmean(a[mask]))  # noqa: E731
    out["pr_gs_in"] = cell(P.sum(0)) / 25.4
    out["tasmax_jja_f"] = cell(Tx[(mon >= 6) & (mon <= 8)].mean(0)) * 9 / 5 + 32
    out["et0_hg_gs_in"] = cell(hg.sum(0)) / 25.4
    hu, rs, ws = (load(model, scen, v, year) for v in ("hurs", "rsds", "sfcWind"))
    if hu is not None and rs is not None and ws is not None:
        es = (e0(Tx) + e0(Tn)) / 2
        ea = np.clip(hu[0], 0, 100) / 100 * es
        Rs = rs[0] * 0.0864
        u2 = ws[0] * 4.87 / np.log(67.8 * 10 - 5.42)
        Pk = 101.3 * ((293 - 0.0065 * Z_M) / 293) ** 5.26
        gam = 0.000665 * Pk
        delta = 4098 * e0(T) / (T + 237.3) ** 2
        rso = (0.75 + 2e-5 * Z_M) * ra
        rnl = 4.903e-9 * ((Tx + 273.16) ** 4 + (Tn + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0))) * \
            (1.35 * np.clip(Rs / rso, 0.25, 1) - 0.35)
        rn = 0.77 * Rs - rnl
        pm = (0.408 * delta * rn + gam * 900 / (T + 273) * u2 * (es - ea)) / (delta + gam * (1 + 0.34 * u2))
        out["et0_pm_gs_in"] = cell(np.maximum(pm, 0).sum(0)) / 25.4
    return out


def main():
    jobs = [(m, s, v, y) for m in MODELS for s, yrs in PERIODS.items() for v in VARS for y in yrs]
    print(len(jobs), "jobs", flush=True)
    fails, t0 = [], time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        for i, (job, st) in enumerate(ex.map(fetch, jobs)):
            if st not in ("ok", "cache"):
                fails.append((job, st))
            if i % 50 == 0:
                print(i, job, st, f"{time.time() - t0:.0f}s", flush=True)
    (D / "fetch_failures.txt").write_text("\n".join(f"{j}\t{s}" for j, s in fails))
    print("fails", len(fails), flush=True)
    # region mask on the 0.25 deg grid
    from shapely import contains_xy
    probe = load(MODELS[0], "historical", "tasmax", 1995)
    lat, lon = probe[1], probe[2]
    LON, LAT = np.meshgrid(lon - 360, lat)
    mask = contains_xy(region_counties().geometry.union_all(), LON, LAT)
    rows = []
    for m in MODELS:
        for s, yrs in PERIODS.items():
            for y in yrs:
                st = year_stats(m, s, y, mask)
                if st:
                    rows.append(dict(model=m, scenario=s, year=y, **st))
    df = pd.DataFrame(rows)
    df.to_parquet(D / "cmip6_region_yearly.parquet", index=False)
    metrics = [c for c in ["pr_gs_in", "tasmax_jja_f", "et0_pm_gs_in", "et0_hg_gs_in"] if c in df]
    res = {"models": {}, "ensemble": {}}
    for m in MODELS:
        h = df[(df.model == m) & (df.scenario == "historical")]
        res["models"][m] = {"baseline_1995_2014": {k: round(float(h[k].mean()), 3) for k in metrics if h[k].notna().all()},
                            "n_years_hist": int(len(h))}
        for s in ("ssp245", "ssp585"):
            f = df[(df.model == m) & (df.scenario == s)]
            d = {"n_years": int(len(f))}
            for k in metrics:
                if h[k].notna().all() and len(f) and f[k].notna().all():
                    d[f"{k}_future"] = round(float(f[k].mean()), 3)
                    d[f"{k}_change"] = round(float(f[k].mean() - h[k].mean()), 3)
                    if k.startswith("et0") or k.startswith("pr"):
                        d[f"{k}_change_pct"] = round(float(100 * (f[k].mean() / h[k].mean() - 1)), 2)
            res["models"][m][s] = d
    for s in ("ssp245", "ssp585"):
        e = {}
        for key in sorted({k for m in MODELS for k in res["models"][m][s] if k.endswith("change") or k.endswith("pct")}):
            vals = [res["models"][m][s][key] for m in MODELS if key in res["models"][m][s]]
            e[key] = {"mean": round(float(np.mean(vals)), 3), "min": round(float(np.min(vals)), 3),
                      "max": round(float(np.max(vals)), 3), "n_models": len(vals)}
        res["ensemble"][s] = e
    # bias check of the downscaled baseline against NASA POWER over the same years/region (POWER = reanalysis)
    pw = PROC / "power_county_annual.parquet"
    if pw.exists():
        p = pd.read_parquet(pw)
        p = p[p.year.between(1995, 2014)].groupby("year")[["precip_gs_in", "et0_gs_in", "tmax_jja_f"]].mean().mean()
        res["power_1995_2014_region_mean"] = {k: round(float(v), 3) for k, v in p.items()}
    pref = "et0_pm_gs_in" if all("et0_pm_gs_in" in res["models"][m]["baseline_1995_2014"] for m in MODELS) else "et0_hg_gs_in"
    out = {
        "generated": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "source": "NASA NEX-GDDP-CMIP6 v1.x/v2.0 daily 0.25 deg, via NASA NCCS THREDDS NCSS "
                  "https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6/catalog.html",
        "variant": VARIANT, "models": MODELS, "scenarios": ["ssp245", "ssp585"],
        "baseline_period": [1995, 2014], "future_period": [2035, 2055],
        "region": "0.25 deg cells with centres inside the 26 GMD1/3/4 counties", "n_cells": int(mask.sum()),
        "season": "Apr 1 - Sep 30 (precip, ET0); Jun-Aug (tasmax)",
        "et0_preferred": pref,
        "units": {"pr_gs_in": "inches Apr-Sep", "tasmax_jja_f": "deg F (mean daily max Jun-Aug)",
                  "et0_pm_gs_in": "inches Apr-Sep, FAO-56 Penman-Monteith", "et0_hg_gs_in": "inches Apr-Sep, Hargreaves-Samani",
                  "*_change": "future mean minus baseline mean (same units)", "*_change_pct": "percent change"},
        "method": "Per model: region mean of per-cell season totals each year; change = mean(2035-2055) - mean(1995-2014) "
                  "for the same model (delta method, so model bias largely cancels). Ensemble = mean/min/max across models.",
        "fetch_failures": len(fails),
        **res,
    }
    (PROC / "cmip6_2045.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["ensemble"], indent=1))
    print(json.dumps(out.get("power_1995_2014_region_mean"), indent=1))
    print({m: res["models"][m]["baseline_1995_2014"] for m in MODELS})


if __name__ == "__main__":
    main()
