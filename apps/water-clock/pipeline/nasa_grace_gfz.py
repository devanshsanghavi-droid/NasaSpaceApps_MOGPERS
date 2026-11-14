"""Volumetric GRACE / GRACE-FO water storage for the Water Clock region, without an Earthdata login.

Sources (GFZ ISDC, open HTTPS, no login):
 1. GFZ GravIS RL06 Level-3 TWS, v0006 (Boergens, Dobslaw, Dill 2019, doi:10.5880/GFZ.GRAVIS_06_L3_TWS)
    https://isdc-data.gfz.de/grace/GravIS/GFZ/Level-3/TWS/GRAVIS-3_GFZOP_0600_TWS_GRID_GFZ_0006.nc
    1 deg global grid, monthly 2002-04 .. 2026-08, variable `tws` (cm equivalent water height, anomaly).
 2. G3P Global Gravity-based Groundwater Product v1.12 (Guentner et al. 2024, doi:10.5880/G3P.2024.001)
    https://isdc-data.gfz.de/grace/GravIS/G3P/v1.12/G3P_v1.12.zip  -> GWSA (groundwater storage anomaly = GRACE TWS
    minus soil moisture, snow, surface water, glaciers from ESA-CCI / model products), 0.5 deg, 2002-04 .. 2023-09.
 Optional 3. TerraClimate soil moisture (Planetary Computer zarr, cpdataeuwest) -> our own GWS = TWS - SM anomaly
    (env WATER_CLOCK_TERRACLIMATE=1; see notes).
 Optional 4. JPL RL06.3 mascons via earthaccess (env WATER_CLOCK_EARTHDATA=1; needs a free Earthdata login + ~/.netrc;
    NOT run in this environment because urs.earthdata.nasa.gov / podaac are blocked and no login exists).

Region mean: area-weighted mean of grid cells, weight = area of the cell inside the 26 region county polygons
(EPSG:5070). NOTE the effective GRACE resolution is ~300 km (GFZ product is filtered), so a 1-deg region mean is a
regional (~western-Kansas-scale) signal with leakage from neighbours, not a county-resolved one.
Trend: OLS on the monthly series y = a + b t + annual + semi-annual harmonics; months without data (GRACE gaps,
2017-07 .. 2018-05 GRACE/GRACE-FO gap) are simply absent (no interpolation). Standard error inflated for lag-1
autocorrelation of residuals (effective n = n (1-r1)/(1+r1)). Windows: 2003-01..2016-12 and 2003-01..latest.
Outputs: merges tws_cm (+ g3p_gws_cm, g3p_rzsm_cm, ...) into data/processed/grace_region.parquet (monthly GRACE
values on rows keyed by month; GRACE-DA rows keep their dates), writes data/raw/gfz/gfz_summary.json and trend grids
data/raw/gfz/trend_grids.npz used by nasa_grace_maps.py.
Re-run: python3 pipeline/nasa_grace_gfz.py
"""
import json
import os
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nasa_common import HP_BBOX, PROC, RAW, http_get, region_counties  # noqa: E402

D = RAW / "gfz"
D.mkdir(parents=True, exist_ok=True)
GFZ_URL = "https://isdc-data.gfz.de/grace/GravIS/GFZ/Level-3/TWS/GRAVIS-3_GFZOP_0600_TWS_GRID_GFZ_0006.nc"
G3P_URL = "https://isdc-data.gfz.de/grace/GravIS/G3P/v1.12/G3P_v1.12.zip"
GFZ_NC = D / "GRAVIS-3_GFZOP_0600_TWS_GRID_GFZ_0006.nc"
G3P_ZIP = D / "G3P_v1.12.zip"
G3P_DIR = D / "g3p"


def download(url, path):
    if path.exists():
        return
    r = http_get(url, timeout=1800, stream=True)
    tmp = path.with_suffix(".part")
    with open(tmp, "wb") as f:
        for ch in r.iter_content(2 ** 22):
            f.write(ch)
    tmp.rename(path)


def cell_weights(lat, lon, counties, dlat, dlon):
    """Area (km2) of each grid cell inside the region polygons. lon in -180..180."""
    import geopandas as gpd
    from shapely.geometry import box
    reg = counties.to_crs(5070).geometry.union_all()
    W = np.zeros((len(lat), len(lon)))
    for i, la in enumerate(lat):
        if not (34 < la < 43):
            continue
        for j, lo in enumerate(lon):
            if not (-105 < lo < -97):
                continue
            b = gpd.GeoSeries([box(lo - dlon / 2, la - dlat / 2, lo + dlon / 2, la + dlat / 2)], crs=4326).to_crs(5070)[0]
            W[i, j] = b.intersection(reg).area / 1e6
    return W


def trend(dates, y, t0, t1):
    s = pd.Series(np.asarray(y, float), index=pd.DatetimeIndex(dates))
    s = s[(s.index >= t0) & (s.index <= t1)].dropna()
    if len(s) < 24:
        return None
    t = (s.index - pd.Timestamp("2003-01-01")).days.values / 365.25
    w = 2 * np.pi * t
    X = np.column_stack([np.ones_like(t), t, np.cos(w), np.sin(w), np.cos(2 * w), np.sin(2 * w)])
    beta, *_ = np.linalg.lstsq(X, s.values, rcond=None)
    res = s.values - X @ beta
    n, k = len(s), X.shape[1]
    r1 = float(np.corrcoef(res[:-1], res[1:])[0, 1])
    neff = max(n * (1 - r1) / (1 + r1), k + 2)
    sig2 = (res ** 2).sum() / (n - k)
    cov = sig2 * np.linalg.inv(X.T @ X) * (n - k) / (neff - k)
    return dict(slope_cm_yr=round(float(beta[1]), 3), se_cm_yr=round(float(np.sqrt(cov[1, 1])), 3),
                n_months=int(n), first=str(s.index.min().date()), last=str(s.index.max().date()),
                lag1_resid_autocorr=round(r1, 3), n_eff=round(float(neff), 1))


def slope_grid(cube, dates, t0, t1):
    """Per-cell OLS trend (cm/yr) with harmonics. cube: (time, lat, lon)."""
    idx = (dates >= t0) & (dates <= t1)
    c = cube[idx]
    t = (dates[idx] - pd.Timestamp("2003-01-01")).days.values / 365.25
    w = 2 * np.pi * t
    X = np.column_stack([np.ones_like(t), t, np.cos(w), np.sin(w), np.cos(2 * w), np.sin(2 * w)])
    Y = c.reshape(len(t), -1)
    ok = np.isfinite(Y).all(0)
    out = np.full(Y.shape[1], np.nan)
    if ok.any():
        beta, *_ = np.linalg.lstsq(X, Y[:, ok], rcond=None)
        out[ok] = beta[1]
    return out.reshape(c.shape[1:])


def load_gfz():
    import xarray as xr
    download(GFZ_URL, GFZ_NC)
    ds = xr.open_dataset(GFZ_NC)
    lon = ds.lon.values.astype(float)
    lon = np.where(lon > 180, lon - 360, lon)
    sel_lat = (ds.lat.values > HP_BBOX[1] - 1) & (ds.lat.values < HP_BBOX[3] + 1)
    sel_lon = (lon > HP_BBOX[0] - 1) & (lon < HP_BBOX[2] + 1)
    isel = dict(lat=np.nonzero(sel_lat)[0], lon=np.nonzero(sel_lon)[0])
    tws = ds.tws.isel(isel).values.astype(float)
    std = ds.std_tws.isel(isel).values.astype(float)
    dates = pd.DatetimeIndex(ds.time.values)
    return dates, ds.lat.values[sel_lat].astype(float), lon[sel_lon], tws, std


def load_g3p():
    import xarray as xr
    if not G3P_DIR.exists() or not list(G3P_DIR.glob("gwsa*.nc")):
        download(G3P_URL, G3P_ZIP)
        G3P_DIR.mkdir(exist_ok=True)
        with zipfile.ZipFile(G3P_ZIP) as z:
            for i in z.infolist():
                if i.filename.endswith(".nc") and "Glacier" not in i.filename:
                    (G3P_DIR / Path(i.filename).name).write_bytes(z.read(i))
    out = {}
    for f in sorted(G3P_DIR.glob("*.nc")):
        key = f.name.split("_")[0]
        ds = xr.open_dataset(f)
        var = key if key in ds.data_vars else list(ds.data_vars)[0]
        da = ds[var]
        latn = [d for d in da.dims if "lat" in d][0]
        lonn = [d for d in da.dims if "lon" in d][0]
        lon = ds[lonn].values.astype(float)
        lon = np.where(lon > 180, lon - 360, lon)
        la = ds[latn].values.astype(float)
        sl = (la > HP_BBOX[1] - 1) & (la < HP_BBOX[3] + 1)
        so = (lon > HP_BBOX[0] - 1) & (lon < HP_BBOX[2] + 1)
        a = da.transpose("time", latn, lonn).isel({latn: np.nonzero(sl)[0], lonn: np.nonzero(so)[0]}).values.astype(float)
        units = da.attrs.get("units", "")
        out[key] = dict(dates=pd.DatetimeIndex(ds.time.values), lat=la[sl], lon=lon[so], data=a, units=units,
                        var=var, long_name=da.attrs.get("long_name", ""), file=f.name)
    return out


def to_cm(a, units):
    u = units.lower()
    if u in ("mm", "kg m-2", "kg/m2", "mm ewh", "mm water equivalent"):
        return a / 10.0
    if u in ("m",):
        return a * 100.0
    return a  # cm


def region_series(dates, lat, lon, cube, W):
    w = W / W.sum()
    vals = []
    for k in range(cube.shape[0]):
        a = cube[k]
        m = np.isfinite(a) & (w > 0)
        vals.append(float((a[m] * w[m]).sum() / w[m].sum()) if m.any() else np.nan)
    return pd.Series(vals, index=dates)


def terraclimate_soil(counties):
    """Region-mean TerraClimate soil moisture (mm) monthly; optional (env WATER_CLOCK_TERRACLIMATE=1)."""
    import xarray as xr
    # anonymous access to the blob is refused (HTTP 409 "Public access is not permitted"), so use the Planetary
    # Computer STAC collection 'terraclimate' (signed SAS token; needs `pip install adlfs`).
    import planetary_computer
    import pystac_client
    c = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                  modifier=planetary_computer.sign_inplace)
    a = c.get_collection("terraclimate").assets["zarr-abfs"]
    ds = xr.open_zarr(a.href, storage_options=a.extra_fields["xarray:open_kwargs"]["storage_options"], consolidated=True)
    sm = ds["soil"].sel(lat=slice(40.1, 36.9), lon=slice(-102.1, -99.5))
    sm = sm.sel(time=slice("2002-01-01", None)).load()
    from shapely import contains_xy
    LON, LAT = np.meshgrid(sm.lon.values, sm.lat.values)
    m = contains_xy(counties.geometry.union_all(), LON, LAT)
    s = pd.Series([float(np.nanmean(sm.values[k][m])) for k in range(sm.shape[0])],
                  index=pd.DatetimeIndex(sm.time.values))
    return s


def jpl_mascons_earthaccess():
    """Code path for JPL GRACE/GRACE-FO RL06.3 CRI mascons (needs Earthdata login). Not run here."""
    import earthaccess  # noqa: F401  (pip install earthaccess)
    earthaccess.login(strategy="netrc")
    res = earthaccess.search_data(short_name="TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4", cloud_hosted=True)
    files = earthaccess.download(res, str(RAW / "jpl_mascon"))
    import xarray as xr
    ds = xr.open_dataset(files[0])
    lwe = ds["lwe_thickness"].sel(lat=slice(36.9, 40.1), lon=slice(257.9, 260.5))  # cm, 0.5-deg grid of 3-deg mascons
    return lwe.mean(["lat", "lon"]).to_series()


def main():
    counties = region_counties()
    summary = {"sources": {}, "trends": {}, "notes": []}
    # ---- GFZ TWS
    dates, lat, lon, tws, std = load_gfz()
    # GFZ has a few split-month solutions (two solutions centred in Oct 2011 and in Apr 2015, none in Nov 2011 /
    # May 2015): when two solutions share a calendar month, the later one moves to the next month if that month has
    # no solution of its own; otherwise (never the case in v0006) duplicates are averaged.
    per = list(dates.to_period("M"))
    for k in range(1, len(per)):
        if per[k] == per[k - 1] and (per[k] + 1) not in per:
            per[k] = per[k] + 1
    dates = pd.PeriodIndex(per).to_timestamp()
    W = cell_weights(lat, lon, counties, 1.0, 1.0)
    s_tws = region_series(dates, lat, lon, tws, W)
    s_std = region_series(dates, lat, lon, std, W)
    summary["sources"]["gfz_tws"] = dict(url=GFZ_URL, cell_deg=1.0, first=str(dates.min().date()),
                                         last=str(dates.max().date()), n_months=int(s_tws.notna().sum()),
                                         region_cells=int((W > 0).sum()), units="cm EWH anomaly",
                                         region_cell_weights_km2={f"{lat[i]:.1f},{lon[j]:.1f}": round(float(W[i, j]))
                                                                  for i, j in zip(*np.nonzero(W))})
    windows = {"2003_2016": ("2003-01-01", "2016-12-31"), "2003_latest": ("2003-01-01", "2030-01-01"),
               "2018_latest_gracefo": ("2018-06-01", "2030-01-01")}
    summary["trends"]["gfz_tws"] = {k: trend(s_tws.index, s_tws.values, *v) for k, v in windows.items()}
    df = pd.DataFrame({"tws_cm": s_tws, "tws_std_cm": s_std}).groupby(level=0).mean()
    grids = {"lat_1deg": lat, "lon_1deg": lon,
             "tws_trend_2003_latest": slope_grid(tws, dates, *[pd.Timestamp(x) for x in windows["2003_latest"]]),
             "tws_trend_2003_2016": slope_grid(tws, dates, *[pd.Timestamp(x) for x in windows["2003_2016"]])}
    # ---- G3P
    try:
        g = load_g3p()
        for key, v in g.items():
            if key not in ("gwsa", "rzsm", "swe", "sws", "tws"):
                continue
            dd = v["dates"].to_period("M").to_timestamp()
            Wg = cell_weights(v["lat"], v["lon"], counties, abs(v["lat"][1] - v["lat"][0]), abs(v["lon"][1] - v["lon"][0]))
            cube = to_cm(v["data"], v["units"])
            s = region_series(dd, v["lat"], v["lon"], cube, Wg)
            name = {"gwsa": "g3p_gws_cm", "rzsm": "g3p_rzsm_cm", "swe": "g3p_swe_cm", "sws": "g3p_sws_cm",
                    "tws": "g3p_tws_cm"}[key]
            df = df.join(s.rename(name).groupby(level=0).mean(), how="outer")
            summary["sources"][name] = dict(url=G3P_URL, file=v["file"], var=v["var"], long_name=v["long_name"],
                                            units_raw=v["units"], cell_deg=float(abs(v["lat"][1] - v["lat"][0])),
                                            first=str(dd.min().date()), last=str(dd.max().date()),
                                            n_months=int(s.notna().sum()))
            summary["trends"][name] = {k: trend(s.index, s.values, *w) for k, w in windows.items()}
            if key == "gwsa":
                grids["lat_g3p"], grids["lon_g3p"] = v["lat"], v["lon"]
                grids["g3p_gws_trend_2003_latest"] = slope_grid(cube, dd, pd.Timestamp("2003-01-01"),
                                                                pd.Timestamp("2030-01-01"))
    except Exception as e:  # noqa: BLE001
        summary["notes"].append(f"G3P failed: {e!r}")
        print("G3P failed", e)
    # ---- optional TerraClimate-based groundwater estimate
    if os.environ.get("WATER_CLOCK_TERRACLIMATE") == "1":
        try:
            sm = terraclimate_soil(counties)
            sm = sm.copy()
            sm.index = sm.index.to_period("M").to_timestamp()
            base = sm["2004-01-01":"2009-12-31"].mean()
            sm_anom_cm = (sm - base) / 10.0
            df = df.join(sm_anom_cm.rename("tc_sm_anom_cm"), how="left")
            tw = df["tws_cm"] - df["tws_cm"]["2004-01-01":"2009-12-31"].mean()
            df["tws_minus_tcsm_cm"] = tw - df["tc_sm_anom_cm"]
            summary["trends"]["tws_minus_terraclimate_sm"] = {
                k: trend(df.index, df["tws_minus_tcsm_cm"].values, *w) for k, w in windows.items()}
            summary["sources"]["terraclimate_soil"] = dict(
                url="Planetary Computer STAC collection terraclimate -> az://cpdata/terraclimate.zarr (cpdataeuwest)", var="soil", units="mm",
                first=str(sm.index.min().date()), last=str(sm.index.max().date()), baseline="2004-2009 mean")
        except Exception as e:  # noqa: BLE001
            summary["notes"].append(f"TerraClimate failed: {e!r}")
            print("TerraClimate failed", e)
    if os.environ.get("WATER_CLOCK_EARTHDATA") == "1":
        s = jpl_mascons_earthaccess()
        df = df.join(s.rename("jpl_mascon_tws_cm"), how="left")
    # ---- merge into grace_region.parquet
    df.index.name = "month"
    df = df.reset_index()
    out = PROC / "grace_region.parquet"
    gr = pd.read_parquet(out)
    gr = gr[gr.file_date.notna()].drop_duplicates("file_date")  # GRACE-DA rows only (idempotent re-runs)
    drop = [c for c in gr.columns if c in df.columns and c != "month"] + (["month"] if "month" in gr else [])
    gr = gr.drop(columns=drop)
    gr["month"] = gr.date.dt.to_period("M").dt.to_timestamp()
    merged = gr.merge(df, on="month", how="outer")
    merged["date"] = merged["date"].fillna(merged["month"])
    merged["source"] = merged["source"].fillna("GFZ GravIS RL06 L3 TWS / G3P v1.12 (no GRACE-DA row)")
    merged = merged.sort_values("date").reset_index(drop=True)
    merged.to_parquet(out, index=False)
    np.savez_compressed(D / "trend_grids.npz", **grids)
    (D / "gfz_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary["trends"], indent=1))
    print(merged[["date", "gws_pct", "tws_cm"] + [c for c in merged if c.startswith("g3p")]].iloc[::24].to_string())


if __name__ == "__main__":
    main()
