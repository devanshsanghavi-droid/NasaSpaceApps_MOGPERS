"""HLS (Harmonized Landsat Sentinel-2 v2.0) irrigation detection for focus counties (Haskell 20081 + Finney 20055)
in mid-summer dry spells.

Steps (all real downloads, cached under data/raw/hls/ and data/raw/power_land/):
 1. NASA POWER daily precipitation (PRECTOTCORR, mm/day) at the county centroid, Jun-Sep of each year
    (https://power.larc.nasa.gov/api/temporal/daily/point). The dry spell = the 14-day window inside Jul 1 - Aug 31 with the
    least rain (ties -> later window); scenes are taken from window start + 5 d to window end + 3 d so the crop has been
    without rain for a while.
 2. HLS v2 scenes (Planetary Computer `hls2-l30` + `hls2-s30`, eo:cloud_cover < 60) over the county inside those dates.
    Bands red/NIR (L30 B04/B05, S30 B04/B8A), scale 1e-4, fill -9999; Fmask clear = bits 1-4 (cloud, adjacent cloud,
    shadow, snow/ice) all 0 and Fmask != 255. Windowed reads at native 30 m resolution over the county only.
 3. Sample points: 30 m CDL pixels of corn / soybeans / sorghum (CDL of the same year) whose 3x3 neighbourhood is the
    same class (field interiors), inside the county. Labels from WIMAS (data/processed/wimas_use.parquet):
    irrigated = an IRR point of diversion that reported water (af_reported > 0) that year lies within 800 m;
    dryland = no WIMAS point of diversion of any use/year within 1600 m; 800-1600 m = ambiguous (no label).
    Because wells are dense (most cropland is within 800 m of a well), sampling is STRATIFIED: per crop and year up to
    75 irrigated-labelled + 75 dryland-labelled pixels, plus 50 unstratified 'random' pixels (not used for accuracy).
 4. NDVI per point = maximum over clear HLS observations in the dry-spell scene set (max-composite limits residual cloud);
    n_obs = number of clear observations.
 5. Threshold irrigated := NDVI > t, with t chosen on a random half of the stratified labelled points (max balanced accuracy) and
    evaluated on the other half (accuracy, Cohen's kappa, precision, recall). Done pooled over years and per year.

Output: data/processed/hls_irrigation.parquet (sample_id, year, ...), data/processed/hls_irrigation_metrics.json
Usage : python3 pipeline/nasa_hls_irrigation.py [fips[,fips...]] [years...]   (default 20081,20055 2022 2023)
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasa_cdl_common import GDAL_ENV, PROC, RAW, STAC, cdl_path, region_counties, retry  # noqa: E402
from nasa_common import http_get  # noqa: E402

HRAW = RAW / "hls"
PRAW = RAW / "power_land"
N_PER_CROP = 150          # per crop and year: 75 irrigated-labelled + 75 dryland-labelled
N_RANDOM = 50
CROPS = {1: "corn", 5: "soybeans", 4: "sorghum"}
IRR_R, DRY_R = 800.0, 1600.0
BANDS = {"L30": {"red": "B04", "nir": "B05"}, "S30": {"red": "B04", "nir": "B8A"}}
SEED = 20260


def power_daily(lon, lat, year):
    p = PRAW / f"power_prectot_{lon:.3f}_{lat:.3f}_{year}.json"
    if not p.exists():
        PRAW.mkdir(parents=True, exist_ok=True)
        r = http_get("https://power.larc.nasa.gov/api/temporal/daily/point",
                     params=dict(parameters="PRECTOTCORR", community="AG", longitude=lon, latitude=lat,
                                 start=f"{year}0601", end=f"{year}0930", format="JSON"))
        p.write_text(r.text)
    d = json.loads(p.read_text())["properties"]["parameter"]["PRECTOTCORR"]
    s = pd.Series(d, dtype=float)
    s.index = pd.to_datetime(s.index, format="%Y%m%d")
    return s.where(s > -900)


def dry_spell(pr, year, days=14):
    jj = pr[f"{year}-07-01":f"{year}-08-31"]
    roll = jj.rolling(days).sum().dropna()
    end = roll[roll == roll.min()].index[-1]
    start = end - pd.Timedelta(days=days - 1)
    return start, end, float(roll.min())


def hls_items(bbox, t0, t1):
    import planetary_computer
    import pystac_client
    c = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    out = []
    for col, sensor in [("hls2-l30", "L30"), ("hls2-s30", "S30")]:
        s = c.search(collections=[col], bbox=bbox, datetime=f"{t0:%Y-%m-%d}/{t1:%Y-%m-%d}",
                     query={"eo:cloud_cover": {"lt": 60}})
        for it in s.items():
            out.append(dict(id=it.id, sensor=sensor, datetime=str(it.datetime), cloud=it.properties.get("eo:cloud_cover"),
                            tile=it.id.split(".")[2], epsg=it.properties.get("proj:epsg") or it.properties.get("proj:code"),
                            assets={k: it.assets[v].href.split("?")[0] for k, v in {**BANDS[sensor], "fmask": "Fmask"}.items()}))
    return out


def read_win(href, bounds_lonlat):
    import planetary_computer

    def go():
        with rasterio.Env(**GDAL_ENV), rasterio.open(planetary_computer.sign(href)) as src:
            t = Transformer.from_crs(4326, src.crs, always_xy=True)
            x, y = t.transform([bounds_lonlat[0], bounds_lonlat[2], bounds_lonlat[0], bounds_lonlat[2]],
                               [bounds_lonlat[1], bounds_lonlat[1], bounds_lonlat[3], bounds_lonlat[3]])
            win = from_bounds(min(x), min(y), max(x), max(y), transform=src.transform).round_offsets().round_lengths()
            arr = src.read(1, window=win, boundless=True, fill_value=src.nodata if src.nodata is not None else 0)
            return arr, src.window_transform(win), src.crs
    return retry(go)


def sample_scene(it, pts, bounds):
    """NDVI at points for one scene (NaN where not clear / outside)."""
    fm, tr, crs = read_win(it["assets"]["fmask"], bounds)
    t = Transformer.from_crs(4326, crs, always_xy=True)
    x, y = t.transform(pts.lon.values, pts.lat.values)
    c, r = ~tr * (x, y)
    r = np.floor(r).astype(int)
    c = np.floor(c).astype(int)
    inside = (r >= 0) & (r < fm.shape[0]) & (c >= 0) & (c < fm.shape[1])
    r, c = np.clip(r, 0, fm.shape[0] - 1), np.clip(c, 0, fm.shape[1] - 1)
    q = fm[r, c].astype(np.int32)
    clear = inside & (q != 255) & ((q & 0b11110) == 0)
    out = np.full(len(pts), np.nan, np.float32)
    if clear.sum() == 0:
        return out, 0
    red, _, _ = read_win(it["assets"]["red"], bounds)
    nir, _, _ = read_win(it["assets"]["nir"], bounds)
    rv = red[r, c].astype(np.float32)
    nv = nir[r, c].astype(np.float32)
    ok = clear & (rv > 0) & (nv > 0) & (rv != -9999) & (nv != -9999)
    out[ok] = (nv[ok] - rv[ok]) / (nv[ok] + rv[ok])
    return out, int(ok.sum())


def wimas_trees(year):
    """KD-trees of (a) IRR points of diversion reporting water (af_reported > 0) in `year`, (b) all WIMAS points (any use/year)."""
    from scipy.spatial import cKDTree
    p = PROC / "wimas_use.parquet"
    if not p.exists():
        return None, None, "wimas_use.parquet not available"
    w = pd.read_parquet(p, columns=["pdiv_id", "year", "use", "lon", "lat", "af_reported"]).dropna(subset=["lon", "lat"])
    x, y = Transformer.from_crs(4326, 5070, always_xy=True).transform(w.lon.values, w.lat.values)
    w["x"], w["y"] = x, y
    allp = w.drop_duplicates("pdiv_id")
    irr = w[(w.year == year) & (w.use == "IRR") & (w.af_reported > 0)].drop_duplicates("pdiv_id")
    return (cKDTree(irr[["x", "y"]].values), cKDTree(allp[["x", "y"]].values),
            f"{len(allp)} WIMAS points of diversion; {len(irr)} IRR points reporting water in {year}")


def sample_points(fips, geom5070, year, rng, t_irr, t_any):
    """Field-interior CDL pixels (3x3 same class) of corn/soybeans/sorghum in the county. Per crop: up to N_PER_CROP/2
    pixels labelled irrigated and N_PER_CROP/2 labelled dryland (stratified, so both classes are represented even in
    well-dense counties), plus N_RANDOM unstratified pixels (stratum 'random', for county-prevalence NDVI distributions)."""
    from rasterio.features import geometry_mask
    with rasterio.open(cdl_path(year)) as src:
        b = geom5070.bounds
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        a = src.read(1, window=win)
        tr = src.window_transform(win)
    inside = ~geometry_mask([geom5070], out_shape=a.shape, transform=tr)
    pts = []
    for code, name in CROPS.items():
        m = (a == code)
        pure = m.copy()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                pure &= np.roll(np.roll(m, dr, 0), dc, 1)
        pure &= inside
        rr, cc = np.nonzero(pure)
        if len(rr) == 0:
            continue
        x, y = tr * (cc + 0.5, rr + 0.5)
        xy = np.c_[x, y]
        d_irr = t_irr.query(xy)[0] if t_irr is not None else np.full(len(x), np.inf)
        d_any = t_any.query(xy)[0] if t_any is not None else np.full(len(x), np.inf)
        lab = np.where(d_irr <= IRR_R, 1, np.where(d_any > DRY_R, 0, -1))
        for stratum, sel, n in [("irrigated", lab == 1, N_PER_CROP // 2), ("dryland", lab == 0, N_PER_CROP // 2),
                                ("random", np.ones(len(x), bool), N_RANDOM)]:
            ii = np.nonzero(sel)[0]
            if len(ii) == 0:
                continue
            k = rng.choice(ii, size=min(n, len(ii)), replace=False)
            pts.append(pd.DataFrame(dict(x5070=x[k], y5070=y[k], cdl_code=code, crop=name, stratum=stratum,
                                         dist_irr_pdiv_m=np.round(d_irr[k]), dist_any_pdiv_m=np.round(d_any[k]),
                                         label=lab[k], n_crop_pure_px=len(rr),
                                         n_candidates_irrigated=int((lab == 1).sum()),
                                         n_candidates_dryland=int((lab == 0).sum()))))
    df = pd.concat(pts, ignore_index=True)
    lon, lat = Transformer.from_crs(5070, 4326, always_xy=True).transform(df.x5070.values, df.y5070.values)
    df["lon"], df["lat"] = lon, lat
    lab = pd.Series(pd.NA, index=df.index, dtype="boolean")
    lab[df.label == 1] = True
    lab[df.label == 0] = False
    df["label_irrigated"] = lab
    return df.drop(columns="label")


def kappa(y, p):
    y, p = np.asarray(y, bool), np.asarray(p, bool)
    po = np.mean(y == p)
    pe = y.mean() * p.mean() + (1 - y.mean()) * (1 - p.mean())
    return float((po - pe) / (1 - pe)) if pe < 1 else np.nan


def evaluate(d, rng):
    d = d[(d.stratum != "random") & d.label_irrigated.notna() & d.ndvi_max.notna()].copy()
    if len(d) < 20 or d.label_irrigated.nunique() < 2:
        return None
    idx = rng.permutation(len(d))
    tr, te = d.iloc[idx[: len(d) // 2]], d.iloc[idx[len(d) // 2:]]
    ys = tr.label_irrigated.astype(bool).values
    best = (-1, None)
    for t in np.round(np.arange(0.20, 0.95, 0.01), 2):
        p = tr.ndvi_max.values > t
        ba = 0.5 * (p[ys].mean() + (~p[~ys]).mean())
        if ba > best[0]:
            best = (ba, t)
    t = best[1]
    y = te.label_irrigated.astype(bool).values
    p = te.ndvi_max.values > t
    return dict(threshold_ndvi=float(t), train_balanced_acc=round(float(best[0]), 3), n_train=len(tr), n_test=len(te),
                n_test_irrigated=int(y.sum()), test_accuracy=round(float(np.mean(p == y)), 3),
                test_balanced_accuracy=round(float(0.5 * (p[y].mean() + (~p[~y]).mean())), 3),
                test_kappa=round(kappa(y, p), 3),
                test_precision_irrigated=round(float(y[p].mean()), 3) if p.any() else None,
                test_recall_irrigated=round(float(p[y].mean()), 3),
                ndvi_median_irrigated=round(float(d[d.label_irrigated.astype(bool)].ndvi_max.median()), 3),
                ndvi_median_dryland=round(float(d[~d.label_irrigated.astype(bool)].ndvi_max.median()), 3))


def run_county(fips, years, g, rng):
    row = g[g.fips == fips].iloc[0]
    geom5070 = g[g.fips == fips].to_crs(5070).geometry.iloc[0]
    bounds = tuple(row.geometry.bounds)
    allpts, meta = [], dict(county_fips=fips, county_name=row["name"], years={})
    for year in years:
        pr = power_daily(row.lon, row.lat, year)
        s0, s1, tot = dry_spell(pr, year)
        t0, t1 = s0 + pd.Timedelta(days=5), s1 + pd.Timedelta(days=3)
        its = hls_items(list(bounds), t0, t1)
        print(f"{fips} {year}: dry spell {s0.date()}..{s1.date()} ({tot:.1f} mm/14 d); {len(its)} HLS items "
              f"{t0.date()}..{t1.date()}", flush=True)
        t_irr, t_any, wmsg = wimas_trees(year)
        pts = sample_points(fips, geom5070, year, rng, t_irr, t_any)
        pts["year"] = year
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(lambda it: sample_scene(it, pts, bounds), its))
        nd = np.vstack([r[0] for r in res]) if res else np.full((1, len(pts)), np.nan)
        scene_info = [dict(id=it["id"], sensor=it["sensor"], date=it["datetime"][:10], tile=it["tile"],
                           cloud_cover=it["cloud"], n_clear_points=r[1]) for it, r in zip(its, res)]
        for sc in scene_info:
            print("   ", sc, flush=True)
        import warnings
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            pts["ndvi_max"] = np.nanmax(nd, 0)
            pts["ndvi_median"] = np.nanmedian(nd, 0)
        pts["n_obs"] = np.isfinite(nd).sum(0)
        dry = pts[pts.label_irrigated == False]  # noqa: E712
        meta["years"][str(year)] = dict(
            power_point=[row.lon, row.lat], dry_spell=[str(s0.date()), str(s1.date())], dry_spell_precip_mm=round(tot, 1),
            jul_aug_precip_mm=round(float(pr[f"{year}-07-01":f"{year}-08-31"].sum()), 1),
            scene_window=[str(t0.date()), str(t1.date())], scenes=scene_info, wimas=wmsg,
            n_dryland_distinct_1km_cells=int(len(set(zip((dry.x5070 // 1000).astype(int), (dry.y5070 // 1000).astype(int))))))
        allpts.append(pts)
    df = pd.concat(allpts, ignore_index=True)
    df["county_fips"] = fips
    return df, meta


def main():
    args = sys.argv[1:]
    counties = (args[0] if args else "20081,20055").split(",")
    years = [int(a) for a in args[1:]] or [2022, 2023]
    g = region_counties()
    rng = np.random.default_rng(SEED)
    parts, meta = [], dict(counties={}, method=__doc__)
    for fips in counties:
        d, m = run_county(fips, years, g, rng)
        parts.append(d)
        meta["counties"][fips] = m
    df = pd.concat(parts, ignore_index=True)
    df.insert(0, "sample_id", [f"{c}_{y}_{i:04d}" for i, (c, y) in enumerate(zip(df.county_fips, df.year))])
    ev = {"pooled": evaluate(df, np.random.default_rng(SEED)),
          "corn_only": evaluate(df[df.crop == "corn"], np.random.default_rng(SEED + 1))}
    for y in years:
        ev[str(y)] = evaluate(df[df.year == y], np.random.default_rng(SEED + y))
        ev[f"{y}_corn"] = evaluate(df[(df.year == y) & (df.crop == "corn")], np.random.default_rng(SEED + y + 1))
    for c in counties:
        ev[c] = evaluate(df[df.county_fips == c], np.random.default_rng(SEED + int(c)))
        for y in years:
            ev[f"{c}_{y}"] = evaluate(df[(df.county_fips == c) & (df.year == y)], np.random.default_rng(SEED + int(c) + y))
    thr = ev["pooled"]["threshold_ndvi"] if ev["pooled"] else None
    pred = pd.Series(pd.NA, index=df.index, dtype="boolean")
    if thr is not None:
        ok = df.ndvi_max.notna()
        pred[ok] = df.ndvi_max[ok] > thr
    df["irrigated_pred"] = pred
    meta["prediction_threshold_ndvi_pooled"] = thr
    meta["metrics"] = ev
    rnd = df[df.stratum == "random"]
    meta["random_sample_pred_irrigated_share"] = (rnd.groupby(["county_fips", "year", "crop"]).irrigated_pred
                                                  .apply(lambda s: round(float(s.dropna().astype(bool).mean()), 3))
                                                  .reset_index().to_dict("records"))
    meta["labels"] = df.groupby(["county_fips", "year", "crop", "stratum"]).label_irrigated.agg(
        n="size", n_irr=lambda s: int((s == True).sum()), n_dry=lambda s: int((s == False).sum())).reset_index().to_dict("records")  # noqa: E712
    lab = df[df.stratum != "random"]
    meta["ndvi_by_crop_label"] = (lab.assign(lab=lab.label_irrigated.astype("string").fillna("NA"))
                                  .groupby(["county_fips", "year", "crop", "lab"]).ndvi_max.describe()[["count", "25%", "50%", "75%"]]
                                  .round(3).reset_index().to_dict("records"))
    cols = ["sample_id", "year", "county_fips", "crop", "cdl_code", "stratum", "lon", "lat", "x5070", "y5070", "ndvi_max",
            "ndvi_median", "n_obs", "dist_irr_pdiv_m", "dist_any_pdiv_m", "label_irrigated", "irrigated_pred", "n_crop_pure_px",
            "n_candidates_irrigated", "n_candidates_dryland"]
    df = df[[c for c in cols if c in df]]
    df.to_parquet(PROC / "hls_irrigation.parquet", index=False)
    (PROC / "hls_irrigation_metrics.json").write_text(json.dumps(meta, indent=1, default=str))
    print(json.dumps({k: (None if v is None else {kk: v[kk] for kk in ("threshold_ndvi", "n_test", "n_test_irrigated",
                      "test_accuracy", "test_kappa", "ndvi_median_irrigated", "ndvi_median_dryland")}) for k, v in ev.items()}))


if __name__ == "__main__":
    main()
