"""Basins draining to the two Des Moines intake gauges, from USGS WBD HUC-12s.

Walks the WBD `tohuc` network upstream from the HUC-12 containing each gauge.
Outputs: data/processed/huc12.parquet, web/data/basins.geojson, web/data/huc12.geojson (geometry only + ids),
web/data/sites.json. Raw WBD JSON cached in data/raw/wbd/.
"""
import json
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, shape
from common import RAW, PROC, WEB_DATA, SITES, get

WBD = "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/6/query"  # layer 6 = HUC-12
CACHE = RAW / "wbd"
CACHE.mkdir(parents=True, exist_ok=True)
GAUGES = {"05484500": (-93.9497778, 41.53402778), "05482000": (-93.6197222, 41.61194444)}
# Drainage areas published by USGS (sq mi) for a sanity check
USGS_DA_SQMI = {"05484500": 3441, "05482000": 6245}


def fetch_huc8(prefix):
    f = CACHE / f"huc12_{prefix}.geojson"
    if f.exists():
        return json.loads(f.read_text())
    feats, offset = [], 0
    while True:
        r = get(WBD, params={"where": f"huc12 LIKE '{prefix}%'", "outFields": "huc12,name,tohuc,areasqkm",
                             "returnGeometry": "true", "outSR": "4326", "f": "geojson",
                             "resultOffset": offset, "resultRecordCount": 500, "geometryPrecision": 5})
        js = r.json()
        feats += js["features"]
        if len(js["features"]) < 500:
            break
        offset += 500
    fc = {"type": "FeatureCollection", "features": feats}
    f.write_text(json.dumps(fc))
    return fc


def main():
    # HUC-4 0710 (Des Moines) sub-basins 07100001..07100007 cover everything upstream of both gauges.
    feats = []
    for i in range(1, 8):
        fc = fetch_huc8(f"0710000{i}")
        feats += fc["features"]
        print(f"0710000{i}: {len(fc['features'])} HUC-12s")
    gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    gdf = gdf.drop_duplicates("huc12").set_index("huc12", drop=False)
    up = {}
    for h, t in zip(gdf.huc12, gdf.tohuc):
        up.setdefault(t, []).append(h)

    basin_of = {}
    for site, (lon, lat) in GAUGES.items():
        b = SITES[site]["basin"]
        pt = Point(lon, lat)
        start = gdf[gdf.contains(pt)].huc12.tolist()
        assert len(start) == 1, (site, start)
        seen, stack = set(), [start[0]]
        while stack:
            h = stack.pop()
            if h in seen:
                continue
            # The Raccoon (HUC-8 07100006/07100007) joins the Des Moines River inside the 2nd Ave gauge's HUC-12,
            # but the gauge itself is above the confluence, so never walk into the Raccoon for that gauge.
            if site == "05482000" and h[:8] in ("07100006", "07100007"):
                continue
            seen.add(h)
            stack += up.get(h, [])
        for h in seen:
            basin_of[h] = b
        sub = gdf.loc[sorted(seen)].to_crs(5070)
        area = sub.area.sum() / 1e6
        print(f"{site} {b}: start {start[0]}, {len(seen)} HUC-12s, {area:,.0f} km2 "
              f"= {area / 2.58999:,.0f} sq mi (USGS DA {USGS_DA_SQMI[site]} sq mi; includes gauge HUC-12 in full)")

    g = gdf[gdf.huc12.isin(basin_of)].copy()
    g["basin"] = g.huc12.map(basin_of)
    g["area_km2"] = g.to_crs(5070).area / 1e6
    fa = PROC / "focus_area.json"
    focus = set(json.loads(fa.read_text())["huc12s"]) if fa.exists() else set()
    g["in_focus"] = g.huc12.isin(focus)
    g = g.reset_index(drop=True)
    out = pd.DataFrame(g.drop(columns="geometry"))
    out["geometry"] = g.geometry.to_wkb()
    out[["huc12", "name", "tohuc", "basin", "area_km2", "in_focus", "geometry"]].to_parquet(
        PROC / "huc12.parquet", compression="zstd")

    # Web layers (simplified)
    gs = g.to_crs(5070)
    gs["geometry"] = gs.geometry.simplify(150)
    gs = gs.to_crs(4326)
    gs[["huc12", "name", "basin", "area_km2", "in_focus", "geometry"]].to_file(WEB_DATA / "huc12.geojson", driver="GeoJSON",
                                                                   COORDINATE_PRECISION=4)
    basins = g.to_crs(5070).dissolve("basin", as_index=False)
    basins["area_km2"] = basins.area / 1e6
    basins["geometry"] = basins.geometry.buffer(1).simplify(300)
    basins = basins.to_crs(4326)
    basins["site"] = basins.basin.map({v["basin"]: k for k, v in SITES.items()})
    basins["name"] = basins.site.map(lambda s: SITES[s]["name"])
    basins[["basin", "name", "site", "area_km2", "geometry"]].to_file(WEB_DATA / "basins.geojson", driver="GeoJSON",
                                                                      COORDINATE_PRECISION=4)
    sites = [{"site": s, "name": SITES[s]["name"], "lon": GAUGES[s][0], "lat": GAUGES[s][1],
              "role": "Raccoon River intake gauge (primary)" if s == "05484500" else "Des Moines River intake gauge"}
             for s in SITES]
    (WEB_DATA / "sites.json").write_text(json.dumps(sites, indent=1))
    print(out.groupby("basin").agg(n=("huc12", "size"), km2=("area_km2", "sum")))


if __name__ == "__main__":
    main()
