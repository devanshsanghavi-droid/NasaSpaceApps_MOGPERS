"""m06: pre-2016 history for the v2 (legacy-N) model. Model-owned; never writes data/processed or data/raw.

Run: python3 model/m06_history.py   (~5-10 min cold; seconds from cache in model/cache/)

Outputs (model/out/):
  nwis_2012_2015.parquet        site, date, no3_mgL, no3_qual, q_cfs, q_qual  (USGS dv, 2011-10-01..2015-09-30;
                                Raccoon nitrate from 2012-03-02; Des Moines has no nitrate before 2016)
  power_daily_basin_2008_2014.parquet  basin, date, POWER vars (same cells/weights/aggregation as hydro p03)
  cover_basin_8day_2011_2015.parquet   MODIS 13Q1 basin composites 2011-07..2015-06 (same mask, rules and code
                                as modis p09, imported; cache in model/cache/modis)
  cdl_basin_year_2011_2015.parquet     basin, year, corn, soy share: PC usda-cdl read at 8x decimation (240 m),
                                validated against the 30 m cdl_basin_year values for 2016-2021
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP / "pipeline"))
from common import get, STAC_URL  # noqa: E402

OUT = HERE / "out"
CACHE = HERE / "cache"
PROC = APP / "data" / "processed"
SITES = ["05484500", "05482000"]


# ------------------------------------------------------------------ NWIS
def nwis():
    import p02_nwis as P2
    c = CACHE / "nwis"
    c.mkdir(parents=True, exist_ok=True)
    frames = []
    for wy in range(2012, 2016):
        f = c / f"dv_wy{wy}.json"
        if f.exists():
            js = json.loads(f.read_text())
        else:
            js = get(P2.DV, params={"format": "json", "sites": ",".join(SITES), "parameterCd": "99133,00060",
                                    "statCd": "00003", "startDT": f"{wy - 1}-10-01", "endDT": f"{wy}-09-30",
                                    "siteStatus": "all"}, timeout=180).json()
            f.write_text(json.dumps(js))
        frames.append(P2.parse(js, daily=True))
    d = pd.concat(frames)
    d["var"] = d.param.map({"99133": "no3", "00060": "q"})
    v = d.pivot_table(index=["site", "date"], columns="var", values="value", aggfunc="first")
    q = d.pivot_table(index=["site", "date"], columns="var", values="qual", aggfunc="first")
    out = pd.DataFrame({"no3_mgL": v.get("no3"), "no3_qual": q.get("no3"), "q_cfs": v.get("q"),
                        "q_qual": q.get("q")}).reset_index()
    out["date"] = pd.to_datetime(out["date"])
    out.to_parquet(OUT / "nwis_2012_2015.parquet", compression="zstd", index=False)
    for s, g in out.groupby("site"):
        n = g.dropna(subset=["no3_mgL"])
        print(f"  NWIS {s}: nitrate days by year {n.groupby(n.date.dt.year).size().to_dict()}, "
              f"max {n.no3_mgL.max() if len(n) else None}; q days {g.q_cfs.notna().sum()}")
    return out


# ------------------------------------------------------------------ POWER
def power():
    import p03_power as P3
    c = CACHE / "power"
    c.mkdir(parents=True, exist_ok=True)
    cells = pd.read_parquet(PROC / "power_cells.parquet")

    def fetch(row):
        f = c / f"{row.cell_id}_2008_2014.json"
        if f.exists() and f.stat().st_size > 1000:
            return row.cell_id, json.loads(f.read_text())
        r = get(P3.API, params=dict(parameters=",".join(P3.PARAMS), community="AG", longitude=row.lon,
                                    latitude=row.lat, start="20080101", end="20141231", format="JSON"),
                timeout=300, retries=6)
        f.write_text(r.text)
        return row.cell_id, r.json()

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(fetch, [r for r in cells.itertuples()]))
    frames = []
    for cid, d in res:
        p = d["properties"]["parameter"]
        df = pd.DataFrame({k: pd.Series(p[k], dtype=float) for k in P3.PARAMS if k in p})
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        df = df.replace(-999.0, np.nan)
        df["cell_id"] = cid
        frames.append(df)
    daily = pd.concat(frames).rename_axis("date").reset_index()
    out = []
    for b in ["raccoon", "desmoines"]:
        w = cells.set_index("cell_id")[f"w_{b}"]
        w = w[w > 0]
        sub = daily[daily.cell_id.isin(w.index)].copy()
        sub["w"] = sub.cell_id.map(w)
        rows = {}
        for col in P3.PARAMS:
            ok = sub[col].notna()
            num = (sub[col].where(ok, 0) * sub.w).groupby(sub.date).sum()
            den = (sub.w * ok).groupby(sub.date).sum()
            rows[col] = (num / den.replace(0, np.nan)).astype("float32")
        bd = pd.DataFrame(rows).rename_axis("date").reset_index()
        bd.insert(0, "basin", b)
        out.append(bd)
    basin = pd.concat(out, ignore_index=True)
    basin.to_parquet(OUT / "power_daily_basin_2008_2014.parquet", compression="zstd", index=False)
    # overlap check is not possible (2015+ comes from a separate request); report annual precip
    yr = basin.groupby(["basin", basin.date.dt.year]).PRECTOTCORR.sum().unstack(0).round(0)
    print("  POWER annual precip (mm):", yr.to_dict())
    return basin


# ------------------------------------------------------------------ MODIS (reuse p09 code, model-local cache)
def modis():
    import p09_modis_cover as P9
    import pystac_client
    P9.CACHE = CACHE / "modis"
    P9.CACHE.mkdir(parents=True, exist_ok=True)
    px, tiles, huc12, basin_of_idx = P9.load_mask()
    client = pystac_client.Client.open(STAC_URL)
    best = {}
    for it in client.search(collections=["modis-13Q1-061"], bbox=[-96.12, 41.46, -93.58, 44.27],
                            datetime="2011-06-01/2015-06-30").items():
        p = it.id.split(".")
        if p[2] not in tiles:
            continue
        k = (p[0], p[1], p[2])
        if k not in best or p[4] > best[k].id.split(".")[4]:
            best[k] = it
    print(f"  MODIS items 2011-06..2015-06: {len(best)}")
    t0 = time.time()
    fails = []
    with ThreadPoolExecutor(6) as ex:
        futs = [ex.submit(P9.fetch, k, it, tiles[k[2]]) for k, it in best.items()]
        for fu in futs:
            try:
                fu.result()
            except Exception as e:
                fails.append(str(e)[:200])
    print(f"  MODIS reads done in {time.time() - t0:.0f}s, {len(fails)} failed")
    comps = {}
    for k in best:
        if P9.cache_path(k).exists():
            comps.setdefault((k[0], k[1]), {})[k[2]] = k
    rows = []
    for (prod, adate), kt in sorted(comps.items(), key=lambda x: (x[0][1], x[0][0])):
        start = pd.Timestamp(int(adate[1:5]), 1, 1) + pd.Timedelta(days=int(adate[5:]) - 1)
        b, _ = P9.composite_stats(kt, px, tiles, len(huc12))
        bd = P9.derive(b)
        bd["date"] = start + pd.Timedelta(days=8)
        bd["composite_start"] = start
        bd["sensor"] = "terra" if prod.startswith("MOD") else "aqua"
        bd["n_tiles"] = len(kt)
        bd["basin"] = bd.index
        rows.append(bd.reset_index(drop=True))
    b8 = pd.concat(rows, ignore_index=True)
    b8 = b8[(b8.composite_start >= "2011-06-15") & (b8.composite_start <= "2015-06-09")]
    b8.to_parquet(OUT / "cover_basin_8day_2011_2015.parquet", compression="zstd", index=False)
    u = b8[(b8.valid_frac >= 0.3) & (b8.tile_cover_frac >= 0.9)]
    print(f"  MODIS composites: {len(b8)} rows, usable {len(u)}; monthly bare (raccoon):",
          u[u.basin == "raccoon"].groupby(pd.to_datetime(u.date).dt.month).bare_share.mean().round(2).to_dict())
    return b8


# ------------------------------------------------------------------ CDL corn share (coarse)
def cdl():
    import geopandas as gpd
    import planetary_computer
    import pystac_client
    import rasterio
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from rasterio.warp import reproject, Resampling
    from shapely import wkb
    hu = pd.read_parquet(PROC / "huc12.parquet")
    g = gpd.GeoDataFrame(hu, geometry=hu.geometry.apply(lambda b: wkb.loads(b)), crs=4326).to_crs(5070)
    bas = g.dissolve("basin")
    res = 240.0
    x0, y0, x1, y1 = g.total_bounds
    x0, y1 = np.floor(x0 / res) * res, np.ceil(y1 / res) * res
    W, H = int(np.ceil((x1 - x0) / res)), int(np.ceil((y1 - y0) / res))
    tr = from_origin(x0, y1, res, res)
    lab = np.zeros((H, W), np.uint8)
    for i, (b, row) in enumerate(bas.iterrows(), 1):
        lab |= (rasterize([row.geometry], out_shape=(H, W), transform=tr) * i).astype(np.uint8)
    names = {i: b for i, b in enumerate(bas.index, 1)}
    lon0, lat0, lon1, lat1 = g.to_crs(4326).total_bounds
    c = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    corn_codes = [1, 12, 13, 241]
    soy_codes = [5, 239, 240]
    rows = []
    for y in range(2011, 2022):
        f = CACHE / "cdl" / f"cdl240_{y}.npy"
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            mos = np.load(f)
        else:
            items = [it for it in c.search(collections=["usda-cdl"], bbox=[lon0, lat0, lon1, lat1],
                                           datetime=f"{y}-01-01/{y}-12-31",
                                           query={"usda_cdl:type": {"eq": "cropland"}}).items()
                     if int(it.properties["start_datetime"][:4]) == y]
            mos = np.zeros((H, W), np.uint8)
            for it in items:
                for k in range(5):
                    try:
                        with rasterio.open(planetary_computer.sign(it.assets["cropland"].href)) as src:
                            dst = np.zeros((H, W), np.uint8)
                            reproject(rasterio.band(src, 1), dst, dst_transform=tr, dst_crs="EPSG:5070",
                                      resampling=Resampling.nearest, src_nodata=0, dst_nodata=0)
                        m = (mos == 0) & (dst != 0)
                        mos[m] = dst[m]
                        break
                    except Exception as e:
                        print("   retry", it.id, str(e)[:100])
                        time.sleep(3 * (k + 1))
            np.save(f, mos)
        for i, b in names.items():
            m = lab == i
            n = (m & (mos > 0)).sum()
            rows.append(dict(basin=b, year=y, corn=float(np.isin(mos[m], corn_codes).sum() / n),
                             soy=float(np.isin(mos[m], soy_codes).sum() / n), n_px=int(n)))
    df = pd.DataFrame(rows)
    ref = pd.read_parquet(PROC / "cdl_basin_year.parquet")[["basin", "year", "corn", "soy"]]
    chk = df.merge(ref, on=["basin", "year"], suffixes=("_240m", "_30m"))
    bias = float((chk.corn_240m - chk.corn_30m).mean())
    print("  CDL 240 m vs 30 m (2016-2021): corn bias", round(bias, 4), "max abs",
          round(float((chk.corn_240m - chk.corn_30m).abs().max()), 4))
    df["corn_bias_vs_30m_2016_2021"] = bias
    df.to_parquet(OUT / "cdl_basin_year_2011_2015.parquet", compression="zstd", index=False)
    print(df.pivot(index="year", columns="basin", values="corn").round(3).to_dict())
    return df


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1:] or ["nwis", "power", "modis", "cdl"]
    for w in which:
        t = time.time()
        print(f"== {w}")
        globals()[w]()
        print(f"   {w} done in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
