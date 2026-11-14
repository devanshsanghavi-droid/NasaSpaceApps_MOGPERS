"""Watershed living-cover / bare-soil shares of persistent row-crop land from NASA MODIS 13Q1 (Terra + Aqua).

Source: Planetary Computer `modis-13Q1-061` (MOD13Q1 Terra + MYD13Q1 Aqua, 250 m, 16-day composites; Terra and Aqua
are offset by 8 days -> 8-day effective cadence), tiles h10v04 + h11v04, 2015-06-10 .. latest.
Only the basin window of `250m_16_days_NDVI`, `250m_16_days_pixel_reliability` and
`250m_16_days_composite_day_of_the_year` is read; values at masked pixels (p08_modis_mask.py) are cached per item in
data/raw/modis/cache/*.npz so reruns only fetch new composites.

Per composite, over masked persistent-row-crop pixels:
  valid = reliability 0/1 and NDVI not fill; snow = reliability 2; cloud = reliability 3; fill = no data
  living = valid & NDVI >= 0.30 ; bare = valid & NDVI < 0.30 (sensitivity at 0.25 / 0.35)
Outputs (data/processed/):
  cover_basin_8day.parquet   basin, date (composite mid-date) ... see notes/modis.md
  cover_basin_daily.parquet  basin, date, daily interpolated shares, gap_days, filled (gap > 24 d)
  cover_huc12_8day.parquet   huc12, date ...
  modis_basin_year.parquet   per basin-year spring / fall bare summaries and bare & non-snow days
Run: python3 pipeline/p09_modis_cover.py
"""
import os

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF")

import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402
from datetime import date  # noqa: E402
from urllib.parse import urlsplit, urlunsplit  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import planetary_computer  # noqa: E402
import pystac_client  # noqa: E402
import rasterio  # noqa: E402
from rasterio.windows import Window  # noqa: E402

from common import APP, PROC, RAW, STAC_URL  # noqa: E402

OUT = RAW / "modis"
CACHE = OUT / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
START = "2015-06-10"
ASSETS = {"ndvi": "250m_16_days_NDVI", "rel": "250m_16_days_pixel_reliability",
          "doy": "250m_16_days_composite_day_of_the_year"}
THRESH = {"t25": 2500, "t30": 3000, "t35": 3500}  # NDVI x 1e4
VALID_MIN = 0.30       # composites with valid_frac below this are not used for daily living/bare interpolation
GAP_FLAG = 24          # days
TILE_MIN = 0.90        # composites missing a MODIS tile over >10% of a basin's mask are not used for daily series
BASINS = {1: "raccoon", 2: "desmoines"}
WORKERS = 6
ASOF_LATENCY = 3       # days after the 16-day window ends before a composite is assumed published (avail = start+16+3)
ASOF_STALE = 40        # days; asof_stale = age_days > 40 (age = t - last day of the as-of composite window)
SUPPORT_GAP = 45       # days; summaries only count days interpolated between composites <= 45 d apart
MIN_COMPOSITES = 3     # usable composites needed for nov / apr / winter living means
HUC_TILE_MIN = 0.5     # HUC-12 rows with tile_cover_frac below this get NaN valid_frac / shares


def sign(href):
    s = urlsplit(href)
    return planetary_computer.sign(urlunsplit((s.scheme, s.netloc, s.path, "", "")))


# ---------------------------------------------------------------- grid / mask
def load_mask():
    z = np.load(OUT / "mask_grid.npz")
    r0, c0 = z["offset"]
    rr, cc = np.nonzero(z["mask"])
    gr, gc = rr + r0, cc + c0
    px = pd.DataFrame({"gr": gr, "gc": gc, "huc_idx": z["huc_idx"][rr, cc], "basin_id": z["basin_id"][rr, cc]})
    px["h"], px["v"] = gc // 4800, gr // 4800
    tiles = {}
    for (h, v), sub in px.groupby(["h", "v"]):
        tr, tc = sub.gr.to_numpy() - v * 4800, sub.gc.to_numpy() - h * 4800
        wr0, wc0 = int(tr.min()), int(tc.min())
        tiles[f"h{h:02d}v{v:02d}"] = dict(idx=sub.index.to_numpy(), r=tr - wr0, c=tc - wc0,
                                          win=Window(wc0, wr0, int(tc.max()) - wc0 + 1, int(tr.max()) - wr0 + 1),
                                          key=int((sub.gr.to_numpy().astype(np.int64) * 100000 + sub.gc).sum() % (2**61)))
    return px, tiles, z["huc12"], z["basin_of_idx"]


# ---------------------------------------------------------------- STAC + reads
def list_items(tiles):
    client = pystac_client.Client.open(STAC_URL)
    end = date.today().isoformat()
    best = {}
    for it in client.search(collections=["modis-13Q1-061"], bbox=[-96.12, 41.46, -93.58, 44.27],
                            datetime=f"{START}/{end}").items():
        p = it.id.split(".")  # MOD13Q1.A2024177.h11v04.061.2024195022907
        if p[2] not in tiles:
            continue
        k = (p[0], p[1], p[2])
        if k not in best or p[4] > best[k].id.split(".")[4]:
            best[k] = it
    return best


def cache_path(k):
    return CACHE / f"{k[0]}.{k[1]}.{k[2]}.npz"


def fetch(k, it, t):
    f = cache_path(k)
    if f.exists():
        try:
            z = np.load(f)
            if int(z["key"]) == t["key"]:
                return k, "cached"
        except Exception:
            pass
    out = {}
    for name, asset in ASSETS.items():
        for a in range(6):
            try:
                with rasterio.open(sign(it.assets[asset].href)) as src:
                    arr = src.read(1, window=t["win"])
                out[name] = arr[t["r"], t["c"]]
                break
            except Exception as e:  # 403 = expired SAS -> re-signed on next attempt
                err = e
                time.sleep(2 * (a + 1))
        else:
            raise RuntimeError(f"{it.id} {asset}: {str(err)[:200]}")
    tmp = f.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, ndvi=out["ndvi"].astype(np.int16), rel=out["rel"].astype(np.uint8),
                        doy=out["doy"].astype(np.int16), key=t["key"])
    os.replace(tmp, f)
    return k, "fetched"


# ---------------------------------------------------------------- per-composite stats
def group_counts(g, ng, valid, snow, cloud, fill, liv, ndvi, off_valid, off_obs, present):
    bc = lambda w=None: np.bincount(g, weights=w, minlength=ng)  # noqa: E731
    d = {"n_px": bc(), "n_present": bc(present), "n_valid": bc(valid), "n_snow": bc(snow), "n_cloud": bc(cloud), "n_fill": bc(fill),
         "ndvi_sum": bc(np.where(valid, ndvi, 0.0)), "off_valid_sum": bc(off_valid), "off_obs_sum": bc(off_obs)}
    for tk, m in liv.items():
        d[f"n_liv_{tk}"] = bc(m)
    return pd.DataFrame(d)


def derive(df):
    nv = df.n_valid.replace(0, np.nan)
    nobs = (df.n_valid + df.n_snow).replace(0, np.nan)
    o = pd.DataFrame(index=df.index)
    o["n_px"] = df.n_px.astype(int)
    o["n_valid"] = df.n_valid.astype(int)
    o["tile_cover_frac"] = df.n_present / df.n_px.replace(0, np.nan)  # px whose MODIS tile exists for this composite
    o["valid_frac"] = df.n_valid / df.n_px.replace(0, np.nan)
    o["snow_frac"] = df.n_snow / df.n_px.replace(0, np.nan)
    o["cloud_frac"] = df.n_cloud / df.n_px.replace(0, np.nan)
    o["fill_frac"] = df.n_fill / df.n_px.replace(0, np.nan)
    o["living_share"] = df.n_liv_t30 / nv
    o["bare_share"] = 1 - o.living_share
    o["snow_share"] = df.n_snow / nobs
    o["bare_nonsnow_share"] = (df.n_valid - df.n_liv_t30) / nobs
    o["mean_ndvi"] = df.ndvi_sum / nv
    for tk in ("t25", "t35"):
        o[f"living_share_{tk}"] = df[f"n_liv_{tk}"] / nv
        o[f"bare_share_{tk}"] = 1 - o[f"living_share_{tk}"]
    o["obs_off_valid"] = df.off_valid_sum / nv
    o["obs_off_obs"] = df.off_obs_sum / nobs
    return o


def composite_stats(keys_by_tile, px, tiles, nh):
    n = len(px)
    ndvi = np.full(n, -3000, np.int16)
    rel = np.full(n, 255, np.uint8)
    doy = np.full(n, -1, np.int16)
    present = np.zeros(n, bool)
    for tile, k in keys_by_tile.items():
        z = np.load(cache_path(k))
        idx = tiles[tile]["idx"]
        ndvi[idx], rel[idx], doy[idx] = z["ndvi"], z["rel"], z["doy"]
        present[idx] = True
    adate = next(iter(keys_by_tile.values()))[1]
    year, start_doy = int(adate[1:5]), int(adate[5:])
    valid = (rel <= 1) & (ndvi > -3000)
    snow = rel == 2
    cloud = rel == 3
    fill = ~(valid | snow | cloud)
    off = doy.astype(np.float64) - start_doy
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    off[off < -300] += 366 if leap else 365  # composite crossing Dec 31: pixel DOY is in the next year
    off = np.where(doy > 0, off, np.nan)
    off_valid = np.where(valid & np.isfinite(off), off, 0.0)
    off_obs = np.where((valid | snow) & np.isfinite(off), off, 0.0)
    liv = {tk: valid & (ndvi >= th) for tk, th in THRESH.items()}
    ndvi_f = ndvi.astype(np.float64) * 1e-4
    b = group_counts(px.basin_id.to_numpy(), 3, valid, snow, cloud, fill, liv, ndvi_f, off_valid, off_obs, present).iloc[1:]
    b.index = [BASINS[i] for i in b.index]
    h = group_counts(px.huc_idx.to_numpy(), nh, valid, snow, cloud, fill, liv, ndvi_f, off_valid, off_obs, present)
    return b, h


# ---------------------------------------------------------------- daily + yearly
def _tdays(s):
    return (pd.to_datetime(s) - pd.Timestamp("1970-01-01")).dt.total_seconds().to_numpy() / 86400


def usable(d):
    """Composites usable for living/bare (ok) and for snow (okobs)."""
    full = d.tile_cover_frac >= TILE_MIN
    return (d.valid_frac >= VALID_MIN) & full, ((d.valid_frac + d.snow_frac) >= VALID_MIN) & full


def daily_series(b8, end_date):
    """Centred (non-causal) interpolated series + causal as-of series, one row per basin-day.

    Interpolated columns (living_share, ... snow_share, gap_days, filled, gapfill_src) are linear interpolation in time
    between bracketing composites (NOT causal: a day uses a composite up to ~16 d later). They are NaN after the last
    usable composite. As-of columns (*_asof, age_days, asof_stale, asof_src) only use composites already published on
    day t: composite_start + 16 + ASOF_LATENCY <= t, carried forward, never interpolated.
    """
    rows = []
    for basin, d in b8.groupby("basin"):
        d = d.sort_values("date")
        m_ok, m_obs = usable(d)
        ok, okobs = d[m_ok].copy(), d[m_obs].copy()
        t_ok, t_obs = _tdays(ok.obs_date), _tdays(okobs.obs_date_obs)
        o1, o2 = np.argsort(t_ok, kind="stable"), np.argsort(t_obs, kind="stable")
        t_ok, ok = t_ok[o1], ok.iloc[o1]
        t_obs, okobs = t_obs[o2], okobs.iloc[o2]
        last_interp = pd.Timestamp(np.floor(t_ok[-1]), unit="D")
        days = pd.date_range(max(pd.Timestamp("2015-07-01"), pd.Timestamp(np.ceil(t_ok[0]), unit="D")),
                             max(pd.Timestamp(end_date), last_interp), freq="D")
        td = (days - pd.Timestamp("1970-01-01")).days.to_numpy().astype(float)
        inr = td <= np.floor(t_ok[-1])
        out = pd.DataFrame({"basin": basin, "date": days.date})
        for c in ["living_share", "bare_share", "living_share_t25", "bare_share_t25", "living_share_t35",
                  "bare_share_t35", "mean_ndvi"]:
            out[c] = np.where(inr, np.interp(td, t_ok, ok[c].to_numpy()), np.nan)
        out["snow_share"] = np.where(td <= np.floor(t_obs[-1]), np.interp(td, t_obs, okobs.snow_share.to_numpy()), np.nan)
        out["bare_nonsnow_share"] = out.bare_share * (1 - out.snow_share)
        j = np.clip(np.searchsorted(t_ok, td, side="right"), 1, len(t_ok) - 1)
        out["gap_days"] = np.where(inr, np.round(t_ok[j] - t_ok[j - 1], 1), np.nan)
        out["filled"] = ~(out.gap_days <= GAP_FLAG)      # also True beyond the last composite (no interpolation)
        k = np.clip(np.searchsorted(t_obs, td, side="right"), 1, len(t_obs) - 1)
        out["snow_gap_days"] = np.where(td <= np.floor(t_obs[-1]), np.round(t_obs[k] - t_obs[k - 1], 1), np.nan)
        src = ok.gapfill_src.to_numpy()
        hls_br = (src[j] == "hls") | (src[j - 1] == "hls")
        out["gapfill_src"] = np.where(~inr, "none", np.where(out.gap_days > GAP_FLAG, "interp",
                                                             np.where(hls_br, "hls", "modis")))
        # ---- causal as-of
        t = pd.DataFrame({"date": days.astype("datetime64[ns]")})
        for sel, cols, tag in ((ok, ["bare_share", "living_share", "gapfill_src"], ""),
                               (okobs, ["snow_share"], "snow_")):
            e = sel.copy()
            st = pd.to_datetime(e.composite_start)
            e["avail"] = (st + pd.Timedelta(days=16 + ASOF_LATENCY)).astype("datetime64[ns]")
            e["wend"] = (st + pd.Timedelta(days=15)).astype("datetime64[ns]")
            e = e.sort_values("avail")
            m = pd.merge_asof(t, e[["avail", "wend"] + cols], left_on="date", right_on="avail", direction="backward")
            for c in cols:
                if c != "gapfill_src":
                    out[f"{c}_asof"] = m[c].to_numpy()
            if tag == "":
                out["age_days"] = (m["date"] - m["wend"]).dt.days.to_numpy().astype(float)
                out["asof_src"] = m["gapfill_src"].fillna("none").to_numpy()
            else:
                out["snow_age_days"] = (m["date"] - m["wend"]).dt.days.to_numpy().astype(float)
        out["bare_nonsnow_asof"] = out.bare_share_asof * (1 - out.snow_share_asof)
        out["asof_stale"] = ~(out.age_days <= ASOF_STALE)
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def window_mask(dates, m0, d0, m1, d1):
    md = dates.month * 100 + dates.day
    return (md >= m0 * 100 + d0) & (md <= m1 * 100 + d1)


def yearly(daily, b8):
    """Per basin-year summaries. Only days *supported* by observations count towards coverage:
    a day is supported for bare/living when it lies between two usable composites <= SUPPORT_GAP (45) days apart
    (MODIS or HLS gap-fill); for the bare & snow-free metrics, when the snow series is supported (snow_gap <= 45 d) and
    either bare/living is supported or the day is snow-dominated (snow_share >= 0.5). A metric is NaN unless >= 90 % of
    its window's days are supported (seasons) or >= 95 % of the year (annual metrics). Composite-month means need
    >= MIN_COMPOSITES usable composites in the month(s)."""
    dd = daily.copy()
    dd["date"] = pd.to_datetime(dd.date)
    dd["year"] = dd.date.dt.year
    dd["sup"] = dd.gap_days <= SUPPORT_GAP
    dd["sup_bns"] = (dd.snow_gap_days <= SUPPORT_GAP) & (dd.sup | (dd.snow_share >= 0.5))
    b8 = b8.copy()
    b8["date"] = pd.to_datetime(b8.date)
    rows = []
    for (basin, year), d in dd.groupby(["basin", "year"]):
        r = {"basin": basin, "year": year, "n_days": int(d.bare_share.notna().sum())}
        for name, (m0, d0, m1, d1, nfull) in {"spring": (3, 15, 6, 15, 93), "fall": (9, 15, 12, 15, 92)}.items():
            s = d[window_mask(d.date.dt, m0, d0, m1, d1)]
            okw = s.sup.sum() >= 0.9 * nfull
            okb = s.sup_bns.sum() >= 0.9 * nfull
            r[f"{name}_bare_mean"] = s.bare_share.mean() if okw else np.nan
            r[f"{name}_bare_mean_t25"] = s.bare_share_t25.mean() if okw else np.nan
            r[f"{name}_bare_mean_t35"] = s.bare_share_t35.mean() if okw else np.nan
            r[f"{name}_bare_nonsnow_mean"] = s.bare_nonsnow_share.mean() if okb else np.nan
            r[f"{name}_bare_nonsnow_days"] = s.bare_nonsnow_share.sum() if okb else np.nan
            r[f"{name}_filled_days"] = int(s.filled.sum())
            r[f"{name}_supported_days"] = int(s.sup.sum())
            r[f"{name}_hls_days"] = int((s.gapfill_src == "hls").sum())
        ny = 366 if (year % 4 == 0) else 365
        full = d.sup_bns.sum() >= 0.95 * ny
        r["bare_nonsnow_days"] = d.bare_nonsnow_share.sum() if full else np.nan
        r["days_majority_bare_nonsnow"] = int(((d.bare_share >= 0.5) & (d.snow_share < 0.5)).sum()) if full else np.nan
        r["filled_days"] = int(d.filled.sum())
        r["supported_days"] = int(d.sup.sum())
        r["supported_days_bare_nonsnow"] = int(d.sup_bns.sum())
        r["hls_days"] = int((d.gapfill_src == "hls").sum())
        e = b8[(b8.basin == basin)]
        e = e[usable(e)[0]]
        win = e[((e.date.dt.year == year) & (e.date.dt.month <= 2)) | ((e.date.dt.year == year - 1) & (e.date.dt.month == 12))]
        r["winter_living_mean"] = win.living_share.mean() if len(win) >= MIN_COMPOSITES else np.nan  # Dec(prev)-Feb
        r["winter_n_composites"] = len(win)
        for mname, mon in (("nov", 11), ("apr", 4)):
            m = e[(e.date.dt.year == year) & (e.date.dt.month == mon)]
            r[f"{mname}_living_mean"] = m.living_share.mean() if len(m) >= MIN_COMPOSITES else np.nan
            r[f"{mname}_n_composites"] = len(m)
            r[f"{mname}_n_hls"] = int((m.gapfill_src == "hls").sum())
        lv = b8[(b8.basin == basin) & (b8.date.dt.year == year)]
        r["n_composites"] = len(lv)
        r["n_hls_composites"] = int((lv.gapfill_src == "hls").sum())
        r["n_lowvalid_composites"] = int((lv.valid_frac < VALID_MIN).sum())
        rows.append(r)
    return pd.DataFrame(rows)


def merge_hls(b8):
    """Insert calibrated HLS composites (p09b) for 16-day windows with no MODIS composite. gapfill_src='hls'."""
    f = PROC / "cover_hls_8day.parquet"
    b8 = b8.copy()
    b8["gapfill_src"] = "modis"
    if not f.exists():
        print("cover_hls_8day.parquet not found: 2025 gap left unfilled (run p09b_hls_gapfill.py)")
        return b8
    h = pd.read_parquet(f)
    h = h[(h.calib == "qm") & h.in_gap].copy()
    have = set(zip(b8.basin, pd.to_datetime(b8.composite_start)))
    h = h[[(b, s) not in have for b, s in zip(h.basin, pd.to_datetime(h.composite_start))]]
    h["sensor"] = "hls"
    h["n_tiles"] = 0
    h["obs_date_obs"] = h.obs_date
    h["gapfill_src"] = "hls"
    h = h[[c for c in b8.columns if c in h.columns] + ["n_scenes"]]
    out = pd.concat([b8, h], ignore_index=True)
    out["date"] = pd.to_datetime(out.date).dt.date
    out["composite_start"] = pd.to_datetime(out.composite_start).dt.date
    print(f"merged {len(h)} HLS gap-fill basin composites")
    return out.sort_values(["basin", "date"]).reset_index(drop=True)


def blocker(msg):
    f = APP / "BLOCKERS.md"
    with open(f, "a") as fh:
        fh.write(f"\n## modis ({date.today().isoformat()})\n{msg}\n")


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    px, tiles, huc12, basin_of_idx = load_mask()
    print(f"masked px: {len(px)}; tiles: " + ", ".join(f"{k}: {len(v['idx'])} px window {v['win']}"
                                                     for k, v in tiles.items()))
    items = list_items(tiles)
    print(f"STAC items (deduped): {len(items)}  " +
          str(pd.Series([k[0][:3] + k[2] for k in items]).value_counts().to_dict()))
    fails = []
    n_f = n_c = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(fetch, k, it, tiles[k[2]]): k for k, it in items.items()}
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                _, st = fu.result()
                n_f += st == "fetched"
                n_c += st == "cached"
            except Exception as e:
                fails.append(f"{futs[fu]}: {e}")
            if i % 100 == 0:
                print(f"  {i}/{len(futs)} ({n_f} fetched, {n_c} cached, {len(fails)} failed) {time.time() - t0:.0f}s",
                      flush=True)
    print(f"reads done: {n_f} fetched, {n_c} cached, {len(fails)} failed, {time.time() - t0:.0f}s")
    if fails:
        print("FAILED:", *fails[:10], sep="\n  ")
        blocker(f"- {len(fails)} MODIS 13Q1 item reads failed after retries (composites dropped or partial):\n" +
                "\n".join(f"  - `{x}`" for x in fails[:20]))

    comps = {}
    for k in items:
        if cache_path(k).exists():
            comps.setdefault((k[0], k[1]), {})[k[2]] = k
    nh = len(huc12)
    brows, hrows = [], []
    for (prod, adate), kt in sorted(comps.items(), key=lambda x: (x[0][1], x[0][0])):
        start = pd.Timestamp(int(adate[1:5]), 1, 1) + pd.Timedelta(days=int(adate[5:]) - 1)
        b, h = composite_stats(kt, px, tiles, nh)
        meta = dict(date=(start + pd.Timedelta(days=8)).date(), composite_start=start.date(),
                    sensor="terra" if prod.startswith("MOD") else "aqua", n_tiles=len(kt))
        bd = derive(b)
        for c, v in meta.items():
            bd[c] = v
        bd["basin"] = bd.index
        brows.append(bd)
        hd = derive(h)
        hd["huc12"] = huc12
        hd["basin"] = np.array(list(BASINS.values()))[basin_of_idx - 1]
        hd["date"], hd["sensor"] = meta["date"], meta["sensor"]
        hrows.append(hd[hd.n_px > 0])
    b8 = pd.concat(brows, ignore_index=True)
    st = pd.to_datetime(b8.composite_start)
    b8["obs_date"] = st + pd.to_timedelta(b8.obs_off_valid.fillna(8.0), unit="D")
    b8["obs_date_obs"] = st + pd.to_timedelta(b8.obs_off_obs.fillna(8.0), unit="D")
    b8 = b8.drop(columns=["obs_off_valid", "obs_off_obs"])
    lead = ["basin", "date", "composite_start", "sensor", "n_tiles", "obs_date", "obs_date_obs"]
    b8 = b8[lead + [c for c in b8.columns if c not in lead]].sort_values(["basin", "date"]).reset_index(drop=True)
    b8 = merge_hls(b8)
    b8["avail_date"] = (pd.to_datetime(b8.composite_start) + pd.Timedelta(days=16 + ASOF_LATENCY)).dt.date
    fl = b8.select_dtypes("float").columns
    b8[fl] = b8[fl].astype("float32")
    b8.to_parquet(PROC / "cover_basin_8day.parquet", compression="zstd", index=False)

    h8 = pd.concat(hrows, ignore_index=True)
    h8["composite_start"] = (pd.to_datetime(h8.date) - pd.Timedelta(days=8)).dt.date
    h8["avail_date"] = (pd.to_datetime(h8.composite_start) + pd.Timedelta(days=16 + ASOF_LATENCY)).dt.date
    shares = ["valid_frac", "living_share", "bare_share", "snow_share", "bare_nonsnow_share", "mean_ndvi"]
    h8.loc[~(h8.tile_cover_frac >= HUC_TILE_MIN), shares] = np.nan   # HUC-12's MODIS tile missing -> unknown, not 0
    h8 = h8[["huc12", "basin", "date", "sensor", "n_px", "n_valid", "valid_frac", "living_share", "bare_share",
             "snow_share", "bare_nonsnow_share", "mean_ndvi", "tile_cover_frac", "composite_start", "avail_date"]
            ].sort_values(["huc12", "date"]).reset_index(drop=True)
    for c in shares + ["tile_cover_frac"]:
        h8[c] = h8[c].astype("float32").round(4)
    h8["n_px"] = h8.n_px.astype("int32")
    h8["n_valid"] = h8.n_valid.astype("int32")
    h8.to_parquet(PROC / "cover_huc12_8day.parquet", compression="zstd", index=False)

    daily = daily_series(b8, date.today())
    fl = daily.select_dtypes("float").columns.drop(["gap_days", "snow_gap_days", "age_days", "snow_age_days"])
    daily[fl] = daily[fl].astype("float32").round(4)
    daily.to_parquet(PROC / "cover_basin_daily.parquet", compression="zstd", index=False)

    yr = yearly(daily, b8)
    yr.round(4).to_parquet(PROC / "modis_basin_year.parquet", compression="zstd", index=False)

    report(b8, daily, h8, yr)
    print(f"done in {time.time() - t0:.0f}s")


def report(b8, daily, h8, yr):
    pd.set_option("display.width", 200, "display.max_columns", 30)
    for f in ["cover_basin_8day", "cover_basin_daily", "cover_huc12_8day", "modis_basin_year"]:
        p = PROC / f"{f}.parquet"
        print(f"{f}.parquet: {len(pd.read_parquet(p))} rows, {p.stat().st_size / 1e6:.2f} MB")
    print(f"8-day dates {b8.date.min()} .. {b8.date.max()}; composites per basin {b8.groupby('basin').size().to_dict()}"
          f"; by source {b8.groupby(['basin', 'gapfill_src']).size().to_dict()}")
    mo = b8[b8.gapfill_src == "modis"]
    off = (pd.to_datetime(mo.obs_date) - pd.to_datetime(mo.composite_start)).dt.total_seconds() / 86400
    print(f"obs_date - composite_start (MODIS): mean {off.mean():.2f} d, range {off.min():.1f}-{off.max():.1f}")
    print("partial-tile composites (basin rows):\n",
          mo[mo.n_tiles < 2][["basin", "date", "sensor", "tile_cover_frac", "valid_frac"]].to_string(index=False))
    hh = b8[b8.gapfill_src == "hls"]
    print("HLS gap-fill composites:\n", hh[["basin", "date", "n_scenes", "valid_frac", "tile_cover_frac", "living_share",
                                           "bare_share", "snow_share"]].round(3).to_string(index=False))
    print("HUC-12 rows with NaN shares (tile missing):", int(h8.living_share.isna().sum() - 0),
          "of which tile_cover_frac < 0.5:", int((h8.tile_cover_frac < HUC_TILE_MIN).sum()))
    a = daily[daily.date >= date(2025, 6, 20)]
    a = a[(pd.to_datetime(a.date).dt.day == 1) | (a.date == a.date.max())]
    print("as-of sample:\n", a[["basin", "date", "bare_share", "gapfill_src", "bare_share_asof", "living_share_asof",
                                "snow_share_asof", "age_days", "asof_stale", "asof_src"]].round(3).to_string(index=False))
    print("as-of stale share by basin:", daily.groupby("basin").asof_stale.mean().round(3).to_dict())
    print("composites with valid_frac < 0.3:", b8[b8.valid_frac < 0.3].groupby("basin").size().to_dict())
    d = b8[b8.gapfill_src == "modis"].copy()
    d["month"] = pd.to_datetime(d.date).dt.month
    good = d[d.valid_frac >= VALID_MIN]
    print("\nMonthly mean over composites with valid_frac >= 0.3 (bare_share | snow_share(all) | valid_frac(all)):")
    t = pd.concat({"bare": good.pivot_table(index="month", columns="basin", values="bare_share"),
                   "snow": d.pivot_table(index="month", columns="basin", values="snow_share"),
                   "valid": d.pivot_table(index="month", columns="basin", values="valid_frac")}, axis=1)
    print(t.round(3).to_string())
    print("\nPer basin-year:")
    print(yr[["basin", "year", "spring_bare_mean", "spring_bare_mean_t25", "spring_bare_mean_t35", "fall_bare_mean",
              "fall_supported_days", "fall_hls_days", "bare_nonsnow_days", "days_majority_bare_nonsnow",
              "winter_living_mean", "nov_living_mean", "nov_n_composites", "nov_n_hls", "apr_living_mean",
              "n_lowvalid_composites"]].round(3).to_string(index=False))
    print("\ndaily filled share:", daily.groupby("basin").filled.mean().round(3).to_dict())


if __name__ == "__main__":
    main()
