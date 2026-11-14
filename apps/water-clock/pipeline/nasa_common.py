"""Shared helpers for the nasa (water & climate) modules: paths, region counties, HTTP.

Region = 26/27 western Kansas counties in GMD1/GMD3/GMD4 (list from CONTRACTS.md).
County polygons/centroids from the Census cartographic boundary file
https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip (cached in data/raw/census/).
Centroids are computed in an equal-area projection (EPSG:5070) and returned as lon/lat.
"""
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
PROC.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "water-clock-hackathon"}
BBOX = (-102.06, 36.99, -99.55, 40.01)          # region bbox (W, S, E, N)
HP_BBOX = (-104.5, 34.0, -97.5, 42.0)           # wider High Plains context box for maps

GMD = {
    "GMD1": {"071": "Greeley", "203": "Wichita", "171": "Scott", "101": "Lane"},
    "GMD3": {"075": "Hamilton", "093": "Kearny", "055": "Finney", "069": "Gray", "057": "Ford", "187": "Stanton",
             "067": "Grant", "081": "Haskell", "129": "Morton", "189": "Stevens", "175": "Seward", "119": "Meade"},
    "GMD4": {"023": "Cheyenne", "153": "Rawlins", "039": "Decatur", "181": "Sherman", "193": "Thomas",
             "179": "Sheridan", "199": "Wallace", "109": "Logan", "063": "Gove", "065": "Graham"},
}
COUNTY_GMD = {"20" + c: g for g, d in GMD.items() for c in d}
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"


def http_get(url, params=None, tries=5, timeout=180, stream=False):
    last = None
    for k in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout, stream=stream)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {r.url}: {r.text[:300]}")
            if r.status_code in (400, 403, 404):
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(3 * (k + 1))
    raise last


def region_counties():
    """GeoDataFrame of region counties: fips, name, gmd, geometry (EPSG:4326), lon, lat (equal-area centroid)."""
    import geopandas as gpd
    z = RAW / "census" / "cb_2023_us_county_500k.zip"
    if not z.exists():
        z.parent.mkdir(parents=True, exist_ok=True)
        z.write_bytes(http_get(COUNTY_URL).content)
    g = gpd.read_file(f"zip://{z}")
    g = g[g.GEOID.isin(COUNTY_GMD)].copy()
    g["fips"] = g.GEOID
    g["name"] = g.NAME
    g["gmd"] = g.fips.map(COUNTY_GMD)
    g = g.to_crs(4326)
    c = g.to_crs(5070).geometry.centroid.to_crs(4326)
    g["lon"], g["lat"] = c.x.round(4), c.y.round(4)
    return g[["fips", "name", "gmd", "lon", "lat", "geometry"]].sort_values("fips").reset_index(drop=True)


if __name__ == "__main__":
    g = region_counties()
    print(len(g), "counties")
    print(g.drop(columns="geometry").to_string())
