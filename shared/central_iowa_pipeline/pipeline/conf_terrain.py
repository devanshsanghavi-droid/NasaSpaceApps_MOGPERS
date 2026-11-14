"""conf module: terrain confounders from NASADEM (NASA SRTM reprocessed) for all 50,850 grid points.

Steps
 1. Download the 1x1 deg NASADEM elevation COGs covering the tile (Planetary Computer, cached in data/raw/nasadem/).
 2. Mosaic + bilinear-resample to a 30 m UTM 15N (EPSG:32615) grid = tile bounds + 6 km buffer
    (buffer reduces truncation of upslope area for flow accumulation near tile edges).
 3. Light Gaussian smoothing (sigma=1 px) to suppress SRTM noise; slope_pct (Horn 3x3), profile curvature (Zevenbergen-Thorne on a Gaussian-smoothed DEM, sigma=1.5 px,
    convex > 0, units 1/(100 m)), flow accumulation (priority-flood depression handling + D8), TWI = ln(a / tan b).
 4. Sample at grid points: 3x3 (90 m) mean for elev/slope/curvature/twi, 3x3 median for flowacc.
Output: data/raw/conf/terrain_points.parquet (merged into data/confounders.parquet by conf_assemble.py)
Re-run: .venv/bin/python pipeline/conf_terrain.py
"""
import heapq
import json
from pathlib import Path

import numba as nb
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
import requests
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject
from rasterio.transform import from_origin
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "nasadem"
OUT = ROOT / "data" / "raw" / "conf"
RAW.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
REGION = json.loads((ROOT / "data" / "region.json").read_text())
RES = 30.0
BUF = 6000.0


def grid_points():
    g = REGION["grid"]
    rows, cols = np.meshgrid(np.arange(g["nrows"]), np.arange(g["ncols"]), indexing="ij")
    rows = rows.ravel(); cols = cols.ravel()
    x = g["x0"] + cols * g["spacing_m"]
    y = g["y0"] - rows * g["spacing_m"]
    gid = rows * g["ncols"] + cols
    return pd.DataFrame(dict(grid_id=gid, row=rows, col=cols, x=x, y=y))


def download_tiles():
    c = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                  modifier=planetary_computer.sign_inplace)
    lon0, lat0, lon1, lat1 = REGION["tile_bounds_lonlat"]
    items = list(c.search(collections=["nasadem"], bbox=[lon0 - 0.1, lat0 - 0.1, lon1 + 0.1, lat1 + 0.1]).items())
    paths = []
    for it in items:
        f = RAW / f"{it.id}.tif"
        if not f.exists():
            r = requests.get(it.assets["elevation"].href, timeout=600)
            r.raise_for_status()
            f.write_bytes(r.content)
        paths.append(f)
    print("nasadem tiles:", [p.name for p in paths])
    return paths


def build_dem(paths):
    srcs = [rasterio.open(p) for p in paths]
    mos, mtr = merge(srcs)
    crs_src = srcs[0].crs
    nod = srcs[0].nodata
    for s in srcs:
        s.close()
    xmin, ymin, xmax, ymax = REGION["tile_bounds_utm"]
    xmin -= BUF; ymin -= BUF; xmax += BUF; ymax += BUF
    w = int(round((xmax - xmin) / RES)); h = int(round((ymax - ymin) / RES))
    tr = from_origin(xmin, ymax, RES, RES)
    dem = np.full((h, w), np.nan, np.float32)
    src = mos[0].astype(np.float32)
    if nod is not None:
        src[src == nod] = np.nan
    reproject(src, dem, src_transform=mtr, src_crs=crs_src, dst_transform=tr, dst_crs="EPSG:32615",
              resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan)
    print("dem", dem.shape, np.nanmin(dem), np.nanmax(dem), "nan frac", np.isnan(dem).mean())
    return dem, tr


def horn(z, res):
    zp = np.pad(z, 1, mode="edge")
    a, b, c = zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:]
    d, f = zp[1:-1, :-2], zp[1:-1, 2:]
    g, h, i = zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * res)
    dzdy = ((g + 2 * h + i) - (a + 2 * b + c)) / (8 * res)  # positive = elevation increases southward
    return dzdx, dzdy


def profile_curvature(z, res):
    """Zevenbergen & Thorne (1987) profile curvature, convex (e.g. knoll shoulder) > 0, 1/m."""
    zp = np.pad(z, 1, mode="edge")
    z1, z2, z3 = zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:]
    z4, z5, z6 = zp[1:-1, :-2], zp[1:-1, 1:-1], zp[1:-1, 2:]
    z7, z8, z9 = zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:]
    # y axis pointing north (row up)
    p = (z6 - z4) / (2 * res)
    q = (z2 - z8) / (2 * res)
    r = (z4 - 2 * z5 + z6) / res ** 2
    t = (z2 - 2 * z5 + z8) / res ** 2
    s = (-z1 + z3 + z7 - z9) / (4 * res ** 2)
    pq = p ** 2 + q ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        kp = -(p ** 2 * r + 2 * p * q * s + q ** 2 * t) / (pq * (1 + pq) ** 1.5)
    kp[pq < 1e-10] = 0.0
    return kp


@nb.njit(cache=True)
def priority_flood_d8(z):
    """Priority-flood (Barnes et al. 2014) + D8.
    Returns receiver index (-1 = outlet) and processing order. Cells with a strictly lower filled
    neighbour drain by D8 steepest descent on the filled surface; cells on filled flats/depressions
    drain to the cell that flooded them (pop order), which guarantees an acyclic drainage tree."""
    h, w = z.shape
    n = h * w
    filled = np.empty(n, np.float64)
    closed = np.zeros(n, np.bool_)
    parent = np.full(n, -1, np.int64)
    order = np.empty(n, np.int64)
    zf = z.ravel()
    heap = [(0.0, np.int64(0), np.int64(0))]
    heap.pop()
    cnt = 0
    for r in range(h):
        for c in range(w):
            if r == 0 or c == 0 or r == h - 1 or c == w - 1:
                k = r * w + c
                v = zf[k]
                if np.isnan(v):
                    v = -1e9
                filled[k] = v
                closed[k] = True
                heap.append((v, np.int64(cnt), np.int64(k)))
                cnt += 1

    heapq.heapify(heap)
    dr = np.array([-1, -1, -1, 0, 0, 1, 1, 1])
    dc = np.array([-1, 0, 1, -1, 1, -1, 0, 1])
    npop = 0
    while len(heap) > 0:
        v, _, k = heapq.heappop(heap)
        order[npop] = k
        npop += 1
        r = k // w
        c = k % w
        for j in range(8):
            rr = r + dr[j]
            cc = c + dc[j]
            if rr < 0 or cc < 0 or rr >= h or cc >= w:
                continue
            kk = rr * w + cc
            if closed[kk]:
                continue
            closed[kk] = True
            zz = zf[kk]
            if np.isnan(zz):
                zz = -1e9
            if zz < v:
                zz = v
            filled[kk] = zz
            parent[kk] = k
            heapq.heappush(heap, (zz, np.int64(cnt), np.int64(kk)))
            cnt += 1
    # receivers
    recv = np.full(n, -1, np.int64)
    sq2 = np.sqrt(2.0)
    for k in range(n):
        r = k // w
        c = k % w
        if r == 0 or c == 0 or r == h - 1 or c == w - 1:
            continue
        best = 0.0
        bk = -1
        for j in range(8):
            kk = (r + dr[j]) * w + (c + dc[j])
            dist = sq2 if (dr[j] != 0 and dc[j] != 0) else 1.0
            sl = (filled[k] - filled[kk]) / dist
            if sl > best:
                best = sl
                bk = kk
        if bk >= 0:
            recv[k] = bk
        else:
            recv[k] = parent[k]
    return recv, order, filled.reshape(h, w)


@nb.njit(cache=True)
def accumulate(recv, order):
    n = recv.shape[0]
    acc = np.ones(n, np.float64)
    for i in range(n - 1, -1, -1):
        k = order[i]
        rk = recv[k]
        if rk >= 0:
            acc[rk] += acc[k]
    return acc


def sample(arr, tr, pts, how="mean"):
    col = np.floor((pts.x.values - tr.c) / tr.a).astype(int)
    row = np.floor((pts.y.values - tr.f) / tr.e).astype(int)
    stack = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            stack.append(arr[row + dr, col + dc])
    stack = np.vstack(stack)
    if how == "mean":
        return np.nanmean(stack, axis=0)
    if how == "median":
        return np.nanmedian(stack, axis=0)
    return arr[row, col]


def main():
    pts = grid_points()
    dem, tr = build_dem(download_tiles())
    # NASADEM/SRTM has ~1-2 m of high-frequency noise, which inflates 30 m slopes (raw median ~4.3% vs
    # ~3.0% after sigma=1 px smoothing). Slope, TWI and flow routing use the sigma=1 smoothed DEM.
    dem_f = np.nan_to_num(dem, nan=float(np.nanmean(dem)))
    z1 = ndimage.gaussian_filter(dem_f, 1.0)
    dzdx, dzdy = horn(z1, RES)
    tanb = np.hypot(dzdx, dzdy)
    slope_pct = 100 * tanb
    zs = ndimage.gaussian_filter(dem_f, 1.5)
    curv = profile_curvature(zs, RES) * 100.0  # 1/(100 m)
    recv, order, filled = priority_flood_d8(z1.astype(np.float64))
    acc = accumulate(recv, order).reshape(dem.shape)
    sca = acc * RES  # specific catchment area, m2 per m contour width
    twi = np.log(sca / np.maximum(tanb, 0.001))
    print("fill depth max", float(np.nanmax(filled - z1)), "acc max (km2)", acc.max() * RES * RES / 1e6)
    out = pts[["grid_id"]].copy()
    out["elev_m"] = sample(dem, tr, pts, "mean")
    out["slope_pct"] = sample(slope_pct, tr, pts, "mean")
    out["curvature"] = sample(curv, tr, pts, "mean")
    out["twi"] = sample(twi, tr, pts, "mean")
    out["flowacc"] = sample(acc, tr, pts, "median")
    out["flowacc_center"] = sample(acc, tr, pts, "center")
    out["field_id"] = ["f%05d" % g for g in out.grid_id]
    out.to_parquet(OUT / "terrain_points.parquet", index=False)
    np.save(OUT / "dem30_utm.npy", dem)
    (OUT / "dem30_transform.json").write_text(json.dumps(list(tr)[:6]))
    print(out.describe().T.round(3))


if __name__ == "__main__":
    main()
