"""Shared helpers for the cdl module."""
import json, os
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from pyproj import Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUF = 600.0  # metres of buffer around the tile in EPSG:5070


def region():
    with open(os.path.join(ROOT, "data", "region.json")) as f:
        return json.load(f)


def tile_bbox_5070(buf=BUF):
    r = region()
    x0, y0, x1, y1 = r["tile_bounds_utm"]
    t = Transformer.from_crs(32615, 5070, always_xy=True)
    xs = np.r_[np.linspace(x0, x1, 200), np.full(200, x1), np.linspace(x0, x1, 200), np.full(200, x0)]
    ys = np.r_[np.full(200, y0), np.linspace(y0, y1, 200), np.full(200, y1), np.linspace(y0, y1, 200)]
    X, Y = t.transform(xs, ys)
    # snap outward to the CDL national 30 m grid, whose pixel edges sit at 15 m (mod 30) in EPSG:5070
    def lo(v):
        return np.floor((v - 15) / 30) * 30 + 15

    def hi(v):
        return np.ceil((v - 15) / 30) * 30 + 15
    return (lo(X.min() - buf), lo(Y.min() - buf), hi(X.max() + buf), hi(Y.max() + buf))


def clip_to_tile(src_path, dst_path, src_desc=""):
    """Read the window covering the tile from a (national) CDL GeoTIFF and write a small GeoTIFF
    keeping the source pixel grid (no resampling)."""
    bb = tile_bbox_5070()
    with rasterio.open(src_path) as src:
        assert src.crs.to_epsg() == 5070, src.crs
        win = from_bounds(*bb, transform=src.transform).round_offsets().round_lengths()
        arr = src.read(1, window=win, boundless=True, fill_value=0)
        tr = src.window_transform(win)
        prof = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=arr.dtype,
                    crs=src.crs, transform=tr, compress="deflate", tiled=True, nodata=0)
    tmp = dst_path + ".tmp"
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(arr, 1)
        dst.update_tags(source=src_desc)
    os.replace(tmp, dst_path)
