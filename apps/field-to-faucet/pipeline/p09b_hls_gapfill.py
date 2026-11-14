"""Fill the 2025 MODIS 13Q1 gap (no composites on Planetary Computer for 16-day windows starting 2025-07-04 ..
2025-11-09) with NASA HLS v2 (Landsat L30 + Sentinel-2 S30) resampled to the MODIS 250 m row-crop mask.

Source: Planetary Computer `hls2-l30` + `hls2-s30` (https://planetarycomputer.microsoft.com/dataset/hls2-l30,
.../hls2-s30). Bands: red B04, NIR B05 (L30) / B8A (S30), Fmask; scale 0.0001. Each scene is read at COG overview
level 1 (120 m; HLS overviews are NEAREST, i.e. a 30 m point sample every 120 m).

Per scene and masked MODIS pixel (p08 mask, 231.656 m): the 4 sub-points at the pixel centre +- PX/4 are sampled.
clear sub-point = Fmask bits 1-4 (cloud, adjacent cloud, shadow, snow) all 0 and valid reflectance;
snow = bit 4 and bits 1-3 clear; cloud = any of bits 1-3. A pixel is *clear* on a scene when >= 3 sub-points are
clear and none is cloud; its NDVI is the mean of the clear sub-points.

Composites mimic MOD13Q1/MYD13Q1: the same 16-day windows (Terra starts DOY 1, 17, ...; Aqua DOY 9, 25, ...);
per pixel the maximum NDVI over clear scenes in the window (maximum-value compositing); valid = >= 1 clear scene;
snow = no clear scene but >= 1 snow scene; cloud = observed but neither.

Calibration: pixel-level pairs (HLS MVC NDVI, MODIS NDVI) on the same composite windows, where both are valid, over
Jun 25-Nov 30 of 2023 and 2024 plus the 2025 composites bracketing the gap -> empirical quantile mapping of HLS NDVI to
the MODIS NDVI distribution, applied before thresholding (0.25 / 0.30 / 0.35). Leave-one-year-out check reported.

Outputs:
  data/raw/modis/hls/<item>.npz            per-scene samples at masked pixels (cache)
  data/processed/cover_hls_8day.parquet    basin x composite (raw and calibrated), same columns as cover_basin_8day
  data/processed/cover_hls_huc12_8day.parquet  huc12 x composite (calibrated) for the gap windows
  data/processed/cover_hls_calibration.json    HLS-vs-MODIS agreement before / after mapping
p09_modis_cover.py merges the gap windows into cover_basin_8day / cover_basin_daily (gapfill_src = 'hls'); this script
re-runs it at the end unless --no-merge. HUC-12 gap-fill stays in cover_hls_huc12_8day.parquet (kept out of
cover_huc12_8day so MODIS-vs-HLS comparisons there are not contaminated).
Needs the p09 MODIS cache (run p09_modis_cover.py once first). ~7 min of reads for 1,526 scenes (6 threads), then ~1 min.
Run: python3 pipeline/p09b_hls_gapfill.py [--fetch-only] [--max-minutes N] [--no-merge]
"""
import os

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF")

import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pystac_client  # noqa: E402
import rasterio  # noqa: E402
from pyproj import Transformer  # noqa: E402

from common import PROC, RAW, STAC_URL  # noqa: E402
from p09_modis_cover import BASINS, THRESH, cache_path, sign  # noqa: E402

OUT = RAW / "modis"
HCACHE = OUT / "hls"
HCACHE.mkdir(parents=True, exist_ok=True)
SINU = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
X0, Y0 = -20015109.354, 10007554.677
PX = 1111950.5197665233 / 4800.0
OVR_LEVEL = 1          # 120 m
OVR_RES = 120.0
OVR_N = 915
CLOUD_MAX = 75         # scene-level eo:cloud_cover filter (Fmask does the pixel-level work)
WORKERS = 6
# HLS search periods: priority order (gap first, then calibration years)
PERIODS = [("gap2025", "2025-06-01", "2025-12-08"),
           ("cal2024", "2024-06-24", "2024-12-04"),
           ("cal2023", "2023-06-24", "2023-12-04")]
GAP_STARTS = ("2025-07-04", "2025-11-09")   # first / last missing MODIS composite_start
CAL_MD = (625, 1130)  # calibration composites: composite_start Jun 25 .. Nov 30 (2023, 2024; 2025 bracketing the gap)
NIR = {"hls2-l30": "B05", "hls2-s30": "B8A"}


# ---------------------------------------------------------------- geometry
def mask_points():
    z = np.load(OUT / "mask_grid.npz")
    r0, c0 = z["offset"]
    rr, cc = np.nonzero(z["mask"])
    gr, gc = (rr + r0).astype(np.float64), (cc + c0).astype(np.float64)
    x = X0 + (gc + 0.5) * PX
    y = Y0 - (gr + 0.5) * PX
    d = PX / 4
    sx = np.stack([x - d, x + d, x - d, x + d], 1)
    sy = np.stack([y + d, y + d, y - d, y - d], 1)
    return dict(n=len(x), sx=sx, sy=sy, basin_id=z["basin_id"][rr, cc], huc_idx=z["huc_idx"][rr, cc],
                huc12=z["huc12"], basin_of_idx=z["basin_of_idx"])


def tile_index(pts, tiles):
    """tiles: {tile: (epsg, ulx, uly)} -> {tile: (pixel indices fully inside, rows (k,4), cols (k,4))}"""
    out = {}
    tr = {}
    for t, (epsg, ulx, uly) in tiles.items():
        if epsg not in tr:
            f = Transformer.from_crs(SINU, f"EPSG:{epsg}", always_xy=True)
            ux, uy = f.transform(pts["sx"].ravel(), pts["sy"].ravel())
            tr[epsg] = (ux.reshape(-1, 4), uy.reshape(-1, 4))
        ux, uy = tr[epsg]
        col = np.floor((ux - ulx) / OVR_RES).astype(np.int64)
        row = np.floor((uly - uy) / OVR_RES).astype(np.int64)
        inside = ((col >= 0) & (col < OVR_N) & (row >= 0) & (row < OVR_N)).all(1)
        idx = np.nonzero(inside)[0]
        out[t] = (idx, row[idx].astype(np.int16), col[idx].astype(np.int16))
    return out


def select_tiles(tix, pts):
    """Greedy set cover of masked pixels (Raccoon first). Returns ordered tile list and coverage stats."""
    sel = []
    for basin_code in (1, 2):
        need = pts["basin_id"] == basin_code
        cov = np.zeros(pts["n"], bool)
        for t in sel:
            cov[tix[t][0]] = True
        while True:
            gains = {t: int((need & ~cov)[tix[t][0]].sum()) for t in tix if t not in sel}
            if not gains:
                break
            t, g = max(gains.items(), key=lambda kv: kv[1])
            if g < 0.002 * need.sum():
                break
            sel.append(t)
            cov[tix[t][0]] = True
    cov = np.zeros(pts["n"], bool)
    for t in sel:
        cov[tix[t][0]] = True
    stats = {BASINS[b]: float(cov[pts["basin_id"] == b].mean()) for b in (1, 2)}
    return sel, stats


# ---------------------------------------------------------------- STAC
def search_items():
    client = pystac_client.Client.open(STAC_URL)
    rows = []
    for pname, a, b in PERIODS:
        for col in NIR:
            for it in client.search(collections=[col], bbox=[-96.12, 41.46, -93.58, 44.27],
                                    datetime=f"{a}/{b}").items():
                p = it.properties
                rows.append(dict(id=it.id, col=col, tile=it.id.split(".")[2], period=pname,
                                 dt=pd.Timestamp(p["datetime"]).tz_convert(None), cloud=p.get("eo:cloud_cover", 100),
                                 epsg=int(str(p["proj:code"]).split(":")[1]), ulx=p["proj:transform"][2],
                                 uly=p["proj:transform"][5], item=it))
    df = pd.DataFrame(rows).drop_duplicates("id")
    return df


# ---------------------------------------------------------------- per-scene read
def read_band(href, a_max=5):
    err = None
    for a in range(a_max):
        try:
            with rasterio.open(sign(href), overview_level=OVR_LEVEL) as s:
                if s.width != OVR_N:
                    raise RuntimeError(f"unexpected overview width {s.width}")
                return s.read(1)
        except Exception as e:  # 403 expired SAS / transient -> retry with fresh signature
            err = e
            time.sleep(2 * (a + 1))
    raise RuntimeError(str(err)[:200])


def fetch_scene(r, tix):
    f = HCACHE / f"{r.id}.npz"
    if f.exists():
        return r.id, "cached"
    idx, rows, cols = tix[r.tile]
    fm = read_band(r.item.assets["Fmask"].href)[rows, cols]  # (k, 4)
    nod = fm == 255
    cloud = ~nod & ((fm & 0b1110) != 0)
    snow = ~nod & ~cloud & ((fm & 0b10000) != 0)
    clear = ~nod & ~cloud & ~snow
    ndvi = np.full(len(idx), -32768, np.int16)
    if clear.any():
        red = read_band(r.item.assets["B04"].href)[rows, cols].astype(np.float32)
        nir = read_band(r.item.assets[NIR[r.col]].href)[rows, cols].astype(np.float32)
        ok = clear & (red > -9999) & (nir > -9999) & ((red + nir) > 0)
        clear = ok
        v = np.where(ok, (nir - red) / np.where(ok, nir + red, 1), 0)
        n = ok.sum(1)
        m = np.where(n > 0, v.sum(1) / np.maximum(n, 1), np.nan)
        ndvi = np.where(n > 0, np.clip(np.round(m * 1e4), -10000, 10000), -32768).astype(np.int16)
    tmp = f.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, ndvi=ndvi, n_clear=clear.sum(1).astype(np.uint8), n_snow=snow.sum(1).astype(np.uint8),
                        n_cloud=cloud.sum(1).astype(np.uint8), n_nod=nod.sum(1).astype(np.uint8))
    os.replace(tmp, f)
    return r.id, "fetched"


def fetch_all(items, tix, max_minutes):
    t0 = time.time()
    todo = items[~items.id.map(lambda i: (HCACHE / f"{i}.npz").exists())]
    print(f"scenes: {len(items)} selected, {len(items) - len(todo)} cached, {len(todo)} to fetch", flush=True)
    fails, n_f, stopped = [], 0, False
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {}
        it = iter(todo.itertuples())
        for r in it:  # bounded submission so the time box can stop cleanly
            futs[ex.submit(fetch_scene, r, tix)] = r.id
            if len(futs) >= WORKERS * 3:
                break
        while futs:
            done = next(as_completed(futs))
            rid = futs.pop(done)
            try:
                _, st = done.result()
                n_f += st == "fetched"
            except Exception as e:
                fails.append(f"{rid}: {e}")
            if n_f and n_f % 100 == 0:
                print(f"  {n_f} fetched, {len(fails)} failed, {time.time() - t0:.0f}s", flush=True)
            if not stopped and time.time() - t0 > max_minutes * 60:
                stopped = True
                print(f"time box {max_minutes} min reached; finishing in-flight reads", flush=True)
            if not stopped:
                nxt = next(it, None)
                if nxt is not None:
                    futs[ex.submit(fetch_scene, nxt, tix)] = nxt.id
    print(f"fetch done: {n_f} fetched, {len(fails)} failed, stopped={stopped}, {time.time() - t0:.0f}s", flush=True)
    return fails, stopped


# ---------------------------------------------------------------- compositing
def composite_windows(a, b):
    """MODIS 16-day composite starts (Terra DOY 1+16k, Aqua DOY 9+16k) with start in [a, b]."""
    out = []
    for y in range(pd.Timestamp(a).year, pd.Timestamp(b).year + 1):
        for sensor, d0 in (("terra", 1), ("aqua", 9)):
            for d in range(d0, 367, 16):
                s = pd.Timestamp(y, 1, 1) + pd.Timedelta(days=d - 1)
                if s.year == y and pd.Timestamp(a) <= s <= pd.Timestamp(b):
                    out.append((s, sensor))
    return sorted(out)


def hls_composite(scenes, tix, n, start):
    """Per-pixel MVC over clear scenes with acquisition date in [start, start+16)."""
    end = start + pd.Timedelta(days=16)
    sub = scenes[(scenes.dt >= start) & (scenes.dt < end)]
    best = np.full(n, -32768, np.int16)
    bday = np.full(n, np.nan, np.float32)
    nclr = np.zeros(n, np.int16)
    nsnow = np.zeros(n, np.int16)
    nobs = np.zeros(n, np.int16)
    for r in sub.itertuples():
        f = HCACHE / f"{r.id}.npz"
        if not f.exists():
            continue
        z = np.load(f)
        idx = tix[r.tile][0]
        clear = (z["n_clear"] >= 3) & (z["n_cloud"] == 0)
        snow = (z["n_snow"] >= 2) & (z["n_cloud"] == 0) & ~clear
        obs = z["n_nod"] < 4
        v = np.where(clear, z["ndvi"], -32768).astype(np.int16)
        upd = v > best[idx]
        bi = idx[upd]
        best[bi] = v[upd]
        bday[bi] = (r.dt - start).total_seconds() / 86400
        nclr[idx] += clear
        nsnow[idx] += snow
        nobs[idx] += obs
    valid = nclr > 0
    snow = ~valid & (nsnow > 0)
    present = nobs > 0
    cloud = present & ~valid & ~snow
    return dict(ndvi=best, valid=valid, snow=snow, cloud=cloud, present=present, off=bday, n_scenes=len(sub))


def counts(g, ng, c, ndvi_map, present_any):
    bc = lambda w=None: np.bincount(g, weights=w, minlength=ng)  # noqa: E731
    valid = c["valid"]
    nd = np.where(valid, ndvi_map, np.nan)
    d = {"n_px": bc(), "n_present": bc(c["present"] | present_any), "n_valid": bc(valid), "n_snow": bc(c["snow"]),
         "n_cloud": bc(c["cloud"]), "ndvi_sum": bc(np.where(valid, nd, 0.0)),
         "off_sum": bc(np.where(valid & np.isfinite(c["off"]), c["off"], 0.0))}
    d["n_fill"] = d["n_px"] - d["n_valid"] - d["n_snow"] - d["n_cloud"]
    for tk, th in THRESH.items():
        d[f"n_liv_{tk}"] = bc(valid & (nd >= th / 1e4))
    return pd.DataFrame(d)


def derive_hls(df):
    nv = df.n_valid.replace(0, np.nan)
    nobs = (df.n_valid + df.n_snow).replace(0, np.nan)
    npx = df.n_px.replace(0, np.nan)
    o = pd.DataFrame(index=df.index)
    o["n_px"] = df.n_px.astype(int)
    o["n_valid"] = df.n_valid.astype(int)
    o["tile_cover_frac"] = df.n_present / npx
    o["valid_frac"] = df.n_valid / npx
    o["snow_frac"] = df.n_snow / npx
    o["cloud_frac"] = df.n_cloud / npx
    o["fill_frac"] = df.n_fill / npx
    o["living_share"] = df.n_liv_t30 / nv
    o["bare_share"] = 1 - o.living_share
    o["snow_share"] = df.n_snow / nobs
    o["bare_nonsnow_share"] = (df.n_valid - df.n_liv_t30) / nobs
    o["mean_ndvi"] = df.ndvi_sum / nv
    for tk in ("t25", "t35"):
        o[f"living_share_{tk}"] = df[f"n_liv_{tk}"] / nv
        o[f"bare_share_{tk}"] = 1 - o[f"living_share_{tk}"]
    o["obs_off"] = df.off_sum / nv
    return o


# ---------------------------------------------------------------- MODIS per-pixel values for calibration
def modis_pixels(pts, start, sensor):
    """MODIS NDVI (float, NaN where not valid) at masked pixels for one composite, from the p09 cache."""
    prod = "MOD13Q1" if sensor == "terra" else "MYD13Q1"
    adate = f"A{start.year}{start.dayofyear:03d}"
    z = np.load(OUT / "mask_grid.npz")
    r0, c0 = z["offset"]
    rr, cc = np.nonzero(z["mask"])
    gr, gc = rr + r0, cc + c0
    h, v = gc // 4800, gr // 4800
    out = np.full(pts["n"], np.nan, np.float32)
    found = False
    for hh, vv in sorted(set(zip(h.tolist(), v.tolist()))):
        f = cache_path((prod, adate, f"h{hh:02d}v{vv:02d}"))
        if not f.exists():
            continue
        found = True
        sel = np.nonzero((h == hh) & (v == vv))[0]   # same ordering as p09 load_mask (row-major nonzero)
        zz = np.load(f)
        ok = (zz["rel"] <= 1) & (zz["ndvi"] > -3000)
        out[sel] = np.where(ok, zz["ndvi"] * 1e-4, np.nan)
    return out if found else None


class QMap:
    """Empirical quantile mapping HLS NDVI -> MODIS NDVI (monotone piecewise linear on 201 quantiles)."""

    def __init__(self, hls, mod):
        q = np.linspace(0, 1, 201)
        self.xq = np.quantile(hls, q)
        self.yq = np.quantile(mod, q)
        self.xq = np.maximum.accumulate(self.xq + np.arange(len(q)) * 1e-9)

    def __call__(self, x):
        return np.interp(x, self.xq, self.yq)


def stats(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if len(a) < 3:
        return {"n": int(len(a))}
    return {"n": int(len(a)), "r": round(float(np.corrcoef(a, b)[0, 1]), 3),
            "bias_hls_minus_modis": round(float(np.mean(a - b)), 3),
            "mae": round(float(np.mean(np.abs(a - b))), 3), "rmse": round(float(np.sqrt(np.mean((a - b) ** 2))), 3)}


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    fetch_only = "--fetch-only" in sys.argv
    max_min = float(sys.argv[sys.argv.index("--max-minutes") + 1]) if "--max-minutes" in sys.argv else 45.0
    pts = mask_points()
    items = search_items()
    print(f"STAC: {len(items)} HLS items, {items.tile.nunique()} tiles, {time.time() - t0:.0f}s", flush=True)
    tiles = items.drop_duplicates("tile").set_index("tile")[["epsg", "ulx", "uly"]]
    tix = tile_index(pts, {t: tuple(r) for t, r in tiles.iterrows()})
    sel, cov = select_tiles(tix, pts)
    print(f"tiles selected (greedy cover, Raccoon first): {sel}; coverage {cov}", flush=True)
    items = items[items.tile.isin(sel) & (items.cloud <= CLOUD_MAX)].copy()
    rac_tiles = set()
    for t in sel:
        if (pts["basin_id"][tix[t][0]] == 1).any():
            rac_tiles.add(t)
    # priority: gap period Raccoon tiles, gap DM-only tiles, then calibration years (Raccoon tiles first)
    items["prio"] = items.period.map({p[0]: i for i, p in enumerate(PERIODS)}) * 2 + (~items.tile.isin(rac_tiles))
    items = items.sort_values(["prio", "dt"]).reset_index(drop=True)
    print(items.groupby(["period", "col"]).size().to_string(), flush=True)
    fails, stopped = fetch_all(items, tix, max_min)
    if fetch_only:
        return
    build(pts, items, tix, sel, cov, fails, stopped)
    print(f"p09b done in {time.time() - t0:.0f}s")
    if "--no-merge" not in sys.argv:
        print("\n==== re-running p09_modis_cover.py to merge the gap-fill ====", flush=True)
        import p09_modis_cover
        p09_modis_cover.main()


def build(pts, items, tix, sel, cov, fails, stopped):
    n = pts["n"]
    have = items[items.id.map(lambda i: (HCACHE / f"{i}.npz").exists())].copy()
    print(f"scenes available: {len(have)} of {len(items)}")
    wins = []
    for pname, a, b in PERIODS:
        wins += composite_windows(a, (pd.Timestamp(b) - pd.Timedelta(days=15)).isoformat())
    gap0, gap1 = map(pd.Timestamp, GAP_STARTS)
    present_none = np.zeros(n, bool)
    comps = {}
    for start, sensor in wins:
        c = hls_composite(have, tix, n, start)
        if c["n_scenes"] == 0:
            continue
        comps[(start, sensor)] = c
    print(f"HLS composites built: {len(comps)}")

    # ---- calibration pairs (pixel level)
    pairs = []
    for (start, sensor), c in comps.items():
        md = start.month * 100 + start.day
        in_cal = (CAL_MD[0] <= md <= CAL_MD[1]) and not (gap0 <= start <= gap1)
        if not in_cal:
            continue
        m = modis_pixels(pts, start, sensor)
        if m is None:
            continue
        ok = c["valid"] & np.isfinite(m)
        if ok.sum() < 1000:
            continue
        pairs.append(dict(start=start, sensor=sensor, idx=np.nonzero(ok)[0], h=c["ndvi"][ok] * 1e-4, m=m[ok],
                          mod_all=m))
    print(f"calibration composites with MODIS overlap: {len(pairs)}")
    allh = np.concatenate([p["h"] for p in pairs])
    allm = np.concatenate([p["m"] for p in pairs])
    qmap = QMap(allh, allm)

    # basin-level comparison, raw and mapped, plus leave-one-year-out mapping
    bid = pts["basin_id"]
    rows = []
    for p in pairs:
        yr = p["start"].year
        others = [q for q in pairs if q["start"].year != yr]
        qloo = QMap(np.concatenate([q["h"] for q in others]), np.concatenate([q["m"] for q in others])) if others else qmap
        for b, bn in BASINS.items():
            sel_b = bid[p["idx"]] == b
            if sel_b.sum() < 500:
                continue
            h, m = p["h"][sel_b], p["m"][sel_b]
            # MODIS share over all its valid pixels in the basin (what cover_basin_8day reports)
            mall = p["mod_all"][(bid == b) & np.isfinite(p["mod_all"])]
            rows.append(dict(basin=bn, start=p["start"], year=yr, sensor=p["sensor"], n=int(sel_b.sum()),
                             modis_living=float((mall >= 0.30).mean()), modis_living_paired=float((m >= 0.30).mean()),
                             hls_living_raw=float((h >= 0.30).mean()), hls_living_qm=float((qmap(h) >= 0.30).mean()),
                             hls_living_loo=float((qloo(h) >= 0.30).mean()),
                             modis_ndvi=float(mall.mean()), hls_ndvi_raw=float(h.mean()), hls_ndvi_qm=float(qmap(h).mean())))
    cal = pd.DataFrame(rows)
    pix = {"raw": stats(allh, allm), "quantile_mapped": stats(qmap(allh), allm)}
    report = {"pixel_ndvi": pix, "n_pixel_pairs": int(len(allh))}
    groups = ([("all", cal), ("raccoon", cal[cal.basin == "raccoon"]), ("desmoines", cal[cal.basin == "desmoines"])]
              + [(f"year_{y}", cal[cal.year == y]) for y in sorted(cal.year.unique())])
    for name, sub in groups:
        report[name] = {"n_composites": int(len(sub)),
                        "living_share_raw": stats(sub.hls_living_raw.to_numpy(), sub.modis_living.to_numpy()),
                        "living_share_quantile_mapped": stats(sub.hls_living_qm.to_numpy(), sub.modis_living.to_numpy()),
                        "living_share_leave_one_year_out": stats(sub.hls_living_loo.to_numpy(), sub.modis_living.to_numpy()),
                        "mean_ndvi_raw": stats(sub.hls_ndvi_raw.to_numpy(), sub.modis_ndvi.to_numpy()),
                        "mean_ndvi_quantile_mapped": stats(sub.hls_ndvi_qm.to_numpy(), sub.modis_ndvi.to_numpy())}
    # Fall-only (Sep 15 - Nov 30 starts): the season the gap-fill matters for
    fall = cal[(cal.start.dt.month * 100 + cal.start.dt.day) >= 915]
    report["fall_sep15_nov30"] = {"n_composites": int(len(fall)),
                                  "living_share_raw": stats(fall.hls_living_raw.to_numpy(), fall.modis_living.to_numpy()),
                                  "living_share_quantile_mapped": stats(fall.hls_living_qm.to_numpy(), fall.modis_living.to_numpy()),
                                  "living_share_leave_one_year_out": stats(fall.hls_living_loo.to_numpy(), fall.modis_living.to_numpy())}

    # ---- composites -> basin + HUC-12 tables (calibrated NDVI)
    huc = pts["huc_idx"].astype(np.int64)
    nh = len(pts["huc12"])
    brows, hrows = [], []
    for (start, sensor), c in comps.items():
        nd_raw = np.where(c["valid"], c["ndvi"] * 1e-4, np.nan)
        nd_qm = np.where(c["valid"], qmap(np.where(c["valid"], nd_raw, 0)), np.nan)
        for kind, nd in (("raw", nd_raw), ("qm", nd_qm)):
            b = counts(bid.astype(np.int64), 3, c, nd, present_none).iloc[1:]
            b.index = [BASINS[i] for i in b.index]
            bd = derive_hls(b)
            bd["basin"] = bd.index
            bd["calib"] = kind
            bd["composite_start"] = start.date()
            bd["date"] = (start + pd.Timedelta(days=8)).date()
            bd["sensor"] = sensor
            bd["n_scenes"] = c["n_scenes"]
            bd["in_gap"] = bool(gap0 <= start <= gap1)
            brows.append(bd)
        if gap0 <= start <= gap1:
            h = derive_hls(counts(np.where(huc >= 0, huc, 0), nh, c, nd_qm, present_none))
            h["huc12"] = pts["huc12"]
            h["basin"] = np.array(list(BASINS.values()))[pts["basin_of_idx"] - 1]
            h["date"], h["sensor"] = (start + pd.Timedelta(days=8)).date(), sensor
            hrows.append(h[h.n_px > 0])
    b8 = pd.concat(brows, ignore_index=True)
    st = pd.to_datetime(b8.composite_start)
    b8["obs_date"] = st + pd.to_timedelta(b8.obs_off.fillna(8.0), unit="D")
    b8 = b8.drop(columns=["obs_off"]).sort_values(["calib", "basin", "date"]).reset_index(drop=True)
    fl = b8.select_dtypes("float").columns
    b8[fl] = b8[fl].astype("float32")
    b8.to_parquet(PROC / "cover_hls_8day.parquet", compression="zstd", index=False)
    if hrows:
        h8 = pd.concat(hrows, ignore_index=True)
        h8 = h8[["huc12", "basin", "date", "sensor", "n_px", "n_valid", "tile_cover_frac", "valid_frac", "living_share",
                 "bare_share", "snow_share", "bare_nonsnow_share", "mean_ndvi"]]
        for col in h8.select_dtypes("float").columns:
            h8[col] = h8[col].astype("float32").round(4)
        h8.to_parquet(PROC / "cover_hls_huc12_8day.parquet", compression="zstd", index=False)

    gapq = b8[(b8.calib == "qm") & b8.in_gap]
    report.update({
        "status": "ok" if not stopped else "partial (time box reached)",
        "method": __doc__.split("Outputs:")[0].strip(),
        "tiles": sel, "tile_coverage_of_mask": cov, "scenes_used": int(len(have)), "scene_cloud_max": CLOUD_MAX,
        "fetch_failures": fails[:20], "n_fetch_failures": len(fails),
        "quantile_map": {"hls_q": np.round(qmap.xq[::10], 4).tolist(), "modis_q": np.round(qmap.yq[::10], 4).tolist()},
        "gap_composites": {bn: gapq[gapq.basin == bn][["date", "valid_frac", "living_share", "tile_cover_frac"]]
                           .assign(date=lambda d: d.date.astype(str)).round(3).to_dict("records") for bn in BASINS.values()},
    })
    (PROC / "cover_hls_calibration.json").write_text(json.dumps(report, indent=1, default=str))
    pd.set_option("display.width", 200, "display.max_columns", 30)
    print(json.dumps({k: report[k] for k in ("pixel_ndvi", "all", "fall_sep15_nov30")}, indent=1))
    print(cal.groupby(["basin", "year"])[["modis_living", "hls_living_raw", "hls_living_qm", "hls_living_loo"]].mean().round(3))
    print(gapq[["basin", "date", "sensor", "n_scenes", "valid_frac", "tile_cover_frac", "living_share", "bare_share",
                "snow_share"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
