"""storms module, step 1: GPM IMERG half-hourly precipitation on sampled storm days vs NASA POWER.

Source: Planetary Computer `gpm-imerg-hhr` (GPM IMERG V06 Final Run, half-hourly, 0.1 deg, variable
`precipitationCal`, mm/hr), Zarr at abfs://imerg/gpm-imerg-hhr.zarr (storage account ai4edataeuwest).
https://planetarycomputer.microsoft.com/dataset/gpm-imerg-hhr

Why a sample, not a series: the collection ends 2021-05-31 and every Zarr chunk is (12 half-hours x whole
globe) ~51 MB blosc-lz4, so one local day costs 4 chunks (~205 MB) whatever the box size. At ~4-6 MB/s a full
daily series 2016-2021 (~2,000 days, ~400 GB) is infeasible. Instead:
  * rank days by NASA POWER basin PRECTOTCORR (max over the two basins; data/processed/power_daily_basin.parquet
    from the hydro module, or a POWER point-API fallback);
  * per year take the TOP_SEASON (default 6) wettest Mar-Oct days plus TOP_WINTER (default 1) wettest
    Nov-Feb day (2021: Jan-May only, season quota scaled to the 3 available months);
  * download in priority order (season rank 1 of every year, rank 2, rank 3, the winter day, ranks 4..6) and
    stop at the budget: <= BUDGET_GB (8) and <= BUDGET_MIN (45) minutes, with the plan trimmed after
    measuring throughput on the first chunks. Dropped days are logged.
  * a local day is 06 UTC d .. 06 UTC d+1 (= POWER's LST day for Iowa, UTC-6), exactly 4 chunks.
Per chunk only the basin box is kept, cached as data/raw/imerg/chunk_<i>.npz, so reruns are free; the sampled
day list is frozen in data/raw/imerg/sampled_days.json (delete it to re-sample).

Outputs
  data/processed/imerg_sample.parquet (basin, date): imerg_mm, imerg_max30_mmhr, imerg_p95_30min,
      wet_frac_12p7, power_mm, sample_class, sample_rank, rationale, n_pix, valid_frac
  data/processed/imerg_vs_power.json: agreement stats and storm-intensity relation (see notes/storms.md)
Re-run: python3 pipeline/p14_imerg.py      (env TOP_SEASON, TOP_WINTER, BUDGET_GB, BUDGET_MIN, WORKERS)
"""
import datetime as dt
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats
from shapely.geometry import box as sbox

sys.path.insert(0, os.path.dirname(__file__))
from common import PROC, RAW, STAC_URL, get  # noqa: E402

IMR = RAW / "imerg"
IMR.mkdir(parents=True, exist_ok=True)
TOP_SEASON = int(os.environ.get("TOP_SEASON", "6"))
TOP_WINTER = int(os.environ.get("TOP_WINTER", "1"))
BUDGET_GB = float(os.environ.get("BUDGET_GB", "8"))
BUDGET_MIN = float(os.environ.get("BUDGET_MIN", "45"))
WORKERS = int(os.environ.get("WORKERS", "6"))
D0, D1 = pd.Timestamp("2016-01-01"), pd.Timestamp("2021-05-31")
T0 = dt.datetime(2000, 6, 1)  # first half-hour of the Zarr; time axis is regular, 368,160 half-hours
NLON, NLAT, NT = 3600, 1800, 12
ZKEY = "imerg/gpm-imerg-hhr.zarr/precipitationCal/{}.0.0"
SEASON = range(3, 11)  # Mar-Oct
WET_MM = 12.7  # 0.5 inch, the RUSLE erosive-storm threshold


# ----------------------------------------------------------------------------- basins and grid
def load_basins():
    d = pd.read_parquet(PROC / "huc12.parquet")
    g = gpd.GeoDataFrame(d, geometry=gpd.GeoSeries.from_wkb(d.geometry), crs=4326)
    return g.dissolve("basin")[["geometry"]]


def grid_box(basins):
    """Index ranges (IMERG lon/lat index) of a 0.1 deg box covering both basins (+1 px pad)."""
    minx, miny, maxx, maxy = basins.total_bounds
    i0 = int(np.floor((minx + 180) / 0.1)) - 1
    i1 = int(np.ceil((maxx + 180) / 0.1)) + 1
    j0 = int(np.floor((miny + 90) / 0.1)) - 1
    j1 = int(np.ceil((maxy + 90) / 0.1)) + 1
    return i0, i1, j0, j1  # python slice ends (exclusive)


def pixel_weights(basins, ib):
    """Fraction of each 0.1 deg pixel (lon x lat) inside each basin, by area in EPSG:5070."""
    i0, i1, j0, j1 = ib
    lons = -179.95 + 0.1 * np.arange(i0, i1)
    lats = -89.95 + 0.1 * np.arange(j0, j1)
    cells = [(a, b, sbox(lo - 0.05, la - 0.05, lo + 0.05, la + 0.05))
             for a, lo in enumerate(lons) for b, la in enumerate(lats)]
    px = gpd.GeoDataFrame({"a": [c[0] for c in cells], "b": [c[1] for c in cells]},
                          geometry=[c[2] for c in cells], crs=4326).to_crs(5070)
    px_area = px.area.values
    out = {}
    for name, geom in basins.to_crs(5070).geometry.items():
        frac = px.intersection(geom).area.values / px_area
        w = np.zeros((len(lons), len(lats)))
        w[px.a.values, px.b.values] = frac
        out[name] = w
    return out, lons, lats


# ----------------------------------------------------------------------------- POWER
def power_basin_daily():
    f = PROC / "power_daily_basin.parquet"
    if f.exists():
        d = pd.read_parquet(f, columns=["basin", "date", "PRECTOTCORR"])
        d["date"] = pd.to_datetime(d.date)
        return d.pivot(index="date", columns="basin", values="PRECTOTCORR"), \
            "data/processed/power_daily_basin.parquet (hydro; area-weighted MERRA-2 cells, LST days)"
    # fallback: POWER daily point API at the centres of the MERRA-2 cells (0.5 x 0.625 deg) intersecting each
    # basin, weighted by intersected area (cached in data/raw/imerg/power/)
    basins = load_basins()
    pdir = IMR / "power"
    pdir.mkdir(exist_ok=True)
    cols = {}
    for name, geom in basins.geometry.items():
        minx, miny, maxx, maxy = geom.bounds
        g5070 = gpd.GeoSeries([geom], crs=4326).to_crs(5070).iloc[0]
        acc, wsum = None, 0.0
        for la in np.arange(np.floor(miny * 2) / 2, maxy + 0.5, 0.5):
            for k in range(int(np.floor((minx + 180) / 0.625)), int(np.ceil((maxx + 180) / 0.625)) + 1):
                lo = -180 + 0.625 * k
                cell = gpd.GeoSeries([sbox(lo - 0.3125, la - 0.25, lo + 0.3125, la + 0.25)], crs=4326).to_crs(5070)
                w = cell.iloc[0].intersection(g5070).area
                if w <= 0:
                    continue
                cf = pdir / f"p{la:.2f}_{lo:.3f}.json"
                if not cf.exists():
                    r = get("https://power.larc.nasa.gov/api/temporal/daily/point",
                            params=dict(parameters="PRECTOTCORR", community="AG", longitude=lo, latitude=la,
                                        start=D0.strftime("%Y%m%d"), end=D1.strftime("%Y%m%d"), format="JSON"))
                    cf.write_text(r.text)
                s = pd.Series(json.loads(cf.read_text())["properties"]["parameter"]["PRECTOTCORR"])
                s.index = pd.to_datetime(s.index, format="%Y%m%d")
                s = s.where(s > -900)
                acc = s * w if acc is None else acc + s * w
                wsum += w
        cols[name] = acc / wsum
    return pd.DataFrame(cols), "POWER daily point API fallback (cell centres, area weights)"


# ----------------------------------------------------------------------------- sampling
def choose_days(pw):
    f = IMR / "sampled_days.json"
    if f.exists():
        return json.loads(f.read_text())
    p = pw.loc[D0:D1].max(axis=1)
    plan = []
    for yr in range(D0.year, D1.year + 1):
        s = p[p.index.year == yr]
        seas = s[s.index.month.isin(SEASON)]
        wint = s[~s.index.month.isin(SEASON)]
        n_months = seas.index.month.nunique()
        k = TOP_SEASON if n_months == 8 else max(1, round(TOP_SEASON * n_months / 8))
        for r, (d, v) in enumerate(seas.sort_values(ascending=False).iloc[:k].items(), 1):
            plan.append(dict(date=d.strftime("%Y-%m-%d"), sample_class="season", sample_rank=r,
                             priority=r if r <= 3 else r + 0.5, power_max_mm=round(float(v), 2),
                             rationale=f"season (Mar-Oct) wettest #{r} of {yr} by POWER basin max"))
        for r, (d, v) in enumerate(wint.sort_values(ascending=False).iloc[:TOP_WINTER].items(), 1):
            plan.append(dict(date=d.strftime("%Y-%m-%d"), sample_class="winter", sample_rank=r,
                             priority=3 + r * 0.5 - 0.25, power_max_mm=round(float(v), 2),
                             rationale=f"winter (Nov-Feb) wettest #{r} of {yr} by POWER basin max"))
    plan.sort(key=lambda x: (x["priority"], x["date"]))
    f.write_text(json.dumps(plan, indent=1))
    return plan


def chunk_ids(day):
    d = dt.datetime.strptime(day, "%Y-%m-%d").replace(hour=6)
    i0 = int((d - T0).total_seconds() // 1800)
    assert i0 % NT == 0
    return [i0 // NT + k for k in range(4)]


# ----------------------------------------------------------------------------- download
class Reader:
    def __init__(self, ib):
        import adlfs
        import numcodecs
        import planetary_computer
        import pystac_client
        c = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
        a = c.get_collection("gpm-imerg-hhr").assets["zarr-abfs"]
        self.fs = adlfs.AzureBlobFileSystem(**a.extra_fields["xarray:storage_options"])
        self.codec = numcodecs.Blosc()
        self.ib = ib
        self.bytes = 0
        self.n = 0
        self.lock = threading.Lock()

    def fetch(self, ci):
        """Download one global chunk, keep the basin box. Returns (ci, bytes_read)."""
        f = IMR / f"chunk_{ci}.npz"
        if f.exists():
            return ci, 0
        i0, i1, j0, j1 = self.ib
        last = None
        for a in range(4):
            try:
                raw = self.fs.cat_file(ZKEY.format(ci))
                arr = np.frombuffer(self.codec.decode(raw), dtype="<f4").reshape(NT, NLON, NLAT)
                p = arr[:, i0:i1, j0:j1].copy()  # (time, lon, lat) mm/hr
                del arr
                np.savez_compressed(f, p=p, ib=np.array(self.ib), ci=ci)
                with self.lock:
                    self.bytes += len(raw)
                    self.n += 1
                return ci, len(raw)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(5 * (a + 1))
        raise RuntimeError(f"chunk {ci}: {last!r}")


def prior_gb():
    """GB already downloaded by earlier runs (the budget is cumulative over runs, not per run)."""
    f = IMR / "run_log.json"
    return sum(r.get("downloaded_gb", 0) for r in json.loads(f.read_text())) if f.exists() else 0.0


def download(plan, ib):
    log = dict(budget_gb=BUDGET_GB, budget_min=BUDGET_MIN, workers=WORKERS, prior_runs_gb=round(prior_gb(), 2))
    todo = [ci for d in plan for ci in chunk_ids(d["date"]) if not (IMR / f"chunk_{ci}.npz").exists()]
    if not todo:
        log.update(downloaded_chunks=0, downloaded_gb=0.0, note="all chunks cached")
        return plan, [], log
    if prior_gb() + 0.06 * min(12, len(todo)) > BUDGET_GB:
        cached = [d for d in plan if all((IMR / f"chunk_{ci}.npz").exists() for ci in chunk_ids(d["date"]))]
        log.update(downloaded_chunks=0, downloaded_gb=0.0, note="cumulative budget spent; using cached days only")
        return cached, [d for d in plan if d not in cached], log
    rd = Reader(ib)
    t0 = time.time()
    # phase 1: first 3 planned days that need downloading -> throughput
    need_days = [d for d in plan if any(not (IMR / f"chunk_{ci}.npz").exists() for ci in chunk_ids(d["date"]))]
    probe = [ci for d in need_days[:3] for ci in chunk_ids(d["date"])]
    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(rd.fetch, probe))
    el = time.time() - t0
    mbps = rd.bytes / 1e6 / max(el, 1e-6)
    per_chunk = rd.bytes / max(1, len(probe))
    print(f"probe: {len(probe)} chunks, {rd.bytes / 1e9:.2f} GB in {el:.0f}s -> {mbps:.1f} MB/s", flush=True)
    # budget in chunks (remaining after probe)
    max_by_gb = (BUDGET_GB * 1e9 - prior_gb() * 1e9 - rd.bytes) / per_chunk
    max_by_time = (BUDGET_MIN * 60 - el) * mbps * 1e6 / per_chunk * 0.95
    allow = int(max(0, min(max_by_gb, max_by_time)))
    kept, dropped, used = [], [], 0
    for d in plan:
        need = [ci for ci in chunk_ids(d["date"]) if not (IMR / f"chunk_{ci}.npz").exists()]
        if used + len(need) <= allow:
            kept.append(d)
            used += len(need)
        else:
            dropped.append(d)
    print(f"budget allows {allow} more chunks; keeping {len(kept)} days, dropping {len(dropped)}", flush=True)
    jobs = [ci for d in kept for ci in chunk_ids(d["date"]) if not (IMR / f"chunk_{ci}.npz").exists()]
    deadline = t0 + BUDGET_MIN * 60
    failed = []
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {}
        for ci in jobs:
            futs[ex.submit(lambda c=ci: rd.fetch(c) if time.time() < deadline else (c, -1))] = ci
        n = 0
        for fu in as_completed(futs):
            n += 1
            try:
                fu.result()
            except Exception as e:  # noqa: BLE001
                failed.append(f"{futs[fu]}: {e}")
            if n % 12 == 0:
                print(f"  {n}/{len(jobs)} chunks, {rd.bytes / 1e9:.2f} GB, {time.time() - t0:.0f}s", flush=True)
    # days whose chunks are incomplete (deadline / failures) also count as dropped
    final_kept = []
    for d in kept:
        if all((IMR / f"chunk_{ci}.npz").exists() for ci in chunk_ids(d["date"])):
            final_kept.append(d)
        else:
            dropped.append(d)
    el = time.time() - t0
    log.update(probe_mb_s=round(mbps, 2), mb_per_chunk=round(per_chunk / 1e6, 1),
               downloaded_chunks=rd.n, downloaded_gb=round(rd.bytes / 1e9, 2),
               elapsed_min=round(el / 60, 1), overall_mb_s=round(rd.bytes / 1e6 / el, 2), failed=failed)
    return final_kept, dropped, log


# ----------------------------------------------------------------------------- metrics
def day_stack(day, ib):
    ps = []
    for ci in chunk_ids(day):
        z = np.load(IMR / f"chunk_{ci}.npz")
        assert tuple(z["ib"]) == tuple(ib), "cached chunk box differs; delete data/raw/imerg/chunk_*.npz"
        ps.append(z["p"])
    p = np.concatenate(ps, axis=0).astype(np.float64)  # (48, lon, lat) mm/hr
    p[p < 0] = np.nan  # -9999.9 missing
    return p


def wquantile(x, w, q):
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = np.cumsum(w) - 0.5 * w
    return float(np.interp(q * w.sum(), c, x))


def basin_metrics(p, w):
    valid = np.isfinite(p).all(axis=0)
    tot = np.nansum(p * 0.5, axis=0)  # mm per local day
    mx = np.nanmax(np.where(np.isfinite(p), p, -np.inf), axis=0)
    m = (w > 0) & valid
    ww = w[m]
    core = (w >= 0.5) & valid  # "basin pixels" for intensity: at least half inside the basin
    return dict(
        imerg_mm=float((tot[m] * ww).sum() / ww.sum()),
        imerg_max30_mmhr=float(mx[core].max()),
        imerg_p95_30min=wquantile(mx[m], ww, 0.95),
        wet_frac_12p7=float(ww[tot[m] > WET_MM].sum() / ww.sum()),
        n_pix=int(core.sum()),
        valid_frac=float((w * valid).sum() / w.sum()),
    )


# ----------------------------------------------------------------------------- analysis
def agreement(x, y):
    """x = IMERG (reference), y = POWER."""
    n = len(x)
    if n < 3:
        return dict(n=n)
    lr = stats.linregress(x, y)
    return dict(
        n=n, pearson_r=round(float(stats.pearsonr(x, y)[0]), 3),
        spearman_rho=round(float(stats.spearmanr(x, y)[0]), 3),
        mean_imerg_mm=round(float(x.mean()), 2), mean_power_mm=round(float(y.mean()), 2),
        bias_mm=round(float((y - x).mean()), 2),
        ratio_power_over_imerg=round(float(y.sum() / x.sum()), 3),
        rmse_mm=round(float(np.sqrt(((y - x) ** 2).mean())), 2),
        mae_mm=round(float((y - x).abs().mean()), 2),
        ols_power_on_imerg=dict(slope=round(float(lr.slope), 3), intercept=round(float(lr.intercept), 2)),
    )


def analysis(df, log, dropped, pw_src):
    out = dict(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        sources=dict(imerg="Planetary Computer gpm-imerg-hhr (GPM IMERG V06 Final, half-hourly 0.1 deg, "
                           "precipitationCal) https://planetarycomputer.microsoft.com/dataset/gpm-imerg-hhr",
                     power=pw_src),
        design=dict(period=f"{D0.date()}..{D1.date()}", local_day="06 UTC d to 06 UTC d+1 (= POWER LST day)",
                    top_season_per_year=TOP_SEASON, top_winter_per_year=TOP_WINTER,
                    ranking="POWER PRECTOTCORR, max of the two basin means",
                    n_days=int(df.date.nunique()), n_rows=len(df),
                    dropped_days=[dict(date=d["date"], why=d["rationale"]) for d in dropped]),
        download=log,
        caveat=("Days are POWER-selected heavy-rain days: correlations are range-restricted (conditional on POWER "
                "being wet) and say nothing about days POWER calls dry. IMERG 0.1 deg half-hour areal rates damp "
                "point peaks."),
    )
    ag = {"pooled": agreement(df.imerg_mm, df.power_mm)}
    for b, g in df.groupby("basin"):
        ag[b] = agreement(g.imerg_mm, g.power_mm)
    for c, g in df.groupby("sample_class"):
        ag[f"class_{c}"] = agreement(g.imerg_mm, g.power_mm)
    out["power_vs_imerg_daily_mm"] = ag
    # storm detection: POWER heavy (>=12.7 basin mean) vs IMERG heavy
    ph, ih = df.power_mm >= WET_MM, df.imerg_mm >= WET_MM
    out["heavy_day_agreement_12p7mm"] = dict(
        both=int((ph & ih).sum()), power_only=int((ph & ~ih).sum()), imerg_only=int((~ph & ih).sum()),
        neither=int((~ph & ~ih).sum()))
    # rank agreement inside each year/basin: is POWER's wettest sampled day also IMERG's?
    hits = []
    for (b, y), g in df.assign(year=pd.to_datetime(df.date).dt.year).groupby(["basin", "year"]):
        if len(g) >= 3:
            hits.append(g.power_mm.idxmax() == g.imerg_mm.idxmax())
    out["same_wettest_day_per_basin_year"] = dict(n=len(hits), share=round(float(np.mean(hits)), 3) if hits else None)
    # storm intensity vs daily total: log(max30) = a + b log(total), also p95 and wet fraction
    rel = {}
    s = df[df.imerg_mm >= 1.0]
    for col in ("imerg_max30_mmhr", "imerg_p95_30min"):
        for xcol in ("imerg_mm", "power_mm"):
            ss = s[(s[col] > 0) & (s[xcol] > 0)]
            lr = stats.linregress(np.log(ss[xcol]), np.log(ss[col]))
            rel[f"{col}_vs_{xcol}"] = dict(
                form=f"{col} = a * {xcol}^b", a=round(float(np.exp(lr.intercept)), 3), b=round(float(lr.slope), 3),
                r_log=round(float(lr.rvalue), 3), n=len(ss),
                resid_sd_log=round(float(np.std(np.log(ss[col]) - lr.intercept - lr.slope * np.log(ss[xcol]),
                                                ddof=2)), 3))
    for xcol in ("imerg_mm", "power_mm"):
        lr = stats.linregress(s[xcol], s.wet_frac_12p7)
        rel[f"wet_frac_12p7_vs_{xcol}"] = dict(form=f"wet_frac = a + b * {xcol}", a=round(float(lr.intercept), 3),
                                              b=round(float(lr.slope), 4), r=round(float(lr.rvalue), 3), n=len(s))
    out["intensity_relations"] = rel
    out["by_season_class"] = {c: dict(n=len(g), mean_max30=round(float(g.imerg_max30_mmhr.mean()), 1),
                                      mean_imerg_mm=round(float(g.imerg_mm.mean()), 1))
                              for c, g in df.groupby("sample_class")}
    pc = ag["pooled"]
    out["verdict"] = (f"On {pc['n']} sampled basin-days POWER PRECTOTCORR vs IMERG basin totals: r={pc['pearson_r']}, "
                      f"rho={pc['spearman_rho']}, bias {pc['bias_mm']:+} mm/day (POWER/IMERG volume ratio "
                      f"{pc['ratio_power_over_imerg']}). POWER captures which days are heavy at basin scale; use it "
                      f"as the continuous rainfall driver for 2022-2026, with storm intensity as a function of daily "
                      f"total (relations above) rather than a separate observed driver.")
    return out


def main():
    t_start = time.time()
    basins = load_basins()
    ib = grid_box(basins)
    weights, lons, lats = pixel_weights(basins, ib)
    print(f"IMERG box: lon {lons[0]:.2f}..{lons[-1]:.2f}, lat {lats[0]:.2f}..{lats[-1]:.2f} "
          f"({len(lons)}x{len(lats)} px); pixels >=50% in basin: "
          + ", ".join(f"{b}={int((w >= 0.5).sum())}" for b, w in weights.items()), flush=True)
    pw, pw_src = power_basin_daily()
    print("POWER source:", pw_src, flush=True)
    plan = choose_days(pw)
    print(f"planned days: {len(plan)} ({sum(d['sample_class'] == 'season' for d in plan)} season, "
          f"{sum(d['sample_class'] == 'winter' for d in plan)} winter), {4 * len(plan)} chunks", flush=True)
    kept, dropped, log = download(plan, ib)
    if dropped:
        print("dropped (budget):", [d["date"] for d in dropped], flush=True)
    logf = IMR / "run_log.json"
    prev = json.loads(logf.read_text()) if logf.exists() else []
    prev.append(dict(run=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **log,
                     kept=len(kept), dropped=[d["date"] for d in dropped]))
    logf.write_text(json.dumps(prev, indent=1))
    # cumulative download cost over all runs (what the budget applies to)
    log = dict(log, cumulative=dict(
        runs_with_downloads=sum(r.get("downloaded_gb", 0) > 0 for r in prev),
        downloaded_gb=round(sum(r.get("downloaded_gb", 0) for r in prev), 2),
        elapsed_min=round(sum(r.get("elapsed_min", 0) for r in prev), 1),
        cached_chunks=len(list(IMR.glob("chunk_*.npz")))))
    rows = []
    for d in sorted(kept, key=lambda x: x["date"]):
        p = day_stack(d["date"], ib)
        for b, w in weights.items():
            m = basin_metrics(p, w)
            rows.append(dict(basin=b, date=pd.Timestamp(d["date"]).date(), **m,
                             power_mm=float(pw.loc[pd.Timestamp(d["date"]), b]),
                             sample_class=d["sample_class"], sample_rank=d["sample_rank"], rationale=d["rationale"]))
    df = pd.DataFrame(rows)
    for c in ("imerg_mm", "imerg_max30_mmhr", "imerg_p95_30min", "power_mm"):
        df[c] = df[c].round(3).astype("float32")
    df["wet_frac_12p7"] = df.wet_frac_12p7.round(4).astype("float32")
    df["valid_frac"] = df.valid_frac.round(4).astype("float32")
    df.to_parquet(PROC / "imerg_sample.parquet", index=False, compression="zstd")
    res = analysis(df, log, dropped, pw_src)
    (PROC / "imerg_vs_power.json").write_text(json.dumps(res, indent=1))
    # report
    print(f"\nimerg_sample.parquet: {len(df)} rows, {df.date.nunique()} days, {df.basin.nunique()} basins")
    print(df.groupby("basin")[["imerg_mm", "power_mm", "imerg_max30_mmhr", "imerg_p95_30min",
                               "wet_frac_12p7"]].mean().round(2).to_string())
    print("valid_frac min:", float(df.valid_frac.min()))
    for k, v in res["power_vs_imerg_daily_mm"].items():
        print(f"  {k}: {v}")
    print("heavy-day table:", res["heavy_day_agreement_12p7mm"])
    for k, v in res["intensity_relations"].items():
        print(f"  {k}: {v}")
    print(f"done in {(time.time() - t_start) / 60:.1f} min")


if __name__ == "__main__":
    main()
