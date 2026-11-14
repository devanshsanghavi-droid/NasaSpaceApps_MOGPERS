"""Shared helpers for the drought-bill `cdl` module.

Sampling lattice: a fixed grid of points in EPSG:5070 every SPACING m. Every point sits exactly on the centre of
a CDL 30 m pixel (CDL national grid pixel edges are at 15 m mod 30, so centres are at 0 mod 30 and any multiple
of 240 m is a pixel centre). The same lattice is used for every year, so per-point crop sequences are valid.
"""
import os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "cdl")
PROC = os.path.join(ROOT, "data", "processed")
WEBDATA = os.path.join(ROOT, "web", "data")
CENSUS_ZIP = os.path.join(ROOT, "data", "raw", "census", "cb_2023_us_county_500k.zip")
CENSUS_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
UA = {"User-Agent": "drought-bill-hackathon"}

STATES = {"19": "IA", "31": "NE", "20": "KS", "29": "MO", "17": "IL", "46": "SD", "27": "MN"}
YEARS = list(range(2008, 2025))          # 2008..2024 (17 years)
PC_YEARS = list(range(2008, 2022))       # on Planetary Computer
NASS_YEARS = [2022, 2023, 2024]          # not on PC -> official NASS national release
FOCUS_FIPS = "19149"                     # Plymouth County, Iowa

SPACING = 240  # m (= 8 CDL pixels)
# region bbox (EPSG:5070) of the 667 counties: [-671178, 1453108, 731262, 2930681]; snapped outward to SPACING
X0 = -671280            # x of lattice column 0 (multiple of 240)
YTOP = 2930880          # y of lattice row 0 (multiple of 240)
NX = int(np.ceil((731262 - X0) / SPACING)) + 1
NY = int(np.ceil((YTOP - 1453108) / SPACING)) + 1


def lattice_xy():
    xs = X0 + SPACING * np.arange(NX, dtype=np.int64)
    ys = YTOP - SPACING * np.arange(NY, dtype=np.int64)
    return xs, ys


def lattice_index_for_raster(transform, height, width):
    """For a north-up 30 m raster on the CDL national grid, return (lat_rows, lat_cols, px_rows, px_cols):
    lattice row/col indices covered by the raster and the matching pixel row/col indices."""
    a, b, x0, d, e, y0 = transform.a, transform.b, transform.c, transform.d, transform.e, transform.f
    assert abs(a - 30) < 1e-9 and abs(e + 30) < 1e-9 and b == 0 and d == 0, transform
    assert abs(((x0 - 15) % 30)) < 1e-6 and abs(((y0 - 15) % 30)) < 1e-6, ("not on CDL grid", x0, y0)
    xs, ys = lattice_xy()
    pc = np.round((xs - (x0 + 15)) / 30).astype(np.int64)   # pixel col whose centre == lattice x
    pr = np.round(((y0 - 15) - ys) / 30).astype(np.int64)
    okc = (pc >= 0) & (pc < width)
    okr = (pr >= 0) & (pr < height)
    lc = np.nonzero(okc)[0]
    lr = np.nonzero(okr)[0]
    return lr, lc, pr[lr], pc[lc]


def load_counties():
    """667 counties of the 7 states, Census CB 2023 500k, as a GeoDataFrame (EPSG:4269)."""
    import geopandas as gpd
    if not os.path.exists(CENSUS_ZIP):
        import requests
        os.makedirs(os.path.dirname(CENSUS_ZIP), exist_ok=True)
        r = requests.get(CENSUS_URL, headers=UA, timeout=300)
        r.raise_for_status()
        tmp = CENSUS_ZIP + ".tmp"
        open(tmp, "wb").write(r.content)
        os.replace(tmp, CENSUS_ZIP)
    g = gpd.read_file("zip://" + CENSUS_ZIP)
    g = g[g.STATEFP.isin(list(STATES))].copy()
    g["fips"] = g.GEOID.astype(str).str.zfill(5)
    return g.reset_index(drop=True)


def lattice_path(year):
    return os.path.join(RAW, f"lattice_{year}.npy")


def focus_path(year):
    return os.path.join(RAW, "focus", f"cdl_{year}_19149.tif")


def focus_bbox_5070():
    """Plymouth County bbox in EPSG:5070 with a 300 m buffer, snapped outward to CDL pixel edges (15 mod 30)."""
    x0, y0, x1, y1 = (-51984.37, 2173611.32, 11498.05, 2212666.47)
    b = 300

    def lo(v):
        return float(np.floor((v - 15) / 30) * 30 + 15)

    def hi(v):
        return float(np.ceil((v - 15) / 30) * 30 + 15)
    return lo(x0 - b), lo(y0 - b), hi(x1 + b), hi(y1 + b)


def write_focus_tif(arr, transform, year, src_desc):
    import rasterio
    p = focus_path(year)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    prof = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="uint8",
                crs="EPSG:5070", transform=transform, compress="deflate", tiled=True, nodata=0)
    tmp = p + ".tmp.tif"
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(arr, 1)
        dst.update_tags(source=src_desc)
    os.replace(tmp, p)
