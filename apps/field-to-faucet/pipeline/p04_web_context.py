"""Map context layers for the web app: rivers, counties, places.

Outputs (web/data/):
  rivers.geojson    major NHD flowlines (NHDPlus V2 medium-resolution "Flowline - Small Scale" layer of the USGS NHD
                    MapServer; stream order >= MIN_ORDER, or a named main river), clipped to the basins (+ buffer),
                    merged per (name, order), simplified. props: name, order
  counties.geojson  Iowa + Minnesota counties intersecting the basins (Census cartographic boundary 2023, 1:500k),
                    simplified. props: name, state, fips
  places.json       [{name, lon, lat, kind, basin, source}] Des Moines, the two intake gauges, towns in the basins
                    (Census 2023 Gazetteer internal points)
Raw downloads cached in data/raw/nhd/, data/raw/census/.
"""
import io
import json
import zipfile

import geopandas as gpd
import pandas as pd
from shapely import wkb
from shapely.geometry import box
from shapely.ops import linemerge

from common import RAW, PROC, WEB_DATA, get

NHD = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/4/query"  # Flowline - Small Scale (NHDPlus V2)
NHD_LARGE = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query"  # Large Scale (times out)
COUNTY_ZIP = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_gaz_place_{fips}.txt"
MIN_ORDER = 4
RACCOON_CONFLUENCE_LON = -93.966  # NHDPlus: North + South Raccoon join at (-93.9667, 41.5438), ~1.5 km above the Van Meter gauge
DSM_BOX = (-94.0, 41.45, -93.57, 41.70)  # lon/lat box from the gauges to the confluence in Des Moines
MAIN_RIVERS = {"Raccoon River", "North Raccoon River", "South Raccoon River", "Middle Raccoon River",
               "Des Moines River", "West Fork Des Moines River", "East Fork Des Moines River", "Boone River"}
TOWNS = {  # (gazetteer NAME, state fips)
    "19": ["Des Moines city", "West Des Moines city", "Fort Dodge city", "Boone city", "Jefferson city",
           "Carroll city", "Storm Lake city", "Perry city", "Adel city", "Humboldt city", "Algona city",
           "Webster City city", "Sac City city", "Estherville city", "Emmetsburg city", "Guthrie Center city",
           "Panora city", "Lake City city", "Rockwell City city"],
    "27": ["Worthington city", "Windom city", "Jackson city"],
}
CNHD = RAW / "nhd"
CCEN = RAW / "census"
for _d in (CNHD, CCEN):
    _d.mkdir(parents=True, exist_ok=True)


def basins_gdf():
    h = pd.read_parquet(PROC / "huc12.parquet")
    g = gpd.GeoDataFrame(h[["basin"]], geometry=h.geometry.apply(wkb.loads), crs=4326)
    return g.dissolve("basin").reset_index()


def fetch_nhd(bbox):
    f = CNHD / f"flowline_ss_order{MIN_ORDER}.geojson"
    if f.exists():
        return gpd.read_file(f)
    names = ",".join("'" + n.replace("'", "''") + "'" for n in sorted(MAIN_RIVERS))
    where = f"StreamOrde >= {MIN_ORDER} OR GNIS_NAME IN ({names})"
    feats, off = [], 0
    while True:
        js = get(NHD, params={"where": where, "geometry": ",".join(map(str, bbox)),
                              "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                              "spatialRel": "esriSpatialRelIntersects", "outFields": "GNIS_NAME,StreamOrde,COMID",
                              "returnGeometry": "true", "outSR": 4326, "f": "geojson", "orderByFields": "OBJECTID",
                              "resultOffset": off, "resultRecordCount": 2000}).json()
        feats += js["features"]
        print(f"  NHD page offset {off}: {len(js['features'])} features")
        if len(js["features"]) < 2000 and not js.get("exceededTransferLimit"):
            break
        off += len(js["features"])
    fc = {"type": "FeatureCollection", "features": feats}
    f.write_text(json.dumps(fc))
    return gpd.GeoDataFrame.from_features(feats, crs=4326)


def rivers(basins):
    bbox = [round(v, 3) for v in basins.total_bounds]
    g = fetch_nhd(bbox)
    print(f"NHD flowlines fetched: {len(g)}")
    g = g.rename(columns={"GNIS_NAME": "name", "StreamOrde": "order"})
    g["name"] = g["name"].fillna("").str.strip()
    # NHDPlus V2 carries the name "North Raccoon River" on the main stem below the North/South Raccoon confluence
    # (just above the Van Meter gauge); its GNIS name is "Raccoon River". Relabel reaches east of the confluence.
    c = g.geometry.representative_point()
    g.loc[(g["name"] == "North Raccoon River") & (g["order"] >= 6) & (c.x > RACCOON_CONFLUENCE_LON) & (c.y < 41.62), "name"] = "Raccoon River"
    g5 = g.to_crs(5070)
    clip = basins.to_crs(5070).union_all().buffer(500)
    # main rivers also run on from the gauges to the Des Moines Water Works intakes / confluence in Des Moines
    metro = gpd.GeoSeries([box(*DSM_BOX)], crs=4326).to_crs(5070).iloc[0]
    main = g5["name"].isin(MAIN_RIVERS)
    g5 = g5[g5.intersects(clip) | (main & g5.intersects(metro))].copy()
    g5["geometry"] = [geom.intersection(clip.union(metro) if m else clip) for geom, m in zip(g5.geometry, main.loc[g5.index])]
    keep = (g5["order"] >= MIN_ORDER) & (g5["name"] != "") | g5["name"].isin(MAIN_RIVERS)
    # unnamed order >= 5 reaches (e.g. through reservoirs) keep the network connected
    keep |= (g5["order"] >= 5)
    g5 = g5[keep & ~g5.geometry.is_empty]
    out = []
    for (name, order), grp in g5.groupby(["name", "order"]):
        merged = linemerge([x for x in grp.geometry.explode().values if x.geom_type == "LineString"])
        if merged.length < 3000:  # slivers of rivers that only graze the basin edge
            continue
        out.append({"name": name or None, "order": int(order), "geometry": merged})
    r = gpd.GeoDataFrame(out, crs=5070)
    r["geometry"] = r.geometry.simplify(120)
    r = r[~r.geometry.is_empty].to_crs(4326).sort_values("order", ascending=False)
    path = WEB_DATA / "rivers.geojson"
    r.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=4)
    print(f"rivers.geojson: {len(r)} features, {path.stat().st_size / 1024:.0f} KB; "
          f"names: {sorted(set(r.name.dropna()))[:40]}")
    return r


def counties(basins):
    z = CCEN / "cb_2023_us_county_500k.zip"
    if not z.exists():
        z.write_bytes(get(COUNTY_ZIP, timeout=300).content)
    c = gpd.read_file(f"zip://{z}")
    c = c[c.STATEFP.isin(["19", "27"])].to_crs(5070)
    b = basins.to_crs(5070).union_all()
    c = c[c.intersects(b)].copy()
    # drop slivers: counties with < 0.5% of their area in the basins
    c = c[c.geometry.intersection(b).area / c.area > 0.005]
    c["geometry"] = c.geometry.simplify(100)
    c = c.to_crs(4326)
    c["state"] = c.STATEFP.map({"19": "IA", "27": "MN"})
    c = c.rename(columns={"NAME": "name", "GEOID": "fips"})[["name", "state", "fips", "geometry"]]
    path = WEB_DATA / "counties.geojson"
    c.sort_values("fips").to_file(path, driver="GeoJSON", COORDINATE_PRECISION=4)
    print(f"counties.geojson: {len(c)} counties ({(c.state == 'IA').sum()} IA, {(c.state == 'MN').sum()} MN), "
          f"{path.stat().st_size / 1024:.0f} KB")


def places(basins):
    rows = []
    for fips, names in TOWNS.items():
        f = CCEN / f"2023_gaz_place_{fips}.txt"
        if not f.exists():
            f.write_text(get(GAZ.format(fips=fips)).text)
        gz = pd.read_csv(f, sep="\t", dtype=str)
        gz.columns = [c.strip() for c in gz.columns]
        for n in names:
            m = gz[gz.NAME == n]
            assert len(m) == 1, (fips, n, len(m))
            rows.append({"name": n.rsplit(" ", 1)[0] + (", MN" if fips == "27" else ""),
                         "lon": round(float(m.INTPTLONG.iloc[0]), 5), "lat": round(float(m.INTPTLAT.iloc[0]), 5),
                         "geoid": m.GEOID.iloc[0]})
    p = gpd.GeoDataFrame(rows, geometry=gpd.points_from_xy([r["lon"] for r in rows], [r["lat"] for r in rows]),
                         crs=4326)
    j = gpd.sjoin(p, basins[["basin", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    out = []
    for _, r in j.iterrows():
        kind = "city" if r["name"] == "Des Moines" else "town"
        if kind == "town" and pd.isna(r.basin) and r["name"] != "West Des Moines":
            print(f"  skip {r['name']}: not inside either basin")
            continue
        out.append({"name": r["name"], "lon": r.lon, "lat": r.lat, "kind": kind,
                    "basin": None if pd.isna(r.basin) else r.basin, "geoid": r.geoid,
                    "source": "US Census 2023 Gazetteer (internal point)"})
    sites = json.loads((WEB_DATA / "sites.json").read_text())
    for s in sites:
        river = "Raccoon River" if s["site"] == "05484500" else "Des Moines River"
        out.append({"name": f"{river} intake gauge (USGS {s['site']})", "lon": s["lon"], "lat": s["lat"],
                    "kind": "intake", "basin": "raccoon" if s["site"] == "05484500" else "desmoines",
                    "site": s["site"], "source": "USGS NWIS site location; gauge used as proxy for the "
                                                 "Des Moines Water Works intake on this river"})
    (WEB_DATA / "places.json").write_text(json.dumps(out, indent=1))
    print(f"places.json: {len(out)} places: {[o['name'] for o in out]}")


def main():
    b = basins_gdf()
    rivers(b)
    counties(b)
    places(b)


if __name__ == "__main__":
    main()
