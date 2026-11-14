"""Fetch USDA CDL 'cropland' (30 m, EPSG:5070) from Microsoft Planetary Computer for every year
it has (2008-2021 at time of writing) and mosaic the tile window to data/raw/cdl/cdl_<year>_tile.tif.

Usage: .venv/bin/python pipeline/cdl_fetch_pc.py
"""
import os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import from_bounds
import pystac_client, planetary_computer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdl_common import ROOT, region, tile_bbox_5070  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw", "cdl")
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def items_by_year():
    c = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    s = c.search(collections=["usda-cdl"], bbox=region()["tile_bounds_lonlat"],
                 query={"usda_cdl:type": {"eq": "cropland"}})
    out = {}
    for it in s.items():
        y = int(it.properties["start_datetime"][:4])
        out.setdefault(y, []).append(it)
    return out


def mosaic_year(year, items):
    dst_path = os.path.join(RAW, f"cdl_{year}_tile.tif")
    if os.path.exists(dst_path):
        return year, "cached"
    bb = tile_bbox_5070()
    W = int(round((bb[2] - bb[0]) / 30)); H = int(round((bb[3] - bb[1]) / 30))
    tr = from_origin(bb[0], bb[3], 30, 30)
    mos = np.zeros((H, W), np.uint8)
    used = []
    for it in items:
        for k in range(5):
            try:
                href = planetary_computer.sign(it.assets["cropland"].href)
                with rasterio.open(href) as src:
                    assert src.crs.to_epsg() == 5070
                    b = src.bounds
                    if b.right <= bb[0] or b.left >= bb[2] or b.top <= bb[1] or b.bottom >= bb[3]:
                        break
                    win = from_bounds(*bb, transform=src.transform)
                    assert abs(win.col_off - round(win.col_off)) < 1e-6 and abs(win.row_off - round(win.row_off)) < 1e-6, win
                    win = win.round_offsets().round_lengths()
                    arr = src.read(1, window=win, boundless=True, fill_value=0, out_shape=(H, W))
                m = (mos == 0) & (arr != 0)
                mos[m] = arr[m]
                used.append(it.id)
                break
            except Exception as e:
                print(f"  {year} {it.id} retry {k}: {e}", flush=True)
                time.sleep(3 * (k + 1))
        else:
            raise RuntimeError(f"failed {it.id}")
    prof = dict(driver="GTiff", height=H, width=W, count=1, dtype="uint8", crs="EPSG:5070", transform=tr,
                compress="deflate", tiled=True, nodata=0)
    tmp = dst_path + ".tmp"
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(mos, 1)
        dst.update_tags(source="planetary-computer usda-cdl cropland: " + ",".join(sorted(used)))
    os.replace(tmp, dst_path)
    return year, f"{len(used)} items, zero-frac={np.mean(mos == 0):.4f}"


def main():
    os.makedirs(RAW, exist_ok=True)
    if all(os.path.exists(os.path.join(RAW, f"cdl_{y}_tile.tif")) for y in range(2008, 2022)):
        print("all cached (cdl_2008..2021_tile.tif); skipping STAC search")
        return
    by = items_by_year()
    print("PC years:", sorted(by))
    with ThreadPoolExecutor(8) as ex:
        for y, msg in ex.map(lambda kv: mosaic_year(*kv), sorted(by.items())):
            print(y, msg, flush=True)


if __name__ == "__main__":
    main()
