"""MODIS MOD16A3GF v061 annual evapotranspiration (500 m, Terra, year-end gap-filled) per county, 2001-2024(+2025 if
published), and by CDL crop class (2008-2024).

Source: Microsoft Planetary Computer STAC collection `modis-16A3GF-061`, asset `ET_500m` (COG on
modiseuwest.blob.core.windows.net), tiles h09v05, h10v05, h10v04 (sinusoidal). Only MOD (Terra) items are used.
ET_500m: uint16, scale 0.1 -> kg/m2/yr (= mm/yr); values 65529-65535 are fill / non-vegetated classes
(65535 fill, 65534 water, 65533 barren, 65532 ice/snow, 65531 wetland, 65530 urban, 65529 unclassified) -> excluded.
Converted to inches: mm / 25.4.

Crop-class ET: each 30 m CDL pixel (nasa_cdl_fetch.py) is assigned to the 500 m MODIS pixel that contains it (nearest
warp of a MODIS pixel-id raster onto the CDL grid). For every MODIS pixel we get its CDL class fractions in that year.
  et_<cls>_in      area-weighted mean ET over the class's 30 m pixels (mixed MODIS pixels contribute by class fraction)
  et_<cls>_pure_in mean ET over MODIS pixels whose CDL class fraction >= 0.75 ("pure" pixels; n_<cls>_pure = count)
County membership of a MODIS pixel = county holding the majority of its 30 m pixels.

Output: data/processed/modis_et_county.parquet (one row per county_fips x year).
Usage : python3 pipeline/nasa_modis_et.py
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import Affine
from rasterio.warp import reproject, Resampling
from rasterio.windows import Window

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasa_cdl_common import (CDL_YEARS, CROP_CLASSES, GDAL_ENV, PROC, RAW, STAC, cdl_path, code_to_class_lut,  # noqa: E402
                             county_raster, region_grid, retry)

MRAW = RAW / "modis"
SIN = ('+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs')
PIX = 463.31271652749973
X0, Y0 = -20015109.354, 10007554.677          # global MODIS sinusoidal grid origin (upper-left)
TILES = ["h09v05", "h10v05", "h10v04"]
CLASSES = ["corn", "winter_wheat", "sorghum", "soybeans", "alfalfa", "grass_pasture", "fallow_idle", "shrubland"]
PURE = 0.75


def window_grid():
    """Global-sinusoidal-grid window (row0, col0, H, W) covering the region bbox."""
    from pyproj import Transformer
    from nasa_common import BBOX
    t = Transformer.from_crs(4326, SIN, always_xy=True)
    lons = np.r_[np.linspace(BBOX[0], BBOX[2], 50), np.linspace(BBOX[0], BBOX[2], 50)]
    lats = np.r_[np.full(50, BBOX[1]), np.full(50, BBOX[3])]
    lons = np.r_[lons, np.full(50, BBOX[0]), np.full(50, BBOX[2])]
    lats = np.r_[lats, np.linspace(BBOX[1], BBOX[3], 50), np.linspace(BBOX[1], BBOX[3], 50)]
    x, y = t.transform(lons, lats)
    c0 = int(np.floor((x.min() - X0) / PIX)) - 3
    c1 = int(np.ceil((x.max() - X0) / PIX)) + 3
    r0 = int(np.floor((Y0 - y.max()) / PIX)) - 3
    r1 = int(np.ceil((Y0 - y.min()) / PIX)) + 3
    return r0, c0, r1 - r0, c1 - c0


def items():
    import planetary_computer
    import pystac_client
    c = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    s = c.search(collections=["modis-16A3GF-061"], bbox=[-102.06, 36.99, -99.55, 40.01])
    out = {}
    for it in s.items():
        if not it.id.startswith("MOD16A3GF"):
            continue
        y = int(it.properties["start_datetime"][:4])
        tile = f"h{it.properties['modis:horizontal-tile']:02d}v{it.properties['modis:vertical-tile']:02d}"
        if tile in TILES:
            out.setdefault(y, {})[tile] = it.assets["ET_500m"].href.split("?")[0]
    return out


def year_mosaic(year, hrefs):
    """ET (raw uint16) on the region window of the global sinusoidal grid; cached as .npy."""
    import planetary_computer
    p = MRAW / f"et_{year}.npy"
    if p.exists():
        return np.load(p)
    r0, c0, H, W = window_grid()
    mos = np.full((H, W), 65535, np.uint16)
    for tile, href in hrefs.items():
        h, v = int(tile[1:3]), int(tile[4:6])
        tr0, tc0 = v * 2400, h * 2400            # tile origin in global rows/cols
        rr0, rr1 = max(r0, tr0), min(r0 + H, tr0 + 2400)
        cc0, cc1 = max(c0, tc0), min(c0 + W, tc0 + 2400)
        if rr0 >= rr1 or cc0 >= cc1:
            continue

        def read():
            with rasterio.Env(**GDAL_ENV), rasterio.open(planetary_computer.sign(href)) as src:
                assert abs(src.transform.a - PIX) < 1e-3 and abs(src.transform.c - (X0 + tc0 * PIX)) < 1.0, src.transform
                return src.read(1, window=Window(cc0 - tc0, rr0 - tr0, cc1 - cc0, rr1 - rr0))
        mos[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = retry(read)
    MRAW.mkdir(parents=True, exist_ok=True)
    np.save(p, mos)
    return mos


def modis_index_on_cdl():
    """int32 raster on the CDL 30 m region grid = flat index of the containing MODIS pixel in the window (-1 outside)."""
    p = MRAW / "modis_idx_on_cdl30.npy"
    if p.exists():
        return np.load(p)
    r0, c0, H, W = window_grid()
    src_tr = Affine(PIX, 0, X0 + c0 * PIX, 0, -PIX, Y0 - r0 * PIX)
    ids = np.arange(H * W, dtype=np.int32).reshape(H, W)
    bb, tr, Wc, Hc = region_grid()
    dst = np.full((Hc, Wc), -1, np.int32)
    reproject(ids, dst, src_transform=src_tr, src_crs=SIN, dst_transform=tr, dst_crs="EPSG:5070",
              resampling=Resampling.nearest, src_nodata=None, dst_nodata=-1, num_threads=4)
    MRAW.mkdir(parents=True, exist_ok=True)
    np.save(p, dst)
    return dst


def chunked_bincount(a_idx, b, nb, n):
    """bincount of a_idx*nb + b over valid a_idx (>=0), chunked to limit memory."""
    out = np.zeros(n * nb, np.int64)
    for r in range(0, a_idx.shape[0], 1500):
        ai = a_idx[r:r + 1500].ravel()
        bi = b[r:r + 1500].ravel().astype(np.int64)
        m = ai >= 0
        out += np.bincount(ai[m].astype(np.int64) * nb + bi[m], minlength=n * nb)
    return out.reshape(n, nb)


def main():
    r0, c0, H, W = window_grid()
    n = H * W
    print(f"MODIS window rows {r0}+{H}, cols {c0}+{W}", flush=True)
    its = items()
    years = sorted(y for y in its if y >= 2001)
    print("MOD16A3GF years:", years, flush=True)
    with ThreadPoolExecutor(4) as ex:
        et = dict(zip(years, ex.map(lambda y: year_mosaic(y, its[y]), years)))
    midx = modis_index_on_cdl()
    cty, g = county_raster()
    nc = len(g) + 1
    cc = chunked_bincount(midx, cty, nc, n)               # (n_modis, n_county+1) 30 m pixel counts
    npx = cc.sum(1)
    owner = cc[:, 1:].argmax(1) + 1
    owner[cc[:, 1:].max(1) == 0] = 0
    # require the MODIS pixel to be mostly covered by the CDL grid (>= 200 of ~238 30 m pixels)
    lut = code_to_class_lut()
    cls_cnt = {}
    for y in CDL_YEARS:
        if cdl_path(y).exists():
            with rasterio.open(cdl_path(y)) as src:
                cl = lut[src.read(1)]
            cls_cnt[y] = chunked_bincount(midx, cl, len(CROP_CLASSES), n)
            print(f"CDL {y} class fractions done", flush=True)
    rows = []
    for y in years:
        e = et[y].ravel()
        ok = e <= 65500
        ein = np.where(ok, e * 0.1 / 25.4, np.nan)
        cc_y = cls_cnt.get(y)
        for i, r in g.iterrows():
            m = (owner == i + 1) & ok
            rec = dict(county_fips=r.fips, county_name=r["name"], gmd=r.gmd, year=y,
                       modis_et_in=float(np.nanmean(ein[m])) if m.any() else np.nan,
                       modis_et_mm=float(np.nanmean(e[m] * 0.1)) if m.any() else np.nan,
                       n_pix=int(m.sum()), n_pix_fill=int(((owner == i + 1) & ~ok).sum()))
            if cc_y is not None:
                tot = cc_y[m].sum(1).astype(float)
                for cname in CLASSES:
                    k = CROP_CLASSES.index(cname)
                    w = cc_y[m, k].astype(float)
                    rec[f"et_{cname}_in"] = float((w * ein[m]).sum() / w.sum()) if w.sum() > 0 else np.nan
                    frac = np.divide(w, tot, out=np.zeros_like(w), where=tot > 0)
                    pure = frac >= PURE
                    rec[f"et_{cname}_pure_in"] = float(ein[m][pure].mean()) if pure.sum() >= 3 else np.nan
                    rec[f"n_{cname}_pure"] = int(pure.sum())
            rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_parquet(PROC / "modis_et_county.parquet", index=False)
    show = ["modis_et_in", "et_corn_in", "et_corn_pure_in", "et_winter_wheat_pure_in", "et_sorghum_pure_in",
            "et_grass_pasture_pure_in"]
    print(df.groupby("year")[show].mean().round(1).to_string())
    print("pure-pixel counts (sum over counties, mean over years):",
          df[[c for c in df if c.startswith("n_") and c.endswith("_pure")]].groupby(df.year).sum().mean().round(0).to_dict())


if __name__ == "__main__":
    main()
