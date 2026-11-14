"""Helpers for the `fields` module (focus area, HLS per-field living cover, field cells).

Adapted (copied, not imported) from shared/central_iowa_pipeline/pipeline/hls_common.py and cdl_fields.py.
"""
import json
import random
import time

import numpy as np
import planetary_computer
import rasterio
from rasterio.windows import Window, from_bounds

from common import RAW, PROC, STAC_URL  # noqa: F401

HLS_RAW = RAW / "hls"
FOCUS_JSON = PROC / "focus_area.json"
CELL = 400.0          # field cell size (m, EPSG:5070) per CONTRACTS.md
NDVI_LIVE = 0.30      # living-cover threshold per CONTRACTS.md (sensitivity 0.25 / 0.35)

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF",
    GDAL_HTTP_MAX_RETRY="4",
    GDAL_HTTP_RETRY_DELAY="2",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    GDAL_HTTP_MULTIPLEX="YES",
    GDAL_HTTP_TIMEOUT="60",
    GDAL_HTTP_USERAGENT="field-to-faucet-hackathon",
    GDAL_CACHEMAX=256,
    VSI_CACHE="FALSE",
)

# CDL code -> crop letter (same scheme as shared/central_iowa_pipeline/notes/cdl.md)
LETTER = {}
for _c in (1, 12, 13, 241):
    LETTER[_c] = "C"
for _c in (5, 239, 240):
    LETTER[_c] = "S"
for _c in (2, 3, 4, 6, 10, 11, 41, 42, 43):
    LETTER[_c] = "R"
for _c in (22, 23, 24, 26, 225, 236, 238):
    LETTER[_c] = "W"
for _c in (21, 25, 27, 28, 30, 205, 237, 254):
    LETTER[_c] = "O"
for _c in (36, 37, 58):
    LETTER[_c] = "H"
for _c in (59, 60, 62, 176):
    LETTER[_c] = "P"
ROW_LETTERS = set("CSR")
LETTER_LUT = np.full(256, ord("X"), np.uint8)
for _c, _l in LETTER.items():
    LETTER_LUT[_c] = ord(_l)
ROWCROP_LUT = np.isin(np.arange(256), [c for c, l in LETTER.items() if l in ROW_LETTERS])


def unsigned(href):
    return href.split("?")[0]


def read_window(href, bounds=None, ov_level=None, retries=6):
    """Read band 1 of a (PC-hosted) COG inside `bounds` (in the file CRS; clipped to the file extent). Re-signs the
    URL on every attempt so an expired SAS token (HTTP 403) is refreshed. Returns (array, window_transform, nodata);
    array is None if `bounds` does not intersect the file."""
    last = None
    for a in range(retries):
        try:
            url = planetary_computer.sign(unsigned(href))
            kw = {} if ov_level is None else {"OVERVIEW_LEVEL": ov_level}
            with rasterio.Env(**GDAL_ENV):
                with rasterio.open(url, **kw) as ds:
                    if bounds is None:
                        return ds.read(1), ds.transform, ds.nodata
                    win = from_bounds(*bounds, transform=ds.transform).round_offsets().round_lengths()
                    try:
                        win = win.intersection(Window(0, 0, ds.width, ds.height))
                    except Exception:  # no overlap
                        return None, None, ds.nodata
                    arr = ds.read(1, window=win)
                    return arr, ds.window_transform(win), ds.nodata
        except Exception as e:  # transient HTTP error or token expiry
            last = e
            time.sleep(min(60, 2 ** a + random.random() * 2))
    raise RuntimeError(f"read failed after {retries} tries: {unsigned(href)} :: {last}")


def pc_cdl_mosaic(year, bounds5070):
    """USDA CDL 'cropland' for `year` (<= 2021) from Planetary Computer `usda-cdl`, mosaicked on the CDL national
    30 m grid (EPSG:5070) over bounds5070 (snapped outward). Returns (uint8 array, transform)."""
    import pystac_client
    from pyproj import Transformer
    x0, y0, x1, y1 = bounds5070
    snap = lambda v, f: f((v - 15) / 30) * 30 + 15  # noqa: E731  (CDL pixel edges at 15 m mod 30)
    x0, y0, x1, y1 = snap(x0, np.floor), snap(y0, np.floor), snap(x1, np.ceil), snap(y1, np.ceil)
    t = Transformer.from_crs(5070, 4326, always_xy=True)
    lo, la = t.transform([x0, x1, x0, x1], [y0, y0, y1, y1])
    c = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    items = list(c.search(collections=["usda-cdl"], bbox=[min(lo), min(la), max(lo), max(la)],
                          datetime=f"{year}-01-01/{year}-12-31",
                          query={"usda_cdl:type": {"eq": "cropland"}}).items())
    if not items:
        raise RuntimeError(f"no usda-cdl cropland items for {year}")
    from rasterio.transform import from_origin
    W, H = int(round((x1 - x0) / 30)), int(round((y1 - y0) / 30))
    out = np.zeros((H, W), np.uint8)
    tr = from_origin(x0, y1, 30, 30)
    for it in items:
        arr, wtr, _ = read_window(it.assets["cropland"].href, (x0, y0, x1, y1))
        if arr is None:
            continue
        assert abs(wtr.a - 30) < 1e-6 and abs(((wtr.c - x0) / 30) - round((wtr.c - x0) / 30)) < 1e-6
        c0 = int(round((wtr.c - x0) / 30)); r0 = int(round((y1 - wtr.f) / 30))
        h, w = arr.shape
        rs, cs = max(r0, 0), max(c0, 0)
        re_, ce = min(r0 + h, H), min(c0 + w, W)
        sub = arr[rs - r0:re_ - r0, cs - c0:ce - c0]
        dst = out[rs:re_, cs:ce]
        m = (dst == 0) & (sub > 0)
        dst[m] = sub[m]
    return out, tr


def load_focus():
    return json.loads(FOCUS_JSON.read_text())
