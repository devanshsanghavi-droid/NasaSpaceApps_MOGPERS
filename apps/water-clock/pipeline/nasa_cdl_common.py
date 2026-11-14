"""Shared helpers for the nasa land modules (CDL, MODIS ET, HLS).

Region grid = the USDA CDL national 30 m grid (EPSG:5070 Albers, pixel edges at 15 m mod 30 m), clipped to the
26 region counties (Census cb_2023_us_county_500k polygons, via nasa_common.region_counties) + 1 km buffer.
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasa_common import RAW, PROC, ROOT, region_counties  # noqa: E402,F401

CDL_RAW = RAW / "cdl"
CDL_YEARS = list(range(2008, 2025))
PIX_AC = 900.0 / 4046.8564224          # one 30 m CDL pixel = 900 m2 = 0.2224 acres
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.zip",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="2",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    GDAL_HTTP_TIMEOUT="120",
    GDAL_HTTP_USERAGENT="water-clock-hackathon",
    GDAL_NUM_THREADS="2",
)

# CDL code -> crop class used in cdl_county.parquet (codes from the CDL legend, USDA NASS)
CLASS_CODES = {
    "corn": [1, 12, 13],                       # corn, sweet corn, pop/orn corn
    "sorghum": [4],
    "soybeans": [5],
    "cotton": [2],
    "winter_wheat": [24],
    "alfalfa": [36],
    "fallow_idle": [61],                       # Fallow/Idle Cropland
    "grass_pasture": [62, 171, 176, 181],      # Pasture/Grass (old), Grassland Herbaceous, Grassland/Pasture, Pasture/Hay
    "double_crop": [26, 225, 226, 236, 237, 238, 239, 240, 241, 254],  # double-crop combos (mostly winter wheat/soy or /sorghum)
    "shrubland": [152, 64],                    # Shrubland (rangeland in SW Kansas)
    "developed": [82, 121, 122, 123, 124],
    "water_wetland": [83, 111, 87, 190, 195],
    "forest": [63, 141, 142, 143],
    "barren": [65, 131],
}
CROP_CLASSES = ["corn", "sorghum", "winter_wheat", "soybeans", "cotton", "alfalfa", "fallow_idle", "grass_pasture",
                "double_crop", "other_crops", "shrubland", "developed", "water_wetland", "forest", "barren", "nodata"]


def code_to_class_lut():
    """uint8 LUT: CDL code (0..255) -> index into CROP_CLASSES. Codes not listed and in 1..60, 66..80, 200..255 -> other_crops."""
    lut = np.full(256, CROP_CLASSES.index("other_crops"), np.uint8)
    lut[0] = CROP_CLASSES.index("nodata")
    for k, codes in CLASS_CODES.items():
        lut[codes] = CROP_CLASSES.index(k)
    # non-crop codes not otherwise assigned (e.g. 81 clouds, 88 nonag/undefined, 92 aquaculture, 112 snow) -> barren/other
    for c in [81, 88, 92, 112]:
        lut[c] = CROP_CLASSES.index("barren")
    return lut


def region_grid(buf=1000.0):
    """(bounds, transform, width, height) of the region window on the CDL 30 m grid in EPSG:5070."""
    from rasterio.transform import from_origin
    g = region_counties().to_crs(5070)
    x0, y0, x1, y1 = g.total_bounds

    def lo(v):
        return np.floor((v - 15) / 30) * 30 + 15

    def hi(v):
        return np.ceil((v - 15) / 30) * 30 + 15
    bb = (lo(x0 - buf), lo(y0 - buf), hi(x1 + buf), hi(y1 + buf))
    W = int(round((bb[2] - bb[0]) / 30))
    H = int(round((bb[3] - bb[1]) / 30))
    return bb, from_origin(bb[0], bb[3], 30, 30), W, H


def cdl_path(year):
    return CDL_RAW / f"cdl_{year}_region.tif"


def county_raster():
    """uint8 raster on the region grid: 0 = outside, i+1 = county index i in region_counties() order. Cached."""
    import rasterio
    from rasterio.features import rasterize
    p = CDL_RAW / "county_index_30m.tif"
    g = region_counties()
    if not p.exists():
        bb, tr, W, H = region_grid()
        gg = g.to_crs(5070)
        arr = rasterize([(geom, i + 1) for i, geom in enumerate(gg.geometry)], out_shape=(H, W), transform=tr,
                        fill=0, dtype="uint8")
        prof = dict(driver="GTiff", height=H, width=W, count=1, dtype="uint8", crs="EPSG:5070", transform=tr,
                    compress="deflate", tiled=True, nodata=0)
        with rasterio.open(p, "w", **prof) as dst:
            dst.write(arr, 1)
    with rasterio.open(p) as src:
        return src.read(1), g


def retry(fn, tries=6, wait=3):
    last = None
    for k in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"   retry {k}: {str(e)[:200]}", flush=True)
            time.sleep(wait * (k + 1))
    raise last
