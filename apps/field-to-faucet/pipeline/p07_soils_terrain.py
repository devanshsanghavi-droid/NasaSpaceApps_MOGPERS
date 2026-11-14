"""Soils (gNATSGO + SSURGO via Soil Data Access) and terrain (NASADEM slope) for row-crop land per HUC-12.

Steps
 1. gNATSGO `mukey` (Planetary Computer `gnatsgo-rasters`, 10 m, ESRI:102039 = same Albers as EPSG:5070) is
    warped (nearest) onto a 90 m EPSG:5070 grid that nests the CDL 30 m grid (3x3 CDL pixels per cell). GDAL reads
    the 8x (80 m) overview, so only a few MB per tile are fetched. -> data/raw/soils/mukey_90m.tif (int32, 0 = none)
 2. USDA Soil Data Access (SDA, SQL over HTTPS): every component of each mukey (comppct_r, drainagecl, hydgrp,
    slope_r) and the surface horizon (min hzdept_r) of each component (kwfact, om_r). The dominant component
    (max comppct_r, ties -> lowest cokey) gives the per-mukey attributes. -> data/processed/soils_mukey.parquet
 3. NASADEM 1 arcsec elevation (PC `nasadem`, 16 1x1 deg tiles, cached in data/raw/terrain/) bilinear-warped to the
    30 m CDL grid, Gaussian-smoothed (sigma = 1 px) to damp SRTM noise, Horn slope (percent = 100 tan b).
    -> data/raw/terrain/slope_90m.tif (float32, 3x3 block mean of the 30 m slope)
 4. Per HUC-12, over row-crop pixels (30 m CDL pixel that is corn/soy/other row crop in >= 6 of 10 years 2016-2025,
    from p06 rowcrop_years_2016_2025.tif; mukey looked up at 30 m by nesting the 90 m cell):
    poorly_drained_share, somewhat_poorly_share, hydgrp_D_share, mean_slope_pct (+ extras, see notes/cdl.md).
    -> data/processed/soils_huc12.parquet
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject
from rasterio.windows import Window
from scipy import ndimage

from common import RAW, PROC, STAC_URL, _session, post

os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

CDL = RAW / "cdl"
SOILS = RAW / "soils"
TERR = RAW / "terrain"
SDA_DIR = SOILS / "sda"
for p in (SOILS, TERR, SDA_DIR):
    p.mkdir(parents=True, exist_ok=True)
SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
MUKEY_NODATA = 2147483647
POORLY = {"Poorly drained", "Very poorly drained"}
SOMEWHAT = {"Somewhat poorly drained"}
HYD_D = {"D", "A/D", "B/D", "C/D"}  # D plus dual groups (D when undrained; most are tile-drained in practice)


def lonlat_bbox(tr, H, W, pad=0.05):
    from pyproj import Transformer
    x0, y1 = tr.c, tr.f
    x1, y0 = x0 + tr.a * W, y1 + tr.e * H
    t = Transformer.from_crs(5070, 4326, always_xy=True)
    xs = np.r_[np.linspace(x0, x1, 50), np.linspace(x0, x1, 50), np.full(50, x0), np.full(50, x1)]
    ys = np.r_[np.full(50, y0), np.full(50, y1), np.linspace(y0, y1, 50), np.linspace(y0, y1, 50)]
    lon, lat = t.transform(xs, ys)
    return [lon.min() - pad, lat.min() - pad, lon.max() + pad, lat.max() + pad]


def stac_items(collection, bbox):
    import planetary_computer
    import pystac_client
    c = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    return list(c.search(collections=[collection], bbox=bbox).items())


# ------------------------------------------------------------------ 1. gNATSGO mukey at 90 m
def mukey_90m(prof30):
    f = SOILS / "mukey_90m.tif"
    tr30 = prof30["transform"]
    H, W = prof30["height"] // 3, prof30["width"] // 3
    tr90 = Affine(90, 0, tr30.c, 0, -90, tr30.f)
    if f.exists():
        with rasterio.open(f) as s:
            return s.read(1), tr90
    import planetary_computer
    items = stac_items("gnatsgo-rasters", lonlat_bbox(tr30, prof30["height"], prof30["width"]))
    print("gnatsgo items:", [i.id for i in items], flush=True)

    def one(it):
        dst = np.full((H, W), MUKEY_NODATA, np.int32)
        for k in range(5):
            try:
                with rasterio.open(planetary_computer.sign(it.assets["mukey"].href)) as src:
                    reproject(rasterio.band(src, 1), dst, dst_transform=tr90, dst_crs="EPSG:5070",
                              dst_nodata=MUKEY_NODATA, resampling=Resampling.nearest)
                return dst
            except Exception as e:
                print(f"  {it.id} retry {k}: {e}", flush=True)
                time.sleep(3 * (k + 1))
        raise RuntimeError(f"gnatsgo read failed {it.id}")

    mos = np.full((H, W), MUKEY_NODATA, np.int32)
    with ThreadPoolExecutor(6) as ex:
        for d in ex.map(one, items):
            m = (mos == MUKEY_NODATA) & (d != MUKEY_NODATA) & (d > 0)
            mos[m] = d[m]
    mos[mos == MUKEY_NODATA] = 0
    p = dict(driver="GTiff", height=H, width=W, count=1, dtype="int32", crs="EPSG:5070", transform=tr90,
             compress="deflate", tiled=True, nodata=0)
    with rasterio.open(f, "w", **p) as d:
        d.write(mos, 1)
        d.update_tags(source="planetary-computer gnatsgo-rasters mukey (nearest, 80 m overview -> 90 m): "
                             + ",".join(i.id for i in items))
    print(f"mukey_90m: {H}x{W}, zero frac {np.mean(mos == 0):.4f}, unique {len(np.unique(mos))}", flush=True)
    return mos, tr90


# ------------------------------------------------------------------ 2. SDA
SQL = """
SELECT mu.mukey, mu.muname, c.cokey, c.compname, c.comppct_r, c.majcompflag, c.slope_r, c.drainagecl, c.hydgrp,
       h.hzname, h.hzdept_r, h.kwfact, h.om_r
FROM mapunit mu
INNER JOIN component c ON c.mukey = mu.mukey
LEFT JOIN chorizon h ON h.cokey = c.cokey AND h.chkey =
    (SELECT TOP 1 h2.chkey FROM chorizon h2 WHERE h2.cokey = c.cokey ORDER BY h2.hzdept_r ASC, h2.chkey)
WHERE mu.mukey IN ({keys})
"""


def sda_batch(keys):
    f = SDA_DIR / f"comp_{keys[0]}_{keys[-1]}_{len(keys)}.json"
    if f.exists():
        return json.loads(f.read_text())
    r = post(SDA_URL, data={"query": SQL.format(keys=",".join(map(str, keys))), "format": "JSON+COLUMNNAME"})
    d = r.json()
    f.write_text(json.dumps(d))
    return d


def sda(mukeys):
    mukeys = sorted(int(m) for m in mukeys)
    batches = [mukeys[i:i + 300] for i in range(0, len(mukeys), 300)]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(sda_batch, batches))
    rows = []
    for d in res:
        tab = d.get("Table", [])
        if tab:
            rows += [dict(zip(tab[0], r)) for r in tab[1:]]
    comp = pd.DataFrame(rows)
    for c in ["mukey", "cokey", "comppct_r", "slope_r", "hzdept_r", "kwfact", "om_r"]:
        comp[c] = pd.to_numeric(comp[c], errors="coerce")
    comp["mukey"] = comp.mukey.astype("int64")
    comp.to_parquet(SDA_DIR / "components.parquet", index=False)
    comp = comp.sort_values(["mukey", "comppct_r", "cokey"], ascending=[True, False, True])
    dom = comp.drop_duplicates("mukey").copy()
    # component-weighted wet-soil fractions (all components, by comppct_r)
    w = comp.assign(p=comp.comppct_r.fillna(0))
    w["pd"] = w.drainagecl.isin(POORLY) * w.p
    w["sp"] = w.drainagecl.isin(SOMEWHAT) * w.p
    w["hd"] = w.hydgrp.isin(HYD_D) * w.p
    agg = w.groupby("mukey")[["p", "pd", "sp", "hd"]].sum()
    tot = agg.p.where(agg.p > 0)
    frac = pd.DataFrame({"poorly_frac_comp": agg.pd / tot, "somewhat_frac_comp": agg.sp / tot,
                         "hydgrp_D_frac_comp": agg.hd / tot}).reset_index()
    out = dom[["mukey", "muname", "compname", "comppct_r", "drainagecl", "hydgrp", "kwfact", "om_r", "slope_r"]]
    out = out.merge(frac, on="mukey", how="left")
    return out


# ------------------------------------------------------------------ 3. NASADEM slope
def nasadem_tiles(prof30):
    items = stac_items("nasadem", lonlat_bbox(prof30["transform"], prof30["height"], prof30["width"], pad=0.02))
    paths = []

    def dl(it):
        f = TERR / f"{it.id}.tif"
        if not f.exists():
            import planetary_computer
            r = _session.get(planetary_computer.sign(it.assets["elevation"].href), timeout=600)
            r.raise_for_status()
            f.with_suffix(".tmp").write_bytes(r.content)
            f.with_suffix(".tmp").replace(f)
        return f

    with ThreadPoolExecutor(6) as ex:
        paths = list(ex.map(dl, items))
    print("nasadem tiles:", len(paths), flush=True)
    return paths


STRIP = 1200  # rows per processing strip (multiple of 3) to keep memory well under 3 GB
HALO = 8      # rows of overlap for the gaussian (sigma 1, truncate 4) + Horn 3x3 stencils


def slope_30m(prof30):
    """Slope percent on the 30 m CDL grid, computed in row strips; written to data/raw/terrain/slope_30m.tif."""
    f30 = TERR / "slope_30m.tif"
    if f30.exists():
        return f30
    H, W, tr = prof30["height"], prof30["width"], prof30["transform"]
    tiles = nasadem_tiles(prof30)
    srcs = [rasterio.open(p) for p in tiles]
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], np.float32) / (8 * 30.0)
    p = dict(driver="GTiff", height=H, width=W, count=1, dtype="float32", crs="EPSG:5070", transform=tr,
             compress="deflate", tiled=True, nodata=np.nan, predictor=3)
    tmpf = f30.with_suffix(".tmp.tif")
    zmin, zmax, nnan = np.inf, -np.inf, 0
    with rasterio.open(tmpf, "w", **p) as dst:
        for r0 in range(0, H, STRIP):
            r1 = min(r0 + STRIP, H)
            a0, a1 = max(r0 - HALO, 0), min(r1 + HALO, H)
            str_tr = tr * Affine.translation(0, a0)
            dem = np.full((a1 - a0, W), np.nan, np.float32)
            for src in srcs:
                tmp = np.full_like(dem, np.nan)
                reproject(rasterio.band(src, 1), tmp, src_nodata=src.nodata, dst_transform=str_tr,
                          dst_crs="EPSG:5070", dst_nodata=np.nan, resampling=Resampling.bilinear)
                m = np.isnan(dem) & np.isfinite(tmp)
                dem[m] = tmp[m]
            nanm = np.isnan(dem)
            nnan += int(nanm[r0 - a0:r1 - a0].sum())
            if nanm.all():
                sl = np.full_like(dem, np.nan)
            else:
                zmin, zmax = min(zmin, np.nanmin(dem)), max(zmax, np.nanmax(dem))
                dem[nanm] = np.nanmean(dem)
                z = ndimage.gaussian_filter(dem, 1.0)
                sl = (100 * np.hypot(ndimage.correlate(z, kx, mode="nearest"),
                                     ndimage.correlate(z, kx.T, mode="nearest"))).astype(np.float32)
                sl[nanm] = np.nan
            dst.write(sl[r0 - a0:r1 - a0], 1, window=Window(0, r0, W, r1 - r0))
    for s_ in srcs:
        s_.close()
    tmpf.replace(f30)
    print(f"slope 30 m: dem range {zmin:.0f}-{zmax:.0f} m, nan px {nnan}", flush=True)
    return f30


def block_mean3(a):
    H, W = a.shape[0] // 3 * 3, a.shape[1] // 3 * 3
    with np.errstate(invalid="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmean(a[:H, :W].reshape(H // 3, 3, W // 3, 3), axis=(1, 3)).astype(np.float32)


def read_strip(path, r0, r1, W):
    with rasterio.open(path) as s:
        return s.read(1, window=Window(0, r0, W, r1 - r0))


# ------------------------------------------------------------------ main
def main():
    with rasterio.open(CDL / "rowcrop_years_2016_2025.tif") as s:
        prof30 = s.profile
    tr30 = prof30["transform"]
    H, W = prof30["height"], prof30["width"]
    assert H % 3 == 0 and W % 3 == 0 and STRIP % 3 == 0
    huc = pd.read_parquet(PROC / "huc12.parquet").sort_values("huc12").reset_index(drop=True)
    nh = len(huc)
    fidx = CDL / "huc12_index_30m.tif"
    frc = CDL / "rowcrop_years_2016_2025.tif"

    # 1. mukey
    mk90, tr90 = mukey_90m(prof30)
    # 2. SDA attributes for every mukey inside the basins
    inside90 = np.zeros(mk90.shape, bool)
    for r0 in range(0, H, STRIP):
        r1 = min(r0 + STRIP, H)
        inside90[r0 // 3:r1 // 3] = block_mean3((read_strip(fidx, r0, r1, W) >= 0).astype(np.float32)) > 0
    keys = np.unique(mk90[inside90 & (mk90 > 0)])
    mu = sda(keys)
    print(f"SDA: {len(mu)} of {len(keys)} mukeys", flush=True)
    for c in ["kwfact", "om_r", "slope_r", "comppct_r"]:
        mu[c] = mu[c].astype("float32")
    mu.to_parquet(PROC / "soils_mukey.parquet", index=False, compression="zstd")

    # 3. slope
    fsl = slope_30m(prof30)
    f90 = TERR / "slope_90m.tif"
    if not f90.exists():
        p = dict(driver="GTiff", height=H // 3, width=W // 3, count=1, dtype="float32",
                 crs="EPSG:5070", transform=tr90, compress="deflate", tiled=True, nodata=np.nan, predictor=3)
        with rasterio.open(f90, "w", **p) as d:
            for r0 in range(0, H, STRIP):
                r1 = min(r0 + STRIP, H)
                d.write(block_mean3(read_strip(fsl, r0, r1, W)), 1, window=Window(0, r0 // 3, W // 3, (r1 - r0) // 3))
            d.update_tags(description="slope percent, NASADEM 1 arcsec -> 30 m bilinear, gaussian sigma 1 px, "
                                      "Horn; 3x3 block mean to 90 m")

    # 4. per-HUC-12 sums over row-crop pixels at 30 m, strip by strip
    lk = mu.set_index("mukey")
    uniq = np.unique(mk90)
    m_attr = lk.reindex(uniq)
    a_known = m_attr.drainagecl.notna().to_numpy()
    a_hknown = m_attr.hydgrp.notna().to_numpy()
    a_pd = m_attr.drainagecl.isin(POORLY).to_numpy() & a_known
    a_sp = m_attr.drainagecl.isin(SOMEWHAT).to_numpy() & a_known
    a_hd = m_attr.hydgrp.isin(HYD_D).to_numpy() & a_hknown
    a_hdo = (m_attr.hydgrp == "D").to_numpy() & a_hknown
    a_pdc = m_attr.poorly_frac_comp.to_numpy(dtype=float)
    a_kw = m_attr.kwfact.to_numpy(dtype=float)
    a_om = m_attr.om_r.to_numpy(dtype=float)
    a_dc = pd.Categorical(m_attr.drainagecl.fillna("unknown"))
    dc_codes, dc_names = a_dc.codes, list(a_dc.categories)
    acc = {k: np.zeros(nh) for k in ["n_rc", "known", "hknown", "pd", "sp", "hd", "hdo", "pdc", "pdc_n",
                                     "sl", "sl_n", "kw", "kw_n", "om", "om_n", "n_tot", "sl_all", "sl_all_n"]}
    dc_count = np.zeros(len(dc_names))
    cidx = np.arange(W) // 3

    def add(k, h, v=None):
        acc[k] += np.bincount(h, weights=None if v is None else v.astype(float), minlength=nh)

    for r0 in range(0, H, STRIP):
        r1 = min(r0 + STRIP, H)
        hidx = read_strip(fidx, r0, r1, W)
        rc = read_strip(frc, r0, r1, W)
        sl = read_strip(fsl, r0, r1, W)
        ins = hidx >= 0
        add("n_tot", hidx[ins].astype(np.int64))
        ok = ins & np.isfinite(sl)
        add("sl_all", hidx[ok].astype(np.int64), sl[ok])
        add("sl_all_n", hidx[ok].astype(np.int64))
        rowc = ins & (rc >= 6) & (rc != 255)
        if not rowc.any():
            continue
        h = hidx[rowc].astype(np.int64)
        mk = mk90[(np.arange(r0, r1) // 3)[:, None], cidx[None, :]][rowc]
        u = np.searchsorted(uniq, mk)
        slv = sl[rowc]
        add("n_rc", h)
        for k, arr in [("known", a_known), ("hknown", a_hknown), ("pd", a_pd), ("sp", a_sp), ("hd", a_hd),
                       ("hdo", a_hdo)]:
            add(k, h, arr[u])
        for k, arr in [("pdc", a_pdc), ("kw", a_kw), ("om", a_om)]:
            v = arr[u]
            f = np.isfinite(v)
            add(k, h[f], v[f])
            add(k + "_n", h[f])
        f = np.isfinite(slv)
        add("sl", h[f], slv[f])
        add("sl_n", h[f])
        dc_count += np.bincount(dc_codes[u], minlength=len(dc_names))

    A = acc
    with np.errstate(invalid="ignore", divide="ignore"):
        out = pd.DataFrame({
            "huc12": huc.huc12, "basin": huc.basin,
            "poorly_drained_share": A["pd"] / A["known"],
            "somewhat_poorly_share": A["sp"] / A["known"],
            "hydgrp_D_share": A["hd"] / A["hknown"],
            "hydgrp_D_only_share": A["hdo"] / A["hknown"],
            "poorly_drained_share_comp": A["pdc"] / A["pdc_n"],
            "mean_slope_pct": A["sl"] / A["sl_n"],
            "kwfact_mean": A["kw"] / A["kw_n"],
            "om_r_mean": A["om"] / A["om_n"],
            "rowcrop_km2": A["n_rc"] * 900 / 1e6,
            "rowcrop_frac": A["n_rc"] / A["n_tot"],
            "soil_known_frac": A["known"] / A["n_rc"],
            "mean_slope_pct_all": A["sl_all"] / A["sl_all_n"],
        })
    for c in out.columns[2:]:
        out[c] = out[c].astype("float32").round(4)
    out.to_parquet(PROC / "soils_huc12.parquet", index=False, compression="zstd")

    # report
    print(f"soils_huc12: {len(out)} rows; soils_mukey: {len(mu)} rows")
    print(out.describe().T.round(3).to_string())
    for b, g in out.groupby("basin"):
        w = g.rowcrop_km2
        print(f"{b}: row-crop {w.sum():,.0f} km2; area-weighted poorly {np.average(g.poorly_drained_share, weights=w):.3f}"
              f" (comp-weighted {np.average(g.poorly_drained_share_comp, weights=w):.3f}), somewhat poorly "
              f"{np.average(g.somewhat_poorly_share, weights=w):.3f}, hydgrp D incl dual "
              f"{np.average(g.hydgrp_D_share, weights=w):.3f} (D only {np.average(g.hydgrp_D_only_share, weights=w):.3f})"
              f", slope {np.average(g.mean_slope_pct, weights=w):.2f}%")
    print("drainage classes of row-crop pixels (both basins):")
    print(pd.Series(dc_count / dc_count.sum(), index=dc_names).sort_values(ascending=False).round(4).to_string())


if __name__ == "__main__":
    main()
