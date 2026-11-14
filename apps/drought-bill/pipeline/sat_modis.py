"""sat module: MODIS Terra MOD13Q1 v6.1 July-August NDVI per county and year (2001-2025), VCI and z-score.

Data: Microsoft Planetary Computer collection `modis-13Q1-061` (STAC; COG assets on modiseuwest.blob.core.windows.net,
signed with planetary_computer). For each Terra (MOD13Q1) 16-day composite whose compositing period STARTS in July or
August (DOY 193/209/225/241, 4 per year per tile) we read the NDVI and pixel_reliability COGs at overview level 1
(factor 4: 1200 x 1200 px of ~927 m per tile, instead of 4800 x 4800 at 232 m). Raw overview reads are cached as
.npz under data/raw/modis/.

Masking: keep overview pixels with pixel_reliability in {0 good, 1 marginal} and NDVI in the valid range
[-2000, 10000] (scale 1e-4). The COG overviews are block averages, so a reliability of 0/1 means the 4x4 block was
(almost) all good/marginal; fill (255) or snow/cloud (2/3) sub-pixels push the averaged value above 1.
Crop mask: if data/raw/modis/cropmask_<tile>.npz exists (built by sat_cropmask.py from USDA CDL 2016 on PC: share
of 30 m CDL crop pixels inside each ~927 m MODIS pixel), pixels with crop share >= 0.5 are used; counties with fewer
than MIN_CROP_PX crop pixels fall back to all land. Columns record which mask each row used.

County aggregation: pixel centres are assigned to Census 2023 county polygons (rasterised in the MODIS sinusoidal grid).
ndvi_jul_aug = pooled mean of all valid pixel-composites in the county for that year (4 composites).

Run: /home/user/venv-db/bin/python pipeline/sat_modis.py [--compute]
Output: data/processed/modis_county_year.parquet
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sat_cmip6 import county_table  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "modis"
PROC = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
COL = "modis-13Q1-061"
A = "250m_16_days_"
YEARS = list(range(2001, 2026))
BASE = list(range(2001, 2025))  # VCI / z baseline
OVR = 1  # overview level -> factor 4
MIN_CROP_PX = 30
# MODIS sinusoidal tile grid
X0, Y0, T = -20015109.355798, 10007554.677899, 1111950.519667
SINU = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
NPX = 1200

_client = None


def client():
    global _client
    import planetary_computer
    import pystac_client
    if _client is None:
        _client = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    return _client


def needed_tiles(g):
    gs = g.to_crs(SINU)
    tiles = set()
    for geom in gs.geometry:
        x0, y0, x1, y1 = geom.bounds
        for h in range(int((x0 - X0) // T), int((x1 - X0) // T) + 1):
            for v in range(int((Y0 - y1) // T), int((Y0 - y0) // T) + 1):
                from shapely.geometry import box
                tb = box(X0 + h * T, Y0 - (v + 1) * T, X0 + (h + 1) * T, Y0 - v * T)
                if geom.intersects(tb):
                    tiles.add((h, v))
    return sorted(tiles)


def list_items(tiles):
    """All Terra MOD13Q1 items for the tiles whose compositing start date falls in Jul-Aug, per year."""
    cache = RAW / "items.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        if set(df.year.unique()) >= set(YEARS[:-1]):
            return df
    rows = []
    for y in YEARS:
        for it in client().search(collections=[COL], bbox=[-105, 35, -87, 50],
                                  datetime=f"{y}-07-01/{y}-08-31").items():
            p = it.properties
            h, v = int(p["modis:horizontal-tile"]), int(p["modis:vertical-tile"])
            st = pd.Timestamp(p["start_datetime"])
            if not it.id.startswith("MOD13Q1") or (h, v) not in tiles or st.month not in (7, 8) or st.year != y:
                continue
            rows.append({"id": it.id, "year": y, "start": st.strftime("%Y-%m-%d"), "doy": st.dayofyear, "h": h, "v": v})
        print(f"  items {y}: {sum(r['year'] == y for r in rows)}", flush=True)
    df = pd.DataFrame(rows).drop_duplicates("id")
    df.to_parquet(cache, index=False)
    return df


def dedupe(df):
    """PC holds two production versions of a few composites (2005 DOY 241, 2021 DOY 225): keep the newest."""
    df = df.assign(prod=df.id.str.split(".").str[-1]).sort_values("prod")
    return df.drop_duplicates(["year", "h", "v", "doy"], keep="last").drop(columns="prod").reset_index(drop=True)


def fetch(item_id):
    out = RAW / f"{item_id}.npz"
    if out.exists():
        return "cached"
    import planetary_computer
    import pystac
    import rasterio
    for k in range(4):
        try:
            it = client().get_collection(COL).get_item(item_id)
            it = planetary_computer.sign(it)
            arrs = {}
            for a in ("NDVI", "pixel_reliability"):
                with rasterio.open(it.assets[A + a].href, overview_level=OVR) as ds:
                    arrs[a] = ds.read(1)
                    tr = ds.transform
            tmp = out.with_suffix(".tmp.npz")
            np.savez_compressed(tmp, ndvi=arrs["NDVI"], rel=arrs["pixel_reliability"],
                                transform=np.array(tr)[:6])
            tmp.rename(out)
            return "ok"
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(5 * (k + 1))
    return f"FAILED {err}"


def tile_county_raster(g, h, v, fips_index):
    """County index (int32, -1 outside) on the 1200x1200 overview grid of tile (h, v)."""
    from affine import Affine
    from rasterio.features import rasterize
    res = T / NPX
    tr = Affine(res, 0, X0 + h * T, 0, -res, Y0 - v * T)
    gs = g.to_crs(SINU)
    shapes = [(geom, fips_index[f]) for f, geom in zip(gs.fips, gs.geometry)]
    return rasterize(shapes, out_shape=(NPX, NPX), transform=tr, fill=-1, dtype="int32"), tr


def compute(g, items):
    fips = g.fips.tolist()
    fidx = {f: i for i, f in enumerate(fips)}
    nf = len(fips)
    tiles = sorted(set(zip(items.h, items.v)))
    crast, cmask, cdl_year = {}, {}, None
    for h, v in tiles:
        crast[(h, v)], tr = tile_county_raster(g, h, v, fidx)
        cm = RAW / f"cropmask_h{h:02d}v{v:02d}.npz"
        cmask[(h, v)] = None
        if cm.exists():
            zc = np.load(cm)
            cmask[(h, v)] = zc["crop_share"] >= 0.5
            cdl_year = int(zc["cdl_year"])
    have_crop = all(m is not None for m in cmask.values())
    # county crop pixel counts (static mask)
    crop_px = np.zeros(nf)
    land_px = np.zeros(nf)
    for t in tiles:
        c = crast[t]
        land_px += np.bincount(c[c >= 0], minlength=nf)
        if have_crop:
            cc = c[(c >= 0) & cmask[t]]
            crop_px += np.bincount(cc, minlength=nf)
    use_crop = have_crop & (crop_px >= MIN_CROP_PX) if have_crop else np.zeros(nf, bool)

    recs = []
    for y in YEARS:
        sub = items[items.year == y]
        s = {k: np.zeros(nf) for k in ("all_s", "all_n", "crop_s", "crop_n")}
        comps = set()
        for _, r in sub.iterrows():
            p = RAW / f"{r.id}.npz"
            if not p.exists():
                continue
            z = np.load(p)
            nd, rel = z["ndvi"], z["rel"]
            c = crast[(r.h, r.v)]
            # sanity: the cached overview grid must match the rasterised grid
            assert nd.shape == (NPX, NPX), nd.shape
            ok = (rel <= 1) & (nd >= -2000) & (nd <= 10000) & (c >= 0)
            val = nd.astype(np.float64) * 1e-4
            s["all_s"] += np.bincount(c[ok], weights=val[ok], minlength=nf)
            s["all_n"] += np.bincount(c[ok], minlength=nf)
            if have_crop:
                okc = ok & cmask[(r.h, r.v)]
                s["crop_s"] += np.bincount(c[okc], weights=val[okc], minlength=nf)
                s["crop_n"] += np.bincount(c[okc], minlength=nf)
            comps.add(r.doy)
        ncomp = len(comps)
        with np.errstate(invalid="ignore", divide="ignore"):
            all_m = s["all_s"] / s["all_n"]
            crop_m = s["crop_s"] / s["crop_n"]
        for i, f in enumerate(fips):
            uc = bool(use_crop[i])
            m = crop_m[i] if uc else all_m[i]
            n = s["crop_n"][i] if uc else s["all_n"][i]
            recs.append({"fips": f, "year": y, "ndvi_jul_aug": m if n > 0 else np.nan,
                         "n_px": n / ncomp if ncomp else 0.0, "n_composites": ncomp,
                         "mask": f"cropland_cdl{cdl_year}" if uc else "all_land",
                         "ndvi_all_land_jul_aug": all_m[i] if s["all_n"][i] > 0 else np.nan,
                         "n_px_all_land": s["all_n"][i] / ncomp if ncomp else 0.0,
                         "county_px_total": land_px[i], "county_crop_px": crop_px[i] if have_crop else np.nan})
    df = pd.DataFrame(recs)
    base = df[df.year.isin(BASE)].groupby("fips")["ndvi_jul_aug"]
    st = pd.DataFrame({"mn": base.min(), "mx": base.max(), "mu": base.mean(), "sd": base.std(ddof=1),
                       "nb": base.count()})
    df = df.merge(st, left_on="fips", right_index=True, how="left")
    ok = df.nb >= 15
    df["vci_jul_aug"] = np.where(ok, (100 * (df.ndvi_jul_aug - df.mn) / (df.mx - df.mn)).clip(0, 100), np.nan)
    df["ndvi_z"] = np.where(ok, (df.ndvi_jul_aug - df.mu) / df.sd, np.nan)
    df = df.drop(columns=["mn", "mx", "mu", "sd", "nb"])
    cols = ["fips", "year", "ndvi_jul_aug", "vci_jul_aug", "ndvi_z", "n_px", "n_composites", "mask",
            "ndvi_all_land_jul_aug", "n_px_all_land", "county_px_total", "county_crop_px"]
    df = df[cols].sort_values(["fips", "year"]).reset_index(drop=True)
    df.to_parquet(PROC / "modis_county_year.parquet", index=False)
    print(f"modis_county_year: {len(df)} rows, {df.fips.nunique()} counties, years {df.year.min()}-{df.year.max()}, "
          f"crop mask used for {int(use_crop.sum())} counties (mask files present: {have_crop})")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compute", action="store_true")
    ap.add_argument("--threads", type=int, default=2)
    a = ap.parse_args()
    g = county_table()
    tiles = needed_tiles(g)
    print("tiles", [f"h{h:02d}v{v:02d}" for h, v in tiles])
    items = dedupe(list_items(set(tiles)))
    print(f"{len(items)} items; per year:", items.groupby("year").size().to_dict())
    if not a.compute:
        t0 = time.time()
        todo = [i for i in items.id if not (RAW / f"{i}.npz").exists()]
        print(f"fetching {len(todo)} items", flush=True)
        with ThreadPoolExecutor(a.threads) as ex:
            futs = {ex.submit(fetch, i): i for i in todo}
            for k, fu in enumerate(as_completed(futs)):
                s = fu.result()
                if s != "ok" or k % 25 == 0:
                    print(f"  [{k + 1}/{len(todo)}] {futs[fu]} {s} ({(time.time() - t0) / 60:.1f} min)", flush=True)
    compute(g, items)


if __name__ == "__main__":
    sys.exit(main())
