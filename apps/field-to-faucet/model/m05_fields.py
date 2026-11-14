#!/usr/bin/env python3
"""m05_fields.py: field leak score, HUC-12 hotspot index, river calibration (Field to Faucet).

Re-runnable end to end:  python3 model/m05_fields.py   (about 1-2 min, no network)
Then run                  python3 model/m06_strategies.py

Idea (details and justification in notes/fields_model.md):
  leak(day) = cover(day) x drainage(day) x soil
    drainage = (liquid rain + snowmelt) x f(GWETROOT of the day before)   [NASA POWER]
               f rises linearly from 0 at w0 to 1 at w0+dw. w0, dw (and a routing constant only used for
               the fit) are fitted to MEASURED monthly runoff (USGS flow) of both basins.
    cover    = bare + eps x (1 - bare); bare from NASA HLS per field, from MODIS (corrected to HLS by
               month) per HUC-12. eps = 1 - INRS land-retirement reduction (facts.json, inrs_crp_pct):
               land under living cover leaks that fraction of bare land.
    soil     = 1 + (m - 1) x poorly-drained share. Poorly drained Iowa row-crop land is tile drained;
               m = delivery multiplier of tiled vs. naturally drained land, uncertain, U[1, 4]
               (upper end from McIsaac & Hu 2004 via David et al. 2010), central 2.5.
    crop     = 1 for corn and soybean years (facts.json isu_lbN_acre_yr note: losses are similar).
  Calibration: per basin and calendar year the HUC-12 index x row-crop area is scaled so the basin sum
  equals s x measured annual nitrate-N load at the gauge (gap-filled), s = share of the river load that
  comes from row-crop land, uncertain U[s_lo, s_hi] (facts.json + CDL, see below).
  Fields are scaled inside their HUC-12 so that the field mean equals the HUC-12 per-hectare value.

Inputs: data/processed/{power_daily_cells, power_cells, huc12_cell, huc12, soils_huc12, cdl_huc12_year,
  cdl_basin_year, cover_huc12_8day, nwis_daily, fields, field_year, hls_field_ts}.parquet,
  data/processed/hls_vs_modis.json, docs/facts.json
Outputs (model/out/): field_scores.parquet, huc12_scores.parquet, basin_index_check.json,
  fields.geojson, huc12_props.json   (field_detail.json and strategies.json are written by m06)
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import lfilter

APP = Path(__file__).resolve().parents[1]
PROC = APP / "data" / "processed"
OUT = APP / "model" / "out"
FACTS = APP / "docs" / "facts.json"

SITES = {"raccoon": "05484500", "desmoines": "05482000"}
CAL_YEARS = list(range(2016, 2026))        # calendar years with complete NWIS + MODIS + POWER
FIELD_YEARS = list(range(2020, 2026))      # calendar years with HLS (PC HLS starts 2020-01)
RECENT_YEARS = [2023, 2024, 2025]          # "latest 3 years" for bare_days_wet / recent shares
KG_HA_TO_LB_AC = 2.20462262 / 2.47105381   # 1 kg/ha = 0.8922 lb/acre
CFS_MGL_TO_KG_DAY = 2.4466
STORM_MM = 25.0                            # "big-storm day" (contract)
WET_DAY_MM = 1.0                           # a day counts as "wet" for bare_days_wet when drainage >= 1 mm
M_GRID = np.array([1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0])   # tile-delivery multiplier grid
M_C = 3                                    # index of central m = 2.5
HLS_MAX_GAP = 120                          # days; same as the fields module
MODIS_LONG_GAP = 60                        # days; longer gaps -> day-of-year climatology (as model/featlib.py)
N_DRAWS = 4000
N_Q = 200                                  # stored quantile function per field (for m06 Monte Carlo)
SEED = 20261114


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------------------- facts
def load_facts() -> dict:
    d = json.loads(FACTS.read_text())
    return {f["id"]: f for f in d["facts"]}


def fact_value(facts: dict, fid: str, allow_unverified: bool = False):
    f = facts.get(fid)
    if f is None:
        return None
    if f.get("verification") == "unverified" and not allow_unverified:
        return None
    return f


# ----------------------------------------------------------------------------- 1. drainage driver
def snow_split(g: pd.DataFrame):
    """Liquid water reaching the soil (rain + snowmelt), mm/day, for one POWER cell (date-sorted).

    Snowfall (PRECSNOLAND, mm water) fills a snow-water store; the store releases water in proportion to the
    day's relative loss of snow depth (SNODP), all of it when depth reaches 0. This avoids assuming a snow
    density. PRECSNOLAND is missing from 2026-10-01 (BLOCKERS.md): there precipitation counts as snow when
    T2M <= 0 degC.
    """
    p = g["PRECTOTCORR"].to_numpy(float)
    snow = g["PRECSNOLAND"].to_numpy(float)
    miss = ~np.isfinite(snow)
    snow[miss] = np.where(g["T2M"].to_numpy(float)[miss] <= 0, p[miss], 0.0)
    snow = np.minimum(snow, p)
    liquid = np.clip(p - snow, 0, None)
    sd = g["SNODP"].fillna(0).to_numpy(float)
    melt = np.zeros_like(p)
    swe = 0.0
    for i in range(len(p)):
        swe += snow[i]
        prev = sd[i - 1] if i > 0 else 0.0
        if sd[i] <= 0:
            frac = 1.0
        elif prev > 0:
            frac = max(0.0, (prev - sd[i]) / prev)
        else:
            frac = 0.0
        m = swe * frac
        melt[i] = m
        swe -= m
    return liquid, melt


def ramp(w, w0, dw):
    return np.clip((w - w0) / dw, 0.0, 1.0)


def build_drainage(pc: pd.DataFrame, cells: pd.DataFrame, nw: pd.DataFrame, basin_area_km2: dict):
    pc = pc.sort_values(["cell_id", "date"])
    dates = pd.DatetimeIndex(sorted(pc["date"].unique()))
    cell_ids = list(cells["cell_id"])
    inp, wprev, rain = [], [], []
    for cid in cell_ids:
        g = pc[pc["cell_id"] == cid].set_index("date").reindex(dates)
        liq, melt = snow_split(g.reset_index())
        inp.append(liq + melt)
        w = g["GWETROOT"].astype(float).shift(1).bfill().to_numpy()   # soil state before the day's rain
        wprev.append(w)
        rain.append(g["PRECTOTCORR"].to_numpy(float))
    INP, WP, RAIN = np.array(inp), np.array(wprev), np.array(rain)  # [cell, day]
    GW = np.array([pc[pc["cell_id"] == c].set_index("date").reindex(dates)["GWETROOT"].to_numpy(float) for c in cell_ids])

    # --- fit w0, dw (and routing k) to measured monthly runoff, both basins, 2016-2025
    wts = {b: cells[f"w_{b}"].to_numpy(float) / cells[f"w_{b}"].sum() for b in SITES}
    ro = {}
    for b, site in SITES.items():
        q = nw[nw["site"] == site].set_index("date")["q_cfs"].reindex(dates).interpolate(limit=5)
        ro[b] = q.to_numpy() * 0.0283168 * 86400 / (basin_area_km2[b] * 1e6) * 1000.0   # mm/day
    sel = (dates >= "2016-01-01") & (dates <= "2025-12-31")
    month = dates.to_period("M")[sel]
    year = dates.year[sel]
    inp_b = {b: wts[b] @ INP for b in SITES}

    def score(w0, dw, k):
        out = []
        for b in SITES:
            D = wts[b] @ (INP * ramp(WP, w0, dw))
            Dr = lfilter([1.0 / k], [1.0, -(1.0 - 1.0 / k)], D)
            dfm = pd.DataFrame({"D": Dr[sel], "ro": ro[b][sel], "m": month}).groupby("m").sum(min_count=20).dropna()
            dfa = pd.DataFrame({"D": D[sel], "ro": ro[b][sel], "y": year}).groupby("y").sum()
            out.append((np.corrcoef(dfm.D, dfm.ro)[0, 1], np.corrcoef(dfa.D, dfa.ro)[0, 1]))
        return np.array(out)

    best = None
    grid = []
    for w0 in np.round(np.arange(0.30, 0.611, 0.01), 2):
        for dw in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40]:
            for k in [5, 10, 20, 40]:
                sc = score(w0, dw, k)
                grid.append((w0, dw, k, sc[:, 0].mean()))
                if best is None or sc[:, 0].mean() > best[3]:
                    best = (w0, dw, k, sc[:, 0].mean(), sc)
    w0, dw, k = best[0], best[1], best[2]
    sc = best[4]
    # baseline: the same with f = 1 (all rain + melt counts)
    base = []
    for b in SITES:
        Dr = lfilter([1.0 / k], [1.0, -(1.0 - 1.0 / k)], inp_b[b])
        dfm = pd.DataFrame({"D": Dr[sel], "ro": ro[b][sel], "m": month}).groupby("m").sum(min_count=20).dropna()
        dfa = pd.DataFrame({"D": inp_b[b][sel], "ro": ro[b][sel], "y": year}).groupby("y").sum()
        base.append((np.corrcoef(dfm.D, dfm.ro)[0, 1], np.corrcoef(dfa.D, dfa.ro)[0, 1]))
    DR = INP * ramp(WP, w0, dw)   # mm/day of drainage-driving water per cell and day
    fit = {
        "form": "D = (liquid rain + snowmelt) * clip((GWETROOT_prev - w0)/dw, 0, 1)",
        "w0": float(w0), "dw": float(dw), "routing_k_days_fit_only": int(k),
        "fit_target": "monthly runoff (USGS daily flow / basin area), 2016-2025, both basins; objective = mean Pearson r",
        "r_monthly": {b: round(float(sc[i, 0]), 3) for i, b in enumerate(SITES)},
        "r_annual": {b: round(float(sc[i, 1]), 3) for i, b in enumerate(SITES)},
        "baseline_f1_r_monthly": {b: round(float(base[i][0]), 3) for i, b in enumerate(SITES)},
        "baseline_f1_r_annual": {b: round(float(base[i][1]), 3) for i, b in enumerate(SITES)},
        "n_grid": len(grid),
    }
    return dates, cell_ids, DR, RAIN, GW, fit, ro


# ----------------------------------------------------------------------------- 2. measured annual loads
def _design(dates: pd.DatetimeIndex, lnq: np.ndarray, years: list[int]):
    doy = dates.dayofyear.to_numpy() / 365.25 * 2 * np.pi
    cols = [np.ones(len(dates)), lnq, lnq ** 2, np.sin(doy), np.cos(doy), np.sin(2 * doy), np.cos(2 * doy)]
    for y in years[1:]:
        cols.append((dates.year == y).astype(float))
    return np.column_stack(cols)


def fill_concentration(dates, c, q, obs):
    """Log-concentration regression on log-flow, season and calendar-year level, fitted on observed days,
    plus linear-in-time interpolation of the residuals between observed days (so short gaps behave like
    concentration interpolation and long gaps borrow the flow and season signal)."""
    lnq = np.log(np.clip(q, 1.0, None))
    years = sorted(set(dates.year))
    X = _design(dates, lnq, years)
    lnc = np.log(np.clip(c, 0.05, None))
    beta, *_ = np.linalg.lstsq(X[obs], lnc[obs], rcond=None)
    pred = X @ beta
    t = np.arange(len(dates))
    res = np.interp(t, t[obs], (lnc - pred)[obs])
    return np.exp(pred + res)


def annual_loads(nw: pd.DataFrame, rng):
    out, cv_out = [], {}
    for b, site in SITES.items():
        g = nw[nw["site"] == site].sort_values("date").set_index("date")
        dates = pd.DatetimeIndex(g.index)
        q = g["q_cfs"].interpolate(limit_direction="both").to_numpy(float)
        c = g["no3_mgL"].to_numpy(float)
        obs = np.isfinite(c)
        cf = fill_concentration(dates, c, q, obs)
        load = np.where(obs, c, cf) * q * CFS_MGL_TO_KG_DAY
        # --- cross-validation of the gap filler: hide blocks of observed days, refill, compare block loads
        rel_sd = {}
        t_obs = np.where(obs)[0]
        for L in [3, 7, 15, 30, 60, 90]:
            errs = []
            tries = 0
            while len(errs) < 120 and tries < 5000:
                tries += 1
                s0 = rng.integers(30, len(c) - L - 30)
                if not obs[s0:s0 + L].all():
                    continue
                o2 = obs.copy()
                o2[s0:s0 + L] = False
                c2 = fill_concentration(dates, c, q, o2)
                true = (c[s0:s0 + L] * q[s0:s0 + L]).sum()
                est = (c2[s0:s0 + L] * q[s0:s0 + L]).sum()
                errs.append((est, true))
            e = np.array(errs)
            # load-normalised: RMSE of block loads / mean block load (robust to near-zero-nitrate blocks)
            rel_sd[L] = (float(np.sqrt(np.mean((e[:, 0] - e[:, 1]) ** 2)) / e[:, 1].mean()),
                         float((e[:, 0] - e[:, 1]).mean() / e[:, 1].mean()), len(e))
        cv_out[b] = {str(L): {"rmse_rel": round(v[0], 3), "bias_rel": round(v[1], 3), "n": v[2]} for L, v in rel_sd.items()}
        Ls = np.array(sorted(rel_sd))
        Rs = np.array([rel_sd[L][0] for L in Ls])
        # gaps (runs of missing days)
        miss = ~obs
        runs = []
        i = 0
        while i < len(miss):
            if miss[i]:
                j = i
                while j < len(miss) and miss[j]:
                    j += 1
                runs.append((i, j))
                i = j
            else:
                i += 1
        for y in CAL_YEARS:
            m = dates.year == y
            var = 0.0
            for (i0, i1) in runs:
                idx = np.arange(i0, i1)
                idx = idx[dates.year[idx] == y]
                if len(idx) == 0:
                    continue
                rs = np.interp(i1 - i0, Ls, Rs)          # error depends on the whole gap length
                var += (rs * load[idx].sum()) ** 2
            tot = load[m].sum()
            out.append({
                "basin": b, "site": site, "year": y,
                "load_kgN": tot, "load_obs_days_kgN": load[m & obs].sum(),
                "days": int(m.sum()), "days_missing_no3": int((m & miss).sum()),
                "filled_share": float(load[m & miss].sum() / tot),
                "load_sd_rel": float(np.sqrt(var) / tot),
                "q_mean_cfs": float(q[m].mean()),
                "fwm_no3_mgL": float(load[m].sum() / (q[m].sum() * CFS_MGL_TO_KG_DAY)),
            })
    return pd.DataFrame(out), cv_out


# ----------------------------------------------------------------------------- 3. MODIS daily bare per HUC-12
def modis_bias_by_doy(hvm: dict) -> np.ndarray:
    """MODIS minus HLS living share by month (focus area, hls_vs_modis.json), interpolated to day of year
    (anchored mid-month, periodic). Subtracting it puts MODIS on the HLS scale (MODIS max-value composites
    and 250 m mixed pixels read greener, mostly Apr-May)."""
    mm = hvm["monthly_mean_living_share"]
    b = np.array([mm[str(m)]["modis"] - mm[str(m)]["hls"] for m in range(1, 13)])
    mid = np.array([15, 45, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349], float)
    x = np.concatenate([mid - 365, mid, mid + 365])
    return np.interp(np.arange(1, 367), x, np.tile(b, 3)), b


def modis_daily(cov: pd.DataFrame, dates: pd.DatetimeIndex, bias_doy: np.ndarray, huc_list: list[str], basin_of: dict):
    cov = cov[cov["valid_frac"] >= 0.30].copy()
    cov["date"] = pd.to_datetime(cov["date"])
    cov["living_c"] = np.clip(cov["living_share"] - bias_doy[cov["date"].dt.dayofyear.to_numpy() - 1], 0, 1)
    t = (dates - dates[0]).days.to_numpy()
    doy = dates.dayofyear.to_numpy()
    B = np.full((len(huc_list), len(dates)), np.nan)
    filled = np.zeros_like(B, dtype=bool)
    for i, h in enumerate(huc_list):
        g = cov[cov["huc12"] == h].sort_values("date")
        if len(g) < 20:
            continue
        tt = (g["date"] - dates[0]).dt.days.to_numpy()
        v = g["living_c"].to_numpy()
        liv = np.interp(t, tt, v, left=np.nan, right=np.nan)
        k = np.searchsorted(tt, t)
        k0, k1 = np.clip(k - 1, 0, len(tt) - 1), np.clip(k, 0, len(tt) - 1)
        gap = tt[k1] - tt[k0]
        exact = np.isin(t, tt)
        long_gap = (gap > MODIS_LONG_GAP) & ~exact
        ok = np.isfinite(liv) & ~long_gap
        # day-of-year climatology from trusted days (15-day circular smoothing)
        clim = np.full(366, np.nan)
        dd = pd.Series(liv[ok]).groupby(doy[ok]).mean()
        clim[dd.index.to_numpy() - 1] = dd.to_numpy()
        cs = pd.Series(np.concatenate([clim[-15:], clim, clim[:15]])).rolling(15, center=True, min_periods=3).mean().to_numpy()[15:-15]
        bad = ~ok
        liv[bad] = cs[doy[bad] - 1]
        filled[i] = bad
        B[i] = 1.0 - liv
    # HUC-12s without MODIS pixels: basin mean
    for b in set(basin_of.values()):
        idx = [i for i, h in enumerate(huc_list) if basin_of[h] == b]
        mean_b = np.nanmean(B[idx], axis=0)
        for i in idx:
            if np.isnan(B[i]).all():
                B[i] = mean_b
                filled[i] = True
    return np.clip(B, 0, 1), filled


# ----------------------------------------------------------------------------- 4. HLS daily bare per field
def hls_spike_scenes(h: pd.DataFrame) -> list:
    """Scene QA (generic): spring scenes whose field-median living share jumps implausibly. Flags a date when
    (a) its median live_px_share exceeds both neighbouring scenes by > 0.25, or (b) before DOY 141 (May 20,
    when HLS median crop green-up is DOY ~150) it is > 0.25 and > 0.20 above the previous scene."""
    s = h.groupby("date").agg(med=("live_px_share", "median"), n=("live_px_share", "size")).reset_index()
    s["date"] = pd.to_datetime(s["date"])
    s = s[s["n"] >= 200].sort_values("date").reset_index(drop=True)
    prev, nxt = s["med"].shift(1), s["med"].shift(-1)
    doy = s["date"].dt.dayofyear
    spring = s["date"].dt.month.isin([3, 4, 5, 6])
    a = spring & (s["med"] - np.maximum(prev, nxt) > 0.25)
    b = (doy < 141) & spring & (s["med"] > 0.25) & (s["med"] - prev > 0.20)
    return sorted(s.loc[a | b, "date"].dt.strftime("%Y-%m-%d").tolist())


def hls_daily(h: pd.DataFrame, fids: list[str], dates: pd.DatetimeIndex):
    t = (dates - dates[0]).days.to_numpy()
    B = np.full((len(fids), len(dates)), np.nan)
    h = h.sort_values(["field_id", "date"])
    grp = dict(tuple(h.groupby("field_id", observed=True)))
    for i, f in enumerate(fids):
        g = grp.get(f)
        if g is None or len(g) < 2:
            continue
        tt = (pd.to_datetime(g["date"]) - dates[0]).dt.days.to_numpy()
        v = g["live_px_share"].to_numpy(float)
        liv = np.interp(t, tt, v, left=np.nan, right=np.nan)
        k = np.searchsorted(tt, t)
        k0, k1 = np.clip(k - 1, 0, len(tt) - 1), np.clip(k, 0, len(tt) - 1)
        gap = tt[k1] - tt[k0]
        liv[(gap > HLS_MAX_GAP) & ~np.isin(t, tt)] = np.nan
        B[i] = 1.0 - liv
    return B


# ----------------------------------------------------------------------------- helpers
def corr(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    return {"pearson": round(float(stats.pearsonr(x, y)[0]), 3), "pearson_p": float(f"{stats.pearsonr(x, y)[1]:.3g}"),
            "spearman": round(float(stats.spearmanr(x, y)[0]), 3), "spearman_p": float(f"{stats.spearmanr(x, y)[1]:.3g}"), "n": int(len(x))}


def r3(x):
    return float(f"{x:.3g}") if np.isfinite(x) else None


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    facts = load_facts()

    # ---------------- inputs
    pc = pd.read_parquet(PROC / "power_daily_cells.parquet")
    pc["date"] = pd.to_datetime(pc["date"])
    cells = pd.read_parquet(PROC / "power_cells.parquet")
    hc = pd.read_parquet(PROC / "huc12_cell.parquet")
    huc = pd.read_parquet(PROC / "huc12.parquet").drop(columns=["geometry"])
    soils = pd.read_parquet(PROC / "soils_huc12.parquet")
    cdlh = pd.read_parquet(PROC / "cdl_huc12_year.parquet")
    cdlb = pd.read_parquet(PROC / "cdl_basin_year.parquet")
    nw = pd.read_parquet(PROC / "nwis_daily.parquet")
    nw["date"] = pd.to_datetime(nw["date"])
    hvm = json.loads((PROC / "hls_vs_modis.json").read_text())
    basin_area = huc.groupby("basin")["area_km2"].sum().to_dict()

    # ---------------- 1. drainage
    log("drainage driver: fitting wet-soil ramp to measured runoff")
    dates, cell_ids, DR, RAIN, GW, dfit, ro = build_drainage(pc, cells, nw, basin_area)
    cidx = {c: i for i, c in enumerate(cell_ids)}
    log("  fit:", {k: dfit[k] for k in ("w0", "dw", "routing_k_days_fit_only", "r_monthly", "baseline_f1_r_monthly")})

    # ---------------- living-cover leak fraction eps (facts)
    crp = fact_value(facts, "inrs_crp_pct")
    eps = 1.0 - float(crp["value"]) / 100.0 if crp else 0.15
    eps_src = f"1 - inrs_crp_pct ({crp['value']}%, {crp['url']})" if crp else "fallback 0.15 (inrs_crp_pct missing)"

    # ---------------- 2. loads
    log("measured annual loads with gap filling (+ cross-validation)")
    loads, cv = annual_loads(nw, rng)

    # ---------------- share of load from row-crop land, s ~ U[s_lo, s_hi]
    ag = fact_value(facts, "ag_share_river_nitrate_pct")
    s_lo = float(ag["range"]["lo"]) / 100.0 if ag and ag.get("range") else 0.70
    m_city = re.search(r"cities\s*([\d.]+)\s*-\s*([\d.]+)\s*%", (ag or {}).get("notes", "") or "")
    point = float(m_city.group(2)) / 100.0 if m_city else 0.0
    s_hi_b = {}
    for b in SITES:
        cb = cdlb[(cdlb["basin"] == b) & cdlb["year"].isin(CAL_YEARS)].mean(numeric_only=True)
        nonrc_land = cb["small_grain"] + cb["hay"] + cb["grass_pasture"] + cb["forest"] + cb["other"]
        rc = cb["row_crop"]
        s_hi_b[b] = (rc / (rc + nonrc_land * eps)) * (1.0 - point)
    s_hi = float(min(s_hi_b.values()))
    s_c = 0.5 * (s_lo + s_hi)
    share_note = (f"s ~ U[{s_lo:.3f}, {s_hi:.3f}]: lower = CISWRA agriculture share lo ({ag['url'] if ag else 'n/a'}); "
                  f"upper = row-crop share of land-based load if non-row-crop land (grass, hay, small grain, forest, other; CDL) "
                  f"leaks eps={eps:.2f} of row-crop land per ha, minus point sources {point:.1%} (cities, facts note on ag_share_river_nitrate_pct). "
                  f"Per-basin upper: {', '.join(f'{k} {v:.3f}' for k, v in s_hi_b.items())}; the smaller one is used for both.")
    log("  row-crop share of river load:", share_note)

    # ---------------- 3. HUC-12 index
    log("HUC-12 index: MODIS bare (HLS-corrected) x drainage x soil")
    huc_list = sorted(huc["huc12"])
    hidx = {h: i for i, h in enumerate(huc_list)}
    basin_of = dict(zip(huc["huc12"], huc["basin"]))
    Wm = np.zeros((len(huc_list), len(cell_ids)))
    for r in hc.itertuples():
        Wm[hidx[r.huc12], cidx[r.cell_id]] += r.weight
    Wm /= Wm.sum(axis=1, keepdims=True)
    DH = Wm @ DR                                   # drainage per HUC-12-day
    RH = Wm @ RAIN
    bias_doy, bias_month = modis_bias_by_doy(hvm)
    cov = pd.read_parquet(PROC / "cover_huc12_8day.parquet")
    BH, BHfilled = modis_daily(cov, dates, bias_doy, huc_list, basin_of)
    JH = (BH + eps * (1 - BH)) * DH                # cover x drainage (mm-equivalent), per row-crop ha-day
    yr = dates.year.to_numpy()
    mo = dates.month.to_numpy()
    JHy = np.array([JH[:, yr == y].sum(axis=1) for y in CAL_YEARS]).T            # [huc, year]
    DHy = np.array([DH[:, yr == y].sum(axis=1) for y in CAL_YEARS]).T
    RHy = np.array([RH[:, yr == y].sum(axis=1) for y in CAL_YEARS]).T
    soil = soils.set_index("huc12").reindex(huc_list)
    pdh = soil["poorly_drained_share"].fillna(soil["poorly_drained_share"].median()).to_numpy(float)
    SOILH = 1.0 + (M_GRID[:, None] - 1.0) * pdh[None, :]                          # [m, huc]
    rc = cdlh.pivot(index="huc12", columns="year", values="row_crop").reindex(huc_list)[CAL_YEARS].to_numpy(float)
    area_h = huc.set_index("huc12").reindex(huc_list)["area_km2"].to_numpy(float)
    AH = rc * area_h[:, None] * 100.0                                             # row-crop ha [huc, year]
    bas = np.array([basin_of[h] for h in huc_list])

    # calibration per m, basin, year:  kg/ha = k * soil * J
    L = loads.set_index(["basin", "year"])
    HUCKG = np.zeros((len(M_GRID), len(huc_list), len(CAL_YEARS)))
    for mi in range(len(M_GRID)):
        I = SOILH[mi][:, None] * JHy
        for b in SITES:
            sel = bas == b
            for yi, y in enumerate(CAL_YEARS):
                k = s_c * L.loc[(b, y), "load_kgN"] / (I[sel, yi] * AH[sel, yi]).sum()
                HUCKG[mi, sel, yi] = k * I[sel, yi]
    # basin calibration numbers
    calib = []
    for b in SITES:
        sel = bas == b
        for yi, y in enumerate(CAL_YEARS):
            a_rc = AH[sel, yi].sum()
            ld = L.loc[(b, y)]
            calib.append({
                "basin": b, "year": y, "load_t": round(ld["load_kgN"] / 1000, 1),
                "load_sd_rel": round(ld["load_sd_rel"], 3), "filled_share": round(ld["filled_share"], 3),
                "rowcrop_km2": round(a_rc / 100, 1),
                "kgN_ha_rowcrop_all_sources": round(ld["load_kgN"] / a_rc, 2),
                "kgN_ha_rowcrop_from_rowcrop": {"central": round(s_c * ld["load_kgN"] / a_rc, 2),
                                                "lo": round(s_lo * ld["load_kgN"] / a_rc, 2), "hi": round(s_hi * ld["load_kgN"] / a_rc, 2)},
                "lbN_ac_rowcrop_from_rowcrop": {"central": round(s_c * ld["load_kgN"] / a_rc * KG_HA_TO_LB_AC, 2),
                                                "lo": round(s_lo * ld["load_kgN"] / a_rc * KG_HA_TO_LB_AC, 2), "hi": round(s_hi * ld["load_kgN"] / a_rc * KG_HA_TO_LB_AC, 2)},
                "fwm_no3_mgL": round(ld["fwm_no3_mgL"], 2), "q_mean_cfs": round(ld["q_mean_cfs"], 0),
            })

    # ---------------- validation: does the UNcalibrated index track measured loads?
    log("validation check")
    rows = []
    sites_area = {}
    for b in SITES:
        sel = bas == b
        for yi, y in enumerate(CAL_YEARS):
            a = AH[sel, yi]
            I = SOILH[M_C, sel] * JHy[sel, yi]
            rows.append({
                "basin": b, "year": y,
                "index_per_ha": (I * a).sum() / a.sum(),
                "drain_only_per_ha": (SOILH[M_C, sel] * DHy[sel, yi] * a).sum() / a.sum(),
                "rain_per_ha": (RHy[sel, yi] * a).sum() / a.sum(),
                "load_kg_ha": L.loc[(b, y), "load_kgN"] / a.sum(),
                "runoff_mm": float(np.nansum(ro[b][yr == y])),
            })
        sites_area[b] = AH[sel].sum(axis=0)
    V = pd.DataFrame(rows)
    chk = {
        "question": "Does the uncalibrated basin leak index (sum over HUC-12s of MODIS-bare x wet-soil drainage x soil factor x row-crop area, per row-crop ha) track the measured annual nitrate-N load per row-crop ha, 2016-2025?",
        "index_definition": "per row-crop ha and year: sum_days (bare + eps*(1-bare)) * D * (1 + (m-1)*poorly_drained_share), m = 2.5",
        "pooled_both_basins": corr(V["index_per_ha"], V["load_kg_ha"]),
        "within_basin": {b: corr(V[V.basin == b]["index_per_ha"], V[V.basin == b]["load_kg_ha"]) for b in SITES},
        "alternatives_pooled": {
            "drainage_only_no_cover": corr(V["drain_only_per_ha"], V["load_kg_ha"]),
            "precipitation_only": corr(V["rain_per_ha"], V["load_kg_ha"]),
            "measured_runoff_reference_not_a_predictor": corr(V["runoff_mm"], V["load_kg_ha"]),
        },
        "years": CAL_YEARS,
        "table": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()} for r in rows],
    }
    # partial: does cover add anything beyond drainage? (log-log regression, pooled, basin dummy)
    Xd = np.column_stack([np.ones(len(V)), np.log(V["drain_only_per_ha"]), (V["basin"] == "raccoon").astype(float)])
    yv = np.log(V["load_kg_ha"].to_numpy())
    res_d = yv - Xd @ np.linalg.lstsq(Xd, yv, rcond=None)[0]
    cover_ratio = np.log(V["index_per_ha"] / V["drain_only_per_ha"]).to_numpy()
    res_c = cover_ratio - Xd @ np.linalg.lstsq(Xd, cover_ratio, rcond=None)[0]
    chk["cover_adds_beyond_drainage"] = {
        "test": "partial correlation of log(index/drainage-only) [the cover part] with log(load), controlling for log(drainage-only) and basin",
        **corr(res_c, res_d),
    }
    # eps sensitivity
    sens = {}
    for e in [0.0, 0.15, 0.3, 0.5, 1.0]:
        JHe = (BH + e * (1 - BH)) * DH
        xs = []
        for b in SITES:
            sel = bas == b
            for yi, y in enumerate(CAL_YEARS):
                a = AH[sel, yi]
                xs.append((SOILH[M_C, sel] * JHe[sel][:, yr == y].sum(axis=1) * a).sum() / a.sum())
        sens[str(e)] = corr(xs, V["load_kg_ha"])["pearson"]
    chk["eps_sensitivity_pooled_pearson"] = sens
    # per-area ratio Raccoon / Des Moines
    vr = V.pivot(index="year", columns="basin")
    ratio_idx = vr["index_per_ha"]["raccoon"] / vr["index_per_ha"]["desmoines"]
    ratio_obs = vr["load_kg_ha"]["raccoon"] / vr["load_kg_ha"]["desmoines"]
    chk["per_area_ratio_raccoon_over_desmoines"] = {
        "index_mean": round(float(ratio_idx.mean()), 3), "measured_mean": round(float(ratio_obs.mean()), 3),
        "index_10yr_total": round(float((vr["index_per_ha"]["raccoon"] * sites_area["raccoon"]).sum() / sites_area["raccoon"].sum()
                                       / ((vr["index_per_ha"]["desmoines"] * sites_area["desmoines"]).sum() / sites_area["desmoines"].sum())), 3),
        "measured_10yr_total": round(float(L.loc["raccoon"].loc[CAL_YEARS, "load_kgN"].sum() / sites_area["raccoon"].sum()
                                          / (L.loc["desmoines"].loc[CAL_YEARS, "load_kgN"].sum() / sites_area["desmoines"].sum())), 3),
        "by_year": {int(y): {"index": round(float(ratio_idx[y]), 3), "measured": round(float(ratio_obs[y]), 3)} for y in CAL_YEARS},
        "year_to_year_corr_of_ratios": corr(ratio_idx, ratio_obs),
    }

    # ---------------- HUC-12 outputs
    log("HUC-12 scores")
    kg_h = HUCKG[M_C]                                         # [huc, year] calibrated kg/ha row crop (central)
    contrib = kg_h * AH                                       # kg
    ry = [CAL_YEARS.index(y) for y in RECENT_YEARS]
    spring_fall = np.isin(mo, [3, 4, 5, 6, 9, 10, 11, 12])
    bdw = np.array([(BH[:, (yr == y) & spring_fall] * (DH[:, (yr == y) & spring_fall] >= WET_DAY_MM)).sum(axis=1) for y in RECENT_YEARS]).mean(axis=0)
    hs = pd.DataFrame({"huc12": huc_list, "basin": bas})
    hs["name"] = hs["huc12"].map(huc.set_index("huc12")["name"])
    hs["area_km2"] = area_h
    hs["in_focus"] = hs["huc12"].map(huc.set_index("huc12")["in_focus"]).astype(bool)
    hs["row_crop_share"] = rc.mean(axis=1)
    hs["poorly_drained_share"] = pdh
    hs["bare_days_wet"] = bdw
    hs["modis_filled_share_recent"] = np.array([BHfilled[:, yr == y].mean(axis=1) for y in RECENT_YEARS]).mean(axis=0)
    for yi, y in enumerate(CAL_YEARS):
        hs[f"kgN_ha_{y}"] = kg_h[:, yi]
    hs["kgN_ha_mean"] = kg_h.mean(axis=1)
    hs["lbN_ac_mean"] = hs["kgN_ha_mean"] * KG_HA_TO_LB_AC
    hs["contrib_t_mean"] = contrib.mean(axis=1) / 1000
    for b in SITES:
        sel = hs["basin"] == b
        tot = contrib[sel.to_numpy()].sum(axis=0)             # per year basin total
        hs.loc[sel, "share_of_basin_leak"] = (contrib[sel.to_numpy()] / tot).mean(axis=1)
        hs.loc[sel, "share_of_basin_leak_recent"] = (contrib[sel.to_numpy()][:, ry] / tot[ry]).mean(axis=1)
        hs.loc[sel, "share_of_basin_area"] = hs.loc[sel, "area_km2"] / hs.loc[sel, "area_km2"].sum()
        bm = (kg_h[sel.to_numpy()] * AH[sel.to_numpy()]).sum() / AH[sel.to_numpy()].sum()
        hs.loc[sel, "leak_index"] = hs.loc[sel, "kgN_ha_mean"] / bm      # 1 = basin average per row-crop ha
        hs.loc[sel, "rank"] = hs.loc[sel, "share_of_basin_leak"].rank(ascending=False, method="first").astype(int)
        hs.loc[sel, "n_in_basin"] = int(sel.sum())
    # m-sensitivity of the HUC-12 ranking
    rank_sens = {}
    for mi, m in enumerate(M_GRID):
        sh = []
        for b in SITES:
            sel = bas == b
            c2 = HUCKG[mi][sel] * AH[sel]
            sh.append(pd.Series((c2 / c2.sum(axis=0)).mean(axis=1), index=np.array(huc_list)[sel]))
        sh = pd.concat(sh).reindex(huc_list)
        rank_sens[str(m)] = round(float(stats.spearmanr(sh, hs["share_of_basin_leak"])[0]), 3)
    chk["huc12_share_rank_spearman_vs_central_m"] = rank_sens
    hs["rank"] = hs["rank"].astype(int)
    hs["n_in_basin"] = hs["n_in_basin"].astype(int)
    hs.to_parquet(OUT / "huc12_scores.parquet", compression="zstd", index=False)
    props = {r.huc12: {"huc12": r.huc12, "name": r.name, "basin": r.basin, "area_km2": round(r.area_km2, 1),
                       "row_crop_share": round(r.row_crop_share, 3), "poorly_drained_share": round(r.poorly_drained_share, 3),
                       "bare_days_wet": round(r.bare_days_wet, 1), "leak_index": round(r.leak_index, 3),
                       "share_of_basin_leak": round(r.share_of_basin_leak, 4), "rank": int(r.rank), "in_focus": bool(r.in_focus),
                       "lbN_ac_yr": round(r.lbN_ac_mean, 1), "share_of_basin_leak_recent": round(r.share_of_basin_leak_recent, 4),
                       "n_in_basin": int(r.n_in_basin)}
             for r in hs.itertuples()}
    (OUT / "huc12_props.json").write_text(json.dumps(props, separators=(",", ":")))

    # ---------------- 5. fields
    log("fields: HLS daily bare x drainage x soil")
    fl = pd.read_parquet(PROC / "fields.parquet")
    fy = pd.read_parquet(PROC / "field_year.parquet")
    h = pd.read_parquet(PROC / "hls_field_ts.parquet")
    h = h[h["clear"]].copy()
    h["date"] = pd.to_datetime(h["date"])
    spikes = hls_spike_scenes(h)
    h = h[~h["date"].dt.strftime("%Y-%m-%d").isin(spikes)]
    log("  dropped spike scenes:", spikes)
    fids = list(fl["field_id"])
    fsel = (dates >= "2020-01-01") & (dates <= "2025-12-31")
    fdates = dates[fsel]
    BF = hls_daily(h, fids, fdates)
    fh = np.array([hidx[x] for x in fl["huc12"]])
    BHf = BH[:, fsel][fh]                                   # fallback MODIS (HLS-corrected) of the field's HUC-12
    fallback = np.isnan(BF)
    BF = np.where(fallback, BHf, BF)
    fc = np.array([cidx[c] for c in fl["power_cell_id"]])
    DF = DR[:, fsel][fc]
    JF = (BF + eps * (1 - BF)) * DF                         # [field, day]
    fyr = fdates.year.to_numpy()
    fmo = fdates.month.to_numpy()
    JFy = np.array([JF[:, fyr == y].sum(axis=1) for y in FIELD_YEARS]).T              # [field, fy]
    pf = fl["poorly_share"].astype(float).fillna(fl["poorly_share"].median()).to_numpy()
    SOILF = 1.0 + (M_GRID[:, None] - 1.0) * pf[None, :]                               # [m, field]
    # relative index within HUC-12 and calibrated kg/ha
    REL = np.zeros((len(M_GRID), len(CAL_YEARS), len(fids)))
    for mi in range(len(M_GRID)):
        I = SOILF[mi][:, None] * JFy
        relfy = np.zeros_like(I)
        for hh in np.unique(fh):
            s = fh == hh
            relfy[s] = I[s] / I[s].mean(axis=0, keepdims=True)
        for yi, y in enumerate(CAL_YEARS):
            REL[mi, yi] = relfy[:, FIELD_YEARS.index(y)] if y in FIELD_YEARS else relfy.mean(axis=1)
    KGF = HUCKG[:, fh, :].transpose(0, 2, 1) * REL            # [m, year, field]
    lb_c = KGF[M_C] * KG_HA_TO_LB_AC                          # central, [year, field]
    # Monte Carlo: year-to-year x calibration (s, gap-fill load error) x tile multiplier m
    sd_rel = np.array([[L.loc[(basin_of[huc_list[hh]], y), "load_sd_rel"] for y in CAL_YEARS] for hh in range(len(huc_list))])
    mi_d = rng.integers(0, len(M_GRID), N_DRAWS)
    yi_d = rng.integers(0, len(CAL_YEARS), N_DRAWS)
    s_d = rng.uniform(s_lo, s_hi, N_DRAWS) / s_c
    z_d = rng.standard_normal(N_DRAWS)
    draws = KGF[mi_d, yi_d, :]                                # [draw, field]
    err = 1.0 + z_d[:, None] * sd_rel[fh][:, yi_d].T
    draws = draws * s_d[:, None] * np.clip(err, 0.2, None) * KG_HA_TO_LB_AC
    q = np.quantile(draws, [0.1, 0.5, 0.9], axis=0)
    qf = np.quantile(draws, (np.arange(N_Q) + 0.5) / N_Q, axis=0).T.astype(np.float32)   # [field, N_Q]

    # monthly calendar (2020-2025 averages)
    cal = {}
    rf = RAIN[:, fsel][fc]
    gwf = GW[:, fsel][fc]
    for key in ["bare_frac", "rain_mm", "storm_days", "wetness", "leak", "leak_share"]:
        cal[key] = np.zeros((len(fids), 12))
    ny = len(FIELD_YEARS)
    for m in range(1, 13):
        s = fmo == m
        cal["bare_frac"][:, m - 1] = BF[:, s].mean(axis=1)
        cal["rain_mm"][:, m - 1] = rf[:, s].sum(axis=1) / ny
        cal["storm_days"][:, m - 1] = (rf[:, s] >= STORM_MM).sum(axis=1) / ny
        cal["wetness"][:, m - 1] = gwf[:, s].mean(axis=1)
        cal["leak"][:, m - 1] = JF[:, s].sum(axis=1) / ny
    cal["leak_share"] = cal["leak"] / cal["leak"].sum(axis=1, keepdims=True)
    cal["leak_risk"] = cal["leak"] / cal["leak"].max(axis=1, keepdims=True)
    octmay = np.isin(fmo, [10, 11, 12, 1, 2, 3, 4, 5])
    frac_octmay = JF[:, octmay].sum(axis=1) / JF.sum(axis=1)
    aprjun = np.isin(fmo, [4, 5, 6])
    frac_aprjun = JF[:, aprjun].sum(axis=1) / JF.sum(axis=1)

    # share of the field's leak that falls in crop years (Oct-Sep) of soybean after corn: where rye-before-soy acts
    wy = np.where(fmo >= 10, fyr + 1, fyr)
    fyx = fy.set_index(["field_id", "year"])
    share_cs = np.full(len(fids), np.nan)
    ncs = np.zeros(len(fids), int)
    cyears = [y for y in range(2021, 2026)]                  # complete crop years inside 2020-01..2025-12
    JFwy = np.array([JF[:, wy == y].sum(axis=1) for y in cyears]).T
    seqs = fl["crop_seq"].tolist()
    for i, f in enumerate(fids):
        seq = seqs[i]                                         # 2016..2025
        cs_flags = np.array([seq[y - 2016] == "S" and seq[y - 2017] == "C" for y in cyears])
        ncs[i] = int(cs_flags.sum())
        share_cs[i] = JFwy[i, cs_flags].sum() / JFwy[i].sum()
    # long-run frequency of soybean-after-corn years in the field's own 2016-2025 history (9 transitions)
    freq_cs = np.array([sum(s[k] == "S" and s[k - 1] == "C" for k in range(1, 10)) / 9 for s in seqs])

    # cover years and recent NDVI
    cover_years = {}
    for f, g in fy.groupby("field_id"):
        cover_years[f] = {str(int(r.year)): bool(r.winter_cover) for r in g.itertuples() if r.year <= 2026}
    hmax = h["date"].max()
    hr = h[h["date"] > hmax - pd.DateOffset(months=18)].sort_values("date")
    ndvi_recent = {f: (g["date"].dt.strftime("%Y-%m-%d").tolist(), [round(float(v), 3) for v in g["ndvi"]])
                   for f, g in hr.groupby("field_id", observed=True)}

    letters = {"C": "corn", "S": "soybean", "W": "wheat", "O": "oats/small grain", "H": "hay/alfalfa", "P": "pasture", "R": "other row crop", "X": "other"}
    fs = pd.DataFrame({"field_id": fids, "huc12": fl["huc12"], "lon": fl["lon"], "lat": fl["lat"]})
    fs["seq"] = fl["crop_seq"]
    fs["crop_2025"] = fl["cdl_2025"].map(letters)
    fs["drainage"] = fl["drainagecl"]
    fs["poorly_share"] = pf
    fs["slope_pct"] = fl["slope_pct"].astype(float)
    fs["power_cell_id"] = fl["power_cell_id"]
    for yi, y in enumerate(CAL_YEARS):
        fs[f"lbN_ac_{y}"] = lb_c[yi]
    fs["lbN_ac_mean_central"] = lb_c.mean(axis=0)
    fs["leak_lbN_ac_yr_p10"], fs["leak_lbN_ac_yr_p50"], fs["leak_lbN_ac_yr_p90"] = q
    fs["leak_index"] = fs["lbN_ac_mean_central"] / fs["lbN_ac_mean_central"].mean()     # 1 = focus-area average
    fs["leak_pctile"] = (fs["leak_lbN_ac_yr_p50"].rank(pct=True, method="average") * 100).round().astype(int).clip(0, 100)
    fs["hls_index_rel_huc"] = REL[M_C, CAL_YEARS.index(2025)]
    fs["hls_fallback_share"] = fallback.mean(axis=1)
    fs["frac_leak_oct_may"] = frac_octmay
    fs["frac_leak_apr_jun"] = frac_aprjun
    fs["share_leak_soy_after_corn_cy2021_2025"] = share_cs
    fs["n_soy_after_corn_cy2021_2025"] = ncs
    fs["freq_soy_after_corn_2016_2025"] = freq_cs
    fs["huc_sd_rel_mean"] = sd_rel[fh].mean(axis=1)
    for key in ["bare_frac", "rain_mm", "storm_days", "wetness", "leak_risk", "leak_share"]:
        fs[f"cal_{key}"] = [list(np.round(v, 4)) for v in cal[key]]
    fs["leak_q200"] = list(qf)
    fs["cover_years_json"] = [json.dumps(cover_years.get(f, {})) for f in fids]
    fs["ndvi_dates"] = [ndvi_recent.get(f, ([], []))[0] for f in fids]
    fs["ndvi_vals"] = [ndvi_recent.get(f, ([], []))[1] for f in fids]
    fs["polygon"] = fl["polygon"]
    fs.to_parquet(OUT / "field_scores.parquet", compression="zstd", index=False)

    # fields.geojson
    feats = []
    for r in fs.itertuples():
        ring = [[round(float(x), 5), round(float(y), 5)] for x, y in r.polygon]
        feats.append({"type": "Feature", "properties": {
            "field_id": r.field_id, "huc12": r.huc12, "seq": r.seq, "leak_index": round(r.leak_index, 3),
            "leak_pctile": int(r.leak_pctile), "drainage": r.drainage, "slope_pct": round(r.slope_pct, 2),
            "lbN_ac_yr_p50": round(r.leak_lbN_ac_yr_p50, 1)},
            "geometry": {"type": "Polygon", "coordinates": [ring]}})
    (OUT / "fields.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))

    # field-level checks for the json
    huc_focus = hs[hs["in_focus"]]
    fmean_by_huc = fs.groupby("huc12")["lbN_ac_mean_central"].mean()
    chk.update({
        "drainage_fit": dfit,
        "eps_living_cover_leak_fraction": {"value": round(eps, 3), "source": eps_src},
        "rowcrop_share_of_river_load": {"lo": round(s_lo, 3), "hi": round(s_hi, 3), "central": round(s_c, 3), "note": share_note},
        "tile_multiplier_m": {"grid": M_GRID.tolist(), "central": float(M_GRID[M_C]),
                              "source": "U[1, 4]: 1 = no difference (null); 4 = upper end implied by McIsaac & Hu (2004), cited in David, Drinkwater & McIsaac (2010) J. Environ. Qual. 39:1657-1667: riverine nitrate export = 100% of net N inputs in tile-drained central Illinois vs 25-37% in the non-tiled south (ratio 2.7-4). Our inference, not a number stated by the authors."},
        "modis_to_hls_bias_by_month_subtracted": {str(m + 1): round(float(v), 3) for m, v in enumerate(bias_month)},
        "load_gapfill_cv": cv,
        "calibration": calib,
        "hls_spike_scenes_dropped": spikes,
        "fields": {
            "n": len(fs),
            "lbN_ac_yr_p50_distribution": {k: round(float(v), 1) for k, v in zip(["p5", "p10", "p25", "p50", "p75", "p90", "p95"], np.percentile(fs["leak_lbN_ac_yr_p50"], [5, 10, 25, 50, 75, 90, 95]))},
            "lbN_ac_yr_central_by_year_focus_mean": {int(y): round(float(lb_c[yi].mean()), 1) for yi, y in enumerate(CAL_YEARS)},
            "hls_fallback_share_mean": round(float(fallback.mean()), 4),
            "poorly_vs_well_p50_ratio": round(float(fs[fs.drainage.str.contains("Poorly|Very poorly", regex=True) & ~fs.drainage.str.contains("Somewhat")]["leak_lbN_ac_yr_p50"].median()
                                                   / fs[fs.drainage.isin(["Well drained", "Moderately well drained"])]["leak_lbN_ac_yr_p50"].median()), 3),
            "field_mean_vs_huc12_mean_check_max_abs_rel_diff": round(float(np.max(np.abs(fmean_by_huc / huc_focus.set_index("huc12")["lbN_ac_mean"].reindex(fmean_by_huc.index) - 1))), 4),
            "hls_vs_modis_annual_index_focus": {int(y): round(float(JFy[:, FIELD_YEARS.index(y)].mean() / JHy[[hidx[x] for x in huc_focus["huc12"]], CAL_YEARS.index(y)].mean()), 3) for y in FIELD_YEARS},
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "inputs_pending_refresh": ["hls_field_ts / field_month / field_year (spike-scene fix)", "hls_vs_modis.json (monthly bias)", "cover_huc12_8day (fall 2025 gap)"],
    })
    (OUT / "basin_index_check.json").write_text(json.dumps(chk, indent=1, default=float))

    log(f"done in {time.time() - t0:.0f}s")
    log("validation pooled:", chk["pooled_both_basins"], "within:", {b: chk["within_basin"][b]["pearson"] for b in SITES})
    log("drainage-only pooled:", chk["alternatives_pooled"]["drainage_only_no_cover"]["pearson"], "cover partial:", chk["cover_adds_beyond_drainage"]["pearson"])
    log("ratio:", {k: v for k, v in chk["per_area_ratio_raccoon_over_desmoines"].items() if k != "by_year"})
    for c in calib:
        log("  calib", c["basin"], c["year"], c["load_t"], "t;", c["kgN_ha_rowcrop_from_rowcrop"], "kg/ha; filled", c["filled_share"], "sd", c["load_sd_rel"])
    log("fields p50 distribution:", chk["fields"]["lbN_ac_yr_p50_distribution"])
    log("fields by year:", chk["fields"]["lbN_ac_yr_central_by_year_focus_mean"])


if __name__ == "__main__":
    main()
