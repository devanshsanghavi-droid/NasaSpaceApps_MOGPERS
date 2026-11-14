"""COUNTERFIELD context module: county polygons intersecting the HLS tile (simplified GeoJSON).

Source: US Census cartographic boundary counties 2023, 1:500k (cb_2023_us_county_500k.zip), cached in data/raw/census/.
Run: .venv/bin/python pipeline/context_counties.py
Output: data/counties.geojson  (EPSG:4326, one feature per county, property `fips` is the key)
  frac_in_tile / share_of_tile are computed against the exact HLS UTM square (region.json tile_bounds_utm, EPSG:32615).
"""
import json
from pathlib import Path

import geopandas as gpd
import requests
import shapely
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "census"
RAW.mkdir(parents=True, exist_ok=True)
URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
ZIP = RAW / "cb_2023_us_county_500k.zip"
OUT = ROOT / "data" / "counties.geojson"
UA = {"User-Agent": "counterfield-hackathon"}


def get_zip():
    if not ZIP.exists() or ZIP.stat().st_size < 1_000_000:
        r = requests.get(URL, headers=UA, timeout=300)
        r.raise_for_status()
        ZIP.write_bytes(r.content)
    return ZIP


def load_us_counties():
    """All US counties (EPSG:4269 -> 4326). Also used by context_climate.py for the analog state lookup."""
    g = gpd.read_file(f"zip://{get_zip()}")
    return g.to_crs(4326)


def main():
    region = json.loads((ROOT / "data" / "region.json").read_text())
    # exact tile = the HLS UTM square (EPSG:32615); the lon/lat bbox slightly over-covers it
    tile_utm = box(*region["tile_bounds_utm"])
    g = load_us_counties()
    g_utm = g.to_crs(region["crs"])
    keep = g_utm.intersects(tile_utm) & (g_utm.intersection(tile_utm).area > 1.0)  # drop edge-touch slivers < 1 m2
    sel = g[keep].copy()
    sel_utm = g_utm[keep]
    # shares from the exact UTM-square intersection (UTM 15N scale error < 0.1% here, cancels in ratios)
    inter = sel_utm.geometry.intersection(tile_utm).area
    sel["area_km2"] = (sel.to_crs(5070).geometry.area / 1e6).round(1)  # county area in equal-area CRS
    sel["frac_in_tile"] = (inter / sel_utm.geometry.area).round(4)
    sel["share_of_tile"] = (inter / tile_utm.area).round(4)
    # topology-preserving simplification (~100 m)
    geoms = shapely.coverage_simplify(sel.geometry.values, tolerance=0.001)
    sel = sel.set_geometry(gpd.GeoSeries(geoms, index=sel.index, crs=4326))
    out = sel.rename(columns={"GEOID": "fips", "NAME": "name", "STUSPS": "state_abbr", "STATE_NAME": "state_name",
                              "STATEFP": "statefp"})
    out = out[["fips", "name", "state_abbr", "state_name", "statefp", "area_km2", "frac_in_tile", "share_of_tile",
               "geometry"]].sort_values("fips")
    out["geometry"] = out.geometry.apply(lambda geom: shapely.set_precision(geom, 1e-5))
    OUT.write_text(out.to_json(drop_id=True))
    print(out.drop(columns="geometry").to_string(index=False))
    print(f"{len(out)} counties; sum share_of_tile={out.share_of_tile.sum():.3f}; wrote {OUT} ({OUT.stat().st_size/1e3:.0f} kB)")


if __name__ == "__main__":
    main()
