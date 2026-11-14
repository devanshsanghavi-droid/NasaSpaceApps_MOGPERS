"""USDA Cropland Data Layer (30 m, EPSG:5070) clipped to the union bbox of both basins, 2016-2025.

Output: data/raw/cdl/cdl_<year>_basins.tif (uint8, deflate, tiled, nodata=0) + empty sentinel DONE_<year>
once the clip is fully written. Every year shares one grid (same transform and shape), snapped to the CDL
national 30 m grid (pixel edges at 15 m mod 30 in EPSG:5070).

- 2022-2025: official NASS national zips (Planetary Computer `usda-cdl` stops at 2021). Downloaded with parallel
  HTTP range requests, the GeoTIFF is extracted, the window clipped, then the zip and the national tif are deleted
  (never more than one national file on disk).
- 2016-2021: Planetary Computer STAC `usda-cdl` (query usda_cdl:type=cropland), tiles mosaicked onto the grid.

Usage: python3 pipeline/p05_cdl_fetch.py [years...] [--keep] [--check]
"""
import shutil
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

from common import RAW, PROC, STAC_URL, UA, _session

OUT = RAW / "cdl"
ZDIR = OUT / "nass_tmp"
NASS_URL = "https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/{y}_30m_cdls.zip"
NASS_YEARS = [2022, 2023, 2024, 2025]
PC_YEARS = [2016, 2017, 2018, 2019, 2020, 2021]
BUF = 1500.0  # m buffer around the union of both basins
NTHREADS = 6  # network threads (contract: <= 6)
CHUNK = 32 * 2**20


def grid():
    """(transform, H, W) of the common clip grid in EPSG:5070."""
    df = pd.read_parquet(PROC / "huc12.parquet")
    g = gpd.GeoSeries.from_wkb(df.geometry, crs=4326).to_crs(5070)
    x0, y0, x1, y1 = g.total_bounds
    lo = lambda v: np.floor((v - 15) / 30) * 30 + 15  # noqa: E731
    hi = lambda v: np.ceil((v - 15) / 30) * 30 + 15  # noqa: E731
    x0, y0, x1, y1 = lo(x0 - BUF), lo(y0 - BUF), hi(x1 + BUF), hi(y1 + BUF)
    W, H = int(round((x1 - x0) / 30)), int(round((y1 - y0) / 30))
    return from_origin(x0, y1, 30, 30), H, W


def aligned_window(src, tr, H, W):
    """Integer window of `src` matching the grid (asserts pixel alignment, no resampling)."""
    assert src.crs.to_epsg() == 5070, src.crs
    st = src.transform
    assert abs(st.a - 30) < 1e-9 and abs(st.e + 30) < 1e-9, st
    col = (tr.c - st.c) / 30.0
    row = (st.f - tr.f) / 30.0
    assert abs(col - round(col)) < 1e-6 and abs(row - round(row)) < 1e-6, (col, row, st)
    return Window(int(round(col)), int(round(row)), W, H)


def write_clip(arr, tr, path, desc):
    prof = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="uint8", crs="EPSG:5070",
                transform=tr, compress="deflate", tiled=True, blockxsize=512, blockysize=512, nodata=0)
    tmp = path.with_suffix(".tif.tmp")
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(arr, 1)
        dst.update_tags(source=desc)
    tmp.replace(path)


def out_path(y):
    return OUT / f"cdl_{y}_basins.tif"


def done_path(y):
    return OUT / f"DONE_{y}"


# ---------------------------------------------------------------- NASS national zips
def fetch_range(url, path, start, end, tries=8):
    for k in range(tries):
        try:
            with _session.get(url, headers={**UA, "Range": f"bytes={start}-{end}"}, timeout=180, stream=True) as r:
                if r.status_code != 206:
                    raise IOError(f"HTTP {r.status_code}")
                n = 0
                with open(path, "r+b") as f:
                    f.seek(start)
                    for b in r.iter_content(4 * 2**20):
                        f.write(b)
                        n += len(b)
            if n != end - start + 1:
                raise IOError(f"short read {n} vs {end - start + 1}")
            return n
        except Exception as e:
            print(f"  retry {k} @{start}: {e}", flush=True)
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"range {start}-{end} failed after {tries} tries")


def download_zip(year):
    url = NASS_URL.format(y=year)
    z = ZDIR / f"{year}_30m_cdls.zip"
    if (ZDIR / f"{year}.zipdone").exists():
        return z
    h = _session.head(url, timeout=60)
    size = int(h.headers["content-length"])
    with open(z, "wb") as f:
        f.truncate(size)
    ranges = [(s, min(s + CHUNK, size) - 1) for s in range(0, size, CHUNK)]
    t0 = time.time()
    with ThreadPoolExecutor(NTHREADS) as ex:
        tot = sum(ex.map(lambda r: fetch_range(url, z, *r), ranges))
    assert tot == size
    print(f"{year}: downloaded {size / 1e9:.2f} GB in {time.time() - t0:.0f}s", flush=True)
    (ZDIR / f"{year}.zipdone").touch()
    return z


def nass_year(year, tr, H, W, keep=False):
    ZDIR.mkdir(parents=True, exist_ok=True)
    z = download_zip(year)
    with zipfile.ZipFile(z) as zf:
        tifs = [m for m in zf.namelist() if m.lower().endswith(".tif")]
        print(f"{year}: zip members {zf.namelist()}", flush=True)
        assert len(tifs) == 1, tifs
        t0 = time.time()
        xdir = ZDIR / f"x{year}"
        tifp = zf.extract(tifs[0], xdir)
        print(f"{year}: extracted in {time.time() - t0:.0f}s", flush=True)
    with rasterio.open(tifp) as src:
        win = aligned_window(src, tr, H, W)
        arr = src.read(1, window=win, boundless=True, fill_value=0)
        print(f"{year}: national {src.width}x{src.height} origin ({src.transform.c},{src.transform.f}) "
              f"window {win}", flush=True)
    write_clip(arr, tr, out_path(year), NASS_URL.format(y=year))
    done_path(year).touch()
    print(f"{year}: wrote {out_path(year).name} zero-frac={np.mean(arr == 0):.4f}", flush=True)
    if not keep:
        shutil.rmtree(xdir, ignore_errors=True)
        z.unlink(missing_ok=True)
        (ZDIR / f"{year}.zipdone").unlink(missing_ok=True)


# ---------------------------------------------------------------- Planetary Computer 2016-2021
def pc_items(years, tr, H, W):
    import planetary_computer
    import pystac_client
    from pyproj import Transformer
    x0, y1 = tr.c, tr.f
    x1, y0 = x0 + 30 * W, y1 - 30 * H
    t = Transformer.from_crs(5070, 4326, always_xy=True)
    xs = np.r_[np.linspace(x0, x1, 50), np.linspace(x0, x1, 50), np.full(50, x0), np.full(50, x1)]
    ys = np.r_[np.full(50, y0), np.full(50, y1), np.linspace(y0, y1, 50), np.linspace(y0, y1, 50)]
    lon, lat = t.transform(xs, ys)
    c = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    out = {}
    for y in years:
        s = c.search(collections=["usda-cdl"], bbox=[lon.min(), lat.min(), lon.max(), lat.max()],
                     datetime=f"{y}-01-01/{y}-12-31", query={"usda_cdl:type": {"eq": "cropland"}})
        out[y] = [it for it in s.items() if int(it.properties["start_datetime"][:4]) == y]
    return out


def read_pc_tile(it, tr, H, W):
    import planetary_computer
    x0, y1 = tr.c, tr.f
    x1, y0 = x0 + 30 * W, y1 - 30 * H
    for k in range(6):
        try:
            href = planetary_computer.sign(it.assets["cropland"].href)
            with rasterio.open(href) as src:
                b = src.bounds
                if b.right <= x0 or b.left >= x1 or b.top <= y0 or b.bottom >= y1:
                    return None
                win = aligned_window(src, tr, H, W)
                # read only the intersecting part
                c0, r0 = max(win.col_off, 0), max(win.row_off, 0)
                c1, r1 = min(win.col_off + W, src.width), min(win.row_off + H, src.height)
                arr = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0))
                return (r0 - win.row_off, c0 - win.col_off, arr)
        except Exception as e:
            print(f"  {it.id} retry {k}: {e}", flush=True)
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"failed to read {it.id}")


def pc_year(year, items, tr, H, W):
    mos = np.zeros((H, W), np.uint8)
    used = []
    with ThreadPoolExecutor(NTHREADS) as ex:
        for it, res in zip(items, ex.map(lambda i: read_pc_tile(i, tr, H, W), items)):
            if res is None:
                continue
            r, c, arr = res
            sub = mos[r:r + arr.shape[0], c:c + arr.shape[1]]
            m = (sub == 0) & (arr != 0)
            sub[m] = arr[m]
            used.append(it.id)
    write_clip(mos, tr, out_path(year), "planetary-computer usda-cdl cropland: " + ",".join(sorted(used)))
    done_path(year).touch()
    print(f"{year}: PC {len(used)} tiles -> {out_path(year).name} zero-frac={np.mean(mos == 0):.4f}", flush=True)


# ---------------------------------------------------------------- checks
def check():
    tr, H, W = grid()
    print(f"grid: origin ({tr.c},{tr.f}) {W}x{H} px")
    for y in PC_YEARS + NASS_YEARS:
        p = out_path(y)
        if not p.exists():
            print(y, "missing")
            continue
        with rasterio.open(p) as s:
            ok = s.transform == tr and (s.height, s.width) == (H, W)
            print(y, "grid ok" if ok else f"GRID MISMATCH {s.transform} {s.shape}", "done" if done_path(y).exists() else "")
    if out_path(2021).exists() and out_path(2022).exists():
        a = rasterio.open(out_path(2021)).read(1)
        b = rasterio.open(out_path(2022)).read(1)
        da, db = (a >= 121) & (a <= 124), (b >= 121) & (b <= 124)
        for dx, dy in [(0, 0), (1, 0), (0, 1), (-1, 0), (0, -1)]:
            bb = np.roll(np.roll(db, dy, 0), dx, 1)
            iou = (da & bb).sum() / max((da | bb).sum(), 1)
            print(f"developed IoU 2021(PC) vs 2022(NASS) shift dx={dx} dy={dy}: {iou:.3f}")


def main():
    args = sys.argv[1:]
    if "--check" in args:
        return check()
    keep = "--keep" in args
    years = [int(a) for a in args if a.isdigit()] or (NASS_YEARS + PC_YEARS)
    OUT.mkdir(parents=True, exist_ok=True)
    tr, H, W = grid()
    print(f"grid: origin ({tr.c},{tr.f}) {W}x{H} px = {W * 30 / 1e3:.1f} x {H * 30 / 1e3:.1f} km", flush=True)
    todo = [y for y in years if not (done_path(y).exists() and out_path(y).exists())]
    for y in years:
        if y not in todo:
            print(f"{y}: cached")
    for y in [y for y in todo if y in NASS_YEARS]:
        nass_year(y, tr, H, W, keep=keep)
    pcy = [y for y in todo if y in PC_YEARS]
    if pcy:
        items = pc_items(pcy, tr, H, W)
        for y in pcy:
            print(f"{y}: {len(items[y])} PC items", flush=True)
            pc_year(y, items[y], tr, H, W)
    check()


if __name__ == "__main__":
    main()
