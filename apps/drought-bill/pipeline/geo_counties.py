"""geo module: county table + simplified county / state GeoJSON for the 7 Drought Bill states.

Source: US Census cartographic boundary counties 2023, 1:500k
  https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip  (cached in data/raw/census/)
Adapted from shared/central_iowa_pipeline/pipeline/context_counties.py.

Run: /home/user/venv-db/bin/python pipeline/geo_counties.py
Outputs:
  data/processed/counties.parquet   fips, state_abbr, state_fips, name, lon, lat (interior point), land_km2, water_km2,
                                    area_km2 (equal-area EPSG:5070 polygon area)
  web/data/counties.geojson         simplified (topology-preserving coverage simplification), coords rounded to 4 dp,
                                    properties {fips, name, state}
  web/data/states.geojson           dissolved state outlines from the same simplified coverage, properties {state, state_fips, name}
"""
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "census"
RAW.mkdir(parents=True, exist_ok=True)
PROC = ROOT / "data" / "processed"
WEB = ROOT / "web" / "data"
PROC.mkdir(parents=True, exist_ok=True)
WEB.mkdir(parents=True, exist_ok=True)
URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
ZIP = RAW / "cb_2023_us_county_500k.zip"
UA = {"User-Agent": "drought-bill-hackathon"}
STATES = {"19": "IA", "31": "NE", "20": "KS", "29": "MO", "17": "IL", "46": "SD", "27": "MN"}
TOL = 0.0025  # degrees (~200-280 m) for coverage_simplify; tuned so counties.geojson < 1.5 MB


def get_zip():
    if not ZIP.exists() or ZIP.stat().st_size < 1_000_000:
        r = requests.get(URL, headers=UA, timeout=300)
        r.raise_for_status()
        ZIP.write_bytes(r.content)
    return ZIP


def round_coords(geom, nd=4):
    return shapely.set_precision(geom, 10 ** -nd)


def write_geojson(gdf, path, nd=4):
    """Write compact GeoJSON with coordinates rounded to nd decimals."""
    feats = []
    for _, row in gdf.iterrows():
        geom = shapely.geometry.mapping(row.geometry)
        props = {k: row[k] for k in gdf.columns if k != "geometry"}

        def rnd(c):
            if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
                return [round(float(c[0]), nd), round(float(c[1]), nd)]
            return [rnd(x) for x in c]

        geom = {"type": geom["type"], "coordinates": rnd(geom["coordinates"])}
        feats.append({"type": "Feature", "properties": props, "geometry": geom})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    return path.stat().st_size


def main():
    g = gpd.read_file(f"zip://{get_zip()}")
    g = g[g["STATEFP"].isin(STATES)].copy().to_crs(4326)
    g = g.sort_values("GEOID").reset_index(drop=True)
    # interior point: centroid (equal-area) if it falls inside the polygon, else point_on_surface
    ea = g.to_crs(5070)
    cen = ea.geometry.centroid
    inside = ea.geometry.contains(cen)
    pt_ea = cen.where(inside, ea.geometry.representative_point())
    pt = gpd.GeoSeries(pt_ea, crs=5070).to_crs(4326)
    tab = pd.DataFrame({
        "fips": g["GEOID"].astype(str).str.zfill(5),
        "state_abbr": g["STATEFP"].map(STATES),
        "state_fips": g["STATEFP"],
        "name": g["NAME"],
        "namelsad": g["NAMELSAD"],
        "lon": pt.x.round(5).values,
        "lat": pt.y.round(5).values,
        "interior_point_method": inside.map({True: "centroid", False: "point_on_surface"}).values,
        "land_km2": (g["ALAND"].astype(float) / 1e6).round(2),
        "water_km2": (g["AWATER"].astype(float) / 1e6).round(2),
        "area_km2": (ea.geometry.area / 1e6).round(2).values,
    })
    tab.to_parquet(PROC / "counties.parquet", index=False)
    print(tab.groupby("state_abbr").size(), "total", len(tab))
    print("interior point methods:", tab.interior_point_method.value_counts().to_dict())

    # topology-preserving simplification over the whole 7-state coverage
    geoms = shapely.coverage_simplify(g.geometry.values, tolerance=TOL)
    simp = gpd.GeoDataFrame({"fips": tab["fips"], "name": tab["name"], "state": tab["state_abbr"]},
                            geometry=gpd.GeoSeries(geoms, crs=4326))
    simp["geometry"] = simp.geometry.apply(round_coords).make_valid()
    size = write_geojson(simp, WEB / "counties.geojson")
    print(f"counties.geojson: {len(simp)} features, {size/1e6:.2f} MB")

    st = simp.dissolve(by="state", as_index=False)[["state", "geometry"]]
    st["state_fips"] = st["state"].map({v: k for k, v in STATES.items()})
    names = dict(zip(g["STUSPS"], g["STATE_NAME"]))
    st["name"] = st["state"].map(names)
    st["geometry"] = st.geometry.apply(round_coords)
    size = write_geojson(st[["state", "state_fips", "name", "geometry"]], WEB / "states.geojson")
    print(f"states.geojson: {len(st)} features, {size/1e6:.2f} MB")


if __name__ == "__main__":
    main()
