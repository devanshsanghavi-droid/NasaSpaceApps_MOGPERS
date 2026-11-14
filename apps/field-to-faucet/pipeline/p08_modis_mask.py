"""Static persistent-row-crop mask on the MODIS 250 m sinusoidal grid for both basins.

For every MODIS 250 m pixel (global sinusoidal grid of MOD13Q1, 231.656 m) that touches the Raccoon or Des Moines
basin, compute the fraction of its area that is row crop (corn / soy / other row crops) in >= 5 of the 6 years
2016-2021, from USDA CDL `cropland` (30 m, EPSG:5070) on Microsoft Planetary Computer (`usda-cdl`, ends 2021).
Pixels with fraction >= 0.75 inside a HUC-12 of either basin form the mask used by p09_modis_cover.py.

Outputs (data/raw/modis/):
  mask_grid.npz       rowcrop_frac (float32), huc_idx (int16, -1 = outside), basin_id (uint8: 0 none, 1 raccoon,
                      2 desmoines), mask (bool), grid transform / shape / global row-col offset, huc12 id list
  rowcrop_frac.tif    rowcrop_frac as GeoTIFF (sinusoidal) for inspection
  huc_idx.tif         HUC-12 index raster (index into huc12 list stored in mask_grid.npz)
  cdl/rowcrop_<year>.npz  per-year packed row-crop bitmask on the 30 m 5070 window (cache)
Run: python3 pipeline/p08_modis_mask.py
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urlunsplit

import geopandas as gpd
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds

from common import PROC, RAW, STAC_URL

OUT = RAW / "modis"
CDL_CACHE = OUT / "cdl"
OUT.mkdir(parents=True, exist_ok=True)
CDL_CACHE.mkdir(parents=True, exist_ok=True)

YEARS = list(range(2016, 2022))
MIN_YEARS = 5
FRAC_MIN = 0.75
# Row crops (CDL codes): corn C {1,12,13,241}, soy S {5,239,240}, other row crops R
# {2 cotton,3 rice,4 sorghum,6 sunflower,10 peanuts,11 tobacco,41 sugarbeets,42 dry beans,43 potatoes}
ROWCROP = np.array([1, 12, 13, 241, 5, 239, 240, 2, 3, 4, 6, 10, 11, 41, 42, 43])

# MODIS global sinusoidal grid (MOD13Q1 250 m)
SINU = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
X0, Y0 = -20015109.354, 10007554.677
TILE = 1111950.5197665233
PX = TILE / 4800.0
BASIN_CODE = {"raccoon": 1, "desmoines": 2}


def sign(href):
    s = urlsplit(href)
    return planetary_computer.sign(urlunsplit((s.scheme, s.netloc, s.path, "", "")))


def load_huc12():
    d = pd.read_parquet(PROC / "huc12.parquet")
    g = gpd.GeoDataFrame(d.drop(columns="geometry"), geometry=gpd.GeoSeries.from_wkb(d.geometry), crs=4326)
    return g.sort_values("huc12").reset_index(drop=True)


def modis_grid(g):
    """Basin window on the global MODIS grid: global row/col offsets, shape, affine."""
    b = g.to_crs(SINU).total_bounds
    c0 = int(np.floor((b[0] - X0) / PX)) - 2
    c1 = int(np.ceil((b[2] - X0) / PX)) + 2
    r0 = int(np.floor((Y0 - b[3]) / PX)) - 2
    r1 = int(np.ceil((Y0 - b[1]) / PX)) + 2
    tr = Affine(PX, 0, X0 + c0 * PX, 0, -PX, Y0 - r0 * PX)
    return r0, c0, r1 - r0, c1 - c0, tr


def cdl_window(g):
    """Basin bbox in EPSG:5070 snapped to the CDL national 30 m grid (pixel edges at 15 m mod 30) + 1 km pad."""
    b = g.to_crs(5070).total_bounds
    pad = 1000
    x0 = np.floor((b[0] - pad - 15) / 30) * 30 + 15
    x1 = np.ceil((b[2] + pad - 15) / 30) * 30 + 15
    y0 = np.floor((b[1] - pad - 15) / 30) * 30 + 15
    y1 = np.ceil((b[3] + pad - 15) / 30) * 30 + 15
    return (x0, y0, x1, y1)


def read_item_into(it, bb, H, W):
    """Read the part of one CDL item that overlaps bb; return (row_off, col_off, array) or None."""
    for k in range(6):
        try:
            with rasterio.open(sign(it.assets["cropland"].href)) as src:
                assert src.crs.to_epsg() == 5070
                sb = src.bounds
                ix0, iy0 = max(sb.left, bb[0]), max(sb.bottom, bb[1])
                ix1, iy1 = min(sb.right, bb[2]), min(sb.top, bb[3])
                if ix0 >= ix1 or iy0 >= iy1:
                    return None
                win = from_bounds(ix0, iy0, ix1, iy1, transform=src.transform)
                assert abs(win.col_off - round(win.col_off)) < 1e-6 and abs(win.row_off - round(win.row_off)) < 1e-6
                win = win.round_offsets().round_lengths()
                arr = src.read(1, window=win)
            ro = int(round((bb[3] - iy1) / 30))
            co = int(round((ix0 - bb[0]) / 30))
            return ro, co, arr
        except Exception as e:  # 403 (expired SAS), network hiccup
            print(f"  {it.id} retry {k}: {str(e)[:160]}", flush=True)
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"failed to read {it.id}")


def rowcrop_year(year, items, bb, H, W):
    f = CDL_CACHE / f"rowcrop_{year}.npz"
    if f.exists():
        z = np.load(f)
        if tuple(z["bb"]) == tuple(bb):
            return np.unpackbits(z["rc"])[: H * W].reshape(H, W).astype(bool), \
                np.unpackbits(z["ok"])[: H * W].reshape(H, W).astype(bool)
    codes = np.zeros((H, W), np.uint8)
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda it: read_item_into(it, bb, H, W), items))
    n = 0
    for r in res:
        if r is None:
            continue
        ro, co, a = r
        sub = codes[ro:ro + a.shape[0], co:co + a.shape[1]]
        m = (sub == 0) & (a != 0)
        sub[m] = a[m]
        n += 1
    rc = np.isin(codes, ROWCROP)
    ok = codes != 0
    np.savez_compressed(f, rc=np.packbits(rc.ravel()), ok=np.packbits(ok.ravel()), bb=np.array(bb))
    print(f"  CDL {year}: {n} items, row-crop share of window {rc.mean():.3f}, nodata {1 - ok.mean():.4f}", flush=True)
    return rc, ok


def main():
    t0 = time.time()
    g = load_huc12()
    r0, c0, H, W, tr = modis_grid(g)
    tiles = sorted({(c // 4800, r // 4800) for c in (c0, c0 + W - 1) for r in (r0, r0 + H - 1)})
    print(f"MODIS grid window: rows {r0}..{r0 + H - 1}, cols {c0}..{c0 + W - 1} ({H}x{W}); tiles h/v {tiles}")

    bb = cdl_window(g)
    CW, CH = int(round((bb[2] - bb[0]) / 30)), int(round((bb[3] - bb[1]) / 30))
    print(f"CDL 30 m window (EPSG:5070) {bb}: {CH}x{CW}")

    need = [y for y in YEARS if not (CDL_CACHE / f"rowcrop_{y}.npz").exists()]
    by_year = {}
    if need:
        client = pystac_client.Client.open(STAC_URL)
        ll = g.total_bounds.tolist()
        for it in client.search(collections=["usda-cdl"], bbox=ll, query={"usda_cdl:type": {"eq": "cropland"}},
                                datetime=f"{YEARS[0]}-01-01/{YEARS[-1]}-12-31").items():
            by_year.setdefault(int(it.properties["start_datetime"][:4]), []).append(it)
        print("PC usda-cdl cropland items per year:", {y: len(v) for y, v in sorted(by_year.items())})
        missing = [y for y in need if y not in by_year]
        if missing:
            raise RuntimeError(f"usda-cdl has no cropland items for {missing}")

    count = np.zeros((CH, CW), np.uint8)
    okall = np.ones((CH, CW), bool)
    for y in YEARS:
        rc, ok = rowcrop_year(y, by_year.get(y, []), bb, CH, CW)
        count += rc
        okall &= ok
        del rc, ok
    persist = (count >= MIN_YEARS)
    print(f"persistent row crop (>= {MIN_YEARS}/6 yrs) share of 30 m window: {persist.mean():.3f}")
    src = persist.astype(np.float32)
    src[~okall] = np.nan
    del count, persist

    frac = np.full((H, W), np.nan, np.float32)
    reproject(src, frac, src_transform=from_origin(bb[0], bb[3], 30, 30), src_crs="EPSG:5070", src_nodata=np.nan,
              dst_transform=tr, dst_crs=SINU, dst_nodata=np.nan, resampling=Resampling.average, num_threads=2)
    del src

    gs = g.to_crs(SINU)
    huc_idx = rasterize(((geom, i) for i, geom in enumerate(gs.geometry)), out_shape=(H, W), transform=tr,
                        fill=-1, dtype="int16")
    basin_of_idx = g.basin.map(BASIN_CODE).to_numpy().astype(np.uint8)
    basin_id = np.where(huc_idx >= 0, basin_of_idx[np.clip(huc_idx, 0, None)], 0).astype(np.uint8)
    mask = (huc_idx >= 0) & np.nan_to_num(frac >= FRAC_MIN, nan=False)

    np.savez_compressed(OUT / "mask_grid.npz", rowcrop_frac=frac, huc_idx=huc_idx, basin_id=basin_id, mask=mask,
                        transform=np.array(tr[:6]), shape=np.array([H, W]), offset=np.array([r0, c0]),
                        huc12=g.huc12.to_numpy().astype(str), basin_of_idx=basin_of_idx, crs=np.array(SINU),
                        frac_min=FRAC_MIN, min_years=MIN_YEARS, years=np.array(YEARS))
    prof = dict(driver="GTiff", height=H, width=W, count=1, crs=SINU, transform=tr, compress="deflate")
    with rasterio.open(OUT / "rowcrop_frac.tif", "w", dtype="float32", nodata=np.nan, **prof) as d:
        d.write(frac, 1)
    with rasterio.open(OUT / "huc_idx.tif", "w", dtype="int16", nodata=-1, **prof) as d:
        d.write(huc_idx, 1)

    pxkm2 = PX * PX / 1e6
    print(f"\npixel area {pxkm2:.4f} km2 (sinusoidal is equal-area)")
    for name, code in BASIN_CODE.items():
        inb = basin_id == code
        f = frac[inb]
        print(f"{name:9s}: {inb.sum():7d} px in basin ({inb.sum() * pxkm2:,.0f} km2), mean persistent-row-crop frac "
              f"{np.nanmean(f):.3f}, px >= {FRAC_MIN}: {mask[inb].sum():7d} ({mask[inb].mean():.1%} of basin px)")
    per = pd.Series(huc_idx[mask]).value_counts()
    nh = (g.index.to_series().map(per).fillna(0))
    print(f"HUC-12s with 0 masked px: {(nh == 0).sum()}, < 20 px: {(nh < 20).sum()} of {len(g)}; "
          f"median masked px per HUC-12 {nh.median():.0f}")
    print(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
