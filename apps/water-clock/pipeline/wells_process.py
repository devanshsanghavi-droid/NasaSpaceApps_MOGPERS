"""Merge KGS WIZARD + USGS water levels, clean, build annual (winter) levels, aquifer base, saturated thickness.

Inputs (raw caches, gitignored; produced by wells_kgs_fetch.py, wells_nwis_fetch.py, wells_base_fetch.py):
  data/raw/kgs/<fips>_{sites,wlevel}.csv
  data/raw/nwis/<fips>_{fm,ml}_<page>.json
  data/raw/usgs_hpa/base/ofr98-393.e00       (USGS OFR 98-393 base-of-aquifer contours)
  data/raw/usgs_hpa/sat09/hp_satthk09/       (USGS SIR 2012-5177 saturated thickness 2009 raster)
Outputs:
  data/processed/wells_levels.parquet, wells_meta.parquet, aquifer_base.json,
  sat_thickness_published.json, wells_summary.json
"""
import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from pyproj import Transformer
from scipy.interpolate import griddata
from scipy.spatial import cKDTree

from wells_kgs_fetch import COUNTIES

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw"
OUT = APP / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)
BBOX = (-102.06, 36.99, -99.55, 40.01)
CELL = 0.02
TO_ALB = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)

GMD_OF = {f"20{c:03d}": g for c, (n, g) in COUNTIES.items()}
NAME_OF = {f"20{c:03d}": n for c, (n, g) in COUNTIES.items()}

# KGS WIZARD water-level status codes (KGS OFR 2007-15 manual). Blank = static. B = only year/month known (kept).
KGS_BAD_STATUS = set("ADEFGHIJOPRSTVWXZN")
KGS_BAD_METHOD = {"E", "L"}          # estimated; interpreted from geophysical logs
NWIS_OK_QUAL = {(), ("Static",)}     # drop ForeignSubstance, Pumping, Dry, Flowing, GWSWAffected...
NWIS_BAD_PROC = {"E", "L"}
NON_HPA_AQUIFERS = {"210DKOT", "211DKOT", "217DKOT", "210CRCS", "300PLZC", "310PRMN"}  # Dakota/Cretaceous/Permian bedrock aquifers


# ---------------------------------------------------------------- KGS
def load_kgs():
    sites, lev = [], []
    for code in COUNTIES:
        fips = f"20{code:03d}"
        s = pd.read_csv(RAW / "kgs" / f"{fips}_sites.csv", dtype=str, skipinitialspace=True)
        s.columns = s.columns.str.strip()
        s["county_fips"] = fips
        sites.append(s)
        w = pd.read_csv(RAW / "kgs" / f"{fips}_wlevel.csv", dtype=str)
        w.columns = w.columns.str.strip()
        lev.append(w)
    s = pd.concat(sites, ignore_index=True).drop_duplicates("USGS_ID")
    w = pd.concat(lev, ignore_index=True).drop_duplicates()
    num = lambda x: pd.to_numeric(x, errors="coerce")
    meta = pd.DataFrame({
        "well_id": s.USGS_ID.str.strip(),
        "source": "KGS_WIZARD",
        "source_id": s.USGS_ID.str.strip(),
        "lon": num(s.LONGITUDE), "lat": num(s.LATITUDE),
        "county_fips": s.county_fips,
        "land_elev_ft": num(s.LAND_SURFACE_ALTITUDE),
        "land_elev_datum": s.ALTITUDE_DATUM.str.strip().replace({"NGCD29": "NGVD29"}),
        "well_depth_ft": num(s.DEPTH_OF_WELL),
        "depth_to_bedrock_ft": num(s.DEPTH_TO_BEDROCK),
        "bedrock_source": s.DEPTH_TO_BEDROCK_SOURCE,
        "aquifer_code": s.AQUIFER_CODE,
        "kgs_gmd": s.GROUNDWATER_MGMT_DISTRICT,
        "local_well_number": s.LOCAL_WELL_NUMBER,
        "site_type": s.SITE_TYPE,
        "use_of_water": s.USE_OF_WATER_PRIMARY,
        "kgs_kid": s.get("WELL_KID", pd.Series(index=s.index, dtype=str)).astype(str).str.strip(),
    })
    lv = pd.DataFrame({
        "well_id": w.USGS_ID.str.strip(),
        "meas_date": pd.to_datetime(w.MEASUREMENT_DATE_AND_TIME, format="%m/%d/%Y", errors="coerce"),
        "depth_to_water_ft": num(w.DEPTH_TO_WATER),
        "status": w.STATUS.fillna("").str.strip(),
        "method": w.METHOD.fillna("").str.strip(),
        "agency": w.AGENCY.fillna("").str.strip(),
        "source": "KGS_WIZARD",
    })
    return meta, lv


# ---------------------------------------------------------------- NWIS
def load_nwis():
    ml_rows, fm_rows = [], []
    for f in sorted(glob.glob(str(RAW / "nwis" / "*_ml_*.json"))):
        fips = Path(f).name[:5]
        for ft in json.load(open(f))["features"]:
            p = ft["properties"]
            lon, lat = ft["geometry"]["coordinates"] if ft.get("geometry") else (np.nan, np.nan)
            ml_rows.append({"source_id": p["id"], "well_id": p["monitoring_location_number"], "lon": lon, "lat": lat,
                            "county_fips": fips, "land_elev_ft": p.get("altitude"),
                            "land_elev_datum": p.get("vertical_datum"), "well_depth_ft": p.get("well_constructed_depth"),
                            "aquifer_code": p.get("aquifer_code"), "local_well_number": p.get("monitoring_location_name")})
    for f in sorted(glob.glob(str(RAW / "nwis" / "*_fm_*.json"))):
        for ft in json.load(open(f))["features"]:
            p = ft["properties"]
            fm_rows.append({"source_id": p["monitoring_location_id"], "time": p["time"], "value": p["value"],
                            "qual": tuple(p.get("qualifier") or []), "proc": p.get("observing_procedure_code") or "",
                            "approval": p.get("approval_status")})
    ml = pd.DataFrame(ml_rows).drop_duplicates("source_id")
    fm = pd.DataFrame(fm_rows)
    fm["well_id"] = fm.source_id.str.split("-", n=1).str[1]
    fm["meas_date"] = pd.to_datetime(fm.time.str[:10], errors="coerce")
    fm["depth_to_water_ft"] = pd.to_numeric(fm.value, errors="coerce")
    fm["status"] = fm.qual.map(lambda q: "" if q in NWIS_OK_QUAL else "|".join(q))
    fm["method"] = fm.proc
    fm["agency"] = fm.source_id.str.split("-", n=1).str[0]
    fm["source"] = "USGS_NWIS"
    fm["bad"] = ~fm.qual.isin(NWIS_OK_QUAL) | fm.proc.isin(NWIS_BAD_PROC) | (fm.approval != "Approved")
    ml["source"] = "USGS_NWIS"
    return ml, fm


# ---------------------------------------------------------------- base surface
def base_surface():
    """Interpolate USGS OFR 98-393 base-of-aquifer contours (ft above NGVD29) on the grid and at points."""
    g = gpd.read_file(RAW / "usgs_hpa" / "base" / "ofr98-393.e00", layer="ARC")
    g = g[g.ELEV > 0]
    # clip to region bbox + 50 km margin in Albers
    x0, y0 = TO_ALB.transform(BBOX[0] - 0.6, BBOX[1] - 0.5)
    x1, y1 = TO_ALB.transform(BBOX[2] + 0.6, BBOX[3] + 0.5)
    g = g.cx[min(x0, x1) - 60000:max(x0, x1) + 60000, min(y0, y1):max(y0, y1)]
    pts, vals = [], []
    for geom, z in zip(g.geometry, g.ELEV):
        L = geom.length
        n = max(2, int(L / 500))  # densify to ~500 m
        for d in np.linspace(0, L, n):
            p = geom.interpolate(d)
            pts.append((p.x, p.y)); vals.append(float(z))
    return np.array(pts), np.array(vals), len(g)


def interp_base(pts, vals, x, y):
    return griddata(pts, vals, (x, y), method="linear")


def sample_raster(path, lon, lat):
    with rasterio.open(path) as r:
        tr = Transformer.from_crs("EPSG:4326", r.crs, always_xy=True)
        xs, ys = tr.transform(lon, lat)
        out = np.array([v[0] for v in r.sample(list(zip(xs, ys)))], dtype=float)
        out[(out < -1e30) | (out == r.nodata)] = np.nan
    return out


def main():
    km, kl = load_kgs()
    nm, nf = load_nwis()

    # --- KGS level cleaning
    kl["bad"] = kl.status.map(lambda s: bool(set(s) & KGS_BAD_STATUS)) | kl.method.isin(KGS_BAD_METHOD)

    # --- NWIS wells not in KGS (by site number), then location match within 50 m
    nwis_only = nm[~nm.well_id.isin(km.well_id)].copy()
    nwis_has = nf.groupby("well_id").size()
    nwis_only = nwis_only[nwis_only.well_id.isin(nwis_has.index)]
    kx, ky = TO_ALB.transform(km.lon.values, km.lat.values)
    tree = cKDTree(np.c_[kx, ky])
    nx_, ny_ = TO_ALB.transform(nwis_only.lon.values, nwis_only.lat.values)
    dist, idx = tree.query(np.c_[nx_, ny_])
    remap = {}
    for (wid, d, i) in zip(nwis_only.well_id, dist, idx):
        if d <= 50:
            kid = km.well_id.iloc[i]
            a = nf[(nf.well_id == wid) & ~nf.bad].set_index("meas_date").depth_to_water_ft
            b = kl[(kl.well_id == kid) & ~kl.bad].groupby("meas_date").depth_to_water_ft.first()
            common = a.index.intersection(b.index)
            if len(common) == 0 or np.nanmedian(np.abs(a.loc[common].groupby(level=0).first() - b.loc[common])) <= 1.0:
                remap[wid] = kid
    n_loc_merged = len(remap)
    nf["well_id"] = nf.well_id.replace(remap)
    nwis_only = nwis_only[~nwis_only.well_id.isin(remap)]

    # --- union measurements: KGS preferred; NWIS rows added only for (well,date) not in KGS
    kl_good = kl[~kl.bad & kl.meas_date.notna() & kl.depth_to_water_ft.notna()]
    nf_good = nf[~nf.bad & nf.meas_date.notna() & nf.depth_to_water_ft.notna()]
    shared = nf_good.merge(kl_good[["well_id", "meas_date", "depth_to_water_ft"]], on=["well_id", "meas_date"],
                           suffixes=("", "_kgs"))
    agree = (np.abs(shared.depth_to_water_ft - shared.depth_to_water_ft_kgs) <= 0.05).mean() if len(shared) else np.nan
    key = set(zip(kl_good.well_id, kl_good.meas_date))
    add = nf_good[[k not in key for k in zip(nf_good.well_id, nf_good.meas_date)]]
    cols = ["well_id", "meas_date", "source", "depth_to_water_ft", "status", "method", "agency"]
    lev = pd.concat([kl_good[cols], add[cols]], ignore_index=True)
    # one row per (well, date): KGS rows come first; same-day repeats -> keep first
    n_dup_day = int(lev.duplicated(["well_id", "meas_date"]).sum())
    lev = lev.drop_duplicates(["well_id", "meas_date"], keep="first")

    # --- meta union
    nm_only = nwis_only.copy()
    nm_only["source"] = "USGS_NWIS"
    meta = pd.concat([km, nm_only[[c for c in nm_only.columns if c in km.columns or c == "source"]]],
                     ignore_index=True).drop_duplicates("well_id")
    meta = meta[meta.county_fips.isin(GMD_OF)]
    meta["gmd"] = meta.county_fips.map(GMD_OF)
    # fill missing KGS land elevation / well depth from NWIS where the same site exists
    nml = nm.set_index("well_id")
    for c in ["land_elev_ft", "well_depth_ft"]:
        miss = meta[c].isna() & meta.well_id.isin(nml.index)
        meta.loc[miss, c] = meta.loc[miss, "well_id"].map(nml[c])
    miss = meta.land_elev_datum.isna() & meta.well_id.isin(nml.index)
    meta.loc[miss, "land_elev_datum"] = meta.loc[miss, "well_id"].map(nml["land_elev_datum"])

    # --- drop wells in non-High-Plains bedrock aquifers
    non_hpa = meta.aquifer_code.isin(NON_HPA_AQUIFERS)
    n_non_hpa = int(non_hpa.sum())
    meta = meta[~non_hpa]
    lev = lev[lev.well_id.isin(meta.well_id)]

    # --- sanity rules on values
    lev = lev.merge(meta[["well_id", "land_elev_ft", "well_depth_ft"]], on="well_id", how="left")
    r_neg = lev.depth_to_water_ft < 0
    r_deep = lev.well_depth_ft.notna() & (lev.depth_to_water_ft > lev.well_depth_ft + 5)
    # if most of a well's readings are "below the well bottom", the well-depth metadata is wrong, not the levels:
    # keep those readings and flag the depth as suspect; otherwise drop the isolated too-deep readings.
    frac_deep = r_deep.groupby(lev.well_id).transform("mean")
    suspect_depth = set(lev.well_id[frac_deep >= 0.5])
    r_deep = r_deep & (frac_deep < 0.5)
    meta["well_depth_suspect"] = meta.well_id.isin(suspect_depth)
    r_old = lev.meas_date < "1940-01-01"
    lev = lev[~(r_neg | r_deep | r_old)].copy()
    n_rule = {"negative_dtw": int(r_neg.sum()), "dtw_gt_well_depth+5": int(r_deep.sum()), "before_1940": int(r_old.sum())}
    # per-well robust outlier screen on annual winter series: |dtw - rolling median(5 winters)| > 40 ft
    lev["wl_elev_ft"] = lev.land_elev_ft - lev.depth_to_water_ft
    m = lev.meas_date.dt.month
    lev["is_winter"] = m.isin([12, 1, 2, 3])
    lev["year"] = np.where(m == 12, lev.meas_date.dt.year + 1, lev.meas_date.dt.year)
    lev = lev.sort_values(["well_id", "meas_date"])

    # annual value: winter measurement closest to Jan 15 of the water year
    w = lev[lev.is_winter].copy()
    w["dd"] = (w.meas_date - pd.to_datetime(w.year.astype(str) + "-01-15")).abs()
    ann_idx = w.sort_values(["well_id", "year", "dd"]).groupby(["well_id", "year"]).head(1).index
    lev["is_annual"] = False
    lev.loc[ann_idx, "is_annual"] = True
    ann = lev[lev.is_annual].copy()
    ann["med5"] = ann.groupby("well_id").depth_to_water_ft.transform(
        lambda s: s.rolling(5, center=True, min_periods=3).median())
    spike = (ann.depth_to_water_ft - ann.med5).abs() > 40
    n_spike = int(spike.sum())
    lev.loc[ann.index[spike], "is_annual"] = False
    lev["outlier_flag"] = False
    lev.loc[ann.index[spike], "outlier_flag"] = True

    # --- aquifer base
    pts, vals, n_arcs = base_surface()
    mx, my = TO_ALB.transform(meta.lon.values, meta.lat.values)
    meta["base_usgs_ft"] = interp_base(pts, vals, mx, my)
    meta["base_kgs_ft"] = meta.land_elev_ft - meta.depth_to_bedrock_ft
    resid = meta.base_kgs_ft - meta.base_usgs_ft
    ok_pick = resid.notna() & (resid.abs() <= 250)  # gross-error screen for bedrock picks
    n_pick_bad = int((resid.notna() & ~ok_pick).sum())
    pk = meta[ok_pick]
    px, py = TO_ALB.transform(pk.lon.values, pk.lat.values)
    rt = cKDTree(np.c_[px, py])
    rvals = resid[ok_pick].values

    def resid_idw(x, y, R=15000.0, R0=5000.0):
        d, i = rt.query(np.c_[x, y], k=12, distance_upper_bound=R)
        d = np.maximum(d, 1.0)
        valid = np.isfinite(d) & (i < len(rvals))
        wgt = np.where(valid, 1.0 / d ** 2, 0.0)
        rv = np.where(valid, rvals[np.minimum(i, len(rvals) - 1)], 0.0)
        return (wgt * rv).sum(1) / (wgt.sum(1) + 1.0 / R0 ** 2)

    meta["base_elev_ft"] = meta.base_usgs_ft + resid_idw(mx, my)
    meta.loc[ok_pick, "base_elev_ft"] = meta.loc[ok_pick, "base_kgs_ft"]
    meta["base_source"] = np.where(ok_pick, "KGS_WIZARD_depth_to_bedrock",
                                   np.where(meta.base_usgs_ft.notna(), "USGS_OFR98-393+KGS_residual_IDW", None))

    # grid
    lons = np.round(np.arange(BBOX[0] + CELL / 2, BBOX[2], CELL), 4)
    lats = np.round(np.arange(BBOX[1] + CELL / 2, BBOX[3], CELL), 4)
    LON, LAT = np.meshgrid(lons, lats)
    gx, gy = TO_ALB.transform(LON.ravel(), LAT.ravel())
    g_usgs = interp_base(pts, vals, gx, gy)
    g_blend = g_usgs + resid_idw(gx, gy)
    sat_path = RAW / "usgs_hpa" / "sat09" / "hp_satthk09"
    g_sat09 = sample_raster(sat_path, LON.ravel(), LAT.ravel())
    meta["sat_thick_2009_usgs_ft"] = sample_raster(sat_path, meta.lon.values, meta.lat.values)

    r1 = lambda a: [None if not np.isfinite(v) else round(float(v), 1) for v in a]
    base_json = {
        "description": "High Plains aquifer base (bedrock) elevation on a regular lon/lat grid (cell centers).",
        "units": "feet", "vertical_datum": "NGVD29 (sea level datum of 1929, as in source)",
        "cell_deg": CELL, "bbox": list(BBOX), "lons": lons.tolist(), "lats": lats.tolist(),
        "layout": "values[j][i] -> lats[j], lons[i]",
        "base_usgs_ft": [r1(row) for row in g_usgs.reshape(LON.shape)],
        "base_blend_ft": [r1(row) for row in g_blend.reshape(LON.shape)],
        "hpa_present_2009": [[bool(np.isfinite(v)) for v in row] for row in g_sat09.reshape(LON.shape)],
        "sources": {
            "base_usgs_ft": {
                "name": "USGS OFR 98-393, Digital map of base of aquifer for High Plains aquifer (Cederstrand & Becker, 1998), "
                        "digitized from Gutentag and others (1984) USGS PP 1400-B, 1:1,000,000, 200-ft contours",
                "url": "https://www.sciencebase.gov/catalog/item/631405f5d34e36012efa35b2",
                "method": "contour vertices densified to ~500 m, linear (Delaunay) interpolation in EPSG:5070; NaN outside contour hull",
            },
            "base_blend_ft": {
                "method": "base_usgs_ft + inverse-distance (p=2, 12 nearest, 15 km radius, 5 km shrink-to-zero term) "
                          "interpolation of residuals (KGS WIZARD bedrock pick - base_usgs_ft) at wells with "
                          "LAND_SURFACE_ALTITUDE and DEPTH_TO_BEDROCK; picks with |residual| > 250 ft dropped",
                "n_picks_used": int(ok_pick.sum()), "n_picks_dropped": n_pick_bad,
                "url": "https://geohydro.kgs.ku.edu/geohydro/wizard/index.html",
            },
            "hpa_present_2009": "True where the USGS 2009 saturated-thickness raster has data (aquifer present)",
        },
    }
    (OUT / "aquifer_base.json").write_text(json.dumps(base_json, separators=(",", ":")))
    sat_json = {
        "description": "USGS published saturated thickness of the High Plains aquifer, 2009 (pre-irrigation season), "
                       "sampled at grid cell centers (nearest 500 m raster cell)",
        "units": "feet", "year": 2009, "cell_deg": CELL, "bbox": list(BBOX), "lons": lons.tolist(), "lats": lats.tolist(),
        "layout": "values[j][i] -> lats[j], lons[i]",
        "sat_thick_ft": [r1(row) for row in g_sat09.reshape(LON.shape)],
        "source": {"name": "McGuire, V.L., 2012/2013, USGS SIR 2012-5177, raster hp_satthk09 (500 m, EPSG:5070)",
                   "url": "https://www.sciencebase.gov/catalog/item/631405d0d34e36012efa33aa",
                   "note": "USGS set interpolated negative values and areas of little/no saturated thickness to 10 ft; "
                           "base used by USGS is the Gutentag et al. (1984) base (same as OFR 98-393)"},
    }
    (OUT / "sat_thickness_published.json").write_text(json.dumps(sat_json, separators=(",", ":")))

    # --- saturated thickness at wells, final tables
    lev = lev.merge(meta[["well_id", "base_elev_ft"]], on="well_id", how="left")
    lev["sat_thick_ft"] = lev.wl_elev_ft - lev.base_elev_ft
    ann = lev[lev.is_annual]
    stats = ann.groupby("well_id").year.agg(["nunique", "min", "max"])
    meta = meta.merge(stats.rename(columns={"nunique": "n_years", "min": "first_year", "max": "last_year"}),
                      left_on="well_id", right_index=True, how="left")
    meta["n_years"] = meta.n_years.fillna(0).astype(int)
    meta["n_meas"] = meta.well_id.map(lev.groupby("well_id").size()).fillna(0).astype(int)
    meta = meta[meta.n_meas > 0].copy()
    last = ann.sort_values("year").groupby("well_id").tail(1).set_index("well_id")
    meta["sat_thick_last_ft"] = meta.well_id.map(last.sat_thick_ft)
    minsat = ann.groupby("well_id").sat_thick_ft.min()
    meta["sat_flag"] = "ok"
    meta.loc[meta.base_elev_ft.isna(), "sat_flag"] = "no_base"
    meta.loc[meta.sat_thick_2009_usgs_ft.isna() & meta.base_elev_ft.notna(), "sat_flag"] = "outside_hpa_2009_raster"
    meta.loc[meta.sat_thick_2009_usgs_ft.le(10) & meta.sat_flag.eq("ok"), "sat_flag"] = "thin_or_absent_usgs2009"
    neg = meta.well_id.map(minsat) < 0
    meta.loc[neg & meta.sat_flag.eq("ok"), "sat_flag"] = "negative_sat_thick"
    meta.loc[meta.well_id.map(minsat) < -100, "sat_flag"] = "base_or_land_elev_inconsistent"

    # cross-check: 2009 winter sat thickness at wells vs USGS published raster
    a09 = ann[ann.year == 2009][["well_id", "sat_thick_ft"]].merge(meta[["well_id", "sat_thick_2009_usgs_ft"]], on="well_id")
    a09 = a09.dropna()
    diff = a09.sat_thick_ft - a09.sat_thick_2009_usgs_ft

    lev_out = lev[["well_id", "meas_date", "source", "year", "depth_to_water_ft", "wl_elev_ft", "sat_thick_ft",
                   "is_winter", "is_annual", "outlier_flag", "status", "method", "agency"]].rename(
        columns={"status": "measurement_status", "method": "measurement_method"})
    lev_out["year"] = lev_out.year.astype("int16")
    lev_out.to_parquet(OUT / "wells_levels.parquet", index=False, compression="zstd")
    meta_cols = ["well_id", "source", "source_id", "lon", "lat", "county_fips", "gmd", "land_elev_ft", "land_elev_datum",
                 "well_depth_ft", "base_elev_ft", "base_source", "base_usgs_ft", "base_kgs_ft", "depth_to_bedrock_ft",
                 "sat_thick_2009_usgs_ft", "n_years", "first_year", "last_year", "n_meas", "aquifer_code", "kgs_gmd",
                 "local_well_number", "use_of_water", "kgs_kid", "sat_thick_last_ft", "sat_flag", "well_depth_suspect"]
    meta[meta_cols].to_parquet(OUT / "wells_meta.parquet", index=False, compression="zstd")

    # --- summary
    m_ann = meta[meta.n_years > 0]
    k_ann = m_ann[m_ann.source == "KGS_WIZARD"]
    per_c = m_ann.groupby("county_fips").agg(wells=("well_id", "size"), wells_15y=("n_years", lambda s: int((s >= 15).sum())),
                                             median_years=("n_years", "median"))
    per_c["name"] = per_c.index.map(NAME_OF)
    per_c["gmd"] = per_c.index.map(GMD_OF)
    recent = ann[ann.year >= 2016].well_id.unique()
    m15 = m_ann[m_ann.n_years >= 15]
    summary = {
        "raw": {"kgs_sites": int(len(km)), "kgs_measurements": int(len(kl)), "kgs_bad_flagged": int(kl.bad.sum()),
                "nwis_sites_listed": int(len(nm)), "nwis_measurements": int(len(nf)), "nwis_bad_flagged": int(nf.bad.sum())},
        "merge": {"nwis_meas_same_well_date_as_kgs": int(len(shared)), "share_identical_within_0.05ft": float(agree),
                  "nwis_rows_added": int(len(add)), "nwis_wells_merged_by_location_50m": n_loc_merged,
                  "nwis_only_wells": int((meta.source == "USGS_NWIS").sum()), "non_hpa_wells_dropped": n_non_hpa},
        "same_day_duplicates_dropped": n_dup_day,
        "sat_flag_counts_wells_with_annual": m_ann.sat_flag.value_counts().to_dict(),
        "cleaning_rules_dropped": n_rule, "annual_spikes_flagged": n_spike,
        "wells_with_annual_levels": int(len(m_ann)), "kgs_wells_with_annual_levels": int(len(k_ann)),
        "median_record_years_kgs_wells": float(k_ann.n_years.median()),
        "median_record_years_wells_ge2y": float(m_ann[m_ann.n_years >= 2].n_years.median()), "wells_ge15_years": int(len(m15)),
        "wells_ge15_years_and_measured_since_2016": int(m15.well_id.isin(recent).sum()),
        "median_record_years": float(m_ann.n_years.median()),
        "annual_values": int(len(ann)), "year_range": [int(ann.year.min()), int(ann.year.max())],
        "annual_values_by_year_2000plus": {int(k): int(v) for k, v in ann[ann.year >= 2000].groupby("year").size().items()},
        "wells_with_base": int(m_ann.base_elev_ft.notna().sum()),
        "wells_base_from_kgs_pick": int((m_ann.base_source == "KGS_WIZARD_depth_to_bedrock").sum()),
        "base_pick_minus_usgs_ft": {"n": int(ok_pick.sum()), "median": float(np.nanmedian(resid[ok_pick])),
                                    "mad": float(np.nanmedian(np.abs(resid[ok_pick] - np.nanmedian(resid[ok_pick]))))},
        "sat2009_wells_minus_usgs_raster_ft": {"n": int(len(diff)), "median": float(diff.median()) if len(diff) else None,
                                               "mae": float(diff.abs().mean()) if len(diff) else None,
                                               "corr": float(np.corrcoef(a09.sat_thick_ft, a09.sat_thick_2009_usgs_ft)[0, 1]) if len(diff) > 2 else None},
        "negative_sat_thick_annual_values": int((ann.sat_thick_ft < 0).sum()),
        "base_contour_arcs_used": n_arcs,
        "per_county": per_c.reset_index().to_dict(orient="records"),
    }
    (OUT / "wells_summary.json").write_text(json.dumps(summary, indent=1, default=float))
    print(json.dumps({k: v for k, v in summary.items() if k != "per_county"}, indent=1, default=float))
    print(per_c.to_string())


if __name__ == "__main__":
    main()
