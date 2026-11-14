"""NASA POWER daily weather/soil wetness for every MERRA-2 cell intersecting the two basins.

POWER meteorology is on the MERRA-2 grid, 0.5 deg lat x 0.625 deg lon, cell centres at lat = k*0.5 and
lon = -180 + k*0.625 (verified by probing: values change at lat 42.25 and at lon -94.0625 / -93.4375).
The most recent months come from GEOS-IT (header `sources`), same grid. Solar (ALLSKY_SFC_SW_DWN) is on a 1 deg grid.

Outputs (data/processed/):
  power_cells.parquet        cell_id, lat, lon, elev_m, area_km2 (in 5070), w_raccoon, w_desmoines
                             (w_<basin> = area(cell & basin) / area(basin); sums to 1 per basin)
  huc12_cell.parquet         huc12, cell_id, weight (= area(cell & huc12) / area(huc12); sums to 1 per huc12)
  power_daily_cells.parquet  cell_id, date, <PARAMS>
  power_daily_basin.parquet  basin, date, <PARAMS> (area-weighted; weights renormalised over non-missing cells),
                             w_valid (weight share of cells with data for PRECTOTCORR)
Raw JSON cached in data/raw/power/ (2015-2025 cached for good; current year refreshed if > 20 h old).
"""
import datetime as dt
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkb
from shapely.geometry import box

from common import RAW, PROC, get

API = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "GWETROOT", "GWETTOP", "SNODP", "PRECSNOLAND",
          "RH2M", "ALLSKY_SFC_SW_DWN", "WS2M"]
DLAT, DLON = 0.5, 0.625
START_YEAR = 2015
TODAY = dt.date.today()
CACHE = RAW / "power"
CACHE.mkdir(parents=True, exist_ok=True)
BASINS = ["raccoon", "desmoines"]


def cell_id(lat, lon):
    return f"p{lat:.2f}_{lon:.3f}"


def cells_for(geom_union_4326):
    lon0, lat0, lon1, lat1 = geom_union_4326.bounds
    out = []
    for i in range(math.floor((lat0 + DLAT / 2) / DLAT), math.floor((lat1 + DLAT / 2) / DLAT) + 1):
        la = i * DLAT
        for k in range(math.floor((lon0 + 180 + DLON / 2) / DLON), math.floor((lon1 + 180 + DLON / 2) / DLON) + 1):
            lo = -180 + k * DLON
            b = box(lo - DLON / 2, la - DLAT / 2, lo + DLON / 2, la + DLAT / 2)
            if b.intersects(geom_union_4326):
                out.append((round(la, 4), round(lo, 4), b.segmentize(0.01)))
    return out


def fetch(lat, lon, y0, y1):
    f = CACHE / f"{cell_id(lat, lon)}_{y0}_{y1}.json"
    current = y1 >= TODAY.year
    if f.exists() and f.stat().st_size > 1000:
        if not current or (time.time() - f.stat().st_mtime) < 20 * 3600:
            return json.loads(f.read_text())
    end = min(dt.date(y1, 12, 31), TODAY)
    r = get(API, params=dict(parameters=",".join(PARAMS), community="AG", longitude=lon, latitude=lat,
                             start=f"{y0}0101", end=end.strftime("%Y%m%d"), format="JSON"), timeout=300, retries=6)
    d = r.json()
    f.write_text(json.dumps(d))
    return d


def main():
    h = pd.read_parquet(PROC / "huc12.parquet")
    hg = gpd.GeoDataFrame(h.drop(columns="geometry"), geometry=h.geometry.apply(wkb.loads), crs=4326)
    basins = hg.dissolve("basin")
    cells = cells_for(basins.union_all())
    print(f"{len(cells)} MERRA-2 cells intersect the basins")
    cg = gpd.GeoDataFrame({"cell_id": [cell_id(a, b) for a, b, _ in cells], "lat": [a for a, _, _ in cells],
                           "lon": [b for _, b, _ in cells]}, geometry=[g for _, _, g in cells], crs=4326).to_crs(5070)
    cg["area_km2"] = cg.area / 1e6
    b5 = basins.to_crs(5070)
    for b in BASINS:
        bg = b5.loc[b, "geometry"]
        cg[f"w_{b}"] = cg.geometry.intersection(bg).area / bg.area
    cg = cg[(cg.w_raccoon > 0) | (cg.w_desmoines > 0)].reset_index(drop=True)

    # HUC-12 -> cell weights
    h5 = hg.to_crs(5070)[["huc12", "geometry"]]
    h5["h_area"] = h5.area
    ov = gpd.overlay(h5, cg[["cell_id", "geometry"]], how="intersection", keep_geom_type=True)
    ov["weight"] = ov.area / ov.h_area
    ov = ov[ov.weight > 1e-4]
    ov["weight"] = ov.weight / ov.groupby("huc12").weight.transform("sum")
    ov[["huc12", "cell_id", "weight"]].sort_values(["huc12", "cell_id"]).to_parquet(
        PROC / "huc12_cell.parquet", compression="zstd", index=False)
    assert ov.huc12.nunique() == len(h), "every HUC-12 must map to a cell"

    # Download: one historical chunk (2015-2025) + current year per cell
    jobs = [(la, lo, START_YEAR, 2025) for la, lo in zip(cg.lat, cg.lon)]
    jobs += [(la, lo, 2026, TODAY.year) for la, lo in zip(cg.lat, cg.lon)] if TODAY.year >= 2026 else []
    t0 = time.time()
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda j: (j, fetch(*j)), jobs))
    print(f"downloaded/cached {len(res)} POWER responses in {time.time() - t0:.0f}s")

    frames, elev, srcs = [], {}, set()
    for (la, lo, _, _), d in res:
        p = d["properties"]["parameter"]
        srcs.update(d["header"].get("sources", []))
        df = pd.DataFrame({k: pd.Series(p[k], dtype=float) for k in PARAMS if k in p})
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        df = df.replace(-999.0, np.nan)
        df["cell_id"] = cell_id(la, lo)
        elev[cell_id(la, lo)] = d["geometry"]["coordinates"][2]
        frames.append(df)
    print("POWER sources:", sorted(srcs))
    daily = pd.concat(frames).rename_axis("date").reset_index()
    daily = daily.sort_values(["cell_id", "date"]).drop_duplicates(["cell_id", "date"])
    # trim trailing dates where every cell is missing the core variables (POWER latency)
    core = daily.groupby("date")[["PRECTOTCORR", "T2M", "GWETROOT"]].apply(lambda g: g.notna().all(axis=None))
    last = core[core].index.max()
    daily = daily[daily.date <= last]
    daily["date"] = daily.date.dt.date
    daily = daily[["cell_id", "date"] + PARAMS]
    for c in PARAMS:
        daily[c] = daily[c].astype("float32")
    daily.to_parquet(PROC / "power_daily_cells.parquet", compression="zstd", index=False)

    cg["elev_m"] = cg.cell_id.map(elev)
    cg[["cell_id", "lat", "lon", "elev_m", "area_km2", "w_raccoon", "w_desmoines"]].to_parquet(
        PROC / "power_cells.parquet", compression="zstd", index=False)

    # Basin area-weighted means
    out = []
    for b in BASINS:
        w = cg.set_index("cell_id")[f"w_{b}"]
        w = w[w > 0]
        sub = daily[daily.cell_id.isin(w.index)].copy()
        sub["w"] = sub.cell_id.map(w)
        rows = {}
        for c in PARAMS:
            ok = sub[c].notna()
            num = (sub[c].where(ok, 0) * sub.w).groupby(sub.date).sum()
            den = (sub.w * ok).groupby(sub.date).sum()
            rows[c] = (num / den.replace(0, np.nan)).astype("float32")
            if c == "PRECTOTCORR":
                rows["w_valid"] = den.astype("float32")
        bd = pd.DataFrame(rows).rename_axis("date").reset_index()
        bd.insert(0, "basin", b)
        out.append(bd)
    basin = pd.concat(out, ignore_index=True)
    basin.to_parquet(PROC / "power_daily_basin.parquet", compression="zstd", index=False)
    report(cg, daily, basin, ov)


def report(cg, daily, basin, ov):
    print(f"\npower_cells.parquet: {len(cg)} cells; weights sum raccoon={cg.w_raccoon.sum():.4f} "
          f"desmoines={cg.w_desmoines.sum():.4f}")
    print(cg[["cell_id", "elev_m", "w_raccoon", "w_desmoines"]].round(3).to_string(index=False))
    print(f"huc12_cell.parquet: {len(ov)} rows, {ov.huc12.nunique()} HUC-12s")
    print(f"power_daily_cells.parquet: {len(daily):,} rows, {daily.date.min()}..{daily.date.max()}")
    print(f"power_daily_basin.parquet: {len(basin):,} rows, {basin.date.min()}..{basin.date.max()}")
    print("missing fraction (cells):", daily[PARAMS].isna().mean().round(4).to_dict())
    miss = daily[daily[PARAMS].isna().any(axis=1)]
    if len(miss):
        print("dates with any missing:", miss.date.min(), "..", miss.date.max(), f"({miss.date.nunique()} dates)")
    b = basin.copy()
    b["year"] = pd.to_datetime(b.date).dt.year
    ann = b.groupby(["basin", "year"]).agg(n=("date", "size"), precip_mm=("PRECTOTCORR", "sum"),
                                           gwetroot=("GWETROOT", "mean"), t2m=("T2M", "mean"),
                                           snow_mm=("PRECSNOLAND", "sum"))
    with pd.option_context("display.width", 200):
        print(ann.round(3).to_string())


if __name__ == "__main__":
    main()
