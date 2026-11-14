"""Field cells and per-field living cover from HLS (focus area).

Inputs
  data/raw/hls/cells.npz, data/raw/hls/g/*.npz      (p11: 400 m cell grid + per-granule per-cell HLS means)
  data/raw/cdl/cdl_<year>_basins.tif 2016-2025      (cdl module; wait for DONE_<year>; fallback PC usda-cdl <= 2021)
  data/processed/soils_mukey.parquet, data/raw/soils/mukey_90m.tif, data/raw/terrain/slope_30m.tif (or slope_90m)
  data/processed/power_cells.parquet

Field rule (CONTRACTS.md): 400 m x 400 m EPSG:5070 cell (centre inside a focus HUC-12) kept when >= 80% of its 30 m
CDL pixels (pixel centre inside the cell) are ONE row crop letter (C corn, S soy, R other row crop) in >= 7 of 2016-2025.

HLS per-field observation: mean over the cell's inner 30 m pixels (>= 30 m from the cell edge) that are Fmask-clear.
An observation is `clear` when >= 60% of the inner pixels are clear; only clear observations are used downstream
(rows with 20-60% clear pixels are kept in hls_field_ts with clear=False for transparency). Dormant-season scene QA:
scenes between Nov 15 and Apr 30 whose median field NDVI exceeds 0.255 are scene-wide artefacts (residue/soil sits
at ~0.21-0.25 and cover crops are < 10% of fields) and are marked clear=False. Same-day duplicates
(L30 + S30 or two S30 granules) -> keep the one with more clear pixels (ties: L30).

Living cover (per clear observation) = at least half of the cell's clear inner pixels have NDVI >= 0.30, i.e. the
cell-MEDIAN NDVI >= 0.30 (sensitivity 0.25 / 0.35). The median (not the mean) is used so grassed waterways, ditches
and field-edge grass (up to 20% of a field cell) cannot make a bare field look green in April. Daily status = that
pixel share linearly interpolated between clear observations (gaps up to 120 days; longer gaps are unknown),
living when >= 0.5.

Year convention: field_year.year is the CROP YEAR = USGS water year: Oct 1 (year-1) .. Sep 30 (year). The winter of
Nov 2024-Apr 2025 belongs to crop year 2025, together with the 2025 cash crop (crop = CDL letter of calendar 2025).
field_month uses calendar year and month.

Winter cover (crop year Y): fall window Oct 15-Dec 15 of Y-1 (after harvest of crop Y-1), spring window
Mar 15-May 10 of Y (before the crop Y canopy). Per window s = 2nd-highest (single value if only one) share of the
field's pixels with NDVI >= 0.30 over the clear observations. Fall observations count only after the field's fall
NDVI minimum (Sep 15-Nov 30, i.e. after senescence/harvest), so standing green crops do not count.
winter_cover_score = max(s_spring, s_fall) (0-1); winter_cover = >= 2 clear obs with >= 50% of pixels NDVI >= 0.30
(cell-median NDVI >= 0.30) in the spring window, or >= 2 such post-harvest obs in the fall window.
"""
import glob
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds

from common import PROC, RAW
from fields_common import CELL, HLS_RAW, LETTER_LUT, load_focus, pc_cdl_mosaic

YEARS = list(range(2016, 2026))
CDL_DIR = RAW / "cdl"
CLEAR_MIN = 0.60     # share of inner pixels clear for a clear observation
KEEP_MIN = 0.20      # rows kept in hls_field_ts (clear=False below CLEAR_MIN)
MAX_GAP = 120        # days, max interpolation gap
THRESH = [0.25, 0.30, 0.35]
T0 = 0.30
SCENE_MED_MAX = 0.255  # dormant-season scene QA (see main)


# ---------------------------------------------------------------- inputs
def wait_for(paths, timeout=2400):
    paths = [str(p) for p in paths]
    if all(os.path.exists(p) for p in paths):
        return True
    cond = " && ".join(f"[ -f '{p}' ]" for p in paths)
    print(f"waiting up to {timeout}s for {len(paths)} sentinel files ...", flush=True)
    subprocess.run(["timeout", str(timeout), "bash", "-c", f"until {cond}; do sleep 30; done"])
    return all(os.path.exists(p) for p in paths)


def cells():
    z = np.load(HLS_RAW / "cells.npz", allow_pickle=False)
    return {k: z[k] for k in z.files}


def cell_lookup(C):
    cmin, rmin = C["col"].min(), C["row"].min()
    lut = np.full((C["row"].max() - rmin + 1, C["col"].max() - cmin + 1), -1, np.int32)
    lut[C["row"] - rmin, C["col"] - cmin] = np.arange(len(C["col"]))

    def f(x, y):
        c = np.floor(x / CELL).astype(np.int64) - cmin
        r = np.floor(y / CELL).astype(np.int64) - rmin
        ok = (c >= 0) & (r >= 0) & (c < lut.shape[1]) & (r < lut.shape[0])
        out = np.full(x.shape, -1, np.int32)
        out[ok] = lut[r[ok], c[ok]]
        return out
    return f


def raster_cells(arr, tr, lookup):
    """Cell index of every pixel centre of `arr` (on transform tr, EPSG:5070)."""
    H, W = arr.shape
    xs = tr.c + (np.arange(W) + 0.5) * tr.a
    ys = tr.f + (np.arange(H) + 0.5) * tr.e
    X, Y = np.meshgrid(xs, ys)
    return lookup(X, Y)


def read_local(path, bounds):
    with rasterio.open(path) as s:
        assert s.crs.to_epsg() == 5070
        win = from_bounds(*bounds, transform=s.transform).round_offsets().round_lengths()
        return s.read(1, window=win), s.window_transform(win)


def cdl_letters(C, lookup, bounds):
    n = len(C["col"])
    lets = {}
    share_row = {}
    src = {}
    for yr in YEARS:
        f = CDL_DIR / f"cdl_{yr}_basins.tif"
        if (CDL_DIR / f"DONE_{yr}").exists() and f.exists():
            arr, tr = read_local(f, bounds); src[yr] = f"data/raw/cdl/cdl_{yr}_basins.tif"
        elif yr <= 2021:
            arr, tr = pc_cdl_mosaic(yr, bounds); src[yr] = "PC usda-cdl"
        else:
            raise RuntimeError(f"CDL {yr} not available (no DONE_{yr} sentinel and PC usda-cdl ends 2021)")
        lab = raster_cells(arr, tr, lookup)
        m = lab >= 0
        L = LETTER_LUT[arr[m]]
        cnt = {}
        for ch in "CSWROHPX":
            cnt[ch] = np.bincount(lab[m][L == ord(ch)], minlength=n)
        tot = np.bincount(lab[m], minlength=n).astype(float)
        stack = np.stack([cnt[ch] for ch in "CSWROHPX"], 1)
        lets[yr] = np.array(list("CSWROHPX"))[stack.argmax(1)]
        share_row[yr] = np.max(np.stack([cnt["C"], cnt["S"], cnt["R"]], 1), 1) / np.maximum(tot, 1)
        print(f"  CDL {yr} ({src[yr]}): pixels/cell median {int(np.median(tot))}", flush=True)
    return lets, share_row, src


# ---------------------------------------------------------------- HLS
def load_hls(C):
    rows = []
    metas = []
    for f in sorted(glob.glob(str(HLS_RAW / "g" / "*.npz"))):
        if f.endswith(".tmp.npz"):
            continue
        z = np.load(f, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        metas.append(meta)
        if len(z["cell"]) == 0:
            continue
        rows.append(pd.DataFrame({"cell": z["cell"], "n_clear": z["n_clear"].astype(np.int32),
                                  "ndvi": z["ndvi"], "ndti": z["ndti"], "gcvi": z["gcvi"],
                                  "p25": z["live25"], "p30": z["live30"], "p35": z["live35"],
                                  "item": meta["item_id"], "sensor": meta["sensor"],
                                  "date": pd.Timestamp(meta["datetime"][:10])}))
    man = pd.DataFrame(metas)
    df = pd.concat(rows, ignore_index=True)
    df["clear_share"] = df.n_clear / C["npx"][df.cell]
    return df, man


def interp_daily(dates_obs, ndvi_obs, days):
    """Linear interpolation of NDVI to `days` (int day numbers); NaN where the bracketing gap > MAX_GAP or outside."""
    out = np.full(days.size, np.nan, np.float32)
    if len(dates_obs) < 2:
        return out
    v = np.interp(days, dates_obs, ndvi_obs)
    i = np.searchsorted(dates_obs, days, side="right")
    ok = (i > 0) & (i < len(dates_obs))
    gap = np.zeros(days.size)
    gap[ok] = dates_obs[i[ok]] - dates_obs[i[ok] - 1]
    exact = np.isin(days, dates_obs)
    good = (ok & (gap <= MAX_GAP)) | exact
    out[good] = v[good]
    return out


def q2(v):
    v = np.sort(v[~np.isnan(v)])
    if v.size == 0:
        return np.nan
    return v[-2] if v.size >= 2 else v[-1]


def winter_metrics(d, n, p, Y):
    """One field, all clear obs: d dates (datetime64[D]), n cell-mean NDVI, p share of the cell's pixels with
    NDVI >= threshold (p >= 0.5 <=> cell-median NDVI >= threshold). Returns metrics for crop year Y."""
    fs, fe = np.datetime64(f"{Y - 1}-10-15"), np.datetime64(f"{Y - 1}-12-15")
    ss, se = np.datetime64(f"{Y}-03-15"), np.datetime64(f"{Y}-05-10")
    sm = (d >= ss) & (d <= se)
    sp = p[sm]
    # fall: Sep 1 .. Dec 15 of Y-1; post-harvest = on/after the minimum NDVI observed from Sep 15 to Nov 30
    fm_all = (d >= np.datetime64(f"{Y - 1}-09-15")) & (d <= fe)
    fa = np.array([], np.float32)
    n_fall_win = int(((d >= fs) & (d <= fe)).sum())
    if fm_all.any():
        dd, nn = d[fm_all], n[fm_all]
        mwin = dd <= np.datetime64(f"{Y - 1}-11-30")
        if mwin.any():
            tmin = dd[mwin][np.argmin(nn[mwin])]
            post = (dd > tmin) & (dd >= fs)
            fa = p[fm_all][post]
    s_sp, s_fa = q2(sp), q2(fa)
    score = np.nanmax([s_sp, s_fa]) if not (np.isnan(s_sp) and np.isnan(s_fa)) else np.nan
    cover = bool((sp >= 0.5).sum() >= 2 or (fa >= 0.5).sum() >= 2)
    return dict(s_spring=s_sp, s_fall=s_fa, winter_cover_score=score, winter_cover=cover,
                n_obs_spring=int(sm.sum()), n_obs_fall=n_fall_win)


def main():
    foc = load_focus()
    C = cells()
    n = len(C["col"])
    lookup = cell_lookup(C)
    x0, y0 = C["x5070"].min() - 400, C["y5070"].min() - 400
    x1, y1 = C["x5070"].max() + 400, C["y5070"].max() + 400
    bounds = (x0, y0, x1, y1)

    # ---------------- CDL field rule
    if not wait_for([CDL_DIR / f"DONE_{y}" for y in YEARS]):
        print("WARNING: some CDL sentinels still missing; using PC usda-cdl for <= 2021", flush=True)
    lets, share_row, cdl_src = cdl_letters(C, lookup, bounds)
    q = np.stack([share_row[y] >= 0.80 for y in YEARS], 1)
    keep = q.sum(1) >= 7
    print(f"cells {n}, fields (>=80% one row crop in >=7 of 10 yrs): {keep.sum()} ({keep.mean():.1%})", flush=True)

    # ---------------- soils + slope
    soil_ok = wait_for([RAW / "soils" / "mukey_90m.tif", PROC / "soils_mukey.parquet"], timeout=600)
    mu = pd.read_parquet(PROC / "soils_mukey.parquet").set_index("mukey")
    mk, trm = read_local(RAW / "soils" / "mukey_90m.tif", bounds)
    lab = raster_cells(mk, trm, lookup)
    m = (lab >= 0) & (mk > 0)
    dcl = mu.drainagecl.reindex(mk[m]).fillna("unknown").to_numpy()
    pfc = mu.poorly_frac_comp.reindex(mk[m]).to_numpy()
    sdf = pd.DataFrame({"cell": lab[m], "dcl": dcl, "pfc": pfc})
    dmode = sdf[sdf.dcl != "unknown"].groupby("cell").dcl.agg(lambda s: s.value_counts().index[0])
    pshare = sdf.groupby("cell").pfc.mean()
    slope_path = RAW / "terrain" / "slope_30m.tif"
    if not slope_path.exists():
        slope_path = RAW / "terrain" / "slope_90m.tif"
    sl, trs = read_local(slope_path, bounds)
    labs = raster_cells(sl, trs, lookup)
    ms = (labs >= 0) & np.isfinite(sl)
    slope = np.bincount(labs[ms], weights=sl[ms], minlength=n) / np.maximum(np.bincount(labs[ms], minlength=n), 1)

    # ---------------- fields table
    t = Transformer.from_crs(5070, 4326, always_xy=True)
    lon, lat = t.transform(C["x5070"], C["y5070"])
    pc = pd.read_parquet(PROC / "power_cells.parquet")
    dist = (lat[:, None] - pc.lat.to_numpy()[None]) ** 2 + ((lon[:, None] - pc.lon.to_numpy()[None]) * 0.74) ** 2
    pcell = pc.cell_id.to_numpy()[dist.argmin(1)]
    idx = np.flatnonzero(keep)
    fid = np.array([f"F{i:05d}" for i in range(n)])
    h = CELL / 2
    polys = []
    for i in idx:
        xs = C["x5070"][i] + np.array([-h, h, h, -h, -h]); ys = C["y5070"][i] + np.array([-h, -h, h, h, -h])
        lo, la = t.transform(xs, ys)
        polys.append([[round(a, 5), round(b, 5)] for a, b in zip(lo, la)])
    F = pd.DataFrame({"field_id": fid[idx], "lon": np.round(lon[idx], 5), "lat": np.round(lat[idx], 5),
                      "x5070": C["x5070"][idx], "y5070": C["y5070"][idx], "huc12": C["huc12"][idx],
                      "area_ha": np.float32(CELL * CELL / 1e4)})
    for y in YEARS:
        F[f"cdl_{y}"] = lets[y][idx]
    F["crop_seq"] = ["".join(lets[y][i] for y in YEARS) for i in idx]
    F["n_rowcrop_years"] = q[idx].sum(1).astype(np.int8)
    F["drainagecl"] = dmode.reindex(idx).fillna("unknown").to_numpy()
    F["poorly_share"] = np.round(pshare.reindex(idx).to_numpy(), 3).astype(np.float32)
    F["poorly_drained"] = F.poorly_share >= 0.5
    F["slope_pct"] = np.round(slope[idx], 2).astype(np.float32)
    F["power_cell_id"] = pcell[idx]
    F["polygon"] = polys
    F.to_parquet(PROC / "fields.parquet", index=False, compression="zstd")
    print(f"fields.parquet: {len(F)} rows, {os.path.getsize(PROC / 'fields.parquet') / 1e6:.2f} MB", flush=True)

    # ---------------- HLS per field
    df, man = load_hls(C)
    df = df[keep[df.cell] & (df.clear_share >= KEEP_MIN)].copy()
    # dormant-season scene QA: with < 10% cover crops, the scene-median field NDVI between Nov 15 and Apr 30 should
    # sit at the residue/soil level (~0.21-0.25). Scenes far above that are scene-wide artefacts (seen mostly on S30
    # at low sun: e.g. 2021-03-05 S30 median 0.32 vs same-day L30 0.26), so they are not used.
    md = df.date.dt.month * 100 + df.date.dt.day
    dormant = (md >= 1115) | (md <= 430)
    good = df.clear_share >= CLEAR_MIN
    sc = df[good & dormant].groupby("item").ndvi.agg(["median", "size"])
    bad_items = sc[(sc["size"] >= 20) & (sc["median"] > SCENE_MED_MAX)]
    df["scene_ok"] = ~df.item.isin(bad_items.index)
    df["clear"] = good & df.scene_ok
    df["_l"] = (df.sensor != "L30").astype(np.int8)
    df = df.sort_values(["cell", "date", "clear", "n_clear", "_l"], ascending=[True, True, False, False, True])
    df = df.drop_duplicates(["cell", "date"], keep="first").drop(columns="_l")
    print(f"dormant-season scene QA: {len(bad_items)} of {sc.shape[0]} dormant scenes dropped "
          f"(median field NDVI > {SCENE_MED_MAX}): " + ", ".join(f"{i.split('.')[1]} {i.split('.')[3][:7]} "
                                                               f"{m:.3f}" for i, m in bad_items["median"].items()),
          flush=True)
    df["field_id"] = fid[df.cell]
    ts = df[["field_id", "date", "sensor", "ndvi", "ndti", "gcvi", "p30", "clear_share", "clear"]].rename(
        columns={"p30": "live_px_share"})
    ts["date"] = ts.date.dt.date
    for c in ("ndvi", "ndti", "gcvi", "live_px_share", "clear_share"):
        ts[c] = ts[c].round(3).astype(np.float32)
    schema = pa.schema([("field_id", pa.dictionary(pa.int16(), pa.string())), ("date", pa.date32()),
                        ("sensor", pa.dictionary(pa.int8(), pa.string())), ("ndvi", pa.float32()),
                        ("ndti", pa.float32()), ("gcvi", pa.float32()), ("live_px_share", pa.float32()),
                        ("clear_share", pa.float32()), ("clear", pa.bool_())])
    tbl = pa.Table.from_pandas(ts.reset_index(drop=True), preserve_index=False).cast(schema)
    pq.write_table(tbl, PROC / "hls_field_ts.parquet", compression="zstd", compression_level=19,
                   use_byte_stream_split=["ndvi", "ndti", "gcvi", "live_px_share", "clear_share"])
    print(f"hls_field_ts.parquet: {len(ts)} rows ({ts.clear.sum()} clear), "
          f"{os.path.getsize(PROC / 'hls_field_ts.parquet') / 1e6:.2f} MB", flush=True)

    # ---------------- daily interpolation, field_month, field_year
    cl = df[df.clear]
    start = np.datetime64("2019-10-01"); end = np.datetime64(str(cl.date.max().date()))
    days = np.arange(start, end + np.timedelta64(1, "D")).astype("datetime64[D]")
    dnum = days.astype(np.int64)
    dser = pd.DatetimeIndex(days)
    cal_y, cal_m = dser.year.to_numpy(), dser.month.to_numpy()
    crop_y = cal_y + (cal_m >= 10)
    doy = dser.dayofyear.to_numpy()
    fm_rows, fy_rows, sens = [], [], {t_: {} for t_ in THRESH}
    groups = {k: g for k, g in cl.groupby("field_id")}
    for fi in F.field_id:
        g = groups.get(fi)
        if g is None:
            continue
        d = g.date.values.astype("datetime64[D]"); nv = g.ndvi.to_numpy(np.float32)
        P = {t_: g[f"p{int(round(t_ * 100))}"].to_numpy(np.float32) for t_ in THRESH}
        V = {t_: interp_daily(d.astype(np.int64), P[t_], dnum) for t_ in THRESH}
        v = V[T0]
        known = ~np.isnan(v)
        live = known & (v >= 0.5)
        bare = known & (v < 0.5)
        # field_month (calendar)
        obs_m = pd.Series(1, index=pd.DatetimeIndex(d)).groupby([pd.DatetimeIndex(d).year,
                                                                pd.DatetimeIndex(d).month]).size()
        key = cal_y * 100 + cal_m
        uk, inv = np.unique(key, return_inverse=True)
        nk = np.bincount(inv, weights=known, minlength=uk.size)
        nl = np.bincount(inv, weights=live, minlength=uk.size)
        for j, k in enumerate(uk):
            yy, mm = divmod(int(k), 100)
            no = int(obs_m.get((yy, mm), 0))
            if nk[j] == 0 and no == 0:
                continue
            lf = nl[j] / nk[j] if nk[j] else np.nan
            fm_rows.append((fi, yy, mm, lf, 1 - lf if nk[j] else np.nan, no))
        # field_year (crop year)
        frow = F.loc[F.field_id == fi].iloc[0]
        for Y in range(2020, int(crop_y.max()) + 1):
            m = crop_y == Y
            if not m.any():
                continue
            if Y > int(cal_y.max()) or (Y == int(cal_y.max()) and cal_m[m].max() < 9):
                continue  # crop year not complete enough (current, partial)
            wm = winter_metrics(d, nv, P[T0], Y)
            mapr = m & (cal_y == Y) & (cal_m >= 4) & (cal_m <= 6)
            moct = m & (cal_y == Y - 1) & (cal_m >= 10) & (cal_m <= 12)
            # green-up: first DOY >= 60 in calendar Y with NDVI >= 0.30 sustained for the next 14 days
            gm = (cal_y == Y) & (doy >= 60)
            gv = v[gm]; gd = doy[gm]
            okg = np.nan_to_num(gv, nan=-1) >= 0.5
            sust = np.convolve(okg.astype(np.int16), np.ones(15, np.int16), "valid") == 15 \
                if len(gv) >= 15 else np.array([], bool)
            gu = int(gd[np.argmax(sust)]) if sust.any() else -1
            yo = (d >= np.datetime64(f"{Y - 1}-10-01")) & (d <= np.datetime64(f"{Y}-09-30"))
            fy_rows.append(dict(field_id=fi, year=Y, crop=frow.get(f"cdl_{Y}", None) if Y <= 2025 else None,
                                prev_crop=frow.get(f"cdl_{Y - 1}", None) if 2016 <= Y - 1 <= 2025 else None,
                                winter_cover_score=wm["winter_cover_score"], winter_cover=wm["winter_cover"],
                                s_spring=wm["s_spring"], s_fall=wm["s_fall"],
                                bare_days_total=int(bare[m].sum()), bare_days_aprjun=int(bare[mapr].sum()),
                                bare_days_octdec=int(bare[moct].sum()) if known[moct].any() else -1,
                                days_known=int(known[m].sum()), green_up_doy=gu, n_clear_obs=int(yo.sum()),
                                n_obs_spring=wm["n_obs_spring"], n_obs_fall=wm["n_obs_fall"]))
            for t_ in THRESH:
                sens[t_][(fi, Y)] = (winter_metrics(d, nv, P[t_], Y)["winter_cover"],
                                     float((V[t_][m] < 0.5).sum()))
    FM = pd.DataFrame(fm_rows, columns=["field_id", "year", "month", "living_frac", "bare_frac", "n_obs"])
    FM["year"] = FM.year.astype(np.int16); FM["month"] = FM.month.astype(np.int8)
    FM["n_obs"] = FM.n_obs.astype(np.int16)
    for c in ("living_frac", "bare_frac"):
        FM[c] = FM[c].round(3).astype(np.float32)
    FM.to_parquet(PROC / "field_month.parquet", index=False, compression="zstd")
    FY = pd.DataFrame(fy_rows)
    for c in ("winter_cover_score", "s_spring", "s_fall"):
        FY[c] = FY[c].round(3).astype(np.float32)
    for c in ("year", "bare_days_total", "bare_days_aprjun", "bare_days_octdec", "days_known", "green_up_doy",
              "n_clear_obs", "n_obs_spring", "n_obs_fall"):
        FY[c] = FY[c].astype(np.int16)
    FY.to_parquet(PROC / "field_year.parquet", index=False, compression="zstd")
    print(f"field_month: {len(FM)} rows; field_year: {len(FY)} rows", flush=True)

    # ---------------- report
    rep = {"dormant_scenes_dropped": {i: round(float(m), 3) for i, m in bad_items["median"].items()},
           "n_cells": int(n), "n_fields": int(len(F)), "cdl_source": {str(k): v for k, v in cdl_src.items()},
           "n_granules": int(len(man)), "n_granules_with_clear": int((man.n_clear > 0).sum()),
           "granules_by_sensor": man.groupby("sensor").size().to_dict(),
           "granules_used_by_sensor": man[man.n_clear > 0].groupby("sensor").size().to_dict()}
    per_fy = FY.groupby("year").agg(n=("field_id", "size"), clear_obs_median=("n_clear_obs", "median"),
                                    winter_cover_pct=("winter_cover", lambda s: 100 * s.mean()),
                                    score_mean=("winter_cover_score", "mean"),
                                    bare_days_median=("bare_days_total", "median"),
                                    days_known_median=("days_known", "median"))
    for t_ in THRESH:
        s = pd.Series({k: v[0] for k, v in sens[t_].items()})
        per_fy[f"wc_pct_t{t_:.2f}"] = (100 * s.groupby(level=1).mean()).reindex(per_fy.index)
        b = pd.Series({k: v[1] for k, v in sens[t_].items()})
        per_fy[f"bare_days_med_t{t_:.2f}"] = b.groupby(level=1).median().reindex(per_fy.index)
    print(per_fy.round(1).to_string())
    rep["by_crop_year"] = json.loads(per_fy.round(2).to_json(orient="index"))
    # seasonal NDVI curve by crop and month (clear obs, fields)
    cl2 = cl.copy()
    cl2["y"] = cl2.date.dt.year; cl2["m"] = cl2.date.dt.month
    lk = F.set_index("field_id")
    cl2["crop"] = [lk.at[f_, f"cdl_{y_}"] if 2016 <= y_ <= 2025 else "?" for f_, y_ in zip(cl2.field_id, cl2.y)]
    curve = cl2[cl2.crop.isin(["C", "S"])].groupby(["crop", "m"]).ndvi.median().unstack(0).round(3)
    print("median NDVI by month (clear obs on corn/soy field-years):\n", curve.to_string())
    rep["ndvi_median_by_month"] = json.loads(curve.to_json())
    rep["hls_through"] = str(cl.date.max().date())
    rep["fields_by_huc12"] = F.groupby("huc12").size().to_dict()
    rep["crop_seq_top"] = F.crop_seq.value_counts().head(8).to_dict()
    rep["drainage"] = F.drainagecl.value_counts().to_dict()
    rep["poorly_drained_pct"] = round(100 * float(F.poorly_drained.mean()), 1)
    rep["slope_median"] = float(F.slope_pct.median())
    rep["focus"] = foc["huc12s"]
    (HLS_RAW / "p12_report.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({k: rep[k] for k in ("n_cells", "n_fields", "n_granules", "n_granules_with_clear",
                                          "granules_used_by_sensor", "hls_through", "poorly_drained_pct",
                                          "slope_median")}, default=str))
    for fn in ("fields", "hls_field_ts", "field_month", "field_year"):
        sz = os.path.getsize(PROC / f"{fn}.parquet") / 1e6
        assert sz < 5, (fn, sz)


if __name__ == "__main__":
    sys.exit(main())
