"""econ: region county polygons (Census cartographic 1:500k, 2023) and GMD polygons (USGS ScienceBase data release).

Outputs (data/processed/):
  counties.geojson  26 region counties {fips, name, gmd, gmd_contract, area_km2, gmd_area_share{...}, gmd_irr_acres_share{...}}
  gmd.geojson       GMD1, GMD3, GMD4 polygons (simplified) from the USGS Kansas irrigation water-use analysis regions
  data/raw/gmd/county_gmd_check.json  county -> GMD assignment check vs the CONTRACTS.md list

Sources:
  https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip
  USGS ScienceBase item 577b8b5fe4b0ef4d2f4223a1 (Reported 2014 water withdrawn for irrigation ... in Kansas irrigation
  water-use analysis regions; polygons = the 5 Kansas GMDs + 3 broader regions), KML file.
Run: python3 pipeline/econ_boundaries.py
"""
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw"
OUT = APP / "data" / "processed"
UA = {"User-Agent": "water-clock-hackathon"}
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
SB_ITEM = "https://www.sciencebase.gov/catalog/item/577b8b5fe4b0ef4d2f4223a1"
GMD_KML_URL = ("https://www.sciencebase.gov/catalog/file/get/577b8b5fe4b0ef4d2f4223a1?f=__disk__02%2F8c%2Fbe%2F"
               "028cbe7658edefebc0bd5590c8067c4768c29858")

CONTRACT = {
    "GMD1": ["071", "203", "171", "101"],
    "GMD3": ["075", "093", "055", "069", "057", "187", "067", "081", "129", "189", "175", "119"],
    "GMD4": ["023", "153", "039", "181", "193", "179", "199", "109", "063", "065"],
}
FIPS2GMD = {"20" + c: g for g, cs in CONTRACT.items() for c in cs}
GMD_NAME = {"Western Kansas GMD #1": "GMD1", "Southwest Kansas GMD #3": "GMD3", "Northwest Kansas GMD #4": "GMD4"}


def get(url, path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, headers=UA, timeout=180)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


def write_small(gdf, path, tol_start, limit=300_000):
    tol = tol_start
    while True:
        g = gdf.copy()
        g["geometry"] = g.geometry.simplify(tol, preserve_topology=True)
        g.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=4)
        if path.stat().st_size < limit:
            return tol, path.stat().st_size
        tol *= 1.6


def main():
    cz = get(COUNTY_URL, RAW / "census" / "cb_2023_us_county_500k.zip")
    us = gpd.read_file(f"zip://{cz}")
    cty = us[us.GEOID.isin(FIPS2GMD)].copy()
    assert len(cty) == 26, len(cty)
    cty = cty.to_crs(4326)
    cty["fips"] = cty.GEOID
    cty["name"] = cty.NAME
    cty["gmd_contract"] = cty.fips.map(FIPS2GMD)
    cty_ea = cty.to_crs(5070)
    cty["area_km2"] = (cty_ea.area / 1e6).round(1)

    # GMD polygons (USGS data release)
    kml = get(GMD_KML_URL, RAW / "gmd" / "regions2014.kml")
    reg = gpd.read_file(kml)
    reg["gmd"] = reg["DWR_region"].map(GMD_NAME)
    gmd = reg[reg.gmd.notna()][["gmd", "DWR_region", "geometry"]].copy()
    gmd = gmd.dissolve("gmd", as_index=False, aggfunc="first")
    gmd_ea = gmd.to_crs(5070)
    gmd["area_km2"] = (gmd_ea.area / 1e6).round(0)

    # county area share in each GMD
    inter = gpd.overlay(cty_ea[["fips", "geometry"]], gmd_ea[["gmd", "geometry"]], how="intersection")
    inter["a"] = inter.area
    tot = cty_ea.set_index("fips").area
    area_share = {f: {} for f in cty.fips}
    for _, r in inter.iterrows():
        area_share[r.fips][r.gmd] = round(float(r.a / tot[r.fips]), 3)

    # WIMAS irrigated acres per county by GMD polygon (points of diversion, mean 2015-2024), if the pumping module's file exists
    irr_share = {f: None for f in cty.fips}
    wim_path = OUT / "wimas_use.parquet"
    wimas_note = "wimas_use.parquet not found"
    if wim_path.exists():
        w = pd.read_parquet(wim_path, columns=["pdiv_id", "year", "use", "lon", "lat", "county_fips", "acres_irrigated"])
        w = w[(w.use == "IRR") & w.year.between(2015, 2024) & w.lon.notna()]
        w = w.groupby(["pdiv_id", "county_fips"], as_index=False).agg(lon=("lon", "first"), lat=("lat", "first"),
                                                                      acres=("acres_irrigated", "mean"))
        pts = gpd.GeoDataFrame(w, geometry=gpd.points_from_xy(w.lon, w.lat), crs=4326)
        pts = gpd.sjoin(pts, gmd[["gmd", "geometry"]], how="left", predicate="within")
        pts["gmd"] = pts["gmd"].fillna("none")
        s = pts.groupby(["county_fips", "gmd"]).acres.sum()
        for f in cty.fips:
            if f in s.index.get_level_values(0):
                sub = s.loc[f]
                irr_share[f] = {k: round(float(v / sub.sum()), 3) for k, v in sub.items() if sub.sum() > 0}
        wimas_note = ("WIMAS irrigation points of diversion (pumping module wimas_use.parquet), mean reported irrigated "
                      "acres 2015-2024, point-in-polygon against the USGS GMD polygons")

    check = []
    gmd_by_irr = {}
    for f in sorted(cty.fips):
        a = area_share[f]
        i = irr_share[f] or {}
        ig = {k: v for k, v in i.items() if k != "none"}  # GMD with most irrigated acres (ignoring the outside-GMD part)
        best_irr = max(ig, key=ig.get) if ig else None
        best_area = max(a, key=a.get) if a else "none"
        gmd_by_irr[f] = best_irr or best_area
        check.append({"fips": f, "name": cty.set_index("fips").name[f], "gmd_contract": FIPS2GMD[f],
                      "area_share": a, "irr_acres_share": irr_share[f], "gmd_max_area": best_area,
                      "gmd_max_irrigated": best_irr,
                      "agrees_with_contract": (best_irr or best_area) == FIPS2GMD[f]})
    (RAW / "gmd").mkdir(parents=True, exist_ok=True)
    json.dump({"method": wimas_note, "counties": check}, open(RAW / "gmd" / "county_gmd_check.json", "w"), indent=1)
    for c in check:
        print(c["fips"], c["name"], c["gmd_contract"], c["area_share"], c["irr_acres_share"],
              "" if c["agrees_with_contract"] else "<-- DISAGREES")

    cty["gmd"] = cty["gmd_contract"]  # region definition per CONTRACTS.md (checked above)
    cty["gmd_by_irrigated_area"] = cty.fips.map(gmd_by_irr)
    cty["gmd_area_share"] = cty.fips.map(lambda f: json.dumps(area_share[f]))
    cty["gmd_irr_share"] = cty.fips.map(lambda f: json.dumps(irr_share[f]) if irr_share[f] else None)
    out = cty[["fips", "name", "gmd", "gmd_by_irrigated_area", "area_km2", "gmd_area_share", "gmd_irr_share", "geometry"]].sort_values("fips")
    tol, size = write_small(out, OUT / "counties.geojson", 0.0005)
    print("counties.geojson", size, "bytes, simplify tol", tol)
    gmd["source"] = f"USGS ScienceBase {SB_ITEM} (Kansas irrigation water-use analysis regions, GMD polygons)"
    tol, size = write_small(gmd[["gmd", "DWR_region", "area_km2", "source", "geometry"]], OUT / "gmd.geojson", 0.001,
                            limit=150_000)
    print("gmd.geojson", size, "bytes, simplify tol", tol)


if __name__ == "__main__":
    main()
