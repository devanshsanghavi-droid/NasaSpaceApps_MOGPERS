"""HLS v2 (NASA Harmonized Landsat Sentinel-2) per-cell reflectance indices over the focus area.

Source: Microsoft Planetary Computer STAC `hls2-l30` (Landsat 8/9 OLI) and `hls2-s30` (Sentinel-2 A/B/C MSI), MGRS tile
from data/processed/focus_area.json (15TUG), 2020-01-01..today (PC HLS v2 starts 2020), eo:cloud_cover <= 80.

For each granule we windowed-read (focus bbox only, native 30 m) Fmask, green (B03), red (B04), NIR (L30 B05 / S30 B8A),
SWIR1 (L30 B06 / S30 B11) and SWIR2 (L30 B07 / S30 B12). A pixel is clear when Fmask bits 1-4 (cloud, adjacent to
cloud/shadow, cloud shadow, snow/ice) are all 0, Fmask != 255 (fill) and every reflectance is > 0 and != -9999.
For S30 granules from Oct 1 to May 31 (month 10-12 or 1-5), pixels with Fmask aerosol level bits 6-7 = 11 (high
aerosol) are also masked: in the dormant season high-aerosol S30 surface reflectance reads green (S30 2024-05-03:
99.8% of clear pixels high-aerosol and 67% of fields "living", between 3% and 2% scenes; the 33 Oct-May S30 scenes
with > 90% high-aerosol pixels had a median field living share of 0.32 vs 0.02 for the rest). L30 is NOT masked:
its high-aerosol flag covers 40-70% of clear pixels in most Dec-Feb scenes (snow-adjacent, bright soil), but those
pixels are not green-biased (the 12 Oct-May L30 scenes with > 90% high-aerosol pixels: median field NDVI 0.216,
living share 0.01), and masking them deleted every Dec 2022-Feb 2023 L30 scene (a > 120-day gap in crop year 2023).
Jun-Sep is never masked (canopies sit far above the 0.30 threshold).
Reflectance = DN * 0.0001. Pixel indices: NDVI = (NIR-red)/(NIR+red); NDTI = (SWIR1-SWIR2)/(SWIR1+SWIR2);
GCVI = NIR/green - 1 (clipped to [-1, 20]).

Pixels are averaged into the 400 m EPSG:5070 field-cell grid (CONTRACTS.md): every cell whose centre lies inside the
focus HUC-12s; only pixels whose centre is >= 30 m inside the cell are used (drops field edges, roads, ditches).
Per granule the cache data/raw/hls/g/<item_id>.npz holds, for cells with >= 1 clear pixel: cell index, n_clear,
mean NDVI/NDTI/GCVI and the pixel share with NDVI >= 0.25/0.30/0.35. Cache version 2 (all Oct-May granules) also
holds `grid` (uint8, cells x len(T_GRID)): the count of clear pixels with NDVI >= each threshold 0.200..0.450 step
0.005, so p12 can apply the S30 -> L30 dormant-season NDVI offset before thresholding. Version-1 caches of Oct-May
granules (or caches made under another aerosol rule) are re-read automatically. The npz is written last, so the run is resumable.
The cell grid is cached in data/raw/hls/cells.npz (p12 reuses it).

Usage: python3 pipeline/p11_hls_fetch.py [--limit N] [--workers 6] [--offline]
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import geopandas as gpd
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from pyproj import Transformer
from rasterio.windows import Window
from shapely import contains_xy
from shapely.ops import unary_union

from common import PROC
from fields_common import CELL, GDAL_ENV, HLS_RAW, STAC_URL, load_focus, unsigned

BANDS = {"L30": dict(green="B03", red="B04", nir="B05", swir1="B06", swir2="B07"),
         "S30": dict(green="B03", red="B04", nir="B8A", swir1="B11", swir2="B12")}
GDIR = HLS_RAW / "g"
ITEMS = HLS_RAW / "items.json"
CELLS = HLS_RAW / "cells.npz"
START = "2020-01-01"
INNER = 30.0       # pixel centre must be >= this far inside the cell edge (m)
MIN_CLEAR_SHARE = 0.005  # skip band reads if < 0.5% of focus pixels are clear
AER_MONTHS = (10, 11, 12, 1, 2, 3, 4, 5)  # Oct-May: cache v2 (threshold grid); S30 high-aerosol mask
AER_SENSORS = ("S30",)  # mask high-aerosol pixels (Fmask bits 6-7 == 3) for these sensors in AER_MONTHS
T_GRID = np.round(np.arange(0.200, 0.4501, 0.005), 3)  # NDVI thresholds for the per-cell count grid (cache v2)
CACHE_V = 2


def aer_window(it):
    return int(it["datetime"][5:7]) in AER_MONTHS


def aer_masked(it):
    return aer_window(it) and it["sensor"] in AER_SENSORS


def cache_ok(it):
    """Cached and, for Oct-May granules, at cache version 2 (threshold grid) with the current aerosol policy."""
    f = GDIR / f"{it['item_id']}.npz"
    if not f.exists():
        return False
    if not aer_window(it):
        return True
    meta = json.loads(str(np.load(f, allow_pickle=False)["meta"]))
    return meta.get("v", 1) >= CACHE_V and meta.get("aer_mask") == aer_masked(it)


def build_cells():
    """Field-cell grid (EPSG:5070, 400 m, origin at multiples of 400 m) with centres inside the focus HUC-12s, and
    the UTM pixel -> cell label raster for the HLS tile window."""
    foc = load_focus()
    d = pd.read_parquet(PROC / "huc12.parquet")
    g = gpd.GeoDataFrame(d.drop(columns="geometry"), geometry=gpd.GeoSeries.from_wkb(d.geometry), crs=4326)
    g = g[g.huc12.isin(foc["huc12s"])].to_crs(5070)
    x0, y0, x1, y1 = g.total_bounds
    cx = np.arange(np.floor(x0 / CELL), np.ceil(x1 / CELL)) * CELL + CELL / 2
    cy = np.arange(np.floor(y0 / CELL), np.ceil(y1 / CELL)) * CELL + CELL / 2
    X, Y = np.meshgrid(cx, cy)
    X, Y = X.ravel(), Y.ravel()
    huc = np.full(X.size, "", object)
    for h, geom in zip(g.huc12, g.geometry):
        m = contains_xy(geom, X, Y)
        huc[m] = h
    keep = huc != ""
    X, Y, huc = X[keep], Y[keep], huc[keep]
    order = np.lexsort((X, -Y))  # north->south, west->east
    X, Y, huc = X[order], Y[order], huc[order]
    col = np.round((X - CELL / 2) / CELL).astype(np.int32)
    row = np.round((Y - CELL / 2) / CELL).astype(np.int32)
    # UTM window of the tile (HLS grid origin 300000/4700040 for 15TUG; read from focus json)
    tb = foc["hls_tile_bounds_utm15n"]
    t5_utm = Transformer.from_crs(5070, 32615, always_xy=True)
    u = unary_union(g.geometry).buffer(200)
    ux, uy = t5_utm.transform(*np.array(u.exterior.coords).T)
    c0 = int(np.floor((min(ux) - tb[0]) / 30)); c1 = int(np.ceil((max(ux) - tb[0]) / 30))
    r0 = int(np.floor((tb[3] - max(uy)) / 30)); r1 = int(np.ceil((tb[3] - min(uy)) / 30))
    win = (c0, r0, c1 - c0, r1 - r0)
    px = tb[0] + (np.arange(c0, c1) + 0.5) * 30
    py = tb[3] - (np.arange(r0, r1) + 0.5) * 30
    PX, PY = np.meshgrid(px, py)
    t_utm5 = Transformer.from_crs(32615, 5070, always_xy=True)
    QX, QY = t_utm5.transform(PX.ravel(), PY.ravel())
    qc = np.floor(QX / CELL).astype(np.int64); qr = np.floor(QY / CELL).astype(np.int64)
    fx = QX - qc * CELL; fy = QY - qr * CELL
    inner = (fx >= INNER) & (fx <= CELL - INNER) & (fy >= INNER) & (fy <= CELL - INNER)
    key = {(int(c), int(r)): i for i, (c, r) in enumerate(zip(col, row))}
    lab = np.full(QX.size, -1, np.int32)
    idx = np.flatnonzero(inner)
    lab[idx] = [key.get((int(c), int(r)), -1) for c, r in zip(qc[idx], qr[idx])]
    lab = lab.reshape(PX.shape)
    npx = np.bincount(lab[lab >= 0], minlength=len(X))
    np.savez_compressed(CELLS, x5070=X, y5070=Y, col=col, row=row, huc12=huc.astype(str), label=lab,
                        window=np.array(win), npx=npx, tile_bounds=np.array(tb))
    print(f"cells: {len(X)} (centre in focus HUC-12s); window {win}; inner pixels per cell "
          f"min {npx.min()} median {int(np.median(npx))} max {npx.max()}", flush=True)
    return load_cells()


def load_cells():
    z = np.load(CELLS, allow_pickle=False)
    return {k: z[k] for k in z.files}


def list_items(offline=False):
    if offline and ITEMS.exists():
        return json.loads(ITEMS.read_text())
    foc = load_focus()
    tile = "T" + foc["hls_tile"]
    c = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    out = []
    for col, sensor in [("hls2-l30", "L30"), ("hls2-s30", "S30")]:
        s = c.search(collections=[col], bbox=foc["bbox_lonlat"], datetime=f"{START}/{dt.date.today()}",
                     query={"eo:cloud_cover": {"lte": 80}})
        for it in s.items():
            if f".{tile}." not in it.id:
                continue
            out.append(dict(item_id=it.id, collection=col, sensor=sensor, datetime=it.datetime.isoformat(),
                            platform=it.properties.get("platform"), cloud_cover=it.properties.get("eo:cloud_cover"),
                            assets={k: unsigned(it.assets[k].href) for k in list(BANDS[sensor].values()) + ["Fmask"]}))
    out.sort(key=lambda d: d["datetime"])
    ITEMS.write_text(json.dumps(out))
    return out


def read_win(href, win, tb, retries=6):
    """Windowed read of band 1 at native resolution; re-signs the SAS URL on each attempt (403 = expired token)."""
    last = None
    for a in range(retries):
        try:
            with rasterio.Env(**GDAL_ENV):
                with rasterio.open(planetary_computer.sign(unsigned(href))) as ds:
                    t = ds.transform
                    assert abs(t.c - tb[0]) < 1e-6 and abs(t.f - tb[3]) < 1e-6 and t.a == 30, t
                    return ds.read(1, window=Window(*win))
        except AssertionError:
            raise
        except Exception as e:
            last = e
            time.sleep(min(60, 2 ** a + np.random.rand() * 2))
    raise RuntimeError(f"read failed: {unsigned(href)} :: {last}")


def process(it, cells):
    t0 = time.time()
    win = tuple(int(v) for v in cells["window"]); tb = cells["tile_bounds"]
    lab = cells["label"]; ncell = len(cells["x5070"])
    m_in = lab >= 0
    fm = read_win(it["assets"]["Fmask"], win, tb)
    clear = (fm != 255) & ((fm & 0b11110) == 0) & m_in
    aer = (fm >> 6) & 0b11
    hi_aer = clear & (aer == 3)
    use_aer = aer_masked(it); v2 = aer_window(it)
    meta = dict(item_id=it["item_id"], datetime=it["datetime"], sensor=it["sensor"], platform=it["platform"],
                cloud_cover=it["cloud_cover"], n_px=int(m_in.sum()), n_fmask_clear=int(clear.sum()),
                n_snow=int(((fm != 255) & ((fm >> 4) & 1 == 1) & m_in).sum()),
                n_fill=int(((fm == 255) & m_in).sum()), n_high_aer=int(hi_aer.sum()),
                n_mod_aer=int((clear & (aer == 2)).sum()), aer_mask=bool(use_aer), v=CACHE_V if v2 else 1)
    if use_aer:
        clear &= ~hi_aer
    arrs = {}
    if clear.sum() >= MIN_CLEAR_SHARE * m_in.sum():
        for name, key in BANDS[it["sensor"]].items():
            arrs[name] = read_win(it["assets"][key], win, tb)
        ok = clear.copy()
        for v in arrs.values():
            ok &= (v > 0) & (v != -9999)
    else:
        ok = np.zeros_like(clear)
    meta["n_clear"] = int(ok.sum())
    res = dict(cell=np.zeros(0, np.int32), n_clear=np.zeros(0, np.uint16), ndvi=np.zeros(0, np.float32),
               ndti=np.zeros(0, np.float32), gcvi=np.zeros(0, np.float32), live25=np.zeros(0, np.float32),
               live30=np.zeros(0, np.float32), live35=np.zeros(0, np.float32))
    if v2:
        res["grid"] = np.zeros((0, len(T_GRID)), np.uint8)
    if ok.any():
        L = lab[ok]
        f = {k: v[ok].astype(np.float32) * 1e-4 for k, v in arrs.items()}
        ndvi = (f["nir"] - f["red"]) / (f["nir"] + f["red"])
        ndti = (f["swir1"] - f["swir2"]) / (f["swir1"] + f["swir2"])
        gcvi = np.clip(f["nir"] / f["green"] - 1.0, -1, 20)
        n = np.bincount(L, minlength=ncell)
        cell = np.flatnonzero(n)
        mean = lambda v: (np.bincount(L, weights=v, minlength=ncell)[cell] / n[cell]).astype(np.float32)  # noqa
        res = dict(cell=cell.astype(np.int32), n_clear=n[cell].astype(np.uint16), ndvi=mean(ndvi), ndti=mean(ndti),
                   gcvi=mean(gcvi), live25=mean((ndvi >= 0.25).astype(np.float32)),
                   live30=mean((ndvi >= 0.30).astype(np.float32)), live35=mean((ndvi >= 0.35).astype(np.float32)))
        if v2:  # counts of clear pixels per cell with NDVI >= each grid threshold (inner cells: <= 140 px)
            k = np.searchsorted(T_GRID, ndvi, side="right")  # ndvi >= T_GRID[j] for j < k
            h = np.zeros((ncell, len(T_GRID) + 1), np.int32)
            np.add.at(h, (L, k), 1)
            cum = h[:, ::-1].cumsum(1)[:, ::-1][:, 1:]  # cum[:, j] = #(k > j) = #(ndvi >= T_GRID[j])
            res["grid"] = cum[cell].astype(np.uint8)
    tmp = GDIR / f"{it['item_id']}.tmp.npz"
    np.savez_compressed(tmp, meta=np.array(json.dumps(meta)), **res)
    os.replace(tmp, GDIR / f"{it['item_id']}.npz")
    return meta, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--offline", action="store_true", help="reuse cached item list")
    ap.add_argument("--rebuild-cells", action="store_true")
    a = ap.parse_args()
    GDIR.mkdir(parents=True, exist_ok=True)
    cells = build_cells() if (a.rebuild_cells or not CELLS.exists()) else load_cells()
    items = list_items(a.offline)
    print(f"{len(items)} HLS items (L30 {sum(i['sensor'] == 'L30' for i in items)}, "
          f"S30 {sum(i['sensor'] == 'S30' for i in items)}), {items[0]['datetime'][:10]}..{items[-1]['datetime'][:10]}",
          flush=True)
    todo = [i for i in items if not cache_ok(i)]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(todo)} to process", flush=True)
    t0 = time.time(); done = 0; fails = []
    with ThreadPoolExecutor(min(a.workers, 6)) as ex:
        futs = {ex.submit(process, it, cells): it for it in todo}
        for f in as_completed(futs):
            it = futs[f]
            try:
                meta, dtm = f.result(); done += 1
                if done % 10 == 0 or done <= 5 or a.limit:
                    print(f"[{done}/{len(todo)}] {it['item_id']} cc={it['cloud_cover']} "
                          f"clear={meta['n_clear'] / max(meta['n_px'], 1):.0%} {dtm:.1f}s "
                          f"elapsed={time.time() - t0:.0f}s", flush=True)
            except Exception as e:
                fails.append((it["item_id"], repr(e)))
                print(f"FAIL {it['item_id']}: {e}", flush=True)
    print(f"done {done}, failed {len(fails)} in {time.time() - t0:.0f}s", flush=True)
    (HLS_RAW / "failures.json").write_text(json.dumps(fails, indent=1))
    n_cached = sum(1 for i in items if (GDIR / f"{i['item_id']}.npz").exists())
    print(f"cached granules: {n_cached}/{len(items)}")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
